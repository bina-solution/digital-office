"""A record written into the InterNIC zone editor (DGO-1032), against a fake panel that behaves as the live
one measured on 2026-10-22.

    python3 apps/domains/test_portal_write.py

The panel, as it is: every record row carries `name_<n>`; «הוסף רשומה ריקה» adds a row whose inputs carry
no name; «שמור שינויים» asks «האם לשמור את השינויים?» over «<N> רשומות» and writes the WHOLE form. What is
held here: the new row and only it is filled; a save dialog that counts anything but one more record is
cancelled; the write is proved by the zone the SERVER returns; a draft portal writes nothing without the
owner's consent; and update/delete are refused by name instead of "succeeding" through an empty script.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_session as bs  # noqa: E402
import portal  # noqa: E402

DOMAIN = "digital-office.co.il"
ZONE = [{"name": "digital-office.co.il.", "type": "A", "content": "93.184.216.5", "ttl": "86400"},
        {"name": "mail.digital-office.co.il.", "type": "A", "content": "93.184.216.5", "ttl": "86400"},
        {"name": "www.digital-office.co.il.", "type": "CNAME", "content": "digital-office.co.il.", "ttl": "3600"}]


def spec_of(src):
    """The argument a `(fn)({...})` source was called with."""
    return json.loads(src[src.rindex(")({") + 2:-1]) if ")({" in src else {}


class Panel:
    """The zone editor: saved records (the server), the form (the page), the dialog."""
    def __init__(self, records, saves=True):
        self.saved = [dict(r) for r in records]
        self.form = [dict(r) for r in records]
        self.fresh = []                   # rows added by «הוסף רשומה ריקה», not saved yet
        self.dialog = None
        self.saves = saves
        self.clicks = []
        self.meanwhile = None             # a record someone saves on the server while the row is filled
        self.served = True                # whether the editor's address serves its rows (round three)
        self.kept_ttl = None              # a panel that keeps its own TTL, whatever is typed
        self.readable = True              # whether the zone can be read back after the save
        self.others_selected = 0          # other domains already ticked on the dashboard (round four)
        self.crash_after_confirm = False  # the browser falls after the save is confirmed (round four)
        self.fetches = 0                  # the guard's served reads: the 1st as the editor loads, the 2nd
                                          # just before the click — a change "meanwhile" lands between them
        self.served_differs = False       # a page whose script fills its fields serves other rows (round five)
        self.confirm_raises = False       # the browser falls INSIDE the confirm click, after the save
        self.no_confirm_button = False    # a dialog with no confirm button to click
        self.confirm_unclear = False      # the click lands and saves, and the tool answers no JSON (round six)
        self.second_read_fails = False    # the guard's read just before the click comes back empty-handed
        self.openers = 0                  # how often the dashboard opener ran (round ten keeps a zone's address)
        self.redirected = False           # the zone's address now lands on the dashboard (re-created elsewhere)
        self.landed_at = None             # …or on this address instead (another zone id), with no rows
        self.unreadable = False           # every read of the editor answers no JSON (the MCP's own error)

    # the transport
    def state(self, origin):
        return {"authenticated": True}

    def open(self, url):
        if self.crash_after_confirm and "confirm" in self.clicks:
            raise bs.SessionError("the browser MCP restarted", state="browser_unavailable")
        if "/zone/" in url:               # a fresh load: the form is what the server holds
            self.form, self.fresh, self.dialog = [dict(r) for r in self.saved], [], None
        return {"url": url}

    def call(self, tool, args=None):
        args = args or {}
        if tool == "browser_tabs":
            return {"text": "- 0: (current) [zone]"}
        if tool == "browser_wait_for":
            return {}
        assert tool == "browser_evaluate", tool
        src = args["function"]
        if "zone-edit" in src:                                   # _JS_OPEN_ZONE
            self.openers += 1
            if self.others_selected:
                return {"text": json.dumps({"found": True, "zone": False,
                                            "others_selected": self.others_selected})}
            self.form, self.fresh = [dict(r) for r in self.saved], []
            return {"text": json.dumps({"found": True, "zone": True})}
        if "fetch(location.href" in src:                         # _JS_SERVER_ZONE: the server, now
            self.fetches += 1
            if self.meanwhile and self.fetches == 2:
                self.saved.append(dict(self.meanwhile))
                self.meanwhile = None
            if not self.served or (self.second_read_fails and self.fetches == 2):
                return {"text": json.dumps({"unavailable": "the served page has no record rows"})}
            rows = [{"id": str(i), **r} for i, r in enumerate(self.saved)]
            if self.served_differs and rows:
                rows[0] = {**rows[0], "type": "A" if rows[0]["type"] != "A" else "CNAME"}   # no `selected`
            return {"text": json.dumps({"rows": rows})}
        if "row_count" in src:                                   # _JS_ZONE: named rows only
            if self.redirected:
                return {"text": json.dumps({"rows": [], "url": portal.SCRIPTS["internic"]["origin"] + "/dashboard/main"})}
            if self.landed_at:
                return {"text": json.dumps({"rows": [], "url": self.landed_at})}
            if self.unreadable:
                return {"text": "Error: Execution context was destroyed"}
            if not self.readable and self.clicks and self.clicks[-1] == "confirm":
                return {"text": json.dumps({"rows": [], "url": portal.SCRIPTS["internic"]["origin"] + "/zone/112859"})}
            rows = [{"id": str(i), **r} for i, r in enumerate(self.form)]
            return {"text": json.dumps({"rows": rows, "url": portal.SCRIPTS["internic"]["origin"] + "/zone/112859",
                                        "zone_id": "112859", "row_count": len(rows) + 3})}
        if "הוסף רשומה ריקה" in src:
            self.clicks.append("add")
            self.fresh.append({"name": "", "type": "", "content": "", "ttl": ""})
            return {"text": json.dumps({"found": True})}
        if "fresh.length" in src:                                # _JS_FILL_NEW
            spec = spec_of(src)
            empty = [r for r in self.fresh if not r["name"]]
            if len(empty) != 1:
                return {"text": json.dumps({"ok": False, "fresh": len(empty)})}
            if spec["type"] not in ("A", "AAAA", "CNAME", "TXT", "MX"):
                return {"text": json.dumps({"ok": False, "type": False})}
            empty[0].update(name=spec["name"], ttl=spec["ttl"], type=spec["type"], marked=True)
            return {"text": json.dumps({"ok": True})}
        if "value_cell" in src:                                  # _JS_FILL_VALUE
            row = next((r for r in self.fresh if r.get("marked")), None)
            if not row:
                return {"text": json.dumps({"ok": False, "row": False})}
            row["content"] = spec_of(src)["value"]
            row.pop("marked")
            return {"text": json.dumps({"ok": True, "row": {"name": row["name"], "ttl": row["ttl"],
                                                            "type": row["type"], "value": row["content"]}})}
        if "שמור שינויים" in src:
            self.clicks.append("save")
            self.dialog = {"open": True, "title": "האם לשמור את השינויים?",
                           "text": f"{len(self.form) + len(self.fresh)} רשומות"}
            return {"text": json.dumps({"found": True})}
        if "swal2-title" in src:                                 # _JS_DIALOG
            return {"text": json.dumps(self.dialog or {"open": False, "title": "", "text": ""})}
        if "swal2-confirm" in src:                               # _JS_ANSWER
            confirm = spec_of(src)["confirm"]
            if confirm and self.no_confirm_button:
                return {"text": json.dumps({"found": False})}
            self.clicks.append("confirm" if confirm else "cancel")
            if confirm and self.confirm_raises:
                self.saved = [dict(r) for r in self.form] + [
                    {k: v for k, v in r.items() if k != "marked"} for r in self.fresh]
                raise bs.SessionError("the browser MCP timed out", state="timeout")
            if confirm and self.confirm_unclear:
                self.saved = [dict(r) for r in self.form] + [
                    {k: v for k, v in r.items() if k != "marked"} for r in self.fresh]
                self.dialog = None
                return {"text": "Error: Target page, context or browser has been closed"}
            if confirm and self.saves:
                # the WHOLE form is written: whatever the server got meanwhile is gone, as on the panel
                self.saved = [dict(r) for r in self.form] + [
                    {k: v for k, v in r.items() if k != "marked"} for r in self.fresh]
                if self.kept_ttl:
                    self.saved[-1]["ttl"] = self.kept_ttl
            self.dialog = None
            return {"text": json.dumps({"found": True})}
        raise AssertionError(f"unexpected script: {src[:80]}")


class InternicWriteTests(unittest.TestCase):
    def setUp(self):
        self.panel = Panel(ZONE)
        original = portal.session_for
        portal.session_for = lambda p, endpoint=None: self.panel
        self.addCleanup(setattr, portal, "session_for", original)
        # never the office's own file: run in the container, these read the live one (the third reader)
        import tempfile
        original_file = portal.VERIFIED_FILE
        portal.VERIFIED_FILE = portal.Path(tempfile.mkdtemp(prefix="domains-write-")) / "portal-verified.json"
        self.addCleanup(setattr, portal, "VERIFIED_FILE", original_file)

    def write(self, allow=True, **record):
        params = {"domain": DOMAIN, "type": "A", "name": "fpg", "value": "93.184.216.10", **record}
        return portal.run_write("internic", "create", params, None, allow)

    def test_a_record_lands_in_a_new_row_and_every_other_record_is_untouched(self):
        res = self.write()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["record"]["name"], "fpg.digital-office.co.il.")
        self.assertEqual(self.panel.saved[:3], ZONE, "an existing record changed")
        self.assertEqual(self.panel.saved[3]["name"], "fpg.digital-office.co.il.")
        self.assertEqual((res["records_before"], res["records_after"]), (3, 4))

    def test_a_dialog_that_counts_anything_else_is_cancelled_and_nothing_is_written(self):
        self.panel.fresh.append({"name": "left-over.digital-office.co.il.", "type": "A",
                                 "content": "1.1.1.1", "ttl": "3600"})   # an unsaved row from before
        original = portal._read_zone_in_tab
        portal._read_zone_in_tab = lambda sess, s, d: {"ok": True, "records": [dict(r) for r in ZONE],
                                                      "zone_id": "112859"}
        self.addCleanup(setattr, portal, "_read_zone_in_tab", original)
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "assert_failed")
        self.assertIn("cancel", self.panel.clicks)
        self.assertEqual(self.panel.saved, ZONE)

    def test_a_save_the_server_did_not_keep_is_a_failure_not_a_success(self):
        self.panel.saves = False
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "assert_failed")

    def test_a_record_already_there_writes_nothing(self):
        res = self.write(name="mail", value="93.184.216.5")
        self.assertTrue(res["ok"] and res.get("unchanged"), res)
        self.assertNotIn("add", self.panel.clicks)

    def test_a_draft_portal_writes_nothing_without_the_owners_consent(self):
        res = self.write(allow=False)
        self.assertEqual(res["state"], "needs_verification")
        self.assertEqual(self.panel.clicks, [])

    def test_update_and_delete_are_refused_by_name_never_reported_done(self):
        for action in ("update", "delete"):
            res = portal.run_write("internic", action, {"domain": DOMAIN, "type": "A", "name": "fpg",
                                                       "value": "93.184.216.10"}, None, True)
            self.assertEqual(res["state"], "not_scripted", (action, res))
        self.assertEqual(self.panel.clicks, [])
        self.assertEqual(portal.write_state("internic")["actions"],
                         {"create": True, "update": False, "delete": False})

    def test_a_name_is_written_as_the_panel_writes_it(self):
        self.assertEqual(portal.fqdn("fpg", DOMAIN), "fpg.digital-office.co.il.")
        self.assertEqual(portal.fqdn("*.fpg", DOMAIN), "*.fpg.digital-office.co.il.")
        self.assertEqual(portal.fqdn("@", DOMAIN), "digital-office.co.il.")
        self.assertEqual(portal.fqdn("", DOMAIN), "digital-office.co.il.")
        self.assertEqual(portal.fqdn("FPG.digital-office.co.il.", DOMAIN), "fpg.digital-office.co.il.")
        self.assertEqual(portal.fqdn("digital-office.co.il", DOMAIN), "digital-office.co.il.")

    def test_a_type_the_writer_does_not_fill_completely_is_refused_by_name(self):
        """The second reader of DGO-1032: MX's priority and SRV's sub-rows were never filled, yet reported
        done. Until each is measured, they are refused before anything is touched."""
        for rtype in ("MX", "SRV", "CAA", "NS"):
            res = self.write(type=rtype, value="mail.example.com")
            self.assertEqual(res["state"], "not_scripted", (rtype, res))
        self.assertEqual(self.panel.clicks, [])

    def test_a_target_is_written_fully_qualified_and_a_retry_writes_nothing(self):
        """The panel stores a CNAME target with its dot; compared verbatim, the write never read back as
        itself and every retry added another row (the second reader)."""
        res = self.write(type="CNAME", name="app", value="digital-office.co.il")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.panel.saved[-1]["content"], "digital-office.co.il.")
        again = self.write(type="CNAME", name="app.digital-office.co.il", value="Digital-Office.co.il.")
        self.assertTrue(again.get("unchanged"), again)
        self.assertEqual(sum(1 for r in self.panel.saved if r["type"] == "CNAME" and
                             r["name"].startswith("app.")), 1, "a retry wrote the record again")

    def test_a_name_the_panel_shows_short_is_the_same_record(self):
        self.panel.saved.append({"name": "tfg", "type": "A", "content": "93.184.216.10", "ttl": "3600"})
        res = self.write(name="tfg.digital-office.co.il.", value="93.184.216.10")
        self.assertTrue(res.get("unchanged"), res)
        self.assertNotIn("add", self.panel.clicks)

    def test_a_txt_value_is_compared_as_it_reads(self):
        self.panel.saved.append({"name": "digital-office.co.il.", "type": "TXT",
                                 "content": '"v=spf1 " "a -all"', "ttl": "3600"})
        res = self.write(type="TXT", name="@", value="v=spf1 a -all")
        self.assertTrue(res.get("unchanged"), res)

    def test_a_cancelled_save_says_what_the_server_holds(self):
        """The cancel path claimed "nothing was written" without looking (the second reader)."""
        original = portal._read_zone_in_tab
        portal._read_zone_in_tab = lambda sess, s, d: {"ok": True, "records": [dict(r) for r in ZONE],
                                                      "zone_id": "112859"}
        self.addCleanup(setattr, portal, "_read_zone_in_tab", original)
        self.panel.fresh.append({"name": "left-over.digital-office.co.il.", "type": "A",
                                 "content": "1.1.1.1", "ttl": "3600"})
        res = self.write()
        self.assertEqual(res["state"], "assert_failed")
        self.assertIn("אינה באזור בשרת", res["error"])

    # ── the second reader of round two (DGO-1032 round three) ────────────────────────────────────────
    def test_a_record_saved_on_the_server_meanwhile_stops_the_save(self):
        """The save writes the WHOLE form: a record added on the server while the row was filled was
        undone, and the read-back still said success."""
        self.panel.meanwhile = {"name": "new.digital-office.co.il.", "type": "A", "content": "9.9.9.9",
                                "ttl": "3600"}
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "conflict")
        self.assertNotIn("save", self.panel.clicks)
        self.assertIn({"name": "new.digital-office.co.il.", "type": "A", "content": "9.9.9.9", "ttl": "3600"},
                      self.panel.saved, "the change made meanwhile was undone")

    def test_a_guard_that_cannot_run_saves_nothing(self):
        """The third reader: a page that serves no rows (a login page, a challenge, a script-drawn editor)
        saved anyway, was reported a success and marked the action watched. No read, no save."""
        self.panel.served = False
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "guard_unavailable")
        self.assertNotIn("save", self.panel.clicks)
        self.panel.served = True
        self.assertEqual(self.write(name="www3")["guard"], "checked")

    def test_a_guard_whose_read_came_back_empty_handed_saves_nothing(self):
        """An error answer (`{}`) read as "checked" — no comparison, and the save went ahead."""
        original = portal._js
        portal._js = lambda sess, fn, spec=None: {} if fn is portal._JS_SERVER_ZONE else original(sess, fn, spec)
        self.addCleanup(setattr, portal, "_js", original)
        res = self.write()
        self.assertEqual(res["state"], "guard_unavailable")
        self.assertNotIn("save", self.panel.clicks)

    def test_the_ttl_reported_is_the_one_the_server_kept(self):
        self.panel.kept_ttl = "86400"
        res = self.write(ttl=300)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["record"]["ttl"], res["ttl_asked"]), ("86400", "300"))
        self.assertIn("86400", res["note"])

    def test_an_address_is_compared_as_an_address(self):
        self.panel.saved.append({"name": "v6.digital-office.co.il.", "type": "AAAA",
                                 "content": "2001:db8::1", "ttl": "3600"})
        res = self.write(type="AAAA", name="v6", value="2001:DB8:0:0:0:0:0:1")
        self.assertTrue(res.get("unchanged"), res)
        self.assertNotIn("add", self.panel.clicks)

    def test_a_name_ending_in_a_dot_is_whole_and_one_outside_the_zone_is_refused(self):
        self.assertEqual(portal.fqdn("fpg.example.com.", DOMAIN), "fpg.example.com.")
        res = self.write(name="fpg.example.com.")
        self.assertEqual(res["state"], "invalid")
        self.assertEqual(self.panel.clicks, [])

    def test_a_txt_value_is_written_as_one_quoted_string_and_a_long_one_is_refused(self):
        res = self.write(type="TXT", name="@", value="v=spf1 a -all")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.panel.saved[-1]["content"], '"v=spf1 a -all"')
        long = self.write(type="TXT", name="dkim", value="k" * 256)
        self.assertEqual(long["state"], "not_scripted")

    def test_a_cname_is_never_written_beside_other_records_nor_another_beside_a_cname(self):
        res = self.write(type="CNAME", name="mail", value="elsewhere.example.com")
        self.assertEqual(res["state"], "conflict")
        res = self.write(type="A", name="www", value="93.184.216.7")
        self.assertEqual(res["state"], "conflict")
        self.assertEqual(self.panel.clicks, [])

    def test_a_zone_that_cannot_be_read_back_is_unknown_never_missing(self):
        self.panel.readable = False
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "unverified")
        self.assertTrue(res["saved"])


class RoundFourTests(InternicWriteTests.__bases__[0]):
    """The third reader of DGO-1032 (round three's code)."""
    def setUp(self):
        InternicWriteTests.setUp(self)

    write = InternicWriteTests.write

    def test_another_domain_selected_on_the_dashboard_opens_nothing(self):
        """Unticking "every other ticked box" would click any switch a row carries — on every read."""
        self.panel.others_selected = 1
        res = self.write()
        self.assertEqual(res["state"], "conflict")
        self.assertEqual(self.panel.clicks, [])

    def test_a_browser_that_falls_after_the_confirm_keeps_the_evidence(self):
        self.panel.crash_after_confirm = True
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertEqual((res["state"], res["saved"]), ("unverified", True))
        self.assertIn("fpg.digital-office.co.il.", res["detail"])

    def test_a_cname_never_sits_at_the_apex(self):
        """…even when the read shows no apex row: its SOA and NS are never rows (the third reader)."""
        self.panel.saved = [r for r in self.panel.saved if r["name"] != "digital-office.co.il."]
        res = self.write(type="CNAME", name="@", value="elsewhere.example.com")
        self.assertEqual(res["state"], "conflict")
        self.assertEqual(self.panel.clicks, [])

    def test_a_priority_changed_meanwhile_stops_the_save(self):
        self.panel.saved.append({"name": "digital-office.co.il.", "type": "MX", "content": "mail.digital-office.co.il.",
                                 "ttl": "3600", "priority": "10"})
        self.panel.meanwhile = None
        original = self.panel.call

        def call(tool, args=None):
            if tool == "browser_evaluate" and "fetch(location.href" in (args or {}).get("function", "") \
                    and self.panel.fetches == 1:                  # between the guard's two reads
                self.panel.saved[-1]["priority"] = "20"          # someone changes it on the server
            return original(tool, args)
        self.panel.call = call
        res = self.write()
        self.assertEqual(res["state"], "conflict")
        self.assertNotIn("save", self.panel.clicks)

    def test_a_txt_is_measured_in_octets(self):
        res = self.write(type="TXT", name="he", value="א" * 200)       # 200 letters, 400 octets
        self.assertEqual(res["state"], "not_scripted")

    def test_a_ttl_of_zero_is_written_as_zero(self):
        res = self.write(ttl=0)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.panel.saved[-1]["ttl"], "0")

    def test_an_unchanged_record_reports_the_zones_ttl(self):
        res = self.write(name="mail", value="93.184.216.5", ttl=300)
        self.assertTrue(res.get("unchanged"), res)
        self.assertEqual(res["record"]["ttl"], "86400")

    def test_a_value_the_type_cannot_hold_is_refused_before_anything(self):
        for rtype, value in (("A", "not-an-address"), ("A", "2001:db8::1"), ("AAAA", "93.184.216.7"),
                             ("CNAME", "two words")):
            self.assertEqual(self.write(type=rtype, value=value)["state"], "invalid", (rtype, value))
        self.assertEqual(self.panel.clicks, [])

    def test_an_editor_of_another_domain_is_refused(self):
        self.panel.saved = [{"name": "office.co.il.", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        res = self.write()
        self.assertEqual(res["state"], "conflict")
        self.assertNotIn("add", self.panel.clicks)


class RoundFiveTests(InternicWriteTests.__bases__[0]):
    """The fourth reader of DGO-1032 (round four's code)."""
    def setUp(self):
        InternicWriteTests.setUp(self)

    write = InternicWriteTests.write

    def test_a_browser_that_falls_inside_the_confirm_click_keeps_the_evidence(self):
        """The click landed, the panel saved, and THAT call raised: the result had no `saved`, and the
        history no trace, while the record was on the server."""
        self.panel.confirm_raises = True
        res = self.write()
        self.assertEqual((res["state"], res.get("saved")), ("unverified", True), res)

    def test_a_confirm_that_found_no_button_confirms_nothing(self):
        self.panel.no_confirm_button = True
        res = self.write()
        self.assertFalse(res["ok"])
        self.assertIn("cancel", self.panel.clicks)
        self.assertFalse(res.get("saved"), "a save nobody confirmed was reported as made")
        self.assertEqual(self.panel.saved, ZONE)

    def test_a_page_that_serves_other_rows_than_it_shows_refuses_before_touching_anything(self):
        """Fields the page's own script fills are not in the served HTML: compared with the live form
        just before the click, every save said "the zone changed" — false, and no retry helped."""
        self.panel.served_differs = True
        res = self.write()
        self.assertEqual(res["state"], "guard_unavailable")
        self.assertNotIn("add", self.panel.clicks)

    def test_the_guard_compares_the_server_with_itself(self):
        """The two served reads — as the editor loads, and just before the click — are compared with
        each other, by the same parser: a change on the server between them is caught."""
        self.panel.meanwhile = {"name": "late.digital-office.co.il.", "type": "A", "content": "9.9.9.9",
                                "ttl": "3600"}
        res = self.write()
        self.assertEqual(res["state"], "conflict")
        self.assertEqual(self.panel.fetches, 2)

    # ── the fifth reader (round five's code) ──────────────────────────────────────────────────────────
    def test_a_second_read_that_comes_back_empty_handed_saves_nothing(self):
        self.panel.second_read_fails = True
        res = self.write()
        self.assertEqual(res["state"], "guard_unavailable")
        self.assertNotIn("save", self.panel.clicks)

    def test_an_unclear_answer_to_the_confirm_click_is_read_back_as_a_save(self):
        """The tool's error answer (no JSON) was read as "no confirm button": a save that landed was
        cancelled-and-reported, and went unrecorded when it showed late."""
        self.panel.confirm_unclear = True
        res = self.write()
        self.assertTrue(res["ok"], res)
        self.assertNotIn("cancel", self.panel.clicks)


class RoundSevenTests(InternicWriteTests.__bases__[0]):
    """The sixth reader of DGO-1032 (round six's code)."""
    def setUp(self):
        InternicWriteTests.setUp(self)

    write = InternicWriteTests.write

    def test_a_read_of_another_domains_editor_shows_nothing_under_this_name(self):
        """The write refused a foreign editor, the read did not: a zone the opener got wrong was shown as
        this domain's records — and the read runs unattended on every sync."""
        self.panel.saved = [{"name": "office.co.il.", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        res = portal.read_zone("internic", DOMAIN)
        self.assertEqual(res["state"], "conflict", res)
        self.assertNotIn("records", res)

    def test_a_name_dns_cannot_hold_is_refused_before_anything(self):
        for name in ("a b", "a..b", "-a", "a-", "x" * 64, "a.*", "שם"):
            self.assertEqual(self.write(name=name)["state"], "invalid", name)
        self.assertEqual(self.panel.clicks, [])
        for name in ("@", "*", "*.fpg", "_dmarc", "fpg.digital-office.co.il."):
            self.assertNotEqual(self.write(name=name, value="9.9.9.9")["state"], "invalid", name)

    def test_a_full_name_longer_than_dns_allows_is_refused(self):
        """The seventh reader: the length was the name's as given — 249 characters became a 270-character
        full name, and the panel's save writes the whole zone."""
        long = ".".join(["a" * 61] * 4)                        # 247 characters, each label legal
        self.assertEqual(self.write(name=long)["state"], "invalid")
        self.assertEqual(self.panel.clicks, [])

    def test_a_record_not_found_after_the_confirm_click_does_not_say_it_was_saved(self):
        """The click may never have landed (the dialog still open, or closed with nothing saved): "not in
        the zone after the save" told the history of a save that may not have happened."""
        self.panel.saves = False
        res = self.write()
        self.assertEqual(res["state"], "assert_failed")
        self.assertIn("ייתכן שהשמירה לא התבצעה", res["error"])


class RoundTenTests(InternicWriteTests.__bases__[0]):
    """The ninth reader of DGO-1032 (round nine's code): an unattended click on a dashboard no one can
    measure is a guess — so a zone that proved itself is read from its address from then on."""
    def setUp(self):
        InternicWriteTests.setUp(self)

    @staticmethod
    def kept():
        """InterNIC's own memory (round eleven keys it by portal)."""
        return portal._zones().get(portal.SCRIPTS["internic"]["origin"], {})

    def test_a_zone_that_proved_itself_is_read_from_its_address_after(self):
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.panel.openers, 1, "the dashboard was clicked again")
        self.assertEqual(self.kept(), {DOMAIN: "112859"})

    def test_a_kept_address_that_no_longer_proves_itself_is_forgotten(self):
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        saved = self.panel.saved
        self.panel.saved = [{"name": "office.co.il.", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        res = portal.read_zone("internic", DOMAIN)
        self.assertEqual(res["state"], "conflict")
        self.assertNotIn("records", res)
        self.assertEqual(self.kept(), {})
        self.panel.saved = saved
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.panel.openers, 2, "found again from the dashboard")

    def test_a_zone_that_proves_nothing_is_not_kept(self):
        """Short names only: nothing says whose zone it is — never kept."""
        self.panel.saved = [{"name": "www", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        portal.read_zone("internic", DOMAIN)
        self.assertEqual(self.kept(), {})

    # ── the tenth reader (round ten's code) ───────────────────────────────────────────────────────────
    def test_a_child_zone_never_proves_itself_the_parents(self):
        """Z1: every name under shop.<domain>. — inside the domain, and not its zone."""
        self.panel.saved = [{"name": "shop.digital-office.co.il.", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        portal.read_zone("internic", DOMAIN)
        self.assertNotIn("112859", json.dumps(portal._zones()), "kept, in whatever shape")

    def test_a_slow_load_keeps_the_address(self):
        """Z3: one load with no rows forgot the kept address, and sent reads back to the dashboard's clicks."""
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        saved, self.panel.saved = self.panel.saved, []
        self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.kept(), {DOMAIN: "112859"})
        self.panel.saved = saved
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.panel.openers, 1)

    def test_the_memory_is_each_portals_own(self):
        """Z2: another portal's door opened `<its origin>/zone/<InterNIC's id>` and forgot InterNIC's."""
        portal._keep_zone("https://other.example", DOMAIN, "7")
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(portal._zones().get("https://other.example"), {DOMAIN: "7"})
        self.assertEqual(self.kept(), {DOMAIN: "112859"})
        self.assertEqual(self.panel.openers, 1, "another portal's id was used for InterNIC")

    def test_a_kept_id_is_ascii_digits(self):
        portal._keep_zone(portal.SCRIPTS["internic"]["origin"], DOMAIN, "١٢")
        self.assertEqual(self.kept(), {})

    # ── the eleventh reader (round eleven's code) ─────────────────────────────────────────────────────
    def test_a_kept_address_that_lands_elsewhere_is_forgotten(self):
        """K1: the zone re-created under another id — its address landed on the dashboard with no rows, the
        memory stayed, and every read and write of the domain failed for good."""
        portal._keep_zone("https://other.example", DOMAIN, "7")
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.panel.redirected = True
        self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.kept(), {}, "the dead address was kept")
        self.assertEqual(portal._zones().get("https://other.example"), {DOMAIN: "7"}, "another portal's went too")
        self.panel.redirected = False
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.panel.openers, 2, "found again from the dashboard")

    def test_the_apex_proves_the_zone_with_or_without_its_dot_and_at_never(self):
        """K4: an apex shown without its trailing dot proved nothing, and the dashboard was clicked on every
        read. `@` names no domain: it proves nothing."""
        self.panel.saved = [{"name": "digital-office.co.il", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        portal.read_zone("internic", DOMAIN)
        self.assertEqual(self.kept(), {DOMAIN: "112859"})
        portal._keep_zone(portal.SCRIPTS["internic"]["origin"], DOMAIN, None)
        self.panel.saved = [{"name": "@", "type": "A", "content": "1.1.1.1", "ttl": "3600"}]
        portal.read_zone("internic", DOMAIN)
        self.assertEqual(self.kept(), {})

    # ── the twelfth reader (round twelve's code) ───────────────────────────────────────────────────────
    def test_an_unreadable_editor_is_no_evidence_against_the_kept_address(self):
        """Z1: every read of the editor answered no JSON — no address at all read as "not the zone's", and a
        good address was forgotten."""
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.panel.unreadable = True
        self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.kept(), {DOMAIN: "112859"})

    def test_another_zone_ids_page_is_not_the_kept_one(self):
        """Z5: `/zone/1128590` holds `/zone/112859` as a substring — the dead address was kept."""
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        self.panel.landed_at = portal.SCRIPTS["internic"]["origin"] + "/zone/1128590"
        self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
        self.assertEqual(self.kept(), {})

    def test_a_page_that_is_no_panel_page_is_no_evidence(self):
        """The reader of 42f2fa71: an error page, about:blank, or a sign-in the session ran out into forgot a
        good address."""
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        origin = portal.SCRIPTS["internic"]["origin"]
        for landed in ("chrome-error://chromewebdata/", "about:blank", origin + "/login",
                       origin + "/login?next=%2Fzone%2F112859"):
            self.panel.landed_at = landed
            self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
            self.assertEqual(self.kept(), {DOMAIN: "112859"}, landed)

    # ── the reader of 8c03fbcd ─────────────────────────────────────────────────────────────────────────
    def test_only_the_panels_own_host_is_the_panel(self):
        """A name that merely STARTS with the panel's origin is another host: it forgot a good address."""
        self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
        origin = portal.SCRIPTS["internic"]["origin"]
        for landed in (origin + ".evil.example/dashboard", origin + "x/dashboard"):
            self.panel.landed_at = landed
            self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
            self.assertEqual(self.kept(), {DOMAIN: "112859"}, landed)

    def test_a_sign_in_or_a_zone_is_the_pages_path_not_its_query(self):
        """`/login` or `/zone/<kept id>` only in a panel page's query kept a dead address."""
        origin = portal.SCRIPTS["internic"]["origin"]
        for landed in (origin + "/dashboard?from=/login", origin + "/dashboard?return=/zone/112859"):
            self.panel.landed_at = None
            self.assertTrue(portal.read_zone("internic", DOMAIN)["ok"])
            self.assertEqual(self.kept(), {DOMAIN: "112859"})
            self.panel.landed_at = landed
            self.assertFalse(portal.read_zone("internic", DOMAIN)["ok"])
            self.assertEqual(self.kept(), {}, landed)

    def test_the_memory_key_is_the_domain_as_dns_writes_it(self):
        portal._keep_zone(portal.SCRIPTS["internic"]["origin"], "Digital-Office.co.il.", "112859")
        self.assertEqual(self.kept(), {DOMAIN: "112859"})

    def test_a_refusal_says_what_the_header_over_the_box_said(self):
        original = self.panel.call

        def refusing(tool, args=None):
            if tool == "browser_evaluate" and "zone-edit" in (args or {}).get("function", ""):
                return {"text": json.dumps({"found": True, "zone": False, "no_selection": True,
                                            "header": ["Auto"], "box": "sel"})}
            return original(tool, args)
        self.panel.call = refusing
        res = portal.read_zone("internic", DOMAIN)
        self.assertEqual(res["state"], "conflict")
        self.assertIn("Auto", res["detail"])


class WatchedOnceTests(unittest.TestCase):
    """The consent is one-time per action: a watched success makes the action the office's, and the
    screens say so (the second reader: nothing ever marked a portal verified, so every write needed the
    flag for ever, and DRAFT_WHY's promise was untrue)."""
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="domains-verified-")
        original = portal.VERIFIED_FILE
        portal.VERIFIED_FILE = portal.Path(self.dir) / "portal-verified.json"
        self.addCleanup(setattr, portal, "VERIFIED_FILE", original)
        self.panel = Panel(ZONE)
        original_session = portal.session_for
        portal.session_for = lambda p, endpoint=None: self.panel
        self.addCleanup(setattr, portal, "session_for", original_session)

    def test_one_watched_create_makes_create_the_offices(self):
        state = portal.write_state("internic")
        self.assertFalse(state["enabled"])
        self.assertEqual(state["watched"]["create"], False)
        self.assertEqual(portal.run_write("internic", "create", {"domain": DOMAIN, "type": "A", "name": "a1",
                                                                 "value": "1.1.1.1"})["state"], "needs_verification")
        portal.mark_verified("internic", "create", "owner@office", {"name": "a1"})
        state = portal.write_state("internic")
        self.assertTrue(state["enabled"], state)
        self.assertTrue(state["watched"]["create"])
        self.assertIn("עריכת רשומה", state["missing"])
        res = portal.run_write("internic", "create", {"domain": DOMAIN, "type": "A", "name": "a2",
                                                      "value": "93.184.216.12"})
        self.assertTrue(res["ok"], res)
        kept = json.loads(portal.VERIFIED_FILE.read_text(encoding="utf-8"))["internic"]["create"]
        self.assertEqual(kept["by"], "owner@office")

    def test_watching_create_never_unlocks_another_action(self):
        portal.mark_verified("internic", "create", "owner@office", {})
        self.assertFalse(portal.verified("internic", "delete"))
        self.assertFalse(portal.verified("other-portal", "create"))

    def test_a_mark_of_another_writer_version_is_no_mark(self):
        portal.mark_verified("internic", "create", "owner@office", {})
        data = json.loads(portal.VERIFIED_FILE.read_text(encoding="utf-8"))
        data["internic"]["create"]["version"] = "an older writer"
        portal.VERIFIED_FILE.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(portal.verified("internic", "create"))

    def test_a_file_of_another_shape_is_no_mark_and_breaks_nothing(self):
        for shape in ('[1, 2]', '{"internic": []}', '{"internic": {"create": "yes"}}'):
            portal.VERIFIED_FILE.write_text(shape, encoding="utf-8")
            self.assertFalse(portal.verified("internic", "create"), shape)
            self.assertIn("watched", portal.write_state("internic"))
            portal.mark_verified("internic", "create", "owner@office", {})
            self.assertTrue(portal.verified("internic", "create"), shape)

    def test_the_draft_texts_name_no_checkbox_that_is_not_there(self):
        self.assertNotIn("תיבת הסימון", portal.DRAFT_HOW)
        self.assertEqual(portal.write_state("internic")["types"], ["A", "AAAA", "CNAME", "TXT"])


if __name__ == "__main__":
    unittest.main()
