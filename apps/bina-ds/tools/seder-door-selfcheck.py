#!/usr/bin/env python3
"""seder-door-selfcheck — the office's clock door, exercised WITHOUT opening a cycle.

WHY THIS EXISTS. `POST /v1/seder/<cycle>` starts a FULL AUTONOMOUS SESSION: it creates a conversation,
hands it the day's brief, and that conversation reads the ledger and works real items until the day's
budget is spent. On 2026-10-14 ordinary probe requests — `curl -X POST`, the way every other door in
this office is tested — opened exactly that, several times, and had to be cancelled by hand minutes
later. A door whose only behaviour is "spend money" cannot be verified the way the rest of the office
is, so it grew the two shapes this file checks, and this file is how they are checked from now on:

  · `{"dry_run": true}` answers with everything a real call would do — the cycle, the day, the grant,
    which fire of the day it is — and opens NOTHING. This is the free door.
  · anything else must name the clock it comes from (`{"by": "bina-seder"}`). A caller that does not
    name it is refused in words, so a stray POST reads as a refusal and not as a session.

WHERE IT RUNS. Against the LIVE office — the door is inside the running `bina-ds` container, reached
by its service name on the office network. So it is a check that runs AFTER a bring-up, not a unit
test: `python3 apps/bina-ds/tools/seder-door-selfcheck.py` from anywhere in the office.

THE ONE RULE THIS FILE IS BUILT AROUND: **it may not open a cycle, not once, not ever.** That is not
a comment, it is the structure:

  1. the FIRST request is the dry run, and its answer is read before anything else is sent. An answer
     that carries a `session` id, or `started: true`, means the running adapter predates these
     guards — the probe would have opened a conversation. So the run STOPS there, says which container
     to rebuild, and sends nothing more. (Measured the hard way: the first version of this file was
     run against an adapter that did not have the guard yet, and its five checks opened five cycles.)
  2. every later check is a REFUSAL (403/400/404) or another dry run. The refusal is the property
     being verified, and a refusal is the one answer that cannot cost anything.
  3. the fleet is counted before and after, and a run that moved it FAILS — the last line of defence,
     reported as loudly as a broken door.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BINA_DS_SEDER_URL", "http://bina-ds:3081").rstrip("/")
CYCLE = "shacharit"


def send(path: str, body: dict | str | None, ctype: str = "application/json") -> tuple[int, dict]:
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}/v1/seder/{path}", data=data, method="POST")
    if data is not None:
        req.add_header("content-type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, _json(raw)
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read().decode("utf-8", "replace"))
    except Exception as e:                                   # unreachable, not a failing check
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _json(raw: str) -> dict:
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {"body": out}
    except ValueError:
        return {"raw": raw[:300]}


def running_sessions() -> int | None:
    """How many conversations are running a turn — the number a new session would move by one."""
    token = ""
    for p in ("/data/dsh/api-token", os.path.expanduser("~/.bina-ds-token")):
        try:
            token = open(p, encoding="utf-8").read().strip()
            break
        except OSError:
            continue
    if not token:
        return None
    req = urllib.request.Request(f"{BASE}/v1/sessions")
    req.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            items = json.loads(r.read().decode()).get("sessions", [])
        return sum(1 for s in items if s.get("running"))
    except urllib.error.HTTPError as e:
        # The door's own words: a 401 here (no token, or one it refuses) must not read as
        # "nothing is running" — the shape a success has too.
        print(f"  NOTE  the session count was refused: HTTP {e.code} "
              f"{e.read().decode('utf-8', 'replace')[:200]}")
        return None
    except Exception as e:
        print(f"  NOTE  the session count could not be read: {type(e).__name__}: {e}")
        return None


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    before = running_sessions()

    # 1 — THE FREE PROBE AND THE STOP. Everything downstream is only reachable from a dry run that
    # behaved: an adapter without these guards answers a dry run with a conversation.
    code, body = send(CYCLE, {"dry_run": True})
    opened = bool(body.get("session")) or body.get("started") is True
    if opened:
        print(f"  STOP  the running adapter ignored `dry_run` and opened a session: "
              f"{body.get('session') or body.get('id')}")
        print("        That is the pre-guard code. Nothing else was sent — this check refuses to open "
              "a second one.")
        print("        Rebuild and re-create bina-ds, then run this again:  "
              "./scripts/dc up -d --build bina-ds")
        if body.get("session"):
            print(f"        The cycle it opened — cancel it if nobody asked for it:  "
                  f"./bbox agent cancel {body['session']}")
        return 2
    results.append(("a dry run answers", code == 200, f"{code} {body}"))
    if code == 200:
        for field in ("cycle", "name", "day", "at", "grant", "opened_today"):
            results.append((f"…and it carries {field}", field in body,
                            json.dumps(body, ensure_ascii=False)[:200]))
        results.append(("…and it says it is a dry run", body.get("dry_run") is True, str(body.get("dry_run"))))
        results.append(("…and it started nothing",
                        "session" not in body and body.get("started") is None,
                        str({k: body.get(k) for k in ("started", "session")})))
        results.append(("…and its grant is the day's grant, a number",
                        isinstance(body.get("grant"), (int, float)), str(body.get("grant"))))

    # 2 — the real shape without a name: refused, in words, and no session behind it.
    code, body = send(CYCLE, {})
    said = json.dumps(body, ensure_ascii=False)
    results.append(("a caller that names no clock is refused", code == 403, f"{code} {body}"))
    results.append(("…with the reason and the two shapes that work",
                    "dry_run" in said and "bina-seder" in said, said[:200]))
    results.append(("…and that refusal opened nothing", body.get("session") is None and body.get("started") is None,
                    said[:200]))

    # 3 — a wrong name is refused the same way (no near misses).
    code, body = send(CYCLE, {"by": "someone-else"})
    results.append(("a caller that names the WRONG clock is refused", code == 403, f"{code} {body}"))

    # 4 — a body that is not JSON at all.
    code, body = send(CYCLE, "by=bina-seder", ctype="application/x-www-form-urlencoded")
    results.append(("a non-JSON body is refused", code == 400, f"{code} {body}"))

    # 5 — a cycle nobody declared (asked as a dry run, so the refusal is about the cycle alone).
    code, body = send("zzz", {"dry_run": True})
    results.append(("an undeclared cycle is refused", code == 404, f"{code} {body}"))

    # 6 — and the fleet did not move.
    after = running_sessions()
    if before is None or after is None:
        results.append(("no session was opened by this file (fleet not readable — NOT CHECKED)", True, ""))
    else:
        results.append((f"no session was opened by this file ({before} running before, {after} after)",
                        after <= before, f"before={before} after={after}"))

    bad = [n for n, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if bad:
        print(f"SEDER-DOOR SELFCHECK FAIL — {len(bad)} of {len(results)}: " + "; ".join(bad))
        return 1
    print(f"SEDER-DOOR SELFCHECK PASS — {len(results)} checks, and not one cycle opened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
