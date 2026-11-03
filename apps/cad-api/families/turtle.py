"""Turtle Top — a hipped shell over an open screen, on a single-flashing bottom.

The pieces are Alan's own rules (The Fireplace Guys, MEET-41, 2026-10-30), the same ones the services
app's sheet calculator cuts by. What he has not said is marked ASSUMED in the notes, never filled in
silently. The 3D model is the ANATOMY of those pieces — every blank laid out flat and exploded — and
not a folded shell: the fold lines of the hip were never described.
"""
from __future__ import annotations

from . import shop

ID = "turtle"
TITLE = {"en": "Turtle Top", "he": "כובע צב"}
SOURCE = "Alan, MEET-41 (2026-10-30): bottom L+7 × W+7 for a 3″ turn-down; sides 12″; top L−4 × W−4; legs 18 × 6 [28:12], two 18 × 5 more past 48″; 9 rivets, ½ tube of caulk [42:50–43:25]"

PARAMS = shop.size_params(turn_down=True)


def pieces(p: dict) -> tuple[list[dict], list[str]]:
    L, W = p["L"], p["W"]
    notes = []
    out = [
        shop.single_bottom(L, W, p["turn_down"], notes),
        shop.piece("side M", L, 12, 2),
        shop.piece("side F", W + shop.EARS, 12, 2),
        # Alan: the top square is L − 6, plus 2 for its 1″ turn-down: (L − 4) × (W − 4).
        shop.piece("top", L - 4, W - 4),
        # Alan: turtle legs are 18 × 6, and a cap longer than 48″ gets two 18 × 5 more.
        shop.piece("leg", 18, 6, 4),
        *([shop.piece("leg", 18, 5, 2)] if L > 48 else []),
    ]
    return out, notes


def consumables(p: dict) -> list[dict]:
    return [dict(c) for c in shop.RIVETS_AND_CAULK]


def labour_hours(p: dict) -> float:
    # ASSUMED (a sample, as in the services app): Alan gave 1–1½ h for a 24 × 24 single flashing [41:33, 43:34]
    return 1.5


def solid(p: dict):
    # The ASSUMED notes travel in the model's label: `/model` returns only a file, so a model-only caller
    # would otherwise never see what Alan has not said.
    parts, notes = pieces(p)
    return shop.anatomy(parts, p["t"], shop.model_label(f"turtle {p['L']:g}x{p['W']:g} anatomy", notes))
