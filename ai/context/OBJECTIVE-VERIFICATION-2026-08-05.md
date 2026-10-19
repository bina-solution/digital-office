# Objective Verification — 2026-08-05

Live verification against the running `shlomo-laptop` stack (WSL Ubuntu, `DOCKER_HOST=unix:///run/bbox-docker.sock`).
Checks were run in a rolling window from **~12:00 to ~12:35 UTC on 2026-08-05**. Other agents were editing the repo and the
live stack concurrently during this window (confirmed: `sync_registry` grew from 6 to 8 entries and `gates.sh` went from
timing out to 24/26 passing while this sweep was in progress) — timestamps are given on anything that could have moved.

No code, config, or workflow was changed to produce this report. Every number below is either a direct `psql` read, a direct
`curl` against a live service through a container, a `docker exec`/`docker inspect` fact, or a grep of the file the claim is
about (repo source **or** the shipped container bundle — labelled which).

## Summary table

| # | Objective | Verdict | One-line evidence |
|---|---|---|---|
| O1 | CI all green | **PARTIAL / UNVERIFIED (GH Actions)** | `gh` CLI not installed anywhere in this environment — GitHub Actions state genuinely unverifiable from here. `scripts/ci/gates.sh` (26 gates): **24 PASS / 2 FAIL** (`browser42-site-neutrality-lint`, `gallery-default-lint`). |
| O2 | No duplicate/ghost n8n workflows | **DONE** | 0 duplicate names across 81 workflows. `indoxSetupWF001` and `bdchh5urW9lBzudZ`: 0 rows in `workflow_entity` **and** 0 rows in `execution_entity` — both ghosts are gone, not just renamed. |
| O3 | Mail label engine live and tagging | **DONE** | `mailLabelEngine01` active, running every 15 min, 52 success / 13 crashed in trailing 24h (crashes cluster at a container restart). Live proof of output: `label:תוויות-טופל` search returns **1,137** tagged messages. |
| O4 | Mail UI per-message processed/waiting indicator | **DONE** | `gm-triage` dot wired to `PROCESSED_LABEL="תוויות-טופל"` in `apps/mail/mailview/static/app.js`, confirmed present in the **live-served** `http://mailview:8976/app.js`. |
| O5 | Seven sync registries correctly configured | **PARTIAL** | `sync_registry` now has **8** entries (grew from 6 during this sweep — see per-objective section). All 8 resolve to a real Drive/Gmail source. One config bug found: `drive-gdoc-warehouse`'s `synced` destination folder id is byte-for-byte identical to `drive-bs`'s `synced` folder — a likely copy-paste collision. |
| O6 | Every mail+drive doc reaches INDOX | **NOT DONE (data is not real coverage)** | `incoming_documents` = 6,207 rows, but `sync_ledger` (the real pipeline ledger) shows only **~79** documents were ever actually delivered by the 8 registries combined (drive-gdoc 2, drive-bs 1, gmail-doc 12, gmail-bs 2, gmail-link 3, mail-private 59). The other ~6,100 rows in `incoming_documents` came from bulk-seed/test fixtures, not the live sync pipeline — a true "% of real client mail+drive reaching INDOX" cannot be computed from this table as-is. |
| O7 | Seven registries resolve to real, reachable sources | **PARTIAL** | 6/8 resolve cleanly (real folder/label, non-zero or legitimately-empty). `drive-gdoc-warehouse.synced` collides with `drive-bs.synced` (see O5). The original `drive-gdoc`/`drive-bs` folder ids do not appear in the connection's 577-folder enumeration but DO resolve via direct file-list (200 OK, empty) — a Drive-API enumeration quirk, not inaccessibility. |
| O8 | THUMBNAIL generation is a real state-machine step | **DONE (but flaky)** | `indoxV2GenerateThumbnail01.json` in blueprint, live in n8n DB, `active=true`, has executed successfully (1 success in the 4 most recent runs; 3 of those 4 errored). `POST /documents/thumbnail` Flask endpoint exists and is fail-soft by design. |
| O9 | Sync status board: full management + timing | **PARTIAL / ONE ENDPOINT BROKEN NOW** | `/sync/registry` 1.1s, `/sync/inventory` 20.9s (both under the 40s console-proxy budget). **`/sync/items` took 149s — 3.7× over the 40s budget, live, right now.** Board source has run/edit/delete/pause/run-all wired to the API; no literal "DONE" table column found (a `done`/`in_indox` progress stat exists inline instead). |
| O10 | 6 known HIGH-severity defects | **5 of 6 CONFIRMED STILL PRESENT, live, as of 12:3x UTC** | (a) poller cap: PRESENT — `PGRST_DB_MAX_ROWS=1000` confirmed live via `docker inspect`, `poller.py` calls unpaged `fetch_all()`, table has 6,207 rows. (b) `_get_cached_row_count`: PRESENT, same root cause. (c) `_gmail_messages` 300-cap: PRESENT, `INDOX_SYNC_MAIL_LIMIT` unset live → default 300 applies. (d) 20-min settings cache: PRESENT, `ttl:1200` in `indoxSettings01`. (e) `LOCALMAIL_USER` mismatch: PRESENT and LIVE — `mailapi`=`indox`, `mailboxd`=`admin`, confirmed via `printenv` in both running containers. (f) `folders()` 600-cap: PRESENT in code, **not currently biting** (live tree is 577 folders, under the cap). |
| O11 | Backfill: how much is missing / unreprocessed | **MEASURED** | INDOX-internal backlog (non-COMPLETED, non-DOUBLE): **340** rows. Sync-ledger backlog: **110 claimed** for `gmail-doc` (108 already past the 14-min timeout, oldest stuck 1h20m+ — live incident, being worked by another agent) + 41 claimed / 31 needs_review for `mail-private`. Drive-side "(בוריס)" failure/manual folders: **~6,067 files** across 5 folders (1,900 / 1,963 / 304 / 0 / 1,900 — two folders returned an identical 1,900, suggesting the count itself may be capped by the same list-pagination pattern as O10; treat as "at least"). |
| O12 | SOURCE_ID writer fixes live in n8n, not just blueprint | **DONE** | All 5 candidate writer workflows (`SyncProcBS000001`, `SyncProcGDoc0001`, `indoxGmailBSDownloader01`, `indoxGmailDocDownloader01`, `indoxGmailLinkDownloader01`) have **identical** per-document `.json.id`-style SOURCE_ID expressions on disk and live in the n8n DB, and all 5 share the exact same `updatedAt = 2026-08-05 11:32:48.539+00` — `bbox n8n push` demonstrably ran today. |

