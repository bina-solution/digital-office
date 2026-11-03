"""The gallery's caps as sheet-metal assemblies — pan, standard, pitched, bell, cube, chase, tee, turtle, bishop.

Frame: the chimney top is L × W (the builder's quoted size: measured + ½″ clearance), centred on the origin, x
along L, y along W, its top at z = 0; the cap is built upward. Inches.

Three sources, each named where it is used:
  Alan    MEET-41 (2026-10-30) — the cut rules and the base by chimney type: a brick chimney takes the masonry
          model (10½″ strips, 10½ × 6 legs), a wood chase / flue takes a single flashing (L+7 × W+7 for a 3″
          turn-down) with a hole and a collar per flue [24:18, 33:34]. Straight bends only [59:32]. Rivets [43:05].
  builder the shop's 3D builder (cap3d.js), fitted to the shop's own photos: the proportions of each style.
  ASSUMED industry practice (Rockford/K&M/Riverside, IRC R1003.9) where Alan gave nothing: listed in the notes.

Every style returns parts (blank, bends, rivets, mesh, folded 3D) and the notes of what it assumed.
"""
from __future__ import annotations

import math

from . import Style, style
from .sm import Part, plate, polygon_plate

EARS = 1.5      # Alan: an F piece is 1½″ longer — a ¾″ ear each side
HEM = 0.5       # Alan: a ½″ fold on a turn-down [32:47]
SEAM = 1.0      # ASSUMED: a 1″ standing seam takes 1″ from each panel it joins


def _p(key, label, default, lo=0.25, hi=240, unit="in"):
    return {"key": key, "label": label, "unit": unit, "min": lo, "max": hi, "default": default}


SIZE = [_p("L", "chimney top, long side (quoted)", None, 4), _p("W", "chimney top, short side (quoted)", None, 4)]
SKIRT = _p("skirt", "skirt / turn-down", 3, 1, 12)                      # Alan: «standard skirt is three inches» [1:06:04]
LEGS = _p("legs", "leg height (screen opening + laps)", 10, 2, 36)      # Alan: «10 inch legs is normal… opening of eight» [1:07:01]
MESH = _p("mesh", "mesh screen 1 = yes, 0 = no", 1, 0, 1, "")
BASE = {"key": "base", "label": "base", "kind": "choice", "options": ["auto", "masonry", "flashing"], "default": "auto"}
FLUES = {"key": "flues", "label": "flues [{d, x, y}]", "kind": "list", "min": 0, "max": 0, "default": []}


# --- shared parts ---------------------------------------------------------------------------------------------------

def base_kind(p, group):
    """Alan [24:18]: a brick chimney → the masonry model; a wood chase or a flue → a single flashing."""
    b = p.get("base", "auto")
    return b if b != "auto" else ("masonry" if group == "brick" else "flashing")


#: the fasteners that hold a cap down, by its base: Tapcons 1/4″ × 1-3/4″ into a brick chimney, #10 hex screws into
#: a chase or a flue's flashing — through the skirt, ≤ ANCHOR_PITCH apart and two a side at least. The same rule
#: places them in FPG's FreeCAD library (apps/chimney-services/cad, FPG-604: 14 at 30 × 24).
ANCHOR_PITCH = 12.0


def anchors(p, group):
    """(tapcons, screws, note) for a cap's base."""
    def per_side(s):
        return max(2, math.ceil(s / ANCHOR_PITCH) + 1)
    n = 2 * per_side(p["L"]) + 2 * per_side(p["W"])
    note = (f"ASSUMED (industry; the FreeCAD library's rule): {n} anchors through the skirt, ≤ {ANCHOR_PITCH:g} in apart, "
            f"two a side at least — ")
    if base_kind(p, group) == "masonry":
        return n, 0, note + "Tapcons 1/4 × 1-3/4 into the brick"
    return 0, n, note + "#10 hex screws into the chase or the flue's flashing"


