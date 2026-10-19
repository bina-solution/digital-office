# Incoming Documents — Phase 2: Implementation Plan

> Inputs: [plan.txt](plan.txt) · [context-collection/](context-collection/) (n8n workflows, apitools snapshot, production config, sample CSV).
>
> Goal: Move the data side of `Batch Upsert` (`indoxDocBatchUpsert01`) and `Get Incoming Document` (`indoxDocGet01`) into a Python module under `apitools/src/incoming_documents/`, with a `DocumentRepo` abstraction over Google Sheets and Supabase. Keep `process_lock` (Redis) inside n8n. Add a Kafka producer/consumer to drive `Incoming Documents 0.1.6`.

---

## 1. Architectural decisions

### 1.1 Host project
- Add a Flask **blueprint** `incoming_documents_bp` registered in [src/api/__init__.py](../api/__init__.py) under URL prefix `INCOMING_DOCS_API_PREFIX` (default `/incomingDocuments`).
- All new code lives under `apitools/src/incoming_documents/` (sibling of `ocr_core/`, `pdf_core/`).
- Keep Gunicorn sync workers for HTTP. **The Python API is producer-only**: it publishes change events to Kafka after every successful write. The events are consumed by `Incoming Documents 0.1.6` via n8n's native Kafka Trigger node — no Python consumer worker, no extra container.

### 1.2 Message bus: **Redpanda** (Kafka API-compatible)
- Plan mandates Kafka. Redis Streams is rejected because we need topic semantics, replay from offset, and consumer groups visible to future producers/consumers. Redpanda is a single-binary, ZK-less, Kafka-wire-compatible broker — fits our compose.yml profile.
- Add to [compose.yml](../../../compose.yml) under profile `incoming-docs`:
  - `redpanda:` (`docker.redpanda.com/redpandadata/redpanda:latest`, single-node, advertised `PLAINTEXT://redpanda:9092`).
  - `redpanda-console:` (UI behind Traefik) — optional.
- Topic naming: `${KAFKA_TOPIC_PREFIX}.<repo-name>` (default prefix `incoming-documents`, e.g. `incoming-documents.prod_gsheet`).
- Partition count: 3 (room to scale consumer group). Replication: 1 (single-node). Retention: 7 days.

### 1.3 Repo registry
- Stored as a JSON file at `INCOMING_DOCS_REPO_REGISTRY` (default `.storage/incoming_documents/repos.json`).
- Schema validated via `pydantic`. Hot-reload via `mtime` check on each request (cheap, single-process). Atomic writes via temp-file + `os.replace`.
- Out-of-scope for v1: a Supabase-table registry (deferrable; the JSON file is sufficient).

### 1.4 Concurrency boundary
- The Python API **does not implement application-level locking**. Per-PK ordering is provided by Kafka: events for a given `row.ID` are keyed on the PK and therefore land on the same partition, preserving order for any downstream consumer. Whatever locking n8n already does around its workflows is out of scope for this module.

### 1.5 Backwards compatibility with the existing GSheet
- The GSheet **stays the source of truth** during migration. The Python API writes to GSheet through the `gsheet` backend, exactly as today.
- Supabase backend is built and tested in parallel (using a *different* repo name) and only becomes primary after the human migration step (phase 6).

---

## 2. Module layout

