# QA — 05: Gantt Canvas & Detail Panel

URL: `https://any-concurrency.hacohen.bina-solutions.co.il/`

---

## TC-UI-G01 — Gantt renders spans

**Steps:**
1. Load the page.
2. Wait for data load.
3. Inspect `#cGantt` canvas visually.

**Expected:**
- Canvas is non-blank (coloured bars visible)
- Multiple rows visible with source labels on the left gutter

---

## TC-UI-G02 — Click a Gantt row opens detail panel

**Steps:**
1. Click on any green or red bar in the Gantt canvas.
2. Observe the right-side detail panel (`#detail`).

**Expected:**
- `#detail` gains class `open` (slides in from right)
- Panel shows: span `id`, `src`, `svc`, `status`, start/end timestamps, duration
- Close button (`×`) is present

---

## TC-UI-G03 — Detail panel closes on × button

**Steps:**
1. With detail panel open (from TC-UI-G02):
2. Click the `×` close button inside the panel.

**Expected:**
- `#detail` loses `open` class; panel slides out
- Canvas returns to normal (no highlighted span)

---

## TC-UI-G04 — n8n span detail shows deep link [OPTIONAL]

**Pre-condition:** n8n source is active; `N8N_URL` is configured.

**Steps:**
1. Click on a purple (n8n) bar in the Gantt.
2. Read the detail panel actions.

**Expected:**
- A `Open in n8n` link is visible
- Link href contains the n8n base URL and execution ID

---

## TC-UI-G05 — Follow badge pauses on manual pan

**Steps:**
1. Confirm `#followBadge` shows `↪ follow`.
2. Click and drag the Gantt canvas leftward (pan back in time).
3. Read `#followBadge`.

**Expected:**
- Badge changes to `⏸ paused`
- Live updates no longer auto-scroll the view
- Clicking the badge again re-enables follow mode
