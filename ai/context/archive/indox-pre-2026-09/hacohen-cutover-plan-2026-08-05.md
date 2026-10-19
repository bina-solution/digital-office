# Hacohen live cutover — findings + plan (2026-08-05)

Written after the client's REAL Google account (Drive + Gmail) was connected for the first time.
Everything below was measured against the live account, not inferred.

## 0. The goal, restated

1. Every document the client already has (≈6 months back, and ideally the full archive) is loaded
   into the INDOX table and reaches `COMPLETED`.
2. From now on, a new document arriving in **any** source (mail attachment, Drive drop, WhatsApp bot,
   scanner) is picked up, processed, and reaches `COMPLETED` without a human touching it.
3. That is *proven*, not asserted — visible in the Console UI, per source, with nothing silently missed.

## 1. What was actually wrong (measured, this session)

### 1.1 The sync registry points at a sandbox, not production — THE headline

`settings.sync_registry`'s drive entries point at `קבצי ניהול אוטומציות / סינכרון / …`, a folder tree
owned by the **developer's** account (`person8@example.com`), created for testing.

Final measured totals (441 folders, all counted successfully, post-pagination-fix):

| Tree | Files (recursive) |
|---|---|
| `סינכרון` — **what the registry syncs today** | **5** |
| `סרוקות / ווטסאפ ראשי - אוטומציות` | **28,767** |
| `מייל ודואר ראשי - אוטומציות` | **10,211** |
| `כרטסות ודוחות גיול ראשי - אוטומציות` | **7,004** |
| ROOT `חשבוניות הכהנים` (441 folders) | **78,651** |

The registry is syncing 5 files out of 78,651 — 0.006% of the corpus.

The production tree was never connected. This alone explains why nothing meaningful synced.

### 1.2 Drive listing silently truncated at ~460 files per folder — FIXED

`apps/drive/adapters/google.py::_list()` issued a **single** Drive API request and never followed
`nextPageToken`. Any folder with more than one page silently reported only its first page — no error,
no warning. `folders()` directly above it already paginated, so this was an inconsistency, not intent.

Impact once fixed (same folders, before → after):

| Folder | Before | After |
|---|---|---|
| `סרוקות הצליח` | 460 | **17,066** |
| `סרוקות- נכשל (בוריס)` | 460 | **2,001** |
| `סרוקות- שינוי ידני (בוריס)` | 460 | **1,967** |
| `מסמכים מהבוט בווצאפ` | 460 | 584 |

For a 35k-document migration this was fatal: every large folder would have synced its first 460 and
reported the rest as absent.

**Status: fixed.** `_list` now paginates; `limit=None` means "everything". Folder listing (the sync
path) is unbounded on purpose; the trash *view* stays bounded at 1000 so the UI can't stall.

### 1.3 `hasAttachment` was structurally always false — FIXED

`apps/mail/mailapi/app.py::search()` fetched only IMAP headers, never `BODYSTRUCTURE`, so
`_msg_summary` could never detect an attachment regardless of the real message. Every mail search
reported `hasAttachment: false` for every message.

**Status: fixed** (fetch `BODYSTRUCTURE`, reuse the leaf walk `/message?meta=true` already had).
Verified live: 226 of 400 client messages now correctly report attachments.

### 1.4 indoxHealth drive probe caused a 108/day error storm — FIXED

