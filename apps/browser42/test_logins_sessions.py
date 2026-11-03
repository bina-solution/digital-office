"""The signed-in scan, against a fabricated profile — no Chrome, no real cookies.

What this file exists for: `logins.py` answered "is there a password" and was then asked "is the
browser SIGNED IN", and the two questions are answered from different stores. The mistakes that
cost are the quiet ones — a "now" computed with the wrong epoch sign (measured 2026-10-14: it made
every expired cookie look live, and a logged-out console row was reported as a live session), and a
matcher loose enough that every ad cookie reads as a session (`_uetsid`, same day). Both are pinned
here, with the shapes that were actually in the profile.
"""
import contextlib
import importlib.util
import io
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("browser42_logins", Path(__file__).with_name("logins.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

#: 1601-01-01 is the WebKit epoch; a cookie's stamps are microseconds since then.
WEBKIT_OFFSET_S = 11644473600


def webkit(seconds_from_now: float) -> int:
    return int((time.time() + seconds_from_now + WEBKIT_OFFSET_S) * 1_000_000)


DAY = 86400


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        profile = os.path.join(self.tmp.name, "__default__")
        os.makedirs(os.path.join(profile, "Default"))
        self.db = os.path.join(profile, "Default", "Cookies")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER,"
                    " is_persistent INTEGER, last_update_utc INTEGER)")
        con.executemany("INSERT INTO cookies VALUES (?,?,?,?,?)", [
            # claude.ai: the real shape — a live session key on the parent domain.
            (".claude.ai", "sessionKey", webkit(30 * DAY), 1, webkit(-600)),
            (".claude.ai", "sessionKeyV3", webkit(30 * DAY), 1, webkit(-600)),
            (".claude.ai", "__cf_bm", webkit(1800), 1, webkit(-60)),
            # google: signed in, and the sign-in also stamped the country domain.
            (".google.com", "SID", webkit(35 * DAY), 1, webkit(-300)),
            (".google.com", "__Secure-1PSID", webkit(35 * DAY), 1, webkit(-300)),
            ("accounts.google.com", "__Host-GAPS", webkit(35 * DAY), 1, webkit(-300)),
            ("google.co.il", "SID", webkit(35 * DAY), 1, webkit(-300)),
            # github: the "logged_in" flag alone is NOT a session — measured 2026-10-14 11:24.
            (".github.com", "logged_in", webkit(300 * DAY), 1, webkit(-5 * DAY)),
            (".github.com", "_octo", webkit(300 * DAY), 1, webkit(-5 * DAY)),
            # a service whose proof cookie is there but EXPIRED: not connected, and that is the case
            # the wrong epoch sign used to get wrong.
            ("auth.localhost", "authentik_session", webkit(-2 * DAY), 1, webkit(-4 * DAY)),
            ("auth.localhost", "authentik_csrf", webkit(300 * DAY), 1, webkit(-4 * DAY)),
            # a host nobody declared, holding a session cookie that lives only as long as Chrome.
            ("app.example.com", "JSESSIONID", 0, 0, webkit(-120)),
            # a tracker that ends in "sid" and must never read as a session.
            (".canva.com", "_uetsid", webkit(DAY), 1, webkit(-30)),
            # an expired unknown-host session.
            ("old.example.com", "sessionid", webkit(-DAY), 1, webkit(-3 * DAY)),
        ])
        con.commit()
        con.close()
        MODULE.COOKIE_DB = self.db

    def test_now_is_in_this_century(self):
        """The sign of the epoch offset — the bug that made every expired cookie read as live."""
        now_us = MODULE._now_us()
        self.assertAlmostEqual(now_us / 1_000_000 - WEBKIT_OFFSET_S, time.time(), delta=5)

    def test_services_report_what_proves_them(self):
        report = {row["service"]: row for row in MODULE.service_sessions(MODULE._cookie_rows())}
        self.assertEqual(report["claude"]["state"], "connected")
        self.assertIn("sessionKey", report["claude"]["proof"])
        self.assertEqual(report["google"]["state"], "connected")
        self.assertIn("__Host-GAPS", report["google"]["spot"])       # the account chooser was seen
        self.assertEqual(report["github"]["state"], "not_connected")  # `logged_in` is not a session
        self.assertEqual(report["facebook"]["state"], "not_connected")
        # A service whose session is not a cookie says so rather than claiming "not connected".
        self.assertEqual(report["whatsapp"]["state"], "not_a_cookie")
        self.assertIn("IndexedDB", report["whatsapp"]["note"])

    def test_expired_cookies_are_not_sessions(self):
        rows = MODULE._cookie_rows()
        self.assertNotIn("auth.localhost", [h["host"] for h in MODULE.other_sessions(rows)])
        # A host is answered by what was MEASURED, not by a verdict about the service.
        self.assertEqual(MODULE.session_of("auth.localhost", rows)["state"], "no_live_cookie")

    def test_unknown_hosts_with_a_live_session_show_up(self):
        hosts = {h["host"]: h for h in MODULE.other_sessions(MODULE._cookie_rows())}
        self.assertIn("app.example.com", hosts)
        self.assertEqual(hosts["app.example.com"]["cookies"], ["JSESSIONID"])
        self.assertNotIn("old.example.com", hosts)                    # expired

    def test_tracker_cookies_are_not_sessions(self):
        """`_uetsid` ends in "sid"; matching it would call every ad cookie a sign-in."""
        hosts = {h["host"] for h in MODULE.other_sessions(MODULE._cookie_rows())}
        self.assertNotIn("canva.com", hosts)
        # …and it is never called "not connected": Canva was signed in that day, through Google,
        # holding no session cookie at all (2026-10-14) — see session_of's docstring.
        self.assertEqual(MODULE.session_of("canva.com", MODULE._cookie_rows())["state"], "no_live_cookie")
        self.assertEqual(MODULE.session_of("claude.ai", MODULE._cookie_rows())["state"], "connected")

    def test_await_returns_as_soon_as_a_session_exists(self):
        """The human handoff: `await` answers from the same fact `sessions` reports."""
        MODULE.POLL_SECONDS = 0.01
        MODULE.DEFAULT_AWAIT_SECONDS = 5
        original = MODULE._cookie_rows
        self.addCleanup(lambda: setattr(MODULE, "_cookie_rows", original))
        self.assertEqual(MODULE.session_of("claude", original())["state"], "connected")
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            with self.assertRaises(SystemExit) as caught:          # a service nothing signed in to
                MODULE.cmd_await("linkedin", "0.05")
            self.assertEqual(caught.exception.code, 2)
            MODULE.cmd_await("claude", "5")                          # …and the connect path answers
        self.assertIn('"state": "connected"', quiet.getvalue())


if __name__ == "__main__":
    unittest.main()
