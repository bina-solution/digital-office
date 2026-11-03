"""test_feed_live.py — the control centre's live Plane layer (feed.py), against a FAKE Plane (no network).

    python3 apps/dashboard/test_feed_live.py

What is asked: between two full reads, one ask for the items changed last turns each moved state into a line of
today's log at once (closed, started, cancelled, reopened, opened); the topics' bars and the tiles follow; an
item changed without a state move is no line; a page where every row is new asks for the full read now; a close
the live ask saw and the full read rebuilt is one line, not two; the day's log keeps every line of 24 hours
(not the last 16); and the lines only the live ask could see survive a restart.
"""
import importlib.util
import json
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(DASHBOARD_STATE=os.path.join(TMP, "state.json"), DASHBOARD_HERD=os.path.join(TMP, "none.yaml"))
SPEC = importlib.util.spec_from_file_location("dashboard_feed", os.path.join(HERE, "feed.py"))
f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f)


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".%06d+00:00" % int((ts % 1) * 1e6)


NOW = time.time()
STATES = [{"id": "s_back", "group": "backlog"}, {"id": "s_go", "group": "started"},
          {"id": "s_done", "group": "completed"}, {"id": "s_no", "group": "cancelled"}]


def issue(n, state, upd, made=None, done=None, labels=()):
    return {"id": "i%d" % n, "sequence_id": n, "name": "item %d" % n, "state": state, "labels": list(labels),
            "created_at": iso(made or NOW - 5 * 86400), "updated_at": iso(upd),
            "completed_at": iso(done) if done else None}


