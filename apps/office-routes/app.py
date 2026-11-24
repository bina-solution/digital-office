"""network — the office's own routes: what is reachable, from where, and at which address (DGO-543).

WHY THIS APP EXISTS. Every host this office serves is a `<name>.localhost` one, and `.localhost` is
loopback BY DEFINITION (RFC 6761): on a phone that name is the phone itself. Measured 2026-10-12 on
hp-laptop: nothing but the machine could open the office — the router's DNS knew no name for it, no
mDNS responder answered, and every rule the compiler rendered was a `Host(...)`, so a device on the
same network asking for the machine's own address got traefik's 404 while the edge did listen there.

The answer is a ROUTE: the office's own address, opened deliberately, from a screen — not a line in
`.env` and never by default. This app is that screen and the plane that owns it:

    the screen  →  the control plane  →  the compiler  →  the edge and the machine

  * the DECLARATION is `network.routes` in `platform.state.yaml`, the file the console writes (the
    same one `apps:` and `remote:` live in) — one writer, and a route that is not declared (or is
    declared without `enabled: true`) adds nothing anywhere;
  * this app never touches that file: it asks the CONTROL PLANE (`APP_MANAGEMENT_URL`, the app that
    owns every change to the estate), which runs the compiler's `network-set` verb — validated
    before it is written, refused with one sentence per reason;
  * the compiler renders what the edge serves (`Host(<address>)` twins of the console's whole URL
    space, the sign-in's host and its provider) and what the MACHINE side needs
    (`.generated/network.json`, read by the Windows firewall converge);
  * the app then asks the control plane to converge, and re-reads the truth rather than assuming it.

WHAT IT DOES NOT PRETEND TO KNOW — AND HOW IT FINDS OUT ANYWAY. Which addresses THIS MACHINE holds is
a fact of the machine, and a container cannot read it: `/proc` inside a container is the container's
own network namespace — measured 2026-10-12, a read-only bind of the machine's root answers
`/proc/net/route` with the CONTAINER's gateway (Eth0 172.18.0.1) and nothing else, which is how this
app's first version offered an address no phone could dial. So the screen does not read interfaces. It
takes the address the office already declares about this machine (a host-side step measured it — the
tunnel's `DGO_WG_ENDPOINT`), lets a person type or pick one, and CHECKS it by knocking.

AND WHEN THE DECLARED ONE IS STALE, IT SEARCHES — `/api/find`. A lease that moved (hp-laptop was
192.168.16.102, then .100, then .102 again inside one week, 2026-10) leaves the office declaring an
address it no longer holds, and a screen that only says "nothing answers there" leaves the person
holding a phone with nothing to type. So the app asks the network the one question it can ask —
`/api/find` walks the machine's own `/24`, nearest-first and bounded, and accepts an answer ONLY when
it is THIS office's edge: a redirect to this office's own sign-in host (`auth.<its own domain>`), which
is a thing no other device on the network says. The search is started by a person on the screen, never
on load, and never adopts a stranger.

The authoritative check still belongs where the machine is: `scripts/windows/firewall-converge.ps1`
refuses to open its rule for an address this machine does not hold. No engine socket, no host root,
and nothing written outside this volume.
"""
from __future__ import annotations

import json
import os
import queue
import re
import socket
import threading
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

def _host_only(url: str) -> str:
    """The host of a URL or a Host header, lowercased, without scheme, path or port."""
    return url.split("://", 1)[-1].split("/", 1)[0].split(":")[0].strip().lower()


