# forward-auth — the office's identity service, as one binary

Replaces **authentik** in layers 1–2. Design, the measurement it rests on, and the ordered migration
with a rollback per step: [`ai/context/core-go-forward-auth.md`](../../ai/context/core-go-forward-auth.md).
This file is only *how to run it*.

```bash
go test ./...        # 45 tests, no stack, no Docker, no network (auth_test.go +
                     # compatibility_test.go — the migration's own proof — + handoff_test.go,
                     # the review's F1–F4 with a host-scoped cookie jar walking two app hosts,
                     # login CSRF, sign-out on every host, the limiter; + setup_test.go, first run)
go build .           # one static binary; stdlib only, so there is no go.sum and nothing to fetch
```

## The two things that must survive a swap (`core-006`)

The owner's requirement is that replacing authentik is a **drop-in**: the passwords, the sessions and
the connections stay as they are, so an office that is updated stays connected with nothing to
re-enter. This service reads **authentik's own data** for the first two; the third is unchanged
because nothing here owns it (the vault and the blueprints are untouched).

* **Passwords** — an authentik row (`pbkdf2_sha256$720000$<22 chars>$<padded base64>`, Django's own
  `PBKDF2PasswordHasher`) verifies **as it stands**, and a `!<40 chars>` row means "no usable
  password" and never matches. Both families are read; ours (`pbkdf2-sha256$…`) is the one this
  service writes.
* **Sessions** — an `authentik_session` cookie is accepted while two values are configured
  (`FORWARD_AUTH_LEGACY_SECRET` + `FORWARD_AUTH_LEGACY_SESSIONS`), so a browser signed in before the
  swap is not asked again. With either missing the acceptance is **off**, which is the steady state
  after the migration — and a browser then meets the sign-in page, where **the same password works**.

Both are read-only and both are optional. `platform-base/forward-auth/legacy.go` and the family
comment in `users.go` carry the measurements; the window procedure is §"Migration" of the design note.

## Run it

```bash
# 1. The owner's line. The password is read from stdin, never from argv — argv is in `ps`.
printf '%s\n' 'a long passphrase' | ./forward-auth -hash
# → pbkdf2-sha256$210000$Wv8…$9aQ…

# 2. The users file: name email display uid groups hash. `-` means no groups.
mkdir -p /tmp/fa && cat > /tmp/fa/users <<'EOF'
owner owner@localhost הבעלים 1 admins,incoming-docs-admin pbkdf2-sha256$210000$Wv8…$9aQ…
EOF
chmod 600 /tmp/fa/users

# 3. Run.
FORWARD_AUTH_SECRET="$(openssl rand -hex 32)" \
FORWARD_AUTH_EXTERNAL_URL="http://auth.localhost" \
FORWARD_AUTH_ALLOWED_HOSTS=".localhost" \
FORWARD_AUTH_USERS_FILE=/tmp/fa/users \
./forward-auth
# forward-auth: listening on :9000 · 1 user(s) · http://auth.localhost · cookies plain (http edge) ·
#               return-to bounded to .localhost · authentik cookies NOT accepted
```

During a migration, add the pair below — and nothing else changes. The second value is a snapshot
of authentik's live sessions (one read-only `psql`, in the design note); without it a signature is
accepted but no *live session* can be, and a session authentik retired would keep working here.

```bash
  FORWARD_AUTH_LEGACY_SECRET="$AUTHENTIK_SECRET_KEY" \
  FORWARD_AUTH_LEGACY_SESSIONS=/etc/forward-auth/legacy-sessions \
  ./forward-auth
# … · accepting 1 live authentik session(s) until 2026-10-11T13:28:49Z
# forward-auth: 1 of 1 user(s) authenticate from an authentik pbkdf2_sha256 hash, verified as-is; …
```

Container, from this directory:

```bash
docker build -t forward-auth .
docker run --rm -p 9000:9000 \
  -e FORWARD_AUTH_SECRET="$(openssl rand -hex 32)" \
  -e FORWARD_AUTH_EXTERNAL_URL="http://auth.localhost" \
  -e FORWARD_AUTH_ALLOWED_HOSTS=".localhost" \
  -v /tmp/fa/users:/etc/forward-auth/users:ro \
  forward-auth
```

Cross-compile for any OS from one host — the property the owner asked for, and the reason the module
is stdlib-only and the build is `CGO_ENABLED=0`:

```bash
GOOS=darwin  GOARCH=arm64 CGO_ENABLED=0 go build -o dist/forward-auth-darwin-arm64 .
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -o dist/forward-auth-windows-amd64.exe .
```

