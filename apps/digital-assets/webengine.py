# Lifted from apps/domains/webengine.py — ai/context/web-engine.md marks it "generic (lift as-is)". The only
# edits are the logger name and (webengine) the env names of the DB path. Keep the two copies in step.
"""webengine — the generic engine behind every screen that depends on a SLOW source.

The problem this file solves, stated once
-----------------------------------------
Some of the office's data comes back in two seconds and some in forty: a provider's HTTP API answers
fast, a browser driving a registrar's panel does not, and the registry's WHOIS is a shared service
we deliberately query rarely. A screen that waits for the slowest of them is a screen nobody uses,
and a screen that shows nothing while it waits is a screen nobody trusts.

So every slow read and every slow action goes through this module, which gives the app three
properties it cannot get from plain request/response:

  1. **A read never blocks.** `get()` answers from the cache immediately — however old it is, and it
     says how old — and refreshes in the BACKGROUND. That is stale-while-revalidate, and it is why
     the domains screen paints at once even when the panel takes 40 seconds.
  2. **An action is a JOB, not a request.** Anything that can take longer than a user's patience is
     submitted, returns an id, and reports progress while it runs; the UI subscribes and shows the
     steps. Nothing hangs on an HTTP connection hoping.
  3. **Change is announced, not polled.** When a job finishes (or a write invalidates something),
     the engine publishes the KEY it invalidated; open screens refresh exactly that and nothing else.

Deliberately small: one SQLite database, one worker pool inside the same process, one in-process
event bus. No Redis, no broker, no scheduler service. The platform is a single small host; the point
of this file is to give every app the *behaviour* of a job system without the machinery of one.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("webengine")

#: The cache and the job log live in the app's OWN volume, not next to the code: a rebuild must not
#: throw away the answer to "what did we already fetch", and a container filesystem is not storage.
DB_PATH = Path(os.environ.get("WEBENGINE_DB")
               or (Path(os.environ.get("APP_STATE_DIR", "/data")) / "webengine.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
  key        TEXT PRIMARY KEY,
  payload    TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  ttl        INTEGER NOT NULL DEFAULT 60,
  state      TEXT NOT NULL DEFAULT 'ok',      -- ok | error
  error      TEXT,
  meta       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS jobs (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT '',
  params     TEXT NOT NULL DEFAULT '{}',
  state      TEXT NOT NULL DEFAULT 'queued',  -- queued | running | ok | error | cancelled
  progress   INTEGER NOT NULL DEFAULT 0,
  message    TEXT NOT NULL DEFAULT '',
  result     TEXT,
  error      TEXT,
  log        TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  ended_at   INTEGER,
  invalidates TEXT NOT NULL DEFAULT '[]',
  client     TEXT NOT NULL DEFAULT '',         -- the caller's idempotency token (see submit)
  error_kind TEXT                              -- the exception's class name, for the log only
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created_at);
CREATE INDEX IF NOT EXISTS jobs_client ON jobs(client, state);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=20, isolation_level=None,
                            check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=20000")
        _local.c = c
    return c


def init() -> None:
    conn().executescript(SCHEMA)
    # A column added after the first release: `CREATE TABLE IF NOT EXISTS` will not give it to a
    # database that already exists, so the migration is explicit and idempotent.
    cols = {r["name"] for r in conn().execute("PRAGMA table_info(jobs)").fetchall()}
    if "client" not in cols:
        conn().execute("ALTER TABLE jobs ADD COLUMN client TEXT NOT NULL DEFAULT ''")
    if "error_kind" not in cols:
        conn().execute("ALTER TABLE jobs ADD COLUMN error_kind TEXT")
    # A job that was running when the process died cannot be resumed — say so instead of leaving it
    # "running" forever, which reads to the user as a screen that will never finish.
    conn().execute("UPDATE jobs SET state='error', ended_at=?, "
                   "error='העבודה הופסקה (האפליקציה הופעלה מחדש)' WHERE state IN ('queued','running')",
                   (now(),))


def now() -> int:
    return int(time.time())


# ── the event bus: one process, every open screen ────────────────────────────────────────────────
_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _sub_lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _sub_lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(event: dict) -> None:
    event = {**event, "at": now()}
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


# ── resources: read fast, refresh behind ─────────────────────────────────────────────────────────
#: One version per key, bumped by every write. A background refresh that started BEFORE a newer value
#: landed must not overwrite it — that is how a 40-second panel read comes back and clobbers the
#: fresh answer somebody just fetched by hand, leaving the screen "correct" and wrong.
_versions: dict[str, int] = {}
_versions_lock = threading.Lock()


def version(key: str) -> int:
    with _versions_lock:
        return _versions.get(key, 0)


def put(key: str, payload: Any, ttl: int = 60, meta: dict | None = None,
        state: str = "ok", error: str | None = None) -> None:
    with _versions_lock:
        _versions[key] = _versions.get(key, 0) + 1
    conn().execute(
        "INSERT INTO resources (key, payload, fetched_at, ttl, state, error, meta) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
        "fetched_at=excluded.fetched_at, ttl=excluded.ttl, state=excluded.state, "
        "error=excluded.error, meta=excluded.meta",
        (key, json.dumps(payload, ensure_ascii=False), now(), int(ttl), state, error,
         json.dumps(meta or {}, ensure_ascii=False)))
    publish({"type": "resource", "key": key})


def peek(key: str) -> dict | None:
    r = conn().execute("SELECT * FROM resources WHERE key=?", (key,)).fetchone()
    if not r:
        return None
    try:
        payload = json.loads(r["payload"])
    except ValueError:
        payload = None
    return {"key": r["key"], "value": payload, "fetched_at": r["fetched_at"],
            "ttl": r["ttl"], "age": now() - r["fetched_at"],
            "stale": (now() - r["fetched_at"]) > r["ttl"], "state": r["state"],
            "error": r["error"], "meta": json.loads(r["meta"] or "{}")}


def invalidate(prefix: str = "") -> None:
    """Drop cached resources whose key starts with `prefix`, and tell every open screen."""
    if prefix:
        conn().execute("DELETE FROM resources WHERE key LIKE ?", (prefix + "%",))
    else:
        conn().execute("DELETE FROM resources")
    publish({"type": "invalidate", "prefix": prefix})


#: keys currently being refreshed, so ten open screens cause ONE fetch, not ten.
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


def get(key: str, loader: Callable[[], Any], ttl: int = 60, force: bool = False,
        want: str = "fresh") -> dict:
    """The read path every screen uses.

    `want="cache"`  → answer from the cache, whatever its age, and refresh behind (never blocks).
    `want="fresh"`  → if the cache is stale, fetch synchronously; otherwise answer at once.
                      This is what a "refresh" button and a first-ever load use.
    """
    hit = peek(key)
    if hit and not force and not hit["stale"]:
        return {**hit, "refreshing": False}
    if hit and not force and want == "cache":
        _refresh_async(key, loader, ttl)
        return {**hit, "refreshing": key in _inflight}
    if hit and not force and want != "fresh":
        return {**hit, "refreshing": False}
    if not force and hit and not hit["stale"]:
        return {**hit, "refreshing": False}
    # a synchronous fetch, but only ONE of them at a time per key
    with _inflight_lock:
        ev = _inflight.get(key)
        mine = ev is None
        if mine:
            ev = _inflight[key] = threading.Event()
    if not mine:
        ev.wait(timeout=120)                       # somebody else is already fetching this
        return {**(peek(key) or {"value": None, "age": 0, "stale": True}), "refreshing": False}
    started = version(key)
    try:
        value = loader()
        if version(key) != started:
            log.info("dropped a stale load for %s: a newer value landed while it ran", key)
            return {**(peek(key) or {}), "refreshing": False, "superseded": True}
        put(key, value, ttl)
        return {**(peek(key) or {}), "refreshing": False}
    except Exception as e:                          # noqa: BLE001 — a failed refresh is data too
        log.warning("loader failed for %s: %s: %s", key, type(e).__name__, e)
        put(key, (hit or {}).get("value"), ttl, state="error", error=f"{type(e).__name__}: {e}")
        out = peek(key) or {"value": None, "age": 0, "stale": True}
        return {**out, "refreshing": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        ev.set()


def _refresh_async(key: str, loader: Callable[[], Any], ttl: int) -> None:
    with _inflight_lock:
        if key in _inflight:
            return
        ev = _inflight[key] = threading.Event()
    started = version(key)

    def run():
        try:
            value = loader()
            if version(key) != started:
                log.info("dropped a stale background load for %s", key)
                return
            put(key, value, ttl)
        except Exception as e:                      # noqa: BLE001
            log.info("background refresh failed for %s: %s", key, type(e).__name__)
            put(key, (peek(key) or {}).get("value"), ttl, state="error",
                error=f"{type(e).__name__}: {e}")
        finally:
            with _inflight_lock:
                _inflight.pop(key, None)
            ev.set()

    threading.Thread(target=run, daemon=True, name=f"refresh-{key[:40]}").start()


# ── jobs: an action that takes as long as it takes ───────────────────────────────────────────────
def submit(name: str, fn: Callable[..., Any], params: dict | None = None, title: str = "",
           invalidates: list[str] | None = None, client: str | None = None) -> dict:
    """Queue one action. `fn(progress, params)` runs on a worker; `progress(pct, message)` reports.

    `client` is the caller's IDEMPOTENCY TOKEN — one value per intended action, generated by the
    screen that asked for it. A double-click, a retried request or a refreshed page that re-sends the
    same intent then joins the job that is already queued instead of starting a second one. That
    matters here more than usual: the slow door is a browser driving a registrar's panel, and two
    concurrent panel writes are not a performance problem, they are a correctness one.
    """
    params = params or {}
    if client:
        row = conn().execute(
            "SELECT id FROM jobs WHERE client=? AND name=? AND params=? "
            "AND state IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
            (str(client), name, json.dumps(params, ensure_ascii=False))).fetchone()
        if row:
            existing = job(row["id"]) or {}
            return {**existing, "deduped": True}
    jid = uuid.uuid4().hex[:12]
    conn().execute(
        "INSERT INTO jobs (id, name, title, params, state, created_at, invalidates, client) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (jid, name, title or name, json.dumps(params, ensure_ascii=False), "queued", now(),
         json.dumps(invalidates or [], ensure_ascii=False), str(client or "")))
    publish({"type": "job", "id": jid, "state": "queued", "name": name, "title": title})
    _work.put((jid, fn, params))
    return job(jid)


def job(jid: str) -> dict | None:
    r = conn().execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d.setdefault("error_kind", None)
    for k in ("params", "result", "log", "invalidates"):
        try:
            d[k] = json.loads(d[k]) if d[k] else ({} if k == "params" else [])
        except ValueError:
            d[k] = {} if k == "params" else []
    d["age"] = now() - d["created_at"]
    d["elapsed"] = (d["ended_at"] or now()) - (d["started_at"] or d["created_at"])
    return d


def jobs(limit: int = 25, active_only: bool = False) -> list[dict]:
    q = "SELECT id FROM jobs"
    if active_only:
        q += " WHERE state IN ('queued','running')"
    q += " ORDER BY created_at DESC LIMIT ?"
    return [job(r["id"]) for r in conn().execute(q, (limit,)).fetchall()]


def cancel(jid: str) -> dict | None:
    """Mark a queued job cancelled. A job already running is asked to stop at its next progress
    callback (the runner checks `state` — a browser mid-navigation cannot be interrupted politely)."""
    conn().execute("UPDATE jobs SET state='cancelled', ended_at=? WHERE id=? AND state='queued'",
                   (now(), jid))
    publish({"type": "job", "id": jid, "state": "cancelled"})
    return job(jid)


def _progress(jid: str):
    def report(pct: int | float, message: str = "") -> None:
        cur = conn().execute("SELECT state, log FROM jobs WHERE id=?", (jid,)).fetchone()
        if not cur or cur["state"] == "cancelled":
            raise JobCancelled()
        try:
            entries = json.loads(cur["log"] or "[]")
        except ValueError:
            entries = []
        entries = (entries + [{"at": now(), "pct": int(pct), "message": message}])[-60:]
        conn().execute("UPDATE jobs SET progress=?, message=?, log=? WHERE id=?",
                       (int(pct), message, json.dumps(entries, ensure_ascii=False), jid))
        publish({"type": "job", "id": jid, "state": "running", "progress": int(pct),
                 "message": message})
    return report


class JobCancelled(Exception):
    pass


_work: queue.Queue = queue.Queue()


def _worker(n: int) -> None:
    while True:
        jid, fn, params = _work.get()
        try:
            row = conn().execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row or row["state"] == "cancelled":
                continue
            conn().execute("UPDATE jobs SET state='running', started_at=? WHERE id=?",
                           (now(), jid))
            publish({"type": "job", "id": jid, "state": "running", "progress": 0,
                     "message": "מתחיל"})
            result = fn(_progress(jid), params)
            row = conn().execute("SELECT invalidates FROM jobs WHERE id=?", (jid,)).fetchone()
            keys = json.loads((row or {})["invalidates"] or "[]") if row else []
            conn().execute("UPDATE jobs SET state='ok', progress=100, ended_at=?, result=? "
                           "WHERE id=?",
                           (now(), json.dumps(result, ensure_ascii=False, default=str), jid))
            for k in keys:
                invalidate(k)
            publish({"type": "job", "id": jid, "state": "ok", "progress": 100,
                     "message": "הושלם"})
        except JobCancelled:
            conn().execute("UPDATE jobs SET state='cancelled', ended_at=? WHERE id=?", (now(), jid))
            publish({"type": "job", "id": jid, "state": "cancelled"})
        except Exception as e:                      # noqa: BLE001
            log.warning("job %s failed: %s", jid, traceback.format_exc(limit=3))
            # WHAT THE OWNER READS, and what they don't: a `DomainError` already carries a Hebrew
            # sentence written for a person, and prefixing it with the exception's class name is how
            # "DomainError: …draft…" ended up in a dialog box. The class name is still kept, in
            # `error_kind`, for the log and for anyone debugging — just not in front of the owner.
            message = getattr(e, "he_message", None) or str(e)
            kind = type(e).__name__
            # A refusal that knows WHY and WHAT TO DO carries that with it (`body()`), so the screen
            # can show the same three lines the synchronous path shows instead of one bare sentence.
            meta = None
            body = getattr(e, "body", None)
            if callable(body):
                try:
                    meta = body()
                except Exception:                            # noqa: BLE001
                    meta = None
            conn().execute("UPDATE jobs SET state='error', ended_at=?, error=?, error_kind=?, "
                           "result=? WHERE id=?",
                           (now(), message, kind,
                            json.dumps({"error_body": meta}, ensure_ascii=False) if meta else None,
                            jid))
            publish({"type": "job", "id": jid, "state": "error", "message": message,
                     "error": message, "error_kind": kind, "result": {"error_body": meta}})
        finally:
            _work.task_done()


def start_workers(n: int = 2) -> None:
    for i in range(max(1, n)):
        threading.Thread(target=_worker, args=(i,), daemon=True, name=f"webengine-{i}").start()
    log.info("webengine started (%s workers)", n)
