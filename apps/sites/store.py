"""sites.store — the office's sites, their samples and their findings, in ONE sqlite file.

Why a private store and not the shared `sql` capability
------------------------------------------------------
Everything in here is high-frequency, self-pruning and meaningless outside this app: a 60-second
uptime sample per site, an hourly visit counter, the findings of last night's scan. Putting that in
the platform's Postgres would buy nothing (no other app may read it — it is this service's own
model, the way `drive`'s tables are drive's) and would cost a hard dependency on a database for an
app whose whole job is to tell you when something is DOWN. An app that watches your sites must not
be the app that fails because a database it does not need is unreachable.

The file lives in `sites_state` (declared in app.json), so `bbox data backup` covers it and
reinstalling the app does not lose the history.

Two nouns, and they are deliberately different
----------------------------------------------
* a **site** — a ROW here. It is a description: which machine, which hostnames, where its stack
  lives on that machine, how it is served. The machine itself is NOT a row here: it is a connection
  instance in the credential plane, owned by the `computers` service, and this table only ever
  holds its id (see machines.py).
* a **run** — one execution of one check, with its findings. History is kept, because "the score
  dropped" is only visible against the previous run, and because a scan that ran and found nothing
  must be distinguishable from a scan that never ran.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("SITES_STATE_DIR", "/data"))
DB_PATH = Path(os.environ.get("SITES_DB", str(STATE_DIR / "sites.db")))

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
  id            TEXT PRIMARY KEY,
  label         TEXT NOT NULL,
  enabled       INTEGER NOT NULL DEFAULT 1,
  monitor       INTEGER NOT NULL DEFAULT 1,
  machine       TEXT NOT NULL,
  hosts         TEXT NOT NULL DEFAULT '[]',      -- JSON list; hosts[0] is canonical
  kind          TEXT NOT NULL DEFAULT 'static',  -- static | static-built | proxy
  root          TEXT NOT NULL,                   -- deploy dir ON THE MACHINE
  project       TEXT NOT NULL,                   -- docker compose project name on the machine
  port          INTEGER NOT NULL DEFAULT 80,     -- port the site's web container listens on
  health_path   TEXT NOT NULL DEFAULT '/',
  content       TEXT NOT NULL DEFAULT '{}',      -- JSON: how the content gets there
  edge          TEXT NOT NULL DEFAULT '{}',      -- JSON: how it is published (traefik/net/middlewares)
  public        TEXT NOT NULL DEFAULT '{}',      -- JSON: the PUBLIC PATH — who serves the site
                                                 --       (container | office) and on which
                                                 --       {domain, path} entries. See public.py
  legacy        TEXT NOT NULL DEFAULT '{}',      -- JSON: the stack this site had BEFORE the office
                                                 --       ran it (adoption), so a migration can
                                                 --       switch it off and a rollback can switch
                                                 --       it back on
  source        TEXT NOT NULL DEFAULT 'office',  -- office | adopted | external
  checks        TEXT NOT NULL DEFAULT '{}',      -- JSON: per-site thresholds (beauty_min, seo_pages,
                                                 --       deep, scan_hour) — the owner's knobs, kept
                                                 --       next to the site they belong to
  notes         TEXT NOT NULL DEFAULT '',
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  last_state    TEXT,                            -- up | down | unknown
  last_checked  INTEGER,
  last_error    TEXT
);

-- one row per uptime check. Kept at 1-minute resolution and pruned, because a chart needs shape,
-- not an archive: the raw HTTP evidence of three weeks ago has no reader.
CREATE TABLE IF NOT EXISTS samples (
  site_id TEXT NOT NULL, ts INTEGER NOT NULL,
  ok INTEGER NOT NULL, status INTEGER, ms INTEGER, error TEXT, url TEXT
);
CREATE INDEX IF NOT EXISTS samples_site_ts ON samples(site_id, ts);

-- visits are AGGREGATED AT INGEST, hourly: a busy site produces millions of lines and the office
-- needs the shape (when, how many, from where, to which page), never the individual line.
CREATE TABLE IF NOT EXISTS visits (
  site_id TEXT NOT NULL, hour INTEGER NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0, uniques INTEGER NOT NULL DEFAULT 0,
  bots INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
  bytes INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS visits_key ON visits(site_id, hour);
CREATE TABLE IF NOT EXISTS visit_paths (site_id TEXT, hour INTEGER, path TEXT, hits INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS visit_paths_key ON visit_paths(site_id, hour, path);
CREATE TABLE IF NOT EXISTS visit_refs (site_id TEXT, hour INTEGER, ref TEXT, hits INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS visit_refs_key ON visit_refs(site_id, hour, ref);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id TEXT NOT NULL, check_name TEXT NOT NULL,   -- NOT `check`: a SQLite keyword (CHECK)
  started_at INTEGER NOT NULL, finished_at INTEGER,
  state TEXT NOT NULL DEFAULT 'running',        -- running | ok | warn | error
  summary TEXT NOT NULL DEFAULT '{}',
  error TEXT
);
CREATE INDEX IF NOT EXISTS runs_site ON runs(site_id, started_at);

-- a finding is keyed by (site, check, code, url) so a re-run UPDATES it instead of appending a
-- duplicate: "still broken" and "broken again" are different facts and the UI must show the first.
CREATE TABLE IF NOT EXISTS findings (
  site_id TEXT NOT NULL, check_name TEXT NOT NULL, code TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL,                       -- error | warn | info | ok
  title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', fix TEXT NOT NULL DEFAULT '',
  first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, resolved_at INTEGER,
  PRIMARY KEY (site_id, check_name, code, url)
);
CREATE INDEX IF NOT EXISTS findings_site ON findings(site_id, resolved_at, severity);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id TEXT, ts INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_site ON events(site_id, ts);

-- per-site cursors: the byte offset of the last access-log line ingested, the last scan time, …
CREATE TABLE IF NOT EXISTS cursors (site_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS cursors_key ON cursors(site_id, key);
"""


