# The web engine — a slow, human-gated web UI as a backend

**Where it lives:** `apps/domains/webengine.py` (cache + jobs + change feed), `apps/domains/browser_session.py`
(the office browser over MCP), `apps/domains/portal.py` (per-provider script + reader).
**Status:** in production use by `apps/domains` since 2026-09-25, driving the Internic registrar panel
end to end. Written to be lifted into any app whose backend is *somebody else's web page*.

## The problem, stated once

A registrar with no API still has to be read and written by something. The office does it through its
own Chromium (browser42), driven over MCP. That link is slow (10–40s a page), shared with a human, and
occasionally absent. Three failures follow from that, and each has exactly one answer here:

| Failure | Answer |
|---|---|
| A screen that waits 40s is unusable | **read fast, refresh behind** (`webengine.get`, SWR) |
| A 40s action on one HTTP connection looks hung | **an action is a JOB** (`webengine.submit` + SSE) |
| Ten screens asking at once = ten browser runs | **single-flight** per key, per intent |

## 1 · Resources: stale-while-revalidate, with a version guard

```python
out = webengine.get(key, loader, ttl=180, force=fresh, want="cache" | "fresh")
# → {"value":…, "age":…, "stale":…, "refreshing":…, "state":"ok"|"error", "error":…}
```

* `want="cache"` **never blocks**: it returns the stored value however old, and refreshes in a
  background thread. That is why the domains screen paints immediately even when the panel is slow.
* One loader runs per key at a time (`_inflight`): ten open screens cause one fetch.
* Every write bumps a per-key **version**; a loader that started before a newer value landed has its
  result *dropped* (`superseded`). Without this, a 40-second read comes back and overwrites the fresh
  answer somebody just fetched by hand — the screen is then "correct" and wrong.
* A loader that RAISES keeps the previous value and marks the entry `state="error"`. **A failed read
  must never be stored as an empty result**: "this account has no domains" and "the browser did not
  answer" look identical on screen when you get this wrong, and only one of them is true.

## 2 · Jobs: the row is the API contract

```python
job = webengine.submit(name, fn, params, title=…, invalidates=["domain:…"], client=<token>)
# → {"id", "state": queued|running|ok|error|cancelled, "progress", "message", "log":[…]}
```

* `fn(progress, params)` runs on a worker; `progress(pct, message)` writes the row and publishes an
  event. A page reload, a closed tab or a crashed process keep the work — on startup every
  `queued`/`running` row is marked failed with *"the work stopped (the app restarted)"*, because a job
  that reads "running" forever is a screen that never finishes.
* **`client` is an idempotency token.** The same intent submitted twice (double-click, retry,
  re-sent request) joins the running job instead of performing the side effect twice. This is not an
  optimisation when the effect is *writing DNS for a live domain through a browser*.
* Progress is per STEP (`צעד 1 מתוך 3`), not a percentage that pretends to measure something.

## 3 · One change feed

`GET /api/events` (SSE) carries `{type: resource|invalidate|job}`. Open screens refresh exactly the
key that changed. Verified end to end in a real browser, not only with curl.

## 4 · The browser, treated as an unreliable dependency

* One shared session (`browser_session.shared()`), handshake made idempotent, fresh-session retry,
  **45s per call and 150s per flow** — the app fails fast and says `browser_unavailable` instead of
  holding a worker for minutes.
* **Extract IN the page.** Returning `document.body.innerText` moves megabytes over the MCP link into
  a Node process capped at 512MiB, which then dies of `Reached heap limit` (see
  `browser42-handoff-from-domains.md`). A read returns a few hundred bytes.
* **Poll for a completion predicate, never sleep-and-check.** "The URL is a zone page AND a record row
  exists" — ten tries, then a named failure. A fixed `wait_for(3)` is how an empty zone was read as
  the truth.
* **A human state is not an error**: `needs_human_login` hands over one link and stops. Nothing here
  automates a 2FA prompt or a CAPTCHA, and nothing retries a challenge — retrying is what escalates.
* **Be a good guest**: count tabs before a click and close only the tab you can prove you opened;
  leave the browser where you found it.

## 5 · Filters and gates on the way out

* FastAPI runs `async def` endpoints **on the event loop**. Every route that touches the vault, a
  provider or the browser parses its body with `await _json_body(request)` and then runs the work in
  `run_in_threadpool` — otherwise a slow read freezes the health check and the progress stream too.
* What the app will not do is scripted, not implied: `portal.WRITE_OPS` maps create/update/delete to
  the script's own operation names, and a missing one is refused with the sentence saying what to
  observe next. Money and irreversible operations need `confirm: "<domain>:<op>"`, an exact string.

## What is generic here, and what is not

**Generic** (lift as-is): `webengine.py`, `browser_session.py`, the drawer/diff/typed-delete UI
vocabulary, the job contract.
**Per-site** (a script, not a code change): the paths, the locators, the extraction, the status gate —
`portal.py`'s `SCRIPTS`, plus `paths` and the reader. Adding a site = adding a script entry and a read.

Two things this engine deliberately does NOT do, because they are the line between automating a
client's own account and evading a platform: **it never automates a human-presence check**, and it
**never retries past a challenge**.
