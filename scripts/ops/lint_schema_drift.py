#!/usr/bin/env python3
"""Assert every object a migration creates also exists in the fixture schema.

THE DRIFT THIS CATCHES
----------------------
Two things build a database and they advance independently:

  apps/indox/blueprint/fixtures/schema.sql   builds a FRESH database from nothing
  scripts/ops/migrations/*.sql               advances an EXISTING one

Nothing compares them. So a migration can add a function, table, view, trigger or index that a
freshly-provisioned deployment will never have, and the difference only shows up as behaviour that
works on this machine and not on a new one -- the worst kind of bug to chase, because the code is
identical and only the substrate differs.

Measured 2026-08-23: `indox_priority_signature` lives in BOTH files and had to be patched in both
when the FROMWAREHOUSE coercion was corrected. That one function has a bespoke drift check inside
scripts/ops/verify_priority_signature.mjs -- which is the right idea applied to exactly one object.
This generalises it to every object the migrations create.

WHAT IT DOES NOT CHECK, stated rather than implied: that the DEFINITIONS match, only that the
object is present in both. Two different bodies under one name still pass here; the priority
signature's own byte-comparison in verify_priority_signature.mjs is the stronger check and stays.
Nor does it read the live database -- this is static, over committed SQL.

Exit 1 if a migration creates something the fixture schema lacks.
"""
import glob
import io
import os
import re
import sys

# It prints Hebrew (G10): python on Windows writes it in the console's codepage and dies on its own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "apps", "indox", "blueprint", "fixtures", "schema.sql")
MIGRATIONS = os.path.join(ROOT, "scripts", "ops", "migrations", "*.sql")

# Objects a migration is allowed to create without the fixture schema carrying them.
#   bak_*  one-off backup tables taken before a destructive step
#   *_20260806-style suffixes are the same thing, dated
EXEMPT = re.compile(r"^(public\.)?(bak_|_)", re.I)

CREATE = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?(?:unique\s+)?(?:materialized\s+)?"
    r"(function|table|view|trigger|index)\s+"
    r"(?:concurrently\s+)?(?:if\s+not\s+exists\s+)?"
    r"([a-z0-9_.\"]+)", re.I)
# `CREATE INDEX ON ...` in prose (an unnamed index, or a sentence in a comment that survived
# stripping) parses as an object literally named "on". It is not one.
NOT_A_NAME = {"on", "if", "exists", "concurrently", "unique"}

# KNOWN, RECORDED DRIFT — reported as a warning, not a failure.
#
# A gate that is permanently red is a gate people learn to skip, and skipping a gate is how the
# truncated node shipped this morning. So an item that cannot be resolved by editing the fixture
# schema gets an entry here WITH ITS REASON, and everything else still fails the build.
# Removing an entry is how it gets fixed; adding one without a reason is not a fix.
KNOWN_DRIFT = {
    ("index", "idx_sync_ledger_created_at"):
        "its migration (2026-08-06_sync_ledger_created_at.sql) ALTERs in a created_at column "
        "first, and that column exists in NEITHER the fixture schema NOR the live database -- "
        "the migration has never been applied anywhere. Adding the index alone fails with "
        "'column created_at does not exist'. Applying an unapplied migration is an owner "
        "decision, not a lint fix.",
}
DROP = re.compile(
    r"\bdrop\s+(?:materialized\s+)?(function|table|view|trigger|index)\s+"
    r"(?:concurrently\s+)?(?:if\s+exists\s+)?([a-z0-9_.\"]+)", re.I)


