# INDOX main state machine — v2 (swappable, modular, testable)

> Goal: a **brand-new v2 layer that behaves EXACTLY like the live v1** main workflow
> (`Incoming Documents 0.1.7` = `sv5xxRBVGxvV0kXx`, 323 nodes), but decomposed into small,
> independently testable workflows. Built **alongside** v1 (v1 stays active); v2 is inactive
> until parity is proven, then swapped. **All v2 workflows carry the tag `indox-state-machine-v2`.**

## Why v2 preserves exact behaviour (fidelity contract)
1. **Same brain.** v2 `Decide` runs the *verbatim* `determineAction` function from v1 — same ordered
   if-ladder + per-type routers → every doc yields the same `ACTION`. The only change is that the 3
   `$('Companies')` config reads (`max_actions_per_doc`, `old_document_months_back`, `activePrioritySync`)
   are injected as an input object `_cfg` (with a `$('Companies')` fallback), making Decide a pure
   `(doc, cfg) → {ACTION, DOC_TYPE, ...doc}`.
2. **Same leaf effects.** Every v2 handler calls the *exact same* effect sub-workflows v1 calls
   (see the registry `effect` column). No effect is rewritten. The row writer is the same
   `Batch Upsert` (`indoxDocBatchUpsert01`) with the *same field mappings* (incl. the `ACTION_LOG` append
   `(ACTION_LOG||'') + ', <TAG>, ' + $now + ', ' + $execution.id`).
3. **Same driver semantics.** Same lock protocol (`process_lock` `processLock01`, TTL 10m), same
   loop-back (re-GET by ID → Decide → act until terminal), same `max_actions_per_doc` guard, same
   triggers (poll line-changes + pg trigger). Only the topology of *dispatch* changes.

### The one real hazard: cross-node references break on extraction
v1 handlers reference their own label node via `$('Action: X').item.json.*` and read `$('Companies')`,
`$('Start')`, `$('Determine Action')`. Pulling a handler into its own sub-workflow breaks these across
the `executeWorkflow` boundary (the `unknown-11644` / stale item-0 class — see
`n8n-paired-item-batch-correctness`). **Rule for every port:** the handler receives the full determined
item `{...doc, ACTION, DOC_TYPE, _cfg}` on its `executeWorkflowTrigger` input, and every external
`$('…').item` reference is repointed to `$json` (or a `.first()` on the batch driver, never
`$('<execWf>').first()`). The complex handlers are ported node-by-node, not mechanically.

## AS-BUILT architecture (2026-07-02) — verbatim block extraction (chosen for Option A / exact clone)
Instead of a generic executor (JS-translation risk when generating blind), v2 lifts v1's **three natural
action-blocks verbatim** into sub-workflows. Boundary analysis proved the three blocks are disjoint with
**zero cross-references and zero exit edges** (handlers are terminal; the loop re-enters via the driver's
`Run By ID`, not via wires) — so the copy is behaviourally exact with no expression repointing.

| v2 workflow | id | nodes | = v1 source |
|---|---|---|---|
| **Decide** | `indoxV2Decide01` | 2 | verbatim `Determine Action` (cfg → `_cfg`, default-fallback = v1) |
| **Decide Tests** | `indoxV2DecideTest01` | 4 | v1 fixture table + assertions → calls Decide |
| **Actions — Global** | `indoxV2ActionsGlobal01` | 39 | the `3a. Global Actions Switch` island (13 actions) |
| **Actions — GDoc** | `indoxV2ActionsGDoc01` | 100 | the `3a. GDOC Action Switch1` island (27 actions, incl. find_link/check_from_office/extract_shipment_ids/select_invoice_values) |
| **Actions — BS** | `indoxV2ActionsBS01` | 44 | the `3b. BS Action Switch1` island (10 actions, incl. link_documents) |
| **Driver** | `indoxV2Driver01` | 146 | v1 **minus** the 3 blocks; `Switch1` out0/1/2 rewired → `executeWorkflow(collection)` (terminal). All 8 triggers + lock + loop + ACTION_LINES + inline brain preserved verbatim. |

Config fidelity: v1's single `Companies` node lives *inside* the Global block and never runs before
`Determine Action`, so v1's brain always falls back to defaults (max=50, months=24, priority=off). Decide
with no `_cfg` does the same → identical. Each collection is `executeWorkflowTrigger(passthrough) → its
switch → verbatim handlers (terminal)`. Vestigial phantom loop-back edges (stale renamed-node connection
keys, already dead in v1) are dropped. **The generic-executor/registry design below is the v2.1 target**
(collapse the collections once parity is proven); v2 keeps blocks verbatim for exactness.