---

## O1 — CI / gates

`gh` is not installed in WSL Ubuntu or in the Windows Git-Bash environment (`gh: command not found` in both). GitHub Actions
state (`gh run list`) is **genuinely unverifiable from this machine** — say so rather than guess.

`scripts/ci/gates.sh` (26 gates total, list confirmed via `GATES=(...)` in the script) — first run timed out at 300s after
9 gates; re-run with a 560s budget completed:

```
self-test  G31 self-test: 14/14 passed
self-test  G32 self-test: 12/12 passed
self-test  G33 self-test: 9/9 passed
self-test  G34 self-test: 12/12 passed
self-test  G35 self-test: 5/5 passed
self-test  G36 self-test: 8/8 passed
self-test  G37 self-test: 16/16 passed
PASS  ownership-lint / compose-invocation-lint / layering-lint / layer0-lint / engine-bypass-lint
PASS  state-writer-lint / legacy-ref-lint
FAIL  browser42-site-neutrality-lint   (historical incident publisher names hard-coded in browser42 source/tests)
PASS  portability-lint / registry-drift-lint / compile-lint / blueprint-dep-lint / image-pin-lint
PASS  route-claim-lint / profile-gate-lint
FAIL  gallery-default-lint             (browser42 gallery entry ships {state: enabled, by: user} instead of {enabled:false})
PASS  external-resource-lint / data-volumes-lint / fresh-clone-lint / healthcheck-lint
PASS  workflow-input-lint / tenancy-lint / capability-use-lint / memory-budget-lint
PASS  paginated-list-lint / source-id-lint

gates: 2 FAILING — browser42-site-neutrality-lint gallery-default-lint
exit code: 1
```

**24/26 PASS.** Both failures are in `browser42`, unrelated to INDOX/mail/sync.

## O2 — Duplicate / ghost n8n workflows

```sql
select name, count(*) from workflow_entity group by name having count(*)>1;
-- 0 rows
select count(*) from workflow_entity where id='indoxSetupWF001'; -- 0
select count(*) from execution_entity where "workflowId"='indoxSetupWF001'; -- 0
select count(*) from workflow_entity where id='bdchh5urW9lBzudZ'; -- 0
select count(*) from execution_entity where "workflowId"='bdchh5urW9lBzudZ'; -- 0
```

