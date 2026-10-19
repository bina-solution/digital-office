# QA — 02: UI Page Load & Header

URL: `https://any-concurrency.hacohen.bina-solutions.co.il/`

---

## TC-UI-H01 — Page loads without errors

**Steps:**
1. Navigate to the dashboard URL.
2. Wait for the page title to appear.
3. Check browser console for errors.

**Expected:**
- Page title = `any-concurrency`
- `<h1>` contains `any-concurrency`
- No JS errors in console (warnings OK)
- Canvas elements present: `#cConc`, `#cBrush`, `#cGantt`

---

## TC-UI-H02 — Health badge shows sources online

**Steps:**
1. Wait 3 seconds after page load.
2. Read the `#health` span text.

**Expected:**
- At least n8n, traefik, docker show `on` (bold, not grayed)
- No source shows `off` for n8n/traefik/docker

---

## TC-UI-H03 — Live badge goes green (WebSocket connects)

**Steps:**
1. Load the page.
2. Wait up to 5 seconds.
3. Read `#liveBadge` class and text.

**Expected:**
- `#liveBadge` class contains `on` (not `off`)
- Text is `● live`

---

## TC-UI-H04 — Stats row shows span counts

**Steps:**
1. Wait for initial data load (reload button stops spinning).
2. Read `#stats` div content.

**Expected:**
- Contains at least one count badge (e.g. `n8n 1234`)
- `total` count is > 0
- `p50`, `p95`, `p99` latency values are present
