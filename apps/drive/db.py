"""db — the one Postgres handle this service uses.

Split out of adapters/local.py so that profiles.py and bootstrap.py can talk to the same database
WITHOUT importing the adapter package (adapters/__init__ imports connections_client, which would
close an import cycle the moment the profile store needed a query).

Nothing here knows what a table means. `q` runs SQL and hands back rows; ownership of every
statement stays with the module that declares the table.
"""
import os

import psycopg2

DB = dict(host=os.environ.get("PGHOST", "supabase-db"), port=5432,
          dbname="postgres", user="postgres",
          password=os.environ.get("SUPABASE_DB_PASSWORD", ""))


def q(sql, args=()):
    with psycopg2.connect(**DB) as c, c.cursor() as cur:
        cur.execute(sql, args)
        if cur.description:
            return cur.fetchall()
        return []


def try_advisory_lock(key):
    """Best-effort cross-worker mutex.

    gunicorn runs this service with several workers and each one boots the profile reconciler. Two
    workers reconciling the same declaration at the same instant would each see "no instance" and
    each mint one — two vault instances, two keys, one profile. A Postgres advisory lock is the
    cheapest mutex that both workers can actually see (a process-local lock cannot).

    Returns True when THIS connection holds the lock. The lock is released when the connection
    closes, which `q`'s context manager does at the end of every call — so it is held for exactly
    the length of this check and the caller must serialise itself by other means if it needs more.
    Hence `with_advisory_lock` below, which keeps ONE connection open for the whole critical section.
    """
    return bool(q("SELECT pg_try_advisory_lock(%s)", (int(key),))[0][0])


class advisory_lock:  # noqa: N801 — used as a context manager, reads as a statement
    """`with advisory_lock(k) as got:` — holds the lock for the whole block, or reports it was taken.

    Keeping the connection open is the point: pg advisory locks are owned by a SESSION, so a lock
    taken on a connection that is immediately closed protects nothing.
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