Both named suspects are completely absent — not disabled, not renamed, gone from both tables. No dangling
`execution_entity.workflowId` values with no matching `workflow_entity` row either (checked via LEFT JOIN, 0 rows).

Side observation (not a defect, flagging for hygiene): of 81 workflows, 80 are `active=true` (only `indoxV2DecideTest01` is
inactive). Many of the "active" ones are subworkflows with only `manualTrigger`/`executeWorkflowTrigger` (normal — they're
called via `executeWorkflow`, not directly), but several are named E2E/reset/test workflows shipped `active=true`
(`INDOX Reset - Drive Sync`, `INDOX Reset - Gmail Sync`, `INDOX Reset + Setup`, `INDOX Seed Fixtures`, `indox-v2 BS E2E Test`,
`indox-v2 DOC BASE E2E Test`, `mail-organizer E2E Test`, `sync-v3 Full/Kernel/Sources Test`). Worth a look, not a "ghost".

## O3 — Mail label engine

```sql
select id, name, active, "updatedAt" from workflow_entity where id='mailLabelEngine01';
-- mailLabelEngine01 | Mail Label Engine | t | 2026-08-05 11:32:48.539+00
select status, count(*) from execution_entity where "workflowId"='mailLabelEngine01' and "startedAt" > now() - interval '24 hours' group by status;
-- crashed | 13
-- success | 52
```
Trailing 10 executions as of 12:30 UTC: 1 `running`, then success/success/success/**crashed/crashed** (11:15–11:30, coincides
with an n8n worker restart)/success×5. Engine is healthy and cycling every 15 minutes.

Live production proof (not just execution logs) via `mailapi /search`:
```
POST http://mailapi:8970/search {"query":"label:תוויות-טופל","limit":1}
→ {"count":1,"has_more":true,"next_cursor":47960,"total":1137}
```
**1,137 messages carry the processed label** on the default mail connection right now.

The sync-specific labels (`SYNCED_DOC`, `SYNCED_BS`, `DOC_TO_SYNC`, `BS_TO_SYNC`, `IN_PROGRESS`, `FAILED_BS`) all returned
`total:0` on that same default connection — consistent with O6's finding that the drive/gmail sync registries have moved
very little real volume; may also reflect that the registries target a different `connection_id` than mailapi's default.

## O4 — Mail UI processed/waiting indicator

`apps/mail/mailview/static/app.js`:
```js
const PROCESSED_LABEL = "תוויות-טופל";
...
const triaged = (m.labels || []).includes(PROCESSED_LABEL);
const triageTitle = triaged ? "מנוע התוויות סיים" : "ממתין למנוע התוויות";
...
<span class="gm-triage ${triaged ? "on" : "off"}" role="img" aria-label="${triageTitle}" title="${triageTitle}"></span>
```
Confirmed **shipped**, not just in source: `curl http://mailview:8976/app.js` (live container) contains `gm-triage` and the
literal `PROCESSED_LABEL = "תוויות-טופל"`. This is a real per-row dot with a Hebrew tooltip: "Label engine finished" /
"Waiting for label engine". **DONE.**

## O5 / O7 — The sync registries (merged — same underlying evidence)

`select value from public.settings where key='sync_registry'` — **8 entries** as of 12:27 UTC (was 6 at 12:00 UTC; two more
appeared mid-sweep, presumably from a concurrent fix agent):

| Owner's item | Registry name | State | Evidence |
|---|---|---|---|
| 1. mail gdoc | `gmail-doc` | enabled | label-based Gmail pipe, `processor_wf=indoxGmailDocDownloader01` |
| 2. mail bs | `gmail-bs` | enabled | label-based, `processor_wf=indoxGmailBSDownloader01` |
| 3. mail gdoc link | `gmail-link` | enabled | label-based, `processor_wf=indoxGmailLinkDownloader01` |
| 4. drive gdoc (מסמכים כללים) | `drive-gdoc` (3 pairs) | enabled | folder ids **not** in the connection's 577-folder enumeration, but `/list` on each returns **200 OK** (real, accessible, currently empty) — a Drive API enumeration quirk (see below), not a broken source |
| 5. drive bs | `drive-bs` | enabled | same pattern as #4 — resolves via `/list` (200, empty), absent from enumeration |
| 6. drive gdoc — יצוא צט | `drive-gdoc-tzat` | enabled, **new** | all 3 folder ids (to_sync/synced/failed) found in the live 577-folder tree with matching names: `"יצוא צט 2026 לפני"`, `"יצוא צט 2026 אחרי "`, `"יצוא צט 2026 נכשל"` — clean |
| 7. drive gdoc — warehouse scans | `drive-gdoc-warehouse` | enabled, **new** | `to_sync` resolves (`"סרוקות מהמחסן 2026"`); **`synced` = `1HoBifHSHmzk4cuaw6L98lwwTfQvyIdvH`, which is IDENTICAL to `drive-bs`'s `synced` folder id** — likely copy/paste bug, needs its own destination folder |
| (extra, not in owner's 7) | `mail-private` | enabled | local IMAP attachment sync, `connection_id=mail_imap_local-local` |

Enumeration quirk, explained: `GET /api/folders` (Drive `files.list` with `mimeType='folder'`) returns 577 folders for the
bound service account, but the original `drive-gdoc`/`drive-bs` folder ids are **not** in that list. Direct `POST /list`
against those same ids returns HTTP 200 with a real (empty) file array — a deliberately-bogus id returns HTTP 503
`"File not found"` instead, so 200-with-empty is a genuine resolve, not a masked error. Conclusion: those 2 older
registries point at real, accessible folders that Drive's plain folder-listing query does not surface (a service-account/
shared-item quirk), not at broken sources.

**Confirmed gap, live right now:** `drive-gdoc-warehouse.synced` and `drive-bs.synced` share one destination folder id.
Any document the warehouse pipe marks "synced" lands in the same physical Drive folder as balance-sheet "synced" output.

Legacy `WarehouseScansSourceFolder` setting (`1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu`, folder name `"סרוקות הצליח"`) is a
**different** folder from the new `drive-gdoc-warehouse.to_sync` (`1Lmhka14VGQMVGr4VQFRpF1YDEdOUnUhM`, `"סרוקות מהמחסן 2026"`)
— worth a sanity check with the owner on which is actually correct, not necessarily a bug.

Did **not** confirm: that the 3 MAIL registries deposit into the local drive connection under
`automations/<sync-name>` specifically. Confirmed the local drive connection (`drive_local-19213e58`) IS receiving files
with today's timestamps (11:18–11:28 UTC), but did not resolve the parent folder ids to names to prove the exact
`automations/<sync-name>` convention — mark **UNVERIFIED**, would need one more `/api/folders` name-resolution call.

Stale orphan: `incoming_documents.SYNC_NAME='drive-לסינכרון-3'` has 1 row and does not match any current registry name —
leftover from an old naming scheme.

## O6 — Coverage: every doc reaches INDOX

```sql
select count(*) from public.incoming_documents; -- 6207
select "STATUS", count(*) ... ;
--  COMPLETED 5138, DOUBLE 729, MISSING_COMPANY_ID 178, MISSING_TYPE 98, MISSING_LINK 19,
--  ACTION_RESTART 16, UNKNOWN_COMPANY 10, OLD 6, MAX_ITERATIONS 4, EXTRACTION_FAILED 4,
--  NEEDS_REVIEW 3, PAUSE 2
select "SOURCE_TYPE", count(*) ...;
--  GOOGLE_DRIVE_FOLDER 3124, GMAIL 2332, INVOICE 247, BALANCE_SHEET 190, GOOGLE_DRIVE_FILE 183,
--  (blank) 83, WHATSAPP 43, MAIL_ATTACHMENT 5
select to_char(date_trunc('month',created_at),'YYYY-MM'), count(*) ...;
--  2026-07: 172,  2026-08: 6035
```

**The "last 6 months" ask cannot be answered as asked**: `created_at` on this table only spans **6 days**
(2026-07-30 → 2026-08-05). This is not a 6-month-old production table; it was seeded/reset very recently.

More importantly: `SYNC_NAME` on `incoming_documents` — the column that says "this row came from the live sync
pipeline" — is populated on only **25 of 6,207 rows**. Cross-checking against `public.sync_ledger` (the actual delivery
ledger, 324 rows total, most of which are `sv3f_*`/`sv3s_*` E2E-test namespaces, not production):

| registry | delivered (lifetime) | last delivered |
|---|---|---|
| `mail-private` | 59 (+41 stuck `claimed`, +31 `needs_review`) | 2026-08-05 12:23 |
| `gmail-doc` | 12 (+**110 stuck `claimed`**, 108 past the 14-min timeout) | 2026-08-05 11:07 |
| `gmail-link` | 3 | 2026-08-05 11:04 |
| `gmail-bs` | 2 | 2026-08-05 11:04 |
| `drive-gdoc` | **2** | 2026-07-31 |
| `drive-bs` | **1** | 2026-07-31 |

Real pipeline-attributed deliveries: **~79 documents, ever**. The other ~6,100 rows in `incoming_documents` are bulk
seed/import/test data, not organically-synced client documents. **A true "% of real mail+drive reaching INDOX" cannot be
computed from `incoming_documents` alone** — the honest number is "the live registries have delivered ~79 documents since
they started running, 2 of them (drive-gdoc, drive-bs) have not delivered anything in 5 days, and gmail-doc is currently
stuck with 108 timed-out claims." **Verdict: NOT DONE**, and the gap is structural (drive pipes barely run), not a rounding
error.

## O8 — THUMBNAIL state-machine step

```sql
select id, name, active, "updatedAt" from workflow_entity where name ilike '%thumbnail%';
-- indoxV2GenerateThumbnail01 | indox-v2 Generate Thumbnail | t | 2026-08-05 11:32:48.539+00
select id, status, "startedAt" from execution_entity where "workflowId" ilike '%Thumbnail%' order by "startedAt" desc limit 4;
-- 69412 success 11:25:33
-- 69385 error   11:24:10
-- 69316 error   11:20:40
-- 69153 error   11:16:55
```
Present on disk at `apps/indox/blueprint/n8n/indoxV2GenerateThumbnail01.json` (8,589 bytes), live in n8n DB, `active=true`.
`POST /documents/thumbnail` exists in `apps/indox/app/incoming_documents/api/__init__.py` (fail-soft by design: renders a
JPEG preview via apitools `/pdfToJpeg` or Pillow, uploads to the local drive's `automations/thumbnails` folder, always
returns 200). **It has executed successfully at least once** — but 3 of the last 4 attempts errored (75% recent failure
rate). Consistent with the DB fact that only **1 of 6,207** `incoming_documents` rows has `THUMBNAIL` populated
(`THUMBNAIL_COMPLETED='true'` on exactly 1 row too). **Verdict: present and working end-to-end, but flaky — not yet
reliable at any volume.**

## O9 — Sync status board

```
GET http://localhost:8080/incomingDocuments/sync/registry   → HTTP 200, 1.11s,  6,247 bytes
GET http://localhost:8080/incomingDocuments/sync/inventory  → HTTP 200, 20.89s, 6,672 bytes
GET http://localhost:8080/incomingDocuments/sync/items      → HTTP 200, 149.03s, 145,074 bytes
```
`/sync/items` took **149 seconds** — nearly 4× the stated 40s console-proxy timeout — measured live at 12:31 UTC, right
in the middle of the `gmail-doc` 110-stuck-claim incident (O6/O11), which is almost certainly what it's scanning slowly.
**This endpoint is functionally broken through the console right now.**

Backend has full CRUD + run wired (`apps/indox/app/incoming_documents/api/__init__.py`):
`POST /sync/registry`, `PATCH /sync/registry/<name>`, `DELETE /sync/registry/<name>`, `POST /sync/registry/<name>/run`.
Frontend (`SyncStatePage.tsx`) wires `onRun`, `onEdit`, `remove`/`toggle`, `runAll`, and a pause-refresh toggle
(`"השהה רענון"`). Did **not** find a literal "DONE" table column — there is a `done = inv.in_indox` value rendered as an
inline `X/Y (Z%)` progress line per registry, which may be what was meant, but it is not a distinct column. Mark this
sub-item **UNVERIFIED against the specific ask**.

## O10 — Six HIGH-severity defects (checked live, timestamped)

All checks run 2026-08-05 ~12:2x–12:3x UTC. Per the coordinator note, another agent may be actively fixing these —
treat as a snapshot, not a permanent verdict.

**(a) sync poller capped at 1000 — PRESENT.**
`apps/indox/app/incoming_documents/poller.py:45`: `current_rows = repo_obj.fetch_all()` — unpaged. For the Supabase
backend this becomes a PostgREST `select` with no `limit`, so the server default applies:
`docker inspect supabase-rest-shlomo-laptop` → **`PGRST_DB_MAX_ROWS=1000`** (confirmed live, not just `docker-compose.yml`'s
default). Table has 6,207 rows. The poller (and anything else calling unpaged `fetch_all()`) silently sees only the first
1,000 and calls that "everything."

**(b) `_get_cached_row_count` capped — PRESENT, same root cause.**
`api/__init__.py:2944`: `count = len(repo_obj.fetch_all())` — same unpaged call, same 1000-row ceiling. `/repos/<repo>/stats`
and the accounts dashboard report a `row_count` that is capped at 1,000 even though the real count is 6,207.

**(c) `_gmail_messages` 300-cap — PRESENT, live.**
`api/__init__.py:1675`: `"limit": int(os.getenv("INDOX_SYNC_MAIL_LIMIT", "300"))`.
`docker exec incoming-documents-shlomo-laptop printenv INDOX_SYNC_MAIL_LIMIT` → **unset**, so the 300 default is what's
actually running.

**(d) 20-minute settings cache staleness — PRESENT.**
`indoxSettings01` (both on disk and live in n8n DB) uses `"ttl": 1200` (seconds = 20 min) on its cache nodes;
`apps/indox/blueprint/fixtures/settings.json` ships the same `"1200"` value.

**(e) `LOCALMAIL_USER` delete-guard mismatch — PRESENT AND LIVE.**
`apps/mail/docker-compose.yml`: mailapi service defaults `LOCALMAIL_USER=${LOCALMAIL_USER:-indox}`; mailboxd service
defaults `LOCALMAIL_USER=${LOCALMAIL_USER:-admin}`. No `LOCALMAIL_USER` is set anywhere in the deployment `.env`, so both
defaults are live:
```
docker exec mailapi-shlomo-laptop printenv LOCALMAIL_USER    → indox
docker exec mailboxd-shlomo-laptop printenv LOCALMAIL_USER   → admin
```
mailapi actually authenticates as `indox@…`; mailboxd's delete-guard (`mailboxd.py:268`) protects `admin@…`. **The account
mailapi actually logs in as is NOT protected from deletion right now.**

**(f) `apps/drive/adapters/google.py::folders()` 600-cap — PRESENT in code, not currently biting.**
`google.py:168`: `if not page or len(out) >= 600: return out`. Live enumeration for the bound connection returns
**577 folders** — under the cap today, but the hardcoded ceiling remains and will silently start dropping folders the
moment the tree crosses 600 (client was previously described as having 443; the live tree is actually 577, closer to the
cap than assumed).

**5 of 6 confirmed present and live. None of the 6 appear fixed as of this sweep.**

## O11 — Backfill / unreprocessed backlog

INDOX-internal (rows stuck in a non-terminal state, excluding COMPLETED/DOUBLE):
`178 + 98 + 19 + 16 + 10 + 6 + 4 + 4 + 3 + 2 = 340 documents`.

Sync-ledger backlog (documents claimed at the source but not yet delivered into INDOX):
- `gmail-doc`: **110 claimed, 108 past the 14-minute timeout**, oldest stuck since 11:05 UTC (over 1h20m as of the last
  check) — this is a live, currently-unresolved incident (see O9's slow `/sync/items`, almost certainly caused by this).
- `mail-private`: 41 claimed + 31 `needs_review`.

Drive "(בוריס)" — the manual-review/failure folders the owner asked about — 5 relevant folders found by name:

| Folder (Hebrew name) | Files |
|---|---|
| `סרוקות- נכשל (בוריס)` — scans failed | 1,900 |
| `טיפול מהמייל, נכשל (בוריס)` — mail handling failed | 1,963 |
| `סרוקות שבוריס לא הצליח לתת שם` — scans Boris couldn't name | 304 |
| `אחרי שמות, סרוקות בוריס נכשל` | 0 |
| `סרוקות- שינוי ידני (בוריס)` — manual change | 1,900 |

**~6,067 files sitting in these 5 folders combined.** Two folders returned the identical count of 1,900 — a coincidence
that lines up suspiciously well with the same kind of pagination-cap pattern documented in O10; treat these as
**"at least N," not exact counts** without a second, explicitly-paged measurement. Three older dated folders
(`בוריס חשבוניות 2023`, `חשבוניות בוריס 05.02.2024`, `בוריס חשבונית 30.1.24`) look like historical archives, not active
backlog, and were not counted here.

## O12 — SOURCE_ID writer fixes: blueprint vs. live n8n

Compared the 5 workflows that write `SOURCE_ID` for the sync pipes (drive-gdoc/drive-bs processors + the 3 gmail
downloaders) — on-disk blueprint JSON vs. live `workflow_entity.nodes`:

| Workflow | On disk | Live in n8n DB | `updatedAt` |
|---|---|---|---|
| `SyncProcBS000001` | `$('Start').first().json.id` | same | 2026-08-05 11:32:48.539+00 |
| `SyncProcGDoc0001` | `$('Loop Over Items').first().json.id` | same | 2026-08-05 11:32:48.539+00 |
| `indoxGmailBSDownloader01` | `$('Gmail Message').item.json.id` | same | 2026-08-05 11:32:48.539+00 |
| `indoxGmailDocDownloader01` | `$('Loop over documents').first().json.id` | same | 2026-08-05 11:32:48.539+00 |
| `indoxGmailLinkDownloader01` | `$('Get a message').item.json.id` | same | 2026-08-05 11:32:48.539+00 |

All 5 use a per-document id (message id / loop item id), never a folder id or sender address — matches gate `G37`
(`source-id-lint`, self-test 16/16, live PASS in the `gates.sh` run above). All 5 share the **exact same** `updatedAt`
timestamp, today at 11:32:48.539 UTC — proof `bbox n8n push` ran today and the DB is not stale relative to the blueprint.
**DONE.**

---

## What's still broken, most severe first

1. **`gmail-doc` sync pipe is wedged right now**: 108 of 110 claimed messages are past their 14-minute claim timeout,
   oldest stuck 1h20m+ (O11). This is very likely also why `/sync/items` takes 149s instead of <40s (O9) — the board is
   probably scanning through the stuck claims. *(Reported as being worked by another agent concurrently.)*
2. **Two silent 1,000-row data-loss points, confirmed live**: the sync poller (`poller.py`) and the row-count cache both
   call unpaged `fetch_all()` against a PostgREST endpoint with `PGRST_DB_MAX_ROWS=1000` live, against a table that
   already has 6,207 rows — the poller is very likely missing over 5,000 rows on every scan cycle (O10a/b).
3. **`LOCALMAIL_USER` delete-guard protects the wrong account, live**: mailapi authenticates as `indox@…`; mailboxd's
   delete-guard protects `admin@…`. The account actually in use has no delete protection (O10e).
4. **The drive-side sync registries have essentially never run**: `drive-gdoc` has delivered 2 documents total, `drive-bs`
   1, both last active 2026-07-31 (5 days idle) — this, not throughput or extraction failures, is the real reason
   "coverage" of client Drive documents is nowhere near 100% (O6).
5. **`drive-gdoc-warehouse` and `drive-bs` share one destination folder id** — a live misconfiguration that will file
   warehouse-scan output into the balance-sheet synced folder (O5/O7).
6. **~6,067 files sit in the "(בוריס)" manual-review/failure Drive folders**, uncounted by INDOX and outside the sync
   ledger entirely (O11).
7. **THUMBNAIL generation is flaky**: only 1 of 6,207 `incoming_documents` rows has a thumbnail; the workflow's 3 most
   recent attempts before its one success all errored (O8), so the INDOX card view (O7) will show placeholders almost
   everywhere in production today even though the UI code fully supports thumbnails.
8. **`_gmail_messages` mail-board cap at 300** and **`folders()` cap at 600** are both still hardcoded (O10c/f); the
   600-cap isn't biting yet (577 < 600) but is close, and headroom keeps shrinking as the tree grows.
9. **20-minute settings cache TTL** (`indoxSettings01`, `ttl:1200`) means a settings change can take up to 20 minutes to
   take effect anywhere that reads through this cache (O10d).
10. Two CI gates fail (`browser42-site-neutrality-lint`, `gallery-default-lint`) — unrelated to INDOX/mail/sync, lower
    priority (O1).
11. GitHub Actions state is unverifiable from this environment (no `gh` CLI installed) — needs to be checked from a
    machine that has it, or via the GitHub web UI (O1).
12. Minor/cosmetic: no literal "DONE" column found on the sync board's registry table (a `done`/`in_indox` progress stat
    exists inline instead) (O9); "automations/<sync-name>" folder convention for the 3 mail registries not fully
    confirmed (O5); stale orphan `SYNC_NAME='drive-לסינכרון-3'` (1 row) in `incoming_documents` (O6).