def masonry_base(L, W, skirt, m, notes):
    """Alan: four strips 10½″ wide — two M (L), two F (W + 1½) — for a 3″ skirt. The shop's installs (William's photos
    p27, p28, p29, t09, 2026-11-01) show what they fold into: a HOOD — the skirt down the chimney's side, a shoulder
    sloping up and in at about 45°, and a short flat lip at the frame where the legs stand. ASSUMED split of the strip:
    skirt + ½″ fold, the shoulder, a 2″ lip; a deeper skirt widens the strip by the difference."""
    w = 10.5 + (skirt - 3)
    if skirt != 3:
        notes.append(f"ASSUMED: a {skirt:g} in skirt makes the masonry strips {w:g} in wide (10.5 for 3 in, Alan)")
    lip = 2.0
    slant = max(w - skirt - HEM - lip, 1.0)
    run = rise = slant / math.sqrt(2)
    notes.append(f"ASSUMED: each masonry strip = {skirt:g} in skirt + ½ in fold + {slant:.2f} in shoulder at 45° + {lip:g} in lip "
                 f"(the hood of the shop's brick installs)")

    def build():
        from build123d import Pos
        t = m.t
        out = [Pos(-L / 2 - t, -W / 2 - t, -skirt) * plate(L + 2 * t, t, skirt), Pos(-L / 2 - t, W / 2, -skirt) * plate(L + 2 * t, t, skirt),
               Pos(-L / 2 - t, -W / 2, -skirt) * plate(t, W, skirt), Pos(L / 2, -W / 2, -skirt) * plate(t, W, skirt)]
        lo = [(-L / 2, -W / 2, 0), (L / 2, -W / 2, 0), (L / 2, W / 2, 0), (-L / 2, W / 2, 0)]
        hi = [(-L / 2 + run, -W / 2 + run, rise), (L / 2 - run, -W / 2 + run, rise), (L / 2 - run, W / 2 - run, rise), (-L / 2 + run, W / 2 - run, rise)]
        out += [polygon_plate([lo[k], lo[(k + 1) % 4], hi[(k + 1) % 4], hi[k]], m.t) for k in range(4)]
        l2, w2 = L - 2 * run, W - 2 * run
        out += [Pos(-l2 / 2, -w2 / 2, rise) * plate(l2, lip, t), Pos(-l2 / 2, w2 / 2 - lip, rise) * plate(l2, lip, t),
                Pos(-l2 / 2, -w2 / 2 + lip, rise) * plate(lip, w2 - 2 * lip, t), Pos(l2 / 2 - lip, -w2 / 2 + lip, rise) * plate(lip, w2 - 2 * lip, t)]
        return out

    return [Part("bottom strip M", (L, w), 2, bends=3, build=build),
            Part("bottom strip F", (W + EARS, w), 2, bends=3)], rise, run


def band(l, w, z0, h, m, name, notes, why):
    """A band of sheet all round the frame (the photos' top band under the lid, the rail under the mesh): two M strips
    (l) and two F (w + 1½), each its height + a ½″ fold top and bottom, riveted to the legs."""
    notes.append(f"{why}: {name} {h:g} in all round")

    def build():
        from build123d import Pos
        t = m.t
        return [Pos(-l / 2, -w / 2, z0) * plate(l, t, h), Pos(-l / 2, w / 2 - t, z0) * plate(l, t, h),
                Pos(-l / 2, -w / 2, z0) * plate(t, w, h), Pos(l / 2 - t, -w / 2, z0) * plate(t, w, h)]

    return [Part(f"{name} M", (l, h + 2 * HEM), 2, bends=2, rivets=2, build=build),
            Part(f"{name} F", (w + EARS, h + 2 * HEM), 2, bends=2, rivets=2)]


def flashing_base(L, W, skirt, m, notes, flues):
    """Alan: the single flashing is (L + 7) × (W + 7) for a 3″ turn-down, 2″ more for each inch deeper — the top
    L × W, the turn-down each side and a ½″ fold. A hole and a collar per flue (ASSUMED collar 3″, a 1″ lap)."""
    extra = 7 + 2 * (skirt - 3)
    if skirt < 3:
        notes.append(f"ASSUMED: a {skirt:g} in turn-down shrinks the flashing by Alan's rule (+{extra:g})")
    holes = flues or [{"d": 8, "x": 0, "y": 0}]
    if not flues:
        notes.append("ASSUMED: one 8 in flue, centred (the job named none)")

    def build():
        from build123d import Align, Box, Cylinder, Pos
        top = (Align.CENTER, Align.CENTER, Align.MAX)
        pan = Box(L, W, skirt, align=top) - Pos(0, 0, -m.t) * Box(L - 2 * m.t, W - 2 * m.t, skirt, align=top)
        for f in holes:
            pan = pan - Pos(f["x"], f["y"], 0) * Cylinder(f["d"] / 2, 4 * m.t)
        return pan

    parts = [Part("bottom flashing", (L + extra, W + extra), 1, bends=8, rivets=0, build=build)]
    for i, f in enumerate(holes):
        d = f["d"]

        def collar(f=f, d=d):
            from build123d import Align, Cylinder, Pos
            up = (Align.CENTER, Align.CENTER, Align.MIN)
            return Pos(f["x"], f["y"], 0) * (Cylinder(d / 2 + m.t, 3, align=up) - Cylinder(d / 2, 4, align=up))

        parts.append(Part(f"collar {i + 1} (dia {d:g})", (math.pi * (d + m.t) + 1, 4), 1, bends=1, rivets=4, build=collar))
    return parts


