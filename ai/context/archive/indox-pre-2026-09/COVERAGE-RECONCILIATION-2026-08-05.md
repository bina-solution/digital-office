# Coverage Reconciliation — 2026-08-05

Independent measurement of "are we really at 100% of incoming documents." All numbers below are
either (a) **directly measured** by this report — a live `psql` query, a live `curl` against
`mailapi:8970`/`drive:8975`/the INDOX API through `incoming-documents-shlomo-laptop`, or a `docker
exec`/`docker inspect` fact, all run between **2026-08-05 15:31 UTC and 16:15 UTC**, or (b)
**doc-sourced**, meaning taken from one of today's other audit passes in `ai/context/` (mainly
`OBJECTIVE-VERIFICATION-2026-08-05.md`, `MASTER-PLAN-2026-08-05-EVENING.md`,
`FAILURE-BACKLOG-2026-08-05.md`) and explicitly labelled as such because this report could not
re-derive them inside its time/host-memory budget. Every doc-sourced number is flagged; nothing is
silently repeated as if independently confirmed. This document is read-only reporting — no code,
config, table, Drive file, or mail message was modified to produce it.

**This is a live system other agents are actively changing while this report was being written.**
Several numbers (claimed-count, delivered-count, row totals) moved between the start and end of this
measurement window; where that happened it's called out with both readings and a timestamp.

---

## Zero. The finding that reframes everything below

Before the requested five sections: the headline comparison the owner asked for —
`incoming_documents` has 6,207ish rows against an expected ~18,000 — **is not the right comparison**,
and using it would send the cutover in the wrong direction. Directly verified, three ways:

1. **`created_at` on `incoming_documents` spans 6 days, not 6 months.**
   ```sql
   select min(created_at), max(created_at) from public.incoming_documents;
   -- 2026-07-30 23:52:18 → 2026-08-05 15:24:15
   select to_char(created_at,'YYYY-MM-DD'), count(*) from public.incoming_documents group by 1 order by 1;
   -- 2026-07-30: 27   2026-07-31: 116   2026-08-03: 18   2026-08-05: 6,035
   ```
   **6,035 of 6,196 rows (97.4%) were inserted in a single bulk load today.** This table was reset
   and reseeded very recently — it is not an accumulation of six months of live client traffic.

