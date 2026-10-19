# INDOX State Machine v2.1 — consolidated, ready-to-implement plan

**What v2.1 is:** the v2 state machine, **restructured into explicit per-type action routers**, fully
testable, better-structured — with **zero behaviour change** for invoice/shipment/BS and **additive**
order/receipt. It carries forward everything in the original **0.1.7 monolith** (`sv5xxRBVGxvV0kXx`, 323
nodes) that the v2 split already preserved, and folds in every lesson from the build/debug work this
session (parallelism, paired-item, dedup, tests, gotchas).

Author date 2026-07-05. Companion designs: `ROUTERS-ARCHITECTURE.md`, `indox-per-type-fixture-architecture.md`
(fixture idea — **descoped**, see §9), `production/n8n/lib/normalizers.js`, `production/n8n/fixtures/`.

---

## A. Architecture

```
                         ┌──────────── async fan-out + wait-for-all (webhook callback) ────────────┐
 pg line-change / poll → DRIVER (indoxV2Driver01)  ── the ONLY cross-worker parallelism ───────────┘
      loop per doc:  GET-by-id → acquire doc_step lock →
        ┌── CENTRAL DECIDE (shrunk indoxV2Decide01) ──────────────────────────────┐
        │  1. batch-normalize (null · "true"/"false"→bool · Excel-date→DD/MM/YYYY)  │  ← MUST be central
        │  2. batch-dedup     (checkDuplicate + trackDoc — module Maps)             │  ← MUST be central (stateful)
        │  3. cross-cutting guards (empty-id · max-iter · pause)                    │
        │  4. shared pre-type guards (company_id · company_name · old-date)         │
        │  5. DISPATCH:  !DOC_BASE_COMPLETE ? router_doc_base : switch(TYPE)            │
        └──────────────────────────────────────────────────────────────────────────┘
                    │ returns { ACTION, ROUTER } for this doc
                    ▼
   router_doc_base | router_invoice | router_shipment | router_order | router_bs
       each = "decide next action for me" head  +  a switch that executes it via SHARED sub-WFs
                    ▼
   action ENDS with Batch Upsert (sets *_COMPLETED, unlocks) → Driver loops → … → mark_completed
```

BS diverges at `router_bs` (extract lines → verify → spawn INVOICE rows); spawned rows are `TYPE=INVOICE`,
flagged `isBsLine` (no LINK/AI), and re-enter `router_invoice`.

---

## B. Workflow manifest (create / rename / keep / retire)

| v2.1 workflow | Action | From current id | Notes |
|---|---|---|---|
| **Driver** | KEEP | `indoxV2Driver01` | loop/lock/snooze/test/warehouse/action-lines/shipment-linking side-flow stay |
| **central decide** | SHRINK | `indoxV2Decide01` | keep §1–5 only; move `gdocAction/bsDocAction` OUT |
| **router_doc_base** | RENAME | `indoxV2ActionsGlobal01` | figure_type/company/name (already exists) |
| **router_invoice** | RENAME + trim | `indoxV2ActionsGDoc01` | drop shipment-only branches |
| **router_shipment** | FORK (new) | from `indoxV2ActionsGDoc01` | shipment path only; no amount/AI/shipment-spawn |
| **router_order** | NEW | — | id·date·amount + AI; today ORDER→MISSING_TYPE |
| **router_bs** | RENAME | `indoxV2ActionsBS01` | extract/verify/link/spawn |
| **shared actions** | KEEP (sub-WFs) | see §D.2 | called by routers via executeWorkflow |
| **per-router tests** | NEW ×5 | template = `indoxV2BSTest01` | §E |
| `resolveDocType` | EDIT | in decide | add ORDER/RECEIPT → gdoc-family |

**Retire only after cut-over + green E2E:** the invoice/shipment tangle inside old GDoc; keep `0.1.7`
(`sv5xxRBVGxvV0kXx`) and `0.1.4` (`RSlxF4ztnpwSTdgE`) archived — **0.1.4 is still live as `ACTION_LINES`**,
do NOT delete it.

---

## C. Central decide vs per-router decide (the seam)

