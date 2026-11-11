"""domain-internic — the InterNIC provider app (ai/context/provider-apps.md).

The generic `domains` app organises the office's domains; THIS app is the only place that knows how to
talk to InterNIC. Its four channels (ai/context/build-your-first-app.md, «The four channels»):

  ui    the console tile /a/domain-internic/ (static/index.html): the session, the domains, a zone
  cli   ./bbox domain-internic <verb> (hooks/ → cli.py, run inside this container)
  api   the domain-provider.v1 ops below, which the generic app and agents call
  flow  dgo:flow:domain-internic on the office redis: login.*, record.*, session.*

The ops (domain-provider.v1) — every answer is {"ok":…, …}:

  GET  /ops                    who this is: interface, provider, portal origin, the ops
  GET  /api/state              is the office browser signed in, is the credential there, can it write
  POST /api/login              sign in by itself (login.py): the leased credential, the mailed code
  POST /api/connect            the provider flow: signed in AND in control (portal.connect_check)
  GET  /api/domains            the account's domains, read off the panel
  GET  /api/zones/{domain}     one zone, read off the panel's own editor
  GET  /api/write-state        which writes the office may do here, before anything is clicked
  POST /api/records            {action, domain, type, name, value, ttl, consented_by?} — one record
  POST /api/run                {operation, params} — a registrar operation of the portal script
  POST /api/selftest           the zone editor against the fixture panel, through the real browser

THE CONSENT (DGO-1032, narrowed by DGO-1473's second reader): a write the office has not seen succeed once
is refused (`needs_verification`) unless it carries `consented_by` from INSIDE this container — the CLI at
the office's own shell (`--consent "<who>: <why>"`). A consent any other caller sends, the generic app's
screen included, is dropped: this app cannot see a person behind a network call, and the uvicorn here
trusts no X-Forwarded-For. One consented write that the zone READ BACK makes that action the office's own
(portal.mark_verified): from then on it runs alone, from the CLI and from the generic app's screen alike.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import browser_session
import login
import portal

log = logging.getLogger("domain-internic")
logging.basicConfig(level=logging.INFO)

SERVICE = "domain-internic"
PORTAL = "internic"
INTERFACE = "domain-provider.v1"
OPS = ["state", "login", "connect", "listDomains", "readZone", "writeState", "writeRecord", "run", "selftest"]
_STATIC = Path(__file__).parent / "static"
app = FastAPI(title="domain-internic")


# ── flow.v1: the office's event stream ─────────────────────────────────────────────────────────────
import sys as _sys

_sys.path.insert(0, "/opt/dgo")
try:
    import flowpub as _flowpub                       # the office's ONE flow.v1 publisher (platform-base/redis)
except ImportError:
    _flowpub = None


class Flow:
    """`dgo:flow:domain-internic`, written through the office's ONE publisher (platform-base/redis/flowpub.py,
    mounted read-only at /opt/dgo — docker-compose.yml): it caps the stream, renews its TTL, never blocks and never
    raises (DGO-1402; this class carried its own copy of the contract until then). What is published is what
    HAPPENED (a sign-in, a record, a lost session) — never a secret, a code or a cookie: every agent of the office
    reads this stream. Reading the stream back for the screen (`last`) stays here."""
    STREAM = f"dgo:flow:{SERVICE}"

    def __init__(self):
        self._r, self._read_error = None, None

    @property
    def published(self) -> int:
        return _flowpub.stats()["sent"] if _flowpub is not None else 0

    @property
    def error(self) -> str | None:
        if _flowpub is None:
            return "the office's publisher is not mounted (/opt/dgo/flowpub.py)"
        return _flowpub.stats()["last_error"] or self._read_error

    def _redis(self):
        if self._r is None:
            import redis
            self._r = redis.Redis(host=os.environ.get("REDIS_HOST_INTERNAL", "redis"), port=6379,
                                  password=os.environ.get("REDIS_PASSWORD") or None, decode_responses=True,
                                  socket_timeout=5, socket_connect_timeout=5)
        return self._r

    def publish(self, type_: str, title: str, data: dict | None = None, link: str = "") -> None:
        if _flowpub is not None:
            _flowpub.emit(SERVICE, type_, title, data or {}, link)

    def last(self, n: int) -> list[dict]:
        try:
            rows = self._redis().xrevrange(self.STREAM, count=max(1, min(500, n)))
            self._read_error = None
        except Exception as e:                                   # noqa: BLE001
            self._read_error = f"{type(e).__name__}: {e}"[:200]
            return []
        out = []
        for eid, f in rows:
            try:
                data = json.loads(f.get("data") or "{}")
            except ValueError:
                data = f.get("data")
            out.append({"id": eid, "type": f.get("type", ""), "title": f.get("title", ""),
                        "at": f.get("at", ""), "link": f.get("link", ""), "data": data})
        return out


FLOW = Flow()
LINK = "#/m/domain-internic/"


def _safe(fn, *a, **kw) -> dict:
    """Every op answers a dict; a browser fault is a STATE, never a 500 that hides which one."""
    try:
        res = fn(*a, **kw)
        return res if isinstance(res, dict) else {"ok": True, "data": res}
    except browser_session.SessionError as e:
        return {"ok": False, "state": e.state, "error": e.message, "detail": e.detail}
    except Exception as e:                                       # noqa: BLE001
        log.exception("op failed")
        return {"ok": False, "state": "unknown_error", "error": f"{type(e).__name__}: {e}"[:300]}


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except ValueError:
        return {}


def _norm(domain: str) -> str:
    return (domain or "").strip().rstrip(".").lower()


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": SERVICE}


def _provider_card() -> dict:
    """provider.json: what this app bridges, its kind (external | engine) and its access ladder, measured
    (ai/context/provider-apps.md). A missing or broken card is an empty one, never a failed /ops."""
    try:
        return json.loads((Path(__file__).parent / "provider.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/ops")
def ops():
    s = portal.SCRIPTS[PORTAL]
    card = _provider_card()
    return {"ok": True, "service": SERVICE, "interface": INTERFACE, "provider": PORTAL,
            "for": card.get("for") or "domains", "kind": card.get("kind") or "external",
            "ladder": card.get("ladder") or [],
            "name": s.get("name"), "origin": s.get("origin"), "access": "browser",
            "capabilities": {"write_dns": True, "list_zones": True, "registrar": True, "via_browser": True,
                             "signs_in": True, "mail_code": bool(login.MAIL_CONNECTION)},
            "ops": OPS}


@app.get("/api/state")
def api_state():
    if login.busy():
        # a sign-in is filling the shared tab: reading the portal's state would navigate it under the fill
        return {"ok": True, "busy": True, "session": {"authenticated": False, "state": "busy",
                                                      "reason": "a sign-in is running"},
                "credential": {}, "write": portal.write_state(PORTAL)}

    def _state():
        st = portal.state(PORTAL)
        return {"ok": True, "portal": portal.describe(PORTAL), "session": st,
                "browser": browser_session.available(), "credential": login.configured(),
                "write": portal.write_state(PORTAL), "mail_connection": bool(login.MAIL_CONNECTION),
                "flow": {"published": FLOW.published, "error": FLOW.error}}
    return _safe(_state)


@app.post("/api/login")
async def api_login():
    res = await run_in_threadpool(_safe, login.sign_in)
    if res.get("ok") and not res.get("already_signed_in"):
        FLOW.publish("login.ok", "הלשכה התחברה לפורטל אינטרניק" + (" (עם קוד מהמייל)" if res.get("mail_code") else ""),
                     {"mail_code": bool(res.get("mail_code")), "seconds": res.get("seconds")}, LINK)
    elif not res.get("ok"):
        FLOW.publish(f"login.{res.get('state') or 'failed'}", f"הכניסה לאינטרניק נעצרה: {res.get('reason') or res.get('state')}",
                     {"state": res.get("state")}, res.get("live_view") or LINK)
    return res


@app.post("/api/connect")
async def api_connect():
    return await run_in_threadpool(_safe, portal.connect_check, PORTAL)


@app.get("/api/domains")
async def api_domains():
    return await run_in_threadpool(_safe, portal.read_domains, PORTAL)


@app.get("/api/zones/{domain}")
async def api_zone(domain: str):
    return await run_in_threadpool(_safe, portal.read_zone, PORTAL, _norm(domain))


@app.get("/api/write-state")
def api_write_state():
    return _safe(portal.write_state, PORTAL)


def write_record(body: dict) -> dict:
    """One record write and its consequences — the provider's half of what the generic app's
    `_portal_written` did: the consent decides the gate, a read-back success marks the action."""
    action = (body.get("action") or "create").strip().lower()
    domain = _norm(body.get("domain") or "")
    if not domain:
        return {"ok": False, "state": "invalid", "error": "חסר domain"}
    consented_by = (body.get("consented_by") or "").strip() or None
    rec = {"domain": domain, "type": (body.get("type") or "A").upper(), "name": body.get("name") or "@",
           "value": body.get("value") if body.get("value") is not None else body.get("content"),
           "ttl": body.get("ttl")}
    res = portal.run_write(PORTAL, action, rec, None, bool(consented_by))
    # only a write that CHANGED the zone and whose guard RAN vouches for the writer: a record that was
    # already there proves nothing, and an "unavailable" guard showed nothing (DGO-1032's third reader)
    if res.get("ok") and not res.get("unchanged") and consented_by and res.get("guard") == "checked" \
            and not portal.verified(PORTAL, action):
        portal.mark_verified(PORTAL, action, consented_by, res.get("record") or {})
        res = {**res, "marked_verified": True}
    who = f" · באישור {consented_by}" if consented_by else ""
    if res.get("ok") and not res.get("unchanged"):
        FLOW.publish(f"record.{action}d", f"{rec['type']} {rec['name']} ב-{domain} נכתבה בפורטל{who}",
                     {"domain": domain, "record": res.get("record") or rec, "consented_by": consented_by}, LINK)
    elif not res.get("ok"):
        FLOW.publish(f"record.{action}_failed", f"{rec['type']} {rec['name']} ב-{domain}: {res.get('error') or res.get('state')}",
                     {"domain": domain, "state": res.get("state"), "saved": res.get("saved")}, LINK)
    return res


LOOPBACK = {"127.0.0.1", "::1"}


@app.post("/api/records")
async def api_records(request: Request):
    """A consent is taken from ONE door: a call made inside this container — the CLI, piped in by the
    office's own shell (hooks/ → cli.py → 127.0.0.1). Every other caller (a container on the network, a
    linked office through its door, a screen) is no person this app can see, so a `consented_by` it sends
    is dropped, and a write the office never watched is refused by name (the second reader of DGO-1473:
    the body's word alone would have let any caller unlock every later write)."""
    body = await _body(request)
    if body.get("consented_by") and (request.client.host if request.client else "") not in LOOPBACK:
        body = {k: v for k, v in body.items() if k != "consented_by"}
        body["_consent_dropped"] = True
    res = await run_in_threadpool(_safe, write_record, body)
    if body.get("_consent_dropped") and res.get("state") == "needs_verification":
        res = {**res, "how": "the first write of an action is consented at the office that runs domain-internic: "
                             "./bbox domain-internic add-record … --consent \"<who>: <why>\""}
    return res


@app.post("/api/run")
async def api_run(request: Request):
    b = await _body(request)
    return await run_in_threadpool(_safe, portal.run, PORTAL, b.get("operation") or "", b.get("params") or {})


@app.get("/api/verified")
def api_verified(action: str = "create"):
    return {"ok": True, "action": action, "verified": portal.verified(PORTAL, action)}


@app.get("/api/flow")
def api_flow(n: int = 20):
    return {"ok": True, "stream": Flow.STREAM, "events": FLOW.last(n),
            "published": FLOW.published, "error": FLOW.error}


@app.post("/api/selftest")
def api_selftest():
    """The zone editor (browser_ops.py) against the generic app's fixture panel, through the REAL
    browser: read the table → add a record → see it → delete it → see it gone (moved from domains)."""
    import browser_ops
    if not browser_session.available().get("available"):
        return {"ok": False, "state": "browser_unavailable", "error": "הדפדפן של הלשכה אינו זמין"}
    s = browser_session.shared()
    origin = os.environ.get("DOMAINS_FIXTURE_URL", "http://domains:8980/internal/fixture/panel")
    editor = browser_ops.ZoneEditor(s, origin, learned={})
    stamp = str(int(time.time()))
    out: dict = {"origin": origin, "steps": {}, "learned": {}}
    try:
        s.open(origin)
        before = editor.records("example.co.il")
        out["steps"]["read"] = {"ok": True, "records": [r.get("content") for r in before]}
        created = editor.add_record("example.co.il", {"type": "TXT", "name": "bina-selftest",
                                                      "content": f"ok-{stamp}", "ttl": 300})
        out["steps"]["write"] = {"ok": True, "record": created.get("record")}
        out["steps"]["delete"] = editor.delete_record("example.co.il", {"type": "TXT", "content": f"ok-{stamp}"})
        after = editor.records("example.co.il")
        out["steps"]["verify_gone"] = {"ok": not any(r.get("content") == f"ok-{stamp}" for r in after)}
        out.update(learned=editor.learned, trace=editor.trace,
                   ok=all(step.get("ok") for step in out["steps"].values()))
    except browser_session.SessionError as e:
        out.update({"ok": False, "state": e.state, "error": e.message, "trace": editor.trace})
    except Exception as e:                                       # noqa: BLE001 — a state, never a bare 500
        out.update({"ok": False, "state": "unknown_error", "error": f"{type(e).__name__}: {e}"[:300],
                    "trace": editor.trace})
    return out


@app.get("/")
def index():
    """Relative URLs only: the console embeds this at /a/domain-internic/ and injects `<base href>`."""
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
