"""spans.py — this office's work items, as spans the ‏כל מקביל timeline can draw  (DGO-10)

    GET /timeline/spans?since=<unix_ms>   →   {"spans": [ … ]}

WHY IT LIVES IN THE APP. ‏כל מקביל shows one picture of "who is doing what, when"; a service that knows
WHEN something started and WHEN it ended beside the agent who did it belongs next to what it shows.
A task in Plane has exactly that shape — one work item, one actor, a start and an end — so the timeline
does not need Plane's database or its UI: it needs one honest feed, and this is it.

THE CONTRACT (frozen by the timeline session's comment on DGO-10, comment ee50afb8):

    {"spans": [{"id": <stable string>, "svc": "DGO-12 · הכותרת", "svcid": "<item uuid>",
                "label": "DGO-12", "status": "running|ok", "s": <unix ms>, "e": <unix ms|null>,
                "meta": {"project", "module", "assignees", "priority", "state"}}]}

* times are **unix milliseconds**; `e` is null while the span is open;
* `since` is **incremental**: only spans touched after that timestamp are returned, so a poller can
  ask for the delta;
* `svc` is "<ref> · <title>" and `svcid` is the item's uuid — one span per work item, not one per
  agent, because the ITEM is what the timeline draws a bar for.

WHERE THE TIMES COME FROM, stated plainly because it decides how much the picture can be trusted:
the item's own record. `completed_at` closes a finished span; an item still in a `started` state is
open from the moment of its LAST transition (Plane's `updated_at` for that state) — a transition
history is not exposed by the public API, so a span's start is exact for "how long has this been in
progress", and a project's past is not reconstructed retroactively. `meta.state` carries the way to
verify it: the state the item is in now.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PLANE_SPANS_PORT", "3006"))
BASE = (os.environ.get("PLANE_API_URL") or "http://127.0.0.1").rstrip("/")
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
WS = os.environ.get("PLANE_WORKSPACE") or "bina"
DEFAULT_PROJECTS = [p.strip() for p in (os.environ.get("PLANE_SPANS_PROJECTS") or "").split(",") if p.strip()]
CACHE_SECONDS = float(os.environ.get("PLANE_SPANS_CACHE", "30"))

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "spans": []}
_refreshing = threading.Event()          # one background rebuild at a time, however many pollers


def log(msg: str) -> None:
    print(f"[project-pln/spans] {msg}", flush=True)


def http(method: str, url: str, body=None, headers=None, tries: int = 4):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            return (json.loads(raw) if raw.strip() else {}), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                time.sleep(4 * (attempt + 1))
                continue
            return {"error": e.read().decode("utf-8", "replace")[:200]}, e.code
        except Exception as e:                                       # noqa: BLE001
            if attempt < tries - 1:
                time.sleep(2)
                continue
            return {"error": f"{type(e).__name__}: {e}"}, -1
    return {"error": "giving up"}, -1


def token() -> str:
    tok = os.environ.get("PLANE_LOCAL_API_TOKEN")
    if tok:
        return tok
    out, code = http("GET", f"{VAULT}/api/instances/plane_local_api_token-local/secret")
    sec = (out or {}).get("secret") or {}
    if not sec.get("token"):
        log(f"no API key from the credential plane (HTTP {code})")
        return ""
    return sec["token"]


def ms(value) -> int | None:
    """Plane's timestamps are ISO-8601 with an offset; the contract wants unix milliseconds."""
    if not value:
        return None
    try:
        import datetime
        return int(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:                                                # noqa: BLE001
        return None


def page(key: str, path: str) -> list | None:
    """Every page, transparently — or `None` when Plane could not be read at all.

    `None` and `[]` are different answers and the difference is the whole reason this returns one:
    an empty list means "Plane says there is nothing here", `None` means "I could not ask". Caching
    the second as if it were the first is how a slow API turns into a timeline that reads "nothing
    is happening" — measured 2026-10-01, when a loaded engine made `/projects/` answer in 71s while
    the request timeout was 20s and the endpoint reported zero spans with a straight face.
    """
    sep = "&" if "?" in path else "?"
    out, code = http("GET", f"{BASE}/api/v1/workspaces/{WS}{path}{sep}per_page=100",
                     headers={"X-API-Key": key})
    if code not in (200, 201):
        return None
    if not isinstance(out, dict):                                    # a body we cannot read
        return None
    rows = list(out.get("results") or [])
    while out.get("next_page_results") and out.get("next_cursor"):
        out, code = http("GET", f"{BASE}/api/v1/workspaces/{WS}{path}{sep}per_page=100"
                                 f"&cursor={out['next_cursor']}", headers={"X-API-Key": key})
        if code not in (200, 201) or not isinstance(out, dict):
            break
        rows += list(out.get("results") or [])
    return rows


def build(since_ms: int | None) -> list | None:
    key = token()
    if not key:
        return None
    spans: list = []
    projects = page(key, "/projects/")
    if projects is None:
        return None
    wanted = [p for p in projects if not DEFAULT_PROJECTS or p.get("identifier") in DEFAULT_PROJECTS]
    for proj in wanted:
        pid, P = proj["id"], f"/projects/{proj['id']}"
        # A read that could not happen makes the WHOLE build unusable, not just that project: measured
        # 2026-10-01, one project's issue page timed out at 60s and the endpoint answered ONE span
        # (the other project's) with a straight face — a partial timeline is read as "the work
        # stopped", which is worse than serving the previous complete one.
        raw_states = page(key, f"{P}/states/")
        raw_modules = page(key, f"{P}/modules/")
        raw_items = page(key, f"{P}/issues/?expand=labels,assignees")
        if raw_states is None or raw_modules is None or raw_items is None:
            return None
        states = {s["id"]: s for s in raw_states}
        modules = {m["id"]: m.get("name", "") for m in raw_modules}
        for it in raw_items:
            st = states.get(it.get("state")) or {}
            group, state_name = st.get("group", ""), st.get("name", "")
            if group not in ("started", "completed"):
                continue                      # only work that is in progress or finished has a bar
            start = ms(it.get("updated_at") if group == "started" else it.get("start_date")
                       or it.get("created_at"))
            end = ms(it.get("completed_at")) if group == "completed" else None
            if end is None and group == "completed":
                end = ms(it.get("updated_at"))
            if start is None:
                continue
            if since_ms and max(start, end or 0) < since_ms:
                continue                      # incremental: nothing about this item changed since
            ref = f"{proj['identifier']}-{it.get('sequence_id')}"
            mod = next((modules.get(m if isinstance(m, str) else m.get("module_id") or m.get("id"), "")
                        for m in (it.get("module_ids") or [])), "")
            who = [a.get("display_name") or a.get("email") or "" for a in (it.get("assignees") or [])
                   if isinstance(a, dict)]
            spans.append({"id": f"{proj['identifier']}:{it['id']}:{group}",
                          "svc": f"{ref} · {it.get('name', '')}",
                          "svcid": it["id"], "label": ref,
                          "status": "running" if group == "started" else "ok",
                          "s": start, "e": end,
                          "meta": {"project": proj["identifier"], "module": mod,
                                   "assignees": [w for w in who if w], "state": state_name,
                                   "priority": it.get("priority") or "none",
                                   "url": f"{BASE}/{WS}/projects/{pid}/issues/{it['id']}"}})
    return spans


def _refresh() -> list:
    """Rebuild the snapshot and store it. Runs on the request thread for the FIRST call, and on a
    background thread afterwards, so a slow Plane never makes the timeline wait (see `cached`).

    A build that could not read Plane (`None`) does NOT become the snapshot: the previous one is
    kept, timestamp and all, so the next caller tries again instead of being told "no work" for a
    cache period by a read that failed."""
    spans = build(None)
    if spans is None:
        with _lock:
            return _cache["spans"]
    with _lock:
        _cache.update(at=time.time(), spans=spans)
    return spans


def cached(since_ms: int | None) -> list:
    """The snapshot now, a rebuild behind it — and the `since` filter never triggers a refetch.

    Measured 2026-10-01 on the loaded office engine: one full build is ~17s of Plane API calls and a
    single call has been seen at 71s, so the old shape had two failures at once — a poller asking
    `since=<last>` rebuilt the whole estate on every tick (the delta is a FILTER over the same list,
    not a cheaper read), and when a call timed out the answer was `{"spans": []}`, which reads as
    "nothing is happening" rather than "the read failed". Stale-but-real beats empty-but-fast: the
    last good snapshot is served while a background thread refreshes it, and only the very first
    call after a restart waits for Plane.
    """
    with _lock:
        have = _cache["at"] > 0
        age = time.time() - _cache["at"]
        spans = _cache["spans"]
    if not have:
        spans = _refresh()
    elif age >= CACHE_SECONDS and not _refreshing.is_set():
        _refreshing.set()
        threading.Thread(target=lambda: (_refresh(), _refreshing.clear()), daemon=True).start()
    if since_ms:
        spans = [s for s in spans if max(s["s"], s["e"] or 0) >= since_ms]
    return spans


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):                                                # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") not in ("/timeline/spans", ""):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        try:
            since = int(q["since"][0]) if q.get("since") else None
        except (ValueError, IndexError):
            since = None
        try:
            spans = cached(since)
            body = json.dumps({"spans": spans}, ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as e:                                       # noqa: BLE001
            body = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):                                       # quiet: Caddy logs the requests
        pass


def main() -> int:
    log(f"serving /timeline/spans on :{PORT} for workspace {WS}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