#: The office's control plane — the ONE writer of `platform.state.yaml`'s blocks.
#:
#: BY THE DEPLOYMENT-SUFFIXED NAME, not by the bare service name, and that is not decoration: this
#: machine carries a SECOND stack of an older platform on the same edge network (its containers are
#: `-posnet`), and a docker name that two containers answer to is round-robined between them —
#: measured 2026-10-12: `network` resolved to {mydgo, platform-os-net}, and this app's first call to
#: `app-management` landed on the other office's instance, which answered 404. Container names carry
#: the deployment (`app-management-hp`), so they are the unambiguous door — and `bbox status` names
#: `app-management` itself under "a name more than one container answers to".
#:
#: So the SUFFIXED name is what this app dials, and `APP_MANAGEMENT_URL` is honoured only when it
#: names something of its own (another host, an address, or the suffixed name): the platform's `.env`
#: sets it to the bare name, which is exactly the door this app must not use.
_DEPLOYMENT = os.environ.get("DEPLOYMENT_NAME", "").strip()


def _control_plane() -> str:
    env = os.environ.get("APP_MANAGEMENT_URL", "").strip().rstrip("/")
    if not _DEPLOYMENT:
        return env or "http://app-management:8080"
    if env and _host_only(env) not in ("app-management", "localhost", "127.0.0.1"):
        return env
    return f"http://app-management-{_DEPLOYMENT}:8080"


APPMGMT = _control_plane()

#: The edge's plain-http entrypoint — the one port a route opens. http on purpose: an address has no
#: certificate, so a browser sent to https there would refuse it.
EDGE_PORT = int(os.environ.get("OFFICE_ROUTES_EDGE_PORT", "80"))
STORE = os.environ.get("OFFICE_ROUTES_STATE_DIR", "/data")

#: THIS APP'S OWN HOST — handed to every app by the platform through `app.json`'s `sso.base_url_env`.
#: The search below needs it and nothing else: an answer is this office's edge only if it sends the
#: caller to this office's own sign-in, and that host is derived from this office's own domain the way
#: the compiler derives it (`<suffix>` of this app's host → `auth.<suffix>`). No host, no identity
#: claim: the screen then says what it cannot tell rather than guessing.
OWN_HOST = _host_only(os.environ.get("OFFICE_ROUTES_BASE_URL", ""))
OWN_SIGNIN = f"auth.{OWN_HOST.split('.', 1)[1]}" if "." in OWN_HOST else ""

#: The bounds of the search. The machine's lease moves inside its own network, so the candidates are
#: the other hosts of ITS OWN /24, nearest first, and never a second subnet or a wider sweep. One
#: knock is one TCP connect with a short read; a person on a phone waits for the answer, so the whole
#: search is bounded by both a cap and a deadline.
FIND_WORKERS = 24
FIND_TIMEOUT = 0.7
FIND_DEADLINE = 12.0
FIND_LIMIT = 254

app = FastAPI(title="office-routes", docs_url=None, redoc_url=None)