# COLUMNS (DGO-235). The drift that started all this was a COLUMN — LINK_CONNECTION, added on a live
# database and never to schema.sql (apps/indox/issues/schema-drift-fixture-vs-live.md) — and an
# object-level check cannot see one. So a column a migration adds (`alter table … add column`, or
# the body of a `create table`) must be a column of the same table in the fixture schema too.
ALTER = re.compile(r"\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?([a-z0-9_.\"]+)\s+(.*?);", re.I | re.S)
# `ADD [COLUMN]` — the keyword is optional in Postgres; `add constraint / primary key / unique / …` is not a column
ADD_COL = re.compile(r"\badd\s+(?!(?:constraint|primary|unique|foreign|check|exclude)\b)(?:column\s+)?"
                     r"(?:if\s+not\s+exists\s+)?(\"[^\"]+\"|[a-z0-9_]+)", re.I)
DROP_COL = re.compile(r"\bdrop\s+column\s+(?:if\s+exists\s+)?(\"[^\"]+\"|[a-z0-9_]+)", re.I)
RENAME_COL = re.compile(r"\brename\s+column\s+(\"[^\"]+\"|[a-z0-9_]+)\s+to\s+(\"[^\"]+\"|[a-z0-9_]+)", re.I)
CREATE_TABLE = re.compile(r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_.\"]+)\s*\(", re.I)
NOT_A_COLUMN = {"constraint", "primary", "unique", "check", "foreign", "exclude", "like"}

# KNOWN, RECORDED COLUMN DRIFT — the same rule as KNOWN_DRIFT: each entry carries its reason.
KNOWN_COLUMN_DRIFT = {
    ("sync_ledger", "created_at"):
        "added by 2026-08-06_sync_ledger_created_at.sql, a migration that has never been applied "
        "anywhere (see the index of the same name above): putting the column in schema.sql would "
        "ALTER every live instance on its next apply. Applying it is an owner decision.",
}


LEADING_IDENT = re.compile(r'^\s*("(?:[^"]|"")*"|\S+)')   # "שם חברה" is ONE name, spaces and all


def column_name(token):
    t = token.strip()
    return t[1:-1].replace('""', '"') if t.startswith('"') else t.lower()


def table_bodies(text):
    """(position, table, [column, …]) for every `create table name ( … )`, the body read to its MATCHING paren."""
    for m in CREATE_TABLE.finditer(text):
        depth, i, start = 1, m.end(), m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        items, cur, d = [], "", 0
        for ch in text[start:i - 1]:
            if ch == "," and d == 0:
                items.append(cur)
                cur = ""
                continue
            d += {"(": 1, ")": -1}.get(ch, 0)
            cur += ch
        items.append(cur)
        cols = []
        for it in items:
            lead = LEADING_IDENT.match(it)
            if lead and lead.group(1).lower() not in NOT_A_COLUMN:
                cols.append(column_name(lead.group(1)))
        yield m.start(), norm("table", m.group(1))[1], cols


def columns_of(text, into=None, source=None):
    """Apply a file's column statements to `into` {(table, column): source} IN THE ORDER THEY APPEAR — a `drop
    table` then `create table` of one name in one file must leave the new table's columns, not erase them."""
    cols = {} if into is None else into
    events = [(pos, "create", table, names) for pos, table, names in table_bodies(text)]
    events += [(m.start(), "alter", norm("table", m.group(1))[1], m.group(2)) for m in ALTER.finditer(text)]
    events += [(m.start(), "drop", norm("table", m.group(2))[1], None) for m in DROP.finditer(text)
               if m.group(1).lower() == "table"]
    for _pos, kind, table, data in sorted(events, key=lambda e: e[0]):
        if kind == "create":
            for c in data:
                cols.setdefault((table, c), source)
        elif kind == "drop":
            for key in [k for k in cols if k[0] == table]:
                cols.pop(key)
        else:
            for c in ADD_COL.findall(data):
                cols.setdefault((table, column_name(c)), source)
            for c in DROP_COL.findall(data):
                cols.pop((table, column_name(c)), None)
            for old, new in RENAME_COL.findall(data):
                cols.pop((table, column_name(old)), None)
                cols.setdefault((table, column_name(new)), source)
    return cols


def strip_sql_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return "\n".join(l.split("--")[0] for l in text.split("\n"))


