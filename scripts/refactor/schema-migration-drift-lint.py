#!/usr/bin/env python3
"""schema-migration-drift-lint — gate G109: what a migration creates, a fresh office's schema creates too (DGO-235).

    python3 scripts/refactor/schema-migration-drift-lint.py
    python3 scripts/refactor/schema-migration-drift-lint.py --self-test

Two things build an INDOX instance's schema and they advance independently: apps/indox/blueprint/fixtures/schema.sql
builds a FRESH one (hooks/apply-schema), scripts/ops/migrations/*.sql advance an EXISTING one. When a migration adds a
table, a view, a function, an index, a trigger or a COLUMN that schema.sql lacks, every office that already ran the
migration works and every new office does not — the code is identical and only the substrate differs.

That happened twice, each time found by hand: LINK_CONNECTION (a column; every linked document classified unopenable
on a fresh database — apps/indox/issues/schema-drift-fixture-vs-live.md) and `sync_item_reasons` (a view the sync
board reads; in a 2026-09-03 migration only, found by this gate's first run on 2026-11-10). The check itself is
scripts/ops/lint_schema_drift.py — this gate runs THAT, it is not a second copy — so the mechanism the issue left open
("nothing compares them") is closed where it can be closed statically: every build compares them. Each known drift is
recorded in the lint with its reason (one today: a migration never applied anywhere, whose column must not be
pushed onto live instances by schema.sql). What it does not check, said rather than implied: that two definitions
under one name are the same, and anything done to a live database by hand (hooks/schema-drift reads a live one).
"""
from __future__ import annotations

import importlib.util
import io
import os
import pathlib
import sys
import tempfile
from contextlib import redirect_stdout

# It prints Hebrew (G10): python on Windows writes it in the console's codepage and dies on its own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
LINT = REPO / "scripts" / "ops" / "lint_schema_drift.py"


def load():
    spec = importlib.util.spec_from_file_location("lint_schema_drift", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check() -> int:
    if not LINT.exists():
        print(f"G109 FAIL — the check is gone: {LINT.relative_to(REPO)}")
        return 1
    rc = load().main([])
    print("G109 PASS — every object and column a migration creates is in the fixture schema" if rc == 0 else
          "G109 FAIL — a migration creates what a freshly provisioned office will not have (above)")
    return 0 if rc == 0 else 1


def self_test() -> int:
    mod = load()
    table = 'create table if not exists incoming_documents ("ID" text primary key, "TYPE" text);\n'
    cases = [
        # (name, schema.sql, {migration: text}, the verdict wanted)
        ("a column only a migration adds (LINK_CONNECTION) fails", table,
         {"2026-08-13_link.sql": 'alter table incoming_documents add column if not exists "LINK_CONNECTION" text;'}, 1),
        ("a view only a migration creates (sync_item_reasons) fails", table,
         {"2026-09-03_reasons.sql": "create or replace view sync_item_reasons as select 1 as n;"}, 1),
        ("both carried in schema.sql pass",
         table + 'alter table incoming_documents add column if not exists "LINK_CONNECTION" text;\n'
                 "create or replace view sync_item_reasons as select 1 as n;\n",
         {"2026-08-13_link.sql": 'alter table incoming_documents add column if not exists "LINK_CONNECTION" text;',
          "2026-09-03_reasons.sql": "create or replace view sync_item_reasons as select 1 as n;"}, 0),
        ("a column added then dropped by later migrations is not owed", table,
         {"2026-08-01_a.sql": "alter table incoming_documents add column x text;",
          "2026-08-02_b.sql": "alter table incoming_documents drop column if exists x;"}, 0),
        ("a renamed column is owed under its new name", table + 'alter table incoming_documents add column "OLD" text;\n',
         {"2026-08-01_a.sql": 'alter table incoming_documents add column "OLD" text;',
          "2026-08-02_b.sql": 'alter table incoming_documents rename column "OLD" to "NEW";'}, 1),
        ("a quoted column is its own case: \"Id\" is not \"ID\"", table,
         {"2026-08-01_a.sql": 'alter table incoming_documents add column "Id" text;'}, 1),
        ("a column of a table the schema carries in its create body passes",
         'create table t (a int, b numeric(12,2), constraint t_pk primary key (a));\n',
         {"2026-08-01_a.sql": "alter table t add column if not exists b numeric(12,2);"}, 0),
        ("a backup table a migration takes is exempt", table,
         {"2026-08-01_a.sql": "create table bak_incoming_documents_20260801 as select * from incoming_documents;"}, 0),
        # the second reader's blind spots, each a case (statements in order; quoted names; ADD without COLUMN; UNIQUE)
        ("a drop-then-create in ONE migration is owed", table,
         {"2026-08-01_a.sql": "drop trigger if exists trg_x on incoming_documents; create trigger trg_x after insert "
                              "on incoming_documents for each row execute function f();"}, 1),
        ("a quoted column with a space, in the schema's create body, is that column",
         'create table companies ("ID" text primary key, "שם חברה" text, "מזהה 1" text);\n',
         {"2026-08-01_a.sql": 'alter table companies add column if not exists "שם חברה" text;'}, 0),
        ("ADD without the COLUMN keyword is a column", table,
         {"2026-08-01_a.sql": 'alter table incoming_documents add "LINK_CONNECTION" text;'}, 1),
        ("a UNIQUE index only a migration creates is owed", table,
         {"2026-08-01_a.sql": 'create unique index if not exists ux_doc on incoming_documents ("ID");'}, 1),
        ("ADD CONSTRAINT is not a column", table,
         {"2026-08-01_a.sql": 'alter table incoming_documents add constraint c_type check ("TYPE" <> \'\');'}, 0),
    ]
    failed = 0
    keep = (mod.SCHEMA, mod.MIGRATIONS)
    try:
        for name, schema, migrations, want in cases:
            with tempfile.TemporaryDirectory() as tmp:
                (pathlib.Path(tmp) / "schema.sql").write_text(schema, encoding="utf-8")
                (pathlib.Path(tmp) / "m").mkdir()
                for fname, text in migrations.items():
                    (pathlib.Path(tmp) / "m" / fname).write_text(text, encoding="utf-8")
                mod.SCHEMA, mod.MIGRATIONS = os.path.join(tmp, "schema.sql"), os.path.join(tmp, "m", "*.sql")
                with redirect_stdout(io.StringIO()):
                    got = mod.main([])
            ok = got == want
            failed += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {name} (exit {got}, wanted {want})")
    finally:
        mod.SCHEMA, mod.MIGRATIONS = keep
    print("schema-migration-drift-lint self-test:", "PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else check())
