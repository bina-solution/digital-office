# INDOX — per-type action routers (final architecture)

**Decision:** one action router *per document type*, each a self-contained full processing flow,
reusing shared actions as sub-workflows. No family abstraction, no config interpreter — explicit,
readable, inspectable n8n workflows. The state machine (Driver loop, one action per iteration,
completion-flag driven) stays intact.

## 1. The routers (5)

Today the Driver calls 3 collections: `DOC BASE`, `GDoc` (invoice **and** shipment), `BS`. This splits the
tangled `GDoc` into three and keeps `DOC BASE`/`BS`:

| Router (n8n workflow) | Runs on | Owns |
|---|---|---|
| **`router_doc_base`** *(was indoxV2ActionsGlobal01)* | **every doc, first** | normalize · classify TYPE · company_id · company_name · dedup · old-date · max-iter · pause |
| **`router_invoice`** *(split from GDoc)* | TYPE=INVOICE | full invoice flow (id·date·amount·purchase·shipment · AI · shipment-spawn · select · priority) |
| **`router_shipment`** *(split from GDoc)* | TYPE=SHIPMENT | shipment flow (id·date·purchase·shipment · select · priority) — no amount, no AI |
| **`router_order`** *(new)* | TYPE=ORDER | order flow (id·date·amount · AI · select) |
| **`router_bs`** *(was indoxV2ActionsBS01)* | TYPE=BALANCE_SHEET | extract lines · verify · spawn invoices |

Each router is **the full flow for its type**: a "decide next action for this type" head (the ordered,
flag-gated sequence) → a switch → the action handlers. Invoice and shipment *look* similar but are
**separate and clear** — the shared work is factored into the action library (§3), not shared control flow.

## 2. Dispatch — the clear type path

The tangle today is: Decide lumps INVOICE|SHIPMENT→`gdoc`, BS→`bs_doc`, ORDER→`unknown`, and the Driver
switches on `doc_class`. Replace with a two-line dispatcher:

```
Driver loop (unchanged shape):
   GET doc by id → acquire doc_step lock
   ┌── DISPATCH ─────────────────────────────────────────────┐
   │  if (!doc.DOC_BASE_COMPLETE)      → router_doc_base          │
   │  else switch (doc.TYPE) {                                │
   │     INVOICE       → router_invoice                       │
   │     SHIPMENT      → router_shipment                      │
   │     ORDER         → router_order                         │
   │     BALANCE_SHEET → router_bs                            │
   │     else          → router_doc_base (re-classify)          │
   │  }                                                       │
   └─────────────────────────────────────────────────────────┘
   router returns ONE action's result → Batch Upsert (sets a *_COMPLETED flag + unlocks) → loop
```

`router_doc_base` sets `DOC_BASE_COMPLETE` once TYPE + company are resolved; from then the doc flows through
its type router until `mark_completed`. One `switch(TYPE)` — that is the entire "type dispatching," explicit
and symmetrical. Adding a type = one `switch` arm + its router.

## 3. Shared action library (the reused sub-workflows)

Routers **orchestrate**; the actual work lives in shared sub-workflows called by whichever routers need
them. This is where "reuse stuff that occurs in multiple types" lives — DRY at the *action* level, not the
router level.

| Shared action (sub-WF) | Used by |
|---|---|
| `get_api_tools_id` (OCR upload) | invoice, shipment, order |
| `query_doc_date` | invoice, shipment, order |
| `query_doc_total_amount` | invoice, order |
| `query_purchase_id` | invoice, shipment |
| `query_shipment_id` | invoice, shipment |
| `query_doc_id` (invoice_id / order_id / receipt_id — one sub-WF, query passed in) | invoice, shipment, order |
| `ai_extract` (prompt+schema passed per type) | invoice, order |
| `select_values` (reconciliation) | invoice, shipment, order |
| `find_link` · `update_name` · `check_from_office` · `get_short_doc_id` · `update_company_doc_id` · `mark_completed` | all gdoc-type routers |
| `priority_sync` | invoice, shipment |
| `indoxApiRouter01` (all DB) · `driveApi01` · `gmailApiRouter01` | all |

