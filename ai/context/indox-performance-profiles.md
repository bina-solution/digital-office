# INDOX performance profiles — resource-matched work progression (design, 2026-07-08)

## The measured problem (1h window, parallel batteries, this laptop)

apitools: 2,604 requests, **active 72% of the wall hour**, `/documentJsonQuery` alone
10,382 busy-seconds (2.9 CPU-hours) against a 4-CPU cap. **In-flight demand p50=7, p90=20,
max=36 — against a 6-slot blocking gate** (598 queue events/h). Ideal query cost ~0.3s;
observed p50 3.16s, p95 31s = **10–100× queue inflation**. Meanwhile n8n's main workflow
burned 11,303 CPU-s across 1,010 entries (178 killed by the table-change trigger flood),
and the lock/router chatter added 7,200 sub-executions.

Root: **the feeder (n8n) and the consumer (apitools) are sized independently and neither
derives from the actual machine.** n8n pushes up to 36 concurrent OCR/KW calls (2 workers ×
8 + webhook fan-out 5 + suite drivers) into 6 slots on 4 CPUs. Every layer's batching
constant (fan-out 5, scanner take 50, chunk 25, batch-upsert 25, poll intervals, worker
concurrency 8, gunicorn 16) is hardcoded somewhere different — .env, compose defaults,
workflow constants, settings rows.

## Principle

One machine envelope → ONE profile → every concurrency/batching knob derived from it and
routed through the SAME config mechanism we built for backends (.env → settings row →
default, applied at `bbox n8n push`). No knob lives hardcoded in a workflow.

**Sizing rules (steady-state, IO+OCR mixed load):**
- apitools gunicorn workers ≈ cores × 1.5 (mostly CPU-bound short requests)
- apitools query slots ≈ cores × 1.5 (queue must live in n8n retries, not 75s soft-timeouts)
- apitools OCR slots ≈ max(1, cores / 2) (Tesseract is fully CPU-bound)
- n8n worker concurrency (each) ≈ cores × 1.5 (executions are IO-wait-heavy)
- extraction fan-out ≈ min(query_slots, worker_concurrency / 2) — the feeder must never
  exceed the consumer's gate by more than ~2× (that's the whole game)
- scanner take / sync chunk / batch-upsert stay throughput knobs, scaled with fan-out
- main trigger: debounce/lock-early so surplus row-change deliveries die in <0.5s

## The profiles (committed as production/perf-profiles.yml)

| knob | ci-small (2c) | laptop (12t) | vps (4c) | prod (8c) |
|---|---|---|---|---|
| N8N_WORKER_CONCURRENCY | 4 | 8 (×2 workers) | 6 | 8 (×2) |
| APITOOLS_GUNICORN_WORKERS | 4 | 16 | 6 | 12 |
| APITOOLS_MAX_CONCURRENT_JSON_QUERY | 3 | 16 | 6 | 12 |
| APITOOLS_MAX_CONCURRENT_OCR | 1 | 5 | 2 | 4 |
| perf_extract_fanout (settings) | 2 | 6 | 3 | 5 |
| perf_scan_take / perf_sync_chunk | 25 / 10 | 50 / 25 | 50 / 25 | 50 / 25 |
| perf_batch_upsert | 10 | 25 | 25 | 25 |
| test budget scale | 1.5 | 1.0 | 1.25 | — |

`PERFORMANCE_PROFILE=<name>` in .env; `bbox n8n push` resolves the profile file →
(a) substitutes the workflow constants (fan-out width in the batch-extract splitInBatches,
batch sizes) exactly like `substitute_backend()`, (b) upserts the `perf_*` settings rows,
(c) ci-env.sh just sets the profile name. Compose reads the APITOOLS_*/N8N_* values from
.env as today — the profile GENERATES that .env block (bbox writes it under an
`# ── perf-profile:<name> ──` marker).

## Work-progression fixes the profiles unlock (ranked)

1. **Feeder/consumer match** (fan-out ≤ slots): kills the 10× queue inflation and the
   retry-exhaustion flakes (empty dates). Biggest single win on every envelope.
