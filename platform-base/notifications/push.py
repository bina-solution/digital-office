"""push — the office's notices on the owners' phones (Web Push: RFC 8030, 8291, 8292).

A person allows it once, on a phone (the card at the top of this app's page); from then on every
notice whose level is in PUSH_LEVELS (default: error) — a service down, the CPU at its limit, a
backup that failed — rings that phone. When the same notice clears (its row turns «back to normal»,
level info, same source_id — the office watch's contract) the phone's notice is REPLACED quietly
(same tag, no sound), so a stale alarm never sits on a lock screen.

  * The VAPID key is made ONCE, at the first start, into the data volume (PUSH_KEY_FILE, default
    /data/vapid.pem, mode 600). It is never printed or logged; only its public half leaves
    (GET api/push/key). A new key would silence every phone, so a damaged file is said, never replaced.
  * push_devices: one row per browser endpoint, owned by the signed-in person the edge's forward-auth
    names (X-authentik-username, else X-authentik-email). Every route of this module needs that person.
  * Fan-out: create_notification() calls notice_written() after its write. The decision is made there
    (new · re-opened · recurred after PUSH_REPEAT_MIN · cleared) and the sending runs on ONE background
    thread, so a POST to /api/notifications answers at once whatever the push services do.
  * A push service answering 404/410 means that phone unsubscribed: its row goes.

Settings (environment, all optional):
  PUSH_ENABLED=1          0 = nothing is sent and the card says push is off here
  PUSH_LEVELS=error       which notice levels ring (error | warning | info, comma-separated)
  PUSH_REPEAT_MIN=240     a notice that keeps recurring rings again at most this often (minutes)
  PUSH_CLEAR_QUIETLY=1    a rung notice that clears replaces the phone's notice quietly
  PUSH_TTL=86400          how long a push service keeps a message for a phone that is off (seconds)
  PUSH_MAX_PER_HOUR=30    a storm guard: past this many rung notices in an hour, ONE summary instead
  PUSH_KEY_FILE=/data/vapid.pem
  PUSH_SUBJECT=           the VAPID contact (mailto: or https:); default = the origin a phone allowed from
  PUSH_ENDPOINT_HOSTS=    the push services a subscription may point at (suffix match); default = the
                          browsers' own: FCM (Chrome, Samsung Internet, Edge-Android), Mozilla, Apple, Windows
"""
import base64
import hashlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

log = logging.getLogger("notifications.push")
bp = Blueprint("push", __name__)

DEFAULT_HOSTS = ("fcm.googleapis.com,android.googleapis.com,updates.push.services.mozilla.com,"
                 "push.services.mozilla.com,web.push.apple.com,notify.windows.com")
_BUCKET = {"error": "error", "fatal": "error", "critical": "error", "warning": "warning", "warn": "warning"}


def _env(name, default):
    return os.getenv(name, default)


def _int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def enabled():
    return _env("PUSH_ENABLED", "1").strip() not in ("0", "false", "no", "off", "")


def levels():
    return {x.strip().lower() for x in _env("PUSH_LEVELS", "error").split(",") if x.strip()}


def bucket(level):
    return _BUCKET.get((level or "info").strip().lower(), "info")


def _db_path():
    return os.getenv("NOTIFICATIONS_DB", "/data/notifications.db")


