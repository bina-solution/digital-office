#!/usr/bin/env python3
"""The desktop app's icons — what a computer shows for the office once the app is installed (DGO-1972).

    python3 packaging/desktop/scripts/app_icons.py [--chromium PATH]

Writes two PNGs into build/icons/, the mark as it is — the rounded tile on nothing:

  icon-512.png   electron-builder makes every system's icon from it: the Windows .ico (the Start menu, the
                 taskbar, the installer), the macOS .icns (Applications, the Dock) and the Linux launcher's
  icon-192.png   the window's, the tray's and a notice's icon at run time (src/main.js iconPath)

Rendered by Chromium headless from the office's mark, platform-base/bina-ui/brand/favicon.svg, so the
three colours stay the owner's (2026-11-15, DGO-1908) and nothing here names one (G82). Run it again
whenever the mark changes; test/icons.test.mjs checks the sizes.
"""
import argparse
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
MARK = HERE.parents[2] / "platform-base" / "bina-ui" / "brand" / "favicon.svg"
OUT = HERE.parent / "build" / "icons"

#: (file, side in px)
ICONS = (("icon-192.png", 192), ("icon-512.png", 512))


def page(svg: str, side: int) -> str:
    return (f"<!doctype html><meta charset=utf-8><style>html,body{{margin:0;background:transparent}}"
            f"svg{{display:block;width:{side}px;height:{side}px}}</style>{svg}")


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
        for name, side in ICONS:
            html = pathlib.Path(tmp) / f"{name}.html"
            html.write_text(page(svg, side), encoding="utf-8")
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