## Architecture (3 layers + registry) — v2.1 target (not yet built)
```
 trigger(s) ─▶ GET doc by ID ─▶ acquire lock ─▶ [Decide] ─▶ action_id
                                                     │
                                     registry lookup (action_id → handler + effect + writes)
                                                     ▼
                                         [Execute Action]  ── simple ─▶ generic executor
                                                            └ complex ─▶ dedicated handler WF
                                                     ▼
                                        Batch Upsert (write row + ACTION_LOG + unlock)
                                                     ▼
                                        loop back to GET (until terminal / no_action)
```
- **`indox-v2 Decide`** (`indoxV2Decide01`) — pure transition fn + attached unit-test harness.
- **`indox-v2 Driver`** (`indoxV2Driver01`) — triggers, GET, lock, Decide, dispatch, loop, max-iter guard.
- **`indox-v2 Execute Action`** (`indoxV2Exec01`) — generic executor for the *simple* action classes.
- **Dedicated handler WFs** — the 6 complex actions (below).
- **`action_registry`** — a data map `action_id → {scope, class, effect, inputMap, writeMap, statusTag, terminal}`.
  Kept in the Decide/Driver as a Code map first (guards are closures); can move to a settings row later.

## Action classes (from the full v1 extraction)
Every v1 action reduces to one of five classes. Class determines whether the generic executor handles it.

| class | shape in v1 | generic? |
|---|---|---|
| **NO_ACTION** | just a `noOp` sink; no write, no lock (runs on the "Map NO ACTION" branch) | ✅ (do-nothing sink) |
| **STATUS_WRITE** | `noOp → splitInBatches(1) → Batch Update(STATUS=…, ACTION_LOG+=)` | ✅ (writeMap only) |
| **FIELD_WRITE** | STATUS_WRITE that also sets specific fields (e.g. `update_company_doc_id`, `get_short_doc_id`) | ✅ (writeMap only) |
| **SINGLE_EFFECT** | `noOp → loop → executeWorkflow(effect) → Batch Update(map result → fields)` | ✅ (effect + writeMap) |
| **COMPLEX** | multi-node: conditional writes / sub-searches / row fan-out | ❌ dedicated WF |

## Action registry (all 50 outputs — id · scope · class · effect · writes)
`scope`: global | gdoc | bs. Effects are workflow IDs. "writer" = `Batch Upsert lmcZ` unless noted.

### Global (from `3a. Global Actions Switch`)
| action_id | class | effect / notes |
|---|---|---|
| `update_status_double` | COMPLEX | writer(STATUS per dup) → `If id Match1` branch |
| `figure_company_id` | SINGLE_EFFECT | `indoxV2FigureCompanyId01` Figure COMPANY_ID → writer(COMPANY_ID) |
| `update_status_missing_company` | STATUS_WRITE | STATUS=MISSING_COMPANY_ID |
| `no_action_awaiting_company_id` | NO_ACTION | — |
| `get_company_name` | SINGLE_EFFECT | `indoxSettings01` Settings/Companies → writer(COMPANY_NAME) |
| `update_status_unknwon_company` | STATUS_WRITE | STATUS=UNKNOWN_COMPANY |
| `no_action_awaiting_company_name` | NO_ACTION | — |
| `figure_document_type` | SINGLE_EFFECT | `indoxV2FigureDocType01` Figure Document Type → writer(TYPE) |
| `update_status_missing_type` | STATUS_WRITE | STATUS=MISSING_TYPE |
| `update_status_old_doc` | STATUS_WRITE | STATUS=OLD/COMPLETED3 |
| `mark_max_iterations` | STATUS_WRITE | STATUS=MAX_ITERATIONS |
| `no_action_max_iterations` | NO_ACTION | — |
| `Default` | (guard) | `Stop and Error2` — should never route here |