2. **`SYNC_NAME` — the column that says "a live sync pipe wrote this row" — is populated on 29 of
   6,196 rows (0.47%).**
   ```sql
   select "SYNC_NAME", count(*) from public.incoming_documents
   where "SYNC_NAME" is not null and "SYNC_NAME" <> '' group by 1 order by 2 desc;
   -- drive-gdoc 6, gmail-doc 5, mail-private 5, sv3s_drive-gdoc 4, gmail-link 3,
   -- gmail-bs 2, sv3s_drive-bs 2, drive-לסינכרון-3 1, drive-bs 1   (= 29 total)
   ```
   The other 6,167 rows (99.5%) carry no pipe attribution at all — consistent with bulk
   seed/import/demo-fixture data, not organic ingestion. (`./bbox indox demo run <size>` is a
   documented command in this repo for exactly this purpose — CLAUDE.md, "Inject demo data
   (drive files / syncs)".)

3. **`sync_ledger` — the actual, append-only pipeline delivery ledger — shows 90 real deliveries,
   ever, across the 8 currently-configured registries**, as of 16:04 UTC today:
   ```sql
   select source, status, count(*) from public.sync_ledger group by source, status order by source;
   ```
   | registry (current, in `sync_registry`) | delivered (lifetime) |
   |---|---|
   | drive-gdoc | 2 |
   | drive-bs | 1 |
   | gmail-bs | 2 |
   | gmail-doc | 17 |
   | gmail-link | 3 |
   | mail-private | 65 |
   | drive-gdoc-tzat | 0 |
   | drive-gdoc-warehouse | 0 |
   | **total, 8 live registries** | **90** |

   (`sync_ledger` also has 15 more delivered rows under names that are **not** in the current
   8-registry list — `drive-invoices` (4), `drive-לסינכרון-3` (5), and the `sv3s_*` E2E-test
   namespace (8) — stale/test artefacts, excluded above as not attributable to a real, currently
   configured source.)

**Conclusion**: the honest "how much of the real 6-month mail+Drive universe has organically reached
INDOX" answer is **on the order of 90 documents**, not 6,207 and not "a third of 18,000." The 5,117
`COMPLETED` rows in the table today are overwhelmingly synthetic fixture data used to build/QA the
new sync-v3 engine, not evidence of client coverage. Sections 1–4 below still answer the owner's
question in full — the *size of the true universe*, the *size of the true backlog*, and the *sized
plan to close it* — but section 2's "actual" column is `sync_ledger`-based (90), with the seeded
`incoming_documents` STATUS breakdown given alongside for transparency, not as the coverage number.

---

## 1. The denominator — what should be in INDOX for the last 6 months

Window used throughout: **2026-02-05 00:00 UTC → 2026-08-05 16:00 UTC** (6 calendar months back from
today; August is a 5-day partial month).

### 1a. Mail attachments — fully paginated, not sampled

Method: `POST http://mailapi:8970/search` against connection `mail_imap_app_password-51185288`,
folder `[Gmail]/All Mail` (the account-wide folder — **not** `INBOX`, which the app's own default is
and which the Label Engine bug used to hard-code; confirmed via the mail UI's `apps/mail/app.js` that
pagination is `before_uid`-based, newest-page-first, walking backward in time). 17 pages of 500,
every page's date range logged, until the oldest message on a page fell before the window start:

```
page 1: min=2026-07-30 → max=2026-08-16   (500 msgs)
...
page 17: min=2026-01-26 → max=2026-02-19  (500 msgs, 498 in-window) → boundary hit, stopped
```
**Raw messages scanned in window: 8,498.** Of those, **8 are synthetic verification traffic**
(`from`/`to` on `demo.indox` — a live sync-v3 self-test sender/recipient, e.g. `sv3s-gd@demo.indox`)
and are excluded. **Real messages in the 6-month window: 8,490** — a complete count, not a sample
(total mailbox size at time of read: 83,478, close to the 83,442 in prior measurements — growing
normally).

Every message carries `hasAttachment: true/false` (this flag reads Gmail's `BODYSTRUCTURE`, per
`apps/mail/mailapi/app.py`; a historical always-false bug here is code-confirmed fixed). **6,083 of
8,490 real messages (71.7%) have at least one attachment.**

Per-message attachment **count** requires a second call per message
(`GET /message/<uid>?meta=true&folder=...`, response `.attachments[]`). Full enumeration of all 6,083
attachment-bearing messages was not completed in the time budget (would be ~6,000 sequential calls at
~1–2s each, well over an hour against a memory-constrained host running other agents' work
concurrently). Instead: **a stratified 1-in-5 sample, every 5th message by uid within each month,
target n=1,218; final completed n=918 (75% of target) when this measurement was closed out** — not
the same messages as any prior measurement, drawn fresh from the full, exhaustively-paginated list
above, not a blind sample of an unspecified population:

| month sampled | msgs sampled | attachments | avg/msg |
|---|---:|---:|---:|
| 2026-03 | 25 | 48 | 1.92 |
| 2026-04 | 134 | 253 | 1.89 |
| 2026-05 | 211 | 434 | 2.06 |
| 2026-06 | 245 | 507 | 2.07 |
| 2026-07 | 240 | 493 | 2.05 |
| 2026-08 | 63 | 127 | 2.02 |
| **total (n=918)** | | **1,862** | **2.028** |

February 2026 was not reached before the sample was closed out (the population's uid ordering meant
sampling proceeded newest-month-first; Feb was next in line). Ratio is stable within a 1.89–2.07 band
across 6 consecutive months with no trend — **2.03 attachments per attachment-bearing message** used
below, applied uniformly including to the unsampled February bucket since every sampled month sits
within ±5% of that figure.

**Mail attachment documents, 6-month window ≈ 6,083 × 2.03 ≈ 12,348.**

| month | real messages | hasAttachment=true | est. attachment-documents (×2.03) |
|---|---:|---:|---:|
| 2026-02 | 876 | 595 | ~1,208 |
| 2026-03 | 1,495 | 1,015 | ~2,060 |
| 2026-04 | 949 | 667 | ~1,354 |
| 2026-05 | 1,450 | 1,060 | ~2,152 |
| 2026-06 | 1,621 | 1,235 | ~2,507 |
| 2026-07 | 1,671 | 1,196 | ~2,428 |
| 2026-08 (5 days) | 428 | 315 | ~640 |
| **total** | **8,490** | **6,083** | **~12,348** |

Message-count and hasAttachment-count columns are **exact, exhaustive** (full pagination). Only the
final "documents" column is a ratio-based extrapolation, clearly marked.

One design note that matters for the denominator: all three Gmail-side registries
(`gmail-doc`, `gmail-bs`, `gmail-link`, and `mail-private`) are configured with
`search_extra`/`v3_query: "has:attachment newer_than:6m"` (confirmed live via
`GET /incomingDocuments/sync/registry`) — **the system itself only treats attachment-bearing
messages as candidate documents.** The 2,407 real messages with no attachment are correctly out of
scope for "incoming documents," not an undercount.

### 1b. Drive files created in the window, by source vs. destination folder

**Directly confirmed live**: `GET http://drive:8975/api/folders` (the connection
`drive_google_service_account-ea660043`) returns **577 folders**, matching every prior measurement
exactly.

**Not independently re-verified in this pass**: the **78,651-file / 19,683-created-in-window /
5,924-INDOX-matched (30.1%)** figures, and the month-by-month decay pattern, are **doc-sourced**
(`OBJECTIVE-VERIFICATION-2026-08-05.md`, `MASTER-PLAN-2026-08-05-EVENING.md`, and earlier passes they
cite). A full independent recrawl means listing all 577 folders via `api/files?folder=<id>` and
filtering `created` — not attempted here because (a) the host is memory-constrained and other agents
are running concurrent work against the same containers, (b) 570+ of the 577 folders are **not**
referenced by any of the 8 sync registries at all (only ~15 folder IDs appear in `sync_registry`
pairs — see 1c), so a full crawl would mostly be counting undifferentiated legacy folders whose
role (source vs. archive vs. someone's personal Drive item) is unknown without per-folder
inspection — exactly the ambiguity `FAILURE-BACKLOG-2026-08-05.md` spent its own pass resolving for
the failure-bin folders. **What independent re-verification would take**: ~577 paginated
`api/files` calls (a few seconds each, several minutes total, feasible but not attempted here to
avoid adding load during another agent's live fix work), then bucket by `created` month and by
folder role using the registry's own `pairs[].{from,to,synced,failed}` map (below) to exclude
destination/failed folders from the source count.

**Source vs. destination, from the live registry** (`GET /incomingDocuments/sync/registry`, directly
fetched — this is authoritative, not doc-sourced):

| registry | source (`from`/`to_sync`) folder(s) | destination (`synced`) | failed bin |
|---|---|---|---|
| drive-gdoc | `1tK4m...`, `1LKjn...`, `1Whm...` (3 "GeneralDocs" folders) | `1-2Ov...`, `1ev3j...`, `1s3Eh...` | `1FwcE...` (shared) |
| drive-bs | `1M9h_...` ("DocumentsToProcess") | `1HoBi...` | `1FwcE...` (shared) |
| drive-gdoc-tzat | `1DYzD...` | `1xthr...` | `1PYaV...` |
| drive-gdoc-warehouse | `1Lmhk...` ("סרוקות מהמחסן 2026") | `1HoBi...` **← identical to drive-bs's `synced`, a live config collision** | `1FwcE...` (shared) |

**Directly confirmed live**: the two oldest, largest source folders — `drive-gdoc`'s
`1tK4m0VyC2spEV8ByPYrPt6DKdI53tXp1` and `drive-bs`'s `1M9h_cpKmz5O7dNC2KzbUeEyvczLsWylM` — return
**`{"files":[],"folders":[]}`, HTTP 200, right now**, via direct `api/files?folder=<id>`. This
matches `OBJECTIVE-VERIFICATION`'s finding exactly: a genuine 200-with-empty resolve (not a 503/404
masked error), and these two folder IDs are **absent** from the live 577-folder enumeration despite
resolving directly — a service-account/shared-item enumeration quirk, not a broken source. Whether
"empty" means genuinely fully drained or an enumeration/permission artifact **could not be settled
further in this pass** — flagged `UNVERIFIED`, and it is the single most consequential unknown in
this section, since these two folders are meant to be the two biggest sources.

**Excluding destinations from the source count**: `1FwcEBh6VAbnxu84Ny2g2xH_Bw5-dT7iq` (the shared
failed bin), `1-2Ov...`/`1ev3j...`/`1s3Eh...`/`1HoBi...`/`1xthr...` (synced destinations) must **not**
be counted as sources — a document that lands there is a *copy of* a source document, not a second
one. This report did not independently recount their contents (see above), so cannot state the exact
document-level effect of applying this exclusion to the doc-sourced 19,683/78,651 figures — noted as
`UNVERIFIED`, would require the same 577-folder crawl.

### 1c. The failure-folder population

**Doc-sourced from `FAILURE-BACKLOG-2026-08-05.md`** — that pass is unusually rigorous (per-folder ID
citation, a 3-way match against INDOX by strong ID/link, name-only weak match, and no-match), and its
headline numbers match the brief's pre-stated figures exactly, which this report treats as a good
cross-validation sign even though it could not re-run the reconciliation itself in this time budget:

| group | folders | files | wired to a registry? |
|---|---:|---:|---|
| A — literally named "(בוריס)" | 6 | **5,555** | **0 of 6** |
| B — "יצוא צט" / "נחמן" / "טמבור" naming scheme | 30 | ~4,393 | 1 of 30 (a `failed` bin only) |
| C — dated historical archives (2023–2024) | 3 | 202 | 0 of 3 |
| D — live registry `failed` destinations (for completeness) | — | 713 (drive-gdoc-tzat) | yes (this is the working one) |

Reconciling Group A + the one live Group-D bin (7 folders, 6,268 files) against `incoming_documents`
by strong ID/link match: **577 files (9.2%) matched an existing INDOX row; 5,691 (90.8%) have never
been seen by INDOX at all** — no STATUS value, because no row exists.

**Directly confirmed live** (this report, not doc-sourced): `drive-gdoc-tzat`'s **`to_sync`** folder
(the one *live, wired* registry with real content) currently shows `at_source: 401, remaining: 401`
via `GET /incomingDocuments/sync/inventory` — an exact match to `FAILURE-BACKLOG`'s independently
reported 401, a strong cross-check that both measurements are reading the same live state correctly.

### De-duplicated total — the single most important number

**The mail↔Drive overlap was directly measured, not estimated: it is effectively zero right now.**
The two Drive folders that exist specifically to receive a Drive-side copy of a synced Gmail
attachment — `GmailDownloadedDocumentsFolder` (`15As7by792NlEuyvxKPMRo9hl7p7FctBK`, the `dest_folder`
for `gmail-doc`/`gmail-link`/`mail-private` per the live registry) and
`GmailDownloadedBalanceDocsFolder` (`1UMGaSMmUtR4J0wOdS29y6kw9d6LwHoER`, `gmail-bs`'s `dest_folder`)
— were queried directly:
```
GET /api/files?folder=15As7by792NlEuyvxKPMRo9hl7p7FctBK  → {"files":[],"folders":[]}
GET /api/files?folder=1UMGaSMmUtR4J0wOdS29y6kw9d6LwHoER   → {"files":[],"folders":[]}
```
**Both are empty.** Even the 90 lifetime-delivered documents from section 0 either didn't get a Drive
copy written to their configured destination, or something removed it — either way, **as measured
right now, the mail-origin and Drive-origin document pools do not overlap in practice.** (`
mail-private`'s `dest_folder` is `"mail-private"`, not a Drive-style ID — it targets a *separate*
local IMAP-mailbox drive connection, `drive_local-...`, not the 78,651-file Google Drive connection
at all, which independently explains why its far larger delivered count, 65, still shows 0 in the
Google Drive destination folders above.)

**De-duplicated 6-month total** = mail attachment-documents + Drive-window files − overlap:
```
~12,348 (mail, own exhaustive count + verified-stable sampled ratio, n=918)
+ 19,683 (Drive, doc-sourced — NOT independently re-crawled, see 1b)
−     ~0 (overlap, directly measured at both dedicated destination folders)
────────
~32,031  (of which only the mail half, ~12,348, is a number this report generated itself end-to-end;
          the Drive half is carried forward from other agents' earlier measurement, clearly flagged)
```
This is **higher**, not lower, than the owner's 3,000/month × 6 = 18,000 rule of thumb — consistent
with the owner's own framing ("a message with 3 PDFs is 3 documents") once attachment-count, not
message-count, is used as the unit, and once Drive's separate file population is added rather than
assumed to be the same documents.

---

## 2. The numerator and the gap

**`incoming_documents` STATUS/SOURCE_TYPE breakdown, as measured 2026-08-05 16:04 UTC (6,196 rows —
this table is actively being written to by other agents; it was 6,207 at 12:0x UTC per
`OBJECTIVE-VERIFICATION`, moved a few rows since):**

| STATUS | count |
|---|---:|
| COMPLETED | 5,117 |
| DOUBLE | 723 |
| MISSING_COMPANY_ID | 190 |
| MISSING_TYPE | 97 |
| MISSING_LINK | 20 |
| ACTION_RESTART | 16 |
| UNKNOWN_COMPANY | 10 |
| MAX_ITERATIONS | 9 |
| OLD | 6 |
| NEEDS_REVIEW | 3 |
| EXTRACTION_FAILED | 3 |
| PAUSE | 2 |

| SOURCE_TYPE | count |
|---|---:|
| GOOGLE_DRIVE_FOLDER | 3,128 |
| GMAIL | 2,332 |
| INVOICE | 247 |
| BALANCE_SHEET | 186 |
| GOOGLE_DRIVE_FILE | 183 |
| (blank) | 72 |
| WHATSAPP | 43 |
| MAIL_ATTACHMENT | 5 |

**As established in section 0, this breakdown is overwhelmingly seed/demo data (97.4% inserted today
in one bulk load, 99.5% with no `SYNC_NAME` pipe attribution) and must not be read as "coverage."**
The month-by-month view below makes this explicit by using `TIMESTAMP` (the row's own business
timestamp, independent of `created_at`) — even this shows a suspicious concentration (55% of all
rows dated June 2026 by `TIMESTAMP`), consistent with a demo fixture built around a June reference
date rather than organic arrival:

| month (by `TIMESTAMP`) | INDOX rows | dominant STATUS |
|---|---:|---|
| 2026-02 | 22 | COMPLETED 13, MISSING_TYPE 5, DOUBLE 4 |
| 2026-03 | 60 | DOUBLE 31, COMPLETED 27 |
| 2026-04 | 79 | COMPLETED 50, DOUBLE 27 |
| 2026-05 | 243 | COMPLETED 171, DOUBLE 48 |
| 2026-06 | 3,409 | COMPLETED 3,263, DOUBLE 111 |
| 2026-07 | 127 | COMPLETED 123 |
| 2026-08 | 241 | COMPLETED 165, MISSING_COMPANY_ID 39 |

**The real numerator — `sync_ledger` delivered, by registry, lifetime** (repeated from section 0 for
side-by-side comparison against section 1's expected totals):

| registry | delivered (real, lifetime) | last delivered |
|---|---:|---|
| gmail-doc | 17 (+12 stuck `claimed` right now) | today |
| gmail-bs | 2 | today |
| gmail-link | 3 | today |
| mail-private | 65 (+19 `claimed`, +53 `needs_review`) | today |
| drive-gdoc | 2 | 2026-07-31 (5 days idle) |
| drive-bs | 1 | 2026-07-31 (5 days idle) |
| drive-gdoc-tzat | 0 | never |
| drive-gdoc-warehouse | 0 | never |
| **total** | **90** | |

### Expected vs. actual, by month

| month | expected (mail attachment-docs, own count) | expected (Drive-created, doc-sourced) | actual (real, `sync_ledger`) | coverage |
|---|---:|---:|---:|---:|
| 2026-02 | ~1,208 | doc-sourced only, not re-verified this month-by-month | ~0 attributable | ~0% |
| 2026-03 | ~2,060 | " | ~0 | ~0% |
| 2026-04 | ~1,354 | " | ~0 | ~0% |
| 2026-05 | ~2,152 | " | ~0 | ~0% |
| 2026-06 | ~2,507 | 3,110 (doc-sourced) vs 526 INDOX (16.9%, doc-sourced) | ~0 pipeline-attributed | ~0% |
| 2026-07 | ~2,428 | " | ~0 | ~0% |
| 2026-08 (5d) | ~640 | " | ~90 (all-time, mostly today) | n/a (all delivery activity is concentrated in the last few hours of the last few days) |

**Every registry's real, ledger-confirmed delivery activity is from the last few days** (`drive-gdoc`
and `drive-bs` last moved a document on **2026-07-31**; every other registry's most recent delivery
is **today**, 2026-08-05, coinciding exactly with the ongoing fix work by other agents visible in
this same session). There is effectively no real historical monthly coverage to report for
February–July — the pipes were not meaningfully running during that period. **Coverage, honestly
stated: ~90 of an expected ~30,000+ documents in the window, i.e. under 0.3%.**

---

## 3. Gap decomposition, with a count for each

| # | Cause | Count / evidence | Verification |
|---|---|---|---|
| 1 | **Drive pipes barely ran** | `drive-gdoc`: 2 delivered lifetime, `drive-bs`: 1, both idle since 2026-07-31 | **Directly measured**, `sync_ledger` |
| 2 | **`SyncProcGDoc0001` crashes on execution** | **2 executions in its entire history, both crashed, 0 successes** — exec `73049` (12:30:11→12:30:14 UTC, 3s) and exec `78371` (13:34:30→13:34:30, <1s) | **Directly measured** (this report), `n8n` `execution_entity`, more current than `FAILURE-BACKLOG`'s "exactly one execution" (written before the second crash). Error text: "n8n may have run out of memory" — `ERROR-RCA-2026-08-05.md` (doc-sourced) separately debunks this as n8n's generic crash-recovery string, not real OOM evidence (`OOMKilled:false` confirmed on every restart it caught) |
| 3 | **Claims leaked with no reaper** | **146 stuck claims across 3 pipes, reaped today** (doc-sourced, `MASTER-PLAN-2026-08-05-EVENING.md`: "ledger delivered 79 → 146... claim leak reaped"). **Live right now** (this report): `gmail-doc` 12 claimed, `mail-private` 19 claimed + 53 `needs_review` — the leak is not fully closed, it recurs | Reaper **exists** and is code-verified (5-min schedule, `syncLedgerApi01.json`) but is new/same-day; its own comment documents it shipped with its own bug (used `$input.first()`, released only 1 of 3 sources on first live fire) |
| 4 | **Label engine searched INBOX only** | Doc-sourced: "0 vs 115 results in 48h" before the fix. **Code-verified fixed**: `mailLabelEngine01.json` explicitly sets `folder:'[Gmail]/All Mail'` at 3 call sites. Live proof (doc-sourced, `OBJECTIVE-VERIFICATION`): 1,137 messages now carry the processed label | Fixed; `/search`'s own default remains `INBOX` for any *other*, unfixed caller — not biting the sync registries, which all pass `folder`/label explicitly |
| 5 | **"(בוריס)" files wired to no registry** | **5,555 files, 0 of 6 folders wired** (doc-sourced, `FAILURE-BACKLOG-2026-08-05.md`, high-confidence per-folder reconciliation) | Doc-sourced, cross-checked against the brief's pre-existing figure (exact match) |
| 6 | **Drive `_list()` pagination bug hid 43,326 of 78,651 files** | Doc-sourced historical figure. **Code-verified as fixed today**: `apps/drive/adapters/google.py` `_list()` (lines 187-207) correctly follows `nextPageToken` to completion now; the code comment documents the historical page-cap-of-600 defect explicitly | Fixed in code; the 43,326/78,651 historical undercount itself is doc-sourced, not independently re-derived (would need the pre-fix code, which is gone) |
| 7 | **`DOUBLE` status: real duplicates or `SHORT_DOC_ID` collisions?** | 723 `DOUBLE` rows. **Directly measured, three sub-findings**: (a) collision sinks confirmed exactly — `'00000'`→12 rows (spanning 3 different `COMPANY_ID`s — a cross-company collision), `'61520'`→24 rows (spanning `COMPANY_ID` 512600297/515186625/512004235 — also cross-company), `'22026'`→10 rows (4 different `COMPANY_ID`s). (b) Tracing `DOUBLE_LINE_CONTEXT.matchedId` against the table's own `ID`/`SOURCE_ID` columns: of 720 `DOUBLE` rows with a parseable match context, **353 (49%) have a live sibling row** (a real, present duplicate pair) and **365 (51%) point to a `matchedId` that no longer exists anywhere in the current table** — its partner was deleted, replaced, or belongs to pre-reset data no longer present, so those flags cannot be independently re-confirmed against today's table as-is. (c) Code-verified: 3 divergent `SHORT_DOC_ID` formulas exist across `indoxV2Actions*01.json` / `indoxGmailDocDownloader01.json` / `indoxGmailLinkDownloader01.json` (strip-then-slice-then-pad vs. pad-then-slice vs. neither) | (a),(b) directly measured this report; (c) code-verified by source read |
| 8 | **Config collision: `drive-gdoc-warehouse` and `drive-bs` share one `synced` destination folder** | `1HoBifHSHmzk4cuaw6L98lwwTfQvyIdvH` appears as both registries' `synced` id, confirmed in the live `GET /sync/registry` response fetched by this report | Directly measured |
| 9 | **Cached `done` counts collide** *(new finding, not in any prior doc)* | `GET /sync/inventory` reports `gmail-doc` and `gmail-link` **both** at `done: 15832` — identical to 5 digits, on two registries with different queries. Consistent with a shared/degraded cache key, not independently confirmed as a real coincidence | Directly measured, **flagged, not fully diagnosed** — would need the cache-key code read to confirm |
| 10 | **6 of the 8 live registries are erroring right now** *(new finding)* | `GET /sync/inventory` → `"sources_with_errors": 6` of 8, `totals.sources_measured: 5` of 8. Two concrete errors seen: `drive-bs` and `drive-gdoc-tzat` both `"folders: ReadTimeout: timed out"` at read time | Directly measured, this report, 2026-08-05 ~15:57 UTC |
| 11 | **`PGRST_DB_MAX_ROWS=1000` truncates every unpaged read against a 6,196-row table** | Doc-sourced (`MASTER-PLAN-2026-08-05-EVENING.md` Pattern A) — the poller, the row-count cache, `_ledger_rows`, and `sync_engine` all call unpaged reads that PostgREST silently caps at 1,000 regardless of the limit requested in code | Doc-sourced; the live `PGRST_DB_MAX_ROWS=1000` setting and the 6,196-row table size are both independently consistent with this report's own findings |
| 12 | **`NEXT_RETRY_AT` retry path has never fired** *(directly re-confirmed)* | `select count(*) from incoming_documents where "NEXT_RETRY_AT" is not null` → **0 of 6,196** | Directly measured |
| 13 | **Drive service-account cannot upload/create** | Code-verified: `apps/drive/adapters/google_sa.py` — `create_folder`/`upload`/`op_upload`/`op_create_from_text` unconditionally raise `GoogleAuthError` for this connection type (no Shared Drive granted). Doc-sourced: 413/503 errors on this path, peaked 177/24h, now ~22 | Code-verified block; error-rate trend doc-sourced |

**Every gap-contributing document should land in exactly one of the buckets above.** What this report
could **not** attribute with a count: the exact number of the ~5,691 never-seen failure-bin files or
the Drive-window files that fall into *more than one* of the above causes simultaneously (e.g. a file
sitting in an unwired "(בוריס)" folder AND affected by the old pagination bug, historically) —
flagged `UNVERIFIED`, would need per-file provenance that predates this session.

---

## 4. The reprocessing plan, sized

**Confirmed live** (`GET /sync/registry`): **7 of 8 registries run `take:50`** on a 15-minute
schedule (`drive-gdoc`, `drive-bs`, `gmail-link`, `gmail-bs`, `gmail-doc`, `drive-gdoc-tzat`,
`drive-gdoc-warehouse` all show `"batch":{"chunk":25,"schedule_min":15,"take":50,"timeout_min":14}`
verbatim). `mail-private` is the exception: `"batch":{"page_size":50,"schedule_min":15,"take":25}`.
This **confirms** the brief's ≈200/hour, ≈4,800/day-per-pipe figure for 7 of the 8 pipes (50 × 4
runs/hour = 200/hr = 4,800/day); `mail-private` runs at 100/hr = 2,400/day.

**At the currently-measured backlog** (`GET /sync/inventory`, `at_source` = live count still waiting
at the source, right now):

| registry | at_source (live, right now) | take/hr | naive wall-clock to drain (single pipe, no other constraint) |
|---|---:|---:|---|
| gmail-doc | 1,037 | 200 | ~5.2 hours |
| gmail-link | 374 | 200 | ~1.9 hours |
| gmail-bs | 27 | 200 | ~8 min |
| drive-gdoc-tzat | 401 | 200 | ~2.0 hours |
| drive-gdoc / drive-bs / drive-gdoc-warehouse | 0 (reported — but 2 of these 3 are erroring on read right now, see gap #10; treat as unknown, not confirmed-zero) | 200 each | unknown until the `ReadTimeout` is fixed |
| **mail-private + Group-A/B failure-bin backlog (once wired)** | 5,555 (Group A) + ~4,393 (Group B) + 366 (drive-gdoc-tzat's own failed-bin never-seen files) | 100–200 | **~2–4 days once a registry exists for them (blocked, see §5)** |

All 8 pipes running concurrently and error-free (**not** the current state — 6 of 8 are erroring
right now, per gap #10) gives a theoretical combined ceiling of ~4,800×7 + 2,400 ≈ **36,000
documents/day**. In practice, three things throttle this well below the ceiling:

- **Host memory.** `free -m` showed 188 MiB free / 449 MiB swap free at the start of this session;
  `MASTER-PLAN-2026-08-05-EVENING.md` records the host actually running out of memory earlier today
  and corrupting results, forcing a cutback from six agents to three. `SyncProcGDoc0001`'s crash
  (gap #2) carries an OOM error string, even though `docker inspect` did not confirm real OOM on the
  restarts that were checked. **Recommendation: reprocess one registry at a time, `take` no higher
  than the current 50, and watch `free -m` between batches** — the "small batches, no parallel heavy
  jobs" instruction this report itself operated under is the right operating mode for the fix work
  too.
- **API quotas.** Not independently measured this pass (would need Google API console access this
  report doesn't have) — flagged `UNVERIFIED`.
- **The Drive service-account upload block** (gap #13) — any reprocessing step that needs to *write* a
  Drive copy (not just move/rename an existing file) will fail outright until either a Shared Drive
  is granted or an OAuth Drive connection replaces the service account. This blocks turning the
  "(בוריס)" and Group-B piles into real registries cleanly (their natural `to_sync` destination would
  need a folder the service account can write to).

**Realistic wall-clock estimate, once the 6-of-8 live errors (#10) and the two Drive-source
enumeration questions (§1b) are resolved**: draining the currently-known, currently-wired backlog
(gmail-doc 1,037 + gmail-link 374 + gmail-bs 27 + drive-gdoc-tzat 401 + drive-gdoc-tzat's own 366
never-seen failed-bin files ≈ **2,200 documents**) at a conservative single-pipe-at-a-time rate of
~150/hr blended ≈ **~15 hours of pipe-uptime**, spread over **2–3 calendar days** given the 15-minute
schedule, host-memory-driven batching, and the fact 6 of 8 pipes need their live errors fixed first
before that throughput is even reachable. The much larger "(בוריס)" + Group-B pile (~9,948 files) is
**not** included in that estimate — it is blocked on an owner decision (§5), not a throughput
question.

---

## 5. What cannot be reprocessed, and why

| Pool | Files | Why it's blocked | Owner action needed |
|---|---:|---|---|
| Group A — "(בוריס)" folders | 5,555 | No `to_sync` registry mapping exists at all; nothing decides where these belong | Decide: new registry entry, or fold into an existing source, or leave as permanent manual triage |
| Group B — "יצוא צט"/"נחמן"/"טמבור" folders | ~4,393 | Same — 29 of 30 unwired | Same decision, folder-by-folder |
| Group C — dated historical archives (2023–2024) | 202 | Outside the 6-month window by definition; look like intentional cold storage, not backlog | Confirm they're archival, not action needed |
| `drive-gdoc`/`drive-bs` source folders | unknown (currently read as empty) | **UNVERIFIED**: genuinely empty, or a service-account enumeration quirk hiding real content — this report could not settle it | Needs a second measurement method (e.g. the owning human account listing the same folder) to rule out the enumeration quirk |
| Any reprocessing step requiring a Drive **upload** (not move/rename) | unbounded | Service-account has no Shared Drive — `create_folder`/`upload` unconditionally error (code-verified) | Grant `person7@example.com` a Shared Drive, or add an OAuth Drive connection |
| `drive-gdoc-warehouse`'s synced output | unbounded going forward | Destination folder collides with `drive-bs` (config bug, confirmed live) — reprocessing now would misfile warehouse scans into the balance-sheet bin | Needs its own destination folder id before any volume is pushed through it |
| Documents whose duplicate partner no longer exists (the 365 orphaned `DOUBLE` matches, gap #7b) | 365 | Nothing to reconcile against in the current table — cannot confirm or deny the duplicate flag from data alone | Needs either the pre-reset table or a manual spot-check |
| `NEXT_RETRY_AT`-gated retries | 0 rows ever, but conceptually all `EXTRACTION_FAILED`/error-state docs | The retry-scheduling write path has never fired (n8n silently drops fields not in a workflow's declared schema) — any document waiting on a scheduled retry is not actually going to retry | Needs the schema/field-passing fix, not a reprocessing run |
| Not truly a "document" | not separately counted | Some `SOURCE_TYPE=GOOGLE_DRIVE_FILE`/`INVOICE` rows in the seed data are shortcuts (`mimeType: application/vnd.google-apps.shortcut`, seen directly in this report's own `api/files` sample) rather than files — should be excluded from any 100% target, count not separately broken out this pass | None — definitional, flag for the extraction step |

**Honest summary of what "100%" excludes today**: everything in Group A/B (~9,948 files) until a
registry mapping exists; anything needing a Drive upload until the service-account permission is
fixed; the two main historical source folders' true content until the enumeration quirk is resolved
one way or the other; and the 365 orphaned duplicate flags, which are unresolvable from the data as
it stands.

---

## Standards note

Every count in this document is either a number this report generated directly against the live
system (labelled, with the query/endpoint shown) or explicitly marked doc-sourced with the source
file named. Nothing here restates a bounded/capped query as a total: the mail-window count (8,490) is
a complete, exhaustively-paginated scan with the stopping condition shown, not a `LIMIT`-truncated
read; the 577-folder Drive count is a direct, complete `api/folders` read; the attachment-count ratio
is an explicit stratified sample (n and method stated) applied to an exhaustive base population, not
presented as exact. Where this report could not independently verify a doc-sourced number (the
78,651/19,683/5,924 Drive figures, the "(בוריס)" per-folder counts, the 43,326-file historical
pagination-bug undercount), it says so and states what verification would require, per instruction,
rather than repeating the number with false confidence.

---

## Addendum — final attachment-ratio sample

Closed out at **n=965** of the 1,218 originally targeted (79%; the sampler ran single-threaded
against the live `mailapi` container for ~20 minutes and was still slowly progressing when closed
out — extending it further was judged not to change the conclusion, see stability below). 3 lookups
errored (uid not found / timeout) and were skipped, not counted as zero.

| month sampled | msgs | attachments | avg/msg |
|---|---:|---:|---:|
| 2026-03 | 72 | 150 | 2.08 |
| 2026-04 | 134 | 253 | 1.89 |
| 2026-05 | 211 | 434 | 2.06 |
| 2026-06 | 245 | 507 | 2.07 |
| 2026-07 | 240 | 493 | 2.05 |
| 2026-08 | 63 | 127 | 2.02 |
| **total (n=965)** | | **1,964** | **2.035** |

- **Final ratio: 2.035 attachments per attachment-bearing message** (the body of the report above uses
  2.03, computed at n=918 mid-sample — the two-decimal difference from the final 2.035 changes the
  ~12,348 mail-document estimate by under 0.3%, well inside the margin already implied by "estimate,
  not exact count"; not worth re-threading through every table above for a ~35-document shift). Stable
  in a **1.89–2.08** band across all 6 consecutive months sampled (March–August 2026), no trend —
  strong grounds to apply it uniformly to the one unsampled month (February).
- Distribution is right-skewed: of 965 messages, 541 (56%) had exactly 1 attachment, a further 321
  (33%) had 2–3, and a long thin tail ran up to 27 attachments on a single message (2 messages hit
  27, one hit 19, one hit 15) — consistent with the owner's own framing ("a message with 3 PDFs is 3
  documents") rather than a flat "1 email = 1 document" assumption, and the reason the mail-side true
  document count (~12,348) is meaningfully larger than the raw attachment-bearing message count
  (6,083).
- This figure, and the ~12,348 mail-side total derived from it throughout this report, should be
  read as a **high-confidence estimate**, not an exact count — the only way to get an exact count is
  the full 6,083-message enumeration this report did not have time to complete (79% of a 1-in-5
  sample = ~15.8% of the true population, directly measured, not extrapolated from a smaller pilot).
  Extending the same script (`mail_attach_sample.py`, sample-every-N=1) to the full population is the
  direct next step if an exact figure is required.
