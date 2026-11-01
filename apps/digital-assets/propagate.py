"""digital-assets.propagate — "make this the active one, and change it everywhere".

Two steps, and the gap between them is the point:

  plan(slot)     for every target of the slot, WHAT would change WHERE and HOW — computed, shown to
                 the owner as a list with facts, never executed on the way:
                   push     automated: a social account through social-list (the office browser on
                            every network, or the network's API), a website through sites
                   manual   a listing or a printed surface — tracked here, done by hand
                   live     the office's own products read the brand live (the `brand` capability)
                   skip     with the reason: no account bound yet, the platform cannot, the channel is
                            in the other language, or a more specific slot covers this field there
  publish(run)   one publication row per chosen item, dispatched as jobs to the owning service,
                 then WATCHED until each ends — `ok` only when that service read the value back.

A more specific slot wins: `identity.profile.x.bio` (targets X's bio only) covers X, so
`identity.description.short` (targets every network's bio) skips X while the specific one is set.
"""
from __future__ import annotations

import logging
import os
import time

import clients
import files
import store
import webengine

log = logging.getLogger("digital-assets.propagate")

SELF_URL = os.environ.get("DIGITAL_ASSETS_URL", "http://digital-assets:8985").rstrip("/")
WATCH_BUDGET = float(os.environ.get("DIGITAL_ASSETS_WATCH_SECONDS", "900"))

FIELD_HE = {"name": "שם תצוגה", "bio": "תיאור קצר", "avatar": "תמונת פרופיל",
            "banner": "תמונת נושא", "links": "קישור", "handle": "שם משתמש"}
IMAGE_FIELDS = ("avatar", "banner")


def file_url(asset: dict, px: int | None = None) -> str | None:
    """An in-network URL for an asset's file — rasterised when it is an SVG and a platform needs
    pixels (no social platform accepts an SVG avatar)."""
    if not asset or not asset.get("file_sha"):
        return None
    url = f"{SELF_URL}/files/{asset['file_sha']}.{asset['file_ext']}"
    if px:
        url += f"?px={int(px)}"
    return url