### GDOC (from `3a. GDOC Action Switch1`)
| action_id | class | effect / notes |
|---|---|---|
| `restart_gdoc` | STATUS_WRITE | STATUS=MISSING_COMPANY_ID (restart) |
| `get_short_doc_id` | FIELD_WRITE | SHORT_DOC_ID |
| `update_name` | SINGLE_EFFECT | writer(NAME) → `driveApi01` Update file (rename in place) |
| `check_from_office` | COMPLEX | WH settings → `indoxV2SearchWarehouse01` warehouse search → writer(FROM_OFFICE_CHECK) |
| `find_link` | COMPLEX | `indoxV2SearchFile01` Search File → `If Found` → writer(LINK / SEARCH_IN_DRIVE_COMPLETED) |
| `update_status_missing_link` | STATUS_WRITE | STATUS=MISSING_LINK |
| `no_action_link_not_found` | NO_ACTION | — |
| `get_api_tools_id` | SINGLE_EFFECT | `indoxV2UploadApiTools01` Upload to apitools → writer(API_TOOLS_ID) |
| `update_status_api_tools_failed` | STATUS_WRITE | STATUS=API_TOOLS_FAILED |
| `no_action_api_tools_failed` | NO_ACTION | — |
| `query_invoice_id` | SINGLE_EFFECT | `indoxV2QueryInvoiceId01` Query INVOICE_ID → writer(INVOICE_ID) |
| `query_doc_date` | SINGLE_EFFECT | `indoxV2QueryDocDate01` Query DOCUMENT_DATE → writer(DOC_DATE) |
| `query_doc_total_amount` | SINGLE_EFFECT | `indoxV2QueryTotalAmt01` Query DOCUMENT_TOTAL_AMOUNT → writer(DOC_TOTAL_AMOUNT) |
| `query_purchase_id` | SINGLE_EFFECT | `indoxV2QueryPurchaseId01` Query PURCHASE_ID → writer(PURCHASE_ID) |
| `query_shipment_id` | SINGLE_EFFECT | `indoxV2QueryShipmentId01` Query SHIPMENT_ID → writer(SHIPMENT_ID_COMPLETED) |
| `no_action_doc_date_missing` | NO_ACTION | — |
| `no_action_doc_total_amount_missing` | NO_ACTION | — |
| `update_status_missing_shipment` | STATUS_WRITE | STATUS=COMPLETED1 |
| `extract_invoice_google_ai` | SINGLE_EFFECT | `indoxV2ExtractInvoiceGemini01` invoice Extractor Gemini → writer(AI values) |
| `update_company_doc_id` | FIELD_WRITE | COMPANY_DOC_ID (from NEW_COMPANY_DOC_ID) |
| `extract_shipment_ids` | COMPLEX | mark → split IDs → `indoxDocGet01` search → link/create shipment rows |
| `select_invoice_values` | COMPLEX | `oomGi…` settings → `Selection & Scoring Logic1` → writer(selected fields) |
| `priority_sync` | SINGLE_EFFECT | HTTP Post Priority Table → writer(PRIORITY_SYNC_COMPLETED) |
| `mark_completed` | STATUS_WRITE | STATUS=COMPLETED |
| `action_old_date` | STATUS_WRITE | STATUS=COMPLETED2 |
| `no_action_awaiting_company_id` / `no_action_awating_doc_id` | NO_ACTION | — |

### BS (from `3b. BS Action Switch1`)
| action_id | class | effect / notes |
|---|---|---|
| `update_status_missing_company` | STATUS_WRITE | STATUS=MISSING_COMPANY_ID (BS) |
| `no_action_awaiting_company_id` | NO_ACTION | — |
| `restart_balance_sheet` | STATUS_WRITE | restart |
| `extract_balance_sheet` | SINGLE_EFFECT+ | `indoxV2ExtractBalanceSheet01` BS Extractor → `If Success` → writer(BS_EXTRACTED_LINES + …_COMPLETED) |
| `update_status_extraction_failed` | STATUS_WRITE | STATUS=EXTRACTION_FAILED |
| `no_action_extraction_failed` | NO_ACTION | — |
| `link_documents` | COMPLEX | the big one: loop BS → split lines → `nSCc…` search → link/create invoice rows → aggregate |
| `mark_completed` | STATUS_WRITE | STATUS=COMPLETED (BS) |
| `no_action_already_completed` | NO_ACTION | — |
| `action_old_date` | STATUS_WRITE | STATUS=COMPLETED4 |

## Complex handlers → dedicated v2 WFs (ported node-by-node)
1. `indoxV2H_find_link` — Search File + If-Found conditional writes.
2. `indoxV2H_check_from_office` — warehouse settings + search + write.
3. `indoxV2H_extract_shipment_ids` — mark + split + search-existing + link/create shipment rows.
4. `indoxV2H_link_documents` — BS-line linkage (loop/split/search/link/aggregate). Highest risk; port last.
5. `indoxV2H_select_invoice_values` — settings read + `Selection & Scoring Logic` + write.
6. `indoxV2H_update_status_double` — writer + `If id Match` branch.

## VERIFICATION STATUS (2026-07-02)
- ✅ **Decision-logic exact-clone PROVEN.** `node scripts/indox-v2-decide-test.mjs` runs v1's brain and
  v2's brain on 46 diverse fixtures → **identical ACTION on all 46** (byte-exact). Stack-free, <1s, CI-ready.
