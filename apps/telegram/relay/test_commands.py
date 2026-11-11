#!/usr/bin/env python3
"""The owner's commands in the group (commands.py, DGO-1329), without redis, Plane or Telegram:
    python3 apps/telegram/relay/test_commands.py
What is asked: only his own account's messages are commands, «מצב»/«קדימה» only when they are not a reply; «משימה»
opens ONE item even when its POST timed out after Plane stored it, answers once even when the stream replays it, and
moves the desk to ✍; «מצב» answers with the table and leaves the desk (👌) — and goes to the answerer when the table
could not be sent; «קדימה» posts the table and hands the message over with it, tried again when the door is busy;
«חסום» says the measured truth from its thread; an internal address is masked, never the reason a reply is lost; a
lost redis connection is raised, never taken as «run it anyway»."""
import os
import sys
import threading
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commands      # noqa: E402
import desk          # noqa: E402
from test_desk import FakeRedis, GROUP   # noqa: E402


class Redis(FakeRedis):
    def cmd(self, op, *a):
        if op == "SET":                                   # SET key value NX EX ttl
            if a[0] in self.h.setdefault("__keys__", {}):
                return None
            self.h["__keys__"][a[0]] = a[1]
            return "OK"
        return super().cmd(op, *a)


def ev(mid, text, out=True, reply_to=None, media=None):
    return {"type": "message.new", "at": "2026-11-05T12:00:00Z",
            "data": {"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": mid, "sender": "ED", "out": out,
                     "text": text, "reply_to": reply_to, "media": media}}


class Bot:
    def __init__(self, down=False):
        self.said, self.marks, self.down = [], [], down

    def token(self):
        return "t"

    def reply(self, chat, msg, text):
        if self.down:
            return None
        self.said.append((msg, commands.clean(text)))
        return 9000 + len(self.said)

    def mark(self, chat, msg, emoji):
        self.marks.append((msg, emoji))


class Plane(commands.Plane):
    """A Plane in memory; `store_then_fail` stores the item and then times out, as a slow gateway does."""

    def __init__(self, store_then_fail=False, down=False):
        super().__init__()
        self.items, self.posts, self.store_then_fail, self.down = {}, 0, store_then_fail, down
        self.pause = lambda s: None

    def project(self):
        return "proj-1"

    def call(self, path, body=None, timeout=20):
        if self.down:
            raise OSError("timed out")
        if body is None:
            ext = path.split("external_id=")[-1].replace("%3A", ":").replace("%2D", "-")
            if ext in self.items:
                return self.items[ext]
            raise urllib.error.HTTPError(path, 404, "not found", {}, None)
        self.posts += 1
        item = {"id": "uuid-%d" % self.posts, "sequence_id": 1400 + self.posts, "name": body["name"],
                "external_id": body["external_id"]}
        self.items[body["external_id"]] = item
        if self.store_then_fail:
            raise TimeoutError("the gateway timed out after Plane stored it")
        return item


class Ctx(commands.Context):
    def __init__(self, r, plane=None, bot=None, door_fails=0):
        self.delivered, self.door_fails, self.paused = [], door_fails, []
        super().__init__(redis_fn=lambda: r, deliver=self.door, bot=bot or Bot(), plane=plane or Plane(),
                         sessions_fn=lambda: [{"id": "s1", "title": "DGO-1389 · DKIM", "running": True},
                                              {"id": "s2", "title": "idle one"}, {"id": "s3", "blank": True}],
                         pause=self.paused.append)

    def door(self, text):
        if self.door_fails:
            self.door_fails -= 1
            raise ConnectionError("HTTP 409 a send in flight")
        self.delivered.append(text)


def with_record(r, e):
    desk.create(r, desk.new_record(e["data"], e["at"]))


def in_thread(fn):
    """Run commands.take and wait for the thread it starts (the table and the ban run in their own)."""
    done = threading.Event()
    orig = commands.run_table, commands.run_ban, commands.run_task

    def wrap(target):
        def run(*a):
            try:
                target(*a)
            finally:
                done.set()
        return run
    commands.run_table, commands.run_ban, commands.run_task = (wrap(t) for t in orig)
    try:
        got = fn()
        if got is not None and got.get("deliver", True) is False and got.get("note"):
            return got                                      # a replay: no thread was started
        assert done.wait(5), "the command's thread did not finish"
        return got
    finally:
        commands.run_table, commands.run_ban, commands.run_task = orig


