# Master plan — consolidated state and forward plan

**2026-08-05, evening.** Supersedes `MASTER-PLAN-30-MESSAGES-2026-08-05.md`. This is the single
document: what you asked for, what is done, every defect found, the patterns behind them, and the
ordered plan to finish — including the full live-QA proof plan.

---

## Part 1 — Your last 20 messages, as objectives

| # | Ask | State |
|---|---|---|
| U01 | Every mail/drive document in the INDOX table; mail registries deposit to local drive `automations/<name>` | **partial** — pipeline now works, coverage still short |
| U02 | Sync UI that actually shows what is going on | **done** — board rebuilt, DONE column added, timeouts fixed |
| U03 | Full task list to a perfect INDOX + hacohen live | this document |
| U04 | The seven sync registries | **partial** — 6 live after the seed wipe; restore in flight; #4 blocked on Drive permission |
| U05 | #6 is `יצוא צט`, not whatsapp | **done** — folders found and wired |
| U06 | Clear last month's labels; explain 06/26; DONE column | **partial** — 06/26 explained, DONE column shipped, label clearing not run |
| U07 | INDOX table to ERP standard: paging, inline STATUS, month nav, filter/sort, card view + THUMBNAIL | **mostly done** — all fixed except thumbnails populating |
| U08/U09/U20 | Consolidated issue + task plan with full QA | this document |
| U10 | Sync page timeout; `normalizeCompanyID`; fix all issues | **done** — timeouts fixed; issue filed, not authored by me |
| U11/U16/U19 | Full autopilot until everything fixed and QA passed | ongoing |
| U12 | Deep-analyse the OOM, permanent fix | **done** — it was not an OOM (see Part 3) |
| U13 | New emails not getting tagged | **done** — folder scope, fixed and proven |
| U14/U15 | QA via private Chrome or browser42 | **done via the repo's own harness** — 62/62 views authenticated |
| U17/U19 | Monitor every subagent for stalls and drift | **done** — 3 stalls found and corrected |
| U18 | Thumbnails must trigger via `ACTION_RESTART`, like any state-machine change | **accepted** — bespoke backfill abandoned |

---

## Part 2 — Delivered and verified

Each of these was proven against the running system, not asserted from code.

**Data reach.** Drive pagination fixed — `_list()` followed no `nextPageToken` and was hiding
**43,326 of 78,651** client files. `shared_folders()` (200) and `folders()` (600) uncapped.
Mail `hasAttachment` was structurally always-false (no `BODYSTRUCTURE` fetch); fixed, and the latent
`_dec()` crash it exposed fixed with it.

**Mail.** Label engine tagging fixed — every search was silently IMAP-scoped to `INBOX`, returning
**0** results where `[Gmail]/All Mail` returns **115**. Your ERCO invoice now carries `DOC_TO_SYNC`.
Per-message triage indicator (waiting/processed/failed) shipped and verified live.

**Sync.** Claim leak reaped — 146 stuck claims across three pipes cleared, now 12 claimed with 0 past
timeout. Ledger `delivered` 79 → 146. n8n crashes 82/hour → 7/hour against 4,355 successes.

**Endpoints**, all cold-measured: `/sync/status` >90s → **0.05s**, `/sync/inventory` >90s → **3.7s**,
`/sync/items` (board shape) 46.7s → **4.1s**, `/sync/registry` 43.9s → **0.17s**.

**Table.** Pagination, sort, search, card-view degradation confirmed working. Inline STATUS editing
fixed and proven end-to-end — an `ACTION_RESTART` write was picked up by the state machine ~30s later.
Month badges fixed: March 2026 now reads **1507** against a SQL count of 1507 (was 236).

**Document page.** Both broken tabs fixed — it was calling extraction-*testing* routes whose ids can
never match a real `doc_<hash>`.

**Hygiene.** 26/26 gates passing. SOURCE_ID fixes confirmed live in n8n. Ghost workflows already
clean. 1,503 rows of raw 502 HTML purged from `REQUIRED_ACTION`.