- ✅ **Structural fidelity.** 50/50 action outputs resolve; zero dangling refs; 3 blocks disjoint w/ zero
  cross-refs; driver `Switch1` rewired to the 3 collection calls; all 8 triggers + lock + loop + ACTION_LINES preserved.
- ✅ **Imports clean.** All 6 v2 WFs import into n8n, inactive, tagged `indox,indox-state-machine-v2`.
- ✅ **Action-layer node equivalence.** `node scripts/indox-v2-actions-test.mjs` → all **323 carried nodes
  byte-identical to v1** (type+params+creds+wiring). Verbatim clone by construction.
- ✅ **Action-layer runtime contract tests.** `bash scripts/indox-v2-contract-test.sh` → **6/6** representative
  actions across every class (STATUS_WRITE `mark_completed`, SINGLE_EFFECT `query_doc_date`/`figure_company_id`,
  FIELD_WRITE `update_company_doc_id`, COMPLEX-conditional `find_link`, BS `extract_balance_sheet`) run their
  REAL handler node-graph headlessly (throwaway n8n → shared PG) with leaf I/O mocked (writer→Set with identical
  mapping expressions, effects→canned Code), asserting the exact write payload. Proves boundary hand-off +
  switch routing + write-mapping actually execute. No external services.
- ⬜ **Full end-to-end parity (remaining).** Action collections are *verbatim node copies* (identical by
  construction), but a live doc has not yet been driven through v2 end-to-end. That needs the full data
  stack (supabase+apitools+drive+gmail) and is the final acceptance gate → run supervised, compare
  per-doc traces (`scripts/indox-doc-trace.py`) of v1 vs v2 via the `main_version` toggle.

Run the suite: `node scripts/indox-v2-decide-test.mjs`  (gate = per-case v1≡v2 parity; absolute fixtures
are v1-inherited/informational — some predate the current pipeline shape).

## HIGH-LOAD / BATCH ROBUSTNESS — `indoxV2BSHighLoad01` (2026-07-02)
Config-driven high-load test: seeds ONE BS with `lineCount` lines (+edge cases) → drives link (batch 50) →
COMPLETED → verifies. Battle-tests the classic batching complexes:
- **Completeness/order/integrity**: N lines → N distinct invoice rows, each line's amount on its OWN row
  (`first=101 last=600`) — no cross-batch mixing, no loss.
- **In-batch dedup**: 2 identical line ids → exactly 1 row.
- **Partial-error resilience**: malformed lines (null/missing id) **must not crash the batch**.
- Result at 500 lines: **✅ PASS, ~33s, batch 50**. Throughput sweet spot = batch **50–250** (~32–34s);
  a single giant batch (500) DEGRADES badly (don't). So `Loop Over Items19/18` stay at **50**.
- **BUG #3 FOUND & FIXED**: the link search's `SHORT_DOC_ID = …id.slice(-5)` had **no null-guard** (unlike
  the create writer) → one malformed line threw and aborted all 500. FIX: `Prepare Split` now **filters
  malformed lines** (`l && l.id!=null && String(l.id).trim()!==''`) so bad lines are skipped, valid ones all persist.
- **Parallelism model**: within one execution the link batches are **sequential** (n8n splitInBatches).
  Extraction parallelism is now handled by the pool below (see next section); link stays batch-50.

## PARALLEL BS EXTRACTION — `Extract via Webhook` HTTP node (2026-07-02) ⭐ NEW
The extract handler was the last serial bottleneck. Replaced `Loop Over Items8 → executeWorkflow(extractor,
mode="each")` with a single **HTTP Request node** in `indoxV2ActionsBS01` that fans out to the extractor's webhook.

**Why HTTP, not executeWorkflow** — empirically measured (fan→sleeper probe): `executeWorkflow` (any mode /
`waitForSubWorkflow`) runs sub-calls **serially, in-process** even in queue mode — 6× 3s subs took 28.4s, starts
spread 15s. `mode=each`+`wait=false` subs run in the parent process and die if it exits — NOT enqueued. The
**only** mechanism that distributes long extractions across the 2 workers is the extractor's **webhook**
(webhook-triggered executions ARE enqueued). So the node fires N concurrent HTTP → workers run extractions in parallel.

**Node** `Extract via Webhook` (`httpRequest` v4.2): `Action: Extract Balance Sheet1` → this node → `If Sucsess`
→ Builds → `Upsert (central)`. POST `http://n8n:5678/webhook/bs_ex_2_dev`, jsonBody
`{LINK, use_cache: !=='false', full_response:false}`, `onError: continueRegularOutput`. It fires **all input items
concurrently** (measured 15 docs in 6.2s vs ~43s serial). HTTP nodes auto-preserve `pairedItem`, so `Build`'s
`$('Action: Extract Balance Sheet1').item.json.ID` resolves without manual work.

