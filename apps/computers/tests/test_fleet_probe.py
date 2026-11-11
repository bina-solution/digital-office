#!/usr/bin/env python3
"""test_fleet_probe — the fleet is probed at once, not one machine after another (DGO-1359).

Measured 2026-11-05: the MacBook away from home held two machines on the home LAN; each probe waits up to ssh's
8 s for a machine that does not answer, and the fleet probed them in turn — `/api/computers?probe=1` took 17–20 s,
and the control centre, which waits 8 s, read the MacBook's own row «the computers app did not answer». The vault
and ssh are stood in for: four machines, each taking 0.4 s to probe, answer in about 0.4 s and in the same order
and shape as before; `?probe=0` probes nothing.

Run in the app's image: python3 tests/test_fleet_probe.py   (from apps/computers)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("COMPUTERS_DATA", tempfile.mkdtemp(prefix="computers-test-"))

import app  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    names = ["computer_local-local", "computer_ssh-a", "computer_ssh-b", "computer_ssh-c"]
    probed, live, most = [], [0], [0]
    lock = threading.Lock()
    app.local_gateway = lambda: "172.18.0.1"
    app.vault_list = lambda: ([{"id": n} for n in names], None)
    app.computer_record = lambda inst, host: {"id": inst["id"], "label": inst["id"], "host": host, "port": 22,
                                              "user": "root", "builtin": inst["id"].endswith("local")}
    app._computer_ctx = lambda rec, host: ({}, None)

    def slow_probe(rec, sec, max_age=app.PROBE_TTL):
        with lock:
            live[0] += 1
            most[0] = max(most[0], live[0])
        time.sleep(0.4)
        with lock:
            live[0] -= 1
            probed.append(rec["id"])
        ok = rec["id"] != "computer_ssh-b"
        return {"id": "ignored", "ok": ok, "state": "ok" if ok else "error"}
    app.probe_computer = slow_probe

    began = time.monotonic()
    got = app.api_computers(probe=1)
    took = time.monotonic() - began
    check(took < 1.0, f"four machines of 0.4 s each answer at once, not in 1.6 s: {took:.2f} s")
    check(most[0] > 1, f"more than one probe ran at the same time: {most[0]}")
    check(sorted(probed) == sorted(names), f"every machine probed once: {probed}")
    rows = got.get("computers") or []
    check([r["id"] for r in rows][0] == "computer_local-local", "the built-in machine is still first")
    check(all(r["id"] != "ignored" for r in rows), "a probe's own id never replaces the machine's")
    bad = next(r for r in rows if r["id"] == "computer_ssh-b")
    check(bad.get("state") == "error" and rows[-1]["id"] == "computer_ssh-b", "a failed machine sorts last, as before")
    check(got.get("count") == 4, "the count is the fleet's")

    probed.clear()
    got = app.api_computers(probe=0)
    check(not probed and len(got.get("computers") or []) == 4, "?probe=0 probes nothing")

    # …and says what the last probe SAID (2026-11-11, vps1 after batch 38: the terminal read `ok`/`state` off this
    # list and showed «לא ידוע» for a machine that answered — the rows were the bare records)
    with app._probe_lock:
        app._probe_cache.clear()
        app._probe_cache["computer_local-local"] = (time.time() - 50, {
            "id": "x", "host": "172.18.0.1", "port": 22, "user": "root", "checked_at": 1, "cached": False,
            "ok": True, "state": "ok", "hostname": "srv"})                     # the shape probe() stores
        app._probe_cache["computer_ssh-b"] = (time.time() - 5000, {"id": "x", "ok": False, "state": "no_ssh"})
    rows = {r["id"]: r for r in app.api_computers(probe=0)["computers"]}
    here, b, a = rows["computer_local-local"], rows["computer_ssh-b"], rows["computer_ssh-a"]
    check(here.get("ok") is True and here.get("state") == "ok" and here.get("cached") is True,
          f"a probed machine's row carries its last reading, marked cached: {here}")
    check(here.get("checked_at") == 1 and here.get("label") == "computer_local-local",
          "the reading's time comes along and the record's own fields stay")
    check(b.get("state") == "no_ssh" and b.get("ok") is False, f"an old reading is still the last word: {b}")
    check("ok" not in a and "state" not in a, f"a machine never probed is the bare record: {a}")
    check(not probed and set(rows) == set(names), "still no probe, and every id is the machine's own")
    with app._probe_lock:
        app._probe_cache.clear()

    app.PROBE_WORKERS = 1
    began = time.monotonic()
    app.api_computers(probe=1)
    check(time.monotonic() - began >= 1.5, "with one worker it is the old order, one after another")

    for f in FAIL:
        print("FAIL:", f)
    print("test_fleet_probe:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
