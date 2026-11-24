#!/usr/bin/env python3
"""A message the agent's door keeps refusing (relay_group.Stuck, DGO-2049), without Telegram or a door:
    python3 apps/telegram/relay/test_relay_stuck.py
Measured on the HP 2026-11-19: one message tried 1,541 times in 31 hours, every 20-80 s, each try driving the
office's Claude app to another page, and nobody told. These checks pin the waits that grow, the shorter wait while
the session is only busy, and the one line the group gets — what it says, and that it is not a reply."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relay_group     # noqa: E402

NOT_SENT = ('the agent door did not take the message: HTTP 409 {"error":"the app shows another page than this '
            'session; nothing was sent')
BUSY = 'the agent door did not take the message: HTTP 409 {"error":"the session is mid-turn (busy); nothing was sent'


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class StuckTests(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        self.stuck = relay_group.Stuck(tell_after=600, clock=self.clock)

    def rounds(self, eid, why, n, every, tell_works=True):
        seen = []
        for _ in range(n):
            wait, due = self.stuck.failed(eid, why)
            if due and tell_works:
                self.stuck.told_now()
            seen.append((wait, due))
            self.clock.t += every
        return seen

    def test_the_wait_grows_to_ten_minutes(self):
        waits = [w for w, _ in self.rounds("1-0", NOT_SENT, 10, 1)]
        self.assertEqual(waits, [5, 10, 20, 40, 80, 160, 320, 600, 600, 600])

    def test_a_busy_session_is_waited_for_at_most_a_minute_and_never_told(self):
        seen = self.rounds("2-0", BUSY, 12, 120)                      # 24 minutes of «busy»
        self.assertEqual(max(w for w, _ in seen), 60)
        self.assertFalse(any(d for _, d in seen))

    def test_a_message_waiting_in_the_doors_line_ahead_is_busy_not_stuck(self):
        # bina-claude's line (DGO-2126): a message to the session already waits there, and this one goes after it
        at_cap = ('the agent door did not take the message: HTTP 429 {"error":"a message to this session waits in the '
                  'line: nothing was sent — send again when it is in","code":"at-cap"}')
        seen = self.rounds("2-1", at_cap, 12, 120)
        self.assertEqual(max(w for w, _ in seen), 60)
        self.assertFalse(any(d for _, d in seen))

    def test_the_group_is_told_once_at_ten_minutes_of_nothing_sent(self):
        seen = self.rounds("3-0", NOT_SENT, 30, 100)                  # 50 minutes, a round every 100 s
        told = [i for i, (_, d) in enumerate(seen) if d]
        self.assertEqual(told, [6], "told once, at the round that reaches 600 s")

    def test_a_long_busy_turn_does_not_start_the_clock(self):
        self.rounds("4-0", BUSY, 10, 100)                             # a 16-minute turn
        wait, due = self.stuck.failed("4-0", NOT_SENT)                # then one «locked»: not an alarm yet
        self.assertFalse(due)
        self.clock.t += 600
        wait, due = self.stuck.failed("4-0", NOT_SENT)                # ten minutes of refusals: now
        self.assertTrue(due)

    def test_a_long_busy_turn_between_two_locked_answers_is_not_an_alarm(self):
        self.stuck.failed("9-0", NOT_SENT)                            # a «locked» while a command thread delivers
        self.clock.t += 60
        self.rounds("9-0", BUSY, 12, 60)                              # then the turn it started: 12 minutes busy
        wait, due = self.stuck.failed("9-0", NOT_SENT)                # «locked» again: the session works, not stuck
        self.assertFalse(due)

    def test_a_notice_that_failed_is_due_again(self):
        seen = self.rounds("5-0", NOT_SENT, 12, 100, tell_works=False)
        self.assertGreater(sum(1 for _, d in seen if d), 1, "a notice that did not go out is tried again")

    def test_another_message_starts_afresh(self):
        self.rounds("6-0", NOT_SENT, 8, 100)
        self.assertEqual(self.stuck.failed("7-0", NOT_SENT), (5, False))

    def test_a_delivery_ends_it(self):
        self.rounds("8-0", NOT_SENT, 8, 100)
        self.stuck.delivered("8-0")
        self.assertEqual(self.stuck.failed("8-0", NOT_SENT), (5, False))


class NoticeTests(unittest.TestCase):

    def test_the_notice_is_hebrew_with_no_error_text(self):
        text = relay_group.stuck_text(1_763_536_000)
        self.assertIn("סוכן הקבוצה", text)
        for english in ("HTTP", "409", "error", "door", "session", "nothing was sent"):
            self.assertNotIn(english, text)
        self.assertNotIn("לפי הסדר", text, "no promise the capped stream cannot keep")

    def test_the_notice_is_its_own_message_not_a_reply(self):
        sent = {}

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=0):
            sent["url"] = req.full_url
            sent["body"] = json.loads(req.data.decode("utf-8"))
            return Resp()

        with mock.patch.object(relay_group.urllib.request, "urlopen", fake_urlopen):
            ok = relay_group.tell_stuck("1:AA", "-100123", 1_763_536_000)
        self.assertTrue(ok)
        self.assertTrue(sent["url"].endswith("/sendMessage"))
        self.assertNotIn("reply_parameters", sent["body"], "a reply would be recorded as the request's answer")
        self.assertEqual(sent["body"]["chat_id"], "-100123")

    def test_no_token_tells_nobody_and_says_so(self):
        self.assertFalse(relay_group.tell_stuck("", "-100123", 0))


if __name__ == "__main__":
    unittest.main(verbosity=1)
