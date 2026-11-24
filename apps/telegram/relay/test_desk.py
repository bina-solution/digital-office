#!/usr/bin/env python3
"""The group desk's rules (desk.py) and the relay's line (relay_group.py), without redis or Telegram:
    python3 apps/telegram/relay/test_desk.py
Each case is a failure read in the group's thread of 2026-11-03/04 (DGO-1352)."""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desk          # noqa: E402
import relay_group   # noqa: E402

GROUP = -1001234567890


class FakeRedis:
    """The few commands the desk speaks, over dicts — enough to prove what is stored and read back."""

    def __init__(self, refuse_writes=False, lose_socket=False):
        self.h, self.stream, self.ttl, self.refuse, self.lose = {}, [], {}, refuse_writes, lose_socket
        self.sock = None

    def connect(self):
        self.sock = object()

    def close(self):
        self.sock = None

    def cmd(self, op, *a):
        h = self.h
        if self.lose:
            raise ConnectionError("redis closed the connection")
        if self.refuse and op in ("HSET", "HSETNX", "XADD", "HDEL"):
            raise ConnectionError("redis refused: OOM command not allowed when used memory > 'maxmemory'.")
        if op == "EXPIRE":
            self.ttl[a[0]] = int(a[1])
            return 1
        if op == "HSETNX":
            if str(a[1]) in h.get(a[0], {}):
                return 0
            h.setdefault(a[0], {})[str(a[1])] = a[2]
            return 1
        if op == "HSET":
            h.setdefault(a[0], {})[str(a[1])] = a[2]
            return 1
        if op == "HGET":
            return h.get(a[0], {}).get(str(a[1]))
        if op == "HGETALL":
            out = []
            for k, v in h.get(a[0], {}).items():
                out += [k, v]
            return out
        if op == "HLEN":
            return len(h.get(a[0], {}))
        if op == "HKEYS":
            return list(h.get(a[0], {}))
        if op == "HDEL":
            return 1 if h.get(a[0], {}).pop(str(a[1]), None) is not None else 0
        if op == "XADD":
            self.stream.append(a)
            return "1-0"
        raise AssertionError("unexpected redis command " + op)


class FakePublisher:
    """flowpub's emit, recorded (DGO-1402: the desk's events go through the office's one publisher)."""

    def __init__(self):
        self.events = []

    def emit(self, app, type_, title, data=None, link=""):
        self.events.append((app, type_, title, data or {}))
        return True


# no test here reaches a real redis: every event the desk publishes is recorded instead
desk._flowpub = FakePublisher()


def owner_msg(mid, text, reply_to=None, media=None):
    return {"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": mid, "sender": "ED",
            "text": text, "reply_to": reply_to, "media": media}


T0 = "2026-11-04T11:26:00Z"


