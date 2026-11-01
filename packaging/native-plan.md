# BinaOS native — the plan to become our own Docker Desktop

The target, as decided: **one executable per OS, dockerd embedded, layers 1–2 running as native
binaries, layer 3 accepting BOTH docker-compose apps and native apps.** Supabase leaves layer 1;
only the database stays. Everything keeps working exactly as it does today, declaratively.

This document is the study of every service, the architecture that makes it cheap instead of
expensive, and the migration path where each phase is shippable on its own.

---

## D1 — The decision that collapses the cost: one userland, not three

The naive reading of "native binaries on every OS" is: build postgres, redis, traefik, n8n and our
16 services for Windows, macOS and Linux — **6 build targets** (3 OS × 2 arch), three service
supervisors (systemd / Windows services / launchd), three sets of path, signal and permission
semantics. That is the months-long version, and it is the wrong reading.

**Look at what Docker Desktop actually is:** a thin host shell (UI, tray, port forwarding,
lifecycle) plus **one Linux guest** where everything real happens. The host app never runs the
engine; it runs the VM that runs the engine. That is the whole trick, and it is copyable:

```
BinaOS.exe / BinaOS.app / binaos (linux)
 ├─ host shell        tray icon, start/stop, port forwarding, first-run import   (thin, per-OS)
 └─ ONE Linux guest   systemd
     ├─ layer 1–2     native processes under systemd — NO images, NO containers
     │                traefik · postgres · redis · zitadel/authelia · n8n · our 16 services
     ├─ dockerd       the embedded engine (78 MB static, Apache-2.0) — exists FOR layer 3
     └─ layer 3       container apps (docker-compose, unchanged) + native apps (systemd units)
```

- **Windows**: the guest is our WSL2 distro — already designed and largely built
  ([windows.md](windows.md)). `wsl --import` from stdin, keepalive task, `localhost` forwarding.
- **macOS**: the guest is our VZ VM — already designed ([macos.md](macos.md)). vfkit (Apache-2.0)
  spares us the Swift host app.
- **Linux**: two options, decided below (D3).

**Consequence: the build matrix is `linux/amd64` + `linux/arm64`, full stop.** "Native" means
native *processes in the guest* — no image layers, no container runtime in the path, direct
syscalls — not "compiled for Windows". The RAM and disk wins are identical; the engineering cost
drops by roughly two thirds. And because the guest rootfs is ours, services install from ordinary
apt packages at rootfs-build time — no static-linking heroics.

Docker Desktop for Linux itself runs a VM for exactly this parity reason. We get to choose.

## D2 — The engine is a platform capability

dockerd stops being the thing the platform runs ON and becomes a capability the platform
PROVIDES — for layer 3:

```json
platform-base/container-engine/app.json:
  { "id": "container-engine", "layer": 1, "kind": "service",
    "capabilities": [{ "name": "container-runtime" }] }
```

Every layer-3 container app gets `use: [{"capability": "container-runtime", "strength": "requires"}]`
added by the compiler automatically (its manifest declares `compose:`, which implies it). Source:
the verified 78 MB static tgz — `dockerd`, `containerd`, `runc`, `docker`, `docker-proxy` —
Apache-2.0, redistributable, and pinned to **28.5.2** (Docker 29 breaks traefik v3.3 silently;
see [linux.md](linux.md)).

## D3 — Linux: same guest, no VM

On Linux the host already has a kernel, so a VM is waste. But "install 20 services on the
customer's unknown distro" reintroduces everything containers solved. The answer between those:

**Ship the SAME guest rootfs and run it under `systemd-nspawn`** (part of systemd, present
everywhere). One userland everywhere, byte-identical to the Windows/macOS guest, no Docker images
involved, and the host stays clean. dockerd runs inside the nspawn container with a bind-mounted
data root. Fallback for hosts without systemd-nspawn: chroot + our own supervision, or documented
"bring your own Docker" mode (the current `.run` behavior).

This makes the release pipeline literally one artifact family: `rootfs.tar.gz` consumed by
`wsl --import` (Windows), by the VZ disk builder (macOS), and by nspawn (Linux).

---

## The service-by-service study

From the live inventory (29 images, 38 services). **Bold** = decision, not observation.

### Layer 1 — chassis

| Service | Today | Native path | Risk |
|---|---|---|---|
| traefik | `traefik:v3.3` image | Single Go binary, official release. Config unchanged (static flags + docker provider for L3 + **file provider for native services** — see "routing" below) | LOW. Must move ≥ v3.6.2 anyway (Docker 29) |
| redis | `redis:7-alpine` | `apt install redis-server` in rootfs. Same conf | LOW |
| supabase-db | `supabase/postgres:15.8.1.085` | **Replaced by vanilla `postgresql-17`** (apt) as the new layer-1 `postgres` app — see supabase section | MED: data migration 15→17, role/extension re-creation |
| authentik (+its postgres) | 3 containers + DB, **no non-Docker install exists** | **Replace.** Two candidates, decision required — see below | **HIGH — the long pole** |
| connections | our Flask service (BUILD) | Python under systemd. Ours; trivial | LOW |
| app-management | our Flask service (BUILD) | Python under systemd. Gains: writes systemd units as well as compose | LOW-MED (it grows the native-lifecycle arm) |
| container-engine | — (new) | dockerd 28.5.2 static, systemd unit | LOW (already proven on WSL) |

