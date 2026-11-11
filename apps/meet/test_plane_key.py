"""test_plane_key — meet-start asks Plane with the office's own key, read from the vault (DGO-1649).

A fake vault on loopback answers `GET /api/instances/<id>/secret` as the credential plane does. meet-start's
`_plane_key` reads the key from it only when MEET_PLANE_KEY_VAULT names an instance, holds it five minutes, keeps the
last key when the vault does not answer, and lets a key written in .env (MEET_PLANE_API_KEY) win; `_plane_headers`
carries it as X-API-Key. Run: python3 apps/meet/test_plane_key.py   (stdlib only)
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import threading
from pathlib import Path

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


ASKED: list[str] = []
STATE = {"token": "k-1", "up": True}


class Vault(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ASKED.append(self.path)
        if not STATE["up"]:
            self.send_response(503)
            self.end_headers()
            return
        if self.path == "/api/instances/plane_local_api_token-local/secret":
            body = json.dumps({"secret": {"token": STATE["token"], "base_url": "http://project-pln:80"}}).encode()
            self.send_response(200)
        else:
            body = b'{"detail":"no such instance"}'
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main() -> int:
    if sys.version_info < (3, 10):
        # server.py is meet-start's, written for its image (python:3.12-alpine; `float | None` in its signatures):
        # G72's word for a test that needs its own image is NOT RUN — then it is run there (--in-images)
        print("No module named 'server' on this interpreter: meet-start's server.py needs Python 3.10+ (its image)")
        return 1
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Vault)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ.update(MEET_PLANE_KEY_VAULT="plane_local_api_token-local", CONNECTIONS_URL=f"http://127.0.0.1:{port}",
                      MEET_PLANE_API_KEY="", MEET_PLANE_API_URL="http://project-pln:80")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "start"))
    import server  # noqa: E402  (a helper's import: the server runs only as __main__)

    t0 = 1_800_000_000.0
    check(server._plane_key(t0) == "k-1", "the key is read from the vault instance the hook named")
    check(ASKED == ["/api/instances/plane_local_api_token-local/secret"], f"…asked once, at its own path: {ASKED}")
    STATE["token"] = "k-2"
    check(server._plane_key(t0 + 60) == "k-1" and len(ASKED) == 1, "held for five minutes: no second ask in a minute")
    check(server._plane_key(t0 + server.VAULT_KEY_TTL + 1) == "k-2" and len(ASKED) == 2,
          "after five minutes the vault is asked again (a rotated key arrives)")
    STATE["up"] = False
    check(server._plane_key(t0 + 2 * server.VAULT_KEY_TTL + 2) == "k-2",
          "a vault that does not answer keeps the last key it gave")
    check(server._plane_headers({"Accept": "application/json"}).get("X-API-Key") == "k-2",
          "the key travels as X-API-Key on every call to Plane")
    asked = len(ASKED)
    server.PLANE_API = "http://plane.hp-laptop:9003"
    check(server._plane_key(t0 + 3 * server.VAULT_KEY_TTL) == "" and len(ASKED) == asked,
          "an address an operator pointed at another office's Plane never gets this office's own key")
    server.PLANE_API = "http://project-pln:80"
    server.PLANE_KEY = "from-env"
    check(server._plane_key(t0) == "from-env", "a key written in .env (EXF's way) wins over the vault")
    server.PLANE_KEY, server.PLANE_KEY_VAULT = "", ""
    server._vault_key.update(at=0.0, key="")
    check(server._plane_key(t0) == "" and "X-API-Key" not in server._plane_headers({}),
          "no key and no vault instance: no header (a herd office's link door signs the call in)")
    srv.shutdown()
    if FAIL:
        print(f"{len(FAIL)} check(s) failed")
        return 1
    print("test_plane_key: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
