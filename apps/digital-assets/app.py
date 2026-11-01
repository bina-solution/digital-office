"""digital-assets (נכסים דיגיטליים) — the business's whole digital front, organised as slots.

What it is FOR, in the owner's words: add a logo, make it the active one, and it changes on every
account, on the website and in the office's own products. Change the name, the slug, the
description — same. Media the office agent makes lands in the right gallery, and is posted by one
click or by the agent. Every text and picture on the website is a slot, editable here.

The model (store.py): slots → assets (versions) → the active one → publications (per channel).
Blueprints (blueprints/*.yaml) create the slots; propagate.py plans and publishes a change; the
doors to the outside are other apps' capabilities — `social` (social-list) and `sites` — so this app
holds no credential and speaks to no platform itself.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import blueprints
import clients
import files
import posting
import propagate
import store
import webengine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("digital-assets")

SERVICE = "digital-assets"
_STATIC = Path(__file__).parent / "static"
OPS = ["listSlots", "getSlot", "addAsset", "setActive", "plan", "publish", "listMedia", "addMedia",
       "createPost", "getBrand", "getBundle", "listBlueprints", "applyBlueprint", "listChannels",
       "bindChannel"]
TEXT_KINDS = {"text", "richtext", "link", "handle", "list", "price-list", "hours", "address",
              "phone", "email", "color", "palette"}
INBOX = "media.inbox"

app = FastAPI(title=SERVICE, docs_url=None, redoc_url=None, openapi_url=None)


def _err(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


async def _json_body(request: Request) -> dict:
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


def _label(s: dict | None) -> str:
    return ((s or {}).get("label") or {}).get("he") or (s or {}).get("key") or ""


# ── health and the platform-service contract ─────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": SERVICE}


@app.get("/readyz")
def readyz():
    try:
        store.conn().execute("SELECT 1").fetchone()
        return {"ready": True}
    except Exception as e:                                    # noqa: BLE001
        return JSONResponse({"ready": False, "reason": str(e)}, status_code=503)


@app.get("/manifest")
def manifest():
    return {"service": SERVICE, "ops": OPS, "protocols": [],
            "capabilities": {"digital-assets": "digital-assets.v1", "brand": "brand.v1"}}


@app.get("/ops")
def ops():
    return {"ops": OPS, "interface": "digital-assets.v1"}


# ── views of the whole ───────────────────────────────────────────────────────────────────────────
def _slot_view(s: dict, actives: dict, counts: dict) -> dict:
    a = actives.get(s["key"])
    asset = store.get_asset(a["asset_id"]) if a else None
    return {"key": s["key"], "section": s["section"], "grp": s.get("grp"), "label": s.get("label"),
            "kind": s["kind"], "lang": s.get("lang"), "required": bool(s.get("required")),
            "constraints": s.get("constraints"), "expires": s.get("expires"),
            "targets": s.get("targets"), "plan": s.get("plan"), "sources": s.get("sources"),
            "count": counts.get(s["key"], 0), "active": _asset_view(asset) if asset else None,
            "active_since": (a or {}).get("set_at")}


def _asset_view(a: dict | None) -> dict | None:
    if not a:
        return None
    out = {k: a.get(k) for k in ("id", "slot_key", "kind", "title", "text", "mime", "size", "width",
                                 "height", "source", "author", "status", "meta", "created_at")}
    if a.get("file_sha"):
        out["file"] = f"files/{a['file_sha']}.{a['file_ext']}"
        out["ext"] = a["file_ext"]
        out["thumb"] = out["file"] + ("" if a["file_ext"] == "svg" else "?px=480")
    return out


def _counts() -> dict:
    return {r["slot_key"]: r["n"] for r in store.conn().execute(
        "SELECT slot_key, COUNT(*) AS n FROM assets WHERE status != 'archived' GROUP BY slot_key")}


def _overview() -> dict:
    slots = store.list_slots()
    actives = store.active_map()
    counts = _counts()
    sections = {}
    for s in slots:
        sec = sections.setdefault(s["section"], {"slots": 0, "filled": 0, "required": 0,
                                                 "required_filled": 0})
        sec["slots"] += 1
        # a media unit is a SET: it is "filled" once it has items, not once one is active
        filled = s["key"] in actives or (s["section"] == "media" and counts.get(s["key"], 0) > 0)
        sec["filled"] += int(filled)
        if s.get("required"):
            sec["required"] += 1
            sec["required_filled"] += int(filled)
    chans = store.list_channels()
    social_err = None
    try:
        accts = {a["id"]: a for a in clients.social_accounts()}
    except clients.Unavailable as e:
        accts, social_err = {}, f"שירות הרשתות החברתיות אינו זמין ({e})"
    ch_view = []
    for c in chans:
        acc = accts.get(c.get("account_id") or "")
        ch_view.append({**c, "account": acc, "bound": bool(c.get("account_id") or c.get("site_id"))})
    upcoming = []
    for s in slots:
        p = s.get("plan") or {}
        if s["section"] == "media" and p.get("due") and counts.get(s["key"], 0) == 0:
            upcoming.append({"key": s["key"], "label": s.get("label"), "due": p["due"],
                             "phase": p.get("phase_name"), "channels": p.get("channels")})
    upcoming.sort(key=lambda x: x["due"])
    return {"sections": sections, "channels": ch_view, "social_error": social_err,
            "blueprints": [blueprints.summary(b) for b in blueprints.all_blueprints().values()],
            "pending": [_pub_view(p) for p in store.pending_publications(30)],
            "events": store.events(12), "upcoming": upcoming[:6],
            "raster": files.can_raster(), "settings": {"launch_date": _launch_date()}}


def _launch_date() -> str | None:
    return (store.applied().get("startup-tail", {}).get("params") or {}).get("launch_date")


@app.get("/api/overview")
async def api_overview():
    return await run_in_threadpool(_overview)


@app.get("/api/slots")
async def api_slots(section: str = "", q: str = ""):
    def work():
        actives = store.active_map()
        counts = _counts()
        out = [_slot_view(s, actives, counts) for s in store.list_slots(section or None)]
        if q:
            ql = q.strip().lower()
            out = [s for s in out if ql in s["key"].lower() or ql in _label(s).lower()]
        return {"slots": out}
    return await run_in_threadpool(work)


def _slot_detail(key: str) -> dict | JSONResponse:
    s = store.get_slot(key)
    if not s:
        return _err("לא נמצאה משבצת כזו", 404)
    actives = store.active_map()
    view = _slot_view(s, actives, _counts())
    view["brief"] = s.get("brief")
    view["assets"] = [_asset_view(a) for a in store.list_assets(key)]
    view["publications"] = [_pub_view(p) for p in store.latest_publications(key)]
    view["posts"] = store.list_posts(20, key)
    view["events"] = store.events(15, key)
    return view


@app.get("/api/slots/{key}")
async def api_slot(key: str):
    return await run_in_threadpool(_slot_detail, key)


@app.post("/api/slots")
async def api_slot_create(request: Request):
    body = await _json_body(request)
    key = (body.get("key") or "").strip().lower()
    if not re.fullmatch(r"(identity|content|media)(\.[a-z0-9-]+)+", key):
        return _err("מפתח משבצת לא תקין — למשל content.website.hero-title", 400)
    if store.get_slot(key):
        return _err("משבצת כזו כבר קיימת", 409)
    kind = body.get("kind") or "text"
    if kind not in blueprints.KINDS:
        return _err("סוג לא מוכר", 400)
    s = store.upsert_slot({"key": key, "section": key.split(".")[0], "grp": key.split(".")[1],
                           "label": {"he": body.get("label") or key, "en": body.get("label_en") or key},
                           "kind": kind, "targets": body.get("targets") or [],
                           "constraints": body.get("constraints") or {}})
    store.event("slot", f"נוספה משבצת {_label(s)}", slot_key=key, actor=_actor(request, body))
    return s


@app.patch("/api/slots/{key}")
async def api_slot_patch(key: str, request: Request):
    body = await _json_body(request)
    s = store.patch_slot(key, body)
    return s or _err("לא נמצאה משבצת כזו", 404)


# ── assets ───────────────────────────────────────────────────────────────────────────────────────
def _ingest(slot_key: str, body: dict, actor: str, raw: bytes | None = None,
            filename: str = "", mime: str = "") -> dict:
    """One door for every way an asset arrives: a form upload, JSON with base64, an SVG string, a
    URL to fetch, or plain text. Returns the asset view (and activates it when asked)."""
    slot = store.get_slot(slot_key)
    if not slot:
        raise LookupError("לא נמצאה משבצת כזו")
    data = raw
    if data is None and body.get("data_base64"):
        data = base64.b64decode(body["data_base64"])
    if data is None and body.get("svg"):
        data = body["svg"].encode("utf-8")
        mime = mime or "image/svg+xml"
    if data is None and body.get("url"):
        import requests
        r = requests.get(body["url"], timeout=30)
        r.raise_for_status()
        data, mime = r.content, r.headers.get("content-type", "").split(";")[0]
        filename = filename or body["url"].rsplit("/", 1)[-1]
    source = body.get("source") or ("agent" if actor.startswith("agent") else "upload")
    meta = dict(body.get("meta") or {})
    if body.get("expires_at"):
        meta["expires_at"] = body["expires_at"]
    if body.get("spec"):
        meta["spec"] = body["spec"]
    if data is not None:
        info = files.put(data, filename or body.get("name") or "", mime or body.get("mime") or "")
        kind = body.get("kind") or (slot["kind"] if slot["kind"] not in ("set",) and slot["kind"] not in TEXT_KINDS else info["kind"])
        asset = store.add_asset(slot_key, kind, title=body.get("title") or filename or "",
                                file=info, source=source, author=body.get("author") or actor,
                                status=body.get("status") or "draft", meta=meta,
                                text=body.get("text"))
    else:
        text = body.get("text")
        if text is None or (isinstance(text, str) and not text.strip()):
            raise ValueError("לא נמסר תוכן — טקסט או קובץ")
        kind = body.get("kind") or (slot["kind"] if slot["kind"] != "set" else "text")
        asset = store.add_asset(slot_key, kind, title=body.get("title") or "", text=str(text),
                                source=source, author=body.get("author") or actor,
                                status=body.get("status") or "draft", meta=meta)
    store.event("asset", f"נוסף נכס ל„{_label(slot)}” ({asset['kind']})", slot_key=slot_key,
                actor=actor, data={"asset": asset["id"], "source": source})
    webengine.publish({"type": "asset", "slot": slot_key, "id": asset["id"]})
    out = {"asset": _asset_view(asset)}
    if body.get("activate"):
        out.update(_activate(asset["id"], actor, publish=bool(body.get("publish")),
                             watch=bool(body.get("watch"))))
    return out


def _activate(asset_id: str, actor: str, publish: bool = False, watch: bool = False) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise LookupError("לא נמצא נכס כזה")
    slot = store.get_slot(asset["slot_key"])
    store.set_active(asset["slot_key"], asset_id, actor)
    if asset.get("status") == "draft":
        store.patch_asset(asset_id, {"status": "approved"})
    store.event("active", f"„{_label(slot)}” — נבחרה גרסה פעילה", slot_key=asset["slot_key"],
                actor=actor, data={"asset": asset_id})
    webengine.publish({"type": "active", "slot": asset["slot_key"], "id": asset_id})
    out = {"active": asset_id, "plan": propagate.plan(asset["slot_key"], asset_id)}
    out["plan"]["asset"] = _asset_view(out["plan"].get("asset"))
    if publish:
        out["run"] = propagate.publish(asset["slot_key"], asset_id, actor=actor, watch=watch)
    return out


@app.post("/api/slots/{key}/assets")
async def api_asset_add(key: str, request: Request):
    ctype = request.headers.get("content-type", "")
    raw, filename, mime, body = None, "", "", {}
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        up = form.get("file")
        if up is not None and hasattr(up, "read"):
            raw = await up.read()
            filename, mime = up.filename or "", up.content_type or ""
        body = {k: v for k, v in form.items() if k != "file" and isinstance(v, str)}
        for flag in ("activate", "publish", "watch"):
            if flag in body:
                body[flag] = body[flag] in ("1", "true", "on", "yes")
    else:
        body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        try:
            return _ingest(key, body, actor, raw, filename, mime)
        except LookupError as e:
            return _err(str(e), 404)
        except (ValueError, files.FileError) as e:
            return _err(str(e), 400)
    return await run_in_threadpool(work)


@app.get("/api/assets/{aid}")
def api_asset(aid: str):
    return _asset_view(store.get_asset(aid)) or _err("לא נמצא נכס כזה", 404)


@app.patch("/api/assets/{aid}")
async def api_asset_patch(aid: str, request: Request):
    body = await _json_body(request)
    if "slot_key" in body and not store.get_slot(body["slot_key"]):
        return _err("משבצת היעד אינה קיימת", 400)
    a = store.patch_asset(aid, {k: v for k, v in body.items() if k in ("title", "status", "text", "meta", "slot_key")})
    return _asset_view(a) or _err("לא נמצא נכס כזה", 404)


@app.delete("/api/assets/{aid}")
async def api_asset_delete(aid: str, request: Request):
    a = store.get_asset(aid)
    if not a:
        return _err("לא נמצא נכס כזה", 404)
    if (store.active_of(a["slot_key"]) or {}).get("asset_id") == aid:
        return _err("זו הגרסה הפעילה — בחרו גרסה אחרת לפני מחיקה", 409)
    store.patch_asset(aid, {"status": "archived"})
    store.event("asset", "נכס הועבר לארכיון", slot_key=a["slot_key"], actor=_actor(request))
    return {"ok": True, "archived": aid}


@app.post("/api/assets/{aid}/activate")
async def api_activate(aid: str, request: Request):
    body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        try:
            return _activate(aid, actor, publish=bool(body.get("publish")), watch=bool(body.get("watch")))
        except LookupError as e:
            return _err(str(e), 404)
    return await run_in_threadpool(work)


@app.get("/api/slots/{key}/plan")
async def api_plan(key: str, asset_id: str = ""):
    def work():
        try:
            pl = propagate.plan(key, asset_id or None)
        except KeyError:
            return _err("לא נמצאה משבצת כזו", 404)
        pl["asset"] = _asset_view(pl.get("asset"))
        return pl
    return await run_in_threadpool(work)


@app.post("/api/slots/{key}/publish")
async def api_publish(key: str, request: Request):
    body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        act = store.active_of(key)
        aid = body.get("asset_id") or (act or {}).get("asset_id")
        if not aid:
            return _err("אין גרסה פעילה לפרסם", 400)
        return propagate.publish(key, aid, actor=actor, choose=body.get("choose"),
                                 watch=bool(body.get("watch")))
    return await run_in_threadpool(work)


def _pub_view(p: dict) -> dict:
    s = store.get_slot(p["slot_key"])
    ch = store.get_channel(p["channel_id"])
    return {**p, "slot_label": _label(s),
            "channel_label": "המוצרים של הלשכה" if p["channel_id"] == "brand"
            else (((ch or {}).get("label") or {}).get("he") or p["channel_id"]),
            "field_label": propagate.FIELD_HE.get(p.get("field") or "", "")}


@app.get("/api/runs/{rid}")
def api_run(rid: str):
    r = store.get_run(rid)
    if not r:
        return _err("לא נמצא", 404)
    return {**r, "publications": [_pub_view(p) for p in store.run_publications(rid)]}


@app.post("/api/publications/{pid}/done")
async def api_pub_done(pid: str, request: Request):
    body = await _json_body(request)
    row = await run_in_threadpool(propagate.mark_done, pid, _actor(request, body), body.get("url"))
    return _pub_view(row) if row else _err("לא נמצא", 404)


# ── media, posts ─────────────────────────────────────────────────────────────────────────────────
def _ensure_inbox() -> None:
    if not store.get_slot(INBOX):
        store.upsert_slot({"key": INBOX, "section": "media", "grp": "inbox", "kind": "set",
                           "label": {"he": "מדיה שטרם שובצה", "en": "Unfiled media"}, "ord": -1,
                           "brief": {"he": "כל מה שנוצר או הועלה בלי משבצת — משם משבצים."}})


@app.get("/api/media")
async def api_media(slot: str = "", limit: int = 200):
    def work():
        media_keys = {s["key"]: s for s in store.list_slots("media")}
        if slot:
            assets = store.list_assets(slot, limit=limit)
        else:
            assets = [a for a in store.list_assets(None, limit=2000) if a["slot_key"] in media_keys][:limit]
        return {"assets": [{**_asset_view(a), "slot_label": _label(media_keys.get(a["slot_key"]))}
                           for a in assets]}
    return await run_in_threadpool(work)


@app.post("/api/media")
async def api_media_add(request: Request):
    """The agent's door: drop a created image / video / text into a slot (or the inbox)."""
    body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        _ensure_inbox()
        key = body.get("slot") or INBOX
        try:
            return _ingest(key, {**body, "source": body.get("source") or "agent"}, actor)
        except LookupError as e:
            return _err(str(e), 404)
        except (ValueError, files.FileError) as e:
            return _err(str(e), 400)
    return await run_in_threadpool(work)


