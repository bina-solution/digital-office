"""The takeoff: a family's pieces packed onto stock sheets, and the bill of materials of one unit.

    takeoff(fam, params, sheet_w, sheet_h, material, qty=1, kerf=0) -> {pieces, notes, sheets, bom}
    sheet_svg(sheet) -> one sheet as a standalone <svg> (the warehouse ticket's drawing)

Packing is MaxRects (rectpack), in two stages, as the services app's sheet calculator does it:
  1. every fit rule × every sort order;
  2. if that is still above the area bound, the kinds of piece laid in EVERY order (past
     ALL_ORDERS_UP_TO kinds, every ordered pair leading and the rest by area) — big-first sorts miss
     layouts a strip-heavy cut list needs (turtle 50 × 25 and 38 × 38: two sheets by stage 1, one by 2).
The fewest sheets win; among those, the biggest leftover on the emptiest sheet (the shop reuses scrap).
Pieces may turn 90°. A piece larger than the sheet either way round is an error, never a silent second
sheet. No money here: the price list turns `bom` into a price.
"""
from __future__ import annotations

import math
from itertools import permutations
from xml.sax.saxutils import escape

SCALE = 1000          # rectpack packs integers: thousandths of an inch keep halves and quarters exact
ALL_ORDERS_UP_TO = 5  # 5 kinds = 120 orders × 4 rules; 6 would be 720
MAX_QTY = 50          # one takeoff is one job; a bigger run is several (and would hold the worker)


def _u(x: float) -> int:
    return round(float(x) * SCALE)


def _run(order, sw, sh, kerf, algo, sort_algo):
    """One MaxRects pass: {sheet index: [(x, y, w, h, rid)]} with every item placed, or None."""
    from rectpack import PackingBin, newPacker

    pk = newPacker(bin_algo=PackingBin.BFF, pack_algo=algo, sort_algo=sort_algo, rotation=True)
    for rid, w, h in order:
        pk.add_rect(_u(w + kerf), _u(h + kerf), rid=rid)
    pk.add_bin(_u(sw + kerf), _u(sh + kerf), count=len(order))
    pk.pack()
    placed = pk.rect_list()
    if len(placed) != len(order):
        return None
    used = {}
    for b, x, y, w, h, rid in placed:
        used.setdefault(b, []).append((x, y, w, h, rid))
    return used


def _key(used, sheet_area_u):
    # fewest sheets; then the biggest leftover on the emptiest sheet (the smaller its fill, the bigger the offcut)
    emptiest = min(sum(w * h for _, _, w, h, _ in r) for r in used.values())
    return (len(used), emptiest - sheet_area_u)


