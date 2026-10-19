"""notifications — התראות: a self-developed notifications microservice.

A generic notifications store + full REST API + a background poller. The FIRST
integration source is GlitchTip: GlitchTip already aggregates errors from every app
(via per-project DSNs), so this service polls GlitchTip's Sentry-compatible issues API
and creates one notification per NEW issue (deduped by GlitchTip issue id). Any other
source (indox, whatsapp, system, …) can later POST into /api/notifications — the schema
is source-agnostic (a `source` + `source_id` pair is the only coupling).

Serves a Hebrew-RTL Bina SPA (static/) at `/` with a thin REST API under /api/.
All UI + API paths are RELATIVE so the app embeds same-origin at console.localhost/a/alerts/.

Stack: stdlib + Flask + requests + gunicorn only. SQLite (single writer) persisted on a
volume at /data. Exactly ONE poller runs (gunicorn 1 worker → post_worker_init).
"""
import json
import os
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from flask import Flask, request, jsonify, send_from_directory

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# NOTIFICATIONS_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset. (Yes, the
# notifications service reports ITS OWN errors to GlitchTip too — dogfooding the platform.)
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

app = Flask(__name__, static_folder="static", static_url_path="")

# ── config (all env-driven; safe defaults for local) ─────────────────────────────
DB_PATH = os.getenv("NOTIFICATIONS_DB", "/data/notifications.db")
# GlitchTip on the shared traefik-network. Internal DNS `glitchtip:8000` is proven to
# resolve (apps/connections/providers/40-apps.yaml probes http://glitchtip:8000/_health/).
GLITCHTIP_URL = os.getenv("GLITCHTIP_URL", "http://glitchtip:8000").rstrip("/")
# Slug of GLITCHTIP_ORG_NAME. The default was the literal "hacohen": on any other company the
# poller asked GlitchTip for an org that does not exist, got 404 on every page, and rendered an
# EMPTY alerts screen rather than a failing one. compose passes ${GLITCHTIP_ORG_SLUG}, which
# derives from COMPANY_SLUG — the same slug that names every host.
GLITCHTIP_ORG = os.getenv("GLITCHTIP_ORG", "").strip()
# The token does NOT exist yet in .env / the connection catalog. It must be provisioned
# (mint an APIToken via glitchtip-push ORM and write GLITCHTIP_API_TOKEN). Without it the
# poller logs ONE warning and stays idle; the REST API + manual POSTs still work.
GLITCHTIP_TOKEN = os.getenv("GLITCHTIP_API_TOKEN", "")
GLITCHTIP_QUERY = os.getenv("GLITCHTIP_QUERY", "is:unresolved")  # Sentry grammar (NOT is:unread)
POLL_INTERVAL = int(os.getenv("NOTIFICATIONS_POLL_INTERVAL", "60"))
SOURCE_GLITCHTIP = "glitchtip-issue"
# External, browser-reachable base for GlitchTip permalinks. GlitchTip's own `permalink`
# uses GLITCHTIP_DOMAIN, which historically hardcoded https:// — on an http-only *.localhost
# stack that yields a cert error when the user clicks "פתח במקור". If set, we rewrite the
# permalink's scheme+host to this base (path/query preserved) so the link actually opens.
GLITCHTIP_WEB_URL = os.getenv("GLITCHTIP_WEB_URL", "").rstrip("/")


def _fix_link(permalink: str) -> str:
    """Rewrite a GlitchTip permalink onto GLITCHTIP_WEB_URL (working scheme+host), keeping
    the path. No-op when GLITCHTIP_WEB_URL is unset or the permalink is empty/unparseable."""
    if not permalink or not GLITCHTIP_WEB_URL:
        return permalink or ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        base, p = urlsplit(GLITCHTIP_WEB_URL), urlsplit(permalink)
        if not p.path:
            return permalink
        return urlunsplit((base.scheme, base.netloc, p.path, p.query, p.fragment))
    except Exception:
        return permalink

