#!/usr/bin/env python3
"""The link proxy leaves a namespace dgo-net no longer holds, and only that one (DGO-1753).

`link-proxy.py` runs in dgo-net's network namespace. When dgo-net is restarted it gets a new namespace and the
proxy stays in the old one, whose endpoint (and default route) Docker took away; the proxy then ends, so its
restart policy joins the live one. These checks drive the decision with routing tables shaped like /proc's:
- a live namespace (a default route through eth0, IPv4 or IPv6) is never left;
- the dead one is recognised even when a kernel WireGuard device and its /24 outlived dgo-net there;
- nothing is decided inside the start grace, it takes a whole run, and a default route or a failed look breaks it;
- the watch ends the process once, with exit status 3; a bad setting is the default, not a crash.
Run: python3 apps/dgo-extend/tests/test_link_stranded.py
"""
from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path

APP = Path(__file__).resolve().parent.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


door = _load(APP / "link-proxy.py", "dgo_door_stranded")

HEADER4 = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
LIVE4 = (HEADER4 + "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
         "wg3\t00034F0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n")
STALE4 = HEADER4 + "wg3\t00034F0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
LO6 = ("00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
       "00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo\n")
LIVE6 = LO6 + ("00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
               "fd000000000000000000000000000001 00000400 00000001 00000000 00000003     eth0\n")


def test_no_default_route():
    assert not door.no_default_route(LIVE4, LO6), "a live IPv4 namespace read as gone"
    assert door.no_default_route(STALE4, LO6), "the stale namespace (a wg /24 left) read as live"
    assert door.no_default_route(HEADER4, ""), "an empty namespace read as live"
    assert not door.no_default_route(HEADER4, LIVE6), "an IPv6-only default read as gone"
    assert door.no_default_route(HEADER4 + "lo\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n", LO6), \
        "a default through lo counted as a way out"


def test_grace_then_a_whole_run():
    s = door.Stranded(start=1000.0, grace=30, after=20)
    assert not any(s.step(1000.0 + t, True) for t in range(0, 30, 5)), "decided inside the grace"
    assert not s.step(1035.0, True) and not s.step(1050.0, True), "ended before 20 s without a default route"
    assert s.step(1055.0, True), "did not end after 20 s without a default route"


def test_a_route_or_a_failed_look_breaks_the_run():
    s = door.Stranded(start=0.0, grace=0, after=20)
    s.step(0.0, True)
    s.step(15.0, False)                      # the default route is back: the run ends
    assert not s.step(25.0, True), "a run broken by a default route still counted its start"
    assert s.step(45.0, True), "a new 20 s run did not end"
    s = door.Stranded(start=0.0, grace=0, after=20)
    s.step(0.0, True)
    s.step(10.0, None)                       # the look failed
    assert not s.step(25.0, True), "a failed look did not end the run"


def _watch(gone, ticks=12):
    """The watch with a clock that moves 5 s per look and no real sleep; returns the exit codes it asked for."""
    t = {"now": 0.0}
    codes = []
    stop = threading.Event()

    def look():
        t["now"] += 5.0
        if t["now"] > ticks * 5:
            stop.set()
        return gone

    def end(code):
        codes.append(code)
        stop.set()

    door.watch_namespace(every=5.0, clock=lambda: t["now"], look=look, end=end, stop=stop, grace=10, after=20,
                         sleep=lambda _s: None)
    return codes


def test_the_watch_ends_once_with_status_3_and_never_in_a_live_namespace():
    assert door.STRANDED_EXIT == 3
    assert _watch(True) == [3], "a stranded proxy did not end once with 3"
    assert _watch(False) == [], "a proxy with its default route ended"


def test_a_bad_setting_is_the_default_not_a_crash():
    os.environ["DGO_LINK_STRANDED_AFTER"] = "twenty"
    try:
        assert door._seconds("DGO_LINK_STRANDED_AFTER", 20.0) == 20.0
    finally:
        del os.environ["DGO_LINK_STRANDED_AFTER"]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"link_stranded: {len(tests)} check(s), {len(tests) - failed} pass, {failed} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
