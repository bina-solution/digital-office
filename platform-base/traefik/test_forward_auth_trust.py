"""אמון כותרת — the identity headers the office hands an app are not accepted from a client.

SECTION 9 OF THE RELEASE (rel-3, apps/project-pln/plans/dgo-dev.yaml): every security claim is a
test, and this is the first one — "a request that arrives from outside carrying a forged
`X-authentik-*` is not a signed-in user".

WHERE THE CLAIM LIVES. `platform-base/traefik/config/authentik-forwardauth.yaml` is the dynamic
configuration of the edge (traefik 3's file provider, mounted at /etc/traefik and rendered there).
In the `DGO_IDENTITY=forward-auth` window the middleware is `forwardAuth` with
`trustForwardHeader: false` and the five identity names in `authResponseHeaders`; traefik's contract
for that middleware is that each name listed there is taken from the AUTH SERVICE's response onto
the forwarded request — never from the request the client sent. The identity service
(`platform-base/forward-auth`) answers 200 plus those five headers only out of a session it read
itself, and 302 to the sign-in page otherwise; it has one other way to say yes, the phone core's
HMAC signature (`X-DGO-Edge-*`), and a signature it cannot check is no identity at all.

FOUR THINGS ARE MEASURED, AND THE THIRD IS WHAT KEEPS THE OTHERS FROM BEING DECORATION:

  1. middleware   the file the edge actually loads carries `forwardAuth`, `trustForwardHeader:
                  false`, and the identity names in `authResponseHeaders`;
  2. through the  a forged `X-authentik-*` sent to a gated host through the edge serves NO identity
     edge         (the browser is sent to sign in);
  3. directly to  THE SAME forged request sent straight at the app — no middleware in the path —
     the app      IS taken as that user. That is the unprotected state, and it is exactly what check
                  2 must catch: the app trusts the header, the edge is what makes trusting it safe.
                  If this check stops holding, check 2 has measured nothing and this test fails.
  4. the auth     the identity service asked the way the edge asks it, with the same forged headers
     service      and no session, answers from its own state: a challenge, never the forged user.

Run: `python3 platform-base/traefik/test_forward_auth_trust.py` (also discovered and run by gate
G72, `scripts/refactor/plane-tests-lint.py`). On a machine that is not on an office's network the
live names do not resolve, and the gate reads that as NOT RUN rather than as a pass.
"""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: What the client claims to be. A value that names nobody on any office, so "it came back" can only
#: mean a header was believed.
FORGED = {
    "X-authentik-username": "forged-trust-probe",
    "X-authentik-email": "forged@trust-probe.invalid",
    "X-authentik-name": "Forged Probe",
    "X-authentik-groups": "authentik Admins",
    "X-authentik-uid": "forged-uid",
    # the phone core's signature family: forged values are not a signature
    "X-DGO-Edge-At": "1700000000",
    "X-DGO-Edge-Nonce": "forged-forged-forged",
    "X-DGO-Edge-Sig": "00" * 32,
    # the link's door writes this; a client writing it must never be an office
    "X-DGO-Office": "forged",
    "X-DGO-From": "forged",
}

IDENTITY_NAMES = ["X-authentik-username", "X-authentik-groups", "X-authentik-email",
                  "X-authentik-name", "X-authentik-uid"]
EDGE_NAMES = ["X-DGO-Edge-At", "X-DGO-Edge-Nonce", "X-DGO-Edge-Sig"]

#: The gated host probed through the edge, and the app it routes to (the console is the one gated
#: surface every office has).
HOSTS = ["console.localhost"]
APP_PORTS = [8000]


