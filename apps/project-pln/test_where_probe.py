#!/usr/bin/env python3
"""where.sh's reachability probe, run as where.sh runs it (its own text, cut out of the file) against a local
server: a Plane whose web front answers while its backend hangs is NOT up — the hub is taken — and any HTTP
answer of the API itself, 401 included, is up (issues/plane-calls-hang-half-an-hour-when-the-office-that-runs-
plane-stalls.yaml, DGO-1848).

    python3 apps/project-pln/test_where_probe.py
"""
import http.server
import pathlib
import re
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
FAIL = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def probe_source() -> str:
    text = (HERE / "where.sh").read_text(encoding="utf-8")
    m = re.search(r"python3 -c '\n(.*?)\n' \"\$\{PLN_API\}\"", text, re.S)
    if not m:
        sys.exit("FAIL where.sh's probe was not found — the test reads it from the file, so the file changed shape")
    return m.group(1)


def serve(api_answer):
    """A local Plane: `/` answers 200 (the web front); the API answers `api_answer` — an HTTP code, or None
    to hang past the probe's timeout (a backend that does not answer)."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/"):
                if api_answer is None:
                    time.sleep(12)
                    return
                self.send_response(api_answer)
            else:
                self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def probe(api_answer) -> int:
    srv = serve(api_answer)
    try:
        return subprocess.run([sys.executable, "-c", probe_source(), f"http://127.0.0.1:{srv.server_port}"],
                              timeout=30).returncode
    finally:
        srv.shutdown()


check(probe(None) == 1, "a front that answers over a backend that hangs is not up (the hub is taken)")
check(probe(401) == 0, "the API's 401 without a key is a live Plane")
check(probe(200) == 0, "the API's 200 is a live Plane")
check(probe(502) == 1, "the link proxy's 502 for a dead tunnel is not up")
check(probe(504) == 1, "…nor its 504")
print("test_where_probe: OK" if not FAIL else "test_where_probe: FAILED")
sys.exit(1 if FAIL else 0)
