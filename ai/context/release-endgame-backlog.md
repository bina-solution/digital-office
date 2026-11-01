# Release endgame — the full collected backlog (2026-07-08)

Everything left between "here" and a **fast, proven, well-organised release**: backend-API
config unification, apitools speed, the 5-minute CI lane, remaining correctness opens, and
the release-plan proof phases. Companion to `release-lockin-plan.md` (phases/gates) — this
doc is the concrete work list. Check items off here; keep gate definitions there.

Lanes (do not cross): `release-v2-lockin` = stabilisation lane (other agent).
`ci-image-prebake-poc` = speed/CI lane. apitools changes land via the submodule.

---

## WS1 — Integration-API backend config: unification + cleanup

**Rule being locked in:** every integration API (DATA / DRIVE / GMAIL) checks its backend in
exactly ONE place — its router. No workflow ever branches on backend itself.
**Config precedence (agreed):** `.env` → `settings` row → hardcoded default.

Current state (audited 2026-07-07):

| API | Router | Configured via | Default | Violations |
|---|---|---|---|---|
| DATA | indoxApiRouter01 | redis key `n8n.indox.data_backend` | supabase (was sheets ×7) | 5 active WFs self-check + private sheets branches + `__force_backend` params |
| DRIVE | driveApi01 | `.env DRIVE_BACKEND` (n8n-push sed into Pick Backend) | google | none |
| GMAIL | gmailApiRouter01 | hardcoded const | imap | none |

- [x] 1.1 (implemented as push-time resolution instead of seeded rows — the substituted
      router constant IS the config; settings row = optional override layer read at push)
      ~~Seed `settings` rows `backend_data` / `backend_drive` / `backend_gmail` from `.env`
      (`INDOX_DATA_BACKEND` / `DRIVE_BACKEND` / `GMAIL_BACKEND`) in the Seed Fixtures workflow
      (TABLE_UPSERT, only-if-env-set), defaults in-router.
- [x] 1.2 indoxApiRouter01: read `backend_data` setting (cached) instead of the redis key;
      retire `n8n.indox.data_backend` everywhere (grep-proof: zero references).
- [x] 1.3 driveApi01 + gmailApiRouter01: same one mechanism (env-substitution stays as the
      .env layer; router falls back to settings row, then default). One documented pattern ×3.
- [x] 1.4 (params still SENT by callers but stripped+ignored by adapters; inert) Remove `__force_backend` params from callers (tests get their backend via env/settings
      like everyone else).
- [x] 1.5 DONE 2026-07-08 (77327d8: -607 lines; backend forks deleted from all 5; sheets node-islands left inert for Phase 3b prune). CLEANUP (tier 2): delete the private sheets branches + self-checks from the 5
      violators (Create Incoming Document, Incoming Documents v2 Scan Backend IF, Batch
      Upsert, Get Incoming Document, Settings ×2, 0.1.7) — they route through indoxApiRouter01
      only. ⚠ This narrows the release-plan "sheets dual-path kept as-is" freeze: the sheets
      *implementation* stays (inside the router), but per-workflow dual paths go. Sequence
      AFTER WS3 CI is green so the suite catches regressions.
      SCOPED 2026-07-08 (per WF: kill `Read Backend`+`Backend IF`, wire supabase path direct,
      remove sheets-only nodes after a full `$('…')` reference scan — see
      n8n-dead-node-removal-safety): Create Incoming Document 2 sheets nodes; Batch Upsert 6
      (incl. Get Tags Settings); Get Incoming Document 5; Incoming Documents v2 5 (+ Google
      Sheets Trigger!); Settings 2 (+ two Backend IFs). ~25 nodes total.
- [x] 1.6 Document the final pattern in `architecture-map.md` + `indox-testing.md` (backends
      section), including "how to add a backend" in 5 lines.

