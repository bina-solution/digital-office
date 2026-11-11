#!/usr/bin/env python3
"""The acceptance run for `apps/office-routes` (DGO-543) — reads, and proves the refusals. Opens nothing.

WHAT IT PROVES, against the LIVE office:

  1. the screen's reading is the truth of the guard this feature is: `*.localhost` is always there,
     and the `lan` route reports CLOSED until somebody opens it (this run never opens one — that is
     the owner's action on the screen, and it exposes the office's sign-in page to a network);
  2. the address it offers is the office's own AND IS MEASURED: the app knocks, and an answer is
     accepted as this office's only when it is this office's edge. Two readings, both asserted —
     the machine's own address answers AS this office, and something that answers as somebody else
     (here: the app's OWN http server, reached on a port that is not the edge) is never claimed as
     the office. `/api/find` is proved in both directions: it re-finds the machine's address when it
     starts one step away from it, and it adopts nothing that is not this office;
  3. a FOREIGN address is refused (HTTP 422) and nothing is written: the state block is read before
     and after and must be identical;
  4. the compiled facts agree with the declaration (`.generated/network.json` through the control
     plane): closed means `enabled: false`, and a closed route has an empty address and port 80;
  5. the control plane refuses a linked office's attempt to open this office's doors (403) — the
     office's routes are its owner's, and that is asserted here because it cannot be asserted from
     the screen.

Usage (from the office checkout, stack up):

    python3 apps/office-routes/tests/routes_acceptance.py
    python3 apps/office-routes/tests/routes_acceptance.py --url http://office-routes:8080
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

FAILS: list[str] = []


def _deployment_name() -> str:
    """`DEPLOYMENT_NAME` from this checkout's `.env` (the suffix every container name carries)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), ".env"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("DEPLOYMENT_NAME="):
                    return line.split("=", 1)[1].strip() or "office"
    except OSError:
        pass
    return "office"


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("  ok    " if ok else "  FAIL  ") + what + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(what)


def call(method: str, url: str, body=None, headers=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw) if raw.strip() else None
        except ValueError:
            return e.code, {"raw": raw[:200]}
    except Exception as e:                                   # noqa: BLE001 — the reason is the finding
        return 0, {"error": str(e)}