**Auth = ONLY the cred, zero exposure** — the node attaches the existing `Incoming Documents [env-managed]`
credential (`azPhHBvOWaf9IsEA` = `${BS_WEBHOOK_USER}`/`${BS_WEBHOOK_PASS}`, blueprint line 91) directly. No redis,
no env read. (A Code-node pool was tried first but **can't** get the cred: the external task runner has no
`process` — `"process is not defined"` — `$env` is blocked, and `httpRequestWithAuthentication` is unsupported in
Code nodes. So a Code node can only get a secret via a data channel like redis; the HTTP node sidesteps that.)

**Bounded-5-concurrent via `Loop Over Items` (splitInBatches, batchSize=5)** wrapping the HTTP node — self-loop to
drain + `Extract via Webhook` as the **dead-end** processing branch (per the standard batch-loop pattern). Each wave
feeds the HTTP node **5 items which it fires CONCURRENTLY** (~2.5s ≈ one call), then the next wave — measured live:
15 docs = 3 waves of 5 (`wave1 start+0`, `wave2 +3655ms`, `wave3 +6715ms`, each 5 items concurrent). This is a hard
5-in-flight cap AND parallel — the goal the Code+redis pool was for, achieved with just the cred-attached HTTP node.
**n8n gotcha**: the HTTP node's own **"Batching" option IS serial** (batchSize=5 → 13.9s/5 docs) — do NOT use it;
bound via the splitInBatches loop instead, whose per-wave batch the node runs concurrently. (Earlier notes here
wrongly said the loop serializes — it was an aggregate-time misread; the extraction runs 5-concurrent per wave.)
`onError:continueRegularOutput` does not break the per-wave concurrency.

**Error isolation** — `onError: continueRegularOutput` routes a failed extraction (non-2xx) to the node's normal
output with `$json.error` set and no `success` → `If Sucsess` false → EXTRACTION_FAILED branch, other docs
unaffected. Also fixed a latent extractor bug: the no-binary path (`Code in JavaScript`, `{success:false}`) was a
dead-end with no respond node → hung the webhook; now wired → `API Response1` (200), so bad downloads respond fast.

**Proven** (`indoxV2BSExtractConc01`, config-driven docCount) — concurrent, capped by worker slots:
| docs | 1 | 5 | 10 | 15 | serial-equiv |
|---|---|---|---|---|---|
| node wall | 2.85s | 3.8s | 5.7s | 6.2s | ~43s |

All docs extract, no loss, order preserved. **Partial-error** (`indoxV2BSPartialErr01`): 5 good + 3 garbage-link →
5 extracted / 0 bad / 3 flagged, no crash. Single-doc lifecycle + 100% coverage + 500-line high-load all green.
`bs_ex_2_dev` webhook has zero other callers (feature-suite uses `bs_ex_2`); registers only on n8n **main restart**
(`import:workflow` deactivates → must reactivate + restart to re-register). **Note** driver passes docs mode="once"
by design — the node parallelizes WITHIN that execution; driver-level group-by-action re-fire is a later step.

**Layout**: 9 switch branches laid out as even rows (DY=300) in output order; each loop branch = `Action → Loop →
Build(offset up)`; batch loops self-loop to drain with a **dead-end** processing branch (the final upsert returns a
variable item count that would break the split if fed back — hence self-loop + separate process branch, per the
link-loop pattern). `When Called` sits by the switch (no long dangling edge); `Upsert (central)` centered.

## LINK SEARCH — direct indox-API call (2026-07-02) ⭐ NEW
The link branch's document search called `Execute Workflow1 → "Get Incoming Document"` (`indoxDocGet01`) — a
**dual-backend shim** (redis `data_backend` flag routes legacy Google-Sheets vs supabase). It DID work in supabase
mode (its SB branch = `GET_ALL → Call INDOX GETALL → indoxApiRouter01 → SB Match` client-side filter), but carried
a dead Sheets half. Replaced in `indoxV2ActionsBS01` with a direct call:
`Split Lines1 → GET_ALL Req → Call indox api (GET_ALL) → Match Existing → Join Search Results`.
- `GET_ALL Req` collapses N line-items → one `{INLINE_ACTION:'GET_ALL'}`; `Call indox api` = executeWorkflow →
  `indoxApiRouter01` (passthrough); `Match Existing` (Code) replicates `SB Match` **exactly** — per line, query
  `{COMPANY_ID, SHORT_DOC_ID = last-5 of line id}`, filter rows where every non-empty key matches, output
  `{...matches[0], filter, matches, matchCount}` (the shape `Join Search Results` zips onto each line by index).