def legs(l, w, z0, h, m, notes, blank_h, mid=False, pw=3.0):
    """Angle legs in the four corners of the l × w frame, each cut 2·pw wide and folded once; long caps add posts
    (Alan: two more past 48″, four past 70″). Two rivets at each end."""
    n_extra = 4 if l > 70 else 2 if (l > 48 or mid) else 0

    def build():
        from build123d import Pos
        out = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                x = sx * l / 2 - (pw if sx > 0 else 0)
                y = sy * w / 2 - (pw if sy > 0 else 0)
                xe = sx * l / 2 - (m.t if sx > 0 else 0)
                ye = sy * w / 2 - (m.t if sy > 0 else 0)
                out += [Pos(x, ye, z0) * plate(pw, m.t, h), Pos(xe, y, z0) * plate(m.t, pw, h)]
        for i in range(n_extra):
            x = -l / 2 + l * (i // 2 + 1) / (n_extra // 2 + 1) - pw / 2
            y = w / 2 - m.t if i % 2 else -w / 2
            out.append(Pos(x, y, z0) * plate(pw, m.t, h))
        return out

    parts = [Part("leg", (blank_h, 2 * pw), 4, bends=1, rivets=4, build=build)]
    if n_extra:
        parts.append(Part("leg", (blank_h, 2 * pw - 1), n_extra, bends=1, rivets=4))
    return parts


def mesh_band(l, w, z0, h, notes):
    """The spark-arrestor mesh all round the opening, priced by area. IRC R1003.9: ≥ 4 × the flue's area open,
    stops a ½″ sphere — the builder's full band of the leg height clears it on any cap this size."""
    area = 2 * (l + w) * (h + 1.0)
    notes.append(f"ASSUMED: mesh band {2 * (l + w):g} in round × {h + 1:g} in (½ in lapped each edge), ¾ in mesh")

    def build():
        from build123d import Pos
        t = 0.02
        return [Pos(-l / 2, -w / 2, z0) * plate(l, t, h), Pos(-l / 2, w / 2 - t, z0) * plate(l, t, h),
                Pos(-l / 2, -w / 2, z0) * plate(t, w, h), Pos(l / 2 - t, -w / 2, z0) * plate(t, w, h)]

    return Part("mesh screen", (0, 0), 1, mesh_in2=area, build=build)


def flat_lid(l, w, o, turn, z0, m, name="lid", rule=None, cross_break=True):
    """A flat lid over an l × w frame with overhang o: a turn-down `turn` and a ½″ fold each side (Alan's T-top top
    is L + 5: a 2″ turn-down + ½″ fold, no overhang [32:47]); an X cross-break sheds the water (industry, 2 bends)."""
    lo, wo = l + 2 * o, w + 2 * o
    blank = rule or (lo + 2 * (turn + HEM), wo + 2 * (turn + HEM))

    def build():
        from build123d import Pos
        return [Pos(-lo / 2, -wo / 2, z0 + turn) * plate(lo, wo, m.t),
                Pos(-lo / 2, -wo / 2, z0) * plate(lo, m.t, turn), Pos(-lo / 2, wo / 2 - m.t, z0) * plate(lo, m.t, turn),
                Pos(-lo / 2, -wo / 2, z0) * plate(m.t, wo, turn), Pos(lo / 2 - m.t, -wo / 2, z0) * plate(m.t, wo, turn)]

    return Part(name, blank, 1, bends=8 + (2 if cross_break else 0), rivets=0, build=build)


def hip_faces(LL, WW, rise, z0, m, panels_long=1):
    """A hipped roof over LL × WW: two trapezoids (L) to a ridge LL − WW, two triangles (W). Each face is cut from
    the rectangle it fits in; a long face may be several seamed panels."""
    ridge = max(LL - WW, 0)
    s = math.hypot(rise, WW / 2)

    def build():
        c = [(-LL / 2, -WW / 2, z0), (LL / 2, -WW / 2, z0), (LL / 2, WW / 2, z0), (-LL / 2, WW / 2, z0)]
        r0, r1 = (-ridge / 2, 0, z0 + rise), (ridge / 2, 0, z0 + rise)
        return [polygon_plate([c[0], c[1], r1, r0], m.t), polygon_plate([c[2], c[3], r0, r1], m.t),
                polygon_plate([c[1], c[2], r1], m.t), polygon_plate([c[3], c[0], r0], m.t)]

    return ridge, s, build


def hours_by_work(p, parts, base=0.5, why="ASSUMED: 0.5 h set-up + 2.4 min a bend + 0.6 min a rivet"):
    """Labour from the work itself where Alan gave no hours — calibrated so his turtle (1.5 h [41:33]) comes out
    1.5: set-up, then each brake bend and each rivet."""
    bends = sum(x.bends * x.qty for x in parts)
    rivets = sum(x.rivets * x.qty for x in parts)
    return round(base + bends * 0.04 + rivets * 0.01, 2), f"{why}: {bends} bends, {rivets} rivets"


def flues_of(p):
    return [{"d": float(f["d"]), "x": float(f.get("x", 0)), "y": float(f.get("y", 0))} for f in p.get("flues") or []]


def framed(p, m, notes, group, inset):
    """The lower half most caps share: the base by chimney type, then legs on the l × w frame. Returns (parts, z of
    the leg feet, l, w)."""
    L, W, skirt = p["L"], p["W"], p["skirt"]
    if base_kind(p, group) == "masonry":
        parts, z, run = masonry_base(L, W, skirt, m, notes)
        l, w = L - 2 * run, W - 2 * run
        blank_h = p.get("legs", 0) + 0.5                             # Alan: 10½ legs for the normal 10
    else:
        parts = flashing_base(L, W, skirt, m, notes, flues_of(p))
        z, l, w = 0.0, L - 2 * inset, W - 2 * inset
        blank_h = p.get("legs", 0)
    return parts, z, l, w, blank_h


# --- the gallery ----------------------------------------------------------------------------------------------------

def _pan(p, m):
    L, W, skirt = p["L"], p["W"], p["skirt"]
    notes = ["ASSUMED (industry dummy cap): one tray, skirt + ½ in fold, a low X cross-break top; no legs, no mesh"]
    rise = 0.0196 * L                                                  # builder: the top's low peak

    def build():
        from build123d import Pos
        ridge, s, faces = hip_faces(L, W, rise, 0, m)
        return [Pos(-L / 2, -W / 2, -skirt) * plate(L, m.t, skirt), Pos(-L / 2, W / 2 - m.t, -skirt) * plate(L, m.t, skirt),
                Pos(-L / 2, -W / 2, -skirt) * plate(m.t, W, skirt), Pos(L / 2 - m.t, -W / 2, -skirt) * plate(m.t, W, skirt),
                *faces()]

    blank = (m.base_flat(L) + 2 * m.flange_flat(skirt) + 2 * HEM, m.base_flat(W) + 2 * m.flange_flat(skirt) + 2 * HEM)
    return [Part("tray", blank, 1, bends=8 + 4, rivets=4, note="4 corner tabs riveted", build=build)], notes


def _standard(p, m):
    notes = []
    parts, z, l, w, blank_h = framed(p, m, notes, "brick", inset=0.066 * p["L"])
    h = p["legs"]
    o = max(1.5, 0.08 * p["W"])                                        # photos t05/t08/t09: the lid ~8 % past the frame
    notes.append(f"photos (t05, t08, t09): lid {o:.2f} in past the frame (~8 %); Alan's 2 in turn-down + ½ in fold; X cross-break")
    parts += legs(l, w, z, h, m, notes, blank_h, mid=True)
    if p["mesh"]:
        parts += band(l, w, z, 1.5, m, "bottom rail", notes, "photos (p27, p29)")
        parts.append(mesh_band(l, w, z, h, notes))
    if p.get("band"):
        parts += band(l, w, z + h - p["band"], p["band"], m, "top band", notes, "photos (top band under the lid)")
    parts.append(flat_lid(l, w, o, 2.0, z + h, m))
    return parts, notes


def _pitched(p, m):
    """The shop's hip-roof caps (photos p27, p28, p29, t03): the hood base, corner legs, a bottom rail and mesh, an
    optional top band (p29), then a hip lid ~10 % past the frame: a fascia/drip of ~5 %, four faces (two trapezoids to a
    short ridge, two triangles), the hips and the ridge closed by seam strips — no seams across the faces."""
    notes = []
    parts, z, l, w, blank_h = framed(p, m, notes, "brick", inset=0.07 * p["L"])
    h = p["legs"]
    o = max(1.5, 0.10 * p["W"])
    parts += legs(l, w, z, h, m, notes, blank_h)
    if p["mesh"]:
        parts += band(l, w, z, 1.5, m, "bottom rail", notes, "photos (p27, p29)")
        parts.append(mesh_band(l, w, z, h, notes))
    if p.get("band"):
        parts += band(l, w, z + h - p["band"], p["band"], m, "top band", notes, "photo p29 (a frieze under the lid)")
    LL, WW = l + 2 * o, w + 2 * o
    fascia = max(0.05 * p["W"], 1.5)

    def fascia_build():
        from build123d import Pos
        t, z0 = m.t, z + h
        return [Pos(-LL / 2, -WW / 2, z0) * plate(LL, t, fascia), Pos(-LL / 2, WW / 2 - t, z0) * plate(LL, t, fascia),
                Pos(-LL / 2, -WW / 2, z0) * plate(t, WW, fascia), Pos(LL / 2 - t, -WW / 2, z0) * plate(t, WW, fascia),
                Pos(-LL / 2, -WW / 2, z0 + fascia - t) * plate(LL, o + 0.5, t), Pos(-LL / 2, WW / 2 - o - 0.5, z0 + fascia - t) * plate(LL, o + 0.5, t),
                Pos(-LL / 2, -WW / 2, z0 + fascia - t) * plate(o + 0.5, WW, t), Pos(LL / 2 - o - 0.5, -WW / 2, z0 + fascia - t) * plate(o + 0.5, WW, t)]

    parts.append(Part("eave fascia M", (LL + 1, fascia + o + 2 * HEM), 2, bends=3, rivets=3,
                      note="fascia + drip + the soffit back to the frame", build=fascia_build))
    parts.append(Part("eave fascia F", (WW + EARS, fascia + o + 2 * HEM), 2, bends=3, rivets=3))
    rise = p["pitch"] / 12 * WW / 2
    ridge, s, faces = hip_faces(LL, WW, rise, z + h + fascia, m)
    s_end = math.hypot(rise, (LL - ridge) / 2)
    parts.append(Part("roof face M", (LL + 2 * SEAM, s + HEM + SEAM), 2, bends=3, rivets=0,
                      note=f"trapezoid {LL:.1f} → ridge {ridge:.1f}, slant {s:.2f}", build=faces))
    parts.append(Part("roof face F", (WW + 2 * SEAM, s_end + HEM + SEAM), 2, bends=3, rivets=0, note=f"triangle, slant {s_end:.2f}"))
    hips = 4 * math.sqrt(rise ** 2 + (WW / 2) ** 2 + (WW / 2) ** 2) + ridge
    parts.append(Part("hip + ridge seam strip", (hips, 2.5), 1, bends=2, rivets=8, note="one strip cut along the sheet"))
    notes.append(f"photos: {p['pitch']:g}/12 pitch, lid {o:.2f} in past the frame (~10 %), fascia {fascia:.2f} in; "
                 f"hips and ridge seam-stripped, faces unseamed")
    return parts, notes


def _bell(p, m):
    notes = []
    L = p["L"]
    parts, z, l, w, blank_h = framed(p, m, notes, "brick", inset=0.09221 * L)
    h = p["legs"]
    parts += legs(l, w, z, h, m, notes, blank_h)
    if p["mesh"]:
        parts.append(mesh_band(l, w, z, h, notes))
    # builder's hood: a quarter-ellipse from the eave (overhang o) in by `inn` and up by `H`, then a crown wall
    o, inn, H, crown = 0.07695 * L, 0.172 * L, 0.20933 * L, 0.07341 * L
    facets = 5                                                         # builder facetsW=5; Alan: straight bends only
    pts = [(inn * math.sin(t * math.pi / 2 / facets), H * (1 - math.cos(t * math.pi / 2 / facets))) for t in range(facets + 1)]
    dev = sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) + crown + HEM + 1
    LL, WW = l + 2 * o, w + 2 * o
    cl, cw = LL - 2 * inn, WW - 2 * inn
    z0 = z + h

    def build():
        from build123d import Pos
        out = []
        rings = [(LL - 2 * a, WW - 2 * a, z0 + b) for a, b in pts] + [(cl, cw, z0 + H + crown)]
        for (l0, w0, h0), (l1, w1, h1) in zip(rings, rings[1:]):
            r0 = [(-l0 / 2, -w0 / 2, h0), (l0 / 2, -w0 / 2, h0), (l0 / 2, w0 / 2, h0), (-l0 / 2, w0 / 2, h0)]
            r1 = [(-l1 / 2, -w1 / 2, h1), (l1 / 2, -w1 / 2, h1), (l1 / 2, w1 / 2, h1), (-l1 / 2, w1 / 2, h1)]
            out += [polygon_plate([r0[k], r0[(k + 1) % 4], r1[(k + 1) % 4], r1[k]], m.t) for k in range(4)]
        out.append(Pos(-cl / 2, -cw / 2, z0 + H + crown) * plate(cl, cw, m.t))
        return out

    parts += [Part("bell side M", (LL + 2 * SEAM, dev), 2, bends=facets + 2, rivets=4,
                   note=f"{facets} facets on the brake, developed {dev:.2f}", build=build),
              Part("bell side F", (WW + EARS + 2 * SEAM, dev), 2, bends=facets + 2, rivets=4),
              Part("bell crown", (cl + 2, cw + 2), 1, bends=4, rivets=4)]
    notes.append(f"builder's bell: overhang {o:.2f}, sweep in {inn:.2f} and up {H:.2f}, crown {crown:.2f}; "
                 f"ASSUMED: {facets} straight facets per side (Alan bends straight lines only), seamed hips")
    return parts, notes