**Stays central** (indoxV2Decide01, ~150 lines) — *because it is batch-stateful and shared*:
- entry normalization (the Supabase TEXT string-boolean footgun fix — `"false"` is truthy; MUST run first);
- `checkDuplicate`/`trackDoc` (byId/byHash[only if LINKED_BS blank]/byCompanyShortDoc **batch Maps** — cannot be per-doc);
- guards: empty-id, max-iter (`max_actions_per_doc` default 50), pause, company_id (gated by `!!LINK`), company_name, old-date (`old_document_months_back` default 24);
- `resolveDocType` + `switch(TYPE)` dispatch. Output per doc: `{ACTION|route, ROUTER}`.

**Moves into each router's decide-head** (the type's ordered, flag-gated next-action):
- `gdocAction` → split into `router_invoice` + `router_shipment` heads;
- `bsDocAction` → `router_bs` head; new `router_order` head.
- Contract unchanged: **one action per Driver loop, gated by the same `*_COMPLETED` flags, same order.**

---

## D. Shared logic — two mechanisms (n8n can't `import`)

### D.1 Pure/string functions → a settings row, loaded via `new Function()`
Because n8n Code nodes have no module system, store the stateless helpers as a JS string in
`settings.indox_shared_lib` and each Code node does `const L = new Function(cfg.indox_shared_lib+';return {…}')()`.
Functions: `isBlank`, `parseDate`, `excelSerialToDate`, `anyOldDate`, `parseAiShipmentIds`,
string-bool/`null` coercion, and the reconciliation normalizers already extracted to
`production/n8n/lib/normalizers.js` (`docid_last5`, `companyid_last6`, `amount_2dp`, `date_ddmmyyyy`,
`id_clean`, `trim`, `uppercase`, `has`). Single source of truth; edit once. (Alternative for tiny/stable
ones: copy-paste — accept the drift risk only for trivial fns.)

### D.2 Reusable ACTIONS → shared sub-workflows (executeWorkflow)
| Shared sub-WF | id | Used by |
|---|---|---|
| get_api_tools_id (OCR) | `indoxV2UploadApiTools01` | invoice, shipment, order |
| Query DATE / AMOUNT / PURCHASE / SHIPMENT / INVOICE_ID | `indoxV2QueryDocDate01` `indoxV2QueryTotalAmt01` `indoxV2QueryPurchaseId01` `indoxV2QueryShipmentId01` `indoxV2QueryInvoiceId01` | per §per-type field lists |
| Figure Type / Company | `indoxV2FigureDocType01` `indoxV2FigureCompanyId01` | router_doc_base |
| invoice AI extractor | `indoxV2ExtractInvoiceGemini01` | invoice, order (per-type prompt) |
| BS AI extractor | `indoxV2ExtractBalanceSheet01` | router_bs |
| Batch Upsert | `indoxDocBatchUpsert01` | all (every action ends here) |
| Search File / Warehouse | `indoxV2SearchFile01` `indoxV2SearchWarehouse01` | find_link / from-office |
| Snooze | `bdchh5urW9lBzudZ` | Driver |
| ACTION_LINES | `RSlxF4ztnpwSTdgE` | BS line actions (legacy 0.1.4 — keep) |
| API routers | `indoxApiRouter01` `driveApi01` `gmailApiRouter01` | all DB/Drive/Gmail (nothing touches DB outside these) |
| select_values, find_link, update_name, update_company_doc_id, get_short_doc_id, check_from_office, mark_completed, priority_sync | extract from GDoc into their own sub-WFs | gdoc-family routers |

**Rule: routers ORCHESTRATE, sub-WFs DO.** Invoice & shipment share the *actions* (sub-WFs), not the
control flow — so changing invoice can't silently break shipment.

---

## E. Tests — one E2E per router (template = `indoxV2BSTest01` / `indoxV2GDocTest01`)

Reuse the proven harness shape: `Config` → `Execute Flows` fan-out → per-flow **seed → act → assert →
cleanup** → `🏁 Test Summary` → `Gate`. One test workflow per router:

- `test_router_doc_base` — seed a raw doc → assert TYPE + COMPANY_ID + COMPANY_NAME resolved, dedup catches a planted duplicate, old-date flagged.
- `test_router_invoice` — the existing `indoxV2GDocTest01` batch-lc flow (5×3 docs, find-or-upload reuse, drive to COMPLETED timed, assert `GT===AI===KW`, coverage, partial-error). **14/15 today** (shp3 KW-OCR pin).
- `test_router_shipment` — shipment docs to COMPLETED; assert KW id/date, no amount/AI, link-optional path.
- `test_router_order` — new; orders reach COMPLETED (not MISSING_TYPE).
- `test_router_bs` — the existing `indoxV2BSTest01` (extract→verify→spawn; spawned invoices complete).
- `test_suite` — runs all five, one consolidated summary.

