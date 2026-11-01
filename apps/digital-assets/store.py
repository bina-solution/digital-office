"""digital-assets.store — the business's digital assets, as ONE small database the app owns.

The nouns, and they are the whole model:

  slot         a named, typed place for one asset of the business: `identity.logo.square`,
               `content.about.story`, `media.launch-day.launch-film.1`. A blueprint creates slots;
               the owner can add their own. A slot knows its constraints (sizes, lengths, formats),
               its brief (what good looks like), and its TARGETS — the channels it shows up on.
  asset        one candidate value for a slot: a text, a colour, a file. A slot collects versions
               (uploaded, made by the office agent, imported) and never forgets them.
  active       the version that IS the business right now, per slot. Changing it is the one act
               that propagates: every target of the slot is planned, and the plan is published.
  channel      a place the business appears: a social account (through social-list), a website
               (through sites), a listing or a printed thing (tracked, updated by hand).
  publication  one (asset → channel field) delivery, with its state and its evidence. The ledger of
               "is the new logo live everywhere?", answered per channel.
  post         one piece of media published to one or more channels.

Files are content-addressed (files.py); rows hold the hash. Nothing here holds a credential: the
accounts behind the channels are social-list's (the vault's), the sites are sites'.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

STATE_DIR = Path(os.environ.get("APP_STATE_DIR", "/data"))
DB_PATH = STATE_DIR / "assets.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots (
  key         TEXT PRIMARY KEY,
  section     TEXT NOT NULL,                 -- identity | content | media
  grp         TEXT NOT NULL DEFAULT '',
  label       TEXT NOT NULL DEFAULT '{}',     -- {he, en}
  kind        TEXT NOT NULL,
  lang        TEXT NOT NULL DEFAULT '',
  constraints TEXT NOT NULL DEFAULT '{}',
  required    INTEGER NOT NULL DEFAULT 0,
  expires     TEXT NOT NULL DEFAULT '',
  targets     TEXT NOT NULL DEFAULT '[]',     -- [{channel, field?}]
  brief       TEXT NOT NULL DEFAULT '{}',
  sources     TEXT NOT NULL DEFAULT '[]',     -- blueprint ids that declared it; [] = the owner's
  plan        TEXT NOT NULL DEFAULT '{}',     -- media timeline: {phase, unit, timing, due, channels, copy}
  ord         INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id          TEXT PRIMARY KEY,
  slot_key    TEXT NOT NULL,
  kind        TEXT NOT NULL,
  title       TEXT NOT NULL DEFAULT '',
  text        TEXT,
  file_sha    TEXT,
  file_ext    TEXT,
  mime        TEXT,
  size        INTEGER,
  width       INTEGER,
  height      INTEGER,
  source      TEXT NOT NULL DEFAULT 'upload', -- upload | agent | import | url
  author      TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'draft',  -- draft | approved | archived
  meta        TEXT NOT NULL DEFAULT '{}',
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_slot ON assets(slot_key, created_at);
CREATE TABLE IF NOT EXISTS active (
  slot_key    TEXT PRIMARY KEY,
  asset_id    TEXT NOT NULL,
  set_at      INTEGER NOT NULL,
  set_by      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS channels (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,                 -- social | website | listing | print
  label       TEXT NOT NULL DEFAULT '{}',
  platform    TEXT,                          -- social-list platform id (social channels)
  account_id  TEXT,                          -- social-list account id
  site_id     TEXT,                          -- sites site id (website channels)
  url         TEXT,
  handle      TEXT,
  lang        TEXT NOT NULL DEFAULT 'he',
  enabled     INTEGER NOT NULL DEFAULT 1,
  core        INTEGER NOT NULL DEFAULT 0,
  ord         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
  id          TEXT PRIMARY KEY,
  slot_key    TEXT NOT NULL,
  asset_id    TEXT NOT NULL,
  actor       TEXT NOT NULL DEFAULT '',
  state       TEXT NOT NULL,                 -- planned | running | done | partial | failed
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
  id          TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  slot_key    TEXT NOT NULL,
  asset_id    TEXT NOT NULL,
  channel_id  TEXT NOT NULL,
  field       TEXT NOT NULL DEFAULT '',
  state       TEXT NOT NULL,                 -- planned|queued|running|ok|needs_owner|failed|skipped
  job_id      TEXT NOT NULL DEFAULT '',
  result      TEXT NOT NULL DEFAULT '{}',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pubs_slot ON publications(slot_key, created_at);
CREATE INDEX IF NOT EXISTS pubs_run ON publications(run_id);
CREATE TABLE IF NOT EXISTS posts (
  id          TEXT PRIMARY KEY,
  slot_key    TEXT,
  asset_ids   TEXT NOT NULL DEFAULT '[]',
  text        TEXT NOT NULL DEFAULT '',
  channels    TEXT NOT NULL DEFAULT '[]',
  state       TEXT NOT NULL,
  results     TEXT NOT NULL DEFAULT '{}',
  actor       TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS applied (
  blueprint_id TEXT PRIMARY KEY,
  version      INTEGER NOT NULL,
  params       TEXT NOT NULL DEFAULT '{}',
  applied_at   INTEGER NOT NULL,
  by           TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  slot_key    TEXT,
  summary     TEXT NOT NULL DEFAULT '',
  actor       TEXT NOT NULL DEFAULT '',
  data        TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS settings (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL
);
"""

