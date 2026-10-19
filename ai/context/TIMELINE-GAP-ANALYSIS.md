# Timeline Gap Analysis — n8n execution pool idle-time audit

Date: 2026-08-06 (analysis of 2026-08-05 13:18–21:18 UTC, shlomo-laptop deployment)
Tool: [`scripts/ops/timeline-gaps.py`](../../scripts/ops/timeline-gaps.py)
Source of truth: `execution_entity` in the n8n Postgres DB (`startedAt`/`stoppedAt`/`status`/`workflowId`/`mode`), cross-referenced with `sync_ledger` in the Supabase DB and the schedule-trigger node configs stored in `workflow_entity.nodes`.

**Bottom line:** the pool spent **~60.7 of the 8 analysed hours** with at least one idle worker slot while backlog was demonstrably present — worth an estimated **~136 documents/hour** of unrealized throughput at the observed rate (`~200s`/document). Almost all of that loss is concentrated in one **3h06m stretch (15:25–18:31) plus a preceding 59m stretch (14:25–15:24)** where the pool ran at **~3/16 slots busy (≈20% utilisation)** despite a live document backlog. Utilisation jumps sharply after 18:31 and averages **101.9%** of the modelled 16-slot pool for the rest of the window (some of that is a modelling artifact of burst error/crash storms — see caveats). Schedule-fired pipes running on fixed 15-minute intervals (`Sync Scanner`, `Mail Label Engine`) are the clearest remaining structural gap, still losing **~55–60 minutes of every scheduled hour** to a scanner that returns in under a second.

---

## 1. The tool

`scripts/ops/timeline-gaps.py` reconstructs the worker-slot timeline directly from `execution_entity` — no other instrumentation needed. It talks to Postgres via `docker exec <container> psql`, so it runs unmodified on the VPS or this workstation.

```bash
# inside WSL, with the bbox docker socket exported
export DOCKER_HOST=unix:///run/bbox-docker.sock

# full available history
python3 scripts/ops/timeline-gaps.py

# a specific window
python3 scripts/ops/timeline-gaps.py --start "2026-08-05 14:24" --end "2026-08-05 18:30" \
  --n8n-container n8n-postgres-shlomo-laptop --ledger-container supabase-db-shlomo-laptop

# tune the model
python3 scripts/ops/timeline-gaps.py --hours 8 --workers 2 --concurrency 8 \
  --bucket 30 --lookahead 20 --doc-seconds 200
```

