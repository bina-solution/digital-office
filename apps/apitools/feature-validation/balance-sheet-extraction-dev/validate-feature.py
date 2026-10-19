#!/usr/bin/env python3
"""balance-sheet-extraction-dev — the dev SCENARIO, run by the implementation next door.

This file was a SYMLINK to ../balance-sheet-extraction/validate-feature.py. Git checks a symlink
out as a plain TEXT FILE wherever `core.symlinks` is off (every Windows clone), so on those
machines this `.py` file's entire content was the string
`../balance-sheet-extraction/validate-feature.py` — a suite that could not run, and, the moment
this tree stopped being excluded from G12's parse sweep by living under `legacy/`, a Python file
that does not parse. Loading the sibling module explicitly is the same sharing, spelled identically
on every platform.

(`fixtures` beside this file is still a symlink to the parent suite's fixtures — a directory, which
has no portable in-file spelling. It is dereferenced inside the container, where the compose file
mounts BOTH suites, so the CI path is unaffected.)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "balance-sheet-extraction" / "validate-feature.py"


def load_shared():
    """Import ../balance-sheet-extraction/validate-feature.py as a module.

    A hyphen is not a legal module name, so this cannot be a plain `import`; and the shared file
    guards its entry point with `if __name__ == "__main__"`, so importing it runs nothing.
    """
    spec = importlib.util.spec_from_file_location("bs_extraction_validate_feature", SHARED)
    if spec is None or spec.loader is None:            # pragma: no cover - only if the file moved
        raise SystemExit(f"balance-sheet-extraction-dev: shared implementation not found: {SHARED}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    # HERE, not the shared file's own directory: the feature root selects scenario.json, the case
    # list and benchmarks/ — and that difference is the entire point of this suite.
    sys.exit(load_shared().run_feature(HERE))