def _cube(p, m):
    """Alan (MEET-41 [53:08]): bottom flashing +7, top flashing +5, legs 22 × 6, slats 5½″ — 8 each way; the builder
    stacks them as courses of blades with gaps under a hip top."""
    L, W = p["L"], p["W"]
    notes = ["Alan: 8 slats 5.5 in each way stack as 4 courses (builder: 3 blades + the lid band); "
             "OPEN: his «18 inch» folded piece [14:38]"]
    td = p["skirt"]
    blade, gap = 0.0252 * L + 2.5, 0.0456 * L

    def build():
        from build123d import Pos
        out = []
        for i in range(4):
            zz = 0.03 * L + i * (blade + gap)
            out += [Pos(-L / 2, -W / 2, zz) * plate(L, m.t, blade), Pos(-L / 2, W / 2 - m.t, zz) * plate(L, m.t, blade),
                    Pos(-L / 2, -W / 2, zz) * plate(m.t, W, blade), Pos(L / 2 - m.t, -W / 2, zz) * plate(m.t, W, blade)]
        top = 0.03 * L + 4 * (blade + gap)
        ridge, s, faces = hip_faces(L, W, 0.0364 * L, top, m)
        return out + faces()

    extra = 7 + 2 * (td - 3)
    return [Part("bottom flashing", (L + extra, W + extra), 1, bends=8),
            Part("top flashing", (L + 5, W + 5), 1, bends=8, build=build),
            Part("leg", (22, 6), 4, bends=1, rivets=4),
            Part("slat M", (L, 5.5), 8, bends=2, rivets=2),
            Part("slat F", (W + EARS, 5.5), 8, bends=2, rivets=2)], notes


