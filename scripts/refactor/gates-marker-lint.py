#!/usr/bin/env python3
"""gates-marker-lint — gate G101: the gates' own trigger cannot be fired by prose, or missed.

    python3 scripts/refactor/gates-marker-lint.py

WHY (DGO-1619). `gates-hosted.yml` asked `contains(github.event.head_commit.message, '[gates]')` — a
substring — so a commit that merely QUOTED the marker started a full gates run on the office's one
runner (7bb4397b, 2026-11-09), behind which a released batch's gates were already waiting. The marker
is a git TRAILER now, parsed by `scripts/ci/gates-asked`, with the old `[gates]` ending a subject
accepted for one release — on dgo-stable and, staged with a warning, on an office branch (DGO-1619
closes the window).

THE TWO FAILURES THIS GATE KEEPS APART, because they pull in opposite directions:
  * a marker a QUOTATION can fire — prose, a fenced code block, a nested `[gates]` in a subject;
  * a marker a SIGN-OFF can hide — `Gates: run` in its own paragraph with a blank line and a
    `Co-Authored-By:` under it. `git interpret-trailers` reads only the LAST trailer block, so that
    shape (the shape every commit here has) would have lost the request while looking correct.

It runs `scripts/ci/gates-asked` on real messages, asserts all of them, and asserts that neither
workflow still contains the substring test. ~1 second, no network, no stack.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = "G101"
SCRIPT = REPO / "scripts" / "ci" / "gates-asked"

#: (label, branch, message, expected)
CASES = [
    ("a plain trailer asks", "mac-dgo", "subject\n\nGates: run\n", "true"),
    ("a trailer above its sign-offs asks", "mac-dgo",
     "subject\n\nGates: run\n\nCo-Authored-By: X <x@y>\n", "true"),
    ("a trailer with sign-offs and no blank line asks", "mac-dgo",
     "subject\n\nGates: run\nSigned-off-by: X <x@y>\n", "true"),
    ("a message that is only the trailer asks", "mac-dgo", "Gates: run\n", "true"),
    ("Gates: no does not ask", "mac-dgo", "subject\n\nGates: no\n\nCo-Authored-By: X <x@y>\n", "false"),
    ("Gates: Run is not the marker (it is a value, not prose to be guessed)", "mac-dgo",
     "subject\n\nGates: Run\n", "false"),
    ("Gates:Run without a space is not a trailer", "mac-dgo", "subject\n\nGates:Run\n", "false"),
    ("Gates: true is not 'run'", "mac-dgo", "subject\n\nGates: true\n", "false"),
    ("the line quoted inside prose does not ask", "mac-dgo",
     "subject\n\nThe workflow asks for\n\nGates: run\n\nwhen you want it.\n", "false"),
    ("the line inside a fenced block does not ask", "mac-dgo",
     "docs: the marker\n\n```\nGates: run\n```\n", "false"),
    ("a stray non-trailer line in the final block breaks it", "mac-dgo",
     "subject\n\nGates: run\n[gates]\n", "false"),
    ("the old marker ending a subject asks on dgo-stable (one release)", "dgo-stable",
     "batch 30 asks for its gates run [gates]\n", "true"),
    ("the old marker NOT ending a subject asks nothing, even on dgo-stable", "dgo-stable",
     "plans: we quote [gates] in the middle of a subject and it must not fire\n", "false"),
    # staged, not yet refused (AGENTS.md rule 8): six lanes still end their subjects with it on mac-dgo
    ("the old marker ending a subject still asks on an office branch, for one release", "mac-dgo",
     "batch 30 asks for its gates run [gates]\n", "true"),
    ("a quotation of the old marker asks nothing", "mac-dgo",
     "plans: herd-406 — a quoted [gates] in this sentence must not fire\n", "false"),
]


def main() -> int:
    findings: list[str] = []
    if not SCRIPT.exists():
        print(f"{GATE} FAIL — {SCRIPT.relative_to(REPO)} is gone; the workflows call it")
        return 1
    for label, branch, message, want in CASES:
        got = subprocess.run(["bash", str(SCRIPT), "--branch", branch], input=message,
                             capture_output=True, text=True).stdout.strip()
        if got != want:
            findings.append(f"gates-asked answered {got!r} where {want!r} was right: {label}")
    # THE DECISION MUST COME FROM THE SCRIPT, in one job, and no other job may decide on a substring.
    # A cheap substring PRE-FILTER is allowed — and only in `decide` — because it costs the runner a
    # checkout for nothing on every push to those two branches; it is not allowed to be the answer.
    host = REPO / ".github/workflows/gates-hosted.yml"
    doc = yaml.safe_load(host.read_text(encoding="utf-8")) or {}
    jobs = doc.get("jobs") or {}
    decide = json.dumps(jobs.get("decide") or {}, ensure_ascii=False)
    if "gates-asked" not in decide:
        findings.append("gates-hosted.yml: the `decide` job no longer asks scripts/ci/gates-asked")
    for name, job in jobs.items():
        cond = str((job or {}).get("if") or "")
        if "head_commit.message" in cond and name != "decide":
            findings.append(f"gates-hosted.yml: job '{name}' decides on a substring of the commit "
                            f"message — only `decide`, through gates-asked, may answer")
    gotest = (REPO / ".github/workflows/go-test.yml").read_text(encoding="utf-8")
    if "head_commit.message" in gotest:
        findings.append("go-test.yml reads the commit message — its trigger must be paths, not prose")
    if findings:
        print(f"{GATE} FAIL — {len(findings)} finding(s):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print(f"{GATE} PASS — the marker asks when it must and stays quiet when it must "
          f"({len(CASES)} shapes), the answer comes from gates-asked in `decide` alone, and no other "
          f"job decides on a substring")
    return 0


if __name__ == "__main__":
    sys.exit(main())
