"""documents — the HTTP service (documents.v1): one list over the issued and the incoming documents (DGO-1630).

    GET  /healthz                 the process answers
    GET  /readyz                  every bound provider answers — through resolve(), the same door as the ops
    GET  /api/providers           op providers: who is bound, and each one's last sync in one Hebrew sentence
    GET  /api/types               op types: the document types (types.json — data, not code)
    GET  /api/documents           op list   ?direction=out|in &provider= &type= &q= &limit= &offset=
    GET  /api/documents/<id>      op get    the index row + the provider's own record (live)
    GET  /api/search?q=           op search one query over both directions
    POST /api/sync                op sync   {"provider": "local"|"indox", "accept_shrink": false}, or every bound one —
                                            reads only; a set half the size of the list is refused unless accepted

Every answer is {"ok": true, "op": …, "data": …}; a refusal is a 4xx/5xx with {"ok": false, "detail": "<Hebrew>"}.
The index syncs by itself every DOCUMENTS_SYNC_SECONDS (300). Events go to `dgo:flow:documents` through the
office's ONE publisher (platform-base/redis/flowpub.py, mounted read-only) and never block: a document is told once
per kind (issued / filed / needs review), a sync only when it changed something or failed — the stream is capped at
1000 entries, and a heartbeat every 5 minutes would push the documents out of it in two days.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import documents_core as core  # noqa: E402

try:                                                      # the office's one flow.v1 publisher (DGO-1402)
    sys.path.insert(0, "/opt/dgo")
    import flowpub  # noqa: E402
except ImportError:                                       # a test or a machine without it: no events, no failure
    flowpub = None

APP = "documents"
PORT = int(os.environ.get("DOCUMENTS_PORT", "8080"))
INDEX = core.Index(os.environ.get("DOCUMENTS_DB", "/data/documents.sqlite"))
TYPES = core.load_types()
SYNC_SECONDS = max(30, int(os.environ.get("DOCUMENTS_SYNC_SECONDS", "300")))
_sync_lock = threading.Lock()
EVENTS_PER_SYNC = 20


SYMBOL = {"ILS": "₪", "USD": "$", "EUR": "€", "GBP": "£"}


def _emit(type_: str, title: str, data: dict | None = None):
    if flowpub:
        flowpub.emit(APP, type_, title, data=data or {})


def _announce(rec: dict, kind: str):
    total = ""
    if isinstance(rec.get("total"), (int, float)):
        cur = rec.get("currency") or "ILS"
        total = f" · {SYMBOL.get(cur, cur + ' ')}{rec['total']:,.2f}"
    _emit(kind, f"{core.type_name(rec['type'], TYPES)} {rec['number']} · {rec['party'] or '—'}{total}",
          {"id": rec["id"], "provider": rec["provider"], "direction": rec["direction"]})


def run_sync(provider_id: str | None = None, accept_shrink: bool = False) -> list:
    with _sync_lock:
        providers = core.resolve(provider_id)
        before = {s["provider"]: (s["ok"], s["error"]) for s in INDEX.status()}
        report = core.sync(INDEX, providers, on_event=_announce, accept_shrink=accept_shrink, budget=EVENTS_PER_SYNC)
        after = {s["provider"]: (s["ok"], s["error"]) for s in INDEX.status()}
    # a failure is told when it STARTS (or says something new), and its end once — not every round: an office without
    # INDOX would otherwise push 288 failures a day into a stream of 1000
    fresh_bad = [r for r in report if not r["ok"] and before.get(r["provider"]) != after.get(r["provider"])]
    back = [r for r in report if r["ok"] and before.get(r["provider"], (1, ""))[0] == 0]
    moved = [r for r in report if r["ok"] and (r["added"] or r["changed"] or r["removed"])]
    if fresh_bad:
        _emit("documents.sync.failed", ("המסמכים: " + " · ".join(f"{r['provider']} לא סונכרן — {r['said']}"
                                                              for r in fresh_bad))[:300], {"report": report})
    if back:
        _emit("documents.sync.recovered", "המסמכים: " + " · ".join(f"{r['provider']} מסונכרן שוב" for r in back),
              {"report": report})
    if moved:
        _emit("documents.sync.changed", "המסמכים: " + " · ".join(
            f"{r['provider']} +{r['added']} ~{r['changed']} −{r['removed']}"
            + (f" (ועוד {r['events_dropped']} שלא נאמרו אחד-אחד)" if r.get("events_dropped") else "")
            for r in moved), {"report": report})
    return report


def _loop():
    time.sleep(3)
    while True:
        try:
            run_sync()
        except core.Refused as e:                         # no binding, or a provider the binding names that does not
            print(f"documents: no sync — {e.detail}", flush=True)   # exist: said every round, never silent
        except Exception as e:                            # noqa: BLE001 — the loop must outlive one bad sync
            print(f"documents: sync failed: {type(e).__name__}: {e}", flush=True)
        time.sleep(SYNC_SECONDS)


def _with_names(rows: list) -> list:
    for r in rows:
        r["type_name"] = core.type_name(r["type"], TYPES)
    return rows


class Door(BaseHTTPRequestHandler):
    server_version = "documents/1"

    def log_message(self, fmt, *args):                    # one line per request, nothing from the body
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def _send(self, code: int, body: dict):
        raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _ok(self, op: str, data):
        self._send(200, {"ok": True, "op": op, "data": data})

    def _route(self, method: str):
        url = urlsplit(self.path)
        path, q = url.path.rstrip("/") or "/", {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if method == "GET" and path == "/healthz":
                return self._send(200, {"ok": True})
            if method == "GET" and path == "/readyz":
                return self._readyz()
            if method == "GET" and path == "/api/providers":
                bound = core.binding()
                status = {s["provider"]: s for s in INDEX.status()}
                return self._ok("providers", [{"id": pid, "title": core.make(pid).title, "direction": core.make(pid).direction,
                                               "bound": pid in bound, "sync": status.get(pid)} for pid in core.PROVIDERS])
            if method == "GET" and path == "/api/types":
                return self._ok("types", TYPES)
            if method == "GET" and path == "/api/documents":
                rows = INDEX.list(q.get("direction"), q.get("provider"), q.get("type"), q.get("q"),
                                  q.get("limit", 100), q.get("offset", 0))
                return self._ok("list", {"rows": _with_names(rows), "status": INDEX.status(), "counts": INDEX.counts()})
            if method == "GET" and path.startswith("/api/documents/"):
                return self._get(unquote(path[len("/api/documents/"):]))
            if method == "GET" and path == "/api/search":
                return self._ok("search", {"rows": _with_names(INDEX.search(q.get("q", ""), int(q.get("limit", 50)))),
                                           "status": INDEX.status()})
            if method == "POST" and path == "/api/sync":
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 <= n <= 65536:                   # a negative length would block this thread on read(-1)
                    raise core.Refused("אורך גוף הבקשה לא תקין", 400)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    raise core.Refused("גוף הבקשה צריך להיות אובייקט JSON, למשל {\"provider\": \"indox\"}", 400)
                return self._ok("sync", run_sync(body.get("provider"), body.get("accept_shrink") is True))
            return self._send(404, {"ok": False, "detail": "אין דרך כזו באפליקציית המסמכים"})
        except core.Refused as e:
            return self._send(e.code, {"ok": False, "detail": e.detail})
        except ValueError as e:                           # a bad number or a body that is not JSON: the caller's
            return self._send(400, {"ok": False, "detail": f"בקשה לא תקינה: {e}"})
        except Exception as e:                            # noqa: BLE001 — ours: an answer, never an empty reply
            sys.stderr.write(f"documents: {method} {path}: {type(e).__name__}: {e}\n")
            return self._send(500, {"ok": False, "detail": "תקלה פנימית באפליקציית המסמכים — הפרטים ביומן שלה"})

    def _get(self, doc_id: str):
        row = INDEX.get(doc_id)
        if not row:
            raise core.Refused(f"אין מסמך «{doc_id}» ברשימה — אולי עוד לא סונכרן", 404)
        row["type_name"] = core.type_name(row["type"], TYPES)
        try:
            row["live"] = core.make(row["provider"]).document(row["ref"])
            row["live_said"] = ""
        except core.NotAtProvider as e:
            row["live"], row["live_error"] = None, str(e)
            row["live_said"] = f"הספק «{row['provider']}» כבר לא מכיר את המסמך הזה (אולי נמחק); זו השורה מהסנכרון האחרון"
        except ConnectionError as e:
            row["live"], row["live_error"] = None, str(e)
            row["live_said"] = f"הספק «{row['provider']}» לא ענה עכשיו; זו השורה מהסנכרון האחרון"
        return self._ok("get", row)

    def _readyz(self):
        try:
            providers = core.resolve()
        except core.Refused as e:
            return self._send(503, {"ok": False, "detail": e.detail})
        out, ok = [], True
        for p in providers:
            try:
                p.ping()
                out.append({"provider": p.id, "ok": True})
            except ConnectionError as e:
                ok = False
                out.append({"provider": p.id, "ok": False, "detail": str(e)})
        return self._send(200 if ok else 503, {"ok": ok, "providers": out})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


if __name__ == "__main__":
    threading.Thread(target=_loop, name="sync", daemon=True).start()
    print(f"documents: listening on :{PORT}, providers {core.binding() or 'NONE'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Door).serve_forever()