def _db():
    c = sqlite3.connect(_db_path(), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    """Two tables of this module's own (the notifications schema is not touched)."""
    os.makedirs(os.path.dirname(_db_path()) or ".", exist_ok=True)
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS push_devices(
                       id         INTEGER PRIMARY KEY AUTOINCREMENT,
                       person     TEXT NOT NULL,             -- the signed-in user (forward-auth)
                       endpoint   TEXT NOT NULL UNIQUE,      -- the browser's push-service address
                       p256dh     TEXT NOT NULL,
                       auth       TEXT NOT NULL,
                       label      TEXT DEFAULT '',           -- «Android · Samsung Internet»
                       origin     TEXT DEFAULT '',           -- where it was allowed (the VAPID contact)
                       created_at TEXT NOT NULL,
                       last_ok_at TEXT,
                       last_error TEXT DEFAULT '',
                       fails      INTEGER NOT NULL DEFAULT 0)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_push_person ON push_devices(person)")
        # what was last rung for a notice: decides «again?» and «replace quietly?»
        c.execute("""CREATE TABLE IF NOT EXISTS push_rung(
                       source     TEXT NOT NULL,
                       source_id  TEXT NOT NULL DEFAULT '',
                       at         REAL NOT NULL,
                       level      TEXT NOT NULL,
                       PRIMARY KEY(source, source_id))""")


# ── the key ──────────────────────────────────────────────────────────────────────────────────────
_KEY = {}
_key_lock = threading.Lock()


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64u(text):
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_file():
    return _env("PUSH_KEY_FILE", os.path.join(os.path.dirname(_db_path()) or ".", "vapid.pem"))


def load_key():
    """The office's VAPID key: made once into the data volume, read at every start after. Returns the
    public key (base64url, uncompressed point) or '' when push cannot run here (said once in the log,
    never with any part of the key)."""
    with _key_lock:
        if _KEY.get("public"):
            return _KEY["public"]
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            import pywebpush  # noqa: F401 — the sender: checked here so a half-installed push never half-works
            from py_vapid import Vapid
        except ImportError as e:
            log.warning("web push is off: %s is not installed (requirements.txt: pywebpush)", e.name)
            return ""
        path = key_file()
        if not os.path.exists(path):
            pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass                                # made a moment ago by another start: that one is the key
            else:
                with os.fdopen(fd, "wb") as f:
                    f.write(pem)
                log.info("web push: a new VAPID key was made in %s (mode 600) — keep it: a new one silences every phone", path)
        try:
            vapid = Vapid.from_file(path)
            raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        except Exception as e:  # noqa: BLE001 — a damaged key is said, never silently replaced
            log.error("web push is off: %s cannot be read (%s); a NEW key would orphan every phone", path, type(e).__name__)
            return ""
        _KEY.update(vapid=vapid, public=b64u(raw))
        return _KEY["public"]


# ── who is asking ────────────────────────────────────────────────────────────────────────────────
def person():
    for h in ("X-authentik-username", "X-authentik-email"):
        v = (request.headers.get(h) or "").strip()
        if v:
            return v[:120]
    return ""


def _who():
    p = person()
    if not p:
        return None, (jsonify(error="no_person", message="לא זוהה משתמש מחובר — היכנס דרך המשרד"), 401)
    return p, None


def _json():
    """A JSON body only: a cross-site form cannot post one (application/json needs a CORS preflight)."""
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def _hosts():
    return [h.strip().lower().lstrip(".") for h in _env("PUSH_ENDPOINT_HOSTS", DEFAULT_HOSTS).split(",") if h.strip()]


def endpoint_ok(url):
    """Only the browsers' own push services: a subscription is never a way to make this server post to an
    address of the office's network."""
    try:
        u = urlsplit(url or "")
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" and not (u.scheme == "http" and _env("PUSH_ALLOW_HTTP", "0") == "1"):
        return False
    return bool(host) and any(host == h or host.endswith("." + h) for h in _hosts())


def device_label(ua):
    ua = ua or ""
    os_ = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua
           else "Windows" if "Windows" in ua else "Mac" if "Macintosh" in ua else "Linux" if "Linux" in ua else "")
    br = ("Samsung Internet" if "SamsungBrowser" in ua else "Edge" if "Edg/" in ua else "Firefox" if "Firefox" in ua
          else "Chrome" if ("Chrome" in ua or "CriOS" in ua) else "Safari" if "Safari" in ua else "")
    return " · ".join(x for x in (os_, br) if x) or "דפדפן"


def _device_out(r, endpoint=""):
    return {"id": r["id"], "label": r["label"], "created_at": r["created_at"], "last_ok_at": r["last_ok_at"],
            "last_error": r["last_error"] or "", "this": bool(endpoint) and r["endpoint"] == endpoint}


# ── the API (relative paths: it is served at its own host and inside the console at /a/alerts/) ──
@bp.get("/api/push/key")
def api_key():
    k = load_key() if enabled() else ""
    return jsonify(enabled=enabled(), ready=bool(k), key=k, levels=sorted(levels()), person=person())


