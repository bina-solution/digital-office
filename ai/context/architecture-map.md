# The map of the office — what DGO is for, how it is built, every app and every file (2026-11-10)

**Asked by the owner, verbatim (DGO-1800):** «לחקור לעומק את הארכיטקטורה של הלשכה הדיגיטלית וכל הקוד מקור ולהבין
איך הכל מתחבר יחד להחזיק ראש על כל האפלקציות הקיימות והליבה וכל קובץ בקוד מקור הכל ממופה ומאורגן … כדי שתבין את
התכלית של הלשכה ותפעל … להגשים את התכלית בצורה הטובה ביותר».

**How this was made.** Every tracked file was indexed from the source itself (5,908 files, 1.41 million lines), every
`app.json` was read into one table (70 apps), and seven read-only readings of the code were written by area, each
claim with its `path:line`. This page is the synthesis; the detail is beside it:

| What | Where |
|---|---|
| every file: path, kind, lines, last change, its own first words | `ci-artifacts/dgo-source-map/files.tsv` (generated, not tracked) |
| every app: names, layer, gives / needs, routes, services, the four channels, size | `ci-artifacts/dgo-source-map/apps.tsv` · sizes per area and unit: `areas.tsv` beside it |
| the readings, with `path:line` | `research_notes/DGO source map 2026-11/`: `01-core-compiler-and-cli.md` · `02-platform-base.md` · `03-herd-links-and-offices.md` · `04-agents-ai-and-observation.md` · `05-apps-documents-and-communication.md` · `06-apps-business-web-and-tools.md` · `07-release-packaging-ci-gates.md` |
| the review of the decisions and the plan to one binary | [dgo-architecture-2026.md](dgo-architecture-2026.md) |
| the July map this page replaces (INDOX's inner layers, its API contract) | [archive/indox-pre-2026-09/architecture-map-2026-07.md](archive/indox-pre-2026-09/architecture-map-2026-07.md) |

To generate the three tables (16 seconds, read-only; a Python with PyYAML, from the repository root):
`python3 "research_notes/DGO source map 2026-11/source-map.py" ci-artifacts/dgo-source-map`. They are not tracked:
a table of every path also names the parked tree, and the gate on references into it refuses that in a tracked file.

---

## 1. The purpose

In the owner's words:

- «the best human–digital interface the world has seen — all the world's open source at the click of a button, and
  one perfect set for running a business, a company, personal life, development and content creation, all from
  inside the office's shell» (2026-10-30).
- The product is «a binary at the base + a collection of apps» that gives full management of a business in ONE
  install; «every app … up to all standards with full UI, API and CLI, actionable from agents and humans» (2026-10-30).
- «the best one click setup for full scale business / software / company run … operating system of the future cause
  its basically decentralised cloud running on any device and connecting with each others so i can transform any 5
  computers into 1 dgo that just has all compute resources of all accessible where you want» (2026-11-10).
- The end of the road is **DGO net**: one public app on the company's server that serves ten services to every
  office — accounts, apps, news, operatives, domains, compute, public-route, llm, dgo cloud, payments
  ([dgo-net.md](dgo-net.md)).

What follows from it — five questions every piece of work answers:

1. **Does it install from one download on every operating system?** (Linux, Windows, macOS, a server, a phone.)
2. **Is the app whole?** A screen, a CLI, an API and a flow of events — so a person and an agent can both run it
   and both can see it running.
3. **Does it work across the herd?** Any office can open it, and work can run on the machine that has room.
4. **Is it declared?** Nothing the owner types, nothing made by hand on a host, nothing that lives outside the office.
5. **Is it generic?** A client's need comes back as something the next business gets for free.

---

## 2. The office in one page

**The directory is the layer.** `platform/` is layer 0, the compiler. `platform-base/` is layers 1–2, what every
office gets. `apps/` is layer 3, one directory per app. An app declares itself in `app.json`; the compiler turns the
declarations and the office's state into `.generated/`; Docker Compose runs what was generated; Traefik is the door.

**From `git clone` + `./bbox run` to a running office** (the full chain with line numbers is reading 01, §1):

1. `bbox` (bash) sources `scripts/lib.sh`. On macOS every verb is handed into the Lima engine; on Windows `bbox.cmd`
   hands it into WSL.
2. Admission: the office's branch, the engine, one heavy slot (`heavy_admit`: a lock and a memory floor), disk.
3. `.env` and secrets are ensured; then `platform/manager/reconcile.py render` compiles.
4. The compiler: load every `app.json` (the directory enforces the layer) → load the state → validate → **resolve**
   (which apps are on, which app provides each capability another needs, in what order) → **render** `.generated/`:
   one compose file that includes each ordered app's own compose, the routing labels, the connections overlay, the
   registries the console reads, the agents' context, the office's Obsidian vault, the plan of apps served to and
   from linked offices.
5. Per app: its `hooks/prepare`, then `docker compose up --wait`, then `hooks/refresh` and `hooks/onboard`.
6. The control plane (`app-management`) reconciles what is left; the run prints its problems.

**The contract an app signs** (`platform/schema/app.schema.json`; reading 01, §2):

| field | what it does |
|---|---|
| `id`, `layer`, `kind`, `people` | identity; where it may live; `people: admins` puts the admins-only door on its routes |
| `capabilities[]` | what it GIVES — a named capability with an endpoint or interface (its API) and its operations |
| `use[]` | what it NEEDS — a capability, how strongly (`requires` pulls a provider in, `wants` does not), and ordering |
| `routing[]` | its hosts, ports and `auth` (`sso` unless said), and `module` — its tile in the console |
| `compose`, `connections[]`, `data`, `health`, `agent.context` | its services; the secrets it registers; its volumes; its probe; its `AGENT.md` brief |
| `hooks/<verb>` (files, not a field) | its CLI: `bbox <app> <verb>` runs `apps/<id>/hooks/<verb>` |

Not enforced by the compiler today, although declared: `resources` (shown only; CPU comes from the performance
profile, memory from a gate), `system`, `lifecycle` (no reader).

**State.** `platform.state.default.yaml` is the product's default (17 apps on). `platform.state.yaml` is one office's
own set — which apps are on, by whom, and the `remote:` block of linked offices' apps. `.env` holds config and
secrets; `BUSINESS_NAME` is the one line a new office edits and the rest derives.

**The four channels** every app is asked to have: **ui** (a route and a tile), **cli** (`hooks/`), **api** (a
capability with an endpoint), **flow** (events on the office's stream `dgo:flow:<app>`, which «כל מקביל» draws as
rows). Today 57 apps have a screen, 60 a CLI, 48 a declared API, 18 a flow — **15 of 70 have all four**.

---

## 3. What every office gets — the base (`platform-base/`, reading 02)

| unit | Hebrew | what it is |
|---|---|---|
| `traefik` · `https-redirect` | נתב הקצה | the edge on :80/:443; reads the engine only through a GET-only socket door |
| `forward-auth` · `authentik` | זהות וכניסה | sign-in. forward-auth (one Go binary) is the default since October; authentik remains the fallback and its names remain in the middleware and headers |
| `postgres` · `redis` | בסיס נתונים · מטמון ותורים | ONE shared Postgres (six apps in one database) and one Redis: cache, queues, locks and the event stream |
| `connections` | חיבורים ומפתחות | the vault of secrets and a broker that names its caller from the engine |
| `app-management` · `containers` | ניהול אפליקציות · מכולות | the control plane: install, enable, disable — by calling the compiler and `scripts/dc` |
| `console` | המרכז | the shell: tiles from the compiled registry, every app framed same-origin at `/a/<alias>/` |
| `bina-ui` | ספריית ממשק | the one palette («Olive Grove») and the shared blocks; apps carry stamped copies, kept identical by a gate |
| `machine` · `security` | מכונה · אבטחה | the host's figures; the door log and verdicts (server offices only) |
| `notifications` · `glitchtip` · `autoheal` | התראות · מעקב שגיאות · ריפוי עצמי | notices and web push; error tracking (off by default); restart of opted-in unhealthy containers |
| `data-management` | ניהול נתונים | backup and restore: inventory, archives, a restic store for the herd |
| `follow-runner` | מעקב אחרי הגרסה היציבה | takes the newest green commit of `dgo-stable` every 30 minutes, where no host timer can |

---

## 4. How the apps connect — the capability graph

59 capabilities tie the 70 apps together (`apps.tsv`, columns `provides` and `uses`). The ones most others stand on:

| capability | given by | needed by |
|---|---|---|
| `identity` | forward-auth (authentik) | 28 apps |
| `kv` | redis | 20 |
| `secrets` | connections | 19 |
| `notify` | notifications | 13 |
| `ui-kit` | bina-ui | 12 |
| `sql` | postgres | 11 |
| `workflow` | n8n | 8 |
| `computers` | computers | 4 |
| `ledger`, `browser` | apitools, browser42 | 3 each |

No capability is needed without a provider. 26 capabilities are given and needed by no other app yet — most are an
app's own API waiting for its first consumer (`office-agent`, `claude-agent`, `git`, `esign`, `news-feed`, `tv` …).

---

## 5. Every app

Columns: **gives** / **needs** are capabilities; **U C A F** = screen, CLI, API, flow; **default** = on in a fresh
office; **lines** = tracked lines in its directory.

### Layer 1–2 — `platform-base/`

| app | Hebrew | gives | needs | U C A F | default | lines |
|---|---|---|---|---|---|---:|
| `app-management` | ניהול אפליקציות | control-plane | data-management | UCA· | on | 10,073 |
| `authentik` | משתמשים וכניסה | identity, forward-auth | sql | UCA· | off | 2,012 |
| `autoheal` | ריפוי עצמי | – | notify | ···· | on | 1,626 |
| `bina-ui` | ספריית ממשק | ui-kit | – | ···· | on | 25,158 |
| `connections` | חיבורים ומפתחות | secrets, connection-instances | kv, identity | UCAF | on | 7,432 |
| `console` | המרכז | shell | secrets, identity, ledger, notify, ui-kit | UCA· | on | 13,434 |
| `containers` | מכולות | container-runtime | – | ··A· | on | 81 |
| `data-management` | ניהול נתונים | data-management, backup-store | – | UCA· | on | 10,736 |
| `follow-runner` | מעקב אחרי הגרסה היציבה | – | notify | ···· | off | 325 |
| `forward-auth` | זהות וכניסה | identity | – | UCA· | on | 6,718 |
| `glitchtip` | מעקב שגיאות | error-tracking | sql, kv | UCA· | off | 1,215 |
| `https-redirect` | הפניה ל-HTTPS | – | – | ·C·· | – | 382 |
| `machine` | מכונה | host-metrics | – | UCA· | on | 23,740 |
| `notifications` | התראות | notify | kv, error-tracking, identity | UCAF | on | 4,996 |
| `postgres` | בסיס נתונים | sql | – | ·CA· | on | 696 |
| `redis` | מטמון ותורים | kv | – | ·CAF | on | 1,176 |
| `security` | אבטחה | security | identity, notify | UCA· | – | 9,606 |
| `traefik` | נתב הקצה | edge | identity | UCA· | on | 2,648 |

### Layer 3 — the herd, the agents and the tools of the office itself

| app | Hebrew | gives | needs | U C A F | default | lines |
|---|---|---|---|---|---|---:|
| `dgo-extend` | הרחבת הלשכה | dgo-extend | computers, secrets, ui-kit, identity | UCA· | off | 50,600 |
| `computers` | מחשבים | computers | secrets, ui-kit, host-metrics, security, identity | UCA· | off | 33,387 |
| `terminal` | טרמינל | terminal | computers, identity, ui-kit | UCA· | off | 1,593 |
| `office-routes` · `lan-console` | ניהול רשת · הקונסול ברשת המקומית | – | control-plane, identity | U··· · ·C·· | – | 2,877 |
| `bina-ds` | בינה | office-agent | identity, secrets, workflow, notify, computers | UCA· | on | 27,864 |
| `bina-claude` | בינה קלוד | claude-agent | identity | UCA· | – | 4,465 |
| `raphael` · `operatives` | רפאל · אוסף האופרטיבים | – | workflow, notify | ·C·· | off | 2,748 |
| `ollama` | מודלים מקומיים | llm-local | – | UCA· | off | 2,198 |
| `openhands` · `google-workspace-agent` | סוכן קוד · סוכן Google Workspace | coding-agent | llm-local, secrets, workflow | U·A· · ·C·· | off | 8,402 |
| `browser42` | דפדפן | browser | concurrency-metrics | UCA· | off | 14,043 |
| `any-concurrency` | כל מקביל | concurrency-metrics | sql, kv | UCAF | off | 6,890 |
| `dashboard` | מרכז הבקרה | – | identity, kv, telegram, secrets | UC·F | – | 7,874 |
| `git` | ניהול גרסאות | git | identity, secrets, ui-kit | UCA· | off | 9,796 |
| `obsidian` · `archify` | אובסידיאן · ארכיטקטורה | – | – | UC·· | off | 1,880 |
| `portainer` · `redisinsight` · `supabase` | – | object-storage, data-api | sql, kv | U… | off | 1,309 |

### Layer 3 — the daily work: documents, messages, files, meetings, automation

| app | Hebrew | gives | needs | U C A F | default | lines |
|---|---|---|---|---|---|---:|
| `indox` | מסמכים | indox-api | identity, workflow, sql, secrets, kv, data-api, ocr, drive, mail, mail-organizer, chat, notify | UCA· | on | 196,773 |
| `apitools` | כלי מסמכים | ocr, ledger, speech | sql, secrets | UCA· | on | 27,986 |
| `documents` · `my-docs` · `esign` | מסמכים · מסמכים שלי · חתימות | documents, esign | identity, ledger, indox-api, kv, drive, notify | UCAF · UC·· · UCAF | – | 28,374 |
| `n8n` | אוטומציות | workflow, automation-stdlib, workflow-hooks | sql, kv, secrets, error-tracking | UCAF | off | 18,660 |
| `mail` | מייל | mail, mail-backend-local, mail-organizer | workflow, secrets | UCA· | on | 22,628 |
| `chat` · `element` · `slack` · `signal` · `telegram` | צ׳אט ומספקיו | chat, chat-matrix, chat-slack, telegram | workflow, secrets, notify, indox-api, kv, sql, identity | UCA· / UCAF | off | 42,167 |
| `meet` | פגישות וידאו | recordings | kv, identity, workflow, speech, notify | UCAF | off | 25,200 |
| `drive` · `drive-google` · `drive-local` | קבצים ומספקיו | drive, drive-google, drive-local | kv, workflow, secrets, sql, object-storage | UCAF / ·CA· | on | 25,536 |

### Layer 3 — the business, the web, content, and a client's own applications

| app | Hebrew | gives | needs | U C A F | default | lines |
|---|---|---|---|---|---|---:|
| `project-pln` | ניהול פרויקטים | – | identity, sql, kv | UC·F | off | 32,979 |
| `sites` | אתרים | sites | kv, computers, domains, digital-assets, notify, ui-kit | UCAF | off | 11,413 |
| `domains` · `domain-internic` | דומיינים · אינטרניק | domains, domain-internic | secrets, identity, sites, notify, browser, mail, kv | UCA· · UCAF | off | 14,935 |
| `digital-assets` | נכסים דיגיטליים | digital-assets, brand | identity, social, sites, ui-kit | UCA· | off | 73,147 |
| `social-list` · `telegram-tv` · `newsflow` | רשתות חברתיות · טלגרם TV · זרימת חדשות | social, tv, news-feed | identity, secrets, browser, notify, ui-kit | UCA· · UCA· · UCAF | off | 20,851 |
| `assets` · `examplem-io` | נכסים · דוגמה | assets, examplem | identity, kv | UCA· · UCAF | – | 10,534 |
| one client's own business application (not in the public tree) | – | – | – | UC·· | – | 40,314 |
| `cad` · `cad-api` · `calculator` · `hello-bina` | – | – | – | U… | – | 11,373 |

What the readings 05 and 06 found that the tables do not show:

- **The provider pattern** (a generic app per kind of work + one provider app per service, found by name) is complete
  only for `drive` ↔ `drive-local` / `drive-google`. `domains` still holds five providers inside itself and
  `social-list` eight; `chat` and `mail` choose their backends inside one app; `element` and `slack` serve the chat
  contract and nobody calls them.
- **The flow is missing where the work is heaviest**: `indox`, `mail`, `chat`, `apitools` and `bina-ds` publish no
  events, so their work does not appear in «כל מקביל».
- **`n8n` carries four apps at once** — INDOX's pipeline, the mail labelling, the meetings' transcripts and the
  WhatsApp API — and one shared database holds almost all of this area's data.
- **`project-pln` is one Plane for every office and every session** (60 calls a minute per key): it is the
  bottleneck of all planned work, and its outbox does not keep a batch that could not be sent.
- **A third business application of the same client group (loans) is a model and a plan, not an app.**

---

## 6. The herd — how offices become one (reading 03)

An office has one identity (an Ed25519 key and one WireGuard key). A **link** between two offices is a pair record on
each end, and five layers stand on it:

1. **WireGuard** — one interface and one /24 per pair; `net.py` renders it, the `dgo-net` container applies it.
2. **The path** — WireGuard's own UDP, or (when the record says `transport: tcp`) the Go carrier `dgo-carry` over one
   TCP connection: on the LAN, direct, through the far office's HTTPS door, or met at the hub's relay.
3. **The firewall** — nftables rendered from the same record: only the served ports may arrive; no peer-to-peer routing.
4. **The door** (`dgo-link`) — one listener per pair; the `Host` header picks the app; the peer's identity headers are
   stripped and replaced by a mapped user, the office's name and a signature.
5. **The catalog** — each office publishes a projection of its own compiled registry; every 60 seconds the other end
   pulls it into the `remote:` block of its state, and the compiler turns that into tiles, routers and aliases.

So office A opens an app of office B as a tile: A's console → A's Traefik → the alias `<app>.<B>` → A's door for that
pair → the tunnel → B's door → B's app, as B's mapped user. `bbox remote <office> <app> <path>` is one call through
the same way. `bbox via <office> …` runs a bbox verb on the far office — today by ssh into its host, which a
Windows/WSL office does not have. `scripts/follow.sh` is how an office takes the newest green commit of `dgo-stable`.
The herd itself is declared in `apps/computers/herd.yaml`.

**What heals by itself:** the source port, the /24 search, the carrier's redial and relay. **What does not:** a pair
record written the wrong way round, a vanished record, a UDP pair with no relay, the door and the carrier after a
boot where no heal timer runs.

**What is designed and not built** (`research_notes/DGO Dell office organisation 2026-11/`): one admit for heavy work
on a machine; the CI runner and the Android emulator as office apps; every run — a runner job, an ssh command, a
loaded model — reported to «כל מקביל»; and a **job door**, so an office accepts a named job from its herd. That door is
what turns «any five computers» into one pool of compute.

---

## 7. The agents, their models, and how work is seen (reading 04)

- **Azaria** (and Raphael, and the local preset) are presets of one harness in ONE container, `bina-ds`: every
  conversation, sub-agent and shell command of every agent runs there, with the engine's socket and the checkout
  read-write. **Bina Claude** is the official Claude desktop app inside an office, behind the same agent contract.
- A request reaches an agent from the console tile, from `bbox agent` (also `--office <office>` over a link), from a
  Telegram group through a relay, and from the office's clock (the «seder» — whose door refuses today).
- Models: remote providers called directly by the harness, or a local model through `ollama` (the capability
  `llm-local`); a linked office's Ollama is offered as a route. The in-office model router is a design, not code.
- **browser42** is the agents' hands on the web: ONE signed-in browser shared by every agent, a tab cap and a reaper.
- **Seeing the work**: `any-concurrency` («כל מקביל») draws spans from Docker, the edge, n8n and every app's flow
  stream; the agents appear only as polled lanes; its rows live in memory. 18 apps publish to the flow today.
- The agent's context is `AGENTS.md`, each enabled app's `AGENT.md`, and the office's Obsidian vault — compiled from
  `apps/obsidian/vault.yaml`, where this page is the note «מפת הארכיטקטורה».
- Found by the reading: the office's clock is effectively off (its door refuses without a budget meter that nothing
  sets); the «wake» paths feed a script that was deleted; after an update the harness still tells recent sessions
  to continue; no code handles a provider's «no balance» or rate-limit answer; the cost meter prices one provider.

