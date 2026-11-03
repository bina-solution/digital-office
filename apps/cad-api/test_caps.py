"""The gallery's dynamic caps: every style quotes from a job, Alan's rules hold, a real job record prices, and every
style folds into a model (where the CAD kernel is installed)."""
from __future__ import annotations

import pytest

pytest.importorskip("rectpack")
import caps  # noqa: E402

GALLERY = ["pan", "standard", "pitched", "bell", "cube", "chase", "tee", "turtle", "bishop"]


def blanks(q):
    return {(p["name"], p["blank"][0], p["blank"][1]): p["qty"] for p in q["parts"]}


@pytest.mark.parametrize("sid", GALLERY)
@pytest.mark.parametrize("metal", ["galvanized", "prepainted", "stainless", "copper"])
def test_every_gallery_cap_quotes_with_explained_money(sid, metal):
    q = caps.quote(sid, {"params": {"L": 30, "W": 24}, "material": metal})
    assert q["bom"]["sheets"] >= 1 and not q["errors"]
    c = q["cost"]
    assert c["cost_cents"] == sum(x["cents"] for x in c["lines"]) > 0
    assert c["price_cents"] >= c["cost_cents"] * 2 - 100              # Alan: «I charge around double» [43:58]
    assert all(x["source"] for x in c["lines"])


def test_sheets_charged_by_metal_as_the_services_app_does():
    # DGO-1076, 2026-11-02: copper pays whole sheets (its leftovers sit), any other metal the share it covers —
    # and the lines still add up to the cost
    import caps.cost as costing
    g = caps.quote("pan", {"params": {"L": 30, "W": 24}, "material": "galvanized"})["cost"]
    assert g["sheet_charge"] == "used" and g["cost_cents"] == g["cost_used_share_cents"] < g["cost_whole_sheets_cents"]
    assert g["cost_cents"] == sum(x["cents"] for x in g["lines"])
    cu = caps.quote("pan", {"params": {"L": 30, "W": 24}, "material": "copper"})["cost"]
    assert cu["sheet_charge"] == "whole" and cu["cost_cents"] == cu["cost_whole_sheets_cents"]
    old = caps.quote("pan", {"params": {"L": 30, "W": 24}}, costing.load("fpg-2026-11-01"))["cost"]
    assert old["sheet_charge"] == "whole"                                         # a dated list never changes
    forced = caps.quote("pan", {"params": {"L": 30, "W": 24}}, {**costing.load(), "sheet_charge": "whole"})["cost"]
    assert forced["sheet_charge"] == "whole"


def test_turtle_is_alans_cut_list():
    q = caps.quote("turtle", {"params": {"L": 35, "W": 32, "legs": 18}})
    b = blanks(q)
    assert b[("bottom flashing", 42, 39)] == 1 and b[("side M", 35, 12)] == 2 and b[("side F", 33.5, 12)] == 2
    assert b[("top", 31, 28)] == 1 and b[("leg", 18, 6)] == 4
    assert q["bom"]["sheets"] == 1 and q["bom"]["hours"] == 1.5      # one sheet [31:03], 1.5 h [41:33]


def test_masonry_base_follows_the_chimney_and_alans_strips():
    q = caps.quote("standard", {"params": {"L": 30, "W": 24, "base": "masonry"}})
    b = blanks(q)
    assert b[("bottom strip M", 30, 10.5)] == 2 and b[("bottom strip F", 25.5, 10.5)] == 2
    assert ("leg", 10.5, 6) in b                                      # 10 in legs cut 10.5 [1:07:01]
    f = caps.quote("standard", {"params": {"L": 30, "W": 24, "base": "flashing"}})
    assert ("bottom flashing", 37, 31) in blanks(f)                   # L + 7 [MEET-41]


def test_a_real_job_record_prices_end_to_end():
    spec = {"chimney": "flue", "style": "tee", "material": "copper",
            "outside": {"length": 30, "width": 18, "quoted": {"A": 30.5, "B": 18.5}},
            "holes": [{"index": 1, "diameter": 8, "fromTop": 5, "fromLeft": 4.5},
                      {"index": 2, "diameter": 10, "fromTop": 4, "fromLeft": 17.25}],
            "skirt": 4, "legs": "std", "legsInches": 10, "meshScreen": False}
    q = caps.quote("tee", {"cap_spec": spec})
    assert q["params"]["L"] == 30.5 and q["params"]["base"] == "flashing" and len(q["params"]["flues"]) == 2
    assert q["metal"]["key"] == "copper" and q["cost"]["lines"][0]["item"].startswith("sheet copper 36")
    assert ("top flashing", 35.5, 23.5) in blanks(q)                  # Alan's T-top L + 5


def test_the_fpg_turtle_job_fg_1007():
    # FG-1007 (the owners' Telegram, 2026-11-01): Turtle Top 30 × 20, 3 in skirt, standard 18 in legs
    q = caps.quote("turtle", {"params": {"L": 30, "W": 20, "skirt": 3, "legs": 18}, "material": "prepainted"})
    assert q["bom"]["sheets"] == 1 and ("bottom flashing", 37, 27) in blanks(q)


def test_the_cap_is_held_down_and_its_anchors_are_priced():
    # FPG-604: the FreeCAD library's rule — ≤ 12 in apart, two a side at least: 14 at 30 × 24
    q = caps.quote("standard", {"params": {"L": 30, "W": 24, "base": "masonry"}})
    assert (q["bom"]["tapcons"], q["bom"]["screws"]) == (14, 0) and "Tapcons" in q["bom"]["anchors_why"]
    line = next(x for x in q["cost"]["lines"] if x["item"].startswith("Tapcon"))
    assert line["qty"] == 14 and line["cents"] == 14 * 35 and line["source"]
    f = caps.quote("chase", {"params": {"L": 48, "W": 36}})               # a chase: screws into the wood, not Tapcons
    assert (f["bom"]["tapcons"], f["bom"]["screws"]) == (0, 2 * 5 + 2 * 4)
    assert any(x["item"].startswith("#10") for x in f["cost"]["lines"])
    assert q["cost"]["price_list"] == "fpg-2026-11-02"          # the anchors stay priced in the list after it


def test_a_price_list_from_before_the_anchors_prices_as_it_did():
    import caps.cost as costing
    old = caps.quote("standard", {"params": {"L": 30, "W": 24}}, costing.load("fpg-2026-10-30"))["cost"]
    assert old["price_list"] == "fpg-2026-10-30" and not any(x["item"].startswith(("Tapcon", "#10")) for x in old["lines"])


def test_copper_that_does_not_fit_its_sheet_is_an_error():
    q = caps.quote("cube", {"params": {"L": 40, "W": 38}, "material": "copper"})
    assert any("larger than a 36" in e for e in q["errors"])


@pytest.mark.parametrize("sid", GALLERY)
def test_every_style_folds_into_a_model(sid):
    pytest.importorskip("build123d")
    job = {"params": {"L": 30, "W": 24}}
    m = caps.model(sid, job)
    valid = [c.is_valid() if callable(c.is_valid) else c.is_valid for c in m.children]   # a property in 0.13
    assert m.children and m.label.isascii() and all(valid)
