"""doc_data DB layer — Postgres (Supabase) is the source of truth.

Connection comes from env, in priority order:
  DOC_DB_DSN                                  full libpq DSN / URL
  DOC_DB_HOST/PORT/NAME/USER/PASSWORD         components
  SUPABASE_DB_HOST/.../SUPABASE_DB_PASSWORD   the deployment's Supabase Postgres
If none resolve (standalone dev / unit tests), falls back to a local SQLite file so
the layer still works without a database — but Postgres is the intended backend.

The rest of doc_data speaks a tiny dialect-neutral SQL through `Cursor`: write `%s`
placeholders and `now()`; SQLite mode rewrites them. JSON columns are dict-in/dict-out;
the bytea/blob artifact column is bytes-in/bytes-out.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

from src.utils.logging_config import get_logger

logger = get_logger('apitools.db')

_LOCK = threading.Lock()
_STATE = {'conn': None, 'pg': None, 'schema_done': False, 'generation': 0}

# ── Connection recovery ───────────────────────────────────────────────────────
# This module used to cache the connection in a module global and NEVER reset it: a
# connection broken by a tunnel drop or a DB restart stayed broken for the life of the
# worker process. The estate only recovered from the 2026-08-11 split because
# gunicorn.conf.py's `max_requests = 50` recycles every worker after ~35-65 requests,
# so poisoned connections were discarded within minutes -- recovery by accident, from a
# setting whose stated rationale is memory. Raise max_requests back to 1000 and the same
# blip becomes a multi-hour outage. Reconnect is now explicit and by design; max_requests
# is a backstop, not the mechanism. See _reset()/Cursor.run() below.
#
# psycopg2 signals a dead connection as OperationalError or InterfaceError. Both inherit
# from Error; DataError/IntegrityError/ProgrammingError do NOT indicate a dead socket and
# must NOT trigger a reconnect (a constraint violation is not a network problem).
def _conn_errors():
    try:
        import psycopg2
        return (psycopg2.OperationalError, psycopg2.InterfaceError)
    except Exception:  # noqa: BLE001 — psycopg2 absent in the SQLite dev path
        return ()


# A dead ssh -R listener ACCEPTS the TCP connection and then never speaks Postgres, so a
# bare connect can hang for the kernel's default (minutes). connect_timeout bounds the
# handshake and the keepalives bound a session that dies mid-query -- without them a
# worker blocks for `timeout` (300s) holding the process lock every other request needs.
_CONNECT_TIMEOUT = os.getenv('DOC_DB_CONNECT_TIMEOUT', '8')
_KEEPALIVES = (f"keepalives=1 keepalives_idle={os.getenv('DOC_DB_KEEPALIVE_IDLE', '15')} "
               f"keepalives_interval={os.getenv('DOC_DB_KEEPALIVE_INTERVAL', '5')} "
               f"keepalives_count={os.getenv('DOC_DB_KEEPALIVE_COUNT', '3')}")

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS business_documents (
  id            TEXT PRIMARY KEY,
  doc_number    TEXT,
  doc_type      TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'draft',
  series        TEXT NOT NULL DEFAULT 'A',
  tax_year      TEXT,
  seq_number    INTEGER,
  issuer_id     TEXT,
  customer_id   TEXT,
  customer_name TEXT,
  currency      TEXT DEFAULT 'ILS',
  subtotal      NUMERIC, discount NUMERIC, vat NUMERIC, total NUMERIC,
  allocation_number TEXT, allocation_status TEXT DEFAULT 'none',
  model         JSONB NOT NULL,
  truth         JSONB,
  pdf           BYTEA,
  file_ext      TEXT DEFAULT 'pdf',
  original_served_at TIMESTAMPTZ,
  cancels       TEXT,
  cancelled_by  TEXT,
  converted_from TEXT,
  signature     BYTEA,                     -- detached CMS/PKCS#7 over the PDF
  signer        TEXT,
  signed_at     TIMESTAMPTZ,
  sig_certified BOOLEAN DEFAULT false,      -- true only with a certified CA cert
  chain_hash    TEXT,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now(),
  issued_at     TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bizdoc_number ON business_documents (doc_number) WHERE doc_number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_bizdoc_seq ON business_documents (doc_type, series, tax_year, seq_number) WHERE seq_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_bizdoc_status ON business_documents (status);
CREATE INDEX IF NOT EXISTS ix_bizdoc_customer ON business_documents (customer_id);
CREATE TABLE IF NOT EXISTS business_document_events (
  id SERIAL PRIMARY KEY, doc_id TEXT, ts TIMESTAMPTZ DEFAULT now(),
  actor TEXT DEFAULT 'api', action TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS business_sequences (
  doc_type TEXT NOT NULL, series TEXT NOT NULL, tax_year TEXT NOT NULL,
  next_seq INTEGER NOT NULL, PRIMARY KEY (doc_type, series, tax_year)
);
CREATE TABLE IF NOT EXISTS business_consents (
  customer_id TEXT NOT NULL, granted_at TIMESTAMPTZ DEFAULT now(),
  method TEXT NOT NULL, withdrawn_at TIMESTAMPTZ, PRIMARY KEY (customer_id, granted_at)
);
CREATE TABLE IF NOT EXISTS business_settings (
  id TEXT PRIMARY KEY DEFAULT 'default',
  onboarded BOOLEAN DEFAULT false,
  name TEXT, company_id TEXT, business_type TEXT DEFAULT 'murshe',
  street TEXT, city TEXT, zip TEXT, phone TEXT, fax TEXT, email TEXT,
  logo_b64 TEXT, vat_pct NUMERIC DEFAULT 18, vat_registered BOOLEAN DEFAULT true,
  default_series TEXT DEFAULT 'A', doc_start INTEGER DEFAULT 0,
  bank_name TEXT, bank_branch TEXT, bank_account TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY, name TEXT, company_id TEXT, street TEXT, city TEXT, zip TEXT,
  phone TEXT, email TEXT, notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, name TEXT, sku TEXT, description TEXT, unit TEXT,
  unit_price NUMERIC, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
"""

