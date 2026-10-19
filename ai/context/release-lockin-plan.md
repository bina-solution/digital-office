# Release: lock-in v2 refactor → clean, stable, client-billable version

Authored 2026-07-07. Owner: william + agent. Companion docs: `indox-v2.1-state-machine-plan.md` (state
machine), `indox-sync-control-plane.md` (sync design), `api-abstraction-refactor.md` (db/gmail layer),
`release.md` (release runbook), `indox-expected-behaviour.md` (runtime spec).

## The goal (agreed 2026-07-07)

Lock all refactor gains into ONE clean, stable, releasable version — same functionality as the live
hacohen-VPS deployment, but on the refactored stack (v2 state machine, db/gmail API layers, sync_registry,
config-driven behaviour). **Definition of done (verbatim bar):** run locally and prove all syncs working
short- and long-term + high load; full document pipeline verified; a **full clean 100-document sync-to-rest
run with no issues/mistakes — smooth, fast, exactly-as-expected results** (all documents through sync, full
pipeline, high-quality extraction, no drift). VPS migration/swap is a SEPARATE later step — this release
produces the proven-ready version + migration plan, not the swap.

## Scope — decisions taken

| Area | Decision |
|---|---|
| GDoc invoice/shipment physical fork | **DEFERRED** (next release). Decide-level split is done + 700k-fuzz-proven; physical fork is structure-only, no behaviour gain, new risk. Ship 3 routers: DOC BASE / GDoc / BS. |
| Sync control-plane rework (`sync source` primitive, pure processors, RESET/STATUS off registry) | **FREEZE architecture; verify function.** Current scanner/scan-unit/processors ship as-is IF all 5 syncs prove functional. Only build the *minimum* needed to make any broken sync work (see Phase 2 gmail check). Full sync-refactor-v2 = next release. |
| Sheets-node unification (−57 nodes), config-fixture engine, router_order, KW per-type extractors | **OUT** (next release). Fixture engine already descoped in v2.1 plan §I. |
| shp3 OCR pin (14/15 extraction) | Fix if cheap during Phase 1; otherwise document as known limitation in the release report. Not a gate. |
| Clean minimal + tags (added 2026-07-07) | **IN.** No legacy/redundant workflows in the release set; every workflow tag-organized under one canonical taxonomy. |
| CI hard-lock (added 2026-07-07) | **IN.** Router E2E suites + the Driver full-pipeline suite run in GitHub Actions ci-verify — fully declarative, zero manual work. |
| Driver full-pipeline E2E clone (added 2026-07-07) | **IN.** A 1:1 clone of the action-router E2E suites that drives the SAME tests through the main Driver (real full pipeline, all types). Main indox = hard-locked by router suites + Driver suite together. |
| Repo re-context (added 2026-07-07) | **IN.** Entire deployment-hacohen re-contexted: every production file explained, cleaned, dead files removed, context docs de-drifted. |
| VPS swap strategy | Later, separate: deploy dormant → shadow-diff vs 0.1.7 on real traffic → flip with 0.1.7 kept dormant for instant rollback. Documented in Phase 5 deliverable, not executed now. |

## What ships (the release set)

- **v2 state machine** (tag `indox-state-machine-v2` / `sm-refactore-v2.1`): `indoxV2Driver01` (Driver) +
  `indoxV2Decide01` (pure orchestration decide) + routers DOC BASE / GDoc / BS (each decide+execute mode) +
  `indoxV2Upsert01` central upsert. Batch decide proven (4 docs → 3 executions).
- **Data layer**: `indoxApiRouter01` front door, supabase backend (sheets dual-path kept as-is), Batch
  Upsert dedup ruling.
- **Gmail layer**: `gmailApiRouter01` → imap|oauth (IMAP structurally production-ready; app-password flow
  documented in `gmail-onboardin-imap-stmp.md`).
- **Sync layer**: `sync_registry` + Scanner/ScanUnit + 5 processors + `sync api` scaffold (as-is).
- **Test suites**: DOC BASE 5/5 (100% node cov), BS 4/4 (100%), GDoc 14/15 (95%), all batch-mode; + the new
  full-pipeline test (Phase 1).
- **Docs**: updated context docs + before-release-report + migration plan.

## Phases (each gated; nothing advances on red)

