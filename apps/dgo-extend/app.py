"""dgo-extend — further digital dgo-extend on the office's machines, declared from here.

What this app is
----------------
A digital office runs on one machine. When one machine is not enough — memory, a public address,
a client that needs its own office — the answer is another office on another machine, and this
app is where that other office is DECLARED and kept true. It is the platform's own installer,
pointed at a machine the owner already connected in `computers`:

    pick a machine (computers)  ·  give it a domain (domains checks DNS)  ·  choose the code
    (this office's own repository and commit, the token from the git app)  ·  choose its apps
    →  converge: machine → dns → code → engine → env → state → run → health

The declaration is the source of truth
--------------------------------------
Each office is one YAML file in this app's volume (/data/dgo/<id>.yaml). Everything the remote
machine ends up with is derived from it on every converge, so a first install, an upgrade (change
`source.commit`) and a repair (converge again) are ONE operation, and a lost machine is rebuilt
from the same file. What is NOT derived is kept: the remote `.env` holds that office's own secrets
and is only ever extended with keys a newer version needs; its volumes are never touched.

The one door to a machine is `computers`
----------------------------------------
This container has no SSH client, key or engine socket. Every command is POSTed to
`computers /api/computers/<id>/exec`, so an office can only be built on a machine the owner has
approved the office key on, and every step is in that app's log.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
import traceback
import urllib.parse
from pathlib import Path

import requests
import yaml
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import catalog
import converge as cv
import declaration
import move as mv
import pair_api
import peers
import projection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dgo-extend")

STATE_DIR = Path(os.environ.get("DGO_STATE_DIR", "/data"))
DECL_DIR = STATE_DIR / "dgo"
RUN_DIR = STATE_DIR / "runs"
HOME_REPO = os.environ.get("DGO_HOME_REPO", "")
LOCAL_MACHINE = "computer_local-local"
REGISTRY_DIR = os.environ.get("DGO_REGISTRY_DIR", "/registry")
GIT_URL = os.environ.get("GIT_URL", "http://git:8978").rstrip("/")
APPMGMT_URL = os.environ.get("APPMGMT_URL", "http://app-management:8080").rstrip("/")
_STATIC = Path(__file__).parent / "static"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
DOMAIN_RE = re.compile(r"^(?=.{4,200}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

app = FastAPI(title="dgo-extend", docs_url=None, redoc_url=None)


@app.exception_handler(cv.StepFailed)
async def _refused_in_words(_request: Request, exc: cv.StepFailed):
    """A refusal is an ANSWER. `StepFailed` carries the sentence the owner reads and what to do about
    it, and it is raised by the readers every route here starts with (`home_office()` on an office
    with no identity, first of all). Unhandled, each of those routes answered a bare 500 — measured
    2026-10-05 on a brand-new office: `GET /api/link`, `/api/pair` and every pairing verb said
    "Internal Server Error" while the reason and the remedy were in the exception. 409, with the
    same words in `error` that the screens already know how to show."""
    return JSONResponse({"error": pair_api.worded_refusal(exc) or str(exc),
                         "reason": exc.reason, "action": exc.action}, status_code=409)


class _FreshStatic(StaticFiles):
    """The app's own scripts and styles, always REVALIDATED. Without this a browser keeps yesterday's
    `app.js` beside today's `index.html` for as long as its heuristic cache likes — measured
    2026-10-05: after a rebuild the page drew the new header and the OLD cards, which reads as "the
    fix did not work". `no-cache` still lets the browser reuse the file when its ETag matches."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _FreshStatic(directory=str(_STATIC)), name="static")


def _err(message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


# ── declarations ────────────────────────────────────────────────────────────────
def _path(oid: str) -> Path:
    return DECL_DIR / f"{oid}.yaml"


def load(oid: str) -> dict | None:
    p = _path(oid)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text()) or None


def save(office: dict) -> None:
    DECL_DIR.mkdir(parents=True, exist_ok=True)
    office["updated_at"] = int(time.time())
    tmp = _path(office["id"]).with_suffix(".tmp")
    header = ("# A remote digital office, declared by the dgo-extend app. Converging makes the machine\n"
              "# match this file; edit it from the app (לשכות נוספות), not by hand.\n")
    tmp.write_text(header + yaml.safe_dump(office, allow_unicode=True, sort_keys=False))
    tmp.replace(_path(office["id"]))


def all_declarations() -> list[dict]:
    if not DECL_DIR.exists():
        return []
    out = []
    for p in sorted(DECL_DIR.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text())
            if d:
                out.append(d)
        except yaml.YAMLError:
            log.warning("unreadable declaration %s", p.name)
    return out


def machine_declarations() -> list[dict]:
    """The peers that are MACHINES — what a converge, a move or a fleet-shaped screen means.

    A `kind: paired` record (a peer that joined from the pairing screens) has no machine, no path and
    no source: it is a peer, not a converge target, and offering it to a step is how a `KeyError`
    becomes a Hebrew sentence nobody can act on."""
    return [d for d in all_declarations() if str(d.get("kind") or "office") != "paired"]


def paired_records() -> list[dict]:
    """The peers that joined by pairing: shown, linked, and never converged."""
    return [d for d in all_declarations() if str(d.get("kind") or "") == "paired"]


def validate(body: dict, existing: dict | None) -> tuple[dict | None, str | None]:
    d = dict(existing or {})
    for k in ("label", "machine", "domain", "path"):
        if k in body:
            d[k] = (body.get(k) or "").strip()
    if not existing:
        d["id"] = (body.get("id") or "").strip().lower()
        if not ID_RE.match(d["id"]):
            return None, "מזהה הלשכה: אותיות לטיניות קטנות, ספרות ומקף (2–31 תווים)"
        if load(d["id"]):
            return None, f"לשכה בשם {d['id']} כבר קיימת"
        d["created_at"] = int(time.time())
    if "source" in body:
        s = body.get("source") or {}
        d["source"] = {"repo": (s.get("repo") or "").strip(), "branch": (s.get("branch") or "").strip(),
                       "commit": (s.get("commit") or "").strip(), "account": s.get("account") or None}
    if "apps" in body:
        d["apps"] = {k: ("enabled" if v in (True, "enabled") else "disabled")
                     for k, v in (body.get("apps") or {}).items() if re.match(r"^[a-z0-9-]+$", k)}
    if "placement" in body:
        # PLACEMENT: the apps that belong to this office while they keep their tile at home. It is a
        # subset of what runs there by construction — placing an app that this office does not run
        # would advertise a door to nothing.
        want = body.get("placement") or []
        if isinstance(want, str):
            want = [x for x in want.replace(",", " ").split() if x]
        d["placement"] = sorted({str(x).strip() for x in want if str(x).strip()})
    if "engine" in body:
        d["engine"] = {"replace_docker": bool((body.get("engine") or {}).get("replace_docker"))}
    # the link plane's rules live in declaration.py: pure stdlib, so the gate can exercise them
    # without importing this module's web stack (measured: `import app` outside a container needs
    # `requests`, and a gate that cannot run is not a gate).
    d, err = declaration.apply_link_plane(body, d)
    if err:
        return None, err
    if not d.get("machine"):
        return None, "בחר מחשב"
    if d["machine"] == LOCAL_MACHINE:
        return None, "המחשב הזה כבר מריץ את הלשכה הזו — בחר מחשב אחר"
    if not DOMAIN_RE.match(d.get("domain") or ""):
        return None, "דומיין לא תקין (לדוגמה office2.example.co.il)"
    d.setdefault("path", "")
    if not d["path"]:
        d["path"] = f"/opt/digital-office/{d['id']}"
    if not d["path"].startswith("/") or ".." in d["path"] or not re.match(r"^[\w./ -]+$", d["path"]):
        return None, "תיקיית ההתקנה חייבת להיות נתיב מלא במחשב"
    src = d.get("source") or {}
    if not src.get("repo") or not re.match(r"^[0-9a-f]{7,40}$", src.get("commit") or ""):
        return None, "בחר מקור קוד וגרסה (commit)"
    d.setdefault("apps", {})
    d.setdefault("placement", [])
    d.setdefault("engine", {"replace_docker": False})
    not_here = [a for a in d["placement"] if d["apps"].get(a) != "enabled"]
    if not_here:
        return None, ("אפליקציה שמוצהרת כ־placement חייבת גם להיות מופעלת בלשכה הזו: " +
                      ", ".join(not_here))
    d.setdefault("label", d["id"])
    return d, None


# ── runs ────────────────────────────────────────────────────────────────────────
_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


def _run_file(oid: str) -> Path:
    return RUN_DIR / f"{oid}.json"


def last_run(oid: str) -> dict | None:
    with _runs_lock:
        if oid in _runs:
            return json.loads(json.dumps(_runs[oid]))
    p = _run_file(oid)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return None
    return None


