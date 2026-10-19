#!/usr/bin/env python3
"""G65 node-coverage-gate — how much of the n8n estate the suites actually execute.

WHY THIS IS NOT IN gates.sh. Every other gate is static: it reads the tree and answers without a
stack. This one counts EXECUTIONS, so it is only meaningful after the suites have run — in P0b it
would read zero and either fail every run or, worse, pass vacuously. It runs as a baseline phase
after P5, which is where the fact it measures comes into existence.

TWO FAILURES, and the first matters more than the number:

  1. AN EMPTY SCAN IS A RED, NEVER A PASS. scripts/n8n-node-coverage.py globbed `*.json` under the
     blueprint roots long after blueprints became .workflow.ts, matched nothing, and reported "no
     workflow files found" — which is why "279/624 = 44.7%" was carried around this repo as a live
     figure for weeks. It was JSON-era data nothing could reproduce, and every attempt to
     reproduce it errored rather than returning a smaller number. A measurement over zero inputs
     is not a low score; it is no score.

  2. A RATCHET, not a target. The floor lives in scripts/ci/node-coverage-floor.json and may only
     be raised. Coverage that drops means a suite stopped exercising something it used to, which
     is exactly the regression a coverage number is for; a fixed high target would instead sit red
     for months and be ignored.

Non-goal: 100% is not the aim and would be dishonest — 25 workflows execute zero nodes today, and
some of them (the JQExV3 Run* family, Gmail Actions Scanner, DocumentUploader) are candidates for
legacy/ rather than for new tests. The tool prints that list; this gate reports the count so the
choice stays visible instead of being absorbed into a percentage.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "n8n-node-coverage.py"
FLOOR = ROOT / "scripts" / "ci" / "node-coverage-floor.json"
APP = os.environ.get("COVERAGE_APP", "indox")


def measure() -> dict:
    r = subprocess.run([sys.executable, str(TOOL), "--app", APP, "--json"],
                       capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit("G65 FAIL — the coverage tool could not run:\n  "
                         + (r.stderr or r.stdout).strip()[:400])
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise SystemExit("G65 FAIL — the coverage tool returned no JSON:\n  "
                         + (r.stdout or r.stderr).strip()[:400])


def main() -> int:
    if not TOOL.exists():
        print("G65 FAIL — %s is missing" % TOOL.relative_to(ROOT))
        return 1
    data = measure()
    per = (data.get("per_app") or {}).get(APP) or {}
    nodes = int(per.get("nodes") or 0)
    ran = int(per.get("ran") or 0)
    wf = int(per.get("wf") or 0)
    wf_ran = int(per.get("wf_ran") or 0)
    dead = per.get("dead_wf") or []

    if wf == 0 or nodes == 0:
        print("G65 FAIL — scanned ZERO workflows/nodes for app %r." % APP)
        print("  A coverage number over no inputs is not a low score, it is no score. Check the")
        print("  blueprint globs in scripts/n8n-node-coverage.py before reading any percentage.")
        return 1

    pct = 100.0 * ran / nodes
    floor = 0.0
    if FLOOR.exists():
        try:
            floor = float(json.loads(io.open(FLOOR, encoding="utf-8").read()).get(APP, 0.0))
        except (ValueError, OSError):
            floor = 0.0

    line = ("%d/%d nodes executed (%.1f%%) across %d workflow(s); %d/%d workflows ran; "
            "%d executed nothing" % (ran, nodes, pct, wf, wf_ran, wf, len(dead)))

    if pct + 0.05 < floor:
        print("G65 FAIL — coverage %.1f%% is BELOW the recorded floor %.1f%%." % (pct, floor))
        print("  " + line)
        print("  A drop means a suite stopped exercising something it used to. Find what stopped")
        print("  running rather than lowering the floor: the floor may only be raised.")
        return 1

    print("G65 PASS — " + line)
    print("  floor %.1f%%%s" % (floor, "" if pct < floor + 0.5 else
                                "  → raise it to %.1f in %s" % (pct, FLOOR.relative_to(ROOT))))
    if dead:
        print("  %d workflow(s) executed no node at all — legacy/ candidates, listed by "
              "`python3 scripts/n8n-node-coverage.py --app %s`" % (len(dead), APP))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
