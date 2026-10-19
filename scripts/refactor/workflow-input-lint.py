#!/usr/bin/env python3
"""workflow-input-lint — gate G19: a sub-workflow call must actually pass its inputs.

n8n's `executeWorkflow` node changed how `workflowInputs` mappings are evaluated at typeVersion
1.2. A node still on 1.1 that supplies a **literal** value silently sends `null` for *every* field —
not just the literal one. Nothing errors. The sub-workflow runs, matches no op, returns nothing, and
the caller carries on.

That is exactly what the `Mail Label Engine` did:

    Sub Search  (typeVersion 1.1)   op: "search",  params: "={{ ({query: $json.query, …}) }}"
      -> gmail api received          {"op": null, "params": null}
      -> matched no branch, returned nothing
      -> the engine stopped and labelled nothing, and reported success

The whole mail-organiser subsystem did nothing for an unknown length of time and every surrounding
check stayed green, because the only lane that appends UNLABELLED mail — the one thing that can
prove labelling happens at all — is a gate that had never been run.

Two things make this worth a permanent lint rather than a one-off fix. The failure is *silent*, and
the fix is *invisible in a diff review*: `typeVersion` is a field nobody reads, and the mapping
beside it looks perfectly correct.

Exit 1 if any executeWorkflow node below typeVersion 1.2 passes a literal (non-expression) input.

IT READ NOTHING FOR SEVEN WEEKS. It globbed `*.json` in the blueprint directories, which have held
only `.workflow.ts` since 2026-08-16, and reported "every sub-workflow call passes its inputs
(0 executeWorkflow node(s))" on every run — the sentence two paragraphs up, said by this gate
about itself. It also asked the compiler which blueprint directories this OFFICE has enabled, so
even reading, an office without INDOX would never have looked at INDOX's 200-odd calls. It reads
every shipped blueprint through the one reader now (296 nodes on 2026-10-07, all passing), and a
run that reads none is a failure.
"""
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
MIN_VERSION = 1.2
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402


def main():
    bad, checked, read = [], 0, 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                wf = load_blueprint(str(path))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {os.path.relpath(path, REPO)}: {e}")
                continue
            read += 1
            for node in wf.get("nodes", []):
                if not node.get("type", "").endswith("executeWorkflow"):
                    continue
                checked += 1
                try:
                    version = float(node.get("typeVersion") or 0)
                except (TypeError, ValueError):
                    version = 0.0
                values = ((node.get("parameters") or {}).get("workflowInputs") or {}).get("value") or {}
                literals = [k for k, v in values.items()
                            if isinstance(v, str) and not v.startswith("=")]
                if version < MIN_VERSION and literals:
                    bad.append((wf.get("name") or "?", node.get("name") or "?", version,
                                literals, os.path.relpath(path, REPO)))

    if not read:
        print("G19 FAIL — read ZERO blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    if bad:
        print("SUB-WORKFLOW CALLS THAT SILENTLY PASS null")
        print("-" * 78)
        for wf, node, version, literals, path in bad:
            print(f"  {wf[:36]:38} node {node!r}")
            print(f"  {'':38} typeVersion={version} with literal input(s) {literals}")
            print(f"  {'':38} {path}")
        print("-" * 78)
        print(f"  -> set typeVersion to {MIN_VERSION} on that node. Below it, a literal input makes\n"
              f"     n8n send null for EVERY field, the sub-workflow matches nothing, and the call\n"
              f"     succeeds having done nothing.")
        print(f"\nG19 FAIL — {len(bad)} sub-workflow call(s) would pass null.")
        return 1

    print(f"G19 PASS — every sub-workflow call passes its inputs "
          f"({checked} executeWorkflow node(s) in {read} blueprint(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
