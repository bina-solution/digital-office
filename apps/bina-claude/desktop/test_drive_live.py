#!/usr/bin/env python3
"""test_drive_live — `drive live` names the live files a killed process left behind, and only those (DGO-2126). The
adapter's cap of running turns counts the app's «busy» live files; one whose `claude` the memory killer took would
hold a slot until the app restarts, so the desktop's own /proc says which are gone. Checked here against a fake app
HOME and this process's own /proc: a pid that is gone, a pid reused by another process, a live one, one that cannot
be judged. It presses nothing and takes no lock.

    python3 apps/bina-claude/desktop/test_drive_live.py
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8")

HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)
_loader = importlib.machinery.SourceFileLoader("drive", str(Path(__file__).with_name("drive")))
_spec = importlib.util.spec_from_loader("drive", _loader)
drive = importlib.util.module_from_spec(_spec)
_loader.exec_module(drive)


def own_ticks():
    """This process's start in clock ticks, /proc/self/stat field 22 (an older file's procStart)."""
    with open("/proc/self/stat", encoding="utf-8") as f:
        return f.read().rsplit(")", 1)[1].split()[19]


def own_lstart():
    """This process's start as Claude Code writes procStart: `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>`."""
    import subprocess
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}).stdout
    return " ".join(out.split())


def own_domain():
    """This system's pidDomain as Claude Code writes it on Linux: linux:<machine-id>:<readlink /proc/self/ns/pid>."""
    try:
        machine = open("/etc/machine-id", encoding="utf-8").read().strip()
    except OSError:
        machine = ""
    return f"linux:{machine}:{os.readlink('/proc/self/ns/pid')}"


def gone_pid():
    """A pid no process has right now."""
    pid = 4194000
    while os.path.exists(f"/proc/{pid}"):
        pid -= 1
    return pid


@unittest.skipUnless(os.path.exists("/proc/self/stat"), "needs a /proc (the desktop's container has one)")
class Live(unittest.TestCase):
    def setUp(self):
        live = HOME / ".claude/sessions"
        live.mkdir(parents=True, exist_ok=True)
        for p in live.iterdir():
            p.unlink()
        files = {
            "1.json": {"hostSessionId": "local_gone", "status": "busy", "pid": gone_pid(), "procStart": "Mon Jan  5 01:02:03 2026", "startedAt": 11},
            "2.json": {"hostSessionId": "local_reused", "status": "busy", "pid": os.getpid(), "procStart": "Mon Jan  5 01:02:03 2026", "startedAt": 22},
            "3.json": {"hostSessionId": "local_alive", "status": "busy", "pid": os.getpid(), "procStart": own_lstart(), "startedAt": 33},
            "4.json": {"hostSessionId": "local_no_pid", "status": "busy", "startedAt": 44},
            "6.json": {"hostSessionId": "local_alive_ticks", "status": "busy", "pid": os.getpid(), "procStart": own_ticks(), "startedAt": 66},
            "7.json": {"hostSessionId": "local_reused_ticks", "status": "busy", "pid": os.getpid(), "procStart": "1", "startedAt": 77},
            # stored as Claude Code stores it — trimmed only: a one-digit day keeps ps's double space
            "8.json": {"hostSessionId": "local_alive_spaced", "status": "busy", "pid": os.getpid(),
                       "procStart": own_lstart().replace(" ", "  ", 1), "startedAt": 88},
            # a pid of another system's processes (a file Windows wrote): not judged here
            "9.json": {"hostSessionId": "local_other_domain", "status": "busy", "pid": gone_pid(), "pidDomain": "win32",
                       "procStart": "Mon Jan  5 01:02:03 2026", "startedAt": 99},
            # this system's own domain, as Claude Code writes it on Linux: judged — its process is gone
            "10.json": {"hostSessionId": "local_gone_here", "status": "busy", "pid": gone_pid(), "pidDomain": own_domain(),
                        "procStart": "Mon Jan  5 01:02:03 2026", "startedAt": 100},
            # another Linux system's pid space (another machine-id, another namespace): not judged here
            "11.json": {"hostSessionId": "local_other_linux", "status": "busy", "pid": gone_pid(),
                        "pidDomain": "linux:0123456789abcdef:pid:[4026531836]", "procStart": "Mon Jan  5 01:02:03 2026", "startedAt": 110},
        }
        for name, j in files.items():
            (live / name).write_text(json.dumps(j))
        (live / "5.json").write_text("{not json")

    def run_live(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = drive.main(["live"])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_names_only_what_is_shown_gone(self):
        rc, j = self.run_live()
        self.assertEqual(rc, 0)
        self.assertTrue(j["ok"])
        self.assertEqual(j["dead"], [{"file": "1.json", "startedAt": 11}, {"file": "10.json", "startedAt": 100},
                                     {"file": "2.json", "startedAt": 22}, {"file": "7.json", "startedAt": 77}],
                         "a pid that is gone, and one another process now has (by its ps start, or an older file's "
                         "ticks); never a live one — its procStart as Claude Code writes it — or one it cannot judge")

    def test_presses_nothing_and_takes_no_lock(self):
        self.run_live()
        self.assertFalse(os.path.exists(drive.LOCK), "no lock file: a drive in progress is never in its way")


if __name__ == "__main__":
    unittest.main(verbosity=2)