- `Split Lines1` (splitOut on `BS_EXTRACTED_LINES.data.lines`, include allOtherFields) emits a **flat** key
  `"BS_EXTRACTED_LINES.data.lines"` = the single line object (probed) — so `Match Existing` reads `ln['BS_EXTRACTED_LINES.data.lines']`.
- Behavior-identical (still `GET_ALL` + client match — the supabase API has no server-side SEARCH action, only
  `GET_ALL`/`GET`-with-SQL). Verified: `Assert Link Branches` (create/update-existing/skip) + 500-line high-load
  both green. `Get Incoming Document` still used by 7 other WFs (v1 main, v2 GDoc/Driver…) — left intact, only the
  BS link path migrated off it. **Future opt**: a server-side filtered SEARCH (via `GET`+SQL) would avoid fetching
  all rows per link execution — the one remaining scale cost here.

## GDoc — BS treatment applied (2026-07-02) ⭐ NEW
`indoxV2ActionsGDoc01` (103 nodes, **26 handlers**) got the same passes as BS:
- **Parallel invoice extraction**: `Loop Over Items28` set to **batch=5**; replaced `Call 'invoice Extractor' (execWF
  mode=each, serial)` with `Extract Invoice via Webhook` (HTTP node → `invoice_extractor` webhook, same cred
  `azPhHBvOWaf9IsEA`, `onError:continueRegularOutput`). Invoice extractor uses the SAME postgres `ai_extraction_cache`
  (`invoice:<md5>`), so testable by priming. Proven live: **3 waves of 5** (bounded-5 concurrent). Build reads
  `$json.data.AI_*` + `$('Action…').item.json.ID` (pairedItem preserved). NOTE the other heavy mode=each ops
  (`Search File`/find_link, apitools `Upload`, warehouse `Search`, the `Query *` sub-WFs) have **no webhook** — would
  each need one added to parallelize; deferred.
- **Direct-API shipment search**: replaced `Search Existing Shipment1` (`Get Incoming Document` shim, **mode=each = one
  GET_ALL per shipment**) with `GET_ALL Req → Call indox api (GET_ALL) → Match Existing Shipment` (one GET_ALL + local
  match; query `{COMPANY_ID, SHORT_DOC_ID=last5 of shipment id, TYPE:'SHIPMENT'}`). Feeds `Join Search Results2` unchanged.
- **Centralized find_link writes**: `Build SEARCH_IN_DRIVE_COMPLETED` + `Build LINK FOUND` (both same-line, ID=current
  doc) repointed from local Upsert nodes → shared `Upsert (central)` (20 feeders now). Cross-row writes (shipment/invoice
  Create/Mark/Update) correctly KEPT local (multi-write handlers, per BS principle).
- **Test** — ONE `indoxV2GDocTest01` "indox-v2 GDoc E2E Test", **exact same shape as `indoxV2BSTest01`**: Config →
  Capture-off → Cleanup → Download→Crypto→Prime invoice cache → `Execute Flows` fan-out to **4 phases** → `🏁 Test Summary`.
  Phases: **(1) FULL LIFECYCLE (timed)** — seed invoice doc → GET→Decide→Act loop → `COMPLETED` (~38s, 14 real actions:
  get_api_tools_id→query_invoice_id→query_doc_date→query_doc_total→query_purchase_id→query_shipment_id→
  extract_invoice(cached)→update_company_doc_id→get_short_doc_id→update_name→check_from_office→extract_shipment_ids→
  select_invoice_values→mark_completed); (2) parallel invoice extraction (15/15, bounded-5); (3) 14 pure-write handler
  coverage (loop); (4) partial-error isolation (5 good + 3 garbage → 5/0). Result: **✅ ALL TESTS PASS (4/4)**.
  The lifecycle exercises the **real external integrations** (apitools OCR, all `Query *` sub-WFs, Drive rename, warehouse
  search, sheets `select_invoice_values`) — they WORK; AI extraction is cache-primed and `priority_sync` is gated OFF by
  the `activePrioritySync=false` setting. (Superseded the 3 separate GDoc test WFs + the standalone LC probe.)
- **Layout**: all **26 branch heads** even-spaced (DY=300) + X-aligned in switch-output order (per-branch Y-shift,
  subtrees follow, `Upsert (central)` excluded/centered); switch + `When Called` to the left. All 3 tests green after.

