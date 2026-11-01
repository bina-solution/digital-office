# INDOX — Final Architecture (2026-08-04, post Sheets-excision)

> The incoming-documents dancing machine, end to end. Google Sheets is fully
> legacy. Everything reads/writes the registered app-level Supabase indox
> instance (`incoming-documents-main`, table `public.incoming_documents`)
> through ONE workflow API (`indoxApiRouter01` → `indoxApiSupabase01`) and ONE
> code API (`apps/indox` BFF). No workflow talks to Drive/Gmail directly — only
> to the `apps/drive` (`driveApi01`) and `apps/mail` (`gmailApiRouter01` /
> `mailapi`) app APIs.

## 1. The two API planes (unified, deduped)

| Plane | Entry | Backend | Match rules (source of truth now shared) |
|---|---|---|---|
| **Workflow API** | `indoxApiRouter01` (5 nodes) | `indoxApiSupabase01` (27 nodes, 11 postgres nodes, credential `yY8FYvp6Kz86pt2t`) | 3 rules: `COMPANY_ID+COMPANY_DOC_ID`, `COMPANY_ID+SHORT_DOC_ID`, `HASH` |
| **Code API** | `apps/indox` FastAPI BFF (`incoming-documents-shlomo-laptop`) | Supabase PostgREST + direct postgres, registry `apps/indox/storage/incoming_documents/repos.json` | same 3 rules (repos.json aligned 2026-08-04) |

- **Router** (`indoxApiRouter01`): `When Called` → `If Management`
  (`INLINE_ACTION ∈ RESET/STATUS/INJECT/SCAN` ?). Management → `SyncApi0000000001`;
  data CRUD → `indoxApiSupabase01`. The sheets backend, the backend switch, and
  the `INDOX_DATA_BACKEND` toggle are gone (hook, `.env.ex`, `ci-env.sh`,
  `automations-reset.py` all cleaned).
- **Code API registry** (`repos.json`): repo `incoming-documents-main`,
  `backend: supabase`, `gsheet: null`, table `public.incoming_documents`,
  kafka enabled. Multi-profile ready: each company profile will own its own
  repo entry + table (per-instance scoping), the n8n plane will gain PROFILE
  awareness later.
- **ID generation difference (documented, not forced to converge):** the code
  API auto-assigns `uuid4` PKs; the workflow plane generates `doc_<ts36><rand6>`.
  Both are valid string PKs; logical-identity matching (the 3 rules) is what
  prevents duplicates, so format uniformity is not required for correctness.
- **Intake upload (2026-08-04, later same day):** `POST /documents/upload`
  (full path `/incomingDocuments/documents/upload`) is the consolidated intake
  upload endpoint for app-level clients (chat); it uploads through the drive app.

## 2. Every file taking part in the machine

### A. n8n blueprint — `apps/indox/blueprint/n8n/` (67 workflows)

**Data plane (the ONE way rows move):**
- `indoxApiRouter01.json` — single entry for all data CRUD + management.
- `indoxApiSupabase01.json` — the supabase engine: GET/GETALL/UPSERT/DELETE,
  `Resolve IDs` (3-rule logical matching + ID gen), `Poll Line Changes` (30s
  schedule) → dispatches changed docs to the driver, sync-v3 DELIVER atomic
  content-dedup insert.
- `indoxDocBatchUpsert01.json` — the write path every caller uses:
  `executeWorkflow` → `UPSERT Adapter` → `indoxApiSupabase01`, then emit IDs +
  unlock the doc's process lock. (Sheets update arms excised.)
- `indoxDocGet01.json` — read path: `executeWorkflow` → supabase GET/GETALL
  → match. (Sheets query arms + dead webhook excised.)
- `indoxDocUploader01.json` — moved to `legacy/n8n/indox-sheets-era/` (2026-08-04,
  later same day): chat intake now goes through the app API —
  `POST /incomingDocuments/documents/upload` (new, uploads via the drive app) +
  `PUT /repos/incoming-documents-main/documents` (existing batch upsert).
- `indoxV2Upsert01.json` — delegates to `indoxDocBatchUpsert01`.

**Ingestion (sync layer, all drive/gmail via app APIs):**
- `SyncScanner00001` → `SyncScanUnit0001` (claims units from `sync_registry`) →
  dispatches processor via `$json.processor_wf`.
- `syncV3Main0001` / `syncV3Unit0001` / `syncV3Deliver0001` — the v3 sync
  engine (all 5 registry sources are `engine: v3`); DELIVER writes via the
  content-dedup insert in `indoxApiSupabase01`.
- Processors: `SyncProcGDoc0001` (drive gdoc), `SyncProcBS000001` (drive bs),
  `indoxGmailDocDownloader01`, `indoxGmailBSDownloader01`,
  `indoxGmailLinkDownloader01` (gmail). All call `indoxProcessDocument01`
  (apitools OCR + `driveApi01` upload) then `indoxDocBatchUpsert01`.
