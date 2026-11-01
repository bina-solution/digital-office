# handoff — what `apps/domains` needs from `browser42` (and the evidence)

**From:** the domains-app session (Azaria). **To:** the browser42 session ("הפעלת דפדפן ופרסום פוסט").
**Date:** 2026-09-23. **Status:** the domains app drives the office browser for the registrar flow
(Internic has no API — see `apps/domains/AGENT.md`). The app side is finished and hardened; what is
missing is that the browser link be **rock solid**, as the owner asked.

## The interface I consume (please keep exactly this stable)

| | |
|---|---|
| endpoint | `http://browser42-caddy:80/mcp` (from `traefik-network`), `Authorization: Bearer $BROWSER42_MCP_TOKEN` |
| protocol | MCP JSON-RPC over HTTP (`initialize` → `notifications/initialized` → `tools/call`) |
| tools used | `browser_navigate`, `browser_evaluate`, `browser_click`, `browser_type`, `browser_take_screenshot`, `browser_wait_for`, `browser_tabs` |
| browser | the SHARED persistent profile (that is the whole point: the owner logs in once) |

## What breaks, with the exact strings (all observed 2026-09-23, from `domains-local`)

1. `tools/call` → **`TimeoutError: async initializeServer: Timeout 30000ms exceeded ... retrieving
   websocket url from http://browser42-browser:9222`** — the MCP server cannot reach the browser's
   CDP port. This is the one that kills the flow.
2. Caddy log: `aborting with incomplete response ... upstream browser42-mcp:8931 ... error: reading:
   context canceled` — the upstream abandons the request.
3. Caddy log: `dial tcp: lookup browser42-browser on 127.0.0.11:53: server misbehaving` — Docker's
   embedded DNS intermittently fails to resolve the browser from sibling containers.
4. MCP session lifecycle: `Bad Request: Server not initialized` on a live-looking session, and
   `Invalid Request: Server already initialized` when re-handshaking. (The app now recovers by
   dropping the session and opening a fresh one, and by treating "already initialized" as success —
   but the server should not be in that state after a normal container restart.)

Measured effect on the app: a portal flow that should take ~15s hangs; without the app-side budget it
held an API worker for minutes. I added a 150s run budget and a 45s per-call timeout, so the app now
fails fast and reports `browser_unavailable` — but the flow still cannot complete.

## What "stable" means for me (acceptance test)

From a sibling container on `traefik-network`, this must complete in **under ~10 s, repeatedly**:

```bash
docker exec -w /app domains-local python -c "
import browser_session as s, json
sess = s.Session(); print(json.dumps(sess.open('http://domains:8980/fixture/panel'), ensure_ascii=False)[:200])"
```

and then, end to end (this is the app's own test bench — a small DNS panel the app serves, so it needs
no credentials and no owner login):

```bash
curl -s -X POST http://domains:8980/api/browser/selftest   # → {"ok": true, ...}
```

That second call exercises the whole translation layer (read table → add record → verify → delete →
verify) through the real browser. It passed once today (the record was created and verified) and has
been failing since on the CDP timeouts above.

## What I would ask you to check, in order

1. That `browser42-browser:9222` (CDP) is reachable **from a sibling container** (`domains-local`,
   `sites-local`) and answers `/json/version`; today it answers from inside its own container but the
   MCP server times out reaching it.
2. That the MCP process does not accumulate sessions/websockets: it logged
   `MaxListenersExceededWarning: 11 unhandledRejection listeners added to [process]` after ~an hour
   of use, and the "context canceled" errors started around then. A restart clears it — so something
   is leaking per session.
3. That a fresh `initialize` on a NEW HTTP session always succeeds (not "Server already
   initialized"), so a caller that has just started can talk to the browser.

## What I do NOT need

No new surface, no REST API, no changes to the profile/clipboard/task machinery. The MCP endpoint
that exists is enough — it only has to answer, always and quickly.

---

## Update 2026-09-25 — the leak now has a name, and it is an OOM (evidence)

Ran the app's portal flow (zone read, 30 records, twice in a row — it works) and this is what the
`browser42-mcp` container did **in the middle of a working session**:

```
browser42-mcp-local  | FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
browser42-mcp-local  |  5: v8::internal::Heap::CollectGarbage(...)
browser42-mcp-local  | 10: [node]
browser42-mcp-local  | Aborted (core dumped)
browser42-mcp-local  | Listening on http://localhost:8931        ← restarted, ~8s later
```

Consequences, measured from `domains-local` at the same moment: `tools/call` (a plain
`browser_wait_for`) returned **HTTP 502** from Caddy and the app raised
`SessionError: הדפדפן החזיר 502`. So items 1–3 below are all downstream of ONE thing: **the MCP
process exhausts its heap, dies, and its container is restarted by `restart: unless-stopped`.**
Every symptom above — the 30s CDP initialize timeout, "context canceled", "Server not initialized",
the listener warning after an hour — is what a dying/restarting process looks like from outside.

Two configuration facts, both from the running stack:

| | |
|---|---|
| `browser42-mcp` memory limit | **512 MiB** (`docker inspect … HostConfig.Memory` = 536870912) |
| Node heap | default for that cgroup — no `NODE_OPTIONS` is set on the service |

So the ask is concrete and small:

1. **Give the process room and a bounded heap**: raise the service's memory limit (1 GiB is the
   container's swap figure today) and/or set `NODE_OPTIONS=--max-old-space-size=384` so V8 collects
   instead of aborting. An OOM kill is not a graceful failure: it drops every in-flight call.
2. **Find what grows per call.** The payloads are the suspects, and one is mine: `browser_evaluate`
   with `document.body.innerText` on a big admin page is a multi-megabyte string. I have already
   moved that extraction *into the page* (the app now returns ~50 domain names instead of the whole
   DOM text) — but `browser_take_screenshot` and `browser_snapshot` return large blobs too, and if
   they are retained per session the leak survives my fix. A `process.memoryUsage().heapUsed` log
   line per request, or a `/debug/heap` endpoint, would settle it in one session.
3. **Make the failure honest while it lasts**: if the MCP server is restarting, a call should answer
   `503` with `Retry-After`, not `502` with an empty body — that is the difference between a caller
   that backs off and a caller that reports "the browser is broken".

### What I changed on my side, so we are not chasing each other's ghosts

* the app's own reads are **idempotent and tab-clean**: a zone read counts the browser's tabs before
  it clicks and only closes the tab it can prove *it* opened, then puts the browser back on the
  domain list. Tested twice back to back: 30 records, one tab, no leftovers.
* a panel read that FAILS is never cached as "this zone has no records" — the last successful read is
  carried forward and marked stale, because an empty zone that looks normal is the one wrong answer a
  domains screen must never show.
* every flow still runs under the app's own budget (45s per call, 150s per flow) and reports
  `browser_unavailable` rather than hanging.