**Test-harness lessons baked in (from this session):**
- **find-or-upload, not hardcoded links** — bulk `driveApi01 list` → resolve links in code so each item
  carries its own LINK via `$json` (a per-item `list` INSIDE the loop broke pairing and collapsed every
  link to the last doc → all docs got one doc's values). Recreatable + idempotent (reuse, don't re-upload).
- **postgres column case** — quoted cols come back UPPERCASE in n8n; alias ALL to lowercase in the verify
  query or reads silently return `undefined`.
- **type-aware asserts** — shipments have no invoice-AI; only assert AI fields for INVOICE/ORDER.
- **shadow-diff before cut-over** — `production/n8n/fixtures/tools/shadow_diff.py` pattern: run the new path,
  diff against live columns/action-log; cut over only on empty diff.

---

## F. State-machine contract — preserved

- **Driver loop unchanged**: GET → lock → decide → dispatch → Upsert(sets flag, unlocks) → loop; one action per iteration.
- **Parallelism unchanged**: the async sub-workflow fan-out + wait-for-all (0.1.7 mechanic) is the ONLY
  cross-worker parallelism; `executeWorkflow` is **serial in the calling worker**; a webhook call to an
  n8n workflow is what distributes. AI extract stays **bounded-5 via the extractor webhook** (measured
  max-6 concurrent). apitools is **single-query, `APITOOLS_MAX_CONCURRENT_JSON_QUERY=2`** — KW fields loop
  bounded-2. Don't try to parallelise KW via executeWorkflow (it serialises).
- **doc_step lock** stays (the churn/throughput root when not released between actions — TTL 10min).
- **Publish/active gate**: every router + shared sub-WF must be **active + activeVersionId** or
  `executeWorkflow` callers throw "not active". Deploy via `bbox n8n push` then `publish:workflow` +
  restart — never raw import (import leaves activeVersionId unset).
- **Paired-item correctness**: after any async boundary (executeWorkflow / driveApi / HTTP webhook),
  `$('Node').item` returns stale/item-0 → write-nodes must key off the **loop node** or pass the ID
  through the call; in batchSize-1 loops use `.first()`. (This was the AI-contamination root.)

---

## G. Anti-regression checklist (0.1.7 + v2 behaviours → where in v2.1)

| Behaviour (0.1.7 `sv5xxRBVGxvV0kXx`) | v2.1 home |
|---|---|
| async fan-out + wait-for-all parallelism | Driver (unchanged) |
| row locking (`Check LOCKED` `processLock01`, redis) | Driver + doc_step lock |
| TEST mode (`If TEST`) | Driver |
| Snooze (`bdchh5urW9lBzudZ`) | Driver |
| warehouse / from-office (`Search From Warehouse` `indoxV2SearchWarehouse01`) | shared action `check_from_office` |
| ACTION_LINES (BS lines, `RSlxF4ztnpwSTdgE` 0.1.4) | Driver → keep 0.1.4 archived-but-live |
| DOC BASE / GDoc / BS action switches | router_doc_base / invoice+shipment+order / router_bs |
| shipment↔invoice linking side-flow (`Search Existing Shipment`, `Create New Shipment Row`, `Update Existing — Link`, `Mark Invoice Completed`) | Driver side-flow (unchanged) + router_invoice `extract_shipment_ids` spawn |
| Kafka + schedule + webhook triggers | Driver / sync layer |
| SAME-ACTION-TWICE / COMPLETED / All-Finished guards | central decide + Driver |
| dedup, old-date, max-iter, pause | central decide |
| priority sync (default OFF) | router_invoice/shipment `priority_sync` |
| reset (`IndoxResetFull01` +setup, `IndoxResetGml001` gmail, `tVzFMkz18pCsXRyw` drive) | keep as-is |
| sync layer (Scanner/ScanUnit/Proc/Source, `sync-refactor-v1`) | keep as-is (upstream of Driver) |

**Nothing from 0.1.7 is dropped** — v2 already carried it; v2.1 only re-groups the collections.

---

## H. Session learnings folded in (the "don't relearn these" list)

