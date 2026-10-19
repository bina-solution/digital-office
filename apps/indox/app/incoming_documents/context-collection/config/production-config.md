# Production Configuration — Incoming Documents (current n8n implementation)

> Snapshot of the currently running production config, to be used as the **first document-repo** in the new system.

## Document Repo (Google Sheet)
- **Spreadsheet ID:** `1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo`
- **Spreadsheet name:** `AutomationValues`
- **Tab (sheet) name:** `מסמכים נכנסים` ("Incoming Documents")
- **gid:** `542119184`
- **URL:** https://docs.google.com/spreadsheets/d/1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo/edit#gid=542119184
- **Lookup column / primary key:** `ID`
- **Header row:** row 1 (52 columns — see `sample-data/incoming-documents.csv`)

## Google credential (n8n)
- Credential ID: `e2knIZpw8YF0QBAB`
- Credential name: `Google Sheets person17@example.com`
- Service account / OAuth2 user: `person17@example.com`
- **PLACEHOLDER:** `GOOGLE_SERVICE_ACCOUNT_JSON` — service-account JSON for the new Python API. To be provisioned; current n8n uses OAuth2 stored inside n8n.

## Workflows in scope for this migration
| Workflow ID            | Name                                | Role |
|------------------------|-------------------------------------|------|
| `xWM5NQjGxl0qAhHg`     | **Incoming Documents 0.1.6**        | Plan target. Main orchestration. Currently inactive (in-dev). Triggers: GSheet + Schedule + Webhook. |
| `indoxDocBatchUpsert01`     | Batch Upsert                        | Primary batch upsert of document rows (incl. lock/unlock). To be re-pointed at Python API. |
| `indoxDocGet01`     | Get Incoming Document               | Batch / single get with filters. To be re-pointed at Python API. |
| `indoxDocCreate01`     | Create Incoming Document            | Single create (HASH/COMPANY_ID dedupe). Reference for create semantics. |
| `pqD1bjLaiTcHRyCj`     | Batch API GSheet Cache Table        | Postgres-backed read cache for the GSheet. Reference for cache semantics. |
| `TTgW5l6qnQjsLwfM`     | Document Management - Optimal       | Cleanest reference impl of diff-engine batch upsert/append. |
| `processLock01`     | process_lock                        | Redis row-lock primitive. **Stays in n8n.** |
| `indoxSettings01`     | Settings                            | Settings/Companies/Queries cache (KVStorage + GSheet). |

## Explicitly out of scope
- `Incoming Documents 0.1.4` (`RSlxF4ztnpwSTdgE`), `0.1.5` (`oLdsvBaMCJ0fiwmE`) — superseded.
- `Snooze Incoming Document` (`bdchh5urW9lBzudZ`) — stays in n8n unchanged.
- `Update Incoming Document` (`BUtRdAn9Pj1Nv6aa`) — single-row update, not migrating.

## Locking
- Implemented via the `process_lock` workflow (Redis). Every batch-update path acquires a per-row lock keyed by `ID` and releases it on success/failure. **Lock/unlock will stay in n8n** (per plan), the Python API only handles the data side.

## Trigger for Incoming Documents 0.1.5
- `Google Sheets Trigger` polling the same spreadsheet/sheet (gid 542119184) for row changes.
- `Schedule Trigger` periodic sweep.
- **Future (per plan):** replace GSheet trigger with a Kafka trigger on topic prefix `${config.document-repo}` (e.g. `incoming-documents.AutomationValues_main`).

## Infra (deployment-hacohen)
- Redis: `redis-${DEPLOYMENT_NAME}` (also exposed via Traefik TCP 6379)
- n8n: queue mode + worker + task-runners
- Postgres (Supabase) available at `supabase.hacohen.bina-solutions.co.il` — see `SUPABASE_*` env vars
- **PLACEHOLDER:** `KAFKA_BROKERS` — no Kafka broker is currently deployed in the stack.
- **PLACEHOLDER:** `INCOMING_DOCS_DEFAULT_REPO` — name of the first repo entry to seed (e.g. `prod_gsheet`).

## Sample data
- `sample-data/incoming-documents.csv` — full export of the production sheet (39,582 data rows, 52 columns). Hebrew tab name preserved in source filename `AutomationValues - מסמכים נכנסים.csv`.
- Example header columns:
  `NAME, COMPANY_ID, SHORT_DOC_ID, TYPE, STATUS, COMPANY_DOC_ID, LINK, DOC_DATE, DOC_TOTAL_AMOUNT, PURCHASE_ID, SHIPMENT_DOC_ID, LINKED_BS, BS_LINE_DATE, BS_LINE_AMOUNT, SOURCE_TYPE, SOURCE_ID, SOURCE_LINK, SIZE, HASH, TIMESTAMP, COMPANY_NAME, REQUIRED_ACTION, BS_EXTRACTED_LINES, TOTAL_AMOUNT, BS_EXTRACTION_VERIFIED, BS_LINE_NOTE, FROM_OFFICE, FROM_OFFICE_CHECK, BS_LINK_DOCUMENTS_COMPLETED, SEARCH_IN_DRIVE_COMPLETED, DOC_DATE_COMPLETED, DOC_TOTAL_AMOUNT_COMPLETED, PURCHASE_ID_COMPLETED, SHIPMENT_ID_COMPLETED, COMPANY_NAME_COMPLETED, API_TOOLS_ID_COMPLETED, API_TOOLS_ID, ID, EMPTY, סימון כרטסת עדכנית, BS_EXTRACTED_LINES_COMPLETED, BS_EXTRACTION_USE_CACHE, EX_INVOICE_ID, INVOICE_ID_COMPLETED, EX_IS_BS, EX_IS_BS_COMPLETED, FIGURE_TYPE_COMPLETED, DOUBLE_LINE_CONTEXT, FIGURE_COMPANY_COMPLETED`
