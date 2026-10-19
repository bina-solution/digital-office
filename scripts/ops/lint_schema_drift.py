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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "apps", "indox", "blueprint", "fixtures", "schema.sql")
MIGRATIONS = os.path.join(ROOT, "scripts", "ops", "migrations", "*.sql")

# Objects a migration is allowed to create without the fixture schema carrying them.
#   bak_*  one-off backup tables taken before a destructive step
#   *_20260806-style suffixes are the same thing, dated
EXEMPT = re.compile(r"^(public\.)?(bak_|_)", re.I)

CREATE = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?"
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
    r"\bdrop\s+(function|table|view|trigger|index)\s+"
    r"(?:if\s+exists\s+)?([a-z0-9_.\"]+)", re.I)


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

    # Walk migrations in filename (date) order; an object created then dropped later is not
    # expected in the fixture schema.
    created = {}
    for path in files:
        txt = strip_sql_comments(io.open(path, encoding="utf-8").read())
        for k, n in CREATE.findall(txt):
            key = norm(k, n)
            if EXEMPT.search(n.strip('"')) or key[1] in NOT_A_NAME:
                continue
            created.setdefault(key, os.path.basename(path))
        for k, n in DROP.findall(txt):
            created.pop(norm(k, n), None)

    absent = sorted((k, v) for k, v in created.items() if k not in in_schema)
    known = [(k, v) for k, v in absent if k in KNOWN_DRIFT]
    missing = [(k, v) for k, v in absent if k not in KNOWN_DRIFT]
    print("  fixture schema defines %d object(s); migrations create %d (after drops)"
          % (len(in_schema), len(created)))
    for (kind, name), src in known:
        print("  known drift (not failing): %-8s %s" % (kind, name))
        print("      %s" % KNOWN_DRIFT[(kind, name)])
    for (kind, name), src in missing:
        print("  MISSING from schema.sql: %-8s %-42s (added by %s)" % (kind, name, src))
    if missing:
        print("  FAIL: %d object(s) exist only after a migration. A freshly provisioned database"
              % len(missing))
        print("        will not have them, and the difference shows up as behaviour that works")
        print("        here and not on a new machine.")
        return 1
    print("  ok: every migration-created object is also in the fixture schema"
          + (" (%d known drift item(s) reported above)" % len(known) if known else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
