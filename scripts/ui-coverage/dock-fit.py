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
    (the property that makes the next install a non-event);
  · and the SCREEN it sits on is whole at every width from 360 up (DGO-1637): the menu bar on the
    screen with no item cut, a desk opened wide and then narrowed in place (`--narrow`) keeping its
    bar, its search and a dock inside the screen with Files under ONE bar, and a phone (`--phones`)
    with no sideways scroll. `--static-from <checkout>` serves a commit's console and Files static
    files to the live console's page — a before/after pair with no deploy.

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
#: DGO-1637's acceptance: every width from 360 up — a desk narrowed in place, and a phone from the start
DEFAULT_NARROW = ["1100x800", "900x760", "700x760", "390x844", "360x780"]
DEFAULT_PHONES = ["390x844", "360x780"]
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

#: DGO-1637 — the desk on a screen NARROWER than it was opened at («התפריט … נחתך באמצע ברגע שהמסך
#: צר מדי, זה באג»). Compact hid the bar (search and menus gone), kept the wide dock as a sideways
#: scroller cut at the screen's edge, and let Files draw its phone tabs above the dock: two bars. What
#: must hold at every width: the page does not scroll sideways; the bar is on the screen with the
#: office's mark and the search, and no item of it is cut; the dock is inside the screen and is no
#: scroller; the focused app draws no phone tabs of its own under the shell's bars.
NARROW = """
() => {
  const vw = innerWidth, box = e => e.getBoundingClientRect();
  const shown = e => !!e && e.offsetWidth > 0 && e.offsetHeight > 0 && getComputedStyle(e).visibility !== 'hidden';
  const bar = document.querySelector('.dk-bar'), dock = document.querySelector('.dk-dock');
  const b = shown(bar) ? box(bar) : null;
  const items = b ? [...bar.children].filter(e => !e.classList.contains('dk-grow') && shown(e)) : [];
  const cut = b ? items.filter(e => { const r = box(e);
      return r.left < Math.max(0, b.left) - .5 || r.right > Math.min(vw, b.right) + .5; })
    .map(e => (e.className || e.tagName) + ':' + (e.textContent || '').trim().slice(0, 12)) : [];
  const tiles = dock ? [...dock.querySelectorAll('.dk-ic')] : [];
  const d = shown(dock) ? box(dock) : null;
  let tabs = null;                  // null: the focused window's page could not be read (another host)
  try { const f = document.querySelector('.dk-win.focused iframe'), doc = f && f.contentDocument;
        if (doc && doc.querySelector('.fx')) tabs = !!doc.querySelector('.fx-tabs'); } catch (e) { /* ignore */ }
  return { compact: !!document.querySelector('.dk.compact'),
           hscroll: document.documentElement.scrollWidth > vw + 1,
           bar: !!b, mark: shown(bar && bar.querySelector('.dk-logo')), search: shown(bar && bar.querySelector('.dk-srch')),
           cut: cut, barOverflow: b ? bar.scrollWidth > bar.clientWidth + 1 : null,
           folds: bar ? [...bar.classList].filter(c => /^f-/.test(c)) : [],
           dock: !!d, dockIn: d ? d.left >= -.5 && d.right <= vw + .5 : false,
           // a scroller is a box that SCROLLS: the tiles' tooltips overhang the pill by design (MEASURE)
           dockScrolls: dock ? /auto|scroll/.test(getComputedStyle(dock).overflowX) && dock.scrollWidth > dock.clientWidth + 1 : null,
           offScreen: tiles.filter(e => { const r = box(e); return r.left < -.5 || r.right > vw + .5; }).length,
           appTabs: tabs };
}
"""

#: The office's mark menu, opened: whole inside the screen, and what it offers.
MARK_MENU = """
() => { const m = document.querySelector('.dk-menu'); if (!m) return null; const r = m.getBoundingClientRect();
  return { inside: r.left >= -.5 && r.right <= innerWidth + .5 && r.bottom <= innerHeight + .5,
           items: [...m.querySelectorAll('[role=menuitem]')].map(e => e.textContent.trim()) }; }
"""

