#!/usr/bin/env python3
"""test_join_backoff — a joiner whose host does not answer asks less and less often, never less than every 15 min.

DGO-2111 root 22, measured 2026-11-19: link.exf.digital-office.co.il served traefik's default certificate, and the
MacBook's join asked it 1,071 times in one day, each time an SSLError. Every failure rested the same 30 s. Now each
failure in a row doubles the rest (30, 60, 120 … s), up to RETRY_CAP. A host that SAID no (403) still rests
REFUSED_REST, and `again` starts the count over. Driven in memory: `pair_api._MemoryPorts` (the app's own test seam),
an `http` that fails as `_http` does on an SSLError (PairError 502), and a clock this test moves.

Run: python3 apps/dgo-extend/tests/test_join_backoff.py      # exit 0 = every claim held
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import join_api                                                     # noqa: E402
import pair_api                                                     # noqa: E402
from pair_api import PairError                                      # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def main() -> int:
    clock = {"t": 1_000_000.0}
    status = {"code": 502}

    def http(method, url, body=None, headers=None):
        raise PairError("הלשכה אינה עונה: האישור (TLS) שלה לא אומת", status["code"])

    tmp = Path(tempfile.mkdtemp(prefix="dgo-join-backoff-"))
    j = join_api.Joiner(pair_api.Pairing(pair_api._MemoryPorts("macbook", "MacBook", slot=1)), tmp / "joiner.json",
                        now=lambda: clock["t"], http=http, env={"DGO_JOIN": "https://link.example.org"})
    rests = []
    for _ in range(8):
        got = j.step()
        rests.append(round(j.rest_until - clock["t"]))
        check(got.get("state") == "failed", f"a host that does not answer: «failed» ({got.get('state')})")
        clock["t"] = j.rest_until + 1                       # the next pass, once the rest is over
    want = [30, 60, 120, 240, 480, 900, 900, 900]
    check(rests == want, f"each failure in a row doubles the rest, up to {join_api.RETRY_CAP} s: {rests}")
    # a pass inside the rest asks nobody
    asked = {"n": 0}

    def counting(method, url, body=None, headers=None):
        asked["n"] += 1
        return http(method, url, body, headers)
    j.http = counting
    j.step()
    clock["t"] = j.rest_until - 10
    j.step()
    check(asked["n"] == 1, f"a pass inside the rest asks nothing: {asked['n']} call(s) for two passes")
    # `again` (forget) starts over
    j.forget()
    j.step()
    check(round(j.rest_until - clock["t"]) == 30, f"`again` (forget) starts the count over: {round(j.rest_until - clock['t'])}")
    # a refusal rests REFUSED_REST, whatever the count
    status["code"] = 403
    clock["t"] = j.rest_until + 1
    j.step()
    check(round(j.rest_until - clock["t"]) == join_api.REFUSED_REST, "a host that said no rests REFUSED_REST")
    print(f"test_join_backoff: {'all passed' if not FAIL else str(len(FAIL)) + ' failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
