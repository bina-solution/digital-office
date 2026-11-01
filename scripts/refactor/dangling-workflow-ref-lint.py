#!/usr/bin/env python3
"""dangling-workflow-ref-lint — gate G38: every workflow reference names a workflow that exists.

    python3 scripts/refactor/dangling-workflow-ref-lint.py [--self-test]

WHY THIS EXISTS. 41 live workflows (`ai/context/archive/indox-pre-2026-09/ERROR-RCA-2026-08-05.md`, 2026-08-05) had
`settings.errorWorkflow` pointing at `RqAY1Z1i2F7ZaPbe` — a workflow id that does not exist,
presumably a stale id left by an earlier Error-Handler rename. n8n's runtime behaviour for a
dangling `errorWorkflow` is not an error the way a dangling `executeWorkflow` target is (that fails
loud, on every run, at the caller): it logs one line — `Calling Error Workflow for "<name>". Could
not find workflow "<id>"` — from the crash-recovery path, and creates **zero** execution_entity
rows. No red execution, no failed run, nothing in the n8n UI's execution list. For all 41 workflows,
every real production failure for as long as there is retained history has been silently discarded
at the exact moment it was supposed to trigger an alert. The defect was invisible precisely because
alerting is the thing that tells you something is broken, and this is the one class of break that
disables alerting itself without leaving a trace.

The dangling value was **live-only drift** — none of the 41 blueprint files had ever had an
`errorWorkflow` key at all, so `git diff` before this fix showed nothing wrong; the value had been
set via the n8n UI's per-workflow dropdown, against a workflow id that existed at some earlier point
(presumably an older, differently-id'd Error Handler), and was never captured back into git. A gate
that only looked at blueprint files before the fix would have found nothing, correctly — the bug
lived in the live DB, not the tree. What this gate polices going forward is the blueprint tree
itself: once a workflow's `errorWorkflow` (or an `executeWorkflow` node's target) is set to a REAL
id and captured into git, a later edit that breaks it — a rename, a deleted workflow file, a typo'd
id pasted from the wrong place — is exactly the kind of silent, no-execution-row failure this gate
exists to catch before it reaches a push.

WHAT COUNTS AS A REFERENCE:
  * `settings.errorWorkflow` at the top level of a workflow export — a plain id string.
  * an `executeWorkflow` node's `parameters.workflowId` — `{"value": "<id>", ...}` (the resource-
    locator shape every node in this tree uses, `mode` "id" or "list") or, defensively, a bare string.

A reference is DANGLING if its target id is not the `id` of any workflow blueprint file in this
repo. Empty/absent `errorWorkflow` is fine (most workflows correctly have none — not every workflow
needs its own error handler, it inherits n8n's instance-level default). An `executeWorkflow` node
whose `workflowId` is an *expression* (starts with `=`, i.e. resolved at runtime from data) is not
checked — this gate has no way to evaluate it, and a wrong runtime-resolved id is a data bug, not a
blueprint-authoring bug. A `disabled: true` node is not checked either — n8n never executes it, and
this repo already relies on that: `indoxV2Driver01.json`'s "Call 'Snooze Incoming Document'" node
still points at `bdchh5urW9lBzudZ`, deliberately archived to `apps/n8n/_archive/` in commit
`ec20a671` ("prune 49 disposable workflows + archive Snooze") which left the caller node disabled
rather than deleted — the commit message's own words, "disabled Snooze nodes left harmless", is the
precedent this gate follows.

SCOPE: every n8n workflow under `apps/*/blueprint/n8n/*.json` and `apps/n8n/blueprint/n8n/*.json`
— the same roots G19 (`workflow-input-lint`) and G37 (`source-id-lint`) scan. A workflow that is live
in the n8n database but was never captured into a blueprint file (this repo has exactly one such
case today — `indoxDocUploader01` / "DocumentUploader", a workflow retired by an app consolidation
that stayed active live; see `ai/context/archive/indox-pre-2026-09/ERROR-RCA-2026-08-05.md`) is invisible to this gate by
construction: a static gate can only diff the tree against itself, not against a live server nobody
guarantees is running in CI. That workflow's dangling reference was fixed live directly (no
blueprint file exists to fix), and is flagged separately in the task report — it is not something
this gate can be made to catch without turning it into a live-DB check, which would break every
other lane that runs this gate offline.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
# [2026-08-23] These read *.json until today. The blueprints became .workflow.ts in 52b32aa4
# and no .json has existed under these roots since, so REPO.glob() matched nothing, the gate
# checked zero files and printed PASS. See the empty-scan guard in main().
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)


def _workflow_id_target(value) -> str | None:
    """Pull the target id out of an executeWorkflow node's `workflowId` parameter, or None if it
    isn't a static reference this gate can check (an expression, or an unrecognised shape)."""
    if isinstance(value, str):
        if value.startswith("="):
            return None  # runtime-resolved — out of scope, see docstring
        return value or None
    if isinstance(value, dict):
        v = value.get("value")
        if isinstance(v, str) and not v.startswith("=") and v:
            return v
    return None


