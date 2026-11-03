"""From a cap's BOM to money: every line says what it is, how many, at what price and where that price came from.

    cost(bom, prices) -> {lines, cost_cents, price_cents, price_list}

The price list is a dated file (prices/<id>.json): a quote stores the id it was costed with, so a later price
change never re-prices an old job silently. Sheets are whole sheets (the shop buys whole sheets; the offcut is
scrap or legs for the next cap), mesh is by the square foot, labour by the hour, rivets and caulk by the unit.
"""
from __future__ import annotations

import json
import math
import os

HERE = os.path.join(os.path.dirname(__file__), "prices")
DEFAULT = "fpg-2026-11-02"


def load(pid: str = DEFAULT) -> dict:
    if not pid.replace("-", "").isalnum():
        raise ValueError(f"no price list {pid!r}")
    path = os.path.join(HERE, f"{pid}.json")
    if not os.path.exists(path):
        raise ValueError(f"no price list {pid!r}: one of {', '.join(sorted(p[:-5] for p in os.listdir(HERE)))}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sheet_for(prices: dict, metal: str) -> dict:
    s = prices["sheets"].get(metal) or prices["sheets"]["galvanized"]
    return {"metal": metal if metal in prices["sheets"] else "galvanized", **s}


def money(c: int) -> str:
    return f"${c / 100:,.2f}"


def cost(bom: dict, prices: dict) -> dict:
    """bom: {metal, sheets, mesh_in2, rivets, caulk_tubes, hours}. Returns explainable lines and the totals."""
    lines = []

    def add(item, qty, unit, each_cents, source):
        c = int(round(qty * each_cents))
        lines.append({"item": item, "qty": qty, "unit": unit, "each_cents": each_cents, "cents": c, "source": source})

    sh = sheet_for(prices, bom["metal"])
    add(f"sheet {sh['metal']} {sh['w']}×{sh['h']}", bom["sheets"], "sheet", sh["cents"], sh["source"])
    if bom.get("mesh_in2"):
        ft2 = round(bom["mesh_in2"] / 144, 3)
        add("spark-arrestor mesh", ft2, "ft²", prices["mesh"]["cents_per_ft2"], prices["mesh"]["source"])
    if bom.get("rivets") and not prices.get("spot_welder"):
        add("rivet", bom["rivets"], "each", prices["rivet"]["cents_each"], prices["rivet"]["source"])
    for key, item in (("tapcons", "Tapcon 1/4 × 1-3/4"), ("screws", "#10 hex screw")):    # a list from before has none
        if bom.get(key) and key in prices:
            add(item, bom[key], "each", prices[key]["cents_each"], prices[key]["source"])
    if bom.get("caulk_tubes"):
        add("caulk", bom["caulk_tubes"], "tube", prices["caulk"]["cents_per_tube"], prices["caulk"]["source"])
    add("labour", round(bom["hours"], 2), "hour", prices["labour"]["cents_per_hour"], prices["labour"]["source"])
    total = sum(x["cents"] for x in lines)
    factor = float(prices["markup"]["factor"])

    def priced(c):
        return max(int(math.ceil(c * factor / 100.0)) * 100, int(prices.get("floor_cents") or 0))

    # Which one is the price is Alan's own rule, metal by metal — and the services app's (Prices & setup → whole-sheet
    # metals), so the two never disagree on the same cap (DGO-1076, 2026-11-02):
    #   copper pays its whole sheets — its leftovers sit («one and a half sheets of copper sitting in there» [16:22]);
    #   any other metal pays the share it covers — its offcut becomes the next caps' legs [42:28], and his 24 × 24
    #   single flashing costs him $60–70 against a $70 sheet [41:15].
    # `sheet_charge: "by_metal"` with `whole_sheet_metals` is that rule; "whole" / "used" force one for every metal.
    used = bom.get("sheet_fill")
    share = None
    if used is not None:
        share = total - lines[0]["cents"] + int(round(used * sh["cents"]))
    mode = prices.get("sheet_charge") or "whole"
    if mode == "by_metal":
        mode = "whole" if bom["metal"] in (prices.get("whole_sheet_metals") or ["copper"]) else "used"
    by_share = mode == "used" and share is not None
    if by_share:
        # the sheet line says what is charged — the share, with the whole sheets it is cut from — so the lines add up
        lines[0] = {**lines[0], "qty": round(used, 3), "cents": int(round(used * sh["cents"])),
                    "item": f"{lines[0]['item']} (the share of {bom['sheets']} sheet(s) the cap covers)"}
    cost_c = share if by_share else total
    return {"price_list": prices["id"], "lines": lines, "cost_cents": cost_c, "markup": factor,
            "price_cents": priced(cost_c), "cost": money(cost_c), "price": money(priced(cost_c)),
            "sheet_charge": "used" if by_share else "whole",
            "cost_used_share_cents": share, "price_used_share": money(priced(share)) if share is not None else None,
            "cost_whole_sheets_cents": total, "price_whole_sheets": money(priced(total)),
            "price_source": prices["markup"]["source"]}