2. **Trigger-flood debounce**: main's row-change webhook entries that lose the redis lock
   must exit at node 1 (<0.5s); today they crash (178/h) or burn 5.9s medians. Profile knob:
   `perf_main_max_parallel_docs` backing the lock breadth.
3. **Main per-entry config cache**: settings/companies/tag_rules per entry × 1,000
   entries/h — short-TTL redis cache row keyed by updated_at (scale-priority carryover).
4. **Adaptive stretch (later)**: apitools already exposes `/api/queue` depth via
   any-concurrency; the extraction fan-out could read queue depth and self-throttle.
   Static profiles first — measure, then decide if adaptivity pays.

## Stability + configurability contract

- Every knob has: profile value → settings-row override (ops, no deploy) → hardcoded default
  (= prod values). Grep-provable single mechanism, same as backends.
- Profiles are COMMITTED and diffable; changing a machine's behaviour = 1-line .env change
  + `bbox n8n push`; CI proves ci-small on every run; the acceptance run (Phase 3) proves
  prod values under 100-doc load.
- No workflow may read $env or invent its own constant — push-time substitution only,
  keeping n8n's env-block security posture.

## Status / next steps

- [ ] perf-profiles.yml + n8n-push substitution + settings upsert (mirror substitute_backend)
- [ ] Replace hardcoded fan-out 5 / chunk 25 / take 50 with substituted constants
- [ ] Main lock-early exit (kills trigger-flood cost) + measure crash count → 0
- [ ] Local laptop profile: raise apitools slots/workers → re-measure query p50 (expect ~0.5s)
- [ ] CI stays ci-small; prove parallel battery under it
- [ ] Phase-3 acceptance run pins the prod profile numbers


## FULL inventory + exact change markout (scan 2026-07-08, all active WFs)

Three classes — do NOT treat them the same:

**A. True concurrency controls → become profile knobs (exact targets):**
| # | workflow :: node / param | today | change to |
|---|---|---|---|
| 1 | Orchestrator - Parallel Document Processing :: `Rate Limit Batches` (splitInBatches) | `batch_size ǀǀ 5` | default → `perf_extract_fanout` (substituted) |
| 2 | indox-v2 Actions — BS :: `Loop Over Items7` + `Loop Over Items` (batchSize 5 = BS extract fan-out feeders) | 5 | `perf_extract_fanout` |
| 3 | Query PURCHASE_ID :: `Extract AFTER1/BELOW1` http-batching {5, 5-10s} — ONLY this Query has pacing! | inconsistent | ALL 5 Query WFs get `{batchSize: perf_apitools_feed, batchInterval: perf_apitools_feed_ms}` |
| 4 | indox api - supabase :: `Poll Line Changes` schedule 30s + `Get Changed Docs` limit 40 | fixed | `perf_line_poll_s` / `perf_line_poll_limit` |
| 5 | Incoming Documents v2 :: `Wait` (random 3–9s jitter) + `Loop Over Items37/38` (5/6) | fixed | `perf_main_jitter_max_s` (0 on ci/laptop), fan constants |
| 6 | Gmail scanners ×3 :: Schedule 3min | fixed | `perf_scanner_interval_min` |
| 7 | Sync Scanner/Scan Unit :: Schedule 15m, take 50, chunk 25, gmail take 10 | fixed ×2 places | `perf_sync_interval_min` / `perf_sync_take` / `perf_sync_chunk` |
| 8 | Batch Upsert (+legacy Create/Update paths) :: `Wait 35s` | sheets-era throttle | verify dead post-tier-2; live → `perf_upsert_wait_s` (0 supabase) |
| 9 | .env/compose: N8N_WORKER_CONCURRENCY, worker count, APITOOLS_GUNICORN_WORKERS, APITOOLS_MAX_CONCURRENT_JSON_QUERY/OCR, APITOOLS_PDF_DPI | scattered | generated `# perf-profile:<name>` .env block |
| 10 | indox-test CLI: budgets, --budget-scale, watch-poll, suite pg_sleep | CLI consts | `perf_test_budget_scale` etc. |

**B. Correctness-serializers (batchSize=1) — PINNED BY DESIGN, profiles must NOT touch:**
Gmail scanners `Loop Over Gmails` (overlap-safety: in-progress tag AFTER search), Sync
Processors `Loop Over Items`, Search File(+Warehouse), Label Engine loops, suite Fx/Seed
loops. Documented so nobody "optimizes" them into races.

