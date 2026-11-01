#!/usr/bin/env python3
"""FROM_OFFICE -> FROM_WAREHOUSE : the complete, atomic rename patch set.

    python3 scripts/ops/rename-from-office-to-warehouse.py --check   # dry run, no writes
    python3 scripts/ops/rename-from-office-to-warehouse.py --apply   # all-or-nothing rewrite

PREPARED, NOT APPLIED. Hand-off artifact: run --apply in ONE pass, once the agent
holding indoxV2ActionsGDoc01/Ship01 has released them. A rename split across two
agents and two moments is the partial rename this whole effort exists to avoid.

────────────────────────────────────────────────────────────────────────────────
WHY THIS IS AN ALLOWLIST AND NOT A repo-wide sed — READ THIS FIRST
────────────────────────────────────────────────────────────────────────────────
A repo-wide search for FROM_OFFICE matches **36,995 occurrences across 209 files**
(measured 2026-08-06). Only ~156 of them are live code. The rest are DATA that must
never be rewritten, and a `sed -i` across the tree would silently corrupt all of it:

    apps/indox/storage/.../incoming-documents-main.json     12,443   live DB snapshot
    apps/apitools/feature-validation/.../benchmark-*.json    8,496   4 frozen benchmarks
    .claude/worktrees/fervent-mestorf-*/**                   ~4,000  another worktree
    data/_wf_backup/**, data/exclude/**, data/_runs/**       ~3,500  backups/exports
    .tmp-indox-v2-ct/*.out                                   ~8,000  scratch test output
    legacy/n8n/indox-sheets-era/**                               10  retirement archive

Those files record what the columns WERE called at the time they were written.
Rewriting a historical snapshot does not migrate anything — it falsifies the record
and destroys the only evidence of the pre-rename state. They are excluded by
construction: this tool touches ONLY the paths named in IN_SCOPE below.

────────────────────────────────────────────────────────────────────────────────
THE THREE SITES THAT MUST NOT BE RENAMED — a different namespace, same string
────────────────────────────────────────────────────────────────────────────────
`FROM_OFFICE` is ALSO a STATUS enum value (UI category "attention", Hebrew label
'מהמשרד'), which has nothing to do with the incoming_documents column:

    apps/indox/app/incoming_documents/api/__init__.py         _DASH_STATUS_GROUP
    apps/indox/app/webapp/src/pages/DashboardPage.tsx         status legend label
    digital-office/sim/apps/indox/src/pages/DashboardPage.tsx same, in the sim fork

They are absent from IN_SCOPE. `--check` ASSERTS each still holds exactly its known
occurrence count, so if someone later adds a genuine column reference to one of these
files the tool fails loudly instead of quietly leaving it behind.

Also deliberately untouched (different identifiers that merely contain the words):
    FROMWAREHOUSE          Priority-ERP outbound payload field (no underscore) —
                           renaming it breaks the Priority integration
    WarehouseScansSourceFolder / WAREHOUSE_FOLDER   settings key names, not columns
    indoxV2SearchWarehouse01                        a workflow name
    check_from_office                               an ACTION name, not a column;
                                                    renaming actions is a separate
                                                    change with its own G41 exposure

────────────────────────────────────────────────────────────────────────────────
schema.sql IS DELIBERATELY NOT IN SCOPE
────────────────────────────────────────────────────────────────────────────────
"FROM_WAREHOUSE"/"FROM_WAREHOUSE_CHECK" already exist there (and live in the DB).
The legacy "FROM_OFFICE"/"FROM_OFFICE_CHECK" declarations must SURVIVE this rename —
they hold all 5,697/5,719 populated values until the backfill has run and been
verified. Dropping them is the final, separate phase. See
scripts/ops/indox-column-consolidation.sql §4.

SEQUENCE: run §4 of that file (backfill) BEFORE --apply here. Otherwise every writer
switches to a column that is still 100% NULL and the pipeline reads empty values.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: FROM_OFFICE_CHECK must win over FROM_OFFICE — one regex with an optional suffix
#: group does that correctly in a single pass (no double-rewrite hazard).
PATTERN = re.compile(r"FROM_OFFICE(_CHECK)?")
REPLACE = r"FROM_WAREHOUSE\1"

#: Every live code path that reads or writes the column. path -> occurrences expected
#: at preparation time (2026-08-06). A mismatch is reported, not silently accepted.
IN_SCOPE: dict[str, int] = {
    # ---- n8n blueprints: the write/declare surface -------------------------
    "apps/indox/blueprint/n8n/indoxDocBatchUpsert01.json": 72,
    "apps/indox/blueprint/n8n/indoxV2Driver01.json": 21,
    "apps/indox/blueprint/n8n/indoxV2ActionsGDoc01.json": 9,   # OWNED by extraction agent
    "apps/indox/blueprint/n8n/indoxV2ActionsShip01.json": 9,   # OWNED by extraction agent
    "apps/indox/blueprint/n8n/indoxGmailBSDownloader01.json": 4,
    "apps/indox/blueprint/n8n/indoxGmailDocDownloader01.json": 4,
    "apps/indox/blueprint/n8n/indoxGmailLinkDownloader01.json": 4,
    "apps/indox/blueprint/n8n/SyncProcBS000001.json": 4,
    "apps/indox/blueprint/n8n/SyncProcGDoc0001.json": 4,
    "apps/indox/blueprint/n8n/indoxV2DecideTest01.json": 3,
    "apps/indox/blueprint/n8n/indoxDataGateway01.json": 2,
    "apps/google-workspace-agent/blueprint/n8n/gSheetMcpAgent01.json": 2,
    # ---- fixtures / seeds --------------------------------------------------
    "apps/indox/blueprint/fixtures/fixture_INVOICE.json": 2,
    "apps/indox/blueprint/fixtures/types/fixture_INVOICE.json": 2,
    "apps/indox/blueprint/fixtures/types/fixture_SHIPMENT.json": 2,
    "apps/indox/blueprint/fixtures/settings.json": 2,
    # ---- app code ----------------------------------------------------------
    # the editable field grid — these ARE column names (SOURCE_FIELDS)
    "apps/indox/app/webapp/src/pages/DocumentDetailPage.tsx": 2,
    "apps/indox/storage/incoming_documents/repos.json": 2,
}

#: Files whose ONLY occurrence is the STATUS enum value, never the column.
#: --check asserts the count is unchanged so a future column reference cannot hide here.
STATUS_VALUE_ONLY: dict[str, int] = {
    "apps/indox/app/incoming_documents/api/__init__.py": 1,
    "apps/indox/app/webapp/src/pages/DashboardPage.tsx": 1,
    "digital-office/sim/apps/indox/src/pages/DashboardPage.tsx": 1,
}

#: Owned by the in-flight extraction refactor — --apply refuses unless --force-owned.
OWNED_BY_OTHER_AGENT = {
    "apps/indox/blueprint/n8n/indoxV2ActionsGDoc01.json",
    "apps/indox/blueprint/n8n/indoxV2ActionsShip01.json",
}


def scan() -> tuple[list[tuple[str, int, int]], list[str]]:
    """Returns (rows, problems). rows = (path, expected, actual)."""
    rows, problems = [], []
    for rel, expected in IN_SCOPE.items():
        p = REPO / rel
        if not p.exists():
            problems.append(f"MISSING: {rel}")
            continue
        actual = len(PATTERN.findall(p.read_text(encoding="utf-8")))
        rows.append((rel, expected, actual))
        if actual == 0:
            problems.append(f"ALREADY RENAMED or empty: {rel} (expected {expected})")
        elif actual != expected:
            problems.append(
                f"DRIFT: {rel} has {actual} occurrence(s), manifest says {expected} "
                f"— a file changed since this patch set was prepared; re-review before applying")
    for rel, expected in STATUS_VALUE_ONLY.items():
        p = REPO / rel
        if not p.exists():
            problems.append(f"MISSING (status-value file): {rel}")
            continue
        actual = len(PATTERN.findall(p.read_text(encoding="utf-8")))
        if actual != expected:
            problems.append(
                f"STATUS-VALUE FILE CHANGED: {rel} now has {actual} occurrence(s), "
                f"expected {expected}. One of them may be a real COLUMN reference that must "
                f"be renamed — INSPECT BY HAND before applying.")
    return rows, problems


def rewrite_all() -> dict[pathlib.Path, str]:
    """Build every new file body in memory. Raises before anything is written."""
    staged: dict[pathlib.Path, str] = {}
    for rel in IN_SCOPE:
        p = REPO / rel
        old = p.read_text(encoding="utf-8")
        new = PATTERN.sub(REPLACE, old)
        if p.suffix == ".json":
            json.loads(new)          # must still parse — fail the whole run if not
        if PATTERN.search(new):
            raise RuntimeError(f"{rel}: FROM_OFFICE survived the rewrite")
        staged[p] = new
    return staged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force-owned", action="store_true",
                    help="apply even to files owned by the extraction agent")
    a = ap.parse_args()
    if not (a.check or a.apply):
        ap.error("pass --check or --apply")

    rows, problems = scan()
    total = sum(r[2] for r in rows)
    print(f"{'file':<62} {'want':>5} {'have':>5}")
    print("-" * 76)
    for rel, exp, act in rows:
        flag = "  <- OWNED" if rel in OWNED_BY_OTHER_AGENT else ""
        print(f"{rel:<62} {exp:>5} {act:>5}{flag}")
    print("-" * 76)
    print(f"{'TOTAL in scope':<62} {sum(r[1] for r in rows):>5} {total:>5}")
    print(f"\nexcluded STATUS-value sites (NOT renamed): {len(STATUS_VALUE_ONLY)}")

    if problems:
        print("\nPROBLEMS:")
        for pr in problems:
            print(f"  ! {pr}")

    if a.check:
        print("\nCHECK ONLY — nothing written.")
        return 1 if problems else 0

    if problems:
        print("\nREFUSING TO APPLY while problems are outstanding. Resolve them first.")
        return 1
    if not a.force_owned:
        print("\nREFUSING TO APPLY: this set includes files owned by the extraction agent\n"
              "  " + "\n  ".join(sorted(OWNED_BY_OTHER_AGENT)) + "\n"
              "Confirm that agent has released them, then re-run with --force-owned.\n"
              "Applying only the unowned subset would create exactly the partial rename\n"
              "this tool exists to prevent.")
        return 1

    staged = rewrite_all()          # all-or-nothing: raises before any write
    for p, body in staged.items():
        p.write_text(body, encoding="utf-8", newline="")
    print(f"\nAPPLIED to {len(staged)} file(s), {total} occurrence(s).")
    print("NOW RE-RUN THE GATES:")
    print("  python3 scripts/refactor/trigger-schema-drift-lint.py")
    print("  python3 scripts/refactor/gen-gateway-trigger-schema.py --check")
    print("  python3 scripts/refactor/switch-fallback-lint.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
