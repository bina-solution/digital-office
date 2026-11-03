"""Chase Cover — a flat lid over the whole chase, a skirt folded down on four sides, a collar round each flue.

Alan gave no cutting rules for it (MEET-41 names it, nothing more), so this is the textbook sheet-metal
part and every rule is marked ASSUMED: one blank, four 90° bends, the flat size from the bend allowance
BA = π/2 · (r + K·t), square corner notches, each collar a strip rolled round its flue with a 1″ lap.
It is the family that shows the method end to end — a folded 3D, its flat pattern, its sheets — and it
stays ASSUMED until Alan's own numbers replace these.
"""
from __future__ import annotations

import math

from .shop import ascii_label, model_label
from .units import inches

ID = "chase"
TITLE = {"en": "Chase Cover", "he": "כיסוי ארובה"}
SOURCE = "No cutting rules from Alan yet (MEET-41 names the cap only); textbook sheet metal, every rule ASSUMED"

PARAMS = [
    {"key": "L", "label": "chase top, long side", "unit": "in", "min": 8, "max": 120, "default": None},
    {"key": "W", "label": "chase top, short side", "unit": "in", "min": 8, "max": 120, "default": None},
    {"key": "skirt", "label": "skirt height", "unit": "in", "min": 1, "max": 8, "default": 3},
    {"key": "t", "label": "sheet thickness", "unit": "in", "min": 0.01, "max": 0.1, "default": 0.024},
    {"key": "r", "label": "inside bend radius", "unit": "in", "min": 0.0, "max": 0.5, "default": 0.03},
    {"key": "K", "label": "K-factor", "unit": "", "min": 0.2, "max": 0.5, "default": 0.44},
    {"key": "collar", "label": "collar height", "unit": "in", "min": 1, "max": 12, "default": 3},
    # [{d, x, y}] — each flue's diameter and its centre from the lid's centre (inches)
    {"key": "flues", "label": "flues [{d, x, y}]", "unit": "in", "kind": "list", "min": 0, "max": 0, "default": []},
]

LAP = 1.0  # a collar strip overlaps itself by an inch where it is riveted


def bend_allowance(p: dict) -> float:
    return math.pi / 2 * (p["r"] + p["K"] * p["t"])


def flat(p: dict) -> tuple[float, float]:
    """The blank, from OUTSIDE sizes: each side loses (r + t) at both bends and gains the bend's arc."""
    lose = 2 * (p["r"] + p["t"])
    ba = bend_allowance(p)
    leg = p["skirt"] - (p["r"] + p["t"])     # the flat part of the skirt below the bend
    return (p["L"] - lose + 2 * ba + 2 * leg, p["W"] - lose + 2 * ba + 2 * leg)


def _flues(p: dict) -> list[dict]:
    out = []
    for i, f in enumerate(p.get("flues") or []):
        try:
            d, x, y = float(f["d"]), float(f.get("x", 0)), float(f.get("y", 0))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"flue {i + 1}: needs a number d (and x, y from the centre)") from None
        if not 2 <= d <= min(p["L"], p["W"]) - 2:
            raise ValueError(f"flue {i + 1}: d = {d:g} does not fit the lid")
        if abs(x) + d / 2 > p["L"] / 2 - 1 or abs(y) + d / 2 > p["W"] / 2 - 1:
            raise ValueError(f"flue {i + 1}: the hole runs off the lid")
        out.append({"d": d, "x": x, "y": y})
    return out


def pieces(p: dict) -> tuple[list[dict], list[str]]:
    fl, fw = flat(p)
    notes = [f"ASSUMED: one blank {fl:.3f} × {fw:.3f} — four 90° bends, BA {bend_allowance(p):.4f}″ each "
             f"(r {p['r']:g}, K {p['K']:g}, t {p['t']:g}), square corner notches {p['skirt']:g}″",
             "ASSUMED: no drip edge or hem — Alan has not described one"]
    out = [{"name": "lid + skirt", "w": inches(fl), "h": inches(fw), "qty": 1}]
    for i, f in enumerate(_flues(p)):
        out.append({"name": f"collar {i + 1} (⌀{f['d']:g})", "w": inches(math.pi * (f["d"] + p["t"]) + LAP),
                    "h": inches(p["collar"] + 1), "qty": 1})
    if len(out) > 1:
        notes.append("ASSUMED: a collar strip is π·(d + t) + 1″ lap long and collar + 1″ high (a ½″ tab each edge)")
    return out, notes


def consumables(p: dict) -> list[dict]:
    n = len(p.get("flues") or [])
    return [{"item": "rivet", "qty": 4 + 6 * n, "unit": "each"},            # ASSUMED
            {"item": "caulk", "qty": 0.5 + 0.25 * n, "unit": "tube"}]       # ASSUMED


def labour_hours(p: dict) -> float:
    return 1.0 + 0.5 * len(p.get("flues") or [])                            # ASSUMED


def solid(p: dict):
    """The cover as it is folded: lid on top (z = 0), skirt down, a hole and a collar per flue."""
    from build123d import Align, Box, Compound, Cylinder, Pos

    L, W, S, t = p["L"], p["W"], p["skirt"], p["t"]
    top = (Align.CENTER, Align.CENTER, Align.MAX)
    cover = Box(L, W, S, align=top) - Pos(0, 0, -t) * Box(L - 2 * t, W - 2 * t, S, align=top)
    parts = []
    for f in _flues(p):
        cover = cover - Pos(f["x"], f["y"], 0) * Cylinder(f["d"] / 2, 4 * t)
        up = (Align.CENTER, Align.CENTER, Align.MIN)
        ring = Cylinder(f["d"] / 2 + t, p["collar"], align=up) - Cylinder(f["d"] / 2, p["collar"] + 1, align=up)
        ring = Pos(f["x"], f["y"], 0) * ring
        ring.label = ascii_label(f"collar ⌀{f['d']:g}")
        parts.append(ring)
    cover.label = "lid + skirt"
    # every rule of this family is ASSUMED: the model says so as the takeoff does
    cut, notes = pieces(p)
    return Compound(children=[cover, *parts], label=model_label(f"chase cover {L:g}x{W:g} ({len(cut)} blanks)", notes))
