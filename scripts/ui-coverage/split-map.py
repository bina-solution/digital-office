#!/usr/bin/env python3
"""split-map.py — slice the tall composite ui-map.png into upload-safe strips.

The composed map is one very tall PNG (~5230x20320). Chat / file-share uploads reject images that
tall (they cap height, not width), so to SHARE the map, cut it top-to-bottom into JPEG strips no
taller than --max-h. Parts stack vertically back into the whole map. The full-res PNG is untouched.

Usage:  python3 scripts/ui-coverage/split-map.py
        python3 scripts/ui-coverage/split-map.py --src ci-artifacts/ui-map/ui-map.png --max-h 2900
"""
import argparse
import math
import os
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # the map is intentionally huge; not a decompression bomb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="ci-artifacts/ui-map/ui-map.png", help="composite map PNG")
    ap.add_argument("--outdir", default="ci-artifacts/ui-map/strips", help="where to write strips")
    ap.add_argument("--max-h", type=int, default=2900, help="max strip height px (upload-safe)")
    ap.add_argument("--quality", type=int, default=86, help="JPEG quality")
    a = ap.parse_args()

    im = Image.open(a.src).convert("RGB")
    w, h = im.size
    os.makedirs(a.outdir, exist_ok=True)
    n = math.ceil(h / a.max_h)
    written = []
    for i in range(n):
        y0, y1 = i * a.max_h, min(h, (i + 1) * a.max_h)
        if y1 - y0 < 8:  # skip a sub-8px sliver at the bottom
            continue
        p = os.path.join(a.outdir, f"ui-map-part-{i + 1:02d}-of-{n:02d}.jpg")
        im.crop((0, y0, w, y1)).save(p, "JPEG", quality=a.quality, optimize=True)
        written.append(p)

    print(f"{len(written)} strip(s) written to {a.outdir}/  (source {w}x{h})")
    for p in written:
        print(" ", p)


if __name__ == "__main__":
    main()
