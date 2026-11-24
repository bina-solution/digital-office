#!/usr/bin/env python3
"""test_drive_left — a refusal once the text went into a composer says so (`left`), and only then (DGO-2126).

`drive send` pastes the text, then asks once more whether the session took a turn meanwhile or the app shows another
page; a refusal there leaves the text in the app's composer, unsent. The owner may still send it from the app, so the
adapter must never try it again blind: its line drops it as «not known» instead of retrying it forever (each retry
would find «the composer is not empty», and one after the owner pressed Return would send it twice). The same holds
for `drive new` once its link filled the New page's composer. Checked against a fake app: the keys, the clipboard,
the session's live state, the answer's JSON.

    python3 apps/bina-claude/desktop/test_drive_left.py
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8")

os.environ["HOME"] = tempfile.mkdtemp()
_loader = importlib.machinery.SourceFileLoader("drive", str(Path(__file__).with_name("drive")))
_spec = importlib.util.spec_from_loader("drive", _loader)
drive = importlib.util.module_from_spec(_spec)
_loader.exec_module(drive)

TEXT = "הודעה מהתור (DGO-2126)"
SID = "local_left"


class FakeApp:
    """A composer and a clipboard that answer every copy; select-all selects, End collapses, a paste appends."""

    def __init__(self, composer=""):
        self.composer, self.clipboard, self.keys, self.now, self.selected = composer, b"owner's", [], 0.0, False

    def press(self, *keys):
        self.keys.extend(keys)
        for k in keys:
            if k == "ctrl+a":
                self.selected = True
            elif k == "End":
                self.selected = False
            elif k == "ctrl+v":
                self.composer = self.clipboard.decode() if self.selected else self.composer + self.clipboard.decode()
                self.selected = False
            elif k == "ctrl+c" and self.composer:
                self.clipboard = self.composer.encode()
        self.now += 0.3

    def sleep(self, s):
        self.now += s


def wire(app, states):
    """`states`: the session's live status, one per look (idle, idle, … then what it turned to)."""
    drive.typed = drive.pressed = False
    drive.press = app.press
    drive.clip_set = lambda data: setattr(app, "clipboard", data)
    drive.clip_get = lambda: app.clipboard
    drive.click_composer = lambda: app.keys.append("click")
    drive.time = types.SimpleNamespace(monotonic=lambda: app.now, sleep=app.sleep, time=lambda: app.now)
    drive.started = 0.0
    drive.records = lambda: {SID: {"sessionId": SID, "cliSessionId": "cli-left"}}
    drive.delivered_link = lambda url: True
    drive.focused = lambda sid: True
    looks = iter(states)
    drive.status = lambda sid: (next(looks, states[-1]), None)


def answer(call):
    buf = io.StringIO()
    with redirect_stdout(buf):
        call()
    return json.loads(buf.getvalue().strip().splitlines()[-1])


class Left(unittest.TestCase):
    def test_a_turn_begun_after_the_paste_leaves_the_text_and_says_so(self):
        app = FakeApp()
        wire(app, ["idle", "idle", "busy"])        # before the link, after it, then — after the paste — a turn runs
        j = answer(lambda: drive.send(SID, TEXT))
        self.assertEqual(app.composer, TEXT, "the text was pasted")
        self.assertNotIn("Return", app.keys, "never sent")
        self.assertEqual([j["ok"], j["code"], j.get("left")], [False, "busy", True])

    def test_a_refusal_before_the_paste_leaves_nothing_and_says_nothing(self):
        app = FakeApp()
        wire(app, ["busy"])
        j = answer(lambda: drive.send(SID, TEXT))
        self.assertEqual(app.composer, "")
        self.assertEqual([j["code"], "left" in j], ["busy", False])

    def test_the_owners_draft_is_not_pasted_over_and_nothing_is_left(self):
        app = FakeApp(composer="טיוטה שלו")
        wire(app, ["idle"])
        j = answer(lambda: drive.send(SID, TEXT))
        self.assertEqual(app.composer, "טיוטה שלו")
        self.assertEqual([j["code"], "left" in j], ["not-sent", False])

    def test_after_return_an_end_is_not_confirmed_never_left(self):
        drive.typed, drive.pressed = True, True
        j = answer(lambda: drive.out(False, code="not-confirmed", error="Return pressed, …"))
        self.assertEqual([j["code"], "left" in j], ["not-confirmed", False])

    def test_a_new_session_whose_link_filled_the_composer_says_left_when_refused(self):
        app = FakeApp()
        wire(app, ["idle"])
        drive.fill = lambda text, prefilled: "the composer the link filled did not give the text back"
        try:
            j = answer(lambda: drive.new(TEXT))
        finally:
            drive.fill = _loader_fill
        self.assertEqual([j["code"], j.get("left")], ["not-sent", True])


_loader_fill = drive.fill

if __name__ == "__main__":
    unittest.main(verbosity=2)