class Live(unittest.TestCase):
    def setUp(self):
        self.issues = [issue(n, "s_back", NOW - 3600) for n in range(1, 7)]
        self.issues[0]["labels"] = ["l_owner"]
        self.recent = []                            # what `?order_by=-updated_at` answers, newest first

        def pages(base, path):
            if path == "/projects/":
                return [{"id": "p", "identifier": "DGO"}]
            if path.endswith("/states/"):
                return STATES
            if path.endswith("/labels/"):
                return [{"id": "l_owner", "name": "בעלים"}]
            if path.endswith("/issues/"):
                return self.issues
            if path.endswith("/modules/"):
                return [{"id": "m1", "name": "topic"}]
            if path.endswith("/module-issues/"):
                return [{"issue": "i%d" % n} for n in range(1, 7)]
            return []

        def get(url, timeout=8):
            assert "order_by=-updated_at" in url, url
            if "per_page=1" in url and "per_page=10" not in url:      # the full read's watermark, before its pages
                return {"results": sorted(self.issues, key=lambda i: i["updated_at"], reverse=True)[:1]}
            return {"results": self.recent}

        f.pages, f.get, f.plane_base = pages, get, lambda: "http://plane"
        self.full = f.plane_read()

    def ask(self, *rows):
        self.recent = list(rows)
        return f.plane_live(self.full["_live"])

    def test_a_close_is_a_line_at_once_and_the_bars_move(self):
        lines, over = self.ask(issue(2, "s_done", NOW - 10, done=NOW - 10))
        self.assertEqual([(l["kind"], l["ref"]) for l in lines], [("done", "DGO-2")])
        self.assertFalse(over)
        totals = f.recount(self.full["_live"], self.full["topics"])
        self.assertEqual((self.full["topics"][0]["done"], totals["completed"]), (1, 1))

    def test_started_cancelled_reopened_and_new(self):
        lines, _ = self.ask(issue(3, "s_go", NOW - 40), issue(4, "s_no", NOW - 30),
                            issue(9, "s_back", NOW - 20, made=NOW - 20))
        self.assertEqual([l["kind"] for l in lines], ["start", "cancel", "open"])
        lines, _ = self.ask(issue(4, "s_back", NOW - 5), issue(3, "s_go", NOW - 40))
        self.assertEqual([(l["kind"], l["text"]) for l in lines], [("open", "נפתח מחדש: item 4")])

    def test_a_change_without_a_state_move_is_no_line_and_the_same_change_is_read_once(self):
        lines, _ = self.ask(issue(5, "s_back", NOW - 15))
        self.assertEqual(lines, [])
        self.ask(issue(5, "s_done", NOW - 10, done=NOW - 10))
        lines, _ = self.ask(issue(5, "s_done", NOW - 10, done=NOW - 10))
        self.assertEqual(lines, [])

    def test_a_full_page_of_only_new_rows_asks_for_the_full_read(self):
        lines, over = self.ask(*[issue(n, "s_done", NOW - n, done=NOW - n) for n in range(1, 7)])
        self.assertFalse(over)                      # six rows: the page was not full, nothing lies beyond it
        self.assertEqual(len(lines), 6)
        lines, over = self.ask(*[issue(100 + n, "s_back", NOW, made=NOW) for n in range(f.LIVE_PAGE)])
        self.assertTrue(over)
        self.assertEqual(len(lines), f.LIVE_PAGE)

    def test_the_owner_tile_follows_a_label_and_a_close(self):
        self.assertEqual(self.full["totals"]["owner"], 1)
        self.ask(issue(1, "s_done", NOW - 10, done=NOW - 10, labels=["l_owner"]))
        self.assertEqual(f.recount(self.full["_live"], self.full["topics"])["owner"], 0)

    def test_one_close_seen_twice_is_one_line_and_the_day_keeps_more_than_16(self):
        lines, _ = self.ask(issue(2, "s_done", NOW - 10, done=NOW - 10))
        self.issues[1] = issue(2, "s_done", NOW - 10, done=NOW - 10)
        rebuilt = f.plane_read()["events"]
        day = f.day_lines(rebuilt, lines)
        self.assertEqual(sum(1 for e in day if e["ref"] == "DGO-2"), 1)
        many = [{"ts": int(NOW - i), "kind": "done", "text": "x%d" % i, "ref": "DGO-%d" % i} for i in range(40)]
        old = [{"ts": int(NOW - 2 * 86400), "kind": "done", "text": "old", "ref": "DGO-1"}]
        self.assertEqual(len(f.day_lines(many + old, [])), 40)

    def test_a_move_no_live_ask_saw_is_still_a_line_at_the_next_full_read(self):
        prev = self.full["_live"]
        self.issues[2] = issue(3, "s_go", NOW - 5)       # started between two reads, never seen by a live ask
        self.issues[3] = issue(4, "s_done", NOW - 5, done=NOW - 5)
        got = f.plane_read(prev)
        self.assertEqual([(l["kind"], l["ref"]) for l in got["lines"]], [("start", "DGO-3")])
        self.assertIn(("done", "DGO-4"), [(e["kind"], e["ref"]) for e in got["events"]])
        self.assertEqual(got["_live"]["high"], f.instant(iso(NOW - 5)))

    def test_a_close_renamed_before_the_full_read_is_one_line(self):
        lines, _ = self.ask(issue(2, "s_done", NOW - 10, done=NOW - 10))
        renamed = dict(issue(2, "s_done", NOW - 2, done=NOW - 2), name="item 2, renamed")
        self.issues[1] = renamed
        day = f.day_lines(f.plane_read(self.full["_live"])["events"], lines)
        self.assertEqual([e["text"] for e in day if e["ref"] == "DGO-2"], ["נסגר: item 2, renamed"])

    def test_a_close_after_a_reopen_since_the_full_read_is_its_own_line(self):
        self.issues[1] = issue(2, "s_done", NOW - 600, done=NOW - 600)
        full = f.plane_read(self.full["_live"])
        lines = [{"ts": int(NOW - 5), "kind": "done", "text": "נסגר: item 2", "ref": "DGO-2"}]
        self.assertEqual(sorted(e["ts"] for e in f.day_lines(full["events"], lines) if e["ref"] == "DGO-2"),
                         [int(NOW - 600), int(NOW - 5)])

    def test_a_state_made_since_the_full_read_asks_for_it_now(self):
        lines, over = self.ask(issue(6, "s_new", NOW - 3))
        self.assertEqual((lines, over), ([], True))

    def test_a_saved_file_with_a_broken_line_loses_that_line_only(self):
        with open(os.environ["DASHBOARD_STATE"], "w", encoding="utf-8") as fh:
            json.dump({"feed": [{"ts": None, "kind": "start", "text": "x", "ref": "DGO-1", "live": 1},
                                {"ts": int(NOW), "kind": "start", "text": "y", "ref": "DGO-2", "live": 1}]}, fh)
        self.assertEqual([e["ref"] for e in f.saved_live_lines(os.environ["DASHBOARD_STATE"])], ["DGO-2"])
        with open(os.environ["DASHBOARD_STATE"], "w", encoding="utf-8") as fh:
            fh.write("[1, 2")
        self.assertEqual(f.saved_live_lines(os.environ["DASHBOARD_STATE"]), [])

    def test_lines_only_the_live_ask_saw_survive_a_restart(self):
        lines, _ = self.ask(issue(3, "s_go", NOW - 40))
        with open(os.environ["DASHBOARD_STATE"], "w", encoding="utf-8") as fh:
            json.dump({"feed": lines + [{"ts": int(NOW), "kind": "bad", "text": "HP", "ref": ""}]}, fh)
        self.assertEqual([e["kind"] for e in f.saved_live_lines(os.environ["DASHBOARD_STATE"])], ["start"])


if __name__ == "__main__":
    unittest.main()