class Ledger(unittest.TestCase):
    def test_a_message_is_received_then_taken(self):
        rec = desk.new_record(owner_msg(160, "זה לא עובד לא פותח לי שום דפדפן", reply_to=159), T0)
        self.assertEqual(rec["state"], "received")
        self.assertEqual(rec["reply_to"], 159)
        desk.take(rec, ["dgo-1336"])
        self.assertEqual((rec["state"], rec["items"]), ("working", ["DGO-1336"]))
        self.assertEqual(desk.MARKS[rec["state"]], "✍")

    def test_done_needs_proof_he_can_see(self):
        rec = desk.take(desk.new_record(owner_msg(122, "מה קורה עם האפלקציה"), T0), ["DGO-1338"])
        for not_proof in ("", "נכנס לקוד", "pushed c6ed3b05, live in the next build"):
            with self.assertRaises(ValueError):
                desk.done(rec, not_proof)
        desk.done(rec, "https://console.staging.digital-office.co.il/ — the phone shot of the app")
        self.assertEqual(desk.MARKS[rec["state"]], "👌")
        rec2 = desk.take(desk.new_record(owner_msg(123, "…"), T0), ["DGO-1338"])
        desk.done(rec2, "ci-artifacts/dgo1338-phone.png")
        self.assertEqual(rec2["state"], "done")

    def test_a_question_is_dropped_not_swept_forever(self):
        rec = desk.new_record(owner_msg(187, "מי אנחנו ?"), T0)
        with self.assertRaises(ValueError):
            desk.drop(rec, "")
        desk.drop(rec, "a question, answered in msg 188", at=T0)
        self.assertEqual((rec["state"], desk.MARKS[rec["state"]]), ("dropped", "👌"))
        self.assertEqual(desk.open_requests([rec], desk.parse_at(T0) + 86400), [])
        taken = desk.take(desk.new_record(owner_msg(191, "…"), T0), ["DGO-1351"])
        with self.assertRaises(ValueError):
            desk.drop(taken, "a request with an item ends in done")

    def test_done_before_take_is_refused(self):
        rec = desk.new_record(owner_msg(10, "…"), T0)
        with self.assertRaises(ValueError):
            desk.done(rec, "https://example.org/proof")

    def test_a_promise_comes_due(self):
        rec = desk.new_record(owner_msg(15, "תטפל בזה גם תעדכן כשהכל מושלם פה"), T0)
        desk.promise(rec, "צילום הוכחה מהמסך האמיתי יגיע כאן", hours=2, at=T0)
        t = desk.parse_at(T0)
        self.assertEqual(desk.overdue(rec, t + 3600), [])
        self.assertEqual(len(desk.overdue(rec, t + 3 * 3600)), 1)

    def test_the_sweep_puts_unanswered_first_and_skips_closed(self):
        t = desk.parse_at(T0) + 4 * 3600
        answered = desk.answered(desk.take(desk.new_record(owner_msg(138, "מחקר אבטחה"), T0), ["DGO-1344"], at=T0), 140)
        silent = desk.new_record(owner_msg(141, "מה קרה לכל התפעול של הקבוצה"), "2026-11-04T11:40:00Z")
        closed = desk.move(desk.new_record(owner_msg(128, "hello@"), T0), "closed", "test")
        fresh = desk.new_record(owner_msg(150, "ויאללה קדימה"), "2026-11-04T15:20:00Z")
        got = desk.open_requests([answered, silent, closed, fresh], t, stale_s=1800)
        self.assertEqual([r["message_id"] for r in got], [141, 138])      # fresh is not stale; closed is closed
        text = desk.sweep_text(got, t)
        self.assertIn("a reply is not progress", text)
        self.assertIn("at most two workers", text)          # the HP serves everyone: capacity before speed
        self.assertIn("NOT ANSWERED", text.splitlines()[1])

    def test_a_new_promise_supersedes_the_open_one(self):
        rec = desk.take(desk.new_record(owner_msg(748, "…"), T0), ["DGO-1765"], at=T0)
        desk.promise(rec, "measure Google and DuckDuckGo again with a screenshot, here", hours=3, at=T0)
        desk.promise(rec, "DDG measured; Google next", hours=24, at="2026-11-04T13:00:00Z")
        t = desk.parse_at(T0) + 5 * 3600
        self.assertEqual(desk.overdue(rec, t), [])                       # the 3-hour one no longer sweeps
        self.assertEqual(desk.open_requests([rec], t), [])               # the 24-hour one carries it
        self.assertFalse(rec["promises"][0]["kept"])                     # superseded, not claimed kept
        self.assertTrue(rec["promises"][0]["superseded"])

    def test_a_kept_promise_is_not_swept(self):
        rec = desk.take(desk.new_record(owner_msg(15, "…"), T0), ["DGO-1321"])
        desk.promise(rec, "proof shot", hours=1, at=T0)
        desk.done(rec, "ci-artifacts/dgo1321-phone.png, posted as a reply to his message")
        self.assertEqual(desk.open_requests([rec], desk.parse_at(T0) + 86400), [])


class Carried(unittest.TestCase):
    def test_a_promise_in_force_holds_a_request_out_of_the_sweep_until_it_is_due(self):
        rec = desk.take(desk.new_record(owner_msg(176, "תברר לעומק…"), T0), ["DGO-1349"], at=T0)
        desk.promise(rec, "carried by the herd session (DGO-1353): the tiles through vps1", hours=24, at=T0)
        t = desk.parse_at(T0)
        self.assertEqual(desk.open_requests([rec], t + 3 * 3600), [])          # someone is on it
        self.assertEqual(len(desk.open_requests([rec], t + 25 * 3600)), 1)     # due: back in front of the answerer