- **Extraction quality is the real SLO, not "add a type".** Keep investing there: KW `ocr_json_query`
  wrong-field + shp3 (doc-date vs dispatch-date, stylized-id truncation); **post-process KW at extraction**
  (amount comma-strip, date normalize, id_clean); apitools **300 DPI** fix; invoice AI cache key was **MD5,
  no version/model bust** → use `prefix:version:model:hash`; Gemini billing/dunning can 403 live extraction.
- **The config-fixture engine was descoped** (§9) as over-engineering for n8n + a 5-type single-tenant
  product; keep only its *data* parts (queries/prompts/keywords in settings) and the normalizers lib.
- **Reliability gotchas**: Docker→Google DNS degrades under long sessions (EAI_AGAIN) — restart Docker
  Desktop; n8n heap must be < cgroup (OOM); host gives Docker ~8GB, pressure destabilises DNS.
- **Reconciliation** (`select_values`): AI-first, `docid_last5`/`companyid_last6`, `idMismatch`→certainty 0,
  180-day date-outlier, trusted-supplier boost; `SELECTION_VALUES_HASH` over 14 fields is the re-sync gate.

---

## I. Descoped / decided

- **No config interpreter / guard-DSL / dynamic pipeline runner.** Routers are readable n8n workflows;
  the per-type "what's next" is code, not JSON. (`indox-per-type-fixture-architecture.md` is kept for
  reference but NOT the plan.) Data lives in settings; flow lives in routers.

---

## J. Migration order (each step independently shippable + shadow-diffed + gated on the E2E)

1. **Extract shared actions** from `indoxV2ActionsGDoc01` into their own sub-WFs (`select_values`,
   `update_company_doc_id`, `get_short_doc_id`, `mark_completed`, …). GDoc still calls them → behaviour identical. Ship.
2. **Extract the shared lib** (`settings.indox_shared_lib` + normalizers) and rewire the decide + collections to load it. Byte-identical. Ship.
3. **Fork `router_shipment`** out of GDoc (shipment path only); wire the decide `switch(TYPE)` SHIPMENT arm; **shadow-diff shipment docs' action-log identical** → cut over. Ship.
4. **Rename GDoc → `router_invoice`**, delete dead shipment branches; invoice E2E (`indoxV2GDocTest01`) green. Ship.
5. **Add `router_order`** + `resolveDocType` ORDER→gdoc; orders now COMPLETE (strict improvement). Ship.
6. **Shrink central decide** to §C (batch-infra + dispatch); per-type heads now live in routers. Full E2E suite green. Ship.
7. **Wire the 5 per-router tests + suite**; run high-load-to-rest (200-doc). Ship.
8. Confirm publish/active + doc_step-lock behaviour under load; then archive the old tangle.

Every step: `bbox n8n push` → `publish:workflow` → restart → shadow/action-log diff vs a Step-0 oracle →
E2E green → ship. Riskiest structural change (shrinking decide) is last, on already-proven routers.

---

## K. Open risks & decisions

1. **Shared-lib load cost** — `new Function()` per Code node per doc; cache the built object in
   `$getWorkflowStaticData` or accept it (helpers are cheap). Editing the lib needs a settings/cache bump.
2. **Router count vs duplication** — invoice/shipment/order heads are ~40 similar lines each; accepted (clarity
   over DRY at the head level; DRY at the action level via sub-WFs). Watch for copy-paste drift → the
   per-router tests are the guard.
3. **doc_step lock throughput** — the known churn root; v2.1 doesn't fix it by itself. Ensure every action
   releases the lock on its terminal Upsert; consider it a separate reliability workstream.
4. **BS `ACTION_LINES` on 0.1.4** — a live dependency on an archived monolith; leave it, but flag for a
   future clean extraction into a shared `action_lines` sub-WF.
5. **Publish gate is a per-step tax** — 5 routers + N sub-WFs must all be published+active; the migration
   must verify after each push (a failed push deactivates callers).

**Can we get a fully working, testable v2.1 state machine this way? Yes** — because it's a *re-grouping*, not
a rewrite: the Driver, the decide contract, the shared actions, and the parallelism mechanic all stay; only
the collection boundaries move (GDoc → doc-base + invoice + shipment + order), guarded at every step by
shadow-diff + the per-router E2E. The one honest caveat: it improves *structure and testability*, not the
extraction-quality/throughput SLO — that stays a parallel workstream (§H).

---

## Progress log

