#!/usr/bin/env python3
"""remote-ui-capture.py — prove the REMOTE mark on every surface, at desktop and phone size.

Why this exists and `bbox ui-map` is not enough: the ui map walks the screens the inventory names
and answers "did this screen render". The subject here is one *state* of a tile — an app that runs
on a LINKED office — and that state only exists while the peer registry holds a record for it. The
map has no view for it, so the mark could regress to a plain local tile and every map would stay
green. This drives the running console, asserts the mark, and captures the pixels.

What it asserts, per viewport, on the HOME — the console's navigator since the side rail went (DGO-2132): the
phone's home in its content at 390, and «בית» over the desk at 1440 (the rules of DGO-2122 — one tile per KIND of
app for this business's own herd, and another business's office as a card of its own):
  * a remote app is reachable from the home — its own tile when it is the only copy of its kind here, else
    its office's card (`o:<office>`) — and that tile or card names the office in its tooltip;
  * an alias that runs BOTH here and on a linked office is ONE tile, this office's own, and the other copy
    is on its office's page (`#/o/<office>`);
  * an office that does not answer dims its tile (`.is-offline`) and says `… לא זמינה כרגע` in the tooltip.
Non-zero exit on the first failed assertion, so it can gate.

    python3 scripts/remote-ui-capture.py                       # http://console:8000, /tmp/out
    python3 scripts/remote-ui-capture.py --url http://console:8000 --out ci-artifacts/remote-ui

Needs Playwright + a Chromium. In this repo that is the `ui-capture` image (see
scripts/ui-coverage/Dockerfile), reached on the stack network because the console is a service name:

    docker run --rm --network traefik-network -v "$PWD":/repo -w /repo \
      -e UI_OWN_BROWSER=1 -e UI_CHROME_BIN=/usr/bin/chromium ui-capture:latest \
      python3 scripts/remote-ui-capture.py --url http://console:8000
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):          # Hebrew on a Windows console (cp1255) raises without it
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}
#: What the peer rows are, filled from the LIVE registry at run time. Nothing here names an office:
#: the peer records are the deployment's own data — they appear when an office is linked and vanish
#: when it is not — and a script that hard-codes `hp-laptop` turns "the office was unlinked" into
#: "the capture failed". The RULE is asserted over whatever is actually on the home.
SUBJECTS: dict[str, dict] = {}

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name + (f" — {detail}" if detail else ""))


def chrome() -> str | None:
    return os.getenv("UI_CHROME_BIN") or next(
        (str(g) for g in sorted(pathlib.Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)


def discover(pg) -> None:
    """Ask the live registry which remote tiles exist, and pick the three subjects from it.

    The three cases the feature has to get right, selected by what the data says rather than by name:
    a plain remote tile, an alias that runs BOTH here and on a linked office (the two-tiles rule),
    and an office whose record says it did not answer (`ok: false`). A case the deployment does not
    have is reported as a note, not as a failure — an office that is not linked is not a defect.
    """
    mods = pg.evaluate("""() => fetch('/api/modules').then(r => r.json())
        .then(d => (d.modules || []).map(m => ({id: m.id, name: m.name, remote: m.remote || null})))""")
    remote = [m for m in mods if isinstance(m.get("remote"), dict)]
    ids = {m["id"] for m in mods}
    SUBJECTS.clear()
    if remote:
        SUBJECTS["remote"] = remote[0]
    for m in remote:                                  # an alias that also exists locally
        alias = str(m["id"]).split(".")[0]
        if alias in ids and alias != m["id"]:
            SUBJECTS["duplicate"] = {**m, "local": alias}
            break
    for m in remote:                                  # an office that did not answer
        if m["remote"].get("ok") is False:
            SUBJECTS["offline"] = m
            break
    print("  subjects: " + (", ".join(f"{k}={v['id']}" for k, v in SUBJECTS.items())
                            or "none — no linked office is publishing apps to this home"))


def open_home(pg, office: str = "") -> None:
    """The home, open: «בית» over the desk on a computer (desktop.js, DGO-2132), the phone's home in its content.
    With `office`, that machine's or office's own page (`#/o/<office>`)."""
    pg.evaluate("""o => { if (window.BinaDesktop && BinaDesktop.isOn()) BinaDesktop.home(o || undefined);
                          else location.hash = o ? '#/o/' + encodeURIComponent(o) : '#/'; }""", office)
    pg.wait_for_timeout(1000)


def rows(pg) -> list[dict]:
    """Every place of the open home as the DOM holds it — an app's tile (its id) or a machine's or office's card
    (`o:<office>`), with its address and its tooltip."""
    # `said`: the tooltip AND the words drawn on it — an office's card writes «לא זמינה כרגע» in its own line, not in
    # its tooltip (which is the office's name), and a tile writes it under its name as well as in its tooltip.
    return pg.evaluate("""() => [...document.querySelectorAll('.lt[data-hid], .lo[data-office]')].map(a => ({
        id: a.dataset.hid || 'o:' + a.dataset.office, title: a.title || '', href: a.getAttribute('href') || '',
        said: (a.title || '') + ' ' + (a.innerText || ''),
        offline: a.classList.contains('is-offline') || a.classList.contains('is-off')}))""")


def place(item_id: str) -> str:
    """The selector of one place on the home: an app's tile, or an office's card."""
    return f".lo[data-office='{item_id[2:]}']" if item_id.startswith("o:") else f".lt[data-hid='{item_id}']"


def where(seen: dict, subj: dict) -> dict | None:
    """The place a remote app is reached by: its own tile, or its office's card (DGO-2122)."""
    return seen.get(subj["id"]) or seen.get("o:" + str((subj.get("remote") or {}).get("office") or ""))


