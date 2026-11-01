"""#7's i0 in the old icon's style (demo/logos/bina_final.py in beautiful): tile #1b5e4a with corners at 22 % of
its side, ink #fbfcfc, mint #7ecfad, one cap radius (0.27 x stroke) on every stroke end.
Versions vary the o's corners, which parts are mint, and the palette."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iomark import Design

CAP = 0.27
O_SHAPES = {"boxy": (CAP, CAP), "nested": (1 + CAP, CAP), "stadium": (2.0, 1.0)}
ACCENTS = {"head+apps": ("dot", "apps"), "apps": ("apps",), "head": ("dot",), "one colour": ()}
PALETTES = {
    "old":      dict(bg="#f4f5f4", tile="#1b5e4a", ink="#fbfcfc", mint="#7ecfad"),
    "site":     dict(bg="#f4f5f4", tile="grad:#0e5e49:#0e9f6e", ink="#fbfcfc", mint="#9fe0c3"),
    "night":    dict(bg="#f4f5f4", tile="#0f2a22", ink="#fbfcfc", mint="#7ecfad"),
    "light":    dict(bg="#f4f5f4", tile="#fbfcfc", ink="#1b5e4a", mint="#7ecfad"),
    "mint":     dict(bg="#f4f5f4", tile="#7ecfad", ink="#fbfcfc", mint="#1b5e4a"),
    "platform": dict(bg="#f4f5f4", tile="#0e9f6e", ink="#fbfcfc", mint="#0f2a22"),
}


def design(o="boxy"):
    ro, ri = O_SHAPES[o]
    d = Design(4, 1, CAP, ro, 0.0, "pos", 3.0, "median", ri=ri, rc=0.0)
    d.rc_tile = 0.22 * 2 * d.a                     # the old icon's tile radius: 22 % of the side
    return d


def svg(o="boxy", accent="head+apps", palette="old", size=None, frame=0.06):
    d = design(o)
    P = PALETTES[palette]
    a = d.a
    side = 2 * a * (1 + 2 * frame)                 # canvas = tile + a thin light frame, like an app-icon preview
    u = 1000.0 / side
    X = lambda x: 500 + (x - d.ox) * u
    Y = lambda y: 500 + (y - d.oy) * u
    f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
    defs = ""
    tile_fill = P["tile"]
    if tile_fill.startswith("grad:"):
        _, c1, c2 = tile_fill.split(":")
        defs = f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
        tile_fill = "url(#g)"
    t0, ts, tr = 500 - a * u, 2 * a * u, d.rc_tile * u
    parts = []
    names = ["dot", "body", "apps"]
    for name, (cx, cy, hx, hy, r) in zip(names, d.solid):
        col = P["mint"] if name in ACCENTS[accent] else P["ink"]
        parts.append(f'<rect x="{f(X(cx - hx))}" y="{f(Y(cy - hy))}" width="{f(2 * hx * u)}" height="{f(2 * hy * u)}" rx="{f(r * u)}" fill="{col}"/>')

    def rpath(cx, cy, hx, hy, r, cw=True):
        x0, y0, x1, y1, r = X(cx - hx), Y(cy - hy), X(cx + hx), Y(cy + hy), r * u
        if cw:
            return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}"
                    f"H{f(x0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")
        return (f"M{f(x0 + r)} {f(y0)}A{f(r)} {f(r)} 0 0 0 {f(x0)} {f(y0 + r)}V{f(y1 - r)}A{f(r)} {f(r)} 0 0 0 {f(x0 + r)} {f(y1)}"
                f"H{f(x1 - r)}A{f(r)} {f(r)} 0 0 0 {f(x1)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 0 {f(x1 - r)} {f(y0)}Z")
    parts.insert(2, f'<path d="{rpath(*d.outer)}{rpath(*d.inner, cw=False)}" fill="{P["ink"]}"/>')
    wh = f' width="{size}" height="{size}"' if size else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000"{wh}>{defs}'
            f'<rect width="1000" height="1000" fill="{P["bg"]}"/>'
            f'<rect x="{f(t0)}" y="{f(t0)}" width="{f(ts)}" height="{f(ts)}" rx="{f(tr)}" fill="{tile_fill}"/>'
            + "".join(parts) + "</svg>\n")


VERSIONS = ([(o, acc, "old") for o in O_SHAPES for acc in ACCENTS] +
            [("boxy", "head+apps", p) for p in ("site", "night", "light", "mint", "platform")] +
            [("stadium", "head+apps", p) for p in ("night", "light", "platform")])