class Storage(unittest.TestCase):
    def test_stored_records_read_back_and_publish_an_event(self):
        # the event goes through the office's ONE publisher (flowpub, DGO-1402), not this ledger's redis client
        pub = desk._flowpub = FakePublisher()
        r = FakeRedis()
        self.assertTrue(desk.create(r, desk.new_record(owner_msg(202, "אנרואיד צריך לעבוד בדיוק כמו מק"), T0)))
        self.assertEqual(desk.load(r, GROUP, 202)["text"], "אנרואיד צריך לעבוד בדיוק כמו מק")
        self.assertEqual(len(desk.all_records(r)), 1)
        self.assertEqual(pub.events[0][:2], ("telegram", "desk.request"))
        self.assertEqual(pub.events[0][3]["message_id"], 202)
        self.assertEqual(r.stream, [])                       # no copy of the contract left in the desk

    def test_every_key_has_a_ttl_so_the_redis_backup_passes(self):
        r = FakeRedis()
        desk.create(r, desk.new_record(owner_msg(202, "…"), T0))
        desk.add_answer(r, GROUP, 202, 206)
        desk.remember(r, owner_msg(202, "…"), T0)
        for key in r.h:
            self.assertGreater(r.ttl.get(key, 0), 0, key)
        # the stream's TTL is the one publisher's now (renewed in its own MULTI — platform-base/redis/test_flowpub.py)

    def test_a_replay_never_resets_a_record_that_moved_on(self):
        r = FakeRedis()
        desk.create(r, desk.new_record(owner_msg(160, "…"), T0))
        rec = desk.take(desk.load(r, GROUP, 160), ["DGO-1336"])
        desk.store(r, rec)
        self.assertFalse(desk.create(r, desk.new_record(owner_msg(160, "…"), T0)))
        self.assertEqual(desk.load(r, GROUP, 160)["state"], "working")

    def test_the_answer_and_the_answerers_edit_do_not_erase_each_other(self):
        r = FakeRedis()
        desk.create(r, desk.new_record(owner_msg(15, "…"), T0))
        mine = desk.load(r, GROUP, 15)                    # the answerer reads the record…
        desk.add_answer(r, GROUP, 15, 18)                 # …the relay records the bot's reply meanwhile…
        desk.store(r, desk.promise(mine, "the proof shot", 2, at=T0))   # …and the answerer writes back
        back = desk.load(r, GROUP, 15)
        self.assertEqual(back["answers"], [18])
        self.assertEqual(len(back["promises"]), 1)

    def test_a_saved_file_puts_its_drive_path_on_the_record(self):
        # DGO-1805: the owner's 97 MB video (#825) is saved to the drive; the request it is carries the path, so the
        # answerer opens the file from the record. The state does not move, and no second desk event is published.
        pub = desk._flowpub = FakePublisher()
        r = FakeRedis()
        video = {"kind": "video", "label": "וידאו", "size": 97153903, "mime": "video/mp4", "name": ""}
        desk.create(r, desk.new_record(owner_msg(825, "", media=video), T0))
        sent = len(pub.events)
        path = "/טלגרם/Bina Solutions Main/825-video.mp4"
        ev = {"type": "media.saved", "at": T0, "data": {"chat_id": GROUP, "chat": "Bina Solutions Main",
                                                         "message_id": 825, "path": path}}
        mine = desk.load(r, GROUP, 825)                      # the answerer reads the record…
        self.assertTrue(relay_group.note_saved_file(r, ev))  # …the relay hears the file was saved meanwhile…
        desk.store(r, desk.take(mine, ["DGO-1805"]))         # …and the answerer writes back: neither loses
        back = desk.load(r, GROUP, 825)
        self.assertEqual(back["media"]["path"], path)
        self.assertEqual(back["media"]["size"], 97153903)
        self.assertEqual((back["state"], back["items"]), ("working", ["DGO-1805"]))
        self.assertEqual(len(pub.events), sent + 1)          # the answerer's take only — the relay published none
        self.assertEqual(r.ttl.get(desk.FILES, 0) > 0, True)  # renewed like every desk key (the backup's rule)
        # …and every listing shows it, not only load(): `desk list --json` and the sweep read all_records
        listed = [x for x in desk.all_records(r) if x["message_id"] == 825]
        self.assertEqual(listed[0]["media"]["path"], path)
        # a message with no request (the bot's own, or one before the desk) is left alone
        self.assertFalse(relay_group.note_saved_file(r, {**ev, "data": {**ev["data"], "message_id": 826}}))
        self.assertIsNone(desk.load(r, GROUP, 826))

    def test_an_edited_request_shows_the_words_he_means_now(self):
        # DGO-1995: msg 1129 arrived as «…ותצרף לאזור חיפה» and was edited to «…אולי כגליל מערבי»; the desk kept the
        # first, and a worker built what he had replaced. The record shows his words as they are now, keeps the
        # first beside them, and the answerer's write-back loses neither.
        r = FakeRedis()
        first = "בחלוקת האזורים: אזור נהריה ועכו תפצל מאזור צפון וגליל ותצרף לאזור חיפה"
        now = "בחלוקת האזורים: אזור נהריה ועכו תפצל מאזור צפון וגליל אולי כגליל מערבי"
        desk.create(r, desk.new_record(owner_msg(1129, first), T0))
        desk.remember(r, owner_msg(1129, first), T0)
        mine = desk.load(r, GROUP, 1129)                       # the answerer reads the record…
        ev = {"type": "message.edited", "at": "2026-11-15T21:40:00Z", "data": owner_msg(1129, now)}
        told = relay_group.note_edit(r, ev)                    # …the relay hears the edit meanwhile…
        self.assertEqual((told["text"], told["text_at_receipt"], told["was"]), (now, first, first))
        desk.store(r, desk.take(mine, ["DGO-1897"]))           # …and the answerer writes back: neither loses
        back = desk.load(r, GROUP, 1129)
        self.assertEqual((back["text"], back["text_at_receipt"], back["edited"]), (now, first, "2026-11-15T21:40:00Z"))
        self.assertEqual((back["state"], back["items"]), ("working", ["DGO-1897"]))
        self.assertEqual([x["text"] for x in desk.all_records(r) if x["message_id"] == 1129], [now])
        self.assertEqual(desk.recall(r, GROUP, 1129)["text"], now)       # a quote of it is his words now…
        self.assertEqual(desk.recall(r, GROUP, 1129)["at"], T0)          # …at the time he sent it
        self.assertGreater(r.ttl.get(desk.EDITS, 0), 0)                  # renewed like every desk key
        # the record the answerer stores keeps the words it arrived with: the edit lives in EDITS alone
        self.assertEqual(json.loads(r.cmd("HGET", desk.REQUESTS, desk.field(GROUP, 1129)))["text"], first)
        # the same words again (an edit of the preview alone) tells nobody; a message with no request neither
        self.assertEqual(relay_group.note_edit(r, ev), {})
        self.assertEqual(relay_group.note_edit(r, {**ev, "data": owner_msg(1130, "x")}), {})
        self.assertIsNone(desk.load(r, GROUP, 1130))
        # edited twice: the last words win, the first stay the first
        desk.add_edit(r, GROUP, 1129, "שוב אחרת", "2026-11-15T22:00:00Z")
        self.assertEqual((desk.load(r, GROUP, 1129)["text"], desk.load(r, GROUP, 1129)["text_at_receipt"]),
                         ("שוב אחרת", first))

    def test_closed_records_are_pruned_after_two_weeks(self):
        r = FakeRedis()
        old = desk.drop(desk.new_record(owner_msg(187, "מי אנחנו ?"), T0), "answered", at=T0)
        desk.create(r, old)
        desk.add_file(r, GROUP, 187, "/טלגרם/x/187-video.mp4")
        desk.add_edit(r, GROUP, 187, "מי אנחנו בעצם ?", T0)
        self.assertEqual(desk.prune(r, desk.parse_at(T0) + 3 * 86400), 0)
        self.assertEqual(r.cmd("HKEYS", desk.FILES), [desk.field(GROUP, 187)])   # kept while its request is
        self.assertEqual(desk.prune(r, desk.parse_at(T0) + 15 * 86400), 1)
        self.assertEqual(desk.all_records(r), [])
        self.assertEqual(r.cmd("HKEYS", desk.FILES) or [], [])                  # …and leaves with it
        self.assertEqual(r.cmd("HKEYS", desk.EDITS) or [], [])                  # …and so does its edit

    def test_the_group_is_remembered_by_number_for_quotes(self):
        r = FakeRedis()
        desk.remember(r, {"chat_id": GROUP, "message_id": 159, "sender": "Bina Agent",
                          "text": "מוכן: לחץ Continue with Google"}, T0)
        self.assertEqual(desk.recall(r, GROUP, 159)["sender"], "Bina Agent")
        self.assertIsNone(desk.recall(r, GROUP, 158))


