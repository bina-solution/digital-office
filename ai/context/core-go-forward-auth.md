# Replacing authentik with a Go forward-auth service (item `core-006`)

Owner-approved 2026-10-09 («כן כן הכל מאושר»). This note is the design and the migration; the service
it describes is in [`platform-base/forward-auth/`](../../platform-base/forward-auth/README.md).

**Status: a PROPOSAL plus a compiled, unit-tested binary. Nothing here is wired.** The edge still
points at authentik. The swap is steps 6–7 below and needs a maintenance window.

---

## 1. What authentik actually does here — measured, not remembered

Everything below was read out of this checkout (branch `hp-dgo`, HEAD `2d9fba9b`) on 2026-10-09.
The numbers are counts from a mechanical scan, and the scan that produced them is named.

### 1.1 The one job the estate uses

`platform-base/traefik/config/authentik-forwardauth.yaml` is the whole contract:

```yaml
forwardAuth:
  address: http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
  trustForwardHeader: true
  authResponseHeaders: [X-authentik-username, -groups, -email, -name, -uid,
                        -jwt, -meta-jwks, -meta-outpost, -meta-provider, -meta-app, -meta-version]
```

It lives in traefik's **file** provider, not on the container's labels, and that is load-bearing: a
label-defined middleware exists only while `authentik-server` is in traefik's docker snapshot, and
traefik's answer to an unresolvable middleware is to **discard the whole router** — measured
2026-07-30, 3,718 router rejections and every gated host 404 while the stack reported healthy.

The middleware is attached by `platform/manager/reconcile.py::routing_labels()`: every router of a
routing entry with `auth: sso` — `-local`, `-http`, `-https`, and `-frame` when the shell frames the
app — gets `middlewares=authentik@file`. `auth` is validated against `("sso","none")` and anything
else is refused outright, because `auth: "basic"` used to resolve to **open**.

The same file is replaced wholesale when `BBOX_SSO=off`, with five static headers
(`X-authentik-username: akadmin`, `-groups: authentik Admins`, …). That is a measurable statement
about what the identity in this estate really is.

### 1.2 The scale

| measure | count | how it was counted |
|---|---|---|
| `auth: sso` routing entries across all manifests | **33** | `routing[].auth == "sso"` in `apps/*/app.json` + `platform-base/*/app.json` |
| manifest files declaring ≥ 1 | **31** | same |
| …of those, installable apps that also carry an `sso{}` block | **24** | `routing[].sso` present |
| routers carrying `authentik@file` in the **base** render (12 apps enabled) | **34**, over **17** distinct hosts | `grep -c authentik@file .generated/routing.override.yml`, after `python3 platform/manager/reconcile.py render` |
| committed blueprint's own providers/applications | **14 + 14** | `platform-base/authentik/blueprints/deployment-apps.yaml` — the base estate this office owns by hand |
| app instances the compiler emits, one provider per host | 1 per host | `render_authentik()`, plus `zzz-generated-apps.yaml` (gitignored) |

The blueprint uses **two** provider models and nothing else: `authentik_providers_proxy.proxyprovider`
(×14, all `mode: forward_single`) and `authentik_core.application` (×14). There is **no** `oauth2`,
`saml`, `ldap` or `source` model anywhere in the blueprints — see §1.6.

### 1.3 The sign-in flow a human takes

1. Browser → `http://<app>.localhost:8080/`. traefik matches `-local` (or `-frame`) → the
   `authentik@file` middleware.
2. traefik calls the outpost at `/outpost.goauthentik.io/auth/traefik`, carrying
   `X-Forwarded-Host`, `X-Forwarded-Uri`, `X-Forwarded-Proto`.
3. No session → **302** to the `auth` host. That host is `auth: none`, `emit_labels: false` — an
   ungated host on purpose, because a login service gated behind its own login is a loop.
4. authentik's Django flow authenticates, sets its own session cookie on `auth.<domain>`, and
   returns the browser to the app host, where step 1 succeeds and traefik copies the five identity
   headers onto the app's request.
5. **The outpost has its own table of hosts and answers 404 for a host it does not know.**
   `platform-base/authentik/outpost-ready.py` is the true readiness probe for exactly this: it asks
   the forward-auth endpoint about each gated host and reads a **302 as "served"**, **404 as "not"**.
   `hooks/refresh` is the repair chain — wait → sentinel re-applies blueprints → restart
   `authentik-server`. The middle remedy exists because of a measured 15-hour outage
   (`authentik-bootstrap-unhealthy-for-fifteen-hours-two-sso-hosts-unserved`); the last one exists
   because an outpost that froze under an older blueprint stays frozen.

The app is framed by the console at `console.localhost/a/<alias>/`, which **reverse-proxies the app
under the console's own origin** — a cross-origin iframe's auth redirect is X-Frame-blocked over
http. So inside a frame the console is the host the middleware gated, and it is the console that
reads the headers (see §1.5). `platform/manager/serve.py` adds `/.dgo/signed-in` (asks the host
whether it is signed in, through `authentik@file`) and `/.dgo/enter` (signs it in) for a host the
shell frames that cannot show its own sign-in.

### 1.4 Where the identity comes from today

`.env`: one user, `AUTHENTIK_BOOTSTRAP_USER=akadmin`. `bootstrap.sh` sets that account's password
from `AUTHENTIK_BOOTSTRAP_PASSWORD` and stays alive as an outpost-readiness sentinel. The blueprints
bind every provider to `default-provider-authorization-implicit-consent` with **no policy bindings**:
any signed-in user reaches every gated app. Data: three volumes (`authentik_media`,
`authentik_templates`, `authentik_postgres_data`), a **dedicated** Postgres instance, and Redis db 1
(non-durable — cache and sessions).

`authentik-google-login` is declared `connections[].required: false` and **nothing in the repo reads
it** (grep: zero consumers of `GOOGLE_LOGIN` / `google-login` outside the manifest).

### 1.5 Every consumer of the capability and of the headers

**The capability graph** (`use: [{capability: identity}]`) says three apps:

| file | strength |
|---|---|
| `apps/my-docs/app.json` | requires |
| `platform-base/console/app.json` | requires |
| `platform-base/traefik/app.json` | wants |

…and `platform-base/authentik/app.json` is the only provider, offering `identity` with ops
`forward-auth, oidc, user-info` and a separate `forward-auth` capability.

**The header contract has twice as many consumers as the capability graph admits.** This is the
finding that matters for a swap, and it is why the enumeration below is by *grep over the header
family*, not by reading manifests:

*Runtime readers of `X-authentik-*` (7):*

| file | what it reads |
|---|---|
| `platform-base/console/app.py:29,80` | username, email, name, groups → `/api/me` |
| `apps/my-docs/app.py:81,93,96` | username, email, name, groups, uid |
| `apps/indox/app/incoming_documents/api/__init__.py:6978-6991` | username, email, groups; `is_admin = "incoming-docs-admin" in groups` |
| `apps/digital-assets/app.py:69` | username (falls back to `"owner"`) |
| `apps/social-list/app.py:87` | username (falls back to `"owner"`) |
| `apps/git/docker-compose.yml:140` | delegates to Forgejo: `REVERSE_PROXY_AUTHENTICATION_USER=X-authentik-username` |
| `apps/bina-ds/docker-compose.yml:46` | delegates to the harness: `DSH_TRUST_PROXY_AUTH_HEADER=X-authentik-username` |

