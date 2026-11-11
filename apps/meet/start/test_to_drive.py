#!/usr/bin/env python3
"""The recordings into «קבצים» (meet-start `to_drive`): one file the drive takes no file that big for never keeps the
others out.

Exampleu, 2026-11-10: exu101's 388 MB video was refused by the drive (413, its ceiling there is 50 MB) every ten minutes
since 5.11, and the copier stopped the whole pass at it — exu101's own 27 MB sound and every meeting listed after it
never reached «קבצים». Run with Python ≥ 3.10 (server.py's own; the meet-start image): python3 test_to_drive.py —
nothing but this file and server.py, no network.
"""
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent
TMP = tempfile.mkdtemp(prefix="meet-to-drive-")
os.environ["MEET_RECORDINGS"] = TMP
sys.path.insert(0, str(HERE))
import server  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Stop(Exception):
    """Ends `to_drive`'s endless loop after the passes a test asks for."""


def http(code):
    return urllib.error.HTTPError("http://drive", code, "refused", {}, io.BytesIO(b""))


def run_passes(recs, refuse=(), error=None, passes=1, clock=None):
    """`passes` passes of to_drive over `recs`, the drive played in memory: (copied names, printed lines). `refuse`:
    names the drive takes no file that big for; `error`: what every copy raises instead (an outage)."""
    copied, said, slept = [], [], {"n": 0}
    held: set = set()
    real = (server.recordings, server._in_drive, server._to_drive_one, server._drive, server.time.sleep,
            server.time.time, server.time.monotonic)

    def to_drive_one(src, folder, name, mime):
        if error is not None:
            raise error
        if name in refuse:
            raise server.TooBig(400 * 2 ** 20)
        copied.append(name)
        held.add(f"{folder}/{name}")

    def sleep(s):
        slept["n"] += 1
        if clock is not None:
            clock[0] += 3600 * 25                           # each pass a day and an hour after the one before
        if slept["n"] >= passes:
            raise Stop

    server.recordings = lambda limit=500: recs
    server._in_drive = lambda path: path in held
    server._to_drive_one = to_drive_one
    server._drive = lambda *a, **k: (200, {})
    server.time.sleep = sleep
    if clock is not None:
        server.time.time = lambda: clock[0]
        server.time.monotonic = lambda: clock[0]
    import builtins
    builtins_print = builtins.print
    builtins.print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
    try:
        server.to_drive()
    except Stop:
        pass
    finally:
        builtins.print = builtins_print
        (server.recordings, server._in_drive, server._to_drive_one, server._drive, server.time.sleep,
         server.time.time, server.time.monotonic) = real
    return copied, said


def rec(session, stem, started):
    d = pathlib.Path(TMP, session)
    d.mkdir(parents=True, exist_ok=True)
    for ext, size in (("mp4", 1024), ("ogg", 256)):
        (d / f"{stem}.{ext}").write_bytes(b"x" * size)
    return {"session": session, "file": f"{stem}.mp4", "audio": f"{stem}.ogg", "done": True, "initiator": "owner",
            "started": started, "room": stem.split("_")[0], "mtime": 0}


OVER = "is more than «קבצים» takes"
BACKOFF = "copying the recordings into «קבצים»:"


class ToDrive(unittest.TestCase):
    def test_one_file_over_the_ceiling_never_stops_the_rest(self):
        recs = [rec("s101", "exu101_2026-11-05-15-57-16", "2026-11-05 15:57"),
                rec("s102", "exu102_2026-11-08-12-09-18", "2026-11-08 12:09")]
        copied, said = run_passes(recs, refuse={"exu101_2026-11-05-15-57-16.mp4"})
        self.assertEqual(copied, ["exu101_2026-11-05-15-57-16.ogg", "exu102_2026-11-08-12-09-18.mp4",
                                  "exu102_2026-11-08-12-09-18.ogg"],
                         "exu101's sound and the next meeting are copied though exu101's video is refused")
        self.assertEqual(sum(OVER in s for s in said), 1, f"the refused file is said, once: {said}")
        self.assertFalse(any(BACKOFF in s for s in said), "too big is no failure of the pass: no back-off")

    def test_said_once_a_day_and_asked_again_after_it(self):
        recs = [rec("s101", "exu101_2026-11-05-15-57-16", "2026-11-05 15:57")]
        _, said = run_passes(recs, refuse={"exu101_2026-11-05-15-57-16.mp4"}, passes=3)
        self.assertEqual(sum(OVER in s for s in said), 1, f"said once in three passes of one day: {said}")
        _, said = run_passes(recs, refuse={"exu101_2026-11-05-15-57-16.mp4"}, passes=3, clock=[1e9])
        self.assertEqual(sum(OVER in s for s in said), 3, f"asked again each day (a raised ceiling is found): {said}")

    def test_an_empty_recording_is_skipped_not_waited_on(self):
        empty = rec("s100", "e100_2026-11-04-10-00-00", "2026-11-04 10:00")
        pathlib.Path(TMP, "s100", "e100_2026-11-04-10-00-00.mp4").write_bytes(b"")
        recs = [empty, rec("s102", "exu102_2026-11-08-12-09-18", "2026-11-08 12:09")]
        copied, said = run_passes(recs)
        self.assertEqual(copied, ["e100_2026-11-04-10-00-00.ogg", "exu102_2026-11-08-12-09-18.mp4",
                                  "exu102_2026-11-08-12-09-18.ogg"], f"the empty video is skipped, the rest go: {said}")

    def test_an_outage_still_backs_off(self):
        recs = [rec("s102", "exu102_2026-11-08-12-09-18", "2026-11-08 12:09")]
        for err in (urllib.error.URLError("no route to host"), http(507), http(500)):
            copied, said = run_passes(recs, error=err)
            self.assertEqual(copied, [])
            self.assertTrue(any(BACKOFF in s for s in said) and not any(OVER in s for s in said),
                            f"{err}: said, and the whole pass waits ten minutes, as before — never «too big»: {said}")


