#!/usr/bin/env python3
"""test_herd — what the network view may read through the herd door, and what it is told when it cannot.

  1. The detail of ONE address (`api/inbound/<ip>`, `api/outbound/<ip>`) is readable, and only when the
     last part IS an address: it is parsed and written back, so no other path rides on the prefix.
  2. A service THIS office does not run is said to be not running here (404), never «no way to this
     computer» (502) — vps1 ran no `security` and its screen blamed the road (2026-11-01, DGO netv-002).
     A linked office's name that does not resolve is still the road: the link proxy did not answer.

Standard library only. Run: python3 tests/test_herd.py   (from apps/computers)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import herd  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    a = herd.allowed
    check(a("security", "api/summary") == "api/summary", "a listed read passes")
    check(a("security", "api/inbound/93.184.216.7") == "api/inbound/93.184.216.7", "one inbound address passes")
    check(a("security", "api/outbound/2001:db8::1") == "api/outbound/2001:db8::1", "an IPv6 destination passes")
    check(a("security", "api/outbound/2001:DB8:0::1") == "api/outbound/2001:db8::1", "an address is written back canonical")
    for bad in ("api/inbound/93.184.216.7/../bans", "api/inbound/x", "api/inbound/", "api/bans/93.184.216.7",
                "api/inbound/93.184.216.7?x=1", "api/settings", "api/inbound/93.184.216.7%2F..%2Fbans",
                "api/inbound/fe80::1%x?limit=99999&hours=99999", "api/inbound/::1%2F..", "api/outbound/fe80::1%eth0"):
        check(a("security", bad) == "", f"refused: {bad}")
    check(a("machine", "api/inbound/93.184.216.7") == "", "a prefix of one service is not another's")

    h = herd.Herd("/nonexistent", {"security": "http://no-such-service.invalid:8995"}, office="t")
    st, body, why = h.get("local", "security", "api/summary", timeout=5)
    check(st == 404 and body is None and "לא פועל" in why, f"local, unresolvable → 404 not running ({st} {why})")
    st, _, _ = h.get("local", "security", "api/inbound/../../etc", timeout=5)
    check(st == 403, f"a path off the list is refused before any network ({st})")
    # a linked office's unresolvable door is the road, not a missing service
    st, _, why = herd.Herd._fetch("http://no-such-door.invalid:9999/api/summary", 5, local=False)
    check(st == 502 and "אין דרך" in why, f"remote, unresolvable → 502 no way ({st} {why})")

    for f in FAIL:
        print("FAIL", f)
    print(f"test_herd: {'FAIL' if FAIL else 'ok'} ({len(FAIL)} failed)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