**C. Plain chunkers (batchSize 25–150 in Actions engines, Lines Batching 15000/1000) —**
memory/DB-churn shaping, NOT parallelism (splitInBatches is sequential). Leave as
constants; only `perf_batch_upsert` (25) graduates to a knob.

**Mechanism:** committed `production/n8n/perf-manifest.json` = list of
`{file, node, paramPath, knob}`; `bbox n8n push` loads profile + manifest and rewrites the
staged workflow JSONs (python, exact paths — no sed fragility), upserts `perf_*` settings
rows, and writes the .env block. Same lifecycle & grep-provability as backend substitution.


## MEASURED 2026-07-08 (first stamped report, laptop slots-only trial)

Battery green 4/4 with auto-report ✓. Query p50 UNCHANGED (3.15s) at 16 slots — because
apitools stays cgroup-capped at cpus:4; the gate moved from slots to CPU. LESSON: the
profile env MUST include container CPU limits (APITOOLS_CPUS, worker cpus) via compose
${VAR} substitution — knob class 11, missed by the markout, caught by the report's first
run. Also: duplicate .env keys (manual edits + appended block) → the marked profile block
must REPLACE, not append. Both = first items of B1 wiring.

## MEASURED 2026-07-08 PM — knobs 11/12 + the two melt lessons

- ci-small GREEN ON CI (f7109ac): low profile + parallel battery proven remotely.
- knob-11 warm trial (slots16/cpus8→rejected→ran at 4): gdoc 585→377s, pipeline →564s,
  query p50 3.15→2.02s — CPU raise works.
- COLD-OCR melt: 5 OCR slots @4G mem = gunicorn SIGKILL OOM storm, 32/46 documentOcr = 500,
  'Tesseract process timeout'. OCR slots must derive from MEMORY (~1.5-2G per cold
  multipage OCR). knob 12 = APITOOLS_MEM (+ mem-derived ocr slots).
- **Docker VM envelope, not host**: VM has 6 CPUs/12G (host 12t) — cpus:8 REJECTED by
  daemon and the pipe masked it (old container kept running = garbage run). Rules: size
  profiles to `docker info` NCPU/MemTotal; NEVER pipe-mask `compose up` exits; verify the
  container env/limits after every recreate.

## OFFICIAL COLD BENCHMARK (2026-07-08, laptop profile: cpus5/mem6G/q16/ocr3/OMP1)

Full parallel battery, ocr_cache WIPED (real Tesseract per doc), ALL assertions green:
bs 73s | doc_base 163s | gdoc 646s (reproducible ±2%) | pipeline 778s = **13-min wall**.
Zero OCR/query errors across the run. Baseline (pre-profile, 6 slots/4cpu, warm!) was
~11-13 min — i.e. the profile absorbed the ENTIRE cold-OCR cost. OMP_THREAD_LIMIT=1 is
load-bearing: without it, 3 concurrent cold OCRs thrash to 120s timeouts (melt captured).

Live-captured for B3 (twice): doc_step locks survive dead action chains (~15min TTL,
no release-on-failure) — froze 4 docs 5+ min mid-run; also main-vs-deleted-rows orphan
locks. THE Phase-3 pre-arm item, now with repro.
Benchmark procedure gotcha: inter-run row DELETEs race the sync layer's re-ingestion
(organic twins/locks) — clean runs need lock-clear + tolerate organic co-load.

## Upload-path audit (2026-07-08, user-prompted — 671 Upload runs/30min)

VERDICT: no re-upload bug. Design works: Decide runs `get_api_tools_id` FIRST (persists to
row), KW actions gated on `doc.API_TOOLS_ID`, Upload flow short-circuits HASH→docExists→
Return (no download). The 203 downloads/15min = ORGANIC first-touches: every inter-run row
DELETE re-triggered sync re-registration → new doc generations → legitimate re-derivation.
Residual optimization (B2, medium): Query WFs still spawn the Upload sub-execution per call
just to docExists (~308 sub-execs/battery, avg 4.0s span incl. queue). An IF-bypass inside
each Query WF (API_TOOLS_ID present → skip the Upload call entirely) saves ~250
sub-executions/battery — but downstream nodes reference $('Upload OR Get…') by name
(paired-item), so the bypass must present the same output shape. Do with fresh context.
Also confirmed: any-concurrency 'parallel N' rows = occupancy stacking, not suite lanes;
suite-internal lane parallelism remains the queued CLI-managed refactor.