JSON_COLS = {"label", "constraints", "targets", "brief", "sources", "plan", "meta", "result",
             "asset_ids", "channels", "results", "params", "data"}

_local = threading.local()
_write_lock = threading.RLock()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=20, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=20000")
        _local.c = c
    return c


def init() -> None:
    conn().executescript(SCHEMA)


def now() -> int:
    return int(time.time())


def new_id(prefix: str = "") -> str:
    return (prefix + "-" if prefix else "") + uuid.uuid4().hex[:10]


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in list(d):
        if k in JSON_COLS and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


# ── settings ─────────────────────────────────────────────────────────────────────────────────────
def setting(key: str, default=None):
    r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value) -> None:
    conn().execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE "
                   "SET value=excluded.value", (key, _j(value)))


# ── slots ────────────────────────────────────────────────────────────────────────────────────────
SLOT_FIELDS = ("section", "grp", "label", "kind", "lang", "constraints", "required", "expires",
               "targets", "brief", "sources", "plan", "ord")


def upsert_slot(s: dict, source: str | None = None) -> dict:
    """Create or refresh a slot from a blueprint declaration. A blueprint that is re-applied
    refreshes the DECLARATION (label, constraints, targets…) and adds itself to `sources`; it never
    touches the slot's assets or its active choice — those are the owner's."""
    with _write_lock:
        cur = get_slot(s["key"])
        t = now()
        if cur:
            sources = list(cur.get("sources") or [])
            if source and source not in sources:
                sources.append(source)
            vals = {k: s.get(k, cur.get(k)) for k in SLOT_FIELDS}
            vals["sources"] = sources
            conn().execute(
                "UPDATE slots SET section=?, grp=?, label=?, kind=?, lang=?, constraints=?, "
                "required=?, expires=?, targets=?, brief=?, sources=?, plan=?, ord=?, updated_at=? "
                "WHERE key=?",
                (vals["section"], vals["grp"] or "", _j(vals["label"] or {}), vals["kind"],
                 vals["lang"] or "", _j(vals["constraints"] or {}), int(bool(vals["required"])),
                 vals["expires"] or "", _j(vals["targets"] or []), _j(vals["brief"] or {}),
                 _j(vals["sources"] or []), _j(vals["plan"] or {}), int(vals["ord"] or 0), t,
                 s["key"]))
        else:
            conn().execute(
                "INSERT INTO slots (key, section, grp, label, kind, lang, constraints, required, "
                "expires, targets, brief, sources, plan, ord, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s["key"], s["section"], s.get("grp") or "", _j(s.get("label") or {}), s["kind"],
                 s.get("lang") or "", _j(s.get("constraints") or {}), int(bool(s.get("required"))),
                 s.get("expires") or "", _j(s.get("targets") or []), _j(s.get("brief") or {}),
                 _j([source] if source else []), _j(s.get("plan") or {}), int(s.get("ord") or 0),
                 t, t))
        return get_slot(s["key"])


