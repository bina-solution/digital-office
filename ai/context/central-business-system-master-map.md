# deployment-hacohen → Central Business System: Master Map & Path to a Product

Status: **understanding + product map** (companion to `central-business-system-plan.md`). Branch:
`claude/centralized-business-system-qs1edt`. Built from a full read of every service (both submodules
cloned: `production/apitools`, `production/chat`) plus web research on how this class of
product is shipped.

**The ask.** Collapse the whole estate into ONE business webapp — same look as פנקס/דרייב/מייל — that
unifies dashboard, ledger (פנקס), drive, mail, incoming documents, the chat service,
any-concurrency, alerts (GlitchTip API), machine, apps (homepage), system validation
(feature-validation), settings + **access-key management** + connections, and an **install screen**.
And: **solve the access-key problem once and for all** (text / QR-barcode / OAuth keys) with one service
that centralizes them, streams them from `.env` for a friction-free boot, and asks in the installer only
for what's missing. Target shape: **a single installable product each business runs locally** — like
desktop software you install, run, and it just works, with state kept locally and stable.

---

## Part 0 — Executive summary (read this first)

**What it really is today.** Not one app — a **fleet of ~40 containers** across ~17 stacks, wired by
Traefik, unified at the edges by **Authentik SSO** and a **homepage** dashboard. Most first-party
surfaces (`morning`/פנקס, `localdrive`/דרייב, `mailview`/מייל, `machine`, `any-concurrency`) are already
small BFF + RTL-SPA services in one shared "morning/פנקס" style. The business core is an **n8n state
machine** that turns Gmail/Drive documents into rows in one `incoming_documents` ledger, using
**apitools** for OCR and Gemini/Document-AI for extraction.

**The three headline findings** (things that change the plan):
1. **The ledger backend does not exist yet.** `morning` (פנקס) is a complete RTL SPA that calls
   `/api/documents`, `/customers`, `/items`, `/business`… but the only thing it can proxy to
   (`apitools`) is **OCR-only** — it implements none of those routes. The "INDOX Books" accounting
   engine (`doc_models`/`doc_gen`/`doc_data`, Israeli compliance) is **designed** (`indox-books-
   product-design-map.md`) but **not built in `production/`**. So פנקס is a front-end over a missing
   backend today.
2. **WhatsApp is Baileys embedded in the chat service, NOT Evolution.** The running bot pairs via a Baileys
   `useMultiFileAuthState` QR and stores the session as files in `data/auth_info`. The
   `WHSP2_EVOLUTION_*` and `CHATBASE_*` keys in `.env` are **declared but unbuilt** (no container, no
   code) — a planned second WhatsApp account + multi-account layer, not current infrastructure.
   *(This corrects the `.env`-only impression that WhatsApp runs on Evolution.)*
3. **The whole thing is single-business, and hardwired to "Hacohen."** The design was re-scoped
   (2026-07-08) from multi-tenant SaaS to **one deployment = one business**. But the "one business" is
   still literally BINA/Hacohen: domain, org name, admin emails, Gmail address, allow-listed IPs, Google
   Sheet/Drive/Label IDs are hardcoded across compose defaults, blueprints, and n8n nodes. Turning this
   into "install for ANY business" is mostly a **config-routing + secret-generation problem**, not a
   logic rewrite.

**The verdict / path.** Three additive moves get to the product (detail in Parts 6–8):
- **(A) A `connections` service** — the single credential plane (text/OAuth/QR), with a
  `store → .env → install-wizard` resolution chain. This is the stated pain and the highest-value first
  ship. Back it with **Infisical** (text) + a **Nango-shaped OAuth broker** + a **QR pairing UI** for
  Baileys. Generalize the n8n `credential_overrides` `.env`-seed mechanism deployment-wide.
- **(B) An install wizard** driven by a per-service **connections manifest** — auto-mints machine
  secrets, asks only for the human/OAuth/QR gaps, parameterizes every "Hacohen" literal from one
  "business name + domain" input.
- **(C) A `console` shell** — one RTL portal that federates the existing BFFs behind the SSO + homepage
  registry that already exist. Plus finishing the **ledger backend** (the one genuinely missing engine).

---

## Part 1 — System topology at a glance

One Debian host, one Docker Compose project from repo root, behind Traefik. `compose.yml` (traefik) →
`include:` `production/compose.yml` (17 stacks) + `production/compose.override.yml` (routing + homepage
labels). Every container is `<svc>-${DEPLOYMENT_NAME:-bina-deployment}` on the external
`traefik-network`; routes are `<svc>.${DEPLOYMENT_DOMAIN}` + `<svc>.localhost`; TLS via Let's Encrypt
(`myresolver`, HTTP-01).

**The ~40 containers by role:**
- **Edge/identity:** traefik, authentik (server + worker + postgres + bootstrap-sentinel).
- **Data/infra:** supabase (db/kong/rest/storage/studio/meta), redis + redisinsight, portainer.
- **Automation core:** n8n (main + worker-1 + worker-2 + task-runners) + n8n-postgres.
- **Business apps:** apitools (OCR, in-tree), chat (Baileys, in-tree),
  morning/פנקס, localdrive/דרייב, mailview/מייל, inbox, localmail (GreenMail+Roundcube),
  indox-demo-docs.
- **Ops/observability:** homepage (dashboard), glitchtip (alerts, 5 containers), machine (host metrics),
  any-concurrency (timeline), browser42 (stealth Chromium + MCP + noVNC).
- **Dev-only (not in prod include):** feature-validation (fv), incoming-documents (FastAPI+Kafka rewrite),
  openhands, librechat, etc.

**How it boots (`bbox` = the deployment CLI):** `bbox install debian` (docker/git/node + network +
portainer pw) → `cp .env.ex .env` + hand-edit secrets → `bbox run` (compose up with Authentik
head-start + `--wait` on the SSO readiness sentinel) → `bbox onboarding` (restore browser42 state → wait
n8n REST → `n8n-push` blueprint: owner + 25 creds seeded from `.env` + ~62 workflows published/activated
→ verify → INDOX seed). CI runs this on every push and asserts a **25-check scorecard** (`.ci-cd/`).

---

## Part 2 — The unifying layers that ALREADY exist (what a shell builds on)

A unified product does **not** start from scratch — four unifying layers are already load-bearing:

