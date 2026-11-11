"""element adapter — the headless side of «אלמנט»: the Matrix client-server API behind chat.v1 (DGO-1264).

The screen is Element Desktop under Selkies (Dockerfile.desktop). This container is the CLI's and the API's
door. It holds its OWN Matrix device: Element Desktop keeps its session encrypted in its own store, and the
office never reads a vendor's files (ai/context/wrapped-official-app.md). So the owner signs this device in
once, with a password or with an access token he copies from Element, and the token lives in this app's
volume, never in a log or an answer.

The contract is chat.v1 as chat's backends implement it (apps/chat/chatapi/adapters/index.js, CANONICAL_OPS):

    GET  /v1/health                              up, signed in, which account (no token needed)
    POST /v1/login      {homeserver, user, password} | {homeserver, access_token}
    POST /v1/logout                              this device signs out (the screen's sign-in is untouched)
    GET  /v1/conversations?limit=N               listConversations: the joined rooms, newest first
    GET  /v1/conversations/<room>?limit=N        getConversation: the room's last N messages
    POST /v1/conversations/<room>/messages {text}   sendMessage
    POST /v1/conversations/<room>/read {event_id}   markRead

What it does NOT do, on purpose. It does not decrypt: an encrypted room's messages arrive as «encrypted», and
a message into an encrypted room is refused (409): sending plain text into it would show every member an
unencrypted message. Those rooms are read and written on the screen. Every call but /v1/health carries the
app's bearer token (minted into the volume on first start, as bina-claude's adapter does): any container on
the office network can reach this port, and a message sent here goes out as the owner.

Standard library only (python:3.12-slim in the image; the tests run on 3.9 too).
"""
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# THE FLOW (flow.v1, dgo:flow:element): what this adapter DID — a sign-in, a sign-out, a message sent, a room
# read — through the office's one publisher (platform-base/redis/flowpub.py, mounted read-only at /opt/dgo). Never
# a message's text and never a token: every agent of the office reads the stream. Without the mount (a test, a
# shell) it publishes nothing and never fails a request.
try:
    sys.path.insert(0, "/opt/dgo")
    import flowpub  # noqa: E402
except ImportError:
    flowpub = None


def flow(type_, title, data=None):
    if flowpub is not None:
        try:
            flowpub.emit("element", type_, title, data=data or {})
        except Exception:                            # noqa: BLE001 — the stream never costs a request
            pass


PORT = int(os.environ.get("ELEMENT_ADAPTER_PORT", "3093"))
STATE = os.environ.get("ELEMENT_STATE", "/data/adapter")
DEVICE_NAME = os.environ.get("ELEMENT_DEVICE_NAME", "Digital Office")
TIMEOUT = int(os.environ.get("ELEMENT_HTTP_TIMEOUT", "30"))
VERSION = "0.1.0"
# Room and event ids are OPAQUE to a client (the spec): a version-12 room has no server part, a server name can
# be an IPv6 literal with a port. So only the sigil is checked, and nothing a URL or a log line could be hurt by.
ROOM = re.compile(r"![^\x00-\x20\x7f]{1,255}")
EVENT = re.compile(r"\$[^\x00-\x20\x7f]{1,255}")
LOCAL = re.compile(r"^http://(localhost|127\.\d+\.\d+\.\d+|\[::1\])(:\d+)?$")
_lock = threading.Lock()


class Fail(Exception):
    def __init__(self, code, error, detail=""):
        super().__init__(detail or error)
        self.code, self.error, self.detail = code, error, detail


# ── the app's own state: its bearer token and its Matrix session ───────────────────────────────────
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
        return s if isinstance(s, dict) and s.get("access_token") and s.get("homeserver") else None
    except (OSError, ValueError):
        return None


def save_session(s):
    _write_private("session.json", json.dumps(s))


def drop_session():
    try:
        os.remove(_path("session.json"))
    except OSError:
        pass


