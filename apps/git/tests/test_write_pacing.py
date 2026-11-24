#!/usr/bin/env python3
"""test_write_pacing — GitHub's secondary limits on writes, kept before GitHub enforces them (DGO-2155).

The pacer (adapters/pacing.py) is driven with a clock this test moves and a sleep that only records, so 500 writes
take no time. Claims: 80 writes in a minute go at once and the 81st waits for the first to leave the minute; a wait
over MAX_WAIT is refused with the time to retry; 500 in an hour is the second wall; reads are never counted; each
account has its own count.

Run: python3 apps/git/tests/test_write_pacing.py      # exit 0 = every claim held
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters"))
import pacing  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def main() -> int:
    clock = {"t": 1000.0}
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    p = pacing.WritePacer(now=lambda: clock["t"], sleep=sleep, max_wait=60)
    for i in range(80):
        p.take("a", "POST")
        clock["t"] += 0.1
    check(not slept, "80 writes in 8 s go at once")
    w = p.take("a", "POST")
    check(abs(w - (60 - 8.0)) < 0.01 and slept[-1] == w, f"the 81st waits for the first to leave the minute: {w:.1f}s")
    for _ in range(50):
        p.take("a", "GET")
    check(len(slept) == 1, "reads are never counted nor waited")
    q = pacing.WritePacer(now=lambda: clock["t"], sleep=sleep, max_wait=5)
    for _ in range(80):
        q.take("b", "PUT")
    try:
        q.take("b", "PUT")
        check(False, "a wait over max_wait is refused")
    except pacing.Paced as e:
        check(e.retry_after > 5, f"a wait over max_wait is refused with the time to retry: {e.retry_after:.0f}s")
    q.take("c", "DELETE")
    check(True, "another account's write goes at once: each account has its own count")
    # the hour: 500 writes spread past the minute wall, then the 501st is refused (the hour's wait is long)
    h = pacing.WritePacer(now=lambda: clock["t"], sleep=lambda s: None, max_wait=20)
    for _ in range(500):
        h.take("d", "PATCH")
        clock["t"] += 1.0                 # 60 a minute: under the minute wall, so only the hour can stop it
    try:
        h.take("d", "PATCH")
        check(False, "the 501st write in the hour is refused")
    except pacing.Paced as e:
        check(3000 < e.retry_after <= 3600, f"the 501st write in the hour is refused until the first leaves it: {e.retry_after:.0f}s")
    print(f"test_write_pacing: {'all passed' if not FAIL else str(len(FAIL)) + ' failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