---

## Part 3 — Every defect found, and the three patterns behind them

Forty-plus distinct defects. They are not forty unrelated bugs — they are three patterns.

### Pattern A — a bounded query treated as the whole truth (~18 instances)

The dominant defect. A `LIMIT`, `pageSize`, or an implicit server-side clamp, whose caller then
treats the partial result as complete.

The nastiest variant is invisible at the call site: **`PGRST_DB_MAX_ROWS=1000`** silently caps *every*
unpaged PostgREST select regardless of the limit the code requests. `_ledger_rows` asked for 5,000,
`sync_engine` for 20,000; both got 1,000 and never knew. The poller's `fetch_all()` reported
`row_count: 1000` against a real 6,207 — and every row past #1000 never fired `ROW_CREATED`, ever.

Instances: drive `_list`/`shared_folders`/`folders`; poller; `_get_cached_row_count`;
`_gmail_messages` (300-message window judging 38,643); `_claimed_ids`; `_ledger_rows`; `sync_engine`;
`batch_query`'s truncation test (comparing to the client's limit, not the server's clamp — the month
badge 6× undercount).

### Pattern B — the false clean (the most dangerous)

Something fails and reports success, or reports zero where it means "unknown".

- `sync_engine` capped *before* filtering by instance — a second instance's rows could squeeze this
  instance's out entirely, returning `reachable: true` with empty counts.
- **41 workflows point at a dangling `errorWorkflow`.** n8n logs it and creates **zero execution
  rows** — silent, total loss of alerting, invisible in the UI.
- `flow-qa.py --url` has no Authentik login at all, so every layout check reported 0 characters of
  content instead of failing.
- **`seed.sh` overwrote the live client `sync_registry` with demo data.** Nothing errored; the board
  just quietly showed fewer sources.
- n8n's `executeWorkflowTrigger` **silently drops fields not in its declared schema** — that is how
  `THUMBNAIL`, `THUMBNAIL_COMPLETED`, `CONNECTION`, `NEXT_RETRY_AT` and `RETRY_COUNT` vanished.
  `NEXT_RETRY_AT` is set on **0 of 6,207** rows: retry scheduling has never once worked.
- n8n labels restart-orphaned executions *"possible out-of-memory issue"* — a guess that sent me
  chasing memory. It was never an OOM.

### Pattern C — two sources of truth

Blueprint files vs the n8n database. The demo fixture vs live settings. A workflow's declared input
schema vs the actual table. The repo's `tag_rules` vs the mail app's `organizer-defaults.json`.
Every one drifts silently.

### Open defects not yet fixed

`drive api` 503 — the service account cannot upload (413 errors/24h; peaked at 177 in one window,
since fallen to ~22). `SHORT_DOC_ID` computed by three divergent formulas, 729 rows in `DOUBLE`.
Telegram alerting dead (placeholder token). Thumbnails: mechanism proven, yield only 1 in 20 under
memory pressure. `drive-gdoc-warehouse`/`drive-bs` share destination folders.

---

## Part 4 — Duplications, drifts and process failures

- **Three agents stalled** saying "I'll wait for the monitor" — which *ends* the turn rather than
  pausing it. Found by transcript-mtime inspection; all three resumed.
- **One agent classified my own dispatch messages as prompt injection** and refused the extra scope.
  From inside its context that was defensible: escalating urgency, "STOP", "supersedes", and numbers
  that shifted between messages as I re-measured. Lesson: mid-flight re-scoping reads as an attack;
  re-spawn with one self-contained brief instead.
- **One agent wrote live credentials into scratchpad files** (a JWT, a GlitchTip `secret_key` dump).
  Deleted; the scratchpad is outside the repo, so nothing could be committed.
- **My own wrong calls, corrected on the record:** the "OOM" (it was restart-orphaning); the dangling
  `errorWorkflow` as cause of the red cluster (it was a separate, larger problem — 42 workflows, not
  3); the label-engine `connection_id` hypothesis (it was folder scope); and reporting the sync page
  fixed after fixing only one of its three endpoints.
