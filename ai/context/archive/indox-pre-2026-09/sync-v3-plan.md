# sync-v3 — reconciliation sync layer: full refactor + test-suite plan

Status: **W0–W4 DONE (laptop/dev)** — 2026-07-10: proc-mode parity landed, all 3 suites + coverage green,
all 5 registry sources flipped to `engine:v3` (proc auto via processor_wf), live business-like docs from
localdrive+localmail delivered with full v1 enrichment (sender→company, date−2mo naming, OCR figuring,
filename-parse, link resolution), billboards flipped, second pass idempotent, sync state AT REST.
Remaining: prod (hacohen-vps) cutover as a deliberate separate step + W5 optimizations.
Supersedes the claim/label sync (`sync-refactor-v1`: SyncScanner00001 → SyncScanUnit0001 → SyncProc*).
Companion decisions + research: memory `indox-sync-best-practices-research` (★/★★ sections + code-review gate).

## 0. Implementation record (what was actually built — deltas from the plan below)

Built + verified green on shlomo-laptop (all three suites manual AND `--lanes`, plus doc_base/bs canaries):
`sync_kernel` 6/6 lanes (27 asserts, ~14s) · `sync_sources` 4/4 (23 asserts, ~27s) · `sync_full` 5/5
(25 asserts, ~89s; history walk converges in 3 passes, handoff touched by loop 2 in ~4 checks) ·
**node coverage 299/299 = 100%** (`scripts/sync-v3-coverage.py`).

Deltas vs the plan sections below:
- **Adapters are inline branches of `syncV3Deliver0001`** (drive/gmail switch), not 5 separate `syncV3Proc*`
  WFs; projections are an inline post-Record branch, no separate `syncV3Project0001`. Fewer WFs, same coverage.
