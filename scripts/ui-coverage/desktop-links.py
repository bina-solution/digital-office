#!/usr/bin/env python3
"""desktop-links — the LIVE half of the console's deep-link behaviour (DGO-501/ui2-060).

    python3 scripts/ui-coverage/desktop-links.py [--url http://console-hp:8000] [--out DIR]

WHY THIS EXISTS. The console's desktop mode is driven by the LINK: a `#/m/<module>/<route>` address
opens (or focuses) that module's window, loads the route the link names, and leaves the address bar
describing what is on screen — in the same tab, on the same desk. Both halves of that sentence were
broken at some point and both were fixed without anything running the proof:
  * the route was dropped for a window on an app's OWN host (fixed 2026-10-08; the browser-free half
    is platform-base/console/test_ext_route.mjs);
  * a link to the CONSOLE clicked INSIDE an app's frame navigated the frame itself — the chat window
    turned into the console and the desk never moved (measured 2026-10-12; the browser-free half is
    platform-base/console/test_frame_links.mjs).
`test_ext_route.mjs` names a live gate `console-deeplink-lint.py --live` that was never written. This
is that run, in the shape the other live readers have (live-ui-map.py, flow-qa.py --url): it drives a
REAL console in a browser of its own and photographs each step.

WHAT IT ASSERTS — the item's acceptance, as far as a browser without a person's sign-in can carry it:
  1. a deep link that arrives WITH the page opens the named module's window, focused, carrying the
     ITEM's route, with the address bar equal to the link;
  2. the same link arriving while the desk is up (only the hash changes — what a click in the chat
     does) moves the same desk to the same window;
  3. pasting the address again does the same;
  4. no new tab: one page in the browser context the whole time;
  5. a link to the console inside an app's frame is taken by the SHELL (the frame does not navigate
     itself away from the app).
The app's own CONTENT inside the frame (that the work item is painted, not the app's home) needs the
office sign-in, which a robot browser does not have; the route the frame is given is asserted instead.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parents[2]


def deployment() -> str:
    """`DEPLOYMENT_NAME` from this checkout's .env — a bare service name is round-robined between the
    two stacks on this engine (gate DGO-544), so the console is dialled by its suffixed name."""
    try:
        for line in open(REPO / ".env", encoding="utf-8"):
            if line.strip().startswith("DEPLOYMENT_NAME="):
                return line.split("=", 1)[1].strip() or "office"
    except OSError:
        pass
    return "office"
# DGO-544 — a real work item in this office's Plane workspace; `#/m/<module>/<route>` is the shape
# the console's own address bar uses (parseModuleHash).
DEEP = ("#/m/project-pln/bina/projects/e13492c5-ae57-4c34-8cd2-85e4aa65bab9"
        "/issues/2e493a24-a188-4af2-be85-32c4e0c5d55e")
OTHER = "#/m/bina"
FAILS: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("  ok    " if ok else "  FAIL  ") + what + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(what)


STATE = """() => {
  const wm = window.BinaDesktop && window.BinaDesktop.wm;
  if (!wm) return {desktop: false};
  const w = wm.focused();
  const of = x => ({mid: x.mid, mode: x.mode, route: x.route || "",
                    extRoute: (x.ext && x.ext.route) || "",
                    open: !!(x.ext && x.ext.open), sleeping: !!x.sleeping});
  return {desktop: window.BinaDesktop.isOn(), hash: location.hash,
          wins: wm.wins().map(of), focused: w ? of(w) : null,
          frames: [...document.querySelectorAll('iframe')].map(f => f.getAttribute('src') || '')};
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=f"http://console-{deployment()}:8000",
                    help="the console, from inside the office network")
    ap.add_argument("--out", default="ci-artifacts/ui-map", help="where the screenshots land")
    ap.add_argument("--chrome", default="/usr/bin/chromium", help="the browser to drive")
    ap.add_argument("--deep", default=DEEP,
                    help="the console deep link to drive the desk with (a work item's own link is "
                         "the acceptance's case)")
    a = ap.parse_args()
    console = a.url.rstrip("/")
    deep = a.deep
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"desktop links — {console}")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chrome,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        opened: list[str] = []
        ctx.on("page", lambda pg: opened.append(pg.url))
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('do-desktop', 'true')")

        print("1. a deep link that arrives WITH the page")
        pg.goto(f"{console}/{deep}", wait_until="load")
        pg.wait_for_timeout(2500)
        s = pg.evaluate(STATE)
        print("   " + json.dumps(s, ensure_ascii=False)[:230])
        check(bool(s.get("desktop")), "desktop mode came up", json.dumps(s)[:200])
        check(s.get("hash") == DEEP, "the address bar is the link that was asked for", s.get("hash", ""))
        check(any(w["mid"] == "ext:project-pln" for w in s.get("wins") or []),
              "the tasks app has a window on the desktop", json.dumps(s.get("wins"))[:250])
        check((s.get("focused") or {}).get("mid") == "ext:project-pln",
              "and that window is the focused one", str(s.get("focused")))
        check("2e493a24" in json.dumps({"r": s.get("focused"), "f": s.get("frames")}),
              "and it carries the ITEM's route, not the app's home",
              json.dumps({"focused": s.get("focused"), "frames": s.get("frames")})[:300])
        pg.screenshot(path=str(out / "desktop-link-1.png"))
        pages_after_first = len(ctx.pages)

        print("\n2. the same link arriving WHILE the desktop is up (a click in the chat)")
        pg.evaluate("h => { location.hash = h; }", OTHER)
        pg.wait_for_timeout(1200)
        pg.evaluate("h => { location.hash = h; }", DEEP)
        pg.wait_for_timeout(2500)
        s2 = pg.evaluate(STATE)
        print("   " + json.dumps(s2, ensure_ascii=False)[:230])
        check(s2.get("hash") == DEEP, "the address bar followed the link", s2.get("hash", ""))
        check((s2.get("focused") or {}).get("mid") == "ext:project-pln",
              "the tasks window came back to the front", str(s2.get("focused")))
        check(any(w["mid"] == "ext:project-pln" for w in s2.get("wins") or []),
              "still one desk, still one window for that app (not a second one)",
              json.dumps(s2.get("wins"))[:250])
        pg.screenshot(path=str(out / "desktop-link-2.png"))

        print("\n3. pasting it again in the same tab")
        pg.goto(f"{console}/{deep}", wait_until="load")
        pg.wait_for_timeout(2500)
        s3 = pg.evaluate(STATE)
        check((s3.get("focused") or {}).get("mid") == "ext:project-pln",
              "same result after a paste", str(s3.get("focused")))

        print("\n4. no new tab was opened by any of it")
        check(len(ctx.pages) <= pages_after_first,
              f"one page in the context ({len(ctx.pages)})", json.dumps(opened)[:250])

        print("\n5. a link INSIDE a framed app — what the chat hands the owner")
        before = pg.evaluate("() => [...document.querySelectorAll('iframe')].length")
        click = pg.evaluate("""(deep) => {
          const wm = window.BinaDesktop.wm;
          const w = wm.wins().find(x => x.mid === 'bina') || wm.wins().find(x => x.frame);
          if (!w || !w.frame) return {err: 'no framed window'};
          let doc = null;
          try { doc = w.frame.contentDocument; } catch (e) { return {err: 'cross-origin: ' + e.message}; }
          if (!doc || !doc.body) return {err: 'no document in the frame yet'};
          const a = doc.createElement('a');
          a.href = location.origin + '/' + deep;
          a.textContent = 'probe';
          doc.body.appendChild(a);
          const inFrame = w.frame.contentWindow.location.href;
          a.click();
          return {ok: true, window: w.mid, frameBefore: inFrame};
        }""", DEEP)
        print("   " + json.dumps(click, ensure_ascii=False)[:300])
        pg.wait_for_timeout(2500)
        s5 = pg.evaluate(STATE)
        after_frame = pg.evaluate("""() => {
          const w = window.BinaDesktop.wm.wins().find(x => x.mid === 'bina');
          try { return w && w.frame ? w.frame.contentWindow.location.href : null; } catch (e) { return 'x-origin'; }
        }""")
        print("   frame now: " + json.dumps(after_frame, ensure_ascii=False)[:220])
        print("   " + json.dumps({"focused": s5.get("focused"), "hash": s5.get("hash")},
                                 ensure_ascii=False)[:300])
        check(len(ctx.pages) <= pages_after_first, "the click opened no new tab",
              json.dumps(opened)[:200])
        check(not isinstance(after_frame, str) or not after_frame.endswith(DEEP),
              "the framed app did not navigate ITSELF to the console address",
              str(after_frame)[-90:])
        check((s5.get("focused") or {}).get("mid") == "ext:project-pln",
              "the shell moved: the tasks window is in front", str(s5.get("focused")))
        pg.screenshot(path=str(out / "desktop-link-3.png"))
        check(before == pg.evaluate("() => [...document.querySelectorAll('iframe')].length"),
              "no extra frame appeared on the desk")
        browser.close()

    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed")
        return 1
    print("the desktop is driven by the link — same tab, same desk, the window it names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
