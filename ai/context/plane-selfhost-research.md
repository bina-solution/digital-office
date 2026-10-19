# Plane, self-hosted — what is actually runnable, and what `project-pln` should be

Research date: 2026-09-28. Every claim below is sourced either from the live `makeplane/plane` repo
(cloned read-only through the office `git` app, default branch `preview`, plus `master`), the GitHub
release assets, the Docker Hub API, the official docs, or from **measurements taken on this office's
own engine** (marked MEASURED). Where a subagent report and a direct file read disagreed, the file read
wins.

Scope of the question this answers: *can Plane run locally in the digital office, in its leanest form,
in full Hebrew — and if not as-is, what exactly should `project-pln` be?*

---

## 1. The project, the editions, the license

| Edition | What it is | Where | License |
|---|---|---|---|
| **Community (CE)** | The open-source self-host edition. **There is no `makeplane/plane-ce` repo** — it 404s. CE is `makeplane/plane`, branch `master`/`preview`. | github.com/makeplane/plane | **AGPL-3.0-only** |
| Commercial | Closed source, installed via `curl -fsSL https://prime.plane.so/install/ \| sh -`, managed by `prime-cli`. "Commercial Edition remains closed-source." | prime.plane.so | proprietary |
| Airgapped | Commercial variant, Enterprise only, 100 seats minimum. | — | proprietary |
| Cloud | Hosted (`app.plane.so`) — the service the owner already uses. | — | SaaS |

Consequence for us: if we ship a modified Plane, **AGPL-3.0 applies** — a modified frontend offered
over the network carries the source-availability obligation. That is fine inside the office (we own
the source), but it is a real constraint the moment "our Plane fork" is given to anyone else.

**The self-host artifact is NOT the repo-root `docker-compose.yml`.** That file is a build-from-source
dev compose (`build: context: .`). The supported file is a **release asset**:

```bash
curl -fsSL -o setup.sh https://github.com/makeplane/plane/releases/latest/download/setup.sh
# ./setup.sh → menu: install / start / stop / restart / upgrade / logs / backup
# resolve a concrete tag instead of the moving `stable`:
# https://github.com/makeplane/plane/releases/download/<tag>/docker-compose.yml
```

Latest CE release observed: **v1.4.2** (2026-08-23). `setup.sh` resolves `stable` by calling
`api.github.com` — pin `APP_RELEASE=<tag>` for reproducibility.

---

## 2. The full CE stack — 13 services

From the released compose + `apps/proxy/Caddyfile.ce`:

| Service | Image | Role | Internal port |
|---|---|---|---|
| `web` | `makeplane/plane-frontend` | the UI — a **static SPA** (`react-router.config.ts` → `ssr: false`) served by nginx | 3000 |
| `space` | `makeplane/plane-space` | public sharing of projects/views/pages without login | 3000 |
| `admin` | `makeplane/plane-admin` | instance admin ("god mode"): **home of the telemetry toggle** | 3000 |
| `live` | `makeplane/plane-live` | real-time collaboration over WebSockets | 3000 |
| `api` | `makeplane/plane-backend` | Django REST API (gunicorn/uvicorn) | 8000 |
| `worker` | `plane-backend` | Celery — notifications, imports/exports, webhooks | — |
| `beat-worker` | `plane-backend` | Celery beat — periodic jobs | — |
| `migrator` | `plane-backend` | one-shot: `wait_for_db` + `migrate`, then **exits** | — |
| `plane-db` | `postgres:15.7-alpine` | primary DB, started with `max_connections=1000` | 5432 |
| `plane-redis` | `valkey/valkey:7.2.11-alpine` | cache / session / broker results | 6379 |
| `plane-mq` | `rabbitmq:3.13.6-management-alpine` | AMQP queue | 5672 |
| `plane-minio` | `pgsty/minio` (third-party rebuild) | S3-compatible object storage, bucket `uploads` | 9000 |
| `proxy` | `makeplane/plane-proxy` (Caddy 2.11) | the only published-port container; owns the path routing below | 80/443 |

The routing contract the proxy exists to implement — **every one of these is an absolute root path**:

```
/*                          → web:3000        (catch-all)
/spaces/*                   → space:3000
/god-mode/*                 → admin:3000
/live/*                     → live:3000   (needs Upgrade/Connection headers)
/api/*, /auth/*, /static/*  → api:8000
/uploads/*  (= $BUCKET_NAME)→ plane-minio:9000
```

---

## 3. The leanest runnable subset

**There are no `profiles:` in the CE compose** — `docker compose --profile …` is not available; the
only levers are deleting services or naming them explicitly on `up`.