### Phase 0 — Reconcile & snapshot (the real lock-in risk)  [~½ day]
The refactor currently lives in the LIVE local n8n instance + a large uncommitted working tree; blueprint
files have drift (e.g. old gmail scanners `active:true` in files but deactivated live; 0.1.4 severed live
but `active:true` in blueprint). Steps:
1. `bbox n8n pull` → blueprint == live instance. Diff-review the pull (nothing unexpected reverts).
2. Inventory the active set; assert every v2 workflow + shared sub-WF is active+activeVersionId
   (publish gate). Assert 0.1.4 truly severed (dormant, nothing references it) and decide the correct
   active flags for the 4 old gmail scanners (see Phase 2).
3. Sort the uncommitted working tree: (a) refactor deliverables (b) unrelated drift. **Ask before any
   commit** (standing rule), then commit deliverables to a release branch (suggest `release-v2-lockin`
   off `shlomo-laptop`). This is the single highest-value step — until committed, months of work exist
   only in a working tree + a docker volume.
4. Backup: fresh `data/_wf_backup/` export + supabase dump.

**Gate 0:** repo == live, release branch exists, all suites still green post-pull (DOC BASE 5/5 · BS 4/4 · GDoc 14/15).

### Phase 1 — Close the known pipeline gaps + the Driver E2E clone  [~1–1.5 days]
1. **Build the Driver full-pipeline suite** (`indox v2 full pipline`, specced in v2.1 plan) as a **1:1
   clone of the action-router E2E suites**: same Config → Execute Flows fan-out → coverage · timed single
   lifecycle · batch lifecycle · 🏁 summary — but every Act drives the **main Driver**
   (`indoxV2Driver01`), not the collections. Docs seeded with ONLY a link → all DOC BASE actions (figure
   type+company from the file) → all type actions → COMPLETED, for INVOICE / SHIPMENT / BALANCE_SHEET
   (+ORDER-as-invoice). Result: main indox is **hard-locked twice** — routers pinned in isolation by their
   suites, the real pipeline pinned end-to-end by this one.
2. Fix the 5 terminal `no_action` mis-routes in Driver `Switch1` (currently mis-route to gdoc/bs as no-ops)
   + the `1`-suffix naming cruft — cheap correctness/hygiene flagged in the v2.1 plan.
3. GDoc last 5 uncovered nodes (seeded shipment create/update + find_link-found): attempt cheaply; else
   keep documented as deferred edge branches.
4. shp3: one bounded attempt at the OCR anchor fix (doc-date vs dispatch-date, stylized-id truncation).

**Gate 1:** Driver suite green for all types; all router suites green; bare-link→COMPLETED timed + recorded.

### Phase 1b — Consolidate the test entrypoint into the CLI  [~½–1 day]
Once the n8n suites are final (Phase 1), route them into ONE CLI verb — consolidating ALL the scattered
testing attempts into a single entrypoint (per the bbox one-tool principle):

```
bbox indox test [all | doc_base | bs | gdoc | pipeline] [--ci-mode] [--junit <path>]
```
- Invokes each suite headlessly (the proven REST manual-run mechanism), waits, parses the 🏁 Test Summary,
  prints a scorecard, exits non-zero on any red; `--junit` emits JUnit XML.
- `--ci-mode` passes `ci_mode:true` into each suite Config (fixture/cache-only lanes; live-external lanes
  skip-with-note).
- **Consolidates + retires** the scattered attempts: `scripts/indox-v2-contract-test.sh`,
  `indox-v2-actions-test.mjs`, `indox-v2-contract-assert.py`, the nodecov/coverage one-offs, ad-hoc
  runner scripts. Keep `indox-doc-trace.py` (a trace tool, not a test) and the feature-validation suite
  (separate observability concern — the CLI can gain `bbox fv run` later).
- One doc: `ai/context/indox-testing.md` — how the suites, the CLI, and CI relate.

**Gate 1b:** `bbox indox test all` green locally in both modes; old test scripts removed; no duplicated
test entrypoints left.