---

## 8. The release line, the proofs and the gates (reading 07)

Each office commits on its own branch (`mac-dgo`, `hp-dgo`, `vps1-dgo`, `dell-dgo`); proven work is merged into
`dgo-stable` in batches; offices take `dgo-stable` by `follow`. A proof is `scripts/ci/gates.sh` — every gate of
`scripts/refactor/GATES.md` — and the Go tests, run by GitHub workflows on ONE self-hosted runner (the Dell). When
both pass on `dgo-stable`, `refs/green/dgo-stable` moves, and that ref is what an office follows. The public
repository is an export of the private one (`scripts/release/public/`). Binaries: `packaging/` holds the installer,
signing (`relsign`, `trust`), the macOS engine (Lima), Windows, Android, and `packaging/dgo` — the Go successor of
the compiler, the console's server and the control plane.

What reading 07 found:

- **No signed release is possible yet**: the installer's root-key file is empty until the owner's key ceremony; the
  only tag is `v0.2.0`.
- **One machine carries the whole release line.** Every proof — gates, Go tests, release binaries, Android, the
  export — runs on the one self-hosted runner. While it is away, `refs/green` does not move and no office updates.
- **The workflows that ran on GitHub's own runners are dead** — among them the only clean-machine install proof and
  the image build; and the full-stack proofs (`ci-verify`, `indox-e2e`, `ui-map`) listen on branches nobody pushes to.
