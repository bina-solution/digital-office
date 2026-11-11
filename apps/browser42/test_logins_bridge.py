"""browser42 logins — one login per origin in Chrome, and the declared row wins (DGO-1488).

    python3 apps/browser42/test_logins_bridge.py

Held here, against a throwaway `Login Data` with Chrome's own columns and fake plane answers:
  - chrome_put replaces Chrome's OWN saved row for the origin (filed under the slashed realm, with the
    login page as origin_url), not only the bridge's — before, the two sat side by side;
  - chrome_delete removes both shapes of the realm;
  - plane_entries lets a row an app declares win over a harvested `browser-login-*` row for the same
    origin, in either listing order.
"""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("browser42_logins_bridge", Path(__file__).with_name("logins.py"))
logins = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logins)

SCHEMA = ("create table logins (origin_url text, action_url text, username_element text, username_value text,"
          " password_element text, password_value blob, submit_element text, signon_realm text,"
          " date_created integer, blacklisted_by_user integer, scheme integer, password_type integer,"
          " times_used integer, date_last_used integer, date_password_modified integer)")
ORIGIN = "https://portal.internic.co.il"


class ChromeRows(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="b42-logins-"), "Login Data")
        con = sqlite3.connect(self.db)
        con.execute(SCHEMA)
        # rows Chrome saved itself when a person signed in by hand: the account the plane now holds, another
        # account for the same site (exists nowhere else), and a «never save» choice
        for user, black in (("old@example.test", 0), ("personal@example.test", 0), ("", 1)):
            con.execute("insert into logins (origin_url, username_value, password_value, signon_realm,"
                        " blacklisted_by_user) values (?,?,?,?,?)",
                        (ORIGIN + "/user/login", user, b"v10old", ORIGIN + "/", black))
        con.commit()
        con.close()
        original = logins.LOGIN_DB
        logins.LOGIN_DB = self.db
        self.addCleanup(setattr, logins, "LOGIN_DB", original)
        original_ssl = logins._openssl
        logins._openssl = lambda args, blob: b"enc"
        self.addCleanup(setattr, logins, "_openssl", original_ssl)

    def rows(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("select origin_url, username_value, signon_realm from logins").fetchall()
        finally:
            con.close()

    def users(self):
        return sorted(r[1] for r in self.rows())

    def test_put_replaces_the_same_account_and_the_shadowed_one_and_nothing_else(self):
        logins.chrome_put(ORIGIN, "owner@example.test", "pw", ("old@example.test",))
        self.assertEqual(self.users(), ["", "owner@example.test", "personal@example.test"])

    def test_put_of_the_account_chrome_saved_replaces_it_once(self):
        logins.chrome_put(ORIGIN, "old@example.test", "pw")
        self.assertEqual(self.users(), ["", "old@example.test", "personal@example.test"])
        logins.chrome_put(ORIGIN, "old@example.test", "pw2")
        self.assertEqual(self.users(), ["", "old@example.test", "personal@example.test"])

    def test_delete_takes_the_exact_row_the_cleanup_names(self):
        """The `:8080` cleanup hands chrome_delete an origin_url as Chrome stored it, path and all."""
        con = sqlite3.connect(self.db)
        con.execute("insert into logins (origin_url, username_value, signon_realm, blacklisted_by_user)"
                    " values (?,?,?,0)", ("http://n8n.localhost:8080/signin", "a", "http://n8n.localhost:8080/"))
        con.commit()
        con.close()
        logins.chrome_delete("http://n8n.localhost:8080/signin")
        self.assertNotIn("http://n8n.localhost:8080/signin", [r[0] for r in self.rows()])
        self.assertEqual(self.users(), ["", "old@example.test", "personal@example.test"])


class DeclaredWins(unittest.TestCase):
    def plane(self, order):
        rows = {"domain-internic-login": {"app": {"url": ORIGIN}, "fields": [
                    {"key": "DOMAIN_INTERNIC_USER", "secret": False, "clear": "owner@example.test"},
                    {"key": "DOMAIN_INTERNIC_PASSWORD", "secret": True}]},
                "browser-login-portal-internic-co-il": {"app": {}, "fields": [
                    {"key": "BROWSER_LOGIN_PORTAL_INTERNIC_CO_IL_URL", "secret": False, "clear": ORIGIN + "/"},
                    {"key": "BROWSER_LOGIN_PORTAL_INTERNIC_CO_IL_USER", "secret": False, "clear": "old@example.test"},
                    {"key": "BROWSER_LOGIN_PORTAL_INTERNIC_CO_IL_PASSWORD", "secret": True}]}}
        values = {"domain-internic-login": "new-pw", "browser-login-portal-internic-co-il": "old-pw"}
        self.revealed = []

        def call(path, data=None):
            if path == "/api/connections":
                return {"connections": [{"id": cid} for cid in order]}
            if path.startswith("/api/cred/"):
                return rows[path.rsplit("/", 1)[1]]
            if path.startswith("/api/reveal/"):
                self.revealed.append(path.rsplit("/", 1)[1])
                return {"value": values[path.rsplit("/", 1)[1]]}
            raise AssertionError(path)
        original = logins._call
        logins._call = call
        self.addCleanup(setattr, logins, "_call", original)
        return logins.plane_entries()

    def test_the_declared_row_wins_in_either_order(self):
        for order in (["domain-internic-login", "browser-login-portal-internic-co-il"],
                      ["browser-login-portal-internic-co-il", "domain-internic-login"]):
            got = self.plane(order)
            self.assertEqual(len(got), 1, got.keys())
            entry = next(iter(got.values()))
            self.assertEqual(entry["cid"], "domain-internic-login", order)
            self.assertEqual(entry["username"], "owner@example.test")
            self.assertEqual(entry.get("shadowed"), ["old@example.test"], order)
        # declared first: the harvested row's password is never revealed for nothing
        self.plane(["domain-internic-login", "browser-login-portal-internic-co-il"])
        self.assertEqual(self.revealed, ["domain-internic-login"])


class HarvestSkipsAnEmptyRow(unittest.TestCase):
    """DGO-1490: one Chrome row with an empty user name (the HP, 2026-11-08) ended the WHOLE harvest — the
    plane refused the empty value (/api/set → 400 «value required») and fail() exited. Now that row is
    skipped and said, and the others are harvested."""

    def test_an_empty_row_is_skipped_and_said_and_the_rest_are_harvested(self):
        rows = {"https://auth.example.test": {"username": "", "password": "pw1", "modified": 1},
                "https://nopw.example.test": {"username": "me", "password": "", "modified": 1},
                "https://good.example.test": {"username": "me@example.test", "password": "pw2", "modified": 1}}
        written, reports = [], []

        def call(path, data=None):
            # the plane as it answers: an empty value is refused, and a refusal ends the run (fail → exit 2)
            if data is not None and not str(data.get("value", "")).strip():
                logins.fail("credentials_refused", f"{path} -> 400 value required")
            written.append(path)
            return {}
        fakes = {"chrome_rows": lambda: rows, "plane_entries": lambda: {}, "_call": call,
                 "load_state": lambda: {"key": "ab" * 32, "entries": {}}, "save_state": lambda state: None,
                 "out": lambda **fields: reports.append(fields), "chrome_delete": lambda origin: None,
                 "plane_exists": lambda cid: False,
                 # its own state's place: the lock is taken beside it, never in the office's /data (the sixth reader)
                 "STATE_FILE": os.path.join(tempfile.mkdtemp(prefix="b42-harvest-"), "browser-logins.json")}
        for name, fake in fakes.items():
            self.addCleanup(setattr, logins, name, getattr(logins, name))
            setattr(logins, name, fake)
        self.addCleanup(logins._LOCKS.clear)
        logins.cmd_sync(materialize=False, harvest=True)
        report = reports[-1]
        self.assertEqual([c["origin"] for c in report["created"]], ["https://good.example.test"])
        self.assertEqual(report["skipped"], [{"origin": "https://auth.example.test", "reason": "no user name"},
                                             {"origin": "https://nopw.example.test", "reason": "no password"}])
        # nothing was written for a skipped row: one credential, its user name and its address
        self.assertEqual(written, ["/api/add", "/api/set/browser-login-good-example-test",
                                   "/api/set/browser-login-good-example-test"])


class HarvestNeverWritesOverACredential(unittest.TestCase):
    """The fourth reader: http and https of one host got one id, and /api/add — which has no check of its own —
    overwrote the https credential's password with the http one's."""

    def test_two_schemes_two_ids_and_an_existing_id_is_never_written_over(self):
        self.assertNotEqual(logins.custom_id("http://shop.test")[0], logins.custom_id("https://shop.test")[0])
        self.assertEqual(logins.custom_id("https://shop.test")[0], "browser-login-shop-test", "https keeps its id")
        self.assertNotEqual(logins.custom_id("https://shop.test:8443")[0], logins.custom_id("https://shop.test")[0])
        written = []
        self.addCleanup(setattr, logins, "_call", logins._call)
        self.addCleanup(setattr, logins, "plane_exists", logins.plane_exists)
        logins._call = lambda path, data=None: written.append(path) or {}
        logins.plane_exists = lambda cid: True
        with self.assertRaises(logins.PlaneIdTaken):
            logins.plane_create_custom("https://shop.test", "me", "pw")
        self.assertEqual(written, [], "nothing written")


class SyncOnARealLoginData(unittest.TestCase):
    """The issue «two of its promised directions never run»: cmd_sync over a REAL `Login Data`, with the real
    chrome_rows / chrome_put / chrome_delete_written and a real state file, run more than once — the first
    attempt's faked delete hid a no-op, and a second run is where a deleted credential came back.

    Faked: only the plane (a dict that answers like plane_entries and records every write) and the AES
    (identity, so `v10` + the password is the stored value)."""
    OTHER = "https://other.example.test"
    NEWER = 14_000_000_000_000_000                  # WebKit µs ≈ 2044: later than anything chrome_put writes today

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="b42-sync-")
        self.db = os.path.join(tmp, "Login Data")
        con = sqlite3.connect(self.db)
        con.execute(SCHEMA)
        # what Chrome saved itself: the account the plane will hold, his personal account, a «never save» row
        for user, black in (("owner@example.test", 0), ("personal@example.test", 0), ("", 1)):
            con.execute("insert into logins (origin_url, username_value, password_value, signon_realm,"
                        " blacklisted_by_user, date_password_modified) values (?,?,?,?,?,1)",
                        (ORIGIN + "/user/login", user, b"v10his-" + user.encode(), ORIGIN + "/", black))
        con.commit()
        con.close()
        self.plane = {}
        self.writes, self.reports, self.kept, self.kept_from = [], [], [], []
        self.addCleanup(logins._LOCKS.clear)              # each test is its own process as far as the lock goes

        def plane_write(cid, field, value):
            self.assertTrue(value, "the plane is never sent an empty value")
            self.writes.append((cid, field, value))
            for entry in self.plane.values():
                if entry["cid"] == cid and field is None:
                    entry["password"] = value

        def plane_create_custom(origin, username, password):
            cid = "browser-login-" + origin.split("://", 1)[-1].replace(".", "-")
            self.plane[origin] = {"cid": cid, "username": username, "password": password}
            return cid
        fakes = {"LOGIN_DB": self.db, "STATE_FILE": os.path.join(tmp, "browser-logins.json"),
                 "_openssl": lambda args, blob: blob, "plane_write": plane_write,
                 "plane_create_custom": plane_create_custom,
                 "plane_entries": lambda: {o: dict(e) for o, e in self.plane.items()},
                 # a password about to be replaced is kept in the plane first (Chrome's, or the plane's own)
                 "plane_keep_aside": lambda origin, user, pw, source="chrome": (
                     self.kept.append((origin, user, pw)), self.kept_from.append(source),
                     f"kept-{len(self.kept)}")[-1],
                 "plane_exists": lambda cid: False,
                 # CHANGED (the fifth reader): the deletion tests hold the TWO-listing rule; its minimum time between
                 # the two looks has a test of its own (test_two_looks_within_the_hour_delete_nothing)
                 "MISSING_MIN_SECONDS": 0,
                 "out": lambda **fields: self.reports.append(fields)}
        for name, fake in fakes.items():
            self.addCleanup(setattr, logins, name, getattr(logins, name))
            setattr(logins, name, fake)

    def declare(self, origin, username, password, cid=None):
        self.plane[origin] = {"cid": cid or "declared-" + origin.split("://", 1)[-1], "username": username,
                              "password": password}

    def sync(self, **verbs):
        logins.cmd_sync(**verbs)
        return self.reports[-1]

    def chrome(self, origin=ORIGIN):
        con = sqlite3.connect(self.db)
        try:
            return sorted((u, bytes(p or b"")[3:].decode()) for u, p in con.execute(
                "select username_value, password_value from logins where signon_realm in (?, ?)"
                " and blacklisted_by_user = 0", (origin, origin + "/")))
        finally:
            con.close()

    def chrome_types(self, user, password, origin_url=ORIGIN + "/"):
        """He changes a saved password in the browser: Chrome rewrites that row and dates it."""
        con = sqlite3.connect(self.db)
        con.execute("update logins set password_value = ?, date_password_modified = ? where origin_url = ?"
                    " and username_value = ?", (b"v10" + password.encode(), self.NEWER, origin_url, user))
        con.commit()
        con.close()

    def test_a_password_changed_in_chrome_reaches_the_plane(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.assertEqual(self.sync()["to_chrome"], [ORIGIN])
        self.chrome_types("owner@example.test", "pw2")
        report = self.sync()
        self.assertEqual(report["to_plane"], [ORIGIN])
        self.assertEqual(self.writes, [("declared-portal.internic.co.il", None, "pw2")])
        self.assertEqual(self.plane[ORIGIN]["password"], "pw2")
        report = self.sync()                                            # and then it is quiet
        self.assertEqual((report["to_plane"], report["to_chrome"], report["skipped"]), ([], [], []))

    def test_another_accounts_newer_row_or_an_empty_one_is_never_taken(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.chrome_types("personal@example.test", "personal-pw", ORIGIN + "/user/login")
        report = self.sync()
        self.assertEqual(report["to_plane"], [])
        # CHANGED (the bridge's second reader): the sync reads the owner's OWN row, unchanged, so there is nothing
        # to skip — before, another account's newer row made the credential look changed, and it was skipped
        self.assertEqual(report["skipped"], [])
        self.assertEqual(self.plane[ORIGIN]["password"], "pw1")
        self.assertIn(("owner@example.test", "pw1"), self.chrome())      # the owner's row is untouched
        self.chrome_types("owner@example.test", "")                       # a row that decrypts to ""
        con = sqlite3.connect(self.db)
        con.execute("update logins set date_password_modified = ? where username_value = ?",
                    (self.NEWER + 1, "owner@example.test"))
        con.commit()
        con.close()
        report = self.sync()                                            # no fail(), no write
        self.assertEqual((report["to_plane"], self.writes), ([], []))

    # ── the bridge's second reader: four ways a password was still lost, and a deletion that never came ──────────
    def insert(self, origin_url, user, password, realm=ORIGIN + "/", modified=1):
        con = sqlite3.connect(self.db)
        con.execute("insert into logins (origin_url, username_value, password_value, signon_realm,"
                    " blacklisted_by_user, date_password_modified) values (?,?,?,?,0,?)",
                    (origin_url, user, b"v10" + password.encode(), realm, modified))
        con.commit()
        con.close()

    def test_his_other_account_saved_from_the_home_page_is_never_deleted(self):
        self.insert(ORIGIN + "/", "home@example.test", "home-only-pw")   # a form on the home page: filed at origin/
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.assertIn(("home@example.test", "home-only-pw"), self.chrome())
        self.assertIn(("owner@example.test", "pw1"), self.chrome())

    def test_a_change_he_typed_survives_another_accounts_newer_row_and_a_later_plane_change(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.chrome_types("owner@example.test", "TYPED-IN-CHROME")
        self.chrome_types("personal@example.test", "personal-2", ORIGIN + "/user/login")   # now the newest row
        con = sqlite3.connect(self.db)
        con.execute("update logins set date_password_modified = ? where username_value = ?",
                    (self.NEWER + 5, "personal@example.test"))
        con.commit()
        con.close()
        report = self.sync()
        self.assertEqual(report["to_plane"], [ORIGIN], "the owner's own row moved: it is taken")
        self.assertEqual(self.plane[ORIGIN]["password"], "TYPED-IN-CHROME")
        self.plane[ORIGIN]["password"] = "pw-from-the-plane"              # then the plane moves
        self.sync()
        self.assertIn(("owner@example.test", "pw-from-the-plane"), self.chrome())
        self.assertIn(("personal@example.test", "personal-2"), self.chrome(), "his account is untouched")

    def test_a_shadowed_account_is_replaced_only_when_nothing_of_it_is_lost(self):
        # CHANGED (the third reader): a shadowed account whose Chrome and plane passwords differ is kept in both and
        # nothing is overwritten — the second reader's version wrote Chrome's over the plane's, which loses a password
        # he set in the plane's screen
        harvested = "browser-login-portal-internic-co-il"
        secrets_held = {harvested: "P1"}
        self.addCleanup(setattr, logins, "plane_secret", logins.plane_secret)
        logins.plane_secret = lambda cid: secrets_held.get(cid)
        self.chrome_types("personal@example.test", "P2-NEW", ORIGIN + "/user/login")    # the two now differ
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.plane[ORIGIN].update(shadowed=["personal@example.test"],
                                  shadowed_cid={"personal@example.test": harvested})
        report = self.sync()
        self.assertFalse([w for w in self.writes if w[0] == harvested], "nothing overwritten in the plane")
        self.assertIn(("personal@example.test", "P2-NEW"), self.chrome(), "nor in Chrome")
        self.assertTrue(any("differs" in s.get("reason", "") for s in report["skipped"] if isinstance(s, dict)))
        # the same password in both: nothing is lost, and the declared row replaces it (DGO-1488)
        secrets_held[harvested] = "P2-NEW"
        self.plane[ORIGIN]["password"] = "pw2"
        self.sync()
        self.assertNotIn(("personal@example.test", "P2-NEW"), self.chrome())
        # …and a shadowed account whose credential cannot be read stays in Chrome
        self.insert(ORIGIN + "/user/login", "personal@example.test", "P3")
        logins.plane_secret = lambda cid: None
        self.plane[ORIGIN]["password"] = "pw3"
        self.sync()
        self.assertIn(("personal@example.test", "P3"), self.chrome())

    def test_his_home_page_row_harvested_is_never_taken_for_the_bridges(self):
        con = sqlite3.connect(self.db)
        con.execute("insert into logins (origin_url, action_url, username_element, username_value, password_element,"
                    " password_value, signon_realm, blacklisted_by_user, date_password_modified)"
                    " values (?,?,?,?,?,?,?,0,?)", (self.OTHER + "/", self.OTHER + "/login", "email", "me@home.test",
                                                    "pass", b"v10ONLY-COPY", self.OTHER + "/", self.NEWER))
        con.commit()
        con.close()
        self.opt_in_delete()          # the office that DOES delete in Chrome still never takes his row (fifth reader)
        self.declare(ORIGIN, "owner@example.test", "pw1")               # keeps the listing non-empty
        self.sync()                                                       # harvested
        self.sync()                                                       # identical: no `wrote` for his row
        del self.plane[self.OTHER]                                        # he deletes the harvested credential
        self.sync()
        self.sync()
        self.assertIn(("me@home.test", "ONLY-COPY"), self.chrome(self.OTHER), "his only copy stays in Chrome")

    def test_a_credential_that_now_names_another_account_takes_nothing_from_chrome(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        # in the plane he moves the credential to his personal account, which Chrome holds with an old password
        self.plane[ORIGIN].update(username="personal@example.test", password="NEW-VAULT-PW")
        self.sync()
        self.assertEqual(self.plane[ORIGIN]["password"], "NEW-VAULT-PW", "the plane's new password stays")
        self.assertIn(("personal@example.test", "NEW-VAULT-PW"), self.chrome())

    def test_a_state_file_that_cannot_be_read_stops_the_sync(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        with open(logins.STATE_FILE, "w") as f:
            f.write('{"key": "ab", "entr')                               # a write cut short (a full disk, a kill)
        before = self.chrome()
        self.addCleanup(setattr, logins, "fail", logins.fail)
        logins.fail = lambda code, message: (_ for _ in ()).throw(SystemExit(code))
        with self.assertRaises(SystemExit) as said:
            self.sync()
        self.assertEqual(str(said.exception), "state_unreadable")
        self.assertEqual((self.chrome(), self.writes), (before, []), "nothing synced on a state it cannot read")

    def test_an_old_address_row_is_never_migrated_when_this_run_did_not_refile_it(self):
        n8n, at8080 = "http://n8n.localhost", "http://n8n.localhost:8080"
        self.declare(n8n, "owner@example.test", "pw0", cid="n8n-owner")
        self.sync()
        # the profile is restored from before the bridge: only the old address holds the owner, changed by hand
        con = sqlite3.connect(self.db)
        con.execute("delete from logins where signon_realm = ?", (n8n + "/",))
        con.commit()
        con.close()
        self.insert(at8080 + "/signin", "owner@example.test", "OWNER-AT-8080", realm=at8080 + "/", modified=self.NEWER)
        self.insert(at8080 + "/signin", "personal@example.test", "mine", realm=at8080 + "/", modified=self.NEWER + 9)
        report = self.sync()
        held = [p for u, p in self.chrome(at8080) + self.chrome(n8n) if u == "owner@example.test"]
        self.assertTrue("OWNER-AT-8080" in held or self.plane[n8n]["password"] == "OWNER-AT-8080",
                        f"the only copy of it is not lost: {report}")

    def opt_in_delete(self):
        """CHANGED (the fourth reader): deleting in Chrome is an office's opt-in (BROWSER42_LOGINS_DELETE=1); these
        tests hold that path, the default (nothing deleted) is held apart."""
        self.addCleanup(setattr, logins, "DELETE_IN_CHROME", logins.DELETE_IN_CHROME)
        logins.DELETE_IN_CHROME = True

    def test_by_default_a_credential_gone_from_the_plane_stays_in_chrome_and_is_not_harvested_back(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")
        self.sync()
        del self.plane[ORIGIN]                    # gone from the listing: deleted, or its value stopped resolving
        for _ in range(3):
            report = self.sync()
            self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertIn(("owner@example.test", "pw1"), self.chrome(), "the last copy stays")
        self.assertNotIn(ORIGIN, self.plane, "and it does not come back into the plane by itself")

    def test_a_password_chrome_holds_unrecorded_is_kept_in_the_plane_before_it_is_replaced(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")     # Chrome holds «his-owner@…» for this account, by hand
        report = self.sync()
        self.assertIn((ORIGIN, "owner@example.test", "his-owner@example.test"), self.kept)
        self.assertEqual([k["origin"] for k in report.get("kept", [])], [ORIGIN])
        self.assertIn(("owner@example.test", "pw1"), self.chrome())
        logins.plane_keep_aside = lambda origin, user, pw, source="chrome": None   # the plane could not keep it
        self.plane[ORIGIN].update(username="personal@example.test", password="pw-p")   # another account, unrecorded
        report = self.sync()
        self.assertIn(("personal@example.test", "his-personal@example.test"), self.chrome(), "nothing replaced")

    def test_an_entry_from_before_wrote_has_its_row_deleted_with_its_credential(self):
        self.opt_in_delete()
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")          # a plane that lists nothing decides nothing
        self.sync()
        import json as _json
        st = _json.load(open(logins.STATE_FILE))
        st["entries"][ORIGIN].pop("wrote")                                # as every office's state is today
        _json.dump(st, open(logins.STATE_FILE, "w"))
        self.sync()                                                       # identical: `wrote` is filled in
        del self.plane[ORIGIN]
        self.assertEqual(self.sync()["deleted"], [], "missing from one listing decides nothing yet")
        self.assertEqual(self.sync()["deleted"], [ORIGIN])
        self.assertNotIn(("owner@example.test", "pw1"), self.chrome())

    def test_a_credential_deleted_in_the_plane_takes_the_bridges_row_and_stays_gone(self):
        self.opt_in_delete()
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")
        self.sync()
        self.assertIn(("owner@example.test", "pw1"), self.chrome())
        del self.plane[ORIGIN]
        # CHANGED (the third reader): missing from ONE listing decides nothing — a plane restored from an older backup
        # would otherwise take every newer row the bridge wrote; the next sync, still missing, deletes
        report = self.sync()
        self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertIn(("owner@example.test", "pw1"), self.chrome())
        report = self.sync()
        self.assertEqual(report["deleted"], [ORIGIN])
        self.assertEqual(report["created"], [])                          # not harvested back on the same run
        # exactly the bridge's row went: his personal account stays (the owner's own old row was replaced by
        # the bridge's at the first sync, by design — DGO-1488)
        self.assertEqual(self.chrome(), [("personal@example.test", "his-personal@example.test")])
        self.assertNotIn(ORIGIN, self.plane)
        for _ in range(2):                                              # nor on the runs after it
            report = self.sync()
            self.assertEqual((report["created"], report["deleted"]), ([], []))
        self.assertNotIn(ORIGIN, self.plane)
        # once he changes something there in Chrome, it is a new row like any other, and harvest takes it
        self.chrome_types("personal@example.test", "new-personal-pw", ORIGIN + "/user/login")
        report = self.sync()
        self.assertEqual([c["origin"] for c in report["created"]], [ORIGIN])
        self.assertEqual(self.plane[ORIGIN]["username"], "personal@example.test")

    def test_an_empty_plane_answer_decides_nothing(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.plane.clear()
        report = self.sync()
        self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertEqual([s["origin"] for s in report["skipped"]], ["*"])
        self.assertIn(("owner@example.test", "pw1"), self.chrome())

    def test_harvest_alone_never_deletes(self):
        self.opt_in_delete()
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")
        self.sync()
        del self.plane[ORIGIN]
        report = self.sync(materialize=False, harvest=True)
        self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertIn(("owner@example.test", "pw1"), self.chrome())
        self.assertEqual(self.sync()["deleted"], [ORIGIN])               # the next sync does it

    def test_a_delete_that_did_not_happen_is_not_reported(self):
        self.opt_in_delete()
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")
        self.sync()
        del self.plane[ORIGIN]
        real = logins.chrome_delete_written
        logins.chrome_delete_written = lambda origin, username: 0       # Chrome held the store
        try:
            report = self.sync()
        finally:
            logins.chrome_delete_written = real
        self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertEqual([s["origin"] for s in report["skipped"]], [ORIGIN])
        self.assertEqual(self.sync()["deleted"], [ORIGIN])               # tried again, and done

    def test_his_own_row_harvested_then_deleted_in_the_plane_stays_in_chrome_and_out_of_the_plane(self):
        self.declare(self.OTHER, "me@example.test", "pw-other")
        report = self.sync()
        self.assertEqual([c["origin"] for c in report["created"]], [ORIGIN])
        before = self.chrome()
        del self.plane[ORIGIN]
        for _ in range(2):
            report = self.sync()
            self.assertEqual((report["deleted"], report["created"]), ([], []))
        self.assertEqual(self.chrome(), before)                          # the bridge never wrote it: never deleted
        self.assertNotIn(ORIGIN, self.plane)

    # ── the fifth reader ──────────────────────────────────────────────────────────────────────────────────────────
    def test_a_harvested_credential_moved_to_another_account_in_the_plane_keeps_its_new_password(self):
        self.declare(self.OTHER, "me@example.test", "pw-other")          # keeps the listing non-empty
        self.sync()                                                       # ORIGIN harvested: one of his accounts
        taken = self.plane[ORIGIN]["username"]
        other = next(u for u in ("owner@example.test", "personal@example.test") if u != taken)
        self.assertEqual(logins.load_state()["entries"][ORIGIN].get("account"), taken, "the harvest says whose")
        self.plane[ORIGIN].update(username=other, password="NEW-VAULT-PW")
        self.sync()
        self.assertEqual(self.plane[ORIGIN]["password"], "NEW-VAULT-PW", "Chrome's old password did not go over it")
        self.assertIn((other, "NEW-VAULT-PW"), self.chrome())
        self.assertIn((ORIGIN, other, "his-" + other), self.kept, "Chrome's old password of that account is kept")

    def test_an_entry_the_memory_names_no_account_for_takes_nothing_from_chrome(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        state = logins.load_state()
        state["entries"][ORIGIN].pop("account")                           # a state from an older bridge
        logins.save_state(state)
        self.chrome_types("owner@example.test", "typed-in-chrome")
        self.plane[ORIGIN]["password"] = "set-in-plane"
        self.sync()
        self.assertEqual(self.plane[ORIGIN]["password"], "set-in-plane", "nothing taken from Chrome on no account")
        self.assertIn(("owner@example.test", "set-in-plane"), self.chrome())
        self.assertIn((ORIGIN, "owner@example.test", "typed-in-chrome"), self.kept, "…and Chrome's is kept aside")

    def test_a_password_in_a_companion_field_is_written_to_that_field(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.plane[ORIGIN]["password_field"] = "SHOP_PASSWORD"
        self.sync()
        self.chrome_types("owner@example.test", "pw2")
        self.sync()
        self.assertIn(("declared-portal.internic.co.il", "SHOP_PASSWORD", "pw2"), self.writes)
        self.assertNotIn(("declared-portal.internic.co.il", None, "pw2"), self.writes, "the main value untouched")

    def test_when_both_sides_moved_the_planes_password_is_kept_before_chromes_goes_over_it(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.chrome_types("owner@example.test", "chrome-new")
        self.plane[ORIGIN]["password"] = "plane-new"
        self.sync()
        self.assertEqual(self.plane[ORIGIN]["password"], "chrome-new", "Chrome wins, as before")
        self.assertIn((ORIGIN, "owner@example.test", "plane-new"), self.kept)
        self.assertEqual(self.kept_from[self.kept.index((ORIGIN, "owner@example.test", "plane-new"))], "plane")

    def test_a_plane_restored_to_an_older_password_keeps_chromes_newer_one_first(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        self.chrome_types("owner@example.test", "pw2")
        self.sync()                                                       # pw2 reached the plane
        self.plane[ORIGIN]["password"] = "pw1"                            # the vault restored from an older backup
        self.sync()
        self.assertIn((ORIGIN, "owner@example.test", "pw2"), self.kept, "the newer password is not lost")

    def test_two_looks_within_the_hour_delete_nothing(self):
        self.opt_in_delete()
        self.addCleanup(setattr, logins, "MISSING_MIN_SECONDS", logins.MISSING_MIN_SECONDS)
        logins.MISSING_MIN_SECONDS = 3600
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.declare(self.OTHER, "me@example.test", "pw-other")          # keeps the listing non-empty
        self.sync()
        del self.plane[ORIGIN]
        self.assertEqual(self.sync()["deleted"], [])
        self.assertEqual(self.sync()["deleted"], [], "a second look in the same hour is not a second listing")
        state = logins.load_state()
        state["entries"][ORIGIN]["missing"] -= 3601                       # an hour later
        logins.save_state(state)
        self.assertEqual(self.sync()["deleted"], [ORIGIN])

    def test_a_sync_while_another_runs_does_nothing_and_says_so(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        import fcntl
        holder = open(logins.STATE_FILE + ".lock", "a")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(setattr, logins, "fail", logins.fail)
        logins.fail = lambda code, message: (_ for _ in ()).throw(SystemExit(code))
        before = self.chrome()
        with self.assertRaises(SystemExit) as said:
            self.sync()
        self.assertEqual(str(said.exception), "sync_running")
        self.assertEqual((self.chrome(), self.writes), (before, []))

    def test_keep_once_keeps_a_password_once_and_saves_at_once(self):
        state = logins.load_state()
        first = logins.keep_once(state, ORIGIN, "owner@example.test", "old-pw")
        on_disk = logins.load_state()                                     # saved at once, before the sync's own save
        second = logins.keep_once(on_disk, ORIGIN, "owner@example.test", "old-pw")
        self.assertEqual((first, second, len(self.kept)), ("kept-1", logins.ALREADY_KEPT, 1))
        self.assertEqual(logins.keep_once(on_disk, ORIGIN, "owner@example.test", "another-pw"), "kept-2")

    def test_a_password_kept_once_is_not_kept_again_by_the_next_sync(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.chrome_types("owner@example.test", "unrecorded", origin_url=ORIGIN + "/user/login")
        self.sync()
        state = logins.load_state()
        state["entries"].pop(ORIGIN)                        # as if the sync had stopped before its own save
        logins.save_state(state)
        self.chrome_types("owner@example.test", "unrecorded", origin_url=ORIGIN + "/user/login")
        self.sync()
        self.assertEqual([k for k in self.kept if k[2] == "unrecorded"], [(ORIGIN, "owner@example.test", "unrecorded")],
                         "kept once, though two syncs saw it")

    def test_a_state_write_cut_short_leaves_the_old_state_and_no_stray_file(self):
        self.declare(ORIGIN, "owner@example.test", "pw1")
        self.sync()
        before = open(logins.STATE_FILE).read()
        real = logins.json.dump

        def cut(*a, **k):
            raise OSError("disk full")
        logins.json.dump = cut
        try:
            with self.assertRaises(OSError):
                logins.save_state({"key": "ab", "entries": {}})
        finally:
            logins.json.dump = real
        self.assertEqual(open(logins.STATE_FILE).read(), before)
        base = os.path.basename(logins.STATE_FILE)
        self.assertEqual(sorted(f for f in os.listdir(os.path.dirname(logins.STATE_FILE)) if f.startswith(
            (base, ".logins-state-")) and f not in (base, base + ".lock")), [], "no temporary file left beside it")

    def test_two_saves_never_share_a_temporary_file(self):
        names = []
        real = logins.tempfile.mkstemp

        def watch(*a, **k):
            fd, path = real(*a, **k)
            names.append(path)
            return fd, path
        logins.tempfile.mkstemp = watch
        try:
            logins.save_state({"key": "ab", "entries": {}})
            logins.save_state({"key": "ab", "entries": {}})
        finally:
            logins.tempfile.mkstemp = real
        self.assertEqual(len(set(names)), 2, names)


class KeepAsideAndKept(unittest.TestCase):
    """The real plane_keep_aside and plane_entries against a fake connections API (the fifth reader)."""

    def setUp(self):
        self.calls, self.writes = [], []

        creds = {   # the listing as the real API gives it: a kept copy AFTER the site's own credential
            "browser-login-shop-test": ("https://shop.test/", [
                {"key": "BROWSER_LOGIN_SHOP_TEST_PASSWORD", "secret": True, "primary": True}]),
            "browser-login-shop-test-kept-20261110120000": ("https://shop.test/", [
                {"key": "BROWSER_LOGIN_SHOP_TEST_KEPT_20261110120000_PASSWORD", "secret": True, "primary": True}]),
            # a real site with `kept` in its name is a site, not a kept copy (the sixth reader)
            "browser-login-www-kept-co-il": ("https://www.kept.co.il/", [
                {"key": "BROWSER_LOGIN_WWW_KEPT_CO_IL_PASSWORD", "secret": True, "primary": True}]),
            # a credential whose password is a COMPANION of its main value (an API key)
            "shop-api": ("https://api.shop.test/", [
                {"key": "SHOP_API_KEY", "secret": True, "primary": True},
                {"key": "SHOP_PASSWORD", "secret": True, "primary": False}]),
        }

        def call(path, body=None):
            self.calls.append((path, body))
            if path == "/api/connections":
                return [{"id": cid} for cid in creds]
            if path.startswith("/api/cred/"):
                url, fields = creds[path.rsplit("/", 1)[-1]]
                return {"app": {"url": url, "user": "me@shop.test"}, "fields": fields}
            if path.startswith("/api/reveal/"):
                return {"value": "pw-of-" + path.rsplit("/", 1)[-1]}
            return {"ok": True}

        def write(cid, field, value):
            self.writes.append((cid, field, value))          # seen, even when the plane refuses it
            if not value:
                raise SystemExit("value required")
        for name, fake in {"_call": call, "plane_write": write, "plane_exists": lambda cid: False}.items():
            self.addCleanup(setattr, logins, name, getattr(logins, name))
            setattr(logins, name, fake)

    def test_a_kept_copy_is_never_a_sites_login(self):
        entries = logins.plane_entries()
        self.assertEqual(entries["https://shop.test"]["cid"], "browser-login-shop-test", "not the kept copy listed after")
        self.assertIsNone(entries["https://shop.test"]["password_field"], "the primary: /api/set's default")
        self.assertEqual(entries["https://www.kept.co.il"]["cid"], "browser-login-www-kept-co-il",
                         "a site with `kept` in its name is still a site")

    def test_a_password_in_a_companion_field_is_written_to_that_field(self):
        entries = logins.plane_entries()
        self.assertEqual((entries["https://api.shop.test"]["password_field"], entries["https://api.shop.test"]["password"]),
                         ("SHOP_PASSWORD", "pw-of-shop-api"))

    def test_a_password_kept_with_no_user_name_is_kept_once(self):
        cid = logins.plane_keep_aside("https://shop.test", "", "old-pw")
        self.assertTrue(cid and "-kept-" in cid)
        self.assertEqual([c for c in self.calls if c[0] == "/api/add"][0][1]["value"], "old-pw")
        self.assertFalse([w for w in self.writes if w[1].endswith("_USER")], "an empty user name is not written")

    def test_two_kept_in_one_second_take_two_ids(self):
        taken = set()
        logins.plane_exists = lambda cid: cid in taken
        self.addCleanup(setattr, logins.time, "gmtime", logins.time.gmtime)
        frozen = logins.time.gmtime(1_800_000_000)
        logins.time.gmtime = lambda *a: frozen                    # the same second for both: never by luck
        first = logins.plane_keep_aside("https://shop.test", "me", "pw-a")
        taken.add(first)
        second = logins.plane_keep_aside("https://shop.test", "me", "pw-b")
        self.assertTrue(first and second and first != second, (first, second))

    def test_the_copies_of_the_password_store_are_removed_when_the_process_ends(self):
        db = os.path.join(tempfile.mkdtemp(prefix="b42-db-"), "Login Data")
        open(db, "wb").close()
        self.addCleanup(setattr, logins, "LOGIN_DB", logins.LOGIN_DB)
        logins.LOGIN_DB = db
        copy = logins._login_db_copy()
        self.assertTrue(os.path.exists(copy))
        logins._drop_copies()
        self.assertFalse(os.path.exists(os.path.dirname(copy)), "a copy of every password left in /tmp")

    def test_a_field_that_cannot_be_written_after_the_copy_still_counts_as_kept(self):
        def write(cid, field, value):
            raise SystemExit("refused")
        logins.plane_write = write
        self.assertTrue(logins.plane_keep_aside("https://shop.test", "me", "old-pw"))


class MigrationMovesOneAccount(unittest.TestCase):
    """«migrated»: a row filed under the owner's `:8080` is unreachable from this browser, so the account the plane
    holds is refiled under the port-less address and its `:8080` row goes. On a real Chromium Login Data (the
    second reader, ci-artifacts/king-2026-11-10/lanes/security-backup/bridge_real.py) it deleted EVERY row of the
    variant: his other account there, whose password exists nowhere else, went with it."""
    N8N = "http://n8n.localhost:8080"
    setUp, declare, sync, chrome = (SyncOnARealLoginData.setUp, SyncOnARealLoginData.declare,
                                    SyncOnARealLoginData.sync, SyncOnARealLoginData.chrome)

    def test_the_planes_account_moves_and_his_other_account_stays(self):
        con = sqlite3.connect(self.db)
        for user, black in (("owner@example.test", 0), ("personal@example.test", 0), ("", 1)):
            con.execute("insert into logins (origin_url, username_value, password_value, signon_realm,"
                        " blacklisted_by_user, date_password_modified) values (?,?,?,?,?,1)",
                        (self.N8N + "/signin", user, b"v10at8080-" + user.encode(), self.N8N + "/", black))
        con.commit()
        con.close()
        self.declare("http://n8n.localhost", "owner@example.test", "P1", cid="n8n-owner")
        got = self.sync()
        self.assertEqual(got.get("migrated"), [self.N8N + "/signin"])
        con = sqlite3.connect(self.db)
        try:
            left = sorted(r for r in con.execute("select username_value, blacklisted_by_user from logins "
                                                 "where origin_url = ?", (self.N8N + "/signin",)))
        finally:
            con.close()
        self.assertEqual(left, [("", 1), ("personal@example.test", 0)],
                         "his other account and his «never save» stay under :8080; only the plane's account moved")
        self.assertEqual(self.chrome("http://n8n.localhost"), [("owner@example.test", "P1")])


if __name__ == "__main__":
    unittest.main()
