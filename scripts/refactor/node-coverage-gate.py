#!/usr/bin/env python3
"""G103 node-coverage-gate — how much of the n8n estate the suites actually execute.

G103 since batch 30 (2026-11-09); it was G94 from 2026-11-03 and G65 before that, as did `cpu-budget-lint`, and GATES.md's G65 row
and ci-verify's G65 step name the CPU budget — so that one keeps the number. The `G<n>` prefix this
file prints is G103 as of the same day, so the number in the output and the number here agree;
`scripts/baseline.sh` strips whatever number it prints either way.

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

ALIGNED TO THE TOOL THAT IS THERE (2026-11-03). This gate called
`scripts/n8n-node-coverage.py --app indox --json` — two flags that tool never had. Its interface is
`--since-id` (REQUIRED), `--until-id`, `--min`, `--wf`, `--out`, and what it produces is a TEXT
report: a per-workflow table plus one `CORE TOTAL` line, no JSON. So argparse refused the call
before a single execution was counted, and the gate died with "the coverage tool could not run" on
every battery — a gate that measured nothing, reporting nothing, which is failure 1's own class one
layer out. It now passes a real window and parses the report the tool really prints.

WHAT IT MEASURES, AND WHAT IT REFUSES TO MEASURE. The tool's gated scope is its own CORE list — the
sync engine, the INDOX state machine, the extraction lanes — and the floor is keyed by the app those
suites belong to (`indox`). A CORE workflow that is not IN this instance's n8n is not "uncovered": it
is absent, so a percentage over the rest would be a different measurement wearing the same name (the
ratio's universe is 1987 nodes on the office that runs INDOX; five workflows and 108 nodes on an
office that does not). That case fails with the cause named — never a silent low score, never a pass.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "n8n-node-coverage.py"
FLOOR = ROOT / "scripts" / "ci" / "node-coverage-floor.json"
#: The floor's key: the app whose suites this estate exists for. The tool has no per-app scope any
#: more (its CORE list IS the INDOX/sync estate), so this names the floor row and the messages.
APP = os.environ.get("COVERAGE_APP", "indox")

#: THE WINDOW IS EXECUTION-ID FENCES, and an execution id means nothing outside the instance it came
#: from: vps1 held 1661500..1684897 on 2026-11-03 (N executions) and the HP's range is its own.
#: A literal id written here would therefore be right for exactly one office and silently wrong — or
#: silently empty — on the next one, so there is no literal here.
#:
#: Unset, the fence is 0: everything this instance still holds. That is a real window and not an
#: ever-sticky union, because the tool reads at most the newest 2000 executions per workflow. A lane
#: that wants "only what this battery just executed" passes the ids it saw, both of them real:
#:   COVERAGE_SINCE_ID=1684000 COVERAGE_UNTIL_ID=1684897 bbox baseline
SINCE_ID = int(os.environ.get("COVERAGE_SINCE_ID") or 0)
UNTIL_ID = os.environ.get("COVERAGE_UNTIL_ID") or None
SINCE_FROM_ENV = "COVERAGE_SINCE_ID" in os.environ

# `OK  syncV3Main0001  100.0%  17/17 nodes  (12 execs)` / `LOW …`; INFO rows open with "  -" and are
# the tool's informational scope, never gated. A workflow the instance does not run prints
# `<name>  MISSING from n8n`, with NO scope marker — so a missing row's scope cannot be read off the
# line, and the tool's own declaration is what says which of them the floor is about.
CORE_ROW = re.compile(r"^(?:OK |LOW) (\S+)\s+([\d.]+)%\s+(\d+)/(\d+)\s+nodes\s+\((\d+) execs")
MISSING_ROW = re.compile(r"^(\S+)\s+MISSING from n8n")
TOTAL_ROW = re.compile(r"^CORE TOTAL\s+([\d.]+)%\s+(\d+)/(\d+)\s+nodes")


def declared_core() -> set:
    """The tool's CORE list — the workflows it gates, read from the file itself, not retyped here.

    A hand-kept copy in this gate would be a second source of truth for exactly the list whose drift
    this gate exists to catch.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("n8n_node_coverage", str(TOOL))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return set(getattr(mod, "CORE", []) or [])


def window() -> str:
    """Said on every run: a coverage number without its fence is not a measurement."""
    if UNTIL_ID:
        return "execution ids %s..%s%s" % (SINCE_ID, UNTIL_ID,
                                           "" if SINCE_FROM_ENV else " (until from COVERAGE_UNTIL_ID)")
    if SINCE_FROM_ENV:
        return "execution ids >= %d (from COVERAGE_SINCE_ID)" % SINCE_ID
    return ("execution ids >= %d (everything this instance still holds; COVERAGE_SINCE_ID narrows it)"
            % SINCE_ID)


