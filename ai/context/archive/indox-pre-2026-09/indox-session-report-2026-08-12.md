# INDOX — full findings report, 2026-08-12

One session, three kinds of finding: **defects in the UI**, **defects in the data**, and
**structural problems in how INDOX is built**. This is all of it, with what should be done about
each.

Context that sets the bar: INDOX is becoming the business's primary management software. That
moves the standard from "the screens render" to "a person can work in them all day without being
lied to". Most of what follows is that one class of defect — **the screen asserting something the
data does not support** — which is the only class an operator cannot catch themselves, because the
number at the bottom always agrees with whatever the screen just did.

---

## PART 1 — UI DEFECTS

All fixed and verified live unless marked otherwise.

### 1.1 Every dashboard drill-down was dead — **the worst one**
Clicking any bar navigated to the documents table **unfiltered**. The חילוץ נכשל bar said 134; the
table opened all 25,576 rows, no filter chip, nothing on screen contradicting the number just
clicked.

**Cause:** `ActiveDocsRedirect` in `App.tsx` resolved `/documents?status=…` to the active
instance's table and **dropped `location.search`** in the hop.
**Impact:** every drill-down story — status, type, source, and every cross-view flow.
**Fixed:** the redirect carries `search`. Verified: chip present, 130 rows, 3 pages, matching the bar.

### 1.2 STATUS was blank in all 25,576 rows
The grid's enum cell set `value` on a `<select>` vnode. `<select value=…>` is not a thing in
rendered HTML — the browser ignores it and keeps the **first** option selected, which was the empty
`—`. So every row displayed a blank status over correct data, **beside a dropdown that would have
written that blank on a stray click**.

**Fixed:** `selected` on the matching `<option>`; unknown values still render; cells coloured by the
shared status palette. Verified: red `חילוץ נכשל` pills matching the dashboard.

### 1.3 Four live statuses were missing from the editable enum — **~19% of the table**
`NEEDS_REVIEW` (3,131) · `IN_PROGRESS` (1,711) · `API_TOOLS_FAILED` (56) · `ACTION_REQUIRED` (7) —
**4,905 documents**. The status dropdown could not express the state 1 in 5 documents were in, and
`validate` actively **rejected** those values: an operator opening such a row and saving would be
refused permission to keep the status it already had.

**Found by the harness**, not by eye — it noticed the cell rendering raw English.
**Fixed:** added to `DOCUMENT_STATUS_VALUES`; labels now resolve for any status, listed or not.

### 1.4 "מסמכים אחרונים" printed `true` as a date — and sorted by it
477 rows carry the literal string `'true'` in `RECEIVED_DATE`. `'true'` is truthy, so the
`RECEIVED_DATE or DOC_DATE` fallback never reached the perfectly good `DOC_DATE` all 477 rows have.
Worse, the sort key was that same string — `'true'` sorts above every real date — so **the eight
"most recent documents" were the eight most corrupted rows**.

**Fixed:** sorts on `created_at`; the displayed date is the first value that actually parses.
Verified: rows minutes old.

### 1.5 Raw English enums across a Hebrew UI
`IRRELEVANT`, `API_TOOLS_FAILED`, raw statuses in grid cells, in the header filter's option list,
in the drill-down chip, and on the detail page.

**Root cause:** the same four enums were spelled out separately in `DashboardPage`,
`DocumentBrowserPage`, `DocumentDetailPage` and `api.ts` — so a status added in one place stayed
English everywhere else.
**Fixed:** one module, `src/vocab.ts`, owns labels + the single colour rule. `documentStatusKind`
deleted from `api.ts`, leaving it transport-only. That consolidation is *why* the fix was one
change instead of four.

### 1.6 The documents table had no defined order
PostgREST returned planner order — not stable between two identical requests.
**Fixed at the query layer** (`SupabaseRepo.query`), per the owner's instruction: `created_at DESC`
when no order is given, so the grid, exports and any direct API consumer all open newest-first
without asking. Falls back to unordered if a table lacks `created_at`, so a convenience default can
never take the screen down.

### 1.7 Month filtering consumed the whole viewport
~90 month pills in a page-wide block. **Rebuilt into the date column's header filter**: a scrollable
capped list with per-month counts, a search box, "ללא תאריך", and a from/to range. The basis
dropdown was deleted — the column you open *is* the answer to "by which date". The month index is
now fetched lazily on filter-open instead of on every page load.

