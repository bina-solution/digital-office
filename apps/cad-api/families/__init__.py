"""Constructible families: what a product IS, as the shop builds it (DGO-1076).

A family is one module here (or one record of masonry.py, where four caps share their parts through
shop.py). It declares its parameters and, from them, three things — the flat
pieces to cut, what else a unit consumes, the hours it takes — plus its 3D model. Pricing is not
here: a family says how much metal, rivets and time; the price list says what they cost. So a new
size is never a new product, and a new metal price never touches a family.

Each module exposes:

    ID, TITLE, SOURCE                 who said so (a meeting and its timestamp), never a guess unmarked
    PARAMS                            [{key, label, unit, min, max, default}] — default None = required;
                                      kind "choice" (options) and kind "list" (of objects) are not numbers
    pieces(p)    -> (pieces, notes)   pieces: [{name, w, h, qty, material}]; notes: every ASSUMED step
    consumables(p) -> [{item, qty, unit}]
    labour_hours(p) -> float
    solid(p)     -> a build123d shape (imported lazily: the takeoff runs without the CAD kernel)

Units: inches. L is the longer side, W the shorter.
"""
from __future__ import annotations

import math

from . import chase, masonry, turtle

FAMILIES = {m.ID: m for m in (turtle, *masonry.ALL, chase)}


def get(fid: str):
    fam = FAMILIES.get(str(fid or "").strip().lower())
    if fam is None:
        raise KeyError(f"no family {fid!r}: one of {', '.join(sorted(FAMILIES))}")
    return fam


def describe(fam) -> dict:
    return {"id": fam.ID, "title": fam.TITLE, "source": fam.SOURCE,
            "params": [dict(p) for p in fam.PARAMS]}


def check(fam, raw: dict | None) -> dict:
    """The family's parameters from what was sent: every one a finite number inside its range, the
    defaults filled in, L ≥ W. A missing required one or a value out of range raises ValueError with
    its name — the caller shows that sentence, never a stack."""
    if raw is not None and not isinstance(raw, dict):
        raise ValueError("params must be an object of name → value, like {\"L\": 35, \"W\": 32}")
    raw = dict(raw or {})
    out = {}
    for spec in fam.PARAMS:
        key = spec["key"]
        v = raw.pop(key, None)
        if v is None or v == "":
            if spec.get("default") is None:
                raise ValueError(f"missing {key} ({spec['label']})")
            v = spec["default"]
        if spec.get("kind") == "choice":
            v = str(v).strip().lower()
            if v not in spec["options"]:
                raise ValueError(f"{key} is one of {', '.join(spec['options'])}, got {v!r}")
            out[key] = v
            continue
        if spec.get("kind") == "list":
            # a list of objects, or nothing: a malformed one is refused, never read as «none» (one fewer
            # collar is a cheaper wrong price)
            if not isinstance(v, (list, tuple)) or not all(isinstance(x, dict) for x in v):
                raise ValueError(f"{key} must be a list of objects, like [{{\"d\": 8, \"x\": 0, \"y\": 0}}]")
            out[key] = [dict(x) for x in v]
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number, got {v!r}") from None
        if not math.isfinite(v) or not spec["min"] <= v <= spec["max"]:
            raise ValueError(f"{key} = {v:g} is outside {spec['min']:g}–{spec['max']:g} {spec.get('unit', '')}".strip())
        out[key] = v
    if raw:
        raise ValueError(f"{fam.ID} has no parameter {', '.join(sorted(raw))}")
    if "L" in out and "W" in out and out["W"] > out["L"]:
        out["L"], out["W"] = out["W"], out["L"]
        # what sits ON the lid turns with it: x runs along L, y along W
        for x in out.get("flues") or []:
            x["x"], x["y"] = x.get("y", 0), x.get("x", 0)
    return out
