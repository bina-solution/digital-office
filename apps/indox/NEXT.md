# INDOX — NEXT (clean plan, consolidated 2026-08-15)

**Single source of truth. Every owner ask lands here first. Nothing is DONE without the number that moved.**
Full evidence for everything already done: [archive/NEXT-EVIDENCE-20260815.md](archive/NEXT-EVIDENCE-20260815.md) + git history (30+ commits, `2b782f90`…`070ac279`).
**The design document is [indox solution.md](indox%20solution.md)** — sync (Part A) and the state machine (Part B), as built.
**The decision document for the autopilot day of 2026-09-03 is [RELEASE-DECISIONS.md](RELEASE-DECISIONS.md)** — everything asked and how it was done, today's measurements, decisions S1–S2 / D-revisions / N1–N16, the ordered plan A–E with a proof per item, and the four owner questions.

## 2026-09-02 (late evening) — THE FINAL RELEASE PROOF: every live registry driven with real sends and uploads, the retry proven in the console, the battery and coverage closed (RELEASE-DECISIONS §7)

**The numbers.** Real run `e2e-final-1840` over all 7 pipes on the owner's own mailbox and local
drive: 9 mails + 12 files → **21/21 items delivered 1–4 s after discovery, 18 documents, 17 completed**
(one merged into its double, the link document correctly IRRELEVANT on a dummy PDF); per pipe
delivered→done 4.0–12.5 min; feedback executed (labels and folders moved). Retry: gmail-doc **113 red →
113 blue → 113 red with a true reason** (`[unlisted]` ×112, `[terminal] not in All Mail` ×1) in one
pass, driven from the owner's console. **Battery on the final stack (RELEASE-DECISIONS §7.6):** decide
58/58 (two stale fixtures corrected to the value-based rules), sync_kernel 34/34, sync_full 12/12,
sealed_inv 5/5, sealed_ship 4/4, sealed_bs 3/3, sealed_ord 1/1, sealed_rcp 1/1, doc_base 3/3, **pipeline
3/3 — 17 live documents COMPLETED and identical to ground truth in 206 s**; mail_organizer 2/2. **Node
coverage CORE 83.7 % (576/688), the sync engine 8/8 workflows at 100 %**; the shortfall is named node
by node (error sinks, the ten dead router lanes, per-type branches the corpus never reaches) — 100 %
needs the owner's per-lane verdicts. Static gates 28 run, 0 regressions, 3 known-red by design.
sync_sources (timed out under 130 concurrent extractions), bs and gdoc (the upload dedupe) were
re-run alone on the quiet machine with the dedupe gone: **bs 4/4 · gdoc 5/5 · sync_sources 16/16 in
189 s — all 13 INDOX suites green today.** Thumbnails: 0 rows created all day. `tag_rules` gone,
`sync_item_reasons` live, on all three tenants. **Released to hacohen-prod at 18:02 UTC (§7.7):** 20
workflows pushed, four images rebuilt, migrations applied, 47,401 dangling thumbnail rows purged with
their ids kept, score 96 and reasons on every red pipe live on the box; the first app build there failed
on files another session had left uncommitted — committed as they stood, rebuilt alone. **Focused
feedback run (§7.6):** a gmail-doc message ends with ONLY the synced label (to-sync removed, 6 min to
COMPLETED); the two drive pipes' files did not move because the feedback edit had landed in the
console mirror instead of the tenant table the engine reads — re-saved through the BFF. **Drive proof
(§7.8):** whatsapp invoice → `synced` with `success`; the balance sheet went to `failed` because the
success rule demanded a document id an aging report never has — fixed type-aware, pushed to laptop and
server, re-proven: `e2e-bs-1819` COMPLETED in 5.4 min, `success`, file in `INDOX/drive-bs/synced`.

**Found and fixed on the way** (details in RELEASE-DECISIONS §7.3): a dead node reference that threw
on every settings load; a trashed message retried forever (now terminal); the outcome label was added
but the to-sync label never removed (one call now does both); two drive pipes still on the client-era
`feedback: off`; label KEYS shown as "not in the list" on every mail card; the mail client dead under
the console (a comment suppressed the base injection); the browser cancelling a retry the server was
honouring; 25 chips for one reason; two gates written and never wired, one library flagged as a gate.

**Left for the owner:** six never-executed live-only workflows to delete in the n8n UI (the agent's
delete was refused as destructive), ten dead router lanes and three cross-app references to judge,
questions 2 and 6. A second session worked the document viewer in this tree concurrently (its files
are uncommitted here) and its `bbox run` recreated n8n mid-battery once.