**Gate:** full `bbox indox test all` green twice: once `DRIVE_BACKEND=local`+supabase data,
once google+supabase; grep shows zero backend conditionals outside the 3 routers.

## WS2 — apitools under real OCR load (RULING 2026-07-08: NO new caching)

USER RULING: OCR must REALLY run in e2e — no query-result cache, no pre-seeded ocr_cache
fixtures for now. (The existing md5-of-bytes OCR cache stays: it just means each doc is
OCR'd once per fresh environment, which is the honest cost.) The work is instead: **measure
the real cost and make every suite complete on the slow 2-vCPU Actions runner.**

Root cause context (measured): burst congestion — ~114 json-query calls/run against 6
blocking slots; worst real query standalone = 0.47s, under burst = 10–71s tails. CI
additionally pays full 300-DPI Tesseract once per doc.

- [x] 2.1 **Profiled cold OCR at 2 CPU** (2026-07-08): 113.5s total / 13 corpus docs
      (per-doc 2–20s, worst = plx_shp3 19.9s). Honest CI floor ≈ 2–2.5 min of Tesseract,
      amortised across the run. No pathological docs.
- [x] 2.2 **Profiled query burst at 2 CPU**: 104 concurrent real-query calls = 1.2s wall,
      p95 0.46s. apitools is NOT the bottleneck — measured local slow window had 61
      CONCURRENT n8n executions (2,048 in 4 min) starving the box; apitools calls inflate
      20–150× under that. Verdict: fix the n8n-side churn, not apitools.
- [x] 2.3 → root causes found & fixed instead of de-bursting:
      (a) leaf sub-WFs saved full success data (25KB+/exec × ~2k execs) → tried
          saveDataSuccessExecution=none on 6 leaves — REVERTED: n8n 2.17 queue mode never
          finalizes those entity rows (status='running', stoppedAt NULL forever → 8.6k
          unprunable orphans per battery). Leaf data stays saved; pruner keeps it bounded;
      (a') the n8n execution PRUNER handles volume (max_count 2000 / 168h) — rely on it;
      (b) n8n-push didn't restart WORKERS → stale in-memory workflows ignore new
          settings (CLI import + SQL bypass pubsub reload) → workers added to restart;
      (c) drive-local `l:shape list` alwaysOutputData emitted phantom `{}` for empty
          folders (google-parity bug) → Sync Processor download/move with empty id →
          29+8+6 error executions per battery (worse in CI) → flag removed;
      (d) CI: N8N_WORKER_CONCURRENCY=4 (was 2×8 on 2 vCPU).
- [ ] 2.4 **Stall-detector safety**: verified indirectly (heartbeats kept beating through
      CI's slow phase; execs move constantly). Re-verify after fixes on a green CI run.
- [ ] 2.5 Set suite budgets FROM measured CI numbers post-fix; document in
      `indox-testing.md`. CI battery step timeout raised 16→24min (must exceed CLI
      worst-case 300+300+720 so the timeout verdict + dump aren't beheaded).
- [ ] 2.6 CI diagnostics: errored-executions dump was null-concatenation-blank → rewritten
      (grouped counts + null-safe last-10). Verify output on next red run.
- [ ] 2.7 Investigate leftovers once loud errors are gone: invoice Extractor "Invalid output
      format" (3/battery, retried OK), gmail scanner error-loop in CI (no creds — candidate:
      backend_gmail=none setting from WS1 makes scanners no-op cleanly).
- KNOWN NOISE (accepted): suite NEGATIVE cases produce ~11 `drive api (- local)` error
  executions per full battery by design — doc_base `db_figure_company` dummy LINK
  `http://x/f`, gdoc garbage-link case `GDOC_GARBAGE_XYZ`. Suites green; don't chase these
  in the error census. Baseline after phantom-fix (battery#3 2026-07-08): 11 drive +
  3 invoice-extractor ("Invalid output format", retried OK) = 14 total; more than that =
  investigate.

**Gate:** full `bbox indox test all` completes green on the 2-vCPU runner with real local
OCR, twice consecutively, within documented budgets; no stall-kill false positives.
**GATE CLOSED 2026-07-08:** TWO consecutive full-green fresh-machine runs — 28910279506
(doc_base 126s / bs 42s / gdoc 754s / pipeline 175s, battery 1118s) and 28911952568.
Merged back into release-v2-lockin (9869ba5 + 80f510b budget fix) per U-ruling;
ci-verify green on both merges.

## WS3 — CI/CD: fast, organised, fresh-machine-proven

Proven so far: doc_base ✅129s + bs ✅51s on fresh CI; prebake = setup 8-9min → 4.5min.
Target: **full indox e2e ≤ 5min**, one green required lane, zero special setup steps.

- [ ] 3.1 Merge prebake PoC → main lane (with the stabilisation agent): content-addressed
      image tags (hash of dockerfile+context, not mutable `:ci`), build-fallback when the
      tag is absent, digest-pinned GHCR mirrors of third-party images.
      RULING: once baked images are PROVEN, merge `ci-image-prebake-poc` back into
      `release-v2-lockin` (coordinate with the stabilisation agent's in-flight work).
- [~] 3.2 USER RULING 2026-07-08: **TRUE ALL-PARALLEL required** — prove locally, then CI.
      PROGRESS same day: content-unique corpora via OCR-guided re-stamping
      (scripts/gen-unique-corpus.py, 21 variants, all Tesseract-verified; see
      unique-corpus-map.json); AI-cache clones with numbers replaced; content-versioned
      upnames (md5-suffix) kill stale drive-file reuse; per-suite-scoped cleanups;
      CLI --parallel + --budget-scale. Parallel run #2: all 32 docs COMPLETED, zero
      DOUBLEs, 3 suites green; 2 stamp-geometry KW drifts pinned (plx_inv2, plx_shp3 —
      same class as the original shp3 pin). Full-green proof runs in flight.
      Plan: content-unique per-suite corpora. The demo docs appear GENERATED
      (production/n8n/demo-docs/_active-blueprint.json + companies.json = declarative
      generator inputs) → regenerate per-suite copies with suite-specific doc NUMBERS;
      synthesize matching ai_extraction_cache values (string-replace the number in the
      cached JSON — we control both); update suite GT assertions accordingly. Then CLI
      runs all 4 suites concurrently (threads); prove locally (battery ≈ max(suite)) then
      on CI. Also verify doc_base may already be parallel-safe (its docs park BEFORE
      extraction — see published CSV: db_* rows end MISSING_*/UNKNOWN_* states).
      History: — CORRECTED 2026-07-08: byte-variants DONE (22 per-suite
      variant files + cloned ai-cache rows, scripts/gen-suite-variants.py; hash-collisions
      dead) BUT the COMPANY_ID+SHORT_DOC_ID dedup rule makes content-identical docs collide
      regardless of bytes → gdoc/pipeline/doc_base (15 shared source docs) can NOT run
      concurrently. Only bs is content-disjoint (parallel-safe with anything). Full
      concurrency needs content-unique per-suite corpora = the synthetic-doc generator
      (per-type fixture architecture / dataset.csv GT) — next-release scope.
- [ ] 3.3 THE viable parallel win: split GDOC INTERNALLY (its 15 docs are content-unique) —
      2 parallel halves ≈ 754s → ~400s; schedule [gdocA ∥ gdocB ∥ bs] → [doc_base →
      pipeline] ≈ 13min battery. Plus pipeline `pg_sleep 20→5` (minor).
- [ ] 3.4 Optional after measuring: `saveDataSuccessExecution=none` on leaf API workflows;
      4-vCPU runner ruling (user, costs money).
- [ ] 3.5 CI hygiene lock-in: keep heartbeats + stall-kill + errors=N(+Δ) (shipped);
      per-suite timeout budgets documented in `indox-testing.md`; scorecard publish stays.
- [ ] 3.6 One workflow file layout: `ci-verify.yml` (deployment) + `indox-e2e.yml` (product)
      + `build-images.yml` (prebake); delete PoC-only cruft on merge; README section: what
      runs when, what a red lane means, where artifacts live.
- [ ] 3.7 gdoc 720s CI budget resolved BY WS2 speed (not by raising budgets).

**Gate:** fresh-machine full `bbox indox test all` green in ≤5min wall-clock on the standard
runner, twice consecutively, zero manual steps beyond secrets.

## CI/CD timing — measured baseline (2026-07-08) + the path to faster

All numbers from green runs on standard 2-vCPU GitHub runners, real local OCR, no caching.

| Lane | Stage | Measured |
|---|---|---|
| build-images (PoC) | build job (GHA cache warm) | ~1–4 min |
| build-images (PoC) | pull prebuilt images | 160s |
| build-images (PoC) | bring up lean stack | 81s |
| build-images (PoC) | n8n blueprint push | 26s |
| build-images (PoC) | full battery | **1118s** (doc_base 126 / bs 42 / gdoc 754 / pipeline 175) |
| build-images (PoC) | **job total** | **~23 min** |
| indox-e2e (release) | build on runner + stack + battery | ~25 min green case; cap 45m (worst >35m killed run 28913581495) |
| ci-verify (release) | deployment verify + screenshots | ~17–18 min |

Budget rationale (indox-test SUITES): doc_base 360 / bs 480 / gdoc 900 / pipeline 720 —
each set from a measured healthy-at-budget incident, not vibes. Battery step cap 27m
(build-images) and job cap 45m (indox-e2e) must exceed the CLI's fail-fast worst case.

### What's left to fasten (ranked by minutes saved)

1. **Adopt prebaked images in indox-e2e.yml** (WS3.1: content-addressed tags + build-
   fallback): kills ~9 min of on-runner builds → release e2e ~25m → ~16m. Also makes the
   35m-class timeout impossible.
2. **Parallelize suites on disjoint corpora** (WS3.2): battery 18.6m → ~max(gdoc) ≈ 13m
   wall. Needs per-suite corpus separation (no cross-suite dedup collisions) — scoped.
3. **Split gdoc's batch-extraction lane** into a 5th parallel suite / halve its corpus per
   lane (WS3.3): gdoc 754s → 2×~400s in parallel → battery ~8–9 min.
4. pipeline pg_sleep 20→5 + hybrid driving: −1–2 min (matters only after 2–3).
5. Image slimming / zstd layers: pull 160s → ~100s (minor).

**Honest floor:** gdoc's 754s is dominated by real Tesseract OCR + extraction on 2 shared
vCPUs (per USER ruling: no caching — OCR must really run). With steps 1–3 the full battery
lands ~8–9 min end-to-end (~13 min job with setup). Getting the FULL battery under 5 min on
2 vCPU is not achievable without caching OCR, shrinking the corpus, or paying for a bigger
runner (U4: ruled skip — repo is private). A 5-min PR-gate IS achievable as
doc_base+bs+pipeline in parallel (~4–5 min incl. setup) with gdoc in the heavier lane —
needs a USER ruling on splitting gate vs full battery.

## WS6 — Performance profiles (design ready, next arc)

Measured 2026-07-08 (1h any-concurrency window): apitools demand p90=20 concurrent against
6 blocking slots on 4 CPUs → 10-100× queue inflation (query p50 0.3s→3.16s); main WF
trigger-flood (178 killed entries/h, 11.3k CPU-s); 7.2k lock/router sub-execs/h.
DESIGN: ai/context/indox-performance-profiles.md — PERFORMANCE_PROFILE per machine envelope
(ci-small/laptop/vps/prod), applied by n8n-push via the backend-substitution mechanism:
compose env block + perf_* settings rows + workflow constants (fan-out/chunk/take). Sizing
rules from cores; feeder ≤ consumer is the core invariant. Steps in the doc.

## WS4 — Correctness/stability opens (pre-acceptance)

- [ ] 4.1 Fresh-stack cascade leftovers: get_company_name loop, sync-state hang,
      worker auto-start (memory: fresh-stack-bringup-cascade).
- [ ] 4.2 Frozen-cache curation for XLSX EXTRACTION_FAILED + JPG MISSING_TYPE demo docs.
- [ ] 4.3 doc_step lock release under load — re-verify at 100-doc scale in Phase 3 (unlock
      fix landed; churn was the old #1 blocker).
- [ ] 4.4 gdoc last-5-uncovered nodes + shp3 KW pin: keep as knownPins, review at Phase 3.
- [ ] 4.5 Warehouse folder TODO→config (check_from_office fix left it hardcoded).

## WS5 — Release-plan proof phases (unchanged, from release-lockin-plan.md)

- [ ] 5.1 Phase 2: prove all 5 syncs short-term.
- [ ] 5.2 Phase 3: 100-doc high-load acceptance run to rest (uses WS2/WS3 speed).
- [ ] 5.3 Phase 3b: prune legacy (disabled "V2 thin batch-25" etc.) + full tag organisation.
- [ ] 5.4 Phase 4: re-context + package.

## USER decisions — RULED 2026-07-08

- [x] U1 Shipment actions router: stays cancelled; shipment handling stays implemented in
      GDoc actions. Keep as-is.
- [x] U2 Vision key rotation: NOT now — focus is the fully-working LOCAL version.
- [x] U3 Gemini billing: NOT now — tests use the AI cache; live extraction out of scope.
- [x] U4 4-vCPU runner: CLOSED as skip — repo is PRIVATE (checked 2026-07-08), so free
      runners are 2 vCPU; 4-vCPU would be paid. Revisit only if 2-vCPU budgets can't hold.
- [x] U5 WS1 tier-2 (sheets-branch deletion) confirmed in-release, sequenced after CI green.

## THE CONSOLIDATED PLAN (2026-07-08 — three tracks, run in parallel)

**Method — the maximum-speed loop:** every iteration overlaps three lanes:
(1) IMPLEMENT: edit blueprint/scripts → `bbox n8n push` → local PARALLEL battery (~11 min)
    as verification; (2) PROVE: CI runs the previous landing (~20 min) unattended, publishing
    results + table CSV + concurrency PNG per commit; (3) OBSERVE: any-concurrency measures
    live behaviour → feeds the next iteration. Nothing waits on anything; backlog + memory
    updated at every landing.

**Track A — v2 lock-in (the release bar)**
- A1 ✅ CLOSED 2026-07-08: TRUE ALL-PARALLEL proven — local ×2 (11-min walls) + CI green
  (run #23 / 7d9261c: bs 115 ∥ doc_base 180 ∥ pipeline 739 ∥ gdoc 973 = 16.2-min battery on
  2 vCPU). Per-version artifacts live: results/junit/CSV + concurrency-1h.png/txt.
  (was: parallel battery green ×2 local (attempt 4 in flight; budgets finalized
  360/480/900/900) → commit the true-parallel set → CI `--parallel` green ×2 (~19–22 min).
- A2 ✅ CLOSED 2026-07-09: all 5 syncs proven inject→rest on LOCAL mail + LOCAL drive
  (gmail-doc/bs/link + drive-gdoc/bs → COMPLETED). The downloader-binary blocker below is
  FIXED (added 'Download PDF (binary)' node materializing the resolved URL before Upload
  Document; crash-proof l:size). Full locality landed as a bonus: localmail (email.localhost)
  + localdrive Drive-grade app (drive.localhost, browser-QA'd — .hidden cascade + /file/d
  504 consolidation fixes). CI-provable now. Original note below for history.
- A2 Phase 2 (history): all 5 syncs inject→rest, local. STATUS 2026-07-09: drive-gdoc PROVEN
  (register + 3×COMPLETED + correct UNKNOWN parking; needed drive-api-local size fix),
  drive-bs register+process proven (to company gate), gmail-doc PROVEN E2E (3×COMPLETED,
  cross-source HASH dedup demonstrated). gmail-bs/link: blocked on REAL Gmail by X-GM-RAW
  index nondeterminism (dateless-MIME injector bug fixed; index still flaps) → pivoted to
  LOCAL MAIL (user directive): mailserver+webmail live, scanner/claim/advance proven
  deterministic E2E; remaining blocker is a PRODUCT bug — 'Gmail Link Documents Downloader
  2.0' Upload Document expects binary from Process Document's return but no node
  materializes it (Is PDF?→Merge has no download node; Process Document hands the URL to
  apitools without n8n binary) → Buffer.from(undefined) in driveApi upload; gmail-bs
  'Save Balance Doc' errors similarly. Fix the downloader binary contract (download the
  resolved URL into binary before Upload Document, or upload via apitools file_hash) and
  the gmail legs close ON LOCAL MAIL (= CI-provable). Also fixed en route: Label Engine
  stealing to_sync mails (now excludes *_TO_SYNC/IN_PROGRESS), legacy gmail scanners
  deactivated (two sync generations were competing), companies seeding + ACTION_RESTART
  re-drive documented as the missing-company recovery path.
- A3 Phase 3: 100-doc acceptance through sources + 24h soak — RUNS UNDER THE PROD PROFILE
  (B4), pinning its numbers. [1–2 days]
- A4 Phase 3b prune (sheets islands, _diag clutter, tag org) + Phase 4 package.

**Track B — resource profiles & concurrency optimisation (WS6, design complete)**
- B1 perf-profiles.yml + perf-manifest.json + push-time application (mirror
  substitute_backend); apply `laptop` locally → MEASURE: query p50 3.16s→~0.5s,
  battery wall −20%. [~½ day]
- B2 Wire the 10 marked knobs (extract fan-out, Query pacing ×5 — 4 are UNPACED today,
  line-poll, main jitter→0 on dev, scanner/sync intervals+takes, 35s upsert-wait check,
  env block, test budgets). Class-B serializers stay pinned; class-C chunkers stay put.
- B3 Main trigger-flood lock-early exit (178 kills/h → 0) + per-entry config cache.
- B4 `ci-small` on CI (re-measure battery; expect ~16 min & steadier) + `prod` profile
  proven by A3's acceptance run.

**Track C — CI lane upkeep (continuous, keep while A/B progress)**
- C1 Per-run artifacts live: results.txt + junit + incoming_documents.csv + concurrency
  PNG/txt (validate on next CI run).
- C2 Budgets updated from measured runs only (no vibes); scorecard trends reviewed via the
  committed artifacts per version.
- C3 Later/optional: image slimming (pull 161→~90s), Hostinger-VPS self-hosted fast lane
  (proof lane stays ubuntu-latest), 5-min PR-gate ruling.

Order of the next sessions: finish A1 (today) → B1+B2 (next, they directly de-flake and
speed everything after) → A2 → B3 → A3 under prod profile → A4.

## Historical order notes (superseded by the consolidated plan)

1. WS2.1–2.2 measurement (real OCR + burst on 2 CPU) → 2.3–2.5 fixes/budgets from numbers.
2. WS3 prebake proven → **merge back into release-v2-lockin** → parallel suites → 5-min-class gate
   (real-OCR floor may move the exact number; budgets come from WS2 measurements).
3. WS1.1–1.4 (config unification, freeze-safe) → then 1.5 cleanup under green CI.
4. WS4 fixes → WS5 proofs → package.
