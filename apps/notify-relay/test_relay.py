#!/usr/bin/env python3
"""test_relay — a board-less office's notices reach the hub's board, in order, and none is lost (DGO-2111, root 2).

A fake hub (a real HTTP server on a free port) stands for the HP's board over the link; the compiled record that names
its door is written into a temp registry. Proven: a notice is carried and the hub's answer is the poster's; with the
hub down it is kept and answered 202; a later notice joins the queue rather than overtaking it; the kept ones are sent
in order when the hub returns; a 4xx is the hub's refusal, said back, never kept for ever; no record means kept.

Run: python3 apps/notify-relay/test_relay.py   (stdlib only)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="notify-relay-"))
os.environ.update(NOTIFY_RELAY_REGISTRY=str(TMP / "registry"), NOTIFY_RELAY_SPOOL=str(TMP / "spool.jsonl"),
                  NOTIFY_RELAY_HUB="hp-laptop", NOTIFY_RELAY_TIMEOUT_S="2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay  # noqa: E402

GOT: list = []
HUB = {"up": True, "status": 201}


class Hub(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        GOT.append(body)
        out = json.dumps({"id": len(GOT), "created": True}).encode()
        self.send_response(HUB["status"])
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def main() -> int:
    fails: list[str] = []
    hub = ThreadingHTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    (TMP / "registry").mkdir()
    record = TMP / "registry" / "remote.hp-laptop.alerts.json"
    record.write_text(json.dumps({"door": {"base": f"http://127.0.0.1:{hub.server_port}"}}))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/api/notifications",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    s, b = post({"source": "machine", "source_id": "disk-low", "title": "a"})
    if not (s == 201 and GOT and GOT[-1]["source_id"] == "disk-low"):
        fails.append(f"a notice is carried, the hub's answer is the poster's: {s} {b} {GOT}")
    record.write_text(json.dumps({"door": {"base": "http://127.0.0.1:9"}}))   # the hub stops answering
    s1, b1 = post({"source": "machine", "source_id": "down", "title": "b"})
    record.write_text(json.dumps({"door": {"base": f"http://127.0.0.1:{hub.server_port}"}}))   # it is back…
    s2, _ = post({"source": "machine", "source_id": "up", "title": "c", "resolves": ["down"]})
    if not (s1 == 202 and b1.get("queued") and s2 == 202):
        fails.append(f"hub down: kept (202); a later one joins the queue, never overtakes it: {s1} {b1} {s2}")
    n = len(GOT)
    sent = relay.spool_flush()
    if not (sent == 2 and [g["source_id"] for g in GOT[n:]] == ["down", "up"] and not relay._kept()):
        fails.append(f"the kept ones go in order when the hub answers: sent={sent} {GOT[n:]} kept={relay._kept()}")
    HUB["status"] = 400
    s, _ = post({"source": "x", "title": "refused"})
    if not (s == 400 and not relay._kept()):
        fails.append(f"a 4xx is the hub's refusal, said back and never kept: {s} kept={relay._kept()}")
    HUB["status"] = 429                        # the way's 4xx: kept, never lost
    s, _ = post({"source": "x", "source_id": "rl", "title": "rate limited"})
    if not (s == 202 and len(relay._kept()) == 1):
        fails.append(f"a 429 is the way's, kept: {s} kept={relay._kept()}")
    HUB["status"] = 201
    relay.spool_flush()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/api/notifications",
                                 data=b'{\n  "source": "pretty",\n  "title": "indented"\n}', method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        pass
    if GOT[-1].get("source") != "pretty":
        fails.append(f"a pretty-printed body is one notice: {GOT[-1]}")
    record.unlink()
    s, _ = post({"source": "x", "title": "no record"})
    if not (s == 202 and len(relay._kept()) == 1):
        fails.append(f"no record of the hub: kept, not lost: {s} {relay._kept()}")
    print("PASS test_relay" if not fails else "FAIL test_relay")
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