@app.get("/api/posts")
def api_posts(slot: str = "", limit: int = 50):
    return {"posts": store.list_posts(limit, slot or None)}


@app.post("/api/posts")
async def api_post_create(request: Request):
    body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        chans = body.get("channels") or []
        if not chans:
            return _err("לא נבחרו ערוצים", 400)
        try:
            return posting.create(body.get("slot"), body.get("asset_ids") or [], body.get("text") or "",
                                  chans, actor=actor, watch=bool(body.get("watch")), link=body.get("link"))
        except ValueError as e:
            return _err(str(e), 400)
    return await run_in_threadpool(work)


@app.post("/api/posts/{pid}/done")
async def api_post_done(pid: str, request: Request):
    body = await _json_body(request)
    p = await run_in_threadpool(posting.mark_done, pid, body.get("channel") or "", _actor(request, body),
                                body.get("url"))
    return p or _err("לא נמצא", 404)


# ── channels ─────────────────────────────────────────────────────────────────────────────────────
@app.get("/api/channels")
async def api_channels():
    def work():
        try:
            accounts = clients.social_accounts()
            err = None
        except clients.Unavailable as e:
            accounts, err = [], f"שירות הרשתות החברתיות אינו זמין ({e})"
        try:
            sites = clients.sites_list()
        except clients.Unavailable:
            sites = []
        return {"channels": store.list_channels(), "accounts": accounts, "sites": sites,
                "social_error": err}
    return await run_in_threadpool(work)