### Layer 2 — base apps

| Service | Today | Native path | Risk |
|---|---|---|---|
| n8n + 2 workers | BUILD image ×3 + `n8nio/runners` ×3 | `npm i -g n8n@2.17.0` in rootfs; main + workers as systemd units; **task runners in internal mode** (n8n supports child-process runners — kills 3 sidecar containers) | MED: runner mode change needs the E2E suites to pass |
| n8n-postgres | `postgres:17` | **Consolidate into the one layer-1 postgres cluster** as database `n8n` | MED: dump/restore migration |
| console, notifications, machine, any-concurrency | our BUILDs | Node/Python under systemd | LOW |
| glitchtip (+postgres+valkey) | 5 containers, Django, Docker-only upstream | **Demote to gallery as a container app.** Nothing `requires` error-tracking — n8n and notifications only `wants` it. Not worth fighting Django deployment for an optional tool | LOW (it just moves) |
| bina-ui | build-time library, no container | unchanged | — |
| indox-demo-docs | `caddy:2-alpine` | caddy binary or a `python -m http.server` unit; demo-only | LOW |

### Layer 3 — stays container-first, gains native as an option

apitools, drive, mail, indox, my-docs, whatsapp, browser42, ollama, openhands, portainer,
redisinsight, supabase-studio, hello-bina — **all unchanged, all keep running on compose** against
the embedded engine. First-party ones may migrate to native later, one at a time, for RAM — never
as a precondition.

**Security rule that falls out:** a native app has no isolation. Third-party gallery apps stay
container-only; `runtime: native` is reserved for first-party/trusted manifests, enforced by the
compiler (a gallery-index app declaring native is a validation error).

---

## The identity replacement — the one genuinely hard thing

authentik provides two capabilities: `identity` (OIDC, used by console and my-docs) and
`forward-auth` (traefik middleware protecting ~31 routes). Whatever replaces it must provide both.

| | **Authelia** | **Zitadel** |
|---|---|---|
| Form | one Go binary + config file | one Go binary + postgres |
| forward-auth | **native, purpose-built** (`/api/authz/forward-auth`) | needs a companion (oauth2-proxy or traefik OIDC plugin) |
| OIDC provider | yes (sufficient for console/my-docs) | yes, richer (orgs, projects, actions) |
| Users/admin UI | file/LDAP backend, minimal UI | full admin UI, closest to authentik's feel |
| Fit here | fewer moving parts, exactly our two capabilities | more product, more surface |

**Recommendation: Authelia** — it is the minimal correct shape for exactly the two capabilities the
graph declares, and forward-auth without a second component matters when every route depends on it.
Zitadel is the right answer only if multi-tenant orgs/customer-facing login portals are on the
roadmap. **This is the decision to confirm before phase C starts.**

Migration is mechanical but wide: the authentik blueprint (`deployment-apps.yaml`) declares every
SSO app; the equivalent Authelia config is generated from the same routing data the compiler
already owns — `sso:` blocks in app.json manifests. The compiler becomes the source of truth for
identity config the same way it already is for routing. G8 (registry drift) extends to cover it.

---

## Supabase decomposition (as decided)

Today `supabase` (L1) = db + rest + storage + kong, providing `sql` + `object-storage` + `data-api`.

**After:**

```
platform-base/postgres/        L1, provides sql — vanilla postgresql-17, native, ONE cluster
                               databases: platform, n8n, authelia (as needed)
apps/supabase/                 L3 GALLERY, container app
                               services: rest (postgrest) + storage + kong (or kong dropped — below)
                               provides: object-storage, data-api
                               install hook: creates supabase roles/schemas in the L1 cluster
apps/supabase-studio/          already in gallery (done earlier) — gains a dependency on apps/supabase
```

**kong can very likely be dropped entirely, not moved:** its verified in-tree role is routing
`SUPABASE_BASE_URL` to rest/storage with key-auth. Traefik already does path routing and the
JWT gate can be traefik middleware. One less OpenResty stack. Decide during phase B with the
routes in front of us.

**⚠️ An undeclared dependency this study surfaced — must be fixed regardless:** nothing declares
`use: object-storage`, yet the n8n "drive api - local" workflows read/write supabase-storage via
kong, and `drive.localhost` file links route to the public bucket (documented in the supabase
compose itself). If supabase moves to the gallery and is not enabled, **drive-local file serving
breaks silently.** Fix: `drive`'s manifest declares `object-storage (requires)` for the
`drive_local` protocol — then the capability graph itself tells the operator "enable supabase" at
plan time instead of failing at runtime. This is exactly the class of bug the graph exists to
catch; today it can't, because the edge is undeclared.

