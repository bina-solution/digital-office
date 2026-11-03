#!/usr/bin/env python3
"""test_served_ports — the firewall opens every door the link proxy listens on (DGO-1002).

`converge._served_ports_local` is what the tunnel's firewall accepts on a served pair; the link proxy
listens by `catalog.serve_with_agents` — `serve:` ENRICHED with the agent door each served app declares
in its registry row (DGO-570). Until 2026-10-22 the firewall read `serve:` alone, so an agent port the
office did not write by hand (browser42's 8931 on hp-laptop, served by `{"*": {}}`) was listened on
and dropped: every linked office's `bbox b42 task --office hp-laptop` timed out at the HP's tunnel
address. These assert on the function the running system calls, with the registry each caller passes.

Run: python3 apps/dgo-extend/tests/test_served_ports.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

REGISTRY = {"apps": [
    {"app": "browser42", "alias": "browser42", "port": 80, "agent_api_port": 8931, "service": "browser42-caddy"},
    {"app": "bina-ds", "alias": "bina", "port": 3080, "agent_api_port": 3081, "service": "bina-ds"},
    {"app": "drive", "alias": "drive", "port": 8975, "service": "drive"},
]}
FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    office = {"id": "hp-laptop", "serve": {"*": {}}, "tunnel": {"slot": 5}}
    ports = converge._served_ports_local(office, 5, REGISTRY)
    check(ports.get("browser42:agent") == 8931, f"a wildcard serve opens browser42's declared agent door: {ports}")
    check(ports.get("bina-ds:agent") == 3081, f"…and Bina's: {ports}")
    check("drive:agent" not in ports, "an app that declares no agent door gets none invented")
    explicit = converge._served_ports_local({**office, "serve": {"*": {}, "bina-ds": {"port": 3080, "agent_api_port": 3999}}}, 5, REGISTRY)
    check(explicit.get("bina-ds:agent") == 3999, f"the office's own words win over the registry: {explicit}")
    narrowed = converge._served_ports_local({**office, "serve": {"bina-ds": {"port": 3080}}}, 5, REGISTRY)
    check("browser42:agent" not in narrowed, f"an app the office does not serve opens nothing: {narrowed}")
    bare = converge._served_ports_local(office, 5)
    check("browser42:agent" not in bare, "without a registry the old reading stands (callers must pass theirs)")
    # `serve.only` narrows per PEER exactly as the proxy does: the door and the catalog stay, an agent door
    # is opened only for an app on that peer's list — the firewall's accept has no destination address
    only = {**office, "serve": {"*": {}, "only": {"vps1": ["plane", "bina-ds"]}}}
    vps1 = converge._served_ports_local(only, 5, REGISTRY, peer="vps1")
    check("browser42:agent" not in vps1 and vps1.get("bina-ds:agent") == 3081,
          f"a peer narrowed to plane and bina-ds gets Bina's agent door and not the browser's: {vps1}")
    check("door" in " ".join(vps1) or len(vps1) >= 2, f"…and keeps the link's door and the catalog: {vps1}")
    mac = converge._served_ports_local(only, 5, REGISTRY, peer="macbook")
    check(mac.get("browser42:agent") == 8931, f"a peer not named in serve.only is given what serve says: {mac}")
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_served_ports" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