- **Three packaging lineages exist and none is retired**: the old bundle installers, the native binaries signed by
  `relsign`, and the Python app catalog with its own key. First-party images build three ways.
- **The gates' list promises more than runs**: four gates are wired nowhere, four are marked as known failing.

---

## 9. Where the mass is

| area | files | lines | | language | lines |
|---|---:|---:|---|---|---:|
| `apps/` | 3,323 | 778,913 | | Python | 366,768 |
| `legacy/` (parked) | 247 | 125,368 | | JSON (mostly n8n blueprints) | 279,471 |
| `platform-base/` | 390 | 122,054 | | JavaScript + TypeScript | 313,211 |
| `scripts/` | 404 | 92,840 | | documents | 159,938 |
| `ai/` (context) | 336 | 66,835 | | YAML | 76,281 |
| `packaging/` | 226 | 64,101 | | Go | 57,665 |
| `digital-office/` (UI workbench) | 335 | 55,431 | | HTML + CSS | 72,264 |
| `issues/` | 325 | 26,797 | | shell + hooks | 41,954 |
| `platform/` (the compiler) | 38 | 15,229 | | | |

The largest units: `apps/indox` 196,773 · `apps/digital-assets` 73,147 · `apps/dgo-extend` 50,600 · `packaging/dgo`
41,598 · `apps/chimney-services` 40,314 · `scripts/refactor` (the gates) 33,642 · `apps/computers` 33,387 · `apps/chat`
33,348 · `apps/project-pln` 32,979. The compiler itself is one file of 4,831 lines.

