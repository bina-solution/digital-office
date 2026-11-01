# INDOX — Final Scale Architecture — 2026-08-05

Read-only design deliverable. Builds on, does not re-derive, `INDOX-CODEBASE-MAP-2026-08-05.md`,
`INDOX-CONSOLIDATION-PLAN-2026-08-05.md`, `INDOX-TARGET-ARCHITECTURE-2026-08-05.md`,
`INDOX-UNIFIED-N8N-SPEC.md`, `THE-PLAN.md`, `COVERAGE-RECONCILIATION-2026-08-05.md`. Where this
document adds new evidence beyond those (the per-hop cost chain in §1, the apitools batching gap in
§2, the live v1/v3 parallel sync engine identified by file in §5), it says so and cites the exact
read. Everything else is cited back to the source document rather than restated as new.

**Verified this session, live, via WSL `docker exec` against `n8n-postgres-shlomo-laptop` /
`supabase-db-shlomo-laptop`** (numbers below are used throughout, not re-derived per-section):

| Fact | Value | How |
|---|---:|---|
| Host memory | 9,950 MiB total, 4,451 MiB free / 6,420 MiB available at check time | `free -m` |
| Host cores | 6 | `nproc` |
| n8n workers | 2 containers × `--concurrency=8` (`N8N_WORKER_CONCURRENCY`, default 8) | `platform-base/n8n/docker-compose.yml:303,429` — confirms the brief's "16-slot pool" exactly |
| PostgREST row cap | `PGRST_DB_MAX_ROWS: ${SUPABASE_PGRST_DB_MAX_ROWS:-1000}` | `apps/supabase/docker-compose.yml:24` — env unset in `.env`, so **1000 is live today**, not historical |
| `sync_ledger.needs_review` | **72** | `select count(*) from sync_ledger where status='needs_review'` — matches the brief exactly |
| `incoming_documents."NEXT_RETRY_AT"` populated | **0 of 56,213** | direct count — table has grown since the morning docs (6,196→56,213; other agents' backfill/injection work is live during this session) — the 0-of-N finding is unchanged in kind, worse in absolute count |
| `apps/drive` memory limit | was **256M**, raised to **384M** today, same day | `apps/drive/docker-compose.yml:79-87`, in-file comment: *"0.5 CPU / 256M was starving the process under real concurrent sync traffic... every non-download request timed out"* — **confirms the OOM-at-256MiB claim exactly, and confirms it was already partially fixed today** |
| Recent `indoxProcessDocument01` executions (n8n `execution_entity`, `status='success'`, last 15) | 36.0s – 244.4s, mean of this small sample ≈ 123s | live query — same order of magnitude as the brief's 211.8s mean; large spread is itself evidence for §1 |
| apitools JSON-query concurrency slots | `cores + 2` = **8** on this host | `apps/apitools/src/utils/autoscale.py:93-94` |
| apitools OCR concurrency slots | `max(1, cores-1)` clamped by memory (0.9 GiB/slot + 0.7 GiB base) | `apps/apitools/src/utils/autoscale.py:81-90` |

Live system caveat, inherited from every prior doc in this series: other agents are actively changing
this instance while these numbers were taken (`incoming_documents` grew 9× mid-session). Treat every
absolute count as "as of this read," every ratio and structural finding as durable.

---

## 1. The per-document cost budget, attacked

### 1.1 What `indoxProcessDocument01` (907 lines, 20 nodes, mean 211.8s) actually does

Direct read of `apps/indox/blueprint/n8n/indoxProcessDocument01.json` — node list and the connection
graph (not inferred from the name):

```
Before Start → If Testing Mode → If Didnt Get Settings
  → Companies Loader   [httpRequest → http://n8n:5678/webhook/company     , retryOnFail maxTries=4]
  → Query Settings     [httpRequest → http://n8n:5678/webhook/queries     , retryOnFail maxTries=4]
  → Settings Loader → Start
  → Document OCR       [httpRequest → http://apitools:8080/documentOcr   , retryOnFail maxTries=4]
  → Call 'Figure Document COMPANY_ID'   [executeWorkflow → indoxV2FigureCompanyId01, 1,282 lines/31 nodes]
  → Extract InvoceId   [httpRequest → http://apitools:8080/documentJsonQuery, retryOnFail maxTries=4]
  → Extract ShipmentId [httpRequest → http://apitools:8080/documentJsonQuery, retryOnFail maxTries=4]
  → Extract Purchase ID[httpRequest → http://apitools:8080/documentJsonQuery, retryOnFail maxTries=4]
  → Map Extractions → Document Properties → Validate Document
```

This is a **strictly serial chain of 7 network calls**, each independently retried up to 4× on
failure (fixed 3,000 ms wait, no jitter, no cap on the multiplicative effect of retries stacking
across 7 sequential hops). That serial structure — not any single call — is the dominant cost:

| Segment | What it is | Real work / avoidable overhead |
|---|---|---|
| **Companies Loader + Query Settings** | Two `httpRequest` calls from `indoxProcessDocument01` **to n8n's own webhook endpoint** (`http://n8n:5678/webhook/company`, `.../webhook/queries`) — a workflow calling back into the same n8n instance over HTTP instead of `executeWorkflow` (in-process) or a direct read | **Pure avoidable overhead.** Company/settings config changes rarely; this is per-document data that should be cached, not re-fetched over a self-loopback HTTP round-trip on every single document. Confirmed by `indoxV2ActionsGlobal01`'s `Companies` node doing the same pattern with `load_settings:false` (target-architecture doc, §Part 2 #3) — this loopback-fetch pattern recurs at multiple hops in the pipeline, not just here. |
| **Document OCR** (`apitools/documentOcr`) | Real, necessary, per-document work — OCR of a new file is not cacheable the first time | Real work. Governed by apitools' own `ocr_slots_default()` = `max(1, cores-1)` clamped by memory — **6-core host → ~5 slots**, each slot memory-bounded (0.9 GiB/OCR + 0.7 GiB base per `autoscale.py:76-90`). Genuine, correctly-sized bottleneck. |
| **Call 'Figure Document COMPANY_ID'** | `executeWorkflow` call into a 1,282-line/31-node sub-workflow | In-process (no extra HTTP hop, n8n's `executeWorkflow` is native) but adds its own internal chain — not measured node-by-node this session (see limits below), flagged as the next place to look if OCR+3-extraction fixes below don't close the gap alone. |
| **Extract InvoceId → Extract ShipmentId → Extract Purchase ID** | **Three separate `httpRequest` calls to the identical endpoint** `http://apitools:8080/documentJsonQuery`, chained node-to-node (confirmed via the connections graph: `Extract InvoceId → Extract ShipmentId → Extract Purchase ID`, i.e. genuinely serial, not just visually laid out that way) | **The single highest-value fix in this document.** Each call independently: (a) does an HTTP round-trip n8n→apitools, (b) acquires one of apitools' `json_slots_default() = cores+2 = 8` concurrency slots (`ocr_api.py:53-104`, a real bounded-wait bulkhead — good pattern, see §3.2), (c) reloads `OcrObject.from_file_id(file_id)` (cached, but still a deserialize), (d) runs one `json_query`. Three sequential slot-acquire/release cycles instead of one. **apitools already has the fix built and shipped, unused by this call path**: `POST /documentDraw` (`apps/apitools/src/api/__init__.py:173-213`) accepts `{"file_id":..., "queries":[{"label":..., "ocr_json_query":{...}}, ...]}` and runs **all queries against one loaded `OcrObject`** in a single call — this is the exact multi-field-in-one-call shape needed here, already proven, just not wired to the JSON (non-drawing) response path `indoxProcessDocument01` needs. |

### 1.2 The fix, quantified

**Add `POST /documentJsonQueryBatch`** to `apps/apitools/src/api/ocr_api.py` (sibling to
`document_json_query` at line 131-154 and `document_draw` at line 173-213 — literally copy
`document_draw`'s "load once, iterate `queries[]`" body, drop the drawing/image-serving branch, return
`{"results": [{"label":..., "result":...}, ...]}`). Change `indoxProcessDocument01.json`'s three
`Extract *` nodes into **one** `httpRequest` node posting `{"file_id":..., "queries": [invoice_id_spec,
shipment_id_spec, purchase_id_spec]}`.

**What it buys, concretely:**
- 3 HTTP round-trips → 1: removes 2 of apitools' `json_slots` acquire/release cycles per document —
  at the 8-slot ceiling, this is the difference between one document occupying a slot 3× vs. 1×,
  directly increasing effective throughput under contention (the exact scenario a 50,000-document
  burst creates).
- 3 `OcrObject.from_file_id` reloads → 1: for a multi-page PDF this is not a trivial `dict` lookup —
  it deserializes the OCR JSON tree each time; doing it once removes 2 of 3 reloads.
- Removes 2 of 3 `retryOnFail`/`maxTries=4` exposure windows — today a single transient apitools
  hiccup on the *second* of three sequential calls costs up to `3 × 3s = 9s` of retry wait on top of
  the two calls that already succeeded and can't be "kept"; collapsing to one call means one retry
  budget, not three compounding ones.

**Also collapse the two self-loopback config calls.** `Companies Loader`/`Query Settings` should not
be `httpRequest` nodes hitting n8n's own webhook — either (a) switch to `executeWorkflow` (native,
zero network hop) calling the workflow that currently backs `/webhook/company`/`/webhook/queries`
directly, or (b) — better, since company/settings data changes on the order of hours not seconds —
add the same TTL-cache pattern the master plan already fixed once for the settings cache elsewhere in
this codebase (THE-PLAN.md, "the 20-minute settings cache" under "Backend" fixes) so repeat calls
within the TTL window return from cache with no network hop at all. Either fix removes 2 of the 7
serial network calls in this one workflow.

### 1.3 Target budget per hop

| Hop | Today (chain position) | Target | How |
|---|---|---:|---|
| Config load (company+settings) | 2 self-loopback HTTP calls, retried 4× each | **0 network calls** on a cache hit (TTL cache, e.g. 5 min) | Cache at the settings-read layer, mirroring the existing 20-min settings cache fix |
| OCR | 1 apitools call, real work, slot-bounded | **unchanged** — this is legitimate per-document cost, not overhead | Keep `autoscale.py`'s sizing; it is already right (§3.2) |
| Company-ID resolution | 1 `executeWorkflow` (31-node sub-workflow) | unchanged for now — flagged for a follow-up node-level trace (§ Limits) | — |
| Field extraction (invoice/shipment/purchase) | **3 serial apitools calls** | **1 apitools call** (`/documentJsonQueryBatch`) | §1.2 |
| Total serial network hops | **7** | **4** (OCR, company-ID subworkflow, 1 batched extraction call, upsert) | removes the 2 config calls + collapses 3 extraction calls to 1 |

**What this does NOT claim**: without per-node execution timing (this session's n8n API key returned
`{"message":"unauthorized"}` against `GET /api/v1/executions/<id>?includeData=true` — the key in
`.env` did not authenticate against the running instance; **this is a real, separate finding**: either
the key is stale or the running instance's owner/key pairing drifted, and it means exact per-node
millisecond attribution for `indoxProcessDocument01` **could not be obtained this session** — flagged
`UNVERIFIED`, not guessed at). What IS established by direct source read, not guesswork: the chain is
genuinely serial where three of its seven hops are provably redundant (same endpoint, same cached
input, three round-trips instead of one), and apitools already ships the code pattern that fixes it.
The quantified claim is "removes 2 of 3 extraction-call round-trips and both config-load round-trips
from the critical path," not a specific second-count, because the second-count requires the node
timing this session couldn't pull. **Task for the next session with a working API key**: re-run
`GET /api/v1/executions/<id>?includeData=true` (fix the key first — see task list §6, task T1) against
2-3 recent `indoxProcessDocument01` executions and attribute `resultData.runData[node].executionTime`
per node; this closes the gap between "structurally serial and provably redundant" (established) and
"exactly how many of the 211.8s seconds this buys back" (not yet measurable this session).

---

## 2. Batching design

Every site below is an **N-calls-where-1-would-do** pattern, named by file/node, per the task's
standard.

| # | Site (file:node) | Today | Fix | Buys |
|---|---|---|---|---|
| B1 | `apps/apitools/src/api/ocr_api.py` `document_json_query` route, called 3× serially from `indoxProcessDocument01.json`'s `Extract InvoceId`/`Extract ShipmentId`/`Extract Purchase ID` | 3 HTTP calls, 3 slot acquisitions, 3 `OcrObject` reloads for the same `file_id` | New `POST /documentJsonQueryBatch` (mirror `document_draw`'s already-proven "load once, iterate `queries[]`" shape at `apps/apitools/src/api/__init__.py:173-213`); one n8n node instead of three | §1.2 — the highest-value single fix in this document |
| B2 | `indoxProcessDocument01.json`'s `Companies Loader`/`Query Settings` nodes → `http://n8n:5678/webhook/{company,queries}` | 2 self-loopback HTTP calls per document, retried 4× each | TTL cache (mirror the existing 20-min settings-cache fix per THE-PLAN.md) or `executeWorkflow` | Removes 2 of 7 serial network hops per document |
| B3 | `indoxApiSupabase01.json`'s `Get Changed Docs` (`select "ID" from incoming_documents where ...`) followed by `Process Changed Doc → indoxV2Driver01 → Get Line By ID` (`indoxDocGet01`, a single-row `SELECT * WHERE "ID"=x`) | Up to 40 rows/tick: 1 query that reads only `"ID"`, then up to 40 **separate** single-row re-fetches of the same rows by ID | `Get Changed Docs` selects the full row (`select *`, not `select "ID"`) and passes the row payload as input to each `indoxV2Driver01` execution; `indoxDocGet01`'s hot-path call from this trigger becomes unnecessary (keep `indoxDocGet01` itself — it's independently used elsewhere, e.g. `Run By ID` per the target-architecture doc §1.1 — just stop calling it redundantly from this specific path) | Removes up to 40 redundant single-row `SELECT`s per 30s tick = up to 4,800/hr eliminated round-trips at the polling ceiling |
| B4 | `indoxV2ActionsGlobal01.json`'s `Companies` node → `indoxSettings01` with `load_settings:false` (target-architecture doc, Part 2 #3), invoked once per document per hop (up to ~15×/document) | Config re-fetched on every hop of every document | Same TTL-cache fix as B2, applied at the shared `indoxSettings01` boundary so every caller benefits, not just this one call site | Up to ~14 avoided per-document config fetches at steady hop count |
| B5 | `indoxDocBatchUpsert01` (5,158 lines, 5 nodes) — despite its name, called once per document per write-triggering hop with a **single-row** payload (the per-document state-machine design means each document reaches a write-worthy state independently, at a different tick) | 1-row PostgREST upsert per call, up to ~15×/document across its lifetime, up to 40 documents/tick each doing this independently | Two-tier fix, staged: (a) short-term — coalesce a single document's own consecutive same-tick writes (several hops in one execution write ACTION_LOG/STATUS/extraction fields; today each write-worthy point calls the upsert separately even within one execution) into one upsert per execution, not per hop; (b) longer-term — batch across the **tick's cohort** (up to 40 documents progressing in the same 30s window) into one multi-row upsert flushed at tick-end, which requires decoupling "decide" from "write" (a bigger structural change, sequenced behind the read-model/gateway work in §6, not a quick win) | (a) is a same-file mechanical change; (b) is the real N→1 win but changes the write-timing model — do not rush it ahead of the data-gateway work in §6 |
| B6 | `api/__init__.py:5104` `dashboard_stats()`, `:2295` `_indox_match_index()` | Full `_paged_select(..., max_rows=60_000)` (60+ sequential 1,000-row PostgREST pages at 180,000 rows) + in-process Python aggregation, on every cache-miss | Materialized stats table, computed on write — §4 | Turns O(rows/1000) HTTP round-trips into O(1) `SELECT * FROM <stats table>` |
| **Already correct — keep** | `syncLedgerApi01.json`'s `Build Claim`/`Build Record` | `INSERT ... ON CONFLICT(source,platform_id) DO NOTHING RETURNING platform_id` — accepts an **array** of candidate items and claims them in one statement | — | **This is the model for B3/B5**: one race-safe, set-based SQL statement instead of N round-trips. Every batching fix above should converge toward this shape, not away from it. |

---

## 3. Stability under extreme load

### 3.1 Backpressure keyed to real queue depth

**Today**: `syncV3Unit0001`'s `Take X` node computes `bound = min(take||25, chunk||25)` — a **static**
per-tick ceiling, not responsive to actual backlog. `indoxApiSupabase01`'s `Poll Line Changes` is a
fixed `LIMIT 40` every 30s regardless of how many rows are actually waiting.

**Target**: size `take` from measured queue depth each tick, bounded by a hard ceiling the BFF
enforces (not just registry config — `sync_registry_patch`, `api/__init__.py:4062`, should reject a
`batch.take` above a system-wide max regardless of what a registry entry requests, per the
target-architecture doc's own §3.8 recommendation, given `syncV3Unit0001`'s own in-file comment
documents a real incident from an unbounded `take:50`).

Concrete signal to key off: `sync_ledger`'s own `claimed` count (currently queryable directly —
`select count(*) from sync_ledger where status='claimed'`) plus `incoming_documents` rows with
`STATUS` in the active-hop set. A simple, implementable rule, consistent with the n8n scaling
guidance in the brief (backlog>50 for >10min and CPU<70% → raise concurrency; CPU>75% with high lag →
add workers; memory-bound → lower concurrency, add workers):

| Signal | Read from | Action |
|---|---|---|
| `sync_ledger` claimed count rising, host memory available | `select count(*) from sync_ledger where status='claimed'`, `free -m` inside the container's cgroup | Raise `take` toward the ceiling |
| `sync_ledger` claimed count flat/falling, apitools returning `server_busy` (429) | `_busy_response` payloads already logged by `_expensive_request_slot` (`ocr_api.py:96`) | Lower `take`, lengthen the 15-min tick interval |
| Host `available` memory below the floor (§3.6) | `free -m` / cgroup `memory.max` | Stop claiming new work entirely until it recovers |

### 3.2 Circuit breaker per downstream

**apitools already has the right pattern — keep it, extend the others to match.**
`apps/apitools/src/api/ocr_api.py:53-113` (`_expensive_request_slot`/`_busy_response`) is a genuine
bulkhead: per-kind (OCR vs. JSON-query) bounded concurrency pools sized from the cgroup's real CPU/
memory allotment (`autoscale.py`, cores-aware, memory-clamped, calibrated against a measured peak —
"3 concurrent OCR slots peaked the whole cgroup at 1.29 GiB," `autoscale.py:76-80`), with a bounded
wait (`APITOOLS_SLOT_WAIT_TIMEOUT`, default 600s) before returning a `server_busy` response rather
than piling up unboundedly. **This is the model.** It is missing three things, all additive:

1. **A trip-open state, not just a wait-then-busy.** Today, at sustained overload, every request
   still waits up to 600s before failing — a caller under load gets a slow failure, not a fast one.
   Add a rolling error-rate counter (e.g. last 20 responses) that trips the breaker open — fail fast
   with `server_busy` immediately, no 600s wait — once the recent failure/timeout rate crosses a
   threshold, then half-open after a cooldown to test recovery. This is additive to the existing
   slot mechanism, not a replacement.
2. **No equivalent exists for Drive or Gemini calls from n8n.** `driveApi01` and the Gemini-backed
   extraction workflows (`indoxV2ExtractInvoiceGemini01`, `indoxV2ExtractBalanceSheet01`) have
   per-node `retryOnFail`/`maxTries` (bounded retry — good) but no shared concurrency bulkhead and no
   trip-open state — a Drive outage or Gemini rate-limit today just means every in-flight document's
   retry budget burns down independently, with no system-wide signal to slow new admissions. Target:
   a small shared-state table (or even n8n's own static-data mechanism) recording per-downstream
   recent failure rate, read by `syncV3Unit0001`'s `Take X`/schedule-interval logic (§3.1) to reduce
   `take` when a downstream is unhealthy — reusing the same signal both for backpressure and for the
   breaker.
3. **mailapi has no documented equivalent at all** — worth the same audit `ocr_api.py` already
   passed; not confirmed either way this session (`apps/mail/mailapi/app.py` was read for other
   findings in the codebase map but not specifically for a concurrency-bulkhead pattern) — flagged
   `UNVERIFIED`, task T9 in §6.

**Drive's 256→384 MiB fix, done today, is real and correct** (`apps/drive/docker-compose.yml:79-87`)
but is a symptom fix (more headroom), not a circuit breaker — it does not stop a future traffic spike
from re-hitting the same wall, it just moves the wall. Pair it with the bulkhead pattern above.

### 3.3 DLQ semantics — `needs_review` needs an exit path

**Confirmed live this session: 72 rows in `sync_ledger` with `status='needs_review'`, 0 with any
route out.** Direct read of `syncLedgerApi01.json` (grep for `needs_review` operations) plus the
consolidation plan's own finding: `NEEDS_REVIEW` functions as a dead-letter state by accident (
`Terminalize Stalled`'s 45-minute `IN_PROGRESS` timeout writes it) with no formalized retry-from-DLQ
or manual-requeue operation.

**Target**: two things, both additive to existing structures, not a new subsystem:
1. **An explicit `REQUEUE` op** in `syncLedgerApi01.json`, callable from the webapp's
   `SyncBoard.tsx`/sync board UI (which already has `moveSyncItems()`/`applyFallbackType()` wired to
   `/sync/items/move` and `/sync/items/apply-fallback-type`) — an operator-triggered
   `status='needs_review' → status='claimed'` transition with `RETRY_COUNT` reset to 0, so a human who
   fixes the underlying cause (e.g. the misconfigured `drive_google_service_account-ea660043`
   connection, target-architecture Part 2 #15) can push the 72 parked items back through the pipeline
   without a manual SQL statement.
2. **A reason tag on entry**, not just the terminal state — today `NEEDS_REVIEW` doesn't distinguish
   "stalled, unknown cause" from "retried N times, still failing, here's the last error" (the
   target-architecture doc's own §3.2 recommendation). Add a `REQUIRED_ACTION`-style message on the
   write into `needs_review`, naming which check failed, so the 72 rows are triageable by cause, not
   just by count.

### 3.4 Retry with jitter and a budget

**Confirmed live this session: 0 of 56,213 `incoming_documents` rows have `NEXT_RETRY_AT` populated**
(grew from the morning's 0-of-6,196 — same defect, larger table). Already fully diagnosed in the
target-architecture doc (§3.2, §Part 2 #18): the column and the read-side gate both exist and work
(`indoxApiSupabase01.json:520,606` correctly gate on `"NEXT_RETRY_AT" is null or "NEXT_RETRY_AT" <=
now()`); **nothing ever writes a non-null value**, so the gate is permanently a no-op.

**Additional finding this session, at the n8n-node level, not previously documented**: every
`httpRequest` node touching apitools/Gemini/Drive in the hot path (`indoxProcessDocument01`'s OCR and
3 extraction calls, confirmed by direct read — §1.1) uses `retryOnFail: true, maxTries: 4,
waitBetweenTries: 3000` — a **fixed** 3-second interval, **no jitter, no exponential backoff**. At
the concurrency levels a 50,000-document burst implies, fixed-interval retries from many concurrent
executions synchronize into retry storms (all failed calls from one bad tick retry at
`t+3s, t+6s, t+9s, t+12s` in lockstep) — exactly the thundering-herd pattern jitter exists to break.

**Target**, additive to existing columns/schema, no new tables:
- Write `RETRY_COUNT = coalesce(RETRY_COUNT,0)+1` and
  `NEXT_RETRY_AT = now() + (base_backoff_s * 2^RETRY_COUNT) + random_jitter_s` on any retryable
  failure, in `indoxDocBatchUpsert01.json`'s `UPSERT Adapter` (or a node immediately before it) — the
  `base_backoff_s` default of 60 is **already threaded from the registry into every sync-v3 unit**
  (`syncV3Main0001`'s `Build Units`) but never consumed downstream; consume it here.
- Route to `NEEDS_REVIEW` (§3.3) only after `RETRY_COUNT` exceeds `max_attempts` (also already
  threaded from the registry, default 5, currently unused per the target-architecture doc).
- For the n8n-node-level retries (not the ledger-level ones), change `waitBetweenTries` from a fixed
  3000 to n8n's own jittered/exponential option where the node type supports it, or wrap the call in
  a small Code node doing `sleep(base * 2^attempt + random(0, base))` before a manual retry loop if
  the node type doesn't expose jitter natively — lower priority than the ledger-level fix (this is
  bounded to 4 tries × ~3-24s vs. the ledger-level gate that has *never* fired once).

### 3.5 Graceful degradation — thumbnails before essential work

**Confirmed** (brief's own numbers, consistent with this session's live sample):
`indoxV2GenerateThumbnail01` averages 116.0s and runs **inline**, blocking the document's main path,
called from the `generate_thumbnail` action dispatched by `indoxV2Driver01`'s `Switch1` (§ codebase
map, `/documents/thumbnail` route, `api/__init__.py:3147`, the one route n8n calls over HTTP).
`indoxV2GenerateThumbnail01` itself already models the *right* internal pattern — bounded retries (4
tries/3s for download, 3 tries/3s for render), **fail-soft** (never throws, stamps
`THUMBNAIL_COMPLETED` regardless, per the target-architecture doc §3.8). The defect is not the
workflow's own robustness — it's that it sits **on** the document's critical path instead of beside
it.

**Target**: make `generate_thumbnail` a **fire-and-forget dispatch**, not a blocking hop:
- In `indoxV2Driver01.json`'s `Switch1`, the `generate_thumbnail` branch should trigger
  `indoxV2GenerateThumbnail01` **without waiting** (n8n's `executeWorkflow` node has a
  "wait for sub-workflow" toggle — flip it off for this specific call, or route through a queue/webhook
  fire instead) and let the main document continue to its next real hop immediately. Thumbnail
  generation still runs, still retries, still fail-softs — it just stops gating the ~15-hop chain
  behind its own 116.0s (up to 2,187.1s measured max) latency.
- **Host-memory-floor tie-in (§3.6)**: when free memory drops below the floor, thumbnails are the
  first thing to shed entirely (skip the dispatch, mark `THUMBNAIL_COMPLETED=false` with a
  `deferred` reason) — optional/cosmetic work sacrificed before anything on the STATUS-progression
  path.

### 3.6 Host memory floor

**Measured this session**: 9,950 MiB total, 4,451 MiB free at a quiet moment; the coverage
reconciliation doc recorded **188 MiB free / 449 MiB swap free** during active concurrent-agent load
earlier the same day — a 20×+ swing on the same host. `apps/drive`'s 256→384M fix (§3.2) shows the
platform is already memory-constrained enough that a single container's limit change was needed
mid-session.

**Target**: a floor check the pipeline itself respects, not just an operator watching `free -m`:
- A lightweight scheduled node (piggyback on `syncV3Main0001`'s existing 15-min tick, or the
  `Reaper Schedule 5m` branch already running in `syncLedgerApi01.json`) reads host memory (via a
  small sidecar script exposing `free -m`'s `available` column, or the cgroup's own
  `memory.current`/`memory.max` the way `apitools/autoscale.py` already reads it for its own sizing —
  reuse that exact mechanism rather than inventing a second one) and writes it to a `settings` key
  (e.g. `_meta.host_available_mb`).
- `Take X` (§3.1) and the `Poll Line Changes` cadence both read this value: below a configured floor
  (start conservative — e.g. 1,500 MiB available, informed by the 256M-was-too-tight drive incident),
  **stop claiming new work** (set effective `take=0` for one tick) rather than continuing to admit
  documents that will contend for a shrinking memory pool. This is the same throttle-not-crash
  principle apitools' `autoscale.py` already applies at the single-container level — extending it to
  the pipeline's admission point, not adding a new paradigm.
- This directly addresses `SyncProcGDoc0001`'s OOM crash (target-architecture Part 2 #7) at the
  system level: a floor check at admission time means a memory-constrained host stops accepting new
  claims before a processor crashes mid-batch, rather than after.

---

## 4. The read model (CQRS)

**Computed on write, not re-aggregated on read** — extending the target-architecture doc's §3.5
recommendation with the exact shape asked for.

### 4.1 What moves to write-time

| Aggregate | Today (read-time) | Target table | Maintained by |
|---|---|---|---|
| Status counts (dashboard, sync board totals) | `dashboard_stats()` full 60,000-row paged read + Python `by_status[st]+=1` loop, `api/__init__.py:5104` | `indox_stats_by_status(status text PRIMARY KEY, cnt bigint, updated_at timestamptz)` | `AFTER INSERT OR UPDATE OR DELETE` trigger on `incoming_documents`: on INSERT, `+1` to the new status's row; on UPDATE where `STATUS` changed, `-1` old / `+1` new; on DELETE, `-1`. One small `UPSERT` per write, not a scan. |
| Month-bucket counts (the badge that undercounted 236 vs. true 1,507 — `LIVE-QA-2026-08-05.md` Failure D) | Some pre-aggregation path independent of the main filtered-query path (this document did not trace the exact undercounting code, same as the target-architecture doc's own admission) | `indox_stats_by_month_status(month date, status text, cnt bigint, PRIMARY KEY(month,status))` | Same trigger, additionally bucketing by `date_trunc('month', "TIMESTAMP")` — **the same trigger fires for both tables in one function**, so there is exactly one place where "did I remember to update the badge count" can go wrong, not two independent code paths computing the same number (the root cause class the undercount belongs to) |
| Match-index for dedup (`by_id`/`by_hash`/`by_name`, `_indox_match_index`, `api/__init__.py:2295`) | 60,000-row paged read + in-memory Python set build, every cache-miss | Not a new table — becomes a **direct indexed lookup** once §3.3 of the target-architecture doc's `(CONNECTION,SOURCE_ID)` unique constraint and the existing `uq_incdoc_hash` are both live: `WHERE "CONNECTION"=$1 AND "SOURCE_ID"=$2` / `WHERE "HASH"=$1`, each an index seek, not a table scan | Postgres itself, via the constraint's own index — no trigger needed, this one is "stop building a match index in Python when Postgres already has the matching index" |
| Company/repo breakdowns | Not separately tracked today | `indox_stats_by_company(company_id text, status text, cnt bigint, PRIMARY KEY(company_id,status))` if the dashboard needs a company-level view — same trigger function, same pattern, add only if a route actually needs it (avoid speculative surface per this series' own standard) |

**Consistency**: trigger-maintained counts are exactly consistent with `incoming_documents` at every
commit — no eventual-consistency window, no separate refresh job to fall out of sync (unlike a
materialized view needing `REFRESH MATERIALIZED VIEW`, which would either lock or lag). Write
amplification is bounded and small: 1-2 extra single-row UPSERTs into tiny (≤~15-row,
≤~180-row-at-3-years) tables per write to `incoming_documents` — cheap relative to the write it rides
on, and the trigger function is one place to audit, not N call sites.

### 4.2 What stays computed on read

- **Per-pipe sync counts** (`_inventory_drive`/`_inventory_gmail`, `_enrich_registry`) — depend on
  live Drive/Gmail state, which cannot be trigger-maintained until the incremental-sync cursor work
  (target-architecture §3.1) exists to define "what changed." Stay read-time, stay behind the existing
  `_TTL_INVENTORY=120s` cache and the explicit `?with_items=1`/`?sync=<name>` opt-in (never a page-load
  default — this is already correctly gated per `api/__init__.py:2212`'s own docstring citing a
  measured 43.9s full item-walk). Once §3.1 lands, these become update-on-write too (the cursor
  consumer is the natural place to also bump a live-count row) — a second-order optimization, not
  blocking this document's read-model recommendation.
- **Anything genuinely ad hoc** (a one-off filtered query from the document browser) stays a live
  `SELECT`, just keyset-paginated (below) rather than full-scanned.

### 4.3 Pagination: keyset, not offset, for every user-facing table

`_paged_select` (`api/__init__.py:420`) is correct for **internal bulk reads** (bounded, sequential,
nobody waiting on page 200) — keep it there. For **user-facing** paging — the INDOX document browser
(`BinaTable.tsx` backing `DocumentBrowserPage.tsx`) and the sync board — offset pagination degrades
at high offsets (Postgres must still scan-and-discard the first `offset` rows) and is unstable under
concurrent writes (a row inserted before the current offset shifts every later page by one, causing
skipped or duplicated rows mid-scroll).

**Target**: `ORDER BY updated_at DESC, "ID" DESC` with a cursor `WHERE (updated_at, "ID") <
($last_updated_at, $last_id)` for the next page. `_paged_select`'s existing `order_col` parameter
already threads a sortable column through the function signature (per the target-architecture doc's
own read) — this is a query-shape change in the route handlers that call it for user-facing endpoints
(`/repos/<repo>/documents/query`, `/sync/items`), not a new capability to build.

### 4.4 Sub-second at 180,000 rows — how each surface gets there

| Surface | Query shape at 180,000 rows | Latency floor |
|---|---|---|
| Dashboard status/month tiles | `SELECT * FROM indox_stats_by_status` / `indox_stats_by_month_status` — O(distinct buckets), not O(rows); at most a few dozen rows returned regardless of table size | Index/seq scan on a table with ≤~15-180 rows — sub-millisecond query time, response bounded by network/serialization, not by row count |
| INDOX document browser (BinaTable) | Keyset-paginated `SELECT ... WHERE (updated_at,"ID") < (cursor) ORDER BY updated_at DESC, "ID" DESC LIMIT 50`, using the existing PK/an added `(updated_at,"ID")` composite index | Index range scan for 50 rows — flat cost regardless of total table size, unlike offset paging's cost-grows-with-depth |
| Sync board (`/sync/items`) | Registry-scoped counts from `indox_stats_by_*` where possible; live per-pipe item walk stays behind the 120s cache and explicit opt-in (§4.2) | Cached path: sub-second (already measured 0.17s for `/sync/registry` without `with_items`, per THE-PLAN.md's "Endpoints, cold" table); live-walk path: bounded by external Drive/Gmail API latency, not by `incoming_documents` row count, and only paid when explicitly requested |

---

## 5. Minimisation — the final workflow set

### 5.1 Today: 66 workflows, only 47 are production

Confirmed by the codebase map's full inventory (`INDOX-CODEBASE-MAP-2026-08-05.md` §1c) and this
session's own cross-check: 66 total blueprint files; **9 confirmed E2E/test/fixture workflows executed
in production today** (`indoxV2TestFixtures01`, `indoxV2BSTest01`, `indoxV2DocBaseTest01`,
`indoxV2GDocTest01`, `indoxV2PipelineTest01`, `mailOrgTest00001`, `syncV3FullTest01`,
`syncV3KernelTest01`, `syncV3SourcesTest01`); **5 `JQExV3*` example workflows** + **4 `JQExV3Run*`
harness runners** (armed, `active=true`, 0 recorded executions in the observation window — dormant,
not confirmed-firing, still counted as test surface since they exist only to exercise the JQ-expression
engine); **1 inactive test** (`indoxV2DecideTest01`, the sole `active=false` blueprint). `9 + 5 + 4 + 1
= 19` test/example/fixture workflows. `66 − 19 = 47` — **matching the target-architecture doc's own
"the ~47 confirmed production workflows" figure exactly**, a cross-check that this categorization is
right, not a new estimate.

### 5.2 New this session: the confirmed live v1/v3 parallel sync engine, by file

The consolidation plan's Target 6 documents a v1-vs-v3 sync-registry engine split from `hooks/
sync-state`/`hooks/sync-engine` (script-level evidence) but does not name which **n8n blueprint files**
implement v1. Traced this session by following the actual `executeWorkflow` graph plus
`hooks/sync-engine`'s own source (`../../hooks/sync-engine:42`, which literally opens
`apps/indox/blueprint/n8n/SyncScanner00001.json` to check whether its `Build Units` node is
engine-aware):

- **`SyncScanner00001.json`** has its own independent `scheduleTrigger` at **15 minutes** — the exact
  same cadence as `syncV3Main0001`'s v3 schedule, confirmed live and running in parallel, not dormant
  — calling **`SyncScanUnit0001`** (the v1 per-pipe scan-and-process unit).
- `hooks/sync-engine`'s own comment (`:8-12`): *"the v1 SyncScanner 'Build Units' filter was NOT
  engine-aware when built... setting v3 does NOT stop v1 from processing every entry regardless of
  engine"* — i.e. **today, every registry entry not yet explicitly guarded gets processed by BOTH the
  v1 and v3 engines on the same 15-minute cadence**, a live double-claim risk the existing
  `hooks/sync-engine` script partially guards (refuses a v1→v3 flip until `Build Units` is confirmed
  engine-aware) but does not eliminate, because v1 itself was never made to skip `engine:'v3'` entries.
- `SyncApi0000000001` (webhook `indox-manage`) and `SyncSource000001` (its callee) are a **separate**
  concern — the registry CRUD/manage-webhook layer the BFF's `runSyncEntry()`/`runAllSyncs()` call
  into (per the codebase map's `api.ts` citations) — **not** part of the v1/v3 duplication. Verified by
  reading their trigger nodes and caller graph directly rather than assumed from naming similarity
  (the same discipline that refuted the earlier "41 dangling errorWorkflow" false claim in this
  series) — do not delete these two; they back a live BFF code path regardless of sync engine version.

**Minimisation target**: delete `SyncScanner00001.json` + `SyncScanUnit0001.json` (the confirmed v1
engine) **once every `sync_registry` entry is confirmed `engine:'v3'`** — the check `hooks/sync-state`
already provides (`s.get("engine","v1")` per-entry listing). This closes Target 6 from the
consolidation plan with an exact file-level action, where that document could only say "retire v1"
without naming which files. **Sequence this after §3's stability work, not concurrently with a
backfill** (echoing the consolidation plan's own caution on Target 6) — a double-claim during a
50,000-document burst is a much worse incident than during steady 5,000/month traffic.

### 5.3 Merge candidates within the 47 production workflows, evidenced

| Merge | Files | Evidence it's safe | Buys |
|---|---|---|---|
| GDoc + Shipment actions | `indoxV2ActionsGDoc01.json` (4,661 lines/104 nodes) + `indoxV2ActionsShip01.json` (4,642 lines/104 nodes) → 1 parameterized workflow | Codebase map, direct read: *"GDoc and Ship's entire 104-node graphs are near-byte-identical, differing only in `DOC_TYPE`"* — already-established, not new | 2 → 1 |
| The 5 per-field query workflows | `indoxV2QueryDocDate01` (845/22), `QueryInvoiceId01` (828/22), `QueryPurchaseId01` (2,092/44), `QueryShipmentId01` (2,022/42), `QueryTotalAmt01` (1,748/20) → 1 parameterized workflow, ideally calling the new `/documentJsonQueryBatch` (§1/§2, B1) in one shot instead of dispatching to 5 separate n8n files | Structurally the same shape as the `Extract*` redundancy found in §1.1 (a per-field apitools query wrapped in its own n8n workflow) — the same fix that collapses 3 serial HTTP calls in `indoxProcessDocument01` applies at the workflow-count level here | 5 → 1 (or 5 → 0 if the BFF/gateway calls `/documentJsonQueryBatch` directly and these workflows become unnecessary — evaluate once B1 ships and the calling pattern is proven) |
| Admin/demo/reset ops | `IndoxInjectDemo01`, `IndoxResetFull01`, `IndoxResetGml001`, `tVzFMkz18pCsXRyw`, `sv3Inject3x001` → 1 parameterized ops workflow (dispatch by an `INLINE_ACTION`-style param, mirroring the BFF's own dispatch pattern) | All 5 are `manualTrigger`-only, admin-invoked, low/zero execution volume in the observed window — no production traffic depends on them being separate files | 5 → 1 |
| v1 legacy sync engine | `SyncScanner00001` + `SyncScanUnit0001` | §5.2 | 2 → 0 (delete, not merge, once the engine-check passes) |

**Not merged, evidenced why not**: `indoxV2ActionsBS01` (Balance Sheet actions) stays separate from
the GDoc/Ship merge — it carries the **divergent SHORT_DOC_ID formula** (codebase map §1c) and a
different lookup shape (`GET Req`/`Match Existing` nodes with no character-stripping, vs. the
canonical formula GDoc/Ship use) — merging it today would either propagate the divergent formula into
the merged workflow or require fixing identity first. Correct order: land `indoxIdentity01` (§5.4)
and retire the divergent formula, **then** evaluate a 3-way Actions merge as a phase-2 target — not
forced into this document's count.

### 5.4 New workflows required (additions, not reductions — needed to enforce the "one pattern" rule)

Per `INDOX-UNIFIED-N8N-SPEC.md`'s already-agreed governing decision ("no workflow may touch the
database directly" / "one sub-workflow computes identity") — restated here only to fold into the
final count, not re-argued:

| New workflow | Purpose | Supersedes |
|---|---|---|
| `indoxDataGateway01` | The one sub-workflow with Postgres write access; schema validation from `information_schema.columns` (never hand-maintained — the exact mechanism that lost `THUMBNAIL`/`CONNECTION`/`NEXT_RETRY_AT`/`RETRY_COUNT` historically), identity assignment, status-transition legality, audit trail | Direct-Postgres-write nodes in the other 46 production workflows (65 of 66 today write Postgres directly per the codebase map) |
| `indoxIdentity01` | One sub-workflow computing `(source_system, source_id)` as the natural key + `HASH` for content-identity; `SHORT_DOC_ID` demoted to a display label only | The consolidation plan's earlier, narrower `indoxUtilShortDocId01` proposal (Target 2) — this document adopts the unified-spec's broader identity redesign instead, since a SHORT_DOC_ID-only fix doesn't address the `(CONNECTION,SOURCE_ID)` migration the target-architecture doc's §3.3 already calls for; do not build both |

### 5.5 The number

```
66 total today
− 19  test/fixture/example (relocate to a segregated test n8n project — Target 7 of the
                             consolidation plan; not deleted from git, removed from the
                             production instance's active set)
────
 47   production workflows today (cross-checked against the target-architecture doc)
− 1   GDoc+Ship merge (2→1)
− 4   5 Query* workflows merge (5→1)
− 4   5 admin/demo/reset merge (5→1)
− 2   v1 legacy sync engine deletion (SyncScanner00001, SyncScanUnit0001) — contingent
      on the engine-check in §5.2 passing first
+ 2   indoxDataGateway01, indoxIdentity01 (new, required)
────
 38   FINAL production workflow count target
```

**38**, down from 66 total (47 of which count as "production" today) — a 42% reduction from the
current production set, achieved by merging genuinely-duplicated logic (GDoc/Ship, the 5 Query
workflows), deleting a confirmed-dead-weight parallel engine (v1 sync), and consolidating low-volume
admin tooling — while *adding* the two workflows the "no direct writes / one identity" rules require,
because minimisation that skips those two additions would just be fewer files doing the same
unmediated-write thing that produced the divergent-identity and 502-HTML defects in the first place.

---

## 6. The complete ordered task list

Every task names the file/node/table it lands in, what it buys quantitatively, its risk, how to
verify, and its dependencies. **[E2E-PREREQ]** marks tasks that must land before the 50,000-document
burst test; unmarked tasks improve the system but do not block it.

| # | Task | File / Node / Table | Buys | Risk | Verify | Depends on | E2E-PREREQ |
|---|---|---|---|---|---|---|---|
| T1 | Fix the n8n API key/auth so per-execution node timing is obtainable | `.env`'s `N8N_API_KEY`; confirm against `GET /api/v1/executions/<id>?includeData=true` | Unblocks exact per-node ms attribution for §1's budget attack — currently the one number this document could not produce | Low — read-only key check | `curl` returns `resultData.runData` with real `executionTime` values, not `{"message":"unauthorized"}` | none | ✅ |
| T2 | Add `POST /documentJsonQueryBatch` to apitools, mirroring `document_draw`'s load-once/iterate-queries shape | `apps/apitools/src/api/__init__.py` (new route, sibling to `documentDraw` at 173-213 and `documentJsonQuery` at 131-154); `apps/apitools/src/api/ocr_api.py` | Collapses 3 serial extraction calls → 1; frees 2 of `json_slots_default()`'s 8 concurrency slots per document | Low — additive new route, existing `/documentJsonQuery` untouched for other callers | Call with a real `file_id` + 3-query payload; confirm one response contains all 3 results, matching what 3 separate calls return today | none | ✅ |
| T3 | Rewire `indoxProcessDocument01`'s `Extract InvoceId`/`Extract ShipmentId`/`Extract Purchase ID` into one `documentJsonQueryBatch` call | `apps/indox/blueprint/n8n/indoxProcessDocument01.json` | Realizes T2's saving on the hot path | Low-medium — one workflow edit on the core document-processing path | Run against a sample of real documents; diff extracted field values before/after (must be identical); measure execution duration before/after via T1 | T1, T2 | ✅ |
| T4 | Cache/collapse `Companies Loader`/`Query Settings` self-loopback HTTP calls | `indoxProcessDocument01.json` nodes `Companies Loader`/`Query Settings`; and the equivalent pattern in `indoxV2ActionsGlobal01.json`'s `Companies` node | Removes 2 of 7 serial hops per document; removes the recurring per-hop config refetch (~14×/document at full hop count) | Low — cache invalidation on a slow-changing config, TTL-bounded | Change a company setting via the webapp; confirm it propagates within the TTL window, not instantly-but-also-not-never | none | — |
| T5 | Fix `3a. DOC BASE Actions Switch`'s missing `extract_invoice_google_ai` case | `indoxV2ActionsGlobal01.json`, node `3a. DOC BASE Actions Switch` | Recovers every document silently stuck needing the AI-extraction fallback (already identified as the target-architecture doc's own "single highest-value change") | Low — one Switch node edit | Query for rows whose derived ACTION would be `extract_invoice_google_ai`; confirm progression before/after | none | ✅ |
| T6 | Decouple thumbnail generation from the document's critical path | `indoxV2Driver01.json`'s `Switch1`, `generate_thumbnail` branch | Removes a 116.0s mean (up to 2,187.1s measured) blocking hop from every document that needs a thumbnail | Medium — changes execution-wait semantics of one branch; must confirm downstream state doesn't implicitly depend on thumbnail completion before proceeding | Trigger a document needing a thumbnail; confirm it reaches its next real STATUS transition without waiting on `THUMBNAIL_COMPLETED` | none | ✅ |
| T7 | `needs_review` exit path — add a `REQUEUE` op + reason tag | `syncLedgerApi01.json` (new op); `SyncBoard.tsx` (wire an operator action) | Gives the 72 currently-parked rows (and every future one) a way out; makes the DLQ triageable by cause | Low-medium — new op, additive | Requeue one of the 72 real parked rows; confirm it re-enters `claimed` and either completes or re-parks with an incremented `RETRY_COUNT` | T8 (retry/backoff) for the reset semantics to mean anything | ✅ |
| T8 | Wire `NEXT_RETRY_AT`/`RETRY_COUNT` — the write side that has never existed | `indoxDocBatchUpsert01.json`'s `UPSERT Adapter` (or a node before it); reads `base_backoff_s`/`max_attempts` already threaded from `syncV3Main0001`'s `Build Units` | Retry scheduling starts working for the first time (0 of 56,213 rows today); reduces `NEEDS_REVIEW` pileup from transient failures | Low — additive writes to existing, already-declared, currently-unused columns | Force a transient failure (simulate a downstream timeout); confirm `NEXT_RETRY_AT` is set to a real future timestamp and `Get Changed Docs`'s existing gate respects it | none | ✅ |
| T9 | Add jitter to node-level `retryOnFail` waits on apitools/Gemini/Drive calls | Every `httpRequest` node with `retryOnFail:true` in `indoxProcessDocument01.json` and the extraction workflows | Prevents retry-storm synchronization under concurrent load (a real risk newly identified this session, not previously documented) | Low | Force N concurrent failures; confirm retry timestamps are no longer in lockstep | none | — |
| T10 | Audit mailapi for an apitools-style concurrency bulkhead; add one if absent | `apps/mail/mailapi/app.py` | Closes the one downstream this document could not confirm has backpressure | Low to investigate | Read the file for an equivalent to `ocr_api.py:53-104`; if absent, design one matching apitools' shape | none | — |
| T11 | Add trip-open state to `_expensive_request_slot` | `apps/apitools/src/api/ocr_api.py:53-104` | Converts "wait up to 600s then fail" into "fail fast once recent failure rate crosses a threshold" — faster failure detection under sustained overload | Low-medium — changes failure-mode timing, needs careful default tuning to avoid false trips | Simulate sustained downstream failure; confirm requests fail fast (not after the full 600s wait) once the threshold trips, and recover once healthy | none | — |
| T12 | Shared per-downstream health signal (Drive/Gemini) feeding `take` sizing | New small state (a `settings` key or dedicated table) written by node-level failure observations, read by `syncV3Unit0001`'s `Take X` | Gives sync-v3 the same "downstream unhealthy → slow down" signal apitools already has internally | Medium — new signal path, needs a clear read/write contract | Force a Drive error burst; confirm `take` visibly drops on the next tick, recovers after | T1 (for confirming timing effects), T11 (shared pattern) | — |
| T13 | Host-memory-floor check gating new claims | Piggyback on `syncV3Main0001`'s 15-min tick or `syncLedgerApi01.json`'s `Reaper Schedule 5m`; reuse `apitools/autoscale.py`'s cgroup-read mechanism rather than inventing a second one | Stops the pipeline from admitting new work into a memory-starved host — directly targets the `SyncProcGDoc0001` OOM class | Medium — needs a conservative default floor and a way to override for testing | Constrain the container's memory artificially low; confirm claims stop before a crash, resume once memory recovers | T1 | ✅ |
| T14 | Materialized stats tables + trigger | New `indox_stats_by_status`, `indox_stats_by_month_status` tables; `AFTER INSERT OR UPDATE OR DELETE` trigger on `incoming_documents` | Removes `dashboard_stats()`'s O(rows) aggregation; fixes the month-pill undercount's underlying two-code-paths-one-number class | Low-medium — trigger write amplification needs load-testing at the 50,000-doc burst write rate | Compare `dashboard_stats()` output before/after against a direct SQL `GROUP BY` for a full month; load-test trigger overhead at burst insert rate | none | ✅ (for the burst test to have a working dashboard) |
| T15 | Keyset pagination for user-facing tables | `api/__init__.py`'s `/repos/<repo>/documents/query`, `/sync/items` route handlers; uses `_paged_select`'s existing `order_col` param | Stable, flat-cost pagination at 180,000 rows instead of offset-degrades-with-depth | Low — query-shape change, not new capability | Page through a large table; confirm no skipped/duplicated rows under concurrent writes during paging | none | — |
| T16 | `(CONNECTION,SOURCE_ID)` unique-constraint migration | `incdoc_connection_platform_idx` (already exists as a plain btree) → unique constraint; staged per target-architecture doc §3.3 steps 1-4 | Turns `DOUBLE` (5.7-11.7% of the table depending on snapshot) from a dumping ground into a decision; makes re-delivery idempotent by real identity | Medium — touches all live rows; violations must be triaged, not blindly deleted | Run the pre-check duplicate-count query before adding the constraint; re-run `DOUBLE` rate after | none | ✅ — strongly recommended before the 50,000-doc burst, since backfilling through an unconstrained identity model only grows the triage burden |
| T17 | Build `indoxIdentity01` | New workflow | The one identity computation, ends the SHORT_DOC_ID multi-formula drift (4 divergent formulas, confirmed live collisions) | Medium — touches every Actions workflow's entry point | Diff identity output old vs. new across a sample of real documents before cutting any caller over | T16 | ✅ |
| T18 | Build `indoxDataGateway01` | New workflow; retires direct-Postgres nodes across 46 other production workflows, one at a time | Ends "65 of 66 workflows write Postgres directly" — the structural root of the divergent-identity and 502-HTML-as-data defect classes | High — largest single change in this plan, touches nearly every workflow's write path | Three rejection proofs (malformed field, illegal status transition, unknown column) + old/new write-path diff per migrated workflow, one at a time, each independently revertible | T17 (identity must be settled before the gateway enforces it) | recommended before burst, not strictly blocking if T8/T16 land first — see honest-ceiling note in §7 |
| T19 | Confirm every `sync_registry` entry is `engine:'v3'`, then delete `SyncScanner00001`/`SyncScanUnit0001` | `hooks/sync-state`'s existing per-entry engine listing; `apps/indox/blueprint/n8n/SyncScanner00001.json`, `SyncScanUnit0001.json` | Removes the confirmed-live double-claim risk (§5.2) — the v1 engine currently processes every entry regardless of its `engine` field | Medium — live sync logic; do not run mid-burst | `hooks/sync-state` output shows 100% `engine:'v3'`; after deletion, confirm no `SyncScanner00001`/`SyncScanUnit0001` executions occur and delivery rates are unaffected | none | ❌ — explicitly do NOT schedule during the 50,000-doc burst (a double-claim during burst is worse than during steady load) |
| T20 | Merge `indoxV2ActionsGDoc01` + `indoxV2ActionsShip01` | Both files → one parameterized workflow (`DOC_TYPE` as the dispatch param) | 2→1, per §5.3 | Low-medium — mechanical given the near-byte-identical evidence, but still a live-workflow edit | Run both document types through the merged workflow; diff output against the pre-merge two-file behavior for a sample of each type | T17 recommended (avoid merging before identity is settled, to keep the diff clean) | — |
| T21 | Merge the 5 `indoxV2Query*01` workflows | 5 files → 1 (or → 0 if superseded by direct `documentJsonQueryBatch` calls, per §5.3's note) | 5→1 minimum, per §5.3 | Medium — 5 separate call sites to re-point | Diff each field's extracted value before/after across a sample | T2, T3 (proves the batched-query pattern first, at the document-processing level, before repeating it at the workflow-count level) | — |
| T22 | Merge the 5 admin/demo/reset workflows | `IndoxInjectDemo01`, `IndoxResetFull01`, `IndoxResetGml001`, `tVzFMkz18pCsXRyw`, `sv3Inject3x001` → 1 | 5→1, per §5.3 | Low — manual-trigger-only, no production traffic depends on the split | Run each of the 5 original operations via the merged workflow's dispatch param; confirm identical effect | none | — |
| T23 | Relocate the 19 test/fixture workflows out of the production n8n project | Per consolidation plan Target 7 — separate n8n project/instance, or at minimum a `test/`/`qa/` id/name prefix enforced by CI, with confirmed instance-scoped writes | Stops test executions from sharing the production instance's execution table/worker pool/error-alerting surface with real traffic | Low to investigate, medium to execute (real infra change if a second n8n project) | Confirm no test-workflow execution appears in a production-instance-filtered query after the move; confirm the 3 no-trigger-node workflows (task claim, not independently re-derived this session — see T24) stop their 256s retry loop | none | recommended before burst (keeps the burst's own execution-table growth attributable to real traffic) |
| T24 | Identify and fix the 3 workflows with no trigger node retried every 256s forever | `workflow_entity` join `execution_entity` where `mode='retry'` or no valid trigger node exists — **this session could not independently re-derive which 3 files** (stated as given in the task brief's "Measured Reality," not re-verified against live data due to time budget — flagged, not silently repeated) | Stops a permanent, wasted execution-retry loop | Low once identified | `SELECT` for the specific pattern; confirm the loop stops post-fix | none | — |
| T25 | Node-level circuit-breaker trip-open for apitools (extends T11) | `apps/apitools/src/api/ocr_api.py` | See T11 | — | — | T11 | — |
| T26 | Load-test the trigger write amplification from T14 at burst insert rate | T14's trigger function | Confirms the materialized-stats approach doesn't itself become a bottleneck at 50,000-document burst insert rates | Medium — needs a realistic burst-rate synthetic load, not a steady-state one | Insert at the target burst rate against a copy of the trigger; measure `incoming_documents` write latency with/without the trigger | T14 | ✅ |
| T27 | Drive incremental sync (`changes.list`/`startPageToken`) | `apps/drive/adapters/google.py` (new `changes` op); `syncV3Unit0001.json` (wire `CURSOR_GET`/`CURSOR_SET`, already-implemented ops in `syncLedgerApi01.json`) | Removes full-relisting cost at 3-year/180,000-row scale — not urgent at today's volume, load-bearing at the stated 3-year target | Medium-high — new adapter surface, cursor-expiry handling | Run incremental and full-listing in parallel for one cycle, diff the item sets, confirm match before cutover | none | not for the 50k E2E specifically (that's a burst-ingest test, not a discovery-cost test), but required before 3-year sustained volume is real |
| T28 | Gmail incremental sync (REST API migration or CONDSTORE) | Transport-level decision — this document, like the target-architecture doc before it, cannot determine mail-server CONDSTORE support from static analysis | Same benefit as T27, for mail | High — either a transport migration or a server-capability dependency | Same parallel-run diff approach as T27 | Owner decision on which path (flagged, not resolved) | same as T27 |

**Ordering logic**: T1-T4 (budget attack) and T5-T9 (silent-drop/DLQ/retry/jitter fixes) are cheap,
independently-revertible, and directly reduce both per-document latency and the failure modes a burst
would amplify — do these first, in parallel where they touch different files. T13-T14 (memory floor,
stats table) must exist *before* the 50,000-document burst has anything meaningful to observe or
protect the host from. T16-T18 (identity → gateway) are the largest, riskiest, highest-payoff changes
— sequence identity before the gateway (the gateway needs a settled identity rule to enforce), and do
not rush the gateway migration (46 workflows, one at a time) purely to hit an artificial deadline
ahead of the burst test — T8+T16+T13+T14 landing without T18 still makes the burst survivable and
observable, just not yet unmediated-write-free.

---

## 7. Honest ceiling

**Restating the brief's own already-measured ceiling, not re-deriving it**: scheduling is bounded at
**800/hr** by `Take X`'s bound on `chunk` (not `take` — a config-reading defect independent of
everything in this document); the realistic worker-pool ceiling, confirmed this session (2 workers ×
`--concurrency=8` = 16 slots, `platform-base/n8n/docker-compose.yml:303,429`), is **230-380/hr**.
**3,000/hr is not reachable on this host by adding workflow-level fixes alone** — this was true before
this document and remains true after it; nothing here changes that physics.

### What THIS document's changes move, and what they don't

| Change category | Effect on **sustained** rate (5,000+/month ≈ 7/hr) | Effect on **burst** rate (the 50,000-doc E2E) | Effect on the **800/1000+/hr ceiling itself** |
|---|---|---|---|
| §1/§2 batching (T2-T4, T20-T22) | Reduces per-document wall-clock cost, which reduces how long each of the 16 worker slots is occupied per document — **more documents fit in the same slot-hours**, but does not add slots | Same — a burst drains faster because each document's occupancy is shorter, not because more documents run concurrently | **No** — the ceiling is a slot-count/scheduling-config ceiling, not a per-document-cost ceiling; fewer seconds per document raises effective throughput *within* the existing 16-slot/800-per-hour envelope, it does not raise the envelope itself |
| §3 stability (T5-T13) | Prevents documents from getting silently stuck, retried forever, or crashing a processor — **more of the attempted throughput actually lands as COMPLETED**, closing the gap between "scheduled" and "delivered" | Prevents a burst from cascading into stuck-claim pileup, OOM crashes, or an unbounded `DOUBLE` explosion — makes the burst *survivable*, not faster | **No** | 
| §4 read model (T14-T15) | No effect on ingestion rate — this is entirely about the UI staying responsive while ingestion happens, at any rate | Same — keeps the dashboard/board usable *during* a 50,000-document burst instead of degrading as the target-architecture doc's own measured `/sync/items` 20.4s→39.1s→56.1s regression showed happening *as the pipeline got healthier* (i.e., as a side effect of more real data existing) | **No** |
| §5 minimisation (T19-T24) | Fewer workflows to maintain, one fewer parallel engine risking double-claims — an operability and correctness win | Removing the v1 legacy engine (T19) removes a double-claim risk that would be *worse*, not better, under burst concurrency — a correctness protection, not a speed-up | **No** |
| Raising `--concurrency` per worker, or worker count | not attempted by this document — infra, not workflow | — | **Yes, this is the actual lever** — but bounded by memory (§3.6's own findings: this host swung from 4,451 MiB free to 188 MiB free under real concurrent load *today*) and by `Take X`'s `chunk`-not-`take` bug, which must be fixed first (a scheduling-config fix, not infra, but currently caps any concurrency increase from mattering) |

### The honest number

**With every workflow-level task in §6 (T1-T26) complete**, sustained throughput moves from
"5,000/month barely, with silent losses and stuck rows eating into the effective rate" to **5,000+/
month reliably delivered** (the brief's own sustained target, already within the 230-380/hr realistic
ceiling at ~7/hr average — the gap today is not raw capacity, it's the defects in §3 silently losing
work that was already scheduled). **Burst capacity for the 50,000-document E2E moves from "will
visibly throttle for hours and likely produce stuck claims / OOM crashes / an unbounded DOUBLE
explosion" (today's honest state, per the target-architecture doc's own Part 2 #5, #7 findings) to
"will complete, bounded by the existing 230-380/hr realistic ceiling, i.e. roughly 130-220 hours of
continuous pipe-uptime at the current worker count** — not fast, but survivable, observable, and
correct, which today's system is not proven to be at that volume.

**3,000/hr requires infrastructure, not workflow changes — separated explicitly, per the brief's
own ask**:
- Fix the `Take X` `chunk`-not-`take` config-reading bug first (this is arguably a workflow fix,
  cheap, and is the one item that must land before adding workers would even help — otherwise more
  workers just contend for the same artificially-small `chunk`).
- More worker containers, each with real memory headroom — this host's own measured swing (4,451 MiB
  → 188 MiB free under real load, same day) means "add workers" on *this* 9.95 GiB host trades one
  resource constraint for another; dozens of worker slots at `--concurrency=8` each need proportional
  RAM apitools/Drive/mailapi/Postgres/n8n itself aren't currently sized for.
- A Drive service that doesn't need a 384M→larger ceiling under real concurrent traffic (today's
  256→384M fix bought headroom, not unlimited scale).
- Host RAM sized for all of the above simultaneously, not sequentially — this is the "infrastructure,
  not workflows" line the brief itself already draws, confirmed rather than contradicted by this
  session's own memory measurements.

---

## Standards note

Every recommendation above names a real file, node, table, or route in this repository. Facts carried
forward from the five source documents are cited to them, not re-asserted as independently derived.
New evidence produced this session — the `documentDraw`/`documentJsonQuery` batching gap (§1-2), the
`SyncScanner00001`/`SyncScanUnit0001` v1-engine file identification (§5.2), the apitools
`_expensive_request_slot` bulkhead as a keep-and-extend model (§3.2), the drive 256→384M fix
confirmation (front-matter table), the live `needs_review=72`/`NEXT_RETRY_AT=0-of-56213` re-confirmation
(front-matter table) — is marked as such and grounded in a direct read or a live query shown inline.
Where a number could not be obtained this session (per-node execution timing for the 211.8s chain, the
exact 3 no-trigger-node workflow ids, mailapi's concurrency-bulkhead status), this document says so
and names the task that closes the gap (T1, T24, T10) rather than guessing. Per this repo's own
standard: where the current design is right, this document says keep it — `syncLedgerApi01.json`'s
CLAIM/RECORD ledger primitives (§2, "already correct"), apitools' `_expensive_request_slot` bulkhead
(§3.2), `autoscale.py`'s cgroup-aware sizing (§3.6), and the thumbnail workflow's own bounded-retry/
fail-soft internals (§3.5) are all genuinely correct patterns this document extends rather than
replaces.
