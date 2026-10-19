# connections — the credential plane

The single place for **every** secret/connection in deployment-hacohen. One declarative catalog
describes each; the service resolves values in a fixed order and verifies them with live probes:

```
vault store  →  .env seed (friction-free first boot)  →  install-wizard prompt (ask only the gaps)
```

Runs as a normal BFF on `traefik-network`, behind Authentik SSO, at `connections.localhost` /
`${CONNECTIONS_BASE_URL}`. Verified live against the running stack: **50 connections**, resolve chain
+ real health probes (HTTP/TCP/redis), with the only two install-blockers being the genuine human
steps — Google OAuth consent and the WhatsApp QR scan.

## Declarative layers (git = source of truth)
- `providers/*.yaml` — the **catalog**: one entry per connection, with `kind`
  (`text-secret | password | app-password | oauth-client | oauth-grant | sa-key | qr-session |
  derived | cert | config`), the `env` key that seeds it, its `consumers`, a live `probe`, the
  `wizard` behaviour, and a `now:` field documenting **exactly how it is implemented today**.
- `manifests/*.yaml` — what each **service requires** (generalizes n8n's `credential_overrides`);
  the union drives the install wizard + fail-fast boot + dependency graph.

Adding a connection to any service in the world = adding one catalog entry. No code.

## Interfaces
| | |
|---|---|
| **UI** | `GET /` — grouped dashboard (status pill · source badge · consumers · "how it works now") |
| **API** | `GET /api/connections`, `POST /api/resolve/<id>`, `POST /api/set/<id>`, `GET /api/manifest`, `GET /healthz` |
| **Broker** | `POST /api/broker/lease`, `POST /api/broker/token` → `GET /api/broker/redeem/<t>`, `GET /api/broker/whoami`, `GET /api/broker/audit`, `GET /api/broker/policy` |
| **CLI** | `python cli.py list [--group G] [--blockers] · get <id> · set <id> <val> · health · manifest` |

## The broker — apps stop holding standing secrets

Before this, six apps held standing plaintext credentials as env vars (`indox` alone carried
google-workspace-grant, gemini-key, gmail-app-password, supabase-service-key, redis-password,
n8n-encryption-key) and this service handed `GET /api/export-all?format=env` — **every secret in the
estate** — to anyone who could open a socket to it. One compromised app was every credential it
held, permanently and silently; one SSRF was the whole estate.

Flatpak portals, macOS Powerbox and Vault+SPIFFE converged on the same answer, and it is the one
implemented here:

| Property | How |
|---|---|
| **Broker out of process** | The caller is named from OUTSIDE the request — `identity.py` maps the connection's source address to a container over the Docker Engine API, then to its `com.docker.compose.service` label. Nothing the caller *says* decides who it is. |
| **Narrow capability, not the standing secret** | A caller receives only the connections its own `app.json` `connections[]` declares. Undeclared ids are refused **by name**, never silently dropped. `POST /api/broker/token` mints a single-use capability that expires in 90s. |
| **Every grant logged** | Append-only, fsync'd JSONL beside the vault (`data/grants.jsonl`), readable at `GET /api/broker/audit`. The `flatpak permissions` equivalent: who was granted what, when, allowed or refused. |
| **Revocable** | `POST /api/broker/revoke` (loopback) drops every live token; restarting the broker revokes them all. |

### Identity — two factors, and what they do *not* prove
1. **Network position** — the source IP, mapped to a running container via the docker socket.
2. **Proof of container** — the caller reads its own 64-hex container id from `/proc/self/mountinfo`
   and sends it as `X-Conn-Container`. The broker refuses unless that container actually holds the
   source address. A container cannot learn *another* container's id without a docker socket of its
   own, so this is a 256-bit value the attacker must also possess.

> ⚠ **A source IP on a shared docker bridge is not unforgeable.** Containers keep `NET_RAW`, so a
> hostile neighbour can ARP-poison and complete a handshake from a spoofed address. That is exactly
> why factor 2 exists and why an ip-only identification is reported as `method: "ip"` rather than as
> proof. Unforgeable workload identity needs mTLS with per-workload certs (SPIFFE); this is the
> strongest thing available here without a PKI, and calling it more than that would be the dangerous
> part.

> ⚠ **The docker socket in this container is host root.** `identity.py` issues `GET` only and never
> `POST`, but `:ro` on a socket restricts the *file*, not the API — the restraint is our code, not
> the kernel. Point `DOCKER_SOCK` at a read-only socket proxy where one exists.

> ⚠ **The container table is cached for `CONN_IDENTITY_CACHE_TTL` (default 2s).** A cached row may
> already be wrong in one direction that matters: a container dies, docker later hands its address to
> a different service, and until the TTL expires an *ip-only* lookup would name the dead container's
> service. Presenting a container id closes this (the id is re-checked against the live address set);
> two seconds is short enough that the attacker must win a recycling race it does not control.

### What this does **not** cover yet
- `GET /api/instances/<id>/secret` — the per-account OAuth grants — is identified and **logged**, but
  not policy-gated: instances carry no manifest declaration to check against, and `drive` reads them
  on every op. Gating them needs a per-protocol claim in `app.json` first.
- Five apps (`indox`, `apitools`, `mail`, `my-docs`, `chat`) still hold standing
  plaintext env. Each needs its own `broker` block; `drive` is the worked example.
- `CONN_BROKER_MODE` defaults to `warn`, so a caller the broker cannot identify **at all** is still
  served. That is the phase-1 setting, not the destination.

### Modes — `CONN_BROKER_MODE`
Every consumer boots by calling this service, so the rollout is staged (security-plan-2026, Domain 3):

| Mode | An **unidentified** caller | An **identified** caller |
|---|---|---|
| `warn` *(default)* | served, and logged with `unidentified: true` | full policy |
| `enforce` | **refused** | full policy |
| `off` | served | policy skipped (escape hatch, still logged) |

"Full policy" is enforced in `warn` too — an identified app can never obtain another app's secrets,
or one its manifest does not declare. A warn mode that let `indox` ask for `drive`'s secrets would be
theatre. Flip to `enforce` when `GET /api/broker/audit` shows no `unidentified` grants.

`GET /api/export-all` is not policy-checked, it is **closed**: loopback only, in every mode but
`off`. It is the final step of the documented kill chain and nothing calls it over the network.

### Migrating an app (one block in its own `app.json`)
```json
"broker": {
  "service": "drive",
  "blank_env": ["SUPABASE_DB_PASSWORD", "SUPABASE_SERVICE_KEY"],
  "entrypoint": ["sh","/inject.sh","sh","-c","exec gunicorn -w 2 -b 0.0.0.0:8975 app:app"]
}
```
`reconcile.py render` compiles every such block into `.generated/connections.override.yml` and adds
it to the canonical `-f` list. An app **without** the block keeps reading `.env` exactly as before —
the migration is per-app, reversible, and costs un-migrated apps nothing.

## Secret-zero & safety
- Vault is encrypted at rest (Fernet); exactly **one** root key (`CONNECTIONS_ROOT_KEY`) unlocks it.
- The API/UI/CLI return only **masked** values + a source badge — never raw secrets.
- `derived` connections (Supabase anon/service keys, GlitchTip DSNs) are recomputed, never asked.

## Run it (against the live stack)
```bash
docker compose --env-file .env -f development/connections/docker-compose.yml up -d --build connections
# UI:  http://connections.localhost      API: /api/connections      CLI: docker exec connections-ci python cli.py list
```

## The injector — make a consumer run off connections (proven)

`inject.sh` is an entrypoint shim: at boot it pulls a service's required secrets from
`/api/export/<service>`, exports them, then execs the real command — so the service reads its
secrets from connections, not raw `.env`. Adopt it per service with a compose override:

```yaml
# <service>/inject.override.yml
services:
  any-concurrency:
    volumes: [ "../../development/connections/inject.sh:/inject.sh:ro" ]
    environment: [ "CONN_URL=http://connections:8990", "CONN_SERVICE=any-concurrency" ]
    entrypoint: ["sh","/inject.sh","sh","-c",
      "export PG_PASSWORD=\"$POSTGRES_PASSWORD\"; export REDIS_URL=\"redis://:$REDIS_PASSWORD@redis:6379/0\"; exec uvicorn app:app --host 0.0.0.0 --port 8080"]
```

**Verified:** `any-concurrency` run with **zero secrets in its env** connected to Postgres
(`n8n: true`) and Redis (`available: true`) using `POSTGRES_PASSWORD` + `REDIS_PASSWORD` sourced
entirely from connections. The per-service `export …=$CANONICAL` line maps connections' canonical
names to whatever env vars the app expects.

## Backends it will delegate to (production hardening)
- text/password/rotation → **Infisical** (swap the local Fernet file)
- `oauth-grant` → a **Nango-shaped broker** (own the Google client; run consent; store+refresh tokens)
- `qr-session` → the **Baileys** pairing module (render the QR here; mirror `auth_info` into the vault)