# ── Matrix ─────────────────────────────────────────────────────────────────────────────────────
def homeserver_url(h):
    """The client-server base URL. A bare server name (example.org) is resolved the spec's way, through
    https://<name>/.well-known/matrix/client. Plain http is refused off this machine: a password would cross
    the network in clear."""
    h = str(h or "").strip().rstrip("/")
    if not h:
        raise Fail(400, "homeserver", "homeserver is required (matrix.example.org or https://matrix.example.org)")
    if h.startswith("http://") and not LOCAL.match(h):
        raise Fail(400, "homeserver", "plain http is refused: use https://")
    if re.match(r"^https?://", h):
        return h
    try:
        with urllib.request.urlopen(f"https://{h}/.well-known/matrix/client", timeout=TIMEOUT) as r:
            base = str((json.loads(r.read() or b"{}").get("m.homeserver") or {}).get("base_url") or "").rstrip("/")
        if base.startswith("https://"):
            return base
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
        pass
    return "https://" + h


def mx(hs, method, path, body=None, token=None, query=None):
    """One client-server call. A Matrix error comes back as Fail with its errcode, never as a traceback."""
    url = hs + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except ValueError:
            j = {}
        errcode = j.get("errcode") or f"http-{e.code}"
        if token and errcode == "M_UNKNOWN_TOKEN" and session() and session().get("access_token") == token:
            # the device was removed (in Element's own settings) or its token expired: this device is signed out,
            # and says so — /v1/health stops claiming a session the homeserver no longer honours
            with _lock:
                drop_session()
            raise Fail(409, "signed-out", "the homeserver no longer accepts this device's token — sign in again")
        code = 403 if e.code == 401 else 502 if e.code >= 500 else e.code      # 401 is the bearer gate's own
        raise Fail(code, errcode, j.get("error") or f"the homeserver answered {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Fail(504, "unreachable", f"the homeserver did not answer ({getattr(e, 'reason', e)})")
    except ValueError:
        raise Fail(502, "bad-answer", "the homeserver answered something that is not JSON")


def signed_in():
    s = session()
    if not s:
        raise Fail(409, "signed-out", "this device is not signed in — `./bbox element login`")
    return s


def login(body):
    hs = homeserver_url(body.get("homeserver"))
    if body.get("access_token"):
        token = str(body["access_token"]).strip()
        who = mx(hs, "GET", "/_matrix/client/v3/account/whoami", token=token)
        s = {"homeserver": hs, "access_token": token, "user_id": who.get("user_id"),
             "device_id": who.get("device_id"), "how": "token"}
    else:
        user, password = str(body.get("user") or "").strip(), body.get("password")
        if not user or not password:
            raise Fail(400, "credentials", "user and password, or access_token")
        r = mx(hs, "POST", "/_matrix/client/v3/login",
               {"type": "m.login.password", "identifier": {"type": "m.id.user", "user": user},
                "password": password, "initial_device_display_name": DEVICE_NAME})
        s = {"homeserver": hs, "access_token": r.get("access_token"), "user_id": r.get("user_id"),
             "device_id": r.get("device_id"), "how": "password"}
        if not s["access_token"]:
            raise Fail(502, "bad-answer", "the homeserver signed in but returned no access token")
    old = session()
    with _lock:
        save_session(s)
    if old and old.get("how") == "password" and old.get("access_token") != s["access_token"]:
        _sign_out(old)                   # a second sign-in must not leave the first device alive and forgotten
    flow("account.signed_in", "המכשיר של הלשכה נכנס ל-Matrix", {"user_id": s["user_id"], "how": s["how"]})
    return {"ok": True, "user_id": s["user_id"], "device_id": s["device_id"], "homeserver": hs}


def _sign_out(s):
    """Sign out a device THIS app signed in (by password). None, or why the homeserver did not do it."""
    try:
        mx(s["homeserver"], "POST", "/_matrix/client/v3/logout", {}, token=s["access_token"])
        return None
    except Fail as e:
        return f"{e.error}: {e.detail}" if e.error != "signed-out" else None


def logout():
    s = session()
    why = None
    if s and s.get("how") == "password":       # a token the owner copied belongs to his other device: keep it alive
        why = _sign_out(s)
    with _lock:
        drop_session()
    out = {"ok": True, "forgotten": bool(s)}
    if why:                                    # said, never hidden: the device may still be live on the account
        out.update({"signed_out_on_server": False, "detail": why + " — remove the device in Element's settings"})
    if s:
        # what happened, exactly: the adapter forgot the device; whether the SERVER signed it out too is its own fact
        # (a copied token is kept alive by design, and a sign-out the server refused leaves the device live)
        flow("account.signed_out", "הלשכה שכחה את המכשיר שלה ב-Matrix",
             {"user_id": s.get("user_id"), "how": s.get("how"),
              "on_server": s.get("how") == "password" and not why})
    return out


SYNC_FILTER = json.dumps({
    "presence": {"not_types": ["*"]}, "account_data": {"not_types": ["*"]},
    "room": {"timeline": {"limit": 1},
             "state": {"types": ["m.room.name", "m.room.canonical_alias", "m.room.encryption"], "lazy_load_members": True},
             "ephemeral": {"not_types": ["*"]}, "account_data": {"not_types": ["*"]}},
})


def list_conversations(limit):
    s = signed_in()
    r = mx(s["homeserver"], "GET", "/_matrix/client/v3/sync", token=s["access_token"],
           query={"filter": SYNC_FILTER, "timeout": "0"})
    out = []
    for rid, room in ((r.get("rooms") or {}).get("join") or {}).items():
        state = ((room.get("state") or {}).get("events") or []) + ((room.get("timeline") or {}).get("events") or [])
        name = alias = None
        encrypted = False
        for ev in state:
            t = ev.get("type")
            if t == "m.room.name":
                name = (ev.get("content") or {}).get("name") or name
            elif t == "m.room.canonical_alias":
                alias = (ev.get("content") or {}).get("alias") or alias
            elif t == "m.room.encryption":
                encrypted = True
        last = ((room.get("timeline") or {}).get("events") or [{}])[-1]
        # a direct chat has neither a name nor an alias: it is called by its members (the room summary's heroes)
        heroes = ", ".join(str(h) for h in ((room.get("summary") or {}).get("m.heroes") or [])[:3])
        out.append({"id": rid, "name": name or alias or heroes or rid, "encrypted": encrypted,
                    "unread": ((room.get("unread_notifications") or {}).get("notification_count") or 0),
                    "last_ts": last.get("origin_server_ts") or 0})
    out.sort(key=lambda c: -c["last_ts"])
    return {"conversations": out[:limit], "count": len(out)}


def room_of(rid):
    rid = urllib.parse.unquote(rid)
    if not ROOM.fullmatch(rid):
        raise Fail(400, "room", "not a Matrix room id (it starts with !)")
    return rid


def is_encrypted(s, rid):
    try:
        mx(s["homeserver"], "GET", f"/_matrix/client/v3/rooms/{urllib.parse.quote(rid, safe='')}/state/m.room.encryption/",
           token=s["access_token"])
        return True
    except Fail as e:
        if e.error == "M_NOT_FOUND":
            return False
        raise


def get_conversation(rid, limit):
    s = signed_in()
    r = mx(s["homeserver"], "GET", f"/_matrix/client/v3/rooms/{urllib.parse.quote(rid, safe='')}/messages",
           token=s["access_token"],
           query={"dir": "b", "limit": str(limit),        # N MESSAGES, not N events of any kind
                  "filter": json.dumps({"types": ["m.room.message", "m.room.encrypted"]})})
    msgs = []
    for ev in r.get("chunk") or []:
        t = ev.get("type")
        if t not in ("m.room.message", "m.room.encrypted"):
            continue
        c = ev.get("content") or {}
        msgs.append({"id": ev.get("event_id"), "from": ev.get("sender"), "ts": ev.get("origin_server_ts"),
                     "encrypted": t == "m.room.encrypted",
                     "kind": c.get("msgtype") if t == "m.room.message" else None,
                     "text": c.get("body") if t == "m.room.message" else None})
    msgs.reverse()                                   # oldest first, as a conversation reads
    return {"id": rid, "messages": msgs}


def send_message(rid, body):
    s = signed_in()
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise Fail(400, "text", "text is required")
    if is_encrypted(s, rid):
        raise Fail(409, "encrypted-room", "the room is end-to-end encrypted: send from the screen (the tile)")
    txn = f"dgo{int(time.time() * 1000)}{secrets.token_hex(4)}"
    r = mx(s["homeserver"], "PUT", f"/_matrix/client/v3/rooms/{urllib.parse.quote(rid, safe='')}/send/m.room.message/{txn}",
           {"msgtype": "m.text", "body": text}, token=s["access_token"])
    flow("message.sent", "נשלחה הודעה בחדר", {"room": rid, "event_id": r.get("event_id")})   # never the text
    return {"ok": True, "id": r.get("event_id")}


def mark_read(rid, body):
    s = signed_in()
    eid = str(body.get("event_id") or "")
    if not EVENT.fullmatch(eid):
        raise Fail(400, "event", "event_id is required ($opaque)")
    mx(s["homeserver"], "POST", f"/_matrix/client/v3/rooms/{urllib.parse.quote(rid, safe='')}/receipt/m.read/"
       f"{urllib.parse.quote(eid, safe='')}", {}, token=s["access_token"])
    flow("conversation.read", "חדר סומן כנקרא", {"room": rid, "event_id": eid})
    return {"ok": True}


def health():
    s = session()
    return {"ok": True, "app": "element", "version": VERSION, "signed_in": bool(s),
            "user_id": s and s.get("user_id"), "device_id": s and s.get("device_id"),
            "homeserver": s and s.get("homeserver")}


def limit_of(q, default=20, top=100):
    try:
        return max(1, min(top, int((q.get("limit") or [default])[0])))
    except ValueError:
        raise Fail(400, "limit", "limit is a number")


class Door(BaseHTTPRequestHandler):
    server_version = "element-adapter/" + VERSION

    def log_message(self, fmt, *args):            # no request line in the log: a room id names people
        pass

    def answer(self, code, doc):
        b = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
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
            return self.answer(200, health())
        if not self.authorized():
            raise Fail(401, "token", "missing or wrong bearer token")
        if method == "POST" and p == "/v1/login":
            return self.answer(200, login(self.body()))
        if method == "POST" and p == "/v1/logout":
            return self.answer(200, logout())
        if method == "GET" and p == "/v1/conversations":
            return self.answer(200, list_conversations(limit_of(q, 50, 200)))
        m = re.fullmatch(r"/v1/conversations/([^/]+)(/messages|/read)?", p)
        if m:
            rid = room_of(m.group(1))
            if method == "GET" and not m.group(2):
                return self.answer(200, get_conversation(rid, limit_of(q)))
            if method == "POST" and m.group(2) == "/messages":
                return self.answer(200, send_message(rid, self.body()))
            if method == "POST" and m.group(2) == "/read":
                return self.answer(200, mark_read(rid, self.body()))
        raise Fail(404, "not-found", f"no {method} {p}")

    def handle_one(self, method):
        try:
            self.route(method)
        except Fail as e:
            self.answer(e.code, {"ok": False, "error": e.error, "detail": e.detail})
        except Exception as e:                      # noqa: BLE001 — a bug is said, the door stays up
            print(f"element adapter: {method} {urllib.parse.urlsplit(self.path).path}: {type(e).__name__}", file=sys.stderr)
            self.answer(500, {"ok": False, "error": "internal", "detail": type(e).__name__})

    def do_GET(self):
        self.handle_one("GET")

    def do_POST(self):
        self.handle_one("POST")


def main():
    api_token()
    print(f"element adapter {VERSION} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Door).serve_forever()


if __name__ == "__main__":
    main()