def pack(pieces: list[dict], sheet_w: float, sheet_h: float, kerf: float = 0.0) -> dict:
    from rectpack import (SORT_AREA, SORT_LSIDE, SORT_NONE, SORT_PERI, SORT_SSIDE, MaxRectsBaf, MaxRectsBl,
                          MaxRectsBlsf, MaxRectsBssf)

    algos = (MaxRectsBssf, MaxRectsBaf, MaxRectsBlsf, MaxRectsBl)
    items, errors = [], []
    for p in pieces:
        w, h = float(p["w"]), float(p["h"])
        if not ((w <= sheet_w and h <= sheet_h) or (h <= sheet_w and w <= sheet_h)):
            errors.append(f"{p['name']} {w:g} × {h:g} is larger than a {sheet_w:g} × {sheet_h:g} sheet")
            continue
        items += [(p["name"], w, h)] * int(p["qty"])
    order = [(i, w, h) for i, (_, w, h) in enumerate(items)]
    sheet_u = _u(sheet_w + kerf) * _u(sheet_h + kerf)
    bound = math.ceil(sum(_u(w + kerf) * _u(h + kerf) for _, w, h in order) / sheet_u) if order else 0
    best = None

    def consider(used):
        nonlocal best
        if used is not None and (best is None or _key(used, sheet_u) < best[0]):
            best = (_key(used, sheet_u), used)

    if order:
        for algo in algos:                                                       # stage 1
            for sort_algo in (SORT_AREA, SORT_LSIDE, SORT_SSIDE, SORT_PERI):
                consider(_run(order, sheet_w, sheet_h, kerf, algo, sort_algo))
        if best[0][0] > bound:                                                   # stage 2
            kinds = {}
            for rid, w, h in order:
                kinds.setdefault((items[rid][0], w, h), []).append((rid, w, h))
            ks = sorted(kinds, key=lambda k: -k[1] * k[2])
            if len(ks) <= ALL_ORDERS_UP_TO:
                leads = permutations(ks)
            else:
                leads = ([a, b, *[k for k in ks if k not in (a, b)]] for a, b in permutations(ks, 2))
            for seq in leads:
                laid = [it for k in seq for it in kinds[k]]
                for algo in algos:
                    consider(_run(laid, sheet_w, sheet_h, kerf, algo, SORT_NONE))
                if best[0][0] == bound:
                    break
    sheets = []
    for _, rects in sorted((best[1] if best else {}).items()):
        placed = []
        for x, y, w, h, rid in rects:
            name, pw, ph = items[rid]
            turned = w != _u(pw + kerf)            # compared in the packer's own units: a kerf never reads as a turn
            ww, hh = (ph, pw) if turned else (pw, ph)
            placed.append({"name": name, "x": x / SCALE, "y": y / SCALE, "w": ww, "h": hh, "rotated": turned})
        area = sum(p["w"] * p["h"] for p in placed)
        sheets.append({"w": sheet_w, "h": sheet_h, "placed": placed, "used_area": round(area, 3),
                       "fill": round(area / (sheet_w * sheet_h), 4)})
    return {"sheets": sheets, "errors": errors, "area_bound": bound}


def takeoff(fam, params: dict, sheet_w: float, sheet_h: float, material: str, qty: int = 1, kerf: float = 0.0) -> dict:
    qty = int(qty or 1)
    if not 1 <= qty <= MAX_QTY:
        raise ValueError(f"qty is 1–{MAX_QTY} per takeoff, got {qty}")
    pieces, notes = fam.pieces(params)
    pieces = [{**p, "qty": int(p["qty"]) * qty, "material": material} for p in pieces]
    packed = pack(pieces, sheet_w, sheet_h, kerf)
    area = sum(p["w"] * p["h"] * p["qty"] for p in pieces)
    bom = [{"item": f"sheet {material} {sheet_w:g}×{sheet_h:g}", "qty": len(packed["sheets"]), "unit": "sheet",
            "why": f"{len(pieces)} kinds of piece, {area:,.1f} in² of metal on "
                   f"{len(packed['sheets'])} sheet(s)" if packed["sheets"] else "nothing to cut"}]
    for c in fam.consumables(params):
        bom.append({**c, "qty": c["qty"] * qty})
    bom.append({"item": "labour", "qty": round(fam.labour_hours(params) * qty, 3), "unit": "hour"})
    return {"family": fam.ID, "params": params, "qty": qty, "material": material,
            "pieces": pieces, "notes": notes, "metal_area_in2": round(area, 3),
            "sheets": packed["sheets"], "area_bound": packed["area_bound"], "errors": packed["errors"], "bom": bom}


def sheet_svg(sheet: dict, scale: float = 6.0) -> str:
    """The sheet with every piece placed and named, inches × scale px. Palette-free: line + text only."""
    W, H = sheet["w"] * scale, sheet["h"] * scale
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.1f} {H:.1f}">',
           f'<rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" fill="none" stroke="currentColor" stroke-width="2"/>']
    for p in sheet["placed"]:
        x, y, w, h = p["x"] * scale, p["y"] * scale, p["w"] * scale, p["h"] * scale
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="none" stroke="currentColor"/>')
        out.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="11" text-anchor="middle" '
                   f'fill="currentColor">{escape(p["name"])} {p["w"]:g}×{p["h"]:g}</text>')
    out.append("</svg>")
    return "\n".join(out)
