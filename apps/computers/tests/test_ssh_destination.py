#!/usr/bin/env python3
"""test_ssh_destination — a computer's user can never become an ssh option (issues/a-computers-user-that-starts-…).

    python3 apps/computers/tests/test_ssh_destination.py     (the computers image: fastapi, and ssh for `ssh -G`)

Measured 2026-11-10: a computer saved with the user `-oProxyCommand=<cmd>` made ssh read `<user>@<host>` as an OPTION
and run <cmd> in this container, which holds every machine's key (`ssh -G` printed `proxycommand <cmd>@h`). Now the
one command line (ssh_argv, which ssh_run, transfer and the terminal all use) ends ssh's options with `--` and refuses
a user or host led by «-» or holding a control character; saving one is a 400. A Windows account with a space is
still a user. `ssh -G` prints the configuration ssh WOULD use and connects to nothing.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))
try:
    import fastapi  # noqa: F401
except ImportError as e:
    print(f"NOT RUN needs the package `{e.name}` (the computers image has it)")
    sys.exit(1)
import app  # noqa: E402
import shell as shellmod  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


def refused(user, host) -> bool:
    try:
        app.check_destination(user, host)
        return False
    except app.BadDestination:
        return True


# 1. the rule
for user, host in (("root", "203.0.113.5"), ("Owner Owner", "192.0.2.104"), ("me@corp", "h"), ("שלמה", "h")):
    check(not refused(user, host), f"{user!r}@{host!r} is a destination")
for user, host, what in (("-oProxyCommand=touch /tmp/x", "h", "a user led by «-» (an ssh option)"),
                         ("root\nProxyCommand x", "h", "a user with a newline"), ("", "h", "no user"),
                         ("root", "-oProxyCommand=x", "a host led by «-»"), ("root", "h h", "a host with a space"),
                         ("root", "evil@203.0.113.9", "a host with «@» (ssh would split it and reach another")):
    check(refused(user, host), f"{what} is refused")

# 2. the one command line: `--` before the destination, the command after it
app._key_path_for = lambda secret: "/tmp/k"
argv = app.ssh_argv("c1", "203.0.113.5", 22, "root", {}, "uptime")
check(argv[-3:] == ["--", "root@203.0.113.5", "uptime"], f"`--` ends the options before the destination ({argv[-3:]})")
try:
    app.ssh_argv("c1", "h", 22, "-oProxyCommand=touch /tmp/x", {}, "true")
    check(False, "ssh_argv refuses a dash-led user")
except app.BadDestination:
    check(True, "ssh_argv refuses a dash-led user — a record saved before the check never reaches ssh")

# 3. ssh itself reads that command line as intended (`ssh -G`: the configuration only, nothing is connected)
if shutil.which("ssh"):
    for user in ("root", "Owner Owner"):
        a = app.ssh_argv("c1", "h.example", 2222, user, {}, "true")
        out = subprocess.run(["ssh", "-G", *a[1:]], capture_output=True, text=True, timeout=10).stdout
        conf = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
        check(conf.get("user") == user and conf.get("hostname") == "h.example" and conf.get("port") == "2222"
              and "proxycommand" not in conf, f"ssh reads user {user!r}, host and port from the line, no proxy command")
    raw = subprocess.run(["ssh", "-G", "-p", "22", "-oProxyCommand=echo PWNED@h", "true"], capture_output=True,
                         text=True, timeout=10).stdout
    check("proxycommand echo PWNED@h" in raw, "…and without the check, the old line WAS an option (measured again)")
else:
    print("NOT RUN  ssh -G: no ssh here (the computers image has it)")

# 4. ssh_run and the terminal refuse an old record with a sentence, before any process starts
ran = []
app.subprocess.run = lambda *a, **k: ran.append(a) or None
app.ensure_key = lambda: True
res = app.ssh_run("c1", "h", 22, "-oProxyCommand=touch /tmp/x", {}, "true", 5)
check(res["code"] == 255 and res["state"] == "error" and "אינו תקין" in res["reason"] and not ran,
      f"ssh_run refuses it, and nothing ran ({res['reason']})")
try:
    app.shell_argv("c1", {"host": "h", "port": 22, "user": "-oX=y"}, {})
    check(False, "the terminal refuses it")
except shellmod.ShellError as e:
    check(e.status == 409 and "אינו תקין" in str(e), f"the terminal refuses it ({e.status})")


# 5. saving a computer with that user is a 400 — before the vault is asked
class Req:
    def __init__(self, body):
        self._b = json.dumps(body).encode()
        self.state = type("S", (), {"caller": None})()

    async def body(self):
        return self._b

    async def json(self):
        return json.loads(self._b)


asked = []
app.vault_add = lambda *a, **k: asked.append(a) or ({}, 500)
r = asyncio.run(app.api_computers_post(Req({"host": "203.0.113.5", "user": "-oProxyCommand=touch /tmp/x"})))
check(r.status_code == 400 and not asked, f"saving a dash-led user is a 400, and the vault is never asked ({r.status_code})")
# …through `/connections` too, which handed api_computers_post a dict and crashed on `.body()` before any check
try:
    r = asyncio.run(app.connections_add(Req({"host": "203.0.113.5", "user": "-oProxyCommand=touch /tmp/x"})))
    check(r.status_code == 400 and not asked, f"POST /connections answers the same 400 ({r.status_code})")
except AttributeError as e:
    check(False, f"POST /connections crashes before any check ({e})")

# 6. a transfer between two machines says the refusal at once, not as a queued job that fails a moment later
app._resolve = lambda cid, gw: ({"id": cid, "host": "h", "port": 22, "user": "-oX=y" if cid == "bad" else "root"}, None)
app._computer_ctx = lambda rec, gw: ({}, None)
app.local_gateway = lambda: "172.18.0.1"                     # (subprocess is stood in for above: no docker here)
started = []
sys.modules["transfer"] = type(sys)("transfer")
sys.modules["transfer"].start = lambda *a, **k: started.append(a) or {}
r = asyncio.run(app.api_transfer("good", Req({"to": "bad", "volume": "v1"})))
check(r.status_code == 409 and not started, f"a transfer to a machine with a bad user is refused before it starts ({r.status_code})")

print("test_ssh_destination: " + ("ok" if not FAIL else f"{len(FAIL)} FAILED"))
sys.exit(1 if FAIL else 0)