### Phase 1c — CI hard-lock: the CLI in GitHub Actions  [~½ day]
`ci-verify` already boots the full stack from scratch (compose + .env + blueprint push, 25 checks) — extend
it with `integration-n8n-indox-e2e-*` checks that simply run **`bbox indox test all --ci-mode --junit`**
after the push/publish step and publish the per-suite JUnit results. CI never re-implements test logic —
it calls the same CLI a human runs, so everything stays consolidated.
Suites: router_doc_base · router_bs · router_gdoc · **driver full-pipeline** (+ decide parity if kept as a
workflow).

**CI-mode design (the runner has NO real Google/Gemini secrets and strips the private apitools submodule):**
- Tests must run **from repo-committed fixtures**: pre-seeded `ai_extraction_cache` rows + seeded docs/
  companies/settings (the suites already use prime-cache + seed patterns — commit the fixture data and make
  seeding part of the suite Config, `ci_mode:true`).
- Lanes that REQUIRE live externals (real Drive find-or-upload, live apitools KW/OCR, live Gemini) are
  **gated by `ci_mode`** and skip-with-note in CI; they stay in the local full-fat run (Phase 3) and the
  release evidence pack. Alternative (optional, later): repo secrets (submodule PAT + Google creds) enable
  a scheduled nightly full-fat CI run — decision deferred, not a release gate.
- CI seeds supabase directly (acceptable here — CI pins pipeline/state-machine behaviour; source-transit is
  proven in Phases 2–3).

**Gate 1c:** ci-verify green on the release branch including the new indox-e2e checks; scorecard shows
suite results; zero manual steps.

### Phase 2 — Prove all 5 syncs (short-term)  [~1 day]
For each of `drive-gdoc, drive-bs, gmail-doc, gmail-bs, gmail-link` (source of truth = `sync_registry`):
1. **First: establish gmail-sync truth.** The 4 legacy gmail scanners were live-deactivated 2026-06-25
   (OVERQUOTA recycle) "until the sync-refactor gmail processors replace them". Verify what actually scans
   gmail today on the local stack (Label Engine @10min + Scanner/ScanUnit on IMAP?). If gmail syncs are
   dead, build the MINIMUM to run them through Scanner/ScanUnit + IMAP processors — this is the one place
   sync work is in-scope, because the bar says all syncs work.
2. INJECT a small batch per sync (drive upload / gmail append+label) → watch LIST/CLAIM/ADVANCE → doc rows
   land → pipeline drives to COMPLETED → source item reaches `synced`.
3. Verify OVERQUOTA discipline on gmail (batched label writes), and that failures park at `failed`/error
   states visibly (GlitchTip + n8n), never silently.

**Gate 2:** every sync: inject → rest, source labels/folders correct, rows COMPLETED, zero manual touches.

### Phase 3 — The acceptance run: 100 docs, high load, to rest  [1–2 days incl. fixes]
The billing-bar run. Seed ~100 documents ACROSS types and sources **through the sources** (drive folders +
gmail IMAP append; respect the ≤40/type IMAP practical cap — split across syncs; direct-DB seeding is NOT
acceptable here since the bar says "all documents going through sync").

Pre-arm the known killers (all previously hit):
- **Memory**: 8GB host pressure collapses n8n under load → low-memory-mode profile or 12GB Docker + right-
  sized compose limits BEFORE the run; watch for OOM (n8n heap < cgroup).
- **Terminalizer false NEEDS_REVIEW**: bounded line-change poll (limit 8) can't drain BS-line load within
  the 15-min window → raise poll limit (30–50) and/or widen window for the run; assert ZERO spurious
  NEEDS_REVIEW afterward.
- **doc_step lock churn**: TTL 10min; every action must release on terminal Upsert; a stuck lock = a bug to
  find, never manual-unlock mid-run.
- **Docker→Google DNS EAI_AGAIN** on long sessions → restart Docker Desktop before the run.
- **Gemini billing 403** can kill live AI extraction → verify billing green before seeding.

Measure + assert (came-to-rest via `STATUS.at_rest` + table quiet):
- 100/100 reach COMPLETED (or a *correct* terminal state with a documented reason).
- Zero stuck IN_PROGRESS, zero spurious NEEDS_REVIEW, zero stuck locks, zero unhandled errors.
- Extraction quality: on the GT-known subset, `GT === AI === KW` selected values (no drift vs the pinned
  14/15 + whatever Phase 1 improved).
- Throughput/timing recorded (drain rate per sync, per-doc wall time, extractor concurrency ~bounded-5,
  apitools bounded-2) — the numbers go in the report.
