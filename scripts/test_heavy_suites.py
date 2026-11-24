#!/usr/bin/env python3
"""test_heavy_suites.py — the heavy-work slot's three shell suites, run where G72 runs tests (DGO-1797).

    python3 scripts/test_heavy_suites.py

G72 (plane-tests-lint) runs `scripts/test_*.py` and never the shell suites beside them, so the office's ONE heavy-job
slot was proven by suites that ran nowhere but by hand: test_heavy_slot.sh (heavy_admit, lib.sh), test_heavy_ready.sh
(the readiness rule) and test_heavy_hold.sh (the holder a CI job keeps it with — found by its second reader). This
runs the three. They need Linux's flock and setsid and bash 4: elsewhere it says NOT RUN and fails, as a test that
cannot run must. Each suite works in its own temp directory; none touches this checkout's data/.locks.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ("test_heavy_slot.sh", "test_heavy_ready.sh", "test_heavy_hold.sh")

need = [t for t in ("bash", "flock", "setsid", "timeout") if not shutil.which(t)]
bash4 = not need and subprocess.run(["bash", "-c", "[ \"${BASH_VERSINFO[0]}\" -ge 4 ]"]).returncode == 0
if need or not bash4 or not Path("/proc/self").is_dir():
    print(f"NOT RUN needs {', '.join(need) or ('bash 4' if not bash4 else '/proc')} (Linux, as the offices run)")
    sys.exit(1)

# ON THE CI, ONLY WHEN WHAT IT TESTS CHANGED SINCE THE LAST GREEN (scripts/ci/since_green.py; 36 s of G72's one
# `scripts/` worker on batches 114 and 115): the three suites, the lib.sh they source, the two ops scripts they run, and
# the thresholds heavy-ready.sh sources
SUBJECTS = ("scripts/test_heavy_suites.py", *(f"scripts/{s}" for s in SUITES), "scripts/lib.sh",
            "scripts/ops/heavy-ready.sh", "scripts/ops/heavy-hold.sh", "scripts/ops/admission-thresholds.sh")
_spec = importlib.util.spec_from_file_location("since_green", HERE / "ci" / "since_green.py")
since_green = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(since_green)
since_green.or_not_run(HERE.parent, SUBJECTS)

failed = []
for suite in SUITES:
    got = subprocess.run(["bash", str(HERE / suite)], capture_output=True, text=True, timeout=300)
    lines = (got.stdout + got.stderr).strip().splitlines()
    for line in lines:
        if line.startswith(("FAIL", "SKIP")):
            print(f"  {suite}: {line}")
    print(f"{'ok  ' if got.returncode == 0 else 'FAIL'} {suite}: {lines[-1] if lines else '(no output)'}")
    if got.returncode != 0 or any(line.startswith("SKIP") for line in lines):
        failed.append(suite)
print("heavy suites: " + ("PASS" if not failed else f"{len(failed)} FAILED: {', '.join(failed)}"))
sys.exit(1 if failed else 0)