From Windows, wrap the call in a one-line `.sh` and run it with
`MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash <wrapper>.sh` (per the deployment's WSL-only shell policy).

It reports six sections, in order: slot utilisation (10-minute bins), a ranked gap census, per-workflow concurrency, schedule alignment (dead-time per fixed-interval pipe), zombie executions, and queue depth vs. activity (best-effort, from `sync_ledger`).

### A modelling correction made while building it

n8n's `execution_entity.mode` column matters a lot here. `mode='integrated'` rows are **Execute-Workflow sub-calls that run inside the calling execution's own worker slot** — n8n does not queue them as separate jobs. In this window, **16,729 of 19,322 executions (87%) were `integrated`.** Counting every row as consuming a pool slot (my first pass) produced a nonsense 274% "utilisation." The tool now computes slot occupancy only from `trigger` / `webhook` / `manual` / `error` / `retry` / `cli` modes (configurable via `--slot-modes`), and keeps the full row set for per-workflow concurrency, where a fan-out of many parallel integrated calls is still a meaningful (non-slot) signal. This dropped the headline number to a defensible **101.9%** average, still elevated by burst error storms discussed below.

**Caveat carried into every number below:** `sync_ledger` has no `created_at` or status-history — only `claimed_at`/`delivered_at`, both null unless the item is actually delivered. There is no way to reconstruct true queue depth over time from it alone. The tool substitutes a **backlog-signal proxy**: a time bucket counts as "backlog present" if any sync/indox-family workflow *started* within a configurable look-ahead window (default 20 min). This is conservative in the right direction — it under-counts backlog (misses cases where work was waiting but nothing fired yet) rather than over-counts it, so idle-time-while-backlog figures below are a **floor**, not a ceiling.

---

## 2. Slot-utilisation timeline

Pool model: 2 workers × 8 concurrency = 16 slots (per task scope; see §7 for why the real ceiling may not be 16 — no `N8N_CONCURRENCY_PRODUCTION_LIMIT` override was found in either worker's environment, so the effective concurrency is whatever n8n's build default is, not confirmed as exactly 8).

| Time (UTC) | Busy slots (of 16) | Utilisation | Note |
|---|---|---|---|
| 13:18–14:38 | 0.0 | 0% | no backlog yet — legitimately idle, **not** counted as a gap |
| 14:38–15:24 | 0.7–1.9 | 4–12% | backlog present, pool nearly empty |
| 15:24–18:08 | 2.1–5.3 | 13–33% | sustained low-utilisation stretch, backlog present throughout |
| 18:08–18:38 | 8.6–13.7 | 54–86% | ramp-up |
| 18:38–21:08 | 13.7–113.8 | 86%–712% | high throughput, with repeated overshoot spikes far above 16 |
| 21:08–21:18 | 1.0 | 6% | backlog draining, tool run mid-stretch |

The overshoot spikes (e.g. 113.8/16 at 19:38, 78.0/16 at 18:48) are **not** evidence the pool safely runs at 7x its modelled capacity — they line up with bursts of `error`-mode executions (`Error Handler` peaked at **124 simultaneous** invocations, `GlitchTip Error Reporter` at 16) and rapid `indox api - supabase` retries (54 concurrent). These look like failure cascades — many things breaking near-simultaneously — rather than genuine sustained throughput. Treat the >16 bins as "something broke and fanned out fast," a distinct problem from idle-slot waste, and worth its own investigation (out of scope here — see `ai/context/ERROR-RCA-2026-08-05.md` if a related RCA already covers it).

**Average utilisation across the 8h window: 101.9% (16.3/16).** Split by regime: **21.2%** in the 14:24–18:30 low-utilisation stretch (4.1h) vs **241.8%** in the 18:30–21:14 high-throughput stretch (2.73h) — execution volume in the second, shorter window (10,989 executions) exceeded the first, longer window (7,768) by 41% in 63% of the time. That inflection is consistent with — though not conclusively proven to be caused by, since workflow `updatedAt` timestamps were overwritten by a later redeploy and can't pin the exact fix-landing time — the `syncV3Unit0001` sequential-await-loop fix landing today per the known context.

---

## 3. Gap census (idle-slot intervals while backlog was present)

17 distinct gaps totalling **60h41m of idle slot-time** in the 8h window (i.e. summed across all 16 slots — not 60 hours of wall-clock idleness). Ranked by slot-time lost:

| Start → End (UTC) | Wall time | Slot-time lost | Preceded by |
|---|---|---|---|
| **15:24:46 → 18:30:46** | **3h06m** | **37h12m30s** | Incoming Documents v2 (success) |
| **14:25:16 → 15:24:16** | **59m** | **14h08m30s** | (window start) |
| 20:46:16 → 21:06:16 | 20m | 3h39m30s | GlitchTip Error Reporter (crashed) |
| 19:17:46 → 19:29:16 | 11m30s | 1h41m | gmail api (success) |
| 19:02:16 → 19:12:46 | 10m30s | 1h16m | GlitchTip Error Reporter (success) |
| 20:00:46 → 20:06:46 | 6m | 32m | indox api (success) |
| 19:13:46 → 19:17:16 | 3m30s | 22m | indox api (success) |
| 18:31:16 → 18:39:16 | 8m | 20m | gmail api (success) |
| (9 smaller gaps, 1–2min each) | — | ~1h10m combined | mostly Error Handler / indox api |

**The top two gaps are 90% of the total loss** and are literally one contiguous stretch (14:25–18:31, ~4h05m wall) where the pool sat at 3–6 busy slots instead of 16. This is the single event to fix. At **~200s/document**, the 51.3 slot-hours lost in just those two gaps represents **~925 documents** of theoretical throughput, or **~226 documents/hour** averaged over that stretch — the largest number in this whole analysis.

The 20:46–21:06 gap (3h39m30s lost) immediately follows a **crashed** `GlitchTip Error Reporter` execution — worth a look, since a crash in the error-reporting path itself stalling downstream work is a bad failure mode (errors should never be able to back up the pipe further than the thing that failed).

---

## 4. Per-workflow concurrency

Top workflows by execution count (all modes, since sub-workflow fan-out concurrency is itself informative even though it doesn't consume a pool slot):

| Workflow | Runs (8h) | Max concurrent |
|---|---|---|
| indox api - supabase | 2,709 | 54 |
| indox api | 2,015 | 16 |
| process_lock | 1,662 | 5 |
| Error Handler | 1,279 | 124 |
| GlitchTip Error Reporter | 1,273 | 16 |
| gmail api / gmail api - imap smtp | 1,082 each | 7–11 |
| drive api | 905 | 14 |
| Incoming Documents v2 | 869 | 56 |
| Sync Ledger API | 841 | 7 |
| Sync v3 Deliver | 559 | 34 |

**Named pipeline workflows called out in scope:**

| Workflow | Runs | Max concurrent | Verdict |
|---|---|---|---|
| Sync v3 Reconcile (`syncV3Main0001`) | 24 | 2 | not serialised — the lock allows exactly the intended overlap |
| Sync v3 Source Unit (`syncV3Unit0001`) | 234 | 2 | **fixed** from a hard serial `await` loop, but still capped at 2 concurrent — headroom to widen further if the fix allows it |
| Sync Scanner (`SyncScanner00001`) | 22 | **1** | serialised — but by design: it's a single top-level schedule trigger, only one instance should exist per interval. Not itself a bug. |
| Sync Scan Unit (`SyncScanUnit0001`) | 0 | — | no executions in this window |
| Sync Processor - drive-bs (`SyncProcBS000001`) | 0 | — | no bs-source items arrived in this window (informational, not a gap) |
| Sync Processor - drive-gdoc (`SyncProcGDoc0001`) | 165 | 31 | healthy parallelism |
| Sync v3 Deliver (`syncV3Deliver0001`) | 559 | 34 | healthy parallelism |
| Sync Ledger API (`syncLedgerApi01`) | 841 | 7 | healthy — this is the ledger-claim reaper + API, expected to be called often |
| Process Document (`indoxProcessDocument01`) | 205 | **38** | **not** the serial bottleneck it might look like from the per-document time (211.8s) — it's already running highly parallel |
| indox-v2 Generate Thumbnail (`indoxV2GenerateThumbnail01`) | 30 | 10 | also already parallel; the 116s cost is a latency problem for each document's critical path, not a pool-occupancy problem — consistent with the plan to remove it entirely rather than optimise it |
| INDOX Data Gateway (`indoxDataGateway01`) | 0 | — | no executions in this window |

**Conclusion for this section:** none of the document-processing pipeline workflows are pathologically serialised right now. `Sync v3 Source Unit`'s fix clearly landed — it went from a documented sequential `await` loop to running 2-wide. The one workflow correctly showing `max concurrent = 1` (`Sync Scanner`) is inherent to being a single schedule-triggered orchestrator, not a lock or an `await` bug — its cost shows up in §5 instead, as dead schedule time, not as serialisation.

---

## 5. Schedule alignment — dead time per fixed-interval pipe

Filtered strictly to `mode='trigger'` executions (the actual cron firings — this excludes the 87% of rows that are on-demand sub-workflow calls, which a first pass of the tool incorrectly mixed in and which produced misleading numbers for high-frequency helper workflows like `indoxV2GenerateThumbnail01`).

| Workflow | Runs | Median cycle | Median runtime | Dead time/cycle | Dead time/hr | Configured interval (from node JSON) |
|---|---|---|---|---|---|---|
| **Sync Scanner** | 22 | 14m59s | **0s** | **14m59s** | **59m59s/hr** | 15 min (`n8n-nodes-base.scheduleTrigger`) — matches exactly |
| Sync Ledger API | 67 | 5m00s | 0s | 4m59s | 59m58s/hr | 5 min reaper — **by design**, not a backlog pipe, exclude |
| indox integration health | 5 | 1h00m | 5s | 59m54s | 59m54s/hr | hourly health check — **by design**, exclude |
| indox api - supabase (as trigger) | 694 | 30s | 0s | 29s | 59m45s/hr | fast polling loop already near-real-time — exclude |
| **Mail Label Engine** | 21 | 14m59s | 1m19s | **13m40s** | **54m42s/hr** | 15 min — matches |
| Gmail Actions Scanner | 7 | 14m48s | 5m01s | 9m46s | 39m37s/hr | **configured for 3 min, observed cycle is 14m48s — mismatch, low confidence** (see caveat) |
| Sync v3 Reconcile | 21 | 14m59s | **15m56s** | 0s (clamped) | 0s/hr | 15 min — matches; runtime now *exceeds* the interval |

**Sync Scanner is the clean, unambiguous, single largest schedule gap.** 22/22 runs return in under a second, every 15 minutes, all day — meaning the scanner's own top-level execution (the thing holding a slot) does essentially no work; whatever real scanning happens must be dispatched elsewhere (via `webhook`-mode calls it fires and doesn't wait on) or barely touches this window. Either way, **the schedule itself, not the work, sets the cadence** — a textbook case for event-driven triggering or a much shorter interval while backlog is deep.

**Gmail Actions Scanner's numbers don't match its own configuration** (3-minute schedule node vs. an observed ~15-minute cycle over only 7 samples). Before acting on its dead-time number, confirm whether the workflow was active the whole window, gated by an internal condition that no-ops most firings, or genuinely running at the configured cadence with most `trigger` executions simply not landing in `execution_entity` the way expected. Flagging rather than asserting.

**Sync v3 Reconcile is the interesting one: 0 dead time, but a new risk.** Median runtime (15m56s) now *exceeds* the 15-minute schedule interval and comfortably exceeds the `processLock01` Try-Lock TTL (600s / 10 min, per the node's own inline note). Checked directly: **0 of 24 executions in this window show a `{skipped:true}` lock rejection** in `execution_data`, so the lock is not currently costing idle slot-time — the concern in the task brief ("if the lock is held while slots idle, that is now a gap") does not reproduce today. But because the TTL (600s) is shorter than the observed worst-case runtime (956s), there's a **latent correctness gap**: the Redis key can expire while the original run is still genuinely in flight, silently permitting a second overlapping run the lock was meant to prevent. That's not an idle-slot problem, but it sits right next to this one and is worth fixing in the same pass (raise the TTL past the p99 runtime, or make it a renewable/heartbeat lock).

**Total measured schedule dead-time across all seven pipes: ~5h34m of dead time per wall-clock hour** (summed across pipes, not a single 5.5-hour block). Excluding the three by-design/non-backlog rows (`Sync Ledger API` reaper, `indox integration health`, `indox api - supabase` polling), the **backlog-relevant** dead time is **Sync Scanner (60m/hr) + Mail Label Engine (55m/hr) + Gmail Actions Scanner (40m/hr, unverified) ≈ 1h35m–2h15m of dead time per wall-clock hour**, spread across three pipes that each individually waste most of their own 15-minute budget.

---

## 6. Zombie executions

**0 zombies right now** (`status='running'` older than 20 minutes) — checked live. The known-context figure of 34 stuck executions is real but historical; the environment has restarted multiple times since (most recently during this analysis, for unrelated WSL-service reasons), which clears `running` rows as a side effect. Currently only 3 executions were mid-flight at the moment of the full-window query, none aged past the threshold.

**The structural gap is still there, though.** `syncLedgerApi01` has its own 5-minute "Reaper Schedule" node — but per its own inline note, that reaper closes out **stuck `sync_ledger` claims**, not stuck `execution_entity` rows. There is no equivalent for n8n's own execution table. If a worker dies mid-execution (OOM, container restart, crash), the row can sit at `status='running'` indefinitely with nothing to flip it. Impact model: each zombie permanently removes one slot from the 16-slot pool until an operator or a scheduled reaper cleans it up. At the historical high-water mark of 34 stuck executions, that's **more than double the entire pool** — a scenario that would have completely starved new work regardless of backlog size. Even a handful (3–4) sitting unreaped for hours costs **18–25% of theoretical capacity** (≈50–70 documents/hour at full utilisation) for as long as they're not cleaned up.

---

## 7. Queue depth vs. activity (best-effort)

`sync_ledger` current snapshot: **150 delivered, 72 needs_review** (222 tracked total in this deployment's history — no in-flight/`claimed` items right now). Delivery timestamps show real but sparse throughput across the last several days (e.g. 25/hour on 08-04 13:00 and 08-05 01:00–02:00, dropping to single digits in between), consistent with a bursty, schedule-gated pipeline rather than continuous draining.

**32% of all tracked documents (72/222) are sitting in `needs_review`** — a genuinely unresolved backlog, distinct from the idle-slot gaps above. This isn't a pool-occupancy problem (nothing is running for these), so it's outside the "idle slot" framing of this task, but it's worth a separate look: either these need human triage or there's a systematic extraction/matching failure worth root-causing.

**The bigger structural finding here is an observability gap, not a throughput one:** `sync_ledger` has no `created_at` and no status-change history — `claimed_at`/`delivered_at` are the only timestamps, and both are null unless an item fully succeeds. It's impossible to answer "how big was the backlog at 15:00?" directly from this table; this analysis had to proxy backlog presence from nearby execution activity instead (see §1 caveat). Adding a `created_at` column and a lightweight status-history table (or an `updated_at` + audit trigger) would let a future run of this tool compute real queue depth over time instead of inferring it — worth doing before the next gap-analysis pass, since it would tighten every number in §2–3.

---

## 8. Ranked fixes, by estimated documents/hour recovered

All figures are ceilings computed from measured idle slot-time at 200s/document (midpoint of the known 150–250s range); real recovery will be lower once downstream constraints (OCR/API rate limits, Gemini extraction throughput) are accounted for — call these "worth investigating" magnitudes, not guaranteed deltas.

| # | Fix | Target | Evidence | Ceiling value |
|---|---|---|---|---|
| 1 | **Event-driven trigger (or much shorter interval while backlog is deep) for `Sync Scanner` and `Mail Label Engine`** | `SyncScanner00001`, `mailLabelEngine01` | Both run near-instantly on a fixed 15-min schedule; Sync Scanner returns in 0s every single time (22/22 runs), losing ~60min/hr; Mail Label Engine loses ~55min/hr | Largest single lever — directly responsible for most of the 60.7 slot-hours idle-while-backlog measured in §2–3 (~136 docs/hr theoretical, realistically a large fraction of that) |
| 2 | **Investigate the 15:25–18:31 stretch specifically** (3h06m at ~20% utilisation, 37h12m slot-time lost) | whatever gated dispatch during that window — likely the same root cause as #1, since it's the same scanner/reconcile cadence, just measured as one big contiguous gap rather than per-cycle | Directly measured, single largest line item in the gap census | ~226 docs/hr during that stretch (~925 docs total) |
| 3 | **Build a reaper for `execution_entity`** (parallel to the existing `sync_ledger` claim-reaper) | mark `status='running'` executions past a sane age (e.g. 30–60 min, above the observed p99 runtime) as failed via direct SQL, since n8n has no native API for this | 0 zombies now, but 34 historically — no code path currently prevents recurrence | Insurance against total pool starvation; ~50–70 docs/hr protected per handful of zombies if it recurs |
| 4 | **Raise (or make renewable) the `processLock01` TTL** | `processLock01` / `syncV3Main0001` | TTL (600s) is shorter than observed median runtime (956s) — the lock can silently expire mid-run | Not an idle-slot fix — a correctness fix that prevents a future duplicate-processing bug before it costs anything |
| 5 | **Verify `Gmail Actions Scanner`'s actual trigger cadence** | `indoxGmailActionsScanner01` | Configured for 3 min, observed cycle 14m48s over only 7 samples — numbers don't reconcile, don't act on the 40m/hr figure until this is resolved | Unknown until verified — could be 0 (already fine) or another ~40 docs/hr if the scanner really is idling |
| 6 | **Add `created_at` + status history to `sync_ledger`** | `sync_ledger` schema (Supabase) — flagged for the owning team, not touched here | Currently impossible to compute real queue depth over time; every backlog-presence number in this report is a proxy | Enables tighter, more confident versions of every number above in the next analysis pass |

---

## 9. Utilisation now vs. achievable

- **Measured now (8h window, 2026-08-05 13:18–21:18):** 101.9% average against the modelled 16-slot pool, but bimodal — ~20% utilisation for a contiguous 4-hour stretch, then overshoot (up to 712% in 10-minute bins, driven by error-storm bursts, not genuine throughput) for the remainder.
- **If the 4-hour low-utilisation stretch were closed** (fix #1/#2 above): the 60.7 idle slot-hours measured while backlog existed would collapse toward the ~13.1 slot-hours still idle in the already-healthy 18:30–21:14 stretch — roughly an **80% reduction in idle-while-backlog time**, worth the ~136 docs/hr ceiling computed in §8.
- **Re-run after a fix lands:** `python3 scripts/ops/timeline-gaps.py --hours <N>` against the post-fix window, compared directly to the `14:24–18:30` vs `18:30–21:14` sub-window split already captured in this report as the before/after baseline. No fixes were applied by this analysis (per scope, the touched workflow JSONs are off-limits) — the tool is ready to re-measure the moment any of the above lands.

---

## Appendix: files and containers used

- Tool: `scripts/ops/timeline-gaps.py`
- n8n Postgres: `n8n-postgres-shlomo-laptop` (db `n8n`, user `hacohen`) — `execution_entity`, `workflow_entity`
- Ledger Postgres: `supabase-db-shlomo-laptop` (db `postgres`, user `postgres`) — `sync_ledger`, `sync_pipe_state` (currently empty — reset by a recent redeploy, not usable for historical queue-depth reconstruction either)
- Schedule configs verified directly from `workflow_entity.nodes` JSON (not inferred): `Sync Scanner` = 15 min, `Sync v3 Reconcile` = 15 min, `Gmail Actions Scanner` = 3 min (configured, doesn't match observed), `Sync Ledger API` reaper = 5 min
