#!/usr/bin/env python3
"""test_drive_cancel — `drive cancel local_<id>` presses Esc only into a running turn it can be sure is on screen
(DGO-1684). Every path that presses NOTHING is checked here, against a fake app HOME; pressing itself needs the
app's display and is proven live.

    python3 apps/bina-claude/desktop/test_drive_cancel.py
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

SID = "local_aaaa"
CLI = "cli-aaaa"


def setup(status=None, other=None):
    for p in HOME.rglob("*"):
        if p.is_file():
            p.unlink()
    rec = HOME / ".config/Claude/claude-code-sessions/x/y" / f"{SID}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"sessionId": SID, "cliSessionId": CLI}))
    live = HOME / ".claude/sessions"
    live.mkdir(parents=True, exist_ok=True)
    if status:
        (live / "1.json").write_text(json.dumps({"hostSessionId": SID, "status": status}))
    if other:
        (live / "2.json").write_text(json.dumps({"hostSessionId": "local_bbbb", "status": other}))
    (HOME / ".claude/projects/p").mkdir(parents=True, exist_ok=True)
    return HOME / ".claude/projects/p" / f"{CLI}.jsonl"


def call():
    buf = io.StringIO()
    with redirect_stdout(buf):
        drive.cancel(SID)
    return json.loads(buf.getvalue().strip().splitlines()[-1])


class NothingPressed(unittest.TestCase):
    def setUp(self):
        drive.delivered_link = lambda url: self.fail("no link may be sent")
        drive.press = lambda *keys: self.fail("no key may be pressed")

    def test_an_idle_session_has_nothing_to_stop(self):
        setup(status="idle")
        self.assertEqual(call(), {"ok": True, "id": SID, "cancelled": False, "note": "no turn was running; nothing was pressed"})

    def test_a_session_waiting_on_the_owner_is_his_to_answer(self):
        setup(status="waiting")
        j = call()
        self.assertEqual((j["ok"], j["code"]), (False, "waiting"))

    def test_another_running_session_could_be_the_page_on_screen(self):
        setup(status="busy", other="busy")
        j = call()
        self.assertEqual((j["ok"], j["code"]), (False, "busy"))
        self.assertIn("local_bbbb", j["error"])

    def test_an_unknown_session(self):
        setup(status="busy")
        buf = io.StringIO()
        with redirect_stdout(buf):
            drive.cancel("local_nope")
        self.assertEqual(json.loads(buf.getvalue())["code"], "no-session")


class TheFocus(unittest.TestCase):
    """No key goes into a page the app's own log says is not this session's (Exampleu, 2026-11-09)."""

    def setUp(self):
        self.log = Path(tempfile.mkdtemp()) / "main.log"
        self.addCleanup(setattr, drive, "MAIN_LOG", drive.MAIN_LOG)
        drive.MAIN_LOG = str(self.log)

    def test_the_last_focus_line_says_which_page_is_up(self):
        self.assertIsNone(drive.focused(SID), "no log: unknown")
        self.log.write_text(f"2026 [info] [CCD] LocalSessions.setFocusedSession: sessionId={SID}\n")
        self.assertTrue(drive.focused(SID))
        with self.log.open("a") as f:
            f.write("2026 [info] [CCD] LocalSessions.setFocusedSession: sessionId=null\n")
        self.assertFalse(drive.focused(SID), "the New page is up")

    def test_cancel_presses_nothing_into_another_page(self):
        self.log.write_text("2026 [info] [CCD] LocalSessions.setFocusedSession: sessionId=local_owner\n")
        setup(status="busy")
        for name in ("delivered_link", "press"):
            self.addCleanup(setattr, drive, name, getattr(drive, name))
        drive.delivered_link = lambda url: True
        drive.press = lambda *keys: self.fail("no key may be pressed")
        j = call()
        self.assertEqual((j["ok"], j["code"]), (False, "not-focused"))


class TheComposerCheck(unittest.TestCase):
    def test_the_editors_compatibility_forms_are_the_same_words_and_a_different_word_is_not(self):
        self.assertEqual(drive.words("tasks …, 120 m² «ok»"), drive.words("tasks ..., 120 m2 «ok»"))
        self.assertNotEqual(drive.words("send to EXU-1"), drive.words("send to EXU-2"))
        self.assertNotEqual(drive.words("the whole brief"), drive.words("the whole"), "a cut text is not the text")


class TheMarker(unittest.TestCase):
    def test_only_the_apps_own_marker_counts_never_a_tool_output_quoting_it(self):
        t = setup()
        quoted = {"type": "user", "timestamp": "2026-11-09T19:00:05Z",
                  "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "[Request interrupted by user]"}]}}
        t.write_text(json.dumps(quoted) + "\n")
        since = drive.stamp("2026-11-09T19:00:00Z")
        self.assertFalse(drive.interrupted(str(t), since))
        marker = {"type": "user", "timestamp": "2026-11-09T19:00:06Z",
                  "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}}
        t.write_text(json.dumps(quoted) + "\n" + json.dumps(marker) + "\n")
        self.assertTrue(drive.interrupted(str(t), since))
        self.assertFalse(drive.interrupted(str(t), drive.stamp("2026-11-09T19:05:00Z")), "an older marker is not this Esc")


class TheHandOff(unittest.TestCase):
    """A link goes to the app only in the app's own session (its bus and keyring): without them the hand-off
    emptied the app's cookie store, measured on Exampleu 2026-11-09."""

    def proc(self, procs):
        root = Path(tempfile.mkdtemp())
        for pid, (cmd, env, started) in procs.items():
            d = root / str(pid)
            d.mkdir()
            (d / "cmdline").write_bytes(b"\0".join(cmd) + b"\0")
            (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0")
            fields = ["0"] * 30
            fields[19] = str(started)
            (d / "stat").write_text(f"{pid} (x) " + " ".join(fields))
        return str(root)

    def test_the_apps_own_session_is_found_from_its_newest_live_process(self):
        live = Path(tempfile.mkdtemp()) / "bus"
        live.write_text("")
        good = {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={live}", "GNOME_KEYRING_CONTROL": "/run/keyring",
                "XDG_RUNTIME_DIR": "/run", "XDG_CURRENT_DESKTOP": "openbox"}
        root = self.proc({
            10: ([b"/bin/sh", b"/usr/local/bin/bina-claude-desktop"], good, 900),          # not the app's
            11: ([b"/usr/lib/claude-desktop/claude-desktop", b"--no-sandbox"], {}, 500),     # the main one hides it
            12: ([b"/usr/lib/claude-desktop/chrome_crashpad_handler"], {**good, "SECRET_THING": "never"}, 510),
            13: ([b"/usr/lib/claude-desktop/chrome_crashpad_handler"],                       # an earlier session's
                 {**good, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}, 800),
            14: ([b"/usr/lib/claude-desktop/x"], {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={live}"}, 700),  # bus only
        })
        self.assertEqual(drive.app_env(root), good)

    def test_no_session_no_hand_off(self):
        self.assertIsNone(drive.app_env(self.proc({11: ([b"/usr/lib/claude-desktop/claude-desktop"], {"HOME": "/config"}, 1)})))
        for name in ("window", "app_env", "run"):
            self.addCleanup(setattr, drive, name, getattr(drive, name))
        drive.window = lambda: "1"
        drive.app_env = lambda proc="/proc": None
        drive.run = lambda *a, **k: self.fail("nothing may be handed over")
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            drive.link("claude://code/new")
        self.assertEqual(json.loads(buf.getvalue())["code"], "no-app-session")


if __name__ == "__main__":
    unittest.main(verbosity=2)