#: The classic shell on a screen that is narrow from the start (a phone): no sideways scroll, the
#: search whole on the screen, and Files with ONE bar at the bottom (the office's, DGO-1507).
PHONE = """
() => { const vw = innerWidth, s = document.querySelector('#paletteBtn'), r = s && s.getBoundingClientRect();
  let tabs = null;
  try { const doc = document.querySelector('#frame').contentDocument;
        if (doc && doc.querySelector('.fx')) tabs = !!doc.querySelector('.fx-tabs'); } catch (e) { /* ignore */ }
  return { desk: !!document.querySelector('.dk'), hscroll: document.documentElement.scrollWidth > vw + 1,
           search: !!r && r.width > 0 && r.left >= -.5 && r.right <= vw + .5, appTabs: tabs }; }
"""


def bar_problems(m: dict) -> list[str]:
    """What NARROW says is wrong with the bar and the dock, in words."""
    out = []
    if m["hscroll"]:
        out.append("the page scrolls sideways")
    if not (m["bar"] and m["mark"] and m["search"]):
        out.append(f"the bar is not on the screen whole (bar {m['bar']}, mark {m['mark']}, search {m['search']})")
    if m["cut"] or m["barOverflow"]:
        out.append(f"the bar is cut: {m['cut'][:4]}")
    if not (m["dock"] and m["dockIn"]) or m["offScreen"]:
        out.append(f"the dock is not inside the screen ({m['offScreen']} tile(s) off it)")
    if m["dockScrolls"]:
        out.append("the dock is a sideways scroller")
    return out


def _wanted(entry: str, name: str, path: str) -> bool:
    """An --static-only entry: a bare name matches a file of that name; one with a `/` is a served path
    (without its leading slash), and a trailing `*` makes it a prefix."""
    if "/" not in entry:
        return name == entry
    served = path.lstrip("/")
    return served.startswith(entry[:-1]) if entry.endswith("*") else served == entry


def static_router(root: str, console_url: str, as_user: str = "", only: frozenset = frozenset()):
    """Serve the console's and Files' static files from a CHECKOUT instead of the console answering —
    so one live console shows what a commit's screens do (a before/after pair: the base commit, then
    the change), with no deploy. Files' own page (index.html) stays the app's: its server marks it.
    Only the console's own host is answered: an app on its own host keeps its own files.

    `as_user`: the console on its own address has nobody signed in, so it lists no apps and no window
    can be opened (`apps 0`). The edge's forward-auth names the person in `X-authentik-username`; this
    names a PROOF user the same way, on GET/HEAD to the console's host only — a read-only look, never
    a write in anybody's name.

    `only`: serve just these from the checkout — a file NAME (`desktop.js`), or a served PATH, `*` closing a
    prefix (`a/drive/*` = all of Files' static). A checkout's WHOLE console beside another office's server is
    not that office: measured on vps1, mac-dgo's app.js and index.html against vps1-dgo's server failed every
    API call («Failed to fetch»), so the shell listed no app — while the change under test was two files.
    Name the files the change touched (a bare `app.js` would be the console's AND Files' — use a path)."""
    base = pathlib.Path(root).resolve() if root else None
    con = base / "platform-base/console/static" if base else None
    drv = base / "apps/drive/static" if base else None
    from urllib.parse import urlparse
    host = urlparse(console_url).netloc

    def handle(route):
        u = urlparse(route.request.url)
        if u.netloc != host:
            route.continue_()
            return
        p = u.path
        f = None
        if base and p.startswith("/a/drive/"):
            rest = p[len("/a/drive/"):]
            if rest and not rest.endswith(".html"):
                f = drv / rest
        elif base and p.count("/") == 1:
            f = con / (p[1:] or "index.html")
        if f is not None and (not only or any(_wanted(o, f.name, p) for o in only)):
            f = f.resolve()
            if f.is_file() and (con in f.parents or drv in f.parents):
                route.fulfill(path=str(f))
                return
        if as_user and route.request.method in ("GET", "HEAD"):
            route.continue_(headers={**route.request.headers, "x-authentik-username": as_user})
            return
        route.continue_()
    return handle


