"""The gallery — ONE visual library of the business's digital assets, kept in «קבצים» (drive).

Drive is the office's one file layer (owner, CHAT-70), so this module stores nothing: every folder
and file lives under `GALLERY_ROOT` in drive and is read through drive's path API. The browser never
talks to drive; these routes proxy it. When drive is not installed or does not answer, every route
says so in Hebrew (`drive.ok = false` + `reason`) instead of failing (CHAT-79).

  GET  /api/gallery                      the folders, their counts and a few covers, and drive's state
  POST /api/gallery/setup                create the folder layout in drive (get-or-create, idempotent)
  GET  /api/gallery/folder/{fid}         one folder's items (id, name, mime, size, kind)
  GET  /api/gallery/file/{id}/thumb      drive's picture of a file (webp), 404 when it has none
  GET  /api/gallery/file/{id}/content    the file itself (sandboxed: never runs as this app's page)
  GET  /api/gallery/file/{id}/model      an STL model as projected, shaded triangles (drawn inline)
"""
import math
import os
import struct

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()
DRIVE_URL = os.environ.get("DRIVE_URL", "http://drive:8975").rstrip("/")
ROOT = os.environ.get("GALLERY_ROOT", "/נכסים דיגיטליים").rstrip("/")
TIMEOUT = float(os.environ.get("GALLERY_DRIVE_TIMEOUT", "5"))
MAX_MODEL = 25 * 1024 * 1024
FOLDERS = [  # (id, folder name in drive) — the order is the gallery's order
    ("logos", "לוגו"), ("designs", "עיצובים"), ("mockups", "הדמיות"), ("images", "תמונות"),
    ("icons", "אייקונים"), ("3d", "מודלים תלת־ממד"), ("pdf", "PDF"), ("html", "HTML"),
]
NAMES = dict(FOLDERS)


class DriveDown(Exception):
    pass