def value_for(asset: dict, field: str | None, slot: dict) -> dict | str | list | None:
    """The value a channel field receives from an asset."""
    if field in IMAGE_FIELDS:
        if not asset.get("file_sha"):
            return None
        return {"kind": "image", "url": file_url(asset, 2048), "mime": "image/png",
                "name": f"{slot['key'].replace('.', '-')}.png"}
    text = (asset.get("text") or "").strip()
    if field == "links":
        return [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
    return text


def _specific_cover(slot: dict, channel_id: str, field: str, actives: dict) -> dict | None:
    """Another ACTIVE slot that targets (channel, field) more specifically than this one."""
    mine = sum(1 for t in slot.get("targets") or [] if t.get("field") == field)
    for other in store.list_slots():
        if other["key"] == slot["key"] or other["key"] not in actives:
            continue
        tg = [t for t in other.get("targets") or [] if t.get("field") == field]
        if any(t.get("channel") == channel_id for t in tg) and len(tg) < mine:
            return other
    return None


def plan(slot_key: str, asset_id: str | None = None) -> dict:
    slot = store.get_slot(slot_key)
    if not slot:
        raise KeyError(slot_key)
    act = store.active_of(slot_key)
    aid = asset_id or (act or {}).get("asset_id")
    asset = store.get_asset(aid) if aid else None
    actives = store.active_map()
    if asset_id:
        actives = {**actives, slot_key: {"asset_id": asset_id}}
    channels = {c["id"]: c for c in store.list_channels()}
    caps_cache: dict[str, dict] = {}
    social_down = None
    items = []
    for t in slot.get("targets") or []:
        cid, field = t.get("channel"), t.get("field")
        if cid == "brand":
            items.append({"channel": "brand", "channel_label": "המוצרים של הלשכה", "kind": "brand",
                          "field": t.get("brand") or "", "action": "live",
                          "why": "המוצרים קוראים את המותג ישירות מכאן — השינוי חל מיד"})
            continue
        ch = channels.get(cid)
        if not ch:
            continue
        label = (ch.get("label") or {}).get("he") or cid
        base = {"channel": cid, "channel_label": label, "kind": ch["kind"], "field": field or "",
                "field_label": FIELD_HE.get(field or "", "")}
        if not ch.get("enabled"):
            items.append({**base, "action": "skip", "why": "הערוץ כבוי"})
            continue
        if ch["kind"] == "social":
            if not field:
                items.append({**base, "action": "manual", "why": "בשימוש בערוץ הזה — עדכון ידני אם צריך",
                              "url": ch.get("url")})
                continue
            if slot.get("lang") and ch.get("lang") and slot["lang"] != ch["lang"]:
                items.append({**base, "action": "skip",
                              "why": f"הערוץ מוגדר ב{'אנגלית' if ch['lang'] == 'en' else 'עברית'}"})
                continue
            cover = _specific_cover(slot, cid, field, actives)
            if cover:
                items.append({**base, "action": "skip",
                              "why": f"מכוסה על ידי „{(cover.get('label') or {}).get('he', cover['key'])}”",
                              "covered_by": cover["key"]})
                continue
            if not ch.get("account_id"):
                items.append({**base, "action": "skip", "why": "לא חובר חשבון לערוץ", "needs": "bind"})
                continue
            if social_down:
                items.append({**base, "action": "skip", "why": social_down})
                continue
            try:
                caps = caps_cache.get(ch["account_id"]) or clients.social_capabilities(ch["account_id"])
            except clients.Unavailable as e:
                social_down = f"שירות הרשתות החברתיות אינו זמין ({e})"
                items.append({**base, "action": "skip", "why": social_down})
                continue
            caps_cache[ch["account_id"]] = caps
            if caps.get("error"):
                items.append({**base, "action": "skip", "why": caps["error"], "needs": "bind"})
                continue
            sup = (caps.get("ops") or {}).get(f"profile.update.{field}") or {}
            answer = sup.get("answer")
            if answer in ("yes", "limited"):
                items.append({**base, "action": "push", "account_id": ch["account_id"],
                              "account_kind": caps.get("kind"),
                              "why": "חלקי: " + sup.get("why") if answer == "limited" and sup.get("why") else ""})
            else:
                items.append({**base, "action": "skip", "why": sup.get("why") or "הפלטפורמה לא מאפשרת"})
            if asset and field in IMAGE_FIELDS and asset.get("file_ext") == "svg" and not files.can_raster():
                items[-1] = {**items[-1], "action": "skip",
                             "why": "הלוגו הוא SVG ואין כאן המרה לתמונה — העלו גם PNG"}
        elif ch["kind"] == "website":
            if not ch.get("site_id"):
                items.append({**base, "action": "skip", "why": "לא נבחר אתר לערוץ", "needs": "bind"})
            else:
                items.append({**base, "action": "push", "site_id": ch["site_id"],
                              "why": f"המפתח {slot_key} בעמודי האתר"})
        else:
            items.append({**base, "action": "manual", "url": ch.get("url"),
                          "why": "עדכון ידני — הלשכה עוקבת שבוצע"})
    for i, it in enumerate(items):
        it["i"] = i
    counts = {}
    for it in items:
        counts[it["action"]] = counts.get(it["action"], 0) + 1
    return {"slot": slot_key, "asset_id": aid, "items": items, "counts": counts,
            "asset": asset}


# ── publish ──────────────────────────────────────────────────────────────────────────────────────
def publish(slot_key: str, asset_id: str, *, actor: str, choose: list[int] | None = None,
            watch: bool = False) -> dict:
    """Start a publication run for (slot, asset). Returns the run with its rows; the deliveries run
    as jobs and are watched in the background."""
    pl = plan(slot_key, asset_id)
    slot = store.get_slot(slot_key)
    asset = store.get_asset(asset_id)
    rid = store.new_run(slot_key, asset_id, actor)
    # Without an explicit choice, what the office can DO goes out (push, live); a manual update of a
    # directory listing is tracked only when the owner ticks it — otherwise every name change would
    # leave ten "update Waze by hand" chores nobody asked for.
    default = ("push", "live")
    chosen = [it for it in pl["items"]
              if (it["i"] in choose if choose is not None else it["action"] in default)
              and it["action"] in ("push", "manual", "live")]
    rows = []
    for it in chosen:
        state = {"live": "ok", "manual": "needs_owner"}.get(it["action"], "queued")
        pid = store.add_publication(rid, slot_key, asset_id, it["channel"], it.get("field") or "",
                                    state, {"action": it["action"], "why": it.get("why"),
                                            "url": it.get("url")})
        rows.append((pid, it))
    store.set_run_state(rid, "running" if any(it["action"] == "push" for _, it in rows) else "done")
    for pid, it in rows:
        if it["action"] != "push":
            continue
        try:
            _dispatch(pid, it, slot, asset, actor, watch)
        except Exception as e:                                # noqa: BLE001 — one channel's failure
            log.warning("dispatch %s failed: %s", pid, e)     # never stops the others
            store.update_publication(pid, state="failed",
                                     result={"error": "השליחה נכשלה"})
    if any(it["action"] == "push" for _, it in rows):
        webengine.submit(f"watch:{rid}", _watch, {"run": rid},
                         title=f"פרסום „{(slot.get('label') or {}).get('he', slot_key)}”",
                         invalidates=[f"slot:{slot_key}"])
    store.event("publish", f"הופעל פרסום ל-{len(rows)} ערוצים", slot_key=slot_key, actor=actor,
                data={"run": rid, "asset": asset_id})
    webengine.publish({"type": "run", "run": rid, "slot": slot_key})
    return {"run": rid, "publications": store.run_publications(rid)}


def _dispatch(pid: str, it: dict, slot: dict, asset: dict, actor: str, watch: bool) -> None:
    label = (slot.get("label") or {}).get("he", slot["key"])
    if it["kind"] == "social":
        value = value_for(asset, it["field"], slot)
        if value in (None, "", []):
            store.update_publication(pid, state="failed", result={"error": "לנכס אין ערך לשדה הזה"})
            return
        code, body = clients.social_update_profile(
            it["account_id"], {it["field"]: value}, client=pid, actor=f"digital-assets:{actor}",
            summary=f"{label} → {it.get('field_label') or it['field']}", watch=watch)
        _absorb(pid, code, body)
    elif it["kind"] == "website":
        code, body = clients.sites_apply(it["site_id"], bundle(only=[slot["key"]]),
                                         actor=actor, client=pid)
        if code == 404 and "slots" not in str(body):
            store.update_publication(pid, state="failed",
                                     result={"error": "אפליקציית האתרים עוד לא תומכת במשבצות (data-da)"})
            return
        _absorb(pid, code, body)


def _absorb(pid: str, code: int, body: dict) -> None:
    """A remote answer → the row's state. 202 = a job to watch; 200 = done now; else failed."""
    job = (body or {}).get("job") or {}
    if code == 202 or (job and job.get("state") in ("queued", "running")):
        store.update_publication(pid, state="running", job_id=job.get("id") or "",
                                 result={"remote": "queued"})
    elif code < 300:
        _finish_from(pid, body)
    else:
        store.update_publication(pid, state="failed", result=_error_of(body))


def _error_of(body: dict) -> dict:
    b = body or {}
    return {k: b.get(k) for k in ("error", "why", "how", "url", "kind", "state", "detail") if b.get(k)}


def _finish_from(pid: str, body: dict) -> None:
    result = (body or {}).get("result") or body or {}
    rstate = result.get("state")
    if rstate in (None, "ok"):
        store.update_publication(pid, state="ok", result={"verify": result.get("verify"),
                                                          "url": result.get("url"),
                                                          "report": result.get("report")})
    else:
        store.update_publication(pid, state="failed", result={"error": "לא אומת", **result})


def _watch(progress, params) -> dict:
    """Follow every running row of a run until it ends (or the budget does)."""
    rid = params["run"]
    end = time.time() + WATCH_BUDGET
    while time.time() < end:
        rows = store.run_publications(rid)
        running = [r for r in rows if r["state"] in ("queued", "running") and r.get("job_id")]
        for r in running:
            try:
                job = clients.social_job(r["job_id"])
            except clients.Unavailable:
                continue
            if not job:
                continue
            if job.get("state") == "ok":
                _finish_from(r["id"], {"result": job.get("result") or {}})
            elif job.get("state") in ("error", "cancelled"):
                body = (job.get("result") or {}).get("error_body") or {"error": job.get("error")}
                state = "needs_owner" if (body or {}).get("kind") in ("needs_owner", "needs_verification") else "failed"
                store.update_publication(r["id"], state=state, result=_error_of(body))
            webengine.publish({"type": "publication", "run": rid, "id": r["id"]})
        rows = store.run_publications(rid)
        done = sum(1 for r in rows if r["state"] not in ("queued", "running"))
        progress(int(100 * done / max(1, len(rows))), f"{done} מתוך {len(rows)} ערוצים הסתיימו")
        if not any(r["state"] in ("queued", "running") for r in rows):
            break
        time.sleep(2)
    rows = store.run_publications(rid)
    states = {r["state"] for r in rows}
    final = "done" if states <= {"ok", "needs_owner"} else (
        "failed" if states <= {"failed"} else "partial")
    store.set_run_state(rid, final)
    webengine.publish({"type": "run", "run": rid, "state": final})
    return {"run": rid, "state": final, "counts": {s: sum(1 for r in rows if r["state"] == s) for s in states}}


def mark_done(pid: str, actor: str, url: str | None = None) -> dict | None:
    """The owner did the manual step (a listing, a printed surface): the delivery is now done."""
    row = store.get_publication(pid)
    if not row:
        return None
    res = dict(row.get("result") or {})
    res.update({"done_by": actor, "done_at": store.now(), **({"url": url} if url else {})})
    store.update_publication(pid, state="ok", result=res)
    store.event("done", "סומן כבוצע ידנית", slot_key=row["slot_key"], actor=actor,
                data={"publication": pid, "channel": row["channel_id"]})
    webengine.publish({"type": "publication", "run": row["run_id"], "id": pid})
    return store.get_publication(pid)


# ── what websites and products read ──────────────────────────────────────────────────────────────
def bundle(only: list[str] | None = None, public_base: str | None = None) -> dict:
    """Every ACTIVE value a website shows, keyed by slot key (the `data-da` attribute value)."""
    base = (public_base or SELF_URL).rstrip("/")
    out = {}
    actives = store.active_map()
    for s in store.list_slots():
        if only and s["key"] not in only:
            continue
        if not any(t.get("channel") in ("website", "blog", "app-store") for t in s.get("targets") or []):
            continue
        a = actives.get(s["key"])
        asset = store.get_asset(a["asset_id"]) if a else None
        if not asset:
            continue
        entry = {"kind": s["kind"], "label": (s.get("label") or {}).get("he")}
        if asset.get("file_sha"):
            entry.update({"url": f"{base}/files/{asset['file_sha']}.{asset['file_ext']}",
                          "sha": asset["file_sha"], "mime": asset.get("mime"),
                          "width": asset.get("width"), "height": asset.get("height")})
        if asset.get("text") is not None:
            entry["text"] = asset["text"]
        out[s["key"]] = entry
    return {"generated_at": store.now(), "slots": out}


def brand(public_base: str | None = None) -> dict:
    """The business identity as the office's own products read it (capability `brand`)."""
    base = (public_base or SELF_URL).rstrip("/")
    out = {}
    actives = store.active_map()
    for s in store.list_slots("identity"):
        for t in s.get("targets") or []:
            if t.get("channel") != "brand" or not t.get("brand"):
                continue
            a = actives.get(s["key"])
            asset = store.get_asset(a["asset_id"]) if a else None
            if not asset:
                continue
            if asset.get("file_sha"):
                out[t["brand"]] = {"url": f"{base}/files/{asset['file_sha']}.{asset['file_ext']}",
                                   "png": f"{base}/files/{asset['file_sha']}.{asset['file_ext']}?px=512",
                                   "mime": asset.get("mime")}
            else:
                out[t["brand"]] = asset.get("text")
    return {"brand": out, "updated_at": max([a["set_at"] for a in actives.values()] or [0])}