*Producers and rewriters of the family (3):*

| file | what it does |
|---|---|
| `platform-base/traefik/config/authentik-forwardauth.yaml` | the middleware — names all 11 response headers, and the 5 static ones under `BBOX_SSO=off` |
| `platform/manager/serve.py:509-540` | the link door: runs `authentik@file` **first** so a forged `X-authentik-username` is already gone, then writes this office's mapped user |
| `apps/dgo-extend/link-proxy.py:66-70` | the tunnel door: **writes** `x-authentik-username`, **removes** the whole `x-authentik-` family from a peer's request |

**Of those seven readers, five do not declare `use: identity`** — `indox`, `digital-assets`,
`social-list`, `git` and `bina-ds` use the header without the manifest admitting it. A swap planned
from the capability graph would move three apps; the reality is ten runtime files. Per AGENTS.md
rule 8 this is the enumeration a contract change has to be built on — and no gate in
`scripts/refactor/` finds it today: G25 (`capability-use-lint.py`) compares a declared capability
against the *image* a consumer's compose runs, which is the right question for `sql` and the wrong
one for a header. One file proves how far the trust goes: `apps/bina-ds/tools/office-links-selfcheck.py:36`
makes its own request with `headers={"X-authentik-username": "azaria"}` and is answered — nothing in
the estate verifies that identity came from the edge.

*Not runtime — the other 14 of the 24:* `platform-base/console/test_app.py`,
`apps/indox/…/test_facade_routes.py`, `apps/dgo-extend/tests/phase3.py`, `apps/git/{AGENT,README}.md`,
`apps/bina-ds/{README.md,harness/customize.sh,harness/profile/…/office-operations/SKILL.md}`,
`apps/bina-ds/tools/office-links-selfcheck.py`, `apps/archify/diagrams/office-link.architecture.json`,
`apps/project-pln/plans/{dgo-dev,office}.yaml`, and two comment-only mentions that name the family
without reading it (`apps/dgo-extend/firewall.py:56`, `apps/bina-ds/harness/customize.sh:5`).
**24 files in tracked non-`legacy/` code name the family in total; 10 of them are runtime.**

*The one place authentik is reached by ROLE, not by name:* `platform-base/app-management/app.py:795`
walks the enabled manifests for `capabilities[].name == "forward-auth"` and runs that app's `refresh`
hook. **Renaming the app does not break the control plane** — which is what makes a parallel install
possible at all.

*The `.env` surface being retired:* `AUTHENTIK_BASE_URL`, `AUTHENTIK_SECRET_KEY`,
`AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_BOOTSTRAP_{USER,PASSWORD,EMAIL,TOKEN}`, plus
`BBOX_AUTHENTIK_WEB_WORKERS` and `AUTHENTIK_READY_SERVER`.

### 1.6 What an app calls directly: nothing

Searched for `oidc`, `openid`, `userinfo`, `user-info`, `jwks`, `/application/o/` across every
`.py/.js/.yml/.yaml/.json`. **Zero apps configure an authentik OIDC provider or call one.**
The hits are: the `identity` capability's unexercised `required_ops: [forward-auth, oidc, user-info]`,
`X-authentik-jwt`/`-meta-jwks` in the middleware's header list (which **no code reads**),
`apps/supabase/volumes/api/kong.yml`'s own `/auth/v1/.well-known/jwks.json` (Supabase's auth, not
authentik), and `issues/plane-signs-in-twice-when-opened-from-the-console.yaml`, which records that
Plane CE has no OIDC at all (it is a Pro/Business feature).

So `X-authentik-jwt` and the five `X-authentik-meta-*` headers are **produced and never consumed**.
That is what makes it safe for v1 to stop producing them.

### 1.7 What is being removed, in one number

`packaging/OPTIMISATION.md:39,45`: authentik (server, worker, bootstrap, its own postgres) is
**1132 MB across 4 containers** — **24% of the entire platform's memory**, the largest single
consumer, and the only true blocker for a native layer 1. Optimisation phase 2 is exactly this task.

---

## 2. What stays, and what the Go service must implement

**Traefik stays.** The edge, its routers, the file-provider middleware, the `auth: sso` →
`authentik@file` rule in `routing_labels()`, the compile step, and every one of the 33 gated entries
are untouched. Only the *address the middleware dials* changes. That is the point of doing it as
forward-auth: everything upstream of one YAML key is already declarative and already tested.

**The Go service must implement, and nothing else:**

| # | what | why it is unavoidable |
|---|---|---|
| 1 | **the forward-auth endpoint** — `GET/POST /auth/traefik`: `200` + the five identity headers for a valid session; `302` + `Location` to sign in for an anonymous caller; `400` when the return-to is not this office's | This is the contract traefik implements. It is not ours to vary: a 2xx is copied onto the app's request, anything else IS the client's response, verbatim. |
| 2 | **the session cookie** — HMAC-SHA256 over `user\nexpiry`, `HttpOnly`, `SameSite=Lax`, `Secure` **iff** the external URL is https | Cookie-only is what removes the database, the Redis and the second container. The `Secure` rule is a measured trap: the `.localhost` office is plain http, where a `Secure` cookie is never stored and sign-in loops for ever. |
| 3 | **the login form** — `GET/POST /login`, one sentence for a wrong name and a wrong password alike | It is the only screen an anonymous caller reaches. `POST` answers **303** so the browser re-requests the destination as a GET, and the page sets `X-Frame-Options: DENY` + `Cache-Control: no-store`. |
| 4 | **the user store** — read once from a file, held in memory, `pbkdf2-sha256` with the iteration count stored beside each hash, `subtle.ConstantTimeCompare`, and equal work for an unknown name | No database, no ORM, no migrations — and no free username oracle. 210k iterations is ~60 ms; the store is one file, so a line deleted takes effect on the next request because the store is consulted on **every** request, not only at sign-in. |
| 5 | **the header contract** — `X-authentik-username`, `-groups`, `-email`, `-name`, `-uid`, with groups joined by `\|` | These five names are read by seven runtime files (§1.5). `\|` is not a guess: `console/app.py:83` and `indox …/api/__init__.py:6983` both `.split("|")` it. **The six `jwt`/`meta-*` headers are NOT produced** — nothing reads them, and emitting them would be a false claim of a signed token. |
| 6 | **logout** — clears this browser's cookie | Said plainly: it cannot reach a session an app keeps for itself (Plane, n8n and Supabase each have one), and there is no server-side revocation. Ending *every* session is rotating `FORWARD_AUTH_SECRET` and restarting. |
| 7 | **the minimum admin surface** — `GET /whoami` only | Listing, adding or removing users over HTTP would create a **second writer** for the fact "who may sign in". The office already has exactly one (the credential plane), so v1 has none. The users file is written by the bootstrap, from the vault. |
| 8 | **`GET /healthz`** | Liveness only — it touches neither the users file (already in memory) nor the clock, so it cannot fail for a reason unrelated to serving requests and restart a working container. |

