"""test_door_duplicates.py — the same door rule twice is one door, not a clash (DGO-653, linkproxy.build_multi).

The HP's whole delivery plan was refused as «פורט … מבוקש גם עבור X וגם עבור X — דלת אחת, אפליקציה אחת»: two
IDENTICAL rows of one office and app. Held here, with plans other offices ship (`shipped`), which join this office's
own rules and go through the same clash check:
  * the same rule from two plans → one rule, no refusal, and the drop is said with both sources;
  * the same rule twice in one plan → one rule;
  * a TRUE clash (one address and port, another app) → still refused, naming each side's plan.

    python3 apps/dgo-extend/tests/test_door_duplicates.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import linkproxy  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


class Said(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def doc(*rules):
    return {"pairs": [{"office": "examplef", "slot": 4, "side": 2, "self": "10.79.4.2", "iface": "wg0",
                       "host_doors": True}], "rules": list(rules)}


PLANE = {"office": "examplef", "app": "plane", "bind": "10.79.4.2", "port": 9005, "kind": "door"}
DRIVE = {**PLANE, "app": "drive"}
HOME = {"id": "hp-laptop"}


def main() -> int:
    said = Said()
    logging.getLogger("dgo-extend.linkproxy").addHandler(said)

    try:
        plan = linkproxy.build_multi(HOME, [], shipped={"vps1": doc(PLANE), "macbook": doc(dict(PLANE))})
        doors = [r for r in plan["rules"] if r.get("app") == "plane"]
        check(len(doors) == 1, f"the same rule from two shipped plans is ONE door: {len(doors)} rule(s)")
        check(any("twice" in s and "macbook" in s and "vps1" in s for s in said.lines),
              f"…and the dropped copy is said with both sources: {said.lines}")
    except linkproxy.LinkProxyError as e:
        check(False, f"the same rule from two shipped plans was refused as a clash: {e}")

    try:
        plan = linkproxy.build_multi(HOME, [], shipped={"vps1": doc(PLANE, dict(PLANE))})
        check(len([r for r in plan["rules"] if r.get("app") == "plane"]) == 1,
              "the same rule twice in ONE shipped plan is one door")
    except linkproxy.LinkProxyError as e:
        check(False, f"the same rule twice in one plan was refused as a clash: {e}")

    try:
        linkproxy.build_multi(HOME, [], shipped={"vps1": doc(PLANE), "macbook": doc(DRIVE)})
        check(False, "a TRUE clash (one address and port, two apps) went through")
    except linkproxy.LinkProxyError as e:
        msg = str(e)
        check("examplef/plane" in msg and "examplef/drive" in msg and "vps1" in msg and "macbook" in msg,
              f"a true clash is still refused, naming both apps and each one's plan: {msg}")

    # ...and only an IDENTICAL rule is one door: a rule that differs in any field that matters is still a clash
    for field, other in (("target", "10.79.4.1:9006"), ("kind", "agent-x"), ("slot", 5), ("side", 1),
                         ("port", "9005")):
        try:
            linkproxy.build_multi(HOME, [], shipped={"vps1": doc(PLANE), "macbook": doc({**PLANE, field: other})})
            check(False, f"two rules that differ in `{field}` were merged into one door")
        except linkproxy.LinkProxyError:
            check(True, f"two rules that differ only in `{field}` are not one door: still refused")

    print("test_door_duplicates:", "all passed" if not FAIL else f"{len(FAIL)} FAILED")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
