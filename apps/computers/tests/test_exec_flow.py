#!/usr/bin/env python3
"""test_exec_flow — every command run through `exec` is one bar in «כל מקביל», and the bar says only its first word.

The owner, DGO-1797: «אני רואה בכל מקביל של דל את כל מה שרץ … כולל פקודות ssh». The route publishes on
`dgo:flow:computers` through the office's one publisher: `command.started`, then `command.ended` (exit 0) or
`command.failed` (any other exit, or the call raising), sharing `data.span`. What may carry a secret — the rest of
the command line, a leading `NAME=value`, its stdin, its output — never goes out. ssh and the publisher are
stood in for; what is tested is what the route gives them.

Run in the app's image: python3 tests/test_exec_flow.py   (from apps/computers)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))

import app  # noqa: E402

FAIL: list[str] = []
SECRET = "S3CRET-" + "x" * 40
SHORT = "s3cretTOKEN42"          # a secret that LOOKS like a program name: fits the allowed set, under 40


def check(cond, what):
    if not cond:
        FAIL.append(what)


class Pub:                                       # the publisher, as flowpub.emit is called
    def __init__(self):
        self.events = []

    def emit(self, app_id, type_, title, data=None, link=""):
        self.events.append({"app": app_id, "type": type_, "title": title, "data": dict(data or {})})
        return True


class Req:                                       # the route reads only .body(), .json() and .state
    def __init__(self, body):
        self._b = json.dumps(body).encode()
        self.state = type("S", (), {"caller": type("C", (), {"ok": True, "who": "office:macbook/k3", "way": "door"})()})()

    async def body(self):
        return self._b

    async def json(self):
        return json.loads(self._b)


def run(command, code=0, raises=None, stdin=None):
    pub = Pub()
    app.flowpub = pub

    def ssh(*a, **kw):
        if raises:
            raise raises
        return {"code": code, "stdout": "out " + SECRET, "stderr": ""}
    app.ssh_run = ssh
    body = {"command": command, **({"stdin": stdin} if stdin else {})}
    try:
        out = asyncio.run(app.api_computer_exec("computer_local-local", Req(body)))
    except Exception as e:                       # noqa: BLE001 — the route re-raises; the bar must be closed first
        out = e
    return out, pub.events


def main() -> int:
    app._resolve = lambda cid, gw: ({"host": "h", "port": 22, "user": "root"}, None)
    app._computer_ctx = lambda rec, gw: ({}, None)

    out, ev = run(f"TOKEN={SECRET} /usr/local/bin/backup --key {SECRET} /data", code=0, stdin=SECRET)
    types = [e["type"] for e in ev]
    check(types == ["command.started", "command.ended"], f"exit 0: started then ended — {types}")
    check(all(e["app"] == "computers" for e in ev), "under its own id")
    check(len({e["data"].get("span") for e in ev}) == 1 and ev[0]["data"].get("span"), "one bar: one span id on both")
    check(ev[-1]["data"].get("exit") == 0 and isinstance(ev[-1]["data"].get("ms"), int)
          and isinstance(ev[-1]["data"].get("t0"), int), f"the end carries exit, t0 and ms: {ev[-1]['data']}")
    check(ev[0]["title"] == "computer_local-local: backup", f"the title is the computer and the program: {ev[0]['title']}")
    check(ev[0]["data"].get("caller") == "office:macbook/k3" and ev[0]["data"].get("way") == "door", "who asked, and how")
    check(SECRET[:8] not in json.dumps(ev), "no secret in any event: not the argument, not the NAME=value, not stdin, not the output")
    check("TOKEN" not in json.dumps(ev), "not even the name of a leading assignment")

    # the secret can sit where a whitespace split would take it for the program (the second reader's cases)
    for cmd, want in ((f'AUTH="Bearer {SECRET}" curl -s x', "curl"), (f"PGPASSWORD='pw {SECRET}' psql -c 1", "psql"),
                      (f"X=$(echo {SECRET}) y", "sh"), (f"TOKEN=a\\ {SECRET} cmd", "cmd"),
                      (f"(TOKEN={SECRET} cmd)", "sh"), (f"true;TOKEN={SECRET} cmd", "sh"),
                      (f'"TOKEN={SECRET}" cmd', "cmd"), (f"echo '{SECRET}", "sh"), (f"{SECRET[:4]}$(x) y", "sh")):
        _, ev = run(cmd)
        blob = json.dumps(ev)
        check(SECRET[:8] not in blob, f"no part of the secret leaves for {cmd[:30]!r}: {ev[0]['title']!r}")
        check(ev[0]["title"] == f"computer_local-local: {want}", f"{cmd[:30]!r} → «{want}», not {ev[0]['title']!r}")

    # …and a SHORT secret, which a 40-character cap would not hide, where a value runs on into the next words as a
    # shell reads it (the third reader's rows) or sits in the earlier cases' places
    for cmd, want in ((f"TOKEN=$(echo {SHORT} | base64) curl -H x", "sh"), (f"PGPASSWORD=$(echo {SHORT} ) psql", "sh"),
                      (f"X=$(cat {SHORT} ) y", "sh"), (f"X=`echo {SHORT} ` y", "sh"), (f"KEYS=( {SHORT} other ); cmd", "sh"),
                      (f"X=${{Y:- {SHORT} }} cmd", "sh"), (f"T=$'a\\' {SHORT} \\'' cmd x\\'", "sh"),
                      (f'AUTH="Bearer {SHORT}" curl', "curl"), (f"PGPASSWORD='pw {SHORT}' psql", "psql"),
                      (f"TOKEN=a\\ {SHORT} cmd", "cmd"), (f"(TOKEN={SHORT} cmd)", "sh"), (f"true;TOKEN={SHORT} cmd", "sh")):
        _, ev = run(cmd)
        check(SHORT not in json.dumps(ev), f"the short secret stays home for {cmd[:34]!r}: {ev[0]['title']!r}")
        check(ev[0]["title"] == f"computer_local-local: {want}", f"{cmd[:34]!r} → «{want}», not {ev[0]['title']!r}")

    t = time.monotonic()
    _, ev = run("ls " + "x " * 2_500_000)                # 5 MB: only the head is read, the loop is not held
    check(time.monotonic() - t < 1.0 and ev[0]["title"] == "computer_local-local: ls",
          f"a 5 MB command is named in under a second: {time.monotonic() - t:.2f} s")
    check(app._first_word('"curl\n" x') == "sh", "a quoted word with a trailing newline is not a name")

    _, ev = run("false", code=3)
    check([e["type"] for e in ev] == ["command.started", "command.failed"] and ev[-1]["data"].get("exit") == 3,
          f"a non-zero exit is a failed bar: {[(e['type'], e['data'].get('exit')) for e in ev]}")

    out, ev = run("sleep 9", raises=RuntimeError("ssh died"))
    check(isinstance(out, RuntimeError), "the route's own error is not swallowed")
    check([e["type"] for e in ev] == ["command.started", "command.failed"] and ev[-1]["data"].get("error") == "RuntimeError",
          f"a call that raises still closes its bar: {ev}")

    check(app._first_word("A=1 B=2") == "sh" and app._first_word("  ls -la") == "ls", "only assignments → «sh»; spaces skipped")

    app.flowpub = None
    app.ssh_run = lambda *a, **kw: {"code": 0, "stdout": "", "stderr": ""}
    out2 = asyncio.run(app.api_computer_exec("computer_local-local", Req({"command": "true"})))
    check(isinstance(out2, dict) and out2.get("code") == 0, "without the publisher the route works the same")

    print("PASS test_exec_flow" if not FAIL else "FAIL test_exec_flow")
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