def http(method: str, url: str, body: dict | None = None, timeout: int = 60):
    """One call to the control plane. Returns (status, json-or-None, error-or-None)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None), None
    except urllib.error.HTTPError as e:                     # a refusal WITH a body: keep its words
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), None
        except ValueError:
            return e.code, None, raw[:300] or f"HTTP {e.code}"
    except Exception as e:                                  # noqa: BLE001 — said to the screen
        return 0, None, str(e)


# ── the history: every ATTEMPT, kept where it happened ───────────────────────────────────────────
# Append-only, one JSON line per attempt, in this app's own store (data/office-routes/state). Both halves matter and for
# different reasons: an OPENING is a door the office now answers on and must be attributable
# ("who opened it, when, on which address"), and a REFUSAL is the record that the guard worked —
# a screen that says "not answering" and writes nothing is a claim nobody can check afterwards.
# A call that carries no identity (the acceptance run, anything inside the office network) is
# recorded as it is, `—`, rather than credited to somebody.
def _by(request: Request) -> str:
    return (request.headers.get("X-authentik-username")
            or request.headers.get("X-authentik-email") or "—")


def record(action: str, address: str, by: str, result: str, detail: str = "") -> None:
    try:
        os.makedirs(STORE, exist_ok=True)
        with open(os.path.join(STORE, "history.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "action": action, "address": address or "", "by": by,
                                 "result": result, "detail": detail[:300]},
                                ensure_ascii=False) + "\n")
    except OSError:
        pass                        # a history that cannot be written is not a reason to refuse a door


def history(limit: int = 20) -> list:
    """The last `limit` events, newest first."""
    path = os.path.join(STORE, "history.jsonl")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in lines[-max(1, limit):]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out))


# ── the address, before it is declared ───────────────────────────────────────────────────────────
def knock(host: str, port: int, timeout: float = FIND_TIMEOUT) -> dict:
    """One TCP knock on the edge's port, asked AS THIS OFFICE. A reading, never an exception."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(f"GET / HTTP/1.1\r\nHost: {OWN_HOST or host}\r\n"
                         "Connection: close\r\n\r\n".encode())
            raw = b""
            while b"\r\n\r\n" not in raw and len(raw) < 4096:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                raw += chunk
    except OSError as e:                                     # no answer, refused, timed out — the reason
        return {"answers": False, "status": 0, "location": "", "why": str(e)[:200]}
    lines = raw.decode("latin-1", "replace").split("\r\n")
    head = re.match(r"HTTP/\d\.\d\s+(\d{3})", lines[0] if lines else "")
    location = next((ln.split(":", 1)[1].strip() for ln in lines[1:]
                     if ln.lower().startswith("location:")), "")
    return {"answers": bool(head), "status": int(head.group(1)) if head else 0,
            "location": location, "why": ""}


def answer_is_ours(status: int, location: str) -> bool | None:
    """Is this answer THIS OFFICE's edge? None when it cannot be told at all.

    The signature is measured, not assumed (2026-10-12, at the machine's own address): the office's
    own host, asked at the edge, answers `302` → `http://auth.<domain>/application/o/authorize/…`
    with an `authentik_proxy_` cookie. A router's admin page, another office's stack on the same
    machine, a printer — none of them sends a caller to THIS office's sign-in. When the app does not
    know its own host (no `OFFICE_ROUTES_BASE_URL`), nothing is claimed either way: a check that
    cannot run must not be able to reject an address.
    """
    if not OWN_HOST:
        return None
    if status not in (301, 302, 303, 307, 308):
        return False
    return _host_only(location) in {OWN_SIGNIN, OWN_HOST} - {""}


def probe(address: str) -> dict:
    """Does something answer at that address on the edge's port — and is it THIS office?

    This is the one check a container can honestly make about an address: it cannot see the machine's
    interfaces (a container's `/proc` is its own network namespace), so what it does instead is the
    thing that actually matters to a phone: knock. Two readings come back, and they are different
    facts — `answers` (something is listening on the edge's port there) and `ours` (the answer is this
    office's own edge). A route is only opened for an address that answered AND, when that is
    knowable, answered as this office: a door on a stranger's port 80 is a door to nowhere. The
    authoritative check of "is that address mine" still happens where the machine is
    (`scripts/windows/firewall-converge.ps1`), because only that half can see its interfaces.
    """
    host = address.rsplit(":", 1)[0]
    port = int(address.rsplit(":", 1)[1]) if ":" in address else EDGE_PORT
    if not host:
        return {"answers": False, "ours": None, "status": 0, "why": "no address"}
    if ":" in address and not address.rsplit(":", 1)[1].isdigit():
        return {"answers": False, "ours": None, "status": 0, "why": "not an address"}
    reading = knock(host, port)
    return {"answers": reading["answers"], "status": reading["status"], "why": reading["why"],
            "ours": answer_is_ours(reading["status"], reading["location"]) if reading["answers"] else None}


def _candidates(start: str) -> list[str]:
    """The hosts of `start`'s own /24, nearest to it first — the machine's lease moves inside its own
    network, and the nearest addresses are where it moves to. Never a second subnet, never wider."""
    octets = start.split(".")
    if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
        return []
    base, last = ".".join(octets[:3]), int(octets[3])
    others = sorted((i for i in range(1, 255) if i != last), key=lambda i: (abs(i - last), i))
    return [f"{base}.{i}" for i in [last] + others][:FIND_LIMIT]