def _chase(p, m):
    L, W, skirt = p["L"], p["W"], p["skirt"]
    fl = flues_of(p)
    notes = ["ASSUMED (industry chase cover): one blank, X cross-break, skirt with a drip kick and a ½ in fold, "
             "a 3 in collar per flue (Alan gave no rules)"]
    blank = (m.base_flat(L) + 2 * m.flange_flat(skirt) + 2 * HEM, m.base_flat(W) + 2 * m.flange_flat(skirt) + 2 * HEM)

    def build():
        from build123d import Align, Box, Cylinder, Pos
        top = (Align.CENTER, Align.CENTER, Align.MAX)
        c = Box(L, W, skirt, align=top) - Pos(0, 0, -m.t) * Box(L - 2 * m.t, W - 2 * m.t, skirt, align=top)
        for f in fl:
            c = c - Pos(f["x"], f["y"], 0) * Cylinder(f["d"] / 2, 4 * m.t)
        return c

    parts = [Part("cover", blank, 1, bends=8 + 2, build=build)]
    for i, f in enumerate(fl):
        d = f["d"]

        def collar(f=f, d=d):
            from build123d import Align, Cylinder, Pos
            up = (Align.CENTER, Align.CENTER, Align.MIN)
            return Pos(f["x"], f["y"], 0) * (Cylinder(d / 2 + m.t, 3, align=up) - Cylinder(d / 2, 4, align=up))

        parts.append(Part(f"collar {i + 1} (dia {d:g})", (math.pi * (d + m.t) + 1, 4), 1, bends=1, rivets=6, build=collar))
    return parts, notes


