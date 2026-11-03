#!/usr/bin/env python3
"""test_home_delivery — a far office that only SERVES is not measured on the home's ports.

step_link probed, from the far machine, every port the home serves, whatever the link's direction. On
fireplace's link (direction `serve`: fireplace serves, the Mac uses) nothing of the Mac's is opened to
fireplace by design, so the log always read «0/3 open», beside DGO-1018's 502 and after it was fixed
(issues/a-one-way-link-reports-the-home-ports-the-far-office-never-uses-as-0-open.yaml).

Run: python3 apps/dgo-extend/tests/test_home_delivery.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    office, home = {"id": "fireplace", "machine": "m"}, {"id": "macbook", "serve": {"*": {}}}
    probed, said = [], []
    real_ports, real_must = converge._served_ports_local, converge.must
    try:
        converge._served_ports_local = lambda *a, **k: {"console": 9006, "bina-ds": 3081}
        converge.must = lambda m, cmd, t=0, why="": probed.append(cmd) or "OPEN\nEND\n"
        got = converge._home_delivery(office, home, "serve", 6, "10.79.6.1", said.append)
        check(got == {} and not probed and not said, f"a `serve` link measures nothing of the home's: {got} {said}")
        for direction in ("use", "both"):
            probed.clear()
            said.clear()
            got = converge._home_delivery(office, home, direction, 6, "10.79.6.1", said.append)
            check(set(got) == {"console", "bina-ds"} and len(probed) == 2 and all(d["open"] for d in got.values())
                  and said and "2/2" in said[-1], f"a `{direction}` link measures every served port: {got} {said}")
    finally:
        converge._served_ports_local, converge.must = real_ports, real_must
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_home_delivery" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
