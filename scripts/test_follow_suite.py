#!/usr/bin/env python3
"""test_follow_suite.py — the take's own suite, run where G72 runs tests (DGO-2123).

    python3 scripts/test_follow_suite.py

scripts/test_follow.sh holds the take of every office: follow.sh takes only a green version, keeps it only while the
office stays healthy, never loses an office's own changes, and pulls a ready-made image only where it is the office's
own build. Its 225 checks ran nowhere but by hand: G72 (plane-tests-lint) runs `scripts/test_*.py`, never the shell
suites beside them. On 2026-11-20 they were run twice on a vps1 probe, and once, against the owner's rule of 11-10,
on the Dell's host (issues/the-shell-test-suites-of-scripts-run-in-no-ci-lane-the-takes-own-test-included.yaml).

The suite needs Linux's flock and timeout, and bash 4: elsewhere this says NOT RUN and fails, as a test that cannot
run must. It works in its own temp directory and plays every outside dependency of follow.sh by a stub: no engine, no
office, no network.

WHERE THE CI RUNS IT (GITHUB_ACTIONS), ONLY WHEN WHAT IT TESTS CHANGED SINCE THE LAST GREEN. That is follow.sh, the
lib.sh it sources, checkout-owner.sh, the suite and this file. The suite takes about 5 minutes of the proof's one runner
(2 cores), and 9 of the line's 25 batches on 2026-11-20 changed one of them. Otherwise it says NOT RUN, naming the green
it measured from (gates-hosted.yml fetches refs/green/dgo-stable beside the checkout). It is the last GREEN, never the
commit before: a red batch that broke the take, then one that leaves the take alone, would turn green with the take
untested. With no green to measure from, it runs. Run by hand, it always runs. The rule is scripts/ci/since_green.py's,
shared with the other suites that test one part of the tree.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = "test_follow.sh"
SUBJECTS = ("scripts/follow.sh", "scripts/lib.sh", "scripts/checkout-owner.sh", "scripts/test_follow.sh",
            "scripts/test_follow_suite.py")

need = [t for t in ("bash", "git", "flock", "timeout") if not shutil.which(t)]
bash4 = not need and subprocess.run(["bash", "-c", "[ \"${BASH_VERSINFO[0]}\" -ge 4 ]"]).returncode == 0
if need or not bash4 or not Path("/proc/self").is_dir():
    print(f"NOT RUN needs {', '.join(need) or ('bash 4' if not bash4 else '/proc')} (Linux, as the offices run)")
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("since_green", HERE / "ci" / "since_green.py")
since_green = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(since_green)
since_green.or_not_run(HERE.parent, SUBJECTS)   # the rule above, one copy for every suite that asks it

began = time.monotonic()
got = subprocess.run(["bash", str(HERE / SUITE)], capture_output=True, text=True, timeout=840)
took = time.monotonic() - began
lines = (got.stdout + got.stderr).strip().splitlines()
passed = sum(1 for line in lines if line.startswith("PASS"))
failed = [line for line in lines if line.startswith("FAIL")]
for line in failed:
    print(f"  {SUITE}: {line}")
ok = got.returncode == 0 and not failed and passed > 0
print(f"{'PASS' if ok else 'FAIL'} {SUITE}: {passed} check(s) passed, {len(failed)} failed, exit {got.returncode}, "
      f"{took:.0f} s")
sys.exit(0 if ok else 1)
