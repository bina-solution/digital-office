#!/usr/bin/env python3
"""
gen-indox-schema.py — regenerate the BFF's repo registry from schema.sql + the display catalog.

    python3 scripts/ops/gen-indox-schema.py            # write repos.json
    python3 scripts/ops/gen-indox-schema.py --check    # exit 1 if it has drifted (CI gate)
    python3 scripts/ops/gen-indox-schema.py --diff     # show what would change
    python3 scripts/ops/gen-indox-schema.py --live     # also cross-check against the running DB

WHERE THIS SITS IN THE CHAIN — READ THIS BEFORE EDITING ANYTHING IT TOUCHES

`apps/indox/blueprint/fixtures/schema.sql` is THE source of truth for INDOX's schema: idempotent
`alter table … add column if not exists`, applied to every environment, provisioning a fresh
database and patching an existing one with the same statements. Everything else is generated
from it:

    schema.sql ──> indoxDataGateway01  (n8n trigger schema + KNOWN_FIELDS allow-list)
               │      gen-gateway-trigger-schema.py --check   [existing, G39-gated]
               │      the ONE workflow allowed to WRITE public.incoming_documents
               │
               └──> repos.json         (the BFF's READ registry: what the UI is told exists)
                      this script --check                     [the gap this fills]

The write path was already generated and gated. The read registry was not: it was hand-maintained
and drifted to **47 of the table's 108 columns**. The 61 it never learned about were not obscure —
`created_at`, `updated_at`, `DOC_ID`, `THUMBNAIL`, `SYNC_NAME`, `MERGED_INTO`, `doc_date_norm` and
the whole AI_*/LOCAL_*/SELECTED_* provenance family. Code that needed them reached around the
registry (the dashboard queries `created_at` directly), which is how a column ends up real,
load-bearing and invisible to the layer meant to describe it.

So this script is deliberately the SAME SHAPE as gen-gateway-trigger-schema.py: same parsing
strategy, same `--check` gate, same `--live` opt-in. Two generated consumers, one source, one
convention — rather than a second way of knowing what a column is.

SOURCE OF TRUTH: schema.sql for STRUCTURE, `apps/indox/blueprint/schema/display.json` for
PRESENTATION (Hebrew labels, enum domains, default visibility). Presentation is the only part a
human writes; the column list is never hand-edited again.

`--live` is opt-in, not the default, for the reason the sibling script states: `--check` must work
in CI and in a fresh clone with no database reachable, and schema.sql *is* what stamps
information_schema in every environment — so the two are the same fact by construction unless
schema.sql has drifted from a database it was never applied to.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "apps/indox/blueprint/fixtures/schema.sql"
REGISTRY = REPO_ROOT / "apps/indox/storage/incoming_documents/repos.json"
CATALOG = REPO_ROOT / "apps/indox/blueprint/schema/display.json"

# ── identical parsing strategy to gen-gateway-trigger-schema.py / G39 ────────────────────────
# Duplicated on purpose rather than imported, for the reason that script gives: it is a
# hyphenated filename, not importable without machinery neither script otherwise needs, and two
# regexes are cheap to keep in lockstep by inspection.
_CREATE_COL = re.compile(
    r'create\s+table\s+if\s+not\s+exists\s+public\.(\w+)\s*\(\s*"([^"]+)"', re.IGNORECASE)
_ALTER_COL = re.compile(
    r'alter\s+table\s+public\.(\w+)\s+add\s+column\s+if\s+not\s+exists\s+"([^"]+)"', re.IGNORECASE)
#: the type as schema.sql declares it, so the registry says what the table actually stores
_ALTER_TYPED = re.compile(
    r'alter\s+table\s+public\.(\w+)\s+add\s+column\s+if\s+not\s+exists\s+"([^"]+)"\s+([A-Za-z ]+)',
    re.IGNORECASE)

#: SQL type → the registry's LogicalType. This is a TEXT-first schema by design, so anything
#: unrecognised is a string — which is also the safest default for a column we cannot classify.
SQL_TO_LOGICAL = {
    "text": "string", "varchar": "string", "char": "string",
    "int": "number", "integer": "number", "bigint": "number", "smallint": "number",
    "numeric": "number", "decimal": "number", "real": "number", "double precision": "number",
    "boolean": "boolean", "bool": "boolean",
    "timestamptz": "datetime", "timestamp": "datetime",
    "timestamp with time zone": "datetime", "timestamp without time zone": "datetime",
    "date": "date", "json": "json", "jsonb": "json",
}
#: server-managed columns. UNLIKE the gateway generator — which excludes them because a CALLER
#: never supplies them on a write — the READ registry must DECLARE them: they exist, the UI
#: reads them (created_at is the documents table's default sort), and omitting them here is
#: precisely the "hidden column" this script exists to end.
SERVER_MANAGED = {"created_at", "updated_at"}


def table_columns_typed(schema_sql: str, table: str) -> list[tuple[str, str]]:
    """(name, logical_type) for `table`, in schema.sql's declaration order — order-preserving and
    de-duplicated, so the generated file diffs reviewably."""
    types: dict[str, str] = {}
    for m in _ALTER_TYPED.finditer(schema_sql):
        if m.group(1) == table:
            types[m.group(2)] = SQL_TO_LOGICAL.get(m.group(3).strip().lower(), "string")
    cols: dict[str, str] = {}
    for pat in (_CREATE_COL, _ALTER_COL):
        for m in pat.finditer(schema_sql):
            if m.group(1) == table:
                cols.setdefault(m.group(2), types.get(m.group(2), "string"))
    return list(cols.items())


def deployment_name() -> str:
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DEPLOYMENT_NAME="):
                return line.split("=", 1)[1].strip()
    return "bina-deployment"


def live_columns(table: str) -> list[str] | None:
    sql = ("select column_name from information_schema.columns "
           f"where table_schema='public' and table_name='{table}' order by ordinal_position;")
    r = subprocess.run(
        ["docker", "exec", f"supabase-db-{deployment_name()}",
         "psql", "-U", "postgres", "-d", "postgres", "-tAc", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[gen-indox-schema] --live: DB unreachable ({r.stderr.strip()[:120]})",
              file=sys.stderr)
        return None
    return [c.strip() for c in r.stdout.splitlines() if c.strip()]


def build(repo: dict, table: str, schema_sql: str, catalog: dict) -> list[dict]:
    prev = {c["name"]: c for c in repo.get("columns", [])}
    meta = ((catalog.get("tables") or {}).get(table) or {}).get("columns") or {}
    out = []
    for name, logical in table_columns_typed(schema_sql, table):
        old = prev.get(name, {})
        col = {
            "name": name,
            "type": logical,
            # nullable/unique/default describe INTENT the app enforces, which schema.sql's
            # `add column if not exists <TYPE>` does not state — so the registry's existing
            # opinion is preserved rather than flattened to a guess.
            "nullable": old.get("nullable", True),
            "unique": old.get("unique", False),
            "default": old.get("default"),
        }
        for k in ("label", "enum", "visible", "searchable", "align", "deprecated", "description"):
            v = (meta.get(name) or {}).get(k)
            if v is not None:
                col[k] = v
        out.append(col)
    return out


def regenerate(live: bool) -> tuple[list[dict], list[str], bool]:
    schema_sql = SCHEMA_SQL.read_text(encoding="utf-8")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    notes: list[str] = []
    ok = True
    for repo in registry:
        if repo.get("backend") != "supabase":
            continue
        table = (repo.get("supabase") or {}).get("table")
        if not table:
            continue
        before = {c["name"] for c in repo.get("columns", [])}
        cols = build(repo, table, schema_sql, catalog)
        if not cols:
            print(f"[gen-indox-schema] FATAL: no columns for public.{table} in schema.sql",
                  file=sys.stderr)
            return registry, notes, False
        repo["columns"] = cols
        after = {c["name"] for c in cols}
        used = {c["enum"] for c in cols if c.get("enum")}
        repo["enums"] = {k: v for k, v in (catalog.get("enums") or {}).items() if k in used}

        labelled = sum(1 for c in cols if c.get("label"))
        notes.append(f"{repo['name']} ({table}): {len(after)} columns, {labelled} labelled, "
                     f"{len(repo['enums'])} enum domains  [+{len(after - before)} newly declared]")
        if after - before:
            notes.append("  newly declared: " + ", ".join(sorted(after - before)))

        if live:
            db = live_columns(table)
            if db is not None:
                missing = [c for c in db if c not in after]
                if missing:
                    ok = False
                    notes.append("  LIVE MISMATCH — in the database but not in schema.sql: "
                                 + ", ".join(missing))
                else:
                    notes.append(f"  live cross-check OK ({len(db)} columns in the database)")
    return registry, notes, ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()

    new, notes, live_ok = regenerate(a.live)
    for n in notes:
        print(f"[gen-indox-schema] {n}")
    rendered = json.dumps(new, ensure_ascii=False, indent=2) + "\n"
    current = REGISTRY.read_text(encoding="utf-8")

    if a.diff:
        import difflib
        sys.stdout.writelines(difflib.unified_diff(
            current.splitlines(True), rendered.splitlines(True),
            fromfile="repos.json (current)", tofile="repos.json (generated)"))
        return 0
    if a.check:
        if rendered != current:
            print("[gen-indox-schema] FAIL — repos.json has drifted from schema.sql.\n"
                  "                   Run: python3 scripts/ops/gen-indox-schema.py",
                  file=sys.stderr)
            return 1
        if not live_ok:
            return 1
        print("[gen-indox-schema] up to date")
        return 0
    if rendered != current:
        REGISTRY.write_text(rendered, encoding="utf-8")
        print(f"[gen-indox-schema] wrote {REGISTRY.relative_to(REPO_ROOT)}")
    else:
        print("[gen-indox-schema] no change")
    return 0 if live_ok else 1


if __name__ == "__main__":
    sys.exit(main())
