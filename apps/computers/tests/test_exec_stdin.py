#!/usr/bin/env python3
"""test_exec_stdin — `exec` hands a secret to the machine on standard input, never on a command line.

The command travels as an argument: in this container's `ssh` argv and in the far side's `bash -c` argv,
where any local user reads /proc/<pid>/cmdline. A key DGO Extend's off-server backup carries (FPG-26) must
therefore go as stdin. ssh itself is stood in for; what is tested is what this app gives it, and what the
route answers and logs.

Run in the app's image: python3 tests/test_exec_stdin.py   (from apps/computers)
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))

import app  # noqa: E402

FAIL: list[str] = []
SECRET = "S3CRET-" + "x" * 40


def check(cond, what):
    if not cond:
        FAIL.append(what)


class P:
    returncode, stdout, stderr = 0, b"ok\n", b""


def main() -> int:
    seen = {}
    app.ensure_key = lambda: True
    app._key_path_for = lambda secret: "/tmp/k"
    app.subprocess.run = lambda cmd, **kw: (seen.update(cmd=cmd, kw=kw), P())[1]
    r = app.ssh_run("c1", "h", 22, "root", {}, "cat > /tmp/s.sh", 30, stdin=SECRET.encode())
    check(r.get("code") == 0 and seen["kw"].get("input") == SECRET.encode(), f"stdin reaches ssh as input: {seen.get('kw')}")
    check(not any(SECRET in str(a) for a in seen["cmd"]), "never in ssh's argv")
    app.ssh_run("c1", "h", 22, "root", {}, "true", 30)
    check(seen["kw"].get("input") == b"", "no stdin = an empty one (EOF), as /dev/null was")

    import asyncio
    import json

    class Req:                                   # the route reads only .body() and .json()
        def __init__(self, body):
            self._b = json.dumps(body).encode()

        async def body(self):
            return self._b

        async def json(self):
            return json.loads(self._b)

    def post(body):
        r = asyncio.run(app.api_computer_exec("c1", Req(body)))
        code = getattr(r, "status_code", 200)
        return code, (json.loads(r.body) if code != 200 else r)
    app._resolve = lambda cid, gw: ({"host": "h", "port": 22, "user": "root"}, None)
    app._computer_ctx = lambda rec, gw: ({}, None)
    logs = []
    handler = logging.Handler()
    handler.emit = lambda rec: logs.append(rec.getMessage())
    app.log.addHandler(handler)
    app.log.setLevel(logging.INFO)
    code, out = post({"command": "cat > /tmp/s.sh", "stdin": SECRET})
    check(code == 200 and out.get("stdin_bytes") == len(SECRET) and SECRET not in str(out),
          f"the answer says the length, not the secret: {out}")
    check(any("stdin" in m for m in logs) and not any(SECRET in m for m in logs), f"the log neither: {logs}")
    code, _ = post({"command": "true", "stdin": "x" * (app.STDIN_MAX + 1)})
    check(code == 400, f"stdin past its limit is refused: {code}")
    code, _ = post({"command": "true", "stdin": 5})
    check(code == 400, f"stdin that is not text is refused: {code}")
    code, _ = post({"command": "true", "stdin": "ab\ud800"})
    check(code == 400, f"a lone surrogate is a 400, not a 500: {code}")
    print("PASS test_exec_stdin" if not FAIL else "FAIL test_exec_stdin")
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
