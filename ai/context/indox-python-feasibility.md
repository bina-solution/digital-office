# Can INDOX's automation layer leave n8n for Python? — feasibility and plan (DGO-233)

The owner, 2026-08-10: «the existing app is legacy i want complete from n8n workflow full zero shot transfermation
resutling 1:1 functionality or better.»

The item asks whether the whole INDOX automation layer (sync, the state machine, the API and the data layer) can be
re-implemented as clean Python with 1:1 or better behaviour, replacing n8n. It wants a feasibility answer and then a
plan.

Written 2026-11-10 from measurements, not estimates. Every one of the 70 workflows in `apps/indox/blueprint/n8n/`
was compiled with the push toolchain (`apps/n8n/tooling/wrap.mjs`, on mac-dgo), and the numbers below are counted
from the compiled JSON. INDOX is at rest by the owner's decision of 2026-10-22, so this is the answer and the plan,
not a start.

## The answer

**Yes: feasible, at 1:1 behaviour or better. But not "zero-shot".**

The logic is portable:
- 10,837 lines of JavaScript in Code nodes;
- SQL in Postgres nodes;
- HTTP calls.

None of it depends on anything only n8n can do. What n8n really provides is a runtime around that logic:
- a queue of workers;
- retries;
- an error workflow;
- a per-run execution record people click through;
- schedules and webhooks;
- a credential store.

Each of those has a known Python replacement in this office, and most already exist:
- the BFF;
- redis;
- any-concurrency's spans;
- flow.v1;
- the connections vault.

A one-shot rewrite would throw away the one asset that makes 1:1 provable: the twenty test suites. They pin today's
behaviour, and n8n runs them. So the transformation is a strangler. Each workflow is replaced behind the door it
already has, runs in shadow beside the n8n original with the decisions compared, and is cut over only when the
suite that pins it is green on the Python side.

## What there is to move (measured)

| | workflows | nodes | Code nodes | JS lines |
|---|---|---|---|---|
| production | 50 | 899 | — | 10,837 |
| test suites (sealed, E2E, demo) | 20 | 536 | — | 2,956 |
| **all** | **70** | **1,435** | **408** (407 with JavaScript) | **13,793** |

Node types across all 70: code 408, executeWorkflow 253, postgres 138, set 102, noOp 89, if 80, splitInBatches 56,
executeWorkflowTrigger 44, respondToWebhook 40, webhook 38, httpRequest 32, switch 32, redis 15, stopAndError 8.