- Per-doc trace sample (`scripts/indox-doc-trace.py`) — every action in expected order, one action per loop.

**Long-term soak:** after the run, leave schedules live ≥24h with trickle injections; assert no degradation
(memory creep, lock leaks, label drift, queue buildup).

**Gate 3:** the run meets the bar end-to-end with NO manual intervention; soak clean.

### Phase 3b — Clean minimal version: prune legacy + full tag organization  [~1 day]
Done AFTER the acceptance run proves the release set (pruning before proof risks cutting something live),
verified by re-running `bbox indox test all` + a sync smoke after every batch of removals.
1. **Inventory → classify** every workflow in the blueprint (~119): `release` (the v2 set + api layers +
   sync + suites) · `legacy-archive` (0.1.7 kept dormant as rollback ref, 0.1.4 dormant, pre-refactor
   backups) · `delete` (disposable test clutter, orphaned experiments, superseded duplicates — continue
   the ec20a67 prune).
2. **Canonical tag taxonomy** — every workflow carries exactly: one *layer* tag (`indox/main` ·
   `indox/router` · `indox/decide` · `api/data` · `api/drive` · `api/gmail` · `sync` · `extractor` ·
   `test/e2e` · `feature-validation` · `agent` · `archived`) + release tag (`sm-refactore-v2.1`) where
   applicable. No untagged workflows; tags declared in blueprint files so they survive push/pull.
3. Assert nothing active references a deleted/archived workflow (call-graph check); active-set count drops
   to the minimal release set; ci-verify workflow-count checks updated.

**Gate 3b:** blueprint = minimal tagged release set; all suites + syncs still green; zero untagged workflows.

### Phase 4 — Re-context + package the release  [~1–1.5 days]
Per `release.md` runbook, plus the full re-context pass:
1. **Re-context the entire deployment-hacohen**: refresh `architecture-map.md` to as-built; a per-file
   explanation of everything under `production/` (compose files, services, n8n blueprint groups, fixtures,
   scripts) — what it is, why it exists, what calls it; delete dead files/scripts found on the way
   (superseded by the CLI consolidation and the prune); de-drift every `ai/context/` doc against reality
   (release.md report §12 checks this — make it pass honestly).
2. Final `bbox n8n pull`; final commit on the release branch (ask first).
3. **`before-release-report.md`** (all 13 sections) + the acceptance-run evidence pack: scorecard, timings,
   extraction table, per-sync drain rates, soak notes, CI run link. This + the run IS the client-billable
   deliverable.
4. Secret hygiene pass (`git grep --cached` patterns clean; `.env` only), version bump, PR
   `deployment-hacohen → main` per runbook when told to.

**Gate 4:** report written, evidence attached, docs match reality, branch clean + pushable. Client
demo/billing ready.

### Phase 5 — Migration plan (document only, execute later)
Deliver `vps-migration-plan.md`: deploy release branch to VPS dormant → reseed env-managed creds → shadow-
diff v2 decide/action-log vs live 0.1.7 on real traffic (shadow_diff.py pattern) → flip (activate v2
Driver, deactivate 0.1.7 kept dormant) → rollback = reactivate 0.1.7 → post-swap watch (feature-validation
suite + STATUS.at_rest). Includes the VPS deltas: branch `insider`, container names `-bina-deployment`,
8GB profile settings from Phase 3 learnings.

## Risks & standing rules
- **Never commit without asking; secrets only in `.env`; publish via n8n (bbox push), never raw import.**
- Biggest schedule risk = Phase 3 stability on 8GB — budget for one fix-and-rerun cycle.
- Biggest silent risk = blueprint↔live drift — Phase 0 kills it first.
- 0.1.4 stays dormant-but-archived (was ACTION_LINES); 0.1.7 stays the VPS prod until the later swap.

## Deferred (explicit next-release backlog)
Physical router fork (invoice/shipment/order) + per-type suites · sync source primitive + pure processors +
registry-driven RESET/STATUS/INJECT · sheets-node unification (−57 nodes) · redis settings cache · per-type
config-driven KW extractors + naming-as-pipeline-step (company-shortdocid, BS company-mm-yy incl. Drive
rename) · BS-line batch processing (biggest throughput lever) · doc_step lock throughput rework.
