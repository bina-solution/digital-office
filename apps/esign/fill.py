"""esign — «מילוי וחתימה» (DGO-2139): ONE link for every side of a document.

The owner (2026-11-20): «במסמך עצמו מגדירים את המידע שצריך להזין ואת המקומות לחתימות … הקישור לחתימה בעצם מנהל את כל
האירוע … כל אחד נכנס ובוחר צד במסמך וממלא את הנתונים וחותם». An EVENT is one frozen PDF, its sides (parties) and its
places (fields), and one token. Whoever opens the link picks a side; the side is CLAIMED by that browser (a cookie
whose hash the side keeps), answers only its own questions, sees them in place, and signs. When the last required
side has signed, ONE final copy is made — every answer and signature drawn into the pages, the certificate of every
side appended, one office seal — and every side downloads it from the same link.

No product the research found lets each visitor of one link pick their own side (research_notes/DGO-2139…/02), so
the claim is this app's own: atomic (one UPDATE that only an open side satisfies), bound to the device, guarded by
a personal code when the office sets one, and never silent — taking a side another browser holds is asked for, and
the trail says so. «opened» is said by a person's browser (a POST), never by a GET: a chat app's preview bot fetches
every link it is sent.

Two halves, as in server.py: /api/events/… behind the office's sign-in, and /s/<token>/… (the event's page and its
calls under /s/<token>/f/…) on the one public path. Nothing here reaches beyond its own event.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import urllib.parse
from datetime import datetime, timedelta

from flask import (Flask, Response, current_app, make_response, render_template, request, send_file)

import clients
import fillpdf
import pdfsign
from store import hash_password, iso, parse, sha256_bytes, token_hash, utcnow, verify_password

PUBLIC_PREFIX = "/s/"
FIELD_TYPES = ("name", "text", "textarea", "id_number", "company_number", "phone", "email", "date", "number",
               "checkbox", "choice", "signature", "initials", "stamp", "date_signed")
SIGN_TYPES = ("signature", "initials")
NOT_ASKED = ("signature", "initials", "stamp", "date_signed")
MAX_PARTIES, MAX_FIELDS = 12, 200
MAX_SIG = 600 * 1024
MAX_STAMP = 1500 * 1024
MAX_ANSWER = 500
#: the public calls' bodies: a signature and a stamp photo fit in the first, an answer or a claim in the second
MAX_BODY_SIGN, MAX_BODY = 3_600_000, 64_000
#: five wrong codes lock a side; each lock is twice the one before (15 min, 30, 60 … up to a day), so a personal code
#: is never guessed in a link's lifetime (the second reader: a 4-digit code fell to 480 tries a day in ~19 days)
CODE_TRIES, CODE_LOCK_MIN, CODE_LOCK_MAX_MIN = 5, 15, 24 * 60
#: wrong codes on a side from every browser together, for the life of its link, after which the side is closed until
#: the office issues a new link (which opens it and starts the count again) — and the office is told. A browser that
#: changes its cookie every five tries meets this ceiling, not its own lock: 100 of a million six-digit codes is one
#: chance in 10,000 per link (the second reader, round 4: a day's lock that reset let 1,000 tries a day through)
CODE_CEILING = 100
#: personal codes checked at once: argon2 holds 19 MiB a check, and esign's container has 384 MB (round 5)
CODE_CHECKS = threading.BoundedSemaphore(2)
#: the browser that guesses: a cookie the event's page gives on its first open. Wrong codes are counted per BROWSER,
#: not per address — behind the office's door every visitor reaches esign from the door's own address (measured on
#: the HP: 172.18.0.28 for every event of DGO-2125's test envelope), so per address was everyone (round 3)
VISITOR_COOKIE = "fill_v"
#: a side another browser holds is offered to the next one only after it was quiet this long — quiet since its last
#: answer or look at the page, not since it was taken — or when the next one asks for it
QUIET_MIN = 10
#: «opened» is kept once an hour per address and event: a script looping on the page does not grow the trail
SEEN_EVERY_S = 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS fill_events (
  id           TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL,
  expires_at   TEXT NOT NULL,
  status       TEXT NOT NULL,            -- draft | open | completing | complete | cancelled
  title        TEXT NOT NULL,
  doc_name     TEXT NOT NULL,
  doc_path     TEXT NOT NULL,
  doc_sha256   TEXT NOT NULL,
  doc_size     INTEGER NOT NULL,
  pages        TEXT NOT NULL,            -- [{w, h, rotate}] of the pages as shown
  sender       TEXT NOT NULL,
  ref          TEXT,                     -- the caller's own name for the source (my-docs: the ledger id)
  order_mode   TEXT NOT NULL DEFAULT 'any',   -- any | seq (each side after the one before it)
  token_hash   TEXT UNIQUE,
  map_sha256   TEXT,                     -- the sides and places as they were frozen at sending
  final_path   TEXT,
  final_sha256 TEXT,
  final_state  TEXT,                     -- sealing | ok | failed:<why>
  completed_at TEXT,
  drive_path   TEXT,
  drive_state  TEXT,
  notice_state TEXT,
  closed_reason TEXT,
  trail_gaps   INTEGER NOT NULL DEFAULT 0  -- acts whose trail line could not be written (the certificate says so)
);
CREATE INDEX IF NOT EXISTS fill_events_ref ON fill_events(ref);
CREATE TABLE IF NOT EXISTS fill_parties (
  event_id     TEXT NOT NULL,
  id           TEXT NOT NULL,
  ord          INTEGER NOT NULL,
  label        TEXT NOT NULL,
  note         TEXT,
  code_hash    TEXT,                     -- a personal code the office gave this side, hashed
  code_tries   INTEGER NOT NULL DEFAULT 0,      -- wrong codes from EVERY address (the side's ceiling)
  code_locked  TEXT,                            -- the ceiling's lock, for everyone
  state        TEXT NOT NULL DEFAULT 'waiting',   -- waiting | filling | signed
  claim_hash   TEXT,
  claimed_at   TEXT,
  active_at    TEXT,                     -- the holder's last answer or look: «quiet» is measured from here
  claims       INTEGER NOT NULL DEFAULT 0,
  signer_name  TEXT,
  signed_at    TEXT,
  signer_ip    TEXT,
  signer_ua    TEXT,
  sig_kind     TEXT,
  sig_png      BLOB,
  stamp_img    BLOB,
  PRIMARY KEY (event_id, id)
);
CREATE TABLE IF NOT EXISTS fill_fields (
  event_id     TEXT NOT NULL,
  id           TEXT NOT NULL,
  ord          INTEGER NOT NULL,
  party        TEXT NOT NULL,
  type         TEXT NOT NULL,
  label        TEXT NOT NULL,
  help         TEXT,
  required     INTEGER NOT NULL DEFAULT 1,
  grp          TEXT,
  options      TEXT,
  autocomplete TEXT,
  page         INTEGER,
  box          TEXT,                     -- [x, y, w, h]: fractions of the page as shown, from its top-left
  value        TEXT,
  PRIMARY KEY (event_id, id)
);
CREATE TABLE IF NOT EXISTS fill_code_tries (     -- wrong personal codes, per side and per address
  event_id     TEXT NOT NULL,
  party        TEXT NOT NULL,
  who          TEXT NOT NULL,
  tries        INTEGER NOT NULL DEFAULT 0,
  locks        INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  PRIMARY KEY (event_id, party, who)
);
"""
#: columns added after a table was first made: a volume from before them gets them when the store opens
LATE_COLUMNS = {"fill_parties": (("active_at", "TEXT"),),
                "fill_events": (("trail_gaps", "INTEGER NOT NULL DEFAULT 0"),)}


# ── what an answer must be (the same rules as fill.js) ─────────────────────────────────────────────
def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def check_digit_ok(v) -> bool:
    """Israel's check digit, the same for a person's ת.ז. and a company's ח.פ./ע.מ."""
    s = _digits(v)
    if not s or len(s) > 9:
        return False
    s = s.zfill(9)
    total = 0
    for i, ch in enumerate(s):
        d = int(ch) * (i % 2 + 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _phone(v) -> str:
    s = _digits(v)
    return "0" + s[3:] if s.startswith("972") else s


def problem(f: dict, v) -> str:
    """The Hebrew sentence a wrong or missing answer gets; '' when the answer will do."""
    empty = v is None or v == "" or v is False
    if empty:
        if not f.get("required"):
            return ""
        return "יש לסמן כדי להמשיך" if f["type"] == "checkbox" else "זה שדה חובה"
    t, s = f["type"], str(v).strip()
    if len(s) > 500:
        return "התשובה ארוכה מדי"
    if t == "name" and len(s) < 2:
        return "כתבו שם מלא"
    if t == "id_number" and not check_digit_ok(s):
        return "מספר הזהות אינו תקין — בדקו את 9 הספרות"
    if t == "company_number" and not re.fullmatch(r"\d{8,9}", _digits(s)):
        return "כתבו את 9 הספרות של המספר"
    if t == "phone" and not re.fullmatch(r"0(5\d|7\d|[2-489])\d{7}", _phone(s)):
        return "מספר הטלפון אינו תקין"
    if t == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", s):
        return "כתובת הדוא״ל אינה תקינה"
    if t == "number" and not re.fullmatch(r"-?\d+([.,]\d+)?", s):
        return "כתבו מספר"
    if t == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "כתבו תאריך"
    if t == "choice" and s not in (f.get("options") or []):
        return "בחרו אחת מהאפשרויות"
    return ""


def shown(f: dict, v) -> str:
    """An answer as it is drawn on the page."""
    if v is None or v == "":
        return ""
    t = f["type"]
    if t == "date":
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v))
        return "%s.%s.%s" % (m.group(3), m.group(2), m.group(1)) if m else str(v)
    if t == "checkbox":
        return "✓" if v in (True, "true", "1", 1, "on") else ""
    if t == "phone":
        s = _phone(v)
        return s[:3] + "-" + s[3:] if len(s) == 10 else s
    return str(v).strip()