def _tee(p, m):
    """Alan's T-top (MEET-41): top L + 5 × W + 5 [32:47] on legs; the base by chimney type."""
    notes = []
    L, W = p["L"], p["W"]
    parts, z, l, w, blank_h = framed(p, m, notes, "flue", inset=0.0)
    h = p["legs"]
    parts += legs(l, w, z, h, m, notes, blank_h)
    if p["mesh"]:
        parts.append(mesh_band(l, w, z, h, notes))
    b = p["band"] if p.get("band") is not None and p["band"] >= 0 else max(2.5, 0.07 * l)
    if b:
        parts += band(l, w, z + h - b, b, m, "top band", notes, "photos t04, t10, t11 (a band under the lid, ~7 %)")
    parts.append(flat_lid(l, w, 0, 2.0, z + h, m, name="top flashing", rule=(l + 5, w + 5), cross_break=False))
    return parts, notes


def _turtle(p, m):
    """Alan (MEET-41): bottom L+7 × W+7, sides 12″ (M = L, F = W + 1½), top L−4 × W−4, legs 18 × 6 (+2 × 18 × 5
    past 48″). The builder's shell over the legs: a fascia 0.0433·L, then a slope in 0.0951·L (= Alan's 3″ each side,
    the top square L − 6) and up 0.0855·L, the top closed."""
    notes = []
    L, W = p["L"], p["W"]
    parts, z, l, w, _ = framed(p, m, notes, "flue", inset=0.0)
    h = p["legs"]
    parts += legs(L, W, z, h, m, notes, h, pw=max(0.0666 * L / 2, 1.5))
    if p["mesh"]:
        parts.append(mesh_band(L, W, z, h, notes))
    fascia, run, rise = 0.0433 * L, 3.0, 0.0855 * L
    z0 = z + h

    def build():
        from build123d import Pos
        lo = [(-L / 2, -W / 2, z0 + fascia), (L / 2, -W / 2, z0 + fascia), (L / 2, W / 2, z0 + fascia), (-L / 2, W / 2, z0 + fascia)]
        hi = [(-L / 2 + run, -W / 2 + run, z0 + fascia + rise), (L / 2 - run, -W / 2 + run, z0 + fascia + rise),
              (L / 2 - run, W / 2 - run, z0 + fascia + rise), (-L / 2 + run, W / 2 - run, z0 + fascia + rise)]
        out = [polygon_plate([lo[k], lo[(k + 1) % 4], hi[(k + 1) % 4], hi[k]], m.t) for k in range(4)]
        out += [Pos(-L / 2, -W / 2, z0) * plate(L, m.t, fascia), Pos(-L / 2, W / 2 - m.t, z0) * plate(L, m.t, fascia),
                Pos(-L / 2, -W / 2, z0) * plate(m.t, W, fascia), Pos(L / 2 - m.t, -W / 2, z0) * plate(m.t, W, fascia),
                Pos(-L / 2 + run, -W / 2 + run, z0 + fascia + rise) * plate(L - 2 * run, W - 2 * run, m.t)]
        return out

    parts += [Part("side M", (L, 12), 2, bends=2, rivets=2, build=build),
              Part("side F", (W + EARS, 12), 2, bends=2, rivets=2),
              Part("top", (L - 4, W - 4), 1, bends=4, rivets=1)]
    if base_kind(p, "flue") == "flashing":
        # Alan's turtle legs are 18 × 6; the leg part above was cut at the job's height — keep his 18 when standard
        for x in parts:
            if x.name == "leg" and h == 18:
                x.blank = (18, x.blank[1] if x.blank[1] in (5, 6) else 6)
    return parts, notes