SNAP = {"lines": ["🐑 העדר: 4 מתוך 5 מחוברים", "🗂 משימות: 63 בעבודה"], "tz_offset": 7200,
        "parts": {"security": [{"office": "vps1", "mode": "observe"}]}}


class Parse(unittest.TestCase):
    def p(self, text, **kw):
        return commands.parse(ev(1, text, **kw)["data"])

    def test_the_four_forms(self):
        self.assertEqual(self.p("משימה: לבדוק את הקישור של vps1"), ("task", "לבדוק את הקישור של vps1"))
        self.assertEqual(self.p("משימה חדשה - סרטון במצב דסקטופ"), ("task", "סרטון במצב דסקטופ"))
        self.assertEqual(self.p("מצב"), ("status", ""))
        self.assertEqual(self.p("מה המצב?"), ("status", ""))
        self.assertEqual(self.p("קדימה"), ("forward", ""))
        self.assertEqual(self.p("ויאללה קדימה"), ("forward", ""))
        self.assertEqual(self.p("קדימה אחרי הפגישה האחרונה bs101"), ("forward", "אחרי הפגישה האחרונה bs101"))
        self.assertEqual(self.p("חסום 203.0.113.9"), ("ban", "203.0.113.9"))
        self.assertEqual(self.p("חסום 2001:db8::7"), ("ban", "2001:db8::7"))
        self.assertEqual(self.p("חסום", reply_to=55), ("ban", ""))
        self.assertEqual(self.p("משימה: לתקן את זה", reply_to=55), ("task", "לתקן את זה"))   # a task stays one

    def test_what_is_not_a_command(self):
        self.assertIsNone(self.p("מצב", out=False))                  # not his account: the bot, or anyone else
        self.assertIsNone(self.p("מה המצב?", reply_to=55))           # about THAT message: the answerer's
        self.assertIsNone(self.p("קדימה", reply_to=55))              # «go ahead» to a proposal: the answerer's
        self.assertIsNone(self.p("קדימהה"))
        self.assertIsNone(self.p("תפתח משימה: משהו"))
        self.assertIsNone(self.p("מצב המערכת גרוע"))
        self.assertIsNone(self.p("חסום"))                             # no address and no notice it answers
        self.assertIsNone(self.p("חסום את זה"))
        self.assertIsNone(self.p("חסום 1329"))                        # a number is not an address
        self.assertIsNone(self.p("חסום cafe"))
        self.assertIsNone(self.p(""))


class Task(unittest.TestCase):
    def setUp(self):
        self.r = Redis()

    def test_one_item_answered_with_its_link_and_taken_on_the_desk(self):
        ctx = Ctx(self.r)
        e = ev(301, "משימה: לסדר את הקישור בכרטיס ה-QR\nשייפתח בלחיצה")
        with_record(self.r, e)
        got = in_thread(lambda: commands.take(self.r, e, "TG: … msg 301", ctx))
        self.assertFalse(got["deliver"])                             # its thread hands it over, with the note
        self.assertEqual(ctx.plane.posts, 1)
        msg, text = ctx.bot.said[0]
        self.assertEqual(msg, 301)
        self.assertTrue(text.startswith(commands.RLM + "📌 DGO-1401 · לסדר את הקישור בכרטיס ה-QR"))
        self.assertIn("https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/projects/proj-1/issues/uuid-1", text)
        rec = desk.load(self.r, GROUP, 301)
        self.assertEqual((rec["state"], rec["items"], rec["answers"]), ("working", ["DGO-1401"], [9001]))
        self.assertEqual(ctx.bot.marks, [(301, "✍")])
        self.assertEqual(len(ctx.delivered), 1)
        self.assertTrue(ctx.delivered[0].startswith("TG: … msg 301"))
        self.assertIn("ALREADY has DGO-1401", ctx.delivered[0])

    def test_a_post_that_timed_out_after_plane_stored_it_is_one_item(self):
        ctx = Ctx(self.r, Plane(store_then_fail=True))
        in_thread(lambda: commands.take(self.r, ev(302, "משימה: פעם אחת"), "line", ctx))
        self.assertEqual(ctx.plane.posts, 1)
        self.assertIn("📌 DGO-1401", ctx.bot.said[0][1])
        self.assertIn("ALREADY has DGO-1401", ctx.delivered[0])

    def test_a_replayed_message_makes_no_second_item_and_says_nothing_twice(self):
        ctx = Ctx(self.r)
        e = ev(303, "משימה: קיים")
        with_record(self.r, e)
        in_thread(lambda: commands.take(self.r, e, "line", ctx))
        again = in_thread(lambda: commands.take(self.r, e, "line", ctx))
        self.assertEqual((ctx.plane.posts, len(ctx.bot.said), len(ctx.delivered)), (1, 1, 1))
        self.assertFalse(again["deliver"])
        self.assertIn("already answered", again["note"])

    def test_plane_down_is_said_once_and_handed_over_with_the_truth(self):
        ctx = Ctx(self.r, Plane(down=True))
        in_thread(lambda: commands.take(self.r, ev(304, "משימה: משהו"), "line", ctx))
        self.assertIn("לא נפתח פריט", ctx.bot.said[0][1])
        note = ctx.delivered[0]
        self.assertIn("made no item", note)
        self.assertIn("did not answer whether this message already has one", note)   # never «there is none»
        self.assertIn("he was told Plane did not answer", note)

    def test_a_file_with_the_task_is_named_to_the_answerer(self):
        ctx = Ctx(self.r)
        in_thread(lambda: commands.take(self.r, ev(305, "משימה: עם צילום", media={"kind": "photo"}), "line", ctx))
        self.assertIn("tasks attach DGO-1401", ctx.delivered[0])


