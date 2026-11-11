#!/usr/bin/env python3
"""The cross-office half of `computers`, as one command, against the running office and a REAL peer.

What this proves, and why each check is here — every one of them was a live defect found in this
codebase on 2026-11-02, and every one of them was invisible from a unit test:

  1. `status`, `probe`, `audit` and `authorize-command` on a `<machine>.<office>` id answer from the
     office that HOLDS the machine. Three of them used to stop at a local lookup and answer
     `404 «לא נמצא מחשב בזהות…»` inside a dialog for a machine that plainly exists; `probe` answered
     `500` for local machines too, because it called the status route without the request.
  2. the «אישור המפתח» answer carries the PEER's key, not this office's: approving our own key on
     somebody else's machine is the wrong command, and the two are told apart by the key's own name.
  3. `DELETE` on a peer's machine is refused BY NAME (`403`), not answered as "no such machine".
  4. `stream`/`transfer` to or from a peer is refused BY NAME (`501`) instead of `404`.
  5. the sharing gate: a request that only CLAIMS an office is refused (`403`), and a local caller
     still gets the whole fleet.

It needs no peer on new code — every op it exercises is one the peer already has.

Usage (from the office checkout, with the stack up):

    python3 apps/computers/tests/cross_office_acceptance.py            # any linked office
    python3 apps/computers/tests/cross_office_acceptance.py --office macbook
    python3 apps/computers/tests/cross_office_acceptance.py --skip-audit   # audit runs a script there

Exit 0 when everything holds, 1 otherwise; exit 2 when there is no peer machine to test against
(that is "not applicable here", which is not the same answer as "passes").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

COMPUTERS = "http://computers:8977"
for _stream in (sys.stdout, sys.stderr):          # Hebrew sentences out of a Windows code page
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None,
         timeout: float = 60.0) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"content-type": "application/json"} if data else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(COMPUTERS + path, method=method, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="", help="linked office id to test (default: the first one)")
    ap.add_argument("--machine", default="", help="the peer machine id (default: the first remote row)")
    ap.add_argument("--skip-audit", action="store_true", help="skip the audit check (it runs a script there)")
    args = ap.parse_args()

    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        print(("ok    " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
        if not ok:
            fails += 1

    code, fleet = call("GET", "/api/computers?probe=0")
    check("the fleet answers", code == 200, str(code))
    rows = fleet.get("computers") or []
    local = [r for r in rows if not r.get("remote")]
    remote = [r for r in rows if r.get("remote")]
    check("a local caller still sees this office's own machines", bool(local), f"{len(local)}")

    if args.machine:
        mine = next((r for r in remote if r.get("id") == args.machine), None)
    else:
        mine = next((r for r in remote if args.office and (r.get("remote") or {}).get("office") == args.office),
                    remote[0] if remote else None)
    if not mine:
        print()
        print("no machine of a linked office is in the fleet — nothing to test against (not a pass).")
        return 2
    cid = mine["id"]
    office = (mine.get("remote") or {}).get("office") or "?"
    print(f"── peer machine: {cid} (office {office})")

    code, st = call("GET", f"/api/computers/{cid}/status")
    check("status is answered by its office", code == 200 and st.get("office") == office,
          f"{code} office={st.get('office')}")

    code, pr = call("POST", f"/api/computers/{cid}/probe", {})
    check("probe is answered by its office", code == 200 and (pr.get("office") in (office, None)),
          f"{code} {pr.get('error') or pr.get('state')}")

    if not args.skip_audit:
        code, au = call("GET", f"/api/computers/{cid}/audit", timeout=180)
        # a machine that is down says so (409/502) — what must NOT happen is "no such machine" (404)
        check("audit does not answer 'no such machine'", code != 404, f"{code} {au.get('error') or ''}")

    code, ac = call("POST", f"/api/computers/{cid}/authorize-command", {})
    cmd = (ac.get("command") or "")
    ours = call("POST", "/api/computers/" + (local[0]["id"] if local else "x") + "/authorize-command", {})

    def key_name(command: str) -> str:
        """The NAME of the office key inside the command — its last field, e.g. `office-key@local`.

        Not the command's last word: that is the `chmod` target (`~/.ssh/authorized_keys`), and taking
        it made this check compare a path with itself and fail over two different keys.
        """
        m = re.search(r"echo '([^']+)'", command or "")
        return m.group(1).rsplit(" ", 1)[-1].strip() if m else ""

    their_name = key_name(cmd)
    our_name = key_name(ours[1].get("command") or "") if ours[0] == 200 else ""
    check("the key offered is the PEER's, not ours",
          code == 200 and bool(their_name) and their_name != our_name,
          f"{code} theirs={their_name} ours={our_name}")

    code, de = call("DELETE", f"/api/computers/{cid}")
    check("a peer's machine is refused by name, not 'no such machine'",
          code == 403 and "שייך ללשכה" in (de.get("error") or ""), f"{code} {de.get('error') or ''}")

    for path, body in (("/stream", {"to": local[0]["id"] if local else "", "volume": "x"}),
                       ("/transfer", {"to": cid, "volume": "x"})):
        source = cid if path == "/stream" else (local[0]["id"] if local else "")
        code, tr = call("POST", f"/api/computers/{source}{path}", body)
        check(f"{path} across offices is refused by name",
              code == 501 and "אינה נתמכת" in (tr.get("error") or ""), f"{code} {tr.get('error') or ''}")

    code, fo = call("GET", "/api/computers", headers={"x-dgo-office": "no-such-office"})
    check("a request that only CLAIMS an office is refused",
          code == 403 and "אינה מקושרת" in (fo.get("error") or ""), f"{code} {fo.get('error') or ''}")

    print()
    if fails:
        print(f"cross_office_acceptance — {fails} failing")
        return 1
    print("cross_office_acceptance — all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