# Warn-once latch: the "no token → idle" warning is emitted a single time, not every cycle.
_warned_no_token = False

# ── poller liveness (what /healthz actually reports on) ──────────────────────────
# This service has exactly ONE job: turn GlitchTip issues into notifications. If the poller is
# not polling, the service is BROKEN — however cheerfully the Flask process answers HTTP. The
# old /healthz checked only that SQLite was readable and reported `token:false` as a FIELD while
# still returning 200, so Docker called the container healthy for 6.5h while it saw nothing and
# ~1,700 errors went unreported. Health is now derived from the poll loop itself:
#   _poll["ok"]  — did the LAST cycle succeed? (None = no cycle completed yet)
#   _poll["at"]  — monotonic clock of the last SUCCESSFUL cycle (staleness detection: a loop
#                  wedged on a hung socket stops updating this while _poll["ok"] stays True)
_poll = {"ok": None, "at": None, "error": None, "started": time.monotonic()}
_poll_lock = threading.Lock()
# A cycle is late after 3 missed intervals (tolerates one slow/retried poll without flapping).
POLL_STALE_AFTER = POLL_INTERVAL * 3
# Boot grace: 200 until the first cycle has had a fair chance to run, so a cold start does not
# restart-loop. Bounded — after this, "no cycle yet" is a real failure, not a pending state.
POLL_BOOT_GRACE = max(POLL_INTERVAL, 30)


def _record_poll(ok: bool, error: str = "") -> None:
    with _poll_lock:
        _poll["ok"] = ok
        _poll["error"] = error
        if ok:
            _poll["at"] = time.monotonic()


# ── is there an error-tracking provider at all? ──────────────────────────────────
# This app declares error-tracking as `wants` (platform-base/notifications/app.json), and
# glitchtip is a GALLERY app since 2026-09-17: a first run ships without it. "No token" then has
# two very different meanings, and /healthz must tell them apart:
#   * glitchtip is DEPLOYED but no token was minted → blind while issues pile up → 503 (the
#     outage this liveness check was written for; unchanged).
#   * glitchtip is NOT deployed → there is nothing to poll → idle is the correct state → 200.
# The distinction is made the only way that is true by construction: can the provider's
# address be reached? Checked at most once a minute so /healthz stays cheap.
_provider = {"at": 0.0, "reachable": None}


def _provider_reachable() -> bool:
    now = time.monotonic()
    if _provider["reachable"] is not None and now - _provider["at"] < 60:
        return _provider["reachable"]
    parts = urlsplit(GLITCHTIP_URL)
    host, port = parts.hostname or "glitchtip", parts.port or (443 if parts.scheme == "https" else 80)
    try:
        socket.create_connection((host, port), timeout=2).close()
        ok = True
    except OSError:
        ok = False
    _provider.update(at=now, reachable=ok)
    return ok


def poller_health():
    """(ok, detail) for the poll loop. ok=False whenever this service cannot do its job."""
    with _poll_lock:
        state = dict(_poll)
    if not _provider_reachable():
        # Nothing to poll: the provider is not part of this deployment (or not up). The REST
        # API and manual POSTs (indox, mail, system) still work — this service is doing its
        # job, and a token left in .env by a template changes nothing about that.
        return True, "idle: no error-tracking provider deployed (glitchtip unreachable)"
    if not GLITCHTIP_TOKEN:
        # The precise failure that hid tonight's outage: no token → every issues call is a 401 →
        # nothing is ever seen. Blind is not healthy.
        return False, "GLITCHTIP_API_TOKEN not set — poller idle, no issue can ever be seen"
    if state["ok"] is False:
        return False, f"last poll failed: {state['error']}"
    if state["ok"] is None:
        if time.monotonic() - state["started"] < POLL_BOOT_GRACE:
            return True, "starting: first poll cycle pending"
        return False, "no poll cycle has completed since start"
    age = time.monotonic() - (state["at"] or state["started"])
    if age > POLL_STALE_AFTER:
        return False, f"last successful poll {int(age)}s ago (> {POLL_STALE_AFTER}s)"
    return True, f"last successful poll {int(age)}s ago"