- ~~Thin delivery confirmed~~ **⚠️ CORRECTED BY PARITY AUDIT (2026-07-10, user-driven — sources reverted
  to v1)**: thin delivery DROPS per-source figuring that v1 processors did at sync time, some of it
  UNRECOVERABLE downstream (sender email, email-date−2mo BS dating, forwarded-chain company lookup,
  multi-attachment BS selection strategies, "Company - MM.YY" filename parse, link-provider resolution,
  attachment filters, naming conventions, per-source STATUS semantics). Live-run correction: drive-gdoc's
  upsert reads `$json.is_ok` off the LOG item (undefined) → v1 actually writes IN_PROGRESS at sync and
  loop-2 completes it; figuring/rename/naming ARE at sync, terminal status is not.
  Full then/now audit of all 5 processors + shared Process Document engine done.
  **RESOLUTION IMPLEMENTED (same day): proc mode.** Instead of porting code, `syncV3Deliver0001` gained a
  `mode` gate: `thin` (metadata-only; test fixtures/kernel suites) vs `proc` — Deliver INVOKES THE UNCHANGED
  v1 PROCESSOR WORKFLOW with SyncScanUnit's exact contract (drive: `{ctx:{sync_name,source,type_hint,
  to_sync,in_progress,synced,failed}, settings, items:[file]}`; gmail: `{gmail_id, labels}` where labels =
  settings.gmail.labels). mode auto-derives: registry entry has `processor_wf` → proc; else thin
  (`v3_mode` overrides). Unit loads settings once per pass (proc only) and builds the gmail query from
  label KEYS + search_extra (positive terms only — no claim exclusions; ledger is the loop memory).
  Success/fail label billboards (v1 Gmail Outcome ops) are proj_on-gated projections after RECORD/ATTEMPT.
  RECORD stores drive md5 as content_hash; gmail rows join via SOURCE_LINK ends-with msg id.
  Deterministic processor failures (e.g. BS mail with no attachment) ride the attempt rail; at
  max_attempts the item is PROMOTED to ledger status='needs_review' (attempt row cleared) = v1's failed
  label, plus the actual failed-label projection when proj_on. Empty source listing (fully-synced folder,
  zero-hit search) previously KILLED the Unit silently — List/Search now alwaysOutputData (found by the
  parity lanes; real prod hole: an emptied to_sync folder is the normal converged state).
  Gmail/localmail parity HOLDS (both modes share gmailApiImap01 shape:get which builds the exact
  mailparser shape processors consume). Five proc-parity lanes in syncV3SourcesTest01 (proc-gdoc/-bs/
  -gmail-bs/-gmail-doc/-gmail-link) assert the enrichment against runtime truth: docGen-generated invoices
  (run-unique doc ids, supplier = runtime-picked company from settings → COMPANY figuring asserted),
  sender→company + date−2mo naming for gmail-bs, filename-parse company for drive-bs, LDrY link resolution
  against /docGen/sample?truth=1.
- **gmail-link IMPLEMENTED** (2026-07-09, second pass): 5th Deliver branch (get msg → extract first URL →
  download → upload → deliver) + 5th sources-suite lane proving byte integrity (delivered HASH == source
  file md5) via localmail + `storage:5000/object/public/drive/<id>` as in-cluster URL host. Coverage 316/316.
  Production caveat: handles direct-download links (level-1); LDrY's provider-translation resolver ports at
  cutover if vendor links need it. **LDrY itself fixed too**: `Code` + `Generic PDF Resolver` created raw
  inline base64 binaries (invisible in filesystem binary mode — the open "LDrY downloader bug") → now
  `prepareBinaryData`. **W4 seed tool built**: `scripts/sync-v3-seed-ledger.py` (idempotent; derives
  (SYNC_NAME, #inbox/<id>) from existing rows; validated: 12 seeded, re-run 0).
- **`status_override`** param (Unit/registry→Deliver): test suites deliver rows as `NEEDS_REVIEW` so the live
  30s loop-2 poll doesn't churn garbage test docs (it selects any recently-updated row). The `handoff` lane
  delivers real `IN_PROGRESS` and asserts loop-2 pickup (poll-query membership + row touched ≤10×15s checks).
- **Coverage gate is Python** (`scripts/sync-v3-coverage.py`, not .mjs) — reuses the runner's psql/flatted
  parse; wired as a CI step in `indox-e2e.yml` after the battery (`--since-minutes 60`); excludes
  trigger/respond/sticky nodes (mode-dependent); backend scope = only the 4 injected DELIVER nodes.
- **`sync_full` lanes = history/mixed/races/chaos** — handoff runs in manual/`all` only (it measures live
  loop-2 latency; contention-flaky under 5-way lane concurrency; CI uses manual mode so it IS exercised).
- **Suite watch-guards use `$runIndex`**, never `$getWorkflowStaticData` (staticData persists across
  executions and races under concurrent lanes — real bug found by the lanes run).
- **Drive walk requires projection-move ON** when backlog > page_size (no pageToken cursor yet — W5):
  delivered items otherwise permanently occupy the first page. `sync_full/history` proves the proj-on walk.
- **Two pre-existing `driveApiLocal01` bugs fixed** (found by sync_sources): `l:text to binary` created an
  unregistered inline binary (must `prepareBinaryData`), and `l:md5` was a crypto node reading
  `binary.data.data` inline — undefined in filesystem binary mode (same class as the open LDrY bug) →
  replaced with `getBinaryDataBuffer` + createHash Code node.
- Kernel suite has 6 lanes (no separate `cov` lane — the external coverage gate is the enforcement).
- Suite cleanups are **lane-scoped** (concurrent lanes must never wipe each other's seeds).

---

## 1. Architecture (settled — recap only)

Two level-triggered **reconciliation loops**; sync is loop 1, the existing 30s poll → `indoxV2Driver01`
state machine is loop 2 (already reconcile-shaped — unchanged by this plan).

```
sources (READ-ONLY, paginated)          walk = full history · steady = new items only
   │ list page (≤N ids)
   ▼
List+diff ─→ Process ─→ Deliver① ─→ Record②          ← the loop, per source, every N min
 page →       take X     upsert       ledger row
 SQL diff     fetch/OCR  content      = delivered
              extract    dedup
   ▲                        │             │
   └── diff reads ledger ───┼─────────────┘
                            ▼
              incoming_documents          sync_ledger
              (business ledger,           (sync-private memory,
               ZERO sync state)            PK (source, platform_id))
                            │
                            ▼  optional, fire-and-forget, never read back
              projections: drive move-to-processed · gmail retag
