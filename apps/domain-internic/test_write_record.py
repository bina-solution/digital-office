"""domain-internic: the provider's write, its consent and its door; the sign-in's stops (DGO-1473).

    python3 apps/domain-internic/test_write_record.py

Held here, with no browser and no credential plane (every door is a fake):
  - a write the office never watched is refused without a consent, and runs with one;
  - only a write that CHANGED the zone, whose guard RAN, with a consent, marks the action the office's;
  - a consent is taken only from inside the container (the CLI); any other caller's is dropped (the second
    reader: the body's word alone unlocked every later write);
  - the sign-in touches nothing when the browser is already signed in, or when the page is not a login;
  - a missing credential is named with its screen; the browser's store not holding it yet is named too;
  - the sign-in never presses Enter (an empty form submitted is a failed attempt on the account), never
    types a password, takes the code branch only when a code field exists, and clears the fields on a stop;
  - two sign-ins never run at once.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest

os.environ["DOMAINS_STATE_DIR"] = tempfile.mkdtemp(prefix="domain-internic-")
os.environ["REDIS_HOST_INTERNAL"] = "127.0.0.1"
os.environ["REDIS_PASSWORD"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402
import login  # noqa: E402
import portal  # noqa: E402

CREATE = {"action": "create", "domain": "digital-office.co.il", "type": "A", "name": "*.exampleu",
          "value": "93.184.216.11", "ttl": 3600}


class Quiet(unittest.TestCase):
    def setUp(self):
        self.published = []
        original = app.FLOW.publish
        app.FLOW.publish = lambda t, title, data=None, link="": self.published.append((t, title, data))
        self.addCleanup(setattr, app.FLOW, "publish", original)


class WriteTests(Quiet):
    def setUp(self):
        super().setUp()
        original = portal.VERIFIED_FILE
        portal.VERIFIED_FILE = portal.Path(tempfile.mkdtemp(prefix="di-verified-")) / "portal-verified.json"
        self.addCleanup(setattr, portal, "VERIFIED_FILE", original)
        self.calls = []
        self.answer = {"ok": True, "state": "ok", "guard": "checked",
                       "record": {"name": "*.exampleu.digital-office.co.il.", "type": "A", "content": "93.184.216.11"}}
        real = portal.ZONE_WRITERS[("internic", "create")]
        portal.ZONE_WRITERS[("internic", "create")] = self.writer
        self.addCleanup(portal.ZONE_WRITERS.__setitem__, ("internic", "create"), real)

    def writer(self, portal_name, params, endpoint):
        self.calls.append(params)
        return dict(self.answer)

    def test_an_unwatched_write_without_consent_is_refused_and_nothing_is_written(self):
        res = app.write_record(dict(CREATE))
        self.assertEqual(res["state"], "needs_verification")
        self.assertEqual(self.calls, [])

    def test_a_consented_write_that_was_read_back_makes_the_action_the_offices(self):
        res = app.write_record({**CREATE, "consented_by": "owner (chat, DGO-1473)"})
        self.assertTrue(res["ok"] and res.get("marked_verified"), res)
        self.assertTrue(portal.verified("internic", "create"))
        mark = json.loads(portal.VERIFIED_FILE.read_text())["internic"]["create"]
        self.assertEqual(mark["by"], "owner (chat, DGO-1473)")
        again = app.write_record({**CREATE, "name": "exampleu"})          # no consent: the office's own now
        self.assertTrue(again["ok"], again)

    def test_a_record_already_there_or_a_guard_that_did_not_run_marks_nothing(self):
        for answer in ({**self.answer, "unchanged": True}, {**self.answer, "guard": "unavailable: no rows"},
                       {"ok": False, "state": "assert_failed", "saved": True}):
            self.answer = answer
            app.write_record({**CREATE, "consented_by": "owner"})
            self.assertFalse(portal.verified("internic", "create"), answer)

    def test_a_write_without_a_domain_is_invalid(self):
        self.assertEqual(app.write_record({"type": "A"})["state"], "invalid")


class FakeRequest:
    def __init__(self, host, body):
        self.client = type("C", (), {"host": host})() if host else None
        self._body = body

    async def json(self):
        return dict(self._body)


class ConsentDoorTests(WriteTests):
    def post(self, host, body):
        return asyncio.run(app.api_records(FakeRequest(host, body)))

    def test_a_consent_from_the_network_is_dropped(self):
        for host in ("172.18.0.9", "10.79.7.1", None):
            res = self.post(host, {**CREATE, "consented_by": "anyone"})
            self.assertEqual(res["state"], "needs_verification", host)
            self.assertIn("--consent", res.get("how", ""))
        self.assertEqual(self.calls, [])
        self.assertFalse(portal.verified("internic", "create"))

    def test_a_consent_from_inside_the_container_is_taken(self):
        res = self.post("127.0.0.1", {**CREATE, "consented_by": "owner: DGO-1473"})
        self.assertTrue(res["ok"] and res.get("marked_verified"), res)


# ── the sign-in ─────────────────────────────────────────────────────────────────────────────────────
ORIGIN = "https://portal.internic.co.il"


def page(**kw):
    base = {"url": ORIGIN + "/user/login", "origin": ORIGIN, "ready": "complete", "password": True,
            "password_len": 0, "user_len": 0, "code": False, "captcha": False, "refused": False}
    return {**base, **kw}


class FakeSession:
    """The browser contract as login.py uses it. `pages` answers PAGE_JS in order (the last one repeats)."""

    def __init__(self, states, pages, after_keys=None, submit="clicked"):
        self.states, self.pages, self.after_keys = list(states), list(pages), after_keys
        self.submit = submit
        self.actions = []

    def state(self, origin=None):
        return self.states.pop(0) if self.states else {"authenticated": False, "state": "needs_human_login"}

    def open(self, url, retries=1, snapshot=True):
        self.actions.append(("open", url))

    def _next_page(self):
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]

    def call(self, tool, args=None):
        args = args or {}
        self.actions.append((tool, {k: v for k, v in args.items() if k != "function"}))
        if tool == "browser_evaluate":
            fn = args["function"]
            if fn is login.PAGE_JS:
                return {"text": "### Result\n" + json.dumps(json.dumps(self._next_page()))}
            if fn in (login.MARK_USER_JS, login.MARK_CODE_JS):
                # as the real MCP answers: the code it ran (which contains 'marked') FIRST, then the result
                return {"text": "### Ran Playwright code\n```js\nawait page.evaluate('... return \\'marked\\' ...')\n```\n"
                                "### Result\n\"marked\"\n### Page\n- Page URL: " + ORIGIN}
            if fn is login.CLEAR_JS:
                self.actions.append(("cleared", {}))
                return {"text": "### Result\n\"cleared\""}
            if "return 'wrong_page'" in fn:
                assert ORIGIN in fn and "%ORIGIN%" not in fn, "the submit was not given the portal's origin"
                self.actions.append(("submit", {}))
                return {"text": "### Ran Playwright code\n... return 'clicked' ...\n### Result\n\"%s\"" % self.submit}
            raise AssertionError("an evaluate the fake does not know: " + fn[:80])
        if tool == "browser_click":
            assert args.get("target") == '[data-dgo-login="user"]' or args.get("element"), args
        if tool == "browser_press_key" and args.get("key") == "Tab" and self.after_keys:
            self.pages.insert(0, self.after_keys)
        return {"text": ""}

    def element_args(self, tool, node):
        return {"element": node["name"], "target": node.get("ref") or node.get("css")}

    def keys(self):
        return [a[1].get("key") for a in self.actions if a[0] == "browser_press_key"]


class SignInTests(Quiet):
    def setUp(self):
        super().setUp()
        self.cred = {"known": True, "declared": True, "status": "healthy", "rows": [login.CONNECTION]}
        for owner, name, fake in ((login, "configured", lambda: dict(self.cred)),
                                  (login.time, "sleep", lambda s: None)):
            original = getattr(owner, name)
            setattr(owner, name, fake)
            self.addCleanup(setattr, owner, name, original)

    def run_with(self, session):
        original = portal.session_for
        portal.session_for = lambda p, e=None: session
        self.addCleanup(setattr, portal, "session_for", original)
        return login.sign_in()

    def test_already_signed_in_touches_nothing(self):
        s = FakeSession([{"authenticated": True, "state": "ok", "url": ORIGIN + "/dashboard/main"}], [page()])
        res = self.run_with(s)
        self.assertTrue(res["ok"] and res["already_signed_in"])
        self.assertEqual(s.actions, [])

    def test_a_page_that_is_not_a_login_is_never_touched(self):
        for st in ({"authenticated": False, "state": "blocked", "reason": "WAF"},
                   {"authenticated": False, "state": "browser_unavailable"}):
            s = FakeSession([st], [page()])
            res = self.run_with(s)
            self.assertEqual((res["ok"], res["state"]), (False, st["state"]))
            self.assertEqual(s.actions, [])

    def test_a_missing_credential_is_named_with_its_screen(self):
        self.cred = {"known": True, "declared": True, "status": "unset", "rows": []}
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}], [page()])
        res = self.run_with(s)
        self.assertEqual((res["state"], res["screen"]), ("credential_not_configured", "/a/connections/"))
        self.assertEqual(s.actions, [])

    def test_the_browser_store_not_holding_it_yet_is_named_and_the_fields_are_cleared(self):
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}], [page()])
        res = self.run_with(s)
        self.assertEqual(res["state"], "not_in_browser_store")
        self.assertIn(("cleared", {}), s.actions)
        self.assertNotIn("Enter", s.keys())

    def test_a_good_sign_in_picks_the_saved_login_and_never_types_it(self):
        # ends on the dashboard the portal really lands on: with the login page repeating, _settle waited its
        # whole 25 s deadline (the second reader: 26 s of the suite's 26)
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": True, "state": "ok", "url": ORIGIN + "/dashboard/main"}],
                        [page(), page(), page(password=False, url=ORIGIN + "/dashboard/main")],
                        after_keys=page(user_len=12, password_len=14))
        res = self.run_with(s)
        self.assertTrue(res["ok"] and res.get("signed_in"), res)
        self.assertEqual(s.keys(), ["ArrowDown", "Tab"])
        self.assertFalse([a for a in s.actions if a[0] == "browser_type"], "something was typed")
        self.assertNotIn(("cleared", {}), s.actions, "a signed-in page was cleared")

    def test_chrome_filling_on_the_click_needs_no_keys(self):
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": True, "state": "ok"}],
                        [page(), page(user_len=12, password_len=14), page(password=False, url=ORIGIN + "/dashboard/main")])
        self.assertTrue(self.run_with(s)["ok"])
        self.assertEqual(s.keys(), [])

    def test_a_refused_password_is_not_retried(self):
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": False, "state": "needs_human_login"}],
                        [page(), page(user_len=3, password_len=3), page(user_len=3, password_len=3, refused=True)])
        res = self.run_with(s)
        self.assertEqual(res["state"], "login_failed")
        self.assertEqual(len([a for a in s.actions if a[0] == "browser_click"]), 1, "clicked twice")

    def test_a_page_that_only_mentions_a_code_is_not_a_code_request(self):
        """The second reader: a dashboard that says «קוד העברה» sent a signed-in office to the mail."""
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": True, "state": "ok"}],
                        [page(), page(user_len=3, password_len=3),
                         page(password=False, code=False, url=ORIGIN + "/dashboard/main")])
        res = self.run_with(s)
        self.assertTrue(res["ok"], res)
        self.assertFalse(res.get("mail_code"))

    def test_a_code_asked_with_no_mailbox_named_stops_by_name_and_clears(self):
        original = login.MAIL_CONNECTION
        login.MAIL_CONNECTION = ""
        self.addCleanup(setattr, login, "MAIL_CONNECTION", original)
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": False, "state": "needs_human_login"}],
                        [page(), page(user_len=3, password_len=3),
                         page(password=False, code=True, url=ORIGIN + "/user/verify")])
        res = self.run_with(s)
        self.assertEqual(res["state"], "needs_mail_code")
        self.assertIn(("cleared", {}), s.actions)

    def test_a_tab_on_another_origin_is_never_filled(self):
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}],
                        [page(origin="https://portal.internic.co.il.evil.example")])
        res = self.run_with(s)
        self.assertEqual(res["state"], "wrong_page")
        self.assertFalse([a for a in s.actions if a[0] == "browser_click"])

    def test_a_form_that_emptied_before_the_click_is_never_sent(self):
        """The second reader: the shared tab reloaded between the length read and the submit."""
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}],
                        [page(), page(user_len=3, password_len=3)], submit="empty")
        res = self.run_with(s)
        self.assertEqual(res["state"], "login_selector_missing")
        self.assertIn("nothing reached the portal", res["reason"])
        self.assertIn(("cleared", {}), s.actions)

    def test_the_code_page_is_read_where_it_is_not_reloaded(self):
        original = login.MAIL_CONNECTION
        login.MAIL_CONNECTION = ""
        self.addCleanup(setattr, login, "MAIL_CONNECTION", original)
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}],
                        [page(), page(user_len=3, password_len=3),
                         page(password=False, code=True, url=ORIGIN + "/user/verify")])
        self.run_with(s)
        opened = [a for a in s.actions if a[0] == "open"]
        self.assertEqual(len(opened), 1, "the code page was navigated away from")

    def test_a_code_sign_in_that_succeeds_answers_ok_with_its_seconds(self):
        """Gate G80 (DGO-1496): _finish_with_code read `started`, a name that lived only in _sign_in, so the one
        path that ended in success — the mailed code accepted — raised NameError on its way out."""
        for owner, name, fake in ((login, "MAIL_CONNECTION", "mail-internic"),
                                  (login, "mail_code", lambda since, wait=120: "482913")):
            original = getattr(owner, name)
            setattr(owner, name, fake)
            self.addCleanup(setattr, owner, name, original)
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"},
                         {"authenticated": True, "state": "ok", "url": ORIGIN + "/dashboard/main"}],
                        [page(), page(user_len=3, password_len=3),
                         page(password=False, code=True, url=ORIGIN + "/user/verify"),
                         page(password=False, code=False, url=ORIGIN + "/dashboard/main")])
        res = self.run_with(s)
        self.assertTrue(res["ok"] and res.get("signed_in") and res.get("mail_code"), res)
        self.assertIsInstance(res.get("seconds"), float)
        self.assertEqual(len([a for a in s.actions if a[0] == "browser_type"]), 1, "the code was not typed once")
        self.assertNotIn(("cleared", {}), s.actions, "a signed-in page was cleared")

    def test_a_missing_user_name_is_named_too(self):
        self.cred = {"known": True, "declared": True, "status": "healthy", "user": False, "rows": []}
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}], [page()])
        res = self.run_with(s)
        self.assertEqual(res["state"], "credential_not_configured")
        self.assertIn("user name", res["reason"])

    def test_a_plane_that_does_not_answer_is_not_called_missing(self):
        self.cred = {"known": False}
        s = FakeSession([{"authenticated": False, "state": "needs_human_login"}], [page()])
        self.assertEqual(self.run_with(s)["state"], "credential_plane_unreachable")
        self.assertEqual([a for a in s.actions if a[0] != "open"], [])

    def test_two_sign_ins_never_run_at_once(self):
        login._BUSY.acquire()
        try:
            self.assertEqual(login.sign_in()["state"], "busy")
        finally:
            login._BUSY.release()


class FlowTests(unittest.TestCase):
    def test_publishing_with_redis_away_is_counted_not_raised(self):
        # The app publishes through the office's ONE publisher (DGO-1402's follow-up). It is mounted at /opt/dgo in
        # the container, so here it is loaded from the checkout and pointed at a port where nothing listens: the
        # publish returns, and the failure is COUNTED where the screen reads it — not merely "not mounted".
        import importlib
        import socket
        here = os.path.dirname(os.path.abspath(__file__))
        pub_dir = os.path.join(here, "..", "..", "platform-base", "redis")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]          # free now, and nothing listens on it once closed
        saved = {k: os.environ.get(k) for k in ("REDIS_HOST_INTERNAL", "REDIS_PORT_INTERNAL", "REDIS_PASSWORD")}
        os.environ.update(REDIS_HOST_INTERNAL="127.0.0.1", REDIS_PORT_INTERNAL=str(port), REDIS_PASSWORD="")
        sys.path.insert(0, pub_dir)
        before = app._flowpub
        try:
            import flowpub
            app._flowpub = importlib.reload(flowpub)
            flow = app.Flow()
            flow.publish("record.created", "x", {"a": 1})   # returns at once: the send is the publisher's thread's
            self.assertTrue(app._flowpub.flush(5))
            self.assertEqual(flow.published, 0)
            self.assertIn("Connection", flow.error or "")    # ConnectionRefusedError, counted by the publisher
            self.assertEqual(app._flowpub.stats()["failed"], 1)
        finally:
            app._flowpub = before
            sys.path.remove(pub_dir)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