| variable | required | default | what it is |
|---|---|---|---|
| `FORWARD_AUTH_SECRET` | **yes**, ≥ 32 bytes | — | the cookie signing key. There is no default: a service that starts without one signs every session with an empty key, and anyone on the office network can then mint a cookie naming the owner. |
| `FORWARD_AUTH_EXTERNAL_URL` | **yes** | — | where a browser reaches this service (`http://auth.localhost`). Never derived from a request — a redirect target built from a header is an open redirect. `https://` here is also what turns the cookie `Secure`. |
| `FORWARD_AUTH_ALLOWED_HOSTS` | **yes** | — | comma-separated. `.example.com` = every host **under** it; `example.com` = that exact host. It bounds every return-to URL. |
| `FORWARD_AUTH_USERS_FILE` | no | `/etc/forward-auth/users` | must load at boot; re-read when it changes (checked at most once a second), and a change that does not load leaves the last good file answering |
| `FORWARD_AUTH_SETUP_FILE` | no | `/etc/forward-auth/setup` | a FRESH office's first-run code, as the hex SHA-256 of the code (never the code). While there is no users file, `/setup?code=<code>` makes the owner once and deletes this file; with neither file the service refuses to start (`setup.go`) |
| `FORWARD_AUTH_LISTEN` | no | `:9000` | a TCP address, or `unix:<absolute path>`: a socket only its owner may open — the phone's native core, where loopback is shared by every app (DGO-1090). A socket a dead process left is replaced; one a live process answers on, and a file that is not a socket, are refused |
| `FORWARD_AUTH_EDGE_TOKEN` | no | — | only on a phone's machine, behind its native core (DGO-1090): ≥ 32 bytes, made at each boot and given to the machine outside its network. It never travels: the core's edge signs each request it sends the machine (`X-DGO-Edge-At`, `-Nonce`, `-Sig`: HMAC-SHA256 over when, the nonce, method, host, URI and identity), and a request signed for itself, within a minute, once, is the core's edge's, which has asked the core's own forward-auth already: its `X-authentik-*` are taken as they came. `/edge-proof?nonce=` proves to the core that this machine holds it. Without a good signature — another app that reached the forwarded port — nothing of a request's identity is taken. |
| `FORWARD_AUTH_SESSION_TTL` | no | `336h` | 14 days, authentik's own session length |
| `FORWARD_AUTH_COOKIE_DOMAIN` | no | — | set only if the session must span subdomains |
| `FORWARD_AUTH_LEGACY_SECRET` | no | — | authentik's `AUTHENTIK_SECRET_KEY`, during a migration only. The HMAC key is derived from it exactly as authentik does (`sha512(secret).hexdigest()`), so the value that moves is the one `.env` already names. **Both-or-neither with the next row.** |
| `FORWARD_AUTH_LEGACY_SESSIONS` | no | — | path to the snapshot of authentik's live sessions: `<sid> <username> <expiry-unix>`, one per line. Read once, at boot; a session it does not name is refused, so a stale snapshot fails closed. |

## Endpoints

| path | what it answers |
|---|---|
| `GET /auth/traefik` | **traefik's forwardAuth contract.** `200` + the five `X-authentik-*` identity headers for a signed-in caller; `302` to `/login?rd=…` for an anonymous one; `400` when the return-to is a host this office does not serve. A caller's session may come from this service's cookie or, during a migration, from authentik's — the answer is identical either way. A request with no session but a good `dgo_code` for its host gets `302` to the same URL without the code, **with this host's own cookie** (the per-host hand-off, `handoff.go`: a `.localhost` browser never shares one cookie across hosts). |
| `GET`/`POST /login` | the sign-in form. A right password, or a `GET` from a browser already signed in here, answers `303` to `rd` with a one-time `dgo_code` for `rd`'s host (60 s, single use, bound to the app host's `dgo_state` cookie by its hash `st`, so a code planted in another browser is refused). Five failures per address, or per name at an address, block that key for 60 s, doubling up to an hour, attempts counted while they run: `429` + `Retry-After`, the right password included (`limit.go`). A stranger's failures do not lock the owner out at his own address. Each sign-in, failure, block, hand-off and sign-out is one log line — the name and the address, never a password. |
| `GET`/`POST /setup` | a fresh office only: with the first-run code, the form that makes the owner (a name, a password of 12+ characters), writes the users file atomically, spends the code and signs the browser in. Without the code, a page that says to open the device's link; once a user exists, `404`. |
| `GET /logout` | clears this browser's session cookie, and refuses every session of this person minted before now on every host (each app host holds its own cookie) — in memory, so a restart forgets it |
| `GET /whoami` | the caller's own identity as JSON, or `401 {"signed_in":false}`. **The whole admin surface** — see the design note for why there is no user-management API. |
| `GET /healthz` | `ok`. Used by the image's `HEALTHCHECK` through the binary's own `-health` flag, because a `scratch` image has no `wget`. |

## Known limits, said once

* **An edge that forwards every client from one address** (a VM's or Docker's userland port-forward —
  the phone's and the Mac's :8080) makes the per-address limit one limit for everybody behind it: a
  stranger on the same network can block a name at that address for a while. The phone has one person
  on it; on a shared network, prefer an edge that sees real client addresses.
* **traefik's access log** records request URLs, so a `dgo_code` and the first-run `code` appear in it.
  A `dgo_code` is single-use and good only in the browser that started its round trip; the first-run
  code is printed to the same machine's console anyway. Whoever reads that log is root on the office.
* **Sign-out is in memory**: a restart forgets it, and sessions it refused come back until they expire.
  Rotating `FORWARD_AUTH_SECRET` ends every session for good.
* **A service on the office's network** can call `forward-auth:9078` directly with any `X-Forwarded-For`.

## Wiring it into the edge

Not this file's job, and **not done**: the middleware in `platform-base/traefik/config/` still points
at authentik. The swap and its rollback are steps 6–7 of the design note; nothing in this directory
changes the running office on its own.
