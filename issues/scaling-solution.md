# INDOX Scaling Solution

**Status:** v1 — written 2026-08-11 ~17:00Z from the live session record. A parallel deep-scan of the
full session transcript, all subagent transcripts, the repo issue files and git history is running;
its findings will be merged as v2. Anything below marked *(unverified)* is awaiting that scan.

**Purpose:** the durable record of how this pipeline scales, what its real ceilings are, and which of
them are architectural rather than resource limits. Written because the working configuration was lost
once and had to be rediscovered from first principles.

---

## 0. THE BINDING CONSTRAINT — `doc_action` locks are acquired and never released

Found and proven 2026-08-12 ~22:30Z. **This is the single defect gating the 800/hr target.**

`indoxV2Driver01` / node `Check LOCKED` acquires via `check_and_lock` with
`PROCESS='doc_action'`, `KEY='<ID>::<ACTION>'`. **No workflow anywhere — active or inactive — calls
`unlock` with `PROCESS='doc_action'`.** The only three real unlock callers all pass the
*pre-migration* shape `PROCESS='doc_step'`, `KEY='<ID>'`:
`indoxApiSupabase01.json:870`, `indoxDocBatchUpsert01.json:80,153`, `errorHandler01.json:139`.

Acquire and release address **different keys**. Locks therefore only ever die of TTL (live 5400s).

Evidence:

| measurement | value |
|---|---|
| redis `process_lock` keys | 4,516 — of which **4,514 `doc_action`, exactly 1 `doc_step`** |
| `<doc>::extract_base_doc` keys | 697, vs max concurrent `BaseDocEx01` ever observed = 19 → **≥97% stale** |
| docs with `BASE_EXTRACTION_COMPLETED='true'` still holding a lock | **491** |
| TTL spread (n=400) | near-uniform 27–5324s, mean 2796s — pure decay, never release |
| driver funnel (`If NOT LOCKED`) | 91 candidates → 2 · 100 → 4 · 100 → 0 |
| share of each offered 216-doc window already locked | **75.9%** |

This is *why* the drainer looked capacity-limited when it was not: dispatch swung 1–68 drivers/pass,
in-flight capped at 54 on a box proven to run 440 concurrent, and 44% of passes picked a single row.
Three-quarters of every offer was debris.

**It also masqueraded as correct behaviour.** Lock-skip IS correct by design when another workflow
genuinely holds the document — so the skip logs looked healthy. They were skipping documents nothing
was working on. Any future "the drainer is skipping, that's by design" claim must first prove the
holder is alive.

**Root cause is a repo/live divergence:** the acquire side was migrated to `doc_action` +
`<ID>::<ACTION>` **on the live instance only** (repo `indoxV2Driver01.json:130-132` still says
`doc_step`), and the release side was never migrated at all. A second divergence: live TTL 5400 vs
repo `processLock01.json` 1800.

Fix: release on **both the success and the failure exit** (success-only is the same bug in slow
motion — the failure path is what accumulates), land the acquire change into the repo, and migrate
the three dead `doc_step` callers.

Capacity was never the problem. At the measured 66.0s mean and 1 document per execution, Little's law
puts the ceiling at **1,036/hr**, and ground truth already reached **579/hr for a full clock hour**.

### 0.1 The consequence nobody could see: `Process Blocked Error` records nothing

Found 2026-08-12 ~00:40Z, and it is the reason the leak was so expensive.

When `indoxV2Driver01`/`Check LOCKED` finds `<ID>::<ACTION>` already held, `If NOT LOCKED` goes false
and the line lands on **`Process Blocked Error`**, a `stopAndError`. The action never runs, **nothing
is written** — no ACTION_LOG, no `updated_at`, no `NEXT_RETRY_AT` — so the row stays perfectly
eligible and the drainer re-offers it on every pass for the **full 90-minute TTL**.

| measurement | value |
|---|---|
| `Process Blocked Error` ran (n=250 driver executions, independently verified) | **210 = 84%** |
| `Execute Action` ran | 141 = 56% |
| documents stuck ≥60 min and offered ≥5× | **855, consuming 14,023 of 20,656 offers = 67.9%** |
| of those, holding a `doc_action` lock right now | **796 = 93%** |
| median staleness vs TTL | 76–88 min vs 90 min — one TTL exactly |

**Why no amount of error-hunting would ever find it.** The blocked line dies on its own branch while
sibling lines continue, so the execution finishes `status=success`. Hours were spent decoding
`execution_data` for errors; this never appears there. It was found by measuring **offers versus
progress**, not by measuring failures. When a queue is full and the box is idle, count what is being
*offered* and what actually *moves* — not what errors.

**The actual root cause, found 2026-08-12 ~01:00Z: the back-off existed and pointed at nothing.**
The blocked branch called `Call 'Snooze Incoming Document'` → workflow id **`bdchh5urW9lBzudZ`**,
which **does not exist** — 0 rows in `workflow_entity`, 0 executions ever, no workflow of that name
among the 90 on this instance. Because the node used `waitForSubWorkflow: false`, the failed launch
returned its input items immediately and surfaced nothing: it ran as a **pure pass-through in 674 of
824 driver executions**. The intended 180-second snooze had never once been applied.

**Generalise this:** an `executeWorkflow` node with `waitForSubWorkflow: false` pointed at a missing
or renamed workflow is *completely silent* — no error, no failed execution, correct-looking runData.
It is indistinguishable from success in every signal except the effect never happening. When a
mechanism "exists" but its effect is absent, verify the target id resolves before debugging the
logic. Cheap check: `select count(*) from workflow_entity where id = '<the id in the node>'`.

Fix as landed: `Blocked: Build Backoff` → `Blocked: Batch Upsert` → `Blocked: Resume` →
`Process Blocked Error`, with an **escalating ladder 5 → 15 → 45 → 90 min** rather than a flat
interval. Justified by measurement, not taste: of 600 held locks the median remaining TTL was 1,265s
and **only 4% were under the 180s the original design used**. Normal contention clears at the first
rung; a leaked lock costs ~4 offers over 90 minutes instead of ~39. The step is the trailing run of
blocked markers in ACTION_LOG, so any real action resets it — and it needs no Redis round-trip.
Written as a name+epoch **pair**: being refused is not an attempt, and a triple would walk blocked
documents into `MAX_ITERATIONS` for the crime of being busy.

