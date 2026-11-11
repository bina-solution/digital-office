#!/usr/bin/env python3
"""test_shell_routes — the terminal app's five calls, through THIS app over HTTP (DGO-1800).

apps/terminal opens, types into, polls, resizes and closes a shell through `/api/computers/<id>/shell…`; until
these routes, no branch's app.py served them and shell.py had no caller
(issues/the-terminal-app-calls-shell-routes-the-computers-app-never-had.yaml). Here the real app is served on
loopback (uvicorn, in a thread) with the real middleware; only the machine record and the ssh command line are
stood in for — an interactive /bin/sh where ssh to the machine would be. What it asks:
- open answers a session, a cursor and «alive»; typed keys reach the shell and its output comes back on a poll;
- a session belongs to the caller that opened it: another caller's poll is a 404, like one that does not exist;
- resize answers; close closes, twice is still «closed»; a closed session's poll is a 404;
- a machine that is not in the fleet is refused before anything starts.

Run: python3 tests/test_shell_routes.py   (needs fastapi, uvicorn and requests: the computers image has them)
"""
from __future__ import annotations

import logging
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
try:
    import requests
    import uvicorn
except ImportError as e:                                    # G72's convention: one NOT RUN line, a non-zero exit
    print(f"NOT RUN needs the package `{e.name}` (the computers image has it)")
    sys.exit(1)
import app  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


app.shell_argv = lambda cid, rec, sec: ["/bin/sh", "-i"]
app._resolve = lambda cid, gw: (({"host": "h", "port": 22, "user": "u"}, None) if cid == "m1"
                               else (None, app._err("המחשב לא נמצא", 404)))
app._computer_ctx = lambda rec, gw: ({}, None)
app.EXEC_TOKEN = "tok"                                      # a second, known caller: the service token


class _Keep(logging.Handler):                               # every line the app and shell.py log, to read back
    lines: list[str] = []

    def emit(self, rec):
        _Keep.lines.append(rec.getMessage())


logging.getLogger().addHandler(_Keep())
logging.getLogger().setLevel(logging.INFO)

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()
server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="off"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
U = f"http://127.0.0.1:{PORT}/api/computers"


def poll_until(sid, cursor, want, limit=6.0):
    out, end = "", time.time() + limit
    while time.time() < end:
        r = requests.get(f"{U}/m1/shell/{sid}", params={"cursor": cursor}, timeout=5)
        if r.status_code != 200:
            return out, r.status_code, cursor
        d = r.json()
        out += d.get("output") or ""
        cursor = d.get("cursor", cursor)
        if want in out:
            return out, 200, cursor
        time.sleep(0.15)
    return out, 200, cursor