def conn() -> sqlite3.Connection:
    """One connection per thread (the scheduler has its own), WAL, foreign keys off by design."""
    c = getattr(_local, "c", None)
    if c is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=15000")
        _local.c = c
    return c


#: Columns added to `sites` AFTER the table shipped. `CREATE TABLE IF NOT EXISTS` never touches an
#: existing table, so a database that predates a column would fail every write with "no such column"
#: — while looking perfectly healthy on read. Each entry is added only when it is missing.
MIGRATIONS = (("sites", "public", "TEXT NOT NULL DEFAULT '{}'"),)


def init() -> None:
    c = conn()
    c.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def now() -> int:
    return int(time.time())


def _row(r) -> dict | None:
    return dict(r) if r is not None else None


# ── sites ────────────────────────────────────────────────────────────────────────────────────────
SITE_JSON_FIELDS = ("hosts", "content", "edge", "legacy", "checks", "public")


def _decode(row: dict) -> dict:
    for f in SITE_JSON_FIELDS:
        try:
            row[f] = json.loads(row.get(f) or ("[]" if f == "hosts" else "{}"))
        except ValueError:
            row[f] = [] if f == "hosts" else {}
    row["enabled"] = bool(row.get("enabled"))
    row["monitor"] = bool(row.get("monitor"))
    return row


def list_sites(enabled_only: bool = False) -> list[dict]:
    q = "SELECT * FROM sites"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY label"
    return [_decode(_row(r)) for r in conn().execute(q).fetchall()]


def get_site(sid: str) -> dict | None:
    r = conn().execute("SELECT * FROM sites WHERE id=?", (sid,)).fetchone()
    return _decode(_row(r)) if r else None