**2026-07-05 — decide-split shipped + verified (migration step 5, done first per user choice).**
`indoxV2Decide01 › Determine Action` refactored from one branching `gdocAction()` into an explicit,
symmetric shape — behavior-preserving, one action-collection still executes:
- `docBaseDecide(doc,dup)` = the pre-router phase (dedup·double·pause·company_id·company_name·old-date),
  returns an action or `null` (= "doc-base complete"). Dedup stays stateful in the caller.
- `switch(TYPE)` dispatch: `INVOICE→invoiceDecide · SHIPMENT→shipmentDecide · ORDER→orderDecide ·
  BALANCE_SHEET→bsDecide · else→unknownTypeAction`.
- `gdocHead()` (restart + short-doc/name/from-office trails) and `gdocTail()` (select→priority→mark) are
  shared; the per-type *middle* (link handling, api-tools, KW queries, AI, spawn) is inline per decide fn.
- `orderDecide` is provisional = `invoiceDecide` (orders run the invoice flow until a dedicated router_order
  is built); `resolveDocType` now maps `ORDER→gdoc` (was `unknown`). Strict improvement; no INVOICE/SHIPMENT/BS
  doc affected.
- **Proof:** 700k-case fuzz harness (`scratchpad/parity_harness.js`) — Test1 gdocAction≡{invoice,shipment}Decide
  300k/300k, Test2 full determineAction parity (non-ORDER) 300k/300k, Test3 orderDecide≡invoiceDecide 100k/100k.
  Then live E2E `indoxV2GDocTest01` held **14/15** (4/5 suite checks green; only the gdx_shp3 OCR pin remains).
- **Also fixed this session (real defects, in-repo, uncommitted):** (a) `Build: Batch Update - Selection &
  Score` Set node omitted `SELECTED_DOC_TIPE` from the upsert mapping → type silently dropped before persist
  (the root cause of the earlier 4/15); (b) added `AI_TYPE`/`TIPE` to the `selection_values` resync hash so
  selection re-runs when the type lands.

**Next:** full-pipeline line E2E — a doc seeded with ONLY a link, driven through doc-base + type-specific
actions to COMPLETED, asserting each action fires. Then (optional) physically fork router_shipment/router_order.

---

## As-built architecture — verified 2026-07-05 (proper separation done)

The state machine is now **one loop + one decide + separated action collections**, all wired and verified:

```
Incoming Documents v2  (indoxV2Driver01, the Driver / loop)
  trigger {ID}  →  Get Line By ID  →  Start  →  Call indox-v2 Decide ─────┐
                                                                          │  (executeWorkflow, passthrough)
  ┌───────────────────────────────────────────────────────────────────── ▼
  │ indox-v2 Decide  (indoxV2Decide01 — THE single decide, no more inline copy)
  │   determineAction(doc):
  │     normalize · max-iter guard · stateful dedup
  │     docBaseDecide(doc,dup)            ← DOC BASE (pre-router): double·pause·company_id·
  │                                          company_name·old-date  → action | null
  │     if null → switch(TYPE):
  │        INVOICE  → invoiceDecide   ┐ gdocHead()  → per-type middle → gdocTail()
  │        SHIPMENT → shipmentDecide  │
  │        ORDER    → orderDecide     ┘ (provisional = invoice flow)
  │        BALANCE_SHEET → bsDecide
  │        else → unknownTypeAction (figure_type/AI fallback)
  └── returns {ACTION, DOC_TYPE, ...doc}
  →  Actions Dispacher  →  Switch1 (by DOC_TYPE / ACTION bucket):
        DOC BASE actions → indox-v2 Actions — DOC BASE   (indoxV2ActionsGlobal01*, figure company/name/type)
        gdoc actions     → indox-v2 Actions — GDoc       (indoxV2ActionsGDoc01)
        bs actions       → indox-v2 Actions — BS         (indoxV2ActionsBS01)
  →  indox-v2 Upsert (central)  (indoxV2Upsert01 → Batch Upsert)  →  loop
```
*(workflow ID `indoxV2ActionsGlobal01` kept to preserve caller bindings; display name is now
"indox-v2 Actions — DOC BASE".)*

**What changed this session (all in-repo, uncommitted, deployed+published+verified):**
1. **0.1.4 severed** — the disabled `Execute ACTION_LINES` dead node (which called `Incoming Documents 0.1.4`
   `RSlxF4ztnpwSTdgE`) removed from BOTH the Driver and 0.1.7. Nothing references 0.1.4 now; it is dormant
   (inactive+unpublished). **Only 0.1.7 and Incoming Documents v2 are live processors.**
