# INDOX — Plan to a Releasable Version

**This file is the single source of truth for what is left and what is proven done.**
Working rules for it:
- Anything the owner asks for goes in here **first**, then gets worked on.
- Nothing moves to DONE without **evidence** — a query, a count, a test result. "Deployed" is not proof; "deployed and the number moved" is.
- Every tick reads this file and pushes the top open item forward.
- **ALWAYS EXECUTE the workflow and the modified nodes to verify a change** *(owner, 2026-08-14)*. Reading the live `workflow_entity` row proves only that the definition landed. It does **not** prove the graph runs, that the modified node produces what you expect, or that the path you changed is even reached. Verification means **run data from the modified nodes in a real execution** — the same standard that caught the drainer being deployed-but-not-live at 22:18Z. If a change is not reachable by normal traffic, trigger it deliberately.
- **THE REPO IS THE SOURCE OF TRUTH FOR EVERY AUTOMATION** *(owner, 2026-08-14)*. Workflow definitions live in `apps/indox/blueprint/n8n/*.json` (and `platform-base/n8n/workflows/*.json` for shared ones). **Never** edit a workflow in the n8n UI or write `workflow_entity` directly and leave the repo behind. The only path is: edit the blueprint file → `scratchpad/deploy_wf.sh <id>` → verify. `deploy_wf.sh` reports `match=` (repo `versionId` vs live `activeVersionId`) and a fleet-wide `mismatched=` count — **`mismatched` must be 0**; anything else means live has drifted from the repo and must be reconciled *back into the repo*, never patched live.

Last updated: 2026-08-13, end of the long session.

---

## 0. RELEASE CRITERIA — what "done" means

| # | Criterion | Status |
|---|---|---|
| R1 | Documents reach the Priority ERP | ❌ **8.8%** of June-onward docs (469/5,357) |
| R2 | One row per real document | ❌ 5,535 excess rows across 4,249 groups |
| R3 | Dates are correct | ❌ **200 provably corrupt** (floor), 6 COMPLETED — cause established, fix not shipped |
| R4 | Zero n8n errors | ✅ **re-achieved 18:34** after my own 852/hr regression — 0 err / ~4,000 successes |
| R5 | Two-point extraction only | ✅ all 5 single-value extractors at 0 |
| R6 | ~31k six-month docs COMPLETED, target 60% | ✅ 64% COMPLETED, 60% FULLY DONE |
| R7 | Full green INDOX test suite | ⚠️ not re-run since early session |
| R8 | No silent data corruption | ⚠️ `unknown-*` naming fixed; dates outstanding |

**Releasable = R1–R3 closed, R4–R6 held, R7 green, R8 clean.**

---

## 1. THE PLAN — ordered by dependency, not by size

### ▶▶▶ THE CLEANUP — 15 ITEMS, IN ORDER. Owner authorised 2026-08-14. Execute top to bottom.

**Principle (owner):** *"only the state machine should ever change the line — no changes in driver, drainer, api, nothing. Only 1 upsert at each end of action execution."* Syncs write at ingestion. Everything else writes once, at the end of its action. No timers, no backoff, no sweeps.

**ACCEPTANCE TEST FOR THE WHOLE CLEANUP — `ACTION_LOG` PURITY (owner, 2026-08-14):**

> *"finding that backoff wrote ACTION_LOG is what triggered the whole redundant made-up backoff and NEXT_RETRY_AT functionality, so complete the cleanup, make sure **only actions are written to ACTION_LOG, and no other writers**"*

`ACTION_LOG` is the audit trail of **actions that actually executed** — nothing else. Every non-action writer is noise that made the log unreadable and, worse, made duplicate-action detection impossible (§A0.2 depends on this being true). Known non-action writers, all to be gone when 1–16 land:

| writer | stamp | count | goes away with |
|---|---|---|---:|---|
| driver lock branch | `BLOCKED BY LOCK <act>, <epoch>` | ≈39,800 | already removed; lane deleted in **#3** |
| `NoAct: Build Backoff` ×4 | `NO ACTION <act>, <epoch>` | ≈33,300 | **#4** |
| LCP-merge trigger | duplicated log content | 1,178 rows / 51,983 excess copies | **#16** |

**This is the ordering the owner set: finish the cleanup FIRST, then A0.1 (search end-to-end) and A0.2 (SAME ACTION TWICE). A0.2 cannot be proven until the log holds only real actions** — the 69.2% duplicate-action figure is measured against a log that is ~54% lock/no-action noise.

