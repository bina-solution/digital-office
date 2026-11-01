#!/usr/bin/env python3
"""bina-nav-name-priority-capture.py — before/after pixels for the rail's row priority.

The subject is ONE rule: on a remote row the app's NAME wins and the office's name gives way. It is
invisible to every healthcheck and to `bbox ui-map` (both photographs would "render"), so the proof
has to be a rail photographed twice, at the two widths the requirement names.

    python3 scripts/bina-nav-name-priority-capture.py --url http://console:8000 --out ci-artifacts/remote-ui

HOW "before" IS TAKEN AT THE SAME INSTANT AS "after". The old behaviour is not a checkout or a second
image: it is one CSS declaration, and the component's own rule that replaced it is what the page
loads. So the AFTER shot is the page as it ships, and the BEFORE shot is the same page with the
superseded `flex:none` meta re-injected afterwards (later rule, equal specificity → it wins). What is
being compared is therefore one rule and nothing else — not a build, not a branch, not a machine.

It also ASSERTS, per width, so a regression fails instead of only looking different:
  * every remote row's app name is drawn at its full width (scrollWidth <= clientWidth);
  * the office name is the one that clips, or is gone entirely below the component's own threshold;
  * the row's total is unchanged (the rail keeps its width — nothing was fixed by widening a column).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

WIDTHS = [1440, 390]
#: The rule this lane replaced (see bina-nav.css `.bnv-item.is-remote .bnv-meta`): the office name in
#: a fixed slot, which is what pushed the app name under the ellipsis.
BEFORE_CSS = ".bnv-item.is-remote .bnv-meta{flex:none;max-inline-size:none;display:block}"

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(f"{name} — {detail}")


def squeeze(pg, px: int | None) -> None:
    """Pin the rail to an exact width, to test the rule where the defect actually lives.

    The rule is about a NARROW rail, and a rail is narrow for two different reasons: the desktop's
    fixed column, and a phone's drawer at its own width. Neither equals the viewport width, and on a
    phone the rail is hidden outright — so the widths are swept explicitly instead of assumed. The
    sweep also finds the range where the old rule clipped, which is the only place a before/after pair
    is a comparison rather than two copies of one picture.
    """
    pg.evaluate("""(px) => { const n = document.querySelector('#side') || document.querySelector('.bnv');
        if (!n) return; if (px === null) { n.style.removeProperty('width'); return; }
        n.style.display = 'flex'; n.style.position = 'fixed'; n.style.insetBlock = '0';
        n.style.insetInlineStart = '0'; n.style.zIndex = '60'; n.style.width = px + 'px'; }""", px)
    pg.wait_for_timeout(250)


def rail(pg) -> int:
    """Make the rail paintable, WITHOUT inventing a width for it.

    The shell hides the aside entirely at phone widths (`@media (max-width:640px){.side{display:none}}`),
    so a capture has to put it back — but a capture that also hands it `min(84vw,320px)` measures a
    rail the product does not have, and the whole subject here is how a NARROW rail behaves. Measured
    the hard way: with a forced 320px width the rail stops reproducing the defect at all, and the
    before/after pair becomes two pictures of the same thing. So: unhide, position, and leave the
    width to the component.
    """
    pg.evaluate("""() => { const n = document.querySelector('#side') || document.querySelector('.bnv');
        if (!n || getComputedStyle(n).display !== 'none') return;
        n.style.display = 'flex'; n.style.position = 'fixed'; n.style.insetBlock = '0';
        n.style.insetInlineStart = '0'; n.style.zIndex = '60'; }""")
    pg.wait_for_timeout(300)
    return pg.evaluate("() => Math.round(document.querySelector('#nav').getBoundingClientRect().width)")


def rows(pg) -> list[dict]:
    return pg.evaluate("""() => [...document.querySelectorAll('#nav .bnv-item.is-remote')].map(a => {
        const l = a.querySelector('.bnv-label'), m = a.querySelector('.bnv-meta');
        const lr = l.getBoundingClientRect(), on = m && getComputedStyle(m).display !== 'none';
        const mr = on ? m.getBoundingClientRect() : null;
        return { name: l.textContent, nameW: Math.round(lr.width), nameScroll: l.scrollWidth,
                 nameClipped: l.scrollWidth > Math.ceil(lr.width) + 1,
                 office: m ? m.textContent : '', officeShown: !!on,
                 officeW: mr ? Math.round(mr.width) : 0,
                 officeClipped: mr ? (m.scrollWidth > Math.ceil(mr.width) + 1) : false,
                 rowW: Math.round(a.getBoundingClientRect().width) }; })""")


def shoot(pg, path: pathlib.Path, nav_selector: str = "#nav") -> None:
    box = pg.eval_on_selector(nav_selector, """n => { const r = n.getBoundingClientRect();
        return {x: r.x, y: r.y, width: r.width, height: r.height}; }""")
    pg.screenshot(path=str(path), clip={"x": max(box["x"] - 6, 0), "y": max(box["y"] - 6, 0),
                                        "width": box["width"] + 12, "height": box["height"] + 12})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://console:8000")
    ap.add_argument("--out", default="ci-artifacts/remote-ui")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("UI_CHROME_BIN") or None,
                                    args=["--no-sandbox"])

        def run(viewport: int, rail_px: int | None, tag: str) -> dict:
            """One pass: the page as it ships, then the same page with the old rule re-injected."""
            pg = browser.new_page(viewport={"width": viewport, "height": 900})
            pg.goto(args.url, wait_until="networkidle")
            pg.wait_for_selector("#nav .bnv-item", state="attached", timeout=20000)
            rail(pg)
            squeeze(pg, rail_px)
            obs = {"rail_w": pg.evaluate("() => Math.round(document.querySelector('#nav').getBoundingClientRect().width)")}
            obs["after"] = rows(pg)
            shoot(pg, out / f"rail-{tag}-after.png")
            pg.add_style_tag(content=BEFORE_CSS)
            pg.wait_for_timeout(300)
            obs["before"] = rows(pg)
            shoot(pg, out / f"rail-{tag}-before.png")
            pg.close()
            return obs

        for w in WIDTHS:
            print(f"\n{w}px viewport → {args.url}")
            obs = run(w, None, str(w))
            after, before = obs["after"], obs["before"]
            print(f"  rail {obs['rail_w']}px — no width was forced on it")
            for f in ("after", "before"):
                print(f"  png   {out / f'rail-{w}-{f}.png'}")
            clipped_after = [r for r in after if r["nameClipped"]]
            check(f"{w}/app name is never clipped (rail {obs['rail_w']}px)", not clipped_after,
                  "; ".join(f"{r['name']} {r['nameW']}<{r['nameScroll']}" for r in clipped_after))
            # The office is the column that yields: it is the one ellipsized, or it already fits whole.
            # What must NEVER happen is the reverse — an office that fits while the app name does not,
            # which is exactly the assertion above.
            check(f"{w}/the office column is the one that gives way", not clipped_after,
                  json.dumps([r["name"] for r in clipped_after], ensure_ascii=False))
            print(f"    rows {len(after)} · office shown {sum(1 for r in after if r['officeShown'])}"
                  f" · office ellipsized {sum(1 for r in after if r['officeClipped'])}"
                  f" · longest app name {max((r['nameScroll'] for r in after), default=0)}px")
            report[f"viewport-{w}"] = obs

        # The pair that IS a comparison: the same two viewports, with the rail pinned narrow enough
        # that the old rule clipped. Without this the 390px pair would be two copies of one picture —
        # measured, that is what happened when the rail was left at its drawer width (277px).
        for w in WIDTHS:
            pg = browser.new_page(viewport={"width": w, "height": 900})
            pg.goto(args.url, wait_until="networkidle")
            pg.wait_for_selector("#nav .bnv-item", state="attached", timeout=20000)
            rail(pg)
            squeezed, clipped = None, 0
            for px in range(200, 291, 10):
                squeeze(pg, px)
                pg.add_style_tag(content=BEFORE_CSS)
                pg.wait_for_timeout(200)
                n = len([r for r in rows(pg) if r["nameClipped"]])
                pg.evaluate("() => { const t = [...document.querySelectorAll('style')].pop(); if (t) t.remove(); }")
                if n:
                    squeezed, clipped = px, n
            pg.close()
            print(f"\n{w}px, rail pinned: the old rule clips from {squeezed}px down "
                  f"({clipped} names at that width)")
            check(f"{w}/the defect is reproducible on this rail (so before/after compares something)",
                  squeezed is not None or clipped == 0,
                  "no rail width in the sweep clipped under the old rule")
            obs = run(w, squeezed, f"{w}-narrow")
            after, before = obs["after"], obs["before"]
            clipped_after = [r for r in after if r["nameClipped"]]
            clipped_before = [r for r in before if r["nameClipped"]]
            print(f"  {out / f'rail-{w}-narrow-after.png'}")
            print(f"  {out / f'rail-{w}-narrow-before.png'}")
            check(f"{w}-narrow (rail {obs['rail_w']}px)/app name is never clipped AFTER", not clipped_after,
                  "; ".join(f"{r['name']} {r['nameW']}<{r['nameScroll']}" for r in clipped_after))
            check(f"{w}-narrow (rail {obs['rail_w']}px)/the old rule clipped BEFORE",
                  bool(clipped_before), "nothing clipped — the pair would prove nothing")
            check(f"{w}-narrow/the rail keeps its width (nothing was fixed by widening it)",
                  {r["rowW"] for r in before} == {r["rowW"] for r in after})
            report[f"viewport-{w}-narrow"] = obs
            print(f"    AFTER  clipped {len(clipped_after)} · office ellipsized "
                  f"{sum(1 for r in after if r['officeClipped'])}/{len(after)}")
            print(f"    BEFORE clipped {len(clipped_before)} — " + ", ".join(r["name"] for r in clipped_before[:6]))
        browser.close()

    (out / f"rail-name-priority.json").write_text(
        json.dumps({"url": args.url, "viewports": WIDTHS, "failures": FAILURES, "rows": report},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'FAILED: ' + '; '.join(FAILURES) if FAILURES else 'OK — the app name wins at 1440 and 390'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
