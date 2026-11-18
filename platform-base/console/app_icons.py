#!/usr/bin/env python3
"""The console's app icons — what a computer shows for the office once it is installed (DGO-1972).

    python3 platform-base/console/app_icons.py [--chromium PATH]

Writes three PNGs into static/icons/, the ones manifest.webmanifest names:

  icon-192.png, icon-512.png   the mark as it is — the rounded tile on nothing — for the Start menu, the
                               Dock, a Linux launcher and the window's own icon ("purpose": "any")
  icon-maskable-512.png        the same mark on a SQUARE tile, for a system that cuts its own shape out of
                               the icon ("maskable": a phone, and Chrome on macOS for the Dock); the glyph
                               already sits inside the safe circle (a radius of 40% of the side: its
                               farthest corner is 35% from the centre), so only the tile's corners change

Rendered by Chromium headless from the office's mark, platform-base/bina-ui/brand/favicon.svg, so the
three colours stay the owner's (2026-11-15, DGO-1908) and nothing here names one (G82). Run it again
whenever the mark changes; test_app_manifest.py checks the sizes the manifest declares.
"""
import argparse
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
MARK = HERE.parents[1] / "platform-base" / "bina-ui" / "brand" / "favicon.svg"
OUT = HERE / "static" / "icons"

#: (file, side in px, the tile's corners squared)
ICONS = (("icon-192.png", 192, False), ("icon-512.png", 512, False), ("icon-maskable-512.png", 512, True))


def page(svg: str, side: int, square: bool) -> str:
    # the tile is the mark's first rect; `rx` as a property overrides the attribute (SVG 2)
    tile = "svg>rect:first-of-type{rx:0;ry:0}" if square else ""
    return (f"<!doctype html><meta charset=utf-8><style>html,body{{margin:0;background:transparent}}"
            f"svg{{display:block;width:{side}px;height:{side}px}}{tile}</style>{svg}")


def png_size(path: pathlib.Path):
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("google-chrome") or "chromium")
    a = ap.parse_args()
    svg = MARK.read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, side, square in ICONS:
            html = pathlib.Path(tmp) / f"{name}.html"
            html.write_text(page(svg, side, square), encoding="utf-8")
            shot = pathlib.Path(tmp) / name
            run = subprocess.run([a.chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                                  "--force-device-scale-factor=1", "--default-background-color=00000000",
                                  f"--window-size={side},{side}", f"--screenshot={shot}", html.as_uri()],
                                 capture_output=True, text=True, timeout=120)
            if run.returncode != 0 or not shot.is_file():
                print(f"app_icons: {a.chromium} drew no {name} (exit {run.returncode})\n{run.stderr[-2000:]}", file=sys.stderr)
                return 1
            if png_size(shot) != (side, side):
                print(f"app_icons: {name} came out {png_size(shot)}, not {side}x{side}", file=sys.stderr)
                return 1
            shutil.copyfile(shot, OUT / name)
            print(f"app_icons: {OUT / name} {side}x{side}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
