# Lane D — n8n consolidation and dead code (2026-08-06)

Owner items E1, E2, E4, E8 from `FINAL-PARALLEL-PLAN-2026-08-06.md`, plus the retry-column
decision and the 66 → 38 consolidation. Every number here was measured against the running
stack on 2026-08-06, not read off a plan. Where the deploy freeze prevented live verification
this document says **not verified — needs deploy** rather than implying it passed.

---

## 0. Two measurement traps that invalidate earlier reports

**`$?` through `wsl bash -lc` is structurally unreliable on this host**, and so are shell
variables inside loops:

```
wsl bash -lc 'exit 7'                       -> rc=7   correct
wsl bash -lc 'false; echo $?'               -> 0      WRONG
wsl bash -lc 'python3 a-failing-gate.py; echo "rc=$?"'
        -> prints the gate's own FAIL report, then `rc=` (empty)
wsl bash -lc 'for w in a b; do cmd $w; done' -> cmd runs with an EMPTY argument
```

The first cost five gates being reported PASS when they had not been run meaningfully. The
second silently ran a deactivation loop against no workflow at all. **Use
`scripts/refactor/run-gates.py`** — it reads `subprocess.CompletedProcess.returncode` and
`--self-test` proves the status is real on this host. Do not write a second harness.

**`PATCH /rest/workflows/:id {"active": false}` returns HTTP 200 and does nothing.** Details in
`platform-os-consolidation.md` § "The defect class this repo keeps producing". Deactivate with
`docker exec <n8n> n8n unpublish:workflow --id=<id>` and read `workflow_entity.active` back from
Postgres. `tmp/ld_deactivate.py` does this and reports FAILED when the DB has not moved.

---

## 1. `indoxV2GenerateThumbnail01` never existed (E1/E2)

The owner asked to remove it. It is not in `apps/*/blueprint/n8n/`, not in `legacy/`, not in the
live n8n DB (82 workflows enumerated), and `git log --all -- "*Thumbnail*"` is **empty** — it was
never committed under that name. The intent behind the request was nonetheless implemented: the
`generate_thumbnail` action is gone from `indoxV2ActionsGlobal01`, replaced by a `Get Doc Thumbnail`
call into `indoxV2UploadApiTools01`, which renders the preview in parallel with the OCR upload.

Stale comments naming the non-existent workflow were corrected in
`apps/indox/app/incoming_documents/api/__init__.py` (×2) and `apps/indox/blueprint/fixtures/schema.sql`.

### 1.1 The thumbnail feature does not work for the existing corpus — OPEN

| measure | value |
|---|---|
| `incoming_documents` rows | 6,318 |
| rows with `API_TOOLS_ID` (uploaded to apitools) | 5,775 |
| rows with a `THUMBNAIL` | **17** |

`indoxV2UploadApiTools01` renders a thumbnail only on the path where it actually downloads bytes.
On an apitools `/docExists` hash hit it short-circuits `Check HASH → If Exists(true) → Return`
and never downloads — so **a document whose bytes were already uploaded can never acquire a
thumbnail**, which is every document that predates the feature. This is a field that looks
functional and is not.

**Fix, shaped as the owner asked (via `ACTION_RESTART`, not a bespoke backfill).** The state
machine already re-runs an action when its `*_COMPLETED` flag is unset; the upload workflow just
has to do the minimum work when the only missing thing is the preview:

1. `Start` gains an input `NEED_THUMBNAIL` (additive — no existing input moves).
2. `If Exists`(true) no longer goes straight to `Return`. It goes to a new
   `If Needs Thumbnail`: false → `Return` (today's zero-work behaviour, unchanged);
   true → `Download file3`.
3. `Render Thumbnail` becomes reachable from that path **without** `Document OCR2` — the hash
   already exists at apitools, so the OCR upload stays skipped. Hash-check and thumbnail become
   independent decisions over the same bytes.
4. `indoxV2ActionsGlobal01`'s `Get Doc Thumbnail` passes
   `NEED_THUMBNAIL = {{ !$json.THUMBNAIL }}`; clearing `THUMBNAIL_COMPLETED` on a row is then
   enough to make `ACTION_RESTART` fill it in, like any other state change.

**Not implemented.** This changes the cache-hit path of the single hottest workflow in the system
(every action calls it) and cannot be exercised while the push is frozen. Specified here for
review; do not hand-edit it blind.

---

## 2. Never re-upload, always hash-check (E4) — half exists, as the owner suspected

`Switch` in `indoxV2UploadApiTools01` has four branches:

| # | key | guard | behaviour |
|---|---|---|---|
| 0 | `hash` | `!!HASH && !binary` | → `Check HASH` (apitools `/docExists`) → `If Exists` true → `Return`. **Correct: no re-upload.** |
| 1 | `link` | `!!LINK && !binary` | → `Download file3` → `Document OCR2`. **No hash check.** |
| 2 | `binary` | `!!binary` | → `Binary` → `Document OCR2`. **No hash check.** |
| 3 | fallback | — | `WRONG INPUT` |

**`COMPANY_ID → Upload OR Get API_TOOLS_ID` is already satisfied on branch 0, and more directly
than the owner expected: `API_TOOLS_ID` *is* an md5.** apitools computes
`file_hash = md5(file_content)` (`apps/apitools/src/api/ocr_api.py:163`) and `/docExists` is keyed
on exactly that.

**But there are TWO md5s and they are not interchangeable.** Another lane measured Drive's
`md5Checksum` disagreeing with apitools' `file_hash` on **725 of 3,092 rows**, with the stored
`HASH` matching the *current Drive bytes*. So hash-as-identity must name a primary rather than treat
them as one value:

| value | means | authoritative for |
|---|---|---|
| apitools `file_hash` (= `API_TOOLS_ID`) | md5 of the bytes **apitools received and stored** | `/docExists`, OCR cache, "have we processed this?" |
| Drive `md5Checksum` | md5 of the bytes **currently in Drive** | change detection — "has the source been replaced since we ingested it?" |

A disagreement is not corruption; it is the legitimate signal that the source file changed after
ingestion. Feeding a Drive md5 into `/docExists` would miss the cache and force a re-upload — the
exact behaviour E4 asks us to eliminate. **`Check HASH` must be fed `API_TOOLS_ID`** (or a `HASH`
column defined as "the apitools hash"), never a freshly-read Drive checksum. Any future
"reconcile hashes" job should treat a mismatch as *re-ingest this document*, not as *repair the row*.

**The residual gap** is branches 1 and 2, which upload unconditionally. Note the true cost is
smaller than "re-upload" suggests: `/documentOcr` caches on the same hash (`OcrObject.from_file_path
(..., cache=True)`), so a repeat costs a wasted download + multipart POST, not a re-OCR.

**Fix:** on branches 1 and 2, once bytes are in hand, compute `md5` and call `/docExists`; on a hit,
skip `Document OCR2` and return that `file_id`. **Must be landed together with §1.1** — a naive
short-circuit here would bypass `Render Thumbnail` too and make the thumbnail gap worse. Not
implemented for the same reason as §1.1: unverifiable during the freeze.

---

## 3. `sG9bU0ER2yVitKXR` "zz-scratch-gateway-probe (delete me)" — retired

3 nodes: webhook `gw-test-probe-8f21` → unwrap → `executeWorkflow(indoxDataGateway01)`. Created
2026-08-05 22:43, three executions at 22:44, none since. No blueprint file anywhere (DB-only, so
G44/G38 could never have seen it), no workflow references its id, nothing in the repo references
its webhook path.

Backed up to `tmp/lane-d-backups/sG9bU0ER2yVitKXR.json`, then deactivated. **Verified in Postgres,
not from the API response:** `active = f`, and its `webhook_entity` row is gone — the live route is
retired. The row itself was deliberately **not deleted**; deactivation removes the risk and a
destructive production delete is the owner's call. `tmp/ld_delete_probe.sh delete` is ready.

---

## 4. Active test workflows (D4) — 2 deactivated, 6 deliberately left alone

The eight are exactly the `active` blueprints tagged `lifecycle:test`, excluding `ciHelloWebhook01`
(the CI probe, which must be active) and three mis-tagged GWA MCP servers.

**Deactivated** (blueprint + live DB, verified in `workflow_entity`):

| id | why safe |
|---|---|
| `indoxV2TestFixtures01` | sub-workflow (`executeWorkflowTrigger`); `executeWorkflow` callers ignore `active` |
| `whatsappSendDoc01` | `manualTrigger`-only, no webhook; this was G44's last check-1 offender |

*Caveat:* `n8n unpublish:workflow` prints *"Changes will not take effect if n8n is running"*. The DB
is correct; the running process keeps its in-memory registration until restart. **Not verified in
the running instance — needs an n8n restart.**

**NOT deactivated — doing so would break the E2E harness:**
`indoxV2GDocTest01`, `indoxV2PipelineTest01`, `mailOrgTest00001`, `syncV3FullTest01`,
`syncV3KernelTest01`, `syncV3SourcesTest01`. Each is driven per-lane through its **production
webhook** by `apps/indox/hooks/test.py:431` (`POST /webhook/<lane-path>`) and by `_run_one_lane()`
in `apps/indox/app/incoming_documents/api/__init__.py:767` — the product's own test-run API. A
production webhook exists only while the workflow is active, so deactivating 404s both callers and
breaks Lane E. Converting those six to `POST /rest/workflows/:id/run` (what `run_suite` already
uses) is a real change to `test.py` plus the indox API and belongs in its own task.

### 4.1 G44 extended — it was catching 1 of 8

G44 asked only "is there a node that can activate this?". Seven of the eight carry a `webhook`
beside their `manualTrigger`, so they were structurally invisible to it and the gate read green.
A second, independent check now keys off the `lifecycle:test` tag rather than trigger shape:
an active `lifecycle:test` blueprint fails unless it is on `ACTIVE_TEST_ALLOWLIST` **with a reason**.
The six above are allowlisted pointing at the conversion task; the three MCP servers are allowlisted
as MIS-TAGGED (retag `role:api`, do not deactivate). Self-test 15/15; gate green over 83 blueprints.

---

## 5. `NEXT_RETRY_AT` / `RETRY_COUNT` — "zero writer nodes" is **wrong**

> **Correction, appended after re-measuring on the fresh VM (2026-08-06, later).** An earlier
> revision of this section said the writer "has never once taken effect". That was true of the
> sample I had (0 stamps across 6,318 rows) and is now **falsified**: `doc_mshcuhavqopu60` carries
> `RETRY_COUNT=1`, `NEXT_RETRY_AT=+5min` (matching the `5 × 3^0` backoff exactly) and
> `ERROR='action failed @exec 137432'`. So the mechanism is **alive but vanishingly rare** — 1 row
> in 6,341 — not dead. The root cause below is unchanged and explains the rarity; only the word
> "never" was wrong. Recording the correction rather than editing it away, because "never" would
> have justified deleting the columns and that would have been the wrong call.

**The feature is fully implemented end to end and fires on a tiny fraction of the failures it
was built for.**

| component | where | status |
|---|---|---|
| writer | `platform-base/n8n/workflows/errorHandler01.json` → `Backoff + Dead-letter` | exists; increments `RETRY_COUNT`, sets `NEXT_RETRY_AT` with exponential backoff (`5 × 3^n` min), terminalizes to `NEEDS_REVIEW` at 5 |
| reader | `indoxApiSupabase01.json:520` — the IN_PROGRESS driver query gates on `("NEXT_RETRY_AT" is null or <= now())` | exists |
| reader | `indoxApiSupabase01.json:606` — stalled-row auto-terminalizer | exists |
| UI | `DocumentDetailPage.tsx:237-238` — renders "ניסיונות" and "ניסיון חוזר הבא" | exists |

Measured:

| measure | value |
|---|---|
| `errorHandler01` executions | **6,047** (2,714 success / 1,482 error / 1,365 crashed) |
| workflows declaring `errorWorkflow: errorHandler01` | 67 of 83 |
| rows with `RETRY_COUNT > 0` | **1** of 6,341 |
| rows with `NEXT_RETRY_AT` set | **1** of 6,341 |
| rows carrying the writer's own `ERROR` stamp `'action failed @exec%'` | **1** of 6,341 |
| rows with `ITERATION_COUNT` set (a *different* counter — do not conflate) | 6 of 6,341 |

The stamp count is the decisive measure: the `Backoff + Dead-letter` UPDATE writes a distinctive
`ERROR` string, so its footprint is directly countable, and it has touched **one** row against
6,047 errorHandler01 dispatches — roughly 0.02%.

**Root cause — an execution-id scoping mismatch.** The chain is
`Error Trigger → Get Lock Map → If Has Lock → Backoff + Dead-letter`. `Get Lock Map` is a Redis GET
of `n8n.exec.{{ $json.execution.id }}.docmap`, where `$json.execution.id` is **the failing
execution's** id. The only writer of that key is `indoxV2Driver01`'s `Lock Map Set`, keyed by
`{{ $execution.id }}` — **the driver's own execution id**, TTL 20 min. Almost every failure happens
inside a *sub-workflow* execution, which has its own id, so the GET misses, `If Has Lock` takes the
false branch, and the UPDATE never runs. The document id the retry was meant to be scheduled for is
never recovered.

### 5a. Re-measured on the fresh VM — the handler SUCCEEDS and does nothing

`Process Document` now measures **30.8% success** (143/464 over 3h), failures burning 460–480 s of a
600 s timeout against a 74 s median success. That makes a working backoff worth far more than it
looked. So the mechanism was re-measured on the fresh DB:

| errorHandler01 executions | count |
|---|---|
| **success** | **1,596** |
| crashed | 99 |
| error | 56 |

**All 1,596 successful runs end at the same node index.** The handler is not dying — it runs to
completion, finds no lock, takes the `If Has Lock` false branch, and exits having written nothing.
91% of dispatches are a successful no-op. (This *is* the repo's signature defect, in the component
whose job is to notice failures.)

### 5b. Why it cannot be fixed in one file — and the exact fix

I checked for a cheaper route and there isn't one:

* `execution_entity` has **no `parentExecutionId`** column (13 columns, verified) — n8n does not
  record sub-workflow ancestry in a form a workflow can query.
* `execution_metadata` **does** carry an `ids` key holding the very document ids we need
  (`["gdt_pe_7","gdt_pe_8",...]`, 475 executions) — but it is written by an `executionData` node in
  **`indoxV2Driver01` only** (476 of 476), so it is keyed by the *driver's* execution id and carries
  exactly the same blind spot as the Redis key.

So the doc id genuinely is not recoverable from a child execution today. The fix must put it there:

> **Each sub-workflow writes the lock map under its OWN execution id at entry.** One Redis `set`
> node immediately after each `executeWorkflowTrigger` that receives an `ID`:
> key `=n8n.exec.{{ $execution.id }}.docmap`, value `={{ $json.ID }}`, TTL 1200 s — identical
> parameters to `indoxV2Driver01`'s existing `Lock Map Set`. `errorHandler01` then needs **no
> change at all**: its `Get Lock Map` starts resolving because the key now exists under the id the
> Error Trigger actually reports.

Priority order (highest failure volume first): `indoxV2ActionsGlobal01`, `indoxV2ActionsGDoc01`,
`indoxV2ActionsShip01`, `indoxV2ActionsBS01`, then `indoxProcessDocument01`,
`indoxV2FigureCompanyId01`, `indoxV2UploadApiTools01`.

**Blocked on the fence:** the four highest-value targets are the `indoxV2Actions*` files owned by the
extraction lane. This is additive (one node, no connection rewiring, no switch indices touched) but
must be sequenced through the coordinator, same protocol as §1.1.

**Do not** attempt a fallback that guesses the document from workflow id + timestamp. Writing a retry
against the wrong document is worse than writing none.

### 5c. STOP — the spec in §5b is UNSAFE for the four `indoxV2Actions*` files. Retracted.

The fence was lifted to build §5b. Surveying the targets before writing showed the spec violates its
own final rule, so it was **not built**. Two facts kill it:

* `indoxV2Driver01`'s four `Call indox-v2 Actions — *` nodes have **`mode: None`** — n8n's default,
  *"Run once with ALL items"*. The action workflows receive a **batch** per execution.
* Their triggers are **`inputSource: "passthrough"`** with no declared inputs, so the whole batch
  arrives as multiple items.

A Redis node at the trigger evaluates `{{ $json.ID }}` against the **first item only**. If the
execution dies on item 5 of 8, `errorHandler01` would stamp `RETRY_COUNT` and `NEXT_RETRY_AT` on
**item 1 — a document that may have succeeded**. That is precisely the false-positive retry
constraint 3 forbids, and writing an array of all batch ids is no better: it would penalise every
document in the batch for one document's failure.

**The doc id must be captured where the failure happens, not where the workflow starts.** The action
workflows already iterate (`Loop Over Items` / `Route Mode`); the lock-map write belongs *inside*
that per-document loop, so the key always names the document currently in flight. That is a
different and larger change than "one additive node at the entry", and it needs the action routers'
loop structure read properly rather than patched from the outside.

**Where §5b IS safe, unchanged:** workflows invoked per-document with declared inputs —
`indoxV2FigureCompanyId01` (declares `ID`), `indoxV2UploadApiTools01` (declares `ID`). Those can take
the entry node exactly as specced. They are also lower-volume, so the value is smaller.

### 5d. The bigger blind spot: **timeouts never dispatch an error workflow at all**

| status, all workflows | count |
|---|---|
| success | 22,632 |
| crashed | 951 |
| error | 820 |
| **canceled** | **627** |

`errorHandler01`'s own census has **no `canceled` bucket** (1,303 success / 56 error / 49 crashed),
and the hourly correlation is decisive:

| hour | handler runs | canceled | error |
|---|---|---|---|
| 13:00 | 667 | 217 | 234 |
| **12:00** | **152** | **0** | **154** |
| 11:00 | 500 | 410 | 351 |

In the hour with **zero** canceled executions, handler runs match `error` almost exactly (152 vs
154). **`errorHandler01` fires ~1:1 with `error` and not at all for `canceled`.**

`indoxProcessDocument01` — the 30.8%-success bottleneck — ends: 120 success / 141 error / 167
crashed / **95 canceled**. Its failures burn 460–480 s of a 600 s timeout, and a timeout produces
`canceled`. So **a large slice of the exact failures the retry mechanism exists to catch never
reach it**, and fixing the Redis key would not change that.

**Consequence for planning: the §5b fix alone will NOT move the 30.8% success rate.** Shipping it and
reporting "retry implemented" would be this session's defect pattern one more time. The timeout path
needs its own answer — either a watchdog that converts `canceled` into a retry row by polling
`execution_entity`, or lowering the timeout so failures land as `error` while a real backoff handles
them. That is a decision, not a patch, and it belongs with the throughput work rather than here.

### Recommendation: **implement it — do not remove the columns.**

I would not remove them, for three reasons:

1. **The read side is already load-bearing.** `indoxApiSupabase01:520` gates the driver on
   `NEXT_RETRY_AT`. Dropping the column means editing the hot driver query; keeping it costs nothing
   because it is uniformly NULL today.
2. **The gap is one expression, not a feature.** Pass the doc id down to the sub-workflow and have
   `errorHandler01` resolve it from the error payload
   (`$json.execution.id` → also try `$json.workflow.id` + the parent execution id), or have the
   driver write the lock map under **both** its own and the child's execution id. This is small.
3. **The failures it was built for are real and currently unmanaged.** 697 `DOUBLE`, 269
   `MISSING_COMPANY_ID`, 92 `MISSING_TYPE`, plus 1,482 error + 1,365 crashed executions. Removing
   the mechanism removes the only backoff the pipeline has.

**UI — fixed 2026-08-06.** `DocumentDetailPage.tsx` rendered "ניסיונות 0 / ניסיון חוזר הבא —" on
every document, which reads as *this document has never needed a retry* when it means *nothing wrote
this*. The pair is now rendered **only when there is genuine retry state**. The old
`RETRY_COUNT ?? ITERATION_COUNT` fallback was also removed: those count different things
(state-machine passes vs post-failure backoff attempts), and silently substituting one for the other
is how a 0 becomes believable. `ITERATION_COUNT` now has its own row, shown only when non-zero.

**Related, found in passing:** `indoxDocUploader01` (live, active) declares
`errorWorkflow: RqAY1Z1i2F7ZaPbe`, **which does not exist** — every error dispatch from it is
silently dropped. G38 cannot see it because the workflow lives in `legacy/n8n/indox-sheets-era/`,
outside the gate's blueprint roots. This is plan item A6.

---

## 6. `imapclient.search()` charset (D6)

Fixed and verified by the census agent before this lane reached it, including a second fault behind
it (`_send_literal` reading `_cached_capabilities`, `None` on pooled connections). Not re-touched.

---

## 7. 66 → 38 consolidation and retiring the v1 engine (D7) — plan

**The premise needs restating first, and the count is a moving target.** There are **87** blueprints
as of the latest re-baseline (was 83 earlier the same day) — the extraction lane added
`BaseDocEx01`, `InvoiceDocEx01`, `ShipmentDocEx01`, `BsDocEx01`. Any "66 → 38" arithmetic inherited
from an earlier plan is counting a tree that no longer exists. **Re-count before quoting a number;
do not cite 66, 83 or 87 as stable.**

### 7.1 What the 83 actually are

| group | n | members |
|---|---|---|
| v3 JSON-query extraction | 9 | `JQExV3{Base,Invoice,Order,Ship,BS}` + 4 `JQExV3Run*` harnesses |
| v1 per-value query engine | 5 | `indoxV2Query{DocDate,InvoiceId,PurchaseId,ShipmentId,TotalAmt}` |
| v2 action routers | 4 | `indoxV2Actions{Global,GDoc,Ship,BS}` — **Lane A owns these right now** |
| extraction | 2 | `indoxV2Extract{InvoiceGemini,BalanceSheet}` |
| sync v3 | 4 | `syncV3{Main,Deliver,Unit}`, `syncLedgerApi01` |
| sync v1/v2 | 6 | `SyncApi`, `SyncProc{BS,GDoc}`, `SyncScanner`, `SyncScanUnit`, `SyncSource` |
| gmail ingest | 5 | 3 downloaders + 2 action processors |
| api routers | 8 | `indoxApiRouter`, `indoxApiSupabase`, `driveApi`, `mailApi`, `gmailApi{Router,Imap}`, `whatsappApi`, `syncLedgerApi` |
| single-owner services | 4 | `indoxDataGateway01`, `indoxIdentity01`, `indoxV2Upsert01`, `indoxDocBatchUpsert01` |
| reset / demo / fixtures | 5 | `IndoxReset{Full,Gml}01`, `tVzFMkz18pCsXRyw`, `IndoxInjectDemo01`, `indoxV2TestFixtures01` |
| tests | 9 | see §4 |
| infra | 4 | `errorHandler01`, `glitchtipReporter01`, `processLock01`, `ciHelloWebhook01` |
| other | ~18 | driver, decide, figure*, search*, settings, health, mail discovery/label, GWA, chat |

### 7.2 Sequencing — this cannot start yet

The v1 engine to retire is the `indoxV2Query*` five plus `indoxProcessDocument01`, superseded by the
`JQExV3*` two-stage pattern. **But Lane A is actively rewriting exactly that surface** (B1–B13: two
extraction steps, `AI_VAL`/`LOCAL_VAL`/`VAL`, `SELECTED_*` removal, `DOC_ID`/`TOTAL_AMOUNT`/
`FROM_WAREHOUSE` renames). Retiring the v1 engine before Lane A lands would collide head-on. The
honest sequence is: **Lane A lands → re-measure the call graph → then retire.**

### 7.3 The safe retirement technique (validated tonight by another agent)

Make an action **unreachable** rather than deleting it and reshuffling switch indices. A rules-mode
`switch` in n8n routes by output index; deleting a case renumbers every case after it and silently
re-routes traffic — while G41 still passes, because every remaining case still has a
`fallbackOutput`. So:

1. Remove the *decide* function's ability to return the retired literal (it can no longer be chosen).
2. Leave the switch case and its downstream nodes in place, now unreachable.
3. Verify with G41 `switch-fallback-lint` — it cross-checks every literal a decide Code node can
   return against the cases on its switch, so an orphaned case is visible rather than inferred.
4. Delete the dead subtree in a later, separate change once execution counts confirm zero traffic.

Applied to the 5 `indoxV2Query*` workflows, this retires them without touching a single switch index.

### 7.4 Realistic target

Retiring the v1 query engine (5), the 4 `JQExV3Run*` harnesses (fold into the suites), and the 6
sync v1/v2 workflows once sync v3 owns all traffic removes 15 — **87 → 72** at today's count (it was
83 → 68 when first written; the delta is the four new `*DocEx01` extractors, which are net-new
engine, not consolidation targets). Reaching the high-30s means
merging the 8 api routers and the gmail-ingest 5, which is an architecture change (E8, "all logic
unified in n8n, single data/API pattern"), not a cleanup — it needs its own design and an owner
decision. **Claiming 38 as a cleanup outcome would be dishonest.**

---

## 7a. Node positions are semantic — and the re-layout reordered 4 workflows

Under `executionOrder: v1`, when one output feeds several nodes n8n runs them **top-to-bottom by the
target's y position**. So a layout change is only cosmetic if it preserves every fan-out's order.

`tmp/ld_fanout_diff.py` compares fan-out ORDER between a git ref and the working tree and reports
only genuine reorderings. Measured against HEAD on 2026-08-06:

> **15 file(s) have moved nodes; 4 of those REORDERED a fan-out (semantic change); 76 kept order.**

The four are `indoxV2Actions{Global,GDoc,Ship,BS}01.json` — the action routers every document goes
through. Every reordering is the same shape, on a `splitInBatches` loop output:

```
Loop Over Items6[main#1]
      HEAD: Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED  ->  Loop Over Items6
  worktree: Loop Over Items6  ->  Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED
```

i.e. HEAD ran the **action lane first, then the loop-back**; the working tree runs the **loop-back
first**. That is exactly the inversion the owner described, and it is invisible in a coordinate diff
— you only see it by re-deriving the order.

**This lane moved nothing.** No node position was changed by any Lane D edit (`git diff` on my two
blueprint edits shows the `active` flag only, 0 `position` hunks) and `n8n-layout.py` was never run
here.

**Consequence for G45 `n8n-layout-lint`:** that gate *requires* committed positions to match what
`n8n-layout.py` would generate. Under the position constraint that is now a gate demanding a
semantic change — it will fail any correctly-restored file and pass the reordered ones. G45 should
be suspended or re-scoped to overlap-only until the restore lands. `run-gates.py` still runs it, but
its verdict must not be treated as authoritative right now.

---

## 8. Gate status after this lane's changes

Baseline before, measured with `run-gates.py` (the `$?` trap means earlier PASS reports were not
trustworthy): G45 `n8n-layout-lint` **already red** on 4 files owned by other agents in flight
(`indoxV2ActionsGDoc01`, `indoxV2ActionsShip01`, `indoxV2ExtractInvoiceGemini01`,
`glitchtipReporter01`). G42/G43 red as documented. G41 and G46 measured **green** despite GATES.md
still calling them KNOWN FAILING — `run-gates.py` no longer excuses them, so a regression there will
now be caught.

G44 moved red → green and gained a second check.