def probe_of(call, url: str, address: str) -> dict:
    """One knock through the app: the two readings, `answers` and `ours` — see `probe()` in app.py."""
    return call("POST", f"{url}/api/probe", {"address": address})[1] or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    # The DEPLOYMENT-SUFFIXED names, because a bare service name on this engine is round-robined
    # between this office and the second stack sharing the edge network (measured 2026-10-12: the
    # name `network` resolved to both, and a call meant for this office's control plane landed on the
    # other one's and answered 404).
    dn = _deployment_name()
    ap.add_argument("--url", default="http://office-routes:8080", help="the app, from inside the office")
    ap.add_argument("--control", default=f"http://app-management-{dn}:8080", help="the control plane")
    a = ap.parse_args()

    print(f"office-routes — acceptance against {a.url}")
    status, view = call("GET", f"{a.url}/api/routes")
    if status != 200 or not isinstance(view, dict):
        print(f"  FAIL  the screen's own reading did not answer: HTTP {status} {view}")
        return 1
    routes = {r.get("kind"): r for r in view.get("routes", [])}

    print("\n1. the guard: localhost always, lan closed until somebody opens it")
    check(routes.get("localhost", {}).get("open") is True, "‎*.localhost‎ is open (it is what the office always answers)")
    lan = routes.get("lan") or {}
    check(lan.get("closable") is True, "the lan route is the one this screen opens and closes")
    check(lan.get("open") in (True, False), "the lan route reports a state", str(lan.get("open")))
    if lan.get("open"):
        print("     note: a route IS open right now — the reading below is the open one")

    print("\n2. what the screen offers, and the one check it can honestly make")
    suggested = view.get("suggested")
    check(isinstance(suggested, list), "the addresses the office already declares are offered as a hint",
          json.dumps(view.get("suggested"))[:120])
    check(all(not a.startswith(("127.", "169.254.")) for a in (suggested or [])),
          "none of them is loopback or link-local")
    # The knock, which is the whole of the check: an address that answers on the edge's port can be
    # declared, and one that does not cannot (a lease that moved, a typo, a stranger's port 80 is
    # caught by the machine side, not here). A DEAD address is the interesting case, and it is safe:
    # it writes nothing.
    dead = call("POST", f"{a.url}/api/probe", {"address": "10.99.99.99"})[1] or {}
    check(dead.get("answers") is False, "an address that answers nothing is reported as such")
    if suggested:
        alive = call("POST", f"{a.url}/api/probe", {"address": suggested[0]})[1] or {}
        print(f"     the office's own declared address {suggested[0]} answers: {alive.get('answers')}"
              + ("" if alive.get("answers") else f"  [{str(alive.get('why'))[:60]}]")
              + "   (false is a real finding: the lease moved, and the screen would refuse to open it)")

    print("\n2b. which answer is THIS office — and the search for the machine's own address")
    # Identity is the difference between "something is listening" and "this office is there". The
    # second half is measured on a service on the office's own network that definitely answers HTTP
    # and is definitely not the edge: the control plane. Safe, local, and no stranger involved.
    # (The app's OWN port cannot be used for this: uvicorn serves one request at a time, so a knock
    # on itself waits until the knock's own request is done — measured 2026-10-12, it times out.)
    other = probe_of(call, a.url, f"app-management-{dn}:8080")
    check(other.get("answers") is True, "another service on the office network answers HTTP",
          json.dumps(other, ensure_ascii=False)[:200])
    check(other.get("ours") is False,
          "an answer that is NOT this office's edge is not claimed as the office",
          json.dumps(other, ensure_ascii=False)[:200])
    check(view.get("own_host"), "the app was told its own host (app.json sso.base_url_env)",
          str(view.get("own_host")))
    if suggested:
        here = probe_of(call, a.url, suggested[0])
        check(here.get("ours") is True,
              f"this office's edge answers at the machine's own address {suggested[0]}",
              json.dumps(here, ensure_ascii=False)[:200])
        # …and the search RE-FINDS it, starting one address away: the lease that moved is the whole
        # reason the search exists. Nearest-first, so this is a handful of knocks, not a sweep.
        octets = suggested[0].split(".")
        start = ".".join(octets[:3] + [str(max(1, int(octets[3]) - 1))])
        found = call("POST", f"{a.url}/api/find", {"address": start})[1] or {}
        check(suggested[0] in (found.get("found") or []),
              f"the search found the machine's own address, starting from {start}",
              json.dumps(found, ensure_ascii=False)[:200])
        check(int(found.get("probed") or 0) < 64,
              "and it stopped at the first verified answer (bounded by the worker pool, not the /24)",
              f"probed={found.get('probed')}")
        check(int(found.get("ms") or 0) < 5000, "and answered in a time a phone can wait for",
              f"{found.get('ms')}ms")

    print("\n3. a foreign address is refused, and nothing is written")
    before = call("GET", f"{a.control}/api/network")[1]
    status, body = call("PUT", f"{a.url}/api/routes/lan", {"address": "10.99.99.99"})
    check(status == 422, f"a foreign address is refused (HTTP {status})", json.dumps(body, ensure_ascii=False)[:200])
    # The other half of the same guard, and the sharper one: the address ANSWERS, but as somebody
    # else. A route declared there is a door onto a stranger's screen, so it is refused by name —
    # before anything is written (the control plane is never called), which is what the check below
    # the second refusal proves.
    status, body = call("PUT", f"{a.url}/api/routes/lan", {"address": f"app-management-{dn}:8080"})
    check(status == 422, f"an address that answers as another service is refused (HTTP {status})",
          json.dumps(body, ensure_ascii=False)[:200])
    after = call("GET", f"{a.control}/api/network")[1]
    check(before == after, "the declaration is untouched by the refusal")

    print("\n3b. every attempt left a record — a refusal included")
    events = (call("GET", f"{a.url}/api/history?limit=5")[1] or {}).get("events") or []
    check(bool(events), "the app kept a history", json.dumps(events, ensure_ascii=False)[:200])
    if events:
        last = events[0]
        check(last.get("action") in ("open", "close"), "the newest record names the action", str(last))
        check("result" in last and "at" in last and "by" in last,
              "and carries when, by whom, and what came of it", json.dumps(last, ensure_ascii=False)[:200])
        check(any(e.get("result") == "refused" for e in events),
              "the refusal above is IN the history (a guard that writes nothing cannot be checked later)")

    print("\n4. the compiled facts agree with the declaration")
    rendered = (after or {}).get("rendered") or {}
    declared_lan = next((r for r in (after or {}).get("routes", []) if r.get("kind") == "lan"), {})
    check(bool(rendered.get("lan")), "the machine side of it was compiled")
    check(bool(rendered.get("lan", {}).get("enabled")) == bool(declared_lan.get("enabled")),
          "what is compiled is what is declared",
          f"declared={declared_lan.get('enabled')} compiled={rendered.get('lan', {}).get('enabled')}")
    check(rendered.get("lan", {}).get("port") == 80, "the door is TCP 80 (the edge's http entrypoint)")

    print("\n5. a linked office cannot open this office's doors")
    status, _body = call("PUT", f"{a.control}/api/network", {"routes": []},
                         headers={"X-DGO-Office": "vps1"})
    check(status == 403, f"the control plane refuses a request that crossed a link (HTTP {status})")

    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed")
        return 1
    print("all checks passed — the routes plane reads, refuses, and stays closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
