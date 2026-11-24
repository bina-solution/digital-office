"""The three places a signing lands besides the app's own volume: «קבצים», «התראות», and the stream.

Each is one HTTP call to a service of this office, each is *allowed to fail* — the signature is the
product, the copy and the notice are not — and each failure is recorded on the envelope so `bbox esign
retry <id>` can finish the job instead of anyone guessing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

try:
    import redis as _redis
except Exception:                        # pragma: no cover - the image always has it
    _redis = None


def _request(method: str, url: str, body: bytes | None = None,
             headers: dict | None = None, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:                      # a real answer, with a code
        return exc.code, exc.read() or b""
    except Exception as exc:                                   # no answer at all
        return 0, str(exc).encode("utf-8")


# ── the office's documents renderer ─────────────────────────────────────────────────────────────────
def render_house(render_url: str, doc: dict, timeout: int = 15) -> bytes | None:
    """A page in the office's house style, drawn by the documents renderer (the ledger's
    `POST /docGen/house`, DGO-2029) — the same look as every document the business issues. None when
    the renderer is not there or answers anything but a PDF: the caller draws its own page instead."""
    if not render_url:
        return None
    code, body = _request("POST", "%s/docGen/house?format=pdf" % render_url.rstrip("/"),
                          body=json.dumps(doc, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, timeout=timeout)
    return body if code == 200 and body.startswith(b"%PDF") else None


# ── the drive ───────────────────────────────────────────────────────────────────────────────────────
def drive_put(drive_url: str, path: str, data: bytes, content_type: str = "application/pdf",
              timeout: int = 120) -> dict:
    """PUT one file into a folder, by its contract: `PUT /api/fs/content?path=…` (never overwrites).

    Drive keeps an existing file and names the new one «name (2)», which is exactly the behaviour a
    signed document wants: the office's earlier copy is never lost.
    """
    url = "%s/api/fs/content?path=%s" % (drive_url.rstrip("/"), urllib.parse.quote(path))
    code, body = _request("PUT", url, body=data, headers={"Content-Type": content_type}, timeout=timeout)
    ok = 200 <= code < 300
    detail = ""
    if not ok:
        detail = body.decode("utf-8", "replace")[:300]
    return {"ok": ok, "status": code, "path": path, "detail": detail}


def drive_find(drive_url: str, path: str, timeout: int = 30) -> dict:
    """Read back what is in a folder (`GET /api/fs?path=…`) — the proof that a copy arrived."""
    url = "%s/api/fs?path=%s" % (drive_url.rstrip("/"), urllib.parse.quote(path))
    code, body = _request("GET", url, timeout=timeout)
    if not 200 <= code < 300:
        return {"ok": False, "status": code, "detail": body.decode("utf-8", "replace")[:300]}
    try:
        return {"ok": True, "status": code, "data": json.loads(body)}
    except Exception:
        return {"ok": True, "status": code, "data": {}}


# ── the notice board ───────────────────────────────────────────────────────────────────────────────
def notify(notifications_url: str, *, source_id: str, title: str, body: str = "", link: str = "",
           level: str = "info", to: list[str] | None = None,
           actions: list[dict] | None = None, meta: dict | None = None,
           timeout: int = 20) -> dict:
    """One notice, with a STABLE `source_id`: a second signer updates the notice, never doubles it."""
    payload = {"source": "esign", "source_id": source_id, "title": title, "body": body,
               "level": level, "link": link}
    extra = dict(meta or {})
    if to:
        extra["to"] = to
    if actions:
        extra["actions"] = actions
    if extra:
        payload["meta"] = extra
    code, resp = _request("POST", notifications_url.rstrip("/") + "/api/notifications",
                          json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          {"Content-Type": "application/json"}, timeout=timeout)
    return {"ok": 200 <= code < 300, "status": code,
            "detail": "" if 200 <= code < 300 else resp.decode("utf-8", "replace")[:300]}


# ── the stream ─────────────────────────────────────────────────────────────────────────────────────
def publish(app_id: str, type_: str, title: str, *, link: str = "", data: dict | None = None,
            redis_url: str = "", password: str = "") -> bool:
    """flow.v1: one XADD, capped and expiring, and a publish that fails is counted — never raised."""
    if not redis_url or _redis is None:
        return False
    try:
        client = _redis.Redis.from_url(redis_url, password=password or None, socket_timeout=5)
        key = "dgo:flow:%s" % app_id
        fields = {"type": type_, "title": title, "at": _now(), "app": app_id}
        if link:
            fields["link"] = link
        if data:
            fields["data"] = json.dumps(data, ensure_ascii=False)
        pipe = client.pipeline()
        pipe.xadd(key, fields, maxlen=1000, approximate=True)
        pipe.expire(key, 2592000)
        pipe.execute()
        return True
    except Exception:
        return False


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_base() -> str:
    """The address a signer's link is minted on, the one rule (server.public_base reads it here).

    ESIGN_PUBLIC_URL when the office's signer page is published on another office's edge (DGO-2125: the HP's door at
    https://sign.bina-solutions.digital-office.co.il, opened by vps1's `publish:`, DGO-2050). That edge serves the door
    on https only,
    so a name written without a scheme is that https address. Else ESIGN_BASE_URL. The public address is never
    written into ESIGN_BASE_URL: that one is also the host this office routes esign's own screen under
    (docker-compose.yml) and signs it in at (app.json `sso`)."""
    public = os.environ.get("ESIGN_PUBLIC_URL", "").strip()
    if public and "://" not in public:
        public = "https://" + public
    return (public or os.environ.get("ESIGN_BASE_URL", "http://esign.localhost:8080")).rstrip("/")


def config() -> dict:
    return {
        "drive_url": os.environ.get("DRIVE_URL", "http://drive:8975").rstrip("/"),
        # under «מסמכים»: «ארכיון» lists what is there (DGO-2125); /חתימות was a folder nothing indexed
        "drive_folder": os.environ.get("ESIGN_DRIVE_FOLDER", "מסמכים/חתימות"),
        "notifications_url": os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/"),
        "redis_url": os.environ.get("REDIS_URL", ""),
        "redis_password": os.environ.get("REDIS_PASSWORD", ""),
        "public_base": public_base(),
        # the office's documents renderer (the ledger, apitools): the certificate in the house style
        "render_url": os.environ.get("ESIGN_RENDER_URL", "http://apitools:8080").rstrip("/"),
    }
