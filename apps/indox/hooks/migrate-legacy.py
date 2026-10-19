#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
indox-migrate-legacy.py — load the Hacohen LEGACY Google-Sheet CSV exports into supabase.

Ground truth: ai/context/archive/indox-pre-2026-09/hacohen-legacy-migration-spec.md

  incoming_documents : direct column-for-column load. All 76 named CSV columns exist in
                       the target table with identical names (verified 2026-07-16),
                       including the Hebrew column 'סימון כרטסת עדכנית'.
  companies          : 7 columns map direct; every other legacy column (Priority/ERP aux)
                       is folded into the existing `extra` JSONB.

Transport: stdlib only. No psycopg2 exists on this laptop or on the VPS, so rows are
streamed as a COPY ... FROM STDIN block into `docker exec -i supabase-db-bbox psql`
(optionally via ssh). One psql session, one transaction, TEMP staging table, chunked
COPY blocks -> constant memory regardless of row count.

Idempotency: COPY into a TEMP table, then INSERT ... SELECT ... ON CONFLICT (<key>)
DO UPDATE. Re-running the same source is a no-op-equivalent (values overwritten with
the same values). See --dedupe-key.

uq_incdoc_hash: a PARTIAL unique index --
    CREATE UNIQUE INDEX uq_incdoc_hash ON incoming_documents ("HASH")
      WHERE "HASH" IS NOT NULL AND "HASH" <> '' AND lower("HASH") <> 'unknown';
33,195 of the 46,680 loadable export rows fall under it; they form 759 HASH groups with
841 excess rows. --dedupe-hash decides what happens to them. See merge_hash_groups().

Usage:
  # inspect only, no DB connection needed
  python scripts/indox-migrate-legacy.py --source X.csv --table incoming_documents --dry-run

  # load, staging supabase over ssh
  python scripts/indox-migrate-legacy.py --source X.csv --table incoming_documents \
      --apply --ssh bina-devops-vps --batch 500

  # verify what is in the table against the spec's expected distribution
  python scripts/indox-migrate-legacy.py --table incoming_documents --verify --ssh bina-devops-vps
