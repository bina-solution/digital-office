#!/usr/bin/env python3
"""test_via_door.py — `bbox via` asks the far office's JOB DOOR first, and its host shell only when the door is not the
way (scripts/via.py, DGO-1797 package 10). The link is stood in for: `_remote_json` (the door's calls through
scripts/remote.py) and `subprocess.run` (the Computers exec) are replaced, so what is proved is what via DOES with each
answer — never a live office.

    python3 scripts/test_via_door.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

# the cases name Hebrew answers: on Windows python's own stdout is not UTF-8, and printing one would crash the test (G10)
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import via  # noqa: E402

fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


class Door:
    """A far office's door: what POST answers, how the job ends, and its log in pages."""

    def __init__(self, post=202, state="done", exit_code=0, log="", error=""):
        self.post, self.state, self.exit, self.log, self.error = post, state, exit_code, log.encode(), error
        self.calls = []

    def __call__(self, office, alias, path, method="GET", body=None, timeout=30):
        self.calls.append((method, path, body))
        if method == "POST":
            if self.post == 202:
                return 202, json.dumps({"ok": True, "data": {"id": "1762800000-0a1b2c3d", "state": "queued"}})
            return self.post, json.dumps({"ok": False, "error": self.error})
        if path.endswith("/log") or "/log?offset=" in path:
            off = int(path.rsplit("=", 1)[1])
            page = self.log[off:off + 7]                     # small pages, cut on whole characters as door.py cuts
            while page:
                try:
                    return 200, page.decode()
                except UnicodeDecodeError:
                    page = page[:-1]
            return 200, ""
        return 200, json.dumps({"ok": True, "data": {"state": self.state, "exit": self.exit}})


class Shell:
    """The Computers exec: what it answers when the host shell is asked."""

    def __init__(self, out=None):
        self.out = out if out is not None else {"code": 0, "stdout": "from the shell\n", "stderr": ""}
        self.asked = 0

    def __call__(self, call, capture_output=True, text=True, **kw):
        self.asked += 1

        class P:
            stdout = json.dumps(self.out)
            stderr = ""
        return P()


def run(argv, door, shell, env=None):
    via._remote_json, via.subprocess.run = door, shell
    out, err = io.StringIO(), io.StringIO()
    old = dict(os.environ)
    os.environ.update(env or {})
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = via.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return rc, out.getvalue(), err.getvalue()


via.time.sleep = lambda s: None                              # no real waits in a test
PUBLISHED = {"hp-laptop", "vps1"}                              # the offices whose door this one sees
via._door_published = lambda office: office in PUBLISHED

d, s = Door(), Shell()
rc, out, err = run(["portable-ubuntu", "status"], d, s)
check("an office that publishes no door is never asked one: no call, straight to its host shell",
      d.calls == [] and s.asked == 1 and rc == 0, (d.calls, s.asked))

d, s = Door(log="args: status — בדיקה\n"), Shell()
rc, out, err = run(["hp-laptop", "status"], d, s)
check("a door that takes the verb runs it: its whole log, its exit, and no host shell asked",
      rc == 0 and out == "args: status — בדיקה\n" and s.asked == 0, (rc, out, s.asked))
check("…asked as the named job bbox with the words as typed",
      d.calls[0] == ("POST", "/api/door/jobs", {"name": "bbox", "args": {"verb": ["status"]}}), d.calls[0])

rc, out, err = run(["hp-laptop", "computers", "herd"], Door(state="failed", exit_code=3), Shell())
check("a job that failed there exits with its own code", rc == 3, rc)
rc, out, err = run(["hp-laptop", "status"], Door(state="timeout", exit_code=124), Shell())
check("a job stopped at its timeout there exits 124 and says so", rc == 124 and "timeout" in err, (rc, err))

for code, why in ((404, "no such route"), (403, "this office takes no jobs from macbook"),
                  (400, "is not one of the verbs")):
    d, s = Door(post=code, error=why), Shell()
    rc, out, err = run(["vps1", "dgo", "link", "status"], d, s)
    check(f"a door that answers {code} is not the way: the host shell is asked, as before",
          rc == 0 and out == "from the shell\n" and s.asked == 1 and len(d.calls) == 1, (rc, out, s.asked, d.calls))

d, s = Door(), Shell()
rc, out, err = run(["vps1", "project-pln", "tasks", "list"], d, s)
check("a verb off the door's own list never costs a call to the door: straight to the host shell",
      d.calls == [] and s.asked == 1 and rc == 0, (d.calls, s.asked))

d, s = Door(), Shell()
rc, out, err = run(["vps1", "status"], d, s, env={"BBOX_VIA_DOOR": "off"})
check("BBOX_VIA_DOOR=off: the door is not asked", d.calls == [] and s.asked == 1, d.calls)
tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "via-door-put.txt"
tmp.write_text("x")
d, s = Door(), Shell()
rc, out, err = run(["vps1", "--put", str(tmp), "project-pln", "tasks", "attach", "DGO-1", str(tmp)], d, s)
tmp.unlink()
check("a call that carries files (--put) never goes to the door", d.calls == [] and s.asked == 1, d.calls)

d = Door(post=403, error="this office takes no jobs from macbook")
s = Shell({"code": 255, "stdout": "", "stderr": "", "reason": "ssh: connect to host 172.18.0.1 port 22: Connection refused"})
rc, out, err = run(["hp-laptop", "status"], d, s)
check("neither a host shell nor a door: said in those words, with the door's own reason",
      rc == 255 and "has no host shell that answers, and no job door that runs this verb" in err
      and "takes no jobs from macbook" in err, (rc, err))

print("via door: " + ("PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