def narrowed(browser, url: str, sizes: list[str], keep: str, route) -> int:
    """A desk opened wide with Files in a window, then the screen made narrower step by step — the
    owner's own move (MEET-28, 43:58). Returns how many widths failed."""
    failed = 0
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    if route:
        ctx.route("**/*", route)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_function("!!window.BinaDesktop", timeout=int(READY_S * 1000))
        page.evaluate("window.BinaDesktop.enable()")
        page.wait_for_selector(".dk-dock .dk-ic", timeout=int(READY_S * 1000))
    except Exception as e:                                      # noqa: BLE001 — reported, not raised
        print(f"FAIL  narrowed · the desktop never mounted a dock: {type(e).__name__}")
        ctx.close()
        return len(sizes)
    # The shell lists its apps only once its boot has asked the office (and its linked offices) who it
    # is — tens of seconds on a herd's centre (measured on the HP: the dock mounted with `apps 0` while
    # /api/modules answered 57). Waited for here, so the window the owner had open is really opened.
    try:
        page.wait_for_function("typeof MODULES !== 'undefined' && Array.isArray(MODULES) && MODULES.length > 0",
                               timeout=45000)
    except Exception:                                           # noqa: BLE001 — said in the line below
        print("NOTE  narrowed · the shell listed no app within 45 s — the app in the window is not measured")
    app = page.evaluate("""() => { const all = typeof MODULES !== 'undefined' && Array.isArray(MODULES) ? MODULES : [];
        const m = all.find(x => x.id === 'drive') || all.find(x => x.embed);
        if (m) window.BinaDesktop.openModule(m, ''); return m ? m.id : null; }""")
    page.wait_for_timeout(3000)                                 # the app's page loads and offers its search
    for spec in sizes:
        # one width that breaks (a click or a load that times out) is that width's FAIL, not the run's end
        try:
            failed += narrow_one(page, spec, keep, app, errors)
        except Exception as e:                                  # noqa: BLE001 — reported, not raised
            failed += 1
            print(f"FAIL  narrowed 1440→{spec} · the measurement broke: {type(e).__name__}: {str(e)[:160]}")
    ctx.close()
    return failed


def narrow_one(page, spec: str, keep: str, app: str, errors: list[str]) -> int:
    w, _, h = spec.partition("x")
    page.set_viewport_size({"width": int(w), "height": int(h or 800)})
    page.wait_for_timeout(900)                                  # the resize's debounce, then the bar's fit
    if keep:
        page.screenshot(path=str(pathlib.Path(keep) / f"narrowed-{spec}.png"))
    m = page.evaluate(NARROW)
    problems = bar_problems(m)
    if int(w) < 1024 and not m["compact"]:
        problems.append("the desk did not go compact below 1024")
    if m["compact"] and m["appTabs"]:           # (a wide desk's window may have its own: it is a window)
        problems.append(f"`{app}` draws its own phone tabs above the dock: two bars")
    # the mark's menu — only when the mark is on the screen at all (bar_problems already said it is not)
    if m["mark"]:
        page.click(".dk-bar .dk-logo")
        page.wait_for_timeout(250)
        if keep:
            page.screenshot(path=str(pathlib.Path(keep) / f"narrowed-menu-{spec}.png"))
        mm = page.evaluate(MARK_MENU)
        if not mm or not mm["inside"]:
            problems.append("the mark's menu is not whole inside the screen")
        elif "f-menus" in m["folds"] and not any(t.startswith("חלון") for t in mm["items"]):
            problems.append("the bar folded its menus and the mark's menu does not offer them")
        if mm:
            page.click(".dk-bar .dk-logo")                      # the same press closes it
            page.wait_for_timeout(150)
    if errors:
        problems.append(f"JS errors: {errors[:2]}")
        errors.clear()
    print(f"{'PASS' if not problems else 'FAIL'}  narrowed 1440→{spec} · compact {m['compact']}, folds "
          f"{','.join(m['folds']) or '—'}, app `{app}` own tabs {m['appTabs']}")
    for pr in problems:
        print(f"        {pr}")
    return 1 if problems else 0


