#!/usr/bin/env python3
"""app-standard-lint — gate G114: a cell of the app standard that was closed stays closed (DGO-1047).

    python3 scripts/refactor/app-standard-lint.py              # hold scripts/app-standard/inventory.json
    python3 scripts/refactor/app-standard-lint.py --self-test  # prove it can fail, on fixtures

WHY. scripts/app-standard/measure.py measures every app against the one standard (ui, api, cli, ops, share,
brief, gate — DGO-1039) and writes inventory.json; its `--check` refuses a cell the committed file has met and
the tree no longer does. Nothing ran it, so a «קבץ קדמה» round could close a cell and the next commit open it
again in silence (the inventory was found 15 apps stale on 2026-11-10). This gate runs it on every gate run.

WHAT IT RUNS. `measure.py --check --no-views`: the whole measure from source — the compiler's catalog, its
render of the console's tiles into a directory of this run, dgo-extend's publishable(), the operatives, the
hooks, GATES.md — with one reader left out: the UI map's VIEW counts, which need this office's compiled
`.generated/` (a fresh clone has none) and decide no cell. It prints how many apps it held, and every cell
closed since the committed file, which `measure.py` (no flags) records.

WHAT FAILS IT. A cell lost (`LOST: <app>: <column> was met and is not now`), an app gone, a measure that
could not read (exit 2), a self-test case that does not hold. A newly closed cell passes and says so.
"""
import os
import subprocess
import sys

# it prints the measure's lines, Hebrew among them (G10): UTF-8 whatever the host's default
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT =os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEASURE = os.path.join(ROOT, "scripts", "app-standard", "measure.py")


def run(*args):
    r = subprocess.run([sys.executable, MEASURE, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (r.stdout + r.stderr).strip()
    if out:
        print(out)
    return r.returncode


def main():
    if "--self-test" in sys.argv[1:]:
        rc = run("--self-test")
        print(f"G114 self-test {'PASS' if rc == 0 else 'FAIL'}")
        return rc
    rc = run("--check", "--no-views")
    print(f"G114 {'PASS' if rc == 0 else 'FAIL'} — the app standard's closed cells "
          f"{'hold' if rc == 0 else 'do not hold (or the measure did not read)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
