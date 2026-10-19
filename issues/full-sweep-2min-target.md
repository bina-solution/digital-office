# Full-table sweep / restart drain — should take 2 min, instead runs indefinitely and floods the queue

**Status:** diagnosed via source + live execution counts, not fixed. Read-only investigation only — no
workflow was modified, no deploy or restart was performed, per the standing rule for this pass.

**Owner's bar (verbatim):** *"this full table sweep should take 2min max, not create thousands of
stalled workflows and never end."*

**Cost:** real and ongoing every time the sweep fires (once/hour by design). Measured in one ~59-minute
window: **3,043 executions of `indoxV2Driver01` alone**, of which **2,327 (76.5%) were still queued and
had not started** at query time. The restart pool (~19,000 `STATUS='ACTION_RESTART'` rows) and the
normal 2-minute quota lane both share the same 16 worker slots the sweep is saturating, so the sweep
doesn't just fail to finish itself — it stalls the *other* lane too.

---

## 1. What the owner observed (console concurrency view, ~12:1xZ)

- Executions named `decide_execute_x_200_lines_x_...` stacking up.
- Long blue "integrated" bars; **p99 164s**; **124 concurrently running**.
- **10,611 successes / 15 min** system-wide (≈42,400/hr — all workflows, not just the driver).
- `Incoming Documents v2` (= `indoxV2Driver01`'s display name, confirmed at
  `apps/indox/blueprint/n8n/indoxV2Driver01.json:3`) showing **80 executions / 59 concurrent**.
- Restart pool: **~19,000 docs `STATUS='ACTION_RESTART'`**, draining at only **~15,000–20,000/hr**
  through the quota-lane drainer (figures as given; see §7 for why I could not re-verify them live).

These are not four separate symptoms. §3–§6 below show they are one mechanism.

## 2. The architecture, as it actually is today (read from the live blueprints, not from memory)

`indoxV2BaseDrain01.json` ("indox-v2 Stage Drainer") runs **two lanes off one `Check Capacity` gate**:

| Lane | Cadence | Selection | Chunking | Dispatch |
|---|---|---|---|---|
| **Quota lane** | every 2 min (`Every 5 min` node, actually 2-min interval) | classified/ranked/capped (`Pick Drain Candidates`), excludes locked + terminal-status rows | `Drain Loop`, batchSize **100** | `Driver: Run By ID` → `indoxV2Driver01`, `waitForSubWorkflow:false` |
| **Sweep lane** | once/hour, only when `Check Capacity` gear==2 (idle) and 55+ min since last run | `Pick All IDs (full table)` — **`SELECT "ID" FROM incoming_documents ORDER BY "ID"`, no STATUS filter, no LIMIT, deliberately unfiltered** | `Sweep Chunk`, batchSize **200** | `Driver: Full Sweep` → `indoxV2Driver01`, `waitForSubWorkflow:false` |

Both lanes call the **same** entry point (`indoxV2Driver01` via `When Executed by Another Workflow`),
just with different chunk sizes and different candidate sets. There is no third lane in this proposal —
see §8 non-goals.

Table size at last sweep: **36,762 rows** (`incoming_documents_pre_sweep_20260815` snapshot, named in
`indoxV2BaseDrain01.json`'s `Sweep Gate (1/hour)` node — the snapshot's own name is dated one day past
the DB/session clock at measurement time; treated as informational, not re-verified live, per §7).
36,762 / 200 = **184 chunks per full sweep**.

## 3. The multiplication mechanism (the root cause)

Traced mechanically from the live blueprint graph (BFS from `When Executed by Another Workflow` over
`indoxV2Driver01.json`'s own `connections` object — 51 reachable nodes, not inferred from names).

**Confirmation that one chunk = one execution carrying the whole batch, not N single-item executions:**
`indoxV2Decide01.json`'s `Execution Data (decide)` node stamps every Decide execution with:

```
outline = 'decide_' + mode + '_x_' + $input.all().length + '_lines_x_' + distinctActionCount + '_actions'
```

— this is the literal source of the owner's observed `decide_execute_x_200_lines_x_...` label
(`apps/indox/blueprint/n8n/indoxV2Decide01.json:365`). `$input.all().length` is the whole array, so a
**200-item Sweep Chunk batch is delivered to Decide as ONE execution with 200 items**, not split into
200 executions. The same "once" (whole-array) semantics hold end to end — confirmed independently by
`Get Line Match`'s own comment: *"The hourly full-table sweep hands the driver 30,000 ids in one
execution"* (`indoxV2Driver01.json:5768`, describing a quadratic bug this exact shape triggered before
it was fixed to O(1) lookup).