1. **Authentik ForwardAuth = one identity.** The `authentik` Traefik middleware calls the embedded
   outpost on every gated request; on success it injects `X-authentik-username / -email / -name /
   -groups / -uid / -jwt …` onto the upstream. Apps read identity from those headers with zero auth code
   (`morning /api/me`, `incoming-documents /auth/me`). Providers/apps are declarative
   (`authentik/blueprints/deployment-apps.yaml`).
   - *Gated (middleware=authentik):* homepage, machine, any-concurrency, redisinsight, ollama, traefik
     dashboard, incoming-documents, browser42 (except `/mcp`), supabase-studio, morning/drive/mail.
   - *Own auth (no ForwardAuth):* authentik (public for login), n8n, portainer, glitchtip, supabase kong
     API. **Gap:** apitools and feature-validation are public with NO Traefik auth despite intent.
2. **homepage = the module/apps registry via Docker labels.** `services.yaml` is empty; every container
   self-advertises with `homepage.group/name/icon/href/widget.*`. homepage reads `docker.sock:ro` and
   renders the grid. **A `console` shell can enumerate the entire product by reading these same labels.**
3. **Traefik routing convention** — label-driven, three routers per service, one TLS resolver, one shared
   `authentik` middleware; DB/cache exposed as TCP entrypoints (`postgres:5432`, `redis:6379`) with
   `HostSNI` + `ipallowlist` (`DBS_ALLOWED_IPS`).
4. **Supabase = the shared data substrate** — Postgres 15 (`supabase-db`) + PostgREST + storage + kong +
   studio. n8n does schema+CRUD straight to `supabase-db`; `localdrive` streams object bytes from the
   storage bucket. Single source of truth via root-`.env` `SUPABASE_*`.

> Implication: "one webapp, distributed services" = a thin **portal shell** over these four layers +
> the existing BFFs. Federate, don't rewrite.

---

## Part 3 — Domain deep-maps

### 3.1 Incoming Documents (the core pipeline)

The business core: Hebrew financial documents (invoices / delivery notes = "shipments" / purchase
orders / balance-sheet aging reports) arrive by **Gmail** and **Google Drive**, get OCR'd, classified,
field-extracted, cross-linked, and written as rows into one **`incoming_documents`** ledger, which is
itself the processing state machine. n8n is the "code"; **apitools** owns OCR + positional field
extraction; Gemini/Document-AI/Ollama own AI extraction. Two generations exist: the **n8n v1/v2 state
machine** (production) and a **FastAPI+Kafka rewrite** (`development/incoming-documents/`, not deployed).

**End-to-end flow — two level-triggered reconciliation loops.** *Sync is thin discover+idempotent-
register; the `incoming_documents` table does all the work.*
- **Loop 1 = sync (discover→register), ~15 min + Drive/Gmail triggers.** Gmail **Label Engine**
  classifies new mail and applies the automation label → **Sync Scanner** → **Sync Scan Unit** LISTs
  items in `to_sync` and CLAIMs them (`in_progress`) across sources `drive-gdoc`, `drive-bs`,
  `gmail-doc`, `gmail-bs`, `gmail-link` → per-source **Sync Processors** download + (gmail) upload to
  Drive + batch-register `incoming_documents` rows in chunks of 25 (md5 from Drive list = dedup, no
  download). No OCR at sync time. Registered row: `{ID, NAME, SOURCE_TYPE, SOURCE_ID, LINK, HASH:md5,
  SIZE, CREATED_AT, STATUS:'IN_PROGRESS'}`.
- **Loop 2 = the state machine, 30s poll + pg trigger.** A bounded poll (`updated_at > now()-150s …
  limit 6`) fires the driver per row: acquire doc lock → **Decide** (pure `(doc,cfg)→ACTION`) →
  dispatch ONE Action → write row + `ACTION_LOG` → unlock → re-GET by ID until a terminal STATUS.
  Actions: **OCR** (apitools `/documentOcr`, Google Vision, md5-cached) → **figure_company_id** (via
  Companies table) → **figure_document_type** → **query_* fields** (`/documentJsonQuery` positional
  "find after/above": INVOICE_ID, DOCUMENT_DATE, DOCUMENT_TOTAL_AMOUNT, PURCHASE_ID, SHIPMENT_ID,
  IS_BALANCE_SHEET) → **AI extraction** (invoice Extractor Gemini `gemini-3.1-pro`/`2.5-pro`; Balance
  Sheet Extractor v2 — both cached in Postgres `ai_extraction_cache` keyed `invoice:<md5>`/`bs:<md5>`)
  → **update_name** (rename Drive file), **find_link**, **check_from_office**, **extract_shipment_ids**,
  **link_documents** (cross-link invoices↔shipments↔BS lines) → **mark_completed** → optional
  **priority_sync** (Priority ERP) → downstream **WhatsApp Send Document**. Every write funnels through
  **Batch Upsert**; the data front door is **indox api** (`indoxApiRouter01`) → supabase or Google
  Sheets per the backend toggle.

**The state machine — where state lives:**
- **`incoming_documents` table** (Supabase, or the Google Sheet `מסמכים נכנסים` tab, 52→68 cols, PK
  `ID`): the row **is** the state (`STATUS` + field columns + `ACTION_LOG`).
- **Redis:** doc lock `process_lock` (TTL 10 min); toggles `n8n.indox.data_backend` (`sheets|supabase`),
  `n8n.indox.main_version` (`v1|v2` driver swap), `n8n.label-engine.settings`.
- **`ai_extraction_cache`** (Supabase, `expire:false` — must survive resets).
- **`sync_ledger`/`sync_attempt`/`sync_cursor`** (Supabase, sync-v3) — sync-private memory, PK
  `(source, platform_id)`.
- **Kafka topics** `incoming-documents.<repo>` — dev rewrite only; no broker in the prod path.
- **Lifecycle STATUSes:** `IN_PROGRESS` → `MISSING_COMPANY_ID`/`UNKNOWN_COMPANY` → `MISSING_TYPE` →
  (GDOC) `API_TOOLS_FAILED`/`MISSING_LINK` / (BS) `EXTRACTION_FAILED` → `COMPLETED`(+ variants
  1/2/3/4 for missing-shipment/old-date/old-doc). Guards: `MAX_ITERATIONS` (`max_actions_per_doc`=50),
  old-doc window (`OldDocumentMonthsBack`=24), and a Terminalizer (stale IN_PROGRESS >15 min →
  `NEEDS_REVIEW`). **v2** splits Decide (proven byte-identical to v1 on 46 fixtures) + Driver + Action
  collections, swapped via the `main_version` redis toggle.