@app.put("/api/channels/{cid}")
async def api_channel_bind(cid: str, request: Request):
    body = await _json_body(request)
    ch = store.set_channel_binding(cid, body)
    if not ch:
        return _err("לא נמצא ערוץ כזה", 404)
    store.event("channel", f"ערוץ {((ch.get('label') or {}).get('he')) or cid} עודכן", actor=_actor(request, body),
                data={k: body.get(k) for k in ("account_id", "site_id", "lang", "enabled")})
    return ch


# ── blueprints ───────────────────────────────────────────────────────────────────────────────────
@app.get("/api/blueprints")
def api_blueprints():
    return {"blueprints": [blueprints.summary(b) for b in blueprints.all_blueprints().values()]}


@app.get("/api/blueprints/{bid}")
def api_blueprint(bid: str):
    b = blueprints.all_blueprints().get(bid)
    if not b:
        return _err("תבנית לא מוכרת", 404)
    chain = blueprints.resolve(bid)
    return {**blueprints.summary(b), "slots": b.get("slots") or [], "phases": b.get("phases") or [],
            "calendar": b.get("calendar") or [], "chain": [x["id"] for x in chain]}


@app.post("/api/blueprints/{bid}/apply")
async def api_blueprint_apply(bid: str, request: Request):
    body = await _json_body(request)

    def work():
        try:
            return blueprints.apply(bid, body.get("params") or {}, by=_actor(request, body))
        except blueprints.BlueprintError as e:
            return _err(str(e), 400)
    return await run_in_threadpool(work)


