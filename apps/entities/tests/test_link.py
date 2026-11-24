"""«ישויות» opened from a LINKED office (DGO-2135): the person the link's door signed, behind the office's real door.

The owner, signed in on vps1, opened the HP's «ישויות» from vps1's console and read «הכניסה שלך ללשכה לא אומתה»: his
browser carried vps1's cookie, which the HP's sign-in cannot vouch for, and the door (platform-base/forward-auth/
signin.py) believed nothing else. This test runs the real app behind that door, with the link's door at its own
address (127.0.0.2; any other container is 127.0.0.3) and a vault that holds the pair's secret:

  * a request from the door, signed by it for vps1's owner (a herd office), reads the screen and the API, and a
    change it makes is named `akadmin@vps1`;
  * from the door: a signature made with another secret, a tampered user, a stale one, another office's, none at
    all, a bare cookie of another office — 401, with the link's reason; a vault that does not answer — 401; a
    signed person of an office that is not the herd's — 403 (a person, not an admin);
  * from any other container: a VALID signature is not believed (any container can read a pair's secret from the
    vault today), and a bare cookie of another office is no session — 401;
  * a local session behaves as before (an admin 200, a non-admin 403), and an owner whose group is forward-auth's
    second name for admins (`authentik-admins`, the HP's) is an admin.

    python3 apps/entities/tests/test_link.py     (in the app's image: fastapi + uvicorn; signin.py and
                                                  link_identity.py on the path)
"""
from __future__ import annotations

import http.client
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.update(ENTITIES_DATA=tempfile.mkdtemp(prefix="entities-link-"), ENTITIES_API_TOKEN="tok-test",
                  ENTITIES_TRUST_LOOPBACK="0", no_proxy="127.0.0.1,localhost", NO_PROXY="127.0.0.1,localhost")
sys.path.insert(0, str(HERE.parent))
for _up in HERE.parents:              # the tree's copies; in the app's image, /opt/dgo's (the app puts it on the path)
    if (_up / "platform-base" / "forward-auth" / "signin.py").is_file():
        sys.path.insert(0, str(_up / "platform-base" / "forward-auth"))
        sys.path.append(str(_up / "platform-base" / "connections"))   # last: the vault's own app.py is not this app
        break
else:
    sys.path.insert(0, "/opt/dgo")

FAIL: list = []
DOOR, OTHER = "127.0.0.2", "127.0.0.3"
SECRET = "the-pair-secret-of-vps1"


def check(cond, what):
    if not cond:
        FAIL.append(what)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(handler) -> int:
    p = free_port()
    threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", p), handler).serve_forever,
                     daemon=True).start()
    return p


class WhoAmI(http.server.BaseHTTPRequestHandler):
    """forward-auth's /whoami: this office's sessions; vps1's cookie is none of them (401)."""

    def do_GET(self):
        who = {"dgo_session=admin": ("owner", ["admins"]), "dgo_session=staff": ("staff", []),
               "dgo_session=migrated": ("akadmin", ["authentik-admins"])}.get(self.headers.get("Cookie", ""))
        if not who:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"signed_in": True, "username": who[0], "groups": who[1]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


VAULT_UP = threading.Event()


class Vault(http.server.BaseHTTPRequestHandler):
    """The credential plane, as link_identity.link_secret reads it: the pair `dgo_link-vps1` and its secret."""

    def do_GET(self):
        if not VAULT_UP.is_set():
            self.send_response(503)
            self.end_headers()
            return
        if self.path.startswith("/api/instances?"):
            body = {"instances": [{"id": "dgo_link-vps1", "account_hint": ""}]}
        elif self.path == "/api/instances/dgo_link-vps1/secret":
            body = {"secret": {"token": SECRET}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


os.environ["ENTITIES_WHOAMI_URL"] = f"http://127.0.0.1:{serve(WhoAmI)}/whoami"
VAULT = f"http://127.0.0.1:{serve(Vault)}"

import link_identity as linkid  # noqa: E402
import signin  # noqa: E402

# the app builds its door at import, and the door its Link from the office (DEPLOYMENT_NAME): here the door is
# 127.0.0.2 and the vault is the one above — everything else is the app's own
_Link = getattr(signin, "Link", None)                     # a door older than DGO-2135 has none: its checks then fail
if _Link:
    signin.Link = lambda: _Link(addresses={DOOR}, vault=VAULT)

import uvicorn  # noqa: E402

import app as entities_app  # noqa: E402

port = free_port()
server = uvicorn.Server(uvicorn.Config(entities_app.app, host="127.0.0.1", port=port, log_level="warning",
                                       proxy_headers=False))   # as the image runs it: `--no-proxy-headers`
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)


