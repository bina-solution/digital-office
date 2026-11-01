# Failure-folder backlog inventory — 2026-08-05

Read-only survey. No file was moved, no DB row was written, no workflow was touched. Live checks run
**2026-08-05, ~12:45–13:05 UTC** against the `shlomo-laptop` stack, connection
`drive_google_service_account-ea660043` (577 folders enumerated via `/api/folders`, confirmed via a
fresh, unbounded `docker exec … curl` call during this sweep — not reused from an earlier report).
Six other agents were editing code/config/DB concurrently; where my numbers disagree with the earlier
`OBJECTIVE-VERIFICATION-2026-08-05.md` sweep (12:00–12:35 UTC), the disagreement is flagged and is most
likely real drift (files being moved by other agents' fixes), not measurement error — every count below
comes from the drive engine's own `files()`/`_list()` call, which **follows `nextPageToken` to
completion internally** (verified by reading `apps/drive/adapters/google.py:187-221`) — this is not a
capped read.

**Owner's instruction**, verbatim: *"move from all failing sync folders to there original to-sync
folder and make sure our new indox app is really handling evrything currectly."*

**Headline finding that changes the shape of the whole task**: the owner's instruction cannot be
executed as literally stated for 5 of the 6 folders literally named "(בוריס)". Those folders are **not
referenced anywhere in the live `sync_registry`, anywhere in the n8n workflow DB, or anywhere in this
repo** (grepped both). There is no "original to-sync folder" for them to go back to — they are not
sync-v3 rejects at all, they are a **pre-INDOX / parallel manual triage pile**, almost certainly the
output of a person named Boris sorting scanned documents by hand, sitting entirely outside the
automated pipeline. One folder in the wider "failure-named" universe **is** a live, registry-wired
sync-v3 reject bin (`drive-gdoc-tzat`'s `failed` folder) — and it is wedged by a confirmed, live
out-of-memory crash in its processor workflow, `SyncProcGDoc0001`, not by document-content problems.

---

## 1. Every failure/reject-named folder found (41 folders, 10,150 files)

Search was keyword-based over all 577 live folders (`בוריס`, `נכשל`, `failed`/`Failed`, `reject`,
`דחוי`) — this is a name search, not a registry search, per the task's instruction to look for "the
(בוריס) ones and any others named as failure bins." Grouped by what they actually *are*, which turned
out to be the most important axis:

### Group A — the "(בוריס)" folders (owner's literal reference)

| # | Folder name | Folder ID | Files | Wired into `sync_registry`? |
|---|---|---|---|---|
| A1 | סרוקות- נכשל (בוריס) | `1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2` | **2,001** | No |
| A2 | טיפול מהמייל, נכשל (בוריס) | `1aOSsB0rbVbAOM34iqL_mOKtk6csYBGW_` | **1,447** | No |
| A3 | סרוקות- שינוי ידני (בוריס) | `1bR2EDqDUtLMSiHKQkL25DacK0ptzH_40` | **1,967** | No |
| A4 | מייל - טופל ידנית (בוריס) | `1wvSieNfGjbAHzB-PTI8NwKgUKSaS4w-W` | **124** | No |
| A5 | סרוקות שבוריס לא הצליח לתת שם | `122uDKW3HMwv3OwuShJ1foAn2LcAq9OoV` | **16** | No |
| A6 | אחרי שמות, סרוקות בוריס נכשל | `11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb` | **0** | No |
| | **Group A total** | | **5,555** | **0 of 6 wired** |

All 6 have `parents=None` in the Drive API response — top-level items in the service account's shared
view, not nested under any other sync folder. None of the 6 IDs appear anywhere in `git grep` across
the whole repo (blueprint JSON, fixtures, docs) — they are pure live-Drive artifacts unknown to the
codebase.

**Discrepancy vs. the earlier sweep** (`OBJECTIVE-VERIFICATION-2026-08-05.md`, O11, measured ~12:30
UTC): it reported 1,900 / 1,963 / 304 / 0 / 1,900 for 5 of these folders (it did not find A4). My counts,
~30 min later with a properly-paginated call: 2,001 / 1,447 / 1,967 / 0 (A6) / 16 (A5). Three folders
grew, two shrank substantially (A2: 1,963→1,447, A5: 304→16) — consistent with other agents actively
working this exact backlog while this sweep ran, not a measurement bug on either side. **Treat every
count in this report as "as of ~13:00 UTC 2026-08-05," not a permanent fact.**

### Group B — the "יצוא צט" / נחמן / טמבור universe (a *different*, mostly-unrelated naming scheme)

30 more folders matched the `נכשל`/`failed` keyword search. Investigating the live `sync_registry`
(`public.settings.key='sync_registry'`) shows **exactly one** of these is a real, currently-configured
sync-v3 destination:

| Folder name | Folder ID | Files | Registry status |
|---|---|---|---|
| **יצוא צט 2026 נכשל** | `1PYaVJ4dKdOl1iGJlVKFT0pzJ_Rs2mYNL` | **713** | **LIVE** — `drive-gdoc-tzat` pipe's `failed` destination, confirmed via `sync_registry` JSON |
| יצוא צט 12.25 - נכשל | `1OhkT-2VQ0HVT6tZnJ5y18ijdn_GWXoGK` | 41 | not wired |
| יצוא צט חודש 10 - נכשל | `1myaXou-ksvNvftjhneVlv1J0Hsa_li7J` | 31 | not wired |
| יצוא צט 09.25 נכשל | `1RnAGXbRWmBluh-p-JMhJI-GaxdCKxGqL` | 167 | not wired |
| טיפול מהמייל, נכשל 2 | `1QcsN9RtGJNujVNtTXDBIC5nfG8imQ8TP` | 179 | not wired |
| צט נכשל 08.25 | `1PBIChcX06DmAaEf9D3xEmpIv5H-c1DAK` | 64 | not wired |
| צט 07.25 נכשל | `1W72ujka8tNYzLZ476wnROFIWTHi8mfBO` | 42 | not wired |
| יצוא צט יוני נכשל- שילה 26.25 | `1LMbwgH1xgFN8XzKSzHabYFXCNpVjCj3S` | 35 | not wired |
| יצוא צט יוני יצהר נכשל- 06.25 | `1itiXbaGJKak036mqdmcUUbjgmQCoCRcE` | 13 | not wired |
| יוצא צט יוני- נכשל-קרית 06.25 | `1HizNTbHRcKMkd7m3i3fjr4NP1vmZ56W5` | 33 | not wired |
| יוצא צט מאי 05.25 - נכשל | `1HYL_E2T0xE-cDZajblZliAxxAoJcXo66` | 132 | not wired |
| צט אפריל 04.25 נכשל | `18KLUWN-Kp4ekmeZISVAdUO5DeEym1y3R` | 97 | not wired |
| יצוא צט 03.25 נכשלים | `1ZLY2QM0zOtlP6qk-nEL39Jq8AU9oNUmi` | 107 | not wired |
| יצוא צט 02.25 נכשל | `1gSh5CQazcb8keiWKEaS_pnrHZfADS32K` | 100 | not wired |
| יוצא צט 01.25 נכשל | `1iQDB1_4oUOrdb4FuiI0a4eZrapMOKS8Q` | 99 | not wired |
| נכשל- יצוא צט | `1qc-4yEgT9BAtXOxVmeRsoMT_cadoTrv0` | 109 | not wired |
| אחרי- יצוא צט פעם שניה עם בוריס עד 31.12.24 | `1OXsFTNhvvCD8_yLwjCyG_iL_-_f1xFO1` | 613 | not wired |
| יצוא צט פעם שניה עם בוריס עד 31.12.24 | `1ZOzmeLtOIAKNCf6SpfZq0JGlXo7-iw7n` | 0 | not wired |
| נכשל- צט נחמן 1 | `1TFYlUmgcr8oZK9zaA9_jV-WvJIm8G_s3` | 78 | not wired |
| נכשל- צט נחמן 2 | `159qxtXQQcjUutjxOU-EOyUiguW2ULT7j` | 191 | not wired |
| נכשל- צט נחמן 3 | `1a2DDDfGllaROHiMxcjBPqiMYWq5wVf8B` | 194 | not wired |
| נכשל- צט נחמן 4 | `1BKRcx1OFXKYWVR2lJD0MEY78lM0T5omM` | 194 | not wired |
| נכשל- צט נחמן 5 | `1YYGoYxLNjnY1-N657lrvNi9RmtrlR85z` | 83 | not wired |
| יצא צט תעודות - נכשל | `1jBcjGC3S5ZGteNe_2S6B7RcKTKk-3gez` | 635 | not wired |
| יצוא צט תעודות- נכשל 2 | `1gujNd8rnkyTGko17_3ClI7NF4rT9KFKB` | 205 | not wired |
| יצא צט תעודות- מעורבב טובים ונכשלים | `1OIyGfnmwPIhQDfrz47senT1HDKdrHpVt` | 0 | not wired |
| נכשל פעם שלישית | `1jDqqo-CDJuMhSZn-pcTBoKrkNg_ITHbl` | 15 | not wired |
| טמבור נכשל | `1njpOuMbmFYXrzwH6BYqEdGimtDXTlhTm` | 0 | not wired |
| טמבור נכשל פעם שניה | `1wXD6fXg582Nux079PBwo8dfc68hW8rCj` | 0 | not wired |
| מוקלדות שירות- נתינת שמות נכשלה | `11zMyuI3Xu7QS4vMcee5NbLYiDBI0GFEg` | 223 | not wired |
| | **Group B total (30 folders)** | | **4,393** | **1 of 30 wired** |

### Group C — dated historical Boris archives (explicitly pre-backlog)

| Folder name | Folder ID | Files |
|---|---|---|
| בוריס חשבוניות 2023 | `1OAw7WSCHbvhPk68hk1cu8U-aWk57x1qV` | 15 |
| חשבוניות בוריס 05.02.2024 | `1JfEQYAAHHspKkS10x5aENyAwe9bRMk0S` | 67 |
| בוריס חשבונית 30.1.24 | `1RzM25jSifUfrui56qsIpi0hprFNT5jjC` | 120 |
| **Group C total** | | **202** |

### Group D — the current live registry `failed` destinations (for completeness)

`sync_registry` currently defines 7 pipes with drive `pairs`. Their `failed` destination IDs:

| Pipe | `failed` folder ID | Resolves in `/api/folders`? | Files (via direct `/api/files`) |
|---|---|---|---|
| `drive-gdoc-tzat` | `1PYaVJ4dKdOl1iGJlVKFT0pzJ_Rs2mYNL` | Yes — this is Group B's "יצוא צט 2026 נכשל" | **713** (already counted in Group B) |
| `drive-gdoc` (×3 pairs), `drive-bs`, `drive-gdoc-warehouse` | `1FwcEBh6VAbnxu84Ny2g2xH_Bw5-dT7iq` (all 5 share the **same** ID) | No — same "200-OK-but-absent-from-enumeration" quirk documented in the earlier sweep's O5/O7 | **0** — empty right now |

**Grand total across everything name-matched: 41 folders, 10,150 files.** The owner's own earlier
estimate of "~6,067" corresponds closely to Group A + the historical Group C (5,555 + 202 = 5,757) or to
the now-stale O11 numbers — either way, **the true keyword-matched universe is 67% larger than the
number the task was framed around**, almost entirely because of Group B, which turns out to be a
different, mostly-orphaned naming scheme, not more Boris folders.

---

## 2. INDOX reconciliation

Reconciled the **7 folders that matter for this task** — Group A (6 folders, 5,555 files, the owner's
literal ask) plus the one live registry `failed` folder with real content (Group D's `drive-gdoc-tzat`,
713 files) — against a full, un-truncated dump of `public.incoming_documents` taken via direct `psql`
(6,207 rows, **not** through the buggy PostgREST-capped `fetch_all()` path documented in
`SYNC-ARCHITECTURE-REVIEW-2026-08-05.md §2.1** — this reconciliation is not subject to that bug).
Matching used the Drive file's own `id` against `SOURCE_ID`/the file-id embedded in `LINK`/`SOURCE_LINK`
— a **strong, unambiguous identity match**. A second, weaker pass matched by exact filename only,
reported separately because generic scanner filenames (`סריקה_YYYYMMDD (n).pdf`) collide across
unrelated documents and inflate false positives if trusted.

**Important caveat, stated rather than papered over**: `incoming_documents.created_at` only spans
2026-07-30 → 2026-08-05 (documented independently in `SYNC-ARCHITECTURE-REVIEW-2026-08-05.md`) — this
table was reseeded/reset 6 days ago. A file processed successfully by an older version of the pipeline,
before that reset, would show as "no row" here even though it may have been genuinely handled once. This
reconciliation can only prove **"does this file have a trace in the last 6 days,"** not **"was this file
ever processed, full stop."** Given most of these files' `createdTime` in Drive predates 2026-07-30 by
months, that gap is real and unresolvable from here without an older backup of the table.

| Folder | Files | Strong ID/link match | % | Name-only candidate (weak) | No match at all |
|---|---|---|---|---|---|
| A1 סרוקות- נכשל (בוריס) | 2,001 | 359 | 17.9% | 642 | 1,000 |
| A2 טיפול מהמייל, נכשל (בוריס) | 1,447 | 46 | 3.2% | 103 | 1,298 |
| A3 סרוקות- שינוי ידני (בוריס) | 1,967 | 0 | 0.0% | 0 | 1,967 |
| A4 מייל - טופל ידנית (בוריס) | 124 | 0 | 0.0% | 0 | 124 |
| A5 סרוקות שבוריס לא הצליח לתת שם | 16 | 0 | 0.0% | 0 | 16 |
| A6 אחרי שמות, סרוקות בוריס נכשל | 0 | 0 | — | 0 | 0 |
| **Group A subtotal** | **5,555** | **405** | **7.3%** | **745** | **4,405** |
| D יצוא צט 2026 נכשל (live) | 713 | 172 | 24.1% | 175 | 366 |
| **Combined (7 folders)** | **6,268** | **577** | **9.2%** | **920** | **4,771** |

**STATUS of the 577 strong-matched rows** (this is the honest "what did INDOX actually do with the
documents it can prove it saw" number):

| STATUS | Count | Meaning here |
|---|---|---|
| DOUBLE | 229 | INDOX already flagged this as a duplicate of another row |
| COMPLETED | 221 | INDOX already finished this document successfully — **it is sitting in a "failed" folder despite being done**; almost certainly a copy that was never moved out after a duplicate/second delivery completed, or the physical file/ledger split-brain the architecture review calls `delivered_not_moved` |
| MISSING_TYPE | 81 | INDOX ingested it but could not classify document type |
| MISSING_COMPANY_ID | 45 | INDOX ingested it but could not resolve a company |
| EXTRACTION_FAILED | 1 | OCR/extraction genuinely failed |

**The single largest fact in this whole reconciliation**: **90.8% of these 6,268 files (5,691) have no
reliable trace in `incoming_documents` at all.** That is not "INDOX processed them and they failed" — it
is **"INDOX has never seen these files."** This matches, and is fully explained by, the already-documented
fact that `drive-gdoc` has delivered 2 documents *total, ever* and `drive-bs` 1 (O6 of the earlier
sweep) — the Drive-side sync pipes essentially never ran against real volume, so a pile of manually
triaged Drive files sitting next to them was never going to be picked up regardless of content quality.

---

## 3. Why they failed — ranked classification

Ranking by file count, using the reconciliation above plus live pipeline state pulled this session
(`sync_ledger`, `sync_registry`, `workflow_entity`/`execution_entity`):

### (d) Never touched INDOX at all — **5,691 files (90.8% of the 6,268 reconciled)** — by far the dominant cause
Not a documented `STATUS` value because these rows don't exist. Root cause is structural, not
per-document: **5 of the 6 "(בוריס)" folders (A1, A3, A4, A5, A6 — everything except A2) and 29 of the
30 Group-B folders are not referenced by any pipe in `sync_registry`.** There is no automated process
that has ever looked inside them. This is a **pre-INDOX manual workflow** (a person, apparently named
Boris, sorting scans and mail attachments by hand into named buckets) running in parallel to, not
integrated with, the current sync-v3/indox-v2 pipeline. Sub-observation with real value: **140 of the
5,555 Group-A files carry filenames like `טמבור 62422`, `אפולו 01767`, `כלי יהודה 00280`** —
`<company name> <document number>` — meaning a human had *already* identified company and doc-id by
hand for at least these files. That is exactly the hard part `indoxV2FigureCompanyId01` exists to do by
OCR; these 140 are a small but genuinely valuable subset if any reprocessing happens (see §5).

### (b) Would fail again identically today — **713 files, `drive-gdoc-tzat`'s own live failure bin — reprocessing is pointless until X is fixed**
`SyncProcGDoc0001` (the processor workflow for `drive-gdoc-tzat`, confirmed live via `sync_registry`'s
`processor_wf` field) has **exactly one execution in its entire history, and it crashed**:
```
execution 73049 | status: crashed | 2026-08-05 12:30:11 → 12:30:14 UTC (3 seconds)
error.message: "n8n may have run out of memory while running this execution."
error.name:    NodeCrashedError / WorkflowCrashedError
node:          "Loop Over Items" (workflow-level: "Workflow did not finish, possible out-of-memory issue")
```
That crash happened **immediately after** a live `CLAIM` of 50 items (`take:50` from the registry's own
batch config) — all 50 rows in `sync_ledger` for `incoming-documents-main/drive-gdoc-tzat` share the
identical `claimed_at = 2026-08-05 12:29:35` and are still `status='claimed'`, 30+ minutes later, well
past the pipe's own 14-minute timeout, with **no automatic release** (this is the same structural gap —
no scheduled `STUCK`→`RELEASE` sweep — already documented for the unrelated `gmail-doc` pipe in
`SYNC-ARCHITECTURE-REVIEW-2026-08-05.md §2.5`, now confirmed a second time on a second pipe). **X = fix
the OOM in `SyncProcGDoc0001` (likely needs its `take`/`chunk` batch size reduced, or a memory-limit
raise, or whatever is loading all 50 documents' bytes at once in "Download File"/"Process Document") and
add the auto-release sweep.** Until both land, every 15-minute tick either does nothing (all in-flight
items are excluded from the diff by the stuck claims) or claims a fresh batch that will very likely hit
the identical crash — this task explicitly said `SyncProcGDoc0001` has never completed a single
execution, and that is now proven, with a root cause, live.

### (b, same root cause) — the 45 + 81 = 126 `MISSING_COMPANY_ID` / `MISSING_TYPE` strong-matched rows
These *did* make it through delivery once (they have real `incoming_documents` rows), so they are not
blocked by the OOM crash above — they got stuck later, in the indox-v2 state machine's own
company/type-detection step (`indoxV2FigureCompanyId01`, `indoxV2ActionsGlobal01`). Nothing found this
session shows that logic was changed today. Moving these back to `to_sync` would very likely reproduce
the same `STATUS` — **not safe to call "fixed" without separately verifying the type/company detection
path**, which is out of this survey's scope (a different subsystem than the sync-v3 bugs already
catalogued).

### (a) Failed for a reason with a name and a fix, but not provably fixed yet
None of the 6,268 reconciled files could be confidently placed here this session. The known,
already-catalogued sync-v3 defects (poller's 1,000-row cap, the 20-minute settings-cache TTL, the
`SHORT_DOC_ID`/`COMPANY_ID` truncation collisions, `_gmail_messages`'s 300-cap) are all still reported
**PRESENT** as of the most recent live check this morning (`OBJECTIVE-VERIFICATION-2026-08-05.md`, O10)
— so nothing here can be labelled "safe to reprocess, root cause resolved" yet. If/when any of those
land, the 229 `DOUBLE` and 221 `COMPLETED` rows above are the ones most likely to be affected (dedupe
correctness), not the 5,691 never-seen files.

### (c) Not documents at all
**None found.** Every sampled file across all 7 reconciled folders is a real scanned image (`image/jpeg`)
or PDF (`application/pdf`) of plausible document size (43KB–29MB); combined across Group A:
**3,450 `image/jpeg` (62.1%), 2,104 `application/pdf` (37.9%), 1 `image/png`, plus 5 zero-byte files**
(the only candidates for "not really a document," 0.09% of the total — negligible). There is no `.ini`,
`.tmp`, thumbnail, or non-document noise in this backlog. Whatever else is true about these folders,
they are a real archive of real client documents.

---

## 4. Sizing the real backlog

**Genuinely worth reprocessing today, through the existing pipeline mechanism, right now: 0.**
Stated plainly because it is the honest answer, not a hedge: every path that could receive a "move to
to_sync" is currently blocked —

- The one live, registry-wired failure bin with content (`drive-gdoc-tzat`, 713 files) is wedged by a
  reproducing OOM crash (§3, cause b) with 50 items already claimed-and-stuck. Moving more files into
  its `to_sync` folder right now adds to a queue nothing is currently draining.
- The 5,555 Group-A "(בוריס)" files have **no `to_sync` folder to move to** — no registry pipe claims
  them. "Move them back" presumes a mapping that does not exist in the live system today.

**What becomes reprocessable once the two blockers above are cleared, and the real size of each pool**:

| Pool | Files | Why it's real backlog |
|---|---|---|
| `drive-gdoc-tzat`'s existing `to_sync` (not even the failed folder) | 401 | Already waiting, blocked by the same OOM/stuck-claim issue — drains first once fixed |
| `drive-gdoc-tzat`'s `failed` folder, files with no INDOX trace | 366 (of 713; 172 already have a row, 175 are ambiguous name-only) | Real, undelivered documents once the pipe is unblocked |
| Group A files with **no** INDOX trace at all | 4,405 (of 5,555) | Only reprocessable **after** the owner defines what `to_sync` folder (existing or new `sync_registry` entry) they belong to — see §5 |
| Group A files already `COMPLETED`/`DOUBLE` | 405 | **Should not** be moved to `to_sync` — would either no-op against the `HASH`/`SOURCE_ID` unique constraints or, for the 495-live-rows-with-no-`HASH` gap already documented, risk a genuine duplicate row |
| Group B (excluding the live tzat folder) + Group C | 4,393 + 202 = 4,595 | Undetermined — no registry link found; likely a separate, older business process (monthly branch/company export batches — "נחמן", "טמבור" are company/branch names, not INDOX terminology anywhere in this repo). **Recommend a short scoping conversation with the owner before touching these at all** — this survey did not have evidence either way on what process produced them |

**Batch-size / timing estimate**, using the registries' own live batch config (`take:50` per pipe,
`schedule_min:15`, confirmed in `sync_registry` for every drive pipe today):

- Effective discovery+claim rate ≈ 50 items / 15 min = **200/hour** per pipe (the binding constraint —
  the downstream indox-v2 state machine's own throughput ceiling, "Poll Line Changes" at 40 rows/30s ≈
  4,800/hour, is far higher and not the bottleneck).
- `drive-gdoc-tzat` realistic near-term pool (401 to_sync + 366 unrecorded-failed = 767 items):
  **767 ÷ 200/hr ≈ 3.8 hours**, i.e. ~16 fifteen-minute ticks, *after* the OOM fix and a stuck-claim
  release, assuming zero further crashes.
- If the owner decides to fully re-route all 4,405 never-seen Group-A files through a new registry
  entry: **4,405 ÷ 200/hr ≈ 22 hours** of pure discovery-tick time (≈ 1 day), before accounting for
  indox-v2 handling latency per document or for however many of those land on `MISSING_COMPANY_ID`
  again given the identity-truncation bugs already documented as still live.

---

## 5. Recommended plan

**Order matters — do not start with a bulk move.**

1. **Fix `SyncProcGDoc0001`'s OOM crash first.** It is the one live, registry-wired pipe actually
   touching a folder in this backlog (`drive-gdoc-tzat`), and it has never once finished. Until this is
   fixed, "reprocessing" anything through the existing mechanism is not possible — there's no evidence
   the mechanism works at all yet for this pipe.
2. **Add (or confirm) an automatic stuck-claim release**, the same fix already recommended in
   `SYNC-ARCHITECTURE-REVIEW-2026-08-05.md §3 item 2` for the unrelated `gmail-doc` incident — this
   session found a **second, independent pipe (`drive-gdoc-tzat`) hitting the identical gap**, which
   raises the priority of that fix considerably: it is not a one-off, it is what happens to *any* pipe
   whose processor workflow dies mid-batch, and nothing recovers automatically. `RELEASE` is already
   guarded to only touch `status='claimed'` rows, so this is safe to add without risking a delivered row.
3. **Verify on the smallest real slice first**: once 1–2 land, run exactly one 15-minute tick against
   `drive-gdoc-tzat`'s existing 401-item `to_sync` folder (do **not** add the 713 failed-folder files
   yet). Confirm: (a) the workflow completes without crashing, (b) the claimed batch actually reaches
   `delivered` in `sync_ledger`, (c) the resulting `incoming_documents` rows show sane `STATUS` values
   (not 100% `MISSING_TYPE`/`MISSING_COMPANY_ID`), (d) no new `DOUBLE` explosion. Only after that single
   batch is verified clean should the 366 never-seen `failed`-folder files be moved into `to_sync`.
4. **For Group A (the actual "(בוריס)" folders) — do not move anything without an owner decision
   first.** There is no `to_sync` folder to move them to. Two real options, both requiring a decision
   this survey cannot make: (a) treat them as a new source and add a `sync_registry` entry
   (`to_sync`/`synced`/`failed` triplet) pointing at one of these folders, reusing the existing
   CLAIM/DIFF/DELIVER machinery rather than writing a bespoke migration script — consistent with using
   the pipeline's own idempotent primitives instead of a one-off heuristic; or (b) treat them as outside
   INDOX's scope entirely (a closed historical archive) and leave them alone. Either way, **first
   exclude the 405 files that already have a `COMPLETED`/`DOUBLE` row** from whatever gets moved, to
   avoid manufacturing duplicate ingestion attempts.
5. **Batch size and resumability**: reuse the registries' own `take:50`/`chunk:25` batching — it is
   already exactly-once via `sync_ledger`'s `INSERT … ON CONFLICT(source, platform_id) DO NOTHING`
   claim, so re-running a partially-completed batch is safe by construction (already-claimed or
   already-delivered items are excluded automatically). **Do not write a separate move script that
   bypasses this ledger** — a raw Drive `move()` call outside the CLAIM/RECORD flow is exactly the
   `moved_not_recorded` split-brain the architecture review already flags as a live, unrepaired gap
   (`SYNC-ARCHITECTURE-REVIEW-2026-08-05.md §2.6`). If a new registry entry is created for Group A,
   point its `to_sync` at the folder in question and let the existing 15-minute scheduler + ledger do
   the moving, claiming, and delivering — don't move files directly.
6. **Watch for the identity-truncation bugs** (`SHORT_DOC_ID`'s 5-character/`COMPANY_ID`'s 6-digit
   truncation, confirmed still live) during the first verified batch — with 140+ files in Group A that
   already carry a human-assigned company name + doc number in their filename, a truncation collision
   here would be a very visible, very avoidable regression to catch early.
7. **Re-run this survey's folder counts after step 3's verification batch**, since counts here are
   already proven to be volatile within the same hour (§1) — don't plan step 4 off numbers more than a
   few hours old.

---

## What could not be determined from this survey (stated rather than guessed)

- Whether any of the 4,405 never-seen Group-A files, or the 4,595 Group-B/C files, were **ever**
  processed by an older version of the pipeline before the `incoming_documents` table's 6-day-old reset
  — unknowable without an older backup/export of that table.
- What produced Group B (the "צט"/"נחמן"/"טמבור" monthly archives) — no reference to that naming scheme
  exists anywhere in this repo. It reads like a separate, possibly older or branch-specific export
  process, but this is inference from folder names, not confirmed.
- Whether the 175 "name-only" candidate matches in `drive-gdoc-tzat`'s failed folder are genuine
  duplicate-content matches or coincidental filename reuse — the drive listing used here does not include
  `md5Checksum` (excluded from the paginated `_list()`'s field set), so HASH-based matching, which would
  resolve this cleanly, was not possible without a slower per-file metadata call this survey did not run.