**The sync model:** settings-driven directory **PAIRS**, auto-discovered, up to 10 per type:
`GeneralDocsSourceFolderN → …DestFolderN` (+ Fails), `BalanceSheetSourceFolderN → …DestFolderN` (type
forced BALANCE_SHEET by folder). **Drive state = folder** (move source→dest); **Gmail state = label**
(`to_sync`/`in_progress`/`synced`/`failed`, batched to avoid IMAP OVERQUOTA). **sync-v3** reframes it as
ledger reconciliation (`desired − ledger`, deliver-before-record, HASH unique-index dedup). Local
emulation: `drive api - local` + **localdrive** UI and `inbox` LOCAL mode (GreenMail) let the
Scanner treat local uploads like real Drive/Gmail for CI/demo.

**Services touched:** n8n (5678, internal `http://n8n:5678`), n8n-postgres, apitools (8080, internal
`http://apitools:8080` — registers only `/documentOcr`, `/documentJsonQuery`, `/pdfToJpeg`, `/docExists`,
`/health`; **`/columnExtraction` & `/findOptionMatching` are NOT routes** — they're feature-validation
scenarios over `/documentJsonQuery`), redis, supabase-db + storage/kong, inbox (8970), localmail,
localdrive (8975), indox-demo-docs (8088). Kafka/Redpanda = dev rewrite only.

**Keys/settings:** env→n8n creds (via `credential_overrides`): `GEMINI_API_KEY`, `GOOGLE_VISION_API_KEY`
(blocks OCR if empty), `SUPABASE_*`, `REDIS_PASSWORD`, `POSTGRES_*`, `BS_WEBHOOK_*`, `SETTINGS_AUTH_*`,
`N8N_WEBHOOK_*`/`N8N_API_KEY`, `N8N_GOOGLE_OAUTH_CLIENT_*`/`N8N_GMAIL_OAUTH_CLIENT_*` (via
`CREDENTIALS_OVERWRITE_DATA`), `KAFKA_*`, `DOCUMENT_AI_SA_*`, `OLLAMA_INTERNAL_URL`, `OPENAI_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `CHAT_AUTH_*`, `PRIORITY_*`, `MCP_AUTH_TOKEN`, `GMAIL_IMAP_*`, `LOCALMAIL_*`.
**Per-tenant Google OAuth refresh tokens** (Gmail/Sheets/Drive/Sheets-Trigger) are NOT env-managed — the
onboarding pain. **Runtime `settings` table keys:** the sync folder pairs, legacy folder keys,
`sync_registry`, `OldDocumentMonthsBack`, `max_actions_per_doc`, `activePrioritySync`; the **Companies**
tab (name+ח.פ.+AI hints — private business data) and **Tag-Settings** taxonomy.

**Productization gaps (clone→install→works for a NEW business):** *a config-routing problem, not a logic
rewrite.* (1) **Account-specific Gmail label IDs baked into 14+ nodes** → resolve labels **by name** via
the Label Engine. (2) Hardcoded prod URLs in ~35 workflows → internal hostnames / `$env` (largely done).
(3) Hardcoded Sheet/tab IDs in ~15 workflows → one config source written at setup. (4) Companies +
Tag-Settings are private business data → must be seeded per tenant. (5) OAuth = the one non-automatable
step (create client once via browser42; per-tenant is just consent). (6) Exists already:
`indox/demo-company-state.yml` blueprint, `provision.js`/`rewire.js`, the dev `POST
/incomingDocuments/repos` idempotent provisioner. **Missing for one-click:** a "Tenant Setup" workflow
(`indoxSetupWF001` scaffold) that provisions the Drive tree + settings/data sheets + base labels and
writes all IDs back into the tenant's `settings`/`sync_registry`.

### 3.2 פנקס / Ledger (morning + apitools)

**What the ledger IS.** `morning` (brand **פנקס**, title *"פנקס · ניהול מסמכים עסקיים"*) is a
single-business RTL SPA cloning the morning.com / Green-Invoice "issue a compliant Israeli business
document in seconds" experience. It is a **thin BFF only** (~70 lines): serves the SPA and blind-proxies
`/api/*` to a document backend. **All ledger logic lives in the backend it proxies to.** Five views:
**לוח בקרה** (dashboard: total receipts, KPI strip, 12-month income chart from `GET /api/documents`),
**מסמכים** (status-chipped table), **לקוחות**/**פריטים** (CRUD registries), **הגדרות עסק** (singleton
business profile; first run forces an onboarding modal: name, ח.פ/עוסק type patur|murshe|company, VAT,
`doc_start` numbering). Document editor: `INVOICE`/`INVOICE_RECEIPT`/`RECEIPT`/`QUOTE`/`ORDER`/`SHIPMENT`
with live VAT (default 18%), draft-vs-issue, a PDF drawer (`/api/documents/:id/download`), an event log
(create/issue/send/pay/cancel/convert), and line-level conversions (QUOTE→ORDER→SHIPMENT→INVOICE→…).
Product intent (`indox-books-product-design-map.md`): "INDOX Books" — Israeli-compliance accounting
(gapless per-type/tax-year numbering, SHA-256 tamper chain, 7-year retention, allocation-number/
חשבוניות-ישראל ₪5k threshold, CMS signing, מבנה-אחיד export). Re-scoped 2026-07-08 to **single-business**
(singleton `business_settings`, no RLS/tenancy).

**apitools API surface — OCR ONLY** (`src/api/__init__.py`): `/` + `/health`; `/pdfToJpeg` (PDF→stitched
jpeg); **`/documentOcr`** (Google Vision `DOCUMENT_TEXT_DETECTION`, result cached on disk by MD5;
`?ocr_engine=local|google`); **`/documentJsonQuery`** (position-based extraction over cached OCR:
`action` ∈ `find after/before/above/below` with `value_validations`, or `find option`; `?draw=true`
debug overlay); `/docExists`. Identity = **MD5 of content** (`file_id`). **No database** — source of
truth is the on-disk `.storage/` volume (`files/`, `ocr_cache/`, `ocr_pdf_images/`, `ocr_drawings/`).