def _bishop(p, m):
    """The builder's bishop: a gothic arch (two arcs of radius R = 1.047·L meeting at the top, ≈ 0.893·L tall)
    run along W, a back wall of the same shape, a front frame round the open face, a deck with the flue hole.
    Alan bends straight lines only: the arch is cut as facets (ASSUMED 6 a side)."""
    notes = []
    L, W = p["L"], p["W"]
    parts, z, _, _, _ = framed(p, m, notes, "flue", inset=0.0)
    R = max(L / 2 + 0.01, 1.047 * L)
    cx = R - L / 2
    H = math.sqrt(R * R - cx * cx)
    n = 6
    xs = [-L / 2 + (L / 2) * i / n for i in range(n + 1)]
    arc = [(x, math.sqrt(max(R * R - (x - cx) ** 2, 0))) for x in xs]
    half = sum(math.dist(a, b) for a, b in zip(arc, arc[1:]))
    zf = z + p["skirt"] * 0 + 0.0

    def build():
        pts = arc + [(-x, y) for x, y in reversed(arc[:-1])]
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out.append(polygon_plate([(x0, -W / 2, zf + y0), (x1, -W / 2, zf + y1), (x1, W / 2, zf + y1), (x0, W / 2, zf + y0)], m.t))
        back = [(x, -W / 2 + 0.05, zf + y) for x, y in pts]
        out.append(polygon_plate(back, m.t))
        return out

    parts += [Part("mitre shell half", (half + SEAM + HEM, W + 1), 2, bends=n + 1, rivets=6,
                   note=f"arch R {R:.2f}, {n} facets a side, developed {half:.2f}", build=build),
              Part("back wall", (L + 1, H + 1), 1, bends=2, rivets=6, outline=None, note="cut to the arch"),
              Part("front frame", (L + 1, H + 1), 1, bends=2, rivets=6, note="the arch less the opening (frame 0.064·L)")]
    if p["mesh"]:
        parts.append(Part("mesh (front opening)", (0, 0), 1, mesh_in2=0.7 * L * H * 0.75))
    notes.append(f"builder's bishop arch: R {R:.2f}, height {H:.2f}; ASSUMED {n} straight facets a side, front open")
    return parts, notes


