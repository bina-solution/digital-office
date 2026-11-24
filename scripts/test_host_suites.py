#!/usr/bin/env python3
"""test_host_suites.py — the host tools' shell suites, run where G72 runs tests (DGO-2123).

    python3 scripts/test_host_suites.py

G72 (plane-tests-lint) runs `scripts/test_*.py`, never the shell suites beside them, and these three ran nowhere but
by hand (issues/the-shell-test-suites-of-scripts-run-in-no-ci-lane-the-takes-own-test-included.yaml):
  * test_as_host_root.sh — scripts/as-host-root.sh, root on this host with the access the office has (DGO-1848);
    `sudo`, `docker`, `nsenter` and the rest are stand-ins on a CLOSED PATH, never the machine's own;
  * test_client_apps.sh — scripts/client-apps.sh, on a throwaway checkout and a local «private» repository (DGO-1819);
  * test_host_power.sh — scripts/host-power.sh, against a folder shaped like a laptop's /sys and /etc (DGO-1750).
Each works in a temp directory of its own and needs bash, git and tar alone: no root, no engine, no network. Measured
on the Mac on 2026-11-20 (bash 3.2): 20, 39 and 30 checks, in 16, 7 and 1 s.

The other shell suites of scripts/ have runners already: test_bbox_run_contract.py, test_ccr_pull.py and
test_heavy_suites.py run six of them, and test_follow_suite.py runs test_follow.sh. test_bbox_plane_lock.sh is the
Mac's own: it tests the Mac hand-off's BSD lockf and says SKIP anywhere else.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ("test_as_host_root.sh", "test_client_apps.sh", "test_host_power.sh")

need = [t for t in ("bash", "git", "tar") if not shutil.which(t)]
if need:
    print(f"NOT RUN needs {', '.join(need)}")
    sys.exit(1)

failed = []
for suite in SUITES:
    began = time.monotonic()
    got = subprocess.run(["bash", str(HERE / suite)], capture_output=True, text=True, timeout=300)
    took = time.monotonic() - began
    lines = (got.stdout + got.stderr).strip().splitlines()
    for line in lines:
        if line.startswith(("FAIL", "SKIP")):
            print(f"  {suite}: {line}")
    print(f"{'ok  ' if got.returncode == 0 else 'FAIL'} {suite}: {lines[-1] if lines else '(no output)'} ({took:.0f} s)")
    if got.returncode != 0 or any(line.startswith("SKIP") for line in lines):
        failed.append(suite)
print("host suites: " + ("PASS" if not failed else f"{len(failed)} FAILED: {', '.join(failed)}"))
sys.exit(1 if failed else 0)
