"""test_computers.py — `./bbox dashboard computers` (computers.py, DGO-1052) on snapshots shaped like feed.py's.

    python3 apps/dashboard/test_computers.py

What is asked: each computer is one line with its state, and the line says what the screen says about it — a fall
the link recorded is "since <when>" (feed.py writes since_ts and no `when` for it), a sky row says why it has no
command door (its note), a down or away row says the link's error, a hollow row that it is not linked here; the
snapshot's age is printed and called stale past the collector's own healthcheck; --json is the file as written; a
collector that has written nothing yet, or a file that is not JSON, is one sentence and exit 1, never a traceback;
an unknown argument is exit 2.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import computers  # noqa: E402

NOW = 1794300000
STATE = {
    "at": NOW - 20,
    "computers": [
        {"id": "macbook", "office": "macbook", "name": "MacBook", "state": "up", "when": "כאן", "home": True},
        {"id": "hp-laptop", "office": "hp-laptop", "name": "HP", "state": "half", "when": "עכשיו",
         "note": "מחובר, אבל אי אפשר להריץ בו פקודות מכאן: אין SSH."},
        {"id": "portable-ubuntu", "office": "portable-ubuntu", "name": "Dell", "state": "down",
         "why": "handshake stale", "since_ts": NOW - 7200, "when_ts": NOW - 7200},
        {"id": "vps1", "office": "vps1", "name": "vps1", "state": "away", "when": "עכשיו", "since_ts": NOW - 600,
         "why": "הקישור הישיר לא עונה; HP מגיע אליו עכשיו", "reason": "handshake stale"},
        {"id": "dell", "office": "dell", "name": "Dell2", "state": "none", "when": "",
         "note": "מוצהר בעדר, אבל לא מקושר למחשב הזה."},
    ],
    "feed": [], "topics": [],
    "totals": {"all": 10, "completed": 4, "started": 3, "owner": 1},
    "errors": {"plane": "timed out"},
}


def run(argv, state=STATE, now=NOW, raw=None, missing=False):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        if not missing:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(raw if raw is not None else json.dumps(state, ensure_ascii=False))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = computers.main(["computers.py"] + argv, path=path, now=now)
        return rc, out.getvalue(), err.getvalue()


class Lines(unittest.TestCase):
    def setUp(self):
        self.rc, self.out, self.err = run([])
        self.lines = self.out.splitlines()

    def test_one_line_per_computer_and_the_age(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.lines[0], "snapshot: 20s old")
        self.assertEqual(len([ln for ln in self.lines if ln.startswith("  ") and "!" not in ln]), 5)

    def test_a_recorded_fall_says_since_when(self):
        dell = next(ln for ln in self.lines if "(portable-ubuntu)" in ln)
        self.assertIn("down", dell)
        self.assertIn("since 2026-", dell)
        self.assertIn("— handshake stale", dell)
        self.assertNotIn("  —", dell)                     # no empty `when` leaving a double space

    def test_a_sky_row_says_why_there_is_no_command_door(self):
        hp = next(ln for ln in self.lines if "(hp-laptop)" in ln)
        self.assertTrue(hp.lstrip().startswith("half"))
        self.assertIn("אין SSH", hp)

    def test_away_and_hollow_rows_say_what_the_screen_says(self):
        vps1 = next(ln for ln in self.lines if "(vps1)" in ln)
        self.assertIn("HP מגיע אליו עכשיו", vps1)
        self.assertIn("(vps1) עכשיו", vps1)               # heard now: the screen's word, not the direct link's fall
        self.assertNotIn("since", vps1)
        self.assertIn("לא מקושר", next(ln for ln in self.lines if "(dell)" in ln))

    def test_totals_and_errors(self):
        self.assertIn("items: 4 done of 10, 3 started, 1 the owner's", self.lines)
        self.assertIn("  ! plane: timed out", self.lines)


class Edges(unittest.TestCase):
    def test_stale_snapshot_is_called_stale(self):
        rc, out, _ = run([], now=NOW + 1000)
        self.assertEqual(rc, 0)
        self.assertIn("stale", out.splitlines()[0])

    def test_json_is_the_file_as_written(self):
        raw = json.dumps(STATE, ensure_ascii=False) + "\n"
        rc, out, _ = run(["--json"], raw=raw)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), STATE)
        self.assertTrue(out.endswith("}\n"))

    def test_no_snapshot_yet_is_one_sentence_and_exit_1(self):
        rc, out, err = run([], missing=True)
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("no snapshot yet", err)
        self.assertNotIn("Traceback", err)

    def test_not_json_is_exit_1(self):
        self.assertEqual(run([], raw="{half")[0], 1)
        self.assertEqual(run([], raw="[1, 2]")[0], 1)

    def test_unknown_argument_is_exit_2(self):
        rc, _, err = run(["--bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("--bogus", err)

    def test_before_the_first_plane_read(self):
        state = dict(STATE, totals=None, errors={})
        rc, out, _ = run([], state=state)
        self.assertEqual(rc, 0)
        self.assertNotIn("items:", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