**And these four things must not exist in v1, for measured reasons:**

* **an outpost host table** — the whole class of failures in §1.3. `forward-auth` answers for the
  request in front of it and has no table to fall behind. The readiness probe
  (`outpost-ready.py`), the sentinel that applies blueprints, and `hooks/refresh`'s three-remedy
  chain all disappear with it.
* **a blueprint compiler** — `render_authentik()` and `zzz-generated-apps.yaml` (one proxy provider
  per host, plus the two-providers-for-one-host bug it once had) exist only to feed authentik.
* **a provisioning API** — the compiler never talks to the service; a second writer for identity is
  the thing §2.7 refuses.
* **any cache or session store** — the cookie is the session.

---

## 3. What v1 deliberately does NOT do

| not in v1 | why — and what it would cost |
|---|---|
| **An OIDC provider for third-party apps** | **Nothing in this office uses one.** Zero `oauth2`/`saml`/`ldap` provider models in the blueprints, zero apps calling `/userinfo` or `/application/o/` (§1.6). Building an OIDC provider means JWKS endpoints, key rotation, discovery documents and an ID-token verifier — a large, security-critical surface, for **zero current callers**. `X-authentik-jwt` and the five `meta-*` headers are dropped with it, and they are proven dead. If Plane Pro is ever bought, that is the moment to add it, with a caller to test against. |
| **Social login (Google)** | `authentik-google-login` is `required: false` and **nothing reads it** (§1.4). Keeping it means an OAuth client, a redirect-URI registry, a token exchange and a consent screen — for a flow nobody has configured. The vault (`connections`, provider `30-google.yaml`) already keeps Google credentials for the apps that *do* use them, and those are unaffected. |
| **MFA** | There is one account (`akadmin`), and the office's own SSO is the door. MFA belongs at a second factor the owner has chosen and enrolled — a decision for the owner, not a default an agent ships. |
| **A policy/authorization engine** | The blueprints bind every provider to implicit consent with **no policy bindings**: today any signed-in user reaches every gated host. Reproducing that is not a loss, and a policy engine with one user and one policy would be fiction. Group data is still passed through (`X-authentik-groups`, `incoming-docs-admin`), so an app that wants to gate can. |
| **A user-management UI, self-registration, invite flows** | §2.7. |
| **Password reset / email** | No mail path is configured for authentik today. The owner's recovery is `-hash` on the machine. |
| **Managing sessions across devices** | The cookie is the session (§2.2, §2.6). |

**Accepted risks, stated rather than hidden:** a login-CSRF (an attacker with a *valid* account
signing a victim into it) is not defended against beyond `SameSite=Lax`, and is not exploitable with
one account whose password the attacker would have to know. And **a password leaked from the users
file** is protected by PBKDF2 at 210k iterations — better than a bare hash, worse than argon2id,
which is what `x/crypto` would buy at the cost of the stdlib-only, cross-compile-anywhere property
the owner asked for.

---

## 4. Migration, in order — each step with its own rollback

Everything before step 6 is **additive**: it changes no route and touches no running container.
Steps 6–7 are the window.