```
apitools/src/incoming_documents/
├── __init__.py
├── plan.txt                            # (existing)
├── IMPLEMENTATION-PLAN.md              # (this file)
├── TESTING-STRATEGY.md                 # (next file)
├── context-collection/                 # (phase 1 output, frozen)
├── api/
│   ├── __init__.py                     # blueprint factory
│   ├── routes_repos.py                 # /repos CRUD + provisioning
│   ├── routes_documents.py             # /repos/<name>/documents (batch upsert, batch get)
│   ├── routes_kafka.py                 # /repos/<name>/kafka (publish, topic ensure)
│   ├── routes_admin.py                 # /health, /schema/introspect
│   └── schemas.py                      # pydantic request/response models
├── core/
│   ├── repo.py                         # DocumentRepo abstract base + DiffEngine
│   ├── registry.py                     # RepoRegistry (load/save/get)
│   ├── provisioning.py                 # provision_repo() / rollback() — backend-agnostic orchestrator
│   ├── types.py                        # logical ↔ backend type mapping
│   ├── diff.py                         # pure diff: current rows + incoming → updates + creates
│   ├── errors.py                       # exceptions
│   └── models.py                       # pydantic: RepoConfig, DocumentRecord, DiffResult
├── backends/
│   ├── __init__.py                     # backend factory by RepoConfig.backend
│   ├── gsheet.py                       # GSheetRepo (google-api-python-client)
│   └── supabase.py                     # SupabaseRepo (httpx → PostgREST)
├── kafka/
│   ├── __init__.py
│   ├── producer.py                     # idempotent producer + topic ensure (the API is producer-only)
│   └── admin.py                        # topic create/describe/lag helpers
├── webapp/
│   ├── README.md                       # dev workflow (vite dev server proxying to flask)
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx                    # React entrypoint
│   │   ├── App.tsx                     # router shell
│   │   ├── api/                        # typed client generated from openapi.json
│   │   ├── pages/
│   │   │   ├── RepoList.tsx            # / — list all repos with health + counts
│   │   │   ├── RepoCreate.tsx          # /repos/new — wizard wrapping POST /repos
│   │   │   ├── RepoDetail.tsx          # /repos/:r — schema + stats + tabs
│   │   │   ├── DocumentBrowser.tsx     # /repos/:r/documents — paginated grid + filter builder
│   │   │   ├── DocumentDetail.tsx      # /repos/:r/documents/:id — view + edit + change history
│   │   │   ├── KafkaTail.tsx           # /repos/:r/kafka — live SSE stream of events
│   │   │   └── SchemaEditor.tsx        # /repos/:r/schema — add columns / introspect-adopt / drift view
│   │   ├── components/                 # DataGrid, FilterBuilder, JsonViewer, RepoBadge, etc.
│   │   ├── hooks/                      # useRepo, useDocuments, useSse, useAuth
│   │   └── styles/                     # Tailwind config
│   └── dist/                           # built static assets, served by Flask static route
└── tests/
    ├── unit/                           # diff, registry, schemas
    ├── integration/                    # gsheet (mock googleapis), supabase (testcontainers)
    ├── e2e/                            # curl-equivalent against running compose stack
    └── load/                           # locust scenario
```

---

## 3. HTTP contract (frozen — must match n8n behaviour)

All routes are mounted under `${INCOMING_DOCS_API_PREFIX}` (default `/incomingDocuments`). All requests/responses are JSON unless noted. `<repo>` is a registry name (e.g. `prod_gsheet`).

### 3.1 Batch upsert — replaces n8n `Batch Upsert` (`indoxDocBatchUpsert01`)

```
PUT /incomingDocuments/repos/<repo>/documents
```

Mirrors the existing webhook `PUT /webhook/incoming-documents/update` (responseMode: responseNode).

