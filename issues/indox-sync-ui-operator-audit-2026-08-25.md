# Sync UI as the operator's surface — audit + fixes (2026-08-25)

Mandate: everything runs through the sync UI — the operator must be able to see full
ground-truth sync state, restart failures, see exactly what each scan has left, and drive
everything green; codebase aligned/minimal; `monthsOld` honored everywhere.

## What the UI already does well (verified live, console → מסמכים נכנסים → סנכרון)

- 8 source cards with: connection identity + health dot, at-source / in-INDOX / remaining,
  lifetime 4-state bars (each segment click-through), **per-code failure chips** (e.g.
  `לא עובד במערכת — נמצא בתיקיית הכשלים ללא רישום עיבוד · 277`), folder/label mapping,
  cadence, run-now / edit / pause / delete.
- Items board: 4 virtualized columns, filter by pipe/text/failure-code/stuck, select-all
  (server-side ids), **drag-to-column = state change written at the SOURCE** (relabel /
  folder move) — this is the restart-fails affordance, and the natural-path doctrine
  (syncs re-discover what returns to `to_sync`).
- Engine tab: generated pipeline diagram, ledger live state (claimed/delivered/needs_review),
  last run per source with n8n execution links.
- Honest partials: `gmail-doc: to_sync — ReadTimeout` is surfaced on the board rather than
  swallowed; bounded mail listing is labeled.
- The global numbers agree with the ground-truth census work: לסנכרון 2,821 (the cleared
  ledger claims awaiting natural re-delivery), נכשל 2,268 with reasons (≈ the census failed
  classes), tie to `lz_census`.

## Defects found (measured) and fixed

1. **Cold load broke the whole page.** `GET /sync/registry` = 5–10s on EVERY call
   (measured 9.85s, then 5.3s cold / 62ms warm): the read fetched every pipe's whole
   `indox_sync_stats` payload — each embeds the pipe's complete item list — while the memo
   TTL was 5s and the UI polls every 5s, so every poll re-paid the fetch; the four board
   columns fired concurrently into serialized Flask and ALL blew the webapp's 12s abort.
   Operator saw four dead columns, and on a true cold load — **"למופע הזה אין עדיין מקורות
   סנכרון"** (add your first source) with 8 live sources behind it.
   **Fix:** `_TTL_SYNC_STATS` 5→75s (the table itself is only rewritten by the 90s
   background pass; mutations still clear the memo), the background pass now **primes** the
   memo (`_sync_stats_memo_prime`) so the request path reads memory between passes, and the
   empty-registry invitation renders only when the load actually succeeded (aborted load
   shows "לא נטענו עדיין — אין להסיק שאין מקורות"). Verified: registry 3.6s cold-after-boot
   → 82ms warm; board renders.
2. **"הרצה אחרונה —" on every card, forever.** The engine deliberately splits "a pass ran"
   (`sync_pipe_state.run_finished_at`) from "a delivery landed" (`last_run`, ledger-stamped);
   the registry payload sent neither, though `api.ts` typed `last_run`/`last_run_url` from
   day one. **Fix:** `_enrich_registry` stamps scoped `run_finished_at`, else the scheduler's
   `*` row for enabled pipes (a paused pipe is never vouched for by the full pass), else the
   delivery stamp — with the n8n execution link.
3. **The restart click itself timed out.** `POST /sync/items/move` re-derived every item's
   state via a FULL live source walk (hundreds of per-message mailapi searches) before one
   relabel — >40s → console proxy 502 `app_unreachable`, while the relabel landed anyway
   minutes later (operator told "failed" for a move that happened). **Fix:** the legal-move
   gate reads the ≤90s stats cache (live walk only as cold-cache fallback); the source write
   remains the authority.
4. **"ניקוז רץ · 7:54" badge counting forever**: an orphaned `processLock01` execution
   (id 3578404, `renew` of the reconcile lock, parent 3578351 no longer exists) sat
   `running` for ~8h and fed the pipeline badge. Marked crashed. syncV3Main itself runs
   every 15m and succeeds (08:15/08:30/08:45/09:00/09:26 all success) — the engine was
   never stuck, only the badge.
5. **Restarting a failed GMAIL item had NEVER worked — the click moved nothing and
   polluted the mailbox instead.** `_gmail_move` sent the registry's role KEYS
   (`BS_TO_SYNC`, `FAILED_BS`…) to mailapi verbatim; mailapi auto-creates unknown labels,
   so the "restart" ADDED a literal `BS_TO_SYNC` Gmail label (found live on a client mail,
   1 message) while the real failed label stayed — invisible to the engine, which scans the
   configured names. **Fix:** keys now resolve through the same `organizer/settings`
   document the engine and inventory use (`_gmail_label_names`), + a 45s timeout on the
   label ops (the 8s default lost real IMAP round-trips as `ReadTimeout`), + refusal
   reasons are logged. Residue cleaned: bogus `BS_TO_SYNC` removed from the polluted mail.
   `DOC_LINK_TO_SYNC` (Label_149, 1 old message) is the same fingerprint from an earlier
   click — the empty label shells `BS_TO_SYNC`/`DOC_LINK_TO_SYNC` can be deleted in Gmail.
   **Executed proof of the whole loop (2026-08-25):** move `1987f6be3c15da6f`
   failed→to_sync → `moved=1` in 18.8s → Gmail metadata confirms the real to_sync label
   (`לטיפול-אוטומציה-שמירת-דוחות-גיול`) added and the failed label removed. The next 15-min
   gmail-bs scan re-discovers it naturally — the owner's "syncs should find them" doctrine,
   as a UI button.