class Tables(unittest.TestCase):
    def setUp(self):
        self.r = Redis()
        self.saved = commands.http_json
        commands.http_json = lambda url, *a, **k: SNAP

    def tearDown(self):
        commands.http_json = self.saved

    def test_status_is_the_table_as_a_reply_and_leaves_the_desk(self):
        ctx = Ctx(self.r)
        other = ev(299, "בקשה אחרת")
        with_record(self.r, other)
        e = ev(305, "מצב")
        with_record(self.r, e)
        got = in_thread(lambda: commands.take(self.r, e, "TG: ED 12:00 UTC msg 305 מצב", ctx))
        self.assertFalse(got["deliver"])
        text = ctx.bot.said[0][1]
        self.assertRegex(text, "^" + commands.RLM + r"📸 תמונת מצב · \d\d:\d\d\n")   # now, at the owner's offset
        self.assertIn("🐑 העדר: 4 מתוך 5 מחוברים", text)
        self.assertIn("💬 הקבוצה: 1 בקשות פתוחות", text)               # the other request; not this «מצב» itself
        self.assertIn("🤖 סוכנים: 1 עובדים עכשיו — DGO-1389 · DKIM", text)
        self.assertEqual(ctx.delivered, [])
        self.assertEqual(desk.load(self.r, GROUP, 305)["state"], "dropped")
        self.assertEqual(ctx.bot.marks, [(305, "👌")])

    def test_status_that_could_not_be_sent_goes_to_the_answerer(self):
        ctx = Ctx(self.r, bot=Bot(down=True))
        e = ev(306, "מצב")
        with_record(self.r, e)
        in_thread(lambda: commands.take(self.r, e, "TG: … msg 306 מצב", ctx))
        self.assertEqual(len(ctx.delivered), 1)
        self.assertIn("did NOT go out", ctx.delivered[0])
        self.assertEqual(desk.load(self.r, GROUP, 306)["state"], "received")

    def test_forward_posts_the_table_then_hands_it_over_even_when_the_door_is_busy(self):
        ctx = Ctx(self.r, door_fails=2)
        e = ev(307, "קדימה אחרי הפגישה האחרונה bs101")
        with_record(self.r, e)
        got = in_thread(lambda: commands.take(self.r, e, "TG: ED 12:00 UTC msg 307", ctx))
        self.assertFalse(got["deliver"])
        self.assertEqual(len(ctx.delivered), 1)
        self.assertEqual(ctx.paused, [10, 20])                       # tried again, not dropped
        handed = ctx.delivered[0]
        self.assertTrue(handed.startswith("TG: ED 12:00 UTC msg 307"))
        self.assertIn("«אחרי הפגישה האחרונה bs101»", handed)
        self.assertIn("ALREADY posted", handed)

    def test_a_replayed_table_command_is_not_run_twice(self):
        ctx = Ctx(self.r)
        e = ev(308, "מצב")
        with_record(self.r, e)
        in_thread(lambda: commands.take(self.r, e, "line", ctx))
        again = commands.take(self.r, e, "line", ctx)
        self.assertEqual(len(ctx.bot.said), 1)
        self.assertFalse(again["deliver"])