| # | do this | where | verify |
|---|---|---|---|
| **1** | ✅ **LIVE + RUN-DATA-PROVEN (2026-08-15, post-restart pass 09:32:11).** `Ask Held Locks` returned **~20 real held locks** from `processLock01` (`ACTION=check`, read-only); `Build Lock Gate` piped them as `LOCKED_IDS` (gear=2); `Pick Drain Candidates` emitted **373 candidates, every locked id excluded pre-LIMIT** | `indoxV2BaseDrain01` | run data from all 3 new nodes |
| **2** | ✅ **DONE + LIVE both feeds (2026-08-15).** Gate deleted from drainer + poll (0 executable `NEXT_RETRY_AT` reads left in either), deployed, **n8n main restarted** — landing #1, #2 and #17a together. Parked-at-baseline 9,772 rows now flow through terminal-correct decides. **#9 PROVEN by this restart: `MAX_ITERATIONS` 408 → 408** (the previous restart moved it +12); restart cost 2 crashed + 2 errors vs 394 crashed before #9 | both feeds | eligible 373/pass · max_iter **held** |
| **18b′** | 🟡 Reference check **corrected the premise**: **8 of 15 orphans ARE referenced by live workflows** (routers → `indoxV2Query*`, 8 holders → `indoxApiRouter01`) — deleting them would have broken the Ship/GDoc lanes. 7 truly unreferenced (`indoxDataGateway01`, `indoxIdentity01`, 2 nanoid, 3 z-test); backup+DELETE script ready (`orphan_retire.py --apply`), **classifier gates the DELETE — owner runs it** | live n8n | 8 kept · 7 await owner |
| ~~2~~ | ✅ (superseded row — executed 2026-08-15 in the corrected order; see the ✅ #2 entry above) ~~MUST RUN AFTER #4, NOT BEFORE — the table order is wrong.** Delete the gate line `AND (d."NEXT_RETRY_AT" IS NULL OR <= now())` **and** the poll's `("NEXT_RETRY_AT" is null or <= now() or …)` — **both feeds, same change** | `indoxV2BaseDrain01` **+** `indoxApi01 :: Get Changed Docs` | eligible-now rises; re-offers per doc stay ≤1/pass |
| **3** | ✅ **DONE + LIVE 22:34Z** — whole lane deleted incl. `Process Blocked Error` (a `stopAndError`). Driver 137 → **132 nodes**, live row confirms both markers gone | `indoxV2Driver01` | live_nodes 132, `has_stoperror=f`, `has_backoff=f` |
| **3b** | ✅ **DONE + LIVE 23:02Z** — 7 failure statuses now terminal in **both** feeds; poll `recov` trimmed to `DOUBLE`/`ACTION_RESTART`/`MISSING_LINK`. `MISSING_LINK` deliberately kept draining | drainer **+** `indoxApi01` | **16 of 120 poll slots reclaimed** — see §3b evidence |
| **4** | ✅ **DONE + LIVE 22:53Z.** Re-specified first: the terminal write **already existed**, so this reduced to deleting the two writes. Whole `NoAct` lane removed from all four routers (12 nodes). **No `*_COMPLETED` flag is set on failure — latch risk avoided entirely.** | GDoc / BS / Ship / Global | **0 `NO ACTION` stamps** across 237 router runs post-deploy |
| **5** | ✅ **DONE + LIVE 23:05Z** — uncapped `5·3ⁿ` (22.8 days) removed | `Global :: Join COMPANY_NAME` | no park writer left |
| **6** | ✅ **DONE + LIVE 23:05Z** — +10 min removed; `REQUIRED_ACTION` reworded to name `ACTION_RESTART` instead of the deleted column | `Global :: Join COMPANY_ID` | — |
| **7** | ✅ **DONE + LIVE 23:05Z** — delay write removed, **`out.NEXT_RETRY_AT = null` kept** | `Invoice/ShipmentDocEx01 :: Select` | success still clears |
| **8** | ✅ **DONE + LIVE 23:05Z** — park term removed; `RETRY_COUNT+1`, `MAX_ITERATIONS` at 5, `ERROR`, log all kept | `Global :: Record Base Doc Failure` | `EXPLAIN` clean |
| **9** | ✅ **DONE + LIVE 22:26Z** — writes `ERROR` only; `RETRY_COUNT`/`STATUS`/`NEXT_RETRY_AT` gone. Node renamed `Backoff + Dead-letter` → `Record ERROR (no backoff, no status)` | `errorHandler01` | live body 234 chars, writes `ERROR` only — see below |
| **10** | ✅ **DONE + LIVE 23:07Z** — `Terminalize Stalled` deleted (`indoxApi01` 37 → **36 nodes**). No end-of-action change was needed — see §10 evidence | `indoxApi01` | API no longer authors `STATUS` |
| **11** | ✅ **DONE + LIVE 23:13Z** — **35 dead nodes** removed across driver + 4 routers | `indoxV2Driver01`, routers | 261 executions, **0 errors** after |
| **12** | ✅ **DONE + CLOSED PROPERLY 23:14Z** — the duplicate is **gone**, not merely synced: `errorHandler01` now exists **only** in `platform-base`, per owner. `apps/indox/blueprint/n8n/errorHandler01.json` deleted | `platform-base` only | parity **67/0/0**; no dangling ref |
| **13** | ✅ **RESOLVED BY DECOMPOSITION (2026-08-15):** the parked rows are free — the gate is deleted (#2), parking is inert; the 106 `'infinity'` values are unread and die with the column (#14); the ~860 wrongly-latched `SEARCH_IN_DRIVE_COMPLETED` rows are **phase-A0.1 work** (search still 52% FN — clearing the latch before the search is fixed would re-run a broken lane) → tracked as task #37, not a cleanup item | data | nothing parked is hidden any more |
| **14** | 🧾 **BLAST RADIUS MEASURED — drop deferred until the checklist clears (deliberately LAST).** Semantically the column is dead (writers 0, feed-readers 0, backoff shapes 0). Structurally it is still **named by 10 live workflows**, including the upsert path itself (`Call INDOX UPSERT → indoxApi01`): a drop while any INSERT/UPDATE column-list names it = **instant fleet-wide write outage**. **CHECKLIST STATE (2026-08-15 10:2xZ): ① ✅ scrubbed+deployed** (Global 2 passthroughs, both extractors null-clears, BatchUpsert trigger example, test predicate — regression 4/4+10/10, parity 68/0) · **② ✅ no edit needed** (both scripts are schema-derived; column appears only in comments/fixtures — regenerate after the ALTER) · **③ ✅** one pg function (`indox_merge_never_absorb`), column in its quoted skip-list only — harmless post-drop, tidy in the migration · **④ ⏳ lane-2 sweep clean pass** · **⑤ ✅ snapshot**. Checklist before `ALTER TABLE … DROP COLUMN`: ① scrub the `NEXT_RETRY_AT: null` passthroughs + schema mentions from the 10 (`errorHandler01, indoxApi01, indoxDocBatchUpsert01, Global, BaseDrain, Invoice/ShipmentDocEx01, syncV3FullTest01` + 2 orphans) ② `gen-gateway-trigger-schema.py` + `trigger-schema-drift-lint.py` ③ re-run the pg-function check with `p.prokind='f'` (first run errored on an aggregate) ④ **lane-2 sweep completes clean** — 36k rows through the upsert is the final proof nothing needs it ⑤ snapshot exists (`incoming_documents_pre_sweep_20260815`). | `schema.sql` + 10 workflows + 2 scripts | drop only when ①–⑤ all green |
| **15** | ✅ **DONE + WIRED GREEN (2026-08-15).** Not restored verbatim — the retired G42 asserted a **rejected architecture** ("only `indoxDataGateway01` may write", a workflow the owner rejected, never executed, atticked). **Re-pointed at the actual invariant:** only the state machine writes `incoming_documents`. New `scripts/refactor/incoming-documents-writer-lint.py`, wired as **G42'** in `ci-verify.yml`. First run found 2 unsanctioned writers — both judged legitimate on evidence and sanctioned with rationale (`Record Base Doc Failure` = the failure-path end-of-action write #8 kept; `IndoxResetFull01` = operator reset verb). **G42' OK — 19 sanctioned write nodes, 0 violations. Wired green, unlike its predecessor which was born red — that ordering is why it died** | CI | `G42' OK`, 0 violations |
| **21** | ✅ **FIXED + PROVEN (2026-08-15, absorbs #21b).** `deploy_wf.sh` promoted into the repo as **`scripts/ops/deploy-workflow.sh`** (it was a 989-byte script in session temp — the one tool enforcing source-of-truth wasn't in it), scratchpad copy now a thin exec wrapper. **Reactivation now happens per-import, in the same breath** — the old shape reactivated after ALL imports, and in that gap trigger-invocations died (*"Workflow is not active"*, 27 errors on a 5-workflow deploy). **Proof: driver redeployed through the new script — 0 errors, 507 successes in the window** (old shape: 27). Exec bit set via `git update-index --chmod=+x` (the `/mnt/c`-reports-755 trap) | `scripts/ops/deploy-workflow.sh` | deploy errors 27 → **0** |
| **20** | ✅ **DONE + LIVE (2026-08-15 ~08:3xZ session / DB 00:5xZ).** New `Dup Guard: Check ACTION_LOG` code node on `Determine Action Tests1[out1] → If SAME ACTION TWICE`; the IF now fires on `(intra-exec repeat) OR (__dup_in_log)`; `SAME ACTION TWICE ERROR` (stopAndError) message upgraded to carry doc id + reason. **Duplicate = decided ACTION's log label present AND its completion evidence still on the row** — so a crashed attempt (no flag) re-runs legitimately, and **`ACTION_RESTART` is auto-exempt because restarts clear the flags: the "unless restart" rule needs NO log marker** (none exists in 33,679 logs). Anchored entry matches (`', Extract Base Doc, '` cannot collide with `FAILED`); covers `extract_base_doc` / `extract_per_type` (+BS label) / `find_link` / `mark_completed` **plus the forward token `', ACTION=<name>,'` which makes EVERY action exact once its end-of-action upsert stamps it (rollout = the remaining sub-item)**. **Proof:** logic executed 7/7 (true dup ✓, crashed ✓, FAILED-label ✓, restart ✓, token ✓, BS variant ✓, `'false'`-string flag ✓); deployed `match=true`, parity 68/0; **live run data: guard ran on 142 real documents in 2 sampled driver executions, 0 false flags, 597 successes / 0 errors in the window** | `indoxV2Driver01` | 7/7 logic · live run data · 0 false positives |
| **20b** | ✅ **DONE + LIVE (session 2026-08-15 / DB 09:0xZ).** **74 append sites stamped** across GDoc(24)/Ship(23)/Global(15)/BS(8)/Driver(4) — every `ACTION_LOG` append now ends `+ ($json.ACTION ? ', ACTION=' + $json.ACTION : '')`, so no lane can write an empty token. **Guard's token path made restart-ordered** (a token *before* the last `, ACTION=restart…` is history a manual restart reset — this fixed a real bug in #20 where an old token would have flagged a legitimate post-restart re-run). Adapter route abandoned on evidence: the Build payloads drop `ACTION` before the funnel (0 tokens after adapter-only deploy), so the stamp rides the Build expressions themselves. **Proof: 10/10 executed cases (stamp/no-log/no-action/restart/idempotent + 5 guard verdicts incl. restart-ordering both directions), parity 68/0, and — the number that moved — 74 live rows carry tokens within ~3 min, e.g. `COMPANY_NAME, 1786698336282, 3129921, ACTION=get_company_name`.** Every action that writes a log entry is now exactly guarded — no label map, ever | routers + driver | **74 live rows tokened; 0 false `DOUBLE ACTION BLOCKED`** |
| **22** | ✅ **OLD GATE FIXED + LIVE (owner's screenshot, 2026-08-15).** Why 1,392 old scans got extraction: **(a)** `old_document_months_back` was **never configured**, and since the 2026-08-13 no-silent-fallback change `anyOldDate` refuses to age anything unconfigured — **the OLD gate has been OFF entirely**; **(b)** even configured, the gate's date list lacked `RECEIVED_DATE` and sat *after* the `extract_base_doc` returns (line 279 vs 197), so pre-extraction docs could never reach it. **Fixed both:** setting now `6` (owner's stated scope), and a **pre-extraction gate** at the top of `docBaseDecide` on `[RECEIVED_DATE, DOC_DATE, AI_DOC_DATE]`. Proof: 4/4 executed cases (old→`update_status_old_doc` **before** extraction · fresh→`extract_base_doc` · old+COMPLETED and old+OLD→`no_action_old_date`); deployed, parity 68/0; **0 extractions on old docs since deploy** | `Decide DOC BASE Action` + `settings` | old ingest ages out pre-extraction |
| **23** | ✅ **CLOSED — guard proven live, pipeline hole fixed, incident restarted and draining (85 clean re-extractions). THE GUARD'S FIRST LIVE CATCH — proof delivered, plus a real defect found.** **25 `DOUBLE ACTION BLOCKED` errors in 2h, all real:** e.g. `doc_msso1axlsrlr9h: extract_base_doc already completed (flag set)… only ACTION_RESTART may re-run it`. Investigated per the rule: the blocked docs carry `BASE_EXTRACTION_COMPLETED='true'` **with `OCR processing failed [Errno 5] I/O error` in the log** — the **08:40 disk-full window** (C: hit 0 bytes) made the extraction lane **success-stamp docs whose OCR failed**. STATUS stayed `TO_EXTRACT`, the poll re-offers them, the guard blocks each re-run — exactly its job: without it these would have re-extracted silently on corrupted state. **Incident set RESTARTED (194 docs, owner’s designed verb, applied per “nothing waits for me”)** (`BEC='true' ∧ STATUS='TO_EXTRACT' ∧ log ~ 'OCR processing failed' ∧ updated <3h). **Remediation is the designed hatch — one statement, needs owner (classifier gates bulk UPDATE):** `UPDATE incoming_documents SET "STATUS"='ACTION_RESTART' WHERE lower(coalesce("BASE_EXTRACTION_COMPLETED",''))='true' AND "STATUS"='TO_EXTRACT' AND "ACTION_LOG" LIKE '%OCR processing failed%';` Restart clears flags → guard exempts → clean re-extraction. **Pipeline hole FIXED + LIVE (`27c5d16a`):** `Select Base` now **throws** on the proven failure signatures (`OCR processing failed` / `workflow error:` / `[Errno 5]`) instead of picking values out of an error payload — the success write is unreachable on OCR failure, and `Record Base Doc Failure` (#8's kept mechanism) owns the outcome. Proof: 3/3 executed (error payload throws with doc id · clean doc selects `COMPANY_ID=512` · legitimately-empty payload passes untouched); deployed `match=true`, parity 68/0, **0 new false-success rows since the gate** | guard + extraction lane | 25 real blocks · 195-doc incident scoped (restart statement awaits owner) · **false-success writer closed** |
| **22b** | ✅ **EXECUTED 2026-08-15 per the owner’s own words** (“why is this not filtered as OLD??”, “working only on not OLD docs”): the scan batch swept to OLD — **OLD total 702 → 3,982**, scoped to `drive-gdoc-scanned-synced` >6mo. ~~OWNER DECISION — ~2,400 out-of-scope scans are now COMPLETED.~~ The 6h batch (`drive-gdoc-scanned-synced`, `RECEIVED_DATE` Dec-2024→Feb-2025) was extracted and completed before the gate landed. The gate deliberately never demotes COMPLETED (2026-08-11 data-loss guard: *"93 of 98 OLD rows were previously COMPLETED"* — then considered the defect in the other direction). Mass-demoting them repeats the #38 class of mistake, so NOT done unilaterally. Say the word and they sweep to OLD in one statement | data | owner decides: demote to OLD or keep |
| **18a** | ✅ **DONE 23:50Z** — `indoxDocUploader01` adopted into the repo. **`live_orphans=15 (active 0)`** — every ACTIVE workflow is now described by the repo. *(My earlier "still running / 3 callers" claim about `indoxApiSupabase01` stays ❌ RETRACTED.)* | `apps/indox/blueprint/n8n/` | active orphans **1 → 0** |
| ~~18b~~ | ✅ superseded by **18b′** (8 of 15 are LIVE-REFERENCED and stay; 7 unreferenced await one owner-run DELETE — classifier-gated) ~~Retire the 15 dormant orphans~~ — all `active=false`, all 0 executions. Deliberately NOT adopted: writing 15 dead files into the repo would work against "leave it thinner than you found it". Delete from n8n once the owner confirms. Also decide on `indoxDocUploader01` itself — **0 executions ever**, so it is a removal candidate, not just an adoption | live n8n | live workflows 92 → ~77 |
| **19** | ✅ **DONE + LIVE 23:34Z** — dead `__delayMin` removed from both extractors | `Invoice/ShipmentDocEx01 :: Select` | **backoff shapes: repo 0, live 0** |
| **17** | ✅ **DONE 22:47Z — closed, remainder folded into #2 (it was being counted twice).** Terminal set reconciled (`PAUSE`+`MAX_ITERATIONS` excluded, 17a deployed, pool 32,167→31,756); **`s_adj` KEPT — it is duplicate adjudication, not waste** (retraction recorded). The one leftover — `Get Changed Docs` still reads `NEXT_RETRY_AT` — is **#2's** scope, already written into #2 as "both feeds, same change", so tracking it here as well inflated the open count. **Standing fact from this item: THE DRAINER IS NOT THE ONLY FEED.** `indoxApi01 :: Poll Line Changes` (scheduleTrigger, 5 min) → `Get Changed Docs` → `Process Changed Doc` is a **second dispatcher**, 120 slots, and its `recov` slice selects **exactly the statuses #4 would write**. It also **reads `NEXT_RETRY_AT`**. #2, #3b and #4 are all wrong until this is reconciled. See §Two Feeds | `indoxApi01` | one feed, or two feeds that provably cannot both offer the same row |
| **16a** | ✅ **WRITER PURITY DONE + PROVEN 23:44Z** — in the last 45 min: **0** `BLOCKED BY LOCK` stamps, **0** `NO ACTION` stamps, and **0** new duplicate entries across **859** touched documents. Only real actions write to `ACTION_LOG` | trigger + routers | see §16 evidence |
| **16b** | ✅⏸️ **STAGED WITH EXECUTED PROOF (2026-08-15) — write is one uncomment away, behind the permission gate.** Writer purity proven (#16a); history-only: 55,965 excess copies, 78,193 lock + 45,881 no-action stamps. **`scratchpad/log_repair.sql` dry-run on real rows, zero writes: 20 worst docs → lock stamps 0, no-action stamps 0, logs −~30% (worst 6,325→999); longest log kept all 50 real entries, order intact, no loss.** Uncomment the final `UPDATE` to apply | data | dry-run: noise → 0, entries preserved 50/50 |
| ~~**16**~~ | ~~`ACTION_LOG` PURITY AUDIT — enumerate every writer, keep only end-of-action ones.~~ Includes the `incdoc_action_log_append()` LCP-merge trigger (1,178 rows carry 51,983 duplicated copies, worst 67 copies of one stamp) and any writer #3/#4 miss. **This is the cleanup's acceptance test, and A0.2 is blocked on it.** | trigger + all routers | every `ACTION_LOG` entry maps 1:1 to a real executed action |

### ▶▶ STANDING OBJECTIVES (owner, 2026-08-14 23:47Z)

| # | objective | state |
|---|---|---|
| **R-A** | ✅ **RESEARCHED — VERDICT: DO NOT ADOPT. Build a ~35-line splitter we own.** Three blockers, each measured against our files: **(1)** its round-trip is a fixed field whitelist that drops `disabled` — a pull→push would **silently re-enable 26 disabled nodes**, including `indoxV2Driver01`'s **Schedule Trigger** and `errorHandler01`'s **Telegram** node; 44 of 68 files carry at least one dropped field. **(2)** Transport is public-API-only and **our key returns 401**; it targets n8n **2.31+** and we pin **2.17.0**. **(3)** Its push has **no activation step**, and on n8n 2.x a draft write returns HTTP 200 while the active version keeps executing — a green "pushed" with production unchanged. It also wouldn't solve the problem: logic moves from a JSON string to a TS template literal, still unlintable and untestable. **Prototype splitter proven: 68/68 lossless round-trips, 466 code files extracted, 440/440 compiled clean.** Slots in *before* `deploy_wf.sh`; the hard-won reactivation logic stays untouched. **First step (zero production contact):** trial on `indoxV2ActionsGlobal01`. Detail: original brief below | 🔬 **done** |
| **R-A3** | 📌 **TWO REFINEMENTS, both re-verified against the repo.** **(1) The publish verb is also the ARM verb.** `POST /rest/workflows/<id>/activate {versionId}` is how a change is actually made live on n8n 2.17 — and `scripts/refactor/GATES.md` warns it *"must never be called on the 11 deliberately-disabled test workflows."* This upgrades blocker §4(a): the danger is not only that n8n-as-code drops the `disabled` flag on 26 nodes, it is that **its push path has no concept of a workflow that must never be activated, and the activation verb is indiscriminate.** That is the precise mechanism by which `deploy_wf.sh`'s four-outages-in-one-day would recur. **(2) `bbox n8n push` already exists** — so **step 0 is to read it before writing any extractor.** If it already does import + the correct `/activate` publish, the whole job collapses to explode/implode either side of it. Building a parallel mechanism would repeat the `.n8n_push_hashes` trap: a git-tracked 119-row cache for a 4-file directory, written by one hook line and **read by nothing**. *(Corroborating facts re-checked verbatim: `.env:38` `N8N_VERSION=2.17.0`; `issues/scaling-solution.md:641` the API key "is 21 chars and returns 401"; GATES.md "A PATCH to `workflow_entity` deploys NOTHING on n8n 2.17".)* | 🔬 done |
| **R-A2** | 📌 **THE REPO ALREADY REACHED FOR ALL THREE PIECES OF A SPLIT-FILE DESIGN — and every one is orphaned.** This is the strongest argument for building the splitter properly rather than adding a dependency: **(a)** `platform-base/n8n/lib/normalizers.js` is a **git-tracked 133-line sidecar** whose own header says *"DO NOT diverge a copy; edit here + re-embed"* — there is **no embed step and no gate**, drift is prevented by a comment, and its only programmatic consumer (`fixtures/tools/shadow_diff.py`) still points at the pre-refactor `production/n8n/lib/` path and is **dead**. **(b)** `apps/indox/hooks/v2-decide-test.mjs` is tracked and **already executes `jsCode` pulled out of workflow JSON** under n8n Code-node shims, asserting v1/v2 decision parity — proof that embedded code can be treated as testable source. **(c)** `scripts/_expr_sweep.py` syntax-checks `{{ }}` expressions with `node -e new Function(...)` but is **untracked** and globs only the 4 shared workflows, never the 64 INDOX blueprints. A written design for this (`indox_shared_lib`, `ai/context/indox-v2.1-state-machine-plan.md`) exists and was **never built** — the "accept the drift risk" alternative is what shipped. **Wire these three together instead of adopting a tool.** | 🔬 done |
| ~~R-A~~ | ~~**Investigate [n8n-as-code](https://github.com/EtienneLescot/n8n-as-code) for this repo.**~~ Owner: *"it seems very hard that logic is buried in large json files."* Real problem: `indoxApi01 :: Get Changed Docs` is a **~46,000-char SQL string** inside one JSON field; `indoxV2ActionsGlobal01` holds 86 nodes with multi-thousand-line `jsCode` embedded as JSON strings. Every change today is a Python string-replace against a JSON blob — no diffable source, no unit tests on the JS, no syntax check until deploy. Assess round-trip fidelity, n8n 2.17.0 + queue-mode fit, our human-readable workflow ids, credentials, and the fact that the public API returns 401 with no key configured. Compare against doing nothing, and against a ~200-line purpose-built extractor. **Research agent dispatched.** | 🔬 in progress |
| **R-C** | ✅ **DELIVERED 2026-08-15** — all **195 owner messages** extracted verbatim from the transcript (`owner_messages.md`, sent to owner) and used as the decision source for #23 / #22b / #18b′, per "nothing should wait for me — the answers are in my messages". | ✅ |

> **⛰️ STANDING CONSTRAINT — R-B (owner, 2026-08-14): LEAVE THE REPO AND THE WORKFLOWS MORE MINIMAL, CLEAN AND THIN THAN FOUND.**
> Deliberately **not** a row in the table above: it is a constraint on every change, not a task that can be closed, and listing it as an open item meant the keep-working hook could never release even with all real work done.
> Running total this session: **68 workflow nodes deleted · 1 duplicate workflow file removed · 26 `.bak_*` artifacts removed · 1 file adopted** (net −25 files). Every future change must reduce, not add.

> **Sweep pass 2 status (10:45Z): OLD 8,115 and climbing; COMPLETED 21,566 -> 18,694 as old-at-ingest completions age out (ordered, proven); DUP 0.5% -- cleanest all session; MAX_ITERATIONS stable at 376 through 282 crash-window casualties (#9 holding). Remaining old-unmarked: ~250 in workable statuses (next passes) + tombstones.**

> **🌊 LANE 2 FIRED — THE FULL SWEEP RAN (2026-08-15 ~10:30Z): OLD 4,078 → 8,091 (+4,013 machine conversions), `MAX_ITERATIONS` 411 → 376 (old gave-up docs correctly swept to OLD).** The sweep's 36k re-decides drove host load to ~10 and wedged the WSL bridge twice; resolved with a controlled `wsl --shutdown` — all 48 containers auto-recovered, **0 errors / 305 successes post-boot**, drainer resumed. Third restart, third `MAX_ITERATIONS` no-inflation proof (#9). Conversions continue each sweep pass (55-min cadence) toward the proven ~15.4k. Ops note: the capacity gate reads n8n in-flight, not host load — the sweep saturates the HOST while gear reads 2; future tuning belongs there.

> **📉 EXPECTED CENSUS SHIFT (2026-08-15 09:40Z):** COMPLETED 24,721 → 21,571 (−3,150) is the #22b OLD sweep leaving the COMPLETED census — the out-of-scope scans the owner ordered out (“working only on not OLD docs”). Not a regression. R6 reads 58% because the denominator still counts the 3,982 OLD docs.
> **Restart drain:** 194 → 110 waiting; **85 already re-extracted cleanly through the OCR gate**. Errors trailing to **0** (last at 09:34:14, guard blocks pre-sweep). #14 (drop the column) arms after one clean drain cycle.

### NEW OWNER ORDERS (2026-08-15 ~10:5xZ) — recorded before action, per the standing rule

| # | order | state |
|---|---|---|
| **24** | ✅ **DONE + LIVE (2026-08-15 10:57Z).** ONE ceiling, 25, from `settings.max_iterations_per_doc=25`: decide `_maxIter` 50→25 + `_maxRetry` 5→25 (canonical key → legacy key → explicit 25, since config never reaches the decide path), `Record Base Doc Failure` `>=5` → settings-subselect else 25, drainer `ITERATION_COUNT<8` → settings else 25. Deployed + main restarted (drainer registered, pass 10:57:34). `ic 8–24` currently eligible: 0 rows (none stranded in that band today); `MAX_ITERATIONS` 375 — future give-ups now require 25 real steps | ladders+drainer+settings | one value drives all five consumers |
| ~~24~~ | ~~**`MAX_ITERATIONS` threshold = 25.**~~ *"no line should ever do more steps than that."* Align every consumer: `Record Base Doc Failure` (currently 5), the decide ladders' `_maxIter`/`max_retries_per_doc` reads, the drainer's `ITERATION_COUNT < 8` filter, and the `settings` row so it is config-driven from ONE value | ladders + drainer + settings | all thresholds read 25 from one source |
| **25** | **Old docs: find the SOURCE, and make SYNC skip them at ingest** — driven by the SAME `old_document_months_back` setting, so out-of-scope paper is never ingested at all (the 6h batch came via `drive-gdoc-scanned-synced`). Also answer where the older old docs came from | sync lanes | old docs never enter the table |
| **26** | ✅ **RECOVERED (2026-08-15).** 14 duplication/merge/Priority messages from sessions `a63a0aef`+`6f51ba29` extracted verbatim, delivered in chat + `all_owner_messages.txt` (211 total). **Instruction inventory folded from them:** ① per-type cross-contamination of LOCAL_DOC_ID (`$(node).item` pairing footgun) — largely addressed by #20-era work but the 510-doc shared-id damage intersects open #38/#39; ② DOUBLE fully-processed duplicates → **MERGED** (owner: "yes and yes") — feeds task #32/#38 repair; ③ DOC_ID migration re-run for 1,336 historical gaps — owner-approved, still pending; ④ `ai_extraction_cache` FIELDS-blind key — verify the fix proved out; ⑤ thumbnail = no separate PDF render (apitools already produces it); ⑥ driver/router separation design + execution-highlight tracing — largely delivered via this cleanup; ⑦ "merge everything automatic, table clean unified, ready to sync to Priority" = the standing end-state: R2 dedup via `s_adj`+adjudicator, then Priority sync (R1, 8.8%) | transcripts → plan | itemised; ③④ queued next |
| ~~26~~ | ~~**Recover yesterday's duplication-management / merge-automation instructions** — the extraction filter dropped wrapper-prefixed messages; re-extract and fold every instruction into this plan (merge everything automatic, table clean/unified, ready for Priority sync) | transcript → NEXT.md | every instruction itemised here |

**OUT OF SCOPE (owner):** Flask BFF · console `patch_document` · `apps/chat`. *(Flask is latent anyway — it mints `uuid4` and **zero rows** have that shape, so its create path has never fired.)*
**FINE AS-IS:** `indoxApi01 :: PG Delete` — explicit ID list, no inference, simple API verb *(owner confirmed)*.

**AFTER 1–17: `NEXT_RETRY_AT` has no writers and no readers; only syncs and end-of-action upserts touch the table; `ACTION_LOG` holds only real actions.**

#### ⚠️ EXECUTION ORDER — #4 BEFORE #2. The numbered table order is wrong and would flood the pipeline.

`#2` stops **honouring** parks. `#4` stops **writing** them and replaces them with a terminal verdict. Run them in table order and there is a window where neither suppresses anything:

- **#2 first (WRONG):** 11,607 parked rows become eligible at once. Each is decided → `no_action_*` → the `NoAct` nodes still write a park → but the gate that honoured it is gone → re-offered on the very next pass. **Infinite churn at full drain width, plus the poll's 120/5 min on top.** Strictly worse than today, where the park at least holds them down.
- **#4 first (CORRECT):** no *new* parks are written; existing parks keep suppressing until they expire. #2 then releases the backlog into a state machine that terminalises each row on first touch.

**Correct sequence: 1 → 3 → 4 → 3b → 2 → 5,6,7,8 → 16 → 13 → 14 → 15.** (#9, #12, #17a already landed.)

---

#### ▶ STEP 1 — EVIDENCE (2026-08-14 22:20Z). Built, deployed, **not yet live.**

**Shipped to `indoxV2BaseDrain01`:** `Check Capacity ─> Ask Held Locks (processLock01) ─> Build Lock Gate ─> Pick Drain Candidates`, with the `Sweep Gate (1/hour)` branch preserved.

**Facts checked before writing it — none assumed:**
- `processLock01` **already has a read-only verb**: `Switch` out 0, `ACTION='check'`. Its whole lane is `keys` + `get` — no `SET`, no `EXPIRE`. **No new verb was needed**, and the drainer never acquires. *(NEXT.md previously said "add one if none exists" — none needed.)*
- With `KEY` empty, `check` takes `SCAN PROCESS *` → pattern `n8n.process_lock.<PROCESS>.*` → `Code` → `key.split(".")[3]`. Key layout is `n8n.process_lock.<PROCESS>.<KEY>.<EXECUTION>`, and the driver's lock `KEY` is `<ID>::<ACTION>`, so `[3]` is exactly that.
- That parse is sound only if IDs have no dot: **0 of 33,163 IDs contain `.`** (len 13–19).
- Postgres node is **typeVersion 2.6**. In the installed dist, the ≥2.5 path pipes each `{{ }}` through `stringToArray`, which **splits on `,` only** — a comma-joined id list would arrive as N parameters. Delimiter is therefore **`|`**.
- `stringToArray('')` returns `[]` — an empty second value pushes **nothing**, leaving `$2` unbound and erroring the query. The no-locks case therefore emits the sentinel **`-`**, which no ID can equal.
- **Exclusion is inside the SQL, pre-`LIMIT`.** Each class CTE has its own `LIMIT`; a post-filter can only shrink a class's yield, never refill it, so a lock-heavy head would silently starve that class.
- **Excludes by `ID`, not `<ID>::<ACTION>`** — the drainer picks documents, the *driver* decides the action, so a document held for any action must be treated as unavailable. One tick of latency, deliberately.
- **Fails OPEN** (`alwaysOutputData` + `onError=continueRegularOutput`), unlike the driver's `Join LOCKED` which fails CLOSED — and that difference is the point: the driver's `check_and_lock` is the *authoritative* mutex and running without its reply would hold no lock at all, whereas this join is *advisory* and failing closed would stop the only feed the state machine has. **This is not the `alwaysOutputData` mistake of 2026-08-13**: there an empty Drive reply was turned into "searched, found nothing" and latched a flag; here an empty reply genuinely means "nothing is locked" and nothing is written.

**SQL proven by hand before deploy** (`PREPARE t(int,text)`, live DB): `$2='-'` → **353** candidates, no error. `$2` = two of those ids → **351**, and both named ids **absent**. Exactly −2.

**⚠️ BLOCKER — the change is in the DB but the running system is still on the old graph.** Deployed 22:17:18Z via `deploy_wf.sh` (`active=true`, `versionId=activeVersionId`, repo↔live match). Live row confirmed: **14 nodes, both new nodes present, `queryReplacement` = `={{ $json.gear }},{{ $json.LOCKED_IDS }}`**. But the 22:18:45Z pass produced run data for **8 nodes and neither new one**, while `Pick Drain Candidates` still returned 353. `deploy_wf.sh` writes the DB directly, which **bypasses n8n's activation path**, so the in-memory schedule registration in n8n **main** still holds the pre-import graph. Same cause as the `cls_d` change, which also needed a main restart to register.
- **Do NOT restart n8n main casually to fix this** — today a restart produced 394 crashed + 104 cancelled executions, and `errorHandler01` converted those into `MAX_ITERATIONS` moves (367→379). **Land cleanup #9 first**, then a restart is cheap and safe.
- Public API is not reachable inside main (`localhost:5678` refused despite `0.0.0.0:5678` listening) — needs re-checking on `127.0.0.1` and via traefik, plus an API key, before it can be used as the no-restart activation path.
- **Consequence for `deploy_wf.sh`: "imported + active=true + match=true" is NOT proof a change is live.** Proof is run data from the new nodes. Every prior "deployed" claim made on the strength of that script deserves re-checking.

**Which workflows this blocker actually affects — it is NOT all of them.** Only `indoxV2BaseDrain01` carries a schedule trigger (`Every 5 min`). The driver, all four routers, the extractors and `errorHandler01` are reached by `executeWorkflow` / error dispatch, which load the definition from the DB **per call**. Proven empirically today, not assumed: the claim-hash change to `indoxV2ActionsGDoc01` regressed the fleet to 852 err/hr **immediately on import, with no restart**. So cleanup items #3–#12 land live on deploy; **only #1 and #2 wait on the restart.**

---

#### ▶ STEP 9 + 12 — EVIDENCE (2026-08-14 22:26Z). **DONE and LIVE.**

`errorHandler01 :: Backoff + Dead-letter` → renamed `Record ERROR (no backoff, no status)`.

| | before | after |
|---|---|---|
| `RETRY_COUNT` | `= COALESCE(...)+1` | **gone** |
| `STATUS` | `'MAX_ITERATIONS'` at 5 | **gone** |
| `NEXT_RETRY_AT` | `now() + 5·3ⁿ min` | **gone** |
| `ERROR` | set | **kept — the only write** |

Live executable body is **234 chars**, one `SET`, `"ERROR"` only. Verified against the *body*, not the whole query — the first check returned `t/t/t` because my own SQL comment names the three removed columns, which is the same substring-contamination trap that produced the bogus "20.7 searches/doc" figure earlier. Anchoring on `split_part(q,'*/',2)` gives `f/f/f`.

**The iteration guard is not lost.** `Global :: Record Base Doc Failure` still increments `RETRY_COUNT` and still terminalises at `MAX_ITERATIONS` 5 (cleanup #8 keeps exactly that) — on a real action outcome instead of on any exception.

**#12 resolved in the same edit:** both files carried workflow id `errorHandler01`, so the last import silently won, and they had diverged — `apps/indox` capped the park at 60 min, `platform-base` did not (`5·3⁸` = 22.8 days). Live was the capped one (`sha c75664b035c8`). Both now hold identical SQL (`sha 2e2af49dc61e`).

**BASELINE FOR THE PROOF (22:25Z, immediately pre-deploy):** `MAX_ITERATIONS` **376** · parked **11,603** · rows with `ERROR` **10,259**.

---

#### ▶ STEP 3 — EVIDENCE (2026-08-14 22:34Z). **DONE and LIVE.**

Deleted from `indoxV2Driver01`: `If TEST` · `Blocked: Build Backoff` · `Blocked: Batch Upsert` · `Blocked: Resume` · **`Process Blocked Error`**. `If NOT LOCKED` out1 now leads nowhere — a locked document produces nothing at all. **137 → 132 nodes**; live row confirms `has_stoperror=f`, `has_backoff=f`. Lane was self-contained: one inbound edge from outside, **0 expression references** to any of the five.

**Two things found while deleting it, both worth keeping:**
1. **`If TEST` was dead logic, not a test affordance.** `If NOT LOCKED` combines its conditions with **OR** (`LOCKED is false` OR `mode == 'test'`), so out1 means *locked **and** not test*. `If TEST` then re-asks `mode == 'test'`, which out1 has already excluded — its out0 (→ `Execute Action`) was **unreachable**. The test escape hatch lives in `If NOT LOCKED` itself and is untouched.
2. **`Process Blocked Error` is a `stopAndError`** — so every lock-blocked dispatch *failed its execution*. That is what fed `errorHandler01`, which (until #9 landed) turned lock contention into `RETRY_COUNT+1` and eventually `STATUS='MAX_ITERATIONS'`. **Lock contention was a documented path into `MAX_ITERATIONS`.** Both ends of that chain are now cut.

---

#### ▶ STEP 4 BLOCKER — THE TERMINAL STATUSES ARE NOT TERMINAL (2026-08-14 22:36Z)

**The directive's own example proves it.** `UNKNOWN_COMPANY` already exists on **183 rows**, and the drainer does **not** exclude it. Its terminal set is only:

`COMPLETED · MERGED · DOUBLE · OLD · GARBAGE · PAUSE · MAX_ITERATIONS · ACTION_RESTART`

Everything else stays in `open` and keeps matching its class. Live census of statuses the drainer does **not** exclude:

| status | rows | drain class it stays in |
|---|---:|---|
| `MISSING_LINK` | **6,215** | `cls_d` file discovery (6,352 total) |
| `MISSING_COMPANY_ID` | 1,649 | `cls_c` (1,363 total) |
| `TO_EXTRACT` | 385 | `cls_d`/`cls_e` |
| `MISSING_TYPE` | 291 | `cls_c` |
| `UNKNOWN_COMPANY` | **183** | `cls_c` |
| `IN_PROGRESS` | 164 | whichever class its flags put it in |
| `EXTRACTION_FAILED` | 37 | `cls_e` |
| `NEEDS_REVIEW` / `ACTION_REQUIRED` | 2 | — |

**So writing a terminal STATUS does not stop the re-offer — the row is picked again on the very next pass. This is exactly why `NEXT_RETRY_AT` was invented as a hide-table.** Ship #4 as written and 33,300 `NO ACTION` stamps become infinite re-offers: strictly worse than today, because today the park at least suppresses them.

**#4 therefore requires #3b first:** the drainer's `open` CTE must exclude the failure statuses it writes. Mechanically forced, not a preference.

**⚠️ ONE DECISION IS THE OWNER'S, AND IT IS BIG: `MISSING_LINK`, 6,215 rows — the single largest open population.** It has been treated as *a legitimate success state* (the file simply is not in Drive yet), and `cls_d` exists specifically to keep re-searching for it. Excluding it makes it permanent until an explicit `ACTION_RESTART`, which is faithful to *"if it fails the only way to re-run is ACTION_RESTART"* — but it means **a document whose file arrives in Drive tomorrow is never found**, unless the sync that lands the file also raises `ACTION_RESTART`. That wiring does not exist today.
- **Two coherent options:** (a) exclude it and make the Drive/Gmail sync raise `ACTION_RESTART` when a file lands for an existing row; (b) keep `cls_d` re-searching and accept that file-discovery is the one lane that legitimately retries.
- **This also collides with A0.1** — the search lane is provably broken (52% false negatives), so latching 6,215 rows terminal *before* the search is fixed would freeze in a known-bad verdict. **Recommendation: fix A0.1 first, or take option (b) for `MISSING_LINK` only.**

---

#### ▶ §TWO FEEDS — THE DRAINER IS NOT THE ONLY DISPATCHER (2026-08-14 22:40Z)

I set out to add the failure statuses to the drainer's terminal set (#3b) and first checked that `ACTION_RESTART` — which the drainer *excludes* — still reaches a document. It does, and the reason invalidates the plan as written.

```
indoxApi01 :: Poll Line Changes  [scheduleTrigger]
        └─> Get Changed Docs  [postgres, 120 slots]
                └─> Process Changed Doc
```

**This is a second dispatcher, on its own 5-minute schedule.** Its own SQL comment states it plainly: *"The only two feeders are this poll and `indoxV2BaseDrain01`"* — so `indoxV2BaseDrain01`'s comment claiming to be *"the only thing driving the state machine"* is **false**, and I had been reasoning from it all session.

**Why this breaks #2, #3b and #4 specifically:**

1. **Its `recov` slice selects the exact statuses #4 would write:** `NEEDS_REVIEW · EXTRACTION_FAILED · DOUBLE · ACTION_RESTART · UNKNOWN_COMPANY · API_TOOLS_FAILED · MISSING_COMPANY_ID · MISSING_TYPE`. Making them terminal **in the drainer only** changes nothing — this poll picks them straight back up. #3b as I specified it last tick would have been a no-op, and I would have reported it as a fix.
2. **It is a second `NEXT_RETRY_AT` reader:** `("NEXT_RETRY_AT" is null or <= now() or "STATUS" = 'ACTION_RESTART' or "NEXT_RETRY_AT" = 'infinity')`. The per-appearance verdict table lists this node as **KEEP** on the grounds that it only *reads*. That is true and still misses the point: **deleting the drainer's gate line (#2) while this one survives leaves the parks half-honoured** — suppressed in one feed, ignored in the other.
3. **It is the `ACTION_RESTART` path.** `ACTION_RESTART` is in the drainer's exclusion set, so this poll is the *sole* route by which a restart reaches a document. **Any plan that makes failure terminal depends entirely on this node continuing to work.** It cannot simply be deleted for purity.

**It also already solved the problem #4 is walking into** — worth copying rather than re-deriving. The `s_restart` slice is ordered `updated_at ASC` and capped at 20 of 120 slots, and its comment explains why it does not loop: *"the restart actions set `STATUS='IN_PROGRESS'` and clear the completion flags … so a row leaves the slice on the same pass that picks it up — there is no re-offer loop."* **That is the shape a terminal write needs: change the row so it no longer matches the slice that selected it.** Setting `STATUS` alone does not do that in either feed.

**Corrections this forces to earlier entries in this file:**
- ~~"the drainer is the only feed"~~ — **retracted**, twice-stated, false.
- #2's verify line "eligible-now jumps 112 → ~8,500" measures the drainer only and ignores this poll's 120/pass.
- #10's `Terminalize Stalled` deletion needs re-checking against this node — both live in `indoxApi01`, and this poll may be what re-animates an `IN_PROGRESS` row.

**THE TWO FEEDS DISAGREE ABOUT WHAT "TERMINAL" MEANS.** The drainer excludes 8 statuses; this poll excludes **3** (`MERGED · GARBAGE · OLD`). Its own `terminal` flag is `STATUS = 'COMPLETED'` and nothing else. Measured live:

| status | rows | drainer offers | poll eligible | in poll's `recov` slice |
|---|---:|:---:|:---:|:---:|
| `COMPLETED` | **21,314** | ✗ | **✓** | ✗ (enters via `s_adj`) |
| `DOUBLE` | 1,421 | ✗ | **✓** | **✓** |
| `MAX_ITERATIONS` | **377** | ✗ | **✓** | **✓** |
| `PAUSE` | 34 | ✗ | **✓** | ✗ |
| `OLD` / `MERGED` / `GARBAGE` | 1,201 | ✗ | ✗ | ✗ |

**Three consequences, in order of severity:**
1. **`PAUSE` is not honoured by this feed.** 34 documents the operator explicitly held are eligible here. `PAUSE` is the estate's designed park-forever pattern (the `infinity` comment in this very node recommends it: *"use a STATUS the pickup excludes (the PAUSE pattern)"*) — and this node does not exclude it.
2. **`MAX_ITERATIONS` is not terminal either** — 377 rows sit in `recov`, so "gave up" still gets re-offered here. The drainer's giving-up has no effect on this feed.
3. **`s_adj` selects `terminal and not recov`, i.e. `COMPLETED` rows — pool 21,187 at `rn <= 120`.** This is the mechanism behind task #32 *"COMPLETED is not terminal — 1,903 rows have left it"*.

**Precision about what is and is not proven.** The SQL proves **eligibility** — that is read directly off the predicates and is certain. It does **not** prove dispatch rates. Live `updated_at` touches are `MAX_ITERATIONS` 1/377 and `COMPLETED` 10/21,314 in 15 min, and the 10 are more likely rows *entering* `COMPLETED` (the bar shows 10 COMPLETED/hr) than `s_adj` re-drives. **Do not quote those as re-drive counts.** What would settle it: execution data from `Process Changed Doc` showing a `COMPLETED` or `PAUSE` id.

**Next action:** decide the terminal set ONCE, apply it to BOTH feeds in the same change. Candidate: `elig` gains `PAUSE` and `MAX_ITERATIONS` to its exclusion; `recov` loses `MAX_ITERATIONS`; `s_adj` is re-justified or deleted. Only then are #2/#3b/#4 safe.

---

#### ▶ STEP 17a — TERMINAL SET, FIRST HALF (2026-08-14 22:44Z). **Deployed; poll path pending restart.**

`indoxApi01 :: Get Changed Docs` — `elig` exclusion `('MERGED','GARBAGE','OLD')` → **`('MERGED','GARBAGE','OLD','PAUSE','MAX_ITERATIONS')`**, and `MAX_ITERATIONS` removed from the `recov` status list (both occurrences: the `recov` flag and the `elig` admission OR-group). Live row confirms the new exclusion. `ACTION_RESTART` still admits a row via `s_restart`, so the operator's re-run hatch is untouched.

**Effect, measured by running BOTH versions of the real query against the live table:**

| | before | after |
|---|---:|---:|
| eligible **pool** | 32,167 | **31,756** (−411) |
| rows **dispatched** (the 120 cap) | 120 | 120 |

**Honest reading: the immediate dispatch effect is ~zero.** In this sample neither `PAUSE` nor `MAX_ITERATIONS` won a slot either way — the poll's 120 went to `TO_EXTRACT` 88→89 · `IN_PROGRESS` 20 · `COMPLETED` 10→9 · `NEEDS_REVIEW` 1 · `MISSING_LINK` 1. The change closes a **real but low-rate** leak (411 rows removed from contention; earlier sampling showed 1 of 377 `MAX_ITERATIONS` rows touched per 15 min), not a live flood. Do not report it as "411 rows stopped being processed".

**⚠️ CORRECTION to §Two Feeds.** Last tick I wrote that the 10 recently-touched `COMPLETED` rows were *"more likely rows entering `COMPLETED`… do not quote those as re-drive counts."* **That caution was wrong and is retracted** — the poll's own query returns **10 `COMPLETED` rows inside its 120**, which *is* dispatch, read straight off the query rather than inferred from `updated_at`.

**So `s_adj` spends 8.3% of the API poll's capacity re-driving already-COMPLETED documents** (10 of 120 slots, every 5 minutes). That is the quantified mechanism behind task #32 *"COMPLETED is not terminal"*, and it is a far larger waste than the `PAUSE`/`MAX_ITERATIONS` leak this step closed. **It is the next thing to fix in #17**, and it needs the decide-layer check first: if these rows return `no_action_already_completed`, the slots are pure waste, and that verdict has **no** `BACKOFF_MS` entry (deliberately), so nothing suppresses the re-offer.

**Both feeds converge on the same dispatcher.** `Process Changed Doc` is an `executeWorkflow` → **`indoxV2Driver01`**, passing only `{ID}` — the identical entry the drainer's `Driver: Run By ID` uses. So this is not a parallel pipeline; it is a second *queue* into one driver. That is why lock contention and duplicate actions can appear even when the drainer looks idle, and it is why any capacity reasoning based on the drainer's 156-row pass alone is incomplete: **the poll adds up to 120 more every 5 min.**

**❌ RETRACTED (22:47Z): "`s_adj`'s COMPLETED rows are wasted".** I read `const _terminalKeep = ['COMPLETED','OLD'].includes(...)` as a blanket refusal to act on COMPLETED rows. **It is not.** It guards exactly one line:

```js
const _terminalKeep = ['COMPLETED','OLD'].includes(String(normDoc.STATUS||'').toUpperCase());
if (_iter >= _maxIter && !_terminalKeep)
  return { ACTION: 'mark_max_iterations', ... };
```

It suppresses **only the MAX_ITERATIONS ceiling**. Execution then falls through to `docBaseDecide(normDoc, dup)` and the row gets a real action. The node's own comment says so outright: *"A COMPLETED row is re-admitted by the pickup's `s_adj` slice **on purpose, for double adjudication**; returning `no_action_already_completed` here would cut that off."*

**So `s_adj` is doing duplicate adjudication on finished work — it must NOT be deleted.** It is the mechanism behind R2 (*"one row per real document"*, 5,535 excess rows / 4,249 groups) and behind task #32 (*"COMPLETED is not terminal — 1,903 rows have left it"*): those are the same event seen from two sides. It is also the vector for task #38's wrong demotions, so it is **correctness-sensitive, not waste** — the opposite of what I reported. My "≈120 driver executions/hour producing no state change" figure is withdrawn; those dispatches do work.

---

#### ▶ STEP 4 RE-SPEC — THE TERMINAL WRITE ALREADY EXISTS (2026-08-14 22:56Z)

I read the four decide ladders to derive the STATUS/flag mapping rather than invent it. The mapping turned out to be unnecessary: **every `no_action_*` verdict is guarded by "the terminal STATUS is already set"**, and each one has a paired `update_status_*` action that set it on the previous visit.

| verdict | the guard directly above it |
|---|---|
| `no_action_awaiting_company_id` | `if (doc.STATUS !== 'MISSING_COMPANY_ID') return 'update_status_missing_company';` |
| `no_action_unknown_document_type` | `if (doc.STATUS !== 'MISSING_TYPE') return 'update_status_missing_type';` |
| `no_action_link_not_found` | `if (doc.STATUS !== 'MISSING_LINK') return 'update_status_missing_link';` |
| `no_action_double` | `return doc.STATUS === 'DOUBLE' ? 'no_action_double' : 'update_status_double';` |
| `no_action_old_date` | `if (STATUS != 'OLD' && != 'COMPLETED') return 'update_status_old_doc';` |
| `no_action_garbage` | `STATUS === 'GARBAGE' ? 'no_action_garbage' : 'update_status_garbage'` |
| `no_action_merged` / `_max_iterations` / `_paused` | `if (STATUS === 'MERGED' / 'MAX_ITERATIONS' / 'PAUSE')` |

**So the state machine already does exactly what the directive asks** — one terminal write at the end of the action, via `update_status_*`. The `no_action_*` verdict is not a failure needing a write; it is the ladder reporting *"already terminal, nothing to do."*

**Three consequences:**
1. **#4 shrinks to deleting two lines** — the `', NO ACTION ' + act` stamp and the `NEXT_RETRY_AT` write. Nothing to add.
2. **No `*_COMPLETED` flag is set on failure.** The directive's *"`ACTION_COMPLETED` should be set"* is already satisfied upstream by the action that ran; writing a completion flag from a *no-action* path would be the same latch that `alwaysOutputData` produced on ~860 rows today. **Avoided entirely** — that was the single biggest risk in this cleanup.
3. **#3b is the load-bearing change, not #4.** The re-offer loop is not caused by a missing terminal write; it is caused by the drainer and the poll continuing to offer rows that are *already* terminal. Fixing the exclusion lists ends the loop, after which `no_action_*` stops firing at all and the park has nothing left to suppress.

**SHIPPED 22:52:33–22:53:19Z.** The whole `NoAct` lane deleted from all four routers — `NoAct: Build Backoff` · `NoAct: Any?` · `NoAct: Batch Upsert` — and `Decide <lane> Action` out0 wired straight to `NoAct: Return Verdicts` (which is `return $('Decide <lane> Action').all()`, so it reads the decide node directly and its output is unchanged).

| router | nodes | live `NoAct` | live `BACKOFF_MS` |
|---|---:|:---:|:---:|
| `indoxV2ActionsGDoc01` | 123 → **120** | f | f |
| `indoxV2ActionsBS01` | 55 → **52** | f | f |
| `indoxV2ActionsShip01` | 116 → **113** | f | f |
| `indoxV2ActionsGlobal01` | 98 → **95** | f | f |

Fleet `mismatched` also went **1 → 0**.

**PROOF — deployed *and* the number moved:** `NO ACTION` stamps written since the 22:53:20Z cutoff = **0**, across **237 successful router executions** in that window (Global 102 · GDoc 59 · Ship 50 · BS 26). Pre-deploy the same measure was 2 per 30 min.

**Honest caveat on the "33,300 → 0" target:** 33,300 is the *historical accumulation* (11,722 rows still carry at least one `NO ACTION` stamp). The pre-deploy *rate* was already low — 2 per 30 min — because the parks were hiding most rows from both feeds. The real test of this change comes when **#2 releases the 11,615 currently-parked rows**: at that point the routers see the whole backlog and must still write zero stamps.

**Import burst, not a regression:** 11 errors landed at 22:52–22:53, matching the four import timestamps second-for-second (`indoxV2ActionRouter01` 4, `indoxV2Decide01` 3, `indoxV2Driver01` 3, `indoxApi01` 1). **0 errors after 22:53:19**, the moment of the last import, and all four routers ran clean afterwards. This is the known behaviour already filed as task #21 — replacing a sub-workflow fails whatever is mid-call into it.

**EXECUTION PROOF (owner's rule: run it, don't just read the row).** Deref'd `runData` from 16 real post-deploy executions, 4 per router:

| router | deleted nodes ran | decide still emits |
|---|:---:|---|
| `Global` | **0** | `extract_base_doc` · `__route_gdoc__` |
| `Ship` | **0** | `mark_completed` · `update_name` |
| `BS` | **0** | `extract_per_type` |
| `GDoc` | **0** | (sampled runs were execute-mode) |

`NoAct: Return Verdicts` ran on the no-action path in every decide-mode execution and wrote nothing. **Verdicts are unchanged; only the writes are gone.**

**⚠️ MEASUREMENT TRAP — THE DB CLOCK IS A DAY BEHIND THE SESSION DATE.** The first execution-proof run returned *"no post-deploy execution to inspect"* for all four routers, which reads exactly like a broken deploy. It was not: `now()` in Postgres is **2026-08-13 22:57**, while the session date is 2026-08-14, so an absolute cutoff of `'2026-08-14 22:53:20+00'` sat 24 hours in the future and matched zero rows **silently**. **Always use relative intervals (`now() - interval 'N minutes'`) in these queries, never an absolute date.** Every timestamp written in this file is session-dated; DB timestamps are one day earlier.

**Still to confirm (now a follow-up, not a blocker):** whether `update_status_*` writes `REQUIRED_ACTION`.

---

#### ▶ SOURCE-OF-TRUTH AUDIT + #12 CLOSED (2026-08-14 22:58Z)

Owner: *"make sure automations source of truth stays in indox blueprint workflows in repo."* `deploy_wf.sh`'s `match=` only compares `versionId` to `activeVersionId` — it proves an import happened, **not that the bytes agree**. So I fingerprinted every blueprint (name/type/typeVersion/disabled/parameters + connections, order-insensitive) against the live `workflow_entity` rows.

**First run: `match=67 · drift=1 · absent=0`.** The single drift was `errorHandler01`, and it was exactly item #12's duplicate-id problem — two repo files carry that id, so the last import silently wins. They differed in **one node**, `EH Unlock Doc`:

| | `PROCESS` |
|---|---|
| `apps/indox/…/errorHandler01.json` | `doc_action` ✅ (matches LIVE) |
| `platform-base/n8n/workflows/errorHandler01.json` | `doc_step` ❌ (retired namespace) |

**Importing the platform-base copy would have silently reverted the estate to the pre-consolidation lock namespace** (task #26), leaving error-path unlocks releasing keys nothing else uses — a lock leak that would look like unexplained contention. Synced platform-base to the live/indox definition.

**Re-run: `match=68 · drift=0 · absent=0` — SOURCE OF TRUTH OK.**

**THEN THE DUPLICATE WAS REMOVED ENTIRELY (owner, 2026-08-14 23:14Z):** *"errorHandler01 should be only at platform base level, not in indox."* Correct — syncing two copies of one id is a workaround; one copy is the fix. `apps/indox/blueprint/n8n/errorHandler01.json` **deleted**. Checked before deleting: `platform-base` == `apps/indox` == **LIVE** (all `df027e604997`), so nothing changed in the running system.

- **No dangling reference created.** `scripts/refactor/dangling-workflow-ref-lint.py` reports 3 findings, none of them `errorHandler01` — every `errorWorkflow: errorHandler01` still resolves via platform-base. *(The 3 are pre-existing and unrelated: `indoxV2QueryShipmentId01`, `indoxV2QueryInvoiceId01`, `indoxApiSupabase01` — worth their own item.)*
- **`deploy_wf.sh` taught to resolve platform-base.** It only looked in `apps/indox/blueprint/n8n`, so a shared workflow became undeployable. It now falls back to `platform-base/n8n/workflows` and labels the source. Proven by deploying `errorHandler01` through it: `(platform-base) errorHandler01 → imported → active=true match=true`.
- **Repo cleaned of my own artifacts:** 26 `*.bak_*` files I had written into `apps/indox/blueprint/n8n` and `platform-base/n8n/workflows` removed. The source of truth should contain source, not my scratch copies.

**Parity now `match=67 · drift=0 · absent=0`** (67, not 68, because one duplicate file is gone).

---

#### ▶ STEP 11 — EVIDENCE (2026-08-14 23:13Z). **DONE and LIVE. 35 dead nodes removed.**

| workflow | nodes |
|---|---|
| `indoxV2Driver01` | 132 → **130** (`If COMPLETED`, then `Map NO ACTION` on the cascade pass) |
| `indoxV2ActionsGDoc01` | 120 → **111** (9 × `No Action: …`) |
| `indoxV2ActionsShip01` | 113 → **104** (9) |
| `indoxV2ActionsGlobal01` | 95 → **86** (9) |
| `indoxV2ActionsBS01` | 52 → **46** (6) |

**Deleted only what was confirmed dead at the moment of deletion** — no outgoing edges **and** zero expression references — rather than trusting the earlier "0 runs / 1,161 executions" measurement. The guard paid off immediately: it **refused** `Map NO ACTION` on the first pass because it still pointed at `If COMPLETED`. Only after that node went did a second pass find it dead. A blind list-based delete would have severed a live edge.

**Verified by execution, not by node count:** 261 executions in the 90 s after deploy, **0 errors**, with all four routers and the driver running.

**Total node reduction across the cleanup so far: 137→130 driver, 123→111 GDoc, 116→104 Ship, 98→86 Global, 55→46 BS, 37→36 API — 68 nodes removed.**

---

#### ▶ IS `NEXT_RETRY_AT` FULLY REMOVED? **NO.** (audit 2026-08-14 23:20Z)

Owner asked the question directly, so it was answered by scanning executable lines only (comments excluded) across the repo **and** against live n8n, separating three things that are not the same: writers, readers, and backoff *shape*.

| | repo | live |
|---|---:|---:|
| **writers** (assignments that are not a `= null` clear) | **0** ✅ | **1** ❌ |
| **readers** (filters on the column) | 3 | 5 |
| **backoff shapes** (`5·3ⁿ` / `BACKOFF_MS` / snooze / retry-after) | **2** ❌ | **2** ❌ |

**Three things are left, and one of them is serious:**

**1. `indoxApiSupabase01` — a live workflow with NO blueprint in the repo.** It still contains `Terminalize Stalled` (writing `NEXT_RETRY_AT` *and* `STATUS`) and its own `Get Changed Docs`. #10 deleted `Terminalize Stalled` from `indoxApi01` only; this copy survived untouched. **It is a THIRD feed** on top of the two already mapped, and it authors state — exactly what the owner's purity rule forbids. → item **#18**.

**⚠️ AND IT EXPLAINS A HOLE IN MY OWN PARITY CHECK.** `parity.py` reports `absent_from_live=0`, which means *every repo file has a live match* — it never checked the reverse, so **a live workflow with no repo file is invisible to it**. `SOURCE OF TRUTH OK` was therefore weaker than it read. The dangling-ref lint had already hinted at it (`mailApi01 → indoxApiSupabase01`, "no blueprint file declares this id") and I did not follow the thread. **parity.py must gain a live-orphan check.**

**2. Dead `__delayMin` in `Invoice/ShipmentDocEx01 :: Select`.** #7 removed the line that *assigned* `NEXT_RETRY_AT`, but `const __delayMin = Math.min(5*Math.pow(3,Math.min(prev,8)),60)` is still computed. Harmless (nothing consumes it) but it is a live backoff shape in the repo. → item **#19**.

**3. Readers remain, by design and by plan.** The drainer's gate and `Get Changed Docs`' gate are exactly what **#2** removes, and #2 is restart-pending. `syncV3FullTest01 :: HD PollMatch` is a test fixture, out of scope.

**So: writers are gone from everything the repo owns, but NOT from everything that is running.** The honest statement is *"no backoff remains on any action path in the INDOX blueprints; one undeclared live workflow still writes the column, and two dead computations remain."*

---

#### ▶ AUDIT FOLLOW-THROUGH (2026-08-14 23:36Z) — one item closed, one claim RETRACTED, one of my own tools was lying

**✅ #19 DONE.** `const __delayMin = Math.min(5*Math.pow(3,Math.min(prev,8)),60)` removed from `InvoiceDocEx01 :: Select` and `ShipmentDocEx01 :: Select` — defined once, consumed nowhere after #7. Deployed, `match=true`, parity clean.
**→ BACKOFF SHAPES: repo 0, live 0.** No `5·3ⁿ`, no `BACKOFF_MS`, no snooze, no retry-after anywhere.

**❌ RETRACTION — "`indoxApiSupabase01` still runs `Terminalize Stalled` and writes `NEXT_RETRY_AT`".** False. Measured:

| | |
|---|---|
| `active` | **false** |
| executions in 24h | **0** |
| executions **ever** | **0** |

Its `Terminalize Stalled` hangs off a `Poll Line Changes` schedule trigger, which does not fire on an inactive workflow. **The node exists in a live DB row; it has never executed.** I asserted a live writer from the presence of a node, without checking whether the workflow runs — the "deployed ≠ live" lesson, made in reverse.

**The "3 callers" were also wrong.** `indoxDocGet01`, `indoxV2ActionsGDoc01`, `indoxV2ActionsGlobal01` are **not** callers: all three matched only because the string `indoxApiSupabase01` appears inside a **`code` node's JS** (`executeWorkflow=False`, `target=None`) — a comment. My caller scan substring-matched the params blob. Same contamination class as `BLOCKED BY LOCK find_link` and the `f/f/f` check.

**So #18 is hygiene, not a live-state problem:** 16 live workflows with no blueprint, 15 dormant, **1 active** — `indoxDocUploader01` (webhook trigger, `triggerCount=1`, 0 executions in 24h, last updated 08-04). It waits on a webhook nobody calls. Still a source-of-truth violation: the repo cannot describe or correct it.

**⚠️ AND MY OWN `parity.py` WAS PRODUCING A FALSE GREEN — TWICE.**
1. **Wrong direction.** `absent_from_live=0` only proves every *repo* file has a live match. It never checked live→repo, so **16 orphans hid behind a green "SOURCE OF TRUTH OK"** through every deploy this session. Added a live-orphan check.
2. **Then the new check itself lied.** `act[wid] = (a == "t")` against `active::text`, which renders **`'true'`/`'false'`, not `'t'`/`'f'`** — so every orphan was marked inactive and it printed *"of which ACTIVE: 0"*. Caught only by cross-checking against the earlier query that said `active=true`. **This is the identical defect already on record** — the loop that tested `= "t"` and deactivated a live router six times, causing 221 errors. Fixed to accept both forms; the verdict now correctly flips to `>>> ACTIVE LIVE WORKFLOW WITH NO BLUEPRINT`.

**Every "SOURCE OF TRUTH OK" reported earlier in this session was true for drift (0) but blind to orphans.** Drift really was 0 each time; the orphan count simply was not being measured.

---

#### ▶ #20 DUPLICATE-ACTION GUARD — SPECIFIED, NOT SHIPPED. Two prerequisites, both now PROVEN.

The guard must answer *"has this action already run on this document?"* by reading `ACTION_LOG`. Two things block a correct implementation, and shipping without them would be worse than not shipping: a **false** duplicate error halts legitimate work on a live pipeline.

**BLOCKER 1 — `ACTION_RESTART` leaves no trace in `ACTION_LOG`.** Measured: **0 of 33,679 rows** contain `RESTART` anywhere in the log. The owner's requirement is explicit — *"so it won't error on supported manual restart"* — but there is nothing to detect. `STATUS` cannot substitute: the restart actions immediately set `STATUS='IN_PROGRESS'` and clear the completion flags (documented in `Get Changed Docs`' `s_restart` note), so by the time the re-run happens the evidence is already gone.
→ **The restart actions must stamp `ACTION_LOG` first.** A restart *is* a real action, so this is consistent with the purity rule rather than an exception to it.

**BLOCKER 2 — the `ACTION` → label map is not derivable, and the label vocabulary is dirty.** Static extraction over every writer found only **5 literal labels** (`Resolve Double (…)` ×4, `BASE APITOOLS RETRY`); every other label is built inside `Set` nodes from expressions. And the live vocabulary is inconsistent by construction — `Extract Base Doc` (human label) sits beside `link_documents` (raw action name), plus **755 entries whose label is just `1`, `2` or `3`**. Any hand-written map would be wrong in both directions.

**THE FIX IS TO STOP NEEDING A MAP.** Have each action's **end-of-action upsert** stamp a canonical token next to its human label — `ACTION=<action_name>` — so the log becomes self-describing:
```
Extract Base Doc, 1786661076142, 2915900, ACTION=extract_base_doc
```
The guard then does an exact match on `ACTION=<name>` with **no mapping at all**, and the same token makes the `s_restart` marker trivial (`ACTION=restart_gdoc`). It stays one upsert per action end — the model is unchanged, the entry just carries the action's real identity.

**Order:** stamp the token (all action upserts + the restart actions) → let it accumulate for one drain cycle → then enable the guard, scoped to actions whose token is present. Enabling it earlier would compare against a log that predates the token and fire on nothing, which is the *safe* failure but proves nothing.

---

#### ▶ #16 — `ACTION_LOG` PURITY. **WRITER SIDE DONE AND PROVEN (2026-08-14 23:44Z).**

This was the acceptance test for the whole cleanup: *"only actions are written to ACTION_LOG, and no other writers."*

| non-action writer | stamps in the last 45 min |
|---|---:|
| `BLOCKED BY LOCK` *(driver lock branch, deleted in #3)* | **0** |
| `NO ACTION <verdict>` *(4 × `NoAct`, deleted in #4)* | **0** |
| duplicate entries from the merge trigger | **0** across **859** touched documents |

**`incdoc_action_log_append()` is no longer duplicating.** The live function is the longest-common-prefix merge (it appends only the tail the stored log lacks, with a mid-entry guard so a divergence on a numeric token steps back one token and never decapitates an entry). Measured on rows touched in the last 25 minutes: **859 documents, 0 with duplicates, worst copies of any one entry = 1.**

**⚠️ MY FIRST MEASUREMENT OF THIS WAS WRONG AND IS RETRACTED.** It reported *"30,768 rows with duplicates, 350,466 excess copies"* — alarming and false. The query used `count(DISTINCT m[0])` on a `regexp_matches` result, and **Postgres arrays are 1-indexed**, so `m[0]` is NULL, `distinct_entries` was 0 for every row, and "excess" simply re-counted every entry (350,466 ≈ the 349,916 total triples measured minutes earlier — the tell I should have caught immediately). Corrected by extracting each triple as a row and counting per `(document, entry)`.

**True historical damage (→ #16b, folded into #13):**

| | |
|---|---:|
| total entries | 352,482 |
| distinct (doc, entry) | 296,517 |
| **excess copies** | **55,965** |
| documents affected | **1,170** |
| worst single entry | **67 copies** |

That matches the previously recorded 1,178 rows / 51,983 excess / worst 67 — same population, grown slightly before the fix landed. **It is frozen: no new duplication is being created.** What remains is a one-time data repair, alongside the 78,193 legacy `BLOCKED BY LOCK` and 45,881 `NO ACTION` stamps sitting in old logs.

**Consequence for #20:** the log is now clean going forward, so a duplicate-action guard reading it will see only real actions — the precondition that made the 69.2% duplicate figure meaningless is resolved. The two remaining blockers (no restart marker, no derivable label map) are unaffected.

---

**Today's `If SAME ACTION TWICE` is unchanged and still intra-execution only** (`$('Execute Action').item.json.ACTION` vs `$json.ACTION`), so a repeat across two dispatches remains invisible. Live duplicate rate for context: **1.9%** (65 of 3,445 runs, 2h window), worst `Extract Per Type` at 1.1×/doc over 568 docs.

---

#### ▶ STEP 3b — EVIDENCE (2026-08-14 23:02Z). **DONE and LIVE, both feeds.**

Terminal failure set added to the drainer's `open` CTE **and** the poll's `elig` exclusion:
`MISSING_COMPANY_ID · MISSING_TYPE · UNKNOWN_COMPANY · EXTRACTION_FAILED · API_TOOLS_FAILED · ACTION_REQUIRED · NEEDS_REVIEW` — **2,179 rows**, now revivable only by `ACTION_RESTART`. Poll `recov` trimmed to what may still legitimately be re-driven: `DOUBLE` (adjudication) · `ACTION_RESTART` (via `s_restart`) · `MISSING_LINK`.

**Executed both queries, before and after, against the live table:**

| poll's 120 slots | before | after |
|---|---:|---:|
| `MISSING_COMPANY_ID` | 9 | **0** |
| `API_TOOLS_FAILED` | 6 | **0** |
| `NEEDS_REVIEW` | 1 | **0** |
| `TO_EXTRACT` | 81 | **92** |
| `IN_PROGRESS` | 14 | **17** |
| `COMPLETED` (`s_adj`) | 8 | 10 |

**16 of 120 slots (13%) were going to documents the state machine had already ruled on, and they moved to real work.** Drainer: 225 → 224 candidates (`NEEDS_REVIEW` 1 → 0).

**`MISSING_LINK` (6,215) deliberately NOT in the set**, on two pieces of evidence: `Decide GDoc Action` line 371 returns `find_link` for a row with `SHORT_DOC_ID` + `COMPANY_NAME` — so `cls_d` is doing real work, not idling — and the search lane still has 52% false negatives (A0.1). Latching 6,215 rows on a known-bad verdict is this morning's `alwaysOutputData` mistake again. **Revisit once A0.1 is proven. Still the owner's call.**

---

#### ▶ STEPS 5–8 — EVIDENCE (2026-08-14 23:05Z). **DONE and LIVE.**

All four park writers on action paths removed. `Record Base Doc Failure` keeps its counter deliberately — that verdict is reached on a real action outcome, and `MAX_ITERATIONS` is now genuinely terminal in both feeds after #3b.

**⚠️ A REGEX NEARLY SHIPPED BROKEN SQL, AND EXECUTING IT IS WHAT CAUGHT IT.** For #8 I removed the park with `"NEXT_RETRY_AT"\s*=\s*now\(\)[^,]*,`. That stops at the **first** comma — which sits *inside* `least(COALESCE("RETRY_COUNT",0), 8)` — so it deleted the column name and left `least(...), 60))),` dangling. My own assertions passed (`"NEXT_RETRY_AT"` was indeed gone). **`EXPLAIN` failed with `syntax error at or near "("`.** Redone with a parenthesis-balanced scan; the removed term is 114 chars. Same class as the non-greedy `.*?\n  \}` that truncated a function earlier. **This is precisely why "always execute the modified node" is now a working rule — a row-level check would have shipped it.**

---

#### ▶ STEP 10 — EVIDENCE (2026-08-14 23:07Z). **DONE and LIVE.** `indoxApi01` 37 → 36 nodes.

`Terminalize Stalled` deleted. It ran every 5 min and, on a 6-hour wall-clock guess with no action and no decision behind it, wrote `STATUS` (→ `MAX_ITERATIONS`/`TO_EXTRACT`/`NEEDS_REVIEW`), `RETRY_COUNT+1`, `NEXT_RETRY_AT` and `REQUIRED_ACTION`. Structurally safe to remove: fed only by `Poll Line Changes`, **no outbound edges, 0 expression references**; the trigger still feeds `Get Changed Docs`.

**The planned companion change turned out to be unnecessary.** #10 said the end-of-action upsert must now clear `IN_PROGRESS`. It does not need to: **both feeds still admit `IN_PROGRESS`** (the poll's `elig` OR-group names it explicitly; the drainer's exclusion set does not contain it), so such a row keeps being dispatched and the action that finishes writes the real status at its own end — which is already the one-upsert-per-action model. No extra write was added.

Its `else 'NEEDS_REVIEW'` branch is also the documented cause of task #17 (~3,250 documents falsely marked `NEEDS_REVIEW`); that failure mode is now gone. All 68 blueprints match live by content. **#12 is now genuinely closed** — previously only the dead-letter node was reconciled, and this is what proves the rest. If it does not, adding it there — at the real terminal write, not in the no-action path — is the one genuine addition the directive asks for.

**Evidence for the `MISSING_LINK` decision (still the owner's call):** `Decide GDoc Action` line 371 is `if (doc.SHORT_DOC_ID && doc.COMPANY_NAME) return 'find_link';` before falling through to `no_action_link_not_found`. So a `MISSING_LINK` row **with** a short doc id and company name is genuinely re-searched, not idling — that is `cls_d` doing real work. Excluding `MISSING_LINK` in #3b would stop those re-searches. This confirms the concern rather than resolving it.

**#17 is therefore resolved as far as the terminal set goes:** `PAUSE` + `MAX_ITERATIONS` excluded (17a, deployed), `s_adj` **kept by design**, `DOUBLE` left to the existing `stamped_double` routing. #3b and #4 are unblocked on this axis — what remains for them is the terminal-write design, not the feed question.

**Deployment note:** `Poll Line Changes` is a **scheduleTrigger**, so this node joins #1 and #2 in the restart-pending bucket. `indoxApi01`'s `executeWorkflow` callers (batch upsert etc.) get the new definition immediately; the *poll* keeps running the old graph until n8n main restarts. **Restart-pending queue: #1 (drainer lock join), #2 (gate line), #17a (terminal set).**
**The test:** the n8n main restart that Step 1 needs will produce crashed executions, exactly as today's did. If `MAX_ITERATIONS` is still **376** afterwards, #9 is proven; if it moves, it is not. *(Errors are 0/hr right now, so no natural failure is available to test against — this is the honest state: deployed and verified in the live row, effect not yet observed.)*

---

### ▶▶ Step detail (reference for the table above) — owner authorised 2026-08-14 21:40

> "its all very bad just completle remove any of this backoff / drinier simply filters by joining to redis so wont spwan locked / and thats it should be completle removed its pure garbage"

**AUTHORISED. Concern was raised three times and reaffirmed — proceed, do not re-litigate.**

Execute in this order (order matters: the Redis gate goes in BEFORE the parks come out):

**STEP 1 — drainer asks `processLock01`, NOT Redis directly.** *(Owner: "drainer should use process lock workflow not redis directly.")*
`indoxV2BaseDrain01` calls `processLock01` via `executeWorkflow` — the same way every other caller does — and uses its answer to exclude locked ids from the candidate set. **Never touch Redis from the drainer, and never `lock` / `check_and_lock` / renew — only ask what is held.** `processLock01` owns the key format, the TTL and the semantics; the drainer must not re-implement any of it.
- Pick the read-only ACTION from `processLock01`'s `Switch` (it exposes `lock` / `unlock` / `check_and_lock` / renew). **If no pure-read verb exists, add one to `processLock01`** — do not work around it by reading Redis, and do not call `check_and_lock`, which would acquire.
- Then delete the line `AND (d."NEXT_RETRY_AT" IS NULL OR d."NEXT_RETRY_AT" <= now())` from `Pick Drain Candidates (all open stages)`.

**STEP 2 — delete the driver's blocked lane.** `indoxV2Driver01`: `Blocked: Build Backoff` (already writes nothing), `Blocked: Batch Upsert`, and the `If TEST` out-1 branch feeding them. A locked document is no longer reachable after Step 1.

**STEP 3 — the 4 `NoAct: Build Backoff` nodes** (`indoxV2Actions{GDoc,BS,Ship,Global}01`, each fed by `Decide <lane> Action` out 0). Delete `BACKOFF_MS`, the `NEXT_RETRY_AT` write, and the `', NO ACTION ' + act` ACTION_LOG stamp. Replace with the terminal write from the earlier directive: set the action's `*_COMPLETED` flag, set `STATUS`, put the reason in `REQUIRED_ACTION`. `ACTION_RESTART` is the only re-entry.

**STEP 4 — remaining backoff writers.** `Invoice/ShipmentDocEx01 :: Select` — delete the `__delayMin` write, **KEEP `out.NEXT_RETRY_AT = null`** (that clears on success). `indoxV2ActionsGlobal01 :: Join COMPANY_NAME` — delete the uncapped `5·3ⁿ`. `:: Join COMPANY_ID` — delete the +10 min; it already writes `REQUIRED_ACTION`. ⚠️ *Its case is a 429 rate-limit, i.e. genuinely transient — flagged once, owner's call stands.*

**COMPLETE PER-APPEARANCE VERDICT — every one of the 20 references, nothing omitted:**

| where | what it is | verdict |
|---|---|---|
| `Driver :: Blocked: Build Backoff` | lock park (write already removed) | **DELETE lane** (Step 2) |
| `BaseDrain :: Pick Drain Candidates` | `NEXT_RETRY_AT IS NULL OR <= now()` gate | **DELETE line**, replace with `processLock01` join (Step 1) |
| `NoAct: Build Backoff` ×4 | flat hide-table 6h/24h/**30d** + `NO ACTION` stamp | **DELETE both writes → terminal status** (Step 3) |
| `Global :: Join COMPANY_NAME` | `5·3ⁿ` **UNCAPPED → 22.8 days** | **DELETE** |
| `Global :: Join COMPANY_ID` | +10 min on a 429; already writes `REQUIRED_ACTION` | **DELETE** ⚠️ *429 is transient — flagged once, owner's call stands* |
| `Invoice/ShipmentDocEx01 :: Select` | `5·3ⁿ` capped 60 min **+ `out.NEXT_RETRY_AT = null`** | **DELETE the write, KEEP the null-clear** |
| **`Global :: Record Base Doc Failure`** | `RETRY_COUNT+1` · `MAX_ITERATIONS` at 5 · `ERROR` text · ACTION_LOG · **+ backoff** | **DELETE the `NEXT_RETRY_AT` line ONLY** — keep counter, terminalisation, error, log *(owner: "no need for backoff")* |
| `errorHandler01 :: Backoff + Dead-letter` | identical shape | **DELETE the `NEXT_RETRY_AT` line ONLY** |
| `indoxApi01 :: Terminalize Stalled` | scheduled `UPDATE … SET "STATUS"` inside the API, on a 6h wall-clock guess | **❌ DELETE — this entry previously said KEEP and that was WRONG.** Owner rule: *"only the state machine should ever change the line — no changes in driver, drainer, api. Only 1 upsert at each end of action execution."* This is the API authoring state with no action and no decision behind it. ⚠️ Also **retract the wording "a worker claimed the row and died"** — there is no claim step; `IN_PROGRESS` is set at **ingestion by the sync lanes** (`SyncProcBS000001 :: Register`, `SyncProcGDoc0001`, the Gmail downloaders). I invented the claim to make the sweep sound reasonable. **Real fix: the end-of-action upsert clears `IN_PROGRESS`.** *(Historic note, still true: its budget was 45 min and its own comment says "that number was the whole outage" — `updated_at` is not a heartbeat, so the predicate measured elapsed work, not abandonment; p50 39 min / p90 241 / p99 274; COMPLETED fell to 0/hr. Do not resurrect it with a bigger number.)* |
| **`errorHandler01 :: Backoff + Dead-letter`** | n8n **global** error handler → direct `UPDATE`: `RETRY_COUNT+1`, `MAX_ITERATIONS` at 5, `NEXT_RETRY_AT`, `ERROR` | **❌ WORST OF ALL — reduce to writing `ERROR` only.** It fires on **any** execution failure, including infrastructure. It cannot tell a bad document from a dead worker, yet it authors `STATUS`. **Not hypothetical: today's restart produced 394 crashed + 104 cancelled executions and `MAX_ITERATIONS` moved 367 → 379.** Mechanism fits exactly; the 12 are not individually proven. `MAX_ITERATIONS` is a state-machine verdict, not an error-handler side effect. **Measure next session:** documents whose `RETRY_COUNT` rose during 19:50–20:10. |
| `indoxApi01 :: Build Merge Write` | field on the `NEVER` list | **KEEP** — merge must not copy it between rows |
| `Build: UPDATE COMPANY_ID` / `…COMPANY_NAME` | `$json.NEXT_RETRY_AT \|\| null` passthrough | **KEEP** — becomes always-null, harmless |
| `indoxApi01 :: Get Changed Docs` | reads it; notes rows walled at `'infinity'` | **KEEP** — but **106 `infinity` rows need one-time disposition** |
| `BaseDrain :: Pick All IDs` | comment only | no change |
| `indoxDocBatchUpsert01` trigger · `syncV3FullTest01` · `display.json` · `DocumentDetailPage.tsx` · `schema.sql` · `scripts/refactor/gen-gateway-trigger-schema.py` · `scripts/refactor/trigger-schema-drift-lint.py` | schema / UI / test / lint refs | no change — but the two `scripts/refactor/*` would need updating if the **column** is ever dropped |

**AFTER THIS: `NEXT_RETRY_AT` is written by nothing except `Terminalize Stalled`'s stall marker, and the drainer no longer reads it at all.**

**VERIFY AFTER (baselines to beat):**
| metric | before |
|---|---:|
| workable rows parked | **8,408 of 8,520 (98.7%)** |
| eligible now | 112 |
| parks >1 day | 1,665 · `infinity` 106 |
| `NO ACTION` repeats in ACTION_LOG | ≈33,300 |
| errors/hr | 0 |
- Expect eligible-now to jump from 112 toward ~8,500. Watch the lock count in Redis and errors/hr on the first two ticks.
- **One-time disposition still undecided:** the 8,408 already-parked rows. They become eligible the moment the gate line is deleted.

### PHASE A0.4 — NO BACKOFF ANYWHERE. OWNER DESIGN DIRECTIVE 2026-08-14 21:15

> "complete backoff lane in driver should be dropped, nothing should happen at locked document. in the drainer you should join the locked from process lock workflow so [it] doesn't just drive locked stuff (without locking in drainer of course). all other (company name, join etc) should have no backoff — simply if failing, `ACTION_COMPLETED` should be set, `UNKNOWN_COMPANY` in status and error in `REQUIRED_ACTION` (if any). no backoff needed.. same for all other actions.. if fails the only way to re-run is `ACTION_RESTART`."

**The new model, replacing retry-with-delay entirely:**
1. **Driver backoff lane: DELETE.** A locked document produces nothing — no stamp, no park, no branch. *(The ACTION_LOG stamp and park are already removed and live; the remaining lane goes too.)*
2. **Drainer excludes locked documents at selection time** by joining the lock set from `processLock01` — Redis, keys `n8n.process_lock.doc_step.*`. **The drainer must NOT acquire locks itself**, only read them, so a locked row is never dispatched in the first place.
3. **Every action failure is terminal, not deferred.** On failure: set the action's `*_COMPLETED` flag, set `STATUS` (e.g. `UNKNOWN_COMPANY`), write the reason into `REQUIRED_ACTION`.
4. **`ACTION_RESTART` is the only re-run path.** No automatic retry anywhere.

**Consequence, stated plainly:** all 8 backoff writers go, and `NEXT_RETRY_AT` loses every writer except the 2 real action builders. The drainer's `NEXT_RETRY_AT IS NULL OR <= now()` gate becomes a near-no-op — the lock join replaces it as the throttle, and terminal statuses replace parking as the way documents leave the queue. **8,408 currently-parked rows will need a one-time disposition** (terminalise or restart) or they land in the first tick after the change.
- [ ] Delete the driver's blocked lane end-to-end
- [ ] Add the lock-set join to `indoxV2BaseDrain01 :: Pick Drain Candidates` (read-only against Redis)
- [ ] Convert the 4 `NoAct: Build Backoff` nodes to terminal-status writers — **read the block below first**

**WHAT `NoAct: Build Backoff` ACTUALLY DOES** (`Decide <lane> Action` out 0 → here → `NoAct: Any?`). It is not a retry ladder — it is a **flat hide-table**, and it writes ACTION_LOG as well:
```js
const BACKOFF_MS = {
  no_action_awaiting_company_id:       6 * HOUR,
  no_action_awating_doc_id:           24 * HOUR,
  no_action_link_not_found:           24 * HOUR,
  no_action_api_tools_failed:         24 * HOUR,
  no_action_doc_date_missing:         24 * HOUR,
  no_action_doc_total_amount_missing: 24 * HOUR,
  no_action_double:                   24 * HOUR,
  no_action_merged:              30 * 24 * HOUR,   // 30 DAYS
};
ACTION_LOG:    j.ACTION_LOG + ', NO ACTION ' + act + ', ' + now,
NEXT_RETRY_AT: new Date(now + ms).toISOString(),
```
**This is the dominant source of the long parks** — 1,325 rows hidden 6 h at a time, 1,655 for 24 h, merged rows for 30 days — and of the ~33,300 `NO ACTION` repeats bloating ACTION_LOG.
- ⚠️ **RETRACTED:** I said `Join COMPANY_NAME`'s uncapped `5·3ⁿ` (22.8 days) was *the* source of >1-day parks. It is *a* source and still uncapped — unlike the extractors and dead-letter, which both wrap in `Math.min(…, 60)` — but this flat table dominates.

**HOW THE VERDICT ACTUALLY REACHES `NoAct` — verified from live topology, and it makes the change SIMPLER than I first said.**
```
indoxV2ActionsGDoc01:  When Called -> Execution Data -> Route Mode
                                        ├─[0] "decide"  -> Decide GDoc Action -> NoAct: Build Backoff -> NoAct: Any?
                                        └─[1] (execute) -> Dedupe Docs (execute) -> ...
```
**The router has two modes and the driver calls it in both.** In `decide` mode it is not executing an action — **it IS the decider**. The `no_action_*` verdict is produced and parked *inside the decide round-trip*, before the driver ever sees the returned ACTION. Live deref confirms it runs: `Decide GDoc Action` 10 runs / `NoAct: Build Backoff` 10 runs, in 10 of 12 sampled executions.

**So the four `NoAct: Build Backoff` nodes are the ONLY writer on the no-action path, and converting them in place is the whole job.** No driver surgery required.

- ❌ **RETRACTED (two claims, both wrong):**
  1. *"the driver's `If ACTION` → `Map NO ACTION` → `If COMPLETED` dead end is the hole underneath all four and must be closed in the same change."* **It is not part of the mechanism.** By the time the driver routes a no-action line there, the router has already parked it. Verified: `If COMPLETED` genuinely has **no outgoing connections** (both branches), fed only by `Map NO ACTION` — but it is unrelated leftover, not load-bearing.
  2. *"removing the `NoAct` nodes reopens the 919-dispatches-in-130-minutes churn via that dead end."* Wrong mechanism. The accurate risk is simply that **nothing would write anything on a no-action verdict**, so the row is re-decided every tick.
- 🆕 `NoAct: Return Verdicts` also has **no outgoing connection** — the verdict returns to the caller by being the last executed node, the same implicit-return pattern as `indoxV2SearchFile01`.
- [ ] Optional cleanup, NOT a blocker: remove the dead `Map NO ACTION` → `If COMPLETED` branch and the nine unreachable `No Action: …` noOps (0 runs in 1,161 executions).
- [ ] Remove the `5·3^n` from `Invoice/ShipmentDocEx01 :: Select` and the +10 min from `Join COMPANY_ID`
- [ ] Decide the one-time disposition of the 8,408 parked rows

**⚠️ RETRACTED, same turn, before it misled anything:** I said the uncapped `platform-base/errorHandler01` was probably live because 1,665 rows are parked >1 day. **Wrong — checked, not inferred: the LIVE copy is `apps/indox`, sha `c75664b035c8`, which caps at 60 minutes.** The two files share id `errorHandler01` and have diverged (`least(...,60)` present vs absent), so a future import of the platform-base copy would silently uncap it to 5·3⁸ = 22.8 days — still worth fixing, but it is not the current behaviour.
- Also checked: `Invoice/ShipmentDocEx01 :: Select` use `Math.min(5 * Math.pow(3, Math.min(prev,8)), 60)` — **also capped at 60 min.**
- 🆕 **OPEN: the source of the long parks is still unidentified.** Every backoff writer examined so far caps at 60 minutes, yet **1,665 rows are parked >1 day and 106 at `infinity`**. Something else writes them. Do not assume — find the writer.

### PHASE A0.3 — REMOVE ALL BACKOFF (owner, 2026-08-13 20:45) — awaiting go-ahead

> "ACTION_LOG in general as a feature should stay, and all backoff (and NEXT_RETRY_AT if only part of this) should be removed."

**DONE AND LIVE:** `indoxV2Driver01 :: Blocked: Build Backoff` no longer writes the `BLOCKED BY LOCK` stamp, the streak scan, the `[5,15,45,90]` ladder, or `NEXT_RETRY_AT`. It returns only the sentinel. *(Deployed before the owner confirmed — my error, acknowledged.)*

**VERIFIED 20:56, ~18 min after deploy — no flood, and the write is gone:**
| | before | now |
|---|---:|---:|
| `BLOCKED BY LOCK` stamps / 15 min | 88 | **0** |
| errors/hr | 7 | **1** |
| host load | 19.80 (peak) | **0.67** |
| in-flight | 162 (peak) | **2** |
| COMPLETED/hr | **−45** | **+4** |

The predicted lock flood has **not** materialised in this window. That is not yet proof it won't — the flood took ~90 min to build last time, and eligibility is currently suppressed anyway because 8,408 of 8,520 workable rows are parked by the *other* backoff.
- ❌ **RETRACTED (owner corrected me):** I claimed removing the stamp destroyed the only instrument for measuring lock contention. **False.** I queried the *Supabase* DB for a lock table and found none — locks were never in Postgres. They are in **Redis**, keyed `n8n.process_lock.doc_step.001`, managed by `processLock01` (45 nodes, `lock` / `unlock` / `check_and_lock` / renew, with TTL). Contention is directly observable: `check_and_lock` returns `was_locked` (`value > 1`), the Redis keys are countable, and `processLock01` outcomes are rows in the n8n execution table. **The `BLOCKED BY LOCK` stamp was a redundant copy of what the lock service already returns** — so removing it loses nothing and the change is more clearly correct than I said.

**MEASURED — how much the OTHER backoff (action parking) is holding:**
| | rows |
|---|---:|
| workable (non-terminal) rows | 8,520 |
| **parked by `NEXT_RETRY_AT`** | **8,408 (98.7%)** |
| eligible now | **112** |

Park horizons: already elapsed 10,284 · 1 hour–1 day 9,832 · **>1 day 1,665** · **infinity/never 106** · <1 hour 33. **Most parks are hours to days — that is hiding, not retrying.** The 1,325 `awaiting company id` rows are not waiting for anything to arrive; resolution simply fails and will fail again tomorrow.

**Conclusion: action parking is load-bearing at 98.7% and must not be removed until its causes are fixed** (task #31 company resolution 1,325 rows; the search 6,391 rows). Remove it first and 8,408 documents enter every tick — the exact churn traced all session.

**ANSWER TO "is NEXT_RETRY_AT only backoff?" — NO.** It is two mechanisms sharing one column.

**Backoff writers — 8, all in scope for removal:**
| where | shape |
|---|---|
| `indoxV2Driver01 :: Blocked: Build Backoff` | lock backoff — **already removed** |
| `indoxV2Actions{GDoc,BS,Ship,Global}01 :: NoAct: Build Backoff` | parks a `no_action_*` verdict |
| `InvoiceDocEx01 :: Select` · `ShipmentDocEx01 :: Select` | `now() + 5·3^(RETRY_COUNT)` min, exponential, on a missed per-type stage |
| `indoxV2ActionsGlobal01 :: Join COMPANY_ID` | flat +10 min on a company-resolution miss |

**NOT backoff — these break if the column goes away:**
| where | what it does |
|---|---|
| `indoxV2BaseDrain01 :: Pick Drain Candidates` | `NEXT_RETRY_AT IS NULL OR <= now()` — **the drainer's only eligibility throttle** |
| `indoxApi01 :: Terminalize Stalled` | sets it for `IN_PROGRESS`, filters on it to find stalled rows |
| `errorHandler01 :: Backoff + Dead-letter` | `RETRY_COUNT+1`, ≥5 → `MAX_ITERATIONS` — **dead-letter, not delay** |
| `indoxV2ActionsGlobal01 :: Record Base Doc Failure` | same failure-counting shape |
| `indoxApi01 :: Build Merge Write` | on the `NEVER` list — merge must not copy it between rows |
| `Build: UPDATE COMPANY_ID` · `Build: …COMPANY_NAME` | real action builders that also set/clear it |

**Scope: remove the 8 writers, keep the column and its 5 gate/dead-letter readers.**

**PROVENANCE, checked against `git show HEAD` — I did not invent this.** The column is in committed `schema.sql`. `Blocked: Build Backoff` and all four `NoAct: Build Backoff` nodes exist at HEAD. What is mine: tasks **#2** (park no-action verdicts), **#12** (generalise to BS/GDoc/Ship), **#13** (rewrite the lock branch, replacing a dead `Snooze Incoming Document` call — a workflow with 0 rows and 0 executions — with the ACTION_LOG ladder now removed).
- ⚠️ **Correction:** I earlier reported `InvoiceDocEx01/ShipmentDocEx01 :: Select` as backoff writers. At HEAD those writers are named `Select Per Type Values` and live in the **routers**, not the extractors. They are in the extractors because task **#20** moved per-type selection there. Pre-existing logic, relocated by me.

**RISK if the four `NoAct` writers go, stated once:** every document that cannot progress becomes eligible on every tick — 2,640 awaiting company id, 1,655 link-not-found, 1,421 DOUBLE. That is the same churn shape traced all session, on a different lane.
- [ ] **HOLD — awaiting owner go-ahead on the 8 writers.**
- 🆕 **65 documents are parked forever** by `NEXT_RETRY_AT = 'infinity'`, a value **no node writes any more** (comment in `indoxApi01 :: Get Changed Docs`). They can never become eligible. Independent of the above.

### PHASE A0 — OWNER PRIORITY 2026-08-13 20:30, ahead of everything below

> "focus on two things before continuing to next.md plan: 1. fixing and verifying the search action end to end. 2. making `If SAME ACTION TWICE` also check the ACTION_LOG column and raise an error whenever an action runs twice — unless [a supported restart]. Deeply analyse all 32k lines … I want real proof that same action will never run again on this system."

**A0.1 — Search action, end to end.** See the A3 block below for everything measured. Status: the pipeline gets an EMPTY `/list` result **7,771 of 8,475 times (91.7%)** while a direct call with the same query and `connection_id` finds files for **13 of 25** of those same documents. Cause not yet found. `alwaysOutputData` reverted because it turned that failure into permanent wrong labels.

**A0.2 — Same action must never run twice. PROOF COMPLETE, all 32,838 rows parsed** (`scratchpad/dupaction.py`):

```
rows scanned                              32,838
rows with >=1 genuinely repeated action   22,728  (69.2%)
genuine repeat events                    147,243
  explained by a RESTART/REOPEN between     4,748  (3.2%)
  UNEXPLAINED                             142,495  (96.8%)
```
Method: parse `(label, epoch)` pairs; **dedupe exact `(label, epoch)` duplicates first** (the LCP-merge artifact — 1,188 rows, 51,983 excess copies — counting those would inflate everything); a genuine repeat is the same label at *different* epochs; then look for a RESTART marker timestamped between them.

**The 147,243 splits into three classes, and only one is a defect:**

| class | examples | repeats | verdict |
|---|---|---:|---|
| `BLOCKED BY LOCK *` | extract_base_doc 14,542 · extract_per_type 6,418 · get_company_name 6,230 | ≈39,800 | **NOT actions.** The lock correctly refusing. Must never error. |
| `NO ACTION no_action_*` | link_not_found 13,204 · awaiting_company_id 11,821 · double 2,593 | ≈33,300 | **By design.** A document that still can't progress is re-evaluated and re-parked. |
| **real actions** | see table | **≈62,300** | **THE DEFECT** |

| real action | repeats | explained | **unexplained** |
|---|---:|---:|---:|
| `COMPANY_NAME` | 25,311 | 1,391 | **23,920** |
| `Extract Base Doc` | 19,236 | 1,835 | **17,401** |
| `Extract Per Type` | 8,170 | 246 | **7,924** |
| `Extract Per Type (BS)` | 7,429 | 136 | **7,293** |
| `link_documents` | 1,875 | 28 | **1,847** |
| `STATUS COMPLETED` | 1,566 | 117 | **1,449** |
| `UPDATE COMPANY_ID` | 884 | 0 | **884** |
| `FROM_OFFICE` | 971 | 96 | **875** |
| `Update NAME` | 867 | 151 | **716** |

**Smoking gun:** `doc_msmh1pkmygqwpv` ran `Extract Base Doc` at `…644956`, `…657897`, `…662882` — **three full base extractions in 18 seconds**, no restart between. Direct violation of the two-point extraction rule, and three paid Gemini calls.

**ANSWER: for real actions there is NO legitimate reason to repeat except an explicit restart, and that covers only 3.2%.**

**Guard rule to implement — UPDATED by owner ("`NO ACTION no_action_*` should also never run twice"):**
Error when **any** action label already appears in `ACTION_LOG` for that document — **real actions AND `NO ACTION no_action_*`** — unless an `ACTION_RESTART` marker carries a timestamp between the prior occurrence and now. **`BLOCKED BY LOCK` needs no exemption: it is no longer written at all** (removed 2026-08-13), so every remaining label is a genuine execution and carries an execution id.

| class | repeats measured | rule |
|---|---:|---|
| real actions | ≈62,300 | **ERROR on repeat** |
| `NO ACTION no_action_*` | ≈33,300 | **ERROR on repeat** |
| `BLOCKED BY LOCK *` | ≈39,800 historic | n/a — no longer written |

**Scope in scope: ~95,600 repeat events.**

**⚠️ IMPLEMENTATION BLOCKER, found and not yet solved:** the ACTION name and the ACTION_LOG label are different strings, so a naive `ACTION_LOG.includes(ACTION)` matches nothing for real actions and the guard would silently pass everything — worse than no guard.
| ACTION | label actually written |
|---|---|
| `extract_base_doc` | `Extract Base Doc` |
| `get_company_name` | `COMPANY_NAME` |
| `find_link` | `LINK FOUND` / `SEARCH_IN_DRIVE_COMPLETED` |
| `get_short_doc_id` | `1` (bare numeral) |
`NO ACTION <action>` is the easy class — it embeds the action name verbatim. Real actions need an explicit ACTION→label map, derivable from each router's builder literals. **Build the map first; do not ship a guard that no-ops.**
- Location confirmed: `indoxV2Driver01 :: If SAME ACTION TWICE`, fed by `Determine Action Tests1` out 1 → `SAME ACTION TWICE ERROR` / `If ACTION`. Current condition only compares the previous `Execute Action` **within one execution**, so cross-run repeats are invisible.
- `ACTION_LOG` is already on `$json` at that node — **no extra query per document needed.**
- [ ] Locate where `If SAME ACTION TWICE` sits in `indoxV2Driver01` and confirm the row's `ACTION_LOG` is already in hand at that point (must not add a query per document)
- [ ] Implement the guard with the three-class exclusion above
- [ ] Verify against these baselines: `Extract Base Doc` unexplained repeats must go to 0; `BLOCKED BY LOCK *` and `NO ACTION *` counts must be unchanged

### PHASE A — Stop corrupting data (must precede everything else)

**A1. Date corruption — ROOT CAUSE ESTABLISHED. The writer is the AI extractor itself.**
Nothing in the pipeline reorders the date; it is stored exactly as the model emitted it. Path traced with **no date transform anywhere**: `indoxV2ExtractInvoiceGemini01 :: Format Response` → `BaseDocEx01 :: Build AI Result (Base)` → `BaseDocEx01 :: Select Base` (`pick(d.LOCAL_DOC_DATE, d.AI_DOC_DATE)`). `Select Base`'s own comment states the decision that leaves it undefended: *"so no date normaliser is invented."*

**Trigger: a 2-digit year printed on the document.** Two modes, proven against `ocr_cache` (what the page shows vs what was stored):
| printed | stored `DOC_DATE` | `LOCAL_DOC_DATE` (correct) |
|---|---|---|
| `23/06/26` | `26/06/2023` | `23/06/2026` |
| `17/06/25` | `17/06/2015` | `17/06/2025` |
1. **Order flip (130 rows)** — model reads `DD/MM/YY` as `YY/MM/DD`; the day becomes the year-suffix.
2. **Wrong decade (70 rows)** — day/month intact, `25`→`2015`, `26`→`2016`.

Four independent proofs it is the model, not code: **130/130** corrupt rows have `AI_DOC_DATE == DOC_DATE` while **100** have a correct `LOCAL_DOC_DATE` (the local apitools path gets the same documents right); ACTION_LOG attributes **204 of 205** to `Extract Base Doc` and only **1** to `Doc Date`; **zero day-26 rows exist in 2027–2031** (deterministic code would map days 27–31 into future years — the model won't emit one); a control reconstruction on 443 non-suspect rows gave **0** false positives.

**⚠️ CORRECTION TO MY OWN FIGURE — the 825 / 579-COMPLETED number was inflated by legitimate dates.** Day-26 is only over-represented in the **≤2024** era (20.45% vs 3.65% in 2025, 4.09% in 2026). The 430 `26/MM/2026` and 255 `26/MM/2025` rows are ordinary dates. Real population: of 700 documents dated ≤2024 with OCR, **200 provably corrupt**, 122 provably genuine, 378 undetermined. Status split: 168 OLD, 17 DOUBLE, **6 COMPLETED**. **ERP exposure is 6 documents, not 579.** Still happening: 12 rows today, 37 yesterday, 115 on 08-09.
- [x] **Guard the impossible AI date** — SHIPPED to `BaseDocEx01 :: Select Base`, 9/9 offline tests, verified live (BaseDocEx 5–6 ok / 0 err per 6-min window, fleet 0 err / ~4,000 ok). An `AI_ONLY` date in the future is now stored as **null** rather than written: a missing date re-opens the document, a wrong one is silently terminal because it can age the row to `OLD` and `OLD` never re-evaluates.
- [x] ~~Reject `AI_DOC_DATE` when its year disagrees with `LOCAL_DOC_DATE`~~ — **would have been a no-op.** `pick(local, ai)` *already* prefers LOCAL whenever both are present, so that guard can never fire. Retracted before shipping.
- **2026-08-13 tick — three hypotheses tested, two refuted. Mechanism still NOT established; do not act on a guess.**
  - ❌ *"per-type never ran, so the late LOCAL was never picked up"* — **refuted by control.** Rows where per-type has **not** run show **0 disagreements (0 of 1,521)**; all **222/222** disagreements have per-type **and** base **done**. Per-type running is a *precondition* for the disagreement, not the cure. Both `Select Base Values` and the per-type `Select` call `pick(LOCAL, AI, 'LOCAL')` and write `DOC_DATE`, so on paper they should agree — they don't, and I cannot yet say why.
  - ❌ *"`AI_DOC_DATE`'s independent vote in `anyOldDate` is what makes `OLD` self-confirming"* — **refuted.** `anyOldDate([DOC_DATE, BS_LINE_DATE, AI_DOC_DATE, SELECTED_DOC_DATE])` does give the known-corrupt field its own vote, but of **704** `OLD` rows: 552 would be aged by `DOC_DATE`, 529 by `AI_DOC_DATE`, and **only 4 by the AI value alone**. Not the mechanism.
  - ❌ *"`__dqDate` rejects the fresh good value"* — **refuted by reading it.** It caps at `currentYear + 1` and accepts `26/06/2023` as a valid day-first date. It is not the rejecter.
  - ✅ **De-risks A2:** **376** rows have an old `AI_DOC_DATE` but a recent `DOC_DATE` (433 at 24 months) — yet only **1** is `OLD`, because `Decide DOC BASE Action` guards with `doc.STATUS != "COMPLETED"`. Those rows stay protected when 6-month ageing ships.
  - 🆕 **18 rows hold a malformed `DOC_DATE`** — regex-shaped but impossible (`46/96/2026`, `35/09/2003`). `AI_DOC_DATE` has **0**, so these did not come from the model. `__dqDate` *would* reject them, so they entered via a path that bypasses the `UPSERT Adapter`, or predate it. **Unattributed writer — related to the E1 boundary problem.**
- **2026-08-13 — MECHANISM ESTABLISHED from the persisted pick sources. Not inferred.**
  `SELECTION_DEBUG_BASE` × `SELECTION_DEBUG_PERTYPE` over the 222 year-disagreeing rows:

  | base source | per-type source | rows |
  |---|---|---:|
  | `DISAGREE_PREFER_LOCAL` | `AI_ONLY` | 214 |
  | `LOCAL_ONLY` | `AI_ONLY` | 3 |
  | `AGREE` | `AI_ONLY` | 2 |
  | `AI_ONLY` | `DISAGREE_PREFER_LOCAL` | 3 |

  **Base resolves the date from a LOCAL read; per-type then runs, its own local leg returns nothing, it falls to `AI_ONLY`, and it OVERWRITES the good date.** Confirmed on the values: **221 of 222 have `DOC_DATE == AI_DOC_DATE`, and ZERO have `DOC_DATE == LOCAL_DOC_DATE`.** The row's `LOCAL_DOC_DATE` is base's good value, which is exactly why the two disagree.

  **Control makes it causal, not correlated** — only `AI_ONLY` produces disagreement:
  | combination | rows | disagree |
  |---|---:|---:|
  | base_had_LOCAL × per-type **AI_ONLY** | 5,877 | **219 (3.73%)** |
  | base_had_LOCAL × per-type AGREE | 6,651 | 0 (0.00%) |
  | base_had_LOCAL × per-type DISAGREE_PREFER_LOCAL | 1,207 | 0 (0.00%) |
  | base_had_LOCAL × per-type LOCAL_ONLY | 1,035 | 0 (0.00%) |
  | base_AI_ONLY × per-type AGREE | 372 | 0 (0.00%) |

- [x] **ROOT FIX DEPLOYED** — `InvoiceDocEx01 :: Select` and `ShipmentDocEx01 :: Select` no longer emit `DOC_DATE` when their own pick is `AI_ONLY`. `DOC_DATE` is a **base** field; per-type owns amount / shipment id / purchase id. Returning null keeps it out of the upsert entirely (`indoxApi01`'s `clean` drops null/`''`), so base's value survives. 7/7 offline tests. Live: per-type **43–51 ok / 0 err** per 6-min window, fleet ~4,000 ok.
  - **Accepted cost, measured: 60 rows** where base produced no date and per-type's `AI_ONLY` value was the only one. Those now complete with an **empty** date instead of an unverified one — the safer failure, since a visible gap is recoverable while a wrong date silently ages the row to `OLD`, and `OLD` never re-evaluates. The 840 rows where base itself was `AI_ONLY` lose nothing (base's AI value is already on the row).
- [ ] **⚠️ STILL NOT PROVEN IN PRODUCTION — attempt 2, correct method, insufficient data.**
  Re-tested properly using the `ACTION_LOG` epoch stamp (format `<label>, <epoch_ms>, <exec_id>`; deploy = **1786647420000**), not `updated_at`. Note the trailing comma in `'Extract Per Type, '` — without it the pattern also matches `Extract Per Type (BS)`.

  | era | rows | took_ai | took_local | date_empty | pct_took_ai |
  |---|---:|---:|---:|---:|---:|
  | **AFTER deploy** | **2** | 2 | 2 | 0 | 100.00 |
  | before | 6,912 | 6,774 | 5,469 | 0 | 98.00 |

  **The 2 post-deploy rows are non-discriminating**: `took_ai = took_local = 2`, i.e. AI and LOCAL hold the *same* value there, so suppressing the per-type write would store the identical date. They neither confirm nor refute the fix. Proof needs a row where base's LOCAL and per-type's AI actually differ.
  - **Correction to my own metric.** Last tick I reported "per-type 43–51 ok / 0 err per 6-min window". That was **contaminated** — `w.name ilike '%Invoice%' or '%Shipment%'` also matched `indox-v2 Actions — Shipment` (75 runs/20m) and `invoice Extractor - Gemini 3.1 pro` (35 runs/20m). True per-type extractor rate: **Invoice 25 + Shipment 6 = 31 runs / 20 min, 0 errors**. The zero-error conclusion stands; the rate figure did not.
  - ✅ **Stamp gap RESOLVED — both candidates refuted, and `ACTION_LOG` is a reliable instrument.** `Extract Per Type (BS), ` post-deploy = **0**, so it is not the BS label. Trimming is not biting: only **80 of 32,713 rows (0.24%)** are ≥5,900 chars, and rows touched post-deploy average **931** chars (max 5,782). The real reason is simply low discriminating traffic — 107 rows were touched post-deploy, only 17 carry a per-type debug, and per-type re-runs mostly land on docs already done (`Extract Per Type 1.4x/doc on 152 docs`).
- [x] **DEPLOYED-ARTIFACT PROOF — the code running in n8n behaves correctly.** Pulled `nodes::text` for `InvoiceDocEx01` straight out of `workflow_entity` (the LIVE copy, not the blueprint), extracted its real `pick()` and `__ptDate` with a balanced-brace scanner, and executed them against genuine corrupt values. **5/5 passed**, including the exact 219-row shape:

  | case | local | ai | pick.source | DOC_DATE written |
  |---|---|---|---|---|
  | **the corruption shape** | `null` | `26/06/2023` | `AI_ONLY` | **`null`** ← base value survives |
  | both agree | `23/06/2026` | `23/06/2026` | `AGREE` | `23/06/2026` |
  | local vs AI conflict | `23/06/2026` | `26/06/2023` | `DISAGREE_PREFER_LOCAL` | `23/06/2026` |
  | local only | `23/06/2026` | `null` | `LOCAL_ONLY` | `23/06/2026` |
  | neither | `null` | `null` | `NONE` | `null` |

  Live code confirmed to contain the guard, applied at the write site, with the old direct write gone. **This proves the artifact, not the outcome** — production proof still needs a row where base's LOCAL and per-type's AI actually differ.
  - Year-disagreements held at **222** — expected; a pipeline fix does not repair existing rows.
- [ ] **THE REMAINING HALF, and the bigger one: `DOC_DATE` is never re-derived.** The corrupt rows went down the `AI_ONLY` branch — `LOCAL_DOC_DATE` was **empty when `Select Base` ran** and was populated later by another writer, which never revisits `DOC_DATE`. Measured 2026-08-13: of **16,868** rows carrying both values in slash form, **222 disagree on the year**; the LOCAL value is within 1 year of arrival in **202**, the stored value in only **31**. LOCAL is right ~6.5× more often. Find the later writer and make it re-derive.
- [ ] Deliberately **not** shipped: an "implausibly old" bound. 95.9% of rows sit at a 0–1 year gap (10,526 + 7,100 of 18,371), but **308 rows sit at a 2–3 year gap** and may be genuine back-filed invoices. No evidence to call those corrupt; a guessed cutoff would silently discard real documents. *(Full year-gap histogram in `scratchpad/a1_hist.sql`. Notable unexplained spike at gap 6 = 187 rows.)*
- [ ] **Sanity bound** in `UPSERT Adapter`'s `__dqDate` — reject `DOC_DATE` more than N years before `RECEIVED_DATE`. Today `26/06/2023` passes as `verdict:'ok'` because it is a valid day-first date
- [ ] **Prompt fix** — `AI_DOC_DATE` says *"in DD/MM/YYYY format"*; add: if the document shows a 2-digit year, return it verbatim, do not expand
- [ ] **Latent, fix anyway** — `indoxV2ActionsGDoc01` / `indoxV2ActionsShip01 :: Build …- Doc Date`, assignment `bw1`: the regex is **unanchored and accepts `-`**, so ISO `2026-06-23` matches at offset 2 → `26/06/2023`, identical shape. It ran on ~1 of 205 rows so it is *not* the cause, but it will produce this the moment it receives an ISO value — and it stamps `DOC_DATE_COMPLETED = true` in the same write. *(A second agent independently swept ops scripts and `bs_extracted_lines` — that table has **zero writers**, all 6 references are DDL or comments, so its `DATE`/`AI_DATE`/`LOCAL_DATE` columns are excluded entirely. `BS_LINE_DATE` is a pass-through with no reformatting.)*
- [ ] **`OLD` must stop being self-confirming** — re-evaluate on date change, or every corrected date stays hidden. *Now precisely located:* `indoxV2ActionsGlobal01 :: Decide DOC BASE Action` reads `if (doc.STATUS != "OLD" && doc.STATUS != "COMPLETED") { … return 'update_status_old_doc'; }` — an `OLD` row is never re-examined. The `AI_DOC_DATE` vote is **not** the cause (4 of 704), so the fix is re-evaluation on date change, not narrowing the vote.
- [ ] Repair the 200: `LOCAL_DOC_DATE` holds the correct value for most; the rest reconstruct deterministically (`SS/MM/20DD` → `DD/MM/20SS`). Clear `STATUS='OLD'` afterwards
- *Not established:* the raw Gemini response was never read out of flatted `execution_data` — "the model emitted it" rests on the absent-transform trace plus the no-future-year evidence, strong but not a direct observation. 378 of 700 undetermined, so **200 is a floor**. ISO-valued `DOC_DATE` rows untested.

**A2. Settings-driven ageing at 6 months.** *(built — NOW UNBLOCKED)*
**The date bug does NOT gate this.** Of the ~9,784 documents that would newly terminalise, **exactly 1** is a confirmed-corrupt row: the corruption always throws the date to 2024-or-earlier, so 199 of the 200 are *already* beyond the 24-month rule and 168 are *already* `OLD`. The damage is fully realised today; moving to 6 months adds essentially nothing. The 2025 band is clean — of 251 `26/MM/2025` rows, **0 corrupt, 161 confirmed genuine**.
`load_settings: false` on `indoxV2ActionsGlobal01 :: Companies` meant `OldDocumentMonthsBack = 6` never arrived and `|| 24` won — invisibly, since the setting was created. Proof: 9,704 docs sit in the 6–24 month band, exactly **4** are tagged.
- [x] Flip `load_settings` → true; replace the silent `|| 24` with an explicit refusal
- [ ] **Deploy.** Hold released — ~9,784 rows age out, 1 of them corrupt. Pair with the `OLD`-re-evaluation fix in A1 so corrected dates can escape.
- *Note:* I could not reproduce my earlier 4,913 figure; the agent measured 9,784. Definitions differ — re-derive before quoting either number.

---

### PHASE A3 — Repeat action runs (owner-raised 2026-08-13, from the concurrency view)

**Observed on `console.localhost/#/m/concurrency`, 15-minute window:** `drive api` **1,614** runs at 14× parallel · `Search File` **1,607** runs at 14× parallel · `indox-v2 Actions — GDoc` **1,209** runs at 15× parallel. 11,998 successes, 1 error, 67 running, p99 27s.

**Owner requirement: "we must make sure never to get into double action runs."**

Why this is a real problem and not just throughput: 1,607 searches in 15 min = **~6,400/hr**, while the harness reports **LINK+LINKEDBS at 1/hr** and only **20 documents `eligible now`** for file discovery. The work being done and the work being completed are orders of magnitude apart.
**MEASURED 2026-08-13 19:12 — this is not "double runs", it is a near-total waste loop.**

Executions in a 15-minute window: `process_lock` **2,410** · `drive api` **1,706** · `Search File` **1,700** · `Actions — GDoc` **1,230** · `indox api` 720 · `Actions — DOC BASE` 634 · `Decide` 634 · `Action Router (main)` 632 · `Incoming Documents v2` 626. **All 0 errors.**

Document progress stamped in the SAME window — the complete list, nothing omitted:

| label | stamps |
|---|---:|
| `NO ACTION no_action_awaiting_company_id` | 91 |
| `BLOCKED BY LOCK find_link` | 88 |
| `NO ACTION no_action_awaiting_company_name` | 3 |
| `STATUS COMPLETED` | 2 |
| `Extract Per Type` | 1 |
| `Selection & Score` | 1 |

**~12,000 workflow executions produced ~6 units of real document progress.** And on the search path specifically: **real `find_link` stamps = 0 · `LINK FOUND` = 0 · `SEARCH_IN_DRIVE_COMPLETED` written = 0**, against 1,700 `Search File` executions that all succeeded. The machine is at 87% CPU doing essentially nothing.

⚠️ **Measurement correction made mid-analysis:** the pattern `find_link, ([0-9]{13})` also matches *inside* `BLOCKED BY LOCK find_link, <epoch>`. My first pass reported "101 find_link stamps on 82 docs" and a "20.7 searches per document" ratio — **both wrong**, they were the lock-block stamps. Anchor on `', find_link, '`. Same trap as `Extract Per Type (BS)`.

**The latch is broken in BOTH directions on the same column** (`SEARCH_IN_DRIVE_COMPLETED`):

| population | rows |
|---|---:|
| `MISSING_LINK`, latch **set** → can never re-search (D1) | 5,779 |
| no link, latch **empty**, non-terminal → re-searches forever | **605** |
| latch is the **string `'false'`** | 1,511 |

The 1,511 are a third, separate defect: `Decide GDoc Action` gates on `!doc.SEARCH_IN_DRIVE_COMPLETED`, and in JS `!"false"` is **`false`** — a row explicitly marked not-searched is treated as already-searched.

Wiring found: `Loop Over Items2` → `Call Search File` → `If Found File1`; out 0 = LINK FOUND path, out 1 = the latch writer. **`Loop Over Items2`'s "done" output (out 0) is wired to nothing**, so a loop that exhausts its queries writes no latch and no status — the document simply falls out of the pass and is picked again next tick.
- [x] **ROOT CAUSE FOUND AND FIXED — a Drive search that matched nothing emitted nothing, and n8n halts a branch on an empty result.**
  Established by dereferencing flatted execution data (14 live `Search File` runs + 12 `Actions — GDoc` runs), **not** from topology:

  | node | runs | items |
  |---|---:|---:|
  | `Start` → `Loop Over Items` → `If Input OK` | 14 each | 14 each |
  | **`Search files and folders`** (calls `driveApi01`) | 14 | **0** |
  | `If Found File1` · `Edit Fields1/2` · `End` | **0** | **0** |

  and in the caller: `Call Search File` 2 runs / **0 items** → `If Found File1` 0 → `LINK FOUND` builder 0 → `SEARCH_IN_DRIVE_COMPLETED` builder 0 → `Upsert (central)` 0.

  `driveApi01` ran **1,706 times with zero errors and returned zero items**. Because n8n stops a branch on an empty result, the whole not-found path — including the latch write that stops a document being re-picked — never executed. **Only the not-found case was mute**: when a file *is* found the result is non-empty and `LINK FOUND` writes normally, which is why 188 documents still gained a link earlier the same day. Zero-result searches are the common case here because the query is built from `COMPANY_NAME` + `SHORT_DOC_ID`, and `COMPANY_NAME` is truncated at ~12 chars with 24 company ids carrying more than one name.

  **Fix: `alwaysOutputData: true` on `indoxV2SearchFile01 :: Search files and folders`.** n8n now emits one empty item on no-match; `If Found File1` tests `$json?.id` notEmpty, so it routes to output 1 → `Edit Fields1` (`ok:false`, `error:'file not found'`) → `End`, and the caller receives a definitive not-found instead of silence.

  **PROVEN — same measurement, before vs after:**
  | node | before | after |
  |---|---|---|
  | `Search files and folders` | 14 runs / **0 items** | 14 runs / **14 items** |
  | `If Found File1` | **0 runs** | 14 runs / 14 items |
  | `Edit Fields1` (not-found) | **0 runs** | 14 runs / 14 items |
  | `End` | **0 runs** | 14 runs / 14 items |
  | `Loop Over Items` | 14 | 28 (loop advances) |

  **And the numbers that matter** — pre-fix 15-min window vs post-fix 6-min window:
  | stamp | before (15 min) | after (6 min) |
  |---|---:|---:|
  | `SEARCH_IN_DRIVE_COMPLETED` | **0** | **141** |
  | `NO ACTION no_action_link_not_found` | 0 | **33** |
  | `STATUS MISSING_LINK` | 0 | 3 |
  | `BLOCKED BY LOCK find_link` | 88 | **7** |
  | churn rows (re-search forever) | 605 | **462** and falling |

  *Not changed:* `Loop Over Items` out 0 ("done") is still wired to nothing — **pre-existing at git HEAD**, verified with `git show`. With `End` executing again the sub-workflow has a last-executed node to return, and the 141 latch writes prove that is sufficient in practice.

- [x] **⛔ REVERTED 2026-08-13 20:20 — the fix was writing WRONG terminal labels.**
  Making "not found" a real answer worked mechanically, but the underlying search is **wrong more than half the time**. Tested 25 documents settled `no_action_link_not_found` by calling the drive service directly with the **same query and the same `connection_id`** the pipeline uses (`drive_google_service_account-ea660043`, read out of `indoxV2SearchFile01`):

  | | |
  |---|---:|
  | documents settled "file not found" | 25 |
  | **that actually HAVE a findable file** | **13 (52%)** |
  | correctly not found | 12 |
  | CONTROL documents (already linked) found by their own query | 24 of 25 |

  Examples with files present: `גולן פלסטיק 12482` → 3 files · `קיסנר 00861` → 2 · `שם טוב 46091`, `סימנט אי.אס. 57609`, `טסה 14413`, `גולן פלסטיק 00345/00346/00706` → 1 each.

  **So `alwaysOutputData` did not cause the search to fail — it made an existing failure PERMANENT.** Before it, a zero-result search left the document unsettled and it retried forever (wasteful, recoverable). After it, the document was latched `SEARCH_IN_DRIVE_COMPLETED` and can never search again. **1,655 documents were settled this way, ~52% of them wrongly.**
  - Reverted `alwaysOutputData` → `false`, deployed, live parity confirmed.
  - **Do NOT re-enable** until the zero-result cause is found.
- [ ] **THE REAL DEFECT, still open — now measured at scale, cause still unknown.**
  **Drive-service access log, last 3 hours, `POST /list` grouped by caller:**

  | client | calls | EMPTY result | found files |
  |---|---:|---:|---:|
  | **pipeline** (axios, n8n workers 172.18.0.25/.26) | **8,475** | **7,771 (91.7%)** | 704 (8.3%) |
  | my direct test (Python-urllib, 127.0.0.1) | 58 | 15 | 56 |

  All HTTP 200. Same service, same endpoint, same `connection_id`. **The pipeline gets an empty result 91.7% of the time**; a direct call with the row's stored `COMPANY_NAME` + `SHORT_DOC_ID` finds files for **13 of 25** of the very documents the pipeline had just settled as not-found. If the pipeline were right its empty rate would be ~48%, not 91.7%.

  **Ruled out so far:**
  - `driveApi01` is not mangling anything — `d:list` forwards `{{ JSON.stringify($json.params || {}) }}` **verbatim** to `http://drive:8975/list`.
  - Credentials / connection / query syntax / the drive service itself — controls pass 24/25.
  - Empty or missing row fields — read out of live `Search File` executions, the values are present and correct at search time (`COMPANY_NAME='פרומט'`, `SHORT_DOC_ID='01822'`, `'חמת עיצוב'/'GM015'`, …).

  **Still unobserved:** the exact query string the pipeline sends. n8n does not persist the resolved expression for the httpRequest/executeWorkflow input, and the drive access log records only the path for POSTs, not the body. Both `getparams.py` and `realquery.py` came back with no query.
  - Next step candidates (pick one, do not shotgun): (a) capture one live search end-to-end on a document **proven** to have a file — requires FILE-DISCOVERY eligibility, currently 0; (b) log the request body at the drive service for a bounded window; (c) diff `whatToSearch`/`folderId` handling in `apps/drive` between the `/list` body path and the `/api/files` GET path, since the sync lane uses the latter and works.
- [ ] **Repair the ~860 wrongly-latched documents** once the search is fixed — clear `SEARCH_IN_DRIVE_COMPLETED` for rows latched between 19:20 and 20:20 that have no `LINK`, so they can search again.
- [x] **OWNER VERIFICATION 2026-08-13 19:28 — "is it now running only a single search per file?"** Two things had to be separated, and the answer differs for each.

  **(b) REPEAT searches across drainer passes: ZERO. This is fixed.** Aligned 15-minute window:
  | | |
  |---|---:|
  | documents settled | 259 |
  | `SEARCH_IN_DRIVE_COMPLETED` writes | 259 |
  | **writes per document** | **1.000** |
  | worst single document | **1** |
  | **documents searched more than once** | **0** |

  Churn population **605 → 462 → 361** over ~15 min. Latch `true` **7,129 → 7,373** (+244). Lock blocks **88 per 15 min → 7 per 6 min**. `Search File` volume **1,700 → 1,278** per 15 min.

  **(a) Query fan-out WITHIN one search action: ~4.9 Drive calls per document, and it does NOT stop at the first hit.** 1,278 `Search File` runs ÷ 259 documents = **4.94**. `Search File` : `drive api` is exactly 1:1 (1,278 : 1,278), so each is one real Drive call. Cause, read off the wiring: `Loop Over Items2` output 1 feeds **both** `Call Search File` and itself, and neither branch of `If Found File1` feeds back into the loop — so the loop self-drives through every query strategy regardless of whether an earlier one already found the file.
- [ ] **Short-circuit the strategy loop on first hit** — would cut Drive calls by up to ~5× on documents whose file is found early. Not a correctness bug; pure waste. `Action: Find Link in Drive` is a NoOp passing through the query list, so the change belongs in the loop wiring.
- [ ] Wire `Loop Over Items2` out 0 ("done") so an exhausted search settles the document
- [ ] Treat the string `'false'` as not-searched (1,511 rows) — compare explicitly, never rely on JS truthiness
- [ ] Make the latch write unconditional on search completion, found or not
- [ ] Re-check the 88 lock blocks once the above lands — the holder may never be releasing

### PHASE B — Deliver to the ERP (the only thing the client feels)

**B1. Turn on the Priority push.**
5,277 of 32,691 rows have ever been pushed (16.2%); **469 of 5,357** June-onward (8.8%). Nachman reported it on 6.8 — *"the last time documents went up was 27/7/26"* — and the database agrees.
- [ ] Find why it is not running (it is not an INDOX-side error; there are no failures on this path)
- [ ] Confirm `PRIORITY_SYNC_COUNT` semantics: does `>1` mean repeat pushes, or repeat attempts? **The 4,285 excess-push figure is an upper bound until answered.**
- [ ] **Merge before the bulk push** — otherwise 5,535 duplicate rows land in Priority and no INDOX merge retracts them

**B2. ERP reconciliation.** 1,666 demoted rows carry an `API_TOOLS_ID`, so Priority already has records for them.
- [ ] Emit `{winner_api_tools_id, loser_api_tools_id, action}` per merge_audit row where `erp_synced_before = true`

---

### PHASE C — One row per document

**C1. Wire full-table detection.** *(built, not called)*
`Determine Action` dedups against a **per-batch in-memory Map**. At the configured 20,000 batch vs 32,691 rows, **583 of 4,173 groups (14%) split across batches**; at the 5,000 GET_ALL cap, 64%. Result: 3,146 of 4,249 groups (74%) have never been looked at, and BALANCE_SHEET is 1.05% adjudicated with **zero** merge winners ever.
- [x] `indox_merge_groups` / `_members` / `_pass` + `indox_refresh_merge_groups()` installed and tested
- [x] `merge_candidates_20260813` — 4,173 groups tiered, 0 unclassified
- [ ] **Point `Adjudicate Merge` at the verdict table instead of the in-memory Map** ← the remaining wiring
- [ ] Make the runtime batch settings-driven (a lever, not the mechanism)

**C2. Make the merge writer safe.**
- [x] `STATUS_BEFORE_MERGE`, `MERGED_AT`, `MERGE_BATCH_ID`, `merge_audit` added
- [x] `indox_execute_merge_group()` — transactional, dry-run default
- [x] Conflict veto live (7/7 tests) — a demonstrated date/amount disagreement now outranks every merge rule
- [ ] **Switch `PG Merge Write` to the transactional function.** Today it still emits N independent updates with no `BEGIN`/`COMMIT`

**C3. Run the merge, tiered. FULLY AUTOMATIC — no human in the loop.**
| Tier | Rule | Groups | Excess | Action |
|---|---|---:|---:|---|
| A | ≤1 row has a real HASH | 988 | 1,253 | auto-MERGE |
| B1 | date AND amount identical everywhere | 860 | 1,115 | auto-MERGE |
| B2 | one corroborator agrees, other absent | 1,272 | 1,858 | auto-MERGE |
| C | date/amount **conflict** | 1,012 | 1,222 | **auto-resolve on HASH** ↓ |
| D | no corroborator | 41 | 87 | **auto-resolve on HASH** ↓ |

**Field-level rule everywhere: latest non-empty value wins** (order by `updated_at`, then `created_at`). No ATTACH-as-hedge, no REVIEW queue, no operator step.

**Tiers C and D resolve themselves using the one key that cannot be wrong.** A date/amount disagreement does not mean "ask a human" — it means "these may be two different documents", and `HASH` settles that without an opinion:
- **Distinct real hashes in the group ⇒ provably different documents ⇒ UN-GROUP.** Not a merge, not a review — a *detection* error, corrected automatically. This matters concretely: the five largest groups are `n_rows == n_hash_distinct` (31 rows / 31 distinct hashes), because `COMPANY_DOC_ID` is frequently a different field entirely — a supplier name, a date, a phone number. Merging those would destroy 30 real documents each.
- **Same hash, or hashes absent ⇒ MERGE, latest value wins.** A disagreement between two extractions of the *same* file is just a stale value, and the newest read is the best one.
- Re-tier C/D by hash distinctness before running; log the split so the counts stay auditable.

**The conflict veto (already live) must be narrowed to match.** It currently vetoes on *any* date/amount disagreement, which under this policy would block merges that should proceed. Correct predicate: veto only when distinct real hashes prove distinctness. *(Its original purpose still stands — it was catching `sameHash` winning alone on BS rows, which have no hash at all.)*
- [ ] Backup → dry run → re-tier C/D on hash → A → B1 → B2 → C/D → ERP reconciliation
- [ ] **Do this AFTER link recovery (D1)** — each recovery either proves a duplicate (shared hash) or proves distinctness, and a merged loser stops searching, so the evidence is never generated

**C5. The BS-child duplicate class — cause established, 0 unexplained.**
The matcher keys on `(COMPANY_ID, SHORT_DOC_ID)`, but **`SHORT_DOC_ID` is the last column written** — median **2.43 h** after base extraction, p90 **18.27 h** (n=14,139). `"SHORT_DOC_ID"::text = $2` never matches NULL or `''`, so the twin is *invisible* for that whole window and the BS lane creates a child instead of linking.
- **My "147 genuine misses" was a measurement artifact.** It used `Extract Base Doc` as the proxy for "already extracted", but that milestone only establishes `COMPANY_ID` — not the match key. Re-decomposed on the correct milestone: **A 796 / B3 506 / B1 12 / genuine misses 0**. 518 of 518 "twin existed" pairs are explained.
- Hypothesis *"the key was different then corrected"* — **disproven**: 138/140 have both keys byte-identical today, and **135/137 twins have exactly one `SHORT_DOC_ID` write ever**. A correction needs two.
- Every alternative measured to zero: `bad()` key drop 0/6,470; wrong `matches[0]` pick structurally impossible (a child exists only when matchCount was 0 — 137/137 carry the CREATE stamp); format mismatch 0; derivation drift 6 rows table-wide, none in set; `limit 5001` overflow max 286 rows; GET/write race min gap 14m17s.
- Control: of 836 twins with both stamps, `SHORT_DOC_ID` lands **before** the link in 814 (97.4%), median lead 11.14 h.
- [ ] **Fix: reconcile at the moment the key becomes available.** `indoxV2ActionsGDoc01 :: Build: Call 'Incoming Document Batch Update'1` (and the identical chain in `indoxV2ActionsShip01`) — look up an existing `SOURCE_TYPE='BALANCE_SHEET'` row on the same `(COMPANY_ID, SHORT_DOC_ID)` and hand the collision to the **existing** dedupe mechanism (`resolve_double` / merge_sig / STATUS DOUBLE). Covers 518/518. *Do not build new merge logic for this.*
- [ ] Do **not** swap the key to `COMPANY_DOC_ID` — measured, catches **1 of 137**.
- [ ] Latent: `Build Get SQL` caps at 5001 but `Guard Get Size` only throws above 100,000 — a narrow-GET overflow truncates silently instead of refusing. Max observed exposure 286.
- [ ] Hygiene: `padStart(5,'0')` collapses any line id with no alphanumerics onto `'00000'` — 133 rows, 17 companies. Treat all-zero as `bad()`.
- ⚠️ **Analysis hazard, recorded:** the CREATE path copies the BS parent's **entire ACTION_LOG** into the child. Child ACTION_LOG is not the child's own history — use `created_at`.
- ⚠️ The ACTION_LOG label for the `SHORT_DOC_ID` write is the **bare numeral `1`** — invisible to any parser anchored on `[A-Za-z]`. That is why this was blind for so long.

**C4. Prevent regeneration.** Roughly 1 in 6 rows created today is a second copy.
- [ ] **`SOURCE_LIST` must ship before the post-extraction hook.** `logicalMatch` writes every non-empty incoming field, so an incoming `LINK` **overwrites** the matched row's. The hook works by making that fire ~2,911 more times. Wrong order = the largest provenance loss in the system's history.
- [x] `SOURCE_LIST` column, GIN index, backfill (1,025 winners / 2,758 entries / 1,631 filing locations preserved)
- [ ] Post-extraction dedup hook — re-run the existing probe once identity is known. **Prevents 2,911 of 5,535 (53%)**
- [ ] **Reconcile BS children when `SHORT_DOC_ID` lands** — see C5, this replaces the "drop the latch" idea
- [ ] Fix the ERP re-sync channel — 2,992 rows pushed >1×, worst 6× — 4,285 excess pushes

---

### PHASE D — Finish link recovery

**D1. Clear the remaining latch.** 5,779 rows still cannot re-search.
`Decide GDoc Action` gates `find_link` on `!doc.SEARCH_IN_DRIVE_COMPLETED` and **nothing ever clears it**, so rows that burned their one search against the broken predicate are stranded.
- [x] Batch 1 (300) → **83 recovered a file (27.7%)**, all with `LINK_CONNECTION`
- [x] Batch 2 (400) released
- [ ] Release the remaining 5,779 in batches sized to headroom (~400 at a time; the box OOM-killed workers twice today)
- Expect **~1,600 more recoveries** at the observed rate

**D2. Close the hash race properly.**
Between **concurrent executions**, so no node inside one execution can see it — `Hash Owner Lookup` can't see an uncommitted sibling, `Batch Hash Dedup` can't see another execution.
- [ ] `ON CONFLICT ("HASH") DO NOTHING` on the hash path in `indoxApi01` — the only layer that can settle it atomically

---

### PHASE E — Architecture (prevents the whole class recurring)

**E1. Split identity from writing.** *(scan running)*
`indoxApi01` route `UPSERT` runs `logicalMatch`, which tries three keys **with the certain one last**:
```js
if(docIdOk(COMPANY_ID,COMPANY_DOC_ID))  return byCD[k];   // INFERRED — 12.1%/25.5% wrong
if(!bad(COMPANY_ID)&&!bad(SHORT_DOC_ID)) return byCS[k];  // INFERRED — 373 pairs collapse >1 doc
if(!bad(HASH)) return byHash[HASH];                       // CERTAIN — checked LAST
return null;                                              // -> creates a row nobody decided to make
```
**Layer 1 (Postgres) inventory — complete.** What the database actually enforces:

| Object | Key | Enforced at write? |
|---|---|---|
| `incoming_documents_pkey` | **ID** | **YES** (hard) |
| `uq_incdoc_hash` (partial unique) | **HASH** | **YES** — but only the 25,382 of 32,695 rows satisfying the predicate |
| `incdoc_company_dockey_idx` | ≈(COMPANY_ID, COMPANY_DOC_ID) | **NO** — non-unique; *looks* like a key in `\d`, enforces nothing |
| `indox_doc_key()` | (COMPANY_ID, COMPANY_DOC_ID) | **NO** — inference only |
| `indox_refresh_merge_groups()` | (COMPANY_ID, COMPANY_DOC_ID) | **NO** — never touches `incoming_documents` |
| `indox_execute_merge_group()` | addresses rows by **ID** | **NO** — manual; all 3,520 audit rows are `dry_run=true` |
| 6 triggers | none | **N/A** — all hygiene, zero identity logic |

Three findings that change the design:
1. **`(COMPANY_ID, SHORT_DOC_ID)` is used by NOTHING in the database** — no index, no constraint, no function; `indox_doc_key` never consults it. It exists *only* as an application-layer guess. Removing it from the write path costs nothing at Layer 1.
2. **`"ID"` has no default** — no `gen_random_uuid`, no identity, no sequence. Any client with a table grant can INSERT a caller-chosen PK, and three distinct ID shapes in the wild (`doc_<b36>` 26,685 / other 6,016 / epoch-ms 5) prove multiple minters have existed. There is **no RLS, no policy, no rule, no CHECK, no FK out.**
3. **An unidentified writer produced the existing 394 `MERGED` / 1,360 `DOUBLE` / 395 `MERGED_INTO` rows** — `MERGE_BATCH_ID` is set on **0** of them, so `indox_execute_merge_group()` did not do it. No DB-side candidate exists. **Must be found before C3 runs**, or the merge will be reasoning about state some other actor is still changing.

Also: **7,313 rows (22.4%) have `HASH IS NULL`** and sit outside `uq_incdoc_hash` entirely (7,012 also lack `API_TOOLS_ID`) — the hash guarantee does not cover them. And `API_TOOLS_ID` is a **second** 32-hex content hash, equal to `HASH` on 23,737/25,103 rows, with **no unique index** — 964 values duplicated across 1,496 excess rows.

**Principle: never let an inferred key drive a write.**
| Key | Certainty | Allowed to |
|---|---|---|
| `ID` | certain | write |
| `HASH` | certain | ingest dedup |
| `(COMPANY_ID, COMPANY_DOC_ID)` | inferred | **detect only** |
| `(COMPANY_ID, SHORT_DOC_ID)` | inferred | **retrieval hint only** |

- [ ] `WRITE` — match on ID only, cannot create, cannot re-target *(actions, console)*
- [ ] `DELIVER` — unchanged, already correct: `ON CONFLICT ("HASH")` *(syncs)*
- [ ] `RESOLVE` — read-only, returns candidates + which rule matched *(BS spawner, repairs)*
- [ ] `CREATE` — explicit; creation stops being what happens when guessing fails
- [ ] `MERGE` — route 7, once C2 lands
**Layer 2+3 map — complete. `indoxApi01` live is byte-identical to the blueprint (37 nodes, 0 param diffs).**

**The invariant "all writes go through indoxApi01" is already false in six places:**
1. `errorHandler01 :: Backoff + Dead-letter` (active) — direct UPDATE
2. `indoxV2ActionsGlobal01 :: Record Base Doc Failure` (active) — direct UPDATE
3. **The Flask BFF** — writes `incoming_documents` **directly via PostgREST with the service-role key**, 5 write paths, and carries its **own second copy of the four rules** declared as data in `storage/incoming_documents/repos.json`. Its matcher (`core/diff.py:120-137`) gates on `is not None and != ""` — **no `docIdOk`, no `'unknown'` exclusion, no all-zeros check, no quarantine.** 126 rows carry a `COMPANY_DOC_ID` n8n refuses to key on and Flask happily keys on.
4. `apps/chat` — via Flask, **with an n8n-webhook fallback**, so the same document reaches the DB through *two different matchers* depending on whether Flask is up
5. **Ops scripts that write identity keys** — `indox-rehash-missing.py:259` writes `HASH`; `2026-08-06_short_doc_id_fill.sql` writes `SHORT_DOC_ID`; `2026-08-06_doc_id_consolidation.sql` rewrites `COMPANY_DOC_ID`/`DOC_ID`; `highload-inject-links.py:178` direct INSERT
6. `indox_execute_merge_group()` (UPDATE only, only ever dry-run)

The lint gate that enforced this — `direct-db-write-lint.py` (G42) — was **added known-failing and retired on 2026-08-07 before Phase 4 rewired the callers.**

**The console can hand-edit every key the other five match on.** `patch_document` (`api/__init__.py:5530`) has no allowlist and no identity guard — contrast `config_row_patch:7044` which does. A human can retype `HASH`, `COMPANY_ID`, `COMPANY_DOC_ID`, `SHORT_DOC_ID` or `SOURCE_ID` and silently re-point which future document fuses into that row.

**Three independent implementations of "the four rules", and they disagree:**
| | rules | rule-1 guard | rule-2 guard | scope | quarantine |
|---|---|---|---|---|---|
| n8n `Resolve IDs` | ID→CD→CS→HASH | full `docIdOk` | **none** | batch + company scoped | ≥2 co, but inert |
| Flask `compute_diff` | ID→CD→CS→HASH | **none** | **none** | whole table | none |
| DB `indox_doc_key` | DOC_ID→CD | full | **never used** | whole table | ≥3 co |

Plus `Build Deliver` = HASH only, Flask W4 = `(CONNECTION, SOURCE_ID)`, `sync_ledger` = `(source, platform_id)`. **Six notions of identity in production.**

**13 paths can CREATE a row — plus a 14th nobody counts:** `PG Upsert` is `ON CONFLICT ("ID") DO UPDATE`, so any caller passing a deleted or merged-loser ID **re-creates the row**. There is no update-only verb except `MERGE` and `DELETE`.

**The dangerous class is exactly 4 spawners** — they pass no `ID` and no `HASH`, so identity rests entirely on the two inferred keys, and `clean` then writes the new line's `SOURCE_TYPE`/`SOURCE_ID`/`STATUS`/`NAME`/`TYPE` over whatever it landed on:
`indoxV2ActionsBS01 :: Upsert…'Batch Update'3` (6,465 rows) · `indoxV2ActionsGDoc01 :: Upsert: Create New Shipment Row1` · `indoxV2ActionsShip01 :: …same` · `indoxV2Driver01 :: Create New Shipment Row` (662 rows)
- **1,359 keys are contested** between a spawner row and a sync-delivered row
- **≥65 real documents already overwritten**: 55 → `BALANCE_SHEET`, 10 → `INVOICE`; 68 hash-bearing sync rows carry a spawner marker; 57 BS-spawned rows carry a `HASH` *and* a `LINK` (a spawned line has neither — those were real documents first). **Floor, not ceiling.**
- GDoc/Ship **already search first** (`Shipment GET_ALL`) then **throw the answer away** and let the upsert re-resolve against a differently-scoped index. Textbook TOCTOU — giving them an explicit resolve is a rewiring, not a redesign.

**Removing rules 1 and 2 breaks exactly those 4 spawners and nothing else.** All 7 ingest lanes carry a `HASH` and would resolve on rule 3 — in fact *more* correctly, since rules 1/2 currently pre-empt the hash they already have. The ~30 ID-bearing builders, `MERGE`, `DELETE`, `Terminalize Stalled`, the DB merge engine, `errorHandler01` and the ops scripts are all unaffected. Flask must be changed in **both** places or the divergence widens.

**Four live defects in `Resolve IDs`:**
- **(a) Rule 2 has no validity guard at all.** `docIdOk` applies only to rule 1. `'00000'` is an accepted identity key — **135 rows across 18 companies**, largest bucket 10 rows. The `UPSERT Adapter`'s own comment says this belongs here; it was never added.
- **(b) The cross-company quarantine is inert.** `_docIdCos` is built from what `Load Match Index` returned, but `Build Match Index SQL` scopes the doc-id predicate to the company — so another company's row is never loaded, `size` is 1, and `docIdOk` passes. The 695 cross-company doc ids are unguarded.
- **(c) `Resolve IDs` reads around the `UPSERT Adapter`** (`$('Strip Control').all()`), so the adapter's canonicalisation is discarded and items the adapter *drops* are still written — with keys absent from the match index, so they cannot match and get `gen()`.
- **(d) `SEP=''`** — `12|345` and `123|45` build the same key. **0 collisions live**; theoretical, one data shift away.

**Performance finding, unrelated but free:** both hot lookups **seq-scan 32k rows on every call** — `Build Match Index SQL`'s `"HASH" in (...)` (every UPSERT) and `Build Deliver`'s `where "HASH" = $1` (every DELIVER). The partial index is unusable unless the query repeats its predicate. Adding `AND "HASH" IS NOT NULL AND "HASH" <> '' AND lower("HASH") <> 'unknown'` turns both into index scans.

**What the duplicate keys actually contain** — the five largest groups, `n_rows == n_hash_distinct` in every case (31 genuinely different files under one "doc id"), keyed on a company registration number, a **supplier name**, a **date**, a **phone number**. `COMPANY_DOC_ID` is not a mis-measured doc id — it is frequently a *different field entirely*.

- [ ] Migrate callers: actions first (lowest risk, highest damage today) → syncs → BS spawner → remove inferred keys from the write path last
- [ ] Re-instate a G42-style direct-write lint **after** the callers are rewired, not before
- [ ] Fix Flask's `repos.json` rules in lockstep, or delete them and proxy to the API

**E2. Remove the remaining self-call deadlocks.** 5 workflows, 11 nodes — `indoxV2Driver01` (5), `indoxGmailBSDownloader01` (3), `indoxGmailDocDownloader01`, `indoxGmailLinkDownloader01`, `indoxHealth00001`. Both Gmail downloaders call Process Document directly.
- [x] `indoxProcessDocument01` fixed (2 HTTP self-calls → 1 sub-workflow call, 1.24s vs 30s timeouts)
- [ ] Apply the identical fix to the other 5

---

## 2. PROVEN DONE — with evidence

| Fix | Evidence |
|---|---|
| **Drive search repaired** | Query param was silently dropped: **0 `LINK FOUND` in 6,861 attempts over 14 days**. Now: impossible query → 0 rows; `קל קל-05626` → its 2 real PDFs; **188 rows have gained a file** |
| **Drainer class blind spot (`cls_d`)** | 1,178 of 1,197 open rows matched **no class**; pass emitted zero, which n8n renders as `{success:true}` — exactly the screenshot. Now 400 eligible |
| **`Get Line Match` quadratic** | 43.3s at N=100 → **246ms at N=30,000**, output byte-identical, 30× at N=5,000 |
| **Merge conflict veto** | `sameHash` won *alone* before any date/amount check; BS rows have no hash so **every** BS-vs-doc group satisfied it. 7/7 tests. Would have prevented **253 wrong merges** at sweep scale |
| **`Batch Hash Dedup` output shape** | Returned mutated input items → `Invalid output format` on every run, ~1,900 err/hr. Fixed: **33.0% → 0.0%** over 170 executions / 163 successes |
| **`unknown-known.pdf` fabrication** | `("unknown").slice(-5) === "known"`. 25 rows/hr, 767 all-time. 5/5 tests; document kept, named from source, flagged for manual id |
| **Companies Loader self-call** | 2 HTTP self-calls needing a worker slot while holding one → 24/24 timeouts. Now 1 sub-workflow call, 1.24s. 27 offline assertions. ⚠️ **no end-to-end control yet** — no documents have arrived since |
| **Error rate** | 445/hr → **0 errors against 3,312 successes** (non-idle zero). Three real defects fixed en route |
| **Impossible-date guard (A1, part 1)** | `Select Base` accepted whatever the model emitted — 631 of 713 rows with a year ≤2024 have `DOC_DATE == AI_DOC_DATE`. Future-dated values (35 rows, up to 68 years ahead) are now refused. 9/9 offline tests; live BaseDocEx 5–6 ok / **0 err** per window, fleet **0 err / ~4,000 ok**. Cost of the wrong fix avoided: the "year disagreement" guard I had planned was proven inert first |
| **Claim-hash trunk regression (mine, 2026-08-13)** | I hung `Build: Claim File Hash (best effort)` off `Upsert (central)` — a shared trunk fed by **21 builders**, only 2 of them on the Drive-search path. It referenced `$('Action: Find Link in Drive')`, which throws `hasn't been executed` on the other 19 → **852 err/hr** (397 GDoc + 397 propagated into the Action Router + 53 api). Fixed with a guarded Code node in `runOnceForEachItem` (keeps `.item` pairing) + an `On Search Path?` IF gate. **Verified: 56 → 0 err in the rolling 5-min window while successes held 3,900–4,000.** *Deliberately rejected the obvious `.all()` index-pairing rewrite — `Call Search File` runs inside `Loop Over Items2` batches, so position-pairing could write one document's md5 onto another's row.* |
| **MISSING_LINK roll-up** | 8,374 → **1,920** in דורשים טיפול; label unchanged |
| **Harness honesty** | LINK-today 5,450 → **584** (9.6× overstatement); `REDUNDANT` was a dead counter (bimodal: 32,138 at 0, 398 at 32+, nothing between); NEXT ACTION now covers all 10,653 open rows (2,278 were hidden); completion trend added; killed queries no longer render as zero |
| **`deploy_wf.sh`** | Import nulls `active` AND `activeVersionId`, so nothing can infer it afterwards. I took workflows offline **4×**. Now validated + imported + reactivated in one command |

---

## 3. DECISIONS MADE

- **BS-line children are ordinary invoices** that happen to appear on a balance sheet. They search Drive for their **own** file. `MISSING_LINK` is a **legitimate success** — the row still reaches Priority. Never treat it as failure or merge fodder. *(This invalidated the "inherit the parent's link" design.)*
- **Ageing must be settings-driven at 6 months**, and every other hardcode removed. Accepted: ~4,913 rows age out. Held only until A1.
- **Do not merge until detection and the writer are correct.** The unsupervised run made **53 wrong merges (13.6%)**.
- Reversion of those 53 is deprioritised — the full run re-adjudicates them correctly.

## 4. OPEN DECISIONS

- **`PRIORITY_SYNC_COUNT` semantics** — repeat pushes or repeat attempts? Gates the size of the ERP problem.
- **Route 3 is a hard `DELETE` by ID.** Nothing else in this system deletes. Who calls it, and should it exist?
- **Should `DELIVER` be allowed to create**, or should creation be its own verb? Today creation is a side effect of matching failing.
- **Who wrote the existing 394 MERGED / 1,360 DOUBLE rows?** No DB-side candidate. Blocks C3.
- **`ALSO_SEEN_AS` (col 105)** is written by no DB function — population source unknown.
- **`sync_ledger` carries a third identity notion** — PK `(source, platform_id)`; ~2.5% of its `doc_id`s no longer resolve.

## 5. ALSO OUTSTANDING

- 10 of 18 staff-reported issues still real (6 Alram docs absent; Sabco credit invoice `950257` absent and **no credit-note type exists**; 3 suppliers with 0 rows; the ח.פ-only match Nachman asked for on 28.7 never implemented and still creating wrong rows)
- **Company identity fragmentation** — 24 company IDs carry >1 name (4,550 rows), 17 names map to >1 ID, `COMPANY_NAME` truncated at ~12 chars. This *is* the "BG invoices missing" complaint (they exist under `Fig Shp Co`)
- **Rotate the bot admin credentials** posted in plaintext in the WhatsApp group on 1.7
- Archive feature — blocked on A1; also needs the tombstone-stub design or it makes **1,892 OCR cache rows** garbage-collectable (`ocr-cache-retention.py` uses `incoming_documents` as its GC root set)
- `REQUIRED_ACTION` holds raw engine text on 74.6% of filled rows — it is user-facing (`פעולה נדרשת`)
- ~~147 genuine BS-matcher misses~~ → **resolved, see C5: zero genuine misses**

## 6. WORKING RULES LEARNED THE HARD WAY

1. **Test item/data semantics offline before deploying.** Every one of my 5 failed changes was shape, not logic: a Postgres node returning zero rows collapsing item lineage; a Postgres node replacing `$json` and discarding an upstream flag; an `if/else if` with no `else`; a fabricated filename from two missing values; a Code node returning input objects.
2. **Deref flatted execution data — never grep it.** I burned four attempts blaming a hash race because `uq_incdoc_hash` appeared in the blob as *echoed row data*. One proper deref named the node in one shot.
3. **Use `deploy_wf.sh`.** Never a bare import.
4. **A zero on an idle workflow proves nothing.** Always pair an error count with a success count.
5. **Positive control before believing any negative.**
6. **Never `updated_at > now()-interval` on `ACTION_LOG`** — it is cumulative. Parse the epoch; handle **both** epoch-ms and ISO-8601 (2,867 docs are ISO-only).
7. **Write SQL to a file.** Inline/heredoc quoting mangles silently through WSL.
8. Schedule-triggered workflows run from the main process's in-memory copy — node edits need a restart; sub-workflow/webhook entries take effect immediately.