2. **Single decide** — the Driver's live loop used to run its OWN stale inline `Determine Action` (old
   `gdocAction`, no split, no AI_TYPE hash fix, 98.8% == the pre-refactor standalone). Replaced with
   `Call indox-v2 Decide` (executeWorkflow → `indoxV2Decide01`). The 2 orphaned inline copies removed.
   Dedup safety preserved: `Lines Batching Loop` batchSize=15000 = one pass, and n8n Code nodes re-init
   module scope per execution anyway, so per-call dedup == prior behavior. **Verified:** invoking the Driver
   with `{ID:gdx_inv1}` spawns a child `indox-v2 Decide` execution returning `no_action_already_completed`.
3. **global → DOC BASE** — renamed everywhere human-visible: `indoxV2ActionsGlobal01.name`, its internal
   node names, the Driver's dispatch node + Switch1 output key, and `globalDecide`→`docBaseDecide` /
   `globalAction`→`docBaseAction`. `getWorkflowStaticData('global')` (n8n reserved, test-only) preserved.

**Two levels of separation — status:**
- **Decide-level: DONE** — `docBaseDecide` + symmetric `switch(TYPE)` per-type decide fns; 700k-fuzz parity
  proven; GDoc E2E held 14/15 through the rename+consolidation.
- **Actions-level: partial** — three collections exist (DOC BASE / GDoc / BS), but INVOICE+SHIPMENT+ORDER
  still share the one `Actions — GDoc` collection. Physically forking `router_shipment` / `router_order`
  out of GDoc is the remaining (optional) structural step; the decide already routes them per-type.

## The "indox v2 full pipline" test (next deliverable)

Goal: prove a doc goes **from only a link → COMPLETED** through *Incoming Documents v2* (the Driver), doing
ALL DOC BASE actions (implies TYPE + COMPANY from the file) then ALL type-specific actions — for **every**
type (INVOICE, SHIPMENT, ORDER, BALANCE_SHEET). Same shape as the per-type action-router tests
(`indoxV2GDocTest01` / `indoxV2BSTest01`) but driving the **Driver**, not the collections directly:
coverage · single lifecycle (timed) · batch lifecycle · consolidated summary. Named **`indox v2 full pipline`**.
Requirement it enforces: sync may deliver only a link — the pipeline must classify TYPE + resolve COMPANY
from the file alone and still complete. (Most real sources give more context; the link-only path is the floor.)

---

## FINAL separation — implemented + verified 2026-07-05

Decide and execute are separate calls in the main loop; per-type logic (decide + actions) lives in the
type router, called twice — once for decide (unlocked) and once for execute (locked). "Lock only what we work on."

```
MAIN LOOP (Incoming Documents v2 / Driver), per doc-batch:
  DECIDE (unlocked):  Call indox-v2 Decide           ← ONE batch call, all docs
  LOCK
  EXECUTE (locked):   Call router_X (mode=execute)   ← runs the chosen action
  UNLOCK → Upsert

indox-v2 Decide  ("basic determine action", 11k chars — shrunk from 17.7k):
   normalize · dedup(stateful) · max-iter · docBaseDecide · resolveDocType
     ├ doc-base action → return it
     └ else → set marker __route_gdoc__ | __route_bs__
   Route By Type (switch on marker):
     __route_bs__   → Set mode=decide (includeOtherFields!) → Call router_bs  (mode=decide, BATCH)  ┐
     __route_gdoc__ → Set mode=decide (includeOtherFields!) → Call router_gdoc (mode=decide, BATCH)  ├→ Decided (Merge) → return ACTION
     else           → ─────────────────────────────────────────────────────────────────────────────┘

router_bs / router_gdoc  (type-action-router = decide + actions, one WF, mode switch):
   When Called → Route Mode(mode):
     'decide'  → [bsDecide | invoice/shipment/orderDecide] → set ACTION, delete mode → return   (called by central)
     else      → action switch → handlers → upsert                                             (called by Driver execute)
```

**Batch — PROVEN (not assumed):** feeding 4 mixed docs (2 inv + 2 bs) to `indox-v2 Decide` → **1** Decide
execution (4 items) + **1** `router_bs.decide` (2 items) + **1** `router_gdoc.decide` (2 items). 4 docs → 3
executions, batched by type. (Per-doc Decide executions only appear in the coverage sub-test, which isolates
each handler by design.)