SCHEMA_SQLITE = (SCHEMA_PG
                 .replace('JSONB', 'TEXT').replace('BYTEA', 'BLOB')
                 .replace('TIMESTAMPTZ DEFAULT now()', "TEXT DEFAULT (datetime('now'))")
                 .replace('TIMESTAMPTZ', 'TEXT').replace('NUMERIC', 'REAL')
                 .replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
                 .replace(' WHERE doc_number IS NOT NULL', '')
                 .replace(' WHERE seq_number IS NOT NULL', ''))

JSON_COLS = {'model', 'truth'}


def _dsn():
    if os.getenv('DOC_DB_DSN'):
        # Caller-supplied DSN/URL is used verbatim -- appending keywords to an arbitrary
        # libpq URL is not safely composable. Put connect_timeout/keepalives in it yourself.
        return os.getenv('DOC_DB_DSN')
    host = os.getenv('DOC_DB_HOST') or os.getenv('SUPABASE_DB_HOST')
    if not host:
        return None
    return (f"host={host} port={os.getenv('DOC_DB_PORT') or os.getenv('SUPABASE_DB_PORT', '5432')} "
            f"dbname={os.getenv('DOC_DB_NAME') or os.getenv('SUPABASE_DB_NAME', 'postgres')} "
            f"user={os.getenv('DOC_DB_USER') or os.getenv('SUPABASE_DB_USER', 'postgres')} "
            f"password={os.getenv('DOC_DB_PASSWORD') or os.getenv('SUPABASE_DB_PASSWORD', '')} "
            f"connect_timeout={_CONNECT_TIMEOUT} {_KEEPALIVES}")


def dsn_configured():
    """True when a Postgres DSN is configured (i.e. the SQLite dev fallback is NOT in play).

    Lets callers tell 'the shared DB is DOWN' (an incident worth failing on) apart from
    'this process has no shared DB' (unit tests, standalone dev)."""
    return _dsn() is not None


# idempotent column additions so existing tables upgrade (CREATE IF NOT EXISTS won't).
MIGRATIONS = [
    "ALTER TABLE business_documents ADD COLUMN IF NOT EXISTS converted_from TEXT",
    "ALTER TABLE business_documents ADD COLUMN IF NOT EXISTS signature BYTEA",
    "ALTER TABLE business_documents ADD COLUMN IF NOT EXISTS signer TEXT",
    "ALTER TABLE business_documents ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ",
    "ALTER TABLE business_documents ADD COLUMN IF NOT EXISTS sig_certified BOOLEAN DEFAULT false",
    "ALTER TABLE business_settings ADD COLUMN IF NOT EXISTS doc_start INTEGER DEFAULT 0",
]


def _connect():
    dsn = _dsn()
    if dsn:
        import psycopg2
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        # RECONNECTS SKIP THE SCHEMA PASS. SCHEMA_PG + MIGRATIONS is ~14 round trips; over
        # the portable's 145ms-RTT tunnel that is ~2s, and paying it on every recovery
        # would make reconnect look like a hang. The schema is process-wide idempotent
        # state -- once this process has ensured it against this DSN, it is ensured.
        if not _STATE['schema_done']:
            with conn.cursor() as c:
                c.execute(SCHEMA_PG)
                for mig in MIGRATIONS:
                    try:
                        c.execute(mig)
                    except Exception:
                        conn.rollback()
            conn.commit()
            _STATE['schema_done'] = True
        return conn, True
    # dev fallback
    from src.utils.storage import storage_path
    path = os.path.join(storage_path(), 'business_documents.db')
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA_SQLITE)
    conn.commit()
    return conn, False


def _reset(reason=''):
    """Drop the cached connection so the next _conn() dials a fresh one.

    Called on connection-shaped errors only (see _conn_errors). Closing is best-effort:
    a socket that just failed will often fail to close too, and that must not mask the
    original error."""
    conn = _STATE['conn']
    _STATE['conn'] = None
    _STATE['pg'] = None
    _STATE['generation'] += 1
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("doc_data DB connection reset (gen %s): %s",
                       _STATE['generation'], reason)