def _get(route, **params):
    try:
        return requests.get(DRIVE_URL + route, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise DriveDown(str(e)) from e


def _down(e=None, status=None):
    if status:
        why = f"«קבצים» החזיר שגיאה ({status})"
    else:
        why = "«קבצים» לא עונה — האפליקציה לא מותקנת במשרד הזה או שהיא כבויה"
    return {"ok": False, "reason": why, "detail": str(e or "")[:200]}


def kind_of(f):
    n, m = (f.get("name") or "").lower(), (f.get("mime") or "").lower()
    ext = n.rsplit(".", 1)[-1] if "." in n else ""
    if ext == "svg" or m == "image/svg+xml":
        return "svg"
    if m.startswith("image/") or ext in ("png", "jpg", "jpeg", "webp", "gif", "avif"):
        return "image"
    if ext == "pdf" or m == "application/pdf":
        return "pdf"
    if ext in ("html", "htm") or m == "text/html":
        return "html"
    if ext in ("stl", "glb", "gltf", "obj", "3mf", "ply") or m.startswith("model/"):
        return "model"
    if m.startswith("video/"):
        return "video"
    return "file"


def _item(f, fid):
    return {"id": f.get("id"), "name": f.get("name") or "", "mime": f.get("mime") or "",
            "size": f.get("size") or 0, "created": f.get("created") or "", "kind": kind_of(f),
            "ext": ((f.get("name") or "").rsplit(".", 1)[-1].lower() if "." in (f.get("name") or "") else ""),
            "folder": fid}


def _listing(name):
    r = _get("/api/fs", path=f"{ROOT}/{name}")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise DriveDown(f"status {r.status_code}")
    return r.json()


@router.get("/api/gallery")
def gallery():
    out = {"root": ROOT, "drive": {"ok": True}, "exists": True, "folders": []}
    try:
        r = _get("/api/fs", path=ROOT)
        if r.status_code == 404:
            out["exists"] = False
        elif r.status_code != 200:
            out["drive"] = _down(status=r.status_code)
            return out
        for fid, name in FOLDERS:
            d = _listing(name) if out["exists"] else None
            files = (d or {}).get("files") or []
            out["folders"].append({"id": fid, "name": name, "path": f"{ROOT}/{name}", "exists": d is not None,
                                   "count": len(files), "covers": [_item(f, fid) for f in files[:4]]})
    except (DriveDown, ValueError) as e:
        out["drive"] = _down(e)
        out["folders"] = [{"id": fid, "name": name, "path": f"{ROOT}/{name}", "exists": False, "count": 0,
                           "covers": []} for fid, name in FOLDERS]
    return out


@router.post("/api/gallery/setup")
def gallery_setup():
    made = []
    try:
        for _, name in FOLDERS:
            r = requests.post(DRIVE_URL + "/api/fs/mkdir", json={"path": f"{ROOT}/{name}"}, timeout=TIMEOUT)
            if r.status_code >= 300:
                return JSONResponse({"error": f"«קבצים» לא יצר את {name} ({r.status_code})"}, 502)
            made.append(name)
    except requests.RequestException as e:
        return JSONResponse({"error": _down(e)["reason"]}, 503)
    return {"ok": True, "folders": made}


@router.get("/api/gallery/folder/{fid}")
def gallery_folder(fid: str):
    if fid not in NAMES:
        return JSONResponse({"error": "אין תיקייה כזו בגלריה"}, 404)
    try:
        d = _listing(NAMES[fid])
    except (DriveDown, ValueError) as e:
        return {"drive": _down(e), "items": [], "id": fid, "name": NAMES[fid]}
    return {"drive": {"ok": True}, "id": fid, "name": NAMES[fid], "path": f"{ROOT}/{NAMES[fid]}",
            "exists": d is not None, "items": [_item(f, fid) for f in ((d or {}).get("files") or [])]}


def _pass(r, extra=None):
    h = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    h.update(extra or {})
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"), headers=h)


@router.get("/api/gallery/file/{fid}/thumb")
def gallery_thumb(fid: str, s: int = 480):
    try:
        r = _get(f"/api/file/{fid}/thumb", s=max(64, min(int(s), 1600)))
    except DriveDown as e:
        return JSONResponse({"error": _down(e)["reason"]}, 503)
    if r.status_code != 200:
        return JSONResponse({"error": "אין תמונה לקובץ הזה"}, 404)
    return _pass(r)


@router.get("/api/gallery/file/{fid}/content")
def gallery_content(fid: str, request: Request):
    try:
        r = _get(f"/api/file/{fid}/content")
    except DriveDown as e:
        return JSONResponse({"error": _down(e)["reason"]}, 503)
    if r.status_code >= 300:
        return JSONResponse({"error": "הקובץ לא נקרא מ«קבצים»"}, 404)
    # a design page or an SVG from the gallery is SHOWN, never run as this app: no scripts, no
    # same-origin, no forms — whatever is inside the file.
    return _pass(r, {"Content-Security-Policy": "sandbox", "Content-Disposition": "inline"})


def _stl(data):
    tris = []
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        vs = []
        for line in data.decode("utf-8", "ignore").splitlines():
            p = line.split()
            if p and p[0] == "vertex" and len(p) >= 4:
                vs.append(tuple(float(x) for x in p[1:4]))
                if len(vs) == 3:
                    tris.append(vs)
                    vs = []
    else:
        n = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
        for i in range(min(n, (len(data) - 84) // 50)):
            v = struct.unpack_from("<12f", data, 84 + i * 50)
            tris.append([v[3:6], v[6:9], v[9:12]])
    return tris


@router.get("/api/gallery/file/{fid}/model")
def gallery_model(fid: str):
    """An STL drawn as the thing itself: triangles turned to a three-quarter view, painted far to
    near, each with its light (0..1). The page fills them with the office's own colour."""
    try:
        r = _get(f"/api/file/{fid}/content")
    except DriveDown as e:
        return JSONResponse({"error": _down(e)["reason"]}, 503)
    if r.status_code >= 300 or len(r.content) > MAX_MODEL:
        return JSONResponse({"error": "המודל לא נקרא"}, 404)
    tris = _stl(r.content)[:6000]
    if not tris:
        return JSONResponse({"error": "אין במודל משולשים לציור (STL בלבד)"}, 415)
    ay, ax = math.radians(35), math.radians(-28)
    cy, sy, cx, sx = math.cos(ay), math.sin(ay), math.cos(ax), math.sin(ax)

    def rot(p):
        x, y, z = p[0], p[2], p[1]                      # STL is Z-up; the screen is Y-up
        x, z = x * cy + z * sy, -x * sy + z * cy
        y, z = y * cx - z * sx, y * sx + z * cx
        return x, y, z
    out, light = [], (0.35, 0.75, -0.55)
    for t in tris:
        a, b, c = (rot(p) for p in t)
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx, ny, nz = u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
        shade = abs(nx * light[0] + ny * light[1] + nz * light[2]) / ln
        out.append(((a[2] + b[2] + c[2]) / 3, [a[0], -a[1], b[0], -b[1], c[0], -c[1]], shade))
    out.sort(key=lambda t: -t[0])
    xs = [q for _, p, _ in out for q in p[0::2]]
    ys = [q for _, p, _ in out for q in p[1::2]]
    x0, y0 = min(xs), min(ys)
    w, h = (max(xs) - x0) or 1, (max(ys) - y0) or 1
    k = 100 / max(w, h)
    polys = [[round((p[i] - (x0 if i % 2 == 0 else y0)) * k, 2) for i in range(6)] + [round(0.25 + 0.75 * s, 3)]
             for _, p, s in out]
    return {"w": round(w * k, 2), "h": round(h * k, 2), "polys": polys, "count": len(tris)}
