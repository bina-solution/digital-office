#!/usr/bin/env python3
"""test_shared_machines — a linked office's machine is a row of this fleet, and what is done to it goes to that office
(DGO-553, wired in DGO-1800).

    python3 apps/computers/tests/test_shared_machines.py     (the computers image: fastapi, uvicorn, requests)

remote.py held the design — `<machine>.<office>` rows, every op sent back over the link — and app.py called none of it
(issues/computers-never-lists-the-machines-a-linked-office-shares-…). Here the REAL app is served on loopback with the
compiled registry stood in for (a directory with `remote.<office>.computers.json`) and a stand-in office behind the
«door» (an HTTP server playing the far computers). What it asks: the far office's own machine is listed, and only it;
an office that does not answer is named in shared_from; an exec on the shared machine reaches that office as ITS
machine, carrying nothing of this request's identity headers; the caller check runs before anything leaves (a failed
office claim on a shell is refused here); a local id or an unknown office never goes over the link.
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))
REG = Path(tempfile.mkdtemp(prefix="registry-"))
os.environ["COMPUTERS_REGISTRY"] = str(REG)
os.environ.pop("COMPUTERS_REGISTRY_DIR", None)
try:
    import requests
    import uvicorn
except ImportError as e:
    print(f"NOT RUN needs the package `{e.name}` (the computers image has it)")
    sys.exit(1)

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ── the far office, behind the door ─────────────────────────────────────────────────────────────────────────────────
SEEN: list[dict] = []


class Peer(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, doc):
        raw = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _note(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null") if n else None
        SEEN.append({"method": self.command, "path": self.path, "body": body, "headers": dict(self.headers)})

    def do_GET(self):
        self._note()
        if self.path.startswith("/api/computers?"):
            return self._send(200, {"computers": [
                {"id": "computer_local-local", "label": "HP", "host": "192.0.2.10", "user": "u", "port": 22,
                 "ok": True, "state": "ok", "builtin": True},
                {"id": "computer_ssh-x", "label": "another", "host": "192.0.2.11", "ok": True, "state": "ok"}]})
        return self._send(404, {"error": "?"})

    def do_DELETE(self):
        self._note()
        return self._send(200, {"closed": True})

    def do_POST(self):
        self._note()
        if self.path == "/api/computers/computer_local-local/exec":
            return self._send(200, {"code": 0, "stdout": "from the far office\n", "stderr": ""})
        return self._send(200, {"session": "0a1b2c3d4e5f6071", "cursor": 0, "alive": True, "output": ""})


PEER_PORT = free_port()
peer = http.server.ThreadingHTTPServer(("127.0.0.1", PEER_PORT), Peer)
threading.Thread(target=peer.serve_forever, daemon=True).start()
for office, port in (("peer", PEER_PORT), ("down", free_port())):     # `down`: a port nothing listens on
    (REG / f"remote.{office}.computers.json").write_text(json.dumps(
        {"app": "computers", "door": {"base": f"http://127.0.0.1:{port}", "host": f"computers.{office}"},
         "remote": {"office": office, "label": office.upper()}}), encoding="utf-8")

import app  # noqa: E402

app.vault_list = lambda: ([], None)                          # this office: no machine of its own in the vault
app.local_gateway = lambda: "172.18.0.1"
app.REMOTE_LIST_S = 2.0

PORT = free_port()
server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="off"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
U = f"http://127.0.0.1:{PORT}/api/computers"

# 1. the list: the far office's OWN machine, and only it; the office that does not answer named
d = requests.get(U, params={"probe": 0}, timeout=15).json()
ids = [c["id"] for c in d.get("computers", [])]
check("computer_local-local.peer" in ids and "computer_ssh-x.peer" not in ids,
      f"the far office's own machine is a row `<machine>.<office>`, its other machine is not ({ids})")
row = next((c for c in d.get("computers", []) if c["id"] == "computer_local-local.peer"), {})
check(row.get("remote", {}).get("office") == "peer" and row.get("builtin") is False and row.get("removable") is False,
      f"…marked as the office's, neither built in nor removable here ({row.get('remote')})")
frm = {s["office"]: s for s in d.get("shared_from", [])}
check(frm.get("peer", {}).get("ok") is True and frm.get("down", {}).get("ok") is False and frm["down"].get("why"),
      f"shared_from names the office that did not answer, with why ({d.get('shared_from')})")

# 2. an exec on the shared machine goes to that office as ITS machine, and its answer comes back as it is
SEEN.clear()
r = requests.post(f"{U}/computer_local-local.peer/exec", json={"command": "uptime"},
                  headers={"x-authentik-username": "should-not-travel"}, timeout=15)   # an office claim is refused (6)
sent = next((s for s in SEEN if s["method"] == "POST"), {})
check(r.status_code == 200 and r.json().get("stdout") == "from the far office\n",
      f"an exec on the shared machine answers as the far office answered ({r.status_code})")
check(sent.get("path") == "/api/computers/computer_local-local/exec" and sent.get("body") == {"command": "uptime"}
      and sent["headers"].get("Host") == "computers.peer",
      f"…it reached that office as its own machine, through its door's address ({sent.get('path')})")
check(not any(k.lower() in ("x-dgo-identity", "x-dgo-office", "x-authentik-username") for k in sent.get("headers", {})),
      "…carrying none of this request's identity headers (the door writes its own)")

# 3. the caller check runs BEFORE anything leaves: a failed office claim on a shell is refused here
SEEN.clear()
r = requests.post(f"{U}/computer_local-local.peer/shell", json={}, headers={"x-dgo-office": "intruder"}, timeout=15)
check(r.status_code == 403 and not SEEN, f"a failed office claim is refused here and nothing is sent ({r.status_code}, {len(SEEN)})")

# 4. a local id, and an office this one is not linked to, never go over the link
SEEN.clear()
r1 = requests.post(f"{U}/computer_ssh-zz/exec", json={"command": "true"}, timeout=15)
r2 = requests.post(f"{U}/computer_ssh-zz.nosuch/exec", json={"command": "true"}, timeout=15)
check(r1.status_code == 404 and r2.status_code == 404 and not SEEN,
      f"a local id and an unknown office are answered here, not sent ({r1.status_code}, {r2.status_code}, {len(SEEN)})")

# 5. no loop between offices: a list asked THROUGH a door (another office's) does not ask its own peers, nor one asked
#    with shared=0 (what this office sends its peers) — and the peer was asked with shared=0
app._SHARED["at"] = 0.0
SEEN.clear()
d1 = requests.get(U, params={"probe": 0}, headers={"x-dgo-office": "hp-laptop"}, timeout=15).json()
d2 = requests.get(U, params={"probe": 0, "shared": 0}, timeout=15).json()
check(not SEEN and not d1.get("shared_from") and not d2.get("shared_from"),
      f"a list asked through a door, or with shared=0, asks no other office ({len(SEEN)})")
requests.get(U, params={"probe": 0}, timeout=15)
check(any(s["path"] == "/api/computers?probe=0&shared=0" for s in SEEN), "…and this office asks its peers with shared=0")

# 6. only what the far office's door would let through goes: a command, a terminal and its poll on the machine it
#    gives — not a delete, not another machine, not a request that itself came through a door
SEEN.clear()
r1 = requests.delete(f"{U}/computer_local-local.peer", timeout=15)
r2 = requests.post(f"{U}/computer_ssh-x.peer/exec", json={"command": "true"}, timeout=15)
r3 = requests.get(f"{U}/computer_local-local.peer/shell/0a1b2c3d4e5f6071", headers={"x-dgo-office": "vps1"}, timeout=15)
check((r1.status_code, r2.status_code, r3.status_code) == (403, 403, 403) and not SEEN,
      f"a delete, another machine of that office, and a request from a third office are refused here "
      f"({r1.status_code}, {r2.status_code}, {r3.status_code}, sent {len(SEEN)})")
r4 = requests.get(f"{U}/computer_local-local.peer/shell/0a1b2c3d4e5f6071", params={"cursor": 3}, timeout=15)
check(any(s["path"] == "/api/computers/computer_local-local/shell/0a1b2c3d4e5f6071?cursor=3" for s in SEEN),
      f"…and a terminal's poll goes, with its cursor ({r4.status_code})")

# …and what goes is exactly the path that was checked: an encoded `/` passed as «close a shell» is forwarded as that
#    close, never as a delete of the machine (the second reader, round 2)
SEEN.clear()
r = requests.delete(f"{U}/computer_local-local.peer%2Fshell%2F0a", timeout=15)
sent = [s for s in SEEN if s["method"] == "DELETE"]
check(all(s["path"] == "/api/computers/computer_local-local/shell/0a" for s in sent),
      f"an encoded path is forwarded as the path that was checked, nothing wider ({[s['path'] for s in sent]})")

# 7. an unidentified writer never leaves as this office's signed request, in warn too
app.callermod.is_loopback = lambda addr: False               # loopback is no longer «local»: an unknown caller
SEEN.clear()
r = requests.post(f"{U}/computer_local-local.peer/exec", json={"command": "true"}, timeout=15)
check(app.AUTH_MODE == "warn" and r.status_code == 403 and not SEEN,
      f"an unidentified caller's command is refused here, even in warn ({r.status_code}, sent {len(SEEN)})")

server.should_exit = True
peer.shutdown()
print("test_shared_machines: " + ("ok" if not FAIL else f"{len(FAIL)} FAILED"))
sys.exit(1 if FAIL else 0)
