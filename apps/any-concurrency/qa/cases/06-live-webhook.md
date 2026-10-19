# QA — 06: Live WebSocket & Webhook Round-Trip

URL: `https://any-concurrency.hacohen.bina-solutions.co.il/`

---

## TC-LIVE-01 — WebSocket connection established

**Steps:**
1. Open browser DevTools → Network → WS filter.
2. Reload the page.
3. Find the `/ws` connection.

**Expected:**
- `/ws` connection shows status `101 Switching Protocols`
- A `{"type":"hello","t":...}` message is received within 2 seconds
- Regular `{"type":"ping"}` messages arrive every ~30 seconds

---

## TC-LIVE-02 — Webhook span appears live in the Gantt

**Steps:**
1. Open the dashboard.
2. Ensure `#followBadge` shows `↪ follow`.
3. In a new terminal / curl, POST to `/ingest/span`:
   ```json
   {"id":"qa-live-001","src":"qa","svc":"live-test","label":"QA live round-trip","s":NOW_MS,"e":NOW_MS+2000,"status":"success"}
   ```
4. Watch the Gantt canvas.

**Expected:**
- A new green bar appears in the Gantt within 2 seconds of the POST
- It is labelled `qa` or `live-test`
- No page reload was needed

---

## TC-LIVE-03 — Open span shows as running then closes live

**Steps:**
1. POST `/ingest/span`:
   ```json
   {"id":"qa-live-002","src":"qa","svc":"open-span","s":NOW_MS,"status":"running"}
   ```
2. Observe the Gantt — a running (pulsing right edge) bar appears.
3. POST `/ingest/span/qa-live-002/close` with `{"status":"success"}`.
4. Observe the Gantt.

**Expected:**
- Step 2: bar visible with no right cap (open / running)
- Step 4: bar updates in-place to have a right cap (closed / success)

---

## TC-LIVE-04 — URL state persists across reload

**Steps:**
1. Apply a filter: select `error` status, set window to `30m`.
2. Copy the current URL (includes hash).
3. Open a new tab and paste the URL.

**Expected:**
- New tab loads with the same filters applied:
  - Window = 30m
  - Status = error
- URL hash matches the original
