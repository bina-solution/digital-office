"""Alan's masonry caps — T-top, crown hip, Avante dome — and the Modern Cube (MEET-41, 2026-10-30).

One module per style would repeat the same masonry bottom and legs four times; each style here is a small
class-free record built by `_family`, so the API sees four families with their own ids, parameters and
sources, and the shared parts live once in shop.py. Same rules, same ASSUMED notes as the services app's
sheet calculator; their 3D is the anatomy of the pieces (their folds were never described).
"""
from __future__ import annotations

import types

from . import shop


def _ttop(p, notes):
    return [shop.top_flashing(p["L"], p["W"]), *shop.masonry_bottom(p["L"], p["W"]), *shop.masonry_legs(p["L"])]


def _crownhip(p, notes):
    L, W = p["L"], p["W"]
    # Alan: the arched top is L × (W + 10). Past W = 38 that no longer comes out of one 48″ strip, so up to 40
    # he flattens the arch (W + 8) [46:37], and beyond that he cuts the top in two halves with an inch of
    # overlap each, so the seam doesn't leak [47:02].
    if W <= 38:
        top = [shop.piece("arch top", L, W + 10)]
    elif W <= 40:
        top = [shop.piece("arch top", L, W + 8)]
        notes.append(f"flatter arch: W = {W:g} is over 38, so the top is L × (W + 8) to come out of a 48″ sheet; "
                     f"the ends are not reduced for the lower arch")
    else:
        top = [shop.piece("arch top half", L, (W + 10) / 2 + 1, 2)]
    h = p["arch_h"]
    if h == ARCH_DEFAULT:
        notes.append("ASSUMED unless measured: arch height H = 12½″ (the default), so each end is (W + 1½) × 15")
    # Alan: the two ends are triangles, cut as (W + 1½) × (H + 2½) rectangles [21:10].
    return [*top, shop.piece("arch end", W + shop.EARS, h + 2.5, 2), *shop.masonry_bottom(L, W), *shop.masonry_legs(L)]


def _avante(p, notes):
    L, W = p["L"], p["W"]
    notes.append("ASSUMED: the dome is four 24″-wide pieces, two M (L × 24) and two F ((W + 1½) × 24)")
    dome = [shop.piece("dome M", L, 24, 2), shop.piece("dome F", W + shop.EARS, 24, 2)]
    if p["base"] == "brick":
        notes.append("NOT CUT: Alan says a masonry Avante «takes a square on the top» [16:35]; its size is not known")
        return [*dome, *shop.masonry_bottom(L, W), *shop.masonry_legs(L)]
    notes.append("ASSUMED: no legs on a wood chase; Alan listed legs for Avante on brick only")
    notes.append("NOT CUT: the wood-chase bottom has a hole for the pipe [33:43]; its size is not known")
    return [shop.single_bottom(L, W, p["turn_down"], notes), *dome]


def _cube(p, notes):
    L, W = p["L"], p["W"]
    notes.append("ASSUMED: «eight for the M, eight for the F» means 8 slats 5½″ wide each way [53:16]; "
                 "Alan also spoke of an «18 inch» folded middle piece [14:38] — which one is open")
    return [shop.single_bottom(L, W, p["turn_down"], notes), shop.top_flashing(L, W),
            shop.piece("leg", 22, 6, 4),                                   # Alan: modern-cube legs are 22 × 6
            shop.piece("slat M", L, 5.5, 8), shop.piece("slat F", W + shop.EARS, 5.5, 8)]


ARCH_DEFAULT = 12.5


def _family(fid, title, source, rule, hours, extra_params=(), turn_down=False):
    params = shop.size_params(turn_down) + list(extra_params)

    def pieces(p):
        notes = []
        return rule(p, notes), notes

    def solid(p):
        # the model carries what was ASSUMED, as the takeoff does: a file opened alone must say it too
        cut, notes = pieces(p)
        return shop.anatomy(cut, p["t"], shop.model_label(f"{fid} {p['L']:g}x{p['W']:g} anatomy", notes))

    return types.SimpleNamespace(
        ID=fid, TITLE=title, SOURCE=source, PARAMS=params, pieces=pieces,
        consumables=lambda p: [dict(c) for c in shop.RIVETS_AND_CAULK],
        labour_hours=hours, solid=solid)


def _crownhip_hours(p):
    # Alan: 34 × 34 takes 2½–3 h, bigger ones up to 4 h, «half of the day» [44:19–44:32] (the services app's tiers)
    return 2.5 if p["L"] <= 36 else 3.0 if p["L"] <= 48 else 4.0


TTOP = _family("ttop", {"en": "Masonry T-Top", "he": "כובע T לבנייה"},
               "Alan, MEET-41: «masonry texas tops, the t-tops» [32:40]; top = cap + 5 [32:47]; masonry strips 10½″ and legs 10½ × 6",
               _ttop, lambda p: 2.0)
CROWNHIP = _family("crownhip", {"en": "Masonry Crown Hip", "he": "כובע קשת לבנייה"},
                   "Alan, MEET-41: arched top L × (W+10), W+8 past 38 [46:37], halves past 40 [47:02]; ends (W+1½) × (H+2½) [21:10]",
                   _crownhip, _crownhip_hours,
                   [{"key": "arch_h", "label": "arch height", "unit": "in", "min": 2, "max": 30, "default": ARCH_DEFAULT}])
AVANTE = _family("avante", {"en": "Avante Dome", "he": "כיפת אוונטה"},
                 "Alan, MEET-41: a dome of four 24″ pieces [24:01, 34:04]; on brick the masonry strips and legs; on a wood chase a single-flashing bottom",
                 _avante, lambda p: 3.0,
                 [{"key": "base", "label": "what it sits on", "kind": "choice", "options": ["brick", "wood"], "default": None}],
                 turn_down=True)
CUBE = _family("cube", {"en": "Modern Cube", "he": "קובייה מודרנית"},
               "Alan, MEET-41: single-flashing bottom, top flashing L+5 × W+5, legs 22 × 6, 8 slats 5½″ each way [53:16–53:40]",
               _cube, lambda p: 3.0, turn_down=True)

ALL = (TTOP, CROWNHIP, AVANTE, CUBE)
