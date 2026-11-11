#!/usr/bin/env python3
"""blueprint-tmp-test — gate G100: a killed gate run does not leave its extraction dir behind.

    python3 scripts/refactor/blueprint-tmp-test.py

WHY. `n8n_blueprint.load()` extracts a `.workflow.ts` into a `n8n-bp-*` dir under the temp directory
and removes it at exit. `atexit` does not run when a process is KILLED — and every gate that reads a
blueprint runs under a timeout, so the runs that die are exactly the runs that leave dirs behind.
Measured on the HP 2026-11-09 (DGO-1393): 129 dirs, 171 MB in all (~1.3 MB each), abandoned since
05:05 the same day while the office's C: sat at 95%. Nothing was wrong with the office; a temp dir
had simply stopped being temporary.

THE TEST. It plants two dirs of the module's OWN prefix — one dated past the module's own cutoff, one fresh — imports
the module and asserts the stale one is gone and the fresh one is not. **On the pre-fix code this
fails**: the import sweeps nothing, so the 8-hour-old dir is still there. That is why it is a gate and
not a comment: a sweep is only a fix if a run proves it happens.

WHAT IT TOUCHES. The import it performs sweeps every `n8n-bp-*` dir older than the module's cutoff
(12 hours) — that IS the behaviour under test, so it is stated here rather than denied. Its own two
fixtures are dated past the cutoff and now, so the test cannot pass by sweeping the very dir it needs to
find, and both are removed either way.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = "G100"


def module_cutoff_hours(src: pathlib.Path) -> float:
    """The module's own stale cutoff — the fixture must be older than it, or the test is a lie."""
    m = re.search(r"^STALE_AFTER_HOURS\s*=\s*([\d.]+)", src.read_text(encoding="utf-8"), re.M)
    return float(m.group(1)) if m else 12.0


def module_prefix(src: pathlib.Path) -> str | None:
    """The temp dir prefix the module actually uses — read from its code, so a rename cannot leave
    this test planting dirs the sweep does not recognise while the gate stays green."""
    m = re.search(r'mkdtemp\(\s*prefix\s*=\s*["\']([^"\']+)["\']', src.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def main() -> int:
    src = REPO / "scripts" / "refactor" / "n8n_blueprint.py"
    prefix = module_prefix(src)
    if not prefix:
        print(f"{GATE} FAIL — n8n_blueprint.py no longer names a mkdtemp prefix; this test cannot "
              f"know which dirs are its own")
        return 1
    tmp = pathlib.Path(tempfile.gettempdir())
    stale = tmp / (prefix + "staletest%d" % os.getpid())
    fresh = tmp / (prefix + "freshtest%d" % os.getpid())
    for d in (stale, fresh):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        (d / "one.json").write_text("{}", encoding="utf-8")
    # older than the module's own cutoff, so "stale" means what the module means by it
    old = time.time() - (module_cutoff_hours(src) + 2) * 3600
    os.utime(stale, (old, old))
    try:
        spec = importlib.util.spec_from_file_location("n8n_blueprint_for_g100", src)
        mod = importlib.util.module_from_spec(spec)
        # Importing runs the sweep — that is what this gate measures.
        spec.loader.exec_module(mod)
        failures = []
        if stale.exists():
            failures.append(f"the {int(module_cutoff_hours(src) + 2)}-hour-old {prefix}dir survived the import: {stale.name} — a killed "
                            f"run's extraction dir is still on the disk (the pre-fix behaviour)")
        if not fresh.exists():
            failures.append(f"the FRESH dir was deleted: {fresh.name} — a running gate's own "
                            f"extraction dir must never be swept")
        if not callable(getattr(mod, "prune_stale", None)):
            failures.append("n8n_blueprint has no prune_stale() — nothing to call, nothing swept")
        if failures:
            print(f"{GATE} FAIL — {len(failures)} finding(s):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(f"{GATE} PASS — the stale {prefix} dir was swept at import, the fresh one was kept")
        return 0
    finally:
        for d in (stale, fresh):
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
