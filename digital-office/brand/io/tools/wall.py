"""The logo wall as vectors (DGO-1501): fit every tile of a wall of versions with `iomark.Design`, then draw
the fitted wall as ONE SVG of shapes, for a CSS mask.

The owner chose a wall of versions with no scores (2026-09-25 17:58, `selected_preview.png`, 100 marks) as
the background of the sign-in app and of the office's failure card. The PNG is a 1310 px screenshot made in a
folder that no longer exists, and the search that drew it is not in tools/ (search3/search4 came later). So
each tile is FOUND again: a grid over the factors (o width, i<->o gap, caps, o radius, container corner,
polarity, clearance, centring) picks the closest version at 48 px, and a coordinate descent at the tile's own
size settles it; tiles still under IoU 0.99 get a second grid with the o's inner radius and the median
centring, and a descent from sharp starts. The 0.75 container corner is a value of that sweep (a disc fits
those tiles badly). Measured, the record in ../wall/wall100.json: raster IoU per tile mean 0.9994, 98 of 100
at 0.99 or more, the lowest 0.9755; Chrome's render of the SVG against the PNG, median 0.9939.

    python3 wall.py fit <wall.png> <tile> <pitch> <offset> <out.json>    # needs numpy + Pillow
    python3 wall.py svg <wall.json> <out.svg>

The SVG names no colour: a shape with no fill is black, and a mask reads only its alpha, so a screen paints
the wall with the palette. Each tile is one evenodd path: the container, the mark's three bars and the o's two
outlines, which leaves exactly the dark half of the original, positive (dark box) or negative (dark canvas).
Half a gap on each side of every tile, so the wall repeats without a seam."""
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iomark import Design  # noqa: E402


def design(p):
    rc = p.get("rc")
    return Design(p["wo"], p["gap"], p["rho"], p["ro"], p.get("tau", 0.0), p["pol"], p["k"], p["centre"],
                  ri=p.get("ri"), rc=(None if rc is None else (math.inf if rc == -1 else rc)))


# ── fit ──────────────────────────────────────────────────────────────────────────────────────────────

def _space():
    for wo in (4, 4.5, 5, 5.5, 6):
        for gap in sorted({1.0, wo / 2 - 1}):
            for rho in (0.0, 0.25, 0.5):
                for ro in sorted({0.0, 0.5, 1.0, 1 + rho, 1.5, 2.0, wo / 2}):
                    if ro > wo / 2:
                        continue
                    for box in ("t0", "t0.15", "t0.3", "t0.5", "t0.75", "disc", "r0.5", "r1", "r1.5", "r2"):
                        for pol in ("pos", "neg"):
                            for k in (1.0, 1.5, 2.0):
                                for centre in ("mass", "bbox"):
                                    p = dict(wo=wo, gap=gap, rho=rho, ro=ro, pol=pol, k=k, centre=centre)
                                    if box.startswith("t"):
                                        p["tau"] = float(box[1:])
                                    elif box == "disc":
                                        p["rc"] = -1
                                    else:
                                        p["rc"] = float(box[1:])
                                    yield p


