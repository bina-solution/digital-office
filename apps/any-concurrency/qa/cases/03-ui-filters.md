# QA — 03: Filters

URL: `https://any-concurrency.hacohen.bina-solutions.co.il/`

---

## TC-UI-F01 — Source pill toggles off a source

**Steps:**
1. Note initial Gantt row count.
2. Click the `traefik` source pill.
3. Observe the Gantt.
4. Click `traefik` pill again to re-enable.

**Expected:**
- After step 2: `traefik` pill gains `off` class; traefik rows disappear from Gantt
- After step 4: traefik rows return
- URL hash updates to reflect the changed `src=` state

---

## TC-UI-F02 — Window selector narrows the view

**Steps:**
1. Select `5m` from the Window dropdown (`#fHours`).
2. Read the view range text below the toolbar.

**Expected:**
- View range shrinks to ~5 minutes
- Row count may decrease (fewer spans in 5m)
- Select `1h` to restore.

---

## TC-UI-F03 — Service filter narrows rows

**Steps:**
1. Open the Service dropdown (`#fSvc`).
2. Select any non-`(all)` service.
3. Observe the Gantt.

**Expected:**
- Only rows matching that service are visible
- Empty-hint appears if no rows remain
- Resetting to `(all)` restores all rows

---

## TC-UI-F04 — Status filter: error only

**Steps:**
1. Open the Status dropdown (`#fStatus`).
2. Select `error`.
3. Observe the Gantt.

**Expected:**
- Only red (error) spans visible
- Count badge shows reduced numbers

---

## TC-UI-F05 — Search box filters by text

**Steps:**
1. Type a known workflow name fragment (e.g. `Batch`) into `#fSearch`.
2. Observe the Gantt.

**Expected:**
- Only rows whose label/svc/id contains `Batch` are shown
- Case-insensitive match

---

## TC-UI-F06 — All filters reset with reset view button

**Steps:**
1. Apply a status filter + search text.
2. Click `⌖ reset view` button.

**Expected:**
- Status filter returns to `(all)`
- Search field clears
- View window resets to default (1h)
- All rows visible again