def capture(pg, out: pathlib.Path, profile: str, name: str, selector: str, pad: int = 12) -> None:
    """Screenshot the SUBJECT, not the window: the element's own box (a tile, a card, the home), so three proofs
    (remote / duplicate / offline) cannot come out as the same picture of a page."""
    el = pg.query_selector(selector)
    if el:
        el.scroll_into_view_if_needed()
    pg.wait_for_timeout(250)
    path = out / f"{profile}__{name}.png"
    if el:
        box = el.bounding_box() or {}
        if box:
            pg.screenshot(path=str(path), clip={"x": max(box["x"] - pad, 0), "y": max(box["y"] - pad, 0),
                                                "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})
        else:
            pg.screenshot(path=str(path))
    else:
        pg.screenshot(path=str(path))
    print(f"  png   {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://console:8000")
    ap.add_argument("--out", default="/tmp/remote-ui")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome(), args=["--no-sandbox"])
        for profile, vp in VIEWPORTS.items():
            print(f"\n{profile.upper()}  {vp['width']}x{vp['height']}  → {args.url}")
            pg = browser.new_page(viewport=vp)
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            # An office that was never onboarded is landed on the install wizard instead (`boot()`, "first-run
            # landing"), and this deployment's business name comes from apitools, which may not be installed:
            # the endpoint is answered for the page so the tiles draw. Nothing is written.
            pg.route(re.compile(r"/api/business(\?.*)?$"), lambda route: route.fulfill(
                status=200, content_type="application/json",
                body='{"onboarded": true, "name": "הלשכה הדיגיטלית", "id": "bina"}'))
            pg.goto(args.url, wait_until="networkidle")
            pg.wait_for_timeout(1200)
            desk = bool(pg.evaluate("() => !!(window.BinaDesktop && BinaDesktop.isOn())"))
            check(f"{profile}/{'a computer is the desk' if profile == 'desktop' else 'a phone is the home and its bar'}",
                  desk == (profile == "desktop"), f"desk={desk}")
            if profile == "desktop":
                discover(pg)          # the subjects are this deployment's data, not this file's list
            open_home(pg)
            seen = {r["id"]: r for r in rows(pg)}
            check(f"{profile}/the home draws its tiles", any(not k.startswith("o:") for k in seen),
                  "no tile resolved")

            subj = SUBJECTS.get("remote")
            if subj is None:
                check(f"{profile}/a remote app is reachable from the home", False,
                      "no remote tile in the registry")
            else:
                r = where(seen, subj)
                check(f"{profile}/a remote app is reachable from the home — its tile or its office's card",
                      bool(r), f"places={sorted(seen)}")
                if r:
                    # The tooltip names the office by its LABEL — what a person reads — taken from the
                    # registry's own record, as the place's address carries the id.
                    label = str((subj.get("remote") or {}).get("label") or "")
                    if isinstance((subj.get("remote") or {}).get("label"), dict):
                        lab = subj["remote"]["label"]
                        label = str(lab.get("he") or lab.get("en") or "")
                    check(f"{profile}/the home names its office in words",
                          bool(label) and label in r["title"], f"title={r['title']!r} label={label!r}")
                    capture(pg, out, profile, "remote-tile", place(r["id"]))
                # …and a linked office outside the herd is a card of its own, never tiles mixed into the home
                foreign = [m for m in [subj] + [SUBJECTS.get(k) for k in ("duplicate", "offline")]
                           if m and not (m.get("remote") or {}).get("herd")]
                if foreign:
                    office = str(foreign[0]["remote"].get("office") or "")
                    check(f"{profile}/a linked office outside the herd is a card on the home",
                          ("o:" + office) in seen, f"office={office!r} places={sorted(seen)}")

            dup = SUBJECTS.get("duplicate")
            if dup is None:
                print("  note  no alias runs both here and on a linked office — "
                      "the one-tile-per-kind case is not on this home")
            else:
                local, remote = seen.get(dup["local"]), seen.get(dup["id"])
                check(f"{profile}/an alias that runs here and on a linked office is ONE tile, this office's own",
                      bool(local) and not remote, f"local={bool(local)} remote={bool(remote)}")
                office = str((dup.get("remote") or {}).get("office") or "")
                open_home(pg, office)
                check(f"{profile}/…and the other copy is on its office's page",
                      pg.evaluate("id => !!document.querySelector(`.lt[data-hid='${id}']`)", dup["id"]))
                open_home(pg)

            off = SUBJECTS.get("offline")
            if off is None:
                print("  note  no linked office reports ok=false — "
                      "the unreachable case is not on this home")
            else:
                r = where(seen, off)
                check(f"{profile}/an unreachable office says so: its tile or card dims and says it in words",
                      bool(r and r["offline"] and "לא זמינה כרגע" in r["said"]),
                      f"said={r and r['said']!r} offline={r and r['offline']}")
                if r:
                    capture(pg, out, profile, "offline-tile", place(r["id"]))

            home = ".dk-home .dk-more-box" if desk else "#content .lh"
            if pg.query_selector(home):
                capture(pg, out, profile, "home", home)
            pg.unroute(re.compile(r"/api/business(\?.*)?$"))
            if desk:
                check(f"{profile}/the dock starts at «בית»",
                      pg.evaluate("""() => { const b = document.querySelector('.dk-dock > *');
                                     return !!b && (b.getAttribute('aria-label') || '').startsWith('בית'); }"""))
            else:
                check(f"{profile}/the phone bar starts at «בית»",
                      pg.evaluate("""() => { const b = document.querySelector('.bottomnav .bn-item');
                                     return !!b && b.getAttribute('href') === '#/'; }"""))
                capture(pg, out, profile, "bottom-bar", ".bottomnav")
            check(f"{profile}/no JS error while rendering remote tiles",
                  not [e for e in errors if "Failed to load resource" not in e], "; ".join(errors[:3]))
            pg.close()
        browser.close()

    (out / "remote-ui-capture.json").write_text(
        json.dumps({"url": args.url, "viewports": VIEWPORTS, "subjects": SUBJECTS,
                   "failures": FAILURES}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'OK — every remote surface marked'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
