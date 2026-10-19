# Simulation alignment changelog

Tracks every **design-alignment change made in the simulation only** (never in the real app source),
so they can later be ported into the live platform frontends. Each entry says WHAT changed, WHERE it
applies, and the exact PORTING action for the real code.

The mechanism: a layer of **sim-only overlays** (`sim/overlay/*.js` — tokens, icons, brand, switcher,
drive, mail, responsive, theme) is injected into every embedded app at build time (by `sim/build.mjs`,
after the app's mock). They run in the app iframe and adjust appearance/behavior at runtime — they do
**not** edit `production/*` or `development/*` source. When we implement for real, each item below becomes
a concrete source edit in the named app(s).

**Entry tracks** (all interleaved newest-first within their block):
- **A** — design alignment: making the 10 real apps look like one product (tokens, icons).
- **B** — quality passes + capability rebuilds (grid, mail actions, chat client, mobile, a11y/theming).
- **C** — platform features built in the sim that the real apps don't have yet (v0.7.0–v0.12.0 era:
  switcher, multi-provider Drive, de-INDOX, compose, health panel, doc renderer, brand/version).
- **D** — the fixtures and tooling that make everything above *verifiable*. Not user-facing, but
  without them a claim like "every screen renders" is an opinion.

> **Implementing this for real?** Start with **[PORT-PLAN.md](PORT-PLAN.md)** — this file says WHAT
> and WHY, entry by entry; that one says in what ORDER, how you know each item is done, and how to
> prove the live platform matches (`flow-qa.py --url <your-host>` runs these exact assertions
> against a real deployment).

**Complementary records of "everything changed":**
1. **This file** — the curated, port-focused log (WHAT / WHERE / PORT action) for the live-platform port.
2. **The git commit history** on `claude/fresh-ui-map-image-80dfry` — the exhaustive, per-change record
   (every commit is one self-contained change with a detailed message + the exact files).
3. **`CONNECTED-INSTANCES.md`** — the design spec behind the C3/C4 switcher pattern (model, switcher UI,
   5-step connect flow) shared by Drive / Mail / Chat. Referenced rather than duplicated below.
4. **`ASTRYX-EXTRACTION.md`** — the Astryx-derived design-system work (A8/A10 quality bars, completion
   matrix) behind B6/B7.

---

