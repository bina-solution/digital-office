#!/usr/bin/env python3
"""test_dialog_bound — is a dialog bounded by its window, with its title still in sight?

    python3 platform-base/bina-ui/test_dialog_bound.py [--old-rev HEAD] [--out <dir>]

DGO-518 and DGO-519, measured instead of described:

  · INDOX's dialog card had no height bound at all, so in a short window the title and the buttons
    began OUTSIDE the frame and there was nothing to scroll.
  · The console's cards were bounded, but scrolled WHOLE — the title and the close button went up
    with the content, which is the same defect with a nicer first impression.

Both are now the same stamped rule (`@bina-modal`, source `platform-base/bina-ui/bina-ui.css`), so
this measures the RULE at both of its ends: for every surface that carries it, in a real Chromium, at
the smallest window the platform's desktop mode drags to (380x260) and at a comfortable one:

  1. the card fits inside the window (nothing outside the frame);
  2. after scrolling the card's content to the bottom, the title AND the close button are still
     inside the window — the point of sticking the header;
  3. the close button is the topmost element at its own centre, so it can actually be pressed.

TWO ARMS. `--old-rev` (default HEAD) gives the same measurement against the stylesheet as it was, so
the run reports what the defect WAS beside what it is; the assertions are only on the working copy.

Guarded for a machine that cannot run it: says "not run" and exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from html import escape

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                     # pragma: no cover - host without it
    print("not run: no playwright here (the ui-capture image has it)")
    sys.exit(0)

REPO = pathlib.Path(__file__).resolve().parents[2]

#: every surface that carries the stamped block — the same list the gate holds (`@bina-modal`).
SURFACES = [
    "platform-base/bina-ui/bina-ui.css",
    "platform-base/console/static/style.css",
    "apps/indox/app/webapp/src/index.css",
    "apps/computers/static/index.html",
    "apps/dgo-extend/static/index.html",
]

#: what a dialog holds when it is too tall for the window: the case the two items were filed about.
FILLER = "".join(f"<p>שורה {i} — מה שהדיאלוג הזה מחזיק, ארוך מן החלון.</p>" for i in range(1, 41))

PAGE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>{name}</title>
<style>{css}</style>
<style>body{{margin:0;font-family:system-ui,sans-serif}}
/* the harness's own furniture, so a missing rule here is never mistaken for the app's */</style>
</head><body>
<div class="modal-ov"><div class="modal" id="card">
  <div class="modal-h"><h3>מצב החיבורים</h3><button class="ghost" id="x" aria-label="סגירה">✕</button></div>
  <div id="body">{filler}</div>
</div></div>
</body></html>"""

PROBE = """() => {
  const card = document.getElementById('card'), h = document.querySelector('.modal-h');
  const x = document.getElementById('x'), vh = innerHeight, vw = innerWidth;
  const r = el => { const b = el.getBoundingClientRect();
                    return {top: Math.round(b.top), bottom: Math.round(b.bottom),
                            left: Math.round(b.left), right: Math.round(b.right),
                            w: Math.round(b.width), h: Math.round(b.height)}; };
  card.scrollTop = card.scrollHeight;               // the bottom of a long dialog
  const rb = r(document.getElementById('body'));
  const hit = document.elementFromPoint(...(() => { const b = x.getBoundingClientRect();
                                                    return [b.left + b.width / 2, b.top + b.height / 2]; })());
  return {viewport: {w: vw, h: vh}, card: r(card), header: r(h), close: r(x),
          card_scrollable: card.scrollHeight > card.clientHeight + 1,
          scrolled_to: card.scrollTop,
          close_is_topmost: !!hit && (hit.id === 'x' || x.contains(hit))};
}"""


def source_at(rev: str, rel: str) -> str | None:
    try:
        r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


