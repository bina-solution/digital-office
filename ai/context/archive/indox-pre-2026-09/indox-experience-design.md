# INDOX (מסמכים נכנסים) — Full Experience Design + Build Plan

> Goal: turn the embedded INDOX SPA into a **PM-harnessed section-app** matching the
> כל מקביל (any-concurrency) quality bar — one consolidated, live, dense, RTL-Hebrew,
> Bina-consistent surface with a **horizontal section nav** (מסמכים / סנכרון / הגדרות / בדיקות)
> that obeys the double-nav rule (NO second dark vertical rail).
>
> **Status:** design reference. No app code changed by this doc. Author pass 2026-07-13,
> branch `release-v2-lockin`. This is the plan to implement next.

---

## 0. Topology (how the pieces reach each other) — READ FIRST

The SPA lives at `development/incoming-documents/app/webapp` and is served by the
incoming-documents **Flask BFF** (`development/incoming-documents/app`). Two mount contexts:

- **Standalone** `incoming.localhost/` → BFF serves SPA + its API at `/incomingDocuments/…`.
- **Embedded** `console.localhost/a/incoming/` → the **console** (`development/console/app.py`,
  `app_proxy`) reverse-proxies to the incoming-documents service under the console origin and
  injects `<base href="/a/incoming/">`. All SPA relative fetches resolve to
  `/a/incoming/incomingDocuments/…` (same origin). This is the primary context.

**What the embedded SPA can and cannot reach (critical for wiring):**

| Target | Reachable from SPA? | How |
|---|---|---|
| Own BFF `/incomingDocuments/…` | ✅ always | relative fetch (already used by `src/api.ts`, `API_PREFIX = <base>/incomingDocuments`) |
| feature-validation API | ✅ **only when embedded** | absolute `/a/feature-validation/api/…` — same console origin, console proxies it (`APP_BASES["feature-validation"]`). **Breaks standalone.** |
| n8n webhook `/webhook/indox-manage` (sync STATUS/SCAN/RESET/INJECT) | ❌ never | different origin, not proxied, unauthenticated cross-service. **Must go through a new BFF endpoint.** |
| supabase `settings`/`companies`/`tag_rules` | ❌ directly | **Must go through a new BFF endpoint** (BFF already talks to supabase). |

**Design consequence:** the incoming-documents BFF becomes the single front door for the SPA.
New BFF endpoints proxy n8n (sync) and read/write supabase config; the tests surface either
proxies feature-validation through the same BFF (robust, works standalone) or calls
`/a/feature-validation/api/…` directly (embedded-only, zero backend work). Recommendation: **proxy
through the BFF** so the surface is origin-independent and consistent.

**BFF supabase capability already present** (`backends/supabase_transport.py`): env
`SUPABASE_BASE_URL` + `SUPABASE_SERVICE_KEY`, plus an RPC `INCOMING_DOCS_SQL_RPC` (default
`run_sql`) that can run arbitrary SQL. So config-table reads/writes and sync-ledger reads are a
thin addition, not new infrastructure.

**The registered repo** bound to `public.incoming_documents`:
- dev storage: `n8n-demo-incoming-docs`; prod storage: `incoming-documents-main`
  (`…/storage/incoming_documents/repos.json`), backend `supabase`, `primary_key: "ID"`,
  `priority_sync_columns: ["STATUS","REQUIRED_ACTION"]`.
- **Never hard-code the name** — resolve it at runtime from `GET /incomingDocuments/repos` (take the
  supabase repo whose `supabase.table === "incoming_documents"`).

---

## 1. Navigation shell — the section-app frame (Phase 0, do first)

Today `App.tsx` renders a **dark `.topbar`** (`--side:#0f2a22`) with brand "מסמכים נכנסים" + links
מאגרים / מאגר חדש. Inside the console that's a **second dark surface** → violates the double-nav
rule from `ai/context/platform-navigation-design.md §3.2`.

**Target:** replace the dark topbar (when embedded) with a **light horizontal contextual tab-strip**
— the section-app pattern. Four sections:

```
[ מסמכים ]  [ סנכרון ]  [ הגדרות ]  [ בדיקות ]           <live beat>  <me pill>
```

- Surface `--surface`, `--line` bottom border, active tab = 2px `--accent` underline + `--ink`
  text, inactive `--muted`. (Tokens already in `src/index.css`: `--accent`, `--side`, `--line`,
  `--surface`, `--muted`, `.pill`, `.table`, `.card`, `.btn`, `.switch`, dark-mode block.)
- **Embed detection:** `const EMBEDDED = window.self !== window.top` (or `<base>` present). When
  embedded, hide the dark `.topbar` brand and render only the tab-strip (console already shows the
  app name/logo). Standalone keeps a slim brand + the tab-strip.