@bp.get("/api/push/devices")
def api_devices():
    p, err = _who()
    if err:
        return err
    ep = request.args.get("endpoint", "")
    with _db() as c:
        rows = c.execute("SELECT * FROM push_devices WHERE person=? ORDER BY id DESC", (p,)).fetchall()
    return jsonify(person=p, devices=[_device_out(r, ep) for r in rows])


@bp.post("/api/push/subscribe")
def api_subscribe():
    p, err = _who()
    if err:
        return err
    b = _json()
    if not isinstance(b, dict):
        return jsonify(error="json_required"), 400
    sub = b.get("subscription") if isinstance(b.get("subscription"), dict) else b
    ep = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if not endpoint_ok(ep) or len(ep) > 1000:
        return jsonify(error="bad_endpoint", message="כתובת המנוי אינה של שירות התראות מוכר"), 400
    try:
        if len(unb64u(keys.get("p256dh"))) != 65 or len(unb64u(keys.get("auth"))) != 16:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify(error="bad_keys"), 400
    label = (str(b.get("label") or "") or device_label(request.headers.get("User-Agent")))[:80]
    origin = (request.headers.get("Origin") or "").strip()[:200]
    if not origin.startswith(("https://", "http://")):
        origin = ""
    replaces = str(b.get("replaces") or "")
    with _db() as c:
        if replaces and replaces != ep:
            c.execute("DELETE FROM push_devices WHERE endpoint=? AND person=?", (replaces, p))
        cur = c.execute("SELECT id FROM push_devices WHERE endpoint=?", (ep,)).fetchone()
        if cur:   # this browser again — maybe another person signed in on a shared phone: it rings for them now
            c.execute("UPDATE push_devices SET person=?, p256dh=?, auth=?, label=?, origin=?, fails=0, last_error='' "
                      "WHERE id=?", (p, keys["p256dh"], keys["auth"], label, origin, cur["id"]))
            return jsonify(id=cur["id"], created=False), 200
        cur = c.execute("INSERT INTO push_devices(person, endpoint, p256dh, auth, label, origin, created_at) "
                        "VALUES(?,?,?,?,?,?,?)", (p, ep, keys["p256dh"], keys["auth"], label, origin, _now_iso()))
        return jsonify(id=cur.lastrowid, created=True), 201


@bp.post("/api/push/unsubscribe")
def api_unsubscribe():
    p, err = _who()
    if err:
        return err
    b = _json() or {}
    with _db() as c:
        if b.get("id"):
            cur = c.execute("DELETE FROM push_devices WHERE id=? AND person=?", (int(b["id"]), p))
        else:
            cur = c.execute("DELETE FROM push_devices WHERE endpoint=? AND person=?", (str(b.get("endpoint") or ""), p))
    return jsonify(ok=True, removed=cur.rowcount)


@bp.post("/api/push/test")
def api_test():
    """«Send a test to this phone»: sent NOW (not queued), so the card can say what the push service said."""
    p, err = _who()
    if err:
        return err
    if not enabled() or not load_key():
        return jsonify(error="push_off", message="ההתראות לטלפון כבויות במשרד הזה"), 409
    b = _json() or {}
    ep = str(b.get("endpoint") or "")
    with _db() as c:
        rows = c.execute("SELECT * FROM push_devices WHERE person=?" + (" AND endpoint=?" if ep else ""),
                         (p, ep) if ep else (p,)).fetchall()
        if not rows:
            return jsonify(error="no_device", message="אין מכשיר רשום — אפשר קודם"), 404
        msg = message("בדיקה — התראות המשרד", "כך תיראה התראה חמורה מהמשרד בטלפון הזה.", "", "office-test", "error")
        res = [send(c, r, msg, "office-test", urgency="normal") for r in rows]
    return jsonify(sent=res.count("ok"), gone=res.count("gone"), failed=len(res) - res.count("ok") - res.count("gone"))