**Gotchas hit + fixed:** the `Set mode=decide` node silently dropped the doc `ID` ([[n8n-set-node-drops-unmapped-fields]])
→ churn (300+ non-converging iterations); fixed with `includeOtherFields:true`. Router decide-heads
`delete d.mode` so the execute call isn't re-routed to decide.

**Verified:** BS E2E 4/4 · GDoc E2E 14/15 (only the gdx_shp3 OCR pin) · Driver→single Decide smoke test.
Decide functions in the router heads are byte-identical to the 700k-fuzz-parity-proven ones (relocated, not
rewritten). Driver execute relies on the router `mode` fallback=execute (decided docs carry no `mode`).

**Remaining:** the "indox v2 full pipline" test (bare-link→COMPLETED via the Driver, per type). Optional later:
fork router_gdoc into physical router_invoice/shipment/order; explicit `mode=execute` on the Driver dispatch (hardening).

---

## DOC BASE router made symmetric — 2026-07-05 (all routers now decide+execute)

Per user directive: moved `docBaseDecide` (+ the empty-id / max-iter guards + AI_TYPE fallback + type-route
resolution) OUT of central and INTO `router_doc_base` (`indoxV2ActionsGlobal01`) as its **decide** mode. Now
EVERY router is `When Called → Route Mode(decide|execute)`, and central `indox-v2 Decide` is **pure
orchestration**:

```
indox-v2 Decide:
  Determine Action  = normalize · string-bool · date · STATEFUL dedup → attach doc._dup   (NO decision logic)
  → Set mode=decide → Call router_doc_base.decide   (guards + docBaseDecide + emit doc-base action | __route_TYPE__)
  → Route By Type → [ __route_bs__ → router_bs.decide | __route_gdoc__ → router_gdoc.decide | passthrough ]
  → Decided (Merge) → return ACTION
```

Dedup stays central (stateful across batch); its result rides on `doc._dup`, which the DOC BASE decide reads
(then deletes, along with `mode`). Verified: BS E2E 4/4 · GDoc E2E 14/15, converges 13 batched iterations
(1 central + 1 router_doc_base.decide + type-router.decide per iteration, each a batch call). Cost of the
symmetry: one extra batched decide execution per iteration — accepted for uniform decide/execute lock scoping.

**Next (user roadmap):** remove the shared `router_gdoc`, forking it into physical `router_invoice` /
`router_shipment` / `router_order` (each decide+execute), and route them explicitly from `Route By Type`.

---

## DOC BASE router test suite — added + green 2026-07-05

`indox-v2 DOC BASE E2E Test` (`indoxV2DocBaseTest01`, 23 nodes) — the BS/GDoc-style suite for router_doc_base:
- **Decide coverage (ONE batch):** 15 seed-states → call `router_doc_base.decide` directly (mode=decide,
  `_dup` supplied) → assert each decided action. Covers every docBase branch incl. the `__route_gdoc__` /
  `__route_bs__` markers. All 15 decided in a single batch call (the isolation test — central Decide would
  fan the markers onward, so we hit the router directly).
- **Lifecycle:** seed {COMPANY_ID, TYPE, no NAME} + a seeded test company → decide→execute loop →
  `get_company_name` resolves the name → next decide routes `__route_gdoc__`. Exercises the execute mode.
- **Summary:** 2/2. `update_status_double` intentionally omitted (needs two in-batch docs colliding on
  company+short-doc, which the upsert layer dedupes to one row; `no_action_double` covers the path).

Per user: when router_gdoc is forked into invoice/shipment/order, each gets its own suite of this shape.

---

## Router cleanup + test-parity pass — 2026-07-05

Compared the 3 router+test pairs; brought router_doc_base and its test up to alignment:
- **Layout:** doc_base's trigger/Route Mode/decide were stranded at x≈-300,y=0 while the handler cluster sat
  at x≈7000 (a ~7300px dangling wire). Repositioned them beside the execute switch, matching bs/gdoc.
- **router_doc_base clean:** removed the dead `xxxxx → Stop and Error2` arm; fixed `=update_status_old_doc`.
- **router_gdoc clean:** removed the disabled `Update file` node; fixed `=update_company_doc_id`.
- **DOC BASE test → full parity (3/3):** added **execute-coverage** (Act each STATUS-writing handler → assert
  STATUS: missing_company/unknown_company/missing_type/old/max-iter) alongside the 17-branch decide-coverage
  (one batch) and the get_company_name lifecycle. Matches the BS/GDoc coverage+execute+lifecycle shape.
