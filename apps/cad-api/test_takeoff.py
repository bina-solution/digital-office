"""cad-api's families and takeoff, checked against Alan's own numbers (MEET-41). `python -m pytest` in the
image; the packing tests skip where rectpack is not installed (the families alone need nothing)."""
from __future__ import annotations

import math

import pytest

import families
from families import chase, turtle


def test_turtle_pieces_are_alans_rules():
    p = families.check(turtle, {"L": 35, "W": 32})
    got = {(x["name"], x["w"], x["h"]): x["qty"] for x in turtle.pieces(p)[0]}
    assert got == {("bottom", 42, 39): 1, ("side M", 35, 12): 2, ("side F", 33.5, 12): 2,
                   ("top", 31, 28): 1, ("leg", 18, 6): 4}


def test_turtle_past_48_gets_two_short_legs_and_a_deeper_turn_down_a_bigger_bottom():
    p = families.check(turtle, {"L": 50, "W": 30, "turn_down": 4})
    ps = turtle.pieces(p)[0]
    assert {"name": "leg", "w": 18, "h": 5, "qty": 2} in ps
    assert ps[0]["w"] == 50 + 9 and ps[0]["h"] == 30 + 9


def test_width_larger_than_length_is_turned_round():
    assert families.check(turtle, {"L": 20, "W": 30}) == {"L": 30, "W": 20, "turn_down": 3, "t": 0.024}


@pytest.mark.parametrize("raw, words", [({"W": 20}, "missing L"), ({"L": 500, "W": 20}, "outside"),
                                        ({"L": "x", "W": 20}, "must be a number"), ({"L": 30, "W": 20, "z": 1}, "no parameter z")])
def test_bad_parameters_say_which(raw, words):
    with pytest.raises(ValueError, match=words):
        families.check(turtle, raw)


def test_chase_flat_pattern_is_the_bend_allowance_rule():
    p = families.check(chase, {"L": 40, "W": 30})
    ba = math.pi / 2 * (0.03 + 0.44 * 0.024)
    fl, fw = chase.flat(p)
    leg = 3 - (0.03 + 0.024)
    assert fl == pytest.approx(40 - 2 * 0.054 + 2 * ba + 2 * leg)
    assert fw == pytest.approx(30 - 2 * 0.054 + 2 * ba + 2 * leg)


def test_chase_flue_that_runs_off_the_lid_is_refused():
    p = families.check(chase, {"L": 30, "W": 20, "flues": [{"d": 10, "x": 12, "y": 0}]})
    with pytest.raises(ValueError, match="runs off"):
        chase.pieces(p)


def test_turtle_35x32_is_one_sheet_as_alan_said():
    pytest.importorskip("rectpack")
    import takeoff as tk
    p = families.check(turtle, {"L": 35, "W": 32})
    out = tk.takeoff(turtle, p, 48, 120, "galvanized")
    assert len(out["sheets"]) == 1, out["sheets"]          # «will definitely come out of one sheet» [31:03]
    assert not out["errors"]
    placed = out["sheets"][0]["placed"]
    assert len(placed) == 10
    for a in placed:                                        # nothing off the sheet, nothing on top of another
        assert a["x"] >= 0 and a["y"] >= 0 and a["x"] + a["w"] <= 48 + 1e-6 and a["y"] + a["h"] <= 120 + 1e-6
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            assert (a["x"] + a["w"] <= b["x"] + 1e-6 or b["x"] + b["w"] <= a["x"] + 1e-6 or
                    a["y"] + a["h"] <= b["y"] + 1e-6 or b["y"] + b["h"] <= a["y"] + 1e-6)


@pytest.mark.parametrize("L, W", [(50, 25), (38, 38)])
def test_strip_heavy_turtles_need_the_second_stage_to_fit_one_sheet(L, W):
    # the services app's calculator gets these onto one sheet only by laying the kinds in every order
    pytest.importorskip("rectpack")
    import takeoff as tk
    out = tk.takeoff(turtle, families.check(turtle, {"L": L, "W": W}), 48, 120, "galvanized")
    assert len(out["sheets"]) == 1 == out["area_bound"]


def test_a_kerf_never_reads_as_a_turn_and_sizes_stay_exact():
    pytest.importorskip("rectpack")
    import takeoff as tk
    out = tk.takeoff(turtle, families.check(turtle, {"L": 35, "W": 32}), 48, 120, "galvanized", kerf=0.0625)
    cut = {(p["w"], p["h"]) for p in out["pieces"]}
    for a in out["sheets"][0]["placed"] if len(out["sheets"]) == 1 else [x for s in out["sheets"] for x in s["placed"]]:
        assert ((a["h"], a["w"]) if a["rotated"] else (a["w"], a["h"])) in cut


