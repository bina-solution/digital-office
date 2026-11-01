# Operating `domains`

The office's domain accounts and the domains inside them. Two levels, and that is the whole model:

```
account  ──►  the domains of that account  ──►  one domain's settings
```

An **account** is a connection in the credential plane: an **API account** (GoDaddy, Cloudflare,
Plesk, Porkbun, DigitalOcean, Gandi, Hetzner) or a **BROWSER account** — a session the owner logged
into once in the office's own Chromium, the only door a registrar with no API has. Nothing above
`accounts.py` knows which kind it is talking to, and that is what makes the screens identical whether
the control behind them is an HTTP endpoint or a button in someone's panel.

`GET /ops` lists the canonical ops other apps call; `GET /providers` is the catalogue the "add
account" screen is built from. Per domain: `POST /records`, `POST /op`, `GET /health`,
`GET /activity`, `POST /activity/{id}/revert`.

## The browser flow (one call, three answers)

`POST /api/accounts/browser {"provider":"portal"}` returns `step`:

* `needs_human_login` — the panel is on a login screen; the response carries `live_view`
  (`/a/browser42/`) and the URL. The owner logs in there ONCE and the screen polls this endpoint
  until it flips. No password is ever typed into this app.
* `connected` — the office read the account's own domain list as proof of control, and the response
  carries the evidence (the names it saw). Only then is the connection stored.
* `browser_unavailable` / `login_failed` / else — named. A browser fault must never be reported as a
  login failure: that sends the owner to a page that is already logged in.

## Verified facts (live, 2026-09-23/25)

* Registrar **InterSpace Ltd (Internic)**; `portal.internic.co.il` is behind Imperva — a non-JS client
  gets **HTTP 200 with a 212-byte JS challenge**, which is why this needs a real browser and why a
  naive check reads failure as success.
* The panel's data is at **`/dashboard/main`** (`/domains` 404s). The zone editor is per-domain at
  `/zone/<id>`, reached by ticking the row and clicking `zone-edit` (marked `visually-hidden`).
* **A zone row is identified by its FIELD NAMES, not by position**: a record row has
  `select[name=rectype_<n>]` AND `input[name=specs_<n>]`; `<n>` is the TYPE's index (six CNAME rows
  all carry `rectype_1`), so the row's ordinal is the only identity there is. Every other row with a
  type select is a TEMPLATE (the add-record form, the SRV priority/weight/port/target sub-rows).
  Reading those positionally invented an apex A at 80.244.162.32 that no resolver ever answered —
  **24–36 records looked plausible; 30 are real**. The editor renders after the click, so the read
  POLLS for a completion predicate (a zone URL AND a record row) instead of sleeping once. The click
  may open a NEW TAB: count tabs first, close only the one you can prove you opened, leave the
  browser back on the domain list.
* The **zone is NOT at Internic**: `ns1/ns2.sitesdepot.com` is a Plesk Obsidian box of **InterVision**
  whose REST API is live but refuses callers **by IP** (`403 Access to API is disabled for <IP>`). An
  API key + our IP on their allowlist unlocks full DNS read/write via the `plesk` provider; the
  alternative is moving delegation to Cloudflare.
* **The panel is not the whole zone**: a type the world answers but the panel does not render (here
  `facebook-domain-verification`) is reported as `world_only`, never as a missing record.
* Registry expiry is public over `whois.isoc.org.il:43`, watched hourly.

## The engine and the screens (2026-09-25)

* `webengine.py` is a **generic** engine, reusable by any app with a slow source: SWR resources,
  jobs whose ROW is the API contract, and one SSE change feed. `submit(client=…)` is an idempotency
  token: the same intent twice joins the running job instead of writing twice.
* **Every route that blocks runs in the threadpool** (`run_in_threadpool`). FastAPI runs an
  `async def` endpoint ON the event loop, so a 40s panel read written there freezes the whole app —
  health check and progress stream included. That failure mode is total.
* Screens: **accounts → domains → one domain** (`overview | records | health | ops | activity`).
  A record is edited in a **drawer** (`#/a/<aid>/d/<name>/records/<key>`, ONE Save, live diff,
  client-side rules mirroring the server's, typed `מחיקה` to delete). `/activity` lists every change
  with before/after and an undo.
* **A failed read is never cached as truth**: it keeps the last successful list and marks it stale
  (`records_stale`, `_cache.state=error`). An empty zone that looks normal is the one wrong answer
  this app must not show.

## Traps

* **A panel write script must be `verified`.** The flow past the login was observed; the WRITE has
  not been watched end to end, so portal `create/update/delete` refuse with `needs_verification`
  until a human sees it work once (`allow_draft_write: true` is that consent). Which script operation
  writes a record is the SCRIPT's business (`portal.WRITE_OPS`) — this panel uses one form for create
  and update and defines no delete, and the refusal says exactly that.
* **Money and irreversible ops need an exact confirmation**: `confirm: "<domain>:<op>"`, not `true`.
* **`PUT /v1/domains/{d}/records` at GoDaddy replaces the WHOLE ZONE** — never issued here.
* **WHOIS is a shared service**: each domain at most every `DOMAINS_WHOIS_HOURS` (12), one at a time.
* **The office browser is shared with the owner.** Keep MCP payloads small — extract IN the page and
  return a few hundred bytes, not the page's text.
* **The browser MCP dies of a heap OOM** (512MiB limit, no `NODE_OPTIONS`) and restarts; that is what
  every `browser_unavailable` here actually is (`FATAL ERROR: Reached heap limit`). Evidence:
  `ai/context/browser42-handoff-from-domains.md`.
* `/_internal/…` routes are diagnostics for the translation layer, not a product surface.