def find(start: str) -> dict:
    """THE MACHINE'S OWN ADDRESS, MEASURED — the one thing this app cannot read and can only ask for.

    Started from the address the office already declares (or one a person typed), it knocks, nearest
    first, and returns the addresses of THIS office that answered. Anything else is passed over: a
    device that refuses, stays silent, or answers as somebody else is not this machine's edge, and
    adopting it would declare a route to a stranger. Bounded by `FIND_LIMIT` (one /24), by
    `FIND_TIMEOUT` per knock and by `FIND_DEADLINE` for the whole search, and it stops at the first
    verified answer — the common case is the declared address itself, at the first knock.
    """
    candidates = _candidates(start)
    if not candidates:
        return {"start": start, "probed": 0, "found": [], "ms": 0, "identity": bool(OWN_HOST),
                "why": "אין כתובת שממנה לחפש — הלשכה לא הצהירה כתובת של המכונה, ואין מה להקליד"}
    started, deadline = time.monotonic(), time.monotonic() + FIND_DEADLINE
    todo: "queue.Queue[str]" = queue.Queue()
    for candidate in candidates:
        todo.put(candidate)
    found: list[str] = []
    stop = threading.Event()
    counter = {"probed": 0}
    guard = threading.Lock()

    def work() -> None:
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                candidate = todo.get_nowait()
            except queue.Empty:
                return
            reading = knock(candidate, EDGE_PORT)
            with guard:
                counter["probed"] += 1
            if reading["answers"] and answer_is_ours(reading["status"], reading["location"]):
                with guard:
                    found.append(candidate)
                stop.set()
                return

    workers = [threading.Thread(target=work, daemon=True)
               for _ in range(min(FIND_WORKERS, len(candidates)))]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(FIND_DEADLINE + FIND_TIMEOUT + 1)
    return {"start": start, "probed": counter["probed"], "found": found,
            "ms": int((time.monotonic() - started) * 1000), "identity": bool(OWN_HOST),
            "why": "" if found else "לא נמצאה ברשת הזו כתובת שהלשכה עונה בה"}


# ── the routes, as declared and as compiled ──────────────────────────────────────────────────────
def control() -> dict:
    """Everything the control plane answers for this plane: declared routes, compiled facts, and the
    addresses THIS OFFICE already declares (`DGO_WG_ENDPOINT` — the one a host-side step measured,
    which is the only address any part of the office can honestly call "the machine's own")."""
    status, body, err = http("GET", f"{APPMGMT}/api/network", timeout=20)
    if status != 200 or not isinstance(body, dict):
        return {"routes": [], "error": (body or {}).get("error") if isinstance(body, dict)
                else (err or f"HTTP {status}")}
    return body


def declared() -> tuple[list, str]:
    doc = control()
    return doc.get("routes") or [], doc.get("error") or ""


def compiled() -> dict | None:
    """The last compile's answer (`.generated/network.json`, via the control plane)."""
    return control().get("rendered")


