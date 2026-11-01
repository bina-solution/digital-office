#!/usr/bin/env python3
"""
run_all.py — run every per-app E2E suite in this directory in sequence, print one combined
scorecard, and exit non-zero if any suite failed. Each suite is also independently runnable
(`python3 scripts/ui-coverage/e2e/test_drive.py`) — this is just the one-command convenience.

    python3 scripts/ui-coverage/e2e/run_all.py             # all suites
    python3 scripts/ui-coverage/e2e/run_all.py drive mail   # named suites only

Always run scripts/ui-coverage/e2e/cleanup.py afterwards (pass/fail) to remove QA_E2E_-tagged
data. This runner does NOT clean up automatically, so a failed run's evidence stays inspectable
until you choose to clear it.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = {
    "drive": "test_drive.py",
    "mail": "test_mail.py",
    "indox": "test_indox.py",
    "indox-regressions": "test_indox_regressions.py",
    "indox-ui": "test_indox_ui.py",
}
ORDER = ["drive", "mail", "indox", "indox-regressions", "indox-ui"]


def main():
    wanted = [a for a in sys.argv[1:] if a in SUITES] or ORDER
    results = {}
    for name in wanted:
        print(f"\n{'=' * 70}\nRUNNING: {name}  ({SUITES[name]})\n{'=' * 70}", flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, str(HERE / SUITES[name])])
        results[name] = (r.returncode, round(time.time() - t0))

    print(f"\n{'=' * 70}\nSCORECARD\n{'=' * 70}")
    red = False
    for name in wanted:
        rc, secs = results[name]
        ok = rc == 0
        red = red or not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:<20} exit={rc}  {secs}s")
    print("\nRun scripts/ui-coverage/e2e/cleanup.py to remove QA_E2E_-tagged data.")
    sys.exit(1 if red else 0)


if __name__ == "__main__":
    main()
