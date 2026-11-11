#!/usr/bin/env python3
"""test_ccr_pull.py — runs scripts/test_ccr_pull.sh, so that G72 (plane-tests-lint), which runs `scripts/test_*.py`,
runs it on every change (DGO-1017). The shell suite needs neither flock nor bash 4: macOS's bash 3.2 runs it."""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.exit(subprocess.run(["bash", str(HERE / "test_ccr_pull.sh")]).returncode)