r = requests.post(f"{U}/m1/shell", json={"cols": 80, "rows": 24}, timeout=10)
d = r.json() if r.ok else {}
sid = d.get("session")
check(r.status_code == 200 and sid and d.get("alive") is True and isinstance(d.get("cursor"), int),
      f"open answers a session, a cursor and «alive» ({r.status_code} {d})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json={"data": "echo DGO-$((40+2))\n", "cursor": d.get("cursor", 0)}, timeout=10)
check(r.status_code == 200, f"typed keys are taken ({r.status_code})")
out, code, cur = poll_until(sid, d.get("cursor", 0), "DGO-42")
check("DGO-42" in out, f"the shell's own output comes back on a poll ({out[-120:]!r})")
OTHER = {"Authorization": "Bearer tok"}                    # the service token: known, and not the opener
r = requests.get(f"{U}/m1/shell/{sid}", params={"cursor": 0}, headers=OTHER, timeout=5)
check(r.status_code == 404, f"another caller's poll answers as a session that does not exist ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json={"data": "echo INTRUDER-$((1+1))\n"}, headers=OTHER, timeout=5)
check(r.status_code == 404, f"another caller cannot type into it ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/resize", json={"cols": 30, "rows": 9}, headers=OTHER, timeout=5)
check(r.status_code == 404, f"another caller cannot resize it ({r.status_code})")
r = requests.delete(f"{U}/m1/shell/{sid}", headers=OTHER, timeout=5)
check(r.status_code == 200, f"another caller's close answers as for a session that is gone ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json={"data": "echo STILL-$((2+3))\n", "cursor": cur}, timeout=10)
out2, code, cur = poll_until(sid, cur, "STILL-5")
check(code == 200 and "STILL-5" in out2 and "INTRUDER-2" not in out + out2,
      f"…and the opener's session is alive and untouched after all three ({code}, {out2[-80:]!r})")

# a caller that SAYS it is another office and fails the claim (here: not from the door) — refused in every mode
OFFICE = {"x-dgo-office": "hp-laptop"}
check(app.AUTH_MODE == "warn", f"these run in the default mode, warn ({app.AUTH_MODE})")
r = requests.post(f"{U}/m1/shell", json={}, headers=OFFICE, timeout=5)
check(r.status_code == 403, f"a failed office claim cannot open a shell, even in warn ({r.status_code})")
r = requests.get(f"{U}/m1/shell/{sid}", params={"cursor": 0}, headers=OFFICE, timeout=5)
check(r.status_code == 403, f"…nor poll one ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json={"data": "x"}, headers={"x-dgo-identity": "v1.x.y"}, timeout=5)
check(r.status_code == 403, f"…nor type into one with only a signature header ({r.status_code})")
r = requests.post(f"{U}/nope/exec", json={"command": "true"}, headers=OFFICE, timeout=5)
check(r.status_code != 403, f"exec keeps warn for now: its callers over the link are counted first ({r.status_code})")

# the bodies a route takes
r = requests.post(f"{U}/m1/shell", json=[1, 2], timeout=5)
check(r.status_code == 400, f"a JSON body that is not an object is a 400, not a 500 ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json="ls", timeout=5)
check(r.status_code == 400, f"…on input too ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", data='{"data": "", "cursor": Infinity}',
                  headers={"content-type": "application/json"}, timeout=5)
check(r.status_code == 200, f"a cursor of Infinity reads from the start, not a 500 ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/input", json={"data": "א" * 33000}, timeout=5)
check(r.status_code == 400, f"the 64KB cap counts bytes: 33,000 Hebrew letters are 66,000 ({r.status_code})")

r = requests.post(f"{U}/m1/shell/{sid}/resize", data='{"cols": Infinity, "rows": 40}',
                  headers={"content-type": "application/json"}, timeout=5)
check(r.status_code == 200 and r.json().get("cols") == 100, f"a size of Infinity is the default, not a 500 ({r.status_code})")
r = requests.post(f"{U}/m1/shell/{sid}/resize", data="{not json", headers={"content-type": "application/json"}, timeout=5)
check(r.status_code == 400, f"a body that is not JSON is a 400, not a 500 ({r.status_code})")
check(any(k[1] == "GET" and k[2] == "/api/computers/{id}/shell/{sid}" for k in app._REFUSED),
      "a refused poll is counted with the refused writes (`bbox computers callers`)")
r = requests.post(f"{U}/m1/shell/{sid}/resize", json={"cols": 120, "rows": 40}, timeout=5)
check(r.status_code == 200 and r.json().get("cols") == 120, f"resize answers ({r.status_code})")
r = requests.delete(f"{U}/m1/shell/{sid}", timeout=5)
check(r.status_code == 200 and r.json().get("closed") is True, f"close closes ({r.status_code})")
r = requests.delete(f"{U}/m1/shell/{sid}", timeout=5)
check(r.status_code == 200 and r.json().get("closed") is True, f"closing twice is still «closed» ({r.status_code})")
r = requests.get(f"{U}/m1/shell/{sid}", params={"cursor": 0}, timeout=5)
check(r.status_code == 404, f"a closed session's poll is a 404 ({r.status_code})")
r = requests.post(f"{U}/nope/shell", json={}, timeout=5)
check(r.status_code == 404, f"a machine not in the fleet is refused before anything starts ({r.status_code})")

# reads that name another office are COUNTED (the first stage of narrowing them — answered as before): the poll above
# claimed hp-laptop from 127.0.0.1, which is not the door, so it is counted as a claim «(not the door)» by route
# template — never as hp-laptop's read (DGO-1800: only the door's reads decide the narrowing); a read with no office is not
before = sum(x["count"] for x in requests.get(f"http://127.0.0.1:{PORT}/api/callers", timeout=5).json().get("door_reads", []))
requests.get(f"{U}/m1/shell/{sid}", params={"cursor": 0}, timeout=5)               # no office header
reads = requests.get(f"http://127.0.0.1:{PORT}/api/callers", timeout=5).json().get("door_reads", [])
check(any(x["office"] == app.NOT_THE_DOOR and x["route"] == "/api/computers/{id}/shell/{sid}" for x in reads)
      and not any(x["office"] == "hp-laptop" for x in reads)
      and sum(x["count"] for x in reads) == before,
      f"a read claiming another office from outside the door is counted as a claim, one naming none is not ({reads})")

check(bool(sid) and not any(sid in ln for ln in _Keep.lines) and any(f"/shell/{sid[:4]}…" in ln for ln in _Keep.lines),
      f"the log never holds a session's id whole, only its first four ({len(_Keep.lines)} lines read)")
check(app._log_path("/api/computers/c/shell") == "/api/computers/c/shell"
      and app._log_path("/api/computers/c/shell/0a1b2c3d/input") == "/api/computers/c/shell/0a1b…/input",
      "_log_path cuts the id and keeps the route")

# a character is never cut between two reads: the bytes of an unfinished one wait for the next
for raw, held in ((b"", 0), (b"abc", 0), ("שלום".encode(), 0), (b"a\xd7", 1), (b"\xd7\x90\xd7", 1),
                  (b"\xe2\x82", 2), (b"\xe2\x82\xac", 0), (b"\xf0\x9f\x98", 3), (b"\xf0\x9f\x98\x80", 0)):
    check(app._utf8_tail(raw) == held, f"_utf8_tail({raw!r}) holds back {held} ({app._utf8_tail(raw)})")

class _Cut:                                                # a read that ended inside «א» (0xD7 0x90)
    key, error = "m1:0a1b2c3d", ""

    def drain(self, wait):
        pass

    def since(self, cursor):
        return b"ab\xd7", 3, False

    def alive(self):
        return True


st = app._shell_state(_Cut(), 0)
check(st["output"] == "ab" and st["cursor"] == 2 and st["session"] == "0a1b2c3d",
      f"_shell_state hands back «ab» and a cursor before the cut letter, so the next poll reads it whole ({st})")


class _Ended(_Cut):                                         # ssh has ended; was the last drain stopped by its cap?
    def __init__(self, capped):
        self.capped = capped

    def drain(self, wait):
        return self.capped

    def since(self, cursor):
        return b"", 0, False

    def alive(self):
        return False


check(app._shell_state(_Ended(True), 0)["alive"] is True and app._shell_state(_Ended(False), 0)["alive"] is False,
      "a drain stopped on its cap keeps the session «alive» for its reader, so the shell's last words are read")

# one drain() has an end, and stays inside the buffer: a far side that never stops writing does not hold the
# session's lock for good, and a reader that was caught up loses nothing. A real `yes` cannot show it on one CPU
# (the pty runs dry between two reads, so even an unbounded loop ends), so the far side here is ALWAYS ready and
# reads come in a Linux pty's 4,095 bytes: shell.py's own `select` and `os.read` are stood in for, nothing else's.
class _AlwaysOS:
    def __getattr__(self, name):
        return getattr(os, name)

    @staticmethod
    def read(fd, n):
        return b"y" * min(n, 4095)


SH = app.shellmod
s = SH.start("cap", ["/bin/sh", "-c", "sleep 30"], owner="t")
time.sleep(0.2)
s.drain(0)
caught_up = s.total                                         # a reader that has read everything so far…
held = max(0, caught_up - 1)                                # …and one that holds back the lead byte of a letter
real = (SH.select, SH.os)
SH.select, SH.os = type("Sel", (), {"select": staticmethod(lambda r, w, x, t=0: (r, [], []))}), _AlwaysOS()
try:
    t = threading.Thread(target=s.drain, args=(0.2,), daemon=True)
    t0 = time.time()
    t.start()
    t.join(4.0)
    ended, took = not t.is_alive(), time.time() - t0
finally:
    SH.select, SH.os = real                                 # a drain still looping ends on the real, quiet pty
check(ended and s.total - caught_up <= SH.DRAIN_BYTES,
      f"drain() ends by its cap ({took:.2f}s, {s.total - caught_up} bytes, cap {SH.DRAIN_BYTES})")
check(not s.since(caught_up)[2] and not s.since(held)[2],
      f"…and a reader caught up before it lost nothing, not even a held-back byte (dropped {s.dropped})")
t.join(2.0)
s.close()

# a far side that stops reading what is typed: the write ends with a sentence within its bound, and the session's
# lock is free again — a poll still answers. The tty is put in RAW mode first, as ssh puts its own: a tty in
# canonical mode drops what is past its 4 KB line instead of making the writer wait, and would show nothing.
s = SH.start("full", ["/bin/sh", "-c", "stty raw -echo; sleep 30"], owner="t")
time.sleep(0.5)
res: dict = {}


def _paste():
    try:
        s.write("x" * 1_000_000)
        res["ok"] = True
    except SH.ShellError as e:
        res["err"] = (e.status, str(e))


t = threading.Thread(target=_paste, daemon=True)
t0 = time.time()
t.start()
t.join(SH.WRITE_SECONDS + 3)
took = time.time() - t0
check(not t.is_alive() and res.get("err", (0,))[0] == 503,
      f"a write the far side does not take ends as a 503 within its bound — the session lives on "
      f"({took:.1f}s, {res.get('err', res)})")
t2 = threading.Thread(target=s.drain, args=(0,), daemon=True)
t2.start()
t2.join(2.0)
check(not t2.is_alive(), "…and the session's lock is free: a poll after it answers")
if not t.is_alive():
    s.close()

server.should_exit = True
print("test_shell_routes: " + ("ok" if not FAIL else f"{len(FAIL)} FAILED"))
sys.exit(1 if FAIL else 0)
