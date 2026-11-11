#!/usr/bin/env python3
"""test_server — the slack adapter against a fake Slack Web API (DGO-1264).

The fake answers the methods the adapter calls the way api.slack.com/methods documents them: HTTP 200 with
{"ok": true, …} or {"ok": false, "error": "…"}, cursor paging, and 429 with Retry-After. What is asked:
- /v1/health is open; every other route wants the app's bearer token, and a non-ASCII bearer is a 401;
- login keeps a token only after auth.test accepts it, never answers it back, and keeps it 0600;
- Slack's own error names come through (invalid_auth and not_in_channel → 403; 401 is this door's own token
  gate), never a traceback, and a token Slack no longer accepts signs the adapter out (409);
- listConversations follows the cursor, kinds a DM / a private channel / a channel, in Slack's own order;
- getConversation reads oldest first; sendMessage posts chat.postMessage with the text; markRead posts
  conversations.mark with the ts; a channel id or a ts that is not Slack's shape is refused before any call;
- a 429 is passed on with its Retry-After; logout only forgets the token;
- the flow (dgo:flow:slack) says what was done, and never the text or a token.

Run: python3 apps/slack/adapter/test_server.py   (standard library only)
"""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = tempfile.mkdtemp(prefix="slack-adapter-")
os.environ["SLACK_STATE"] = STATE
CALLS = []
HEADERS = []                      # (method, api, Content-Type) of every call the fake answered
RATE_LIMIT = {"on": False}
# the office's publisher, replaced: what the adapter emits on dgo:flow:slack is recorded here
import sys as _sys  # noqa: E402
import types as _types  # noqa: E402
EMITTED = []
_fp = _types.ModuleType("flowpub")
_fp.emit = lambda app, type_, title, data=None, link="": EMITTED.append((app, type_, title, data)) or True
_sys.modules["flowpub"] = _fp