## A4 · One palette — the office's, read at build time (2026-10-07)
**Sim change** (`sim/build.mjs`, `sim/overlay/{tokens,theme,switcher,mail,drive,responsive,brand}.js`,
the three forks, `sim/wadmin.html`, the mocks' own data).

The direction of this entry is the reverse of the others: nothing here waits to be ported — the LIVE
platform changed first («Olive Grove», the owner's one palette: `platform-base/bina-ui/theme-tokens.css`,
gates G27 and G82), and the simulation kept the previous one, because it carried copies: A1's forced
token set in `overlay/tokens.js`, each fork's own `:root`, and two more palettes offered as "themes".

- `build.mjs` reads the palette block from the office's file and puts it LAST in the `<head>` of every
  page it embeds (`PALETTE`, `withPalette`). The simulation holds no copy of a colour of the office.
- `overlay/tokens.js` writes no colour (A1's light token set, the status roles and the `slate` /
  `midnight` blocks are gone); what is left is the ramps, the focus ring and the two utilities.
- `overlay/theme.js` chooses a GROUND — by the device, light, dark — not a palette: the same three
  states the live console keeps in `do-theme`. («אמרלד / אפור / כהה» were three palettes.)
- The forks, `wadmin.html` and the overlays name tokens only (≈570 literals and every
  `var(--x,#fallback)` removed; the forks' "midnight" override sections with them), following the
  conversions of their real counterparts — the legend included: what waits is lime, what is in motion
  is the sky, done is olive, failed is plum.
- What is still written as a value, on purpose: a provider's mark (Google, Dropbox, WhatsApp …), a
  picture the mock draws (a document, a stand-in image), and an e-mail's own white paper.
- The INDOX fork's grid skin follows `platform-base/bina-ui/bina-table.css` (the same day, after
  opening a filter panel on the dark ground): the grid is given every colour variable it reads —
  its rows were black, its range blue, its filter panel a white card with the grid's own green
  button, pinned to the window's right edge — and what it writes with no variable is overridden one
  step more specifically than its own sheet does.
- B6's keyboard focus ring is PORTED (2026-10-08): it is three rules of the office's palette block
  now, at no specificity, so `overlay/tokens.js` no longer writes it and the simulation shows the
  ring the live screens show. (The overlay's forced it with `!important` and squared a focused
  part's corners to 4px; a part that draws its own ring keeps it now, here as on the live office.)

**Supersedes** the palette half of A1, the theme blocks of B6 and the colours of C5 (a file's kind keeps
its glyph; its colour is the palette's, in the roles the real mail gives a kind). The tracked
`platform-sim.html` is a build of an earlier day and still shows the old palette until it is rebuilt.

## D2 · Build integrity — a skipped app fails the build, and any built file can be audited
**Sim change** (`sim/build.mjs`, `sim/verify-sim.mjs`).

`build.mjs` silently skipped any app whose html or mock was missing, embedded a grey
"מודול זה ייטען בגרסה הבאה של הסימולטור" placeholder in its place, exited 0, and printed a cheerful
summary listing only the apps that made it. A missing app was indistinguishable from a feature that
had merely been deferred — and anyone piping the build to `/dev/null` (most CI) never saw the one
line that reported it. This actually bit us: a stale download showed דרייב as a placeholder and cost
a round of debugging.

- Skips are collected and **fail the build** unless `BBOX_ALLOW_PARTIAL=1` is set. A thrown app (the
  `✗` path) counts as a skip too; it did not before.
- **`verify-sim.mjs`** reads the embedded registry out of ANY built file and reports version, md5 and
  which apps are real vs placeholder. It keeps its own expected-app list rather than importing from
  `build.mjs`, precisely so it can judge a file produced by an *older* build — which is the case it
  exists for. `node digital-office/sim/verify-sim.mjs [path]`, non-zero exit if anything is missing.

**Port:** none — simulation build tooling.

---

## D1 · View profiles as one tracked source, read by both map generators
**Sim change** (`scripts/ui-coverage/view-profiles.yaml`, `sim/ui-map.py`, the CI capture).

The mobile / tablet / desktop viewports were hardcoded, separately, in the offline sim map and in the
docker-stack CI capture — so the two could disagree about what "mobile" meant and nobody would know.

- `view-profiles.yaml` is now the single tracked declaration (width, height, DSF, touch, columns),
  read by **both** generators, so a viewport is declared once.
- `ci_matrix` in that file drives the CI matrix directly: adding a profile needs no workflow edit.
- `ui-map.py` gained `--profile` / `--all` / `--list` / `--recompose`, a fresh browser context per
  panel (so an open modal on one surface can never leak into the next shot), and grew from 23 to 43
  panels as the Drive/Mail rebuild added surfaces.

**Port:** none — capture tooling, already shared with the real-stack CI path.

---

## C0 · The business data spine — one set of documents behind mail, INDOX and notifications
**Sim change** (`sim/business.js` → `window.__biz`, consumed by `mocks/mailview.js`,
`mocks/incoming.js`, `mocks/notifications.js`).

*(Chronologically the first C-track change — it predates C1 and everything built on it.)*

Each mock invented its own data, so the same supplier invoice was a different amount in מייל than in
INDOX, and the notification about it referenced a document that existed nowhere. The simulation
looked like ten apps that had never met.

- `business.js` holds the canonical business: suppliers, incoming documents (number, amount, kind,
  status, failure reason, dates), and the vocabulary helpers that map one document into each app's
  own language (`kindHeOne`, `kindIndox`, `statusIndox`).
- מייל builds its supplier-invoice messages from it, INDOX's repo is seeded from it, and
  notifications alert about the same records — so a failed extraction shows as `EXTRACTION_FAILED`
  in the table, a "נכשל" label on the message, and an alert naming that same invoice.
- Later (C10) the spine also became the single catalog of **connections and their folders/labels**,
  so INDOX's sync editor can only offer accounts and folders that Drive and Mail actually have.

**Port:** the real apps already share a database; this entry exists because the *fixture* had to
learn what production already knows. What ports is the vocabulary mapping — the three helpers that
translate one document into each app's terms are a real duplication in the live code today.

---

## C16 · One scroll axis at a time — and a check that makes it stay that way
**Sim change** (`sim/apps/indox/src/index.css`, `App.tsx`, `components/BinaTable.tsx`,
`pages/DocumentBrowserPage.tsx`, `sim/flow-qa.py`).

INDOX's documents screen had **two vertical scrollbars stacked on the same axis** — the grid's, and
the document's behind it — so the wheel obeyed whichever the pointer happened to be over. The cause
was one line: `BinaTable` defaulted to `height = 520`, a fixed pixel box. A grid that decides its own
height forces the page around it (header + toolbar + pager + padding) to be taller than the viewport,
and the page starts scrolling too.

- `BinaTable` gains a **`fill`** mode: the card becomes a flex column and the grid takes the height
  it is GIVEN instead of a number chosen up front.
- The INDOX shell is now `height:100dvh; overflow:hidden` — `min-h-screen` was the other half of the
  bug, because `min-height` lets the shell grow past the viewport, which IS the second scrollbar.
- `.wrap` is `flex:1; min-height:0; overflow:auto`, so a genuinely long page (dashboard, sync) still
  scrolls — once, inside one container — while `.page-fill` pages hand the leftover to the grid and
  do not scroll at all.

**Platform-wide audit:** every screen was measured. Only INDOX was doubled. `pinkas`, `alerts`,
`machine` and `validation` overflow the page but have no inner scroller — one scrollbar doing its
job on a long page, which is correct and was left alone.

**Two new permanent suites** (`flow-qa.py scroll` · `flow-qa.py layout`), run at every viewport:

| Invariant | Why |
|---|---|
| the page never scrolls **horizontally** | horizontal scroll on a whole page is never a design decision; it is always something that did not fit and was not told it had to |
| nothing **spills past the viewport edge** | content nobody can reach. Deliberately excludes a closed off-canvas drawer (parked off-screen on purpose) and anything inside a horizontally scrollable ancestor (a wide table in its own scroll region is the CORRECT answer) — a check that cries wolf gets ignored |
| no **double vertical scroll** | the defect above |
| the screen **rendered something** | catches a blank frame before a human has to |

141/141 flows at 1440×900 and at 390×844, zero JS errors.

**Port:** `production/incomingDocuments` — the `fill` prop on the shared table component, the
`height:100dvh` shell, and the `.wrap{flex:1;min-height:0;overflow:auto}` rule. The invariants are
written against the simulation but are viewport-level assertions: pointed at a live URL they hold
for the real stack unchanged.

---

## C15 · The connection switcher moves into the top bar — and the band it lived in disappears
**Sim change** (`sim/overlay/switcher.js`).

The account/connection chip lived in `#acctBar`, a full-width strip between the console header and
the app iframe. That strip existed to hold exactly one chip: it spent ~56px of vertical height, in
every app, forever, to use about 15% of one row. On a laptop that is four file rows or four messages
you cannot see.

- The chip now mounts into the console's own top bar (`.topbar .tb-right`), as the **last** child —
  the far end of the line, which in RTL is screen-left and is where Gmail and Drive keep the
  account. That row already existed and had the room.
- `#acctBar` is collapsed and `embedwrap.has-bar` removed, so the app reclaims the full height. The
  band is kept in the code purely as a fallback for a console build that has no `.tb-right`.
- The chip is compact and degrades by width, and **only the chip does**: under 1100px it drops the
  identity line, under 760px the label too, leaving avatar + status. The menu keeps its labels at
  every width — an account list of four identical coloured circles is not a compact switcher, it is
  a guessing game, and the name is the entire point of that list.

**Port:** `development/console/static/index.html` — move the account element into `.tb-right` and
delete `#acctBar` plus the `.embedwrap.has-bar` rules in `style.css`.

---

## C14 · Flow QA — proving the screens WORK, not that they render
**Sim change** (`sim/flow-qa.py`, plus the four defects it found).

The ui-map proves every screen renders. It cannot prove a screen *works*, and this branch shipped
four defects that looked perfect in a screenshot:

| Defect | Why a screenshot could never see it |
|---|---|
| Mail row selection was invisible — the row never got `.sel`, the checkbox never got `.on` | the screenshot showed a correct-looking list; only the bulk bar hinted anything was selected |
| Closing a dialog left the modal veil up while the reader was open, swallowing every click | an invisible `rgba(...)` sheet photographs as nothing at all |
| INDOX's drawers ignored Escape, and the items drawer covers the tab strip | the drawer looks right; the app is simply stuck |
| `advanceSync()` referenced a non-existent `FAIL_REASONS` array | it threw on a *transition*, never on a paint |

`flow-qa.py` drives every flow to its end and asserts the effect, across four suites
(`drive` · `mail` · `indox` · `console`), and exits non-zero on any failed flow **or any JS error**,
so it can gate CI:

```
python3 digital-office/sim/flow-qa.py             # every suite
python3 digital-office/sim/flow-qa.py drive mail  # named suites
```

Drive covers places · breadcrumb navigation · filter narrow-and-clear · star round-trip and
persistence · details pane · grid selection · shift-range · bulk trash and restore · rename · new
folder · share · full preview with ‹ › · context menu · global search · account switch.
Mail covers every system view · star reaching the starred view · select-by-predicate · bulk archive
with undo-and-restore · reading pane replacing the list · ‹ › walking · conversation turns
expanding · label add · reply prefilled-and-quoted · compose landing in נשלח · search · account
switch. INDOX covers the one-click table · the merged sync surface · the items drawer and its
dismissal · per-instance settings · an instance switch changing the repo. Console walks every rail
destination.


### C14.1 · The phone run — four more, all invisible on a desktop

`flow-qa.py --mobile` runs every flow at 390×844, where both rails move behind a drawer and the
details pane becomes a fixed overlay. The same flows travel a different path and broke in four ways
the desktop run never touches:

| Defect | Why it only exists on a phone |
|---|---|
| **Escape closed the reply AND the message behind it** | the compose overlay only appears above a reader, and Escape is the phone gesture — one keypress read as the app throwing your draft away. Fixed by making Escape peel exactly one layer: the app's handler now runs in the CAPTURE phase, because the compose overlay removes itself before a bubble listener could ever see it. |
| **The details pane had no way out** | above 1120px it is a column beside the list; below, it is a fixed overlay covering the toolbar — including the ⓘ that opened it. It now carries its own ✕, a backdrop, and Escape. |
| **The modal veil sat on top of its dialog** | the veil was raised to z-index 1001 for the old full-screen reader drawer; the modal sits at 60, so on a phone the tag picker was visible and completely unclickable. A veil must always sit directly beneath its dialog. |
| **Touch targets of 25×21px** | fine for a cursor, a coin-toss for a thumb. Apple asks 44pt, Android 48dp. Grown under `pointer:coarse` so the dense desktop layout those controls were tuned for is untouched. |

**Result:** 76/76 flows at 390×844 and 76/76 at 1440×900, zero JS errors, on the ten-year corpora.

**Port:** the suite is written against the simulation, but the assertions ARE the acceptance
criteria for C11/C12/C13 in the real apps — re-point `SIM` at a running stack and the same
assertions hold.

---

## C13 · Ten years of real load — and the UI changes that only a real mailbox/drive forces
**Sim change** (`sim/mocks/mailview.js`, `sim/mocks/localdrive.js`, both forks).

A simulation with fifteen messages and twelve files never has to prove anything: every list fits on
one screen, no counter ever gets big, no date group is ever long, threads are never deep, search
always returns everything, and the tree is never taller than the rail. So both mocks now synthesise
**ten years of one Israeli accounting office** on top of the curated hero sets — generated from a
**seeded PRNG** (never `Math.random`, so screenshots and CI captures are byte-identical), which
keeps the simulation file small while the data is large.

- **Mail** — ~9,800 messages over ten years, denser recently: supplier documents with the sync
  pipeline's own labels in realistic proportions, client conversations **with 1–4-turn reply
  chains**, system digests, newsletters, sent mail, spam, deleted mail, drafts, stars and importance
  marks, and attachments across nine formats. Unread thins out with age, exactly like a mailbox that
  was actually worked through.
- **Drive** — a `ארכיון/<year>/<month>` tree across ten years (~130 folders, ~3,000 files) on the
  office account and three years on the local disk, spanning fourteen formats with **format-accurate
  sizes** (a 4 kB "scan" would make the storage meter a lie), real ownership and sharing.

**What the load then forced — each of these is a bug that only exists at scale:**

| Symptom at scale | Fix |
|---|---|
| Rail counts read "19 unread" on a mailbox with 400 — computed from the loaded page, which is 1% of the box | `viewCounts()` server-side over the whole mailbox; client overlays only its local marks |
| נשלח / טיוטות / ספאם / אשפה looked empty — they were filtered from the loaded inbox page | real server-side `view=` queries (`sent`·`drafts`·`spam`·`trash`·`starred`·`important`·`all`) |
| A star vanished on the next refetch — it was sim-local state | `POST api/mark`; STARRED/IMPORTANT are labels the backend keeps, seeded back into the client on fetch |
| "מוקדם יותר" became ONE heading above 9,000 rows | `dayKey()` keeps dividing: היום · אתמול · השבוע · החודש · month · month + year |
| "5 במאי" meant ten different days | `fmtDate()` shows the year for anything outside the current year (both apps) |
| A 3,000-file folder painted 3,000 rows / 3,000 SVG cards | drive view **windowing** (`PAGE`/`SHOWN`) — sort, filter, count and select-all still run over the whole list, only the DOM is capped, and the window grows on scroll |
| A 130-folder tree became a wall of identical month names | **collapsible tree nodes** with their own twisty hit target, persisted open state, and the path to the current folder force-opened |
| A four-turn thread could only be read four screens at a time | `GET api/thread/<id>` + the **conversation view**: newest expanded, earlier turns collapsed to one line each, expand in place |
| Attachments were a row of identical links | **attachment cards** with a type-coloured glyph and a human word ("PDF · 1.1 MB") |

- **INDOX** — the repo now carries ~13,800 documents for סבח (a decade-old client) and ~1,450 for
  אגן (onboarded eighteen months ago), so switching instances changes the SCALE of the table and not
  only the names in it. Status mix is age-aware: the churn lives in the last few weeks, old
  documents are almost all `COMPLETED`, and the failure long-tail (OCR · corrupt file · amount
  mismatch · missing order link · VAT-id mismatch · duplicate · unclassified) is present in the
  proportions an operator actually meets.
- **Bug found by the load, fixed**: `advanceSync()` referenced a `FAIL_REASONS` array that does not
  exist — every pipeline tick that produced a failure threw. It never fired in the old fixture
  because the tick rarely reached a failure; at volume it threw on the first sync tab open. It now
  uses `pickFail()` and carries the full taxonomy (`error`, `error_code`, `error_group`), which the
  board needs to decide which action it can offer.

**Port:** the generators are simulation-only fixtures. What ports is the list above: whole-mailbox
counts in the list response, server-side system views, `api/mark`, `api/thread/<id>`, and the
client-side windowing/tree/date/thread/attachment work in both apps.

---

## C12 · מייל · a real mail client: system-label rail, replace-in-place reading, undo everywhere
**Sim change** (`sim/apps/mailview/index.html` + `app.js` — the sim-owned fork; nothing under
`production/mailview` touched).

**Why:** the screen answered "which INDOX-tagged messages need work?" and nothing else. A mail client
has to answer "where can a message BE?" before anything else, and this one had two links (דואר נכנס,
דורש טיפול) and a drawer. Everything below comes from that one gap.

- **System-label rail** (`SYS_VIEWS`, `renderSysNav`) — דואר נכנס · מסומן בכוכב · נדחה · נשלח ·
  טיוטות · דורש טיפול, with חשוב / כל הדואר / ספאם / אשפה behind **עוד**. Frequency-ordered, not
  alphabetical. Counts are UNREAD counts and are **omitted when zero** (a "0" badge reads as a badge
  and costs attention for no information). The active row is a full-bleed pill.
- **Archive and delete MOVE, they never destroy** (`ARCHIVED`/`TRASHED`/`SNOOZED` sets + `inView()`).
  Archiving takes a message out of Inbox and it stays findable in כל הדואר. This is what makes
  "where did it go?" answerable and undo cheap.
- **Undo snackbar** (`snack()`, `moveTo()`) — every destructive action acts immediately and offers
  the reversal for 6s. **No confirmation dialogs**: a confirm taxes the 99% of correct actions to
  protect the 1% wrong one; undo taxes nothing.
- **Select-all with predicates** (`#gmAllCaret` → הכל / כלום / נקראו / לא נקראו / מסומנים בכוכב /
  ללא כוכב) plus a partial-selection dash state, because "select every unread" is the operation
  people actually want and clicking 40 boxes is not it. Bulk bar gains דחייה and סימון כלא נקרא.
- **Density switch** (comfortable · cozy · compact) on `body[data-density]`.
- **Replace-in-place reading pane** (`.readpane`) — opening a message **replaces** the list instead
  of sliding a drawer over it, so ← lands exactly where you left. Subject is the page heading,
  sender block below it, body capped at a readable measure (860px), one action bar at the top
  (ארכיון · מחיקה · לא נקרא · דחייה · כוכב) and ‹ › walking the same list. `←`/`→` on the keyboard
  walk it too, **with the RTL sense** (left = next).
- **Every emoji-as-icon replaced** with the Lucide set already used by דרייב/wadmin/console (one
  stroke weight, one size, colour inherits). Closes A2's mailview rows in the fork.
- **Landing view is the inbox**, not `/attention` — the attention queue is now one labelled row in
  the rail carrying its own count, so it no longer has to be the landing view.
- **Hebrew**: uses Gmail's own Hebrew terms (נדחה, not the colloquial "נודניק").


**Coverage-engine note (applies to C11 + C12):** `scripts/ui-coverage/inventory.py` derives the
mail and drive view sets from `production/*/static/app.js` — the real sources, which these entries
deliberately do not touch — so CI coverage is still accurate for the live platform today. When the
port lands, `x_mailview` gains the `/v/<view>` system views and `x_localdrive` gains `/p/<place>`,
and the denominators grow with them. Doing it the other way round (adding the views to the
inventory first) would report coverage for screens that do not exist yet.

**Port:** `production/mailview/static/index.html` + `static/app.js`. The rail, the move-sets, the
snackbar and the reading pane are all client-side over the existing `api/messages` shape — the only
backend work is persisting starred / important / snoozed / archived per message (today they are
sim-local sets) and honouring `view=` for sent/drafts/spam/trash server-side instead of filtering
the fetched page.

---

## C11 · דרייב · a real drive: places, breadcrumb, filters, grid, details, full preview, sharing
**Sim change** (`sim/apps/localdrive/index.html` + `app.js` + `sim/mocks/localdrive.js` — the
sim-owned fork; nothing under `production/localdrive` touched).

**Why:** the drive showed one flat folder list and a table with three columns. It could not answer
where you are (no path), what kind of file this is (no type language), who owns it, who else can see
it, what you touched recently, or how full the disk is.

- **System places** (`SYS_PLACES`, `renderSysRail`) — דף הבית · הדרייב שלי · שיתפו איתי · לאחרונה ·
  מסומן בכוכב · אשפה. Three of those are **standing queries, not places** (a file is in several at
  once and moving it changes none of them), which is why they sit above the tree and visually apart.
  `/p/<place>` is in the URL, so a place is linkable.
- **Breadcrumb** with a real nested path; **every crumb is a drop target**, so "move this up two
  levels" needs no hunting in the tree.
- **Filter chips** — סוג · שונה · אנשים. A chip that is off is an offer; a chip that is on states its
  value **and carries its own ✕**. Filters clear on navigation (a filter that survives a folder
  change silently hides files and reads as "the folder is empty").
- **Grid view** with a type-coloured thumbnail band, toggled against the list and **persisted**
  (it is a preference about how this person reads, not about this folder).
- **Details pane** — type in human words (`typeName`: "גיליון Google", never a mime string), size,
  location, owner, created, last opened, and who it is shared with. It reflects the selection and
  **describes the folder when nothing is selected** (a pane that goes blank reads as broken).
- **Full-screen document view** replacing the old side drawer: dark chrome so the page is the
  brightest thing on screen, one action bar, and ‹ › walking the same list you were reading, with
  the RTL sense.
- **Share dialog** ordered the way the question is asked — who has it now, then who else may, then
  the link. ("Copy link" first is what trains people to paste links nobody can open.)
- **Storage meter** with amber/red thresholds, and sizes that read at human scale (GB/TB, not
  "238418.6 MB").
- **Starring** as a mark, not a move (`api/star`), with undo when un-starring inside מסומן בכוכב.
- **List gains** a star column, an owner avatar + name, and a shared mark; folders render **above**
  files in both layouts.
- **Selection now follows what is on screen** — ⌘/Ctrl+A and shift-range use the filtered, visible
  list, so a bulk action can never touch rows a filter is hiding.

**Mock/API additions** (`sim/mocks/localdrive.js`, all documented in its header):
`GET api/files?view=recent|starred|shared` · `POST api/star {ids,starred?}` · `GET api/storage
{used,total,files}`; `publicFile` now carries `owner`, `shared[]`, `starred`, `opened`. Content grew
to ~50 files across nested folders with real ownership and sharing, because density is what makes
list-vs-grid, sorting and filter chips worth having at all.

**Port:** `production/localdrive/static/index.html` + `static/app.js`, plus the three endpoints above
in the drive service. `opened` is the only genuinely new column the backend must keep (Recent sorts
by last-opened, **not** by created).

---

## C10 · INDOX sync · operator board at real scale, on the platform's real connections
**Sim change** (`sim/business.js`, `mocks/incoming.js`, `pages/SyncBoard.tsx`, `SyncStatePage.tsx`;
port contract in **`INDOX-SYNC-PORT.md`**).
- **Connections now come from the shared spine.** INDOX carried its own connection list and its own
  folder/label tables, so the sync editor could offer accounts and folders Drive and Mail had never
  heard of. `sim/business.js` is now the single catalog all three read — same accounts, same folders,
  same labels, same health. Creating a folder/label from INDOX writes into the spine, so Drive sees it.
- **Real operating scale**: 8 pipes across 4 real connections (2 mail, 2 drive), ~3,100 documents
  synced, deliberately seeded so every operator case exists — a healthy high-volume pipe, a pile of
  unclassified receipts, a mail pipe full of irrelevant mail to skip, and a pipe parked on a **broken
  connection** (Dropbox, `status:error` in the spine) whose items strand in an unknown state.
- **Failures carry machine codes** (`ocr` · `type` · `company` · `connection` · `timeout` ·
  `duplicate` · `corrupt`), grouped `fixable | type | terminal`. At 3,000 docs/month nobody fixes
  failures one at a time — they fix a **cause** and re-queue everything behind it, so the board filters
  and acts by cause.
- **`fallback_type` per pipe** — the real `bs-gdrive-sync` case: anything in `נכנס/קבלות` IS a receipt,
  so when extraction can't classify, the pipe's own location answers it. One click reclassifies the
  whole "סוג לא זוהה" class and re-queues it.
- **Stuck detection** — an item claimed longer ago than the pipe's `timeout_min` is surfaced as תקוע
  with a `שחרר` action, and totalled in a banner alongside broken connections.
- **Type is optional per pipe.** A mixed folder or label has no single correct type, and forcing one
  would mislabel everything in it — so `type_hint`/`fallback_type` may be null and the editor defaults
  to "ללא — הסוג ייקבע לפי זיהוי המסמך", stating the consequence either way. The one-click
  reclassify is offered only when the selected items' pipe actually declares a fallback.
- **Selection is explicit**: a checkbox on every card, a select-all checkbox in every column header,
  visible `בחר N` / `בחר את כל N` / `נקה` buttons and a "Shift לטווח · גררו לעמודה" hint. The first
  cut hid all of this behind muted 11px links that read as captions rather than controls.
- **The board**: 4 state columns, multi-select (click · shift-range · select-all-loaded ·
  select-all-N-matching beyond the page), **drag between columns** with illegal targets refusing the
  drop, bulk actions, filters by pipe/cause/search/stuck, and paging so a month of documents stays
  usable. On phones the columns collapse to one behind a segmented control and the bulk bar becomes
  the whole interaction — dragging a card past three stacked columns is a poor phone gesture, and
  HTML5 drag-and-drop does not fire on touch at all (which is why dragging is pointer-event based).
**Port:** `INDOX-SYNC-PORT.md` maps every call to the real control plane. The board turned out to sit
directly on the primitives `ai/context/indox-sync-control-plane.md` already defines — LIST(sync,state),
CLAIM, ADVANCE — so most of it is BFF routes over existing ops. Genuinely new: registry CRUD, failure
**codes** from processors, and a `claimed_at` stamp (gmail cannot report when a label was added, so
stuck detection for mail pipes needs it).

## C9 · INDOX · one sync surface (author + watch + act), replacing two read-only halves
**Sim change** (`sim/apps/indox/src/pages/SyncStatePage.tsx`, `SettingsPage.tsx`, `mocks/incoming.js`,
design in **`INDOX-SYNC.md`**). The same `sync_registry` was rendered **twice** — live counts under
**סנכרון**, the config under **הגדרות** — both read-only, so answering "is this pipe healthy, and what
folder does it watch?" needed two tabs and *changing* it needed neither: there was no edit path at all.
- **One card per pipe** now carries config **and** live state **and** its actions. The 4-state bar is a
  control, not decoration: each segment opens the items behind it. Every non-zero state gets a visible
  width floor — proportionally, 2 waiting beside 184 synced rounds to an invisible sliver, so a pipe
  with a problem looked identical to a healthy one.
- **Items, not counters.** Counts used to be four integers drifting randomly; you cannot move an item
  that doesn't exist. Each pipe now owns a real queue and **every count is derived from it**, so a move,
  a run and the bar can never disagree.
- **Move items between states**, with a legal-transition table enforced on both sides:
  `failed→to_sync` (נסה שוב) · `in_progress→to_sync` (שחרר a stuck claim) · `synced→to_sync`
  (סנכרן מחדש) · `to_sync→synced` (דלג). `to_sync→in_progress` is deliberately **not** offered — that
  transition *is* what running means, and hand-placing an item there would invent a claim no worker
  holds, i.e. exactly the stuck state שחרר exists to clean up.
- **Run manually** per pipe or all at once; **pause/resume** a pipe without deleting its config.
- **Connection-first editor** — pick the connection, and that choice decides labels (gmail) vs folders
  (drive); then **browse that connection's real locations** with item counts and pick from them, or
  create a new one inline. You cannot list the folders to choose from before knowing the account.
- **Settings loses the duplicate** and points at סנכרון, so a pipe is described in exactly one place.
**Fixes a defect from C8:** `registry` became per-instance but `SYNC_COUNTS` stayed global — verified
that אגן שיווק was shown **סבח's** three syncs as its live state. The sync board lied for every instance
but the first. Counts now derive from per-instance items, so the board follows the switcher.
**Port:** `sync_registry`, `labels` and `pairs` are the real shapes — the editor writes what the live
pipeline already consumes. Needs four small endpoints (locations browse/create, registry CRUD, run,
item move). The one new backend concept is the item queue, and even that maps onto existing reality:
`GET /sync/items` = "messages carrying label X" / "files in folder Y", and a move = relabel / move-file.

## C8 · INDOX instances (a whole INDOX per company) + one click to the table + no Kafka
**Sim change** — this is the first change that needed the app's *own source*, so INDOX was **forked
into the sim** (`sim/apps/indox/`, seeded byte-identical to the platform build; `build.mjs` compiles it
automatically and `dist-sim` is a gitignored artifact). Nothing under `development/` or `production/`
was touched.
- **Two screens deleted.** `מסמכים` used to open a "pick a מאגר" list → a "repo detail" screen → the
  table. Both were pure navigation. The tab now points at the **active instance's table**; `/repos` and
  `/repos/:repo` are redirects so the back button and deep links can't reach the dead screens. Repo
  detail's information (backend, target table, primary key, row count) is **promoted into an
  always-visible strip above the grid** — it costs zero clicks now instead of one.
- **Instances, not repos.** An instance owns *everything* that makes an INDOX what it is: its final
  table + documents + history, its sync registry, **and its settings** — the key/value store, the
  companies table, the tag-rules table and the extraction queries. `activate()` re-points every live
  store at once, so switching company swaps all of them together. Seeded with two genuinely different
  instances (סבח: supabase / `incoming_documents` / gmail+drive · אגן: gsheet / `INDOX_AGAN` /
  drive-only), exactly one active.
- **Top-bar switcher** (`overlay/switcher.js`, new `isIndox` branch) — the same chip Drive/Mail/Chat
  use, over the same `accounts / account/select / account/add` contract (served by INDOX under its own
  `/incomingDocuments` prefix). Includes a **"פרטי המופע"** panel showing the target table, columns and
  per-instance store counts.
- **New-instance flow** — 3 steps: identity → target table (supabase table / gsheet sheet) →
  **sync registries**: pick a real connection (the Drive/Mail accounts the platform already has), then
  what to pull from it — **gmail labels** or **drive folder pairs** — plus type hint and schedule. A new
  instance starts with an empty table, default settings and only its chosen registries.
- **Switching returns to the default view** (לוח בקרה) rather than forcing the מסמכים tab — only
  `/repos/:repo/*` carries an instance id, so staying put would strand you on the previous instance's
  table. When sub-routing becomes per-instance this should instead preserve the open sub-tab.
- **The create-repo screen was removed too** — it was orphaned once the repo list was deleted, and it
  could not select sync registries; creation now lives in the switcher flow.
- **Kafka removed entirely** (unused): the tail page + route, `RepoConfig.kafka`, `kafka_enabled`,
  `kafkaTail()`, the SSE feed and `kafka_default_partitions`. Zero occurrences remain.
- **Fixed a latent blank-app bug** — react-router v6 normalises `basename` via `replace(/^\/*/,'/')`,
  turning the srcdoc pathname `srcdoc` into `/srcdoc`, which no longer prefixes it; `stripBasename`
  returns null and `<Router>` renders **null** with no error. Any fresh INDOX build rendered an empty
  `#root`; the sim had been riding on a stale prebuilt artifact. Now routes in memory when there is no
  real http(s) URL. Also unpinned the dashboard's "all documents" link, which hardcoded one company's
  repo id.
**Port:** the real model already has both halves — `RepoConfig` *is* an instance and `sync_registry` is
a real settings key with `labels` (gmail tags) and `pairs` (drive folders). To ship: point `מסמכים` at
the active repo's documents route and demote the repo list to a switcher; scope `/config/settings`,
`/config/companies`, `/config/tag_rules` and `/sync/registry` **by repo** (today they're global — that's
what makes settings shared); add the registry-authoring step to repo creation; drop the Kafka paths.

## B7 · Mobile completion (0 overflow everywhere) + consistent Esc + QA-review fixes
**Sim change** (`sim/overlay/responsive.js` + `sim/wadmin.html`):
- **Generic mobile fallback** for every app not individually handled (incoming-documents + infra
  dashboards): horizontal tab-bars/navs and wide data tables scroll inside themselves; toolbars wrap;
  media caps at 100%. Result: **all 10 apps have 0 horizontal overflow at 390px**.
- **Global Esc-closes-overlay** (A10.5/6): Esc closes the topmost open overlay/drawer/dialog in ANY app
  (real apps' modals too, via their close control / backdrop) — one consistent gesture everywhere.
- **Drive auto-opens the root folder** on desktop **and** mobile (was a blank "בחר תיקייה מהצד" pane).
- **Chat error account**: surfaces a "החיבור נכשל" + "חבר מחדש" reconnect card in the conversation list
  (on mobile the thread pane is hidden, so the errored account was a dead-end).
- Slimmed the mobile console topbar + account-switcher bar; nudged the desktop hub to medium density.
**Port:** fold each app's mobile rules into its own stylesheet; give Drive a default-folder-on-load; add
the error→reconnect list state + a global Esc handler to the shell.

## B6 · Astryx-derived design-system layer — accessibility + theming (see ASTRYX-EXTRACTION.md)
Extracted the essence of Meta's Astryx (8-yr design system) into our vanilla stack. Sim changes:
- **`sim/overlay/tokens.js`**: token ramps (spacing/radius/elevation/motion + status roles); a global
  keyboard **`:focus-visible` ring**; `.visually-hidden` utility; `prefers-reduced-motion` guard; and
  **theme blocks** (`:root[data-theme="slate"|"midnight"]`) — a theme is just a variable-override set.
- **`sim/overlay/theme.js`** (new): a console **theme switcher** (אמרלד/אפור/כהה) that sets `data-theme`
  on the console + every app iframe (cascade), persisted to localStorage.
- **Accessibility**: Esc-close + focus-trap + focus-restore on our overlays (switcher/compose/health);
  ARIA roles + keyboard nav on the **chat** (list/listitem/log, Enter/Space) and the **account switcher**
  (menu/menuitemradio, aria-expanded, arrows/Esc); a **skip-to-content** link in the console shell.
**Port:** move the token ramps + theme blocks into each app's `:root`; ship the a11y defaults
(focus-visible, ARIA, skip link, focus-managed dialogs) in the shared `development/design/bina-ui.css`
and the console shell. `ASTRYX-EXTRACTION.md` holds the full essence, the A8/A10 quality-bars, and the
completion matrix (incl. the two genuinely PORT-only items: async-undo on native `confirm()`, deep
inline form-validation inside the real app forms).

## B5 · Mobile Hebrew mojibake fix + chat message-list scroll fix
- **Charset**: `sim/build.mjs` now emits `<meta charset="utf-8">` as the **first** child of `<head>`
  (was at byte ~65726, past the ~1KB mobile browsers sniff → Hebrew rendered as mojibake on phones) plus
  a **UTF-8 BOM**. **Port:** ensure every served page has charset first in `<head>`.
- **Chat scroll**: `sim/wadmin.html` — the `#thread` wrapper broke the flex chain (`min-height:0`
  missing), so the message list grew past the viewport and pushed the composer off-screen. Fixed the
  flex column so `.msgs` scrolls internally and the composer stays pinned, for any message count.
  **Port:** part of the chat-client port (B3).

---

## B4 · Mobile-first responsive pass (desktop kept pixel-identical)
**Goal:** a native super-app feel on phones — central hub + bottom tab bar, full-screen sub-apps,
single-column list→detail→back — while every desktop layout stays byte-for-byte the same (all rules are
behind `@media (max-width:…)`, so >820px is untouched). Grounded in 2026 super-app patterns (WeChat/Grab/
Gojek: hub + 3–5 bottom tabs in the thumb zone, mini-app shell, 44–48px targets, no hover menus).
**Also fixed a latent bug that hurt mobile everywhere:** `<meta charset>` sat at byte ~65726 (past the
~1KB mobile browsers sniff) → Hebrew mojibake on phones. Now charset is first in `<head>` + a UTF-8 BOM.
**Sim changes:**
- `sim/wadmin.html` (chat, sim-authored): `@media(max-width:820px)` collapses the 3-pane layout to a
  single column; tapping a conversation slides to a full-screen thread with a ‹back button; composer
  clears the console's bottom nav; touch-sized rows/controls.
- `sim/overlay/responsive.js` (NEW): injected into every app + the console shell. Console: reserves the
  60px bottom-nav strip inside `.embedwrap.has-bar` (the switcher had flipped `.embed` off absolute,
  killing the native `.embed{inset:0 0 60px 0}` so app bottoms hid under the nav). Mail: `#app` grid →
  single column + labels sidebar becomes an RTL-correct off-canvas drawer (hamburger + backdrop) +
  full-screen reader. Docs (my-docs): `.dash-top`/`.drawer-b` grids → single column, KPI strip → 2 cols
  (1 col ≤460px), nav wraps, data grids scroll in-card. Drive is already mobile-native (own drawer) → left
  untouched. The console shell is already responsive (icon-rail ≤1024, bottom tab bar ≤640).
**Verified:** console/chat/mail/drive/docs all 0 horizontal overflow at 390px; chat list→thread→back +
composer-above-nav; desktop (1440) overflow 0, chat still 3-pane, no stray hamburger (display:none).
**Port (real source):** fold each app's `@media(max-width:820px)` block into its own stylesheet; give
mail a real sidebar-drawer toggle; the charset-first + BOM belong in every served page's `<head>`.

---

## B3 · Chat: renamed "בוט ווצאפ" → "צ׳אט" and rebuilt as a multi-provider chat client
**Sim change:** the WhatsApp-admin surface (`sim/wadmin.html`, module id `whatsapp`) is renamed **צ׳אט**
(console.js module + app title/brand) and rebuilt into a full chat client that mirrors the Drive/Mail
multi-account pattern:
- **Accounts / providers** — a top-bar instance switcher (the shared `switcher.js`, now with an `isChat`
  branch) over `api/accounts` + `api/account/select` + `api/account/add`, with a `api/chat-providers`
  catalog: local (fully functional, builtin), WhatsApp·Baileys (QR), Telegram Bot (Bot Token),
  WhatsApp Cloud API (API key + Phone ID), Facebook Messenger. Full connect flow + connection-health
  panel (status / reason / "בדוק שוב" / event log), identical to Mail.
- **Full chat UI** — conversation list (search, filters: הכל/לא נקראו/קבוצות/מסומנות, unread badges,
  pins, tags), a WhatsApp-Web thread (in/out bubbles, timestamps, read ticks) and a composer that sends
  via `api/conversation/<id>/send`. Switching account re-boots the client through `window.__chatReload`.
- **Active bot per connection** — a "בוט פעיל בחיבור זה" selector (bots: ללא בוט / תפריט בסיסי /
  תורים והזמנות / מסמכים) persisted per account via `api/account/bot`; when a bot is active it
  auto-replies in the thread and shows a botnote. The mock (`sim/mocks/wadmin.js`) is the full backend.
- **Premium visual pass (v0.16.0)** — a refined design system: gradient brand mark, sectioned sidebar
  (bot control + provider-badged connection footer), segmented filter tabs, presence dots, a subtle
  dotted chat wallpaper, grouped message bubbles with tails + day separators, an animated typing
  indicator before bot replies, read-tick previews in the list, and polished composer/micro-interactions.
  Fully theme-aware (light + dark).
**Port (real source):** the live WhatsApp admin (`whatsapp-hacohanim`) is a single-account bot panel.
To ship this, generalize its backend to a multi-provider account model (local/Baileys/Telegram/Cloud
adapters behind one interface), add a conversations+messages store and a per-account "active bot"
assignment, and replace the admin page with this chat UI. The sim mock's endpoint shapes
(`api/accounts`, `api/chat-providers`, `api/bots`, `api/account/bot`, `api/conversations`,
`api/conversation/<id>[/send]`) are the reference contract.

---

## B2 · Mail reply / reply-all / forward (the real reader is read-only)
**Sim change:** `sim/overlay/mail.js` adds a Gmail-style action bar (השב / השב לכולם / העבר) to the
message reader (`#reader .drawer-h`) and wires it to the compose modal (`window.__mailCompose`). It
remembers the last-opened row (rows carry `data-id`), re-fetches the full message, and prefills:
reply → `to`=sender address, `Re:` subject, quoted body with a "בתאריך … כתב/ה:" attribution;
reply-all → also appends the original `to`; forward → empty `to`, `Fwd:` subject, a "הודעה שהועברה"
header block + original body. Sends through the mock's `api/send` (persists to SENT).
**Port (real source):** `production/mailview` is currently a read-only viewer. To ship this for real,
add a compose/reply capability to the mailview frontend (button bar in the reader + a compose view) and
a backend `send` endpoint, OR route "reply/forward" to the Gmail/provider deep-link. The sim's prefill
logic (address extraction, quote/forward formatting) is a ready reference.

---

## B1 · RevoGrid pre-bundled so the real BinaTable grid renders offline (fixes "טוען נתונים…" hang)
**Symptom:** every BinaTable grid in the sim (my-docs מסמכים / לקוחות / פריטים, and `production/machine`)
hung forever on the "טוען נתונים…" spinner and never showed rows.
**Root cause (not a sim data bug):** `vendor/bina-table.js` lazy-loads RevoGrid at first `create()` via a
runtime **module** import — `import(`./${bundleId}.entry.js`)` in the Stencil loader
(`vendor/revo-grid/index-Chp_81rd.js`), resolved against `import.meta.url`. Inside the offline
`about:srcdoc` iframe there is no network and the opaque origin can't resolve that URL, so
`customElements.whenDefined('revo-grid')` never settles and the grid stays in its loading state.
**Sim fix (no real-source edit):** `sim/bundle-revogrid.mjs` copies the **exact vendored dist (v4.43.2)**,
rewrites that ONE computed dynamic import into a static switch over the finite, known bundle-id set
(`revo-grid`, `revogr-filter-panel`, `revogr-clipboard_3`, `revogr-data_4`, `revogr-attribution_7`), and
esbuild-bundles it to a single offline IIFE → `sim/vendor/revo-grid.bundle.js`. `sim/build.mjs` injects
that bundle (after the URL shim, before app code) into every app whose page references `bina-table`
(my-docs, machine, incoming), so `customElements.get('revo-grid')` is already defined when
`BinaTable.create()` runs. `bina-table.js:90` then short-circuits its loader and the **real** grid renders —
row-headers, export/density toolbar, search, quick-filter chips, sorting and row-click all identical to the
live platform. `incoming-documents` ships its own RevoGrid; the double-define is a no-op (Stencil guards
with `customElements.get`), verified 0 console errors.
**Port (real source):** nothing to change in the app — this is a sim-packaging concern only. The live
platform serves `vendor/revo-grid/*.entry.js` over HTTP, so it already works there. If a future fully-static
export of the platform is wanted, reuse `bundle-revogrid.mjs` (or ship Stencil's `dist-custom-elements`
single-file build) so no runtime chunk fetch is needed.

---

## C7 · my-docs: faithful document renderer + fluid doc-view (v0.8.0–v0.8.2)
**Sim change** (`sim/mocks/my-docs.js`): documents are rendered by a **1:1 JS port of the real
production doc-gen template** (the live app proxies `/documents/:id/download` → apitools doc-gen,
WeasyPrint HTML→PDF — unreachable offline). Same A4 print design: brand mono-mark, doc chip, hero tick,
field grid, line-items table, totals, seal + signature block.
- **v0.8.1/0.8.2** — the fixed-A4-width page clipped inside narrow preview panes. Reworked to a **fluid
  fills-to-width layout** (`width:100%;max-width:210mm` + `clamp()` padding) so it never clips at any
  pane width, with the print design preserved. No JS scaling — the preview iframe blocks inline scripts.
- Removed the "כל התיבות" filter option (the real backend has no such grouping — it was a dead control).
**Port:** nothing needed for the PDF itself (the live doc-gen path works over HTTP). Do port the two UI
fixes: make the document **preview pane** fluid rather than fixed-A4 so it can't clip, and drop the
unsupported "כל התיבות" option from the real filter.

## C6 · Mail: Gmail-style Compose (the real reader is read-only)
**Sim change** (`sim/overlay/mail.js`): a prominent "כתיבה" pill button in the mail sidebar + a
bottom-anchored compose modal (אל / נושא / body, RTL) that sends through the mock's `api/send`
(persists into the active mailbox's SENT) and confirms with a toast. Exposed as `window.__mailCompose`
— this is the hook **B2** (reply / reply-all / forward) later prefills into.
**Port:** `production/mailview` is a read-only viewer. Shipping this needs a compose view in the frontend
plus a backend `send` endpoint — or route composing to the provider's deep-link. See B2 for the
reply/forward prefill logic that builds on the same modal.

## C5 · Drive: true Google file-type icons on file rows
**Sim change** (`sim/overlay/drive.js`): the real localdrive paints **one generic glyph** for every file.
The overlay reads the active account's id→mime map (`window.__driveMime`, exposed by the mock) and paints
the correct Google-style typed icon + brand color per row — Docs `#1a73e8`, Sheets `#0f9d58`, Slides
`#e8710a`, PDF `#d93025`, image `#12b5cb`, archive/text/generic `#5f6368`.
**Port:** add a mime→icon map to the localdrive file-row renderer (the sim's `typeOf()` regex table is a
ready reference) so file type is scannable at a glance instead of uniform.

## C4 · Connection health propagated everywhere + a health / error-log panel
**Sim change** (`sim/overlay/switcher.js`): every connected instance carries `status` (`ok` / `warning` /
`error`) + a human `reason` + an event `log`. That vocabulary propagates to **three** surfaces: the
closed chip's status dot (worst-of-all-connections), each dropdown row's dot + reason line, and a
**"מצב החיבורים" panel** — per-connection status, reason, a "בדוק שוב" re-check action, and an
expandable timestamped event log. Chat additionally surfaces an errored account as a "חבר מחדש"
reconnect card in the conversation list (see B7).
**Port:** give the real account model a `status` / `reason` / `log` triple and render the same three
surfaces. This is the difference between "it silently shows nothing" and "the user knows *why*."

## C3 · Connected-instances switcher + connect flow for Drive / Mail / Chat
**Sim change** (`sim/overlay/switcher.js`, spec in `CONNECTED-INSTANCES.md`): the platform is a **hub over
many providers**, but the real apps have no visible way to switch between connected accounts. The overlay
adds ONE switcher shared by all three apps, mounted **top-level** into the console's service bar
(`#acctBar`, reached same-origin via `window.parent`), falling back to the app sidebar.
- **Drive** — delegates switch/connect to the app's own proven-but-hidden native controls
  (`#acctBtn` / `.acct-pick` / `.acct-add`), so the working flow finally gets visible UI.
- **Mail / Chat** — fully custom against the generic accounts API (`api/accounts`, `api/account/select`,
  `api/account/add`); only the provider catalog and the post-switch reload differ (mail re-fetches the
  inbox, chat re-boots via `window.__chatReload`).
- **Connect flow** — provider picker → method (OAuth / form) → credentials → verify → connected.
- **v0.9.0** merged what had been two competing switchers (console-level + per-app) into this single one.
**Port:** implement the `{id, provider, label, identity, color, status, builtin}` instance model + the
switcher/connect UI once in the shell, and have Drive/Mail/Chat all bind to it. `CONNECTED-INSTANCES.md`
is the authoritative spec (model, switcher states, 5-step connect flow, provider registries).

## C2 · De-INDOX: Drive and Mail became standalone platform apps
**Sim change** (`sim/mocks/localdrive.js`, `sim/mocks/mailview.js`): both apps shipped hard-wired to
INDOX-specific content (INDOX folder trees, INDOX-labelled mailboxes), which made the hub read as one
vertical rather than a general office. Reworked to **local-first, multi-provider**: Drive = built-in
"אחסון מקומי" + connectable Google Drive / Dropbox / OneDrive / S3; Mail = built-in "דואר מקומי" +
Gmail / Outlook / IMAP. INDOX becomes *one app among ten*, not the platform's identity.
**Port:** decouple the real localdrive and mailview from INDOX-specific seeding/labels and give each a
built-in local instance as the default. This is the data-model half of C3.

## C1 · Brand rename המרכז → הלשכה הדיגיטלית + build-version footer
**Sim change** (`sim/overlay/brand.js`): a text-node walker renames the brand across every app (only the
console shell carries the string, so a global swap is safe), relabels the single-letter logo mark
`מ` → `ל`, and rewrites the tab title. Also pins a **build version** (`digital-office v0.22.0`) to the
bottom of the console side menu — bumped on every sim change, so you always know which build you're
looking at.
**Port:** the rename is a straight source edit in the console shell (string + logo letter + `<title>`);
no runtime walker needed. The version footer is a genuinely useful shell feature — wire it to the real
build/commit stamp when porting.

---

## A1 · Design tokens normalized to one palette + one type stack (light theme)
**Sim change:** `sim/overlay/tokens.js` injects a canonical `:root` token block, **scoped to**
`@media (prefers-color-scheme:light)`** so the dark-mode variants keep their own tokens:
```
--bg:#f4f6f8; --surface:#fff; --surface-2:#fbfcfd; --ink:#15202b; --muted:#65727e; --line:#e3e8ec;
--accent:#0e9f6e; --accent-d:#087f57; --accent-soft:#e6f6ef;
--font:"Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew","Assistant",Arial,sans-serif;
```
**Drift found across a full `:root` sweep (port each in real source so no runtime override is needed):**
- `production/notifications` — dark-block `--accent:#12b981` (brighter). Keep for dark, but its light
  block is canonical; confirm the light `--accent` stays `#0e9f6e`.
- `development/connections` — `--accent-d:#0a7d55` → `#087f57`; also `--bg:#f5f7f8`→`#f4f6f8`,
  `--surface-2:#f7f9fa`→`#fbfcfd`, `--ink:#16232d`→`#15202b`, `--muted:#6b7883`→`#65727e`,
  `--line:#e5eaed`→`#e3e8ec`.
- `production/machine` **and** `development/connections` — `--font` omits `"Assistant"` (the Hebrew
  fallback) → add it so Hebrew renders identically to the other apps.
- `production/any-concurrency` — `--line:#e6eaee`→`#e3e8ec`; uses the radius var name `--r:16px` while
  every other app uses `--radius:16px` (rename to `--radius` when porting, or alias).
**All other apps already match the canonical set exactly — no change needed.**
**Not overridden at runtime (documented only, low value / higher risk):** the `--r`/`--radius` name
mismatch and the per-app dark-theme neutral hexes — normalize these directly in source during porting.

## A2 · One icon pack (Lucide-style stroke SVG), emojis-as-icons removed
**Sim change:** `sim/overlay/icons.js` replaces pictographic emoji glyphs with inline SVG icons from a single
Lucide-style set (24×24, `stroke=currentColor`, `stroke-width=2`, `fill=none`) — the same visual family
localdrive/wadmin/console already use. Done at runtime via a text-node walker + MutationObserver; the
match regex tolerates a trailing VS16 (`U+FE0F`) so `⚙️`/`✉️` are handled the same as their bare forms.

**Complete emoji→icon map (authoritative porting spec — replace each glyph with the named Lucide icon
in the source noted). Verified against a full glyph sweep of every app's real source:**

| emoji | Lucide icon | source location(s) to edit |
|---|---|---|
| 📥 | inbox | `production/mailview/static/index.html` |
| 🚨 | triangle-alert | `production/mailview/static/index.html` |
| 🏷 | tag | `production/mailview/static/index.html` |
| 📎 | paperclip | `production/mailview/static/index.html` |
| 🎉 | sparkles | `production/mailview/static/index.html` |
| 🔔 | bell | `production/notifications/static/index.html` |
| 🐛 | bug | `production/notifications/static/index.html` |
| 🧾 | receipt | `production/notifications/static/index.html` |
| 🔄 | refresh-cw | `production/notifications/static/index.html` |
| 💬 | message-circle | `production/notifications` + `production/any-concurrency` (ICON map) |
| 📄 | file-text | `production/notifications` + `production/any-concurrency` (ICON map) |
| 📁 | folder | mailview, notifications, incoming |
| 🔍 / 🔎 | search | notifications, mailview |
| 🔀 | shuffle | `production/any-concurrency/static/index.html:160` (ICON.n8n) |
| 🌐 | globe | `production/any-concurrency/static/index.html:160` (ICON.traefik) |
| 📦 | box | `production/any-concurrency/static/index.html:160` (ICON.docker) |
| 🪝 | webhook | `production/any-concurrency/static/index.html:160` (ICON.webhook) |
| 📝 | file-pen | `production/any-concurrency/static/index.html:160` (ICON.logspan) |
| ✉ / ✉️ | mail | `production/any-concurrency/static/index.html:160` (ICON.gmail) |
| ⚙ / ⚙️ | settings | `any-concurrency` (ICON.custom) + `development/feature-validation/api/dashboard.html` |

**Scope note:** semantic text glyphs (→ ← ↑ ↓ ✓ ✕ ✅ ⚠ ☰ ↗ ↻ ↺ ⌕ ↩ ✎) are intentionally LEFT as-is —
they are directional/status/affordance marks, not brand icons, and swapping them is higher-risk with no
consistency gain. Verified present-and-untouched by the sim QA.

## A3 · any-concurrency: canvas-drawn icons need a source-level fix (sim cannot reach them)
**Finding:** `production/any-concurrency/static/index.html` renders its `ICON` glyphs two ways —
(a) into DOM chips/detail panels (line ~226/368), which `sim/overlay/icons.js` DOES normalize, and
(b) onto a `<canvas>` via `ctx.fillText(ICON[src] + …)` (line ~287) for the live timeline lane labels.
**Sim limitation:** a DOM text-walker cannot rewrite canvas raster text, so the timeline's per-lane
emoji labels are the one place a pictographic glyph can still paint in the sim.
**Port (real source):** when the ICON map is converted to the icon pack (see A2), also change the canvas
label drawing — either draw the SVG/icon-font glyph with `ctx`, or drop the icon from the canvas label
and rely on the lane's DOM icon. This removes the last emoji surface with no sim workaround needed.

---
_Newest entries above this line._
