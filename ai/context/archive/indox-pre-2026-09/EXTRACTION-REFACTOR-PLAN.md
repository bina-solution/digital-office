# INDOX Extraction Pipeline Refactor — Safe Migration Plan

**Status: PLAN ONLY. Nothing in this document has been implemented. Read-only research.**
**Author's note on scope honesty:** every claim below is either a `file:line` citation into this
checkout or a live query result, labeled with which database answered it. Where the owner's brief
assumed something this research found to be different, that correction is called out explicitly
rather than folded in silently — see §0.

## 0. Corrections to the brief, up front

**0.1 — Which database this plan's live numbers come from.** The brief (and the deployment-hacohen
skill it points at) describes `hacohen-vps` (the production VPS). Mid-research the coordinator
confirmed this session's actual working environment is the **local dev stack** — every container
suffixed `-shlomo-laptop`, reached through `DOCKER_HOST=unix:///run/bbox-docker.sock` (from WSL, per
`CLAUDE.md`'s "Windows via `bbox.cmd`" path). Before that correction arrived, one research pass tried
`ssh hacohen-vps` — it **failed outright** (`Permission denied (publickey,password)`, the configured
key is no longer authorized on that host) before any query ran, and a second pass probed
`https://n8n.hacohen.bina-solutions.co.il` directly — also read-only (an unauthenticated `curl`/`GET`
against a public webhook path, no write, no credential guessing beyond one attempt). **No query, read
or write, ever reached production.** Every population count and every "is this node live" check in
this document was re-run (or run for the first time) against the local stack, confirmed by container
name (`supabase-db-shlomo-laptop`, `n8n-postgres-shlomo-laptop`) and cross-checked against the
coordinator's own expected numbers (56,249/56,250 total rows, ~6,200 real rows) before being trusted.

**0.2 — `indoxProcessDocument01` is not the main pipeline.** The brief's throughput argument centers
on this workflow's "strictly serial 7-hop chain, 3 separate calls to the same apitools endpoint." Both
facts are confirmed true by file:line (§5) — but this workflow is the **older Gmail-ingestion lane**
(invoked only by `indoxGmailDocDownloader01`, `indoxGmailLinkDownloader01`, `SyncProcGDoc0001` —
confirmed by grepping its workflow id across every file in `apps/indox/blueprint/n8n/`). It is **not**
reachable from the main state machine (`indoxV2Decide01` → `indoxV2ActionsGlobal01`/`GDoc01`/`Ship01`/
`BS01`) that a live-count query shows handling the bulk of real rows. That main pipeline has its own,
**worse** fragmentation — up to 13 separate local `apitools` round trips per document across 7
workflows — which turns out to be the stronger throughput argument. See §5 for the corrected,
quantified comparison.

**0.3 — The UI blast radius is smaller than implied.** Grepping the three UI files named in the brief
for every `AI_*`/`SELECTED_*`/`SELECTION_*`/`EX_*`/`FIGURE_*` column name found matches in **exactly
one** file, `DocumentDetailPage.tsx` — and only through a generic prefix categorizer, not per-column
bindings. `DocumentBrowserPage.tsx` and `BinaTable.tsx` have **zero** references to any of these
columns. Details in §2.6.

**0.4 — An in-flight, uncommitted fix exists on `indoxDocBatchUpsert01` right now.** Its trigger
schema currently *does* declare `THUMBNAIL`, `THUMBNAIL_COMPLETED`, `CONNECTION`, `RETRY_COUNT`,
`NEXT_RETRY_AT` — but `git diff`/`git blame` on
`apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json` show this is an **uncommitted, working-tree-only
change** (`git blame -L 11,11` → `Not Committed Yet`). This is exactly the class of defect G39 exists
to catch, sitting fixed-but-unlanded. See §4.1 — this needs to be committed *before or alongside* this
refactor's own schema additions, or it risks being silently reverted by an unrelated `git checkout`/
`git reset`.

**0.5 — The settings cache-invalidation webhook is LIVE on this session's environment.** Confirmed
directly against `n8n-postgres-shlomo-laptop`:
```
select active, nodes::text like '%Invalidate Cache Webhook%', nodes::text like '%settings-invalidate-cache-webhook%'
from workflow_entity where id='indoxSettings01';
 t | t | t
```
So `PUT /config/settings/<key>`'s best-effort call to `_invalidate_settings_cache()`
(`apps/indox/app/incoming_documents/api/__init__.py:161-180`) does land on a real, active webhook here
— settings changes take effect immediately, not after a 20-minute TTL. The node is still **not
committed to git**, same caveat as §0.4: don't let it get reverted.

---

## 1. Current state

### 1.1 Every extraction step, precisely

| # | Workflow | Node(s) | AI or Local | Field(s) | Writes column(s) | Runs when | Cost |
|---|---|---|---|---|---|---|---|
| 1 | `indoxV2FigureCompanyId01` | `Find Option`, `Extract COMPANY ID AFTER` (:127-153, :577-610) | Local (apitools `find option`/`find after`) | Company ID | `COMPANY_ID`, `COMPANY_NAME` (via `indoxV2ActionsGlobal01.json:978-987`) | Base lane, always first (before type) | 1-2 `documentJsonQuery` calls; keyword default at `:611-624` |
| 2 | `indoxV2FigureDocType01` | `Find Option` (:170-195), `Keywords` (:128-169, 4 hardcoded kw lists) | Local | Doc type | `TYPE` (`indoxV2ActionsGlobal01.json:915-920`) | Base lane, after company resolved | 1 `documentJsonQuery` call |
| 3 | `indoxV2ExtractInvoiceGemini01` | `Document Processor`/`Text Processor` (`@n8n/n8n-nodes-langchain.googleGemini`, :856-923) | **AI** | Company ID, type, doc ID, date, amount, shipment IDs, order IDs (7 fields, one prompt, :813-835) | `AI_COMPANY_ID, AI_TYPE, AI_DOC_ID, AI_DOC_DATE, AI_DOC_AMOUNT, AI_SHIPMENT_IDS, AI_ORDER_IDS` (`indoxV2ActionsGlobal01.json:1364-1409`) | Base lane, strictly **after** local type classification completes, gated by `AI_EXTRACTION_COMPLETED` — runs once per document, its output feeds both lanes | `models/gemini-3.1-pro-preview` + `models/gemini-3-flash-preview`, hardcoded model names (:861-863, :890-892), `maxTries:3`, backed by `ai_extraction_cache` (key=`<kind>:md5(bytes)`) |
| 4 | `indoxV2QueryDocDate01` | `Extract AFTER` + `Extract BELOW` (:210-267) | Local | Doc date | `DOC_DATE` (`indoxV2ActionsShip01.json:1783-1784`) | Per-type lane | 2 `documentJsonQuery` calls, 60s timeout, `maxTries:5` |
| 5 | `indoxV2QueryInvoiceId01` | `Extract AFTER` + `Extract BELOW` (:210-267) | Local | Invoice/doc ID | `COMPANY_DOC_ID` (`indoxV2ActionsShip01.json:2874-2875`) | Per-type lane (called for **both** GDoc and Shipment types) | 2 calls |
| 6 | `indoxV2QueryShipmentId01` | `Extract SHIPMENT ID AFTER` + `...BELOW` (:9-78) | Local | Shipment ID | `SHIPMENT_DOC_ID` (`indoxV2ActionsShip01.json:1740-1741`) | Per-type lane | 2 calls (+`draw:true`) |
| 7 | `indoxV2QueryPurchaseId01` | `Extract AFTER`/`BELOW` ×2 sets + unused `Information Extractor`/Ollama fallback | Local (+dormant local-LLM fallback) | Purchase order ID | `PURCHASE_ID` (`indoxV2ActionsShip01.json:2612-2613`) | Per-type lane | 2 calls; Ollama `qwen2.5vl:3b` fallback exists but is off the `If has results1` false branch — effectively unused |
| 8 | `indoxV2QueryTotalAmt01` | `Extract AFTER`/`BELOW` (:210-267) | Local | Total amount | `DOC_TOTAL_AMOUNT` (`indoxV2ActionsShip01.json:2710-2711`) | Per-type lane | 2 calls |
| 9 | `indoxV2ExtractBalanceSheet01` | `Document Processor`/`Text Processor`/`Text Processor1` (Gemini, :1004-1301) | **AI only** — confirmed zero `apitools`/`documentJsonQuery` calls anywhere in this file (only one `documentOcr` call, for OCR text, :1305) | BS header, transaction lines, totals | `documentDate, lines[], documentTotalAmount` returned to `indoxV2ActionsBS01` (no direct DB write traced in this file) | BS lane, **no local step precedes it at all** | `gemini-3.1-pro-preview`×2 + `gemini-2.5-pro`, `maxTries:5`, `ai_extraction_cache`-backed, + per-company prompt override (`CONFIG1`/`CONFIG FINAL`, :1406-1560) |
| 10 | `Selection & Scoring Logic1` (embedded code) | Duplicated verbatim in `indoxV2ActionsGDoc01.json:673-684` **and** `indoxV2ActionsShip01.json` (same code) | Neither — reconciles AI vs local | Compares `AI_*` vs bare local columns, scores agreement | `SELECTED_COMPANY_ID, SELECTED_DOC_ID, SELECTED_DOC_TIPE, SELECTED_DOC_AMOUNT, SELECTED_DOC_DATE, SELECTED_DOC_SHIPMENT_ID, SELECTED_DOC_ORDER_ID, SELECTION_CERTAINTY, SELECTION_SOURCE, SELECTION_COMPLETED` | Per-type lane, after all local queries + AI both complete | Pure JS, 0/50/100 point scoring, Hebrew debug strings |
| 11 | `indoxV2Driver01:1266-1276` "Selection & Scoring Logic" | — | Neither | A **third**, independently-scored copy of the same reconciliation concept (0-100/`HIGH`/`MEDIUM`/`LOW`/`NONE`) | — | Wired only into Driver's test-fixture harness, not the production path | Dead-ish, but a live maintenance hazard — 3 divergent scoring formulas for the same decision |
| 12 | `indoxProcessDocument01` (separate Gmail lane, **not** the main pipeline — see §0.2) | `Document OCR` → `Figure Document COMPANY_ID` → `Extract InvoceId` → `Extract ShipmentId` → `Extract Purchase ID` → `Map Extractions` → `Document Properties` → `Validate Document` (8 nodes, 7 hops, :9-826) | Local only, **zero AI** | shipment_id, invoice_id, company_id, purchase_id, document_id/type | Returned to Gmail-lane caller as fields; final SQL write not traced (caller workflows were out of this scan's required-read set) | Gmail-ingestion lane only | `Extract InvoceId`/`ShipmentId`/`Purchase ID` are **3 separate `POST /documentJsonQuery` calls** to the identical endpoint, confirmed verbatim (:73-98, :47-72, :337-362) — the brief's claim, confirmed true, but scoped to this one lane |
| 13 | `JQExV3*` family (`JQExV3Base000001`, `Invoice001`, `Order00001`, `Ship000001`, `BS00000001` + 4 `Run*` wrappers) | `Load V3 Config` (Postgres, reads `settings.q_v3_%`) → `Fan Fields` → `Query apitools` → `Collect` | Local, config-driven, **not AI** | All base/per-type fields, one query per field, config sourced live from `public.settings` | None — **not wired into the live pipeline at all** (grepped every workflow id across the whole directory: appears only inside its own files + its own `jqexv3-run-*` webhooks) | Standalone prototype, reachable only via its own webhooks (used today by a dataset-based eval harness, see §3.3) | 1 apitools call per field per category, `timeout:300000`, `maxTries:3` |

### 1.2 Diagram — current flow

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    indoxV2Decide01                       │
                    │       (routes every doc through the BASE lane first)     │
                    └──────────────────────────┬────────────────────────────┘
                                                 ▼
                    ┌─────────────────────────────────────────────────────────┐
   BASE LANE        │           indoxV2ActionsGlobal01 ("DOC BASE")            │
  (indoxV2Actions-  │                                                          │
   Global01)        │  1. Figure Document COMPANY_ID  (local, 1-2 apitools)    │
                    │  2. Figure Document Type        (local, 1 apitools)      │
                    │  3. Extract Invoice via Webhook (AI, Gemini) ─────┐      │
                    │     → AI_COMPANY_ID/TYPE/DOC_ID/DOC_DATE/          │      │
                    │       DOC_AMOUNT/SHIPMENT_IDS/ORDER_IDS  (1 call)  │      │
                    └──────────────────────────┬──────────────────────┼──────┘
                                                 ▼                      │ (AI output reused,
                          TYPE resolves the doc into one lane:          │  not re-called)
                    ┌───────────┬───────────┬───────────┐               │
                    ▼           ▼           ▼           ▼               │
              ┌──────────┐┌──────────┐┌──────────┐                     │
   PER-TYPE    │ GDoc     ││ Shipment ││ BS       │                     │
   LANE        │(invoice/ ││          ││          │                     │
              │ order)   ││          ││          │                     │
              │          ││          ││          │                     │
              │ 5 local  ││ 5 local  ││ NO local  │◄────────────────────┘
              │ Query*   ││ Query*   ││ step at   │
              │ sub-wf   ││ sub-wf   ││ all       │
              │ calls,   ││ calls,   ││           │
              │ each     ││ each     ││ AI-only:  │
              │ AFTER+   ││ AFTER+   ││ Extract   │
              │ BELOW =  ││ BELOW =  ││ Balance   │
              │ up to 10 ││ up to 10 ││ Sheet01   │
              │ apitools ││ apitools ││ (Gemini,  │
              │ calls    ││ calls    ││ 3 model   │
              │          ││          ││ nodes)    │
              │ Selection││ Selection││           │
              │ &Scoring ││ &Scoring ││ No        │
              │ Logic1   ││ Logic1   ││ SELECTED_*│
              │ (DUP'd)  ││ (DUP'd)  ││ writes    │
              │ → SELECTED_*/SELECTION_*│           │
              └──────────┘└──────────┘└──────────┘

  SEPARATE, OLDER LANE (not reachable from Decide01 — Gmail ingestion only):
  indoxGmailDocDownloader01 / indoxGmailLinkDownloader01 / SyncProcGDoc0001
    → indoxProcessDocument01: OCR → FigureCompanyId → 3× separate documentJsonQuery
      calls (InvoiceId/ShipmentId/PurchaseId) → Map → Validate   [local only, no AI]

  ORPHANED, NOT WIRED IN (config-driven prototype, used only by a dev eval harness):
  JQExV3Base000001 / Invoice001 / Ship000001 / BS00000001  (+ 4 jqexv3-run-* webhooks)
    reads public.settings 'q_v3_%' rows, one apitools call per field, local only
```

### 1.3 The duplication ledger — every field defined more than once

The brief frames this as AI-prompt-vs-local-query, 2-way. The evidence shows most fields are actually
defined **3-4 times**, because the unwired `q_v3_*` settings rows are a live, populated *third* copy
nobody reads yet:

| Field | AI prompt (1) | Live local query (2) | Dormant `q_v3_*` copy (3) | 4th copy? |
|---|---|---|---|---|
| Company ID | `indoxV2ExtractInvoiceGemini01.json:820` — "ח.פ, עוסק מורשה, מספר תאגיד" | `indoxV2FigureCompanyId01.json:614` — `["עוסק מורשה","ח.פ","ע.מ",...]` | `settings.q_v3_company` (confirmed live in DB, `action:"find option"` against a company-identifier list) | — |
| Invoice/doc ID | `:820` item 4, 5-item preference order | `indoxV2QueryInvoiceId01.json:420-432` — 16 Hebrew variants | `settings.q_v3_invoice_id` (confirmed live) | `indoxV2FigureDocType01.json:140-143` `invoice_kws` — a *classifier* copy, not extraction, but the same phrases again |
| Shipment ID | `:820` item 6 | `indoxV2QueryShipmentId01.json:144` — 30 variants | `settings.q_v3_shipment_id`/`q_v3_linked_shipment` | — |
| Doc date | `:820` item 3, 4-step preference | `indoxV2QueryDocDate01.json:282` — 22 variants + regex fallback | `settings.q_v3_date_base`/`date_invoice`/`date_shipment`/`date_bs` (4 separate live rows) | — |
| Purchase/order ID | `:820` item 5 | `indoxV2QueryPurchaseId01.json:334` — 15 variants | `settings.q_v3_order_id`/`purchase_order_id_query`/`q_purchase_id_after` (3 live rows) | — |
| Total amount | `:820` item 2 | `indoxV2QueryTotalAmt01.json:381` — 60+ variants | `settings.q_v3_amount_invoice`/`amount_shipment`/`q_amount_after`/`q_amount_below` (4 live rows) | — |
| Doc type | `:820` item 7, 5-way classification | `indoxV2FigureDocType01.json:130-156` — 4 separate keyword lists | `settings.q_v3_type` (confirmed live, `find option` against 11 BS-specific phrases plus fallbacks) | — |

**The owner's design target — "the local JSON query per value is the single place a field is
defined" — is not a new idea to invent. It already exists, live, in `public.settings.q_v3_*`, with a
routing table (`q_v3_routing`, confirmed live) mapping field → query per category, and it is already
rendered/editable in production UI** (`ExtractionQueries.tsx`, see §2.5). **The gap is that nothing in
the live pipeline reads it.** This changes the shape of the migration from "invent a new
single-source-of-truth format" to "wire the existing one in and delete the 3-4 redundant copies
around it" — a smaller, lower-risk task than greenfield design.

A second, unrelated-to-extraction-but-adjacent naming duplication: the bare canonical columns
themselves may already be doubled — `INVOICE_ID` (schema.sql:105) vs `COMPANY_DOC_ID` (the one
actually written, per traced evidence in §1.1 row 5), and `TOTAL_AMOUNT` (schema.sql:24) vs
`DOC_TOTAL_AMOUNT` (the one actually written). Neither pair was in this scan's required-read list to
resolve fully — flagged as an **open question for the owner** in §6, not assumed either way.

### 1.4 Where the query definitions live

Confirmed live in `public.settings` (local stack, `instance='incoming-documents-main'`), 41 rows
matching `key like 'q\_%'` or the legacy keyword-list keys, including all 14 `q_v3_*` field queries,
`q_v3_routing`, and the older `q_settings_invoice_id`/`q_amount_after`/etc. generation. Query shape,
confirmed both from a live row and from the apitools parser that consumes it
(`apps/apitools/src/ocr_core/ocr_json_query.py:190-712`):
```json
{"action": "find after", "action_value": [...], "value_validations": [...], "is_rtl": true,
 "fallbacks": [{"action": "find regex", ...}]}
```
`fallbacks` (an ordered retry list within **one** query object, consumed **server-side** by apitools in
a single call) is the mechanism that already replaces the "AFTER-then-BELOW-as-two-HTTP-calls"
pattern the live `Query*` workflows use today — the `q_v3_*` rows already use it (e.g.
`q_v3_date_base`'s `fallbacks` array). This is the concrete apitools-side building block the target
design's "one call per value" relies on (§5).

### 1.5 apitools — what each endpoint does (`apps/apitools/src/api/__init__.py`, `ocr_api.py`, `ocr_core/`)

| Endpoint | What it does | Per-call cost pattern |
|---|---|---|
| `POST /documentOcr` | OCRs a file once, caches result in Postgres `ocr_cache` keyed by `file_hash` (md5 of bytes) | One-time per document; cache hit skips re-OCR |
| `POST /documentJsonQuery` | Builds a **fresh `OcrObject` per HTTP call** (`ocr_api.py:246`), runs **exactly one** query against it | N fields = N HTTP round trips, each re-materializing the query engine from the cached OCR JSON |
| `POST /documentDraw` | Loads the `OcrObject` **once**, then loops a `queries: [{label, ocr_json_query}, ...]` array against the **same** object in one request (`api/__init__.py:173-208`) | 1 HTTP call regardless of query count — the "load once, iterate" pattern the brief describes, confirmed to exist, confirmed **not** used by `/documentJsonQuery` or any live extraction workflow today |
| `POST /docGen` | Unrelated — synthetic test-document generation, not extraction | n/a |

`OcrQuery.annotations_aligned_with_annotation` (`ocr_core/ocr_query.py:188-199`) memoizes per-document
alignment **within one `OcrObject`'s lifetime** — shared across every query in one `/documentDraw`
call, but rebuilt from scratch on every separate `/documentJsonQuery` call. This is the concrete
mechanism-level reason batching queries saves real work, not just HTTP overhead.

### 1.6 The UI's actual dependency on these columns

Grepped for every `AI_*`/`SELECTED_*`/`SELECTION_*`/`EX_*`/`FIGURE_*` name across
`apps/indox/app/webapp/src/**`:

- `DocumentBrowserPage.tsx`, `BinaTable.tsx` — **zero matches.** Neither displays, filters, nor sorts
  on any of these columns today.
- `DocumentDetailPage.tsx` — **one mechanism**, a generic field-to-section categorizer
  (`fieldGroup()`, `DocumentDetailPage.tsx:26-37`):
  ```tsx
  if (n.startsWith('AI_')) return 'זיהוי AI';
  if (n.startsWith('SELECTED_') || n.startsWith('SELECTION_')) return 'התאמה ובחירה';
  ...
  return 'אחר';   // anything unmatched falls here — never crashes, never hides a field
  ```
  This is **not** a per-column binding; it's a prefix/suffix dispatch that degrades gracefully (an
  unrecognized column just lands in the "אחר"/Other bucket, still shown). Adding `LOCAL_*` columns
  needs **one new line** in this function; removing `SELECTED_*`/`SELECTION_*` needs **zero** code
  change (the bucket becomes empty and simply doesn't render — confirmed by reading the render loop
  immediately below `GROUP_ORDER`).

This is a real, evidence-based **correction** to the brief's framing: a rename here does not "break
the UI silently" in the way a hardcoded-per-column UI would. The actual risk surface is one function,
one array (`GROUP_ORDER`), fully diffable in a two-line PR.

---

## 2. Target state

### 2.1 The column-shape decision: per-field columns, not a JSON blob

**Recommendation: per-field columns** (`AI_<F>`, `LOCAL_<F>`, `<F>`), not a JSONB blob holding all
fields. Argued from evidence, not preference:

1. **Every existing mechanism in this repo that touches this table is column-level, not blob-level.**
   `schema.sql` is a flat list of `alter table ... add column`. `gen-gateway-trigger-schema.py` (the
   *documented, only sanctioned way* to add a column to the new write gateway, per its own docstring)
   parses `schema.sql` with a regex that expects one `add column` statement per field — it has no
   concept of "a field living inside a JSONB column." G39 (`trigger-schema-drift-lint.py`) diffs a
   trigger's declared field set against `information_schema.columns` — same assumption. A blob would
   either bypass both gates entirely (silently reintroducing the exact class of bug G39 was built to
   catch) or require rewriting both.
2. **The UI's only relevant mechanism (`fieldGroup()`, §1.6) is a column-*name* prefix dispatcher.**
   It already does the right thing for `AI_*`/`LOCAL_*` for free. A blob would need a bespoke renderer
   (there is no existing JSONB-field UI component in this codebase to reuse — `ExtractionQueries.tsx`
   renders *query definitions*, not *extracted values*).
3. **The field set is small, closed, and named already.** Seven base/per-type scalar fields
   (`COMPANY_ID, TYPE, DOC_DATE, INVOICE_ID-shaped, DOC_TOTAL_AMOUNT, SHIPMENT_ID, PURCHASE_ID`) plus
   two BS summary scalars. This is not an open/growing schema where a blob's flexibility would pay for
   itself — it's the same seven fields `q_v3_routing` already names live in the DB (§1.3/1.4).
4. **Migration cost is asymmetric.** Per-field is `alter table add column if not exists` — additive,
   idempotent, zero-downtime, instantly reversible (an unused new column costs nothing to leave in
   place if a phase is rolled back). A JSONB blob is a **new column with a new internal shape**,
   requiring new parsing/validation code on both the n8n write side and the Python read side, and it
   cannot reuse `gen-gateway-trigger-schema.py`'s column-diffing at all — it would need a second,
   parallel drift-detection mechanism for what's *inside* the blob, which is exactly the kind of new
   bespoke heuristic this project's own operating notes says to avoid in favor of an existing
   mechanism.

Per-field wins on every axis measured. The one blob-favoring argument (fewer physical columns) does
not apply at this field count.

### 2.2 Canonical field map — what gets added, what's frozen, what's dropped

**Do not rename the existing `AI_*` columns.** They carry real, populated data today
(3,474-3,810 non-null values per field on the 6,250 real rows, §2.7) and are referenced from
`DocumentDetailPage.tsx`'s `fieldGroup()` and from the selection code in two workflows. Renaming them
buys nothing and adds a migration step with no corresponding benefit. Instead, **new `LOCAL_*` columns
mirror the existing `AI_*` names exactly** (not the differently-named bare columns they'll ultimately
feed) so the pairing stays visually and structurally obvious:

| Canonical field | `AI_*` (existing, frozen) | `LOCAL_*` (new) | Bare "VAL" column (existing, unchanged name) |
|---|---|---|---|
| Company ID | `AI_COMPANY_ID` | `LOCAL_COMPANY_ID` | `COMPANY_ID` |
| Doc type | `AI_TYPE` | `LOCAL_TYPE` | `TYPE` |
| Doc date | `AI_DOC_DATE` | `LOCAL_DOC_DATE` | `DOC_DATE` |
| Doc/invoice ID | `AI_DOC_ID` | `LOCAL_DOC_ID` | `DOC_ID` *(new canonical name — see §2.2b, owner-resolved)* |
| Total amount | `AI_DOC_AMOUNT` | `LOCAL_DOC_AMOUNT` | `TOTAL_AMOUNT` *(canonical name — see §2.2b, owner-resolved)* |
| Shipment ID | `AI_SHIPMENT_IDS` | `LOCAL_SHIPMENT_IDS` | `SHIPMENT_DOC_ID` |
| Purchase/order ID | `AI_ORDER_IDS` | `LOCAL_ORDER_IDS` | `PURCHASE_ID` |

**9 new `LOCAL_*` columns total** (7 above). All `TEXT`, matching every sibling column's type.

**§6.1 (open question) is now resolved by the owner — see §2.2b immediately below for the
`DOC_ID`/`TOTAL_AMOUNT` consolidation this table already reflects.**

### 2.2a BS per-line design — ruled by the owner: same model, no exception

**The owner's ruling, verbatim: *"it should fit, we later plan adding local also for BS so should
follow the same pattern."*** Local extraction for BS is coming, not hypothetical — the triad must be
designed to hold it now, not retrofitted later. This supersedes the earlier draft of this section,
which treated BS's line-item structure as something the owner's design "doesn't fully specify a
mechanism for." It does specify one; it just needs the triad applied at the right **grain**, not
flattened onto the wrong one.

**First, what BS actually needs is two different things, confirmed by live data — not one:**

| BS data | Live evidence | Cardinality |
|---|---|---|
| Document-level summary (as-of date, total balance) | `indoxV2ExtractBalanceSheet01.json` AI output shape: `documentDate`, `documentTotalAmount` (§1.1 row 9) — one value each, per document | **1 per document** — same cardinality as every other type's date/amount |
| Transaction lines (the aging-report rows) | `BS_EXTRACTED_LINES` (152/6,250 populated — 152 of the 154 live `BALANCE_SHEET`-typed documents, confirmed: `select count(*) from incoming_documents where "TYPE"='BALANCE_SHEET'` → 154) | **N per document** — an array, not a scalar |

(For completeness: `BS_LINE_DATE`/`BS_LINE_AMOUNT`/`BS_LINE_NOTE`/`LINKED_BS` are a **different,
adjacent** mechanism — 2,003/6,250 populated, but on *invoice/shipment* documents, not BS documents.
They record "this invoice was matched to line X of a balance-sheet report," a downstream
cross-reference/reconciliation feature that *reads* `BS_EXTRACTED_LINES` after the fact. They are not
part of BS's own extraction and are out of scope for this refactor — named here only so they aren't
confused with the columns actually being redesigned.)

**Design: apply the flat triad where the cardinality is 1 (reusing the universal columns every type
already gets), and a new child table where the cardinality is N (applying the same triad per line).**
This is not two different models bolted together — it's one model (`AI value, local value, selected
value, per field`) applied at whatever grain a given field actually has, which is what "same mental
model, nobody remembers an exception" means in practice:

- **Document-level BS summary — no new columns needed at all.** Once BS goes through the base-doc step
  like every other type (owner's brief: "the document is already indexed at the base step, so that
  information is available"), it already gets `AI_DOC_DATE`/`LOCAL_DOC_DATE`/`DOC_DATE` from the base
  lane. Its "total balance" is the same concept as an invoice's "total amount" — after the §2.2b
  consolidation there is exactly one canonical `TOTAL_AMOUNT` column, and BS's AI/local extractors
  populate `AI_DOC_AMOUNT`/`LOCAL_DOC_AMOUNT` like every other type. **Zero new document-level columns
  for BS** — this is the cleanest evidence the "same pattern" ruling is achievable, not aspirational.
- **Line items — a new child table, `bs_extracted_lines`, with the identical triad per field per
  row:**
  ```sql
  create table if not exists public.bs_extracted_lines (
    "id" bigint generated always as identity primary key,
    "document_id" TEXT not null references public.incoming_documents("ID"),
    "line_index" integer not null,
    "AI_DATE" TEXT, "LOCAL_DATE" TEXT, "DATE" TEXT,
    "AI_AMOUNT" TEXT, "LOCAL_AMOUNT" TEXT, "AMOUNT" TEXT,
    "AI_NOTE" TEXT, "LOCAL_NOTE" TEXT, "NOTE" TEXT,
    "created_at" timestamptz default now());
  create index if not exists bs_extracted_lines_doc on public.bs_extracted_lines ("document_id");
  ```
  Three fields (`DATE`, `AMOUNT`, `NOTE`), each with its own `AI_*`/`LOCAL_*`/bare triple — **exactly**
  the pattern from §2.2's table, just scoped to one row per transaction line instead of one row per
  document. This is a normalized child table, not a JSON blob, so it inherits every argument from
  §2.1 (column-level gates, UI-safe, generator-compatible) — it does not reopen the blob-vs-column
  decision, it extends the *same* decision to a one-to-many relationship, which is the standard
  relational answer to "N per document," not a special case.

**Options weighed, per the owner's request:**

| Option | Verdict | Why |
|---|---|---|
| (a) Parallel line-level table, triad per field per line | **Chosen** | Correct cardinality, reuses every existing per-field mechanism (§2.1), only 154 documents affected (2.5% of the table) so the child table stays small |
| (b) Triad at document level, lines as one structured `AI_VAL`/`LOCAL_VAL`/`VAL` JSON blob | Rejected | Reintroduces exactly the JSON-blob problem §2.1 already argued against — the whole line array would move or not move as one unit, so a selection step could not pick "this line's date from AI, that line's amount from local," which defeats the purpose of having a local side at all once it exists |
| (c) Hybrid: flat document-level scalars + separate line-item table | **This is what's chosen, described precisely** — option (a) applied only to the line items, with the document-level scalars needing **no new mechanism** because they're already covered by the universal base-lane columns. (a) and (c) are the same design; (c) is just the more precise way to state it once you notice BS's document-level fields aren't BS-specific at all. |

**Cost:** one new table (not a change to the 89-column main table), one one-time migration script
(parse each of the 152 populated `BS_EXTRACTED_LINES` JSON blobs, insert N rows into
`bs_extracted_lines` with `AI_DATE`/`AI_AMOUNT`/`AI_NOTE` populated from the parsed JSON — since BS is
AI-only today, `LOCAL_*` starts null on every backfilled row, populated only once the "later" local-BS
work the owner referenced actually lands). The legacy `BS_EXTRACTED_LINES` JSON column is deprecated
on the same reversible timeline as `SELECTED_*`/`SELECTION_*` (§3 Phase 6) — additive first, drop last,
after the new table is proven in production.

### 2.2b The two bare-column consolidations — ruled by the owner

The owner resolved §1.3's "second, unrelated-to-extraction-but-adjacent naming duplication" flag
directly: **`COMPANY_DOC_ID` and `INVOICE_ID` consolidate into a new canonical `DOC_ID`; `DOC_TOTAL_AMOUNT`
consolidates into the existing `TOTAL_AMOUNT`.** Both are simplifications toward one name per concept,
not toward the currently-more-populated column — worth stating plainly since population count alone
would have pointed the other way for the second one (see below).

**Live population, both sides, real rows only (6,250):**

| Pair | Column | Non-null | Notes |
|---|---|---|---|
| → `DOC_ID` | `COMPANY_DOC_ID` | 5,841 (93%) | The one actually written by the live per-type lane (`indoxV2ActionsShip01.json:2874-2875`, §1.1 row 5) |
| → `DOC_ID` | `INVOICE_ID` | 3,549 (57%) | Older column; not traced to a live writer in this scan's required-read set (§1.1's file list didn't include whatever writes it) |
| → `TOTAL_AMOUNT` | `DOC_TOTAL_AMOUNT` | 3,425 (55%) | The one actually written by the live per-type lane (`indoxV2ActionsShip01.json:2710-2711`, §1.1 row 8) |
| → `TOTAL_AMOUNT` | `TOTAL_AMOUNT` (pre-existing) | 152 (2.4%) | Far sparser than `DOC_TOTAL_AMOUNT` today — the owner's chosen *name* wins, not the currently-fuller *column*, so this migration is a real backfill in the majority-populated direction, not a rename of the already-bigger column |

**Both consolidations are real data migrations, not renames.** `DOC_ID` doesn't exist as a column yet
at all (it's a genuinely new name for the concept both `COMPANY_DOC_ID` and `INVOICE_ID` were
independently trying to be); `TOTAL_AMOUNT` exists but is the *emptier* of its pair, so most of the
data has to move into it, not out of it.

**Conflict handling — what happens when both sides of a pair are populated and disagree:**
Un-measured today (would need a live join comparing values, out of this pass's time budget) but the
rule to apply is unambiguous given §1.1's evidence of which column each pair's *live writer* actually
targets:
- **`DOC_ID` ← `COMPANY_DOC_ID`, always, when both are non-null and differ.** `COMPANY_DOC_ID` is the
  column the *currently-running* extraction pipeline writes (§1.1 row 5); `INVOICE_ID`'s writer was
  not identified in this scan, meaning its value — where it exists and disagrees — is more likely
  stale/legacy than `COMPANY_DOC_ID`'s. If `INVOICE_ID` is non-null and `COMPANY_DOC_ID` is null,
  fall back to `INVOICE_ID` (don't discard real data just because it's the less-trusted source).
- **`TOTAL_AMOUNT` ← `DOC_TOTAL_AMOUNT`, always, when both are non-null and differ**, for the identical
  reason — `DOC_TOTAL_AMOUNT` is the live writer's target (§1.1 row 8); `TOTAL_AMOUNT`'s 152 populated
  rows are almost certainly older/legacy given how much sparser they are. Fall back to `TOTAL_AMOUNT`
  only where `DOC_TOTAL_AMOUNT` is null.
- **Before running the real backfill, a one-time live audit is required**: `select count(*) from
  incoming_documents where "COMPANY_DOC_ID" is not null and "INVOICE_ID" is not null and
  "COMPANY_DOC_ID" <> "INVOICE_ID"` (and the `TOTAL_AMOUNT`/`DOC_TOTAL_AMOUNT` equivalent) — if that
  count is non-trivial, the "always prefer the live writer's column" rule needs a human look at a
  sample before the backfill runs unattended, since a systematic disagreement (not just noise) would
  mean one of the two columns encodes something subtly different (e.g. one includes VAT, one doesn't)
  rather than being a stale duplicate.

**Every reader, both pairs** (grepped across `apps/indox/`, filtered to code — not the historical
`storage/extraction-runs/*.json` execution-log dump, which is data, not a reader):

| Column | Readers (file, not exhaustive line-level — see grep evidence) |
|---|---|
| `COMPANY_DOC_ID` | `indoxV2Driver01.json`, `indoxDataGateway01.json`, `indoxV2ActionsShip01.json`, `indoxV2ActionsGDoc01.json`, `indoxApiSupabase01.json`, `indoxGmailLinkDownloader01.json`, `indoxDocBatchUpsert01.json`, `indoxV2Decide01.json`, `indoxGmailBSDownloader01.json`, `indoxGmailDocDownloader01.json`, `syncV3SourcesTest01.json`, `indoxV2QueryShipmentId01.json`, `apps/indox/blueprint/fixtures/{settings,schema.sql,fixture_INVOICE}.json`, `DocumentDetailPage.tsx:22` (`IDENTITY_FIELDS` set — same safe prefix-categorizer pattern as §1.6, one-line update) |
| `INVOICE_ID` | `indoxV2Driver01.json`, `indoxDataGateway01.json`, `indoxV2ActionsShip01.json`, `indoxV2ActionsGDoc01.json`, `indoxV2QueryInvoiceId01.json`, `indoxApiSupabase01.json`, `indoxGmailLinkDownloader01.json`, `indoxDocBatchUpsert01.json`, `indoxGmailBSDownloader01.json`, `indoxGmailDocDownloader01.json`, `extraction.py` (the shadow-harness's own `TYPES["invoice"]["scored"]` field-name list, §3 Phase 3 — **must be updated to `DOC_ID` alongside the rename or the harness silently starts comparing the wrong column**), fixtures |
| `DOC_TOTAL_AMOUNT` | `indoxV2Driver01.json`, `indoxDataGateway01.json`, `indoxV2ActionsShip01.json`, `indoxV2ActionsGDoc01.json`, `indoxV2QueryTotalAmt01.json`, `indoxApiSupabase01.json`, `indoxDocBatchUpsert01.json`, `DocumentBrowserPage.tsx:20` (`DEFAULT_VISIBLE` array — a real, live column-name string in the browsable-columns list, **must** be updated to `TOTAL_AMOUNT` or the default view silently stops showing this column, since `cfg.columns` is matched by exact name against this array) |
| `TOTAL_AMOUNT` | `indoxV2Driver01.json`, `indoxV2ActionsGlobal01.json`, `indoxDataGateway01.json`, `indoxV2ActionsShip01.json`, `indoxV2ActionsGDoc01.json`, `indoxV2ActionsBS01.json`, `indoxApiSupabase01.json`, `indoxDocBatchUpsert01.json`, `platform-base/n8n/extensions/bina-solutions-nodes/gsheet-table-api.md:41` — **a third system**: a legacy Google-Sheets-backed table-API extension's hardcoded column allowlist, outside `apps/indox/` entirely, that must also be updated or it silently rejects/ignores writes to the renamed field for whatever still routes through it |

**`indoxDocBatchUpsert01`/`indoxDataGateway01` — the `executeWorkflowTrigger` trap, again.** Both
`COMPANY_DOC_ID`/`INVOICE_ID`/`DOC_TOTAL_AMOUNT`/`TOTAL_AMOUNT` are currently declared in both
gateways' trigger schemas (confirmed by grep). Adding `DOC_ID` and dropping the old names must go
through the exact same Phase-1-style additive sequencing as everything else in this plan (§4.1) —
this is not a special case, it is the same trap applying to two more columns.

**Migration sequencing (mirrors §3's phases exactly, run in parallel with them, not as a separate
project):**
1. **Additive:** add `DOC_ID` (new) to `schema.sql`; `TOTAL_AMOUNT` already exists, no schema change
   needed for it. Regenerate both gateway trigger schemas (§3 Phase 1's mechanism).
2. **Dual-write:** every writer of `COMPANY_DOC_ID`/`INVOICE_ID` also writes `DOC_ID` (preferring
   `COMPANY_DOC_ID`'s value per the conflict rule above); every writer of `DOC_TOTAL_AMOUNT` also
   writes `TOTAL_AMOUNT`. Old columns keep being written too — no reader breaks yet.
3. **One-time backfill** for historical rows written before dual-write existed: `update
   incoming_documents set "DOC_ID" = coalesce("COMPANY_DOC_ID", "INVOICE_ID") where "DOC_ID" is null`
   and `update incoming_documents set "TOTAL_AMOUNT" = coalesce("DOC_TOTAL_AMOUNT", "TOTAL_AMOUNT")
   where "DOC_TOTAL_AMOUNT" is not null` (both paginated per §4.3's `PGRST_DB_MAX_ROWS=1000` caveat —
   6,250 rows exceeds it).
4. **Switch every reader** in the table above from the old name to the new one, one file at a time —
   `extraction.py`'s field-name list and `DocumentBrowserPage.tsx`'s `DEFAULT_VISIBLE` array are the
   two call-outs above that are easy to miss because they're string literals, not schema
   declarations, so no gate catches a stale one automatically.
5. **Drop `COMPANY_DOC_ID`, `INVOICE_ID`, `DOC_TOTAL_AMOUNT`** only after step 4 is confirmed complete
   and, per the standard rule in this plan, after a `pg_dump` snapshot and a production observation
   window — same reversibility posture as §3 Phase 6.

**Relation to `SHORT_DOC_ID` (§4.2) — related but not the same problem, per the owner's instruction
not to conflate them.** `SHORT_DOC_ID` (four divergent formulas, tracked separately under G43) is
computed as *the last five characters of a document identifier* — today, of `COMPANY_DOC_ID` in the
canonical formula. Once `DOC_ID` exists as the single consolidated identifier, `SHORT_DOC_ID`'s
formula should derive from `DOC_ID`, not from whichever of `COMPANY_DOC_ID`/`INVOICE_ID` a given
divergent implementation happens to read — **this doesn't fix the four-formula problem, but it does
reduce it to "four formulas reading the same well-defined source column" instead of "four formulas
possibly reading different source columns too,"** which is one fewer axis of divergence.
`SHORT_DOC_ID`'s deeper fix (one formula, in `indoxIdentity01`, per `ai/context/INDOX-UNIFIED-N8N-SPEC.md`
§2) stays exactly as tracked — this refactor doesn't take it on, but a canonical `DOC_ID` is a genuine
prerequisite for that fix to land cleanly, and the owner's framing ("`DOC_ID` may make `SHORT_DOC_ID`
unnecessary as anything but a display label") is directionally right: with one trustworthy `DOC_ID`
column, `SHORT_DOC_ID` stops being load-bearing for identity/dedup (that job moves to `DOC_ID` +
`COMPANY_ID`, or whatever key `indoxIdentity01` lands on) and survives only as the shortened label the
UI already shows — which is what `ai/context/INDOX-UNIFIED-N8N-SPEC.md:60-63` independently already
concludes for the separate identity-consolidation effort.

### 2.3 The selection step

**Collapse three divergent implementations into one shared sub-workflow.** Today's
`Selection & Scoring Logic1` is duplicated verbatim between `indoxV2ActionsGDoc01.json:673-684` and
`indoxV2ActionsShip01.json`, and a **third**, independently-scored variant exists at
`indoxV2Driver01.json:1266-1276` (dead in production, live in test fixtures — a genuine landmine if
anyone ever wires it in expecting parity). Target: one sub-workflow, e.g. `indoxV2Select01`, called
from both the base-doc step and the per-type step. This is not a new principle — it's the platform's
own already-stated rule (`ai/context/INDOX-UNIFIED-N8N-SPEC.md` §6: "no branching business logic in a
workflow — it belongs in a shared sub-workflow with one copy").

It reads `AI_<F>`/`LOCAL_<F>` for each field in scope for that step, applies the existing scoring logic
(kept as-is — no evidence today's 0/50/100 mismatch scoring is wrong, only that it's copy-pasted), and
writes the winner into the **existing bare column** — the same column many of these fields already
sometimes get written to today, just now with one authoritative writer instead of an early
local-lane write plus a later, separate `SELECTED_*` write.

### 2.4 `SELECTED_*`/`SELECTION_*` disposition — and one respectful pushback

**`SELECTED_*` (7 columns): DELETE, per the owner's rule, no reservations.** Every one of them is
superseded 1:1 by writing straight into the bare canonical column (§2.2) — this isn't even a new write
path, since several of these bare columns are *already* written earlier in the pipeline today; this
consolidates who owns the final write, it doesn't invent a new destination.

**`SELECTION_*` (5 columns) — the owner's rule says delete all of these too. I recommend keeping one,
and want that flagged rather than silently overridden or silently complied with.** Reasoning: four of
the five (`SELECTION_SOURCE`, `SELECTION_CERTAINTY`'s *raw* winner, `SELECTION_COMPLETED`,
`SELECTION_VALUES_HASH`) become **recoverable for free** once `AI_<F>`/`LOCAL_<F>`/`<F>` all exist side
by side — a consumer can always tell which source won by comparing `<F>` to `AI_<F>` and `LOCAL_<F>`
directly, something today's design *couldn't* do (today's local write overwrites the bare column, so
the pre-selection local value is gone by the time you'd want to audit it). But the **agreement score
itself** — the specific 0/50/100 mismatch computation, not just which side won — is not
re-derivable post-hoc without re-running the comparison logic. Dropping it loses a genuine debugging
signal with no free replacement. **Recommendation: keep exactly one, `SELECTION_DEBUG` (jsonb,
renamed from `SELECTION_SCORE_DEBUG`), written once per document by the new shared selection
sub-workflow; drop the other four (`SELECTION_CERTAINTY`, `SELECTION_SOURCE`, `SELECTION_COMPLETED`,
`SELECTION_VALUES_HASH`).** If the owner wants the literal "all `SELECTION_*` deleted" honored exactly,
the fallback is dropping all five and relying on n8n execution history / GlitchTip for post-hoc
debugging instead — flagging the tradeoff, not deciding it unilaterally.

### 2.5 Settings-driven configuration (folds in the coordinator's toggle requirement)

Reuse the existing mechanism exactly as-is — this needed no new design, just new entries:

- **`_EDITABLE_SETTINGS_KEYS`** (`apps/indox/app/incoming_documents/api/__init__.py:195-206`) is a
  5-entry frozenset today (`activePrioritySync`, `indox_execution_mode`, `max_actions_per_doc`,
  `OldDocumentMonthsBack`, `default-upload-folder`). Add:
  - `extraction_ai_enabled` — `"true"`/`"false"`; `EditableSetting`/`isBoolish`
    (`SettingsPage.tsx:22-24, 39-122`) renders any boolish-valued editable key as a toggle switch
    automatically, **zero new frontend code**, confirmed by tracing `editable_keys` from the API
    response straight into the render filter (`SettingsPage.tsx:421-423`).
  - `extraction_model` — free text, e.g. `"models/gemini-3.1-pro-preview"`, replacing the **currently
    hardcoded** model name at `indoxV2ExtractInvoiceGemini01.json:861-863,890-892` and
    `indoxV2ExtractBalanceSheet01.json:1009,1039,1267` (three separate hardcoded literals across two
    files today — another small duplication this closes).
  - `extraction_local_enabled` — `"true"`/`"false"`, independent kill switch for the local side
    (mirrors `extraction_ai_enabled` above; useful during Phase 4/5 to isolate which side is
    misbehaving without a redeploy).
  - `extraction_selection_confidence_threshold` — numeric text (e.g. `"50"`), read by the new
    `indoxV2Select01` sub-workflow (§2.3) in place of today's hardcoded 0/50/100 scoring thresholds
    inside the duplicated `Selection & Scoring Logic1` code — makes the selection cutoff tunable
    without a workflow edit.

  **Prerequisite, satisfied today (§0.5) but worth stating plainly:** every one of these toggles is
  read by an n8n workflow through `indoxSettings01`'s 20-minute KV cache
  (`n8n-nodes-kv-storage`, `ttl:1200`). Without a live cache-invalidation path, flipping a toggle in
  the UI silently takes up to 20 minutes to take effect — indistinguishable from "the toggle doesn't
  work" to whoever just flipped it. Confirmed live on this environment (§0.5); **must be re-confirmed
  on any other environment** (staging/production) before shipping these new toggles there, using the
  same DB check: `select active, nodes::text like '%Invalidate Cache Webhook%' from workflow_entity
  where id='indoxSettings01';` against that environment's own n8n Postgres.
- **`q_v3_*` rows already have a UI** — `ExtractionQueries.tsx` (`apps/indox/app/webapp/src/components/`)
  renders every `q_v3_*` row as a pipeline (primary step + ordered fallbacks) with a validated JSON
  editor, `PUT /extraction/queries/<key>`, live-reload — no n8n redeploy needed for a query edit
  (confirmed: its own on-page callout text says exactly this — "לוגיקת החילוץ כולה — קריאת apitools
  אחת לכל ערך" / "the entire extraction logic — one apitools call per value"). **This is already the
  UI for editing the single-source-of-truth local query definitions the owner's design calls for** —
  nothing new to build here, just wire the workflows that read it into the live pipeline.
- **Cache invalidation is live on this environment** (§0.5) — a settings edit takes effect on the very
  next extraction run, not up to 20 minutes later. No caveat needed for the new keys.

### 2.6 UI impact — confirmed minimal (§1.6)

- `DocumentDetailPage.tsx:26-37` (`fieldGroup()`): add one line, `if (n.startsWith('LOCAL_')) return
  'זיהוי AI';` (or a new group, owner's call). `GROUP_ORDER` array: no change needed (unmatched-prefix
  fields already fall through safely to `'אחר'`).
- `DocumentBrowserPage.tsx`, `BinaTable.tsx`: **no change needed** — confirmed zero references to any
  of these columns.

### 2.7 Live population — what's actually safe to touch

All counts below are from the **local dev stack**, `public.incoming_documents`, split by the
`SYNC_NAME='loadtest-50k' OR CONNECTION='loadtest-50k' OR ID LIKE 'lt50k_%'` marker
(`scripts/ops/loadtest-50k-cleanup.sql:3`) — a NULL-safe predicate (the naive `NOT (...)` form silently
undercounts on NULL columns; verified with a corrected `coalesce(...) <> ...` version):

| Segment | Rows |
|---|---|
| Total (re-checked at write time) | **6,250** |
| `loadtest-50k` synthetic | **0 — already deleted** (confirmed live: `SYNC_NAME='loadtest-50k' OR CONNECTION='loadtest-50k' OR ID LIKE 'lt50k_%'` now matches zero rows) |
| Real/seed | 6,250 (== total, now that synthetic rows are gone) |

The per-column counts below were computed against the real/seed-only predicate from the start (to
isolate real data even while the 50,000 synthetic rows were still present), so they are **unaffected**
by the subsequent deletion — re-querying after the deletion returns identical numbers, confirmed by
spot-check (`select count(*) from incoming_documents` now returns 6,250 with zero loadtest rows,
matching the real/seed segment size used throughout this section).

| Column | Non-null / 6,250 |
|---|---|
| `AI_COMPANY_ID` | 3,521 |
| `AI_TYPE` | 3,531 |
| `AI_DOC_ID` | 3,810 |
| `AI_DOC_DATE` | 3,535 |
| `AI_DOC_AMOUNT` | 3,474 |
| `AI_SHIPMENT_IDS` | 3,536 |
| `AI_ORDER_IDS` | 2,823 |
| `AI_EXTRACTION_COMPLETED` | 3,564 |
| `SELECTED_COMPANY_ID` | 5,469 |
| `SELECTED_DOC_ID` | 5,365 |
| `SELECTED_DOC_TIPE` (sic — live typo in the column name) | 435 |
| `SELECTED_DOC_AMOUNT` | 3,631 |
| `SELECTED_DOC_DATE` | 5,465 |
| `SELECTED_DOC_SHIPMENT_ID` | 1,161 |
| `SELECTED_DOC_ORDER_ID` | 2,096 |
| `SELECTION_CERTAINTY` | 5,273 |
| `SELECTION_SOURCE` | 5,520 |
| `SELECTION_COMPLETED` | 5,472 |
| `SELECTION_SCORE_DEBUG` | 5,518 |
| `SELECTION_VALUES_HASH` | 5,516 |
| `EX_INVOICE_ID` | **0** |
| `EX_IS_BS` | **0** |
| `EX_IS_BS_COMPLETED` | **0** |
| `FIGURE_TYPE_COMPLETED` | 1,968 |
| `FIGURE_COMPANY_COMPLETED` | 1,540 |
| `NEXT_RETRY_AT` | **0** (confirms the historical bug is still live even on this stack) |
| `RETRY_COUNT` | 6,250 (default `0`, not real signal) |
| `THUMBNAIL` | 17 |
| `CONNECTION` | 5 |

**Conclusions that follow directly:**
- **`SELECTED_*`/`SELECTION_*` are heavily populated (43%-88% of real rows) — none of them are safe to
  drop without migrating.** This directly contradicts an implicit "just delete them" reading of the
  brief; the brief itself anticipated this ("Dropping a populated column is irreversible") and this is
  the number that proves it. Migration must backfill any bare canonical column that's currently null
  but has a non-null `SELECTED_*` counterpart, **before** dropping the `SELECTED_*` column (§3, Phase
  3).
- **`EX_*` (3 columns) are dead on real data — 0 of 6,250.** These are safe to drop with a simple
  `DROP COLUMN`, no migration/backfill needed. (Not touched by this refactor's core design, but a
  free, evidence-backed cleanup opportunity worth doing in the same PR since it's zero-risk.)
- **`FIGURE_*` (2 columns) are partial (25%/31%)** — these are *completion flags* for the local
  base-lane steps, not values; they stay meaningful under the new design (the consolidated base-doc
  step still needs a completion flag) and are out of scope for deletion.

### 2.8 `FROM_OFFICE` → `FROM_WAREHOUSE` — ruled by the owner, folded into this refactor

**Owner's ruling, verbatim:** *"make sure any reference to FROM_OFFICE becomes now FROM_WHEARHOUSE —
it's an old mistake we did calling warehouse office and it's confusing (cause those docs (usually
shipments, sometimes invoices) really come from the warehouse where goods are received, and not from
office)."*

**Spelling note, flagged prominently per instruction so the owner can overrule it:** the owner wrote
"WHEARHOUSE," which is a typo for "WAREHOUSE." **This plan uses the correct spelling, `FROM_WAREHOUSE`**,
on the reasoning that the entire point of this rename is fixing a wrong, confusing name — shipping a
new misspelled identifier would plant tomorrow's cleanup task on day one. This is the owner's schema
and the owner's call to reverse; noted here explicitly rather than silently corrected.

**Every occurrence, found first, before any change (per instruction):**

Grepped `FROM_OFFICE` across `apps/`, `platform-base/`, `ai/`, fixtures, and this document's own
earlier text. Filtered to code/config (excluding the historical `storage/extraction-runs/*.json`
execution-log dump and `storage/incoming_documents/snapshots/*.json`, which are data captures, not
readers):

| File | What it does with `FROM_OFFICE`/`FROM_OFFICE_CHECK` |
|---|---|
| `apps/indox/blueprint/fixtures/schema.sql:63,65` | Column definitions (`TEXT`, both) |
| `apps/indox/blueprint/n8n/indoxV2Driver01.json:471,1373,2690-2700,3646-3656,4347-4357,5064-5074` | Reads `FROM_OFFICE` (`!!$('Action: Query Shipment ID').item.json.FROM_OFFICE`), writes `FROM_OFFICE_CHECK` (`$json.FROM_OFFICE_CHECK ? 'Y' : ''`), and declares both in **5 separate** node schemas across this one file |
| `apps/indox/blueprint/n8n/indoxV2ActionsShip01.json:435,2339,2960-2988,4268,4561` / `indoxV2ActionsGDoc01.json` (identical lines) | Writes `FROM_OFFICE` (`$json.FROM_OFFICE == true ? 'Y' : ""`), a dedicated node named `"Build: Call 'Incoming Document Batch Update' - FROM_OFFICE"`, and an `ACTION_LOG` entry that literally embeds the string `', FROM_OFFICE, '` |
| `apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json:11,191,325,330,483-...,1428+ (×18 occurrences)` | Declares both fields in its trigger schema (correctly — not a silent-drop case) and in ~18 duplicated per-branch mapping nodes throughout the file |
| `apps/indox/blueprint/n8n/indoxDataGateway01.json:79,82,290` | Declares both fields in the new gateway's schema too |
| `apps/indox/blueprint/n8n/SyncProcGDoc0001.json:914-924`, `SyncProcBS000001.json:472-482`, `indoxGmailLinkDownloader01.json:697-707`, `indoxGmailDocDownloader01.json:1190-1200`, `indoxGmailBSDownloader01.json:689-699` | Field declarations, same pattern, across every sync-intake workflow |
| `apps/indox/blueprint/fixtures/types/fixture_SHIPMENT.json:251-252`, `fixture_INVOICE.json:331-332`, `apps/indox/blueprint/fixtures/fixture_INVOICE.json:874-875` | State-machine fixture guard: `"guard": "!isBlank(COMPANY_DOC_ID) && isBlank(FROM_OFFICE_CHECK)", "sets": "FROM_OFFICE_CHECK"` |
| `apps/indox/app/webapp/src/pages/DocumentDetailPage.tsx:24` | `SOURCE_FIELDS` categorizer set (same safe prefix-style pattern as §1.6 — but this one is an **exact name**, not a prefix, so it needs a literal string update, not a prefix rule change) |
| `apps/indox/app/webapp/src/pages/DashboardPage.tsx:20` | **User-facing Hebrew label**: `FROM_OFFICE: 'מהמשרד'` ("from the office") — this is the one place end users actually see the wrong word; must become `'מהמחסן'` ("from the warehouse") to match the rename's own stated purpose, not just the column name |
| `apps/indox/storage/incoming_documents/repos.json:197,204` | Repo-registry column metadata (`"name": "FROM_OFFICE"` / `"FROM_OFFICE_CHECK"`) |
| `ai/context/indox-state-machine-v2.md:110` | Documents the `check_from_office` state-machine action: *"WH settings → `indoxV2SearchWarehouse01` warehouse search → writer(FROM_OFFICE_CHECK)"* — **confirms "warehouse" is already the internal concept name**; the underlying search workflow is already called `indoxV2SearchWarehouse01`, not `indoxV2SearchOffice01`. This corroborates the owner's framing directly: the code already knows this is about a warehouse, only the column/action names lag. |
| `ai/context/indox-experience-design.md:119`, `ai/context/hacohen-legacy-migration-spec.md:30` | Column referenced in architecture docs |
| `ai/obsidian/Projects/deployment-hacohen/High-Load Supervised Run 2026-06-23.md` | A **real production incident** about this exact column: `FROM_OFFICE_CHECK` writes were silently not persisting (root-caused to an `alwaysOutputData`-masked empty return — a different failure shape than the `executeWorkflowTrigger` schema-drop bug, but the same *category* of "write silently vanished" defect this whole plan keeps finding). Cited here as evidence this column is operationally fragile, not just semantically misnamed — worth extra care during the rename. |
| `platform-base/n8n/extensions/bina-solutions-nodes/gsheet-table-api.md:42` | The same legacy Google-Sheets-backed table-API allowlist flagged in §2.2b for `TOTAL_AMOUNT` — a **third** system with `FROM_OFFICE`/`FROM_OFFICE_CHECK` hardcoded, outside `apps/indox/` |

Also found, and **not** the same live column** — flagging so it isn't conflated during the rename:
`ai/context/indox-per-type-fixture-architecture.md:183,295` references `FROM_OFFICE_CHECK_COMPLETED`
(with a `_COMPLETED` suffix). This name does **not** appear in the live `information_schema.columns`
dump (§2.7's full-ledger query, §8) — it looks like either stale documentation or an aspirational name
from a doc that predates the actual implementation. Don't rename a column that doesn't exist; flag the
doc as inconsistent with live schema instead (out of scope to fix here).

**Live population count** (real rows, 6,250 — confirms this is a data migration, not cosmetic):

| Column | Non-null | Value distribution |
|---|---|---|
| `FROM_OFFICE` | 5,697 (91%) | `false`: 3,856 · `true`: 1,841 · empty string: 553 |
| `FROM_OFFICE_CHECK` | 5,718 (91%) | `true`: 5,697 · empty string: 532 · `false`: 21 |

**91% populated — this is one of the more heavily-used columns in the whole table, confirmed by its
own state-machine action (`check_from_office`) gating document progress (per the fixture guards
above). `FROM_OFFICE_CHECK` is effectively a completion flag in practice** (`true` on 5,697 of 5,718
non-empty rows, `false` only 21 times) **despite not carrying the `_COMPLETED` suffix every other
completion flag in this table uses** — worth folding that naming inconsistency into the same rename
PR since it's directly adjacent (`FROM_OFFICE_CHECK` → `FROM_WAREHOUSE_CHECK`, still not
`_COMPLETED`-suffixed, preserving the existing name shape exactly — not proposing a second, unrelated
rename here, just noting the observation for the owner's awareness).

**Meaning, preserved in a comment at the column definition** (per instruction — this sentence is why
the rename exists, and without it the next person re-derives the same confusion):
```sql
-- FROM_WAREHOUSE / FROM_WAREHOUSE_CHECK (renamed 2026-08, was FROM_OFFICE/FROM_OFFICE_CHECK — the old
-- name was a mistake: these documents (usually shipments, sometimes invoices) come from the WAREHOUSE
-- where goods are physically received, never from an office. See ai/context/EXTRACTION-REFACTOR-PLAN.md §2.8.
alter table public.incoming_documents add column if not exists "FROM_WAREHOUSE" TEXT;
alter table public.incoming_documents add column if not exists "FROM_WAREHOUSE_CHECK" TEXT;
```

**The `executeWorkflowTrigger` trap, once more, named because this is exactly the shape of mistake the
owner explicitly warned against here**: both `indoxDocBatchUpsert01.json` and `indoxDataGateway01.json`
currently declare `FROM_OFFICE`/`FROM_OFFICE_CHECK` in their trigger schemas (§ table above). A rename
that updates the table and the ~10 writer workflows but forgets either trigger schema would have every
writer *believe* it succeeded (n8n reports no error) while the value is silently dropped before the
upsert code runs — indistinguishable from the live system today until someone notices
`FROM_WAREHOUSE_CHECK` stuck at 0% populated, weeks later, exactly like `NEXT_RETRY_AT`. Both trigger
schemas **must** be regenerated/hand-edited in the same commit as the table rename, never a commit
apart.

**Safe sequencing (dual-write, not a single rename) — mirrors §3's phases and §2.2b's consolidation
sequencing exactly, because it is the same class of problem:**
1. **Additive:** add `FROM_WAREHOUSE`/`FROM_WAREHOUSE_CHECK` to `schema.sql` (with the comment above).
   Regenerate `indoxDataGateway01`'s trigger schema; hand-add both fields to
   `indoxDocBatchUpsert01.json`'s `jsonExample` (§4.1's two-gateway wrinkle applies here too).
2. **Dual-write:** every one of the ~10 writer workflows in the table above writes both the old and
   new column names for one deployment cycle. The `"Build: Call 'Incoming Document Batch Update' -
   FROM_OFFICE"` node (and its `ACTION_LOG` string embedding `', FROM_OFFICE, '`) gets a matching
   `FROM_WAREHOUSE`-named twin rather than an in-place edit, so a mid-deploy state (some workflows
   updated, some not) never drops data either direction.
3. **One-time backfill:** `update incoming_documents set "FROM_WAREHOUSE" = "FROM_OFFICE",
   "FROM_WAREHOUSE_CHECK" = "FROM_OFFICE_CHECK" where "FROM_WAREHOUSE" is null` (paginated, §4.3).
4. **Switch every reader**: `indoxV2Driver01.json`'s 5 read/write sites, the fixture guards (2 files),
   `DocumentDetailPage.tsx:24`'s `SOURCE_FIELDS` set, and — the one users actually see —
   `DashboardPage.tsx:20`'s Hebrew label, from `'מהמשרד'` to `'מהמחסן'`. Also update
   `platform-base/n8n/extensions/bina-solutions-nodes/gsheet-table-api.md`'s allowlist (the third
   system, same as §2.2b).
5. **Drop `FROM_OFFICE`/`FROM_OFFICE_CHECK`** only after step 4 is confirmed and a production
   observation window has passed — standard reversibility posture, same as every other drop in this
   plan. Given the documented history of this exact column silently failing to persist
   (`High-Load Supervised Run 2026-06-23.md`), this is a column worth an especially long observation
   window before the old names are removed.

---

## 3. The safe migration path

Six phases. Each is independently shippable, independently verifiable, independently reversible. No
phase requires the pipeline to stop processing documents.

### Phase 0 — Land the in-flight fixes first (prerequisite, not really "this" refactor)

- Commit the uncommitted `indoxDocBatchUpsert01.json` schema fix (§0.4: `THUMBNAIL`,
  `THUMBNAIL_COMPLETED`, `CONNECTION`, `RETRY_COUNT`, `NEXT_RETRY_AT` already added on disk, not in
  git).
- Commit the uncommitted `indoxSettings01.json` cache-invalidation webhook (§0.5: live on this
  environment, not in git).
- **Why first:** every later phase adds MORE fields to the same trigger schema. Doing that on top of
  an uncommitted base risks losing both the old fix and the new one to the same `git reset`/stale
  checkout failure mode this whole gate (G39) exists to prevent.
- **Verify:** `git status --short` clean on both files after commit; `python3
  scripts/refactor/trigger-schema-drift-lint.py` passes (gate G39).
- **Rollback:** revert the commit — zero interaction with running data, these are blueprint files.

### Phase 1 — Additive schema only, no behavior change

- Add the 7 `LOCAL_*` columns (§2.2) + `SELECTION_DEBUG` (or the 5 originals if the owner overrides
  §2.4's pushback) to `apps/indox/blueprint/fixtures/schema.sql` as `alter table ... add column if not
  exists` statements — the established idiom, confirmed idempotent by every existing line in that
  file.
- Run `python3 scripts/refactor/gen-gateway-trigger-schema.py --apply` to regenerate
  `indoxDataGateway01.json`'s trigger schema + its `KNOWN_FIELDS` runtime allow-list from the same
  parsed column list (belt-and-suspenders, per that script's own docstring).
- **Manually** add the same fields to `indoxDocBatchUpsert01.json`'s `jsonExample` (the generator only
  targets `indoxDataGateway01` — the still-primary write path for extraction today per Agent B's
  trace; see §4.1's note on the two-gateway situation).
- Nothing reads or writes these columns yet. No workflow logic changes.
- **Verify:** `python3 scripts/refactor/trigger-schema-drift-lint.py` (G39) green for both gateway
  files; `bbox n8n indox push`; confirm via `information_schema.columns` that all new columns exist
  with `count(col)=0` (freshly added, nothing writes them yet).
- **Rollback:** `alter table ... drop column if exists` for each new column — trivially reversible,
  nothing depends on them yet.

### Phase 2 — Wire the base-doc step: local + AI together, writing to `AI_*`/`LOCAL_*` only

- Extend `indoxV2FigureCompanyId01`/`indoxV2FigureDocType01` (or fold them into one new "base-doc
  extractor" workflow, owner's call on granularity) to also write `LOCAL_COMPANY_ID`/`LOCAL_TYPE`/
  `LOCAL_DOC_DATE` — **in addition to**, not instead of, whatever they write today. The bare
  `COMPANY_ID`/`TYPE` writes stay exactly as-is in this phase — nothing downstream changes behavior
  yet.
- Switch the local query source from each workflow's hardcoded keyword `Set`/`Code` node to a read of
  `settings.q_v3_company`/`q_v3_type`/`q_v3_date_base` (already live, §1.3/1.4) — this is the "AI maps
  the local extraction as its prompt" prerequisite: before AI can be told "find this," the local
  definition needs to be the one place the field is defined, not a third parallel hardcoded copy.
- Do **not** touch the AI prompt yet — Phase 4 handles prompt-from-query generation, once local
  writes are proven correct in isolation (Phase 3's shadow compare).
- **Verify:** for a sample of real documents, `LOCAL_COMPANY_ID`/`LOCAL_TYPE`/`LOCAL_DOC_DATE` should
  equal the bare `COMPANY_ID`/`TYPE`/`DOC_DATE` values already on the row (same query logic, now
  sourced from settings instead of hardcoded — should be a no-op in output, only in provenance).
  Any mismatch here is a bug in the settings-sourcing change, not a real extraction regression, and
  must be fixed before Phase 3.
- **Rollback:** stop writing `LOCAL_*` (revert the workflow diff) — the new columns sit empty, nothing
  else depended on them.

### Phase 3 — Shadow/compare phase (THE gate before switching anything over)

**This reuses existing, already-built infrastructure — it is not new tooling.**
`apps/indox/app/incoming_documents/extraction.py` is a dataset-based extraction runner + scorer,
already wired to the live `JQExV3` webhooks (`jqexv3-run-base/invoice/shipment/bs`), already scoring
against a human-verified ground-truth dataset (`corrected_truth.json`) with locale-robust comparators
for amounts/dates/IDs (`extraction.py:184-232`). **Gap: it only exercises the local (`JQExV3`) side
today — it has zero AI/Gemini invocation.** Extend it, don't replace it:

1. Add an AI-side run mode: call the existing `invoice_extractor`/`bs_ex_2_dev` webhooks against the
   same dataset documents, score their output with the **same** `_score()` comparators already in
   `extraction.py:215-231` (locale-robust amount/date parsing, last-5-digits ID matching) — this
   guarantees the AI and local sides are graded by an identical, already-validated rubric, not two
   different ones invented separately.
2. Run both sides against the full dataset and produce a 3-way table per document per field: AI
   result / local result / ground truth — this is the direct evidence for "does the new path produce
   the same values as the old on the same documents," and it's stronger than old-vs-new since it also
   grades both against **truth**, not just against each other.
3. **Gate:** do not proceed to Phase 4 until local-extraction accuracy from the *wired-in* path
   matches the already-measured `JQExV3` accuracy on the same dataset (the harness already reports
   this number per field, per doc type — it's a diff of two runs of the same tool, not a new metric).
4. Run this in **shadow mode** in production too: for a sample of real (non-loadtest) documents
   flowing through the live pipeline, write `LOCAL_*` values (Phase 2) alongside today's still-active
   legacy write path, without switching selection to prefer them, and compare offline. No user-facing
   behavior changes in this phase.
- **Verify:** the harness's own scored-accuracy report, before/after, per field, per doc type — already
  built, already has ground truth, already has the comparators. The only new work is pointing it at
  the newly-wired-in local step instead of (only) the standalone `JQExV3` webhooks, plus the new
  AI-side run mode.
- **Rollback:** this phase makes no write-path changes at all — it's pure observation. Nothing to roll
  back.

### Phase 4 — Wire per-type extraction the same way; AI prompt generated from the local query

- Same additive pattern as Phase 2, applied to the 5 `Query*` workflows: write `LOCAL_DOC_ID`,
  `LOCAL_DOC_AMOUNT`, `LOCAL_SHIPMENT_IDS`, `LOCAL_ORDER_IDS` in addition to today's bare-column
  writes, sourced from `settings.q_v3_invoice_id`/`amount_invoice`/`linked_shipment`/`linked_order`
  (already live).
- **"AI maps the local extraction as its prompt"** — concretely: generate each field's AI prompt
  fragment from its `q_v3_*` `action_value` list (the same Hebrew anchor phrases), rather than hand
  duplicating them in the Gemini `CONFIG` node's prompt text. This closes the duplication in §1.3 at
  the source: one list of anchor phrases per field, in settings, read by both the local query and the
  prompt-builder step.
- Consolidate the per-type local calls using the `documentDraw` load-once/iterate-queries pattern
  (§1.5, §5) — either by pointing `JQExV3*`'s `Query apitools` node at `/documentDraw` with all of a
  category's fields in one `queries[]` array instead of fanning out to N separate
  `/documentJsonQuery` calls, or by adding a lightweight `/documentJsonQueryBatch` endpoint to apitools
  that does the same iterate-without-draw (cheaper than reusing `/documentDraw`, which also renders an
  image nobody needs here). Either is a small, contained apitools change — not core to the migration's
  data-safety, sequence it whenever convenient after Phase 3's accuracy gate passes.
- Repeat Phase 3's shadow comparison for the per-type fields before proceeding.
- **Verify:** same harness, per-type fields this time.
- **Rollback:** identical to Phase 2 — stop the `LOCAL_*` writes, nothing downstream depends on them
  yet.

### Phase 5 — Cut over: one shared selection sub-workflow writes the bare columns

- Build `indoxV2Select01` (§2.3), replacing the two duplicated `Selection & Scoring Logic1` copies and
  retiring the third dead copy in `indoxV2Driver01`.
- Base-doc step and per-type step each call it once, after their own `AI_*`/`LOCAL_*` writes complete.
- It writes the bare canonical columns (`COMPANY_ID`, `TYPE`, `DOC_DATE`, etc.) — **this is the actual
  behavior cutover**; everything before this phase was purely additive.
- **Data-safety for existing `SELECTED_*` history:** before dropping those columns, run a one-time
  backfill: for every real row where a bare canonical column is null/stale but its `SELECTED_*`
  counterpart is non-null, `UPDATE` the bare column from `SELECTED_*`. This preserves the 43-88%
  already-computed selections (§2.7) instead of discarding them and forcing every historical row
  through re-extraction.
- **Verify:** re-run Phase 3's harness against the *actual* pipeline output (not shadow) for a sample
  of real documents pre/post cutover — values should match the shadow-phase predictions from Phase 3/4
  almost exactly (any drift here, not caught in shadow mode, is the signal something about the live
  environment differs from the harness's dataset — investigate before wider rollout).
- **Staged rollout, not big-bang:** gate the cutover behind the new `extraction_ai_enabled`-style
  settings toggle if useful for a fast kill switch, or simply merge the workflow change and watch the
  next N real documents (5-20/hour sustained rate, well within a single business day) before touching
  the loadtest-50k backfill or any bulk reprocessing.
- **Rollback:** revert the `indoxV2Select01` wiring — base/per-type steps fall back to not calling it,
  bare columns stop getting written by the new path (the `LOCAL_*`/`AI_*` writes from Phases 2/4 keep
  running harmlessly). Because Phase 1-4 never removed the old write paths, this is a clean revert, not
  a data-loss event.

### Phase 6 — Drop `SELECTED_*`/`SELECTION_*` (and the dead `EX_*` columns)

- Only after Phase 5 has run in production long enough to confirm the bare columns are the trusted
  final value (owner's call on duration — suggest at minimum one full week of real-document volume,
  given the ~6,200-row real dataset accumulated over the system's life to date).
- `alter table ... drop column` for the 7 `SELECTED_*` columns, 4 of the 5 `SELECTION_*` columns (or
  all 5, per the owner's final call on §2.4's pushback), and the 3 confirmed-dead `EX_*` columns.
- Regenerate `indoxDataGateway01.json`/`indoxDocBatchUpsert01.json` trigger schemas again
  (`gen-gateway-trigger-schema.py --apply`) to remove the now-gone fields — G39 would otherwise flag a
  trigger field with no matching column.
- **Verify:** `select count(*) from information_schema.columns where column_name in (...)` returns 0
  for every dropped name; G39 green; a final harness run confirms no regression.
- **Rollback: this is the one genuinely hard-to-reverse phase — it's a real `DROP COLUMN`.** Mitigate
  by (a) taking a `pg_dump --table=incoming_documents` snapshot immediately before this phase (cheap —
  6,250 real rows), and (b) sequencing it last, after every other phase has had time to prove itself in
  production, specifically so this is the *only* step that isn't trivially reversible.

---

## 4. Risks, named

### 4.1 The `executeWorkflowTrigger` trap — and a wrinkle the brief didn't know about

Confirmed, `apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json:9-20`: the trigger's `jsonExample`
schema declares exactly 85 fields; anything a caller sends outside that list is silently dropped
before the workflow body ever runs — this is exactly how `NEXT_RETRY_AT` stayed empty on all rows
(confirmed still true today: `NEXT_RETRY_AT` is 0/6,250 on the live local stack). Gate: G39
(`trigger-schema-drift-lint.py`).

**The wrinkle:** there are now **two** write gateways in this codebase, not one. `indoxDocBatchUpsert01`
is the historical one this brief names; `indoxDataGateway01` (`apps/indox/blueprint/n8n/`,
679 lines) is a **newer, in-progress replacement** — confirmed via `scripts/refactor/GATES.md`'s gate
table: **G42** ("only `indoxDataGateway01` ... contains a Postgres node or a direct PostgREST call") is
listed **KNOWN FAILING as of 2026-08-05** with the note *"the gateway now exists (Phase 3) but the 65
direct writers have not been rewired onto it yet (Phase 4, tracked separately)."* Agent B's trace
confirms `indoxDocBatchUpsert01` is still the one actually in the live write path for extraction today
(`indoxDocBatchUpsert01` → `indoxApiRouter01` → `indoxApiSupabase01` → `PG Upsert` with
`autoMapInputData`, matched against the real 85-column schema, zero mismatches found). **This means:
every new column this refactor adds must be added to `indoxDocBatchUpsert01`'s schema for it to work
today, AND — since `gen-gateway-trigger-schema.py --apply` only regenerates `indoxDataGateway01` —
must also be added there for it to keep working once/if the separately-tracked Phase 4 rewire lands.**
Doing only one is a plausible way to reproduce the exact NEXT_RETRY_AT bug a second time, on a
different gateway file. §3 Phase 1 calls out both explicitly for this reason.

### 4.2 `SHORT_DOC_ID` — four divergent formulas (tangential to extraction, flagged for completeness)

Confirmed via `ai/context/INDOX-UNIFIED-N8N-SPEC.md:20,56-59` (the most recent of two same-day audits;
an earlier one counted three — the newer count supersedes it per its later timestamp): four
implementations of `SHORT_DOC_ID` exist with known collision sinks (`'00000'`, `'61520'`, `'22026'`).
**This refactor does not write `SHORT_DOC_ID`** (confirmed: none of the extraction/selection nodes
touched in this scan assign it) — it's a pipeline-wide identity concern, not an extraction concern, and
is already tracked separately under G43/`indoxIdentity01` in the broader consolidation plan. Named here
only so it isn't mistaken for something this refactor should also fix.

### 4.3 `PGRST_DB_MAX_ROWS=1000` — confirmed live

`docker inspect supabase-rest-shlomo-laptop` → `PGRST_DB_MAX_ROWS=1000` (local stack, confirmed
directly, not from a doc). Any verification query or backfill script in this plan that reads
`incoming_documents` without explicit pagination will silently see at most 1,000 rows. Every SQL in
§3's verification steps must page explicitly (`limit`/`offset` or keyset) once run against more than
1,000 rows — the 6,250-row real segment already exceeds this cap.

### 4.4 The two-gateway situation is itself a sequencing risk

If the separately-tracked "Phase 4" rewire (all 65 direct writers onto `indoxDataGateway01`) lands
*during* this extraction refactor's own phases, the extraction workflows' write target changes
mid-migration. Recommend: check `scripts/refactor/gates.sh` / G42's status before starting §3 Phase 5
(the actual behavior cutover) — if the rewire has landed by then, point Phase 5's new write at
`indoxDataGateway01` directly instead of `indoxDocBatchUpsert01`, since building new behavior on a
gateway already flagged for replacement is avoidable rework.

### 4.5 Settings/UI risk — low, but not zero

`_EDITABLE_SETTINGS_KEYS` is a hand-maintained frozenset (`apps/indox/app/incoming_documents/api/
__init__.py:195-206`) — adding a key there is a one-line, low-risk change, but it's the one piece of
this plan that **is** hand-maintained rather than generated, unlike the schema-column mechanism. No
gate currently checks this list against anything. Not a blocker, just noted as the one spot without a
drift-detection gate backing it.

---

## 5. The throughput dividend — quantified

**Constraint honored:** this section does not propose retuning `take`/`chunk`/`schedule_min`/worker
concurrency — those are confirmed out of scope. The dividend below is purely **hops removed** and
**round trips per document**, which reduces wall-clock latency for a *given* document at whatever rate
the existing scheduler already dispatches it — it does not require processing more documents per
interval to realize the benefit.

### Today, per document, in the actual live pipeline (not the Gmail-only `indoxProcessDocument01`
lane the brief centered on — see §0.2):

| Step | Calls |
|---|---|
| `Find Option` (company ID) + fallback `Extract COMPANY ID AFTER` | 1-2 |
| `Find Option` (doc type) | 1 |
| AI extraction (Gemini, base lane, covers all 7 base+per-type AI fields in one call) | 1 |
| `Query DOCUMENT_DATE` (AFTER + BELOW) | 2 |
| `Query INVOICE_ID` (AFTER + BELOW) | 2 |
| `Query SHIPMENT_ID` (AFTER + BELOW) | 2 |
| `Query PURCHASE_ID` (AFTER + BELOW) | 2 |
| `Query DOCUMENT_TOTAL_AMOUNT` (AFTER + BELOW) | 2 |
| **Total apitools/AI round trips** | **~13-14** |

(This excludes the one-time `documentOcr` upload/OCR call, which is already load-once and cached by
`file_hash` regardless of this refactor — not a target for reduction.)

### After consolidation (per §3's target design):

| Step | Calls |
|---|---|
| Base-doc step: 1 batched local call (`company_id`+`type`+`date_base`, via `documentDraw`-style
  multi-query, §1.5/§3 Phase 4) | 1 |
| Base-doc step: AI extraction (unchanged — already returns all 7 fields in one call today) | 1 |
| Per-type step: 1 batched local call (`invoice_id`/`date`/`amount`/`shipment_id`/`purchase_id` in one
  `queries[]` array) | 1 |
| Per-type step: AI (reused from base-doc's single call — no second AI call needed, confirmed by
  Agent B: the per-type lane's `if (!doc.AI_EXTRACTION_COMPLETED)` guard skips a redundant call when
  base-lane AI already ran) | 0 |
| **Total apitools/AI round trips** | **3** |

**~13-14 round trips → 3 round trips per document — roughly a 75-80% reduction in extraction-pipeline
network hops.** Each removed round trip pays for: one HTTP request/response cycle, one fresh
`OcrObject` reconstruction from the cached OCR JSON, and one from-scratch
`annotations_aligned_with_annotation` recomputation (§1.5) that a single `documentDraw`-style call
would compute once and reuse across all fields in that call.

### Concrete wall-clock numbers (supplied by the owner, folded in here)

Per-document cost is reported as **~95% apitools**, concentrated in two calls that dominate every
document regardless of lane:

| Call | Latency |
|---|---|
| `Document OCR` (the one-time OCR bootstrap, `indoxProcessDocument01.json:9-46` / equivalently
  `indoxV2UploadApiTools01`'s `Document OCR2`, :58-96) | **75.7s** |
| `Upload OR Get API_TOOLS_ID` (the cached-handle fetch every `Query*`/`Extract*` node reads
  `file_id` from — confirmed by name in `indoxV2QueryInvoiceId01.json:210-267`'s expression
  `$('Upload OR Get API_TOOLS_ID').item.json.file_id`) | **60.1s** |
| **Combined** | **135.8s**, ≈95% of total per-document processing time |

These two calls are **not** touched by this refactor — the OCR bootstrap is inherently one-time-per-
document (already cached by `file_hash`, §1.5) and isn't a target for consolidation; it's the *floor*,
not the part this plan reduces. **What this refactor removes is everything layered on top of that
floor**: the fragmented per-field round trips this document quantifies at ~13-14 calls today, down to
~3 (§5, table above). Each of those extra ~10-11 calls is a full `OcrObject` reconstruction from the
cached OCR JSON plus a fresh `annotations_aligned_with_annotation` recompute (§1.5) — real, measurable
work on top of the 135.8s floor, not free. Consolidating them via `documentDraw`'s load-once/iterate
pattern (§3 Phase 4, task #10) collapses that layered cost from ~11 extra round trips to ~1.

**Precise seconds saved is not fabricated here** — the two numbers above were supplied, not measured
by this research pass, and the per-call cost of the ~10-11 *fragmented field-query* calls specifically
(as opposed to the two big bootstrap calls) was not separately given. Every apitools response already
carries `ocr_ms`/`elapsed_ms`/`ocr_at` (`ocr_api.py:135-197,270-282`) — existing instrumentation, not
something to build. **Recommended first verification step:** sum `elapsed_ms` across the ~10-11
per-field query calls (excluding the two bootstrap calls above, which are unaffected) for a sample of
real documents, from n8n execution history, before vs. after Phase 4's batching lands. That turns "75%
fewer hops" into an exact seconds-per-document number for the part this refactor actually changes,
without re-measuring what's already been supplied and without touching any frozen batching/concurrency
setting.

---

## 6. Open questions for the owner

**Resolved since the first draft of this plan** (kept here, struck through in substance not in
markdown, so the resolution is traceable):

1. ~~`COMPANY_DOC_ID` vs. `INVOICE_ID`, `DOC_TOTAL_AMOUNT` vs. `TOTAL_AMOUNT`~~ — **Resolved by the
   owner: consolidate into new `DOC_ID` and existing `TOTAL_AMOUNT` respectively.** Full migration in
   §2.2b, including the conflict rule for disagreeing values and the live audit query that should run
   before the backfill (not yet run — that specific join was outside this pass's time budget; §2.2b
   names it explicitly as a pre-backfill step, not a remaining open question about the *design*, only
   about one *measurement* to take before executing it).
2. ~~BS summary scalars' bare-column names~~ — **Resolved by the owner: "should follow the same
   pattern."** Full design in §2.2a — document-level BS fields need zero new columns (they reuse the
   universal `DOC_DATE`/`TOTAL_AMOUNT` every type gets), line items get a new child table
   (`bs_extracted_lines`) with the same triad applied per line.

**Still open:**

3. **`SELECTION_*` disposition** — §2.4's pushback (keep one `SELECTION_DEBUG`, drop four) vs. the
   letter of "all `SELECTED_*`/`SELECTION_*` deleted." Needs an explicit owner decision before Phase 6.
4. **Duration of the observation window between Phase 5 (cutover) and Phase 6 (drop)** — this plan
   suggests "at least one week of real volume" as a floor, not a specific number; owner's call given
   actual document arrival rate. Given `FROM_OFFICE_CHECK`'s documented history of silently failing to
   persist (§2.8), recommend a *longer* window specifically for that rename, not the general floor.
5. **The `COMPANY_DOC_ID`/`INVOICE_ID` and `DOC_TOTAL_AMOUNT`/`TOTAL_AMOUNT` conflict-rate audit**
   (§2.2b) — a live join comparing both pairs' values where both are non-null. Not run in this pass;
   needed before the backfill in §2.2b step 3 executes unattended, in case a non-trivial disagreement
   rate signals the two columns aren't simply duplicate/stale but encode a real semantic difference
   (e.g. VAT-inclusive vs. not).
6. **`TIMESTAMP` (4,336/6,250) vs. `RECEIVED_DATE` (1,701/6,250)** — noticed during the full column
   audit (§8) as a possible third instance of the same "two names, one concept" pattern as §2.2b, but
   **not investigated** — out of the scope the owner explicitly named (`FROM_OFFICE`, `DOC_ID`,
   `TOTAL_AMOUNT`, BS). Flagged, not acted on; would need the same reader/writer trace as §2.2b before
   any recommendation.

---

## 7. Ordered task list

| # | Task | File/node | Buys | Risk | Verification | Rollback | Depends on |
|---|---|---|---|---|---|---|---|
| 1 | Commit uncommitted `indoxDocBatchUpsert01.json` schema fix | `apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json` | Stops the in-flight NEXT_RETRY_AT/THUMBNAIL/CONNECTION fix from being silently lost | Low | `git status` clean, G39 green | `git revert` | — |
| 2 | Commit uncommitted `indoxSettings01.json` cache-invalidation webhook | `apps/indox/blueprint/n8n/indoxSettings01.json` | Locks in the already-live 20-min-cache fix | Low | `git status` clean | `git revert` | — |
| 3 | Add `LOCAL_*` (×7) + `SELECTION_DEBUG` to `schema.sql` | `apps/indox/blueprint/fixtures/schema.sql` | Additive schema, zero behavior change | Low | `count(col)=0` for each new column | `drop column if exists` | 1,2 |
| 4 | Regenerate `indoxDataGateway01` trigger schema | `scripts/refactor/gen-gateway-trigger-schema.py --apply` | Keeps the new gateway in lockstep with schema.sql (belt-and-suspenders) | Low | G39/G42 green | Re-run generator against reverted schema.sql | 3 |
| 5 | Manually extend `indoxDocBatchUpsert01`'s `jsonExample` with the same new fields | `apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json:11` | The *actually-live* write path also accepts the new columns | Medium — hand-edit, no generator covers this file | G39 green for this file specifically | Revert the line | 3 |
| 6 | Source `FigureCompanyId01`/`FigureDocType01` queries from `settings.q_v3_company`/`q_v3_type`, write `LOCAL_COMPANY_ID`/`LOCAL_TYPE` alongside existing writes | `indoxV2FigureCompanyId01.json`, `indoxV2FigureDocType01.json` | First real use of the single-source-of-truth query definitions; base-doc `LOCAL_*` data starts flowing | Medium | `LOCAL_*` == bare column on a real-doc sample (should be a no-op in value, only provenance) | Revert workflow diff — new columns sit empty | 3,4,5 |
| 7 | Extend `extraction.py`'s harness with an AI-side run mode, scored by the same `_score()` comparators | `apps/indox/app/incoming_documents/extraction.py` | The actual shadow/compare mechanism — reuses existing dataset + comparators instead of building new | Low — pure addition to an existing tool | Harness reports AI accuracy per field/type, comparable to existing local accuracy numbers | No write-path involved — nothing to roll back | — |
| 8 | Run harness: wired-in local path vs. standalone `JQExV3` vs. ground truth | dataset + `extraction.py` | The correctness gate before Phase 4/5 | Low | Accuracy parity confirmed per field | n/a (observation only) | 6,7 |
| 9 | Wire per-type `Query*` workflows the same way (§3 Phase 4), write `LOCAL_DOC_ID`/`LOCAL_DOC_AMOUNT`/`LOCAL_SHIPMENT_IDS`/`LOCAL_ORDER_IDS` | `indoxV2Query{InvoiceId,TotalAmt,ShipmentId,PurchaseId}01.json` | Per-type `LOCAL_*` data starts flowing | Medium | Same harness, per-type fields | Revert workflow diff | 8 |
| 10 | Batch per-type local queries into one `documentDraw`-style call | `JQExV3*` `Query apitools` node, or new apitools `/documentJsonQueryBatch` | The throughput dividend (§5) — ~10 calls → 1 | Medium — apitools-side change | Response count/latency drop confirmed via existing `elapsed_ms` telemetry | Revert to per-field calls | 9 |
| 11 | Generate AI prompt fragments from `q_v3_*` `action_value` lists instead of hand-duplicated prompt text | `indoxV2ExtractInvoiceGemini01.json` CONFIG node | Closes the AI-prompt-vs-local-query duplication at the source | Medium — prompt-quality risk if generation is naive | Re-run harness's AI-side mode, confirm no accuracy regression vs. hand-written prompt | Revert to hand-written prompt text | 7,9 |
| 12 | Build `indoxV2Select01`, retire the two duplicated + one dead `Selection & Scoring Logic` copies | `indoxV2ActionsGDoc01.json`, `indoxV2ActionsShip01.json`, `indoxV2Driver01.json`, new `indoxV2Select01.json` | One selection implementation instead of three | Medium | Same scoring output as today's duplicated logic, on a real-doc sample | Revert to the two duplicated copies (keep, don't delete, until this is proven) | 6,9 |
| 13 | Cut over: base/per-type steps call `indoxV2Select01`, it writes bare canonical columns | Same files as #12 | The actual behavior change | High — this is the real cutover | Harness re-run against live output; monitor real-document volume for a window | Revert #12's wiring — old writes keep working, no data loss | 8,12 |
| 14 | Backfill bare columns from `SELECTED_*` where bare is null and `SELECTED_*` isn't | one-time SQL against `incoming_documents`, paginated (§4.3) | Preserves 43-88% already-computed history instead of discarding it | Medium — a real UPDATE, but targeted and reversible via the pre-migration `pg_dump` | Row-count diff before/after matches expected backfill count | Restore from `pg_dump` snapshot | 13 |
| 15 | Drop `SELECTED_*` (×7), `SELECTION_*` (×4-5 per owner's §6.2 call), `EX_*` (×3, dead) | `schema.sql`, regenerate gateway schemas | Final cleanup — the state the owner's design describes | **High — the one non-trivially-reversible step** | `information_schema.columns` no longer lists them; G39/G42 green; final harness run | Restore from the Phase-6 `pg_dump` snapshot taken immediately before this step | 13,14, ≥1 week production observation |
| 16 | (Optional, zero-risk, can run any time) Drop the 3 confirmed-dead `EX_*` columns | `schema.sql` | Free cleanup, evidence-backed (0/6,250 populated) | Low | `count(col)=0` confirmed pre-drop | `pg_dump` restore | — |
| 17 | Create `bs_extracted_lines` child table + one-time migration of the 152 populated `BS_EXTRACTED_LINES` JSON blobs into it | `schema.sql` (new table), one-off Python/SQL migration script | The BS design (§2.2a) — same triad-per-field model extended to line-item cardinality | Medium — a real ETL, but scoped to 152 rows | Row count in `bs_extracted_lines` matches `sum(jsonb_array_length(...))` over the 152 source blobs | Table is additive; drop it and nothing else is affected | 3 |
| 18 | Add `DOC_ID` column; dual-write from `COMPANY_DOC_ID`/`INVOICE_ID` writers | `schema.sql`, both gateway trigger schemas, ~10 writer workflows (§2.2b) | Starts the `DOC_ID` consolidation | Medium | New column populates alongside old ones on new writes | Stop dual-write; `DOC_ID` sits unused | 4,5 |
| 19 | Backfill `DOC_ID`/`TOTAL_AMOUNT` from `coalesce(live-writer-column, legacy-column)`; run the pre-backfill conflict audit first (§2.2b, §6 item 5) | One-time paginated SQL | Historical rows get the canonical value without re-extraction | Medium — real UPDATE, mitigated by pre-migration `pg_dump` | Backfilled-row count matches expected; conflict-audit count reviewed by owner if non-trivial | Restore from `pg_dump` | 18 |
| 20 | Switch every `COMPANY_DOC_ID`/`INVOICE_ID`/`DOC_TOTAL_AMOUNT` reader to `DOC_ID`/`TOTAL_AMOUNT`, including `extraction.py`'s field-name list and `DocumentBrowserPage.tsx`'s `DEFAULT_VISIBLE` array (easy to miss — string literals, no gate catches a stale one) | Files listed in §2.2b's reader table | Completes the consolidation | Medium | Harness + UI smoke-check post-switch | Revert reader diffs one at a time | 19 |
| 21 | Drop `COMPANY_DOC_ID`, `INVOICE_ID`, `DOC_TOTAL_AMOUNT` | `schema.sql`, both gateway schemas | Final state of the consolidation | High — real `DROP COLUMN` | `information_schema.columns` confirms gone; G39 green | `pg_dump` restore taken pre-drop | 20, observation window |
| 22 | Add `FROM_WAREHOUSE`/`FROM_WAREHOUSE_CHECK`, dual-write from every `FROM_OFFICE`/`FROM_OFFICE_CHECK` writer (~10 workflows, §2.8) | `schema.sql` + both gateway trigger schemas + workflows listed in §2.8 | Starts the rename, safely | Medium — this column has a documented silent-persistence-failure history; extra care warranted | New columns populate alongside old ones on new writes | Stop dual-write | 3 |
| 23 | Backfill `FROM_WAREHOUSE`/`FROM_WAREHOUSE_CHECK` from the old columns; switch every reader (`indoxV2Driver01`'s 5 sites, 2 fixture files, `DocumentDetailPage.tsx:24`, `DashboardPage.tsx:20`'s Hebrew label, `gsheet-table-api.md`'s allowlist) | Files listed in §2.8 | Completes the rename | Medium | Old vs. new column values match post-backfill; Hebrew label reads `'מהמחסן'` in the running UI | Revert reader diffs one at a time; dual-write keeps old path alive | 22 |
| 24 | Drop `FROM_OFFICE`/`FROM_OFFICE_CHECK` | `schema.sql`, both gateway schemas | Final state of the rename | High — real `DROP COLUMN`, and this specific column has a documented history of writes silently vanishing, so this drop deserves the longest observation window in this plan | `information_schema.columns` confirms gone; G39 green | `pg_dump` restore taken pre-drop | 23, extended observation window |

---

## 8. Full column ledger — every column in `public.incoming_documents`

Live counts, local stack, **6,250 rows, loadtest-50k already deleted** (re-confirmed at write time —
identical predicate as §2.7, now redundant since the whole table is real data). Generated via a
single query (`information_schema.columns` driving a `union all` of per-column `count()`s — full text
in the Appendix). Verdict legend: **KEEP** (no action), **RENAME** (this refactor renames it, see
cross-reference), **CONSOLIDATE** (merges with another column, see cross-reference), **DROP**
(remove — count/reader evidence given), **NEW** (added by this refactor).

| Column | Type | Non-null / 6,250 | Writer(s) | Reader(s) | Verdict |
|---|---|---|---|---|---|
| `ID` | text | 6,250 | Every ingestion workflow (primary key) | Everything | KEEP |
| `NAME` | text | 6,146 | Ingestion/naming workflows | `DocumentBrowserPage.tsx` (`DEFAULT_VISIBLE`/`SEARCH_COLS`), `DocumentDetailPage.tsx` (`IDENTITY_FIELDS`) | KEEP |
| `COMPANY_ID` | text | 6,019 | Base lane (§1.1 row 1), new selection step (§2.3) | UI browser/detail, every per-type workflow | KEEP — becomes the `VAL` side of the company-ID triad, §2.2 |
| `COMPANY_NAME` | text | 6,111 | `indoxV2ActionsGlobal01.json:978-987` | UI, fixtures | KEEP |
| `SHORT_DOC_ID` | text | 5,809 | 4 divergent formulas (§4.2, tracked separately, G43) | UI display label, dedup logic (today) | KEEP for now — its dedup role is slated to shrink once `DOC_ID` lands (§2.2b's cross-reference to §4.2), but that's the separate identity-consolidation effort's call, not this one's |
| `COMPANY_DOC_ID` | text | 5,841 | Per-type lane (§1.1 row 5) | §2.2b's reader table | **CONSOLIDATE → `DOC_ID`** (§2.2b) |
| `TYPE` | text | 6,171 | Base lane (§1.1 row 2), new selection step | Everywhere — the state-machine's own routing key | KEEP — becomes the `VAL` side of the doc-type triad, §2.2 |
| `STATUS` | text | 6,250 | State machine throughout | Everywhere | KEEP — out of scope, the state machine's own bookkeeping |
| `LINK` | text | 5,970 | Drive/Gmail ingestion | UI, source-linking | KEEP |
| `SOURCE_TYPE` | text | 6,168 | Ingestion | UI, `DocumentDetailPage.tsx` `SOURCE_FIELDS` | KEEP |
| `SOURCE_ID` | text | 6,168 | Ingestion | Dedup/identity | KEEP |
| `SOURCE_LINK` | text | 5,945 | Ingestion | UI `SOURCE_FIELDS` | KEEP |
| `SIZE` | text | 5,760 | Ingestion | UI `SOURCE_FIELDS` | KEEP |
| `HASH` | text | 5,760 | Ingestion | Dedup, UI `SOURCE_FIELDS` | KEEP |
| `TIMESTAMP` | text | 4,336 | Ingestion | UI `DEFAULT_VISIBLE` | KEEP — possible overlap with `RECEIVED_DATE`, flagged as §6 item 6, not investigated further |
| `RECEIVED_DATE` | text | 1,701 | Some ingestion paths only | Unclear from this pass | KEEP — see above |
| `DOC_DATE` | text | 6,025 | Base lane, new selection step | Everywhere, `DEFAULT_VISIBLE` | KEEP — the `VAL` side of the doc-date triad, and (§2.2a) BS's document-level date too |
| `DOC_TOTAL_AMOUNT` | text | 3,425 | Per-type lane (§1.1 row 8) | §2.2b's reader table | **CONSOLIDATE → `TOTAL_AMOUNT`** (§2.2b) |
| `TOTAL_AMOUNT` | text | 152 | Sparse/legacy path, not traced | `gsheet-table-api.md` allowlist, others | **KEEP as the consolidation target** (§2.2b) — receives `DOC_TOTAL_AMOUNT`'s data |
| `PURCHASE_ID` | text | 3,321 | Per-type lane | UI, per-type workflows | KEEP — the `VAL` side of the purchase-ID triad, §2.2 |
| `SHIPMENT_DOC_ID` | text | 2,737 | Per-type lane | UI, per-type workflows | KEEP — the `VAL` side of the shipment-ID triad, §2.2 |
| `REQUIRED_ACTION` | text | 3,021 | State machine | `SEARCH_COLS`, state machine | KEEP |
| `FROM_OFFICE` | text | 5,697 | `indoxV2ActionsShip01`/`GDoc01` (§2.8) | §2.8's reader table | **RENAME → `FROM_WAREHOUSE`** (§2.8) |
| `FROM_OFFICE_CHECK` | text | 5,718 | Same as above | Same as above | **RENAME → `FROM_WAREHOUSE_CHECK`** (§2.8) |
| `EMPTY` | text | **0** | Declared in both gateway trigger schemas (`indoxDocBatchUpsert01`, `indoxDataGateway01`) but no writer *sets* a non-blank value found in this pass | None found beyond schema declaration | **DROP — but confirm no writer first.** 0% populated despite being correctly declared in the trigger schema (i.e. this is the "empty because unused" case, not the "empty because the write was eaten" case — the schema doesn't drop it, nothing ever tries to fill it). Distinguishing evidence: unlike `NEXT_RETRY_AT` (also 0%, also declared correctly — see below), no workflow node was found assigning `EMPTY` a value at all, whereas `NEXT_RETRY_AT`'s writers exist and try to set it. |
| `LINKED_BS` | text | 2,003 | BS cross-reference matching (§2.2a note) | Reconciliation feature, out of this refactor's scope | KEEP |
| `BS_LINE_DATE` | text | 2,003 | Same as `LINKED_BS` | Same | KEEP — not the same mechanism as `BS_EXTRACTED_LINES`, see §2.2a |
| `BS_LINE_AMOUNT` | text | 2,003 | Same | Same | KEEP |
| `BS_LINE_NOTE` | text | 1,697 | Same | Same | KEEP |
| `BS_EXTRACTED_LINES` | text | 152 | `indoxV2ExtractBalanceSheet01` (AI-only today) | `indoxV2ActionsBS01`, BS UI | **CONSOLIDATE → `bs_extracted_lines` table** (§2.2a) — migrated then dropped, same reversible timeline as `SELECTED_*` |
| `BS_EXTRACTION_VERIFIED` | text | 152 | BS lane | BS workflow | KEEP |
| `BS_EXTRACTION_USE_CACHE` | text | 34 | BS lane, `ai_extraction_cache` control | BS workflow | KEEP |
| `BS_LINK_DOCUMENTS_COMPLETED` | text | 160 | BS lane | BS workflow | KEEP |
| `SEARCH_IN_DRIVE_COMPLETED` | text | 2,050 | State machine | State machine | KEEP |
| `DOC_DATE_COMPLETED` | text | 5,365 | Per-type lane | State machine | KEEP |
| `DOC_TOTAL_AMOUNT_COMPLETED` | text | 3,668 | Per-type lane | State machine | KEEP — flag name follows the old `DOC_TOTAL_AMOUNT`; owner's call whether the completion-flag name also moves with the §2.2b consolidation (not assumed here — the flag's *meaning* doesn't change, only the value column it gates does) |
| `PURCHASE_ID_COMPLETED` | text | 5,787 | Per-type lane | State machine | KEEP |
| `SHIPMENT_ID_COMPLETED` | text | 5,777 | Per-type lane | State machine | KEEP |
| `COMPANY_NAME_COMPLETED` | text | 5,119 | Base lane | State machine | KEEP |
| `API_TOOLS_ID_COMPLETED` | text | 5,790 | Upload step | State machine | KEEP |
| `API_TOOLS_ID` | text | 5,775 | `indoxV2UploadApiTools01` | Every `Query*`/`Extract*` node's `file_id` source (§5) | KEEP |
| `BS_EXTRACTED_LINES_COMPLETED` | text | 159 | BS lane | State machine | KEEP — mirrors `BS_EXTRACTED_LINES`'s consolidation timeline conceptually but the flag itself isn't dropped, only what it gates changes shape |
| `INVOICE_ID_COMPLETED` | text | 5,483 | Per-type lane | State machine | KEEP |
| `INVOICE_ID` | text | 3,549 | Not traced to a live writer in this pass | §2.2b's reader table | **CONSOLIDATE → `DOC_ID`** (§2.2b) |
| `INV_ID_FOR_SHIP` | text | 305 | `indoxV2Driver01`, `indoxV2ActionsShip01`/`GDoc01`, sync workflows (9 files) | Cross-reference feature | KEEP — low population is expected for this field (a rare cross-reference), not evidence of dead code; actively read/written across 9 workflow files |
| `EX_INVOICE_ID` | text | **0** | None found | None found | **DROP** — confirmed dead, §2.7 |
| `EX_IS_BS` | text | **0** | None found | None found | **DROP** — confirmed dead, §2.7 |
| `EX_IS_BS_COMPLETED` | text | **0** | None found | None found | **DROP** — confirmed dead, §2.7 |
| `FIGURE_TYPE_COMPLETED` | text | 1,968 | Base lane | State machine | KEEP |
| `FIGURE_COMPANY_COMPLETED` | text | 1,540 | Base lane | State machine | KEEP |
| `DOUBLE_LINE_CONTEXT` | text | 950 | `DOUBLE`-status collision tracking (SHORT_DOC_ID-adjacent, §4.2) | Identity/dedup logic | KEEP — out of this refactor's scope |
| `AI_COMPANY_ID` | text | 3,521 | AI extractor (§1.1 row 3) | Selection step, UI `fieldGroup()` | KEEP — frozen name, §2.2 |
| `AI_TYPE` | text | 3,531 | AI extractor | Selection step, UI | KEEP — frozen name |
| `AI_DOC_ID` | text | 3,810 | AI extractor | Selection step, UI | KEEP — frozen name (maps conceptually to `DOC_ID`, §2.2) |
| `AI_DOC_DATE` | text | 3,535 | AI extractor | Selection step, UI | KEEP — frozen name |
| `AI_DOC_AMOUNT` | text | 3,474 | AI extractor | Selection step, UI | KEEP — frozen name (maps to `TOTAL_AMOUNT`, §2.2) |
| `AI_SHIPMENT_IDS` | text | 3,536 | AI extractor | Selection step, UI | KEEP — frozen name |
| `AI_ORDER_IDS` | text | 2,823 | AI extractor | Selection step, UI | KEEP — frozen name |
| `AI_EXTRACTION_COMPLETED` | text | 3,564 | AI extractor | Per-type lane's `if (!doc.AI_EXTRACTION_COMPLETED)` guard (§5) | KEEP |
| `PRIORITY_SYNC_COMPLETED` | text | 5,381 | Priority-sync feature | State machine | KEEP |
| `PRIORITY_SYNC_COUNT` | text | 5,305 | Priority-sync feature | State machine | KEEP |
| `priority_sync` (lowercase, boolean) | boolean | 3 | Newer flag, actively referenced in `api.ts`, `core/models.py`, `core/diff.py` | Frontend + backend | KEEP — low population reflects a rare manual-override feature, not dead code (actively coded on both frontend and backend, unlike the `EX_*`/`EMPTY` dead columns) |
| `SELECTED_COMPANY_ID` | text | 5,469 | Duplicated selection logic (§1.1 row 10) | UI `fieldGroup()` | **DROP — migrate into `COMPANY_ID` first** (§3 Phase 5/6) |
| `SELECTED_DOC_ID` | text | 5,365 | Same | Same | **DROP — migrate into `DOC_ID` first** (post-§2.2b) |
| `SELECTED_DOC_TIPE` (sic) | text | 435 | Same | Same | **DROP — migrate into `TYPE` first** |
| `SELECTED_DOC_AMOUNT` | text | 3,631 | Same | Same | **DROP — migrate into `TOTAL_AMOUNT` first** |
| `SELECTED_DOC_DATE` | text | 5,465 | Same | Same | **DROP — migrate into `DOC_DATE` first** |
| `SELECTED_DOC_SHIPMENT_ID` | text | 1,161 | Same | Same | **DROP — migrate into `SHIPMENT_DOC_ID` first** |
| `SELECTED_DOC_ORDER_ID` | text | 2,096 | Same | Same | **DROP — migrate into `PURCHASE_ID` first** |
| `SELECTION_CERTAINTY` | text | 5,273 | Same | UI | **DROP per owner's rule** — or keep, per §2.4's pushback (open question, §6 item 3) |
| `SELECTION_SOURCE` | text | 5,520 | Same | UI | **DROP** — recoverable post-hoc by comparing `AI_<F>`/`LOCAL_<F>`/`<F>` once the triad exists (§2.4) |
| `SELECTION_COMPLETED` | text | 5,472 | Same | State machine | **DROP per owner's rule**, or keep (§6 item 3) |
| `SELECTION_SCORE_DEBUG` | text | 5,518 | Same | Debug/UI | **DROP per owner's rule**, or rename to `SELECTION_DEBUG` and keep — the one column §2.4 argues for keeping (§6 item 3) |
| `SELECTION_VALUES_HASH` | text | 5,516 | Same | Cache-invalidation logic | **DROP per owner's rule**, or keep (§6 item 3) |
| `IS_OLD` | text | 175 | `OldDocumentMonthsBack` cutoff logic | State machine | KEEP — low population is expected (a rare "past the cutoff" flag) |
| `EXTRACT_SHIPMENT_COMPLETED` | text | 3,370 | Per-type lane | State machine | KEEP |
| `סימון כרטסת עדכנית` (Hebrew: "current ledger-card marking") | text | **0** | None found beyond schema/gateway declaration | None found | **DROP — confirm no writer first**, same reasoning as `EMPTY` — likely a never-implemented BS-adjacent feature |
| `created_at` | timestamptz | 6,250 | Server default | — | KEEP |
| `updated_at` | timestamptz | 6,250 | Trigger (`trg_incdoc_touch`) | — | KEEP |
| `ACTION_LOG` | text | 620 | Every action-writing workflow | Debug/audit | KEEP |
| `ERROR` | text | 181 | Error paths | State machine, alerting | KEEP — low population is legitimate (most documents don't error) |
| `ITERATION_COUNT` | integer | 6 | State machine loop guard | State machine | KEEP — low population is legitimate (few documents loop) |
| `RETRY_COUNT` | integer | 6,250 | Declared correctly in trigger schema, defaults to `0` | Retry logic (once it works) | KEEP — **this is a bug-fix target, not a drop candidate.** Its 100% population is the `default 0`, not a real signal; the actually-important companion column is `NEXT_RETRY_AT` below. |
| `NEXT_RETRY_AT` | timestamptz | **0** | **Declared correctly in the trigger schema today** (§0.4's Phase-0 fix) — writers exist and attempt to set it | Retry-scheduling logic that has never once fired | **KEEP — THIS IS THE BUG, NOT A DEAD COLUMN.** 0/6,250 for the system's entire life because the write was silently dropped at the `executeWorkflowTrigger` boundary before §0.4's fix (still uncommitted). This is the textbook case the owner's instruction warns about: "empty because the write was being eaten," the opposite remedy from `EMPTY`/`EX_*`/`סימון כרטסת עדכנית` above — commit the fix (§3 Phase 0), don't drop the column. |
| `SYNC_NAME` | text | 73 | Newer sync-v3 pipes only | Loadtest marker (§2.7, now moot — loadtest rows deleted), state machine | KEEP — most of the table predates this column's convention, consistent with an in-progress sync-v3 migration (`ai/context/sync-v3-plan.md`), not evidence of dead code |
| `CONNECTION` | text | 5 | §0.4's Phase-0 fix (recently un-dropped) | State machine, `DocumentDetailPage.tsx` `SOURCE_FIELDS` | KEEP — low population is expected: this field was **also silently dropped by the same `executeWorkflowTrigger` bug as `NEXT_RETRY_AT`** until the uncommitted §0.4 fix; 5/6,250 reflects "just started working," not "unused." Same remedy as `NEXT_RETRY_AT`: land the fix, don't drop. |
| `THUMBNAIL` | text | 17 | §0.4's Phase-0 fix, `indoxV2ActionsGlobal01`'s `generate_thumbnail` action (owner request, `schema.sql:218-224`, dated the same day as this plan) | UI card view | KEEP — brand-new feature (days old), low population is simply "not yet backfilled," not dead |
| `THUMBNAIL_COMPLETED` | text | 334 | Same | State machine | KEEP — same reasoning; higher than `THUMBNAIL` itself because it's stamped whether or not the render succeeded (idempotent-terminal design, per `schema.sql`'s own comment) |

**Final target schema — the state after every phase in this plan, listed additively:**

- **Dropped** (7): `SELECTED_COMPANY_ID`, `SELECTED_DOC_ID`, `SELECTED_DOC_TIPE`, `SELECTED_DOC_AMOUNT`, `SELECTED_DOC_DATE`, `SELECTED_DOC_SHIPMENT_ID`, `SELECTED_DOC_ORDER_ID`
- **Dropped, pending §6 item 3's resolution** (4-5): `SELECTION_CERTAINTY`, `SELECTION_SOURCE`, `SELECTION_COMPLETED`, `SELECTION_VALUES_HASH`, and possibly `SELECTION_SCORE_DEBUG` (or that one renamed and kept as `SELECTION_DEBUG`)
- **Dropped** (3, zero-risk): `EX_INVOICE_ID`, `EX_IS_BS`, `EX_IS_BS_COMPLETED`
- **Dropped, pending confirmation of zero writers** (2): `EMPTY`, `סימון כרטסת עדכנית`
- **Dropped** (3, after §2.2b's consolidation completes): `COMPANY_DOC_ID`, `INVOICE_ID`, `DOC_TOTAL_AMOUNT`
- **Dropped** (2, after §2.8's rename completes): `FROM_OFFICE`, `FROM_OFFICE_CHECK`
- **Dropped** (1, after §2.2a's migration completes): `BS_EXTRACTED_LINES` (superseded by the `bs_extracted_lines` table)
- **Renamed** (2): `FROM_OFFICE`→`FROM_WAREHOUSE`, `FROM_OFFICE_CHECK`→`FROM_WAREHOUSE_CHECK`
- **New, on the main table** (7-8): `LOCAL_COMPANY_ID`, `LOCAL_TYPE`, `LOCAL_DOC_DATE`, `LOCAL_DOC_ID`, `LOCAL_DOC_AMOUNT`, `LOCAL_SHIPMENT_IDS`, `LOCAL_ORDER_IDS`, plus `DOC_ID` (new canonical identity column, §2.2b)
- **New, own table**: `bs_extracted_lines` (`AI_DATE`/`LOCAL_DATE`/`DATE`, `AI_AMOUNT`/`LOCAL_AMOUNT`/`AMOUNT`, `AI_NOTE`/`LOCAL_NOTE`/`NOTE`, per line, §2.2a)
- **Fixed, not schema-changed**: `NEXT_RETRY_AT`, `CONNECTION` (the executeWorkflowTrigger bug fix, §0.4/§3 Phase 0 — these columns already exist correctly, they just need their writers' values to stop being silently dropped)
- **Everything else**: unchanged — the ~55 identity/state-machine/lifecycle columns not named above carry no duplication, no dead data, and no owner instruction to touch them; the ledger above accounts for every one of them individually with a KEEP verdict and its reason, not by omission.

Net column-count change on the main table: -18/-19 (drops, pending §6 item 3) + 8 (new `LOCAL_*` +
`DOC_ID`) = **roughly 10-11 fewer columns on `public.incoming_documents` than today**, plus one new
small child table replacing a sparse JSON-blob column — a real simplification, not a wash.

---

## Appendix — commands used to produce this document's live numbers (local stack, reproducible)

```bash
# from WSL, targeting the bbox docker context (NOT hacohen-vps):
export DOCKER_HOST=unix:///run/bbox-docker.sock
docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -c "select count(*) from public.incoming_documents;"
docker exec n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -t -c \
  "select active, nodes::text like '%Invalidate Cache Webhook%' from workflow_entity where id='indoxSettings01';"
docker inspect supabase-rest-shlomo-laptop --format '{{range .Config.Env}}{{println .}}{{end}}' | grep PGRST

# §8's full column ledger — generate one count per column, then run it:
docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -t -A -f - <<'SQL'
select string_agg(
  format('select %L::text as col, %L::text as typ, count(%I) as n from incoming_documents',
         column_name, data_type, column_name),
  ' union all '
  order by ordinal_position
) || ' order by 1;'
from information_schema.columns where table_name = 'incoming_documents';
SQL
# ^ paste the single generated line back into psql -f to get every column's live count in one pass.

# TYPE breakdown + BS-line-count cross-check used in §2.2a:
docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -t -c \
  "select \"TYPE\", count(*) from incoming_documents group by 1 order by 2 desc;" -c \
  "select count(*) from incoming_documents where \"BS_EXTRACTED_LINES\" is not null and \"TYPE\" not ilike '%balance%';"

# FROM_OFFICE / FROM_OFFICE_CHECK value distribution used in §2.8:
docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -t -c \
  "select \"FROM_OFFICE\", count(*) from incoming_documents group by 1 order by 2 desc;" -c \
  "select \"FROM_OFFICE_CHECK\", count(*) from incoming_documents group by 1 order by 2 desc;"
```
