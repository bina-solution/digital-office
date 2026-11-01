"""social-list.media — a picture, made the size THIS platform wants, exactly once per write.

digital-assets owns the master (the logo the owner chose); every platform wants something different
from it — a 400×400 circle on X, a 1640×624 cover on Facebook, 800×800 on YouTube. The catalogue
(platforms.yaml: `profile.avatar` / `profile.banner`) says what; this module makes it:

  * centre-crop to the target aspect (never stretch — a stretched logo is the one visible bug);
  * resize to the target pixels with a real filter;
  * keep PNG when the master has transparency and the target is an avatar (a logo on a circle),
    otherwise JPEG at q90 — small enough to cross the browser link inline (see browser.py).

A media item arrives as `{kind, url | data_base64, mime, name, alt}`. `url` is in-network
(`http://digital-assets:8985/files/<sha>`), fetched once and kept for the life of the write.
"""
from __future__ import annotations

import base64
import io
import logging
import re

import requests

log = logging.getLogger("social-list.media")

try:                                                   # Pillow is in the image; tests run without
    from PIL import Image
except ImportError:                                    # pragma: no cover
    Image = None

MAX_FETCH = 60 * 1024 * 1024
FETCH_TIMEOUT = 30


class MediaError(Exception):
    pass


class Media:
    def __init__(self, spec: dict):
        spec = spec or {}
        self.kind = spec.get("kind") or "image"
        self.url = spec.get("url") or ""
        self.mime = spec.get("mime") or ""
        self.name = spec.get("name") or ""
        self.alt = spec.get("alt") or ""
        self._b64 = spec.get("data_base64") or ""
        self._data: bytes | None = None

    def data(self) -> bytes:
        if self._data is not None:
            return self._data
        if self._b64:
            self._data = base64.b64decode(self._b64)
        elif self.url:
            r = requests.get(self.url, timeout=FETCH_TIMEOUT, stream=True)
            if r.status_code != 200:
                raise MediaError(f"לא הצלחתי להביא את הקובץ ({r.status_code}) מ-{self.url}")
            buf = io.BytesIO()
            for chunk in r.iter_content(64 * 1024):
                buf.write(chunk)
                if buf.tell() > MAX_FETCH:
                    raise MediaError("הקובץ גדול מדי להעברה")
            self._data = buf.getvalue()
            self.mime = self.mime or r.headers.get("content-type", "").split(";")[0]
        else:
            raise MediaError("פריט מדיה בלי קובץ")
        return self._data

    def filename(self, ext: str | None = None) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", self.name or "media").strip("-") or "media"
        if ext and not base.lower().endswith("." + ext):
            base = base.rsplit(".", 1)[0] + "." + ext
        return base

    def public(self) -> dict:
        return {"kind": self.kind, "url": self.url, "mime": self.mime, "name": self.name}


def _aspect(spec: dict) -> float | None:
    if spec.get("w") and spec.get("h"):
        return float(spec["w"]) / float(spec["h"])
    a = str(spec.get("aspect") or "")
    m = re.match(r"^\s*([\d.]+)\s*:\s*([\d.]+)\s*$", a)
    return float(m.group(1)) / float(m.group(2)) if m else None


def rendition(media: Media, spec: dict | None, prefer_png: bool = False) -> tuple[bytes, str]:
    """(bytes, mime) of `media` cut to `spec` = {w, h, aspect, max_mb}. Without Pillow or without a
    spec, the original bytes — never a failure just because we could not resize."""
    raw = media.data()
    if not spec or Image is None or media.kind != "image":
        return raw, media.mime or "application/octet-stream"
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:                              # noqa: BLE001 — SVG and friends
        raise MediaError("הקובץ אינו תמונה שאפשר לעבד; "
                         "יש לספק PNG או JPEG") from e
    ratio = _aspect(spec)
    w, h = img.size
    if ratio:
        if w / h > ratio:                                # too wide → crop the sides
            nw = int(round(h * ratio))
            left = (w - nw) // 2
            img = img.crop((left, 0, left + nw, h))
        elif w / h < ratio:                              # too tall → crop top and bottom
            nh = int(round(w / ratio))
            top = (h - nh) // 2
            img = img.crop((0, top, w, top + nh))
    tw, th = spec.get("w"), spec.get("h")
    if tw and th and (img.size[0] > tw or img.size[1] > th or img.size[0] < tw * 0.5):
        img = img.resize((int(tw), int(th)), Image.LANCZOS)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    out = io.BytesIO()
    if has_alpha and prefer_png:
        img.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png"
    if has_alpha:
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.convert("RGBA").split()[-1])
        img = bg
    img = img.convert("RGB")
    img.save(out, "JPEG", quality=90, optimize=True)
    data = out.getvalue()
    limit = float(spec.get("max_mb") or 0) * 1024 * 1024
    q = 85
    while limit and len(data) > limit and q >= 50:          # the platform's size cap, honoured
        out = io.BytesIO()
        img.save(out, "JPEG", quality=q, optimize=True)
        data = out.getvalue()
        q -= 10
    return data, "image/jpeg"


def sha_short(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


# ── a public copy, for the one API that fetches media itself (Instagram) ─────────────────────────
#: Instagram's publishing API takes an `image_url` it downloads — it cannot receive bytes. So the
#: file needs a PUBLIC address for a few minutes. When the deployment has one
#: (SOCIAL_LIST_PUBLIC_URL, routed with /public/ outside SSO), the rendition is written under an
#: unguessable name and removed after an hour; without it, the op refuses and names the setting.
import os as _os
import secrets as _secrets
import time as _time
from pathlib import Path as _Path

PUBLIC_BASE = (_os.environ.get("SOCIAL_LIST_PUBLIC_URL") or "").rstrip("/")
PUBLIC_DIR = _Path(_os.environ.get("APP_STATE_DIR", "/data")) / "public"
PUBLIC_TTL = 3600


def publish_public(data: bytes, mime: str) -> str | None:
    if not PUBLIC_BASE:
        return None
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    ext = {"image/png": "png", "image/jpeg": "jpg", "video/mp4": "mp4"}.get(mime, "bin")
    name = f"{_secrets.token_urlsafe(18)}.{ext}"
    (PUBLIC_DIR / name).write_bytes(data)
    cutoff = _time.time() - PUBLIC_TTL
    for old in PUBLIC_DIR.iterdir():
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    return f"{PUBLIC_BASE}/public/{name}"


def public_file(name: str):
    p = (PUBLIC_DIR / name).resolve()
    if PUBLIC_DIR.resolve() not in p.parents or not p.exists():
        return None
    if _time.time() - p.stat().st_mtime > PUBLIC_TTL:
        return None
    return p
