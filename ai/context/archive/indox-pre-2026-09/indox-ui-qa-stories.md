# INDOX UI — 100 user stories, and the QA that proves them

**Why this exists:** INDOX is about to become the business's primary management software. That
raises the bar from "the screens render" to "a person can work in them all day without being lied
to, stalled, or surprised". These 100 stories are the acceptance surface for that claim.

**Scope order (the owner's, 2026-08-12):** לוח בקרה and מסמכים first, to ship-ready. Only then
סנכרון, הגדרות, בדיקות, חילוץ מסמכים.

**How a story is judged.** Three failure classes, in priority order:

1. **LIE** — the screen asserts something the data does not support (a count that opens a different
   number of rows, a chip claiming a filter the server never applied, a label naming the wrong
   column). Highest severity: it is the one defect class the operator cannot detect themselves.
2. **BREAK** — a crash, an unhandled error, a dead control, a state you cannot get out of.
3. **FRICTION** — it works but costs the operator attention it shouldn't: layout that eats the
   viewport, a control that needs a second click to do the obvious thing, an unlabelled affordance,
   an inconsistency with the console's visual language.

Status column: `PASS` / `FAIL` / `BLOCKED` / `—` (not yet run). No story is marked PASS from a
screenshot alone — each one names the observable that was checked.

---

## A. לוח בקרה — the dashboard (1–30)

| # | As an operator I want to… | Expected (the observable) | Status |
|---|---|---|---|
| 1 | see the board within a moment of opening INDOX | first paint < 2s; no "טוען לוח בקרה…" left on screen with a healthy API | — |
| 2 | read the six KPIs and trust they describe one row set | סה״כ / הושלמו / דורשים טיפול / נכשלו / חברות / ציון חילוץ all recomputed under the SAME window | — |
| 3 | see הושלמו's share of the total | sub-line shows `N% מהמסמכים`, and N == round(done/total*100) | — |
| 4 | know how fresh the numbers are | "עודכן HH:MM:SS" advances on the 15s poll | — |
| 5 | see that the board is live | the חי beat animates; polling pauses when the tab is hidden | — |
| 6 | switch to a 15-minute window | `15 דק׳` applies; every KPI and bar changes together | — |
| 7 | switch to 30 דק׳ / שעה / היום / החודש / הכל | each applies server-side; `since_applied` differs per window | — |
| 8 | not pay for a window I re-click | clicking the ACTIVE window is a no-op (no refetch) | — |
| 9 | keep my window across a reload | the window persists (localStorage) | — |
| 10 | choose which date column the window cuts on | the basis control lists every offered column | — |
| 11 | be told why a basis is unavailable | unavailable options render disabled WITH the measured reason in the tooltip | — |
| 12 | not ask a 15-minute question of a business date | on a day-granularity basis the sub-day buttons are disabled with the reason | — |
| 13 | see the numbers move when I change basis | נוצר vs עודכן give materially different counts | — |
| 14 | know how many rows a basis cannot place | "N ללא ערך בעמודה זו" appears when non-zero and a window is applied | — |
| 15 | read the pipeline health bar | the stacked bar's segments are proportional to the four groups | — |
| 16 | read the status legend | הושלמו / דורשים טיפול / נכשלו / אחר match the KPI strip exactly | — |
| 17 | see every status present in the window | one bar per status, sorted by count desc | — |
| 18 | see Hebrew status names, not enums | every status in STATUS_LABEL renders Hebrew; unmapped renders raw + tooltip | — |
| 19 | click a status bar and land on those documents | opens `/documents?status=X`; table shows that status, count agrees | — |
| 20 | trust the extraction score's population | ציון חילוץ is scored over documents that COMPLETED; `scored` == הושלמו KPI | — |
| 21 | see how many rows the score ignores | "N שטרם הושלמו — לא נספרים" states the excluded count | — |
| 22 | see per-field extraction quality | חברה / תאריך / מס׳ מסמך / סכום / חילוץ AI each render a % bar | — |
| 23 | know which column a field bar measures | each bar's tooltip names the column(s) | — |
| 24 | see a real number for מס׳ מסמך | the doc-number bar reads the resolved VALUE, not the dead legacy flag | — |
| 25 | read the document-type distribution | one bar per TYPE, Hebrew labels, sorted desc | — |
| 26 | click a type and land on those documents | opens `/documents?type=X`, correctly filtered | — |
| 27 | read where documents came from | לפי מקור shows the full SOURCE_TYPE distribution, bars sum to total | — |
| 28 | click a source and land on those documents | opens `/documents?source=X`; the blank bucket opens its rows too | — |
| 29 | see the top companies | up to 6, sorted desc; empty state when none | — |
| 30 | see the most recent documents | 8 rows: name, company, type, status pill, date | — |

## B. מסמכים — the documents table (31–70)

| # | As an operator I want to… | Expected (the observable) | Status |
|---|---|---|---|
| 31 | open the table and see rows quickly | first page renders; row count shown in the toolbar | — |
| 32 | know what I'm looking at | backend, table, primary key, row count all visible in the strip | — |
| 33 | filter a column from its own header | the filter icon opens a popover anchored to that column | — |
| 34 | pick a month from the date column's header | month list with per-month counts, scrollable, capped height | — |
| 35 | search within 116 months | the month search box narrows the list | — |
| 36 | have a month apply immediately | one click applies and closes; no second confirm | — |
| 37 | open exactly the rows a month advertises | bucket count == filtered row count, for every month | — |
| 38 | reach the rows with no date | "ללא תאריך" applies is_null and returns exactly its count | — |
| 39 | be told about unreadable dates | the count of present-but-unparseable dates is stated, not linked | — |
| 40 | not pay for the month index unless I use it | the aggregate is fetched on filter-open, not on page load | — |
| 41 | filter by a date RANGE instead | מ/עד inputs work; the truncation to one bound is not silent | — |
| 42 | filter by status | header filter on STATUS offers the known enum | — |
| 43 | filter by free text on a column | contains / equals / ריק / לא ריק all apply server-side | — |
| 44 | combine filters across columns | two column filters AND together in ONE request | — |
| 45 | combine a drill-down with a column filter | URL chip + header filter both apply | — |
| 46 | see every active filter | each active filter shows a chip | — |
| 47 | clear one filter | its chip's ✕ removes only that filter | — |
| 48 | clear all filters | one control returns to the unfiltered table | — |
| 49 | search free-text across the table | the search box hits the server-side ILIKE columns | — |
| 50 | sort by a column | sort is server-side and survives paging | — |
| 51 | page through results | pager works; page resets when the query changes | — |
| 52 | change page size | the grid re-queries with the new size | — |
| 53 | choose which columns I see | the column picker shows 47 columns, 13 visible by default | — |
| 54 | have my column choice remembered | hidden/visible persists per table id | — |
| 55 | open a document | clicking the ID cell opens the document detail | — |
| 56 | switch to card view | the כרטיסים toggle renders cards with thumbnails | — |
| 57 | see a thumbnail, or a graceful placeholder | broken/missing images degrade to 📄, never a broken icon | — |
| 58 | edit a cell inline | an edit commits via PATCH and the row refreshes | — |
| 59 | be stopped from writing an invalid status | validate rejects a value outside the enum, with a toast | — |
| 60 | select rows | selection checkboxes work and survive scroll | — |
| 61 | export what I'm looking at | ייצוא produces the filtered set, not the whole table | — |
| 62 | add or upsert a row | the drawer opens, validates and reports created/updated/noop | — |
| 63 | see a status as a coloured pill | STATUS renders a pill whose colour matches the dashboard's grouping | — |
| 64 | read Hebrew everywhere | no raw English enum leaks into a user-facing cell label | — |
| 65 | keep the table usable at 25k rows | paging never silently truncates (the PostgREST 1000-row cap is handled) | — |
| 66 | not be lied to about the row count | the toolbar count agrees with the active filter | — |
| 67 | land here from the dashboard and know why | the chip says which observation I came from | — |
| 68 | go back to the dashboard and back again | navigation preserves nothing stale; no ghost filters | — |
| 69 | resize / use a narrow window | the table scrolls horizontally; the page never scrolls sideways | — |
| 70 | never see the page break on a slow request | loading state is visible; a failed request shows an error, not a blank grid | — |

## C. Real-life cross-view flows (71–85)

| # | Flow | Expected | Status |
|---|---|---|---|
| 71 | Dashboard → click נכשלו bar → see exactly those documents | count on the bar == rows in the table | — |
| 72 | Dashboard → click חילוץ נכשל → fix one → return → count dropped | the board reflects the change within one poll | — |
| 73 | Dashboard → 15 דק׳ → click a status → table shows that status | (the time window is NOT carried into the table — verify this is stated, not implied) | — |
| 74 | Find every unprocessed invoice from one company this month | type=INVOICE + company filter + month filter, in one table state | — |
| 75 | Find documents with no company but a valid amount | multi-filter: COMPANY_NAME ריק + DOC_TOTAL_AMOUNT לא ריק | — |
| 76 | Find everything that arrived from WhatsApp | source drill-down from the dashboard | — |
| 77 | Find the balance sheets that failed extraction | type + status combined | — |
| 78 | Audit one month end-to-end | month filter → export → counts agree with the dashboard's month | — |
| 79 | Chase a specific document by its number | free-text search finds it by SHORT_DOC_ID | — |
| 80 | Chase a document by name fragment | search matches NAME | — |
| 81 | Triage: what needs a human right now | דורשים טיפול KPI → the union of those statuses in the table | — |
| 82 | Spot a bad extraction and open the file | open a row, view the document, compare to extracted fields | — |
| 83 | Switch INDOX instance and see everything re-scope | the instance chip changes table, dashboard and counts together | — |
| 84 | Work for 10 minutes without a reload | no memory growth, no stuck spinner, no stale numbers | — |
| 85 | Use the browser's back button throughout | back never lands on a broken or half-filtered state | — |

## D. Stability, design and readiness (86–100)

| # | Requirement | Expected | Status |
|---|---|---|---|
| 86 | Zero console errors in normal use | no uncaught exceptions across the two main views | — |
| 87 | Zero failed network requests in normal use | no 4xx/5xx on the happy path | — |
| 88 | No layout shift after load | KPI strip and cards do not jump as data arrives | — |
| 89 | RTL is correct everywhere | no mirrored-icon or reversed-number bugs; numbers stay LTR | — |
| 90 | One visual language with the console | fonts, radii, shadows, spacing, accent colours match | — |
| 91 | Status colour semantics are global | the same status is the same colour on dashboard and table | — |
| 92 | Every control has an accessible name | buttons/inputs are labelled (aria or text) | — |
| 93 | Keyboard: tab order is sane | the window control is a radiogroup; popovers close on Escape | — |
| 94 | Focus is never lost | closing a popover returns focus somewhere sensible | — |
| 95 | Empty states are designed, not blank | every list has a real empty message | — |
| 96 | Error states are actionable | errors say what failed and what to do | — |
| 97 | Nothing takes the whole viewport without earning it | no control block dominates the screen (the month-pill regression) | — |
| 98 | Works at 1280×800 and at 1920×1080 | both render without horizontal page scroll | — |
| 99 | Works in a narrow/split window | the responsive grid collapses cleanly | — |
| 100 | A new user can find the main task unaided | the primary action on each screen is visually obvious | — |

---

## Findings log

Recorded as they are confirmed, worst first. Every entry names the observable, not an impression.

**Run 1 — 2026-08-12, Chrome via the console shell (`console.localhost/#/m/incoming`), authenticated
as authentik Default Admin, live table ~25,600 rows.**

| ID | Severity | Story | Finding | State |
|---|---|---|---|---|
| D3 | **LIE** | 19, 26, 28, 67, 71–77 | **Every dashboard drill-down was dead.** `ActiveDocsRedirect` resolved `/documents?status=…` to `/repos/<active>/documents` and dropped `location.search`. Clicking a bar that said 134 opened the unfiltered table — 25,576 rows, no chip. Every drill-down story depended on this. | **FIXED + verified** (chip, 130 rows, 3 pages) |
| D4 | **LIE** | 63, 64, 91 | **STATUS was blank in all 25,576 rows.** The enum cell set `value` on the `<select>` vnode; `<select value=…>` does nothing in rendered HTML, so the empty `—` option stayed selected over correct data — beside a dropdown that would have written that blank on a stray click. | **FIXED + verified** (red `חילוץ נכשל` pill) |
| D1 | **LIE** | 30 | **מסמכים אחרונים showed `true` as the date, and was sorted by it.** 477 rows carry the string `'true'` in `RECEIVED_DATE`; `'true'` is truthy so the `or DOC_DATE` fallback never fired, and the lexical sort ranked those rows top — "the 8 most recent documents" were the 8 most corrupted ones. | **FIXED + verified** (real rows, minutes old) |
| D2 | FRICTION | 18, 64 | Raw English enums in a Hebrew UI: `IRRELEVANT` (type card), `API_TOOLS_FAILED` (status bar), raw statuses in grid cells, in the header filter's option list, and on the detail page. | **FIXED + verified** (`כשל בעיבוד`) |
| D5 | FRICTION | 30 | מסמכים אחרונים mixes date formats — `18/06/2026` on some rows, raw ISO `2026-08-12T10:38:07.659Z` on others (the `TIMESTAMP` fallback is printed unformatted). | OPEN |
| D6 | **BREAK** | 31, 70, 84 | **Grid renders empty inside the CONSOLE IFRAME.** Root cause found: the first-paint orchestration keeps the grid `visibility:hidden` until a `requestAnimationFrame` loop settles, and rAF does not run in an unpainted frame — so a grid mounted in the iframe stayed hidden with correct data behind it. Two fixes landed (a wall-clock reveal backstop; an IntersectionObserver `refresh()` when it becomes visible) and the grid is now VISIBLE — **but its viewport is still empty in the iframe**, so the row virtualisation is still measuring against a zero-height mount. **Standalone is fine; the console-embedded path is not.** | **PARTLY FIXED — still open** |
| D8 | **LIE** | 63, 64 | **Four live statuses were missing from `DOCUMENT_STATUS_VALUES`** — NEEDS_REVIEW (3,131), IN_PROGRESS (1,711), API_TOOLS_FAILED (56), ACTION_REQUIRED (7): 4,905 documents, ~19% of the table. The status dropdown could not express the state 1 in 5 documents were in, and `validate` actively REJECTED those values, so saving such a row was refused. Surfaced by the harness (S64) noticing raw English in the cell. | **FIXED + verified** |
| D7 | FRICTION | 46, 67 | The drill-down chip showed the raw enum — `סטטוס: EXTRACTION_FAILED`. Now Hebrew, with the raw value kept in the chip's tooltip. | **FIXED + verified** |
| D9 | — | 50 | Default table order was undefined — PostgREST returned planner order, not even stable between identical requests. Now `created_at DESC` in the **query layer** (`SupabaseRepo.query`), so the grid, exports and any API consumer all open newest-first without asking. | **FIXED + verified** |
| DATA-1 | — | — | Upstream: 477 rows have the boolean string `'true'` in the `RECEIVED_DATE` date column (all 477 have a good `DOC_DATE`). A writer bug, not a UI one — flagged for the owner, not mass-fixed. | OPEN (owner) |

## The harness

`bbox indox ui-qa` — [scripts/ui-coverage/e2e/test_indox_ui.py](../../scripts/ui-coverage/e2e/test_indox_ui.py),
also wired into `run_all.py` as the `indox-ui` suite. Drives the live app at
`http://<incoming-documents-ip>:8080` on the traefik network (no Authentik hop, no password,
CI-able), READ-ONLY, exits non-zero on any failure, writes
`ci-artifacts/e2e/indox-ui-scorecard.json`.

**Current: 73/73 passing.** It caught D7 and D8 on its own after being written, which is the
point of it existing.

**Known gap, stated rather than hidden:** it drives the app STANDALONE. The console embeds it in
an iframe, and D6 lives only on that path — so a green run does not currently prove the
console-embedded case. Closing that gap is the next change to the harness, and it must land
before D6 can be called fixed.

**Structural cleanup done in this run:** the four enum vocabularies (status/type/source labels + the
status colour rule) were spread across DashboardPage, DocumentBrowserPage, DocumentDetailPage and
api.ts, each spelling them differently. They now live in one module, `src/vocab.ts`, which is what
made D2 a one-line fix in four places instead of four separate patches — and `documentStatusKind`
was deleted from `api.ts`, leaving that module transport-only.
