#!/usr/bin/env python3
"""remote-ui-capture.py — prove the REMOTE mark on every surface, at desktop and phone size.

Why this exists and `bbox ui-map` is not enough: the ui map walks the screens the inventory names
and answers "did this screen render". The subject here is one *state* of a tile — an app that runs
on a LINKED office — and that state only exists while the peer registry holds a record for it. The
map has no view for it, so the mark could regress to a plain local tile and every map would stay
green. This drives the running console, asserts the mark, and captures the pixels.

What it asserts, per viewport:
  * the remote tile is drawn (`.bnv-item.is-remote`) with the office in its row and in its tooltip;
  * an alias that is BOTH local and remote yields TWO rows with two different ids (the two-tiles
    rule — the remote one carries the mark, the local one does not);
  * an office that does not answer reads `… לא זמינה כרגע` in the tooltip and `… לא זמינה` in the
    row, and its mark is the quiet one (`.is-offline`).
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
#: "the capture failed". The RULE is asserted over whatever is actually on the rail.
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
                            or "none — no linked office is publishing apps to this rail"))


def rows(pg) -> list[dict]:
    """Every rail row as the DOM actually holds it — the tile, the office column and the tooltip."""
    return pg.evaluate("""() => [...document.querySelectorAll('#nav .bnv-item')].map(a => ({
        id: a.dataset.id || '', title: a.title || '',
        remote: a.classList.contains('is-remote'),
        offline: a.classList.contains('is-offline'),
        office: (a.querySelector('.bnv-meta')?.dataset.office) || '',
        meta: (a.querySelector('.bnv-meta')?.textContent) || ''}))""")


def open_drawer(pg) -> bool:
    """Make the rail's rows PAINTABLE at 390px so the mark can be photographed.

    A phone puts the menu behind the shell's own drawer (bina-nav.css §4), and this shell does not
    ship the component's burger: on 390px the aside is simply the off-canvas panel the phone rail
    lives in, and the rows inside it are their normal selves the moment it is on screen. So this
    forces the PANEL into the viewport (`transform:none` + `position:fixed` on the aside) and touches
    no row, no colour and no class of the component — the pixels captured are the component's own.
    """
    return bool(pg.evaluate("""() => {
        const n = document.querySelector('#side') || document.querySelector('.bnv');
        if (!n) return false;
        n.classList.add('is-open');
        n.style.display = 'flex';       // at 390px the shell drops the aside entirely
        n.style.transform = 'none';
        n.style.position = 'fixed';
        n.style.insetBlock = '0';
        n.style.insetInlineStart = '0';
        n.style.zIndex = '60';
        n.style.width = 'min(84vw,320px)';
        return true; }"""))


def close_drawer(pg) -> None:
    """Put the phone panel back where the shell keeps it: the launcher capture is the CONTENT area,
    and a forced panel left on screen would cover the tiles it is meant to show."""
    pg.evaluate("""() => {
        const n = document.querySelector('#side') || document.querySelector('.bnv');
        if (!n) return;
        n.classList.remove('is-open');
        for (const k of ['display', 'transform', 'position', 'insetBlock', 'insetInlineStart', 'zIndex', 'width'])
            n.style[k] = ''; }""")


def capture(pg, out: pathlib.Path, profile: str, name: str, selector: str, pad: int = 12) -> None:
    """Screenshot the SUBJECT, not the window.

    A full-window shot of one row is 95% empty page, and three of them (remote / duplicate /
    offline) come out byte-identical — a folder of proofs that prove nothing apart. So the clip is
    the nav column when the subject is a rail row (which is what "in the rail, with its office" has
    to show), and the element's own box otherwise.
    """
    el = pg.query_selector(selector)
    if el:
        el.scroll_into_view_if_needed()
    pg.wait_for_timeout(250)
    path = out / f"{profile}__{name}.png"
    nav = pg.query_selector("#nav .bnv-item") if selector.startswith("#nav") else None
    if nav:
        box = pg.eval_on_selector("#nav", """n => { const r = n.getBoundingClientRect();
            return {x: r.x, y: r.y, width: r.width, height: r.height}; }""")
        pg.screenshot(path=str(path), clip={"x": max(box["x"] - pad, 0), "y": max(box["y"] - pad, 0),
                                            "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})
    elif el:
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
            pg.goto(args.url, wait_until="networkidle")
            # ATTACHED, not visible: at 390px the rail is the component's drawer (bina-nav.css §4)
            # and every row is `display:none` until the drawer is opened — the markup is there, and
            # "the tile exists and is marked" is exactly what is being asserted.
            pg.wait_for_selector("#nav .bnv-item", state="attached", timeout=20000)
            open_drawer(pg)
            if profile == "desktop":
                discover(pg)          # the subjects are this deployment's data, not this file's list
            seen = {r["id"]: r for r in rows(pg)}
            check(f"{profile}/the rail shows remote tiles at all", bool(seen), "no rail rows resolved")

            subj = SUBJECTS.get("remote")
            if subj is None:
                check(f"{profile}/a remote tile is drawn with the mark", False,
                      "no remote tile in the registry")
            else:
                r = seen.get(subj["id"])
                check(f"{profile}/a remote tile is drawn with the mark", bool(r and r["remote"]),
                      f"rows={sorted(seen)}")
                if r:
                    # The tooltip is `<app> · <office LABEL>` and `data-office` is the office's ID.
                    # Asserting the ID appears in the title would fail on a correct tile, so both
                    # halves come from the registry's own record: the label is what a person reads,
                    # the id is what the row carries for anything machine-readable.
                    label = str((subj.get("remote") or {}).get("label") or "")
                    if isinstance((subj.get("remote") or {}).get("label"), dict):
                        lab = subj["remote"]["label"]
                        label = str(lab.get("he") or lab.get("en") or "")
                    check(f"{profile}/the remote tile names its office in words",
                          bool(label) and label in r["title"] and r["office"] == subj["remote"]["office"],
                          f"title={r['title']!r} office={r['office']!r} label={label!r}")
                    capture(pg, out, profile, "remote-tile", f"#nav .bnv-item[data-id='{subj['id']}']")

            dup = SUBJECTS.get("duplicate")
            if dup is None:
                print("  note  no alias runs both here and on a linked office — "
                      "the two-tiles case is not on this rail")
            else:
                local, remote = seen.get(dup["local"]), seen.get(dup["id"])
                check(f"{profile}/a duplicate alias yields TWO rows", bool(local and remote),
                      f"local={bool(local)} remote={bool(remote)}")
                check(f"{profile}/only the remote row of the pair is marked",
                      bool(local and remote and remote["remote"] and not local["remote"]))
                if remote:
                    capture(pg, out, profile, "duplicate-tile", f"#nav .bnv-item[data-id='{dup['id']}']")

            off = SUBJECTS.get("offline")
            if off is None:
                print("  note  no linked office reports ok=false — "
                      "the unreachable case is not on this rail")
            else:
                r = seen.get(off["id"])
                check(f"{profile}/an unreachable office says so",
                      bool(r and r["remote"] and r["offline"]
                           and "לא זמינה כרגע" in r["title"] and "לא זמינה" in r["meta"]),
                      f"title={r and r['title']!r} meta={r and r['meta']!r} offline={r and r['offline']}")
                if r:
                    capture(pg, out, profile, "offline-tile", f"#nav .bnv-item[data-id='{off['id']}']")

            # The launcher is the NO-ROUTE state, and on a phone it is the only place the whole app
            # list is visible. On a DESKTOP the launcher does not exist at all — the rail IS it (owner
            # decision, app.js renderHome) — so this capture is taken at 390, where it does. An office
            # that was never onboarded is landed on the install wizard instead (`boot()`, "first-run
            # landing"), and this deployment's business name comes from apitools, which is not
            # installed here: the endpoint is answered for the page so the tiles draw. Nothing is written.
            close_drawer(pg)
            pg.set_viewport_size(VIEWPORTS["mobile"])
            pg.route(re.compile(r"/api/business(\?.*)?$"), lambda route: route.fulfill(
                status=200, content_type="application/json",
                body='{"onboarded": true, "name": "הלשכה הדיגיטלית", "id": "bina"}'))
            pg.reload(wait_until="networkidle")
            pg.wait_for_selector("#nav .bnv-item", state="attached", timeout=20000)
            # `location.hash = "#/"` and NOT a URL rewrite: the launcher is what `route()` renders for
            # a bare `#/` on a phone (app.js: `if (PHONE.matches && MODULES.length) return renderHome()`),
            # and that runs on a hashchange only. Rewriting the URL in place fires no event and leaves
            # whatever screen was already open — the trap this hit first.
            pg.evaluate("() => { location.hash = '#/'; }")
            pg.wait_for_timeout(1400)
            check(f"{profile}/the launcher marks the remote tile",
                  pg.evaluate("() => !!document.querySelector('.htile.is-remote')"))
            if pg.evaluate("() => !!document.querySelector('.htile.is-remote')"):
                capture(pg, out, profile, "launcher", "#content .htile.is-remote")
            pg.unroute(re.compile(r"/api/business(\?.*)?$"))
            pg.set_viewport_size(vp)
            pg.wait_for_timeout(400)
            check(f"{profile}/the phone bar and the drawer carry the mark",
                  pg.evaluate("""() => !!document.querySelector('.bn-item.is-remote')
                                 || !!document.querySelector('#nav .bnv-item.is-remote')"""))
            if profile == "mobile":
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
