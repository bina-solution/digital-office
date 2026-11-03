"""The pair slots a new pairing (or join) may take — what THIS office's pairing port reports as held.

2026-10-19: vps1's first JOIN (a Claude cloud office) was given slot 2, which vps1 already used for its
link with the MacBook — a link the MacBook converged onto vps1, whose tunnel is vps1's HOST wg0 and
whose only trace in vps1's dgo-extend is the plan the MacBook shipped (`link-proxy.d/macbook.json`).
The door ports collided (9002), vps1 refused the MacBook's plan, and the MacBook's link answered
nothing until the join was undone. The port now reads every address the shipped plans name.

    python3 apps/dgo-extend/tests/pair_slots_selftest.py   (in the app's image: it imports app.py)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    tunnel = Path(tempfile.mkdtemp(prefix="pair-slots-"))
    (tunnel / "link-proxy.d").mkdir()
    (tunnel / "link-proxy.d" / "macbook.json").write_text(json.dumps({
        "office": "vps1", "rendered_by": "macbook", "slot": 2, "self": "10.79.2.2",
        "pairs": [{"office": "macbook", "slot": 2, "side": 2, "self": "10.79.2.2", "iface": "wg0"}],
        "rules": []}), encoding="utf-8")
    (tunnel / "link-proxy.d" / "broken.json").write_text("{not json", encoding="utf-8")
    (tunnel / "addressing.json").write_text(json.dumps({"self": "10.79.3.2"}), encoding="utf-8")
    os.environ["DGO_TUNNEL_DIR"] = str(tunnel)
    import app
    import pair_api

    problems = []
    held = app._PairPorts().addresses()
    if "10.79.2.2" not in held:
        problems.append(f"the address of a link another office shipped is held: {held}")
    if "10.79.3.2" not in held:
        problems.append(f"this office's own tunnel address is held: {held}")
    if len(held) != len(set(held)):
        problems.append(f"each address once: {held}")

    # …and the engine turns them into slots it will not give away
    class Ports(pair_api._MemoryPorts):
        def addresses(self):
            return held
    engine = pair_api.Pairing(Ports("vps1", "vps1", slot=1))
    if not {2, 3} <= engine._taken_slots():
        problems.append(f"slots 2 (shipped) and 3 (own) are taken, got {sorted(engine._taken_slots())}")
    for p in problems:
        print("FAIL", p)
    print("pair_slots selftest:", "PASS" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