| Service | Mandatory? | What actually breaks without it |
|---|---|---|
| `api` | **yes** | nothing works; it is the only thing that talks to Postgres |
| `plane-db` | **yes** (or external PG 15.7+/16) | — |
| `plane-redis` | **yes** (or external) | cache/session/bus |
| `plane-mq` | **yes in practice** | `AMQP_URL` is in the api env block; API boots, background work stalls |
| `migrator` | **yes (one-shot)** | `docker-entrypoint-api.sh` runs `wait_for_migrations` **before gunicorn** → api never becomes healthy. The symptom is a hang, not a crash. |
| `plane-minio` | effectively yes | the entrypoint runs `create_bucket`; uploads/attachments/exports fail. Replaceable by external S3 (`USE_MINIO=0`) |
| `web` | yes (for humans) | the API serves no HTML |
| `worker` | optional, keep it | CRUD still works; notifications/exports/webhooks silently stop and the queue grows |
| `beat-worker` | optional | periodic jobs stop |
| `proxy` | documented as optional | **but then you own the 6-route table above** |
| `space` | optional | `/spaces/*` dead; published links die |
| `admin` | optional | `/god-mode/*` dead **and you lose the telemetry toggle** |
| `live` | optional-ish | `/live/*` 404s; the SPA baked `VITE_LIVE_BASE_PATH=/live` at build time, so the real-time editor spins. Low confidence — keep it, it is cheap |

**Floor: 8 long-running containers + 1 one-shot** (`api, web, worker, beat, migrator, db, redis, mq, minio`),
minus whatever we can point at shared infrastructure.

### What each piece actually costs — the one real measurement

