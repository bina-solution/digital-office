# INDOX — the solution

**As built 2026-09-02.** One document for the whole INDOX pipeline: how external sources are
synchronised into the platform (Part A), and how every document is then driven to its terminal
state by the state machine (Part B). Everything here is named as it is in the code:
`apps/indox/blueprint/n8n/<id>.workflow.ts` for workflows, `apps/indox/app/incoming_documents/api/__init__.py`
for the BFF, `apps/indox/app/webapp/src/` for the UI, `apps/indox/hooks/*` for the `bbox indox` verbs,
`apps/indox/blueprint/fixtures/` for schema and seeds. Superseded plans and reports live under
`ai/context/archive/indox-pre-2026-09/` and `apps/indox/archive/` — they are history, not design.

---

## Part A — Sync

### A1. What sync is, in one paragraph

A **source** is a Google Drive folder or a Gmail label, reachable through a platform **connection**
(the `drive` and `mail` apps own the credentials; n8n holds none). **Discovery** runs once per
platform on a schedule and writes one row per external item into **our database** — the *sync
item*. **Delivery** takes pre-discovered items, downloads the bytes through the platform apps, and
creates the document row that the state machine will process. Nothing in the source (a "synced"
folder, a "processed" label) is ever read to decide state; those are user-visible marks that
delivery may leave behind through *source feedback*, and a registry needs only the source folder
or label — destinations are optional. Sync state is one table, counted by one view, drawn as one
bar per pipe.

### A2. The rules the design is held to

| # | Rule (owner) | Where it is enforced |
|---|---|---|
| 1 | State lives in OUR DB, per item, persistently | `indox_<tenant>.sync_ledger` (§A3); the only writer is `syncLedgerApi01` |
| 2 | Discovery once per platform, periodically; sync processes only pre-discovered rows; no discovery inside sync | `syncDiscoverDrive01` / `syncDiscoverGmail01` write, `syncRun01` only TAKEs |
| 3 | Not dependent on completion tags or destination folders | delivery reads the row's `listing`; feedback is optional (`feedback_on_success/failure`) |
| 4 | Registry requires only source folder / tag | `_validate_sync_entry` (BFF): gmail needs `labels.to_sync`, drive needs `to_sync` (or `from`) |
| 5 | An item older than `OldDocumentMonthsBack` is never even listed | the age bound at discovery (both sources), a defence-in-depth guard on the listing, and expiry at TAKE (§A6) |
| 6 | The INDOX BFF talks to no other app | counts from the view; run/reset through n8n's manage door; pickers are the browser's business (`/a/drive`, `/a/mailview`) |
| 7 | One IMAP connection per mailbox | `GMAIL_IMAP_READ_POOL=1` in the mail app; nothing in INDOX opens a mailbox |
| 8 | Nothing blocks deleting a registry entry | `DELETE /sync/registry/<name>` has no pipe-identity assertion; rows in the ledger stay as history |
| 9 | Sync UI = one bar (blue to sync, green synced, red failed), DB-only | `SyncStatePage.tsx` `StateBar` over `sync_item_counts` |

### A3. The sync item

Table `indox_<tenant>.sync_ledger` (schema: `apps/indox/blueprint/fixtures/schema.sql`; migrations
`scripts/ops/migrations/2026-09-02_sync_item*.sql`). Primary key `(source, platform_id)` where
`source = '<instance>/<pipe-name>'` and `platform_id` is the Drive file id or the Gmail message id
(the stable hex id from `X-GM-MSGID`, never a per-folder IMAP UID).

| Column | Meaning |
|---|---|
| `status` | `discovered` → `claimed` → `delivered` \| `failed` \| `needs_review` |
| `listing` (jsonb) | what delivery needs and nothing more: drive `{id,name,md5,size,link,createdTime,mimeType}`, gmail `{uid,subject,from,date,hasAttachment}` |
| `discovered_at`, `claimed_at`, `delivered_at` | the three timestamps of the lifecycle |
| `attempts`, `not_before`, `last_error` | the retry budget, the backoff, the reason |
| `doc_id`, `content_hash` | what delivery produced |
| `instance` | tenant tag (the schema is the tenant boundary; this is informational) |

State diagram:

```
            UPSERT (discovery)                TAKE (run)                 RECORD (delivery ok)
  (none) ───────────────────► discovered ──────────────► claimed ────────────────────► delivered
                                  ▲                        │
                 backoff elapsed  │            FAIL (retryable) / REAP (stuck claim)
                                  └──────────────── failed ◄─┘
                                                     │  attempts ≥ max_attempts, or [terminal]
                                                     ▼
                                                needs_review  ◄── expiry at TAKE (older than the window)
                                                              ◄── unlisted at TAKE (empty listing a day after discovery)
  RESET (retry failed / full re-drive) : failed | needs_review | delivered → discovered   (purge:true deletes)
```

`needs_review` is the dead-letter state: nothing retries it; the operator's *retry failed* button
(RESET with `statuses: ['failed','needs_review']`) is the only way back.

View `sync_item_counts` (one row per `source`): `discovered, claimed, delivered, failed,
needs_review, total, last_discovered_at, last_delivered_at, last_claimed_at, last_error`, plus the
lag metric added 2026-09-02: `oldest_waiting_at` and `waiting` (items still owed: discovered /
failed / claimed — `needs_review` excluded, the way a queue excludes its dead-letter messages).

`sync_cursor` (per source): `mode, walk_token, steady_cursor` — the Gmail UID walk position
(§A5). Drive keeps no cursor: every pass lists the whole window.

### A4. The registry — `settings.sync_registry`

One JSON array in `indox_<tenant>.settings` (`key='sync_registry'`, `instance='incoming-documents-main'`);
every mutation is a read-modify-write of that row (`_read_sync_registry` / `_write_sync_registry`).
Example: `apps/indox/blueprint/fixtures/sync_registry.example.json`.

| Field | Drive pipe | Gmail pipe |
|---|---|---|
| `name`, `source`, `enabled`, `engine:'v3'` | required | required |
| `connection` | the drive connection id (catalog) or `profile_id` (local engine) | the mailbox connection id |
| scope | `pairs[]` with `to_sync` (or `from`) — **required**; `synced` / `failed` optional | `labels.to_sync` — **required**; `labels.synced` / `labels.failed` optional; `query` / `search_extra` optional |
| `dest_folder` | — | where attachments are uploaded (private drive); optional |
| `type_hint`, `type_authority` | `fallback` / `hint` / `decisive` — the type vote weight in `SelectBase01` | same |
| `batch` | `take`, `chunk`, `timeout_min` (claim lease, floor 14), `schedule_min` | same, plus `page_size` |
| `max_attempts`, `base_backoff_s` | retry budget (default 5 / 60 s) | same |
| `feedback` | `feedback_on_success` / `feedback_on_failure` (moves) | (labels) |