| # | step | verify | rollback |
|---|---|---|---|
| **0** | **Enumerate, mechanically, before touching anything.** Re-run the §1.5 scan (`grep -rn 'X-authentik\|x-authentik'` over tracked non-`legacy/` code) and record the count. Add the five readers that do **not** declare `use: identity` to the item, and declare the capability on them **first**, in its own commit. | The scan finds the same 24 files / 10 runtime files; `capability-use-lint.py` stays green. | `git revert` that commit. Nothing runs differently. |
| **1** | **Build and unit-test the binary.** `go test ./...` — 14 tests, no stack, no network. | `go test ./...` → `ok` (§5). Keep the output on the item. | Nothing deployed to roll back. |
| **2** | **Publish the image.** Build from `platform-base/forward-auth/Dockerfile`; tag by commit, never `latest`. | `docker run` the image and `-health http://127.0.0.1:9000/healthz`. | Delete the tag. |
| **3** | **Write the parallel config, referenced by nothing.** A second middleware in `platform-base/traefik/config/` — a name no router names yet — dialling `http://forward-auth:9000/auth/traefik`, with `trustForwardHeader: false` and **five** `authResponseHeaders`. | `./scripts/dc config` renders; `grep -c forward-auth@file .generated/routing.override.yml` → **0**; every existing route still resolves. | Delete the file. traefik never loaded it. |
| **4** | **Move the owner's identity into the vault.** Write the users file from `connections` (`project-pln`'s `-hash` precedent: `printf … \| forward-auth -hash`, password never in `argv`). Declare the app in its `app.json` (`auth: none`, its own host **for now** — `auth.<domain>` is authentik's until step 6, and `declared-host-routing-lint` must stay green). It is **disabled** until enabled. | `configFromEnv` refuses without a secret, an external URL or an allowlist; the file has exactly one line. | Nothing enabled, nothing running. |
| **5** | **Dry run, side by side, with no traffic.** Start `forward-auth` next to authentik. From inside `traefik-network`, call `/auth/traefik` with `X-Forwarded-Host: console.localhost` and **no** cookie → expect `302` to the auth host. Then run the §5 smoke script end to end. | The 302 and the 200-with-five-headers below. **Both identity services are up; neither is authoritative.** | `./scripts/dc down forward-auth` — that service only. authentik has never stopped serving. |
| **6** | **⚠ THE WINDOW. Flip the middleware address.** One YAML key: `authentik-forwardauth.yaml`'s `address:` → the new service, `trustForwardHeader: false`, and `authResponseHeaders` reduced from 11 to 5. Take the host `auth.<domain>` from authentik for the new service's router in the same edit. | **Every gated host, measured**: `curl -s -o /dev/null -w '%{http_code}' http://<host>.localhost:8080/` → `302`, for all 17 base hosts / 33 declared entries. Then sign in once and confirm `console.localhost/api/me` returns the owner — which is the *end-to-end* proof that the header contract survives. `apps/indox`'s `is_admin` must read `incoming-docs-admin` from the group header. | **One file, one key.** `git checkout platform-base/traefik/config/authentik-forwardauth.yaml && ./scripts/dc up -d traefik`. authentik is **still running and still holds every user, flow and session** — nothing was stopped or deleted, which is exactly why step 7 waits. |
| **7** | **Stop authentik — after the window, not during it.** `./bbox apps disable authentik`. Its four containers stop; volumes are kept. | `docker ps` shows no `authentik-*`; every gated host still answers `302`; the per-host sweep of step 6 is repeated. | `./bbox apps enable authentik && ./scripts/dc up -d` + restore the middleware line. Its volumes are intact because `data.on_uninstall: keep` — but **re-attach the blueprint inputs before trusting it**, since the compiled blueprint lives in `.generated/`. |
| **8** | **Report the win.** `packaging/OPTIMISATION.md`: −1132 MB, −4 containers, −1 Postgres, 24% of the platform's memory. | `./bbox status` / the machine app's own memory reading, before and after. | n/a |
| **9** | **Retire, later and separately.** `platform-base/authentik/` → `legacy/` (one archive, one gate); drop the six `AUTHENTIK_*` variables from `.env.ex`; `render_authentik()`, `zzz-generated-apps.yaml`, `outpost-ready.py` and `hooks/refresh` go with it. Note that `authentik-bootstrap.override.yml` is in the compiled file list. | `python3 platform/manager/reconcile.py validate` green with authentik absent; G20 (`sso-provider-lint`) re-pointed at the new service. | `git revert`. |

### What must NOT be flipped in production without a maintenance window

**Step 6, and only step 6.** It is the single moment when the identity of every gated host changes
hands, and its failure mode is total: a wrong `address` breaks **all 33 gated entries at once**, and
traefik reports nothing — the browser gets a 502 naming an unreachable auth service (the *good*
case, and the reason the middleware lives in the file provider) or every host serves a bare 404 (the
bad one, measured 2026-07-30). Steps 0–5 are additive and can run any time. Step 7 is reversible
only while authentik's volumes are intact, which is why it waits for a window of its own.

The second thing to be careful about is not a flip but an **assumption**: the six header readers in
§1.5 step 0 are the enumerated blast radius. If that scan is not re-run on the day, the list is a
memory, and a memory is what AGENTS.md rule 8 exists to forbid.

---

## 5. The verification actually run

```
$ cd platform-base/forward-auth
$ gofmt -l .                        # (no output)
$ go build ./...                    # BUILD OK
$ go vet ./...                      # exit 0
$ go test ./...                     # ok   github.com/solomonBoltin/deployment-hacohen/platform-base/forward-auth   5.787s
$ go test -v ./...                  # 14 × --- PASS, then: ok … 5.787s
$ docker build -t forward-auth:proposal .
    #11 [build 5/5] RUN CGO_ENABLED=0 go build … && CGO_ENABLED=0 go test ./...
    #11 98.12 ok  	github.com/…/platform-base/forward-auth	5.988s
    #13 naming to docker.io/library/forward-auth:proposal done
```

The Dockerfile is proven, not just written: the **whole test suite runs inside the build**, so an
image cannot be produced from source that does not pass. Its runtime stage is `scratch` — there is no
shell and no package manager in the shipped artifact.

Cross-compiled from this one host, with the Dockerfile's own flags:

| target | size |
|---|---|
| `linux/amd64` (the deployment) | 7,794,840 B |
| `darwin/arm64` (the MacBook office) | 7,689,666 B |
| `linux/arm64` | 7,471,256 B |
| `windows/amd64` | 8,042,496 B |

Against `packaging/OPTIMISATION.md`'s 1132 MB, the replacement is **~7.8 MB of static binary, one
process, no Postgres, no Redis, no blueprint** — about 0.7% of what it replaces.

14 tests, all passing — the four the owner named (`anonymous → redirect`, `wrong password →
refusal`, `right password → cookie → forward-auth answers with the identity headers`, `tampered
cookie → refusal`) and ten that cover decisions the code makes on its own. One of them found a real
defect while this note was being written: the first version of `allowedHost()` folded the apex into a
dotted allowlist entry, so `rd=http://localhost/` was redirected to instead of refused. The
allowlist now has two spellings (`.example.com` = hosts *under* it; `example.com` = that exact host)
and the test pins both.

Beyond the unit tests, the binary was run and asked the way traefik asks it:

```
GET  /healthz                                    → 200
GET  /auth/traefik   X-Forwarded-Host: console.localhost, no cookie
                                                 → 302  Location: http://auth.localhost/login?rd=http%3A%2F%2Fconsole.localhost%2Fapps%3Fx%3D1
POST /login (wrong password)                     → 401, no Set-Cookie
POST /login (right password)                     → 303  Location: http://console.localhost/apps
                                                        Set-Cookie: dgo_session=…; HttpOnly; SameSite=Lax
GET  /auth/traefik   with that cookie            → 200  X-Authentik-Username: owner
                                                        X-Authentik-Email: owner@localhost
                                                        X-Authentik-Name: Owner
                                                        X-Authentik-Uid: 1
                                                        X-Authentik-Groups: admins|incoming-docs-admin
GET  /auth/traefik   tampered cookie             → 302  (refused, not served)
GET  /auth/traefik   X-Forwarded-Host: evil.example
                                                 → 400, no Location
GET  /whoami         with the cookie             → 200 {"signed_in":true,…}
/forward-auth -health http://127.0.0.1:9000/healthz → exit 0
```

Copyable form — this is the script to re-run at step 5 and again at step 6:

```bash
printf 'a long passphrase\n' | ./forward-auth -hash > /tmp/h
printf 'owner owner@localhost Owner 1 admins,incoming-docs-admin %s\n' "$(cat /tmp/h)" > /tmp/fa/users
FORWARD_AUTH_SECRET="$(openssl rand -hex 32)" FORWARD_AUTH_EXTERNAL_URL=http://auth.localhost \
FORWARD_AUTH_ALLOWED_HOSTS=.localhost FORWARD_AUTH_USERS_FILE=/tmp/fa/users ./forward-auth &

curl -s -o /dev/null -w '%{http_code}\n' localhost:9000/healthz
curl -s -D- -o /dev/null -H 'X-Forwarded-Host: console.localhost' -H 'X-Forwarded-Uri: /apps' \
     localhost:9000/auth/traefik | grep -i '^location'          # expect 302 → /login?rd=…
curl -s -c /tmp/j -o /dev/null -d 'user=owner&password=a long passphrase' localhost:9000/login
curl -s -D- -o /dev/null -b /tmp/j -H 'X-Forwarded-Host: console.localhost' \
     localhost:9000/auth/traefik | grep -i '^x-authentik-'     # expect all five
```

**Gate coverage, and the honest gap.** Every gate that can see these paths was run, and all pass:

```
python3 scripts/refactor/layering-lint.py --strict  → G9  PASS — no base app names a layer-3 app (TOTAL 0)
python3 scripts/refactor/compile-lint.py            → G12 PASS — all 577 first-party Python file(s) compile …
python3 scripts/refactor/ownership-lint.py          → G5  PASS — every service lives in an app; nothing outside
python3 scripts/refactor/healthcheck-lint.py        → G18 PASS — every first-party healthcheck uses a binary its image provides
python3 scripts/refactor/manifest-lint.py           → G73 PASS — OK — 41 manifest(s) valid
python3 scripts/refactor/fresh-clone-lint.py        → G11 PASS — 3563 tracked file(s) scanned
```

G12 (`compile-lint.py`) scans Python only, so it has nothing to say about a Go file, and G25
(`capability-use-lint.py`) compares a capability against a compose *image*, which is not how a header
consumer is found. **There is no gate in `scripts/refactor/` that enumerates consumers of the
`X-authentik-*` header family** — §1.5 is a manual scan, and per AGENTS.md rule 8 a manual scan is
exactly what a contract change must not rest on. Writing that gate is step 0's real deliverable and
is listed as open work below.

---

# 6. Compatibility — the DROP-IN requirement for `core-006`

The owner, 2026-10-09, verbatim: *«כשאתה מחליף את שכבת האבטחה ב‑Go אתה חייב לוודא 100% שהכל נשאר
מאובטח ומנוהל בדיוק באותה צורה כמו עכשיו, ו‑0 גליצ'ים. גם הסיסמאות עצמן והחיבורים צריכים להישאר בדיוק
אותו הדבר, ככה שאם נעדכן גרסה בכל השלושה לשכות הן יישארו מחוברות בלי שום צורך בחיבור מחדש — ואותו
דבר הסיסמאות והסשנים.»*

Read as an engineering contract, that is three things that must survive, and they are not the same
kind of thing:

| # | must survive | how it survives | what it costs |
|---|---|---|---|
| 1 | **the password hashes** | the Go service READS Django's `pbkdf2_sha256$…` as it stands | code (users.go), no data change |
| 2 | **the live sessions** | the Go service READS authentik's `authentik_session` cookie | code (legacy.go) **+** two values handed to it during the window |
| 3 | **the connection bindings** | nothing is migrated — they stay where they are | nothing, and this section proves why |

Everything below was measured on the live office on 2026-10-09, read-only, from inside the running
containers. Every command is written out so it can be re-run on the day; every count is a count, not
an impression.

## 6.1 What authentik actually stores and issues

### 6.1.1 The password column — `authentik_core_user.password`

```
$ docker exec authentik-postgres-hp psql -U authentik -d authentik -c '\d authentik_core_user'
 password             | character varying(128) |           | not null |
 ...
$ docker exec authentik-postgres-hp psql -U authentik -d authentik -t -A -F'|' -c "select username,
    array_length(string_to_array(password,'$'),1) as fields, split_part(password,'$',1) as field1,
    length(split_part(password,'$',2)) as iters_len, length(split_part(password,'$',3)) as salt_len,
    length(split_part(password,'$',4)) as digest_len,
    case when password='' then 'EMPTY' when password like '!%' then 'UNUSABLE' else 'SET' end
  from authentik_core_user order by username;"
AnonymousUser|1|!IUX9S2enEAt0SrveeknjhhAINJ0EaZfmKBGASuwR|0|0|0|UNUSABLE
ak-outpost-f4c31a97268e4ccfa150ec3df47ca76a|1|!bCI6oMAKagkGglT1g7F2kz2Tt7H038YAA2XzOUMy|0|0|0|UNUSABLE
akadmin|4|pbkdf2_sha256|6|22|44|SET
```

Three accounts, and the ONE that is a person carries four fields: first field `pbkdf2_sha256`, second
`720000` (6 characters), third 22 (the salt), fourth 44 (the digest). That is Django's
`PBKDF2PasswordHasher` exactly — `algorithm`, `iterations`, `salt`, `hash` — and the parameters are
Django 5.0's own defaults, read out of the image rather than inferred:

```
$ docker exec authentik-server-hp sh -lc 'grep -n "class PBKDF2PasswordHasher" -A10 \
    /ak-root/venv/lib/python3.12/site-packages/django/contrib/auth/hashers.py'
class PBKDF2PasswordHasher(BasePasswordHasher):
    algorithm = "pbkdf2_sha256"
    iterations = 720000
    digest = hashlib.sha256
$ …grep -n "salt_entropy" …/hashers.py                     → 217:    salt_entropy = 128
$ …grep -n '^RANDOM_STRING_CHARS' …/django/utils/crypto.py → 48: "abc…zABC…Z0123456789"
```

so `salt()` is `ceil(128 / log2(62))` = **22 characters from `[A-Za-z0-9]`** — *not* base64 — and the
digest is `base64.b64encode(...)` **with** padding (32 bytes → 44 characters, ending `=`). The
`!`-prefixed rows are Django's `UNUSABLE_PASSWORD_PREFIX` + 40 characters: the account exists and has
no password at all (both are authentik's own service accounts).

**The three ways it differs from this service's own `pbkdf2-sha256$…`** — each one a silent failure
if it is got wrong, and all three are why `parseHash` has two families and not one:

| | ours | authentik / Django |
|---|---|---|
| scheme | `pbkdf2-sha256` | `pbkdf2_sha256` |
| salt | base64 of 16 random bytes, unpadded | the 22 ASCII characters themselves |
| digest | base64, unpadded (43) | base64, **padded** (44) |
| verification | compare the raw digest, constant time | re-encode the WHOLE entry and compare that |

The salt is the trap: base64-decoding Django's salt produces a different PBKDF2 key and refuses a
correct password. The last row is why re-encoding is the implementation and not "compare the digests".

**One more fact that shortens the window.** `platform-base/authentik/bootstrap.sh:125` re-sets the
bootstrap account's password from `AUTHENTIK_BOOTSTRAP_PASSWORD` on every bring-up:

```sh
ak shell -c "from authentik.core.models import User; import os; u=User.objects.filter(username=os.environ.get('AUTHENTIK_BOOTSTRAP_USER','akadmin')).first(); pw=os.environ.get('AUTHENTIK_BOOTSTRAP_PASSWORD',''); [ (u.set_password(pw), u.save()) for _ in [0] if u and pw ]"
```

so for `akadmin` the plaintext source of truth is `.env`, and the hash is derived from it. For anyone
else — a password changed through authentik's own UI — **the hash is the only copy that exists**.

### 6.1.2 The session — what backs a signed-in browser

```
$ docker exec authentik-server-hp sh -lc 'sed -n "36,45p" /authentik/root/settings.py'
SESSION_COOKIE_NAME = "authentik_session"
SESSION_COOKIE_DOMAIN = CONFIG.get("cookie_domain", None)
$ …grep -n "SIGNING_HASH" /authentik/root/middleware.py
28:SIGNING_HASH = sha512(settings.SECRET_KEY.encode()).hexdigest()
58:            session_payload = decode(key, SIGNING_HASH, algorithms=["HS256"])
125:                    value = encode(payload=payload, key=SIGNING_HASH)
$ …sed -n "112,127p" /authentik/root/middleware.py
                    payload = {
                        "sid": request.session.session_key,
                        "iss": "authentik",
                        "sub": "anonymous",
                        "authenticated": request.user.is_authenticated,
                        "acr": "goauthentik.io/core/default",
                    }
                    if request.user.is_authenticated:
                        payload["sub"] = request.user.uid
```

So the cookie is:

| | |
|---|---|
| **name** | `authentik_session` |
| **value** | a JWT, `HS256`, HMAC key = `sha512(AUTHENTIK_SECRET_KEY).hexdigest()` — a 128-character hex string used *as* the key, so the browser's cookie is unverifiable without that one secret |
| **claims** | `sid` (the session key), `iss: "authentik"`, `sub` (**the user's uid**, or `"anonymous"`), `authenticated`, `acr` |
| **expiry** | **no `exp` claim at all.** `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`, so the browser holds a *session* cookie, and the real lifetime is server-side |
| **what makes it live** | a Django session (in Redis — `session_storage: cache`) plus a row in `authentik_core_authenticatedsession` |

```
$ docker exec authentik-postgres-hp psql -U authentik -d authentik -c '\d authentik_core_authenticatedsession'
 session_key     | character varying(40)     | not null |
 expires         | timestamp with time zone  |          |
 user_id         | integer                   | not null |
$ …-c "select left(session_key,8)||'…', length(session_key), user_id, expires
        from authentik_core_authenticatedsession order by expires desc;"
p57wq3i5…|32|4|2026-10-22 22:29:23.718988+00
7w3cbtxb…|32|4|2026-10-18 18:55:48.79887+00
$ …-c "select count(*) from django_session;"     → 0        (SESSION_ENGINE is cache, not db)
```

Two live sessions, both the owner's, 14 days out. The session data itself is in Redis db 1
(`AUTHENTIK_REDIS__DB=1`, ~194k keys, the outpost's `authentik_proxy_session_*` among them).

**Therefore, and this is the answer to "can it be done without the authentik secret": it cannot.**
The cookie is a signed JWT and the signing key is derived from `AUTHENTIK_SECRET_KEY`; accepting an
unsigned one would mean anyone on the office network can mint
`{"authenticated":true,"sub":<the owner's uid>}` and be let in — an authentication bypass, not a
compatibility convenience. What *is* possible, and is implemented, needs exactly **one** value:
`AUTHENTIK_SECRET_KEY`, which `.env` already holds and which is deleted at step 9 anyway. And
because the JWT has no `exp`, its signature alone cannot say a session is still *live* — so a second
input is required: a **snapshot of `authentik_core_authenticatedsession`**, read once at the window.

**If the owner will not hand over that key, the compatible alternative is already the default** and
needs no new code: the legacy cookie is simply not accepted, the browser meets the sign-in page, and
**the same password works** (§6.1.1). Nothing is reset, nothing is re-authorised, and no app
configuration changes — which is the whole of "no reconnection".

### 6.1.3 The SSO / OIDC bindings

```
$ docker exec authentik-postgres-hp psql -U authentik -d authentik -t -A -F'|' -c "
    select 'proxy_providers', count(*) from authentik_providers_proxy_proxyprovider
    union all select 'oauth2_providers', count(*) from authentik_providers_oauth2_oauth2provider
    union all select 'outpost_bound', count(*) from authentik_outposts_outpost_providers
    union all select 'applications', count(*) from authentik_core_application
    union all select 'tokens', count(*) from authentik_core_token
    union all select 'flows', count(*) from authentik_flows_flow
    union all select 'policy_bindings', count(*) from authentik_policies_policybinding;"
proxy_providers|64
oauth2_providers|64
outpost_bound|25
applications|64
tokens|2
flows|14
policy_bindings|11
$ …-c "select name, mode, external_host, intercept_header_auth, length(cookie_secret)
        from authentik_providers_proxy_proxyprovider p
        join authentik_core_provider c on c.id = p.oauth2provider_ptr_id order by c.name;" | head
Any Concurrency Local Provider|forward_single|http://any-concurrency.localhost|t|32
…64 rows, every one forward_single, every one intercept_header_auth = t, cookie_secret 32 chars…
$ …-c "select name, _config::text from authentik_outposts_outpost;"
authentik Embedded Outpost|{"authentik_host": "http://auth.localhost/"}
```

Three things to read out of that, and one of them contradicts a number in §1.2:

* `oauth2_providers` = 64 is **not** 64 OIDC providers. Both tables have exactly 64 rows because a
  proxy provider *is* an oauth2 provider (Django multi-table inheritance, `oauth2provider_ptr_id`
  primary key). There is still **no standalone OIDC provider in this office** — §1.6 stands.
* **64, not 14.** §1.2 counted the *committed* blueprint's entries; the live estate has grown to 64
  providers and 64 applications, one pair per gated host including every linked office's tiles
  (`… · MacBook Provider`, `… · שרת פיתוח בינה סלושנס Provider`). The blast radius of step 6 is
  therefore **64 hosts' worth of routing**, not 14 — and traefik's `authentik@file` middleware is
  attached by `routing_labels()`, per router, so what actually breaks on a bad flip is still "every
  gated entry at once".
* The 11 policy bindings are **all of them authentik's own defaults** (source enrollment, error
  matching, the password stage); not one names a user, a group, an application or a provider. §3's
  "any signed-in user reaches every gated host, no policy bindings" is measured true, and there is
  no authorization data to migrate.
* Every provider sets `intercept_header_auth: true`, so the outpost ALSO gives each host a
  `authentik_proxy_<hash>` cookie signed with that provider's own 32-character `cookie_secret`.
  **Nothing in the estate reads it**: `grep -rn 'authentik_proxy'` over tracked non-`legacy/` code
  finds two hits, both inside a test *string* in `platform-base/console/test_app.py:84,97`. It is
  not a compatibility requirement, and this is the scan that says so.

`X-authentik-jwt` and the five `X-authentik-meta-*` headers are in the same position — `grep` finds
zero runtime readers. One place *wants* them: `apps/project-pln/plans/office.yaml` (a **plan**, not
code) proposes verifying `X-authentik-jwt` to sign a browser into Plane without a second prompt. If
that plan is ever executed it becomes a real requirement, and it is the only one on the horizon.

## 6.2 The compatibility table — claim by claim

"today" = what the Go service in `platform-base/forward-auth/` did before this change; "must change"
= what this change did. Nothing in the "data migration" column is done by this service.

| # | the claim `core-006` has to meet | what the service did | what must change | kind |
|---|---|---|---|---|
| 1 | an existing password authenticates, with no reset | `parseHash` accepted **only** `pbkdf2-sha256$…` and base64-decoded the salt; an authentik row was refused at load, fatally | both families are parsed; Django's salt is used as its ASCII bytes; the whole entry is re-encoded and compared (Django's own `verify`) | **code** — done |
| 2 | an account with no usable password is not a way in | `!…` would have failed `parseHash` and made the whole file fatal | `!` + 40 is recognised as "no password", loads, never matches, and burns equal work | **code** — done |
| 3 | the logged-in browser is not thrown out | only `dgo_session` was read | `authentik_session` is read: JWT `HS256` verified against `sha512(SECRET_KEY).hexdigest()`, `iss`/`authenticated` checked, resolved to a user by the JWT's `sub` | **code** — done |
| 4 | …and only while that session is genuinely alive | n/a | a snapshot of `authentik_core_authenticatedsession` (`sid username expiry`) gates it; a `sid` outside it — or past its `expires` — is refused | **code + data**: code done; the snapshot is one read-only query at the window |
| 5 | `X-authentik-username/-uid/-email/-name/-groups`, byte for byte | the five names already matched exactly | nothing — pinned by `TestIdentityHeadersAreExactlyTheFiveNames`, which asserts the SET, so a sixth fails too | **nothing** — done |
| 6 | `X-authentik-uid` is the SAME uid an app may have stored | the users file's `<uid>` field was free text; the README's example is literally `1` | `<uid>` must carry **authentik's own uid**: `sha256("<user.id>-<install_id>")`, hex, 64 chars | **data** — one read-only query, §6.3 |
| 7 | `X-authentik-groups` carries the same groups | `,`-separated in the file, `\|`-joined in the header | nothing to change in code; **a group name containing a space cannot be expressed** in a whitespace-separated file, and this office's only group is literally `authentik Admins` | **data / accepted limit** — see §6.3 |
| 8 | the connections and the vault accounts are untouched | — | nothing: the vault (`connections`), `auth: sso` in each `app.json`, `routing_labels()`, and every router are not read or written by this service | **nothing** — by construction |
| 9 | an app must not be re-authorised | — | the outpost's host table (64 providers, 25 bindings) is **retired, not migrated**: forward-auth has no table to fall behind. The same commit edits the middleware: `address` → the new service, `trustForwardHeader` `true` → `false`, `authResponseHeaders` 11 → 5 | **config** — step 6 |
| 10 | the other two offices stay connected | — | they each hold their OWN `authentik_session` cookie and their OWN authentik DB; nothing here crosses a link. A partial rollout is therefore a *per-office* logout at worst, never a cross-office one — but the uid in claim 6 is per-office, because `install_id` is | **data, per office** |

Claim 9 deserves the sentence it implies: **the risky edit is smaller than it looks.** `BBOX_SSO=off`
already proves the estate survives a middleware that returns five static headers, which is exactly
the shape of what replaces the outpost.

## 6.3 What will be copied, and exactly how

Three read-only queries, run **before** the window, on each office. Nothing is written to authentik,
nothing needs it to be running afterwards, and no output below contains a password, a key or a
cookie value.

**(a) The users file — one line per person.** `hash` is copied verbatim; `uid` is authentic's own.

```bash
# the uid the outpost actually sends, and the password column, per active account
docker exec authentik-postgres-hp psql -U authentik -d authentik -t -A -F'|' -c "
  select u.username, u.email, u.name,
         encode(sha256((u.id::text || '-' || (select id from authentik_install_id limit 1))::bytea),'hex'),
         u.password
  from authentik_core_user u where u.is_active and u.type = 'internal' order by u.id;"
```

The `uid` expression is authentik's own `User.uid`
(`authentik/core/models.py`: `sha256(f"{self.id}-{get_unique_identifier()}")`, where
`get_unique_identifier()` is the `authentik_install_id` row). Confirmed against the API, not only
against the source — for `akadmin` both answer `2f3a28eeedbd…` (64 hex characters).

The `password` column is then converted to the users file's six whitespace-separated fields. `-` goes
in the groups field for an account whose group is `authentik Admins` (claim 7) — and the boot line
says out loud how many users authenticate from the authentik family, so the window can watch it.

**(b) The sessions snapshot** — one line per live session, read at the window:

```bash
docker exec authentik-postgres-hp psql -U authentik -d authentik -t -A -F' ' -c "
  select s.session_key, u.username, extract(epoch from s.expires)::bigint
  from authentik_core_authenticatedsession s
  join authentik_core_user u on u.id = s.user_id
  where s.expires > now();" > /etc/forward-auth/legacy-sessions
chmod 600 /etc/forward-auth/legacy-sessions
```

`session_key` is the JWT's own `sid` (`AuthenticatedSession.from_request()` sets
`session_key=request.session.session_key`, which is the same value the middleware puts in `sid`), and
`expires` is authentik's own expiry. **A `sid` the file does not name is refused**, so a snapshot
that is stale or short fails closed — the only safe direction. Handing `session_key` around is not
handing out a credential: a `sid` alone cannot be turned into a cookie, because the cookie needs the
HMAC over it, which needs `AUTHENTIK_SECRET_KEY`.

**(c) The secret.** `AUTHENTIK_SECRET_KEY`, from `.env`, passed as `FORWARD_AUTH_LEGACY_SECRET` for
the length of the migration and removed at step 9. It is not new exposure — it is the same value the
authentik container has held all along, and step 9 deletes it from `.env` anyway.

**What is NOT copied, deliberately:** the 64 providers, the 64 applications, the 25 outpost bindings,
the flows, the 11 default policy bindings, the two tokens, and the per-provider `cookie_secret`s.
They exist to feed a host table and an OIDC/JWKS surface that nothing in this repository reads
(§6.1.3). Retiring them is the point of the swap.

## 6.4 What is proven, and what is not

### Proven offline, on this checkout (`go test ./...`, 28 tests, 2026-10-09)

```
$ cd platform-base/forward-auth
$ gofmt -l .                    # (no output)
$ go build ./...                # BUILD OK
$ go vet ./...                  # exit 0
$ go test ./...                 # ok  github.com/solomonBoltin/deployment-hacohen/platform-base/forward-auth  21.303s
$ go test -v ./... | grep -c '^--- PASS'   → 28
```

The two headline fixtures are **not written by this repository** — they were produced by the same
software the office runs, inside the live image, and pasted in verbatim. A fixture generated by the
code under test can only prove the code agrees with itself:

* **A hash Django itself wrote** verifies here, and a wrong password against it is refused
  (`TestADjangoWrittenRowVerifiesHereItself`). Re-made with:
  `docker exec authentik-server-hp /ak-root/venv/bin/python -c "from django.contrib.auth.hashers import PBKDF2PasswordHasher; h=PBKDF2PasswordHasher(); print(h.encode('<passphrase>', h.salt()))"`
* **A cookie PyJWT minted** — the library `middleware.py` calls — is accepted, answered with the five
  headers, and refused under any other key (`TestAPyJWTWrittenCookieIsAccepted`). Re-made with
  `jwt.encode(payload={…}, key=hashlib.sha512(SECRET.encode()).hexdigest())`.

The other direction was run once, by hand, against the live image, because it needs a container and
the suite must not:

```
# a row written by THIS Go code, verified by Django's own hasher:
$ GO_ROW_SHAPE= [13, 6, 22, 44]
$ DJANGO_VERIFIED_GO_ROW= True
$ DJANGO_REFUSED_WRONG= True
```

and the binary itself, run with the migration configuration and asked the way traefik asks it:

```
$ /tmp/fa-bin   (FORWARD_AUTH_LEGACY_SECRET=…, FORWARD_AUTH_LEGACY_SESSIONS=…)
forward-auth: listening on :9078 · 1 user(s) · http://auth.localhost · cookies plain (http edge) ·
              return-to bounded to .localhost · accepting 1 live authentik session(s) until 2026-10-11T13:28:49Z
forward-auth: 1 of 1 user(s) authenticate from an authentik pbkdf2_sha256 hash, verified as-is; …

GET  /healthz                                                          → 200
GET  /auth/traefik  console.localhost, no cookie                        → 302  Location: http://auth.localhost/login?rd=http%3A%2F%2Fconsole.localhost%2Fapps
GET  /auth/traefik  cookie: authentik_session=<the PyJWT token>        → 200  X-Authentik-Username: akadmin
                                                                              X-Authentik-Uid: 2f3a28eeedbd9305b659e0b8302ce44d3549ce6c2bd9e2b6cbe4a1e0e53a5f11
                                                                              X-Authentik-Email: ci@example.com
                                                                              X-Authentik-Name: authentik-Default-Admin
                                                                              X-Authentik-Groups: admins|incoming-docs-admin
GET  /auth/traefik  the same cookie, last 4 signature chars flipped    → 302  (refused)
GET  /whoami        with the legacy cookie  → 200 {"signed_in":true,"username":"akadmin","uid":"2f3a28ee…"}
POST /login         the SAME password, against the Django row AS-IS    → 303  (a session, minted by this service)
POST /login         a wrong password                                   → 401
```

That last-but-one line is the whole of "no reconnection": the password the owner knows, checked
against the row authentik wrote, signing him in to the new service.

### NOT proven offline — and it can only be proven in the window

Everything below needs the live office, a real browser, or both. None of it is a gap in the code;
it is a gap in what a unit test can reach.

1. **That the edge copies our five headers onto a real request.** The tests assert our response; only
   traefik can prove it copies them. The window's end-to-end check is `console.localhost/api/me`
   returning the owner, which is the console reading exactly those headers (`console/app.py:80`).
2. **That a real browser's `authentik_session` cookie verifies.** The fixture is a real PyJWT token —
   but with a synthetic secret and a synthetic `sid`. The window proves it with a browser that was
   signed in BEFORE the flip, on the first request after it.
3. **`AUTHENTIK_SECRET_KEY` in this office is the one the cookie was signed with** (i.e. that the
   container's env is the same value the browser's cookie came from). One curl proves it.
4. **Which of the 64 providers correspond to enabled routers** in the current `platform.state.yaml`,
   and therefore how many hosts the step-6 sweep must cover. That is a `reconcile.py render` count,
   not a guess, and step 6's sweep is `grep -c authentik@file .generated/routing.override.yml`.
5. **The other two offices.** Each has its own authentik, its own `install_id` (so its own uids) and
   its own cookies. Their migration is this same section re-run there; nothing here can stand in
   for it.
6. **That the per-office uid mapping is right for apps that stored one.** Nothing in this repository
   reads `X-authentik-uid` as an identity key — `grep -rn 'X-authentik-uid|authentik-uid'` over
   `apps/`, `platform-base/` and `platform/` finds four hits: `apps/my-docs/app.py:82` (which
   *forwards* it), the middleware's own two (`-uid` in `authResponseHeaders`, and the static value
   under `BBOX_SSO=off`), and one test string (`apps/dgo-extend/tests/phase3.py:453`). So the risk is
   low — but "low" is not "measured", and the uid is copied exactly so that it cannot matter.