6. **The eternal "רץ כעת · מתכנן את העבודה" strip**: a canceled/timed-out pass (the 09:15
   full pass hit its execution timeout at 09:25) never reaches its Run End stamp, so
   `sync_pipe_state.'*'` says `running` forever. `GET /sync/runs` now reports a running row
   older than 45min (3 schedule periods) as `stale`, which also drops it from the strip's
   running count; the card's last-run falls back to `run_started_at` for the same reason.

## monthsOld compliance (sweep verdict)

Live values now: `OldDocumentMonthsBack=6`, `old_document_months_back=6`. The live v3 lane
is fully settings-driven with one shared clamp (`syncV3Unit0001` drive `createdAfter` +
gmail `newer_than` strip-and-replace; BFF `_months_back_dt` shared by both). Fixed this
pass:

- `indoxGmailLinkDownloader01` hardcoded 6 → now reads `old_document_months_back` from its
  own Settings Loader (6 only as absent-setting fallback). Pushed + live node verified.
- `blueprint/fixtures/settings.json` shipped `OldDocumentMonthsBack=1200` (unbounded) as the
  **fresh-install default** → now 6. (The clobber-on-test-run half was already fixed
  2026-08-06 — operational keys are never re-seeded.)

Still non-compliant, all on the legacy v1 lane (documented, not grown):

- `SyncSource000001` (ACTIVE; reachable only via the `indox-manage` STATUS verb — the
  product BFF never calls it): gmail fallback hardcoded `newer_than:6m` (currently equals
  the setting), drive listing has NO date bound.
- `SyncScanner00001` + `SyncScanUnit0001` (both INACTIVE, `lifecycle:legacy`, zero retained
  executions): hardcoded/no cutoffs. Retirement candidates — but still referenced from
  `api/__init__.py`, `hooks/sync-engine`, `hooks/demo.py`, so removal is a scoped task, not
  a file delete.

## Restart vs monthsOld — a semantic conflict the owner should rule on

The board's restart (move failed→to_sync) relabels at the source, and the scan then re-discovers
the item **only if it is inside the discovery window**: the gmail scan is query-bounded by
`newer_than:<monthsOld>m`, so an explicitly re-queued mail OLDER than 6 months never re-enters,
silently. Measured on gmail-bs: only **62 of 299** failed items are in-window — the operator can
restart a fifth of what the board offers to restart. (First live proof used a 2025-08-06 mail:
the relabel landed perfectly and the scan can never see it.) Options: treat the to_sync label as
explicit intent exempt from the discovery bound (label-scoped listing, not query), or gray out /
annotate out-of-window items on the board so the offer is honest. Until ruled, the second is the
truthful minimum.

## Phantom "delivered" ledger rows — the gmail analogue of the census loss

`sync_ledger` holds **1,932 `delivered` rows with no `doc_id`**, gmail-heavy (mail-private 796,
gmail-doc 641, gmail-link 410, gmail-bs 78, drive 7). Cross-matched by SOURCE_ID, upper-bound
REAL misses (row says delivered, no document found): gmail-doc ≈185, gmail-link ≈34, gmail-bs 1,
mail-private ≈786 (paused pipe, dev-era backfill history; overlaps gmail-doc's label). These
mails are in the ledger's own "done" memory, so the DIFF never re-offers them — same mechanism
as the drive-side census loss. The board's בדיקת התאמה (read-only reconcile) is the right
surface: it should count "ledger-delivered but absent in INDOX" per pipe and offer RELEASE
(the verb exists) for in-window items. Not executed tonight — needs the same care as the drive
census (SOURCE_ID matching is weak for gmail; hash-level verification before any release).

## Operator-coverage gaps remaining (not fixed tonight — decisions/scoping)

- `OldDocumentMonthsBack` has **no typed control in the UI** (only an untyped key/value row
  in הגדרות); the one knob that bounds every pipe's discovery is invisible from סנכרון.
- No UI for `sync_cursor` rewind ("rescan history") or the `sync_attempt` retry queue
  (due/backoff retries invisible).
- `batch.schedule_min` is stored but honored by nothing (cards honestly print the global
  15m).
- "הרץ עכשיו" is often `skipped` (reconcile lock held by the scheduled pass) — rendered
  honestly, but there is no force/override.
- Gmail `page_size`/`chunk` mismatch can silently drop messages; PipeEditor exposes neither.
- PipeEditor edits only `pairs[0]` of multi-pair drive pipes (disclosed in-UI).
- Active-in-prod test/reset workflows with live webhooks: `syncV3FullTest01`
  (`sync-full-e2e-lane`), `drainPoolTest01`, `drainPoolTarget01`, `IndoxResetFull01`,
  `IndoxResetGml001`, `tVzFMkz18pCsXRyw`.
- `POST /repos/<repo>/sync` has zero UI callers; `?with_items=1` unreachable from the SPA.

## Ground-truth blocker (unchanged)

Drive folder shares to the service account are still revoked (~08-16): folder-scoped
listings empty, folder ids 404 to the SA. Until the owner re-shares, drive-side "remaining"
cannot drain and the census fids cannot re-deliver (`NATURAL REDELIVERY = 0` all night).
The UI now shows this truthfully as remaining/failed counts; the fix is the re-share.
