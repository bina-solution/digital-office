#!/usr/bin/env python3
"""Bounded retention for public.ocr_cache — the only table in this database that grows
without limit, and the only one with no eviction path.

WHAT THE NUMBERS SAY (MEASURED 2026-08-11)
------------------------------------------
    ocr_cache            316 MB / 8,440 rows  = 65% of the whole database
    growth               ~100 MB/day (08-09: 2,140 rows/84MB · 08-10: 2,911/114MB)
    db volume free       869 GB
    ocr_json storage     EXTENDED, already TOASTed and compressed (322 MB toast relation)
    avg row              37 KB compressed, max 548 KB
    referenced by a live incoming_documents row:   7,632 of 8,440  (90.4%)
    UNREFERENCED:                                    808 of 8,440  ( 9.6%, 7.5 MB)

Three conclusions, and they matter because they say what NOT to build:

1. **Eviction is not the lever people assume.** Deleting every unreferenced row today
   reclaims 7.5 MB of 305 MB — 2.5%. The table is large because it is USED, not because
   it is stale. A policy that only reaps unreferenced rows will never be the thing that
   saves this database.
2. **Compression is not a lever either.** ocr_json is already TOAST-compressed; the 305 MB
   IS the compressed size. Switching to lz4 would be faster and BIGGER, not smaller.
3. **There is no urgency, and that is exactly why the policy should exist now.** At
   100 MB/day against 869 GB free the runway is years. The job of this script is to be in
   place, measured, and provably safe BEFORE the day it is needed — not to be written in a
   hurry when the volume is at 95%.

WHY THIS CANNOT LOSE DATA INDOX NEEDS
-------------------------------------
ocr_cache is a CACHE. Its key is the md5 of the document bytes and its value is the OCR of
exactly those bytes, so a deleted row costs a re-OCR (one Google Vision call), never a fact
about a document. The business data lives in incoming_documents and doc_data; nothing here
is a source of truth.

On top of that this script REFUSES to delete any hash referenced by incoming_documents
(API_TOOLS_ID, API_TOOLS_ID_COMPLETED or HASH), so a document that INDOX can still ask
about keeps its cache entry regardless of age. `--include-referenced` relaxes that and is
deliberately awkward to reach: it needs its own much longer horizon and an explicit flag.

USAGE
    ocr-cache-retention.py                      # report only: what WOULD go, and when
    ocr-cache-retention.py --days 90 --apply    # reap unreferenced rows older than 90d
    ocr-cache-retention.py --budget-mb 4096     # also report the projected breach date
Connection comes from the same env as the app (DOC_DB_* / SUPABASE_DB_*), or --dsn.
"""
import argparse
import os
import sys

REF_SQL = """
  SELECT DISTINCT h FROM (
    SELECT "API_TOOLS_ID"           AS h FROM incoming_documents
    UNION SELECT "API_TOOLS_ID_COMPLETED" FROM incoming_documents
    UNION SELECT "HASH"                   FROM incoming_documents
  ) x WHERE h IS NOT NULL AND h <> ''
"""


