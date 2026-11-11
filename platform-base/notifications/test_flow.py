"""test_flow — the office's notices on its event stream, proven through the real app without redis.

The event is published through the office's ONE publisher, platform-base/redis/flowpub.py (DGO-1402). A fake
publisher stands where flowpub stands and records what app.py's `_flow` hands it, so a pass means the exact
event the stream would carry: which notices are events (new, a new occurrence once the repeat window has passed)
and which are not (a refresh), what an event carries — the answers the owner's group relay offers (DGO-1329),
its audience, its level and a scrubbed body — and that a GlitchTip notice is named, never quoted.

    python -m unittest -v test_flow          (from this directory; stdlib + the image's own packages)
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ONE environment for the folder's suites: app.py fixes its database at import and push.py reads it per call,
# so two suites that each set their own would split them (the second reader: 15 of test_push red when this
# module loaded first). test_push's is the environment; importing it sets it — its tests stay in its module.
import test_push  # noqa: E402,F401

import app  # noqa: E402


class FakeFlowpub:
    """What `_flow` calls: emit(app, type, title, data, link), and stats() for /healthz."""
    def __init__(self):
        self.events = []

    def emit(self, app_id, type_, title, data=None, link=""):
        self.events.append({"app": app_id, "type": type_, "title": title, "data": json.loads(json.dumps(data)),
                            "link": link})
        return True

    def stats(self):
        return {"sent": len(self.events), "failed": 0}


BAN = [{"id": "block", "label": "חסום", "op": "security.ban", "args": {"ip": "203.0.113.9"}}]


class FlowTest(unittest.TestCase):
    def setUp(self):
        self._real = app._flowpub
        self.fake = app._flowpub = FakeFlowpub()
        app._flow_told.clear()
        self.c = app.app.test_client()

    def tearDown(self):
        app._flowpub = self._real

    def post(self, **b):
        return self.c.post("/api/notifications", json=b)

    def test_a_new_notice_is_one_event_with_its_answers(self):
        r = self.post(source="security", source_id="addr:203.0.113.9", title="כתובת חדשה נכנסה לכניסה",
                      body="203.0.113.9 · vps1", level="warning", link="/a/security/", meta={"actions": BAN, "to": "x"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.fake.events), 1)
        e = self.fake.events[0]
        self.assertEqual((e["app"], e["type"], e["title"], e["link"]),
                         ("notifications", "notice.warning", "כתובת חדשה נכנסה לכניסה", "/a/security/"))
        d = e["data"]
        self.assertEqual(d["id"], r.get_json()["id"])
        self.assertEqual((d["source"], d["source_id"], d["level"], d["new"]),
                         ("security", "addr:203.0.113.9", "warning", True))
        self.assertEqual(d["actions"], BAN)           # the relay's «חסום» travels whole
        self.assertEqual(d["to"], ["x"])              # the audience travels, as push reads it
        self.assertEqual(d["body"], "203.0.113.9 · vps1")
        self.assertNotIn("count", d)                  # the poster's other meta stays on the board

    def test_the_title_and_body_are_one_line_and_scrubbed(self):
        self.post(source="t", source_id="nl", title="שורה\nשנייה  \t ושלישית",
                  body="see https://x.example/a?token=abc and key " + "A" * 40)
        e = self.fake.events[0]
        self.assertEqual(e["title"], "שורה שנייה ושלישית")
        self.assertEqual(e["data"]["body"], "see https://x.example/a?… and key …")

    def test_glitchtip_is_named_never_quoted(self):
        self.post(source="glitchtip-issue", source_id="77", title="HTTPError https://x/y?dsn=secret",
                  body="Traceback … dsn=secret")
        e = self.fake.events[0]
        self.assertEqual(e["title"], "תקלה במעקב השגיאות (GlitchTip)")
        self.assertNotIn("body", e["data"])

    def test_a_new_occurrence_is_an_event_once_the_repeat_window_passed(self):
        app.create_notification("autoheal", "restarted", source_id="c1")
        app.create_notification("autoheal", "restarted", source_id="c1")           # within 15 minutes: not told
        self.assertEqual([e["data"]["new"] for e in self.fake.events], [True])
        nid = self.fake.events[0]["data"]["id"]
        app._flow_told[nid] -= app._FLOW_REPEAT_S + 1                               # the window has passed
        app.create_notification("autoheal", "restarted", source_id="c1")
        self.assertEqual([e["data"]["new"] for e in self.fake.events], [True, False])

    def test_a_refresh_is_not_an_event(self):
        meta = {"count": 1, "lastSeen": "2026-11-04T00:00:00+00:00"}
        self.post(source="glitchtip", source_id="77", title="TypeError", meta=meta)
        self.post(source="glitchtip", source_id="77", title="TypeError", meta=meta)             # the poller, again
        self.assertEqual(len(self.fake.events), 1)

    def test_bad_answers_are_refused_never_trimmed(self):
        for meta in ({"actions": "חסום"}, {"actions": [{"label": "חסום", "op": "security.ban"}]},
                     {"actions": [{"id": "b", "label": "חסום", "op": "ban"}]},
                     {"actions": [{"id": "b", "label": "חסום", "op": "security.ban", "args": [1]}]},
                     {"actions": [{"id": "b", "label": "חסום", "op": "security.ban", "args": {"x": "a" * 600}}]},
                     {"actions": [{"id": "b" * 65, "label": "חסום", "op": "security.ban"}]},
                     {"actions": [{"id": "b", "label": "חסום", "op": "Security.ban x"}]},
                     {"actions": BAN * 5}):
            r = self.post(source="t", source_id=json.dumps(meta), title="t", meta=meta)
            self.assertEqual(r.status_code, 400, meta)
            self.assertIn("meta.actions", r.get_json()["error"])
        self.assertEqual(self.post(source="t", title="t", meta=["x"]).status_code, 400)
        self.assertEqual(self.fake.events, [])
        self.assertEqual(self.post(source="t", source_id="empty", title="t", meta="").status_code, 201)  # as before

    def test_no_publisher_mounted_no_event_and_said(self):
        app._flowpub = None
        r = self.post(source="t", source_id="none", title="t")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.fake.events, [])
        self.assertFalse(self.c.get("/healthz").get_json()["flow"]["on"])

    def test_the_health_says_what_the_publisher_did(self):
        self.post(source="t", source_id="h", title="t")
        self.assertEqual(self.c.get("/healthz").get_json()["flow"], {"on": True, "sent": 1, "failed": 0})


if __name__ == "__main__":
    unittest.main()
