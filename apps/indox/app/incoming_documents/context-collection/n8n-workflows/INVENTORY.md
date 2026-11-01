# n8n Workflows — Inventory

> **Source of truth:** the live n8n instance. Always run `./scripts/n8n-pull` from the deployment root before reading these files; **do not trust the local cache**.
> Last refresh: phase-1 collection (127 workflows total: 57 active · 70 inactive).

## A. Subworkflow tree of `Incoming Documents 0.1.6` (`xWM5NQjGxl0qAhHg`)

Computed by following every `n8n-nodes-base.executeWorkflow` node transitively. **22 reachable workflows.**

```
Incoming Documents 0.1.6 (xWM5NQjGxl0qAhHg) ❌
├── Batch Upsert (indoxDocBatchUpsert01) ✅                  ← migration target
│   └── process_lock (processLock01) ✅              ← stays in n8n
├── Get Incoming Document (indoxDocGet01) ✅          ← migration target  (called as "Execute Workflow1" + "Get Line By ID")
├── Search File (indoxV2SearchFile01) ✅
├── Search File In Warehouse Scans (indoxV2SearchWarehouse01) ✅
├── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅        ← already calls existing apitools service
├── process_lock (processLock01) ✅                   (also called directly: "Check LOCKED")
├── Settings (indoxSettings01) ✅                       ("Companies")
├── Query SHIPMENT_ID (indoxV2QueryShipmentId01) ✅
│   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
├── Figure Document Type (indoxV2FigureDocType01) ✅
│   ├── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
│   ├── Query INVOICE_ID (8TedFahagr7xPfuA) ✅
│   │   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
│   ├── Query IS_BALANCE_SHEET (hgeyNmcWVw6XUDu0) ✅
│   │   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
│   └── Query SHIPMENT_ID (indoxV2QueryShipmentId01) ✅
├── Figure Document COMPANY_ID (indoxV2FigureCompanyId01) ✅
│   ├── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
│   └── Settings (indoxSettings01) ✅
├── Balance Sheet Extractor - v2 (mphF5Nf028u8sIix) ✅   ("Call 'Balance Sheet Extractor - Next1'")
├── Query DOCUMENT_DATE (indoxV2QueryDocDate01) ✅
│   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
├── Query PURCHASE_ID (indoxV2QueryPurchaseId01) ✅
│   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
├── Query DOCUMENT_TOTAL_AMOUNT (indoxV2QueryTotalAmt01) ✅
│   └── Upload Doc To API TOOLS (indoxV2UploadApiTools01) ✅
├── invoice Extractor - Gemini 3.1 pro (indoxV2ExtractInvoiceGemini01) ✅
├── Snooze Incoming Document (bdchh5urW9lBzudZ) ✅       ← excluded per user; stays in n8n
└── Incoming Documents 0.1.4 (RSlxF4ztnpwSTdgE) ❌       ← excluded per user; called via "Execute ACTION_LINES" recursion target
```

Anomaly: `Incoming Documents 0.1.3` references its own `Execute ACTION_LINES` with a dynamic `={{ $workflow.id }}` (self-call), which appears as a missing target in static analysis. Not relevant to 0.1.6.