def measure() -> dict:
    """The tool's own report, parsed — its table is the contract, there is no --json to ask for."""
    # `--min 0` on purpose: the tool's own per-workflow bar is a SECOND, earlier-versioned bar
    # (default 80) and it also makes the tool exit 1, which this gate would have to read as "could
    # not run". The bar that matters is the ratchet below — the floor — so the tool is asked only to
    # measure and the gate compares. Nothing is loosened: 67.4 still fails at 67.3.
    args = [sys.executable, str(TOOL), "--since-id", str(SINCE_ID), "--min", "0"]
    if UNTIL_ID:
        args += ["--until-id", str(UNTIL_ID)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit("G103 FAIL — the coverage tool could not run:\n  "
                         + (r.stderr or r.stdout).strip()[:400])
    out = {"core": [], "missing": [], "ran": 0, "nodes": 0, "pct": 0.0}

    for line in (r.stdout or "").splitlines():
        m = CORE_ROW.match(line)
        if m:
            out["core"].append({"wf": m.group(1), "pct": float(m.group(2)),
                                "ran": int(m.group(3)), "nodes": int(m.group(4)),
                                "execs": int(m.group(5))})
            continue
        m = MISSING_ROW.match(line)
        if m:
            out["missing"].append(m.group(1))
            continue
        m = TOTAL_ROW.match(line)
        if m:
            out["pct"], out["ran"], out["nodes"] = float(m.group(1)), int(m.group(2)), int(m.group(3))

    # The tool's own CORE TOTAL is the answer when it printed one; the rows are the fallback, so a
    # change in the report's tail cannot silently turn the number into a zero.
    if not out["nodes"]:
        out["ran"] = sum(w["ran"] for w in out["core"])
        out["nodes"] = sum(w["nodes"] for w in out["core"])
        out["pct"] = (100.0 * out["ran"] / out["nodes"]) if out["nodes"] else 0.0
    return out


def floor_for(app: str) -> float:
    if not FLOOR.exists():
        return 0.0
    try:
        return float(json.loads(io.open(FLOOR, encoding="utf-8").read()).get(app, 0.0))
    except (ValueError, OSError):
        return 0.0


def main() -> int:
    if not TOOL.exists():
        print("G103 FAIL — %s is missing" % TOOL.relative_to(ROOT))
        return 1
    data = measure()
    core = data["core"]
    ran, nodes, pct = data["ran"], data["nodes"], data["pct"]
    dead = [w["wf"] for w in core if w["ran"] == 0]
    line = ("%d/%d nodes executed (%.1f%%) across %d workflow(s); %d/%d workflows ran; "
            "%d executed nothing" % (ran, nodes, pct, len(core),
                                     len([w for w in core if w["execs"]]), len(core), len(dead)))

    # An absent CORE workflow is a missing ESTATE, not a coverage gap: a percentage over the rest
    # would be computed over a different universe than the one the floor describes. INFO-scope
    # absences are the tool's own informational list and are reported, never gated. Asked FIRST,
    # because "the whole estate is absent" and "nothing was measured" are different facts and only
    # one of them sends the reader to the database.
    absent_core = [w for w in data["missing"] if w in declared_core()]
    absent_info = [w for w in data["missing"] if w not in declared_core()]
    if absent_core:
        print("G103 FAIL — %d of %d CORE workflow(s) are not in this instance's n8n, so the %r "
              "estate cannot be measured here." % (len(absent_core),
                                                   len(absent_core) + len(core), APP))
        if core:
            print("  measured over the %d that are: %s" % (len(core), line))
        print("  window: %s" % window())
        print("  absent: " + ", ".join(absent_core[:12])
              + (" … +%d more" % (len(absent_core) - 12) if len(absent_core) > 12 else ""))
        print("  The floor in %s describes the office that RUNS this estate; a ratio over a"
              % FLOOR.relative_to(ROOT))
        print("  subset of it is not that number, low or high. Run G103 there. On an office without")
        print("  the estate this gate is a deliberate red, not a silent green.")
        if absent_info:
            print("  (%d informational workflow(s) are absent too — reported, not gated.)"
                  % len(absent_info))
        return 1

    # No CORE number was produced at all — no row and no total.
    if not core or nodes == 0:
        print("G103 FAIL — scanned ZERO workflows/nodes for the %r estate." % APP)
        print("  window: %s" % window())
        print("  A coverage number over no inputs is not a low score, it is no score. Either nothing")
        print("  executed in this window, or the tool cannot reach the n8n database — it now says")
        print("  which one, on stderr above. Neither answer is a percentage to read.")
        return 1

    if absent_info:
        print("G103 note — %d informational workflow(s) are not in this instance's n8n (not gated): %s"
              % (len(absent_info), ", ".join(absent_info[:6])
                 + (" …" if len(absent_info) > 6 else "")))

    floor = floor_for(APP)
    if pct + 0.05 < floor:
        print("G103 FAIL — coverage %.1f%% is BELOW the recorded floor %.1f%%." % (pct, floor))
        print("  " + line)
        print("  window: %s" % window())
        print("  A drop means a suite stopped exercising something it used to. Find what stopped")
        print("  running rather than lowering the floor: the floor may only be raised.")
        return 1

    print("G103 PASS — " + line)
    print("  window: %s" % window())
    print("  floor %.1f%%%s" % (floor, "" if pct < floor + 0.5 else
                                "  → raise it to %.1f in %s" % (pct, FLOOR.relative_to(ROOT))))
    if dead:
        print("  %d workflow(s) executed no node at all — legacy/ candidates, listed by "
              "`python3 scripts/n8n-node-coverage.py --since-id %d`" % (len(dead), SINCE_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
