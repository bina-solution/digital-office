#!/usr/bin/env python3
"""Assert the owner's ABOLISHED schema laws stay dead in every committed source.

THE RESURRECTION THIS CATCHES
-----------------------------
2026-08-17 the owner retired three things from the incoming-documents schema:

  unique index on ("HASH")                          "the dedup ACTION owns dedup"
  unique index on ("COMPANY_ID","COMPANY_DOC_ID")
  column COMPANY_DOC_ID                             "DOC_ID is the one canonical doc number"

They were dropped from the live table and the fixture — but survived as DECLARATIONS in the
repo registry (`storage/incoming_documents/repos.json` -> `supabase.indexes` / `columns`).
Harmless for a year of main-table operation, until 2026-08-24: provisioning a NEW table (the
archive twin) read the stale declarations and faithfully re-materialised all three, and
`ux_incoming_documents_archive_HASH` aborted a 15,364-row archive move on the first legitimate
duplicate hash.

Two layers now hold the line:
  1. runtime — `backends/supabase.py` (`_RETIRED_UNIQUE_INDEXES` / `_RETIRED_COLUMNS`) refuses
     to materialise these whatever a config says;
  2. this lint — fails if anyone re-DECLARES them in the registry or re-CREATES them in the
     fixture schema, so the stale-config state itself cannot come back.

Static, over committed files; does not read the live database. Exit 1 on any hit.
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_GLOB = os.path.join(
    ROOT, "apps", "indox", "storage", "incoming_documents", "**", "*.json")
SCHEMA = os.path.join(ROOT, "apps", "indox", "blueprint", "fixtures", "schema.sql")

RETIRED_INDEXES = {("HASH",), ("COMPANY_ID", "COMPANY_DOC_ID")}
RETIRED_COLUMN = "COMPANY_DOC_ID"

failures: list[str] = []


def check_registry(path: str) -> None:
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return  # not a registry document (e.g. a data snapshot too big/foreign) — not ours
    repos = data if isinstance(data, list) else [data]
    for repo in repos:
        if not isinstance(repo, dict) or "columns" not in repo:
            continue  # row-data snapshots etc.
        name = repo.get("name", "?")
        for col in repo.get("columns") or []:
            if isinstance(col, dict) and col.get("name") == RETIRED_COLUMN:
                failures.append(
                    f"{path}: repo '{name}' declares retired column {RETIRED_COLUMN}")
        sup = repo.get("supabase") or {}
        for idx in (sup.get("indexes") or []):
            if tuple(idx) in RETIRED_INDEXES:
                failures.append(
                    f"{path}: repo '{name}' declares retired unique index {tuple(idx)}")
        for rule in repo.get("upsert_match_rules") or []:
            cols = tuple((rule or {}).get("columns") or [])
            if RETIRED_COLUMN in cols:
                failures.append(
                    f"{path}: repo '{name}' upsert_match_rule references retired "
                    f"column {RETIRED_COLUMN}")


def check_fixture(path: str) -> None:
    if not os.path.exists(path):
        failures.append(f"{path}: fixture schema missing")
        return
    with io.open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("--", 1)[0]  # comments may NAME the dead laws; code may not
            if not line.strip():
                continue
            if re.search(r'add\s+column\s+if\s+not\s+exists\s+"?' + RETIRED_COLUMN,
                         line, re.I):
                failures.append(f"{path}:{lineno}: fixture re-adds retired column")
            if re.search(r'create\s+unique\s+index', line, re.I) and '"HASH"' in line:
                failures.append(f"{path}:{lineno}: fixture re-creates unique HASH index")


def main() -> int:
    for path in sorted(glob.glob(REGISTRY_GLOB, recursive=True)):
        check_registry(path)
    check_fixture(SCHEMA)
    if failures:
        print("DEAD-LAW RESURRECTION DETECTED (owner order 2026-08-17; incident 2026-08-24):")
        for f in failures:
            print("  " + f)
        return 1
    print("lint_dead_laws: clean (registry + fixture carry none of the retired declarations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