def find_references(doc: dict) -> list[tuple[str, str, str]]:
    """Yield (kind, node/context, target_id) for every static workflow reference in `doc`."""
    out: list[tuple[str, str, str]] = []
    settings = doc.get("settings")
    if isinstance(settings, dict):
        ew = settings.get("errorWorkflow")
        if isinstance(ew, str) and ew:
            out.append(("errorWorkflow", "settings", ew))
    for node in doc.get("nodes", []) or []:
        if not str(node.get("type", "")).endswith(".executeWorkflow"):
            continue
        if node.get("disabled"):
            continue  # never executes — see docstring, "Call 'Snooze Incoming Document'"
        target = _workflow_id_target((node.get("parameters") or {}).get("workflowId"))
        if target:
            out.append(("executeWorkflow", str(node.get("name") or "?"), target))
    return out


def check(doc: dict, known_ids: set[str]) -> list[tuple[str, str, str]]:
    """Return the references in `doc` whose target is not in `known_ids`."""
    return [ref for ref in find_references(doc) if ref[2] not in known_ids]


#: The ids that left the blueprints for good — see the file's own header for who else reads it.
RETIRED_LIST = REPO / "apps" / "n8n" / "retired-workflows.txt"


def retired_ids(text: str) -> list[str]:
    return [ln.split()[0] for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def resurrected(known_ids: dict[str, str], retired: list[str]) -> list[tuple[str, str]]:
    """(id, path) for every retired id that has a blueprint file again. `bbox n8n pull all`
    exports the whole instance, so a retired workflow comes back from any instance that still
    holds it; pull skips the listed ids, and this is what notices when one arrives another way."""
    return [(wid, known_ids[wid]) for wid in retired if wid in known_ids]


# ─────────────────────────────────────────────────────────────────────────────
def collect_known_ids() -> dict[str, str]:
    """workflow id -> repo-relative path, for every blueprint file on disk."""
    ids: dict[str, str] = {}
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(str(path))
            except (OSError, ValueError, CompileError):
                continue
            wid = doc.get("id")
            if isinstance(wid, str) and wid:
                ids[wid] = str(path.relative_to(REPO)).replace("\\", "/")
    return ids


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    ("dangling errorWorkflow", True,
     {"id": "wfA", "settings": {"errorWorkflow": "doesNotExist99"}, "nodes": []},
     {"wfA", "errorHandler01"}),
    ("errorWorkflow pointing at a real id", False,
     {"id": "wfA", "settings": {"errorWorkflow": "errorHandler01"}, "nodes": []},
     {"wfA", "errorHandler01"}),
    ("no errorWorkflow key at all — the normal case", False,
     {"id": "wfA", "settings": {"executionOrder": "v1"}, "nodes": []},
     {"wfA", "errorHandler01"}),
    ("dangling executeWorkflow target, resource-locator shape", True,
     {"id": "wfA", "nodes": [{"name": "Call It", "type": "n8n-nodes-base.executeWorkflow",
       "parameters": {"workflowId": {"__rl": True, "value": "ghostWf01", "mode": "list"}}}]},
     {"wfA"}),
    ("executeWorkflow target that exists", False,
     {"id": "wfA", "nodes": [{"name": "Call It", "type": "n8n-nodes-base.executeWorkflow",
       "parameters": {"workflowId": {"__rl": True, "value": "wfB", "mode": "id"}}}]},
     {"wfA", "wfB"}),
    ("executeWorkflow target resolved at runtime (expression) — not checkable, must allow", False,
     {"id": "wfA", "nodes": [{"name": "Call Dynamic", "type": "n8n-nodes-base.executeWorkflow",
       "parameters": {"workflowId": {"__rl": True, "value": "={{ $json.targetWfId }}", "mode": "id"}}}]},
     {"wfA"}),
    ("non-executeWorkflow node with an unrelated workflowId-shaped param — must not be scanned", False,
     {"id": "wfA", "nodes": [{"name": "Unrelated", "type": "n8n-nodes-base.noOp",
       "parameters": {"workflowId": {"value": "ghostWf01"}}}]},
     {"wfA"}),
    ("dangling target but the node is disabled — must allow (never executes)", False,
     {"id": "wfA", "nodes": [{"name": "Call Archived", "type": "n8n-nodes-base.executeWorkflow",
       "disabled": True,
       "parameters": {"workflowId": {"__rl": True, "value": "archivedWf01", "mode": "list"}}}]},
     {"wfA"}),
]