def _conn():
    conn = _STATE['conn']
    if conn is not None:
        # psycopg2 sets .closed non-zero when the backend went away; sqlite3 has no such
        # attribute, hence the getattr. Cheap enough to check on every cursor.
        if getattr(conn, 'closed', 0):
            _reset('connection marked closed')
            conn = None
    if conn is None:
        _STATE['conn'], _STATE['pg'] = _connect()
    return _STATE['conn'], _STATE['pg']


def is_postgres():
    _conn()
    return _STATE['pg']


def ping(timeout=3.0):
    """Bounded liveness check on a SEPARATE short-lived connection.

    Not the shared one, and not behind _LOCK: a readiness probe must never queue behind
    an in-flight query, or a busy instance reports itself dead. Raises on failure so the
    caller sees why."""
    dsn = _dsn()
    if not dsn:
        return True                      # SQLite dev fallback is always 'reachable'
    import psycopg2
    if 'connect_timeout' not in dsn:
        dsn = f"{dsn} connect_timeout={int(max(1, timeout))}"
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as c:
            # A statement timeout matters as much as connect_timeout here: a dead ssh -R
            # listener completes the TCP handshake and then goes silent, so the failure
            # arrives (if ever) as a hung query, not a refused connection.
            c.execute("SET LOCAL statement_timeout = %s", (int(timeout * 1000),))
            c.execute("SELECT 1")
            c.fetchone()
        return True
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


class Cursor:
    """Context manager yielding a dialect-adapted cursor over the shared connection.
    Commits on clean exit, rolls back on exception. Serialised by a process lock so
    gapless-sequence allocation and row chaining stay atomic."""

    def __enter__(self):
        _LOCK.acquire()
        try:
            self.conn, self.pg = _conn()
            self.cur = self.conn.cursor()
        except BaseException:
            _LOCK.release()          # never strand the lock on a failed connect
            raise
        self._did_work = False       # no statement has run -> a retry is still safe
        return self

    def _sql(self, sql):
        return sql if self.pg else sql.replace('%s', '?').replace('now()', "datetime('now')")

    def _enc(self, args):
        if self.pg:
            from psycopg2.extras import Json
            return tuple(Json(a) if isinstance(a, (dict, list)) else a for a in (args or ()))
        return tuple(json.dumps(a, ensure_ascii=False) if isinstance(a, (dict, list)) else a
                     for a in (args or ()))

    def run(self, sql, args=()):
        try:
            self.cur.execute(self._sql(sql), self._enc(args))
        except _conn_errors() as e:
            # RETRY EXACTLY ONCE, AND ONLY BEFORE ANY STATEMENT HAS SUCCEEDED in this
            # cursor. At that point nothing has been written and no transaction state
            # exists, so redialling and replaying is genuinely idempotent. Retrying the
            # 2nd statement of a multi-statement unit would silently split a transaction
            # that the gapless-sequence allocation depends on being atomic -- so we do
            # not: later failures propagate, and the reset in __exit__ makes the NEXT
            # request reconnect. Without this, a broken socket persists for the life of
            # the worker (~35-65 requests) and every one of them fails.
            if self._did_work:
                raise
            _reset(f'{type(e).__name__} on first statement: {e}')
            self.conn, self.pg = _conn()
            self.cur = self.conn.cursor()
            self.cur.execute(self._sql(sql), self._enc(args))
        self._did_work = True
        return self

    def one(self):
        row = self.cur.fetchone()
        return self._row(row)

    def all(self):
        return [self._row(r) for r in self.cur.fetchall()]

    def _row(self, row):
        if row is None:
            return None
        cols = [d[0] for d in self.cur.description]
        rec = dict(zip(cols, row))
        for k in JSON_COLS:
            if isinstance(rec.get(k), (str, bytes)):
                try:
                    rec[k] = json.loads(rec[k])
                except Exception:
                    pass
        if isinstance(rec.get('pdf'), memoryview):
            rec['pdf'] = bytes(rec['pdf'])
        return rec

    def __exit__(self, exc_type, exc, tb):
        broken = None
        try:
            if exc_type:
                if _conn_errors() and issubclass(exc_type, _conn_errors()):
                    broken = f'{exc_type.__name__}: {exc}'
                self.conn.rollback()
            else:
                self.conn.commit()
        except BaseException as e:      # rollback/commit itself failing == dead socket
            if _conn_errors() and isinstance(e, _conn_errors()):
                broken = broken or f'{type(e).__name__} on finish: {e}'
                if not exc_type:
                    raise               # a failed COMMIT must not look like success
            else:
                raise
        finally:
            try:
                self.cur.close()
            except Exception:  # noqa: BLE001
                pass
            if broken:
                # The next Cursor dials a fresh connection instead of inheriting this
                # one. This is the reconnect path that used to not exist.
                _reset(broken)
            _LOCK.release()
