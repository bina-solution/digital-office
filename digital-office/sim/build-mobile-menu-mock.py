#!/usr/bin/env python3
"""build-mobile-menu-mock — the phone frame, made of the owner's own screenshot, with the sheet rule on it.

The rule this artifact exists for (AGENTS.md § "A display change comes back as an interactive
simulation, and its screenshots", 2026-10-12): a proposal about what a screen looks like is a mock a
person can DRIVE plus the picture of it — and when the problem arrived as a screenshot, the demo
starts from THAT screen. So the "before" state here is not a drawing: it is the app area of the shot
he sent (2026-10-13 20:52, `ci-artifacts/owner-reports/2026-10-13-mobile-menu-squeezes-main.jpg`),
cropped to the rows between the console's top bar and its dock, exactly as his phone painted it.

Everything else is measured, never typed:
  * the app area's rows        — the dock's own olive band and the header's border line, found in the
                                 image (`bands()`), and printed by this script;
  * the menu/strip boundary    — the first column, inside the app area, where the surface stops being
                                 the conversation's ground and becomes the sidebar's fill;
  * the conversation at the width it SHOULD have — the same app, same profile, photographed live with
                                 the menu closed (`ci-artifacts/mobile-nav-squeeze/opened.png`, the
                                 probe that measured the defect) — real pixels, not a reconstruction;
  * the office palette         — inlined from `platform-base/bina-ui/theme-tokens.css`, verbatim.

Output is a BUILD ARTIFACT under the gitignored `ci-artifacts/` (it carries a copy of the palette,
which is exactly what gate G27 keeps in one tracked place).

    python3 digital-office/sim/build-mobile-menu-mock.py            # → ci-artifacts/mobile-menu-mock/
    python3 digital-office/sim/build-mobile-menu-mock.py --out DIR
"""
from __future__ import annotations

import argparse
import base64
import io
import pathlib
import re
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("needs Pillow: run this in a container that has it (ui-capture / sites-render do)")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "mobile-menu-mock.src.html"
DEFAULT_OUT = REPO / "ci-artifacts" / "mobile-menu-mock"
OWNER_SHOT = REPO / "ci-artifacts" / "owner-reports" / "2026-10-13-mobile-menu-squeezes-main.jpg"
LIVE_SHOT = REPO / "ci-artifacts" / "mobile-nav-squeeze" / "opened.png"
TOKENS = REPO / "platform-base" / "bina-ui" / "theme-tokens.css"


def bands(im: Image.Image) -> tuple[int, int]:
    """The app area's rows: below the console header's border line, above the dock's own olive band."""
    px, (w, h) = im.load(), im.size
    def row(y, step=8):
        return [px[x, y] for x in range(0, w, step)]
    def olive(c):
        r, g, b = c
        return r < 130 and 80 < g < 140 and b < 120 and g >= r
    bottom = None
    for y in range(h - 1, int(h * 0.6), -1):
        cells = row(y)
        if sum(1 for c in cells if olive(c)) > len(cells) * 0.85:
            bottom = y
            continue
        if bottom is not None and y < bottom - 8:
            break
    if bottom is None:
        sys.exit("no dock band found in the shot — is this a phone screenshot of the console?")
    dock_top = bottom
    while dock_top > 0 and sum(1 for c in row(dock_top - 1) if olive(c)) > len(row(dock_top - 1)) * 0.85:
        dock_top -= 1
    # the header's own white: the LAST row in the top half that is white edge to edge — the app area
    # (and its border line) begins immediately below it
    last_white = None
    for y in range(int(h * 0.06), int(h * 0.45)):
        if all(sum(c) / 3 >= 253 for c in row(y, 4)):
            last_white = y
    if last_white is None:
        sys.exit("no header found in the shot — is this a phone screenshot of the console?")
    return last_white + 3, dock_top