def test_qty_is_capped_per_takeoff():
    import takeoff as tk
    with pytest.raises(ValueError, match="qty"):
        tk.takeoff(turtle, families.check(turtle, {"L": 35, "W": 32}), 48, 120, "galvanized", qty=5000)


def test_sizes_carry_no_float_noise():
    tops = [p for p in turtle.pieces(families.check(turtle, {"L": 35.3, "W": 30}))[0] if p["name"] == "top"]
    assert tops[0]["w"] == 31.3


def test_flues_turn_with_the_lid_and_a_malformed_list_is_refused():
    p = families.check(chase, {"L": 20, "W": 30, "flues": [{"d": 6, "x": 0, "y": 10}]})
    assert (p["L"], p["W"]) == (30, 20) and p["flues"][0] == {"d": 6, "x": 10, "y": 0}
    assert len(chase.pieces(p)[0]) == 2
    for bad in ({"d": 8}, "[]", [1, 2]):
        with pytest.raises(ValueError, match="list of objects"):
            families.check(chase, {"L": 30, "W": 20, "flues": bad})


@pytest.mark.parametrize("raw", [5, "abc", [1]])
def test_params_that_are_not_an_object_are_a_sentence_not_a_crash(raw):
    with pytest.raises(ValueError, match="params must be an object"):
        families.check(turtle, raw)


def test_the_masonry_caps_are_alans_rules():
    def cut(fid, **raw):
        fam = families.get(fid)
        return {(x["name"], x["w"], x["h"]): x["qty"] for x in fam.pieces(families.check(fam, raw))[0]}
    assert cut("ttop", L=70, W=22) == {("top flashing", 75, 27): 1, ("bottom strip M", 70, 10.5): 2,
                                       ("bottom strip F", 23.5, 10.5): 2, ("leg", 10.5, 6): 4, ("leg", 10.5, 5): 2}
    assert cut("crownhip", L=34, W=34)[("arch top", 34, 44)] == 1
    assert cut("crownhip", L=40, W=39)[("arch top", 40, 47)] == 1                  # W + 8 past 38 [46:37]
    assert cut("crownhip", L=57, W=50)[("arch top half", 57, 31)] == 2             # halves past 40 [47:02]
    assert cut("crownhip", L=34, W=34)[("arch end", 35.5, 15)] == 2                # (W + 1½) × (H + 2½) [21:10]
    assert ("dome M", 36, 24) in cut("avante", L=36, W=33, base="brick")
    assert ("bottom", 43, 40) in cut("avante", L=36, W=33, base="wood")
    assert cut("cube", L=34, W=34)[("slat M", 34, 5.5)] == 8


def test_a_choice_is_one_of_its_options():
    fam = families.get("avante")
    with pytest.raises(ValueError, match="base is one of brick, wood"):
        families.check(fam, {"L": 36, "W": 33, "base": "stone"})
    with pytest.raises(ValueError, match="missing base"):
        families.check(fam, {"L": 36, "W": 33})


def test_every_family_describes_itself_and_says_who_gave_its_rules():
    for fam in families.FAMILIES.values():
        d = families.describe(fam)
        assert d["id"] and d["title"]["en"] and d["source"] and d["params"][0]["key"] == "L"


def test_a_model_label_is_ascii_so_step_keeps_the_whole_note():
    from families import shop
    fam = families.get("crownhip")
    p = families.check(fam, {"L": 34, "W": 34})
    label = shop.model_label("crownhip 34x34", fam.pieces(p)[1])
    assert label.isascii() and "'" not in label
    assert "arch height H = 12 1/2 in (the default), so each end is (W + 1 1/2) x 15" in label


@pytest.mark.parametrize("fid, raw", [("turtle", {"L": 30, "W": 24, "turn_down": 2}), ("crownhip", {"L": 34, "W": 34}),
                                      ("avante", {"L": 36, "W": 33, "base": "brick"}),
                                      ("chase", {"L": 40, "W": 30, "flues": [{"d": 8, "x": 0, "y": 0}]})])
def test_every_label_that_enters_a_model_is_ascii(fid, raw):
    # the glb writer double-encodes UTF-8 (DGO-1077): no glyph may reach a model label
    pytest.importorskip("build123d")
    fam = families.get(fid)
    shape = fam.solid(families.check(fam, raw))
    labels = [shape.label] + [c.label for c in shape.children]
    assert all(lb.isascii() for lb in labels), labels
    assert "ASSUMED" in shape.label


def test_a_piece_bigger_than_the_sheet_is_an_error_not_a_sheet():
    pytest.importorskip("rectpack")
    import takeoff as tk
    p = families.check(turtle, {"L": 60, "W": 50})
    out = tk.takeoff(turtle, p, 36, 120, "copper")         # copper comes 36 wide [16:13]: a 67 × 57 bottom cannot
    assert any("bottom" in e for e in out["errors"])