Optional knob `DriveSearchConnection` (settings): which Drive `find_link` / `check_from_office`
search; absent = the first enabled drive pipe's connection (§B8).

### A5. The workflows — nine, and what each node does

All carry tag `app:indox`, `callerPolicy: workflowsFromSameOwner`, `errorWorkflow: errorHandler01`.
Every request carries `__instance` (the tenant); a missing one throws — there is no public fallback.

**`syncLedgerApi01` — Sync Item API (4 nodes).** `When Called` → `Build SQL` → `PG Execute` → `Reply`.
The ONLY writer of `sync_ledger` / `sync_cursor`. The op table:

| op | statement, in words |
|---|---|
| `UPSERT` | insert every listed item as `discovered`; on conflict, refresh `listing` only when the row is not `delivered` and the listing changed. Returns `discovered / refreshed / listed`. |
| `TAKE` | expire (→ `needs_review` "[expired] older than OldDocumentMonthsBack") any owed item whose own source time fell out of the window; dead-letter (→ `needs_review` "[unlisted] …") any owed item still carrying an EMPTY listing a day after discovery — discovery runs before every take, so an empty listing means the source no longer lists it (measured 2026-09-02: eight such rows had waited four weeks); then claim up to `limit` items — `status in (discovered, failed)`, non-empty `listing`, `not_before` passed, `attempts < max_attempts` (from the registry via a CTE), failed first, oldest first — `for update skip locked`, in one statement. |
| `RECORD` | delivered (or `needs_review`) with `doc_id` / `content_hash`; never overwrites a `delivered` row. |
| `FAIL` | `attempts+1`, `last_error`, `not_before = now + full-jitter backoff` (`random() * min(3600, base·2^attempts)`), `status = needs_review` when the error is terminal (`[terminal]` in the message, or the sentinel host `*.terminal.invalid`) or the budget is spent, else `failed`. |
| `RELEASE` | a claim handed back untouched (`claimed` → `discovered`). |
| `RESET` | re-drive: `statuses` filter (`failed`,`needs_review` for the board's retry; absent = every non-discovered row = full re-drive, which also deletes the cursor); rows with an empty listing are counted as `skipped_no_listing`; `purge:true` deletes (test teardown). |
| `REAP` | claims older than the pipe's `timeout_min` → `failed` with backoff (or `needs_review` at the budget). Scheduled by `indox01` every 5 min. |
| `GATE`, `CURSOR_GET`, `CURSOR_SET` | counts; the Gmail cursor. |

**`syncV3Main0001` — Sync Main (10 nodes).** `When Called` → `Try Lock` (`processLock01`, key
`reconcile:<instance>`) → `Lock Acquired?` (held → dead end; the door reports `skipped`) → `Read
Config` (one query: `indoxSyncOn`, `OldDocumentMonthsBack` (default 6), the registry, the label
vocabulary from `tag_rules`) → `Build Pipes` (one unit per enabled pipe; a scoped run keeps one;
`_no_units` sentinel with `status:'noop'`) → `Route Source` (drive / gmail / none) → `Discover Drive
Each` / `Discover Gmail Each` (wait) → `Run Each` (no wait — n8n's worker pool is the backpressure)
→ `Unlock`. Outline stamped on the execution: `sync-main_x<N>_units[_OFF]`.

**`syncDiscoverDrive01` (6 nodes).** `List Req` (`createdAfter = now − months`, `limit` = the whole
window, 2000 default / 5000 max — the drive app pages internally, newest first, so a per-page cap
would hide the oldest files of a big folder forever) → `List` (`driveApi01` op `list`) → `Upsert Req`
(listing per file; drops any file older than the window by its own `createdTime`; counts `_too_old`)
→ `Call UPSERT` → `Result` (outline `<pipe>_x<discovered>_of<listed>_discovered[_TRUNCATED]`).

**`syncDiscoverGmail01` (10 nodes).** `Cursor Req` → `Call CURSOR_GET` → `Search Req` (op
`searchRaw` on `[Gmail]/All Mail`: `label:<to_sync>` + pipe `query` + `search_extra` + **always**
`newer_than:<months>m` — a pipe's own `newer_than` can only tighten the window; `since_uid` from the
steady cursor; `limit = page_size`) → `Search` (`gmailApiImap01`) → `Upsert Req` (one item per
message id; drops messages older than the window by their `date`; decides the next cursor: max UID
clamped to `next_cursor`, never backwards, `UIDVALIDITY` change → anchor 1) → `Call UPSERT` → `Cursor
Set Req` → `Call CURSOR_SET` → `Result`.

**`syncRun01` (8 nodes).** `Take Req` (`limit = min(take, chunk)`, `months`) → `Call TAKE` → `Build
Payloads` (rows filtered on `platform_id`; payload = `listing` + the unit's `list_ctx`, `feedback`,
budget, `__instance`) → `Route Kind` → `Deliver Drive Each` / `Deliver Gmail Each` / `Deliver Link
Each` (no wait).

**`syncDeliverDrive01` (7) / `syncDeliverGmail01` (10) / `syncDeliverLink01` (10).** Download through
`driveApi01` / `gmailApiImap01` (attachments: split, filtered by type/size; link mails: the link in
the body, or the sentinel `http://no-link-in-message.terminal.invalid/`), upload to the pipe's
`dest_folder` on the private drive when configured, hash, `DELIVER` into `indoxApi01` (the single
write door: `WHERE NOT EXISTS` on `(HASH)` or `(SOURCE_TYPE, SOURCE_ID)`, mints `doc_<base36>`,
fills `SOURCE_LIST[origin='self']`), then `RECORD`; any error → `Fail Req` (`terminal` when the
message carries `[terminal]` or the sentinel host) → `Call FAIL`.

**`SyncApi0000000001` — the manage door (11 nodes).** Webhook `indox-manage` (and `When Called`) →
`Normalize` (valid `__instance` required) → `Action Switch`: `SCAN` → `Call Main` → `Scan Reply`
(`{ok, status: ran | skipped | error, execution_id, workflow_id}`); `RESET` → `Call Ledger` (`RESET`
with `source` or `source_like:'%'`, `statuses`, `purge:false`) → `Reset Reply`; else `Unknown Action`.

Scheduling: `indox01` (§B1) dispatches `sync` every 15 min (`indox.auto.sync.every`) and
`ledger_reaper` every 5 min; `indoxSyncOn=false` makes every pass a no-op (`sync-main_x0_units_OFF`).

### A6. The age bound, end to end

`OldDocumentMonthsBack` (settings; fixture seeds 6; UI knob) is read once per pass by Main and rides
on every unit as `months`:

1. **Drive discovery** lists with `createdAfter = now − months` and drops anything older by its own
   `createdTime` before UPSERT (an engine that ignored the bound cannot leak an old file in).
2. **Gmail discovery** always searches with `newer_than:<months>m` and drops anything older by its
   `Date` before UPSERT.
3. **TAKE** expires an owed item whose source time fell out of the window since discovery (a narrowed
   setting, a long backlog): it becomes `needs_review` with the reason, never a document delivered
   years late — and never a document in `incoming_documents` at all.
4. **The state machine** terminalises an old document (`update_status_old_doc`) if one ever arrived
   by another path (manual upload, an older release).

### A7. Feedback — the one writer of source moves and labels

`indoxV2ActionsGlobal01 :: source_feedback_<idx>` (§B6): after a document finishes (the owner's
definition of *success* — `COMPLETED` with base and per-type extraction complete and a company and a
document id), and only when the pipe asks for it (`feedback_on_success` / `feedback_on_failure`),
the file is moved to the pipe's `synced` / `failed` folder, or the message gets the `synced` /
`failed` label **and loses the pipe's to-sync label** (2026-09-02: one mailapi call, `/labels/add`
with a `remove` list — a message that carried both "waiting for the automation" and "handled" was
the measured state of every message of the first real run). Label names resolve from the mail
app's organizer store (`GET http://mailapi:8970/organizer/settings`, the one store since
`tag_rules` retired). A drive pipe whose `to_sync` and `synced` are the SAME folder (the client's
whatsapp-bot / drive-bs shape) completes with the destination recorded and no move; the laptop's
brand-new INDOX/<pipe>/{to_sync,synced,failed} trees move. Every refusal is recorded on
`SOURCE_LIST[idx].sync_feedback_*` and completed, so the gate never re-decides it. Sync state is
untouched by any of this.

