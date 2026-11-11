#!/usr/bin/env python3
"""What the group may never be told (say_group.INTERNAL), without Telegram:
    python3 apps/telegram/relay/test_say_group.py
The refused forms are the ones found in replies and in the dashboard's masking on 2026-11-05 (DGO-1352, DGO-1329);
the passed ones are what a reply to the owner says every day — numbers, versions, dates, the console he opens."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import say_group     # noqa: E402

#: a token's shape, assembled here so no token-shaped literal sits in the file
TOKEN = "1234567890:" + "A" * 20 + "b" * 15


class Internal(unittest.TestCase):

    def refused(self, text):
        self.assertTrue(say_group.internal(text), "should be refused: %r" % text)

    def passed(self, text):
        self.assertEqual(say_group.internal(text), "", "should pass: %r" % text)

    def test_private_addresses_also_at_the_end_of_a_sentence(self):
        for text in ("the door is 10.9.8.7.", "בכתובת 192.168.16.104.", "172.18.0.1, then", "100.64.0.1",
                     "the metadata 169.254.169.254", "10.79.3.1:9003"):
            self.refused(text)

    def test_the_loopback_in_every_spelling(self):
        for text in ("127.0.0.1", "127.0.1.1 answered", "0.0.0.0", "open localhost:3000", "LOCALHOST", "::1",
                     "ip ::1."):
            self.refused(text)

    def test_ipv6_unique_local_and_link_local(self):
        for text in ("fd12:3456:789a::1", "fe80::1c2b:3aff:fe4d", "FE80::1"):
            self.refused(text)

    def test_localhost_names_of_one_label_or_several(self):
        for text in ("console.localhost", "http://forge.console.localhost/x", "see console.localhost."):
            self.refused(text)

    def test_a_bare_service_and_an_office_host_with_a_port(self):
        self.refused("http://plane:9003/api")
        self.refused("git-accounts.macbook:9005")

    def test_a_bot_token_is_refused_and_never_echoed(self):
        why = say_group.internal("the token is " + TOKEN)
        self.assertTrue(why)
        self.assertNotIn(TOKEN, why)
        self.assertNotIn(TOKEN[:12], why)

    def test_what_a_reply_says_every_day_passes(self):
        for text in ("DGO-1352", "גרסה 1.2.3", "Microsoft Windows [Version 10.0.26200.9457]", "2026-11-05 17:47",
                     "0.45GB פנויים מתוך 16.8", "3 מתוך 3", "1.2.3.4.5 is not an address", "10.5%",
                     "https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/projects/p/issues/i",
                     "feedback: fine", "a::1", "msg 263", "מספר 0501234567"):
            self.passed(text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
