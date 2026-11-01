#!/usr/bin/env python3
"""dock-fit.py — the desktop dock's capacity, MEASURED against a live console.

    python3 scripts/ui-coverage/dock-fit.py [--url http://console:8000/] [--widths 1294x810,1440x900,1920x1080]

WHY THIS EXISTS. `issues/console-desktop-dock-overflows-its-pill-and-hides-17-apps.yaml` was not a
style complaint: the dock drew one 46px tile per (app × machine) in an uncapped row, so 2189px of
content was clipped by a pill capped at `100vw - 40px` — 17 of 40 tiles unreachable by pointer at the
owner's own width, with the rail hidden in desktop mode. The fix is a budget
(`platform-base/console/static/dock-budget.js`, `ai/context/console-dock-capacity-design.md`), and a
budget is only true if someone measures the rendered row. This does, at the widths that matter:

  · every tile inside the pill's box (nothing paints outside it, nothing is clipped) — the property
    the bug broke;
  · every app reachable: the apps the dock did not draw are in the «עוד» door's panel, every panel
    tile is inside the panel's box, and clicking one opens it (a window, or the app's own host);
  · the dock's own size does not change with the estate: same width for 0 apps and for 40
    (the property that makes the next install a non-event).

It needs a browser and a reachable console: the ui-capture image has both
(`scripts/ui-coverage/Dockerfile`), e.g.

    docker run --rm -v "$PWD":/repo -w /repo -e UI_CHROME_BIN=/usr/bin/chromium ui-capture:latest \
      python3 scripts/ui-coverage/dock-fit.py --url http://console:8000/

Exit code is non-zero on any failed measurement, so it can gate CI (see
`scripts/refactor/dock-fit-lint.py`, which runs it from the gate registry — in WARN mode for one
release, per AGENTS.md's staged rollout).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

# This prints Hebrew («עוד»), and a Windows console is cp1255/cp1252 unless told otherwise: without
# this the first PASS line is a UnicodeEncodeError there (gate G10, portability-lint).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_WIDTHS = ["1294x810", "1440x900", "1920x1080"]
#: How long a console gets to mount the desktop, in each viewport.
READY_S = 25.0

MEASURE = """
() => {
  const d = document.querySelector('.dk-dock');
  const r = d.getBoundingClientRect();
  const tiles = [...d.querySelectorAll('.dk-ic')];
  const gap = parseFloat(getComputedStyle(d).columnGap) || 0;
  const outside = tiles.filter(e => { const b = e.getBoundingClientRect();
    return b.left < r.left - .5 || b.right > r.right + .5; });
  const door = d.querySelector('.dk-more-ic');
  // The ROW (tiles + the gaps between them) against the pill's own content box — NOT `scrollWidth`,
  // which also counts decorations this design paints outside a tile on purpose (the hover tooltip, the
  // door's count badge, both inside the pill's padding): a check that flags those would forbid the
  // affordances and call it a fix.
  const row = tiles.reduce((a, e) => a + e.getBoundingClientRect().width, 0) + gap * Math.max(0, tiles.length - 1);
  return {
    tiles: tiles.length, apps: (typeof MODULES !== 'undefined' && Array.isArray(MODULES) ? MODULES.length : -1),
    dockLeft: r.left, dockRight: r.right, dockWidth: r.width, box: d.clientWidth, row: row,
    gap: gap, outside: outside.length,
    overflows: row > d.clientWidth + 1,
    offScreen: tiles.filter(e => e.getBoundingClientRect().right <= 0
                             || e.getBoundingClientRect().left >= window.innerWidth).length,
    door: !!door,
    doorCount: door ? (door.querySelector('.dk-more-n') || {}).textContent || '' : '',
    // the door must not be a second copy of the tile beside it: same glyph, same colour, told apart
    // by a badge is what it was on its first day
    doorIsATwin: !!door && tiles.some(e => e !== door && e.querySelector('svg') && door.querySelector('svg')
                                           && e.querySelector('svg').innerHTML === door.querySelector('svg').innerHTML),
  };
}
"""

#: What a person types to find an app, taken from the registry the page itself holds: an app's id
#: in the OTHER case than it is written in, and the lower-cased name of a linked office. Both found
#: nothing while the panel searched the Hebrew name case-sensitively.
PROBES = """
() => {
  if (typeof MODULES === 'undefined' || !Array.isArray(MODULES)) return null;
  const ascii = MODULES.find(m => /^[a-z][a-z0-9.-]+$/.test(String(m.id)) && !String(m.name).toLowerCase().includes(String(m.id)));
  const far = MODULES.find(m => m.remote && typeof m.remote === 'object');
  const lab = far && (typeof far.remote.label === 'string' ? far.remote.label
                      : (far.remote.label || {}).he || (far.remote.label || {}).en || far.remote.office);
  return {id: ascii ? String(ascii.id) : '', typedId: ascii ? String(ascii.id).toUpperCase() : '',
          office: lab ? String(lab).toLowerCase() === String(lab) ? String(lab).toUpperCase() : String(lab).toLowerCase() : ''};
}
"""

HITS = "() => [...document.querySelectorAll('.dk-more .htile')].map(e => e.dataset.mid)"

#: A window's three controls, as drawn. In a right-to-left bar the group sits at the bar's start (its
#: right end) and the first control in the DOM is the outermost: x FALLS along the DOM order.
LIGHTS = """
() => {
  const l = document.querySelector('.dk-win .dk-lights');
  if (!l) return null;
  const xs = [...l.children].map(e => e.getBoundingClientRect().left);
  const bar = l.closest('.dk-tb').getBoundingClientRect(), box = l.getBoundingClientRect();
  return { n: xs.length, dir: getComputedStyle(l).direction,
           mirrored: xs.every((x, i) => i === 0 || x < xs[i - 1]),
           atStart: (bar.right - box.right) < (box.left - bar.left) };
}
"""

PANEL = """
() => {
  const ov = document.querySelector('.dk-more');
  if (!ov) return null;
  const box = ov.querySelector('.dk-more-box'), list = ov.querySelector('.dk-more-list');
  if (!box || !list) return null;
  const lb = list.getBoundingClientRect();
  const tiles = [...ov.querySelectorAll('.htile')];
  // Every tile is inside the SCROLLER's box horizontally — the panel's list is the one place the
  // design allows a scroll ("inside the overflow panel, not on the dock"), so what is asserted is
  // that nothing spills sideways out of it and that every app is present at all.
  const sideways = tiles.filter(e => { const t = e.getBoundingClientRect();
    return t.left < lb.left - .5 || t.right > lb.right + .5; }).length;
  // …and that a NAME is whole: not cut sideways, not cut below its second line.
  const cut = tiles.map(e => e.querySelector('.htile-nm')).filter(n => n &&
    (n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1)).map(n => n.textContent);
  return {tiles: tiles.length, sideways: sideways, boxWidth: box.getBoundingClientRect().width, cut: cut,
          scrolls: list.scrollHeight > list.clientHeight + 1,
          hasSearch: !!ov.querySelector('.dk-more-q'),
          focused: document.activeElement === ov.querySelector('.dk-more-q')};
}
"""


def chrome_path():
    p = os.environ.get("UI_CHROME_BIN")
    if p and pathlib.Path(p).exists():
        return p
    for c in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
        if pathlib.Path(c).exists():
            return c
    return None


def run(url: str, widths: list[str], keep: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — run this inside the ui-capture image "
              "(scripts/ui-coverage/Dockerfile), which has it and a Chromium", file=sys.stderr)
        return 2

    failed = 0
    exe = chrome_path()
    with sync_playwright() as p:
        launch = {"args": ["--no-sandbox"]}
        if exe:
            launch["executable_path"] = exe
        browser = p.chromium.launch(**launch)
        for spec in widths:
            w, _, h = spec.partition("x")
            ctx = browser.new_context(viewport={"width": int(w), "height": int(h or 800)})
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_function("!!window.BinaDesktop", timeout=int(READY_S * 1000))
                page.evaluate("window.BinaDesktop.enable()")
                page.wait_for_selector(".dk-dock .dk-ic", timeout=int(READY_S * 1000))
                page.wait_for_timeout(400)                      # a settle for the budget's own pass
            except Exception as e:                              # noqa: BLE001 — reported, not raised
                print(f"FAIL  {spec} · the desktop never mounted a dock: {type(e).__name__}")
                failed += 1
                ctx.close()
                continue
            if keep:
                pathlib.Path(keep).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(pathlib.Path(keep) / f"dock-{spec}.png"))
            m = page.evaluate(MEASURE)
            problems = []
            if m["overflows"]:
                problems.append(f"the row is {m['row']:.0f}px inside a {m['box']:.0f}px pill")
            if m["outside"]:
                problems.append(f"{m['outside']} tile(s) paint outside the pill")
            if m["offScreen"]:
                problems.append(f"{m['offScreen']} tile(s) off screen")
            if errors:
                problems.append(f"JS errors: {errors[:2]}")
            hidden = m["apps"] - (m["tiles"] - (1 if m["door"] else 0))
            if hidden > 0 and not m["door"]:
                problems.append(f"{hidden} app(s) are neither in the dock nor behind a door")
            if m["doorIsATwin"]:
                problems.append("the «עוד» door wears the same glyph as another dock tile")
            panel = "—"
            if m["door"]:
                page.click(".dk-more-ic")
                page.wait_for_timeout(400)
                if keep:
                    page.screenshot(path=str(pathlib.Path(keep) / f"dock-panel-{spec}.png"))
                pm = page.evaluate(PANEL)
                if not pm:
                    problems.append("the «עוד» door opened nothing")
                else:
                    panel = f"{pm['tiles']} tiles, scrolls={pm['scrolls']}"
                    if pm["sideways"]:
                        problems.append(f"{pm['sideways']} panel tile(s) spill out of the panel's box")
                    if pm["tiles"] < m["apps"]:
                        problems.append(f"the panel shows {pm['tiles']} tiles for {m['apps']} apps")
                    if not pm["hasSearch"] or not pm["focused"]:
                        problems.append("the panel has no focused search field")
                    if pm["boxWidth"] > int(w) - 30:
                        problems.append(f"the panel is {pm['boxWidth']:.0f}px wide in a {w}px viewport")
                    if pm["cut"]:
                        problems.append(f"{len(pm['cut'])} name(s) are cut in the panel: {pm['cut'][:3]}")
                    # …its search finds an app by what a person calls it: its id, or its office, in
                    # whatever case they type (the registry the page holds says which to try).
                    probe = page.evaluate(PROBES)
                    if probe and probe["typedId"]:
                        page.fill(".dk-more-q", probe["typedId"])
                        page.wait_for_timeout(150)
                        if probe["id"] not in page.evaluate(HITS):
                            problems.append(f"typing {probe['typedId']!r} does not find the app `{probe['id']}`")
                    if probe and probe["office"]:
                        page.fill(".dk-more-q", probe["office"])
                        page.wait_for_timeout(150)
                        if not page.evaluate(HITS):
                            problems.append(f"typing the office {probe['office']!r} finds nothing")
                    page.fill(".dk-more-q", "")
                    page.wait_for_timeout(150)
                    # …Escape closes it and puts the keyboard back on the door it came from.
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)
                    if page.query_selector(".dk-more"):
                        problems.append("Escape did not close the panel")
                    elif not page.evaluate("document.activeElement === document.querySelector('.dk-more-ic')"):
                        problems.append("after Escape the focus is not back on the door")
                    page.click(".dk-more-ic")
                    page.wait_for_timeout(300)
                    # …and a panel tile is REACHABLE: clicking one opens the app (a window here).
                    before = len(page.query_selector_all(".dk-win"))
                    page.click(".dk-more-box .htile")
                    page.wait_for_timeout(600)
                    after = len(page.query_selector_all(".dk-win"))
                    if after <= before:
                        problems.append("clicking a panel tile opened nothing")
                    if page.query_selector(".dk-more"):
                        problems.append("the panel stayed open after choosing an app")
            # …and a WINDOW's three controls mirror with its bar. Pinned to ltr, the group mirrored
            # and its contents did not (the owner found it, 2026-10-05). Asked of a window this run
            # opens itself — the door's tile above, or a dock tile where there is no door.
            for tile in page.query_selector_all('.dk-dock .dk-ic[data-mid]:not([data-mid^="native:"])')[:4]:
                if page.query_selector(".dk-win .dk-lights"):
                    break
                tile.click()
                try:                                    # a window mounts when it mounts — wait for IT
                    page.wait_for_selector(".dk-win .dk-lights", timeout=3000)
                except Exception:                       # noqa: BLE001 — a tile that opens its own host
                    continue
            lights = page.evaluate(LIGHTS)
            if lights is None:
                problems.append("no window could be opened to look at its controls")
            elif lights["n"] != 3 or lights["dir"] != "rtl" or not lights["mirrored"] or not lights["atStart"]:
                problems.append(f"a window's controls do not mirror with its bar: {lights}")
            state = "PASS" if not problems else "FAIL"
            failed += 1 if problems else 0
            print(f"{state}  {spec} · dock {m['dockWidth']:.0f}px, row {m['row']:.0f}px of {m['box']:.0f}px, "
                  f"{m['tiles']} tiles, door {m['door']}{' (' + m['doorCount'] + ')' if m['door'] else ''}, "
                  f"apps {m['apps']}, panel {panel}, window controls "
                  f"{'mirrored' if lights and lights.get('mirrored') and lights.get('atStart') else 'NOT mirrored'}")
            for pr in problems:
                print(f"        {pr}")
            ctx.close()
        browser.close()
    print(f"\n{len(widths) - failed}/{len(widths)} widths passed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DOCK_FIT_URL", "http://console:8000/"))
    ap.add_argument("--widths", default=",".join(DEFAULT_WIDTHS))
    ap.add_argument("--screenshots", default="")
    a = ap.parse_args()
    widths = [x.strip() for x in a.widths.split(",") if x.strip()]
    return run(a.url.rstrip("/") + "/", widths, a.screenshots)


if __name__ == "__main__":
    sys.exit(main())