# ── what products and websites read ──────────────────────────────────────────────────────────────
@app.get("/api/brand")
def api_brand():
    return propagate.brand()


@app.get("/api/bundle")
def api_bundle():
    return propagate.bundle()


@app.post("/api/site-kit/scan")
async def api_site_scan(request: Request):
    """Which texts and pictures of a web page are slots already, and which are still hand-written.
    Read-only: fetches the page (or takes the HTML given) and never writes anything."""
    body = await _json_body(request)

    def work():
        import requests as rq
        import site_kit
        page = body.get("html")
        if not page and body.get("url"):
            try:
                r = rq.get(body["url"], timeout=20, headers={"User-Agent": "digital-assets site-kit"})
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                page = r.text
            except rq.RequestException as e:
                log.warning("work: %r", e)
                return _err("לא הצלחתי לקרוא את העמוד", 502)
        if not page:
            return _err("חסרה כתובת או HTML", 400)
        out = site_kit.scan(page)
        actives = store.active_map()
        for m in out["mapped"]:
            s = store.get_slot(m["key"])
            m["label"] = _label(s) if s else None
            m["known"] = bool(s)
            a = actives.get(m["key"])
            asset = store.get_asset(a["asset_id"]) if a else None
            m["active"] = (asset or {}).get("text") if asset and asset.get("text") is not None else (
                "קובץ" if asset else None)
        return out
    return await run_in_threadpool(work)