def get_slot(key: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM slots WHERE key=?", (key,)).fetchone())


def list_slots(section: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM slots", []
    if section:
        q += " WHERE section=?"
        args.append(section)
    q += " ORDER BY section, ord, key"
    return [_row(r) for r in conn().execute(q, args).fetchall()]


def patch_slot(key: str, changes: dict) -> dict | None:
    allowed = {k: v for k, v in changes.items() if k in ("label", "constraints", "required",
                                                          "targets", "brief", "expires", "grp",
                                                          "plan", "lang")}
    if not allowed:
        return get_slot(key)
    sets, args = [], []
    for k, v in allowed.items():
        sets.append(f"{k}=?")
        args.append(_j(v) if k in JSON_COLS else (int(bool(v)) if k == "required" else v))
    sets.append("updated_at=?")
    args.extend([now(), key])
    with _write_lock:
        conn().execute(f"UPDATE slots SET {', '.join(sets)} WHERE key=?", args)
    return get_slot(key)


def delete_slot(key: str) -> None:
    with _write_lock:
        conn().execute("DELETE FROM slots WHERE key=?", (key,))
        conn().execute("DELETE FROM active WHERE slot_key=?", (key,))


# ── assets ───────────────────────────────────────────────────────────────────────────────────────
def add_asset(slot_key: str, kind: str, *, title: str = "", text: str | None = None,
              file: dict | None = None, source: str = "upload", author: str = "",
              status: str = "draft", meta: dict | None = None) -> dict:
    aid = new_id("a")
    f = file or {}
    with _write_lock:
        conn().execute(
            "INSERT INTO assets (id, slot_key, kind, title, text, file_sha, file_ext, mime, size, "
            "width, height, source, author, status, meta, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, slot_key, kind, title or "", text, f.get("sha"), f.get("ext"), f.get("mime"),
             f.get("size"), f.get("width"), f.get("height"), source, author or "", status,
             _j(meta or {}), now()))
    return get_asset(aid)


def get_asset(aid: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone())


def list_assets(slot_key: str | None = None, *, kinds: tuple | None = None,
                include_archived: bool = False, limit: int = 500) -> list[dict]:
    q, args, where = "SELECT * FROM assets", [], []
    if slot_key:
        where.append("slot_key=?")
        args.append(slot_key)
    if kinds:
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args.extend(kinds)
    if not include_archived:
        where.append("status != 'archived'")
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit))
    return [_row(r) for r in conn().execute(q, args).fetchall()]


def patch_asset(aid: str, changes: dict) -> dict | None:
    sets, args = [], []
    for k in ("title", "status", "text", "meta", "slot_key"):
        if k in changes:
            sets.append(f"{k}=?")
            args.append(_j(changes[k]) if k == "meta" else changes[k])
    if sets:
        args.append(aid)
        with _write_lock:
            conn().execute(f"UPDATE assets SET {', '.join(sets)} WHERE id=?", args)
    return get_asset(aid)


def delete_asset(aid: str) -> None:
    with _write_lock:
        conn().execute("DELETE FROM assets WHERE id=?", (aid,))


# ── the active choice ────────────────────────────────────────────────────────────────────────────
def set_active(slot_key: str, asset_id: str, by: str = "") -> None:
    with _write_lock:
        conn().execute("INSERT INTO active (slot_key, asset_id, set_at, set_by) VALUES (?,?,?,?) "
                       "ON CONFLICT(slot_key) DO UPDATE SET asset_id=excluded.asset_id, "
                       "set_at=excluded.set_at, set_by=excluded.set_by",
                       (slot_key, asset_id, now(), by or ""))


def active_of(slot_key: str) -> dict | None:
    r = conn().execute("SELECT * FROM active WHERE slot_key=?", (slot_key,)).fetchone()
    return dict(r) if r else None


def active_map() -> dict[str, dict]:
    return {r["slot_key"]: dict(r) for r in conn().execute("SELECT * FROM active").fetchall()}