- **Routing** (extend `App.tsx` routes; keep existing repo/kafka routes as deep-links):
  - `/` → **Documents** (was RepoList; INDOX has effectively one repo, so land straight on the
    document browser for the resolved repo, with a repo switcher only if >1).
  - `/sync` → **Sync state** (new).
  - `/settings` → **Settings** (new; folds RepoDetail config + INDOX config tables).
  - `/tests` → **Test suites** (new).
  - keep `/repos/:repo/documents/:id`, `/repos/:repo/tail` as sub-routes.
- A persistent **live beat** pill (reuse any-concurrency `.live/.beat` idea) in the strip shows
  global freshness and a pause toggle for the polling views (sync + tests).

This alone converts INDOX from "an embedded mini-app with its own chrome" into a section of המרכז.

---

## 2. AREA 1 — Incoming documents (the dense table + detail)

### 2.1 Data source / API (exact)

All via the BFF, already implemented (`incoming_documents/api/__init__.py`):

- **List/query** — `POST /incomingDocuments/repos/<repo>/documents/query`
  Body = `Query` (`core/models.py`): `{ mode, ids?, filter?, select?, limit, offset }`.
  - `mode ∈ {single, by_ids, filter, all}` (default `all`).
  - `filter: { "<COLUMN>": <scalar> | { op, value } }`, `op ∈ eq,neq,in,nin,gt,gte,lt,lte,
    contains,startswith,endswith,is_null,not_null` (`QueryOp`). Scalar is sugar for `{op:eq}`.
  - `select: ["ID","NAME",…]` to limit columns (big win for the dense list — don't fetch 52 cols).
  - Response `{ rows, count, truncated, next_offset }` (`next_offset` drives pagination; current
    SPA already uses it).
  - **GAP:** `Query` has **no sort/order field**. Server-side sorting is not available. Either
    (a) add `order: "COL.desc"` to `Query` + supabase backend (backend already builds PostgREST;
    add `order=`), or (b) sort client-side within the page. Recommend (a) — cheap, high value.
  - **GAP:** no cross-column free-text search; emulate with `contains` on a chosen column
    (NAME / COMPANY_NAME / SHORT_DOC_ID) or add an `or`-filter mode. Flag for backend.
- **Single doc** — `GET /incomingDocuments/repos/<repo>/documents/<id>` → `{ row }`.
- **Edit** — `PATCH …/documents/<id>` (already wired in `DocumentDetailPage`).
- **History** — `GET …/documents/<id>/history` (kafka events; empty if kafka disabled).
- **Stats** — `GET …/repos/<repo>/stats` → `{ row_count, columns, kafka_enabled }`.

### 2.2 The 52-column model — how to present it

`production/n8n/fixtures/01_schema.sql` defines `public.incoming_documents` (all TEXT). Group the
columns into **semantic zones** (the table shows a curated subset; the detail drawer shows all,
grouped):

| Zone | Columns |
|---|---|
| **Identity** | `ID` (pk), `NAME`, `COMPANY_ID`, `COMPANY_NAME`, `SHORT_DOC_ID`, `COMPANY_DOC_ID`, `TYPE` |
| **Lifecycle** | `STATUS`, `REQUIRED_ACTION`, `ACTION_LOG`, `ERROR`, `RETRY_COUNT`, `NEXT_RETRY_AT`, `ITERATION_COUNT`, `IS_OLD`, `EMPTY`, `FROM_OFFICE`, `FROM_OFFICE_CHECK` |
| **Source** | `SOURCE_TYPE`, `SOURCE_ID`, `SOURCE_LINK`, `LINK`, `SIZE`, `HASH`, `SYNC_NAME`, `RECEIVED_DATE`, `TIMESTAMP` |
| **Doc facts** | `DOC_DATE`, `DOC_TOTAL_AMOUNT`, `TOTAL_AMOUNT`, `PURCHASE_ID`, `SHIPMENT_DOC_ID`, `INVOICE_ID` |
| **AI extraction** | `AI_TYPE`, `AI_COMPANY_ID`, `AI_DOC_ID`, `AI_DOC_DATE`, `AI_DOC_AMOUNT`, `AI_SHIPMENT_IDS`, `AI_ORDER_IDS`, `AI_EXTRACTION_COMPLETED` |
| **Selection** (chosen values) | `SELECTED_COMPANY_ID`, `SELECTED_DOC_ID`, `SELECTED_DOC_TIPE`, `SELECTED_DOC_AMOUNT`, `SELECTED_DOC_DATE`, `SELECTED_DOC_SHIPMENT_ID`, `SELECTED_DOC_ORDER_ID`, `SELECTION_CERTAINTY`, `SELECTION_SOURCE`, `SELECTION_COMPLETED`, `SELECTION_SCORE_DEBUG` |
| **Balance-sheet link** | `LINKED_BS`, `EX_IS_BS`, `BS_LINE_DATE`, `BS_LINE_AMOUNT`, `BS_LINE_NOTE`, `BS_EXTRACTED_LINES`, `BS_EXTRACTION_VERIFIED`, `BS_LINK_DOCUMENTS_COMPLETED` |
| **Completion flags** | every `*_COMPLETED` (render as ✓/○ chips, not raw text — note the TEXT-"false"-is-truthy gotcha `[[indox-supabase-text-boolean-bug]]`: normalize `"false"/"0"/""` → false) |

### 2.3 UX — dense table + facets + detail drawer

**Table (default column preset ≈ 9 cols, not 52):**
`STATUS · TYPE · COMPANY_NAME · NAME · SHORT_DOC_ID · DOC_DATE · DOC_TOTAL_AMOUNT ·
SELECTION_CERTAINTY · RECEIVED_DATE`. Column-preset switcher ("תמצית / חילוץ / מקור / הכל") and a
column menu let the user swap zones. Fetch only preset columns via `select` for speed.

Apply `platform-navigation-design.md §3.5` table conventions on top of the existing `.table`:
- **Sticky header** (`position:sticky; top:0`, opaque `--surface-2`).
- **Density toggle** comfortable/compact (persist per-app).
- **Toolbar** with a **search box** + **facet chips** that map to server-side `filter`:
  - `STATUS` facet (distinct values → dismissible `.pill` chips; multi-select → `{STATUS:{op:in,value:[…]}}`).
  - `TYPE` facet (INVOICE / SHIPMENT / BALANCE_SHEET / ORDER / QUOTE / …).
  - `SOURCE_TYPE` facet (drive / gmail …), `SYNC_NAME` facet (the 5 syncs from §3).
  - date range on `DOC_DATE` / `RECEIVED_DATE` (`gte`/`lte`), amount range on `DOC_TOTAL_AMOUNT`.
  - a **"טעון טיפול"** quick filter (`REQUIRED_ACTION not_null` / `STATUS != COMPLETED`).
  - **Active-filter chips always visible** so filtered state can't be misread.
- **Status cell as colored pill** (map STATUS → `.pill.ok/.warn/.bad/.muted`; keep the existing
  pill palette). Amounts/IDs wrapped LTR-isolated (`.num` / `.mono`).
- **Pagination footer** (already have offset/next_offset): page controls + row range + page-size
  25/50/100; keep filter/sort stable across pages.
- **Empty / loading / error** states (reuse `.spin`, `.callout`).

**Detail drawer** (upgrade `DocumentDetailPage` → a right-side drawer or full page):
- **Header:** `NAME` + `TYPE` pill + `STATUS` pill + certainty meter (`SELECTION_CERTAINTY`).
- **Source block:** `SOURCE_LINK` / `LINK` as an "פתח מסמך ↗" button; `SOURCE_TYPE`, `SYNC_NAME`,
  `HASH`, `SIZE`, `RECEIVED_DATE`.
- **Extraction panel:** three parallel columns — **AI** (`AI_*`), **Selected** (`SELECTED_*` /
  `SELECTION_*`), **Doc facts** — so the operator sees AI-proposed vs chosen vs final at a glance
  (this is the INDOX pipeline's core story). Show `SELECTION_SOURCE` + `SELECTION_SCORE_DEBUG`
  (collapsible JSON) for "why this value".
- **Completion strip:** all `*_COMPLETED` flags as a row of ✓/○ chips (pipeline progress).
- **BS-link block** when `LINKED_BS`/`EX_IS_BS` set: the linked balance-sheet line
  (`BS_LINE_*`, `BS_EXTRACTED_LINES`).
- **Lifecycle:** `REQUIRED_ACTION`, `ACTION_LOG`, `ERROR`, `RETRY_COUNT`, `NEXT_RETRY_AT` +
  the kafka **history** timeline (already fetched).
- **Editable** fields keep the existing PATCH path; PK read-only.
- **Optional OCR/AI preview:** the feature-validation API already proxies apitools drawings
  (`/api/features/{name}/cases/{case}/drawing` → apitools `/documentJsonQuery?draw=1`). Not
  per-document, but the same apitools endpoints (`/documentOcr`, `/documentJsonQuery`) can render
  a live OCR overlay for `API_TOOLS_ID`/`LINK`. Treat as a stretch; flag apitools reachability
  (BFF → apitools) as the dependency.

### 2.4 Gaps flagged (Area 1)
- No server-side **sort** (`Query.order` missing) — add to model + supabase backend.
- No **free-text across columns** — add `or`/multi-column contains, or settle for one search column.
- Distinct-value **facets** need a source of values: either a new `GET …/documents/facets?cols=STATUS,TYPE`
  BFF endpoint (SELECT DISTINCT via the `run_sql` RPC) or a hard-coded enum seeded from
  `settings` type lists. Recommend the facets endpoint (accurate, cheap).

---

## 3. AREA 2 — Sync state (the PM-harness centerpiece)

This is where the כל מקביל quality bar most applies: **live, dense, legible** per-source status.

### 3.1 Data source / API (exact)

- **Truth = the source** (drive folders / gmail labels), surfaced by the n8n **sync api**
  `SyncApi0000000001`, webhook `POST /webhook/indox-manage`.
  Request `{ INLINE_ACTION: "STATUS", sync?: "<name>" }`.
  Response (verified from the workflow's `Aggregate Status` node):
  ```json
  { "ok": true, "action": "STATUS",
    "at_rest": <bool>,            // in_progress==0 AND waiting(to_sync)==0 across all syncs
    "waiting": <int>,            // Σ to_sync
    "in_progress": <int>,        // Σ in_progress
    "per_sync": { "<name>": { "to_sync":N, "in_progress":N, "synced":N, "failed":N }, … } }
  ```
- **Registry (config of the pipeline)** = `settings.value WHERE key='sync_registry'` — a JSON array
  (verified in `production/n8n/fixtures/settings.json`). Each entry:
  ```
  { name, source:"drive"|"gmail", engine:"v3", processor_wf,
    batch:{take,chunk,timeout_min,schedule_min}, type_hint,
    // drive: pairs:[{to_sync,in_progress,synced,failed}]  (folder IDs, N pairs)
    // gmail: labels:{to_sync,in_progress,synced,failed}, claim_label, dest_folder,
    //        search_take, search_extra }
  ```
  Live set (5 syncs): `drive-gdoc` (3 pairs), `drive-bs` (BALANCE_SHEET), `gmail-link`,
  `gmail-bs` (BALANCE_SHEET), `gmail-doc`. localdrive reads the same registry
  (`production/localdrive/app.py`).
- **Other verbs on the same webhook** (`ai/context/indox-sync-control-plane.md`):
  `SCAN {INLINE_ACTION:"SCAN", sync?}`, `RESET {INLINE_ACTION:"RESET", scope}` (scope `full` |
  `{sync}` | `{sync,count:N}` | `{items:[…]}`), `INJECT {INLINE_ACTION:"INJECT", sync, items}`.
- **v3 reconciliation tables** (extra live signal, read via `run_sql` RPC): `sync_ledger`
  (delivered/quarantined per `(source,platform_id)`), `sync_attempt` (retry backlog: `attempts`,
  `not_before`, `last_error`), `sync_cursor` (discovery position). Great for a "retry queue" panel.

### 3.2 The wiring GAP (must build)

The SPA cannot call the n8n webhook. **Add BFF proxy endpoints** on the incoming-documents Flask
app (same origin as the SPA), server-side POSTing to the webhook:

```
GET  /incomingDocuments/sync/status[?sync=<name>]   → POST indox-manage {INLINE_ACTION:STATUS}
GET  /incomingDocuments/sync/registry               → settings row parsed to JSON (run_sql or PostgREST)
POST /incomingDocuments/sync/scan    body {sync?}    → {INLINE_ACTION:SCAN}
POST /incomingDocuments/sync/reset   body {scope}    → {INLINE_ACTION:RESET}   (guarded — see §6)
POST /incomingDocuments/sync/inject  body {sync,items|mode} → {INLINE_ACTION:INJECT}
GET  /incomingDocuments/sync/ledger[?status=&limit=] → run_sql over sync_ledger/sync_attempt (optional)
```
New env: `INDOX_MANAGE_WEBHOOK_URL` (e.g. `http://n8n:5678/webhook/indox-manage`). The BFF already
has `requests` and supabase access. Keep a short server-side cache (2–3s) on STATUS since it does
live drive/gmail listing (can be ~seconds) — mirrors the console's `_OV_CACHE` pattern.

### 3.3 UX — live sync board (any-concurrency quality)

Layout mirrors any-concurrency's `top` (HUD stat strip + live beat) over a dense board:

- **Global HUD strip** (reuse `.stat` cards): `רץ עכשיו` (Σ in_progress) · `ממתין` (Σ to_sync) ·
  `הושלמו` (Σ synced) · `נכשלו` (Σ failed) · **`במנוחה`/`פעיל`** derived from `at_rest`
  (green pill when at_rest, blue pulsing when active). A **live beat** + pause toggle; poll
  `/sync/status` every **3–5s** (config; align to registry `schedule_min` context).
- **Per-sync cards** (5), each a `.card` showing:
  - name + `source` icon (drive 📁 / gmail ✉️) + `type_hint` tag + `engine` + `processor_wf`.
  - a **4-segment state bar** `to_sync → in_progress → synced → failed` with counts (a compact
    horizontal stacked bar, colored `--muted / --blue / --accent / --red`), the visual heart of
    the board.
  - **throughput**: compute `Δsynced / Δt` between polls client-side → "X מסמכים/דקה" sparkline
    (a tiny canvas like any-concurrency's `pulse`), plus ETA-to-drain = `to_sync / rate`.
  - **failed > 0** → red accent + a "צפה בנכשלים" link (filters Documents to `SYNC_NAME=<name>,
    STATUS=FAILED`); ties the two surfaces together.
  - per-card actions (guarded): `סרוק עכשיו` (SCAN {sync}) · `אפס` (RESET {sync}) ·
    `הזרק דמו` (INJECT).
- **At-rest banner:** when `at_rest`, a calm "המערכת במנוחה — אין פריטים ממתינים או בעיבוד"
  (the debug-run "came-to-rest" signal, `[[indox-runtime-attention]]`, `[[indox-expected-behaviour]]`).
- **Optional retry-queue panel** from `sync_attempt`: rows with `not_before>now` (backing off) +
  `last_error` — surfaces the doc_step-lock / churn story operators care about.
- **Registry drawer:** clicking a card opens the raw registry entry (folder IDs / labels /
  batch) read-only here; **editing** lives in Settings (§4).

Poll discipline: pause when the tab/section is hidden; single in-flight request; reuse the last
good snapshot on transient 502 (STATUS can flap under Docker DNS pressure, `[[stack-memory-pressure-flakiness]]`).

### 3.4 Gaps flagged (Area 2)
- **New BFF sync proxy** (§3.2) is the blocker — SPA→n8n is impossible otherwise.
- STATUS returns only counts, not per-item lists → per-item "failed" drill-down comes from the
  **Documents** query (`SYNC_NAME`+`STATUS`), not STATUS. Wire the cross-link.
- `INDOX_MANAGE_WEBHOOK_URL` must be set in the incoming-documents service env/compose.
- Confirm STATUS latency is acceptable; if slow, lean on the `sync_ledger`/table view for the fast
  path and STATUS for the authoritative-but-slower refresh.

---

## 4. AREA 3 — Settings

Two config planes, unified under one settings surface (horizontal sub-tabs — `platform-navigation-design.md §3.6`,
tab-strip since ≤5 groups):

### 4.1 Repo config (already have)
`RepoDetailPage` + BFF `/incomingDocuments/repos/<repo>` (GET) and `PATCH` (allowed fields:
`active`, `poll_interval_seconds`, `supabase_studio_url`, `upsert_match_rules`). Keep the schema
table, source card, stats, the `active` **switch** (`.switch`), poll interval. This is the
"מאגר" sub-tab. `RepoCreatePage`/delete stay as admin actions (rarely used for INDOX's single repo).

### 4.2 INDOX config tables (must build BFF endpoints)

Data lives in supabase (`01_schema.sql`): `settings` (key/value; ~45 rows incl `sync_registry`,
`q_*` extraction queries, type lists, toggles like `activePrioritySync` per
`[[indox-settings-full-queries-and-toggles]]`), `companies` (Hebrew columns: `שם חברה`, `מזהה 1`,
`מזהה 2`, `שם ספק מפריוריטי`, `מייל 1/2`, `הוראות לAI לחילוץ דוח גיול`, `TRUSTED_SOURCE_TYPES`),
`tag_rules` (~23 rows: `KEY`, `EVENT`, `LABEL`, `label_id`, `TYPE`, `RULE`).

Reachable two ways: n8n `indoxApiRouter01` `TABLE_GET/TABLE_UPSERT` (executeWorkflow — needs a
webhook front, more moving parts) **or** directly via the BFF's supabase transport (PostgREST /
`run_sql`). **Recommend BFF-direct** — fewer hops, the BFF already owns supabase creds:

```
GET  /incomingDocuments/config/settings                 → [{key,value,updated_at}]
PUT  /incomingDocuments/config/settings   body {key,value}
GET  /incomingDocuments/config/companies                → rows
PUT  /incomingDocuments/config/companies  body {id?, …}  (upsert; key on "מזהה 1", unique index exists)
GET  /incomingDocuments/config/tag_rules
PUT  /incomingDocuments/config/tag_rules  body {id?, …}
GET  /incomingDocuments/config/sync_registry            → parsed array   (shared with §3.2)
PUT  /incomingDocuments/config/sync_registry body <array> (writes settings key='sync_registry')
```

**Sub-tabs / UX:**
- **חברות (Companies):** dense editable `.table` (add/edit/delete rows). Hebrew headers as-is;
  `מזהה 1` is the dedup key (unique index `companies_mzhe1_uniq`).
- **תוויות (Tag rules):** editable table of gmail label rules (`KEY→EVENT→LABEL/label_id`), the
  "settings-centric label architecture" (`[[settings-centric-label-architecture]]`).
- **מקורות סנכרון (Sync registry):** a structured editor for the 5 syncs — per sync: name,
  source, processor_wf, batch (take/chunk/timeout/schedule), and the folder-IDs (drive `pairs`) /
  labels (gmail). This is the highest-leverage config (drives §3). Edit as a form; persist via
  `PUT …/config/sync_registry`. **Warn** that folder-ID edits change live routing (never a route
  *removal* silently — cf. `[[never-change-app-routing]]` for app routes; here it's data-routing
  but treat destructive edits with a confirm).
- **חילוץ (Extraction queries):** the `q_*` settings keys (per-type apitools query JSON). Show
  as key→JSON editors (monospace textarea, JSON-validate before save).
- **מתגים (Toggles):** boolean-ish settings (`activePrioritySync` default OFF, etc.) as `.switch`.
- **Save affordance:** explicit Save/Cancel with dirty-state for the structured editors (registry,
  queries); inline switch auto-save for toggles (`§3.6`). Never silently discard.

### 4.3 Gaps flagged (Area 3)
- New **BFF config endpoints** (§4.2). Reads are trivial (PostgREST GET); writes go through
  `run_sql` upsert or PostgREST `POST ?on_conflict=`. Validate JSON on `settings.value` writes.
- Hebrew-keyed columns: URL-encode / quote carefully in PostgREST/SQL.
- Editing `sync_registry` is powerful and dangerous (live routing) — gate behind admin
  (`auth/me.is_admin`, group `incoming-docs-admin`, already surfaced) + confirm dialog.

---

## 5. AREA 4 — Test suites (manual run + LIVE progress)

### 5.1 Data source / API (exact) — feature-validation FastAPI

`development/feature-validation/api/server.py` (console-proxied at `/a/feature-validation/…`,
`APP_BASES["feature-validation"] = http://feature-validation-api:8100`). The INDOX extraction tests
are its features:
`document-ocr`, `aligned-value-extraction`, `local-ocr`, `local-aligned-value-extraction`,
`balance-sheet-extraction`, `balance-sheet-extraction-dev`, `column-extraction`,
`find-option-matching`, `integration`.

Endpoints:
- `GET /api/features` → each feature + `latest_benchmark` summary (`summarize_benchmark`):
  `all_passed`, `case_count`, `cases_passed`, `failures[]`, and `cases[]` with per-case
  `name/status/assertions_passed/assertions_total/analysis/failed_assertions/execution_url/…`.
- `GET /api/features/{name}` → scenario + latest benchmark + benchmark file list.
- `GET /api/status` → overall roll-up (`overall_status`, `summary.{features_passed/total,
  cases_passed/total}`) — the homepage-widget shape.
- `GET /api/features/{name}/history?limit=` → pass/fail trend across recent benchmarks.
- `POST /api/run?tag=<substr>` → **run all (or name-filtered) — BLOCKING**, returns full results.
- `POST /api/run/{name}?cases=<c1,c2>` → **run one feature (optionally specific cases) — BLOCKING**.
- `GET /api/features/{name}/cases/{case}/drawing` → apitools annotated OCR overlay (per case).

### 5.2 The LIVE-progress GAP (the real design problem)

`run_feature_validation` uses `subprocess.run(...)` and **returns only when the whole suite
finishes** (timeout 3600s). Benchmarks are written **once, at the end**. So there is **no
intra-run progress** today. Three ways to deliver "live progress", in increasing fidelity:

- **(A) v1, zero backend change — determinate spinner.** On "הרץ", read the feature's known
  `case_count` from `GET /api/features`, show a progress bar "מריץ… 0/N" with an indeterminate
  shimmer, disable re-run, and on the awaited response swap to the pass/fail breakdown. Honest but
  not per-case-live.
- **(B) recommended — async job + partial results.** Add to feature-validation:
  `POST /api/run/{name}` → returns `{job_id}` immediately, runs in a background thread; the
  validator writes a **partial progress file** (`benchmarks/_running.json`: `{done, total,
  cases:[…so far]}`) after each case (small change in `lib/validate_feature_base.py`); expose
  `GET /api/jobs/{job_id}` (or `GET /api/features/{name}/progress`) that returns the partial.
  SPA polls every 1–2s → true per-case streaming (passed/failed counts climbing). Clean, matches
  the PM-harness "live" bar.
- **(C) max — SSE.** `GET /api/jobs/{job_id}/stream` server-sent events per case. Nice-to-have;
  (B)'s polling is enough for suites of tens of cases.

**Origin note:** calling FV from the embedded SPA works via `/a/feature-validation/api/…`
(same console origin) **but breaks standalone**. For robustness, **proxy FV through the BFF**:
`/incomingDocuments/tests/* → FV_URL/api/*` (BFF env `FEATURE_VALIDATION_URL`). Then the tests
surface is origin-independent like the rest.

### 5.3 UX — in-UI suite runner

- **Suite list** (cards or dense table), each row: suite name (Hebrew label), last-run timestamp,
  a **pass ratio** `cases_passed/case_count` as a mini-meter + `.pill.ok/.bad`, a **"הרץ"** button,
  and a **"הרץ הכל"** at the top (`POST /api/run` or loop). Trend sparkline from `/history`.
- **Live run panel** (on run): a progress bar `done/total`, live-incrementing passed/failed
  counters (green/red), and a streaming per-case list (name + ✓/✗ + assertions x/y + duration),
  newest first — the any-concurrency "live" feel. A **live beat** while running.
- **Case detail:** expand a case → `failed_assertions` (expected vs actual vs operator),
  `analysis` (result_value / aligned_value / match_count …), and the **apitools drawing overlay**
  (`…/cases/{case}/drawing`) for OCR/extraction tests — visually shows what was extracted.
- **Reset / seed panel** (ties tests to a clean state — `[[indox-reset-workflows]]`,
  `[[indox-verification-practices]]`): buttons for **INDOX Reset - Full / Gmail / Drive** and
  **Inject demo docs**. These are n8n workflows (`IndoxResetFull01` / `IndoxResetGml001` /
  `tVzFMkz18pCsXRyw`) — route them through the **sync BFF** as `RESET`/`INJECT` (§3.2) rather than
  raw n8n REST, per the control-plane consolidation. Gate behind admin + confirm (destructive).

### 5.4 Gaps flagged (Area 4)
- **Live progress needs a new FV endpoint** (option B) — the current run is blocking with no
  intra-run signal. This is the single biggest new-backend item for tests.
- **FV origin**: proxy through BFF (`/incomingDocuments/tests/*`) for standalone parity.
- Long runs (balance-sheet 30–90s/case, up to 3600s) → the SPA must handle long-lived polling and
  a "still running" state; don't block the UI thread.
- Reset/inject are destructive → admin-gate + confirm; prefer the sync-api `RESET/INJECT` path.

---

## 6. Cross-cutting: guards, RTL, quality bar

- **Bina consistency:** reuse the tokens/classes already in `src/index.css` (`--accent`, `--side`,
  `--line`, `--surface`, `--muted`, `.table`, `.pill`, `.card`, `.btn`, `.switch`, `.callout`,
  dark-mode block) and mirror any-concurrency's `.stat`/`.live/.beat`/`pulse` for the live views.
  No new color system.
- **RTL:** logical properties only (`margin-inline-*`, `inset-inline-*`, `text-align:start`),
  numbers/IDs/amounts LTR-isolated (`.mono` / add a `.num{direction:ltr;unicode-bidi:isolate}`),
  mirror only directional icons. (`platform-navigation-design.md §1f`.)
- **Permissions:** destructive/side-effectful actions (SCAN/RESET/INJECT, registry edits, running
  suites, reset workflows) gate on `auth/me.is_admin` (group `incoming-docs-admin`) + a confirm.
  Read-only views (documents, sync status, settings view) need no gate.
- **Polling discipline:** sync + tests views poll; pause on hidden tab; single in-flight; reuse
  last good snapshot on 502; short server-side cache on STATUS. (Docker-DNS flakiness is real.)
- **Double-nav rule:** exactly one dark surface (the console rail). INDOX renders only the light
  horizontal tab-strip when embedded. No dark topbar, no vertical rail.

---

## 7. Staged implementation plan (buildable, ordered by impact-per-effort)

Each phase is independently shippable and verifiable.

**Phase 0 — Section-app shell** *(SPA only, no backend)*
- `App.tsx`: add embed detection; replace dark `.topbar` with a light 4-tab strip
  (מסמכים/סנכרון/הגדרות/בדיקות) + live beat; add routes `/sync`, `/settings`, `/tests`; land `/`
  on the resolved repo's document browser. Add `.num` helper + tab-strip styles to `index.css`.

**Phase 1 — Documents surface** *(mostly SPA; 1–2 small BFF adds)*
- Rebuild `DocumentBrowserPage` as the dense, faceted, curated-column table (presets via `select`,
  status/type/source/sync facets → server `filter`, sticky header, density, active-filter chips,
  pagination footer).
- Rebuild `DocumentDetailPage` as the grouped drawer (Identity/Source/Extraction AI‖Selected‖Facts/
  Completion flags/BS-link/Lifecycle + history).
- **BFF:** add `Query.order` (sort) + supabase `order=`; add `GET …/documents/facets?cols=` (DISTINCT
  via `run_sql`). *(Optional but recommended.)*

**Phase 2 — Sync state (PM-harness centerpiece)** *(new BFF proxy + new SPA view)*
- **BFF:** `GET /sync/status`, `GET /sync/registry`, `POST /sync/{scan,reset,inject}`, optional
  `GET /sync/ledger`; env `INDOX_MANAGE_WEBHOOK_URL`; 2–3s STATUS cache.
- **SPA:** live sync board — global HUD + at-rest banner + 5 per-sync cards with 4-state bars,
  throughput sparkline, failed→Documents cross-link, guarded scan/reset/inject. Poll 3–5s w/ beat.

**Phase 3 — Settings** *(new BFF config endpoints + SPA sub-tabs)*
- **BFF:** `GET/PUT /config/{settings,companies,tag_rules,sync_registry}` over supabase.
- **SPA:** settings tab-strip — מאגר (existing RepoDetail) · חברות · תוויות · מקורות סנכרון
  (registry editor) · חילוץ (q_* JSON) · מתגים. Explicit Save/Cancel; admin-gate registry.

**Phase 4 — Test suites** *(FV progress endpoint + BFF proxy + SPA view)*
- **FV:** async `POST /api/run/{name}` → `{job_id}` + per-case partial file + `GET …/progress`
  (option B). **BFF:** `/incomingDocuments/tests/*` → FV (env `FEATURE_VALIDATION_URL`).
- **SPA:** suite list with הרץ/הרץ-הכל + pass meters + trend; live run panel (progress bar,
  streaming per-case pass/fail, drawing overlays); reset/seed panel routed through sync `RESET/INJECT`.

**Phase 5 — Polish** — command-palette hook-in (console-level), RTL screenshot diff, compact-density
persistence, empty/error states everywhere.

---

## 8. Endpoint summary (what exists vs what to add)

**Exists (reuse as-is):**
- Documents: `POST /incomingDocuments/repos/<repo>/documents/query`, `GET/PATCH …/documents/<id>`,
  `…/history`, `GET …/repos`, `GET …/repos/<repo>[/stats]`, `PATCH …/repos/<repo>`, `GET /auth/me`.
- Sync truth: n8n `POST /webhook/indox-manage {INLINE_ACTION:STATUS|SCAN|RESET|INJECT}`.
- Config truth: supabase `settings`/`companies`/`tag_rules` (+ `run_sql` RPC via BFF transport).
- Tests: FV `GET /api/features|status|features/{n}[/history]`, `POST /api/run[/{n}]`,
  `…/cases/{c}/drawing`.

**To add — BFF (incoming-documents Flask), all same-origin as SPA:**
- `GET Query.order` support (+ supabase `order=`); `GET …/documents/facets`.
- `GET /sync/status`, `GET /sync/registry`, `POST /sync/{scan,reset,inject}`, `GET /sync/ledger`.
- `GET/PUT /config/{settings,companies,tag_rules,sync_registry}`.
- `ALL /incomingDocuments/tests/*` → FV proxy.
- Env: `INDOX_MANAGE_WEBHOOK_URL`, `FEATURE_VALIDATION_URL` (BFF already has supabase + apitools
  reach via existing envs).

**To add — feature-validation (for live progress):**
- Async run + per-case partial file + `GET …/progress` (or SSE). The only new backend work outside
  the BFF.

---

## 9. Key references
- SPA: `development/incoming-documents/app/webapp/src/{App.tsx,api.ts,index.css,pages/*}`.
- BFF: `development/incoming-documents/app/incoming_documents/{api/__init__.py,core/models.py,
  backends/supabase*.py,n8n_credentials.py}`.
- Console proxy: `development/console/app.py` (`app_proxy`, `APP_BASES`), `modules.yaml`.
- Schema: `production/n8n/fixtures/01_schema.sql`; registry: `production/n8n/fixtures/settings.json`
  (`key='sync_registry'`).
- Sync: `production/n8n/workflows/SyncApi0000000001.json`; design
  `ai/context/indox-sync-control-plane.md`; `ai/context/sync-v3-plan.md`.
- Tests: `development/feature-validation/api/server.py`, `lib/validate_feature_base.py`.
- Quality bar: `production/any-concurrency/static/index.html`; nav
  `ai/context/platform-navigation-design.md`.
- Memory: `[[indox-expected-behaviour]]`, `[[indox-runtime-attention]]`,
  `[[indox-sync-v2-thin-batch]]`, `[[indox-settings-full-queries-and-toggles]]`,
  `[[settings-centric-label-architecture]]`, `[[indox-reset-workflows]]`,
  `[[indox-verification-practices]]`, `[[indox-supabase-text-boolean-bug]]`,
  `[[never-change-app-routing]]`, `[[stack-memory-pressure-flakiness]]`.
```