## B2-item-1 MEASURED (2026-07-08, warm, laptop: line-poll 10s + slots 8 capacity-matched)

doc_base 71s | bs 76s (both best-ever) | gdoc 410s | pipeline 589s — wall 9.8 min, ZERO
errors (the same verification bursts that soft-timed-out at slots=16 flow clean at 8).
Reading: line-poll 10s transforms the SHORT suites (chain-hop latency dominated); the long
suites are extraction/verification-bound — their floor needs fan-out/jitter knobs, suite
lanes, and the Upload-call bypass. Slots MUST be capacity-matched (cpus×1.5), never
demand-matched — 16 slots on 5 CPUs = 75s soft-timeout storms (measured live).
B1 chain GREEN ON CI (25dc08e): profile file → apply → env block (cpus/mem per profile) →
ci-small battery + stamped report.

## B2-items-2/3 MEASURED (2026-07-08, warm, laptop: + fan-out 6, main-jitter 0)

doc_base 140s | bs 154s | gdoc 620s | pipeline 748s — wall 12.5 min, full green (execs
101593/94/97/98). CAVEAT: heavy co-load (agent editing/pushing on the same machine), not
head-to-head with the clean B2-1 run (71/76/410/589). Knobs 2/3 target long-suite
extraction fan-out; clean re-measure rides the next battery (Upload-bypass verification).
CI on 3b146b2 carries the same knobs for runner-side timing.

## Upload-call bypass MEASURED (2026-07-08, cold battery)

140 Upload sub-executions/battery vs ~308 baseline (55% cut); remaining callers are
by-design: Figure Document Type (classification first-touch) + Action: Get API_TOOLS_ID
(GDoc/Ship routers) + first-touch per doc. Zero Query-WF Upload calls (was ~250-300).
gdoc cold 620-630s with bypass vs 646-658s before. GOTCHA (cost a doc_base red): bypass
merge Code nodes MUST be multi-item-safe — DOC BASE batches N docs through one Figure
Document Type call; runOnceForAllItems + `return [{json:$json}]` collapses N→1 and
downstream per-ID lookups explode. Map $input.all() with pairedItem.

## CI lanes verdict + local drive sync proof (2026-07-09)

CI --lanes REVERTED after one measured red: 10 concurrent lane executions oversubscribe
the 2-vCPU runner (ci-small worker concurrency 4) — lane webhooks queue behind each other
until the HTTP clients time out (gdoc 0/7 transport at ~1380s). Lanes are LOCAL-only;
cold OCR is the runner's floor, serial-suite --parallel (#38, 11.3-min battery) is the
proven CI shape. If CI lanes are ever wanted: raise ci-small worker concurrency AND wave
the lanes (≤4 concurrent), or wait for a bigger runner.

Local drive sync PROVEN live end-to-end on a brand-new pair: created lfdemo-* folder keys
→ registered as 4th drive-gdoc registry pair → 3 fresh docs uploaded to its to_sync →
claim (files moved to in_progress) → registered → pipeline COMPLETED ×3 (companies
resolved, renamed in place) → files advanced to lfdemo-dest-synced. drive.localhost view
links serve (host alias added; route previously listened only on drive.${DEV_DOMAIN} —
and after re-upping storage, traefik held a stale backend IP until restarted).
KNOWN BLEMISH: one successful doc's file was advanced to the failed folder
(outcome-mapping gap in Sync Scan Unit's Apply Outcome — doc state unaffected; same
class as the acceptance-findings claim-outcome gap). Fix with the on-fail hardening item.

## pipeline lanes + full-lane battery — GREEN (2026-07-09)