class ToDriveOne(unittest.TestCase):
    """`_to_drive_one` itself: only the drive's «takes no file this big» is TooBig."""

    def setUp(self):
        self.src = pathlib.Path(TMP, "one.mp4")
        self.src.write_bytes(b"y" * (server.DRIVE_PIECE + 10))
        self.real = server._drive

    def tearDown(self):
        server._drive = self.real

    def play(self, post=None, patch=None, status=None, on_patch=None, on_post=None, delete_raises=None):
        calls = []

        def drive(method, path, body=None, data=None, headers=None, timeout=120):
            calls.append((method, len(data) if data is not None else None))
            if method == "POST":
                if post:
                    raise http(post)
                if on_post:
                    on_post()
                return 201, {"id": "u1"}
            if method == "PATCH":
                if patch:
                    raise http(patch)
                if on_patch:
                    on_patch()
                return 204, {}
            if method == "DELETE":
                if delete_raises:
                    raise delete_raises
                return 204, {}
            return 200, status or {"state": "done"}
        server._drive = drive
        return calls

    def test_the_opening_refused_is_too_big(self):
        self.play(post=413)
        with self.assertRaises(server.TooBig):
            server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")

    def test_the_opening_failing_otherwise_is_an_outage(self):
        for code in (507, 500, 503):                       # the drive's disk full, broken, down: never «too big»
            self.play(post=code)
            with self.assertRaises(urllib.error.HTTPError) as got:
                server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")
            self.assertNotIsInstance(got.exception, server.TooBig)

    def test_a_recording_replaced_while_copied_is_dropped_and_copied_again(self):
        new = pathlib.Path(TMP, "one.rebuilt")
        new.write_bytes(b"z" * (server.DRIVE_PIECE + 10))    # the SAME size: only the inode tells them apart
        calls = self.play(on_patch=lambda: os.replace(new, self.src))   # finalize.sh's mv, after the first piece
        with self.assertRaises(OSError) as got:
            server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")
        self.assertIn("replaced", str(got.exception))
        self.assertEqual([m for m, _ in calls], ["POST", "PATCH", "DELETE"],
                         f"the old copy is never finished: its session dropped before the last piece: {calls}")

    def test_a_one_piece_recording_replaced_is_dropped_too(self):
        small = pathlib.Path(TMP, "small.mp4")
        small.write_bytes(b"s" * 100)
        new = pathlib.Path(TMP, "small.rebuilt")
        new.write_bytes(b"t" * 100)
        calls = self.play(on_post=lambda: os.replace(new, small))
        with self.assertRaises(OSError):
            server._to_drive_one(str(small), "/פגישות/x", "small.mp4", "video/mp4")
        self.assertEqual([m for m, _ in calls], ["POST", "DELETE"], f"its only piece is never sent: {calls}")

    def test_a_failed_session_is_dropped(self):
        for status, raised in (({"state": "failed", "error": "x", "error_status": 413}, server.TooBig),
                               ({"state": "failed", "error": "disk"}, OSError)):
            calls = self.play(status=status)
            with self.assertRaises(raised):
                server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")
            self.assertEqual(calls[-1][0], "DELETE", f"its bytes never left on the drive's disk ({status}): {calls}")

    def test_a_drop_that_fails_never_hides_the_reason(self):
        for err in (ValueError("not JSON"), OSError("reset"), urllib.error.HTTPError("u", 500, "x", {}, None)):
            self.play(status={"state": "failed", "error": "x", "error_status": 413}, delete_raises=err)
            with self.assertRaises(server.TooBig):
                server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")

    def test_a_piece_refused_is_not_too_big(self):
        self.play(patch=413)
        with self.assertRaises(urllib.error.HTTPError):
            server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")

    def test_the_finish_refused_for_its_size_is_too_big(self):
        self.play(status={"state": "failed", "error": "החיבור הזה מקבל קבצים עד 64 MB", "error_status": 413})
        with self.assertRaises(server.TooBig):
            server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")
        self.play(status={"state": "failed", "error": "disk"})
        with self.assertRaises(OSError):
            server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")

    def test_no_piece_runs_past_the_size_declared(self):
        calls = self.play()
        server._to_drive_one(str(self.src), "/פגישות/x", "one.mp4", "video/mp4")
        pieces = [n for m, n in calls if m == "PATCH"]
        self.assertEqual(sum(pieces), server.DRIVE_PIECE + 10, f"exactly the size declared: {pieces}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
