"""test_reserved_paths — every route the console serves under /api is one it RESERVES (DGO-1434).

    python3 platform-base/console/test_reserved_paths.py

An app that root-mounts a passthrough (bina-ds takes /api at the console origin's root) is compiled with
the console's `reserved_paths` carved out of its rule (reconcile.py, routing.go), and NOTHING else. A
console route missing from that list is answered by the app instead, from a browser — while a check from
inside the network reaches the console and passes. Measured 2026-11-06: `/api/handoffs` (DGO-1336) and
`/api/frame-check` were not reserved, so on every office running bina-ds the shell's hand-off poll and its
frame check went to bina-ds, and «Continue with Google» could never bring the office browser to anyone.

This reads the routes from app.py's own decorators — no Flask, no import — and fails on any /api route
whose first segment no reserved path covers.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROUTE = re.compile(r'@app\.(?:route|get|post|put|delete|patch)\(\s*"(?P<path>/api/[^"]*)"')


def served() -> set[str]:
    """Each /api route of app.py, up to its first variable part."""
    out = set()
    for m in ROUTE.finditer((HERE / "app.py").read_text(encoding="utf-8")):
        out.add(m.group("path").split("<", 1)[0].rstrip("/") or "/api")
    return out


def reserved() -> list[str]:
    return json.loads((HERE / "app.json").read_text(encoding="utf-8")).get("reserved_paths") or []


def covered(path: str, prefixes: list[str]) -> bool:
    """The compiled rule excludes `^/(<reserved>)(/|$)`: a reserved path covers itself and below it."""
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)


class EveryApiRouteIsReserved(unittest.TestCase):
    def test_app_py_has_api_routes(self):
        # the scan read something: a renamed decorator must not turn this test into a silent pass
        self.assertGreaterEqual(len(served()), 8, sorted(served()))

    def test_every_api_route_is_reserved(self):
        missing = sorted(p for p in served() if not covered(p, reserved()))
        self.assertEqual(missing, [], "console routes a root-mounted app would answer instead: add them to "
                                      "platform-base/console/app.json reserved_paths")

    def test_the_two_found_missing_are_reserved(self):
        for p in ("/api/handoffs", "/api/frame-check"):
            self.assertTrue(covered(p, reserved()), p)

    def test_the_rule_matches_the_compilers(self):
        # reconcile.py: !PathRegexp(`^/(<reserved minus /a>)(/|$)`) — a prefix covers itself and below it only
        self.assertTrue(covered("/api/svc/x/manifest", ["/api/svc"]))
        self.assertFalse(covered("/api/svcx", ["/api/svc"]))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