"""
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and
# dies with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import csv
import io
import json
import subprocess
import sys
from collections import Counter, OrderedDict

csv.field_size_limit(10 * 1024 * 1024)

# ---------------------------------------------------------------- expectations
# From the spec (live legacy counts, 2026-07). The two entries marked EXTRA were not
# in the spec but exist in the real export; kept here so --verify reports the truth.
EXPECTED_STATUS = {
    "OLD": 16299, "COMPLETED": 13785, "DOUBLE": 7205, "MISSING_COMPANY_ID": 3617,
    "MISSING_TYPE": 2719, "ACTION_RESTART": 1124, "IN_PROGRESS": 908, "MISSING_LINK": 615,
    "MISSING_SHIPMENT": 192, "UNKNOWN_COMPANY": 94, "ACTION_REQUIRED": 55,
    "EXTRACTION_FAILED": 40,
    "PAUSE": 27,             # EXTRA - absent from spec, present in export
    "API_TOOLS_FAILED": 1,   # EXTRA - absent from spec, present in export
}
EXPECTED_TYPE = {
    "INVOICE": 29607, "SHIPMENT": 8681, "UNKNOWN": 5058, "BALANCE_SHEET": 2615,
    "ORDER": 709, "TRASH": 10,
    "": 1,                   # EXTRA - one row with a blank TYPE
}
EXPECTED_TOTAL = 46681

# companies: legacy header -> supabase column. Everything else -> extra JSONB.
COMPANIES_DIRECT = [
    "שם חברה", "מזהה 1", "מזהה 2", "מייל 1", "מייל 2",
    "שם ספק מפריוריטי", "הוראות לAI לחילוץ דוח גיול",
]
# Legacy column that deserves a real column but has none in supabase today.
# Reported by --dry-run; parked in `extra` until the column is added by the schema owner.
COMPANIES_WANTS_COLUMN = "הוראות לAI לחילוץ חשבונית"

# ---------------------------------------------------------------- hash-merge policy
# Grounded in an analysis of the 759 duplicate-HASH groups in the 2026-07 export
# (see the module docstring of scripts/ and the migration spec). Two facts drive it:
#
#  1. STATUS=DOUBLE is the LEGACY SYSTEM'S OWN "this row is the throwaway" verdict --
#     n8n writes STATUS=DOUBLE together with DOUBLE_LINE_CONTEXT={"hashMatch":"<other ID>"}
#     (indoxV2ActionsGlobal01). In 677/759 groups exactly one row is non-DOUBLE, and
#     764 of the 892 parseable hashMatch pointers resolve to a sibling in the same group.
#     So the keeper is identified by STATUS, not by arrival order.
#  2. "Latest" is not even a total order here: 547 rows in duplicate groups have a BLANK
#     TIMESTAMP, and 146/759 groups tie at max(TIMESTAMP). A pure latest-wins rule is
#     undefined for 19% of the groups, and it would demote a COMPLETED sibling to a
#     DOUBLE base in 62 groups, discarding that document's extracted values.
#
# Hence: rank first (progress), then recency, then informativeness, then ID (total order).
# DOUBLE ranks below everything; OLD (archived) ranks above DOUBLE but below live work.
STATUS_RANK = {
    "COMPLETED": 100,          # terminal-good: carries the real extracted values
    "ACTION_REQUIRED": 60, "ACTION_RESTART": 60,
    "IN_PROGRESS": 55,
    "EXTRACTION_FAILED": 50, "API_TOOLS_FAILED": 50, "PAUSE": 50,
    "MISSING_COMPANY_ID": 45, "MISSING_TYPE": 45, "MISSING_LINK": 45,
    "MISSING_SHIPMENT": 45, "UNKNOWN_COMPANY": 45,
    "OLD": 20,                 # archived, but still a real document
    "DOUBLE": 0,               # the legacy system's own duplicate marker
}
STATUS_RANK_DEFAULT = 40       # an unseen status outranks OLD/DOUBLE, not COMPLETED

# Columns never taken from a collapsed sibling.
#   ID/HASH  - identity. ID is the PK we keep; HASH is equal across the group by definition.
#   STATUS   - the base's verdict is authoritative; filling it could import "DOUBLE".
#   DOUBLE_LINE_CONTEXT - the sibling's "I am a duplicate of <ID>" note. Copying it onto the
#                         keeper would mislabel the keeper and point at a row that the merge
#                         just removed. It is preserved in ACTION_LOG provenance instead.
MERGE_NO_FILL = ("ID", "HASH", "STATUS", "DOUBLE_LINE_CONTEXT")

# Where provenance goes. ACTION_LOG is a real column on incoming_documents, is absent from
# the legacy export (so nothing is overwritten), and is already the house append-only audit
# trail: n8n writes  ACTION_LOG = (ACTION_LOG || '') + ', <what>, <when>, <execution id>'.
MERGE_PROVENANCE_COL = "ACTION_LOG"


def _hash_indexed(h):
    """True iff this HASH is covered by the partial unique index uq_incdoc_hash."""
    h = (h or "").strip()
    return bool(h) and h.lower() != "unknown"


def merge_hash_groups(cols, records, report):
    """Collapse every uq_incdoc_hash duplicate group into ONE row.

    base   = max by (STATUS_RANK, TIMESTAMP, populated-field-count, ID) -- most progressed,
             then newest, then most informative, then a total order for determinism.
    fill   = for each column the base leaves empty, take the first non-empty value walking
             siblings newest-first (TIMESTAMP desc, ID asc).
    trace  = collapsed siblings' IDs + STATUSes appended to ACTION_LOG.

    Deterministic and idempotent: no wall clock, no dict iteration order, no input order
    dependence in the choice of base. Output keeps first-occurrence order of each group.

    Returns a new records list. `cols` may gain MERGE_PROVENANCE_COL, so callers must use
    the returned column list.
    """
    ci = {c: i for i, c in enumerate(cols)}
    for req in ("ID", "HASH", "STATUS", "TIMESTAMP"):
        if req not in ci:
            raise SystemExit("ERROR: --dedupe-hash merge needs column %r in the source" % req)

    def val(rec, c):
        i = ci.get(c)
        return "" if i is None else ((rec[i] or "").strip() if rec[i] is not None else "")

    # group by HASH, remembering first-occurrence order
    order, groups = [], {}
    for rec in records:
        h = val(rec, "HASH")
        if not _hash_indexed(h):
            order.append(("row", rec))          # outside the index -> untouched
            continue
        if h not in groups:
            groups[h] = []
            order.append(("grp", h))
        groups[h].append(rec)

    populated = lambda rec: sum(1 for v in rec if (v or "").strip())
    base_key = lambda rec: (STATUS_RANK.get(val(rec, "STATUS"), STATUS_RANK_DEFAULT),
                            val(rec, "TIMESTAMP"), populated(rec), val(rec, "ID"))
    # newest-first: TIMESTAMP desc, then ID asc as a stable tiebreak
    sib_key = lambda rec: (val(rec, "TIMESTAMP"), val(rec, "ID"))

    if MERGE_PROVENANCE_COL in ci:
        prov_i = ci[MERGE_PROVENANCE_COL]
        out_cols = list(cols)
    else:
        prov_i = len(cols)
        out_cols = list(cols) + [MERGE_PROVENANCE_COL]

    def widen(rec):
        return rec if prov_i < len(rec) else list(rec) + [None]

    stats = {"groups": 0, "collapsed": 0, "fields_filled": 0, "groups_gained": 0,
             "base_status": Counter(), "demoted_saved": 0, "examples": []}
    out = []
    for kind, payload in order:
        if kind == "row":
            out.append(widen(list(payload)))
            continue
        g = groups[payload]
        if len(g) == 1:
            out.append(widen(list(g[0])))
            continue

        stats["groups"] += 1
        stats["collapsed"] += len(g) - 1
        base = max(g, key=base_key)
        sibs = sorted([r for r in g if r is not base], key=sib_key, reverse=True)
        merged = widen(list(base))
        stats["base_status"][val(base, "STATUS")] += 1
        # did rank-based selection rescue a COMPLETED that latest-wins would have dropped?
        newest = max(g, key=sib_key)
        if val(base, "STATUS") == "COMPLETED" and val(newest, "STATUS") != "COMPLETED":
            stats["demoted_saved"] += 1

        filled = []
        for c in out_cols:
            if c in MERGE_NO_FILL or c == MERGE_PROVENANCE_COL:
                continue
            i = ci.get(c)
            if i is None or (merged[i] or "").strip():
                continue
            for s in sibs:
                if val(s, c):
                    merged[i] = s[i]
                    filled.append(c)
                    break
        stats["fields_filled"] += len(filled)
        if filled:
            stats["groups_gained"] += 1

        trace = "legacy-hash-merge, kept ID=%s STATUS=%s, collapsed %d: %s%s, %s" % (
            val(base, "ID"), val(base, "STATUS"), len(sibs),
            " | ".join("ID=%s STATUS=%s TS=%s" % (val(s, "ID"), val(s, "STATUS"),
                                                  val(s, "TIMESTAMP") or "-") for s in sibs),
            (", filled: " + ",".join(filled)) if filled else "",
            "indox-migrate-legacy")
        prev = (merged[prov_i] or "").strip() if prov_i < len(merged) and merged[prov_i] else ""
        merged[prov_i] = (prev + ", " + trace) if prev else trace

        if len(stats["examples"]) < 3:
            stats["examples"].append((payload, val(base, "ID"), val(base, "STATUS"),
                                      [(val(s, "ID"), val(s, "STATUS")) for s in sibs],
                                      filled))
        out.append(merged)

    report["hash_merge"] = stats
    return out_cols, out


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- CSV reading
def read_csv(path):
    """Return (header, rows). utf-8-sig strips a BOM if present; cp1255 is the fallback."""
    for enc in ("utf-8-sig", "cp1255"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                rows = list(csv.reader(fh))
            if not rows:
                raise SystemExit("ERROR: %s is empty" % path)
            return rows[0], rows[1:], enc
        except UnicodeDecodeError:
            continue
    raise SystemExit("ERROR: cannot decode %s as utf-8 or cp1255" % path)


def uniquify(header):
    """Legacy sheets contain blank and repeated header cells. Give every column a stable
    key so nothing is silently collapsed (csv.DictReader would drop duplicates)."""
    seen, out = Counter(), []
    for i, name in enumerate(header):
        n = (name or "").strip()
        if not n:
            out.append("_col%d" % i)
            continue
        seen[n] += 1
        out.append(n if seen[n] == 1 else "%s__%d" % (n, seen[n]))
    return out


# ---------------------------------------------------------------- psql plumbing
def psql_argv(args):
    inner = ["docker", "exec", "-i", args.container,
             "psql", "-U", args.db_user, "-d", args.db_name,
             "-v", "ON_ERROR_STOP=1"]
    if args.psql_cmd:
        return args.psql_cmd, True
    if args.ssh:
        return ["ssh", args.ssh, " ".join(inner)], False
    return inner, False


def run_psql(args, script, capture=True):
    argv, shell = psql_argv(args)
    p = subprocess.run(argv, input=script.encode("utf-8"), shell=shell,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0:
        log(out)
        raise SystemExit("psql FAILED (rc=%d):\n%s" % (p.returncode, err))
    if err.strip() and capture:
        log("psql stderr: %s" % err.strip())
    return out


def q(ident):
    return '"%s"' % ident.replace('"', '""')


def copy_csv_line(values):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL).writerow(values)
    return buf.getvalue()


# ---------------------------------------------------------------- transforms
def prep_incoming_documents(header, rows, args):
    """Direct load. Returns (columns, records, report)."""
    keys = uniquify(header)
    named = [k for k, h in zip(keys, header) if (h or "").strip()]
    report = {"skipped": []}

    tbl_cols = args._table_cols
    missing = [c for c in named if c not in tbl_cols]
    report["csv_not_in_table"] = missing
    report["table_not_in_csv"] = [c for c in tbl_cols if c not in named]

    cols = [c for c in named if c in tbl_cols]
    idx = {k: i for i, k in enumerate(keys)}

    records, seen = [], {}
    for lineno, row in enumerate(rows, start=2):
        get = lambda c: (row[idx[c]] if idx[c] < len(row) else "")
        doc_id = (get("ID") or "").strip()
        if not doc_id:
            # The PK is NOT NULL. One known corrupt row (an embedded newline shifted its
            # cells one position left). Quarantine rather than load garbage.
            report["skipped"].append((lineno, "blank ID", (get("NAME") or "")[:60]))
            continue
        rec = [get(c) for c in cols]
        if doc_id in seen:
            report["skipped"].append((lineno, "duplicate ID (last wins)", doc_id))
        seen[doc_id] = rec
        records.append((doc_id, rec))

    # last-wins within the file so the COPY itself never trips the PK
    dedup = OrderedDict()
    for doc_id, rec in records:
        dedup[doc_id] = rec
    return cols, list(dedup.values()), report


def prep_companies(header, rows, args):
    """7 direct columns; every other legacy column -> extra JSONB."""
    keys = uniquify(header)
    tbl_cols = args._table_cols
    report = {"skipped": []}

    direct = [c for c in COMPANIES_DIRECT if c in tbl_cols and c in keys]
    report["direct"] = direct
    report["into_extra"] = [k for k in keys if k not in COMPANIES_DIRECT]
    report["wants_real_column"] = (
        COMPANIES_WANTS_COLUMN
        if (COMPANIES_WANTS_COLUMN in keys and COMPANIES_WANTS_COLUMN not in tbl_cols)
        else None
    )

    cols = direct + ["extra"]
    idx = {k: i for i, k in enumerate(keys)}
    dedup = OrderedDict()
    for lineno, row in enumerate(rows, start=2):
        get = lambda c: (row[idx[c]] if idx[c] < len(row) else "")
        key = (get("מזהה 1") or "").strip()
        extra = {}
        for k in keys:
            if k in COMPANIES_DIRECT:
                continue
            v = (get(k) or "").strip()
            if v:
                extra[k] = v
        vals = [(get(c) or "").strip() for c in direct]
        # blank מזהה 1 -> NULL: '' would collide across rows on companies_mzhe1_uniq,
        # whereas SQL NULLs are all distinct to a unique index.
        vals = [(None if (c == "מזהה 1" and not v) else v) for c, v in zip(direct, vals)]
        vals.append(json.dumps(extra, ensure_ascii=False))
        if not key:
            report["skipped"].append((lineno, "blank מזהה 1 -> loaded with NULL key",
                                      (get("שם חברה") or "")[:40]))
            dedup["__null__%d" % lineno] = vals
            continue
        if key in dedup:
            report["skipped"].append((lineno, "duplicate מזהה 1 (last wins)", key))
        dedup[key] = vals
    return cols, list(dedup.values()), report


# ---------------------------------------------------------------- load
def build_load_script(table, cols, records, key, batch, dedupe_hash):
    stg = "stg_migrate"
    coldefs = ", ".join("%s text" % q(c) for c in cols)
    parts = ["\\set ON_ERROR_STOP on",
             "SET client_encoding TO 'UTF8';",
             "BEGIN;",
             "CREATE TEMP TABLE %s (%s) ON COMMIT DROP;" % (stg, coldefs)]

    collist = ", ".join(q(c) for c in cols)
    for i in range(0, len(records), batch):
        chunk = records[i:i + batch]
        parts.append("COPY %s (%s) FROM STDIN WITH (FORMAT csv, NULL '\\N');" % (stg, collist))
        for rec in chunk:
            parts.append(copy_csv_line(["\\N" if v is None else v for v in rec]).rstrip("\n"))
        parts.append("\\.")

    sel = ", ".join(
        ("%s::jsonb" % q(c)) if c == "extra" else q(c)
        for c in cols
    )
    updates = ", ".join("%s = EXCLUDED.%s" % (q(c), q(c)) for c in cols if c != key)
    if dedupe_hash == "skip":
        # No conflict target => ANY unique violation (PK *or* uq_incdoc_hash) skips the row.
        # Still idempotent, but a re-run will not refresh changed values.
        conflict = "ON CONFLICT DO NOTHING"
    else:
        # 'none'  -> uq_incdoc_hash violations surface as a hard error (nothing silent).
        # 'merge' -> the groups were already collapsed in Python, so no violation can occur
        #            and the DO UPDATE keeps the re-run idempotent.
        conflict = "ON CONFLICT (%s) DO UPDATE SET %s" % (q(key), updates)

    parts.append("INSERT INTO %s (%s) SELECT %s FROM %s %s;"
                 % (q(table), collist, sel, stg, conflict))
    parts.append("COMMIT;")
    parts.append("SELECT count(*) AS rows_in_table FROM %s;" % q(table))
    return "\n".join(parts) + "\n"


def do_verify(args, table):
    if table != "incoming_documents":
        out = run_psql(args, "SELECT count(*) FROM %s;" % q(table))
        log(out)
        return
    script = (
        "SELECT count(*) AS total FROM incoming_documents;\n"
        "SELECT \"STATUS\", count(*) FROM incoming_documents GROUP BY 1 ORDER BY 2 DESC;\n"
        "SELECT \"TYPE\", count(*) FROM incoming_documents GROUP BY 1 ORDER BY 2 DESC;\n"
    )
    out = run_psql(args, script)
    log(out)
    actual_status, actual_type, total = {}, {}, None
    section = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("total"):
            section = "total"; continue
        if s.startswith("STATUS"):
            section = "status"; continue
        if s.startswith("TYPE"):
            section = "type"; continue
        if "|" not in s:
            # single-column result (the total) prints bare, with no pipe
            if section == "total" and total is None and s.isdigit():
                total = int(s)
            continue
        left, right = [x.strip() for x in s.rsplit("|", 1)]
        if not right.isdigit():
            continue
        if section == "status":
            actual_status[left] = int(right)
        elif section == "type":
            actual_type[left] = int(right)
        elif section == "total" and total is None:
            total = int(right)

    def cmp(name, exp, act):
        log("--- %s: expected vs actual" % name)
        ok = True
        for k in sorted(set(exp) | set(act), key=lambda x: -exp.get(x, 0)):
            e, a = exp.get(k, 0), act.get(k, 0)
            flag = "OK " if e == a else "DIFF"
            if e != a:
                ok = False
            log("  %-4s %-22s expected %7d  actual %7d  delta %+d" % (flag, k or "(blank)", e, a, a - e))
        return ok

    s_ok = cmp("STATUS", EXPECTED_STATUS, actual_status)
    t_ok = cmp("TYPE", EXPECTED_TYPE, actual_type)
    log("--- TOTAL expected %d actual %s" % (EXPECTED_TOTAL, total))
    log("VERDICT: %s" % ("FULL MATCH" if (s_ok and t_ok and total == EXPECTED_TOTAL)
                         else "MISMATCH (see DIFF lines above)"))


def fetch_table_cols(args, table):
    out = run_psql(args, "select column_name from information_schema.columns "
                         "where table_name='%s' order by ordinal_position;" % table,
                   capture=False)
    cols = []
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("-") or s == "column_name" or "row" in s and "(" in s:
            continue
        cols.append(s)
    return cols


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Migrate Hacohen legacy CSV -> supabase")
    ap.add_argument("--source")
    ap.add_argument("--table", required=True, choices=["incoming_documents", "companies"])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--limit", type=int, help="load only the first N rows (subset test)")
    ap.add_argument("--dedupe-key", help="override the conflict key")
    ap.add_argument("--dedupe-hash", choices=["none", "skip", "merge"], default="none",
                    help="incoming_documents only: what to do about the uq_incdoc_hash "
                         "partial unique index. 'none' (DEFAULT, nothing changes silently) "
                         "lets a collision fail the load loudly. 'skip' drops the colliding "
                         "rows (data loss). 'merge' collapses each HASH group into one row: "
                         "base = most progressed (STATUS_RANK) then newest, empty fields "
                         "filled from siblings newest-first, collapsed IDs+STATUSes traced "
                         "into ACTION_LOG. Deterministic and idempotent.")
    ap.add_argument("--hash-conflict", choices=["error", "skip"],
                    help=argparse.SUPPRESS)  # back-compat alias for --dedupe-hash
    ap.add_argument("--only-hash",
                    help="comma-separated HASH values; load only rows with those HASHes. "
                         "For subset tests that must include real duplicate groups.")
    ap.add_argument("--ssh", help="ssh host that runs docker (e.g. bina-devops-vps)")
    ap.add_argument("--container", default="supabase-db-bbox")
    ap.add_argument("--db-user", default="postgres")
    ap.add_argument("--db-name", default="postgres")
    ap.add_argument("--psql-cmd", help="raw shell command that pipes stdin into psql")
    args = ap.parse_args()

    if args.hash_conflict:
        args.dedupe_hash = {"error": "none", "skip": "skip"}[args.hash_conflict]
        log("NOTE: --hash-conflict %s is deprecated -> --dedupe-hash %s"
            % (args.hash_conflict, args.dedupe_hash))
    if args.dedupe_hash != "none" and args.table != "incoming_documents":
        raise SystemExit("ERROR: --dedupe-hash only applies to incoming_documents")

    key = args.dedupe_key or ("ID" if args.table == "incoming_documents" else "מזהה 1")

    if args.verify:
        do_verify(args, args.table)
        return

    if not args.source:
        raise SystemExit("ERROR: --source is required for --dry-run/--apply")

    header, rows, enc = read_csv(args.source)
    log("SOURCE   %s" % args.source)
    log("encoding %s | header cells %d | data rows %d" % (enc, len(header), len(rows)))

    # dry-run still needs the live column list to prove the schema match
    args._table_cols = fetch_table_cols(args, args.table)
    log("TARGET   %s (%d columns)" % (args.table, len(args._table_cols)))

    if args.table == "incoming_documents":
        cols, records, report = prep_incoming_documents(header, rows, args)
        log("")
        log("SCHEMA MATCH: %d/%d named CSV columns map direct" %
            (len(cols), len([h for h in header if (h or '').strip()])))
        log("  CSV cols NOT in table : %s" % (report["csv_not_in_table"] or "NONE"))
        log("  table cols not in CSV : %s" % report["table_not_in_csv"])

        if args.only_hash:
            want = set(h.strip() for h in args.only_hash.split(",") if h.strip())
            hi = cols.index("HASH")
            records = [r for r in records if (r[hi] or "").strip() in want]
            log("")
            log("ONLY-HASH filter: %d HASH values -> %d rows" % (len(want), len(records)))

        before = len(records)
        if args.dedupe_hash == "merge":
            cols, records = merge_hash_groups(cols, records, report)
            st = report["hash_merge"]
            log("")
            log("DEDUPE-HASH merge (uq_incdoc_hash):")
            log("  duplicate HASH groups collapsed : %d" % st["groups"])
            log("  rows removed by collapsing      : %d" % st["collapsed"])
            log("  rows in  : %d   rows out : %d" % (before, len(records)))
            log("  field values recovered from siblings : %d (in %d groups)"
                % (st["fields_filled"], st["groups_gained"]))
            log("  COMPLETED bases a naive latest-wins would have demoted : %d"
                % st["demoted_saved"])
            log("  base STATUS distribution : %s"
                % ", ".join("%s=%d" % kv for kv in st["base_status"].most_common()))
            log("  provenance -> %s" % MERGE_PROVENANCE_COL)
            for h, bid, bst, sibs, filled in st["examples"]:
                log("    HASH %s.. base ID=%s(%s) <- %s%s"
                    % (h[:16], bid, bst,
                       ", ".join("%s(%s)" % s for s in sibs),
                       ("  filled=%d" % len(filled)) if filled else ""))
        elif args.dedupe_hash == "none":
            log("")
            log("DEDUPE-HASH none: uq_incdoc_hash collisions will FAIL the load "
                "(use --dedupe-hash merge to collapse them).")
    else:
        cols, records, report = prep_companies(header, rows, args)
        log("")
        log("COMPANIES MAP: %d direct + extra JSONB" % len(report["direct"]))
        log("  direct     : %s" % report["direct"])
        log("  -> extra   : %d legacy columns" % len(report["into_extra"]))
        if report["wants_real_column"]:
            log("  ** WANTS A REAL COLUMN (not added by this script): %s"
                % report["wants_real_column"])

    if report["skipped"]:
        log("")
        log("SKIPPED/ADJUSTED rows: %d" % len(report["skipped"]))
        for lineno, why, what in report["skipped"][:10]:
            log("  line %-7s %-34s %s" % (lineno, why, what))
        if len(report["skipped"]) > 10:
            log("  ... +%d more" % (len(report["skipped"]) - 10))

    if args.limit:
        records = records[:args.limit]
        log("")
        log("LIMIT: loading only the first %d rows" % len(records))

    log("")
    log("dedupe key : %s   batch: %d   rows to load: %d" % (key, args.batch, len(records)))

    if args.dry_run:
        log("")
        log("DRY RUN - nothing written. Preview of first row:")
        if records:
            for c, v in list(zip(cols, records[0]))[:8]:
                log("  %-22s %s" % (c, (v or "")[:60]))
        return

    script = build_load_script(args.table, cols, records, key, args.batch, args.dedupe_hash)
    log("")
    log("APPLY: streaming %d rows in %d COPY blocks ..."
        % (len(records), (len(records) + args.batch - 1) // args.batch))
    out = run_psql(args, script)
    log(out.strip())
    log("DONE.")


if __name__ == "__main__":
    main()