**The critical gap.** The endpoints `morning` actually calls — `/api/business`, `/customers`, `/items`,
`/documents` (+ `/download`, `/events`, `/convert`, `/issue`, `/send`, `/pay`, `/cancel`) — **exist
nowhere in the apitools submodule.** apitools is OCR-only; the `doc_models`/`doc_gen`/`doc_data` Books
engine described in the design map is **not present in `production/`**. As shipped, `morning` is a
front-end against a missing backend (every `/api/documents` call 404s/502s). **This is the single biggest
build item for the product.** The ledger's intended store is Supabase/Postgres (`document`, `customer`,
`item`, `doc_counter`, `business_settings`, `audit_log`) — but no code in this cluster opens it.

**Auth/identity:** `morning` trusts Authentik forward-auth entirely (reads `X-authentik-*` at
`/api/me`; forwards them upstream; downgrades apitools' `X-Frame-Options: DENY`→`SAMEORIGIN` so the PDF
drawer iframe renders). No role/capability gating yet.

**Where each runs:** morning (container `morning`, Flask/gunicorn, :8000, `Host(${MORNING_BASE_URL})` +
`morning.localhost`, behind `authentik`). apitools (container `apitools`, Python + poppler + tesseract-
heb/eng, gunicorn 4 workers, :8080, `Host(${APITOOLS_BASE_URL})` with an `apitools-retry` middleware,
**no Authentik middleware — reachable directly**; storage volume; 4 CPU/4G; `stop_grace_period 120s`).

**Keys/settings:** morning: `APITOOLS_URL` (default `http://apitools:8080` — where the Books backend must
be pointed), `MORNING_BASE_URL`. apitools: **`GOOGLE_VISION_API_KEY`** (text-secret; **⚠ hard-coded
leaked fallback key at `ocr_processor.py:19`**), `OCR_ENGINE` (`google|local`), `SENTRY_DSN`, plus
throughput knobs (`APITOOLS_MAX_CONCURRENT_OCR/JSON_QUERY`, timeouts, `GUNICORN_*`, `MAX_CONTENT_LENGTH`
50 MB). The ledger's future backend will need `SUPABASE_*`, `INDOX_DATA_BACKEND`, and the legal layer
(`SIGN_CERT_P12`/`_PASSWORD`, `ITA_ALLOCATION_URL`/`_TOKEN`).

**Productization gaps:** (1) **build the ledger backend** (biggest). (2) wire Supabase for the ledger.
(3) **remove the hard-coded Vision key** (`ocr_processor.py:19`). (4) apitools is unauthenticated —
unacceptable once it serves ledger data. (5) auth is trust-the-header with no role enforcement.
(6) collapse stale multi-tenant machinery to a singleton business. (7) compliance essentials (signing
cert, ITA allocation, gapless numbering, tamper chain, מבנה-אחיד) are designed but absent.

### 3.3 WhatsApp bot + admin (chat)

> **Two WhatsApp layers, NOT the same.** (a) **Runs today:** `chat`
> (`production/chat`, package `baileys-bot` v0.7.4) embeds **Baileys directly** — no
> Evolution, no separate service. (b) **Declared, not built:** `WHSP2_EVOLUTION_*` (Evolution API) and
> `CHATBASE_*` (multi-account manager) exist ONLY in `.env`/docs — no compose, no code, no container.
> Treat them as a future second account, not current infra.

**What chat IS.** One Node.js process running two things (`src/main.js`): an **Express 5 + EJS admin
panel** (server-rendered, `express-session` login) showing bot status/number/subscriber-count + quick
actions; and a **Baileys WhatsApp bot** — a Hebrew chatbot for "חברת הכהנים" (numbered menu, referral/
lottery, per-user daily limits, subscribers in NeDB `data/subscribers.db`, archive `data/wa_archive.db`).
A business user logs into `chat.<domain>`, scans a QR to connect the org's number, then manages
subscribers/broadcasts and **sends/receives financial documents**. Admin menu options drive intake
(10=aging/balance report, 11=invoice/delivery note, 12=document-from-link).

**The QR "key" mechanism (the `paired`/QR case).** In `src/whatsapp/baileyes_app.js`: on boot it imports
Baileys v7 (ESM), calls `useMultiFileAuthState(AUTH_INFO_PATH)` where **`AUTH_INFO_PATH =
/app/data/auth_info`**, and creates a socket. On `connection.update` Baileys emits `update.qr`; the raw
string is stashed in `appProperties.qr_text` and rendered to a PNG by **`GET /api/bot/qr`** (only when
disconnected). The user scans once (WhatsApp → Linked Devices). After scan, Baileys writes credentials as
**files under `data/auth_info`** (refreshed on every `creds.update`), persisted via the bind mount
`…/chat/data:/app/data`. Reconnect: non-logout closes → exponential backoff reusing the
session; `DisconnectReason.loggedOut` (or `POST /api/bot/disconnect`) → **`fs.rmSync` the whole
`data/auth_info`** → fresh QR. So the artifact the unified `connections` service must absorb =
the `data/auth_info` session blob; the surface = the `/api/bot/qr` PNG. Plan target: keep Baileys, mirror
the session blob into the vault, render the QR + "re-pair" in the central UI.

**Message + document flow.** Inbound: `messages.upsert` → dev-group/agent hooks → `onMessage`; docs/links
run through **apitools OCR** (`DOCUMENT_OCR_ENDPOINT`, `DOCUMENT_JSON_QUERY_ENDPOINT`), guess company,
then **POST to the n8n "Incoming Documents" webhook** (`INCOMING_DOCS_WEBHOOK`) — so chat is a
WhatsApp-side **intake front-end** for the same INDOX pipeline. Outbound (all `isAuthenticated`):
`/api/bot/broadcast`, `/api/bot/send-document` (PDF thumbnail via poppler), `/api/bot/send`,
`/api/bot/send-image`, `/api/bot/create-group`. n8n's **"WhatsApp Send Document"** workflow
(`whatsappSendDoc01`) HTTP-POSTs `https://chat.hacohen.bina-solutions.co.il/api/bot/send-document` with
the `Chat Auth` basic-auth cred (`BmKlKWiEeZAxNWyi` = `${CHAT_AUTH_USER}`/`_PASS`).

