#!/usr/bin/env python3
"""Fetch this suite's fixtures — which are the parent suite's fixtures.

Was a SYMLINK to ../balance-sheet-extraction/download_fixtures.py; see the note in
validate-feature.py beside this file for why a symlinked `.py` cannot stay (it checks out as a
one-line text file wherever `core.symlinks` is off, i.e. every Windows clone).

Running the shared downloader with ITS OWN `__file__` is deliberate and is exactly what the symlink
did: `fixtures` here points at ../balance-sheet-extraction/fixtures, so both spellings download into
the one shared documents directory.
"""
import runpy
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent / "balance-sheet-extraction" / "download_fixtures.py"

if __name__ == "__main__":
    if not SHARED.is_file():                           # pragma: no cover - only if the file moved
        raise SystemExit(f"balance-sheet-extraction-dev: shared downloader not found: {SHARED}")
    sys.argv[0] = str(SHARED)
    runpy.run_path(str(SHARED), run_name="__main__")
