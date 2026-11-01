"""domains.registry — the office's own list of domains, and what WHOIS says about each.

Two sources of truth, and they are deliberately different things:

* **the provider** (Cloudflare, GoDaddy, …) is the truth about a ZONE: which records exist, what they
  point at. It is reached through an API and it changes under us.
* **this table** is the truth about what the OFFICE WATCHES: which domains this business cares
  about, when each was last checked, what the registry said, and which site a domain belongs to. It
  exists because a domain is not a zone — a registrar that has no API at all (this office's own,
  Internic) still has to be watched for expiry, and "which domains do I own" must be answerable
  without asking anybody's API.

The expiry date is the reason this table is worth its own store: `.co.il` publishes it over plain
WHOIS on port 43 with no credentials, and a domain that expires is the one failure in this app that
cannot be fixed after it happens.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("DOMAINS_STATE_DIR", "/data"))
DB_PATH = Path(os.environ.get("DOMAINS_DB", str(STATE_DIR / "domains.db")))

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
  name          TEXT PRIMARY KEY,               -- the registrable name, lower-case, no www
  provider      TEXT NOT NULL DEFAULT 'registry',  -- which account/API owns its ZONE
  account       TEXT,                            -- connection id, or NULL for registry-only
  site_id       TEXT,                            -- the office site this domain serves, if any
  registrar     TEXT,
  status        TEXT,                            -- the registry's own words ("Transfer Locked", …)
  expiry        INTEGER,                         -- epoch seconds, as the registry reports it
  registered    INTEGER,
  nameservers   TEXT NOT NULL DEFAULT '[]',
  auto_renew    INTEGER,
  account_hint  TEXT,
  watched       INTEGER NOT NULL DEFAULT 1,
  notes         TEXT NOT NULL DEFAULT '',
  last_whois    INTEGER,
  last_error    TEXT,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT, ts INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_domain ON events(domain, ts);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        _local.c = c
    return c


def init() -> None:
    conn().executescript(SCHEMA)


def now() -> int:
    return int(time.time())


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    if "nameservers" in d:
        try:
            d["nameservers"] = json.loads(d["nameservers"] or "[]")
        except ValueError:
            d["nameservers"] = []
    if "watched" in d:
        d["watched"] = bool(d["watched"])
    if "auto_renew" in d and d["auto_renew"] is not None:
        d["auto_renew"] = bool(d["auto_renew"])
    return d


def list_domains() -> list[dict]:
    return [_row(r) for r in conn().execute("SELECT * FROM domains ORDER BY name").fetchall()]


def get(name: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM domains WHERE name=?", (name.lower().strip(),))
                .fetchone())


def upsert(name: str, **fields) -> dict:
    name = name.lower().strip()
    ts = now()
    existing = get(name) or {}
    row = {
        "name": name,
        "provider": fields.get("provider") or existing.get("provider") or "registry",
        "account": fields.get("account", existing.get("account")),
        "site_id": fields.get("site_id", existing.get("site_id")),
        "registrar": fields.get("registrar", existing.get("registrar")),
        "status": fields.get("status", existing.get("status")),
        "expiry": fields.get("expiry", existing.get("expiry")),
        "registered": fields.get("registered", existing.get("registered")),
        "nameservers": json.dumps(fields.get("nameservers") or existing.get("nameservers") or []),
        "auto_renew": (None if fields.get("auto_renew") is None
                       else (1 if fields["auto_renew"] else 0)),
        "account_hint": fields.get("account_hint", existing.get("account_hint")),
        "watched": 1 if fields.get("watched", existing.get("watched", True)) else 0,
        "notes": fields.get("notes", existing.get("notes") or ""),
        "last_whois": fields.get("last_whois", existing.get("last_whois")),
        "last_error": fields.get("last_error", existing.get("last_error")),
        "created_at": existing.get("created_at") or ts,
        "updated_at": ts,
    }
    cols = ", ".join(row)
    conn().execute(
        f"INSERT INTO domains ({cols}) VALUES ({', '.join('?' * len(row))}) "
        f"ON CONFLICT(name) DO UPDATE SET "
        + ", ".join(f"{k}=excluded.{k}" for k in row if k != "name"),
        list(row.values()))
    return get(name)


def delete(name: str) -> None:
    conn().execute("DELETE FROM domains WHERE name=?", (name.lower().strip(),))
    conn().execute("DELETE FROM events WHERE domain=?", (name.lower().strip(),))


def due_for_whois(hours: float = 12.0) -> list[dict]:
    """Domains never checked, or last checked longer ago than `hours`. Expiry moves slowly and WHOIS
    is a shared public service with a published policy against hammering it — this is a watch, not a
    crawl."""
    cutoff = now() - int(hours * 3600)
    return [_row(r) for r in conn().execute(
        "SELECT * FROM domains WHERE watched=1 AND (last_whois IS NULL OR last_whois < ?) "
        "ORDER BY COALESCE(expiry, 0)", (cutoff,)).fetchall()]


def event(domain: str | None, kind: str, message: str, meta: dict | None = None) -> int:
    """Append one line to the change log and RETURN ITS ID — because the id is what an "undo" button
    points at, and an event you cannot refer to is a log you cannot act on."""
    cur = conn().execute("INSERT INTO events (domain, ts, kind, message, meta) VALUES (?,?,?,?,?)",
                         (domain, now(), kind, message,
                          json.dumps(meta or {}, ensure_ascii=False)))
    return int(cur.lastrowid or 0)


def events(domain: str | None = None, limit: int = 40) -> list[dict]:
    if domain:
        rows = conn().execute("SELECT * FROM events WHERE domain=? ORDER BY ts DESC LIMIT ?",
                              (domain, limit)).fetchall()
    else:
        rows = conn().execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