def _image(data_url: str, limit: int, kinds: tuple) -> bytes | None:
    """A picture sent as a data: URL (the pad's PNG, a stamp's photo), if it is one of `kinds` and not too big."""
    m = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)", str(data_url or ""))
    if not m or m.group(1) not in kinds:
        return None
    raw = base64.b64decode(m.group(2))
    if len(raw) > limit:
        return None
    if m.group(1) == "png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if m.group(1) == "jpeg" and not raw.startswith(b"\xff\xd8"):
        return None
    return raw


# ── the store ───────────────────────────────────────────────────────────────────────────────────────
class FillStore:
    """The events, their sides and places, on the app's own volume (the same file as the envelopes). Its own
    connection, in autocommit, so a claim and a signature are each ONE statement or one explicit transaction; the
    lock keeps this process's threads from interleaving inside one."""

    def __init__(self, path: str, clock=utcnow):
        self.clock = clock
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._side_locks: dict = {}                     # (event, side) → one personal-code check at a time
        with self.lock:
            self.conn.executescript(SCHEMA)
            for table, cols in LATE_COLUMNS.items():
                have = {r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table)}
                for name, decl in cols:
                    if name not in have:
                        self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, args).rowcount

    # an event, whole
    def get(self, eid: str) -> dict | None:
        rows = self._q("SELECT * FROM fill_events WHERE id=?", (eid,))
        if not rows:
            return None
        ev = rows[0]
        ev["pages"] = json.loads(ev["pages"] or "[]")
        ev["parties"] = self._q("SELECT * FROM fill_parties WHERE event_id=? ORDER BY ord", (eid,))
        ev["fields"] = []
        for f in self._q("SELECT * FROM fill_fields WHERE event_id=? ORDER BY ord", (eid,)):
            f["box"] = json.loads(f["box"]) if f.get("box") else None
            f["options"] = json.loads(f["options"]) if f.get("options") else []
            f["required"] = bool(f["required"])
            f["group"] = f.pop("grp")
            ev["fields"].append(f)
        return ev

    def by_token(self, token: str) -> dict | None:
        if not token or len(token) < 20:
            return None
        rows = self._q("SELECT id FROM fill_events WHERE token_hash=?", (token_hash(token),))
        return self.get(rows[0]["id"]) if rows else None

    def list(self, ref: str | None = None, limit: int = 50) -> list[dict]:
        if ref:
            rows = self._q("SELECT id FROM fill_events WHERE ref=? ORDER BY created_at DESC, rowid DESC LIMIT ?", (ref, limit))
        else:
            rows = self._q("SELECT id FROM fill_events ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self.get(r["id"]) for r in rows]

    def create(self, *, title: str, doc_name: str, doc_path: str, doc_sha256: str, doc_size: int, pages: list,
               sender: str, ref: str | None, days: int, parties: list, fields: list) -> dict:
        now = self.clock()
        eid = secrets.token_hex(8)
        with self.lock:
            self.conn.execute(
                "INSERT INTO fill_events (id,created_at,expires_at,status,title,doc_name,doc_path,doc_sha256,doc_size,"
                "pages,sender,ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, iso(now), iso(now + timedelta(days=max(int(days or 30), 1))), "draft", title[:200], doc_name[:200],
                 doc_path, doc_sha256, doc_size, json.dumps(pages), sender[:120], ref))
            self._write_map(eid, parties, fields)
        return self.get(eid)

    def _write_map(self, eid: str, parties: list, fields: list) -> None:
        self.conn.execute("DELETE FROM fill_parties WHERE event_id=?", (eid,))
        self.conn.execute("DELETE FROM fill_fields WHERE event_id=?", (eid,))
        for i, p in enumerate(parties):
            code = str(p.get("code") or "").strip()
            self.conn.execute(
                "INSERT INTO fill_parties (event_id,id,ord,label,note,code_hash) VALUES (?,?,?,?,?,?)",
                (eid, p["id"], i, p["label"], p.get("note") or "", hash_password(code) if code else None))
        for i, f in enumerate(fields):
            self.conn.execute(
                "INSERT INTO fill_fields (event_id,id,ord,party,type,label,help,required,grp,options,autocomplete,page,box)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, f["id"], i, f["party"], f["type"], f["label"], f.get("help") or "", 1 if f.get("required") else 0,
                 f.get("group") or None, json.dumps(f.get("options") or []), f.get("autocomplete") or None,
                 f.get("page") if f.get("box") else None, json.dumps(f["box"]) if f.get("box") else None))

    def open(self, eid: str, *, title: str, parties: list, fields: list, order: str, expires: datetime | None) -> str | None:
        """Freeze the sides and places and mint the one link; None if the event is no longer a draft."""
        token = secrets.token_urlsafe(32)
        frozen = sha256_bytes(json.dumps({"parties": [{k: p.get(k) for k in ("id", "label", "note")} for p in parties],
                                          "fields": fields}, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("SELECT status FROM fill_events WHERE id=?", (eid,)).fetchone()
                if not row or row["status"] != "draft":
                    self.conn.execute("ROLLBACK")
                    return None
                self._write_map(eid, parties, fields)
                sets = ["status='open'", "title=?", "order_mode=?", "token_hash=?", "map_sha256=?"]
                args = [title[:200], order, token_hash(token), frozen]
                if expires:
                    sets.append("expires_at=?")
                    args.append(iso(expires))
                self.conn.execute("UPDATE fill_events SET %s WHERE id=?" % ",".join(sets), (*args, eid))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return token

    def set(self, eid: str, **cols) -> None:
        if cols:
            self._x("UPDATE fill_events SET %s WHERE id=?" % ",".join("%s=?" % k for k in cols), (*cols.values(), eid))

    def relink(self, eid: str) -> str | None:
        """A new link; the old one stops working. A side the ceiling of wrong codes closed opens again with it, every
        count started over: whoever was guessing held the old link."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                n = self.conn.execute("UPDATE fill_events SET token_hash=? WHERE id=? AND status IN "
                                      "('open','completing','complete')", (token_hash(token), eid)).rowcount
                if n == 1:
                    self.conn.execute("UPDATE fill_parties SET code_tries=0, code_locked=NULL WHERE event_id=?", (eid,))
                    self.conn.execute("DELETE FROM fill_code_tries WHERE event_id=?", (eid,))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return token if n == 1 else None

    def cancel(self, eid: str, reason: str) -> bool:
        return self._x("UPDATE fill_events SET status='cancelled', closed_reason=? WHERE id=? AND status IN ('draft','open')",
                       (reason[:300], eid)) == 1

    # a side
    def claim(self, eid: str, pid: str, old_hash: str, new_hash: str, *, take: bool) -> tuple[str, dict]:
        """Take side `pid` for a browser: `old_hash` is what its cookie held (its side so far, if any), `new_hash` the
        secret minted for this claim — a claim never adopts a secret the browser brought (one planted by a neighbour
        host would else be a key to the side). 'ok' | 'took' (another browser's, and asked for or quiet) | 'busy'
        (another browser holds it and is active) | 'signed' | 'missing'. One statement decides: of two browsers at the
        same moment, one wins. Whatever was typed on a side that changes hands, or that its browser leaves for
        another side, is cleared: the next one to hold it sees nothing of the last (Amendment 13)."""
        now = self.clock()
        quiet = iso(now - timedelta(minutes=QUIET_MIN))
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("SELECT * FROM fill_parties WHERE event_id=? AND id=?", (eid, pid)).fetchone()
                if not row:
                    self.conn.execute("ROLLBACK")
                    return "missing", {}
                row = dict(row)
                if row["state"] == "signed":
                    self.conn.execute("ROLLBACK")
                    return "signed", row
                mine = bool(old_hash) and row["claim_hash"] == old_hash
                last_seen = max(row["active_at"] or "", row["claimed_at"] or "")
                if row["state"] == "filling" and not mine and not take and last_seen > quiet:
                    self.conn.execute("ROLLBACK")
                    return "busy", row
                n = self.conn.execute(
                    "UPDATE fill_parties SET state='filling', claim_hash=?, claimed_at=?, active_at=?, claims=claims+1 "
                    "WHERE event_id=? AND id=? AND state!='signed' AND COALESCE(claim_hash,'')=?",
                    (new_hash, iso(now), iso(now), eid, pid, row["claim_hash"] or "")).rowcount
                if n != 1:
                    self.conn.execute("ROLLBACK")
                    return "busy", row
                took = bool(row["claim_hash"]) and not mine
                if took:
                    self.conn.execute("UPDATE fill_fields SET value=NULL WHERE event_id=? AND party=?", (eid, pid))
                if old_hash:
                    # one browser, one side at a time: a side it held and left unsigned goes back to waiting, empty
                    self.conn.execute(
                        "UPDATE fill_fields SET value=NULL WHERE event_id=? AND party IN (SELECT id FROM fill_parties "
                        "WHERE event_id=? AND id!=? AND claim_hash=? AND state='filling')", (eid, eid, pid, old_hash))
                    self.conn.execute("UPDATE fill_parties SET state='waiting', claim_hash=NULL WHERE event_id=? AND id!=? "
                                      "AND claim_hash=? AND state='filling'", (eid, pid, old_hash))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return ("took" if took else "ok"), row

    def touch(self, eid: str, pid: str, secret_hash: str) -> None:
        """The holder is still there (an answer, a look at the page): its side is not «quiet»."""
        self._x("UPDATE fill_parties SET active_at=? WHERE event_id=? AND id=? AND claim_hash=? AND state='filling'",
                (iso(self.clock()), eid, pid, secret_hash))

    def code_ok(self, eid: str, pid: str, code: str, who: str) -> str:
        """'ok' | 'bad' | 'locked' | 'ceiling' | 'closed' | 'none'. Wrong codes are counted per BROWSER (`who`): five
        lock that browser out of the side, each lock twice the one before — so a stranger with the link locks out
        himself, not the signer (rounds 2–3). Behind that, the side's ceiling: CODE_CEILING wrong codes from every
        browser together close the side until a new link ('ceiling' the moment it closes — the caller tells the
        office — and 'closed' after). The code is checked outside the store's lock: argon2 takes tens of milliseconds
        on a small CPU, and every public call of every event waits on that lock (round 4). One check per side at a
        time, so what it read still holds when it writes — a guess in flight neither erases a lock another set nor
        passes a ceiling that closed meanwhile — and CODE_CHECKS at once in all (round 5)."""
        with self.lock:
            side_lock = self._side_locks.setdefault((eid, pid), threading.Lock())
        with side_lock:
            return self._code_ok(eid, pid, code, who)

    def _code_ok(self, eid: str, pid: str, code: str, who: str) -> str:
        now = self.clock()
        with self.lock:
            row = dict(self.conn.execute("SELECT code_hash, code_locked FROM fill_parties WHERE event_id=? AND id=?",
                                         (eid, pid)).fetchone() or {})
            if not row.get("code_hash"):
                return "none"
            if row.get("code_locked"):
                return "closed"
            mine = self.conn.execute("SELECT locked_until FROM fill_code_tries WHERE event_id=? AND party=? AND who=?",
                                     (eid, pid, who)).fetchone()
            if mine and mine[0] and now < parse(mine[0]):
                return "locked"
        with CODE_CHECKS:
            good = verify_password(row["code_hash"], code or "")
        if good:
            self._x("DELETE FROM fill_code_tries WHERE event_id=? AND party=? AND who=?", (eid, pid, who))
            return "ok"
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                total = int(self.conn.execute("SELECT code_tries FROM fill_parties WHERE event_id=? AND id=?",
                                              (eid, pid)).fetchone()[0] or 0) + 1
                closes = total >= CODE_CEILING
                self.conn.execute("UPDATE fill_parties SET code_tries=?, code_locked=COALESCE(code_locked, ?) "
                                  "WHERE event_id=? AND id=?", (total, iso(now) if closes else None, eid, pid))
                mine = dict(self.conn.execute("SELECT tries, locks FROM fill_code_tries WHERE event_id=? AND party=? "
                                              "AND who=?", (eid, pid, who)).fetchone() or {})
                tries, locks, until = int(mine.get("tries") or 0) + 1, int(mine.get("locks") or 0), None
                if tries >= CODE_TRIES:
                    locks += 1
                    until = iso(now + timedelta(minutes=min(CODE_LOCK_MIN * 2 ** (locks - 1), CODE_LOCK_MAX_MIN)))
                    tries = 0
                self.conn.execute("INSERT INTO fill_code_tries (event_id,party,who,tries,locks,locked_until) "
                                  "VALUES (?,?,?,?,?,?) ON CONFLICT(event_id,party,who) DO UPDATE SET "
                                  "tries=excluded.tries, locks=excluded.locks, locked_until=excluded.locked_until",
                                  (eid, pid, who, tries, locks, until))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        if closes:
            return "ceiling" if total == CODE_CEILING else "closed"
        return "locked" if until else "bad"

    def held_by(self, eid: str, secret_hash: str) -> dict | None:
        if not secret_hash:
            return None
        rows = self._q("SELECT * FROM fill_parties WHERE event_id=? AND claim_hash=? ORDER BY state='signed', ord LIMIT 1",
                       (eid, secret_hash))
        return rows[0] if rows else None

    def save_values(self, eid: str, pid: str, secret_hash: str, values: dict) -> bool:
        """The holder's answers as typed — only while it still holds the side, checked in the same transaction (an
        autosave still in flight after a take-over must not write into the next holder's empty side)."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                held = self.conn.execute("SELECT 1 FROM fill_parties WHERE event_id=? AND id=? AND claim_hash=? AND "
                                         "state='filling'", (eid, pid, secret_hash)).fetchone()
                if held:
                    for fid, v in values.items():
                        self.conn.execute("UPDATE fill_fields SET value=? WHERE event_id=? AND id=? AND party=?",
                                          (None if v is None else json.dumps(v, ensure_ascii=False), eid, fid, pid))
                    self.conn.execute("UPDATE fill_parties SET active_at=? WHERE event_id=? AND id=?",
                                      (iso(self.clock()), eid, pid))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return bool(held)

    def begin_seal(self, eid: str) -> bool:
        """One seal at a time, and none over a finished one: (completing|complete) and not sealing and not ok."""
        return self._x("UPDATE fill_events SET final_state='sealing' WHERE id=? AND status IN ('completing','complete') "
                       "AND (final_state IS NULL OR final_state LIKE 'failed%')", (eid,)) == 1

    def begin_delivery(self, eid: str) -> bool:
        """One delivery again at a time, of a copy that is made and not delivered: pending → delivering."""
        return self._x("UPDATE fill_events SET drive_state='delivering' WHERE id=? AND final_state='ok' AND "
                       "drive_state LIKE 'pending%'", (eid,)) == 1

    def unsealed(self) -> list[str]:
        """Events whose every side signed but whose copy was never made (a restart in the middle, a failure)."""
        return [r["id"] for r in self._q("SELECT id FROM fill_events WHERE status='completing' AND "
                                         "(final_state IS NULL OR final_state LIKE 'failed%' OR final_state='sealing')")]

    def sign(self, eid: str, pid: str, secret_hash: str, *, values: dict, signer: str, ip: str, ua: str, kind: str,
             sig: bytes, stamp: bytes | None, dates: dict) -> tuple[bool, bool]:
        """The side's answers, its signature and its date, in ONE transaction that only the browser holding the side
        can make, and only once. (signed, last): `last` when no required side is left — the event then moves to
        `completing` in the same transaction, so exactly one request makes the final copy."""
        now = iso(self.clock())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                n = self.conn.execute(
                    "UPDATE fill_parties SET state='signed', signed_at=?, signer_name=?, signer_ip=?, signer_ua=?, "
                    "sig_kind=?, sig_png=?, stamp_img=? WHERE event_id=? AND id=? AND state='filling' AND claim_hash=?",
                    (now, signer[:120], ip, ua[:300], kind, sig, stamp, eid, pid, secret_hash)).rowcount
                if n != 1:
                    self.conn.execute("ROLLBACK")
                    return False, False
                for fid, v in {**values, **dates}.items():
                    self.conn.execute("UPDATE fill_fields SET value=? WHERE event_id=? AND id=? AND party=?",
                                      (None if v is None else json.dumps(v, ensure_ascii=False), eid, fid, pid))
                left = self.conn.execute("SELECT COUNT(*) FROM fill_parties WHERE event_id=? AND state!='signed'",
                                         (eid,)).fetchone()[0]
                last = left == 0 and self.conn.execute(
                    "UPDATE fill_events SET status='completing' WHERE id=? AND status='open'", (eid,)).rowcount == 1
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return True, last


def values_of(ev: dict) -> dict:
    out = {}
    for f in ev["fields"]:
        try:
            out[f["id"]] = json.loads(f["value"]) if f.get("value") is not None else None
        except (TypeError, ValueError):
            out[f["id"]] = f.get("value")
    return out


# ── the map the office sends ───────────────────────────────────────────────────────────────────────
def clean_map(body: dict, pages: list) -> tuple[list, list, str]:
    """The sides and places as the office's editor sent them, checked: ('', …) or the Hebrew reason it cannot go."""
    raw_p, raw_f = body.get("parties") or [], body.get("fields") or []
    if not raw_p or len(raw_p) > MAX_PARTIES:
        return [], [], "צריך לפחות צד אחד, ולא יותר מ-%d" % MAX_PARTIES
    if len(raw_f) > MAX_FIELDS:
        return [], [], "יותר מדי מקומות במסמך"
    parties, ids = [], set()
    for p in raw_p:
        pid = str(p.get("id") or "")[:24]
        label = str(p.get("label") or "").strip()[:60]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", pid) or pid in ids or not label:
            return [], [], "לכל צד צריך שם"
        ids.add(pid)
        code = re.sub(r"\D", "", str(p.get("code") or ""))
        if code and not 6 <= len(code) <= 8:                   # four digits fall to the ceiling's guesses (round 4)
            return [], [], "קוד אישי הוא 6 עד 8 ספרות"
        parties.append({"id": pid, "label": label, "note": str(p.get("note") or "").strip()[:80], "code": code})
    fields, fids = [], set()
    for f in raw_f:
        fid, t = str(f.get("id") or "")[:32], f.get("type")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", fid) or fid in fids or t not in FIELD_TYPES or f.get("party") not in ids:
            return [], [], "אחד המקומות במסמך אינו תקין"
        fids.add(fid)
        box, page = f.get("box"), f.get("page")
        if box is not None:
            try:
                box = [round(float(v), 5) for v in box]
            except (TypeError, ValueError):
                return [], [], "אחד המקומות במסמך אינו תקין"
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0 or box[0] < 0 or box[1] < 0 or box[0] + box[2] > 1.001 \
                    or box[1] + box[3] > 1.001 or not isinstance(page, int) or not 1 <= page <= len(pages):
                return [], [], "אחד המקומות יוצא מגבולות הדף"
        elif t in SIGN_TYPES or t in ("date_signed", "stamp"):
            return [], [], "לחתימה ולתאריך צריך מקום במסמך"
        label = str(f.get("label") or "").strip()[:120]
        if not label:
            return [], [], "לכל שאלה צריך נוסח"
        if t == "choice" and not [o for o in (f.get("options") or []) if str(o).strip()]:
            # a choice nobody can answer would hold the event open for ever (the second reader)
            return [], [], "לשאלת הבחירה «%s» צריך לפחות אפשרות אחת" % label
        fields.append({"id": fid, "party": f["party"], "type": t, "label": label,
                       "help": str(f.get("help") or "").strip()[:200], "required": bool(f.get("required")),
                       "group": str(f.get("group") or "").strip()[:80] or None,
                       "options": [str(o)[:80] for o in (f.get("options") or [])][:30],
                       "autocomplete": str(f.get("autocomplete") or "")[:40] or None,
                       "page": page if box else None, "box": box})
    for p in parties:
        if not any(f["party"] == p["id"] and f["type"] in SIGN_TYPES and f["box"] for f in fields):
            return [], [], "לצד «%s» אין מקום חתימה במסמך" % p["label"]
    return parties, fields, ""


# ── the app's half ─────────────────────────────────────────────────────────────────────────────────
def fs() -> FillStore:
    return current_app.config["FILL"]


def _audit(eid: str, type_: str, data: dict | None = None) -> None:
    current_app.config["STORE"].append(eid, type_, data or {})


def _audit_after(eid: str, type_: str, data: dict | None = None) -> None:
    """The trail of an act that HAS happened (a side taken, a hand signed): a trail that does not answer is logged
    loudly, never the visitor's error — the claim's cookie and the signer's «נחתם» must still reach them (round 2)."""
    try:
        _audit(eid, type_, data)
    except Exception as exc:
        current_app.logger.error("esign fill: the trail did not take %s for %s: %s", type_, eid, exc)
        # a hole in the trail is said on the certificate: a hash chain proves order, not that nothing is missing
        try:
            fs()._x("UPDATE fill_events SET trail_gaps=trail_gaps+1 WHERE id=?", (eid,))
        except Exception:
            pass


def _ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def _public_ip(ip: str) -> str:
    """The address as the certificate may show it: a signer's own address on the internet, else "". An address inside
    a network — the door's 172.18.0.28, a LAN's — is not where the signer was: the certificate showed the door as every
    signer's (the second reader, round 4). The door does not pass the visitor's address yet
    (issues/a-published-signing-door-loses-the-signers-ip-at-the-link.yaml); the trail keeps what was seen."""
    try:
        a = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    return str(a) if a.is_global else ""


def _ua() -> str:
    return (request.headers.get("User-Agent") or "")[:300]


def _json(payload: dict, code: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False, default=str), status=code, mimetype="application/json")


def _office() -> str:
    return os.environ.get("ESIGN_OFFICE_NAME", "").strip()


def link_for(token: str) -> str:
    return "%s/s/%s" % (clients.public_base(), token)


def office_view(ev: dict, base: str = "") -> dict:
    """An event as the office sees it: every side with its state, every place with its answer."""
    vals = values_of(ev)
    return {
        "id": ev["id"], "status": ev["status"], "title": ev["title"], "doc_name": ev["doc_name"], "sender": ev["sender"],
        "ref": ev["ref"], "created_at": ev["created_at"], "expires": ev["expires_at"][:10], "order": ev["order_mode"],
        "doc_sha256": ev["doc_sha256"], "final_sha256": ev.get("final_sha256"), "final_state": ev.get("final_state"),
        "completed_at": ev.get("completed_at"), "drive_path": ev.get("drive_path"), "drive_state": ev.get("drive_state"),
        "pages": [dict(p, src="%s/api/events/%s/page/%d" % (base, ev["id"], i + 1)) for i, p in enumerate(ev["pages"])],
        "parties": [{"id": p["id"], "label": p["label"], "note": p["note"], "state": p["state"], "code": bool(p["code_hash"]),
                     "signed_at": p["signed_at"], "signer": p["signer_name"], "claimed_at": p["claimed_at"]}
                    for p in ev["parties"]],
        "fields": [{k: f.get(k) for k in ("id", "party", "type", "label", "help", "required", "group", "options",
                                           "autocomplete", "page", "box")} | {"value": vals.get(f["id"])}
                   for f in ev["fields"]],
    }


def public_view(ev: dict, token: str, me: dict | None) -> dict:
    """What the link shows: the document, every side's state, the places — an answer only once its side has
    signed and only where the page shows it — and the browser's own side with its answers so far."""
    base = PUBLIC_PREFIX + token
    vals = values_of(ev)
    signed = {p["id"] for p in ev["parties"] if p["state"] == "signed"}
    blocked = {}
    if ev["order_mode"] == "seq":
        before = None
        for p in ev["parties"]:
            if before and before["state"] != "signed" and p["state"] != "signed":
                blocked[p["id"]] = before["label"]
            before = p if p["state"] != "signed" else before
    status = ev["status"]
    if status in ("draft", "cancelled") or (status == "open" and _expired(ev)):
        status = "closed"
    elif status == "completing":
        # every side has signed: for the page that is done, the copy only not ready yet (final_ready says so)
        status = "complete"
    fields = []
    for f in ev["fields"]:
        out = {k: f.get(k) for k in ("id", "party", "type", "label", "help", "required", "group", "options",
                                      "autocomplete", "page", "box")}
        if f["party"] in signed and f.get("box"):
            if f["type"] in SIGN_TYPES:
                out["image"] = "%s/f/sig/%s" % (base, f["party"])
            else:
                out["value"] = shown(f, vals.get(f["id"]))
        fields.append(out)
    mine = []
    if me and me["state"] != "signed":
        mine = [{"field": f["id"], "value": vals.get(f["id"])} for f in ev["fields"]
                if f["party"] == me["id"] and f["type"] not in NOT_ASKED and vals.get(f["id"]) is not None]
    v = ev["doc_sha256"][:10]
    return {
        "base": base, "office": {"name": _office()},
        "event": {"title": ev["title"], "doc_name": ev["doc_name"], "sender": ev["sender"], "expires": ev["expires_at"][:10],
                  "status": status, "order": ev["order_mode"],
                  "final_ready": ev["status"] == "complete" and ev.get("final_state") == "ok" and bool(ev.get("final_path")),
                  "final_failed": str(ev.get("final_state") or "").startswith("failed"),
                  "pages": [dict(p, src="%s/f/page/%d?v=%s" % (base, i + 1, v)) for i, p in enumerate(ev["pages"])]},
        "parties": [{"id": p["id"], "label": p["label"], "note": p["note"], "state": p["state"], "code": bool(p["code_hash"]),
                     "signed_at": p["signed_at"] if p["state"] == "signed" else None,
                     "signer": p["signer_name"] if p["state"] == "signed" else None, "blocked": blocked.get(p["id"], "")}
                    for p in ev["parties"]],
        "fields": fields,
        "me": me["id"] if me and me["state"] != "signed" else None,
        "mine": mine,
    }


def _expired(ev: dict) -> bool:
    return fs().clock() >= parse(ev["expires_at"])


def _cookie(ev: dict) -> str:
    return "fill_" + ev["id"]


def _https() -> bool:
    """The signer reached us over https — at this app, or at the edge that forwarded the request (vps1's door)."""
    return request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


def _secret_hash(ev: dict) -> str:
    raw = request.cookies.get(_cookie(ev), "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else ""


#: the claim's cookie lives on every event link, not on one token's path: a new link for the same event («קישור
#: חדש») keeps every side that is being filled in its browser (the second reader); its name carries the event's id
COOKIE_PATH = PUBLIC_PREFIX


def _public_event(token: str) -> tuple[dict | None, str]:
    ev = fs().by_token(token)
    if not ev:
        return None, "missing"
    if ev["status"] in ("draft", "cancelled"):
        return ev, "missing"
    if ev["status"] in ("completing", "complete"):
        return ev, "ok"
    if _expired(ev):
        return ev, "expired"
    return ev, "ok"


# ── the final copy ─────────────────────────────────────────────────────────────────────────────────
def _local(at: str) -> str:
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return str(at)


def certificate(ev: dict, chain_ok: bool) -> dict:
    """The SIGN_CERTIFICATE document (apitools' house renderer) for every side of the event."""
    events = []
    for e in current_app.config["STORE"].events(ev["id"]):
        try:
            data = json.loads(e.get("data") or "{}")
        except (TypeError, ValueError):
            data = {}
        events.append({"when": _local(e["at"]), "what": EVENT_WORDS.get(e["type"], e["type"]) +
                       (" · " + data["side"] if data.get("side") else ""), "ip": _public_ip(data.get("ip") or "")})
    signers = []
    for p in ev["parties"]:
        method = "קישור אחד לכל הצדדים · בחירת צד במכשיר" + (" + קוד אישי שנמסר בנפרד" if p.get("code_hash") else "")
        signers.append({"name": "%s · בשם %s" % (p["signer_name"] or "", p["label"]), "method": method,
                        "when": _local(p["signed_at"] or ""), "ip": _public_ip(p["signer_ip"] or "")})
    n, gaps = len(events), int(ev.get("trail_gaps") or 0)
    if not chain_ok:
        verdict = "אימות שרשרת יומן החתימה נכשל — ראו את יומן החתימה המצורף."
    elif gaps:
        # the chain proves the order of what IS there; what could not be written is said, not hidden (round 3)
        verdict = ("שרשרת יומן החתימה תקינה (%d אירועים), אבל %d פעולות לא נרשמו ביומן בזמן אמת — החתימות עצמן "
                   "שמורות ומוצגות בתעודה." % (n, gaps))
    else:
        verdict = "שרשרת יומן החתימה שלמה (%d אירועים), והמסמך נחתם בידי כל הצדדים כפי שנשלח." % n
    if any(p.get("signer_ip") and not _public_ip(p["signer_ip"]) for p in ev["parties"]):
        verdict += " כתובת רשת שאינה כתובת אינטרנט של החותם (כתובת פנימית של הרשת) אינה מוצגת."
    return {"doc_type": "SIGN_CERTIFICATE", "doc_id": ev["id"], "doc_date": datetime.now().astimezone().strftime("%d/%m/%Y"),
            "certificate": {"envelope": ev["id"], "title": ev["title"], "sender": ev["sender"], "sha_before": ev["doc_sha256"],
                            "signers": signers, "events": events, "verdict": verdict}}


EVENT_WORDS = {
    "event.created": "המסמך הוכן למילוי ולחתימה", "event.sent": "קישור המילוי והחתימה נוצר",
    "event.relinked": "הקישור הונפק מחדש", "event.opened": "הקישור נפתח", "party.claimed": "נבחר צד",
    "party.taken_over": "הצד נלקח ממכשיר אחר", "party.code": "הוזן קוד אישי", "party.signed": "נחתם",
    "event.completed": "כל הצדדים חתמו", "event.cancelled": "האירוע בוטל", "event.sealed": "העותק החתום הופק",
}


def places_of(ev: dict) -> list[dict]:
    """Every place of the event as fillpdf.fill draws it: answers, signatures (one hand per side, everywhere that
    side signs), stamps beside a «…חותמת» signature, and each side's signing date."""
    vals = values_of(ev)
    sides = {p["id"]: p for p in ev["parties"]}
    out = []
    for f in ev["fields"]:
        if not f.get("box"):
            continue
        p = sides.get(f["party"]) or {}
        item = {"page": f["page"], "box": f["box"]}
        if f["type"] in SIGN_TYPES:
            if not p.get("sig_png"):
                continue
            item["image"] = bytes(p["sig_png"])
            if p.get("stamp_img") and f["type"] == "signature":
                item["stamp"] = bytes(p["stamp_img"])
        elif f["type"] == "stamp":
            if not p.get("stamp_img"):
                continue
            item["image"] = bytes(p["stamp_img"])
        else:
            item["text"] = shown(f, vals.get(f["id"]))
        out.append(item)
    return out


class Busy(RuntimeError):
    """The copy is being made or delivered by another call, or is made already: nothing failed."""


def seal(eid: str, *, begun: bool = False) -> dict:
    """Make the final copy of a completed event: draw, certify, seal once, keep, deliver. Run once: begin_seal
    lets one call in (a seal in flight, or a copy already made, refuses the next — the second reader: the office's
    «/complete» could race the seal thread and change the copy under the sides that had downloaded it). `begun`: the
    caller already holds the seal (the office's «/complete» takes it in its request, so a second press is refused)."""
    st, store = fs(), current_app.config["STORE"]
    if not begun and not st.begin_seal(eid):
        raise Busy("העותק החתום כבר הופק, או שהוא מופק ממש עכשיו")
    try:
        return _seal(st, store, eid)
    except Exception as exc:
        # failed only while the copy was being MADE: once it is made (ok), nothing after it un-makes it
        st._x("UPDATE fill_events SET final_state=? WHERE id=? AND final_state='sealing'", ("failed:%s" % str(exc)[:200], eid))
        raise


def _seal(st: "FillStore", store, eid: str) -> dict:
    ev = st.get(eid)
    cfg = clients.config()
    data_dir = current_app.config["DATA_DIR"]
    body = fillpdf.fill(ev["doc_path"], places_of(ev))
    chain_ok, _bad, last = store.chain_ok(eid)
    cert = clients.render_house(cfg["render_url"], certificate(ev, chain_ok))
    if not cert:
        lines = ["שם המסמך: %s" % ev["title"], "השולח: %s" % ev["sender"], "מזהה האירוע: %s" % ev["id"],
                 "טביעת האצבע (SHA-256) של המסמך כפי שנשלח:", ev["doc_sha256"][:32], ev["doc_sha256"][32:]]
        for p in ev["parties"]:
            lines.append("%s — %s · %s · %s" % (p["label"], p["signer_name"] or "", _local(p["signed_at"] or ""),
                                                 _public_ip(p["signer_ip"] or "")
                                                 or ("כתובת פנימית, לא מוצגת" if p["signer_ip"] else "")))
        lines.append("שרשרת יומן החתימה: %s" % ("אימות תקין" if chain_ok else "אימות נכשל"))
        if ev.get("trail_gaps"):
            lines.append("פעולות שלא נרשמו ביומן בזמן אמת: %d (החתימות עצמן שמורות ומוצגות כאן)" % ev["trail_gaps"])
        cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית", lines,
                                        footer="המסמך מולא ונחתם אלקטרונית בידי כל הצדדים.\n"
                                               "החתימה מוצמדת למסמך כולו, ומזהה שינוי בכל בייט אחרי החתימה.")
    body = pdfsign.append_pages(body, cert)
    office = _office()
    key_pem, cert_pem = pdfsign.load_or_create_cert(data_dir, os.environ.get("ESIGN_CERT_P12", ""),
                                                    os.environ.get("ESIGN_CERT_PASS", ""), office=office)
    final = os.path.join(data_dir, "signed", "fill-%s.pdf" % eid)
    tmp_dir = tempfile.mkdtemp(prefix="fill-")
    try:
        staged = os.path.join(tmp_dir, "staged.pdf")
        made = os.path.join(tmp_dir, "signed.pdf")             # the copy is made aside and moved in whole
        with open(staged, "wb") as fh:
            fh.write(body)
        reason, where = "נחתם בידי כל הצדדים: %s" % ev["title"], office or "Digital Office"
        tsa = os.environ.get("ESIGN_TSA_URL", "")
        try:
            pdfsign.sign(staged, made, key_pem, cert_pem, reason=reason, location=where, stamper=pdfsign.timestamper(tsa))
        except Exception:
            if not tsa:
                raise
            if os.path.exists(made):
                os.remove(made)
            pdfsign.sign(staged, made, key_pem, cert_pem, reason=reason, location=where)
        checks = pdfsign.verify(made)
        os.replace(made, final)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    with open(final, "rb") as fh:
        signed = fh.read()
    when = st.clock()
    st.set(eid, status="complete", final_path=final, final_sha256=sha256_bytes(signed), final_state="ok",
           completed_at=iso(when))
    # the copy is made: what follows only records and delivers it, and a failure there is retried, never a reason to
    # undo it
    _audit_after(eid, "event.sealed", {"sha256": sha256_bytes(signed), "pades": checks, "chain_last": last})
    try:
        return _deliver(st, store, ev, eid, signed, checks, last, when, cfg)
    except Exception as exc:
        st.set(eid, drive_state="pending:%s" % str(exc)[:200])
        _warn_office(eid, ev.get("title", eid), "העותק החתום הופק ושמור, אבל לא נמסר ל«קבצים»: %s. «מסירה מחדש» במגירה "
                                                "מוסרת אותו שוב." % str(exc)[:200], ev)
        return {"pades": checks, "drive": {"ok": False, "status": 0, "path": "", "detail": str(exc)[:200]}}


def _screen(ev: dict | None = None) -> str:
    """Where a notice about an event opens: its document in «מסמכים», or «חתימות» there — this app's tile left the
    home and its own /#/m/esign/ opens nothing now (DGO-2169). Relative to the console that shows it (G95)."""
    ref = (ev or {}).get("ref")
    return "/#/m/my-docs/doc/" + urllib.parse.quote(str(ref), safe="") if ref else "/#/m/my-docs/signatures"


def _warn_office(eid: str, title: str, body: str, ev: dict | None = None) -> None:
    """A warning notice to the office about one event (the same notice id as its other notices: one, updated)."""
    try:
        cfg = clients.config()
        clients.notify(cfg["notifications_url"], source_id="esign-fill-%s" % eid, level="warn",
                       title="מילוי וחתימה: %s" % title, body=body, link=_screen(ev))
    except Exception:
        pass


def redeliver(eid: str) -> dict:
    """The copy that IS made, delivered again (to «קבצים», the notice, the stream) — when the delivery failed."""
    st, store = fs(), current_app.config["STORE"]
    ev = st.get(eid)
    with open(ev["final_path"], "rb") as fh:
        signed = fh.read()
    checks = pdfsign.verify(ev["final_path"])
    ok, bad, last = store.chain_ok(eid)
    if not ok:
        # A trail that no longer verifies is never delivered again as if it did (batch 100, dropped-signal-lint: the
        # verdict was unpacked and thrown away). Both callers say an exception: the drawer's 500, or the office's
        # notice with the delivery left pending. The copy stays where it was made.
        raise RuntimeError("יומן החתימה אינו מאומת (רשומה %s), ולכן העותק לא נמסר שוב" % bad)
    return _deliver(st, store, ev, eid, signed, checks, last, st.clock(), clients.config())


def _deliver(st: "FillStore", store, ev: dict, eid: str, signed: bytes, checks: dict, last: str, when, cfg: dict) -> dict:
    # the copy in «קבצים», under the day's folder, where «ארכיון» finds it
    folder = "%s/%s" % (cfg["drive_folder"].strip("/"), when.astimezone().strftime("%Y-%m-%d"))
    name = re.sub(r"[\\/]+", "-", re.sub(r"\.pdf$", "", ev["title"] or ev["doc_name"], flags=re.I))
    put = clients.drive_put(cfg["drive_url"], "/%s/%s — חתום.pdf" % (folder, name), signed)
    trail = pdfsign.certificate_page("יומן חתימה", [json.dumps(e, ensure_ascii=False) for e in store.events(eid)],
                                     footer="יומן החתימה של %s" % eid)
    clients.drive_put(cfg["drive_url"], "/%s/%s — יומן חתימה.pdf" % (folder, name), trail)
    why = str(put["detail"] or put["status"])[:200]
    st.set(eid, drive_path=put["path"] if put["ok"] else None, drive_state="ok" if put["ok"] else "pending:%s" % why)
    who = ", ".join(p["label"] for p in ev["parties"])
    if put["ok"]:
        note = clients.notify(cfg["notifications_url"], source_id="esign-fill-%s" % eid,
                              title="%s נחתם בידי כל הצדדים" % ev["title"],
                              body="חתמו: %s. העותק החתום נשמר ב«קבצים»: %s" % (who, put["path"]),
                              link=_screen(ev), level="info")
    else:
        # «קבצים» refused or did not answer — drive_put says so, it does not raise: the office is warned and has the
        # button, not an «it was saved» with no path (the second reader, round 4)
        note = clients.notify(cfg["notifications_url"], source_id="esign-fill-%s" % eid,
                              title="%s נחתם בידי כל הצדדים — העותק לא נמסר ל«קבצים»" % ev["title"],
                              body="חתמו: %s. העותק החתום הופק ושמור, אבל «קבצים» לא קיבלו אותו (%s). «מסירה מחדש» "
                                   "במגירה מוסרת אותו שוב." % (who, why), link=_screen(ev), level="warn")
    st.set(eid, notice_state="ok" if note["ok"] else "pending")
    clients.publish("esign", "event.completed", "%s נחתם בידי כל הצדדים" % ev["title"], link=_screen(ev),
                    data={"event": eid, "ref": ev["ref"], "drive_path": put["path"] if put["ok"] else None},
                    redis_url=cfg["redis_url"], password=cfg["redis_password"])
    return {"pades": checks, "drive": put}


def seal_later(app: Flask, eid: str, *, begun: bool = False) -> None:
    """The final copy is made beside the request: the last signer gets their answer at once (DGO-2125: a signature
    waited 40 s on a renderer that was down). A failure is said: in the trail, and to the office as a notice that
    names the event and the call that makes the copy again. A seal another call is making is no failure: this one
    ends quietly (the second reader, round 4: a second press of «הפקה מחדש» warned «not made» of a copy in the
    making)."""
    def run():
        with app.app_context():
            try:
                seal(eid, begun=begun)
            except Busy:
                return
            except Exception as exc:
                why = str(exc)[:300]
                try:
                    current_app.config["STORE"].append(eid, "event.seal_failed", {"error": why})
                    ev = fs().get(eid) or {}
                    cfg = clients.config()
                    clients.notify(cfg["notifications_url"], source_id="esign-fill-%s" % eid, level="warn",
                                   title="העותק החתום של %s לא הופק" % ev.get("title", eid),
                                   body="כל הצדדים חתמו, והחתימות שמורות. הפקת העותק נכשלה: %s. "
                                        "מפיקים אותו שוב ב-POST /api/events/%s/complete." % (why, eid),
                                   link=_screen(ev))
                except Exception:
                    pass                                         # the failure is in final_state already
    if app.config.get("FILL_SYNC"):
        run()
    else:
        threading.Thread(target=run, name="fill-seal-%s" % eid, daemon=True).start()


def deliver_later(app: Flask, eid: str) -> None:
    """The made copy delivered again beside the request, the delivery already taken (begin_delivery): two calls to
    «קבצים» of up to two minutes each outlast the drawer's wait (the second reader, round 4). A failure is said."""
    def run():
        with app.app_context():
            try:
                redeliver(eid)
            except Exception as exc:
                fs().set(eid, drive_state="pending:%s" % str(exc)[:200])
                again = fs().get(eid) or {}
                _warn_office(eid, again.get("title", eid),
                             "העותק החתום הופק ושמור, אבל המסירה ל«קבצים» נכשלה שוב: %s" % str(exc)[:200], again)
    threading.Thread(target=run, name="fill-deliver-%s" % eid, daemon=True).start()


def warm_pages(app: Flask, ev: dict) -> None:
    """Every page's picture drawn once, beside the request, as soon as the link exists: the first person to open it
    sees the document at once (a cold page took seconds on the real server — its thumbnail was still blank)."""
    def run():
        for n in range(1, len(ev["pages"]) + 1):
            try:
                fillpdf.render_page(ev["doc_path"], n, 1100, cache_dir=os.path.join(app.config["DATA_DIR"], "pages"),
                                    key=ev["doc_sha256"][:24])
            except Exception:
                return
    if app.config.get("FILL_SYNC"):
        run()
    else:
        threading.Thread(target=run, name="fill-pages-%s" % ev["id"], daemon=True).start()


def sweep(app: Flask) -> list[str]:
    """At start: an event whose every side signed but whose copy was never made (the process stopped in the middle,
    or the seal failed) is sealed again — a signature is never left without its copy (the second reader)."""
    st = app.config["FILL"]
    st._x("UPDATE fill_events SET final_state=NULL WHERE status='completing' AND final_state='sealing'")
    # a delivery the stop cut short is pending again: the drawer offers «מסירה מחדש» for it
    st._x("UPDATE fill_events SET drive_state='pending:stopped' WHERE drive_state='delivering'")
    left = st.unsealed()
    for eid in left:
        seal_later(app, eid)
    return left


# ── routes ─────────────────────────────────────────────────────────────────────────────────────────
def routes(app: Flask) -> Flask:
    """The event's two halves on the app server.py made. Its own store on the same volume."""
    app.config.setdefault("FILL", FillStore(os.environ.get("ESIGN_DB", os.path.join(app.config["DATA_DIR"], "esign.db")),
                                            clock=app.config.get("CLOCK") or utcnow))
    os.makedirs(os.path.join(app.config["DATA_DIR"], "pages"), exist_ok=True)
    static = app.static_folder

    def err(op: str, detail: str, code: int = 400, **more):
        return _json({"ok": False, "op": op, "message": detail, **more}, code)

    #: «opened» kept once an hour per (event, address): {(event, ip): when}
    seen_at: dict = {}
    seen_lock = threading.Lock()

    @app.before_request
    def fill_limits():
        """The public calls: JSON only (a form a stranger's page posts is not one — CSRF), and small: a signature and a
        stamp in /f/sign, a few answers anywhere else (the app's own 40 MB limit is the office's uploads')."""
        if not (request.path.startswith(PUBLIC_PREFIX) and "/f/" in request.path and request.method == "POST"):
            return None
        if not request.is_json:
            return err("public", "the call must be JSON", 415)
        limit = MAX_BODY_SIGN if request.path.endswith("/f/sign") else MAX_BODY
        if (request.content_length or 0) > limit:
            return err("public", "הבקשה גדולה מדי", 413)
        # and a body that does not say its length (chunked) is cut at the same size while it is read (Flask ≥ 3.1)
        request.max_content_length = limit
        return None

    # the office's half (behind the sign-in, as every /api/ of the app)
    @app.post("/api/events")
    def ev_create():
        up = request.files.get("file")
        raw = up.read() if up is not None else b""
        if not raw.startswith(b"%PDF"):
            return err("create", "the file is not a PDF", 415)
        form = request.form
        doc_path = os.path.join(app.config["DATA_DIR"], "docs", "%s.pdf" % secrets.token_hex(8))
        with open(doc_path, "wb") as fh:
            fh.write(raw)
        try:
            hints = json.loads(form.get("hints") or "[]")
        except ValueError:
            hints = []
        pages = fillpdf.page_sizes(doc_path)
        try:
            found = fillpdf.detect(doc_path, hints)
        except Exception as exc:                                # a document we cannot read: the office places by hand
            found = {"parties": [{"id": "p%d" % (i + 1), "label": h, "note": ""} for i, h in enumerate(hints[:2])] or
                     [{"id": "p1", "label": "צד א׳", "note": ""}], "fields": [], "found": None, "error": str(exc)[:200]}
        name = form.get("name") or os.path.basename(up.filename or "document.pdf")
        days = int(form["days"]) if re.fullmatch(r"\d{1,4}", form.get("days") or "") else 30
        ev = fs().create(title=form.get("title") or re.sub(r"\.pdf$", "", name, flags=re.I), doc_name=name,
                         doc_path=doc_path, doc_sha256=sha256_bytes(raw), doc_size=len(raw), pages=pages,
                         sender=form.get("sender") or _office() or "הלשכה", ref=(form.get("ref") or "").strip()[:200] or None,
                         days=days, parties=found["parties"], fields=found["fields"])
        _audit(ev["id"], "event.created", {"doc_name": name, "sha256": ev["doc_sha256"], "pages": len(pages),
                                           "found": len(found["fields"])})
        view = office_view(ev)
        return _json({"ok": True, "event": view, "parties": view["parties"], "fields": view["fields"],
                      "found": found.get("found")})

    @app.get("/api/events")
    def ev_list():
        limit = int(request.args["limit"]) if re.fullmatch(r"\d{1,3}", request.args.get("limit", "")) else 50
        rows = fs().list(ref=(request.args.get("ref") or None), limit=limit)
        return _json({"ok": True, "items": [office_view(e) for e in rows]})

    @app.get("/api/events/<eid>")
    def ev_get(eid):
        ev = fs().get(eid)
        if not ev:
            return err("get", "no such event", 404)
        ok_, bad, last = current_app.config["STORE"].chain_ok(eid)
        return _json({"ok": True, "event": office_view(ev), "events": current_app.config["STORE"].events(eid),
                      "chain": {"ok": ok_, "first_bad": bad, "last_hash": last}})

    @app.post("/api/events/<eid>/send")
    def ev_send(eid):
        ev = fs().get(eid)
        if not ev:
            return err("send", "no such event", 404)
        if ev["status"] != "draft":
            return err("send", "הקישור כבר נוצר לאירוע הזה", 409)
        body = request.get_json(force=True, silent=True) or {}
        parties, fields, why = clean_map(body, ev["pages"])
        if why:
            return err("send", why, 400)
        settings = body.get("settings") or {}
        order = "seq" if settings.get("order") == "seq" else "any"
        expires = None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(settings.get("expires") or "")):
            day = datetime.fromisoformat(settings["expires"]).replace(hour=23, minute=59)
            expires = day.astimezone() if day.tzinfo is None else day
            # a link born expired is no link (a draft reopened days later kept its old date — the second reader)
            if expires <= fs().clock():
                return err("send", "תאריך התוקף כבר עבר — בחרו תאריך עתידי", 400)
        token = fs().open(eid, title=str(body.get("title") or ev["title"]).strip()[:200] or ev["title"], parties=parties,
                          fields=fields, order=order, expires=expires)
        if not token:
            return err("send", "הקישור כבר נוצר לאירוע הזה", 409)
        _audit(eid, "event.sent", {"by": body.get("by") or "office", "parties": [p["label"] for p in parties],
                                   "fields": len(fields), "order": order})
        clients.publish("esign", "event.sent", "נשלח למילוי וחתימה: %s" % ev["title"], data={"event": eid},
                        redis_url=clients.config()["redis_url"], password=clients.config()["redis_password"])
        warm_pages(app, ev)
        return _json({"ok": True, "link": link_for(token), "event": office_view(fs().get(eid))})

    @app.post("/api/events/<eid>/link")
    def ev_relink(eid):
        token = fs().relink(eid)
        if not token:
            return err("link", "the event is not open", 409)
        _audit(eid, "event.relinked", {"by": request.form.get("by") or "office"})
        return _json({"ok": True, "link": link_for(token)})

    @app.post("/api/events/<eid>/cancel")
    def ev_cancel(eid):
        if not fs().cancel(eid, request.form.get("reason") or (request.get_json(silent=True) or {}).get("reason") or ""):
            return err("cancel", "the event is signed or closed", 409)
        _audit(eid, "event.cancelled", {})
        return _json({"ok": True})

    @app.post("/api/events/<eid>/complete")
    def ev_complete(eid):
        ev = fs().get(eid)
        if not ev or ev["status"] not in ("completing", "complete"):
            return err("complete", "not every side has signed", 409)
        if ev.get("final_state") == "sealing":
            return err("complete", "העותק החתום מופק ממש עכשיו", 409)
        if ev.get("final_state") == "ok":
            # made, not delivered: delivered again (round 3) — taken here, so a second press is refused, and done
            # beside the request, which «קבצים» can outlast (round 4)
            if ev.get("drive_state") == "delivering":
                return err("complete", "העותק החתום נמסר ל«קבצים» ממש עכשיו", 409)
            if not fs().begin_delivery(eid):
                return err("complete", "העותק החתום כבר הופק ונמסר", 409)
            if app.config.get("FILL_SYNC"):
                try:
                    out = redeliver(eid)
                except Exception as exc:
                    fs().set(eid, drive_state="pending:%s" % str(exc)[:200])
                    return err("complete", str(exc)[:300], 500)
                return _json({"ok": True, "drive": out["drive"]})
            deliver_later(app, eid)
            return _json({"ok": True, "started": True})
        # the seal is taken in this request: a second press is refused rather than racing it (round 4)
        if not fs().begin_seal(eid):
            return err("complete", "העותק החתום מופק ממש עכשיו", 409)
        if app.config.get("FILL_SYNC"):
            try:
                out = seal(eid, begun=True)
            except Exception as exc:                            # seal() keeps the reason in final_state
                return err("complete", str(exc)[:300], 500)
            return _json({"ok": True, "pades": out["pades"], "drive": out["drive"]})
        # made beside the request: a seal and two deliveries can outlast the caller's wait (the drawer's «הפקה מחדש»
        # said «not made» of a copy that was) — the drawer reads the state again
        seal_later(app, eid, begun=True)
        return _json({"ok": True, "started": True})

    @app.get("/api/events/<eid>/download")
    def ev_download(eid):
        ev = fs().get(eid)
        path = ev and (ev.get("final_path") if ev["status"] == "complete" else ev["doc_path"])
        if not path or not os.path.exists(path):
            return err("download", "no file", 404)
        return send_file(path, mimetype="application/pdf", as_attachment=True,
                         download_name="%s%s.pdf" % (ev["title"], " — חתום" if ev["status"] == "complete" else ""))

    @app.get("/api/events/<eid>/page/<int:n>")
    def ev_page(eid, n):
        ev = fs().get(eid)
        return _page(ev, n, request.args.get("w")) if ev else err("page", "no such event", 404)

    @app.get("/api/events/<eid>/sig/<pid>")
    def ev_sig(eid, pid):
        ev = fs().get(eid)
        return _sig(ev, pid) if ev else err("sig", "no such event", 404)

    def _page(ev, n, width=None):
        # one of three widths (fillpdf.WIDTHS): a width per request was a file per request (the second reader)
        try:
            data, mime = fillpdf.render_page(ev["doc_path"], n, fillpdf.snap_width(width or 1100),
                                             cache_dir=os.path.join(app.config["DATA_DIR"], "pages"),
                                             key=ev["doc_sha256"][:24])
        except (IndexError, ValueError):
            return err("page", "no such page", 404)
        resp = Response(data, mimetype=mime)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    def _sig(ev, pid):
        p = next((p for p in ev["parties"] if p["id"] == pid and p["state"] == "signed" and p.get("sig_png")), None)
        if not p:
            return err("sig", "no signature", 404)
        resp = Response(bytes(p["sig_png"]), mimetype="image/png")
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    # the signer's half: the page, its stylesheet and script, and its calls — all under the one public path
    @app.get(PUBLIC_PREFIX + "fill.css")
    def fill_css():
        return send_file(os.path.join(static, "fill.css"), mimetype="text/css", max_age=3600)

    @app.get(PUBLIC_PREFIX + "fill.js")
    def fill_js():
        return send_file(os.path.join(static, "fill.js"), mimetype="text/javascript", max_age=3600)

    @app.before_request
    def fill_page():
        """/s/<token> of an EVENT is the event's page; an envelope's token falls through to server.py's own page."""
        m = re.fullmatch(r"/s/([A-Za-z0-9_-]{20,})/?", request.path)
        if not m or request.method not in ("GET", "HEAD"):        # HEAD too: a check from outside, a chat's preview
            return None
        ev = fs().by_token(m.group(1))
        if not ev:
            return None
        ev, state = _public_event(m.group(1))
        if state != "ok":
            title, body = (("פג התוקף של הקישור הזה", "אפשר לבקש קישור חדש מהלשכה.") if state == "expired" else
                           ("הקישור הזה אינו בתוקף", "ייתכן שהקישור בוטל, או שהלשכה הנפיקה קישור חדש במקומו."))
            return Response(render_template("sentence.html", title=title, body=body, kind=state),
                            status=410 if state == "expired" else 404, mimetype="text/html")
        me = fs().held_by(ev["id"], _secret_hash(ev))
        resp = make_response(render_template("fill.html", boot=public_view(ev, m.group(1), me)))
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        if not request.cookies.get(VISITOR_COOKIE):
            # this browser, for counting ITS wrong codes (the address is the door's, the same for every visitor)
            resp.set_cookie(VISITOR_COOKIE, secrets.token_urlsafe(18), max_age=60 * 60 * 24 * 120, httponly=True,
                            samesite="Lax", secure=_https(), path=COOKIE_PATH)
        return resp

    def pub(token):
        ev, state = _public_event(token)
        if state != "ok":
            return None, err("public", "הקישור אינו בתוקף", 410 if state == "expired" else 404)
        return ev, None

    @app.get(PUBLIC_PREFIX + "<token>/f/page/<int:n>")
    def pub_page(token, n):
        ev, bad = pub(token)
        return bad or _page(ev, n)

    @app.get(PUBLIC_PREFIX + "<token>/f/sig/<pid>")
    def pub_sig(token, pid):
        ev, bad = pub(token)
        return bad or _sig(ev, pid)

    @app.get(PUBLIC_PREFIX + "<token>/f/state")
    def pub_state(token):
        ev, bad = pub(token)
        if bad:
            return bad
        me = fs().held_by(ev["id"], _secret_hash(ev))
        if me and me["state"] == "filling":
            fs().touch(ev["id"], me["id"], _secret_hash(ev))    # its page is open: the side is not quiet
        return _json({"ok": True, **public_view(ev, token, me)})

    @app.post(PUBLIC_PREFIX + "<token>/f/seen")
    def pub_seen(token):
        ev, bad = pub(token)
        if bad:
            return bad
        key, now_s = (ev["id"], _ip()), fs().clock().timestamp()
        with seen_lock:                                           # one thread at a time in the dict (round 2)
            fresh = now_s - seen_at.get(key, 0) >= SEEN_EVERY_S
            if fresh:
                seen_at[key] = now_s
                if len(seen_at) > 5000:                           # a bounded memory, whatever reaches it
                    for k in sorted(seen_at, key=seen_at.get)[:1000]:
                        seen_at.pop(k, None)
        if fresh:
            _audit_after(ev["id"], "event.opened", {"ip": _ip(), "ua": _ua()})
        return _json({"ok": True})

    @app.post(PUBLIC_PREFIX + "<token>/f/claim")
    def pub_claim(token):
        ev, bad = pub(token)
        if bad:
            return bad
        if ev["status"] != "open":
            return err("claim", "כל הצדדים כבר חתמו על המסמך", 409)
        body = request.get_json(silent=True) or {}
        pid = str(body.get("party") or "")
        side = next((p for p in ev["parties"] if p["id"] == pid), None)
        if not side:
            return err("claim", "אין צד כזה במסמך", 404)
        if ev["order_mode"] == "seq":
            for p in ev["parties"]:
                if p["id"] == pid:
                    break
                if p["state"] != "signed":
                    return err("claim", "הצד הזה יחתום אחרי %s" % p["label"], 409, blocked=p["label"])
        if side["code_hash"]:
            code = str(body.get("code") or "").strip()
            # asking for the code is not a wrong code: only a code typed in counts toward the lock
            visitor = request.cookies.get(VISITOR_COOKIE, "")
            who = ("v:" + hashlib.sha256(visitor.encode("utf-8")).hexdigest()) if visitor else ("ip:" + _ip())
            verdict = fs().code_ok(ev["id"], pid, code, who) if code else "ask"
            if verdict == "ceiling":
                _warn_office(ev["id"], ev["title"], "הצד «%s» ננעל: %d קודים שגויים הוזנו בו מכל המכשירים יחד. הוא "
                             "נפתח שוב בקישור חדש («קישור חדש» במגירה) — שלחו אותו לצדדים, והקישור הקודם מפסיק "
                             "לעבוד." % (side["label"], CODE_CEILING), ev)
                verdict = "closed"
            if verdict != "ok":
                if code:
                    _audit_after(ev["id"], "party.code", {"side": side["label"], "result": verdict, "ip": _ip()})
                return err("claim", {"bad": "הקוד אינו נכון.", "locked": "יותר מדי ניסיונות. נסו שוב מאוחר יותר.",
                                     "closed": "הצד הזה ננעל אחרי ניסיונות רבים מדי. בקשו מהשולח קישור חדש."}
                           .get(verdict, "הצד הזה מוגן בקוד אישי."), 403, need_code=True, verdict=verdict)
        raw = secrets.token_urlsafe(24)                          # a new secret for every claim, never the one brought
        verdict, row = fs().claim(ev["id"], pid, _secret_hash(ev), hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                                  take=bool(body.get("take")))
        if verdict == "signed":
            return err("claim", "הצד הזה כבר חתום", 409)
        if verdict == "busy":
            return err("claim", "הצד הזה נפתח במכשיר אחר לפני דקות ספורות.", 409, busy=True, since=row.get("claimed_at"))
        # the side is this browser's now whatever the trail answers: the cookie must reach it (a `finally` did not —
        # the exception still went up, and the side stayed held by a secret no browser had — round 2)
        _audit_after(ev["id"], "party.taken_over" if verdict == "took" else "party.claimed",
                     {"side": side["label"], "ip": _ip(), "ua": _ua()})
        ev = fs().get(ev["id"])
        me = next(p for p in ev["parties"] if p["id"] == pid)
        view = public_view(ev, token, me)
        resp = _json({"ok": True, "took_over": verdict == "took", "parties": view["parties"], "values": view["mine"]})
        resp.set_cookie(_cookie(ev), raw, max_age=60 * 60 * 24 * 120, httponly=True, samesite="Lax",
                        secure=_https(), path=COOKIE_PATH)
        return resp

    def mine_or_refuse(ev):
        me = fs().held_by(ev["id"], _secret_hash(ev))
        body = request.get_json(silent=True) or {}
        if not me or me["id"] != body.get("party") or me["state"] != "filling":
            return None, body, err("side", "הצד הזה אינו פתוח במכשיר הזה. בחרו אותו שוב.", 409, lost=True)
        return me, body, None

    def answers_of(ev, me, body) -> tuple[dict, dict]:
        given, kept = body.get("values") or {}, values_of(ev)
        vals, errors = {}, {}
        for f in ev["fields"]:
            if f["party"] != me["id"] or f["type"] in NOT_ASKED:
                continue
            v = given.get(f["id"], kept.get(f["id"]))
            if f["type"] == "checkbox":
                v = bool(v) if v is not None else None
            elif v is not None:
                v = str(v).strip()[:MAX_ANSWER]                  # an answer is a few words, never a megabyte
            why = problem(f, v)
            if why:
                errors[f["id"]] = why
            vals[f["id"]] = v
        return vals, errors

    @app.post(PUBLIC_PREFIX + "<token>/f/answers")
    def pub_answers(token):
        ev, bad = pub(token)
        if bad:
            return bad
        me, body, bad = mine_or_refuse(ev)
        if bad:
            return bad
        vals, errors = answers_of(ev, me, body)
        # progress is kept as it is typed — a wrong answer too, so the person finds it where they left it — and only
        # while this browser still holds the side (checked again inside the write)
        if not fs().save_values(ev["id"], me["id"], _secret_hash(ev),
                                {k: v for k, v in vals.items() if k in (body.get("values") or {})}):
            return err("side", "הצד הזה אינו פתוח במכשיר הזה. בחרו אותו שוב.", 409, lost=True)
        return _json({"ok": True, "errors": errors})

    @app.post(PUBLIC_PREFIX + "<token>/f/sign")
    def pub_sign(token):
        ev, bad = pub(token)
        if bad:
            return bad
        if ev["status"] != "open":
            return err("sign", "כל הצדדים כבר חתמו על המסמך", 409)
        me, body, bad = mine_or_refuse(ev)
        if bad:
            return bad
        vals, errors = answers_of(ev, me, body)
        if errors:
            return err("sign", "יש פרטים שצריך לתקן", 400, errors=errors)
        if body.get("consent") is not True:
            return err("sign", "כדי לחתום, סמנו שקראתם את המסמך ושאתם מסכימים לחתום עליו.", 400)
        sig_in = body.get("signature") or {}
        # the hand is kept in the paper's ink, whatever the signer's screen drew it in (a phone in dark mode drew it in
        # near-white), and only as a picture of a sane size (a small file may decode to a huge one)
        sig = _image(sig_in.get("image"), MAX_SIG, ("png",))
        sig = fillpdf.ink_png(sig) if sig else None
        if not sig:
            return err("sign", "החתימה לא התקבלה. חתמו שוב בתוך המסגרת.", 400)
        stamp = _image(body.get("stamp"), MAX_STAMP, ("png", "jpeg")) if body.get("stamp") else None
        if stamp is not None and not fillpdf.picture_ok(stamp):
            return err("sign", "תמונת החותמת גדולה מדי. צלמו אותה שוב.", 400)
        # the name a signature is shown under: a name the page itself shows, else the typed hand, else the side —
        # never an answer the page does not show (that one is not public)
        name_f = next((f for f in ev["fields"] if f["party"] == me["id"] and f["type"] == "name" and f.get("box")
                       and vals.get(f["id"])), None)
        signer = (vals.get(name_f["id"]) if name_f else "") or str(sig_in.get("text") or "").strip()[:120] or me["label"]
        today = datetime.now().astimezone().strftime("%d.%m.%Y")
        dates = {f["id"]: today for f in ev["fields"] if f["party"] == me["id"] and f["type"] == "date_signed"}
        done, last = fs().sign(ev["id"], me["id"], _secret_hash(ev), values=vals, signer=signer, ip=_ip(), ua=_ua(),
                               kind="type" if sig_in.get("kind") == "type" else "draw", sig=sig, stamp=stamp, dates=dates)
        if not done:
            return err("sign", "הצד הזה כבר נחתם, או נפתח במכשיר אחר.", 409)
        # the hand IS signed: the trail, the stream and the notice follow it, and none of them can turn it into an error
        # for the signer (round 2: an exception after the signature answered 500 — «not saved» — to a saved hand)
        _audit_after(ev["id"], "party.signed", {"side": me["label"], "signer": signer, "ip": _ip(), "ua": _ua(),
                                                "kind": "type" if sig_in.get("kind") == "type" else "draw",
                                                "signature_sha256": sha256_bytes(sig), "stamp": bool(stamp),
                                                "answers_sha256": sha256_bytes(json.dumps(vals, ensure_ascii=False,
                                                                                          sort_keys=True).encode("utf-8")),
                                                "consent": "קראתי את המסמך, ואני מסכים/ה לחתום עליו אלקטרונית בשם %s"
                                                           % me["label"]})
        cfg = clients.config()
        clients.publish("esign", "party.signed", "%s חתם/ה על %s בשם %s" % (signer, ev["title"], me["label"]),
                        data={"event": ev["id"], "side": me["label"]},
                        redis_url=cfg["redis_url"], password=cfg["redis_password"])
        if not last:
            # the office hears of each signature, not only of the last: «the client signed» is the news it waits for
            # (the same notice as the event's completion — one notice per event, updated)
            done_n = sum(1 for p in ev["parties"] if p["state"] == "signed") + 1
            clients.notify(cfg["notifications_url"], source_id="esign-fill-%s" % ev["id"], level="info",
                           title="%s חתם/ה על %s בשם %s" % (signer, ev["title"], me["label"]),
                           body="%d מתוך %d צדדים חתמו. כשכולם יחתמו, העותק החתום יישמר ב«קבצים»."
                                % (done_n, len(ev["parties"])), link=_screen(ev))
        else:
            _audit_after(ev["id"], "event.completed", {"sides": len(ev["parties"])})
            seal_later(current_app._get_current_object(), ev["id"])   # the last signature always starts the copy
        ev = fs().get(ev["id"])
        view = public_view(ev, token, None)
        return _json({"ok": True, "event": view["event"], "parties": view["parties"], "fields": view["fields"]})

    @app.get(PUBLIC_PREFIX + "<token>/f/final")
    def pub_final(token):
        ev, bad = pub(token)
        if bad:
            return bad
        if ev["status"] != "complete" or not ev.get("final_path") or not os.path.exists(ev["final_path"]):
            return err("final", "העותק החתום עוד לא מוכן", 409)
        resp = send_file(ev["final_path"], mimetype="application/pdf", as_attachment=True,
                         download_name="%s — חתום.pdf" % ev["title"])
        resp.headers["Cache-Control"] = "no-store"
        return resp

    sweep(app)                                                    # a copy left unmade by a stop is made now
    return app