def routes_view() -> dict:
    """The whole picture the screen draws: the always-there route, the declared one, and the truth."""
    doc = control()
    decl = doc.get("routes") or []
    lan = next((r for r in decl if isinstance(r, dict) and r.get("kind") == "lan"), None)
    facts = doc.get("rendered") or {}
    lan_facts = (facts.get("lan") or {}) if isinstance(facts, dict) else {}
    lan_route = {
        "kind": "lan",
        "title": "ברשת המקומית",
        "address": (lan or {}).get("address") or "",
        "open": bool(lan and lan.get("enabled")),
        "closable": True,
        "compiled": bool(lan_facts.get("enabled")),
        "port": lan_facts.get("port") or EDGE_PORT,
        "why": (lan or {}).get("address") and "" or
               "לא נבחרה כתובת. הכתובות שהלשכה מצהירה על המכונה מופיעות למטה.",
    }
    if lan_route["open"] and lan_route["address"]:
        probe_result = probe(lan_route["address"])
        lan_route["reachable"] = probe_result["answers"]
        lan_route["ours"] = probe_result.get("ours")
        lan_route["probe_why"] = probe_result["why"]
    else:
        lan_route["reachable"] = False
        lan_route["ours"] = None
        lan_route["probe_why"] = ""
    return {
        "routes": [
            {
                "kind": "localhost",
                "title": "על המכונה עצמה",
                "address": "*.localhost",
                "open": True,
                "closable": False,
                "why": "השמות שהמכונה מפענחת לעצמה. זה מה שהלשכה תמיד עונה; אין מה לפתוח או לסגור.",
            },
            lan_route,
        ],
        "declared_error": doc.get("error") or "",
        "compiled": facts or None,
        # What the office already declares about this machine (the tunnel's address, written by a
        # host-side step that measured it). A HINT for the picker, never the truth of the route: the
        # screen checks whatever is chosen by knocking on it, the search below re-measures it, and
        # the machine checks it again.
        "suggested": doc.get("known_addresses") or [],
        # The address this office answers a knock ON — what makes an answer recognisable as ours.
        # `None` means this app was not told its own host, and then nothing is claimed about identity.
        "own_host": OWN_HOST or None,
        "history": history(8),
        "edge_port": EDGE_PORT,
    }


@app.post("/api/probe")
async def api_probe(request: Request):
    """Knock on an address before it is declared — the check the screen runs."""
    body = await request.json()
    return probe(str((body or {}).get("address") or "").strip())


def _search_start(body: dict) -> str:
    """Where a search begins: what the caller named, else the route's own address, else the address
    this office already declares about the machine. All three are the office's own network."""
    named = str((body or {}).get("address") or "").strip()
    if named:
        return named
    return _declared_address() or next(iter(control().get("known_addresses") or []), "")


@app.post("/api/find")
async def api_find(request: Request):
    """Find this machine's own address on the office's own network — by knocking on it, nearest first.

    The person starts it (`the screen's button`), never the app on its own: it asks the network, and a
    question is not something to fire on every page load. What is accepted is only THIS office's edge
    (see `answer_is_ours`), so the search can say "the machine is at 192.168.16.102" and never "some
    device at 192.168.16.7 answers". Every search is recorded, found or not.
    """
    try:
        body = await request.json()
    except Exception:                                        # noqa: BLE001 — an empty body is fine
        body = {}
    start = _search_start(body if isinstance(body, dict) else {})
    result = find(start)
    record("find", start, _by(request), "ok" if result["found"] else "none",
           f"probed {result['probed']} in {result['ms']}ms -> {', '.join(result['found']) or 'nothing'}")
    return result


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/routes")
def api_routes():
    return routes_view()


@app.get("/api/history")
def api_history(limit: int = 20):
    """The last attempts — opened, closed, refused — newest first."""
    return {"events": history(max(1, min(int(limit or 20), 200)))}