## 6.5 Rollback

**The swap is one file, and authentik is never stopped during it.**

| what | how to undo | how long |
|---|---|---|
| the edge (step 6) | `git checkout platform-base/traefik/config/authentik-forwardauth.yaml && ./scripts/dc up -d traefik` | seconds; authentik is still running and still holds every user, flow and session |
| the Go service | it is a separate container; `./scripts/dc down forward-auth` touches nothing else | seconds |
| the legacy acceptance | unset `FORWARD_AUTH_LEGACY_SECRET` / `FORWARD_AUTH_LEGACY_SESSIONS` and restart the one service — the defaults are "accept nothing" | seconds |
| the users file and the snapshot | they are files; `rm` them. Nothing else reads them | seconds |
| authentik itself (step 7) | `./bbox apps enable authentik && ./scripts/dc up -d`; its volumes are `data.on_uninstall: keep`. Re-attach the blueprint inputs first — the compiled blueprint lives in `.generated/` | minutes |
| `AUTHENTIK_SECRET_KEY` | it stays in `.env` until step 9. **Step 9 must not run while legacy acceptance is on**, or a rollback finds a service whose old cookies can no longer be verified | — |

The one irreversible act is deleting authentik's volumes, and **nothing in this migration asks for
it**. Step 9 (retire the directory) is `git revert`-able; deleting the data is a separate decision
that this note does not make.