class Relay(unittest.TestCase):
    """The loop's ledger step (note_group_message) and the busy check, without the network."""

    def ev(self, data):
        return {"type": "message.new", "at": T0, "data": data}

    def test_a_full_redis_costs_the_record_not_the_message(self):
        recorded, mark = relay_group.note_group_message(FakeRedis(refuse_writes=True),
                                                        self.ev(owner_msg(202, "…")), set(relay_group.DEFAULT_BOT_NAMES))
        self.assertEqual((recorded, mark), (False, "👀"))      # delivered without a record, never dropped

    def test_a_bot_reply_is_recorded_on_the_request_it_answers(self):
        r, bots = FakeRedis(), set(relay_group.DEFAULT_BOT_NAMES)
        self.assertEqual(relay_group.note_group_message(r, self.ev(owner_msg(202, "…")), bots), (True, "👀"))
        bot = {"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": 206, "sender": "Bina Agent",
               "text": "…", "reply_to": 202}
        self.assertEqual(relay_group.note_group_message(r, self.ev(bot), bots), (False, ""))
        self.assertEqual(desk.load(r, GROUP, 202)["answers"], [206])

    def test_the_bot_named_azaria_is_the_bot(self):
        r, bots = FakeRedis(), set(relay_group.DEFAULT_BOT_NAMES)
        relay_group.note_group_message(r, self.ev(owner_msg(968, "…")), bots)
        reply = {"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": 979, "sender": "Azaria",
                 "text": "…", "reply_to": 968}
        notice = {"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": 977, "sender": "Azaria",
                  "text": "🟢 🦅 vps1: …"}
        self.assertEqual(relay_group.note_group_message(r, self.ev(reply), bots), (False, ""))
        self.assertEqual(relay_group.note_group_message(r, self.ev(notice), bots), (False, ""))
        self.assertEqual(desk.load(r, GROUP, 968)["answers"], [979])
        self.assertEqual([x["message_id"] for x in desk.all_records(r)], [968])

    def test_a_replayed_message_keeps_its_records_mark(self):
        r, bots = FakeRedis(), set(relay_group.DEFAULT_BOT_NAMES)
        relay_group.note_group_message(r, self.ev(owner_msg(160, "…")), bots)
        desk.store(r, desk.take(desk.load(r, GROUP, 160), ["DGO-1336"]))
        self.assertEqual(relay_group.note_group_message(r, self.ev(owner_msg(160, "…")), bots), (True, "✍"))

    def test_busy_is_read_from_running_and_queue(self):
        self.assertTrue(relay_group.busy_of({"running": True, "queue": 0}))
        self.assertTrue(relay_group.busy_of({"running": False, "queue": 3}))
        self.assertFalse(relay_group.busy_of({"running": False, "queue": 0}))
        self.assertTrue(relay_group.busy_of(None))