def _tee_hours(p, parts):
    return hours_by_work(p, parts)


def _turtle_hours(p, parts):
    return 1.5, "Alan: about 1.5 h (a 24 × 24 single flashing [41:33]); the services app's 1.5 h"


style(Style("pan", "Dummy Cap (no hole)", "brick", [*SIZE, SKIRT], _pan, hours_by_work,
            "Industry dummy cap (Riverside NV006); builder's low top; ASSUMED"))
TOP_BAND = _p("band", "top band under the lid (0 = none)", 0, 0, 12)
style(Style("standard", "Standard", "brick", [*SIZE, SKIRT, LEGS, MESH, BASE, FLUES, TOP_BAND], _standard, hours_by_work,
            "Alan's masonry base + legs (MEET-41); the shop's installs (photos t05, t08, t09): hood, rail, mesh, lid ~8 % over"))
style(Style("pitched", "Pitched Roof Standing Seam", "brick",
            [*SIZE, SKIRT, LEGS, MESH, BASE, FLUES, TOP_BAND, _p("pitch", "roof pitch (rise in 12)", 5, 2, 12, "/12")],
            _pitched, hours_by_work,
            "Alan's masonry base (MEET-41); the shop's hip caps (photos p27, p28, p29, t03): 15–30° hip, ~10 % over, seam-stripped hips"))
style(Style("bell", "Bell Top", "brick", [*SIZE, SKIRT, LEGS, MESH, BASE, FLUES], _bell, hours_by_work,
            "Alan's masonry base (MEET-41); builder's bell hood, faceted"))
style(Style("cube", "Modern Cube", "brick", [*SIZE, SKIRT], _cube, hours_by_work,
            "Alan, MEET-41 [53:08]: bottom +7, top +5, legs 22 × 6, slats 5.5 in, 8 each way"))
style(Style("chase", "Chase Cover", "flue", [*SIZE, SKIRT, FLUES], _chase, hours_by_work,
            "Industry chase cover (Rockford, K&M, Riverside); ASSUMED"))
style(Style("tee", "T-Top", "flue", [*SIZE, SKIRT, LEGS, _p("mesh", "mesh screen", 0, 0, 1, ""), BASE, FLUES,
                                     _p("band", "top band under the lid (-1 = the shop's ~7 %)", -1, -1, 12)], _tee,
            _tee_hours, "Alan, MEET-41: top L+5 [32:47]; masonry or single-flashing base by chimney [24:18]"))
style(Style("turtle", "Turtle Top", "flue", [*SIZE, SKIRT, _p("legs", "leg height", 18, 2, 36), _p("mesh", "mesh screen", 0, 0, 1, ""),
                                            BASE, FLUES], _turtle, _turtle_hours,
            "Alan, MEET-41: bottom L+7, sides 12, top L−4, legs 18 × 6 [28:12]; builder's shell"))
style(Style("bishop", "Bishop", "flue", [*SIZE, SKIRT, _p("mesh", "mesh screen", 0, 0, 1, ""), BASE, FLUES], _bishop,
            hours_by_work, "Builder's gothic mitre; base by chimney (Alan); ASSUMED facets"))