## BUGS FOUND & FIXED via BS test (2026-07-02) — v2 defects the test caught
1. **`includeOtherFields: True` on centralized `Build` nodes** → a create-row (link_documents opening an
   invoice per BS line) passed the BS doc's *inherited* `ID` on the wire → the upsert UPDATED the BS doc
   (mutating it to `TYPE=INVOICE`) instead of creating a new row; all lines collapsed onto it. FIX:
   `includeOtherFields: False` on all 43 Build nodes (matches v1's `defineBelow` = only mapped fields).
2. **`indoxV2Upsert01` wrapper used `$('When Called').item` (singular)** in `Restore Payload`/`Capture Echo`
   → when called with a BATCH (link sends N line-creates in one call), only 1 item reached `lmcZ`. FIX:
   `return $('When Called').all();`. Now N BS lines open as N separate INVOICE rows, BS doc untouched.
Verified: BS doc stays `BALANCE_SHEET`+COMPLETED (no LINKED_BS/COMPANY_DOC_ID); both lines → INVOICE rows
with `LINKED_BS`. LESSON: the wrapper/Build must be batch-safe; single-item assumptions break link_documents.

## Centralized write path (2026-07-02) — `indoxV2Upsert01`
Every v2 write now routes through ONE wrapper `indoxV2Upsert01` (= "centralize the upsert" + the single
test mock point). Each handler's writer `executeWorkflow(lmcZ, mapping)` became a **`Build: <name>` Set node**
(identical mapping expressions) → the wrapper. Single-write actions funnel into **one shared `Upsert (central)`
node per collection**; the 4 multi-write handlers (`find_link`, `extract_shipment_ids`, `extract_balance_sheet`,
`link_documents`) keep local `Upsert: <name>` calls (can't collapse — a node can't run twice / row fan-outs).
- **Wrapper behaviour:** reads redis flag `n8n.indox.test_capture`; if set → record payload to
  `n8n.indox.test_capture:<ID>:<exec>:<run>:<item>` and echo (skip write); else → **delegate to the real
  `lmcZ`** (passthrough). Live v1/`lmcZ` untouched; flag default off.
- **Verified stack-free** (`node scripts/indox-v2-actions-test.mjs`): 280 nodes byte-identical to v1 +
  **43 Build nodes carry the exact v1 write mapping**, wiring preserved (writer→Build rename normalized),
  0 drift. All import clean. Behaviour-preserving; no longer byte-verbatim (deliberate, user-approved).
- **Full-integration test (the goal):** set the capture flag, run the REAL collection/driver with the REAL
  stack (apitools/Gemini/Drive/supabase), read captured payloads from redis, assert. Mocks ONLY the upsert;
  everything else real. No copy workflows. ⬜ pending full-stack bring-up.

## BS FULL-LIFECYCLE test — DECLARED IN n8n as `indoxV2BSTest01` ("indox-v2 BS E2E Test")
ONE end-to-end test, **fully declared as an n8n workflow** (run from the UI, manual trigger). It exercises
the **full BS lifecycle incl. the real `extract_balance_sheet` action**, using a **pre-seeded cache** so the
AI path is tested without live Gemini. Flow (17 nodes):
`Capture Flag OFF → Cleanup Prior (pg: doc+children) → Seed BS Doc (indox api UPSERT: BALANCE_SHEET, real
Drive LINK, COMPANY resolved, NO lines, BS_EXTRACTION_USE_CACHE=true) → PRIME CACHE [Set LINK → Download
(drive api) → Crypto(binary)=cached_input_key → Prime Cache: UPSERT ai_extraction_cache 'bs:<hash>' =
fixture {success,data:{lines,summary,documentDate}}] → [loop: GET (indox api) → Decide (indoxV2Decide01) →
Is No-Action? → (no) Act (indoxV2ActionsBS01) → back to GET] → (yes) Assert COMPLETED → PASS/FAIL`.
Verified Decide sequence: **`extract_balance_sheet → link_documents → mark_completed →
no_action_already_completed`**, ends **✅ PASS** (`STATUS=COMPLETED, BS_LINK_DONE=true`).
- **Cache mechanism proven:** `extract_balance_sheet` downloads the file, `Crypto`-hashes it → the primed
  `ai_extraction_cache` row is HIT (KVStorage lookup `bs:<hash>`) → returns the fixture, **no Gemini call**.
  Cache table cred = `yY8FYvp6Kz86pt2t`. (The real cached extraction for that demo file is overwritten by the
  fixture — acceptable test side-effect on dev/demo data.)
- Writes are real (wrapper→`lmcZ`, capture flag off). `link_documents` create-vs-link is v1 behaviour (kept),
  so exact child-row count isn't asserted; cleanup deletes doc+children (LINKED_BS/SOURCE_ID) each run.
- Gotchas handled: router calls = **Set→executeWorkflow(passthrough)** (router trigger is passthrough);
  **alwaysOutputData** on GET/Download (0-row/empty output otherwise kills the branch).

### 100% BS NODE coverage (empirically measured, 43/43)
The test is config-driven (`Config` JS node) with 3 parallel flows fanned from `Execute Flows`:
- **§3 Lifecycle** (primed `{success:true}` cache): extract→link→complete→COMPLETED. Now seeds **2 pre-existing
  invoices** so `link_documents` hits ALL branches — **create** (new line→new INVOICE row), **update-existing**
  (line matches an unlinked invoice→link it, no dup), **skip** (line matches an already-exactly-linked invoice).
  `Assert Link Branches` verifies each + that the BS doc stays untouched.
- **§3b Extract-FAILURE** (primed `{success:false}` for a 2nd Drive file): extractor returns failure → hits the
  extract-fail writer → `update_status_extraction_failed` → EXTRACTION_FAILED.
- **§4 Coverage loop**: every remaining handler incl. `no_action_already_completed`.
Coverage is **measured**: scan the BS collection's saved sub-executions (`execution_data`) for each node name →
**43/43 = 100%**. Dead `action_old_date` handler was **pruned** from BS + GDoc (3 nodes each). Two v2 bugs the
test caught are fixed (see top: includeOtherFields, wrapper `.all()`).

### 100% BS handler coverage (28 nodes total)
After the lifecycle, a **coverage loop** (splitInBatches over 5 cases) seeds each remaining action's
precondition state → GET → Decide → Act → batch-verify DB state. Covers all **9 reachable** BS handlers:
lifecycle 4 + `update_status_missing_company`, `no_action_awaiting_company_id`, `restart_balance_sheet`,
`update_status_extraction_failed`, `no_action_extraction_failed`. It drives via **Decide** (proves
Decide→handler for each), then asserts final STATUS per doc. **`action_old_date` is the only uncovered
BS switch output — it's DEAD** (the brain emits `update_status_old_doc`/`no_action_old_date`, both Global;
never `action_old_date`). So 9/9 live handlers = 100%; consider deleting the dead `action_old_date` handler.