## 6.6 The window, in order

Steps 0–5 of §4 are unchanged and additive. Inside the window:

1. **Freeze and export** (§6.3 a–c) on this office: users file, sessions snapshot, secret. `chmod 600`
   both files. Re-run the snapshot immediately before the flip — a session minted after the export
   is not in it, and will be refused (fail-closed, and the person sees a sign-in page, not an error).
2. **Dry run, both services up** (§4 step 5), including the two lines that matter:
   `GET /auth/traefik` with no cookie → `302`; with the token from `TestAPyJWTWrittenCookieIsAccepted`
   and the real `FORWARD_AUTH_LEGACY_SECRET` → `200` + five headers.
3. **Flip the middleware** (§4 step 6): `address`, `trustForwardHeader: false`, `authResponseHeaders`
   11 → 5, and the `auth.<domain>` host moved to the new service in the same edit.
4. **Sweep every gated host**: `curl -s -o /dev/null -w '%{http_code}' http://<host>:8080/` → `302`
   for each. On an office that was signed in, open `console.<domain>/api/me` in the SAME browser that
   was signed in before the flip: it must answer with the owner and with authentik's own uid. That
   single page is claims 1–5 of §6.2 at once.
5. **Watch the two boot lines** from §6.4 and the number of users still on the legacy family.
6. **Only then** §4 step 7 (stop authentik), and only after the sweep.

**The `BBOX_SSO=off` path is unaffected**: it replaces the whole middleware with five static headers
and reads none of this.

## 6.7 Open work this section creates

* **A gate for the header family** — §5's honest gap is unchanged and is now the last item standing
  between `core-006` and rule 8: `grep` found 18 non-`legacy/` files naming the five names, of which
  the runtime readers are the ones §1.5 lists. That enumeration must come from a gate, not from this
  paragraph.
* **The group name with a space.** `authentik Admins` cannot be written into a whitespace-separated
  users file. Options, in order of preference: (a) rename the group in authentik to a token without a
  space before the migration and keep the file format; (b) teach the credential plane to write an
  escaped group field and teach `loadUsers` to read it. (a) is one edit and keeps the format; nothing
  in this repository matches on `authentik Admins` by name today (`console/app.py` only *reports*
  groups), so it is a safe rename — but it is a change to the owner's data and therefore his call,
  recorded rather than taken.
* **`X-authentik-jwt`** — `apps/project-pln/plans/office.yaml` wants it. Until that plan is executed
  the header is dead; the moment it is executed, it is a new requirement on this service.