def upsert_site(s: dict) -> dict:
    """Insert or update. `id` is the caller's slug and the primary key — two rows for one site is
    the failure this table exists to prevent, so there is no path that creates a second one."""
    c = conn()
    existing = get_site(s["id"])
    ts = now()
    row = {
        "id": s["id"], "label": s.get("label") or s["id"],
        "enabled": 1 if s.get("enabled", True) else 0,
        "monitor": 1 if s.get("monitor", True) else 0,
        "machine": s.get("machine") or "", "hosts": json.dumps(s.get("hosts") or []),
        "kind": s.get("kind") or "static", "root": s.get("root") or "",
        "project": s.get("project") or f"site-{s['id']}", "port": int(s.get("port") or 80),
        "health_path": s.get("health_path") or "/",
        "content": json.dumps(s.get("content") or {}),
        "edge": json.dumps(s.get("edge") or {}),
        "public": json.dumps(s.get("public") or (existing or {}).get("public") or {}),
        "legacy": json.dumps(s.get("legacy") or (existing or {}).get("legacy") or {}),
        "checks": json.dumps(s.get("checks") or (existing or {}).get("checks") or {}),
        "source": s.get("source") or (existing or {}).get("source") or "office",
        "notes": s.get("notes") or "",
        "created_at": (existing or {}).get("created_at") or ts, "updated_at": ts,
    }
    cols = ", ".join(row)
    conn().execute(
        f"INSERT INTO sites ({cols}) VALUES ({', '.join('?' * len(row))}) "
        f"ON CONFLICT(id) DO UPDATE SET "
        + ", ".join(f"{k}=excluded.{k}" for k in row if k != "id"),
        list(row.values()))
    return get_site(s["id"])


def delete_site(sid: str) -> None:
    c = conn()
    for t in ("samples", "visits", "visit_paths", "visit_refs", "runs", "findings", "events",
              "cursors"):
        c.execute(f"DELETE FROM {t} WHERE site_id=?", (sid,))
    c.execute("DELETE FROM sites WHERE id=?", (sid,))


def set_state(sid: str, state: str, error: str | None = None) -> None:
    conn().execute("UPDATE sites SET last_state=?, last_checked=?, last_error=? WHERE id=?",
                   (state, now(), error, sid))


def event(sid: str | None, kind: str, message: str, meta: dict | None = None) -> None:
    conn().execute("INSERT INTO events (site_id, ts, kind, message, meta) VALUES (?,?,?,?,?)",
                   (sid, now(), kind, message, json.dumps(meta or {}, ensure_ascii=False)))


def recent_events(sid: str | None = None, limit: int = 50) -> list[dict]:
    if sid:
        rows = conn().execute("SELECT * FROM events WHERE site_id=? ORDER BY ts DESC LIMIT ?",
                              (sid, limit)).fetchall()
    else:
        rows = conn().execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


# ── samples ──────────────────────────────────────────────────────────────────────────────────────
def add_sample(sid: str, ok: bool, status: int | None, ms: int | None, error: str | None,
               url: str | None) -> None:
    conn().execute("INSERT INTO samples (site_id, ts, ok, status, ms, error, url) "
                   "VALUES (?,?,?,?,?,?,?)", (sid, now(), 1 if ok else 0, status, ms, error, url))


def samples(sid: str, hours: int = 24, limit: int = 5000) -> list[dict]:
    since = now() - hours * 3600
    rows = conn().execute("SELECT ts, ok, status, ms, error, url FROM samples "
                          "WHERE site_id=? AND ts>=? ORDER BY ts", (sid, since)).fetchall()
    return [_row(r) for r in rows][-limit:]


def uptime_summary(sid: str, hours: int = 24) -> dict:
    """Uptime over a window, computed from the SAMPLES rather than from an average of averages: a
    watch that stops sampling (the office being down) must not read as 100%."""
    since = now() - hours * 3600
    r = conn().execute(
        "SELECT COUNT(*) n, SUM(ok) up, AVG(CASE WHEN ok=1 THEN ms END) ms, MAX(ts) last "
        "FROM samples WHERE site_id=? AND ts>=?", (sid, since)).fetchone()
    n, up = (r["n"] or 0), (r["up"] or 0)
    return {"samples": n, "up": up, "down": n - up,
            "uptime_pct": round(up * 100.0 / n, 2) if n else None,
            "avg_ms": int(r["ms"]) if r["ms"] else None, "window_hours": hours,
            "last_sample": r["last"]}