## B. Files collected here
| File | n8n ID | Active | Migration role |
|------|--------|--------|----------------|
| `incoming-documents-0.1.6_xWM5NQjGxl0qAhHg.json` | `xWM5NQjGxl0qAhHg` | ❌ | **Plan target** — main orchestrator (213 nodes). Webhook trigger present (Kafka swap point). |
| `batch-upsert_lmcZgw2TU8KOBXgs.json` | `indoxDocBatchUpsert01` | ✅ | **Migration target** — n8n batch update workflow. Lock/unlock stays in n8n; data side moves to Python API. |
| `get-incoming-document_nSCcTxfq1BiNspG3.json` | `indoxDocGet01` | ✅ | **Migration target** — n8n batch get workflow. |
| `process_lock_ilrs3Nl5eKmOLWFQ.json` | `processLock01` | ✅ | Redis row-lock primitive. **Stays in n8n.** |
| `settings_oomGi61yQd8RHoUO.json` | `indoxSettings01` | ✅ | Settings/Companies/Queries cache. |
| `upload-doc-to-api-tools_I584zKj0EStjV7ui.json` | `indoxV2UploadApiTools01` | ✅ | Already calls existing apitools service (reference for HTTP shape). |
| `search-file_cnvttABSBdZTe9Xv.json` | `indoxV2SearchFile01` | ✅ | GDrive search subworkflow. |
| `search-file-in-warehouse-scans_F4p4izmsw0KOWE62.json` | `indoxV2SearchWarehouse01` | ✅ | GDrive search subworkflow (warehouse scans). |
| `figure-document-type_GPjxkk2M0Wf22f4b.json` | `indoxV2FigureDocType01` | ✅ | Document-type classifier. |
| `figure-document-company-id_wFx3dWtcIn8gpxVD.json` | `indoxV2FigureCompanyId01` | ✅ | COMPANY_ID classifier. |
| `query-shipment-id_Lz6sfgDe88Zo4MnA.json` | `indoxV2QueryShipmentId01` | ✅ | OCR query (SHIPMENT_ID). |
| `query-purchase-id_Kwd61XkBdMLHoKsy.json` | `indoxV2QueryPurchaseId01` | ✅ | OCR query (PURCHASE_ID). |
| `query-document-date_61FD26EtrSPJskBe.json` | `indoxV2QueryDocDate01` | ✅ | OCR query (DOCUMENT_DATE). |
| `query-document-total-amount_b5kjPxOFVEzeUU54.json` | `indoxV2QueryTotalAmt01` | ✅ | OCR query (DOCUMENT_TOTAL_AMOUNT). |
| `query-invoice-id_8TedFahagr7xPfuA.json` | `8TedFahagr7xPfuA` | ✅ | OCR query (INVOICE_ID). |
| `query-is-balance-sheet_hgeyNmcWVw6XUDu0.json` | `hgeyNmcWVw6XUDu0` | ✅ | OCR query (IS_BALANCE_SHEET). |
| `balance-sheet-extractor-v2_mphF5Nf028u8sIix.json` | `mphF5Nf028u8sIix` | ✅ | Balance-sheet extractor pipeline. |
| `invoice-extractor-gemini-3.1-pro_Fa9wDKGFm9fx1vMY.json` | `indoxV2ExtractInvoiceGemini01` | ✅ | Invoice extraction via Gemini. |
| `create-incoming-document_bt5Uzzl65Std5e3h.json` | `indoxDocCreate01` | ✅ | Single-doc create (HASH/COMPANY_ID dedupe). Reference for create semantics — not a direct child of 0.1.6 but contract-relevant. |
| `batch-api-gsheet-cache-table_pqD1bjLaiTcHRyCj.json` | `pqD1bjLaiTcHRyCj` | ✅ | Postgres-backed read cache. Reference for cache semantics — not a direct child of 0.1.6. |
| `document-management-optimal_TTgW5l6qnQjsLwfM.json` | `TTgW5l6qnQjsLwfM` | ✅ | Cleanest reference impl of diff-engine batch upsert/append. |
| `batch-upsert-supabase-example_OtbKllH7OGAlUVDQ.json` | `OtbKllH7OGAlUVDQ` | ❌ | **Supabase batch upsert + get reference** (32 nodes, marked "untested example"). Implements same Webhook contract as `Batch Upsert` but writes to Supabase via PostgREST/RPC. Includes auto-introspection + schema DDL. Strong reference for the Python API's Supabase backend. |

## C. Excluded — explicitly not relevant to this migration
| Workflow | Reason |
|----------|--------|
| `Incoming Documents 0.1.4` (`RSlxF4ztnpwSTdgE`) | superseded; called by 0.1.6 as `Execute ACTION_LINES` legacy fallback only |
| `Incoming Documents 0.1.5` (`oLdsvBaMCJ0fiwmE`) | superseded |
| `Incoming Documents 0.1.3` (`Qq2sY8nWb4Dz0KcL`) | superseded; reachable only via `Snooze` |
| `Snooze Incoming Document` (`bdchh5urW9lBzudZ`) | stays in n8n unchanged |
| `Update Incoming Document` (`BUtRdAn9Pj1Nv6aa`) | single-row update path, not migrating |