Measured effect: documents offered ≥5× went **1,350 (91.8%) → 0 (0.0%)**; max offers to any one
document **23 → 4**; mean offers per document **9.7 → 1.8**; distinct documents reached per pass
**92 → 488 (5.3×)**; blocked dispatches that record anything **0 → 100%**.

**Related measurement defect, fixed with it:** `Record Base Doc Failure` writes
`, Extract Base Doc FAILED (reason), <execid>` — **with no epoch**. Every epoch-keyed rate query in
this system (the harness included) therefore scores those documents as zero-growth even though they
*were* recorded. Any rate measured before that fix undercounts.

### Secondary, will bind next: the `Check Capacity` gate proxies the wrong thing

The gate counts *total in-flight execution rows*, which correlate only weakly with extraction load
(Pearson r=0.635, r²=0.404, n=31). It fired gear 0 in 9/31 passes — including passes where the
extractor count was 0 and 2, dispatching nothing while extraction sat completely idle. The clause
that actually fires is **`drivers >= 30`**, not `inflight >= 75` (which never tripped once in 75
minutes of observation; in-flight peaked at 54). Thresholds were calibrated when a pass was 156 rows;
a pass is now 1,944. Raised to `drivers >= 70` / `inflight >= 150` (gear 1 at 40/90) as a measured
step; the correct long-term proxy counts **extraction workflows**, not all execution rows.

---

## 0a. THE HEADLINE FINDING — the scaling configuration was never lost

Verified live 2026-08-11 ~17:15Z by a dedicated scan of the session, all subagent transcripts, the
repo and git history.

**The owner was right that a working scaling setup existed, and it is STILL IN PLACE.** At peak the
topology was:

- **2 local workers × concurrency 8 + 5 remote workers × 8 = 56 Bull slots**
- four SSH tunnels
- haproxy sending **~95% of OCR** to the portable box
- the driver's **self-webhook loop** turning at **~3,156 hops/hr — 91% of all driving**

Every one of those is live right now, and *measurably healthier* than at peak: remote job duration is
**20.7s now vs 79.3s then**, and remote workers took **261 of 368 job starts (70.9%)** in a recent
20-minute window.

**What stopped was not the configuration — it was the flywheel.** Driver `mode='webhook'` went
**1,250 per 15 min at 14:15Z → 0 from 15:10Z** (§1.1).

**And the crucial structural point:** there were **no drain workflows at peak**. Base extraction ran at
only **67–85/hr** then. The peak throughput was carried by the **tail** — completing documents that had
already been extracted. That is why fixing extraction (§1.2b) raised extraction 5× without moving
completions, and why the completion path is the correct target.

## 0. The one-paragraph summary

INDOX is **dispatch-limited, not capacity-limited.** Sixteen local worker slots routinely sit at
under 10% utilisation with an empty Bull queue while thousands of documents wait. Every throughput
problem investigated on 2026-08-11 resolved to *how work is handed out*, never to CPU, RAM, workers,
or network. The portable laptop's value is **apitools offload (~80% of OCR/JSON-query load), not n8n
workers** — a remote worker is worth ~16% of a local one. Adding capacity without fixing dispatch
changes nothing, and this was measured twice.

---

## 1. The dispatch architecture — the real ceiling

There are exactly **three** mechanisms that hand work to `indoxV2Driver01`, and until 2026-08-11 all
three were structurally incapable of draining a backlog.

| mechanism | cadence | what it can see | ceiling |
|---|---|---|---|
| `indoxV2Driver01` Schedule Trigger | **hourly**, `{"field":"hours","triggerAtMinute":5}` | whole corpus, walked from the top | one pass/hour |
| `indoxApiSupabase01` → `Get Changed Docs` → `Process Changed Doc` | every 5 min | **only rows whose `updated_at` moved** | see below |
| `indoxV2TailDrain01` | every 5 min | only docs **past per-type extraction** | `LIMIT 25` × 12 = **300/hr** |

### 1.1 The flywheel collapse (the most important failure mode here)

The change feed is a **change feed, not a queue**. It only sees documents that recently changed.

- While work flows: processing updates documents → the poll sees them → more work is dispatched. Self-sustaining.
- When work stops: nothing changes → the poll sees nothing → nothing is dispatched. **The system cannot restart itself.**

Measured 2026-08-11 15:31Z: 85 rows updated in the last 5 minutes against **11,368 open documents**.
Driver `mode='webhook'` dispatch went 975 per 10 min (14:15) → 35 (14:30) → **0** (15:10 onward).

The only thing that can re-prime it is the driver's own sweep — which runs **once an hour**. A pipeline
that stops at 14:30 therefore stays stopped until 15:05 at the earliest, and if that sweep spends its
budget on extraction (it does), the tail never recovers.

**Consequence for operators:** after ANY event that stops the pipeline (a deploy, a restart, an error
storm), it must be re-primed manually or it will idle indefinitely. `scratchpad/prime_once.sh` invokes
the driver's own sweep via the REST run endpoint; `scratchpad/primeloop.sh` does it every 5 minutes,
gated on the driver's own recent activity.

### 1.2 The sequential ceiling

`indoxV2TailDrain01` uses `Drain Loop` (splitInBatches) with **batchSize = 1** and
`Driver: Run By ID` with **`waitForSubWorkflow: true`** — strictly sequential.

Measured: ~7.2s per document (a 25-document pass took 179.6s; later passes 77–90s).

> **A single sequential drain lane can never exceed 3600 / 7.2 ≈ 500 documents/hour**, no matter how
> large its `LIMIT`. Raising `LIMIT` alone moves the ceiling from 300/hr to ~500/hr and then stops.
> Exceeding that requires **concurrency** — either bounded parallel fan-out, or multiple lanes over
> disjoint candidate partitions (partitioning preserves per-lane backpressure and is the safer shape).

For extraction the arithmetic is far worse: `BaseDocEx01` is p50 **43.1s**, p95 **168.4s**, max 375.0s.
A sequential 5-minute pass moves ~7 documents. Extraction drains **must** fan out concurrently.

### 1.2b THE SOLUTION THAT WORKS — async fan-out dispatch (measured 5x)