def clear_active(slot_key: str) -> None:
    with _write_lock:
        conn().execute("DELETE FROM active WHERE slot_key=?", (slot_key,))


# ── channels ─────────────────────────────────────────────────────────────────────────────────────
def upsert_channel(ch: dict) -> dict:
    cur = get_channel(ch["id"])
    with _write_lock:
        if cur:
            merged = {**cur, **{k: v for k, v in ch.items() if v is not None}}
            conn().execute(
                "UPDATE channels SET kind=?, label=?, platform=?, account_id=?, site_id=?, url=?, "
                "handle=?, lang=?, enabled=?, core=?, ord=? WHERE id=?",
                (merged["kind"], _j(merged.get("label") or {}), merged.get("platform"),
                 merged.get("account_id"), merged.get("site_id"), merged.get("url"),
                 merged.get("handle"), merged.get("lang") or "he", int(bool(merged.get("enabled", 1))),
                 int(bool(merged.get("core"))), int(merged.get("ord") or 0), ch["id"]))
        else:
            conn().execute(
                "INSERT INTO channels (id, kind, label, platform, account_id, site_id, url, handle, "
                "lang, enabled, core, ord) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ch["id"], ch.get("kind") or "listing", _j(ch.get("label") or {}), ch.get("platform"),
                 ch.get("account_id"), ch.get("site_id"), ch.get("url"), ch.get("handle"),
                 ch.get("lang") or "he", int(bool(ch.get("enabled", 1))), int(bool(ch.get("core"))),
                 int(ch.get("ord") or 0)))
    return get_channel(ch["id"])


def set_channel_binding(cid: str, changes: dict) -> dict | None:
    """The owner's edit of a channel: which account/site/url it is. `None` CLEARS a binding here
    (unlike upsert, which treats None as 'not mentioned')."""
    cur = get_channel(cid)
    if not cur:
        return None
    sets, args = [], []
    for k in ("account_id", "site_id", "url", "handle", "lang", "enabled", "label"):
        if k in changes:
            v = changes[k]
            sets.append(f"{k}=?")
            args.append(_j(v) if k == "label" else (int(bool(v)) if k == "enabled" else v))
    if sets:
        args.append(cid)
        with _write_lock:
            conn().execute(f"UPDATE channels SET {', '.join(sets)} WHERE id=?", args)
    return get_channel(cid)


def redefine_channel(cid: str, kind: str, platform: str | None) -> dict | None:
    """The catalogue redefined what a channel IS (a network left social-list and became a listing,
    or joined it): follow the catalogue, keep everything the owner set — except an account binding,
    which only means something on a social channel."""
    cur = get_channel(cid)
    if not cur or (cur.get("kind"), cur.get("platform")) == (kind, platform):
        return cur
    with _write_lock:
        conn().execute("UPDATE channels SET kind=?, platform=?, account_id=? WHERE id=?",
                       (kind, platform, cur.get("account_id") if kind == "social" else None, cid))
    return get_channel(cid)


def get_channel(cid: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone())


def list_channels() -> list[dict]:
    return [_row(r) for r in conn().execute(
        "SELECT * FROM channels ORDER BY core DESC, ord, id").fetchall()]


# ── publication runs and their items ─────────────────────────────────────────────────────────────
def new_run(slot_key: str, asset_id: str, actor: str) -> str:
    rid = new_id("r")
    t = now()
    with _write_lock:
        conn().execute("INSERT INTO runs (id, slot_key, asset_id, actor, state, created_at, "
                       "updated_at) VALUES (?,?,?,?,?,?,?)",
                       (rid, slot_key, asset_id, actor or "", "planned", t, t))
    return rid


def set_run_state(rid: str, state: str) -> None:
    with _write_lock:
        conn().execute("UPDATE runs SET state=?, updated_at=? WHERE id=?", (state, now(), rid))


def get_run(rid: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())


