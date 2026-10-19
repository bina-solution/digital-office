#!/usr/bin/env python3
"""build-fullscreen-mock — the standalone, single-file form of console-fullscreen-mock.

The source (`console-fullscreen-mock.src.html`) LINKS the real stylesheets, which is what keeps it
honest: it cannot drift from the office palette or from the shell's own CSS, because it does not
carry a copy of either. A single self-contained file is what a person can open from anywhere (and
what a headless renderer can shoot without a web server), so this builder inlines them, verbatim.

Output is a BUILD ARTIFACT, deliberately under the gitignored `ci-artifacts/`: the file carries a
byte-for-byte copy of `theme-tokens.css`, and a copy of that block inside a tracked surface is
exactly what gate G27 exists to keep in one place (`--fix` rewrites copies; the artifact would be
read as an unlisted copy). Source is tracked, output is not.

    python3 digital-office/sim/build-fullscreen-mock.py            # → ci-artifacts/fullscreen-mock/
    python3 digital-office/sim/build-fullscreen-mock.py --out DIR

    # …and the form that carries the screen the owner sent: the app area of THAT screenshot, cropped
    # to just the region between the console's top bar and its tab bar (device rows 400…2034 of a
    # 1080×2340 shot), plus the app's own background colour sampled from it.
    python3 digital-office/sim/build-fullscreen-mock.py \
        --app-shot ci-artifacts/fullscreen-mock/screen-app.jpg --app-bg "#151517" \
        --app-centre ci-artifacts/fullscreen-mock/screen-centre.jpg

Without `--app-shot` the mock falls back to its drawn stand-in; with it, the picture inside the
frame IS the owner's screen and only the shell chrome around it is drawn.
"""
from __future__ import annotations

import argparse
import base64
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "console-fullscreen-mock.src.html"
DEFAULT_OUT = REPO / "ci-artifacts" / "fullscreen-mock"

LINK = re.compile(r'<link rel="stylesheet" href="(?P<href>[^"]+)"\s*/>')

# The montage: the three states side by side, each an iframe of the built file — a real one, so each
# frame gets its own viewport width and therefore the shell's own phone media queries apply.
MONTAGE = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"/>
<title>מסך מלא בקונסול — שלושת המצבים</title>
<link rel="stylesheet" href="../../platform-base/bina-ui/theme-tokens.css"/>
<style>
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
     display:flex;gap:26px;padding:26px;align-items:flex-start;justify-content:center}
figure{margin:0;display:flex;flex-direction:column;gap:10px;align-items:center}
figcaption{font-size:14px;font-weight:700}
figcaption small{display:block;font-weight:400;color:var(--muted);margin-top:3px}
iframe{width:390px;height:845px;border:1px solid var(--line);border-radius:var(--radius-lg);
       background:var(--surface);box-shadow:var(--elev-2)}
</style></head><body>
<figure><iframe src="console-fullscreen-mock.html#now" title="כמו היום"></iframe>
  <figcaption>כמו היום<small>topbar 58 + tab bar 60 + מסילת בינה 57</small></figcaption></figure>
<figure><iframe src="console-fullscreen-mock.html#focus" title="מיקוד בקונסול"></iframe>
  <figcaption>מיקוד בקונסול<small>ה-chrome של הלשכה ירד (קיים ועובד)</small></figcaption></figure>
<figure><iframe src="console-fullscreen-mock.html#app" title="וגם בינה בלי ניווט"></iframe>
  <figcaption>וגם בינה בלי ניווט<small>מסילת בינה יורדת, המרכז מקבל את הרוחב</small></figcaption></figure>
<figure><iframe src="console-fullscreen-mock.html#full" title="הכול"></iframe>
  <figcaption>הכול<small>וגם שורת הכתובת וסרגל הניווט</small></figcaption></figure>
