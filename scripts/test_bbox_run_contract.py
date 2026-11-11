#!/usr/bin/env python3
"""test_bbox_run_contract.py — how `bbox run` ends and what `bbox apps disable` stops (DGO-995).

Runs the two bash tests that read the real functions out of bbox and scripts/lib.sh:
    scripts/test_bbox_run_verdict.sh   «up.» / «up, with problems» / «NOT up» exit 3, the old contract, targeted runs,
                                       and the item's four call sites pinned as fatal
    scripts/test_stop_off_apps.sh      a switched-off app's containers stopped in THIS compose project, never one an
                                       enabled app requires; the project named by compose when lib.sh leaves it empty
They are bash; this file is what the gates find (G72 reads scripts/test_*.py). Needs bash and nothing else.
"""
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    if not shutil.which("bash"):
        print("NOT RUN no bash on this machine (the two tests are bash)")   # G72 reads this line as NOT RUN
        return 1
    bad = 0
    for name in ("test_bbox_run_verdict.sh", "test_stop_off_apps.sh"):
        r = subprocess.run(["bash", str(HERE / name)], capture_output=True, text=True, timeout=120)
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            bad += 1
            print(f"FAIL  {name} exited {r.returncode}")
            sys.stdout.write(r.stderr[-2000:])
    print("test_bbox_run_contract: " + ("ok" if not bad else f"{bad} of 2 FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