Triggers:
- 44 sub-workflow entries;
- 38 webhooks;
- 4 schedules (`indox01`'s tick and three others);
- 22 manual triggers, all in tests.

The heaviest production workflows (nodes / JS lines):

| workflow | nodes | JS lines |
|---|---|---|
| `indoxV2ActionsGlobal01` | 63 | 1,674 |
| `indoxApi01` | 40 | 1,248 |
| `indoxV2ActionsInv01` | 63 | 708 |
| `indoxV2ActionsShip01` | 58 | 540 |
| `indoxSettings01` | 63 | 510 |
| `indoxV2ExtractInvoiceGemini01` | 59 | 467 |
| `indoxV2ExtractBalanceSheet01` | 57 | 399 |
| `indoxV2ActionsBS01` | 47 | 289 |

**Already Python:** the BFF, `apps/indox/app/incoming_documents/`. It has 13,768 lines (API, backends with the
Supabase transport, core models, the poller) and 2,403 lines of tests. Its `Query` / `OrderClause` / repo layer is
the data layer an n8n-free INDOX needs, and it already serves the console.

## What n8n gives, and what replaces it

| n8n gives | how INDOX uses it (measured) | the Python replacement |
|---|---|---|
| a worker queue (queue mode, concurrency) | every `… Each` call is "no wait — n8n's worker pool is the backpressure" | a redis-backed job queue with a bounded worker pool, one per lane (sync, drain, decide, actions) |
| retries | 90 nodes `retryOnFail` | a retry decorator on the HTTP and DB clients, with the same counts and waits per call site, read from the compiled JSON so nothing is guessed |
| the error workflow | 63 workflows set `errorWorkflow` (errorHandler01) | one exception boundary per job, writing the same ERROR / lock release that errorHandler01 writes today |
| execution order v1 (canvas height = order, depth-first) | all 70; G45 exists because of it | plain sequential code: the order becomes explicit, and G45's whole class of bug disappears |
| `splitInBatches` loops | 56 | `for batch in chunks(rows, n)` with the same n (5000 driver lines, 25 priority calls, …) |
| continue-on-error + a reader of failures | 154 nodes continue on error (139 on the regular output, 15 on an error output); three readers turn some of that back into a failed run (`Assert Discovered`, `Verify Delivery`, `Verify Dispatch`) | collected results, then one raise: the same verdict without the indirection, and without the cases no reader sees (a fire-and-forget delivery that fails while running) |
| sub-workflow calls | 253 | function calls; a "workflow" becomes a module with one entry function |
| cross-node references `$('Node')` | 816 in 467 nodes (514 of them in 256 production nodes) | ordinary variables. This is the riskiest part of the port: implicit data flow made explicit, so it is ported with the suite running |
| execution records people click | `$execution.customData` outlines in 15 nodes; the owner's habit of execution links (DGO-293) | a span per job and step on any-concurrency, plus flow.v1 events: an execution page per run, with the same outline strings |
| schedules | 4 schedule triggers | the scheduler already decides dueness in SQL (`indox01`'s plan); a Python tick reads the same table |
| webhooks | 38, most of them suite lanes and the manage door | Flask routes on the BFF, which already owns the INDOX HTTP surface |
| credentials | Postgres, Gemini, apitools, Drive, Gmail through n8n's store | the connections vault (`connections` app), already the office's one secret store |
| the visual editor | how lanes were debugged | gone. The span pages and the suites must be good enough that nobody misses it (the main cost the owner pays) |

## The plan

A strangler, in this order. Each phase is shadowed and pinned by a suite before cutover:

| # | what moves | why this order | done when |
|---|---|---|---|
| 0 | tooling: a compiled-JSON → Python reference extractor (retry counts, batch sizes, SQL text, branch tables) and a shadow harness that runs an n8n workflow and its Python port on the same input and diffs the outputs | every later phase uses it | a diff of `indoxV2Decide01` against itself is empty |
| 1 | **decide**: `indoxV2Decide01` plus the per-type decides (pure JS over row data) | pure functions, no I/O: the easiest 1:1, and the heart of the state machine | the decide matrices (`indoxV2DecideTest01`, the Sealed* matrices) are green on Python, and a shadow week shows 0 diverging decisions on live rows |
| 2 | **the data layer**: `indoxApi01` (1,248 JS lines) into the BFF's existing repo layer | everything calls it; the BFF already has most of it | `indoxApi01`'s callers talk to the BFF route; the suites stay green |
| 3 | **the driver and the router**: `indoxV2BaseDrain01`, `indoxV2Driver01`, `indoxV2ActionRouter01` | orchestration only, once decide and data are Python | the driver lanes and `indoxV2PipelineTest01` are green; G45's class no longer applies |
| 4 | **the actions**: Global, then Inv / Ship / BS / GDoc, and the extraction arms | the bulk of the code (≈4,000 JS lines), each type alone | each type's Sealed suite is green on Python, cut over type by type |
| 5 | **sync**: `syncV3Main0001`, `syncRun01`, discover / deliver, `syncLedgerApi01` | SQL-heavy and already ledger-shaped (sync_ledger is the contract) | `syncItemApiTest01`, `syncFullTest01` and the source suites are green |
| 6 | **scheduler and settings**: `indox01`, `indoxSettings01` | last, so n8n can be switched off in one step | n8n carries no INDOX workflow; the INDOX app no longer `wants` workflow |

The phase costs follow from the table above. Decide and data together are about a quarter of the JS; actions are
the largest single phase. The suites already exist; only the shadow harness is new.

**Risks, named:**
1. The 816 cross-node references (514 in production) hide data flow. Each one is ported with its suite running, never by reading alone.
2. n8n's depth-first order sometimes carries meaning (G45's 28 loops). Phase 3 must keep the effective order, so
   the shadow diff compares sequences, not only end states.
3. The owner and the agents lose the editor view. Phase 0 must give spans and execution links good enough before
   phase 3 starts (DGO-293 is the same need on n8n today).
4. INDOX is at rest (2026-10-22). Starting this is the owner's call; the plan costs nothing until then.

## What this answers on the item

Feasible: yes, 1:1 or better, by a shadowed strangler in six phases, with the existing suites as the oracle.
Zero-shot: no. The plan above replaces it.