def edge_column(im: Image.Image, top: int, bottom: int) -> int:
    """The sheet's own edge, per row, then the MEDIAN of the rows.

    Two surfaces meet here — the conversation's ground and the sidebar's fill — and either side can
    carry text on a given row, so one row cannot decide it. The median of every row's own answer can:
    a row where the boundary is covered by a glyph or a button is an outlier."""
    px, (w, _h) = im.load(), im.size
    def near(c, ref, tol=3):
        return all(abs(c[i] - ref[i]) <= tol for i in range(3))
    guesses = []
    for y in range(top + 40, bottom - 40, 5):
        fill = px[int(w * 0.85), y]                      # deep inside the sidebar: its own fill
        for x in range(int(w * 0.08), int(w * 0.55)):
            if near(px[x, y], fill) and all(near(px[x + k, y], fill) for k in range(0, 40, 6)) \
               and sum(px[x - 5, y]) / 3 >= 252:         # …and the conversation is its own ground
                guesses.append(x)
                break
    if len(guesses) < 20:
        sys.exit(f"could not find where the sidebar's fill begins ({len(guesses)} rows agreed)")
    guesses.sort()
    return guesses[len(guesses) // 2]


def data_uri(im: Image.Image, quality: int = 88) -> str:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    ap.add_argument("--owner-shot", type=pathlib.Path, default=OWNER_SHOT)
    ap.add_argument("--live-shot", type=pathlib.Path, default=LIVE_SHOT)
    a = ap.parse_args()
    for p in (a.owner_shot, a.live_shot, SRC, TOKENS):
        if not p.exists():
            sys.exit(f"missing input: {p}")
    out = a.out
    out.mkdir(parents=True, exist_ok=True)

    owner = Image.open(a.owner_shot).convert("RGB")
    live = Image.open(a.live_shot).convert("RGB")
    o_top, o_bottom = bands(owner)
    l_top, l_bottom = bands(live)
    # the CSS size each shot was painted at: a phone screenshot is `device px / devicePixelRatio`
    o_css_w = 393.0                                    # 1080 / 2.75 — the owner's phone
    l_css_w = 390.0                                    # the capture profile (view-profiles.yaml)
    o_scale = owner.size[0] / o_css_w
    l_scale = live.size[0] / l_css_w
    o_edge = edge_column(owner, o_top, o_bottom)

    before = owner.crop((0, o_top, owner.size[0], o_bottom))
    sheet = owner.crop((o_edge, o_top, owner.size[0], o_bottom))
    room = live.crop((0, l_top, live.size[0], l_bottom))
    before.save(out / "owner-app.jpg", quality=90)
    sheet.save(out / "owner-sheet.jpg", quality=90)
    room.save(out / "live-room.jpg", quality=90)

    css = {
        "frame_w": round(owner.size[0] / o_scale, 1),
        "frame_h": round((o_bottom - o_top) / o_scale, 1),
        "sheet_w": round((owner.size[0] - o_edge) / o_scale, 1),
        "strip_w": round(o_edge / o_scale, 1),
        "room_css_h": round((l_bottom - l_top) / l_scale, 1),
        "owner_scale": round(o_scale, 4),
        "live_scale": round(l_scale, 4),
        "owner_rows": f"{o_top}…{o_bottom}",
        "live_rows": f"{l_top}…{l_bottom}",
        "owner_edge_px": o_edge,
    }
    html = SRC.read_text(encoding="utf-8")
    html = html.replace("/*{{TOKENS}}*/", TOKENS.read_text(encoding="utf-8"))
    html = html.replace("{{BEFORE}}", data_uri(before))
    html = html.replace("{{SHEET}}", data_uri(sheet))
    html = html.replace("{{ROOM}}", data_uri(room))
    for key, value in css.items():
        html = html.replace(f"{{{{{key}}}}}", str(value))
    left = re.findall(r"\{\{[a-z_]+\}\}", html)
    if left:
        sys.exit(f"unfilled placeholders: {sorted(set(left))}")
    (out / "mobile-menu-mock.html").write_text(html, encoding="utf-8")
    print(f"owner shot  : {a.owner_shot.name} {owner.size} app rows {css['owner_rows']} "
          f"@ {css['owner_scale']}x → {css['frame_w']}×{css['frame_h']} css")
    print(f"live shot   : {a.live_shot.name} {live.size} app rows {css['live_rows']} "
          f"@ {css['live_scale']}x")
    print(f"the boundary: device x={css['owner_edge_px']} → menu {css['sheet_w']} css, "
          f"conversation {css['strip_w']} css")
    print(f"out         : {out / 'mobile-menu-mock.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
