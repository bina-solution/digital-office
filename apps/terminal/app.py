"""terminal — a command line on any machine of the office (DGO-553).

What this app is, and what it deliberately is NOT
-------------------------------------------------
It is a SCREEN. The key that opens a shell is the office's own key and it lives, alone, in the
`computers` volume (`computers_state:/data/ssh/office_key`); this app has no key, no volume and no
privilege of its own. Every byte it moves is a call to `computers.v1`:

    the browser  →  this app  →  computers  →  ssh (a pty)  →  the machine

The reason there is an app at all rather than a panel inside «מחשבים» is the office's own rule: an
app is the unit that can be ENABLED, DISABLED, MOVED and SHARED between offices. A terminal that is
part of another app could not be given to the MacBook without giving the whole computers app; this
one can, and the receiving office runs it against its own computers — which is what makes "a command
line straight from the other office" the same feature rather than a second one.

Why HTTP and not a websocket — `apps/computers/shell.py` explains it in full. Short version: the
console frames an embedded app through `/a/<alias>/`, that proxy is Flask + requests and strips
`Upgrade`, so a socket opened from a framed app never connects. A session here is start → post keys
→ poll, and `cursor` is an absolute byte offset so a reader that missed a poll gets what it missed.
"""
from __future__ import annotations

import logging
import os
import re
import time

import requests
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("terminal")

#: The fleet's one door. `computers` is the only app that holds the key; this one never does.
COMPUTERS_URL = os.environ.get("COMPUTERS_URL", "http://computers:8977").rstrip("/")
#: A shell call that has to reach a machine waits on ssh; a browser waiting on that must not look
#: dead, so the timeout is generous and the UI says "connecting" while it waits.
HTTP_TIMEOUT = float(os.environ.get("TERMINAL_HTTP_TIMEOUT", "25"))
#: The machine list is polled by the screen; a 5 s cache keeps a refresh from becoming an SSH probe
#: of every machine in the fleet (`?probe=0` never probes, this only bounds the calls).
LIST_TTL = float(os.environ.get("TERMINAL_LIST_TTL", "5"))

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app = FastAPI(title="terminal", docs_url=None, redoc_url=None, openapi_url=None)

_LIST_CACHE: dict = {"at": 0.0, "data": None}


# ── plumbing ────────────────────────────────────────────────────────────────────────────────────
def _err(message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


async def _body(request: Request) -> dict:
    """The request's JSON, or an empty dict — never a 500 for a malformed body.

    A terminal sends keystrokes; a proxy, a stale tab or a hand-written curl sends broken JSON
    eventually. `request.json()` raises on that, and an uncaught raise answers 500 "Internal Server
    Error" for a request the app could have refused in one sentence (measured 2026-11-01: a curl
    with a bad escape, 500 and a traceback in the log).
    """
    try:
        raw = await request.body()
        if not raw:
            return {}
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


#: What the LINK's door writes on a request that crossed a link, and what this app must pass ON to
#: `computers` on every call it makes for it. The sharing gate lives THERE (which office may see which
#: machine), and a terminal that dropped these would be asking as a LOCAL caller — listing every
#: machine of this office and opening a shell on any of them, whatever the owner shared (DGO-553 §ד:
#: a proxy is not an exemption from the rule it proxies to).
CALLER_HEADERS = ("x-dgo-office", "x-dgo-identity", "x-authentik-username")


def _caller(request) -> dict:
    out = {}
    try:
        for name in CALLER_HEADERS:
            value = request.headers.get(name)
            if value:
                out[name] = value
    except Exception:                                   # noqa: BLE001 — no headers is no caller
        return {}
    return out


def _call(method: str, path: str, body: dict | None = None,
          headers: dict | None = None) -> tuple[int, dict]:
    """One call to the fleet. The APP's own errors are passed through as they are: the computers app
    already speaks this office's Hebrew, and re-wording its refusals here would be a second opinion
    about the same machine."""
    try:
        r = requests.request(method, f"{COMPUTERS_URL}{path}", json=body, timeout=HTTP_TIMEOUT,
                             headers=headers or None)
    except requests.RequestException as e:
        return 502, {"error": "שירות המחשבים אינו עונה", "detail": str(e),
                     "action": "בדוק שמחשבים למעלה (מסך «מחשבים» או bbox status)."}
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {"error": f"תשובה לא קריאה משירות המחשבים ({r.status_code})", "detail": r.text[:400]}
    return r.status_code, data


#: What a machine id and a session id may be. Both are interpolated into an outbound PATH, so a
#: value carrying `/`, `?` or `#` turns one `computers` op into another — measured by the second reader
#: on 2026-11-02: `machine: "x/status?fresh=1"` made a shell call land on a status route. The ids are
#: the office's own (a machine is `<protocol>-<suffix>[.<office>]`, a session is 16 hex chars).
MACHINE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
SESSION_RE = re.compile(r"^[0-9a-f]{8,32}$")


def _bad_id(value: str, what: str) -> JSONResponse | None:
    pattern = SESSION_RE if what == "הטרמינל" else MACHINE_RE
    if pattern.match(str(value or "")):
        return None
    return JSONResponse({"error": f"{what} אינו מזהה תקין"}, status_code=400)


def _relay(code: int, data: dict) -> JSONResponse:
    return JSONResponse(data, status_code=code)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "terminal", "computers": COMPUTERS_URL}


@app.get("/manifest")
def manifest():
    """platform-service.v1: what this service does and what it needs to do it. It owns no protocol
    and stores nothing — `shell` is the op, and it is a proxy to the app that holds the key."""
    code, data = _call("GET", "/manifest")
    fleet = data if code < 300 else {}
    return {"service": "terminal",
            "protocols": [],
            "ops": ["machines", "shell"],
            "depends_on": {"computers": {"endpoint": COMPUTERS_URL,
                                         "ok": code < 300,
                                         "ops": (fleet.get("ops") or []),
                                         "shell": bool((fleet.get("capabilities") or {}).get("shell"))}},
            "capabilities": {"terminal": True, "transport": "http", "buffer": "cursor",
                             "no_key_of_its_own": True}}