This is the single most important section of this document. It is the pattern to copy.

**`indoxV2BaseDrain01`** (display name *"indox-v2 Stage Drainer"*):

```
Every 5 min (scheduleTrigger)
  -> ONE selection query for the entire pass          (not per item)
  -> Drain Loop (splitInBatches, batchSize 4)
  -> Driver: Run By ID (executeWorkflow, mode: once, waitForSubWorkflow: FALSE)
  => 12 parallel chunks of 4
```

| window | n | rate |
|---|---|---|
| before — 12:40–15:40Z (3h) | 226 | **75.3/hr** |
| after — 16:15–17:00Z (45m) | 286 | **381/hr** |
| peak 15-min bucket | 130 | **520/hr** |

15-minute buckets across the change: `15:30│25  15:45│19` → `16:00│51  16:15│77  16:30│130  16:45│77`.
First pass converted **24/24** documents to `BASE_EXTRACTION_COMPLETED` + `API_TOOLS_ID` within 5.5
minutes.

**Sizing arithmetic — derive this, never guess it.** `Loop Base Doc` in `indoxV2ActionsGlobal01` is
`splitInBatches batchSize=1`, so a group runs strictly serially and duration is linear in group size
(n=59: 23 lines/938s, 15/585s, 13/581s, 6/251s) ≈ **100s fixed + 41s/doc**. Therefore
`100 + 41×4 = 264s < 300s` tick. `LIMIT 48` fills the slots → **576 docs/hr offered**, peaking at ~12
of the 16 worker slots. Steady state is self-limiting: `base_running` peaks 8–12 after a pass and
drains to 1–2 before the next.

**Why one query covering all stages beats per-stage drains:** the selection query covers base,
company-id, type and per-type together, and an **md5 rotation makes each stage's share proportional
to its depth automatically** — the exact property the change feed's fixed weights lack. Live pick:
27 base / 7 company / 14 per-type from a pool of 8,313.

**What does NOT work: a bigger synchronous batch.** Raising `indoxV2TailDrain01`'s `Drain Loop`
batchSize 1→25 with `mode: once` was tried and **rolled back**: the intended `line_count=25` signature
never appeared across 6 passes, `select_invoice_values` stayed at `line_count=1`, pass duration went
77–90s → 220–331s, and it produced `Connection terminated unexpectedly` errors. The gain comes from
**`waitForSubWorkflow: false` + many small parallel chunks**, not from batch size.

**Why the change feed could never do this job.** `indoxApiSupabase01 :: Get Changed Docs` is capped at
`LIMIT 120` split across 11 slices by **fixed weights**. Live attribution (n=120): only 40 rows needed
base extraction, while 18 slots went to per-type (population ~1,200), 15 to recov, and **7 to rows
already COMPLETED**. The 6,337 untouched base-needing rows reached only `s_new` (16 slots, ordered
`updated_at DESC` — deterministic, so it re-offers the same head every pass) and `s_old` (6 random).
**~22 slots against 6,337 rows.**

### 1.2c Deployment gotcha: a NEW workflow's cron does not register via CLI import

`indoxV2StageDrain01` was created and is **deactivated**, because `import:workflow` **does not compute
`triggerCount` for a NEW row** (it preserves it for existing ones), so its cron never registered. Only
an n8n main restart would fix that. Keep it deactivated or delete it — if it ever activates it would
duplicate the working drain's coverage.

### 1.3 Stage coverage — three of four stages had no drain

Measured 16:42Z, after base extraction was fixed:

```
awaiting base extract (pt 1)   8,202   → indoxV2BaseDrain01 (new 2026-08-11)
awaiting per-type extract      1,313   → NO DRAIN — hourly driver only
awaiting company id            1,128   → NO DRAIN — hourly driver only
awaiting selection               682   → tail drain, LIMIT 25, sequential
awaiting mark_completed          174   → tail drain
```

Fixing one stage moves the queue downstream. `indoxV2StageDrain01` was created 16:43Z to address this
*(effect unverified at time of writing)*.

---

## 2. The portable laptop

**Hardware:** `192.168.16.103`, user `shlomy`, **4 cores** (`nproc`; the owner sometimes says 6),
15GB RAM. On **2.4GHz WiFi with no ethernet interface** — confirmed by the owner, not changing.

### 2.1 What it is actually worth

| measure | value | n |
|---|---|---|
| max stable remote workers | **5** — a 6th and 7th *reduced* total throughput | — |
| remote job success rate | comparable to local (152 ok / 3 err vs 265 / 1) | ~300 |
| `Incoming Documents v2` duration | **61.4s remote** vs 10.3s local | 764 / 2,209 |
| `Action Router` duration | **100.6s remote** vs 15.0s local | 624 / 1,558 |
| apitools call latency | **39ms through tunnel** vs 2.6ms on-box | — |
| **capacity value of a remote worker** | **≈16% of a local one** | derived |

An earlier estimate put it at 26%; the measured figure is 16%. The gap is entirely the tunnel: every
apitools call a remote worker makes travels back to the host and returns.

> **The highest-value unexploited optimisation:** make remote workers call the apitools instance **on
> their own box** (2.6ms) instead of tunnelling to the host (39ms). This attacks the 6x duration
> penalty directly and is worth more than the worker count. **Caveat flagged and not yet resolved:**
> there is a file-locality constraint that makes the naive routing change wrong — documents may exist
> on only one side. Investigate before changing routing.

### 2.2 What it IS doing well — apitools offload

haproxy `be_split/remote` **UP**: 9,008 sessions vs 1,230 local; **71 of 87 requests (81.6%)** in a
3-minute sample went to the portable box; 0.35% lifetime 5xx, zero in the preceding 30 minutes.

This is the box's genuine contribution: it absorbs ~80% of OCR/JSON-query load off a host that runs
at 130–300MB free RAM. **It must not be disturbed.**

It survives WiFi drops because it is the **`-L` direction, bound on the host**, unlike the workers'
`-R` tunnels.

> **Probe trap:** haproxy listens on **8080/8404**, not 80. A probe against `:80` returns `http=000`
> and was misread as "the LB is broken". It was never broken.

### 2.3 The tunnel fault — CORRECTED 17:05Z, the first diagnosis was wrong