**What happens inside that one execution**, per document in the batch, traced through the live graph:

```
When Executed by Another Workflow (N items, e.g. 200)
  -> Switch (routes on ID vs ACTION_LINE/ACTION_LINES presence)
  -> Run By ID -> MAP ID -> Get Line Req -> Call indox api (Get Line)     [indoxApi01, batched call]
  -> Get Line Match -> Map ID Match Line Data -> Start -> If UNDEFINED NAME
  -> Call indox-v2 Decide                                                 [indoxV2Decide01, wait=True]
       -> Determine Action (dedup, pure JS over the WHOLE batch)
       -> Call router_doc_base (decide)                                   [indoxV2ActionsGlobal01, wait=True]
            ^ UNCONDITIONAL — runs for every item in the batch regardless of the eventual verdict
       -> Route By Type (per item: __route_bs__/__route_gdoc__/__route_shipment__/fallthrough)
       -> conditionally ALSO Call router_bs / router_gdoc / router_shipment (decide)  [wait=True each]
  -> Dup Guard: Check ACTION_LOG -> If SAME ACTION TWICE -> If ACTION (drops no_action items)
  -> Taking Action -> Check LOCKED                                        [processLock01, executeWorkflow]
  -> If NOT LOCKED -> Execute Action
       -> Group By ACTION (buckets ≤25 items per action) -> Loop Over Items37 (batchSize 10)
            -> POST Action Router (group)   [HTTP POST webhook/indox-action-router -> NEW QUEUED execution
                                              of indoxV2ActionRouter01 — confirmed at indoxV2ActionRouter01
                                              .json:203-204, httpMethod POST, path "indox-action-router"]
       -> Check Next Action -> Next Action IDs
            -> POST Next Action (by id)      [HTTP POST webhook/incoming-documents-017 -> NEW QUEUED
                                              execution of indoxV2Driver01 ITSELF — the self-recursion]
```

Three things matter about this shape:

1. **`Call router_doc_base (decide)` is unconditional.** Every one of the 200 items pays for a
   synchronous (`waitForSubWorkflow:true`), blocking call into `indoxV2ActionsGlobal01` (186KB, the
   largest action workflow) *before* the batch is even routed by type — including the majority of rows
   that are already terminal and will resolve to `no_action`. The sweep is explicitly designed to
   re-decide the *whole* table every hour (`indoxV2BaseDrain01.json`'s own comment: *"no STATUS filter
   ... Re-deciding a COMPLETED row is cheap and idempotent"*) — but "cheap" is not true today, because
   deciding still means one blocking sub-workflow call per batch minimum, regardless of verdict.
2. **Two independent channels re-enter the Bull queue per document that takes any action**: the
   self-webhook (`POST Next Action`, back into `indoxV2Driver01`) and the Action Router dispatch
   (`POST Action Router`, into `indoxV2ActionRouter01`, which itself fans out further into the
   GDoc/BS/Ship/Global action workflows). Both are `httpRequest` nodes with `batching:{batchSize:10,
   batchInterval:250}` — that paces the *outgoing POSTs*, it does not bound how many new executions
   result, and it does not wait for them to finish.
3. **`Check LOCKED` (processLock01) runs once per batch too**, but per the driver's own note it is the
   authoritative mutex, so this part is correct by design — it is not where the multiplication problem
   lives; the unconditional Decide call and the two re-entry channels are.

## 4. Measured: execution volume and the multiplication factor

Queried against `n8n-postgres-shlomo-laptop` (`execution_entity` / `execution_metadata`), window
**2026-08-14 11:32:21Z – 12:31:16Z** (~59 min, overlapping the owner's 12:1xZ screenshot):

| mode | status | count |
|---|---|---|
| webhook | **new (queued, not yet started)** | **2,327** |
| webhook | success | 496 |
| webhook | error | 2 |
| integrated | success | 202 |
| integrated | error | 15 |
| integrated | running | 1 |
| **total, `indoxV2Driver01` only** | | **3,043** |

`execution_metadata` key counts for the same population: `trigger_type` / `origin_execution` /
`trigger_chain` = 714 rows each (executions that ran far enough to stamp); `line_count` / `actions` /
`outline` / `exection_type` / `has` = 508 rows each (the subset that reached the action-dispatch stamp,
i.e. carried at least one candidate action); `parent_execution` = 497.

**Multiplication factor, driver self-recursion alone (measured, lower bound):**
2,825 webhook-mode executions (496 success + 2,327 queued + 2 error) arose from only
**~218 chunk-level dispatches** (202 integrated success + 15 error + 1 running) in the same window —
**≈13x**, and that counts only `indoxV2Driver01`'s own re-entries. It excludes the `Call indox-v2
Decide`, `Call router_*`, `Call indox api (Get Line)`, `Check LOCKED`, and `POST Action Router` layers,
which the graph trace in §3 confirms are *also* invoked per chunk (and, for the four `Call router_*`
sub-workflows, unconditionally). The owner's own **10,611 successes/15min system-wide** (≈42,400/hr,
all workflows) against ≈218 top-level driver dispatches/hr implies a **system-wide multiplication on
the order of 100–200x per chunk dispatch** — consistent in order of magnitude with the direct
measurement, not independently re-derived from it, and stated as a cross-check, not a second proof.

**Reconciling "124 concurrently running" (Little's Law, not a new measurement):** `Driver: Full Sweep`
and `Driver: Run By ID` both use `waitForSubWorkflow:false`, so `Sweep Chunk`/`Drain Loop` fire the next
chunk without waiting for the previous one to finish. `indoxV2BaseDrain01.json`'s own comment documents
a per-chunk **dispatch** cost of 1.2–7.6s (quiet to worst-case, from its own measured passes). At the
owner's p99 of 164s **service** time per chunk, steady-state concurrent chunks ≈ service_time /
dispatch_interval ≈ 164 / 1.3 ≈ **126** — matching the observed 124 almost exactly. The sweep isn't
slow *and separately* concurrent; the concurrency **is** the arithmetic consequence of dispatching 184
chunks faster than any one of them can finish.

## 5. Designed vs. actual — where the 2-minute bar is lost

| | Designed (owner's own figures) | Actual (live blueprint) |
|---|---|---|
| Decide batch size | **5,000** lines/pass — quoted verbatim from `indoxV2Driver01.json`'s (now-dead) `Lines Batching Loop` node: *"5000 lines per pass is the owner's standing figure"* | **200** (`Sweep Chunk` batchSize) |
| Chunks for 36,762 rows | 36,762 / 5,000 ≈ **8** | 36,762 / 200 = **184** — a **23x** oversized dispatch granularity |
| Cost per no-op row | one decide verdict, no sub-workflow call | one **unconditional, blocking** call into `indoxV2ActionsGlobal01` (§3.1), regardless of verdict |
| Verdict/marker writes | batched (task brief: batches of 100) | not batched at the sweep layer — no-op rows are re-decided individually every hour with no bulk marker write |
| Queue behavior | 8 dispatches, bounded concurrency | 184 fire-and-forget dispatches against 16 shared Bull slots → §4's 126-deep pile-up |

Chunk count alone (184 vs 8, a 23x gap) is sufficient to explain most of the queue depth in §4; the
unconditional Decide→ActionsGlobal call is what turns each of those 184 chunks into a genuinely
expensive (not just numerous) dispatch.

## 6. "Thousands of stalled workflows / never ends" — what backs this claim

I could not pull a direct `status='running' AND age>10min` census with per-execution stuck-node
detection this pass (see §7 — an unrelated environment fault cut the DB session short). The closest
directly-measured evidence is §4's **2,327 `webhook`/`new` (queued-not-started) executions of
`indoxV2Driver01` alone**, within a single hour, against **16 total Bull worker slots (2 workers ×
concurrency 8, pinned — see §8) shared by every workflow in the system**, including the restart pool's
own drain traffic. A job queued behind 2,327 others for the better part of an hour reads, from the
console concurrency view, exactly like what the owner described — regardless of whether n8n's internal
status field says `new` or `running`. This is a lower bound: it does not include the Action Router or
per-type action workflows' own queued backlogs, which §3 shows exist but which I did not get to query.

The restart pool (~19,000 `STATUS='ACTION_RESTART'` rows, draining at ~15,000–20,000/hr, per the task
brief) is **not exempt from this queue** — `indoxV2BaseDrain01`'s quota-lane `open` CTE excludes a
fixed terminal-status set (`COMPLETED, MERGED, DOUBLE, OLD, GARBAGE, PAUSE, MAX_ITERATIONS,
MISSING_COMPANY_ID, MISSING_TYPE, UNKNOWN_COMPANY, EXTRACTION_FAILED, API_TOOLS_FAILED,
ACTION_REQUIRED, NEEDS_REVIEW`) and `ACTION_RESTART` is not in it, so restart rows are picked up by
whichever class they otherwise match and dispatched through the **same** `Driver: Run By ID` →
self-webhook path as everything else. They queue behind the same 2,327-deep backlog the sweep creates,
which is the direct explanation for a drain rate (~15-20k/hr) that is far below what 16 worker slots
should sustain for genuinely lightweight state-machine transitions.

## 7. What I could not verify this pass

Mid-investigation, the machine's `C:` drive hit **0 bytes free** (confirmed independently via `df -h`
in Git Bash and `Get-Volume`/`Get-PSDrive` in PowerShell — not a tool artifact). Every subsequent WSL
invocation (the only path to `docker exec`/`psql` on this host) failed, intermittently with an explicit
ENOSPC error and intermittently by silently returning empty output for queries that should have had
rows (verified by re-running an identical query that had returned real data minutes earlier). I made
eleven attempts across both the Bash and PowerShell channels, including redirecting output straight to
a file to bypass the harness's own output relay; none succeeded once the disk hit zero. This is flagged
separately to the user as its own operational risk — a 100%-full system disk can degrade Postgres,
Docker, and WSL's virtual disk in ways indistinguishable from application-level slowness, so it should
be ruled out (or in) before any fix here is judged by its effect on timing. It is plausible, but **not
established**, that the volume of `execution_data`/`execution_metadata` this same multiplication
produces (§4: 3,043 executions/hr from one workflow alone, each with its own execution-data blob) is
itself a contributor to disk growth — noted as a hypothesis, not a finding.

Blocked by the above, specifically:
- Per-node timing inside a single 200-item chunk execution (`execution_data` node-level `executionTime`)
  — §3's cost path is structurally confirmed (which nodes run, in what order, integrated vs queued) but
  not individually clocked this pass.
- `status='running' AND age > 10min` census with decoded current-node / last-`runData` entry.
- Live `bull:jobs:wait` / `bull:jobs:active` depth from `redis-posnet`.
- Independent re-verification of the owner-supplied 19,000-row restart pool and its 15–20k/hr drain
  rate (used here as given).
- Individual execution IDs to cite (all figures in §4 are aggregate `GROUP BY` counts, captured before
  the fault; no `execution_entity.id` values were retrieved before the DB session became unreliable).

## 8. Root cause, stated plainly

The hourly full sweep is architecturally a **fan-out of 184 fire-and-forget, non-backpressured
dispatches**, each of which pays for **at least one unconditional, blocking, whole-batch call into the
largest action workflow** regardless of verdict, and each of which **re-enters the shared Bull queue
through two independent channels** (driver self-webhook, Action Router webhook) for every document that
takes any action. Because dispatch (`waitForSubWorkflow:false`, ~1.2–7.6s/chunk) is roughly 100x faster
than one chunk's own completion (p99 164s), the sweep outruns its own capacity signal — `Check Capacity`
is evaluated once before the sweep starts and never again during its 184-chunk dispatch loop — and
piles up ~126 concurrent chunk executions (matching the observed 124) while flooding the shared queue
with thousands of secondary executions that the 16 pinned worker slots cannot drain faster than they
arrive. The restart pool and the normal 2-minute quota lane share that same queue and that same
`Check Capacity` gear signal, so the sweep's self-inflicted congestion throttles *all* other work for
its own duration, not just itself.

## 9. Redesign proposal (fits the existing two-lane architecture — no new lane)

All four changes are inside the **existing** sweep lane's own dispatch loop and inside `indoxV2Decide01`;
nothing here adds a third lane, a new scheduled trigger, or a new drain mechanism.

1. **Raise `Sweep Chunk` batchSize from 200 toward the owner's own documented design figure, 5,000**
   (`indoxV2BaseDrain01.json`, one node, one number). 36,762 / 5,000 ≈ 8 chunks instead of 184 — a 23x
   cut in chunk count, which by §4's Little's Law relationship directly cuts steady-state concurrency by
   roughly the same factor (~126 → ~5-6), independent of anything else changing.
2. **Add a cheap sweep-mode short-circuit ahead of `Call router_doc_base (decide)` in
   `indoxV2Decide01`.** Today every item pays for a blocking call into `indoxV2ActionsGlobal01` before
   routing even happens (§3.1). A pure-JS pre-check — terminal `STATUS` and no relevant field changed
   since the last sweep stamp → emit `no_action` directly, skip the sub-workflow call entirely — lets
   the (documented, large) terminal majority of the 36,762 rows resolve in the same batch pass that
   already does dedup, at no added sub-workflow cost. This is the single highest-leverage change: it is
   what makes an 8-chunk sweep actually *cheap* per chunk, not just fewer in number.
3. **Batch any verdict/marker writes** for the no-op cohort — e.g. one `UPDATE ... WHERE ID = ANY($1)`
   per 100 IDs (matching the batching convention already used by `Drain Loop`), instead of leaving
   no-op rows with no bulk write path. Rows that genuinely need action already flow into the normal
   per-action upsert path unchanged.
4. **Re-check `Check Capacity` inside the sweep's own dispatch loop**, not only once before `Sweep Gate`
   fires — e.g. every 2-3 chunks, using the same gear signal the quota lane already reads. This is a
   backstop for #1/#2, not a substitute: even an 8-chunk sweep could in principle still crowd out the
   quota lane if each chunk is heavier than expected, and today nothing inside the loop would notice or
   slow down.

**2-minute feasibility, order-of-magnitude:** 8 chunks, each doing pure-JS dedup + the short-circuit
check over ~4,600 items (36,762/8) + sub-workflow calls only for the genuine non-terminal minority
(the same fraction the quota lane already processes today at its normal, non-pathological cost) +
batched marker writes (~46 batches of 100 at 5,000/chunk). None of that is new *work* — it is work the
system already does for real actions today, just no longer paid redundantly by every terminal row every
hour. Firing 8 fire-and-forget dispatches a few seconds apart, each finishing in tens of seconds rather
than up to 164s, keeps concurrent in-flight chunks in the single digits and the whole sweep inside 2
minutes wall-clock for dispatch, with the tail bounded by however long the real (non-terminal) action
processing already takes today — the same bound the quota lane already lives with. This is an estimate
from the measured structure, not a re-run of the sweep; it should be validated against a real timed
pass before being treated as proven.

## 10. Non-goals (explicit)

- **Do not raise worker concurrency or worker count.** 2 workers × concurrency 8 = 16 slots is pinned in
  `perf-profiles.yml` with documented OOM history (see `issues/scaling-solution.md` §3 and this repo's
  standing operational rule); adding slots to a dispatch-storm does not fix a dispatch storm, it just
  raises the ceiling the storm can reach before something else breaks.
- **Do not add a third drain lane.** The proposal in §9 changes chunk size, adds a short-circuit, batches
  writes, and adds an intra-loop capacity check — all inside the two lanes that already exist.
- **Do not touch the quota lane's own logic.** It is not implicated in this issue; it is a *victim*
  (§6) of the sweep's congestion, not a contributor to it.
- **Do not shorten the sweep's hourly cadence or widen its candidate set.** Cadence and "no STATUS
  filter" are both deliberate owner decisions recorded in `indoxV2BaseDrain01.json`'s own comments
  (duplicate detection needs whole-table co-residency — see `indoxV2Decide01.json`'s `Determine Action`
  comment on why batch-local dedup requires the full table in view). Nothing here proposes changing that.

## References

- `apps/indox/blueprint/n8n/indoxV2BaseDrain01.json` — both lanes, `Check Capacity`, `Sweep Gate (1/hour)`,
  `Pick All IDs (full table)`, `Sweep Chunk`, `Driver: Full Sweep`, `Driver: Run By ID`
- `apps/indox/blueprint/n8n/indoxV2Driver01.json` — `When Executed by Another Workflow`, `Switch`,
  `Call indox-v2 Decide`, `Check LOCKED`, `Dup Guard: Check ACTION_LOG`, `Group By ACTION`,
  `Loop Over Items37`, `POST Action Router (group)`, `Next Action IDs`, `POST Next Action (by id)`,
  `Lines Batching Loop` (dead code, preserves the owner's 5,000-line design figure), `Get Line Match`
  (quadratic-fix comment documenting the 30,000-id-in-one-execution shape)
- `apps/indox/blueprint/n8n/indoxV2Decide01.json` — `Execution Data (decide)` (source of the
  `decide_execute_x_200_lines_x_...` label), `Determine Action`, `Call router_doc_base (decide)`,
  `Route By Type`, `Call router_bs/gdoc/shipment (decide)`
- `apps/indox/blueprint/n8n/indoxV2ActionRouter01.json` — webhook path `indox-action-router` (line 204)
- `issues/scaling-solution.md` — §3 (16 pinned worker slots, do not raise), §1.2b (chunk-count vs
  chunk-size arithmetic this issue reuses), §4 (n8n deploy mechanics, if this is ever staged)
- `issues/indox-scheduled-sweep-stalled-2026-08-11.yaml` — an earlier, different sweep failure mode
  (Bull `maxStalledCount:0` killing the old hourly `Schedule Trigger` sweep). That entry point is now
  `disabled:true` in the live blueprint, superseded by the two-lane `indoxV2BaseDrain01` design this
  issue is about; not the same bug, kept here only so the two are not conflated.
- `issues/indox-consolidated-state-2026-08-11.yaml` — prior finding that the driver's self-webhook
  recursion is a standing queue-depth risk; this issue measures the same mechanism under the newer
  two-lane sweep and quantifies it.
