"""A stand-in for the credential plane (`connections`), for tests and local development only.

Implements exactly the four instance endpoints this app calls (platform-service-contract.md §1):
GET/POST /api/instances, GET /api/instances/<id>/secret, DELETE /api/instances/<id>. It keeps
everything in memory and is never shipped (the Dockerfile copies the app's modules, not tests/).

    python3 tests/fake_vault.py 8990      # then CONNECTIONS_URL=http://localhost:8990
"""
from __future__ import annotations

import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):          # quiet
        pass

    def _send(self, code: int, body) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/instances":
            self._send(200, {"instances": [{k: v for k, v in i.items() if k != "secret"}
                                           for i in STORE.values()]})
        elif path.startswith("/api/instances/") and path.endswith("/secret"):
            cid = path.split("/")[3]
            inst = STORE.get(cid)
            self._send(200 if inst else 404, {"protocol": inst["protocol"], "secret": inst["secret"]}
                       if inst else {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/instances":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        cid = body.get("id") or f"{body.get('protocol')}-{secrets.token_hex(4)}"
        STORE[cid] = {"id": cid, "protocol": body.get("protocol"), "label": body.get("label") or "",
                      "account_hint": body.get("account_hint") or "", "status": "ok",
                      "created_at": int(time.time()), "secret": body.get("secret") or {}}
        self._send(200, {"id": cid})

    def do_DELETE(self):
        cid = self.path.rstrip("/").split("/")[-1]
        existed = STORE.pop(cid, None) is not None
        self._send(200 if existed else 404, {"ok": existed})


def serve(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8990).serve_forever()