# ── the fleet, as this screen needs it ──────────────────────────────────────────────────────────
@app.get("/api/machines")
def api_machines(request: Request, refresh: int = 0):
    """The machines a terminal can be opened on.

    `probe=0` on purpose: the screen opens in a fraction of a second even when a machine on the
    other side of the world does not answer, and the row's own state is drawn from what the probe
    cache already says. A person who wants a fresh reading presses «בדיקה» in «מחשבים»."""
    caller = _caller(request)
    # …and the cache is PER CALLER-OR-NOTHING: a person of a linked office must never be served the
    # list a local caller filled a second ago (that list is the whole fleet).
    key = caller.get("x-dgo-office") or ""
    now = time.time()
    if not refresh and not key and _LIST_CACHE["data"] is not None and now - _LIST_CACHE["at"] < LIST_TTL:
        return _LIST_CACHE["data"]
    code, data = _call("GET", "/api/computers?probe=0", headers=caller)
    if code >= 300:
        return _relay(code, data)
    machines = []
    for c in data.get("computers") or []:
        machines.append({
            "id": c.get("id"),
            "label": c.get("label") or c.get("host"),
            "host": c.get("host"),
            "user": c.get("user"),
            "port": c.get("port"),
            "state": c.get("state"),
            "ok": bool(c.get("ok")),
            "builtin": bool(c.get("builtin")),
            "note": c.get("note") or "",
            "reason": c.get("reason") or "",
            "action": c.get("action") or "",
            "ssh": c.get("state") not in ("no_ssh",),
            # CAN this machine be given a terminal at all? A machine of a linked office whose app is
            # older than `shell` (DGO-553) cannot, and the screen says so instead of offering a
            # button that answers 501.
            "shell": (None if not c.get("remote") else (c.get("remote") or {}).get("shell")),
        })
    out = {"machines": machines, "count": len(machines),
           "office_key": (data.get("office_key") or {}).get("fingerprint") or "",
           # …and WHICH OFFICES THESE MACHINES COME FROM, including the one that did not answer: a
           # peer whose link blipped otherwise just loses its rows here, and an empty list looks like
           # a sharing that was withdrawn (apps/computers says the same on its own screen).
           "shared_from": data.get("shared_from") or []}
    if not key:                                   # a peer's narrowed list is never the cache
        _LIST_CACHE.update(at=now, data=out)
    return out


# ── the shell ──────────────────────────────────────────────────────────────────────────────────
# These five routes are thin on purpose. Each one is a single call to the app that owns the key, and
# the answer is handed back unchanged — a terminal that re-decides what "the shell ended" means
# would disagree with the app the machine actually talks to.
@app.post("/api/shell")
async def api_shell_open(request: Request):
    body = await _body(request)
    cid = str(body.get("machine") or "").strip()
    if not cid:
        return _err("לא נבחר מחשב", 400)
    bad = _bad_id(cid, "המחשב")
    if bad:
        return bad
    code, data = _call("POST", f"/api/computers/{cid}/shell",
                       {"cols": body.get("cols"), "rows": body.get("rows")},
                       headers=_caller(request))
    if code >= 300:
        return _relay(code, data)
    log.info("shell opened on %s", cid)
    return {"machine": cid, **data}


@app.post("/api/shell/input")
async def api_shell_input(request: Request):
    body = await _body(request)
    cid, sid = str(body.get("machine") or ""), str(body.get("session") or "")
    if not cid or not sid:
        return _err("חסר מחשב או מזהה טרמינל", 400)
    bad = _bad_id(cid, "המחשב") or _bad_id(sid, "הטרמינל")
    if bad:
        return bad
    code, data = _call("POST", f"/api/computers/{cid}/shell/{sid}/input",
                       {"data": body.get("data") or "", "cursor": body.get("cursor") or 0},
                       headers=_caller(request))
    return _relay(code, data)


@app.get("/api/shell/poll")
def api_shell_poll(request: Request, machine: str, session: str, cursor: int = 0):
    code, data = _call("GET", f"/api/computers/{machine}/shell/{session}?cursor={int(cursor or 0)}",
                       headers=_caller(request))
    return _relay(code, data)


@app.post("/api/shell/resize")
async def api_shell_resize(request: Request):
    body = await _body(request)
    cid, sid = str(body.get("machine") or ""), str(body.get("session") or "")
    bad = _bad_id(cid, "המחשב") or _bad_id(sid, "הטרמינל")
    if bad:
        return bad
    code, data = _call("POST",
                       f"/api/computers/{cid}/shell/{sid}/resize",
                       {"cols": body.get("cols"), "rows": body.get("rows")},
                       headers=_caller(request))
    return _relay(code, data)


@app.delete("/api/shell/{machine}/{session}")
def api_shell_close(request: Request, machine: str, session: str):
    code, data = _call("DELETE", f"/api/computers/{machine}/shell/{session}",
                       headers=_caller(request))
    return _relay(code, data)


# ── the screen ──────────────────────────────────────────────────────────────────────────────────
# Static files are served from the ROOT of this app (`/term.js`, `/vendor/xterm.js`) and every URL
# the screen builds is RELATIVE. That is the platform's rule for an embedded app (the console puts
# this app under `/a/terminal/` and injects a `<base>`), and the rule exists because the same screen
# is opened through the link in another office's console.
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/vendor", StaticFiles(directory=os.path.join(STATIC, "vendor")), name="vendor")