While verifying, found the **"ללא תאריך" bucket advertised 7,657 and opened 7,631**. The index
counted empty and *unparseable* dates together; the drill-down uses `is_null`, which only reaches
the empty ones. Split into `no_date` (exact) and `bad_date` (stated, not linked — no single
operator can select them).

### 1.8 Extraction score and מס׳ מסמך (earlier in the session)
The score was computed over every row in the window, including documents nothing had processed —
so a large Drive delivery *lowered* the score with no extraction getting worse. Now scored over
documents that COMPLETED, the same set the הושלמו KPI counts.

`מס׳ מסמך` read **0%** because it measured `INVOICE_ID_COMPLETED`, an INVOICE-only legacy flag the
modern pipeline deliberately stopped writing (5 rows of 692 carried it, while 385 carried a real
document number). Now reads the resolved value. **0% → 94%.**

### 1.9 A defect I reported that was not real — correction
I reported a "blank grid inside the console iframe" as a ship-blocker. **It was an artifact of my
own reproduction**: I was setting `iframe.contentWindow.location.href` directly, which reloads the
iframe outside the console's router into a frame that isn't being painted. Navigating as a user
does — clicking the מסמכים tab — renders correctly every time. The two hardening changes I made
(a wall-clock reveal backstop, an IntersectionObserver refresh) are still sound, but the bug as
described is not reachable by a user.

---

## PART 2 — DATA DEFECTS (not UI; the pipeline writes these)

| Finding | Size | Recommended action |
|---|---|---|
| `RECEIVED_DATE = 'true'` — a boolean in a date column | **477 rows** | find the writer; all 477 have a good `DOC_DATE`, so a backfill is safe |
| `DOC_DATE` present but unparseable (`23/06/26`, 2-digit year) | **26 rows** | normalise on write |
| `SOURCE_TYPE` null | 159 rows | trace the ingestion lane that skips it |
| `SOURCE_TYPE` carrying `INVOICE` / `BALANCE_SHEET` | 4,966 rows | document *types* leaked into the source axis via those ingestion lanes; decide whether to rename the lane or the column |
| A column literally named **`EMPTY`** | — | declare, mark deprecated, do not drop without checking writers |
| A column whose **name is mojibake** (Hebrew written through the wrong encoding) | — | same |
| Future-dated `DOC_DATE` (2094, 2078, 2050…) | ~10 buckets | OCR errors; the date filter now surfaces them rather than hiding them |

None of these were touched. They are pipeline-side and yours to schedule.

---

## PART 3 — THE HARNESS

```bash
bbox indox ui-qa
```

[test_indox_ui.py](../../scripts/ui-coverage/e2e/test_indox_ui.py) — the 100 user stories in
[indox-ui-qa-stories.md](indox-ui-qa-stories.md) as executable assertions. Registered in the
existing `run_all.py` as the `indox-ui` suite.

- **73/73 passing.**
- Reaches the app directly on the traefik network — no Authentik hop, no password, CI-able.
- **Read-only**; needs no cleanup pass.
- Every check compares *the number the screen shows* against *the number the server returns for the
  thing that screen offers to open*.
- Stories that cannot be judged mechanically print **MANUAL** rather than being silently skipped.

It found §1.3 and the raw-enum chip **on its own, after being written** — which is the argument for
it existing.

**Known gap, stated rather than hidden:** it drives the app standalone, not inside the console
iframe. A green run does not currently prove the embedded path.

---

## PART 4 — STRUCTURAL FINDINGS

### 4.1 Three data layers, no single door
1. ~43 Postgres nodes in production pipeline workflows — direct SQL
2. `indoxApiSupabase01` + `indoxApiRouter01` — the intended data layer, `executeWorkflow`-only
3. The Flask service — 74 routes, 22 direct DB reads, 9 direct writes

The UI talks only to layer 3. `indoxApiRouter01` is 5 nodes whose whole job is one boolean — and it
is **already bypassed**: 20 workflows call it, 7 call the worker directly.