def phone(browser, url: str, sizes: list[str], keep: str, route) -> int:
    """The classic shell at a phone's width from the start, Files open. Returns how many failed."""
    failed = 0
    for spec in sizes:
        w, _, h = spec.partition("x")
        ctx = browser.new_context(viewport={"width": int(w), "height": int(h or 800)}, is_mobile=True, has_touch=True)
        if route:
            ctx.route("**/*", route)
        try:
            page = ctx.new_page()
            page.goto(url + "#/m/drive", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            if keep:
                page.screenshot(path=str(pathlib.Path(keep) / f"phone-{spec}.png"))
            m = page.evaluate(PHONE)
        except Exception as e:                                  # noqa: BLE001 — that width's FAIL
            failed += 1
            print(f"FAIL  phone {spec} · the measurement broke: {type(e).__name__}: {str(e)[:160]}")
            ctx.close()
            continue
        problems = []
        if m["hscroll"]:
            problems.append("the page scrolls sideways")
        if not m["search"]:
            problems.append("the search is not whole on the screen")
        if m["appTabs"]:
            problems.append("Files draws its own phone tabs above the office's: two bars")
        failed += 1 if problems else 0
        print(f"{'PASS' if not problems else 'FAIL'}  phone {spec} · desk {m['desk']}, Files own tabs {m['appTabs']}")
        for pr in problems:
            print(f"        {pr}")
        ctx.close()
    return failed

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


def run(url: str, widths: list[str], keep: str, narrow: list[str] = (), phones: list[str] = (),
        static_from: str = "", as_user: str = "", static_only: frozenset = frozenset()) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — run this inside the ui-capture image "
              "(scripts/ui-coverage/Dockerfile), which has it and a Chromium", file=sys.stderr)
        return 2

    failed = 0
    exe = chrome_path()
    route = static_router(static_from, url, as_user, static_only) if (static_from or as_user) else None
    if keep:
        pathlib.Path(keep).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        launch = {"args": ["--no-sandbox"]}
        if exe:
            launch["executable_path"] = exe
        browser = p.chromium.launch(**launch)
        for spec in widths:
            w, _, h = spec.partition("x")
            ctx = browser.new_context(viewport={"width": int(w), "height": int(h or 800)})
            if route:
                ctx.route("**/*", route)
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
            # …and the bar above it is whole (DGO-1637) — once it has settled into its pill (a 350 ms
            # timer, then a 550 ms transition): mid-way it is still wider than it will be
            page.wait_for_timeout(1000)
            problems = bar_problems(page.evaluate(NARROW))
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
        if narrow:
            failed += narrowed(browser, url, list(narrow), keep, route)
        if phones:
            failed += phone(browser, url, list(phones), keep, route)
        browser.close()
    total = len(widths) + len(narrow) + len(phones)
    print(f"\n{total - failed}/{total} widths passed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DOCK_FIT_URL", "http://console:8000/"))
    ap.add_argument("--widths", default=",".join(DEFAULT_WIDTHS))
    ap.add_argument("--narrow", default=",".join(DEFAULT_NARROW),
                    help="widths a desk opened at 1440 is narrowed to, in turn ('' = none)")
    ap.add_argument("--phones", default=",".join(DEFAULT_PHONES),
                    help="phone widths the classic shell is opened at, Files in front ('' = none)")
    ap.add_argument("--static-from", default="",
                    help="a checkout whose console and Files static files are served instead of the console's")
    ap.add_argument("--as-user", default=os.environ.get("DOCK_FIT_AS_USER", ""),
                    help="a proof user named to the console (GET/HEAD only), so it lists apps and opens windows")
    ap.add_argument("--static-only", default="",
                    help="with --static-from: serve only these file names (the files the change under test touched)")
    ap.add_argument("--screenshots", default="")
    a = ap.parse_args()
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]   # noqa: E731
    return run(a.url.rstrip("/") + "/", split(a.widths), a.screenshots, split(a.narrow), split(a.phones),
               a.static_from, a.as_user, frozenset(split(a.static_only)))


if __name__ == "__main__":
    sys.exit(main())