So `router_invoice` and `router_shipment` are thin: each is an ordered list of `executeWorkflow(shared_action)`
calls gated by completion flags. The *only* per-router code is the **order** and the **guards** — which is
exactly the part that should be visible per type.

## 4. What each router's flow looks like (ordered, flag-gated)

**`router_doc_base`** → `normalize` → `figure_document_type` → `figure_company_id` → `get_company_name` →
(guards: dedup / old-date / max-iter / pause) → set `DOC_BASE_COMPLETE`.

**`router_invoice`** → `get_short_doc_id` → `update_name` → `check_from_office` → `find_link`
(→ missing-link dead-end if no file) → `get_api_tools_id` → `query_doc_id` → `query_doc_date` →
`query_doc_total_amount` → `query_purchase_id` → `query_shipment_id` → `ai_extract` →
`update_company_doc_id` → `extract_shipment_ids` (spawn) → `select_values` → `priority_sync` → `mark_completed`.

**`router_shipment`** → same head (`get_short_doc_id`…`find_link` — but **link-optional**, no dead-end) →
`get_api_tools_id` → `query_doc_id` → `query_doc_date` → `query_purchase_id` → `query_shipment_id` →
`update_company_doc_id` *(from SHIPMENT_DOC_ID‖AI_SHIPMENT_IDS[0])* → `select_values` → `priority_sync` →
`mark_completed`. **Omits** amount, AI, shipment-spawn.

**`router_order`** → `get_short_doc_id` → `update_name` → `get_api_tools_id` → `query_doc_id (order)` →
`query_doc_date` → `query_doc_total_amount` → `ai_extract (order schema)` → `update_company_doc_id` →
`select_values` → `mark_completed`.

**`router_bs`** → `extract_balance_sheet` → `verify_balance_sheet` → `link_documents` *(spawns INVOICE rows
that re-enter router_invoice, flagged `isBsLine` = no link/AI)* → `mark_completed`.

## 5. The state machine — intact

- **Driver loop unchanged**: GET → lock → dispatch → act → Upsert(sets flag) → loop. One action per iteration.
- **Completion flags unchanged**: each action sets its `*_COMPLETED`; the router's "decide next action" reads
  the same flags in the same order as `gdocAction()` does today — it's just now *one router per type* instead
  of one function branching on TYPE.
- **Reconciliation, spawn, dedup unchanged**: still real code (shared `select_values`, `link_documents`,
  the batch dedup in `router_doc_base`).
- Net behavior for invoice/shipment/BS is identical to today; order/receipt are additive new routers.

## 6. Migration (incremental, each step behind the 15-doc E2E)

1. **Extract shared actions** from `indoxV2ActionsGDoc01` into the sub-WF library (`select_values`,
   `update_company_doc_id`, etc. that aren't already sub-WFs). Behavior-preserving; GDoc still calls them.
2. **Fork `router_shipment`** out of GDoc: copy the shipment path, drop invoice-only steps, wire the Driver's
   `switch(TYPE)` SHIPMENT arm to it. Shadow-diff shipment docs (action-log identical) → cut over.
3. **Rename GDoc → `router_invoice`**, delete the now-dead shipment branches. Invoice E2E green.
4. **Add `router_order`** (new arm) — orders now reach COMPLETED instead of MISSING_TYPE. Strict improvement.
5. **Move per-type decide** out of the central `Determine Action` into each router's head; `Determine Action`
   shrinks to the §2 dispatcher (`DOC_BASE_COMPLETE ? … : switch(TYPE)`).
6. `router_bs`, `router_doc_base` unchanged; only the dispatcher + `resolveDocType` learn ORDER→router_order.

## 7. Why this is the right shape here

- **Each type's path is readable in one workflow** — open `router_shipment`, see the whole shipment flow.
- **Reuse without coupling** — shared work is sub-WFs; the routers don't share control flow, so changing
  invoice can't silently break shipment.
- **Symmetric dispatch** — one `switch(TYPE)`; BS is a peer router, not a bolted-on special case; order/receipt
  are first-class.
- **Stays in n8n's grain** — visual, inspectable workflows; no interpreter, no DSL, no config engine.
- **Config still helps where it's data** — the OCR queries / prompts / keyword lists remain settings the shared
  actions read (the `field_defs`/normalizer work already done). Data in config, flow in routers.
