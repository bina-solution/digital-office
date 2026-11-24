"""test_resolve — a notice that ENDS an episode closes it (DGO-2111), proven through the real app.

Before this, only GlitchTip rows were ever retired. A producer's «back» never closed its «down»: on vps1, 217 of
dgo-extend's 218 unread rows were outages long over, and the HP's board held 10,650 autoheal rows. Two ways to end
one, and what they never do:
  * `meta.state: "resolved"`: the notice's own row is read, also when it rewrites a «down» of the same source_id
    (meet's watch, autoheal's «works again»);
  * `resolves: [source_id, …]`: the rows of the SAME source that it names are read (dgo-extend's «link-up-…»);
  * never another producer's row, and never a row the notice does not name;
  * a `resolves` that is not a list of names is refused, never trimmed.

    python -m unittest -v test_resolve          (from this directory; stdlib + the image's own packages)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the folder's ONE environment (test_flow.py says why): importing test_push sets the database before app.py
import test_push  # noqa: E402,F401

import app  # noqa: E402


def row(source, source_id):
    with app._db() as c:
        r = c.execute("SELECT * FROM notifications WHERE source=? AND source_id IS ?", (source, source_id)).fetchone()
    return app._row(r) if r else None


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self._flow = app._flowpub
        app._flowpub = None                    # the event stream is test_flow's; nothing is published here
        self.c = app.app.test_client()

    def tearDown(self):
        app._flowpub = self._flow

    def post(self, **b):
        return self.c.post("/api/notifications", json=b)

    def test_a_resolved_notice_closes_its_own_down_row(self):
        self.post(source="meet", source_id="rec:7", title="⚠️ הפגישה לא מוקלטת", level="warning")
        self.assertFalse(row("meet", "rec:7")["is_read"])
        r = self.post(source="meet", source_id="rec:7", title="✅ הפגישה מוקלטת עכשיו", level="info",
                      meta={"state": "resolved"})
        self.assertEqual(r.status_code, 200)
        got = row("meet", "rec:7")
        self.assertTrue(got["is_read"], "the episode is over: the row is read")
        self.assertEqual(got["title"], "✅ הפגישה מוקלטת עכשיו")

    def test_a_resolved_notice_with_no_down_is_written_read(self):
        r = self.post(source="autoheal", source_id="x:unhealthy:1", title="x תקין שוב", meta={"state": "resolved"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(row("autoheal", "x:unhealthy:1")["is_read"])

    def test_resolves_closes_the_named_rows_of_its_own_source_only(self):
        self.post(source="dgo-extend", source_id="link-down-hp-100", title="הקישור ל-HP נפל", level="error")
        self.post(source="dgo-extend", source_id="link-down-hp-200", title="הקישור ל-HP נפל", level="error")
        self.post(source="sites", source_id="link-down-hp-100", title="another producer's row", level="error")
        r = self.post(source="dgo-extend", source_id="link-up-hp-100", title="הקישור ל-HP חזר",
                      resolves=["link-down-hp-100", "link-slow-hp-100"], meta={"state": "resolved"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(row("dgo-extend", "link-down-hp-100")["is_read"], "the episode it names is closed")
        self.assertTrue(row("dgo-extend", "link-up-hp-100")["is_read"], "the «back» itself is read")
        self.assertFalse(row("dgo-extend", "link-down-hp-200")["is_read"], "another episode stays open")
        self.assertFalse(row("sites", "link-down-hp-100")["is_read"], "never another producer's row")
        self.assertIsNone(row("dgo-extend", "link-slow-hp-100"), "a name with no row creates nothing")

    def test_a_notice_without_an_end_still_comes_back_unread(self):
        self.post(source="dgo-extend", source_id="link-down-mac-300", title="הקישור למק נפל", level="error")
        self.c.post(f"/api/notifications/{row('dgo-extend', 'link-down-mac-300')['id']}/read", json={})
        self.assertTrue(row("dgo-extend", "link-down-mac-300")["is_read"])
        self.post(source="dgo-extend", source_id="link-down-mac-300", title="הקישור למק נפל", level="error",
                  meta={"count": 2})
        self.assertFalse(row("dgo-extend", "link-down-mac-300")["is_read"], "a new occurrence re-surfaces, as before")

    def test_an_alarm_after_its_resolve_comes_back_unread(self):
        # meet's keys are fixed (`server:memory`): the next episode reuses the row the last one closed
        self.post(source="meet", source_id="server:memory", title="⚠️ זיכרון", level="warning")
        self.post(source="meet", source_id="server:memory", title="✅ זיכרון", meta={"state": "resolved"})
        self.assertTrue(row("meet", "server:memory")["is_read"])
        self.post(source="meet", source_id="server:memory", title="⚠️ זיכרון", level="warning")
        self.assertFalse(row("meet", "server:memory")["is_read"], "a new episode on the same key is news again")

    def test_a_log_row_is_a_record_written_read_and_stays_read(self):
        r = self.post(source="follow", source_id="follow:took:vps1:abc", title="המשרד התעדכן ל־dgo-stable abc",
                      meta={"office": "vps1", "state": "log"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(row("follow", "follow:took:vps1:abc")["is_read"])
        self.post(source="follow", source_id="follow:took:vps1:abc", title="המשרד התעדכן ל־dgo-stable abc",
                  meta={"office": "vps1", "state": "log", "count": 2})
        self.assertTrue(row("follow", "follow:took:vps1:abc")["is_read"], "a record never comes back as news")

    def test_a_warning_is_still_news(self):
        self.post(source="bina-ds", source_id="seder-door:9", title="סדר מנחה לא נסגר", level="warning")
        self.assertFalse(row("bina-ds", "seder-door:9")["is_read"])

    def test_fifty_names_are_accepted(self):
        r = self.post(source="dgo-extend", source_id="link-up-y-1", title="t", resolves=[f"n{i}" for i in range(50)])
        self.assertEqual(r.status_code, 201)

    def test_a_resolves_that_is_not_a_list_of_names_is_refused(self):
        for bad in ("link-down-a", [1], [""], ["  "], [None], ["x"] * 51, {"a": 1}):
            r = self.post(source="dgo-extend", source_id="link-up-z-1", title="t", resolves=bad)
            self.assertEqual(r.status_code, 400, f"refused: {bad!r}")
        self.assertIsNone(row("dgo-extend", "link-up-z-1"), "a refused notice writes nothing")


if __name__ == "__main__":
    unittest.main()