def add_publication(rid: str, slot_key: str, asset_id: str, channel_id: str, field: str,
                    state: str, result: dict | None = None) -> str:
    pid = new_id("p")
    t = now()
    with _write_lock:
        conn().execute(
            "INSERT INTO publications (id, run_id, slot_key, asset_id, channel_id, field, state, "
            "result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, rid, slot_key, asset_id, channel_id, field or "", state, _j(result or {}), t, t))
    return pid


def update_publication(pid: str, **changes) -> None:
    sets, args = [], []
    for k in ("state", "job_id", "result"):
        if k in changes:
            sets.append(f"{k}=?")
            args.append(_j(changes[k]) if k == "result" else changes[k])
    sets.append("updated_at=?")
    args.extend([now(), pid])
    with _write_lock:
        conn().execute(f"UPDATE publications SET {', '.join(sets)} WHERE id=?", args)


def get_publication(pid: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM publications WHERE id=?", (pid,)).fetchone())


def run_publications(rid: str) -> list[dict]:
    return [_row(r) for r in conn().execute(
        "SELECT * FROM publications WHERE run_id=? ORDER BY created_at, channel_id", (rid,)).fetchall()]


def latest_publications(slot_key: str) -> list[dict]:
    """The newest publication per (channel, field) for a slot — "where is it live now"."""
    rows = conn().execute(
        "SELECT * FROM publications WHERE slot_key=? ORDER BY created_at DESC", (slot_key,)).fetchall()
    seen, out = set(), []
    for r in rows:
        k = (r["channel_id"], r["field"])
        if k in seen:
            continue
        seen.add(k)
        out.append(_row(r))
    return out


def pending_publications(limit: int = 100) -> list[dict]:
    return [_row(r) for r in conn().execute(
        "SELECT * FROM publications WHERE state IN ('queued','running','needs_owner') "
        "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]


# ── posts ────────────────────────────────────────────────────────────────────────────────────────
def add_post(slot_key: str | None, asset_ids: list, text: str, channels: list, actor: str) -> str:
    pid = new_id("post")
    t = now()
    with _write_lock:
        conn().execute("INSERT INTO posts (id, slot_key, asset_ids, text, channels, state, results, "
                       "actor, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pid, slot_key, _j(asset_ids), text or "", _j(channels), "queued", _j({}),
                        actor or "", t, t))
    return pid


def update_post(pid: str, state: str | None = None, results: dict | None = None) -> None:
    sets, args = ["updated_at=?"], [now()]
    if state:
        sets.append("state=?")
        args.append(state)
    if results is not None:
        sets.append("results=?")
        args.append(_j(results))
    args.append(pid)
    with _write_lock:
        conn().execute(f"UPDATE posts SET {', '.join(sets)} WHERE id=?", args)


def get_post(pid: str) -> dict | None:
    return _row(conn().execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone())


def list_posts(limit: int = 50, slot_key: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM posts", []
    if slot_key:
        q += " WHERE slot_key=?"
        args.append(slot_key)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in conn().execute(q, args).fetchall()]


# ── blueprints applied, and the event log ────────────────────────────────────────────────────────
def mark_applied(bid: str, version: int, params: dict, by: str) -> None:
    with _write_lock:
        conn().execute("INSERT INTO applied (blueprint_id, version, params, applied_at, by) "
                       "VALUES (?,?,?,?,?) ON CONFLICT(blueprint_id) DO UPDATE SET "
                       "version=excluded.version, params=excluded.params, "
                       "applied_at=excluded.applied_at, by=excluded.by",
                       (bid, int(version or 1), _j(params or {}), now(), by or ""))


def applied() -> dict[str, dict]:
    return {r["blueprint_id"]: _row(r) for r in conn().execute("SELECT * FROM applied").fetchall()}


def event(kind: str, summary: str, *, slot_key: str | None = None, actor: str = "",
          data: dict | None = None) -> None:
    with _write_lock:
        conn().execute("INSERT INTO events (at, kind, slot_key, summary, actor, data) "
                       "VALUES (?,?,?,?,?,?)",
                       (now(), kind, slot_key, summary, actor or "", _j(data or {})))


def events(limit: int = 50, slot_key: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM events", []
    if slot_key:
        q += " WHERE slot_key=?"
        args.append(slot_key)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in conn().execute(q, args).fetchall()]