def self_test() -> int:
    bad = 0
    for label, should, doc, known in SELF_TEST:
        got = bool(check(doc, known))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    listed = retired_ids("# a comment\n\nwfOld01   folded into wfNew01\n  # indented comment\nwfOld02\n")
    extra = [
        ("the retired list: ids only, comments and blank lines skipped", listed == ["wfOld01", "wfOld02"]),
        ("a retired id with a blueprint file again is caught, with its path",
         resurrected({"wfOld01": "apps/n8n/blueprint/n8n/wfOld01.workflow.ts", "wfNew01": "x"}, listed)
         == [("wfOld01", "apps/n8n/blueprint/n8n/wfOld01.workflow.ts")]),
        ("a retired id that stayed away is not", resurrected({"wfNew01": "x"}, listed) == []),
    ]
    for label, ok in extra:
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}")
    total = len(SELF_TEST) + len(extra)
    print(f"\nG38 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    known_ids = collect_known_ids()
    findings: list[tuple[str, str, str, str]] = []  # path, kind, node, target
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(str(path))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {path.relative_to(REPO)}: {e}")
                continue
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for kind, node, target in check(doc, set(known_ids)):
                findings.append((rel, kind, node, target))

    for wid, rel in resurrected(known_ids, retired_ids(RETIRED_LIST.read_text(encoding="utf-8"))
                                if RETIRED_LIST.is_file() else []):
        findings.append((rel, "retired, and shipped again", "-", wid))

    # A gate that scanned nothing must never report PASS. This one did exactly that for as long
    # as its globs pointed at a file extension the repo no longer uses, and a green gate is
    # indistinguishable from a working one until something downstream breaks.
    if not known_ids:
        print("G38 FAIL — scanned ZERO blueprint workflows. BLUEPRINT_GLOBS matches no "
              "file on disk, so this gate is checking nothing." + chr(10)
              + "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    if not findings:
        print(f"G38 PASS — every errorWorkflow / executeWorkflow reference in "
              f"{len(known_ids)} blueprint workflow(s) resolves to a workflow that exists.")
        return 0

    print(f"G38 FAIL — {len(findings)} workflow reference(s) point at an id that does not exist "
          f"in the blueprint set:\n")
    for path, kind, node, target in findings:
        print(f"  {path}")
        print(f"      {kind} @ {node!r} -> {target!r}  (no blueprint file declares this id)")
    print(
        "\n  A dangling errorWorkflow is SILENT: n8n logs 'Could not find workflow \"<id>\"' and\n"
        "  creates zero execution rows — no red run, nothing in the UI. A dangling executeWorkflow\n"
        "  target fails loud on every call instead, but both mean the id in the blueprint is wrong.\n"
        "  Point it at a real workflow's `id` (see the file's own top-level \"id\" field), or clear\n"
        "  the field if no error handler is intended."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