# ── the message and one send ─────────────────────────────────────────────────────────────────────
def message(title, body, url, tag, level, nid=None, quiet=False):
    """Declarative Web Push form ({web_push: 8030, notification: {…}}): an iPhone on iOS 18.4+ shows it by
    itself; sw.js shows the same fields everywhere else. Encrypted end to end, under the 4 KB limit."""
    d = {"web_push": 8030,
         "notification": {"title": (title or "התראה מהמשרד")[:120], "body": (body or "")[:300], "navigate": url or "",
                          "tag": tag, "silent": bool(quiet), "lang": "he", "dir": "auto"},
         "level": level, "id": nid}
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def topic_of(tag):
    """RFC 8030 Topic: ≤ 32 base64url characters. A newer message with the same topic replaces one the
    push service still holds for a phone that is off."""
    return b64u(hashlib.sha256(tag.encode("utf-8")).digest())[:32]


def _contact(row):
    s = _env("PUSH_SUBJECT", "").strip()
    if s:
        return s
    o = (row["origin"] or "").strip()
    return o if o.startswith("https://") else "mailto:office@localhost"


def send(c, row, data, tag, urgency="high"):
    """One message to one device: 'ok', 'gone' (its row deleted), or 'failed' (kept, counted)."""
    import pywebpush
    try:
        pywebpush.webpush(subscription_info={"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                          data=data, vapid_private_key=_KEY["vapid"],
                          vapid_claims={"sub": _contact(row)},      # a NEW dict each time: webpush() writes aud/exp into it
                          ttl=_int("PUSH_TTL", 86400, 60, 2419200), timeout=10,
                          headers={"Urgency": urgency, "Topic": topic_of(tag)})
    except pywebpush.WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        host = urlsplit(row["endpoint"]).hostname
        if code in (404, 410):
            c.execute("DELETE FROM push_devices WHERE id=?", (row["id"],))
            log.info("push: a device of %s is gone (%s at %s) — removed", row["person"], code, host)
            return "gone"
        c.execute("UPDATE push_devices SET fails=fails+1, last_error=? WHERE id=?", (("HTTP %s" % code)[:60], row["id"]))
        log.warning("push: %s answered %s for a device of %s", host, code, row["person"])
        return "failed"
    except Exception as e:  # noqa: BLE001 — the push service did not answer
        c.execute("UPDATE push_devices SET fails=fails+1, last_error=? WHERE id=?", (type(e).__name__[:60], row["id"]))
        log.warning("push: %s for a device of %s: %s", urlsplit(row["endpoint"]).hostname, row["person"], type(e).__name__)
        return "failed"
    c.execute("UPDATE push_devices SET last_ok_at=?, fails=0, last_error='' WHERE id=?", (_now_iso(), row["id"]))
    return "ok"


# ── the decision, and the one thread that sends ──────────────────────────────────────────────────
def _to(meta):
    """meta.to (a username/e-mail, or a list of them) addresses a notice to those people only."""
    t = (meta or {}).get("to") if isinstance(meta, dict) else None
    if isinstance(t, str):
        t = [t]
    return {str(x).strip().lower() for x in (t or []) if str(x).strip()}


def decide(created, prev_level, level, recurred, rung, now):
    """What a write means for the phones: 'new' | 'reopened' | 'again' | 'clear' | None.

    rung = (at, level) of the last push for this notice, or None. A notice that existed before push was
    turned on and only recurs is recorded, not rung (no burst of old notices on the first day)."""
    lv = levels()
    if bucket(level) not in lv:
        if rung and bucket(rung[1]) in lv and _env("PUSH_CLEAR_QUIETLY", "1") == "1":
            return "clear"
        return None
    if created:
        return "new"
    if prev_level is not None and bucket(prev_level) not in lv:
        return "reopened"
    if recurred:
        if rung is None:
            return "baseline"
        if now - rung[0] >= _int("PUSH_REPEAT_MIN", 240, 1, 10080) * 60:
            return "again"
    return None


_Q = queue.Queue()
_worker = {"t": None}
_worker_lock = threading.Lock()
_storm = {"window": 0, "count": 0, "told": False}


def notice_written(nid, source, source_id, title, body, level, link, meta, created, prev_level, recurred):
    """Called by create_notification() after its write; never raises, never blocks on the network."""
    try:
        if not enabled():
            return
        now = time.time()
        sid = "" if source_id is None else str(source_id)
        with _db() as c:
            r = c.execute("SELECT at, level FROM push_rung WHERE source=? AND source_id=?", (source, sid)).fetchone()
            what = decide(created, prev_level, level, recurred, (r["at"], r["level"]) if r else None, now)
            if what is None:
                return
            if what == "baseline":
                c.execute("INSERT OR REPLACE INTO push_rung(source, source_id, at, level) VALUES(?,?,?,?)",
                          (source, sid, now, level or "info"))
                return
            if what == "clear":
                c.execute("DELETE FROM push_rung WHERE source=? AND source_id=?", (source, sid))
            else:
                c.execute("INSERT OR REPLACE INTO push_rung(source, source_id, at, level) VALUES(?,?,?,?)",
                          (source, sid, now, level or "error"))
        _Q.put({"what": what, "nid": nid, "source": source, "source_id": sid, "title": title, "body": body,
                "level": bucket(level), "link": link or "", "to": sorted(_to(meta))})
        _ensure_worker()
    except Exception as e:  # noqa: BLE001 — a notice is stored whatever happens to its push
        log.warning("push: could not queue notice %s: %s", nid, type(e).__name__)


def _ensure_worker():
    with _worker_lock:
        if _worker["t"] is None or not _worker["t"].is_alive():
            _worker["t"] = threading.Thread(target=_loop, name="push-sender", daemon=True)
            _worker["t"].start()


def _loop():
    while True:
        job = _Q.get()
        try:
            deliver(job)
        except Exception as e:  # noqa: BLE001 — the thread survives any one job
            log.warning("push: delivering notice %s failed: %s", job.get("nid"), type(e).__name__)
        finally:
            _Q.task_done()


def flush(timeout=10.0):
    """Wait until every queued push was tried (tests; a graceful stop)."""
    end = time.time() + timeout
    while _Q.unfinished_tasks and time.time() < end:
        time.sleep(0.02)
    return not _Q.unfinished_tasks


def deliver(job):
    if not load_key():
        return {}
    tag = "notice-%s:%s" % (job["source"], job["source_id"])
    quiet = job["what"] == "clear"
    if not quiet:   # the storm guard: past PUSH_MAX_PER_HOUR in an hour, one summary and then quiet
        hour = int(time.time() // 3600)
        if _storm["window"] != hour:
            _storm.update(window=hour, count=0, told=False)
        _storm["count"] += 1
        if _storm["count"] > _int("PUSH_MAX_PER_HOUR", 30, 1, 1000):
            if _storm["told"]:
                return {}
            _storm["told"] = True
            job = dict(job, title="עוד התראות חמורות במשרד", body="יש עוד התראות — פתח את מרכז ההתראות.", link="")
            tag = "notice-storm"
    data = message(job["title"], job["body"], job["link"], tag, job["level"], job["nid"], quiet=quiet)
    out = {}
    with _db() as c:
        rows = c.execute("SELECT * FROM push_devices").fetchall()
    if job["to"]:
        rows = [r for r in rows if r["person"].lower() in job["to"]]
    for r in rows:
        # one short write per device, after its network call: no database lock is held across devices, so a notice
        # POSTed while a push service is slow never waits on the database (the office watch's POST stays fast)
        with _db() as c:
            res = send(c, r, data, tag, urgency="normal" if quiet else "high")
        out[res] = out.get(res, 0) + 1
    if rows:
        log.info("push: notice %s (%s) to %d device(s): %s", job["nid"], job["what"], len(rows), out)
    return out


def setup(app):
    """Wire this module into the app: its tables, its routes, and the key made at the first start."""
    global log
    log = app.logger.getChild("push")       # the app's own log (docker logs), never with any part of the key
    init_db()
    app.register_blueprint(bp)
    if enabled():
        try:
            load_key()
        except Exception as e:  # noqa: BLE001 — the notices work whatever push does
            log.warning("web push: key not loaded at start: %s", type(e).__name__)
