"""io mark — every part is a rounded box, every free number is solved.

Module = stroke = every vertical gap. Rows (from the top): dot 0-1, gap 1-2, i-body 2-6; apps 2-4 on the
o's centre line; the o spans the full 6 modules. Factors:
  wo   o width (4 = "0" on a square anchor grid -> mark is 1:1;  6 = circle on the 3:2 grid)
  gap  i<->o gap (1 = stroke; or the equal-column grid value wo/2 - 1)
  rho  cap radius of dot, body and apps (0 flat .. 0.5 round)
  ro   o outer radius (0 sharp "digital 0", 1+rho boxy, 2 soft, wo/2 round); inner = max(0, ro - 1)
  tau  container corner radius / half-size (0 square .. 1 disc)
  pol  pos = black container, white mark; neg = white container on black, black mark
  k    clearance: min distance mark -> container edge
Solved: container half-size a (from k), canvas side L (black area = white area, exactly).
"""
import math
import numpy as np

FOURPI = 4 - math.pi


def rbox_area(hx, hy, r):
    return 4 * hx * hy - FOURPI * r * r


def rbox_sdf(px, py, cx, cy, hx, hy, r):
    qx = np.abs(px - cx) - (hx - r)
    qy = np.abs(py - cy) - (hy - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def rbox_outline(cx, cy, hx, hy, r, step=0.01):
    pts = []
    for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        ccx, ccy = cx + sx * (hx - r), cy + sy * (hy - r)
        if r > 0:
            n = max(8, int(r * math.pi / 2 / step))
            t = np.linspace(0, math.pi / 2, n)
            pts.append(np.c_[ccx + sx * r * np.cos(t), ccy + sy * r * np.sin(t)])
        else:
            pts.append(np.array([[ccx, ccy]]))
    for (x0, y0, x1, y1) in ((cx - hx, cy - hy + r, cx - hx, cy + hy - r), (cx + hx, cy - hy + r, cx + hx, cy + hy - r),
                             (cx - hx + r, cy - hy, cx + hx - r, cy - hy), (cx - hx + r, cy + hy, cx + hx - r, cy + hy)):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / step))
        t = np.linspace(0, 1, n)
        pts.append(np.c_[x0 + (x1 - x0) * t, y0 + (y1 - y0) * t])
    return np.vstack(pts)


