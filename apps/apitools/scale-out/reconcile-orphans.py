#!/usr/bin/env python3
"""Backfill per-instance OCR cache JSON files into the SHARED Postgres ocr_cache.

WHY THIS EXISTS
---------------
Before the strict guard landed (src/ocr_core/ocr_cache.py, 2026-08-11), a shared-cache
outage made apitools write OCR results to a local JSON file and keep serving. The
portable instance did that for 6 hours while haproxy sent it 81.6% of all traffic, and
produced 1,171 results that no other instance could see. `/docExists` answers "false"
for those hashes from everywhere else, so INDOX re-OCRs documents already paid for.

THIS IS A CACHE BACKFILL, NOT A DOCUMENT MUTATION. The key is the md5 of the document
bytes and the value is the OCR of exactly those bytes, so importing a file written by
instance A into the table instance B reads is definitionally the same result -- it is
the value the shared cache would already hold if the DB leg had been up. Nothing in
incoming_documents or any business table is touched.

SAFETY
------
* ``ON CONFLICT DO NOTHING`` — a row that is already in the shared table always wins.
  Local files are, by construction, the OLDER and less-authoritative copy.
* Every file is validated as JSON with the shape the cache contract requires before it
  is offered to the database; unparseable files are reported and skipped.
* ``--apply`` is required. The default is a dry run.
* Imported files are left on disk unless ``--prune`` is passed, and --prune only ever
  removes a file whose hash is verifiably present in the shared table afterwards.

USAGE
    python3 reconcile-orphans.py --dir ~/apitools-storage/ocr_cache            # dry run
    python3 reconcile-orphans.py --dir ~/apitools-storage/ocr_cache --apply
    python3 reconcile-orphans.py --dir ... --apply --prune
Connection comes from the same env as the app (DOC_DB_* / SUPABASE_DB_*), or --dsn.
"""
import argparse
import json
import os
import re
import sys

HASH_RE = re.compile(r'^[0-9a-fA-F]{32}$')


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
    ap.add_argument('--dir', required=True, help='the instance-local ocr_cache folder')
    ap.add_argument('--dsn', default=None)
    ap.add_argument('--apply', action='store_true', help='actually write (default: dry run)')
    ap.add_argument('--prune', action='store_true',
                    help='delete local files confirmed present in the shared table')
    ap.add_argument('--batch', type=int, default=100)
    a = ap.parse_args()

    import psycopg2
    from psycopg2.extras import execute_batch

    dsn = a.dsn or dsn_from_env()
    if not dsn:
        sys.exit('no DSN: set DOC_DB_HOST/SUPABASE_DB_HOST or pass --dsn')

    folder = os.path.expanduser(a.dir)
    files = sorted(f for f in os.listdir(folder) if f.endswith('.json'))
    print(f"local cache files: {len(files)} in {folder}")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM ocr_cache")
    before = cur.fetchone()[0]
    print(f"shared ocr_cache rows BEFORE: {before}")

    stats = {'bad_name': 0, 'bad_json': 0, 'already_shared': 0, 'to_import': 0,
             'imported': 0, 'pruned': 0}
    candidates = []
    for fn in files:
        h = fn[:-5]
        if not HASH_RE.match(h):
            stats['bad_name'] += 1
            continue
        try:
            with open(os.path.join(folder, fn), 'r', encoding='utf-8', errors='ignore') as fh:
                doc = json.load(fh)
        except Exception as e:  # noqa: BLE001
            print(f"  SKIP unparseable {fn}: {e}")
            stats['bad_json'] += 1
            continue
        if not isinstance(doc, dict):
            stats['bad_json'] += 1
            continue
        candidates.append((h.lower(), doc, doc.get('ocr_engine')))

    # Which are already shared? Ask in one round trip rather than per-file.
    hashes = [c[0] for c in candidates]
    present = set()
    for i in range(0, len(hashes), 1000):
        cur.execute("SELECT file_hash FROM ocr_cache WHERE file_hash = ANY(%s)",
                    (hashes[i:i + 1000],))
        present.update(r[0] for r in cur.fetchall())
    stats['already_shared'] = len(present)
    todo = [c for c in candidates if c[0] not in present]
    stats['to_import'] = len(todo)

    print(f"parseable: {len(candidates)}   already in shared table: {len(present)}   "
          f"ORPHANED (to import): {len(todo)}")
    engines = {}
    for h, d, e in todo:
        engines[e] = engines.get(e, 0) + 1
    print(f"orphan engine mix: {engines}")

    if not a.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        conn.rollback()
        return

    # %s::jsonb over PRE-SERIALISED, NUL-STRIPPED text — mirrors ocr_cache._jsonb_safe().
    # Postgres cannot store NUL in jsonb; real production OCR output contains it, and
    # a single such document aborts the whole batch (execute_batch sends them joined by
    # ';', so one bad row takes the others with it).
    rows = [(h, json.dumps(d, ensure_ascii=False).replace('\\u0000', ''), e) for h, d, e in todo]
    stats['nul_stripped'] = sum(
        1 for (_, d, _), (_, s, _) in zip(todo, rows)
        if '\\u0000' in json.dumps(d, ensure_ascii=False))
    execute_batch(cur,
                  "INSERT INTO ocr_cache (file_hash, ocr_json, ocr_engine, created_at, updated_at) "
                  "VALUES (%s, %s::jsonb, %s, now(), now()) ON CONFLICT (file_hash) DO NOTHING",
                  rows, page_size=a.batch)
    conn.commit()
    cur.execute("SELECT count(*) FROM ocr_cache")
    after = cur.fetchone()[0]
    stats['imported'] = after - before
    print(f"shared ocr_cache rows AFTER: {after}   (+{after - before})")

    if a.prune:
        # Only remove what is PROVEN present in the shared table right now.
        confirmed = set()
        for i in range(0, len(hashes), 1000):
            cur.execute("SELECT file_hash FROM ocr_cache WHERE file_hash = ANY(%s)",
                        (hashes[i:i + 1000],))
            confirmed.update(r[0] for r in cur.fetchall())
        for h, _, _ in candidates:
            if h in confirmed:
                try:
                    os.remove(os.path.join(folder, f"{h}.json"))
                    stats['pruned'] += 1
                except OSError as e:
                    print(f"  prune failed {h}: {e}")
        print(f"pruned {stats['pruned']} local files now redundant with the shared table")

    print(f"\nstats: {stats}")
    conn.close()


if __name__ == '__main__':
    main()