**Request body** (array — same shape as today's "Code - Process Update Request1" input):
```json
[
  { "ID": "abc-123", "STATUS": "COMPLETED", "DOC_DATE": "2025-11-12", ... },
  { "ID": "abc-124", "TYPE": "INVOICE", ... }
]
```
- Each item must contain the primary key column (`ID` for the prod sheet, configurable per-repo).
- Items without `ID` → routed to **append** (create) path.
- `null` values are stripped (`Clean Nulls`).
- Special "Check Priority Sync" rule (force `priority_sync=true` when AI/selection fields are set) is implemented in `core/diff.py` and applied **before** the diff.

**Response 200 (success path — mirrors today's `Response - Update Success`):**
```json
{
  "success": true,
  "updated": [ { "ID": "abc-123", "row": 17, "changedColumns": ["STATUS", "DOC_DATE"] } ],
  "created": [ { "ID": "abc-124", "row": 39583 } ],
  "skipped": [],
  "stats": { "incoming": 2, "updated": 1, "created": 1, "noop": 0 }
}
```

**Response 4xx/5xx (mirrors `Response - Update Fail`):**
```json
{ "success": false, "error": "<message>", "updated": [], "created": [] }
```

**Concurrency:** the API does not lock. Per-PK ordering downstream is guaranteed by the Kafka key (`row.ID`) — all events for one ID land on the same partition.

**Bus publish (post-write):** after `batch_update` + `batch_create` succeed, the route handler emits one Kafka event per affected row to `${KAFKA_TOPIC_PREFIX}.<repo>` with `key=row.<primary_key>` and `event_type=ROW_CHANGED|ROW_CREATED`. Publish is **synchronous** (`producer.flush(timeout=5s)`) before the HTTP 200 returns, so the API never acks a write the bus didn't see. If Kafka is unreachable: the response is `503 BackendUnavailable` with `{success:false, error:"kafka_unavailable", written:true}` — the data is already persisted in the backend, but the caller is told the bus failed so it can decide whether to retry the publish via `POST /kafka/publish`. The producer is configured `enable.idempotence=true` so a retried publish with the same `event_id` is deduped by Redpanda.

**Sweep path note:** the n8n sweep (Schedule Trigger → `Incoming Documents 0.1.6` → `Get Incoming Document` wrapper) reuses §3.2 batch get unchanged — no new endpoint is needed. Live updates flow over Kafka; sweep continues to call `POST /documents/query`.

### 3.2 Batch get — replaces n8n `Get Incoming Document` (`indoxDocGet01`)

```
POST /incomingDocuments/repos/<repo>/documents/query
```

(Use POST, not GET — query payloads can exceed URL length and contain non-ASCII Hebrew column names.)

**Request body** (matches today's `Code - Process Get Request` query types):
```json
{
  "mode": "single" | "by_ids" | "filter" | "all",
  "ids": ["abc-123"],                        // for single / by_ids
  "filter": {                                // for filter mode
    "STATUS": "COMPLETED",
    "DOC_DATE": { "op": "gte", "value": "2025-01-01" },
    "COMPANY_ID": { "op": "in", "value": ["c1","c2"] }
  },
  "select": ["ID", "STATUS", "DOC_DATE"],    // optional column projection
  "limit": 1000,
  "offset": 0
}
```

Supported `op`: `eq` (default if value is scalar), `neq`, `in`, `nin`, `gt`, `gte`, `lt`, `lte`, `contains`, `startswith`, `endswith`, `is_null`, `not_null`. Matches the union of `COMPLEX GSHEET QUERY` + `Custom Filter Engine` behaviour.

**Response 200:**
```json
{
  "success": true,
  "rows": [ { "ID": "abc-123", "STATUS": "COMPLETED", ... } ],
  "count": 1,
  "truncated": false,
  "next_offset": null
}
```

**Pagination:** `limit` is hard-capped at `INCOMING_DOCS_QUERY_MAX_LIMIT` (default 2000). `mode:"all"` is **not** unbounded — it is an alias for `{offset:0, limit:MAX_LIMIT}`. When `count == limit`, `truncated:true` and `next_offset` is set; the caller pages by re-issuing with `offset=next_offset`. The 39k-row prod sweep therefore takes ~20 calls, each capped at 2000 rows. Streaming via `Transfer-Encoding: chunked` is out of scope for v1.

### 3.3 Repo CRUD + provisioning

```
GET    /incomingDocuments/repos                    → list
POST   /incomingDocuments/repos                    → create_repo: registers + PROVISIONS underlying storage
GET    /incomingDocuments/repos/<repo>             → get
PUT    /incomingDocuments/repos/<repo>             → update non-schema fields only (priority_sync_columns, kafka.partitions cap, gsheet.editors)
DELETE /incomingDocuments/repos/<repo>             → unregister; underlying storage kept unless ?drop_storage=true
POST   /incomingDocuments/repos/<repo>/schema/introspect          → returns current backend column list
POST   /incomingDocuments/repos/<repo>/schema/introspect?adopt=true → ALSO writes the introspected columns into RepoConfig.columns (one-shot bootstrap for an existing GSheet/table; the only sanctioned way to seed columns without re-typing 52 Hebrew names by hand)
POST   /incomingDocuments/repos/<repo>/schema/ensure              → reconciles backend schema with RepoConfig.columns (idempotent, add-only — never drops)
DELETE /incomingDocuments/repos/<repo>/documents                  → body {ids:[...]} — OUT OF SCOPE for v1 (returns 501); planned for v2 once n8n needs it
```

**`POST /repos` is the single entry point for `create_repo(name, ...)`.** It is fully transactional and idempotent: registry write + storage provisioning + Kafka topic ensure either all succeed or all roll back. On a re-run with the same name + identical config it returns 200 (no-op); same name + drifted config returns 409.

**Provisioning steps (executed by `core.provisioning.provision_repo()` after registry validation):**

| Step | `gsheet` backend | `supabase` backend |
|------|------------------|--------------------|
| 1. Validate `RepoConfig.columns` | required (no introspection seed) | required |
| 2. Ensure container exists | If `gsheet.spreadsheet_id` is `null` → create a new spreadsheet (`spreadsheets.create`) named `gsheet.spreadsheet_title`, store the returned ID back into the registry. Else verify the spreadsheet is accessible by the service account. | If `supabase.schema` does not exist → `CREATE SCHEMA IF NOT EXISTS "<schema>"`. |
| 3. Ensure tab/table exists | If sheet tab `gsheet.sheet_name` does not exist on the spreadsheet → `spreadsheets.batchUpdate.addSheet` (returns the new `gid`, stored back into the registry). | `CREATE TABLE IF NOT EXISTS "<schema>"."<table>" ( <pk> text PRIMARY KEY, ... )`. |
| 4. Ensure schema (columns) | Write the header row in row 1 with `RepoConfig.columns` in declared order. If a header row already exists → reorder is **never** done; missing columns are appended at the right; extra columns are reported as a warning, never deleted. | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS "<col>" <type>` per missing column. PK enforced via `CREATE UNIQUE INDEX IF NOT EXISTS`. Mirrors the `Batch Upsert Supabase` reference workflow's introspection branch. Removed columns are reported but never dropped. |
| 5. Sharing / permissions | Share the spreadsheet with `RepoConfig.gsheet.editors[]` (defaults to `[person17@example.com]`) via `drive.permissions.create`. | Grant `service_role` SELECT/INSERT/UPDATE/DELETE on the table (RLS off by default; opt-in via `RepoConfig.supabase.rls=true`). |
| 6. Ensure Kafka topic | `kafka_admin.create_topic(${prefix}.<repo>, partitions=3, retention=7d)` if missing. | Same. |
| 7. Persist `RepoConfig` | Write the (possibly enriched) config to the JSON registry via the atomic temp-file + `os.replace` path. | Same. |
| 8. Publish `repo_created` event | Emit a single event of type `REPO_CREATED` to `${prefix}.<repo>` so live consumers see the new repo immediately. | Same. |

**Atomicity:** steps 1–7 are wrapped in a try/except that calls `provision_repo.rollback(state)` on any failure. Rollback only removes resources that were *created in this call* (never destroys pre-existing tables/sheets). The Kafka topic, once created, is not deleted on rollback (cheap to keep, awkward to delete safely).

**`create_repo` request body (extends `RepoConfig` with provisioning hints):**
```json
{
  "name": "prod_supabase",
  "backend": "supabase",
  "primary_key": "ID",
  "columns": [
    { "name": "ID", "type": "text", "nullable": false },
    { "name": "STATUS", "type": "text" },
    { "name": "DOC_DATE", "type": "date" },
    { "name": "DOC_TOTAL_AMOUNT", "type": "numeric" }
  ],
  "supabase": {
    "schema": "public",
    "table": "incoming_documents",
    "service_key_env": "SUPABASE_SERVICE_KEY",
    "rls": false
  },
  "kafka": { "enabled": true, "partitions": 3, "retention_hours": 168 }
}
```

For `gsheet`, omit `gsheet.spreadsheet_id` to have one created for you:
```json
{
  "name": "prod_gsheet",
  "backend": "gsheet",
  "primary_key": "ID",
  "columns": [ { "name": "ID", "type": "string" }, ... ],
  "gsheet": {
    "spreadsheet_title": "Incoming Documents — prod",
    "sheet_name": "מסמכים נכנסים",
    "editors": ["person17@example.com"]
  }
}
```

**Response 201:**
```json
{
  "success": true,
  "repo": { /* fully resolved RepoConfig with spreadsheet_id, gid, table fully-qualified, etc. */ },
  "provisioned": {
    "container_created": true,    // new spreadsheet or new schema created
    "tab_or_table_created": true,
    "columns_added": ["DOC_DATE", "DOC_TOTAL_AMOUNT"],
    "columns_extra_warning": [],
    "kafka_topic_created": true
  }
}
```

**Column type mapping** (single source of truth in `core/types.py`):

| Logical type | GSheet representation | Supabase / Postgres |
|--------------|----------------------|---------------------|
| `string` (default) | text cell, `valueInputOption=USER_ENTERED` | `text` |
| `text` | text | `text` |
| `int` | number | `bigint` |
| `numeric` | number | `numeric` |
| `bool` | `TRUE`/`FALSE` | `boolean` |
| `date` | ISO `YYYY-MM-DD` | `date` |
| `timestamp` | ISO `YYYY-MM-DDTHH:MM:SSZ` | `timestamptz` |
| `json` | stringified JSON in cell | `jsonb` |

For a GSheet repo, the on-disk shape is always strings; the `type` is used by `DiffEngine` for value normalization (so `"42"` and `42` compare equal for `int` columns).

**Canonical error envelope** (all 4xx/5xx responses):
```json
{ "success": false, "error": "<machine_code>", "message": "<human readable>", "details": { ... } }
```

| Status | `error` code | When |
|---|---|---|
| 400 | `validation_error` | Body fails pydantic validation |
| 404 | `repo_not_found` | Unknown `<repo>` in URL |
| 409 | `schema_drift` | `POST /repos` re-run with same name + drifted config |
| 413 | `batch_too_large` | More than `INCOMING_DOCS_MAX_BATCH_SIZE` rows |
| 422 | `primary_key_missing` | Update item without PK in non-create context |
| 501 | `not_implemented` | Reserved (e.g. `DELETE /documents` in v1) |
| 502 | `backend_unavailable` | GSheet/Supabase upstream error after retries |
| 503 | `kafka_unavailable` | Backend write succeeded but Kafka publish failed (response includes `written:true`) |
| 503 | `provisioning_failed` | `POST /repos` rolled back; `details.rollback_state` lists what was undone |

### 3.4 Kafka

```
POST /incomingDocuments/repos/<repo>/kafka/ensure       → creates topic if missing
POST /incomingDocuments/repos/<repo>/kafka/publish      → publish 1..N events to ${prefix}.<repo>
GET  /incomingDocuments/repos/<repo>/kafka/topic        → topic metadata + lag per consumer group
```

Event payload (matches what `Incoming Documents 0.1.6` Webhook trigger expects, so the n8n side just swaps trigger node):
```json
{
  "event_id": "uuid",
  "repo": "prod_gsheet",
  "event_type": "ROW_CHANGED" | "ROW_CREATED" | "MANUAL",
  "occurred_at": "2026-04-30T08:42:11Z",
  "row": { "ID": "abc-123", "STATUS": "PENDING", ... }
}
```

Producer is `confluent-kafka-python` with `enable.idempotence=true`, `acks=all`, `linger.ms=20`, `compression.type=zstd`. Key = `row.ID` (so all events for one ID land on the same partition, preserving order).

### 3.5 Webapp endpoints (read-mostly facade for the UI)

The webapp (§4.4) is a first-class consumer of the API and needs a few endpoints beyond the n8n contract. They live under the same `${INCOMING_DOCS_API_PREFIX}` and are JSON-only.

```
GET  /incomingDocuments/repos/<repo>/stats                     → row count, last write ts, columns, kafka lag
GET  /incomingDocuments/repos/<repo>/documents/<id>            → single row (sugar over /query mode:by_ids)
PATCH /incomingDocuments/repos/<repo>/documents/<id>           → partial update of a single row (sugar over batch upsert)
GET  /incomingDocuments/repos/<repo>/documents/<id>/history    → last N change events for this PK from Kafka (best-effort tail)
GET  /incomingDocuments/repos/<repo>/kafka/tail?limit=100      → SSE stream of recent events on the topic (for live UI)
GET  /incomingDocuments/auth/me                                → current user (from reverse-proxy header) + permissions
```

No new business logic — these are thin aggregations over §§3.1–3.4. SSE uses the existing Kafka producer's admin client to seek-to-end + poll; the stream closes after `INCOMING_DOCS_SSE_MAX_SECONDS=300` to avoid sticky connections.

---

## 4. Core abstractions

### 4.1 `DocumentRepo` (in `core/repo.py`)

```python
class DocumentRepo(Protocol):
    config: RepoConfig

    # ---- provisioning (called by core.provisioning.provision_repo) ----
    def ensure_container(self) -> ContainerReport: ...   # gsheet: spreadsheet; supabase: schema
    def ensure_table(self) -> TableReport: ...           # gsheet: tab/sheet; supabase: table
    def ensure_schema(self) -> SchemaReport: ...         # gsheet: header row; supabase: ADD COLUMN/index
    def ensure_permissions(self) -> PermissionsReport: ... # gsheet: drive share; supabase: grants
    def teardown(self, *, drop_storage: bool) -> None: ... # used on rollback / DELETE?drop_storage=true

    # ---- runtime ----
    def get_columns(self) -> list[str]: ...
    def fetch_all(self, *, columns: list[str] | None = None) -> list[dict]: ...
    def fetch_by_ids(self, ids: list[str], *, columns: list[str] | None = None) -> list[dict]: ...
    def query(self, q: Query) -> list[dict]: ...
    def batch_update(self, updates: list[RowUpdate]) -> list[UpdatedRow]: ...
    def batch_create(self, creates: list[dict]) -> list[CreatedRow]: ...
```

`DiffEngine` (in `core/diff.py`) is **backend-agnostic**:
1. Pull current rows for incoming IDs (`fetch_by_ids`).
2. For each incoming item → bucket into `update` / `create` / `noop`.
3. Apply `priority_sync` rule.
4. Return `DiffResult` consumed by the route handler, which then calls `batch_update` + `batch_create` on the repo.

### 4.2 `GSheetRepo`

- Auth: `google-auth` service-account loaded from `GOOGLE_SERVICE_ACCOUNT_JSON` (path or inline JSON).
- Reads via `spreadsheets.values.get` with the Hebrew sheet name URL-encoded.
- Updates via `spreadsheets.values.batchUpdate` (single HTTP call per batch — same as today's `Google Sheets batchUpdate` node).
- Creates via `spreadsheets.values.append` with `valueInputOption=USER_ENTERED`, `insertDataOption=INSERT_ROWS`.
- Maps incoming dict keys → column letters by indexing the header row. Header row is cached in-memory with TTL `INCOMING_DOCS_HEADER_TTL_SEC=60` (mirrors n8n behaviour where a fresh read happens per batch).
- Rate limiting: token bucket at 50 req/100s/user (Sheets API quota); on 429 → exp-backoff with jitter.

### 4.3 `SupabaseRepo`
- Auth: `SUPABASE_SERVICE_KEY` (header `apikey: <key>` + `Authorization: Bearer <key>`).
- Transport: `httpx.Client` to `${SUPABASE_BASE_URL}/rest/v1/<table>`.
- `fetch_by_ids`: `GET ?<pk>=in.(id1,id2,...)`.
- `batch_update + batch_create`: single `POST ?on_conflict=<pk>` with `Prefer: resolution=merge-duplicates,return=representation` — atomic upsert.
- `query`: translates our `Query` into PostgREST query string.
- `ensure_schema`: mirrors the Supabase reference workflow: introspect via `POST /rpc/run_sql` (or `pg_meta`) → diff against `RepoConfig.columns` → create table + unique index on PK + add missing columns. Never drops columns. Returns `SchemaReport`.

### 4.4 Webapp (frontend)

A single-page app served by the same `apitools` Flask process (no extra container). It is the only UI for **navigating, inspecting, editing, and provisioning** repos and documents.

**Stack**
- React 18 + TypeScript + Vite for the build (`npm run build` → `webapp/dist/`).
- React Router v6 for client-side routing.
- TanStack Query (`@tanstack/react-query`) for caching + revalidation of all GETs.
- Tailwind CSS for styling; Radix UI primitives for accessible widgets (combobox, dialog, tooltip).
- TanStack Table for the document grid (virtualised so 39k rows scroll smoothly).
- `EventSource` (native) for the Kafka tail SSE stream.
- API client auto-generated from a Flask-emitted `/incomingDocuments/openapi.json` via `openapi-typescript` + a thin `fetch` wrapper — zero hand-written types.

**Build & serve**
- Dev: `cd webapp && npm run dev` runs Vite on `:5173` with `/incomingDocuments` proxied to the local Flask on `:8000`.
- Prod: `npm run build` outputs `webapp/dist/`. Flask serves it via a `webapp_bp` blueprint mounted at `${INCOMING_DOCS_WEBAPP_PREFIX}` (default `/incomingDocuments/ui`):
  - `GET /ui/` → `dist/index.html`
  - `GET /ui/assets/*` → `dist/assets/*` with long-`Cache-Control` (Vite hashes the filenames).
  - SPA fallback: any `/ui/<unknown>` returns `index.html` so client routing works on hard refresh.
- Build runs in the apitools Docker image: a multi-stage `Dockerfile` adds `node:20-alpine` as builder, copies the `dist/` into the final python image. No node in the runtime image.

**Routes (client-side)**

| Route | Page | Purpose |
|---|---|---|
| `/` | `RepoList` | Card grid of all repos: name, backend badge, row count, last-write age, kafka-lag pill, health dot. Click → detail. “New repo” button. |
| `/repos/new` | `RepoCreate` | Multi-step wizard: 1) name + backend, 2) PK + columns (with type picker + Hebrew support), 3) backend-specific block (gsheet editors / supabase schema), 4) review + `POST /repos`. Live preview of the resulting JSON. Shows the `provisioned` report on success; rollback details on failure. |
| `/repos/:r` | `RepoDetail` | Header with stats from `GET /repos/:r/stats`. Tabs: **Documents**, **Schema**, **Kafka**, **Settings**. |
| `/repos/:r/documents` | `DocumentBrowser` | Virtualised TanStack Table powered by `POST /documents/query`. Sticky filter bar with the FilterBuilder (one row per `op`). Column visibility toggles. “Export CSV” (client-side from current page). “New document” → modal create form (drives `PUT /documents` with a single create item). |
| `/repos/:r/documents/:id` | `DocumentDetail` | Two columns: left = editable form generated from `RepoConfig.columns` (typed inputs per logical type, Hebrew labels), right = `history` from `GET /documents/:id/history` (Kafka tail filtered by key). Save → `PATCH /documents/:id`. |
| `/repos/:r/schema` | `SchemaEditor` | Shows `RepoConfig.columns` vs live introspection diff (reuses `/schema/introspect`). “Adopt from backend” button → `?adopt=true`. “Add column” form → `/schema/ensure`. Drift warnings (extra columns) shown read-only. |
| `/repos/:r/kafka` | `KafkaTail` | Live SSE stream from `GET /kafka/tail`. Filterable by `event_type` + PK. Pause / resume / clear. Click an event → jumps to `/documents/:id`. |
| `/repos/:r/settings` | `RepoDetail/Settings` | Edit non-schema fields via `PUT /repos/:r`. Danger zone: `DELETE /repos/:r` with optional `?drop_storage=true` (typed-confirmation). |

**Auth & permissions**
- Identity is read from `X-Forwarded-User` / `X-Forwarded-Email` set by Authentik (existing in this stack, see [authentik/](../../../authentik/)). The Flask blueprint enforces auth on every `/incomingDocuments/*` route; the webapp just renders what `GET /auth/me` returns.
- Role model v1: `viewer` (read-only), `editor` (read + write rows), `admin` (read + write + provisioning + delete). Roles come from Authentik group claims; mapping lives in `INCOMING_DOCS_ROLE_MAPPING` env (JSON: `{"group_name": "role"}`).
- Destructive actions (delete repo with `drop_storage=true`, schema/ensure with column type change) require a confirmation dialog typing the repo name.

**State & errors**
- TanStack Query cache key per repo + endpoint; mutations invalidate the affected keys.
- A single `<ErrorBoundary>` + a global toast that maps the canonical error envelope (§3.3) to a human message. The 503 `kafka_unavailable` case is non-blocking — toast says “Written, but the bus didn’t see it. Click to retry publish.”
- `last seen` indicator per page: TanStack Query’s `dataUpdatedAt` shown in the header; a manual refresh button next to it.

**OpenAPI**
- Flask emits `/incomingDocuments/openapi.json` via `apispec` + the existing pydantic models. The webapp build generates `webapp/src/api/types.gen.ts` from it as a `prebuild` step. CI fails if regenerating produces a diff.

---

## 5. Configuration

Add to `apitools/src/incoming_documents/.env.example` (and document in repo `placeholders.env`):

```ini
INCOMING_DOCS_ENABLED=false                         # feature flag; flip to true at phase 4 cutover
INCOMING_DOCS_API_PREFIX=/incomingDocuments
INCOMING_DOCS_REPO_REGISTRY=.storage/incoming_documents/repos.json
INCOMING_DOCS_HEADER_TTL_SEC=60
INCOMING_DOCS_MAX_BATCH_SIZE=500
INCOMING_DOCS_QUERY_MAX_LIMIT=2000                  # /documents/query hard cap; mode:"all" forces pagination

# GSheet
# Dual-mode: if value starts with "{" → parsed as inline JSON; otherwise treated as a filesystem path.
GOOGLE_SERVICE_ACCOUNT_JSON=/run/secrets/gsa.json

# Supabase
SUPABASE_BASE_URL=https://supabase.hacohen.bina-solutions.co.il
SUPABASE_SERVICE_KEY=__PLACEHOLDER__

# Kafka (Redpanda)
KAFKA_BROKERS=redpanda:9092
KAFKA_TOPIC_PREFIX=incoming-documents
KAFKA_CLIENT_ID=apitools-incoming-documents
KAFKA_SECURITY_PROTOCOL=PLAINTEXT                   # in-cluster only — NOT exposed via Traefik; no public listener

# Webapp
INCOMING_DOCS_WEBAPP_PREFIX=/incomingDocuments/ui
INCOMING_DOCS_WEBAPP_DIST=apitools/src/incoming_documents/webapp/dist
INCOMING_DOCS_SSE_MAX_SECONDS=300
# JSON: {"<authentik group name>": "viewer" | "editor" | "admin"}
INCOMING_DOCS_ROLE_MAPPING={"hacohen-incoming-docs-admins":"admin","hacohen-incoming-docs-editors":"editor","hacohen-staff":"viewer"}
```

### 5.1 `/health` probe
- `GET /incomingDocuments/health` — shallow: process up + registry file readable. Always cheap (< 5 ms).
- `GET /incomingDocuments/health?deep=true` — also probes: GSheet token mints OK, `${SUPABASE_BASE_URL}/rest/v1/` returns 200, Kafka admin client lists topics. Returns `200` with per-component `{ok:true|false, latency_ms}` map; overall status `200` if all probed components are OK, else `503`.

---

## 6. Dependencies to add to `apitools/requirements.txt`

```
google-api-python-client>=2.130
google-auth>=2.30
httpx>=0.27
pydantic>=2.7
confluent-kafka>=2.5
tenacity>=8.4         # backoff for transient API errors
orjson>=3.10          # fast JSON for batch payloads
apispec>=6.6          # /openapi.json generation for the webapp client
apispec-webframeworks>=1.2
```

### 6.1 Webapp (`apitools/src/incoming_documents/webapp/package.json`)

Runtime:
```
react, react-dom, react-router-dom, @tanstack/react-query, @tanstack/react-table,
@radix-ui/react-dialog, @radix-ui/react-tooltip, @radix-ui/react-popover,
clsx, tailwindcss, lucide-react
```

Build / dev:
```
vite, @vitejs/plugin-react, typescript, openapi-typescript, eslint, prettier,
@playwright/test (for webapp e2e)
```

---

## 7. Operational notes

- **Containers (compose.yml under profile `incoming-docs`):**
  - `apitools` (existing, gains the new blueprint via env-var feature flag `INCOMING_DOCS_ENABLED=true`; Dockerfile gets a `node:20-alpine` builder stage that compiles the webapp into `/app/webapp/dist`).
  - `redpanda` (new) + `redpanda-console` (optional).
  - **No Python consumer container** — n8n's native Kafka Trigger node consumes directly.
  - **No separate webapp container** — served by Flask from the built `dist/`.
- **Traefik:** route `${INCOMING_DOCS_API_PREFIX}` and `${INCOMING_DOCS_WEBAPP_PREFIX}` on the existing apitools router (no new TLS host). Both go through Authentik forward-auth (same middleware as the rest of the stack). Redpanda's `9092` is **not** exposed via Traefik — internal compose network only.
- **Secrets:** mount `GOOGLE_SERVICE_ACCOUNT_JSON` as a Docker secret at `/run/secrets/gsa.json`.
- **Observability:** reuse existing Sentry SDK (already in apitools); add Kafka producer error breadcrumbs. The webapp wires `@sentry/react` to the same DSN so client-side errors surface in the same project.
- **Migration safety:** behind feature flag `INCOMING_DOCS_ENABLED`. Disabled by default until phase 4 starts. The webapp is hidden when the flag is off (the `/ui` route returns 404).

---

## 8. Build order (phase 3 sub-steps)

1. Skeleton: blueprint, registry, models, errors, `RepoConfig` validation, type-mapping table.
2. Diff engine (pure-python, fully unit-tested against the production CSV — no external calls).
3. `GSheetRepo` runtime path (read + batchUpdate + append) — integration tested against a throwaway sheet.
4. `GSheetRepo` provisioning path (`ensure_container` / `_table` / `_schema` / `_permissions`) — integration tested by creating a fresh spreadsheet end-to-end and tearing it down.
5. `/documents` PUT and POST routes wired through diff engine + GSheetRepo.
6. `SupabaseRepo` runtime path (read + upsert) — integration tested via PostgREST testcontainer.
7. `SupabaseRepo` provisioning path (`ensure_container` schema + `ensure_table` + `ensure_schema` ADD COLUMN + grants) — mirrors the Supabase reference workflow's introspection branch.
8. `core.provisioning.provision_repo()` orchestrator + rollback + `POST /repos` route. End-to-end test: `create_repo("e2e_gsheet")` and `create_repo("e2e_supabase")` from scratch on a clean stack.
9. Kafka producer + topic ensure + `/kafka` routes; integrate into provisioning step 6.
10. Verify n8n native Kafka Trigger consumes events end-to-end (dry-run flag in producer first).
11. Add Redpanda to `compose.yml` under profile `incoming-docs`.
12. **Webapp — backend support**: add `apispec` `/openapi.json`, the `webapp_bp` static blueprint, the §3.5 facade endpoints (`/stats`, `/documents/<id>` GET+PATCH, `/documents/<id>/history`, `/kafka/tail` SSE, `/auth/me`), the Authentik header parsing + role middleware.
13. **Webapp — frontend scaffold**: Vite + React + TS + Tailwind project under `webapp/`; OpenAPI client generation; auth/me hook; layout shell; `RepoList` page.
14. **Webapp — repo lifecycle pages**: `RepoCreate` wizard (driving `POST /repos`), `RepoDetail` with stats, `SchemaEditor` (introspect-adopt + ensure).
15. **Webapp — document UX**: `DocumentBrowser` (virtualised grid + filter builder backed by `POST /documents/query` with pagination) and `DocumentDetail` (typed form + `PATCH`).
16. **Webapp — live**: `KafkaTail` SSE page + `DocumentDetail` history sidebar.
17. **Webapp packaging**: multi-stage Dockerfile (node builder → python runtime), Flask serves `dist/`, OpenAPI-drift CI check, Playwright e2e (see TESTING-STRATEGY.md §11).
18. Final wire-up + flag flip + run the test suite (see TESTING-STRATEGY.md).

---

## 9. Open questions (deferred to phase 3 kickoff)

- Should `priority_sync_columns` be hard-coded per-repo or read from a sentinel column inside the sheet? **Decision needed before step 2.**
- ~~Should the Kafka consumer call 0.1.6's existing Webhook directly, or should it become an n8n native Kafka trigger node?~~ **Resolved**: native Kafka Trigger node in n8n. Verify availability in our queue-mode worker before step 9.
- Header row cache — do we tolerate stale headers for up to `HEADER_TTL_SEC`, or invalidate on every write? **Tentative: 60 s TTL + invalidate on 4xx schema mismatch.**
