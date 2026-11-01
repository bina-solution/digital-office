"""Construction sheet: the icon with its 4x4 anchor grid, module grid and the solved clearances."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iomark import Design

def construction(r, path):
    if "wo" in r:
        d = Design(r["wo"], r["gap"], r["rho"], r["ro"], r["tau"], r["pol"], r["k"], r["centre"])
    else:                                            # a v3/v4 record (square anchors, explicit radii)
        from search3 import design
        d = design(r)
    u = 1000.0 / d.L
    X = lambda x: 500 + (x - d.ox) * u
    Y = lambda y: 500 + (y - d.oy) * u
    icon = d.svg().split(">", 1)[1].rsplit("</svg>", 1)[0]
    xs = [0, 1 + d.gap, d.xc, d.W]
    ys = [6, 4, 2, 0]                                    # y1..y4 (bottom -> top), SVG y-down
    RED, GRID = "#ff3b30", "#ff3b30"
    p = [f'<g transform="translate(150 40)">{icon}']
    for i in range(int(round(d.W)) + 1):
        p.append(f'<line x1="{X(i)}" y1="{Y(0)}" x2="{X(i)}" y2="{Y(6)}" stroke="{GRID}" stroke-opacity=".28" stroke-width="1.2"/>')
    for j in range(7):
        p.append(f'<line x1="{X(0)}" y1="{Y(j)}" x2="{X(d.W)}" y2="{Y(j)}" stroke="{GRID}" stroke-opacity=".28" stroke-width="1.2"/>')
    for n, x in enumerate(xs, 1):
        p.append(f'<line x1="{X(x)}" y1="-25" x2="{X(x)}" y2="1025" stroke="{RED}" stroke-width="2.5"/>')
        p.append(f'<text x="{X(x)}" y="1062" text-anchor="middle" font-family="Helvetica" font-size="30" font-weight="700" fill="{RED}">x{n}</text>')
    for n, y in enumerate(ys, 1):
        p.append(f'<line x1="-25" y1="{Y(y)}" x2="1025" y2="{Y(y)}" stroke="{RED}" stroke-width="2.5"/>')
        p.append(f'<text x="-40" y="{Y(y) + 10}" text-anchor="end" font-family="Helvetica" font-size="30" font-weight="700" fill="{RED}">y{n}</text>')
    for x in xs:
        for y in ys:
            p.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="9" fill="#fff" stroke="{RED}" stroke-width="4"/>')
    p.append("</g>")
    cap = (f"x1–x4 = {xs[0]:g} · {xs[1]:g} · {d.xc:g} · {d.W:g}   y1–y4 = 0 · 2 · 4 · 6 modules   stroke = gap = 1   "
           f"clearance {d.k:g}   black = white · left = right · top = bottom")
    p.append(f'<text x="650" y="1140" text-anchor="middle" font-family="Helvetica" font-size="21" fill="#555">{cap}</text>')
    open(path, "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="1170" viewBox="0 0 1240 1170">'
                          '<rect width="1240" height="1170" fill="#f4f5f6"/>' + "".join(p) + "</svg>\n")

if __name__ == "__main__":
    sel = json.load(open(sys.argv[1]))
    construction(sel[int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0], sys.argv[3] if len(sys.argv) > 3 else "construction.svg")
