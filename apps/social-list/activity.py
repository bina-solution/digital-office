"""social-list.activity — what the office did on the owner's behalf, one row per action.

browser-session-connection.md §5.4: "every action is logged with who asked, what ran, what the page
said, and when — the log is the answer to 'what did the office do on my behalf'". Media bytes never
land here (only their names and sizes); screenshots are kept only for failures, and trimmed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DB = Path(os.environ.get("APP_STATE_DIR", "/data")) / "activity.db"
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
  id         TEXT PRIMARY KEY,
  at         INTEGER NOT NULL,
  account_id TEXT NOT NULL,
  platform   TEXT NOT NULL,
  kind       TEXT NOT NULL,
  op         TEXT NOT NULL,
  actor      TEXT NOT NULL DEFAULT '',
  summary    TEXT NOT NULL DEFAULT '',
  params     TEXT NOT NULL DEFAULT '{}',
  state      TEXT NOT NULL,
  result     TEXT NOT NULL DEFAULT '{}',
  job_id     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS actions_account ON actions(account_id, at);
"""


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB), timeout=20, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _local.c = c
    return c


def _clean(params: dict) -> dict:
    """Parameters as a person would want them in a log: text kept, media reduced to what it was."""
    out = {}
    for k, v in (params or {}).items():
        if k in ("avatar", "banner", "image") and isinstance(v, dict):
            out[k] = {"kind": v.get("kind"), "name": v.get("name"), "url": v.get("url")}
        elif k == "media" and isinstance(v, list):
            out[k] = [{"kind": (m or {}).get("kind"), "name": (m or {}).get("name"),
                       "url": (m or {}).get("url")} for m in v]
        elif isinstance(v, str) and len(v) > 2000:
            out[k] = v[:2000] + "…"
        else:
            out[k] = v
    return out


def record(account: dict, platform: str, kind: str, op: str, params: dict, state: str,
           result: dict, actor: str = "", summary: str = "", job_id: str = "") -> str:
    aid = uuid.uuid4().hex[:12]
    res = dict(result or {})
    ev = res.get("evidence") or {}
    if isinstance(ev, dict) and ev.get("screenshot_base64"):
        ev = {**ev, "screenshot_base64": ev["screenshot_base64"][:120_000]}
        res["evidence"] = ev
    _conn().execute(
        "INSERT INTO actions (id, at, account_id, platform, kind, op, actor, summary, params, state,"
        " result, job_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, int(time.time()), account.get("id") or "", platform, kind, op, actor or "",
         summary or "", json.dumps(_clean(params), ensure_ascii=False), state,
         json.dumps(res, ensure_ascii=False, default=str), job_id or ""))
    return aid


def recent(account_id: str | None = None, limit: int = 50) -> list[dict]:
    q, args = "SELECT * FROM actions", []
    if account_id:
        q += " WHERE account_id=?"
        args.append(account_id)
    q += " ORDER BY at DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in _conn().execute(q, args).fetchall():
        d = dict(r)
        for k in ("params", "result"):
            try:
                d[k] = json.loads(d[k] or "{}")
            except ValueError:
                d[k] = {}
        # the list never carries screenshots; the single-action endpoint does
        ev = (d["result"] or {}).get("evidence") or {}
        if isinstance(ev, dict) and ev.get("screenshot_base64"):
            d["result"]["evidence"] = {**ev, "screenshot_base64": None, "has_screenshot": True}
        out.append(d)
    return out


def get(action_id: str) -> dict | None:
    r = _conn().execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("params", "result"):
        try:
            d[k] = json.loads(d[k] or "{}")
        except ValueError:
            d[k] = {}
    return d
