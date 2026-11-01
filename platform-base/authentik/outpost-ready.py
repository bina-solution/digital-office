#!/usr/bin/env python3
"""outpost-ready — the TRUE "SSO is ready" probe for authentik's embedded outpost.

The blueprint writing proxy-provider rows is NOT enough: the embedded outpost (inside
authentik-server) learns them a moment later, and Traefik forward-auth 404s a host until it has.
This asks the outpost's forward-auth endpoint about each gated host and reads a redirect (302) as
"the outpost knows this host" and a 404 as "it does not" — verified behaviour.

Runs INSIDE the cluster against authentik-server, so it's environment-agnostic: identical
signal in CI and local (no host/domain/loopback differences).

  python3 outpost-ready.py            # one shot: exit 0 iff every gated host is served (healthcheck)
  python3 outpost-ready.py --wait     # block until all served, logging progress (bootstrap gate)

Exit 0 = every gated host is served · 1 = at least one is not · 2 = there is no list to ask about.

THE HOST LIST IS THE COMPILER'S: the hosts of THIS render, read from the blueprint that declares
them (`context.gated_hosts` in zz-generated-apps.yaml — the same set its outpost entry binds, written
by the same render). Two earlier answers to "which hosts", and what each cost:

  * a file written ONCE by bootstrap.sh at boot. It made the health of a long-running container a
    statement about a configuration that had since changed: disable an app and this probe reported
    UNHEALTHY for a system that was working perfectly (staging 2026-07-29 — 99 consecutive failures
    under a log whose last line read "SSO fully ready"). A red light over a working system is the
    one failure that discredits every OTHER light.
  * authentik's own API, asked on every run with a token the sentinel minted. That answered "what
    did the LAST apply bind to the outpost", so a host compiled a second ago was simply not in the
    list and the probe said "all served" for a render nobody had applied yet; and it could not look
    at all until the sentinel had re-applied every blueprint and minted the token — minutes, on
    every app switched on, and for ever when the sentinel was crash-looping (MacBook 2026-10-05,
    262 restarts under "the host list cannot be determined"). It also kept a non-expiring API token
    of the admin account in a file for the sake of a health check.

The blueprint is bind-mounted, so the list is the declaration itself: it changes in the same
instant the render does, needs no token and no API, and is still readable while authentik is down.
"""
import json, os, re, sys, time, urllib.request, urllib.error

SERVER    = os.environ.get("AUTHENTIK_READY_SERVER", "http://authentik-server:9000")
ENDPOINT  = SERVER + "/outpost.goauthentik.io/auth/traefik"
BLUEPRINT = os.environ.get("OUTPOST_HOSTS_BLUEPRINT", "/blueprints/custom/zz-generated-apps.yaml")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # don't follow — the redirect itself is the "provider known" signal


_OPENER = urllib.request.build_opener(_NoRedirect)


def _served(host):
    """Does the OUTPOST answer for `host`? 302/200/401/403 = it knows the host; 404 = it does not.

    A 5xx is neither: it is the SERVER saying it cannot answer anyone yet. This used to read
    anything but a 404 as "served", so while authentik-server started the probe reported an office
    whose sign-in was down as fully ready. Measured on hp-laptop, 2026-10-06, second by second
    through one re-creation of the server: 50 s refusing connections, then 21 s of 502 for a host it
    serves AND for a host nobody declared, 3 s of 404 for both, and only then 302 / 404. The hook
    that restarts the server waits on this very answer to know the restart has finished."""
    req = urllib.request.Request(ENDPOINT, headers={
        "X-Forwarded-Host": host, "X-Forwarded-Proto": "http", "X-Forwarded-Uri": "/"})
    try:
        code = _OPENER.open(req, timeout=5).status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        return False                  # server not reachable yet
    return code != 404 and code < 500


def _gated():
    """(hosts, why) — the hosts this office's compiled blueprint gates; `why` is a sentence when
    there is no list to ask about, which is a different fact from "a host is not served"."""
    try:
        with open(BLUEPRINT, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        return [], f"no compiled sign-in blueprint at {BLUEPRINT} ({e.strerror}) — this office was never compiled"
    m = re.search(r"^  gated_hosts: (\[.*\])\s*$", text, re.M)
    if not m:
        return [], (f"{BLUEPRINT} states no `gated_hosts` — it was written by a compiler older "
                    "than this probe; run `bbox run`")
    try:
        hosts = [h for h in json.loads(m.group(1)) if isinstance(h, str) and h]
    except ValueError as e:
        return [], f"{BLUEPRINT}: `gated_hosts` is not a list this probe can read ({e})"
    return hosts, ("" if hosts else f"{BLUEPRINT} gates no host")


def _check():
    """(state, served, missing, why) — state is "ready" | "unserved" | "unknown".

    "unknown" is NOT the same fact as "unserved", and the caller has to be able to tell them apart:
    it means there is nothing to ask about, not that a host the platform gates is being refused.
    Reporting it as "not serving" is what sent every `bbox run` on a MacBook into restarting
    authentik-server, waiting four minutes and printing "EVERY gated surface is down" over a working
    SSO (measured 2026-10-05)."""
    hosts, why = _gated()
    if not hosts:
        return "unknown", [], [], why
    served = [h for h in hosts if _served(h)]
    missing = [h for h in hosts if h not in served]
    return ("ready" if not missing else "unserved"), served, missing, ""


def main():
    if "--wait" not in sys.argv:
        state, _, missing, why = _check()
        if state == "unserved":
            print("outpost not serving:", ",".join(missing[:6]), file=sys.stderr)
            sys.exit(1)
        if state == "unknown":
            print("outpost readiness UNKNOWN:", why, file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    missing, why = [], ""
    for i in range(120):              # ~10 min ceiling
        state, served, missing, why = _check()
        if state == "ready":
            print(f"outpost ready: all {len(served)} gated hosts served", flush=True)
            sys.exit(0)
        if state == "unknown":
            print(f"outpost readiness unknown ({why}) [{i + 1}/120]", flush=True)
        else:
            waiting = ",".join(missing[:4])
            print(f"outpost syncing ({len(served)} ok, waiting on {len(missing)}: {waiting}…) [{i + 1}/120]", flush=True)
        time.sleep(5)
    if why:
        print("ERROR: outpost readiness could not be determined:", why, file=sys.stderr, flush=True)
        sys.exit(2)
    print("ERROR: outpost did not sync hosts:", ",".join(missing), file=sys.stderr, flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
