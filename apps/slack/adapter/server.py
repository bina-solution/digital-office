"""slack adapter — the headless side of «סלאק»: Slack's Web API behind chat.v1 (DGO-1264).

The screen is Slack's own Linux client under Selkies (Dockerfile.desktop). This container is the CLI's and the
API's door, and it speaks Slack's official Web API (api.slack.com/methods) with a USER token: the owner
installs a Slack app in his workspace once and gives its user token here (`./bbox slack login --token-stdin`).
The token lives in this app's volume, never in a log or an answer. The office never reads Slack's own files.

The contract is chat.v1 as chat's backends implement it (apps/chat/chatapi/adapters/index.js, CANONICAL_OPS):

    GET  /v1/health                              up, signed in, which workspace (no token needed)
    POST /v1/login      {token}                  checked with auth.test before it is kept
    POST /v1/logout                              the token is forgotten (Slack's own sign-in is untouched)
    GET  /v1/conversations?limit=N               listConversations: channels, private channels, DMs
    GET  /v1/conversations/<channel>?limit=N     getConversation: the last N messages, oldest first
    POST /v1/conversations/<channel>/messages {text}   sendMessage (chat.postMessage, as the owner)
    POST /v1/conversations/<channel>/read {ts}         markRead (conversations.mark)

Slack answers HTTP 200 with {"ok": false, "error": "…"} for most failures; that error is passed on as it is
(invalid_auth, not_in_channel, missing_scope…). A 429 says how long to wait (Retry-After), and so does this
door. Every call but /v1/health carries the app's bearer token: any container on the office network can reach
this port, and a message sent here goes out as the owner.

Standard library only (python:3.12-slim in the image; the tests run on 3.9 too).
"""
import json
import os
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# THE FLOW (flow.v1, dgo:flow:slack): what this adapter DID — a sign-in, a sign-out, a message sent, a
# conversation read — through the office's one publisher (platform-base/redis/flowpub.py, mounted read-only at
# /opt/dgo). Never a message's text and never a token: every agent of the office reads the stream. Without the
# mount (a test, a shell) it publishes nothing and never fails a request.
try:
    sys.path.insert(0, "/opt/dgo")
    import flowpub  # noqa: E402
except ImportError:
    flowpub = None


def flow(type_, title, data=None):
    if flowpub is not None:
        try:
            flowpub.emit("slack", type_, title, data=data or {})
        except Exception:                            # noqa: BLE001 — the stream never costs a request
            pass

PORT = int(os.environ.get("SLACK_ADAPTER_PORT", "3094"))
STATE = os.environ.get("SLACK_STATE", "/data/adapter")
API = os.environ.get("SLACK_API", "https://slack.com/api").rstrip("/")
TIMEOUT = int(os.environ.get("SLACK_HTTP_TIMEOUT", "30"))
VERSION = "0.1.0"
CHANNEL = re.compile(r"[CDG][A-Z0-9]{6,20}")
TS = re.compile(r"\d{9,11}\.\d{6}")
_lock = threading.Lock()


class Fail(Exception):
    def __init__(self, code, error, detail="", retry_after=None):
        super().__init__(detail or error)
        self.code, self.error, self.detail, self.retry_after = code, error, detail, retry_after


def _path(name):
    return os.path.join(STATE, name)


def _write_private(name, text):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    tmp = _path(name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, _path(name))


def api_token():
    """The bearer every call but /v1/health carries: minted once, kept in the volume, read by the hooks."""
    try:
        with open(_path("api-token")) as f:
            t = f.read().strip()
        if t:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    _write_private("api-token", t)
    return t


def session():
    try:
        with open(_path("session.json")) as f:
            s = json.load(f)
        return s if isinstance(s, dict) and s.get("token") else None
    except (OSError, ValueError):
        return None


def drop_session():
    try:
        os.remove(_path("session.json"))
    except OSError:
        pass