class Design:
    def __init__(self, wo, gap, rho, ro, tau, pol, k, centre="mass", ri=None, rc=None):
        """ri: o inner radius (default concentric, ro - 1); rc: container corner radius in modules (overrides tau;
        math.inf = disc)."""
        self.wo, self.gap, self.rho, self.ro, self.tau, self.pol, self.k, self.centre = wo, gap, rho, ro, tau, pol, k, centre
        self.rc = rc
        xc = 1 + gap + wo / 2
        self.xc = xc
        self.W = 1 + gap + wo
        ri = max(0.0, ro - 1) if ri is None else ri
        self.ri = ri
        # (cx, cy, hx, hy, r)
        self.solid = [(0.5, 0.5, 0.5, 0.5, rho), (0.5, 4.0, 0.5, 2.0, rho), (xc, 3.0, 0.5, 1.0, rho)]
        self.outer = (xc, 3.0, wo / 2, 3.0, ro)
        self.inner = (xc, 3.0, wo / 2 - 1, 2.0, ri)
        A = sx = sy = 0.0
        for (cx, cy, hx, hy, r) in self.solid:
            a = rbox_area(hx, hy, r); A += a; sx += a * cx; sy += a * cy
        a = rbox_area(*self.outer[2:]) - rbox_area(*self.inner[2:]); A += a; sx += a * xc; sy += a * 3.0
        self.Am, self.gx, self.gy = A, sx / A, sy / A
        if centre == "median":
            self.ox, self.oy = self.medians()           # equal ink on both sides of both axes
        else:
            self.ox = self.gx if centre == "mass" else self.W / 2
            self.oy = 3.0
        P = np.vstack([rbox_outline(*s) for s in self.solid] + [rbox_outline(*self.outer)]) - [self.ox, self.oy]
        lo, hi = 0.0, 40.0
        for _ in range(60):
            mid = (lo + hi) / 2
            d = -rbox_sdf(P[:, 0], P[:, 1], 0, 0, mid, mid, self.crad(mid))
            lo, hi = (lo, mid) if d.min() >= k else (mid, hi)
        self.a = hi
        self.Ac = rbox_area(hi, hi, self.crad(hi))
        self.L = math.sqrt(2 * (self.Ac - self.Am))
        self.margin = self.L / 2 - self.a

    def crad(self, a):
        return self.tau * a if self.rc is None else min(self.rc, a)

    def key(self):
        box = f"t{self.tau:g}" if self.rc is None else ("disc" if self.rc == math.inf else f"r{self.rc:g}")
        return (f"w{self.wo:g}g{self.gap:g}c{self.rho:g}o{self.ro:g}i{self.ri:g}{box}{self.pol}k{self.k:g}"
                + {"mass": "m", "bbox": "b", "median": "h"}[self.centre])

    def coverage(self, xs, ys, step):
        X, Y = np.meshgrid(xs, ys)
        d = np.maximum(rbox_sdf(X, Y, *self.outer), -rbox_sdf(X, Y, *self.inner))
        for sh in self.solid:
            d = np.minimum(d, rbox_sdf(X, Y, *sh))
        return np.clip(0.5 - d / step, 0, 1)

    def medians(self, step=0.005):
        """The point whose vertical and horizontal lines each cut the mark's area exactly in half."""
        xs = np.arange(-0.25, self.W + 0.25, step) + step / 2
        ys = np.arange(-0.25, 6.25, step) + step / 2
        cov = self.coverage(xs, ys, step)
        cx = np.cumsum(cov.sum(0)); cy = np.cumsum(cov.sum(1))
        return (float(np.interp(0.5, cx / cx[-1], xs + step / 2)), float(np.interp(0.5, cy / cy[-1], ys + step / 2)))

    # -- raster (for the search; the deliverable is the SVG) --
    def raster(self, n=1024):
        s = self.L / n
        c = (np.arange(n) + 0.5) * s - self.L / 2
        px, py = np.meshgrid(c, c)
        mx, my = px + self.ox, py + self.oy
        d = rbox_sdf(mx, my, *self.outer)
        d = np.maximum(d, -rbox_sdf(mx, my, *self.inner))
        for sh in self.solid:
            d = np.minimum(d, rbox_sdf(mx, my, *sh))
        mark = np.clip(0.5 - d / s, 0, 1)
        box = np.clip(0.5 - rbox_sdf(px, py, 0, 0, self.a, self.a, self.crad(self.a)) / s, 0, 1)
        # positive: box black, mark white -> white = 1 - box + mark (mark is inside the box)
        white = 1 - box + mark if self.pol == "pos" else box - mark
        return np.clip(white, 0, 1)

    # -- SVG --
    def svg(self, size=None):
        u = 1000.0 / self.L
        X = lambda x: 500 + (x - self.ox) * u
        Y = lambda y: 500 + (y - self.oy) * u
        f = lambda v: f"{v:.3f}".rstrip("0").rstrip(".")
        ink, paper = "#000", "#fff"
        bg, box, fg = (paper, ink, paper) if self.pol == "pos" else (ink, paper, ink)
        a = self.a * u
        rc = self.crad(self.a) * u
        cont = f'<rect x="{f(500 - a)}" y="{f(500 - a)}" width="{f(2 * a)}" height="{f(2 * a)}"' + (f' rx="{f(rc)}"' if rc else "") + "/>"

        def rpath(cx, cy, hx, hy, r, sweep=1):
            x0, y0, x1, y1 = X(cx - hx), Y(cy - hy), X(cx + hx), Y(cy + hy)
            r = r * u
            if r <= 0:
                return f"M{f(x0)} {f(y0)}H{f(x1)}V{f(y1)}H{f(x0)}Z" if sweep else f"M{f(x0)} {f(y0)}V{f(y1)}H{f(x1)}V{f(y0)}Z"
            if sweep:
                return (f"M{f(x0 + r)} {f(y0)}H{f(x1 - r)}A{f(r)} {f(r)} 0 0 1 {f(x1)} {f(y0 + r)}V{f(y1 - r)}"
                        f"A{f(r)} {f(r)} 0 0 1 {f(x1 - r)} {f(y1)}H{f(x0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0)} {f(y1 - r)}"
                        f"V{f(y0 + r)}A{f(r)} {f(r)} 0 0 1 {f(x0 + r)} {f(y0)}Z")
            return (f"M{f(x0 + r)} {f(y0)}A{f(r)} {f(r)} 0 0 0 {f(x0)} {f(y0 + r)}V{f(y1 - r)}A{f(r)} {f(r)} 0 0 0 {f(x0 + r)} {f(y1)}"
                    f"H{f(x1 - r)}A{f(r)} {f(r)} 0 0 0 {f(x1)} {f(y1 - r)}V{f(y0 + r)}A{f(r)} {f(r)} 0 0 0 {f(x1 - r)} {f(y0)}Z")

        els = []
        for (cx, cy, hx, hy, r) in self.solid:
            els.append(f'<rect x="{f(X(cx - hx))}" y="{f(Y(cy - hy))}" width="{f(2 * hx * u)}" height="{f(2 * hy * u)}"'
                       + (f' rx="{f(r * u)}"' if r else "") + "/>")
        els.append(f'<path d="{rpath(*self.outer)}{rpath(*self.inner, sweep=0)}"/>')
        wh = f' width="{size}" height="{size}"' if size else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000"{wh}>'
                f'<rect width="1000" height="1000" fill="{bg}"/><g fill="{box}">{cont}</g>'
                f'<g fill="{fg}">{"".join(els)}</g></svg>\n')
