"""The sheet-metal kit every cap is built from: a part knows its folded 3D, its flat blank, its bends and rivets.

A cap is an assembly of parts. Each part is made the way the shop makes it — a rectangle (or a shape cut from
a rectangle) bent along straight lines — so each part carries:

    blank      the rectangle cut from the sheet (w × h, inches), what nesting packs and the sheets are counted by
    outline    the true flat shape when it is not the whole rectangle (a hip triangle, a bell side), for the ticket
    bends      how many brake bends it takes (labour grows with them)
    rivets     how many rivets join it to its neighbours
    mesh_in2   for a screen: its area of mesh, priced by the square foot, not by the sheet
    solid      a build123d shape of the part as it sits on the cap (folded), in inches, built lazily

Flat sizes come from the bend allowance BA = θ·(r + K·t) on the neutral line — the rule FreeCAD's SheetMetal
unfolder agreed with to the thousandth (a 40 × 30 × 3 tray: 45.911 × 35.911, DGO-1076, 2026-11-01). Outside
sizes are what the shop measures, so a flange of outside length F adds F − (r + t) + BA/… to the blank:
`flange_flat(F)` below.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

#: per gauge: thickness (in) — galvanized/painted steel by the manufacturers' standard gauge, stainless by its own,
#: copper by ounces per square foot (16 oz = 0.0216″, 20 oz = 0.027″)
THICKNESS = {"steel": {22: 0.0336, 24: 0.0276, 26: 0.0217, 28: 0.0187},
             "stainless": {22: 0.0312, 24: 0.025, 26: 0.0187},
             "copper": {16: 0.0216, 20: 0.027, 24: 0.0323}}
K_FACTOR = 0.44          # air-bent thin sheet on a brake (ANSI table, SheetMetal's default for r ≈ t)


@dataclass
class Metal:
    key: str              # galvanized | prepainted | stainless | copper | …
    family: str           # steel | stainless | copper (its thickness table)
    gauge: int
    t: float              # thickness, in
    r: float              # inside bend radius, in (≈ t on a hand brake)
    K: float = K_FACTOR

    def ba(self, deg: float = 90) -> float:
        """Bend allowance of one bend of `deg` degrees (inches of neutral line in the bend)."""
        return math.radians(deg) * (self.r + self.K * self.t)

    def flange_flat(self, outside: float, deg: float = 90) -> float:
        """Flat length a flange of OUTSIDE length `outside` (from the outer face of the bend) adds to the blank,
        bend included: the straight part past the bend's tangent plus the bend allowance."""
        setback = (self.r + self.t) * math.tan(math.radians(deg) / 2)
        return outside - setback + self.ba(deg)

    def base_flat(self, outside: float, bends_each_end: int = 1, deg: float = 90) -> float:
        """Flat length of a web of OUTSIDE size `outside` that has a bend at each end: it loses one setback per bend."""
        setback = (self.r + self.t) * math.tan(math.radians(deg) / 2)
        return outside - 2 * bends_each_end * setback


def metal_for(key: str, gauge: int | None = None) -> Metal:
    """The metal a job names, with the shop's usual gauge when it names none (MEET-41: galvanized/painted 24 ga,
    stainless 24 ga, copper 16 oz; ASSUMED where Alan did not say)."""
    k = (key or "galvanized").strip().lower()
    family = "copper" if k == "copper" else "stainless" if k == "stainless" else "steel"
    table = THICKNESS[family]
    g = int(gauge) if gauge and int(gauge) in table else (16 if family == "copper" else 24)
    t = table[g]
    return Metal(key=k, family=family, gauge=g, t=t, r=round(max(t, 0.03), 4))


@dataclass
class Part:
    name: str
    blank: tuple[float, float]                     # w × h cut from the sheet, inches
    qty: int = 1
    bends: int = 0
    rivets: int = 0
    mesh_in2: float = 0.0                          # a screen: priced by area, not cut from the sheet
    outline: Optional[list[tuple[float, float]]] = None
    note: str = ""
    build: Optional[Callable[[], object]] = field(default=None, repr=False)   # -> build123d shape, placed

    @property
    def sheet_part(self) -> bool:
        return self.mesh_in2 == 0 and self.blank[0] > 0 and self.blank[1] > 0

    def as_piece(self) -> dict:
        w, h = (round(self.blank[0], 3), round(self.blank[1], 3))
        return {"name": self.name, "w": int(w) if float(w).is_integer() else w,
                "h": int(h) if float(h).is_integer() else h, "qty": self.qty}


def plate(w: float, h: float, t: float):
    """A flat plate w × h of thickness t, lying in XY with its min corner at the origin (z up)."""
    from build123d import Align, Box
    return Box(w, h, t, align=(Align.MIN, Align.MIN, Align.MIN))


def polygon_plate(points: list[tuple[float, float, float]], t: float):
    """A planar polygon given by 3D points, thickened by t along its normal: one face of a hip or a mitre."""
    from build123d import Face, Solid, Vector, Wire
    pts = []
    for p in points:                                   # a square hip's ridge is a point: drop repeated corners
        if not pts or math.dist(p, pts[-1]) > 1e-6:
            pts.append(p)
    if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()
    wire = Wire.make_polygon([Vector(*p) for p in pts], close=True)
    face = Face(wire)
    n = face.normal_at()
    return Solid.extrude(face, n * t)
