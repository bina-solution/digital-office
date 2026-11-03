#!/usr/bin/env python3
"""test_link_repair — a converged office whose tunnel is up while the office does not answer is given
this office's link step again, by itself (DGO-1037: fireplace served nothing for 13 hours behind a
live tunnel, and only a person running the link step brought it back).

The converge and the clock are stood in for; the items have the shape `api_link()` gives them.

Run: python3 apps/dgo-extend/tests/test_link_repair.py   (app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def item(oid, ok, hop):
    return {"office": oid, "verdict": {"ok": ok, "hop": hop}}


def main() -> int:
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    (app.DECL_DIR / "fireplace.yaml").write_text("id: fireplace\nmachine: computer_ssh-x\n")
    (app.DECL_DIR / "hp.yaml").write_text("id: hp\nkind: paired\n")
    (app.DECL_DIR / "nomachine.yaml").write_text("id: nomachine\n")
    started, answer = [], {"busy": False}

    def start(office, only, by=""):
        if answer["busy"]:
            return {"error": "הלשכה כבר בתהליך"}
        started.append((office["id"], only, by))
        return {"run": {"started": 1}}

    t0 = 1_800_000_000
    down = [item("fireplace", False, "office"), item("hp", False, "office"), item("nomachine", False, "office")]
    check(app._repair_far_delivery(down, now=t0, start=start) == [], "the first pass only starts the clock")
    check(app._repair_far_delivery(down, now=t0 + 300, start=start) == [], "five minutes is not yet an outage")
    got = app._repair_far_delivery(down, now=t0 + 601, start=start)
    check(got == ["repair:fireplace"], f"ten minutes down → its link step, got {got}")
    check(started == [("fireplace", ["machine", "link"], "repair")], f"the steps and the caller, got {started}")
    check(app._repair_far_delivery(down, now=t0 + 1200, start=start) == [], "never twice within the hour")
    got = app._repair_far_delivery(down, now=t0 + 601 + 3600, start=start)
    check(got == ["repair:fireplace"], f"an hour later it is asked again, got {got}")
    # a tunnel that is down is the heal's work, not this repair's; an office that answers resets the clock
    check(app._repair_far_delivery([item("fireplace", False, "tunnel")], now=t0 + 9000, start=start) == [],
          "a dead tunnel is not repaired by a link step")
    app._repair_far_delivery([item("fireplace", True, "")], now=t0 + 9100, start=start)
    state = json.loads((Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).read_text())
    check("since" not in state.get("fireplace", {}), f"an answer clears the outage, got {state}")
    # mid-converge: refused now, asked again on the next pass
    answer["busy"] = True
    app._repair_far_delivery(down, now=t0 + 20000, start=start)
    check(app._repair_far_delivery(down, now=t0 + 20000 + 601, start=start) == [], "a busy office is not marked repaired")
    answer["busy"] = False
    got = app._repair_far_delivery(down, now=t0 + 20000 + 700, start=start)
    check(got == ["repair:fireplace"], f"the next pass after a busy one repairs, got {got}")
    check(all(s[0] == "fireplace" for s in started), f"a paired office or one with no machine is never repaired: {started}")
    # the second reader's rules (DGO-1037/1040): at most LINK_REPAIR_MAX tries in one outage …
    app._repair_mem.clear()
    (Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).unlink(missing_ok=True)
    t1, tries = t0 + 100_000, []
    app._repair_far_delivery(down, now=t1, start=start)
    for k in range(app.LINK_REPAIR_MAX + 2):
        tries += app._repair_far_delivery(down, now=t1 + 601 + k * 3601, start=start)
    check(tries.count("repair:fireplace") == app.LINK_REPAIR_MAX, f"no more than {app.LINK_REPAIR_MAX} tries, got {tries}")
    # … a pass that measured nothing neither starts nor ends the outage …
    app._repair_far_delivery([item("fireplace", None, "")], now=t1 + 900_000, start=start)
    state = json.loads((Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).read_text())
    check(state.get("fireplace", {}).get("tries") == app.LINK_REPAIR_MAX, f"ok: None keeps the outage, got {state}")
    # … an office no longer measured is dropped …
    app._repair_far_delivery([item("hp", True, "")], now=t1 + 900_100, start=start)
    state = json.loads((Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).read_text())
    check("fireplace" not in state, f"a vanished office leaves the file, got {state}")
    # … a run of that office in flight, or ended within LINK_REPAIR_AFTER, or a move, holds the repair …
    app._repair_mem.clear()
    (Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).unlink(missing_ok=True)
    t2, real_last, real_move = t1 + 2_000_000, app.last_run, app.mv.running
    app._repair_far_delivery(down, now=t2, start=start)
    app.last_run = lambda oid: {"status": "running"}
    check(app._repair_far_delivery(down, now=t2 + 700, start=start) == [], "never beside a running converge")
    app.last_run = lambda oid: {"status": "failed", "ended": t2 + 650}
    check(app._repair_far_delivery(down, now=t2 + 700, start=start) == [], "never minutes after a run ended")
    app.last_run = lambda oid: None
    app.mv.running = lambda oid: {"app": "drive"}
    check(app._repair_far_delivery(down, now=t2 + 700, start=start) == [], "never during a move")
    app.mv.running = real_move
    check(app._repair_far_delivery(down, now=t2 + 700, start=start) == ["repair:fireplace"], "then it repairs")
    # … a clock that went back is saved as now, so it does not come back from the file …
    app._repair_mem.clear()
    app._repair_far_delivery(down, now=t2 - 500_000, start=start)
    state = json.loads((Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).read_text())
    check(state.get("fireplace", {}).get("since") == t2 - 500_000 and not state["fireplace"].get("ran"),
          f"the clock that went back is written as now, got {state}")
    # … a `door` verdict means the catalog arrived: the outage and its tries end …
    app._repair_far_delivery([item("fireplace", False, "door")], now=t2 - 400_000, start=start)
    state = json.loads((Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).read_text())
    check("fireplace" not in state, f"a door verdict ends the outage, got {state}")
    # … and a torn state file stops nothing
    app._repair_mem.clear()
    (Path(app.STATE_DIR) / app.LINK_REPAIR_FILE).write_text(json.dumps({"fireplace": "x", "hp": {"since": "abc"}}))
    app._repair_far_delivery(down, now=t2 - 300_000, start=start)
    got = app._repair_far_delivery(down, now=t2 - 300_000 + 700, start=start)
    check(got == ["repair:fireplace"], f"a torn file is read as no clock, got {got}")
    app.last_run = real_last
    # … and a repair run is written beside the converge's record, never over it
    check(app._run_kind({"by": "repair", "only": ["machine", "link"]}) == "repair", "a repair run is its own kind")
    check(app._run_file("fireplace", "repair").name == "fireplace.repair.json", "and its own file")
    check(app._run_file("fireplace").name == "fireplace.json", "the converge keeps its file")
    if FAIL:
        print("FAIL\n  " + "\n  ".join(FAIL))
        return 1
    print("test_link_repair: all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