def fit(png, tile, pitch, off, out):
    import numpy as np
    from PIL import Image
    im = np.asarray(Image.open(png).convert("L")).astype(np.float32) / 255
    cols, rows = (im.shape[1] - off) // pitch, (im.shape[0] - off) // pitch
    tiles = [im[off + r * pitch: off + r * pitch + tile, off + c * pitch: off + c * pitch + tile]
             for r in range(rows) for c in range(cols)]
    N = 48

    def small(a):
        return np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((N, N), Image.BOX)).astype(np.float32) / 255

    def err(p, t):
        try:
            d = design(p)
            return 9.0 if d.margin < 0 else float(((d.raster(tile) - t) ** 2).mean())
        except Exception:                   # a factor combination with no solution
            return 9.0

    def iou(p, t):
        ink, tk = 1 - design(p).raster(tile), 1 - t
        return float(np.minimum(ink, tk).sum() / np.maximum(ink, tk).sum())

    def descend(p, t, steps, rounds=6):
        best = err(p, t)
        for _ in range(rounds):
            better = False
            for key, st in steps.items():
                for s in (st, -st, st / 2, -st / 2):
                    q = dict(p)
                    if key == "ri":
                        q["ri"] = round((q["ri"] if q.get("ri") is not None else max(0.0, q["ro"] - 1)) + s, 4)
                    elif key in q and q[key] != -1:
                        q[key] = round(q[key] + s, 4)
                    else:
                        continue
                    if q[key] < 0:
                        continue
                    e = err(q, t)
                    if e < best - 1e-7:
                        p, best, better = q, e, True
            if not better:
                break
        return p

    t0 = time.time()
    cands, rasters = [], []
    for p in _space():
        try:
            d = design(p)
        except Exception:
            continue
        if d.margin >= 0:
            cands.append(p)
            rasters.append(d.raster(N).astype(np.float32).ravel())
    R = np.stack(rasters)
    STEPS = dict(wo=0.25, gap=0.25, rho=0.125, ro=0.25, tau=0.05, k=0.25, rc=0.25, ri=0.25)
    res = []
    for i, t in enumerate(tiles):
        p = descend(cands[int(((R - small(t).ravel()) ** 2).mean(1).argmin())], t, STEPS)
        if iou(p, t) < 0.99:                # second look: the o's inner radius and the median centring
            base, best = dict(p, tau=p.get("tau", 0.75)), (9.0, None)
            base.pop("rc", None)
            for wo in (4, 5, 6):
                for gap in sorted({1.0, wo / 2 - 1}):
                    for rho in (0, 0.25, 0.5):
                        for ro in (0, 0.5, 1, 1.25, 1.5, 2, 2.5, 3):
                            for ri in sorted({0, 0.5, 1, max(0, ro - 1)}):
                                for k in (1, 1.5, 2):
                                    for centre in ("mass", "bbox", "median"):
                                        if ro > wo / 2 or ri > ro:
                                            continue
                                        q = dict(base, wo=wo, gap=gap, rho=rho, ro=ro, ri=ri, k=k, centre=centre)
                                        e = err(q, t)
                                        if e < best[0]:
                                            best = (e, q)
            q = descend(best[1], t, STEPS)
            if iou(q, t) > iou(p, t):
                p = q
        res.append(dict(i=i, p=p, iou=round(iou(p, t), 5)))
        print(f"tile {i}: iou {res[-1]['iou']}", flush=True)
    json.dump(dict(source=Path(png).name, tile=tile, pitch=pitch, off=off, cols=cols, rows=rows, tiles=res),
              open(out, "w"), indent=1)
    s = sorted(r["iou"] for r in res)
    print(f"{len(res)} tiles in {time.time() - t0:.0f} s: iou min {s[0]} median {s[len(s) // 2]}")


# ── svg ──────────────────────────────────────────────────────────────────────────────────────────────

def _f(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _rrect(x0, y0, x1, y1, r):
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 0.05:
        return f"M{_f(x0)} {_f(y0)}H{_f(x1)}V{_f(y1)}H{_f(x0)}Z"
    a = f"A{_f(r)} {_f(r)} 0 0 1 "
    return (f"M{_f(x0 + r)} {_f(y0)}H{_f(x1 - r)}{a}{_f(x1)} {_f(y0 + r)}V{_f(y1 - r)}{a}{_f(x1 - r)} {_f(y1)}"
            f"H{_f(x0 + r)}{a}{_f(x0)} {_f(y1 - r)}V{_f(y0 + r)}{a}{_f(x0 + r)} {_f(y0)}Z")


def svg(src, out):
    J = json.load(open(src))
    T, P, C, R = J["tile"], J["pitch"], J["cols"], J["rows"]
    g = (P - T) / 2
    paths = []
    for t in J["tiles"]:
        d = design(t["p"])
        r, c = divmod(t["i"], C)
        ox, oy = c * P + g, r * P + g
        s = T / d.L
        cx, cy = ox + T / 2, oy + T / 2

        def box(b):
            bx, by, hx, hy, rr = b
            return _rrect(cx + (bx - hx - d.ox) * s, cy + (by - hy - d.oy) * s,
                          cx + (bx + hx - d.ox) * s, cy + (by + hy - d.oy) * s, rr * s)
        a = d.a * s
        mark = _rrect(cx - a, cy - a, cx + a, cy + a, d.crad(d.a) * s) + "".join(box(b) for b in d.solid) \
            + box(d.outer) + box(d.inner)
        paths.append(mark if d.pol == "pos" else _rrect(ox, oy, ox + T, oy + T, 0) + mark)
    W, H = C * P, R * P
    Path(out).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
        f'<!-- the logo wall (DGO-1501): {len(paths)} versions of the mark, {C} x {R}, fitted from {J.get("source", "")} '
        f'by digital-office/brand/io/tools/wall.py. Shapes only, no colour: a screen paints it through a mask. -->'
        f'<path fill-rule="evenodd" d="{"".join(paths)}"/></svg>\n')
    print(out, f"{W}x{H}", len(paths), "tiles")


if __name__ == "__main__":
    if sys.argv[1:2] == ["fit"]:
        fit(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6])
    elif sys.argv[1:2] == ["svg"]:
        svg(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
