#!/usr/bin/env python3
"""test_unminimize — the launcher brings back a window that was minimized, and only that one (DGO-2001).

This display has no taskbar, so a minimized window has no way back: Examplex's office, 2026-11-18, showed a black screen
while the app ran signed in behind it. The watch is read out of the launcher (desktop/autostart, the file the image
installs as /usr/local/bin/bina-claude-desktop) and run for one pass with xprop, xdotool and sleep stubbed:
a minimized (Iconic) window is activated, a normal one and a withdrawn one are not, and the watch is started once,
outside the loop that brings the app back. Restoring on a real display is proven live (the item's two throwaways).

    python3 apps/bina-claude/desktop/test_unminimize.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).with_name("autostart")

XPROP = r"""#!/bin/sh
# the window manager's list: 0x1 minimized, 0x2 normal (0x3, withdrawn, is in no list a window manager keeps)
if [ "$1" = -root ]; then echo "_NET_CLIENT_LIST(WINDOW): window id # 0x1, 0x2"; exit 0; fi
case "$2" in
  0x1) printf 'WM_STATE(WM_STATE):\n\t\twindow state: Iconic\n\t\ticon window: 0x0\n' ;;
  0x2) printf 'WM_STATE(WM_STATE):\n\t\twindow state: Normal\n\t\ticon window: 0x0\n' ;;
esac
"""
XDOTOOL = '#!/bin/sh\necho "$*" >> "$CALLS"\n'
# one pass: the watch's first sleep returns, its second ends the loop
SLEEP = '#!/bin/sh\n[ -f "$CALLS.slept" ] && exit 1\n: > "$CALLS.slept"\n'


def watch(text: str) -> str:
    """The un-minimize watch: the `( … ) &` block whose loop reads the window manager's list."""
    m = re.search(r"^\(\n(.*?_NET_CLIENT_LIST.*?)^\) &$", text, re.S | re.M)
    return m.group(1) if m else ""


class Unminimize(unittest.TestCase):
    def setUp(self):
        self.text = LAUNCHER.read_text(encoding="utf-8")
        self.block = watch(self.text)

    def test_the_launcher_has_the_watch(self):
        self.assertTrue(self.block, "the launcher has no un-minimize watch: a minimized window stays gone (DGO-2001)")

    def test_once_per_session_outside_the_relaunch_loop(self):
        self.assertTrue(self.block)
        self.assertLess(self.text.index(self.block), self.text.index("while :; do"),
                        "the watch must start before the loop that brings the app back, not once per relaunch")

    def test_only_the_minimized_window_is_brought_back(self):
        self.assertTrue(self.block)
        with tempfile.TemporaryDirectory() as t:
            bins = Path(t, "bin")
            bins.mkdir()
            for name, body in (("xprop", XPROP), ("xdotool", XDOTOOL), ("sleep", SLEEP)):
                (bins / name).write_text(body)
                (bins / name).chmod(0o755)
            calls = Path(t, "calls")
            env = {**os.environ, "PATH": f"{bins}:{os.environ.get('PATH', '/usr/bin:/bin')}", "CALLS": str(calls)}
            # its exit status is no answer (it runs in the background, and a pass ends on the last window's test)
            r = subprocess.run(["sh", "-c", self.block], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(r.stderr, "")
            self.assertEqual(calls.read_text().split("\n")[:-1] if calls.exists() else [], ["windowactivate 0x1"])


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=2) and 0)