> **Superseded.** An earlier lane concluded the workers were dead because WiFi drops left half-open
> sshd sessions holding the `-R` ports. A later lane disproved both halves of that: **the 5 workers
> were never stopped** (continuous job starts at 14:24, 14:45, 15:20, 15:30, 15:48, 16:01 and onward;
> the apparent outages were queue starvation), and the port-binding failure had a different cause.
> Killing orphaned `sshd-session` processes — the action that was blocked by the permission classifier
> — **would not have fixed it.** Recorded here because the wrong diagnosis was acted on for ~40 minutes.

**Actual root cause: a regression introduced by the previous lane's own SSH fix.** The
`Host portable 192.168.16.103` stanza it added carried **`ControlMaster auto`**. All four tunnel
supervisors connect by **literal IP**, so that stanza matched them and turned every one into a mux
*slave*. Their `-R` forwards leaked into a single master process and were never released when the
slave exited, so each next iteration hit an already-bound port, `ExitOnForwardFailure` fired, and the
supervisor exited instantly — forever.

**Measured: 1,334 ssh spawn/exit cycles in 10 minutes** across the four supervisors, every one a
no-op, with the whole tunnel estate hanging off one unsupervised mux process.

**The data-correctness bug this hid — a real split-brain.** Because leaked forwards stay bound while
their owner is gone, `apitools_tunnel_watchdog.sh` rebuilt the apitools tunnel with **only the
`-L 18080` traffic leg**, silently dropping **`-R 19118`**, the shared OCR-cache Postgres leg.
haproxy saw a healthy traffic leg and kept sending the remote instance **81.6% of requests**, while
`ocr_cache.py` **fell back to a local JSON file cache**: **5,296 warnings in 6 hours**. This is
precisely the split-brain that `tunnel.sh`'s own comments say the single-connection design exists to
prevent. Residue: ~**1,345 orphaned OCR results** in `~/apitools-storage/ocr_cache/*.json` on the
portable, invisible to the estate — `/docExists` answers "false" for them, so INDOX may re-OCR.

**The fix applied:**
- Split the SSH config: `portable` keeps multiplexing for interactive use; the bare
  `192.168.16.103` stanza gets **`ControlMaster no` + `ControlPath none`**, so supervisors never mux.
- Stopped `apitools_tunnel_watchdog.sh` (rebuilt a partial leg set) and `meshtunnel_watchdog.sh`
  (duplicate owner of 19001–19020); started the repo's supervised `tunnel.sh` with **all three legs**.
- `apps/apitools/scale-out/tunnel.sh` now carries `-o ControlMaster=no -o ControlPath=none` and a
  comment stating that **any watchdog must restart *this script*, never a hand-rolled subset of legs**.

**Protocol-level proof** (not TCP connects — a TCP connect always succeeds against a dead tunnel):
redis 19019 → `-NOAUTH`; n8n-postgres 19120 → `N`; **ocr-cache 19118 → `N` (was ABSENT)**; supabase
19018/19028 → `N`; apitools-lb and n8n-main → HTTP 200.

| metric | before | after |
|---|---|---|
| apitools call from a remote worker | 446.1ms (n=12) | **53.8ms** (n=12) |
| host `-L 18080` leg | 0.75s (n=3) | **0.011s** (n=3) |
| remote job duration | 79.3s (n=4,502) | **20.7s** (n=49) |
| ssh spawns / 10 min | ~1,334 | **0** |
| worker error lines | 157 / 60 min | **0 / 7 min** |
| OCR file-fallback warnings | 5,296 / 6h | **0** since 16:50:38 |
| host RAM available | 139MB free | **2,096MB** |

**Throughput still did not move** — `bull:jobs:wait` was **0 in all 14 samples**. Capacity has never
been the binding constraint, so latency work cannot raise throughput until dispatch is fixed.

**Still durable-fix pending:** `ClientAliveInterval 300` / `ClientAliveCountMax 2` in the portable's
`/etc/ssh/sshd_config.d/99-hardening.conf` needs sudo with a password. At current settings a WiFi drop
self-heals in ≤10 min (supervisors retry every 5s until sshd reaps the half-open session) rather than
never — an acceptable interim state.

### 2.4 SSH access

Access was **never broken**. WSL simply had **no `~/.ssh/config`, no default-named key, and no
ssh-agent**, so `ssh shlomy@192.168.16.103` had no identity to offer while
`ssh -i ~/.ssh/portable_key ...` worked immediately. Fixed with a `Host portable` stanza
(`IdentityFile ~/.ssh/portable_key`, `IdentitiesOnly yes`, ControlMaster persistence).

### 2.5 WiFi latency work

Applied on the host laptop, persisting across reboots (rollback at `scratchpad/rollback.txt`):
- radio power-down disabled — `PnPCapabilities = 24`
- roaming scans disabled — `RegROAMSensitiveLevel = 127`

| | before | after (claimed) | re-measured later |
|---|---|---|---|
| host → router | 46ms | 1ms | — |
| host → portable | 70ms | 11ms | **avg 11.8ms, min 3.8ms** ✅ |
| max spike | 97ms | 4ms | **max 50.7ms, mdev 15.1ms** ❌ |
| throughput | 0.62 MB/s | 0.70 MB/s | — |

**The ~6x average-latency improvement is real and confirmed. The "max spike 4ms" claim does not hold**
— jitter remains substantial. Remaining constraint: the router's client-to-client forwarding (every
byte crosses the air twice through a low-end CPU).

**Critically: the latency fix produced no throughput gain**, because (a) the workers' reverse tunnels
were down, so nothing reached them, and (b) nothing was queued anyway. Verified: TCP connect to the
portable's apitools *through the tunnel* timed out at 5.00s on 5 of 5 attempts, while the host-bound
`-L` leg answered in 0.00036s.

Proposed and **not applied**: SSH compression, ControlMaster multiplexing, mosh, rsync-over-scp,
5GHz hotspot (Phase 2), router settings (Phase 3), NIC driver update. Items 1–4 are zero-risk and
benefit interactive/dev work rather than pipeline throughput.

---

## 2.6 apitools: conditionally stateless, and how to scale it

Investigated 2026-08-11 17:20Z. Full detail in `scratchpad/apitools-scaling.md`.

**Verdict: conditionally stateless, NOT stateless.**

