#!/usr/bin/env python3
"""A person on a LINKED office's console opens this office's meetings (DGO-1895).

The MacBook's console frames vps1's Meet through the link: its proxy → the link → vps1's door (dgo-net) → meet-start.
meet-start believed a signed-in person only from the edge and the console, so every request over the link was
anonymous: the tile was Jitsi's bare welcome page, and «פגישה חדשה» / "I am the host" led to vps1's own sign-in, which a
frame on another office's console can never show («לא ניתן היה להתחבר אל auth.staging…», the owner, 2026-11-15).
Measured from the Mac's console: `/` 302 to the welcome page, `/flow/`, `/new`, `/recordings` 401.

These tests hold the rule that replaced it: from the link door's own address, the ONE username the door writes is a
person (the door removes every X-authentik-* line the other office sent); two lines, none, or any other caller are not.
They need nothing but this file and server.py (run: python3 test_link_person.py, or pytest).
"""
import base64
import http.client
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = pathlib.Path(__file__).resolve().parent
TMP = tempfile.mkdtemp(prefix="meet-link-person-")
os.environ["MEET_RECORDINGS"] = TMP
os.environ["MEET_JWT_SECRET"] = "test-secret-" + "x" * 32
os.environ["MEET_HOST"] = "meet.example.test"
os.environ.pop("MEET_HOME", None)                     # the default: the tile is «פגישות»
sys.path.insert(0, str(HERE))
import server  # noqa: E402

LOCAL = "127.0.0.1"


def claims(location: str) -> dict:
    """The host token's claims, read out of the redirect into the meeting (its signature is prosody's to check)."""
    token = parse_qs(urlsplit(location).query)["jwt"][0]
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


class LinkPerson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # server.py reads its signing secret when it is first imported; under one pytest process another test may
        # have imported it before this file set one (the second reader, DGO-1895), and /new would answer 503
        cls.secret = server.SECRET
        server.SECRET = server.SECRET or os.environ["MEET_JWT_SECRET"]
        cls.httpd = ThreadingHTTPServer((LOCAL, 0), server.Door)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.saved = (server.trusted_ips, server.link_ips)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.trusted_ips, server.link_ips = cls.saved
        server.SECRET = cls.secret
        shutil.rmtree(TMP, ignore_errors=True)

    def caller(self, edge=False, door=False):
        """Who this test's requests come from: the edge, the link's door, or a stranger on the network."""
        server.trusted_ips = (lambda: {LOCAL}) if edge else (lambda: set())
        server.link_ips = (lambda: {LOCAL}) if door else (lambda: set())

    def get(self, path, users=(), extra=None):
        c = http.client.HTTPConnection(LOCAL, self.port, timeout=10)
        c.putrequest("GET", path)
        for u in users:                                  # one header line per name: putheader writes each
            c.putheader("X-authentik-username", u)
        for k, v in (extra or {}).items():
            c.putheader(k, v)
        c.endheaders()
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, r.getheader("Location") or "", body

    # ── who is a person ──────────────────────────────────────────────────────────────────────────────
    def test_the_door_writes_the_person(self):
        self.caller(door=True)
        status, _, body = self.get("/flow/", ["akadmin"])
        self.assertEqual(status, 200)
        self.assertIn("akadmin", body.decode("utf-8"))   # the page's own config names who it is for

    def test_two_username_lines_from_the_door_are_nobody(self):
        self.caller(door=True)
        status, _, _ = self.get("/flow/", ["akadmin", "someone-else"])
        self.assertEqual(status, 401)

    def test_the_door_with_no_username_is_nobody(self):
        self.caller(door=True)
        status, _, _ = self.get("/flow/")
        self.assertEqual(status, 401)

    def test_a_name_from_the_link_is_not_read(self):
        # the door strips names; were one ever to arrive, the person is still their username alone
        self.caller(door=True)
        status, _, body = self.get("/flow/", ["akadmin"], {"X-authentik-name": "Mallory"})
        self.assertEqual(status, 200)
        self.assertNotIn("Mallory", body.decode("utf-8"))

    def test_a_stranger_writing_the_header_is_nobody(self):
        self.caller()
        status, _, _ = self.get("/flow/", ["akadmin"])
        self.assertEqual(status, 401)

    def test_the_edge_is_believed_as_before(self):
        self.caller(edge=True)
        # the edge sends a name's UTF-8 bytes, which http.server reads as latin-1 (server.header undoes that)
        name = "הבעלים".encode("utf-8").decode("latin-1")
        status, _, body = self.get("/flow/", ["owner"], {"X-authentik-name": name})
        self.assertEqual(status, 200)
        self.assertIn("הבעלים", body.decode("utf-8"))

    # ── what the linked console's tile becomes ───────────────────────────────────────────────────────
    def test_the_tile_is_the_meetings_page_not_the_welcome_page(self):
        self.caller(door=True)
        status, location, body = self.get("/", ["akadmin"])
        self.assertEqual(status, 200, f"redirected to {location!r}: the bare Jitsi page again")
        self.assertIn('data-config', body.decode("utf-8"))

    def test_nobody_still_gets_the_welcome_page(self):
        self.caller()
        status, location, _ = self.get("/", ["akadmin"])
        self.assertEqual(status, 302)
        self.assertEqual(location, server.meet_base()[0] + "/")

    def test_a_new_meeting_from_the_linked_console_is_a_host_token(self):
        self.caller(door=True)
        status, location, _ = self.get("/new", ["akadmin"])
        self.assertEqual(status, 302)
        self.assertTrue(location.startswith(server.meet_base()[0] + "/"), location)
        user = claims(location)["context"]["user"]
        self.assertEqual((user["id"], user["name"], user["moderator"]), ("akadmin", "akadmin", True))

    def test_the_host_door_names_the_room(self):
        self.caller(door=True)
        status, location, _ = self.get("/r/dgo1895-room", ["akadmin"])
        self.assertEqual(status, 302)
        self.assertTrue(location.startswith(server.meet_base()[0] + "/dgo1895-room?jwt="), location)
        got = claims(location)
        self.assertEqual((got["room"], got["context"]["user"]["id"]), ("dgo1895-room", "akadmin"))

    def test_the_recordings_answer_the_linked_person(self):
        self.caller(door=True)
        status, _, _ = self.get("/recordings", ["akadmin"])
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
