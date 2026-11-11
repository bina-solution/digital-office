"""db — the one Postgres handle this service uses.

Split out of adapters/local.py so that profiles.py and bootstrap.py can talk to the same database
WITHOUT importing the adapter package (adapters/__init__ imports connections_client, which would
close an import cycle the moment the profile store needed a query).

Nothing here knows what a table means. `q` runs one statement and hands back rows; `tx` holds one
transaction open for a block of them. Ownership of every statement stays with the module that
declares the table.

POOLED (2026-10-28). Every statement used to open its own connection — a TCP handshake and a
Postgres backend per query, several per request. The workers are threaded now (gunicorn.conf.py),
so one small thread-safe pool per worker serves them all; a connection the server dropped is
discarded and the statement retried once on a fresh one.
"""
import os
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as _pool

DB = dict(host=os.environ.get("PGHOST", "supabase-db"), port=int(os.environ.get("PGPORT", "5432")),
          dbname=os.environ.get("PGDATABASE", "postgres"), user=os.environ.get("PGUSER", "postgres"),
          password=os.environ.get("SUPABASE_DB_PASSWORD", ""), connect_timeout=10)

_POOL = None
_POOL_LOCK = threading.Lock()


def _pool_get():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = _pool.ThreadedConnectionPool(1, int(os.environ.get("DRIVE_DB_POOL", "10")), **DB)
    return _POOL


@contextmanager
def _conn():
    p = _pool_get()
    c = p.getconn()
    broken = False
    try:
        yield c
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    finally:
        if not broken and not c.closed:
            try:
                c.rollback()            # nothing a caller left open survives into the next borrower
            except Exception:
                broken = True
        p.putconn(c, close=broken or bool(c.closed))


def q(sql, args=()):
    """Run one statement in its own transaction; rows when it returns any, else []."""
    for attempt in (1, 2):
        try:
            with _conn() as c:
                with c.cursor() as cur:
                    cur.execute(sql, args)
                    rows = cur.fetchall() if cur.description else []
                c.commit()
                return rows
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if attempt == 2:
                raise


@contextmanager
def tx():
    """`with tx() as cur:` — one transaction for a block of statements, committed when the block
    ends and rolled back when it raises. What a get-or-create or a recursive delete needs, so that
    two workers cannot each create the same folder or half-delete one tree."""
    with _conn() as c:
        with c.cursor() as cur:
            yield cur
        c.commit()


def try_advisory_lock(key):
    """Best-effort cross-worker mutex, held only for the length of this one statement — see
    `advisory_lock` below for one held across a block."""
    return bool(q("SELECT pg_try_advisory_lock(%s)", (int(key),))[0][0])


class advisory_lock:  # noqa: N801 — used as a context manager, reads as a statement
    """`with advisory_lock(k) as got:` — holds the lock for the whole block, or reports it was taken.

    Keeping the connection open is the point: pg advisory locks are owned by a SESSION, so a lock
    taken on a connection that is immediately closed protects nothing. It is a connection of its
    own, outside the pool, because the pool would hand the session (and its lock) to someone else.
    """

    def __init__(self, key):
        self.key = int(key)
        self.conn = None

    def __enter__(self):
        try:
            self.conn = psycopg2.connect(**DB)
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
                got = bool(cur.fetchone()[0])
            if not got:
                self._close()
            return got
        except Exception:
            self._close()
            return False

    def _close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __exit__(self, *_exc):
        # closing the session releases the lock; no explicit unlock needed and none that can leak
        self._close()
        return False