def _persist(run: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    p = _run_file(run["office"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False))
    tmp.replace(p)


def _execute(office: dict, run: dict, only: list[str]) -> None:
    ctx: dict = {}
    oid = office["id"]

    def emit(line: str, step: str | None = None) -> None:
        with _runs_lock:
            run["log"].append({"t": int(time.time()), "step": step or run.get("current"), "line": line[:2000]})
            del run["log"][:-1500]

    try:
        # `cv.STEPS + cv.EXTRA_STEPS`: a step that is only ever asked for BY NAME (`unlink`) is still a
        # step this loop has to reach. Iterating only the default list meant `{"steps":["unlink"]}`
        # silently ran nothing and reported success — measured 2026-10-01, when a revoke left the
        # tunnel standing and the run said `ok`.
        for name in cv.STEPS + cv.EXTRA_STEPS:
            st = run["steps"][name]
            if name not in only and name not in ("machine",):
                st["status"] = "skipped"
                continue
            with _runs_lock:
                run["current"] = name
                st.update(status="running", started=int(time.time()))
            emit(f"── {cv.STEP_TITLES[name]}", name)
            try:
                res = cv.RUNNERS[name](office, ctx, lambda ln, n=name: emit(ln, n))
                with _runs_lock:
                    st.update(status="warn" if res.get("warnings") else "ok", result=res,
                              ended=int(time.time()))
                emit(f"✓ {res.get('summary', '')}", name)
                for w in res.get("warnings") or []:
                    emit(f"⚠ {w}", name)
                _persist(run)
            except cv.StepFailed as e:
                with _runs_lock:
                    st.update(status="failed", ended=int(time.time()),
                              error={"reason": e.reason, "action": e.action, "detail": e.detail})
                    run["status"] = "failed"
                emit(f"✗ {e.reason}", name)
                return
        with _runs_lock:
            run["status"] = "ok"
            if ctx.get("health"):
                run["health"] = ctx["health"]
    except Exception as e:  # a bug here must still end the run visibly, never hang it as "running"
        log.error("converge %s crashed: %s", oid, traceback.format_exc())
        with _runs_lock:
            run["status"] = "failed"
            cur = run["steps"].get(run.get("current") or "", {})
            cur.update(status="failed", error={"reason": "שגיאה פנימית",
                                                "action": "", "detail": str(e)})
    finally:
        with _runs_lock:
            run["ended"] = int(time.time())
            run["current"] = None
            _persist(run)
            _runs.pop(oid, None)


def start_run(office: dict, only: list[str] | None) -> dict:
    oid = office["id"]
    with _runs_lock:
        if oid in _runs:
            return {"error": "הלשכה כבר בתהליך", "run": _runs[oid]}
        run = {"office": oid, "status": "running", "started": int(time.time()), "ended": None,
               "commit": (office.get("source") or {}).get("commit"), "current": None,
               "steps": {s: {"status": "pending", "title": cv.STEP_TITLES[s]}
                         for s in cv.STEPS + cv.EXTRA_STEPS},
               "log": []}
        _runs[oid] = run
    # `cv.EXTRA_STEPS` (unlink) are askable BY NAME and never part of a default converge.
    allowed = cv.STEPS + cv.EXTRA_STEPS
    only = [s for s in (only or cv.STEPS) if s in allowed]
    threading.Thread(target=_execute, args=(office, run, only), daemon=True,
                     name=f"converge-{oid}").start()
    return {"run": run}


# ── context from the other apps ─────────────────────────────────────────────────
def home_source() -> dict:
    """This office's own code: repository, branch, commit — read on the machine that runs it."""
    if not HOME_REPO:
        return {"error": "DGO_HOME_REPO לא הוגדר (bbox מגדיר אותו)"}
    r = cv.exec_on(LOCAL_MACHINE,
                   f"cd {cv.q(HOME_REPO)} && echo repo=$(git remote get-url origin) && "
                   f"echo branch=$(git rev-parse --abbrev-ref HEAD) && echo commit=$(git rev-parse HEAD) && "
                   f"echo dirty=$(git status --porcelain --untracked-files=no | wc -l) && "
                   f"echo pushed=$(git branch -r --contains HEAD 2>/dev/null | head -1 | tr -d ' ') && "
                   f"echo subject=$(git log -1 --format=%s | head -c 140)", 40)
    if r.get("code") != 0:
        return {"error": r.get("reason") or (r.get("stderr") or "")[-300:]}
    f = cv.parse_facts(r.get("stdout") or "")
    f["dirty"] = int(f.get("dirty") or 0)
    # Where the checkout IS, on the machine that runs this office. Reported, not guessed: the office's
    # path is a Hebrew name with a TRAILING SPACE, and a caller that hardcodes it reads a directory
    # that does not exist — which looks exactly like a missing app.
    f["path"] = HOME_REPO
    return f


def _get(url: str, timeout: float = 30) -> dict:
    try:
        return cv._http("GET", url, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — a neighbour being down is a state to show, not a crash
        return {"error": f"{type(e).__name__}"}


# ── routes ──────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Ready = the one door this app uses for EVERY machine is reachable (`computers`).

    Its `/healthz` answers `{"status":"ok","office_key":true}`, and this route read `.get("ok")` —
    which is what it did from the day it was written, so a perfectly healthy office answered 503
    here and `readyz` was a constant "no" for anyone who read it (found by the route gate in
    `tests/phase1.py` on 2026-09-30). Accept the neighbour's own spelling rather than renaming its
    contract, and answer WHICH side is missing: a readiness probe that cannot say why is a probe
    whose reader learns to ignore it.
    """
    r = _get(f"{cv.COMPUTERS_URL}/healthz", 5)
    ok = r.get("status") == "ok" or r.get("ok") is True
    return JSONResponse({"ready": ok, "computers": r.get("status") or r.get("error") or "unreachable"},
                        status_code=200 if ok else 503)


@app.get("/manifest")
def manifest():
    return {"id": "dgo-extend", "interface": "dgo-extend.v1",
            "ops": ["list", "create", "delete", "converge", "status"]}


@app.get("/api/office/{oid}/login")
def api_login(oid: str):
    """How the owner gets INTO a deployed office: its console address and the account the deployment
    created for them.

    Read from the credential plane (the `dgo_login-<office>` instance the converge captured), not from
    the machine's `.env` — so the screen shows a secret the vault holds and audits the read, and a
    converge that has never run has nothing to reveal instead of pretending.
    """
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    cid = f"dgo_login-{oid}"
    # Through the vault helper the converge uses, not a second HTTP client: this route shipped once
    # with its own `requests.get` and an undefined `CONNECTIONS_URL`, so the button the owner presses
    # to get into a remote office answered `500 NameError` — a read path with no test behind it.
    try:
        secret = cv.vault_secret(cid)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        log.warning("api_login: %r", e)
        return _err("כספת האישורים אינה זמינה", 502)
    if not secret:
        return _err("עוד לא נשמרו פרטי כניסה ללשכה הזו — הרץ converge", 404)
    return {"login": {"url": secret.get("url") or f"https://console.{o['domain']}/",
                      "email": secret.get("email"), "password": secret.get("password"),
                      "admin_email": secret.get("admin_email"),
                      "admin_password": secret.get("admin_password"),
                      "instance": cid}}


def _dial_endpoint(office: dict) -> str:
    """The address to DIAL for a peer: the fleet's answer first, the declaration's second.

    `computers` already knows where that machine is (the address its SSH connection uses), and an IP
    is the only form `wg-quick` can apply INSIDE a container: this platform's containers get a
    resolver that does not answer for public names (measured), so a rendered
    `Endpoint = staging.digital-office.co.il:51820` makes `wg-quick up` fail with "Name or service not
    known" — and, because the applier logs that and carries on, the office runs with NO tunnel while
    every screen says the link is up. Measured on 2026-10-01: exactly this reproduced on this office
    the moment the home side was rendered here instead of by `step_link` (which resolves it the same
    way, in `converge._dial_address`).
    """
    declared = (office.get("tunnel") or {}).get("endpoint") or office.get("domain") or ""
    try:
        host = (cv.machine_record(office.get("machine") or "").get("host") or "").strip()
    except Exception:                                   # noqa: BLE001 — the fleet is a neighbour
        host = ""
    if host:
        return host
    try:
        return cv._dial_address(declared)
    except Exception:                                   # noqa: BLE001 — falls back to the declaration
        return declared


# ── the one hop this office does not control: the source port of its own tunnel ──────────────────
# A dialing office's UDP source port is the single part of the path nobody can be asked about, and a
# home NAT/router (or the engine's own guest network) can start dropping exactly that flow while every
# other flow from the same machine crosses normally. Measured TWICE on this office, the same way both
# times: 2026-10-04 on port 51820 and 2026-10-06 on 51832 — the tunnel counted its handshake
# initiations as sent, `tcpdump` on the office's own machine showed every 148-byte initiation leaving
# (`192.168.5.15.<port> > 31.97.196.82.51820`), the server's `tcpdump` saw NONE of them while 13-byte
# control packets on other source ports arrived, and `wg set wg0 listen-port 51830` (respectively
# `wg set wg2 listen-port 51900`) handshook within seconds.
#
# So a pair this office DIALS, and that stays unreachable, gets a FRESH source port — and where it
# landed is recorded, because a port that changes on every render is a link that re-handshakes for no
# reason. The far end needs to know nothing: its peer entry carries no Endpoint (it learns this
# office's address from the handshake it receives), and the port the far end LISTENS on is never
# touched here, because that one is the address this office dials.
LISTEN_PORTS_FILE = "listen-ports.json"
#: A dialed pair unreachable this long gets a fresh source port.
HEAL_AFTER = float(os.environ.get("DGO_LINK_HEAL_SECONDS", "180"))
#: …never in a loop: one rotation per pair per window, whatever asks for it.
HEAL_COOLDOWN = float(os.environ.get("DGO_LINK_HEAL_COOLDOWN", "600"))
#: …and not forever: a peer that stays away for a week is away, not mis-ported.
HEAL_MAX = int(os.environ.get("DGO_LINK_HEAL_MAX", "6"))


def _listen_ports() -> dict:
    """`{office: {port, at, count}}` — where this office moved its own port, per pair. Unreadable
    file = nothing was ever moved, which is the state every office starts in."""
    try:
        doc = json.loads((STATE_DIR / LISTEN_PORTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def rotated_port(oid: str) -> int | None:
    """The port this office moved ITS side of one pair to, or None when it never had to."""
    try:
        port = int((_listen_ports().get(oid) or {}).get("port") or 0)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _write_listen_ports(doc: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / LISTEN_PORTS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _taken_ports() -> set[int]:
    """Every listen port the RENDERED plan holds right now — the block a rotation must not land in."""
    taken: set[int] = set()
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    for conf in sorted(base.glob("pairs/*.conf")) + ([base / "wg0.conf"] if (base / "wg0.conf").exists() else []):
        try:
            for line in conf.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ListenPort"):
                    taken.add(int(line.split("=", 1)[1].strip()))
        except (OSError, ValueError):
            continue
    return taken


def rotate_listen_port(oid: str, why: str = "") -> dict:
    """Move THIS office's own listen port for one pair, and re-render the tunnel around it.

    Refused (with a sentence, never silently) when the pair is not one this office dials — the port a
    peer dials is the port it must keep — and when the pair's record already agreed a port with that
    peer (a pairing's `tunnel.listen_port`, which is an agreement between two offices and not a local
    preference). Returns the port it moved to, or the reason it did not.
    """
    import net as netmod
    home = cv.home_office()
    records = {d["id"]: d for d in all_declarations()}
    pair = next((p for p in _link_pairs(home, records) if p["office"] == oid), None)
    if not pair:
        return {"office": oid, "ok": False, "reason": "אין זוג מקושר ללשכה הזאת"}
    if pair["dial"] != "home":
        return {"office": oid, "ok": False,
                "reason": "הצד שמחייג הוא הלשכה האחרת — הפורט שלה הוא הכתובת שמחייגים אליה"}
    if (pair["record"].get("tunnel") or {}).get("listen_port"):
        return {"office": oid, "ok": False,
                "reason": "לזוג הזה יש פורט מוסכם עם הלשכה האחרת — אין להזיז אותו כאן"}
    slot = int(pair["slot"] or 0)
    base = int(netmod.local_listen_port("home", slot=0))       # `DGO_WG_PORT`, the pair's block
    seen = _listen_ports()
    entry = dict(seen.get(oid) or {})
    count = int(entry.get("count") or 0)
    if count >= HEAL_MAX:
        return {"office": oid, "ok": False, "port": rotated_port(oid), "count": count,
                "reason": f"הפורט הוזז {count} פעמים והקישור עודו למטה — זו אינה בעיית פורט"}
    taken = _taken_ports()
    port = 0
    for step in range(count + 1, count + 64):
        candidate = base + 100 * step + slot
        if candidate <= 65535 and candidate not in taken:
            port = candidate
            break
    if not port:
        return {"office": oid, "ok": False, "reason": "לא נמצא פורט פנוי להזזה"}
    entry.update({"port": port, "at": time.time(), "count": count + 1, "why": why})
    seen[oid] = entry
    _write_listen_ports(seen)
    rendered = render_tunnel()
    log.warning("link %s: moved this office's own port to %d (%s)", oid, port, why or "no reason given")
    return {"office": oid, "ok": True, "port": port, "count": count + 1, "tunnel": rendered}


FIND_FILE = "find-peer.json"
#: Down this long before this office goes LOOKING for a peer (seconds).
FIND_AFTER = float(os.environ.get("DGO_LINK_FIND_SECONDS", "300"))
#: Between two searches of the same pair.
FIND_COOLDOWN = float(os.environ.get("DGO_LINK_FIND_COOLDOWN", "900"))
#: Searches per episode — a machine that is switched off is not a lease that moved.
FIND_MAX = int(os.environ.get("DGO_LINK_FIND_MAX", "3"))
#: Addresses tried per search, nearest to the address that was lost first. Each one costs up to five
#: seconds (a probe waits for a handshake, which is not instant), so this is the bound on how long the
#: tunnel container is busy looking: 64 addresses ≈ 5 minutes worst case, and a DHCP pool that moved is
#: a few addresses away. A search that finds nothing says so and is retried, bounded by FIND_MAX.
FIND_CANDIDATES = int(os.environ.get("DGO_LINK_FIND_CANDIDATES", "64"))


def _find_state() -> dict:
    """`{office: {count, at, want, endpoint, tried}}` — the searches this office has run. An entry
    without `want` is a finished one: its count and clock decide when the next may start."""
    try:
        doc = json.loads((STATE_DIR / FIND_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_find_state(doc: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / FIND_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _scan_path(name: str) -> Path:
    return Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")) / name


def find_peer(oid: str, why: str = "") -> dict:
    """Ask the tunnel container to LOOK for a dialed peer whose address moved, and remember the ask.

    A pair's endpoint is a fact of the PAIRING — one address, written on both ends — so nothing local
    notices when a home router hands the machine a different one. Measured 2026-10-07: hp-laptop's
    Wi-Fi came back as `192.168.16.100`, the pair still said `192.168.16.102`, the handshake was
    counted as sent for hours and every repair this office had (a fresh source port) could not help —
    it was dialing an address nobody held. What helps is going to look, and a WireGuard handshake is
    the identification: only the holder of that key completes one. The probing happens in the tunnel
    container, which owns the interface (`scan.cmd` → `scan.result`, line protocol, no JSON in shell);
    this function decides WHAT to look for and records the ask.

    Refusals, each named: a pair this office does not dial (the address that moved is ours to be
    FOUND at, not to look for), an endpoint that is not a LAN address (a name or a public address is a
    decision, never a DHCP lease — see `net.lan_address`), a record with no peer key to identify, and
    — since 2026-10-12 (lnk-032) — a LAN address this office cannot dial at all: an office at a
    public address has no business probing a home /24 that no packet of it crosses, and that search
    cost 8½ minutes of the tunnel's own measurement to prove nothing.
    """
    import net as netmod
    home = cv.home_office()
    records = {d["id"]: d for d in all_declarations()}
    pair = next((p for p in _link_pairs(home, records) if p["office"] == oid), None)
    if not pair:
        return {"office": oid, "ok": False, "reason": "אין זוג מקושר ללשכה הזאת"}
    if pair["dial"] != "home":
        return {"office": oid, "ok": False,
                "reason": "הלשכה הזאת אינה זו שמחייגת לזוג הזה — הכתובת שהשתנתה היא שלנו, ואנחנו "
                          "נמצאים על ידי החיפוש שלה"}
    endpoint = str(pair.get("endpoint") or "")
    if not netmod.lan_address(endpoint):
        return {"office": oid, "ok": False, "endpoint": endpoint,
                "reason": f"הקצה של הזוג ({endpoint or 'לא הוגדר'}) אינו כתובת ברשת מקומית — אין /24 "
                          f"לחפש בו, וכתובת כזאת משתנה בהחלטה ולא בהקצאה"}
    if not netmod.dialable_from_here(endpoint, (pair_api.listen_from_env() or {}).get("endpoint") or ""):
        return {"office": oid, "ok": False, "endpoint": endpoint,
                "reason": f"הקצה של הזוג ({endpoint}) הוא כתובת מקומית שאיננה ברשת של הלשכה הזאת "
                          f"(הלשכה הזאת מפרסמת "
                          f"{(pair_api.listen_from_env() or {}).get('endpoint') or 'כלום'}) — אין לנו "
                          f"/24 לחפש בו. הזוג נכתב בכיוון ההפוך: יש לצמד מחדש."}
    try:
        port = int(pair.get("endpoint_port"))
    except (TypeError, ValueError):
        return {"office": oid, "ok": False, "reason": "לזוג אין פורט מוצהר לחפש עליו"}
    peer_key = str(((pair["record"].get("identity") or {}).get("wg") or "")).strip()
    if not peer_key:
        return {"office": oid, "ok": False,
                "reason": "לרשומת הזוג אין מפתח ציבורי — אין את מי לזהות בתשובת ה-handshake"}
    candidates = netmod.peer_candidates(endpoint, FIND_CANDIDATES)
    if not candidates:
        return {"office": oid, "ok": False, "reason": "לא נמצאו כתובות לחפש בהן"}
    want = f"{oid}-{int(time.time())}"
    lines = [f"want {want}", f"iface {netmod.iface_name(pair['slot'])}", f"peer {peer_key}",
             f"port {port}"] + [f"cand {ip}" for ip in candidates]
    path = _scan_path("scan.cmd")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    state = _find_state()
    entry = dict(state.get(oid) or {})
    state[oid] = {**entry, "want": want, "at": time.time(), "endpoint": endpoint, "port": port,
                  "candidates": len(candidates), "count": int(entry.get("count") or 0) + 1,
                  "why": why}
    _write_find_state(state)
    log.warning("link %s: looking for it on the /24 around %s (%s)", oid, endpoint,
                why or "no reason given")
    return {"office": oid, "ok": True, "want": want, "endpoint": endpoint, "port": port,
            "candidates": len(candidates), "count": state[oid]["count"]}


def collect_found_peer(oid: str, req: dict) -> dict | None:
    """Read the answer to a search and, when the peer was FOUND, write the address it answered from.

    None means "still looking". A found address is written by the ONE writer for the fields a link
    decides (`converge.save_declaration`), and the render that follows is what makes the sidecar dial
    it: nothing else about the pair moves — not the port, not the key, not the record's identity.
    """
    answer = {}
    try:
        for line in _scan_path("scan.result").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(" ")
            answer[key.strip()] = value.strip()
    except OSError:
        answer = {}
    if answer.get("want") != req.get("want"):
        if time.time() - float(req.get("at") or 0) < float(os.environ.get("DGO_LINK_FIND_GIVE_UP", "900")):
            return None                                   # still looking
        state = _find_state()
        state[oid] = {k: v for k, v in (state.get(oid) or {}).items() if k != "want"}
        _write_find_state(state)
        return {"office": oid, "ok": False,
                "reason": "החיפוש לא הסתיים בזמן — לא נגענו בכתובת של הזוג"}
    try:
        tried = int(answer.get("tried") or 0)
    except ValueError:
        tried = 0
    found = str(answer.get("found") or "").strip()
    state = _find_state()
    state[oid] = {**{k: v for k, v in (state.get(oid) or {}).items() if k != "want"},
                  "tried": tried, "at": time.time()}
    if not found:
        _write_find_state(state)
        return {"office": oid, "ok": False, "tried": tried, "endpoint": req.get("endpoint"),
                "reason": f"העמית לא ענה מ-{tried} כתובות ברשת של {req.get('endpoint')} — הלשכה "
                          f"האחרת כבויה, או שעברה לרשת אחרת"}
    rec = load(oid)
    if not rec:
        _write_find_state(state)
        return {"office": oid, "ok": False, "reason": "אין לשכה כזו"}
    was = str((rec.get("tunnel") or {}).get("endpoint") or "")
    rec.setdefault("tunnel", {})["endpoint"] = found
    cv.save_declaration(rec)
    state[oid] = {**state[oid], "adopted": found, "was": was}
    _write_find_state(state)
    rendered = render_tunnel()
    log.warning("link %s: found at %s after %d address(es) (was %s) — the pair dials it now",
                oid, found, tried, was or "unknown")
    return {"office": oid, "ok": True, "endpoint": found, "was": was, "tried": tried,
            "tunnel": rendered}


def _find_and_wait(oid: str, timeout: float = 120.0) -> dict:
    """The deliberate form: start a search and wait for its answer (a screen, a CLI, a gate)."""
    state = _find_state()
    if not (state.get(oid) or {}).get("want"):
        started = find_peer(oid, "requested by hand")
        if not started.get("ok"):
            return started
    deadline = time.time() + timeout
    while time.time() < deadline:
        answer = collect_found_peer(oid, (_find_state().get(oid) or {}))
        if answer is not None:
            return answer
        time.sleep(2)
    return {"office": oid, "ok": False, "reason": "החיפוש עדיין רץ — התוצאה תופיע בלוח הלשכה"}


def adopt_live_endpoint(oid: str, pair: dict) -> dict | None:
    """Follow the ADDRESS THE TUNNEL IS ACTUALLY USING, whenever it is carrying traffic.

    A pair's endpoint is a fact of the pairing, and it can be wrong in both directions: a router hands
    the listening office a new lease and nothing here notices, or a repair writes an address that then
    stops answering. The interface knows better than any record — it learns its peer's address from the
    packets it receives, which is what WireGuard calls roaming — so when a pair is UP, the address in
    use is written back through the link's one writer and the render follows. Nothing is probed and
    nothing is guessed: an address that is carrying the catalog is an address that works.
    """
    import net as netmod
    live = str((_tunnel_measured().get(netmod.iface_name(pair["slot"])) or {}).get("endpoint") or "")
    live_ip = live.rsplit(":", 1)[0].strip("[]")
    if not live_ip or not netmod.lan_address(live_ip):
        return None                       # a name, or an address somebody decided on — not a lease
    rec = load(oid)
    if not rec:
        return None
    was = str((rec.get("tunnel") or {}).get("endpoint") or "")
    if was == live_ip:
        return None
    rec.setdefault("tunnel", {})["endpoint"] = live_ip
    cv.save_declaration(rec)
    render_tunnel()
    log.warning("link %s: the tunnel is using %s (the record said %s) — the pair follows it",
                oid, live_ip, was or "nothing")
    return {"office": oid, "ok": True, "endpoint": live_ip, "was": was, "adopted": "live"}


def heal_links(status: dict | None = None) -> list[dict]:
    """Give every DIALED pair that has been unreachable a fresh source port — once per window.

    Called from the projection's timer (so an office nobody is watching still heals) and from a
    converge's link step (so the repair happens inside the run that is already measuring). A pair that
    is up is never touched, and a rotation inside its cooldown is skipped: the cost of a rotation is a
    re-handshake, and paying it on a peer that is simply switched off is noise.

    The peer's state file carries WHEN IT WAS MEASURED, not when it went down (`projection.save_status`
    rewrites it every pass), so the "how long has it been away" clock is kept here, in the same record
    as the port: an office restarting must not reset the clock and postpone the repair forever.
    """
    import net as netmod
    status = projection.load_status(STATE_DIR) if status is None else status
    home = cv.home_office()
    records = {d["id"]: d for d in all_declarations()}
    out = []
    now = time.time()
    seen = _listen_ports()
    changed = False
    finds = _find_state()
    # An answer that arrived since the last pass is applied FIRST: the address the peer answered from
    # is the repair, and it outranks any further port rotation for that pair.
    for oid, req in list(finds.items()):
        if not req.get("want"):
            continue
        answer = collect_found_peer(oid, req)
        if answer:
            out.append(answer)
    for pair in _link_pairs(home, records):
        oid = pair["office"]
        state = status.get(oid) or {}
        if pair["dial"] != "home":
            continue
        entry = dict(seen.get(oid) or {})
        if state.get("ok"):
            if entry.get("down_since"):
                entry.pop("down_since", None)
                entry["count"] = 0                    # a link that came back starts a fresh budget
                seen[oid] = entry
                changed = True
            if finds.pop(oid, None):                  # …and a fresh episode may look again
                _write_find_state(finds)
            followed = adopt_live_endpoint(oid, pair)
            if followed:
                out.append(followed)
            continue
        if not entry.get("down_since"):
            entry["down_since"] = now                 # first sighting: measured, not yet repaired
            seen[oid] = entry
            changed = True
            continue
        down_for = now - float(entry["down_since"])
        # A pair whose dial target this office cannot reach at all is not repairable from here, by
        # either of the two repairs: moving our source port changes where a handshake comes FROM, and
        # searching a home /24 we are not on changes nothing at all (measured 2026-10-12: 8½ minutes
        # of probing, no peer, while the record was written the wrong way round — lnk-032). Saying so
        # is the repair; `_verdict` says it on every surface that lists the pair.
        if not netmod.dialable_from_here(pair.get("endpoint") or "",
                                         (pair_api.listen_from_env() or {}).get("endpoint") or ""):
            continue
        # TWO FAILURES, TWO REPAIRS — and neither can be told from the other locally: no handshake is
        # no handshake, whether a home NAT blackholed this office's source port or the router handed
        # the peer a different address. So both are tried, on their own clocks: the port is cheap and
        # immediate, and looking for the peer costs a bounded scan of one /24 (measured 2026-10-07,
        # hp-laptop: six rotations in a row did nothing, because the address had moved).
        find = dict(finds.get(oid) or {})
        if (not find.get("want") and down_for >= max(HEAL_AFTER, FIND_AFTER)
                and int(find.get("count") or 0) < FIND_MAX
                and (not find.get("at") or now - float(find["at"]) >= FIND_COOLDOWN)):
            out.append(find_peer(oid, why=f"{oid} לא ענתה {int(down_for)} שניות"))
            finds = _find_state()
        if down_for < HEAL_AFTER or (entry.get("at") and now - float(entry["at"]) < HEAL_COOLDOWN):
            continue
        out.append(rotate_listen_port(oid, why=f"{oid} לא ענתה {int(down_for)} שניות"))
        seen = _listen_ports()                        # the rotation recorded its own port
    if changed:
        _write_listen_ports(seen)
    return out


def _link_pairs(home: dict, records: dict) -> list[dict]:
    """Every linked pair this office holds — the ONE list both halves are rendered from.

    A pair is: which peer, which /24 (its record's slot), which END of it is ours (`tunnel.side` on a
    paired record; the convention `.1` on a converged declaration, because `step_link` renders the
    office that dials as `.1`), who dials, and what the peer may reach here.

    Built once, here, because the tunnel renderer and the delivery renderer must agree about the
    pairs: two lists derived twice is how a door ends up on an interface nothing dials.
    """
    import net as netmod
    out = []
    for pid, d in sorted((records or {}).items()):
        link = cv._link_of(d, home["id"])
        if not link:
            continue
        tun = d.get("tunnel") or {}
        paired = (d.get("kind") or "") == "paired"
        # `side`/`role` describe the office that HOLDS the record — us (contract §1), not the peer.
        # A declaration has neither: it is written about the peer, and the convention there is
        # unchanged — the office that converges is `.1`, the converged one is `.2`.
        our_side = netmod.pair_side(d, default=1) if paired else 1
        peer_side = 3 - our_side
        dials = netmod.holder_dials(d) if paired else netmod.we_dial(d, our_side)
        direction = netmod.link_direction(link)
        mirror = cv._mirror(direction)
        slot = int(tun.get("slot") or 0)
        out.append({
            "office": pid, "record": d, "link": link, "slot": slot,
            "peer_side": peer_side, "side": our_side,
            "direction": direction, "mirror": mirror,
            # who dials: a paired record answers with its own role (`holder_dials`), a declaration with
            # the vocabulary it was written in (`we_dial`), which is measured against the live pair.
            "dial": "home" if dials else "remote",
            "endpoint": _dial_endpoint(d), "endpoint_port": tun.get("port"),
            # Our UDP port for this pair. The side being DIALED listens on `tunnel.listen_port`, which
            # `validate_paired` derives as the listener's `port` (§3): a record that carries the port
            # but not the derived field still gets the right number here, and the dialing side keeps
            # `None` so its own port stays what it always was (`DGO_WG_PORT`) — unless THIS office had
            # to move it, and then the port it moved to is the port it holds (`rotated_port`).
            "listen_port": (rotated_port(pid) if dials
                            else (tun.get("listen_port") or tun.get("port"))),
            # `serve` on THIS office's link means "this office's apps are the ones that get opened", so
            # the port map is keyed by the peer id but filled from the SERVING side's own record — the
            # other way round opens a hole for ports nothing here ever agreed to expose. `both` serves
            # too: a reader that tests for `serve` alone renders a firewall with no accept for any
            # served port (measured 2026-10-01: a `serve:` declaration re-rendered this office's tunnel
            # and vps1's Bina stopped answering).
            "ports": (cv._served_ports_local(home, slot) if mirror in ("serve", "both") else {}),
        })
    return out


def render_tunnel(oid: str = "") -> dict:
    """Render THIS office's tunnel from the records it owns, and write it where `dgo-net` reads.

    Rendering and applying are separate on purpose: the plan (addresses, peers, the firewall that
    follows each link's DIRECTION) is decided here in one place, and the sidecar has no opinion about
    it. Nothing secret is returned — the WireGuard private key goes to a 600 file inside the tunnel
    volume and never into a response.

    A function and not only a route because the `serve:` list is one of its inputs: declaring a new
    served app has to re-render the rules that let it be delivered (DGO-24), not wait for the next
    converge.

    It renders the HOME side — the one the sidecar applies here — and the link lives in the PEER's
    record (`links: [{office: <this office>, direction: …}]`), so each peer is mirrored into this
    office's own view of the link (the same convention `step_link` uses). Rendering a DECLARATION
    instead was measured on 2026-10-01: with one peer declared, a `serve:` change wrote the PEER's
    firewall into this office's tunnel volume — no `accept` for a single served port — and the
    delivery that worked a minute earlier stopped answering, silently, on the side that had just
    declared it. `oid` renders that peer's own side as well, for shipping and inspection, and never
    writes it here.

    ONE PAIR, ONE INTERFACE (2026-10-04): every linked pair gets `pairs/wg<slot>.conf`, its own /24 and
    its own address for us (`tunnel.side`), and the firewall is the same declaration asked about all of
    them at once. `wg0.conf` is still written for the first pair — a compatibility copy for a reader
    written before pairs existed; the applier brings up `pairs/*.conf` and nothing else.
    """
    import identity
    import linkproxy
    import net as netmod
    records = {o["id"]: o for o in all_declarations()}
    if oid and oid not in records:
        return _err("אין לשכה כזאת", 404)
    if oid and (records[oid].get("kind") or "") == "paired":
        return _err("זו רשומת צימוד — הלשכה הזאת מרנדרת את הצד שלה בעצמה", 400)
    # The FAR end of a pair renders nothing here. Its tunnel runs on the machine (`wg-quick@wg0`),
    # rendered and shipped by the office that dials, and that office also wrote this volume's
    # `addressing.json` (the pair's slot — the number the door's port is derived from). With no link
    # declared on this side, a render here could only produce a peer-less tunnel: a second interface
    # inside this office's dgo-net and an `addressing.json` naming a slot of its own, so the door would
    # move to a port the dialing office never computes. The marker is the plan the dialer shipped.
    shipped = linkproxy.read(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")).get("plan") or {}
    if shipped.get("rendered_by") and not records:
        return {"rendered": [], "kept": f"the tunnel is rendered by {shipped['rendered_by']}",
                "proxy": {"rules": len(shipped.get("rules") or []), "refused": None}}
    home = cv.home_office()
    doc_id = identity.load()
    if not doc_id:
        return _err("אין זהות למכונה הזאת — הרצ `bbox dgo identity`", 409)

    pairs = _link_pairs(home, {k: v for k, v in records.items() if k != home.get("id")})
    out = []
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    if pairs or not oid:
        descriptors = []
        for p in pairs:
            descriptors.append({
                "slot": p["slot"], "side": p["side"], "dial": p["dial"],
                "listen_port": p["listen_port"], "ports": p["ports"],
                "peer": {"office": p["office"],
                         "public_key": netmod._key(p["record"].get("identity")),
                         "endpoint": p["endpoint"], "endpoint_port": p["endpoint_port"],
                         "direction": p["mirror"]},
            })
        try:
            doc = netmod.render_multi(descriptors)
        except netmod.NetError as e:
            return _err(f"מנהרת הלשכה הזאת לא רונדרה: {e}", 400)
        base.mkdir(parents=True, exist_ok=True)
        for name, text in sorted(doc["files"].items()):
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        # A plan that SHRANK must not leave the file of a pair that is gone — INCLUDING the legacy
        # `wg0.conf` copy: with it left behind, an `unpair` left the interface up with the revoked
        # peer's key and the applier's fallback brought it back on every restart (measured on
        # hp-laptop 2026-10-04). One list of what must die, decided by `net.stale_tunnel_files`.
        present = ["wg0.conf"] if (base / "wg0.conf").exists() else []
        if (base / "pairs").is_dir():
            present += [f"pairs/{f.name}" for f in sorted((base / "pairs").glob("*.conf"))]
        for name in netmod.stale_tunnel_files(doc["files"], present):
            try:
                (base / name).unlink()
            except OSError:
                pass
        secret = base / "wg-private.key"
        secret.write_text(doc_id["wg"]["private"], encoding="utf-8")
        secret.chmod(0o600)
        (base / "nftables.rules").write_text(doc["nftables"], encoding="utf-8")
        (base / "addressing.json").write_text(json.dumps(doc["addressing"], indent=2), encoding="utf-8")
        # Which source may open a door on the RECEIVING edge (DGO-21). Written next to the plan it was
        # rendered from, so the office that owns a door reads the list instead of deriving it a second
        # time — and so the gate can assert the artifact exists without a machine.
        (base / "edge-guard.json").write_text(json.dumps(doc["guard"], indent=2), encoding="utf-8")
        out.append({"office": home["id"], "ok": True, "peers": len(pairs),
                    "ifaces": [p["iface"] for p in doc["pairs"]],
                    "addressing": doc["addressing"]})

    # ── the PEER's own side, when one was asked for: returned, never written here ────────────────
    if oid:
        d2 = records[oid]
        link = cv._link_of(d2, home["id"]) or {}
        slot = int((d2.get("tunnel") or {}).get("slot") or 0)
        peer_side = {**d2,
                     "links": [{"office": home["id"], "direction": netmod.link_direction(link)}]}
        home_mirror = {**home, "links": [{"office": oid, "direction": cv._mirror(link.get("direction") or "use")}]}
        ids2 = {oid: d2.get("identity") or {}, home["id"]: home["identity"]}
        fw = {home["id"]: (cv._served_ports_local(d2, slot)
                          if (link.get("direction") or "use") in ("serve", "both") else {})}
        try:
            pdoc = netmod.render(peer_side, [home_mirror], ids2, fw,
                                 pair={"slot": slot, "side": 2, "dial": "remote"} if slot else None,
                                 host_forward=True)
            out.append({"office": oid, "ok": True, "side": "peer",
                        "addressing": pdoc["addressing"]})
        except netmod.NetError as e:
            out.append({"office": oid, "ok": False, "reason": str(e)})
    # The delivery plan follows the tunnel plan it belongs to, and after it: which ports get answered
    # depends on the addressing this call just decided.
    proxy = render_link_proxy()
    return {"rendered": out, "proxy": {"rules": len(proxy.get("rules") or []),
                                       "refused": proxy.get("refused")},
            "pairs": [{"office": p["office"], "slot": p["slot"], "side": p["side"],
                       "dial": p["dial"], "iface": f"wg{p['slot']}"} for p in pairs]}


@app.post("/api/tunnel/render")
async def api_tunnel_render(request: Request):
    """The route over `render_tunnel()` — what the converge step and the screen call."""
    body = (await request.json()) if await request.body() else {}
    oid = body.get("office") or ""
    if oid and oid not in {o["id"] for o in all_declarations()}:
        return _err("אין לשכה כזאת", 404)
    return render_tunnel(oid)


# ── the link's catalog: what THIS office says about its own apps (DGO-37) ────────────────────────
# One source, and it is the compiler's: `.generated/registry/office.apps.json` is rendered by layer 0
# from every enabled app's own manifest (see `platform/manager/reconcile.py`), so an app that is
# disabled here disappears from the peer's console in the same render. Everything below only MARRIES
# that file to this office's own `serve:` decisions (identity, exclusions, an explicit port).
_catalog_cache: dict = {"at": 0.0, "commit": ""}
_projection_state: dict = {}
_projection_started = threading.Event()
#: The contract's period: "on link up, every 60 seconds, and on demand".
PROJECTION_SECONDS = float(os.environ.get("DGO_PROJECTION_SECONDS", "60"))
#: …and seconds, not the period, while an office has only just gone silent (`projection.retried`):
#: the pass after the link's containers are re-created runs before the tunnel has shaken hands, and
#: the office read «לא עונה», its tiles marked off, for a whole minute beside a handshake seconds
#: old (2026-10-08, after every rebuild). Until the retries are spent it is «ממתינה לחיבור»; an
#: office that really is down costs them once — its count starts over only when it answers.
QUICK_RETRY_SECONDS = float(os.environ.get("DGO_PROJECTION_RETRY_SECONDS", "8"))
_silent: dict = {}                                      # office → passes in a row it did not answer


def _home_label(home: dict) -> dict:
    """This office's name for the far console, as the catalog's `label` (he/en).

    The office's own record keeps ONE string (`bbox dgo link label`, the name a person recognizes on
    the other side); the catalog publishes it under both keys, because a consumer renders one of them
    and an office with no English name should still say something rather than nothing.
    """
    label = home.get("label")
    if isinstance(label, dict):
        return {"he": str(label.get("he") or label.get("en") or home.get("id")),
                "en": str(label.get("en") or label.get("he") or home.get("id"))}
    # An office nobody named holds „הלשכה הזאת” about itself (`converge._home_office`'s default), and
    # published as-is that became the name on every tile and card of the OTHER office. Unnamed, an
    # office publishes its id — the same rule the pairing follows (`pair_api.own_label`).
    text = pair_api.own_label(home) or "local"
    return {"he": text, "en": text}


def _home_commit() -> str:
    """The commit this office runs. Cached: it costs a round trip through `computers` to the machine,
    and it changes only when someone converges this office."""
    now = time.time()
    have = _catalog_cache.get("commit")
    if have and now - float(_catalog_cache.get("at") or 0) < catalog.FETCH_TTL:
        return str(have)
    if have:
        # Stale: answer with the commit we know and refresh behind the answer. The read is a git
        # round trip through `computers`, and the catalog it feeds is what every link door fetches
        # for its route table — a slow minute there must not become a slow minute in a peer's tile.
        if not _commit_refreshing.is_set():
            _commit_refreshing.set()
            threading.Thread(target=_refresh_commit, daemon=True, name="catalog-commit").start()
        return str(have)
    return _refresh_commit()


_commit_refreshing = threading.Event()


def _refresh_commit() -> str:
    try:
        src = home_source() if HOME_REPO else {}
        commit = str((src or {}).get("commit") or "")
        if commit:
            _catalog_cache.update({"at": time.time(), "commit": commit})
        return commit
    except Exception:                                   # noqa: BLE001 — a catalog is not a commit
        return str(_catalog_cache.get("commit") or "")
    finally:
        _commit_refreshing.clear()


def _pair_slot(oid: str = "") -> int:
    """This office's slot in the pair it is linked to — the number the door's port is derived from.

    Read from the tunnel plan this office APPLIES (`addressing.json`, rendered by the end that
    rendered the pair), not from the home record: the home record's slot is this office's own and the
    pair's slot is the pair's, and the door's port has to be the SAME number on both ends. The home
    record is only a fallback for the moment before the first link exists.
    """
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    try:
        doc = json.loads((base / "addressing.json").read_text(encoding="utf-8"))
        # One address per PAIR (`net.render_multi`): the slot of the pair whose peer was asked about,
        # by name. Without a name the first pair answers, which is what a single-pair office means.
        entries = doc.get("pairs") or []
        # With ONE pair the first entry is the only answer. With several, the legacy single slot must
        # describe the pair whose FAR END reads it — a converged office runs whatever checkout it was
        # last converged to, and a paired office runs this code and reads `pairs[]`. Measured
        # 2026-10-04: after the first pairing, `pairs[0]` was the new pair (slot 4) and every peer was
        # told `link.port = 9004` — so the dev server's tiles pointed at a door it cannot reach and the
        # office there stopped reaching this one. A machine-declared peer comes first.
        pairs_kind = {str(d.get("id")): str(d.get("kind") or "office") for d in all_declarations()}
        machine = [e for e in entries if pairs_kind.get(str(e.get("office"))) != "paired"]
        chosen = next((e for e in entries if oid and e.get("office") == oid), None) \
            or (None if oid else ((machine or entries)[0] if entries else None))
        addr = str((chosen or {}).get("self") or ("" if oid else doc.get("self")) or "")
        parts = addr.split(".")
        if len(parts) == 4 and parts[:2] == ["10", "79"]:
            return int(parts[2])
    except (OSError, ValueError, IndexError):
        pass
    # The FAR end of a pair has no `addressing.json` in this volume: its tunnel runs on the machine
    # and the pair's record went to `.dgo/` there. The plan the dialing office shipped into this
    # volume carries the pair's slot, so the door's port is derived from the same number on both ends.
    # The home record's own slot would name a different door (measured on vps1: no declarations, so
    # its home slot is 1, while the pair is slot 2).
    try:
        import linkproxy
        plan = linkproxy.read(base).get("plan") or {}
        if plan.get("rendered_by") and int(plan.get("slot") or 0):
            return int(plan["slot"])
    except (OSError, ValueError, TypeError):
        pass
    try:
        return int((cv.home_office().get("tunnel") or {}).get("slot") or 0)
    except Exception:                                   # noqa: BLE001 — a catalog is not a link
        return 0


_sso_user_cache: dict = {}


def _default_identity() -> dict:
    """The identity a served app without its own mapping is presented under: this office's SSO user.

    Read once per process (`.env` through `computers`, the same source `converge._local_sso_user`
    uses for the legacy `serve:` block) — the catalog is fetched by every link door and must not pay
    an SSH round trip per fetch. An unreadable answer is not cached, so it is asked again next time.
    """
    user = _sso_user_cache.get("user")
    if not user:
        # DECLARED first (compose hands the same `.env` value this would otherwise read over SSH), then
        # the machine. An office with no door to its own machine has only the first — and without it
        # every app it gives arrived at the door with no identity to become (hp-laptop, 2026-10-05:
        # nine apps published, `identity: None` on each).
        user = (os.environ.get("DGO_SSO_USER") or "").strip()
        if not user:
            try:
                user = cv._local_sso_user() or ""
            except Exception:                           # noqa: BLE001 — a catalog is not an SSO read
                user = ""
        if user:
            _sso_user_cache["user"] = user
    return {"to": user} if user else {}


def _reached() -> dict:
    """Where each office that dials this one reaches it: its own word (`dials`) in the catalog it
    answered with on the last pass. Only an office that answered, in a pair where this one listens."""
    status = projection.load_status(STATE_DIR)
    mine = {d["id"] for d in cv.declarations() if pair_api.listens(d)}
    return {o: c["dials"] for o, c in catalog.load_all(STATE_DIR).items()
            if o in mine and (status.get(o) or {}).get("ok") and isinstance(c.get("dials"), str)}


def build_catalog(now: int | None = None, office: str = "") -> dict:
    """This office's app list, in the contract's shape — what a linked office pulls.

    The list is what this office SERVES and not what it has (DGO-32): `catalog.publishable` filters
    the compiled registry by the office's own `serve:` map before a single row is rendered, so a
    published app is always an app with a door behind it. `office` is the linked office the answer
    is FOR: the door of each pair asks in its own office's name, so an office narrowed by
    `serve.only` is told about — and routed to — its own apps alone.
    """
    home = cv.home_office()
    serve = catalog.app_specs(home.get("serve"))
    reg = catalog.publishable(catalog.load_registry(REGISTRY_DIR), home.get("serve"), office)
    rows = []
    for row in (reg.get("apps") or []):
        if not isinstance(row, dict):
            continue
        spec = serve.get(str(row.get("app"))) or serve.get(str(row.get("alias"))) or {}
        if not isinstance(spec, dict):
            spec = {"port": spec}
        row = dict(row)
        # An agent API is published when this office OPENS it, and the delivery plan opens one only
        # for an app `serve:` names with its `agent_api_port` (`linkproxy._serve_doors`). The
        # registry's own number used to travel regardless, so an office that gives everything
        # (`"*"`) told its peers about a port nothing answered on — and each peer built a listener
        # for it: a connection reset for the CLI, and one of the two listeners whose clash took the
        # MacBook's whole plan down (hp-laptop's 3081, 2026-10-05).
        row.pop("agent_api_port", None)
        try:
            if spec.get("port"):
                row["port"] = int(spec["port"])
            if spec.get("agent_api_port"):
                row["agent_api_port"] = int(spec["agent_api_port"])
        except (TypeError, ValueError):
            continue
        if spec.get("identity"):
            row["identity"] = spec["identity"]
        elif not (row.get("identity") or {}).get("to"):
            # An app served without a mapping of its own (every app under `serve: {"*": {}}`) is
            # presented as this office's own SSO user — the default the legacy `serve:` block has
            # always used (`converge._serve_block`). The door REPLACES the identity header with
            # this value, so publishing none made every wildcard app anonymous on arrival.
            default = _default_identity()
            if default:
                row["identity"] = default
        if "host" in spec:
            # The serving office's declaration wins over the manifest's authority; EMPTY publishes no
            # `host`, so the consuming edge passes the browser's own Host through (see
            # `converge._serve_block` for the measured reason).
            row["host"] = str(spec.get("host") or "").strip().lower()
        rows.append(row)
    import linkproxy
    import identity as _identity
    slot = _pair_slot()
    # This office's own mark travels with the catalog it publishes (flt-004): the peer draws the
    # tile with the name, never with a value of ours. From the identity, because the colour and the
    # animal are the office's (flt-001) — not a per-link setting.
    _mark = (_identity.public() or {}).get("mark")
    out = catalog.build({"apps": rows}, home.get("id") or "local", _home_label(home),
                        commit=_home_commit(), exclude=catalog.excluded(home.get("serve")),
                        now=now, mark=_mark,
                        link_port=linkproxy.door_port(slot) if slot else 0)
    # …and, for the office that asks, where this one's tunnel reaches IT (`pair_api.dials`):
    # additive, read by `pair_api.listen_now` on the other side and by nothing older.
    dials = pair_api.dials(next((d for d in cv.declarations() if d.get("id") == office), None), _tunnel_measured())
    return {**out, "dials": dials} if dials else out


def _link_proxy_addresses() -> set[str]:
    """The addresses the LINK PROXY speaks from on this network.

    `dgo-link` shares the tunnel container's namespace, so a connection it forwards arrives here from
    the tunnel container's own network address. Resolved by name (the compose service `dgo-net`)
    rather than written down: the address is Docker's, and a render that pinned it would stop matching
    the day the container is recreated — the same trap `linkproxy.py` exists to avoid.
    """
    host = os.environ.get("DGO_LINK_PROXY_HOST", "dgo-net")
    ips: set[str] = set()
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            for info in socket.getaddrinfo(host, None, family, socket.SOCK_STREAM):
                ips.add(str(info[4][0]).replace("::ffff:", ""))
        except OSError:
            continue
    return ips


def _link_proxy_bind() -> str:
    """The address the link proxy answers on for callers inside this office's network.

    The `use` half binds it, and it is resolved (never written down) because it is Docker's: a
    rendered address stops matching the day the container is recreated, which is the silent-delivery
    failure the whole delivery plane exists to avoid. Empty when it cannot be resolved — the plan then
    falls back to `0.0.0.0`, which is correct on an office that serves no catalog of its own (see
    `linkproxy._same_door` for why that is the exception rather than the rule).
    """
    ips = sorted(_link_proxy_addresses())
    return ips[0] if ips else ""


# ── what a linked office may ask of this one ─────────────────────────────────────────────────────
# A SECOND listener, and the whole of the answer is which routes it has. The link's control door is
# a raw splice (`linkproxy._serve_doors`): it carries bytes and has no opinion about paths, so
# whatever it leads to is what a peer can call. It led to this app's own port, and a pairing that
# gave one app therefore handed over every route above and below this line — unauthenticated, for
# as long as the tunnel was up (found 2026-10-05). The catalog route then defended itself by asking
# "is the caller the link proxy?", of an address this server takes from `X-Forwarded-For`
# (`--forwarded-allow-ips=*`), which any caller writes.
#
# So the door now leads HERE (`catalog.LINK_PORT`), where the only thing served is what the link is
# for. The edge never routes this port (the app's routing declares 8983 alone), and nothing in the
# office needs to be told who is calling: a route that is not on this listener does not exist for a
# peer. A new thing a peer may ask is a route added below — on purpose, in one place.
link_app = FastAPI(title="dgo-extend · link", docs_url=None, redoc_url=None, openapi_url=None)


@link_app.get("/api/link/catalog")
def api_link_catalog(request: Request):
    """The catalog a linked office pulls, and the route table this office's own door reads — both
    for ONE office: the door names the office its pair belongs to (`x-dgo-office`, written by the
    link proxy on every request that crosses it and never taken from the peer), and the answer is
    what that office is given. A caller inside this office names none and reads the whole list."""
    return build_catalog(office=request.headers.get("x-dgo-office") or "")


def _serve_link() -> None:
    import uvicorn

    class _Quiet(uvicorn.Server):
        def install_signal_handlers(self) -> None:      # the process's signals belong to the app
            return

    _Quiet(uvicorn.Config(link_app, host="0.0.0.0", port=int(catalog.LINK_PORT),
                          log_level="warning", access_log=False)).run()


def _project_once() -> dict:
    """One projection pass, then the delivery plan it feeds. Both halves of one fact — and then what
    the pass found about each office, handed to the console (`peers.publish_link`)."""
    result = projection.sync(cv, str(STATE_DIR), replan=render_link_proxy)
    fresh = projection.silent_passes(_silent, result.get("errors"))
    _silent.clear()
    _silent.update(fresh)
    try:
        healed = heal_links(projection.load_status(STATE_DIR))
        if healed:
            result["healed"] = healed
    except Exception as e:                              # noqa: BLE001 — a heal is not the plan
        log.warning("link heal failed: %s: %s", type(e).__name__, e)
    _projection_state.clear()
    _projection_state.update(result)
    items = api_link()["items"]
    peers.publish_link({it["office"]: it["verdict"] for it in items})
    _record_link_history(items, result.get("healed"))
    return result


# ── the link's own history: when it died, when it came back, and what fixed it ──────────────────
#: Every surface in this app answers "how is the link NOW". After the incidents of 2026-10-04…10-12
#: the question nobody could answer was the other one — and it is the one the owner asked on
#: 2026-10-12: «כמה אנחנו בטוחים שהחיבור הזה יחזיק לאורך זמן בתקווה שלא נצטרך לחבר שוב». A link that
#: never has to be paired again is a CLAIM; this file is the measurement behind it, and it is written
#: by the same projection pass that publishes the verdict, so the record and the screens cannot
#: disagree about what the link was doing.
LINK_HISTORY_FILE = "link-history.jsonl"
#: A pair whose state has NOT changed still says "measured, and alive" this often — a quiet week must
#: not be indistinguishable from a week nobody looked.
LINK_HEARTBEAT = float(os.environ.get("DGO_LINK_HISTORY_HEARTBEAT", "3600"))
#: Bounded: the newest lines are the ones a person reads.
LINK_HISTORY_MAX = int(os.environ.get("DGO_LINK_HISTORY_MAX", "4000"))


def _link_history_path() -> Path:
    return Path(STATE_DIR) / LINK_HISTORY_FILE


def load_link_history(limit: int = 50) -> list[dict]:
    """The last `limit` recorded lines, oldest first — `[]` when nothing was recorded yet."""
    try:
        lines = _link_history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    try:
        keep = max(1, int(limit))
    except (TypeError, ValueError):
        keep = 50
    out = []
    for line in lines[-keep:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue                                        # a torn line is not the link's state
        if isinstance(row, dict):
            out.append(row)
    return out


def _record_link_history(items: list[dict], healed: list[dict] | None = None) -> None:
    """Append what CHANGED since the last pass, and a heartbeat for what did not.

    `fixed_by` is the only honest answer to "who fixed it": a repair that ran in THIS pass, by name
    (`port 51932`, `found 192.168.16.100`) — a state that changed with no repair behind it came from
    the peer or from something a person did. A history that cannot be written is logged and dropped:
    it is not the plan, and a link must not die of a full disk.
    """
    path = _link_history_path()
    last: dict[str, dict] = {}
    for row in load_link_history(LINK_HISTORY_MAX):
        last[str(row.get("office") or "")] = row
    fixed: dict[str, str] = {}
    for h in healed or []:
        oid = str(h.get("office") or "")
        if not oid:
            continue
        fixed[oid] = (f"port {h['port']}" if h.get("port") else
                      f"found {h['found']}" if h.get("found") else
                      str(h.get("reason") or "heal"))
    now = int(time.time())
    out = []
    for it in items:
        oid = str(it.get("office") or "")
        v = it.get("verdict") or {}
        tun = it.get("tunnel") or {}
        state = (v.get("ok"), v.get("hop") or "")
        was = last.get(oid) or {}
        same = (was.get("ok"), was.get("hop") or "") == state
        if same and now - int(was.get("at") or 0) < LINK_HEARTBEAT:
            continue
        out.append({"at": now, "office": oid, "ok": state[0], "hop": state[1],
                    "why": v.get("why") or "", "handshake_age_s": tun.get("handshake_age_s"),
                    "rx": tun.get("rx"), "tx": tun.get("tx"),
                    "kind": "beat" if same else "change",
                    "fixed_by": "" if same else fixed.get(oid, "")})
    if not out:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for row in out:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > LINK_HISTORY_MAX:
            path.write_text("\n".join(lines[-LINK_HISTORY_MAX:]) + "\n", encoding="utf-8")
    except OSError as e:                                    # noqa: BLE001 — see the docstring
        log.warning("link history: %s", e)


def _project_loop() -> None:
    """The contract's timer. Never fatal: a peer that is asleep must not stop this app."""
    while True:
        wait = PROJECTION_SECONDS
        try:
            _project_once()
            if any(projection.retried(_silent, o) for o in list(_silent)):
                wait = QUICK_RETRY_SECONDS
        except Exception as e:                          # noqa: BLE001 — see the docstring
            log.warning("projection failed: %s: %s", type(e).__name__, e)
        time.sleep(wait)


def _start_projection() -> None:
    if _projection_started.is_set():
        return
    _projection_started.set()
    threading.Thread(target=_project_loop, daemon=True, name="dgo-projection").start()


@app.post("/api/link/exclude")
async def api_link_exclude(request: Request):
    """The app manager's show/hide switch: stop showing ONE app of ONE office on THIS console.

    `{"office": "vps1", "alias": "n8n", "hidden": true}`. It is this office's own record (`/data/
    exclude.json`), not the peer's: hiding an app from this rail must not take it away from every
    other office linked to the same peer, and the peer keeps running it either way. The peer's own
    `serve.exclude` — the apps it never publishes at all — is a different act, on the other side.

    A write, so it re-projects at once: the tile, the router and the alias disappear (or come back) in
    the same breath as the switch, and the answer carries the new state rather than a promise.
    """
    body = (await request.json()) if await request.body() else {}
    office = str(body.get("office") or "").strip().lower()
    alias = str(body.get("alias") or "").strip().lower()
    hidden = bool(body.get("hidden", True))
    try:
        block = projection.set_exclude(STATE_DIR, office, alias, hidden)
    except catalog.CatalogError as e:
        return _err(str(e), 400)
    result = await run_in_threadpool(_project_once)
    return {"exclude": block, "office": office, "alias": alias, "hidden": hidden,
            "projection": {"pulled": result.get("pulled"), "errors": result.get("errors"),
                           "block": result.get("block"), "state": result.get("state")}}


@app.get("/api/link/remote")
def api_link_remote():
    """What this office SHOWS of others: the catalogs it holds, and the block it projected.

    Two different facts, both reported: what was pulled (per peer, with the office's own label and
    the commit it was running) and what is DECLARED — read back off `platform.state.yaml` on the
    control plane, because the file is what the compiler renders and this process's memory is not.
    """
    stored = catalog.load_all(STATE_DIR)
    block = projection.read_state(cv)
    return {"catalogs": {oid: {"label": doc.get("label"), "commit": doc.get("commit"),
                               "generated_at": doc.get("generated_at"),
                               "apps": [{"alias": a.get("alias"), "app": a.get("app"),
                                         "title": a.get("title"), "port": a.get("port"),
                                         "api": a.get("api"), "host": a.get("host")}
                                        for a in (doc.get("apps") or [])]}
                         for oid, doc in sorted(stored.items())},
            "state": {"path": f"{HOME_REPO}/platform.state.yaml" if HOME_REPO else "",
                      "block": block},
            "last": _projection_state}


@app.post("/api/link/remote/sync")
async def api_link_remote_sync(request: Request):
    """Pull every linked peer's catalog NOW — the timer's pass, on demand.

    Runs in the threadpool on purpose: it waits on a peer over the tunnel (up to `FETCH_TIMEOUT` per
    office), and an `async def` endpoint doing that on the event loop would freeze this app's health
    check and every other request with it.
    """
    return await run_in_threadpool(_project_once)


def _pair_delivery(slot: int, state: dict) -> dict:
    """Is THIS pair's delivery up? The door here, and the catalog the peer published.

    Deliberately two facts and not one: "the door answers here" is the delivery half on our side
    (`linkproxy`'s listener for the pair, which is what the console's aliases reach), and "the catalog
    arrived" is the peer's half. Either one alone can be green while the link is dead — a tunnel that
    handshakes and delivers nothing was the whole of 2026-10-04 (`issues/
    the-link-goes-dark-after-every-tunnel-rebuild.yaml`), and no surface said so.
    """
    out = {"door": {"port": 0, "listening": False, "checked": False}, "catalog": {
        "ok": bool((state or {}).get("ok")), "at": (state or {}).get("at"), "error": (state or {}).get("error") or ""}}
    if not slot:
        return out
    try:
        import linkproxy
        port = linkproxy.door_port(slot)
    except Exception:                                   # noqa: BLE001 — a port is not a link
        return out
    out["door"]["port"] = port
    host = os.environ.get("DGO_LINK_PROXY_HOST", "dgo-net")
    try:
        with socket.create_connection((host, port), timeout=2):
            out["door"]["listening"] = True
    except OSError:
        out["door"]["listening"] = False
    out["door"]["checked"] = True
    out["up"] = bool(out["door"]["listening"] and out["catalog"]["ok"])
    return out


def _tunnel_measured() -> dict:
    """What the tunnel container last measured, by interface (`wg<slot>`), each with the age of its
    last handshake — and `{}` when it measures nothing: an image from before it did, or a container
    that has stopped (it writes every 15 s; a minute of silence is not a measurement any more).

    A handshake is renewed every two minutes while packets flow and a session is dead at three, so
    `alive` is "a handshake in the last 180 s". `handshake: 0` is "never, since the container started"."""
    try:
        doc = json.loads((Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")) / "wg-state.json").read_text())
        at = int(doc.get("at") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    now = int(time.time())
    if now - at > 60:
        return {}
    out = {}
    for name, m in (doc.get("pairs") or {}).items():
        shook = int(m.get("handshake") or 0)
        age = (now - shook) if shook else None
        out[name] = {"measured_at": at, "endpoint": "" if m.get("endpoint") == "(none)" else str(m.get("endpoint") or ""),
                     "handshake_at": shook or None, "handshake_age_s": age,
                     "alive": age is not None and age < 180,
                     "rx": int(m.get("rx") or 0), "tx": int(m.get("tx") or 0)}
    return out


#: A fallen hop, as a person is told about it — on this app's screen, on the tiles the console
#: marks and on the card it shows instead of a frame. Said here and nowhere else.
_HOP_HE = {
    "tunnel": "המנהרה אליה לא מעבירה תנועה: היא כבויה, מנותקת מהרשת, או שהקישור נפל.",
    "office": "המנהרה אליה פעילה, אבל הלשכה עצמה לא עונה — ייתכן שהיא מופעלת מחדש.",
    "door": "הדלת של הקישור בלשכה הזאת לא עונה, ולכן אף אפליקציה שלה לא נפתחת מכאן.",
    # Not a hop that fell but a pair that never could carry anything: this office dials a private
    # address that is not on any network of ours. Nothing here can be repaired — the pair is written
    # the wrong way round and has to be made again (measured 2026-10-12, lnk-032).
    "pair": "הצימוד הזה נכתב בכיוון שאי אפשר לחייג בו: הכתובת שאליה הוא מחייג היא כתובת מקומית "
            "שאיננה ברשת של הלשכה הזאת. צמדו מחדש — הלשכה הזאת תקשיב, והלשכה האחרת תחייג אליה.",
}


def _mispaired(d: dict, home: dict) -> bool:
    """Is this pair one this office DIALS into a private address it cannot be on?

    Reachability is a fact of the PAIR, and a pair made without asking it (`pair_api.claim` no longer
    writes one, but a record written before it does) cannot carry a byte: this office sends its
    handshake initiations to a home LAN it is not on, the other office sits listening for a dial that
    never arrives, and the only screens that spoke said „מחוברת”. The honest answer is neither
    "the office is not answering" nor "the tunnel is down" — nothing is broken here, the pairing is.

    A converged office (`kind: office`) is dialed at the address `computers` holds for its machine,
    which is reachable by construction, so this question is about paired records only.
    """
    if (d.get("kind") or "") != "paired":
        return False
    tun = d.get("tunnel") or {}
    dial, role = str(tun.get("dial") or ""), str(tun.get("role") or "")
    # `net.holder_dials`: the holder of a paired record dials exactly when `dial == role`.
    if dial not in ("host", "joiner") or dial != role:
        return False
    import net as _net
    return not _net.dialable_from_here(tun.get("endpoint") or "",
                                       (pair_api.listen_from_env() or {}).get("endpoint") or "")


def _verdict(state: dict, tunnel: dict | None, door: dict, mispaired: bool = False) -> dict:
    """ONE answer per linked office, for every surface that lists it: is it reachable from here, and
    if it is not, WHICH hop fell — `hop` for code, `why` for a person. `ok` is None while nothing
    has been measured — never a guess.

    * `pair`   — her catalog did not arrive and this pair's own DIAL TARGET cannot be reached from
      here at all: the record is written the wrong way round, and nothing on this side repairs it.
    * `tunnel` — her catalog did not arrive and no handshake completed in three minutes, or nothing
      measured the tunnel at all: the transport is down (she is off, off the network, or the link
      fell). "Not measured" is NOT "the tunnel is alive": the measurement goes quiet whenever the
      tunnel container is busy (measured 2026-10-12: an 8½-minute `/24` search left it unwritten and
      this verdict said „המנהרה אליה פעילה, אבל הלשכה עצמה לא עונה” over a tunnel that had never
      completed a handshake), and sending the owner to debug the far office's own health is the
      expensive way to be wrong.
    * `office` — her catalog did not arrive, and the tunnel was MEASURED alive: the transport works
      and the office behind it does not answer.
    * `door`   — her catalog arrived, and this pair's own door does not answer HERE: the fault is on
      this side, and every app of hers opened from this console fails.

    The screens used to work this out for themselves, each from different fields — and the console
    from none: it read a field nothing wrote."""
    if not state:
        return {"ok": None, "hop": "", "why": ""}
    if state.get("ok"):
        hop = "door" if door.get("checked") and not door.get("listening") else ""
    elif mispaired:
        hop = "pair"
    elif tunnel and tunnel["alive"]:
        hop = "office"
    else:
        hop = "tunnel"
    return {"ok": not hop, "hop": hop, "why": _HOP_HE.get(hop, "")}


@app.get("/api/link")
def api_link():
    """The link plane as it stands: this office's record, and every declared peer's link.

    Read-only and cheap — the CLI (`bbox dgo link status`) and the screen both need "is there a tunnel,
    and is it to the machine I think it is" without running a converge to find out.
    """
    import identity as _identity

    home = cv.home_office()
    decls = {d["id"]: d for d in cv.declarations()}
    stored = catalog.load_all(STATE_DIR)
    status = projection.load_status(STATE_DIR)
    hidden = projection.load_exclude(STATE_DIR)
    measured = _tunnel_measured()
    items = []
    for oid, d in sorted(decls.items()):
        link = cv._link_of(d, home["id"])
        cat = stored.get(oid) or {}
        # an office inside its quick retries is unmeasured, here and on every tile: not yet a verdict
        state = {} if projection.retried(_silent, oid) else status.get(oid) or {}
        up = bool(state.get("ok"))
        # The apps THIS office shows of that office — the pulled catalog, with each app marked
        # `hidden` when the show/hide switch removed it. The hidden ones are included on purpose: a
        # switch whose effect nobody can see is a switch nobody trusts, and the screen has to be able
        # to draw it back on.
        # "the peer published nothing" is a STATE, not a failure: an office whose `serve:` is empty
        # (or names only apps it has disabled) is reachable and healthy, and calling that "down" is
        # how a working link gets debugged as a broken one (measured 2026-10-04, hp-laptop).
        publishes_nothing = up and not (cat.get("apps") or [])
        apps = []
        for a in (cat.get("apps") or []):
            alias = str(a.get("alias") or "")
            apps.append({"alias": alias, "app": a.get("app"), "title": a.get("title"),
                         "icon": a.get("icon"), "port": a.get("port"), "api": a.get("api"),
                         "hidden": alias in set(hidden.get(oid) or []),
                         "ok": up})
        import net as _net
        # DELIVERY, per pair, and it is NOT the tunnel's state (a handshake can be alive while every
        # door is dead — measured 2026-10-04, and what the owner saw as 502). Two measured facts:
        # this pair's door answering HERE (`dgo-net:<door_port>`, the listener the plan rendered), and
        # the catalog the peer published (`state`/`error` from the projection's last pull).
        delivery = _pair_delivery(int((d.get("tunnel") or {}).get("slot") or 0), state)
        tunnel = measured.get(f"wg{int((d.get('tunnel') or {}).get('slot') or 0)}")
        items.append({"office": oid, "declared": bool(link),
                      "delivery": delivery,
                      # the TUNNEL itself, measured where its interface lives — absent when nothing
                      # measures it, so a screen says "not measured" and never guesses
                      "tunnel": tunnel,
                      "verdict": _verdict(state, tunnel, delivery["door"], mispaired=_mispaired(d, home)),
                      "publishes_nothing": publishes_nothing,
                      # `office` = a machine converged by SSH; `paired` = a peer that joined from the
                      # pairing screens and has no machine here. The screen must not offer to converge
                      # what has nothing to converge, and must not hide a peer it is linked to.
                      "kind": str(d.get("kind") or "office"),
                      # OUR end of that pair (a paired record's own side — contract §1), so the
                      # screen can say which address is ours over there.
                      "side": (_net.pair_side(d, default=1) if (d.get("kind") or "") == "paired"
                               else None),
                      "direction": (link or {}).get("direction"),
                      "peer_slot": (d.get("tunnel") or {}).get("slot"),
                      "endpoint": (d.get("tunnel") or {}).get("endpoint"),
                      "peer_fingerprint": ((d.get("identity") or {}).get("fingerprint")),
                      "machine": d.get("machine"),
                      # The name a PERSON reads (the tooltip and the phone tile print it): the
                      # declaration's own label first — it is the owner's word for that office — then
                      # what the office published about itself in its catalog, then the id.
                      "label": str(d.get("label") or (cat.get("label") or {}).get("he") or oid),
                      "state": "up" if up else ("down" if state else "unknown"),
                      "state_at": state.get("at"),
                      "state_error": state.get("error") or "",
                      # The office's MARK (flt-004): the pair it published with its catalog, or the pair
                      # its NAME gets when it has published none yet — the same fallback the console's
                      # registry uses (platform/manager/serve.py `_mark`), so the row here and the tile
                      # there are one colour, and an office nobody has chosen for yet is not a blank.
                      "mark": _identity.clean_mark(cat.get("mark")) or _identity.mark_for(oid),
                      "commit": cat.get("commit") or "",
                      "apps": apps})
    return {"home": {"id": home["id"], "domain": home["domain"], "slot": (home.get("tunnel") or {}).get("slot"),
                     "fingerprint": (home.get("identity") or {}).get("fingerprint"),
                     # where this office is dialed now — `moved_from` when its declaration is stale
                     "listen": PAIRING.ports.listen() or None},
            "serve": home.get("serve") or {},
            "items": items, "tunnel": api_tunnel(), "proxy": api_link_proxy()}


@app.get("/api/link/history")
def api_link_history(limit: int = 50):
    """Every pair's recorded transitions — the answer to "did it hold", not "is it up now".

    One line per CHANGE of (`ok`, `hop`), plus a heartbeat while nothing changes, written by the same
    pass that publishes the verdict (`_record_link_history`). `fixed_by` names the repair that ran in
    the pass the change was seen in: a port move, an address the search adopted, or nothing — which
    means the peer came back on its own. `./bbox dgo link history` prints this.
    """
    rows = load_link_history(limit)
    return {"items": rows, "limit": int(limit), "file": str(_link_history_path())}


@app.post("/api/link/heal")
async def api_link_heal(request: Request):
    """Repair a link that stops carrying traffic, on the one hop this office owns: its source port.

    `{"office": "vps1"}` moves THIS office's own UDP port for that pair to a fresh number and
    re-renders the tunnel (the sidecar applies it within ~15 seconds). It is the automatic repair
    (`heal_links`) as a deliberate act, for the screen and for a converge's link step — the failure it
    answers is a flow a home NAT/router blackholed, which is invisible from both ends and looks
    exactly like "the other office is off" (see `LISTEN_PORTS_FILE` above).
    """
    body = (await request.json()) if await request.body() else {}
    oid = str(body.get("office") or "").strip()
    if oid:
        return await run_in_threadpool(rotate_listen_port, oid, "requested by hand")
    return await run_in_threadpool(heal_links)


@app.post("/api/link/find")
async def api_link_find(request: Request):
    """Find a DIALED peer whose ADDRESS moved, and write the address it answers from into the pair.

    `{"office": "hp-laptop"}` — the second repair, beside `POST /api/link/heal`. A pair's endpoint is
    a fact of the pairing, so a home router that hands the machine a new lease leaves every packet
    going to an address nobody holds, and no local repair can help: this office has to go and look.
    The search is bounded (the lost address's own /24, nearest first, `DGO_LINK_FIND_CANDIDATES`),
    it only ever runs for a pair THIS office dials where the endpoint is a LAN address, and what it
    accepts as the peer is a completed WireGuard handshake — the key's owner and nobody else.
    """
    body = (await request.json()) if await request.body() else {}
    oid = str(body.get("office") or "").strip()
    if not oid:
        return _err("צריך לסמן לשכה (office)", 400)
    return await run_in_threadpool(_find_and_wait, oid)


@app.post("/api/link/serve")
async def api_link_serve(request: Request):
    """Declare the apps of THIS office that a peer may reach over a link.

    `serve: {"bina-ds": {"port": 3080, "agent_api_port": 3081}}` — read by the link step to open
    exactly those ports on this side's firewall and nothing else. It is a DECLARATION, not a switch:
    the port is what the peer's traffic is allowed to reach, so naming an app nobody runs opens a door
    to nothing and omitting one leaves a door closed that a person believes is open.

    `agent_api_port` is the SECOND door of one app (DGO-32): an agent app serves a UI a person opens
    and an adapter a CLI speaks to, and both are ports the firewall, the delivery plan and the peer's
    own route have to agree about. `identity.to` names the user of THIS office that a request
    arriving over the link becomes — the peer's edge writes it into the identity header — and `label`
    names this office on the peer's console, because "הלשכה הזאת" is not a name anyone recognizes
    from the other side.
    """
    body = (await request.json()) if await request.body() else {}
    serve = body.get("serve")
    if not isinstance(serve, dict):
        return _err("serve חייב להיות מפה של אפליקציה → פורט", 400)
    for app, spec in serve.items():
        if app == "exclude":
            # The one reserved key (DGO-37): the apps this office does NOT publish to a peer. It is
            # metadata of the same declaration and not an app, so it is validated as a list of
            # aliases and never read as a port.
            if not isinstance(spec, list):
                return _err("serve.exclude חייב להיות רשימת כינויים", 400)
            for alias in spec:
                if not isinstance(alias, str) or not re.match(r"^[a-z][a-z0-9-]{0,30}$", alias):
                    return _err(f"serve.exclude: {alias!r} אינו כינוי תקין", 400)
            continue
        if app == "only":
            # The other reserved key: what ONE linked office is given when it is given less than the
            # rest — `{"vps1": ["plane"]}`. An empty list is allowed: linked, and given nothing.
            if not isinstance(spec, dict):
                return _err("serve.only חייב להיות מפה של לשכה → רשימת כינויים", 400)
            for office, names in spec.items():
                if not isinstance(office, str) or not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", office):
                    return _err(f"serve.only: {office!r} אינו מזהה לשכה תקין", 400)
                if not isinstance(names, list):
                    return _err(f"serve.only.{office} חייב להיות רשימת כינויים", 400)
                for alias in names:
                    if not isinstance(alias, str) or not re.match(r"^[a-z][a-z0-9-]{0,30}$", alias):
                        return _err(f"serve.only.{office}: {alias!r} אינו כינוי תקין", 400)
            continue
        if app == catalog.WILDCARD:
            # `"*"` — "every app this office runs" (`catalog.publishable`). A key, not an app: it has
            # no port of its own, because the link's ONE door answers for every app behind it.
            if not isinstance(spec, dict):
                return _err('serve["*"] חייב להיות אובייקט (למשל {})', 400)
            continue
        port = spec.get("port") if isinstance(spec, dict) else spec
        try:
            port = int(port)
        except (TypeError, ValueError):
            return _err(f"לאפליקציה {app} אין פורט מספרי", 400)
        if not 1 <= port <= 65535:
            return _err(f"הפורט של {app} מחוץ לטווח", 400)
        if not isinstance(spec, dict):
            continue
        if spec.get("agent_api_port") not in (None, ""):
            try:
                aport = int(spec["agent_api_port"])
            except (TypeError, ValueError):
                return _err(f"ל„{app}” יש agent_api_port שאינו מספר", 400)
            if not 1 <= aport <= 65535 or aport == port:
                return _err(f"ה-agent_api_port של {app} חייב להיות פורט אחר, בטווח", 400)
        ident = spec.get("identity") or {}
        if ident and not isinstance(ident, dict):
            return _err(f"ה-identity של {app} חייב להיות אובייקט (to, from)", 400)
        to_user = ident.get("to") if isinstance(ident, dict) else None
        if to_user not in (None, "") and not re.match(r"^[A-Za-z0-9@._+\-]{1,128}$", str(to_user)):
            return _err(f"ה-identity.to של {app} אינו שם משתמש תקין", 400)
        # `host`: the authority the far edge writes as Host. EMPTY is a statement, not a gap — the
        # app trusts the consuming office's own name, so the browser's Host passes through.
        if "host" in spec and str(spec.get("host") or "") and \
                not re.match(r"^[a-z0-9][a-z0-9.-]{0,252}(:[0-9]{1,5})?$", str(spec["host"]).strip().lower()):
            return _err(f"ה-host של {app} אינו שם מארח תקין (שם ופורט אופציונלי, או ריק)", 400)
    if body.get("label") not in (None, ""):
        label = str(body["label"]).strip()
        if not 1 <= len(label) <= 60:
            return _err("ה-label של הלשכה חייב להיות באורך 1–60 תווים", 400)
        cv.set_home_label(label)
    saved = cv.set_home_serve(serve)
    # A port is a door, and declaring one re-renders BOTH halves of it here rather than at the next
    # converge: the tunnel's rules (which is where the delivered connection is accepted) and the
    # delivery plan (which is what listens for it).
    tunnel = render_tunnel()
    return {"serve": saved, "tunnel": tunnel.get("rendered"),
            "proxy": tunnel.get("proxy")}


@app.get("/api/tunnel")
def api_tunnel():
    """What is rendered right now — read back from the volume, so "rendered" is never assumed."""
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    files = {}
    for name in ("nftables.rules", "addressing.json", "edge-guard.json", "link-proxy.json",
                 "wg0.conf"):
        p = base / name
        files[name] = {"present": p.exists(), "bytes": p.stat().st_size if p.exists() else 0}
    # One interface per pair: the screen asks about a PAIR, not about "the tunnel".
    pairs = {}
    pdir = base / "pairs"
    if pdir.is_dir():
        for conf in sorted(pdir.glob("*.conf")):
            pairs[conf.stem] = {"file": f"pairs/{conf.name}", "present": True,
                                "bytes": conf.stat().st_size}
    addressing = {}
    try:
        addressing = json.loads((base / "addressing.json").read_text())
    except (OSError, ValueError):
        pass
    return {"tunnel": files, "pairs": pairs, "addressing": addressing}


@app.get("/api/link/proxy")
def api_link_proxy():
    """The DELIVERY plan (DGO-24): which of this office's ports a peer can actually reach.

    Read from the volume the proxy container reads, so the screen and the gate ask the same question
    of the same artifact — and never of a re-derivation that could agree with itself and disagree with
    what is listening.
    """
    import linkproxy
    doc = linkproxy.read(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    plan = doc.get("plan") or {}
    return {"plan": plan, "rules": plan.get("rules") or [], "rendered": doc["present"]}


def render_link_proxy() -> dict:
    """Write the DELIVERY plan (DGO-24) next to the tunnel plan, from the declarations this app owns.

    `net.py` renders the tunnel and `firewall.py` renders what may ARRIVE; neither says where an
    arrived packet lands, and `firewall.py` says so in its own docstring ("the permission, not the
    delivery"). This is the third renderer, and it lives here rather than in layer 0 for the reason
    layer 0 cannot do it at all: WHICH apps this office serves, and TO WHICH peer, are declarations in
    this app's volume — not facts of the catalogue the compiler reads.

    A refusal (a typo'd app name, two apps on one port, no slot) writes NOTHING and leaves whatever is
    already running alone: closing every door because one declaration is malformed is the failure mode
    this choice exists to avoid. The refusal is returned, and logged.
    """
    import linkproxy
    base = os.environ.get("DGO_TUNNEL_DIR", "/tunnel")
    shipped = linkproxy.read(base).get("plan") or {}
    if shipped.get("rendered_by") and not all_declarations():
        # The far end of a pair: the office that dials rendered this plan and shipped it here
        # (`converge._remote_delivery`), from facts only it holds. This office declares no link of its
        # own, so a re-render here could only replace working listeners with an empty plan.
        return {"rules": shipped.get("rules") or [], "kept": f"rendered by {shipped['rendered_by']}"}
    home = cv.home_office()
    records = {o["id"]: o for o in all_declarations() if o.get("id") != home.get("id")}
    # EVERY pair, each with its own slot and side (`_link_pairs`): one plan, one file, one namespace —
    # and a door per pair, because two pairs on one port refuse the whole plan (linkproxy.build_multi).
    pairs = [{"office": p["record"], "slot": p["slot"], "side": p["side"], "link": p["link"]}
             for p in _link_pairs(home, records)]
    # The `use` half needed the peer's own list of served apps, "which today only the serving office
    # knows" (linkproxy's own docstring). It knows it now: the peer PUBLISHES its catalog on the link
    # and the projection stores it here, so the delivery plan is rendered from the same fact the
    # console's tile is. Without a catalog the `use` half renders nothing — deliberately: a listener
    # for a port nobody confirmed is a door onto a guess.
    try:
        return linkproxy.write_multi(base, home, pairs,
                                     served_by_peer=catalog.served_by_peer(catalog.load_all(STATE_DIR)),
                                     control_bind=_link_proxy_bind())
    except linkproxy.LinkProxyError as e:
        log.warning("the delivery plan was refused and NOT written: %s", e)
        return {"rules": [], "refused": str(e)}


@app.on_event("startup")
def _render_link_proxy_on_start() -> None:
    """Re-render at boot: the container may restart while the tunnel volume keeps an older plan.

    Deliberately not fatal — an app that refuses to start because a link declaration is malformed is
    an app nobody can open to fix it.
    """
    threading.Thread(target=_serve_link, daemon=True, name="dgo-link-listener").start()
    try:
        plan = render_link_proxy()
        log.info("link proxy plan: %d rule(s)%s", len(plan.get("rules") or []),
                 f" (refused: {plan['refused']})" if plan.get("refused") else "")
    except Exception as e:                              # noqa: BLE001 — see the docstring
        log.warning("the delivery plan could not be rendered at startup: %s", e)
    # The remote offices' apps (DGO-37): pull the peers' catalogs, project them onto
    # platform.state.yaml, and re-render the delivery plan from what came back. Started here rather
    # than in a converge step so a restarted container re-derives the picture instead of waiting for
    # the next converge of this office.
    _start_projection()


@app.get("/api/identity")
def api_identity():
    """This office's PUBLIC identity — the half that may cross the wire.

    There is deliberately no route (and no function in identity.py) that returns the private halves:
    the Ed25519 and WireGuard secrets live in their own volume, are read by `bbox dgo identity` on
    the machine that owns them, and are carried by `bbox export`. A route that could hand them to a
    caller is the one thing that would make this app a place where a key leaks.
    """
    import identity
    return {"identity": identity.public(identity.load())}


@app.get("/api/context")
def api_context(probe: int = 1):
    """Everything the 'new office' form offers, each from the app that owns it."""
    machines = _get(f"{cv.COMPUTERS_URL}/api/computers?probe={1 if probe else 0}", 60)
    accounts = _get(f"{GIT_URL}/api/accounts", 30)
    domains = cv.domains_list()
    apps = _get(f"{APPMGMT_URL}/api/apps", 30)
    return {
        "home": home_source(),
        "machines": [m for m in machines.get("computers") or [] if m.get("id") != LOCAL_MACHINE],
        "machines_error": machines.get("error"),
        "git_accounts": [{"id": a.get("id"), "label": a.get("label"), "provider": a.get("provider"),
                          "login": a.get("login"), "ok": a.get("ok")}
                         for a in accounts.get("connections") or []],
        "domains": [{"name": d.get("name"), "zone": (d.get("zone_holder") or {}).get("zone_holder"),
                     "can_write": (d.get("zone_holder") or {}).get("can_write")} for d in domains],
        "apps": [{"id": a.get("id"), "title": a.get("title") or a.get("name") or a.get("id"),
                  "core": a.get("core"), "enabled": a.get("enabled"),
                  "memory": (a.get("resources") or {}).get("memory")}
                 for a in apps.get("apps") or []],
        "steps": [{"id": s, "title": cv.STEP_TITLES[s]} for s in cv.STEPS],
    }


@app.get("/api/office")
def api_list():
    import identity as _identity

    out = []
    for o in all_declarations():
        r = last_run(o["id"])
        # `kind` travels with every record: a paired peer has nothing to run, and a list that does not
        # say so is a list whose "run=—" reads as a failure instead of as a different kind of peer.
        out.append({**o, "kind": str(o.get("kind") or "office"),
                    # …and so does the office's MARK (flt-004): what it published with its catalog, or
                    # the pair its name gets while it has published none — the same fallback this file's
                    # /api/link sends and the console's registry derives, so a card and a tile agree.
                    "mark": _identity.mark_for(str(o.get("id") or "")),
                    "run": r and {k: r.get(k) for k in
                                  ("status", "started", "ended", "commit", "current", "health")}})
    return {"items": out, "count": len(out)}


@app.get("/api/office/{oid}")
def api_office(oid: str):
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    return {**o, "run": last_run(oid)}


@app.post("/api/office")
async def api_create(request: Request):
    body = await request.json()
    d, err = validate(body or {}, None)
    if err:
        return _err(err, 400)
    save(d)
    return {"office": d}


@app.put("/api/office/{oid}")
async def api_update(oid: str, request: Request):
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    if declaration.is_paired(o):
        return _err(_PAIRED_REFUSAL, 409)
    d, err = validate(await request.json() or {}, o)
    if err:
        return _err(err, 400)
    save(d)
    return {"office": d}


@app.delete("/api/office/{oid}")
def api_delete(oid: str):
    """Forgets the DECLARATION. The machine is not touched: an office with data is not something a
    click on this page may take down; stopping it is `./bbox stop` on that office."""
    with _runs_lock:
        if oid in _runs:
            return _err("הלשכה בתהליך — המתן לסיום", 409)
    p = _path(oid)
    if not p.exists():
        return _err("אין לשכה כזו", 404)
    if declaration.is_paired(load(oid)):
        # Its token lives in the vault and its peer in the tunnel: deleting the file alone would
        # leave both behind. `DELETE /api/pair/<office>` removes the three together.
        return _err("זו לשכה מצומדת — מסירים אותה ב-DELETE /api/pair/" + oid + " (רשומה, אסימון ומנהרה יחד)", 409)
    p.unlink()
    _run_file(oid).unlink(missing_ok=True)
    return {"deleted": oid}


@app.post("/api/office/{oid}/converge")
async def api_converge(oid: str, request: Request):
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    if declaration.is_paired(o):
        return _err(_PAIRED_REFUSAL, 409)
    body = (await request.json()) if await request.body() else {}
    res = start_run(o, (body or {}).get("steps"))
    if res.get("error"):
        return JSONResponse(res, status_code=409)
    return res


@app.get("/api/office/{oid}/run")
def api_run(oid: str, since: int = 0):
    r = last_run(oid)
    if not r:
        return {"run": None}
    r["log"] = r.get("log", [])[since:] if since >= 0 else r.get("log", [])
    r["log_offset"] = since + len(r["log"])
    return {"run": r}


@app.post("/api/inspect")
async def api_inspect(request: Request):
    """Read an EXISTING office on a machine (a checkout the owner installed by hand), so it can be
    adopted: its domain, repository, commit and enabled apps prefill the declaration."""
    body = await request.json() or {}
    machine, path = body.get("machine") or "", body.get("path") or ""
    if not machine or not path.startswith("/"):
        return _err("בחר מחשב ותיקייה", 400)
    script = (f"cd {cv.q(path)} 2>/dev/null || {{ echo missing=1; exit 0; }}\n"
              "echo repo=$(git remote get-url origin 2>/dev/null)\n"
              "echo branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)\n"
              "echo commit=$(git rev-parse HEAD 2>/dev/null)\n"
              "python3 - <<'PY' 2>/dev/null\nimport re,yaml\nvals={}\n"
              "for ln in open('.env').read().splitlines():\n"
              "  m=re.match(r'^([A-Z0-9_]+)=(.*)$',ln)\n"
              "  if m:\n    v=m.group(2).split(' #')[0].strip().strip(\"'\\\"\")\n"
              "    vals[m.group(1)]=re.sub(r'\\$\\{([A-Z0-9_]+)\\}',lambda x: vals.get(x.group(1),''),v)\n"
              "print('domain='+vals.get('DEPLOYMENT_DOMAIN',''))\n"
              "s=yaml.safe_load(open('platform.state.yaml'))\n"
              "for k,v in (s.get('apps') or {}).items():\n"
              "  v=v or {}\n  on=v.get('enabled') is True or v.get('state')=='enabled'\n"
              "  print('app.'+k+'='+('enabled' if on else 'disabled'))\nPY\n")
    r = cv.exec_on(machine, script, 60)
    if r.get("code") != 0:
        return _err(r.get("reason") or "לא ניתן לקרוא את המחשב", 502, detail=(r.get("stderr") or "")[-500:])
    f = cv.parse_facts(r.get("stdout") or "")
    if f.get("missing"):
        return {"exists": False}
    apps = {k[4:]: v for k, v in f.items() if k.startswith("app.")}
    return {"exists": True, "repo": f.get("repo"), "branch": f.get("branch"), "commit": f.get("commit"),
            "domain": f.get("domain"), "apps": apps}


# ── the door to apps that run on another office ─────────────────────────────────
# An app placed on a remote office is disabled HERE (see converge.step_publish), so the console has
# no local backend for its alias. The console's compiled registry points that alias at this route
# instead, and this route is the ONLY caller that adds the office's peer token: the browser talks to
# the console, the console talks to us, we talk to `peer.<office domain>`.
_HOP = {"content-length", "content-encoding", "connection", "keep-alive", "transfer-encoding", "host"}
PEER_IDLE_S = float(os.environ.get("DGO_PEER_IDLE_S", "45"))


def _peer_location(location: str, oid: str, alias: str) -> str:
    """Map an app's own redirect (it lives at `/` on its own host) back into this door. The console
    then maps it again into `/a/<alias>/`, which is what keeps the user inside the shell."""
    if not location:
        return location
    if "://" in location:
        p = urllib.parse.urlparse(location)
        location = p.path + (("?" + p.query) if p.query else "")
    if not location.startswith("/"):
        return location
    return f"/peer/{oid}/{alias}{location}"


@app.api_route("/peer/{oid}/{alias}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.api_route("/peer/{oid}/{alias}/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.api_route("/peer/{oid}/{alias}/{sub:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def peer_proxy(request: Request, oid: str, alias: str, sub: str = ""):
    """Proxy one request to an app that runs on another office.

    `async def` + `run_in_threadpool` for the outbound call, deliberately: this is FastAPI, not the
    console's Flask, and the domains app wrote down why — a blocking HTTP call written directly in an
    `async def` endpoint freezes the whole app, health check included, for as long as the remote
    takes. Everything that can block goes to a thread.
    """
    o = load(oid)
    doc = peers.read(oid, alias) if o else None
    if not o or not doc:
        return _err("אין אפליקציה כזו בלשכה הזאת", 404)
    token = peers.token_for(oid, create=False)
    if not token:
        return _err("ללשכה הזאת אין אסימון peer — הרץ converge ללשכה", 503)
    url = f"https://{peers.PEER_HOST}.{o['domain']}/{alias}/" + sub
    fwd = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    fwd["X-Office-Peer"] = token
    body = await request.body() if request.method not in ("GET", "HEAD", "OPTIONS") else None
    wants_stream = "text/event-stream" in (request.headers.get("Accept") or "").lower()

    def _call():
        return requests.request(request.method, url, params=dict(request.query_params), data=body,
                                headers=fwd, stream=True, allow_redirects=False,
                                timeout=(6, PEER_IDLE_S) if wants_stream else 60)

    try:
        r = await run_in_threadpool(_call)
    except requests.RequestException as e:
        return _err("האפליקציה בלשכה המרוחקת אינה עונה", 502,
                    detail=str(e)[:300])
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    if r.is_redirect and out.get("Location"):
        out["Location"] = _peer_location(out["Location"], oid, alias)
    if "text/event-stream" in (r.headers.get("Content-Type") or ""):
        out["Cache-Control"] = "no-cache, no-transform"
    return StreamingResponse(r.iter_content(chunk_size=None), status_code=r.status_code, headers=out)


# ── moving an app to another office, with its data ──────────────────────────────
# `placement` moves the containers; this moves the app. The steps, the safety rails and the rollback
# live in move.py; these two routes are the door.
@app.post("/api/office/{oid}/move")
async def api_move(oid: str, request: Request):
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    body = (await request.json()) if await request.body() else {}
    app_id = (body or {}).get("app") or ""
    if not app_id:
        return _err("חסר app — איזו אפליקציה להעביר", 400)
    # A PAIRED office has no machine record for move.py's steps to act on (they died on
    # `office["machine"]`), and it has a mover of its own: the control plane's, which asks the
    # office itself whether it has room and takes the app's data over the link. One mover per kind
    # of office; this door hands a paired one over verbatim, in that mover's own words.
    if declaration.is_paired(o):
        # …but never for a request that itself arrived over a link: handing it on from here would
        # strip where it came from, and the control plane is the one that decides what a linked
        # office may ask of this one.
        if request.headers.get("x-dgo-office"):
            return _err("בקשה שהגיעה מלשכה מקושרת מעבירה אפליקציה ממסך האפליקציות של הלשכה הזאת, לא מכאן.", 403)
        r = cv._http("POST", f"{projection.CONTROL_URL}/api/apps/{app_id}/move",
                     {"to": oid, **{k: body[k] for k in ("wake", "force") if k in (body or {})}}, timeout=120)
        return JSONResponse({k: v for k, v in r.items() if k != "_status"}, status_code=int(r.get("_status") or 200))
    with _runs_lock:
        if oid in _runs:
            return _err("הלשכה בתהליך converge — המתן לסיומו", 409)
    res = mv.start(o, app_id, fail_after=(body or {}).get("fail_after"),
                   allow_mismatch=bool((body or {}).get("allow_mismatch")),
                   allow_disabled=bool((body or {}).get("allow_disabled")))
    if res.get("error"):
        return JSONResponse(res, status_code=409)
    return res


@app.post("/api/office/{oid}/move-office")
async def api_move_office(oid: str, request: Request):
    """MOVE THE WHOLE OFFICE to that machine: every app that holds data here, one at a time.

    Body: `apps` ("a,b,c"; default = every app with data), `allow_mismatch`, `allow_disabled`
    (default TRUE here, false for a single move — moving one app out of a running office is a decision
    about that app; moving the office is a decision about all of it), `fail_after` (test hook).

    The apps go one at a time and each keeps its own rollback, so a failure stops the run and leaves
    THAT app exactly as it was; what already moved stays moved and verified. Progress and per-app
    results: GET /api/office/<oid>/move. Read-only preview: GET /api/office/<oid>/move-office/plan."""
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    # …and there is no "the whole office" to a paired one: it runs itself, and apps go to it one at
    # a time, each asked about by the office that receives it.
    if declaration.is_paired(o):
        return _err("זו לשכה מצומדת: אפליקציות עוברות אליה אחת־אחת, ממסך האפליקציות — "
                    "היא מנהלת את עצמה, ואין «העברת כל הלשכה» אליה.", 409)
    with _runs_lock:
        if oid in _runs:
            return _err("הלשכה בתהליך converge — המתן לסיומו", 409)
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    apps = [a.strip() for a in str(body.get("apps") or "").split(",") if a.strip()] or None
    res = mv.start_office(o, apps, allow_mismatch=bool(body.get("allow_mismatch")),
                          allow_disabled=body.get("allow_disabled", True) is not False,
                          fail_after=body.get("fail_after"))
    if res.get("error"):
        return JSONResponse(res, status_code=409)
    return res


@app.get("/api/office/{oid}/move")
def api_move_status(oid: str):
    cur = mv.running(oid)
    return {"move": cur or mv.last(oid)}


@app.get("/api/office/{oid}/move-office/plan")
def api_move_office_plan(oid: str, apps: str = ""):
    """What moving THIS WHOLE OFFICE to that machine would cost — read only.

    `?apps=a,b` limits it to a few; with no list it covers every app that has data here. Nothing is
    stopped and no declaration is written: this is the call that answers "can we do this, and what
    will it cost" before anything is at stake, using the move's own preflight so a start that would be
    refused later is refused here."""
    o = load(oid)
    if not o:
        return _err("אין לשכה כזו", 404)
    # A paired office has no machine this office installs on, so there is nothing to plan a move TO:
    # the preflight went looking for one and the route answered 500 (`bbox dgo test 1`, DGO-6).
    if declaration.is_paired(o):
        return _err(_PAIRED_REFUSAL, 409)
    sel = [a.strip() for a in (apps or "").split(",") if a.strip()]
    return {"plan": mv.plan(o, sel or None)}


# ── pairing two installed offices from their own screens (pair_api.py) ──────────────────────────
_PAIRED_REFUSAL = ("זו לשכה מצומדת (kind: paired): היא הותקנה בעצמה וקושרה מהמסך, ואין לה מחשב שהלשכה "
                   "הזאת מתקינה עליו. עורכים או מסירים אותה במסך הצימוד.")


class _PairPorts:
    """What the pairing engine needs from this app, and nothing more (see `pair_api.Pairing`)."""

    def home(self) -> dict:
        return cv.home_office()

    def identity_private(self) -> str:
        import identity
        doc = identity.load() or {}
        return (doc.get("ed25519") or {}).get("private") or ""

    def declarations(self) -> list[dict]:
        return cv.declarations()

    def addresses(self) -> list[str]:
        """The tunnel address this office holds — also as the FAR end of a link another office
        converged, whose tunnel is on this machine and in no record here."""
        return [projection.own_address_cached(cv)]

    def save(self, doc: dict) -> None:
        # the declaration's one writer for link-decided fields; the record was validated by the engine
        cv.save_declaration(doc)
        _run_file(doc["id"]).unlink(missing_ok=True)      # a replaced INSTALLED office's last run is not this peer's

    def delete(self, oid: str) -> None:
        _path(oid).unlink(missing_ok=True)

    def vault_put(self, name: str, secret: dict, label: str) -> None:
        import links
        try:
            links._call("DELETE", f"/api/instances/{name}")
        except links.LinkError:
            pass                                          # nothing to replace is the common case
        try:
            got = links._call("POST", "/api/instances", {
                "id": name, "protocol": links.PROTOCOL, "label": label,
                "account_hint": f"{secret.get('office')}<->{secret.get('peer')} {secret.get('direction')}",
                "secret": secret})
        except links.LinkError as e:
            raise pair_api.PairError(f"אסימון הקישור לא נשמר בכספת — הצימוד לא נכתב: {e}", 502) from e
        if got.get("id") not in (None, name):
            raise pair_api.PairError(f"הכספת שמרה את האסימון בשם אחר ({got.get('id')}) — הצימוד לא נכתב", 502)

    def vault_delete(self, name: str) -> None:
        import links
        try:
            links._call("DELETE", f"/api/instances/{name}")
        except links.LinkError as e:
            log.warning("the link token %s was not removed from the vault: %s", name, e)

    def listen(self) -> dict:
        # what is declared, corrected by where the offices that dial this one really reach it
        return pair_api.listen_now(pair_api.listen_from_env(), _reached())

    def dial_only(self) -> str:
        return pair_api.dial_only_why()

    def set_label(self, label: str) -> None:
        cv.set_home_label(label)

    def serve(self) -> dict:
        return dict(cv.home_office().get("serve") or {})

    def publishable(self) -> list[dict]:
        """This office's own apps — the compiled registry, the one list of "our apps"."""
        return [{"alias": r.get("alias"), "app": r.get("app") or r.get("alias"),
                 "name": r.get("name") or r.get("alias"), "port": r.get("port"),
                 "agent_api_port": r.get("agent_api_port")}
                for r in (catalog.load_registry(REGISTRY_DIR).get("apps") or [])
                if isinstance(r, dict) and r.get("alias")]

    def set_serve(self, serve: dict) -> dict:
        return cv.set_home_serve(serve)

    def chose_giving(self) -> bool:
        return (Path(STATE_DIR) / "giving-chosen").exists()

    def mark_giving(self) -> None:
        (Path(STATE_DIR) / "giving-chosen").write_text(str(int(time.time())), encoding="utf-8")

    def published_label(self, oid: str) -> str:
        """What that office says its own name is, in the catalog this office last pulled from it."""
        label = (catalog.load_all(STATE_DIR).get(oid) or {}).get("label") or ""
        if isinstance(label, dict):
            label = label.get("he") or label.get("en") or ""
        return str(label)

    def compile(self) -> dict:
        """Project now and compile, so an unpaired office's tiles and routes leave with it
        (`projection.apply_now`). Never raises: the record IS removed, and what is said is the compile."""
        try:
            _project_once()
        except Exception as e:                              # noqa: BLE001 — see the docstring
            return {"ran": False, "ok": False, "tail": f"{type(e).__name__}: {e}"}
        return projection.apply_now(cv, [], str(STATE_DIR))

    def render(self) -> dict:
        """The tunnel render's own answer, as data: a refusal there must reach the pairing screen as
        a sentence, not disappear into a 200."""
        try:
            got = render_tunnel()
        except Exception as e:                              # noqa: BLE001 — the record IS written
            log.warning("tunnel render after pairing failed: %s", e)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if isinstance(got, JSONResponse):
            try:
                detail = json.loads(got.body or b"{}")
            except ValueError:
                detail = {}
            return {"ok": False, "error": detail.get("error") or f"HTTP {got.status_code}"}
        return {"ok": True, **{k: got.get(k) for k in ("rendered", "proxy", "kept") if k in got}}


PAIRING = pair_api.Pairing(_PairPorts())
app.include_router(pair_api.build_router(PAIRING))


def _page(name: str, script: str):
    """A page with its script addressed BY VERSION (`static/app.js?v=<mtime>`).

    `no-cache` on the static mount is not enough for a browser that already holds the file: a copy
    cached before that header existed keeps being served from its heuristic freshness, and the
    console frames this app under another origin (`/a/dgo-extend/`) with a cache of its own —
    measured 2026-10-05: the standalone page drew the new cards while the SAME page inside the
    console still drew yesterday's. A URL that changes when the file changes cannot be stale.
    """
    html = (_STATIC / name).read_text(encoding="utf-8")
    try:
        version = int((_STATIC / script).stat().st_mtime)
    except OSError:
        version = 0
    html = html.replace(f'src="static/{script}"', f'src="static/{script}?v={version}"')
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _page("index.html", "app.js")


# The pairing screen (DGO-34): the office that is being JOINED opens `/connect` and shows a code, the
# office that HOSTS it opens the same page and scans. It is one page because the three doors in §8 of
# the plan — QR, camera, pasted text — produce the same offer and differ only in how it is carried;
# splitting them into three routes would put the same state machine in three files. The page is
# served by the app, not by the console, so it works on a machine that has not been joined yet: the
# whole point is that the two offices are looking at it BEFORE any link exists.
@app.get("/connect")
def connect():
    return _page("connect.html", "connect.js")