# ── storage (SQLite v1 — single writer, lowest-friction; a volume persists it) ───
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the schema. Idempotent — safe to call on every startup and from the poller."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS notifications(
                 id          INTEGER PRIMARY KEY AUTOINCREMENT,
                 source      TEXT NOT NULL,              -- glitchtip-issue | indox | whatsapp | system | …
                 source_id   TEXT,                       -- dedupe key within a source (glitchtip issue id)
                 title       TEXT NOT NULL,
                 body        TEXT DEFAULT '',
                 level       TEXT DEFAULT 'info',        -- error | warning | info
                 link        TEXT DEFAULT '',            -- deep link back to the source (glitchtip permalink)
                 meta        TEXT DEFAULT '{}',          -- JSON blob (count, project, culprit, …)
                 is_read     INTEGER NOT NULL DEFAULT 0,
                 created_at  TEXT NOT NULL,             -- FIRST occurrence
                 updated_at  TEXT NOT NULL,
                 last_seen   TEXT                       -- LAST occurrence (drives display time + sort)
               )"""
        )
        # migration for pre-existing DBs: add last_seen if missing (sqlite has no ADD COLUMN IF NOT EXISTS)
        cols = [r[1] for r in c.execute("PRAGMA table_info(notifications)")]
        if "last_seen" not in cols:
            c.execute("ALTER TABLE notifications ADD COLUMN last_seen TEXT")
            c.execute("UPDATE notifications SET last_seen=created_at WHERE last_seen IS NULL")
        # dedupe: one row per (source, source_id). Poller relies on INSERT OR IGNORE.
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_source ON notifications(source, source_id)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS ix_read ON notifications(is_read, last_seen)")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row(r):
    d = dict(r)
    d["is_read"] = bool(d["is_read"])
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except Exception:
        d["meta"] = {}
    return d


def create_notification(source, title, *, source_id=None, body="", level="info", link="", meta=None):
    """Upsert-by-(source,source_id). Returns (id, created:bool).

    Dedup with RECURRENCE awareness: re-polling the same GlitchTip issue must not spawn a
    duplicate row, BUT a genuine NEW occurrence (GlitchTip ``count`` went up, or ``lastSeen``
    advanced) should re-surface it — bump ``last_seen`` (which drives the displayed time + sort)
    and mark it unread again, so a recurring error doesn't sit silently as a stale "43m ago".
    A refresh with NO new occurrence only updates display fields and leaves read-state alone.

    Two-step (INSERT OR IGNORE, then UPDATE-if-existed) so `created` is reliable."""
    now = _now()
    meta = meta or {}
    meta_s = json.dumps(meta, ensure_ascii=False)
    last_seen = meta.get("lastSeen") or now  # GlitchTip's real last-occurrence time

    def _cnt(m):
        try:
            return int((json.loads(m) if isinstance(m, str) else m or {}).get("count") or 0)
        except Exception:
            return 0

    with _db() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO notifications
                 (source, source_id, title, body, level, link, meta, is_read, created_at, updated_at, last_seen)
                 VALUES(?,?,?,?,?,?,?,0,?,?,?)""",
            (source, source_id, title, body, level, link, meta_s, now, now, last_seen),
        )
        created = cur.rowcount == 1
        if not created:  # already exists
            prev = c.execute(
                "SELECT meta, last_seen FROM notifications WHERE source=? AND source_id IS ?",
                (source, source_id),
            ).fetchone()
            recurred = (
                _cnt(meta) > _cnt(prev["meta"] if prev else "{}")
                or (last_seen and prev and (prev["last_seen"] or "") and last_seen > prev["last_seen"])
            )
            if recurred:  # NEW occurrence → re-surface (unread) + advance last_seen
                c.execute(
                    """UPDATE notifications SET title=?, body=?, level=?, link=?, meta=?,
                         updated_at=?, last_seen=?, is_read=0
                       WHERE source=? AND source_id IS ?""",
                    (title, body, level, link, meta_s, now, last_seen, source, source_id),
                )
            else:  # no NEW occurrence → refresh display + last_seen (authoritative), keep is_read
                c.execute(
                    """UPDATE notifications SET title=?, body=?, level=?, link=?, meta=?, updated_at=?, last_seen=?
                       WHERE source=? AND source_id IS ?""",
                    (title, body, level, link, meta_s, now, last_seen, source, source_id),
                )
        row = c.execute(
            "SELECT id FROM notifications WHERE source=? AND source_id IS ?", (source, source_id)
        ).fetchone()
        return (row["id"] if row else None, created)


