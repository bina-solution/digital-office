"""The owner's one watched consent to a draft panel write, at the app's doors (DGO-1032, round three).

    python3 apps/domains/test_write_consent.py

The second reader of round two: the consent was a flag ANY caller set — the screen's door, the sync path
and the op API other apps and agents call — tied to no person, never one-time (nothing marked a portal
verified), and the history logged a record "created" that already existed while a save that lost records
left no trace. Held here: only the screen's door takes the consent, and only with the person the edge
signed in; one watched success makes the action the office's; the history says what each write DID.
"""
import json
import os
import sys
import tempfile
import unittest

STATE = tempfile.mkdtemp(prefix="domains-consent-")
os.environ["DOMAINS_STATE_DIR"] = STATE
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402
import portal  # noqa: E402

ACCOUNT = ({"id": "1", "protocol": "domain_portal_session"}, {}, None)
CREATE = {"action": "create", "type": "A", "name": "fpg", "content": "93.184.216.10", "ttl": 3600}


class DoorTests(unittest.TestCase):
    def setUp(self):
        self.jobs, self.events, self.written = [], [], []
        original_file = portal.VERIFIED_FILE
        portal.VERIFIED_FILE = portal.Path(tempfile.mkdtemp(prefix="domains-verified-")) / "portal-verified.json"
        self.addCleanup(setattr, portal, "VERIFIED_FILE", original_file)
        patches = {
            (app.accounts, "resolve"): lambda aid: ACCOUNT,
            (app.webengine, "submit"): lambda name, fn, params=None, **kw: (
                self.jobs.append(params), {"id": "job-1"})[1],
            (app.registry, "event"): lambda domain, kind, message, meta=None: self.events.append(
                {"kind": kind, "message": message, "meta": meta or {}}) or 1,
            (app.portal_mod, "run_write"): self.run_write,
            (app, "_read_records"): lambda provider, secret, name: [],
        }
        for (owner, name), fake in patches.items():
            original = getattr(owner, name)
            setattr(owner, name, fake)
            self.addCleanup(setattr, owner, name, original)
        self.answer = {"ok": True, "state": "ok", "guard": "checked",
                       "record": {"name": "fpg.digital-office.co.il.", "type": "A",
                                  "content": "93.184.216.10", "ttl": "3600"}}

    def run_write(self, portal_name, action, params, endpoint=None, allow_draft_write=False):
        self.written.append(allow_draft_write)
        if not allow_draft_write and not portal.verified(portal_name, action):
            return portal._draft_refusal(portal_name, action, False)
        return dict(self.answer)

    def test_the_screens_door_takes_the_consent_only_with_a_signed_in_person(self):
        refused = app._records_endpoint("1", "digital-office.co.il", {**CREATE, "allow_draft_write": True}, None)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual((self.jobs, self.written), ([], []), "a write was queued without a person")
        app._records_endpoint("1", "digital-office.co.il", {**CREATE, "allow_draft_write": True}, "owner@office")
        self.assertEqual(self.jobs[-1]["consented_by"], "owner@office")
        self.assertTrue(self.jobs[-1]["allow_draft_write"])

    def test_the_op_api_never_takes_the_consent(self):
        """`/writeRecord` is what other apps and agents call: the flag there is refused by name."""
        res = app._op_write_record({**CREATE, "domain": "digital-office.co.il", "account": "1",
                                    "allow_draft_write": True})
        self.assertEqual(getattr(res, "status_code", None), 403, res)
        self.assertEqual(self.written, [])

    def test_the_sync_path_is_held_to_the_same_rule(self):
        res = app._records_endpoint("1", "digital-office.co.il",
                                    {**CREATE, "sync": True, "allow_draft_write": True}, None)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.written, [])
        res = app._records_endpoint("1", "digital-office.co.il", {**CREATE, "sync": True}, None)
        self.assertEqual(res.status_code, 409, "an unwatched draft write went through without consent")

    def test_one_watched_success_makes_the_action_the_offices_and_is_logged_with_the_person(self):
        res = app._portal_written("digital-office.co.il", "create", dict(CREATE), "owner@office")
        self.assertTrue(res["ok"])
        self.assertTrue(portal.verified("internic", "create"))
        self.assertEqual([e["kind"] for e in self.events], ["dns_create"])
        self.assertIn("owner@office", self.events[0]["message"])
        self.assertEqual(self.events[0]["meta"]["consented_by"], "owner@office")
        again = app._portal_written("digital-office.co.il", "create", dict(CREATE), None)   # no consent now
        self.assertTrue(again["ok"], again)

    def test_a_success_whose_guard_did_not_run_marks_nothing(self):
        """The third reader: an "unavailable" guard still marked the action watched — a licence earned by a
        write nobody could show undid nothing."""
        self.answer = {**self.answer, "guard": "unavailable: the served page has no record rows"}
        app._portal_written("digital-office.co.il", "create", dict(CREATE), "owner@office")
        self.assertFalse(portal.verified("internic", "create"))

    def test_a_record_that_was_already_there_is_no_change_and_marks_nothing(self):
        self.answer = {**self.answer, "unchanged": True}
        app._portal_written("digital-office.co.il", "create", dict(CREATE), "owner@office")
        self.assertEqual(self.events, [])
        self.assertFalse(portal.verified("internic", "create"))

    def test_a_save_that_did_not_come_out_as_written_is_history_with_its_evidence(self):
        self.answer = {"ok": False, "state": "assert_failed", "saved": True,
                       "error": "הרשומה נכתבה, אבל 2 רשומות שהיו באזור חסרות בו עכשיו — בדקו בפורטל",
                       "detail": json.dumps({"missing": [{"name": "mail"}]})}
        app._portal_written("digital-office.co.il", "create", dict(CREATE), "owner@office")
        self.assertEqual([e["kind"] for e in self.events], ["dns_create_failed"])
        self.assertIn("missing", self.events[0]["meta"]["result"]["detail"])
        self.assertFalse(portal.verified("internic", "create"), "a failed write was taken as watched")

    def test_a_refusal_before_anything_was_written_is_not_history(self):
        self.answer = {"ok": False, "state": "conflict", "error": "האזור בשרת השתנה"}
        app._portal_written("digital-office.co.il", "create", dict(CREATE), "owner@office")
        self.assertEqual(self.events, [])

    def test_both_doors_say_what_a_refusal_is(self):
        """The fifth reader: the sync door answered 409 for everything, and a deliberate refusal read 502."""
        for state, status in (("invalid", 400), ("conflict", 409), ("guard_unavailable", 409),
                              ("needs_verification", 409), ("not_scripted", 409), ("selector_missing", 502),
                              ("unverified", 502), ("timeout", 502)):
            self.assertEqual(app._portal_status({"state": state}), status, state)
            self.answer = {"ok": False, "state": state, "error": "x"}
            res = app._portal_write("digital-office.co.il", "create", dict(CREATE), "owner@office")
            self.assertEqual(res.status_code, status, state)

    def test_the_jobs_failure_carries_the_writers_evidence(self):
        self.answer = {"ok": False, "state": "assert_failed", "saved": True, "error": "x",
                       "detail": '{"found": false, "records_after": 3}'}
        with self.assertRaises(app.DomainError) as raised:
            app._portal_write_job(lambda *a: None, "digital-office.co.il", "create", dict(CREATE),
                                  {"consented_by": "owner@office"})
        self.assertIn("records_after", raised.exception.body().get("detail", ""))


if __name__ == "__main__":
    unittest.main()