| what | where | shared? |
|---|---|---|
| OCR result JSON (full text + geometry, keyed by document md5) | `public.ocr_cache` — 8,042 rows, **306 MB** | **YES**, both instances |
| byte artifacts (originals, rasters) | each box's **own local disk** | **NO shared filesystem** |

Host holds 13 GB / 12,529 files; portable 4 GB / 3,687. The `files/` sets are nearly **disjoint**
(intersection 320 of the portable's 2,111). The portable reaches the shared table over the
**`-R 19118`** tunnel leg — verified live from inside `apitools-remote`: `PG OK ('postgres','172.18.0.33')`.

### File-locality — resolved by direct test, and it does NOT block on-box routing

Tested against a document whose source file exists **only on the host**, called on-box on the portable:

```
/docExists          -> 200  exists:true
/documentJsonQuery  -> 200  RESOLVED, real OCR metadata     <- the extraction path works cross-box
/documentImage      -> 404                                   <- the raster path does not
```

And decisively: **no n8n workflow calls a raster endpoint.** 25 references to `/documentJsonQuery`,
5 to `/documentOcr`, 1 each to `/docExists` and `/docGen`; **zero** to `/documentImage`,
`/documentDraw`, `/documentOcrDraw` — those are browser UI traffic. So the earlier lane's
file-locality caveat is real at the storage layer but is **not a blocker for worker routing**.

### Three corrections to what was previously believed

1. **`OCR_CACHE_BACKEND=postgres` does NOT make Postgres failure fatal — it is a no-op.** `postgres`
   is already the default, **neither container sets the variable**, and it is exactly what was running
   during today's 6-hour silent split (§2.3). The only special value is `"file"`. Both `load()` and
   `save()` catch all exceptions and fall through to the local file write. **Strict mode requires a
   code change** — the proposed guard does not exist.
2. **Recovery from that outage was accidental.** `db.py` caches the connection in a module global and
   never resets it — there is no reconnect logic. Workers recovered only because
   `gunicorn.conf.py max_requests=50` recycles them every ~35–65 requests. **If anyone restores the
   old value of 1000, a future split lasts hours instead of minutes.**
3. Orphaned local OCR results number **1,171**, not 1,345 — 174 of them did reach the shared table.

### The "single db drive" question

**Not a bottleneck:** 99.97% overall cache hit, 98.6% on `ocr_cache`, max 9 connections from any
client, 869 GB free on `/dev/sdc`. **But it IS a single point of failure with a silent failure mode**
(see correction 1), and it grows ~**100 MB/day with no eviction path** — already 65% of the database.
The nearer disk risk is the **portable at 91% full, 22 GB free**.

### Scaling unit — confirmed as the owner stated

Last 24h engine mix: **google 1,983 / pdf_textlayer 931 / tesseract 0**. The historical
`OCR_ENGINE=local` drift is gone and both instances read `google`. **Caveat:** 32% of documents never
reach Google — text-layer extraction and PDF rasterisation are real local CPU/memory work, so apitools
is not purely an IO layer.

### Recommendations

- **On-box routing for portable workers: safe on file-locality grounds, but NOT YET** — `bull:jobs:wait`
  was 0 in 14/14 samples, so a 20× latency win on an idle queue buys nothing. Revisit when there is a
  real backlog.
- **When it is done, run a small haproxy ON the portable** mirroring the existing `be_split`/
  `be_localfile` split — **not** a `localhost:8080` rewrite. A rewrite loses the 404→peer retry, 429
  spillover, redispatch, and the only split-brain detector in the system.
- **Against session affinity / consistent hashing:** for `be_split` it is pure loss, and for rasters it
  is actively wrong — a file exists wherever the OCR happened, which no hash can predict.
- **New config drift found:** `dev_signer.p12` exists on the host and **not** on the portable. Since
  `SIGN_CERT_P12` is empty on both, the first signed `/docGen` served by the portable will mint a
  *second, different* self-signed certificate.

## 3. The host, and why capacity cannot grow locally

**6 cores, 9.95GB RAM.** The binding constraint is **memory, not CPU** — free RAM routinely
130–300MB with ~3.3GB of swap in use while CPU sits at 38–40%.

- **16 worker slots** = 2 workers × `N8N_WORKER_CONCURRENCY=8`, pinned in `perf-profiles.yml` with
  documented OOM history. **Do not raise.**
- **Do not add containers on the host.** There is no RAM for them.
- Do not raise postgres `max_connections`; do not restart `n8n-postgres`.

### 3.1 `incoming-documents` — NOT a leak. glibc arena sprawl. **RESOLVED 2026-08-11 22:38.**

**This section previously said "leaks ~400MB/hour" and named `GUNICORN_MAX_REQUESTS` as the real
fix. Both were wrong.** There was no leak to bound, and the container was never going to be fixed by
recycling it. Recorded here in full so it is not re-diagnosed from scratch.

**What it actually was.** glibc sizes its malloc arena limit from the **host's** core count, not the
cgroup's. `nproc` reports 6 inside the container, so glibc permitted `8 x 6 = 48` arenas of 64MB
(~3 GB of heap spread) for a service whose `cpu.max` is `100000 100000` — exactly **1.0 CPU**, i.e.
one thread running at a time. It had spread across **19 arena heaps holding 402.5 MiB committed**,
65% of the worker's 623MB RSS. Arenas exist to cut lock contention between threads running
*concurrently*; at a 1.0-CPU quota every arena past the second is a private free list that is never
reused and never returned to the kernel.

The amplifier is glibc's **dynamic mmap threshold**. A 722KB–1.3MB page raster starts above the
128KB threshold, so it is mmap'd and returned to the OS on free — but glibc then *raises* the
threshold to the size of each mmap'd block it frees (up to 32MB). After a few rasters every later
one is served from an arena instead, where freeing returns it to a free list rather than the kernel.

**Why it is not a leak, proved three ways.** (1) During a measured +567MB climb (22:14 137MiB →
22:28 704MiB) the traffic was 236 requests, **86% of them `POST /documents/thumbnail`** — an endpoint
whose raster is a request-scoped `r.content` in `_thumbnail_from_apitools`, retaining nothing
process-global. (2) `/app/.storage/extraction-runs/latest.json`, the persisted snapshot of the
in-memory run/result dicts, was **142 KB, last written Aug 6** — the accumulators were inert.
(3) Memory *oscillated* (614→634→618→611 MiB) rather than rising monotonically.

**Why `GUNICORN_MAX_REQUESTS` was correctly ruled out.** The process tree is a master plus **one**
worker — `apps/indox/app/gunicorn.conf.py` sets `workers=1, worker_class=gthread, threads=8`, because
the BFF holds authoritative in-memory run state. With one worker there is no sibling to absorb
traffic during a retire, so `max_requests` is a serving gap, not a graceful handover. (It would still
have beaten `docker restart` — the master holds the listen socket and `graceful_timeout=60` lets
in-flight work finish — but it treats a symptom that was not the disease.)

**The fix** — `apps/indox/docker-compose.yml`, three env vars, no code change, cap left at 768M:

```
- MALLOC_ARENA_MAX=2          # match the 1.0-CPU budget, not the host's 6 cores
- MALLOC_MMAP_THRESHOLD_=131072   # stop the ratchet; document buffers keep going to mmap
- MALLOC_TRIM_THRESHOLD_=131072   # keep the main arena's top trimmed
```

**Measured result** (26-min windows, equivalent volume — 4,796 vs 4,974 executions):

| | before | after |
|---|---|---|
| arena heaps / committed | 19 / 402.5 MiB | **0 / 0.0 MiB** |
| peak memory | 751.7 MiB (**97.88%**) | 324.8 MiB (**42.3%**), mean 263.0 |
| `memory.events max` | ceiling hit repeatedly | **0** |
| error rate | 43/4,796 = **0.897%** | 3/4,974 = **0.060%** |
| distinct workflows erroring | **12** (broad scatter = killed in-flight work) | **1** |
| container restarts | 5 guard recycles that night | **0** |

Memory now falls as well as rises (298→295→283→277→273 MiB) and held flat through an 89.5% CPU
burst. **`scratchpad/incdocguard.sh` is stopped and renamed `.RETIRED`** — the crutch is gone, and
its 20-minute `docker restart` was itself the single largest error source on the document path.

**Same defect, same fix, applied to the siblings 2026-08-11 23:22 / 23:24** (all `nproc`=6 against a
sub-1-CPU quota):

| service | cap / CPU | arenas before | `events max` before | mean before → after | after |
|---|---|---|---|---|---|
| `mailapi` | 512M / 0.75 | 11 (634.7 MiB rw-p) | **722** | 246.0 → **62.1 MiB** | 0 arenas, `max 0` |
| `console` | 256M / 0.5 | 15 (572.2 MiB rw-p) | **7857** | 145.9 → **43.8 MiB** | 1 arena (0.4 MiB), `max 0` |

`mailapi` was returning 500s to `incoming-documents` (`POST http://mailapi:8970/search` 500, 23:19)
before the change; since it, 202/202 requests served 200. Host `available` rose 2114 → 2945 MB.

**Deliberately NOT applied to `connections`** (35 arenas, 332.4 MiB of arena *address space*, but
RSS 30 MiB and `memory.events max 0` across 25h uptime — it has never once hit its ceiling). The
change would be pure tidiness and still costs a container recreate on a live service. Apply it the
next time that container is recreated for another reason.

**Deliberately NOT applied to `drive`** — its problem is different and arena tuning would not touch
it: `oom_kill 8`, `max 22877`, but only **2** arenas holding 1.7 MiB.

#### 3.1a STILL OPEN — unbounded caches in the incoming-documents source

Found while diagnosing the above and **proved not to be the cause** (see the 142 KB / Aug-6 evidence),
but they are genuine unbounded growth over long uptimes. In every case the TTL is **checked on read
only**: an expired entry is ignored but its value object is never freed, and there is no reaper and
no size cap. Ranked by retained size:

1. **`_SYNC_SRC_CACHE`** — `apps/indox/app/incoming_documents/api/__init__.py:1724`. Written by
   `_sync_cached` (1767, assignment 1784); never deleted on expiry. Values are full Drive folder
   listings (2529), whole Gmail message lists (2785), the entire `/sync/inventory` row set (3479),
   the indox match index (3367), dashboard payloads (6782). Key cardinality is genuinely unbounded —
   line 3455 embeds a `created_after` **date string**, so a new key appears as the window rolls.
   Eviction exists only as `_sync_cache_clear()` (1788), called from 7 **mutation** sites, so in a
   read-mostly steady state nothing ever fires it.
2. **`_RUNS` / `_RESULTS` / `_RESULTS_AI` / `_UPLOADS`** — `extraction.py:119,111,117,118`.
   `_prune_runs()` (163) bounds `RUNS_KEEP=400` **on disk only**; nothing bounds the in-memory dicts,
   a fresh `doc_id` is minted per upload (1349,1351), and `_load_state()` (193-195) re-hydrates them
   at import so the accumulation **survives restarts**.
3. **`_STATS_BUILD_LOCKS`** — `api/__init__.py:3972`. `setdefault` at 3987, **zero** cleanup anywhere;
   its sibling `_STATS_MEMO` is cleared but that function does not touch the locks dict. One
   `threading.Lock` leaked per instance/pipe-name pair, permanently.
4. **`_sync_cache`** — `api/__init__.py:5178`, a *second* cache inside `create_blueprint`.
   Name-collision hazard: `_sync_cache_clear()` operates on `_SYNC_SRC_CACHE`, not this one, so the
   mutation-flush paths never clean it.
5. **`_indox_folder_cache`** — `api/__init__.py:2028`. No TTL/bound; short id strings, low impact.

Also: `_TEST_RUNS` (77) *is* pruned (6698-6705), but only inside `POST /tests/run`, and entries with
`status=="running"` are exempt forever — a run whose background thread died is immune.

**Preferred fix:** one shared bounded-cache helper (size cap + sweep-on-write, or a single periodic
reaper) rather than five bespoke fixes, keeping the existing invalidate-on-mutation behaviour.

### 3.2 Worker wedging

autoheal restarted workers ~**9 times on 2026-08-11** on the signature:

```
liveness: WEDGED wait=3264 mine=0/8
```

— the worker holds **zero of its eight slots** while a job has waited up to 3,264s. A circuit breaker
fired once: *"3 restarts already in the last 6h and it is STILL unhealthy."* **Each restart crashes
in-flight executions.** Root cause not yet determined *(open)*.

Healthy workers report `liveness: OK wait=0 mine=N/8 :: queue empty - idle is legitimate`.

### 3.3 Postgres is NOT a bottleneck (verified)

25/100 connections, zero lock waits, longest active query 0.0s, heap cache hit ratio 0.9872.
Monitoring queries do sequential scans on `execution_entity` (no index on `startedAt` alone) but each
costs **17ms entirely from cache**. `execution_data` is 3,106 MB — large by design; the owner has
explicitly required execution history be kept. **No action needed; the drains can scale freely.**

---

## 4. n8n 2.17 deploy mechanics — the operational traps

These have each caused a real outage.

1. **`workflow_entity.nodes` is a DRAFT.** What executes is `activeVersionId → workflow_history.nodes`.
   Always verify against the live version.
2. **`import:workflow` sets `active=false` AND nulls `activeVersionId`.** Must be followed by
   `n8n update:workflow --id=<ID> --active=true`.
3. **An import file MUST have a top-level `name`** or it fails a not-null constraint.
4. **Activating an already-active workflow DEREGISTERS its crons.** `/tmp/reload.js` returns HTTP 200
   while doing exactly this — it caused a ~10-minute total outage. Only an explicit
   **deactivate → activate** cycle re-registers. Use `scratchpad/forcecron.js`.
4a. **BUT re-registration does NOT bust the DEFINITION cache — only a container restart does.**
   Proved on `indoxV2BaseDrain01` (`triggerCount=1`) 2026-08-12 ~22:40Z. A gate-threshold change was
   confirmed correct in **all four** storage locations — `workflow_entity.nodes`, `workflow_history`
   for the active `versionId`, `versionId == activeVersionId`, and the repo blueprint — while **four
   consecutive executions still ran the OLD parameters**, decoded from `execution_data."workflowData"`.
   None of these made the new definition execute:
   - `import:workflow` + `update:workflow --active=true` → storage updated, old definition runs
   - explicit deactivate → activate via internal `/rest/workflows/:id` PATCH, **HTTP 200/200**,
     `updatedAt` moved → old definition STILL runs
   - n8n **public** API `/activate` + `/deactivate` → the `N8N_API_KEY` in the repo `.env` is 21 chars
     and returns **401**; that route is unavailable on this deployment
   So for `triggerCount >= 1`, **a restart of `n8n-shlomo-laptop` is the only known activation path**,
   and `bbox n8n push` works only because it ends in one. Plan deploys around that: batch every
   `triggerCount >= 1` change into a single restart. `triggerCount = 0` workflows are unaffected —
   they load fresh at call time (verified: `indoxV2ActionsGlobal01`, `indoxDocBatchUpsert01`).
5. **"active = true" is NOT proof of registration.** Confirm real `mode='trigger'` executions appear.
6. **Batch changes into as FEW imports as possible.** Nine imports between 14:32 and 15:05 on
   2026-08-11 collapsed the pipeline from ~400/hr to ~30/hr — each import drops triggers, and the
   change-feed flywheel (§1.1) cannot restart itself afterwards.
7. **Never run `./bbox run`** — it POSTs `/api/reconcile` and pushes stale repo blueprints over live
   workflows. Blueprints are known stale on nodes (the driver blueprint has 131 nodes vs 133 live,
   with 8 live-only nodes).
8. Working deploy script: `scratchpad/p41_deploy.sh`. Credentials: `N8N_OWNER_EMAIL` /
   `N8N_OWNER_PASSWORD` in `deployment-hacohen/.env`.

---

## 5. Throughput history, honestly stated

| window | completions/15 min | rate | note |
|---|---|---|---|
| 12:45–13:15 | 118 / 129 / 103 | ~470–516/hr | the remembered "500/hr" |
| 13:30–14:00 | 89 / 79 / 86 | ~330/hr | |
| 14:15 | 56 | 224/hr | 668-error spike in this bucket |
| 14:30 | 27 | 108/hr | collapse |
| 15:30–16:20 | 3–8 | 12–48/hr | flywheel dead |

**~20% of the old peak was not real.** Linkless `BALANCE_SHEET` lines were completing with **zero
extraction** — no OCR, no API call, nearly free — inflating the rate. 673 were stamped on 2026-08-11
alone. Per 15-min bucket at peak: 118 total = 95 real + 23 false; 129 total = 106 real + 23 false.

> **CORRECTED 17:20Z from the app DB.** The table above is the *second shoulder*, not the peak. The
> real peak 15-minute bucket was **11:30Z at 142 = 568/hr**, and the best rolling hour was
> **11:15–12:15Z = 523/hr** — an hour and a half earlier than first reported. Deducting false BS
> completions, the **genuine peak was ~455–476/hr**, not the ~380–420 stated in v1. Current rate at
> the trough was 11 per 15 min = 44/hr, a **12.9× fall**.

**The collapse was caused by our own deploys**, not by load: **ten** `import:workflow` calls between
14:32 and 15:05 — 14:32:18, 14:36:47, **14:39:35** (`indoxDocBatchUpsert01`, omitted from the original
count), 14:47:16, 14:51:05, 14:53:57, 14:54:15, 14:54:39, 14:54:57, 15:04:47 — after which the
flywheel could not restart (§1.1). Fourteen if counted from 13:53:08.

### 5.1 Source-control risk — every scaling change is uncommitted

**204 files / +27,561 lines are uncommitted**, and the last commit is dated **2026-08-05**. Every
scaling change described in this document exists only in the working tree. This is why
**`git checkout` is forbidden** — it would destroy a day of work from many lanes at once.

---

## 6. Correctness fixes that affect the numbers

- **Linkless BS lines completing with no extraction.** In `indoxV2ActionsGDoc01 :: Decide GDoc Action ::
  invoiceDecide`, a BS line with no link failed **both** guards — exempted from the `MISSING_LINK` park
  *and* from every extraction step — then fell through `gdocTail` to `mark_completed`. 955 rows
  affected (**8.93% of all COMPLETED**). Fixed and verified: 0 false completions since 16:17Z, and the
  first pipeline-written `MISSING_LINK` for a BS line in this estate's history.
- **`settings.executionOrder` drift.** Four workflows lost their settings block, dropping
  `executionOrder: v1`. Under legacy ordering, sibling execution order is data-shape dependent, so
  `Join LOCKED` could run before `Check LOCKED` and throw *"Node 'Check LOCKED' hasn't been executed"*.
  Measured: v1 workflows 0.146% error rate vs unset 4.36%, and the driver alone at **10.45%**
  (738 of 7,062). Restored from blueprints; driver errors → 0.
- **Absent-mutex guard.** `Join LOCKED` now fails **closed** when `Check LOCKED` has no run data,
  because that node runs `check_and_lock` — it *acquires* the lock. An absent reply means no lock was
  held, so proceeding would process unlocked. (The pre-existing fail-*open* for *incomplete* replies is
  correct and unchanged.)

---

## 7. Measurement traps — every one of these produced a wrong answer today

- **Count completions by STATUS delta over a window.** Never by `updated_at`. Never by an ACTION_LOG
  stamp when measuring a *current* rate (acceptable only for retrospective shape, labelled as such).
- **`LIKE '%STATUS COMPLETED%'` also matches `STATUS COMPLETED3`** — the OLD-**demotion** node. Anchor
  on `'STATUS COMPLETED,'` with the comma.
- **A trailing 60-minute bucket is not a rate.** A "709-error crisis" turned out to be a burst that had
  already ended; the live rate was 0.7%.
- **A single sample is not a pattern.** One instantaneous `docker stats` reading made two healthy
  workers look catastrophically imbalanced (99.43% vs 6.73%); their 20-minute job counts were the
  opposite (111 vs 268). One n=1 execution sample refuted a hypothesis that n=40 then confirmed.
- **`group by 1` fails** with *"aggregate functions are not allowed in GROUP BY"* when the selected
  column contains an aggregate — group by the real column. **Do not pipe psql stderr to `/dev/null`
  while developing a query**; several sections silently rendered empty and were nearly reported as
  findings.
- **In psql, `(x = y)::text` yields `'true'`/`'false'`, not `'t'`/`'f'`.** A loop testing `= "t"` never
  matched and deactivated a live router six times.
- **`execution_data` is `flatted`-encoded** — every object, array *and string* deduplicated into a
  top-level array and referenced **by index**. A regex for `"message":"..."` returns an index, not text.
  **The index is a STRING of digits, not a number.** The payload literally reads
  `{"version":1,"startData":"1","resultData":"2",...}` — the `"2"` is a reference; the bare `1` in
  `"version":1` is a real value. So a dereference must test `typeof v === 'string' && /^\d+$/.test(v)`,
  never `typeof v === 'number'`. Three decoders in a row returned `(unresolved)` or printed node names
  as `8`/`4`/`6` because they tested for numbers. Root is `arr['0']`; the failing node is
  `resultData → lastNodeExecuted` and the cause is `resultData → error → message`, each hop dereferenced.
  Working decoder: `scratchpad/decode_err.js` (env `WF` = ILIKE workflow pattern, `MINS` = lookback).
  When a decode returns nothing, **dump the first 500 raw chars and look at the shape** before writing
  a fourth guess — that is what finally settled it.
- **A TCP connect / `nc -z` ALWAYS succeeds against a dead tunnel** — sshd accepts before trying the far
  end. Use real protocol probes (redis `PING` → `+PONG`, postgres SSLRequest).
- **`curl /healthz` returns 000 on every worker**, including healthy ones.
- **Host WSL is UTC+3, the portable is UTC**, and `docker logs --since` uses the *client's* zone — the
  same nominal window returned 575 vs 26 results.
- **Git Bash rewrites `/mnt/c/...` paths** before handing them to `wsl` (→ `C:/Program Files/Git/mnt/c/...`).
  Prefix `MSYS_NO_PATHCONV=1`, or use the PowerShell tool.
- **A monitor's own filter can hide its failure.** A grep for `INDOX|FATAL|ERROR` silently swallowed
  *"No such file or directory"*, making a broken monitor look like a quiet one.

---

## 8. Standing operational rules (from the owner)

1. **Never move items or edit DB rows to make numbers change — fix the pipeline.** "we aim to perfect
   state machine". Reading is unrestricted.
2. **Keep the 5-minute polling window.** Shorter windows fragment batches and are measurably *slower*.
3. **Cheap actions (selection, status update) must be batched** — "minimal execution / code node
   always run once for all". A stage converting far below what it is offered is per-item execution,
   not missing capacity.
4. **Lock skip is correct by design** — it means another main workflow holds the line. Never "fix" it.
5. **Do not disable n8n execution history** — needed for debugging; storage is not a concern.
6. **`indox api` should be the only point that talks to the DB.** Four workflows still bypass it with
   raw SQL *(open)*.
7. **Work locally, push to stage** — never fix things only on the running box.

---

## 9. Open items

- **Portable reverse tunnels down** — the 5 remote workers cannot consume. Fix requires §2.3; the
  process-termination route is blocked by the permission classifier.
- **Remote apitools routing** (§2.1) — the largest unexploited gain; blocked on the file-locality question.
- **`GUNICORN_MAX_REQUESTS`** unset; leak held back only by a stopgap recycler.
- **Worker wedge root cause** (`mine=0/8` with large `wait`) undetermined.
- **All watchdogs/supervisors are session-scoped bash loops** and die with the session — no durable
  mechanism (cron/systemd) is installed. This directly contradicts "so it never happens again".
- **45 of 66 active workflows have no `executionTimeout`**; their blueprints declare none, so setting
  one would be inventing policy.
- **Four workflows bypass `indox api` with raw SQL:** `Backoff + Dead-letter`, `Record Base Doc Failure`,
  `Terminalize Stalled`, `Build Merge Write`.
- **Blueprints are stale on nodes** — reconciling would revert live work. Settings-only reconciliation
  was done deliberately; do not extend it to nodes.
- **955 falsely-completed BS rows** await a bounded one-way re-open to `MISSING_LINK` (proposal in the
  BS lane's report; would correct COMPLETED downward by ~8.9%).
- **`dbTime.getTime is not a function`** — n8n-internal (`db-clock.service.js`), a symptom of brief
  postgres connection timeouts. Not ours; low frequency.
