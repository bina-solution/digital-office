# Incoming Documents — Phase 1 Context Collection

This directory holds the context required for phases 2–6 of the migration plan
([../plan.txt](../plan.txt)).

> **Refresh policy:** Always re-pull from the live n8n instance with `./scripts/n8n-pull` from the deployment root before re-reading these files. The local `n8n/workflows/` cache is **not** authoritative.

## Layout
```
context-collection/
├── README.md                  ← (this file)
├── n8n-workflows/             ← raw exports of every relevant n8n workflow
│   └── INVENTORY.md           ← what was collected, what's missing, what's related
├── apitools-snapshot/
│   └── STRUCTURE.md           ← snapshot of the apitools project today
├── sample-data/
│   └── incoming-documents.csv ← full production GSheet export (39,582 rows × 52 cols)
└── config/
    ├── production-config.md   ← live spreadsheet ID, tab, credentials, infra
    └── placeholders.env       ← env vars needed; unknowns flagged __PLACEHOLDER__
```

## What was collected

### n8n workflows (under `n8n-workflows/`)
Full subworkflow tree of `Incoming Documents 0.1.6` resolved by following every `executeWorkflow` node — see [n8n-workflows/INVENTORY.md](n8n-workflows/INVENTORY.md) for the tree diagram and per-file roles.

**Plan-target / migration-boundary workflows:**
- `incoming-documents-0.1.6_xWM5NQjGxl0qAhHg.json` — main orchestrator (213 nodes; in-dev). Has a `Webhook` trigger — natural seam for the Kafka swap.
- `batch-upsert_lmcZgw2TU8KOBXgs.json` — the n8n batch update workflow.
- `get-incoming-document_nSCcTxfq1BiNspG3.json` — the n8n batch get workflow.
- `process_lock_ilrs3Nl5eKmOLWFQ.json` — Redis row-lock primitive (**stays in n8n**).

**All direct + transitive subworkflows of 0.1.6 (also collected):**
Settings, Upload Doc To API TOOLS, Search File, Search File In Warehouse Scans, Figure Document Type, Figure Document COMPANY_ID, Query SHIPMENT_ID / PURCHASE_ID / DOCUMENT_DATE / DOCUMENT_TOTAL_AMOUNT / INVOICE_ID / IS_BALANCE_SHEET, Balance Sheet Extractor - v2, invoice Extractor - Gemini 3.1 pro.

**Reference (not direct children, useful contract reads):**
- `create-incoming-document_bt5Uzzl65Std5e3h.json` — single-doc create (HASH/COMPANY_ID dedupe).
- `batch-api-gsheet-cache-table_pqD1bjLaiTcHRyCj.json` — Postgres-backed read cache.
- `document-management-optimal_TTgW5l6qnQjsLwfM.json` — cleanest diff-engine reference.
- `batch-upsert-supabase-example_OtbKllH7OGAlUVDQ.json` — **Supabase batch upsert + get reference** (PostgREST + auto-schema introspection). Canonical reference for the Supabase backend of the new Python API.

### Explicitly excluded
- `Incoming Documents 0.1.4` / `0.1.5` / `0.1.3` — superseded.
- `Snooze Incoming Document` — stays in n8n unchanged.
- `Update Incoming Document` — single-row update path, not migrating.

### apitools project
- `apitools-snapshot/STRUCTURE.md` — current code layout, existing routes, env vars, dependencies, and an explicit list of what is **not** present today (no GSheet/Supabase/Kafka clients).

### Sample data
- `sample-data/incoming-documents.csv` — full export of the production sheet `AutomationValues / מסמכים נכנסים` (52-column header, 39,582 data rows).

### Config
- `config/production-config.md` — live spreadsheet ID `1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo`, tab `מסמכים נכנסים` (gid 542119184), n8n Google credential `e2knIZpw8YF0QBAB`.
- `config/placeholders.env` — env-var template with `__PLACEHOLDER__` markers for unprovisioned secrets.

## Gaps / things the plan calls for that don't exist yet
| Item | Status |
|------|--------|
| `Incoming Documents 0.1.6` | ✅ Found (`xWM5NQjGxl0qAhHg`, inactive in n8n). Already exposes a `Webhook` trigger — natural place to insert the Kafka consumer. Still needs its `Call 'Incoming Document Batch Update'` nodes re-pointed at the new Python API in phase 4. |
| Supabase batch upsert workflow | ✅ Found (`OtbKllH7OGAlUVDQ` — *Batch Upsert Supabase (untested example)*, inactive). Implements the same Webhook contract as `Batch Upsert` over PostgREST, plus auto-introspection / schema DDL and a built-in batch-get webhook. |
| Kafka broker | ⚠️ Not deployed in `compose.yml`. Phase 2 must decide: deploy Redpanda/Kafka, or fall back to Redis Streams. |
| Google Service Account JSON | ⚠️ Today n8n uses an **OAuth2 user** (`person17@example.com`). The Python service should switch to a service account with explicit sheet sharing. |
| `INCOMING_DOCS_REPO_REGISTRY` storage location | ⚠️ Plan does not specify. Tentatively local file in `.storage/`. |

## Phase 1 — Done. Ready for Phase 2.
Next step (per `../plan.txt`): produce the implementation + testing plan, including:
- Repo abstraction interface (Google Sheet ↔ Supabase).
- HTTP contract for `batch upsert` and `batch get` matching today's n8n behaviour exactly (lock/unlock stays in n8n).
- Kafka topic conventions: `${KAFKA_TOPIC_PREFIX}.<repo-name>` per plan.
- Test strategy: unit, integration (against ephemeral GSheet + ephemeral Supabase), e2e curl, load.