---

## 10. What is in motion — the half-migrations

| from → to | where it stands |
|---|---|
| the Python compiler → the Go binary `dgo` | 17 of 22 verbs are native and proven equal to Python by oracle tests; **nothing in production calls it** — `bbox`, the control plane and every hook still call `reconcile.py` |
| authentik → forward-auth | forward-auth is the default; authentik is the fallback when `.env` has no `DGO_IDENTITY`; the middleware and the identity headers still carry authentik's name |
| the console's server and the control plane → `dgo` | Go twins exist, proven against Python, each rolled back by one variable; requests not yet proven are proxied to the container |
| INDOX's automation in n8n → Python | planned in six phases; the code is still n8n blueprints |
| one state file → a product default and an office's own record | the default exists; the office's own `platform.state.yaml` is still tracked in git, so a merge can carry one office's app set into another |
| hand-installed pieces on a host → office apps | the CI runner, the emulator, a heat guard and a memory sampler on the Dell |

Duplicated on purpose and held by gates: the palette and the shared UI blocks stamped into each app; three readers of
`app.json` (the compiler, the catalog, the control plane and its Go twin); three writers of `.env`.

---

## 11. The single points of failure

1. **`platform/manager/reconcile.py`** — every compose call of every verb passes through it.
2. **The public server** — the hub, the relay of every TCP link, the door a laptop uses away from home.
3. **The `bina-ds` container** — every agent; any recreate ends every running turn.
4. **One CI runner** — every proof of every lane; with many pushes a proof is cancelled before it ends.
5. **One shared Postgres database** — six apps.
6. **The `dgo-net` namespace** — one restart is every link down.
7. **`dgo-stable` + `refs/green`** — what every office follows; a red or missing proof stops the herd's updates.
8. **The office browser** — one signed-in profile for every agent.

---

## 12. The road from here to the purpose

The plan to one binary per machine is [dgo-architecture-2026.md](dgo-architecture-2026.md) §6, eleven steps: publish
and sign → the stub → `dgo` as the CLI → the compiler native → the control plane and the state store → the console in
`dgo` → the vault → the identity cutover → `dgo net` → the store → layer 0 as the download. Measured against the five
questions of §1 on 2026-11-10:

| question | where the office stands |
|---|---|
| one download on every OS | a private tag v0.2.0; the public repository's newest release is a pre-release; Android releases are drafts; the Go compiler is proven and not live |
| every app whole | 15 of 70 apps have the four channels; 52 publish no flow, so they do not show in «כל מקביל» |
| across the herd | apps open across a link; work cannot yet be SENT to another office (no job door); one office of the herd cannot be driven at all |
| declared | the base and the apps are; a host's own pieces (runner, emulator, guards, swap) are not |
| generic | client-specific applications and code still live inside generic apps; the template's example company is not yet a neutral one |

## 13. Keeping this map true

The tables are generated — regenerate them, never edit them. A reading is dated; when its area changes much, read it
again and replace the file. This page changes when a layer, a capability or a half-migration changes — the same
commit that changes the code.
