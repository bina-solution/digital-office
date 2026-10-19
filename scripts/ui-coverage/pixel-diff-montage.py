#!/usr/bin/env python3
"""One image showing every panel's sim↔live difference, marked.

pixel-diff.py already writes a per-panel sheet and an index.html. That is the right artefact for
drilling in, and the wrong one for the question people actually ask first — *where does live not
match the sim?* Answering it should not require opening 43 files or a browser.

So this composes the per-panel LIVE renders into a single contact sheet with each differing region
boxed in red, ordered worst-first, and the diff percentage printed on every tile. One picture, and
the eye goes straight to the problems.

Choices worth stating:

* **Live is the base, not the sim.** The boxes mark where LIVE diverges, so the thing being judged is
  the thing you are looking at. Showing the sim underneath would make the reader mentally invert
  every box.
* **Worst first.** Sorted by差 percentage, so the top-left tile is always the biggest problem. A
  panel-order montage buries a 55% failure between two 1% passes.
* **UNPAIRED panels are included, greyed, and labelled.** Dropping them would quietly shrink the
  denominator — the same dishonesty as a coverage number that ignores what it could not measure.
"""
import argparse
import json
import pathlib
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow required: pip install pillow")

REPO = pathlib.Path(__file__).resolve().parents[2]


def load_font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"):
            p = pathlib.Path(base) / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="a ci-artifacts/pixel-diff/<run> directory")
    ap.add_argument("--out", default=None)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--tile", type=int, default=460, help="tile width in px")
    a = ap.parse_args()

    run = pathlib.Path(a.run)
    if not run.is_absolute():
        run = REPO / run
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    rows = summary["rows"]

    # worst first; UNPAIRED sink to the end because they carry no percentage to rank by
    def rank(r):
        if r.get("verdict") == "UNPAIRED":
            return (1, 0.0)
        return (0, -(r.get("pct") or 0.0))

    rows = sorted(rows, key=rank)

    tw = a.tile
    th = int(tw * 0.62) + 34            # image area + caption strip
    cols = a.cols
    rowsn = (len(rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rowsn * th), "#12181d")
    d = ImageDraw.Draw(sheet)
    f_cap = load_font(13)
    f_pct = load_font(15)

    VERDICT_COLOR = {"MAJOR": "#e5484d", "DIFFERS": "#f5a524", "CLOSE": "#3fb950",
                     "IDENTICAL": "#3fb950", "UNPAIRED": "#6e7681", "SIZE": "#a371f7"}

    for i, r in enumerate(rows):
        cx, cy = (i % cols) * tw, (i // cols) * th
        verdict = r.get("verdict", "?")
        colour = VERDICT_COLOR.get(verdict, "#6e7681")
        img_h = th - 34

        # The base image is the LIVE render when we have one; UNPAIRED tiles show the sim greyed so
        # the reader can still see WHAT is missing rather than an empty box.
        src = r.get("live") or r.get("sim")
        tile = None
        if src:
            p = pathlib.Path(src)
            if not p.is_absolute():
                p = REPO / p
            if p.exists():
                try:
                    tile = Image.open(p).convert("RGB")
                except OSError:
                    tile = None
        if tile is not None:
            tile.thumbnail((tw - 8, img_h - 8))
            if verdict == "UNPAIRED":
                tile = tile.convert("L").convert("RGB")
            sheet.paste(tile, (cx + 4, cy + 4))
            sx, sy = tile.size
            ow, oh = Image.open(REPO / src if not pathlib.Path(src).is_absolute() else src).size \
                if False else (None, None)
            # draw the diff boxes, scaled from the original render to the thumbnail
            boxes = r.get("regions") or r.get("boxes") or []
            ow = r.get("width") or 0
            oh = r.get("height") or 0
            if boxes and ow and oh:
                fx, fy = sx / float(ow), sy / float(oh)
                for b in boxes[:400]:
                    try:
                        x0, y0, x1, y1 = b[:4] if isinstance(b, (list, tuple)) else \
                            (b["x0"], b["y0"], b["x1"], b["y1"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    d.rectangle([cx + 4 + x0 * fx, cy + 4 + y0 * fy,
                                 cx + 4 + x1 * fx, cy + 4 + y1 * fy],
                                outline="#ff2d55", width=2)
        d.rectangle([cx + 1, cy + 1, cx + tw - 2, cy + th - 2], outline=colour, width=2)

        pct = r.get("pct")
        pct_s = "—" if pct is None else ("%.2f%%" % pct)
        cap = (r.get("caption") or r.get("label") or r.get("key") or "")[:44]
        d.text((cx + 8, cy + img_h + 4), "%s  %s" % (r.get("key", ""), cap), font=f_cap, fill="#c9d1d9")
        d.text((cx + tw - 118, cy + img_h + 3), "%-9s %s" % (verdict, pct_s), font=f_pct, fill=colour)

    out = pathlib.Path(a.out) if a.out else run / "MARKED-DIFF.png"
    if not out.is_absolute():
        out = REPO / out
    sheet.save(out)
    tally = {}
    for r in rows:
        tally[r.get("verdict", "?")] = tally.get(r.get("verdict", "?"), 0) + 1
    print("wrote %s  (%dx%d, %d panels)" % (out, sheet.width, sheet.height, len(rows)))
    print("tally:", ", ".join("%s %d" % kv for kv in sorted(tally.items())))


if __name__ == "__main__":
    main()
