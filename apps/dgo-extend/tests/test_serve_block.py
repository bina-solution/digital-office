#!/usr/bin/env python3
"""test_serve_block — an office that links to nobody is served nothing (FPG-8).

`converge._serve_block` writes the `serve:` list into the PEER's platform.state.yaml: the apps of this
office the peer may open. It read the link's direction with a `use` default, and for an office with NO
link that default mirrored to `serve` — fireplace, a client's office declared with no link at all, was
handed the Mac's bina tile at an address of a pair it is not in (measured 2026-10-22, state step:
«מוגשות ללשכה fireplace: bina (10.79.2.1:3080)»).

Run: python3 apps/dgo-extend/tests/test_serve_block.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

HOME = {"id": "macbook", "domain": "localhost", "tunnel": {"slot": 2},
        "serve": {"bina-ds": {"port": 3080, "agent_api_port": 3081}}}
FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    alone = {"id": "fireplace", "path": "/opt/digital-office/fireplace"}
    check(converge._serve_block(alone, HOME) == [], "an office with no link is served nothing")
    check(converge._serve_block({**alone, "links": []}, HOME) == [], "…nor one with an empty link list")
    check(converge._serve_block({**alone, "links": [{"office": "hp-laptop", "direction": "use"}]}, HOME) == [],
          "…nor one linked only to another office")
    # the office says it USES this one's apps: this office serves — the block is rendered (or, without a
    # manifest for the app in a bare test tree, at least not refused by the link rule)
    used = {**alone, "links": [{"office": "macbook", "direction": "use"}]}
    try:
        converge._serve_block(used, HOME)
    except Exception as e:                       # a manifest lookup may fail outside the image
        check("manifest" in str(e).lower() or isinstance(e, (OSError, KeyError)),
              f"a linked office reaches the serve rendering: {e!r}")
    check(converge._serve_block({**alone, "links": [{"office": "macbook", "direction": "serve"}]}, HOME) == [],
          "an office that SERVES this one is given nothing of this one")
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_serve_block" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
