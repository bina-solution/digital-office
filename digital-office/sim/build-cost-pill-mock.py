#!/usr/bin/env python3
"""build-cost-pill-mock — one self-contained page that shows the price pill on the owner's own screen.

Why a builder rather than a hand-written page: three of the four things the demo must not paraphrase
arrive at build time, from the real sources, so the artifact cannot drift from them.

  * the app area of the owner's screenshot, cut to the region between the console's top bar and its
    tab bar, saved twice — untouched, and with the token chip's rectangle painted out in the screen's
    OWN background colour (sampled beside it, not chosen);
  * the plugin's own stylesheet, lifted verbatim out of `apps/bina-ds/plugins/cost-meter/lib/client.js`
    (`PANEL_CSS`) — the pill in the demo is styled by the product's CSS, not by a copy of it;
  * the plugin's own arithmetic, `lib/pricing.js` and `lib/cost.js`, embedded as module source that
    the page loads as Blob modules — every number in the demo is computed by the code that will run
    in the footer;
  * the office palette, inlined from `platform-base/bina-ui/theme-tokens.css` (the same rule the other
    builders follow: the artifact carries a copy, so it lives under the gitignored `ci-artifacts/`).

    # from the checkout, in a container that has Pillow (sites-render does):
    python3 digital-office/sim/build-cost-pill-mock.py
    python3 digital-office/sim/build-cost-pill-mock.py --shot /path/to/the-owner-screen.jpg

Output (build artifact, gitignored): ci-artifacts/cost-pill-mock/cost-pill-mock.html
"""
from __future__ import annotations

import argparse
import base64
import pathlib
import re
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("needs Pillow: run this in a container that has it (sites-render does)")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "cost-pill-mock.src.html"
PLUGIN = REPO / "apps" / "bina-ds" / "plugins" / "cost-meter"
DEFAULT_OUT = REPO / "ci-artifacts" / "cost-pill-mock"
DEFAULT_SHOT = DEFAULT_OUT / "owner-screen.jpg"

# Device rows of the owner's 1080x2340 shot: the console's top bar ends here, its tab bar starts here.
APP_TOP, APP_BOTTOM = 348, 2004
# The token chip ("1.9 מיליון ⋯") in the same coordinates: x0, y0, x1, y1.
CHIP = (168, 1940, 486, 1998)


def cut(shot: pathlib.Path, out: pathlib.Path) -> tuple[str, str]:
    """Write the owner's app area twice, with and without the token chip; answer both as data URIs."""
    image = Image.open(shot).convert("RGB")
    app = image.crop((0, APP_TOP, image.width, APP_BOTTOM))
    app.save(out / "screen-original.jpg", quality=92)
    # The chip's own rectangle, painted out in the background colour sampled just above it: the row
    # is flat, so this is invisible — and it is what lets the price sit exactly where the tokens were.
    background = image.getpixel(((CHIP[0] + CHIP[2]) // 2, CHIP[1] - 26))
    patched = app.copy()
    for y in range(CHIP[1] - APP_TOP, CHIP[3] - APP_TOP):
        for x in range(CHIP[0], CHIP[2]):
            patched.putpixel((x, y), background)
    patched.save(out / "screen-cost.jpg", quality=92)
    return f"data:image/jpeg;base64,{base64.b64encode((out / 'screen-cost.jpg').read_bytes()).decode()}", \
        f"data:image/jpeg;base64,{base64.b64encode((out / 'screen-original.jpg').read_bytes()).decode()}"


def plugin_css() -> str:
    """The plugin's own style block, read out of its source (never retyped)."""
    source = (PLUGIN / "lib" / "client.js").read_text(encoding="utf8")
    match = re.search(r"const PANEL_CSS = `(?P<css>.*?)`;", source, re.S)
    if match is None:
        sys.exit("could not find PANEL_CSS in the plugin's client.js — the source moved; fix this builder")
    return match.group("css")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", type=pathlib.Path, default=DEFAULT_SHOT)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.shot.exists():
        sys.exit(f"no screenshot at {args.shot} — pass --shot")

    screen, original = cut(args.shot, args.out)
    html = SRC.read_text(encoding="utf8")
    html = html.replace("__PRICING_SRC__", (PLUGIN / "lib" / "pricing.js").read_text(encoding="utf8"))
    html = html.replace("__COST_SRC__", (PLUGIN / "lib" / "cost.js").read_text(encoding="utf8"))
    html = html.replace("__PLUGIN_CSS__", plugin_css())
    html = html.replace("__SHOT_SCREEN__", screen)
    html = html.replace("__SHOT_ORIGINAL__", original)
    # The palette, verbatim, so the drawn shell chrome is the office's and not a second palette.
    tokens = (REPO / "platform-base" / "bina-ui" / "theme-tokens.css").read_text(encoding="utf8")
    html = html.replace(
        '<link rel="stylesheet" href="../../platform-base/bina-ui/theme-tokens.css" />',
        f"<style>\n{tokens}\n</style>",
    )
    target = args.out / "cost-pill-mock.html"
    target.write_text(html, encoding="utf8")
    print(f"{target}  ({target.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