class RelayRoundTwo(unittest.TestCase):
    def ev(self, data):
        return {"type": "message.new", "at": T0, "data": data}

    def test_a_lost_connection_is_raised_so_the_loop_reconnects_first(self):
        with self.assertRaises(ConnectionError):
            relay_group.note_group_message(FakeRedis(lose_socket=True), self.ev(owner_msg(202, "…")),
                                           set(relay_group.DEFAULT_BOT_NAMES))

    def test_no_sender_no_request(self):
        r = FakeRedis()
        msg = dict(owner_msg(300, "…"), sender="")
        self.assertEqual(relay_group.note_group_message(r, self.ev(msg), set(relay_group.DEFAULT_BOT_NAMES)),
                         (False, "👀"))
        self.assertEqual(desk.all_records(r), [])

    def test_a_finished_request_is_reopened_not_taken(self):
        rec = desk.drop(desk.new_record(owner_msg(187, "מי אנחנו ?"), T0), "answered in msg 188", at=T0)
        with self.assertRaises(ValueError):
            desk.take(rec, ["DGO-1"])

    def test_a_dropped_record_owes_no_promise(self):
        rec = desk.new_record(owner_msg(187, "…"), T0)
        desk.promise(rec, "x", hours=1, at=T0)
        desk.drop(rec, "answered", at=T0)
        self.assertEqual(desk.open_requests([rec], desk.parse_at(T0) + 5 * 86400), [])

    def test_answers_from_the_relay_and_the_cli_never_overwrite_each_other(self):
        r = FakeRedis()
        desk.create(r, desk.new_record(owner_msg(15, "…"), T0))
        desk.add_answer(r, GROUP, 15, 18)
        desk.add_answer(r, GROUP, 15, 21)
        desk.add_answer(r, GROUP, 15, 18)
        self.assertEqual(desk.load(r, GROUP, 15)["answers"], [18, 21])

    def test_prune_takes_orphan_answers_and_old_done_records(self):
        r = FakeRedis()
        done = desk.done(desk.take(desk.new_record(owner_msg(1, "…"), T0), ["DGO-1"], at=T0),
                         "https://example.org/x", at=T0)
        desk.create(r, done)
        desk.create(r, desk.new_record(owner_msg(2, "still open"), T0))
        desk.add_answer(r, GROUP, 99, 100)                     # a reply to a message that is not a request
        self.assertEqual(desk.prune(r, desk.parse_at(T0) + 15 * 86400), 1)
        self.assertEqual([x["message_id"] for x in desk.all_records(r)], [2])
        self.assertEqual(r.cmd("HKEYS", desk.ANSWERS), [])