def prune_samples(days: int = 30) -> None:
    conn().execute("DELETE FROM samples WHERE ts < ?", (now() - days * 86400,))


# ── visits ───────────────────────────────────────────────────────────────────────────────────────
def add_visit_hour(sid: str, hour: int, hits: int, uniques: int, bots: int, errors: int,
                   nbytes: int, paths: dict[str, int], refs: dict[str, int]) -> None:
    c = conn()
    for table, extra in (("visit_paths", paths), ("visit_refs", refs)):
        col = "path" if table == "visit_paths" else "ref"
        for key, n in extra.items():
            c.execute(f"INSERT INTO {table} (site_id, hour, {col}, hits) VALUES (?,?,?,?) "
                      f"ON CONFLICT(site_id, hour, {col}) DO UPDATE SET hits=hits+excluded.hits",
                      (sid, hour, key[:200], n))
    c.execute("INSERT INTO visits (site_id, hour, hits, uniques, bots, errors, bytes) "
              "VALUES (?,?,?,?,?,?,?) ON CONFLICT(site_id, hour) DO UPDATE SET "
              "hits=hits+excluded.hits, uniques=uniques+excluded.uniques, bots=bots+excluded.bots, "
              "errors=errors+excluded.errors, bytes=bytes+excluded.bytes",
              (sid, hour, hits, uniques, bots, errors, nbytes))


def visit_series(sid: str, days: int = 7) -> list[dict]:
    since = now() - days * 86400
    rows = conn().execute("SELECT * FROM visits WHERE site_id=? AND hour>=? ORDER BY hour",
                          (sid, since)).fetchall()
    return [_row(r) for r in rows]


def top_paths(sid: str, days: int = 7, limit: int = 15) -> list[dict]:
    since = now() - days * 86400
    rows = conn().execute("SELECT path, SUM(hits) hits FROM visit_paths WHERE site_id=? AND hour>=? "
                          "GROUP BY path ORDER BY hits DESC LIMIT ?", (sid, since, limit)).fetchall()
    return [_row(r) for r in rows]


def top_refs(sid: str, days: int = 7, limit: int = 10) -> list[dict]:
    since = now() - days * 86400
    rows = conn().execute("SELECT ref, SUM(hits) hits FROM visit_refs WHERE site_id=? AND hour>=? "
                          "GROUP BY ref ORDER BY hits DESC LIMIT ?", (sid, since, limit)).fetchall()
    return [_row(r) for r in rows]


def visits_total(sid: str, days: int = 7) -> dict:
    since = now() - days * 86400
    r = conn().execute("SELECT SUM(hits) hits, SUM(uniques) uniques, SUM(bots) bots, "
                       "SUM(errors) errors, SUM(bytes) bytes FROM visits "
                       "WHERE site_id=? AND hour>=?", (sid, since)).fetchone()
    return {"hits": r["hits"] or 0, "uniques": r["uniques"] or 0, "bots": r["bots"] or 0,
            "errors": r["errors"] or 0, "bytes": r["bytes"] or 0, "days": days}


# ── runs and findings ────────────────────────────────────────────────────────────────────────────
def start_run(sid: str, check: str) -> int:
    cur = conn().execute("INSERT INTO runs (site_id, check_name, started_at) VALUES (?,?,?)",
                         (sid, check, now()))
    return int(cur.lastrowid)


def finish_run(run_id: int, state: str, summary: dict | None = None, error: str | None = None) -> None:
    conn().execute("UPDATE runs SET finished_at=?, state=?, summary=?, error=? WHERE id=?",
                   (now(), state, json.dumps(summary or {}, ensure_ascii=False), error, run_id))


def last_run(sid: str, check: str | None = None) -> dict | None:
    q = "SELECT *, check_name AS \"check\" FROM runs WHERE site_id=?"
    args: list = [sid]
    if check:
        q += " AND check_name=?"
        args.append(check)
    q += " ORDER BY started_at DESC, id DESC LIMIT 1"
    r = conn().execute(q, args).fetchone()
    if not r:
        return None
    out = _row(r)
    try:
        out["summary"] = json.loads(out.get("summary") or "{}")
    except ValueError:
        out["summary"] = {}
    return out