# ── Slack ──────────────────────────────────────────────────────────────────────────────────────
def slack(method, token, params=None, post=False):
    """One Web API call. Slack's own error comes back as Fail with its name, never as a traceback."""
    data, url = None, f"{API}/{method}"
    if post:
        data = json.dumps(params or {}).encode()
    elif params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": "Bearer " + token}
    if post:                                   # a GET carries its arguments in the query and no body type
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method="POST" if post else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise Fail(429, "ratelimited", "Slack asks to wait", e.headers.get("Retry-After") or "30")
        raise Fail(502 if e.code >= 500 else e.code, f"http-{e.code}", f"Slack answered {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Fail(504, "unreachable", f"Slack did not answer ({getattr(e, 'reason', e)})")
    except ValueError:
        raise Fail(502, "bad-answer", "Slack answered something that is not JSON")
    if not d.get("ok"):
        err = d.get("error") or "unknown"
        if err in ("invalid_auth", "token_revoked", "token_expired", "account_inactive"):
            # the kept token no longer works (revoked in the Slack app, the app uninstalled): this adapter is
            # signed out, and says so — /v1/health stops claiming a token Slack no longer honours. Checked
            # again INSIDE the lock, so a login that lands meanwhile is never the one dropped.
            with _lock:
                s = session()
                dead = bool(s) and s.get("token") == token
                if dead:
                    drop_session()
            if dead:
                raise Fail(409, "signed-out", f"Slack no longer accepts the token ({err}) — `./bbox slack login`")
        # 401 is this door's own bearer gate: Slack refusing a token is 403, with Slack's own name for why
        code = 403 if err in ("invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive",
                              "missing_scope", "not_in_channel", "channel_not_found", "is_archived") else 400
        raise Fail(code, err, (d.get("needed") and f"needs scope {d['needed']}") or "")
    return d


def signed_in():
    s = session()
    if not s:
        raise Fail(409, "signed-out", "no token yet — `./bbox slack login --token-stdin`")
    return s


def login(body):
    token = str(body.get("token") or "").strip()
    # the owner's USER token, plain or rotating. A bot token (xoxb-) would not act as the owner, and a browser
    # session token (xoxc-) works only with the browser's cookie, which this door never holds.
    if not token.startswith(("xoxp-", "xoxe.xoxp-")):
        raise Fail(400, "token", "the owner's Slack USER token: xoxp-… (or a rotating xoxe.xoxp-…)")
    who = slack("auth.test", token, post=True)
    s = {"token": token, "user_id": who.get("user_id"), "user": who.get("user"), "team": who.get("team"),
         "team_id": who.get("team_id"), "url": who.get("url"),
         "kind": "rotating user" if token.startswith("xoxe.") else "user"}
    with _lock:
        _write_private("session.json", json.dumps(s))
    flow("account.signed_in", "הלשכה נכנסה ל-Slack", {"user_id": s["user_id"], "team_id": s["team_id"],
                                                     "kind": s["kind"]})
    return {"ok": True, "user": s["user"], "team": s["team"], "url": s["url"], "kind": s["kind"]}


def logout():
    with _lock:
        s = session()
        drop_session()                       # the token is the owner's app's: forgetting it is ours, revoking it his
    if s:
        flow("account.signed_out", "הלשכה שכחה את האסימון של Slack", {"user_id": s.get("user_id"),
                                                                     "team_id": s.get("team_id")})
    return {"ok": True, "forgotten": bool(s)}


def list_conversations(limit):
    """The conversations in SLACK'S order, as users.conversations pages them. Not by recency: the list carries
    no last-message time (that is one conversations.history call per conversation), and a sort on what it
    does carry would be a claim it cannot keep."""
    s = signed_in()
    out, cursor = [], None
    while len(out) < limit:
        p = {"types": "public_channel,private_channel,mpim,im", "exclude_archived": "true",
             "limit": str(min(200, limit - len(out)))}
        if cursor:
            p["cursor"] = cursor
        d = slack("users.conversations", s["token"], p)
        for c in d.get("channels") or []:
            kind = "dm" if c.get("is_im") else "group-dm" if c.get("is_mpim") else \
                "private" if c.get("is_private") else "channel"
            out.append({"id": c.get("id"), "name": c.get("name") or c.get("user") or c.get("id"), "kind": kind,
                        "encrypted": False})
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    shown = out[:limit]
    return {"conversations": shown, "count": len(shown), "more": bool(cursor) or len(out) > limit}


def channel_of(cid):
    cid = urllib.parse.unquote(cid)
    if not CHANNEL.fullmatch(cid):
        raise Fail(400, "channel", "not a Slack conversation id (C…, G… or D…)")
    return cid


def get_conversation(cid, limit):
    s = signed_in()
    d = slack("conversations.history", s["token"], {"channel": cid, "limit": str(limit)})
    msgs = [{"id": m.get("ts"), "from": m.get("user") or m.get("bot_id") or m.get("username"),
             "ts": m.get("ts"), "kind": m.get("subtype") or "message", "text": m.get("text"), "encrypted": False}
            for m in d.get("messages") or [] if m.get("type") == "message"]
    msgs.reverse()                                       # oldest first, as a conversation reads
    return {"id": cid, "messages": msgs}


def send_message(cid, body):
    s = signed_in()
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise Fail(400, "text", "text is required")
    d = slack("chat.postMessage", s["token"], {"channel": cid, "text": text}, post=True)
    flow("message.sent", "נשלחה הודעה בשיחה", {"channel": cid, "ts": d.get("ts")})          # never the text
    return {"ok": True, "id": d.get("ts")}


def mark_read(cid, body):
    s = signed_in()
    ts = str(body.get("ts") or body.get("event_id") or "")
    if not TS.fullmatch(ts):
        raise Fail(400, "ts", "ts is required (a Slack message timestamp, 1700000000.000100)")
    slack("conversations.mark", s["token"], {"channel": cid, "ts": ts}, post=True)
    flow("conversation.read", "שיחה סומנה כנקראה", {"channel": cid, "ts": ts})
    return {"ok": True}


def health(deep=False):
    """`deep`: ask Slack (auth.test) whether the kept token still works — a revoked one is then noticed here,
    not on the next real call. Without it, the answer is what this door holds."""
    s = session()
    if s and deep:
        try:
            slack("auth.test", s["token"], post=True)
        except Fail:
            pass                                   # a dead token has just been dropped (slack() above)
        s = session()
    return {"ok": True, "app": "slack", "version": VERSION, "signed_in": bool(s),
            "user": s and s.get("user"), "team": s and s.get("team"), "kind": s and s.get("kind")}


def limit_of(q, default=20, top=200):
    try:
        return max(1, min(top, int((q.get("limit") or [default])[0])))
    except ValueError:
        raise Fail(400, "limit", "limit is a number")


class Door(BaseHTTPRequestHandler):
    server_version = "slack-adapter/" + VERSION

    def log_message(self, fmt, *args):            # no request line in the log: a channel id names people
        pass

    def answer(self, code, doc, retry_after=None):
        b = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise Fail(400, "length", "Content-Length is a number")
        if n < 0:
            raise Fail(400, "length", "Content-Length is not negative")
        if n > 1 << 20:
            raise Fail(413, "too-large", "the body is over 1 MB")
        raw = self.rfile.read(n) if n else b""
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            raise Fail(400, "bad-json", "the body is not JSON")
        if not isinstance(d, dict):
            raise Fail(400, "bad-json", "the body is a JSON object")
        return d

    def authorized(self):
        m = re.match(r"^Bearer\s+(.+)$", self.headers.get("Authorization") or "", re.I)
        if not m:
            return False
        try:                                       # bytes: a non-ASCII bearer is a wrong bearer, not a 500
            return secrets.compare_digest(m.group(1).strip().encode("utf-8"), api_token().encode("utf-8"))
        except (TypeError, ValueError):
            return False

    def route(self, method):
        u = urllib.parse.urlsplit(self.path)
        p, q = u.path.rstrip("/") or "/", urllib.parse.parse_qs(u.query)
        if method == "GET" and p == "/v1/health":
            # ?deep=1 asks Slack, and only for a caller with the token: the open probe never spends Slack's quota
            deep = (q.get("deep") or [""])[0] in ("1", "true") and self.authorized()
            return self.answer(200, health(deep))
        if not self.authorized():
            raise Fail(401, "token", "missing or wrong bearer token")
        if method == "POST" and p == "/v1/login":
            return self.answer(200, login(self.body()))
        if method == "POST" and p == "/v1/logout":
            return self.answer(200, logout())
        if method == "GET" and p == "/v1/conversations":
            return self.answer(200, list_conversations(limit_of(q, 100, 1000)))
        m = re.fullmatch(r"/v1/conversations/([^/]+)(/messages|/read)?", p)
        if m:
            cid = channel_of(m.group(1))
            if method == "GET" and not m.group(2):
                return self.answer(200, get_conversation(cid, limit_of(q)))
            if method == "POST" and m.group(2) == "/messages":
                return self.answer(200, send_message(cid, self.body()))
            if method == "POST" and m.group(2) == "/read":
                return self.answer(200, mark_read(cid, self.body()))
        raise Fail(404, "not-found", f"no {method} {p}")

    def handle_one(self, method):
        try:
            self.route(method)
        except Fail as e:
            doc = {"ok": False, "error": e.error, "detail": e.detail}
            if e.retry_after:
                doc["retry_after"] = e.retry_after          # in the body too: a caller reading JSON sees the wait
            self.answer(e.code, doc, e.retry_after)
        except Exception as e:                      # noqa: BLE001 — a bug is said, the door stays up
            print(f"slack adapter: {method} {urllib.parse.urlsplit(self.path).path}: {type(e).__name__}", file=sys.stderr)
            self.answer(500, {"ok": False, "error": "internal", "detail": type(e).__name__})

    def do_GET(self):
        self.handle_one("GET")

    def do_POST(self):
        self.handle_one("POST")


def main():
    api_token()
    print(f"slack adapter {VERSION} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Door).serve_forever()


if __name__ == "__main__":
    main()