## Testability
- **Decide (unit):** the existing fixture table (`Determine Action Tests`) feeds the single Decide code
  node → assertions. Runs in CI, no side effects. One source of truth (delete v1's 2 orphan copies
  `Determine Action1`, `1. Determine Action1`).
- **Handlers (contract):** each is `executeWorkflow`-callable → feed a fixture doc, assert declared
  `writes` land and the row unlocks. One test per registry row.
- **Executor (interpreter):** table-drive over all SINGLE_EFFECT/STATUS_WRITE rows; assert every one
  maps params, writes its fields, appends ACTION_LOG, unlocks (catches the historic lock-leak class).
- **Whole machine (golden/replay):** run recorded docs through v1 and v2; diff per-doc traces from
  `scripts/indox-doc-trace.py`. **Identical action sequence to COMPLETED = proven parity.**

## Swap mechanism
A redis toggle `n8n.indox.main_version` (`v1`* | `v2`) read by the line-change poll / pg-trigger
dispatch (in `indoxApiSupabase01`) selects which driver to `executeWorkflow`. Default v1 until parity
proven. No destructive change — flip the key to swap, flip back to roll back.

## Build order (each step pushed + verified; publish-gate aware)
1. `Decide` WF (anchor) + wire the fixture tests. ← testable immediately.
2. `action_registry` map + `Execute Action` generic executor (NO_ACTION/STATUS/FIELD/SINGLE_EFFECT).
3. Port the 6 COMPLEX handler WFs.
4. `Driver` WF (triggers + lock + loop + dispatch) behind `main_version` toggle.
5. Tag everything `indox-state-machine-v2`; push inactive; live parity trace vs v1; then swap.

## Key IDs
- v1 main: `sv5xxRBVGxvV0kXx`. Writer: `indoxDocBatchUpsert01`. GET: `indoxDocGet01`. Lock: `processLock01`.
- Effects: figure company `indoxV2FigureCompanyId01`, figure type `indoxV2FigureDocType01`, settings `indoxSettings01`,
  apitools upload `indoxV2UploadApiTools01`, queries `indoxV2QueryInvoiceId01`/`indoxV2QueryDocDate01`/`indoxV2QueryTotalAmt01`/
  `indoxV2QueryPurchaseId01`/`indoxV2QueryShipmentId01`, invoice AI `indoxV2ExtractInvoiceGemini01`, BS AI `indoxV2ExtractBalanceSheet01`,
  drive `driveApi01`, warehouse search `indoxV2SearchWarehouse01`, file search `indoxV2SearchFile01`.
- v2 (new): `indoxV2Decide01`, `indoxV2Driver01`, `indoxV2Exec01`, `indoxV2H_*`.
</content>
