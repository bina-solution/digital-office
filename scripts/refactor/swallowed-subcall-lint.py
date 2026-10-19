#!/usr/bin/env python3
"""swallowed-subcall-lint — gate G53: a sub-workflow failure turned into data must be READ.

    python3 scripts/refactor/swallowed-subcall-lint.py [--self-test]

WHY THIS EXISTS. `onError: continueRegularOutput` on an `executeWorkflow` node is the exact
executeWorkflow analogue of the rule G48 enforces for replies: it converts a FAILURE into ordinary
data on the normal output. That is a legitimate and often necessary thing to do — but only if
somebody then looks. n8n puts the failure in `.error` / `.errorMessage` on the item and carries on;
if no node ever reads those fields, the failure has been deleted, and the workflow proceeds on an
item that looks like a result and is not one.

Measured across this repo's blueprints on 2026-08-06: **27 of 54** such nodes sit in workflows where
NO node anywhere reads `.error` or `.errorMessage`. Three are worth naming:

  * `errorHandler01` / `Call 'GlitchTip Error Reporter'` is TERMINAL and swallowing — so a failure of
    the error reporter is itself unreported. The component whose entire job is to make failures
    visible cannot report its own.
  * `indoxApiSupabase01` / `Process Changed Doc` is terminal: a document that fails processing
    disappears with no trace on the polling path that dispatched it.
  * `SyncScanner00001` / `Call Scan Unit` is terminal: same shape, on the scan path.

WHY THE RULE IS "DECLARED AS READ BY X", NOT "MUST BE READ HERE". Observation can legitimately live
in the CALLER, one workflow up, and the honest example is in this same tree: `syncV3Main0001`'s
`Run Unit` swallows a unit failure locally and re-emits it through `Collect Result` into
`Main Result.results[]`, where `SyncApi0000000001`'s `Scan Result` reads `r.error || r.errorMessage`
per unit and reports `units_failed`. A gate demanding local observation would flag that correct code
and be wrong. So `ALLOWED` records WHO reads it — workflow and node — or, for a deliberate
fire-and-forget dispatch, why nobody needs to.

Same shape and same anti-rot rule as G34: an `ALLOWED` entry that matches nothing FAILS, so a
declaration cannot outlive the call it excused.

SHIPPED KNOWN-FAILING, deliberately and with only the entries I could justify from evidence. The
remaining findings are real and each needs its owner's verdict — "is this dispatch fire-and-forget on
purpose, or is it a failure nobody has ever seen?" — and inventing 27 reasons to make a gate green on
its first run would be precisely the false-clean this gate exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
#: WHERE BLUEPRINTS LIVE — one glob, and it is the app glob. core-001 phase 2 (2026-10-10) moved the
#: central blueprint out of the core to `apps/n8n/blueprint/n8n/`, which is the same `apps/<id>/
#: blueprint/n8n/` every app uses, so the ONE pattern below covers both the apps and the centre. The
#: old `platform-base/n8n/workflows/` pattern was kept for a checkout that predates the move and is
#: gone now: a gate whose glob matches nothing says PASS, and two patterns invite exactly that rot.
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

#: reading the failure n8n parked on the item. `.error` / `.errorMessage`, in code or an expression.
ERR_READ = re.compile(r"\.(?:error|errorMessage)\b|\[[\"'](?:error|errorMessage)[\"']\]")

#: (workflow file, node name, who reads the failure / why nobody has to).
#: The G34 contract: a declaration is a claim that a human looked, naming something checkable.
ALLOWED: list[tuple[str, str, str]] = [
    # THE ANTI-ROT RULE EARNED ITS KEEP HERE (2026-10-09): all five entries written on 2026-08-06
    # named nodes that no longer exist — 'Run Unit', 'Renew Lock', 'Unlock (Done)' and 'Continue
    # Pass' in a workflow whose lock and pass paths were reshaped since, and 'Deliver Each' in a
    # file (`syncV3Unit0001.workflow.ts`) that is not in the tree at all. Two of the five were
    # re-pointed at the node the call lives in NOW and carry their reason with them; the other three
    # had no call left to excuse and are gone. A declaration that outlives its call is not a
    # declaration, it is an exemption.
    ("apps/indox/blueprint/n8n/syncV3Main0001.workflow.ts", "Run Each",
     "READ BY SyncApi0000000001 / 'Scan Result': the unit's item (error and all) is re-emitted by "
     "'Collect Result' into 'Main Result'.results[], and Scan Result filters "
     "`r.error || r.errorMessage` to compute units_failed and set ok:false. Observation lives one "
     "workflow up, which is why this gate asks WHO reads it rather than demanding it be local. "
     "(Declared as 'Run Unit' until 2026-10-09, when the anti-rot rule said the node had been "
     "renamed.)"),
    ("apps/indox/blueprint/n8n/syncV3Main0001.workflow.ts", "Unlock",
     "Failing to unlock must never throw the pass into its errorWorkflow — it falls through to "
     "Redis's own TTL expiry instead, which is the same recovery a hard crash gets. Stated in the "
     "node's own notes and in 'Lock Note'. (Declared as 'Unlock (Done)' until 2026-10-09.)"),
]


def swallowing_subcalls(doc: dict) -> list[tuple[str, bool, list[str]]]:
    """(node name, alwaysOutputData, downstream nodes) for each swallowing executeWorkflow node."""
    out = []
    conns = doc.get("connections") or {}
    for n in doc.get("nodes") or []:
        if n.get("type") != "n8n-nodes-base.executeWorkflow":
            continue
        if n.get("onError") != "continueRegularOutput":
            continue
        branches = (conns.get(n.get("name"), {}) or {}).get("main") or []
        downstream = [c["node"] for br in branches for c in br]
        out.append((str(n.get("name") or "?"), bool(n.get("alwaysOutputData")), downstream))
    return out


def reads_failure(doc: dict) -> bool:
    """Does ANY node in this workflow read `.error` / `.errorMessage` off an item?"""
    blob = " ".join(json.dumps(n.get("parameters") or {}, ensure_ascii=False)
                    for n in doc.get("nodes") or [])
    return bool(ERR_READ.search(blob))


SELF_TEST = [
    ("a swallowing sub-call in a workflow that never reads .error: must catch", 1, False,
     {"nodes": [{"name": "Call X", "type": "n8n-nodes-base.executeWorkflow",
                 "onError": "continueRegularOutput", "parameters": {}}],
      "connections": {}}),
    ("the same workflow once something reads .error: must allow", 1, True,
     {"nodes": [{"name": "Call X", "type": "n8n-nodes-base.executeWorkflow",
                 "onError": "continueRegularOutput", "parameters": {}},
                {"name": "Check", "type": "n8n-nodes-base.code",
                 "parameters": {"jsCode": "if($json.error) throw new Error($json.error);"}}],
      "connections": {}}),
    ("bracket access counts as reading it too", 1, True,
     {"nodes": [{"name": "Call X", "type": "n8n-nodes-base.executeWorkflow",
                 "onError": "continueRegularOutput", "parameters": {}},
                {"name": "Check", "type": "n8n-nodes-base.code",
                 "parameters": {"jsCode": "const e = top['errorMessage'];"}}],
      "connections": {}}),
    ("a sub-call that STOPS on error is out of scope — the failure is already loud", 0, False,
     {"nodes": [{"name": "Call X", "type": "n8n-nodes-base.executeWorkflow", "parameters": {}}],
      "connections": {}}),
    ("continueErrorOutput routes failures down a second branch, also loud: out of scope", 0, False,
     {"nodes": [{"name": "Call X", "type": "n8n-nodes-base.executeWorkflow",
                 "onError": "continueErrorOutput", "parameters": {}}],
      "connections": {}}),
    ("a non-executeWorkflow node is out of scope", 0, False,
     {"nodes": [{"name": "HTTP", "type": "n8n-nodes-base.httpRequest",
                 "onError": "continueRegularOutput", "parameters": {}}],
      "connections": {}}),
]


def self_test() -> int:
    bad = 0
    for label, n_calls, want_read, doc in SELF_TEST:
        got_calls = len(swallowing_subcalls(doc))
        got_read = reads_failure(doc)
        ok = got_calls == n_calls and got_read == want_read
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] calls={got_calls} (want {n_calls}), "
              f"reads_error={got_read} (want {want_read}): {label}")
    print(f"\nG53 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    allowed = {(f, n) for f, n, _ in ALLOWED}
    hits: set[tuple[str, str]] = set()
    findings: list[tuple[str, str, bool, list[str]]] = []
    checked = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(path)
            except (OSError, ValueError):
                continue
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            observed_here = reads_failure(doc)
            for name, always, downstream in swallowing_subcalls(doc):
                checked += 1
                if (rel, name) in allowed:
                    hits.add((rel, name))
                    continue
                if observed_here:
                    continue
                findings.append((rel, name, always, downstream))

    stale = [(f, n, why) for f, n, why in ALLOWED if (f, n) not in hits]

    if not findings and not stale:
        print(f"G53 PASS — {checked} swallowing sub-call(s); every failure is read by somebody, and "
              f"every one of the {len(ALLOWED)} declarations still matches.")
        return 0

    print("G53 FAIL")
    if findings:
        print(f"\n  {len(findings)} sub-call(s) whose failure becomes ordinary data that nothing "
              f"reads:")
        for rel, name, always, downstream in sorted(findings):
            where = " -> ".join(downstream) if downstream else "<TERMINAL — the failure is the reply>"
            print(f"    {rel}  ::  {name!r}  (alwaysOutputData={always})")
            print(f"        downstream: {where}")
    if stale:
        print(f"\n  {len(stale)} ALLOWED entry(ies) match nothing — the call moved or stopped "
              f"swallowing, so the exemption is now blanket:")
        for rel, name, _why in stale:
            print(f"    {rel}  ::  {name!r}")
    if findings:
        print(
            "\n  Either READ the failure (`$json.error || $json.errorMessage`) and report it, or add\n"
            "  the call to ALLOWED naming WHO reads it — a caller one workflow up counts, and is the\n"
            "  common correct answer here. `onError: continueRegularOutput` is not wrong; unobserved\n"
            "  is. A sub-call whose failure nobody reads has had its failure deleted, and the\n"
            "  workflow then proceeds on an item that looks like a result and is not one."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