**Data migration:** existing `supabase_db_data` is PG 15.8 with supabase-patched roles; n8n's
volume is PG 17. Consolidation = `pg_dump` per database → restore into the new cluster, scripted
in the postgres app's install hook, gated by a row-count comparison. Fresh installs skip it.

---

## What the manifest and compiler change — and what does not

An app declares how it runs (default `container`, so **every existing manifest is valid
unchanged**):

```json
"runtime": {
  "kind": "native",
  "exec": "/opt/binaos/apps/<id>/bin/start",
  "env_from": "connections",
  "health": { "http": "http://127.0.0.1:8970/health" },
  "user": "binaos-<id>"
}
```

`reconcile.py` today emits one lane: `.generated/compose.yml` + overrides. It gains a second:

```
.generated/
  compose.yml            ← container apps (unchanged format)
  systemd/<svc>.service  ← native apps: unit per service, Restart=on-failure,
                            After= edges derived from the SAME capability graph
  traefik-native.yml     ← file-provider routes for native services (see below)
```

`bbox reconcile` converges both: `docker compose up -d` for one lane, `systemctl daemon-reload &&
systemctl restart <changed units>` for the other. Dispositions map 1:1 — enabled=`enable --now`,
disabled=`disable --now`, archived=disable + remove binaries, keep data. Generations/rollback
already archive `.generated/` wholesale, so they cover the units for free.

**Routing:** traefik discovers container apps via the docker provider (labels, unchanged) and
native apps via a compiler-emitted **file provider** — same `routing:` blocks in app.json, same
hosts, same middlewares. A service moving container→native changes which provider announces it and
nothing else. **Needs a parity gate: the effective router/middleware set must be identical across
the move.** Note this is an assertion over the *resolved routing table*, not over rendered compose
bytes — the old G1 (`compose-equiv.py`) tried the latter and was deleted on 2026-07-30 precisely
because the render is not reproducible run-to-run and changes on every app add. Take the next free
gate number from `scripts/refactor/GATES.md`; **do not reuse G1**.

**Cross-runtime networking, the one subtle piece:** containers today reach `redis`, `supabase-db`
by compose-network alias. Native services listen on the guest host. The compiler already knows
every capability endpoint (`redis://redis:6379`, `postgres://supabase-db:5432`), so for every
capability whose provider is native it injects `extra_hosts: ["redis:host-gateway", …]` into every
consuming container's compose. **No app changes, no URL changes** — the alias just resolves to the
gateway instead of a peer container. Native→container (rare) goes through traefik or published
ports.

**What does not change at all:** `platform.state.yaml`, the app.json contract, the capability
graph and strengths, blueprints/hooks, `bbox` verbs, the console, baseline. An app that stays on
compose cannot tell anything happened.

---

## Phases — each one shippable, none a prerequisite hostage

| Phase | What ships | Effort | Depends on |
|---|---|---|---|
| **A** | dockerd 28.5.2 into the `.run` runtime segment (today it is a 202-byte placeholder) → **Linux single file, zero dependencies** | ~1 week | nothing |
| **B** | Supabase decomposition: L1 `postgres` (still a container at this point!), gallery `supabase`, kong verdict, `drive→object-storage` edge declared, data migration script | 1–2 weeks | nothing |
| **C** | Identity: Authelia in, authentik out. Compiler generates identity config from `sso:` blocks | 3–4 weeks | decision Authelia/Zitadel |
| **D** | `runtime:` in schema + compiler dual-lane + guest rootfs v2 (systemd services baked in) + nspawn mode for Linux | 3–4 weeks | B (fewer services to bake) |
| **E** | Service-by-service native moves inside the guest: traefik → redis → postgres → n8n → our 16. One per PR, G1-gated | rolling, ~2 weeks total | D |
| **F** | Host shells: Windows installer finishes (exists, needs payload staging), macOS vfkit app | 2–4 weeks | D |

Phases B and C improve the platform **even if native never happens** (fewer images, lighter
default install, identity component that has a non-Docker future). That is deliberate: no phase is
justified only by the end state.

**End state:** base install ~500 MB download (was 2.2 GB), boot in seconds, ~3–4 GB RAM (was ~10),
one signed executable per OS, and a gallery that takes both compose apps and native apps —
declaratively, through the same manifest, state file and compiler as today.

## Open decisions (blocking their phases, nothing else)

1. **Authelia vs Zitadel** — blocks C. Recommendation: Authelia.
2. **kong: drop vs move** — decided inside B with the route table in hand. Recommendation: drop.
3. **glitchtip to gallery** — recommendation: yes, nothing requires it.
4. **Linux nspawn vs host-native binaries** — blocks D's Linux arm. Recommendation: nspawn (one
   userland everywhere).