**Where it runs:** container `chat`, `chat.${DEPLOYMENT_DOMAIN}` + `chat.localhost`,
**:3000**, own login (no ForwardAuth), `depends_on: n8n`, volumes `/app/data` bind + external `wa_media`.

**Keys/settings (live):** **`data/auth_info`** (the qr-paired session — deleted on logout → re-pair),
`CHAT_APP_BASE_URL`/`_PORT`, `AUTH_USERNAME`/`_PASSWORD` (= `CHAT_AUTH_USER`/`_PASS`, also the n8n
cred), `SESSION_SECRET`/`_MAX_AGE`, `ADMIN_PHONE_*` (+ hardcoded numbers in `config.js`),
`DAILY_MESSAGE_LIMIT`, `DEFAULT_COUNTRY_CODE`(972), `N8N_*_WEBHOOK`+`_USER`/`_PASS`,
`DOCUMENT_OCR_ENDPOINT`, `WHATSAPP_HACOHANIM_SENTRY_DSN`, `AGENT_RUNNER_URL/TOKEN`, `DISPATCHER_URL/TOKEN`,
`DEV_GROUP_JID`. **Declared-but-unused:** `WHSP2_EVOLUTION_BASE_URL/API_KEY`, `WHSP2_APP_BASE_URL`,
`CHATBASE_*`.

**Productization gaps:** (1) QR pairing is manual + un-surfaced (no wizard step, no re-pair alert — it
silently wipes `auth_info`). (2) session lives in a **hardcoded host bind mount**
`/home/solomonboltin/chat/data` → must become a named volume / vault blob. (3) admin phone
numbers hardcoded in `config.js`. (4) insecure `.env.ex` defaults (`AUTH_PASSWORD=12345`, committed
`SESSION_SECRET`). (5) Evolution/ChatBase are vaporware in-repo. (6) n8n workflow hardcodes the chat
hostname → template to `${CHAT_APP_BASE_URL}`.

### 3.4 Mail (inbox, localmail, mailview, gmail router)