- **The host ran out of memory** (swap 6.0/6.0 GiB) and began corrupting results — a 1-in-20 thumbnail
  yield, a transient 544, WSL itself failing. Cut from six agents to three; results recovered.

---

## Part 5 — Forward plan

### Blocked on you (nothing proceeds without these)
1. **Drive write permission** — share a Shared Drive with
   `person7@example.com`, or add an OAuth Drive
   connection. Blocks registry #4 (`מסמכים כללים` does not exist and cannot be created), the shared
   destination-folder collision, and the accelerating `drive api` 503s.
2. **`gh auth login`** — GitHub Actions status is unobtainable otherwise.
3. **A real `TELEGRAM_BOT_TOKEN`** — `.env:299` is the literal placeholder; alerting is dead.
4. **Decide where the 5,555 `(בוריס)` files should route.** They are wired to no registry, so
   "move them back to their to-sync folder" has no destination to name.

### In flight
Registry restore + the seed-clobber fix and its gate · 41 dangling `errorWorkflow` references + two
new gates.

### Next, in order
1. Thumbnail yield — prove the 1-in-20 was memory pressure, then backfill 5,902 rows **via
   `ACTION_RESTART`**, in batches, per your instruction.
2. Backfill coverage — 13,759 drive + 1,310 mail documents, once the pipeline holds.
3. `REQUIRED_ACTION` writer validation (`indoxV2Driver01.json:1295` + three siblings).
4. `SHORT_DOC_ID` — one canonical identity function and a real uniqueness key.
5. Incremental sync — Gmail `historyId` + Drive `startPageToken`. The `sync_cursor` table exists with
   zero rows; every pass currently re-lists 78,651 files.
6. Remaining bounded reads and the `NEXT_RETRY_AT` retry path.

---

## Part 6 — Full-coverage live QA plan

browser42's profile is unauthenticated and Chrome is unreachable. **The repo's own harness works** —
`scripts/ui-coverage/capture.py`'s `ak_login`/`open_gated` authenticated 62/62 views, 0 rejected. All
QA runs through it, always via `console.localhost`.

**Every step asserts an effect. A rendered page is not a pass.**

*Before any run:* set `UI_MAP_SKIP_SEED=1` until the seed-clobber fix lands, or QA will destroy live
config again. Snapshot `sync_registry` first and diff it after — that check is now permanent.

**Table** — total is the real total, not the page size · page 2 returns *different row ids* ·
inline STATUS → `ACTION_RESTART` survives reload *and* the state machine acts on it · month
navigation matches a direct SQL count per month · text/enum/range filters each drop the *reported
total* (server-side) · sort flips the first row both directions · card view shows real images where
`THUMBNAIL` exists and a clean placeholder otherwise — never a broken-image glyph.

**Document page** — draw and original render real content or an honest Hebrew empty state, never raw
JSON · every action's effect confirmed in the database.

**Sync board** — loads under 40s cold · **all 8 registries present** · unmeasured counts read "not
measured", never `0/0/0/0` · the DONE column matches folder/label counts · run/pause/edit/delete each
persist across reload · re-run moves ledger rows.

**Mail** — triage dots correct for one message in each of the four states.

**End-to-end** — drop a real document into each of the 7 sources, watch each reach `COMPLETED`, and
confirm the source-side artefact moved to its done location. *This is the suite that actually answers
your standing question; everything above only proves a feature exists.*

**Regression guards** — `bbox indox test` all 8 suites (6 currently fail on the dangling reference) ·
`gates.sh` 26/26 + self-tests · every `/sync/*` endpoint under 40s cold · `sync_registry` unchanged by
the QA run itself.

---

## Definition of done

All 7 registries resolve and are manageable · every document in the 6-month window either present in
INDOX or accounted for by a stated rule · a document dropped into any source reaches `COMPLETED`
unattended · every QA suite above passes on effects · gates green and CI green · no UI endpoint over
40s cold · and no QA run mutates live configuration.
