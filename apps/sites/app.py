"""sites — the office's sites, as ONE platform service.

What this app is
----------------
Every website the business runs, in one place: what it is, which machine it runs on, whether it is
up right now, who visited it, and what is wrong with it (TLS, headers, exposed files, SEO, beauty).
It is the answer to "how do I know the sites are fine" that does not involve opening four control
panels and a browser tab.

Where it stands
---------------
On the `computers` service, entirely. A site is a ROW HERE; the machine it runs on is a connection
instance in the credential plane owned by `computers` (see machines.py). This app holds no host, no
key and no socket: every byte it reads and every command it runs on a machine goes through that
service's `/exec`. Which is also why "which machines exist" is not a question this app can answer
wrongly — it asks.

The pattern, and why there is one
---------------------------------
A site is not "an nginx someone started once". It is a directory on a machine
(`/opt/bina-sites/<id>/`) holding a rendered compose stack, an nginx config, a metadata file and a
README, owned by one compose project, serving one hostname set, writing one JSON access log
(runtime.py documents it in full). Rendered, not hand-written: the site's RECORD in this app is the
source of truth, and the files on the machine are a build artifact of it. That is the same rule the
platform applies to itself (`ai/context/build-your-first-app.md`: declare, do not register), applied
to the things the business sells.

Three kinds of site live under that one pattern — `static` (files), `git` (a repository, optionally
built by a one-shot builder service) and `proxy` (an upstream) — plus `adopted`, which is a site that
predates the office: it is monitored and scanned exactly like the others, and migrated into the
pattern when the owner says so, not before (runtime.deploy refuses to touch an adopted stack).

The one door for consumers
--------------------------
`POST /<op>` with the ops declared in app.json — `listSites`, `getSite`, `createSite`, `startSite`,
`stopSite`, `checkSite`, `uptime`, `visits`, `scan` — so the console, another app or the office agent
never learns an internal URL. The UI is this app's own; the data behind it is the same data.
"""
from __future__ import annotations

import logging
import os
import threading
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import checks
import machines
import public
import runtime
import scheduler
import store
from machines import MachineError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sites")

DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "bina-deployment")
RENDER_DIR = Path(os.environ.get("SITES_RENDER_DIR", "/renders"))
DEFAULT_ROOT = runtime.DEFAULT_ROOT
_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="sites", docs_url=None, redoc_url=None, openapi_url=None)


