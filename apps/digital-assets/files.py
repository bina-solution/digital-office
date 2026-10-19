"""digital-assets.files — every file the business owns, stored once, by what it IS.

Content-addressed: a file's name is the SHA-256 of its bytes (`/data/files/ab/abcd….png`). The same
logo uploaded twice is one file; an asset row points at a hash; a URL to a file never changes
meaning (which is also what makes platform caches refresh — a NEW logo is a NEW url).

Two derived forms, made on demand and cached next to the original:
  * `raster(sha, px)` — a PNG of an SVG master, because no social platform accepts SVG avatars
    (cairosvg in the container; without it, an SVG is served as-is and the plan says a PNG is needed);
  * `thumb(sha, w)`  — a small preview for the gallery.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path

STATE_DIR = Path(os.environ.get("APP_STATE_DIR", "/data"))
ROOT = STATE_DIR / "files"
MAX_BYTES = int(os.environ.get("DIGITAL_ASSETS_MAX_MB", "200")) * 1024 * 1024

try:
    from PIL import Image
except ImportError:                                      # pragma: no cover
    Image = None
try:                                                    # needs libcairo (installed in the image)
    import cairosvg
except Exception:                                       # noqa: BLE001 — ImportError or OSError
    cairosvg = None

EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
               "image/svg+xml": "svg", "video/mp4": "mp4", "video/webm": "webm",
               "video/quicktime": "mov", "application/pdf": "pdf", "application/json": "json",
               "text/plain": "txt", "text/markdown": "md", "font/woff2": "woff2",
               "application/zip": "zip"}
MIME_BY_EXT = {v: k for k, v in EXT_BY_MIME.items()}
MIME_BY_EXT.update({"jpeg": "image/jpeg", "lottie": "application/json", "ttf": "font/ttf",
                    "otf": "font/otf", "woff": "font/woff", "ico": "image/x-icon"})


class FileError(Exception):
    pass


def kind_of(mime: str) -> str:
    m = (mime or "").lower()
    if m == "image/gif":
        return "animation"
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m == "application/pdf":
        return "document"
    return "file"


def _path(sha: str, ext: str) -> Path:
    return ROOT / sha[:2] / f"{sha}.{ext}"


def _sniff(data: bytes, name: str, mime: str) -> tuple[str, str]:
    head = data[:512].lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048]):
        return "image/svg+xml", "svg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:4] == b"%PDF":
        return "application/pdf", "pdf"
    if data[4:8] == b"ftyp":
        return "video/mp4", "mp4"
    ext = (name.rsplit(".", 1)[-1].lower() if "." in (name or "") else "") or EXT_BY_MIME.get(mime, "bin")
    return (mime or MIME_BY_EXT.get(ext, "application/octet-stream")), ext


def _svg_size(data: bytes) -> tuple[int | None, int | None]:
    txt = data[:4000].decode("utf-8", "ignore")
    w = re.search(r'\bwidth="([\d.]+)(px)?"', txt)
    h = re.search(r'\bheight="([\d.]+)(px)?"', txt)
    if w and h:
        return int(float(w.group(1))), int(float(h.group(1)))
    vb = re.search(r'viewBox="[\d.\-]+[ ,]+[\d.\-]+[ ,]+([\d.]+)[ ,]+([\d.]+)"', txt)
    if vb:
        return int(float(vb.group(1))), int(float(vb.group(2)))
    return None, None


def put(data: bytes, name: str = "", mime: str = "") -> dict:
    """Store bytes; return {sha, ext, mime, size, width, height, kind}."""
    if not data:
        raise FileError("קובץ ריק")
    if len(data) > MAX_BYTES:
        raise FileError(f"הקובץ גדול מהמותר ({MAX_BYTES // 1024 // 1024}MB)")
    mime, ext = _sniff(data, name, mime)
    sha = hashlib.sha256(data).hexdigest()
    p = _path(sha, ext)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    w = h = None
    if ext == "svg":
        w, h = _svg_size(data)
    elif Image is not None and mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
        except Exception:                                # noqa: BLE001
            pass
    return {"sha": sha, "ext": ext, "mime": mime, "size": len(data), "width": w, "height": h,
            "kind": kind_of(mime)}


def path_of(sha: str, ext: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{64}", sha or "") or not re.fullmatch(r"[a-z0-9]{1,6}", ext or ""):
        return None
    p = _path(sha, ext)
    return p if p.exists() else None


def can_raster() -> bool:
    return cairosvg is not None


def raster(sha: str, ext: str, px: int = 1024) -> tuple[bytes, str] | None:
    """A PNG of this file at `px` on its long side. SVG → cairosvg; raster → Pillow resize."""
    src = path_of(sha, ext)
    if not src:
        return None
    px = max(16, min(int(px or 1024), 4096))
    cache = ROOT / "derived" / f"{sha}-{px}.png"
    if cache.exists():
        return cache.read_bytes(), "image/png"
    data = src.read_bytes()
    out = None
    if ext == "svg":
        if cairosvg is None:
            return None
        w, h = _svg_size(data)
        if w and h and h > w:
            out = cairosvg.svg2png(bytestring=data, output_height=px)
        else:
            out = cairosvg.svg2png(bytestring=data, output_width=px)
    elif Image is not None:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            im.thumbnail((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            (im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")).save(buf, "PNG", optimize=True)
            out = buf.getvalue()
    if out is None:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(out)
    return out, "image/png"


def thumb(sha: str, ext: str, w: int = 320) -> tuple[bytes, str] | None:
    if ext in ("svg",):
        p = path_of(sha, ext)
        return (p.read_bytes(), "image/svg+xml") if p else None
    return raster(sha, ext, w)
