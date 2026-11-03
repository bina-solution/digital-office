#!/usr/bin/env python3
"""test_listen_ports — two pairs that dial one office get two WireGuard ports.

Measured 2026-11-01 on the Dell (portable-ubuntu, DGO-1080): the HP dials it over UDP on the one port
it publishes (51830), and the MacBook's pair, moved to the carriers' TCP path, was rendered with the
same 51830. `ip link set up dev wg3` answered «Address already in use», and the MacBook pair ran
without a tunnel while every screen said paired
(issues/a-second-pair-that-dials-an-office-collides-on-its-listen-port.yaml).

Renders the Dell's own records through `app._link_pairs` → `_tunnel_descriptors` → `net.render_multi`,
the path `render_tunnel` takes, and asks the rendered files and the carrier's plan.

Run inside the app's image (it imports the app): `python3 tests/test_listen_ports.py` from
`apps/dgo-extend`. Exit code 0 = every check held.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DGO_STATE_DIR"] = tempfile.mkdtemp(prefix="listen-state-")
os.environ["DGO_TUNNEL_DIR"] = tempfile.mkdtemp(prefix="listen-tunnel-")
os.environ["DGO_REGISTRY_DIR"] = tempfile.mkdtemp(prefix="listen-registry-")
os.environ.pop("DGO_WG_PORT", None)

import app  # noqa: E402
import net  # noqa: E402
import pair_api  # noqa: E402

FAIL = []
HOME = {"id": "portable-ubuntu", "tunnel": {}}


def check(cond, what):
    if not cond:
        FAIL.append(what)


def paired(oid, slot, role, dial, transport="", door=""):
    """A paired record as the Dell holds it: the Dell is the side that is dialed (dial != role)."""
    tun = {"slot": slot, "side": 1 if role == "host" else 2, "role": role, "dial": dial,
           "endpoint": "192.168.16.105", "port": 51830, "listen_port": 51830}
    if transport:
        tun["transport"] = transport
    if door:
        tun.update({"port": pair_api.DOOR_WG_BASE + slot, "listen_port": pair_api.DOOR_WG_BASE + slot,
                    "door": door})
    return {"id": oid, "kind": "paired", "identity": {"wg": chr(65 + slot) * 43 + "="},
            "tunnel": tun, "links": [{"office": HOME["id"], "direction": "both"}]}


def render(records):
    pairs = app._link_pairs(HOME, {r["id"]: r for r in records})
    out = net.render_multi(app._tunnel_descriptors(pairs),
                           carry={"accept": False, "own_address": "192.168.16.105"})
    ports = {}
    for name, text in out["files"].items():
        if name.startswith("pairs/"):
            ports[name] = int(re.search(r"^ListenPort = (\d+)$", text, re.M).group(1))
    return out, ports


def main() -> int:
    served = app.cv._served_ports_local
    app.cv._served_ports_local = lambda *a, **k: {}
    try:
        # The Dell today: the HP dials it over UDP, the MacBook's pair rides the carriers.
        hp = paired("hp-laptop", 4, "joiner", "host")
        mac = paired("macbook", 3, "host", "joiner", transport="tcp")
        out, ports = render([hp, mac])
        check(len(set(ports.values())) == len(ports) == 2, f"two pairs, two ports: {ports}")
        check(ports.get("pairs/wg4.conf") == 51830,
              f"the UDP pair keeps the port it is dialed on (51830): {ports}")
        carried = {c["iface"]: c["wg_port"] for c in out["carry"]["pairs"]} if isinstance(out["carry"], dict) \
            else {c["iface"]: c["wg_port"] for c in out["carry"]}
        check(carried.get("wg3") == ports.get("pairs/wg3.conf"),
              f"the carrier hands the TCP pair's datagrams to the port its interface listens on: "
              f"{carried} vs {ports}")

        # Two pairs that both ride the carriers, both paired on the one published port.
        a = paired("office-a", 5, "host", "joiner", transport="tcp")
        b = paired("office-b", 6, "host", "joiner", transport="tcp")
        _, ports = render([a, b])
        check(len(set(ports.values())) == len(ports) == 2, f"two carried pairs, two ports: {ports}")

        # A door's pair (a join) already listens on its own local port; it keeps it.
        door = paired("office-c", 7, "host", "joiner", transport="tcp", door="wss://link.example.test/carry")
        _, ports = render([hp, door])
        check(ports.get("pairs/wg7.conf") == pair_api.DOOR_WG_BASE + 7,
              f"a door's pair keeps DOOR_WG_BASE + slot: {ports}")
        check(ports.get("pairs/wg4.conf") == 51830, f"beside it the UDP pair keeps 51830: {ports}")

        # A carried pair this office DIALS keeps the dialing side's own port (`DGO_WG_PORT + slot`).
        dialer = paired("office-d", 8, "joiner", "joiner", transport="tcp")
        dialer["tunnel"]["listen_port"] = None              # validate_paired: the dialing side has none
        _, ports = render([hp, dialer])
        check(ports.get("pairs/wg8.conf") == net.WG_PORT + 8,
              f"a carried pair this office dials listens on DGO_WG_PORT + slot: {ports}")

        # THE UPDATE ITSELF (measured on the Dell after the roll): files rendered by the old rule are
        # found stale at startup, so the tunnel is rendered whole; files this code wrote are not.
        home_office, declarations = app.cv.home_office, app.all_declarations
        app.cv.home_office, app.all_declarations = (lambda: HOME), (lambda: [hp, mac])
        try:
            out, _ = render([hp, mac])
            base = Path(os.environ["DGO_TUNNEL_DIR"])
            (base / "pairs").mkdir(parents=True, exist_ok=True)
            for name, text in out["files"].items():
                (base / name).write_text(text, encoding="utf-8")
            check(app._stale_pair_files() == [], f"a restart over this code's own files bounces nothing: "
                                                  f"{app._stale_pair_files()}")
            # An `Endpoint` the computers app did not answer for yet is not a change of plan.
            wg4 = (base / "pairs/wg4.conf").read_text(encoding="utf-8")
            (base / "pairs/wg4.conf").write_text(wg4 + "Endpoint = 192.168.16.99:51820\n", encoding="utf-8")
            check(app._stale_pair_files() == [], f"another Endpoint alone bounces nothing: {app._stale_pair_files()}")
            old = (base / "pairs/wg3.conf").read_text(encoding="utf-8")
            (base / "pairs/wg3.conf").write_text(
                re.sub(r"^ListenPort = \d+$", "ListenPort = 51830", old, flags=re.M), encoding="utf-8")
            check(app._stale_pair_files() == ["pairs/wg3.conf"],
                  f"wg3 rendered by the old rule (51830) is stale at startup: {app._stale_pair_files()}")
            # …and the startup step renders the tunnel for it, and only then.
            calls = []
            render_tunnel = app.render_tunnel
            app.render_tunnel = lambda *a, **k: calls.append(a) or {}
            try:
                app._render_tunnel_if_stale()
                check(len(calls) == 1, f"a stale port renders the tunnel once at startup: {calls}")
                (base / "pairs/wg3.conf").write_text(old, encoding="utf-8")
                calls.clear()
                app._render_tunnel_if_stale()
                check(calls == [], f"nothing stale, nothing rendered: {calls}")
            finally:
                app.render_tunnel = render_tunnel
        finally:
            app.cv.home_office, app.all_declarations = home_office, declarations
    finally:
        app.cv._served_ports_local = served
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_listen_ports" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