## D. Supabase-backed batch upsert (referenced by plan)
> **Found** — collected as `batch-upsert-supabase-example_OtbKllH7OGAlUVDQ.json` (workflow `Batch Upsert Supabase (untested example)`, inactive).
>
> Shape:
> - Triggers: `Webhook - Update Document`, `Webhook - Get Documents`, `When Executed by Another Workflow`, manual.
> - Pipeline: `Clean Nulls` → `Check Priority Sync` → `Build Lookup Query` → `Lookup Existing Rows` (PostgREST) → `Resolve & Prepare Records` → `Supabase Upsert` (PostgREST) → `Split Updated IDs` → unlock via `process_lock`.
> - Auto-schema branch: `Build Introspection SQL` → `Run Introspection` → `Analyze Schema` → `Route by Action` switch (Create Schema / Schema OK / Schema Mismatch / Dedupe + Schema DDL).
> - Batch get branch: `Webhook - Get Documents` → `Build Get Query` → `Run Get` (PostgREST) → `Respond to Get Webhook`.
> - Only subworkflow dependency: `process_lock` (already collected).
>
> This is the canonical reference for the **Supabase backend** of the new Python `incoming_documents` API.

## E. Key node-shape summary

### `Incoming Documents 0.1.6` (`xWM5NQjGxl0qAhHg`) — 213 nodes
- **Triggers:** `Google Sheets Trigger` (sheet `מסמכים נכנסים`, gid 542119184), `Schedule Trigger`, `Webhook` (NEW vs 0.1.5), `When Executed by Another Workflow`, `Manual Trigger`.
- **Locking:** `Check LOCKED` → `process_lock`; `If NOT LOCKED` gate.
- **Batch-upsert call sites (~32):** PURCHASE_ID, COMPANY_NAME, EXTRACTED_LINES, EXTRACTED_LINES COMPLETED, LINK FOUND, STATUS COMPLETED, STATUS COMPLETED1, STATUS COMPLETED (BS), MISSING_COMPANY_ID, MISSING_COMPANY_ID (BS), MISSING_COMPANY_ID (Global), MISSING_COMPANY_ID (Global)1, MISSING_LINK, EXTRACTION_FAILED, API_TOOLS_ID, API_TOOLS_FAILED1, FROM_OFFICE, Restart BS, SEARCH_IN_DRIVE_COMPLETED, SHIPMENT_ID_COMPLETED1, UNKNOWN_COMPANY, UPDATE DOCUMENT_TYPE, UPDATE STATUS MISSING_TYPE, UPDATE COMPANY_ID, Update NAME, Doc Date, Doc Total Amount, AI values, Selection & Score, priority_sync, plus 4 untyped (Call …, Call …1, Call …2, Call …3).
- **Apitools integration today:** `Call Upload Doc To API TOOLS`, `Call Search File`, raw `HTTP Request`.

### `Batch Upsert` (`indoxDocBatchUpsert01`) — contract to preserve
- Entry: `When Executed by Another Workflow` **or** `Webhook - Update Document` (HTTP).
- Pipeline: `Code - Process Update Request1` → diff via `Get Sheet Data` → `Google Sheets batchUpdate` (HTTP) for updates, `Google Sheets batchUpdate1`/append for creates → unlock via `Call 'process_lock' unlock doc`.
- Side caches: Redis (tag-settings); optional Postgres mirror via `pqD1bjLaiTcHRyCj`.
- **Migration boundary:** Python API takes over the data side (read sheet → diff → batch update / append). The lock acquire/release stays inside this n8n workflow.

### `Get Incoming Document` (`indoxDocGet01`)
- Entry: `Webhook - Get` and `When Executed by Another Workflow`.
- `Switch` between `SINGLE GET` (by ID via `GET SINGEL BY ID` GSheet read), `Get ALL GSHEET`, `COMPLEX GSHEET QUERY`, and a `Custom Filter Engine` over a full read.

### `Document Management - Optimal` (`TTgW5l6qnQjsLwfM`)
- Self-contained "diff engine": `Standardize Input` → `Acquire Lock(s)` → `Get Current Sheet` → diff → `API Batch Update` + `API Batch Append` → `Release Lock`. Cleanest reference shape for the new Python implementation.

### Query-* subworkflows (indoxV2QueryShipmentId01, indoxV2QueryPurchaseId01, indoxV2QueryDocDate01, indoxV2QueryTotalAmt01, 8TedFahagr7xPfuA, hgeyNmcWVw6XUDu0)
- Common shape: `Upload OR Get API_TOOLS_ID` → call apitools `/documentJsonQuery` with a per-field query template → return value. Out of scope for the python-incoming-docs API, but documents how the orchestrator interacts with the existing apitools service.
