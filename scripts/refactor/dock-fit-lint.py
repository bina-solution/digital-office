#!/usr/bin/env python3
"""dock-fit-lint — gate G79: the desktop dock never paints a tile outside its pill, and a window's controls mirror with its bar.

    python3 scripts/refactor/dock-fit-lint.py            # static invariants + the arithmetic test
    python3 scripts/refactor/dock-fit-lint.py --live     # …and the measurement, if a console answers
    python3 scripts/refactor/dock-fit-lint.py --strict   # a failed measurement is a failure

THE BUG (issues/console-desktop-dock-overflows-its-pill-and-hides-17-apps.yaml): the dock drew one
46px tile per (app × machine) in an uncapped flat row, so its WIDTH was a function of how many apps
exist. 2189px of content against a pill capped at `100vw - 40px`, clipped — 17 of 40 tiles
unreachable by pointer at the owner's own width, and in desktop mode the rail is hidden, so ⌘K was the
only way to them. It shipped because nothing measured the rendered dock: G27's TARGETS excluded
`desktop.css`, G9 skips `/static/`, and `console/test_app.py` is a server-side suite.

WHAT THIS CHECKS, and why in two halves:

  * STATIC (always, no stack, a second): the dock's capacity is a pure function
    (`static/dock-budget.js`), the dock ASKS it (`desktop.js` calls `resolveDock`), a new width
    rebuilds the dock, the tiles take their size from the `--dock-*` custom properties, `.dk-ic` still
    refuses to shrink, and the «עוד» door that absorbs what does not fit exists. Plus the arithmetic
    test itself (`platform-base/console/test_dock_budget.mjs`) — 3 slots to 240 tiles, every width
    from 1024 to 4000, the row must fit its slots.
  * LIVE (`--live`, or when a console answers): `scripts/ui-coverage/dock-fit.py`, which renders the
    console in desktop mode at 1294/1440/1920 and asserts that no tile paints outside the pill, none
    is off screen, every app the dock did not draw is behind the door, and a panel tile opens — and
    that a window's three controls mirror with its bar (the desktop's other bug; the static half
    refuses the stylesheet rule that caused it).

WARN MODE FOR ONE RELEASE. `run-gates.py` invokes this with `--warn` (see GATE_ARGS): a failed live
measurement is printed as WARN and exits 0, per the design doc's §8.5 and AGENTS.md's staged-rollout
rule for a tightened contract. Removing `--warn` from GATE_ARGS is the whole flip.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

import office_browser

# This prints Hebrew («עוד»), and a Windows console is cp1255/cp1252 unless told otherwise: without
# this its own PASS line is a UnicodeEncodeError there (gate G10, portability-lint).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
STATIC = REPO / "platform-base" / "console" / "static"
DEFAULT_URL = "http://console:8000/"      # the console by its name ON the office's docker network


def read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def static_checks() -> list[str]:
    bad: list[str] = []
    budget = read(STATIC / "dock-budget.js")
    desktop = read(STATIC / "desktop.js")
    css = read(STATIC / "desktop.css")
    html = read(STATIC / "index.html")

    if "resolveDock" not in budget or "dockRoom" not in budget:
        bad.append("static/dock-budget.js no longer exports resolveDock/dockRoom — the dock's "
                   "capacity must stay ONE pure function (console-dock-capacity-design.md §6.2)")
    if re.search(r"\bdocument\b|\bwindow\.document\b", budget):
        bad.append("static/dock-budget.js touches the DOM: it is the arithmetic, not the renderer "
                   "(which is what lets test_dock_budget.mjs run it without a browser)")
    if "resolveDock" not in desktop:
        bad.append("desktop.js does not call resolveDock — the dock is drawing whatever it likes again")
    if "dockBudget" not in desktop or "buildDock()" not in desktop:
        bad.append("desktop.js has no dockBudget()/buildDock() pair")
    # The dock must be REBUILT when the viewport changes: the budget is a function of the width, and
    # a stale dock is a dock whose slots no longer match its pill (zoom is a resize).
    if not re.search(r"addEventListener\(\"resize\"", desktop) or desktop.count("buildDock()") < 3:
        bad.append("desktop.js does not rebuild the dock on resize — a new width is a new budget")
    if not re.search(r"\.dk-ic\{[^}]*width:var\(--dock-tile", css):
        bad.append("desktop.css .dk-ic does not take its size from --dock-tile (a number in two "
                   "places is a future inconsistency — design doc §6.2)")
    if re.search(r"\.dk-ic\{[^}]*flex-shrink", css) or re.search(r"\.dk-ic\{[^}]*min-width:0", css):
        bad.append("desktop.css lets .dk-ic shrink — the 44px hit-target floor is what §6.5 forbids")
    if "--dock-pad" not in css or "--dock-gap" not in css:
        bad.append("desktop.css does not consume the --dock-gap/--dock-pad tokens")
    if "dk-more-ic" not in desktop or ".dk-more" not in css:
        bad.append("the «עוד» door (or its panel) is gone: what does not fit must stay reachable")
    if "/dock-budget.js" not in html:
        bad.append("index.html does not load /dock-budget.js — the dock would fall back silently")
    # A window's three controls mirror WITH its bar. `.dk` is direction:rtl; pinned to ltr, the
    # group sat at the bar's start with its own contents un-mirrored — the green dot outermost
    # (issues/console-desktop-window-controls-half-mirrored-in-rtl.yaml, found by the owner). A
    # token may be ltr (a shortcut, a URL); the GROUP may not set a direction of its own.
    lights = re.search(r"\.dk-lights\{([^}]*)\}", css)
    if not lights:
        bad.append("desktop.css has no .dk-lights rule — the window controls' group changed its name")
    elif re.search(r"(^|;)\s*direction\s*:", lights.group(1)):
        bad.append("desktop.css pins .dk-lights to a direction of its own — the window's controls "
                   "must inherit the bar's, or the group mirrors and its contents do not")
    return bad


def arithmetic_test() -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return True, "node not installed — the arithmetic test was NOT run here"
    if not (REPO / "platform-base" / "console" / "test_dock_budget.mjs").exists():
        return False, "platform-base/console/test_dock_budget.mjs is missing"
    r = subprocess.run([node, "platform-base/console/test_dock_budget.mjs"], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    tail = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()][-1:]
    return r.returncode == 0, (tail[0] if tail else f"exit {r.returncode}")


def live_measure(url: str) -> tuple[bool | None, str]:
    """(ok, said) — None when the measurement could not run here (and why)."""
    script = "scripts/ui-coverage/dock-fit.py"
    if not (REPO / script).exists():
        return None, f"{script} is missing"
    run, inside, why = office_browser.lane()
    if run is None:
        return None, f"{why} — the dock was NOT measured in this run"
    # A URL somebody passed is used as given; the default is asked for (office_browser.url: the
    # console's NAME resolves only on the docker network, so a host's browser needs its address).
    if url == DEFAULT_URL:
        url = office_browser.url("console", 8000, inside)
        if not url:
            return None, ("no running console container to measure from this host — the dock was "
                          "NOT measured in this run")
    cmd = [*run, script, "--url", url]
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "the measurement timed out"
    lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
    if lines:
        return r.returncode == 0, " · ".join(lines[-4:])
    # Nothing on stdout: the reason is on the other stream, and "exit 1" is not a reason.
    why = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()]
    return r.returncode == 0, f"exit {r.returncode}" + (f" — {why[-1][:200]}" if why else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also measure a running console")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--warn", action="store_true", help="a failed measurement warns instead of failing")
    ap.add_argument("--strict", action="store_true", help="a failed measurement always fails")
    a = ap.parse_args()

    bad = static_checks()
    ok_math, said_math = arithmetic_test()
    if not ok_math:
        bad.append(f"the capacity arithmetic test failed: {said_math}")

    print("dock-fit-lint — the desktop dock's capacity")
    if bad:
        for b in bad:
            print(f"  FAIL  {b}")
    else:
        print("  PASS  static: one pure budget, asked for on every width; tiles sized by token, "
              "never shrinking; an «עוד» door for what does not fit")
        print(f"  PASS  arithmetic: {said_math}")

    measured: bool | None = None
    if a.live:
        measured, said = live_measure(a.url)
        if measured is None:
            print(f"  SKIP  measurement: {said}")
        elif measured:
            print(f"  PASS  measured: {said}")
        else:
            word = "WARN" if (a.warn and not a.strict) else "FAIL"
            print(f"  {word}  measured: {said}")

    if bad:
        return 1
    if measured is False and not a.warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
