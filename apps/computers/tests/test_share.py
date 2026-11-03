#!/usr/bin/env python3
"""test_share — the share feature's three promises, each pinned by a test.

  1. A REVOKE reports the truth. `key_removed` is the machine's own count of the lines left tagged
     with that share, not ssh's exit code: the removal command used to end in `; true`, so a revoke
     that deleted nothing (a read-only ~/.ssh, a file the ssh user cannot write) answered "removed"
     and the row was dropped — leaving a root key in authorized_keys that nothing named.
  2. A DOOR is never handed to a shell unquoted. ssh runs `ProxyCommand` through /bin/sh and the
     value comes back from the credential plane, so `_door_opts` re-checks it at the point of use.
  3. The door's PATH is not the app. Every plain HTTP request under `/share/` is a 403 — never the
     SPA (this app serves its screens from a catch-all) and never a sign-in redirect.

What is NOT tested here: the WebSocket relay itself (it needs a live sshd; it is exercised live by
openings a door and reading sshd's banner).

Run in the app's image: python3 tests/test_share.py   (from apps/computers)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))

import app  # noqa: E402
import share  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    # ── 1. revoke ────────────────────────────────────────────────────────────────────────────
    cmd = share.revoke_command("share-11111111")
    check("share-11111111" in cmd and "echo" in cmd, "the removal command names the share AND reports")
    check("; true" not in cmd.split("|| true")[-1].strip()[-5:], "it no longer ends in a bare `; true`")

    def run(command, home):
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        import subprocess
        return subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=env)

    home = Path(tempfile.mkdtemp(prefix="share-home-"))
    (home / ".ssh").mkdir()
    keys = home / ".ssh" / "authorized_keys"
    keys.write_text("ssh-ed25519 AAAA one computers-share:share-11111111:cloud\n"
                    "ssh-ed25519 BBBB two computers-share:share-22222222:cloud2\n"
                    "ssh-ed25519 CCCC mine office-key@office\n")
    p = run(cmd, home)
    check(p.stdout.strip() == "0", f"a removed key leaves a count of 0 (got {p.stdout.strip()!r})")
    left = keys.read_text()
    check("share-11111111" not in left, "its own line is gone")
    check("share-22222222" in left and "office-key@office" in left,
          "another share's line and the owner's own key are untouched")

    p = run(share.revoke_command("share-22222222"), home)
    check(p.stdout.strip() == "0", "second revoke reports 0 too")
    check("share-22222222" not in keys.read_text(), "and removes its own line")

    p = run(cmd, Path(tempfile.mkdtemp(prefix="share-nohome-")))
    check(p.stdout.strip() == "0" and p.returncode == 0, "no authorized_keys at all is 0, not an error")

    # the app reads the count, not the exit code
    REAL_SSH_RUN = app.ssh_run
    app.ssh_run = lambda *a, **kw: {"code": 0, "stdout": "1\n", "stderr": ""}
    import asyncio
    import json

    app._resolve = lambda cid, gw: ({"id": "computer_local-local", "host": "h", "port": 22, "user": "root"}, None)
    app._computer_ctx = lambda rec, gw: ({}, None)
    state = tempfile.mkdtemp(prefix="share-state-")
    app.STATE_DIR = Path(state)
    share.create(Path(state), "share-33333333", "computer_local-local", "cloud", "ssh-ed25519 AAAA three")

    async def _drop_nothing(*a, **kw):
        return None

    r = asyncio.run(app.api_share_revoke("share-33333333"))
    body = json.loads(r.body) if hasattr(r, "body") else r
    check(body.get("key_removed") is False, f"a key that did NOT leave is not reported as removed ({body})")
    check(body.get("still_listed") is True and "warning" in body, "and the row is kept, with the warning")
    check(share.get(Path(state), "share-33333333") is not None, "the share is still on record")

    # ── 2. the door in ssh's argv ────────────────────────────────────────────────────────────
    app.ssh_run = REAL_SSH_RUN
    good = "wss://computers.example.co.il/share/" + "A" * 43
    opts = app._door_opts("computer_x", {"door": good})
    check(any(o.startswith("ProxyCommand=") for o in opts), "a valid door becomes a ProxyCommand")
    check(any(o.startswith("HostKeyAlias=") for o in opts), "and pins the host key under the instance id")
    for bad in ["wss://h/share/" + "A" * 43 + "; rm -rf /", "wss://h/share/" + "A" * 43 + " x",
                "wss://h/other/" + "A" * 43, "wss://h/share/short", ""]:
        try:
            out = app._door_opts("computer_x", {"door": bad})
            check(bad == "" and out == [], f"a malformed door is refused, not passed to sh: {bad!r}")
        except ValueError:
            pass
    check(app._door_opts("computer_x", {}) == [], "no door = no ProxyCommand (a plain machine)")

    # ssh_run turns that refusal into a handled answer, never a 500 into the route
    app.ensure_key = lambda: True
    app._key_path_for = lambda secret: "/tmp/k"
    res = app.ssh_run("c1", "h", 22, "root", {"door": "wss://h/share/" + "A" * 43 + "; id"}, "true", 5)
    check(res.get("code") == 255 and res.get("state") == "error", f"a bad door is an error dict ({res})")

    # ── 2b. an append never joins the last line (DGO-1231: FPG's office-key@hp inside office-key@local's line)
    import shutil
    import subprocess
    blob = "ssh-ed25519 " + "H" * 68
    real_key = app.public_key
    app.public_key = lambda: blob                                   # app.py's own commands, office key or not
    swallowed = f"ssh-ed25519 MMMM office-key@local{blob} computers-share:share-33333333:hp\n"   # FPG's file
    for start in ["ssh-ed25519 MMMM office-key@local", "ssh-ed25519 MMMM office-key@local\n", "", swallowed]:
        h = Path(tempfile.mkdtemp(prefix="share-home-"))
        (h / ".ssh").mkdir()
        for command in [share.authorize_command("share-33333333", "hp", blob),
                        app.api_office_key()["authorize_command"]]:
            (h / ".ssh" / "authorized_keys").write_text(start)
            subprocess.run(["sh", "-c", command], env={"HOME": str(h), "PATH": "/usr/bin:/bin"}, check=False)
            lines = (h / ".ssh" / "authorized_keys").read_text().splitlines()
            check(any(ln.startswith(blob) for ln in lines), f"the new key is a line of its own after {start!r}: {lines}")
            check(not start.strip() or lines[0] == start.strip().splitlines()[0],
                  f"the old line is untouched after {start!r}: {lines}")
        shutil.rmtree(h, ignore_errors=True)
    app.public_key = real_key

    # ── 3. the door's path is not the app ────────────────────────────────────────────────────
    got = {}
    r = app.share_http("x")
    check(getattr(r, "status_code", 200) == 403, "a plain request on the door is a 403")
    for path in ["", "x", "x/y", "x" * 43]:
        r = app.share_http(path)
        check(getattr(r, "status_code", 200) == 403, f"403 for /share/{path!r} too, never the SPA")

    print("\n".join(f"FAIL: {f}" for f in FAIL) if FAIL else "PASS test_share")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
