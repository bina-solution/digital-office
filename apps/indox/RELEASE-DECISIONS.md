# INDOX — FINAL RELEASE DECISIONS (2026-09-02, for the autopilot day of 2026-09-03)

**What this is.** The one consolidated decision document for the last full autopilot day before the
production-ready release: what was asked and how it was done, what was measured today, every
decision (old and new) with its reason, the ordered plan with a proof per item, and the few
questions only the owner can answer. Design as built: [indox solution.md](indox%20solution.md).
Running work list with the numbers: [NEXT.md](NEXT.md). Evidence of today's audits is quoted with
file:line so the next session can verify instead of trust.

**Owner rules that bind every item below:** the state machine changes a line only through an
action; failure marks and lands, only an operator's ACTION_RESTART re-runs; the INDOX BFF never
talks to another application; one IMAP connection per mailbox; tags and folders are user-visible
marks, never state; nothing blocks deleting a sync registry; the server carries no change except
`platform.state.yaml`; no credential is ever typed by the agent.

---

## 0. The server (Hetzner VPS `hacohen-prod`, 204.168.193.136) — today's event

Between 10:08 and 10:58 UTC the machine booted four times (10:08, 10:37, 10:42, 10:57), and
between boots a foreign system answered on port 22 with two different SSH host keys and no
https. That is Hetzner's rescue system or a host migration, not anything in this tree (nothing
here reboots a host). After the last boot every container came up healthy on its own, a sync pass
ran at 10:38 and 10:59, executions since boot carry zero errors, and the data is intact: 26,603
documents, 30,384 sync items, 66,021 storage objects with their files on disk.

**Decision S1 — the owner confirms who started the rescue/reboots.** Until then, the server is
treated as stable-but-unexplained; production pushes stay small and verifiable.
**Decision S2 — an off-box backup exists before the release** (nightly `pg_dump` of `supabase-db`
and `n8n-postgres` + `rsync -aX` of the storage volume to a Hetzner Storage Box or object storage,
retention 14 days, restore rehearsed once). Today no off-box copy exists anywhere.

---

## 1. Everything asked so far — how it was implemented and cleaned (summary)

