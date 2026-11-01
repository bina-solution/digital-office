"""digital-assets.posting — publish media from the gallery to channels, by click or by the agent.

A post is text + media assets + channels. Each social channel gets a `createPost` through
social-list (which picks the account's implementation — the office browser, or the network's API);
a listing channel (Product Hunt, Reddit…) gets a manual card — the text and the files, marked done by
the owner. Every channel's outcome is kept on the post row, and the post is watched until each ends.
"""
from __future__ import annotations

import time

import clients
import propagate
import store
import webengine

WATCH_BUDGET = 900


def create(slot_key: str | None, asset_ids: list[str], text: str, channel_ids: list[str], *,
           actor: str, watch: bool = False, link: str | None = None) -> dict:
    assets = [store.get_asset(a) for a in asset_ids or []]
    assets = [a for a in assets if a]
    media = []
    for a in assets:
        if a.get("file_sha") and a["kind"] in ("image", "video", "animation"):
            kind = "image" if a["kind"] in ("image", "animation") and a.get("file_ext") != "mp4" else "video"
            media.append({"kind": kind,
                          "url": propagate.file_url(a, 2048 if a.get("file_ext") == "svg" else None),
                          "mime": "image/png" if a.get("file_ext") == "svg" else a.get("mime"),
                          "name": (a.get("title") or a["id"]) + (".png" if a.get("file_ext") == "svg" else f".{a.get('file_ext')}")})
    if not text.strip() and not media:
        raise ValueError("פוסט ריק — אין טקסט ואין מדיה")
    import files
    svg_blocked = any(a.get("file_ext") == "svg" for a in assets) and not files.can_raster()
    pid = store.add_post(slot_key, [a["id"] for a in assets], text, channel_ids, actor)
    results = {}
    channels = {c["id"]: c for c in store.list_channels()}
    for cid in channel_ids:
        ch = channels.get(cid)
        if not ch:
            results[cid] = {"state": "failed", "error": "ערוץ לא מוכר"}
            continue
        if ch["kind"] == "social" and ch.get("account_id") and svg_blocked:
            results[cid] = {"state": "failed", "error": "המדיה היא SVG ואין כאן המרה לתמונה — "
                                                         "העלו PNG או JPEG לפרסום ברשתות"}
            continue
        if ch["kind"] == "social" and ch.get("account_id"):
            try:
                code, body = clients.social_create_post(
                    ch["account_id"], {"text": text, "media": media, **({"link": link} if link else {})},
                    client=f"{pid}:{cid}", actor=f"digital-assets:{actor}", watch=watch)
            except clients.Unavailable as e:
                results[cid] = {"state": "failed", "error": f"שירות הרשתות אינו זמין ({e})"}
                continue
            job = (body or {}).get("job") or {}
            if code == 202 or job.get("state") in ("queued", "running"):
                results[cid] = {"state": "running", "job_id": job.get("id")}
            elif code < 300:
                results[cid] = _final((body or {}).get("result") or {})
            else:
                results[cid] = {"state": "failed", **propagate._error_of(body)}
        elif ch["kind"] == "social":
            results[cid] = {"state": "failed", "error": "לא חובר חשבון לערוץ", "needs": "bind"}
        else:
            results[cid] = {"state": "needs_owner",
                            "manual": {"title": f"פרסום ב־{(ch.get('label') or {}).get('he', cid)}",
                                        "text": text, "url": ch.get("url"),
                                        "files": [{"file_url": f"files/{a['file_sha']}.{a['file_ext']}",
                                                   "name": a.get("title")} for a in assets if a.get("file_sha")],
                                        "instructions": "פרסמו ידנית עם הטקסט והקבצים — וסמנו „בוצע”."}}
    store.update_post(pid, state=_overall(results), results=results)
    if any(r.get("state") == "running" for r in results.values()):
        webengine.submit(f"watch-post:{pid}", _watch, {"post": pid}, title="פרסום פוסט",
                         invalidates=["posts"])
    store.event("post", f"פוסט ל-{len(channel_ids)} ערוצים", slot_key=slot_key, actor=actor,
                data={"post": pid})
    return store.get_post(pid)


def _final(result: dict) -> dict:
    return {"state": "ok", "url": result.get("url"), "id": result.get("id"),
            "cost_hint": result.get("cost_hint")}


def _overall(results: dict) -> str:
    states = {r.get("state") for r in results.values()}
    if states & {"running", "queued"}:
        return "running"
    if states <= {"ok"}:
        return "ok"
    if states <= {"ok", "needs_owner"}:
        return "needs_owner"
    if states <= {"failed"}:
        return "failed"
    return "partial"


def _watch(progress, params) -> dict:
    pid = params["post"]
    end = time.time() + WATCH_BUDGET
    while time.time() < end:
        post = store.get_post(pid) or {}
        results = dict(post.get("results") or {})
        pending = {c: r for c, r in results.items() if r.get("state") == "running" and r.get("job_id")}
        if not pending:
            break
        for cid, r in pending.items():
            try:
                job = clients.social_job(r["job_id"])
            except clients.Unavailable:
                continue
            if not job:
                continue
            if job.get("state") == "ok":
                results[cid] = _final(job.get("result") or {})
            elif job.get("state") in ("error", "cancelled"):
                body = (job.get("result") or {}).get("error_body") or {"error": job.get("error")}
                results[cid] = {"state": "failed", **propagate._error_of(body)}
        store.update_post(pid, state=_overall(results), results=results)
        webengine.publish({"type": "post", "id": pid})
        done = sum(1 for r in results.values() if r.get("state") != "running")
        progress(int(100 * done / max(1, len(results))), f"{done} מתוך {len(results)} ערוצים")
        time.sleep(2)
    return {"post": pid, "state": (store.get_post(pid) or {}).get("state")}


def mark_done(pid: str, channel_id: str, actor: str, url: str | None = None) -> dict | None:
    post = store.get_post(pid)
    if not post:
        return None
    results = dict(post.get("results") or {})
    r = dict(results.get(channel_id) or {})
    r.update({"state": "ok", "done_by": actor, **({"url": url} if url else {})})
    results[channel_id] = r
    store.update_post(pid, state=_overall(results), results=results)
    webengine.publish({"type": "post", "id": pid})
    return store.get_post(pid)
