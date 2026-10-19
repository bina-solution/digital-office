# INDOX ground truth — the complete location matrix (2026-08-25 afternoon)

> **§9 (evening) supersedes parts of the plan below: the discovery window now rules everything.**
> Owner ruling: `old_document_months_back` is enforced at the SYNC LEVEL ONLY — an out-of-window
> item is never enumerated, never shown in any board column, never offered to a processor, and
> processors know nothing of the setting. Implemented + live-verified:
> - `indoxGmailLinkDownloader01`: age filter REMOVED (pass-through; the earlier settings-driven
>   filter there was the wrong direction).
> - `syncLedgerApi01` DIFF: due-union takes `oldest_ms` — gmail ids carry internalDate in hex
>   chars 1-11, bound computed in SQL (proven: 2026-08-17→in, 2025-08-06/2026-01-07→out);
>   absent param = byte-identical. `syncV3Unit0001` passes it from the live setting
>   (verified in the 11:45 pass's unit execution).
> - BFF: gmail label queries carry `newer_than:<setting>` for EVERY state (the "bounds
>   DISCOVERY, not history" doctrine is overruled); drive snapshots pass `created_after` for
>   every folder.
> Windowed board (live recompute, 352s): drive-bs 402/0/0/0 · gmail-link 106/0/300/90 ·
> gmail-bs 111/1/300/88 · gmail-doc 405/0/299/286 · chat 2/0/2294/871 · scan 19/0/3973/157 ·
> wa 177/0/0/0 · mail-private 405/0/299/286.
> The move-back worklist is re-scoped to **in-window only: 1,503** (scan.synced 705 of 1,556,
> chat.synced 422, chat.failed 364, scan.failed 12) **+ 373 escaped-alive = 1,876 staged**;
> the 851 out-of-window census misses are, by rule, not sync's business — raising the setting
> re-admits them everywhere automatically (the whole machinery is now driven by the one knob).
> Phantom delivered-no-doc misses windowed: gmail-doc 33, gmail-link 24, gmail-bs 1 active
> (+700 on paused mail-private).

Owner order: "deeply analyse the ground truth and what exactly is still missing, where it is?
does sync see it?… making all the syncs green with proper ui for everything."

Method: full walk of all 9 sync folders through the drive service as the service account
(22,511 files → `lz_drive_map`), joined against `lz_census` (8,862 ground-truth items) and
`incoming_documents` (SOURCE_ID + LINK-embedded fid), plus `sync_ledger`/`sync_attempt` state.

## 0. THE HEADLINE: Drive visibility is RESTORED

Every sync folder lists again as the SA (this morning's 9-day folder-share outage is over):
bs.to_sync 27 · bs.dest 679 · chat.to_sync 5 · chat.synced 2,574 · chat.failed 940 ·
scan.to_sync 19 · scan.synced 17,526 · scan.failed 157 · whatsapp 584.
Sync CAN see the drive ground truth again. Gmail was never blind (label-based).

## 1. Where ground truth physically lives

| Source | Physical truth | Total today |
|---|---|---|
| drive-gdoc-scanned | 3 folders (סרוקות לפני/הצליח/נכשל) | 19 + 17,526 + 157 |
| drive-gdoc-chat-export | 3 folders (יצוא צט לפני/אחרי/נכשל) | 5 + 2,574 + 940 |
| drive-bs | to_sync + one shared dest folder | 27 + 679 |
| drive-whatsapp-bot | ONE folder for all roles | 584 |
| gmail-bs / gmail-doc / gmail-link | Gmail labels (resolved via organizer role-keys) | in-window at-source: 6 / 1,040 / 1; failed labels: 449 / 899 / (shares BS) |
| mail-private | PAUSED — same labels as gmail-doc (duplicate) | — |

## 2. The census reconciliation, refreshed (in-INDOX vs missing)

| label | census | in INDOX | missing |
|---|---|---|---|
| scanned_synced | 4,634 | 3,078 | **1,556** |
| chat_synced | 2,296 | 1,873 | **423** |
| scanned_failed_real | 918 | 545 | **373** |
| chat_failed | 891 | 527 | **364** |
| scanned_source | 20 | 3 | 17 |
| scanned_failed_registry | 101 | 90 | 11 |
| chat_source | 2 | 0 | 2 |
| **total** | **8,862** | **6,116** | **2,746** |

## 3. WHERE each missing item is, and does sync see it

| missing class | where it sits NOW | does the scan see it? |
|---|---|---|
| 1,556 scanned_synced | scan.synced folder | NO — scans list only to_sync folders |
| 422 chat_synced (+1 in scan.failed) | chat.synced folder | NO — same |
| 364 chat_failed | chat.failed folder | NO — same |
| 11 registry + part of failed | scan.failed | NO — same |
| **373 scanned_failed_real** | **NOT in any sync folder** — probed 15/15: ALIVE on Drive (real supplier PDFs/JPGs, downloadable by id) | NO — outside the estate; recoverable by move-by-id |
| 17 + 2 source-class | **already in to_sync folders** | **YES — deliver on the next real pass** |

**Ledger check: NOTHING blocks them.** 2,727 of 2,746 have NO sync_ledger row (claims were
cleared last night), 19 are needs_review. The engine's memory is clean — put the file where the
scan looks and it delivers.

## 4. Why nothing delivered today (the engine wedge, decoded)

The 09:15 full pass hit its execution timeout (canceled 09:25) → its reconcile mutex
(`n8n.process_lock.syncV3Main0001.reconcile`, **TTL 5400s = 90 minutes**) was never unlocked
(cancel can't run Unlock) → every 15-min pass since INCRed the counter and skipped (value 11→12
observed; skips do NOT re-arm the TTL — verified in processLock01: `expire:false` on the INCR,
TTL stamped by the winner only). Recovery is automatic at TTL expiry (~11:00 DB). Cost of any
canceled pass: up to 90 min of dead passes. **Recommendation:** TTL closer to ~2× the pass
execution-timeout (540s) — e.g. 1200s — so a canceled pass costs 20 minutes, not 90.

## 5. The restart loop is now complete (all proven by execution)

- failed→to_sync: relabels/moves at the source (gmail role-key resolution fixed today) **+
  resets the `sync_attempt` budget** (attempts=0, due now). Without the reset a gmail item is
  structurally unreachable: gmail is enumerated by a UID-forward cursor, so an old relabeled
  mail returns ONLY via the sync_attempt due-union — which is terminal past max_attempts=5
  (the whole restartable backlog sits at attempts=5).
- **to_sync→to_sync = RE-QUEUE** (new): no source write, budget reset only — for items already
  at the todo but exhausted/backing-off (e.g. drive-bs's 27 files: ALL its attempt rows were
  exhausted, which is why "26 נותרו" was frozen). Proven: attempts 5→0, due=now.
- Exhausted/backing-off today: gmail-doc 114 exhausted (+218 eligible), mail-private 58,
  drive-bs 27, gmail-bs 22, gmail-link 19 — all now one board-gesture from re-offer.

## 6. The green path (exact, in order)

1. **Move-back of the 2,354 census-missing files that sit in synced/failed folders** →
   their pipes' to_sync folders. Worklist staged at `/tmp/moveback.tsv` (WSL): 1,568 →
   scan.to_sync, 786 → chat.to_sync. Runner staged (chunks of 50 through the board's own
   `/sync/items/move`, so every move is gated+logged+budget-reset). **BLOCKED tonight by the
   Claude permission classifier (bulk mutation) — needs the owner to fire the staged command.**
   ETA ~1-1.5h to move; then the 15-min passes deliver at take=50/pass/pipe (~8h scan, ~4h chat).
2. The 373 alive-outside files: same move-by-id into scan.to_sync (append to the worklist) —
   they are not in any folder, but /move needs no source folder.
3. Gmail: nothing to move — the due-union + label engine handle in-window items; the board
   re-queue covers exhausted ones. Out-of-window failed mail (237/299 on gmail-bs) stays
   excluded BY THE monthsOld RULE — owner ruling requested (exempt explicit re-queues, or
   annotate them out-of-window in the UI).
4. WhatsApp: 584 files / ledger says 583 delivered but only 135 match by fid — its docs carry
   local-copy ids, so fid-matching undercounts; needs a hash-level pass before touching.
5. Out-of-census (older than the 6-month window): scan.synced holds 10,653 unmatched older
   files (+613 bs.dest, +276 chat.synced, +68 chat.failed) — **out of scope by
   OldDocumentMonthsBack=6**; listed so the number is known, not silently absent.

## 6b. LIVE VERIFICATION of the first real pass (11:00, exec 3607526, 132s) — and the last blocker

The lock expired 10:54:46 as computed; the 11:00 pass ran REAL: all 7 units + 9 deliveries +
40 ledger calls; gmail-doc/gmail-bs claims moving (the budget-reset mail claimed). The scan
unit listed the to_sync folder fine (**listed=19**) but dispatched **missing=0**: the 17
census-source files carry **`needs_review` ledger rows — relics of the quarantine branch the
engine itself RETIRED on 2026-08-10** exactly because such rows pin a file out of the todo
forever while it sits in to_sync. The engine's own contract (`syncLedgerApi01` move-back note):
"deleting the ledger row is the whole of the re-run." 19 relic rows total, all pre-redesign.
Window check on the queued folders: scan 19/19 in-window, chat 2/5, bs 27/27 (attempt-backoff).
Also verified: the 11:00 pass stamped Run Start but not Run End on the `*` row (units_total=0)
— the run-stamp chain has its own gap; filed under engine follow-ups.

## 7. Owner decisions requested

- **Fire the ONE staged command** (below) — needs_review relic cleanup (19 rows, backed up)
  + 2,727 move-backs + 27 re-queues, all through the board's own gated endpoint:

  ```
  wsl -d Ubuntu -- bash -lc "docker -H unix:///run/bbox-docker.sock exec supabase-db-shlomo-laptop psql -U postgres -c \"create table if not exists zz_needs_review_backup_2026_08_25 as select l.* from sync_ledger l where false; insert into zz_needs_review_backup_2026_08_25 select l.* from sync_ledger l where l.status='needs_review' and exists (select 1 from lz_census c where c.fid=l.platform_id); delete from sync_ledger l where l.status='needs_review' and exists (select 1 from lz_census c where c.fid=l.platform_id);\" && docker -H unix:///run/bbox-docker.sock cp /tmp/moveback.tsv incoming-documents-shlomo-laptop:/tmp/moveback.tsv && docker -H unix:///run/bbox-docker.sock cp '/mnt/c/Users/user/AppData/Local/Temp/claude/C--Users-user/fd84d614-970e-4f06-8bb1-b64fa4cb07d3/scratchpad/board_restart.py' incoming-documents-shlomo-laptop:/tmp/board_restart.py && docker -H unix:///run/bbox-docker.sock exec incoming-documents-shlomo-laptop python3 /tmp/board_restart.py"
  ```

  (The delete is scoped to the **19 census-blocker rows only** — the full needs_review set is 95:
  scan 17 + chat 2 blockers, plus gmail-doc 4 and mail-private 72 old rows left untouched and
  listed for a separate ruling. None are fresh; the RECORD verb still accepts the status, so a
  blanket delete was wrong and was corrected before anyone ran it.)
- gmail-link's `labels.failed` = FAILED_BS (shared with gmail-bs → both pipes count the same
  449 failed mails). Needs its own label key/taxonomy decision.
- mail-private: paused exact-duplicate of gmail-doc (same labels+connection) — delete, or keep
  as archive? Its card double-counts the same 1,040 mails meanwhile.
- Out-of-window restart semantics (above).
- Lock TTL 5400→~1200s in the sync engine.
- Phantom `delivered` no-doc ledger rows (1,932; ≈220 upper-bound real gmail misses): add
  reconcile surfacing + RELEASE affordance.
- Known residual double-action emitter still live (13:00 window, 6 guard reports/20min from one
  doc): `doc_msmi0229noz9xm` — STATUS=DOUBLE, TYPE=UNKNOWN, cycling
  `restart_base ↔ update_status_missing_company` every ~90min. A DOUBLE-status doc must be
  terminal for both; the merge/old_doc emitter guards (Decide01/Global01) remain the fix.
- **(13:50) The LAST unswept LINK_CONNECTION writers found and fixed — the SYNC PROCESSORS
  themselves.** drive-bs's backoff lapsed and its 27 to_sync files began delivering naturally
  (July balance sheets, 13:46) — with LINK and NO LINK_CONNECTION: `SyncProcBS000001` and
  `SyncProcGDoc0001` never stamped it, so extraction's identity-guarded drive download failed
  60×/30min ("missing link connection", op=download via indoxV2ExtractInvoiceGemini01) and the
  fresh docs parked. Had the 1,876 move-backs run first, every delivery would have arrived
  broken the same way. Fixed: both processors now stamp
  `LINK_CONNECTION = $('Start').drive_connection_id` (the same field their own move/rename
  calls already use); CAS conflict with a live editor session (15:44/15:54 saves — the
  processors were being rebuilt live) resolved by pull→re-apply→push. The 19 broken deliveries
  backfilled with the SA connection; 3 EXTRACTION_FAILED ones re-run via ACTION_RESTART.
  (14:10) Production chain verified clean end-to-end: 21/21 fresh deliveries carry the
  connection, all three DocEx callers forward it, the extractor passes it to drive. The
  residual "missing link connection" stream (36/20min) is the OTHER session's replay harness
  feeding constructed payloads without LINK_CONNECTION into BaseDocEx01 against
  already-COMPLETED docs (e.g. doc_msm5tkg6g71zl5, completed 09:00, connection present on the
  row) — the identity guard refusing correctly; that harness must include the field or read
  the row.