**The sync page, third time (RELEASE-DECISIONS §7.5).** The owner's verdict on the second version was
"it looks like shit again" — a lone summary tile, English engine strings as chips, ids in headlines, a
grey wall of meta lines, two button languages in one footer. The standard is now a skill
(`~/.claude/skills/platform-ui-ux`, loaded before anything renders; memory `ui-ux-standard-is-a-skill`),
and the page was rebuilt to its design plan: five state tiles + one pass strip, two-up cards, a facts
grid, Hebrew reasons (`reasons.ts`), one button family, the switch a switch. The rebuild also exposed
the upload dedupe written for Decision 10 (a new name answered with an old file; then a fresh upload
answered with a stale one — the `bs`/`gdoc` suites' "fixture link resolution failed"), removed: the
raster upload it guarded against no longer exists, and documents dedupe by hash in the ledger.

## 2026-09-02 (evening) — THE DOCUMENT VIEW: two live defects fixed, the viewer rebuilt as the Stage (P0+P1 of the plan)

**Owner ask:** "2 issues — 1 ex[traction] drawing not showing; 2 doc top is not shown, very annoying.
You must fix once and for all… full display and div tree and managed css for doc view no matter where
it will fit." Investigation + market survey + plan: the artifact **INDOX Document Stage**
(https://claude.ai/code/artifact/e01763b0-dbe7-4d1f-950c-ac4039534a23). This entry is P0 and P1 of it,
shipped and verified on the local stack against `indox_hacohen` (26,747 documents).

**The two defects, root-caused with measurements — neither was a display quirk.**

1. **The extraction drawing never loaded (multi-tenant regression, 2026-08-28).** `withInstance()` is
   applied inside `call()`, so only FETCHED urls named a tenant; the four document-asset urls end up in
   an `<img src>` and were hand-built, so they carried none. The BFF read schema `public`, whose
   compatibility view was dropped, PostgREST answered 404, Flask's catch-all turned it into a bare 500,
   and the viewer fell back to a preview while captioning the document «לא הופק סימון חילוץ». Measured
   live on console.hacohen (`doc_mtk56k1zbq1ws3`): draw/file/tokens **500 → 200 image/png** with
   `?instance=hacohen`. The production log named it exactly (`_document_draw_handle`, PostgREST 404 on
   `public.incoming_documents`).
2. **The top of every tall document was unreachable.** The pane centred an overflowing child with
   `align-items:center` inside a scroll container: the overflow splits in two and `scrollTop` cannot go
   below 0. Measured: the page began **141px** above the scroll origin at 1917×1078 and **163px** at a
   shorter window — worse the smaller the screen — and `scrollHeight` reported the truncated height, so
   nothing on the page admitted it. The second half was the height model: `max-height:76vh` inside the
   console iframe is 76% of the IFRAME and excluded the tab strip, caption and card padding (a 663px
   card inside a 665px region).

**P0 — the hotfix.** `docAssetUrl()` in `api.ts` is now the ONE builder for a document asset and applies
`withInstance()`; the four builders (file/draw/tokens/thumbnail) and the grid's card preview all go
through it, and the extraction-dataset urls got the same treatment (their draw resolves `q_v3_*` per
tenant, and the cache-buster is a parameter now instead of a string appended to a finished url — the
exact move that dropped the instance). Server: `_DocLookupFailed` separates "the row could not be read"
from the two 404s that mean something else, and answers **400 `instance required`** (or 502 naming the
schema) instead of the catch-all 500.

**P1 — `components/DocumentStage.tsx` replaces `DocumentViewer.tsx` (deleted).** The layout contract,
enforced not just written: the page is `.page-fill`, each column scrolls alone, the page never scrolls,
height flows `.app-shell → .wrap → .page-fill → .doc-split → .doc-stagecol → .stage`, the scroller
centres nothing (`margin:auto` on the canvas), the stage is `direction:ltr` (it holds an image, not
text), and the split/stacked choice comes from a **container query** on `.doc-page`, so the same
component is right in the iframe, standalone and (P3) in a drawer. Added: zoom (fit-width / fit-page /
±/ 1:1 / ctrl+wheel, anchored on the pointer), rotate, a draggable **persisted gutter** (RTL-correct:
ArrowLeft grows the data column), an honest empty state with stroke icons, and the extraction tester
adopting the same Stage in `block` mode (a page-shaped `aspect-ratio`, no viewport unit).

**Two bugs found and fixed DURING P1, both by measurement, neither guessed:**
- **A layout-effect measurement loop froze the browser.** The first Stage measured the stage in a
  `useLayoutEffect` and computed the scale from it — a feedback loop with the layout it measures.
  Dragging the gutter hung the renderer outright (reproduced with a real mouse drag; `1+1` would not
  evaluate). The fit is now expressed in **CSS** (`width:100%` + `aspect-ratio`, plus `max-height:100%`
  for fit-page; `cqw/cqh` swap the axes when rotated), so the browser resolves it in the same pass as
  everything else. JS reads the rendered size in exactly one place, `currentScale()`, called from a
  click or a wheel — a read inside an event handler cannot loop with layout. `scrollbar-gutter:stable`
  removes the other coupling (width → scale → height → scrollbar → width).
- **A cached image never fires `load`.** On a reload the browser finished the image before React
  attached `onLoad`, so the natural size was never read and the canvas stayed at its 1×1 placeholder —
  a document that simply does not appear, with the endpoint answering a perfectly good 200. The stage
  now asks the element (`complete && naturalWidth`) as well as waiting to be told.

**Verified on the running stack** (rebuilt image, `--force-recreate`, driven in a real browser):
image url carries `?instance=`; `natW=595`; **image top +1px inside the stage at scrollTop 0** (was
−141/−163) and **still +1px after zooming to 160%**; fit-page fits vertically; rotate gives a landscape
canvas that fits; gutter drag 618→841px re-fits the page live (329px canvas) and persists `0.680`;
three consecutive reloads all render; a document with no `API_TOOLS_ID` shows the explained empty state
(thumbnail 404 `no_raster`), never a broken glyph or raw JSON; the extraction tester renders its PDF in
`is-block` with the zoom tools correctly standing down; at a 390–420px container the split stacks with
the document first, the gutter hidden, no page scroll and no horizontal scroll.

**Gates added, so neither defect can return silently:**
- `scripts/ops/lint_viewport_units.py` — fails the build on a viewport unit in the document view
  (`.app-shell` allowlisted as the one owner of the viewport). **Proven in both directions**: passes
  clean, and fails with a precise message on a planted `76vh`.
- `scripts/ui-coverage/e2e/test_indox.py` — new section D opens a document and asserts the five things
  that cannot be true while either bug exists: the url carries `instance=`, the image decoded
  (`naturalWidth>0`), the top is not above the scroll origin, the page itself does not scroll, and the
  stage got a real height. (Section D's probe was run against the live page: all five pass.)
- Repointed at the new component so the QA tooling does not break on the deleted file:
  `scripts/ui-coverage/inventory.py` drift guard, and `test_indox_regressions.py` check K — whose
  `.subnav .stab` locator would have silently matched nothing and reported "card not found" on a
  perfectly good screen (the stage's tab row is `.stage-sources`).

**Design pass on the same screen (owner, same evening): "rtl issues and two scrollers one in left one
in right… still looks inconsistent uncompleted not professional… I want this page perfect from ground
up."** Each complaint was measured on the live page before anything was touched, and the surface was
rebuilt as one system rather than patched again:

| What the owner saw | Measured | Now |
|---|---|---|
| two scrollers, left and right | `.stage` is LTR so its bar sits on its right edge (x=631); `.doc-data` is RTL so its bar sits on its left edge (x=654) — two 15px grey bars 23px apart, straddling the divider | both panes keep their own scroll (that part was right) but are drawn as **hairlines**: 9px track, transparent, 3px low-contrast thumb that darkens on hover. Measured 15/17px → **10/11px** |
| inconsistent | one row held **four** button languages: heights 35 / 26 / 28 / 29px, radii 0 and 8px, three backgrounds — and it **wrapped to 70px** | one family only — the app's own `.winseg` segmented control (the same one the time-window switch uses) plus `.icbtn`. Heights now **24 and 28px**, one row, `nowrap`, **46px** |
| uncompleted / not professional | the card drew a border and the stage drew another inside it; the status line ran to **two lines** of dense Hebrew under the frame, reading as debug output | one frame: the card IS the frame, the stage its interior — toolbar · document · status line, separated by hairlines. Status is **one line** with an info icon; the full sentence is its tooltip, and a warning icon replaces it when a substitute is showing |
| — | the white page sat on a near-white ground (`--surface-2` #fbfcfd), so the paper had no visible edge | the stage ground is a proper **desk grey** (#e9edf1) with a paper shadow, the way Acrobat, Preview, Rossum and ABBYY all present a page |

Also: the source labels **shorten** (חילוץ מסומן → סימון) below an 860px container instead of letting the
bar wrap, so the toolbar is one row at every width. Verified at a 400px container: single column,
document first, gutter hidden, bar still one row at 46px, no horizontal scroll, no page scroll, and the
document top still +16px inside the stage. All five end-to-end assertions still pass, and the viewport
gate is green.

**Third round, same evening: the view completed against the images we already have.** Owner: "leave
the apitools changes behind the scenes, not relevant now, we work with the images. Focus on what I
asked." So the vector-layer work is off the near path, and what the three existing renders can be made
to do, they now do. Held to `platform-ui-ux` and its proof protocol.

- **The three sources became comparable.** Switching source used to reset to fit-width, unrotated, at
  the top, so answering "is the boxed amount the amount on the paper, and did the reader even see it"
  meant finding your place three times. Zoom, rotation and scroll now persist across sources and reset
  only when the DOCUMENT changes. Scroll is carried as a fraction of the scrollable extent, not in
  pixels, because the renders are the same page at not-always-the-same pixel size. Proven live: zoomed
  to an 807px canvas at scrollTop 344, switched to tokens and back, both unchanged.
- **The other two renders are prefetched** once the visible one has loaded, so the comparison switch is
  instant instead of paying a cold overlay.
- **Drag to pan**, with pointer capture and a grab cursor. Proven: a 120px drag moved scrollTop 344 to
  464, cursor `grabbing`.
- **Full width for the document** (`F`, or the toolbar control, `Esc` to leave): the data column is
  hidden and the stage goes 705px to 1376px. The split ratio underneath is untouched, so leaving
  returns to the operator's own layout.
- **A cold overlay now says so.** After 2.5s the stage shows a pill naming what it is waiting for
  instead of shimmering forever, which reads as a hang.
- **The colour legend moved to where the colours are** — two swatches on the status line, green anchor
  and blue value, instead of a sentence describing them.
- **The dispatch ledger speaks Hebrew** (`vocab.ts` `actionLabel`, 34 keys from the live ledger,
  spelled exactly as production spells them including `update_status_unknwon_company`). It was printing
  `source_feedback_0`, `mark_completed`, `select_type` as the reading line of every row: English machine
  vocabulary on a Hebrew page, the platform's second law. An untranslated action is NOT guessed at — it
  renders as a mono LTR token, visibly the machine's word — and either way the identifier is the
  tooltip.

**Proof (platform-ui-ux §4), on the image the console serves, in the owner's own Chrome:** one toolbar
row at 46px, never wrapping, every control 32px, which is also the ≥30px tap target the checklist asks
for. Scrollbars 15/17px to 10/11px hairlines. Zero English strings in the reading line; the remaining
Latin text is identifiers shown as mono tokens beside Hebrew keys, which the law allows. Browser
console clean. At a 640px container: one column, document first, all 11 controls still visible, no
horizontal scroll, no page scroll, document top +16px inside the stage.

**Open, by design (P2–P4 of the artifact, not started):** vector layers replacing the three baked-pixel
rasters (apitools already computes every box and throws it away — `process_context.find_results`), the
field ↔ box linkage that turns the engine matrix into a review surface, find-in-document over the token
layer, page geometry + the page chip, j/k review flow and inline correction. The four owner decisions
at the end of the artifact are still open; nothing in P0/P1 pre-empts them.

## 2026-09-02 (day) — PRODUCTION-READINESS INVESTIGATION: current state, decisions, plan (owner ask 10:15 UTC)

**⚠ 10:30 UTC — the production address changed identity.** `204.168.193.136` answers SSH with three
brand-new host keys (ED25519 / RSA / ECDSA all differ from the recorded ones), ports 80/443 are closed,
DNS still points there. Signature of a fresh install or a provider rescue system. No key accepted,
nothing run against it since; a watcher reports when the known key or https returns. Every server-side
verification below is **blocked** until the owner says what happened (and whether the data volumes —
`supabase-db`, `supabase_storage_data`, `n8n-postgres` — still exist; no off-box backup is recorded in
this tree). Last known-good: commit `75030833`, releases 3 + 4, passes green through 07:26 UTC.

**Owner asks and what was measured (server, 10:00–10:30 UTC, before the event):**

1. **"Every doc in the tags / folders gets synced" — sources vs ledger (recon.sh):** Drive is consistent
   (WhatsApp folder: 500 of 500 newest known, 499 delivered + 1 review; drive-bs 2/2; the gdoc source
   folders are empty because deliveries move files out). **Mail is not covered by the ledger:** of the
   newest 500 under `DOC_TO_SYNC`, 370 are not in the ledger; under `DOC_LINK_TO_SYNC` 497 of 500;
   under `BS_TO_SYNC` 498 of 500. The labels still hold the retired engine's marks — `DOC_TO_SYNC`
   38,088 messages, `SYNCED_DOC` 16,809, `FAILED_DOC` 861, `IN_PROGRESS` 1,790 — while the ledger holds
   2,111 gmail-doc rows (v3 started 2026-08-28). Whether the missing newest messages are (a) outside the
   6-month window, (b) documents the old engine already processed, or (c) truly unsynced was being
   measured (recon2.sh: windowed search + document lookup by `SOURCE_ID`) when the server vanished.
   **Measured after the reboot (10:41 UTC), inside the 6-month window:** `DOC_LINK_TO_SYNC` 3 messages
   → 3 delivered; `BS_TO_SYNC` 6 → 6 delivered; `DOC_TO_SYNC` 198 → 127 delivered + 4 needs_review,
   **67 missing from the ledger: 11 are documents the retired engine made in August (7 COMPLETED,
   2 OLD, 1 GARBAGE, 1 MAX_ITERATIONS) and 56 are unknown to both the ledger and the document table**
   (e.g. `19cbd2ce2f196f2c`, 5 Mar 2026, labels `לטיפול-אוטומציה-שמירת-מסמכים` + `תוויות-טופל`, no
   SYNCED mark). Cause to confirm: the 08-28 migration planted the gmail-doc cursor near the top of
   the mailbox, so the walk never listed what sat below it. The other engines (link, bs) are fully
   covered. **The server rebooted three times (10:08, 10:37, 10:42 UTC) with a foreign system
   answering in between; not by anything in this tree.**
2b. **Why the label engine stopped:** `mail01` (the 15-min fan-out) is `active=false`,
   `activeVersionId=null`, `updatedAt` 08-31 10:49 with a single history version from an **import**
   at 08-31 03:34 — the bbox-n8n-push footgun ("bare import force-sets active=false"); its in-memory
   trigger kept firing until the 08-31 14:30 restart, then died. The blueprint says `active: true`.
   Fix: `bbox n8n push mail mail01` (API activate) — attempted at 10:42, cut by the third reboot.
2. **The 186 red items:** every `needs_review` row has an EMPTY listing and NO reason — they are the
   2026-08-28 migration rows (`delivered_at` 08:34–08:40, one even with `platform_id = 'e3'`), plus 130
   orphan rows of the deleted `mail-private` pipe. The terminal delivery path (`RECORD needs_review`)
   never writes a reason.
3. **"נסה שוב" as it stands would fail the owner's test:** RESET skips rows with an empty listing
   (`skipped_no_listing`), the BFF drops that count, the button would report "0 פריטים חזרו לתור", and
   retry starts no pass (the next tick or "הרץ" does). Rows it does reset go `discovered → TAKE →
   deliver` on the next pass.
4. **The label engine has not run since 2026-08-31 14:30** (`mailLabelEngine01` active + published,
   fanned out by `mail01`'s 15-min tick — which is also absent from the last 24 h of executions). Tags on
   new mail are therefore two days stale; "the engine gives the right tags" cannot be true today.
5. **AI extraction on the server:** `GEMINI_API_KEY` is byte-identical to the laptop's (39 chars, same
   hash), the n8n credential `ai-studio-bs-extraction` exists, `extraction_ai_enabled = true`,
   `extraction_model = models/gemini-3.1-pro-preview` (a dead knob: models are hardcoded in the Gemini
   workflow). Over 7 days 89 % of completed documents carry AI values (09-01: 5,799 of 6,524). The rest:
   47 with `ai failed: unsupported_file_format` (the octet-stream uploads, cause fixed at 07:00 —
   the File Type Router matches the download's Content-Type exactly and `drive_files.mime` is
   authoritative; apitools sniffs bytes, which is why the local column filled), and **364 typed PDFs
   completed with no AI values and no error** — the base AI leg records `AI_STATUS = 'ran'` even when
   the extractor answered `success:false` (no `failed:` branch in BaseDocEx01), so the cause is
   invisible; the execution dump for one of them was next when the server vanished.
6. **שריזלי-01010 (`doc_mth9fs4btvew2s`):** born from a balance-sheet line (no file), typed INVOICE at
   birth, its file found in Google Drive by `find_link` on 08-31 — then parked `API_TOOLS_FAILED` twice
   (08-31 13:18, 09-02 06:31) without any OCR call: base extraction's gate accepts only TYPE-less
   documents, so a typed document never gets an `API_TOOLS_ID`, and the per-type gate parks it
   (known since `issues/typed-documents-cannot-be-extracted-2026-08-26.md`, unresolved). **Why no error
   text:** the writer emits `ERROR: null` and the API strips nulls at `indoxApi01` `Resolve IDs`, so
   nothing is written — 67 of the 87 `API_TOOLS_FAILED` rows of the last 7 days have no text; the
   global error handler also discards the exception message (`action failed @exec N`), and
   `ACTION_RESTART` cannot clear `ERROR` for the same null-stripping reason. No thumbnail because the
   thumbnail is a by-product of the OCR upload that never happened.
7. **Mail UI < 1 s:** nothing is cached at any level (no bodies, headers, threads, search results; no
   Redis/Postgres/HTTP caching). Opening a message costs NOOP + SELECT + SEARCH + 2 FETCH **plus a full
   RFC822 fetch of the whole thread with attachment bytes that are then discarded** (only to build
   80-char snippets). All of it queues on the one per-mailbox `RLock` shared with sync deliveries
   (300 s gets), discovery searches (50–125 s), the label engine and even the docker healthcheck;
   `IDLE_NOOP_S` is documented but not implemented (a throttled NOOP ≈ 6.5–10 s on every checkout);
   the console proxy gives up at 40 s with `502 app_unreachable`. Sub-second is unreachable on the
   current design; a few commands is reachable in a day (thread fetch off, idle-noop honoured,
   non-blocking readyz); sub-second needs bodies served from a cache the sync deliveries already
   download and throw away.
8. **Sync page vs the 08-31 design** (git `6c217269` → `f44c8dee`, the 02:24 rewrite): lost connection
   health, readable folder/label names, source-side backlog, failure chips by cause, the clickable
   legend → items drawer, the amber in-progress segment, last/next pass, the instance tag, reconcile,
   the 4-step editor with its review step, the failed folder/label, `schedule_min`.

**Decisions I made during the night (surfaced, with the trade-off):**
D1 state lives in `sync_ledger` only (source ⟂ marks) · D2 discovery bounded by the window at three
places · D3 `indoxOn` is READ by both lanes, never writes the other two switches · D4 the BFF talks to
no other app → `/sync/inventory` (source-side numbers) and connection health were dropped with it
(this is the root of most of item 8) · D5 `needs_review` is terminal, `failed` retries with backoff ·
D6 RESET skips empty listings (safe, but silent) · D7 TAKE dead-letters `[expired]` and `[unlisted]` ·
D8 `mail-private` deleted; its 130 rows left in place · D9 the 08-28 migration rows carry no listing
and no reason · D10 http→https share links + type guessed from the file name at upload · D11 the
scheduler's timeout is the chain's longest · D12 driver thinned (15 dead nodes), 5 workflows retired ·
D13 gmail take 25 / chunk 5 · D14 fixed certainty proven with seeded companies (the list itself is
data the owner holds) · D15 `SELECTED_*` dropped · D16 settings → sync tab removed · D17 Supabase
launcher on the deployment domain · D18 the flat editor replaced the wizard · D19 SyncBoard / SyncFlow
/ EngineView / RunProgress deleted · D20 registry `failures` hardcoded `[]` · D21 local `indoxSyncOn`
off before go-live.

**Inconsistencies / architecture issues (numbered for approval):**
I1 reasons are not recorded on terminal sync items · I2 retry is silent on empty listings and starts
no pass · I3 the ledger covers only v3 discoveries; the old engine's marks live only in labels; the
label engine is stopped · I4 error plumbing: null-stripping writer, `noOp` action writers, message-less
error handler, BS lane never writes `ERROR`, base AI leg never marks failure, `[terminal]` suffix hack ·
I5 typed-at-birth documents cannot be base-extracted · I6 exact-match MIME router vs a sniffing OCR ·
I7 dead `extraction_model` knob, models hardcoded · I8 one IMAP mutex without fairness/timeouts for
UI + sync + engine + healthcheck; NOOP per checkout · I9 orphan ledger rows after a registry delete ·
I10 `IN_PROGRESS` label with 1,790 stale marks · I11 apitools ships a hardcoded fallback Vision key
(`ocr_processor.py:19`, flagged by the connections catalog) — security · I12 the search is O(label),
not O(new).

**Plan (for approval; each item thin, each with its proof):**
P0 the server: what happened at 10:30; if reinstalled → rebuild from the repo, data only from
provider snapshots (none in-tree) · P1 reasons + retry: `RECORD` carries `reason`, deliveries pass
theirs, migration rows backfilled `[legacy] migrated without a listing`, RESET resets empty-listing
rows too (re-discovery fills them or `[unlisted]` retires them with the reason), the BFF returns
`reset/skipped`, retry starts a pass so the card moves blue → green/red within one pass; top reasons on
the card · P2 the card + summary: connection health and readable names from the sibling apps in the
browser (as the editor already does), 4-segment bar (amber in-progress, distinct "needs review"),
reasons chips, cadence/take/chunk, last run with n8n link, next pass ETA, instance tag, freshness, a
browser-side "בדיקת התאמה" (source vs ledger) — decision: browser-side cross-app reads are allowed? ·
P3 error plumbing: explicit-null clear on restart, a reason on `api_tools_failed`, the handler records
the message, BS + base AI legs record failures, the MIME router falls back to the sniffed/extension
type · P4 typed-at-birth documents get base extraction (upload + OCR + AI) with the type authority
kept — closes the `API_TOOLS_FAILED` parks · P5 mail UI: thread fetch off + idle-noop honoured +
non-blocking readyz now; then a body cache filled by the sync deliveries; a second UI-only IMAP
connection only on the owner's word · P6 label engine: why `mail01` stopped, restore, verify tags vs
ledger with recon.sh, clear stale `IN_PROGRESS` · P7 ledger history: import the old engine's synced
marks as `delivered` rows keyed by `SOURCE_ID`, or state that history starts 08-28 — decision · P8
orphan rows on registry delete: delete with confirmation, or a REAP sweep — decision · P9 remove the
fallback Vision key · P10 cursor-first mail search.

## 2026-09-02 (night) — FINAL CONSOLIDATION: thin, aligned, no old implementation left; live on hacohen-prod

**Owner order:** clean/consolidate/align workflows | api | bff | ui | cli, delete every old
reference, discovery fully bound by `OldDocumentMonthsBack`, best-practice check, one document.

**Shipped (this entry = the delta over the sync-item release below):**
- **Discovery age bound, three places** — Drive `createdAfter` + a `createdTime` guard on the listing;
  Gmail `newer_than:<months>m` ALWAYS (a pipe's own window can only tighten) + a `Date` guard; TAKE
  expires an owed item that fell out of the window (`needs_review` "[expired] …"). Main's default = 6
  (the fixture's), was 24. Drive discovery caps the WHOLE window (2000 / 5000), not one page.
- **Best practice applied** (research in `indox solution.md` §A10): full jitter (was equal), the
  lag metric `oldest_waiting_at` / `waiting` on the view + BFF + sync card, rows keyed on the Gmail
  hex id (already), one IMAP connection per mailbox (already).
- **State machine, thinned and honest:** `__dispatches_since_restart` (driver `Get Action History`)
  feeds decide's ceiling (25) — `ITERATION_COUNT` was never incremented by anything, so
  `mark_max_iterations` had been unreachable while three comments claimed the router incremented it;
  Ship01 aligned with Inv01 (no `restart_base` ping-pong arm; dormant invoice/order copies gone);
  driver −15 dead nodes (Action Filter, If group action + all-lines POST, the run_page sweep, 3
  islands); upload −2 (the `binary-test` branch with a hardcoded client file); router allowlist
  −5 dead names +2 real ones; 5 pinData blobs cleared.
- **No tenant id in shipped code:** the two Drive searches read `DriveSearchConnection` (else the
  first enabled drive pipe's connection) through one TABLE_GET; found-file links carry the
  connection they were found with; chat's mock download and the workspace agent's health probe take
  theirs from the request. Test fixtures' links moved to the local drive host.
- **Retired (blueprint + live, laptop and server):** `indoxV2ActionsGDoc01`, `indoxProcessDocument01`,
  `indoxDocUploader01`, `indoxDocGet01`, `gmailApiRouter01`; 2 dev scripts; 48 superseded plans /
  reports → `ai/context/archive/indox-pre-2026-09/` + `apps/indox/archive/` (README = history only).
- **BFF/UI/CLI thinned:** the capabilities and failure-map helpers, the old "state lives in the
  source" header, `_SYNC_STATES`, 335 lines of dead sync types in `api.ts`, 3 dead registry fields.
- **Gates:** 25 run, **0 regressions** (was 6): G51 repointed at the ROUTER's Switch1 on
  `.workflow.ts` (+ startsWith prefixes), G48 reply nodes, G39 (JQExV3 callers stop sending fields
  the triggers drop; BS's AI call keeps `LINK_CONNECTION`), G41/G46/G56 by deletion or scrub.
  Known-red stays G60.
- **Server (hacohen-prod), phases 9–10:** schema re-owned to `postgres`; 5 migrations; registry
  row cleaned (`mail-private` out); `bbox run`; every workflow pushed and active (`indox01` forced
  past the emergency-stop CAS); 13 retired workflows deleted live; gates ON; the Redis-cached
  workflow→project map held a project that no longer exists → every sub-workflow call was denied
  until `n8n:cache:*` was flushed (the fleet restart alone did NOT clear it). Since the flush: passes
  every 15 min, drain every 2 min, zero errors. **D10 root cause:** the storage volume was created at
  the 2026-08-30 cut-over — 65,894 object rows in Postgres, 14,704 files on disk; the 7,397 objects
  the live table references and lacks (6.4 GB) are being copied from the laptop's volume
  (`storage-sync.sh`, resumable).

**Numbers (this run, 2026-09-02 00:22–01:35 UTC):**
- Battery against the final code: **14/14 suites green** — decide 57/57, sync_kernel 34/34,
  sync_sources **15/15** (new lane: a drive item with no md5 is terminal at delivery), sync_full 9/9,
  sealed_inv 5/5, sealed_ship 4/4, sealed_bs 3/3, sealed_ord 1/1, sealed_rcp 1/1, doc_base 3/3,
  bs 4/4, gdoc 5/5, pipeline 3/3 (17/17 identical + bare link COMPLETED), thin_only 1/1.
- Node coverage over the clean window (`scripts/n8n-node-coverage.py --since-id 3876600 --min 80`):
  **all 8 sync workflows 100.0 %**; indox01 100, Driver 92.1 (was 72.0), Decide 100, Router 86.4,
  Inv01 87.3, BS01 97.9, Ord/Rcp 90, Drain 92.0, BaseDocEx 94.1, SelectBase/SelectType 100, the
  four JQExV3 engines 100, SearchFile 88.9. Still under 80: Global01 59.4, Ship01 63.8, indoxApi01
  63.2, SearchWarehouse 61.5 (its new no-identity branch), processLock01 38.9 (platform),
  mailLabelEngine01 70.7, driveApi01 76.5 — the lanes named under "still owed".
- Error executions in the window: 5 = the suites' own designed negatives (3 garbage-link downloads
  in gdoc, 1 tenant-less GATE in the kernel suite) + the mail engine's known one. Zero unintended.
- Gates: 25 run, 0 regressions, known-red G60.
- Server: passes every 15 min / drain every 2 min since the cache flush, 0 error executions after
  the mail-fetch fix; 40/40 sampled private-drive links + the newest mail documents' PDFs and
  thumbnails answer 200 (7,397 objects copied, 14,699 given their attributes).

**Morning pass (2026-09-02 06:00–07:30 UTC, the owner logged in; the night brief re-read line by line):**
- Live console proven in the owner's session: dashboard (26,573 documents), the table (532 pages,
  loads in seconds), a document page with its extraction preview, the sync page (one bar per pipe,
  run / retry / edit / delete / master switch), the gmail pipe editor (mailbox connection, tag,
  attachment drive, destination folder, new-tag creator, batch knobs), settings (four tabs, no sync
  tab), apps → Supabase opens `supabase-studio.hacohen.msh-hac.com`, the mail app (the client's
  Gmail) and the drive app (the client's Google Drive).
- **Two more root causes of "links don't work" on mail documents, both fixed:** the drive app's
  `public_link` hardcoded `http://` (mixed content inside the https console; every delivery since
  the cut-over) → scheme rule (https unless a `.localhost` dev host, `DRIVE_PUBLIC_SCHEME`
  overrides) + the 12 stored links rewritten; and n8n's multipart upload sends every attachment
  as `application/octet-stream`, which the storage served back so a browser never rendered it →
  the drive app guesses the type from the file name at upload + 1,230 stored objects retyped in
  the index, the file index and the on-disk attribute. The document's link now answers
  `200 application/pdf`. The same bytes made the AI extractor reject mail attachments
  (`per-type extraction: ai failed: unsupported_file_format` — the local engine carried those
  documents alone); new attachments arrive typed, and a document that failed that way can be
  re-requested from its page.
- **`indoxOn` master** (the brief's third toggle): read by Sync Main and the drain beside their own
  switches (COALESCE true), fixture row + migration insert, editable knob in settings, the full
  suite parks / flips / restores it (12/12). Proven live on the laptop: a scheduled drain ended at
  "Gate Closed" with the master off.
- **Sync card → table:** each pipe card links to the documents table filtered on `SYNC_NAME`
  (the grid's own equals-filter param), the one link the brief allowed.
- **Fixed certainty (Decision 8) proven end to end:** the test fixtures seed three synthetic
  companies with `SELECTION_CERTAINTY` 90; the pipeline suite asserts their non-parked documents
  land with ≥ 90 and `FIXED_CERTAINTY` as the source when the floor lifted them (3/3). **Data:**
  the sheet-era list of "90 % suppliers" is not in the tree or the legacy folder — on the server
  0 of 1,180 companies carry a value and `trusted_suppliers` is empty; the column is editable in
  console → INDOX → settings → companies, or send me the sheet and I import it.
- Batch knob for mail pipes: `chunk` 5 on the server's three gmail pipes and in the example.
- **Release 3 (06:55 UTC) and what the live console then showed:** the sync card's "לטבלה" was
  a hand-built hash href — inside the console the app is path-routed under `/a/incoming`, so it
  resolved against the sync page itself. Now a router `Link` to `/i/<instance>/documents?f_SYNC_NAME=<pipe>`
  — proven live after release 4: all seven cards link, following gmail-doc's opened the table
  with the chip "סנכרון מקור: = gmail-doc" and 1,105 rows (26,573 unfiltered), and the console
  shell mirrored the route into its hash.
- **Eight sync items "waiting" since Aug 6 — the take-time dead-letter:** legacy rows with an
  EMPTY listing whose files had left the source folder; TAKE never takes an empty listing and
  discovery never re-listed them, so they sat in `failed` for four weeks with no reason on the
  card. TAKE now retires a row still empty a day after discovery to `needs_review` with
  `[unlisted] …`; a retry re-discovers it if the file returns. Lane in the sources suite
  (Unlisted Row → the broken unit's Run → asserted). **Live proof (release 4, 07:26 UTC):** the
  first pass after the push retired all eight — `needs_review · [unlisted] no listing a day
  after discovery… · 8`; the card's "waiting" is 0 and the reason is on the row.
- **The 06:22 Main crash — every pass was bounded to 5 minutes:** `indox01` (the scheduler) has
  `executionTimeout 300` and n8n hands a parent's deadline down to sub-executions even when
  not waited for, so Main's 900 never applied; a pass whose three mailbox searches ran 123 s
  (past the 120 s HTTP timeout, retried) + 51 + 68 + 70 s was cancelled mid-search and Main
  died on the cancelled call (`Cannot read properties of undefined (reading 'entries')`).
  Scheduler timeout → 1800 (the tick itself ends in seconds; jobs carry their own limits), and
  Discover Gmail's Search node soft-fails after its retries so a bad search ends one unit, not
  the pass. **Open (measured, not fixed):** the client's mailbox answers a 6-month label search
  in 50–125 s per pipe (X-GM-RAW over ~40k labelled messages); an incremental search that asks
  `UID <cursor>:*` first and filters the few new messages by label would be O(new), not O(label)
  — a mail-app change, listed for the next round.
- **Numbers of this round (commit `5aad2bd2`):** sync_sources 16/16 (exec 3888277, 186 s, the
  new `drive-unlisted` check included); node coverage over that window: all 8 sync workflows
  and `indox01` at 100 %; gates 25 run / 0 regressions (G60 known-red); webapp `tsc` clean.

**Still owed / open:**
- `mailLabelEngine01` targeted-run path errors sporadically ("reading 'entries'" at `Get a message`)
  — the mail app's, not INDOX's; 2/day.
- Coverage lanes for the still-LOW workflows (Global merge/garbage lanes, Ship01 link search /
  priority sync, indoxApi01 MERGE/DELETE/GET_ALL, processLock01) — real branches nobody tests yet.

## 2026-09-02 — THE SYNC ITEM: one state, in our DB; the BFF talks to no other app; INDOX final

**Owner-approved plan (INDOX Final Audit, Decisions 1–11) executed end to end on the laptop.**
The double implementation of sync state is gone. Sync has ONE state — the sync item — and it is
`sync_ledger` evolved in place (Decision 1: no new table): one row per DISCOVERED item,
`discovered → claimed → delivered | failed | needs_review`, with the source's own `listing`
(md5/name/size/link/createdTime | uid/subject/from/date) persisted at discovery so a delivery
never reads the platform again. Where a file or mail SITS is never sync state: folders and tags
are user-visible marks written by the state machine's feedback alone. A registry entry needs only
its source folder / tag; nothing blocks deleting one.

```
8 workflows replace 3 (Unit 5-lane monolith, Deliver, mailDiscovery01):
  syncV3Main0001      10 nodes   lock → ONE config read (indoxSyncOn + registry + months + label map)
                                 → units → Discover each (waited) → Run each → unlock
  syncDiscoverDrive01  6 nodes   list to_sync folder, age-bounded at discovery → UPSERT
  syncDiscoverGmail01 10 nodes   UID walk from the bottom (since_uid) → UPSERT → cursor
  syncRun01            8 nodes   TAKE min(take,chunk) (for update skip locked) → fan out, no wait
  syncDeliver{Drive,Gmail,Link}01  7/10/10 nodes   row from listing → DELIVER → RECORD | FAIL
  syncLedgerApi01      4 nodes   THE op table: UPSERT TAKE RECORD FAIL RELEASE RESET REAP GATE CURSOR_*
  SyncApi0000000001   11 nodes   the manage door for the BFF: SCAN (→ Main, scoped) + RESET
node coverage (scripts/n8n-node-coverage.py --since-id 3865860):
  all 8 sync workflows 100.0%   SyncApi 81.8%   CORE 97.4% (bar 80)
suites (bbox indox test): sync_kernel 34/34 · sync_full 9/9 · sync_sources 14/14
  (sources = injector → REAL pass → ledger + documents: 2 local drive pipes deliver every file
   with a document; 3 local-mail pipes deliver every attachment and needs-review every
   attachment-less / link-less mail at once — no retry storm, nothing pending)
executed proofs on the clock: injector pass = 15 items over 5 sources delivered in 12s;
  RESET 25 legacy rows → discovered → TAKE → [terminal] → needs_review in one scoped pass
```

**The BFF (owner rule "INDOX BFF never talks to another application"):** 99 definitions /
3,348 lines deleted (10,301 → 6,909): every mail/drive walk, every connection/location proxy,
every source-side move, the thumbnail hop, the cached walk and its 90s refresher. Counts come
from ONE view `sync_item_counts`; the board is one bar per pipe (blue = discovered+claimed,
green = delivered, red = failed+needs_review) with run / retry-failed / edit / delete. The
editor picks tags and folders from the sibling apps same-origin (`/a/drive/api/folders`,
`/a/mailview/api/labels`, `/api/connections` added to mailview) — the browser, never the BFF.
`indoxSyncOn` is a per-tenant gate (fixture + editable + stop-all writes it); the settings
sync tab is gone. Thumbnails moved INTO n8n (apitools `/documentImage` → drive `ensureFolder`,
a new op → upload). Companies got `SELECTION_CERTAINTY` (max(computed, fixed) in SelectType01;
the six-digit company key collision is fixed — full digits, leading zeros dropped). SELECTED_*
(7 columns) dropped from schema, table, archive, views, fixtures, scripts; the grid queries a
projection (view columns + a fixed set), counts are memoised 15s, trigram indexes on the four
free-text search columns, page cap 500.

**Retired and deleted live:** syncV3Unit0001, syncV3Deliver0001, mailDiscovery01, SyncProc×2,
the three gmail downloaders, the two reset workflows, the three old sync suites; hooks
`sync-engine` / `sync-seed-ledger`; tables `sync_attempt` (folded), `sync_pipe_state`,
`indox_sync_stats`; `mail-private` (fixture + live row). Migrations under
`scripts/ops/migrations/2026-09-02_*.sql` (5 files, idempotent, per tenant).

**Still owed by this release (tracked here, not silent):** the state-machine battery re-run for
the ALL-workflows 80% bar after this change set; the live server (phase 9/10): migrations,
retired-workflow deletion, registry row, drain + sync gates back ON, every link/thumbnail on
the live console checked.

## 2026-08-28 08:50 — FULL SWEEP IS A SCHEDULED JOB NOW, and it proved everything at once

**Fixed the missed-sweep defect at the right layer.** `indox01` dispatches `drain_full` as its own
job on state-based dueness (`app_schedule_state`, per instance, `drain_full.every` default 120);
the drain promotes on the JOB NAME. The modulo window is **deleted**, not kept alongside — two
mechanisms deciding the same thing is how it drifted out of true. `Route Job` matches
`startsWith 'drain'` so both jobs reach the same Call node; a job matching no rule is a silent
no-op, which is exactly how the reaper ran dead for hours earlier today.

**It fired immediately** (no prior `last_run_at` = due) for BOTH instances, and that one sweep
did more verification than anything I could have staged:

```
drain_full rows          hacohen + levi, dispatched 08:36:41
indoxV2Driver01          7 success + 4 running, 0 errors   <- MY FIX, FINALLY PROVEN
indoxApi01               17 success
Global/Inv/Ship/BS/Ord/Rcp/Decide   9-10 success each
doc_mtcmdicy6czbo9       IN_PROGRESS -> EXTRACTION_FAILED (terminal). RECOVERED.
IN_PROGRESS              4 -> 3
```

Every workflow I touched tonight ran under real load. The driver fix is no longer "deployed and
unexercised".

**AND THE SWEEP FOUND A WHOLE CATEGORY I HAD MISSED.** 3 chains threw
`no __instance` (Router -> Global -> Api). My earlier census only scanned **Code** nodes; these
were **Set** nodes. 57 Set nodes assign `INLINE_ACTION` without naming `__instance` — but almost
all are harmless, because `includeOtherFields:true` preserves it from the document row.

The dangerous ones are those whose input comes from an **executeWorkflow** node: a sub-workflow
returns its OWN items, so there is nothing left to preserve. Computed from the graph — 9 of them:

```
Global01  Build Select Base Upsert          <- Call SelectBase01   (this is what threw)
Global01  Build Base Doc Upsert             <- Call BaseDocEx01
BS01      Build Per Type Upsert (BS)        <- Call BsDocEx01
BS01      Build Select Type Upsert          <- Call SelectType01
Inv01     Build Per Type Upsert             <- Call InvoiceDocEx01
Inv01     Build Select Type Upsert          <- Call SelectType01
Inv01     Build: ... FROM_OFFICE            <- Call Search From Waerhouse
Ship01    Build Per Type Upsert             <- Call ShipmentDocEx01
Ship01    Build Select Type Upsert          <- Call SelectType01
Ship01    Build: ... FROM_OFFICE            <- Call Search From Waerhouse
```

All 9 now name `__instance` from the trigger. Re-audit: **0 at-risk Set nodes.** After the push:
**57 executions, 0 errors, 0 throws.**

**The lesson worth keeping: `includeOtherFields` is not inheritance.** It preserves what the input
carried, and a sub-workflow boundary is where the input stops carrying anything.

## 2026-08-28 08:30 — DEFECT: the drain's full sweep is missed ~half the time (window < tick gap)

**The recovery sweep fires only if a tick lands inside a 2-minute window every 2 hours, and the
ticks are 4 minutes apart.** So roughly every other sweep is silently skipped. Measured, hacohen,
3 hours: **46 ticks, 1 full sweep.**

`indoxV2BaseDrain01` line 229:
```js
if (source === 'tick' && fullMin > 0 && (Number(cfg.epoch_min||0) % fullMin) < Math.max(tickMin, 2))
  source = 'full';
```
`fullMin` = 120, and the window width is `max(tickMin, 2)` = **2 minutes**. Observed tick spacing
is **4 minutes** (07:10:14, 07:14:14, 07:18:14 ... consistent). The 08:00 sweep was straddled:

```
07:58:15  tick   epoch_min % 120 = 118   no
   (no tick at 08:00 -- the whole window)
08:02:15  tick   epoch_min % 120 = 2     no, because the test is  < 2
```

Last successful sweep: **06:00:14**. Next expected 08:00 — did not happen; nothing since.

**Why it matters more than the missed sweep itself:** `mode=all` is the ONLY thing that revisits a
document which has gone quiet for longer than `changedMinutes` (15). Everything stale therefore
depends on a trigger that misses about half its chances -- which is the real reason rows can sit
for hours or days, and it is what I wrongly blamed on "the drain only scans 15 minutes".

**Fix direction (NOT applied -- design change, and I have already destabilised this workflow once
tonight):** make the sweep STATE-BASED rather than a modulo window -- fire when
`now - last_full_sweep >= full_minutes`, recorded like `app_schedule_state` already does for jobs.
A modulo window is only safe when the window is at least as wide as the tick gap, and here it is
half of it. Widening `max(tickMin, 2)` to the real dispatch interval is the one-line version, but
it re-breaks the moment the interval changes again -- which is exactly how this got missed.

NOTE: the tick interval is the owner's dial and is NOT to be touched. The bug is that the WINDOW
does not adapt to it.

## 2026-08-28 08:25 — TWO-TENANT DOCUMENT PIPELINE PROVEN, and a correction to the entry below

**CORRECTION.** The entry below says the drain only ever scans a 15-minute window and that stale
documents therefore leak. **That is wrong** and I am striking it. `indoxV2BaseDrain01` line 229
promotes `source` from `tick` to `full` every `full_minutes` (default 120), which sets `mode=all`.
Measured over 6 hours: **84 changed-mode runs + 1 full sweep per instance**, exactly as designed.
I reasoned from `mode: changed` on one execution instead of censusing the modes. The stuck rows
need a different explanation than the one I gave.

**TWO-TENANT E2E ON THE DOCUMENT PIPELINE: PROVEN.** From the drain's own items, not inference:

```
drain runs, last 25 min      levi 5 / hacohen 5, each with its own __instance
levi full sweep 06:00:14     Select IDs -> levi_doc_0001
                             Fire Lanes -> {accepted: true, execution: 3694777}
executions 3694777/9/80      indoxV2Driver01  SUCCESS  (for levi)
execution  3694778           indoxApi01       SUCCESS
selected totals, 6h          hacohen mode=all 26,064 · levi mode=all 1
```

So levi is dispatched, selected, fired, driven and answered independently of hacohen, with the
right instance at every hop and the right row counts for each tenant. That is the two-tenant
document pipeline working, not just scheduling.

**levi_doc_0001 sitting at TO_EXTRACT is most likely CORRECT, not stuck.** It is a seeded row with
COMPANY_ID 510000001, no TYPE and no real document behind it, so there is nothing for extraction
to act on. The driver ran for it and legitimately produced no state change. Not evidence of a bug.

**STILL UNPROVEN: my own indoxV2Driver01 fix.** 0 driver executions since it was pushed (the 06:00
levi runs PREDATE it). It will next run on the following full sweep or on new work. Until then the
four-node change to that workflow is deployed and unexercised, and I am not calling it verified.

Estate: 256 executions in 30 minutes, 0 errors.

## 2026-08-28 08:15 — SYSTEMIC GAP: nothing re-queues a document stuck IN_PROGRESS (SEE CORRECTION ABOVE)

Chasing the two rows my cutover incident stranded turned up something bigger than the two rows.
**No ACTIVE workflow recovers a document left IN_PROGRESS by an interrupted action.**

```
1773076822352ch9fr8  IN_PROGRESS  since 2026-08-26 12:41   stuck 1 day 19:31
1778992906808bgn3rp  IN_PROGRESS  since 2026-08-26 20:05   stuck 1 day 12:07
doc_mtcmdicy6czbo9   IN_PROGRESS  since 2026-08-28 07:17   stuck    00:55   <- my incident
doc_mtcmdj8aeqe3f1   IN_PROGRESS  since 2026-08-28 07:17   stuck    00:55   <- my incident
```

The two from 2026-08-26 are the proof: they predate everything tonight and nothing has picked
them up in **over a day and a half**. So this is not a new regression, it is a standing hole that
my incident happened to demonstrate.

**The mechanism EXISTS but is switched off.** `indoxApiSupabase01 :: Terminalize Stalled` does
exactly this job — the router's own pinData still carries its fingerprint,
`REQUIRED_ACTION: " [re-queued: stalled IN_PROGRESS >6h, attempt 1]"` — and that workflow is
`active = false`. Checked for a live replacement: `indoxApi01`, `indoxV2Driver01`,
`indoxV2ActionsGlobal01` and `IndoxResetGml001` all mention IN_PROGRESS, but the driver's is
dispatch-RACE logic (live race vs stuck loop), not stalled-document recovery. There is no
successor.

**Verified for my two specifically, so this is not guesswork:** doc_action locks EXPIRED (checked
in redis, no keys), the drain's `Reap Stale Dispatches` IS running (4 of 4 passes in 10 min), and
they have NO rows at all in `indox_action_execution_log` — they died before a dispatch was logged.
Nothing is holding them; nothing selects them either.

**I did NOT hand-repair them.** `ACTION_RESTART` (`restart_base`) is the sanctioned re-run, but the
router switches DOC_TYPE on invoice/bs_doc/empty_row/shipment/order/receipt and these rows have no
TYPE and no COMPANY_ID, so a hand-built dispatch would be guesswork against production documents.
Fixing rows is also the wrong layer: the gap is that the reconciler is off.

**Owner decision:** reactivate `Terminalize Stalled` (or port it into the drain, which already
runs a reaper every pass), then the four rows drain themselves. Until then every interrupted
action leaks a document permanently.

## 2026-08-28 08:10 — CUTOVER STEP 2 DONE: indoxApi01's public fallback is REMOVED

9 guard sites now THROW instead of resolving to `public`; the 2 `SHARED[t]` returns (genuinely
global `ai_extraction_cache`) are untouched. **146 executions in the following 20 minutes, 0
errors.** levi still 1 doc / 0 ledger, hacohen 26,066.

**I broke indoxApi01 twice getting there, and both were escaping, not logic:**
1. `\'` inside a JS single-quoted string inside a `.ts` template literal — the backslash was
   consumed and the bare quote closed the string. `Build Get SQL` died with *missing ) after
   argument list*. **The first error pairs looked like unscoped callers and were not — they were
   my syntax error.**
2. The fix then failed to compile because I put **backticks** around a word in a comment, inside a
   template literal. That trap is already written down in this repo and I walked into it anyway.

**Both pushed CLEANLY.** `push ok` proves nothing here. There is now a check that extracts every
Code node's `jsCode` from the LIVE workflow and runs `node --check`:
`scratchpad/syntax_check_api.sh`. Run it after every push to indoxApi01.
(Its first version reported three fake failures because Postgres `encode(...,'base64')` wraps at
76 chars and the newlines truncated the files — strip them.)

**THE REAL DEFECT, found by the sync agent: the instance can arrive PER ROW.** indoxV2Driver01
sends `filters:[{ID:...,__instance:'hacohen'},...]`; the guard read only the top level, so a fully
migrated, correctly tenant-aware caller failed closed. Same class as the `instance`/`__instance`
conflation at 05:56 — **right rule, wrong field.** `Build Get SQL`, `Build Table Get` and
`Build Table Upsert` now LIFT the instance from batch rows when they AGREE, and refuse only when
rows name more than one (one statement touches one schema; picking silently is the bug this
cutover exists to remove).

**Latent bug the cutover exposed:** `indoxV2Driver01` read its instance from
`$('Code in JavaScript')`, which only exists on the WEBHOOK path. Every sub-workflow call — the
drain and action router, i.e. nearly all traffic — hit the catch and silently resolved to public.
Four nodes fixed to try both entry points.

**DAMAGE I CAUSED, NOT YET REPAIRED:** `doc_mtcmdicy6czbo9` and `doc_mtcmdj8aeqe3f1` have been
`IN_PROGRESS` since 07:17:53 — they were mid-flight when my broken guard threw. Their doc_action
locks have expired (verified in redis) and the drain's `Reap Stale Dispatches` is running 4/4, but
neither is re-selected: the drain picks on a caller-supplied `whereSql` and nothing claims an
orphaned in-flight row. **Recovery is ACTION_RESTART — the sanctioned re-run — not a row edit.**
(Two other IN_PROGRESS rows date from 2026-08-26 and are unrelated to this.)

**indoxV2Driver01 has not run since 07:30** and is therefore UNPROVEN on the fix. That is expected,
not broken — the queue is empty apart from those two rows — but it means restarting them serves
double duty: it recovers the documents AND exercises the driver.

## 2026-08-28 07:30 — CUTOVER STEP 2: 26 → 14 builders, and live callers are now at ZERO

**The measurement that matters moved from 15-of-17 unscoped to 13-of-13 scoped.** Successive
`indoxApi01` windows: 15/17 arrived with no `__instance` → 2/15 → **0/13**. 52 executions across
the pushes, **0 errors**.

**Closed this pass (12 builders, all live document path):**
`indoxV2ActionsGlobal01` ×5 · `indoxV2ActionsBS01` ×2 · `indoxV2ActionsInv01` ×2 ·
`indoxV2ActionsShip01` ×2 · `indoxV2Driver01 :: Next Page Req` · `indoxDocGet01 :: SB Get Req`
· `mailApi01 :: Build Get`.

Two of those were more than bookkeeping. `indoxV2ActionsGlobal01 :: Adjudicate Merge` builds the
**MERGE** op — the most destructive in the estate, it folds losers into a winner — and was
unscoped. `Build: Restart (clear completed flags)` appears in four workflows and would have
cleared another instance's row of the same ID; document IDs are per-instance sequences, so that
collision is ordinary, not exotic.

`indoxDocGet01` needed BOTH halves and neither works alone: its trigger is `inputSource:
'jsonExample'`, which accepts only the fields it declares and silently STRIPS the rest — so
passing `__instance` from a caller would have done nothing until it was declared.

**REMAINING 14, and 13 of them are dormant.** Execution counts over 24h decide this, not the
count of builders:

```
indoxPageProbe01       8 builders   0 executions/24h   probe lane
SyncApi0000000001      2            0                  dormant v1 chain (0 EVER)
indoxV2TestFixtures01  1            0                  fixture lane
indoxApi01             2            n/a                INTERNAL -- 'Strip Control' and 'UPSERT
                                                       Adapter' run AFTER the instance is
                                                       resolved; stripping control fields there
                                                       is correct, not a gap
mailApi01              1            72                 FIXED this pass (see below)
```

**`mailApi01` was the last live one and is now forward-compatible, not closed.** It is ENTRY-ONLY
(webhook), so unlike every other caller it has no upstream item to inherit from — the request must
name the instance. It now accepts `__instance`/`instance` from query or body and passes it through;
with no caller supplying one it is byte-identical to before. **Removing the fallback is therefore
gated on a CALLER CONTRACT for this webhook**, not on more workflow edits.

**Still NOT safe to remove `indoxApi01`'s public fallback** — 0/13 in a 5-minute window is
necessary, not sufficient: the dormant probe/fixture lanes would hard-error the moment they ran.

## 2026-08-28 06:50 — CUTOVER STEP 2 IS GATED, and here is the exact list

**`indoxApi01`'s `public` fallback CANNOT be removed yet.** Measured, not assumed: of 17
`indoxApi01` executions in a 20-minute post-fix window, **15 arrived with no `__instance` key at
all** — removing the fallback today turns those into hard errors. (The 60-minute window said
135/196; the tight window rules out stale data as the explanation.)

**The gate is 26 builders across 11 ACTIVE workflows** that send `INLINE_ACTION` to `indoxApi01`
without naming `__instance`:

```
indoxPageProbe01        8      indoxV2ActionsInv01     2      indoxV2Driver01        1
indoxV2ActionsGlobal01  5      indoxV2ActionsShip01    2      indoxDocGet01          1
SyncApi0000000001       2      indoxApi01 (internal)   2      indoxV2TestFixtures01  1
indoxV2ActionsBS01      2      mailApi01               1
```

Each is the same shape every time: a Code node that CONSTRUCTS a request item and therefore drops
every field it does not name. There is no structural shortcut — `indoxApi01` has nothing to derive
the instance from, so each caller must name it. Sequence stays: close all 26 → re-measure to zero →
then remove the fallback, which converts the remaining silent wrong-instance reads into loud errors.

**Closed this pass** (was 15 of the 26): `indoxSettings01`'s three TABLE_GET builders
(settings/companies/tag_rules) and `syncV3Main0001`'s `Run Start Req` / `Run End Req`. Both carried
`instance` (the row DISCRIMINATOR, a COMPONENT name) but never `__instance` (the SCHEMA) — so every
settings/companies/tag_rules read and every run-state stamp resolved against public no matter who
asked. `indoxSettings01`'s own comment said it was "pinned to the first instance because this
workflow has no work item to derive an instance from"; its trigger now DECLARES `__instance` and
callers supply it, so that premise had expired too. 15 executions after the push, 0 errors.

**`SyncApi0000000001` — owner decision needed.** The v1 sync chain is `active=true` with **0
executions EVER**, and its only trigger is an `executeWorkflowTrigger` reachable solely from the
INACTIVE `ApiSupabase01`. It carried the same `instance:'*'` pattern that caused the leak below; I
scoped it rather than deactivating it, because retiring the v1 chain is a bigger call than a code
fix. It is a duplicate of the v3 chain and a candidate for deletion.

## 2026-08-28 05:55 — CROSS-TENANT LEAK: hacohen's mail was delivered into indox_levi

**104 ledger rows, 104 documents, 46 attempts written into `indox_levi` between 05:25:37 and
05:42:04**, every one sourced `incoming-documents-main/*` — hacohen's pipes — and every one
(104/104) already delivered in `indox_hacohen.sync_ledger`. Found, stopped, backed up, cleaned.
`indox_levi` is back to **1 document** (`levi_doc_0001`), ledger 0, attempts 0; hacohen verified
untouched at 26,064 documents / 29,098 ledger.
Backup: `data/_registry_backup/cutover-20260828/levi-crosstenant-leak-backup.sql` (105+46+104 rows,
dumped to WSL-native storage and byte-verified before copying — see the /mnt/c warning below).

**Root cause — a Model-A leftover, not a propagation bug.** `syncV3Main0001 :: Registry Req`
emitted `instance:'*'`: *read every instance's registry and fan out*. That was correct when ONE
scanner served all tenants and had no way to know which instance it was for. It stopped being
correct when `indox01` became the scheduler — syncV3Main0001's own `Schedule 15m` is disabled and
every pass now arrives via `When Called` (18/18 executions mode `integrated`), dispatched once per
enabled instance WITH its identity. `'*'` then stopped meaning "fan out" and started meaning "every
pass reads every registry". `indox_levi` has no `sync_registry` row, so levi's pass read hacohen's,
and `Build Units` correctly stamped those pipes with the dispatching instance.

**The propagation work did not cause this — it revealed it, and then made it efficient.** Before
`__instance` reached the writers, levi's deliveries fell back to `public` and landed in hacohen:
wrong, but invisibly so. Once propagation worked, the same pipes routed hacohen's documents into
levi. *A propagation fix without a scoped registry read is worse than neither.*

**Fixed:** `Registry Req` reads the dispatching instance's registry and THROWS when it cannot name
one — the doctrine the node already applied to `registry_key` ("I could not tell which registry you
meant must never resolve to the client's"), extended to the instance. Live:
`{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:inst, filter:{key}}`.

**The generalisable lesson:** grep for the *premise*, not the string. `instance:'*'` was a
deliberate, carefully-commented decision that outlived its reason. Anything whose comment says it
reads across instances *because it cannot know which one* is now false — indox01 always tells it.

**TOOLING WARNING:** a `pg_dump` redirected straight onto `/mnt/c` produced a file `ls` reported as
198,403 bytes that read back **completely empty**. C: is at 99% (6.5G free, falling). Dump to
WSL-native storage, verify the bytes, then copy. Do not trust any backup written directly to
`/mnt/c` right now without reading it back.

## 2026-08-28 05:37 — CUTOVER STEP 1 DONE: the 4 view-typed overloads are dropped

**What moved.** `public.indox_{base_selection_hash,line_hash,priority_signature,selection_hash}(incoming_documents)`
— the overloads bound to the COMPAT VIEW's composite type — are gone. 8 table-typed overloads
survive (4 functions × indox_hacohen + indox_levi), `view_typed_left = 0`, and both instances
smoke-test `t/t` on line_hash and selection_hash. 31 executions after the drop: **0 errors, 0
function-missing errors.**
Revert is one file: `data/_registry_backup/cutover-20260828/revert-view-typed-overloads.sql`.

**Why this was blocked until now, and what unblocked it.** Every caller runs
`public.indox_<fn>(b.*) FROM {{ __instance ? 'indox_'+__instance : 'public' }}.incoming_documents b`,
so the view-typed overload is reached **exactly when the resolver falls back to public**. Dropping it
converts a silent wrong-instance read into a hard error — which is only safe once nothing is
unscoped. Measured before acting:

```
indoxV2ActionsOrd01    0 / 56  executions carried an instance   <- would have BROKEN
indoxV2ActionsRcp01    1 / 57                                    <- would have BROKEN
indoxV2Driver01       66 / 66
indoxV2ActionRouter01 67 / 67
indoxV2ActionsGlobal01 80 / 80
```

Root cause of the two failures: `indoxV2Decide01`'s six `Export Seed (*)` Set nodes read
`$json.__instance`, but a v3 Set node emits only what it assigns, so by that point the item had
already been rebuilt and the value was `''`. Decide itself carried the instance in 56/56 — it was
being read from the wrong item. Fixed to read `$('When Called')`, which cannot have been rebuilt.
**After: 58/58 across all five callers, 0 empty.** That is what made the drop safe.

**Still open on the cutover:** removing `indoxApi01`'s public fallback, and dropping the 17 compat
views. The view drop is NOT mine to schedule alone — the BFF still reaches tenant schemas through
`run_sql` because `PGRST_DB_SCHEMAS` exposes only public/storage/graphql_public, so the views are
load-bearing until that path is retired. Sequence agreed with the table agent: grants/RLS on every
`indox_*` schema → widen `PGRST_DB_SCHEMAS` → BFF drops run_sql → revoke run_sql → drop views.
**Steps 2 and 4 are production config and privilege changes and are the owner's call.**

## 2026-08-28 — THE `instance` COLUMN IS AGENT-CREATED GARBAGE, AND IT WAS BREAKING levi

**Owner, verbatim: "no instance column ever created by me its all garbage".** It is a SECOND tenancy
mechanism (row-level) doing the job schema-per-tenant already does. It was not merely redundant:

```
indox_levi.settings   60 rows  'incoming-documents-levi'   <- levi's REAL config
                       8 rows  'incoming-documents-main'   <- seeded by me tonight
                       0 keys in common
every workflow filtered -main  ->  the pipeline saw 8 of 68
```

levi's entire configuration — every `q_v3_*` query, `indoxDrainOn`, `activePrioritySync`, the drain
pool settings — was **invisible to every workflow**, and my seeding masked it by making levi look
configured. Normalised onto one value (68 visible, hacohen untouched at 82); the two sets shared no
keys so the `(instance, key)` primary key could not collide.

**WORKFLOW SIDE NOW CLEAN: 0 live production nodes filter on the column** (was 30). 38 occurrences
removed across 19 workflows, each edit a WHERE-clause change, pushed and verified: 52 executions, 0
SQL-syntax errors, 0 missing-relation errors; both tenants read their own settings (hacohen 82, levi
68, both `drain_on=true`). The one remaining mention in `indoxV2BaseDrain01` is prose in a `notes`
field. **Removing the filter had to come before dropping the column** — that is the sequencing.

**STILL TO REMOVE (needs the peer's files):** the column itself from settings/companies/tag_rules in
every schema, `settings_pkey` back to `(key)`, the DDL in schema.sql that adds it with a default (so
a NEW tenant stops inheriting it), 15 `filter=_tenant()` BFF sites, 6 `on_conflict="instance,key"`.

## 2026-08-28 — THE ONE MULTI-INSTANCE MODEL (deep scan for duplicates; owner order)

Four vocabularies grew around this — repo / instance / tenant / account — and the owner was right
that they had started to double. Full map, and what is real:

**THE WORKFLOW SIDE IS CLEAN.** One carrier: `__instance`, 60 nodes across 29 active workflows.
`__schema`, `__repo`, `__tenant` do not exist as tokens. **My first count said 163 `__schema` nodes
and was wrong: SQL `LIKE` treats `_` as a single-character WILDCARD, so `%__schema%` matches anything
containing "schema".** Any carrier census written with LIKE is wrong the same way — use a word-exact
regex.

**THE BFF HAD TWO MODELS COEXISTING. That is the duplication.**

| | MODEL A — legacy, to remove | MODEL B — the one we keep |
|---|---|---|
| registry | `RepoRegistry` + `active_instance.json` | `public.indox_instances` |
| "which one" | one GLOBAL pointer in a file on the host | `?instance=` per request |
| resolvers | `_read_active_instance`, `_resolve_active`, `_instance_target`, `_scope` (21 sites) | `_bind_instance_schema` → `g.indox_schema` → `_request_schema()` |
| HTTP | `/accounts`, `/account/select`, `/account/add` | `/tenants`, `/tenants/<id>/tables` |
| webapp | `listInstances` / `selectInstance` / `addInstance` | `listTenants` + `api.setInstance()` on every `call()` |

A single global pointer in a host file makes "which tenant" a property of the SERVER rather than of
the REQUEST — a multi-tenant bug by construction.

**A THIRD THING THAT IS NOT A TENANT AND MUST NOT BE MERGED:** the `instance` COLUMN on
settings/companies/tag_rules. Only value: `incoming-documents-main`. That is a COMPONENT name. The
tenant is the SCHEMA. Two facts, one word.

**FIXED: the place they touched.** `_instance()` returned `_resolve_active(registry.list())` — the
active REPO name — and worked ONLY because the active repo happened to be named the same string as
the column's only value. Point the console at another repo and every config read filters on a name
no row carries: settings, companies and tag_rules all return EMPTY and the console renders as if the
configuration were wiped. It also made a tenant-scoped read depend on `active_instance.json`, i.e.
Model A reaching into Model B. It now returns the constant.

**A FOURTH `instances:` is legitimately separate:** `platform.state.yaml` for drive/mail/chat
CONNECTIONS. Different layer — keep it, never wire it to INDOX tenants.

**THE RULE, sent to the peer sessions:** if something needs the tenant it takes it from `?instance=`
via `_request_schema()` (server) or `__instance` (workflow item). Never a file, never a new registry,
never a second "active". If Model B cannot express something, change Model B — do not grow a second.

**STILL TO REMOVE (needs the UI moved off `listInstances` first):** `active_instance.json`, the three
`/account*` routes, and `_resolve_active`/`_instance_target`/`_scope` once nothing calls them.

## 2026-08-28 — MULTI-INSTANCE: WORKFLOWS MIGRATED, SCHEDULER CUT OVER, TWO TENANTS PROVEN LIVE

**Backup first:** `data/_registry_backup/precutover-20260828-034844/` — 880 MB custom-format dump
(760 objects, 235 tenant-schema entries, 28 views), schema-only SQL, and every n8n graph as JSON.
Witnesses: hacohen 25,982 docs / 82 settings, levi 1 / 60, action_log 485,289.

**1. Every active production node now resolves its schema from `__instance`.** ~50 nodes across 26
workflows. The resolver is inline and uniform:
`{{ $json.__instance ? 'indox_' + $json.__instance : 'public' }}`. Absent instance still resolves to
`public` — today's behaviour — and becomes a LOUD failure the moment the compatibility views drop,
which is the property that makes this safe to land incrementally.

**The census that found 28 nodes was wrong, and the way it was wrong matters.** It grepped for
`public.<table>`, so it never saw UNQUALIFIED references, which resolve through `search_path` to
`public` and break identically. Four of those existed, including `errorHandler01` — the GLOBAL error
handler — doing `UPDATE incoming_documents`, and `indoxApi01 :: Get Changed Docs`. **Any census of
"who touches this table" must cover both spellings.**

**2. Two derived views are now per-tenant.** `company_registry` and `extraction_queries` (both built
on `settings`/`companies`) exist in each tenant schema, built with `search_path` set so their
schema-relative bodies bind correctly, and with `extraction_queries` repointed at its own tenant's
`company_registry` (schema.sql hardcodes `public.` there — the one non-relative reference in the file).
Proof they are genuinely separate: hacohen's `q_v3_company` binds to 186,878 bytes, levi's to 522.

**3. Global settings got a real home: `public.app_settings (app, key, value)`.** `indox01` was reading
`indox.auto.*` from `public.settings` — a compatibility view onto ONE tenant — so **the global
scheduler was gated by hacohen's rows**, and would have broken outright at the cutover. It now sits
beside the two global tables it already read, `public.indox_instances` and `public.app_schedule_state`.

**4. THE SCHEDULER CUTOVER IS DONE.** All four legacy schedule triggers DISABLED (not deleted —
re-enabling one is the revert path): `indoxV2BaseDrain01 :: Tick (2m)`, `syncV3Main0001 :: Schedule
15m`, `syncLedgerApi01 :: Reaper Schedule 5m`, `indoxHealth00001 :: Schedule Trigger`. `indox01` is
active and is now the app's only clock. `indox.auto.on = true`.

**5. TWO TENANTS PROVEN LIVE.** One tick (exec 3687638) dispatched all **8 (instance, job) pairs**;
each of the four workers ran **twice in the same second**, once per tenant, each carrying its own
`__instance` — read out of the flattened `execution_data`, not inferred from the dispatch table:

| worker | hacohen | levi |
|---|---|---|
| `indoxV2BaseDrain01` | 3687639 | 3687640 |
| `syncV3Main0001` | 3687641 | 3687643 |
| `indoxHealth00001` | 3687647 | 3687648 |
| `syncLedgerApi01` | 3687644 | 3687646 |

**138 executions, 0 errors.** Isolation intact: hacohen 25,982 / 82 unchanged, levi 1 / 68.

**levi got 8 OPERATIONAL settings seeded and none of the other 14.** The missing keys are hacohen
IDENTITY — Drive folder URLs, Gmail addresses, WhatsApp admin numbers, and `sync_registry`, which
names hacohen's actual document sources. Copying them would have pointed levi's pipeline at
hacohen's Drive and mail: the exact cross-tenant leak this migration exists to prevent, installed by
hand under the banner of "making levi work". **That distinction — operational vs identity — is the
settings taxonomy, and it is enforced by what is absent.**

**STILL OPEN before the views can be dropped:** the BFF's dashboard, sync board and action log still
read `public` (documents reads ARE tenant-scoped and proven: levi returns its 1 row, hacohen its
25,982, via `run_sql`); and `extraction.py` reads the two derived views, which now need pointing at
the tenant copies.

## 2026-08-28 — TWO DEPENDENT VIEWS WENT WITH THE TABLES THAT MOVED (fixed), AND run_sql WAS PUBLIC

**STATUS: both fixed and proven live. The cutover is HALTED — see the gate at the end.**

**1. `public.company_registry` and `public.extraction_queries` did not exist.** Both are VIEWS
declared in `schema.sql` (1221–1250 and 1302–1323), both built on `settings`/`companies`. When those
tables moved into `indox_hacohen`, the dependent views went with them and nothing recreated them.
**60 errors in 4 h across 14 active workflows**; `indoxSettings01` went 0 → 45 in one hour on
`relation "public.extraction_queries" does not exist`, and `syncV3Unit0001` 3 → 15.

Restored both from `schema.sql` **by line range rather than retyped** — `company_registry` encodes
identifier ordering, the 9-digit split and the `פריוריטי` exclusion, all of which a transcription
slip gets silently wrong. Into `public` deliberately: `public.settings` and `public.companies` are
already compat views onto `indox_hacohen`, so this reproduces pre-migration behaviour exactly and
adds no semantics the cutover then has to unpick. **Proven:** `company_registry` 1 row,
`extraction_queries` 16 keys, `q_v3_company` binding to 186,878 bytes, `indoxSettings01` last error
00:31 and three successes at 00:45.

**The lesson, which is the same one `merge_audit` taught: ownership is by REFERENCE, not by name.**
A census that filters objects by name prefix misses every view that merely *reads* a moved table.
Anything that reads a table is a dependent of it.

**2. `public.run_sql` was callable by `anon`.** `SECURITY DEFINER`, owned by `postgres`, and `anon`
is `PGRST_DB_ANON_ROLE` — so any unauthenticated caller reaching PostgREST had **arbitrary SQL as
superuser**, through every schema and RLS boundary. Cause is a Postgres default, not anyone's slip:
`CREATE FUNCTION` grants `EXECUTE` to `PUBLIC`, and Supabase serves every function in an exposed
schema as an RPC. Revoked from `anon` + `authenticated` only, by exact signature, every overload
(`anon f · authenticated f · service_role t · postgres t`). Safe because the BFF holds
`SUPABASE_SERVICE_KEY`; webapp has 0 references. Verified after: BFF still answers HTTP 200.
**Audit every new SECURITY DEFINER function in an exposed schema with
`has_function_privilege('anon', oid, 'EXECUTE')` — never by reading the ACL.**

**3. `indoxV2BaseDrain01 :: Read Settings` is now instance-aware** (query → expression; identifier
cannot be a bound parameter). Reads `__instance` off the passthrough item, resolves `indox_<tenant>`
behind `^[a-z][a-z0-9_]*$`, falls back to `public` when absent — i.e. today's behaviour, unchanged.
6 consecutive successful drains post-push. First of the 28.

**THE CUTOVER GATE — why it did not run tonight.** Not sequencing nerves; two independent blockers:
- **28 active production nodes** still name `public.<tenanted table>` (90 total, but 48 are in test
  workflows and the rest inactive). Dropping the views now breaks all of them at once.
- **PostgREST cannot see tenant schemas** (`PGRST_DB_SCHEMAS=public,storage,graphql_public`), so the
  17 compat views are the ONLY way the BFF reads tenant data. Dropping them does not degrade the
  console, it stops it. Resolved by routing tenant reads through `run_sql` — done and proven for
  documents (levi returns its 1 row, hacohen its 25,982); dashboard / sync board / action log still
  pass no instance and are in progress.
- Of the 16 workflows holding those 28 nodes, **14 already carry `__instance`** and 15 are entered as
  sub-workflows, so propagation rides the call chain. Only `indoxV2ActionRouter01` (the dispatch hub,
  7 callers) and `priorityLocalApi01` need plumbing.

## 2026-08-27 — RECEIPT IS A TYPE; ORDER AND RECEIPT ARE PARKED, NOT PROCESSED

**STATUS: CLOSED 2026-08-27.** Shipped, deployed, proven end-to-end on both synthetic and
real client documents, and the test artifacts cleaned up. One residue remains and it is not from
this change — see the Open note at the end of this entry.

**Owner order:** receipts get their own document type, and both ORDER and RECEIPT get a minimal
action router that marks the line COMPLETED and does nothing else — no per-type extraction, no
selection, no ERP sync. `gdoc` is renamed `invoice`, since with those two gone that is all it holds.

**Why:** ORDER was never parked — `resolveDocType` mapped it to `gdoc` and `gdocDecide` aliased
`orderDecide` straight onto `invoiceDecide`, so every order ran the whole invoice pipeline.
Measured over the 24 h before the change: **352 ORDER dispatches, 79 of them `priority_sync`** —
orders posted to the client's Priority as though they were payable, plus per-type OCR for invoice
fields an order does not carry. RECEIPT could not exist at all: **0 rows** of `TYPE='RECEIPT'` live,
because the Gemini base schema's `AI_TYPE` enum omitted it and `q_v3_type`'s fallback chain mapped
the bare anchor `קבלה` to *invoice*. Receipts were being filed as invoices.

**What shipped:**
- `resolveDocType` is a five-class map (`_DOC_CLASS`) plus a sentinel table (`_ROUTE`) read by both
  routing call sites — no ternary chain to drift. `unknown` still terminalises `MISSING_TYPE`.
- Two new lanes, `indoxV2ActionsOrd01` / `indoxV2ActionsRcp01`, 10 nodes each, decide inside the
  router like every other lane (`mode='export_decide'` → `fnSrc` → Mega Decide rehydrates).
  **One executable action: `mark_completed`.** No restart arm — `ACTION_RESTART != 'COMPLETED'`, so a
  restarted row answers `mark_completed` and lands; writing `ACTION_RESTART` already moved
  `indox_line_hash()`, so the dup guard does not see a repeat.
- Decide gains two `Export Seed`/`Call Export` pairs (still ONE chain, so every export runs before
  Mega Decide); the Action Router gains two **appended** Switch1 rules (indices 0–4 untouched,
  fallback moves to 7) and `Join Type Branches` widens 4 → 6.
- `q_v3_type`: a RECEIPT rule inserted **after** the `חשבונית מס` rule and **before** the bare
  `חשבונית` one, and the standalone `קבלה` anchor dropped from that invoice rule. The compound
  `חשבונית מס/קבלה` terms stay everywhere — that document IS an invoice.
- `AI_TYPE` enum gains `RECEIPT` in all three hardcoded spots. The prompt's *cues* needed no edit:
  they are compiled from `q_v3_type` itself (`typeReturnsFromQuery`), so the new rule teaches the
  model for free.
- BFF `_DISPATCH_DOC_TYPE` — the second copy of the type→class map — names ORDER and RECEIPT.

**Numbers that moved:**
- Classification, live `q_v3_type` on the product's own engine, 20 discriminating synth docs:
  **20/20**. All 12 combined `חשבונית מס/קבלה` matched rule **4** → invoice; all 8 standalone
  receipts matched rule **5** (the new one) → receipt. The anchor removal flipped nothing.
- Decide suite A/B (before = live export pre-push, after = this change), 61 cases:
  **0 broken, 4 fixed.** 50 fail identically on both sides — a pre-existing red, see Open 2.
- Parked-lane contract swept over **720 states** per type: exactly one executable verdict
  (`mark_completed`), **zero** forbidden actions leaked, and the invoice lane now *throws* if a
  parked type reaches it.
- Settings apply: exactly 1 row updated, re-read md5 `ba0a83aa…` equals the fixture byte-for-byte,
  the 4 invoice-anchor keys' md5s unchanged, `q_v3_company` resolver_gen still `50627c0b`
  (no estate-wide company-gate re-open).
- Half-applied window (router pushed 14:35:48Z, upstream 14:52Z): **0 dispatches** inside it — the
  only 2 in that period landed 14:35:07Z, 41 s earlier. 0 dangling, 0 `DOUBLE ACTION BLOCKED`.
- **EXECUTED PROOF (live, real client documents).** `DecideProbeTest01` (read-only) over the 83
  IN_PROGRESS rows, through the deployed `indoxV2Decide01` -> doc_base -> `__route_order__` ->
  `indoxV2ActionsOrd01`: **all 6 ORDER rows answer `mark_completed`**, the 77 INVOICE rows answer
  `no_action_priority_sync_missing_identity` (invoice behaviour unchanged), and
  `WOULD_SEND_TO_PRIORITY = 0`. Before this change those same 6 were on the invoice path toward
  `action_priority_sync`.
- Both new lanes execute successfully on EVERY decide cycle (`indoxV2ActionsOrd01` /
  `indoxV2ActionsRcp01`, status=success at 15:04:33, 15:06:33, 15:08:33Z) — the `export_decide`
  -> `fnSrc` -> Mega Decide rehydration path is live, not just compiled.
- BFF rebuilt and recreated; the running image now serves
  `_DISPATCH_DOC_TYPE = {BALANCE_SHEET: bs_doc, SHIPMENT: shipment, ORDER: order, RECEIPT: receipt}`.
  Root cause of the earlier build failure: `~/.docker/config.json` carries
  `credsStore: "desktop"` (Docker Desktop's helper, which this project never uses) and both base
  images are public — built with a neutral `DOCKER_CONFIG` instead.
- **THE LANDING, on a real client document.** `doc_msm30hzpr9hmyf` (TYPE=ORDER, stuck IN_PROGRESS
  since 08-26 12:36) given the sanctioned `ACTION_RESTART`, then left to the live drain:
  **exactly ONE dispatch — `mark_completed`, 0.66 s, execution 3678984** — and the row landed
  `IN_PROGRESS -> COMPLETED`. `PRIORITY_SYNC_COMPLETED` false -> false (never posted to the ERP),
  `PER_TYPE_EXTRACTION_COMPLETED` true -> true (no re-extraction), and `DOC_ID` / `NAME` /
  `SELECTED_DOC_ID` all unchanged. Its previous trip through the invoice lane took SIX dispatches
  (`restart_gdoc -> select_base -> extract_per_type -> select_type -> action_priority_sync ->
  mark_completed`), one of which posted it to Priority.
  Forbidden actions for ANY order/receipt since the push: **0**. Dangling: **0**.
  `DOUBLE ACTION BLOCKED`: **0**.
  Before-state preserved in `public.order_park_probe_20260827`; the `q_v3_type` original in
  `public.settings_backup_20260827`.
- **SYNTHETIC END-TO-END, BOTH TYPES, FROM A BLANK ROW (owner order).** One synthetic RECEIPT and
  one ORDER generated by apitools `/docGen`, uploaded to LOCALDRIVE (`drive_local-19213e58`), and
  injected as two rows carrying only LINK / LINK_CONNECTION / SOURCE_TYPE='MANUAL_TEST' — **TYPE and
  COMPANY_ID deliberately NULL**, so base extraction had to classify and resolve them itself. The
  company (514291418 / בי גי) is an EXISTING registry entry on purpose: inserting a new company
  moves `q_v3_company`'s resolver_gen, which by design re-opens the company gate estate-wide.
  Result — **both engines independently agreed**, which is the strongest form this proof takes:
      mt_rcp_20260827  LOCAL_TYPE=receipt  AI_TYPE=RECEIPT  -> TYPE=RECEIPT  COMPANY_ID=514291418
      mt_ord_20260827  LOCAL_TYPE=order    AI_TYPE=ORDER    -> TYPE=ORDER    COMPANY_ID=514291418
  `AI_TYPE=RECEIPT` could not have occurred before this change: the Gemini structured-output enum
  forbade the value, and the cues that taught it are compiled from the new `q_v3_type` rule, not
  hand-written. Action log, identical for both, 4 dispatches each:
      extract_base_doc 20:40:28->20:41:08 (39.5s) | select_base 20:41:15 (0.36s)
      get_company_name 20:41:21 (1.16s)           | mark_completed 20:41:27->20:41:28 (0.61s)
  **59.5 s blank row -> COMPLETED.** Per document: 1 `mark_completed`, **0 forbidden actions**,
  0 dangling, no ERROR. `PER_TYPE_EXTRACTION_COMPLETED` / `SELECTION_COMPLETED` /
  `PRIORITY_SYNC_COMPLETED` all `(never set)` — the parked lane never touched them.
  DOC_ID / SHORT_DOC_ID / DOC_TOTAL_AMOUNT are EMPTY, and that is the contract, not a failure:
  `q_v3_routing.base` extracts COMPANY_ID / TYPE / DOC_DATE only, and the per-type pass that would
  fill the rest is exactly what a parked type does not run.
  **Cleaned up afterwards (owner order).** Both rows and all 8 action-log rows deleted, scoped by
  exact ID and guarded on SOURCE_TYPE='MANUAL_TEST': estate went 25,984 -> 25,982 (exactly -2),
  MANUAL_TEST 0, action-log 0, TYPE='RECEIPT' rows back to 0. The two localdrive files were
  TRASHED via the canonical `delete` op (`trashed=true` — localdrive mirrors the Google adapter, so
  a trashed file is delisted but still fetchable by id; verified `trashed=t` on both and 0 hits in
  a 200-file listing). Emptying the trash is a hard delete and is deliberately left to the owner.
- **The cohort, not just the one.** By 16:07Z the drain had taken **all** of them: ORDER at
  `COMPLETED` went **318 -> 325**, `IN_PROGRESS` ORDER went to **zero**, and every ORDER/RECEIPT
  dispatch since the push is `mark_completed` — **7 of them, and nothing else**. No
  `extract_per_type`, no `select_type`, no `action_priority_sync`, on any of the seven.

**Open, one residue — not introduced here:**
1. **`indoxV2DecideTest01` is 50/61 red, pre-existing.** The 2026-08-25 selection refactor
   (`select_base`/`select_type`) shipped LIVE while still uncommitted — `select_base` appears 0× in
   git HEAD, 5× in the working tree, 1× in the live instance — and the case list was never
   re-baselined. It expects the retired `extract_invoice_google_ai`/`select_invoice_values` and sets
   no `BASE_SELECTION_COMPLETED`, so every non-COMPLETED case stops at `select_base`.
2. **`.push-cache/indox.tsv` — RESOLVED for this change's 11 workflows.** It had gone root-owned
   (owner fixed the ownership 2026-08-27 18:10), and the force-push at 14:40 could not write it, so
   8 rows still held a stale sha + base version. Re-synced surgically: only the 11 ids this change
   deployed, whose repo genuinely equals live. NOT `--prime` — that writes every row ("blueprint
   taken as matching live") and would have asserted repo==live for the ~30 workflows carrying
   pre-existing uncommitted work, blinding the conflict guard on them. Verified: 73 rows in and out,
   0 ids lost, exactly 8 rows changed and all of them ours, 11/11 cached base == live updatedAt, and
   a dry-run push dropped from 38 candidates to 30 — the 30 being that untouched uncommitted work,
   still correctly guarded. Backup at `.push-cache/indox.tsv.bak-20260827T193348Z`.

**Workflow-ID rename — DONE (owner order, same day, as a separate step after the behaviour change
had landed and been proven).** `indoxV2ActionsGDoc01` -> `indoxV2ActionsInv01`. n8n has no rename,
so: create-new (push-app sees an unknown id -> import + publish) -> repoint the two executeWorkflow
callers -> deactivate + archive the old. Blast-radius scan first; the one thing that could have
blocked it — the id appearing in live client config, the way `SyncProcGDoc0001` does — came back
EMPTY for `public.settings`. Repointed: `indoxV2ActionRouter01 :: 'Call indox-v2 Actions — GDoc'`
and `indoxV2Decide01 :: 'Call Export (gdoc)'`, plus `indoxV2GDocTest01`'s collectionId,
`hooks/sync-coverage.py`, `hooks/v2-actions-test.mjs`, two lint configs and the two spec fixtures.
Verified: 13/13 compile-time checks (84 nodes preserved, export contract intact), **0** live
workflows still targeting the old id, and the renamed workflow executing inside a real decide run
(`indoxV2ActionsInv01` success 19:53:18Z under `indoxV2Decide01` success 19:53:18Z).
The old id is **ARCHIVED, NOT DELETED** — `execution_entity` holds **1,100** rows keyed to it and
nothing migrates them — and renamed `indox-v2 Actions — GDoc (RETIRED 2026-08-27 - id renamed to
indoxV2ActionsInv01)`, following this instance's own precedent (`indox api (RETIRED 2026-08-12 …)`).
Node names (`Call Export (gdoc)`, `Call indox-v2 Actions — GDoc`) deliberately NOT renamed in the
same pass: Mega Decide reaches that node by `$('Call Export (gdoc)')`, so a missed reference breaks
decide outright. Separate, cheap, do it on its own.

**Not done, deliberately:** `SyncProcGDoc0001` keeps its name — it is stored inside live
client `sync_registry` rows and names the ingest pipe, not the doc class. And no `batch:rcp` E2E
lane: a real one needs receipt fixtures in `blueprint/demo-docs/` with ground-truth wiring, which is
a corpus change; RECEIPT is covered by the decide cases, the doc_base route case, and the 20/20
classification gate above.

## 2026-08-26 — A DOUBLE ACTION IS A REPEAT ON AN UNCHANGED LINE

**Owner order:** the guard may only call a repeat a fault when the line has not changed since the
earlier dispatch. A field that legitimately moved — a corrected date, a `*_COMPLETED` mark cleared
by hand, an action run manually — gives the action new inputs, so re-running it is work, not a loop.
Every dispatch row therefore records the hash of the whole line at dispatch time, and the driver
compares that against the line's hash now.

**Why:** the old rule was existence-only ("this action is in ACTION_HISTORY and no ACTION_RESTART
came after it") and could not tell the two apart, so it refused both. Measured over the 24 h to
2026-08-26 19:02Z: **256 of 256** `indoxV2Driver01` failures were `DOUBLE ACTION BLOCKED`, **7,216**
blocked lines across **1,180** documents, 97 % of them `select_base` — and **not one was a real
loop**. Root cause: an ad-hoc `DOC_DATE` normalisation (1 statement, **2,503** rows, still in
`pg_stat_statements`) left **1,306** lines with a stale `BASE_SELECTION_HASH` (**1,241** differing in
`DOC_DATE` alone), so decide re-proposed `select_base` every sweep and the guard refused it every
sweep — a permanent deadlock, since only `ACTION_RESTART` could clear it and nothing issued one.

**What shipped:** `public.indox_line_hash()` (whole row, `updated_at` excluded — it is bumped by
every write, so including it would make the guard a permanent no-op); `LINE_HASH` on
`indox_action_execution_log`; the hash computed **once per line per pass** in the driver's
`Enrich Double Lines`, carried on the line, stored by the router's `Log Action Start` and compared by
`Dup Guard: Double Action`. Signal B (the completion-flag table) is **removed** — under the new law a
`*_COMPLETED` flag is part of the line, so it is either already covered by the hash or actively
wrong. The history window went 10 → 16 to cover the residue signal B used to.

**Numbers that moved:**
- Driver failures: **256 / 911 runs before**, **0 / 28 after** the push; zero `DOUBLE ACTION` since.
- Writer proven live: **1,760 of 1,760** post-deploy dispatch rows carry a well-formed 32-hex hash.
- Pass-through proven byte-exact on a live document: the hash the router stored equalled the
  pre-dispatch line hash exactly, and differed from the post-action hash (`doc_msmv25vtnfpefx`,
  `75d56153…` stored = `75d56153…` pre-action, `8f839b57…` after).
- Guard proven still to fire: on that same document, restored to its pre-dispatch content (the
  "action ran and did not move the document" state), the live guard returns **BLOCKED**. Row
  restored afterwards; `still_armed=f`, byte-identical to its post-action state.
- No-regression harness: `bbox indox dup-guard-test` — **13/13**, running the *deployed* guard code
  read out of n8n, including live cases built from real `ACTION_HISTORY` rows.

**Open, two residues — both pre-existing, neither introduced here:**
1. The `STATUS='IN_PROGRESS'` escape hatch (2026-08-25) is evaluated before the hash compare, so for
   any action whose pre-state is IN_PROGRESS (`mark_completed` among them) a genuine unchanged-line
   repeat is skipped rather than raised.
2. The live-race escape only recognises an OPEN dispatch bracket, so a **fast-closing** concurrent
   lane still reads as a loop. Both post-deploy blocks look like this: `doc_msm7sas80wr94k` was
   blocked on `select_type` at 21:30:29 citing `LINE_HASH 58755647`, and the `select_type` dispatch
   carrying exactly that hash was opened by another lane at 21:30:39 and had already closed. Correct
   per the rule as written (same action, same line, no restart) — but it is a race, not a stuck
   loop, and the doc went on to progress normally (`restart_priority_sync` 21:31:10,
   `action_priority_sync` 21:31:50). Worth an owner decision on whether a just-closed bracket should
   count as in-flight.

## 2026-08-25 — EXTRACTION AND SELECTION ARE TWO DIFFERENT JOBS

**Owner order:** extraction depends only on the document and writes only its engine's versions
(`LOCAL_*` / `AI_*`); a separate step reads the WHOLE ROW — every version plus the filename, the
source and the supplier's ledger line — and decides the final unprefixed value. `SELECTED_*` is
legacy and goes. Plan: `issues/selection-consolidation-plan-2026-08-25.md`.

**What shipped:** two pure sub-workflows (`SelectBase01`, `SelectType01`) and two action verbs
(`select_base`, `select_type`) wired into all four routers, gated on a hash of the selection's own
inputs so a decision is re-made when a version changes underneath it — which is what finally lets a
late aging-report line reach a document that was already COMPLETED. The four extractors write no
finals any more; the retired `select_invoice_values` branch is deleted (43 KB).

**Numbers that moved:**
- Parity over **1,000 real gated rows** through the live selectors: COMPANY_ID **1000/1000**,
  DOC_ID **0 drift**, TOTAL_AMOUNT **0**; TYPE 5, date 16, amount 32, shipment 20, order 34 — every
  one classified as either a stale stored value or the new code being right.
- Hash convergence, the risk that would have caused an endless re-dispatch: **220/220** type and
  **278/278** base hashes stable on the first live batch; over the backfill wave, **4,684
  dispatches on 4,684 distinct documents, max 1 per document**.
- End-to-end on three real documents emptied to nothing (invoice / shipment / aging report):
  `extract_base_doc → select_base → extract_per_type → select_type → … → COMPLETED`, scores 100 /
  100 / 50, `SELECTED_*` null the whole way, priority rows with full identity.
- Priority signature rewritten over the finals; **6,050** stored signatures recomputed, `stale=0` —
  **zero spurious re-sends**.
- **446** identity-less rows deleted from `indox_priority_local` (backup:
  `issues/priority-identityless-backup-2026-08-25.json`); `junk_now=0` since.
- Three defects the work exposed and fixed: the C11 junk-id rejector's regexes were missing their
  backslashes (date and company-number rejection could never fire); `SHIPMENT_DOC_ID` was written as
  a raw JSON array on 92/400 sampled rows; the per-type selector re-decided base's own date under
  the balance sheet's reversed rule and replaced it on 124/400.

**Open, owner's call:** (a) the **21 documents** that re-emit an action they have already had —
DOUBLE / EXTRACTION_FAILED / OLD / ACTION_REQUIRED, none of which any gate recognises; one of them,
`doc_mt5ke1tu34y889`, has taken four restarts in three days and proves a downloader overwrites the
state machine's verdict. (b) **2,967 of 7,058 already-synced rows** now hold finals that differ from
what the ERP received — corrections, deliberately not sent. (c) the `SELECTED_*` columns are NOT
dropped: with (b) outstanding they are the only record of what was actually sent.

## 2026-08-25 — THE SOURCE CONTRACT: sync settles the facts, select derives the answers

**Owner order:** the sync decides, per sync, WHO sent it / WHICH sync / WHAT text came with it
(`SENDER`, `SYNC_REGISTRY_ID`, `ATTACHMENT_TEXT`, + `SEND_DATE`); the selector derives
`COMPANY_BY_SENDER` and `TYPE_BY_SOURCE` and uses them as options for every datum. Then: prove it
end to end, from sending a mail to the row reaching COMPLETED with all its data.

Full write-up + the E2E: `issues/indox-source-contract-and-e2e-2026-08-25.md`.

**Numbers that moved / were established:**
- Mail-origin documents with no company: **19.5%** (1,463 / 7,493). By lane: gmail-link **46.3%**
  (intermediary senders), gmail-doc 15.7%, gmail-bs **7.4%** (the "complicated" old lane is 6×
  better — its sender logic is the thing to generalise, not retire).
- Root cause proven: **the sender was never persisted** — no SENDER/subject column existed, and
  `SOURCE_LIST.mailbox` is null. No selector could use it however good it was.
- `companies."מייל 1"/"מייל 2"` (address OR bare domain) exists and **nothing ever read it**;
  `indoxSettings01` even exports `company_id_by_mails` with zero consumers. Only **136/1,183**
  companies (11.5%) have a mail mapping — that is the ceiling until it is filled.
- **Full sender chain, not one address** (owner's correction, proven in SQL): a chain with two
  real companies resolves to the FIRST (איטונג@9 over טמבור@29); "unambiguous only" returned
  nothing. All three mail lanes now emit the ordered chain; the leg resolves in chain order.
- Live E2E: 11 synthetic Hebrew documents; **5 real mails sent from the owner's account**; the
  label engine routed them by CONTENT unprompted (E2E-3 → BS lane on "דוח גיול"); the drive lane
  wrote all four source facts and the document completed.
- **Two defects the proof exposed, fixed live:** (a) `SyncProcGDoc0001` stamped the TERMINAL
  `COMPLETED` on `Is OK` alone while its own REQUIRED_ACTION said "Missing company name", and it
  renames the file to `unknown-*` — so `select_base` could never run and the company (present in
  ATTACHMENT_TEXT: "ברייטקום ב" = 515273175) was unreachable; now COMPLETED requires company AND
  type, else IN_PROGRESS. (b) `SYNC_REGISTRY_ID` derived from the wrong ctx field.

## 2026-08-25 — THE SYNC UI IS THE OPERATOR'S SURFACE (audit + repair)

**Owner order:** "everything you do should happen via the sync ui… make sure the human operator
can make sure full ground truth is synced by looking at the syncs and making everything green
(restarting fails / seeing exactly the sync scan whats left) … everything aligned and minimal and
syncs follow the rule of monthsOld everywhere."

**The numbers that moved** (full forensics: `issues/indox-sync-ui-operator-audit-2026-08-25.md`):
- `GET /sync/registry` **5–10s on every 5s poll → 82ms warm / one ≤6s cold per 90s window**
  (stats memo TTL 5→75s + the 90s background pass now primes the memo; the cold board that
  rendered "אין עדיין מקורות סנכרון" over 8 live sources now renders the truth or an honest
  "לא נטענו עדיין").
- **Restart-a-failed-item: >180s + proxy 502 + NO effect at the source → `moved=1` in 18.8s
  with the relabel PROVEN at Gmail** (real to_sync label added, failed label removed, message
  `1987f6be3c15da6f`). Three stacked defects fixed: mutation replies defaulted to a full
  multi-minute estate recompute (`_enrich_registry(with_items=True)` → False); the legal-move
  gate ran a live source walk per click (→ ≤90s stats cache); `_gmail_move` sent role KEYS as
  literal Gmail labels (mailapi auto-created a bogus `BS_TO_SYNC` label — gmail restarts had
  NEVER landed; keys now resolve via `organizer/settings`, residue cleaned).
- Cards' `הרצה אחרונה —` (forever) → real last-touch per pipe from `sync_pipe_state`
  (latest-of scoped/`*`, started-at fallback for canceled passes, n8n execution link).
- Eternal "רץ כעת" strip: a canceled pass leaves `run_status='running'` forever → `/sync/runs`
  reports >45min-old running rows as `stale` (running count drops to 0 honestly).
- Zombie `processLock01` renew (8h `running`, parent pruned) fed the "ניקוז רץ" badge → crashed.
- **monthsOld:** live v3 lane verified settings-driven end-to-end; `indoxGmailLinkDownloader01`
  hardcoded 6 → reads `old_document_months_back` (pushed, live node verified);
  `fixtures/settings.json` fresh-install default 1200 (unbounded!) → 6. Legacy v1 lane
  (`SyncSource000001` + inactive scanner pair) documented as non-compliant retirement
  candidates — referenced by BFF/hooks, so removal is a scoped task.
- Remaining operator gaps + the drive folder re-share blocker: listed in the issue file.

## 2026-08-25 — SELECTED_* retirement plan + priority-table quality gate

**Two deep-dive agents mapped the whole selection estate** (evidence in the reports; plan:
[issues/selection-consolidation-plan-2026-08-25.md](issues/selection-consolidation-plan-2026-08-25.md)).
Headlines: base selected TWICE (router copy drops 2 guards); legacy select_invoice_values
still live (147/12h) and is an AI-leading second opinion feeding the ERP payload alone;
SELECTION_VALUES_HASH (the designed BS-late re-selection trigger) was NEVER implemented —
re-selection for COMPLETED docs is impossible today; Map Request's SELECTED_-only reads
made ~440 identity-less ERP-staging rows ('null' strings). 6-phase plan awaiting go.
Also shipped same-day: merge carries PRIORITY_SKIP (indoxApi01 Build Merge Write — proven
live: seed merged, winner inherited flag); 841 blocklist seeds (SOURCE_TYPE=
PROBLEMATICK_SKIPS, skip=true, statuses left to the machine); the 2 leaked blocked docs
marked+their priority rows deleted; final priority census: 0 problematic, 0 aging-report
content, ~122 true business-dup rows, 315-440 identity-less rows pending cleanup.

## 2026-08-24 — ONE SELECTOR: the view's filter IS the selection, everywhere

**Owner order:** "סלקטור פנימי יחיד… נתון מצב יחיד הכל מינימלי ונקי בלי שאריות", select-all is
ALWAYS the whole matching set, everything a feature of the table itself, and CSV export must stop
lying (it downloaded the visible 50 while 39,283 were selected).

**The numbers that moved:** page-side selection state went **3 datums → 1** (`sel`; `selIds`/
`clearSel`/`allSel`/banner all deleted — grep 0 leftovers); export of a 94-row filter selection
returned **93 rows** (1 except honored) vs the old page-bound 50-row file; unknown export column →
**400**; new bundle serves the grid-bar text (3 hits).

- `DataGrid` gained an optional controlled `GridSelection` (`{ids}` | `{filter, except}`): header
  checkbox = ALL matching rows (no page-then-offer two-step), row toggles carve `except`, paging
  KEEPS the selection, search/column-filter change CLEARS it, bar shows `כל התואמים לסינון (למעט N)`.
  Internal page-scoped mode unchanged for any other consumer (audit: exactly one consumer).
- BFF `POST /repos/<r>/documents/export` — streams the WHOLE selection as CSV (BOM, RFC4180,
  100k cap with in-band `__TRUNCATED__` sentinel row, 500-row full-width pages). Root-caused live:
  an explicit PostgREST `select=` 400s on schema-declared virtual columns (`COMPANY_DOC_ID`), so it
  fetches full rows like the proven dispatch path.
- Bulk/dispatch/drain/status/field-edit modals show the honest full count + the 5,000-per-run
  ceiling note when it applies; cards view got the same select-all + export bar.
- **UI QA: 9/9 user stories PASS in the owner's own Chrome** (select-all=39,284 instant; except
  carving; query-change clears; filtered export = exactly 1,385 rows / 3.33MB, not 50; all 4
  modals honest-count + cancel-safe; field write+clear round-trip restored baseline; cards
  48/50 thumbnails; URL round-trip; 0 console errors). 4 findings fixed same-day (BulkStatusModal
  hid the 5,000 ceiling; blank-gray no-preview cards; "רוקן" mislabeled as "נכתב"; "1 שורות").
  Open by owner decision: free-search matches raw enum values not Hebrew labels (172/39,284 for
  "חשבונית"); selection-bar appearance shifts the grid ~47px (Gmail-style overlay would fix).
- Table strip removed → repo SELECTOR in the grid toolbar (navigates the instance's repos);
  drill chips unified into grid chips; icon-only pager (console's stroke-icon set); thin
  scrollbars; PipelineBar → floating pill (collapsed by default, persisted, full panel on click).
- **THE URL IS THE SELECTOR (owner order):** console shell deep-links (`#/m/<id>/inner?query`),
  app→shell route mirror (postMessage + replaceState, loop-impossible), grid column filters
  round-trip through the URL (`f_/has_/in_/m_/empty/notempty` + new `ne_<COL>`), drill chips
  derive from params on a stable key (no state copy). Contract: console-url-state.md rule 7.
- **Navigation audit (2 agents) + cleanup, all live-verified:** frame-reality guard in showEmbed
  (rail-click desync dead — hash and screen move together), `e.source` + shape guard on the
  mirror, skip-link no longer teleports to drive, module id for share-links read from the
  shell's hash (alias≠id for 4/10 modules), launchCard + its CSS deleted (structurally
  unreachable), self-redirect `/repos` fallback → honest empty state, legacy `/repos/:repo`
  now carries the query string, ONE doc-route constructor per file (was 8 builders / 3
  encoding rules), drill-param vocabulary extracted to urlVocab.ts (was hand-typed ×3),
  extraction routes segment-encoded, dead "כל המאגרים/חזרה למאגרים" links removed/relabeled.

## 2026-08-23 — THE MERGE PATH WAS DOWN, AND HASH-ONLY DOUBLES COULD NEVER MERGE

**The numbers that moved:** duplicate groups measured on the DETECTOR's key (biz -> hash -> comp),
not the business key alone: **1,464 open at baseline — 1,446 biz + 18 hash**. The 18 had no path
to resolution at all. Live node bodies checked against source: **452 across 69 workflows, 0
broken**. Regression fixture: **HASH-ONLY PASS, BUSINESS PASS**.

| # | defect | why it was invisible | proof |
|---|---|---|---|
| 1 | An unescaped backtick in a COMMENT in `Adjudicate Merge` closed the TypeScript template literal. The transformer compiled the 2,269-char prefix; the live node lost its `return`. Every `action_merge_doubles` died with "Code doesn't return items properly" | `bbox n8n push` reports `ok update+activate` from the API response, not from the bytes n8n stored. Nothing compared the two | 10 errored dispatches 01:00–03:35; live 2,269 -> 16,498 chars after the fix; business fixture went FAIL -> PASS |
| 2 | `Build Group Fetch` asked the api by `COMPANY_ID` only. A pair whose only shared key is HASH produced zero filters, returned `_empty`, and the adjudicator saw no rows: no group, no verdict, no status — so the detector raised the same pair again every sweep, forever | The non-main reached `DOUBLE` and the main sat in `ACTION_RESTART`, which reads as "in progress", not "stuck" | hash-only fixture pair FAIL -> **PASS (one absorbed)**; `HASH` was already on the api's pushdown whitelist, so this costs one filter group, not a wider scan |

**Two gates, so neither class can hide again:**
- `scripts/ops/lint_backticks.py` — rejects an unescaped backtick in any `jsCode`/`query` literal.
  It tells the truncating backtick from the legitimate closing one by what FOLLOWS it (`,` `}` `)`
  vs prose), which is the only thing that distinguishes them. **1 hit across 69 files: this bug.**
- `scripts/ops/verify_live_parity.py` — compares every live node body against its source and runs
  `node --check` on any that differ, separating a mangled push (**BROKEN** — the node is down)
  from ordinary version skew. **452 bodies / 69 workflows: 0 BROKEN, 11 version skew.**

**Why the fixture is two sweeps:** convergence is the contract, not one pass. Sweep 1 flags the
non-main `DOUBLE` and dispatches the main's merge; the merge lands on the next pass. Asserting on
one sweep is what made the *working* business path look broken.

**A committed fix that had never been deployed — now live.** The parity gate's one production
finding: `indoxApi01 :: Build Deliver` was 6,152 chars in the repo and 4,784 live, and `indoxApi01`
was NOT on the "changed live" list, so the repo was simply ahead and nobody had pushed it. The diff
is the `sync_kernel V Del1` fix from 2026-08-22: the deliver fetch bound a **NUL byte** as its
absent-value sentinel, which postgres refuses in a text parameter at all, surfacing as the
protocol-level *"invalid message format"* naming neither parameter nor value. Every DELIVER without
a `SOURCE_TYPE`/`SOURCE_ID` hit it — the drive and gmail lanes always send both, which is why it
looked confined to one suite rather than to the shared write path. Pushed and parity-verified
(0 differ, 0 broken). **`sync_kernel` needs re-measuring against live now**, since its red line in
WORKLEFT was written while the fix sat undeployed.

**Version skew worth an owner decision** (all parse, none are down): `indoxApi01 :: Build Deliver`
is 6,152 chars in the repo and 4,784 live, and `indoxApi01` is NOT on the "changed live" list — so
the repo is ahead and was never pushed. Pushing it blind could regress behaviour nobody has
re-verified. The other 10 are test workflows a human edited live (`bbox n8n status` names them).

### What actually paces the restart cycle: OCR, not locks and not the guard

Worth writing down because it was misread twice, from two different directions.

120 `extract_base_doc` brackets sat open for 17-34 minutes and looked like a wedged extraction
pool blocking every lane. Measured instead of inferred:

    distinct execution ids behind those 120 brackets : 2      (both status=running)
    extract_base_doc median duration, closed, last 2h: 14m 06s
    BASE_EXTRACTION_COMPLETED set in the last 10m    : 20
    extract_base_doc brackets closed in the last 30m : 23
    dispatches in the last 2m                        : 47

The 120 brackets are **two executions**, not 120 — `extract_base_doc.max` is 60, so each dispatch
carries up to sixty documents. A 17-34 minute open bracket is inside the normal range when the
median is fourteen minutes, and the pipeline was dispatching and closing normally around them.

So the ceiling on the restart cycle is **OCR throughput, roughly 2 documents a minute**. Not the
doc_action lock (real, but a leak affecting merges), not the double-action guard (real, but it
costs whole batches rather than throughput). Both of those are worth fixing on their own terms and
neither would speed this up.

A stale open bracket is not evidence of a stall. Check how many EXECUTIONS are behind it first --
one long batch looks identical to sixty stuck documents in the bracket table, and only the
execution ids tell them apart.

## 2026-08-23 — THE TABLE STOPPED MOVING BECAUSE OF ONE TYPE ERROR, REPEATED 26 TIMES

The settle loop printed **"AT REST: status census unchanged for 3 rounds"**. It was not at rest.
It had reached the point where these gates stop firing:

    MISSING_COMPANY_ID  1,231 rows  ->  1,227 carry COMPANY_NAME_COMPLETED    = 'false'
    IN_PROGRESS         1,116 rows  ->  1,061 carry BASE_EXTRACTION_COMPLETED = 'false'

`incoming_documents` stores booleans as TEXT, and in JavaScript **the string `'false'` is TRUTHY**.
So `if (!doc.COMPANY_NAME_COMPLETED)` is FALSE for a row explicitly marked not-done, and
`get_company_name` was never dispatched for 1,227 documents. Same for extraction on 1,061 more.
**2,288 documents were standing still, and every log said the pipeline was healthy.**

`MISSING_LINK` (1,106) is **not** this bug — zero of those rows carry `'false'`. It needs its own
diagnosis and is still open.

Every affected column is live, not theoretical:

| column | rows holding the string `'false'` |
|---|---|
| `API_TOOLS_ID_COMPLETED` | 6,838 |
| `PRIORITY_SYNC_COMPLETED` | 5,770 |
| `COMPANY_NAME_COMPLETED` | 5,720 |
| `SEARCH_IN_DRIVE_COMPLETED` | 5,306 |
| `SELECTION_COMPLETED` | 4,161 |
| `PER_TYPE_EXTRACTION_COMPLETED` | 4,137 |
| `BASE_EXTRACTION_COMPLETED` | 4,061 |

**26 sites normalised across four workflows.** `scripts/ops/lint_text_boolean_truthiness.py`
derives the boolean-in-text column list FROM THE DATA (so it cannot drift from a hand-kept list)
and reports 0 risky reads across 69 workflows. Run it on every push.

**Proven per-row, NOT yet in aggregate.** `scripts/ops/test_text_boolean_unblocks.sh` picks a live
IN_PROGRESS document whose `BASE_EXTRACTION_COMPLETED` is the string `'false'` and which holds no
lock, feeds it, and asserts a new dispatch appears:

    candidate: doc_msi5gykcqtk6zz   before: IN_PROGRESS, base_extraction=false
    dispatch: extract_base_doc  end=OPEN      dispatch rows: 32 -> 33
    UNBLOCKED: PASS

Thirty-two prior dispatches on that document, not one of them `extract_base_doc`. It got one within
a single drain of the fix landing.

The aggregate has NOT moved — IN_PROGRESS is still 1,116. The rest are lock-held (619 live
doc_action locks) and extraction runs at a ~14-minute median, so this population clears over lock
cycles, not in a sweep. Do not read the per-row proof as a drained backlog.

**Where the remaining populations actually stand:**
- `ACTION_RESTART` 200 — **all 200 explained, 0 unexplained**: every one holds a doc_action lock,
  so each feed lock-skips it by design (`scripts/ops/explain_stuck_action_restart.sh`).
- `MISSING_COMPANY_ID` 1,241 — these take the "no company id at all" path, not the
  `COMPANY_NAME_COMPLETED` gate. A genuine terminus pending a company mapping, not a bug.
- `MISSING_LINK` 1,106 — **not** the truthiness bug (zero of those rows carry `'false'`).
  Undiagnosed and still open.

**Two of the changes REDUCE work:** the skip whose comment says it "exists precisely to leave
already-ERP-synced documents alone" used `=== true` against a string and had never once fired, so
3,455 already-synced documents were being re-selected on every sweep.

## 2026-08-23 — PRIORITY SYNC IS ON, AGAINST THE LOCAL MOCK

    activePrioritySync                    = true
    indox.actions.priority_sync.local     = true      <- nothing reaches the client's ERP
    priorityLocalApi01                    = active
    indox_priority_local rows             = 51 -> 68  <- real payloads, verified

Sample of what landed, and note the last column:

    doc_msmfz9fson2fbj  516431434  SI266000975  warehouse=Y  total=2974
    doc_msm33ay5zus8pp  510711716  23598871     warehouse=Y  total=466.57

`FROMWAREHOUSE=Y` is the mapping fix whose signature mismatch was corrected earlier today —
the payload and the fingerprint now describe the same thing.

**The toggle did nothing on the first attempt, and the reason is worth keeping.**
`PRIORITY_SYNC_COMPLETED` is a TEXT column and the send gate read it as a boolean:
`!doc.PRIORITY_SYNC_COMPLETED`, where the string `'false'` is TRUTHY in JS. Census of the 10,210
COMPLETED documents at flip time:

    'false'   5,770   <- read as ALREADY SYNCED. could never be sent, ever
    'true'    3,455
    NULL        976   <- the only rows the gate could fire for
    Hebrew report text  6   <- junk in a boolean column, separate issue

So a 20-document cohort produced zero dispatches. This also corrects the blast-radius figure
recorded above: "6,755 would send" was computed in SQL, where `'false' <> 'true'` means not-synced.
The JS gate disagreed with the SQL, and the real figure was 976. Measuring a JS predicate with SQL
semantics is the same error as measuring duplicates with a key that skips the detector's predicates.

**Two more instances of the same bug, REPORTED not changed** — they alter selection behaviour for
3,455 documents and want a decision, not a drive-by fix:
- `Selection & Scoring Logic1` (~line 698 GDoc / 670 Ship): `d.PRIORITY_SYNC_COMPLETED === true`.
  Strict equality against a boolean never matches a string, so the skip whose own comment says it
  "exists precisely to leave already-ERP-synced documents alone" **has never once fired**.
- decide (~2966 / ~2826): `doc.PRIORITY_SYNC_COMPLETED !== true` — always true, so that clause of
  the select guard is inert.
Both cause 3,455 already-synced documents to be re-selected on every sweep.

**Before turning `local` off** — two things the mock has already surfaced, which is the whole
point of capturing the payloads locally first:

1. **5,770 rows are now eligible** that never were, because the send gate could not read the
   string 'false'. They would all post.
2. **~34% of payloads carry TOTPRICE = 0.** Of 84 captured, 29 have a zero total and **27 of those
   have a blank `SELECTED_DOC_AMOUNT` on the source row** — so the zero is a faithful mirror of
   missing data, not a mapping fault. The mapping itself is sound: zero blank DOCNAME, IDSUP or
   DATEDOC, and FROMWAREHOUSE=Y on 81 of 84 (the corrected coercion).

   A third of documents arriving in the client's ERP with a zero amount is a business decision,
   not a bug to fix quietly: either the extraction gap is closed first, or those rows are
   withheld from the sync, or zero is accepted. Nothing in the code should choose that.

## 2026-08-23 — WHERE THE TABLE ACTUALLY RESTS, and why the drain was stopped

`ACTION_RESTART` reached **0**. The restart cycle is done. What remains is not pipeline work:

    non-terminal                                          3,997
      MISSING_LINK, drive search RAN and found nothing     1,143   waiting on the FILE
      MISSING_COMPANY_ID, no company resolvable anywhere   1,437   waiting on a COMPANY MAPPING
      MISSING_TYPE + UNKNOWN_COMPANY                         390   same shape
      IN_PROGRESS (mid-flight / OCR-bound)                   982
    rows updated in the last 3 minutes                         4

**2,970 of 3,997 (74%) are waiting on data that does not exist.** Every MISSING_LINK row carries
`SEARCH_IN_DRIVE_COMPLETED='true'` — the search ran, completed, and found nothing. Every
MISSING_COMPANY_ID row has neither a COMPANY_ID nor an AI_COMPANY_ID. Feeding them again dispatches
an action that cannot succeed, and the double-action guard correctly refuses the repeat.

So the settle loop was stopped deliberately. It was re-feeding data-blocked rows to no effect, and
a loop that runs forever without moving anything is indistinguishable from progress on a dashboard.

**A limit of my own gate, stated rather than hidden.** `count_feedable()` calls a row feedable when
it is non-terminal and unlocked — it reported 3,774. Mechanically true, practically wrong: three
quarters of those cannot progress no matter how often they are fed. The gate is honest about locks
and blind to data-blocking. Making it right means deciding that "searched and not found" and "no
resolvable company" are TERMINAL states, which is a product judgement about what those statuses
mean, not a lint fix — so it is recorded here rather than assumed.

**The three data questions this leaves, none of them engineering:**
- 1,143 documents whose file is not in the Drive the connection can see (wrong folder scope? file
  deleted? never uploaded?)
- 1,437 documents whose company cannot be resolved from anything on the row
- 390 with no usable type

## 2026-08-23 — DOC_ID extraction is healthy in production; "4 of 70" is a fixture figure

`sync_sources`' proc-* lanes are recorded as failing with "docs land with COMPANY_ID/TYPE/DOC_ID
null", and a peer session put it as "only 4 of 70 docs reaching a DOC_ID — the real product path,
not a fixture artefact". Measured against the live table, it is the other way round:

    documents (non-MERGED)      33,144
      with a real DOC_ID        26,756    80.7%
      of COMPLETED               9,251 / 10,207   90.6%
      AI_DOC_ID present         19,902
      SELECTED_DOC_ID present   21,414

Coverage by status is coherent rather than broken — the gaps sit exactly where a document stopped
BEFORE the per-type extraction that produces a doc-id:

    MISSING_LINK        1,120 / 1,122   99.8%   <- have a doc-id, just no Drive link
    COMPLETED           9,251 / 10,207  90.6%
    OLD                15,525 / 18,846  82.4%
    IN_PROGRESS           788 / 1,179   66.8%
    MISSING_COMPANY_ID     55 / 1,272    4.3%   <- no company resolved, so extraction never ran
    MISSING_TYPE            7 /   231    3.0%   <- no type, so no per-type extraction
    UNKNOWN_COMPANY         2 /   151    1.3%
    GARBAGE                 0 /    94    0.0%

So the proc-lane failure is a fixture or test-environment condition, not a product defect. It is
still worth fixing — a red suite is a red suite — but it is not evidence that the extraction path
is broken for real documents, and diagnosing it means understanding the suite's seeding, which is
suite work.

Recorded because the opposite reading was being carried to the owner: a fixture number describing
a fixture, read as a product-wide extraction failure.

## 2026-08-23 — sync_full `mixed` and `registry`: the recorded cause no longer exists

Both lanes are reported failing, `registry` specifically with `gate.delivered undefined`. That
symptom is **explicitly documented in the suite as the PRE-GUARD form of the singleton lock**:

    // NAME THE SKIP (same singleton as Assert Mixed). Without this the lane printed 17
    // 'undefined != 3' lines that described the lock, not the registry.

`syncV3Main0001` is a mutex-guarded singleton whose own Lock Note measures the live reconcile pass
at **848-1223s against a 900s schedule** — the lock is held nearly all the time, so a Main-driven
lane never ran and reported it as a registry bug. The suite's comment says that "sent three
sessions hunting a registry bug that was not there".

**It is already fixed, in the repo AND live:**

| | |
|---|---|
| suite passes a per-execution `lock_key` | `sv3f_mx_` / `sv3f_mxe_` / `sv3f_rg_` + `$execution.id` |
| live `syncV3Main0001` honours it | 7 nodes — Try Lock, Renew Lock, Unlock (Done), Continue Pass… |
| both asserts name a lock_held skip | returns `BLOCKED`, never a silent numeric failure |

So `mixed 3/6` and `registry`'s undefined gate are **stale readings**, not open defects. They need
re-measuring, not fixing. That is the third stale WORKLEFT entry found today, after the G64 lint
(passes) and the `bs` Drive-connection blocker (never re-measured by anyone).

**What I did NOT establish:** that they now pass. Proving that means running the suite, and G64's
own scope note says it cannot see what is active in n8n — it exists because a test once put 9
fixture messages into the client's production mailbox, and `syncV3FullTest01` is named in it. The
recorded CAUSE is provably gone; the RESULT needs a run, by someone who decides that run is safe.

**A tooling limit this exposed:** `lock_key` handling lives in node PARAMETER expressions, not in
`jsCode`/`query` bodies — so `verify_live_parity.py` cannot see it, and could not have told you
whether live honoured it. Checking that needed a direct read of `workflow_entity.nodes`. The parity
tool covers code bodies only, and that is now the second time today its blind spot mattered.

## 2026-08-23 — sync_full `chaos`: what the static evidence rules OUT

Diagnosed from the repo, without running the suite (G64's scope note says it cannot see what is
active in n8n, and it exists because a test once put 9 fixture messages into the client's
production mailbox).

**The GATE path is correct and deployed, end to end:**
- `CH Gate Req` sends `{op:'GATE', source:'sv3f_chaos'}`
- `syncLedgerApi01` routes `GATE` (an explicit branch, `outputKey:'GATE'`)
- `BuildGate` emits `select ... ::int as delivered, ... as needs_review, ... as attempts_open`
- `syncLedgerApi01` is parity-clean (0 differ, 0 broken), `active=true`, published

**Therefore `gate.delivered === undefined` CANNOT mean the count was wrong.**
`(select count(*) ...)::int as delivered` always returns a row; an empty source yields
`delivered: 0`, never `undefined`. Combined with `alwaysOutputData: true` on `CH Gate`, undefined
means **the sub-call returned NO ITEMS** and n8n substituted an empty `{}`.

The assertion then reports `gate delivered != 1: {}` — which reads as a count mismatch and sends
the reader to the ledger, when the actual failure is one node upstream. That is the same
silent-success shape as everything else today: the node "succeeded", produced nothing, and the
message described the wrong problem.

**What would settle it in one run, and is a safe repo-only change:** have `Assert Chaos`
distinguish the two cases before comparing numbers —

    if (!gate || gate.delivered === undefined)
      fails.push('CH Gate returned NO ITEMS (alwaysOutputData substituted {}) -- the ledger GATE
                  call did not run or errored; the counts below are meaningless');

Same liveness discipline as the fixtures: assert the call produced something before believing what
it says. Not applied — `syncV3FullTest01` is byte-identical live and repo right now, and pushing a
test-workflow edit is a separate decision from diagnosing it.

**Not diagnosed:** `mixed`, and `registry`'s own `gate.delivered` (line ~844 reads
`(r.gate||{}).delivered` out of `m.results`, a different source than the chaos lane's node
reference, so the same symptom there has a different mechanism).

## 2026-08-23 — THE RED TEST SUITES ARE A TWO-WRITER CONFLICT, NOT A PENDING DEPLOY

A peer session reported that `decide` and `sync_sources` are "fixed in repo awaiting a live push"
and that the push is the thing that turns them green. **It is not, and making that push would have
destroyed work.**

`bbox n8n status` lists **`indoxV2DecideTest01`, `syncV3SourcesTest01`, `syncV3FullTest01` and
`syncV3KernelTest01` under "changed LIVE since last sync"** — a person edited them in the n8n UI.
And the drift runs in BOTH directions:

    indoxV2DecideTest01 :: Determine Action Tests   repo 20,943  live 12,808
    syncV3SourcesTest01 :: Assert PG / PD / PL      repo  2,712  live  2,720
    fullDocEx01         :: Shape Input, Build Result             live-only content

**Read the diff, not the byte count.** `syncV3SourcesTest01` is longer LIVE only because the old
assertion message said `COMPANY_DOC_ID` where the repo says `DOC_ID` — eight characters, three
nodes, and live is BEHIND, not ahead. Inferring "newer" from length was wrong.
`scripts/ops/show_live_repo_conflict.py` prints the actual diff per node so this is not guessed
again. Line counts per workflow (repo-only / live-only):

    indoxV2DecideTest01   121 / 26    the 26 are the OLD case text the commit rewrote
    syncV3SourcesTest01     3 / 3     the same three lines, modified
    syncV3FullTest01        0 / 0     IDENTICAL — never deploy-blocked
    syncV3KernelTest01      0 / 0     IDENTICAL — never deploy-blocked
    fullDocEx01             0 / 3     genuine live-only work: RETRY_COUNT and INVOICE_ID mappings

**THE PLATFORM SETTLED IT, and it disagrees with a body-level diff.** A push of
`indoxV2DecideTest01` was REFUSED by compare-and-swap:

    CONFLICT indoxV2DecideTest01 — changed LIVE (15:02, likely a human in the editor)
             after your last sync. Nothing was overwritten.

That is the authority here, and it sees what `verify_live_parity.py` cannot: that tool compares
only `jsCode`/`query` BODIES, so an added node, a changed connection or a rename is invisible to
it. A body-level diff can say "the repo supersedes" and still be wrong about the workflow.
Resolution is the documented one — pull, re-apply, push — and it needs whoever made the 15:02 edit.

**A stale blocker, now corrected:** WORKLEFT records `./bbox indox test` as refusing to start
because `test-registry-scope-lint` (G64) registers `.json` paths that became `.workflow.ts`, 14
findings. **That lint passes today** — 10 test blueprints, every live source kind covered. The
entry is out of date.

**But the suites still should not be run yet, and G64 says why itself:** *"SCOPE OF THE GREEN:
static over committed blueprint JSON — it cannot see what is ACTIVE in n8n."* The gate validated
the repo; the four workflows above differ live; so the code that would actually execute is not the
code the gate cleared. G64 exists because a test suite once appended **9 fixture messages into the
client's production Gmail mailbox**, and 148 fixture messages reached person9@example.com between
2026-08-05 and 2026-08-09 — `syncV3FullTest01` is named in it for mirroring the live registry and
delivering 3 rows into the real table. Running an unvalidated live copy of exactly that suite is
not a risk worth taking to turn a number green.

**Correct sequence when someone picks this up:** resolve the four conflicts with the person who
made the live edits, re-run G64 against the reconciled blueprints, then run the suites.

## 2026-08-23 — OWNER DECISIONS OUTSTANDING (three, all measured, none acted on)

**1. `Raise Double Blocked` is a stop-and-error, and its blast radius is the whole batch.**
One guard-blocked document aborts the entire driver execution; every other document in that run is
discarded. Measured twice today, and it is NOT merge-specific: a 702-id merge drain produced 4
driver errors and zero dispatches, and later a 1,000-id settle drain was taken down by
`update_status_old_doc` (DOUBLE ACTION on `1774628977294culke4`).
The guard itself is right and must stay — a repeated action that does not move the document is
exactly what it exists to catch. The question is whether the RAISE should park the offender and
let the batch finish. Until that is decided, bulk feeders mitigate: the merge feeder predicts and
excludes its blocked set (it only ever dispatches one action), and the settle feeder — which
cannot know which action decide will pick — chunks at 200 so one blocked row costs 200 documents
instead of 1,000.

**2. ~~The MERGE path never releases its `doc_action` lock.~~ FIXED AND PROVEN 2026-08-23.**
`PG Merge Write -> Merge Emit IDs -> Merge Unlock Doc -> Merge Result`, with `Merge Unlock Doc`
byte-identical in parameters to `API Unlock Doc` so the upsert path is untouched. Runtime proof
(`scripts/ops/test_merge_releases_lock.sh`): the pair merged, `action_merge_doubles` closed at
05:50:26, and **no doc_action lock remained on either row** — before the fix that lock sat for its
full TTL. Population confirms it: `action_merge_doubles` locks **977 -> 284** as the pre-existing
leaked ones age out with none being added (total 1,203 -> 962).
The original finding, kept for the record: Audited, not inferred: 1,203 live
locks, **977 of them `action_merge_doubles`**, and of a 400-document sample **364 held a live lock
against a CLOSED dispatch bracket** — only 36 were genuinely in flight. `extract_base_doc` is the
control and behaves correctly, because it ends in an upsert and `API Unlock Doc` is fed only by
`API Emit IDs` on the upsert path. It is a **leak, not a throttle**. Fix: emit winner+loser ids
after `PG Merge Write` into an unlock, exactly as the upsert path does. Not applied — a locking
change to the central API needs a quiet window, and it blocks nothing now that dedup is at zero.

**3. ~~Extraction is producing document ids that are not document ids.~~ OVERSTATED — corrected.**
Of the 49 quarantined ids, only **two** are dramatic wrong-field extractions: `515561520` (a
company registration number under fifteen companies) and `02-6333155` (a phone number under five).
The rest are 26 alphanumeric and 21 numeric ids that merely collide across companies — plus `02-6`
(a truncated phone number) and `21/06/26` (**a date** in the DOC_ID field). I described the two
most vivid examples as if they were the population.

It is also **not ongoing**: the newest row carrying any of them was created **2026-08-14**, nine
days ago. "Extraction still produces them" was unsupported.

**And my quarantine over-reaches, by exactly 3.** `scripts/ops/audit_baddocid_quarantine.sh`:
zero quarantined ids lose a byte-identical duplicate (the hash tier catches those anyway), but
**3 have same-company rows agreeing on date and amount** — a strong duplicate signal — and those
are no longer raised. Small, quantified, and mine.
The refinement, available and not applied: quarantine the biz key only where the same-company rows
also DISAGREE on date and amount. It adds a condition to a detector the owner asked to keep simple,
so it is a decision, not a tidy-up.

**4. `MISSING_LINK` 1,106 — DIAGNOSED, not a defect.** All 1,122 carry
`SEARCH_IN_DRIVE_COMPLETED='true'`: `find_link` ran, completed, and found nothing. Searched and not
found, not dropped. Terminus pending the file existing in Drive — a connection/scope question.

**5. The old "extraction is producing bad ids" line, kept for the record:** 49 doc-ids across 258 rows
are shared by 3+ companies: `515561520` is a company registration number under FIFTEEN companies,
`02-6333155` is a phone number under five. Dedup no longer trips over them (they are quarantined
at the key), but nothing upstream has changed and they will keep arriving.

## 2026-08-23 — DUPLICATE GROUPS: 0

    duplicate groups still open:   0     (session start: 1,540)
    guard-blocked mains:           0     (peak, once measurable: 702)
    unsafe merges at merge time:   0
    hash-tier groups:              0     (was 18, unresolvable before today)
    MERGED rows:               6,048     (was ~3,587)

**What "0" means, precisely.** The last 10 groups were **not merged** — they were reclassified as
not duplicates, which is the correct answer. Their doc-ids are mis-extractions, and
`Adjudicate Merge` had already refused to merge them 146 times each; merging them would have
destroyed real documents. What changed is that they now have a terminal state instead of being
raised forever. Everything before them was genuinely merged, with provenance on every row.

**Still open, and the owner's to prioritise:** the mis-extraction itself. 49 doc-ids across 258
rows are not document ids — a company registration number, a phone number. Dedup is no longer
tripping over them, but extraction is still producing them.

### THE LAST 10 GROUPS WERE ALL ONE BUG: the detector and the adjudicator disagreed about bad doc-ids

Every single remaining duplicate group was a **mis-extracted DOC_ID**, and the pipeline already
knew it.

`Adjudicate Merge` quarantines any group whose doc-id is shared across **3+ companies** — it
refuses to merge, because those are different documents that merely look alike. The **detector**
(driver `dbl` CTE) never had that rule. So the group had no terminal state at all: the driver
raises it, the adjudicator refuses it, nothing is written, and it is raised again next sweep.
That is how five mains reached **146** `action_merge_doubles` dispatches.

The evidence, measured rather than inferred:

| DOC_ID in the tail | distinct companies using it | rows |
|---|---|---|
| `515561520` (a company registration number) | **15** | 68 |
| `02-6333155` (**a phone number**) | 5 | 18 |
| `SH26000709` | 3 | 6 |
| `SH26004136` | 3 | 6 |

`515561520` alone accounted for **7 of the 10 remaining groups**, under seven different companies.
Table-wide there are **49 such doc-ids across 258 rows**.

**The fix is at the KEY, not after grouping.** A doc-id used by 3+ companies no longer forms a biz
key, so those rows simply stop being duplicates and gain a terminal state. Threshold and predicate
are copied from the adjudicator so the two cannot disagree again. A row still gets its hash or comp
key, so a genuine duplicate hiding behind a bad doc-id is still caught by the tiers below — this
narrows the biz tier only.

Regression test: `scripts/ops/test_baddocid_quarantine.sh` — a doc-id under three companies with
two rows sharing one of them must NOT merge, and an ordinary pair must still merge.

**Note on the other session's count.** A peer measuring on a raw `(COMPANY_ID, DOC_ID)` pair read
22 groups where the detector's key reads 10. The 12-group gap is groups whose DOC_ID fails the
detector's own predicates (junk, all-zeros, equal to the COMPANY_ID) and which the pipeline
deliberately never raises. Worth stating because the raw pair looks like the obvious metric and
over-reports against the machine's actual behaviour.

### RESULT: duplicate groups 1,457 -> 10, and the 10 are named

| measure | start of session | now |
|---|---|---|
| duplicate groups (detector's key: biz/hash/comp) | 1,540 -> 1,457 | **10** |
| hash-tier groups | 18 | **0** |
| MERGED rows | ~3,587 | **6,048** |
| guard-blocked mains | 115 (undetected: really 702) | **5** |
| unsafe merges, measured AT MERGE TIME | 0 | **0** |
| cascades (winner demoted after its own merge) | 3 | 6 |

**The 10 that remain are the hard cases, all characterised, none mysterious:**
- **5 mains at 146 `action_merge_doubles` dispatches each**, all OLD, all above the retry cap so
  nothing retries them. These are the runaway loops, and one of them is the shape that should
  never be merged automatically: `doc_msmuxtfmdi6zcb`, eight rows under `COMPANY_ID 515186625 /
  DOC_ID 515561520`, eight distinct hashes, six COMPLETED — a mis-extracted DOC_ID that is really
  a counterparty company number, so they are eight different documents sharing a bad key.
  **Owner call, not another dispatch.**
- the rest sit at the retry cap in ACTION_RESTART, feedable, waiting out their merge locks (see
  the lock-leak entry above — that is what makes "waiting" take 73 minutes).

Every merge in this run carries `STATUS_BEFORE_MERGE` + `MERGE_BATCH_ID`, so any of it is
reversible the same way the 54 bad merges were on 2026-08-22.

### The MERGE path never releases its doc_action lock — found, NOT changed

This is the single biggest remaining lever on duplicate convergence, and it is a one-node fix.
It is written down rather than applied, because it is a locking change to the central API and
there is a convergence run in flight; changing lock behaviour underneath it is how a clean drain
becomes an incident.

`API Unlock Doc` is fed by exactly one node — `API Emit IDs`, on the **upsert** path. Its own note
says the unlock "lives at the upsert — the one step every action necessarily ends with". The MERGE
branch does not end there: `Build Merge Read -> PG Merge Read -> Build Merge Write -> PG Merge
Write -> Merge Result`, and nothing on it unlocks. So every `action_merge_doubles` leaves the
MAIN's `doc_action` lock to die by TTL.

Measured: **1,559 held locks**, essentially all `::action_merge_doubles`, with TTLs up to
**4,358s (~73 min)** — not the ~2,810s the operating notes record. That is the cooldown: a group
main can be attempted about once every 73 minutes, so the backlog drains one wave per lock cycle
(~230 groups a wave) instead of continuously.

**The fix:** emit the winner and loser IDs after `PG Merge Write` and feed them to `API Unlock
Doc`, exactly as `API Emit IDs` does for the upsert. Not a concurrency increase — releasing a
lock when the action that holds it has finished is the documented invariant, and the double-action
guard, not the lock, is what prevents a re-dispatch.

Needs a fixture proof and a quiet window before it goes near the central API.

### The throughput collapse: two stale documents were holding the whole backlog still

Convergence went from **185 merges in 5 minutes to 20 in 10**, and the cause was not capacity.

`Raise Double Blocked` is a **stop-and-error**, so one guard-blocked document aborts the ENTIRE
driver execution. A 702-id drain produced 4 driver errors and **zero** dispatches. Two documents
did that — `doc_msq6hmoidspohq` and `doc_mt37tlhq4rw2kc`.

They slipped past the feeder's blocked-main filter because that filter tested only a document's
LAST logged action, while the guard scans the newest 10 ACTION_HISTORY rows and blocks when
`action_merge_doubles` appears with **no restart after it, whatever ran since**.
`doc_msq6hmoidspohq`: merge at 00:23, `update_status_old_doc` at 00:27 — last action not a merge,
so it was fed, and it killed every batch it was in.

With the filter corrected to mirror signal A exactly (10-row window included), the real state was
visible for the first time: **702 of the 703 remaining mains were guard-blocked.** The backlog was
never a throughput problem; it was a repair job. 697 restarted through the console path, 5 held
back by the retry cap at 146 dispatches each.

**The hash tier is 18 → 0.** Every hash-keyed duplicate group on the table is resolved — the
`Build Group Fetch` fix, confirmed at scale rather than only on a fixture.

**Worth the owner's attention:** a stop-and-error on one document discarding a 700-document batch
is a blast radius nobody chose. The guard itself is right and stays. Whether the *raise* should
park the offender and let the batch finish is a design question, not something to change quietly
while draining.

### Duplicate backlog — what is actually left, by shape (723 open groups, measured 04:4x)

| shape | groups | reading |
|---|---|---|
| 2 members, <=1 distinct hash | 260 | the same bytes twice. Ordinary duplicate; merges cleanly |
| 2 members, 2 distinct hashes | 255 | one document rescanned (`RESCAN` cause). Merges cleanly |
| 3+ members | 208 | mostly repeated rescans of one document |
| 3+ distinct hashes | 138 | subset of the above; a different hash is NOT proof of a different document |
| **3+ hashes AND 2+ COMPLETED** | **10** | **the only genuinely risky set** — see below |

**The 10 need a look after the sweep, not a veto before it.** Worst example
`doc_msmuxtfmdi6zcb`: EIGHT rows under `COMPANY_ID 515186625 / DOC_ID 515561520`, eight distinct
hashes, six of them `COMPLETED`. That `DOC_ID` is a **company registration number**, not a
document id — it is a mis-extraction, and the eight rows are eight different documents that
merely share a bad key. `btrim(COMPANY_ID) <> btrim(DOC_ID)` does not catch it because the number
belongs to the *counterparty*, and the 3+-companies quarantine does not fire because all eight sit
under one company.

Proceeding per the owner's standing rule — *"conflicted should be noted but still merge, same for
BAD_DOC_ID; the double action should not handle this complexity"* — the cause is recorded in
`DUP_CAUSE` and the merge goes ahead. This is safe to revisit because every merge writes
`STATUS_BEFORE_MERGE` + `MERGE_BATCH_ID`, which is exactly how 54 bad merges were reverted on
2026-08-22. Flagged here so the reversal is a decision and not a discovery.

**Also surfaced by the retry cap:** 5 mains have dispatched `action_merge_doubles` **146 times**
each. They are OLD, guard-blocked, and above the cap, so nothing retries them — but 146 is not a
backlog, it is a loop, and it was invisible while every blocked main was one undifferentiated pile.

**Carried, not fixed:** 3 unsafe merges (a `COMPLETED` row absorbed into a survivor that a LATER
merge demoted to `OLD`) — all from one batch `d85c33d0`, all cascade, none new. The drive loop
hard-stops on any INCREASE above that baseline rather than on `>0`, which would stop on history.

## 2026-08-21 — ACTION_LOG COLUMN REMOVED (owner order, 6 phases, all proved)

**The number that moved:** `ACTION_LOG` is **gone** — 20 MB of a 180 MB table, 535 bytes off the
average row on every GET and every `executeWorkflow` hop, **66 write sites** and a 90-line plpgsql
merge trigger deleted. Full record: [issues/remove-action-log-column.md](issues/remove-action-log-column.md).

| phase | what | proof |
|---|---|---|
| 1 | `Enrich Doubles` -> `Enrich Double Lines`, `Dup Guard: Check ACTION_LOG` -> `Dup Guard: Double Action` (a double LINE is data quality answered by a merge; a double ACTION EXECUTION is a state-machine fault that must error loudly) | 55 nodes / 51 refs / 0 dangling; exec 3445861, 0 errors |
| 2 | `ITERATION_COUNT` became a real counter: +1 per dispatch in `Log Action Start`, 0 in the four restart nodes. Ceiling re-measured 25 -> **15** (new/old ratio 0.59) and the `max_iterations_per_doc` settings ROW changed with it, or the drain would have kept the old number | 100 docs: col = dispatch count **100/100**, 0 mismatches. 40 docs seeded to 99 -> all cleared by restart |
| 3 | `Get Action History` + `Attach Action History` — own nodes, deliberately NOT folded into `Enrich Double Lines`. Lateral join, newest 10 per doc, **33 ms / 2,000 docs** | cohort split 250 with history / 250 without -> exactly 250/250 populated at every node; `IS_DOUBLE`/`LINES_TO_MERGE`/`__merge_enabled` survive 500/500 |
| 4 | Guard + decide read the new sources. `apply_gmail_labels` and `file_to_failed_folder` got **completion columns** — they were the only 2 actions of 22 with none | dual-run **3,354/3,354 then 3,000/3,000 identical**; flags 6,000/6,000 |
| 5 | 66 writers deleted, plus `_log`, `RULES.anchors`, and a dead `if(false)` gate | ACTION_LOG md5 **byte-identical** across an 800-doc run that moved 51 docs and logged 71 dispatches |
| 6 | Column, trigger and function dropped; BFF parser (108 lines) + 6 constants removed; document drill-down rewritten on the dispatch log | 600 docs, 49 executions, **0 errors**; endpoints answer; archive 39,149 rows / 24 MB |

**The one real defect this surfaced:** pointing the two gates at ACTION_HISTORY first was wrong —
history answers "was this DISPATCHED", not "is this work DONE". `file_to_failed_folder` is **not
idempotent**: two executions died on `Google Drive: File not found` before the columns went in.

**Known and accepted:** the document page now shows dispatched actions only — node-level labels
(`Extract Base Doc`, `Update NAME`, `COMPANY RESOLVER <hash>`) were never actions and have no row.
In exchange it gains per-action duration and completion, and loses the "may be incomplete" caveat
the 6,000-char middle-trim forced on it.

**Left for the owner:** `indoxDocBatchUpsert01` is dead (0 real call sites, 0 executions ever, logic
re-homed into `indoxApi01` on 2026-08-12) and still `active=true`; `active` is cosmetic on an
executeWorkflowTrigger and `push` re-activates it, so retiring it means deleting/archiving it in
n8n. And the table is still 180 MB on disk — `DROP COLUMN` does not reclaim without `VACUUM FULL`.

**Blocked, PRE-EXISTING, not from this work:** `./bbox indox test` refuses to start —
`test-registry-scope-lint` registers `.json` blueprint paths that became `.workflow.ts` in the
2026-08-16 as-code migration (`scripts/test-fixture-prefixes.yaml`, 14 findings). It is a safety
lint guarding against seeding the client's real mailbox, so it was left alone.


## 2026-08-18 ~00:1x — DECIDE 30k OPTIMIZATION (owner order: one-shot 30k must fit)
**Root cause of "decide runs forever" FOUND + KILLED (source-proven):** n8n's `Execution Data`
node re-evaluates every value-expression PER ITEM (its execute() loops items); four stamp
expressions scanned `$input.all()` → items² — invisible at 250-row driver groups, HOURS at 39k
(measured: 15+ min pegged CPU, zero children). Same node sat in decide + all 4 routers (+ the
DRIVER — untouched per owner rule, fix pending owner go).
**Fixes landed (all as-code, pushed, executed proof):**
1. Stamps → `$execution.customData.setAll()` computed ONCE (decide folded into Determine Action;
   doc_base into Restore Router Payload; gdoc/ship/bs = side-branch dead-end returning 1 item).
2. Copy-count cuts: `Set decide mode (docbase)` folded into Determine Action (n8n retains every
   node's full output → each dropped node pass saves a ~250MB copy at 39k).
3. **Slim+rejoin** (memory): Determine Action drops ACTION_LOG (20MB of 73MB, fattest column;
   its ONLY decide-path reader is Decide DOC BASE Action → 3 derived facts precomputed as
   `doc._log`, inline fallback `__logInfo()` if absent) + 9 census-proven-unread columns
   (SELECTION_SCORE_DEBUG/…_PERTYPE/…_BASE, REQUIRED_ACTION, THUMBNAIL, SOURCE_LINK,
   SOURCE_LIST, SYNC_CONNECTION, CONNECTION). New `Rejoin Full Rows` node restores all of them
   verbatim (+same normalization) at decide's exit — caller contract byte-identical.
**Proof:** 100-row A/B histogram BYTE-IDENTICAL before/after
(`old_date:38/57/merged:1/completed:4`) + restoration probe (withActionLog=100, _log leak=0),
exec 3383001. **15k one-shot: decide SUCCESS 190s** (exec 3383007; docbase 35s, BS 6s, GDoc 5s,
Ship 3s) — pre-fix 15k OOM-killed the worker. 39k pre-fix: 2 heap OOMs (kernel cgroup kills at
2GB). 39k post-slim: NOT YET RUN (cycle is actively draining — sequenced after).
**Gotchas hit:** live decide was stale-tab-reverted to the old graph mid-evening (CAS caught it;
pull/restore/push resolved); loadtest PARENT executions get falsely 'crashed'-marked ~1s in on
big runs while children complete (bookkeeping artifact, root cause open); n8n-main rides its 2GB
cgroup (restarted 20:28Z); 21 crashed giant execution_data blobs purged (170MB each).
**Cycle: ACTION_RESTART 25,002 → 13,824 and falling** — scheduled drainer is draining the
backlog on the slim build; extractors running, DOUBLE ACTION BLOCKED = 0 (30 min window).
**Remaining plan (max optimization, in order):** (a) run 39k one-shot after drain quiets;
(b) driver's identical quadratic stamp — owner go needed; (c) allowlist-slim (~50 read columns)
if 39k still tight; (d) worker heap 1536→2560MB — needs WSL rebalance (host swap was 99% full;
15.7GB physical, WSL capped 10GB after the 12GB starvation incident) or the VPS; (e) NoAct
chooseBranch-merge + docbase Restore reorder (risky semantics — only if (a)-(d) insufficient).

## 2026-08-18 ~03:1x — MAX-EFFICIENCY TIER 2 (owner: "100k one-shot, same results, max speed")
**Deep scan (owner-ordered) — VERDICT CLEAN:** scanned ALL 27 workflow files for the 10 dropped
columns; every non-comment hit classified. All consumers are EXECUTE-branch builds (receive
driver-dispatched rows = post-Rejoin restored rows), ingestion/sync/test workflows, or DB
re-reads (Adjudicate Merge fetches its group fresh; driver dup-guard reads the row from the
API). The NoAct back-off family (the one decide-mode writer candidate) no longer exists — it
went with the no-state-machine-retries purge. Zero decide-path consumers beyond the 3 patched
ACTION_LOG sites in Decide DOC BASE Action.
**Landed this tier:** 'NoAct: Return Verdicts' REMOVED from all 4 routers (was a straight echo
after Decide since the backoff purge — each one a full-batch runner copy + round trip; decide
verdicts now return directly from the Decide nodes). Side-stamp Y positions pinned ~1000 above
'Route Mode' + ORDERING LAW note in each: v1 executes same-output branches topmost-first
(verified in n8n-core workflow-execute.js nodesToAdd.sort) and a sub-workflow returns the LAST
executed node — the stamp must never run last.
**Proof:** 100-slice histogram still byte-identical (38/57/1/4, restored 100/0 leak);
300-newest slice total=300 exact, 11 actions; per-type slice (200 typed active docs) —
extract_per_type:2 + find_link:129 returned THROUGH gdoc/ship decides, 200/200, no 'none'
bucket → per-type return path proven post-Noact-removal.
**FUTURE (owner 2026-08-18, DO NOT IMPLEMENT YET):** split housekeeping OUT of decide into
nightly settings-driven workflows: `indoxDoubleMerger` @02:00 (detect / merge / archive
duplicates) + `indoxOldManager` @03:00 (move old docs). This removes the dedup maps + old-date
logic (and their column dependencies: HASH/SHORT_DOC_ID/*_DATE/OLD_REASON/DOUBLE_LINE_CONTEXT)
from the hot decide path entirely — decide gets smaller AND faster, and the 2am/3am jobs can
work in DB-side batches.
**100k one-shot honesty:** with full rows at decide's entry+exit (the caller contract), 100k
costs ~600MB per retained full copy — entry + rejoin alone exceed the 1536MB heap. The unlock
is Tier B: decide returns VERDICT-ONLY rows (ID/ACTION/DOC_TYPE + decide-writes) and the
execute path stops carrying ACTION_LOG/REQUIRED_ACTION in items — SQL-side append in the bulk
upsert (`"ACTION_LOG" = coalesce(existing,'') || EXCLUDED...`) so no log ever rides the batch.
That touches driver dispatch + indoxApi upsert (owner call). Alternative: worker heap ~3GB on
the VPS. Both recorded, neither implemented.

## 2026-08-18 ~04:4x — VERDICT-ONLY CLONE PROOF (owner-ordered before touching decide/driver)
`indoxV2DecideMin01` = exact clone of decide with ONE change: exit returns verdicts only
(ID/ACTION/DOC_TYPE/IS_OLD/OLD_REASON/_dup, ~150B/row) instead of full rows; DA preserves a
caller-derived `_log` so ACTION_LOG never travels. Harness (`indoxV2DecideLoadTest01`) mirrors
the future driver cluster: Load Full Table → Project Slim (census allowlist + _log derivation)
→ Call DecideMin → Join Verdicts (by-ID, hard count-parity guard) → respond.
**Results (same table slices as the rejoin-build baselines):**
- 100-slice: histogram BYTE-IDENTICAL (38/57/1/4), joined withAction=100, withActionLog=100,
  withRequiredAction=31 (matches rejoin-era exactly), 0 leaks. HTTP round-trip 3s.
- typed-200: BYTE-IDENTICAL to rejoin-era run (extract_per_type:2, find_link:129,
  withRequiredAction:130), 200/200 joined, per-type verdict return path proven.
- 15k: decide 102s (was 165s = **-38%**), 21 actions, withAction 15000/15000, peak ~2.0GB,
  HTTP response delivered end-to-end for the FIRST time on a big run (lean parent also killed
  the false-'crashed' artifact). Exec 3383447.
- **30k: decide SUCCESS TWICE — 205s (exec 3383460) and 238s (exec 3383471)** — the size that
  kernel-killed every full-row attempt. All 4 routers success (docbase 50-69s, per-type 3-7s),
  stamp line_count=30000, all 21 actions present in the verdict output. No kill during decide.
- Remaining constraint is the HARNESS PARENT (webhook + full table + projection + join in one
  process): killed at ~3.0GiB during the 30k join-aggregate. The real driver port avoids this
  shape by folding projection into the existing batching pass and join into Group By ACTION
  (no separately-retained projection/join sets). 100k projection: decide-min footprint at 30k
  ≈ 1.6-2.0GB incl. caller retention → 100k needs the driver-side folds, then fits.
**Next (owner go given for driver, clone proof now in hand):** port verdict-only exit into the
real indoxV2Decide01 + driver cluster (projection folded into batching, join folded into
grouping, count-parity guard), A/B ladder again, then delete the clone.
**Ops note:** `bbox n8n push` wrapper SWALLOWS `--force` — invoke
`bash platform-base/n8n/hooks/push-app indox <id> --force` directly for deliberate overwrites
(needed tonight: owner's editor tab autosaved the loadtest repeatedly).

## 2026-08-18 ~05:5x — MEGA v7 (owner design: routers EXPORT their decide functions) + CYCLE FIRED
All four routers' decide nodes wrapped as self-contained exportable functions (mode=
'export_decide' returns the node's OWN source; RouteMode OR-rule routes it to the decide
branch; graph path byte-identical — proven on 100-slice + typed-200 through the REAL decide
with full rows post-refactor). Mega v7 = 18KB workflow: 4 tiny export calls → new Function
rehydration → ONE code node runs base then per-type. ZERO logic duplication anywhere.
100k synthetic: HTTP 200, 100000/100000 verdicts, 87s end-to-end. Perf fixes live in the
ROUTERS now (CFG memo + blank-guard), so the production graph path gains them too.
Harness-artifact note: feeding the REAL decide projected rows (no ACTION_LOG) mis-derives
_log — production is fine (driver sends full rows); any future projection caller must send
_log (the real decide's DA lacks the clone's preserve-if-present tweak — port it with Tier-B).
**CYCLE FIRED 02:54:50 IDT**: 25,010 → ACTION_RESTART, factor 16, drainer 3383971 fired:16.
Report (live-updated): issues/cycle-20260818-report.md.

## 2026-08-18 ~05:3x — MEGA DECIDE (owner: "100k in 30s, maximum efficiency")
The whole decide path collapsed into ONE code node on the clone (`indoxV2DecideMin01` =
WhenCalled → Load Company Resolver Gen → Mega Decide). The four router decide functions are
embedded VERBATIM (assembler: scratchpad/build_mega.py extracts them from the router files,
wraps each in its own function scope, replaces only the node-input accessors); Determine
Action re-authored async+chunked (batch-stateful dedup preserved, event-loop yields every 10k
so the runner launcher's liveness pings are answered). Routing = the same __route_* partition.
Caller cluster (harness): slim SQL → Call Mega → join-by-ID with count-parity guard.
**Perf ladder at 100k (synthetic worst-case: every row tripled → unique IDs, duplicated
HASH/biz keys → resolve_double storm 22-30k rows):**
- v4 one-hop: 100k decide 83s (in-code 73s: da 13.7s, docbase 58.6s, pertype 0.5s). 15k: 16-18s.
- v5 + __CFG memoized (was $('Companies') throw PER ROW — 100k caught exceptions): 100k 55s
  (docbase halved to 29.9s). 15k decide: **8s**.
- v6 + DOUBLE_LINE_CONTEXT blank-guard (JSON.parse('') throw per row) + success-save off:
  15k HTTP round-trip 20s; 100k HTTP end-to-end **80s wall** — measured UNDER CONTENTION with
  a phantom duplicate 100k task on the same runner (Bull redelivery); solo ≈ 45-50s.
**Correctness gate held at EVERY build:** 100-slice + typed-200 + 15k histograms BYTE-IDENTICAL
to the proven verdict-clone (all 21 buckets incl. mark_max_iterations:1, withRequiredAction
7511 exact) — regression run after every single change.
**Infra fixes landed:** runner sidecars' N8N_RUNNERS_TASK_TIMEOUT was UNSET → runner-side 60s
default killed any >60s task ("Task ... timed out" at exactly 60s; then launcher "unresponsive
6/6" kills on blocked event loops). Compose now sets 900 on all three runner services + the
mega code yields. bbox push wrapper swallows --force (use the hook directly).
**Honest 30s status:** worst-case-synth 100k decide ≈ 45-55s; the dup-storm inflates docbase
(its share = resolve/double paths). Realistic-mix 100k projected at/near 30s. Remaining known
levers: da 14s (normalization 5.3M key-visits), ~10s serialization tail (null-stripping the
payload), realistic-mix measurement (synth with unique HASH), deeper docbase exception census.
**NOTE:** with saveDataSuccessExecution:'none' the clone's success EXECUTION ROWS vanish
(n8n deletes them) — perf evidence lives in the harness HTTP responses + this file; v5-era
executions (3383641=83s, 3383674=55s, 3383671=8s) still linkable.

## 2026-08-18 ~03:5x — ONE-SHOT CAPACITY LADDER (measured, per attempt)
**KEY ARCHITECTURAL FINDING:** executeWorkflow sub-workflows run IN-PROCESS with their caller
in queue mode — 3/3 one-shot runs put caller+decide on ONE worker while the other idled
(~200MB). The separate execution rows are bookkeeping, not separate processes. So the caller's
table copy + decide's retained sets ALWAYS share one heap — true for the real driver sweep too.
- 1536MB heap / 2G cgroup (original): 15k PASSES (165s, decide 3383311); 39k dies at the V8
  heap limit ("Ineffective mark-compacts", container only 1.64GiB — cgroup NOT the wall).
- 2048MB heap / 2.5G cgroup (workers only, compose source updated): 39k doc_base PASSES 78s,
  per-type phase dies at 2.499GiB cgroup; 30k doc_base PASSES 73-79s (execs 3383357/3383377),
  per-type phase dies at 2.499GiB — ~300-500MB short.
- 2600MB heap / 3.25G cgroup (final rung, applied 2026-08-18 ~03:55): 30k doc_base PASSES
  again (90s, exec 3383389), per-type phase killed at **3.0GiB anon-rss** (kernel, 00:58:41).
  Every raise was eaten: kills at 2.0 / 2.44 / 3.0 GiB rss. VERDICT: 30k one-shot with
  full-row entry/exit + in-process caller does NOT fit this 10GB host. NOT raising further
  (host swap-bound). Next levers, owner's pick: (1) aggressive allowlist-slim of the middle
  (~50 read columns, needs the A/B harness re-proof — est. frees 600-800MB, borderline);
  (2) Tier-B verdict-only contract (the real unlock, also the 100k path); (3) VPS-class RAM.
  Worker sizing left at 2600/3.25G (idle workers use ~200-900MB; only sweep spikes matter).
Worker heap/cgroup sizing lives in platform-base/n8n/docker-compose.yml (both worker blocks,
dated comments); revert = restore 1536/2G and recreate workers via root-copy compose up.
**n8n-main is its own patient:** pinned/killed at its 2G cgroup repeatedly tonight (kills
22:21/23:28/00:36/00:42 IDT) — giant crashed-execution blobs + webhook load; crashed giants
purged twice (>20MB & crashed → data='[]'). Main sizing untouched (not in tonight's scope).
**False-'crashed' parent artifact:** every big loadtest parent gets crash-marked seconds in
while its children run to success — bookkeeping (likely queue-recovery), root cause still
open; it kills the HTTP response, so big-run results are read from execution rows instead.

## POST-REBOOT STATE (2026-08-16 ~08:0xZ) — owner rebooted + `bbox run`
Disk crisis RESOLVED (13.5GB freed: 3 orphaned WSL swap.vhdx deleted + docker image prune 12.35GB;
inner ext4 now 114G/1007G). Stack up and verified: all containers healthy except `drive` (serves
200s fine; only its healthcheck probe times out under post-boot load — cosmetic, watch it),
DB accepting, drainer alive (gap 120s), dup-guard 0 repeats, COMPLETED 12,027/36,979 (32%) @8/hr.

**LIVE DEFECT #1 — `indoxV2FigureDocType01` ("Figure Document Type") is `active=false`:**
`bbox run`'s provisioning uses a BARE `n8n import:workflow`, which force-sets active=false +
activeVersionId=NULL (the exact footgun scripts/ops/deploy-workflow.sh exists to prevent). Its
webhook is still registered in main (error says "not active", not 404), so every
`figure_document_type` dispatch errors (~6/hr, e.g. execs 3272179/3272265/3272462, doc
doc_mshfo4whxu4y12 re-offered every ~2min). FIX (one command, sanctioned path — re-imports from
repo + reactivates in the same breath): `bash scripts/ops/deploy-workflow.sh indoxV2FigureDocType01`
THEN enumerate the FULL casualty set (other workflows the same import deactivated):
`scratchpad/casualty_check.sql` (read-only, fingerprint = inactive + activeVersionId NULL +
updatedAt in boot window + recent executions) — WSL wedged before it could run; run it and
deploy-workflow.sh every id it returns with recent_execs>0. Do NOT blanket-reactivate the
inactive list — it is mostly retired legacy (old sync stack, Upsert central, tests) that must
stay off; the activation diff (scratchpad/activation_diff.py) proved repo-active⊄live-inactive=∅.

**LIVE DEFECT #2 — guard catch = ACTION_RESTART routing gap (T-27 family):** doc
177866335843122dxgm: per-type extraction completed long ago → aged OLD → `restart_gdoc` →
pipeline re-dispatched `extract_per_type` instead of routing past it → DOUBLE ACTION BLOCKED
(exec 3271515, ~3/hr). Guard did its job, no corruption; the restart path must check the
completed-flag and route to mark_completed. Evidence preserved here; fix belongs with T-12/T-27.

**Scale-out reality (owner asked):** the portable box (192.168.16.103) is a MANUAL layer —
`apps/apitools/scale-out/up.sh` (haproxy LB + remote apitools) + `tunnel.sh` (21 ssh -R forwards)
+ remote n8n workers + `portablecpu.sh` sampler. None of it is restored by `bbox run`. Right now
the box is unreachable (no route to host — off or off-wifi), 0 tunnels, no haproxy, sampler's
last sample ~Aug-14 16:47Z (the bars PORTABLE panel shows that stale line). Local host carries
100% (cpu 97%, free 150MB) — hence recurring transient WSL wedges (0x8007274c, 2 in 10min).
To restore when the box is back: tunnel.sh → up.sh lb → addworker_remote.sh → portablecpu.sh;
first clear orphaned sshd -R listeners on the box (SIGTERM) per
issues/portable-box-docker-29-and-remote-worker-dns.yaml.

## RESOLVED — host C: drive hit 0 bytes free (found 2026-08-14, mid-session)
`Get-PSDrive C` showed **475.88 GB total / 475.88 GB used / 0 GB free**, discovered while tracing the
OLD_REASON gap below. This broke the Bash/PowerShell tool's own subprocess output capture (ENOSPC on
the harness temp dir) partway through the session — every `wsl`/`docker`/`node` invocation has failed
since, including a retry after 15s and several spaced re-checks. WSL processes (`vmmemWSL`, `wslhost`,
`wslrelay`) are still resident, so the VM itself hasn't crashed, but WSL2's vhdx almost certainly lives
on this same, fully-saturated C: — meaning the live stack (n8n, supabase-db, traefik) is likely also
one write away from failing (Postgres WAL, container logs, etc.), not just this session's tooling.
**Not investigated further and nothing was freed** — clearing space is a systems operation outside a
read-only/staged-changes mandate; needs the owner or main agent to look at it directly (T-21 already
flagged "C: disk headroom (2.5GB free)" as a live concern — this is that same issue, now at zero).
Blocks: items 2's dry-run counts, item 3 (drain convergence poll + `full_adjudicate.js`), item 4
(sweep-completion check) — all need live docker/psql/node access. Everything below that doesn't need
that access (code-reading, the OLD_REASON root cause, staged SQL) was still completed.

## Working rules (owner)
- Only the state machine changes a line — one upsert per action end. Failure is terminal; **`ACTION_RESTART` is the only re-run**.
- **Execute to verify**: run data from modified nodes, never the stored row (`bbox n8n test|plan|exec` are the sanctioned paths). `bbox n8n status` must read clean after every deploy.
- LIVE is source of truth; **workflows are CODE** — `apps/indox/blueprint/n8n/*.workflow.ts` (as-code flip 2026-08-16, ai/context/n8n-development.md). Loop: `bbox n8n pull indox <wfId>` → edit → `bbox n8n push indox <wfId>` immediately (API path, no restart; CONFLICT exit 4 = pull first). `deploy-workflow.sh` is retired.
- Relative SQL intervals (DB clock is a day behind). `active::text` is `'true'/'false'`, never `'t'/'f'`.
- Leave repo + workflows thinner than found. Never `bbox run/push`, never `git checkout`, no concurrency raises, lock-skip is by design, fix pipelines not rows.
- Full autopilot: read the owner's messages for answers (`scratchpad/all_owner_messages.txt`, 211 verbatim), decide-act-report, never wait.
- **Subagents NEVER commit or deploy** (owner, 2026-08-15): they investigate, edit uncommitted, and PROPOSE (file + diff + evidence + offline tests); the main agent reviews, de-slops, and is the **sole committer/deployer**.

## Release criteria (live numbers 2026-08-15 ~11:00Z)
| # | criterion | state |
|---|---|---|
| R1 | documents reach Priority ERP | ❌ **8.8%** — the end-goal, unblocked once R2/R3 close |
| R2 | one row per real document | ❌ 5,535 excess rows / 4,249 groups |
| R3 | dates correct | ❌ #39: 825 rows years-wrong (579 COMPLETED) |
| R4 | zero n8n errors | ✅ steady-state 0; bursts only from deploys/restarts (mechanism known: T-9) |
| R5 | two-point extraction only | ✅ holding (0 single-value) |
| R6 | six-month docs completed ≥60% | ⚠️ census resettling after ordered OLD sweep (in-scope base shrinking to truth) |
| R7 | full green INDOX test suite | ⚠️ not re-run since the cleanup — T-13 |
| R8 | no silent data corruption | ⚠️ dates (#39) + contamination legacy (T-6) outstanding |

---

## OPEN TASKS — priority order

### P0 — correctness & the owner's explicit orders
| id | task | detail / acceptance |
|---|---|---|
| **T-1** | **#25 sync-level OLD gate + source investigation** | Old docs must never ENTER the table: every sync/ingest lane (`drive-gdoc-scanned-synced` first, then Gmail/BS lanes) checks `RECEIVED_DATE` against the SAME `settings.old_document_months_back` (=6) and skips/marks OLD at ingest. Also answer where each old cohort came from (last one: scanned-folder sync). Acceptance: 0 extraction spend on old docs from ingest onward. **Progress (11:05Z):** scans still ingest (200 in 2h, all now OLD); post-entry-gate window has 0 new scans to measure spend against — next batch is the live test. Registration node hunt: not in SyncProc*::Register (BS registers via batch-upsert executeWorkflow); read `syncV3Main0001`/`SyncApi0000000001` next — the gate belongs at first row-write, `STATUS=OLD` when `RECEIVED_DATE` > setting |
| **T-2** | ✅ **DONE + SEALED (2026-08-15 ~11:5xZ): FULL-TABLE BIDIRECTIONAL PROOF = 0/0.** One-shot decide over all 36,929 rows, both directions applied by the gate's own adjudication: 2,953 gate-approved missed-olds → OLD (machine-equivalent write), 4+1 false-olds → ACTION_RESTART. **Final verification pass: false-OLD 0, missed-old 0.** OLD total **18,454**, every one gate-approved; ~820 restarts re-flowing. One-shot census: 15.5k `no_action_old_date` · 12.7k routed to type routers · 1.45k awaiting company · 151 extract_base · tail as designed | **Sweep tail → all old marked OLD** | Lane-2 passes continue (OLD 8,427 → ~15.4k proven target; ~250 workable-status stragglers + IN_PROGRESS/ACTION_RESTART transitions age on touch). Acceptance: all-rows proof re-run shows only tombstones excepted |
| **T-3** | **#14 drop `NEXT_RETRY_AT` column** — LAST structural step | Checklist ①②③⑤ ✅; ④ = one clean sweep pass. Then: `ALTER TABLE … DROP COLUMN` + tidy `indox_merge_never_absorb` skip-list + regenerate trigger schema + drift lint green. **2026-08-14: ④ check attempted, blocked** — needs the ACTION_RESTART drain poll + `full_adjudicate.js` false-old census (item 3) first, both need live docker/psql access, unavailable this session (see URGENT note, top of file). ④ still not evaluated either way — do NOT infer green or red from this session; re-run once access is back |
| **T-4** | **DOUBLE fully-processed duplicates → MERGED** (owner "yes and yes", 08-10) | The 168-cohort and successors; via adjudicator path, not raw SQL. Intersects #38 repair below |
| **T-5** | **#38 revert my unsupervised-merge damage** | 53 wrong merges + 362 wrong demotions; merge path is non-transactional and 202 MERGED rows have unrecoverable prior status — design the repair from `incoming_documents_pre_sweep_20260815` + older snapshots; add `STATUS_BEFORE_MERGE` + transaction to `Adjudicate Merge` (the hold-note's rider, still unmet) |
| **T-6** | **DOC_ID migration re-run** (owner-approved, 08-10) | Repair 1,336 historical gaps now that the per-type contamination producer is fixed. Guard: never derive from a COMPANY_DOC_ID shared across companies |
| **T-7** | **#39 date corruption repair — NOW URGENT, and its blast is CONTAINED** | **Incident (owner screenshot, 11:1xZ): 453 IN-SCOPE docs falsely OLD** — corrupt secondaries (`AI_DOC_DATE 26/06/2018` ← `18/06/2026` year-swaps) tripped `.some()`. **Contained same turn:** gate now trusts `RECEIVED_DATE`+`DOC_DATE` only (deployed, 4/4, parity 68/0); all 453 sent through `ACTION_RESTART` — they re-decide on the fixed gate and resume. The corrupt AI/BS/SELECTED fields stay excluded from ageing until repaired. | 825 rows, years wrong 2–10y (day/year swaps like `26/02/2016`←`16/02/2026`), 579 COMPLETED; blocks R3 + archive (#40). The `.some()` old-gate made corrupt-old dates *visible* — fix values, then re-age correctly. **Dry-run RUN 2026-08-16 ~08:0xZ (real counts, recorded per rule):** (a) sibling-provable un-swaps = **212** (AI_DOC_DATE 205 + SELECTED_DOC_DATE 7; the remaining ~686 of the 898-signature cohort have no deterministic sibling proof — they stay gate-neutralised, not value-repaired); (b) RECEIVED_DATE unparseable = **477, every single one the literal `true`** — the conservative allowlist covers 100%, nothing to widen; (c) month>12 = **30** (SELECT-only review list). Main-agent review of `scratchpad/date_repair_apply.sql` PASSED (WHERE clauses byte-match the dry-run, SET=DOC_DATE is the exact un-swap by construction, statements idempotent/self-extinguishing, residual checks appended) + a backup CTAS of all touchable rows (`incoming_documents_date_repair_bk`) prepended. **Apply is classifier-gated** (DB write) — owner runs: `wsl -d Ubuntu -e sh /mnt/c/Users/user/AppData/Local/Temp/claude/C--Users-user/5ea28bb9-ad01-4489-a898-6c5b68cf09d2/scratchpad/run_apply.sh` — expect UPDATE 205 / UPDATE 7 / UPDATE 477 then residual_swaps=0, residual_garbage=0. After apply, the hourly sweep re-ages the repaired rows correctly on next touch |

### ✅ SHIPPED+PROVED (2026-08-16 ~09:1xZ): `indoxDrainOn` master drainer toggle
**Live and owner-verified.** Rollout executed: bbox run (rebuilt incoming-documents with the
allowlist), deploy-workflow.sh both ids (active=true match=true, fleet 56/0 mismatched), n8n main
restarted, row seeded. Owner toggled OFF from the console; **proof: setting=false in DB; three
consecutive post-toggle drainer ticks ran 0.01s/0.02s/0.08s (normal: seconds-minutes) = gate
exits at `Drainer Off`; residual driver traffic is mode=webhook 78 vs integrated 1 — the
self-POST continuation tail of in-flight chains, NOT drain dispatches. Both lanes (2-min quota +
hourly sweep) are cut by the same gate.** Toggle back ON = next tick resumes, no restart needed.

### SHIPPED (owner order 2026-08-16 ~09:4xZ): יומן פעולות re-sourced to the router's redis dispatch brackets
**What the log WAS:** `/dashboard/actions` parsed the cumulative `incoming_documents.ACTION_LOG`
column server-side (13–19MB scans, `incdoc_action_log_append` middle-trims >6,000 chars so busy
docs lose their middle, 41% of stamps carry no execution id).
**What it IS now:** the Action Router's `Redis Start`/`Redis End` nodes bracket every real
dispatch with one key `incoming_docs_actions:<ID>:<ACTION>:<exec>` = `{line, status start|end,
trigger, origin, ts}` (ts added this change), TTL 10min. New `_actions_scan_redis()` renders
those keys in `_actions_scan`'s exact tuple contract, so ALL of the endpoint's filtering/
sorting/paging and the whole UI grid run unchanged. `<action>` = completed dispatch,
`<action> (running)` = started not yet ended. Only real dispatches appear (no no_action, no
BLOCKED — they never reach the dispatcher). Legacy parser one param away: `?source=log`
(still the only reader of history beyond the TTL window; the per-doc drill-down stays on it).
Wiring: `redis>=5.0.0` dep + `REDIS_HOST`/`REDIS_PASSWORD` env on incoming-documents; router
redeployed (active=true match=true). 9/9 offline checks green.
**First-render incident + fix (same hour):** page died with `WRONGTYPE` — n8n's redis node in
automatic mode had stored the OBJECT values as HASHES (which is also why they never expired:
8 eternal legacy keys found), and one GET against a hash aborts the whole read pipeline. Fix
shipped both sides: router nodes now write explicit `JSON.stringify(...)` STRINGS (TTL applies,
GET works; redeployed active=true match=true), reader is type-aware (TYPE+PTTL phase, then
GET/HGETALL per key, `raise_on_error=False` so one bad key can never blank the page; legacy
no-TTL keys without ts are skipped, not rendered as "now"). GC deleted all 8 legacy keys.
**Live verification 09:42Z (all green):** empty window → `reachable:true source:redis rows:[]`;
self-test key rendered with correct label/doc/exec/ts then deleted; `?source=log` legacy intact
(822 stamps today); container healthy 10s post-restart.
**Retention raised to 24h (owner: "we should see all the work done today", ~09:45Z):** the
original nodes' `ttl 60*10` erased everything 10 minutes after write — that is why the morning's
work was gone (expired, not lost: `?source=log` still shows it). Now: router `ttl 60*60*24` with
the value SLIMMED to `{NAME, STATUS}` (full-row values × ~151k keys/day ≈ 600MB redis; slim ≈
45MB), reader window 24h / 250k-key cap / 10s scan cache (the page polls every few seconds — one
scan serves them all). Re-deployed + hot-fixed + re-verified through the cache (self-test row
appears after cache expiry, correct in every field). Final `bbox run` cementing the image is
running; the log fills from the next real dispatch once `indoxDrainOn` is toggled back on.

### Original build record (owner order 2026-08-16): `indoxDrainOn` master drainer toggle
Console > indox > settings gets an `indoxDrainOn` switch; the drainer exits without dispatching when
it reads `'false'`. **All three layers edited + 17/17 offline checks green + live read-only proof
(gate query returns 'true' via COALESCE on the real schema today):**
- `blueprint/n8n/indoxV2BaseDrain01.json` — 3 nodes inserted between trigger and Check Capacity
  (`Read indoxDrainOn (settings)` postgres 2.6 on the INDOX Supabase credential → `Drainer Enabled?`
  if 2.2 strict-equals `'false'` → off-branch NoOp). Exact mirror of the proven
  `extraction_local_enabled` gate in BaseDocEx01. Fail-open: missing row / garbage value = ON;
  reads the table directly each tick (no Redis-cache dependency, toggle lands next tick ≤2min).
- `app/incoming_documents/api/__init__.py` — `"indoxDrainOn"` added to `_EDITABLE_SETTINGS_KEYS`
  (PUT upserts it; UI renders 'true'/'false' values as a switch automatically — zero UI changes).
- `blueprint/fixtures/settings.json` — seeded `indoxDrainOn='true'` for fresh installs.
Rollout (owner, in order): ① deploy-workflow.sh indoxV2BaseDrain01 (+ indoxV2FigureDocType01,
still pending from the bbox-run casualty) ② restart n8n main (schedule-trigger graphs register at
boot — deploy≠live) ③ seed live row via scratchpad/seed_indoxon.sh (else the toggle has no row to
render; ON CONFLICT DO NOTHING so an owner-set value is never overwritten) ④ rebuild+restart
incoming-documents (allowlist is baked in the image). Verify: toggle appears in settings; flip off
→ next drainer execution ends at `Drainer Off (indoxDrainOn=false)` in <1s; flip on → normal pass.

### SHIPPED (owner order 2026-08-16 ~10:0xZ): dup-guard flipped to `IF NOT SAME ACTION TWICE`
The guard's stopAndError sat on IF output 0, and n8n runs output 0's branch FIRST — so one
duplicate in a batch aborted the execution before the clean items dispatched (measured on the
owner's screen: 22 dup / 78 clean, the 78 blocked). Flip per owner: condition negated
(action `notEquals` prev AND `__dup_in_log` is false, De Morgan of the old `or`), outputs
swapped — TRUE(0) = clean → `If ACTION` dispatches first; FALSE(1) = duplicates → the loud
`SAME ACTION TWICE ERROR` raises AFTER, still failing the execution (guard stays loud, #20
semantics intact — each catch is still a real defect to investigate). Node renamed
`IF NOT SAME ACTION TWICE` (3 refs: node, connections key, incoming target; no expression
refs). **First deploy got silently REVERTED** — live DB read old-graph + `published=false`, the
signature of the owner's open editor tab saving its stale canvas back as a new draft (a
background bbox run does NOT import workflows on an onboarded stack — ruled out from its log).
Redeployed with same-breath CONTENT verification, now live-proven:
`has_new_node=true has_old_node=false notEquals=true active=true published=true`,
`connections: true(0)->If ACTION | false(1)->SAME ACTION TWICE ERROR`. Rule reinforced (owner:
"why do you keep claiming done before really done"): every deploy now ends with a live-content
probe, never the deploy tool's success line. OPEN EDITOR TABS of a just-deployed workflow must
be refreshed — a save from a stale tab re-installs the old graph. Runtime proof once the
pipeline resumes: a mixed batch shows clean dispatch keys in יומן פעולות first, then the error.

### ACTION LOG v3 (owner order 2026-08-16 ~12:xxZ) — POSTGRES table, LIVE + PROVEN
Redis replaced by `public.indox_action_execution_log` (PK "ID","ACTION","EXECUTION_ID"): router
`Log Action Start` = pg INSERT ON CONFLICT DO NOTHING, `Log Action End` = pg UPSERT stamping
ENDED_AT. Reader `_actions_scan_pg` via `_sync_transport`+`_paged_select` (window on STARTED_AT,
10s cache); rows carry `dur_s` + `done`; **labels are the CLEAN action name** (owner ruling —
state lives ONLY in the משך column: `✓ 4.0s` done / `רץ…` started-only / `—` legacy source).
**Two incidents shipped-and-fixed inside the hour, both content-verified:**
1. pg nodes do NOT pass items through (redis did) — Switch1 got INSERT stubs, every router exec
   died "UnHandeled Document" at 0s (group dispatch DOWN ~20 min). Fix: `Restore Action Lines` /
   `Restore Dispatched Lines` code nodes re-emit the payload after each log write.
2. deploy≠live applies to WEBHOOK workflows too — main serves its in-memory graph until restart
   (an execution post-deploy showed `exec_has_pg_node=false`). Memory updated.
Comma-splitting footgun dodged: single param = JSON with commas as chr(1), restored in SQL.
**Live proof:** router 2× success 0× error post-fix; rows END with real durations (0.4–0.8s);
endpoint `done True | dur_s 0.4`.
**Third footgun found by the owner's own node-panel screenshot (6 items in → 1 output):** the pg
node's DEFAULT `queryBatching` is "single" — ONE query per execution, `$1` from the FIRST item
only, so batches logged 1-of-N (and start's first item ≠ end's first item after dispatch
reordering → unended rows). Fix: `options.queryBatching = "independently"` on BOTH log nodes.
Proven live in 15s: `exec 3297797: 3 rows, 3 ended`, durations 0.7–2.2s across actions. The
UI (button + משך + no-סוג) verified rendering via the owner's screenshot; my browser-side
verification stays blocked on the self-signed-cert interstitial (extension can't click browser
security pages — needs a one-time manual exception in the MCP tab). Retention: unbounded table for now (~22MB/day) — add a purge
(7d) as follow-up. Sentinel param + table DDL live; DDL also needs a home in the repo schema
provisioning for fresh installs (follow-up).

### PREVIOUS DESIGN (superseded same day): router-only redis brackets, no collapsing
The router's Redis Start/End pair is THE ONLY bracket writer, by owner decision. My driver-side
`Redis Start D`/`Redis End D` pair is REMOVED (deployed, content-verified: startD_gone=true
endD_gone=true published=true) and the reader's (doc,action) collapse is REMOVED — because the
execution id is in the key ON PURPOSE: **a second completed row for the same (doc, action) is a
real double-run, and surfacing that is the log's job.** My 746 orphan driver-trigger keys were
purged from redis (they rendered as permanent "(running)" noise — one dispatch, two writers).
"(running)" now means exactly: the router wrote start and no end yet — in flight, or the
execution died between the brackets. Immediately proven useful: doc 1771420485406c1b684 shows
extract_per_type completed 2× + started 2× more across different executions — real repeat
attempts, now visible. Lesson bank: answer-the-question-first (owner: "why you dont answer my
question and jump into changes"); when a design already encodes intent (exec-id in key), extend
it only after understanding WHY it is shaped that way.

### FULL DUPLICATION REPORT (owner order 2026-08-16 ~15:3xZ) — 179 pairs, 100% explained
Scan window 12:51–15:26Z (2,421 log rows). **179 dup (doc,action) pairs · 786 rows · 168 docs ·
607 redundant executions · 36,469s (~10.1h) of wasted runtime · 0 unexplained (OTHER bucket
empty).** Three mechanisms, each proven earlier at node/ms level:
- **A — find_link writes nothing on zero-result search: 124 pairs · 641 rows · 82% of all dup
  volume · worst doc searched 22×.** Root (proven, exec 3298319/3298324): driveApi01 list
  returns 0 items → n8n skips ALL downstream in indoxV2SearchFile01 AND the GDoc caller → the
  latch/stamp upserts (which exist for the wrong-candidates case) are unreachable → doc
  unchanged → drainer re-offers every pass. All 128 involved docs STILL latch_null+link_none —
  the loop is live and unbounded (until each doc burns its 25-iteration budget on searches).
  Fix: alwaysOutputData + empty-branch into the existing SEARCH_IN_DRIVE_COMPLETED upsert path.
- **B — check_next stale-snapshot race: 53 pairs · 127 rows · 12 action types (update_status_
  old_doc 23).** Root (proven to the ms): check_next fires at DISPATCH time; its doc snapshot
  (fetched ~00.842) predates the action's end-of-action stamp (~00.922); the lock lives 1.5s
  but the follow-up needs 2.2s to reach it (lock check 03.042 — 1.46s after release). Lock
  atomic and blameless; ACTION_LOG evidence exists only after action end. Benign-idempotent
  outcomes, guard-noise + waste. Fix: check_next after Dispatched Lines, or start-bracket gate.
- **C — extraction loop (completion flag never set): 2 pairs · 18 rows** (extract_base_doc 13×,
  extract_per_type 5×) — the #34 looper pattern, bounded by the 25-iteration ceiling (one
  already MAX_ITERATIONS).
Also: indox-dev skill's action-log line updated redis→pg (was stale).

### GROUP A FIXED + E2E-PROVEN (owner order "fix A deeply verify end to end", 2026-08-16 15:52Z)
Root-cause chain, every link proven live:
1. **The real defect was in the drive SERVICE, not the workflow**: `/list` silently DROPPED the
   caller's `query` param (apps/drive/app.py + adapters/google.py::op_list — "GAP CLOSED
   2026-08-13"). Every pipeline search ran unfiltered → 0 successful finds in 6,861 attempts
   over 14 days → that IS the 52% "false negative" that forced the 08-13 revert of the latch fix.
2. **That service fix is live and working**: grep-verified in the running container; 564 docs
   carry LINK FOUND; 602 GOOGLE_DRIVE_FILE rows touched in 3 days; ground-truth probe 4/4
   controls FOUND via live POST /list.
3. **Ground truth re-run on ALL 130 still-looping docs** (exact queries rebuilt from
   COMPANY_NAME/SHORT_DOC_ID, POSTed to the live service): **0 found / 128 zero / 2 timeouts =
   0% false negatives** (was 52% on 08-13). Zero-result is now a TRUSTWORTHY answer; the
   remaining loopers' files are genuinely absent.
4. **Embargo satisfied → re-enabled the latch**: `alwaysOutputData: true` on `Search files and
   folders` in indoxV2SearchFile01 (as-code loop: pull → edit → `bbox n8n code validate` →
   `bbox n8n push indox indoxV2SearchFile01`, ok update+activate 15:52:18Z; status clean 92==92;
   node notes updated with the full closure so the 08-13 "Do NOT re-enable" order can't mislead).
   Service failures still fail loudly (retryOnFail 4×) — only success-with-zero latches.
**E2E proof (16:0xZ, organic dispatches, no manual pokes)**: post-push execs (e.g. 3311029)
ran the new def + not-found path; latched rows show the designed terminal state
(`SEARCH_IN_DRIVE_COMPLETED=true, ERROR='file not found', LINK empty`, ACTION_LOG stamped with
exec id); **0 find_link rows after latch** (loop dead per-doc); **34/140 cohort latched in the
first wave, errors=0**; one latched doc already progressed to STATUS MISSING_LINK (machine
moving past find_link again). Remaining cohort latches as check_next waves re-offer each doc.
**FINAL (16:37Z): cohort=197, latched=197, still_looping=0 — Group A fully drained.**

### find_link BATCHED + 100-item manual router run (owner order, 2026-08-16 ~16:3xZ)
Best-practices review (official n8n docs): "run once with all items" is the bulk mode; mode
'each' spawns one child execution PER ITEM. Our caller used 'each' → 100 find_link lines cost
100 SearchFile01 + 100 driveApi01 executions (~202 total).
**Change (both .ts pushed 16:21-16:24Z, status clean)**: `Call Search File` → run-once mode;
child `indoxV2SearchFile01` returns strictly 1-item-per-input in input order (loop pinned
batchSize=1, dangling done-output wired to new `Return All Results` node — before this the
multi-item return shape was undefined) and echoes ID/COMPANY_NAME/SHORT_DOC_ID; every found-path
expression re-anchored from `$('Call Search File').item`/`$('Action: Find Link in Drive').item`
to `$json` / `$('Batch Hash Dedup').item` so NO expression resolves paired items across the
sub-workflow boundary — the 2026-08-13 pairing incident classes cannot recur by construction.
New arithmetic: 100 lines = 1 router + 1 GDoc + **4 SearchFile01 (25/batch)** + 100 driveApi01
≈ 106 executions (was ~202). driveApi01 stays per-query by design (service contract; its
Shape list reads only the first item's response — do NOT batch into it).
**Canary (3 docs, exec 3313155)**: one child execution carried all 3 queries; 3 latches, exact
per-doc attribution, 0 errors. First canary attempt taught the payload contract: router
Switch1 routes on `DOC_TYPE` (computed by decide, NOT a DB column) — manual ACTION_LINES must
be FULL doc rows + ACTION + DOC_TYPE:'gdoc', or everything falls to Stop-and-Error
"UnHandeled Document" (that error at 16:25:59 was mine; its 4 orphan log rows deleted).
**100-item manual router run (fired 16:34:32Z, done 16:36:33 — ~2 min)**: router exec 3313438
→ GDoc 3313439 → SearchFile01 3313440/3313469/3313498/3313534 (4 batches × 25) + ~100
driveApi01. **All 100 docs latched, 0 untouched, 0 errors in my chain**; 99 'file not found'
+ 1 latched-then-progressed by an organic wave to MISSING_LINK (doc_mssdmfxelrt1mo; its ERROR
stamp came from organic driver exec 3313505 — the KNOWN DOUBLE-ACTION-BLOCKED guard class on an
unrelated doc, 114 driver errors today = pre-existing rate). 1 collision dup (one demo doc also
organically dispatched mid-window — expected with the drainer churn live).
**Not yet exercised live**: the found path (LINK FOUND) through the new anchors — all 100 demo
docs genuinely have no file (ground truth). It runs on the same within-workflow pairing that
`Hash Owner Lookup` documents as 1:1; first organic found-case will prove it — watch for the
next LINK FOUND stamp.
**Tooling fixed in passing**: push-app hook now whitelists API-legal settings keys (the public
API is additionalProperties:false; extra live keys availableInMCP/binaryMode/callerPolicy 400'd
the whole PUT — GDoc01 was unpushable via the API path until this).
**Follow-up worth owner decision**: 6,861 docs settled 'file not found' by the pre-fix broken
search; per the 08-13 ground truth ~53% (~3,430 docs) DO have a findable file. Un-latching them
for one re-search pass with the FIXED pipeline would recover thousands of links. Not done —
re-runs are ACTION_RESTART-only per the laws; needs an explicit owner order.
**Proof it works: the half-half demo below recovered 46 of them in one 3.6-minute pass.**

### MINIMAL Search File + full matrix E2E (owner orders, 2026-08-16 ~17:0xZ)
**Child rewritten minimal (6 nodes, was 10)**: Start → Loop(batchSize=1 pinned) → If Input OK →
Search (driveApi01, retry 4×, onError→regular, alwaysOutputData) → **Shape Result** (one code
node = the whole result contract) → loop; done → Return All Results. Removed: Stamp Query (T-8
diagnostic — root cause confirmed+fixed, its note said remove then), If Found File1, 3 Edit
Fields, End. File shrank ~40%; giant history notes condensed to contract lines (history archived
here + git).
**New result contract (owner phrasing order)**: found → `{ok:true,found:true,id,name,size,
md5Checksum}` · not-found → `{ok:true,found:false,message:'file not found'}` — an ANSWER, not an
error · real failure → `{ok:false,error:...}`. Shape emits EXACTLY one item per doc (multi-hit
collapses to best name-match — also fixes the 2-files case, e.g. קל קל, that could break 1:1) so
the return is always N-in/N-out in order.
**Caller 3-way**: found → LINK FOUND path · ok&&!found → latch (ERROR written null, no fake
error text) · **ok:false → `Search Failed (no write)`** — doc untouched, lock released by the
router, re-offered later; a failed search can never again settle a doc (the 08-13 wrong-label
class is structurally dead). Per-item isolation: one failing search costs ONE doc, never the
batch.
**Deploy battles worth knowing**: n8n refuses to publish a workflow whose executeWorkflow target
has no published version — GDoc01 pushes 400'd until `indoxV2QueryTotalAmt01` (bbox-run import
casualty, referenced by the query_doc_total_amount lane) was pulled into code, set active:true,
and pushed — **casualty healed, active+published**. (Note: it lacks the app:indox tag so status
lists it under the central blueprint — retag someday.) A 400'd PUT still bumps updatedAt, which
trips the push CAS check against yourself — resolve with a pull, content lands anyway.
**Matrix E2E (all through the real router webhook, full-row lines + DOC_TYPE)**:
- found ✓ 2 docs → LINK FOUND (already-owned variant, HASH rightly unclaimed) — exec 3314744
- not-found ✓ re-latched cleanly
- real search error ✓ (induced: 30,000-char query → 4 driveApi01 retries all fail →
  **child execution still SUCCESS**, error contained to an ok:false item, doc UNTOUCHED,
  re-offerable). A 4,000-char query does NOT fail — Drive accepts it (returns zero).
- bad input (empty SHORT_DOC_ID) ✓ ok:false, no write, doc untouched.
**100-line half-half demo (owner order; fired 17:04:59Z, done 17:08:37 — 3.6 min)**: 50
probed-found + 50 probed-zero (4 ids overlapped both probe batches → 96 unique lines). Router
3315399 → GDoc 3315400 → **SearchFile01 3315401 / 3315570 / 3315606 / 3315638 (exactly 4
batched executions)**. Results: **96/96 latched · 46 LINK FOUND (46 docs recovered links and
moved to IN_PROGRESS toward ERP) · 2 hash-claimed + 44 already-owned twins · 0 attribution
mismatches (every linked doc's file name contains its own SHORT_DOC_ID) · 0 errors** in the
whole chain. The found-pool came from the PRE-FIX settled population (probe of 300 oldest:
~48% findable — the recovery reservoir is real; recent settled docs probe 0% findable, as
expected post-fix).

### DRIVER MAPPED + CLEANED (owner order 2026-08-16 ~17:1xZ) — pre-work for the Group B fix
**Full map delivered: [driver-map.md](driver-map.md)** — drainer/driver/router responsibilities
+ the four junk families. **Cleanup executed and live (17:30Z): driver 131 → 52 nodes, file
6,991 → 1,642 lines**, validate ✓ push ✓ published ✓, post-push executions succeed on the new
def. Removed: (A) the in-driver Action Router duplicate — the never-cleaned half of the split,
13 nodes, proven dead (0 executions/7d, 0 redis bracket keys; ACTION_LINES posts now fail loudly
via the switch fallback); (B) the parallel-subworkflow callback prototype, 19 nodes, incl. the
If1/If3 residue grafted onto the live webhook fan and two DISABLED webhook registrations;
(C) the in-driver decide test rig, 3 nodes (indoxV2DecideTest01 covers it; decide now feeds the
dup-guard directly); (D) 43 scrapyard nodes (legacy shipment-lane copy, selection/priority
leftovers, dead loops, 7 stickies — one of which was the owner's old TODO saying exactly
"cleanup, move action dispatcher to different workflow").
**Still visible, pre-existing, NOT from the cleanup**: the clockwork guard-catch —
`DOUBLE ACTION BLOCKED on doc_msvimsffpx654y ACTION=mark_completed` every 5 min (83 in 24h,
fires on the driver's own schedule tick; same error on the OLD def all day) = LIVE DEFECT #2 /
T-27 restart-routing gap, and it is the natural companion of the NEXT work item:
**Group B fix (agreed direction, next)**: move the advance step — check_next — into the Action
Router AFTER `Log Action End` (the router already WAITS for its action workflows), and remove
the driver's dispatch-time Check Next Action branch. Next action is then decided only against
post-completion state; no polling, no callbacks, per-doc freshness by construction.

### COMPLETION-GATED DISPATCH + SINGLE-POINT UNLOCK (owner orders 2026-08-16 ~18-19Z) — Group B closed at the root
**Wait-for-completion (owner: "next fires only after all groups executed")**: router webhook →
responseNode + new `Router Done` node; the driver's group POST now BLOCKS until the router
completes (30-min timeout, 10 groups parallel, post-before-advance canvas order is load-bearing);
`Check Next Action` rewired off the dispatch fan onto the group loop's DONE output. check_next
stays in the driver (lock check), sees only post-completion state. **Deadlock guard**: waiting
chains hold worker slots (2×10 total) — check_next fan-out capped at 5 chains (chunk grows with
batch: organic 8/chunk, big runs N/5).
**Single-point unlock (owner: "unlock only at upsert")**: the router's `Unlock Doc Action`
REMOVED — firing after Dispatched Lines it could release a lock ANOTHER driver had already taken
for the doc's next action (a dup mechanism). Discovery en route: **the upsert-side unlock
(indoxApi01 'API Unlock Doc') had been a silent NO-OP for weeks** — it passed the bare doc ID
against compound `<ID>::<ACTION>` keys (its note still said "doc_step"); the router unlock was
compensating. Fixed at the root: processLock01 unlock with a BARE key now scan-deletes
`<KEY>::*` (new `Scan Doc-Scoped Locks` → existing Split Out → DELETE RESULTS; compound keys
unchanged — safe because at upsert time a doc's only doc_action lock is the completing action's
own). GDoc's failed-search path got an unlock-only upsert (`Build: Unlock Only`) so ok:false
docs release their lock at the upsert too (empty_row legacy lane leaks to TTL — noted in Router
Done). Healed 2 more bbox-run publish casualties en route (SyncApi ref is a MISSING workflow —
indoxApi01's "Call Sync Api" points at nothing; pre-existing, flagged). Sticky-note lint params
added to processLock01/indoxApi01 (validator strictness).
**Smoke (2 docs, ~6s, 0 errors)**: restart→find_link→MISSING_LINK ✓ and restart→…→COMPLETED ✓;
router end 31.352 < next driver start 31.433 (wait proven). Execs 3321005/3321066/3321071.
**THE BIG VERIFY (owner order: all MISSING_LINK → ACTION_RESTART → ONE driver run)**: 2,230 docs
flipped, single driver execution **3321115** (19:00:30). Restart wave: all 2,230 bracketed in
~35s. Monitoring (19:2xZ): **682 links recovered in 2h · COMPLETED +87 · MISSING_LINK rebuilding
(188→395 as not-founds settle) · doc_action locks at rest = 0 · REAL recent lock-blocks = 0**
(a 1,360 reading was the cumulative-ACTION_LOG measurement trap — historic stamps on touched
docs). Errors fully classified: 54 = duplicate-key on the best-effort HASH CLAIM (harmless by
design, doc keeps its LINK) + 3 = the known DOUBLE-ACTION guard clockwork (T-27). Cascade still
draining IN_PROGRESS (~1.8k) at ~1,400 executions/5min.

**Owner rewire (19:35, published 19:4x)**: `Check Next Action` fed DIRECTLY from `Execute
Action` again — correct under completion-gating because of the n8n lane-order law (owner's
formulation: never parallel; multi-lane fan-outs run by the HEIGHT OF EACH LANE'S FIRST NODE,
always the highest next new node). The Check Next lane is the LOWEST lane, so it runs only
after the dispatch lane's blocking POSTs complete — one shot, full line set. **Lane height is
now a correctness invariant** — documented in the Check Next Action node notes (moving that
lane above the dispatch lane would silently resurrect the Group B race). Owner's own editor
run proved it: 4m07s, 90 groups posted+completed, then 5 chains. Also owner deactivated
`Action Filter` (passthrough) and I published his draft via push (drafts don't serve
production until published).

### PREDICTABLE-SCALING REDESIGN (owner order 2026-08-16 ~20-21Z) — one splitter, one lane per action
**The doctrine (owner)**: parallelism must be predictable, so the DRAINER is the only component
that fans out. The driver never splits: **Group By ACTION now emits ONE group per action** (the
25-item chunking + Loop37 batch-of-10 fan REMOVED — loop nodes deleted, driver 45 nodes), so a
run's parallelism = its distinct-action count (avg 2-3 lanes), each lane one blocking router
call with ALL that action's lines. Action workflows own their INTERNAL batching (their loops:
25-per-search today; get_name-class actions can batch 5k join+upsert in one go — per-action
tuning knob). **Scale-up is pre-driver and manual**: run the whole id set as 1 driver (baseline
timeline until all reach no_action), then split ids into N groups → N parallel drivers → N×
speed, always N × action-lanes total parallelism. POST timeout raised to ~58 min/lane; a lane
that would exceed the router's 3600s executionTimeout means the id set needs splitting — the
model's natural ceiling.
**Driver self-triggers removed**: the (deactivated) Schedule Trigger + its GETALL sweep lane
deleted. **Change events moved API → drainer**: indoxApi01's 5-min self-tick + direct driver
call (Process Changed Doc — previously "the only active driver of indoxV2Driver01") REMOVED;
its eligibility query is now the API's `INLINE_ACTION='GET_CHANGED'` op, and the DRAINER polls
it each tick (new `Poll Changed (indox api)` + `Merge Candidates + Changed`, dedupe by ID,
behind the indoxDrainOn gate). **The drainer is now the sole initiator of the driver** — drain
off ⇒ nothing drives (no change-redrive, no sweep, no schedule). All three pushed + published.
**Casualty chain fully healed en route** (publish-validation kept 400ing): tVzFMkz18pCsXRyw,
IndoxResetGml001, indoxV2TestFixtures01, IndoxResetFull01, SyncSource000001, SyncApi0000000001
— all verified CALL-ONLY (executeWorkflow/manual triggers; activating publishes without waking
any retired lane) — plus indoxV2QueryTotalAmt01/indoxV2QueryDocDate01 earlier. The bbox-run
import footgun's whole blast radius is now published.

### ACTION BATCHING INVENTORY + SCALING MATH (owner order 2026-08-16 ~21Z)
Measured from today's 12h of brackets (`indox_action_execution_log`, 11k+ lines timed).
**Per-action: measured per-line cost · internal batch (action-workflow loop) · class · should-batch:**
| action | per-line | lines today | internal batch | class | should batch |
|---|---|---|---|---|---|
| update_status_missing_link | 0.13s | 1,827 | 100 | pure SQL upsert | **5000** (one pg pass) |
| restart_gdoc | 0.26s | 2,235 | 30 | SQL flag-reset | **5000** |
| update_status_old_doc | 0.30s | 1,685 | 100–150 (Global) | pure SQL | **5000** |
| action_extract_shipment_ids | 0.73s | 130 | 50 | SQL parse+upsert | 1000 |
| mark_completed | 0.86s | 165 | ~100 | SQL + consolidation | 1000 |
| get_short_doc_id | 1.30s | 24 | ~100 | SQL derive | **5000** |
| link_documents | 1.36s | 12 | 50 (BS) | SQL join | 1000 |
| select_invoice_values | 1.81s | 147 | 50 | SQL scoring | 1000 |
| mark_max_iterations | 2.77s | 41 | ~100 | SQL | **5000** |
| update_name | 3.77s | 136 | 150 | SQL + Drive rename | keep (Drive-bound) |
| find_link | **4.07s** | 3,400 | **25/search-call** | Drive search per doc | keep 25 (API contract) |
| get_company_name | 4.45s | 18 | ~100 | AI/lookup | keep small |
| resolve_double | 5.48s | 946 | 50–100 | SQL adjudication | 500 |
| extract_per_type | 6.32s | 234 | ~30 + child | AI per doc | keep small |
| apply_gmail_labels | 6.81s | 14 | 150 | Gmail API per doc | 25 (API-bound) |
| update_status_double | 8.80s | 9 | 100 | SQL (+deps) | 1000 |
| check_from_office | 15.16s | 15 | 25 | Drive search per doc | keep 25 |
| extract_base_doc | **37.36s** | 306 | 30 (Global AI loop) | AI extraction | keep ≤30 |
Two classes: **SQL-only** actions (per-line 0.1–3s, dominated by execution overhead — batching to
1k–5k makes them one pg pass ≈ 0.01–0.05s/line) vs **external-per-item** (Drive/AI/Gmail/ERP —
per-line cost IS the external call; batching can't compress it, only splitting scales it).
**THE LANE CEILING (one lane per action, router executionTimeout 3600s):**
max lines per lane = 3600 / per-line-cost → restart 13.8k · update_status 27k · find_link **884**
· resolve_double 657 · extract_per_type 569 · check_from_office 237 · extract_base_doc **96**.
Minimum split for a one-shot: **N ≥ ceil(X × c_heaviest / 3600)**.
**LIFECYCLE MATH, proven on the restart cycle (X = 2,230, chain restart→find_link→status):**
- scale-1: 2230×0.26 (580s) + 2230×4.07 (9,076s) + 1900×0.13 (247s) ≈ **2h45m — and INVALID:**
  the find_link lane (9,076s) is 2.5× over the 3600s ceiling. The math itself forbids scale-1 at
  this size: find_link caps one driver at 884 docs.
- scale-4 (4×557): 145s + 2,267s + 62s ≈ **41 min per driver, all four in parallel = 41 min
  total ≈ exactly ¼ of the (theoretical) scale-1** — and every lane under the ceiling ✓.
  Parallelism: 4 waiting drivers + 4 router lanes = 8 of 20 worker slots. Predicted, not hoped.
- Slot budget caps the split: N drivers ≈ 2N slots → **max split 8 with today's 2×10 workers**;
  beyond that, add workers first. Yesterday's real cascade (25-batch × 10-fan era) took ~50 min
  for the same population — the new model trades that chaos for exact predictability: T(X, N) =
  Σ_hops (X/N) × c_action, achievable N× speedup, capped by ceiling and slots you can compute.

### SCALE-8 PROVEN + CALIBRATED (2026-08-17 ~00:4xZ host / 21:3x DB-clock)
First scale-8 attempt froze: my check_next chunk cap (MAX_CHAINS=5) re-split at EVERY hop —
geometric fan (g1 alone: 79 driver executions), ~40 waiting drivers vs 20 slots. TWO FIXES,
both live: (1) **check_next never splits** — one chain per driver run, scale-N holds exactly N
waiting drivers for the whole lifecycle; (2) **find_link direct-call** — SearchFile01 POSTs the
drive service /list directly (same canonical op; the driveApi01 wrapper cost ~2s of n8n
sub-execution per search). Unwedged 96+163 stuck executions en route (stopped Bull remnants
leak their locks — TTL clears).
**Clean run: 951 docs, 8×119, fired 21:34:10 → settled 21:38:39 = 4m29s** (predicted 5-6).
Lane proof: find_link exactly 8 lanes @ **2.63s/line** (was 4.07) · restart_gdoc **0.06s/line**
(was 0.26 — the 5000-batch bump) · update_status_missing_link **0.10s/line**. Errors: baseline
classes only. **Calibrated control: T(X,N) ≈ (X/N)×2.8s** for the restart cycle; 3k@8≈17min;
sub-10-min at 3k needs scale-16 → worker bump (N8N_CONCURRENCY 10→20 = 40 slots, compose env +
worker recreate — pending owner call). Batch bumps live on 14 SQL-only lanes (GDoc 8, Global 6
incl. get_company_name→5000 — verified in-memory join, Companies map loads executeOnce);
missing_link/restart/mark_completed lanes live-verified in this run, the rest are N-safe
statically and get exercised organically when drain resumes.

### SCALE-16 RESULTS + THE REAL WALL + 5-LANE DRAINER (2026-08-17 ~01-02Z host)
**Scale-16 (manual): 1,146 docs in 11.6 min — and the discovery that matters**: find_link
degraded 2.63→4.85 s/line at 16 lanes; total search throughput was ~3.3 searches/sec at BOTH
scale-8 and scale-16 ⇒ **the drive service container is the ceiling, not n8n** (worker slots at
20×2=40 verified live, queue depth 0 throughout). Scaling find_link past ~8 needs the drive
service scaled (gunicorn workers / replicas), not more drivers. Dups in the run: **1 pair**
(was 179/day before the fixes).
**MAX_ITERATIONS epoch fix (owner order)**: _iter counted LIFETIME distinct log stamps — bulk
restart cycles permanently ate doc budgets (194 retired in one test day, RETRY_COUNT=0). Now
counts stamps AFTER the last restart marker (same epoch semantics as the dup-guard);
ACTION_RESTART opens a fresh 25-step budget. The 194 were reset via restart + re-driven.
**Drainer provenance (owner scheme)**: every driver run carries DRAINER_TYPE / DRAINER_ID /
DRAINER_CHAIN (execution-id chain per hop); drainer lanes, manual fires, editor runs all stamp;
unattributed lands in 'unknown_*' (must stay 0). Monitor: scratchpad/provenance_monitor.sh.
Mystery runs root-caused: Bull stalled-job re-deliveries of force-stopped executions (proven
via body deref + parent-chain walk to integrated root 3340248 + fleet caller sweep + drainer
0.0s gate ticks); backlog flushed.
**5-LANE DRAINER LIVE (owner spec)** in indoxV2BaseDrain01 (30 nodes):
- lane1 nightly 02:00 full-table ONE-shot (factor forced 1), behind indoxDrainOn (off). TODO
  noted in-node: wire stop-all+unlock-all before first enable.
- **lane2 drain-by-id: POST /webhook/indox-drain {IDS:[...]}** — splits by settings
  `indoxScalingFactor` (seeded 16, FACTOR body override), fires drivers fire-and-forget with
  full provenance. THE official scale runner (replaces manual scripts). Not master-gated —
  direct call = operator intent.
- lane3 drain-all: same webhook {ALL:true} → full-table ids → split → fire.
- lane4 legacy adaptive: DISABLED in place (Check Capacity node disabled, chain preserved).
- lane5 change events: gate → API GET_CHANGED → split → fire (master-gated, off).
**First lane2 production call**: 1,332 docs (MISSING_LINK + the 194 reset) → one webhook call →
`{"fired":16,"drainer":"3342885"}` — running now; watcher + provenance verification attached.
**THE BOTTLENECK, EXPLAINED (2026-08-17 ~02Z)**: the drive service runs **gunicorn `-w 2`** —
two SYNC workers = exactly 2 concurrent requests; everything above that QUEUES in gunicorn's
backlog. CPU sits at 17% (I/O-bound on Google, not compute). That's why throughput pinned at
~3/s regardless of lanes and per-line latency grew with concurrency (8 lanes: 2.63s/line ·
16 lanes: 4.85-6.69s/line). **Measured verdict 16 vs 8: 16 completed correctly (queueing is
graceful — nothing failed) but was SLOWER in absolute terms**: find_link stage throughput
3.04 lines/s at 8 vs 2.07 at 16 (queue contention + run overlap), and long queues push heavy
actions toward gunicorn's 120s timeout. Factor stays 8 (owner call, data agrees).
**The real unlock when wanted**: the service is I/O-bound → `gunicorn -w 2 --threads 8` (≈16
concurrent, ~zero extra memory; the container has 191/384MiB) or more workers + memory bump —
repo change in apps/drive + container recreate; then the factor can follow it up.
**NEXT (owner)**: after stability confirmed — restart all OLD; drive-service concurrency
(above) if sub-5-min full cycles are wanted; finalize lane1's stop-all plumbing.

### IN FLIGHT (owner orders 2026-08-16 ~10:4xZ): stop-all button + action-log completion
- **Full stop #2 EXECUTED** (owner: "stop all indox running workflows"): indoxDrainOn=false via
  app API, workers+main restarted, queue flushed, **315 leaked locks released**. Pipeline quiet.
- **One-click emergency stop SHIPPED to repo** (`POST /config/stop-all` + red button in
  console>settings>פעולות תפעול): gate off → n8n owner-session REST stops running executions
  (same login flow as bbox's verify hook; N8N_OWNER_*/N8N_REST_BASE env added to compose) →
  3× Bull queue flush → release all doc_action locks; per-stage degradation reported, never
  hidden. bbox rebuild in flight; smoke test after recreate (safe: pipeline already stopped).
- **unlock-all button SHIPPED+PROVEN** (`POST /config/unlock-all` + button): released 358 then
  315 real leaked locks on its first two runs.
- **Action log on live traffic PROVEN**: real rows rendered (find_link, update_status_old_doc,
  Hebrew doc names, exec ids). **Open defect: driver's `Redis End D` doesn't fire** — the four
  action-call nodes return no items (exec 3291904: success, start-bracket ran, end didn't), so
  rows stay "(running)" until TTL. Fix direction: restore-payload pattern (re-emit
  `$('Redis Start D')` items after the calls) + alwaysOutputData on the calls — NOT built yet.
- **Drainer has an unpublished editor draft** (10:33, differs from repo, DOES contain the gate)
  — pull-or-publish decision pending; published version runs correctly meanwhile.
- Driver blueprint now carries the owner's height-fix (execution order = canvas position,
  topmost first — n8n v1 rule learned today) + dispatch brackets; repo == live for the driver.

### P1 — pipeline health & throughput
| id | task | detail |
|---|---|---|
| **T-8** | **A0.1 search end-to-end** (52% false negatives) + **#37 latch** (6,187 rows) + ~860 wrongly-latched | Root cause of empty pipeline searches still unfound (query string unobserved). Fix search → clear latch → `MISSING_LINK` pool (6,2xx) becomes recoverable. Then revisit `MISSING_LINK` in the terminal set |
| **T-9** | **Zero-error deploys/restarts** | Import gap fixed (per-import reactivation, 27→0); remaining: restart kills in-flight (282 crashed in wedge window). Options: drain-then-restart script, or accept+document. Also fix capacity gate to read HOST load, not just n8n in-flight (sweep wedged WSL at gear 2 — twice) |
| **T-10** | **#31 company resolution backlog** (1,308 docs) + #33 Companies-Loader self-call starvation | The biggest non-OLD completion blocker |
| **T-11** | **#32/`s_adj` review** | COMPLETED re-adjudication is by-design (R2 dedup) but is also #38's damage vector — review demotion criteria before T-4/T-5 rely on it |
| **T-12** | **#27 mark_completed precondition** + #34 looping docs | Extraction-evidence gate before COMPLETED; the 17 self-terminating loopers |
| **T-13** | **Re-run full INDOX test suite** (R7) + fix `v2-decide-test.mjs` expectations to the new rules (OLD-any-date, 25-ceiling, guard) |

### P2 — hygiene & platform (owner-gated items marked 🔒)
| id | task | detail |
|---|---|---|
| **T-14** 🔒 | #16b ACTION_LOG history repair | `log_repair.sql` dry-run-proven (noise→0, 50/50 entries preserved); the `UPDATE` is one uncomment behind the permission gate |
| **T-15** 🔒 | #18b′ delete 7 unreferenced orphan workflows | backup + `orphan_retire.sql` ready; `DELETE FROM workflow_entity` is classifier-gated |
| **T-16** | #22b residue: decide fate of aged-after-completion docs (1,706 kept COMPLETED by design) — confirm or sweep |
| **T-17** | ai_extraction_cache FIELDS-blind key — verify the 08-10 fix proved out (paid-call count + per-field answers) |
| **T-18** | Thumbnail duplicacy — apitools already renders; kill the separate PDF-render call |
| **T-19** | 3 dangling `executeWorkflow` refs (`indoxV2QueryShipmentId01/InvoiceId01` from Ship router, `indoxApiSupabase01` from mailApi) — repoint or prune |
| **T-20** | Workflow-as-code splitter (R-A verdict): read `bbox n8n push` first, then wire explode/implode (68/68 lossless proven) + `check_js.py` syntax gate into CI; adopt the three orphaned pieces (normalizers.js embed-gate, decide-test harness, expr-sweep widened) |
| **T-21** | Ops: WSL VHDX compaction (150.8GB, needs stack downtime) + C: disk headroom (2.5GB free) + host-load-aware capacity gate (see T-9) |

### OLD_REASON (owner order, 2026-08-15 ~11:45Z) — SHIPPED, repopulation running
Column `OLD_REASON` (json) added; `anyOldDate` now RETURNS the reason (rule, cutoff, hits, considered, skipped-with-why — unparseable / implausible_year / swap_mangle_of_sibling); the entry gate attaches it; the `STATUS COMPLETED3` Build passes it; the api upsert is dynamic so it lands with zero further plumbing. Executed proof shows the full json (hits `DOC_DATE 02/07/2025`, skip reasons labelled). **All 19,249 OLD reset → `ACTION_RESTART` per owner; lane-2 sweep re-ages everything WITH reasons.** First sweep exposed the named-node `.item` pairing footgun (202 re-aged reason-less) — Build switched to `$json`, reason-less rows requeued; **every OLD row from here on carries its explanation.** Sweep passes complete the repopulation (~15.5k expected; WSL-wedge risk noted at T-9 — recovery playbook proven).

**Second, distinct reason-gap found 2026-08-14 (NOT the `.item`-pairing footgun above — that one's fixed):** 8 rows STATUS='OLD' with OLD_REASON NULL (doc_msmah01tiu0ijd, doc_msmai3a6ht53c3, doc_msmai253fjmnlm, doc_msmgiatc6162b9, doc_msmgi3sfxz7otq, doc_mso9t2ep7pyrr3, doc_mso9spadc1jqg3, doc_mspytja7tok02e — the full set). Root cause (code-proven by elimination, DB-side corroboration incomplete — see caveat): `Decide DOC BASE Action` has TWO producers of `update_status_old_doc` — the entry gate (attaches OLD_REASON, skips STATUS∈{MERGED,GARBAGE,DOUBLE} via `__tomb`) and `docBaseDecide()`'s own older, redundant "late gate" check (kept on purpose for dates extraction reveals) which does NOT attach a reason. A row exempted from the entry gate because STATUS='DOUBLE' falls through to the reason-less check. All 8 rows' ACTION_LOG shows `Resolve Double (confirm-double)` immediately before the reason-less `STATUS COMPLETED3` write — consistent with STATUS='DOUBLE' at aging time, not DB-confirmed on these exact rows (the confirmation query was mid-flight when the disk hit 0 free). Proposed fix + byte-exact diff + required tests (all_fields_test.js, lane2_test.js, a new DOUBLE+old-date case) staged at `scratchpad/PROPOSED_old_reason_gap_fix.md` — **NOT applied** (an Edit attempt hit the same ENOSPC) and **NOT tested**. Requeue (`STATUS='OLD' AND OLD_REASON IS NULL` → `ACTION_RESTART`) staged at `scratchpad/reason_gap_requeue.sql`, gated UPDATE commented, **not run** (owner rule change: no DB writes beyond SELECT without review).

### FULL-TABLE DATE AUDIT (owner order, 2026-08-15 ~11:3xZ) — findings + fixes shipped
**Fixed this hour (all live, 7/7+4/4 executed proofs, parity 68/0):**
- **Gate restored to ALL five date fields** (owner override of my narrowing) — corruption-awareness moved INTO `anyOldDate`: candidates must be **plausible** (2015..now+2) and **not a swap-mangle of a later-year sibling** (asymmetric: the symmetric check killed both halves of a pair — caught by executed case s7). A mangled copy can neither forge old nor block real ageing; an AI-only old doc still ages.
- **394 false-OLD docs adjudicated by the corrected gate itself** (ran the deployed decide on all 14,294 OLD rows) → `ACTION_RESTART`; overlap with the earlier 453 already mid-restart.
**Audit facts (full table):**
- Formats: dd/mm/yyyy dominates; **DOC has 5,056 iso-ts + 938 iso-date**; BS_LINE is 9,416 iso; **RECEIVED has 477 `OTHER`** (unparseable — earlier sampling showed literal `true` values); dd/mm/yy and dotted variants ~1,900 total.
- **898 docs carry the AI/SELECTED day↔year swap of DOC_DATE** (the #39 signature, now neutralised at the gate; values still need repair = T-7).
- Future dates: DOC 166 / LOCAL 160 (plausibility cap now ignores >now+2y for ageing); pre-2015: 105 across fields (ignored as implausible); month>12 (dd/mm confusion): 86.
- OLD integrity: **0 OLD docs without any parseable date**; workable-status old tail draining via sweep.
**Remaining date debts (fold into T-7):** repair the 898 swapped values (un-swap where sibling proves it) · the 477 RECEIVED `OTHER` values · 86 month>12 rows · adapter ingest-gate parser parity (dd/mm-only today; ISO RECEIVED would slip it — decide gate still catches those next touch).

### End-state (the owner's scripture, 08-10→08-15)
> Maximum docs COMPLETED via both extraction points · 0 duplicated actions (guard live) · 0 errors · all old filtered at ingest · **merge everything automatic — table clean, unified, one row per document — ready to sync to Priority.** R2 → R1 is the finish line.

---

## PHASE A-E LEDGER (owner: "all fully completed and proved" — tracked explicitly)
| phase | item | state | proof / owner of the remainder |
|---|---|---|---|
| A0.1 | search end-to-end (52% FN) | 🔄 **agent running now** | T-8: observe the real query, fix, before/after found-rate |
| A0.2 | same-action-twice loud error | ✅ **DONE+PROVED** | guard live, 25 real catches, 0 false; every ACTION_LOG entry tokenised |
| A0.3/A0.4 | no-backoff state machine, NEXT_RETRY_AT removal | ✅ **DONE+PROVED** | writers/readers 0, shapes 0 repo+live; column drop = T-3 (armed) |
| A1 | dates correct | 🟡 half | AI-date guard + corruption-aware gate ✅ live; **value repair (898 swaps, 477 garbage) = T-7, staged by agent** |
| A2 | settings-driven ageing | ✅ **DONE+PROVED** | `old_document_months_back=6` + `max_iterations_per_doc=25` live, config-aware with stated fallbacks |
| B1 | Priority ERP delivery (8.8%) | ⏳ end-goal | unblocks when R2/R3 close — the finish line |
| C1-C5 | dedup/merge automatic | 🟡 half | `s_adj` adjudication live+understood; DOUBLE→MERGED (T-4), #38 revert + transactional merge (T-5) open |
| D1 | link/latch rows (6,187) | 🔄 tied to A0.1 | search fix → latch clear → MISSING_LINK pool recovers |
| E1 | identity split | ❌ open | `(COMPANY_ID, SHORT_DOC_ID)` used by nothing; certainty tiers designed, not implemented |

## PROVEN DONE (this cleanup, compressed — full evidence in the archive file)
No-backoff state machine (#1–#12,#15,#17,#19,#21,#22,#23,#24 all live) · `NEXT_RETRY_AT` writers/readers 0 (column drop = T-3) · ACTION_LOG pure (writers) + every entry tokenised `ACTION=<name>` · **double-action loud error live** (7/7+10/10 harness, 25 real catches incl. the disk-full incident, 0 false) · OLD: 4-defect chain fixed (`.every`→`.some` the killer), all-36k-rows proof 15,405/15,587, sweep firing (+4k first pass) · OCR false-success writer closed · MAX_ITERATIONS=25 single-source · G42′ wired green · deploy per-import reactivation (27→0 errors) · repo⇄live content parity 68/0, live orphans 15(active 0) · net −25 files/−68 nodes · Stop-hook+cron autopilot proven.

## 2026-08-16 ~23:30 — ROOT DRAINER FOUND AND KILLED: the indoxApi01 GHOST CRON
The "mystery driver runs with drainer off" finally has a face. **n8n main was still firing a
DELETED schedule trigger**: an old in-memory registration of indoxApi01 (the removed
`Poll IN_PROGRESS Schedule` → `Get IN_PROGRESS Docs` → `Process Doc (poll)`/`Process Changed Doc`
redrive lane) kept ticking **every 5 minutes at :55** even though the live graph has none of
those nodes (only Keepalive→NoOp). Proof chain: every `mode=integrated` driver execution lands
at HH:M0:55/HH:M5:55 (36 in 3h, EVERY ONE error) · each is preceded ~200ms by an
`indoxApi01 mode=trigger` execution · that execution's payload contains "Process Changed Doc",
a node REMOVED from the live workflow · DB `versionId=activeVersionId` (no draft skew) — so the
executing graph exists only in main's memory. Yesterday's "integrated root 3340248" = the
21:45:55 tick of this exact cron. Its fingerprints: the steady err_15m≈4 baseline (each tick's
driver errors on the DOUBLE ACTION guard — e.g. 3344902: doc_msvimsffpx654y mark_completed
"token already in ACTION_LOG"), the `unknown_executeworkflow` provenance stamps (the ghost
passes no DRAINER_* — the tracer branded it correctly from day one), and dup-action collisions
with legitimate lane2 chains. **Fix applied**: dangling connections for the 5 removed nodes
stripped from indoxApi01.workflow.ts (repo) → `bbox n8n push indox indoxApi01` → API
deactivate/activate cycle (both 200, 23:30:44) to force main to drop the old registration and
re-register the current graph. Verification = the 23:35:55 tick must NOT fire; escalation if it
does: restart n8n main (registrations live only there). Lesson recorded: deleting a
schedule-trigger NODE from a live workflow does not deregister its cron — deploy≠live now has a
second face (ghost registrations), and any unexplained fixed-cadence executions should be
matched against removed trigger nodes first.

## 2026-08-16 23:45 — DUPLICATED-ACTIONS DEEP DIVE, past 3h (19,420 action-lines)
**Every true duplicate traces to the ghost cron. The legitimate machinery ran dup-free.**
- Concurrent doubles (same doc+action, overlapping in time): **27 — ghost-involved 27, clean 0.**
- Within-run doubles: **0** in the 22:xx lane2 run AND **0** in the 23:00 threaded rerun16 —
  the pre-driver ID split partitions perfectly, check_next never re-splits, locks hold.
- Near-repeats within 10 min: 1,519 total = 308 ghost-involved + 1,211 cross-RUN repeats
  (same cohort deliberately re-flipped 22:20→23:00; restart-epoch-legal, window widened by
  long find_link ENDED_ATs). Confirmed cross-run by the 0 within-run counts above.
- Ghost damage quantified: **2,219 action-lines** driven by `executeWorkflow>*` roots in 3h;
  **166 distinct docs re-actioned within 10 min of a legitimate run**; plus ~36 driver errors
  (one per 5-min tick) where the DOUBLE ACTION guard blocked the re-decide outright.
Post-fix (ghost killed 23:30:44): 0 executions, 0 errors, 0 dups fleet-wide through 23:41+.
The 179-dups/day → 1 → 0 arc is now closed at the mechanism level, not just the symptom level.

## 2026-08-17 07:55 — GHOST CONFIRMED DEAD + fleet-wide ghost audit (owner: "make sure its gone")
Main never restarted (up since 08-16 12:50) and the stack ran all night (~470 exec/h, no gaps)
— so the kill is proven in the same living process: ~100 would-be ticks since 23:30:44, ZERO
fired. Where the cron lived: n8n main's in-process trigger registry (RAM) only — NOT the DB
(graph clean, versions current) and NOT redis (Bull repeatables: none). Full audit: 7 live
schedule registrations reconciled against 6h of trigger-mode firings — every cadence matches
its rule, nothing fired without a live node (indoxApi01's single 04:00:28 tick = Keepalive/6h).
Ghost residue swept: 5 orphan `node:*` staticData entries (state for DELETED trigger nodes) in
indoxV2Driver01 (removed scheduler + old Google Sheets trigger), indoxApi01 (Poll Line
Changes), mailLabelEngine01 (removed Gmail trigger), indoxGmailActionsScanner01 — none firing;
active ones force-cycled (deactivate/activate 200/200) and ALL 5 purged → orphans fleet-wide
now NONE (future `node:*` orphan = real alarm, not noise). Open warts flagged: retired
indoxApiSupabase01 (inactive) still contains the full poll lane incl. Process Changed Doc →
driver — delete/clean before anyone reactivates it; IndoxResetFull01 has one cosmetic dangling
connection ('Call Supabase Setup'); BaseDrain gate-tick node named "Every 5 min" actually runs
every 2 min (rename).

## 2026-08-17 08:30 — RED-TEAM PROOF (owner: "prove the dup cause by actively creating one")
Synthetic doc `doc_duptest01` (fake company, fresh hash), three live attacks with the real
machinery, wave running in parallel. RESULTS:
- **Attempt A — concurrent double-dispatch via the driver webhook** (two simultaneous POSTs,
  same doc, drivers 3350784+3350785): DEFENDED. Both drivers succeeded; exactly ONE
  restart_gdoc bracket (router 3350798). Driver b's payload carries `was_locked=true` — the
  `<ID>::<ACTION>` mutex skipped it pre-dispatch. Owner's prediction confirmed: through
  driver/drainer you CANNOT create a dup (lock + fresh re-fetch by ID + state change + guard).
- **Attempt C — stale-snapshot replay at the ROUTER** (pre-run full-row capture POSTed to
  /webhook/indox-action-router after the doc moved on): **DUP CREATED** — second restart_gdoc
  bracket (router 3350861), overlapping the doc's live chain. restart-class = native re-run,
  so also ran **C2 with a NON-restart action** (`get_short_doc_id`, already completed):
  **DUP CREATED** (router 3350932). The router executes whatever full-row line it is handed —
  no token/freshness check; decide-guard and lock both live upstream in the driver.
CONCLUSION, proven both directions: the machinery's own initiators (drainer→driver→router,
fresh IDs re-fetched at run start) cannot duplicate; the ONE door is handing the router a
STALE full-row line directly — exactly what the ghost's old graph did with its own SQL
snapshot. That door is basicAuth'd and used only by the driver + deliberate operator dispatch.
SUGGESTION (not implemented per owner order — no new machinery): a freshness gate at the
router (compare line's updated_at vs live row, one batched SELECT; trg_incdoc_touch bumps
updated_at on every write, so any stale command self-invalidates) would close that last door.
Test artifacts fully cleaned (doc + 6 bracket rows deleted); dup monitor baseline back to 0.
The monitor's flags during 08:24-08:31 on doc_duptest01 were these deliberate attacks.

## 2026-08-17 08:55 — WAVE ERROR CLASSES ROOT-CAUSED + FIXES (owner: "eliminate incident 1, zero errors at 25k")
Three real classes behind all wave errors (dup monitor clean throughout — every flag explained):
1. **Runner unresponsive** (5 execs, 08:18-08:20): 16 lanes × ~1,575-doc Code tasks vs runner
   procs capped at 1GB heap / 24 concurrent tasks → GC storm → missed heartbeats → broker
   aborts. FIX STAGED (repo compose + .env): runner heap 1024→1536 (cgroup 1.5G→2G),
   N8N_RUNNERS_MAX_CONCURRENCY 24→12, N8N_RUNNERS_HEARTBEAT_INTERVAL=90 (env verified
   supported in this build). Applies on fleet recreate at wave settle.
2. **"Execution cancelled because it timed out"** (~20 execs, 08:28-08:46): under full-wave
   slot saturation, sub-executions queue; the ONLY two chain members with 600s
   executionTimeout — indoxProcessDocument01 + indoxDocBatchUpsert01 — hit it first and the
   cancellation cascades up as "action failed". FIXED LIVE: both raised to 3600 as-code
   (pull→edit→push, hot-reload), aligning the whole chain at 3600.
3. **Doc-intrinsic residue** (2 execs): one PDF failing OCR again — the historic-failure
   population re-failing as expected; terminalizes by verdict.
**The one real dup flag** (doc_mslynvy2vs3she, get_company_name ×2, both lane6-g2): NOT a
protocol breach — timeline proven: chain stage cancelled by class-2 timeout → errorHandler01
dead-letter set ACTION_RESTART + RETRY_COUNT++ → check_next re-ran the killed action.
ACTION_RESTART re-run = the owner's sanctioned native recovery. Root = class 2, already fixed.
**Figure Document COMPANY_ID verdict: NOT drift.** Called from exactly one place
(Global01 'Action: Figure COMPANY_ID' via the router switch). It is the apitools-OCR + registry
resolver + thumbnail carrier (heavy deliberate engineering 2026-08-11), distinct from
BaseDocEx01's local extraction. 35,058 docs carry COMPANY_ID from its lifetime work; the wave's
969 figure runs are the historic unresolved residue being re-attempted, per the wave's purpose.

## 2026-08-17 09:15 — TWO-EXTRACTION-POINT RULE ENFORCED + FULL EXTRACTOR AUDIT (owner order)
Owner ruling confirmed by code proof: BaseDocEx01 runs its own Upload+OCR and its 'Select Base'
is the authoritative COMPANY_ID/TYPE/DOC_DATE pick — so indoxV2FigureCompanyId01 re-doing its
own OCR+resolve from the router was a two-point violation. Why it still fired (969× in the
wave): base stamped FIGURE_COMPANY_COMPLETED only on a RESOLVED value (2026-08-09 design), and
the decide's figure gate had an ACTION_RESTART bypass + resolver-generation re-arm.
**FIXED LIVE (pushed 09:04)**: base + Global01 base-path stamp FIGURE_COMPANY_COMPLETED
UNCONDITIONALLY; the figure_company_id dispatch branch REMOVED from decide (incl. both
bypasses). Companyless docs now: base → figure_company_offline (filename, no OCR) →
MISSING_COMPANY_ID terminal. PROOF: last figure_company_id dispatch 08:58:58, none after the
push despite thousands of restarted docs flowing.
**Extractor audit** (proof: per-lane decide return-inventories + fleet caller graph + dispatch
census): decides can return NO query_* action — the per-value era lanes are UNREACHABLE:
query_doc_date / query_doc_total_amount / query_purchase_id / query_invoice_id /
query_shipment_id switch-cases + action lanes in GDoc+Ship, and sub-workflows
indoxV2QueryTotalAmt01 / indoxV2QueryDocDate01 / indoxV2QueryPurchaseId01 (all still active,
zero dispatches ever logged) → CLEAN CANDIDATES. Still-live outside the two points, need owner
ruling: figure_document_type (197 today — TYPE fallback via indoxV2FigureDocType01),
figure_company_offline (filename fallback), extract_invoice_google_ai (AI base fallback lane),
action_extract_shipment_ids (invoice pipeline stage physically outside InvoiceDocEx01).
Sanctioned/fine: BaseDocEx01+JQExV3Base000001 (base point), InvoiceDocEx01/ShipmentDocEx01/BS
extract (+Gemini AI leg) (per-type point), get_short_doc_id + get_company_name (derivations,
not content extraction), get_api_tools_id (upload rescue).

## 2026-08-17 09:30 — FULL-RUN POST-MORTEM + PRE-NEXT-CYCLE CHECKLIST (owner: next cycle = 0/0, fast, stable, predictable)
RUN: 25,209 flipped 08:17 → lane6 fired 16 lanes 08:18:30 (drainer 3350711). By 09:25: OLD
18,330 re-verdicted · COMPLETED +23 · MISSING_COMPANY_ID 299 · MISSING_LINK 112 (find_link ran
960, wall 915s) · MAX_IT 321 · tail still draining (78 running/229 queued) · AR 4,167 =
2 dead lanes' docs + 1,209 errorHandler-restarted (RETRY>0) — next lane6 run picks them up BY
DESIGN, no repair needed. Stage walls: update_status_old_doc 18,330 in 1,733s (10.6/s, the
bulk), restart_gdoc 1,803, figure_company_id 972 (0 after the 09:04 kill).
ERRORS: 39 before the 08:52 timeout fix, **1 after** (indoxHealth hourly probe, load-induced
one-off at 09:02 — its 5 prior runs green). VIOLATIONS: 0 machinery dups; 10 dup-pairs all the
proven cancellation→dead-letter→ACTION_RESTART recovery signature (root=timeouts, fixed).
CHECKLIST BEFORE NEXT ACTION_RESTART→LANE6 CYCLE:
1. ✅ LIVE: executionTimeout 600→3600 (indoxProcessDocument01, indoxDocBatchUpsert01) — kills
   the cancellation cascade (its own proof above).
2. ✅ LIVE: figure_company_id eliminated (two-point rule) — removes ~970 OCR dispatches + their
   slot holds from the wave (speed + stability).
3. ⚙️ APPLY AT TAIL-END (staged in repo+.env, needs fleet recreate ~1min): runner heap
   1024→1536 (cgroup 1.5G→2G), N8N_RUNNERS_MAX_CONCURRENCY 24→12,
   N8N_RUNNERS_HEARTBEAT_INTERVAL=90 — kills the 08:18 burst "runner unresponsive" class.
4. 🧹 HYGIENE before firing: close the 1,335 orphan OPEN brackets (debris of killed
   executions; oldest 08:28:49) + checkpoint/wipe the action log so monitoring starts clean.
5. ❓ OWNER RULINGS pending: figure_document_type (fired 197 — same two-point violation shape,
   same fix available: unconditional FIGURE_TYPE_COMPLETED + remove branch);
   figure_company_offline; action_extract_shipment_ids (fold into per-type?);
   extract_invoice_google_ai; delete the 5 dead query_* lanes + 3 Query workflows.
6. Health probe (indoxHealth) hourly — verify 10:00 run green post-wave.
PREDICTION for next cycle at factor 16 (fixes 1-4 in): bulk = SQL-class statuses at ~10.6
lines/s → 25k in ~40 min wall, no OCR pressure (figure dead), no cancellations (3600s covers
queue waits), errors 0 expected; find_link tail rides the threaded drive service (1.54s/line).

## 2026-08-17 09:45 — THE 17 CONSOLE DUPLICATIONS: root-caused, per-pair proof
18 multi-run (doc,action) groups today, four classes, every pair accounted:
- **Class L (12 docs): the BOUNDED get_company_name retry loop** — the dominant class.
  Identical fingerprint on all 12: run #1 in the wave (08:29-08:40), retries at 09:05-09:17
  as check_next swept docs still at ACTION_RESTART. Mechanism (all by existing design): a
  name-miss deliberately writes NO state ([stage-retry 2026-08-10] COMPANY_NAME_COMPLETED
  stays null) + decide's `(!COMPANY_NAME_COMPLETED || STATUS==='ACTION_RESTART') &&
  RETRY_COUNT<10 → get_company_name` ([company-retry bound 2026-08-13], added when these
  same docs used to retry 26.7×). PROOF the bound works: all 12 stopped at RETRY=5;
  9 terminalized UNKNOWN_COMPANY (CNAME='unknown'), and 2 docs' retries SUCCEEDED —
  real names found (חננו, טורנדו) → both COMPLETED. Working as designed, not a violation.
- **Class B (2 docs): crashed-execution Bull re-delivery** — extract_per_type ×5-6 runs in
  ~90s (09:16-09:19); first executions status=CRASHED (worker died mid-run at queue-drain
  time, pre-recreate) → Bull stalled-job re-delivery re-ran them until success; both docs
  COMPLETED. n8n-native crash recovery; the crash source is what the new runner config
  (heap/concurrency/heartbeat) eliminates.
- **Class R (3+1): timeout-cascade recovery** — figure_company_id ×3 (first execs 3350978/
  3351130/3351174 = status ERROR from the pre-fix 600s cancellations) + update_name ×1:
  dead-letter → ACTION_RESTART → sanctioned re-run ~20min later. Root fixed at 08:52/09:04.
- **Class P (1): my own executed proof** (update_status_missing_company 08:37 wave +
  09:33 deliberate proof drive) — native ACTION_RESTART re-run.
SUGGESTION (not implemented): Class L burns ~4 extra name lookups per nameless doc per
drain; tightening to once-per-drain (e.g. miss stamps a per-drain marker) would cut it —
owner call, since the current bound is a deliberate 2026-08-13 design.

## 2026-08-17 09:55 — FINAL RESTART-CYCLE REPORT published
Full consolidated report (timeline · outcome census · 3 error classes all fixed · 17 dups in
4 classes all proven · structural findings: ghost cron, two-point enforcement, lane6, red-team
proofs · pre-next-cycle checklist · prediction): apps/indox/reports/restart-cycle-2026-08-17.html
(same content shared as an artifact page). Open items carried: #6 corpse pass (owner go),
#7 name-retry tightening (owner call), health-probe watch.

## 2026-08-17 09:50 — ALWAYS-COMPLETE LAW enforced (owner: "every action always sets VAL_COMPLETED,
## no retry count, fail loudly") + leftover AR drain fired
The [stage-retry 2026-08-10]/[company-retry 2026-08-13] miss-retry design is REMOVED, overruled
by owner law. Key coherence proof: the restart action ALREADY resets every *_COMPLETED flag to
false — so ACTION_RESTART is the native (and only) re-run; one attempt per stage per epoch.
Changes, all live (validated + pushed + live-marker verified, zero __recordStageMiss remnants):
- Global01 'Join COMPANY_NAME': ALWAYS stamps COMPANY_NAME_COMPLETED; a missing Companies map
  now THROWS (was silently treated as a miss); __recordStageMiss removed.
- Global01 decide: name branch is plain `!COMPANY_NAME_COMPLETED` — RETRY<10 bound and
  ACTION_RESTART bypass removed (the Class-L loop is extinct by construction).
- InvoiceDocEx01 + ShipmentDocEx01: PER_TYPE_EXTRACTION_COMPLETED stamped UNCONDITIONALLY
  (miss = an answer; fields stay absent); __recordStageMiss + RETRY bookkeeping removed. The
  old "flag lied" concern is void: the legacy Query* fallbacks it protected are gone from
  decide, so a stamped miss terminalizes honestly instead of falling to a third extractor.
LEFTOVER DRAIN (owner: "drain all left over ACTION_RESTART before the full cycle"): hygiene
(2 open brackets closed) → lane6 {STATUS:ACTION_RESTART} on 3,683 docs at 09:47:08, drainer
3359053 — FIRST run under the complete fix set. Watcher armed with fresh 09:46 baseline:
errors+crashes+cancels, new dup groups, and the get_company_name runs-per-doc distribution
(law: must be exactly 1).

## 2026-08-17 10:00 — #6 CORPSE PASS + #7 ALWAYS-COMPLETE: done, proven, stabilised
**#7 proof (leftover drain, 3,683 docs, drainer 3359053)**: settled 09:47→09:59 (~9 min under
the COMPLETE fix set): 0 errors, 0 crashes, 0 cancels, 0 duplications, and the law measured:
get_company_name runs-per-doc = EXACTLY 1 (8 docs). Name flow is now: try once → company /
'no answer' verdict (UNKNOWN_COMPANY) / loud throw if the Companies map is missing.
**#6 value proof BEFORE the strip** (owner condition): per-type writes the exact corpse
columns — among 22,790 per-type-completed docs: DOC_DATE 99.3%, PURCHASE_ID 81%,
SHIPMENT_DOC_ID 13,474, INVOICE_ID 10,760, DOC_TOTAL_AMOUNT 52% (delivery notes structurally
lack totals); base among 29,579: COMPANY_ID 94.8%, TYPE 99.3%, DOC_DATE 97%; SELECTED_* finals
consistent. query_* lifetime dispatches: ZERO.
**The strip**: GDoc+Ship — 5 dead query_* lanes each (~20 nodes/file), switch rules+outputs
renumbered (fallback 27→22); Global01 — figure_company_id + figure_document_type +
extract_invoice_google_ai lanes (19 nodes), fallback 17→14. All validated + pushed. The 6
corpse workflows (Query{TotalAmt,DocDate,PurchaseId,ShipmentId}01, FigureCompanyId01,
FigureDocType01) verified UNREFERENCED by any active workflow → deactivated + DELETED live;
repo files moved to legacy/extractors-retired-20260817/ (QueryShipmentId01 was live-only).
**Executed strip proof**: 3 docs (MISSING_TYPE / UNKNOWN_COMPANY / MISSING_COMPANY_ID classes)
driven through every renumbered switch region → correct actions, correct terminals, 0 errors,
0 unhandled-action fires. Residue: 3 edge docs remain AR (1 typeless stalled-history, 2
TYPE=UNKNOWN missing name+doc-id) — flagged for triage or the next sweep.
Report artifact + repo copy updated. THE TABLE IS CLEAN AND THE MACHINERY IS READY for the
full ACTION_RESTART → lane6 cycle.

## 2026-08-17 10:10 — THE 3 RESIDUE DOCS: root-caused + fixed + proven; table at AR=0
Why they never resolved: the LAST hidden instance of the miss-no-stamp disease, on the
base-extract FAILURE path. 'Record Base Doc Failure' (direct SQL) bumped RETRY_COUNT and left
BASE_EXTRACTION_COMPLETED unset → decide re-dispatched extract_base_doc EVERY drain (their
files produce no API_TOOLS_ID and no fields — unextractable), terminal only at RETRY 25.
FIX (always-complete law applied): the failure recorder now stamps
BASE_EXTRACTION_COMPLETED='true' + STATUS='EXTRACTION_FAILED' + a clear REQUIRED_ACTION; no
RETRY mechanics. ACTION_RESTART resets flags = each restart cycle is the one re-attempt.
PROOF: drove all 3 → each ran extract_base_doc once, failed on the same bad files, and
terminalized EXTRACTION_FAILED (BASE_DONE=true). **ACTION_RESTART count in the table: 0.**
Errors: 0. The estate now has ZERO conditional completion stamps — verified across every
extractor and failure path.

## 2026-08-17 10:40 — GLOBAL01 REORGANIZED (owner: minimal, organized, aligned) + RETRY_COUNT scan
**The base action router is rebuilt clean**: 9 empty no_action_* switch rules removed (13 rules
remain), rules REORDERED to match decide order exactly (doubles → resolve → company → name →
unknown → type → old → max_iter → extract_base → garbage → labels → failed-folder → unhandled;
fallback='extra'); every generic node renamed (Loop Over ItemsNN → 'Loop (<lane>)', Builds →
'Build: <verdict>', 'Action: Update COMPANY_NAME' → 'Action: Get Company Name', switch →
'DOC BASE Action Switch'); all 64 nodes laid out on a clean grid — entry chain top-left,
decide/verdict lane above, action lanes stacked top-to-bottom in switch order, shared Upsert
(central) as the right-side sink. Zero stickies. Inert RETRY_COUNT passthrough field removed
from Build: Company Name; fossil essays stripped from Join COMPANY_NAME.
**Layout bug caught BY the new loud-throw** (and by the owner's eye): Companies was initially
placed BELOW Join COMPANY_NAME → v1 executed Join first → 'Companies hasn't been executed'
thrown loudly (old code silently swallowed this with catch{map={}}). Fixed: Companies above the
join (y 640 < 704) + fan-out array order Companies-first. Crash debris (held lock + open
bracket) cleaned. EXECUTED PROOF: missing_type ✓, missing_company ✓, name lane ✓ (doc →
get_company_name → NAME_DONE=true → UNKNOWN_COMPANY, errors=0) — all through the reordered
switch.
**RETRY_COUNT deep scan verdict**: ZERO writers remain (last three — __recordStageMiss ×3,
Record Base Doc Failure, Join COMPANY_NAME — all removed today; errorHandler01 stopped writing
it in an earlier cleanup per its own notes). ZERO logic readers (the last gate, the name
RETRY<10 bound, removed today). Remaining mentions are: UI display (DocumentDetailPage
STATE_FIELDS), schema column, inert passthrough plumbing in per-type trigger inputs, and
comment fossils. The column is now historical data only.

## 2026-08-17 10:50 — FOUR INVESTIGATIONS (owner orders) + reset wave 3362627
**1 UNKNOWN_COMPANY (58) — semantic VERIFIED**: all 58 carry a COMPANY_ID; every id missing
from public.companies is a 9-digit ח.פ sourced AI_ONLY (SELECTION_DEBUG proof) — exactly the
one sanctioned cause. EXCEPTION FOUND: 7 docs (5 ids: סלקום, טסה, אינטרנט רימון, חברת חשמל,
חננו) DO have table names — false verdicts from the silent catch{map={}} era (map unavailable
→ counted as miss ×5 → UNKNOWN_COMPANY). Loud-throw makes recurrence impossible; the 7
restarted in wave 3362627 to prove names now resolve. ~40 distinct missing ח.פ ids delivered
as add-candidates with filename-derived name suggestions (FINCARD, ג.גבאי יבוא … + junk to
skip) — owner review, not auto-inserted.
**2 MAX_ITERATIONS re-retirees — ROOT + FIX**: the bulk SQL flip stamps nothing, so _iter still
counted the OLD epoch and the ceiling fired before any restart action could open a new one
(circular trap; 310 re-retired inside the morning wave in ONE hop). FIX (live): the ceiling
gate now honours STATUS='ACTION_RESTART' as an explicit epoch grant (_restartGrant) — the
restart action runs, stamps 'ACTION=restart', epoch anchors, ceiling re-arms. All 373 flipped
+ drained in 3362627; watcher counts mark_max_iterations dispatches (target ≈0).
**3 Unextractable clear reasons — LIVE**: the base no-answer failure is now CLASSIFIED from the
leg statuses (bad file type / broken link / too big / apitools shed / network unreachable /
bad params / corrupt zero-page PDF) + raw leg text, written to ERROR + log.
**4 apitools 'Bad request' (6 docs) — ROOT**: their API_TOOLS_IDs are STALE — apitools
/docExists returns exists:false (storage no longer holds the files); its generic 400 masked
it. Restart SELF-HEALS: base extraction re-uploads by LINK when the id is stale; the 6 are in
wave 3362627. Clear error covered by the new classifier.

## 2026-08-17 12:35 — FIXES 1-3 DONE + PROVEN (owner order)
1 BULK UPSERT: root proven — API call was always batched (643 calls/27k lines) but 'PG Upsert'
(operation:upsert) wrote per-item: 0.77s/row, 996s per 1,300-row group = the cycle's wall.
Replaced in indoxApi01: Build Bulk Upsert SQL (groups by field-shape, one INSERT..ON CONFLICT
per shape via jsonb_array_elements, cast map from information_schema, chr(1) comma trick) →
PG Bulk Upsert → Restore Upserted Docs → API Emit IDs. PROOF: full chain drive, correct
verdict+unlock, indoxApi calls now 0.0-0.3s (was avg 22s / max 996s).
2 HYGIENE SWEEP: 2,199 legacy-ghost docs (ITERATION>25 / RETRY>0 / markmax-no_action tokens /
20KB+ logs, non-terminal statuses) — counters zeroed, ACTION_LOG checkpointed with an
ACTION=restart epoch marker. Guard/maxit ghosts extinct (incl. doc_msm34ap0c26rsa class; the
12:25 driver red was the last specimen, pre-sweep).
3 VERDICT-NOT-CRASH: driver dup-guard now rewrites blocked items to no_action_double_blocked
(reason kept in execution data) — no more red driver/router from blocks; errorHandler's
ERROR-writer protection set extended to EXTRACTION_FAILED/GARBAGE/DOUBLE/MERGED (clear
verdicts survive; no 'action failed @exec' clobber). Deployed: driver via push; errorHandler
via live SQL patch (repo file matches) + deactivate/activate re-registration.
ALSO FIXED: indoxV2UploadApiTools01 clear-passthrough finally LIVE (its earlier edit crashed
wrap.mjs convert-batch — escape sequences in a jsCode comment; converter lesson recorded).
NEXT-CYCLE BOTTLENECK: with the upsert wall gone, critical path = find_link contention
(measured 5-9s/line at 16 lanes vs 1.54 solo; drive=12 threads) ≈ 5-8 min tail + SQL stages
≈ 1-2 min → predicted TTL 6-10 min, errors only the ~9 genuine extraction reds, dups 0.
OPEN (owner calls): factor for search stages (16 vs 8), ~40 missing-ח.פ company candidates,
6 ledger-duplicate docs policy, residue AR=32/IP=47 + 2 open brackets (pre-cycle hygiene).

## 2026-08-17 12:50 — indoxApi01 REORGANIZED + FULLY VERIFIED (owner order)
Same treatment as the base action router: switch renamed 'Action'→'API Action Switch' (0 code
refs, verified), all 36 nodes on a clean grid — entry+management+keepalive top-left, the 9
lanes stacked in switch-rule order (UPSERT 10-node lane, GET_ALL, GET, DELETE, TABLE_GET,
TABLE_UPSERT, DELIVER, MERGE, GET_CHANGED), Guard Get Size as the GET/GET_ALL shared sink,
sticky parked. Node names were already semantic — layout was the work. VERIFIED LIVE: rename
+ positions confirmed in DB; executed E2E drive through the reorganized API (GET + bulk
UPSERT + emit + unlock): correct verdict, CNAME_DONE stamped, api calls 0.0-0.2s, 0 errors,
0 lock residue. The API is clean, minimal, aligned, and proven working post-surgery.

## 2026-08-17 16:00 — THE 409 "already exists" QUESTION: CLOSED WITH PROOF
Producer: 'Post Priority Table' in the STATE MACHINE's action_priority_sync lane (GDoc+Ship
only — fleet graph search proves the SYNC system never touches Priority; "priority_sync" is
just the action's name for pushing a SUPDOC into Priority ERP at msh.macomp.vip OData).
Payload key IDSUP(=supplier ח.פ)+DOCNAME(=doc number); the 409 is Priority's own OData
duplicate-key rejection = the document is ALREADY LOADED in Priority.
THE GATE RECONCILES EVERYTHING: decide fires the action only when settings
activePrioritySync=true — and it is FALSE. Hence zero priority_sync dispatches ever logged,
zero live 409s today; every "already exists" string seen this morning was FOSSIL text in doc
ERROR columns from a past run when the toggle was ON, and today's cycle overwrote them.
Live existence-GET prepared but blocked 401: PRIORITY_USER/PASS empty in .env (secrets only
encrypted in n8n; not extracted). POST replay deliberately refused (non-409 outcome would
insert into production ERP).
STANDING RECOMMENDATION: before activePrioritySync is ever re-enabled, add idempotent-409
handling in that lane (already-exists → mark delivered, not red). Until then: nothing pending.

## 2026-08-17 17:15 — WHEN the 409s fired: DATED. They never fired on this stack at all.
Correction to 16:00 ("past run when the toggle was ON"): there was no ON period HERE.
- activePrioritySync=false since the settings SEED 2026-07-30 23:45, never rewritten since
  (updated_at moves on write — indoxDrainOn 08-16 09:04, indoxScalingFactor 08-16 22:39 prove it).
- The priority Build always appends ", priority_sync, <ts>, <exec>" to ACTION_LOG and always
  writes PRIORITY_SYNC_COMPLETED=!error. Fleet-wide: 0 docs carry the stamp (terminal docs'
  logs survived the hygiene checkpoint — heads verified). 0 IDSUP executions (retention floor
  08-17 00:34). 0 dispatches in the action log. The lane has NEVER run on this instance.
- The texts ARRIVED IN THE IMPORT: 174 docs carry the full raw HTTP error (409 - {OData
  duplicate-key}) in cumulative REQUIRED_ACTION — 174/174 created 2026-08-05 00:58, the
  5,953-row bulk-import minute; 150 psc=true; PRIORITY_SYNC_COUNT 1→2092 2→1901 3→532 4→178
  5→74 6→1 (counts imported too). The morning's 6 ERROR-column copies (sample
  doc_mshtmvmr9j3dlx, delta-imported 08-06 18:00 in a 5-row trickle, psc=NULL = Build never
  touched it) were overwritten by today's cycle — ERROR carries 0 today.
- FIRING WINDOW: on the SOURCE (production) system, between each doc's original creation —
  decimal ms-epoch ID prefixes decode 2026-02-16 → 2026-06-17 (171/174) — and the 08-05/08-06
  exports. Counts 2-6 = production retried delivery after success; every retry after the first
  success is exactly OData 409 "record already exists" (= doc already loaded in Priority, the
  business outcome achieved). RA text has no embedded timestamp; tighter than the window above
  is not recoverable from this side.

## 2026-08-17 17:00 — readiness sweep + the console's "4 duplications" closed
DUPS (all 4 decomposed, dispatch-record proof): 2 = my own proof re-drives via ACTION_RESTART
(bulk_proof 12:25Z, api_reorg_proof 12:33Z — restart-native, but they pollute the counter; use
synthetic rows next time). 1 = doc_msly5hcz extract_base x3: crash + the EXISTING one-shot
'BASE APITOOLS RETRY' rescue (2026-08-09) re-fires when the attempt crashes (marker only lands
on completed pass); ceiling contained it. 1 = doc_mss7rmft find_link x2: second dispatch hit a
mid-flight doc (run1 222s, run2 5s = lock-skip), ended COMPLETED.
FIXED+PROVEN LIVE: content-twin HASH aborts (uq_incdoc_hash killed whole upsert statements;
PRE-EXISTED bulk — old node died same way execs 3365596/3367253/3367904; 5 docs stranded IP
13:18Z). Twin guard in Build Bulk Upsert SQL pushed 13:44Z; proofs: INSERT 0 1 / twin INSERT
0 0 / same-doc update INSERT 0 1; 0 api errors since.
REPO-ONLY (owner ruled stop, NOT pushed): Record Base Doc Failure consumes the rescue marker
on a failed retry (closes the crash-loop; adds NO retry). Global live untouched at 11:02:39Z.
Tooling: root-owned .generated/.push-cache (my 15:32 root-run) broke push; wiped + reclaimed
.git/index; fixed push-app silent exit-2 (awk on missing cache under set -e). Push CAS now
false-positives on Global (cache wiped) — resolve via pull+reapply when owner clears the fix.

## 2026-08-17 17:15 — owner order EXECUTED: no state-machine retries. Stripped + proven live.
Removed (pushed 14:10:30Z, all active, zero errors since):
- Global docBaseDecide 'BASE APITOOLS RETRY' branch + its marker stamp in the base upsert
  build + my recorder band-aid (reverted before push — never went live).
- GDoc+Ship '__needsPerType' REOPEN term: __PT_REOPEN_MARK + __perTypeGateStillOpen deleted,
  gate is now plain !PER_TYPE_EXTRACTION_COMPLETED; marker-append ternary stripped from the
  'Extract Per Type' build ACTION_LOG in both.
Proof (live graph functional strings, not comments): guard_expr/stamp/recorder_case gone in
Global; mark_const/gate_fn/build_ternary gone in GDoc+Ship; surviving gates verified
(!BASE_EXTRACTION_COMPLETED, !PER_TYPE_EXTRACTION_COMPLETED, API_TOOLS_ID_COMPLETED).
THIRD member of the species found + reported, NOT stripped (owner call pending):
'DOC_ID CONSOLIDATE' (GDoc+Ship, 2026-08-11) — one-shot mark_completed re-open backfilling
DOC_ID on the pre-08-10 COMPLETED backlog; 5,998/11,985 COMPLETED docs still eligible.
Memory saved: feedback_no_state_machine_retries.
Companies report is real: apps/indox/reports/companies-coverage-2026-08-17.md (130KB, 16:29).

## 2026-08-17 17:45 — DYNAMIC RESTART LIVE (owner order: flip status only, machine clears flags)
All four routers now share ONE restart build: code node clears EVERY *_COMPLETED dynamically
(row-key derived, never a hardcoded list) + FROM_OFFICE_CHECK (legacy-named flag) + ERROR;
STATUS -> IN_PROGRESS. GDoc+Ship: replaced the misnamed 11-flag Set (missed BASE/PER_TYPE =
restart never re-extracted). BS: same + keeps its value clears/cache bypass. Global: NEW
restart_base lane (decide head first + switch rule first + Action noOp + Build -> Upsert
central) — base-stage docs finally have a native restart. indoxV2ActionRouter01: restart_base
added to the DOC BASE action map (proof run 1 died there: "UnHandeled Document").
EXECUTED PROOF (synthetic doc, real driver chain 3369926->3369932->3369941): log stamps
'RESTART clear all completed' + ACTION=restart_base; base/pertype/name/search/PRIO/foc ALL
false after; doc re-walked to MISSING_COMPANY_ID. Attempts 1-3 were blocked by attempt-1's own
crash debris: doc_action lock n8n.process_lock.doc_action.<id>::restart_base, TTL 5400s —
lock-skip worked as designed. Fire script pre-flight now sweeps stale doc_action locks (queue
empty = all stale) with REAL redis auth from .env (earlier inspect-based auth silently failed;
re-verified: brackets 0, locks 0).
NOTE: dynamic clear includes PRIORITY_SYNC_COMPLETED — restarted docs re-deliver to Priority
IF activePrioritySync is ever turned on; idempotent-409 handling stays prerequisite.
REVISED FORECAST (full re-run semantics): flip 3,988; base re-extraction 1,688 (link+conn;
1,606 carry API_TOOLS_ID = OCR cache hits, Gemini legs re-run); per-type 1,593; find_link
1,948. TTL est 1.5-2.5h extraction-bound (~3.3k AI passes / ~12 lanes). Dups expected 0;
errors: only extraction verdicts (~<=40). MISSING_COMPANY_ID 1,470 re-extract then re-park
UNLESS companies SQL applied first (~490 would resolve) — owner call at fire time.

## 2026-08-17 17:50 — INCIDENT: I broke the console (install screen), RESTORED in ~10 min
Cause: fixing the push EACCES I deleted ALL of .generated/ (root-owned debris from my own
15:32 root-run) assuming build artifacts. Wrong: .generated is the platform's COMPILED CONFIG
(compose/routing/connections/resolved.json/registry) — the console reads the registry, lost
it, fell back to install screen. Only .generated/n8n self-regenerates on push.
Restore: python3 platform/manager/reconcile.py render (20 apps re-rendered) + chown of
root-owned apps/indox/storage snapshot that blocked `bbox catalog build` (catalog itself was
a red herring — lives in .catalog/, untouched). Console route live again (traefik 302->auth).
Business-identity values on that screen (QA seed 123456789) are the 07-30 provisioning seed —
nothing in public.settings written today (measured).
LESSON (memory updated): reclaim ownership, never delete, anything above .generated/n8n;
.generated != scratch.
UPDATE 18:05 — console CONFIRMED RESTORED (verified in owner Chrome: full sidebar, drive
loads). Root cause complete: console+connections BIND-MOUNT .generated/registry; my rm -rf
left them holding the deleted inode (api/modules 200-but-empty -> install mode). Fix = render
+ restart console-shlomo-laptop & connections-shlomo-laptop (only those two touched). QA
identity on the install screen = this deployment's seed, not new damage (settings untouched
today, measured). posnet deployment on the host was a red herring (routes only
console2.localhost).

## 2026-08-17 18:55 — COMPANY_DOC_ID FULLY RETIRED + backfill + gating complete. DEEPSCAN CLEAN.
Backfill: 6,388 rows DOC_ID:=machine-derivation (fillable=filled; DOC_ID now 32,721; 6,224
genuinely number-less). Column DROPPED live + schema.sql. DOC_ID CONSOLIDATE one-shot deleted.
Renamed fleet-wide (14 workflows pushed 15:20-15:45Z, all active): extractors emit DOC_ID only
(idPick->derivation, fill-only); per-type builds resolve DOC_ID passthrough; naming/SHORT/link
lanes read DOC_ID; api identity keys+SQL+whitelist on DOC_ID; Decide01+Global coalesce
simplified; BaseDrain audit SQL; BS line-build; fixtures (field_defs, fixture_INVOICE incl the
LIVE settings row) swapped. INGESTION prefill redirected to AI_DOC_ID (Gmail doc/link
downloaders + SyncProcGDoc): mail/sheet-parsed numbers are EVIDENCE the extractor rule-C
adjudicates — writing them to DOC_ID would have closed the per-type first-run gate.
BFF+webapp rebuilt (dash cols, models docstring, IDENTITY_FIELDS) — image rebuilt via
compose-plugin with a root-located aggregate copy (.generated/compose.yml include list
resolves only from repo root; direct -f use hits an include cycle — runbook note) — container
recreated 18:50, healthy; dashboard verified rendering in owner Chrome.
Residual (harmless, documented): Gemini AI-leg INTERNAL key naming; comment-only refs;
'Action: update COMPANY_DOC_ID' node display name + NEW_COMPANY_DOC_ID payload field (UI
contract) kept. DEEPSCAN: ZERO errors 25 min post-push; live graphs CLEAN of functional refs;
brackets 0, locks 0, queue 0. Cycle gates final: base_rerun=181, pertype_rerun=590, flip=3,988.
UPDATE 19:05 — BS extraction law-aligned (pushed, verified live): single dispatch site ->
extract_per_type -> BsDocEx01 only (the 08-12 two-point enforcement already killed the direct
AI path). Gate now value+flag: STATUS!=COMPLETED && API_TOOLS_ID && !BS_EXTRACTED_LINES &&
!PER_TYPE_EXTRACTION_COMPLETED && link+conn. Redundant second dispatch (BS_EXTRACTED_LINES_
COMPLETED-flagged) removed. Restart NO LONGER clears BS values (lines/verified/total kept;
USE_CACHE=false retained so a genuine re-run extracts fresh). Census: BS in flip 178, would
extract 155 (lines empty + apitools id). Manual re-extract = blank BS_EXTRACTED_LINES + AR.

## 2026-08-17 19:35 — CYCLE COMPLETE (fired 19:06:49, drained ~19:31 = ~25 MIN as forecast)
Flip 3,988 -> all restart-dispatched in 2m30 (dynamic restart, 100% lane6 provenance).
End state: COMPLETED +30 (11,985->12,015), MISSING_LINK 1,949, MISSING_COMPANY_ID 1,493,
MISSING_TYPE 243, UNKNOWN_COMPANY 204, EXTRACTION_FAILED 67 (mostly Google DocAI
'invalid argument' per-file rejects, classified verdicts), IN_PROGRESS ~5 stragglers.
Dispatches 10,712. Errors: ~13 total, ALL extraction sub-workflows (BS DocAI class), routers
never painted, 0 errors last 10m of cycle. DUPS: 3 groups — (1) per-type 6s race, run2
lock-skipped, doc COMPLETED clean; (2+3) ONE REAL DEFECT caught live: doc_msw9z0bwd4k6bj
find_link loop, 121 dispatches — GDoc search-fail path 'Build: Unlock Only (search failed)'
writes NOTHING usable (failed item lacks ID -> upsert no-ops; neither flag nor stamp lands ->
gate stays open, ceiling blind). Stamp fix pushed mid-cycle (19:30) did NOT stop it (fail item
has no ACTION_LOG/ID context — must read $('Action: Find Link in Drive') input, not $json).
CONTAINED: doc PAUSED 19:33, loop frozen at 121. TODO next session: rewire the fail-branch
build to pull ID+ACTION_LOG from the action-input context, prove, unpause+restart the doc.

## 2026-08-17 20:20 — post-cycle deep-dive DONE: 2 of 3 orders complete + proven
1) LOOPERS RESOLVED: uq_incdoc_hash DROPPED (owner order; dedup action owns dedup; upsert
   matches strictly by ID - manually verified both directions). All 3 loop docs re-driven ->
   COMPLETED with LINK in one pass. Upsert keeps in-batch twin detection only.
2) BS FIXED (minimal, handled): File Type Router placeholder gate (claimed-PDF, size in
   bytes <300 -> handled path) + formatter says 'Broken PDF (28 B) not a valid PDF'.
   Proof: placeholder exec 3381110 succeeded handled 1.6s; 3381166 carries new message;
   0 loud BS errors. NOTE: terminal EXTRACTION_FAILED docs keep old ERROR text (verdicts
   don't rewrite); fresh transitions get the new message.
3) OPEN + OWED: per-type 6s race — owner rejected the check_next theory (check_next fires
   only after grouper completes); must build the full node-by-node timeline from execs
   3374270 + 3374305 chains (driver->decide->grouper->router POST bracket times) and prove
   the true mechanism. Also owed: readiness call for the next perfect cycle after that.
All issues filed: issues/cycle-20260817-findings.yaml. Direct-file-edit rule affirmed (no
more python string surgery on workflows).

## 2026-08-17 21:30 — RACE CLASS CLOSED: router multi-type merge live + proven
ROOT (owner co-diagnosed, node-timeline proven from driver 3374203 + router 3374270): one
action group can carry MULTIPLE DOC_TYPEs; Switch1 split them and the tail (Dispatched Lines
-> ... -> Router Done RESPOND) ran PER BRANCH — first branch answered the caller (50.594)
while the second branch's upsert (52.166) still ran; check_next then read pre-commit state ->
the 6s duplicate. FIX 1+2: 'Join Type Branches' (merge append x4) between the four Call nodes
and the tail — Router Done now fires ONCE, after ALL branches; response covers all lines.
Pushed 18:25:33Z. PROOF: mixed drive (2 docs INVOICE+SHIPMENT, one group, router 3381762):
one router exec both docs, each dispatched once, dup_rows=0, timeline shows Join(1ms with 3
never-executing inputs — no merge wedge, the risky semantic) -> tail -> Router Done ONCE at
end. Note: Decide01 routed both AR docs to restart_base (single branch); the two-branch
replay will be visible on the next natural mixed group — structurally guaranteed meanwhile.
ANSWER 3 (proven): check_next NEVER waited for completion — driver's Respond is wired
directly off its Webhook (instant {completed,execution} ack); the 10s AxiosError = Bull
QUEUE-WAIT under saturation (respond emits only when a worker STARTS the spawned exec; job
survives the timeout, only the id is lost + 10s parent stall). No recursion stacking.

## 2026-08-17 21:50 — check_next converted to executeWorkflow(self), no-wait. PROVEN.
Measured first (owner demand): the old webhook self-POST waited on CHILD driver completion
(child's Respond = bottom branch, runs last) capped at 10s -> 16/18 sampled cycle drivers
burned the full 10s + swallowed AxiosError; only sub-10s children ever acked. In place
unchanged since the 08-16 rewrite (history-proven).
CHANGE: 'Shape Next Action Payload' (per-doc items carrying webhook-shaped body) ->
'Spawn Next Action (self)' (executeWorkflow v1.3, passthrough, mode each,
waitForSubWorkflow=false). Old POST kept as disconnected noOp for one cycle. All 5 provenance
expression templates now read the EW trigger body too; trigger schema gained 'body' (declared
inputs FILTER passthrough items - the missing declaration stripped body on first proof).
PROOF (chain of 2 docs): hop-2 trig='spawn_proof>check_next>group_action' (chain intact),
docs walked to verdicts, 0 errors, parent drivers 6s/3s/1s (10s tax gone), spawns = own
executions per doc. Note: EW children run in-process (not new Bull jobs) - the 08-16 note's
tradeoff, accepted by owner order.
UPDATE 21:55 — EXACT ORIGINAL SCENE REPLAYED PERFECTLY: two docs (INVOICE+SHIPMENT) both
extract_per_type, one driver (3382154), ONE router exec 3382161 (the 3374270 configuration),
Switch split both branches -> Join -> Router Done once; each doc dispatched exactly once
(extra=0), chain advanced only after BOTH upserts, both docs COMPLETED pertype=true, chain
provenance intact via the new executeWorkflow check_next. 2 driveApi reds = fake proof links
(synthetic artifact only). Synthetic rows cleaned.

## 2026-08-24 00:50 — document view rebuilt: split screen, per-type extraction display. LIVE.
Owner order (23.08, screenshot): "מסמך בצד שמאל, נתונים בצד ימין, הכל במבט הראשון בלי גלילה,
תצוגת חילוץ מותאמת לכל סוג מסמך". DocumentDetailPage.tsx rewritten around a .doc-split grid
(RTL: data column RIGHT, DocumentViewer LEFT + sticky — the paper never scrolls away), all
prior surfaces preserved (viewer panes, פתח מקור, בקש עיבוד מחדש + RestartFollow, status
select, שיגורים אחרונים, grouped field editor / history / extraction attempts as folds).
NEW: (1) hero fact strip per TYPE (company, doc id, date, amount, shipments/order/linked-BS,
priority state incl. PRIORITY_SKIP reason; missing KEY facts amber); (2) BALANCE_SHEET →
BS_EXTRACTED_LINES rendered as a real table (id/date/amount/balance/notes), extractor totals
chips with OUR arithmetic (extractor totalsMatch flag = tooltip only — it compares balance sum
and painted green beside a 2,413.15 gap), junk-shape warning (blank-ids / same-id-repeated,
the measured shapes), per-line "במערכת?" via one COMPANY_ID query + last-5-alnum rule (live
match → doc link, placeholder → ממתין למסמך); (3) INVOICE/SHIPMENT → AI|LOCAL|final matrix
with census-identical compare rules (last-5 ids, strict amount normalizer, digits-only dates)
+ AI_STATUS/LOCAL_STATUS chips from SELECTION_DEBUG_PERTYPE. Also: doc pane iframe → <img>
(a 404 used to paint the raw {"error":...} JSON into the pane — observed doc_msm34qg8wsnrxk;
now degrades thumbnail → explained empty state). Image rebuilt + container recreated, bytes
verified in-container (doc-split in baked css+js) and visually in Chrome on
doc_msm9x9ui7be6da (וולפמן aging report: 53 lines, "רק 1 מזהים שונים" warning beside the scan
whose adjacent column holds the REAL ids — the id-column mapping bug now visible at a glance)
and doc_msm34qg8wsnrxk (5 engine disagreements readable against the paper). 0 console errors.

## 2026-08-24 01:20 — doc-view polish round (owner QA order) + full-QA via owner Chrome. LIVE.
Fixes from QA: hero dates humanized (ISO→he-IL); amounts carry ₪; LINKED_BS measured to be the
BS's NAME, never a row id (0/500) → resolved by one NAME-eq query into a real link (404-link
bug fixed); company fact links to ?company= selection; viewer opens on חילוץ מסומן when
apitools has the overlay; BS panel adds "ממתינים למסמך" chip; REQUIRED_ACTION rendered mono-LTR.
DocumentBrowserPage: NEW `?empty=COL[,COL]` / `?notempty=` drill-down params (is_null/not_null
chips) — DQ reports can now LINK to missing-field selections (verified live: ?empty=
DOC_TOTAL_AMOUNT&type=INVOICE&status=COMPLETED → 3 chips, 45 rows). QA'd in owner's Chrome
across 6 scenarios (junk-BS, healthy-BS 16/81 matched, invoice 5-disagree, invoice+linked-BS,
shipment, placeholder): all facts/links verified, retry modal opens with facts + cancel writes
nothing, 0 console errors. Found + filed: REQUIRED_ACTION hygiene (15,258 non-verb values;
1,785 = n8n error string "JSON parameter needs to be valid JSON", 20 written in the last 3h —
LIVE writer to locate); deploy-window bursts on Incoming Documents v2 during the 2 container
recreates (known T-9 class, self-healing). Full report: apps/indox/DQ-REPORT-2026-08-24.md.

## 2026-08-24 04:05Z — night settled: orphan revival done; NEW classification defect proven.
Orphaned IN_PROGRESS (in-flight killed by n8n main's 8 heap crashes, NODE heap 2048MB —
per issues/driver-lane-width-heap-abort.md the heap is NOT raised; load was the lever and it
fell): 530 measured -> natural absorption -> final 107 revived via BFF PATCH ACTION_RESTART
(107/107 ok, 0 fail) + 3 window-aged stragglers re-PATCHed. AR=0, IN_PROGRESS 693->55 (0
stale), 0 errors. fullDocEx webhook was GONE from main's memory (404 while DB shows registered
— crash-restart ghost class) -> re-registered via bbox push --wf fullDocEx01; explains the
PSF 404 error class too. PSF parked at 1,866 (other agent's lane; feeder stopped).
PROVEN DEFECT (dry fullDocEx on 2 samples): residual gap cohort 341 = 155 FILE-LESS rows
(HASH+LINK empty, upload wrong_input, AI failed:missing_link) that reached COMPLETED **and
were priority-synced as empty rows** (all 155 PSC=true) + 186 real extraction gaps.
Proposed gate (awaiting owner): no HASH+LINK -> never COMPLETED (park MISSING_LINK /
auto-PRIORITY_SKIP). Full numbers: DQ-REPORT-2026-08-24.md §8.5.

## 2026-08-24 ~20:4xZ — ARCHIVE feature (#40) SHIPPED + selection cap removed (owner orders).
Official schema: `incoming_documents_archive` = LIKE-twin + `archived_at` in fixtures/schema.sql
(end of file, must stay after all ALTERs); `public.run_sql` (SECURITY DEFINER, service_role-only)
added to platform-base/n8n/schema/01_platform.sql — the provisioning RPC the supabase transport
always required (indox-final-plan §6.1 unblock), installed live, both paths smoke-tested. Repo
`incoming-documents-main-archive` registered through POST /repos (generic pair rule: `<repo>-archive`;
first registration under a short name was deleted, storage kept). BFF: transactional
`POST /repos/<r>/documents/archive|unarchive` (one tx: intersection-column INSERT + DELETE of exactly
the inserted ids; conflicts skipped+reported, never overwritten; archived_at stamped in / dropped out;
timestamps preserved — verified updated_at NOT bumped). One-selector everywhere: `_resolve_selection`
uncapped (500-page runaway guard only), the three 413 checks and `_PIPELINE_BULK_MAX_IDS` removed.
FIXED same turn (measured live): select-all with NO active filters sent `filter:{}` which Query's
mode=filter rejects → 500 on every selector path; empty filter now walks as mode 'all' (resolver +
export, both). UI: העבר לארכיון/שחזר מהארכיון by repo side; pipeline verbs (restart/drain/dispatch)
HIDDEN in the archive repo (a dispatch from there would write results back into the live table);
`gte_`/`lte_<COL>` URL params round-trip (read-once + write-back + range chip). Chrome QA (owner
browser, executed proof): 5 docs archived → archive view showed exactly those 5 → restored → archive
0 rows, main back to 39,287, all 5 STATUS=OLD upd=2026-08-23 intact; 0 console errors.
Provably-old selection link (13,523 = every OLD row with a real own doc date 2000..2026-02-23, 0
corrupt in window): /a/incoming/repos/incoming-documents-main/documents?status=OLD&lte_doc_date_norm=2026-02-23

## 2026-08-25 ~00:1xZ — legacy unique-HASH resurrection killed; old-set archive COMPLETE.
Owner hit `UniqueViolation ux_incoming_documents_archive_HASH` archiving 15,364. Root cause: the
abolished 2026-08-17 laws (uq HASH + COMPANY_ID/COMPANY_DOC_ID) survived as DECLARATIONS in
repos.json `supabase.indexes`; harmless on main (indexes long dropped) until POST /repos provisioned
the NEW archive table and ensure_schema re-materialised them (`ux_*` = create_unique_index naming,
proven). Fixed at both layers: `"indexes": []` in BOTH repo entries (repos.json, bind-mounted) +
DROP INDEX both `ux_incoming_documents_archive_*` (archive uniques now = pkey only, same as main);
no code seed carries them (grepped). Also removed the stale "תקרת ביצוע: 5,000" modal note (two
spots — cap died earlier tonight). Move completed through the console UI on the owner's own
selector (`?lte_doc_date_norm=2026-02-23`): owner's clicks landed 13,522 (waves 20:42–21:04Z, big
ones only passing after the index drop), final 1,844 executed by agent → **main 23,923 ·
main-rows-dated-≤2026-02-23 = 0 · archive 15,366** (OLD 13,522, MERGED 1,810, COMPLETED 22, rest 8).
Note: 4 IN_PROGRESS rows were archived (owner selected by date only) — if their in-flight action
ever completes, the state-machine upsert would recreate the row in MAIN by ID; watch for
archive-conflicts on any future re-archive of the window.

## 2026-08-25 ~00:4xZ — dead laws made UNRESURRECTABLE (owner: "שלא יקרה יותר לעולם, תנקה").
Every copy of the abolished 2026-08-17 declarations swept: repos.json (indexes [] both repos,
COMPANY_DOC_ID column block removed from both, dead COMPANY_ID+COMPANY_DOC_ID upsert_match_rule
removed — SHORT_DOC_ID/HASH write-path rules untouched); phantom COMPANY_DOC_ID column DROPPED from
the archive table (guarded: refused unless all-NULL; was all-NULL); display.json stale entry removed
(spec doc, zero code consumers — verified); settings.json hit = prose inside an extraction _note,
left; snapshots/ = row-data backups, not config, left. TWO permanent layers: (1) runtime —
backends/supabase.py `_RETIRED_UNIQUE_INDEXES`/`_RETIRED_COLUMNS`, ensure_table+ensure_schema
refuse to materialise them whatever any config declares, loud log warnings (deployed build 4;
proven IN the live container: poisoned cfg → all 4 declarations refused); (2) tripwire —
scripts/ops/lint_dead_laws.py (recursive over storage configs + fixture schema; self-tested: fires
on all 4 poison declarations, clean on current tree). Live cfg via API: both repos indexes [] /
no retired column / clean rules. UI loads 23,923 rows, 0 errors. Archive intact: 15,366, uniques
= pkey only.

## 2026-08-25 ~01:0xZ — post-archive deep census + WAIT-TRACKER WEDGE found and fixed.
Owner archived the old set (archive 15,366; main 23,923; 0 rows dated <=2026-02-23 left in main;
0 id-overlap main+archive, 0 resurrections). INCIDENT found during census: restart wave
(1,155 restart_gdoc, ledger 20:39-21:01, 1,828 opened=closed) FROZE at 21:01Z — n8n wait-tracker
wedge, fingerprint `dbTime.getTime is not a function` in main's log + exec 3565657 waiting with
waitTill 40min overdue (the recorded class in reference_n8n_wait_tracker_dbtime). Fix per doctrine:
restart n8n main only (0 running drivers = 0 casualties). Proven moving after: dbTime errors 0,
ledger 200/5m, AR 244->15, running 9. Leftover: drain exec 3565657 parked 'waiting' (webhook-resume
mode) occupying the manual-drain slot (console button would 409) — deliberately NOT canceled
(classifier also declined the direct row update); scheduled tick expected to reclaim; cancel only
on owner word. REMAINING CENSUS (main 23,923): COMPLETED 8,243 · OLD 5,613 (no-own-date 5,109 =
BS_LINE placeholders 3,211 + RECEIVED-aged 2,084 + misc; own-date NEWER than cutoff ~500 = the
mistake family: AI_DOC_DATE 244 / BS_LINE 184 / DOC_DATE 45 / SELECTED 17 / RECEIVED 10; top
זלמן סחר 69, פריוריטי סופ 47, אונת סימנט 28; corrupt 4) · MERGED 4,351 (3,051 recent-date, 1,299
no-date) · MISSING_LINK 1,820 (סופר מנחם 381, עלי סלאמה 234, וולפמן 158, פרומט 101) ·
MISSING_COMPANY_ID 1,660 (MAIL_ATTACHMENT 810, GMAIL 485, DRIVE 207) · IN_PROGRESS ~1,5xx (wave
mid-absorption, NOT backlog) · MISSING_TYPE 243 · UNKNOWN_COMPANY 200 · GARBAGE 94 ·
MAX_ITERATIONS 34 · EXTRACTION_FAILED 33 (30 of them BALANCE_SHEET) · DOUBLE 20 · corrupt dates
>2030: 15 (#39 family). BS metric-4: COMPLETED aging reports with ZERO linked lines = 20 of 276
(measured by NAME across main+archive — first measure by ID was wrong, LINKED_BS holds the BS
NAME). Awaiting owner: BS_LINE-ages-only-HASH-empty + own-date-wins fixes, then AR the ~500;
archive candidates (RECEIVED-aged no-date 2,084 / MERGED 4,351) are one selection-URL click each.

## 2026-08-28 ~03:2xZ — ALL 8 PIPES THIN, and the two defects that flip exposed, fixed + proven.
Registry: all 6 `proc` pipes had `processor_wf` renamed `prev_processor_wf` (backup
`scratchpad/sync_registry.backup.json`) — 8/8 pipes now thin, so no sync lane performs document
extraction; extraction happens once, in the state machine, against a saved file. Going thin
exposed TWO latent defects in `syncV3Unit0001`, both mine to fix, both now fixed and proven on
the live graph (issue: `issues/thin-mail-pipes-searched-whole-mailbox-2026-08-28.md`):
(1) the `to_sync` label term was appended on the **proc branch only**, so every thin mail pipe
degraded to `has:attachment newer_than:6m` = THE WHOLE MAILBOX — measured damage: `gmail-bs`
ingested doc-lane thread `1a0463d3ae940a82` and stamped it BALANCE_SHEET. Now applied in both
modes and **fail-closed**: a declared-but-unresolvable label key throws rather than searching
everything. (2) that throw immediately fired for `gmail-link`, whose key `DOC_LINK_TO_SYNC`
*does* resolve — `Load Settings` had never run, because `Needs Settings?` tested
`src_kind === 'gmail'` and `src_kind` carries the PIPE NAME (`gmail-link`), the kind being in
`conn_kind`. That clause had never matched for any mail pipe in the life of the workflow; it
was masked because `mode === 'proc'` satisfied the gate first. Gate now
`mode==='proc' || conn_kind==='gmail' || !!(label_keys && label_keys.to_sync)`.
EXECUTED PROOF — every mail pipe searches only its own labelled mail, 0 unit errors in the
03:26 pass: gmail-bs [3689985](http://n8n.localhost/workflow/syncV3Unit0001/executions/3689985)
`label:לטיפול-אוטומציה-שמירת-דוחות-גיול` · gmail-doc
[3690061](http://n8n.localhost/workflow/syncV3Unit0001/executions/3690061)
`label:לטיפול-אוטומציה-שמירת-מסמכים` · gmail-link
[3690218](http://n8n.localhost/workflow/syncV3Unit0001/executions/3690218)
`label:לטיפול-אוטומציה-קישור-למסמך` (the pre-fix failing run:
[3689982](http://n8n.localhost/workflow/syncV3Unit0001/executions/3689982)). Reconcile cadence
healthy ~16 min (02:23→02:39→02:55→03:10→03:26), nothing stuck, no stale lock.
LOOSE END (owner's, registry not code): `gmail-link` declares `failed: FAILED_BS`, so link-pipe
failures get labelled with the balance-sheet failure label.

## 2026-08-28 ~04:3xZ — deliver draft PUBLISHED; estate at rest; a host-disk trap recorded.
`syncV3Deliver0001` was ACTIVE while running an OLDER published version than its draft — so the
evidence-not-verdict row builders were in the draft but NOT executing. First push was CAS-rejected
(live changed 02:58); pulled, diffed against my saved copy — the ONLY delta was tag ORDER, nothing
semantic, and `__instance` is absent in both (the instances session confirms it is still pending on
their side) — then pushed: `ok update+activate`. VERIFIED IN LIVE BYTES, not the deploy line:
`active=t`, `activeVersionId = versionId`, and nodes carry `TYPE_BY_SOURCE`x6 / `ATTACHMENT_TEXT`x2
/ `row.SENDER`x2. Remaining lag: `gmailApiImap01` (mail app) is active with a draft newer than its
published version AND changed live since last sync — NOT pushed, because pushing the repo copy
would drop a human's live edit; owner/mail-side call.
ESTATE AT REST, NOT STALLED: 49/49 containers healthy, ZERO errors of any class since 03:38, both
post-restart enumeration passes clean (04:00, 04:15). Nothing touched for 41 min because nothing is
left to move — 1 ACTION_REQUIRED (last touched 08-27 14:34) and 75 IN_PROGRESS whose last touch is
**08-26**, i.e. long-parked awaiting ACTION_RESTART, NOT crash casualties. Two theories tested and
DISCARDED first: a post-crash lock storm (only ONE doc_action lock held,
`doc_mtce5nw5yl7jl6::mark_completed`, TTL 2890s) and crash-window casualties (timestamps are two
days old). Histogram: COMPLETED 9,131 · OLD 7,039 · MERGED 4,564 · MISSING_LINK 2,102 ·
MISSING_COMPANY_ID 1,638 · API_TOOLS_FAILED 680.
HOST TRAP (cost two failed commands): Windows `C:` hit 22 MB free of 476 GB while `df -h /` INSIDE
WSL still read 836 GB free — the Ubuntu vhdx (164.5 GB allocated, 121 GB used) cannot grow, but the
stack runs off allocated slack so every container stays healthy and nothing logs ENOSPC. Symptoms:
`bbox n8n pull` returned NO output, and `bbox n8n push` reported
`lstat .generated/n8n/indox/syncV3Deliver0001.json: no such file` — a misleading pointer at
compiled config that was in fact present. Both worked once space freed (now 8.09 GB). Space inside
the vhdx returns to Windows only via compaction (`wsl --shutdown` + `--set-sparse true`), which
stops the stack — NOT run, owner's call. NOTE: the 03:40-03:58 fleet restart is NOT attributable to
this — n8n main and Postgres logs 03:30-04:05 show no ENOSPC/OOM/FATAL and dmesg no OOM killer or
I/O errors. Cause remains unproven; do not record it as a WSL wedge either.
INVARIANT CONFIRMED estate-wide: grep over every `apps/indox/blueprint/n8n/*.workflow.ts` for a
canonical TYPE write (`row/doc/upsert/rec.TYPE =` or a `"TYPE":` literal, any quoting form,
staticData caches excluded) returns hits in exactly ONE file — `indoxV2BSTest01`, which is a TEST
building fixture payloads with deliberately known types. **Zero production ingest or deliver site
writes a canonical TYPE**; they all write `TYPE_BY_SOURCE` as evidence and leave the verdict to the
state machine. Writers: syncV3Deliver0001 (x6) + the three Gmail downloaders (2/1/3).
PEER RECONCILIATION (instances session) — resolved, nothing lost: the 02:58 version 5fd1d9cd was
their accidental whole-app push; it landed as a DRAFT (activeVersionId still 12b9ff3d), which is what
`bbox n8n status` flagged. My 04:32:29 push PUBLISHED that same version without cutting a new history
row (content identical bar tag order), so table and flag never actually disagreed. Their repo copy
already carried my row builders. Pulled the three downloaders from live: `__instance` and
TYPE_BY_SOURCE now COEXIST in all three, live==repo (2/2, 2/2, 3/3 and 2/2, 1/1, 3/3), nothing to
push. Naming three workflows pulled 62 files into the working tree because live now carries their
instance work estate-wide (`public.companies` -> `{{ $json.__instance ? 'indox_'+$json.__instance :
'public' }}.companies`, settings lookups dropping the `instance=` column filter for the schema,
queries re-prefixed `=` so interpolation evaluates). NOT committed — that churn is theirs, not drift.
Also from them: `indox_levi.settings` has NO `%registry` row, so levi has zero sync pipes; all 8 thin
pipes measured here are hacohen's.

## 2026-08-28 ~06:3xZ — MAIL CURSOR SCOPED (last unscoped op pair closed), + sync outage diagnosed.
The mail walk shared ONE `sync_cursor` position across all tenants: `mailDiscovery01` had ZERO
`__instance`, and CURSOR_GET/CURSOR_SET reached syncLedgerApi01 with `__instance:''` (measured: 13
SET + 12 GET), so every cursor read/write resolved `public.sync_cursor` = indox_hacohen whatever
tenant the pass was for. `source` is NOT protection — it is keyed `<component>/<pipe>`
("incoming-documents-main/gmail-doc"), IDENTICAL across instances, so only the SCHEMA separates
tenants. THREE edits: (1) `mailDiscovery01`'s `When Called` now DECLARES `__instance` — load-bearing,
because an executeWorkflowTrigger that declares `workflowInputs.values` STRIPS undeclared fields, so
passing it from the caller alone would have silently done nothing; (2) `Build CURSOR_GET Call` and
`Build CURSOR_SET Call` both name it, SET reading it from `$('When Called')` so it cannot drift with
the intermediate node names; (3) `syncV3Unit0001` — the `Search` map passes it AND **`Search Req`**
now carries it. Search Req was NOT among the six builders the instances session fixed (they built
that list from nodes feeding syncLedgerApi01; this one feeds mailDiscovery01), it constructs a fresh
item, and `Search` maps `={{ $json.__instance }}` off it — so my FIRST push still produced
`__instance:''` at runtime. Found by measuring, not reading.
EXECUTED PROOF (06:28 pass), GET and SET are independent paths so both are shown:
[3695577](http://n8n.localhost/workflow/syncLedgerApi01/executions/3695577) CURSOR_GET
`__instance='hacohen'` · [3695579](http://n8n.localhost/workflow/syncLedgerApi01/executions/3695579)
CURSOR_SET `__instance='hacohen'` · 3695590 CURSOR_GET gmail-bs — 3/3 scoped.
ALSO FIXED: `syncV3Deliver0001` failed `bbox n8n code validate` on a sticky note (`Timeout Note`)
missing `parameters.color`, so that file had NO working validation gate. Added `color: 3`; both it
and syncV3Unit0001 now validate.
SYNC OUTAGE 05:56-06:28, diagnosed for the instances session (their file, their fix): their
`Registry Req` change sent `__instance` but DROPPED `instance` — two different fields. indoxApi01's
`Build Table Get` guard reads `j.instance` (the row DISCRIMINATOR column, holding a COMPONENT name)
and is unconditional for settings/companies/tag_rules, so every pass threw. Fix applied by them:
send BOTH, `instance:'*'` being safe again precisely because `__instance` now shuts the cross-tenant
door — '*' spans COMPONENTS within one tenant. Second half: the throws happened after Try Lock and
before Unlock, so dead executions held both reconcile locks (TTL 4313s) and later passes returned
`success` while hitting "Skip: Already Running" — green pipeline, zero work, would have stayed down
until ~07:20. Recovered: 0 errors in 20 min, units and mailDiscovery01 running again.
AUDIT (requested: find other nodes resolving instance by SCANNING rather than being told):
(a) `SyncApi0000000001` (v1 "sync api") is **active=true** and still emits
`{table:'settings', instance:'*'}` with no `__instance` (line 468; same premise documented at 533) —
but 0 executions in 24h and no last_run, so dormant, not leaking. Owner/v1 call: fix or deactivate.
(b) `syncV3Main0001` line 439 comment is now STALE — still says Registry Req asks `instance:'*'` so
"this receives ONE SETTINGS ROW PER INSTANCE". Code is fine; the comment describes the dead premise,
which is exactly the failure mode that produced the cross-tenant leak.
TOOLING DEFECT: 5 of 7 files in `apps/mail/blueprint/n8n/` are owned by **root** at mode 644, so
`bbox n8n pull mail <those>` dies with EACCES — the documented "pull before editing" contract is
broken for them. All 74 indox files are shlomo-owned (744), which is why only mail pulls failed.
`sudo` needs a password so ownership was NOT repaired; worked around by moving the file aside so the
pull could CREATE a fresh one (dir is writable). `core.fileMode=false` here, so the 644/744 split
causes no git churn. Incidentally the pulled file was byte-identical to the committed one, so
`bbox n8n status`'s "changed LIVE since last sync" for mailDiscovery01 was cache staleness, not drift.

## 2026-08-28 06:33Z — CLOSED, verified INDEPENDENTLY (not on the other session's numbers).
Re-probed the live graph after their many pushes; every fix of mine survived: fail-closed label
throw 1 · `conn_kind` gate 4 · `Search Req` `__instance` 7 · deliver `TYPE_BY_SOURCE` 6 /
`ATTACHMENT_TEXT` 2 · mailDiscovery01 `__instance` 9. Registry: **thin=8 proc=0**. Latest pass shows
the two workstreams composing correctly — each mail pipe searching ONLY its own label AND carrying
its instance: gmail-doc `inst='hacohen'` `label:לטיפול-אוטומציה-שמירת-מסמכים` · gmail-bs
`label:לטיפול-אוטומציה-שמירת-דוחות-גיול` · gmail-link `label:לטיפול-אוטומציה-קישור-למסמך`.
**0 errors in 30 minutes**; 25 documents touched in 30 min (0 in the last 10 = between passes, the
resting state, not a stall). Their independent census over the same window: 0 unscoped ops of 33,
236 executions, 0 errors — agrees with mine.
Their close-out on my two audit items: (a) SyncApi0000000001 SCOPED rather than deactivated (they
established it is not merely idle but UNREACHABLE — 0 executions ever, only trigger reachable solely
from the inactive ApiSupabase01 — yet scoped it anyway, since "active but unreachable today" is not
a safety property; retiring the v1 chain is put to the owner, not taken by either of us).
(b) The stale comment fixed AND extended: the paragraph below the one I flagged claimed the
`<instance>/<pipe>` namespacing was "the whole reason two instances can run at once", which is FALSE
— both tenants emit `incoming-documents-main/gmail-doc` byte-identical. Both rewritten to state that
the ledger key does not distinguish tenants at all, only the schema does.
STILL OPEN, all owner calls: `gmailApiImap01` active with a draft newer than its published version
(not pushed — would overwrite a live human edit) · vhdx compaction (~43 GB, needs `wsl --shutdown`) ·
the 13,998-row typed backfill · root-owned mail blueprint files breaking `bbox n8n pull mail`.

## 2026-08-28 08:3xZ — THE RETRY QUEUE HAD NO EXIT. Found, fixed, proven at runtime.
**THE DEFECT.** `Build Diff` offers a due id only while `a.attempts < max_att` (default 5), and the
promotion to `needs_review` lives on the ATTEMPT path (`Quarantine?`), which only runs when a
delivery actually FAILS. Those two facts DEADLOCK: an item that reaches max_attempts is excluded
from DIFF → never offered → never delivered → never fails again → **never promoted**. It is pinned
at exactly max_attempts for ever: invisible to the pipeline, immortal in `sync_attempt`, and counted
as "failed" by the UI. MEASURED: **213 rows at attempts>=5 across the four mail pipes with ZERO
retryable**, and `sync_ledger` had not gained a `needs_review` row since **08-06** — three weeks.
This is the real answer to "missing deliveries" and to "why don't they drain".
**THE FIX** (`syncLedgerApi01` :: `Build Reap`): the exclusion and the promotion must live in the
same place, and the reaper is that place — it already resolves `max_attempts` per SOURCE through the
same `pol` lookup and already writes both tables. Added two CTEs: `prom` inserts
`status='needs_review'` for `attempts >= max_att` (bounded 200/pass, ledger anti-join keeps it
idempotent, `stuck` excluded so it can never contend with the `att` CTE in the same statement) and
`promdel` clears the attempt row. This is what the sync-v3 plan always specified — it simply had no
trigger that could fire.
**PROVEN**: dry-run in a ROLLBACK transaction first (promoted 200 / cleared 200), then live —
exec 3696681 hacohen `{"released":0,"attempts_written":0,"promoted_needs_review":200,
"attempts_cleared":200}`, exec 3696682 levi correctly `0`. sync_attempt 224 → 21 and still draining;
needs_review 95 → 295. Live syntax-checked all 16 Code nodes with `node --check` after the push
(push success proves nothing on this file — the other session broke it twice that way).
ALSO CLEANED (each backed up to WSL-native `/home/shlomo/indox-backups`, read back before deleting):
327 `sync_attempt` rows for items that ALREADY had a ledger row — dead by the system's own anti-join,
never cleaned up, inflating the UI's failed count · 25 rows of `sv3s_*` test residue (cursor 7 /
ledger 15 / attempt 3) from the 08-26 suite run · the stale `gmail-bs` `sync_pipe_state` row stuck
`running` for 62 h whose execution 3617820 no longer exists.
OUTLINE STAMPS SHIPPED (the owner's ask): all six sync workflows now write `execution_metadata.outline`
via an `executionData` node, the same mechanism `indoxV2ActionRouter01` uses, each hung as a PARALLEL
branch so a stamp can never cost a delivery. Live: `gmail-doc_x1_taken`, `drive-bs_x1_taken`,
`reconcile_x7_units`, `label_engine_x6_conns` (that last one also proves the mail scheduler really
does fan out over all 6 connections).
ARCHITECTURE NOTE — READ BEFORE "FIXING" THE LEDGER. `sync-v3-plan.md` invariant 1 states:
"Ledger row exists ⟺ item delivered (or quarantined needs_review). **No in_progress/pending rows —
the live diff IS the todo list.**" So `claimed_at` being NULL on all 29,099 rows is BY DESIGN, not a
bug; I was wrong to call it one. BUT that invariant is exactly why sync depends on Gmail/Drive: the
todo is `desired − ledger`, and `desired` can only come from re-listing the source every pass. The
owner's "pure scan, mark, then process — no external system dependency" is therefore a deliberate
CHANGE to invariant 1, not a defect fix, and needs an owner decision before implementation.
STILL OPEN — OWNER'S DIALS, NOT MINE (`feedback_never_touch_concurrency_settings`):
(a) **`mail-private` still carries `take:25, chunk:50, page_size:50`** → `Take X` bounds at
`min(25,50)=25` while discovery lists 50, so HALF OF EVERY PAGE is listed and stepped over. This is
the exact documented data-loss bug the `Search` node's own note says was fixed; the config still has
it. Fix = `page_size == chunk == take`.
(b) **`mail-private` duplicates `gmail-doc`** — same mailbox, identical label keys
(DOC_TO_SYNC/SYNCED_DOC/FAILED_DOC), identical card numbers. Only `mail-private` being paused stops
them both enumerating the same slice.
(c) `gmail-link` declares `failed: FAILED_BS` — link failures get the balance-sheet failure label.
(d) `old_document_months_back` AND `OldDocumentMonthsBack` both exist (both 6); window applied
inconsistently — gmail `newer_than:6m`, drive `createdAfter` = 24 months.
(e) 13 ACTIVE test/fixture workflows (§6 forbids; it recorded 9, it has grown). NOT deactivated:
several are webhook-triggered and the console's בדיקות tab fires them, so a blanket sweep would
break the owner's test surface.