Pipeline suite laned (cov/bare/batch via pipeline-e2e-lane webhook; chain gates keep
manual 'all' serial; NOTE: suites carrying lane webhooks MUST be active:true in the
blueprint or the production webhook never registers). Full battery, both suites laned,
cold OCR: doc_base 348 / bs 148 / gdoc 7/7 773s / pipeline 3/3 833s — quality intact
(14/17+pins, bare 4/4). Cold wall ~14min unchanged: with everything in ONE concurrent
wave, the 3 OCR slots are the floor (total Tesseract work is constant). Lane value =
per-check latency (cov 35s, lc 188s vs 620s serial) + warm/CI overlap + pipeline no
longer serial-chained. CI switched to --parallel --lanes. Also: localmail label
bootstrap runs at battery start (local mode); n8n-push sweeps stale doc_step locks
after its restart; 3b prune landed (blueprint 136→102, 34 archived incl. legacy
scanners/mains + caller-less dup Query INVOICE_ID; Batch-Upsert "dead island" was a
stale finding — its webhook chain has a live caller TTgW5l6qnQjsLwfM).

## gdoc lane parallelism — 7/7 PROVEN (2026-07-09, battery #3 cold + solo perr)

Battery #3 (cold, all-parallel + lanes): doc_base ✅282 / bs ✅108 / pipeline ✅784 /
gdoc lanes: extract ✅51 / cov ✅64 / lc ✅104 / batch:inv ✅538 (5/5) / batch:ord ✅536
(5/5) / batch:shp ✅538 (4/5+pin) / perr ✅ solo after fix. Extraction quality identical
to serial (14/15 + known pin). Battery wall ≈ 13min, pipeline-bound. THREE lane gotchas
fixed en route: (1) n8n Wait node parks execution 'waiting' → pending lane-webhook
response DROPPED (empty body) — poll loops must sleep via Code
`await new Promise(r=>setTimeout(r,15000))`; (2) lane-scope every shared-corpus toucher
(Verify Batch WHERE, Batch Config ids/knownPins — were built pre-filter → lanes drove and
verified all 15 docs, "N/15 drifted"); (3) prelude cleanups per-lane (done at design).
Batch lanes are extraction-bound (3 OCR slots = ceiling) — lane wall gain over serial is
modest cold (~538 vs 620) but short lanes finish 5-12× sooner and warm/CI overlap wins.

## gdoc lane parallelism (B2 item 2) — original design notes

7 webhook lanes (batch:inv/ord/shp, lc, extract, cov, perr) as independent executions;
CLI merges verdicts (--lanes). Proven: 7 concurrent lane execs + 3 suites = 10-way.
Lane verdicts round 1: perr 188s / cov 215s / extract 215s / lc 305s ✅✅✅✅ (lc alone
beats the serial suite's 620s wall by 2×). Batch lanes died at ~390s round 1: apitools
was RECREATED mid-battery by a parallel session (compose up from WSL picked up new
APITOOLS_* env) — environmental, not design. Under cold OCR the batch lanes contend for
the same 3 OCR slots, so lane speedup is capped by apitools throughput (extraction-bound).
process_lock chatter: 703 spans/12min — batch lock ops are a future optimization.

## B3 shipped (2026-07-08): perf_lock_ttl_s knob + errorWorkflow coverage

Third live capture confirmed the freeze shape: 13 locks acquired in one ~5s wave, 2
running executions, docs frozen 15min. Fix: TTL now profile-driven (laptop 300 / ci 480 /
vps 480 / prod 600) via 3 manifest entries into process_lock; errorWorkflow=Error Handler
(EH Unlock Doc via redis lock-map) set on 9 chain WFs that lacked it. Kills still leak
locks (n8n fires no error workflow on kill) — TTL bounds the damage window.

## CI publish loss (found via user report, 2026-07-08)

Green runs #30/#31 generated real results/CSV but `.ci-cd/indox-e2e/latest` kept failed
run #29's files: plain `git checkout -B _publish FETCH_HEAD` refuses to move onto a tip
whose last publish commit touches the same untracked generated paths (error hidden by
2>/dev/null) → commit lands detached → `push _publish:` = "src refspec does not match".
Fix: park generated files in mktemp dir → `checkout -f` → restore → commit → push.
The "export failed — supabase-db-ci unreachable" CSV = failed run #25 (stack never
healthy), preserved only because later green publishes were lost.
