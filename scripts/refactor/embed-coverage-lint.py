#!/usr/bin/env python3
"""embed-coverage-lint — gate G78: the UI map's denominator builds, and every app the shell frames is in it.

    python3 scripts/refactor/embed-coverage-lint.py [--self-test]

WHY THIS EXISTS. `bbox ui-map` measures what `scripts/ui-coverage/inventory.py` derives from
source, and the console embeds whatever `.generated/registry/console.modules.yaml` lists. Those
two are built by different code paths, and nothing compared them — so an app could be installed,
enabled and sitting in the rail while the map had never heard of it.

That is not hypothetical. Measured 2026-09-29: of the 16 embedded modules, **data-management had
zero views** in the denominator, and eight others (bina, telegram-tv, git, sites, domains,
computers, app-management) had been missing until they were found by hand the same week. A green
`ui-map` said "all first-party views captured" while the product had screens nobody had ever
looked at — the same class of false positive as a blank screenshot that reports CAPTURED.

WHAT IT ENFORCES. Two things, both asked of the inventory itself:

  1. IT BUILDS. The inventory refuses to produce a denominator when an app's view model stops
     matching what it reads — which is its job — and then `bbox ui-map` cannot run at all. On
     2026-10-06 the apps screen gave its tabs an `icon:` key, the tab-table reader counted 0 rows,
     and the map could not be built on any office for a day. Nobody knew, because —
  2. EVERY APP THE SHELL FRAMES HAS A VIEW. The inventory's `framed` list is the tiles the
     manifests declare that the compiler emitted on this office; an app in it with no view is
     missing an extractor or a `single_view` row (archify sat in the rail of hp-laptop that way).

— IT WAS CALLED BY NOTHING. Written 2026-09-29, wired into no runner: `run-gates.py` printed it
under UNWIRED on every run and exited 1 for it. It is in the gate list now.

AN OFFICE, NOT THE ESTATE. Offices run different apps; the inventory leaves out what this one
does not run (and says so), and this gate asks only about what is left. On a machine where nothing
was ever compiled there is no registry to ask — that is said as NOT CHECKED, never as a pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def uncovered(inv: dict) -> list[str]:
    """The apps the shell frames here that have no view in the inventory."""
    seen = {v["app"] for v in inv.get("views") or []}
    return [app for app in inv.get("framed") or [] if app not in seen]


def main() -> int:
    if not (ROOT / ".generated" / "registry" / "console.modules.yaml").is_file():
        print("NOT CHECKED  nothing was compiled on this machine (.generated/registry/console.modules.yaml): "
              "an office that was never rendered has no tiles to count")
        return 0
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "inv.json"
        r = subprocess.run([sys.executable, str(ROOT / "scripts/ui-coverage/inventory.py"), "--out", str(out)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        if r.returncode != 0 or not out.exists():
            print("FAIL  the inventory does not build, so `bbox ui-map` cannot run — what it said:")
            print((r.stdout + r.stderr).strip()[-900:])
            return 1
        inv = json.loads(out.read_text(encoding="utf-8"))

    framed = inv.get("framed") or []
    if not framed:
        print("FAIL  the inventory frames no app in the shell — every office frames at least its own "
              "apps screen, so nothing was compared")
        return 1
    bad = uncovered(inv)
    if bad:
        print(f"FAIL  {len(bad)} app(s) the shell frames have NO view in the UI map: {', '.join(bad)}")
        print("      A framed app is in the console's rail, so a map without it measures a smaller\n"
              "      product than the one in front of the owner. Give it an extractor in\n"
              "      scripts/ui-coverage/inventory.py, or a `single_view` row in manifest.yaml.")
        return 1
    off = inv.get("not_here") or {}
    print(f"G78 PASS — the inventory builds ({inv['totals']['all']} views, {inv['totals']['apps']} apps) and "
          f"all {len(framed)} app(s) the shell frames here are in it"
          + (f"; {len(off)} app(s) this office does not run are left out" if off else ""))
    return 0


def self_test() -> int:
    view = lambda app: {"app": app, "id": "main"}                                     # noqa: E731
    cases = [
        ("a framed app with a view is covered", uncovered({"framed": ["drive"], "views": [view("drive")]}), []),
        ("a framed app with NO view is named",
         uncovered({"framed": ["drive", "archify"], "views": [view("drive")]}), ["archify"]),
        ("an app that is not framed owes nothing",
         uncovered({"framed": ["drive"], "views": [view("drive"), view("n8n")]}), []),
        ("an inventory with no views at all: every framed app is named",
         uncovered({"framed": ["drive", "machine"], "views": []}), ["drive", "machine"]),
    ]
    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("embed-coverage-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