class Loop(unittest.TestCase):
    """main() end to end over a fake stream: the first delivery fails, the message is read again — not lost."""

    def test_a_failed_first_delivery_is_read_again_after_the_reconnect(self):
        r = FakeRedis()
        stream = [("1-0", ["type", "message.new", "at", T0, "data",
                           json.dumps(owner_msg(202, "אנרואיד צריך לעבוד בדיוק כמו מק"), ensure_ascii=False)])]
        state = {"xread": 0, "sent": [], "fail": 1}

        def cmd(op, *a, _orig=r.cmd):
            if op == "XREVRANGE":
                return []                                    # «from now on» on an empty stream = 0-0
            if op == "XREAD":
                state["xread"] += 1
                if state["xread"] > 3:
                    raise KeyboardInterrupt                  # end the test's loop
                after = a[-1]
                new = [e for e in stream if after in ("0-0", "$") or e[0] > after]
                return [[relay_group.STREAM, new]] if new else None
            return _orig(op, *a)
        r.cmd = cmd

        def tell(session, text, token_path):
            if state["fail"]:
                state["fail"] -= 1
                raise ConnectionError("the agent door did not take the message: HTTP 502")
            state["sent"].append(text)

        saved = (relay_group.Redis, relay_group.tell_agent, relay_group.bot_token, relay_group.mark_received,
                 relay_group.time.sleep, relay_group.write_state)
        relay_group.Redis = lambda *a, **k: r
        relay_group.tell_agent = tell
        relay_group.bot_token = lambda label: ""
        relay_group.mark_received = lambda *a, **k: None
        relay_group.time.sleep = lambda s: None
        relay_group.write_state = lambda path, eid: None
        try:
            with self.assertRaises(KeyboardInterrupt):
                relay_group.main(["relay", "--session", "s1", "--sweep", "0"])
        finally:
            (relay_group.Redis, relay_group.tell_agent, relay_group.bot_token, relay_group.mark_received,
             relay_group.time.sleep, relay_group.write_state) = saved
        self.assertEqual(len(state["sent"]), 1)               # delivered once, after the failure — not lost, not twice
        self.assertIn("msg 202", state["sent"][0])
        self.assertEqual(desk.load(r, GROUP, 202)["state"], "received")


