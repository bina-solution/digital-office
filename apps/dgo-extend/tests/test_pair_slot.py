#!/usr/bin/env python3
"""test_pair_slot — every converged link uses its OWN /24 (FPG-8).

step_link took the home office's single `tunnel.slot` for every converged office and saved it over the
pair's declared one. vps1 (the first converged link) shares the home's slot, so the second converged
office got vps1's: fireplace was declared with slot 6, saved as 2, and the renderer refused "two pairs on
the same slot (2)". The serve block and the agent hand-off computed this office's address (`.1`) from the
same field. And the renderer's refusal, an HTTP response, crashed `_render_local_tunnel` on `.get`.

Run: python3 apps/dgo-extend/tests/test_pair_slot.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

HOME = {"id": "macbook", "tunnel": {"slot": 2}}
FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    check(converge._pair_slot({"tunnel": {"slot": 6}}, HOME) == 6, "a pair's declared slot is its own")
    check(converge._pair_slot({"tunnel": {}}, HOME) == 2, "a record that declares none shares the home's (vps1)")
    check(converge._pair_slot({}, HOME) == 2, "…as does a record with no tunnel block")
    # a slot another record holds is refused before the step writes anything
    import app as _app
    real_decl, real_home, real_save = _app.all_declarations, converge.home_office, converge.save_declaration
    saved = []
    try:
        _app.all_declarations = lambda: [{"id": "vps1", "tunnel": {"slot": 2}}, {"id": "new", "tunnel": {}}]
        converge.home_office = lambda: {**HOME, "identity": {}}
        converge.save_declaration = lambda o: saved.append(o)
        try:
            converge.step_link({"id": "new", "machine": "m", "links": [{"office": "macbook", "direction": "serve"}]},
                               {}, lambda *_: None)
            check(False, "a slot another pair holds must be refused")
        except converge.StepFailed as e:
            check("vps1" in str(e) and not saved, f"…naming its holder, and nothing saved: {e}")
    finally:
        _app.all_declarations, converge.home_office, converge.save_declaration = real_decl, real_home, real_save
    # the renderer's refusal comes back as an HTTP response: its sentence is the step's failure
    from fastapi.responses import JSONResponse
    real = _app.render_tunnel
    try:
        _app.render_tunnel = lambda: JSONResponse({"error": "שני זוגות על אותו slot (2)"}, status_code=400)
        try:
            converge._render_local_tunnel(lambda *_: None)
            check(False, "a refused render must fail the step")
        except converge.StepFailed as e:
            check("אותו slot" in str(e), f"…with the renderer's own sentence, not a crash: {e}")
    finally:
        _app.render_tunnel = real
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_pair_slot" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