`docker stats` from a self-hosted Plane v0.25.0 on 4 vCPU / 8 GB
([use-apify](https://use-apify.com/docs/self-hosted/productivity/plane), 2026-05-02) — idle → peak
(5 users, one 50-issue import):

| service | idle | peak | note |
|---|---|---|---|
| `api` | 350 MB | 550 MB | every gunicorn worker is a full Django process ([#1449](https://github.com/makeplane/plane/issues/1449): 8 workers → 400–800 MB; `GUNICORN_WORKERS` exists because of it) |
| `worker` | 200 MB | 350 MB | Celery defaults to **one thread per core** ([#6671](https://github.com/makeplane/plane/issues/6671)) — cap it with `CELERY_WORKER_CONCURRENCY` |
| `beat` | 150 MB | 180 MB | droppable, or folded into the worker with `-B` |
| `web` | **300 MB** | 450 MB | that was the Next.js server; in v1.4.x `web` is a **static SPA served by nginx** → ~20 MB |
| `space` | 200 MB | 280 MB | still a Node server in the AIO (`react-router-serve`) |
| `admin` | 150 MB | 200 MB | static in v1.4.x → ~20 MB |
| `plane-db` | 200 MB | 280 MB | shareable with the office Postgres (already running) |
| `plane-redis` | 60 MB | 70 MB | shareable with the office Redis (already running) |
| `minio` | 120 MB | 180 MB | **not** replaceable by a directory — see below |
| their caddy | 15 MB | 20 MB | |

Not measured anywhere: `live`, RabbitMQ, Plane's own `proxy`, `migrator`.

Three code-level facts that fix the floor:

* **There is no disk-only storage mode.** `apps/api/plane/settings/common.py` sets
  `STORAGES["default"] = plane.settings.storage.S3Storage` unconditionally; `USE_MINIO` only chooses
  *how* the S3 client is built (request-host endpoint vs `AWS_S3_ENDPOINT_URL`). Attachments are
  presigned POSTs against an S3 endpoint, on the critical path. It is MinIO or an external S3 — never
  "a folder", whatever the commercial docs sentence suggests.
* **RabbitMQ is required.** `CELERY_BROKER_URL` is *assigned* from `AMQP_URL` and is never read from the
  environment, and there is no Redis or in-memory broker path. A lighter **AMQP 0-9-1** broker
  (LavinMQ, 42 MB image, multi-arch) is the way down — not removal.
* **`beat` is optional; `api` and `worker` are not.**

Sharing is supported by env, and the office already runs two of the four:
`DATABASE_URL` (or `PGHOST/PGDATABASE/…`), `REDIS_URL`, `AMQP_URL`, `AWS_S3_*` + `USE_MINIO=0`.
Caveat: `plane-db` starts with `max_connections=1000`, so pointing Plane at the office Postgres needs a
deliberate connection budget — and Plane requires **PostgreSQL 15.7+** (the office runs
`supabase/postgres:15.8.1.085`, so that part fits).

RabbitMQ has **no provider in the office** — `redis` provides `kv`, not a broker. A Plane app would
have to carry its own `plane-mq` (~100–200 MB) or reuse an external broker.

### The all-in-one image — real, but it buys container count, not dependencies

`makeplane/plane-aio-community` exists (`stable` = **amd64 + arm64**, 641 MB; `v1.4.2` available),
built by `deployments/aio/community/` — web + space + admin + api + worker + beat + live + Caddy in one
container under supervisord. **It still requires external Postgres, Redis, RabbitMQ and S3.** So:
1 container + 4 external services instead of 13 containers. On a machine that already has three of the
four, that is the single biggest saving available — and it removes the need to re-implement the Caddy
route table, because the AIO keeps it.

Note the AIO's `preview` tag is **amd64-only**; `stable`/`v1.4.2` are multi-arch. On this arm64 Mac:
use `stable`/`v1.4.2`, never `preview`.

---

## 4. Can it run HERE? — yes, at ~800 MB, and that is the whole answer

MEASURED on this office (2026-09-28):

| | Value |
|---|---|
| engine (Lima guest) memory | **4904 MiB total**, 4559 used, **345 available**, swap **2047/2047 fully consumed** |
| host sizing rule | `packaging/macos/engine.sh: vm_mem()` → host RAM ≤ 8 GB gives the guest **5 GiB**; the guest *is* 5 GiB, so this is an ≤8 GB Mac |
| sum of all running containers | **3847 MiB** (38 containers) |
| held by stray `ui-capture` containers | **1055 MiB** (4 containers left/left-running by `./bbox ui-map` runs — one is live right now) |
| free disk in the engine | ~24 GB (the AIO image alone is **2.12 GB** on disk, measured after pulling it) |

**The floor is not 4 GB and not 2.5 GB.** The docs' 4 GB/8 GB covers the full 13-service stack plus
production headroom plus the *first boot* (migrations + `collectstatic` peak, and
[#1850](https://github.com/makeplane/plane/issues/1850) is a 6 GB VM freezing while building the
frontend from source). A deliberately pruned instance is:

| kept | MB |
|---|---|
| `api` (GUNICORN_WORKERS=1) | 350–550 |
| `worker` (`CELERY_WORKER_CONCURRENCY=1`) | 200–350 |
| `web` (static, nginx) | ~20 |
| `minio` | 120–180 |
| AMQP broker (LavinMQ) | 40–60 |
| Caddy in front (or the office traefik) | 15–30 |
| **shared** office Postgres + Redis | 0 extra (already running) |
| **dropped**: space, admin, live, beat, plane-db, plane-redis, proxy | 0 |
| **total** | **≈ 750–1200 MB** |

That is the honest number: **~0.8–1.2 GB**, an eighth of the office's current footprint — not the whole
machine. It requires freeing the ~1 GB of stray capture containers (which happens by itself when the
ui-map run ends) plus some slack, because the first boot *and* RabbitMQ/Celery are spiky and the guest's
2 GB swap is already fully consumed. The cheap insurance is a larger swap file inside the Lima guest
(disk has 24 GB free) — slow, but it turns "OOM-killed" into "slow".

So: **Plane fits here, barely, and it will sit at the ceiling of a 5 GiB engine.** The alternative
machine (the dev server) is 8 GB but 76 % consumed by a parallel staging office, and it is not the
office's engine, so an app there is not a console app.

### Measured after landing it — better than the estimate

`apps/project-pln` was built and brought up on this machine on 2026-09-29 (Route A, English UI, the
Hebrew fork still to come). What it actually cost:

| service | resident |
|---|---|
| `project-pln` (migrator + api + worker + Caddy + static web) | 345 MiB |
| `plane-mq` (RabbitMQ) | 62 MiB |
| `plane-minio` | 73 MiB |
| `plane-db` (PostgreSQL 15.7) | 18 MiB |
| `plane-redis` (valkey) | 3 MiB |
| **total** | **~500 MiB** |

First boot to healthy: ~4 minutes (the migrator runs ~150 migrations; `api` blocks on
`wait_for_migrations`). Two traps cost real time and are documented in the app's own README:
traefik kept serving the **old** container's configuration after `up -d --build` recreated it (a
plain 404 with no router name — remedy: restart traefik *after* the container exists), and the AIO's
supervisord config has no `unix_http_server`/`rpcinterface` section, so `supervisorctl status` — the
command upstream's own README tells you to run — does not work until both are added.

---

## 5. Hosting it in the office (if/when a machine exists)

**Subpath hosting is not supported, and cannot be fixed from outside.** Evidence:
`apps/proxy/Caddyfile.ce` is root-only; `apps/web/react-router.config.ts` is `ssr: false` (a static SPA)
with `VITE_API_BASE_URL` / `VITE_ADMIN_BASE_PATH=/god-mode` / `VITE_SPACE_BASE_PATH=/spaces` /
`VITE_LIVE_BASE_PATH=/live` taken as **build ARGs** — there is no base-path/basename knob, and the
assets are served from `/`; open bug [#8168](https://github.com/makeplane/plane/issues/8168)
("Serve on URL path", Nov 2025, no comments) reports exactly the `/_next/static`-at-root failure and
notes that setting the `VITE_*` variables at runtime changes nothing.

So a Plane app in the office is:

* its own host — `plane.localhost:8080` (macOS edge) / `plane.<DEPLOYMENT_DOMAIN>` (VPS),
* `module.embed: false` in `app.json` (a console tile that opens in a new tab, like `n8n`, `supabase`,
  `glitchtip` — all of which are Next/static SPAs for the same reason),
* its own login: **Plane CE has no OIDC/SAML** (those are commercial), so `auth` on the edge is a
  choice between a second authentik login (`auth: "sso"`) and Plane's own accounts (`auth: "none"`,
  the `n8n` precedent). `none` + Plane's own login is the honest option.
* one real trap: **login depends on email**. Plane CE's default flow is a magic code; there is no SMTP
  in the office's `mail` app wired to it, so a first boot needs SMTP configured (or the
  `admin`/god-mode path) before anyone can log in. **Resolved 2026-09-30, and not that way**: SMTP is
  still not wired, and nobody clicks god-mode — `apps/project-pln/{bootstrap.yaml,bootstrap.py}` plus
  `hooks/onboard` write the instance admin, the workspace and the first project directly through the
  ORM (the rows the sign-up view writes), with the owner's password coming from `.env`. See
  `apps/project-pln/AGENT.md` § "Bringing it up".

Expected declared limits if built as an app: `api 1g`, `worker 768M`, `web 256M`, `beat 256M`,
`mq 384M`, `minio 512M` (+ platform `db`/`redis` if shared) — ~3.2 GB declared, ~2.5 GB resident. It
would need its own machine, and gate G30 (memory budget) would have to be told about it.

---

## 6. Hebrew and RTL — the real cost, and it is the biggest one

Plane **does** have i18n: `packages/i18n` (`@plane/i18n`), i18next, translations at
`packages/i18n/src/locales/<locale>/<namespace>.json` — **28 namespaces per locale**
(common, editor, work-item, cycle, module, settings, navigation, page, wiki, …), loaded dynamically.

Shipped locales (21): en, fr, es, ja, zh-CN, zh-TW, ru, it, cs, sk, de, ua, pl, ko, pt-BR, id, ro,
vi-VN, tr-TR, ka-ge, nl.

**Hebrew is not among them — and neither is any RTL language.** Upstream has *no RTL support at all*:

* `apps/web/app/root.tsx` hardcodes `<html lang="en">` — no `dir` attribute anywhere;
* `setLanguage()` sets `document.documentElement.lang` only, never `.dir`;
* **zero** `rtl:` Tailwind variants and no logical-property utilities (`ms-`/`me-`/`ps-`/`pe-`) across
  `apps/` and `packages/`;
* the font stack is Inter + Material Symbols + IBM Plex Mono — no Hebrew face;
* open: [#3314](https://github.com/makeplane/plane/issues/3314) "Add support for rtl text" (since
  2024), [#9641](https://github.com/makeplane/plane/issues/9641) (Persian + RTL),
  [#9299](https://github.com/makeplane/plane/pull/9299) — **an open PR that contains the exact RTL
  recipe** (`RTL_LANGUAGES`, `isRTLLanguage()`, `getLanguageDirection()`, `setLanguage` setting `dir`,
  provider applying it on first load, plus 28 locale files);
* closed **unmerged**: [#8722](https://github.com/makeplane/plane/pull/8722) "add Hebrew (he)
  translations" — written against the *obsolete* `.ts` locale layout, so its strings can be reused as
  data but the PR cannot be cherry-picked; [#6867](https://github.com/makeplane/plane/pull/6867)
  (Arabic).

So "full Hebrew" in Plane means: (1) produce 28 parity-checked Hebrew JSON files
(`pnpm check:sync --ci` fails on any key drift), (2) edit `TLanguage` + `SUPPORTED_LANGUAGES`,
(3) implement the RTL work upstream still lacks, (4) **rebuild the frontend image from the monorepo**
— the published `plane-frontend` image is a prebuilt bundle, so a locale cannot be added at runtime.
(5) There is also no env var for a default locale (`FALLBACK_LANGUAGE = "en"`, and the "detect browser
language" PR is closed unmerged), so an English flash before the user picks Hebrew is the default
behaviour.

That is a genuine fork of the frontend, maintained across every upgrade. It is the honest cost of
"Plane in Hebrew".

### What it actually took — measured, 2026-09-29

It is built and running: **[solomonBoltin/plane-he](https://github.com/solomonBoltin/plane-he)**
(public, AGPL-3.0, 9 commits) holds 3,837 strings across the 28 namespaces, six whole-file overrides
of upstream sources, three tooling scripts and one GitHub Actions workflow; the office's
`apps/project-pln` consumes its release asset. What the estimate above got right and wrong:

* **The translation was the cheap part.** 28 namespaces fanned out to seven agents in one pass,
  parity-checked mechanically against upstream English (`tools/check-parity.py` — keys, placeholders
  AND ICU plural structure). 98.4% of strings carry Hebrew; the rest are brand and code tokens.
* **The RTL work was bigger than "set `dir`".** Three separate mechanisms had to agree, and the third
  was only found by looking at a rendered screen:
  1. `setLanguage()` must set `documentElement.dir`, and the i18n instance must apply it at import so
     a Hebrew reload does not flash left-to-right;
  2. the served `index.html` must carry `lang="he" dir="rtl"` (the bundle runs after first paint);
  3. **the app shell must render `lang`/`dir` itself.** React owns `<html>` — `apps/web/app/root.tsx`
     renders it with a hardcoded `lang="en"` and no `dir`, so a later render DROPS the attribute set
     from outside. Measured: the same workspace rendered RTL on one load and LTR on the next.
* **The language is a SERVER-side per-user field.** `Profile.language` (default `"en"`) is written into
  `localStorage.userLanguage` on every load, so no client-side default survives it. Hebrew-by-default
  needs the API's model default patched, not just the frontend — the frontend is only half the
  setting.
* **The build is CI's job, not this machine's.** `apps/web/Dockerfile.web` is a `turbo prune` + Vite
  build of the whole monorepo; on a native arm64 GitHub runner it takes ~10 minutes. A local build on
  the 5 GiB engine was never attempted.
* **Two upstream traps cost time and are now written down**: the static web root differs by tag
  (`/usr/share/nginx/html` at v1.4.2, `/usr/share/caddy/html` on master), and i18next is configured
  with `returnEmptyString: false`, so an empty translation falls back to English rather than
  rendering nothing.
* **What remains English** is upstream's, not the patch's: the welcome modal, the profile-completion
  step and the instance-setup page contain **no i18n keys at all** (checked string by string), and
  `/god-mode/` is a separate static build upstream never wired to i18n.


---

## 7. Getting the owner's cloud data out

| Path | What it gives | Where it works |
|---|---|---|
| **Export** (Workspace settings → Exports) | **work items only** — all projects or one, CSV/XLSX/JSON, filters; ZIP behind a 7-day presigned URL. API: `POST /api/v1/workspaces/<slug>/export-issues/` | Cloud + Commercial + CE |
| **Importers** (Jira, Linear, Asana, ClickUp, Notion, Confluence, CSV) | field-mapped import | **Cloud and Commercial only** — docs say so explicitly, and the CE code has no importer views/URLs/UI (only a legacy model with `github`/`jira` choices). Not available to us. |
| **REST API** | the reliable surface: `GET /api/v1/workspaces/{slug}/projects/`, `.../work-items/` (+ comments, links, activities, attachments, relations, states, labels, cycles, modules), auth `X-API-Key: plane_api_…`, **rate limit 60/min per key** (`API_KEY_RATE_LIMIT`, returns `X-RateLimit-*`, 429 on excess) | Cloud + self-hosted |
| **`plane-migrate`** (PyPI, third-party) | projects across Cloud ↔ Commercial ↔ OSS: work-item types, states (by name), labels, members (by email), estimates, work items + relations + links + comments, modules, cycles, intake; resumable, delta re-runs | Any combination |
| **Official SDKs / MCP** | `plane-sdk` (Python), `@makeplane/plane-node-sdk` (Node), official MCP server | Cloud + self-hosted |

No official Cloud → self-hosted migration exists: tracking issue
[#1070](https://github.com/makeplane/plane/issues/1070) is closed; a maintainer (2026-07-28) says it is
on the roadmap and that their team helps case-by-case, with export + CSV import as the partial path.

What a *complete* move would require: Postgres rows (workspaces, projects, issues, issue_comments,
issue_attachments, file_assets, states, labels, cycles, modules, pages, …) **and the object-storage
bucket** — file URLs embed bucket + endpoint, so the bucket and the endpoint are part of the move.
Redis/RabbitMQ hold only transient state. Note that attachment/wikis/pages and workspace settings are
**not** covered by the export, and not by `plane-migrate` either.

---

## 8. The routes for `project-pln`

### Route A — Plane CE, lean, self-hosted  ← "it must be Plane"
Faithful Plane (cycles, modules, wiki, intake, real-time, views), AGPL.
Cost: **~0.8–1.2 GB** of the office engine (§4) — it fits, at the ceiling; a **maintained frontend fork**
for Hebrew + RTL, built where there is room (see the build note below) (§6); its own host, not embedded
(§5); its own login (Plane CE has no OIDC) with `ENABLE_EMAIL_PASSWORD` so no SMTP is needed to log in —
and the office's own GreenMail (`mailserver:25`) can carry its outbound mail. Migration from cloud is
straightforward once it runs (`plane-migrate` + API).

*Build note — where the Hebrew image comes from.* The published `plane-frontend` image is a prebuilt
bundle, so a locale cannot be added at runtime; the frontend must be rebuilt from the monorepo
(`turbo prune --scope=web` + a Vite build) — which is exactly what cannot be done comfortably on a
5 GiB engine. It **can** be done on GitHub Actions: the office's own `git` connection is a classic PAT
with `repo` + **`workflow`** scope, and the automatic `GITHUB_TOKEN` in Actions has `packages: write`,
so a fork of `makeplane/plane` with the Hebrew locale + RTL can build and publish
`ghcr.io/<owner>/plane-frontend:he` on every push, and the office pulls that. Same shape as `bina-ds`:
the upstream product, plus one thin layer of ours, built where there is room.

### Route B — `project-pln`, a native Hebrew app in the office
A first-party office app: FastAPI + bina-ui + the platform `postgres`/`redis`, a Plane-shaped model
(workspace → project → work item, states, labels, cycles/iterations, comments, attachments via the
existing storage capability), **Hebrew and RTL by construction**, embedded in the console at
`/a/project-pln/`, behind authentik SSO, **~150–250 MB**. Migration: import the owner's Plane Cloud data
through the REST API (read-only, 60 req/min — an overnight-safe batch) or from the JSON export, into the
app's own schema — the importer becomes part of the app instead of a one-shot script.
Rejected by the owner as "building everything from scratch"; recorded here for completeness.

### Route C — hybrid
Plane CE as the engine-of-record; a Hebrew office UI over Plane's REST API. Best fidelity and best
Hebrew, but two systems to run and keep in sync, and the UI is constrained by Plane's API surface.

### Route D — a different, already-Hebrew product: **Vikunja**  ← "Hebrew that runs here today"
There is exactly one light self-hosted project/task tool that ships **Hebrew with RTL wired in code**:

| | |
|---|---|
| image | `vikunja/vikunja:2.6.0` — **49 MB** compressed, 1 container, **SQLite** (no Postgres, no Redis, no RabbitMQ) |
| RAM | ~50–100 MB |
| licence | AGPL-3.0-or-later |
| Hebrew | `frontend/src/i18n/lang/he-IL.json` + `pkg/i18n/lang/he-IL.json`; registered in `frontend/src/i18n/index.ts` and `pkg/i18n/i18n.go` |
| RTL | yes, in code: `const RTL_LANGUAGES = ['ar-SA','he-IL','fa-IR']` → `document.documentElement.dir = 'rtl'` |
| features | projects, tasks, subtasks, kanban buckets, list/table/gantt, labels, assignees, due dates, reminders, comments, attachments |
| API | `/api/v1`, `Authorization: Bearer <token>`, rate limits configurable |
| import | **built-in CSV migrator** (column mapping UI, `POST /api/v1/migration/csv/*`) — a Plane CSV export imports with no script; flat fields only (no hierarchy/comments/attachments) |
| missing vs Plane | cycles/modules, wiki/pages, intake, real-time co-editing, and Plane's richer views |

Runners-up, for the record: Wekan (real `he-IL`, but Meteor + MongoDB → 500 MB–1 GB), Leantime
(`he-IL.ini` declares `isRTL="true"`, but PHP + MySQL), OpenProject CE (the most complete Hebrew of all,
but 1.5–2.5 GB), Taiga (Hebrew, but 6+ containers), Kanboard (lightest and has RTL, **no Hebrew
strings**), Planka (**no longer open source** since 2025), Focalboard (has `he.json`, upstream dead
since 2023), Huly (no Hebrew at all).

### Recommendation

The two real choices are **A** and **D**, and they answer different questions:

* **"It must be Plane, in Hebrew, running here"** → Route A: lean Plane now (~0.8–1.2 GB, fits once the
  stray capture containers clear, plus a bigger swap file), and the Hebrew frontend fork built on
  GitHub Actions. Weeks, not days — most of it in the translation + RTL work, not in the deployment.
* **"A Hebrew project/task manager that runs here and that I didn't build from scratch"** → Route D:
  one 49 MB container, ~80 MB, Hebrew + RTL out of the box, up in an afternoon, and the owner's Plane
  data arrives through the built-in CSV importer. It is a different product from Plane, and that is the
  trade.

Route B remains available but was rejected; Route C only pays off if the Hebrew Plane fork exists.

---

## 9. Building an app in the office — the condensed recipe

Full anatomy: [`build-your-first-app.md`](build-your-first-app.md) ·
contract: [`platform-service-contract.md`](platform-service-contract.md) · gates: `scripts/refactor/GATES.md`.

```
apps/project-pln/
  app.json            the manifest — the ONLY file the platform reads about the app
  docker-compose.yml  services (one container is normal; Supabase runs 6)
  Dockerfile          only if you build rather than pull
  AGENT.md            the brief the office agent loads on every session (≤6000 bytes)
```

Minimum correct `app.json` (Route B):

```jsonc
{
  "id": "project-pln", "layer": 3, "kind": "service", "version": "0.1.0",
  "title":   { "he": "ניהול פרויקטים", "en": "Projects" },
  "summary": { "he": "פרויקטים, משימות ולוחות — בעברית", "en": "Projects, tasks and boards — Hebrew" },
  "use": [{ "capability": "sql", "strength": "requires", "after": true }],
  "compose": "docker-compose.yml",
  "routing": [{
    "host": "project-pln", "port": 8080, "auth": "sso",
    "module": { "group": "עסק", "icon": "kanban", "embed": true, "alias": "project-pln",
                "id": "project-pln", "name": "ניהול פרויקטים", "desc": "פרויקטים ומשימות",
                "order": 40, "url": "http://project-pln:8080", "url_env": "PROJECT_PLN_URL" }
  }],
  "health": { "structural": "auto",
              "probe": { "http": "http://project-pln:8080/healthz", "interval": "30s" } },
  "data": { "volumes": ["project_pln_data"], "on_uninstall": "keep" },
  "resources": { "cpus": "0.5", "memory": "256M" },
  "agent": { "context": "AGENT.md", "order": 30 }
}
```

Rules that fail **silently** if forgotten (from the skill + gate list):
`title`/`summary` are `{he,en}` objects; directory name == `id`; UI uses **relative URLs only**
(the console serves at `/a/<alias>/` and injects `<base href>`); the healthcheck uses a binary the
image really has (`python`, never `curl` — gate G18); third-party images are pinned by tag or digest
(G15); `data.volumes` matches the compose (G16); the theme is bundled into the app's `static/` and
normalised with `theme-token-lint.py --fix`; numbers/IPs/paths in Hebrew text get
`direction:ltr; unicode-bidi:isolate`.

Two deltas against that template:

* **Route A (Plane)** — `"auth": "none"` (Plane CE has its own accounts and no OIDC, exactly like
  `n8n`), `"embed": false`, `resources.memory: "1g"` on the AIO container, the two extra services
  (`lavinmq`, `minio`) with pinned images, and it must be reachable at a host root because Plane cannot
  be mounted on a subpath (§5). Its own thin `Dockerfile` (FROM the AIO image, our trimmed
  `supervisor.conf` + entrypoint) is where `space`/`live`/`beat` are dropped and `WEB_URL`/
  `CORS_ALLOWED_ORIGINS` are set from the office's base-URL variable.
* **Route D (Vikunja)** — same template with `"auth": "sso"`, `host: "project-pln"`, the single
  `vikunja/vikunja:2.6.0` service, `resources.memory: "256M"`, SQLite on its volume, and
  `VIKUNJA_SERVICE_PUBLICURL` set from the base-URL variable. No Dockerfile needed.

Bring-up order:

```bash
python3 platform/manager/reconcile.py validate     # structure, types, host/tile collisions
python3 platform/manager/reconcile.py plan         # the graph, every diagnostic at once
./bbox apps enable project-pln                     # desired state (the only writer)
./scripts/dc up -d --build project-pln
./scripts/dc ps project-pln && ./scripts/dc logs --tail 50 project-pln
./scripts/dc restart traefik-deployment            # a new host 404s until traefik re-syncs
./scripts/dc restart console                       # the tile appears on the rail
python3 scripts/refactor/layering-lint.py --strict # + healthcheck / image-pin / data-volumes /
                                                   #   engine-bypass / theme-token / capability-use /
                                                   #   memory-budget — see GATES.md
```

The Plane route (A) would follow the same recipe with a very different compose: the AIO image plus
external `postgres`/`redis`/`plane-mq`, `module.embed: false`, its own host, and the Caddy route table
preserved inside the AIO container.

---

## 10. Sources

* Repo (read via the office `git` app, token-free remote): `makeplane/plane` — `docker-compose.yml`,
  `deployments/cli/community/docker-compose.yml`, `deployments/cli/community/variables.env`,
  `deployments/aio/community/{Dockerfile,README.md,supervisor.conf}`, `apps/proxy/Caddyfile.ce`,
  `packages/i18n/src/{constants/language.ts,core/instance.ts}`, `apps/web/react-router.config.ts`.
* [Self-hosted Plane](https://plane.so/self-hosted) · [Editions and versions](https://developers.plane.so/self-hosting/editions-and-versions) ·
  [docker-compose install](https://developers.plane.so/self-hosting/methods/docker-compose) ·
  [Plane architecture](https://developers.plane.so/self-hosting/plane-architecture) ·
  [reverse proxy](https://developers.plane.so/self-hosting/govern/reverse-proxy) ·
  [database and storage](https://developers.plane.so/self-hosting/govern/database-and-storage) ·
  [upgrade](https://developers.plane.so/self-hosting/manage/upgrade-plane) ·
  [telemetry](https://developers.plane.so/self-hosting/telemetry) ·
  [API](https://developers.plane.so/api-reference/introduction) · [SDKs](https://developers.plane.so/dev-tools/build-plane-app/sdks) ·
  [export](https://docs.plane.so/core-concepts/export) · [importers](https://docs.plane.so/importers/overview)
* Issues/PRs: [#8168 subpath](https://github.com/makeplane/plane/issues/8168) ·
  [#3314 RTL](https://github.com/makeplane/plane/issues/3314) ·
  [#9299 Persian+RTL recipe](https://github.com/makeplane/plane/pull/9299) ·
  [#8722 Hebrew (closed unmerged)](https://github.com/makeplane/plane/pull/8722) ·
  [#1070 cloud↔self-host migration](https://github.com/makeplane/plane/issues/1070) ·
  [#1449 api memory / GUNICORN_WORKERS](https://github.com/makeplane/plane/issues/1449) ·
  [#6671 Celery concurrency](https://github.com/makeplane/plane/issues/6671) ·
  [#5778 worker OOMKilled at 1Gi](https://github.com/makeplane/plane/issues/5778) ·
  [#1850 6 GB VM froze building the frontend](https://github.com/makeplane/plane/issues/1850)
* Measured RSS + sizing: [use-apify — Plane](https://use-apify.com/docs/self-hosted/productivity/plane) ·
  [selfhosting.sh](https://selfhosting.sh/apps/plane/) · [ramnode](https://ramnode.com/guides/plane)
* The already-Hebrew alternative: [go-vikunja/vikunja](https://github.com/go-vikunja/vikunja) —
  [`frontend/src/i18n/lang/he-IL.json`](https://raw.githubusercontent.com/go-vikunja/vikunja/main/frontend/src/i18n/lang/he-IL.json),
  [`frontend/src/i18n/index.ts`](https://raw.githubusercontent.com/go-vikunja/vikunja/main/frontend/src/i18n/index.ts)
  (`RTL_LANGUAGES`, `dir="rtl"`),
  [`MigrationCSV.vue`](https://raw.githubusercontent.com/go-vikunja/vikunja/main/frontend/src/views/migrate/MigrationCSV.vue);
  runners-up: [Kanboard locales](https://github.com/kanboard/kanboard/tree/main/app/Locale) (no `he_IL`),
  [Planka LICENSE.md](https://raw.githubusercontent.com/plankanban/planka/HEAD/LICENSE.md) (proprietary since 2025),
  [Leantime he-IL.ini](https://raw.githubusercontent.com/Leantime/leantime/master/app/Language/he-IL.ini)
* [selfhosting.sh — Plane](https://selfhosting.sh/apps/plane/) (third-party sizing) ·
  [plane-migrate (PyPI)](https://pypi.org/project/plane-migrate/)
* MEASURED, this office, 2026-09-28: `docker stats` sum 3847 MiB across 38 containers;
  `free` 4904 MiB total / 345 MiB available / swap 2047 MiB fully used;
  `packaging/macos/engine.sh:vm_mem()` (≤8 GB Mac → 5 GiB guest);
  `curl http://computers:8977/api/computers` for the dev server's 8 GB / 76 % used.