def norm(kind, name):
    n = name.strip().strip('"').lower()
    if n.startswith("public."):
        n = n[len("public."):]
    return (kind.lower(), n)


def main(argv):
    if not os.path.exists(SCHEMA):
        print("  FATAL: fixture schema not found at %s" % SCHEMA)
        return 2
    schema_txt = strip_sql_comments(io.open(SCHEMA, encoding="utf-8").read())
    in_schema = {norm(k, n) for k, n in CREATE.findall(schema_txt)}

    files = sorted(glob.glob(MIGRATIONS))
    if not files:
        print("  FATAL: no migrations found at %s" % MIGRATIONS)
        return 2

    # Walk migrations in filename (date) order, and each file's statements in the order they appear: an object
    # created then dropped later is not expected in the fixture schema, and the idiomatic `drop … if exists X;
    # create … X` within one file leaves X owed (it was skipped when every create ran before every drop).
    created = {}
    for path in files:
        txt = strip_sql_comments(io.open(path, encoding="utf-8").read())
        events = sorted([(m.start(), "create", m) for m in CREATE.finditer(txt)] +
                        [(m.start(), "drop", m) for m in DROP.finditer(txt)], key=lambda e: e[0])
        for _pos, kind, m in events:
            key = norm(m.group(1), m.group(2))
            if kind == "drop":
                created.pop(key, None)
            elif not (EXEMPT.search(m.group(2).strip('"')) or key[1] in NOT_A_NAME):
                created.setdefault(key, os.path.basename(path))

    absent = sorted((k, v) for k, v in created.items() if k not in in_schema)
    known = [(k, v) for k, v in absent if k in KNOWN_DRIFT]
    missing = [(k, v) for k, v in absent if k not in KNOWN_DRIFT]

    # columns: what the migrations leave, in date order, against what the fixture schema builds
    schema_cols = columns_of(schema_txt)
    mig_cols = {}
    for path in files:
        txt = strip_sql_comments(io.open(path, encoding="utf-8").read())
        columns_of(txt, into=mig_cols, source=os.path.basename(path))
    tables_in_schema = {n for k, n in in_schema if k == "table"}
    col_absent = sorted((key, src) for key, src in mig_cols.items()
                        if src and key not in schema_cols and key[0] in tables_in_schema
                        and not EXEMPT.search(key[0]))
    col_known = [(k, v) for k, v in col_absent if k in KNOWN_COLUMN_DRIFT]
    col_missing = [(k, v) for k, v in col_absent if k not in KNOWN_COLUMN_DRIFT]

    print("  fixture schema defines %d object(s) and %d column(s); migrations create %d object(s) "
          "and touch %d column(s) (after drops)"
          % (len(in_schema), len(schema_cols), len(created), sum(1 for v in mig_cols.values() if v)))
    for (kind, name), src in known:
        print("  known drift (not failing): %-8s %s" % (kind, name))
        print("      %s" % KNOWN_DRIFT[(kind, name)])
    for (table, col), src in col_known:
        print("  known drift (not failing): column   %s.%s" % (table, col))
        print("      %s" % KNOWN_COLUMN_DRIFT[(table, col)])
    for (kind, name), src in missing:
        print("  MISSING from schema.sql: %-8s %-42s (added by %s)" % (kind, name, src))
    for (table, col), src in col_missing:
        print("  MISSING from schema.sql: column   %-42s (added by %s)" % ("%s.%s" % (table, col), src))
    if missing or col_missing:
        print("  FAIL: %d object(s) and %d column(s) exist only after a migration. A freshly"
              % (len(missing), len(col_missing)))
        print("        provisioned database will not have them, and the difference shows up as")
        print("        behaviour that works here and not on a new machine.")
        return 1
    print("  ok: every migration-created object and column is also in the fixture schema"
          + (" (%d known drift item(s) reported above)" % (len(known) + len(col_known))
             if known or col_known else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
