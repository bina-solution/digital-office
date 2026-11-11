"""test_groupfeed.py — the owner's group, live in the control centre (groupfeed.py, DGO-1329), against fakes.

    python3 apps/dashboard/test_groupfeed.py

What is asked: the telegram app is read through the door of the office herd.yaml runs it on (this office's own when
none is routed); the main group is the watched group of the right name with the newest message, never another chat;
each message carries its t.me link and whether the bot or the owner wrote it, oldest first, at most GROUP_KEEP; a read
that fails keeps the last good messages and says why.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ["DASHBOARD_GROUP_LIVE"] = os.path.join(TMP, "group-live.json")
import groupfeed  # noqa: E402

HERD = os.path.join(TMP, "herd.yaml")
with open(HERD, "w", encoding="utf-8") as fh:
    fh.write("apps:\n  telegram: hp-laptop\n")
MAIN, OLD, OTHER = -1004303648995, -5551441246, -1009999999999


def rows(*ids, chat=MAIN):
    return [{"message_id": i, "at": "2026-11-05T12:%02d:00+00:00" % (i % 60), "sender": "Bina Agent" if i % 2 else "ED",
             "out": not i % 2, "text": "הודעה %d" % i} for i in ids]


class Fake:
    def __init__(self):
        self.asked, self.fail = [], False

    def get(self, url, timeout=8):
        self.asked.append(url)
        if self.fail:
            return {"_error": "HTTP 502: "}
        if url.endswith("/api/chats"):
            return {"chats": [{"id": OLD, "kind": "group", "watched": True, "title": "Bina Solutions Main"},
                              {"id": MAIN, "kind": "group", "watched": True, "title": "Bina Solutions Main"},
                              {"id": OTHER, "kind": "group", "watched": True, "title": "A client's group"},
                              {"id": -1001, "kind": "group", "watched": False, "title": "Bina Solutions Main"}]}
        if "limit=1&" in url or url.endswith("limit=1"):
            newest = "2026-11-05T12:00:00+00:00" if f"chat_id={MAIN}" in url else "2026-11-03T13:00:00+00:00"
            return {"messages": [{"message_id": 1, "at": newest}]}
        return {"messages": rows(*range(200, 240)) if f"chat_id={MAIN}" in url else rows(1, chat=OTHER)}


class GroupFeed(unittest.TestCase):
    def test_the_door_of_the_office_that_runs_telegram_else_its_own(self):
        self.assertEqual(groupfeed.telegram_base(HERD, lambda o, a: f"http://{a}.{o}:9003"),
                         "http://telegram.hp-laptop:9003")
        self.assertEqual(groupfeed.telegram_base(HERD, lambda o, a: ""), "http://telegram:8984")   # it runs here

    def setUp(self):
        if os.path.exists(os.environ["DASHBOARD_GROUP_LIVE"]):
            os.remove(os.environ["DASHBOARD_GROUP_LIVE"])

    def test_only_where_it_is_shown_to_him(self):
        self.assertIsNone(groupfeed.loop(Fake().get, lambda o, a: "", HERD, once=True, office="vps1"))
        self.assertFalse(os.path.exists(os.environ["DASHBOARD_GROUP_LIVE"]))     # the owner's group never copied there
        self.assertTrue(groupfeed.enabled("macbook", ["macbook"]))
        self.assertFalse(groupfeed.enabled("", ["macbook"]))

    def test_a_restart_while_telegram_is_away_keeps_the_last_messages(self):
        groupfeed.loop(Fake().get, lambda o, a: "http://telegram.hp-laptop:9003", HERD, once=True, office="macbook")
        down = Fake()
        down.fail = True
        doc = groupfeed.loop(down.get, lambda o, a: "http://telegram.hp-laptop:9003", HERD, once=True, office="macbook")
        self.assertEqual(len(doc["messages"]), groupfeed.GROUP_KEEP)
        self.assertIn("HTTP 502", doc["error"])

    def test_a_failed_read_of_the_main_group_never_picks_the_old_one(self):
        f = Fake()
        real = f.get

        def get(url, timeout=8):
            if f"chat_id={MAIN}" in url and "limit=1" in url:
                return {"_error": "HTTP 504: "}
            return real(url, timeout)
        doc = groupfeed.loop(get, lambda o, a: "http://telegram.hp-laptop:9003", HERD, once=True, office="macbook")
        self.assertIsNone(doc["chat_id"])
        self.assertIn("HTTP 504", doc["error"])

    def test_the_main_group_its_newest_messages_oldest_first_with_their_links(self):
        f = Fake()
        doc = groupfeed.loop(f.get, lambda o, a: "http://telegram.hp-laptop:9003", HERD, once=True, office="macbook")
        self.assertEqual((doc["chat_id"], doc["error"]), (MAIN, ""))
        self.assertEqual(doc["link"], "https://t.me/c/4303648995")
        ids = [m["id"] for m in doc["messages"]]
        self.assertEqual(len(ids), groupfeed.GROUP_KEEP)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[-1], 239)
        last = doc["messages"][-1]
        self.assertEqual((last["bot"], last["out"], last["link"]), (True, False, "https://t.me/c/4303648995/239"))
        self.assertTrue(doc["messages"][-2]["out"])
        with open(os.environ["DASHBOARD_GROUP_LIVE"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["chat_id"], MAIN)
        self.assertFalse(any(f"chat_id={OTHER}" in u for u in f.asked))           # never another chat

    def test_a_read_that_fails_keeps_the_last_messages_and_says_why(self):
        f = Fake()
        calls = {"n": 0}

        def sleep(_):
            calls["n"] += 1
            f.fail = True
            if calls["n"] > 1:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            groupfeed.loop(f.get, lambda o, a: "http://telegram.hp-laptop:9003", HERD, sleep=sleep, office="macbook")
        with open(os.environ["DASHBOARD_GROUP_LIVE"], encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(len(doc["messages"]), groupfeed.GROUP_KEEP)
        self.assertIn("HTTP 502", doc["error"])

    def test_an_ordinary_group_has_no_t_me_link(self):
        self.assertEqual(groupfeed.tme(OLD, 5), "")
        self.assertEqual(groupfeed.tme(MAIN, 5), "https://t.me/c/4303648995/5")


if __name__ == "__main__":
    unittest.main()
