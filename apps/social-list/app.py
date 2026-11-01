"""social-list — every social network the business is on, behind ONE abstract API (`social.v1`).

The model
---------
    platform  ──►  accounts on it (vault instances)  ──►  profile · posts · comments · reactions

A **platform** is an entry in platforms.yaml (Facebook, Instagram, X, YouTube, GitHub, Discord,
WhatsApp, and the office's own test network). An **account** is a connection instance in the
credential plane whose PROTOCOL says both the platform and the implementation kind — the platform's
`api`, or the office `browser` driving the owner's logged-in session through portal scripts — the
office browser is the default door for every network. The caller (digital-assets, n8n, the office agent, this screen) never learns which: it calls
`updateProfile` / `createPost` and the account's protocol picks the adapter.

Three rules the layout encodes
------------------------------
1. **Every write is a JOB** (webengine): it returns at once with an id, reports progress, is
   idempotent per `client` token, and ends in a state that says what happened — `ok` only when the
   effect was READ BACK from the platform.
2. **A refusal names the missing piece**: the op the platform does not have, the login the browser
   lacks, the watched first run a draft script needs. Never a button that fails later.
3. **Nothing that needs a human is ever retried by a machine** — a login, a 2FA prompt, a challenge
   stops the run and names the live view where the owner does it once.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import accounts
import activity
import browser_session
import fixture
import platforms
import webengine
from adapters import adapter_for
from adapters import browser as browser_adapter
from adapters.base import PROFILE_FIELDS, SocialError, post_op

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("social-list")

SERVICE = "social-list"
_STATIC = Path(__file__).parent / "static"
OPS = ["listAccounts", "getProfile", "updateProfile", "listPosts", "createPost", "updatePost",
       "deletePost", "listComments", "createComment", "deleteComment", "react", "insights",
       "capabilities"]
DEFAULT_WAIT = float(os.environ.get("SOCIAL_OP_WAIT", "25"))

app = FastAPI(title=SERVICE, docs_url=None, redoc_url=None, openapi_url=None)


# ── plumbing ─────────────────────────────────────────────────────────────────────────────────────
def _err(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def _social_err(e: SocialError) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status if 400 <= e.status < 600 else 502)


async def _json_body(request: Request) -> dict:
    """The body as a dict, never an exception. Parsed on the loop; the blocking work then runs in the
    threadpool (a browser flow on the event loop would freeze the health check with it)."""
    try:
        raw = await request.body()
        if not raw:
            return {}
        body = json.loads(raw)
        return body if isinstance(body, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _actor(request: Request, body: dict | None = None) -> str:
    return ((body or {}).get("actor") or request.headers.get("x-actor")
            or request.headers.get("x-authentik-username") or "owner")


def _guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except SocialError as e:
        return _social_err(e)
    except accounts.VaultError as e:
        return _err(str(e), 502, kind="vault")


# ── health and the platform-service contract ─────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": SERVICE}


@app.get("/readyz")
def readyz():
    try:
        platforms.data()
        accounts.vault_list()
        return {"ready": True}
    except platforms.CatalogError as e:
        return JSONResponse({"ready": False, "reason": str(e)}, status_code=503)
    except accounts.VaultError as e:
        return JSONResponse({"ready": False, "reason": str(e)}, status_code=503)


@app.get("/manifest")
def manifest():
    return {"service": SERVICE, "protocols": platforms.all_protocols(), "ops": OPS,
            "capabilities": {p["id"]: {op: (p.get("ops") or {}).get(op) for op in platforms.ops_vocabulary()}
                             for p in platforms.platforms()}}


@app.get("/ops")
def ops_list():
    return {"ops": OPS, "interface": "social.v1"}


@app.get("/providers")
def providers():
    return platforms.catalog()


@app.get("/connections")
def connections():
    try:
        rows = [accounts.row(i) for i in accounts.vault_list()]
    except accounts.VaultError as e:
        return _err(str(e), 502, kind="vault")
    return {"active": None, "primary": accounts.primaries(), "connections": rows}


# ── the screen's reads ───────────────────────────────────────────────────────────────────────────
def _overview() -> dict:
    vault_error = None
    try:
        insts = accounts.vault_list()
    except accounts.VaultError as e:
        insts, vault_error = [], str(e)
    rows = [accounts.row(i) for i in insts]
    out = []
    for p in platforms.catalog()["platforms"]:
        mine = [r for r in rows if r["platform"] == p["id"]]
        out.append({"id": p["id"], "name": p.get("name"), "color": p.get("color"),
                    "monogram": p.get("monogram"), "test": bool(p.get("test")), "tos": p.get("tos"),
                    "kinds": p.get("kinds"), "accounts": mine,
                    "script": browser_adapter.describe(p["id"])})
    return {"platforms": out, "vault_error": vault_error,
            "browser": browser_session.available(), "ops": platforms.ops_vocabulary()}


@app.get("/api/overview")
async def api_overview():
    return await run_in_threadpool(_overview)


@app.get("/api/catalog")
def api_catalog():
    cat = platforms.catalog()
    for p in cat["platforms"]:
        p["script"] = browser_adapter.describe(p["id"])
    return cat


@app.get("/api/browser")
async def api_browser(force: int = 0):
    return await run_in_threadpool(browser_session.available, bool(force))


@app.get("/api/accounts")
async def api_accounts():
    def work():
        return {"accounts": [accounts.row(i) for i in accounts.vault_list()],
                "primary": accounts.primaries()}
    return await run_in_threadpool(_guard, work)


@app.get("/api/accounts/{aid}")
async def api_account(aid: str, probe: int = 0):
    def work():
        inst = next((i for i in accounts.vault_list() if i.get("id") == aid), None)
        if not inst:
            return _err("לא נמצא חשבון כזה", 404)
        return accounts.row(inst, with_probe=bool(probe))
    return await run_in_threadpool(_guard, work)


@app.post("/api/accounts/{aid}/probe")
async def api_account_probe(aid: str):
    def work():
        accounts.forget_probe(aid)
        inst = next((i for i in accounts.vault_list() if i.get("id") == aid), None)
        if not inst:
            return _err("לא נמצא חשבון כזה", 404)
        webengine.invalidate(f"profile:{aid}")
        return accounts.row(inst, with_probe=True)
    return await run_in_threadpool(_guard, work)


@app.post("/api/accounts/{aid}/primary")
async def api_account_primary(aid: str):
    def work():
        inst = next((i for i in accounts.vault_list() if i.get("id") == aid), None)
        if not inst:
            return _err("לא נמצא חשבון כזה", 404)
        platform, _ = platforms.by_protocol(inst.get("protocol") or "")
        return {"ok": True, "primary": accounts.set_primary(platform["id"], aid)}
    return await run_in_threadpool(_guard, work)


# ── connecting an account ────────────────────────────────────────────────────────────────────────
def _connect_api(body: dict) -> JSONResponse | dict:
    pid, label = body.get("platform") or "", (body.get("label") or "").strip()
    platform = platforms.get(pid)
    if not platform:
        return _err("פלטפורמה לא מוכרת", 400)
    spec = (platform.get("kinds") or {}).get("api")
    if not spec:
        return _err("לפלטפורמה הזו אין חיבור API", 400)
    secret = {k: (v.strip() if isinstance(v, str) else v)
              for k, v in (body.get("secret") or {}).items() if v not in (None, "")}
    missing = [k for k in spec.get("needs") or [] if not secret.get(k)]
    if missing:
        return _err("חסרים פרטים לחיבור: " + ", ".join(missing), 400, missing=missing)
    # a connection is never ADDED, it is VERIFIED: read who we are before storing anything
    try:
        who = adapter_for(platform, "api", secret, {}).whoami()
    except SocialError as e:
        return JSONResponse({**e.body(), "step": "verify_failed"}, status_code=400)
    secret.setdefault("handle", who.get("handle"))
    name = (platform.get("name") or {}).get("he", pid)
    created, code = accounts.vault_add(spec["protocol"], label or f"{name} · {who.get('handle') or who.get('name') or ''}".strip(" ·"),
                                       secret, who.get("handle") or who.get("name") or "")
    if code >= 400:
        return _err(created.get("error") or "שמירת החשבון בוולט נכשלה", code)
    if not accounts.primaries().get(pid):
        accounts.set_primary(pid, created.get("id"))
    return {"step": "connected", "id": created.get("id"), "who": who}


def _connect_browser(body: dict) -> JSONResponse | dict:
    """One call, three answers (the domains app's browser flow): needs_human_login → the owner logs
    in once in the live view and the screen calls again; connected → the account's own profile was
    READ as proof; anything else → named, never reported as a login failure."""
    pid = body.get("platform") or ""
    platform = platforms.get(pid)
    if not platform:
        return _err("פלטפורמה לא מוכרת", 400)
    spec = (platform.get("kinds") or {}).get("browser")
    if not spec:
        return _err("לפלטפורמה הזו אין חיבור דרך הדפדפן", 400)
    avail = browser_session.available(force=True)
    if not avail.get("available"):
        return JSONResponse({"step": "browser_unavailable", "error": avail.get("reason"),
                             "how": avail.get("how")}, status_code=409)
    # where the account lives when the page cannot say it by itself (Discord: which server and
    # which channel) — asked by the catalogue's `needs`, stored with the pointer, never a secret
    given = {k: str(v).strip() for k, v in (body.get("secret") or {}).items() if v not in (None, "")}
    missing = [k for k in spec.get("needs") or [] if not given.get(k)]
    if missing:
        return _err("חסרים פרטים לחיבור: " + ", ".join(missing), 400, missing=missing)
    pointer = {"endpoint": browser_session.DEFAULT_ENDPOINT, "token_connection": "browser42-mcp-token",
               "origin": platforms.origin_of(platform), "group": f"social-{pid}",
               "handle": (body.get("handle") or given.pop("handle", "") or "").strip() or None,
               **{k: v for k, v in given.items() if k in (spec.get("needs") or [])}}
    try:
        prof = adapter_for(platform, "browser", pointer, {}).get_profile()
    except SocialError as e:
        if e.kind == "needs_owner":
            return JSONResponse({"step": "needs_human_login", "live_view": browser_adapter.LIVE_VIEW,
                                 "url": platforms.origin_of(platform), **e.body()}, status_code=200)
        return JSONResponse({"step": "error", **e.body()}, status_code=409)
    pointer["handle"] = pointer["handle"] or prof.get("handle")
    name = (platform.get("name") or {}).get("he", pid)
    label = (body.get("label") or "").strip() or f"{name} · {prof.get('name') or prof.get('handle') or ''}".strip(" ·")
    created, code = accounts.vault_add(spec["protocol"], label, pointer,
                                       prof.get("handle") or prof.get("name") or "")
    if code >= 400:
        return _err(created.get("error") or "שמירת החשבון בוולט נכשלה", code)
    if not accounts.primaries().get(pid):
        accounts.set_primary(pid, created.get("id"))
    return {"step": "connected", "id": created.get("id"),
            "evidence": {"name": prof.get("name"), "handle": prof.get("handle")}}


@app.post("/api/accounts")
async def api_accounts_add(request: Request):
    body = await _json_body(request)
    if (body.get("kind") or "browser") == "browser":
        return await run_in_threadpool(_guard, _connect_browser, body)
    return await run_in_threadpool(_guard, _connect_api, body)


@app.post("/api/accounts/browser")
async def api_accounts_browser(request: Request):
    return await run_in_threadpool(_guard, _connect_browser, await _json_body(request))


@app.delete("/api/accounts/{aid}")
async def api_accounts_delete(aid: str, confirm: str = ""):
    def work():
        inst = next((i for i in accounts.vault_list() if i.get("id") == aid), None)
        if not inst:
            return _err("לא נמצא חשבון כזה", 404)
        if confirm != aid:
            return _err("ניתוק חשבון דורש אישור מפורש", 400, confirm_required=aid)
        out, code = accounts.vault_delete(aid)
        if code >= 400:
            return _err(out.get("error") or "הניתוק נכשל", code)
        platform, _ = platforms.by_protocol(inst.get("protocol") or "")
        if accounts.primaries().get(platform["id"]) == aid:
            accounts.set_primary(platform["id"], None)
        accounts.forget_probe(aid)
        webengine.invalidate(f"profile:{aid}")
        webengine.invalidate(f"posts:{aid}")
        return {"ok": True}
    return await run_in_threadpool(_guard, work)


# ── reads through the adapter, cached (stale-while-revalidate) ───────────────────────────────────
def _read(kind: str, aid: str, fresh: bool, loader_name: str, *args):
    """A cached read. The engine keeps a failed read as `state=error` with the LAST GOOD value (a
    failed read is never stored as an empty profile); the refusal itself — its why and how — is
    caught on the way through, so the screen can say what to do rather than print a class name."""
    caught: dict = {}

    def loader():
        try:
            a, _inst = accounts.adapter(aid)
            return getattr(a, loader_name)(*args)
        except SocialError as e:
            caught["e"] = e
            raise
    key = f"{kind}:{aid}"
    ttl = 600 if kind == "profile" else 300
    out = webengine.get(key, loader, ttl=ttl, force=fresh, want="fresh" if fresh else "cache")
    if caught.get("e") is not None and out.get("value") is None:
        return _social_err(caught["e"])
    resp = {k: out.get(k) for k in ("value", "age", "stale", "state", "refreshing")}
    if caught.get("e") is not None:
        resp["error_body"] = caught["e"].body()
    elif out.get("state") == "error":
        resp["error_body"] = {"error": "הקריאה האחרונה נכשלה — מוצג הערך הקודם",
                              "detail": out.get("error")}
    return resp


@app.get("/api/accounts/{aid}/profile")
async def api_profile(aid: str, fresh: int = 0):
    return await run_in_threadpool(_guard, _read, "profile", aid, bool(fresh), "get_profile")


@app.get("/api/accounts/{aid}/posts")
async def api_posts(aid: str, fresh: int = 0, limit: int = 10):
    return await run_in_threadpool(_guard, _read, "posts", aid, bool(fresh), "list_posts", limit)


@app.get("/api/accounts/{aid}/posts/{pid}/comments")
async def api_comments(aid: str, pid: str):
    def work():
        a, _ = accounts.adapter(aid)
        return {"comments": a.list_comments(pid)}
    return await run_in_threadpool(_guard, work)


@app.get("/api/accounts/{aid}/activity")
async def api_account_activity(aid: str, limit: int = 50):
    return await run_in_threadpool(lambda: {"actions": activity.recent(aid, limit)})


@app.get("/api/activity")
async def api_activity(limit: int = 50):
    return await run_in_threadpool(lambda: {"actions": activity.recent(None, limit)})


@app.get("/api/activity/{action_id}")
async def api_activity_one(action_id: str):
    d = await run_in_threadpool(activity.get, action_id)
    return d or _err("לא נמצא", 404)


# ── writes: every one is a job ───────────────────────────────────────────────────────────────────
WRITE_TITLES = {"update_profile": "עדכון פרופיל", "create_post": "פרסום פוסט",
                "update_post": "עריכת פוסט", "delete_post": "מחיקת פוסט",
                "create_comment": "כתיבת תגובה", "delete_comment": "מחיקת תגובה",
                "react": "לייק"}


def _op_for(method: str, args: list) -> str:
    if method == "update_profile":
        fields = list((args[0] or {}).keys())
        return PROFILE_FIELDS.get(fields[0], "profile.update.name") if len(fields) == 1 else "profile.update"
    if method == "create_post":
        return post_op(args[0] or {})
    return {"update_post": "post.update", "delete_post": "post.delete",
            "create_comment": "comment.create", "delete_comment": "comment.delete",
            "react": "reaction.create"}.get(method, method)


def _submit_write(aid: str, method: str, args: list, *, actor: str, watch: bool = False,
                  client: str | None = None, summary: str = "") -> dict:
    """Queue one write. The job resolves the account AT RUN TIME (a token rotated between the click
    and the run is the new token), records the action, and invalidates what it changed."""
    inst = next((i for i in accounts.vault_list() if i.get("id") == aid), None)
    if inst is None:
        # a platform id means "that platform's primary account"
        inst, _secret, _p, _k = accounts.resolve(aid)
        aid = inst["id"]
    platform, kind = platforms.by_protocol(inst.get("protocol") or "")
    title = f"{WRITE_TITLES.get(method, method)} · {(platform.get('name') or {}).get('he', '')}"
    op = _op_for(method, args)

    def run(progress, params):
        progress(10, "מתחבר לחשבון")
        a, inst2 = accounts.adapter(aid, watch=watch)
        progress(30, "מבצע" if kind == "api" else "הדפדפן של הלשכה פועל")
        try:
            result = getattr(a, method)(*args)
        except SocialError as e:
            activity.record(inst2, platform["id"], kind, op, _params_of(method, args), "error",
                            {**e.body(), "trace": getattr(a, "trace", [])}, actor, summary)
            raise
        progress(90, "מאמת")
        activity.record(inst2, platform["id"], kind, op, _params_of(method, args),
                        result.get("state") or "ok", result, actor, summary)
        if result.get("state") not in (None, "ok"):
            raise SocialError("הפעולה רצה אבל התוצאה לא אומתה בקריאה חוזרת", status=409,
                              kind="assert_failed", state=result.get("state"),
                              detail=json.dumps(result.get("verify"), ensure_ascii=False)[:600])
        return result

    return webengine.submit(f"{method}:{aid}", run, {"aid": aid, "op": op}, title=title,
                            invalidates=[f"profile:{aid}", f"posts:{aid}"], client=client)


def _params_of(method: str, args: list) -> dict:
    if method == "update_profile":
        return dict(args[0] or {})
    if method == "create_post":
        return dict(args[0] or {})
    if method in ("update_post",):
        return {"post_id": args[0], **(args[1] or {})}
    return {"args": [a for a in args if not isinstance(a, (bytes, bytearray))]}


def _wait(job: dict, seconds: float) -> dict:
    end = time.time() + max(0.0, seconds)
    j = job
    while time.time() < end and (j or {}).get("state") in ("queued", "running"):
        time.sleep(0.4)
        j = webengine.job(job["id"]) or j
    return j


def _job_response(job: dict) -> JSONResponse:
    state = job.get("state")
    if state == "ok":
        return JSONResponse({"state": "ok", "job": job, "result": job.get("result")})
    if state == "error":
        body = ((job.get("result") or {}).get("error_body") or {"error": job.get("error")})
        return JSONResponse({"state": "error", "job": job, **body}, status_code=409)
    return JSONResponse({"state": state, "job": job}, status_code=202)


@app.patch("/api/accounts/{aid}/profile")
async def api_profile_update(aid: str, request: Request):
    body = await _json_body(request)
    changes = {k: v for k, v in (body.get("changes") or {}).items() if k in PROFILE_FIELDS}
    if not changes:
        return _err("לא נמסרו שדות לעדכון", 400)

    def work():
        job = _submit_write(aid, "update_profile", [changes], actor=_actor(request, body),
                            watch=bool(body.get("watch")), client=body.get("client"),
                            summary=body.get("summary") or "")
        return _job_response(_wait(job, float(body.get("wait", 0))))
    return await run_in_threadpool(_guard, work)


@app.post("/api/accounts/{aid}/posts")
async def api_post_create(aid: str, request: Request):
    body = await _json_body(request)
    post = body.get("post") or {k: body.get(k) for k in ("text", "media", "link") if body.get(k)}
    if not (post.get("text") or post.get("media")):
        return _err("פוסט ריק — חסר טקסט או מדיה", 400)

    def work():
        job = _submit_write(aid, "create_post", [post], actor=_actor(request, body),
                            watch=bool(body.get("watch")), client=body.get("client"),
                            summary=body.get("summary") or "")
        return _job_response(_wait(job, float(body.get("wait", 0))))
    return await run_in_threadpool(_guard, work)


@app.patch("/api/accounts/{aid}/posts/{pid}")
async def api_post_update(aid: str, pid: str, request: Request):
    body = await _json_body(request)

    def work():
        job = _submit_write(aid, "update_post", [pid, {"text": body.get("text") or ""}],
                            actor=_actor(request, body), watch=bool(body.get("watch")),
                            client=body.get("client"))
        return _job_response(_wait(job, float(body.get("wait", 0))))
    return await run_in_threadpool(_guard, work)


@app.delete("/api/accounts/{aid}/posts/{pid}")
async def api_post_delete(aid: str, pid: str, request: Request):
    body = await _json_body(request)
    confirm = body.get("confirm") or request.query_params.get("confirm") or ""
    if confirm != pid:
        return _err("מחיקת פוסט דורשת אישור מפורש (confirm = מזהה הפוסט)", 400, confirm_required=pid)

    def work():
        job = _submit_write(aid, "delete_post", [pid], actor=_actor(request, body),
                            watch=bool(body.get("watch")), client=body.get("client"))
        return _job_response(_wait(job, float(body.get("wait", 0))))
    return await run_in_threadpool(_guard, work)


@app.post("/api/accounts/{aid}/posts/{pid}/comments")
async def api_comment_create(aid: str, pid: str, request: Request):
    body = await _json_body(request)
    if not (body.get("text") or "").strip():
        return _err("תגובה ריקה", 400)

    def work():
        job = _submit_write(aid, "create_comment", [pid, body["text"], body.get("reply_to")],
                            actor=_actor(request, body), client=body.get("client"))
        return _job_response(_wait(job, float(body.get("wait", 0))))
    return await run_in_threadpool(_guard, work)


@app.get("/public/{name}")
def public_media(name: str):
    """The one route outside SSO (routing auth_exclude): an expiring, unguessable copy of an image
    that a platform downloads itself (Instagram's publishing API). Nothing else is ever served here."""
    import media as media_mod
    p = media_mod.public_file(name)
    if not p:
        return _err("not found", 404)
    return FileResponse(str(p))


# ── jobs and the change feed ─────────────────────────────────────────────────────────────────────
@app.get("/api/jobs")
def api_jobs(active: int = 0, limit: int = 25):
    return {"jobs": webengine.jobs(limit=limit, active_only=bool(active))}


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    return webengine.job(jid) or _err("לא נמצאה עבודה כזו", 404)


@app.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    return webengine.cancel(jid) or _err("לא נמצאה עבודה כזו", 404)


@app.get("/api/events")
def api_events():
    q = webengine.subscribe()

    def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            webengine.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── canonical ops (platform-service.v1): POST /<op> {account, …} ─────────────────────────────────
def _op(name: str, body: dict, actor: str):
    ref = body.get("account") or body.get("account_id") or body.get("platform") or ""
    wait = float(body.get("wait", DEFAULT_WAIT))
    if name == "listAccounts":
        rows = [accounts.row(i) for i in accounts.vault_list()]
        pid = body.get("platform")
        return {"accounts": [r for r in rows if not pid or r["platform"] == pid]}
    if name == "capabilities":
        if platforms.get(ref):
            p = platforms.get(ref)
            return {"platform": ref, "ops": p.get("ops"), "kinds": list((p.get("kinds") or {}).keys())}
        inst, _s, p, kind = accounts.resolve(ref)
        ops = {op: platforms.support(p["id"], op, kind) for op in platforms.ops_vocabulary()}
        script = browser_adapter.describe(p["id"]) if kind == "browser" else None
        if script is not None:
            # through the office browser an op exists when its SCRIPT does: without one the plan
            # skips it with this reason instead of pushing a run that can only refuse
            for op, sup in ops.items():
                if sup["answer"] != "no" and op not in script["ops"]:
                    ops[op] = {"answer": "no", "why": "עוד אין תסריט דפדפן לפעולה הזו"}
        return {"account": inst["id"], "platform": p["id"], "kind": kind, "ops": ops, "script": script}
    if not ref:
        raise SocialError("חסר account (מזהה חשבון או מזהה פלטפורמה)", status=400, kind="bad_request")
    if name == "getProfile":
        return _read("profile", accounts.resolve(ref)[0]["id"], bool(body.get("fresh")), "get_profile")
    if name == "listPosts":
        return _read("posts", accounts.resolve(ref)[0]["id"], bool(body.get("fresh")), "list_posts",
                     int(body.get("limit") or 10))
    if name == "listComments":
        a, _ = accounts.adapter(ref)
        return {"comments": a.list_comments(body.get("post_id") or "")}
    if name == "insights":
        a, _ = accounts.adapter(ref)
        return a.insights()
    writes = {
        "updateProfile": ("update_profile", lambda b: [{k: v for k, v in (b.get("changes") or {}).items()
                                                         if k in PROFILE_FIELDS}]),
        "createPost": ("create_post", lambda b: [b.get("post") or {}]),
        "updatePost": ("update_post", lambda b: [b.get("post_id"), {"text": b.get("text") or ""}]),
        "deletePost": ("delete_post", lambda b: [b.get("post_id")]),
        "createComment": ("create_comment", lambda b: [b.get("post_id"), b.get("text") or "",
                                                       b.get("reply_to")]),
        "deleteComment": ("delete_comment", lambda b: [b.get("comment_id")]),
        "react": ("react", lambda b: [b.get("target_id") or b.get("post_id"), b.get("reaction") or "like"]),
    }
    if name not in writes:
        raise SocialError(f"פעולה לא מוכרת: {name}", status=404, kind="unknown_op")
    method, make = writes[name]
    args = make(body)
    if name == "deletePost" and body.get("confirm") != body.get("post_id"):
        raise SocialError("מחיקת פוסט דורשת confirm = post_id", status=400, kind="confirm_required")
    job = _submit_write(ref, method, args, actor=actor, watch=bool(body.get("watch")),
                        client=body.get("client"), summary=body.get("summary") or "")
    return _job_response(_wait(job, wait))


@app.post("/{op}")
async def canonical_op(op: str, request: Request):
    if op not in OPS:
        return _err("פעולה לא מוכרת", 404, ops=OPS)
    body = await _json_body(request)
    return await run_in_threadpool(_guard, _op, op, body, _actor(request, body))


# ── self-test: the whole chain against the test network, through each kind ───────────────────────
def _selftest(kind: str) -> dict:
    platform = platforms.get("fixture")
    stamp = time.strftime("%H%M%S")
    steps = []
    pointer = {"handle": "example.biz"}
    a = adapter_for(platform, kind, pointer, {"id": f"selftest-{kind}"})

    def step(name, fn):
        t0 = time.time()
        try:
            res = fn()
            steps.append({"step": name, "ok": True, "ms": int((time.time() - t0) * 1000),
                          "result": res})
            return res
        except SocialError as e:
            steps.append({"step": name, "ok": False, "ms": int((time.time() - t0) * 1000),
                          "error": e.body()})
            raise
    try:
        step("profile.get", a.get_profile)
        step("profile.update.bio", lambda: a.update_profile({"bio": f"בדיקה עצמית {stamp}"}))
        step("post.create.text", lambda: a.create_post({"text": f"פוסט בדיקה {stamp} — social-list"}))
        posts = step("post.list", lambda: a.list_posts(5))
        mine = next((p for p in posts if stamp in (p.get("text") or "")), None)
        if mine:
            step("post.delete", lambda: a.delete_post(mine["id"]))
        ok = all(s["ok"] for s in steps)
    except SocialError:
        ok = False
    return {"ok": ok, "kind": kind, "steps": steps}


@app.post("/api/selftest")
async def api_selftest(request: Request):
    body = await _json_body(request)
    kind = body.get("kind") or "api"
    if kind not in ("api", "browser"):
        return _err("kind חייב להיות api או browser", 400)
    return await run_in_threadpool(_selftest, kind)


# ── the test network (fixture.py) ────────────────────────────────────────────────────────────────
# Routed OUTSIDE SSO (app.json auth_exclude) so the office browser can reach it through the edge —
# and therefore answered only to clients on a private network: the office browser, the other
# containers, the owner's own machine. A request from the internet gets a 404, as if it were not here.
import ipaddress


@app.middleware("http")
async def _fixture_private_only(request: Request, call_next):
    if request.url.path.startswith("/fixture"):
        hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        client = hops[0] if hops else (request.client.host if request.client else "")
        try:
            ok = ipaddress.ip_address(client).is_private or ipaddress.ip_address(client).is_loopback
        except ValueError:
            ok = False
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
    return await call_next(request)


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.get("/fixture")
@app.get("/fixture/")
def fixture_home():
    return FileResponse(_STATIC / "fixture" / "index.html")


@app.get("/fixture/settings")
def fixture_settings():
    return FileResponse(_STATIC / "fixture" / "settings.html")


@app.get("/fixture/files/{fid}")
def fixture_file(fid: str):
    got = fixture.file(fid)
    if not got:
        return _err("not found", 404)
    data, mime = got
    return Response(data, media_type=mime, headers={"Cache-Control": "max-age=3600"})


@app.get("/fixture/api/profile")
def fixture_profile(request: Request):
    return fixture.profile(_base(request))


@app.patch("/fixture/api/profile")
async def fixture_profile_patch(request: Request):
    body = await _json_body(request)
    fixture.update_profile(body)
    return fixture.profile(_base(request))


@app.get("/fixture/api/posts")
def fixture_posts(request: Request, limit: int = 20):
    return {"posts": fixture.posts(_base(request), limit)}


@app.post("/fixture/api/posts")
async def fixture_post_create(request: Request):
    body = await _json_body(request)
    return fixture.create_post(body.get("text") or "", body.get("media") or [])


@app.patch("/fixture/api/posts/{pid}")
async def fixture_post_update(pid: str, request: Request):
    body = await _json_body(request)
    return fixture.update_post(pid, body.get("text") or "") or _err("not found", 404)


@app.delete("/fixture/api/posts/{pid}")
def fixture_post_delete(pid: str):
    return {"ok": fixture.delete_post(pid)}


@app.get("/fixture/api/posts/{pid}/comments")
def fixture_comments(pid: str):
    c = fixture.comments(pid)
    return {"comments": c} if c is not None else _err("not found", 404)


@app.post("/fixture/api/posts/{pid}/comments")
async def fixture_comment_add(pid: str, request: Request):
    body = await _json_body(request)
    return fixture.add_comment(pid, body.get("text") or "", body.get("reply_to")) or _err("not found", 404)


@app.delete("/fixture/api/comments/{cid}")
def fixture_comment_delete(cid: str):
    return {"ok": fixture.delete_comment(cid)}


@app.post("/fixture/api/posts/{pid}/like")
def fixture_like(pid: str):
    return fixture.like(pid) or _err("not found", 404)


@app.get("/fixture/api/insights")
def fixture_insights():
    return fixture.insights()


@app.post("/fixture/api/reset")
def fixture_reset():
    fixture.reset()
    return {"ok": True}


# ── the screen ───────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


# ── screen routes ────────────────────────────────────────────────────────────────────────────────
# The console hands an embedded app its inner route as a PATH (#/m/<alias>/matrix loads
# /a/<alias>/matrix): every screen path answers with the page itself, whose script turns the path
# back into its hash route. Standalone (no console prefix) the same address redirects to that form.
_NOT_SCREENS = ("api/", "static/", "files/", "fixture", "public/")


@app.get("/{path:path}", include_in_schema=False)
def screen_route(path: str, request: Request):
    if path.startswith(_NOT_SCREENS) or "." in path.rsplit("/", 1)[-1]:
        return _err("not found", 404)
    if request.headers.get("x-forwarded-prefix"):
        return FileResponse(_STATIC / "index.html")
    q = request.url.query
    return RedirectResponse("/#/" + path + (f"?{q}" if q else ""), status_code=302)


@app.on_event("startup")
def _startup() -> None:
    webengine.init()
    webengine.start_workers(int(os.environ.get("SOCIAL_WORKERS", "2")))
    try:
        platforms.data()
    except platforms.CatalogError as e:
        log.error("%s", e)
