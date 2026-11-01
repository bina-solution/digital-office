# forward-auth — the office's identity service, as one binary

Replaces **authentik** in layers 1–2. Design, the measurement it rests on, and the ordered migration
with a rollback per step: [`ai/context/core-go-forward-auth.md`](../../ai/context/core-go-forward-auth.md).
This file is only *how to run it*.

```bash
go test ./...        # 28 tests, no stack, no Docker, no network (auth_test.go +
                     # compatibility_test.go — the migration's own proof)
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
| `FORWARD_AUTH_USERS_FILE` | no | `/etc/forward-auth/users` | read once, at boot |
| `FORWARD_AUTH_LISTEN` | no | `:9000` | |
| `FORWARD_AUTH_SESSION_TTL` | no | `12h` | |
| `FORWARD_AUTH_COOKIE_DOMAIN` | no | — | set only if the session must span subdomains |
| `FORWARD_AUTH_LEGACY_SECRET` | no | — | authentik's `AUTHENTIK_SECRET_KEY`, during a migration only. The HMAC key is derived from it exactly as authentik does (`sha512(secret).hexdigest()`), so the value that moves is the one `.env` already names. **Both-or-neither with the next row.** |
| `FORWARD_AUTH_LEGACY_SESSIONS` | no | — | path to the snapshot of authentik's live sessions: `<sid> <username> <expiry-unix>`, one per line. Read once, at boot; a session it does not name is refused, so a stale snapshot fails closed. |

## Endpoints

| path | what it answers |
|---|---|
| `GET /auth/traefik` | **traefik's forwardAuth contract.** `200` + the five `X-authentik-*` identity headers for a signed-in caller; `302` to `/login?rd=…` for an anonymous one; `400` when the return-to is a host this office does not serve. A caller's session may come from this service's cookie or, during a migration, from authentik's — the answer is identical either way. |
| `GET`/`POST /login` | the sign-in form |
| `GET /logout` | clears this browser's session cookie |
| `GET /whoami` | the caller's own identity as JSON, or `401 {"signed_in":false}`. **The whole admin surface** — see the design note for why there is no user-management API. |
| `GET /healthz` | `ok`. Used by the image's `HEALTHCHECK` through the binary's own `-health` flag, because a `scratch` image has no `wget`. |

## Wiring it into the edge

Not this file's job, and **not done**: the middleware in `platform-base/traefik/config/` still points
at authentik. The swap and its rollback are steps 6–7 of the design note; nothing in this directory
changes the running office on its own.
