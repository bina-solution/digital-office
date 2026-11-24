"""test_from_office — a linked office's notice, carried over the link, says where it comes from (DGO-2111, root 2).

The MacBook and the Dell run no board, and their notices went nowhere. They are to reach the herd's board on the HP
through the link's door. There:
  * the office is believed only from the door's own address: any container can write `x-dgo-office`;
  * its episodes stay its own: source_id and `resolves` are prefixed with the office, so the MacBook's «disk-full»
    never closes or rewrites the HP's;
  * its answers (meta.actions) are dropped: run here, they would act on the HP, not on the office that asked;
  * this office's own posters see no change at all.

    python -m unittest -v test_from_office          (from this directory; stdlib + the image's own packages)
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the folder's ONE environment (test_flow.py says why): importing test_push sets the database before app.py
import test_push  # noqa: E402,F401

import app  # noqa: E402

DOOR = "10.79.0.9"


def row(source, source_id):
    with app._db() as c:
        r = c.execute("SELECT * FROM notifications WHERE source=? AND source_id IS ?", (source, source_id)).fetchone()
    return app._row(r) if r else None


class FromOfficeTest(unittest.TestCase):
    def setUp(self):
        self._flow = app._flowpub
        app._flowpub = None
        app._DOOR.update(at=time.time(), addrs={DOOR})      # the door's address, as the DNS would answer it
        self.c = app.app.test_client()

    def tearDown(self):
        app._flowpub = self._flow
        app._DOOR.update(at=0.0, addrs=set())

    def post(self, addr, office=None, **b):
        headers = {"x-dgo-office": office} if office else {}
        return self.c.post("/api/notifications", json=b, headers=headers, environ_base={"REMOTE_ADDR": addr})

    def test_a_notice_through_the_door_is_the_offices_own(self):
        r = self.post(DOOR, "macbook", source="machine", source_id="disk-full", title="הדיסק מלא",
                      level="error", meta={"actions": [{"id": "x", "label": "נקה", "op": "machine.clean"}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        n = row("machine", "macbook:disk-full")
        self.assertIsNotNone(n, "the episode id is the office's own")
        self.assertEqual(n["title"], "macbook · הדיסק מלא")
        self.assertEqual((n.get("meta") or {}).get("office"), "macbook")
        self.assertNotIn("actions", n.get("meta") or {}, "an answer from there never runs here")

    def test_its_episode_never_meets_this_offices(self):
        self.post("172.18.0.5", source="machine", source_id="disk-low", title="here")
        self.post(DOOR, "macbook", source="machine", source_id="disk-low", title="there")
        self.post(DOOR, "macbook", source="machine", source_id="disk-ok", title="back",
                  resolves=["disk-low"], meta={"state": "resolved"})
        here, there = row("machine", "disk-low"), row("machine", "macbook:disk-low")
        self.assertEqual(here["title"], "here", "this office's row is untouched")
        self.assertFalse(here["is_read"], "…and the other office's return never closes it")
        self.assertTrue(there["is_read"], "the office's own return closes its own")

    def test_the_header_from_any_other_container_is_nothing(self):
        self.post("172.18.0.7", "macbook", source="spoof", source_id="s1", title="plain")
        n = row("spoof", "s1")
        self.assertEqual(n["title"], "plain", "not from the door: an ordinary local notice, as before")
        self.assertNotIn("office", n.get("meta") or {})

    def test_a_bad_office_name_from_the_door_is_refused(self):
        r = self.post(DOOR, "../etc", source="odd", source_id="o1", title="t")
        self.assertEqual(r.status_code, 403, "the door names no valid office: refused, never taken as local")
        self.assertIsNone(row("odd", "o1"))

    def test_what_would_act_here_is_dropped(self):
        self.post(DOOR, "macbook", source="m", source_id="l1", title="t", link="/#/m/drive",
                  meta={"to": ["akadmin"], "x": 1})
        n = row("m", "macbook:l1")
        self.assertEqual(n["link"], "", "a relative link would open THIS office's app")
        self.assertNotIn("to", n.get("meta") or {}, "meta.to names this office's people")
        self.assertEqual((n.get("meta") or {}).get("x"), 1, "the rest of meta stays")
        self.post(DOOR, "macbook", source="m", source_id="l2", title="t", link="https://x.example/a")
        self.assertEqual(row("m", "macbook:l2")["link"], "https://x.example/a", "an absolute link stays")

    def test_a_door_recreated_with_a_new_address_is_found_at_once(self):
        app._DOOR.update(at=time.time() - 10, addrs={"10.79.0.1"})   # the cache still holds the old address
        real = app.socket.getaddrinfo
        app.socket.getaddrinfo = lambda *a, **k: [(None, None, None, None, (DOOR, 0))]
        try:
            self.post(DOOR, "macbook", source="r", source_id="r1", title="t")
        finally:
            app.socket.getaddrinfo = real
        self.assertIsNotNone(row("r", "macbook:r1"), "a miss reads the door again (at most every 5 s)")


if __name__ == "__main__":
    unittest.main()
