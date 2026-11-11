#!/usr/bin/env python3
"""test_herd_reads — computers believes «this office is the herd's» only from the link's door (DGO-1800).

The door (apps/dgo-extend/link-proxy.py) writes `x-dgo-herd: 1` for a peer whose key is the herd file's and removes a
peer's own; any other container on this office's network could write the header, so it is believed only from the
door's own address — the same rule as x-dgo-office. What it decides today is a COUNT (AGENTS.md rule 8: count before
refusing): /api/callers' door reads carry `herd`, and `door_reads_not_herd` is what narrowing would touch.

Run in the app's image: python3 tests/test_herd_reads.py   (from apps/computers)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))

import app  # noqa: E402
from starlette.requests import Request  # noqa: E402

FAIL: list[str] = []
DOOR = "10.79.0.7"


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


def req(client: str, headers: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/computers", "query_string": b"",
                    "client": (client, 40000), "server": ("computers", 8977), "scheme": "http",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def main() -> int:
    app._hops = lambda: ({DOOR}, set())                    # the door's address, as _hops() resolves it
    said = lambda client, h: app._door_read(req(client, h))   # noqa: E731  → (from the door, the herd's)
    office = {"x-dgo-office": "vps1"}
    check(said(DOOR, {**office, "x-dgo-herd": "1"}) == (True, True), "from the door's address, `1` is believed")
    check(said("172.18.0.33", {**office, "x-dgo-herd": "1"}) == (False, False),
          "from any other container it is not — and that read is not the door's at all")
    check(said(DOOR, {**office, "x-dgo-herd": "yes"}) == (True, False), "only `1` means yes")
    check(said(DOOR, office) == (True, False), "the door's read with no mark is a read by an office not the herd's")
    check(said("", {**office, "x-dgo-herd": "1"}) == (False, False), "a request with no address is not the door")

    app._DOOR_READS.clear()
    app._count_door_read("vps1", "/api/computers", True)
    app._count_door_read("vps1", "/api/computers", True)
    app._count_door_read("exw", "/api/computers", False)
    app._count_door_read("exw", "/api/computers/c1/status", False)
    app._count_door_read(app.NOT_THE_DOOR, "/api/computers", False)
    rows = {(r["office"], r["route"], r["herd"]): r["count"] for r in app._DOOR_READS.values()}
    check(rows.get(("vps1", "/api/computers", True)) == 2 and rows.get(("exw", "/api/computers", False)) == 1,
          f"the reads are counted apart by whether the door said herd: {rows}")
    out = app.api_callers()
    check(out.get("door_reads_not_herd") == 2,
          f"/api/callers says how many of the DOOR's reads narrowing would touch — a claim from elsewhere is not one: "
          f"{out.get('door_reads_not_herd')}")
    check(all("herd" in r for r in out.get("door_reads", [])), "every door-read row says herd or not")

    # past the cap, the overflow is still told apart by herd, so the total of what narrowing would touch stays true
    app._DOOR_READS.clear()
    cap = app._REFUSED_CAP
    for i in range(cap):
        app._count_door_read(f"o{i}", "/api/computers", False)
    app._count_door_read("late-herd", "/api/computers", True)
    app._count_door_read("late-client", "/api/computers", False)
    over = {r["herd"]: r["count"] for r in app._DOOR_READS.values() if r["office"] == "(many)"}
    check(over == {True: 1, False: 1}, f"the rows over the cap keep herd apart: {over}")
    check(app.api_callers()["door_reads_not_herd"] == cap + 1, "…and the not-herd total counts the overflow's own")
    app._DOOR_READS.clear()

    print(f"test_herd_reads: {'all passed' if not FAIL else f'{len(FAIL)} failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
