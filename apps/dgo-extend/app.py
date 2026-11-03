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
import join_api
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
#: The office id and domain rules are declaration.py's (pure stdlib, so its selftest can ask them
#: without this module's web stack). Both end in `\Z`: `$` let "office2.example.co.il\n" through (DGO-615).
ID_RE = declaration.ID_RE
DOMAIN_RE = declaration.DOMAIN_RE
#: An app id (an `apps` / `serve` key) and a user the link's door writes into a header: catalog.py's
#: rules — the manifest schema's id rule and `platform/manager/serve.py`'s HEADER_RE — held in one place.
APP_ID_RE = catalog.APP_ID_RE
HEADER_RE = catalog.HEADER_RE

app = FastAPI(title="dgo-extend", docs_url=None, redoc_url=None)

#: What a linked office is told when it asks this app to change anything (DGO-624).
LINKED_WRITE_REFUSAL = ("בקשה שהגיעה מלשכה מקושרת אינה משנה דבר בלשכה הזאת — את ההצהרות, הקישורים "
                        "והצימודים שלה משנים רק מהמסך שלה עצמה.")


class _NoWritesFromALinkedOffice:
    """A request that crossed a link never WRITES here (DGO-624).

    The link's door writes `x-dgo-office` on every request it carries in, and the peer's own copy of
    that header is removed on the way (`link-proxy.py`), so its presence means exactly "a linked office
    is asking". Offices, links, `serve:`, pairing, a converge or a move are this office's own
    decisions: one guard for the whole app — the pairing router's routes and a route added later
    included — answers every method but a read with a refusal, before any route runs.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") not in ("GET", "HEAD", "OPTIONS") \
                and any(name.lower() == b"x-dgo-office" for name, _value in scope.get("headers") or ()):
            body = json.dumps({"error": LINKED_WRITE_REFUSAL}, ensure_ascii=False).encode("utf-8")
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


app.add_middleware(_NoWritesFromALinkedOffice)        # DGO-624: a linked office never writes here


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
    if existing and existing.get("domain") and d.get("domain") != existing["domain"]:
        # a domain change keeps the domain the MACHINE is on: the env step moves its .env from that name
        # to the new one, and from no other (FPG-33). That is the one before this change, unless an
        # earlier change was not converged yet (a typo corrected before the run): then it is still that
        # earlier one, which the env step clears once the machine has moved. Changed back to it: nothing to do.
        was = existing.get("renamed_from") or existing["domain"]
        d.pop("renamed_from", None)
        if was != d.get("domain"):
            if d.get("domain", "").endswith("." + was) or was.endswith("." + d.get("domain", "")):
                return None, (f"מעבר מ־{was} ל־{d.get('domain')} — אחד מהם בתוך השני — לא נתמך: "
                              "שמות של לשכות אחרות מתחתיו היו מוחלפים גם הם")
            d["renamed_from"] = was
    if "herd" in body:
        # the owner's mark for the herd that office belongs to (DGO-1003); empty clears it
        herd, err = declaration.clean_herd(body.get("herd"))
        if err:
            return None, err
        d.pop("herd", None)
        if herd:
            d["herd"] = herd
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
        apps = body.get("apps") or {}
        if not isinstance(apps, dict):
            return None, "apps חייב להיות מפה של אפליקציה → enabled/disabled"
        # DGO-622: a key that is not an app id is REFUSED, not dropped — `$` passed "drive\n" into the far state file.
        wrong = [k for k in apps if not APP_ID_RE.match(str(k))]
        if wrong:
            return None, (f"מזהה אפליקציה לא תקין ב-apps: {wrong[0]!r} — אותיות לטיניות קטנות, ספרות ומקף "
                          f"(2–31 תווים)")
        d["apps"] = {k: ("enabled" if v in (True, "enabled") else "disabled") for k, v in apps.items()}
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
    if "watch" in body:                       # the daily checks (FPG-26): {health: daily, backup: daily}, or none
        w = body.get("watch") or {}
        if (not isinstance(w, dict) or set(w) - set(WATCH_KINDS)
                or any((v or "daily") not in WATCH_EVERY for v in w.values())):
            return None, "watch: רק {health: daily, backup: daily}"
        kept = {k: v for k, v in w.items() if v}
        if kept:
            d["watch"] = kept
        else:
            d.pop("watch", None)
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


def _run_file(oid: str, kind: str = "") -> Path:
    """The office's last run — and, in a file of its own, its last off-server backup (FPG-26): a daily
    backup written over the converge's run left the card without its health check every day, its status
    the backup's, and a failed upgrade masked by the next morning's backup."""
    return RUN_DIR / (f"{oid}.{kind}.json" if kind in ("backup", "repair") else f"{oid}.json")


def _run_kind(run: dict) -> str:
    """A backup run is one that runs the backup and nothing else (the machine step runs with every run): a
    manual run that also upgrades is a converge, and the card shows it as one. A repair is the link step
    this office starts by itself (`_repair_far_delivery`): written beside the converge, never over it, or
    an hourly repair would erase the record of the converge that failed (the second reader, DGO-1037)."""
    if run.get("by") == "repair":
        return "repair"
    return "backup" if [s for s in (run.get("only") or []) if s != "machine"] == ["offsite"] else ""


def last_backup_run(oid: str) -> dict | None:
    p = _run_file(oid, "backup")
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


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
    p = _run_file(run["office"], _run_kind(run))
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
        if run.get("by") == "watch":
            # the daily check records ITSELF, from its own run: the run file is replaced by the next
            # converge of this office, and reading it later recorded someone else's run, or nothing
            try:
                _watch_record(run)
            except Exception as e:                      # noqa: BLE001 — a record must not crash a run's end
                log.warning("watch record %s: %s: %s", oid, type(e).__name__, e)


def start_run(office: dict, only: list[str] | None, by: str = "") -> dict:
    """`by` names who asked when it is not a person (`watch`): the run carries it, and records itself
    for that caller as it ends (_execute's finally)."""
    oid = office["id"]
    with _runs_lock:
        if oid in _runs:
            return {"error": "הלשכה כבר בתהליך", "run": _runs[oid]}
        run = {"office": oid, "status": "running", "started": int(time.time()), "ended": None, "by": by,
               "commit": (office.get("source") or {}).get("commit"), "current": None,
               "steps": {s: {"status": "pending", "title": cv.STEP_TITLES[s]}
                         for s in cv.STEPS + cv.EXTRA_STEPS},
               "log": []}
        _runs[oid] = run
    # `cv.EXTRA_STEPS` (unlink) are askable BY NAME and never part of a default converge.
    allowed = cv.STEPS + cv.EXTRA_STEPS
    only = [s for s in (only or cv.STEPS) if s in allowed]
    run["only"] = only                  # what was asked: a run that fails before its step still says which
    threading.Thread(target=_execute, args=(office, run, only), daemon=True,
                     name=f"converge-{oid}").start()
    return {"run": run}


#: How long this office's own git facts are trusted before the machine is asked again (seconds).
HOME_SOURCE_TTL = float(os.environ.get("DGO_HOME_SOURCE_TTL", "600"))
_home_source_cache: dict = {}
_home_source_lock = threading.Lock()


# ── context from the other apps ─────────────────────────────────────────────────
def home_source(max_age: float = HOME_SOURCE_TTL) -> dict:
    """This office's own code: repository, branch, commit — read on the machine that runs it."""
    if not HOME_REPO:
        return {"error": "DGO_HOME_REPO לא הוגדר (bbox מגדיר אותו)"}
    # Cached, and for minutes rather than seconds. These six git commands run on the MACHINE through
    # `computers`, and on Windows the checkout is on C: behind the 9p bridge: `git status` alone was
    # measured at 9.1 s there (2026-10-06), this function is asked by every /api/context and by the
    # catalog refresh, and the calls overlapped — a `git status` was running on the host in 16 of 20
    # samples, permanently. Branch/commit/dirty change when someone works on the office, not per poll.
    # The background catalog refresh takes the full TTL. The screen (`api_context`) asks for a short
    # one: its «upgrade to this office's version» button writes `home.commit` into a peer's
    # declaration, and a commit made a minute ago must not lose to a ten-minute-old cache.
    now = time.time()
    with _home_source_lock:
        have = _home_source_cache.get("value")
        if have and now - _home_source_cache.get("at", 0) < max_age:
            return dict(have)
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
    with _home_source_lock:
        _home_source_cache.update(value=dict(f), at=time.time())
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
        # the record's address, never a fresh SSH probe: this runs every time the plane is built (DGO-903)
        host = cv.machine_address(office.get("machine") or "")
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
    # The port this pair LISTENED on until now: the one an earlier rotation left, or — on the first
    # rotation — the plan's own `base + slot`. Recorded beside the new one because "the port moved" is
    # only a sentence a person can check when it carries both ends of the move (DGO-1096).
    was = int(entry.get("port") or 0) or (base + slot)
    entry.update({"port": port, "was": was, "at": time.time(), "count": count + 1, "why": why})
    seen[oid] = entry
    _write_listen_ports(seen)
    rendered = render_tunnel()
    log.warning("link %s: moved this office's own port to %d (was %d; %s)", oid, port, was,
                why or "no reason given")
    return {"office": oid, "ok": True, "port": port, "was": was, "count": count + 1, "tunnel": rendered}


FIND_FILE = "find-peer.json"
#: Down this long before this office goes LOOKING for a peer (seconds).
FIND_AFTER = float(os.environ.get("DGO_LINK_FIND_SECONDS", "300"))
#: Between two searches of the same pair.
FIND_COOLDOWN = float(os.environ.get("DGO_LINK_FIND_COOLDOWN", "300"))
#: Searches per episode at that pace — a machine that is switched off is not a lease that moved…
FIND_MAX = int(os.environ.get("DGO_LINK_FIND_MAX", "3"))
#: …but it comes back, and often on another lease. After FIND_MAX searches the pair is still looked
#: for, less often, until it answers: a search budget that ran out while the laptop was away left the
#: MacBook dialing 192.168.16.100 for ten days after hp-laptop came back as .101 (2026-10-09 → 10-19).
FIND_COOLDOWN_AWAY = float(os.environ.get("DGO_LINK_FIND_COOLDOWN_AWAY", "900"))
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
    if pair.get("transport") == "tcp":
        # The search moves the interface's Endpoint across the /24 for its whole sweep — on a pair
        # whose Endpoint is its own carrier, that cuts the path while it runs. The carrier searches.
        return {"office": oid, "ok": False,
                "reason": "הזוג הזה עובר בנתיב TCP, והנתיב (dgo-carry) הוא שמחפש את הלשכה האחרת ברשת"}
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


def _stuck_handshake(tun: dict) -> float | None:
    """How long this interface's handshake has been STUCK, or `None` when it is not (DGO-1096).

    A dead tunnel and a stuck one are not the same failure. The dead one is written in the verdict —
    nothing answers — and its repairs below are the port and the address search, tried on their clocks.
    The STUCK one is invisible to the verdict and to both ends: the interface `alive`s (a handshake
    inside the measurement window), this side keeps SENDING (`tx`), the far side hears none of it
    (`rx == 0`), and the handshake age grows past `HEAL_AFTER` because a handshake is never renewed.
    That is what a home NAT/router produces when the office changes networks: the OLD network's mapping
    is kept open by the 25 s keepalives, so `wg` counts the initiations as sent and the far side
    captures none (`issues/a-mac-that-changes-networks-keeps-its-tunnels-die-on-a-stale-nat-mapping.yaml`;
    the hand fix on the MacBook was `wg set wgN listen-port 0`).

    `alive` is deliberately NOT a term here, and that is a decision, not an oversight: this app's own
    measurement declares `alive` as "a handshake in the last `HEAL_AFTER` seconds" (`_tunnel_measured`),
    which is the same threshold, so `alive and handshake_age_s >= HEAL_AFTER` is a condition that can
    never hold — dead code dressed as a guard. The honest reading of "the interface is alive" is "it
    has a handshake age at all", which is the `isinstance` test below: an interface that never handshook
    has no age, and it is the address search's case, not this one.

    The caller's half of the decision is the VERDICT (DGO-1096, the verification's first find):
    `rx`/`tx` are CUMULATIVE for the life of the interface and restart at zero when the tunnel
    container is rebuilt, so these numbers alone cannot tell a stuck mapping from a fresh interface — a
    HEALTHY pair in the first minutes after a rebuild is `rx = 0` with a handshake older than
    `HEAL_AFTER`. So this function is only asked about a pair nothing answers (`state["ok"]` false); a
    pair whose catalog answers is left alone, however one-sided its counters look.
    """
    age = tun.get("handshake_age_s")
    if not isinstance(age, (int, float)) or age < HEAL_AFTER:
        return None
    if int(tun.get("tx") or 0) <= 0:            # never sent: there is no attempt to be stuck
        return None
    if int(tun.get("rx") or 0) > 0:             # the far side HEARS this side — the mapping is alive
        return None
    return float(age)


def heal_links(status: dict | None = None) -> list[dict]:
    """Give every DIALED pair that has been unreachable a fresh source port — once per window.

    Called from the projection's timer (so an office nobody is watching still heals) and from a
    converge's link step (so the repair happens inside the run that is already measuring). A pair that
    is up is never touched, and a rotation inside its cooldown is skipped: the cost of a rotation is a
    re-handshake, and paying it on a peer that is simply switched off is noise.

    **The order is the rule (DGO-1096).** Two facts ask for the SAME repair — move THIS office's own
    source port — and they are decided in one place, in this order:
      1. `roamed` — every public pair this office dials died at one moment, so the office's own network
         changed. That is a fact about the WHOLE office, so it is checked first.
      2. a STUCK handshake on ONE interface (`_stuck_handshake`): sending, receiving nothing, age past
         `HEAL_AFTER`. A per-interface fact, so it comes second.
    They share ONE cooldown clock (the same `entry["at"]` against `HEAL_COOLDOWN`) — two clocks for
    one repair would pay two re-handshakes for one episode. In a pass where the port moved, NOTHING
    else runs for that pair: `find_peer` repairs the PEER's address, and nothing measured here says
    the peer moved.

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
    pairs = _link_pairs(home, records)
    measured = _tunnel_measured()
    # THIS side's network moved (a laptop on another Wi-Fi): every public pair it dials died at one moment.
    # Their source ports move on this pass — no first sighting to wait out, and no stale «ok» from a pass
    # that ran before the tunnels died — because the stale mapping is renewed by every keepalive and never
    # expires by itself (net.roaming_stall; the MacBook at a coffee shop, 2026-11-01).
    stalled = set(netmod.roaming_stall(measured, [(netmod.iface_name(p["slot"]), p.get("endpoint") or "")
                                                   for p in pairs
                                                   if p["dial"] == "home" and p.get("transport") != "tcp"]))
    for pair in pairs:
        oid = pair["office"]
        state = status.get(oid) or {}
        # A pair on the TCP path is healed by its carrier, which redials and searches on its own
        # clock: its interface's Endpoint is 127.0.0.1, and a port or an address moved here would be
        # a repair of a path the pair does not use.
        if pair["dial"] != "home" or pair.get("transport") == "tcp":
            continue
        roamed = netmod.iface_name(pair["slot"]) in stalled
        # …measured HERE, once: one interface is the fact both repairs below are decided on.
        measured_iface = measured.get(netmod.iface_name(pair["slot"])) or {}
        # A STUCK handshake is read ONLY for a pair NOTHING ANSWERS, and that gate is the whole
        # difference between a diagnosis and a guess (DGO-1096, the verification's first find): `rx`/`tx`
        # are CUMULATIVE for the life of the interface and restart at zero when the tunnel container is
        # rebuilt, so a HEALTHY pair in the first minutes after such a rebuild — `rx = 0`, a handshake
        # older than `HEAL_AFTER` — reads exactly like a stuck one, and moving its port would pay a
        # needless disconnect and re-handshake for a tunnel that is carrying the catalog. When the pair
        # answers, the catalog IS the proof and nothing is moved.
        # `roamed` keeps its own bypass, untouched: it is a fact about the WHOLE office and it is read
        # BEFORE `ok`, because an `ok` written by a pass that ran before the tunnels died says nothing
        # about now (1df8bd35 — the MacBook at a coffee shop must still be re-ported).
        stuck_for = None if (roamed or state.get("ok")) else _stuck_handshake(measured_iface)
        entry = dict(seen.get(oid) or {})
        if state.get("ok") and not roamed:
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
            if not roamed and stuck_for is None:
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
        # ── ONE REPAIR, TWO FACTS (DGO-1096) ───────────────────────────────────────────────────
        # The source port of THIS office's own packets is the one hop the two ends never agreed about:
        # the peer's address and the port it listens on are facts of the PAIRING, while a home
        # NAT/router keeps the OLD network's mapping for our port and the 25 s keepalives hold that
        # dead mapping open — `wg` counts the initiations as sent, the far side captures none. So the
        # two facts below move the port, here, through ONE path:
        #   1. `roamed` — checked first, because it is a fact about the WHOLE office (every public
        #      pair it dials died at one moment: the office's network changed).
        #   2. `stuck_for` — one interface whose handshake age grows past HEAL_AFTER while it keeps
        #      sending and receives nothing (`_stuck_handshake`).
        if roamed or stuck_for is not None:
            # ONE cooldown for both facts — the same `entry["at"]` against the same HEAL_COOLDOWN,
            # never two clocks: the cost they share is one re-handshake, and an episode is one episode
            # however it was noticed.
            if entry.get("at") and now - float(entry["at"]) < HEAL_COOLDOWN:
                continue
            if roamed:
                # its clock is the TUNNEL's, not this first sighting's: the pairs died at the moment
                # of their last handshake, which is when this office's network changed.
                repair_for = now - float(measured_iface.get("handshake_at") or now)
                because = " — כל הלשכות הציבוריות נפלו יחד: הרשת של הלשכה הזאת התחלפה"
            else:
                # …and a stuck handshake's clock is the measured age itself, for the same reason: the
                # wait the two ends offer (`HEAL_AFTER`) was already paid by the growing age.
                repair_for = stuck_for
                because = f" — לחיצת היד נתקעה {int(stuck_for)} שניות והממשק שולח ואינו מקבל"
            out.append(rotate_listen_port(oid, why=f"{oid} לא ענתה {int(repair_for)} שניות{because}"))
            # The rotation wrote ITS pair's entry; only that one is taken back, merged into what this
            # pass holds — a pair repaired on its first sighting keeps its `down_since` (the second
            # reader on DGO-1096).
            if oid in _listen_ports():
                seen[oid] = {**entry, **_listen_ports()[oid]}
            # …and NOTHING else runs for this pair in this pass: the search below repairs the PEER's
            # address, and nothing measured here says the peer's address moved.
            continue
        # Both repairs below are repairs of the TUNNEL. A tunnel that handshook in the last three
        # minutes is carrying packets to the right address and port, so the hop that fell is behind
        # it (the office, its door) and moving the address or the port only breaks what works:
        # measured 2026-10-08, vps1's door lost its plan and this office rotated its own port seven
        # times over a tunnel that never stopped handshaking.
        if measured_iface.get("alive"):
            continue
        # TWO FAILURES, TWO REPAIRS — and neither can be told from the other locally: no handshake is
        # no handshake, whether a home NAT blackholed this office's source port or the router handed
        # the peer a different address. So both are tried, on their own clocks: the port is cheap and
        # immediate, and looking for the peer costs a bounded scan of one /24 (measured 2026-10-07,
        # hp-laptop: six rotations in a row did nothing, because the address had moved).
        find = dict(finds.get(oid) or {})
        pause = FIND_COOLDOWN if int(find.get("count") or 0) < FIND_MAX else FIND_COOLDOWN_AWAY
        if (not find.get("want") and down_for >= max(HEAL_AFTER, FIND_AFTER)
                and netmod.lan_address(str(pair.get("endpoint") or ""))
                and (not find.get("at") or now - float(find["at"]) >= pause)):
            out.append(find_peer(oid, why=f"{oid} לא ענתה {int(down_for)} שניות"))
            finds = _find_state()
        if down_for < HEAL_AFTER or (entry.get("at") and now - float(entry["at"]) < HEAL_COOLDOWN):
            continue
        # `roamed` and a stuck handshake never reach here: they were repaired above, on their own
        # clocks, and this line's clock is the first sighting's — which is the honest one for a tunnel
        # that simply stops and says nothing (`_stuck_handshake` returned None).
        out.append(rotate_listen_port(oid, why=f"{oid} לא ענתה {int(down_for)} שניות"))
        # The rotation wrote ITS pair's entry; only that one is taken back. Reloading the whole file
        # here dropped what this pass had just recorded for the pairs before it — hp-laptop's
        # `down_since`, every pass, because vps1 (after it in the order) kept being refused a seventh
        # rotation — so its clock never started and it was neither searched for nor healed for ten
        # days (2026-10-09 → 10-19).
        # …merged into what this pass holds: a pair first seen down and re-ported on the SAME pass (a laptop
        # that roamed) keeps its `down_since`, or the link coming back never resets its budget and the
        # seventh network change is refused (the second reader on DGO-1096).
        if oid in _listen_ports():
            seen[oid] = {**entry, **_listen_ports()[oid]}
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
    registry = catalog.load_registry(REGISTRY_DIR)     # the doors this office serves, read once for every pair
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
            # On the TCP path nobody dials that port: the carrier hands the pair's datagrams to it on
            # 127.0.0.1, so it is local — and a pair moved there still carries the UDP port it was
            # paired on, the one this office publishes, which another pair may be dialed on. Measured
            # 2026-11-01 on the Dell (DGO-1080): the HP dials 51830 over UDP, the MacBook's carried
            # pair was rendered on 51830 too, and its interface never came up («Address already in
            # use»). A carried pair listens where a door's pair always has: `DOOR_WG_BASE + slot`.
            "listen_port": (rotated_port(pid) if dials
                            else pair_api.DOOR_WG_BASE + slot if netmod.pair_transport(d) == "tcp"
                            else (tun.get("listen_port") or tun.get("port"))),
            # how the pair's datagrams travel: WireGuard's own UDP, or the carriers' TCP path — and,
            # for a pair that rides an office's HTTPS door (a join, join_api.py), that door's URL
            "transport": netmod.pair_transport(d),
            "door": str(tun.get("door") or ""),
            # `serve` on THIS office's link means "this office's apps are the ones that get opened", so
            # the port map is keyed by the peer id but filled from the SERVING side's own record — the
            # other way round opens a hole for ports nothing here ever agreed to expose. `both` serves
            # too: a reader that tests for `serve` alone renders a firewall with no accept for any
            # served port (measured 2026-10-01: a `serve:` declaration re-rendered this office's tunnel
            # and vps1's Bina stopped answering).
            "ports": (cv._served_ports_local(home, slot, registry, peer=pid)
                      if mirror in ("serve", "both") else {}),
        })
    return out


def _tunnel_descriptors(pairs: list[dict]) -> list[dict]:
    """`_link_pairs` → what `net.render_multi` renders: one descriptor per pair, built in ONE place."""
    import net as netmod
    return [{"slot": p["slot"], "side": p["side"], "dial": p["dial"],
             "listen_port": p["listen_port"], "ports": p["ports"], "transport": p["transport"],
             "door": p.get("door") or "",
             "peer": {"office": p["office"],
                      "public_key": netmod._key(p["record"].get("identity")),
                      "endpoint": p["endpoint"], "endpoint_port": p["endpoint_port"],
                      "direction": p["mirror"]}}
            for p in pairs]


def _write_if_changed(path: Path, text: str, mode: int | None = None) -> bool:
    """Write `text` to `path` whole — a temporary file renamed over it, with `mode` set BEFORE the
    rename, so no reader ever sees half of it or a key it may read — and only when it differs: a
    reader that watches the mtime (the carrier, the tunnel) is not woken for nothing."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        tmp.chmod(mode)
    tmp.replace(path)
    return True


def _stale_pair_files() -> list[str]:
    """The pair files on disk whose `ListenPort` is not what THIS code renders for that pair — the
    number the carrier's plan is derived from as well (`carry_plan`'s `wg_port`). Empty when nothing
    moved, which is the restart that must not bounce a single interface (dgo-net re-applies a pair
    whenever its file's mtime moves, `tunnel-entrypoint.sh`). Only that line is compared: the
    `Endpoint` of a pair this office dials is asked of the computers app, which may not be answering
    yet while the office starts, and a fallback address is not a change of plan."""
    import net as netmod
    home = cv.home_office()
    records = {o["id"]: o for o in all_declarations()}
    pairs = _link_pairs(home, {k: v for k, v in records.items() if k != home.get("id")})
    if not pairs:
        return []
    doc = netmod.render_multi(_tunnel_descriptors(pairs), carry=_carry_facts())
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    stale = []
    for p in doc["pairs"]:
        try:
            held = re.search(r"^ListenPort = (\d+)$", (base / p["file"]).read_text(encoding="utf-8"), re.M)
        except OSError:
            held = None
        if not held or int(held.group(1)) != int(p["listen_port"]):
            stale.append(p["file"])
    return stale


def _render_tunnel_if_stale() -> list[str]:
    """At startup: render the tunnel whole when a pair's port moved under this code (`_stale_pair_files`),
    so the interfaces and the carrier's plan move together. Returns what was stale."""
    stale = _stale_pair_files()
    if stale:
        log.warning("the tunnel's ports are not what this code renders (%s) — rendering the tunnel",
                    ", ".join(stale))
        render_tunnel()
    return stale


def render_carry_plan() -> dict:
    """The carrier's plan alone (`carry.json`), from the records and THIS container's environment.

    Rendered at startup as well as with the tunnel, because half of it is the environment
    (`DGO_CARRY_ACCEPT`, the office's own LAN address): a bring-up that changes `.env` recreates this
    container and nothing else re-renders, so a MacBook that became the side that accepts would have
    gone on with a plan that dials. Nothing else is written here — the pairs' interfaces are not
    touched by a restart of this app."""
    import net as netmod
    home = cv.home_office()
    records = {o["id"]: o for o in all_declarations()}
    pairs = _link_pairs(home, {k: v for k, v in records.items() if k != home.get("id")})
    plan = netmod.render_multi(_tunnel_descriptors(pairs), carry=_carry_facts())["carry"]
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    base.mkdir(parents=True, exist_ok=True)
    _write_if_changed(base / "carry.json", json.dumps(plan, indent=2))
    return plan


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
    tunnel_dir = os.environ.get("DGO_TUNNEL_DIR", "/tunnel")
    shipped = linkproxy.read(tunnel_dir).get("plan") or {}
    by = shipped.get("rendered_by") or ", ".join(sorted(linkproxy.read_shipped(tunnel_dir)))
    if by and not records:
        return {"rendered": [], "kept": f"the tunnel is rendered by {by}",
                "proxy": {"rules": len(shipped.get("rules") or []), "refused": None}}
    home = cv.home_office()
    doc_id = identity.load()
    if not doc_id:
        return _err("אין זהות למכונה הזאת — הרצ `bbox dgo identity`", 409)

    pairs = _link_pairs(home, {k: v for k, v in records.items() if k != home.get("id")})
    out = []
    base = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
    if pairs or not oid:
        descriptors = _tunnel_descriptors(pairs)
        try:
            doc = netmod.render_multi(descriptors, carry=_carry_facts())
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
        # The key and the carrier's plan are written WHOLE (a temporary file, renamed) and only when
        # they change: the carrier re-reads both on their mtime, and a key read in the middle of a
        # rewrite was every carried session dropped for a moment.
        _write_if_changed(base / "wg-private.key", doc_id["wg"]["private"], mode=0o600)
        (base / "nftables.rules").write_text(doc["nftables"], encoding="utf-8")
        (base / "addressing.json").write_text(json.dumps(doc["addressing"], indent=2), encoding="utf-8")
        _write_if_changed(base / "carry.json", json.dumps(doc["carry"], indent=2))
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
        fw = {home["id"]: (cv._served_ports_local(d2, slot, catalog.load_all(STATE_DIR).get(oid) or {}, peer=home["id"])
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


def _home_herd() -> str:
    """The herd this office belongs to, as the office itself declares it (`DGO_HERD`, DGO-1003).

    The owner, 2026-10-22: «כל לשכה קובעת את זה לעצמה» — our offices say «Bina Solutions», a client's
    say its company. Declared in the office's own `.env`, never typed into a screen. A value that is
    not one line of 1–60 characters is published as none, and the log says so — once: this is read on
    every catalog pull and every screen poll.
    """
    herd, err = declaration.clean_herd(os.environ.get("DGO_HERD"))
    if err and not _HERD_WARNED:
        _HERD_WARNED.append(err)
        log.warning("DGO_HERD is not a herd name (%s) — this office publishes no herd", err)
    return herd


_HERD_WARNED: list = []


def _home_commit() -> str:
    """The commit this office runs. Cached: it costs a round trip through `computers` to the machine,
    and it changes only when someone converges this office.

    A catalog NEVER waits for it, not even the first one. The read is a git round trip through
    `computers`, and the catalog it feeds is what every link door fetches for its route table. A peer
    gives that fetch 8.0 s (`projection.FETCH_TIMEOUT`). An office whose Computers could not reach its
    own machine (no approved key, or a firewall between the containers and the host) spent the full
    8.1 s timeout on EVERY catalog, because only a successful read was remembered. So its peer saw
    «the office does not answer» over a live tunnel (the Dell, 2026-10-21, DGO-835). Now the answer
    is whatever is known, "" before the first read, and the read runs behind it, at most once per
    FETCH_TTL, whether it succeeds or fails."""
    now = time.time()
    if "at" in _catalog_cache and now - float(_catalog_cache.get("at") or 0) < catalog.FETCH_TTL:
        return str(_catalog_cache.get("commit") or "")
    if not _commit_refreshing.is_set():
        _commit_refreshing.set()
        threading.Thread(target=_refresh_commit, daemon=True, name="catalog-commit").start()
    return str(_catalog_cache.get("commit") or "")


_commit_refreshing = threading.Event()


def _refresh_commit() -> str:
    commit = ""
    try:
        src = home_source() if HOME_REPO else {}
        commit = str((src or {}).get("commit") or "")
    except Exception:                                   # noqa: BLE001 — a catalog is not a commit
        pass
    finally:
        # Remembered either way: a failed read keeps the last commit known and is not tried again
        # before FETCH_TTL, so the next catalog does not pay for it.
        _catalog_cache.update({"at": time.time(), "commit": commit or str(_catalog_cache.get("commit") or "")})
        _commit_refreshing.clear()
    return str(_catalog_cache.get("commit") or "")


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
        for plan in [linkproxy.read(base).get("plan") or {}, *linkproxy.read_shipped(base).values()]:
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
    registry = catalog.load_registry(REGISTRY_DIR)
    reg = catalog.publishable(registry, home.get("serve"), office)
    # The agent door each served app DECLARES — the very map the delivery plan opens its second door
    # from (`catalog.serve_with_agents`), so the port a peer reads is a port a door answers on. A
    # wildcard office used to publish no adapter at all (the number was popped below and only an
    # explicit `serve:` entry put it back), and a peer that cannot read the port cannot address it:
    # `bbox b42 task --office hp-laptop` died on `no_agent_door` (DGO-570).
    doors = catalog.serve_with_agents(registry, home.get("serve"), office)
    rows = []
    for row in (reg.get("apps") or []):
        if not isinstance(row, dict):
            continue
        # one app's port is not every tile's (an app with two tiles listens on two, DGO-1269) — counted
        # over the WHOLE registry, not the rows `serve.only` left for this office
        spec = catalog.tile_spec(serve, row, registry.get("apps") or [])
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
        except (TypeError, ValueError):
            continue
        door = doors.get(str(row.get("app"))) or doors.get(str(row.get("alias"))) or {}
        # the agent door's port AND who answers it, both the DOOR's word (`catalog.published_agent`)
        row = catalog.published_agent(row, door)
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
                        now=now, mark=_mark, herd=_home_herd(),
                        link_port=linkproxy.door_port(slot) if slot else 0,
                        # the doors with no tile `serve.services` names for THIS office (DGO-945)
                        services=catalog.publishable_services(registry, home.get("serve"), office))
    # What OTHER offices gave this one, handed on when `serve.shared` says so (catalog.reshare) —
    # additive: an office that predates it reads this office's own apps and nothing else.
    shared = _reshared(home, office)
    if shared:
        out["shared"] = shared
    # …and, for the office that asks, where this one's tunnel reaches IT (`pair_api.dials`):
    # additive, read by `pair_api.listen_now` on the other side and by nothing older.
    dials = pair_api.dials(next((d for d in cv.declarations() if d.get("id") == office), None), _tunnel_measured())
    return {**out, "dials": dials} if dials else out


def _reshared(home: dict, office: str) -> list[dict]:
    """The `shared` sections for `office`: from the catalogs this office pulled (what each origin gave
    it), through this office's own door to each origin (its plan), minus what it hides itself. A read
    that fails hands on nothing — never a guess — and says so once in the log."""
    serve = home.get("serve")
    if not catalog.shared_for(serve):
        return []
    try:
        doors = {oid: p.get("door") for oid, p in projection.own_plan(home, str(STATE_DIR)).items()}
        return catalog.reshare(serve, office, str(home.get("id") or ""), catalog.load_all(STATE_DIR),
                               doors, projection.load_exclude(STATE_DIR))
    except Exception as e:                              # noqa: BLE001 — the catalog itself must answer
        # …for EVERY linked office: one origin's stored catalog is another machine's output, and a
        # raise here was `/api/link/catalog` failing for all of them (second reader, 2026-10-19).
        log.warning("serve.shared: nothing handed on this pass (%s: %s)", type(e).__name__, e)
        return []


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


#: An app id or alias, as `DGO_SERVE_AGENTS` may name one.
_AGENT_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,63}")


def _named_agents(home: dict, office: str = "") -> set[str]:
    """The apps this office hands an agent token for: the ones its `serve:` map NAMES — by hand, or in
    `serve.only` for that office — and the ones `DGO_SERVE_AGENTS` names (`.env`, per office). Never the
    wildcard: `*` shares the agent's screen, and its token only where this office said so (DGO-1127,
    the king's rule). Read here, not written into `serve:`: an entry `bina-ds: {}` would reach readers
    that take every key for a door with a port of its own."""
    serve = home.get("serve")
    named = {str(k).strip().lower() for k in catalog.app_specs(serve) if str(k) != catalog.WILDCARD}
    named |= {str(n).strip().lower() for n in (catalog.only_for(serve, office) or set())}
    for word in re.split(r"[,\s]+", os.environ.get("DGO_SERVE_AGENTS") or ""):
        word = word.strip().lower()
        if word and _AGENT_NAME_RE.fullmatch(word):
            named.add(word)
    return named


@link_app.get("/api/link/agent/{alias}")
def api_link_agent(alias: str, request: Request):
    """The credential a linked office needs to USE an agent this office serves it (DGO-32, DGO-1127).

    The converge used to PUSH it, over ssh, into the peer's vault (`converge._handoff_agents`). A
    pairing has no ssh in either direction, and an office with no sshd (the HP) could not even read
    its own agent's token, so no peer of the HP ever held one: `bbox agent --office hp-laptop` was a
    401 from every office. Here the peer PULLS it over the link itself, through the same door it reads
    the catalog by.

    Three checks, and all must hold. The connection comes from the link proxy (`_link_proxy_addresses`):
    a container inside this office reaches this listener too, may write any `x-dgo-office` it likes,
    and can read a pair's secret out of the vault, whose instance secrets are not gated — so the
    header is believed only from the one process that writes it. The office is the door's
    (`x-dgo-office`, never the peer's), and the caller proves it holds the secret this office shares
    with THAT office (`Authorization: Bearer`, compared with this vault's own copy). Only an app the
    asking office is GIVEN with an agent door, read from the very catalog it is shown."""
    import hmac
    import links
    came = str(getattr(getattr(request, "client", None), "host", "") or "").replace("::ffff:", "")
    proxy = _link_proxy_addresses()
    if not proxy or came not in proxy:
        log.warning("link agent: refused a caller at %s — only the link proxy (%s) asks here",
                    came or "?", ", ".join(sorted(proxy)) or "unresolved")
        return _err("רק דלת הקישור שואלת כאן", 403)
    office = (request.headers.get("x-dgo-office") or "").strip()
    presented = (request.headers.get("authorization") or "")
    presented = presented[7:].strip() if presented.lower().startswith("bearer ") else ""
    if not office or not presented:
        return _err("נדרשים הלשכה של הדלת וסוד הזוג", 403)
    home = cv.home_office()
    try:
        held = links.pair_tokens(str(home.get("id") or "local"), office)
    except links.LinkError as e:
        return _err(str(e), 503)
    if not any(hmac.compare_digest(presented.encode(), tok.encode()) for _n, tok in held):
        log.warning("link agent: %s presented a secret this office does not share with it", office)
        return _err(f"הסוד שהוצג אינו הסוד של הזוג עם {office}", 403)
    row = next((a for a in (build_catalog(office=office).get("apps") or [])
                if alias in (a.get("alias"), a.get("app")) and (a.get("api") or {}).get("port")), None)
    if row is None:
        return _err(f"{alias} אינה ניתנת ל-{office} עם דלת סוכן", 404)
    if not ({str(row["app"]).lower(), str(row.get("alias") or "").lower()} & _named_agents(home, office)):
        log.warning("link agent: %s asked for %s's token, which this office gives only under '*'",
                    office, row["app"])
        # `code` tells the asking office to drop a copy it took before the rule (projection._pull_one)
        return _err(f"{row['app']} ניתנת ל-{office} רק תחת \"*\" — אסימון סוכן נמסר רק לסוכן שהלשכה קראה "
                    f"בשמו (serve או DGO_SERVE_AGENTS)", 403, code="not_named")
    service = str(row["api"].get("service") or row.get("service") or row["app"])
    try:
        token = cv.vault_agent_token(service)
    except links.LinkError as e:
        return _err(f"אסימון הסוכן של {row['app']} לא נקרא: {e}", 503)
    if len(token) < 32:
        return _err(f"אסימון הסוכן של {row['app']} ריק", 503)
    log.info("link agent: %s took the agent credential of %s", office, row["app"])
    label = _home_label(home)
    if isinstance(label, dict):
        label = label.get("he") or label.get("en") or ""
    return {"office": home.get("id") or "local", "label": str(label or ""), "app": row["app"],
            "alias": row.get("alias") or row["app"], "port": int(row["api"]["port"]), "token": token}


def _serve_link() -> None:
    import uvicorn

    class _Quiet(uvicorn.Server):
        def install_signal_handlers(self) -> None:      # the process's signals belong to the app
            return

    # proxy_headers off: the caller's address is the socket's, never an `X-Forwarded-For` (api_link_agent)
    _Quiet(uvicorn.Config(link_app, host="0.0.0.0", port=int(catalog.LINK_PORT),
                          log_level="warning", access_log=False, proxy_headers=False)).run()


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
    verdicts = {it["office"]: it["verdict"] for it in items}
    # An office reached THROUGH another (a `remote:` entry with `via`, catalog.shared_sections) is as
    # reachable as the link it rides — its tiles carry that link's verdict, never a blank.
    for entry in result.get("desired") or []:
        via = str(entry.get("via") or "")
        if via and via in verdicts and entry.get("office") not in verdicts:
            verdicts[entry["office"]] = verdicts[via]
    peers.publish_link(verdicts)
    _record_link_history(items, result.get("healed"))
    try:
        _alert_link_drops(items)
    except Exception as e:                              # noqa: BLE001 — telling is not the plan
        log.warning("link alert failed: %s: %s", type(e).__name__, e)
    try:
        _repair_far_delivery(items)
    except Exception as e:                              # noqa: BLE001 — a repair is not the plan
        log.warning("link repair failed: %s: %s", type(e).__name__, e)
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
    (`הוזז פורט מקור 51932`, `found 192.168.16.100`) — a state that changed with no repair behind it
    came from the peer or from something a person did. A repair that ran while nothing changed is a
    row of its own (`kind: repair`), because it is an event the pair's state does not show. A history
    that cannot be written is logged and dropped: it is not the plan, and a link must not die of a
    full disk.
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
        fixed[oid] = (f"הוזז פורט מקור {h['port']}" if h.get("port") else
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
    # A REPAIR IS AN EVENT OF ITS OWN — even in a pass where nothing about the pair's `(ok, hop)`
    # changed, which is the common case: the source port moving is the one repair NEITHER END can see
    # (the far side learns this office's address from the packet it receives, and the peer's catalog
    # says nothing about it), so it is written in words, with the port it moved FROM and the one it
    # moved TO, instead of waiting for a `change` row that may come minutes later or never. DGO-1096.
    by_office = {str(it.get("office") or ""): it for it in items}
    for h in healed or []:
        oid = str(h.get("office") or "")
        if not oid or not h.get("port"):
            continue
        it = by_office.get(oid) or {}
        v = it.get("verdict") or {}
        out.append({"at": now, "office": oid, "ok": v.get("ok"), "hop": v.get("hop") or "",
                    "why": str(h.get("why") or h.get("reason") or ""),
                    "handshake_age_s": (it.get("tunnel") or {}).get("handshake_age_s"),
                    "port": h.get("port"), "from_port": h.get("was"), "count": h.get("count"),
                    "kind": "repair", "fixed_by": fixed.get(oid, "")})
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


# ── a link that falls is SAID, not discovered ────────────────────────────────────────────────────
#: The history above is a record somebody has to go and read. Three times the owner found a dead
#: link himself, days after it fell (MacBook → vps1 for a week, HP → vps1 for four days, MacBook ↔ HP
#: for ten — 2026-10-19), while every pass of this app had measured it. So a pair that stays down this
#: long is told to the office, once per outage, through the office's own notifications (the bell in
#: the console), and its return is told too. Ten minutes: a laptop restarting is not news, a laptop
#: that is gone over lunch is.
LINK_ALERT_AFTER = float(os.environ.get("DGO_LINK_ALERT_AFTER", "600"))
LINK_ALERTS_FILE = "link-alerts.json"
NOTIFICATIONS_URL = os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/")


def _notify(source_id: str, title: str, body: str, level: str) -> bool:
    """One row in the office's notifications, deduplicated by `source_id` (one per outage)."""
    try:
        r = requests.post(f"{NOTIFICATIONS_URL}/api/notifications", timeout=8,
                          json={"source": "dgo-extend", "source_id": source_id, "title": title,
                                "body": body, "level": level, "link": "/#/m/dgo-extend"})
        return r.status_code in (200, 201)
    except requests.RequestException as e:
        log.warning("link alert not delivered (%s): %s", source_id, e)
        return False


def _alert_link_drops(items: list[dict], now: int | None = None, notify=_notify) -> list[str]:
    """Tell the office when a pair has been down `LINK_ALERT_AFTER` seconds, and when it is back.

    The clock is kept in `link-alerts.json` (office → when its outage began, and whether it was told),
    so a restart of this app neither forgets an outage nor tells it twice. An office that is not
    measured yet (`ok: null`) moves no clock. Returns the source ids it told, for the test."""
    path = Path(STATE_DIR) / LINK_ALERTS_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    now = int(time.time()) if now is None else int(now)
    told, changed = [], False
    for it in items:
        oid = str(it.get("office") or "")
        v = it.get("verdict") or {}
        ok = v.get("ok")
        label = str(it.get("label") or oid)
        rec = dict(state.get(oid) or {})
        if ok is None or not oid:
            continue
        if ok:
            if rec.get("down_since"):
                if rec.get("alerted"):
                    minutes = max(1, round((now - int(rec["down_since"])) / 60))
                    sid = f"link-up-{oid}-{int(rec['down_since'])}"
                    if notify(sid, f"הקישור ל{label} חזר", f"אחרי {minutes} דקות שבהן לא ענתה.", "info"):
                        told.append(sid)
                state.pop(oid, None)
                changed = True
            continue
        if not rec.get("down_since"):
            state[oid] = {"down_since": now, "hop": v.get("hop") or ""}
            changed = True
            continue
        if not rec.get("alerted") and now - int(rec["down_since"]) >= LINK_ALERT_AFTER:
            since = time.strftime("%H:%M", time.localtime(int(rec["down_since"])))
            sid = f"link-down-{oid}-{int(rec['down_since'])}"
            if notify(sid, f"הקישור ל{label} נפל", f"מאז {since}. {v.get('why') or ''}".strip(), "error"):
                rec["alerted"] = True
                state[oid] = rec
                changed = True
                told.append(sid)
    if changed:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log.warning("link alerts: %s", e)
    return told


# ── a far office that stops serving is given its plan again, by its home ─────────────────────────────
#: fireplace, 2026-10-30 (DGO-1037): the tunnel to it handshook every two minutes while its dgo-link
#: applied `0 listener(s) for 0 rule(s)` for 13 hours. Its own dgo-extend had rendered an empty
#: delivery plan at a restart, because the plan this office ships into its `link-proxy.d/` was not
#: there. Only this office's link step writes that plan (`converge._remote_delivery`), and nothing ran
#: it: the watch runs health and the backup. So an office this one CONVERGES (a paired one renders its
#: own plan) whose tunnel is up while the office itself does not answer (`hop: office`) for
#: LINK_REPAIR_AFTER gets this office's machine + link steps again: at most once per
#: LINK_REPAIR_EVERY, never mid-converge, and said in the log.
LINK_REPAIR_AFTER = float(os.environ.get("DGO_LINK_REPAIR_AFTER", "600"))
LINK_REPAIR_EVERY = float(os.environ.get("DGO_LINK_REPAIR_EVERY", "3600"))
#: An outage the link step cannot end (a stack stopped on purpose, a far dgo-extend that crashes) is not
#: repaired for ever: each repair bounces the far tunnel and rewrites its firewall. After this many
#: tries in one outage the office is left to the dropped-link alert, which has told a person already.
LINK_REPAIR_MAX = int(os.environ.get("DGO_LINK_REPAIR_MAX", "3"))
LINK_REPAIR_FILE = "link-repair.json"
#: The same clock in memory: a state file that cannot be written must not turn into a repair every pass.
_repair_mem: dict[str, dict] = {}


def _repair_far_delivery(items: list[dict], now: int | None = None, start=None) -> list[str]:
    """Start the link step for every converged office whose tunnel is up and whose office has not
    answered for LINK_REPAIR_AFTER — at most LINK_REPAIR_MAX times in one outage, LINK_REPAIR_EVERY apart,
    never while that office is converging or moving or within LINK_REPAIR_AFTER of its last run. The clock
    is kept in `link-repair.json` (and in memory), so a restart neither forgets an outage nor repeats a
    repair early. Returns `repair:<id>` for each start, for the test."""
    start = start or start_run
    path = Path(STATE_DIR) / LINK_REPAIR_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}

    def _clean(rec) -> dict:                            # a hand-edited or torn file must not stop every repair
        out = {}
        for k in ("since", "ran", "tries"):
            try:
                out[k] = int((rec or {}).get(k) or 0) if isinstance(rec, dict) else 0
            except (TypeError, ValueError):
                out[k] = 0
        return {k: v for k, v in out.items() if v}
    state = {str(o): _clean(r) for o, r in state.items()}
    for oid, rec in _repair_mem.items():               # this process's own clock wins: it is never older
        state[oid] = dict(rec)
    now = int(time.time()) if now is None else int(now)
    did, changed = [], False
    seen = {str(it.get("office") or "") for it in items}
    for oid in [o for o in state if o not in seen]:     # an office that is no longer measured is no outage
        state.pop(oid, None)
        changed = True
    for it in items:
        oid = str(it.get("office") or "")
        v = it.get("verdict") or {}
        rec = dict(state.get(oid) or {})
        if not oid or v.get("ok") is None:              # not measured this pass: the clock neither starts nor ends
            continue
        hop = v.get("hop") or ""
        if v.get("ok") or hop not in ("office", "tunnel", "carry"):
            if rec:                                     # it answers again — or its catalog did arrive (a
                state.pop(oid, None)                    # `door`/`pair` verdict): the outage and its tries end
                changed = True
            continue
        if hop != "office":                             # a dead tunnel is the heal's (heal_links), not a link step's
            continue
        office = load(oid)
        if not office or declaration.is_paired(office) or not office.get("machine"):
            continue
        for key in ("since", "ran"):                    # a clock that went back: count from now, never block —
            if int(rec.get(key) or 0) > now:            # and SAVED, or the file's future value comes back
                rec[key] = now if key == "since" else 0
                state[oid] = rec
                changed = True
        if not rec.get("since"):
            state[oid] = {**rec, "since": now}
            changed = True
            continue
        last = last_run(oid) or {}
        ended = int(last.get("ended") or 0)
        if (now - int(rec["since"]) < LINK_REPAIR_AFTER or now - int(rec.get("ran") or 0) < LINK_REPAIR_EVERY
                or int(rec.get("tries") or 0) >= LINK_REPAIR_MAX
                or last.get("status") == "running" or (ended and 0 <= now - ended < LINK_REPAIR_AFTER)
                or mv.running(oid)):
            state[oid] = rec
            continue
        out = start(office, ["machine", "link"], by="repair")
        if out.get("error") or not out.get("run"):      # mid-converge: the next pass asks again
            continue
        rec["ran"] = now
        rec["tries"] = int(rec.get("tries") or 0) + 1
        state[oid] = rec
        changed = True
        did.append(f"repair:{oid}")
        log.warning("link: %s's tunnel is up but the office has not answered since %s — its link step "
                    "runs again (%d of %d)", oid, time.strftime("%H:%M", time.localtime(int(rec["since"]))),
                    rec["tries"], LINK_REPAIR_MAX)
    _repair_mem.clear()
    _repair_mem.update({o: dict(r) for o, r in state.items()})
    if changed:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log.warning("link repair state: %s", e)
    return did


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


# ── an office that declares a daily check gets one, and its record (FPG-26) ─────────────────────────
#: A client's office in its first month is checked every day, kept as a history the weekly report is
#: made from, and a failure is told the way a fallen link is — once, through the office's bell — with
#: its return told too. Declared on the office's record, `watch: {health: daily}`; nothing is watched
#: that did not ask, and a paired office (which this office never converges) is never watched. The check
#: is the converge's own `health` step (containers, the compose project, the console and every published
#: host), started by this office when its day is due and the office is not mid-converge; the RUN records
#: itself as it ends (_execute's finally → _watch_record), from its own dict — a later converge's run
#: cannot take its place, and a restart mid-check loses one line, never the schedule. A step's warnings
#: (a dead host, an unhealthy container) are a `warn` check and ring the bell too. A machine asleep at the
#: hour catches up when it wakes; the next day is counted from when the check was DUE, so it never drifts.
WATCH_TICK = float(os.environ.get("DGO_WATCH_TICK", "600"))
WATCH_EVERY = {"daily": 86400}
#: what each kind of watch runs, and the key of watch.json that holds when it last ran
WATCH_KINDS = {"health": (["health"], "last"), "backup": (["offsite"], "last_backup")}
WATCH_FILE = "watch.json"
_watch_started = threading.Event()
_watch_lock = threading.Lock()                          # the pass and a run's own record share watch.json


def _watch_state() -> dict:
    try:
        state = json.loads((Path(STATE_DIR) / WATCH_FILE).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _watch_save(state: dict) -> None:
    path = Path(STATE_DIR) / WATCH_FILE
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        log.warning("watch state: %s", e)


def _watch_record(run: dict, notify=None) -> dict:
    """The check's line in the office's history, and the bell: a failed or warned check once per outage
    (`failing` keeps which one), and its return. Returns the line, for the test."""
    notify = notify or _notify
    oid = str(run.get("office") or "")
    steps = run.get("steps") or {}
    h = steps.get("health") or {}
    res = h.get("result") or {}
    failed_step = next((n for n, s in steps.items() if (s or {}).get("status") == "failed"), "")
    failed = steps.get(failed_step) if failed_step else None
    # which watch this run was — from what it was ASKED (a backup that failed at its machine step never
    # reached `offsite`, and must not be told as a failed health check)
    kind = "backup" if _run_kind(run) == "backup" else "health"
    if kind == "backup":
        o = steps.get("offsite") or {}
        res = o.get("result") or {}
        status = "failed" if run.get("status") != "ok" else ("warn" if o.get("status") == "warn" else "ok")
    else:
        status = "failed" if run.get("status") != "ok" else ("warn" if h.get("status") == "warn" else "ok")
    c = res.get("containers") or {}
    # the sentences (summary, warnings, reason) are this office's own, for its bell; the FACTS beside them
    # are what a report in another language is written from (watch_report) — never the sentences
    row = {"t": run.get("ended") or int(time.time()), "status": status, "summary": res.get("summary") or "",
           "warnings": [str(w) for w in (res.get("warnings") or [])][:20],
           "reason": ((failed or {}).get("error") or {}).get("reason") or "", "step": failed_step}
    if kind == "backup":
        row.update(kind="backup", bytes=res.get("bytes"), volume=res.get("volume"), kept=res.get("kept"),
                   verified=res.get("verified"))
    else:
        row.update(healthy=c.get("healthy"), total=c.get("total"),
                   unhealthy=[b for b in str(c.get("bad") or "").split() if b][:20],
                   dead_hosts=[str(x) for x in (res.get("dead_hosts") or [])][:20],
                   answering=res.get("answering"), expected=res.get("expected"))
    try:
        with (Path(STATE_DIR) / f"watch-{oid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("watch history %s: %s", oid, e)
    try:
        label = (load(oid) or {}).get("label") or oid
    except Exception:                                   # noqa: BLE001 — a name is not worth a lost bell
        label = oid
    # each kind keeps its own outage: a failed backup is not a failed health check, nor its end
    fk, lk = ("failing", "failing_level") if kind == "health" else ("failing_backup", "failing_backup_level")
    with _watch_lock:
        state = _watch_state()
        rec = dict(state.get(oid) or {})
        # told once per outage AND per level: a warning (a dead host) must not hide a failure that comes
        # after it (an invalid compose project) — the level key says what the bell has said so far
        worse = status == "failed" and rec.get(lk) == "warn"
        if status != "ok" and (not rec.get(fk) or worse):
            if kind == "backup":
                title = (f"הגיבוי היומי של {label} מחוץ לשרת נכשל" if status == "failed"
                         else f"בגיבוי היומי של {label} חסר חלק מהלשכה")
            else:
                title = (f"בדיקת הבריאות היומית של {label} נכשלה" if status == "failed"
                         else f"בבדיקת הבריאות היומית של {label} יש אזהרות")
            body = row["reason"] if status == "failed" else "; ".join(row["warnings"][:3])
            if notify(f"watch-{kind}-{status}-{oid}-{run.get('started')}", title,
                      body or "פתח את DGO Extend לפרטים.", "error" if status == "failed" else "warning"):
                rec[fk] = rec.get(fk) or run.get("started")
                rec[lk] = status
        elif status == "ok" and rec.get(fk):
            back = f"הגיבוי של {label} מחוץ לשרת חזר לעבוד" if kind == "backup" else f"{label} בריאה שוב"
            if notify(f"watch-{kind}-back-{oid}-{rec[fk]}", back, row["summary"], "info"):
                rec.pop(fk, None)
                rec.pop(lk, None)
        state[oid] = rec
        _watch_save(state)
    return row


def _watch_once(now: int | None = None, start=None) -> list[str]:
    """One pass: start every watched check that is due. Returns `started:<id>` for each, for the test."""
    start = start or start_run
    now = int(time.time()) if now is None else int(now)
    did = []
    with _watch_lock:
        state = _watch_state()
        try:
            for p in sorted(DECL_DIR.glob("*.yaml")) if DECL_DIR.is_dir() else []:
                try:                                    # one record that fails must not stop the others
                    office = yaml.safe_load(p.read_text())
                    if not isinstance(office, dict):
                        continue
                    watch = office.get("watch")
                    oid = str(office.get("id") or "")
                    if not oid or not isinstance(watch, dict) or declaration.is_paired(office):
                        continue
                    rec = dict(state.get(oid) or {})
                    for kind, (steps, key) in WATCH_KINDS.items():
                        every = WATCH_EVERY.get(str(watch.get(kind) or ""))
                        if not every:
                            continue
                        last = int(rec.get(key) or 0)
                        if last > now:                  # the clock went back: due now, not blocked till it returns
                            last = 0
                        if last and now < last + every:
                            continue                    # never run = due now
                        out = start(office, steps, by="watch")
                        if out.get("error") or not out.get("run"):   # mid-converge: the next pass asks again
                            break
                        # the day it was DUE, not when it ran or ended: the check never drifts later by the tick
                        rec[key] = last + every if last and now - (last + every) < every else now
                        state[oid] = rec
                        did.append(f"started:{oid}" if kind == "health" else f"started:{oid}:{kind}")
                        break                           # one run per office per pass: a second would be refused
                except Exception as e:                  # noqa: BLE001 — see the comment above
                    log.warning("watch: %s: %s: %s", p.name, type(e).__name__, e)
        finally:
            if did:                                     # what was started is saved, whatever came after it
                _watch_save(state)
    return did


def _watch_loop() -> None:
    """The watch's timer. Never fatal: one unreadable record must not stop the others' checks."""
    while True:
        try:
            _watch_once()
        except Exception as e:                          # noqa: BLE001 — see the docstring
            log.warning("watch failed: %s: %s", type(e).__name__, e)
        time.sleep(WATCH_TICK)


def _start_watch() -> None:
    if _watch_started.is_set():
        return
    _watch_started.set()
    threading.Thread(target=_watch_loop, daemon=True, name="dgo-watch").start()


#: What a failed step means, in the client's words. A step's own reason is this office's Hebrew and can carry
#: an address, a tunnel or another office's name — it is never passed through to a client.
_STEP_EN = {"machine": "the server could not be reached", "dns": "the office's address (DNS) did not point at "
            "the server", "health": "the health check failed", "run": "the office could not be started",
            "code": "the update could not be installed", "link": "the link to our office was down"}


def _check_en(r: dict) -> str:
    """One check, in English, from its FACTS only."""
    def names(xs):
        xs = [str(x) for x in (xs if isinstance(xs, list) else [])][:5]
        return ", ".join(xs)
    if r.get("kind") == "backup":
        if r.get("status") == "failed":
            return "the off-server backup could not be completed."
        if r.get("status") == "warn":
            return "an encrypted backup was copied off the server, but part of the office was not in it."
        mb = r.get("bytes")
        size = f" ({int(mb) / 1e6:.1f} MB)" if isinstance(mb, (int, str)) and str(mb).isdigit() else ""
        return f"an encrypted backup{size} was copied off the server and verified."
    if r.get("status") == "failed":
        return _STEP_EN.get(str(r.get("step") or ""), "the check could not complete") + "."
    parts = []
    if isinstance(r.get("healthy"), (int, str)) and isinstance(r.get("total"), (int, str)):
        parts.append(f"{r['healthy']} of {r['total']} services healthy")
    if isinstance(r.get("answering"), int) and isinstance(r.get("expected"), int):
        parts.append(f"{r['answering']} of {r['expected']} addresses answering")
    if r.get("dead_hosts"):
        parts.append("not answering: " + names(r["dead_hosts"]))
    if r.get("unhealthy"):
        parts.append("unhealthy: " + names(r["unhealthy"]))
    return ("; ".join(parts) or ("healthy" if r.get("status") == "ok" else "with warnings")) + "."


def watch_report(oid: str, days: int = 7, now: int | None = None) -> dict:
    """The office's daily checks over `days`, counted, and the text of the weekly report (FPG-26: William and
    Alan read English). Read from the history the checks keep; nothing is measured here. The text is written
    from the checks' facts, in fixed English sentences — never from their Hebrew summaries or reasons."""
    now = int(time.time()) if now is None else int(now)
    since = now - days * 86400
    rows = []
    try:
        raw = (Path(STATE_DIR) / f"watch-{oid}.jsonl").read_bytes().decode("utf-8", errors="replace")
    except OSError:
        raw = ""
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            t = int(row.get("t"))                      # a row without a sane time is not a check
        except (ValueError, TypeError, AttributeError, OverflowError):   # 1e400 reads as inf
            continue
        if since <= t <= now + 86400:
            rows.append({**row, "t": t})
    backups = [r for r in rows if r.get("kind") == "backup"]
    rows = [r for r in rows if r.get("kind") != "backup"]          # `rows` are the health checks
    counts = {k: sum(1 for r in rows if r.get("status") == k) for k in ("ok", "warn", "failed")}
    counts["other"] = len(rows) - sum(counts.values())
    counts["backups_ok"] = sum(1 for r in backups if r.get("status") == "ok")
    counts["backups_warn"] = sum(1 for r in backups if r.get("status") == "warn")   # made, but something missing
    counts["backups_failed"] = len(backups) - counts["backups_ok"] - counts["backups_warn"]
    label = (load(oid) or {}).get("label") or oid
    day = lambda t: time.strftime("%b %d", time.gmtime(t))  # noqa: E731
    if not rows:
        text = f"{label} — office health, last {days} days: no daily check was recorded."
    else:
        text = (f"{label} — office health, {day(since)}–{day(now)}: {len(rows)} daily "
                f"check{'' if len(rows) == 1 else 's'} — "
                f"{counts['ok']} healthy, {counts['warn']} with warnings, {counts['failed']} failed"
                + (f", {counts['other']} unreadable" if counts["other"] else "") + ".\n"
                f"Latest ({day(rows[-1]['t'])}): {_check_en(rows[-1])}")
    if backups:
        made = counts["backups_ok"] + counts["backups_warn"]
        text += (f"\nOff-server backups: {made} of {len(backups)} made, encrypted and verified"
                 + (f" ({counts['backups_warn']} with part of the office missing)" if counts["backups_warn"] else "") + "."
                 f" Latest ({day(backups[-1]['t'])}): {_check_en(backups[-1])}")
    issues = sorted([r for r in rows + backups if r.get("status") != "ok"], key=lambda r: r["t"])
    if issues:
        text += "\nNeeded attention:\n" + "\n".join(f"- {day(r['t'])}: {_check_en(r)}" for r in issues[-10:])
    return {"office": oid, "days": days, "since": since, "checks": rows, "backups": backups, "counts": counts,
            "text": text}


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
    `alive` is "a handshake in the last `HEAL_AFTER` seconds". That window is ONE measurement read
    twice — here, and by `heal_links`' `roamed`/stuck decision — so it is the same number on purpose
    (`DGO_LINK_HEAL_SECONDS`, 180 s by default; DGO-1096, the verification's third find). A bound
    spelled twice is two bounds that drift apart in silence the day the env moves, and then `alive`
    would disagree with the very repair it feeds. `handshake: 0` is "never, since the container
    started"."""
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
                     "alive": age is not None and age < HEAL_AFTER,
                     "rx": int(m.get("rx") or 0), "tx": int(m.get("tx") or 0)}
    return out


def _carry_facts() -> dict:
    """What only THIS office knows about its TCP path (`net.carry_plan`): whether its peers' carriers
    can reach its own (`DGO_CARRY_ACCEPT` — a MacBook's engine publishes the port on its LAN through
    its door), and its own LAN address, the /24 a dialing carrier searches for its peer."""
    import net as netmod
    accept = os.environ.get("DGO_CARRY_ACCEPT", "").strip().lower() in ("1", "true", "yes", "on")
    own = (os.environ.get("DGO_WG_ENDPOINT") or os.environ.get("BBOX_HOST_LAN_ADDR") or "").strip()
    # An office with a public link host (`DGO_LINK_HOST`, routed by the edge to dgo-net) opens its
    # DOOR there: the offices that can reach it only over HTTPS join and carry through it.
    door = netmod.DOOR_LISTEN if join_api.link_host() else ""
    # THE HERD'S HUB (DGO-1097): `DGO_RELAY` is where this office's tcp pairs meet their peers when their
    # own way stays silent (`wss://link.<the hub's domain>/relay`); on the hub, `DGO_RELAY_FOR` names the
    # offices whose pairs its door joins.
    relay = (os.environ.get("DGO_RELAY") or "").strip()
    if relay and not netmod.RELAY_URL_RE.match(relay):
        log.warning("DGO_RELAY=%r is not wss://host/path — no pair takes the hub's relay", relay)
    return {"accept": accept, "own_address": own, "door": door, "relay": relay,
            "relay_tags": _relay_tags() if door else []}


def _relay_tags() -> list[str]:
    """The pairs of OTHER offices this office's door may join (`DGO_RELAY_FOR`, carrier/relay.go): the
    herd's hub's declaration, a comma-separated list of office ids. A peer's WireGuard public key is the
    one this office's own record of it holds; an office it holds no pair with is given as `id=<public
    key>` (a public key is no secret: it is what every pairing shows)."""
    import net as netmod
    items = [x.strip() for x in (os.environ.get("DGO_RELAY_FOR") or "").split(",") if x.strip()]
    if not items:
        return []
    keys = {d["id"]: netmod._key(d.get("identity")) for d in all_declarations() if d.get("id")}
    offices = []
    for item in items:
        oid, _, key = item.partition("=")
        oid = oid.strip()
        if key.strip():
            keys[oid] = key.strip()
        offices.append(oid)
    unknown = [o for o in offices if not keys.get(o)]
    if unknown:
        log.warning("DGO_RELAY_FOR: no WireGuard key known for %s — their pairs are not relayed here "
                    "(give it as id=<public key>)", ", ".join(unknown))
    return netmod.relay_tags(keys, offices)


def _carry_measured() -> dict:
    """What the carrier (`dgo-carry`) last wrote, by interface, and `{}` when it writes nothing: no
    carrier, or one that stopped (it writes every 5 s, so a minute of silence is not a measurement)."""
    try:
        # the carrier's own volume (`dgo_carry`, read-only here): the tunnel volume is the carrier's
        # to READ, never to write
        doc = json.loads(Path(os.environ.get("DGO_CARRY_STATE", "/carry/carry-state.json")).read_text())
        at = int(doc.get("at") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    if int(time.time()) - at > 60:
        return {}
    return {name: {**st, "measured_at": at} for name, st in (doc.get("pairs") or {}).items()
            if isinstance(st, dict)}


#: A fallen hop, as a person is told about it — on this app's screen, on the tiles the console
#: marks and on the card it shows instead of a frame. Said here and nowhere else.
_HOP_HE = {
    # The pair rides the carriers' TCP path and that path is not connected: the other machine is off,
    # not on this network, or its office is not running its carrier (`dgo-carry`).
    "carry": "הקישור הזה עובר בנתיב TCP, והנתיב אליה לא מחובר: המחשב השני כבוי או לא באותה רשת, "
             "הלשכה שלו לא מריצה את dgo-carry, או שרק לשכה אחת עברה ל-TCP — `bbox dgo link transport "
             "<לשכה> tcp` נאמר בשתיהן.",
    "tunnel": "המנהרה אליה לא מעבירה תנועה: היא כבויה, מנותקת מהרשת, או שהקישור נפל.",
    "office": "המנהרה אליה פעילה, אבל הלשכה עצמה לא עונה — ייתכן שהיא מופעלת מחדש.",
    "door": "הדלת של הקישור בלשכה הזאת לא עונה, ולכן אף אפליקציה שלה לא נפתחת מכאן.",
    # Not a hop that fell but a pair that never could carry anything: this office dials a private
    # address that is not on any network of ours. Nothing here can be repaired — the pair is written
    # the wrong way round and has to be made again (measured 2026-10-12, lnk-032).
    "pair": "הצימוד הזה נכתב בכיוון שאי אפשר לחייג בו: הכתובת שאליה הוא מחייג היא כתובת מקומית "
            "שאיננה ברשת של הלשכה הזאת. צמדו מחדש — הלשכה הזאת תקשיב, והלשכה האחרת תחייג אליה.",
    "listen": "הלשכה הזאת היא זו שמחייגים אליה בזוג הזה, אבל הפורט שלה לא מפורסם — שום חבילה של "
              "הלשכה האחרת לא מגיעה. `bbox run` מפרסם אותו מרשומת הזוג.",
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
    import net as _net
    if _net.pair_transport(d) == "tcp":
        return False                                  # the carriers decide who dials, not the UDP roles
    tun = d.get("tunnel") or {}
    dial, role = str(tun.get("dial") or ""), str(tun.get("role") or "")
    # `net.holder_dials`: the holder of a paired record dials exactly when `dial == role`.
    if dial not in ("host", "joiner") or dial != role:
        return False
    import net as _net
    return not _net.dialable_from_here(tun.get("endpoint") or "",
                                       (pair_api.listen_from_env() or {}).get("endpoint") or "")


def _listen_published(record: dict) -> dict | None:
    """For a pair in which THIS office is the side that is dialed: is the port the pair agreed on
    actually published by `dgo-net`? None for a pair this office dials.

    The pair's record holds the agreed port (`tunnel.listen_port`) and compose publishes what `.env`
    says — and a rebuilt `.env` loses the second (vps1, 2026-10-14 → 10-19: hp-laptop's handshakes
    arrived at the server's firewall and reached nothing behind it, and every screen called that
    "the tunnel is down"). The container is created from the same `.env` as `dgo-net`, so its
    environment is what was published; `hooks/prepare` is what puts `.env` right again.
    """
    t = record.get("tunnel") or {}
    if (record.get("kind") or "") != "paired" or not t.get("listen_port") or t.get("dial") == t.get("role"):
        return None
    if str(t.get("transport") or "udp").strip().lower() == "tcp":
        return None                                   # no UDP port is dialed: the carriers hold the path
    want = str(t["listen_port"]).strip()
    port = os.environ.get("DGO_WG_PUBLISH_PORT", "").strip()
    bind = os.environ.get("DGO_WG_PUBLISH_BIND", "").strip() or "127.0.0.1"
    return {"port": int(want), "published": port or None, "bind": bind,
            "ok": port == want and bind not in ("127.0.0.1", "::1", "localhost")}


def _verdict(state: dict, tunnel: dict | None, door: dict, mispaired: bool = False,
             listen: dict | None = None, carry: dict | None = None) -> dict:
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
    * `listen` — the tunnel is down and THIS office is the side she dials, with its agreed port not
      published (`_listen_published`): the fault is on this side, and no repair of hers can help.
    * `carry`  — the tunnel is down and the pair rides the TCP path (`carry` is the carrier's reading
      for it, `{}` when nothing measures it), which is not connected. `None` = a UDP pair.

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
    elif carry is not None and carry.get("state") != "up":
        hop = "carry"
    elif listen and not listen["ok"]:
        hop = "listen"
    else:
        hop = "tunnel"
    return {"ok": not hop, "hop": hop, "why": _HOP_HE.get(hop, "")}


DOOR_ACCESS_LOG = Path(os.environ.get("DGO_DOOR_ACCESS_LOG", "/doorlog/door-access.jsonl"))


@app.get("/api/link/access")
def api_link_access(since: float = 0, limit: int = 2000):
    """Every request another office made through this office's door, oldest first, after `since`
    (epoch seconds) — the door's own record (link-proxy.py `access_record`, one JSON line each:
    office, app, the user it became here, method, path, status, bytes each way, ms).

    The owner, 2026-10-21: "dgo extend should log exactly the app its sharing between dgo as there
    accesed". Read by the security app (`SECURITY_DOOR_SOURCE`, contributed in app.json); on the office
    network only — the link listener (catalog.LINK_PORT) serves the catalog and the agent credential
    of the pair that proves it (`api_link_agent`) and nothing else, so no peer can read another peer's
    record here."""
    limit = max(1, min(int(limit or 2000), 10000))
    items: list = []
    for path in (DOOR_ACCESS_LOG.with_name(DOOR_ACCESS_LOG.name + ".1"), DOOR_ACCESS_LOG):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if float(rec.get("ts") or 0) > since:
                        items.append(rec)
        except OSError:
            continue
    items.sort(key=lambda r: r.get("ts") or 0)
    return {"items": items[:limit], "more": len(items) > limit,
            "source": str(DOOR_ACCESS_LOG), "present": DOOR_ACCESS_LOG.exists()}


def _peer_herd(decl: dict, cat: dict) -> str:
    """The herd of a linked office: the owner's mark on its record first, then its own word.

    What the peer published is read as a stranger's text — cleaned by the one rule, and dropped when
    it is not a herd name — because it is drawn on this office's screen."""
    mark, _ = declaration.clean_herd(decl.get("herd"))
    if mark:
        return mark
    own, _ = declaration.clean_herd((cat or {}).get("herd"))
    return own


@app.post("/api/link/herd")
async def api_link_herd(request: Request):
    """Mark the herd a linked office belongs to — `{"office": "wbc-vps", "herd": "WBC"}`; empty clears.

    For a peer whose code publishes no herd of its own (DGO-1003): the owner, 2026-10-22, «mark the
    connection as an external herd, not part of our Bina Solutions herd». Any record, paired or
    installed; only the mark changes, so nothing is re-rendered.
    """
    body = await request.json()
    oid = str((body or {}).get("office") or "").strip().lower()
    doc = load(oid) if ID_RE.match(oid) else None
    if not doc:
        return _err(f"אין כאן לשכה בשם {oid!r}", 404)
    herd, err = declaration.clean_herd((body or {}).get("herd"))
    if err:
        return _err(err, 400)
    doc.pop("herd", None)
    if herd:
        doc["herd"] = herd
    save(doc)
    return {"ok": True, "office": oid, "herd": herd}


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
    carried = _carry_measured()
    # THIS office's own source port per pair, as the heal last left it (DGO-1096): one dict for the
    # whole answer, read once — the same repair is invisible from both ends of the tunnel.
    ports = _listen_ports()
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
        listen = _listen_published(d)
        transport = _net.pair_transport(d)
        # the TCP path, as the carrier measured it: `{}` when nothing does, None for a UDP pair
        carry = (carried.get(f"wg{int((d.get('tunnel') or {}).get('slot') or 0)}") or {}
                 if transport == "tcp" else None)
        items.append({"office": oid, "declared": bool(link),
                      "delivery": delivery,
                      # the TUNNEL itself, measured where its interface lives — absent when nothing
                      # measures it, so a screen says "not measured" and never guesses
                      "tunnel": tunnel,
                      "transport": transport,
                      "carry": carry,
                      # where this office is the side that is dialed: is that port published at all
                      "listen": listen,
                      "verdict": _verdict(state, tunnel, delivery["door"], mispaired=_mispaired(d, home),
                                          listen=listen, carry=carry),
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
                      # The HERD it belongs to (DGO-1003), by the same order: the owner's mark on this
                      # record (an office whose code publishes none — WBC's), then what the office says
                      # about itself, else none — the screen groups an office with no herd with its own.
                      "herd": _peer_herd(d, cat),
                      "state": "up" if up else ("down" if state else "unknown"),
                      "state_at": state.get("at"),
                      "state_error": state.get("error") or "",
                      # The office's MARK (flt-004): the pair it published with its catalog, or the pair
                      # its NAME gets when it has published none yet — the same fallback the console's
                      # registry uses (platform/manager/serve.py `_mark`), so the row here and the tile
                      # there are one colour, and an office nobody has chosen for yet is not a blank.
                      "mark": _identity.clean_mark(cat.get("mark")) or _identity.mark_for(oid),
                      "commit": cat.get("commit") or "",
                      # THIS office's own source port for the pair, when the heal had to move it
                      # (DGO-1096): the one repair neither end can see, so every surface that lists a
                      # pair says it — with the port it came FROM and why. Absent (`None`) when it was
                      # never moved, so a screen never shows a repair that did not happen.
                      "source_port": ({k: (ports.get(oid) or {}).get(k)
                                       for k in ("port", "was", "at", "count", "why")}
                                      if (ports.get(oid) or {}).get("port") else None),
                      "apps": apps})
    return {"home": {"id": home["id"], "domain": home["domain"], "slot": (home.get("tunnel") or {}).get("slot"),
                     "fingerprint": (home.get("identity") or {}).get("fingerprint"),
                     "herd": _home_herd(),
                     # where this office is dialed now — `moved_from` when its declaration is stale
                     "listen": PAIRING.ports.listen() or None},
            "serve": home.get("serve") or {},
            "items": items, "tunnel": api_tunnel(), "proxy": api_link_proxy()}


_MAP_MACHINES: dict = {}


def _map_machine(office: str) -> dict:
    """WHERE an office runs — its machine as the Computers app reads it through the link (DGO-1006):
    the host's name, its system, cores and memory. Cached five minutes: the map is opened by a
    person, and a machine does not change between two looks. An office whose machine is not given
    to this one is an empty answer, never a guess."""
    at, facts = _MAP_MACHINES.get(office, (0.0, None))
    # an answer is kept five minutes; NO answer only thirty seconds — one blip of the Computers app
    # must not blank every machine for five minutes (the second reader of DGO-1006)
    if facts is not None and time.time() - at < (300 if facts else 30):
        return facts
    try:
        d = _get(f"{cv.COMPUTERS_URL}/api/hosts/{urllib.parse.quote(office)}/machine/api/overview?brief=1", 10)
        part = lambda k: (d.get(k) if isinstance(d, dict) and isinstance(d.get(k), dict) else {})  # noqa: E731
        host, cpu, mem = part("host"), part("cpu"), part("memory")
        facts = {k: v for k, v in {
            "hostname": host.get("hostname"), "os": host.get("os"), "arch": host.get("architecture"),
            "cores": cpu.get("cores") if isinstance(cpu.get("cores"), int) else None,
            "memory_gb": round(mem["total"] / 2 ** 30, 1) if isinstance(mem.get("total"), (int, float)) else None,
        }.items() if v and isinstance(v, (str, int, float))}
    except Exception as e:  # noqa: BLE001 — another machine's answer, of any shape, is one empty cell
        log.info("map: no machine facts for %s (%s)", office, type(e).__name__)
        facts = {}
    _MAP_MACHINES[office] = (time.time(), facts)
    return facts


def _map_apps(rows, hidden=()) -> list[dict]:
    """A catalog's apps as the map draws them: the name, what the app is, its icon, and whether it
    has an agent door (the CLI and the API, not only the screen)."""
    out = []
    for a in rows or []:
        if not isinstance(a, dict):
            continue
        title = a.get("title")
        out.append({"alias": str(a.get("alias") or ""), "app": str(a.get("app") or ""),
                    "title": (title.get("he") or title.get("en")) if isinstance(title, dict) else str(title or ""),
                    "desc": str(a.get("desc") or ""), "icon": str(a.get("icon") or ""),
                    "api": bool(a.get("api")), "hidden": str(a.get("alias") or "") in set(hidden)})
    return out


@app.get("/api/map")
def api_map():
    """The DGO MAP (DGO-1006): every herd this office sees, the offices of each, how each is linked
    and in which direction, where it runs, and what it gives — and, one hop further, what OTHER
    offices gave each of them (the `shared` sections of its catalog).

    The owner, 2026-10-22: «I want to see the group of DGO herds we have … every DGO in every group and
    every app we have access to … how everything is connected, where does everything run». Read-only;
    every fact is one this office already holds (its link plane, the catalogs it pulled) or asks the
    Computers app for — nothing here is a second record of the network.
    """
    from concurrent.futures import ThreadPoolExecutor

    link = api_link()
    home = cv.home_office()
    stored = catalog.load_all(STATE_DIR)
    hidden = projection.load_exclude(STATE_DIR)
    ids = [str(i.get("office") or "") for i in link.get("items") or []]
    with ThreadPoolExecutor(max_workers=6) as pool:
        machines = dict(zip(["local", *ids], pool.map(_map_machine, ["local", *ids])))
    items = []
    for i in link.get("items") or []:
        oid = str(i.get("office") or "")
        cat = stored.get(oid) or {}
        shared, _dropped = catalog.shared_sections(cat, home.get("id") or "")
        items.append({**{k: i.get(k) for k in ("office", "label", "herd", "kind", "direction", "state",
                                               "state_error", "transport", "endpoint", "commit", "mark")},
                      "handshake_age_s": (i.get("tunnel") or {}).get("handshake_age_s"),
                      "apps": _map_apps(cat.get("apps"), hidden.get(oid) or ()),
                      # a section's label may be a plain string (catalog.shared_sections allows it)
                      "shared": [{"office": s.get("office"),
                                  "label": ((s.get("label") or {}).get("he") if isinstance(s.get("label"), dict)
                                            else s.get("label")) or s.get("office"),
                                  "commit": s.get("commit") or "",
                                  "apps": _map_apps(s.get("apps"))} for s in shared],
                      "machine": machines.get(oid) or {}})
    own = build_catalog()
    return {"home": {"id": home.get("id"), "label": _home_label(home).get("he"), "herd": _home_herd(),
                     "commit": _home_commit(), "domain": home.get("domain"),
                     "apps": _map_apps(own.get("apps")), "machine": machines.get("local") or {}},
            "items": items, "at": int(time.time())}


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


def set_transport(oid: str, transport: str) -> dict:
    """Move ONE pair onto the TCP path (`tcp`) or back onto WireGuard's own UDP (`udp`), and re-render.

    A fact of the PAIR, so both offices say it, each in its own record: the two ends of a `tcp` pair
    point their interfaces at their own carriers, and an end that still sends UDP to the other's
    address is an end nobody hears. Nothing else about the pair changes — keys, addresses, firewall
    and doors are the ones it had — so moving back is the same call with `udp`.
    """
    import copy
    import net as netmod
    transport = str(transport or "").strip().lower()
    if transport not in netmod.TRANSPORTS:
        return _err(f"transport {transport!r} אינו udp או tcp", 400)
    d = load(oid)
    if not d:
        return _err("אין לשכה כזאת", 404)
    if (d.get("kind") or "") != "paired":
        # A declared office's far end is rendered by this office's converge (`step_link`), which does
        # not carry the transport yet — switching one end only would be a pair that hears nothing.
        return _err("רק זוג מצומד עובר לנתיב TCP — לשכה מוצהרת עדיין לא", 409)
    before_doc = copy.deepcopy(d)
    tun = dict(d.get("tunnel") or {})
    before = netmod.pair_transport(d)
    if transport == "udp":
        tun.pop("transport", None)
    else:
        tun["transport"] = transport
    d["tunnel"] = tun
    save(d)
    render = render_tunnel()
    if isinstance(render, JSONResponse):
        # The record and the rendered files must not disagree: what could not be rendered is undone.
        save(before_doc)
        render_tunnel()
        return render
    log.info("pair %s: transport %s -> %s", oid, before, transport)
    return {"office": oid, "transport": transport, "was": before,
            "carry": next((p for p in (_read_carry_plan().get("pairs") or [])
                           if p.get("office") == oid), None)}


def _read_carry_plan() -> dict:
    try:
        return json.loads((Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")) / "carry.json").read_text())
    except (OSError, ValueError):
        return {}


@app.post("/api/link/transport")
async def api_link_transport(request: Request):
    """`{"office": "hp-laptop", "transport": "tcp"}` — the pair's datagrams ride the carriers' TCP
    path (`dgo-carry`); `"udp"` puts them back on WireGuard's own. See `set_transport`."""
    body = (await request.json()) if await request.body() else {}
    oid = str(body.get("office") or "").strip()
    if not oid:
        return _err("צריך לסמן לשכה (office)", 400)
    return await run_in_threadpool(set_transport, oid, str(body.get("transport") or ""))


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
                    # an own app by its alias, or a re-shared one by `<alias>.<origin>` (catalog.reshare)
                    if not isinstance(alias, str) or not re.match(
                            r"^[a-z][a-z0-9-]{0,30}(\.[a-z][a-z0-9-]{1,30})?\Z", alias):
                        return _err(f"serve.only.{office}: {alias!r} אינו כינוי תקין", 400)
            continue
        if app == "shared":
            # What OTHER offices gave this one, handed on (catalog.shared_for): "*" or a list of
            # origin offices — the two forms an older office driving this one's far plan still reads.
            # Absent re-shares nothing.
            if spec != "*" and not isinstance(spec, list):
                return _err('serve.shared הוא "*" או רשימת לשכות', 400)
            for origin in spec if isinstance(spec, list) else []:
                if not isinstance(origin, str) or not catalog.OFFICE_RE.match(origin):
                    return _err(f"serve.shared: {origin!r} אינו מזהה לשכה תקין", 400)
            continue
        if app == "services":
            # The doors with no tile this office gives (DGO-945, `catalog.publishable_services`):
            # alias → {to, paths}. Never a port: the door's port is its own registry row's.
            _clean, why = catalog.clean_services(spec)
            if why:
                return _err(why, 400)
            continue
        if app == catalog.WILDCARD:
            # `"*"` — "every app this office runs" (`catalog.publishable`). A key, not an app: it has
            # no port of its own, because the link's ONE door answers for every app behind it.
            if not isinstance(spec, dict):
                return _err('serve["*"] חייב להיות אובייקט (למשל {})', 400)
            continue
        if not APP_ID_RE.match(str(app)):     # DGO-624: a key is an app id — it reaches the firewall's rule text
            return _err(f"serve: {app!r} אינו מזהה אפליקציה (אותיות לטיניות קטנות, ספרות ומקף)", 400)
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
        if to_user not in (None, ""):
            # DGO-622: stripped, checked with serve.py's header rule, and STORED stripped — the door writes it into a header.
            to_user = str(to_user).strip()
            if not HEADER_RE.match(to_user):
                return _err(f"ה-identity.to של {app} אינו שם משתמש תקין", 400)
            spec["identity"] = {**ident, "to": to_user}
        users = ident.get("from") if isinstance(ident, dict) else None
        if users not in (None, "", []):
            # DGO-622: `from` is a LIST of users, each stripped and checked like `to`, and stored stripped.
            names = [str(u).strip() for u in users] if isinstance(users, list) else None
            if names is None or not all(HEADER_RE.match(u) for u in names):
                return _err(f"ה-identity.from של {app} חייב להיות רשימת שמות משתמש תקינים", 400)
            spec["identity"] = {**(spec.get("identity") or {}), "from": names}
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
    # …and which linked office an app served here does NOT reach, because its `serve.only` list does
    # not name it (DGO-1269): widening that list is the owner's call, so it is said, not done.
    try:
        withheld = catalog.withheld_by_only(saved, (catalog.load_registry(REGISTRY_DIR) or {}).get("apps") or [])
    except Exception:                      # noqa: BLE001 — a report, never a reason to fail the save
        withheld = {}
    if withheld:
        log.info("serve: not given by serve.only — %s", "; ".join(f"{o}: {', '.join(a)}" for o, a in withheld.items()))
    return {"serve": saved, "tunnel": tunnel.get("rendered"),
            "proxy": tunnel.get("proxy"), **({"withheld": withheld} if withheld else {})}


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
    # The far end of a pair whose office dials and renders it: that office ships its plan for this one
    # (`converge._remote_delivery`), from facts only it holds, into `linkproxy.SHIPPED_DIR` — an INPUT
    # here, merged with this office's own pairs below, never replaced by them. A plan an older office
    # wrote straight into the rendered file is saved as its input first, or this render would erase it.
    legacy = linkproxy.read(base).get("plan") or {}
    if legacy.get("rendered_by") and linkproxy.keep_shipped(base, legacy):
        log.warning("link proxy: the plan %s wrote into %s is kept as its input (%s/)",
                    legacy["rendered_by"], linkproxy.PLAN_NAME, linkproxy.SHIPPED_DIR)
    shipped = linkproxy.read_shipped(base)
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
    facts = {"served_by_peer": catalog.served_by_peer(catalog.load_all(STATE_DIR)),
             "control_bind": _link_proxy_bind(),
             "registry": catalog.load_registry(REGISTRY_DIR)}
    try:
        return linkproxy.write_multi(base, home, pairs, shipped=shipped, **facts)
    except linkproxy.LinkProxyError as e:
        if not shipped:
            log.warning("the delivery plan was refused and NOT written: %s", e)
            return {"rules": [], "refused": str(e)}
        # A plan another office shipped must not close the doors this office declares itself.
        log.warning("the plans shipped by %s do not fit beside this office's own (%s) — rendered "
                    "without them", ", ".join(sorted(shipped)), e)
        shipped_refused = str(e)
    try:
        return {**linkproxy.write_multi(base, home, pairs, **facts), "shipped_refused": shipped_refused}
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
        agents = sorted(_named_agents(cv.home_office()))
        log.info("agent tokens go to linked offices for: %s", ", ".join(agents) or "none (no agent named)")
    except Exception as e:                              # noqa: BLE001 — a log line is not the start
        log.warning("the named agents could not be read at startup: %s", e)
    try:
        plan = render_link_proxy()
        log.info("link proxy plan: %d rule(s)%s", len(plan.get("rules") or []),
                 f" (refused: {plan['refused']})" if plan.get("refused") else "")
    except Exception as e:                              # noqa: BLE001 — see the docstring
        log.warning("the delivery plan could not be rendered at startup: %s", e)
    # AN UPDATE THAT CHANGES WHAT A PAIR RENDERS reaches its interface here, with the carrier's plan,
    # not at the next plan change. Measured 2026-11-01 on the Dell (DGO-1080): the update moved the
    # MacBook's carried pair to its own port, this startup wrote that port into carry.json alone, wg3's
    # file kept 51830, dgo-net came back with wg3 holding 51830 first — and the HP's pair, which is
    # dialed on 51830, ran without a tunnel until the tunnel was rendered by hand.
    try:
        _render_tunnel_if_stale()
    except Exception as e:                              # noqa: BLE001 — see the docstring
        log.warning("the tunnel could not be checked at startup: %s", e)
    try:
        carried = render_carry_plan()
        if carried.get("pairs"):
            log.info("carrier plan: %d pair(s) on the TCP path%s", len(carried["pairs"]),
                     f", accepting on {carried['listen']}" if carried.get("listen") else ", dialing")
    except Exception as e:                              # noqa: BLE001 — see the docstring
        log.warning("the carrier plan could not be rendered at startup: %s", e)
    # The remote offices' apps (DGO-37): pull the peers' catalogs, project them onto
    # platform.state.yaml, and re-render the delivery plan from what came back. Started here rather
    # than in a converge step so a restarted container re-derives the picture instead of waiting for
    # the next converge of this office.
    _start_projection()
    # the daily checks offices declared (`watch: {health: daily}`, FPG-26)
    _start_watch()
    # An office that DECLARED a join (`DGO_JOIN`) carries it out by itself, and keeps it carried
    # out: a sandbox reborn with new keys asks again the moment it is up (join_api.py).
    if join_api.declared():
        threading.Thread(target=JOINER.run_forever, daemon=True, name="dgo-join").start()


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
        "home": home_source(max_age=30),     # the form pins a peer to home.commit: never a stale one
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
        if r and _run_kind(r) in ("backup", "repair"):
            # the daily backup (or a link repair) in progress is not the office's state: the card keeps its
            # last converge and health check (FPG-26); the backup is the office's own page's to show
            p = _run_file(o["id"])
            try:
                r = json.loads(p.read_text()) if p.exists() else r
            except (OSError, ValueError):
                pass
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
    return {**o, "run": last_run(oid), "backup_run": last_backup_run(oid)}


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
    _run_file(oid, "backup").unlink(missing_ok=True)
    _run_file(oid, "repair").unlink(missing_ok=True)
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


@app.get("/api/office/{oid}/watch")
def api_watch(oid: str, days: int = 7):
    """The office's daily checks and the weekly report's text (FPG-26)."""
    if not load(oid):
        return _err("אין לשכה כזו", 404)
    return watch_report(oid, max(1, min(int(days), 90)))


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
# The most of a passed-on body this process holds at once, per request (see peer_proxy).
PASS_CHUNK = 64 * 1024


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
    # In pieces of a BOUNDED size: with `chunk_size=None`, urllib3 reads a body that has a
    # Content-Length with ONE `read(None)`, the whole file in memory, and a meeting's recording opened
    # as a remote tile is hundreds of MB in a 160M container. The console was OOM-killed that way five
    # times on FPG (DGO-1231). An event-stream is chunked, so it keeps None: each event passes on as
    # it arrives.
    stream = "text/event-stream" in (r.headers.get("Content-Type") or "").lower()
    if stream:
        out["Cache-Control"] = "no-cache, no-transform"
    return StreamingResponse(r.iter_content(chunk_size=None if stream else PASS_CHUNK),
                             status_code=r.status_code, headers=out)


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
        """The tunnel addresses this office holds — its own (the tunnel's addressing), and the FAR end
        of every link another office converged onto it, which has no record here and may not be in
        this container's addressing at all: vps1's link with the MacBook is the HOST's wg0, and only
        the plan the MacBook shipped (`link-proxy.d/macbook.json`, `pairs[].self`) names it. Missing it
        gave vps1's first JOIN slot 2 — the MacBook's (2026-10-19): the door ports collided, vps1
        refused the MacBook's plan, and that link answered nothing until the join was undone."""
        import linkproxy
        out = [projection.own_address_cached(cv)]
        try:
            for plan in linkproxy.read_shipped(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")).values():
                out.append(str(plan.get("self") or ""))
                out.extend(str((p or {}).get("self") or "") for p in plan.get("pairs") or []
                           if isinstance(p, dict))
        except Exception as e:                              # noqa: BLE001 — fewer addresses, never no pairing
            log.warning("the shipped plans could not be read for the pair slots: %s", e)
        return [a for a in dict.fromkeys(out) if a]

    def save(self, doc: dict) -> None:
        # the declaration's one writer for link-decided fields; the record was validated by the engine
        cv.save_declaration(doc)
        _run_file(doc["id"]).unlink(missing_ok=True)      # a replaced INSTALLED office's last run is not this peer's
        _run_file(doc["id"], "backup").unlink(missing_ok=True)
        _run_file(doc["id"], "repair").unlink(missing_ok=True)

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

    def vault_forget_agents(self, oid: str) -> None:
        """The agent credentials taken from `oid` over the link (`projection.pull_agents`)."""
        import links
        try:
            projection.forget_agents(oid)
        except Exception as e:                          # noqa: BLE001 — a memo is not the unpair
            log.warning("the agent pulls of %s were not forgotten: %s", oid, e)
        try:
            rows = links._call("GET", f"/api/instances?protocol={links.PROTOCOL}").get("instances") or []
        except links.LinkError as e:
            log.warning("the agent credentials of %s were not listed: %s", oid, e)
            return
        for row in rows:
            name = str((row or {}).get("id") or "")
            # by the hint (`<me>-><oid> agent:<app>`) as well as the name: `hp` must not take `hp-laptop`'s
            if name.startswith(f"{links.PROTOCOL}-serve-{oid}-") and name.endswith("-agent") \
                    and f"->{oid} agent:" in str(row.get("account_hint") or ""):
                self.vault_delete(name)

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
                if isinstance(r, dict) and r.get("alias")
                and catalog.SELF not in (r.get("app"), r.get("alias"))]   # DGO-624: never given — see catalog.publishable

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

# ── joining by declaration (join_api.py): the host half answers the office's link door, the joiner
# half carries out this office's own `DGO_JOIN`. Both run the pairing above — one engine, one record.
JOIN_HUB = join_api.Hub(PAIRING, Path(STATE_DIR) / "join.json", notify=_notify)
JOINER = join_api.Joiner(PAIRING, Path(STATE_DIR) / "join-self.json")
app.include_router(join_api.build_public_router(JOIN_HUB))
app.include_router(join_api.build_admin_router(JOIN_HUB, JOINER))


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


# THE SCREEN'S OWN ADDRESSES answer with the screen. The page routes by PATH (`showRoute`) — the map at
# `map/<office>/<app>` (DGO-1006) and a declaration at `<office id>` — and the console carries a frame's
# path into its own address. Before these, a reload of either answered 404, inside the console and out
# (measured 2026-10-22). Registered LAST, so every route above keeps its own path; an office id is the
# declaration's own rule (ID_RE), so nothing else is taken by the catch.
def _sub_page(request: Request) -> Response:
    """The page at one of its own deeper addresses. Its URLs are relative (`static/…`, `api/…`): inside
    the console its base is the console's (`/a/dgo-extend/`, injected there — the request then carries
    `X-Forwarded-Prefix`), and on the app's own host the base is the host's root, said here — without
    it `map/hp-laptop/browser42` asked for `map/hp-laptop/static/app.js` and stalled on «טוען…»."""
    page = _page("index.html", "app.js")
    if request.headers.get("x-forwarded-prefix"):
        return page
    html = page.body.decode("utf-8").replace("<head>", '<head><base href="/">', 1)
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/map")
@app.get("/map/{rest:path}")
def map_page(request: Request, rest: str = ""):
    return _sub_page(request)


@app.get("/{oid}")
def office_page(request: Request, oid: str):
    if not ID_RE.match(oid):
        return _err("אין מסך כזה", 404)
    return _sub_page(request)
