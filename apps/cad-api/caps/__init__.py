"""Dynamic cap replicas (DGO-1076): a cap style is a function of the job's own cap details → sheet-metal parts.

    STYLES[id] = Style(id, title, group, params, parts(p, metal) -> (parts, notes), hours(p, parts) -> (h, why))
    build(style, job)  -> {params, metal, parts, notes}          (no CAD kernel needed)
    quote(style, job, prices) -> {pieces, sheets, bom, cost, notes, …}
    model(style, job)  -> one build123d Compound of every part as it sits on the cap (folded)

A part is cut as a rectangle and bent on straight lines (Alan: «30–40 degree straight line bends» only [59:38]),
so its blank is what nesting packs and the sheets are counted by; the 3D is the same part folded. Where Alan gave
the cut rule (MEET-41) the blank IS his rule; everything else is marked ASSUMED in `notes` with its source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import cost as costing
from .sm import Metal, Part, metal_for

STYLES: dict = {}


@dataclass
class Style:
    id: str
    title: str
    group: str                      # brick (over the crown) | flue (over one flue or the chase)
    params: list                    # [{key, label, unit, min, max, default}]
    parts: Callable                 # (p, metal) -> (list[Part], notes)
    hours: Callable                 # (p, parts) -> (hours, why)
    source: str = ""


def style(s: Style) -> Style:
    STYLES[s.id] = s
    return s


def get(sid: str) -> Style:
    s = STYLES.get(str(sid or "").strip().lower())
    if s is None:
        raise KeyError(f"no cap style {sid!r}: one of {', '.join(sorted(STYLES))}")
    return s


def params_from(st: Style, job: dict) -> dict:
    """The style's parameters from a job's cap details (the services app's own keys accepted as they are)."""
    from families import check
    raw = dict(job.get("params") or {})
    spec = job.get("cap_spec") or {}
    if isinstance(spec, str):
        import json
        spec = json.loads(spec)
    keys = {p["key"] for p in st.params}
    if spec:
        # the builder's record (flow.js spec()): the quoted size is measured + ½″ clearance; holes by their edges
        out = spec.get("outside") or {}
        q = out.get("quoted") or {}
        raw.setdefault("L", q.get("A") or out.get("length"))
        raw.setdefault("W", q.get("B") or out.get("width"))
        if "skirt" in keys and spec.get("skirt") not in (None, "", "n/a"):
            raw.setdefault("skirt", spec["skirt"])
        if "legs" in keys and str(spec.get("legsInches") or "").strip() not in ("", "n/a", "None"):
            raw.setdefault("legs", spec["legsInches"])
        if "mesh" in keys and spec.get("meshScreen") is not None:
            raw.setdefault("mesh", 1 if spec["meshScreen"] else 0)
        if "base" in keys and spec.get("chimney") in ("brick", "flue"):
            raw.setdefault("base", "masonry" if spec["chimney"] == "brick" else "flashing")
        if "flues" in keys and spec.get("holes"):
            L, W = float(raw["L"]), float(raw["W"])
            fl = []
            for h in spec["holes"]:
                d = float(h.get("diameter") or 8)
                left = h.get("centreFromLeft")
                top = h.get("centreFromTop")
                cx = float(left) if left is not None else float(h.get("fromLeft") or (L - d) / 2) + d / 2
                cy = float(top) if top is not None else float(h.get("fromTop") or (W - d) / 2) + d / 2
                fl.append({"d": d, "x": round(cx - L / 2, 3), "y": round(W / 2 - cy, 3)})
            raw.setdefault("flues", fl)
    dims = job.get("dims") or {}
    for a, b in (("L", "length"), ("W", "width"), ("L", "a_len"), ("W", "a_wid")):
        if raw.get(a) is None and b in dims:
            raw[a] = dims[b]
    for key in keys:
        if key not in raw and key in dims:
            raw[key] = dims[key]
    raw = {k: v for k, v in raw.items() if k in keys and v is not None}
    shim = type("S", (), {"ID": st.id, "PARAMS": st.params})
    return check(shim, raw)


def build(sid: str, job: dict) -> dict:
    st = get(sid)
    p = params_from(st, job)
    spec = job.get("cap_spec") or {}
    if isinstance(spec, str):
        import json
        spec = json.loads(spec)
    metal = metal_for(job.get("material") or spec.get("material") or job.get("metal") or "galvanized",
                      job.get("gauge") or spec.get("gauge"))
    parts, notes = st.parts(p, metal)
    return {"style": st, "params": p, "metal": metal, "parts": parts, "notes": notes}


def bom_of(b: dict, sheets: int) -> dict:
    parts, metal = b["parts"], b["metal"]
    hours, why = b["style"].hours(b["params"], parts)
    rivets = sum(x.rivets * x.qty for x in parts)
    tapcons, screws, why_anchors = styles.anchors(b["params"], b["style"].group)
    return {"metal": metal.key, "gauge": metal.gauge, "sheets": sheets,
            "mesh_in2": round(sum(x.mesh_in2 * x.qty for x in parts), 1),
            "rivets": rivets, "tapcons": tapcons, "screws": screws, "anchors_why": why_anchors,
            "caulk_tubes": 0.5, "hours": hours, "hours_why": why,
            "bends": sum(x.bends * x.qty for x in parts)}


def quote(sid: str, job: dict, prices: dict | None = None) -> dict:
    import takeoff as tk
    b = build(sid, job)
    prices = prices or costing.load()
    sh = costing.sheet_for(prices, b["metal"].key)
    if isinstance(job.get("sheet"), dict):          # the caller's own stock (the services app's Prices & setup)
        sh = {**sh, "w": float(job["sheet"].get("w") or sh["w"]), "h": float(job["sheet"].get("h") or sh["h"])}
    pieces = [x.as_piece() for x in b["parts"] if x.sheet_part]
    packed = tk.pack(pieces, sh["w"], sh["h"], float(job.get("kerf") or 0))
    bom = bom_of(b, len(packed["sheets"]))
    bom["sheet_fill"] = round(sum(s["fill"] for s in packed["sheets"]), 4)     # sheets' worth of metal actually cut
    money = costing.cost(bom, prices)
    return {"style": sid, "title": b["style"].title, "params": b["params"],
            "metal": {"key": b["metal"].key, "gauge": b["metal"].gauge, "t": b["metal"].t},
            "parts": [{"name": x.name, "qty": x.qty, "blank": [round(x.blank[0], 3), round(x.blank[1], 3)],
                       "bends": x.bends, "rivets": x.rivets, "mesh_ft2": round(x.mesh_in2 / 144, 3), "note": x.note}
                      for x in b["parts"]],
            "sheets": packed["sheets"], "errors": packed["errors"], "bom": bom, "cost": money,
            "notes": b["notes"], "source": b["style"].source}


def model(sid: str, job: dict):
    from build123d import Compound
    from families.shop import model_label
    b = build(sid, job)
    kids = []
    for x in b["parts"]:
        if x.build is None:
            continue
        shapes = x.build()
        for s in shapes if isinstance(shapes, (list, tuple)) else [shapes]:
            s.label = model_label(x.name, [])
            kids.append(s)
    p = b["params"]
    return Compound(children=kids, label=model_label(f"{sid} {p.get('L', 0):g}x{p.get('W', 0):g} {b['metal'].key}",
                                                     b["notes"]))


from . import styles  # noqa: E402,F401  — registers every style
