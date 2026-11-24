"""`bbox meet move` end to end on this machine (DGO-1861): two "machines" that are two folders, each with its own
recordings volume and work folder, driven by move.py exactly as the computers app would drive them — host.py and
meet_move.py installed and run there by `bash -c`, the carry by a tar stream (an SSH target) and by exec pieces (a
target behind a link). What it holds: the meeting arrives byte for byte with its times, nothing else moves, the source's
backup is there, a dry run writes nothing, and the source loses the meeting only after the target verified it and only
while it is still the backup's copy.

Runnable with pytest, and (because the office's own boxes do not always have pytest) directly:

    python3 apps/meet/tools/move/test_move.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)

import host  # noqa: E402
import move  # noqa: E402

with open(os.path.join(HERE, "host.py"), encoding="utf-8") as _f:
    CODE = _f.read()
with open(os.path.join(REPO, "scripts", "client-move", "meet_move.py"), encoding="utf-8") as _f:
    TOOL = _f.read()
UUID, OTHER = "a742e5ab-bdf4-4a49-8287-4f6a2a799c54", "b76d0a14-0d74-467c-8de5-88c19dae061f"
STEM = "exu104_2026-11-11-20-20-50"


class LocalMachine(move.Machine):
    """A machine that is this one: the command runs under bash here; streams=False is a target behind a link."""

    def __init__(self, cid, work_root, streams=True, drops=None, cuts=None):
        super().__init__(cid, work_root)
        self.streams, self.calls = streams, []
        self.drops = dict(drops or {})                  # a word of a command → times ssh never reaches it (255)
        self.cuts = dict(cuts or {})                    # … → times it RUNS, and the answer is lost (255, no ssh words)

    def _run(self, command, stdin, timeout):
        self.calls.append(command)
        for word, left in self.drops.items():
            if word in command and left:
                self.drops[word] = left - 1
                return 255, "", "Connection timed out during banner exchange"
        p = subprocess.run(["bash", "-c", command], input=(stdin or "").encode(), capture_output=True, timeout=timeout)
        for word, left in self.cuts.items():
            if word in command and left:
                self.cuts[word] = left - 1
                return 255, "", ""
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

    def stream_argv(self, command):
        return ["bash", "-c", command] if self.streams else None


def write(path, data, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if mtime:
        os.utime(path, (mtime, mtime))


def digest(root):
    """{relative path: (sha256, mtime)} of every file under root."""
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as h:
                out[os.path.relpath(p, root)] = (hashlib.sha256(h.read()).hexdigest(), int(os.stat(p).st_mtime))
    return out


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="meet-move-test-")
        self.src_root, self.dst_root = os.path.join(self.tmp, "src-vol"), os.path.join(self.tmp, "dst-vol")
        self.src_work, self.dst_work = os.path.join(self.tmp, "src-work"), os.path.join(self.tmp, "dst-work")
        rec = os.path.join(self.src_root, "recordings")
        # the meeting: a video of 3.5 pieces (CHUNK is 1 MiB here), its sound, the recorder's notes, an empty file
        write(f"{rec}/{UUID}/{STEM}.mp4", os.urandom(3 * (1 << 20) + 12345), 1762890300)
        write(f"{rec}/{UUID}/{STEM}.ogg", os.urandom(700 << 10), 1762890360)
        write(f"{rec}/{UUID}/metadata.json", b'{"meeting_url": "https://meet/exu104"}', 1762890300)
        write(f"{rec}/{UUID}/{STEM}.capture.json", "{\"note\": \"הקלטה\"}".encode(), 1762890360)
        write(f"{rec}/{UUID}/{STEM}.silence.json", b"", 1762890360)
        # another room's meeting, which must not move
        write(f"{rec}/{OTHER}/exu106_2026-11-17-11-01-22.mp4", os.urandom(1000), 1763370000)
        write(f"{rec}/{OTHER}/metadata.json", b"{}", 1763370000)
        # the target: its own meetings already
        write(f"{self.dst_root}/recordings/5fd3f98c-5713-426f-a463-caa8f58933fe/z102_2026-11-18-11-14-12.mp4", b"z")
        self.before = digest(f"{rec}/{UUID}")
        move.CHUNK, move.PIECE, move.RETRY_WAIT = 1 << 20, 300 << 10, 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def machines(self, streams=True, drops=None):
        return (LocalMachine("computer_local-local.exampleu", self.src_work),
                LocalMachine("computer_ssh-vps1", self.dst_work, streams, drops))

    def run_move(self, streams=True, drops=None, src_cuts=None, **kw):
        src, dst = self.machines(streams, drops)
        src.cuts = dict(src_cuts or {})
        rc = move.move("exu104", src, dst, CODE, TOOL, src_root=self.src_root, dst_root=self.dst_root, **kw)
        return rc, src, dst

    def backup(self):
        runs = os.listdir(self.src_work)
        self.assertEqual(len(runs), 1)
        return os.path.join(self.src_work, runs[0], "staged")

    def test_moves_the_meeting_byte_for_byte_and_removes_it_after(self):
        rc, src, dst = self.run_move(remove=True)
        self.assertEqual(rc, 0)
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before, "same bytes, same times")
        self.assertFalse(os.path.exists(f"{self.src_root}/recordings/{UUID}"), "gone from the source")
        self.assertTrue(os.path.isdir(f"{self.src_root}/recordings/{OTHER}"), "another room's meeting stays")
        self.assertFalse(os.path.exists(f"{self.dst_root}/recordings/{OTHER}"), "and does not move")
        self.assertEqual(digest(os.path.join(self.backup(), "recordings", UUID)), self.before, "the backup is whole")
        with open(os.path.join(self.backup(), "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        self.assertEqual((man["room"], man["units"], len(man["files"])), ("exu104", [UUID], 5))
        self.assertEqual(os.listdir(self.dst_work), [], "the carried copy is not left on the target")
        self.assertTrue(any(" read " in c for c in src.calls) and not any(" append " in c for c in dst.calls),
                        "an SSH target takes the meeting as one stream")

    def test_a_target_behind_a_link_takes_it_by_exec_pieces(self):
        rc, src, dst = self.run_move(streams=False)
        self.assertEqual(rc, 0)
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)
        self.assertGreater(sum(" append " in c for c in dst.calls), 10, "pieces of PIECE bytes")
        self.assertEqual(digest(f"{self.src_root}/recordings/{UUID}"), self.before, "without --remove the source keeps it")

    def test_run_again_keeps_what_is_there(self):
        self.assertEqual(self.run_move()[0], 0)
        shutil.rmtree(self.src_work)
        rc, src, dst = self.run_move()
        self.assertEqual(rc, 0)
        self.assertFalse(any(" read " in c for c in src.calls), "what the target has byte for byte is not carried again")
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)

    def test_a_target_copy_with_other_bytes_is_carried_and_refused(self):
        self.assertEqual(self.run_move()[0], 0)
        with open(f"{self.dst_root}/recordings/{UUID}/{STEM}.ogg", "r+b") as f:
            f.write(b"X")                                          # same size, other bytes
        with self.assertRaises(move.Refused):
            self.run_move(remove=True)
        self.assertEqual(digest(f"{self.src_root}/recordings/{UUID}"), self.before, "the source keeps it")

    def test_a_target_that_did_not_answer_is_asked_again(self):
        rc, src, dst = self.run_move(drops={"meet_move.py place": 2}, remove=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sum("meet_move.py place" in c for c in dst.calls), 3, "asked three times, answered the third")
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)
        self.assertFalse(os.path.exists(f"{self.src_root}/recordings/{UUID}"))

    def test_resume_finishes_a_run_without_carrying_it_again(self):
        with self.assertRaises(move.Unreachable):                 # place never answers: the run stops after the carry
            self.run_move(drops={"meet_move.py place": move.TRIES}, remove=True)
        self.assertEqual(digest(f"{self.src_root}/recordings/{UUID}"), self.before, "nothing removed")
        self.assertFalse(os.path.exists(f"{self.dst_root}/recordings/{UUID}"), "nothing placed")
        run = os.listdir(self.src_work)[0]
        rc, src, dst = self.run_move(resume=run, remove=True)
        self.assertEqual(rc, 0)
        self.assertFalse(any(" read " in c or " stage " in c for c in src.calls), "neither staged nor carried again")
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)
        self.assertFalse(os.path.exists(f"{self.src_root}/recordings/{UUID}"))
        self.assertEqual(os.listdir(self.src_work), [run], "one backup")
        with self.assertRaises(move.Refused):
            self.run_move(resume="exu105-20261119-162125")

    def test_a_step_cut_off_after_it_ran_is_not_asked_again_and_resume_finds_it_done(self):
        with self.assertRaises(move.Unreachable):              # remove ran, its answer was lost: never run beside it
            self.run_move(src_cuts={"host.py remove": 1}, remove=True)
        self.assertFalse(os.path.exists(f"{self.src_root}/recordings/{UUID}"), "it did run")
        rc, src, dst = self.run_move(resume=os.listdir(self.src_work)[0], remove=True)
        self.assertEqual(rc, 0, "the resume finds the meeting removed in this run, and stops there")
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)

    def test_a_meeting_gone_some_other_way_is_not_taken_for_removed(self):
        src, dst = self.machines()
        src.drops = {" read ": move.TRIES}                         # the carry never starts: nothing reaches the target
        with self.assertRaises(move.Unreachable):
            move.move("exu104", src, dst, CODE, TOOL, src_root=self.src_root, dst_root=self.dst_root, remove=True)
        shutil.rmtree(f"{self.src_root}/recordings/{UUID}")       # then a person deletes it on the source
        with self.assertRaises(move.Refused):
            self.run_move(resume=os.listdir(self.src_work)[0], remove=True)

    def test_remove_asked_again_after_it_was_done_says_so(self):
        staged = os.path.join(self.tmp, "staged")
        self.host("stage", self.src_root, "exu104", staged)
        self.assertEqual(self.host("remove", self.src_root, staged)["removed"], [UUID])
        again = self.host("remove", self.src_root, staged)
        self.assertEqual((again["ok"], again.get("already")), (True, True))

    def test_a_resume_after_the_source_changed_is_refused(self):
        with self.assertRaises(move.Unreachable):
            self.run_move(drops={"meet_move.py place": move.TRIES})
        write(f"{self.src_root}/recordings/{UUID}/flow/data.js", b"window.MEETING = {}")
        with self.assertRaises(move.Refused):
            self.run_move(resume=os.listdir(self.src_work)[0], remove=True)
        self.assertTrue(os.path.isfile(f"{self.src_root}/recordings/{UUID}/{STEM}.mp4"))

    def test_a_recording_still_being_finalized_does_not_move(self):
        write(f"{self.src_root}/recordings/{UUID}/{STEM}.holes.json.part", b"{")
        with self.assertRaises(move.Refused):
            self.run_move()
        os.remove(f"{self.src_root}/recordings/{UUID}/{STEM}.holes.json.part")
        os.remove(f"{self.src_root}/recordings/{UUID}/{STEM}.ogg")
        os.utime(f"{self.src_root}/recordings/{UUID}/{STEM}.mp4")      # a fresh video with no sound yet
        with self.assertRaises(move.Refused):
            self.run_move()

    def test_any_piece_size_streams(self):
        move.CHUNK = 1_000_003                                    # not a multiple of tarfile's 16 KiB reads
        self.assertEqual(self.run_move()[0], 0)
        self.assertEqual(digest(f"{self.dst_root}/recordings/{UUID}"), self.before)

    def test_a_piece_sent_twice_is_kept_once(self):
        path = os.path.join(self.tmp, "piece")
        for _ in range(2):
            p = subprocess.run([sys.executable, os.path.join(HERE, "host.py"), "append", path, "0"],
                               input="aGVsbG8=", capture_output=True, text=True)
            self.assertIn('"ok": true', p.stdout)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_a_dry_run_writes_nothing(self):
        dst_before = digest(self.dst_root)
        rc, src, dst = self.run_move(dry_run=True, remove=True)
        self.assertEqual(rc, 0)
        self.assertEqual(digest(self.dst_root), dst_before)
        self.assertEqual(digest(f"{self.src_root}/recordings/{UUID}"), self.before)
        self.assertFalse(os.path.exists(self.src_work) or os.path.exists(self.dst_work))

    def test_other_bytes_on_the_target_refuse_and_the_source_keeps_it(self):
        write(f"{self.dst_root}/recordings/{UUID}/{STEM}.ogg", b"another recording")
        with self.assertRaises(move.Refused):
            self.run_move(remove=True)
        self.assertEqual(digest(f"{self.src_root}/recordings/{UUID}"), self.before)
        with open(f"{self.dst_root}/recordings/{UUID}/{STEM}.ogg", "rb") as f:
            self.assertEqual(f.read(), b"another recording", "a meeting is never written over")

    def test_a_meeting_still_recording_does_not_move(self):
        os.remove(f"{self.src_root}/recordings/{UUID}/metadata.json")
        with self.assertRaises(move.Refused):
            self.run_move()
        self.assertFalse(os.path.exists(f"{self.dst_root}/recordings/{UUID}"))

    def test_remove_refuses_a_source_that_changed_after_its_backup(self):
        staged = os.path.join(self.tmp, "staged")
        self.assertEqual(self.host("stage", self.src_root, "exu104", staged)["ok"], True)
        write(f"{self.src_root}/recordings/{UUID}/{STEM}.live.txt", b"written after the stage")
        res = self.host("remove", self.src_root, staged)
        self.assertFalse(res["ok"])
        self.assertTrue(os.path.isfile(f"{self.src_root}/recordings/{UUID}/{STEM}.mp4"), "nothing was removed")

    def host(self, *args):
        """host.py as a move installs it: in a folder of its own, beside meet_move.py."""
        tools = os.path.join(self.tmp, "tools")
        if not os.path.isdir(tools):
            os.makedirs(tools)
            write(os.path.join(tools, "host.py"), CODE.encode())
            write(os.path.join(tools, "meet_move.py"), TOOL.encode())
        p = subprocess.run([sys.executable, os.path.join(tools, "host.py"), *args], capture_output=True, text=True)
        return json.loads(next(x for x in p.stdout.splitlines() if x.startswith("RESULT "))[7:])

    def test_office_names(self):
        self.assertEqual(move.cid_of("local"), "computer_local-local")
        self.assertEqual(move.cid_of("exampleu"), "computer_local-local.exampleu")
        self.assertEqual(move.cid_of("computer_ssh-00000005"), "computer_ssh-00000005")


class DriveTest(unittest.TestCase):
    """host.DRIVE_CODE, as meet-start runs it, against a Drive that answers like the office's."""

    def run_drive(self, tree, trash):
        trashed = []

        class FakeServer:
            DRIVE_FOLDER = "פגישות"

            @staticmethod
            def quote(v):
                return v

            @staticmethod
            def _drive(method, path, body=None):
                if method == "POST":
                    trashed.extend(body["ids"])
                    return 200, {"ok": True, "count": len(body["ids"])}
                at = path.split("path=", 1)[1]
                node = tree.get(at, {})
                return 200, {"folder": {"id": node.get("id")}, "files": [{"name": n} for n in node.get("files", [])],
                             "folders": [{"name": n, "id": tree.get(at + "/" + n, {}).get("id")}
                                         for n in node.get("folders", [])]}

        saved = sys.modules.get("server"), list(sys.argv), sys.stdout
        sys.modules["server"] = FakeServer
        sys.argv = ["-", "exu104", json.dumps([STEM]), "1" if trash else "0"]
        out = sys.stdout = __import__("io").StringIO()
        try:
            exec(compile(host.DRIVE_CODE, "drive", "exec"), {})
        finally:
            sys.modules.pop("server")
            if saved[0] is not None:
                sys.modules["server"] = saved[0]
            sys.argv, sys.stdout = saved[1], saved[2]
        return json.loads(out.getvalue().split("RESULT ", 1)[1]), trashed

    def test_only_meets_own_copies_go_to_the_trash(self):
        own = {"/פגישות": {"folders": ["2026-11-11 · exu104", "2026-11-17 · exu106"]},
               "/פגישות/2026-11-11 · exu104": {"id": "ld1", "files": [STEM + ".ogg", "תמלול — exu104.txt"],
                                                "folders": [".meet-flow"]},
               "/פגישות/2026-11-11 · exu104/.meet-flow": {"files": ["first.json"]},
               "/פגישות/2026-11-17 · exu106": {"id": "ld2", "files": ["x.ogg"]}}
        res, trashed = self.run_drive(own, trash=True)
        self.assertEqual(trashed, ["ld1"], "the room's folder, and no other room's")
        self.assertEqual(res["folders"][0]["other"], [])

        added = dict(own)
        added["/פגישות/2026-11-11 · exu104/.meet-flow"] = {"files": ["first.json", "edits.jsonl"]}
        added["/פגישות/2026-11-11 · exu104"] = dict(own["/פגישות/2026-11-11 · exu104"],
                                                     files=[STEM + ".ogg", "הסכם.pdf"])
        res, trashed = self.run_drive(added, trash=True)
        self.assertEqual(trashed, [], "what a person added keeps the folder")
        self.assertEqual(sorted(res["folders"][0]["other"]), [".meet-flow/", "הסכם.pdf"])

    def test_another_meeting_of_the_room_is_not_touched(self):
        tree = {"/פגישות": {"folders": ["2026-11-12 · exu104", "2026-11-11 · exu104"]},
                "/פגישות/2026-11-12 · exu104": {"id": "ld3", "files": ["exu104_2026-11-12-09-00-00.ogg"]},
                "/פגישות/2026-11-11 · exu104": {"id": "ld4", "files": ["תמלול — exu104.txt"]}}
        res, trashed = self.run_drive(tree, trash=True)
        self.assertEqual(trashed, [], "another day's recording, and a day with none of the moved files")
        self.assertTrue(all(f["other"] for f in res["folders"]))


if __name__ == "__main__":
    unittest.main()