def call(method, path, *, frm, headers=None, body=None):
    """One request to the app FROM an address (the door's, or another container's)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10, source_address=(frm, 0))
    h = dict(headers or {})
    data = None
    if body is not None:
        data, h["content-type"] = json.dumps(body).encode(), "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read().decode()
    c.close()
    return r.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw)


def door_headers(office="vps1", user="akadmin", *, secret=SECRET, ts=None, sign_as=None, herd=True, claim=None):
    """What the link's door writes on a request it carries in (apps/dgo-extend/link-proxy.py `Door.rewrite`)."""
    ts = int(time.time()) if ts is None else ts
    h = {"x-authentik-username": user, "x-dgo-office": office, "cookie": "dgo_session=vps1-own-session"}
    if claim is None:
        signed = sign_as or office
        claim = f"v1 {signed} {user} {ts} {linkid.signature(secret, signed, user, ts)}"
    if claim:
        h["x-dgo-identity"] = claim
    if herd:
        h["x-dgo-herd"] = "1"
    return h


# 1. the vault does not answer: a signature cannot be checked, so nobody passes (and nothing is remembered)
s, page = call("GET", "/", frm=DOOR, headers=door_headers())
check(s == 401 and "אין ללשכה הזו מפתח" in page, f"vault down → 401 with the link's reason: {s} {page[:200]}")
VAULT_UP.set()

# 2. the owner of a herd office, signed by the door: the screen, its reads, and a change named for him
check(call("GET", "/", frm=DOOR, headers=door_headers())[0] == 200, "signed vps1 owner from the door → the screen 200")
s, body = call("GET", "/api/entities", frm=DOOR, headers=door_headers())
check(s == 200, f"signed vps1 owner from the door → the API 200: {s} {body}")
s, made = call("POST", "/api/entities", frm=DOOR, body={"kind": "person", "name": "דנה כהן"},
               headers={**door_headers(), "sec-fetch-site": "same-origin"})
check(s == 200 and made.get("id"), f"signed vps1 owner → a change from the screen: {s} {made}")
ev = call("GET", f"/api/events?entity={made.get('id')}", frm=DOOR, headers=door_headers())[1]
check(isinstance(ev, dict) and ev.get("events") and ev["events"][0]["actor"] == "akadmin@vps1 (המסך)",
      f"the change is named for the person the door signed: {ev}")

s, b = call("POST", "/api/entities", frm=DOOR, body={"kind": "person", "name": "x"},
            headers={**door_headers(), "sec-fetch-site": "cross-site"})
check(s == 403, f"signed vps1 owner, a change sent from another site → 403: {s} {b}")

# 3. from the door, and not proved: 401 with the reason — each its own case — whatever cookie it carries
for what, h, kind in [
    ("a signature made with another secret", door_headers(secret="not-the-pair-secret"), "bad-mac"),
    ("a tampered user", {**door_headers(), "x-dgo-identity": door_headers()["x-dgo-identity"].replace(
        " akadmin ", " intruder ")}, "bad-mac"),
    ("a stale signature", door_headers(ts=int(time.time()) - linkid.SIG_WINDOW - 60), "stale"),
    ("another office's signature", door_headers(sign_as="macbook"), "mismatch"),
    ("no signature at all", door_headers(claim=""), "unsigned"),
    ("a malformed signature", door_headers(claim="v1 vps1 akadmin"), "malformed"),
    ("a bare cookie of another office", {"cookie": "dgo_session=vps1-own-session"}, "unsigned"),
    ("this office's admin cookie, carried by the door", {"cookie": "dgo_session=admin"}, "unsigned"),
]:
    s, b = call("GET", "/api/entities", frm=DOOR, headers=h)
    check(s == 401 and isinstance(b, dict) and str(b.get("detail", "")).endswith(f"({kind})"),
          f"from the door, {what} → 401 ({kind}): {s} {b}")
