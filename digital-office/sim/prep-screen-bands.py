#!/usr/bin/env python3
"""prep-screen-bands — turn a screenshot of the owner's screen into the app-area images a mock needs.

A demo of a display change has to start from THE screen he sent, not from a drawing of it. That
screen, however, carries three kinds of pixels that a mock must not reuse as pixels: the browser's
own chrome, the shell's chrome (which the mock draws from its real CSS), and the app's own rail —
which must run the whole HEIGHT of a taller viewport and therefore cannot come from a crop.

So this script measures and cuts:

  * the app's own area     — device rows between the console's top bar and its tab bar (given, or
                             reported for you to pick: `--list-bands` prints the transitions), saved
                             as the crop the mock is built with;
  * the app rail           — its width (from the first column that stops being the page's ground)
                             and its ground colour, for the band the mock draws full-height;
  * the gear at its bottom — cut out of the crop and saved on its own, so the mock can pin it to
                             wherever the band now ends. The hole it leaves is filled with the band's
                             own colour, which is invisible on a flat band.

    python3 digital-office/sim/prep-screen-bands.py /path/to/shot.jpg --out ci-artifacts/fullscreen-mock \
        --rows 400,2034
    # then:
    # python3 digital-office/sim/build-fullscreen-mock.py --out ci-artifacts/fullscreen-mock \
    #     --app-shot ci-artifacts/fullscreen-mock/screen-app.jpg --app-bg "#151517" \
    #     --rail-gear ci-artifacts/fullscreen-mock/rail-gear.png

Needs Pillow. Run it in a container that has one (`sites-render` does).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("needs Pillow: run this in a container that has it (sites-render does)")


def bands(im: Image.Image, rows: list[int]) -> None:
    """Print where the flat horizontal bands begin and end — how `--rows` is chosen."""
    px = im.load()
    w, h = im.size
    prev = None
    print("y     mean-RGB        spread   (bands are the long runs of a low spread)")
    for y in range(0, h, 2):
        n = 0
        r = g = b = 0
        mn, mx = 255, 0
        for x in range(0, w, 4):
            c = px[x, y]
            r += c[0]; g += c[1]; b += c[2]; n += 1
            v = (c[0] + c[1] + c[2]) // 3
            mn = min(mn, v); mx = max(mx, v)
        mean = (r // n, g // n, b // n)
        spread = mx - mn
        if prev is None or abs(mean[0] - prev[0]) + abs(mean[1] - prev[1]) + abs(mean[2] - prev[2]) > 18:
            print(f"{y:5d} {str(mean):16s} {spread:5d}")
            prev = mean
    print("\nrows given:", rows)


def prepare(shot: pathlib.Path, out: pathlib.Path, rows: tuple[int, int],
            rail_scan_y: int | None, gear_above: int) -> dict:
    im = Image.open(shot).convert("RGB")
    w, h = im.size
    y0, y1 = rows
    px = im.load()
    bg = px[w // 2, min(h - 20, y1 - 60)]              # the app's page ground, where it is empty
    scan_y = rail_scan_y or max(y0 + 20, y1 - 200)

    x_rail = None                                       # where the page ground stops being the rail
    for x in range(w - 1, 0, -1):
        c = px[x, scan_y]
        if abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) <= 10:
            x_rail = x + 1
            break
    if x_rail is None:
        sys.exit("could not find the rail's edge — the app may have no rail; pass --rail-scan-y")
    rail_bg = px[(x_rail + w) // 2, min(h - 10, y1 - 40)]

    lo, hi, top, bot = 10 ** 9, -1, 10 ** 9, -1       # the gear: anything brighter than the band
    for yy in range(max(y0, y1 - gear_above), y1):
        for xx in range(x_rail, w):
            c = px[xx, yy]
            if (c[0] + c[1] + c[2]) // 3 > 70:
                lo = min(lo, xx); hi = max(hi, xx); top = min(top, yy); bot = max(bot, yy)
    pad = 14
    box = (max(x_rail, lo - pad), max(y0, top - pad), min(w, hi + 1 + pad), min(y1, bot + 1 + pad))

    out.mkdir(parents=True, exist_ok=True)
    gear = im.crop(box)
    gear.save(out / "rail-gear.png", optimize=True)

    crop = im.crop((0, y0, w, y1))
    crop.paste(Image.new("RGB", gear.size, rail_bg), (box[0], box[1] - y0))
    crop.save(out / "screen-app.jpg", quality=88, optimize=True)
    # …and the same app WITHOUT its rail: what the columns-hidden state shows is the centre's own
    # pixels, at their own scale, re-centred in the wider slot — nothing is stretched or invented.
    crop.crop((0, 0, x_rail, crop.size[1])).save(out / "screen-centre.jpg", quality=88, optimize=True)

    scale = 390.0 / w
    css = lambda v: round(v * scale)                    # noqa: E731 - device px → CSS px at 390 wide
    return {
        "page bg": f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}",
        "rail bg": f"#{rail_bg[0]:02x}{rail_bg[1]:02x}{rail_bg[2]:02x}",
        "rail w": f"{css(w - x_rail)}px",
        "gear": f"{css(box[2] - box[0])}×{css(box[3] - box[1])}px, {css(y1 - box[3])}px above the bottom",
        "app area": f"{w}×{y1 - y0} device → 390×{css(y1 - y0)} CSS",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("--out", default="ci-artifacts/fullscreen-mock")
    ap.add_argument("--rows", default="", help="y0,y1 of the app's own area (device pixels)")
    ap.add_argument("--list-bands", action="store_true", help="just print the band transitions")
    ap.add_argument("--rail-scan-y", type=int, default=None)
    ap.add_argument("--gear-above", type=int, default=340, help="how far above y1 the gear may sit")
    a = ap.parse_args()

    im = Image.open(a.shot).convert("RGB")
    rows = tuple(int(v) for v in a.rows.split(",")) if a.rows else ()
    if a.list_bands or len(rows) != 2:
        bands(im, list(rows))
        return 0 if a.list_bands else 2
    for name, value in prepare(pathlib.Path(a.shot), pathlib.Path(a.out), rows, a.rail_scan_y,
                               a.gear_above).items():
        print(f"{name:9s} {value}")
    print(f"\nbuilt into {a.out}/screen-app.jpg + screen-centre.jpg + rail-gear.png — now run build-fullscreen-mock.py "
          f"with --app-shot/--rail-gear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