- `mailLabelEngine01.json` — classifies inbound gmail, applies routing labels
  (`DOC_TO_SYNC` / `BS_TO_SYNC` / `DOC_LINK_TO_SYNC`). Orphan sheets node excised.
- `indoxGmailActionProcessor01` + `indoxGmailActionsScanner01` — gmail action loop.

**The driver (Determine-Action self-loop):**
- `indoxV2Driver01.json` (131 nodes) — the heart. `Get Changed Docs` poll feeds
  it; it resolves one field per pass via the action families below, re-entering
  until `mark_completed`. Sheets-era nodes (trigger, empty_row arm, orphan
  readers) excised; `Switch1[3]` now terminates on a no-op.
- Action families: `indoxV2ActionsGDoc01`, `indoxV2ActionsShip01`,
  `indoxV2ActionsBS01`, `indoxV2ActionsGlobal01`, `indoxV2Decide01`.
- Resolvers: `indoxV2FigureDocType01`, `indoxV2FigureCompanyId01`,
  `indoxV2QueryDocDate01`, `indoxV2QueryInvoiceId01`,
  `indoxV2QueryPurchaseId01`, `indoxV2QueryShipmentId01`,
  `indoxV2QueryTotalAmt01` (sheet arm excised),
  `indoxV2ExtractInvoiceGemini01`, `indoxV2ExtractBalanceSheet01`,
  `indoxV2SearchFile01`, `indoxV2SearchWarehouse01`.
- `indoxV2UploadApiTools01` — uploads to apitools OCR (`http://apitools:8080`).
- `processLock01` — per-doc lock so concurrent passes don't clobber.

**Support / management / config:**
- `indoxSettings01.json` — settings/companies/queries config (supabase `settings`).
- `SyncApi0000000001` / `SyncSource000001` — STATUS/RESET/INJECT management plane.
- `IndoxResetFull01` / `IndoxResetGml001` / `tVzFMkz18pCsXRyw` — resets.
- `indoxHealth00001` — probes the drive + mail app APIs INDOX depends on.
- `JQExV3*` (12) — v3 extraction runners (called by the Python BFF, not the pipeline).
- `indoxV2*Test*` / `syncV3*Test*` / `IndoxInjectDemo01` / `sv3Inject3x001` — test fixtures.

### B. Code plane — `apps/indox/`
- `app/main.py` — FastAPI BFF (`incoming-documents` service).
- `app/incoming_documents/api/__init__.py` — REST routes; auto-uuid4 PK;
  `fetch_by_match_rules` + `compute_diff` upsert.
- `app/incoming_documents/core/` — `registry.py`, `repo.py`, `diff.py`,
  `models.py` (incl. `upsert_match_rules`), `provisioning.py`, `types.py`.
- `app/incoming_documents/backends/supabase*.py` — the live backend
  (`gsheet*.py` retained but unreachable; `backend: supabase` is pinned).
- `app/incoming_documents/kafka/` — broker abstraction (Null when unconfigured).
- `app/incoming_documents/poller.py`, `repo_factory.py`, `extraction.py`.
- `storage/incoming_documents/repos.json` — the registry (source of truth).
- `hooks/migrate-legacy.py` — legacy data loader (uq_incdoc_hash dedupe).
- `app/webapp/` — the console SPA (the UI you verify in browser42).

### C. Cross-app integration (indox never touches drive/gmail directly)
- **apps/drive** — `driveApi01` (73 call sites from indox) + `drive` blueprint.
- **apps/mail** — `gmailApiRouter01` (66 call sites), `gmailApiImap01`
  (active) / `gmailApiOauth01` (fallback), `mailapi` HTTP service. Mail calls
  `indoxApiRouter01` back for doc-context.
- **apps/chat** — consumes `indox-api` (companies read + document upload + record create) over `http://incoming-documents:8080`.
- **apps/apitools** — OCR/extraction backend (`indoxV2UploadApiTools01`).

## 3. What moved to legacy (2026-08-04)

`legacy/n8n/indox-sheets-era/`: `indoxApiSheets01`, `indoxDocCreate01`,
`indoxSetupWF001`, `logger01` (live DB rows deleted; callers rewired). The
router, hook toggle, and env var are gone. See
`ai/context/retired-code-and-workflows.md` §2026-08-04 for the evidence.

## 4. End-to-end data flow (the one true path, supabase-only)
1. Gmail message arrives → `mailLabelEngine01` classifies, applies routing label.
2. `SyncScanner00001` reads `sync_registry`, `SyncScanUnit0001`/`syncV3Unit0001`
   claim the unit, dispatch the processor.
3. Processor downloads via drive/mail app API → `indoxProcessDocument01` (apitools
   OCR) → `indoxDocBatchUpsert01` → `indoxApiRouter01` → `indoxApiSupabase01`
   → row in `incoming_documents` (IN_PROGRESS).
4. `Poll Line Changes` (30s) picks up the row → `indoxV2Driver01` Determine-Action
   loop resolves type/company/date/amount/ids → extractor families → each write via
   `indoxDocBatchUpsert01` → until **COMPLETED**.