s, page = call("GET", "/", frm=DOOR, headers=door_headers(secret="not-the-pair-secret"))
check(s == 401 and "אינה נכונה" in page, f"the screen says why a forged signature is refused: {s} {page[:200]}")

# 4. a signed person of an office that is not the herd's: a person here, not an admin
s, page = call("GET", "/", frm=DOOR, headers=door_headers(herd=False))
check(s == 403 and entities_app.WORDS.no_grant in page, f"signed, not the herd's → 403 (no grant): {s}")

# 5. from any other container: the door's headers are not believed — not even a valid signature
check(call("GET", "/api/entities", frm=OTHER, headers=door_headers())[0] == 401,
      "a VALID signature from another container → 401 (only the door's address carries it)")
check(call("GET", "/", frm=OTHER, headers={"cookie": "dgo_session=vps1-own-session"})[0] == 401,
      "a bare cookie of another office → 401")
check(call("GET", "/api/entities", frm=OTHER, headers={**door_headers(), "x-forwarded-for": DOOR})[0] == 401,
      "another container that names the door's address in X-Forwarded-For → 401 (the socket's address counts)")

# 6. a local session, as before — and forward-auth's second name for its admins
check(call("GET", "/", frm=OTHER, headers={"cookie": "dgo_session=admin"})[0] == 200, "a local admin → 200")
check(call("GET", "/api/entities", frm=OTHER, headers={"cookie": "dgo_session=staff"})[0] == 403,
      "a local non-admin → 403")
check(call("GET", "/", frm=OTHER, headers={"cookie": "dgo_session=migrated"})[0] == 200,
      "an owner in `authentik-admins` (the HP's line) → 200")

# 7. who the door is, as the app finds it in an office: `dgo-net-<DEPLOYMENT_NAME>`, asked of the network (stubbed)
answers: dict = {}
asked: list = []


def fake_getaddrinfo(name, *a, **k):
    asked.append(name)
    if any(len(label) > 63 for label in name.split(".")):
        raise UnicodeError("encoding with 'idna' codec failed (UnicodeError: label too long)")   # what the real one does
    if name not in answers:
        raise socket.gaierror("no such name")
    return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in answers[name]]


_real_getaddrinfo, socket.getaddrinfo = socket.getaddrinfo, fake_getaddrinfo
try:
    office = _Link(deployment="hp", vault=VAULT) if _Link else None
    check(office is not None and office.addresses() == frozenset(), "no door on the network → no door")
    answers["dgo-net-hp"] = ["172.18.0.28"]
    check(office is not None and office.addresses() == frozenset(), "a miss is held 15 s, not asked per request")
    if office is not None:
        office._door = (0.0, frozenset())                 # the hold is over
    check(office is not None and office.addresses() == {"172.18.0.28"} and office.from_door("172.18.0.28")
          and not office.from_door("172.18.0.36"), "dgo-net-hp's address is the door's, and only it")
    check(asked.count("dgo-net-hp") == 2, f"the door is asked by its container name alone: {asked}")
    answers["dgo-net-hp"] = ["172.18.0.28", "172.18.0.99"]
    if office is not None:
        office._door = (0.0, frozenset())
    check(office is not None and office.addresses() == frozenset(),
          "two containers answer to the door's name (an alias) → no door")
    answers["dgo-net-hp"] = ["172.18.0.28", "fd00::28"]
    if office is not None:
        office._door = (0.0, frozenset())
    check(office is not None and office.addresses() == {"172.18.0.28", "fd00::28"}, "one door on both families")
    nameless = _Link(deployment="x" * 70, vault=VAULT) if _Link else None
    check(nameless is not None and nameless.addresses() == frozenset(), "a deployment name DNS cannot carry → no door")
finally:
    socket.getaddrinfo = _real_getaddrinfo

server.should_exit = True
if FAIL:
    print("FAIL", *FAIL, sep="\n  ")
    sys.exit(1)
print("ok — test_link: the door's signed person (herd → admin), every unproved case refused by its case, local as "
      "before, the door found by its container name alone")