```

**Four invariants (everything else is derived) — REWRITTEN 2026-09-02 for the SYNC ITEM (owner
Decision 1; the original "the live diff IS the todo list" is retired, see §1a below):**
1. A ledger row exists from DISCOVERY: one row per item the source scope listed, status
   `discovered → claimed → delivered | failed | needs_review` ("synced" == delivered). The todo
   list is a WHERE (`status in (discovered, failed) and not_before <= now()`), never a set
   difference against the platform, and delivery reads the row's own `listing` — no platform read
   between TAKE and DELIVER.
2. Discovery and sync are two stages of one pass: `syncDiscover{Drive,Gmail}01` UPSERT (on conflict
   the STATUS is kept, a non-delivered LISTING is refreshed); `syncRun01` TAKEs
   `min(take, chunk)` rows in one `for update skip locked` statement. Where a file or mail SITS is
   never sync state — folders and tags are user-visible marks written only by the state machine's
   feedback.
3. **Deliver before Record** — crash between them re-delivers on the next TAKE (the claim is reaped
   into `failed` with backoff); content dedup collapses. Ordering is load-bearing.
4. Races **converge**, they are not prevented: ledger PK `ON CONFLICT DO NOTHING` on discovery, row
   locks on TAKE, content-unique dedup in DELIVER. The reconcile mutex is efficiency-only.

**Convergence gate (one view):** `sync_item_counts` per pipe — discovered / claimed / delivered /
failed / needs_review — is the whole board (blue = discovered+claimed, green = delivered,
red = failed+needs_review). Loop-2's existing no-non-terminal gate stays "processed Y%".

### 1a. The Sync Item API (`syncLedgerApi01`, the only writer) — ops

| op | statement | note |
|---|---|---|
| `UPSERT` | insert discovered rows with `listing`; on conflict refresh listing where status<>'delivered' | discovery |
| `TAKE` | next N (`discovered`/`failed`, due, under budget, with a listing) → `claimed`, `for update skip locked` | run |
| `RECORD` | `delivered` (or `needs_review`) with doc_id/content_hash; no-op on an already-delivered row | deliver |
| `FAIL` | attempts+1, equal-jitter backoff (base 60s, cap 3600); `[terminal]` suffix or max_attempts → `needs_review` | deliver |
| `RELEASE` | claimed → discovered (not a failure) | ops |
| `RESET` | rows → `discovered` (optional `statuses`; cursor dropped only on a full re-drive; rows without a listing are skipped); `purge:true` deletes | re-drive |
| `REAP` | claims older than the pipe's timeout → `failed` with backoff (or `needs_review` at budget) | indox01 every 5 min |
| `GATE` / `CURSOR_GET` / `CURSOR_SET` | counts / the gmail UID walk position | |

---

## 2. Data model (Phase 0 DDL)

```sql
-- sync-private. NOT part of the business schema. Lives in supabase alongside incoming_documents.
create table if not exists sync_ledger (
  source       text not null,            -- registry sync name: drive-gdoc|drive-bs|gmail-doc|gmail-bs|gmail-link
  platform_id  text not null,            -- drive fileId / gmail message id (imap: canonical hex id)
  status       text not null,            -- 'delivered' | 'needs_review'
  doc_id       text,                     -- one-way pointer into incoming_documents.ID (nullable for needs_review)
  content_hash text,                     -- md5 at delivery time (observability/repair joins)
  delivered_at timestamptz default now(),
  primary key (source, platform_id)
);

-- failure bookkeeping (NOT sync state: rows self-delete on success; diff subtracts only not_before>now)
create table if not exists sync_attempt (
  source       text not null,
  platform_id  text not null,
  attempts     int  not null default 0,
  not_before   timestamptz,              -- backoff gate (jittered)
  last_error   text,
  updated_at   timestamptz default now(),
  primary key (source, platform_id)
);

-- discovery position (pure optimization — losing it = wasted list calls, never lost docs)
create table if not exists sync_cursor (
  source        text primary key,
  mode          text not null default 'walk',   -- 'walk' | 'steady'
  walk_token    text,                            -- drive pageToken / gmail window position
  steady_cursor text,                            -- gmail: uidnext (imap) or historyId (oauth); drive: unused (move shrinks source)
  updated_at    timestamptz default now()
);
```

**P0a — content dedup becomes a DB constraint** (required before ANY parallelism; standalone value):
```sql
-- delivery-time content identity. Company-level duplicate detection stays loop-2 business logic (DOUBLE).
create unique index if not exists uq_incdoc_hash
  on incoming_documents ("HASH")
  where "HASH" is not null and "HASH" <> '' and lower("HASH") <> 'unknown';