class Line(unittest.TestCase):
    """The answerer answered «זה לא עובד» about the wrong app because the line carried no reply (msg 160 → 166)."""

    def ev(self, data):
        return {"type": "message.new", "at": "2026-11-04T09:26:11Z", "data": data}

    def test_the_line_carries_the_number_and_the_message_he_replied_to(self):
        line = relay_group.line_for(
            self.ev(owner_msg(160, "זה לא עובד לא פותח לי שום דפדפן", reply_to=159)),
            {"message_id": 159, "sender": "Bina Agent", "at": "2026-11-04T09:24:00Z",
             "text": "מוכן: באריח … לחץ Continue with Google — ההתחברות נפתחת בדפדפן הלשכה"}, ledger=True)
        first, quote, hint = line.splitlines()
        self.assertTrue(first.startswith("TG: ED 09:26 UTC msg 160 "))
        self.assertIn("↩ msg 159 (Bina Agent, 09:24)", quote)
        self.assertIn("Continue with Google", quote)
        self.assertIn("desk take 160", hint)

    def test_a_reply_whose_quote_is_unknown_still_says_so(self):
        line = relay_group.line_for(self.ev(owner_msg(168, "הקישור לא עובד", reply_to=163)))
        self.assertIn("↩ msg 163 (not found", line)
        self.assertIn("answer THAT message's subject", line)

    def test_a_plain_message_is_one_line_as_before(self):
        line = relay_group.line_for(self.ev(owner_msg(169, "מה המצב הלשכה בכללי איך העדר שלנו ?")))
        self.assertEqual(len(line.splitlines()), 1)

    def test_the_bot_is_never_a_request(self):
        bots = set(relay_group.DEFAULT_BOT_NAMES)
        ev = self.ev({"chat_id": GROUP, "chat": "Bina Solutions Main", "message_id": 206, "sender": "Bina Agent"})
        self.assertFalse(relay_group.wanted(ev, "Bina Solutions Main", "", bots))
        self.assertTrue(relay_group.wanted(self.ev(owner_msg(202, "…")), "Bina Solutions Main", "", bots))


class TellAgent(unittest.TestCase):
    """The door's answers to one send (DGO-1878): msg 986 was typed into the session again and again, because a 502
    «not-confirmed» — the text typed, only not yet seen in the transcript — was read as «not delivered»."""

    def door(self, code, answer):
        sends = []

        def urlopen(req, timeout=None):
            sends.append(req)
            raise urllib.error.HTTPError(req.full_url, code, "door", {}, io.BytesIO(answer.encode("utf-8")))
        return sends, urlopen

    def tell(self, urlopen):
        with mock.patch.object(relay_group.urllib.request, "urlopen", urlopen), \
                mock.patch.object(relay_group.time, "sleep", lambda s: None), \
                mock.patch.object(relay_group, "agent_token", lambda p: "t"), \
                mock.patch.object(relay_group, "log", lambda *a: None):
            relay_group.tell_agent("local_x", "TG: …", "/bc/api-token")

    def test_typed_but_not_yet_seen_is_delivered_once(self):
        sends, urlopen = self.door(502, json.dumps({"error": "Return pressed, but the transcript does not show the "
                                                    "text yet — look at the app's screen", "code": "not-confirmed"}))
        self.tell(urlopen)
        self.assertEqual(len(sends), 1)

    def test_text_left_in_the_apps_composer_is_retried_then_raised(self):
        # the driver refuses a composer that is not empty, so a retry never pastes it twice; a lasting refusal is
        # raised, so the cursor stays and Stuck tells the group (DGO-2126)
        sends, urlopen = self.door(409, json.dumps({"error": "the session is mid-turn (busy); nothing was sent (the text "
                                                    "stays in its composer, unsent)", "code": "left-in-composer"}))
        with self.assertRaises(ConnectionError):
            self.tell(urlopen)
        self.assertEqual(len(sends), 3)

    def test_it_asks_not_to_be_queued_and_a_429_is_retried_then_raised(self):
        # a door with a cap of running turns (bina-claude, DGO-2126) would queue it, and a 202 is taken as delivered:
        # the relay asks never to be held in a line; a 429 from any door is retried, then raised — the cursor stays
        sends, urlopen = self.door(429, json.dumps({"error": "too many requests: nothing was sent", "code": "rate"}))
        with self.assertRaises(ConnectionError):
            self.tell(urlopen)
        self.assertEqual(len(sends), 3)
        self.assertEqual(json.loads(sends[0].data.decode("utf-8")).get("queue"), False, "it asks not to be queued")

    def test_busy_is_retried_and_then_raised(self):
        sends, urlopen = self.door(409, json.dumps({"error": "the session is mid-turn (busy); nothing was sent"}))
        with self.assertRaises(ConnectionError):
            self.tell(urlopen)
        self.assertEqual(len(sends), 3)

    def test_another_502_is_still_retried(self):
        sends, urlopen = self.door(502, "Bad Gateway")
        with self.assertRaises(ConnectionError):
            self.tell(urlopen)
        self.assertEqual(len(sends), 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