| ask (night brief 2026-09-01 → morning 2026-09-02) | done, with the proof |
|---|---|
| sync state entirely in our DB; discovery once per platform; sync only processes pre-discovered rows; registry needs only the source | `sync_ledger` is the sync item (discovered → claimed → delivered / failed / needs_review), 9 workflows ≤ 10 nodes, ops UPSERT/TAKE/RECORD/FAIL/RELEASE/RESET/REAP/GATE/CURSOR; battery 14/14, sync_full 12/12, sync_sources 16/16, the 8 sync workflows + scheduler at 100 % node coverage; live on the server since release 1 (2026-09-01 23:44) |
| discovery bound by `OldDocumentMonthsBack` so older items are never listed | the bound at three places: Drive `createdAfter` + guard, Gmail `newer_than:<m>m` always + Date guard, TAKE expiry `[expired]`; measured windowed today: link 3/3, bs 6/6, doc 131 of 198 known (see §2.1) |
| `syncOn` editable like `drainOn`, plus `indoxOn` master | three editable knobs; `indoxOn` READ by Main and Drain beside their own switch (never writes them); scheduled drain ends at Gate Closed when off; suite parks/flips/restores it; visible in settings → הגדרות מערכת on the live console |
| mail sync registry editing: pick from the connection's tags, no INDOX tag management | the editor reads the sibling apps in the browser (drive folders, mailbox labels, new-tag creator); proven on the live gmail-doc pipe; **the picker itself drifts — fixed in §4 (N4)** |
| sync UI: one bar (blue / green / red), no docs-state overview, at most a link to the table | one bar per pipe from `sync_item_counts`; the card links to the table filtered on `SYNC_NAME` (1,105 rows for gmail-doc live); **the card lost too much in the rewrite — restored in §4 (N4)** |
| remove console → INDOX → settings → sync | removed (four tabs, none is sync) |
| console → apps → Supabase opens the deployment domain | opens `supabase-studio.hacohen.msh-hac.com` (proven in the owner's session) |
| INDOX table timeouts | trigram indexes + memoised count; 26,573 rows load in seconds |
| remove the SELECTED_* columns | 0 left on the live schema |
| extraction score / fixed certainty per company | `companies.SELECTION_CERTAINTY` + `max(computed, fixed)` in SelectType01; proven with three seeded companies (pipeline 3/3); **the supplier list is data the owner holds** (0 of 1,180 companies carry a value) |
| server: 0 changes except UI state | `git status` on the server = `platform.state.yaml` only, releases 1–4 |
| clean / consolidate / align workflows · api · bff · ui · cli; delete every old reference | 5 workflows retired live (`indoxV2ActionsGDoc01`, `indoxProcessDocument01`, `indoxDocUploader01`, `indoxDocGet01`, `gmailApiRouter01`), driver thinned by 15 dead nodes, 48 legacy docs archived, lints repointed, `mail-private` deleted; gates 25 run / 0 regressions (G60 known-red) |
| `indox solution.md` — sync + state machine fully outlined | written: Part A (sync), Part B (state machine: base + per type, main, drain, driver, action routers), Part C (operating it, server lessons) |
| 80 %+ node coverage on sync + state machine | sync 100 %; state machine CORE 80.8 % over the battery window (documented lanes for the LOW ones remain in NEXT.md) |
| links on mail documents | four causes fixed: missing migrated bytes, missing xattrs, http share links (mixed content), octet-stream uploads (never rendered, and rejected by the AI extractor); 1,230 objects retyped; the document link answers `200 application/pdf` and renders in the console |
| eight sync items "waiting" since Aug 6 | TAKE dead-letters an empty listing a day after discovery with `[unlisted]`; live: 8/8 retired at the 07:26 pass |
| the 06:22 Main crash | the scheduler's 300 s deadline bounded every pass (n8n hands a parent deadline down); scheduler → 1800, Discover Gmail soft-fails; zero errors since |

---

## 2. Measured today (server, 10:00–11:05 UTC) — the facts the plan rests on

### 2.1 Sources vs the sync ledger (the owner's core question)
- **Drive is consistent.** WhatsApp folder: newest 500 all known (499 delivered, 1 review); drive-bs 2/2; the gdoc source folders are empty because deliveries move files out.
- **Mail inside the 6-month window:** `DOC_LINK_TO_SYNC` 3 → 3 delivered; `BS_TO_SYNC` 6 → 6 delivered; `DOC_TO_SYNC` 198 → 127 delivered + 4 needs_review; **67 missing: 11 are documents the retired engine made in August, 56 are unknown to both the ledger and the document table.** Sample `19cbd2ce2f196f2c` (5 Mar 2026) carries `לטיפול-אוטומציה-שמירת-מסמכים` and no SYNCED mark. Cause to confirm on day 1: the 2026-08-28 migration planted the gmail-doc cursor near the top, so the walk never listed what sat below it.
- The labels still hold the retired engine's marks: `DOC_TO_SYNC` 38,088 messages, `SYNCED_DOC` 16,809, `FAILED_DOC` 861, `IN_PROGRESS` 1,790 — while the ledger holds 2,111 gmail-doc rows (v3 started 2026-08-28).

### 2.2 The 186 red items and "נסה שוב"
Every `needs_review` row has an EMPTY listing and NO reason: the 2026-08-28 migration rows (one with
`platform_id = 'e3'`) plus 130 orphans of the deleted `mail-private` pipe. `RECORD needs_review`
never writes a reason (`syncLedgerApi01.workflow.ts:140-147`). RESET skips empty listings
(`skipped_no_listing`), the BFF drops that count (`api/__init__.py:4790`), and retry starts no pass —
the button would say "0 פריטים חזרו לתור".

### 2.3 The label engine
`mail01` (the 15-min fan-out) was `active=false, activeVersionId=null` since an **import** on
2026-08-31 03:34 (the bare-import footgun); its in-memory trigger died at the 14:30 restart; the
engine had not run for two days. **Re-activated from the blueprint at 11:01 UTC today** (forced
push; the compare-and-swap base was the import's). The engine labels at most **10 messages per
mailbox per tick** (`mailLabelEngine01.workflow.ts:1303-1338`) with no cursor — the `PROCESSED`
label is its only state — so a backlog drains at ~960/day/mailbox.

### 2.4 AI extraction on the server
The Gemini key is byte-identical to the laptop's; the credential `ai-studio-bs-extraction` exists;
`extraction_ai_enabled = true`. Over 7 days 89 % of completed documents carry AI values. Of the
AI-less completed documents of the last 2 days, **736 were extracted before the 06:50 type repair
and 4 after**: the download's `Content-Type` came from `drive_files.mime = application/octet-stream`,
the extractor's `File Type Router` matches it exactly (`indoxV2ExtractInvoiceGemini01.workflow.ts:197-382`)
and answered `unsupported_file_format`; the base AI leg then recorded `AI_STATUS = 'ran'` anyway
(`BaseDocEx01.workflow.ts:633-638`), so the failure was invisible. `extraction_model` is a dead
knob (models hardcoded at `:1081, :1100, :1122`).

### 2.5 שריזלי-01010 and the blank ERROR column
Born from a balance-sheet line, typed INVOICE at birth, its file found in Drive on 08-31, then
parked `API_TOOLS_FAILED` twice with no OCR call: base extraction accepts only type-less documents
(`indoxV2ActionsGlobal01.workflow.ts:1400`), so a typed document never gets an `API_TOOLS_ID`, and
the per-type gate parks it (`indoxV2ActionsInv01.workflow.ts:2143-2158`, known since
`issues/typed-documents-cannot-be-extracted-2026-08-26.md`). The writer emits `ERROR: null`, which
`indoxApi01` strips (`Resolve IDs`, `:502`) — 67 of the 87 `API_TOOLS_FAILED` rows of the week have no
text; `errorHandler01` records only `action failed @exec N`; `ACTION_RESTART` cannot clear `ERROR`
for the same reason; the BS lane never writes `ERROR`.

### 2.6 The dashboard "ציון חילוץ" 22 %
Four of the five bars read stage-completion stamps (`COMPANY_NAME_COMPLETED`, `DOC_DATE_COMPLETED`,
`DOC_TOTAL_AMOUNT_COMPLETED`, `AI_EXTRACTION_COMPLETED`, `api/__init__.py:1360-1376`) that only the
invoice and shipment lanes write, that every restart wipes (`schema.sql:124-125`), that a COMPLETED
document never re-acquires, and one of which is a picture of the AI toggle. The fifth bar reads the
value (`DOC_ID`) and says **94 %** — the real rate. The headline is the unweighted mean of one
measurement and four kill switches; the bars print counts without a `%` (`DashboardPage.tsx:110`).

### 2.7 The mail UI
No cache at any level. Opening a message costs NOOP + SELECT + SEARCH + 2 FETCH **plus a full RFC822
fetch of the whole thread with attachment bytes that are then discarded** (only for 80-char
snippets). Everything queues on the one per-mailbox `RLock` shared with 300 s sync gets, 50–125 s
discovery searches, the engine and the docker healthcheck; `IDLE_NOOP_S` is documented and not
implemented (a throttled NOOP ≈ 6.5–10 s on every checkout); the console proxy gives up at 40 s.
The client fakes archive / trash / snooze / read state in memory (no request, reload restores),
traps the user on the organizer page, discards upstream error text, and cannot deep-link.

### 2.8 The label-rules feature
One evaluator (`mailLabelEngine01.workflow.ts:775-1170`, `new Function` over the rule string, 20
helpers, `email/thread/attachments`, `TYPE === 'ON_CREATE_EVENT'` is the only load-bearing switch,
`-LABEL` removes, row order is priority and stateful) — but **two live stores**: the mail app's
`/data/organizer-defaults.json` (read by the engine, mailapi search, mailview) and
`indox_<tenant>.tag_rules` in Postgres (still read by `syncV3Main0001:143` for KEY → name,
`indoxV2ActionsGlobal01:2527-2535, 2706-2718` for feedback tags, `indoxSettings01:1975-2019`, the mail
gate `mailOrgTest00001:458, 965` and the test harnesses). The fixtures are byte-identical copies;
the live table drifted (27 rows vs 23). The editor is 72 lines of `prompt()` with no validation,
no ordering, no label picker, no enable flag, no preview, English headers, no deep link.

### 2.9 The INDOX webapp (button by button)
The sync editor's pickers drift three ways (a stored id absent from the list renders as the
placeholder — the destination reads "ללא — הקובץ נשאר במקומו" while one is configured; a failed
sibling call degrades to a raw-id text box; **save rebuilds `pairs[0]` and destroys `failed /
failed_to / in_progress`**, hardcodes `projection:'on'`, and "צור" overwrites an untouched field);
the drawer remounts every 5 s. Elsewhere: failures painted in green callouts, bulk delete results
discarded, the drain link never shown (wrong key), an unguarded status `<select>`, six notice idioms,
no error boundary, no 404 route, tabs not in the URL, native `confirm` on pipe delete, unconfirmed
extraction-run delete and E2E runs. Dead: 6 `api.ts` functions, 5 BFF routes, 3 declared-never-set
fields. (No RevoGrid: the grid is TanStack Table + Virtual.)

---

## 3. Decisions

### 3.1 Standing decisions from the night (kept)
D1 state lives in `sync_ledger` only · D2 discovery bounded by the window at three places · D3
`indoxOn` is read, never written, by the lanes · D4 the BFF talks to no other app · D5
`needs_review` is terminal, `failed` retries with backoff · D7 TAKE dead-letters `[expired]` /
`[unlisted]` · D10 https share links + type from the file name · D11 the root of a dispatch chain
carries the longest timeout · D12 driver thinned, five workflows retired · D13 gmail take 25 /
chunk 5 · D14 fixed certainty = `max(computed, fixed)` · D15 `SELECTED_*` gone · D16 settings → sync
tab gone · D17 Supabase launcher · D21 local `indoxSyncOn` off.

### 3.2 Decisions revised today
- **D6 → RESET resets empty-listing rows too** (status `discovered`; discovery re-lists what still
  exists, TAKE retires the rest with `[unlisted]`), returns `reset / skipped` honestly, and **starts a
  pass** so the card moves within one pass.
- **D8/D9 → migration and orphan rows get a reason and a rule.** Backfill `[legacy] migrated
  without a listing` on the 2026-08-28 rows; delete the 130 `mail-private` orphans now; a registry
  delete removes its rows after a confirmation that states the counts.
- **D18/D19 (the thin sync page) → the card comes back (N4)** without violating D4: source-side
  facts are read by the browser from the sibling apps, exactly as the editor already does.
- **D20 (`failures: []`) → reasons chips from the ledger** replace the dead field.

### 3.3 New decisions
- **N1 One rule store.** The mail app's organizer JSON is the only store of label rules. INDOX
  resolves KEY → label name through `GET http://mailapi:8970/organizer/settings` (an n8n-side
  call, not a BFF call) at the three runtime sites; the mail gate reads the same; then the INDOX
  settings tab "חוקי תיוג", its BFF route, its fixture copy and the `tag_rules` table retire
  (migration with a backup of the table). The 27-vs-23 drift is reconciled by keeping the organizer
  names (they are the ones on 15,575 live messages).
- **N2 The rules editor is a real editor**, in the mail app only: server-side validation on PUT
  (unique non-empty KEY, non-empty LABEL, TYPE from a picker, a parse of RULE), Hebrew headers with
  a one-line legend per helper, inline cells (RULE in a monospace LTR box, `inList` arrays as chips),
  a label picker with "create" and the `-` remove form as a toggle, an explicit order column with
  move up/down that renumbers `row_number`, a per-rule `enabled` flag the engine honours, a preview
  ("of the last N messages these would match") powered by the same helper library lifted into a
  shared file, dirty-state guard, `/organizer` as a route, a `previous` snapshot on every PUT, and a
  refusal to delete or rename `PROCESSED` without confirmation. `enabled / schedule_min /
  batch_limit` are wired or removed — never dead knobs.
- **N3 The label engine drains a backlog.** Tick batch 10 → 50 (bounded, one add + one remove call
  per message as today); the dead sched lane, the `row_number === 8` debug dump and the ghost
  `staticData` go; `mail01` guards `PROCESSED` the way the engine does; the stale workflow map is
  regenerated by a pull. **Shipped today (commit `672984d6`, live 11:37 UTC):** the tick probes
  every registry connection, skips a failing one with its reason, runs once per mailbox
  (`account_hint`), and stamps the skipped list on the outline — the first ticks after
  re-activation had dispatched all ten registry entries (the client's Gmail, two entries into the
  developer's solutionsbina mailbox, seven local test mailboxes whose login fails on the server),
  ten error executions per tick. **Proof, the 11:45:11 tick:** outline
  `label_engine_x4_conns_skipped6`, the skipped list naming each failing login and the duplicate,
  four engine runs, zero IMAP error executions.
- **N4 Sync page v2 — the card and the summary.** Card: name, connection label + health (browser
  read of `/api/connections`), readable folder/label names (browser read, cached per session), the
  4-segment bar (to sync · in progress · synced · failed) with "needs review" as its own count, the
  top three reasons as chips (BFF `/sync/registry/<name>/reasons`, ledger group-by), cadence
  (`every N min · take · chunk`), last run with `פתח ב-n8n ↗`, oldest waiting, the table link,
  actions with confirmations. Summary: totals per state, sources count, last pass (time, duration,
  units, link), next pass ETA from `app_schedule_state`, master switch, freshness with the DB clock,
  the instance tag, and "בדיקת התאמה" (browser-side source-vs-ledger reconcile per pipe, the recon
  script's logic). **Browser-side cross-app reads are allowed** (the BFF rule is about the server).
- **N5 Sync editor is additive and honest.** PATCH only changed keys; spread `pairs[0]`; pin the
  stored value (`— לא נמצא ברשימה`); a searchable, sorted picker that shows the id and the
  connection; loading and error states instead of a silent text box; `Select` hoisted and the poll
  frozen while the drawer is open; "צור" writes into the focused field; the failed folder/label and
  `schedule_min` editable again; a review step before the first save of a new pipe.
- **N6 Reasons everywhere.** `RECORD` carries `reason`; every terminal delivery passes its own;
  the card and the items list show them.
- **N7 Error plumbing.** The API writer accepts an explicit null for `ERROR` on restart;
  `api_tools_failed` writes its reason; `errorHandler01` records the message; the BS lane and the
  base AI leg record failures (`failed: <reason>`); the `File Type Router` falls back to the
  extension / sniffed type (apitools already sniffs); `extraction_model` is wired to the nodes or
  deleted.
- **N8 Typed-at-birth documents get base extraction.** The base gate becomes "no `API_TOOLS_ID`
  yet" instead of "no TYPE"; the type authority (`type_hint` / `fallback_type` / `TYPE_BY_SOURCE`) is
  kept as a floor for the selector. Closes the `API_TOOLS_FAILED` parks (67 of 87 blank ones this
  week) and the AI-less typed documents.
- **N9 Extraction score = coverage of final values on completed documents, type-aware.** Bars:
  חברה (`COMPANY_ID`), תאריך (`DOC_DATE`), מס׳ מסמך (`DOC_ID`/`INVOICE_ID`), סכום
  (`DOC_TOTAL_AMOUNT`/`BS_LINE_AMOUNT`, only INVOICE and BALANCE_SHEET), סוג (`TYPE`); headline =
  mean over applicable fields; "ודאות ההתאמה" = mean `SELECTION_CERTAINTY` beside it with its own
  denominator; `%` printed; the e2e assertions S22/S24 updated. The four legacy flags leave the
  read model.
- **N10 The 56 unknown messages get discovered.** One-time: reset the gmail-doc cursor to walk
  from the bottom inside the window (the engine's `walk` mode, page 25 per pass → ~8 passes), then
  the reconciliation proves 198/198 known. History before 2026-08-28 is NOT imported into the
  ledger; the sync page states "היסטוריה מ-28/8/2026".
- **N11 Mail UI honesty first, speed second.** Archive / trash / snooze / read persist through
  `/api/mark`; error text travels to the banner; a real failure state at boot; `/v/<view>` and
  `/organizer` routes with `bina:route` mirroring; rail counts from the server or none; send shows the
  sent message; the tag picker can create; "הדפס" prints or goes. Speed: thread fetch off, idle-noop
  honoured, non-blocking `readyz`, neighbour prefetch; then a **body cache filled by the sync
  deliveries** (mailapi-side on its `/data` volume, keyed by gmail id) so an INDOX-touched message
  opens without IMAP. **No second IMAP connection** (the owner's rule stands; measure after the
  cache).
- **N12 One mail client.** The duplicate client half of `apps/mail/mailapi/static` is deleted;
  its three unique screens (mailbox creation, DNS/DKIM setup status, guided provider connect) move
  into mailview under a console tile, or the directory keeps only those. Zero-caller endpoints
  (`/providers` unless consumed, `/connections/<cid>/options`, `/organizer/effective/<cid>`,
  `/labels/delete`, `/labels/rebuild`) go; test modules leave the image. Removal touches five
  places: `apps/mail/mailapi/static/`, `service.py` `ui_index` + `/ui/unread` + `/ui/attachment`, the
  three `mailui-*` traefik routers in `apps/mail/docker-compose.yml`, the `sso` block in
  `apps/mail/app.json` (so `platform-base/authentik/blueprints/zz-generated-apps.yaml` regenerates
  without the `mailapi.localhost` pair), and `scripts/ui-coverage/manifest.yaml:29`; `MAIL_UI_BASE_URL`
  goes with them.
- **N13 INDOX webapp hygiene.** `useToasts` exported and used everywhere (a failure can never be
  green); `ConfirmModal` on pipe delete, the status select, extraction-run delete and E2E runs;
  route-level `ErrorBoundary` + a 404 route; tabs and views in the URL; the drain link read from
  `execution_id/n8n_url`; bulk results reported truthfully; the connection named on every card and
  picker; Feather icons everywhere; a sentence on every icon-only button.
- **N14 Dead code goes** (with the evidence gathered today): `api.ts` `removeInstance` (or a UI
  for it), `createRepo/deleteRepo/patchRepo/repoStats/syncRepo`, BFF `/timeline/spans`,
  `/repos/<repo>/kafka/tail`, `/extraction/results`, `/extraction/compare`, `dashboard-stats-schema.sql`,
  the `_sync_stats_*` comments, `ztestMailDiscovery01.json` + `ztestGmailApi01.json` copies,
  the retired chain `indoxGmailActionsScanner01 → indoxGmailActionProcessor01 → whatsappSendDoc01`
  (zero executions, `active:false`, listed in `.claude/WORKLEFT.md:116` as awaiting the owner's
  verdict "is this generation retired?" — question 5 below; its removal unlocks the `indoxSettings01`
  gmail branch), the `VALIDATION STATUS/ERRORS` columns, the stale docs
  (`ai/context/mail-labels-and-rules.md` §2–3, `mail-organizer-refactor.md` header, the
  `mailOrgTest00001:777` comment). **Never `.generated/`** — it is build output that regenerates.
- **N15 Security.** The hardcoded fallback Vision key in `apps/apitools/.../ocr_processor.py:19` is
  removed and the key rotated by the owner.
- **N16 Reasons for retry are the proof of "נסה שוב".** The owner's test is run only after N6 + D6:
  click → N items blue → the pass runs → each ends green or red with a reason on the row.

---

## 4. The autopilot plan (2026-09-03) — ordered, each item with its proof

Proof discipline for every item: the change ships as code; the suite or gate that covers it is
green; the executed proof is quoted (execution id or live number); the live console shows it in the
owner's session; NEXT.md gets the number.

**Phase A — the engine tells the truth (morning)**
A1 N6 reasons on RECORD + deliveries; backfill `[legacy]`; delete the 130 orphans; registry delete
removes rows with a confirmation → proof: ledger has zero reason-less review rows; sync_sources
green; the card shows reasons.
A2 D6 retry → reset all + start a pass + honest counts → proof: the owner's click on gmail-doc:
N blue, then green/red with reasons within one pass (recorded execution ids).
A3 N10 the 56 unknown → cursor reset + walk → proof: recon2 says 198/198 known.
A4 N7 error plumbing + N8 typed-at-birth base extraction → proof: שריזלי-01010 restarted lands with
an OCR id, AI values and a reason if it fails; the decide suite gains the typed-at-birth lane;
`API_TOOLS_FAILED` rows carry text.
A5 N3 label engine batch + cleanup → proof: `mail01` ticks, the engine outline shows > 10 handled,
the backlog shrinks per tick, zero errors.
A6 N9 the score → proof: the SQL diagnostic in NEXT.md reproduced (5/4/4/3 → real values), the
card reads the coverage with `%`, e2e S22/S24 green.

**Phase B — the UI a human can manage (midday)**
B1 N5 the sync editor (pickers, additive PATCH, hoisted Select, confirmations) → proof: flow-qa
lane for the editor; drive-bs edited live without touching `failed`; the picker shows the stored
folder by name with its connection.
B2 N4 the card + summary v2 → proof: live screenshots in the owner's session; the reconcile button
reproduces recon.sh numbers.
B3 N13 hygiene across pages → proof: the QA inventory rerun finds zero P1, zero P2.
B4 N1 + N2 the rules store and editor → proof: INDOX tab gone; sync main resolves labels through
mailapi (executed pass); mail gate green against the organizer store; the editor validates,
previews, orders; a bad rule cannot be saved.

**Phase C — mail (afternoon)**
C1 N11 honesty (persisting actions, errors, routes, boot state) → proof: flow-qa mail lane; a reload
keeps an archived message archived.
C2 N11 speed quick wins → proof: `/stats` commands per hit halves; open-message under 5 IMAP
commands.
C3 N11 body cache from deliveries → proof: an INDOX-touched message opens with zero IMAP commands,
measured under 1 s in the console.
C4 N12 one client → proof: the second UI's three screens reachable from a tile; the duplicate half
deleted; gates green.

**Phase D — cleanup, docs, security (late afternoon)**
D1 N14 deletions with the evidence table; D2 N15 the Vision key; D3 `indox solution.md` Part A/B/C
updated for N1–N11; D4 NEXT.md numbers; D5 the audit page.

**Phase E — release + live verification (evening)**
E1 commit/push; E2 server release (pull, migrations with backups, `bbox run`, pushes, cache flush);
E3 the owner's browser pass of every page with the checklist in §5; E4 zero errors over two hours of
passes; E5 S2 backup rehearsed once.

---

## 5. The human-management checklist (what "0 issues" means, page by page)

Every control has a Hebrew label that says what will happen, a busy state while it runs, a
success or failure notice in one channel, a confirmation with measured facts if it destroys or
re-runs work, a link to the execution when one exists, and a visible effect afterwards (a count
that moves, a row that changes, a page that refreshes). Every list has an empty state and a
failure state. Every screen is deep-linkable and survives a reload. Every picker pins its stored
value and names the account it lists from. No English database identifiers on a Hebrew page. No
emoji icons. No native `prompt` / `confirm`.

---

## 6. Questions only the owner can answer

1. Who started the Hetzner rescue/reboots today (10:08–10:58 UTC)? (S1)
2. May the agent create the off-box backup target (Storage Box / object storage credentials are
   the owner's to provide)? (S2)
3. The suppliers' fixed-certainty list (which companies at 90+) — the column and UI exist; the
   data does not.
4. Anything in §3.3 to veto before the day starts — the plan runs on autopilot otherwise.
5. Is the Gmail-actions generation retired (`indoxGmailActionsScanner01` → `indoxGmailActionProcessor01`
   → `whatsappSendDoc01`, zero executions, inactive)? A yes deletes the three and the duplicate
   labels builder in `indoxSettings01`; the same verdict is wanted for the two duplicate-shaped pairs
   `indoxDocUploader01` vs `indoxV2UploadApiTools01` and `fullDocEx01` vs `indoxProcessDocument01`.
6. The server's mail registry: may the seven `mail_imap_local-*` test mailboxes and one of the two
   solutionsbina entries be deleted, and should the label engine run on person2@example.com
   (the developer's mailbox) at all, or only on the client's? Today the scheduler skips the dead
   ones and the duplicate by itself; the registry still shows them.

---

## 7. Status at the close of 2026-09-02 — what shipped, what was proven, what is left

The owner's answers to §6 arrived during the day: 1 (the reboots are another employee's work —
ignore the host), 3 done, 4 no veto, 5 yes (the chain is gone, blueprint and live), 2 and 6 still
open. Everything below is measured on the laptop stack, on the owner's OWN connections
(`mail_imap_app_password-83db1e42` = solutionsbina, `drive_local-19213e58` = מנהל, brand-new
`INDOX/<pipe>/{to_sync,synced,failed}` trees, the client's connections removed from the connections
app) — nothing here touched the client's mailbox or Drive.

### 7.1 The real end-to-end run (`data/_e2e/e2e-final-1840.*`, driver `scripts/ops/indox-e2e-real.py`)
9 real mails sent from the mailbox to itself and labelled with each pipe's to-sync label, 12 real
files uploaded into the four drive pipes' `to_sync` folders, one pass kicked, polled to the end.
**21 of 21 items delivered within 1–4 s of discovery; 18 documents born** (the link pipe's three
messages carry the same URL and correctly became ONE document). Sent → discovered: drive 6–19 s,
gmail 81–84 s (45 s of it the driver's own wait before labelling). Delivered → done, per pipe
(median): drive-bs 12.5 m · drive-gdoc-chat-export 6.4 m · drive-gdoc-scanned 8.7 m · drive-whatsapp-bot
7.4 m · gmail-bs 5.9 m · gmail-doc 8.2 m · gmail-link 4.0 m. Completed: 17 of 18 (one drive-gdoc-scanned
document merged into its double; the link document was judged IRRELEVANT — the public link was a
dummy PDF, and that verdict is right). The feedback lane executed (`source_feedback_0`, 3 s) and the
labels/folders moved. Two facts the run taught: (a) the demo corpus is dated 2025, so the driver
widens `OldDocumentMonthsBack` for the run and restores it — and the late age gate then re-parks
every completed 2025-dated document as OLD on the next pass (correct product behaviour; the driver
gained `--keep-window` for inspection runs); (b) a message a label still lists but All Mail no longer
holds (trashed) 404s on every delivery — now a terminal reason.

### 7.2 "נסה שוב", proven in the owner's console
gmail-doc, 113 red items (112 migration rows without a listing + the trashed message): the
confirmation states the counts and the reasons; the click resets all 113 to לסינכרון and starts the
pass; one pass later every one of them is red again **with a true reason** — `[unlisted] no listing a
day after discovery: the source no longer lists this item` ×112, `… [terminal] the mailbox no longer
holds this message (trashed or spam)` ×1. Found and fixed on the way: the browser's 12 s budget
cancelled a request the server kept honouring (now 150 s, the server's own bound); per-item ids
turned 25 identical reasons into 25 chips (the view folds identifiers).

### 7.3 Shipped today beyond the plan (each with its proof in the commit message)
- `indoxSettings01` carried a reference to a removed node and threw on EVERY settings load for
  three minutes live (the whole pipeline) — the dead guard removed, the stale DSL edge removed;
  memory note written so it is not repeated.
- Feedback semantics: the outcome label is added AND the to-sync label removed in one mailapi call
  (`/labels/add` with `remove`, Gmail and local backends); drive-bs and whatsapp-bot moved from the
  client-era `feedback: off` to `drive_move` on the laptop registry (their folders are distinct now).
- The sync page resolves organizer KEYS to the Hebrew label names the mailbox carries (the cards read
  "לא נמצא ברשימה" on every pipe before); the editor offers the organizer's labels by name.
- The mail client under the console was dead on arrival (a comment that spelled out the base tag
  suppressed the console's injection; every script resolved against the console root) — the mount is
  now read off the URL; memory note written.
- Gates: `rules-lib-parity-lint` (G71) wired; `app-coupling-lint` and `decide-lane-reachability-lint`
  wired KNOWN_RED with their measured findings (3 cross-app references; 10 router lanes no decide
  feeds, `source_feedback` exempted with its executed proof); `n8n_blueprint` declared a library.
  Decide suite 58/58 after two stale fixtures were corrected to the value-based rules.
- Cleanup: `mailDiscovery01` blueprint (dead, a whole-app push would have re-imported it) and its
  `ztest` harness removed; stale lint entries; the 14 old fixture messages still under to-sync labels
  moved to their synced labels; zero thumbnail rows created (20,442 storage objects, the 36 new ones
  are the run's real deliveries); `tag_rules` gone and `sync_item_reasons` present on all three tenants.

### 7.4 Left for the owner (blocked or a decision)
- **Six live-only n8n workflows, never executed, deletion refused to the agent** (a destructive action
  on live data): `drainPoolTarget01`, `drainPoolTest01` (active, 2026-08-21), `indoxV2Upsert01`
  (2026-07-30), `N9EcdCZaQQJTVDea` / `UasPRNzYwO2z7nbN` ("AB MapRequest", 2026-08-26),
  `ztestMailDiscovery01` (its blueprint is deleted). Delete them in the n8n UI; `bbox n8n status`
  reads 93 vs 99 until then.
- The 10 dead router lanes and the 3 cross-app references (§7.3) — one verdict per lane / reference.
- Another session worked the document viewer in this tree at the same time (its files are
  uncommitted and untouched here); its `bbox run` at 15:59 UTC recreated n8n mid-battery, which is
  why the first battery run of the day died on a refused connection. Every `bbox run` recreates n8n
  even with nothing changed (the rendered config hash moves between runs) — cause not pinned today.
- Questions 2 (off-box backup) and 6 (the server's mail registry) stand.
- **A removed connection makes its documents loop (product gap, owner decision).** On the laptop
  the client's Google and Gmail connections were removed by instruction; the client-era documents
  that still name them (`LINK_CONNECTION` / `SOURCE_LIST[].sync_connection`) park correctly
  (`API_TOOLS_FAILED · failed_to_get_gd_link`, feedback "החשבון שנבחר … אינו קיים יותר"), but the
  driver's always-recoverable statuses re-pick them every pass — measured 66 `driveApi01` 404s and
  104 `gmailApiImap01` refusals in ten minutes, ~500 error executions an hour, forever. Production
  has the connections and never sees this; an operator deleting a connection would. The decision
  to take: a document whose connection is no longer registered parks with "החיבור הוסר" and leaves
  the recoverable set (a query change in `indoxApiSupabase01`'s candidate reads, plus the reason
  in the writer). For the proof window the laptop's `indoxOn` was switched off (the focused run
  switches it back on itself).

### 7.5 The owner's second verdict on the sync page ("it looks like shit again") — what changed
Two screenshots, both read the same way: a lone "הסבב הבא" tile floating under a row of seven, English
engine strings as chips and in red ("[legacy] migrated from the retired engine…", "drive item 122XgF…
has no md5 in its …"), `drive_local · admin · admin` in a card headline, a wall of small grey meta lines
under every card, and a footer mixing `.btn` with text links whose icons stacked over their labels.
The code was right; the screen was not. Three things were done, in this order:
1. **A standard, as a skill** — `~/.claude/skills/platform-ui-ux/SKILL.md`: the design system to
   reuse, twelve laws (RTL page / LTR token, Hebrew copy always, no identifiers in the reading line, a
   grid never leaves a lone tile, one button family per row, key-over-value facts, three type sizes,
   colour = state, every control explains and answers, every screen is a URL, density over
   whitespace, embedded means embedded), the two-minute design plan before code, and the proof
   protocol: rebuild the image, open the REAL console in the owner's Chrome, screenshot top and
   scrolled, walk the checklist item by item, report the screenshot's facts. Memory note
   `ui-ux-standard-is-a-skill` makes it standing.
2. **The page rebuilt to that plan** (`SyncStatePage.tsx`, `sync.css`, `reasons.ts`): five state
   tiles in one row + ONE pass strip (sources · last pass · next pass) that cannot float a tile; pipe
   cards two-up from 1100px; a hairline facts grid (source · after sync · failures · files saved to)
   with the NAME as the value and the id one hover away; the connection by its label only; reasons in
   Hebrew through a dictionary of engine sentences (count first, kind-coloured, the original in the
   tooltip and in the drawer); a one-row activity line (cadence · last run ↗ · last delivery · oldest
   waiting) and the table link; a footer of one button family (switch · הרץ · נסה שוב · פריטים |
   עריכה · מחיקה); the type tag in Hebrew; the header switch a real switch and one primary verb.
   **Proof, in the owner's Chrome under the console (`#/m/incoming/i/hacohen/sync`, 1552 px):**
   five tiles in one row (0 · 0 · 3,714 · 0 · 187, each in its state colour), one three-cell pass strip
   (7 מקורות · 7 פעילים | סבב אחרון לפני 2 דק׳ · הופעל · פתח ב-n8n on one line | הסבב הבא בעוד 13 דק׳ ·
   20:11 · כל 15 דק׳), seven cards in four rows of two, every card's facts by name (INDOX/drive-bs/to_sync
   … · לטיפול-אוטומציה-קישור-למסמך …), the connection as "מנהל" / "Gmail solutionsbina", reasons as
   "25 · לפריט בדרייב אין חתימת קובץ (md5) ברישום" and "23 · שורה מהמנוע הקודם — ללא רישום במקור", one
   activity line per card, one button family per footer, zero English sentences, zero ids in the
   reading line, browser console clean. The static-gate and battery numbers of the same build are in
   §7.6.
3. **What the redesign uncovered:** the md5 dedupe on drive uploads (Decision 10) broke the `bs` and
   `gdoc` suites twice — bytes-only answered a NEW name with an old file, name+bytes answered a fresh
   upload with a file from hours ago that the suites no longer found among the newest hundred they
   list ("fixture link resolution failed"). The dedupe is REMOVED: Decision 10 is met at its source
   (no raster upload exists any more), and documents are deduped by content hash in the ledger, not
   files in the drive. Documents that still point at the client's removed Google
   connection park terminally on this laptop (`API_TOOLS_FAILED · failed_to_get_gd_link`), which is
   the law working; the 37 `driveApi01` error executions behind them are the absorbed sub-calls.

### 7.6 The proof window, closed (laptop, 2026-09-02 15:37–17:44 UTC, `data/_e2e/`)
**Static gates** (`run-gates.py`): 28 run · 0 regressions · 3 known-red, all three wired today on
purpose (G60 one-branch-guard, G33 app-coupling 3 findings, decide-lane-reachability 10 dead lanes) ·
G71 rules-lib-parity PASS (49 helper lines identical) · zero unwired gates left.
**INDOX battery** (`bbox indox test all`, n8n untouched from 16:56 to the end): decide 58/58 ·
sync_kernel 34/34 · sync_full 12/12 · sealed_inv 5/5 · sealed_ship 4/4 · sealed_bs 3/3 · sealed_ord 1/1 ·
sealed_rcp 1/1 · doc_base 3/3 · **pipeline 3/3 — 17 documents (5 inv + 5 ord + 5 shp + 2 bs) through the
LIVE pipeline, COMPLETED and byte-identical to ground truth in 206 s**. Not green in the battery:
sync_sources (timed out at 902 s while 110–138 extractions ran at once — it passed 16/16 in 228 s
alone this morning) and bs / gdoc (the upload dedupe, §7.3). **Re-run alone on the quiet machine
with the dedupe gone: bs 4/4 · gdoc 5/5 · sync_sources 16/16 in 189 s — thirteen of thirteen.**
**Mail suite** (`bbox mail test`): mail_organizer 2/2 — label-engine 8/8, system-labels 3/3 (23 names).
**Node coverage** (`n8n-node-coverage.py --since-id 3892177`, the real E2E + every suite above):
**CORE 83.7 % (576 of 688 nodes; bar 80 %)** — the sync engine 8 of 8 workflows at **100 %**
(syncV3Main, syncLedgerApi, both discoverers, syncRun, the three deliverers), indox01 100 %, Decide 100 %,
Driver 94.7 %, ActionsGlobal 90.5 %, BaseDrain 92 %, the selectors and JQ extractors 100 %. Under the bar:
ActionsInv 76.2 %, ActionsShip 63.8 %, SearchWarehouse 76.9 %, mailLabelEngine 75.7 %, processLock 38.9 %
(8 of its 36 nodes are disabled renew lanes). What the unexecuted nodes ARE (the report names each):
`Stop and Error` sinks and dry-skip parks a green run never reaches, the ten router lanes no decide
feeds (§7.4 — they cannot be executed by any input), and per-type branches for statuses the corpus
never produces. **100 % is not reachable without deleting the dead lanes (the owner's per-lane verdict)
and writing failure-injection lanes for the sinks** — the honest number is 83.7 % with the sync
engine complete, up from 80.8 % over the morning's window.
**Concurrency** (`ci-concurrency-report`, 3 h, 21,690 spans, profile wsl-10g, 8 n8n workers): peak
72+ concurrent executions during the pipeline suite; p50/p95 per service — Action Router 4.8 s / 196 s,
DOC BASE 0.65 s / 114 s, Base Document Extraction 35 s / 115 s, Sync Deliver Gmail 19 s / 48 s, Sync
Deliver Link 17 s / 138 s, mail api 2 s / 6 s, drive api 1.7 s / 6.5 s, indox api 0.5 s / 5.5 s. The
drain pool shows 17 of 22 runs crashed or errored in the window: those are the drains n8n's
recreations at 15:59 and 16:09 killed mid-flight (§7.4) plus the removed-connection refusals (drive
api 451, mail api 108 error executions — the laptop-only condition of §7.4). The machine's honest
verdict: the whole battery fits a 6-core / 10 GB WSL box only in sequence; a suite that drives real
deliveries (sync_sources) needs the box to itself.

**The focused feedback run** (`e2e-fb-1756`, one document on gmail-doc, gmail-bs, gmail-link, drive-bs,
drive-whatsapp-bot, after the day's feedback changes): gmail-doc completed in 6.0 min and its message
now carries ONLY the synced label (`אוטומציה-שמירת-מסמכים-טופל` + the engine's `תוויות-טופל`) — the
to-sync label removed in the same call, as designed; gmail-bs parked `MISSING_COMPANY_ID` (the corpus
report names no known company — a person's call, no feedback by design); gmail-link deduplicated onto
the morning's link document (same URL, same hash — one document, as designed); drive-bs and
drive-whatsapp-bot completed in 4.9 / 5.3 min but their files did NOT move — their deliveries carried
`required_feedback_type = null`, because the day's `feedback → drive_move` edit had been written to
`public.settings` (the console instance's mirror) while `syncV3Main0001 · Read Config` reads
`indox_<tenant>.settings`. Re-saved through the BFF's PATCH (which writes the engine's table and
invalidates n8n's settings cache); the drive-only proof run follows in §7.8. Lesson recorded in memory
(`sync-registry-lives-in-tenant-settings`); the E2E driver now reads the tenant table.

### 7.7 Release 5 on hacohen-prod (2026-09-02 17:56–18:02 UTC) — the app, not the host
Branch `indox-final-consolidation` (every session's commits of the day, 25 on top of what the server
ran) pulled; migrations applied to `indox_hacohen` (the reasons view with folded ids, `tag_rules`
retired); `bbox run` rebuilt drive, mailapi, mailview; 20 workflows pushed (17 INDOX, `errorHandler01`
and `indoxApiSupabase01`, the three mail ones), the retired Gmail-actions chain confirmed gone
(`retired-present=0`), 74 active and published of 100; the n8n cache flushed. **The first pass failed
the app image**: the branch imported a component the concurrent session had deleted while its
replacement sat uncommitted (TS2307 in a clean checkout) — the six files were committed as they stood
(`e164fa6b`, `31be1c7f`) and the app image rebuilt alone at 18:02 (`--no-deps`, n8n untouched).
**Proofs on the box after that:** registry reachable, summary present (7 sources, 186 needs_review),
reasons on every red pipe (`[legacy] migrated…` 112/23/23/17/2/1, `[unlisted]` 8 on drive-gdoc-scanned),
score **96** (חברה 100 · תאריך 95 · מס׳ מסמך 94 · סכום 91 · סוג 100; certainty mean 57 over 9,386
rows), console 302 to SSO as always. **Thumbnails (Decision 10, closed on the server too):** 47,401
index rows in `INDOX…/automations/thumbnails` — the rows whose files never shipped — deleted from
`storage.objects` (0 left) and `drive_files`, 7,904 documents' `THUMBNAIL` set to null, the id list
kept in `data/_registry_backup/`; 18,700 storage objects remain, of which 1,986 are OTHER dangling
rows without a drive row (pre-existing, not thumbnails, untouched — the owner's call whether to sweep
them). No file on disk was touched; the host was not touched.

### 7.8 The drive feedback, proven twice — and the balance-sheet rule it exposed
`e2e-drv-1808` (one file into drive-bs, one into drive-whatsapp-bot, the feedback block now in the
table the engine reads): both delivered in 1 s, both COMPLETED (5.3 / 6.1 min); the whatsapp invoice
moved to `INDOX/drive-whatsapp-bot/synced` with `sync_feedback_outcome = success` — **the drive move
works**. The balance sheet moved to `INDOX/drive-bs/failed` with `outcome = failure` although its
document was COMPLETED with base, per-type and lines complete and a company found — the feedback's
success rule demanded a `DOC_ID`, which an aging report never carries; the same rule had filed the
morning's gmail-bs messages under `FAILED_BS`. Fixed in `indoxV2ActionsGlobal01 · __feedbackOutcome`
(type-aware: the document id is required only where the type carries one), pushed to the laptop and to
hacohen-prod. `e2e-bs-1819` after the fix: delivered in 3 s, COMPLETED in 5.4 min, `outcome = success`,
the file in `INDOX/drive-bs/synced`. What remains in the laptop's `to_sync` folders (5 in drive-bs, 4 in
whatsapp-bot) are files of earlier runs whose documents completed before those two pipes had a
feedback channel — nothing will move them now that their documents are settled; they are test
leftovers, not a defect. The laptop ends the day with every switch on and the ageing window back at 6.
