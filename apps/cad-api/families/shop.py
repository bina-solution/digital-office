"""The parts several of Alan's caps share (MEET-41, 2026-10-30), and the anatomy view every cut-list family draws.

"M" pieces run along L with no ears; "F" pieces run along W and are 1½″ longer for a ¾″ ear each side.
"""
from __future__ import annotations

from .units import inches

EARS = 1.5


def piece(name: str, w, h, qty: int = 1) -> dict:
    w, h = inches(w), inches(h)
    if w <= 0 or h <= 0:
        raise ValueError(f"{name} comes out {w:g} × {h:g}: the cap is too small for this style")
    return {"name": name, "w": w, "h": h, "qty": qty}


def single_bottom(L, W, turn_down, notes: list) -> dict:
    # Alan: (L + 7) × (W + 7) for a 3″ turn-down; the 7 grows by 2 for every inch deeper.
    extra = 7 + 2 * (turn_down - 3)
    if turn_down < 3:
        notes.append(f"ASSUMED: a {inches(turn_down):g}″ turn-down shrinks the bottom by the same rule "
                     f"(+{inches(extra):g}); Alan described deeper ones only")
    return piece("bottom", L + extra, W + extra)


def top_flashing(L, W) -> dict:
    # Alan: the flat top with its turn-down and fold is (L + 5) × (W + 5) [32:47].
    return piece("top flashing", L + 5, W + 5)


def masonry_bottom(L, W) -> list[dict]:
    # Alan: four strips 10½″ wide, two M and two F.
    return [piece("bottom strip M", L, 10.5, 2), piece("bottom strip F", W + EARS, 10.5, 2)]


def masonry_legs(L) -> list[dict]:
    # Alan: four 10½ × 6 legs, plus 10½ × 5 ones on a long cap: two past 48″, four past 70″.
    extra = 4 if L > 70 else 2 if L > 48 else 0
    return [piece("leg", 10.5, 6, 4)] + ([piece("leg", 10.5, 5, extra)] if extra else [])


def anatomy(pieces: list[dict], t: float, label: str):
    """Every piece as a plate of the sheet's thickness, in rows — the cap taken apart («Anatomy»). Used where
    the folds were never described: a drawn guess of the folded cap would be a picture nobody can build from."""
    from build123d import Align, Box, Compound, Pos

    parts, y, gap = [], 0.0, 2.0
    for p in pieces:
        x = 0.0
        for _ in range(int(p["qty"])):
            plate = Pos(x, y, 0) * Box(p["w"], p["h"], t, align=(Align.MIN, Align.MIN, Align.MIN))
            plate.label = ascii_label(p["name"])
            parts.append(plate)
            x += p["w"] + gap
        y += p["h"] + gap
    return Compound(children=parts, label=ascii_label(label))


#: A model's labels are ASCII: in STEP a ″ cut the note there («arch height H = », FreeCAD on the Dell,
#: 2026-11-01), and the glb writer double-encodes UTF-8 («2â€³», measured by DGO-1077). So every label that
#: enters a model spells the shop's glyphs out; the true text stays in the takeoff's `notes`.
ASCII = {"″": " in", "′": " ft", "½": " 1/2", "¼": " 1/4", "¾": " 3/4", "×": "x", "−": "-", "–": "-", "—": "-",
         "«": '"', "»": '"', "⌀": "dia ", "·": "*", "π": "pi", "°": " deg"}


def ascii_label(text: str) -> str:
    for glyph, plain in ASCII.items():
        text = text.replace(glyph, plain)
    return text.encode("ascii", "replace").decode().replace("'", "")


def model_label(name: str, notes: list[str]) -> str:
    """The model's own name, with every ASSUMED / NOT CUT note: STEP and glTF keep it, so FreeCAD shows it."""
    return ascii_label(name + "".join(f"; {n}" for n in notes))


def size_params(turn_down: bool = False) -> list[dict]:
    out = [
        # the ranges only keep out the absurd: a cap too small for its rules is refused by pieces(), in words
        {"key": "L", "label": "chimney top, long side", "unit": "in", "min": 0.5, "max": 240, "default": None},
        {"key": "W", "label": "chimney top, short side", "unit": "in", "min": 0.5, "max": 240, "default": None},
    ]
    if turn_down:
        out.append({"key": "turn_down", "label": "bottom turn-down", "unit": "in", "min": 0.25, "max": 12, "default": 3})
    out.append({"key": "t", "label": "sheet thickness (drawn)", "unit": "in", "min": 0.01, "max": 0.1, "default": 0.024})
    return out


RIVETS_AND_CAULK = [{"item": "rivet", "qty": 9, "unit": "each"},      # Alan: 8–9 a cap [43:05–43:25]
                    {"item": "caulk", "qty": 0.5, "unit": "tube"}]    # half a tube [42:50]