# ── background poller: GlitchTip issues → notifications ───────────────────────────
def poll_glitchtip_once():
    """ONE poll cycle.

    Endpoint (GlitchTip mirrors the Sentry API):
        GET {GLITCHTIP_URL}/api/0/organizations/{org}/issues/?query=is:unresolved&sort=new&limit=100
        Authorization: Bearer <GLITCHTIP_API_TOKEN>

    Each issue → create_notification(source='glitchtip-issue', source_id=issue['id']).
    Dedup by issue id means only genuinely-new issues become unread notifications;
    re-seen issues just refresh count/last-seen in `meta`."""
    global _warned_no_token
    if not GLITCHTIP_TOKEN:
        if not _warned_no_token:
            app.logger.warning(
                "poll_glitchtip: GLITCHTIP_API_TOKEN not set — poller idle "
                "(REST API + manual POSTs still work). Set GLITCHTIP_API_TOKEN to enable polling."
            )
            _warned_no_token = True
        return 0
    # An empty org slug would build .../organizations//issues/ and 404 forever, which is exactly
    # the silent-empty-screen failure the old literal "hacohen" default produced on every other
    # company. Say so once, then idle — the same contract as a missing token.
    if not GLITCHTIP_ORG:
        if not _warned_no_token:
            app.logger.warning(
                "poll_glitchtip: GLITCHTIP_ORG not set — poller idle. compose passes it from "
                "GLITCHTIP_ORG_SLUG, which derives from COMPANY_SLUG in .env."
            )
            _warned_no_token = True
        return 0
    url = f"{GLITCHTIP_URL}/api/0/organizations/{GLITCHTIP_ORG}/issues/"
    params = {"query": GLITCHTIP_QUERY, "sort": "-first_seen", "limit": 100}
    headers = {"Authorization": f"Bearer {GLITCHTIP_TOKEN}"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    issues = r.json()
    if not isinstance(issues, list):  # defensive: error payloads are dicts
        raise ValueError(f"unexpected GlitchTip response: {type(issues).__name__}")
    new = 0
    for issue in issues:
        meta = {
            "count": issue.get("count"),
            "shortId": issue.get("shortId"),
            "project": (issue.get("project") or {}).get("slug"),
            "firstSeen": issue.get("firstSeen"),
            "lastSeen": issue.get("lastSeen"),
        }
        _id, created = create_notification(
            SOURCE_GLITCHTIP,
            issue.get("title") or (issue.get("metadata") or {}).get("value") or "שגיאה",
            source_id=str(issue.get("id")),
            body=issue.get("culprit") or "",
            level=(issue.get("level") or "error"),
            link=_fix_link(issue.get("permalink") or ""),
            meta=meta,
        )
        if created:
            new += 1
    return new


def poll_loop():
    """Daemon thread: init, then poll GlitchTip every POLL_INTERVAL seconds. Never crashes
    the process — each cycle is isolated (network/GlitchTip-restart resilient)."""
    init_db()
    while True:
        try:
            n = poll_glitchtip_once()
            # A cycle that returned because there is no token is NOT a healthy cycle — it did no
            # work. poll_glitchtip_once() returns 0 in both cases, so ask the config, not the
            # count; poller_health() reports the token failure and /healthz goes red.
            if GLITCHTIP_TOKEN:
                _record_poll(True)
            if n:
                app.logger.info("poll_glitchtip: %d new notification(s)", n)
        except Exception as e:  # noqa: BLE001 — the LOOP must survive any error…
            # …but the failure must be VISIBLE. Swallowing it kept the process alive and the
            # container "healthy" while every cycle 401'd. Surface it through /healthz.
            _record_poll(False, f"{type(e).__name__}: {e}")
            app.logger.warning("poll_glitchtip failed: %s", e)
        time.sleep(POLL_INTERVAL)


# ── REST API ─────────────────────────────────────────────────────────────────────
# level buckets: GlitchTip/Sentry emit error|fatal|warning|info; we collapse to 3.
_LEVEL_SQL = {
    "error": "lower(coalesce(level,'info')) IN ('error','fatal','critical')",
    "warning": "lower(coalesce(level,'info')) IN ('warning','warn')",
    "info": "lower(coalesce(level,'info')) NOT IN ('error','fatal','critical','warning','warn')",
}


@app.get("/api/notifications")
def list_notifications():
    """List. Query: unread=1, source=<s>, level=error|warning|info, limit=<n>
    (default 100). Newest first."""
    q = "SELECT * FROM notifications"
    where, args = [], []
    if request.args.get("unread") == "1":
        where.append("is_read=0")
    if request.args.get("source"):
        where.append("source=?"); args.append(request.args["source"])
    lvl = (request.args.get("level") or "").lower()
    if lvl in _LEVEL_SQL:
        where.append(_LEVEL_SQL[lvl])
    if where:
        q += " WHERE " + " AND ".join(where)
    # sort by LAST occurrence so a recurring error jumps back to the top, not by first-seen
    q += " ORDER BY COALESCE(last_seen, created_at) DESC, id DESC LIMIT ?"
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    args.append(limit)
    with _db() as c:
        rows = [_row(r) for r in c.execute(q, args).fetchall()]
    return jsonify(notifications=rows, count=len(rows))


@app.get("/api/notifications/<int:nid>")
def get_notification(nid):
    with _db() as c:
        r = c.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
    return (jsonify(_row(r)) if r else (jsonify(error="not_found"), 404))


@app.post("/api/notifications")
def post_notification():
    """Create a notification from ANY source (the extensibility hook). Body:
    {source, title, [source_id, body, level, link, meta]}."""
    b = request.get_json(silent=True) or {}
    if not b.get("source") or not b.get("title"):
        return jsonify(error="source and title required"), 400
    nid, created = create_notification(
        b["source"], b["title"], source_id=b.get("source_id"), body=b.get("body", ""),
        level=b.get("level", "info"), link=b.get("link", ""), meta=b.get("meta"),
    )
    return jsonify(id=nid, created=created), (201 if created else 200)


@app.post("/api/notifications/<int:nid>/read")
def mark_read(nid):
    """Mark read (default) or unread ({read:false})."""
    read = 0 if (request.get_json(silent=True) or {}).get("read") is False else 1
    with _db() as c:
        cur = c.execute(
            "UPDATE notifications SET is_read=?, updated_at=? WHERE id=?", (read, _now(), nid)
        )
    if cur.rowcount == 0:
        return jsonify(error="not_found"), 404
    return jsonify(ok=True, is_read=bool(read))


@app.post("/api/notifications/read-all")
def read_all():
    with _db() as c:
        cur = c.execute("UPDATE notifications SET is_read=1, updated_at=? WHERE is_read=0", (_now(),))
    return jsonify(ok=True, updated=cur.rowcount)


@app.get("/api/notifications/unread-count")
def unread_count():
    with _db() as c:
        n = c.execute("SELECT COUNT(*) n FROM notifications WHERE is_read=0").fetchone()["n"]
    return jsonify(count=n)


def _bucket(level):
    lv = (level or "info").lower()
    if lv in ("error", "fatal", "critical"):
        return "error"
    if lv in ("warning", "warn"):
        return "warning"
    return "info"


@app.get("/api/notifications/stats")
def stats():
    """Aggregate facets for the dashboard KPI strip + filter chips: total, unread,
    counts per level bucket (error/warning/info), and per source. Cheap; UI polls it."""
    with _db() as c:
        rows = c.execute(
            "SELECT source, coalesce(level,'info') level, is_read FROM notifications"
        ).fetchall()
    total = len(rows)
    unread = sum(1 for r in rows if not r["is_read"])
    by_level = {"error": 0, "warning": 0, "info": 0}
    unread_by_level = {"error": 0, "warning": 0, "info": 0}
    by_source = {}
    unread_by_source = {}
    for r in rows:
        b = _bucket(r["level"])
        by_level[b] += 1
        src = r["source"] or "system"
        by_source[src] = by_source.get(src, 0) + 1
        if not r["is_read"]:
            unread_by_level[b] += 1
            unread_by_source[src] = unread_by_source.get(src, 0) + 1
    return jsonify(
        total=total,
        unread=unread,
        by_level=by_level,
        unread_by_level=unread_by_level,
        by_source=by_source,
        unread_by_source=unread_by_source,
    )


@app.delete("/api/notifications/<int:nid>")
def delete_notification(nid):
    """Dismiss a single notification. NOTE: a still-unresolved GlitchTip issue will be
    re-created on the next poll (dedupe by source_id) — that's intended (the error is
    still live); permanent removal = resolve it in GlitchTip."""
    with _db() as c:
        cur = c.execute("DELETE FROM notifications WHERE id=?", (nid,))
    if cur.rowcount == 0:
        return jsonify(error="not_found"), 404
    return jsonify(ok=True)


@app.post("/api/notifications/clear-read")
def clear_read():
    """Bulk-dismiss every already-read notification (declutter). Unread are kept."""
    with _db() as c:
        cur = c.execute("DELETE FROM notifications WHERE is_read=1")
    return jsonify(ok=True, deleted=cur.rowcount)


@app.get("/healthz")
def healthz():
    """RED (503) whenever this service cannot do its job.

    Health = storage readable AND the GlitchTip poller actually polling. It previously
    returned {"ok":true,"token":false} with HTTP 200 — reporting its own blindness in a field
    while telling Docker it was fine. A check that cannot fail is not a check: if we cannot see
    issues, nothing downstream can, and the only honest answer is 503."""
    db_ok = True
    try:
        with _db() as c:
            c.execute("SELECT 1 FROM notifications LIMIT 1")
    except Exception:
        db_ok = False
    poll_ok, poll_detail = poller_health()
    ok = db_ok and poll_ok
    status = 200 if ok else 503
    return jsonify(
        ok=ok,
        token=bool(GLITCHTIP_TOKEN),
        db=db_ok,
        poller=poll_ok,
        detail=poll_detail if not ok else "ok",
    ), status


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# Start the poller exactly once. Under gunicorn this is invoked from post_worker_init
# with a SINGLE worker, so only one poll loop ever runs (no dedupe race).
def start_poller():
    threading.Thread(target=poll_loop, name="glitchtip-poller", daemon=True).start()


# Ensure the schema exists as soon as the module is imported (gunicorn worker import,
# or `python app.py`) so the REST API is usable before the first poll cycle.
try:
    init_db()
except Exception as e:  # pragma: no cover — never block startup on a transient FS error
    app.logger.warning("init_db at import failed (will retry in poller): %s", e)


if __name__ == "__main__":
    start_poller()
    app.run("0.0.0.0", int(os.getenv("PORT", "8977")))
