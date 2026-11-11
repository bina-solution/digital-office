#!/usr/bin/env python3
"""test_bbox_profile_fallback.py — a profile selector that FAILS does not end `bbox run` (DGO-605).

    python3 scripts/test_bbox_profile_fallback.py        (G72 runs it; bash and python3 only)

`ensure_perf_profile` (bbox) sizes an office that has no PERFORMANCE_PROFILE by asking
platform/manager/select-profile.py, and falls back to the floor profile when the selector gives nothing. Under
`set -euo pipefail` the call had no `|| true`, so a selector that EXITS non-zero (no PyYAML, a broken file)
ended `bbox run` on that line and the fallback never spoke. This lifts the function out of bbox as it is, runs
it in bash with the same options against a selector that fails, and holds: it says the fallback, writes the
floor profile and returns 0. On the code before the fix it exits non-zero with nothing said.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def function(src: str, name: str) -> str:
    m = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}\n", src, re.M | re.S)
    if not m:
        sys.exit(f"FAIL  bbox has no `{name}()` any more — this test reads the function it guards")
    return m.group(0)


def main() -> int:
    fn = function((REPO / "bbox").read_text(encoding="utf-8"), "ensure_perf_profile")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "platform" / "manager").mkdir(parents=True)
        (root / "platform" / "manager" / "select-profile.py").write_text("import sys\nsys.exit(1)\n")
        (root / "scripts").mkdir()
        (root / "scripts" / "perf-profile-apply").write_text("import sys\nsys.exit(0)\n")
        (root / ".env").write_text("DEPLOYMENT_NAME=t\n")
        script = "\n".join([
            "set -euo pipefail",
            f"REPO_ROOT='{root}'; SCRIPTS='{root}/scripts'; cy=''; c0=''",
            "say() { echo \"SAY: $*\"; }",
            "npath() { printf '%s' \"$1\"; }",
            "ncores() { echo 4; }",
            "bbox_clamp_cpus_to_host() { :; }",
            fn,
            "ensure_perf_profile",
            "echo REACHED-THE-END",
        ])
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        env = (root / ".env").read_text()
    ok = (r.returncode == 0 and "falling back to the floor profile" in r.stdout and "REACHED-THE-END" in r.stdout
          and "PERFORMANCE_PROFILE=ci-small" in env)
    print(("PASS  " if ok else "FAIL  ") + "a failing profile selector falls back to the floor profile and bbox goes on"
          + ("" if ok else f"\n        rc={r.returncode} stdout={r.stdout.strip()[-300:]!r} .env={env.strip()!r}"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
