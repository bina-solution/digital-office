#!/usr/bin/env python3
"""test_server — the element adapter against a fake Matrix homeserver (DGO-1264).

The homeserver here answers the client-server calls the adapter makes, the way the spec says
(spec.matrix.org, client-server API v3). What is asked:
- /v1/health answers with no token and says whether this device is signed in; every other route wants the token;
- login by password stores the session (and never answers the token back); login by token checks it with whoami;
- a wrong password is the homeserver's own errcode, not a traceback;
- listConversations names each room (m.room.name, else its alias, else its id), marks the encrypted one, and
  puts the newest first;
- getConversation reads messages oldest first, and an encrypted message is «encrypted» with no text;
- sendMessage refuses an encrypted room (409) and sends nothing there; into a plain room it sends m.text;
- markRead posts the receipt; a room id or an event id that is not Matrix's shape is refused before any call;
- logout of a password session signs the device out; of a token session it keeps the owner's other device alive.

Run: python3 apps/element/adapter/test_server.py   (standard library only)
"""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = tempfile.mkdtemp(prefix="element-adapter-")
os.environ["ELEMENT_STATE"] = STATE
# the office's publisher, replaced: what the adapter emits on dgo:flow:element is recorded here
import sys as _sys  # noqa: E402
import types as _types  # noqa: E402
EMITTED = []
_fp = _types.ModuleType("flowpub")
_fp.emit = lambda app, type_, title, data=None, link="": EMITTED.append((app, type_, title, data)) or True
_sys.modules["flowpub"] = _fp
spec = importlib.util.spec_from_file_location("element_adapter", os.path.join(HERE, "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

PLAIN, SECRET, V12 = "!plain:hs.test", "!secret:hs.test", "!31hneApxJ_1REDACTEDdrivexxxxxxxxxxxxxxx0054"
CALLS = []
VALID = {"tok-1"}                 # the tokens the homeserver honours; a test takes one away to "remove the device"
LOGINS = iter(f"tok-{n}" for n in range(2, 100))   # tok-1 is the token «copied from Element»: never a login's


class Homeserver(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, doc):
        b = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def authed(self):
        a = self.headers.get("Authorization") or ""
        return a.startswith("Bearer ") and a[7:] in VALID

    def handle_any(self, method):
        from urllib.parse import unquote, urlsplit
        u = urlsplit(self.path)
        p = unquote(u.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        CALLS.append((method, p, body))
        if p == "/_matrix/client/v3/login" and method == "POST":
            if body.get("password") == "right":
                tok = next(LOGINS)
                VALID.add(tok)
                return self.reply(200, {"access_token": tok, "user_id": "@owner:hs.test", "device_id": "DEV" + tok[4:]})
            return self.reply(403, {"errcode": "M_FORBIDDEN", "error": "Invalid username or password"})
        if not self.authed():
            return self.reply(401, {"errcode": "M_UNKNOWN_TOKEN", "error": "Unknown access token"})
        if p == "/_matrix/client/v3/account/whoami":
            return self.reply(200, {"user_id": "@owner:hs.test", "device_id": "DEV0"})
        if p == "/_matrix/client/v3/logout":
            VALID.discard((self.headers.get("Authorization") or "")[7:])
            return self.reply(200, {})
        if p == "/_matrix/client/v3/sync":
            return self.reply(200, {"next_batch": "s1", "rooms": {"join": {
                PLAIN: {"state": {"events": [{"type": "m.room.name", "content": {"name": "הצוות"}}]},
                        "timeline": {"events": [{"type": "m.room.message", "origin_server_ts": 2000}]},
                        "unread_notifications": {"notification_count": 3}},
                SECRET: {"state": {"events": [{"type": "m.room.canonical_alias", "content": {"alias": "#secret:hs.test"}},
                                              {"type": "m.room.encryption", "content": {"algorithm": "m.megolm.v1.aes-sha2"}}]},
                         "timeline": {"events": [{"type": "m.room.encrypted", "origin_server_ts": 3000}]}},
                "!bare:hs.test": {"timeline": {"events": [{"type": "m.room.member", "origin_server_ts": 1000}]}},
                V12: {"summary": {"m.heroes": ["@friend:hs.test"]},
                      "timeline": {"events": [{"type": "m.room.message", "origin_server_ts": 500}]}},
            }}})
        if p.endswith("/messages") and method == "GET":
            return self.reply(200, {"chunk": [
                {"type": "m.room.encrypted", "event_id": "$3", "sender": "@b:hs.test", "origin_server_ts": 3, "content": {}},
                {"type": "m.room.member", "event_id": "$m", "sender": "@b:hs.test", "origin_server_ts": 2, "content": {}},
                {"type": "m.room.message", "event_id": "$1", "sender": "@a:hs.test", "origin_server_ts": 1,
                 "content": {"msgtype": "m.text", "body": "שלום"}}]})
        if p.endswith("/state/m.room.encryption/"):
            if SECRET in p:
                return self.reply(200, {"algorithm": "m.megolm.v1.aes-sha2"})
            return self.reply(404, {"errcode": "M_NOT_FOUND", "error": "Event not found."})
        if "/send/m.room.message/" in p and method == "PUT":
            return self.reply(200, {"event_id": "$sent"})
        if "/receipt/m.read/" in p and method == "POST":
            return self.reply(200, {})
        return self.reply(404, {"errcode": "M_UNRECOGNIZED", "error": "Unrecognized request"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")


def serve(handler):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


HS, HS_URL = serve(Homeserver)
AD, AD_URL = serve(srv.Door)
TOKEN = srv.api_token()


def call(method, path, body=None, token=TOKEN):
    req = urllib.request.Request(AD_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Adapter(unittest.TestCase):
    def setUp(self):
        srv.drop_session()
        VALID.add("tok-1")
        CALLS.clear()

    def sign_in(self):
        code, d = call("POST", "/v1/login", {"homeserver": HS_URL, "user": "owner", "password": "right"})
        self.assertEqual(code, 200, d)
        return d

    def test_health_is_open_and_everything_else_wants_the_token(self):
        code, d = call("GET", "/v1/health", token=None)
        self.assertEqual((code, d["signed_in"]), (200, False))
        self.assertEqual(call("GET", "/v1/conversations", token=None)[0], 401)
        self.assertEqual(call("GET", "/v1/conversations", token="wrong")[0], 401)

    def test_password_login_stores_the_session_and_never_answers_the_token(self):
        d = self.sign_in()
        self.assertEqual(d["user_id"], "@owner:hs.test")
        self.assertRegex(d["device_id"], r"^DEV\d+$")
        self.assertNotIn("tok-", json.dumps(d))
        self.assertTrue(call("GET", "/v1/health", token=None)[1]["signed_in"])
        self.assertEqual(oct(os.stat(os.path.join(STATE, "session.json")).st_mode & 0o777), "0o600")
        self.assertEqual(CALLS[0][2]["identifier"], {"type": "m.id.user", "user": "owner"})

    def test_a_wrong_password_is_the_homeservers_own_answer(self):
        code, d = call("POST", "/v1/login", {"homeserver": HS_URL, "user": "owner", "password": "wrong"})
        self.assertEqual((code, d["error"]), (403, "M_FORBIDDEN"))
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])

    def test_token_login_is_checked_with_whoami(self):
        code, d = call("POST", "/v1/login", {"homeserver": HS_URL, "access_token": "tok-1"})
        self.assertEqual((code, d["device_id"]), (200, "DEV0"))
        code, d = call("POST", "/v1/login", {"homeserver": HS_URL, "access_token": "nope"})
        self.assertEqual((code, d["error"]), (403, "M_UNKNOWN_TOKEN"))      # 401 is this door's own bearer gate

    def test_signed_out_is_said(self):
        code, d = call("GET", "/v1/conversations")
        self.assertEqual((code, d["error"]), (409, "signed-out"))

    def test_list_names_marks_encrypted_and_puts_the_newest_first(self):
        self.sign_in()
        code, d = call("GET", "/v1/conversations")
        self.assertEqual(code, 200, d)
        rows = [(c["id"], c["name"], c["encrypted"], c["unread"]) for c in d["conversations"]]
        self.assertEqual(rows, [(SECRET, "#secret:hs.test", True, 0), (PLAIN, "הצוות", False, 3),
                                ("!bare:hs.test", "!bare:hs.test", False, 0), (V12, "@friend:hs.test", False, 0)])

    def test_messages_read_oldest_first_and_encrypted_has_no_text(self):
        self.sign_in()
        code, d = call("GET", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "?limit=5")
        self.assertEqual(code, 200, d)
        self.assertEqual([(m["id"], m["encrypted"], m["text"]) for m in d["messages"]],
                         [("$1", False, "שלום"), ("$3", True, None)])

    def test_send_refuses_an_encrypted_room_and_sends_text_to_a_plain_one(self):
        self.sign_in()
        CALLS.clear()
        code, d = call("POST", "/v1/conversations/" + urllib.request.quote(SECRET, safe="") + "/messages", {"text": "hi"})
        self.assertEqual((code, d["error"]), (409, "encrypted-room"))
        self.assertFalse([c for c in CALLS if c[0] == "PUT"])
        code, d = call("POST", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/messages", {"text": "hi"})
        self.assertEqual((code, d["id"]), (200, "$sent"))
        sent = [c for c in CALLS if c[0] == "PUT"]
        self.assertEqual(sent[0][2], {"msgtype": "m.text", "body": "hi"})

    def test_mark_read_posts_the_receipt_and_bad_ids_are_refused_first(self):
        self.sign_in()
        CALLS.clear()
        code, _ = call("POST", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/read", {"event_id": "$1"})
        self.assertEqual(code, 200)
        self.assertTrue(CALLS[-1][1].endswith("/receipt/m.read/$1"))
        CALLS.clear()
        for path, body in (("/v1/conversations/not-a-room", None), ("/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/read", {"event_id": "x"})):
            code, _ = call("POST" if body else "GET", path, body)
            self.assertEqual(code, 400, path)
        self.assertEqual(CALLS, [])

    def test_logout_signs_a_password_device_out_and_keeps_a_copied_token_alive(self):
        self.sign_in()
        CALLS.clear()
        self.assertEqual(call("POST", "/v1/logout")[0], 200)
        self.assertEqual([c[1] for c in CALLS], ["/_matrix/client/v3/logout"])
        call("POST", "/v1/login", {"homeserver": HS_URL, "access_token": "tok-1"})
        CALLS.clear()
        self.assertEqual(call("POST", "/v1/logout")[0], 200)
        self.assertEqual(CALLS, [])
        self.assertIn("tok-1", VALID)
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])

    def test_a_second_sign_in_signs_the_first_device_out(self):
        self.sign_in()
        first = srv.session()["access_token"]
        self.sign_in()
        self.assertNotIn(first, VALID)
        self.assertIn(srv.session()["access_token"], VALID)

    def test_a_removed_device_is_signed_out_not_kept(self):
        call("POST", "/v1/login", {"homeserver": HS_URL, "access_token": "tok-1"})
        VALID.discard("tok-1")                         # the owner removed the device in Element's settings
        code, d = call("GET", "/v1/conversations")
        self.assertEqual((code, d["error"]), (409, "signed-out"))
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])

    def test_room_ids_are_opaque_a_version_12_room_reads(self):
        self.sign_in()
        code, d = call("GET", "/v1/conversations/" + urllib.request.quote(V12, safe=""))
        self.assertEqual(code, 200, d)
        q = [c for c in CALLS if c[1].endswith("/messages")][-1]
        self.assertIn(V12, q[1])

    def test_a_non_ascii_or_negative_request_is_refused_not_a_500(self):
        self.assertEqual(call("GET", "/v1/conversations", token="é")[0], 401)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", AD.server_address[1], timeout=5)
        c.putrequest("POST", "/v1/login")
        c.putheader("Authorization", "Bearer " + TOKEN)
        c.putheader("Content-Length", "-1")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c.close()

    def test_the_flow_says_what_was_done_and_never_the_text_or_a_token(self):
        EMITTED.clear()
        self.sign_in()
        call("POST", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/messages", {"text": "סוד גדול"})
        call("POST", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/read", {"event_id": "$1"})
        call("POST", "/v1/logout")
        self.assertEqual([(a, t) for a, t, _, _ in EMITTED],
                         [("element", "account.signed_in"), ("element", "message.sent"),
                          ("element", "conversation.read"), ("element", "account.signed_out")])
        blob = json.dumps(EMITTED, ensure_ascii=False)
        self.assertNotIn("סוד גדול", blob)
        self.assertNotIn("tok-", blob)
        self.assertIn("on_server", EMITTED[-1][3])

    def test_a_publisher_that_fails_never_fails_the_request(self):
        def boom(*a, **k):
            raise RuntimeError("redis is away")
        keep, _fp.emit = _fp.emit, boom
        try:
            self.sign_in()
            code, d = call("POST", "/v1/conversations/" + urllib.request.quote(PLAIN, safe="") + "/messages", {"text": "hi"})
            self.assertEqual(code, 200, d)
        finally:
            _fp.emit = keep

    def test_plain_http_off_this_machine_is_refused(self):
        code, d = call("POST", "/v1/login", {"homeserver": "http://matrix.example.org", "user": "o", "password": "p"})
        self.assertEqual((code, d["error"]), (400, "homeserver"))
        self.assertEqual(CALLS, [])


if __name__ == "__main__":
    unittest.main()