@app.get("/files/{name}")
def serve_file(name: str, px: int = 0):
    m = re.fullmatch(r"([0-9a-f]{64})\.([a-z0-9]{1,6})", name or "")
    if not m:
        return _err("not found", 404)
    sha, ext = m.group(1), m.group(2)
    if px:
        got = files.raster(sha, ext, px)
        if got:
            return Response(got[0], media_type=got[1], headers={"Cache-Control": "max-age=31536000, immutable"})
    p = files.path_of(sha, ext)
    if not p:
        return _err("not found", 404)
    return FileResponse(str(p), media_type=files.MIME_BY_EXT.get(ext, "application/octet-stream"),
                        headers={"Cache-Control": "max-age=31536000, immutable"})


# ── the change feed, jobs, activity ──────────────────────────────────────────────────────────────
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


@app.get("/api/jobs")
def api_jobs(active: int = 0):
    return {"jobs": webengine.jobs(limit=25, active_only=bool(active))}


@app.get("/api/activity")
def api_activity(limit: int = 60):
    return {"events": store.events(limit)}


# ── canonical ops (platform-service.v1) ──────────────────────────────────────────────────────────
def _op(name: str, body: dict, actor: str):
    if name == "listSlots":
        actives, counts = store.active_map(), _counts()
        return {"slots": [_slot_view(s, actives, counts) for s in store.list_slots(body.get("section"))]}
    if name == "getSlot":
        return _slot_detail(body.get("key") or "")
    if name in ("addAsset", "addMedia"):
        _ensure_inbox()
        return _ingest(body.get("slot") or body.get("key") or INBOX, body, actor)
    if name == "setActive":
        return _activate(body.get("asset_id") or "", actor, publish=bool(body.get("publish")),
                         watch=bool(body.get("watch")))
    if name == "plan":
        pl = propagate.plan(body.get("key") or "", body.get("asset_id"))
        pl["asset"] = _asset_view(pl.get("asset"))
        return pl
    if name == "publish":
        act = store.active_of(body.get("key") or "")
        return propagate.publish(body.get("key") or "", body.get("asset_id") or (act or {}).get("asset_id"),
                                 actor=actor, choose=body.get("choose"), watch=bool(body.get("watch")))
    if name == "listMedia":
        return {"assets": [_asset_view(a) for a in store.list_assets(body.get("slot"), limit=200)]}
    if name == "createPost":
        return posting.create(body.get("slot"), body.get("asset_ids") or [], body.get("text") or "",
                              body.get("channels") or [], actor=actor, watch=bool(body.get("watch")))
    if name == "getBrand":
        return propagate.brand()
    if name == "getBundle":
        return propagate.bundle()
    if name == "listBlueprints":
        return {"blueprints": [blueprints.summary(b) for b in blueprints.all_blueprints().values()]}
    if name == "applyBlueprint":
        return blueprints.apply(body.get("id") or "", body.get("params") or {}, by=actor)
    if name == "listChannels":
        return {"channels": store.list_channels()}
    if name == "bindChannel":
        return store.set_channel_binding(body.get("id") or "", body) or _err("לא נמצא ערוץ", 404)
    return _err("פעולה לא מוכרת", 404)


@app.post("/{op}")
async def canonical(op: str, request: Request):
    if op not in OPS:
        return _err("פעולה לא מוכרת", 404, ops=OPS)
    body = await _json_body(request)
    actor = _actor(request, body)

    def work():
        try:
            return _op(op, body, actor)
        except (LookupError, KeyError) as e:
            return _err(f"לא נמצא: {e}", 404)
        except (ValueError, files.FileError, blueprints.BlueprintError) as e:
            return _err(str(e), 400)
    return await run_in_threadpool(work)


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
    store.init()
    webengine.init()
    webengine.start_workers(int(os.environ.get("DIGITAL_ASSETS_WORKERS", "2")))
    blueprints.ensure_channels()
    _ensure_inbox()