### A8. BFF, UI, CLI

**BFF** (`api/__init__.py`, section "INDOX sync control plane"):

| Route | Does |
|---|---|
| `GET /sync/registry` | the registry with counts from `sync_item_counts` (`counts`, `counts_computed`, `last_*`, `last_error`, `oldest_waiting_at`, `waiting`), plus `n8n_base` for execution links |
| `POST /sync/registry`, `PUT/DELETE /sync/registry/<name>` | read-modify-write of the row; validation = source scope only; delete is unconditional |
| `POST /sync/run[?sync=<name>]` | `SCAN` through the manage door (all enabled pipes, or one) |
| `POST /sync/registry/<name>/reset` | `RESET` `failed`+`needs_review` (`all:true` = full re-drive) |
| `POST /sync/stop-all` | `enabled:false` on every pipe and `indoxSyncOn=false` |
| `GET/PUT /config/settings` | the knobs (`indoxSyncOn`, `indoxDrainOn`, `OldDocumentMonthsBack`, …) via `_EDITABLE_SETTINGS_KEYS` |

**UI** (`pages/SyncStatePage.tsx`): master switch (`indoxSyncOn`), one card per pipe with the
`StateBar` (blue = discovered + claimed, green = delivered, red = failed + needs_review), *run* /
*retry failed* / *edit* / *delete* / *enable*, "last delivery", "waiting longest", the last error;
the editor picks connections, folders and labels from the sibling apps under the console shell
(`/a/drive/…`, `/a/mailview/…`). The old settings→sync tab, the engine view, the run-progress
overlay and the docs-state board are gone.

**CLI** (`bbox indox …`): `sync` (run / list), `sync-reset [--sync-name] [--purge]`, `sync-state`,
`test <suite>`, `demo run`, `apply-schema`. `bbox n8n push indox <ids>` deploys workflows.

### A9. Tests and coverage

| Suite (`bbox indox test <key>`) | Workflow | Proves |
|---|---|---|
| `sync_kernel` | `syncItemApiTest01` (34 checks) | every ledger op on the test tenant: upsert / take / record / fail / reset / reap / cursor / gate |
| `sync_sources` | `syncSourcesTest01` (14) | injector → real pass → every discovered item delivered with a document; settles by polling the ledger |
| `sync_full` | `syncFullTest01` (9) | the pass itself: the `indoxSyncOn` gate, the reconcile lock, an unknown / a private registry key |

Battery of 2026-09-02 (before the thinning): all 15 suites green; node coverage over the battery
window: the eight sync workflows 100 % except `syncDeliverDrive01` (71 %: its fail path never ran —
no drive delivery failed), `SyncApi` 82 %. Gate `apps/indox/hooks/sync-coverage.py` (profile
`sync-v3`) enforces the sync set; `scripts/n8n-node-coverage.py --min 80` measures every CORE
workflow.

### A10. Sync best practice — verdict on this design

Researched 2026-09-02 against Google's Drive / Gmail API guidance, RFC 3501, AWS SQS / Google
Pub/Sub retry and dead-letter guidance, and Postgres `SKIP LOCKED` queues (sources in
`ai/context/archive/indox-pre-2026-09/README.md`).

Matches best practice: the discovery / delivery split; an idempotent upsert keyed on a stable
external id (`X-GM-MSGID` for mail — a UID-keyed row would re-list the mailbox on every
`UIDVALIDITY` reset); `for update skip locked` + a claim lease + a reaper; capped retries with jitter
and a dead-letter state; content-hash dedup as the at-least-once safety net; sync state independent
of the source's folders / labels; the 15-minute cadence (Google's own client guidance is 10).

What the research changed today: full jitter instead of equal jitter (AWS measured it better on
completion time and total work); the age bound enforced at three places including TAKE (the
"zombie" of a narrowed window); the whole-window drive listing (no per-page cap); the lag metric
(`oldest_waiting_at`) exposed per pipe.

Known issues to keep in mind (documented, not defects):

- Drive `createdTime` is set by the uploader and survives a move: a file moved *into* a watched
  folder with an old creation date is, by the owner's rule, never listed. A daily overlap-free
  reconcile is unnecessary here because every pass lists the whole window.