def measure(pw, out: pathlib.Path, name: str, css: str, sizes: list[tuple[int, int]]) -> dict:
    page_file = out / f"{name}.html"
    page_file.write_text(PAGE.format(css=css, filler=FILLER, name=escape(name)), encoding="utf-8")
    got: dict = {"surface": name, "css_bytes": len(css), "sizes": {}}
    b = pw.chromium.launch(executable_path=os.environ.get("DIALOG_CHROME", "/usr/bin/chromium"),
                           args=["--no-sandbox", "--disable-dev-shm-usage"])
    try:
        for w, h in sizes:
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(page_file.as_uri(), wait_until="load", timeout=30000)
            pg.wait_for_timeout(120)
            got["sizes"][f"{w}x{h}"] = pg.evaluate(PROBE)
            pg.screenshot(path=str(out / f"{name}-{w}x{h}.png"))
            pg.close()
    finally:
        b.close()
    return got


def verdict(m: dict) -> list[str]:
    """everything wrong with this measurement, in the words of the two items."""
    bad = []
    for size, g in m["sizes"].items():
        vw, vh = g["viewport"]["w"], g["viewport"]["h"]
        c, hd, x = g["card"], g["header"], g["close"]
        if c["top"] < -1 or c["left"] < -1 or c["bottom"] > vh + 1 or c["right"] > vw + 1:
            bad.append(f"{size}: the card runs outside the window (card {c}, window {vw}x{vh})")
        if hd["top"] < -1 or hd["bottom"] > vh + 1:
            bad.append(f"{size}: the title is outside the window (header {hd})")
        if x["top"] < -1 or x["bottom"] > vh + 1 or x["left"] < -1 or x["right"] > vw + 1:
            bad.append(f"{size}: the close button is outside the window (x {x})")
        if not g["close_is_topmost"]:
            bad.append(f"{size}: the close button is covered — nothing to press at its own centre")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-rev", default="HEAD", help="the revision the before-arms are taken from")
    ap.add_argument("--old-root", default="", help="a checkout to take them from instead (no git here)")
    ap.add_argument("--out", default=os.environ.get("DIALOG_OUT", "/tmp/dialog-bound"))
    args = ap.parse_args()
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sizes = [(380, 260), (1000, 760)]
    report: dict = {"surfaces": [], "old_rev": args.old_rev}

    with sync_playwright() as pw:
        for rel in SURFACES:
            new_css = (REPO / rel).read_text(encoding="utf-8")
            old_css = None
            if args.old_root:
                p = pathlib.Path(args.old_root) / rel
                old_css = p.read_text(encoding="utf-8") if p.exists() else None
            if old_css is None:
                old_css = source_at(args.old_rev, rel)
            name = rel.replace("/", "__")
            print(f"── {rel}")
            if old_css and old_css != new_css:
                before = measure(pw, out, f"old-{name}", old_css, sizes)
                report["surfaces"].append({"before": before})
                bad = verdict(before)
                print(f"   BEFORE ({args.old_rev}): " +
                      ("defective — " + "; ".join(bad) if bad else "already bounded and stuck"))
            else:
                report["surfaces"].append({"before": None})
                print(f"   BEFORE: not measured (no differing revision at {args.old_rev})")
            after = measure(pw, out, f"new-{name}", new_css, sizes)
            report["surfaces"][-1]["after"] = after
            report["surfaces"][-1]["surface"] = rel
            bad = verdict(after)
            for size, g in after["sizes"].items():
                print(f"   AFTER  {size}: card {g['card']['w']}x{g['card']['h']} at y={g['card']['top']}"
                      f"..{g['card']['bottom']}, header y={g['header']['top']}, scrollable="
                      f"{g['card_scrollable']}, close pressable={g['close_is_topmost']}")
            if bad:
                print("   FAIL")
                for b in bad:
                    print(f"     · {b}")
            else:
                print("   PASS — bounded by the window, title and close button in sight")

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [s for s in report["surfaces"] if verdict(s["after"])]
    print(f"\n{len(report['surfaces']) - len(failed)}/{len(report['surfaces'])} surface(s) bound their"
          f" dialog; report: {out}/report.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