class Slack(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, doc, headers=None):
        b = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def handle_any(self, method):
        u = urllib.parse.urlsplit(self.path)
        api = u.path.rsplit("/", 1)[-1]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        q = dict(urllib.parse.parse_qsl(u.query))
        CALLS.append((method, api, body or q))
        HEADERS.append((method, api, self.headers.get("Content-Type")))
        if RATE_LIMIT["on"]:
            return self.reply(429, {"ok": False, "error": "ratelimited"}, {"Retry-After": "7"})
        if self.headers.get("Authorization") != "Bearer xoxp-good":
            return self.reply(200, {"ok": False, "error": "invalid_auth"})
        if api == "auth.test":
            return self.reply(200, {"ok": True, "user": "owner", "user_id": "U1", "team": "המשרד", "team_id": "T1",
                                    "url": "https://office.slack.com/"})
        if api == "users.conversations":
            if not q.get("cursor"):
                return self.reply(200, {"ok": True, "channels": [
                    {"id": "C0000001", "name": "general", "is_private": False, "updated": 100},
                    {"id": "G0000002", "name": "board", "is_private": True, "updated": 300}],
                    "response_metadata": {"next_cursor": "page2"}})
            return self.reply(200, {"ok": True, "channels": [{"id": "D0000003", "is_im": True, "user": "U9", "updated": 200}],
                                    "response_metadata": {"next_cursor": ""}})
        if api == "conversations.history":
            if q.get("channel") == "C0000009":
                return self.reply(200, {"ok": False, "error": "not_in_channel"})
            return self.reply(200, {"ok": True, "messages": [
                {"type": "message", "user": "U9", "text": "second", "ts": "1700000002.000200"},
                {"type": "message", "user": "U1", "text": "שלום", "ts": "1700000001.000100"}]})
        if api == "chat.postMessage":
            return self.reply(200, {"ok": True, "ts": "1700000003.000300", "channel": body.get("channel")})
        if api == "conversations.mark":
            return self.reply(200, {"ok": True})
        return self.reply(200, {"ok": False, "error": "unknown_method"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


def serve(handler):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


SL, SL_URL = serve(Slack)
os.environ["SLACK_API"] = SL_URL + "/api"
spec = importlib.util.spec_from_file_location("slack_adapter", os.path.join(HERE, "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
AD, AD_URL = serve(srv.Door)
TOKEN = srv.api_token()


def call(method, path, body=None, token=TOKEN):
    req = urllib.request.Request(AD_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


class Adapter(unittest.TestCase):
    def setUp(self):
        srv.drop_session()
        RATE_LIMIT["on"] = False
        CALLS.clear()

    def sign_in(self):
        code, d, _ = call("POST", "/v1/login", {"token": "xoxp-good"})
        self.assertEqual(code, 200, d)
        return d

    def test_health_is_open_and_the_rest_wants_the_token(self):
        code, d, _ = call("GET", "/v1/health", token=None)
        self.assertEqual((code, d["signed_in"]), (200, False))
        for t in (None, "wrong", "é"):
            self.assertEqual(call("GET", "/v1/conversations", token=t)[0], 401, t)

    def test_login_keeps_a_token_only_after_auth_test_and_never_answers_it(self):
        d = self.sign_in()
        self.assertEqual((d["user"], d["team"], d["kind"]), ("owner", "המשרד", "user"))
        self.assertNotIn("xoxp-good", json.dumps(d))
        self.assertEqual(oct(os.stat(os.path.join(STATE, "session.json")).st_mode & 0o777), "0o600")
        srv.drop_session()
        code, d, _ = call("POST", "/v1/login", {"token": "xoxp-bad"})
        self.assertEqual((code, d["error"]), (403, "invalid_auth"))       # 401 is this door's own token gate
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])
        for t in ("not-a-token", "xoxb-bot", "xoxc-browser"):                # only the owner's user token
            self.assertEqual(call("POST", "/v1/login", {"token": t})[0], 400, t)
        self.assertEqual(oct(os.stat(os.path.join(STATE, "api-token")).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(STATE).st_mode & 0o777) in ("0o700", "0o755"), True)

    def test_a_get_sends_no_body_type_and_a_post_sends_json(self):
        self.sign_in()
        HEADERS.clear()
        call("GET", "/v1/conversations/C0000001")
        call("POST", "/v1/conversations/C0000001/messages", {"text": "hi"})
        self.assertEqual(HEADERS, [("GET", "conversations.history", None),
                                   ("POST", "chat.postMessage", "application/json; charset=utf-8")])

    def test_list_follows_the_cursor_kinds_each_in_slacks_order(self):
        self.sign_in()
        code, d, _ = call("GET", "/v1/conversations")
        self.assertEqual(code, 200, d)
        self.assertEqual([(c["id"], c["name"], c["kind"]) for c in d["conversations"]],
                         [("C0000001", "general", "channel"), ("G0000002", "board", "private"), ("D0000003", "U9", "dm")])
        self.assertEqual((d["count"], d["more"]), (3, False))
        self.assertEqual([c[2].get("cursor") for c in CALLS if c[1] == "users.conversations"], [None, "page2"])
        code, d, _ = call("GET", "/v1/conversations?limit=2")                # fewer than there are: said
        self.assertEqual((d["count"], d["more"]), (2, True))

    def test_history_oldest_first_and_slacks_own_error_names(self):
        self.sign_in()
        code, d, _ = call("GET", "/v1/conversations/C0000001?limit=5")
        self.assertEqual([(m["text"], m["ts"]) for m in d["messages"]],
                         [("שלום", "1700000001.000100"), ("second", "1700000002.000200")])
        code, d, _ = call("GET", "/v1/conversations/C0000009")
        self.assertEqual((code, d["error"]), (403, "not_in_channel"))

    def test_send_and_mark_post_what_slack_wants_and_bad_ids_are_refused_first(self):
        self.sign_in()
        CALLS.clear()
        code, d, _ = call("POST", "/v1/conversations/C0000001/messages", {"text": "hi"})
        self.assertEqual((code, d["id"]), (200, "1700000003.000300"))
        self.assertEqual(CALLS[-1][1:], ("chat.postMessage", {"channel": "C0000001", "text": "hi"}))
        code, _, _ = call("POST", "/v1/conversations/C0000001/read", {"ts": "1700000002.000200"})
        self.assertEqual(code, 200)
        self.assertEqual(CALLS[-1][1:], ("conversations.mark", {"channel": "C0000001", "ts": "1700000002.000200"}))
        CALLS.clear()
        for method, path, body in (("GET", "/v1/conversations/general", None),
                                   ("POST", "/v1/conversations/C0000001/read", {"ts": "yesterday"}),
                                   ("POST", "/v1/conversations/C0000001/messages", {"text": " "})):
            self.assertEqual(call(method, path, body)[0], 400, path)
        self.assertEqual(CALLS, [])

    def test_a_rate_limit_says_how_long_to_wait(self):
        self.sign_in()
        RATE_LIMIT["on"] = True
        code, d, headers = call("GET", "/v1/conversations")
        self.assertEqual((code, d["error"], headers.get("Retry-After")), (429, "ratelimited", "7"))

    def test_a_revoked_token_signs_the_adapter_out(self):
        self.sign_in()
        with open(os.path.join(STATE, "session.json")) as f:
            s = json.load(f)
        s["token"] = "xoxp-revoked"                    # the owner revoked it in his Slack app
        srv._write_private("session.json", json.dumps(s))
        code, d, _ = call("GET", "/v1/conversations")
        self.assertEqual((code, d["error"]), (409, "signed-out"))
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])

    def test_the_flow_says_what_was_done_and_never_the_text_or_a_token(self):
        EMITTED.clear()
        self.sign_in()
        call("POST", "/v1/conversations/C0000001/messages", {"text": "סוד גדול"})
        call("POST", "/v1/conversations/C0000001/read", {"ts": "1700000002.000200"})
        call("POST", "/v1/logout")
        call("POST", "/v1/logout")                       # nothing was held: nothing to say
        self.assertEqual([(a, t) for a, t, _, _ in EMITTED],
                         [("slack", "account.signed_in"), ("slack", "message.sent"),
                          ("slack", "conversation.read"), ("slack", "account.signed_out")])
        blob = json.dumps(EMITTED, ensure_ascii=False)
        self.assertNotIn("סוד גדול", blob)
        self.assertNotIn("xoxp-", blob)

    def test_a_publisher_that_fails_never_fails_the_request(self):
        def boom(*a, **k):
            raise RuntimeError("redis is away")
        keep, _fp.emit = _fp.emit, boom
        try:
            self.sign_in()
            code, d, _ = call("POST", "/v1/conversations/C0000001/messages", {"text": "hi"})
            self.assertEqual(code, 200, d)
        finally:
            _fp.emit = keep

    def test_signed_out_is_said_and_logout_only_forgets(self):
        code, d, _ = call("GET", "/v1/conversations")
        self.assertEqual((code, d["error"]), (409, "signed-out"))
        self.sign_in()
        CALLS.clear()
        self.assertEqual(call("POST", "/v1/logout")[0], 200)
        self.assertEqual(CALLS, [])
        self.assertFalse(call("GET", "/v1/health", token=None)[1]["signed_in"])


if __name__ == "__main__":
    unittest.main()