def runs(sid: str, limit: int = 30) -> list[dict]:
    rows = conn().execute("SELECT *, check_name AS \"check\" FROM runs WHERE site_id=? "
                          "ORDER BY started_at DESC LIMIT ?",
                          (sid, limit)).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        try:
            d["summary"] = json.loads(d.get("summary") or "{}")
        except ValueError:
            d["summary"] = {}
        out.append(d)
    return out


def record_findings(sid: str, check: str, findings: list[dict]) -> dict:
    """Upsert this run's findings and RESOLVE the ones that no longer appear.

    The resolution half is the point. A linter that only ever adds rows turns yesterday's fixed
    warning into a permanent red dot, and the owner learns to ignore the list — which is the same
    as having no linter. Anything from this check that this run did not report is marked resolved
    rather than deleted, so "it was broken for six days" stays answerable.
    """
    c = conn()
    ts = now()
    seen: list[tuple] = []
    counts = {"error": 0, "warn": 0, "info": 0, "ok": 0}
    for f in findings:
        sev = f.get("severity") or "info"
        counts[sev] = counts.get(sev, 0) + 1
        key = (f.get("code") or "finding", f.get("url") or "")
        seen.append(key)
        c.execute(
            "INSERT INTO findings (site_id, check_name, code, url, severity, title, detail, fix, "
            "first_seen, last_seen, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,NULL) "
            "ON CONFLICT(site_id, check_name, code, url) DO UPDATE SET "
            "severity=excluded.severity, title=excluded.title, detail=excluded.detail, "
            "fix=excluded.fix, last_seen=excluded.last_seen, resolved_at=NULL",
            (sid, check, key[0][:120], key[1][:400], sev, f.get("title") or key[0],
             f.get("detail") or "", f.get("fix") or "", ts, ts))
    rows = c.execute("SELECT code, url FROM findings WHERE site_id=? AND check_name=? AND "
                     "resolved_at IS NULL", (sid, check)).fetchall()
    stale = [(r["code"], r["url"]) for r in rows if (r["code"], r["url"]) not in seen]
    for code, url in stale:
        c.execute("UPDATE findings SET resolved_at=? WHERE site_id=? AND check_name=? AND code=? "
                  "AND url=?", (ts, sid, check, code, url))
    return {**counts, "resolved": len(stale)}


def findings(sid: str, include_resolved: bool = False) -> list[dict]:
    q = "SELECT *, check_name AS \"check\" FROM findings WHERE site_id=?"
    if not include_resolved:
        q += " AND resolved_at IS NULL"
    q += (" ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 WHEN 'info' THEN 2 "
          "ELSE 3 END, check_name, code")
    return [_row(r) for r in conn().execute(q, (sid,)).fetchall()]


def findings_overview() -> list[dict]:
    """Per site: how many unresolved findings at each severity — the dashboard's whole table."""
    rows = conn().execute(
        "SELECT site_id, severity, COUNT(*) n FROM findings WHERE resolved_at IS NULL "
        "GROUP BY site_id, severity").fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["site_id"], {"error": 0, "warn": 0, "info": 0, "ok": 0})
        out[r["site_id"]][r["severity"]] = r["n"]
    return [{"site_id": k, **v} for k, v in out.items()]


# ── cursors ──────────────────────────────────────────────────────────────────────────────────────
def cursor_get(sid: str, key: str, default: str = "") -> str:
    r = conn().execute("SELECT value FROM cursors WHERE site_id=? AND key=?", (sid, key)).fetchone()
    return (r["value"] if r else default) or default


def cursor_set(sid: str, key: str, value: str) -> None:
    conn().execute("INSERT INTO cursors (site_id, key, value) VALUES (?,?,?) "
                   "ON CONFLICT(site_id, key) DO UPDATE SET value=excluded.value",
                   (sid, key, str(value)))
