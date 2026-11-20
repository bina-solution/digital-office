#!/usr/bin/env python3
"""test_drive_copy — the composer is read back by select-all + copy before Return, and a STALLED app answers that
copy late (DGO-2037: on the HP, 2026-11-19, the app's main process was blocked 0.5–1.1 s at a time while git status
timed out on the office's slow checkout; a composer holding the whole text was reported as not holding it, and
nothing was sent from Azaria). Checked against a fake app: the keys pressed, the clipboard, a fake clock.

    python3 apps/bina-claude/desktop/test_drive_copy.py
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8")

os.environ["HOME"] = tempfile.mkdtemp()
_loader = importlib.machinery.SourceFileLoader("drive", str(Path(__file__).with_name("drive")))
_spec = importlib.util.spec_from_loader("drive", _loader)
drive = importlib.util.module_from_spec(_spec)
_loader.exec_module(drive)

TEXT = "בדיקה מעזריה החדשה (DGO-2037). ענה במילה אחת בלבד: עובד."


class FakeApp:
    """The composer and the clipboard of a fake app that answers the n-th copy only (a stalled main process).
    Select-all selects; End collapses; a paste replaces a selection and is appended otherwise. `late` makes the app
    answer one more copy only after the clipboard was put back (the copy queued in a stalled app)."""

    def __init__(self, composer="", answers_from=1, never=False, late=False):
        self.composer, self.answers_from, self.never, self.late = composer, answers_from, never, late
        self.clipboard, self.keys, self.copies, self.now, self.selected = b"owner's clipboard", [], 0, 0.0, False

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
            elif k == "ctrl+c":
                self.copies += 1
                if not self.never and self.copies >= self.answers_from and self.composer:
                    self.clipboard = self.composer.encode()
        self.now += 0.3

    def clip_set(self, data):
        self.clipboard = data
        if self.late and data == b"owner's clipboard" and self.composer:
            self.late = False
            self._answer_late = True

    def clip_get(self):
        if getattr(self, "_answer_late", False):        # the queued copy lands now, over what was put back
            self._answer_late = False
            self.clipboard = self.composer.encode()
        return self.clipboard

    def sleep(self, s):
        self.now += s


def wire(app):
    drive.press = app.press
    drive.clip_set = app.clip_set
    drive.clip_get = app.clip_get
    drive.click_composer = lambda: app.keys.append("click")
    drive.time = types.SimpleNamespace(monotonic=lambda: app.now, sleep=app.sleep, time=lambda: app.now)
    drive.started = 0.0


class ReadBack(unittest.TestCase):
    def test_a_stalled_app_answers_the_third_copy_and_the_text_is_there(self):
        app = FakeApp(composer=TEXT, answers_from=3)
        wire(app)
        self.assertIsNone(drive.fill(TEXT, True))
        self.assertEqual(app.copies, 3, "asked again until the app answered")
        self.assertNotIn("Return", app.keys, "fill never sends")
        self.assertNotIn("click", app.keys, "the link filled the composer: nothing is clicked")
        self.assertEqual(app.keys[-1], "End", "the selection is collapsed, ready for Return")
        self.assertEqual(app.clipboard, b"owner's clipboard", "the clipboard is put back")

    def test_a_composer_that_never_gives_the_text_back_stops_within_the_patience(self):
        app = FakeApp(composer=TEXT, never=True)
        wire(app)
        why = drive.fill(TEXT, True)
        self.assertIn("did not give the text back", why)
        self.assertLessEqual(app.now, drive.COPY_PATIENCE + 2, "bounded by the patience, not the call's deadline")
        self.assertNotIn("End", app.keys, "nothing to collapse: the call stops")
        self.assertEqual(app.clipboard, b"owner's clipboard", "the clipboard is put back")

    def test_an_empty_composer_is_read_once_then_the_pasted_text_is_awaited(self):
        app = FakeApp(composer="", answers_from=2)
        wire(app)
        self.assertIsNone(drive.fill(TEXT, False))
        self.assertEqual(app.keys[0], "click", "the click comes first")
        before_paste = app.keys[:app.keys.index("ctrl+v")]
        self.assertEqual(before_paste.count("ctrl+c"), 1, "an empty composer is asked once")
        self.assertEqual(before_paste[-1], "End", "the selection is collapsed before the paste")

    def test_a_draft_a_late_copy_hid_is_not_pasted_over(self):
        app = FakeApp(composer="טיוטה שלו", never=True)       # the app never answers in time: the draft reads as empty
        wire(app)
        why = drive.fill(TEXT, False)
        self.assertIn("not in the composer", why, "nothing is sent")
        self.assertTrue(app.composer.startswith("טיוטה שלו"), "his draft is still there, whole")
        self.assertNotIn("Return", app.keys)

    def test_a_copy_answered_after_the_clipboard_was_put_back_is_undone_after_the_keys(self):
        app = FakeApp(composer=TEXT, answers_from=1, late=True)
        wire(app)
        self.assertIsNone(drive.fill(TEXT, True))
        waited = app.now
        drive.clipboard_again()                  # main() runs it once the call's keys (Return included) are done
        self.assertEqual(app.clipboard, b"owner's clipboard", "the owner's clipboard is his again")
        self.assertGreater(app.now, waited, "…and that wait is after the keys, not between the read-back and Return")

    def test_a_draft_of_the_owners_is_left_alone(self):
        app = FakeApp(composer="טיוטה שלו")
        wire(app)
        why = drive.fill(TEXT, False)
        self.assertIn("not empty", why)
        self.assertNotIn("ctrl+v", app.keys, "nothing is pasted over his draft")
        self.assertEqual(app.composer, "טיוטה שלו")

    def test_the_wrong_text_is_never_taken_for_the_right_one(self):
        app = FakeApp(composer=TEXT + " ועוד מילה", answers_from=1)
        wire(app)
        self.assertIn("did not give the text back", drive.fill(TEXT, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