- Gmail `newer_than` is day-coarse and evaluated on the internal (received) date; our guard uses
  the `Date` header — a message a few hours across the boundary can differ between the two.
- Gmail's search index lags a minute or two for brand-new mail; the next pass gets it.
- Drive listings are eventually consistent for seconds after an upload; same answer.
- Drive `403 userRateLimitExceeded` / Gmail `[ALERT] Too many simultaneous connections` /
  `[OVERQUOTA]` are handled by the apps (retry, one connection per mailbox) and surface as a
  `failed` item with backoff, never as a wedged pass.
- Moving to Drive `changes.list` (with a client-side `parents` filter) is the documented next step
  only if a folder exceeds ~10k files inside the window or moved-in files must land within one poll.

### A11. The decisions (D1–D11, as approved and amended)

| # | Decision | Where it landed |
|---|---|---|
| D1 | persistent per-item state, no duplicate tables | `sync_ledger` evolved in place; `sync_attempt`, `sync_pipe_state`, `indox_sync_stats` dropped |
| D2 | the workflow list; `processLock01` stays platform-level; `mailDiscovery01` replaced | nine sync workflows; 13 retired workflows deleted live (laptop and server) |
| D3 | prove a full reset comes back; `mail-private` deleted; sync off locally before go-live | `IndoxResetFull01` → `RESET purge`; the pipe is gone; `indoxSyncOn=false` on the laptop |
| D7 | apitools gating kept; mail-compose pool forward investigated | apitools stays behind `authentik@file`; the mail app forwards nothing to INDOX |
| D8 | `ensureFolder` + thumbnails proven | `driveApi01` op `ensureFolder`; `indoxV2UploadApiTools01` renders and uploads `<hash>.jpg` |
| D9 | live on the server | phase 9/10 of this release (§C3) |
| D10 | every link in the live table works | `LINK` / `THUMBNAIL` are the private drive's own links (`https://drive.<domain>/file/d/<id>/view`); legacy `drive.google.com` rows are the client's historical Google links |
| D11 | nothing blocks deleting a registry entry | the pipe-identity assertion is gone |

---

## Part B — The state machine

### B1. The chain

```
indox01 (clock, every 2 min; public.app_settings 'indox.auto.*'; public.indox_instances)
  → indoxV2BaseDrain01   (per instance: selects IDs, P lanes × B documents)
    → POST /webhook/incoming-documents-017
      → indoxV2Driver01  (per document: lock, decide, double-action guard, group, dispatch)
        → indoxV2Decide01 (Mega Decide: the six decide functions rehydrated in one process)
        → POST /webhook/indox-action-router
          → indoxV2ActionRouter01 (Log Action Start → Switch1 → lanes → Log Action End)
            → indoxV2ActionsGlobal01 | Inv01 | Ship01 | BS01 | Ord01 | Rcp01
              → indoxApi01 (INLINE_ACTION=UPSERT — the single write door, and the unlock)
```

Two invariants every node repeats: **an action always stamps its own completion flag** (or decide
re-dispatches it forever), and **the only sanctioned re-run is `STATUS='ACTION_RESTART'`** — the
machine never retries itself.

**`indox01` — the scheduler (9 nodes).** `Tick` (2 min, deliberately not settings-driven: an interval
is registered in main's memory at activation) → `Load Plan` (`public.app_settings` `indox.auto.%`,
`public.indox_instances` with `enabled` and `purpose <> 'test'`, `public.app_schedule_state`) →
`Decide Due` (master `indox.auto.on`, default **false**; per job `indox.auto.<job>.on`, default on;
state-based dueness: a pair with no state row is due) → `Route Job` → `Call Drain` (`drain` 2 min,
`drain_full` 120 min → `mode=all`) / `Call Sync` (15 min) / `Call Reaper` (5 min, `op:'REAP'`) /
`Call Health` (10 min) → `Mark Dispatched` (stamps `last_run_at` before the call; its RETURNING list
is a field filter — anything not named there is gone).

### B2. `indoxV2BaseDrain01` — the drainer (26 nodes)

Entries: `Drain Webhook` (`POST /webhook/indox-drain`, the operator API; bypasses the gate and the
solo check by design), `When Called` (the scheduler). `Read Settings` reads, with COALESCE defaults,
`indoxDrainOn` (true), `indox.statemachine.drain.parallel` (4), `driver.batch` (2000), `driver.max`
(2000), and the DB clock (`db_now` — the host may run hours ahead of the database).

Selection (`Normalize Request` → `Select IDs`, newest first because the order IS dispatch priority):