```
Delivery insert = `INSERT … ON CONFLICT ("HASH") DO NOTHING RETURNING "ID"` (+ one SELECT by HASH when
conflicted, to get the surviving `doc_id` for the ledger row). This **replaces the delivery-insert path
only**; the state machine's update-by-ID upsert is untouched. `Load Match Index` (whole-table read per
write — the O(table)/TOCTOU bomb, see code-review gate) is retired from the delivery path in v3 and can
then be retired from the router entirely once v1 sync is archived.
⚠ Pre-flight: dedupe existing `HASH` violations before creating the index
(`select "HASH", count(*) from incoming_documents group by 1 having count(*)>1 …` → merge/DOUBLE script).

---

## 3. Workflows (all new, tag `sync-v3`; all DB access via the API layer — rule stands)

| WF id | name | role |
|---|---|---|
| `syncV3Main0001` | Sync v3 Reconcile | schedule 15m + manual; reads `settings.sync_registry` (registry stays the config seam, add per-source `engine: v1\|v3` + `projection: on\|off` + `take`, `page_size`); one unit per source → executeWorkflow `syncV3Unit0001` mode=each |
| `syncV3Unit0001` | Sync v3 Source Unit | per source: read `sync_cursor` (mode) → list pages via **driveApi01/gmailApiRouter01 read-ops only** → per-page diff via `syncLedgerApi01 DIFF` → accumulate ≤ take X missing → executeWorkflow `syncV3Deliver0001` per item → save cursor → emit pass stats |
| `syncV3Deliver0001` | Sync v3 Deliver | per item: fetch (download op) → process (per-source adapter, below) → **Deliver** (router `DELIVER` = ON CONFLICT insert) → **Record** (`syncLedgerApi01 RECORD`) → on failure `ATTEMPT` (attempts+1, jittered not_before; ≥N → RECORD needs_review) → optional `syncV3Project0001` |
| `syncV3Proc*` (5) | per-source process adapters | **pure** extract-from-item → row-fields. Carved from today's SyncProc* minus all claim/move/label logic; reuse `Process Document` (indoxProcessDocument01) for OCR. No writes, no platform mutation |
| `syncV3Project0001` | Sync v3 Projections | drive move-to-processed / gmail retag; `onError: continueRegularOutput`; NEVER read back; gated by registry `projection` flag |
| `syncLedgerApi01` | Sync Ledger API | new thin router (op-contract like driveApi01): `DIFF {source, ids[]} → missing[]` · `RECORD {source, platform_id, status, doc_id, hash}` · `ATTEMPT {source, platform_id, error}` · `CURSOR_GET/SET` · `GATE {source} → counts` · `RESET {source}` (test/ops). Keeps the "nothing touches DB outside the API layer" rule; SQL stays thin + extractable to a service later |
| router addition | `indoxApiRouter01` `INLINE_ACTION: DELIVER` | the atomic content-dedup insert (supabase backend only) |

**Gmail discovery boundary (the one platform-side optimization):** walk = paginated search over
date windows (works today on inbox). Steady = per backend: imap → `UIDNEXT` cursor (small
inbox addition: search `uid:N:*` + return uidnext), oauth → `historyId`. This is the only
integration task with unknowns — isolated in `syncV3Unit0001`'s Gmail branch; walk mode alone is
sufficient for cutover (steady is Phase 5).

**Implementation gotchas to bake in (from memory — all previously paid for):**
`$('Node').item` breaks across executeWorkflow → use `.first()`/explicit maps · splitInBatches dies on
empty input → alwaysOutputData + IF-has-items · `$env` throws in expressions → registry/settings only ·
never `saveDataSuccessExecution:'none'` on queue sub-WFs · publish gate: `bbox n8n push` then restart
workers · webhook = the only cross-worker parallelism (lanes design relies on it).

---

## 4. Cutover (per source, reversible)

1. **Phase 0** DDL + P0a index + `DELIVER` action. No behavior change. Gate: kernel suite green.
2. **Phase 1** kernel WFs + `syncLedgerApi01`. v3 runs with registry `engine` still `v1` (v3 idle).
3. **Ledger seed (gmail only):** derive `(source, platform_id)` for existing rows from SOURCE_LINK/LINK
   → seed `sync_ledger` so the first walk doesn't re-deliver history (drive needs no seed — synced files
   were already MOVED out of the desired listing; re-delivery of stragglers collapses on HASH anyway).
4. **Per-source flip** `engine: v3` — order: `drive-bs` (1 pair, lowest volume) → `drive-gdoc` →
   `gmail-doc` → `gmail-bs` → `gmail-link`. v1 claim path stays importable; rollback = flip back.
   Projections start `off`, flip `on` after a green week.
5. **Archive** SyncScanner00001/SyncScanUnit0001/legacy claim logic + retire Load-Match-Index (tag
   `legacy`, active:false, then archive per dead-node-removal safety).

---

## 5. Test suites — same harness pattern as the v2 suites (this is the contract)

All suites follow the extracted recipe: `manualTrigger "▶ …"` + `webhook <suite>-e2e-lane`
(`responseMode: responseNode`) → `Seed Test Fixtures` (`indoxV2TestFixtures01`) → single **`Config`**
Code node (all ids/datasets/knobs; `watchMaxIter/watchWaitSec/knownPins`) → **`Cleanup Prior`**
(lane-scoped `DELETE … LIKE 'pfx_%'`, delete-before-seed, never truncate) → `Lane Switch`
(fallback `all` chains lanes via `Chain? (all only)` IFs) → per lane seed→act→watch→verify→assert→
cleanup ‖ `Respond Lane` → **`🏁 Test Summary`** `{RESULT:'✅/❌ …', passed:'n/m', checks:[…]}`.
Assert dialects: aggregate `{result, passed, fails, scorecard}` for multi-case lanes; throw-on-fail for
single-assert lanes; every assert emits a `result` containing `PASS`. Test rows: ID-prefix scoped.
Runner/CI contract: register in `scripts/indox-test.py` `SUITES/ORDER` (+`LANES/LANE_PATHS` +
`wait_for_webhooks`), corpus disjointness via `gen-suite-variants.py`, JUnit auto → `indox-e2e` check,
publish to `.ci-cd/indox-e2e/latest/`.

### 5a. `syncV3KernelTest01` — kernel unit suite (key `sync_kernel`, budget 360, prefix `sv3k_`)
**Pure Postgres via `syncLedgerApi01` + `DELIVER` — zero Google, zero OCR.** Webhook `sync-kernel-e2e-lane`.

| lane | exercises | key asserts |
|---|---|---|
| `diff` | DIFF membership math | seed ledger subset + synthetic page ids → missing[] EXACT; empty page; all-synced page → ∅; page > take X bounding |
| `record` | invariant 4 (ledger PK) | double RECORD same key → 1 row, second no-op; needs_review counts as terminal in GATE |
| `deliver` | P0a atomicity | two DELIVERs same HASH → 1 doc row, both return same doc_id; distinct HASH → 2 rows |
| `attempts` | poison path | ATTEMPT ×N → not_before excludes from DIFF; attempts≥N → needs_review ledger row + attempt row gone; success mid-way deletes attempt row |
| `order` | invariant 3 | simulate crash-between: DELIVER without RECORD → DIFF still returns item → re-DELIVER collapses (same doc_id) → RECORD → gone from DIFF |
| `cursor` | walk resume | CURSOR_SET/GET roundtrip; RESET → walk restarts → asserts zero re-processing (ledger unchanged) |
| `cov` | node coverage | drives every branch above, then asserts the coverage contract (§5d) |

### 5b. `syncV3SourcesTest01` — per-source E2E (key `sync_sources`, budget 900, webhook `sync-sources-e2e-lane`)
Lanes = **one per source**: `drive-gdoc, drive-bs, gmail-doc, gmail-bs, gmail-link` (prefix `sv3s_<lane>_`).
Gmail lanes run against **localmail** (GreenMail — already CI-proven), drive lanes against the test Drive
folders; inject via existing recipes (drive upload via driveApi01; gmail serial IMAP append batchSize 1).

Per-lane template (identical shape ×5, only the injector + adapter differ):
1. **seed**: inject K scoped docs into the REAL source (names/subjects carry `sv3s_<lane>_`).
2. **act**: webhook-trigger `syncV3Unit0001` for that source (page_size + take X forced small via Config
   so pagination executes even at K≈10).
3. **watch**: poll `GATE` until `delivered == K` (staticData iter counter + pg_sleep, capped).
4. **verify+assert**:
   - ledger: exactly K delivered rows, doc_id set, content_hash set;
   - `incoming_documents`: K rows, provenance fields (SOURCE_TYPE/LINK/RECEIVED_DATE) correct,
     **zero sync-state fields written**;
   - **read-only assertion**: re-list source → all K items STILL present (projections off) — the
     platform was not mutated;
   - idempotence: re-trigger unit → GATE unchanged, zero new executions of Deliver;
   - dup matrix: re-inject same item id → diff excludes; inject NEW item with identical bytes →
     +1 ledger row, doc rows unchanged (hash collapse);
   - projection sub-check: flip projection on → item moves/retags; break dest folder id → delivery
     STILL green (projection failure isolated).
5. **cleanup**: delete scoped rows + ledger + attempt rows + source items (drive delete / mail purge).

### 5c. `syncV3FullTest01` — full-sync battery (key `sync_full`, budget 1080, webhook `sync-full-e2e-lane`)
Lanes (prefix `sv3f_`):

| lane | scenario | key asserts |
|---|---|---|
| `mixed` | all 5 sources seeded concurrently (N each) → `syncV3Main0001` → converge | gate closes per source; totals: Σseeded == Σledger == doc rows; second full pass = zero work |
| `history` | ~300 items, page_size 50 / take 25 → walk; **kill mid-walk** (re-trigger lane) → resume | converges; ledger count EXACT (no double-processing); cursor loss tolerated (re-walk = list calls only, assert Deliver execution count unchanged) |
| `races` | double-fire same source unit concurrently; + same-content two-sources | one ledger row per (source,id); one doc row per content hash; cross-source same doc → 2 ledger / 1 doc(+DOUBLE per loop-2) |
| `chaos` | poison doc (corrupt bytes → OCR fail) · projection failure injection · crash-order replay | poison → needs_review after N, gate still closes; chaos never blocks other docs; deliver-then-die → collapsed on re-pass |
| `handoff` | delivered docs flow into loop 2 | sampled docs reach loop-2 terminal via existing 30s poll — seam intact (thin: full loop-2 quality stays `pipeline` suite's job) |

### 5d. Coverage — "100%" made mechanical, two layers
1. **Node coverage (hard 100% gate):** new `scripts/sync-v3-coverage.mjs` (pattern:
   `indox-v2-actions-test.mjs` + `fetch_summary`'s flatted-parse): after the three suites run, read
   `execution_data` for all executions of the 8 sync-v3 WFs in the run window, union executed node
   names, diff vs each workflow JSON's node set (minus stickies/disabled). **Any never-executed node
   fails CI** — this is literal 100% node coverage, enforced, and it keeps future edits honest (a new
   node without a test trips the gate). Registered as a step in `indox-e2e.yml` after the battery.
2. **Branch/handler coverage (suite-internal):** each suite's `cov` lane enumerates `covCases`
   (`{case, expect…, seed}`) for every logical branch — the §5a-c tables are the case inventory;
   asserts `passed:'n/n'` listing misses. `knownPins` reserved for tolerated environmental flakes only.

Code coverage of the JS Code nodes = same node gate (a Code node is covered iff executed) + the branch
lanes force each internal path (success/conflict/error/poison/empty-page) — asserted by outcome, which
is the only observable that matters at this layer.

### 5e. Runner/CI registration (mechanical)
`indox-test.py`: `SUITES += sync_kernel(360) sync_sources(900) sync_full(1080)`; `ORDER = [sync_kernel,
doc_base, bs, sync_sources, gdoc, sync_full, pipeline]` (kernel first = fail-fast, cheap);
`LANES/LANE_PATHS` for all three; extend `wait_for_webhooks`. `gen-suite-variants.py`: add `sv3s/sv3f`
tags for shared demo-docs (hash-disjoint corpora → suites stay `--parallel`-safe). CI unchanged
otherwise — `bbox indox test all --parallel --budget-scale 1.5` picks everything up; JUnit
`indox-<key>` testsuites; publish step already globs. Budgets keep total battery inside the 38-min job.

---

## 6. Workstreams & gates

| # | workstream | depends | gate |
|---|---|---|---|
| W0 | DDL + P0a index (+ violation pre-clean) + `DELIVER` action | — | migration applied; existing suites still green |
| W1 | `syncLedgerApi01` + kernel WFs (`Main/Unit/Deliver/Project` skeleton) | W0 | `sync_kernel` green locally + CI |
| W2 | 5 process adapters (pure) + source injectors | W1 | `sync_sources` green (gmail via localmail) |
| W3 | full battery + coverage gate script + CI registration | W2 | `sync_full` green; coverage 100%; full CI battery green |
| W4 | ledger seed (gmail) + per-source cutover flags + flips | W3 | each source: 1 green week live, gate closing, zero NEEDS_REVIEW growth |
| W5 | archive v1 sync + retire Load-Match-Index; steady-mode gmail cursor; projections default-on; Retry-After+jitter in driveApi01/gmailApiRouter01 | W4 | legacy tagged/inactive; steady mode cuts walk cost |

Definition of solid: all three sync suites + existing four suites green in one CI battery, node-coverage
gate at 100%, and the convergence gate provably closing on a full-history walk in `sync_full/history`.
