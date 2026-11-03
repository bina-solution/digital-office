# QA — 04: Controls & Toggles

URL: `https://any-concurrency.hacohen.bina-solutions.co.il/`

---

## TC-UI-C01 — Reload button fetches fresh data

**Steps:**
1. Note the current total span count in the stats row.
2. Click `↻ reload`.
3. Wait for the button to stop animating.

**Expected:**
- Stats row updates (count may change if new spans arrived)
- No JS errors thrown
- `#liveBadge` remains `on`

---

## TC-UI-C02 — Expand button opens all groups

**Steps:**
1. Click `expand` button.
2. Observe the Gantt — rows should expand to show individual task spans.

**Expected:**
- Group headers now show child rows expanded
- Gantt height increases

---

## TC-UI-C03 — Collapse button folds all groups

**Steps:**
1. Click `collapse` button.
2. Observe the Gantt.

**Expected:**
- All children hidden; only source group headers visible
- Gantt height decreases

---

## TC-UI-C04 — Log Y toggle changes concurrency chart scale

**Steps:**
1. Check current state of `#logY` checkbox (should be unchecked = linear).
2. Click the `log Y` checkbox.
3. Observe the concurrency bar chart (`#cConc`).

**Expected:**
- Y axis scale changes to logarithmic (bars appear shorter for large values)
- Toggle off restores linear scale

---

## TC-UI-C05 — Incident markers toggle

**Steps:**
1. Note red vertical lines in the Gantt (incident markers, `#showIncidents` checked).
2. Uncheck `incident markers`.

**Expected:**
- Red vertical markers disappear from the canvas
- Re-checking makes them reappear

---

## TC-UI-C06 — Group by source toggle

**Steps:**
1. Uncheck `group by source` (`#groupBySrc`).
2. Observe the Gantt row labels.

**Expected:**
- Rows are no longer grouped under N8N/TRAEFIK/DOCKER headers
- Flat list sorted by start time

---

## TC-UI-C07 — Hide <50ms toggle

**Steps:**
1. Check `hide <50ms` checkbox (`#hideShort`).

**Expected:**
- Very short spans disappear from the Gantt
- Stats count may decrease

---

## TC-UI-C08 — Zoom buttons change time scale

**Steps:**
1. Click `+` zoom-in button (id `zIn`).
2. Read the view range text.
3. Click `−` zoom-out button.
4. Click `⌖` fit button (id `zFit`).

**Expected:**
- `+` narrows the time window
- `−` widens it
- `⌖` resets to default fit