| mode | WHERE |
|---|---|
| `all` (full sweep) | `true` — decide is the filter, a no_action verdict costs nothing |
| `changed` (incremental) | `updated_at > now − 15 min OR (STATUS='IN_PROGRESS' AND updated_at < now − 70 min) OR STATUS='ACTION_RESTART'` — the stranded re-pick (a lane can block on its router POST up to 60 min; the reaper closes the log row at 65) and the operator's restart, picked every pass however old |
| `ids` / `status` | explicit lists (pipe-joined — n8n's query parameter is one string) |

`Solo Check` (n8n DB: another running drain for the same instance blocks) → `Reap Stale
Dispatches` (`indox_action_execution_log` rows open > 65 min get `ENDED_AT`) → `Init Pool` (batches
of B) → `Scheduler` (global admission: `slots = P − running drivers`, counted across every running
driver) → `Fire Lanes` (`POST /webhook/incoming-documents-017` with `IDS`, `__instance`, `MAX`, `DRY`,
the trigger chain) → `Tick Wait` (`pg_sleep(3)`) → `Poll Status` / `Poll Progress` (the progress
signal is `ENDED_AT`, not started) → `Reconcile` → `Summarize` (`RESULT: OK | ATTENTION`).

### B3. `indoxV2Driver01` — the driver (38 nodes after 2026-09-02)

`Webhook` (`incoming-documents-017`, responds immediately) / `When Executed by Another Workflow` →
`Code in JavaScript` (one item per ID; `LANE_MAX` circuit breaker) → `Switch` (`run_by_id` /
`run_lines` / fallback `Stop and Error1`) → `MAP ID` → `Get Line Req` → `Call indox api (Get Line)`
(`INLINE_ACTION:'GET'`) → `Get Line Match` → `Map ID Match Line Data` (unresolvable ids are
skipped, never thrown) → `Start` → `Read Action Caps` + `Main 2k batch` →

- `Enrich Double Lines` (one SQL pass): the duplicate detector (`IS_DOUBLE`, `IS_MAIN_DOUBLE`,
  `LINES_TO_MERGE`; key tiers COMPANY_ID+DOC_ID → HASH → COMPANY_ID+SHORT_DOC_ID), the row-carried
  settings (`__merge_enabled`, `__source_feedback_enabled`, `__priority_sync_enabled`,
  `__priority_local`, `__old_months`), the feedback pointer (`__feedback_idx/key`), and the four
  identity hashes (`__priority_sig`, `__base_selection_hash`, `__selection_hash`, `__line_hash`).
- `Get Action History`: the newest 16 dispatches per document from `indox_action_execution_log`
  (with the `LINE_HASH` stamped at dispatch), and — new 2026-09-02 — `__dispatches_since_restart`,
  the count of dispatches since the last `restart_*` dispatch: the step budget's real counter.
- `Attach Action History` (drops `SOURCE_LIST` from the payload — the fattest column) → `Call
  indox-v2 Decide` → `Dup Guard: Double Action` → `IF NOT SAME ACTION TWICE` → `If ACTION`
  (`no_action_*` verdicts stop here) → `If Dry?` → `Taking Action` → `Check LOCKED`
  (`processLock01`, key `<ID>::<ACTION>`, fails closed) → `Join LOCKED` → `If NOT LOCKED` →
  `Execute Action` → `Group By ACTION` (one group per action, chunked by
  `indox.statemachine.action_router.<action>.max`, cheap actions first, round-robin) → `Loop Over
  Items` (2 concurrent) → `POST Action Router (group)` (blocking until the lane finishes and unlocks).

**The double-action guard** (the owner's law): the same action dispatched again on an *unchanged*
line (same `LINE_HASH`) with no restart in between is rewritten to
`no_action_double_action_blocked`, recorded, and raised once after the lane finishes (`Raise Double
Blocked`). Escapes: `restart_*` actions; a live race (the same action still open < 20 min, or
`IN_PROGRESS`) is silently skipped; a dead owner (`IN_PROGRESS` ≥ 70 min) is re-run.

Removed 2026-09-02 (unexecuted in the battery, unreachable on the map): the disabled `Action
Filter`, the always-true `If group action` and its "all lines" POST twin, the manual `run_page`
sweep (5 nodes + the manual trigger seed), three island nodes.

### B4. `indoxV2Decide01` — the decide ladder (15 nodes)

`Mega Decide` rehydrates the six decide functions exported by the lanes (`Export Seed (…)` →
`Call Export (…)` with `mode='export_decide'`) and runs them in one process (eight graph-path
decides once took 15 minutes each). Per row: normalise (`''`→null, `'true'/'false'`→bool, Excel
serial dates → `DD/MM/YYYY`); the **doubles gate** first (`MERGED` absorbing; `IS_MAIN_DOUBLE` →
`action_merge_doubles` when `indoxDoubleMergeOn`, else `no_action_merge_blocked`; a non-main →
`update_status_double`); then `docBaseRouterDecide` on everything; rows that come back as a
`__route_<class>__` sentinel go through their lane's function.

**Entry gates** (`indoxV2ActionsGlobal01 :: Decide DOC BASE Action`): TEXT-boolean normalisation;
tombstones (`MERGED`, `GARBAGE`, `DOUBLE`) skip the age gate; **the old gate** —
`anyOldDate([RECEIVED_DATE, DOC_DATE, AI_DOC_DATE, BS_LINE_DATE, LOCAL_DOC_DATE], months)` (months =
the row-carried `OldDocumentMonthsBack`, default 6; two-digit-year pivot, `.`→`/`, plausibility
window, swap-mangle and year-misread rejection; `some`, not `every`) → `update_status_old_doc`.

**`docBaseRouterDecide`, in order:** adopt `AI_TYPE` when `TYPE` is blank → `no_action_delete_row`
(no ID) → `no_action_merged` → **source feedback** (`__source_feedback_enabled`, `__feedback_idx`,
outcome not `pending`) → `update_status_garbage` / `no_action_garbage` → `no_action_max_iterations`
/ `mark_max_iterations` (`__dispatches_since_restart ≥ 25`, never on `COMPLETED` / `OLD` /
`ACTION_RESTART`) → `docBaseDecide` → the class sentinel or `update_status_missing_type`.

**`docBaseDecide`:** `ACTION_RESTART` → the typed lane's restart (or `restart_base`) → the late old
gate → `no_action_paused` → `extract_base_doc` (has `LINK` + `LINK_CONNECTION`, no `TYPE`, base not
complete — the value+flag rule) → `select_base` (not complete, or `BASE_SELECTION_HASH` differs from
the row's current base hash — must stay above the company gates) → company gate
(`update_status_missing_company` / `no_action_awaiting_company_id` / `no_action_already_completed`)
→ name gate (`get_company_name` once, then `update_status_unknwon_company`) → null (route by type).

**Classes:** `INVOICE` → `invoice` lane; `SHIPMENT` → `shipment`; `BALANCE_SHEET` → `bs_doc`;
`ORDER` / `RECEIPT` → *parked* (recorded, not processed: `mark_completed` only); anything else →
`MISSING_TYPE`.

**Invoice ladder** (`indoxV2ActionsInv01 :: Decide GDoc Action`): `gdocHead` (`restart_gdoc`,
`get_short_doc_id`, `update_name` = `<COMPANY_NAME>-<SHORT_DOC_ID>`, `check_from_office`) →
`find_link` (link missing, drive search not yet done, name + id known) → `update_status_missing_link`
/ `no_action_link_not_found` → `update_status_api_tools_failed` (both branches park — the machine
restarting itself is a retry loop wearing an action's name) → `extract_per_type` →
`update_company_doc_id` → `gdocTail`: the BS-line link lock → `select_type` (not complete, or
`SELECTION_VALUES_HASH` differs — deliberately no STATUS term: a late aging-report line re-opens a
COMPLETED document's selection) → priority sync (`no_action_priority_sync_failed` /
`_missing_identity` / `restart_priority_sync` on a changed signature / `action_priority_sync`) →
`mark_completed` → `no_action_already_completed`.

**Shipment ladder** (`indoxV2ActionsShip01`): the same head; `find_link` is never dead-ended; the
API-tools gate parks on both branches (aligned with Inv01 on 2026-09-02 — the type-less
`restart_base` arm is gone); `extract_per_type`; `update_company_doc_id` from
`SHIPMENT_DOC_ID` / `AI_SHIPMENT_IDS`; `gdocTail`. The lane's entry routes SHIPMENT only and throws
`[terminal]` for any other type (the dormant invoice / order copies were removed).

**Balance-sheet ladder** (`indoxV2ActionsBS01`): `restart_balance_sheet` → company gate →
`extract_per_type` (sentinel value `BS_EXTRACTED_LINES`) → `update_status_extraction_failed` (no
lines, or not `BS_EXTRACTION_VERIFIED`) → `link_documents` (once) → `select_type` → `mark_completed`
when `hasAllRequiredFields` → `no_action_already_completed` / `no_action_unhandled_state`.

**Parked ladders** (`Ord01`, `Rcp01`): `MERGED` → `no_action_merged`; not `COMPLETED` →
`mark_completed`; else `no_action_already_completed`.

### B5. `indoxV2ActionRouter01` — the action router (22 nodes)

`Router Webhook` (`indox-action-router`, responds after the lanes finish — that is what makes group
dispatch parallel: a new Bull job per group) / `When Called Directly` → `Normalize Action Lines` →
`Log Action Start` (INSERT into `indox_action_execution_log` with the `LINE_HASH`, `queryBatching:
independently`) → `Switch1`:

| out | rule | lane |
|---|---|---|
| 0 | `ACTION` ∈ the base-lane array, **or** starts with `source_feedback_` | `indoxV2ActionsGlobal01` |
| 1 / 2 / 4 / 5 / 6 | `DOC_TYPE` = `invoice` / `bs_doc` / `shipment` / `order` / `receipt` | the typed lane |
| 3 | `empty_row` (sheets legacy) | straight to `Router Done` |
| fallback | | `Stop and Error` "UnHandeled Document" |

→ `Log Action End` (UPSERT `ENDED_AT`) → `Router Done`. The base-lane array names exactly what
`docBaseRouterDecide` / `docBaseDecide` / `unknownTypeAction` can return (gate G51 checks it; five
retired names were removed 2026-09-02).

### B6. `indoxV2ActionsGlobal01` — the global actions (64 nodes)

`Route Mode` (`export_decide` / execute) → `DOC BASE Action Switch`:

| action | does | writes |
|---|---|---|
| `restart_base` | clears every `*_COMPLETED`, `ITERATION_COUNT=0`, `ERROR=null` | `STATUS='IN_PROGRESS'` |
| `update_status_*` (double, missing company, unknown company, missing type, old, garbage) | one status stamp each | `STATUS` (+ `IS_OLD`, `OLD_REASON`) |
| `get_company_name` | `indoxSettings01` companies → join | `COMPANY_NAME`, `COMPANY_NAME_COMPLETED`, `RETRY_COUNT` |
| `mark_max_iterations` | the ceiling | `STATUS='MAX_ITERATIONS'` |
| `extract_base_doc` | `BaseDocEx01` (§B8) → `Select Base Values` (the failure classifier: bad file type / broken link / too big / apitools overloaded / network / corrupt PDF) | `LOCAL_*`, `AI_*`, `API_TOOLS_ID`, `THUMBNAIL`, `BASE_EXTRACTION_COMPLETED`; on failure `STATUS='EXTRACTION_FAILED'`, `REQUIRED_ACTION`, `ERROR` |
| `select_base` | `SelectBase01` (§B8) | `COMPANY_ID`, `TYPE`, `DOC_DATE`, `COMPANY_BY_SENDER`, `TYPE_BY_SOURCE`, `BASE_SELECTION_COMPLETED`, `BASE_SELECTION_HASH` |
| `action_merge_doubles` (`resolve_double` case) | `Adjudicate Merge` → `indoxApi01 MERGE` | winner/loser rows, `MERGED`, `DOUBLE_LINE_CONTEXT` |
| `source_feedback_<idx>` | registry + the mail organizer store (KEY → label name) + fresh `SOURCE_LIST`; `drive_move` via `driveApi01`, `mail_tag` via `gmailApiImap01` `addLabels` (outcome label added, the to-sync label removed in the same call); **the action must always complete** | `SOURCE_LIST[idx].sync_feedback_*` |

Every terminal path ends at `Upsert (central)` (`indoxApi01`, `unlock:true`).

### B7. Per-type lanes — the actions

**Invoice (`indoxV2ActionsInv01`, 84 nodes):** `update_name` (+ Drive rename), `restart_gdoc`,
`get_short_doc_id`, `find_link` (`indoxV2SearchFile01` → `LINK` = the found file's own link,
`LINK_CONNECTION` = the Drive it was found in, `SEARCH_IN_DRIVE_COMPLETED`),
`update_status_missing_link`, `update_status_api_tools_failed`, `check_from_office`
(`indoxV2SearchWarehouse01` over the warehouse-scans folder from `WarehouseScansSourceFolder` →
`FROM_OFFICE`, `FROM_OFFICE_CHECK=true` even on failure), `extract_per_type` (`InvoiceDocEx01`),
`update_company_doc_id`, `select_type` (`SelectType01`), `action_priority_sync` (`Post Priority
Table` to the ERP or to `priorityLocalApi01`; `Verify Priority Row` — the row is the result),
`restart_priority_sync`, `mark_completed` (consolidates `DOC_ID`).

**Shipment (`indoxV2ActionsShip01`, 79 nodes):** the same set with `ShipmentDocEx01`; no
`If Search Completed` arm.

**Balance sheet (`indoxV2ActionsBS01`, 47 nodes):** `restart_balance_sheet`, `extract_per_type`
(`BsDocEx01`: `BS_EXTRACTED_LINES`, `BS_EXTRACTION_VERIFIED` = `summary.totalsMatch`),
`update_status_extraction_failed`, `link_documents` (matched line → the existing invoice row gets
`LINKED_BS`, `BS_LINE_*`; unmatched line → **spawns** an `INVOICE` row with `SOURCE_TYPE='BALANCE_SHEET'`),
`select_type`, `mark_completed` (+ `BS_LINK_DOCUMENTS_COMPLETED`).

**Order / Receipt (10 nodes each):** `mark_completed` only (`unlock:true` is load-bearing).

### B8. The extraction and selection arms

- **`BaseDocEx01`** — `Upload+OCR` (`indoxV2UploadApiTools01`: hash check → download through
  `driveApi01` → `POST apitools /documentOcr` → thumbnail obtained from the OCR raster and uploaded
  to `automations/thumbnails/<hash>.jpg`; 429 = shed, 413 = too big) → local leg (`JQExV3Base000001`,
  gated by `extraction_local_enabled`) ∥ AI leg (`indoxV2ExtractInvoiceGemini01`, gated by
  `extraction_ai_enabled`) → `NAME Company Match (Offline)` (the filename resolver over
  `companies`) → `Select Base` (pairs by index, refuses a mismatch). Writes readings, never finals.
- **`SelectBase01`** — company legs in order (LOCAL/AI pick, filename match, sender, text; the
  first three fill-only); the type vote (reader 2, lead reader 3 — `indox.extraction.type_priority`,
  default AI —, source `type_authority`: fallback 0 / hint 2 / decisive 100); the date guard (an
  AI-only future date is refused). Writes the finals and `BASE_SELECTION_HASH` over the post-write
  state (byte-identical to `public.indox_base_selection_hash`).
- **`SelectType01`** — per-type finals (fill-only `DOC_DATE` and `DOC_ID`, the junk-id rejector,
  the ledger tie-break), the corroboration score (AI / BS / KW over company id, doc id, date,
  amount, type: id mismatch 0, AI+BS 100, all four confirmed 100, no data mismatch 50, else 0),
  raised by `companies.SELECTION_CERTAINTY` (`FIXED_CERTAINTY`, `max(computed, fixed)`) or a trusted
  supplier (100). Writes `SELECTION_COMPLETED`, `SELECTION_VALUES_HASH`, `SELECTION_SCORE_DEBUG`.
- **JQExV3 engines** — one apitools `documentJsonQuery` call per document per category with the
  settings-driven `q_v3_*` queries (`q_v3_routing`); the company registry bound at call time.
- **`indoxApi01`** — the single write door: `UPSERT` (batch, `clean()` drops nulls so "no answer"
  leaves a column alone, `SOURCE_LIST` merged by `public.indox_merge_source_list`, unlock),
  `GET` / `GET_ALL` / `TABLE_GET` / `TABLE_UPSERT` / `DELIVER` / `MERGE` / `GET_CHANGED`; every SQL
  site resolves the tenant from `__instance`.
- **`indoxV2SearchFile01` / `indoxV2SearchWarehouse01`** — the two Drive searches resolve *which
  Drive* from settings (`DriveSearchConnection`, else the first enabled drive pipe's connection)
  through one `TABLE_GET`; no connection id lives in code.
- **Fixtures** (`fixtures/types/fixture_*.json`, the settings rows `fixture_<TYPE>`) — `detect`
  (keywords, priorities), `kw_extract` (field → query key), `select` (dimensions, tiers,
  `resync_fields` = the selection hash), `pipeline.steps` (the declarative mirror of the ladder),
  BS `bs_extract` / `spawn`, ORDER / RECEIPT `_parked`.

### B9. The document row vocabulary

STATUS values and their writers: `IN_PROGRESS` (restarts, BS spawn), `COMPLETED` (the five
`mark_completed` builds), `TO_EXTRACT` (ingest), `PAUSE` / `ACTION_RESTART` (operator),
`MISSING_COMPANY_ID`, `UNKNOWN_COMPANY`, `MISSING_TYPE`, `MISSING_LINK` (recoverable),
`API_TOOLS_FAILED`, `EXTRACTION_FAILED`, `PRIORITY_SYNC_FAILED`, `OLD`, `GARBAGE`, `MAX_ITERATIONS`,
`DOUBLE` (recoverable), `MERGED` (absorbing), `NEEDS_REVIEW` (operator-set; no live writer).

Completion flags and their readers: `BASE_EXTRACTION_COMPLETED` (B: extract gate),
`BASE_SELECTION_COMPLETED` + `BASE_SELECTION_HASH` (select_base), `COMPANY_NAME_COMPLETED`,
`API_TOOLS_ID_COMPLETED`, `PER_TYPE_EXTRACTION_COMPLETED`, `SELECTION_COMPLETED` +
`SELECTION_VALUES_HASH` (select_type), `SEARCH_IN_DRIVE_COMPLETED`, `PRIORITY_SYNC_COMPLETED` +
`PRIORITY_SYNC_SIGNATURE`, `BS_EXTRACTED_LINES`, `BS_EXTRACTION_VERIFIED`,
`BS_LINK_DOCUMENTS_COMPLETED`, `THUMBNAIL(_COMPLETED)`, `FROM_OFFICE_CHECK`. Every restart clears
them. `ACTION_LOG` is gone (2026-08-20): "was it dispatched" = `indox_action_execution_log`,
"is it done" = the flags, the step counter = `__dispatches_since_restart`.

The four SQL identity functions in `public` (pure, tenant-agnostic): `indox_line_hash` (the whole
row minus `updated_at`), `indox_base_selection_hash`, `indox_selection_hash`,
`indox_priority_signature`.

### B10. Tests and coverage

`bbox indox test`: `decide` (48 assertions on the ladder), the three sync suites, `sealed_inv` /
`sealed_ship` / `sealed_bs` / `sealed_ord` / `sealed_rcp` (per-action sealed lanes, batch 1+100),
`doc_base`, `bs`, `gdoc` (5 flows), `pipeline` (bare link → COMPLETED via the live pipeline; a
17-document batch with ground truth), `thin_only` (zero executions of the retired v1 path).
Coverage over the battery window: `scripts/n8n-node-coverage.py --since-id <first exec> --min 80`.

### B11. What changed on 2026-09-02 (this consolidation)

- Sync: the sync item (Part A) replaces the v3 unit/deliver/processor family, `mailDiscovery01`,
  the Gmail downloaders, the run-progress table and the attempt table.
- The step budget is real: `__dispatches_since_restart` (driver) feeds decide's ceiling (25);
  `ITERATION_COUNT` was never incremented by anything, so `mark_max_iterations` had been
  unreachable while three comments claimed otherwise.
- Ship01 aligned with Inv01 on the API-tools gate; its dormant invoice/order copies removed.
- Driver thinned (15 dead nodes), upload thinned (the manual test branch with a hardcoded client
  file), the router's dead action names removed, five pinned-data blobs cleared.
- No tenant id in shipped code: the two Drive searches resolve their connection from settings;
  found-file links carry the connection they were found with.
- Gates repointed at the code blueprints (G51), the reply contract (G48), the JQExV3 triggers no
  longer receive fields they drop (G39), the retired GDoc lane (G41) and the v1 processor deleted.
- Retired: `indoxV2ActionsGDoc01`, `indoxProcessDocument01`, `indoxDocUploader01`,
  `indoxDocGet01`, `gmailApiRouter01` (blueprints and live).
- Links, the two remaining causes (morning): the drive app's share link is `https://` on a real
  host (`DRIVE_PUBLIC_SCHEME` rule; a `.localhost` dev host stays http) — an http link inside the
  https console is mixed content; and an upload whose client sent no type (n8n's multipart sends
  `application/octet-stream`) gets its type from the file name, so the storage serves
  `application/pdf`, the browser renders it inline and the AI extractor accepts it (it rejected
  the untyped bytes with `unsupported_file_format`). Existing rows and objects were repaired.
- `indoxOn`, the master switch read by both lanes; the sync card's link into the table; the
  fixed-certainty proof lane (three seeded companies, asserted in the pipeline suite).
- **A parent's deadline is every child's deadline.** n8n hands `executionTimeout` down to
  sub-executions even when they are dispatched without waiting, so the scheduler's limit (was
  300) bounded every sync pass — Main's own 900 never applied. A pass whose mailbox searches ran
  50–125 s each was cancelled at 5 min and Main died on the cancelled call. The scheduler now
  carries 1800 (its tick ends in seconds; each job keeps its own limit), and Discover Gmail's
  Search soft-fails after its retries so a bad search ends one unit, never the pass. Rule: the
  ROOT of a dispatch chain must carry the LONGEST limit in the chain.
- **A row nothing can take must not wait in silence.** Eight legacy items with an empty listing
  sat in `failed` for four weeks (TAKE takes only listed rows; the files had left the source).
  TAKE now dead-letters such a row a day after discovery with an `[unlisted]` reason — the
  sync-queue rule that every non-terminal state must have a bounded exit.
- Measured on the server the same night: one IMAP connection per mailbox means N parallel
  deliveries queue on it — 25 aborted the queued fetches at 120 s and cancelled the deliveries;
  the mail workflow's fetch now waits 300 s and the gmail pipes' `batch.chunk` is 5 (the example
  registry says why). The two Drive searches skip the drive call entirely when no identity or
  no folder resolves — a "not found", never an error execution per document.

### B12. Open items (known, documented)

- `NEEDS_REVIEW` has no live writer — it is the operator's status; the feedback outcome treats it as
  a failure.
- Coverage below 80 % on the battery for `indoxV2ActionsGlobal01` (merge / garbage / restart lanes
  need a document that reaches them), `indoxV2ActionsShip01` (link search, priority sync),
  `indoxApi01` (MERGE, DELETE, GET_ALL), `processLock01` (platform test lanes). Each is a missing
  test lane, not dead code; the next suite additions are named in `NEXT.md`.
- `fixture_GLOBAL.json` `pipeline.steps` is documentation of the ladder, not executed.

---

## Part C — Operating it

### C1. The knobs (settings, per tenant)

| key | default | effect |
|---|---|---|
| `indoxOn` | true | THE master: off = no sync pass and no scheduled drain, whatever the two lane switches say; both lanes read it beside their own switch, so a lane switched off stays off when the master comes back (the design choice over a UI that flips two rows: no state is overwritten). Proven: a scheduled drain ends at "Gate Closed", Sync Main builds no unit (`sync-main_x0_units_OFF`); the full suite parks and restores it |
| `indoxSyncOn` | true | every sync pass is a no-op when false |
| `indoxDrainOn` | true | the scheduled drain (the webhook bypasses it by design) |
| `OldDocumentMonthsBack` | 6 | the age bound (§A6) |
| `indoxSourceFeedbackOn` | false | source moves / labels after completion |
| `indoxDoubleMergeOn` | false | merge doubles instead of blocking them |
| `activePrioritySync`, `indox.actions.priority_sync.local` | false / true | ERP sync, and whether it goes to the local stand-in |
| `extraction_local_enabled`, `extraction_ai_enabled` | true / fixture false | the two base legs |
| `indox.extraction.type_priority` | AI | the lead reader in the type vote |
| `DriveSearchConnection` | "" | which Drive `find_link` / `check_from_office` search: a catalog connection id, or `profile:<id>` for the local engine; empty = the first enabled drive pipe's own identity; no identity or no folder = no drive call (a "not found", never an error execution) |
| `WarehouseScansSourceFolder` | (unset) | the warehouse scans folder |
| `indox.statemachine.drain.parallel` / `driver.batch` / `driver.max` | 4 / 2000 / 2000 | the pool |
| `indox.auto.on`, `indox.auto.<job>.every` (global, `public.app_settings`) | false / 2,120,15,5,10 | the scheduler |

### C2. Deploy ritual

`bbox n8n pull indox <id>` → edit the `.workflow.ts` → `bbox n8n code validate` → `bbox n8n push
indox <id>` → execute to verify (`bbox indox test <suite>`), `bbox n8n status` drift 0, the errors
panel at zero. BFF / webapp changes need the image rebuilt (`bbox run`). Migrations:
`psql -v schema=indox_<tenant> -f scripts/ops/migrations/<file>.sql` per tenant, then
`notify pgrst, 'reload schema'`.

### C3. The server (hacohen-prod), lessons of this release

- The tenant schema was owned by `supabase_admin`; `postgres` (every hook's role) could not CREATE
  in it. `alter schema indox_<t> owner to postgres` before migrations.
- Never run a deployment script as `ssh host 'bash -s' < script` when it contains `docker exec -i`
  — the first one swallows the rest of the script. Copy the file, `nohup` it, poll its log.
- `push-app` mints its API key with a fixed label; a stale key row with that label makes the mint
  fail — delete the row, the mint persists a fresh key to `.env`.
- Sub-workflow activation order: a caller pushed before its freshly created callees fails with
  "references workflow X which is not published" — push the caller by name afterwards.
- The subworkflow policy checker resolves ownership through n8n's cache, which in queue mode lives
  in Redis (password in `.env`) and survives container restarts: after the release every
  sub-workflow call was denied ("cannot be called by this workflow") because the cache still held
  a project from the 30 August re-creation — `n8n:cache:*` flushed, denials gone.
- Storage bytes are not part of a Postgres migration: the server's storage volume held 14,704 of
  the 65,894 objects its rows described; the 7,397 the live table referenced were copied from the
  laptop volume. supabase-storage's file backend keeps an object's content-type in
  `user.supabase.*` extended attributes — a byte-only copy answers 500 `ENODATA`; copy with
  `rsync -aX` as root.