def sh(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def containers() -> list[str]:
    return [n.strip() for n in sh("docker", "ps", "--format", "{{.Names}}").splitlines() if n.strip()]


def pick(names: list[str], prefix: str) -> str | None:
    for n in names:
        if n.split("-")[0] == prefix:
            return n
    return None


def get(host: str, port: int, path: str, headers: dict[str, str], timeout: float = 8.0):
    """(status, body) with the headers asked for, verbatim: no redirect followed, no cookie kept."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers)
        r = conn.getresponse()
        return r.status, r.read(4096)
    finally:
        conn.close()


def identity_in(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {}


def forged_value_served(body: bytes) -> list[str]:
    """Which forged values the app said back. Empty means: it did not believe the headers."""
    text = body.decode("utf-8", "replace")
    return [v for v in (FORGED["X-authentik-username"], FORGED["X-authentik-email"],
                        FORGED["X-authentik-name"]) if v in text]


# ── 1. the configuration the edge really loads ───────────────────────────────────────────────────


def middleware_source(traefik: str | None) -> tuple[str, str]:
    """(the config text, where it came from) — from inside the running edge when there is one."""
    live = "/etc/traefik/authentik-forwardauth.yaml"
    if traefik:
        text = sh("docker", "exec", traefik, "cat", live)
        if text.strip():
            return text, f"{traefik}:{live}"
    repo = REPO / "platform-base/traefik/config/authentik-forwardauth.yaml"
    return repo.read_text(encoding="utf-8"), f"{repo.relative_to(REPO)} (the file the edge mounts)"


def identity_mode(traefik: str | None) -> str:
    """Which branch of the middleware the edge is serving: the office's `DGO_IDENTITY`."""
    if traefik:
        env = sh("docker", "inspect", traefik, "--format", "{{range .Config.Env}}{{println .}}{{end}}")
        for line in env.splitlines():
            if line.startswith("DGO_IDENTITY="):
                return line.split("=", 1)[1].strip()
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DGO_IDENTITY="):
                return line.split("=", 1)[1].strip()
    return ""


def check_middleware(traefik: str | None) -> str:
    text, where = middleware_source(traefik)
    mode = identity_mode(traefik)
    # The branch that is served: the forward-auth one only in its window, else the authentik one.
    branch = "forward-auth" if mode == "forward-auth" else "authentik"
    # The blocks in the file, in order: sso-off (headers), forward-auth, authentik.
    blocks = [b for b in text.split("      forwardAuth:")[1:]]
    if branch == "forward-auth":
        if not blocks:
            raise AssertionError(f"{where}: no forwardAuth block at all")
        block = blocks[0]
        if "trustForwardHeader: false" not in block:
            raise AssertionError(f"{where}: forwardAuth without `trustForwardHeader: false` — the "
                                 f"client's own X-Forwarded-* would reach the identity service")
        address = next((ln.strip() for ln in block.splitlines() if "address:" in ln), "?")
        if "forward-auth:9078" not in address:
            raise AssertionError(f"{where}: forwardAuth asks {address}, not the office's identity "
                                 f"service (forward-auth:9078)")
    else:
        if len(blocks) < 2:
            raise AssertionError(f"{where}: the authentik branch is missing")
        block = blocks[1]
    listed = [ln.strip().lstrip("- ").strip() for ln in block.splitlines()
              if ln.strip().startswith("- X-")]
    missing = [n for n in IDENTITY_NAMES if n not in listed]
    if missing:
        raise AssertionError(f"{where}: the middleware does not replace {missing} — a client's value "
                             f"for a name traefik does not take from the auth response reaches the app")
    if branch == "forward-auth":
        unhandled = [n for n in EDGE_NAMES if n not in listed]
        if unhandled:
            raise AssertionError(f"{where}: {unhandled} is not replaced, so a forged signature "
                                 f"header would reach the app")
    return (f"{branch}: {where} lists all {len(IDENTITY_NAMES)} identity names in "
            f"authResponseHeaders, trustForwardHeader "
            f"{'false' if branch == 'forward-auth' else 'true (the authentik outpost, unchanged)'}")


# ── 2/3. the same forged request, with and without the edge in the path ─────────────────────────


def served_identity(url: tuple[str, int], host: str | None) -> tuple[int, list[str]]:
    headers = dict(FORGED)
    if host:
        headers["Host"] = host
    status, body = get(url[0], url[1], "/api/me", headers)
    return status, forged_value_served(body)


def refusal(url: tuple[str, int], host: str | None, what: str) -> str:
    """The claim: this request is not a signed-in user. Raised as an AssertionError when it is."""
    status, served = served_identity(url, host)
    if status in (301, 302, 303, 307, 308):
        return f"{what}: {status} to the sign-in page, no identity served"
    if status == 200 and served:
        raise AssertionError(f"{what}: HTTP 200 and the app answered with the forged "
                             f"{', '.join(served)} — a client's header was believed")
    if status == 200:
        return f"{what}: 200 without the forged identity (another identity answered, not the client's)"
    return f"{what}: {status}, no identity served"


def check_the_app_trusts_the_header(app: tuple[str, int]) -> str:
    """Non-vacuity: the very request the edge refuses is believed by the app when the edge is out of
    the way. Both halves of check 2 are only meaningful if this stays true."""
    status, served = served_identity(app, None)
    if status != 200 or not served:
        raise AssertionError(
            f"the app at {app[0]}:{app[1]} did not serve the forged identity directly "
            f"(HTTP {status}), so this test measured nothing about the edge: either the app no longer "
            f"reads these headers or the probe went somewhere else")
    return f"direct to {app[0]}:{app[1]} — 200 and {served[0]!r} served: the header IS the identity " \
           f"channel, and the edge is what makes trusting it safe"


# ── 4. the identity service, asked the way the edge asks it ─────────────────────────────────────


def check_auth_service() -> str:
    headers = {k: v for k, v in FORGED.items() if k.startswith("X-authentik-")}
    headers.update({"X-Forwarded-Host": HOSTS[0], "X-Forwarded-Uri": "/api/me",
                    "X-Forwarded-Method": "GET", "X-Forwarded-Proto": "http"})
    status, body = get("forward-auth", 9078, "/auth/traefik", headers)
    if status == 200:
        raise AssertionError("the identity service answered 200 to a request with no session but a "
                             "forged X-authentik-username: it is echoing a client's claim")
    if forged_value_served(body):
        raise AssertionError("the identity service's answer carries the forged identity")
    return f"forward-auth:9078 — {status} for a forged identity with no session (challenge, not a yes)"


# ── the run ─────────────────────────────────────────────────────────────────────────────────────


def main() -> int:
    names = containers()
    traefik = pick(names, "traefik")
    console = pick(names, "console")
    if not traefik:
        print("NOT RUN: no running edge (a container named traefik*) is visible from here")
        return 1
    try:
        print(f"PASS middleware    {check_middleware(traefik)}")

        edge = (traefik, 80)
        print(f"PASS through-edge  {refusal(edge, HOSTS[0], f'{HOSTS[0]} via {traefik}')}")

        if not console:
            raise AssertionError("no running console container: the unprotected side of the "
                                 "comparison cannot be measured")
        app = (console, APP_PORTS[0])
        print(f"PASS app-trusts   {check_the_app_trusts_the_header(app)}")

        # The sensitivity of check 2, mechanically: the same refusal, aimed at the unprotected app,
        # must FAIL. A check that cannot fail is not evidence.
        try:
            refusal(app, None, "unprotected")
        except AssertionError:
            print(f"PASS non-vacuous   the same refusal FAILS at {console}:{APP_PORTS[0]} with no "
                  f"middleware in the path — it detects the unprotected state")
        else:
            raise AssertionError("the refusal also passed against the unprotected app: it measures "
                                 "nothing")

        print(f"PASS auth-service  {check_auth_service()}")
    except AssertionError as exc:
        print(f"FAIL trust         {exc}")
        return 1
    except OSError as exc:
        # No office network here (a CI box, a clone): the live names do not resolve, and gate G72
        # reads that as NOT RUN.
        print(f"NOT RUN: the live office is not reachable from here: {exc}")
        return 1
    print("PASS forward-auth-trust: identity headers are the edge's to write, not a client's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