</body></html>
"""


def build(out_dir: pathlib.Path, app_shot: pathlib.Path | None = None, app_bg: str = "",
          rail_w: str = "57px", rail_bg: str = "#1a2213",
          rail_gear: pathlib.Path | None = None,
          app_centre: pathlib.Path | None = None) -> tuple[pathlib.Path, list[pathlib.Path]]:
    html = SRC.read_text(encoding="utf-8")
    inlined: list[pathlib.Path] = []

    def swap(m: re.Match) -> str:
        css = (SRC.parent / m.group("href")).resolve()
        if not css.is_file():
            sys.exit(f"missing stylesheet: {m.group('href')} → {css}")
        inlined.append(css.relative_to(REPO))
        body = css.read_text(encoding="utf-8")
        return f"<style data-inlined-from=\"{m.group('href')}\">\n{body}\n</style>"

    html, n = LINK.subn(swap, html)
    if n != 3:
        sys.exit(f"expected 3 linked stylesheets in the source, found {n}")

    if app_shot is not None:
        if not app_shot.is_file():
            sys.exit(f"missing app screenshot: {app_shot}")
        mime = "image/png" if app_shot.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(app_shot.read_bytes()).decode("ascii")
        # `html`, not `:root`: the mock reads both the value and the app's ground back off the root
        # element to decide whether it has a shot at all, and to paint behind it.
        centre = ""
        if app_centre is not None and app_centre.is_file():
            # The crop without the rail. Its width needs no number here: the mock draws it as the
            # frame MINUS the rail (`calc(100% - var(--rail-w))`), so the one measured value is used
            # once. This script therefore needs no image library — only the browser does.
            b64c = base64.b64encode(app_centre.read_bytes()).decode("ascii")
            centre = f'--app-centre:url("data:image/jpeg;base64,{b64c}");' 
        gear = ""
        if rail_gear is not None and rail_gear.is_file():
            gear = ('--rail-gear:url("data:image/png;base64,'
                    + base64.b64encode(rail_gear.read_bytes()).decode("ascii") + '");')
        html = html.replace("</head>", (
            f'<style data-app-shot="{app_shot.name}">html{{--app-shot:url("data:{mime};base64,{b64}");'
            f'--app-bg:{app_bg or "#151517"};--rail-w:{rail_w};--rail-bg:{rail_bg};{centre}{gear}}}'
            "</style>\n</head>"), 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "console-fullscreen-mock.html"
    target.write_text(html, encoding="utf-8")

    montage = out_dir / "montage.html"
    montage.write_text(MONTAGE, encoding="utf-8")
    return target, inlined


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--app-shot", default=None, help="the app area of the screenshot being demonstrated")
    ap.add_argument("--app-bg", default="#151517", help="the app's own background colour, sampled from it")
    ap.add_argument("--rail-w", default="57px", help="the app rail's width, measured off the shot")
    ap.add_argument("--rail-bg", default="#1a2213", help="the rail band's ground, sampled off the shot")
    ap.add_argument("--rail-gear", default=None, help="the gear lifted out of the crop, drawn pinned")
    ap.add_argument("--app-centre", default=None,
                    help="the app area WITHOUT its rail — what the columns-hidden state draws")
    a = ap.parse_args()
    target, inlined = build(pathlib.Path(a.out),
                            pathlib.Path(a.app_shot) if a.app_shot else None, a.app_bg,
                            a.rail_w, a.rail_bg,
                            pathlib.Path(a.rail_gear) if a.rail_gear else None,
                            pathlib.Path(a.app_centre) if a.app_centre else None)
    print(f"{target}  ({target.stat().st_size // 1024} KB)")
    for c in inlined:
        print(f"  inlined {c}")
    print(f"{target.parent / 'montage.html'}  (ארבעת המצבים ליד זה)")
    print("app area: " + (f"{pathlib.Path(a.app_shot).name} (the owner's own screen)"
                          if a.app_shot else "the drawn stand-in (no --app-shot given)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