`indoxHealth00001` probed Drive via the ambient-bound connection, which is the **service account**.
A Google SA cannot create files (no My Drive quota), so `createFromText` 503'd; `onError:
continueRegularOutput` let the failure fall through, and the subsequent delete ran with an
`undefined` fileId → `PATCH /files/` → Google's HTML 404 → wrapped as 503. Three failing
sub-executions every hour, plus GlitchTip noise.

**Status: fixed** — probe pinned to `profile_id: 'admin'` (the local drive engine, which *can*
create), matching every other `driveApi01` caller. Pushed live.

### 1.5 The "6-month backlog fully loaded / all syncs proven" claim was not accurate

Measured at the time: 6,186 of 6,250 rows (98.9%) had **no `SYNC_NAME`** and 6,245 (99.9%) had a
**null `CONNECTION`** — they were bulk-imported from the legacy spreadsheet in a single hour, not
synced. `sync_ledger` held 158 rows against 6,250 documents, which is exactly why the Console items
board showed ~5 items: the board is ledger-driven and the imported rows never passed through it.

### 1.6 The mail connection under test was the wrong mailbox

The registry's gmail entries were bound to `mail_imap_app_password-83db1e42` =
`person2@example.com`, a **demo** mailbox of generated `demo+NNNN@example.com` traffic with
**zero** attachments. The real client connection is `mail_imap_app_password-51185288`
(`person9@example.com`) — 908 messages in the 6-month window, real vendors, real attachments.

## 2. Source taxonomy — which folders are intake vs output

Determined by sampling real filenames. **The discriminator is the filename shape:**

- **raw / vendor-original / device-generated ⇒ SOURCE** (must be drive-synced)
- **`<company>-<docnum>.pdf` ⇒ automation OUTPUT** (must NOT be drive-synced — mail already ingested
  it; syncing it would double-count)
- **`<company>-unknown.pdf` / `unknown-unknown.pdf` ⇒ automation FAILURE** (needs reprocessing)

| Folder | Files | Verdict | Evidence |
|---|---|---|---|
| `שמירת מסמכים אוטומטית- מייל ודואר` | 50 | **SOURCE** (manual drop-box despite the name) | `WhatsApp Image ….jpeg`, `IMG-20260727-WA0039.jpg`, `תמונה מ-נחמן ב.`, vendor originals; uploaded by TWO people (`hachohen`, `hacohanim.pituah`) |
| `מסמכים מהבוט בווצאפ` | 584 | **SOURCE** | WhatsApp bot destination, raw + partially named |
| `סרוקות- לפני שמות` | 380 | **SOURCE** | `סריקה_20260803 (8).jpg` — raw scanner output |
| `שמירת דוחות אוטומטית- …` | 7 | **SOURCE** | human-readable names, mixed owners ⇒ manual drop |
| `אוטומציה מייל - בוצע` | 7,728 | OUTPUT (done) | every file `<company>-<docnum>.pdf` |
| `דוחות גיול מהמייל` | 6,318 | OUTPUT (done) | automation-named |
| `טיפול מהמייל, נכשל 2` | 179 | **FAILURE — reprocess** | `<company>-unknown.pdf` |
| `סרוקות- נכשל (בוריס)` | 2,001 | **FAILURE — reprocess** | |
| `אחרי שמות, סרוקות בוריס נכשל` | ? | **FAILURE — reprocess** | |
| `סרוקות הצליח` | 17,066 | OUTPUT (done) | |

> A human ("בוריס") manually handles a large share of this today — the `(בוריס)` folders. Replacing
> that is the actual business value, and also why the failure buckets are so large.

## 2b. RECONCILIATION — measured answer to "is every document in INDOX?"

Method: dumped all 78,651 drive file ids (441 folders, post-pagination-fix) and all 6,250 INDOX
identities, matched on the Google file id embedded in `LINK` (`file/d/([A-Za-z0-9_-]+)`), with a
filename fallback.

> `SOURCE_ID` is UNUSABLE as a key: only **579 distinct values across 6,250 rows**, because the
> legacy sheet import stored the containing FOLDER id for drive rows and the SENDER EMAIL ADDRESS
> for gmail rows. `LINK` (5,861 distinct ids) and `HASH` (5,751, all distinct) are the real keys.

| | count |
|---|---|
| drive files scanned | **78,651** |
| in drive AND in INDOX (by file id) | **3,519** |
| in drive, NOT in INDOX (by id) | **75,132** |
| …of those, rescued by filename match | 1,497 |
| **TRULY ABSENT from INDOX** | **73,635** |
| in INDOX but id not present in drive | 2,342 (moved/deleted, or non-drive origin) |

### The four confirmed SOURCE folders — essentially nothing has ever synced

| Source folder | files | missing from INDOX | present |
|---|---|---|---|
| `שמירת מסמכים אוטומטית- מייל ודואר` | 50 | **50 (100%)** | 0 |
| `מסמכים מהבוט בווצאפ` | 584 | **540 (92%)** | 44 |
| `סרוקות- לפני שמות` | 380 | **380 (100%)** | 0 |
| `שמירת דוחות אוטומטית` | 7 | **7 (100%)** | 0 |
| **TOTAL immediate backlog** | **1,021** | **977** | 44 |

**This is the tractable, in-scope number: 977 documents.** Everything else in the 73,635 is either
automation OUTPUT (`סרוקות הצליח` 15,273; `אוטומציה מייל - בוצע` 7,355; `דוחות גיול מהמייל` 6,117)
or historical archive (`חשבוניות מייל ודואר 2024` 3,014; `…2023` 2,553; the 2021-2022 trees).

### Failure buckets to reprocess (goal 8)

| Folder | missing from INDOX |
|---|---|
| `סרוקות- שינוי ידני (בוריס)` | 1,967 |
| `סרוקות- נכשל (בוריס)` | 1,642 |
| `טיפול מהמייל, נכשל (בוריס)` | 1,401 |
| **total manual/failed backlog** | **5,010** |

### Health of what IS in INDOX (the 3,519 matched)

`COMPLETED` 2,807 · `DOUBLE` 530 · `MISSING_COMPANY_ID` 89 · `MISSING_TYPE` 85 ·
`ACTION_RESTART` 7 · `EXTRACTION_FAILED` 1. So ~80% of ingested drive documents complete cleanly;
the largest defect class is `DOUBLE` (duplicate detection).

## 2c. MAIL-SIDE RECONCILIATION (measured 2026-08-05)

912 messages in the client's 6-month window; 540 enumerated (59% — the mailapi IMAP pool paces
connections deliberately, so this was gathered gently rather than forced). Of those, **240 carry
attachments**. Their triage state is the finding:

| state of an attachment-carrying message | count | can a sync registry pick it up? |
|---|---|---|
| `אינדוקס - מסמכים כללי - לטיפול` (DOC_TO_SYNC — the LIVE label) | **39** | yes (once rebound to the client mailbox) |
| `לטיפול-אוטומציה-שמירת-מסמכים` (LEGACY — no tag_rule produces it, no registry consumes it) | **99** | **no — orphaned** |
| **NO LABEL AT ALL — never triaged by the label engine** | **95** | **no** |
| other/system labels | remainder | mixed |

So of 240 attachment-bearing messages, only **39** are in a state the pipeline could act on. **194
would be silently missed** even after the connection rebind.

The 95 untriaged ones are real business documents — invoices from תרמוקיר, כרמל פלור דיזיין,
א.צ שיווק, orders from דור רפאל, scans from person10@example.com. Root cause is throughput, not
correctness: the label engine processes **10 messages per 15-minute run** (~40/hour), so it has never
caught up with the backlog.

**Two consequences for the plan:**
1. The label engine's batch limit must be raised (or a one-off backfill pass run) before any mail
   backfill can be complete. Rebinding the connection alone is NOT sufficient.
2. The ~99 legacy-labelled documents need a decision (Phase B5): either add
   `לטיפול-אוטומציה-שמירת-מסמכים` to `tag_rules` as a live to_sync key, or re-triage that mail.

## 3. Plan

### Phase A — connect the real sources (blocked on owner confirmation)
- A1. Confirm the SOURCE list in §2 with the client (which folders receive *new* work today).
- A2. Rewire `settings.sync_registry` drive entries off the sandbox onto the confirmed sources,
      each with its own `to_sync` / `synced` / `failed` triple. Keep `engine: v3`.
- A3. Rebind all gmail entries from the demo connection to `mail_imap_app_password-51185288`.
- A4. Re-point `dest_folder` for the gmail lanes at real client folders (they currently point into
      the sandbox tree).

### Phase B — the mail blocker: TWO DIFFERENT MAILBOXES (measured, confirmed)

> **A hypothesis I raised earlier — that label *names* were mismatched — is WRONG and is recorded
> here so nobody re-investigates it.** The names line up exactly. `DOC_TO_SYNC` and friends are
> **keys**, not label names; every consumer resolves them via `settings.gmail.labels[KEY].name`
> before touching Gmail (`SyncScanUnit0001` node `Gmail Search Req`, `syncV3Unit0001` node
> `Search Req`). `syncV3Deliver0001` even throws deliberately if a key fails to resolve.

**The real cause: the label engine and the sync registries are pointed at different mailboxes.**

- `mailLabelEngine01` sends **no** `connection_id` on its scheduled path, so mailapi resolves the
  **active** connection = `mail_imap_app_password-51185288` = the CLIENT (`person9@example.com`).
- All four gmail registry entries hardcode `connection: mail_imap_app_password-83db1e42` = the
  DEMO mailbox (`person2@example.com`).

Live counts prove it — the two halves are mirror images:

| label (key) | client `-51185288` | demo `-83db1e42` |
|---|---|---|
| `אינדוקס - מסמכים כללי - לטיפול` (DOC_TO_SYNC) | **21** | **0** |
| `לטיפול-אוטומציה-קישור-למסמך` (DOC_LINK_TO_SYNC) | **200+** | **0** |
| `אינדוקס - מסמכים כללי - טופל` (SYNCED_DOC) | 0 | **200+** |
| `אינדוקס - דוחות גיול - נכשל` (FAILED_BS) | 3 | **168** |

The engine tags the client's mail; the registries scan the demo box and find nothing. Tagged client
mail can never be picked up as things stand. The engine itself is healthy — active, 20/20 recent
executions succeeded on a 15-minute cadence, and a sampled client message correctly carries
`['אינדוקס - מסמכים כללי - לטיפול', '\Inbox', 'תוויות-טופל']`.

- B1. **Rebind all four gmail entries to `mail_imap_app_password-51185288`.** This is the single
      highest-value change in this document.
- B2. **BLOCKED WITH B1:** `gmail-doc` / `gmail-link` `dest_folder` is
      `15As7by792NlEuyvxKPMRo9hl7p7FctBK`, which lives in the *sandbox* tree. Flipping the connection
      without also fixing `dest_folder` would deposit real client documents into a dev folder. Both
      must change together.
- B3. Fix cross-wiring: `gmail-doc` and `gmail-link` both set `failed: FAILED_BS`, so a general
      document failure gets stamped `אינדוקס - דוחות גיול - נכשל` (the *balance-sheet* failure
      label). There is no `FAILED_DOC` key in `tag_rules` — adding one is a small schema decision,
      not a config tweak.
- B4. `mail-private` uses key `connection_id` where the other three use `connection`.
      `syncV3Main0001` node `Build Units` handles both for gmail (`s.connection||s.connection_id`),
      but the drive-pair `list_ctx` on the line above reads only `s.connection`. Worth normalising.
- B5. Orphan legacy labels on real client mail that nothing produces or consumes:
      `לטיפול-אוטומציה-שמירת-מסמכים` (200+), `לטיפול-אוטומציה-שמירת-דוחות-גיול` (~520),
      `אוטומציה-שמירת-מסמכים-טופל`, `אוטומציה-דוחות-גיול-נכשלה`, and others. These are the previous
      generation's vocabulary. Decide: migrate them into `tag_rules`, or treat that mail as
      historical and let the backfill (Phase C) pick it up by attachment instead of by label.
- B6. Mail UI indicator — **note a conflict before implementing.** `mailview/static/app.js:31-36`
      records that a per-row pipeline badge was removed *on purpose*: "Mail is a MAIL app. It has no
      opinion about INDOX." Also `app.js:48-54` filters every `אינדוקס - *` label out of row chips.
      Adding the requested indicator reverses a documented architectural decision — needs an explicit
      call. Insertion point if approved: `rowHtml()` at `app.js:421-453`, beside the `hasAttachment`
      slot at `app.js:444`; `m.labels` is already on the row, so no backend change is needed.

### Phase C — backfill the archive
- C1. Enumerate every SOURCE folder with the now-paginated lister; snapshot the true file inventory.
- C2. Reconcile that inventory against `incoming_documents` by `SOURCE_ID` to get the exact
      not-yet-ingested set (rather than re-syncing blindly).
- C3. Feed the gap through the sync engine in batches, watching `sync_ledger` grow to match.
- C4. Same for mail: enumerate all 908 messages in the 6-month window, list attachments per message
      (now that `hasAttachment` works), reconcile 1-by-1 against `incoming_documents`.

### Phase D — reprocess the failures (goal 8)
- D1. For each FAILURE folder in §2, move its contents back to the matching `to_sync` folder.
- D2. Re-run; confirm they now land in `COMPLETED` rather than back in failure.
- D3. Anything that fails twice is a genuine extraction defect — collect and triage separately.

### Phase E — prove steady state
- E1. Drop one new file into every SOURCE (mail attachment, Drive folder, WhatsApp, scanner path).
- E2. Watch each reach `COMPLETED` end-to-end through the Console UI.
- E3. Fix the Console items board so all documents are visible grouped by source/registry, not only
      live-pipeline items (the board reads `sync_ledger`; the bulk-imported corpus isn't in it).

## 4. Open issues not yet closed

- 47 test-fixture rows (`sv3f_*`, `sv3s_*`, `mailorg_*`) still pollute `incoming_documents`; backup
  taken (`testfixture_backup.csv`), DELETE repeatedly blocked by the local permission classifier.
- 2 of 4 GitHub Actions re-runs for `dc2ef35` not yet re-triggered (Chrome extension kept dropping).
- Mail scan reached 550 of 908 messages before the mailapi IMAP pool began throttling; it paces
  connections deliberately so as not to collide with live sync workflows. Resume gently.
- `DOC_DATE` normalization ran (63 rows: `DD/MM/YYYY` + Excel serials → ISO). NOTE: my earlier
  "dates are corrupt" alarm was **wrong** — 98.9% were already clean ISO timestamps; the apparent
  corruption was an artifact of my own `LEFT(DOC_DATE,7)` truncation in a diagnostic query.