@app.put("/api/routes/lan")
async def api_open_lan(request: Request):
    """Open (or move) the office's route on the local network.

    The address must be one THIS MACHINE holds whenever that is knowable — a foreign address would
    render a door nobody can walk through. When the machine cannot be read, the address is accepted
    WITH the reason (the Windows side refuses to open a rule for an address that is not its own and
    says so), because a screen that cannot work on a machine whose `/proc` moved is worse than one
    that says it is guessing.
    """
    body = await request.json()
    address = str((body or {}).get("address") or "").strip()
    if not address:
        return JSONResponse({"error": "צריך כתובת — כתובת ה-IP של המכונה ברשת"}, status_code=400)
    # The one gate this half can honestly hold: nothing answers at that address, so no route is
    # declared for it. A lease that moved, a typo, a wrong port — all three look like this, and all
    # three would otherwise render a door that nobody can walk through.
    checked = probe(address)
    if not checked["answers"]:
        record("open", address, _by(request), "refused", "no answer on the edge port")
        return JSONResponse({"error": f"לא ענה כלום בכתובת {address} על פורט {EDGE_PORT}. "
                                      "אם זו אמורה להיות הכתובת של המכונה הזו — היא כנראה זזה "
                                      "(חכירת DHCP) או שהלשכה עוד לא עונה בה. "
                                      "אפשר ללחוץ «מצא את כתובת המכונה» והיא תחפש אותה ברשת.",
                             "probe": checked}, status_code=422)
    # Answered — but as SOMEBODY ELSE. A route declared there is a door to a stranger's screen, so it
    # is refused by name. Only when identity is knowable: `None` (this app was not told its own host)
    # never blocks, and the machine-side check still refuses an address it does not hold.
    if checked.get("ours") is False:
        record("open", address, _by(request), "refused", "answered, but not this office's edge")
        return JSONResponse({"error": f"בכתובת {address} ענה משהו — אבל זו אינה הלשכה הזו. "
                                      "אפשר ללחוץ «מצא את כתובת המכונה» ולפתוח את הכתובת שהיא תמצא.",
                             "probe": checked}, status_code=422)
    status, out, err = http("PUT", f"{APPMGMT}/api/network",
                            {"routes": [{"kind": "lan", "address": address, "enabled": True}]})
    if status != 200:
        record("open", address, _by(request), "refused",
               str((out or {}).get("refused") if isinstance(out, dict) else err)[:200])
        return JSONResponse({"error": (out or {}).get("error") if isinstance(out, dict) else err,
                             "refused": (out or {}).get("refused") if isinstance(out, dict) else None},
                            status_code=status or 502)
    applied = _converge()
    record("open", address, _by(request), "ok" if applied.get("ok") else "written",
           "" if applied.get("ok") else str(applied.get("detail"))[:200])
    return {"ok": True, "written": bool((out or {}).get("written")), "applied": applied,
            "view": routes_view()}


@app.delete("/api/routes/lan")
def api_close_lan(request: Request):
    """Close it — the declaration stays (the address is remembered), `enabled: false` is the door."""
    status, out, err = http("PUT", f"{APPMGMT}/api/network",
                            {"routes": [{"kind": "lan", "address": _declared_address(), "enabled": False}]})
    if status != 200:
        return JSONResponse({"error": (out or {}).get("error") if isinstance(out, dict) else err},
                            status_code=status or 502)
    applied = _converge()
    record("close", _declared_address(), _by(request), "ok" if applied.get("ok") else "written")
    return {"ok": True, "applied": applied, "view": routes_view()}


def _declared_address() -> str:
    decl, _why = declared()
    lan = next((r for r in decl if isinstance(r, dict) and r.get("kind") == "lan"), None)
    return str((lan or {}).get("address") or "")


def _converge() -> dict:
    """Ask the control plane to converge the estate — the step that makes a written route live.

    Not a shell, not a compose file: the same endpoint the console's own lifecycle uses. Its answer
    is passed through, including a failure, and the screen re-reads the state instead of assuming.
    """
    status, body, err = http("POST", f"{APPMGMT}/api/reconcile", {}, timeout=600)
    ok = status == 200 and isinstance(body, dict) and body.get("ok") is not False
    return {"ok": bool(ok), "status": status,
            "detail": (body or {}).get("error") if isinstance(body, dict) else err}


@app.get("/")
def index() -> FileResponse:
    """The screen. Served at `/` because the console proxies this app at `/a/office-routes/` and
    strips the prefix (`module.embed`): the app's own paths are its own, and the shell injects the
    base."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/a/office-routes")
def index_trailing() -> RedirectResponse:
    """A browser that typed the console's own path without its slash ends up in the same place."""
    return RedirectResponse("/", status_code=307)


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
          name="static")