### 4.2 The single-writer gateway never existed
`INDOX-UNIFIED-N8N-SPEC.md` records that `indoxDataGateway01` "was invented by an agent lane,
rejected by the owner as 'not part of the existing architecture', **never executed once**, and
disarmed on 2026-08-07". Gate G42 was retired because it could never go green.

**Consequence — dead tooling:** `scripts/refactor/gen-gateway-trigger-schema.py` calls itself "the
documented way to add a column" and regenerates
`apps/indox/blueprint/n8n/indoxDataGateway01.json` — **a file that does not exist**. Two other docs
cite it as authoritative. **Delete it.**

### 4.3 The schema is healthy; a private copy of it drifted
`apps/indox/blueprint/fixtures/schema.sql` is a genuine single owner — idempotent DDL, applied
everywhere, **112 columns declared vs 108 live**. It stays.

What drifted is the **Flask service's hand-maintained column registry**: `repos.json` declares
**47 of 108**. The 61 it never learned about include `created_at`, `updated_at`, `DOC_ID`,
`THUMBNAIL`, `SYNC_NAME`, `MERGED_INTO`, `doc_date_norm`. Code that needed them reached around the
registry. **It disappears with the service** — no separate fix needed.

### 4.4 "33 workflows write directly" was misleading
Of **177 Postgres nodes** across 71 workflows, **~105 are in test/fixture workflows**
(`syncV3SourcesTest01` alone has 46). Tests asserting DB state is legitimate and stays. The real
migration surface is **~43 in production pipelines**.

### 4.5 ~1,548 lines of the Python are already dead
- `backends/gsheet.py` + `gsheet_transport.py` — **933 lines**; the Sheets era is over
- `kafka/*` — **370 lines**, while the compose file states *"There is no message broker in this platform"*
- `poller.py` — **245 lines**, *"disabled — n8n owns the pipeline"*

⚠️ Not free-standing: imported by `api/__init__.py` and `core/provisioning.py`.

### 4.6 Cross-app coupling in Gmail labelling
`indoxV2ActionsGlobal01` reads `tag_rules` — mail's table — for the label vocabulary. Per the
owner's decision this is replaced by: **INDOX settings hold plain label strings; applying is one
mail-api call with `createIfMissing`.** Mail-api currently has `labels_add` and `labels_create` as
separate ops, and `labels_create` is already idempotent — so this is a **small mail-api addition**,
not a new subsystem.

---

## PART 5 — WHAT SHOULD BE DONE, IN ORDER

### Now — cheap, independent, no risk to the migration
1. **Delete `gen-gateway-trigger-schema.py`** and stop two docs citing a phantom.
2. **Delete the ~1,548 dead lines** (gsheet, kafka, poller) and unwire their importers.
3. **Close the harness gap** — drive the console-embedded path so a green run means what it says.

### Next — the backend migration ([full plan](indox-api-single-workflow-plan.md))
4. `indoxApiSupabase01` → **`indoxApi01`**; absorb the router branch; repoint 20 callers; delete the
   router.
5. Absorb `indoxSettings01`, `SyncApi`, `syncLedgerApi01` → **~171 nodes, one door**.
6. Add the `/indox-api` webhook entry.
7. **Decouple Gmail labelling** (mail-api `createIfMissing`; INDOX settings strings).
8. Move the frontend one screen at a time; **dashboard last and alone** — it is the only genuinely
   hard port (background refresher → `scheduleTrigger`).
9. **Delete the backend codebase** when: zero `transport.*` calls, `bbox indox ui-qa` green against
   the n8n backend, and only SPA serving + `/auth/me` remain. **~13,377 lines of Python deleted;
   12,293 lines of frontend kept.**
10. **Re-arm the single-writer gate** against `indoxApi01`; migrate the ~43 production Postgres
    nodes behind it.

### Separately — data quality (Part 2)
Not blocking, but the 477 boolean-in-a-date-column rows are writing bad data *today*.

### Also worth doing
- **Display metadata at schema level** (started, then paused): column labels and enum labels served
  *with* the table so the UI can never be behind. Paused deliberately — under the n8n plan it should
  hang off `schema.sql` and the n8n read API, not off `repos.json`, which is being deleted.
- The grid still shows **raw English column headers** (`STATUS`, `TIMESTAMP`, `SOURCE_TYPE`). That
  is what the display-metadata work fixes.