def dsn_from_env():
    if os.getenv('DOC_DB_DSN'):
        return os.getenv('DOC_DB_DSN')
    host = os.getenv('DOC_DB_HOST') or os.getenv('SUPABASE_DB_HOST')
    if not host:
        return None
    return (f"host={host} port={os.getenv('DOC_DB_PORT') or os.getenv('SUPABASE_DB_PORT', '5432')} "
            f"dbname={os.getenv('DOC_DB_NAME') or os.getenv('SUPABASE_DB_NAME', 'postgres')} "
            f"user={os.getenv('DOC_DB_USER') or os.getenv('SUPABASE_DB_USER', 'postgres')} "
            f"password={os.getenv('DOC_DB_PASSWORD') or os.getenv('SUPABASE_DB_PASSWORD', '')} "
            f"connect_timeout=10")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dsn', default=None)
    ap.add_argument('--days', type=int, default=90,
                    help='reap UNREFERENCED rows older than this (default 90)')
    ap.add_argument('--include-referenced', action='store_true',
                    help='ALSO reap referenced rows older than --referenced-days. Costs a '
                         're-OCR if INDOX asks again. Off by default, on purpose.')
    ap.add_argument('--referenced-days', type=int, default=365)
    ap.add_argument('--budget-mb', type=int, default=4096,
                    help='size budget used only to report a projected breach date')
    ap.add_argument('--apply', action='store_true', help='actually delete (default: report)')
    ap.add_argument('--max-delete', type=int, default=20000,
                    help='hard cap per run, so a bad predicate cannot empty the table')
    a = ap.parse_args()

    import psycopg2
    dsn = a.dsn or dsn_from_env()
    if not dsn:
        sys.exit('no DSN: set DOC_DB_HOST/SUPABASE_DB_HOST or pass --dsn')
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()

    def one(sql, args=()):
        cur.execute(sql, args)
        return cur.fetchone()

    rows, size = one("SELECT count(*), pg_total_relation_size('ocr_cache') FROM ocr_cache")
    print(f"ocr_cache: {rows:,} rows, {size/1048576:.0f} MB")

    # Growth rate straight from the table, so the projection is not a guess.
    g = one("""SELECT count(*), coalesce(sum(pg_column_size(ocr_json)),0)
               FROM ocr_cache WHERE created_at > now() - interval '7 days'""")
    per_day_mb = g[1] / 1048576 / 7
    print(f"growth (last 7d): {g[0]/7:,.0f} rows/day, {per_day_mb:.0f} MB/day")
    if per_day_mb > 0:
        headroom = (a.budget_mb - size / 1048576) / per_day_mb
        print(f"budget {a.budget_mb} MB -> breached in ~{headroom:.0f} days "
              f"({'ACT NOW' if headroom < 30 else 'no action needed yet'})")

    cur.execute(f"""
        SELECT count(*), coalesce(sum(pg_column_size(ocr_json)),0)
        FROM ocr_cache c
        WHERE c.updated_at < now() - interval '%s days'
          AND c.file_hash NOT IN ({REF_SQL})""" % a.days)
    n_unref, b_unref = cur.fetchone()
    print(f"\nUNREFERENCED and older than {a.days}d: {n_unref:,} rows, {b_unref/1048576:.1f} MB")

    n_ref = b_ref = 0
    if a.include_referenced:
        cur.execute(f"""
            SELECT count(*), coalesce(sum(pg_column_size(ocr_json)),0)
            FROM ocr_cache c
            WHERE c.updated_at < now() - interval '%s days'
              AND c.file_hash IN ({REF_SQL})""" % a.referenced_days)
        n_ref, b_ref = cur.fetchone()
        print(f"REFERENCED and older than {a.referenced_days}d: {n_ref:,} rows, "
              f"{b_ref/1048576:.1f} MB  (each one is a re-OCR if asked for again)")

    total = n_unref + n_ref
    if total == 0:
        print("\nnothing to reap. The policy is in place; it simply has nothing to do yet.")
        conn.rollback()
        return
    if total > a.max_delete:
        sys.exit(f"\nREFUSING: {total:,} rows exceeds --max-delete {a.max_delete:,}. "
                 f"Raise it deliberately, or shorten the horizon.")
    if not a.apply:
        print(f"\nREPORT ONLY — would delete {total:,} rows "
              f"({(b_unref + b_ref)/1048576:.1f} MB). Re-run with --apply.")
        conn.rollback()
        return

    cur.execute(f"""DELETE FROM ocr_cache c
                    WHERE c.updated_at < now() - interval '%s days'
                      AND c.file_hash NOT IN ({REF_SQL})""" % a.days)
    d1 = cur.rowcount
    d2 = 0
    if a.include_referenced:
        cur.execute(f"""DELETE FROM ocr_cache c
                        WHERE c.updated_at < now() - interval '%s days'
                          AND c.file_hash IN ({REF_SQL})""" % a.referenced_days)
        d2 = cur.rowcount
    conn.commit()
    # DELETE alone frees nothing to the OS; the space becomes reusable heap. Plain VACUUM
    # (never FULL, which takes an ACCESS EXCLUSIVE lock on a table the pipeline reads on
    # every document) makes it reusable and updates the stats.
    conn.autocommit = True
    cur.execute("VACUUM (ANALYZE) ocr_cache")
    rows2, size2 = one("SELECT count(*), pg_total_relation_size('ocr_cache') FROM ocr_cache")
    print(f"\ndeleted {d1:,} unreferenced + {d2:,} referenced")
    print(f"ocr_cache now: {rows2:,} rows, {size2/1048576:.0f} MB "
          f"({(size-size2)/1048576:+.0f} MB)")
    conn.close()


if __name__ == '__main__':
    main()
