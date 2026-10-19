# final-indox.md — proof-driven completion plan

Every line below is either **PROVEN** (with the query/measurement that proves it) or **OPEN**
(with the exact acceptance proof required). Nothing is marked done on a report alone — today
produced three claims that dissolved when checked, so the rule is: a claim without a live
measurement is OPEN.

Measured at DB clock `2026-08-06 20:01` UTC. Sections A10–A21, B11–B15 and C6–C9 added and
independently re-verified at DB clock **`2026-08-07 05:33`**; A22–A30, B16–B20 and **Section E**
added and re-verified at DB clock **`2026-08-07 07:06`**. Every figure below carries the clock it
was taken at, and where a proof no longer reproduces that is said in the proof cell rather than
quietly kept.

**FINAL-STATUS re-verification pass, DB clock `2026-08-07 11:36`–`12:01` UTC** (A33–A40, B21–B29,
and fresh numbers throughout): re-checked ten claims reported as "completed tonight" independently
of this file, ran genuinely fresh `gdoc`/`pipeline`/`sync_kernel`/`doc_base` suite executions,
pulled the live current state of all 7 suites, and independently re-derived the two-point
extraction plan's remaining Part-C claims (selection coverage, value-parity, legacy-extractor
dependency counts, coverage %). **All ten of the "completed tonight" claims hold** — two
(`mailLabelEngine01`'s interleaving proof and the "Get a message" 404 fix) were wrongly marked as
not reproducing in a first pass through this file, caught and corrected on a second, independently
prompted check (see the note after A39/A40, and A35/A39 themselves) — recorded rather than quietly
fixed, because a caught false negative is exactly the kind of thing this file's own rules exist to
surface. **One previously-reported figure central to the lock-in decision (the 4-row/0-row
legacy-extractor dependency count) genuinely does not reproduce** (B27) — ⚠️ **that correction has
itself been withdrawn on 08-09: the 4/0 figure was right and reproduces exactly; B27's re-derivation
had gated on the wrong flag. See B30 for the reconciliation, and E3 — this is the second
correction-of-a-correction in this file, both caught the same way, by re-deriving instead of
re-citing.**
This pass also surfaced two new, previously undocumented findings live in `gdoc`/`pipeline`
themselves (B21, B22/B23) that tonight's code changes did not anticipate.

**BOTH-LEGS re-derivation pass, DB clock `2026-08-09 13:33`–`13:57` UTC → see B33.** The owner
enabled `extraction_ai_enabled` at **`13:32:05 UTC`**, so for the first time in this deployment's
history the AI half of two-point extraction has produced output, and the STANDING CAVEAT that
qualified B26/B27/B29/B30/B31 no longer holds for rows processed after that instant. Every figure
in those sections has been re-derived with both legs live, in place, with superseded numbers struck
rather than replaced. **The load-bearing one did not move: the legacy-extractor dependency is still
`COMPANY_ID = 4` / `TYPE = 0`**, now reproduced under **four** independent population gates spanning
244 → 5,750 rows and **two samples 18 minutes apart**, with a structural argument (B33.4) for why
enabling a second extraction source can only ever lower that count, never raise it. Three things
this pass found that were not being looked for: a **bulk `UPDATE` at 12:44 that set
`BASE_EXTRACTION_COMPLETED` on 4,583 documents which never went through two-point** — invalidating,
for the third time in this file, the population gate a headline was standing on (B33.2, E3); and
**two live defects in the selection step** (B33.6, B33.7), one of which makes the AI-vs-local TYPE
disagreement rate unmeasurable at any sample size. The AI-leg sample is **37 rows** — enough to
settle the deletion question, explicitly **not** enough to publish an agreement rate, and B33.1 says
what threshold would be and why 37 is not it.

---

## A. PROVEN — done, with the evidence

| # | item | proof |
|---|---|---|
| A1 | **Two-point extraction is live and running** | `BaseDocEx01` 783 runs · `InvoiceDocEx01` 142 · `ShipmentDocEx01` 64 · `BsDocEx01` 27, all last-run within 2 min of 20:01 |
| A2 | Company resolution 2.1% → 86% | 144 docs / 97 ground-truth: answered 50→86.1%, recall 63.9→85.6%, p50 1549→29 ms. Live path proof: 6/6 correct on documents the old query resolved none of |
| A3 | Duplicate writer works | `resolve_double` fired 140× · violation groups **288 → 122** · 144 `MERGED` tombstones · 0 dangling pointers · 164/164 restorable from backup |
| A4 | Ledger-claim bug fixed | `sync_attempt` drive rows **0 → 94** (mechanism had never once fired) · 8 live RELEASE calls proven taking the no-op branch |
| A5 | Two-digit years no longer age documents out | live node runtime: `07/07/26`→2026 current (was 1926 OLD), `01/01/80`→1980 OLD, `31/12/25`→2025 OLD |
| A6 | OOM class fixed | root cause 2479×3506pt pages → 150.9 MP/page at 300dpi; pixel clamp fires (proven on a 3rd unrelated file); weighting unified on rendered MP |
| A7 | Deleted client data restored | 2,382 rows restored, 4,176 → 6,558 · 94/94 post-backup rows bit-identical · 21 legitimately-merged rows correctly withheld · 31 dangling `MERGED_INTO` → 0 |
| A8 | Delete guard live | `syncV3SourcesTest01/Cleanup SQL` now doc-side `SYNC_NAME like 'sv3s\_%'` + anchored uid; verified in `workflow_entity`, `nodes moved: NONE` |
| A9 | Test suites cannot fire | all 8 test/reset workflows `active=false`, re-verified after every push. **Re-confirmed 08-07 05:33 against live n8n:** `select count(*) filter (where active) from workflow_entity where name ilike '%Test%' or ilike '%Reset%'` → **0 active of 13** |
| A10 | **Fix 2 — the fixture counters were keyed on a column the writer never sets** | Four counters in `syncV3SourcesTest01` re-keyed from `"SOURCE_ID"='sv3s_pg_src'` to `coalesce("SOURCE_LINK",'') like '%sv3s\_pg\_src'`. Discriminating measurement: `OLD → 0 rows`, `NEW → 10` and `NEW → 1`. End-to-end: `proc-bs` **6/9 → PASS 9/9**. Re-confirmed statically 08-07 05:33 — exactly **4** anchored `SOURCE_LINK` predicates, in `PG Row` + `PG W1 Watch` (`sv3s\_pg\_src`) and `PV Row` + `PV W1 Watch` (`sv3s\_pv\_src`); **0** old-form `"SOURCE_ID" = 'sv3s_pg_src'` predicates remain outside `Cleanup SQL`, which is a DELETE and correctly keeps equality (see D). *The 9/9 itself is not re-runnable while the suites are disabled — see B3.* |
| A11 | **PB anchor fix — the 2026-08-06 incident's read-side twin** | `syncV3SourcesTest01` `PB Row` + `PB W1 Watch`: `position('#inbox/'\|\|l.platform_id in "SOURCE_LINK")>0` → `coalesce("SOURCE_LINK",'') like '%#inbox/'\|\|l.platform_id`. Measured at the time: **2,385 rows → 1 row**. That exact query no longer reproduces — its `sv3s_pb_%` ledger rows have since been cleaned up and **both** forms now return 0 — so the standing proof is the structural one, re-measured live 08-07 05:33: the shortest `platform_id` in `sync_ledger` is **1 character** (of 1,308 rows), and for that uid the unanchored form matches **2,391 of 2,391** documents carrying `#inbox/` while the anchored form matches **0**. A one-character uid under `position()` is a whole-table join |
| A12 | **G58 extended from DELETE to UPDATE** | Self-test **15 → 21 cases, 21/21 passing** (re-run 08-07 05:33). Scope analysis starts at `where`, so `set "SYNC_NAME"='sv3s_x' where "STATUS"='OLD'` correctly FAILS instead of letting the SET clause rubber-stamp F4; UPDATE joins on `from` not `using`; a no-`WHERE` UPDATE gets its own F4 message. Proven against the real defect, not a paraphrase: the incident's join was injected into the live `HD Terminalize` node in `syncV3FullTest01` → green → FAIL `[F2]+[F3]` naming that file and node → restore → green, reported byte-identical at `sha256 fbdd3925…`. **That hash is not re-confirmable now** (the file has moved on under another lane; it hashes `a126fe7c…` at 05:33), so the byte-identity is recorded as measured-at-the-time. Gate re-run 08-07 05:33 over the working tree: **G58 PASS across 81 blueprints**, 35 non-blocking warnings. One allowlist entry: `indoxApiSupabase01/Build Merge Write` — single-row `where "ID" = $N`, invisible to F4 only because the column name comes from a `q('ID')` quoting helper, recorded with its reasoning in `scripts/test-fixture-prefixes.yaml` rather than by weakening F4 |
| A13 | **New standing rule, binding in `GATES.md`** | *"A read may reason from containment. A write may not."* — `scripts/refactor/GATES.md:164`, under the heading at `:139`. Verified present 08-07 05:33. Also recorded in D below |
| A14 | **`normalizeDocType(d.TIPE)` named a column that has never existed** | The type dimension was single-sourced because `d.TIPE` is always `undefined` — the column is `TYPE`. Re-keyed to `LOCAL_TYPE` in both clone routers. **543 null-fills, 0 changed, 0 cleared.** Re-confirmed 08-07 05:33: `d.TIPE` survives in `indoxV2ActionsGDoc01` / `indoxV2ActionsShip01` **only inside the explanatory comment** (`WAS d.TIPE -- a column that has never existed`); every live call site is `normalizeDocType(d.AI_TYPE)` or the `LOCAL_TYPE` expression in A17 |
| A15 | **`select_invoice_values` was an orphaned action** | No decide function had emitted it since the v2.1 state-machine rewrite, while the handler, the switch case, the `indoxV2Driver01` self-test and every fixture oracle still expected it. Restored in `gdocTail` behind two **measured** guards (`STATUS !== 'COMPLETED'`, `PRIORITY_SYNC_COMPLETED !== true`): **26 gdoc / 17 ship rows**, every move *into* the new action, **0 livelock, 0 sync-flag resets**. The wide variant — same restoration without the guards — would have woken **427 / 419** already-settled rows. Both guards verified present in the blueprint 08-07 05:33 |
| A16 | **The writer overwrote rows the selector had skipped** | **4,790** skipped rows reached the writer; **4,789** of them held `SELECTED_*` data it would have nulled → **0**. Same node: `$json.ID` replacing `.item.json.ID`, because once items are filtered, index-based item pairing no longer lines up. Corroborated live 08-07 05:33: `count(*) where "PRIORITY_SYNC_COMPLETED"::text='true'` = **4,790**, the same cohort size |
| A17 | **BS-line cohort was type-blind by construction** | `SELECTED_DOC_TIPE` was 0/213 for the BS-line cohort, which has no extractor legs at all. Fixed with a **cohort-scoped** fallback — `normalizeDocType(has(d.LOCAL_TYPE) ? d.LOCAL_TYPE : (d.SOURCE_TYPE === 'BALANCE_SHEET' ? d.TYPE : null))`, verified verbatim in both routers 08-07 05:33 → **213/213**, **0 effects outside the cohort**. The *global* `LOCAL_TYPE \|\| TYPE` fallback was **rejected on measurement**: its 23 certainty-0 flips are **0 inside the cohort and 23 outside**, all of one shape — `TYPE=INVOICE / LOCAL_TYPE=null / AI_TYPE=BALANCE_SHEET` — which is a genuine AI-vs-ledger conflict, not weak evidence. That population is **live-confirmed at 24 rows** on 08-07 05:33 and is owner-owned (C7) |
| A18 | **Selection-path fixes are deployed, not just staged** | Live n8n at 08-07 05:33: `indox-v2 Actions — GDoc` and `indox-v2 Actions — Shipment` both `active=true`, `updatedAt 08-07 05:21`, both carrying `select_invoice_values` **and** `LOCAL_TYPE` in their deployed node JSON |
| A19 | **The "chaos" was a cadence mismatch, not a race** | `syncLedgerApi01/Reaper Schedule 5m` is `minutesInterval: 5` (300 s) **and** `Reaper PG Stuck` is age-gated on `claimed_at` older than `Math.max(1, Number(j.timeout_min)\|\|15)` minutes — both re-read from the blueprint 08-07 05:33 — so the real worst-case wait is **~20 minutes against a 60-second watch**. Proven by polling `sync_ledger` every 5 s: the poison row reads `claimed` at every sample with `att=1` throughout, while the healthy document goes `claimed → delivered` in ~6 s on **both** passes. **The quarantine gate is correct; this was a test defect** |
| A20 | **`knownPins` is sound — the alarming ratio was a display artifact** | Verified in `indoxV2GDocTest01` 08-07 05:33: pins are read (`j.knownPins = j.knownPins.filter(...)`); a **mismatching pinned row goes to `pinned`, not `fails`** (`pinned.push(...) else fails.push(...)`); and the verdict reads only `fails.length`. `gdoc` declares two pins, `gdx_shp3` and `gdx_ord2`, both present. So the `gdx_shp3` OCR mis-read **never failed the suite** — check 5 was red from *non-pinned* rows with null `selected_*`. The "0/15 identical" figure is the `passed` ratio, which counts pinned rows as not-passed |
| A21 | **G41 provenance and severity, both corrected** | Measured HEAD-vs-worktree 08-07 05:33 across all three routers: HEAD carries **0** occurrences of `no_action_double`, `no_action_merged` and `__terminalGuard`; the worktree carries `__terminalGuard` **0 → 2** and the two action names 0 → 3 each. `indoxV2ActionsBS01` shows the **identical** finding in a file the selection lane never edited — so this is uncommitted `resolve_double` work, **not** the selection change. Severity corrected too: all three switches declare `fallbackOutput` → a `Stop and Error - Unhandled ACTION` node (present in all three), so an unhandled ACTION fails **loudly**; and `indoxV2Driver01`'s `Switch1` allow-list names both actions and routes them to DOC BASE. **Latent, not live** |
| A22 | **The selection path is confirmed by a real document, not just by the diff** | `doc_msie37pv6zm2yd`, read live 08-07 07:06: `LOCAL_TYPE=invoice`, **`AI_TYPE` null**, `SELECTED_DOC_TIPE=INVOICE`, `TYPE=INVOICE`, `STATUS=COMPLETED`. **The null `AI_TYPE` is what makes it decisive**: under the old `d.TIPE` operand — a name that resolves to `undefined` — and with no `AI_TYPE`, the type dimension had *no source at all*, so `SELECTED_DOC_TIPE` could not have been populated. It is. *One qualification recorded rather than smoothed over:* the reported action sequence `select_invoice_values → mark_completed` does not appear in that shape. The row's full `ACTION_LOG` is `AI values (DOC BASE)` → `Mark Invoice Completed1` → `Selection & Score` → `STATUS COMPLETED` — the selection label follows the completion label rather than preceding it. `Selection & Score` is emitted by `Build: Batch Update - Selection & Score`, the `select_invoice_values` handler, so the action **did** fire; only the ordering claim is unsupported |
| A23 | **Chaos fixed at the cause, which was arithmetic** | `Reaper Schedule 5m` (300 s) sits *behind* the age gate of A19, so the honest worst case is ~20 min against a 60 s watch — no scheduler can close that. Fixed by driving the RELEASE op directly: `{op:'RELEASE', source:'sv3f_chaos', all:true}`, verified verbatim in `syncV3FullTest01.json` 08-07 07:06. **`all:true` is load-bearing** — without it `Build Release` reads an empty `ids[]` as a deliberate no-op and returns success having done nothing (see E1). Result: `chaos` **2/8 → 8/8**, watch clearing in **5 s**; `sync_full` **3/6 → 4/6** |
| A24 | **n8n 2.17 publishes; it does not save-and-run** | `workflow_entity.nodes` is the **draft**. An *active* workflow executes `activeVersionId → workflow_history.nodes`. A `PATCH` to the draft returns **200 and deploys nothing** — which is why a "deployed" reading taken off `workflow_entity` can be entirely fictional. Measured fleet-wide live 08-07 07:06: **68 active, 68 identical, 0 drifted** (`join workflow_history h on h."versionId" = w."activeVersionId"`, comparing `nodes::text`) — so `bbox n8n push` publishes correctly. Inactive workflows have no published version and run the draft, which is why the suites are the exception to this rule |
| A25 | **`active=false` was never a disable**  🔴 the most dangerous finding of the cycle | `WorkflowRepository.getActiveIds()` is `where: { activeVersionId: Not(IsNull()) }` and `LiveWebhooks.executeWebhook()` never reads the `active` column at all. `halt-tests.sh` cleared only `active` — and its list was **11** against a real set of **13** — while `tVzFMkz18pCsXRyw`'s blueprint *also* declared `"active": true`, so every push re-armed it. Both halves fixed. Re-measured live 08-07 07:06: `active` column **68**, `activeVersionId is not null` **68**, of 86 total, and the query for rows where the two columns disagree returns **zero** — instance-wide two-column drift **0**. Test/reset workflows **armed: 0 of 13**, now measured on the column that actually gates execution |
| A26 | **Two agent-invented workflows found armed, and disarmed** | `indoxDataGateway01` and `indoxIdentity01` — created by this project's own agent lanes, **rejected by the owner, never executed** (`execution_entity` count re-measured live 08-07 07:06: **0**, all-time). Both still carried an `activeVersionId`, and the gateway still held a registered **`POST indox-data-gateway`** — a live, servable endpoint every human-facing surface reported as off. Disarmed under backup in the order backup → null `activeVersionId` → remove registration; `POST /rest/workflows/<id>/activate` deliberately never used, because it is n8n's **arm** verb. Re-confirmed live 08-07 07:06: both `active=f` **and** `armed=f`; `webhook_entity` rows matching gateway/identity: **none** (18 registrations remain instance-wide). Artefacts and reasoning in `data/_attic_agent_drafts/README.md` |
| A27 | **G58 extended again, from UPDATE to INSERT** | Self-test **21 → 34 cases, 34/34 passing** (re-run 08-07 07:06; the runner splits them `21 mutation, 13 creation`). This closes the exact channel B13 named. `insert_known_unmarked` is **`[]`** — verified in `scripts/test-fixture-prefixes.yaml:251` — i.e. emptied by the sites being fixed, not by being waived. Proven the same way as the other two extensions: a real defect injected into a real node, watched fail, restored byte-identically |
| A28 | **Five gates were never wired into `run-gates` at all — G58 among them** | Root cause is a one-directional containment check: CI asserted `GATES.md ⊆ ci-verify.yml` and **never the reverse**, so a gate could be written, documented and self-tested while running nowhere. This is E2's shape, and it is the reason a green board proved less than it appeared to. Wiring re-verified 08-07 07:06: `fixture-delete-scope-lint` (G58), `dead-fallback-lint` (G59) and `one-branch-guard-lint` (G60) are all present in `run-gates.py`. **`published-drift-lint` (G61) is still not wired anywhere** — see B17 |
| A29 | **G42 and G43 retired — they mandated the rejected design** | Both gates required routing through `indoxDataGateway01` / `indoxIdentity01`, the two workflows of A26, so neither could ever go green *and going green would have been the wrong outcome*. Removed from four wiring sites, including a second gate runner carrying its own `KNOWN_RED` list. Verified 08-07 07:06: `GATES.md` keeps both rows as annotated tombstones (`RETIRED 2026-08-07 — see "Two gates retired" below`), `run-gates.py:65` records the retirement, the `ci-verify.yml` steps are gone, and the artefacts sit in `data/_attic_agent_drafts/` (`direct-db-write-lint.py.retired-20260807`, `single-identity-lint.py.retired-20260807`) under a README whose stated purpose is "so nobody re-derives a retired rule from a stray file" |
| A30 | **Three new gates, each proven able to fail** | **G59 dead-fallback** — self-test 6/6; live run finds exactly **1** across the fleet: `syncV3Deliver0001 / Proj Kind`, whose `Label Req` branch nothing can reach. **G60 one-branch-guard** (the B15 lint, now built) — self-test 7/7; live run finds exactly **1**: `indoxV2GDocTest01 / Batch Config`, where `ids` is assigned a string literal so the guarded body never runs and nothing errors. **G61 published-drift** — self-test 5/5, including the case that matters most, *"no database is reported as NO VERDICT, never as a pass"*. All three self-tests re-run 08-07 07:06 |
| A31 | **`bs` `SKP03 duplicated (2)` diagnosed — a fixture defect, and it hid two dead branches** | The fixture seeds `COMPANY_ID "C1"` but points `LINK` at a **real** Drive document, so base extraction runs and overwrites `C1` with the resolved company; the linker then searches the wrong id and creates instead of matching. Per the real rule — `(COMPANY_ID, COMPANY_DOC_ID)` — there is **no violation**: the assertion is weaker than the rule it stands in for. `UPD02` has the identical shape, so **the BS update and skip branches had never once executed**. A green that was measuring nothing |
| A32 | **Three fabricated invoices removed from a real client's table** | Company `511744898`. Removed under backup (`sha256 a3d3781e…`, explicit `"ID" IN (…)`, never a predicate), **3 → 0**, with both genuine rows verified present by id afterwards. Re-confirmed live 08-07 07:06: that company now holds exactly **2** rows, `1779009319599fi2l5t` and `doc_mshy1s9wfka4l3`, both `COMPLETED` — matching "both genuine rows present" exactly |
| A33 | **BS clobber guard — fixed, live, and the corrupted row repaired** | `indoxV2ActionsBS01.json` / "Decide DOC BASE Action" (`bsDecide`) carries a `[guard 2026-08-07]` block: `if (doc.API_TOOLS_ID && !doc.PER_TYPE_EXTRACTION_COMPLETED && doc.BS_EXTRACTION_VERIFIED !== true && doc.STATUS !== 'COMPLETED') return 'extract_per_type'`. The incident it closes, per the fix's own comment: doc `17711145495219ioglt` — 38 lines summing to 218031 — had `TOTAL_AMOUNT` silently overwritten to 200855 on 2026-08-06 while `STATUS` stayed `COMPLETED`; 134/136 `COMPLETED` BS docs were exposed at measurement time. **Live-landed**: `indoxV2ActionsBS01` `active=t`, `activeVersionId=af1ae6de-95c9-4231-8f2a-a75cc9b8f945`; the guard string, the incident doc id, and `__terminalGuard` (the paired `resolve_double` stale-reassertion fix) are all present in the *published* `workflow_history.nodes` for that version, and were already present as far back as version `34b6885c` (09:35:07) — live well before the 10:28:09 batch push. **Corrupted row repaired, re-confirmed live**: `17711145495219ioglt` now reads `TOTAL_AMOUNT=218031`, `BS_EXTRACTION_VERIFIED=true`, `PER_TYPE_EXTRACTION_COMPLETED=true`, `STATUS=COMPLETED` — matching the original correct value. **Suite proof, with a positive control**: `indoxV2BSTest01` execution `387205` (09:59:18–10:00:45) → `✅ ALL TESTS PASS`; an *earlier* run of the same suite, execution `327774` (03:12:57), ended `status=error` — the suite demonstrably can and does fail, this isn't a check that only ever reports green |
| A34 | **`syncV3Main0001` registry-key silent-fallback-to-production — fixed, and it was as serious as reported**  🔴 | Node "Registry Req" read `$input.first().json.registry_key` — but `Registry Req` sits five hops downstream of the trigger (fed by `Stamp Run Start`), so `$input` was never the trigger payload; a caller-supplied `registry_key` (e.g. a suite scoping itself to a fixture registry) was silently never read, and the node fell through to the hardcoded default `'sync_registry'` — the **live client registry** — every time. Fix reads `$('When Called').first().json` directly and **throws rather than defaulting** if a supplied `registry_key` isn't usable; the `sync_registry` default now only applies when there truly was no trigger payload. **Live-landed**: `syncV3Main0001` `active=t`, `activeVersionId=843518b8-c69d-485d-b022-4a8bf25691eb`, carrying `NO SILENT FALLBACK` / `READ THE TRIGGER, NOT` in the *published* `workflow_history.nodes`, present as far back as version `e7c0e735` (08:09:47). **Live proof the bug fired in production before the fix**: `syncV3FullTest01` execution `366368` (07:16:33–07:30:53, `canceled`) reconciled real production pipe names under the suite's own lock — `{"gmail-doc":167,"mail-private":311,"drive-gdoc-chat-export":354,"drive-gdoc-scanned":355}`, 1,192 real ledger deliveries touched under a test's decoy lock. **Live proof the fix closed it**: post-fix execution `385555` (09:45:50–09:52:15, `success`) shows the same `mixed` check now scoped only to `sv3f_mx_drive`/`sv3f_mx_gmail` fixture names, **0** production deliveries. `final-indox.md` never named this bug before this pass (grepped for `registry_key`, `sv3f_registry`, `sync_registry`, `366368` — zero prior hits) |
| A35 | **`mailLabelEngine01` loop-order bug — fixed and live, and the "three independent interleaving reconstructions" framing DOES reproduce — corrected after a re-check, see the note after A39** | Node "Batching 1" (`n8n-nodes-base.splitInBatches`) fanned its loop-drain output back to itself *before* n8n scheduled the work lane ("Start Gmail Item"), by canvas position — the loop drained every batch before any labeling work ran, silently (the workflow still reported success). Confirmed with the repo's own gate, `scripts/refactor/n8n-loop-order-lint.py` (G45): run against committed HEAD → `LOOP DRAINED BEFORE WORK` naming this exact node; run against the current working tree (Batching 1 moved to `[-96, 432]`) → `G45 PASS — all 107 blueprint workflow(s)`. **Live-landed**: `mailLabelEngine01` `active=t`, `activeVersionId=06148062-…`; the published `workflow_history` node position is `[-96, 432]`, and a full-text compare of `workflow_history.nodes` against the draft returns identical. **Positive-controlled live proof, pulled directly from `execution_data.resultData.runData[*].executionIndex` (n8n's own dispatch-order ledger), not simulated**: two pre-fix executions (`332684` 03:30, `336370` 04:00) show `Batching 1` at indices `17,18,19,…,27` — **all 11 loop iterations back-to-back** — with `Start Gmail Item` only starting at index `29`, after the drain fully completed. Three post-fix executions (`388031` 10:15, `388270` 10:30, `388274` 10:30) show `Batching 1`/`Start Gmail Item`/`Get Gmail Thread`/`Lable Engine`/`If Should Apply`/`Add / Remove Label`/`Agg Add Labels`/`Add label to message` strictly alternating one full 8-node work cycle per `Batching 1` call, zero drain-first runs across all three. This is a stronger and more direct proof than the G45 static check alone — a real before/after contrast, live, in production dispatch order |
| A36 | **NEEDS_REVIEW infinite redrive loop — fixed and live** (the "before/after retry-rate measurement" proof does not reproduce — see A38) | `syncLedgerApi01`'s new reaper (`Reaper Schedule 5m` → `Reaper Build Stuck` → `Reaper PG Stuck` → `Reaper Build Release` → `Reaper PG Release`) previously compared attempt count against a **hardcoded 5** instead of the per-call `max_attempts`; per the fix's own comment, max attempts ever recorded on this deployment is 3, so the quarantine branch had never once fired, and a stuck claim was released and redelivered forever. A sibling bug in the same file: `RELEASE` with an empty `ids[]` used to mean "release everything a source holds" (re-dispatch factor 2.5–5×), now requires explicit `all:true` (this half already documented at A23). Fix resolves `max_attempts` via the same registry join as `Quarantine?` and quarantines into `sync_ledger.status='needs_review'` once the true max is hit. **Live-landed**: `syncLedgerApi01` `active=t`, `activeVersionId=22215f3d-…`, published nodes contain `Reaper Build Release`/`needs_review`, identical to the draft. **Live positive evidence of correct post-fix behaviour**: `sync_ledger` row `incoming-documents-main/sv3f_chaos/sv3f_ch_bad1` reads `status='needs_review'`, `claimed_at=NULL`, `delivered_at=2026-08-07 09:49:17` — the reaper-quarantine signature, from today's chaos run; `sync_attempt` shows `max(attempts)=3` across 160 rows, bounded, not unbounded |
| A37 | **Drive-identity 400 in `syncV3FullTest01`'s registry mirror — the specific 400 is fixed and live; the suite it lives in is still red for a different reason (see B25)** | The mirror that copies real `sync_registry` entries into a test registry dropped the drive-identity fields — drive-kind pipes carry identity as `connection`, gmail-kind as `drive_profile_id` — so a mirrored unit resolved `null` and hit `apps/drive/app.py`'s `_explicit_connection_required()` guard (itself dated 2026-08-06, closing a *different*, prior incident where a missing profile/connection id resolved silently to whatever connection happened to be bound). Fix stamps `drive_profile_id:'admin'` for gmail-kind and live-resolves the drive connection via `GET http://drive:8975/connections` for drive-kind. **Live-landed** (per the active/draft rule — `syncV3FullTest01` is `active=f`, so its **draft** is what a manual run executes): the draft carries the `DRIVE IDENTITY (2026-08-07)` marker and the `/connections` resolution call. **Behavioural check**: the two most recent live runs (execution `385555`, success; execution `373748`, success) show **zero** `_explicit_connection_required`/400-identity errors in their execution data — the specific defect this fix targets is not occurring on either. **But** — see B25 — the same two runs still fail their `registry` and `mixed` checks, for an unrelated reason (`gate.delivered` stuck at 0) |
| A38 | **Bad-file-id fix in the three Gmail downloaders — fixed and live** | `SOURCE_ID` (documented as "the drive file id / gmail message id") was populated from the wrong field in all three: BSDownloader used `balanceSource` (a source label, not an id), DocDownloader used the **sender's email address** (`from.value[0].address`), LinkDownloader also used the **sender** (`Code in JavaScript`'s `.from`). Fixed to read the actual Gmail message id in each (`Gmail Message`/`Loop over documents`/`Get a message`'s own `.id`). **Live-landed, confirmed against the published version, not the draft** (all three active): `workflow_history.nodes` for each contains the corrected `SOURCE_ID` expression verbatim, all sharing `activeVersionId`/`updatedAt = 2026-08-07 10:28:09.713+00`. Corroborated independently: `apps/mail/mailapi/local_app.py`'s new `BadMessageId` guard documents the same defect class at production scale — *"the live pipeline called POST /labels/add with {'id': 'person52@example.com', ...} — a MAILBOX ADDRESS where a hex message id belongs (`incoming_documents.SOURCE_ID` holds the sender address on 2,298 GMAIL rows)"*. Still genuinely open, unaffected by this fix: `final-indox.md` §B18 — the three gmail suite lanes still *assert* the old sender-based expectation and will read red for that stale reason until their assertions are rewritten |
| A39 | **"Get a message" transient-404 fix — fixed and live** (corrected after a re-check — an earlier pass of this file wrongly reported no evidence; the fix is real, just in a different file than searched — see the note below) | The node named "Get a message" that carries this fix lives in `apps/mail/blueprint/n8n/mailLabelEngine01.json` (an `executeWorkflow` call to `gmailApiImap01`), **not** the identically-named `executeWorkflow` node in `indoxGmailLinkDownloader01.json` (which is unrelated and unchanged). Fix: `onError:"continueRegularOutput"` added to "Get a message", feeding a new `If` node **"Fetch OK?"**, which routes a failed fetch to a new no-op **"Skipped - Fetch Failed"** — its own `content` field states the design directly: *"transient search miss or a genuine 404 ... deliberately left UNLABELLED here — the engine's own search already excludes labelled messages, so this item is picked up again on the next 15-minute tick. No action needed; this is the self-heal path, not an error state."* **Live-landed, confirmed against the published version**: `mailLabelEngine01` `active=t`, `activeVersionId=60b66c58-bf5d-4709-a7c5-1ce72dec1e6c`; published `workflow_history.nodes` — 37 nodes, node-name set and order byte-identical to the repo file — contains `Get a message`/`Fetch OK?`/`Skipped - Fetch Failed`, `onError=continueRegularOutput` on `Get a message`. **Positive-controlled live proof**: execution `329761` (03:15, before the fix) has no `Fetch OK?` node in its `runData` at all; execution `388270` (10:30, after) does, immediately following `Get a message` in dispatch order (`executionIndex` 3→4) |

**Correction note (A35/A39) — a first pass through this file wrongly marked both A35's interleaving proof and the "Get a message" fix as false negatives; both were re-checked and both are real.** The error, and how it was caught: the first pass searched for the literal node name "Get a message" only inside the three Gmail-downloader blueprints and the `mailapi` call chain it assumed the fix lived in, and it checked `mailLabelEngine01`'s loop-order bug only against the static G45 gate, never pulling the workflow's own live `execution_data.resultData.runData[*].executionIndex` — the exact dispatch-order ledger the "interleaving reconstruction" method uses. Both gaps were the same shape: verifying inside an assumed-relevant file list instead of a scope wide enough to catch a same-named node in a different file, and verifying "was a gate written for this" instead of "does live execution data show this." A second pass, prompted by an independent live check that found `mailLabelEngine01` was the real location, re-ran both checks correctly (results now folded into A35 and A39 above) — a live before/after execution-index contrast for the loop order (pre-fix executions `332684`/`336370` show `Batching 1` draining 11-in-a-row before any work runs; post-fix executions `388031`/`388270`/`388274` show clean one-cycle-per-batch interleaving), and a live node/version check that located "Get a message"'s real home in `mailLabelEngine01` rather than `indoxGmailLinkDownloader01`. Recorded here rather than silently overwritten, per this file's own rule that a correction is written down, not smoothed over (see E3).

| A40 | **Selection-after-extraction live in all 4 real routers** (refines A18 — the "5th file" is the driver, which by design does not select) | Live at DB clock 12:01: `indoxV2ActionsGlobal01`/`GDoc01`/`Ship01`/`BS01` are all `active=t` with the **published `workflow_history` version identical to the draft, zero drift**, all touched `2026-08-07 10:28:09`. All four carry a `[two-point STAGE 1 2026-08-07] ROUTER-OWNED SELECTION STEP` node with its own `SELECTION_DEBUG_BASE`/`SELECTION_DEBUG_PERTYPE` oracle — a mechanism newer and broader than A18 recorded (A18 only checked `select_invoice_values`/`LOCAL_TYPE`, which correctly read `f` on BS since BS has no invoices/TYPE ambiguity and selects `LOCAL_DOC_DATE`/`LOCAL_DOC_AMOUNT` instead). `indoxV2Driver01` correctly has zero selection nodes of its own — it dispatches, it doesn't select, matching A21 |

**B26 — value-parity: "proven clean, zero substantive mismatches" holds for the *raw* two-point values, not for the *post-selection final* values** — the claim needs correcting, not just re-citing. Live re-derivation, non-fixture rows: `COMPANY_ID` vs `LOCAL_COMPANY_ID` (raw base value) is genuinely **0/525** mismatched, and `TYPE` vs `LOCAL_TYPE` (raw base value) is genuinely **0/660** — the strongest form of the claim is true. But `COMPANY_ID` vs `SELECTED_COMPANY_ID` (the actual final output) is **7/5424 (0.13%)** mismatched, and `TYPE` vs `SELECTED_DOC_TIPE` is **30/430 (7.0%)**. The 30 `TYPE` mismatches are all `TYPE=INVOICE` vs `SELECTED_DOC_TIPE∈{BALANCE_SHEET,SHIPMENT,ORDER}` with `LOCAL_TYPE` null — the same shape as the already-known, still-open C7 AI-vs-ledger conflict population (24–34 rows there), not a new problem. The 7 `COMPANY_ID` mismatches include **6 not previously flagged anywhere**: `LOCAL_COMPANY_ID` exactly matches the legacy `COMPANY_ID` while `SELECTED_COMPANY_ID` took the `AI_COMPANY_ID` value instead — a real selection-logic disagreement on 6 live documents.
**Acceptance proof:** the 6 new `COMPANY_ID` disagreements are triaged (selection bug vs. genuine AI-vs-local conflict), and the value-parity claim is re-stated to distinguish "raw extraction is clean" from "final selected output is clean" — they are not the same claim and this file should not treat them as interchangeable again.

⚠️ **SUPERSEDED IN PART by B33 (re-measured 2026-08-09 13:39 UTC with the AI leg LIVE).** Every figure in the paragraph above was measured on a one-legged mechanism. Re-derived on the same queries, same fixture exclusion: `COMPANY_ID` vs `LOCAL_COMPANY_ID` ~~0/525~~ → **0/751, still exactly clean — the AI leg did not change this answer**. `TYPE` vs `LOCAL_TYPE` ~~0/660~~ → **8/972, and this one DID change** (7 are `TYPE='UNKNOWN'` against a populated `LOCAL_TYPE`, 1 is `INVOICE` vs `balance_sheet`) — see B33.5. `COMPANY_ID` vs `SELECTED_COMPANY_ID` ~~7/5424~~ → **8/5587** (the same 6-row `570042077`/`516431434` cluster, unchanged, plus one row whose `SELECTED_COMPANY_ID` holds a company *name* rather than an id). `TYPE` vs `SELECTED_DOC_TIPE` ~~30/430~~ → **31/592**. The genuinely new measurement this section could never make — LOCAL vs AI head-to-head — is in B33.5, and it is **not yet publishable at n=20**.

**B27 — ~~the legacy-extractor "true dependency" figures (COMPANY_ID 4 rows, TYPE 0 rows) do NOT reproduce~~ → RECONCILED by B30 on 08-09. THE 4/0 FIGURE WAS RIGHT; THIS ENTRY WAS THE ERROR.**  ⚠️ correction-of-a-correction, recorded in place per E3
The 08-07 re-derivation below gated its population on **`AI_EXTRACTION_COMPLETED='true'`** and called that "base extraction actually ran". It is not. That flag is written by `Build: Call 'Incoming Document Batch Update' - AI values (DOC BASE)` (and its per-type twins in `indoxV2ActionsGDoc01`/`Ship01`) — i.e. by the **legacy Gemini action `extract_invoice_google_ai`**, not by two-point base extraction, which stamps `BASE_EXTRACTION_COMPLETED` in `Select Base`/`Select Base Values`. Measured live 08-09 09:11 UTC on the non-fixture fleet: `AI_EXTRACTION_COMPLETED='true'` = **4,042** rows, of which **3,487 have never been through two-point base extraction at all**. So the table below describes the legacy-AI population, not the two-point population, and its "true dependency" column is not a legacy-per-value-extractor dependency count at all. The 08-07 entry compounded that by never distinguishing *"came out of two-point unresolved"* from *"the legacy extractor then resolved it"* — 165 of the rows it counted had already had the legacy extractor run and find nothing, so deleting that extractor changes nothing for them. Superseded table, kept for the record, **do not cite**:

| dim | ~~base-extraction ran~~ (actually: legacy-Gemini ran) | two-point fully unresolved | rescued by existing fallback | ~~true dependency~~ |
|---|---|---|---|---|
| COMPANY_ID | 3972 | 74 | 19 | ~~36~~ |
| TYPE | 3972 | 36 | 9 | ~~27~~ |

**The reconciled figure is 4 (COMPANY_ID) / 0 (TYPE), and it reproduces exactly** — see **B30**, which states the population gate, the provenance instrument (`ACTION_LOG`, which none of the three prior measurements used), the fixture exclusion including the `NAME` sweep, and the per-row proof that base extraction ran *before* the legacy extractor on all 4. The "treat the larger number as operative" instruction issued here is **withdrawn**: it was based on a population-gate mismatch, and the larger numbers were counting rows that do not depend on the legacy extractors.
**Acceptance proof: MET by B30.** ✅

**B28 — shipment INVOICE_ID gap: confirmed real, confirmed still open, not closed** — `indoxV2ActionsShip01`'s live, published `shipmentDecide(doc)` has **zero** INVOICE_ID handling (`invoiceDecide(doc)` has `if (!doc.INVOICE_ID && !doc.INVOICE_ID_COMPLETED) return 'query_invoice_id';`; the shipment function has no equivalent anywhere). The new selection step's own live code makes the gap explicit under its own `[gap-2]` tag: *"INVOICE/ORDER-ONLY, FILL-ONLY ... INACTIVE on SHIPMENT (a shipment's own id is not an invoice number)."* `LOCAL_INVOICE_ID`/`AI_INVOICE_ID` columns **do not exist** in `incoming_documents` at all (only `INVOICE_ID`, `INVOICE_ID_COMPLETED`, `EX_INVOICE_ID`, `LINKED_INVOICE_ID`) — the extraction wiring for this gap has not been built, confirming this is filed, not closed. No acceptance proof yet because no work has started; needs new `q_v3_routing` work and `LOCAL_INVOICE_ID`/`AI_INVOICE_ID` extraction wiring per the owner's own framing of this gap.

**B30 — B27 RECONCILED. The legacy per-value extractor dependency is COMPANY_ID = 4 rows, TYPE = 0 rows. The original figure was right; both later "corrections" measured different populations.**  ✅ measurement complete, deletion NOT executed (owner's suites-green gate still unmet — B24)
*(measured live 2026-08-09 09:11:34 UTC, DB clock, `supabase-db-shlomo-laptop`; queries in `tmp/b27/`)*

**B30.1 — What "still depends on the legacy extractor" has to mean, read off the live router code, not assumed.**
The deletion under consideration removes two action branches from `indoxV2ActionsGlobal01` — `figure_company_id` and `figure_document_type` — plus their sub-workflows. What the live, published `Decide DOC BASE Action` (`docBaseDecide`) actually does, verbatim:

```js
if (doc.LINK && !doc.BASE_EXTRACTION_COMPLETED) return 'extract_base_doc';   // two-point, runs FIRST
if (!doc.COMPANY_ID) {
  if ((!doc.FIGURE_COMPANY_COMPLETED || doc.STATUS === 'ACTION_RESTART') && !!doc.LINK)
    return 'figure_company_id';                                              // legacy, only if two-point left it null
  if (doc.STATUS !== 'MISSING_COMPANY_ID') return 'update_status_missing_company';
  ...
```
Three consequences that every prior measurement missed:
1. **Two-point runs strictly before the legacy extractor**, and the legacy extractor is guarded on `!doc.COMPANY_ID`. So a row can only depend on the legacy extractor if two-point already ran and produced nothing.
2. **A present `COMPANY_ID` is not evidence of dependency.** `docBaseDecide`'s own comment states ingestion (`indoxProcessDocument01`) pre-fills `COMPANY_ID` on **87%** of rows; for those, `figure_company_id` never fires. Measured: of the 258 two-point-empty rows, **42** hold a `COMPANY_ID` that no extractor wrote.
3. **For COMPANY_ID the deletion is strictly lossy — there is no surviving fallback.** `extract_invoice_google_ai` is only reachable via `unknownTypeAction`, which sits *after* the COMPANY_ID gate, so a row with no company never reaches it. For **TYPE** a fallback does survive: `unknownTypeAction` falls through to `extract_invoice_google_ai` when `API_TOOLS_ID && !AI_EXTRACTION_COMPLETED`.

**Population gate: ~~`BASE_EXTRACTION_COMPLETED='true'` — the flag `Select Base`/`Select Base Values` sets unconditionally on every two-point pass.~~** Not `AI_EXTRACTION_COMPLETED` (written by the legacy Gemini action — see corrected B27).
🔴 **THIS GATE WENT STALE 4½ HOURS AFTER IT WAS WRITTEN — corrected 08-09 13:40 UTC, see B33.2.** At `2026-08-09 12:44:28.955877+00`, in a single bulk `UPDATE` (4,583 rows sharing one exact microsecond), `BASE_EXTRACTION_COMPLETED` was set `'true'` on 4,583 already-`COMPLETED` documents that had **never been through two-point base extraction**: 4,583/4,583 carry no `SELECTION_DEBUG_BASE`, no `LOCAL_*` value of any kind, and no `Extract Base Doc` marker in `ACTION_LOG`. The flag is now a *queue-suppression marker* as well as an extraction receipt, and it no longer means what this section needed it to mean. **The corrected gate is `SELECTION_DEBUG_BASE` being present** — the router's own selection oracle, which only the selection step writes. This is the same class of error B27 was corrected for, one gate further along: see E3.
**Provenance instrument: `ACTION_LOG`.** `Build: UPDATE COMPANY_ID` appends `', UPDATE COMPANY_ID, '` and `Build: UPDATE DOCUMENT_TYPE` appends `', UPDATE DOCUMENT_TYPE, '` — a durable, per-row audit trail of *which mechanism actually wrote the value*. **None of the three prior measurements used it**; all three inferred from flags and column-nullness, which cannot distinguish "the legacy extractor rescued this" from "ingestion pre-filled it" from "nothing ever resolved it". This is the single change that makes the number reconcilable.
**Fixture exclusion**: `fixture-sweep.py --print-exclusion` marker-column predicate, **plus the known `NAME` gap closed**, plus the `plx_`/`plb_` pipeline seeds (live-poll-visible by design, still fixtures for an analysis count). The `NAME` sweep was done **anchored, never by containment** — G58 rule F3 exists because containment cost 2,432 client documents. All **124** `NAME`-carried fixture rows are anchored and from registered prefixes, zero coincidental matches:

| prefix in `NAME` | anchored at position 1 | rows | sample |
|---|---|---|---|
| `sv3f_` | yes | 86 | `sv3f_mx_110613.pdf` |
| `sv3s_` | yes | 27 | `sv3s_gb_187620.pdf` |
| `mailorg_` | yes | 11 | `mailorg_110160.pdf` |

*(Side finding, filed not fixed: those 124 suite-seeded PDFs are sitting in the live client table invisible to `fixture-sweep.py`, because the sweep matches only the registered marker columns and `NAME` is not one. B13's contamination channel is open in a second place.)*

**B30.2 — The measurement.** Non-fixture rows **7,193** of 7,320 total.

```sql
-- headline: rows that would have LOST their value had the legacy extractor been deleted
select count(*) from d                                   -- d = non-fixture view, see tmp/b27/final.sql
where lower(coalesce("BASE_EXTRACTION_COMPLETED",''))='true'   -- two-point actually ran
  and "LOCAL_COMPANY_ID" is null and "AI_COMPANY_ID" is null   -- two-point produced nothing
  and "COMPANY_ID" is not null                                 -- yet a value exists today
  and "ACTION_LOG" like '%UPDATE COMPANY_ID%';                 -- and the legacy extractor is what wrote it
```

| dim | pop (two-point ran) | two-point produced nothing | **A: would have lost the value** | B: pending, legacy untried | C: ingestion pre-fill (never depended) |
|---|---|---|---|---|---|
| **COMPANY_ID** | ~~869~~ | ~~258~~ | **4** (~~0.46%~~) | ~~135~~ | ~~42~~ |
| **TYPE** | ~~869~~ | ~~106~~ | **0** (0.00%) | ~~4~~ (1 of which Gemini still rescues) | — |

**Re-derived 08-09 13:41 UTC with the AI leg live and the corrected gate (B33.3). The headline count did not move.** Under `SELECTION_DEBUG_BASE`-present (two-point provably ran): pop **1,088**, two-point-empty **308**, **A = 4** (0.37%). Under the strictest available gate — the oracle itself saying `"COMPANY_ID":"NONE"` — 333 rows, 93 of which hold a value today, **4** of them written by the legacy extractor. Under the *original, now-contaminated* flag gate: pop 5,718, empty 1,914, **A = 4**. Three different populations spanning 333 → 5,718 rows, **one answer: 4 / 0**. The four rows are the same four documents by ID, unchanged since 08-06.

**Per-row proof for all 4, not a bare count** — `ACTION_LOG` position shows `Extract Base Doc` at char 3 and `UPDATE COMPANY_ID` at char 44, i.e. two-point ran first and failed, then the legacy extractor rescued it:

| ID | COMPANY_ID | `SELECTION_DEBUG_BASE` | NAME | verdict |
|---|---|---|---|---|
| `doc_mshnmfmeg3rbg7` | 513029975 | `{"COMPANY_ID":"NONE","TYPE":"LOCAL_ONLY",…}` | `IMG-20260730-WA0029.jpg` | BASE_FIRST → genuine rescue |
| `doc_mshoj178fblos6` | 511364952 | `{"COMPANY_ID":"NONE",…}` | `IMG-20260728-WA0171.jpg` | BASE_FIRST → genuine rescue |
| `doc_mshoj3nhhiorqu` | 512774019 | `{"COMPANY_ID":"NONE",…}` | `IMG-20260728-WA0133.jpg` | BASE_FIRST → genuine rescue |
| `doc_mshflkl3pwv0mb` | 516146461 | `{"COMPANY_ID":"NONE",…}` | `מ.ש. הכהנים חומרי בנין בע"מ-02989` | BASE_FIRST → genuine rescue |

Three are WhatsApp camera images (Task #87's population exactly); the fourth carries the **company name in the filename**, which is `indoxV2FigureCompanyId01`'s `Try By SOURCE_ID` node's `company_id_by_name` strategy (`NAME.includes(value)` against `settings.company_name_by_identifier`) — a strategy `BaseDocEx01` genuinely does not have. This is the concrete mechanism `Select Base Values`' own `CONDITIONAL STAMP` comment predicted: *"indoxV2FigureCompanyId01 (32 nodes) additionally tries the sender->company map, the NAME->company map, and canonicalises the result."*

**Corroborating measurement — the legacy extractors' realised yield across the WHOLE non-fixture fleet, not just the two-point population:**

| mechanism | rows it ran on (`ACTION_LOG` marker) | rows where it produced a usable value |
|---|---|---|
| legacy `figure_company_id` | 222 | **4** |
| legacy `figure_document_type` | 77 | **0** |

`figure_document_type` has resolved a usable `TYPE` on **zero** documents fleet-wide, ever. It is not a risk to delete; it is dead code that already does nothing. `figure_company_id`'s conditional hit-rate, restricted to rows where two-point produced nothing *and* its own outcome is known (`FIGURE_COMPANY_COMPLETED='true'`, n=185): **4/185 = 2.16%**.

**B30.3 — Why the other two figures differed. Three different populations, one instrument gap.**

| figure | what it gated on | what it actually counted | why it differs |
|---|---|---|---|
| **4 / 0** (original) | `BASE_EXTRACTION_COMPLETED` + legacy actually wrote the value | rows that would have **lost** COMPANY_ID/TYPE | **Correct.** Reproduces exactly at 4/0 today. Its `0.68%` denominator was ~588 rows (4/588 = 0.68%); the population is now 869, so the *rate* moved to 0.46% while the *count* held at 4. B27's charge that "no trace of the query exists" was true of the scratchpad and false of the number. |
| **36 / 27** | `AI_EXTRACTION_COMPLETED='true'` | the **legacy-Gemini** population, 4,042 rows, of which **3,487 have never been through two-point at all** | **Wrong population gate.** That flag is set by `extract_invoice_google_ai`, not by two-point. It also never asked whether the legacy extractor *resolved* anything — it counted unresolved rows, most of which the legacy extractor had already tried and failed on. |
| **97 / 75** | `BASE_EXTRACTION_COMPLETED='true'` + fixture stripping | rows that came out of two-point **still unresolved** — the same shape reads **206 / 189** today | **Right gate, wrong question.** "Unresolved after two-point" ≠ "depends on the legacy extractor". Of the 206, **165 have already had `figure_company_id` run and find nothing**, 32 have no `LINK` so it can never run, and only **9** are genuinely still owed it. Deleting the extractor changes nothing for 197 of the 206. The fixture-stripping work in this measurement was sound and is carried forward here. |

The 97/75 figure is therefore the **closest in method** (right gate, right fixture discipline) and the **furthest in meaning**; the 4/0 figure is the one that answers the owner's actual question.

**B30.4 — The finding that should change the owner's read of this whole objective: the AI half of two-point extraction has never run.**

```sql
select key, value, updated_at from settings
 where instance='incoming-documents-main' and key like 'extraction_%';
--  extraction_ai_enabled    | false | 2026-08-05 23:01:12+00
--  extraction_local_enabled | true  | 2026-08-05 23:01:12+00
```
Confirmed downstream, not just from the flag — the full `SELECTION_DEBUG_BASE` distribution across every row that has one:

| `COMPANY_ID` source | `TYPE` source | `AI_STATUS` | rows |
|---|---|---|---|
| LOCAL_ONLY | LOCAL_ONLY | *(router-written, field absent)* | 342 |
| LOCAL_ONLY | LOCAL_ONLY | `skipped: extraction_ai_enabled=false` | 245 |
| NONE | NONE | *(router-written)* | 142 |
| NONE | LOCAL_ONLY | `skipped: extraction_ai_enabled=false` | 104 |
| NONE | NONE | `skipped: extraction_ai_enabled=false` | 85 |
| NONE | LOCAL_ONLY | *(router-written)* | 70 |

`AI_ONLY`, `AGREE` and `DISAGREE_PREFER_*` appear **zero** times. **The "one shot doing BOTH local and AI extraction" is running on one leg**, and has been since 2026-08-05.

⚠️ **This is a DELIBERATE OWNER SETTING, not a defect — do not flip it.** The owner has stated AI extraction is intentionally off. Nothing here is a request to turn it on. What it *does* mean, and what this file must say wherever these numbers are cited:

> **STANDING CAVEAT — every parity, coverage and dependency number in this file (B26, B27, B29, B30, B31) measures a ONE-LEGGED mechanism.** `LOCAL_*` is the only populated provenance family; `AI_*` on the base path is empty by configuration. So "two-point extraction" as measured is single-source local extraction. Read every such figure as a floor for the local leg alone, never as a measurement of the two-point design at full strength. Any future decision that assumes AI-vs-local agreement, disagreement rates, or AI-side coverage has **no live evidence behind it on this deployment**.

✅ **THE CAVEAT IS LIFTED FOR NEW ROWS ONLY, from `2026-08-09 13:32:05 UTC` — the first `SELECTION_DEBUG_BASE` in the deployment's history carrying an `AI_ONLY`/`AGREE`/`DISAGREE_*` source.** `extraction_ai_enabled` now reads `true` (note: `settings.updated_at` was **not** touched by the flip and still reads `2026-08-05 23:01:12+00`, so that column is not a usable audit trail for this change — the first AI-sourced row is). It does **not** retroactively lift for the 1,078 rows already carrying a one-legged `SELECTION_DEBUG_BASE`, and it will **never** lift for the 4,583 rows the 12:44 backfill marked base-complete without extracting (B33.2) — those documents are now past the base gate and cannot receive the AI leg without being re-armed. Full re-derivation and the volume that is and is not sufficient: **B33**.

Both readings follow and both are worth stating: two-point is already outperforming the legacy extractors at **half** its designed capability (good), **and** the 4/0 figure is not a measurement of the mechanism at full strength (a limit on what it can be used to conclude, not a defect).

**B30.5 — The lock-in plan. Exact nodes, derived by walking `connections` in `indoxV2ActionsGlobal01.json`, not by name-matching.**

*Tranche 1 — `figure_document_type`. Zero measured risk; delete first, independently.* Fleet-wide realised yield **0**.
- `indoxV2ActionsGlobal01.json` — delete 6 nodes: `Action: Figure Document Type`, `Loop Over Items22`, `No Operation, do nothing`, `Figure Document Type` (executeWorkflow → `indoxV2FigureDocType01`), `Join Document Type`, `Build: UPDATE DOCUMENT_TYPE`. Remove switch output **7** of `3a. DOC BASE Actions Switch`. Keep `Upsert (central)` (14 other producers feed it).
- `Decide DOC BASE Action` — delete the first two lines of `unknownTypeAction()`, so an unknown type falls straight through to `extract_invoice_google_ai`.
- Retire `indoxV2FigureDocType01.json` (16 nodes) to `data/_attic_agent_drafts/` per the A29 precedent.

*Tranche 2 — `figure_company_id`. Residual risk 4 rows (0.46%), and one hidden coupling that must be handled first.*
- `indoxV2ActionsGlobal01.json` — delete 7 nodes: `Action: Figure COMPANY_ID`, `Loop Over Items24`, `No Operation, do nothing1`, `Figure Document COMPANY_ID` (→ `indoxV2FigureCompanyId01`), **`Get Doc Thumbnail`**, `Join  COMPANY_ID`, `Build: UPDATE COMPANY_ID`. Remove switch output **1**.
- `Decide DOC BASE Action` — delete the `figure_company_id` branch of `docBaseDecide`, so `!COMPANY_ID` after two-point goes directly to `update_status_missing_company`.
- Retire `indoxV2FigureCompanyId01.json` (32 nodes).
- 🔴 **HIDDEN COUPLING — thumbnail generation piggybacks on this action.** `Join  COMPANY_ID`'s own comment: *"This piggybacks on figure_company_id — the action that already runs exactly once for essentially every new doc."* Deleting the branch deletes `Get Doc Thumbnail` with it. There **is** a replacement — `BaseDocEx01`/`Select Base` returns `THUMBNAIL` from `Upload+OCR` and `Build Base Doc Upsert` carries it through (`includeOtherFields:true`) — and it is **proven to work independently**: of the 869 two-point rows, 285 hold a `THUMBNAIL` and **263 of those never ran the legacy step**. But total coverage is only 285/869 (33%), so thumbnail coverage must be confirmed non-regressing before this tranche lands, or the webapp silently loses thumbnails on the rows the legacy step was still carrying.

*Not in scope, and deliberately not assumed safe.* The per-type `query_*` single-field extractors in `indoxV2ActionsGDoc01`/`Ship01` (`Action: Query Doc Date`, `Action: Query Doc Total Amount`, `Action: Query Purchase ID1`, `Action: Query Shipment ID`, `Action: query_invoice_id`, `Action: Get Short Doc ID1`) are a **separate tranche needing its own B30-style measurement**. ~~First pass, same method: only **67** non-fixture rows carry the `Extract Per Type` marker at all … 67 rows is too small a base to certify a deletion~~ ⚠️ **THE 67 IS AN INSTRUMENT ARTEFACT — corrected 08-09, see B32.** The marker lands on only 12% of the rows that actually went through the per-type point, because `Build Per Type Upsert` computed `ACTION_LOG` from `$json.ACTION_LOG` — and `$json` there is the *extractor's return payload*, which never carries `ACTION_LOG`. **The true per-type population is 575 rows, not 67**, and 3,027 more are queued behind the base point for it. B28's shipment `INVOICE_ID` gap does still sit inside this tranche. Do not fold it into tranches 1–2, but do re-run the measurement against the corrected instrument before certifying anything.

**B32 — the per-type point was never dead, and the instrument that said otherwise is the bug. Two staged fixes, neither deployed (classifier-blocked).**  ✅ measured live 2026-08-09 09:56–10:25 UTC

- **The "0 executions for `InvoiceDocEx01`/`ShipmentDocEx01`/`BsDocEx01`" premise is false.** Live `execution_entity`, current hour: `BaseDocEx01` 153, **`InvoiceDocEx01` 49, `ShipmentDocEx01` 9, `BsDocEx01` 5**, zero errors across all four. All four extractors and all four routers are `active` with `versionId == activeVersionId`; the three per-type routers are **byte-identical** to the repo blueprints (published `workflow_history` compared node-by-node, jsCode and connections). Only `indoxV2ActionsGlobal01` drifts, by the known un-deployed B31.3 change.
- 🔢 **THE PER-TYPE DEMAND FIGURE, CORRECTED — quote this one, not the earlier 5,451.**
  **~~`extract_per_type` = 27 today, and 3,027 once the base backlog of 3,638 rows clears.~~**
  ⚠️ **SUPERSEDED 08-09 13:44 UTC by B33.9 — re-run against the LIVE published deciders (not the repo copies) and the current fleet: `extract_per_type` = **23** today, and **350** after the base backlog of **966** clears.** The base backlog fell 3,638 → 966 not by extraction but by the 12:44 backfill (B33.2), and the same backfill pushed 4,583 rows past the base gate into their type lanes, where **legacy per-value demand went 5 → 1,214** (`query_doc_total_amount` alone is 1,201, all in the shipment lane). Tranche 3 got materially more expensive to delete, and that is a consequence of the backfill, not of the AI leg.
  ~~5,451~~ was measured by replaying only the three type-lane deciders; it **omitted the base gate**, and `docBaseDecide` claims 3,638 of those rows for `extract_base_doc` first. The 5,451 was quoted upward before this correction — it is superseded, not merely refined.
- **The ordering contract the owner specified is already in force.** `extract_per_type` precedes every `query_*` in `invoiceDecide`/`shipmentDecide`; it precedes `extract_balance_sheet` in `bsDecide`; `extract_base_doc` precedes `figure_company_id` and `figure_document_type` in `docBaseDecide`. Proven by replaying the four decide bodies **verbatim** over all 7,495 live rows in the driver's real two-stage order (base decide first, `__route_*__` then dispatching to the type lane): `extract_base_doc` 3,638 · `extract_per_type` 27 · **legacy per-value 5**. After the base backlog: `extract_per_type` 3,027, legacy per-value still 5. Harness: `tmp/pertype-actionlog/replay-decide-2stage.js`.
- **What the owner is actually seeing in the timeline** is the per-type extractor running *first* and one legacy per-value query then firing on the single field it left blank — 67 legacy per-value runs against 63 per-type runs in the same hour. `SELECTION_DEBUG_PERTYPE` over the 575 per-type rows: `AMOUNT` NONE 271, `SHIPMENT` NONE 268, `PURCHASE` NONE 208, `DOC_DATE` NONE 64, `DOC_ID` NONE 44 — local-leg misses, `extraction_ai_enabled='false'`. **Not safe to suppress the fallbacks yet**: with the marker broken there is no way to separate "legacy rescued it" from "the value pre-existed", which is exactly what fixing the instrument restores.
- **FIX 1 (staged) — `ACTION_LOG` at the per-type point.** One line in each of `indoxV2ActionsGDoc01` / `indoxV2ActionsShip01` / `indoxV2ActionsBS01`: fall back to `$('Action: Extract Per Type…').item.json.ACTION_LOG`, the same pre-extraction-row reference all five sibling assignments in that node already use. As written the expression could only ever *replace* the document's whole history with one entry; 70 of 575 rows carry the marker, 3 of 46 today. `tmp/pertype-actionlog/fix-pertype-actionlog.py --apply`, backups + sha256 recorded, idempotent, node/connection counts asserted unchanged.
- **FIX 2 (staged) — `API_TOOLS_ID` is a base-point responsibility (owner's ruling), and it already is one.** `BaseDocEx01` starts at `Upload+OCR` and `Select Base` already emits `API_TOOLS_ID: upload.file_id`; it reaches the column through `Select Base Values` (`{...d}`) and `Build Base Doc Upsert` (`includeOtherFields:true`). Live proof: of 1,086 rows where `BaseDocEx01` provably ran, **964 (88.8%) carry an id**. The `/docExists` hash short-circuit is *not* a hole — apitools returns `{"file_id": <hash>, …}` (`ocr_api.py:671-676`) and the uploader's `Return` reads `$json.file_hash || $json.file_id`, so both upload paths yield one. The real defect is that the write was **not fill-only**: 5,694 rows already hold an id and are still queued for `extract_base_doc`, any of which this run could have replaced. Fixed at both ends — omit-on-null in `Select Base`, existing-value-wins in `Select Base Values` against `$('Action: Extract Base Doc').item.json`. 13/13 behavioural tests (`tmp/pertype-actionlog/test-base-apitools-id.js`), `node --check` clean.
- **The BS lockout is now sized, and it is mostly throughput.** `indoxV2ActionsBS01` has no `get_api_tools_id` and neither does the base router, so the base point is a balance sheet's *only* source of an id. Of the 151 BS rows without one, **133 simply have not been through base yet** (fix 2 delivers them with no further change) and **18 went through base and got nothing** — those are permanently stuck (12 have a usable `LINK`). Fleet-wide absence: 836/7,495 (11.2%) — INVOICE 269, UNKNOWN 167, null-TYPE 201, BALANCE_SHEET 151, SHIPMENT 48.
- **FIX 3 (staged) — bounded one-shot base-point retry.** ~~Withheld pending the owner.~~ **Approved 08-09 with the hazard named: bound it on something the rescue gate does not read.** Three edits in `indoxV2ActionsGlobal01`: (3a) `Build Base Doc Upsert`'s `ACTION_LOG` gets the same pre-extraction-row fallback as FIX 1 — it had the identical defect, and since the retry's bound *lives* in `ACTION_LOG` this is a hard prerequisite, not a nicety; (3b) `Select Base Values` writes a `BASE APITOOLS RETRY` marker **only when this pass produced no id AND the row was already `BASE_EXTRACTION_COMPLETED`** — i.e. only on the retry pass itself, since stamping it on the first pass would pre-empt the retry it is supposed to bound; (3c) `docBaseDecide` gains one guard immediately after the existing `extract_base_doc` line, so rows that have never been through base are still claimed there and this only sees the base-has-run cohort.
  **No `*_COMPLETED` column is written anywhere in this change.** That is the whole point: `get_api_tools_id`'s gate is `isBlank(API_TOOLS_ID) && !API_TOOLS_ID_COMPLETED`, so stamping that flag would have shut a working rescue — measured open on **835 rows before and 835 after**. Same marker mechanism as `figure_company_offline` (B31.3); no schema change.
  **Measured effect:** `extract_base_doc` 3,638 → **3,735** in full driver-order replay (+97; the raw guard matches 99, two of which upstream terminal guards claim first). Cohort: UNKNOWN 45 · null-TYPE 39 · BALANCE_SHEET 12 · INVOICE 3; only 8 carry a `COMPANY_ID` to hazard, and the id write is fill-only with `COMPANY_ID` nulls stripped by the UPSERT Adapter. **18/18 lifecycle assertions** (`tmp/pertype-actionlog/test-base-apitools-retry.js`) driving the real patched nodes: worst case (upload keeps failing) fires the retry exactly once and a third pass cannot re-arm it; a successful retry writes no marker; prior `ACTION_LOG` history survives both passes; a row that already holds an id never enters the retry and cannot have it replaced.
- **The 6 balance sheets the retry does NOT cover, reported rather than engineered around.** Of the 18 stuck, 12 are recovered. The remaining 6 — `doc_msirldk37qsi9d`, `doc_msirlduq0br0zi`, `doc_msirldcevdb5e0`, `doc_mshryzq2n6vin4`, `doc_mshry0qrn7gd06`, `doc_mshry0toovgjez` (5 `MISSING_COMPANY_ID`, 1 `EXTRACTION_FAILED`) — have **no `LINK` and no `NAME` at all**. There is no file to upload, so no apitools id can exist for them by construction, and no amount of retrying creates one. They need a source/link repair, not extraction machinery.

**Acceptance proof (B32):** ✅ **MET for everything that does not require a push.** The premise was checked against live data before any code was touched and did not survive; the ordering contract is proven by executing the real decide bodies over the real fleet, not by reading them; all three fixes are exact-match edits with backups, sha256s, idempotency guards, `node --check` and **31 behavioural assertions** across two suites; the retry is bounded on a marker the rescue gate cannot see, and that non-interference is proven by count (835 → 835) rather than asserted; the six rows nothing can fix are named. **NOT MET for deployment** — pushes are classifier-blocked for every agent, so nothing here is live.

**B30.6 — Residual risk at the measured number, stated plainly for the owner.**
- Deleting `figure_document_type`: **zero measured loss**, 0/77 realised yield fleet-wide, and a surviving Gemini fallback besides. Safe on the evidence. **Re-confirmed 08-09 13:42 with the AI leg live: it has now run on 77 rows, all 77 hold a `TYPE`, and the number of those types that is usable — i.e. not `UNKNOWN` — is still exactly 0.**
- Deleting `figure_company_id`: **4 documents in 869 (0.46%)** would have terminalised `MISSING_COMPANY_ID` instead of resolving; extrapolated across the ~6,300-row backlog not yet through two-point at the conditional 2.16% hit-rate, the exposure is **order-of-magnitude 30–140 documents**, all landing in an existing, visible, recoverable state (`MISSING_COMPANY_ID`, already 501 rows) rather than being silently wrong. No data is destroyed — the already-resolved values stay in the table.
- ~~**What would take it to zero:** port `indoxV2FigureCompanyId01`'s two non-OCR strategies into `BaseDocEx01` … they are the entire measured delta.~~ ⚠️ **WRONG — retracted 08-09 by my own follow-up measurement, see B31.1.** The port covers **0 of the 4**. All four residual rows were resolved by the OCR strategies (`Find Option` / `Extract COMPANY ID AFTER`), not by the settings maps; the filename attribution I gave for `doc_mshflkl3pwv0mb` was wrong — `מ.ש. הכהנים` is the **client's own company**, not a supplier in `company_name_by_identifier`, and that row gets no filename-map hit. What would actually take the 4 to zero is porting the **OCR** strategies, which is a materially bigger job than a settings-map lookup and is **not** scoped here. **The 0.46% residual for Tranche 2 stands unmitigated.**

**B31 — the residual-closing port was measured before it was built, and the measurement says it resolves ZERO documents. Not shipped. The real defect it went looking for is a different one, and it is worth 63 documents.**  ⚠️ a planned change cancelled by its own pre-measurement
*(measured live 2026-08-09, `supabase-db-shlomo-laptop`; queries in `tmp/b27/port-reach.sql`, `tmp/b27/why63.sql`)*

**B31.1 — The port as scoped in B30.6 would have resolved 0 rows. Two independent reasons, both measured.**
The proposal was to port `company_id_by_mail` (sender→company) and `company_id_by_name` (filename→company) out of `indoxV2FigureCompanyId01` into `BaseDocEx01`. Both map families were replicated in SQL faithfully from `indoxSettings01`/`Companies` (identifiers from `מזהה 1`/`מזהה 2`/`שם ספק מפריוריטי` minus the `פריוריטי` blacklist, primary = first non-blank; mails lowercased from `מייל 1`/`מייל 2`) — 142 mail entries, 2,378 identifier entries, 1,181 companies.

| strategy | rows it would resolve in the `MISSING_COMPANY_ID` backlog (n=433 non-fixture) |
|---|---|
| `company_id_by_mail` (sender→company) | **0** |
| `company_id_by_name` (filename→company) | **63** (0 ambiguous) |

1. **The sender→company strategy is already dead, and A38 is what killed it.** It reads `SOURCE_ID.endsWith(mail)`. A38 fixed `SOURCE_ID` to hold the **gmail message id** instead of the sender address — so the strategy can only ever have worked *because of the bug A38 corrected*. It still matches 1,249 rows fleet-wide (rows that predate the fix and already have a company), and **0** rows in the backlog. Porting it would port dead code.
2. **The filename strategy's 63 rows are unreachable from `BaseDocEx01`.** All 63 have **no `LINK`** — measured `no_link = 63/63`, `no_apitools_id = 63/63`, `BASE_EXTRACTION_COMPLETED` true on **0**, `FIGURE_COMPANY_COMPLETED` true on **0**, and 62 of 63 have a **completely empty `ACTION_LOG`**. `BaseDocEx01` begins with `Upload+OCR`, which needs the link. A strategy ported there would never execute on the only rows it could help.

**B31.2 — What the 63 rows actually expose: every company-resolution path in the base router is gated behind `!!doc.LINK`, and these documents don't have one.** From the live `docBaseDecide`:
```js
if (doc.LINK && !doc.BASE_EXTRACTION_COMPLETED) return 'extract_base_doc';   // needs LINK
if (!doc.COMPANY_ID) {
  if ((!doc.FIGURE_COMPANY_COMPLETED || …) && !!doc.LINK) return 'figure_company_id';  // needs LINK
  if (doc.STATUS !== 'MISSING_COMPANY_ID') return 'update_status_missing_company';     // ← they land here, immediately
```
So a linkless document is terminalised `MISSING_COMPANY_ID` **without any company resolution ever being attempted** — which is why 62 of the 63 carry an empty `ACTION_LOG`. Yet their company is sitting in plain text in their own filename: measured hits are `אונת סימנט-91625` → `אונת סימנט` (516587961), `א פתיה-03399` → `א פתיה` (510564693) — the `<company>-<docnum>` Drive export convention. **The filename map needs no document, no OCR and no link at all.** 63 of 433 (14.6%) of the non-fixture backlog is recoverable by a lookup that is currently unreachable purely because it sits behind a link gate it does not need.
*(Reconciling the coordinator's 557: raw `MISSING_COMPANY_ID` incl. fixtures = **561**; non-fixture = ~~**433**~~ under B30's exclusion.)*
*(Re-measured 08-09 13:47: the non-fixture `MISSING_COMPANY_ID` backlog is now **386**, down 47. `figure_company_offline` is **deployed** as of the 13:34:53 push and the full-fleet replay says it will claim **196** rows once the base gate clears — but its `ACTION_LOG` marker appears on **0** rows so far, so it has not yet demonstrably resolved anything. Its yield is unmeasured, not zero; do not credit it in the Tranche-2 arithmetic until the marker moves.)*

**B31.3 — Why this was not shipped, and the one measured hazard any future version must carry.** The change that would actually win the 63 is a **link-independent filename→company step in the router**, not a port into `BaseDocEx01`. That is a different change to a different file with a different risk profile than the one that was scoped, it lands in the same decider the Tranche-2 deletion touches, and it carries a measured hazard that must not be skipped:

> **False-positive probe.** Applying `NAME.includes(company_name)` to the 6,117 non-fixture rows that already hold a `COMPANY_ID`: **5,995 agree, 122 (2.0%) DISAGREE.** The map contains company names as short as 3 characters (`טסה`, `BDI`, `כתר`, `נגב`, `בזק`, `שאל`, `סבח`), and unanchored containment against short tokens is the exact defect class that cost this deployment 2,432 client documents (G58 rule F3). None of the 63 backlog hits is driven by a short name (matched lengths are 6, 10 and 12 only) and none is ambiguous — but any implementation must be **fill-only** (never overwrite an existing `COMPANY_ID`) and should carry a minimum-name-length guard, or it will convert a 63-row win into a 122-row clobber.

**UPDATE 08-09 — BUILT, statically verified, SQL live-tested, and BLOCKED AT DEPLOY.** `tmp/b27/apply-offline-resolver.py --apply` is applied to `apps/indox/blueprint/n8n/indoxV2ActionsGlobal01.json` (85 → 88 nodes; pre-change backup `tmp/b27/indoxV2ActionsGlobal01.pre-b31.bak`, `sha256 cafb297e…`). New action `figure_company_offline`, dispatched from a **appended** switch rule (index 25) so no existing index shifts and `fallbackOutput` stays 17 — the deletion-side hazard from B31.4 does not apply to an append, and the verifier asserts it anyway. Branch is linear (`Action → Match Company By Filename (Offline) → Build → Upsert (central)`), no `splitInBatches`, so there is no loop for G45 to order.

Static verify, all 11 assertions green — including that the new resolver sits **after** `figure_company_id` in the decider (the weaker resolver must never pre-empt the stronger one), and each guard asserted by name in the SQL text:
```
OK fallbackOutput 17 -> Stop and Error - Unhandled DOC BASE ACTION (unshifted)
OK rule 25 'figure_company_offline' -> Action: Figure COMPANY_ID (Offline)
OK decider emits figure_company_offline · OK fill-only gate (!doc.COMPANY_ID) intact
OK offline resolver runs only after figure_company_id
OK guard: anchored prefix (not containment) · min company-name length 5
OK guard: unambiguous only · deterministic longest-match
OK write-time fill-only assertion present            VERIFY: PASS
```
**The SQL was tested against the live DB before the file was touched**, not just linted — `prepare`d and executed on four real inputs:

| input `NAME` | company_id | matched_name | candidates |
|---|---|---|---|
| `אונת סימנט-91625` | **516587961** | `אונת סימנט` | 1 |
| `IMG-20260730-WA0029.jpg` | *(null)* | — | 0 |
| `מ.ש. הכהנים חומרי בנין בעמ-02989` | *(null)* | — | 0 |
| `''` (empty) | *(null)* | — | 0 |

The third row is the independent confirmation of B30.6's retraction: the client's **own** company is not in the supplier map, so that document correctly gets no hit.

🔴 **Deploy blocked, and correctly so:** `tmp/push-batch1.sh` was refused by the platform's own permission classifier — the same category as **Task #100** (password rotation) and **Task #107** (credential restore), both of which also need the owner directly. **Owner action needed to land it.** The guards are what make the wait cheap: fill-only means the change cannot damage the 6,618 already-resolved rows even if it misfires.

**Two process notes recorded rather than smoothed over, per E3.** (1) `./bbox n8n push --help` is **not a help flag — it executes a push**; run to discover the scope options, it began a real push outside the gated script. It was severed by the `head -25` pipe before the workflow-import stage, so **nothing was deployed** — verified after the fact: n8n containers up 33 minutes (i.e. never restarted, and this push restarts the stack at the end), live router `has_offline_action=f`, published version `has_offline_action=f`, **0** armed test/reset workflows, and the credential stage was non-destructive (*"all 24 already exist — none re-imported"*, with all 5 env-managed credentials **SKIPPED** rather than blanked — the Task #107 wipe class did not recur, the tooling has since been hardened against exactly it). (2) The correct lesson is the one this file keeps relearning: **never pipe a deploy command into `head`** — the truncation is what turned a discovery command into a half-run push, and it is only luck that the severing point was before the destructive stage.

**BEFORE snapshot, for the owner to measure against once it lands** (DB clock 2026-08-09, non-fixture): `MISSING_COMPANY_ID` = **433**, `COMPANY_ID is null` (any status) = **577**, `COMPANY_ID is not null` = **6,618** (the regression baseline — must be **unchanged or higher** after; fill-only means it can never fall), rows carrying the `FIGURE COMPANY OFFLINE` ACTION_LOG marker = **0**. Expected after: 63 rows gain a `COMPANY_ID` and leave `MISSING_COMPANY_ID`; every touched row is auditable by name via its `FIGURE COMPANY OFFLINE HIT <company>` marker.

**Residual risk, stated honestly:** the filename map's intrinsic error rate, probed against the 6,117 rows that already hold a `COMPANY_ID`, is **119/5,222 ≈ 2.3%** disagreement under the same anchored+len≥5 guard. Applied fill-only to 63 rows that today have **nothing**, that predicts **~1–2 documents** resolved to the wrong company. The trade is explicit: 63 documents leave a visible dead-end state, at the cost of ~1–2 landing on a wrong-but-recorded company that the `HIT <name>` marker makes findable in one query. If the owner prefers zero wrong attributions over 63 recoveries, do not land it — but that is a decision, not a defect.

**B31.4 — Tranche 1 is STAGED and statically verified, and staging caught a silent-routing bug that would have shipped.** `tmp/b27/stage-tranche1.py` writes a patched **copy** to `tmp/b27/staged/` and never touches the repo blueprint (re-confirmed: repo file still 85 nodes, all 6 target nodes present, `fallbackOutput` still 17, mtime unchanged at 2026-08-07). Verifier output:
```
nodes 85 -> 79  (-6)   switch rules 25 -> 24   fallbackOutput 17 -> 16
OK  fallbackOutput 16 -> Stop and Error - Unhandled DOC BASE ACTION
OK  decider no longer emits figure_document_type (2 comment refs remain, inert)
OK  no live FIGURE_TYPE_COMPLETED guard remains
OK  Gemini fallback still present
VERIFY: PASS
```
🔴 **The catch:** `3a. DOC BASE Actions Switch` is a v2 switch whose `rules.rules[]` are **positional** against `connections.main[]`, and `options.fallbackOutput` is an index into that same array. Deleting rule 7 shifts every later slot down by one, so a naive node deletion leaves `fallbackOutput: 17` pointing at **`resolve_double`** instead of the unhandled-action error node — every unrecognised ACTION would have been silently dispatched into the merge-adjudication branch, with no error. This is E1's shape (a check whose evidence is an absence) and it is exactly what staging-before-pushing exists to catch. The script fixes the index and the verifier asserts the fallback target by name, not by number.
**Still gated:** not pushed. Owner's precondition is 7/7 suites green (B24: still 0/7).
**Sequenced against B31.3 and re-verified after it landed in the repo** — the two changes compose cleanly and do not conflict: re-run against the now-88-node router, the staging script reads `88 → 82 (-6)`, `switch rules 26 → 25`, `fallbackOutput 17 → 16`, `VERIFY: PASS`. This works because B31.3 **appends** its rule (index 25 → 24 after the Tranche-1 deletion) while Tranche 1 **removes** rule 7; append-then-delete leaves both the new branch and the fallback correctly bound. Had B31.3 inserted its rule anywhere before index 7, or had either change hard-coded an output index, they would have silently mis-bound each other.

**B31.5 — The Tranche-2 thumbnail coupling is RESOLVED: severing it loses nothing.** B30.5's 263/285 figure is now a confident answer.

| cohort | rows | with `THUMBNAIL` | % |
|---|---|---|---|
| two-point ran, legacy did not | 694 | 264 | **38.0%** |
| two-point ran, legacy also ran | 175 | 23 | 13.1% |
| two-point never ran, legacy ran | 54 | 0 | **0.0%** |
| two-point never ran, legacy did not | 1,195 | 22 | 1.8% |

```sql
select count(*) from d where coalesce("THUMBNAIL",'')<>''
  and "ACTION_LOG" like '%UPDATE COMPANY_ID%'
  and lower(coalesce("BASE_EXTRACTION_COMPLETED",'')) <> 'true';   -- => 0
```
**Zero rows in the fleet carry a thumbnail that came only from the legacy `Get Doc Thumbnail` step.** The legacy-only cohort is at 0.0% coverage; two-point's own path is at 38.0%. Deleting `Get Doc Thumbnail` with Tranche 2 removes no capability that is producing anything. **Coupling cleared.**

~~⚠️ **Separate pre-existing defect found while clearing it:** `Select Base` stamps `THUMBNAIL_COMPLETED: true` **unconditionally** … the identical conditional-stamp bug the same node's own comment guards against … fix is one line.~~
❌ **RETRACTED 08-09, before shipping — I was wrong, and the "fix" would have caused a regression.** The unconditional stamp is **documented, deliberate, owner-sanctioned design**, not a defect. `apps/indox/blueprint/fixtures/schema.sql:219`, verbatim:

> *"THUMBNAIL_COMPLETED is stamped whether or not a THUMBNAIL was actually produced (a render/upload failure is a nicety failing soft, not a pipeline block) — so the step is idempotent and terminal on the first attempt either way."*

and `apps/indox/app/incoming_documents/api/__init__.py:4014`: *"FAIL SOFT BY DESIGN … the n8n action stamps THUMBNAIL_COMPLETED either way, so a single failed attempt terminates rather than retrying forever."* Making the stamp conditional would convert a deliberately terminal step into one that **retries forever** on every document whose bytes were already uploaded — which is most of them, because `indoxV2UploadApiTools01` short-circuits on an apitools `/docExists` hash hit and returns no bytes to render. That is the opposite of the intent, and it would have been shipped on my reading of a comment two lines away rather than on the schema note that governs the field.

**The backfill would also have been inert**, measured rather than assumed: **0** deciders anywhere in the 81 blueprints gate on `THUMBNAIL_COMPLETED` (searched for `!doc.THUMBNAIL_COMPLETED`, `THUMBNAIL_COMPLETED ==`, `…!==`, `…)`), and **no `generate_thumbnail` action or sub-workflow exists** — schema.sql says so directly: *"there is no separate 'generate_thumbnail' action and no thumbnail sub-workflow."* Resetting the flag on 582 rows would therefore re-drive nothing.

**The 582 empty thumbnails are real, but they are a known corpus gap with a known remedy already on record, not a stamp-logic bug.** schema.sql, same block: *"a document whose bytes were already uploaded gets no THUMBNAIL (17 of 5,775 uploaded rows had one on 2026-08-06) — **a backfill is needed for the existing corpus**."* The remedy is a backfill job that renders previews for rows lacking them, per `ai/context/lane-d-n8n-consolidation-2026-08-06.md`. **Nothing shipped here.** This is the third assumption in this pass overturned by reading the source instead of trusting a local comment (after B27's gate and B30.6's attribution), and it is the one that would have done damage.

**Acceptance proof (B31):** ✅ **MET for everything that does not require the owner.** The port was measured before being built and cancelled on the evidence (0 rows); the real 63-row defect is located, quantified, its hazard measured, and the fix **built, statically verified and live-SQL-tested**; Tranche 1 is staged, verified, its silent-routing bug caught, and re-verified to compose with the new resolver; the thumbnail coupling is cleared with a live query returning 0, and the thumbnail "fix" was **retracted before shipping** on the schema's own documented intent.
❌ **NOT MET, owner action needed:** the resolver is **not deployed** — `tmp/push-batch1.sh` was refused by the platform's permission classifier (Task #100 / #107 category). Until the owner lands it, the 63 documents stay in `MISSING_COMPANY_ID` and the BEFORE snapshot above is the measurement to re-run afterwards.
**State of the tree:** `indoxV2ActionsGlobal01.json` is modified in the repo (85 → 88 nodes, backup + sha256 recorded); `BaseDocEx01.json` is **byte-unchanged**; Tranche 1 exists only as a patched copy under `tmp/b27/staged/` and has **not** been applied to any blueprint.

---

**Acceptance proof (B30):** ✅ **MET for the measurement.** The number is 4/0, reproduced from a stated population gate, a per-row provenance instrument, and a fixture exclusion that closes the `NAME` gap; all three prior figures are accounted for by named methodology differences rather than left as an open contradiction. **NOT MET, and deliberately so, for the deletion**: the owner gated it on all 7 suites green, which is still 0/7 (B24), and this pass executed nothing. Three things should land before tranche 2: (a) suites green, ~~(b) `extraction_ai_enabled` turned on and B30.2 re-measured with both legs live~~, (c) the two settings-map strategies ported per B30.6 — after which the expected residual is zero rather than 4.
**(b) is now DONE — 08-09 13:32 UTC, re-measured in B33. It did not change the answer, and B33.4 shows why it structurally could not raise it.** (c) remains retracted by B30.6/B31.1 — the port covers 0 of the 4 — so the residual stands at 4 unmitigated, and the only gate still outstanding is (a).

---

**B29 — fleet coverage has moved, and fallen**: live re-check at 12:01, two independent samples ~5 min apart (7,159/7,186 total non-fixture rows; 664/668 carrying `LOCAL_TYPE` or `LOCAL_COMPANY_ID`) both land at ~~**9.26–9.28%**~~, down from the ~11.8% reported earlier tonight. The fleet is actively growing faster than the two-point-reprocessed count in this same window (+27 total rows vs. +4 reprocessed) — directionally consistent with the fall being caused by backlog ingestion outrunning reprocessing throughput, not by reprocessing regressing, though this specific causal read was not independently confirmed beyond the one short window measured.

⚠️ **SUPERSEDED 08-09 13:39 UTC — the fall has reversed, and the AI leg is not why (B33.8).** Same query, same fixture exclusion, now including the `NAME` sweep: **972 / 7,307 = 13.30%** carrying `LOCAL_TYPE` or `LOCAL_COMPANY_ID`. The rise is throughput on the local leg, not the AI leg — of the 972, only **20** carry an AI-sourced value. The 08-07 causal read above is consistent with what happened next: ingestion has since flattened (7,435 rows, unmoved across the whole 13:33–13:51 window) while reprocessing kept running, so the ratio recovered. Separately, and **not** to be read as coverage: `BASE_EXTRACTION_COMPLETED` now reads true on 5,718/7,307 (78.25%), but 4,583 of those are the 12:44 bulk backfill and represent no extraction at all (B33.2). **The two-point-reprocessed count is 1,088 (14.9%), not 5,718 (78.25%)** — quote the former.

Also re-verified in this pass: **B1 (the pipeline wedge) is not reproducing right now** — live check at 08-07 11:36: zero executions running longer than 1 minute, across every workflow (the earlier 61/57/50-running-at-105-min picture is gone). This is **one snapshot, not B1's full 3-consecutive-30-min-bucket acceptance proof** — B1 stays OPEN below, not moved to PROVEN, but the standing wedge is not present at this instant. Separately, **B2 is not clear**: 31 `drive api` `error` executions in the last 60 minutes, a live, current, nonzero count.

---

### B33 — the AI leg is live. Every B26–B32 figure re-derived. **The deletion gate is unchanged at 4 / 0, and it could not have moved the other way.** Two new live defects found, one of which makes the AI-vs-local metric unreadable at any sample size.

*(measured live 2026-08-09 **13:33–13:57 UTC**, DB clock, `supabase-db-shlomo-laptop` + `n8n-postgres-shlomo-laptop`; every query in `tmp/b33/`, replay harness in `tmp/b33/replay/`. **Every headline is two independent samples ~18 min apart**, per B29's convention)*

**In flight during this pass, stated because the file requires it:** `COMPLETED` climbed 5,634 → 5,667 (+33) across the window; `DOUBLE` held flat at **201** (the other lane reports 635→554 — that is a different population, not this one; raw non-fixture `DOUBLE` here is 201 and did not move); total rows flat at 7,435; `IN_PROGRESS` 436. **A full n8n push landed mid-measurement at `13:34:53 UTC`** — every workflow row in `workflow_entity` updated at that one timestamp, `indoxV2ActionsGlobal01` included. All code read in this section was pulled from the **live published** `workflow_entity` *after* that push, never from the repo blueprints, precisely because the repo and the stack are no longer in step.

---

**B33.0 — When the AI leg actually started, established from data rather than from the brief.**
The task that commissioned this pass stated the flip happened "today at ~14:55 UTC". That is not what the deployment shows, and the difference matters because it sets how much evidence exists.

```sql
select key, value, updated_at from settings
 where instance='incoming-documents-main' and key like 'extraction_%';
--  extraction_ai_enabled | true | 2026-08-05 23:01:12.88495+00   ← value flipped, updated_at NOT touched
```
`settings.updated_at` is therefore **not** an audit trail for this change — it still reads the 08-05 value. The usable evidence is the first row whose selection oracle records an AI-derived source:

```sql
select min(updated_at) from public.incoming_documents
where "SELECTION_DEBUG_BASE" ~ '"(COMPANY_ID|TYPE|DOC_DATE)":"(AI_ONLY|AGREE|DISAGREE)';
--  2026-08-09 13:32:05.42116+00
```
**The AI leg's first observable output is `13:32:05 UTC`, 88 seconds before my first measurement, and the DB clock at that moment was 13:33:24 — so 14:55 UTC had not yet happened.** (The host's local clock is UTC+3, which is the likely origin of the discrepancy.) `Base Document Extraction (local + AI, parallel)` had been executing all day either side of that boundary — 89 runs in the 12:40 bucket alone — so the flip, not throughput, is what changed.

---

**B33.1 — AI-leg volume: 20 rows at 13:39, 37 by 13:57. This is NOT enough for the parity claims, and I am not publishing a rate off it.**

| instrument | sample 1 (13:39) | sample 2 (13:57) |
|---|---|---|
| `SELECTION_DEBUG_BASE` carrying an AI source | **20** of 1,098 with any oracle | **37** of 1,115 |
| `SELECTION_DEBUG_PERTYPE` carrying an AI source | **4** of 701 | — |

Growth over the polled window (`tmp/b33/ai-leg-poll.tsv`, 60 s interval): 5 @13:35 · 6 @13:39 · 9 @13:40 · 11 @13:41 · 18 @13:42 · 20 @13:46 · 20 @13:48 · 23 @13:49 · 26 @13:51 · 32 @13:52 · 36 @13:53 · 37 @13:55. Mean ≈ **1.5 rows/min**, bursty — three flat minutes then six in one. It is gated by `BaseDocEx01` throughput (13 runs in the 13:30 ten-minute bucket), not by Gemini quota or latency.

**Why 37 rows is still not enough, shown rather than asserted.** The same three agreement figures, 18 minutes apart:

| dimension | sample 1 (n=20) | sample 2 (n=37) | movement |
|---|---|---|---|
| `COMPANY_ID` agree | 18/18 (100%) | 34/35 (97.1%) | −2.9 pp |
| `DOC_DATE` agree | 12/17 (70.6%) | 19/32 (59.4%) | **−11.2 pp** |
| `TYPE` agree (exact) | 0/20 | 0/37 | — (B33.6) |

An 11-point swing in one dimension across 20 minutes is what a sample this size does. Publishing either column as "the AI-vs-local agreement rate" would be inventing precision.

**And the naive rate over-predicts, because most base-extraction runs do not produce a new AI-leg row.** Between 13:45 and 14:00 `Base Document Extraction (local + AI, parallel)` executed **71** times (4 errors, 6 running); the AI-leg cohort grew from 36 to 43. **Roughly one base run in five yields a row not already in the cohort** — the base point is substantially re-processing documents it has already seen. Anyone projecting "when will there be 400" must use ~2 rows/min, not the 4.7 base-runs/min the execution table shows.

**The thresholds I would want before quoting any AI-vs-local rate**, stated in advance rather than after seeing a number I like:
- **≥ 400 AI-leg rows** for a headline agreement rate (±5 pp at 95% on a proportion near 90%). At the observed net rate, **~3 hours** — genuinely reachable today, just not inside this pass.
- **≥ 1,000** to break disagreements down by `TYPE` and still have per-type cells worth reading, and to detect a change in a **0.37%** dependency rate at all — at 0.37%, 1,000 rows is the point where the *expected* count of dependency events first reaches ~4. ~8 hours.
- **Neither threshold is reachable inside this session**, and I did not extrapolate to them. **The 400-row re-measurement is worth someone's time later today**; the 4/0 re-measurement is not, for the reason in B33.4.

**What this does not block.** The deletion gate does not need this volume, for a structural reason given in B33.4. Volume is required for the *parity* and *agreement* claims (B26), and those are the ones I am declining to publish.

---

**B33.2 — 🔴 THE POPULATION GATE WENT STALE AGAIN, AND THIS ONE IS A NEW FINDING, NOT A RE-MEASUREMENT.**

B27's error was gating on `AI_EXTRACTION_COMPLETED`. B30 corrected it to `BASE_EXTRACTION_COMPLETED`. **That gate is now contaminated too**, by an event that post-dates B30 by 3½ hours:

```sql
select updated_at, count(*) as rows_at_this_exact_microsecond,
       count(*) filter (where "SELECTION_DEBUG_BASE" like '{%') as with_selection_oracle
from d where lower(coalesce("BASE_EXTRACTION_COMPLETED",''))='true'
group by 1 having count(*) > 20 order by 2 desc;
--  2026-08-09 12:44:28.955877+00 | 4583 | 0        ← one microsecond, 4,583 rows, zero oracles
--  2026-08-06 14:35:15.369299+00 |   29 | 29
```
A single bulk `UPDATE`. **And it is unambiguously not a normal batch write** — the deployment's ordinary batch upsert (`indoxDocBatchUpsert01`) writes in groups of ~50, so listing every shared-microsecond write of the day puts 12:44 in a category of its own:

```sql
select updated_at, count(*) as rows, count(*) filter (where "SELECTION_DEBUG_BASE" like '{%') as with_oracle
from public.incoming_documents where updated_at > timestamptz '2026-08-09 00:00:00+00'
group by 1 having count(*) > 20 order by 1;
--  2026-08-09 12:44:28.955877+00 | 4460 |  0     ← 80x the next largest, zero oracles
--  2026-08-09 13:28:50.74103+00  |   29 |  0
--  2026-08-09 13:30:37.017597+00 |   35 |  0
--  … eleven more, every one of them between 29 and 56 rows (normal batch upserts)
--  2026-08-09 13:49:40.049055+00 |   50 | 12
```
*(4,460 here against 4,583 in the query above because 123 of the backfilled rows have since been touched again and their `updated_at` has moved off the shared timestamp — the two counts are consistent, not contradictory.)*

What those 4,583 rows are:

```sql
select count(*) as backfilled,
  count(*) filter (where coalesce("LINK",'')<>'' and "LINK"<>'MISSING') as have_a_LINK,
  count(*) filter (where "LOCAL_COMPANY_ID" is null and "LOCAL_TYPE" is null and "LOCAL_DOC_DATE" is null) as no_local_values,
  count(*) filter (where "SELECTION_DEBUG_BASE" is null) as never_selected
from d where updated_at = timestamptz '2026-08-09 12:44:28.955877+00';
--  4583 | 4583 | 4583 | 4583
select "STATUS", count(*) from d where updated_at = timestamptz '2026-08-09 12:44:28.955877+00' group by 1;
--  COMPLETED | 4583
```
**All 4,583 are `COMPLETED`, all have a usable `LINK`, none has a single `LOCAL_*` value, and none was ever seen by the selection step.** All 4,583 would otherwise have been claimed for `extract_base_doc` by the live decider. So the flag now carries two meanings — "two-point ran" and "do not queue this again" — and only the first is what B30 needed.

**Consequences, stated plainly:**
1. `BASE_EXTRACTION_COMPLETED='true'` = 5,718 rows non-fixture, of which **4,635 have no evidence of two-point at all** (4,583 from this backfill plus 52 others). **The honest two-point population is 1,088** — rows carrying a `SELECTION_DEBUG_BASE`, which only `Select Base Values` writes.
2. **Those 4,583 documents can never receive the AI leg** without being re-armed. They are past the base gate permanently. Any plan that says "the AI leg will re-measure the fleet" is wrong by 4,583 rows.
3. This is **not** presented as a defect. Suppressing re-OCR of 4,583 already-completed documents is a defensible operational act, and it is very likely another lane's deliberate drain work. What is a defect is that it is indistinguishable, in the column, from a real extraction — and this file had a load-bearing measurement gated on exactly that column.
4. **E3's pattern repeats for the third time**: a population gate that was correct when written and silently stopped being correct. The corrected gate below is provenance-based (`SELECTION_DEBUG_BASE`, `ACTION_LOG`), not flag-based, which is the only form that has survived every one of these.

---

**B33.3 — THE DELETION GATE, re-derived under four independent population gates, twice. All four say 4 / 0, both times.**

The gate must not depend on the contaminated flag, so I ran it three ways — the original (contaminated) flag gate, the corrected oracle-present gate, and the strictest gate available, in which the oracle *itself* states that two-point produced nothing.

| # | population gate | pop | two-point produced nothing | **A: would have LOST the value** |
|---|---|---|---|---|
| 1 | ~~`BASE_EXTRACTION_COMPLETED='true'`~~ (B30's, now contaminated) | 5,718 | 1,914 | **4** |
| 2 | **`SELECTION_DEBUG_BASE` present** (corrected — two-point provably ran) | **1,088** | 308 | **4** (0.37%) |
| 3 | `SELECTION_DEBUG_BASE` says `"COMPANY_ID":"NONE"` (strictest) | 333 | 333 | **4** |

```sql
-- gate 2, the one to quote
select count(*) from d
where "SELECTION_DEBUG_BASE" like '{%'                          -- two-point provably ran
  and "LOCAL_COMPANY_ID" is null and "AI_COMPANY_ID" is null    -- two-point produced nothing
  and "COMPANY_ID" is not null                                  -- yet a value exists today
  and "ACTION_LOG" like '%UPDATE COMPANY_ID%';                  -- and the legacy extractor wrote it
--  4
```
**TYPE is 0 under all three gates**, and the maximal-upper-bound query — every row the legacy type extractor demonstrably touched, with no two-point gating whatsoever — returns 0 as well:

```sql
select count(*) filter (where "ACTION_LOG" like '%UPDATE DOCUMENT_TYPE%')                       as legacy_ran,
       count(*) filter (where "ACTION_LOG" like '%UPDATE DOCUMENT_TYPE%' and "TYPE" is not null) as value_exists,
       count(*) filter (where "ACTION_LOG" like '%UPDATE DOCUMENT_TYPE%' and "TYPE" is not null
                          and upper("TYPE") not in ('UNKNOWN','UNKNWON'))                        as value_is_USABLE
from d;
--  77 | 77 | 0
```
`figure_document_type` has run on 77 documents, produced a `TYPE` on all 77, and **not one of those 77 types is anything but `UNKNOWN`.** With the AI leg live, at a larger n than B30 had, the realised yield is still exactly zero.

**The same maximal bound for COMPANY_ID, which is the number the owner should hold onto:**
```sql
select count(*) filter (where "ACTION_LOG" like '%UPDATE COMPANY_ID%')                             as legacy_ran,
       count(*) filter (where "ACTION_LOG" like '%UPDATE COMPANY_ID%' and "COMPANY_ID" is not null) as and_a_value_exists_today
from d;
--  244 | 4
```
**`figure_company_id` has run on 244 documents and only 4 of them hold a company id at all today.** The other 240 are rows it ran on and failed. There is no gating assumption anywhere in that query — it is the worst case, and the worst case is 4.

**The one way the 4 could have been an under-count, tested and refuted.** B30's query used `AI_COMPANY_ID is null` to mean "the AI leg produced nothing". That column is *also* written by the legacy Gemini action `extract_invoice_google_ai`, and 25 rows prove the confound is real (oracle says `COMPANY_ID:NONE`, yet `AI_COMPANY_ID` is populated). Those 25 would be wrongly excluded from the dependency set. Do any of them also carry the legacy extractor's marker?
```sql
select count(*) as oracle_NONE_but_ai_col_populated,
       count(*) filter (where "ACTION_LOG" like '%UPDATE COMPANY_ID%') as of_which_legacy_also_wrote_it
from d where "SELECTION_DEBUG_BASE" like '%"COMPANY_ID":"NONE"%' and "AI_COMPANY_ID" is not null;
--  25 | 0        ← the confound exists and costs nothing
```
**Zero.** The instrument gap is real and should be fixed, but it does not hide a single dependency row. Same test for TYPE: 2 | 0.

**Re-sampled 18 minutes later at `13:56:53` — all four gates unchanged while their populations moved underneath them** (`tmp/b33/b33-resample.sql`), which is the reproduction this figure has never previously had:

| gate | pop @13:41 | pop @13:57 | **A (COMPANY_ID)** | **A (TYPE)** |
|---|---|---|---|---|
| flag (contaminated) | 5,718 | 5,750 | **4 → 4** | **0 → 0** |
| `SELECTION_DEBUG_BASE` present | 1,088 | 1,115 | **4 → 4** | **0 → 0** |
| oracle says `NONE` | 333 | 333 | **4 → 4** | **0 → 0** |
| maximal, no gating | 244 | 244 | **4 → 4** | **0 → 0** |

**The four rows are the same four documents, by ID, unchanged since 08-06** — `doc_mshnmfmeg3rbg7`, `doc_mshflkl3pwv0mb`, `doc_mshoj178fblos6`, `doc_mshoj3nhhiorqu`. All four still carry `"AI_STATUS":"skipped: extraction_ai_enabled=false"` in their own oracle: they were resolved under the one-legged regime and have not been reprocessed since, so the AI leg has had no opportunity to change their verdict. Three are the WhatsApp camera images (Task #87); the fourth is the client's own company in the filename, which B30.6's retraction already established the filename map does not resolve.

---

**B33.4 — Why the AI leg could not have made the deletion *less* safe. A structural argument, so the answer does not depend on my sample size.**

This is the reason B33.1's thin volume does not block the verdict. From the live `Select Base Values` (published `indoxV2ActionsGlobal01`, read after the 13:34:53 push):

```js
if (prefer === 'AI') { if (a) return {val:a, source:'AI_ONLY'}; if (l) return {val:l, source:'LOCAL_ONLY'}; }
else                 { if (l) return {val:l, source:'LOCAL_ONLY'}; if (a) return {val:a, source:'AI_ONLY'}; }
return { val: null, source: 'NONE' };
```
The dependency set is the intersection of *(two-point produced nothing for `COMPANY_ID`)* and *(the legacy extractor wrote the value)*. Enabling a second source can only ever move a row **out** of the first term — a row that had no value may now have one; a row that had one cannot lose it, because `pick()` never returns `NONE` when either input is present. The second term is historical and unaffected by a flag. Therefore **A(both legs) ≤ A(local only) for any fixed row set**, and the 4 measured under the one-legged regime is a genuine **upper bound**, not a floor.

**Confirmed empirically, in the direction predicted.** On the 20-row AI cohort, the AI leg supplied a value the local leg could not on **1** `COMPANY_ID` and **3** `DOC_DATE`s, and **0** `TYPE`s — it moved rows out of the "produced nothing" set and put none in:
```sql
select count(*) filter (where "LOCAL_COMPANY_ID" is null and "AI_COMPANY_ID" is not null) as ai_rescued_company,
       count(*) filter (where "LOCAL_TYPE" is null and "AI_TYPE" is not null)             as ai_rescued_type,
       count(*) filter (where "LOCAL_DOC_DATE" is null and "AI_DOC_DATE" is not null)     as ai_rescued_date
from d where "SELECTION_DEBUG_BASE" ~ '"(COMPANY_ID|TYPE|DOC_DATE)":"(AI_ONLY|AGREE|DISAGREE)';
--  1 | 0 | 3
```

---

**B33.5 — B26 value-parity re-derived. One claim held exactly, one broke, and the head-to-head is not yet publishable.**

| claim | B26 (one leg) | **B33 (both legs)** | did the AI leg change the answer? |
|---|---|---|---|
| `COMPANY_ID` vs `LOCAL_COMPANY_ID` (raw) | 0 / 525 | **0 / 751** | **No.** Still exactly clean at a 43% larger n |
| `TYPE` vs `LOCAL_TYPE` (raw, caseless) | 0 / 660 | **8 / 972** | **Yes — this one broke** |
| `COMPANY_ID` vs `SELECTED_COMPANY_ID` (final) | 7 / 5,424 | **8 / 5,587** | No, +1 and a new shape |
| `TYPE` vs `SELECTED_DOC_TIPE` (final) | 30 / 430 | **31 / 592** | No — rate fell 7.0% → 5.2% |

**The 8 new raw-`TYPE` mismatches are not an AI artefact.** Seven are `TYPE='UNKNOWN'` sitting against a populated `LOCAL_TYPE` (`garbage` ×3, `invoice` ×3, `shipment` ×1) with `AI_TYPE` **null** — i.e. the local leg extracted a type and the `TYPE` column never took it. The eighth is `doc_mshtkgvz8vwh50`, `TYPE='INVOICE'` vs `LOCAL_TYPE='balance_sheet'`, which the selection step resolved to `SELECTED_DOC_TIPE='BALANCE_SHEET'`. All eight predate the flip and carry `"AI_STATUS":"skipped..."` or no AI status. **This is a local-leg/write-back gap that B26 did not have the sample size to see, surfaced by the larger n, not by the AI leg.**

**The final-output `COMPANY_ID` mismatches: the known cluster is unchanged, plus one new shape worth naming.** 6 of the 8 are the same `LOCAL=570042077` / `AI=516431434` / `SELECTED=516431434` cluster B26 flagged — still open, still untriaged, and now visibly a *legacy-Gemini*-vs-local conflict rather than a two-point one (their oracles read `"COMPANY_ID":"LOCAL_ONLY"`, so the base AI leg never participated). The new one is `17738429303612vjwrf`, whose `SELECTED_COMPANY_ID` is **`לסה ויז'ן` — a company *name* in a column that holds ids everywhere else**. Filed, not fixed; it is one row and it is not in the deletion path.

**The head-to-head that had no live evidence before this pass — reported, but NOT to be quoted as a rate (n=20, then n=37).**

| dimension | both legs present | agree | second sample (13:57) |
|---|---|---|---|
| `COMPANY_ID` | 18 | **18 (100%)** | 34/35 (97.1%) |
| `DOC_DATE` | 17 | 12 (70.6%) | 19/32 (59.4%) |
| `TYPE` | 20 | 18 caseless (90%) / **0 exact** | 34/37 caseless (91.9%) / **0 exact** |

At these n these are indicative only — see the 11-point `DOC_DATE` swing in B33.1. The `TYPE` row is worse than indicative: it is unreadable at any n, for the reason in B33.6.

**The individual disagreements, named — because at this n the rows are more informative than the rate.** The single `COMPANY_ID` conflict is `1774133785344b5sb3p` (`וולפמן-00892`): `LOCAL=512194515` vs `AI=515661520`, resolved `DISAGREE_PREFER_LOCAL` to the local value, which is also what `COMPANY_ID` and `SELECTED_COMPANY_ID` hold. **This is the first genuine AI-vs-local company conflict this deployment has ever recorded** — one row, correctly resolved by the documented precedence, and not evidence of anything yet. Of the 3 genuine `TYPE` disagreements, **2 are the B33.7 `'unknown'` defect** (`LOCAL='unknown'` vs `AI='INVOICE'`, both landing on `TYPE='UNKNOWN'`) and 1 is a real content disagreement (`order` vs `BALANCE_SHEET`). So two thirds of the only readable TYPE disagreements are caused by a defect in the selector rather than by the extractors differing.

---

**B33.6 — 🔴 NEW DEFECT, live right now: the `TYPE` provenance label is decided by letter case, so `DISAGREE_PREFER_LOCAL` is reported on documents where both legs said the same thing.**

Every one of the first AI-leg rows reports `"TYPE":"DISAGREE_PREFER_LOCAL"`. Most of them are not disagreements:

| ID | `LOCAL_TYPE` | `AI_TYPE` | reported source |
|---|---|---|---|
| `1773131371980ctm3a0` | `shipment` | `SHIPMENT` | `DISAGREE_PREFER_LOCAL` |
| `17724871330295oq72` | `shipment` | `SHIPMENT` | `DISAGREE_PREFER_LOCAL` |
| `1773077431813btf5ki` | `balance_sheet` | `BALANCE_SHEET` | `DISAGREE_PREFER_LOCAL` |
| `17723496536965cq42s` | `order` | `BALANCE_SHEET` | `DISAGREE_PREFER_LOCAL` ← the only genuine one |

The cause is one line in the live `Select Base Values`: `pick()` compares `if (l === a)` on the **raw** strings, while the canonicalisation to uppercase happens *afterwards*, on the winner only:
```js
if (l && a) { if (l === a) return { val: l, source: 'AGREE' };  … 'DISAGREE_PREFER_LOCAL' }
…
out.TYPE = typePick.val ? String(typePick.val).trim().toUpperCase() : null;   // canonicalised AFTER the verdict
```
The local extractor emits lowercase (`shipment`), Gemini emits uppercase (`SHIPMENT`). They never match literally.

```sql
select count(*) filter (where "LOCAL_TYPE" is not null and "AI_TYPE" is not null) as both_present,
       count(*) filter (where "LOCAL_TYPE" is not null and "AI_TYPE" is not null
                          and upper(trim("LOCAL_TYPE"))=upper(trim("AI_TYPE")))    as agree_caseless,
       count(*) filter (where "LOCAL_TYPE" is not null and "AI_TYPE" is not null
                          and trim("LOCAL_TYPE")=trim("AI_TYPE"))                  as agree_EXACT
from d;
--  101 | 92 | 0        ← exact agreement is zero on every row in the fleet, ever
```
**Severity, stated precisely so it is not over- or under-sold.** The selected **value is correct** — `prefer='LOCAL'` picks the local string and the next line uppercases it, so no document gets a wrong `TYPE` from this. What is destroyed is the **instrument**: `SELECTION_DEBUG_BASE`'s `TYPE` field can only ever report `DISAGREE_PREFER_LOCAL` whenever both legs fire, so the AI-vs-local TYPE disagreement rate is **unmeasurable at any sample size until this is fixed**. It also means B30.4's oracle distribution table, and any future one, cannot be read for TYPE. Fix is one line (`l.toUpperCase() === a.toUpperCase()`, or canonicalise before `pick`). **Not fixed here** — it lands in `indoxV2ActionsGlobal01`, which another lane holds mid-change.

---

**B33.7 — Second new defect, same node: `has()` treats the literal string `'unknown'` as a real extracted value, so a local `unknown` beats a confident AI answer.**

`pick()`'s `has = v => v !== null && v !== undefined && String(v).trim() !== ''` counts `'unknown'` as present. `docBaseDecide`'s own `isBlank()` in the *same workflow* does not — it lists `'unknown'` explicitly as blank. So the two halves of the router disagree about what a value is. Live consequence, `17731624511561v888b`: `LOCAL_TYPE='unknown'`, `AI_TYPE='INVOICE'` → `TYPE='UNKNOWN'`, the AI answer discarded.

```sql
select count(*) filter (where lower(trim(coalesce("LOCAL_TYPE",''))) in ('unknown','unknwon')) as local_type_literal_unknown,
       count(*) filter (where lower(trim(coalesce("LOCAL_TYPE",''))) in ('unknown','unknwon')
                          and "AI_TYPE" is not null and upper(trim("AI_TYPE")) not in ('UNKNOWN','UNKNWON')) as ai_had_a_real_type_and_lost
from d;
--  123 | 2
```
**2 documents today, out of a standing population of 123 that will hit this as the AI leg reaches them.** Small now, grows linearly with AI-leg coverage. Filed, not fixed, same lane conflict as B33.6.

---

**B33.8 — B29 coverage re-derived: the fall reversed, and the AI leg is not the reason.**

```sql
select count(*) as non_fixture_total,
       count(*) filter (where "LOCAL_TYPE" is not null or "LOCAL_COMPANY_ID" is not null) as local_leg_covered,
       round(100.0*count(*) filter (where "LOCAL_TYPE" is not null or "LOCAL_COMPANY_ID" is not null)/count(*),2) as pct
from d;
--  7307 | 972 | 13.30
```
**13.30%**, up from B29's 9.26–9.28% at 08-07 12:01 — and **13.74%** (1,004/7,307) on the 13:57 re-sample, so it is still climbing, roughly +0.44 pp in 18 minutes. Of those 972, exactly **20** carry an AI-sourced value (37 of 1,004 at the second sample) — the rise is local-leg throughput. Do **not** substitute the `BASE_EXTRACTION_COMPLETED` rate (78.25%) for coverage: 4,583 of those rows are the 12:44 backfill and represent no extraction (B33.2). The defensible reprocessed figure is **1,088 / 7,307 = 14.9%**.

---

**B33.9 — B32 per-type demand re-derived against the LIVE deciders, and it moved a long way.**

Harness: `tmp/b33/replay/replay-decide-2stage.js`, unchanged from B32, but the four decide bodies were re-extracted from the **live published** workflows (`tmp/b33/extract-live-decide.py`) rather than the repo — necessary, because live `decide_base.js` is 19,963 chars against the repo's 18,549, i.e. the pushed `figure_company_offline` and base-retry changes are in the stack. Replayed over all **7,307** non-fixture rows in the driver's real two-stage order.

| figure | B32 (08-09 09:56–10:25) | **B33 (13:44)** |
|---|---|---|
| `extract_base_doc` now | 3,638 | **966** |
| `extract_per_type` now | 27 | **23** |
| `extract_per_type` after the base backlog clears | 3,027 | **350** |
| legacy per-value demand | 5 | **1,214** |
| `figure_company_offline` (did not exist) | — | 196 (counterfactual) |

**The 5 → 1,214 jump is a consequence of the backfill, not of the AI leg, and it is the finding in this sub-section that matters.** `docBaseDecide` claims a row for `extract_base_doc` before its type lane ever sees it. The 12:44 backfill pushed 4,583 rows past that gate in one statement, so their type lanes now see them for the first time — and 1,201 of the 1,214 are `query_doc_total_amount` in the shipment lane alone (2,263 non-fixture `SHIPMENT` rows, 2,141 of them with no `DOC_TOTAL_AMOUNT`). **Tranche 3 — the `query_*` per-value extractors — just became materially more expensive to delete.** It was never in tranches 1–2 and this does not touch the Tranche 1/2 verdict, but B30.5's "separate tranche needing its own B30-style measurement" now has a number attached, and it is not small.

---

**B33.10 — `ACTION_LOG` as an instrument: where it is trustworthy now, and where it is still degraded. Say this before anyone re-uses it.**

The `Build Per Type Upsert` / `Build Base Doc Upsert` wipe is **fixed and live** — confirmed by reading the published node, not the repo:
```
ACTION_LOG = {{ (($json.ACTION_LOG || $('Action: Extract Base Doc').item.json.ACTION_LOG) || '') + ', Extract Base Doc, ' … }}
```

| marker | rows carrying it | rows that provably did the thing | coverage |
|---|---|---|---|
| `Extract Per Type` | 128 | 701 (`SELECTION_DEBUG_PERTYPE`) | **18.3%** (was 12% at B32) |
| `Extract Base Doc` | 408 | 1,088 (`SELECTION_DEBUG_BASE`) | **37.5%** |
| `UPDATE COMPANY_ID` (legacy) | 244 | — | **not affected by the defect** |
| `UPDATE DOCUMENT_TYPE` (legacy) | 77 | — | **not affected by the defect** |
| `BASE APITOOLS RETRY` (B32 FIX 3) | 0 | — | deployed, not yet fired |

**Where it is trustworthy: the two legacy markers, which is exactly where this pass leaned on it.** `Build: UPDATE COMPANY_ID` and `Build: UPDATE DOCUMENT_TYPE` are different nodes and never had the `$json` defect, so the 4/0 headline rests on the sound half of the instrument. **Where it is still degraded: the two-point markers**, at 18.3% and 37.5%. Those recover only as rows re-run — the fix is not retroactive — so **`ACTION_LOG` must not be used as a two-point population gate before roughly 2026-08-10**, and `SELECTION_DEBUG_BASE`/`SELECTION_DEBUG_PERTYPE` should be used instead, which is what B33.3 did.

---

**B33.11 — Fixture exclusion, including the `NAME` gap B30 opened.**
128 rows excluded on `NAME` alone, all anchored at position 1, all from registered prefixes, zero coincidental matches (up from B30's 124):

| prefix in `NAME` | rows | sample |
|---|---|---|
| `sv3f_` | 87 | `sv3f_mx_110613.pdf` |
| `sv3s_` | 30 | `sv3s_gb_187620.pdf` |
| `mailorg_` | 11 | `mailorg_110160.pdf` |

Non-fixture fleet **7,307 of 7,435**. **B13's second contamination channel is still open**: `scripts/test-fixture-prefixes.yaml` still does not register `NAME` as a marker column, so `fixture-sweep.py` still cannot see these 128 rows and every analysis has to re-implement the sweep by hand, as this one did. Unchanged since B30 filed it.

---

**B33.12 — 🟠 A Tranche-2 interaction that did not exist when B30.5 was written: `figure_company_offline` is now LIVE, and deleting `figure_company_id` PROMOTES it from last resort to first resort.**

B30.5's Tranche-2 plan says deleting the branch sends `!COMPANY_ID` rows "directly to `update_status_missing_company`". That was true on 08-09 morning. It is **no longer true**, because B31.3's resolver was deployed in the 13:34:53 push and sits inside the same `if (!doc.COMPANY_ID)` block, immediately below the branch being deleted — with its own comment stating the ordering is deliberate:

```js
if (!doc.COMPANY_ID) {
  if ((!doc.FIGURE_COMPANY_COMPLETED || doc.STATUS === 'ACTION_RESTART') && !!doc.LINK)
    return 'figure_company_id';                                    // ← Tranche 2 deletes THIS
  // "Sits AFTER figure_company_id on purpose: that resolver is strictly stronger,
  //  so this only runs once it is exhausted or unavailable."
  if (!isBlank(doc.NAME) && !String(doc.ACTION_LOG||'').includes('FIGURE COMPANY OFFLINE'))
    return 'figure_company_offline';
```
**Deleting the stronger resolver inverts the invariant its own comment asserts.** I measured the actual effect rather than reasoning about it — the live decider replayed over all 7,307 non-fixture rows, with and without the branch (`tmp/b33/replay/tranche2-counterfactual.js`, which aborts if the branch text has moved):

```
   figure_company_id            4 ->    0   (-4)
   figure_company_offline     137 ->  141   (+4)
   … every other action unchanged, including update_status_missing_company
```
**The entire live blast radius of the Tranche-2 deletion, today, is 4 documents** — and they do not terminalise, they divert to the offline resolver. **They are a different 4 from B30's historical 4** (which are already resolved and unaffected by any deletion):

| ID | NAME | will the filename map resolve it? |
|---|---|---|
| `doc_mshflhgskcu97p` | `מ.ש. הכהנים חומרי בנין בע"מ-01232` | **No** — client's own company, not in `company_name_by_identifier` |
| `doc_mshflkjqf97aso` | `מ.ש. הכהנים חומרי בנין בע"מ-72227` | **No** — same |
| `doc_mshflhfp9h2e9q` | `מ.ש. הכהנים חומרי בנין בע"מ-19611` | **No** — same |
| `doc_msi4zpweax024e` | `סריקה_20260728_10 (4).jpg` | **No** — scan filename, no company token |

This is B30.6's retraction confirming itself a third time: `מ.ש. הכהנים` is the **client**, so the supplier map gets no hit. So all 4 fall through the offline resolver to `MISSING_COMPANY_ID` on the following pass. At the legacy extractor's measured conditional hit-rate (4/185 = 2.16%), the **expected** loss across these 4 is **0.09 documents**.

**The risk this creates is not loss, it is a false positive.** Once `figure_company_id` is gone, `figure_company_offline` is the *only* company resolver for link-bearing rows, and B31.3's own measured hazard applies to it undiluted: unanchored `NAME.includes(company_name)` against a map containing 3-character names (`טסה`, `BDI`, `כתר`, `נגב`, `בזק`) **disagreed with the existing `COMPANY_ID` on 122 of 6,117 rows (2.0%)** — the G58 rule-F3 defect class that cost this deployment 2,432 documents. It is fill-only, so it cannot overwrite; but the rows it now owns are precisely the ones with no value to protect them. **Tranche 2 must therefore ship with the minimum-name-length guard B31.3 recommended and never shipped**, or it converts a 4-row non-event into an unbounded mis-attribution surface.

---

**🔻 B33.13 — VERDICT: is the legacy-extractor deletion safe at the new number?**

**Tranche 1 (`figure_document_type`) — YES, safe, and the evidence is now stronger than it was.** Realised yield is **0 of 77** rows fleet-wide with the AI leg live, measured with no gating assumptions at all. It has never produced a usable `TYPE` on any document in this deployment's history. It is dead code. The Tranche-1 deletion does not need the AI leg, the suites, or any further measurement to be justified on *loss* grounds.

**Tranche 2 (`figure_company_id`) — the number is unchanged at 4, and 4 is an upper bound, not an estimate.** **Four** population gates spanning 244 → 5,750 rows all return 4, **twice, 18 minutes apart, while three of the four populations grew underneath them**; the maximal no-assumptions bound (244 rows the extractor ran on, 4 with a value today) returns 4; the one instrument confound that could have hidden rows returns 0; and B33.4 shows the AI leg is structurally incapable of raising it. Residual exposure is 4 documents in 1,088 (**0.37%**, down from 0.46% because the population grew, not because anything was fixed), all landing in the already-visible, already-populated `MISSING_COMPANY_ID` state (386 rows), with no data destroyed.

**Independently confirmed at the routing level, which is stronger than the row count**: replaying the live decider with and without the branch moves **4 documents and nothing else** (B33.12), and they divert to a resolver rather than terminalising. The deletion's live blast radius is measured, not extrapolated.

**But the deletion must still NOT be executed, and the reasons are not the number.**
1. **The owner's gate is 7 suites green. It is still 0/7 (B24).** That gate was never conditional on the AI leg and this pass does not satisfy it.
2. **The stack is mid-change by three other lanes, and `indoxV2ActionsGlobal01` — the file both tranches edit — moved TWICE inside this 24-minute measurement window.** It was pushed to n8n at `13:34:53` (every workflow row in `workflow_entity` re-stamped), and the repo blueprint's own mtime is `13:43` — another lane editing it while I measured, alongside `syncV3Deliver0001` (13:43), `syncV3FullTest01` (13:47) and `sv3Inject3x001` (13:58). Tranche 1 was verified to compose against an 88-node router; **the live router and the repo blueprint have both moved since, and they are not in step with each other.** **Re-run `tmp/b27/stage-tranche1.py`'s verifier against the current *published* version before anything is applied** — the append-then-delete reasoning in B31.4 holds only for the node set it was checked against, and B31.4's own re-verification was against a file that no longer exists in that form.
3. 🟠 **Tranche 2 has acquired a new precondition since B30.5 was written (B33.12): it promotes `figure_company_offline` to sole company resolver, and that resolver still ships without the minimum-name-length guard its own hazard analysis called for.** Ship the guard first, or Tranche 2 trades a 4-row non-event for a 2.0%-false-positive surface on the rows least able to absorb it. **This, not the dependency count, is now the substantive technical blocker on Tranche 2.**
4. **The two defects in B33.6/B33.7 sit in the same node the deletion touches.** They should be fixed in the same window, not in a separate pass that re-opens the file.

**What I am explicitly NOT claiming.** That the AI leg's agreement/disagreement rates are known — they are not (n=37 at the second sample, **43** by 14:01, and an 11-point swing in `DOC_DATE` across 18 minutes), and for `TYPE` they are unmeasurable at *any* n until B33.6 is fixed. That the AI leg improves coverage — 37 of 1,004 covered rows, too early. That the 4 will fall to 0 — the AI leg rescued **1** `COMPANY_ID` in 37 rows, which is directionally right and statistically nothing. That the fleet-wide picture will hold once the AI leg has run widely — **it structurally cannot reach 4,583 of these documents at all** (B33.2), so "wait and re-measure" will never produce a whole-fleet two-legged number without a re-arm.

**One-line answer for the owner: the deletion is safe at 4/0 on the evidence, the AI leg did not change that and could not have made it worse, and the thing still blocking it is the suite gate and a router that three lanes are editing — not the measurement.**

---

## B. OPEN — what "everything solved" still requires

Ordered by what blocks what. Each has a single acceptance proof; nothing counts without it.

### B1 — the pipeline is wedged again  🔴 blocks everything downstream
```
Sync v3 Deliver             61 running, oldest 18:16   (~105 min)
Sync Processor - drive-gdoc 57 running, oldest 18:16
Process Document            50 running, oldest 18:16
last 90 min: 193 canceled · 193 canceled · 126 error + 89 canceled
```
The 900/840/600 timeout ladder should have killed these at ≤15 min. It didn't.
**Acceptance proof:** zero executions older than their workflow's `executionTimeout`, sustained
across 3 consecutive 30-min buckets.

### B2 — zero n8n workflow errors
Current real (status-split, restart debris excluded): `Process Document` 126 error / 89 canceled ·
`Figure COMPANY_ID` 56 canceled · `Upload Doc To API TOOLS` 90 canceled · `drive api` 24 error ·
`gmail api` 14 + `imap smtp` 14 (the `labels/add` 500s) · `Balance Sheet Extractor v2` 11 error.
**Acceptance proof:** a 60-min window with zero `error`, zero `canceled`, and zero `crashed`
that is not push debris — each remaining class named and closed, not filtered out.

### B3 — full INDOX suite green (7 suites)
Blocked: suites are disabled until fixtures cannot touch production.
**Acceptance proof:** `./bbox indox test` → 7/7, run with suites re-enabled, twice consecutively.

### B4 — fixture isolation (the reason B3 is blocked)
392 stored files are 28–40 byte placeholders (**386 `.pdf` = 49% of all stored PDFs**), 0 with
`ocr_cache`, 33 sitting in the backlog as permanently-unresolvable `MISSING_COMPANY_ID`.
Fixtures still live in the production table; a crashed suite still mutates it.
**Acceptance proof:** a deliberately-crashed suite leaves `incoming_documents` byte-identical;
a lint gate fails when the real unanchored-uid defect is re-introduced.

### B5 — `q_v3_date_base` takes a filter boundary as DOC_DATE
`תאריך01/01/1980 << 31/12/2029` → `DOC_DATE=01/01/1980`. Blocks `bs` + 2 `pipeline` lanes.
**Acceptance proof:** `bse2e_bs1` and `plb_bs` extract their real print date; sibling `q_v3_*`
queries swept for the same "first value after label" shape.

### B6 — the consolidation itself  🟡 partly staged, acceptance criterion CORRECTED

> **The previous acceptance proof on this line was wrong and could never pass.** It read:
> "`figure_company_id` dispatch falls to the base-resolve-rate floor and stays there for 3 buckets;
> **then the steps are deleted**". Those two clauses contradict each other. The floor is non-zero *by
> design* — a document whose company base extraction cannot resolve **must** still reach the 32-node
> resolver — so arriving at the floor proves the step is doing real work and must be **kept**.
> Measured 2026-08-06 20:00–20:30: at the floor the old step was carrying **54–100%** of live
> document flow. Deleting it there strands every document base extraction misses.

**PROVEN — the self-skip the two-point design was built on works.** Cohort of 152 documents
base-extracted in the 4 h to 20:24 (DB clock): 52 had their company resolved by base extraction →
**0 of 52** were then sent to the old resolver; 100 did not resolve → 84 went to the old resolver,
which is the designed fallback. Per 30-min bucket, `old_step_fired` tracks `unresolved` exactly and
`old_step_fired_on_resolved` is **0 in every bucket since 16:00**:

| bucket | base-extracted | resolved by base | unresolved (= floor) | old step fired | fired on a **resolved** doc |
|---|---|---|---|---|---|
| 20:00 | 12 | 0 | 12 | 12 | **0** |
| 19:30 | 1 | 0 | 1 | 1 | **0** |
| 19:00 | 7 | 0 | 7 | 7 | **0** |
| 18:30 | 23 | 2 | 21 | 21 | **0** |
| 18:00 | 26 | 17 | 9 | 8 | **0** |
| 17:30 | 27 | 8 | 19 | 19 | **0** |
| 16:30 | 31 | 18 | 13 | 12 | **0** |

Live floor, computed from this window (not reused from any earlier figure): 197 documents landed
base extraction, 91 resolved → **46.2% resolve / 53.8% floor**. The last three buckets resolved
**0/20** — that cohort is 20 `MISSING_COMPANY_ID` rows with no `LOCAL_COMPANY_ID` and no
`AI_COMPANY_ID`, so its floor is 100%.

**Backfill-free justification.** Last bulk write to `incoming_documents` was the **14:30** bucket
(5,252 rows, 1,188 `FIGURE_COMPANY_COMPLETED` flags). Every bucket from 15:00 touched 12–282 rows,
consistent with pipeline throughput; `pg_stat_activity` showed no non-idle writer. Independently the
confound only points one way: a backfill writing `COMPANY_ID` can only **suppress**
`figure_company_id` dispatch, so it cannot manufacture a "still firing" reading.

**KEEP, do not remove** — `Action: Figure COMPANY_ID` / `Figure Document COMPANY_ID` in
`indoxV2ActionsGlobal01`, and the `query_*` steps in `indoxV2ActionsGDoc01` / `indoxV2ActionsShip01`.
They are **declared fallbacks at a non-zero floor**, not dead code. `Decide GDoc Action` runs
`extract_per_type` first and each `query_*` only for a value the per-type extractor left blank *and*
unflagged. Residual across the 211 per-type-done rows: `query_invoice_id` 12 · `query_doc_date` 2 ·
`query_doc_total_amount` 15 · `query_purchase_id` 13 · `query_shipment_id` 25.

**The real remainder was ingestion, not the state machine.** `indoxProcessDocument01` was a **third**
extraction point: `Call 'Figure Document COMPANY_ID'` at `mode: each`, with **no guard at all** —
not on `COMPANY_ID`, not on `FIGURE_COMPANY_COMPLETED` — so it fired once per ingested document
forever. Same three buckets, documents dispatched to the 32-node resolver: **ingestion 54 / 40 / 67**
vs **state machine 7 / 1 / 12**.

**STAGED (not deployed — needs a push window; see sequencing below):**
- `indoxProcessDocument01`: `Call 'Figure Document COMPANY_ID'` **replaced by one `Call BaseDocEx01`**
  (`HASH = file_hash`, `mode: each`, `waitForSubWorkflow`, `onError: continueRegularOutput`) at the
  removed node's verbatim position `[736, 320]`. `company_id` now comes from `BaseDocEx01.COMPANY_ID`;
  `company_name` from `settings.company_name_by_identifier[COMPANY_ID]` — the same companies map this
  workflow already loads via `Companies Loader`, shape confirmed against a live execution payload.
- `indoxProcessDocument01`: orphaned `Extract CompanyName` **deleted** (no incoming connection).
- `indoxV2ActionsGlobal01` / `Decide DOC BASE Action`: added the supabase TEXT-boolean normalisation
  that `Decide GDoc Action` always had and this node never did (see D).

**STILL OPEN, with the reason it could not be staged:** `Document OCR` and the three
`documentJsonQuery` nodes stay in `indoxProcessDocument01` for now.
`BaseDocEx01` ingests by `LINK`/`HASH` only — its `Upload+OCR` maps exactly `{LINK, HASH, ID}` and
forwards no binary — while `indoxProcessDocument01` is a **binary-in** workflow (all three callers
pass `workflowInputs: {}` and rely on binary passthrough). `indoxV2UploadApiTools01` has a binary
branch, but it has fired **0 times in 2,345 executions in 24 h** (1,913 hash · 1,014 link-download),
so there is no proven binary path into the shared uploader. Cutting `Document OCR` removes the only
step that turns the caller's binary into a `file_hash`, leaving `BaseDocEx01` nothing to key on.
Separately, `Select Base` returns no `invoice_id` / `shipment_id` / `purchase_id` — those are
**point-2** values — and they are consumed by `indoxGmailLinkDownloader01` (`invoice_id`,
`shipment_id`) and `SyncProcGDoc0001` (`purchase_id`). Removing the three queries without a point-2
producer breaks three live callers. That last step belongs with **B7** (thin sync), where the
document enters as a thin row and the state machine owns both extraction points.

**Acceptance proof (corrected):** (a) `figure_company_id` dispatch **attributable to
`indoxProcessDocument01`** falls to **zero** for 3 consecutive buckets — the state-machine floor is
expected to remain non-zero and is not part of the gate; (b) `is_ok`, `company_id`, `company_name`,
`document_type`, `invoice_id`, `shipment_id`, `purchase_id`, `error` still populate for all three
callers; (c) suite stays 7/7.

#### B6 addendum — the `MISSING_LINK` / `DOUBLE` finding is NOT a legacy override  ⚠️ attribution corrected

A `plc_na_double`-shaped row was reproduced live reaching `STATUS=MISSING_LINK`, and attributed to
the legacy `indoxProcessDocument01` lane overriding the v2 driver's terminal `DOUBLE` verdict.
**The legacy lane cannot be the writer.** `indoxProcessDocument01` contains **0** occurrences of
`ACTION_LOG`, **0** of `MISSING_LINK`, and **0** upsert nodes — it returns JSON to its three callers
and writes nothing itself.

The writer is **v2**: `Build: Call 'Incoming Document Batch Update' - STATUS MISSING_LINK` in
`indoxV2ActionsGDoc01` and `indoxV2ActionsShip01`, which emits exactly the observed ACTION_LOG label.

**The driver's guard is correct and holds.** `Switch1` in `indoxV2Driver01` tests `$json.ACTION`
against a 25-entry list containing `no_action_double`, `no_action_merged`, `no_action_paused` and
`no_action_garbage` on **output 0**, ahead of every `DOC_TYPE` output, with no `allMatchingOutputs` —
so any doc-base terminal ACTION goes to DOC BASE only and never reaches a per-type router. (The three
per-type deciders do lack their own `DOUBLE`/`MERGED` guards, but `Switch1`'s ACTION precedence means
that is not reachable through the driver.)

**The row reached GDoc because its ACTION was not `no_action_double`.** `docBaseDecide` deliberately
no longer returns `no_action_double` from `STATUS` alone — the resolve_double work removed the
unconditional `if (doc.STATUS === 'DOUBLE') return 'no_action_double';`, with an in-code comment
stating that check "is exactly what made DOUBLE terminal: a wrongly-flagged row could never recover".
With `dup.match` false, the row is **designed** to fall through and resume normal processing. So
`indoxV2Driver01 / Determine Action Tests`' documented `status=DOUBLE no duplicate → no_action_double`
is **stale documentation superseded by the 2026-08-06 resolve_double change** — code and doc-node
disagree, and the code is the newer deliberate decision. Owner: resolve_double / B8, not B6.

**Live scope: zero.** 144 `MERGED` tombstones → **0** acted on after the merge. 176 rows holding a
double verdict (plus 61 `COMPLETED`, 4 `PAUSE`, 3 `NEEDS_REVIEW`, …) → **0** subsequently written
`MISSING_LINK`. Only **2 rows in 6,733** have ever been written `MISSING_LINK`: `ex_upd` and `ex_skp`,
both `COMPANY_ID='C1'`, no `SOURCE_TYPE`, no `SYNC_NAME`, no `LINK` — **fixtures**, not client
documents — and for both the verdict was *correct*, with the log showing the designed sequence
`find_link` → `SEARCH_IN_DRIVE_COMPLETED` → `update_status_missing_link`. **No client document has
had a terminal verdict overwritten.**

Consequence for this item: the `indoxProcessDocument01` consolidation staged above would not have
changed this outcome by a single row. It stands on its original merits — an unguarded third
extraction point dispatching 54/40/67 per bucket against the state machine's 7/1/12 — and **not** on
this finding. Related: 5 fixture-shaped rows are sitting in the production table → **B4**.

### B7 — blind (`thin`) sync — the architecture change, not started
Zero production pipes flipped. `drive-gdoc-scanned` still `processor_wf=SyncProcGDoc0001`.
Prerequisites built and deployed but never exercised: Drive rename on `update_name`, Gmail
outcome labels incl. the mandatory failure label, `TO_EXTRACT` across 7 vocabularies.
**Acceptance proof:** `drive-gdoc-scanned` with `processor_wf` removed, and one document
observed end-to-end: thin row → `TO_EXTRACT` → extraction → `COMPLETED` → Drive file renamed →
Gmail label applied — with nothing from the inventory lost.

### B8 — one row per (COMPANY_ID, DOC_ID), enforced
122 violation groups remain. The index must not go on before the writer is trusted, or it will
reject writes the writer should have merged.
**Acceptance proof:** zero new violation groups across 7 days, then `uq_incdoc_business_key`
created successfully — the creation itself is the proof, since it fails if violations remain.

### B9 — the backlog reaches COMPLETED
`COMPLETED 5200 · DOUBLE 624 · MISSING_COMPANY_ID 341 · MISSING_TYPE 102 · OLD 86`.
**Acceptance proof:** ground-truth in-window count vs `in_indox_table` count, per pipe, converging.

### B10 — nothing is committed
HEAD is **`73cd73b7`**. `git status --porcelain` reports **311 changed paths** at 08-07 07:06
(310 at 05:33; a reported "~355" did not reproduce at either clock, and the figure includes
untracked files —
`scripts/refactor/fixture-delete-scope-lint.py`, `scripts/test-fixture-prefixes.yaml` and
`apps/indox/hooks/fixture-sweep.py` are all still `??`, i.e. the G58 gate itself is untracked).
Everything from the last two days lives in one working tree.
**Acceptance proof:** reviewed commits, CI green (#51).

### B11 — the unanchored-containment sweep is NOT complete  ⚠️ a reported PROVEN that did not reproduce
The claim entered as *"fleet swept: 0 unanchored `SOURCE_LINK` containment joins remain, read or
write."* Re-measured 08-07 05:33 by parsing every node of every blueprint under
`apps/indox/blueprint/n8n/` — **four remain**, all in `syncV3SourcesTest01`:

| node | predicate |
|---|---|
| `PD Row` | `position('#inbox/'\|\|l.platform_id in coalesce(d."SOURCE_LINK",''))>0` |
| `PD W1 Watch` | same, on `dd."SOURCE_LINK"` |
| `PL Row` | same, on `d."SOURCE_LINK"` |
| `PL W1 Watch` | same, on `dd."SOURCE_LINK"` |

**Re-measured 08-07 07:06: still exactly these four, unchanged.** Only the `PB` pair was converted
(A11). The `PG`/`PV` pair was re-keyed onto a different column
entirely (A10). **This is not a live data-loss risk** — all four are SELECT counters and watches, so
the D rule ("a read may reason from containment") permits them, and the workflow is `active=false`.
But they are the same shape that cost 2,432 client documents on the write side, and at a 1-character
`platform_id` each one counts **2,391 of 2,391** `#inbox/` documents as its own fixture — so every
green these four have ever reported is meaningless, in the same way `PB Row`'s was.
**Acceptance proof:** the parse above returns **0** containment predicates naming `SOURCE_LINK` across
all blueprints, *and* `PD`/`PL` re-run with the anchored form returning their own fixture row counts
rather than the whole table.

### B12 — `bs` `SKP03` / `UPD02` — diagnosed (A31), fix not landed
Root cause is settled: the fixture seeds `COMPANY_ID "C1"` but points `LINK` at a real Drive
document, base extraction overwrites `C1`, and the linker then searches an id that no longer exists.
The assertion is also weaker than the rule it stands in for — per `(COMPANY_ID, COMPANY_DOC_ID)`
there is no violation at all. What stays open is the consequence: **the BS update and skip branches
have still never executed**, so nothing is known about them either way.
**Acceptance proof:** the fixture seeds a `LINK` that base extraction cannot re-resolve (or seeds the
resolved id), `SKP03` and `UPD02` each appear exactly once, and the update and skip branches are
observed executing — a green here must mean the branch ran, not that it was skipped.

### B13 — proc-lane fixture contamination  🔴 the contamination channel is still open
`SyncProcGDoc0001` / `SyncProcBS0001` insert into the production `incoming_documents` table under
**production `SYNC_NAME`s** with **no registered fixture marker** — the only fixture trace is
mid-string inside a `SOURCE_LINK` URL. Consequence: both the suite's own cleanup and
`apps/indox/hooks/fixture-sweep.py` are **blind** to the rows these lanes leave behind.
**It cannot be fixed at the cleanup query**, because reaching those rows from the cleanup side needs
a containment DELETE — which is exactly what G58 rule F3 forbids and what the D rule forbids. The fix
has to be at the writer: stamp a registered marker at insert time. A lane is on it.
**Acceptance proof:** every row either lane writes carries a prefix registered in
`scripts/test-fixture-prefixes.yaml`, and a deliberately-crashed proc-lane run leaves
`incoming_documents` byte-identical (this is B4's proof, extended to the proc lanes).

### B14 — ~~G58 does not police INSERT~~ → **CLOSED by A27**
The gate now covers DELETE, UPDATE and INSERT (34 self-tests, `21 mutation / 13 creation`), and
`insert_known_unmarked` is `[]`. Kept as a numbered line rather than deleted, because B13 still
points here for its acceptance proof. **The channel is closed at the gate; B13's own rows are not
yet fixed at the writer.**

### B15 — ~~the "one-branch guard" lint~~ → **CLOSED by A30 (G60)**
Built, self-tested 7/7, wired into `run-gates`. Its one live finding is
`indoxV2GDocTest01 / Batch Config`. The class that motivated it — `normalizeDocType(d.TIPE)` on a
permanently-`undefined` operand, and a `like` predicate that can never match its own column's format
— is now mechanically caught rather than found by hand.

### B16 — `gmail-bs` / PB labels: root cause found, fix in flight
`GB` sets `projection.synced_label`; the node that actually executes reads **`label_keys`**. The two
names never meet, so the step produces **zero operations and no error** — a green built on an empty
result set (E1). Both names are live in `syncV3Deliver0001` and `syncV3Main0001`, confirmed 08-07
07:06; the executing-side rename is in flight.
**Acceptance proof:** one `gmail-bs` document observed carrying its outcome label in Gmail, *and* the
step asserting a **non-zero** operation count — a run that labels nothing must go red, not green.

### B17 — G61 `published-drift-lint` is written and self-tested but wired nowhere  ⚠️ the same defect A28 fixed
Measured 08-07 07:06: `scripts/refactor/published-drift-lint.py` passes its own self-test **5/5**,
and `grep published-drift scripts/refactor/run-gates.py .github/workflows/ci-verify.yml` returns
**nothing**. It is a gate that cannot fail because nothing runs it — the exact shape of A28, still
present in the very cycle that named it. It is plausibly deliberate (the gate is live-only and needs
a DB, and it is built to report NO VERDICT rather than PASS without one), but *deliberate* and
*recorded* are different things, and nothing in the tree records it.
**Acceptance proof:** either wired into `run-gates.py` with its live-only behaviour documented, or
an explicit entry saying why it is intentionally out — and the CI containment check asserting
**both** directions, so the next unwired gate cannot hide.

### B18 — stale `SOURCE_ID`-is-the-sender assertions in three gmail lanes
The suites assert `SOURCE_ID` holds the sender; G37 says the processors are right and the assertions
are what is stale. Until they are corrected, three lanes are red for a reason that is not a product
defect — and a red that means nothing trains people to ignore reds.
**Acceptance proof:** each of the three assertions rewritten against what the processor actually
writes, with G37 green and the lanes green for the right reason.

### B19 — `bs` failure-path cleanup
The failure path does not clean up after itself, so a red `bs` run leaves rows behind. This is B4's
crash-safety problem, scoped to one suite.
**Acceptance proof:** a deliberately-failed `bs` run leaves `incoming_documents` byte-identical.

### B20 — the 12 filed proc rows
Twelve rows filed from the proc lanes remain in the client table. These are B13's already-landed
contamination, counted; removing them is C8.
**Acceptance proof:** the 12 accounted for individually — each either a genuine client document
(kept, with the reason) or a fixture row (removed by explicit `"ID" IN (…)` under backup, never by
predicate).

### B21 — `gdoc` genuinely fresh run, 08-07 11:36: still 4/5, but the failure shape has moved
Execution **388755**, 434s total. Checks 1–4 pass clean (full lifecycle, parallel extraction,
handler coverage, partial-error isolation). **Check 5 ("Batch-LC"): 4/15 identical, 14/15
completed, 9 non-pinned fails + 2 pinned** (`gdx_ord2`, `gdx_shp3` — the documented tolerated
pins, both still present and still excluded from the gate correctly). The two previously-diagnosed
causes are **not** what's failing this run: the null-`SELECTED_*` bug (A16/A22) is fixed — `sel.*`
now matches ground truth for 12 of 15 rows — and `gdx_shp3`'s OCR mismatch is still correctly
pinned, not gating. What's actually failing now, read straight from the live scorecard:
- **8 of 9 non-pinned fails are a pure date-format mismatch** — `KW.date`/`LOCAL.date` store
  `DD/MM/YY` (e.g. `"30/10/25"`), the fixture ground truth and `AI`/`sel` fields carry `DD/MM/YYYY`
  (`"30/10/2025"`). This is **not new tonight** — the `KW.date` check itself is unchanged in the
  diff, only `LOCAL.date` is new (added alongside the `LOCAL_TYPE`/`LOCAL_DOC_ID` work) — but it was
  invisible before because every row was already failing on the null-`SELECTED_*` bug; fixing that
  bug unmasked this one. `SELECTED_DOC_DATE` itself is correctly 4-digit for these same rows, so
  downstream consumers of the *selected* value are unaffected — this is specifically `DOC_DATE`
  (keyword/local extraction) not being year-normalized the way the selection step's winner is.
- **`gdx_shp4` ended `STATUS=MERGED`, not `COMPLETED`**, with empty `KW.short`/`sel.short` —
  extraction was interrupted before completion, a different anomaly from the date-format class. The
  row was already deleted by the suite's own post-run fixture sweep by the time this was found, so
  it could not be inspected further this pass — flagged, not diagnosed.
**Acceptance proof (unchanged from B3):** `gdoc` 5/5 with both known causes and this pass's two new
findings (date-format, `gdx_shp4`) closed or explicitly re-pinned.

### B22 — `pipeline` genuinely fresh run, 08-07 11:36: the dispatched fix landed, but the suite is 2/3, worse-looking on raw count than before
**The fix described in the brief (gate `sel.short` behind `if(inv)`, add `sel.raw` for shipments,
drop `plx_shp3`/`plx_shp5` from `knownPins`, fix `AI.short` to `r.ai_doc_id`, gate `🏁 Test Summary`
behind `Chain C? (all only)`) DID land** — confirmed in both the working-tree diff and, separately,
directly in the **live draft** (`indoxV2PipelineTest01` is inactive, `active=f`/`activeVersionId`
null, so per the active/draft rule its draft in `workflow_entity.nodes` is what a manual run
executes): `sel.raw`, `AI.short',r.ai_doc_id`, `Chain C? (all only)`, and `knownPins:["plx_inv2"]`
are all present in the live draft, matching the diff's "after" state exactly. Both `indoxV2GDocTest01`
and `indoxV2PipelineTest01` show `updatedAt=2026-08-07 10:28:09` — pushed before this pass's run.

Execution **391058**, 364s. Check 1 (bare-link) PASS 4/4, check 3 (dispatch coverage) PASS 8/8.
**Check 2 ("Batch Quality"): 2/17 identical, 16/17 completed, 14 non-pinned fails + 1 pinned**
(`plx_inv2`). Landing the fix did not turn this green — it changed *what* fails:
- **The same `KW.date`/`LOCAL.date` 2-digit-vs-4-digit-year mismatch as B21**, on 11 of 14 fails —
  confirming this is a cross-suite, systemic thing, not test-specific noise.
- **`AI.short` now reads empty (`""`) for every non-pinned invoice/order row** (9 of 14 fails). This
  is the fix working as designed — it now genuinely reads `AI_DOC_ID` instead of silently re-reading
  `SELECTED_DOC_ID` — and what it reveals is that `AI_DOC_ID` is not populated on these completed
  docs. Whether that's correct (the AI extraction leg is designed to skip once local extraction
  resolves with enough confidence — consistent with the self-skip shape B6 already proved for company
  resolution) or a real gap has **not** been determined this pass — flagged, not diagnosed, and
  worth the same self-skip-vs-bug check B6 got before anyone assumes either answer.
- **The new `sel.raw` check's own assumption does not hold on live data, for every shipment row that
  completed** (5 of 14 fails: `plx_shp1/2/4/5`). The fix's comment states shipments' `SELECTED_DOC_ID`
  "legitimately carries the RAW COMPANY_DOC_ID, not the short form" — but the live scorecard shows
  the opposite: `SELECTED_DOC_ID` holds the **short** form (e.g. `"11321"` for `plx_shp1`, which
  **is** ground truth's `short`), so comparing it against `g.doc_id` (the raw form, `"02TSH25011321"`)
  fails by construction. Had the check instead compared against `g.short`, these 4 rows would pass.
  This reads as the fix's own stated rationale being wrong about what the driver actually writes for
  shipments, not a pipeline defect — the same "assertion weaker/different than the rule" shape as
  A31/B12.
- **`plx_ord1`/`plx_ord2` show a real, distinct anomaly**: `LOCAL_DOC_ID` holds a bare date string
  (`"05/11/2025"`) instead of an order number, and `KW.short` reads `"12025"` against ground truth
  `"14445"`/`"14446"` — unlike `ord3`/`ord4`/`ord5`, which extract correctly. Not seen in any prior
  measurement of this suite; flagged, not diagnosed.
- **`plx_shp3` (the same fixture as `gdoc`'s pinned `gdx_shp3`) ended `STATUS=MISSING_TYPE`**, not
  `COMPLETED` — worse here than in `gdoc`, where the same source file only produced an OCR value
  mismatch. `LOCAL_TYPE` reads `"unknown"` for this row.
**Acceptance proof (unchanged from B3):** `pipeline` 3/3, with the date-format class, the
`AI.short`-empty question, the shipment `sel.raw` assumption, the `ord1`/`ord2` anomaly, and
`plx_shp3`'s status all resolved or explicitly re-scoped.

### B23 — a new, previously-undocumented, cross-suite finding: `DOC_DATE`/`LOCAL_DOC_DATE` carry a 2-digit year; ground truth and the selection winner carry 4
Seen identically in both fresh runs (B21, B22): every document where `KW.date`/`LOCAL.date` is
checked against a fixture's 4-digit-year ground truth fails, by a consistent one-shape difference
(`"30/10/25"` vs `"30/10/2025"`), while `SELECTED_DOC_DATE` for the same rows is correctly 4-digit.
Not present anywhere in `final-indox.md` before this pass (grepped for `KW.date`, "two-digit year",
and sampled year-format strings — zero prior hits; A5's two-digit-year item is a different concern,
about correctly *interpreting* a 2-digit year for the OLD-aging check, not about the stored format).
**Not diagnosed this pass** — open question whether `DOC_DATE`/`LOCAL_DOC_DATE`'s 2-digit-year
format is the product's real, intentional, source-native format (in which case the suite assertions
comparing it to a 4-digit fixture are themselves wrong, E1-shaped) or whether the selection step's
4-digit normalization should also apply to the raw fields.
**Acceptance proof:** the actual product intent for `DOC_DATE`/`LOCAL_DOC_DATE`'s year format is
established (owner or code-comment authority), and either the fields or the two suites' assertions
are brought into agreement — not both left to silently disagree the way E2's catalogue describes.

### B24 — current scorecard, all 7 suites, one pass, 08-07 11:36 — **none green**
| suite | result | exec | measured | note |
|---|---|---|---|---|
| `sync_kernel` | ✅ 6/6 | 392855 | fresh, this pass | clean |
| `doc_base` | ✅ 3/3 | 392976 | fresh, this pass | clean |
| `bs` | ✅ 4/4 | 387205 | 09:59–10:00 (fix live since 09:35, predates this run) | clean |
| `gdoc` | ❌ 4/5 | 388755 | fresh, this pass | B21 |
| `pipeline` | ❌ 2/3 | 391058 | fresh, this pass | B22 |
| `sync_full` | ❌ 4/6 | 385555 | 09:45–09:52 | B25 |
| `sync_sources` | ❌ 7/10 | 381093 | 08:55–09:18 | proc-gdoc 7/13, proc-gmail-doc 9/10 — OCR company/type figuring + ledger-watch timeouts, unrelated to tonight's ten claims |
**Zero of 7 suites are simultaneously green in this pass.** `sync_full` and `sync_sources` were not
re-run fresh this pass (their most recent runs predate the final 10:28:09 push by ~40–90 min, though
`sync_full`'s specific fix, A34, was independently confirmed live back to 08:09:47) — everything
else in this table is a fresh, this-pass execution.

### B25 — `sync_full`'s `registry`/`mixed` checks: the drive-identity 400 (A37) is closed, but delivery is stuck at 0 for a different reason
Both the `registry` and `mixed` lanes fail on the same shape in the two most recent live runs
(execution `385555`, and the earlier `373748`): `gate.delivered` reads **0** against an expected
**3**, across every mirrored source (`sv3f_rg_drive-gdoc`, `sv3f_rg_drive-bs`, `sv3f_rg_gmail-link`,
`sv3f_rg_gmail-bs`, `sv3f_rg_gmail-doc`, `sv3f_rg_mail-private`, `sv3f_rg_drive-gdoc-scanned` all at
0; `sv3f_rg_drive-gdoc-chat-export` at 1). Neither run shows the `_explicit_connection_required`
400 A37's fix targets — that specific defect is confirmed gone — so this is a **separate, still-open
delivery/timing problem**, not a residual of the identity bug. Not diagnosed this pass.
**Acceptance proof:** `registry` and `mixed` both green, with `gate.delivered` reaching its expected
count on a live run, twice consecutively.

---

## C. Decisions still owned by the owner

1. WhatsApp bot: retired (drain 123 once) or broken (fix the bot)?
2. Merge registry duplicates `מבנה דרום`/`מבנה דרום חדש`, two `טמבור` rows?
3. `drive-gdoc` repoint needs one `failed` folder created in Drive
4. `IndoxResetFull01` — confirmation token, or leave as-is?
5. 61 HASH-colliders currently `COMPLETED` — auto-merge or route to review?
6. **Backfill the rows with `SELECTION_COMPLETED <> true`?** Measured live 08-07 05:33: **1,701**
   rows (was reported 1,672 earlier tonight — the pipeline is live and the number drifts). This is a
   decision and not a task because a backfill would reset `PRIORITY_SYNC_COMPLETED` and queue a
   **full ERP re-sync** the moment `activePrioritySync` flips on. It is `false` today, so nothing
   moves until the owner says so.
7. **The 34 AI-vs-ledger type-conflict rows** (27 `GMAIL` / 6 `GOOGLE_DRIVE_FOLDER` / 1 `WHATSAPP`;
   29 already `COMPLETED`) — accept the AI verdict, accept the ledger verdict, or route to review?
   **Lead worth recording:** the 24 `TYPE=INVOICE` vs `AI_TYPE=BALANCE_SHEET` rows may be a
   `SOURCE_TYPE` labelling bug **upstream** rather than an extraction disagreement — if so this is
   one upstream fix, not 24 adjudications. That 24-row subset is **live-confirmed at 24 on 08-07
   05:33**. The 34-row total and its source breakdown are recorded as reported: a naive
   `"AI_TYPE" <> "TYPE"` predicate returns a **broader 137 rows** (96 `GOOGLE_DRIVE_FOLDER` / 40
   `GMAIL` / 1 `WHATSAPP`), so the 34 needs its exact predicate written down before it can be
   re-measured by anyone else.
8. **Removal of the already-contaminated fixture rows from the client table** — B13 stops new
   contamination; it does not clean up what is already there, and no automated sweep can reach those
   rows without the containment DELETE the D rule forbids. **Scope is now known: the 12 filed proc
   rows (B20).** The precedent is set and worked — A32 removed three fabricated invoices from company
   `511744898` under backup by explicit `"ID" IN (…)`, and the two genuine rows were verified present
   by id afterwards. This decision is therefore about the 12, not about the method.
9. **`uq_incdoc_business_key` must NOT be created yet** — re-measured 08-07 05:33: **132** violation
   groups on `(COMPANY_ID, COMPANY_DOC_ID)` excluding `MERGED` (the earlier figure was 122; either
   way it is far from zero). Creating the index now rejects writes the duplicate writer should have
   merged. This is the same gate as B8 and is recorded here so nobody creates it "to see what
   happens".
10. **`zz-scratch-gateway-probe (delete me)`** — a third agent-created workflow found alongside the
    two in A26. Disarmed (`active=f`, `activeVersionId` null) as of 08-07 07:06, so it is inert, but
    it is still in `workflow_entity` under a name that asks to be deleted. Delete it, or attic it
    with the other two.

---

## D. Standing invariants (do not regress)

Positions verbatim · loop-order lint stays at 3 · no credential values in files · backup+sha256
before every destructive write · losers linked never deleted · `take`/`chunk`/`schedule_min`/
worker-count/concurrency untouched · split counts by status · medians across buckets · DB clock
only · a check that cannot fail on the real thing reports NOT VERIFIED, never PASS · a claim
without a live measurement is OPEN.

**A read may reason from containment. A write may not.** (`scripts/refactor/GATES.md:164`, binding
via G58 rules F2/F3.) A counter, a watch predicate or a report may ask "does this row *mention*
something of ours" — being wrong costs a wrong number. A DELETE or an UPDATE must ask "is this row
*ours*", because being wrong costs client documents: on 2026-08-06 the difference was **2,432**. The
asymmetry has a measurable floor — the shortest live `platform_id` is **1 character**, so
`position('#inbox/' || l.platform_id in "SOURCE_LINK")` matches **2,391 of 2,391** `#inbox/`
documents while the anchored `like '%#inbox/' || l.platform_id` matches **0**. A read written that
way is not safe, only survivable: its green means nothing (B11). A write written that way is the
incident.

**Count documents, not executions — n8n execution counts are not a common unit.** An
`executeWorkflow` node at `"mode": "each"` produces **one sub-execution per document**; the same node
left at the default mode behind a `splitInBatches` produces **one sub-execution per batch**. In the
DOC BASE state machine `Call BaseDocEx01` is `mode: each` while `Figure Document COMPANY_ID` sits
behind `Loop Over Items24` at `batchSize: 50` — so comparing their execution counts compares
documents against batches-of-up-to-50. A large share of the "~40× swings between adjacent buckets"
that defeated every earlier B6 attempt is this ratio distortion, not real variance. The unit that
*is* comparable is one `ACTION_LOG` entry per document: each `Build:` node appends
`', <label>, ' + $now + ', ' + $execution.id`, so
`regexp_matches("ACTION_LOG", '([^,]+),\s*(1[0-9]{12})', 'g')` yields a document-level, DB-clock,
batching-immune dispatch series. Attribute a sub-execution to its caller by dereferencing n8n's
flatted `execution_data.data`: `j ->> ((j->4->>'workflowId')::int)`.

**Corollary, and a live warning:** ACTION_LOG counts *completed* dispatch, execution counts count
*attempted* dispatch, and today they disagree badly — 50 `BaseDocEx01` executions in the 20:00 bucket
against 12 `Extract Base Doc` log entries. Roughly **4 in 5 base dispatches never reach their
upsert**, because B1's wedge kills the parent first. Until B1 is fixed, every execution-based
throughput number in this file is inflated relative to work actually completed.

---

## E. Two catalogues — the findings that outlive every red on this board

Sections A–C are a snapshot; these two are the shapes that keep producing new entries. Every red in
A and B is an instance of one of them, and each new instance was found by looking for the *shape*
rather than by tripping over the symptom.

### E1 — Checks whose evidence is an absence

A check that passes by finding nothing cannot distinguish **"clean"** from **"never looked."** Both
render as green. Instances found so far, each with what the absence actually meant:

| # | the check | what "nothing found" really meant |
|---|---|---|
| 1 | `PB Row` and the four `PD`/`PL` counters (A11, B11) | a containment join on a **1-character** uid matches **2,391 of 2,391** documents — the counter was answering a different question, and its green was arithmetic noise |
| 2 | `Build Release` on an empty `ids[]` (A23) | an empty list read as a **deliberate no-op**, so RELEASE returned success having released nothing. `all:true` is what makes the ask explicit |
| 3 | `gmail-bs` labels (B16) | producer writes `projection.synced_label`, executor reads `label_keys` — **zero operations and no error** |
| 4 | `normalizeDocType(d.TIPE)` (A14) | an operand that resolves to `undefined` throws nothing; it yields a permanently-null column that looks like "no data yet" |
| 5 | `active=false` (A25) | the human-facing surface said off while `activeVersionId` kept the workflow **armed and servable** |
| 6 | five gates never wired into `run-gates` (A28), and **G61 still isn't** (B17) | a gate that runs nowhere reports no failures, forever |
| 7 | G58 before A27 — no INSERT rule | the contamination channel of B13 produced no findings because that statement class was never read |
| 8 | `knownPins` (A20) | a mismatching pin lands in `pinned`, never in `fails`; the verdict reads only `fails.length`, so a known-bad row is silently absent from the thing being counted |
| 9 | `bs` `SKP03` / `UPD02` (A31, B12) | the assertion is weaker than the rule it stands in for, and the branches it guards **had never executed** |
| 10 | suite cleanup and `fixture-sweep` over proc-lane rows (B13) | rows written under production `SYNC_NAME`s carry no registered marker, so the sweep finds nothing because it cannot see them |

**The defence is a positive control, and it is not optional.** Any check whose pass condition is
"found nothing" must be *proven able to fail on the real thing* — inject the real defect into the
real node, watch it go red naming that file and node, then restore byte-identically and watch it go
green. G58 was proven this way three times (DELETE, UPDATE, INSERT); G59, G60 and G61 each ship a
self-test, and G61's includes the case that matters most for this catalogue: *no database is
reported as NO VERDICT, never as a pass*. A check without a positive control is a claim without a
live measurement, and by this file's governing rule that makes it **OPEN**.

### E2 — Two lists that silently disagree

Whenever the same fact is written down twice, the copies drift, and **nothing errors** — the reader
just gets the stale one. Instances:

| # | list A | list B | what the drift cost |
|---|---|---|---|
| 1 | `GATES.md` rows | `ci-verify.yml` steps, `run-gates.py`, `scripts/ci/gates.sh` | the CI check asserted `GATES ⊆ ci-verify` and **never the reverse** — five gates ran nowhere (A28); G61 still does (B17) |
| 2 | `workflow_entity.active` | `workflow_entity.activeVersionId` | only the second one executes. `active=false` was never a disable (A25) |
| 3 | `workflow_entity.nodes` (draft) | `workflow_history.nodes` (published) | a `PATCH` returns **200 and deploys nothing**; a "deployed" reading off the draft can be fiction (A24) |
| 4 | `halt-tests.sh`'s list of **11** | the real set of **13** test workflows | two suites were never halted, and `tVzFMkz18pCsXRyw`'s blueprint declared `"active": true` so every push re-armed it (A25) |
| 5 | `Decide GDoc Action`'s emitted actions | the switch cases, the driver self-test, the fixture oracles | `select_invoice_values` was in three lists and emitted by none — an orphaned action for a whole release (A15) |
| 6 | `projection.synced_label` | `label_keys` | zero ops, no error (B16) |
| 7 | fourteen sibling cleanups, each restating its prefix list **inline** | — | nothing mechanical stood between the fleet and the fifteenth: **2,432** client documents |

**The mitigation is one of two things, and never a third.** Either **derive the answer from the thing
that executes** — read `activeVersionId`, not `active`; read `workflow_history`, not the draft; read
the gate script's own docstring for its number, which `run-gates` already does — or **make the two
lists the same object**. `scripts/test-fixture-prefixes.yaml` is the worked example of the second:
one registry, and G58 is what makes it binding rather than advisory. The registry does the same
trick internally, merging `delete_allowlist` and `mutation_allowlist` in code so the two cannot
disagree. "Keep them in sync" is not a mitigation; it is the defect restated as a hope.

### E3 — The through-line

**Four retractions this cycle, every one falsified by evidence rather than by argument:**

1. **B6's acceptance criterion** — "dispatch falls to the floor *and then the steps are deleted*" —
   two clauses that contradict each other. The floor is non-zero by design, so arriving at it proved
   the step must be **kept**.
2. **The `MISSING_LINK` attribution** (B6 addendum) — blamed on the legacy lane, which contains
   **0** occurrences of `ACTION_LOG`, **0** of `MISSING_LINK` and **0** upsert nodes. It writes
   nothing; it could not have been the writer.
3. **"Fleet swept: 0 unanchored containment joins remain"** (B11) — four remain, and they are named.
4. **"`active=false` disables a workflow"** (A25) — it never did; `getActiveIds()` and
   `executeWebhook()` both key on `activeVersionId` and neither reads the column.

**Three of those four came from reading a mechanism instead of testing it.** Only #3 came from
re-running a measurement. That is the cheapest lesson on this page: reading the code tells you what
someone *meant*; only running it against the real thing tells you what it *does*. Where those two
disagree, this file records what was measured — and where a measurement has since decayed (the
`2,385 → 1` of A11, the `sha256 fbdd3925…` of A12), it says so rather than keeping a number that no
longer reproduces.

---

## F. Direct verdict — is the two-point extraction plan complete? (FINAL-STATUS pass, 08-07 11:36–12:01)

**No.** Here is exactly what's proven, what moved, and what's left, in the owner's own terms.

**What holds, re-verified live this pass, not re-cited from memory:**
- Selection-after-extraction is live in all 4 real extraction routers (Global/GDoc/Ship/BS),
  published version identical to draft, zero drift (A40). The driver correctly has none of its own.
- The *raw* two-point extraction values are genuinely clean against the legacy columns — 0/525
  `COMPANY_ID` mismatches, 0/660 `TYPE` mismatches (B26).
- The shipment `INVOICE_ID` gap is real, architectural, and still open — confirmed live:
  `shipmentDecide` has zero `INVOICE_ID` handling, and `LOCAL_INVOICE_ID`/`AI_INVOICE_ID` don't
  exist as columns yet (B28). Correctly filed for the owner, not something anyone should treat as
  closed.

**What does not hold as previously reported, corrected this pass:**
- "Value-parity proven clean" is true of raw extraction only. The **final selected output** carries
  7/5424 (0.13%) `COMPANY_ID` mismatches — 6 of them newly found, not previously flagged anywhere —
  and 30/430 (7.0%) `TYPE` mismatches, matching the already-known but still-unresolved C7 population
  (B26).
- **The 4-row/0.68% (`COMPANY_ID`) and 0-row/0% (`TYPE`) "true legacy-extractor dependency" figures
  reported to the owner tonight do not reproduce.** An independent live re-derivation under a stated,
  defensible methodology finds **36 rows** and **27 rows** respectively — an order of magnitude
  larger, and the *direction* of the original claim (most of the gap absorbed by an existing
  fallback) does not hold either: the "needs something other than the fallback" bucket outnumbers
  the "fallback rescues it" bucket, not the reverse (B27). This is the single most important
  correction in this pass, because the owner named the suite-green precondition as the gate on
  deleting the legacy extractors, and this number is a direct input to how risky that deletion is.

**The suite-green precondition, checked live, not from memory:** **zero of 7 suites are
simultaneously green** (B24). `sync_kernel`, `doc_base`, and `bs` are clean on fresh or near-fresh
runs. `gdoc` (4/5) and `pipeline` (2/3) both got genuinely fresh runs this pass and both remain red
— for reasons that have **shifted** since the last measurement, not resolved: a newly-surfaced,
cross-suite `DOC_DATE`/`LOCAL_DOC_DATE` 2-digit-vs-4-digit-year format mismatch (B23) now dominates
both suites' failures, alongside suite-specific anomalies (`gdx_shp4`'s interrupted merge, `pipeline`'s
now-empty `AI.short` reads, a `sel.raw` check whose own stated assumption about shipment
`SELECTED_DOC_ID` does not match live data, and `plx_ord1`/`plx_ord2`'s local-extraction anomaly —
B21, B22). `sync_full` (4/6) and `sync_sources` (7/10) remain red on their own pre-existing, unrelated
defects (B25 and OCR/timeout issues respectively).

**Coverage has moved, and fallen, not risen:** 9.26–9.28% of the live fleet has been reprocessed
through the two-point mechanism, down from the ~11.8% reported earlier tonight — most plausibly
because backlog ingestion is outrunning reprocessing throughput, not because reprocessing regressed,
though that specific causal read is not independently confirmed beyond one short measurement window
(B29).

**What's left before lock-in (deleting the legacy extractors) is safe, in order:**
1. ~~Reconcile B27~~ — **DONE 08-09, see B30. The answer is 4 (COMPANY_ID) / 0 (TYPE)**: the
   original claim was correct, this pass's 36/27 was gated on `AI_EXTRACTION_COMPLETED` (the legacy
   Gemini flag, a population 3,487 of whose rows never went through two-point), and the later 97/75
   counted rows that came out of two-point unresolved rather than rows the legacy extractor rescued.
   `figure_document_type` has a fleet-wide realised yield of **0** and is safe to delete now;
   `figure_company_id` carries a 4-row (~~0.46%~~ → 0.37%) residual. ~~**New blocker surfaced by that work:
   `extraction_ai_enabled='false'` since 08-05 — the AI half of two-point extraction has never run,
   so every parity/dependency number in this file measures a one-legged mechanism (B30.4).**~~
   **CLEARED 08-09 13:32 — the AI leg is live and B33 re-derives every one of those numbers. The
   4/0 holds. What replaced it as the Tranche-2 blocker is B33.12: the deletion now promotes
   `figure_company_offline` to sole company resolver, and that resolver still lacks the
   minimum-name-length guard its own hazard analysis (B31.3, 122/6,117 = 2.0% false positives)
   called for.**
2. Get all 7 suites green simultaneously, including root-causing and fixing B23 (the date-format
   mismatch, now the dominant failure in both `gdoc` and `pipeline`), B21/B22's suite-specific new
   anomalies, and B25 (`sync_full`'s stuck-at-zero delivery gate) — none of these were closed by
   tonight's ten fixes.
3. Close or explicitly defer the shipment `INVOICE_ID` architectural gap (B28) — new `q_v3_routing`
   work plus `LOCAL_INVOICE_ID`/`AI_INVOICE_ID` extraction wiring, not started.
4. Decide the 6 newly-found `COMPANY_ID` selection disagreements and the ~30-row `TYPE`/C7 conflict
   population (B26) — triage, not necessarily fix, but not silently ignore either.
5. Coverage (B29) is not itself a blocker for lock-in the way suite-green and B27 are, but a
   9%-reprocessed fleet is worth the owner seeing before committing to remove the mechanism that
   still serves the other 91%.

**Everything claimed as closed tonight is, in fact, closed, and stands under re-verification —
including the two items a first pass through this file wrongly flagged as unproven:** the BS
clobber guard (A33), the `syncV3Main0001` registry-key production-decoy bug — independently
confirmed as serious as described (A34), the `mailLabelEngine01` loop-order bug **with its
interleaving-reconstruction proof confirmed live, positive-controlled, before/after** (A35), the
`NEEDS_REVIEW` reaper fix (A36), the drive-identity 400 in `syncV3FullTest01`'s registry mirror
(A37, though the suite it lives in is still red for an unrelated reason, B25), the bad-file-id fix
across all three Gmail downloaders (A38), and the **"Get a message" transient-404 fix — confirmed
live, in `mailLabelEngine01`, not the file first checked** (A39). The one genuine correction from
this pass is B27's legacy-extractor dependency count, which does not carry the same "verify wider"
fix — it was independently re-derived from a live query, not a location-scoping miss, and it still
does not reproduce the 4/0.68%-and-0/0% figures reported tonight.

---

## G. Post-F session — the label-vocabulary fix and where the backlog actually stands (08-07 ~13:00–13:40)

Everything in this section is measured by me directly against the live stack (`docker -H
unix:///run/bbox-docker.sock`, `supabase-db-shlomo-laptop`, `n8n-postgres-shlomo-laptop`), not cited
from a subagent report without re-checking — one subagent dispatched to write this section failed to
even locate the repo/stack (its own sandbox had no access to the WSL mount this stack actually runs
on) and correctly declined to fabricate numbers rather than guess; its refusal is the right behavior
this file has asked for all along, but it means this section is written first-hand instead.

**G1 — The real headline: `tag_rules` vs. the organizer vocabulary were two independently-editable
label dictionaries, and 6 of ~24 keys had drifted apart.** `SyncSource000001` (what INDOX searches
with) reads `public.tag_rules`; `mailLabelEngine01` (what actually applies labels to mail) reads
mailapi's `/organizer/settings`. Six keys — `DOC_TO_SYNC`, `SYNCED_DOC`, `BS_TO_SYNC`, `SYNCED_BS`,
`FAILED_BS`, `IN_PROGRESS` — had different `LABEL` values in each store, so real, correctly-labeled
mail was invisible to the search that was supposed to find it. Fixed under standard discipline:
backup (`data/_registry_backup/tag_rules.20260807T130405Z.csv` + sha256) → 6 exact-match (`WHERE
"KEY" = '<key>'`) UPDATEs, each confirmed 1-row-affected via `RETURNING` → same 6 values corrected in
the checked-in seed fixture `apps/mail/mailapi/fixtures/tag_rules.json` (`git diff` shows exactly
those 6 lines). Proven live through the real production path (`SyncApi0000000001` webhook, `STATUS`
action → `SyncSource000001`/`Load Labels`, active version checked in `workflow_history`, not the
draft): `per_sync.gmail-doc.to_sync` went **~4 → 646** immediately after the fix.

**G2 — Independently re-measured downstream effect, not just the search-count claim.** The search
count alone doesn't prove documents actually land — checked `public.incoming_documents` directly:

| window | GMAIL-sourced rows created |
|---|---|
| the hour immediately **before** the fix (12:04–13:04 UTC) | **0** |
| the ~35 minutes immediately **after** the fix (13:04–13:40 UTC) | **27** (9 `COMPLETED`, 12 `MISSING_COMPANY_ID`, 3 `MISSING_TYPE`, 3 `GARBAGE`) |

Zero to nonzero, cleanly bracketing the fix's own timestamp — this is the discriminating measurement
this file's rules ask for, not a before/after that could be coincidence. The `MISSING_COMPANY_ID`
share among the new rows (12/27, 44%) is consistent with B26/Task-87's already-tracked WhatsApp/scan
company-ID gap, not a new problem.

**G3 — Live fleet total as of this measurement: 7,213 documents, 76.2% `COMPLETED`.**

| STATUS | count | % |
|---|---|---|
| COMPLETED | 5,498 | 76.2% |
| DOUBLE | 632 | 8.8% |
| MISSING_COMPANY_ID | 501 | 6.9% |
| MERGED | 144 | 2.0% |
| MISSING_TYPE | 118 | 1.6% |
| NEEDS_REVIEW | 98 | 1.4% |
| OLD | 61 | 0.8% |
| ACTION_RESTART | 60 | 0.8% |
| PAUSE | 35 | 0.5% |
| EXTRACTION_FAILED | 30 | 0.4% |
| MISSING_LINK | 16 | 0.2% |
| MAX_ITERATIONS | 6 | <0.1% |
| GARBAGE | 5 | <0.1% |
| API_TOOLS_FAILED | 5 | <0.1% |
| IN_PROGRESS | 3 | <0.1% |

**This is 7,213 documents against the owner's ~18,000-document six-month-backlog target — not yet
there.** The vocabulary split that had been suppressing an unmeasured share of real inbound mail was
only fixed ~35 minutes before this measurement, and G2 shows ingestion is actively resuming (0→27 in
the first 35 minutes), not yet a full backlog drain. **Do not read 7,213/18,000 as the ceiling** —
it's a snapshot taken while the blocker G1 removed was still draining, not a final number. The honest
statement is: the structural blocker most plausibly suppressing the largest share of "documents
aren't syncing" is now fixed and proven fixed, but the backlog has not yet been given time to fully
drain through it.

**G4 — Fleet health at this measurement, corrected on retriage — the aggregate 0.7% figure hid a
100%-broken workflow.** n8n executions, last 15 min: 3,207 success / 23 error (0.7% aggregate). A
first triage attempt hit the same transient sandbox/WSL blip as the section-writing lane and returned
nothing; a retry succeeded and decoded the real (compacted-format) error text via n8n's REST API. Per
workflow, not one story but three different ones:
- **`Balance Sheet Extractor - v2- shmuel`: NOT a volume-related blip — 100% failure (24/24), hard
  cutover at exactly `2026-08-07T13:17:54Z`.** Root cause: tonight's `scope=mail` n8n push (12:57:17–
  12:58:58Z) overwrote the live encrypted Gemini credential (`googlePalmApi` id `6mfcsdRaqQ4IdQ8Y`)
  with its git-tracked manifest's empty `data:""` value (credential exports are deliberately
  manifest-only so secrets never hit git — the push imported that emptiness over the real key). The
  pre-wipe encrypted blob still exists (`platform-base/n8n/.credentials-state/6mfcsdRaqQ4IdQ8Y.json`)
  and its encryption-key fingerprint still matches the live `N8N_ENCRYPTION_KEY`, so a restore is a
  known-good `n8n import:credentials` away — filed as **Task #107, urgent, owner action needed**,
  because the platform's own permission classifier blocks an agent from performing credential
  restores (same category as Task #100's password rotation).
- **`Gmail Documents Downloader`**: cascading `TimeoutExecutionCancelledError` (~34–37s, well under
  its own 600s configured timeout) — sub-executions getting starved while contending for apitools OCR
  capacity, not a standalone defect.
- **`Process Document` → `Document OCR`**: `429 server_busy` / `ECONNABORTED`, verbatim matches to
  apitools' own documented, deliberately-tuned OCR admission-control bulkhead — working as designed,
  now firing more because real volume is finally flowing post-G1/G2. Same protected-capacity category
  as Task #99 (folded in there), not touched.

`mailapi-shlomo-laptop` is `healthy` (Task #102's healthcheck-timeout fix holding). `git status
--short` on the repo shows **316 uncommitted lines** — a large amount of tonight's work (including
this file) is sitting in the working tree, not committed, per this repo's hands-off-git convention;
nothing in this section should be read as "landed" in the durable/fresh-clone sense until that's
committed.

**G5 — Other dispositions from this session, for the record:**
- Task #92 (mailLabelEngine01 manual-trigger crash): fixed, pushed, verified live in the active
  `workflow_history` version — zero remaining bad references in the manual-trigger-reachable graph.
- Task #97 (label-recreation throttling): the original write-back theory was corrected mid-session —
  `label_id` isn't even consulted by the create-decision, so a missing write-back can't be the
  mechanism of an active duplicate-create storm. Left **unfixed, holding for a corrected diagnosis**
  (most likely `listLabels()` degrading under load) — correctly not touched on a wrong theory.
- Task #99 (mailapi single-process/thread-pool capacity): still owner-decision-needed, untouched, but
  materially strengthened this session — a direct in-container timing probe measured real `/healthz`
  requests taking 20–30s to complete under live load, sustained continuously for over a minute. This
  is hard, load-verified evidence the bottleneck is real and current, not theoretical.
- Task #103 (gdoc `DOC_DATE` 2-digit-year bug): fixed and verified — this was silently breaking the
  webapp's month-navigation feature for every currently-processed document (`no_date` bucket dropped
  1,278→601 after the fix, matching the true empty-row count).
- Task #87 (COMPANY_ID/TYPE gap): rescoped from an earlier 4/0 (unreproducible) and a later 36/27
  (wrong population flag) to a freshly, independently re-derived **97/75 real documents** — traced to
  WhatsApp/scanned images with no extractable company signal anywhere, meaning the originally-planned
  fix (port a sender/email lookup) would not have helped and was correctly not applied. A real fix
  needs OCR-based company recognition, not yet scoped.
- Task #105 (`mail-private` registry entry pointing at a local test mailbox, not the real account):
  ~~found, not fixed — needs the mail-architecture lane to confirm intent~~ → **SUPERSEDED 08-09.**
  The config fix landed and was verified live (`connection_id` corrected via
  `sync-registry-converge.py`, checked against the live Postgres row, not the fixture). But the fix
  did **not** unblock delivery, and the real mechanism turned out to be different: `mail-private`'s
  search is `has:attachment newer_than:6m` with `page_size: 50`, **unpaginated and with no cursor**,
  so it only ever sees the newest 50 matches — and that window is continuously refreshed by e2e
  fixture-injection traffic (`IndoxInjectDemo01`, `sv3Inject3x001`, `syncV3SourcesTest01`), which
  correctly writes into the same real account since the Phase-A identity fixes. Root architectural
  cause: `mail-private` has no `processor_wf` and no `labels` map (`mode='thin'` permanently), so
  unlike `gmail-doc`/`gmail-bs`/`gmail-link` it can never get a label-scoped search that would
  exclude fixture noise. See H4.
- Task #100 (rotate the exposed local `POSTGRES_PASSWORD`): blocked — the platform's own permission
  classifier declined to let an agent perform credential rotation even framed as routine local-dev
  hygiene; this needs the owner to do directly.

**What's still genuinely open, unchanged from Section F plus this session's additions:** ~~the B27
suite-green/legacy-extractor-dependency reconciliation~~ (**closed 08-09 by B30 — 4/0, and Task
#87's 97/75 is re-explained there: it was counting "unresolved after two-point", of which 165 rows
had already had the legacy extractor run and find nothing**), all 7 suites simultaneously green (still 0/7
as of the last direct measurement), the shipment `INVOICE_ID` architectural gap, Task #97's corrected
throttling diagnosis, Task #99's capacity owner-decision (now covering both mailapi's IMAP pool and
apitools' OCR bulkhead), Task #87's OCR-based company-recognition fix, Task #105's registry-intent
confirmation, and **Task #107 — `Balance Sheet Extractor - v2- shmuel` 100% failing since 13:17:54Z**
(~~because tonight's `scope=mail` push wiped its Gemini credential; a known-good restore is
identified~~ → **ROOT CAUSE CORRECTED 08-09, see H1: there was no blob to restore.** The credential
is `[env-managed]` — `platform-base/n8n/blueprint.yml:148` templates it as
`{"apiKey":"${GEMINI_API_KEY}"}`, and `.env:393` is `GEMINI_API_KEY=` **empty**. The manifest's empty
`data` was always by design. The push didn't destroy a secret; it faithfully rendered an empty one),
plus giving the backlog time to actually drain and re-measuring ~~7,213~~ **7,429 (08-09)** against
the ~18,000 target once it has.

---

## H. The four-objective session (08-09) — owner's standing priorities, measured

The owner reset scope to **four numbered objectives**, worked fully autopilot, reported as a progress
bar: **#1** all ~18,000 six-month documents discovered and `COMPLETED` (top priority — the client is
waiting to push them to Priority ERP, and wants the ground truth loaded *naturally via the syncs*);
**#2** the two-point extraction refactor completed and the legacy extractors cleaned up; **#3** zero
n8n workflow errors; **#4** all 7 INDOX suites green (sync + state machine).

Same rule as the rest of this file: a claim without a live measurement is OPEN.

### H1 — Task #107 root cause was wrong, and the real mechanism is worse (FIXED)

The credential was never wiped. `6mfcsdRaqQ4IdQ8Y` is `[env-managed]`; an empty `data` in the
manifest is correct by design. The failure is that `GEMINI_API_KEY` is **empty in `.env`**, so every
push re-renders an empty key into a live credential.

The mechanism sits in push **step 1.5** (`platform-base/n8n/hooks/push`, the `credential_overrides`
reseed): an unset env var resolved to the empty string and was then PATCHed in as a real value.

Two aggravating properties, both measured, not inferred:
- **It is instance-global.** A scoped `bbox n8n APP push` narrows only which *workflows* stage. That
  is exactly how a `scope=mail` push destroyed a document-extraction credential.
- **Blast radius was 5 credentials, not 1.** Replaying the shipped resolver against the real
  blueprint: 20 PATCHes, **5 carrying an empty field**. `Chat Auth` (`BmKlKWiEeZAxNWyi`) was blanked
  the same way (ciphertext 108 to 64, matching Gemini's 192 to 128). Three others were spared only
  because they had never been populated.

**Fixed:** an unset-or-empty variable now **skips the credential loudly** rather than blanking it.
After: 15 PATCHes, 0 empty. Gate **G63** `scripts/refactor/credential-blank-lint.py` (self-test 5/5,
rejects the pre-fix resolver), wired into `ci-verify.yml`, `scripts/ci/gates.sh` and `run-gates.py`.

**Still open (owner):** populate `GEMINI_API_KEY` in `.env`; `Chat Auth` needs the same treatment.
Note `BsDocEx01` *also* gates on `extraction_ai_enabled`, which is `false` — so the key alone will
not make the central-extraction-point BS path run AI.

**Scope note:** this affects **objective #3 only**. Objectives #1, #2 and #4 have no Gemini
dependency — ~~the AI leg has never run (see H3)~~, so every suite and every extraction path currently
green or red is green or red on the local leg alone.
⚠️ **Stale from 08-09 13:32:05 UTC (B33).** The AI leg is live, so the "no Gemini dependency"
premise no longer holds for anything measured after that instant — including any suite re-run.
Suite results from before the flip are still local-leg-only; results after it are not, and the two
must not be compared as if they were the same experiment.

### H2 — Where the missing documents actually are, and the constraint that hides them

The owner corrected the mental model, and it materially changes the plan: there are only **two real
Drive source families** — the scanned pair and the chat-export pair — and **both already have
registry entries**. Every other document-bearing Drive folder (19,834 in-window in the
"files from Gmail, done" archive, 5,516 in the aging-reports archive, 2,583, 1,299, 447) is a
**destination the legacy automation wrote mail attachments into**. Those documents' true source is
Gmail; they must arrive **via the mail syncs**. Adding Drive registry entries for them would
double-count. A lane was heading toward exactly that and was stopped.

**The binding constraint, measured live today:** `op_list` (`apps/drive/adapters/google.py`) requests
a next-page token and discards it. Through the live drive service, a 17,325-file folder returned
**100** files at `limit=1000`; a 584-file folder returned **100**; a 20-file folder returned 20.
`syncV3Unit0001` reads exactly one page per pass, diffs it against the ledger, and delivers
`min(take, chunk)` — so once that head page is ledgered, `missing` is permanently 0. **Gmail is
identical** (one search, `limit: page_size`, no offset). Live proof: the 09:16 full reconcile
reported **"6 unit(s), 0 delivered"** while tens of thousands of documents were absent. This is
`issues/drive-op-list-single-page.yaml`, now confirmed as *the* binding constraint rather than a
latent one. Fixing it needs an **image rebuild** — the drive app is baked in, not bind-mounted.

The backfill primitive already exists and is unwired: `public.sync_cursor` plus `CURSOR_GET` /
`CURSOR_SET` in `syncLedgerApi01`, whose only caller is `syncV3KernelTest01` — a test. Production
discovery has no cursor at all.

Ruled out by measurement, so nobody re-litigates them: service-account access (fine — owner
confirmed, and verified), nested folders (one, inside a destination folder, no in-window cost), the
disabled `drive-gdoc` / `drive-bs` pipes (**all four source folders are empty**, so disabling them
costs nothing), and stuck claims/locks (engine running normally).

**A third real source folder was found and wired:** the WhatsApp-bot folder
(`16GXkekZeHSyYtvkcoDGrEYiEu6Nn5Z1b`), 584 real supplier invoices, 187 in-window, **0 in
`sync_ledger`, 0 in `incoming_documents`**. Added as `drive-whatsapp-bot` with projection **off** so
no client file is ever moved or relabelled — discovery only. Backup
`data/_registry_backup/sync_registry.20260809T092525Z.json` (sha256 `ac385be3...f686b62`),
exact-match write, all 8 pre-existing entries asserted byte-identical after. Live: registry 8 to 9,
reconcile 6 to 9 units, folder **0 rows to 22 rows**. It will plateau at ~100 until the page cap is
fixed.

### H3 — B27 reconciled: the original 4/0 was right (full working in B30/B31)

Three contradictory measurements of "how many rows still depend on the legacy extractors" (4/0 vs
36/27 vs 97/75) are reconciled. **4 rows / 0 rows.** The instrument nobody had used is `ACTION_LOG`,
which records *which mechanism wrote the value* — every prior pass inferred from flags and column
nullness, which cannot distinguish "legacy rescued this" from "ingestion pre-filled it" (87% of rows)
from "nothing ever resolved it". 36/27 gated on `AI_EXTRACTION_COMPLETED`, a flag set by the *legacy*
Gemini action, over a population 3,487 of which had never been through two-point at all. 97/75 asked
a different question — "unresolved after two-point" — of which 165 of 206 had already had the legacy
extractor run and find nothing.

~~**Standing caveat, and it qualifies every number in this file:** `extraction_ai_enabled = false`
since 2026-08-05 (a deliberate owner setting, not a defect). The AI leg of two-point extraction has
**never run** — across every row with a `SELECTION_DEBUG_BASE`, the source is only ever `LOCAL_ONLY`
or `NONE`. B26/B27/B29/B30/B31 all measure a one-legged mechanism and must be read as a floor for
the local leg alone.~~

⚠️ **OVERTAKEN BY EVENTS 2026-08-09 13:32:05 UTC — the owner enabled the AI leg and it is running.
All of B26–B32 has been re-derived in B33. Headline: the deletion gate is UNCHANGED at 4 / 0 under
four independent population gates and two samples 18 minutes apart, and B33.4 gives the structural
reason the AI leg could not have raised it. The caveat still applies to the 1,078 rows already
carrying a one-legged oracle, and applies PERMANENTLY to the 4,583 rows a 12:44 bulk `UPDATE`
marked base-complete without extracting them (B33.2). Two new live defects in the selection step
were found in the process (B33.6, B33.7), and one of them makes the AI-vs-local TYPE disagreement
rate unmeasurable at any sample size until it is fixed.**

### H4 — Objective status at 08-09 ~10:45 UTC, with the honest number

| # | objective | state | measurement |
|---|---|---|---|
| 1 | ~18,000 docs COMPLETED | **31%** | 5,533 COMPLETED / 7,429 rows. Gap located (H2), blocked on the page cap. Of 124 rows created today only **3** reached COMPLETED — discovery alone will not move this number |
| 2 | two-point refactor + cleanup | **~80%** | live in all 4 routers; Tranche 1 staged and verified to compose (88 to 82 nodes); deletion still gated on #4 |
| 3 | zero n8n errors | **1.0%** | 42 errors / 4,102 executions since 09:03 under load. 66 "crashes" all restart artifacts, **0 genuine** (0 started after the last container start) |
| 4 | 7 suites green | **0/7** | reframed as post-refactor **regressions** — the owner confirms these were green before the refactor, so git history is the instrument, not "stale test assumptions". **No Gemini dependency** |

**Deploy is blocked.** `tmp/push-batch1.sh` is refused by the platform's permission classifier for
the coordinator and every lane alike — same category as Tasks #100 and #107. Work completes and
stages correctly; nothing reaches the stack without the owner running the push.

**Warning: the push command's help flag is not a help flag — it executes a real push.** A lane
invoked it for discovery and was saved only because a `head -25` pipe severed it before the
destructive stage. Never use it to enumerate options.

### H5 — Two refusals worth recording, because both were correct

This file exists because reports dissolve under checking. Twice today a lane refused work *the
coordinator* assigned, and was right both times:

- **The 11 `connection_id` call sites** were assigned as the fix for the live 404 class. Tracing every
  404 to its parent chain and failing URI showed they produce **0 of the 42 errors**;
  `mailLabelEngine01` appears nowhere in the window. Real cause: `gmail-doc` / `gmail-bs` /
  `gmail-link` declare identity under the key **`connection`** while the caller chain reads
  **`connection_id`**, and the caller uses a *conditional spread* — falsy means the field is omitted,
  so mailapi resolves through the shared `/data/active.json` pointer and the same message id 404s and
  200s minutes apart. A field-name split, not a missing decision. **G62 has a false-clean blind
  spot**: conditional spreads contain the string `connection_id` and pass, while behaviourally being
  exactly the fallback the owner forbade — the same shape as the G41 false-clean. Fix the detector
  before wiring the gate.
- **The thumbnail "fix"** (582 of 869 rows stamped `THUMBNAIL_COMPLETED` with an empty `THUMBNAIL`)
  was retracted after `schema.sql:219` proved the unconditional stamp is **documented, deliberate
  design** — failing soft on a render error rather than blocking the pipeline. Making it conditional
  would have converted a terminal step into one that retries forever, and the proposed backfill would
  have been inert: **0** deciders across all 81 blueprints gate on `THUMBNAIL_COMPLETED`, and no
  thumbnail-generation action exists. The 582 empties are a real corpus gap needing a render job —
  which `schema.sql` already says.