class Ban(unittest.TestCase):
    def setUp(self):
        self.r = Redis()
        self.saved = commands.http_json

    def tearDown(self):
        commands.http_json = self.saved

    def test_ban_says_the_observe_truth_and_carries_it(self):
        ctx = Ctx(self.r)
        e = ev(309, "חסום 203.0.113.9")
        with_record(self.r, e)
        commands.http_json = lambda url, *a, **k: SNAP
        in_thread(lambda: commands.take(self.r, e, "line", ctx))
        text = ctx.bot.said[0][1]
        self.assertIn(commands.ltr("203.0.113.9"), text)
        self.assertIn("במצב צפייה", text)
        rec = desk.load(self.r, GROUP, 309)
        self.assertEqual((rec["state"], rec["items"]), ("working", ["DGO-1329"]))
        self.assertEqual(len(ctx.delivered), 1)

    def test_ban_by_reply_reads_the_address_and_the_office_the_notice_offered(self):
        ctx = Ctx(self.r)
        e = ev(310, "חסום", reply_to=4321)
        with_record(self.r, e)
        posted = {"relay": {"posted": {"4321": {"office": "dell", "actions": [
            {"id": "block", "label": "חסום", "op": "security.ban", "args": {"ip": "198.51.100.7"}}]}}}}
        commands.http_json = lambda url, *a, **k: posted if url.endswith("/data/group.json") else {
            "parts": {"security": [{"office": "dell", "mode": "enforce"}, {"office": "vps1", "mode": "observe"}]}}
        in_thread(lambda: commands.take(self.r, e, "line", ctx))
        text = ctx.bot.said[0][1]
        self.assertIn(commands.ltr("198.51.100.7"), text)
        self.assertIn(commands.ltr("dell") + " אוכף", text)


class Safety(unittest.TestCase):
    def test_an_internal_address_is_masked_and_the_rest_still_goes(self):
        sent = []
        saved = commands.http_json
        commands.http_json = lambda url, body=None, **k: sent.append(body) or {"result": {"message_id": 1}}
        try:
            mid = commands.Bot(lambda: "t").reply(GROUP, 1, "📌 DGO-1 · see http://dashboard:80/data/state.json")
        finally:
            commands.http_json = saved
        self.assertEqual(mid, 1)
        self.assertNotIn("dashboard:80", sent[0]["text"])
        self.assertIn("DGO-1", sent[0]["text"])

    def test_a_lost_connection_is_raised_never_taken_as_run_anyway(self):
        class Gone(Redis):
            def cmd(self, op, *a):
                raise ConnectionError("redis closed the connection")
        with self.assertRaises(ConnectionError):
            commands.take(Gone(), ev(311, "מצב"), "line", Ctx(Redis()))

    def test_a_full_redis_costs_the_record_not_the_answer(self):
        class Full(Redis):
            def cmd(self, op, *a):
                if op in ("HSET", "HSETNX", "XADD"):
                    raise ConnectionError("redis refused: OOM command not allowed")
                return super().cmd(op, *a)
        r = Full()
        ctx = Ctx(r)
        in_thread(lambda: commands.take(r, ev(312, "משימה: גם כשהזיכרון מלא"), "line", ctx))
        self.assertIn("📌 DGO-1401", ctx.bot.said[0][1])
        self.assertIn("ALREADY has DGO-1401", ctx.delivered[0])

    def test_every_line_of_the_table_is_right_to_left(self):
        saved = commands.http_json
        commands.http_json = lambda *a, **k: {"lines": ["🐑 העדר: 3 מתוך 4 מחוברים\n   • vps1: לא עונה"]}
        try:
            text = commands.table(Redis(), Ctx(Redis()), 1793880000.0, 1)
        finally:
            commands.http_json = saved
        self.assertTrue(all(line.startswith(commands.RLM) for line in text.split("\n")), text)


if __name__ == "__main__":
    unittest.main()