**Architecture.** The system never uses Gmail's REST API for automations. A single Flask microservice,
**`inbox`**, presents a small HTTP contract mirroring the Gmail ops n8n needs, backed by **IMAP
(read/label) + SMTP (send)** over an app password. Endpoints: `/search` (Gmail-grammar `X-GM-RAW` or IMAP
criteria, UID-cursor pagination), `/message/<uid>` (full or `?meta=true` = attachment list, no bytes —
the Label Engine classifies on metadata only), `/labels`(+`/add`/`/remove`/`/create`/`/delete`),
`/append` (seeds a message — replaces Gmail API `messages.insert`, **no quota**; the reason IMAP was
chosen), `/send` (SMTP), `/healthz`, `/readyz`, `/stats`. **Canonical contract:** id = the Gmail hex id
(same value the OAuth Gmail node returns), labels = names (account-stable). Gmail is a **document source**
for Incoming Documents: scanners call `/search` → `/message?meta=true` (score) → `/message` (pull bytes)
→ `/labels/add|remove` (move mail through Hebrew pipeline labels). **Quota engineering** dominates the
design: a fixed read-pool (`GMAIL_IMAP_READ_POOL`=10 read + 1 write < Gmail's ~15 cap), a hex-id→uid
cache (0 SEARCH on repeated label ops), idle-gated noop, `@quota_retry` backoff `[2,5,10,20]` on
OVERQUOTA; single gunicorn worker, 12 threads (write conn is stateful + lock-guarded).

**Two credential paths + the router.** n8n **`gmail api` (`gmailApiRouter01`, active)** is a façade: a
`Pick Backend` Code node with a hardcoded `const BACKEND='imap'` (`'imap'|'oauth'`) → switch →
`executeWorkflow` to one of two sub-workflows with the identical `{op,params}` contract:
- **`gmail api - imap smtp` (`gmailApiImap01`) — ACTIVE.** Thin HTTP proxy to `http://mailapi:8970/…`.
- **`gmail api - oauth` (`gmailApiOauth01`) — FALLBACK.** Real Gmail API nodes (Google OAuth2 creds). Must
  resolve name→`Label_NN` ids per call, and **`append` is a no-op** ("only supported by the imap
  backend" — OAuth can't seed without `messages.insert` quota).
**Why app-password IMAP:** the Gmail API is quota/OAuth-fragile (250 units/s, insert=25, daily caps,
token re-auth, 429 cascades); a 16-char app password + IMAP/SMTP sidesteps all of it and supports
seeding.

**LOCAL mode** (`entry.py` selects by `GMAIL_IMAP_MODE`; `local`→`local_app.py`): points at **GreenMail**
(`localmail`) for dev/CI. All mail in INBOX (`id == hex(INBOX UID)`); labels = **custom IMAP keywords**
(`kw<base32>` atoms, registry in `/data/labels.json`, mirrored to IMAP folders purely so **Roundcube**
shows them); Gmail-query grammar translated to IMAP SEARCH. Deterministic, no OVERQUOTA. GreenMail store
is in-memory (restart wipes; CI seeds per run; source of truth is the table + Drive).

**mailview** (`מייל`): a read-only + tagging RTL SPA (same פנקס/morning style) that talks **only** to
`http://mailapi:8970`, so it renders whichever backend `GMAIL_IMAP_MODE` selects. Proxies
`/api/messages` (label/text/`view=attention` = failure-labeled mail), `/api/message`, `/api/attachment`
(stream on demand), `/api/doc-context` (pipeline state via n8n `mail-api` webhook), and its one mutation
`/api/tag`.

**Where each runs:** inbox (`inbox`, **:8970**, internal, no route); mailserver (GreenMail,
IMAP 3143/SMTP 3025); webmail (Roundcube, `email.localhost`, :80); mailview (`mail.localhost` /
`mail.${DEV_DOMAIN}`, **:8976**, behind `authentik`).

**Keys/settings:** `GMAIL_IMAP_MODE` (`gmail|local`), `GMAIL_IMAP_USER` (identity), **`GMAIL_IMAP_APP_PW`**
(16-char Google app password — full mailbox access), `GMAIL_IMAP_HOST/PORT` (imap.gmail.com/993),
`GMAIL_SMTP_HOST/PORT`, pool/idle tuning; LOCAL: `LOCALMAIL_USER/PW`, `LOCALMAIL_IMAP/SMTP_*`,
`LABEL_REGISTRY_PATH`; mailview: `GMAIL_IMAP_URL`, `N8N_URL`; GreenMail/Roundcube `GREENMAIL_OPTS` /
`ROUNDCUBEMAIL_*`; router: `GMAIL_BACKEND` (resolved at push time), Google OAuth2 client creds in n8n
(for the oauth fallback).

**Productization gaps:** the **mailbox connection is the hard onboarding step** — per business: enable
2-Step Verification, create a 16-char app password (buried UI), set `GMAIL_IMAP_USER`/`_APP_PW`, recreate
`inbox`, verify `/healthz`. Non-trivial for a non-technical user; done semi-manually / via browser42
today. App-password vs OAuth tradeoff: app-password = no consent/quota + supports seeding, but full
mailbox access + manual 2SV; OAuth = friendlier + scoped, but quota, **can't append/seed**, per-call
`Label_NN` mapping, redirect-URI pitfall (`127.0.0.1:5678`). The backend is a hardcoded `const
BACKEND='imap'` baked at push time (no live toggle). A product needs a **guided mailbox-connect flow**
with credential injection, not `.env` hand-editing.

### 3.5 Supporting services, SSO & infra

Per-service map (role · container · route · port · notes):
- **traefik** — edge proxy + TLS + ForwardAuth injector. `traefik:v3.3`, entrypoints web:80/websecure:443/
  postgres:5432/redis:6379, dashboard :8080 (off by default). `traefik.<dom>` gated by `authentik`.
- **homepage** — the dashboard + apps registry. `ghcr.io/gethomepage/homepage`, :3000, `home.<dom>` gated.
  Groups: Applications / AI Services / Infrastructure / Monitoring / Databases / Tools. `services.yaml`
  empty — everything auto-discovered from Docker labels.
- **glitchtip** — alerts / error tracking (Sentry-compatible). 5 containers (web :8000 + worker + migrate
  + postgres:16 + valkey), own `glitchtip-internal` net; `glitchtip.<dom>`, **own auth**. Deterministic
  DSNs `sha256(GLITCHTIP_SECRET_KEY:<project>)[:32]` (survive `down -v`). `glitchtip-push` seeds org
  `Hacohen` + team `developers` + **one project per app** (n8n, apitools, whatsapp, librechat, traefik,
  machine, any-concurrency, feature-validation) and writes each DSN back into `.env`. **REST API** (Bearer)
  exposes `/api/0/organizations|teams|projects|.../keys` — the read surface for a future notifications
  aggregator.
- **machine** — host + Docker metrics. FastAPI, :8080, mounts `docker.sock:ro` + **`/:/host/root:ro`**;
  `machine.<dom>` gated (the host-root mount makes SSO the only guard); cleanup gated by
  `MACHINE_CLEANUP_ALLOWED_ACTIONS`.
- **any-concurrency** — concurrency/timeline (Gantt) observability. FastAPI, :8080, `docker.sock:ro`;
  aggregates spans from n8n (`execution_entity`), traefik access log, docker events, whatsapp/apitools
  logs, redis Bull queues, `POST /ingest/span`; `/ws` live. `any-concurrency.<dom>` gated. Extractable
  MIT OSS.
- **feature-validation** — system validation / test suite. Persistent `feature-validation-api` (:8100) +
  one-shot per-feature validator containers writing `benchmarks/`; targets live services; `fv.<dom>`
  (in `development/` override), **no authentik (gap)**; auto-runs on `FV_SCHEDULE_MINUTES`.
- **authentik** — SSO/forward-auth (the unifying identity, Part 2). 4 containers + readiness sentinel;
  `auth.<dom>` public; declarative `deployment-apps.yaml`.
- **supabase** — shared data layer (6 containers; Part 2). Studio gated; Kong API own JWT/anon-key auth.
- **redis** — cache/queue (`--requirepass`, TCP via `HostSNI` + `ipallowlist DBS_ALLOWED_IPS`) +
  redisinsight (:5540, gated). Shared by authentik (DB1), any-concurrency; glitchtip uses its own valkey.
- **portainer** — container mgmt, :9000, `docker.sock` rw, admin pw from `portainer_password.txt`, own
  auth.
- **browser42** — stealth Chromium + Playwright-MCP + noVNC. 4 containers behind an internal Caddy that
  enforces `BROWSER42_MCP_TOKEN` on `/mcp` (no SSO — MCP clients can't browser-auth) and gates `/view`
  with authentik.

**Validation + CI:** `scripts/ci-verify.sh` runs a layered named check set — `health-<app>` +
`integration-<app>[-facet]` — asserting declarative config actually took (authentik providers applied,
n8n push + workflows/creds imported + active + secured-webhook roundtrip, glitchtip org+projects+live DSN
ingest, browser42 CDP+VNC, redis PONG, liveness for the rest) ≈ **25 checks**, emitting JUnit + the
markdown scorecard, exit code = failures (CI gate). `bbox verify` is the lighter readiness gate (host/
docker/network, `.env` vs `.env.ex` key drift, containers healthy).

**Keys:** `DEPLOYMENT_NAME/DOMAIN`, `TRAEFIK_*`, `DBS_ALLOWED_IPS`; `AUTHENTIK_*` (secret key ≥50 chars,
postgres pw, bootstrap user/pw/email/token, `AUTH_EXTERNAL_URL`/`_PROTOCOL`); `GLITCHTIP_*` (secret key,
db pw, admin, org, email/retention flags) + per-app `*_SENTRY_DSN`; `SUPABASE_*` (db pw, jwt secret,
cookie key, anon/service JWTs, dashboard basic-auth, storage bucket); `REDIS_*`; `PORTAINER_BASE_URL` +
pw file; `BROWSER42_MCP_TOKEN`/`VNC_PASSWORD`/`STATE_PASSPHRASE`; `MACHINE_*`, `ANY_CONCURRENCY_BASE_URL`,
`FV_*`, `HOMEPAGE_*`.

**Productization gaps:** hardcoded org identity everywhere (domain, "Hacohen", admin emails, IPs, homepage
title); no secret generation on install (all `change_me…`); inconsistent auth coverage (apitools + fv
public; n8n binds 0.0.0.0:5678); DNS/TLS assume a real public domain (no offline/self-signed/LAN path);
manual/scripted post-up steps; host-root exposure (`machine`), `docker.sock` (portainer rw); literal
residential IPs in `DBS_ALLOWED_IPS`; glitchtip is the only alert sink and only 4 apps have wired SDKs.

---

## Part 4 — Keys, Secrets & Install (the backbone)

> The master key table (every meaningful `.env` var → purpose · consumed-by · kind · required · default)
> is maintained in the companion file **`central-business-system-keys.md`** to keep this map readable.
> The essentials:

**Kinds:** text-secret (random hex/token), password (human login), app-password (Gmail IMAP, signing
cert), oauth (client + consent), qr-session (WhatsApp Baileys `auth_info`), dsn (Sentry/Postgres),
url/config, derived (computed — GlitchTip DSNs from `GLITCHTIP_SECRET_KEY`; Supabase ANON/SERVICE JWTs
from `SUPABASE_JWT_SECRET`).

**Current secret-flow:** (a) plain `${VAR}` → containers (the `.env` file **is** the secret store; no
vault). (b) **n8n `credential_overrides`** — on `n8n-push`, each `${ENV}` in `blueprint.yml` (25 creds)
is substituted from `.env` and `PATCH`ed into n8n, which **re-encrypts under the current
`N8N_ENCRYPTION_KEY`** (survives key drift + `down -v`). (c) n8n OAuth **client** id/secret via
`CREDENTIALS_OVERWRITE_DATA` env (creds hold only tokens). (d) Authentik identity via env + a blueprint
apply that **blocks until the outpost serves every gated host** (the sentinel `bbox run --wait` gates on).
(e) **WhatsApp QR** = Baileys `data/auth_info` on disk (no env var; lost on reset). (f) encryption keys
(`N8N_ENCRYPTION_KEY`, `AUTHENTIK_SECRET_KEY`, `SUPABASE_JWT_SECRET`, …) as plain env; DSNs + Supabase
keys **derived** deterministically (survive wipes).

**Install today:** `bbox install debian` → `cp .env.ex .env` + **hand-edit ~30+ secrets** → `bbox run`
(compose up, Authentik head-start, `--wait` on SSO sentinel) → `bbox onboarding` (browser42 state → wait
n8n REST → `n8n-push`: owner bootstrap + cred reseed + publish/activate ~62 workflows → verify → INDOX
seed) → `bbox onboarding --auth-state` (print OAuth re-auth links). **Automated:** infra, network,
health-gated bring-up, owner, cred reseed, GlitchTip projects/DSNs, Authentik providers/outpost, workflow
publish, INDOX seed. **Manual:** editing every secret; DNS+TLS; **Google OAuth consent** per account;
**WhatsApp QR scan**; Authentik Google-login; minting `N8N_API_KEY`; generating Supabase JWTs; Gmail
app-password.

**Declarative today:** service topology, n8n workflows + non-OAuth creds, SSO providers/apps, GlitchTip
projects/DSNs, INDOX config + demo blueprint, browser42 encrypted state. **NOT declarative:** every
secret *value*, OAuth token grants, WhatsApp QR session, Authentik Google-login, `N8N_API_KEY` mint,
Supabase JWT gen, DNS/TLS, env-specific resource IDs (Google Sheet/Drive/Label IDs), and the
business-locked literals.

---

## Part 5 — How the pros ship this (research)

Three distinct layers — do **not** conflate them:
- **Secrets manager (text kind).** Encrypted-at-rest KV + versioning + audit + an **agent/sidecar** that
  injects secrets as env/files with caching + fallback. **Infisical** (MIT, Postgres+Redis — both already
  run here; gentle; dotenv import; `infisical run` sidecar) is the best fit. **OpenBao** (MPL-2.0 Vault
  fork) = heavier (Raft/unseal); Vault = deepest but BUSL + heavy.
- **OAuth broker (oauth kind).** Owns the consent dance + **stores & auto-refreshes tokens** across many
  providers. **Nango** (OSS, self-hostable, 800+ providers, encrypted creds, per-connection model) is the
  primitive for Google Drive/Gmail. Pattern ref: **Unified.to/Apideck** normalize OAuth across 460+ APIs
  with a single redirect URI + per-connection encrypted storage (and can bring-your-own vault).
- **Device/QR pairing (qr-session kind).** No standard product — app-specific (here: **Baileys** QR →
  `auth_info` files). Pro move: keep the pairing lib, **treat the session as a secret** in the vault,
  render the QR in your own UI (ref: OpenClaw stores channel/OAuth creds under `~/.openclaw/credentials`
  `0600`).

**The env-fallback + install-prompt pattern** the user described is standard: Infisical/Doppler support
seeding a store **from a `.env` import**, then failing/prompting when a *required* key is absent. This
repo already does the seed-half in `credential_overrides` — it just needs the "required + prompt" half.

**Packaging for per-business local install.** Self-hosted PaaS installers set the bar for "one command →
running dashboard in 5 minutes": **Coolify / Dokploy / CapRover** (single-script install, Docker-native,
first-run admin account). For a **non-technical** audience, **CasaOS / YunoHost** ship app catalogs +
simplified setup. The universal shape: a **self-contained bundle** + a **first-run setup wizard**
("create your first user / connect your accounts"). That is exactly the install screen this product
needs, layered on `bbox` + the manifest.

---

## Part 6 — The product: unified webapp + connections + install wizard

(Full design in `central-business-system-plan.md`; summary here.)

**Shape:** a thin **`console`** portal shell (one RTL SPA, one nav, one design system) over the existing
BFFs, all behind the **Authentik SSO + homepage-label registry** that already exist. Federate first
(iframe legacy UIs — chat/portainer/glitchtip/redisinsight — under the shared chrome), then
module-federate the first-party SPAs (morning/localdrive/mailview). Plus **build the one missing engine**
(the ledger backend).

**The heart — one `connections` service** with three credential *kinds* and a fixed resolution chain:
```
resolve(conn):  1) STORE (Infisical text / Nango tokens / Baileys session)   ← steady state
                2) .env  → seed the store idempotently, then use              ← friction-free first boot
                3) WIZARD (if required & absent → install screen prompt)       ← ask only for the gaps
```
- **secret/text** → Infisical (auto-mint machine secrets so the owner never sees them; guided-capture for
  Gmail app-password).
- **oauth** → a Nango-shaped broker (product owns the Google client; owner just clicks "Connect Google";
  tokens stored + refreshed) — replaces the manual `127.0.0.1:5678` consent + `PATCH data:{}` drift pain.
- **qr-session** → a QR pairing panel that renders `/api/bot/qr`, watches for pairing, and mirrors
  `auth_info` into the vault with a "re-pair" affordance.
- **derived** (GlitchTip DSNs, Supabase JWTs) → never asked; recomputed and injected.
Generalize the n8n `credential_overrides` `${VAR}`→PATCH→re-encrypt mechanism into the deployment-wide
`connections` contract.

**Install wizard (מסך התקנה)** — driven by a per-service **connections manifest** (each service declares
its required connections, like `credential_overrides` generalized). Flow: base settings (ONE "business
name + domain" input drives every "Hacohen" literal) → **auto-detected-from-`.env`** (green, nothing to
do) → **only the gaps** (text fields / "Connect" buttons / QR panels) → **verify** (health probes; done
when required ones are green — mirrors the 25-check CI ethos).

---

## Part 7 — Security callouts (fix before shipping to any business)

1. **Hard-coded, leaked Google Vision API key** at `production/apitools/.../ocr_processor.py:19` (a real
   `AIzaSy…` fallback used when env is unset). Remove the default; require `GOOGLE_VISION_API_KEY`.
2. **apitools and feature-validation are publicly routed with no Traefik auth** despite in-code intent —
   OCR (and any future ledger data on apitools) is directly reachable. Gate by default.
3. **Insecure `.env.ex` defaults ship as-is:** `AUTH_PASSWORD=12345`, a committed chat `SESSION_SECRET`,
   plaintext webhook passwords, and ~30 `change_me…` placeholders — nothing forces rotation on install.
4. **Host-root + docker.sock exposure:** `machine` mounts `/:/host/root:ro`; portainer mounts
   `docker.sock` rw — safe only while Authentik is intact. Least-privilege defaults needed.
5. **`DBS_ALLOWED_IPS` ships literal residential/operator IPs** — the TCP DB/redis exposure is allow-
   listed to the original operator, not the customer.
6. **WhatsApp session in a hardcoded host path** (`/home/solomonboltin/chat/data`) — not
   portable, and a full-mailbox-equivalent credential sitting on disk unmanaged.

---

## Part 8 — Consolidated gaps & phased roadmap

**The four structural gaps** (everything else is config): (i) **the ledger backend doesn't exist**;
(ii) **no central credential plane / secret generation** (`.env` hand-editing, OAuth dance, QR scan);
(iii) **hardwired to "Hacohen"** (domain/org/emails/IPs/Sheet-Drive-Label IDs); (iv) **no GUI install
wizard** (CLI + hand-edit only).

**Phased (each step additive, shippable, reversible — repo's "one perfect example → scale" rule):**
1. **`connections` MVP, read-only** — stand up Infisical; manifest; `resolve()` store→`.env`→unset chain;
   status list UI. Seed from `.env`. Nothing else changes; validate every service still boots.
2. **Cut ONE consumer over** — `inbox` (single app-password) resolves via `connections`. Prove the
   sidecar/client path.
3. **oauth kind** — Google broker (Nango-shaped); retire the manual consent + drift flow.
4. **qr-session kind** — bring the Baileys QR into the `connections` UI; mirror `auth_info` to the vault.
5. **Ledger backend** — build `doc_data`/`doc_gen`/`doc_models` against Supabase; point `morning`'s
   `APITOOLS_URL`/BFF at it; gate apitools.
6. **`console` shell** — portal chrome + design tokens; fold homepage in; iframe legacy UIs under the nav.
7. **De-Hacohen / tenant setup** — parameterize every literal from one input; finish the "Tenant Setup"
   workflow (`indoxSetupWF001`) that provisions Drive tree + sheets + labels and writes IDs back.
8. **Install wizard** on top of the now-complete manifest; generate machine secrets; ask only the gaps.
9. **Federate first-party SPAs**; **notifications aggregator** over the GlitchTip API + fv + machine.

---

## Part 9 — Open decisions for the owner

1. **v1 scope** — is the near-term ship **just `connections` + install wizard** (the stated pain),
   deferring the shell + ledger backend? (Recommend: yes — highest value first.)
2. **Ledger backend** — build the "INDOX Books" engine now (large), or keep פנקס as a doc-viewer over the
   incoming-documents data until later?
3. **OAuth broker** — custom Google handler first (Nango-shaped interface) vs stand up full Nango now?
   (Recommend custom-first.)
4. **Secret store** — Infisical (recommended) vs OpenBao vs a bespoke encrypted table.
5. **WhatsApp** — keep single-account Baileys embedded in the chat service, or invest in the declared Evolution/ChatBase
   multi-account layer?
6. **Branding/route** of the unified app (`console`? מרכז? BINA?) and whether it replaces `home.<dom>`.
7. **Distribution** — target a Coolify/Dokploy-style one-command installer, or a CasaOS-style catalog app,
   for the "install like desktop software" experience?

---

## Sources (research)

Secrets: [Infisical delivery/agent](https://infisical.com/docs/documentation/platform/secrets-mgmt/concepts/secrets-delivery),
[DeepWiki SDKs & Agent](https://deepwiki.com/Infisical/infisical/8.5-sdks-and-agent),
[OpenBao vs Vault 2026](https://lalatenduswain.medium.com/openbao-vs-hashicorp-vault-the-secrets-management-showdown-every-devops-team-needs-to-read-in-2026-458ae0d9a408),
[GitGuardian top secrets tools](https://blog.gitguardian.com/top-secrets-management-tools/).
OAuth: [Nango](https://github.com/nangohq/nango), [Nango self-hosting](https://nango.dev/docs/guides/platform/self-hosting),
[Unified.to OAuth normalization](https://unified.to/blog/how_we_normalize_oauth_across_460_apis_at_unified),
[Unified.to BYO secrets](https://unified.to/blog/credential_management_in_unified_bring_your_own_secrets_manager).
QR pairing ref: [OpenClaw architecture](https://ppaolo.substack.com/p/openclaw-system-architecture-overview).
Packaging/install: [Best self-hosted PaaS 2026](https://servercompass.app/blog/best-self-hosted-paas-platforms-2026),
[Dokploy vs Coolify vs CapRover](https://massivegrid.com/blog/dokploy-vs-coolify-vs-caprover/),
[self-hosted first-admin wizard (cal.com)](https://github.com/calcom/cal.com/issues/3384).
</content>