- Verified: DOC BASE 3/3 · BS 4/4 · GDoc 14/15 all green.

**Deferred (harmless cosmetic — fold in when forking gdoc into a clean template):** 5 terminal `no_action`s
(double/paused/old_date/delete_row/unknown_document_type) have no doc_base execute arm and aren't in the
Driver `Switch1` doc-base list, so they mis-route to gdoc/bs — but they're no-ops (STATUS already terminal),
so no data harm. Also the `1`-suffixed handler node names (`...MISSING_COMPANY_ID1`) are naming cruft.

---

## DOC BASE test — full coverage incl. REAL-file figure classification — 2026-07-05 (5/5)

Rebuilt `indoxV2DocBaseTest01` as a clean multi-lane fan-out (like the GDoc test), 57 nodes:
- **Lane A — decide coverage** (16 docBase branches, ONE batch, calls router_doc_base.decide directly).
- **Lane B — execute coverage** (5 STATUS-writing handlers: Act → assert STATUS).
- **Lane C — lifecycle** (get_company_name executes → routes).
- **Lane D — figure coverage on REAL demo files** (find-or-upload one file per type via driveApi, then run
  `figure_document_type` + `figure_company_id` and assert): **figure_type 4/4** (INVOICE/ORDER/SHIPMENT/
  BALANCE_SHEET all classify correctly), **figure_company 3/3** (resolves 511301129/511234567/514291418).
  These two handlers were exercised by NO prior suite (BS/GDoc pre-seed type+company) — this is their only test.
- Companies must be seeded into `companies` for figure_company_id to resolve (it validates against the table);
  the test seeds them. Summary sits at the figure-lane tail (the splitInBatches loop defers it, so it runs last
  and all lane asserts are available).

Coverage: decide 11/12 · execute 8/12 (remaining: `update_status_double` unseedable + 3 no_action passthroughs).

---

## Coverage pinning — 100% node + decide, all batch (2026-07-05)

Measured router node-execution coverage from live test runs (aggregate nodes run across all router
sub-executions vs full node list):
- **BS: 100%** (48/48) — already complete (but coverage loops per-case; batch-convert pending).
- **DOC BASE: 100%** (41/41) after rework — inject-based batch execute lane covers all 9 handlers
  (update_status_* + no_action_* + Handle-Doubles) in ONE Act call; decide-coverage now 18 branches
  (added update_status_double via per-case `_dup`, + no_action_unknown_document_type). Full lifecycle
  drives 4 real files (all types) bare-link→figure_company→get_name→figure_type→route in batch.
- **GDoc: 86%** (89/104) — gaps: find_link (7 nodes: never runs, gdx docs pre-uploaded), priority_sync
  (4: setting default OFF), shipment-spawn `…1` variants (4: already-linked vs new-shipment). TODO.

Goal (per user): all 3 tests 100% node + 100% decide reach, ALL batch, to pin router behavior before the
gdoc fork so nothing breaks pipeline/batching/state-machine. Remaining: GDoc 3 gaps + batch-convert BS/GDoc
per-case coverage loops to single-batch decide+act.

## Coverage pinning — final state 2026-07-05

| Router | node coverage | coverage lane batched? |
|---|---|---|
| DOC BASE | 100% (41/41) | ✅ decide(18 branch)+execute(9 handler)+full-lifecycle(4 real files) all batch |
| BS | 100% (48/48) | ✅ converted per-case loop -> one batch (sub-execs 22->14) |
| GDoc | 95% (99/104) | ✅ coverage converted to one batch (17 handlers) |

GDoc last 5 uncovered = search-SUCCESS branches only: shipment-spawn `Create New Shipment Row1` /
`Update Existing — Link to Invoice1` (need `existing.matches` from the per-shipment Drive search inside
`Loop Over Items40`) + find_link `LINK FOUND` (`If Found File1`). Require seeded state (a pre-existing
shipment doc + a Drive file the search resolves), not a plain inject. Deferred as low-value edge branches.

Batch-conversion pattern: unique IDs per case (same-ID batch dedupes to 1 row in the collection), collection
returns only one switch-branch's output for a mixed-action batch so asserts must read the DB (SQL), not the
executeWorkflow return count. All handlers still run (routed per-item to switch arms) = node coverage.
