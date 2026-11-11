"""The office's signing envelope store, and the audit trail that is the evidence.

Two tables on the app's own volume: `envelopes` (one document, one signer, one link) and `events` (the
audit trail, hash-chained). Nothing here knows about HTTP, PDFs or the drive — the server composes them.

Why the hash chain: the law puts the burden of proving that the other side signed on the party that
designed the way of signing (חוק חתימה אלקטרונית §3א — see ai/context/research/dgo-1631-esign.md), and
the office designs the link. One altered event breaks every later link, so the trail on the paper is
worth something in an argument.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

try:                                     # argon2 when the image has it, scrypt when it does not
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _PH = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
except Exception:                        # pragma: no cover - exercised by the fallback test
    PasswordHasher = None               # type: ignore
    _PH = None

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS envelopes (
  id            TEXT PRIMARY KEY,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  status        TEXT NOT NULL,          -- draft | sent | opened | signed | declined | cancelled
  doc_name      TEXT NOT NULL,
  doc_path      TEXT NOT NULL,
  doc_sha256    TEXT NOT NULL,
  doc_size      INTEGER NOT NULL,
  signer_name   TEXT NOT NULL,
  signer_email  TEXT,
  sender        TEXT NOT NULL,
  page          INTEGER NOT NULL DEFAULT 1,
  box           TEXT,
  pw_hash       TEXT,
  token_hash    TEXT NOT NULL UNIQUE,
  attempts      INTEGER NOT NULL DEFAULT 0,
  locked_until  TEXT,
  opened_at     TEXT,
  opened_ip     TEXT,
  opened_ua     TEXT,
  signed_at     TEXT,
  signed_path   TEXT,
  signed_sha256 TEXT,
  signer_ip     TEXT,
  signer_ua     TEXT,
  drive_path    TEXT,
  drive_state   TEXT,
  notice_state  TEXT,
  closed_reason TEXT
);
CREATE TABLE IF NOT EXISTS events (
  envelope_id TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  at          TEXT NOT NULL,
  type        TEXT NOT NULL,
  data        TEXT NOT NULL,
  prev        TEXT NOT NULL,
  hash        TEXT NOT NULL,
  PRIMARY KEY (envelope_id, seq)
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def canonical(payload: dict) -> str:
    """The bytes a hash is taken over: same dict, same string, on any machine."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_password(password: str) -> str:
    if _PH is not None:
        return _PH.hash(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$1$%s$%s" % (salt.hex(), dk.hex())


def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    if stored.startswith("scrypt$"):
        _, _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    if _PH is None:                      # pragma: no cover
        return False
    try:
        return _PH.verify(stored, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


class Store:
    """One connection, one volume, no ORM. `clock` is injectable so the tests can move time."""

    def __init__(self, path: str, clock: Callable[[], datetime] = utcnow):
        self.path = path
        self.clock = clock
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── envelopes ──────────────────────────────────────────────────────────────────────────────────
    def create(self, *, doc_name: str, doc_path: str, doc_sha256: str, doc_size: int,
               signer_name: str, sender: str, days: int = 14, page: int = 1,
               box: Iterable[float] | None = None, password: str | None = None,
               signer_email: str = "") -> dict:
        now = self.clock()
        token = secrets.token_urlsafe(32)
        eid = secrets.token_hex(8)
        row = dict(
            id=eid, created_at=iso(now), expires_at=iso(now + timedelta(days=max(days, 0))),
            status="draft", doc_name=doc_name, doc_path=doc_path, doc_sha256=doc_sha256,
            doc_size=doc_size, signer_name=signer_name, signer_email=signer_email or None,
            sender=sender, page=max(int(page or 1), 1),
            box=json.dumps(list(box)) if box else None,
            pw_hash=hash_password(password) if password else None,
            token_hash=token_hash(token), attempts=0,
        )
        cols = ",".join(row)
        marks = ",".join("?" for _ in row)
        self.conn.execute(f"INSERT INTO envelopes ({cols}) VALUES ({marks})", tuple(row.values()))
        self.conn.commit()
        out = dict(row)
        out["token"] = token             # returned once, never stored
        return out

    def get(self, eid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM envelopes WHERE id=?", (eid,)).fetchone()
        return dict(row) if row else None

    def by_token(self, token: str) -> dict | None:
        if not token or len(token) < 20:
            return None
        row = self.conn.execute("SELECT * FROM envelopes WHERE token_hash=?",
                                (token_hash(token),)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM envelopes ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def set(self, eid: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE envelopes SET {cols} WHERE id=?", (*fields.values(), eid))
        self.conn.commit()

    def expired(self, env: dict) -> bool:
        return self.clock() >= parse(env["expires_at"])

    def usable(self, env: dict | None) -> bool:
        """A link works while it is sent-and-not-closed; a closed link answers nothing but a sentence."""
        if not env:
            return False
        if env["status"] in ("cancelled", "declined", "signed"):
            return False
        return not self.expired(env)

    # ── the password gate ──────────────────────────────────────────────────────────────────────────
    def unlock(self, env: dict, password: str) -> str:
        """`ok` | `bad` | `locked` | `none`. A wrong password costs an attempt; five cost 15 minutes."""
        now = self.clock()
        if env.get("locked_until") and now < parse(env["locked_until"]):
            return "locked"
        if not env.get("pw_hash"):
            return "none"
        if verify_password(env["pw_hash"], password or ""):
            self.set(env["id"], attempts=0, locked_until=None)
            return "ok"
        attempts = int(env.get("attempts") or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            self.set(env["id"], attempts=0,
                     locked_until=iso(now + timedelta(minutes=LOCK_MINUTES)))
            return "locked"
        self.set(env["id"], attempts=attempts)
        return "bad"

    # ── the audit trail ────────────────────────────────────────────────────────────────────────────
    def claim_signature(self, eid: str) -> bool:
        """One signer, one signature: the row moves to `signing` only from a state a sign may leave.

        Two windows posting the same link at the same moment used to stamp the document twice; this is
        the atomic step (one UPDATE, checked by its own row count) that makes the second one lose.
        """
        cur = self.conn.execute(
            "UPDATE envelopes SET status='signing' WHERE id=? AND status IN ('draft','sent','opened')",
            (eid,))
        self.conn.commit()
        return cur.rowcount == 1

    def append(self, eid: str, type_: str, data: dict | None = None) -> dict:
        for attempt in (0, 1):
            try:
                return self._append_once(eid, type_, data)
            except sqlite3.IntegrityError:
                if attempt:      # a concurrent writer took the sequence; the caller must not lose the event
                    raise
        raise RuntimeError("unreachable")

    def _append_once(self, eid: str, type_: str, data: dict | None = None) -> dict:
        prev = self.last_hash(eid)
        seq = (self.conn.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE envelope_id=?",
                                 (eid,)).fetchone()[0]) + 1
        at = iso(self.clock())
        body = {"seq": seq, "at": at, "type": type_, "data": data or {}, "prev": prev}
        digest = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
        self.conn.execute(
            "INSERT INTO events (envelope_id,seq,at,type,data,prev,hash) VALUES (?,?,?,?,?,?,?)",
            (eid, seq, at, type_, canonical(data or {}), prev, digest))
        self.conn.commit()
        return {**body, "hash": digest}

    def events(self, eid: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE envelope_id=? ORDER BY seq", (eid,)).fetchall()
        return [dict(r) for r in rows]

    def last_hash(self, eid: str) -> str:
        row = self.conn.execute(
            "SELECT hash FROM events WHERE envelope_id=? ORDER BY seq DESC LIMIT 1", (eid,)).fetchone()
        return row[0] if row else ""

    def chain_ok(self, eid: str) -> tuple[bool, int | None, str]:
        """(ok, first bad seq, last hash). Recomputed from the events, never trusted from a column."""
        prev = ""
        for ev in self.events(eid):
            body = {"seq": ev["seq"], "at": ev["at"], "type": ev["type"],
                    "data": json.loads(ev["data"]), "prev": prev}
            digest = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
            if digest != ev["hash"] or ev["prev"] != prev:
                return False, ev["seq"], prev
            prev = digest
        return True, None, prev