def _err(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def _json(fn, *a, **kw):
    """Run a function that may raise MachineError / KeyError and turn it into an answer."""
    try:
        return fn(*a, **kw)
    except MachineError as e:
        return JSONResponse(e.body(), status_code=e.status)
    except KeyError as e:
        return _err(f"לא נמצא: {e}", 404)


# ── health / contract ────────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "sites"}


@app.get("/readyz")
def readyz():
    """Ready = the sites exist AND the fleet service answers. It does NOT require a site to be up:
    a site being down is the thing this app is FOR, and reporting the app itself unready would page
    the operator about the wrong component."""
    machines_list, err = machines.list_machines()
    if err:
        return JSONResponse({"ready": False, "reason": err}, status_code=503)
    return {"ready": True, "sites": len(store.list_sites()), "machines": len(machines_list)}


@app.get("/manifest")
def manifest():
    return {
        "service": "sites",
        "protocols": [],
        "ops": sorted(OPS),
        "connection": {"kind": "machines", "service": "computers"},
        "capabilities": {"multi_connection": False, "manages_machines": True,
                         "checks": [c["name"] for c in checks.catalog()],
                         "pattern": "bina-site.v1", "renderer": bool(os.environ.get(
                             "SITES_RENDER_URL", ""))},
    }


@app.get("/providers")
def providers():
    """No credential providers of its own, and that is a decision, not an omission: a site is not a
    credential, and the machines it runs on are `computers`' instances. An empty catalogue here is
    what keeps two copies of the fleet from existing."""
    return {"providers": []}


@app.get("/connections")
def connections():
    machines_list, err = machines.list_machines()
    if err:
        return {"active": None, "connections": [], "reason": err}
    return {"active": None, "connections": [
        {"id": m.get("id"), "protocol": "computer_ssh", "label": m.get("label"),
         "account_hint": m.get("host"), "status": m.get("state") or "ok"}
        for m in machines_list], "note": "המחשבים שייכים לאפליקציית „מחשבים” — כאן הם מוצגים לקריאה."}


@app.get("/ops")
def ops_index():
    return {"service": "sites", "interface": "sites.v1", "ops": sorted(OPS),
            "checks": checks.catalog(),
            "params": {"site": "מזהה האתר (id)", "machine": "מזהה מחשב מתוך /api/machines"}}


# ── the fleet, proxied from `computers` ──────────────────────────────────────────────────────────
@app.get("/api/machines")
def api_machines(probe: int = 1):
    machines_list, err = machines.list_machines(probe=bool(probe))
    if err:
        return _err(err, 502)
    return {"machines": machines_list, "count": len(machines_list),
            "note": "כל פעולה במחשב עוברת דרך אפליקציית „מחשבים”."}


@app.get("/api/machines/{mid}/audit")
def api_machine_audit(mid: str, fresh: int = 0):
    """The MACHINE's own security, asked of the service that owns machines and proxied here.

    A site's security and its host's security are different questions with different fixes — a site
    can be perfectly hardened on a server that accepts SSH passwords — and the owner looking at a
    site is exactly the person who needs to see the second one without going to another screen.
    """
    machines_list, err = machines.list_machines(probe=False)
    if err:
        return _err(err, 502)
    if not any(m.get("id") == mid for m in machines_list):
        return _err("לא נמצא מחשב כזה", 404)
    import requests as _rq
    try:
        r = _rq.get(f"{machines.COMPUTERS_URL}/api/computers/{mid}/audit",
                    params={"fresh": 1 if fresh else 0}, timeout=200)
        return JSONResponse(r.json(), status_code=r.status_code)
    except _rq.RequestException as e:
        log.warning("api_machine_audit: %r", e)
        return _err("שירות המחשבים אינו זמין", 502)
    except ValueError:
        return _err("שירות המחשבים החזיר תשובה שאינה JSON", 502)


@app.get("/api/machines/{mid}/edge")
def api_machine_edge(mid: str):
    return _json(runtime.probe_edge, mid)


@app.post("/api/machines/{mid}/inspect")
async def api_machine_inspect(mid: str, request: Request):
    """Look at a container that ALREADY serves a site — how an existing site is adopted without
    anybody typing its hostnames from memory."""
    body = (await request.json()) if await request.body() else {}
    container = (body or {}).get("container") or ""
    if not container:
        return _err("חסר שם קונטיינר (container)")
    return _json(runtime.inspect_existing, mid, container)


# ── sites ────────────────────────────────────────────────────────────────────────────────────────
def site_view(site: dict, with_uptime: bool = True) -> dict:
    out = dict(site)
    if with_uptime:
        out["uptime"] = store.uptime_summary(site["id"], 24)
        out["uptime_7d"] = store.uptime_summary(site["id"], 24 * 7)
    out["findings"] = _finding_counts(site["id"])
    out["visits"] = store.visits_total(site["id"], 7)
    out["url"] = runtime.site_url(site)
    out["container"] = runtime.container_name(site)
    out["managed"] = runtime.is_managed(site)
    out["log_source"] = runtime.log_source(site)["kind"]
    return out


def _finding_counts(sid: str) -> dict:
    counts = {"error": 0, "warn": 0, "info": 0, "ok": 0}
    for f in store.findings(sid):
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


@app.get("/api/overview")
def api_overview():
    sites = store.list_sites()
    machines_list, merr = machines.list_machines(probe=False)
    rows = []
    for s in sites:
        rows.append({**{k: s[k] for k in ("id", "label", "machine", "hosts", "kind", "source",
                                          "enabled", "monitor", "last_state", "last_checked",
                                          "last_error")},
                     "url": runtime.site_url(s),
                     "uptime": store.uptime_summary(s["id"], 24),
                     "visits": store.visits_total(s["id"], 7),
                     "findings": _finding_counts(s["id"])})
    return {"sites": rows, "machines": machines_list, "machines_error": merr,
            "scheduler": scheduler.status(), "checks": checks.catalog()}


@app.get("/api/sites")
def api_sites():
    return {"sites": [site_view(s) for s in store.list_sites()],
            "machines": machines.list_machines(probe=False)[0],
            "checks": checks.catalog()}


def _validate_new(body: dict) -> tuple[dict | None, JSONResponse | None]:
    sid = (body.get("id") or "").strip().lower()
    if not runtime.slug_ok(sid):
        return None, _err("מזהה האתר חייב להיות באנגלית קטנה עם מקפים (למשל bina-solutions)")
    if store.get_site(sid):
        return None, _err(f"אתר בשם {sid} כבר קיים", 409)
    hosts = [h.strip().lower() for h in (body.get("hosts") or []) if h and h.strip()]
    for h in hosts:
        if not re.fullmatch(r"[a-z0-9*.-]{3,253}", h):
            return None, _err(f"שם האתר אינו תקין: {h}")
    machine_id = (body.get("machine") or "").strip()
    fleet, err = machines.list_machines(probe=False)
    if err:
        return None, _err(err, 502)
    if not any(m.get("id") == machine_id for m in fleet):
        return None, _err("יש לבחור מחשב מהרשימה (ראו /api/machines)")
    kind = body.get("kind") or "static"
    if kind not in ("static", "static-built", "proxy"):
        return None, _err("סוג אתר לא מוכר")
    content = dict(body.get("content") or {})
    if kind == "proxy" and not content.get("upstream"):
        return None, _err("אתר מסוג proxy צריך כתובת upstream")
    if content.get("type") == "git" and not content.get("repo"):
        return None, _err("תוכן מסוג git צריך כתובת מאגר (repo)")
    site = {
        "id": sid, "label": (body.get("label") or sid).strip(), "machine": machine_id,
        "hosts": hosts, "kind": kind,
        "root": (body.get("root") or f"{DEFAULT_ROOT}/{sid}").strip(),
        "project": (body.get("project") or f"site-{sid}").strip(),
        "port": int(body.get("port") or 80),
        "health_path": body.get("health_path") or "/",
        "content": content if content else ({"type": "dir", "dir": "site"} if kind != "proxy"
                                            else {"type": "dir", "upstream": content.get("upstream")}),
        "edge": body.get("edge") or None,
        "checks": body.get("checks") or {},
        "source": body.get("source") or "office",
        "legacy": body.get("legacy") or {},
        "notes": body.get("notes") or "",
        "monitor": body.get("monitor", True),
        "enabled": True,
    }
    if not site["edge"]:
        site["edge"] = runtime.default_edge(machine_id)
    return site, None


@app.post("/api/sites")
async def api_sites_post(request: Request):
    """Create a site. `deploy: true` renders and starts it in the same call — the wizard's path.

    Creation NEVER touches a machine unless deploy is asked for: the record is useful on its own
    (an adopted site has no stack to render) and a create that fails halfway because a VPS is
    unreachable would leave the owner unable to describe what they wanted.
    """
    body = (await request.json()) if await request.body() else {}
    site, bad = _validate_new(body or {})
    if bad:
        return bad
    saved = store.upsert_site(site)
    store.event(saved["id"], "create",
                f"האתר נוצר ({saved['source']}) במחשב {saved['machine']}",
                {"hosts": saved["hosts"], "kind": saved["kind"]})
    out: dict = {"ok": True, "site": site_view(saved)}
    if (body or {}).get("deploy") and runtime.is_managed(saved):
        res = _json(runtime.deploy, saved)
        if isinstance(res, JSONResponse):
            out["deploy"] = res.body.decode()[:2000] if hasattr(res, "body") else "failed"
            out["ok"] = False
            return JSONResponse(out, status_code=res.status_code)
        out["deploy"] = res
        store.event(saved["id"], "deploy", "האתר הועלה", {"ok": res.get("ok")})
    return out


@app.get("/api/sites/{sid}")
def api_site(sid: str):
    site = store.get_site(sid)
    if not site:
        return _err("לא נמצא אתר כזה", 404)
    view = site_view(site)
    view["status"] = _json(runtime.status, site)
    view["findings_list"] = store.findings(sid)
    view["runs"] = store.runs(sid, 12)
    view["events"] = store.recent_events(sid, 25)
    return view


@app.patch("/api/sites/{sid}")
async def api_site_patch(sid: str, request: Request):
    """Change a site's record. Everything except the id; a deploy is a separate, explicit act.

    A change to the PUBLIC PATH is not only a record edit: it decides who serves the site, so the
    save is followed by the convergence that makes the record true — the site's own container
    stopped (or started again), the content pulled into the office's cache, and the edge file
    rewritten. Doing it here rather than in the UI is the point: the same change made over the API
    by an agent has the same effect.
    """
    site = store.get_site(sid)
    if not site:
        return _err("לא נמצא אתר כזה", 404)
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    body.pop("id", None)
    if "hosts" in body:
        body["hosts"] = [h.strip().lower() for h in (body["hosts"] or []) if h and h.strip()]
    if isinstance(body.get("public"), dict) and "entries" in body["public"]:
        entries, bad = public.clean_entries(body["public"]["entries"],
                                            body.get("hosts") or site.get("hosts") or [])
        if bad:
            return _err(bad, 400)
        body["public"] = {**body["public"], "entries": entries}
    merged = {**site, **body}
    saved = store.upsert_site(merged)
    store.event(sid, "update", "הגדרות האתר עודכנו",
                {"fields": sorted(body.keys())})
    out = {"ok": True, "site": site_view(saved)}
    if "public" in body:
        threading.Thread(target=_converge_public_bg, args=(saved, site), daemon=True,
                         name=f"sites-public-{sid}").start()
        out["public"] = {"started": True, "mode": public.mode_of(saved),
                         "note": "ההעברה החלה ברקע — מצב האתר והאירועים יראו אותה"}
    return out


#: The last convergence, for the screen: a PATCH answers at once and the work continues here.
_converge_state: dict = {"running": False, "site": "", "at": 0, "result": None, "error": ""}


def _converge_public(site: dict, prev: dict, apply_mode: bool = True) -> dict:
    """Make the serving mode true.

    THE ORDER IS THE WHOLE POINT, and it is what keeps the site up while its server changes:

      to `office`   sync the content FIRST (the container is still answering), then publish the
                    edge (the office's routers win by priority while both exist), and only then
                    stop the container — so there is no moment in which nothing serves the site.
      to `container` start the container first (its own routers come back with it), then publish,
                    which removes the office's routers.

    Measured on the first two flips (2026-10-02): the old order — stop, sync, publish — left
    bina-solutions.co.il answering 404 for about fifteen seconds between the two.
    """
    mode = public.mode_of(site)
    report: dict = {"mode": mode}
    if not public.entries_of(site):
        report["warning"] = "לא הוגדר נתיב ציבורי — לאתר אין כתובת פומבית"
        return report
    if mode == "office":
        report["sync"] = _json(public.sync, site, True)
        if isinstance(report["sync"], JSONResponse):
            report["sync"] = {"ok": False, "reason": report["sync"].body.decode()[:200]}
        report["edge"] = _json(public.publish, "", True)
        if apply_mode:
            report["container"] = public.container_action(site, "stop")
    else:
        if apply_mode:
            report["container"] = public.container_action(site, "start")
        report["edge"] = _json(public.publish, "", True)
    return report


def _converge_public_bg(site: dict, prev: dict) -> None:
    """`_converge_public` off the request thread.

    A convergence is a content pull (seconds), an edge write and a compose stop — and the door this
    office is reached through drops a connection after a few seconds, so a synchronous answer would
    be an answer nobody receives (measured: HTTP 000 after 5.2s, while the work itself completed).
    The outcome is recorded as the site's own event and in `_converge_state`.
    """
    _converge_state.update({"running": True, "site": site["id"], "at": store.now(),
                            "result": None, "error": ""})
    try:
        rep = _converge_public(site, prev)
        _converge_state.update({"result": rep, "error": ""})
        store.event(site["id"], "public", "הנתיב הציבורי עודכן", rep)
    except Exception as e:                                     # noqa: BLE001
        _converge_state.update({"error": f"{type(e).__name__}: {e}"[:300]})
        store.event(site["id"], "public_failed", "עדכון הנתיב הציבורי נכשל",
                    {"error": _converge_state["error"]})
        log.warning("public convergence failed for %s: %s", site["id"], e)
    finally:
        _converge_state["running"] = False


@app.delete("/api/sites/{sid}")
def api_site_delete(sid: str, purge_files: int = 0, confirm: str = "", stop: int = 1):
    """Forget a site. Files are KEPT unless `purge_files=1&confirm=<id>`.

    The confirmation is the site's own id, not a boolean: this is the one call in the app that can
    delete somebody's website content, and a flag that can be sent by accident (a retried request, a
    stale tab) is not a confirmation. Deleting the RECORD of an adopted site never touches the site
    itself unless `stop=1` asks for it.
    """
    site = store.get_site(sid)
    if not site:
        return _err("לא נמצא אתר כזה", 404)
    if purge_files and confirm != sid:
        return _err("מחיקת קבצים דורשת אישור מפורש: confirm=<id>", 409)
    res = _json(runtime.remove, site, bool(purge_files)) if stop else {"skipped": True}
    store.delete_site(sid)
    store.event(None, "delete", f"האתר {sid} הוסר מהניהול",
                {"purge_files": bool(purge_files), "stopped": bool(stop)})
    cache = public.forget(sid)
    return {"ok": True, "removed": sid, "machine_action": res, "cache": cache}


# ── lifecycle ────────────────────────────────────────────────────────────────────────────────────
def _site_or_404(sid: str) -> tuple[dict | None, JSONResponse | None]:
    site = store.get_site(sid)
    if not site:
        return None, _err("לא נמצא אתר כזה", 404)
    return site, None


@app.post("/api/sites/{sid}/deploy")
async def api_site_deploy(sid: str, request: Request):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    body = (await request.json()) if await request.body() else {}
    res = _json(runtime.deploy, site, bool((body or {}).get("build", True)))
    if isinstance(res, JSONResponse):
        store.event(sid, "deploy_failed", "העלאה נכשלה", {"detail": res.body.decode()[:400]})
        return res
    store.event(sid, "deploy", "האתר הועלה", {"ok": res.get("ok")})
    return {"ok": True, "deploy": res, "status": _json(runtime.status, site)}


@app.post("/api/sites/{sid}/{action}")
async def api_site_action(sid: str, action: str, request: Request):
    """start | stop | restart | probe | collect | scan — one route, because they are one kind of
    thing: an action the owner asks for now, whose result is reported as it happened."""
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    if action == "start":
        res = _json(runtime.start, site)
        store.event(sid, "start", "האתר הופעל")
    elif action == "stop":
        res = _json(runtime.stop, site)
        store.event(sid, "stop", "האתר כובה")
    elif action == "restart":
        res = _json(runtime.restart, site)
        store.event(sid, "restart", "האתר הופעל מחדש")
    elif action == "probe":
        res = scheduler.check_uptime(site)
        res["uptime"] = store.uptime_summary(sid, 24)
    elif action == "collect":
        res = _json(scheduler.collect_visits, site)
    elif action == "seed":
        res = _json(runtime.seed_content, site, bool(body.get("force")))
        store.event(sid, "seed", "תוכן האתר הועתק לדפוס", res if isinstance(res, dict) else {})
    elif action == "sync":
        res = _json(public.sync, site, bool(body.get("force")))
        if isinstance(res, dict) and res.get("ok"):
            store.event(sid, "sync", f"התוכן נאסף ללשכה ({res.get('files')} קבצים)")
    elif action == "publish":
        res = _json(public.publish, "", True)
        if isinstance(res, dict) and res.get("ok"):
            store.event(sid, "publish", "הנתיב הציבורי פורסם בקצה", res)
    elif action == "scan":
        names = body.get("checks") or None
        res = scheduler.run_scan(sid, names, trigger="manual")
    else:
        return _err("פעולה לא מוכרת", 404)
    if isinstance(res, JSONResponse):
        return res
    return {"ok": True, "action": action, "result": res, "site": site_view(site)}


@app.get("/api/sites/{sid}/status")
def api_site_status(sid: str):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {**_json(runtime.status, site), "uptime": store.uptime_summary(sid, 24)}


@app.get("/api/sites/{sid}/logs")
def api_site_logs(sid: str, lines: int = 120):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {"site": sid, "container": runtime.container_name(site),
            "logs": _json(runtime.logs, site, lines)}


@app.get("/api/sites/{sid}/stack")
def api_site_stack(sid: str):
    """The files a deploy WOULD write — readable before anything is written anywhere."""
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {"site": sid, "root": site["root"], "machine": site["machine"],
            "files": runtime.files(site), "managed": runtime.is_managed(site)}


@app.get("/api/sites/{sid}/uptime")
def api_site_uptime(sid: str, hours: int = 24):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {"site": sid, "summary": store.uptime_summary(sid, hours),
            "summary_7d": store.uptime_summary(sid, 24 * 7),
            "samples": store.samples(sid, hours)}


@app.get("/api/sites/{sid}/visits")
def api_site_visits(sid: str, days: int = 7):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {"site": sid, "totals": store.visits_total(sid, days),
            "series": store.visit_series(sid, days),
            "paths": store.top_paths(sid, days), "refs": store.top_refs(sid, days),
            "source": runtime.log_source(site)}


@app.get("/api/sites/{sid}/findings")
def api_site_findings(sid: str, resolved: int = 0):
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return {"site": sid, "findings": store.findings(sid, include_resolved=bool(resolved)),
            "runs": store.runs(sid, 12)}


@app.get("/api/sites/{sid}/shot")
def api_site_shot(sid: str, file: str):
    """A rendered screenshot the beauty check kept. Served from the shared render volume, so the
    office never has to copy a 400 KB PNG through a database."""
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    target = (RENDER_DIR / file).resolve()
    try:
        target.relative_to(RENDER_DIR.resolve())
    except ValueError:
        return _err("נתיב לא חוקי", 400)
    if not target.is_file():
        return _err("לא נמצא צילום כזה", 404)
    return FileResponse(target, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


# ── the public path: the office serving a site itself (`public.py`) ──────────────────────────────
def _public_response(sid: str, path: str, request: Request) -> Response:
    """One public request → the site's own file.

    Reached ONLY through the routers `public.publish()` writes: the edge maps
    `<domain><path>` onto `/public/<id>/<rest>`, with no SSO middleware in front of it. Everything
    about the office's own surface (its API, its console) is a different prefix on a different
    router, and a site that is not `mode: office` answers 404 here rather than being served twice.
    """
    site = store.get_site(sid)
    if not site or public.mode_of(site) != "office":
        return Response(content=b"Not Found", status_code=404, media_type="text/plain")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    out = public.serve(site, path, host=host)
    return Response(content=out["body"], status_code=out["status"], headers=out["headers"])


@app.get("/public/{sid}")
def public_serve_root(sid: str, request: Request):
    return _public_response(sid, "", request)


@app.get("/public/{sid}/{path:path}")
def public_serve(sid: str, path: str, request: Request):
    return _public_response(sid, path, request)


@app.get("/api/sites/{sid}/slots")
def api_site_slots(sid: str):
    """Which texts and pictures of the site are slots already, and which are still hand-written."""
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    return _json(public.slots_scan, site)


@app.post("/api/sites/{sid}/slots/apply")
async def api_site_slots_apply(sid: str, request: Request):
    """`digital-assets`' website channel pushes the active bundle here; the site's files are
    rewritten on the machine and the office's cache is refreshed from them."""
    site, bad = _site_or_404(sid)
    if bad:
        return bad
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    bundle = body.get("bundle") or {}
    if not isinstance(bundle, dict) or not bundle.get("slots"):
        return _err("לא התקבלו משבצות (bundle.slots) לעדכון", 400)
    res = _json(public.slots_apply, site, bundle, body.get("actor") or "", body.get("client") or "")
    if isinstance(res, JSONResponse):
        return res
    return {"ok": True, **res, "site": site_view(site)}


@app.get("/api/domains")
def api_domains():
    """The domains a public path can be put on — the `domains` app's own list, passed through."""
    return public.domains_list()


@app.get("/api/public")
def api_public_state():
    """What the office is serving right now, and where the edge file went."""
    rows = public.office_sites()
    return {"sites": [{"id": s["id"], "domains": [e["domain"] for e in public.entries_of(s)],
                       "cached_files": public.cached_file_count(s["id"]),
                       "synced_at": public.meta(s["id"]).get("at")} for s in rows],
            "machine": public._state.get("machine") or "",
            "published_at": public._state.get("at") or 0,
            "converge": _converge_state,
            "assets": public.bundle() is not None,
            "assets_url": public.ASSETS_URL}


# ── the canonical op surface (platform-service.v1) ───────────────────────────────────────────────
def _op_site(body: dict) -> tuple[dict | None, JSONResponse | None]:
    sid = body.get("site") or body.get("id")
    if not sid:
        return None, _err("חסר שדה: site")
    return _site_or_404(sid)


@app.post("/listSites")
async def op_list_sites(request: Request):
    body = (await request.json()) if await request.body() else {}
    return {"ok": True, "data": [site_view(s, with_uptime=bool((body or {}).get("uptime")))
                                 for s in store.list_sites()]}


@app.post("/getSite")
async def op_get_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    return {"ok": True, "data": api_site(site["id"])}


@app.post("/createSite")
async def op_create_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    return await api_sites_post(_FakeRequest(body or {}))


@app.post("/deleteSite")
async def op_delete_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    site, bad = _op_site(body)
    if bad:
        return bad
    return api_site_delete(site["id"], purge_files=1 if body.get("purge_files") else 0,
                           confirm=body.get("confirm") or "", stop=1 if body.get("stop", 1) else 0)


@app.post("/startSite")
async def op_start_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    res = _json(runtime.start, site)
    return res if isinstance(res, JSONResponse) else {"ok": True, "data": res}


@app.post("/stopSite")
async def op_stop_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    res = _json(runtime.stop, site)
    return res if isinstance(res, JSONResponse) else {"ok": True, "data": res}


@app.post("/checkSite")
async def op_check_site(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    return {"ok": True, "data": scheduler.check_uptime(site)}


@app.post("/uptime")
async def op_uptime(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    hours = int((body or {}).get("hours") or 24)
    return {"ok": True, "data": {"summary": store.uptime_summary(site["id"], hours),
                                 "summary_7d": store.uptime_summary(site["id"], 24 * 7)}}


@app.post("/visits")
async def op_visits(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    days = int((body or {}).get("days") or 7)
    return {"ok": True, "data": {"totals": store.visits_total(site["id"], days),
                                 "paths": store.top_paths(site["id"], days),
                                 "refs": store.top_refs(site["id"], days),
                                 "series": store.visit_series(site["id"], days)}}


@app.post("/scan")
async def op_scan(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    return {"ok": True, "data": scheduler.run_scan(site["id"], (body or {}).get("checks"),
                                                   trigger="api")}


@app.post("/publishSite")
async def op_publish_site(request: Request):
    """Serve this site from the office at its public path (or put it back on its container)."""
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    want = (body or {}).get("mode") or "office"
    if want not in ("office", "container"):
        return _err("mode חייב להיות office או container", 400)
    entries = (body or {}).get("entries")
    cur = dict(site.get("public") or {})
    cur["mode"] = want
    if entries is not None:
        cleaned, err = public.clean_entries(entries, site.get("hosts") or [])
        if err:
            return _err(err, 400)
        cur["entries"] = cleaned
    saved = store.upsert_site({**site, "public": cur})
    store.event(saved["id"], "public", f"מצב ההגשה: {want}", {"by": "api"})
    threading.Thread(target=_converge_public_bg, args=(saved, site), daemon=True,
                     name=f"sites-public-{saved['id']}").start()
    return {"ok": True, "data": {"started": True, "mode": want}, "site": site_view(saved)}


@app.post("/slots")
async def op_slots(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    return {"ok": True, "data": public.slots_scan(site)}


@app.post("/applySlots")
async def op_apply_slots(request: Request):
    body = (await request.json()) if await request.body() else {}
    site, bad = _op_site(body or {})
    if bad:
        return bad
    bundle = (body or {}).get("bundle") or {}
    if not isinstance(bundle, dict) or not bundle.get("slots"):
        return _err("לא התקבלו משבצות (bundle.slots) לעדכון", 400)
    return {"ok": True, "data": public.slots_apply(site, bundle,
                                                   (body or {}).get("actor") or "",
                                                   (body or {}).get("client") or "")}


OPS = {
    "listSites": op_list_sites, "getSite": op_get_site, "createSite": op_create_site,
    "deleteSite": op_delete_site, "startSite": op_start_site, "stopSite": op_stop_site,
    "checkSite": op_check_site, "uptime": op_uptime, "visits": op_visits, "scan": op_scan,
    "publishSite": op_publish_site, "slots": op_slots, "applySlots": op_apply_slots,
}


class _FakeRequest:
    """The op surface and the REST surface share one implementation. A `Request` is only a body
    here, and re-implementing creation for the second door is how two doors start to disagree."""

    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body

    async def body(self):
        return b"x" if self._body else b""


# ── the UI ───────────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    """Relative URLs only: the console embeds this at /a/sites/ and injects `<base href>`."""
    return FileResponse(_STATIC / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
def _startup() -> None:
    store.init()
    log.info("sites up — %s sites, machines via %s", len(store.list_sites()), machines.COMPUTERS_URL)
    scheduler.start()
