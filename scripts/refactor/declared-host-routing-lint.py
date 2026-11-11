#!/usr/bin/env python3
"""declared-host-routing-lint — gate G70: every hostname .env DECLARES has a router that serves it.

    python3 scripts/refactor/declared-host-routing-lint.py [--quiet] [--self-test]

WHY THIS EXISTS. The most expensive failure this deployment has produced does not look like a
failure. Measured 2026-08-24: `platform-base/traefik/config/remote-access.yaml` was never committed
(not gitignored - simply never added, while both its siblings are tracked). Without it, a clean
clone comes up COMPLETELY GREEN: traefik starts, every container reports healthy, the console router
resolves - and then the host answers a bare 404 with `X-Powered-By: authentik`, because authentik's
outpost matches providers by `external_host` and nothing claimed that hostname. Traefik has the
route; the auth layer has never heard of the host. No log line names the cause. That already cost a
day once, which is why that file had a header explaining itself. (The file left on 2026-09-02 with
the window it served; the question it raised did not.)

The shape is general: `.env` DECLARES a hostname, something else is supposed to SERVE it, and when
the second half is missing nothing complains until a human opens a browser. This asks the two halves
whether they agree, at a point where the answer is cheap.

WHO ASKS IT. Only a running stack can answer - the routers are the labels of the containers that
are up - so no static lane runs this. `bbox run` asks at the end of a whole-stack bring-up (--quiet:
it speaks only when a host is unrouted) and `bbox baseline` scores it in P3 with the other live
gates. For six weeks its only caller was `run-gates.py --live`, which nothing invoked: a gate that
is never asked is not a gate.

NOT A SCHEMA CHECK. Nothing here validates that the .env value is well-formed - only that a
hostname someone declared is actually reachable through traefik.

THE INTERNAL-URL TRAP, and why the filter below is narrow. Several `*_BASE_URL` keys are NOT public
hostnames at all: `SUPABASE_BASE_URL=http://kong:8000` names an in-network service and is routed by
nobody, deliberately. A check that flagged those would report a dozen findings where none is real,
and a gate with a dozen false findings is one people learn to ignore (the G67 lesson). So a value is
only considered when it looks like a hostname: no scheme, no path.

A PORT IS THE EDGE'S, NOT THE ROUTER'S. traefik matches Host() against the request's host WITHOUT
its port, and the compiler renders every rule that way (reconcile.traefik_host), so
`console.localhost:8080` is asked about as `console.localhost`. This used to skip a value that
carried a port - and on an office whose edge is not on :80 (every macOS engine: both keys end in
:8080) it therefore compared nothing and printed PASS.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[2]

# THE SCOPE, and it was narrowed by measurement rather than chosen.
#
# The first version of this gate matched every `*_BASE_URL` / `*_EXTERNAL_URL` key. Run live on the
# portable box it produced SEVENTEEN findings - autopilot, browser42, chess, librechat, ollama,
# portainer, rocketchat, and ten more - every one of them an OPTIONAL app that simply is not
# installed on this deployment. Declaring a URL for an app you do not run is not a defect. Worse,
# the one real case it was built for (AUTH_EXTERNAL_URL -> auth3.localhost) was NOT among them,
# because that host IS served: seventeen findings, none of which mattered, and the signal absent.
# That is the shape of a gate people learn to ignore, so the broad version was rejected.
#
# What is left is the chain whose failure is SILENT. CONSOLE_BASE_URL and AUTH_EXTERNAL_URL are
# consumed at login: the console redirects to the auth host, authentik's outpost matches providers
# by external_host, and a hostname with no router yields a bare 404 with `X-Powered-By: authentik`
# while every container reports healthy. Nothing else in .env fails that way - an uninstalled app's
# host just does not resolve, which is obvious the moment anyone tries it.
#
# TO WIDEN THIS SAFELY, scope by ENABLED APPS rather than by key name: `reconcile.py enabled-apps`
# already answers which apps this deployment runs, and a host declared by an enabled app that no
# router serves IS a real finding. That is a bigger change than this gate needs today, and doing it
# by key-suffix instead is what produced the seventeen.
CHECKED_KEYS = ("CONSOLE_BASE_URL", "AUTH_EXTERNAL_URL")
# …and the sign-in host is the one of the identity the edge ASKS. On a forward-auth office (DGO_IDENTITY,
# the product default since 0.3.0) authentik is not running and AUTH_EXTERNAL_URL is read by nothing; sign-in
# is forward-auth's own host, resolved the way its compose resolves it (signin_host). Asking about
# auth.<domain> there failed every clean install of the public copy on a real domain while sign-in worked (a
# client's VPS, 2026-11-08, DGO-1470); the Mac passed only because a file route happens to serve auth.localhost.
# On that office the sign-in half is never skipped: a value it cannot read a host from is a FAIL, or an unrouted
# signin.<domain> would pass on the console's host alone (the second reader of DGO-1470).
SIGNIN_UNREADABLE = "<no host can be read from %s>"


def forward_auth(env):
    return env.get("DGO_IDENTITY", "").strip() == "forward-auth"


def checked_keys(env):
    """The keys consumed at login on THIS office: the console's host, and the identity's sign-in host."""
    if not forward_auth(env):
        return CHECKED_KEYS
    return ("CONSOLE_BASE_URL", "FORWARD_AUTH_EXTERNAL_URL", "FORWARD_AUTH_BASE_URL")


def signin_host(env):
    """(host or None, the key it came from): forward-auth's sign-in host, as its compose resolves it —
    ${FORWARD_AUTH_EXTERNAL_URL:-${AUTH_PROTOCOL:-http}://${FORWARD_AUTH_BASE_URL:-signin.${DEPLOYMENT_DOMAIN:-localhost}}}
    (platform-base/forward-auth/docker-compose.yml). The external URL may carry a port or a path (main.go
    checks only its scheme); the host is what a browser is sent to."""
    ext = env.get("FORWARD_AUTH_EXTERNAL_URL", "").strip()
    if ext:
        try:
            host = urllib.parse.urlsplit(ext).hostname
        except ValueError:
            host = None
        return (host if host and HOSTNAME.match(host) else None), "FORWARD_AUTH_EXTERNAL_URL"
    base, key = env.get("FORWARD_AUTH_BASE_URL", "").strip(), "FORWARD_AUTH_BASE_URL"
    if not base:
        base = "signin." + (env.get("DEPLOYMENT_DOMAIN", "").strip() or "localhost")
        key = "FORWARD_AUTH_BASE_URL (unset: forward-auth's default)"
    m = HOSTNAME.match(base)
    return (m.group(1) if m else None), key

# A hostname - letters/digits/dots/dashes, at least one dot - with or without the edge's port.
# Excludes scheme://... and anything with a path.
HOSTNAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9-]+)(?::\d+)?$")

HOST_RULE = re.compile(r"Host\(`([^`]+)`\)")


def parse_env(text):
    """KEY=VALUE pairs, with ${VAR} (and ${VAR:-default}, ${VAR-default}) expanded from the same file.
    Later definitions win, a quoted value loses its quotes, and an unquoted value loses an inline
    ` # comment` — matching how compose reads it (`DGO_IDENTITY=forward-auth # 0.3.0` is forward-auth)."""
    raw = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
            v = v[1:-1]
        else:
            v = re.sub(r"\s+#.*$", "", v)
        raw[k.strip()] = v

    def expand(v, depth=0):
        if depth > 8:
            return v
        def sub(m):
            name = m.group(1) or m.group(4)
            val = expand(raw.get(name, ""), depth + 1)
            if m.group(2) == ":-" and not val or m.group(2) == "-" and name not in raw:
                return expand(m.group(3), depth + 1)
            return val
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?-)([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)", sub, v)

    return {k: expand(v) for k, v in raw.items()}


def declared_hosts(env):
    """(host -> the key that declared it) for values that are hostnames; a port is dropped. On a
    forward-auth office the sign-in host is always there: the one signin_host resolves, or a marker
    no router serves, so an unreadable value FAILS instead of leaving the console's host to pass alone."""
    out = {}
    fa = forward_auth(env)
    keys = ("CONSOLE_BASE_URL",) if fa else CHECKED_KEYS
    for k, v in sorted(env.items()):
        if k not in keys:
            continue
        m = HOSTNAME.match(v.strip().strip('"').strip("'"))
        if not m:
            continue                      # scheme, path, or empty -> not a routed hostname
        out.setdefault(m.group(1), k)
    if fa:
        host, key = signin_host(env)
        out.setdefault(host or SIGNIN_UNREADABLE % key, key)
    return out


def served_hosts():
    """Hostnames traefik actually serves: docker labels (its docker provider) + the file provider."""
    hosts = set()
    try:
        ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True,
                             timeout=60).stdout.split()
        # ONE inspect for all of them: one per container was 6 s on a 45-container office, and a
        # bring-up asks this every time.
        if ids:
            hosts |= set(HOST_RULE.findall(subprocess.run(
                ["docker", "inspect", "--format", "{{json .Config.Labels}}"] + ids,
                capture_output=True, text=True, timeout=60).stdout))
    except Exception:                                     # noqa: BLE001
        pass
    for f in sorted((REPO / "platform-base" / "traefik" / "config").glob("*.yaml")):
        hosts |= set(HOST_RULE.findall(f.read_text(encoding="utf-8", errors="replace")))
    return hosts


def run(env_text, served):
    """Pure: the comparison, so it is testable without docker."""
    declared = declared_hosts(parse_env(env_text))
    missing = [(h, k) for h, k in sorted(declared.items()) if h not in served]
    return declared, missing


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="say nothing when every host is routed")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()

    envf = REPO / ".env"
    if not envf.is_file():
        print("[declared-host-routing-lint] FAIL - no .env; this gate needs a configured deployment.")
        return 1
    served = served_hosts()
    if not served:
        # An empty scan is a red, never a pass - it means docker was unreachable AND no file
        # provider config was found, so nothing was actually compared.
        print("[declared-host-routing-lint] FAIL - found ZERO served hostnames. Nothing was "
              "compared, which is not a pass.")
        return 1
    env_text = envf.read_text(encoding="utf-8", errors="replace")
    declared, missing = run(env_text, served)
    if not declared:
        # The other empty side: a .env that declares no hostname under these keys was not
        # checked, and saying PASS over it is how a ported office went unasked.
        print("[declared-host-routing-lint] FAIL - .env declares no hostname under %s. Nothing "
              "was compared, which is not a pass." % " / ".join(checked_keys(parse_env(env_text))))
        return 1

    if missing or not a.quiet:
        print("[declared-host-routing-lint] %d declared hostname(s), %d served by traefik"
              % (len(declared), len(served)))
    if missing:
        print("")
        print("[declared-host-routing-lint] FAIL - declared in .env, served by NO router:")
        for h, k in missing:
            print("  %-40s declared by %s" % (h, k))
        print("")
        print("  This is the failure that comes up GREEN: every container healthy, and sign-in")
        print("  lands on a host nobody routes - a bare 404 at the first login. A router's host is")
        print("  not free text: the console's is compiled from CONSOLE_BASE_URL; forward-auth's")
        print("  (DGO_IDENTITY=forward-auth) from FORWARD_AUTH_BASE_URL, or the host of")
        print("  FORWARD_AUTH_EXTERNAL_URL; authentik's follows AUTHENTIK_BASE_URL plus the fixed")
        print("  auth.localhost - so AUTH_EXTERNAL_URL has to name one of those. When it does, the")
        print("  container that carries the router is not running, or is older than the .env it")
        print("  should follow: `bbox status`, then `bbox run`.")
        return 1
    if not a.quiet:
        print("[declared-host-routing-lint] PASS - every declared hostname has a router")
    return 0


def self_test():
    ENV = "\n".join([
        "DEPLOYMENT_DOMAIN=localhost",
        "OTHER_BASE_URL=console3.localhost",
        "CONSOLE_BASE_URL=drive.${DEPLOYMENT_DOMAIN}",
        "SUPABASE_BASE_URL=http://kong:8000",
        "AUTH_EXTERNAL_URL=auth3.localhost",
        "SOME_PORTED_BASE_URL=host.localhost:8080",
        "EMPTY_BASE_URL=",
        "NOT_A_HOST_KEY=console9.localhost",
        "# COMMENTED_BASE_URL=ghost.localhost",
    ])
    served = {"console3.localhost", "drive.localhost"}
    declared, missing = run(ENV, served)
    miss = {h for h, _ in missing}
    # the same office behind an edge that is not on :80: both keys carry the port
    ported, ported_missing = run(
        "CONSOLE_BASE_URL=drive.localhost:8080\nAUTH_EXTERNAL_URL=auth3.localhost:8080", served)
    # ...and values that are not hostnames at all
    urls, _ = run("CONSOLE_BASE_URL=http://drive.localhost\nAUTH_EXTERNAL_URL=auth.localhost/x",
                  served)
    # a forward-auth office (DGO-1470): sign-in is forward-auth's host, and authentik's is read by nothing
    fa = "DGO_IDENTITY=forward-auth\nCONSOLE_BASE_URL=drive.localhost\nAUTH_EXTERNAL_URL=auth3.localhost\n"
    fa_ok, fa_ok_missing = run(fa + "FORWARD_AUTH_BASE_URL=console3.localhost:8080", served)
    _, fa_missing = run(fa + "FORWARD_AUTH_BASE_URL=signin9.localhost", served)
    fa_ext, fa_ext_missing = run(fa + "FORWARD_AUTH_BASE_URL=console3.localhost\n"
                                 "FORWARD_AUTH_EXTERNAL_URL=https://signin7.localhost/", served)
    # the second reader's shapes: none of them may leave the console's host to pass alone
    _, fa_path = run(fa + "FORWARD_AUTH_EXTERNAL_URL=https://signin8.localhost:8443/auth", served)
    _, fa_quoted_empty = run(fa + 'FORWARD_AUTH_EXTERNAL_URL=""\nFORWARD_AUTH_BASE_URL=signin9.localhost', served)
    _, fa_unset = run(fa + "DEPLOYMENT_DOMAIN=x.localhost", served)
    _, fa_unreadable = run(fa + "FORWARD_AUTH_BASE_URL=http://signin.localhost/x", served)
    _, fa_default = run(fa + "FORWARD_AUTH_BASE_URL=signin.${NOPE:-y.localhost}", served)
    _, fa_comment = run("DGO_IDENTITY=forward-auth # 0.3.0\nCONSOLE_BASE_URL=drive.localhost\n"
                        "AUTH_EXTERNAL_URL=auth3.localhost\nFORWARD_AUTH_BASE_URL=console3.localhost", served)

    cases = [
        ("a ported value is asked about by its hostname", sorted(ported),
         ["auth3.localhost", "drive.localhost"]),
        ("...so an unrouted host behind a ported edge IS reported",
         ported_missing, [("auth3.localhost", "AUTH_EXTERNAL_URL")]),
        ("a scheme or a path is not a routed hostname", urls, {}),
        ("${VAR} is expanded from the same file", "drive.localhost" in declared, True),
        ("an internal service URL is NOT a declared host",
         any(h.startswith("http") for h in declared), False),
        ("only in-scope keys are considered", sorted(declared.values()),
         ["AUTH_EXTERNAL_URL", "CONSOLE_BASE_URL"]),
        ("no declared host carries a port", any(":" in h for h in list(declared) + list(ported)),
         False),
        ("an empty value is ignored", "" in declared, False),
        ("an out-of-scope key is ignored (see CHECKED_KEYS)",
         "console9.localhost" in declared or "console3.localhost" in declared, False),
        ("a commented line is ignored", "ghost.localhost" in declared, False),
        ("a served in-scope host is not reported", "drive.localhost" in miss, False),
        ("an UNSERVED declared host IS reported", "auth3.localhost" in miss, True),
        ("the finding names the key that declared it",
         dict(missing).get("auth3.localhost"), "AUTH_EXTERNAL_URL"),
        ("on a forward-auth office an unrouted AUTH_EXTERNAL_URL is not a finding",
         (fa_ok_missing, sorted(fa_ok.values())), ([], ["CONSOLE_BASE_URL", "FORWARD_AUTH_BASE_URL"])),
        ("...and an unrouted FORWARD_AUTH_BASE_URL is", fa_missing,
         [("signin9.localhost", "FORWARD_AUTH_BASE_URL")]),
        ("...and FORWARD_AUTH_EXTERNAL_URL, a URL, wins by its host, as forward-auth's compose has it",
         (sorted(fa_ext), fa_ext_missing),
         (["drive.localhost", "signin7.localhost"], [("signin7.localhost", "FORWARD_AUTH_EXTERNAL_URL")])),
        ("...a port and a path in FORWARD_AUTH_EXTERNAL_URL still give its host", fa_path,
         [("signin8.localhost", "FORWARD_AUTH_EXTERNAL_URL")]),
        ('...FORWARD_AUTH_EXTERNAL_URL="" is unset, as compose reads it', fa_quoted_empty,
         [("signin9.localhost", "FORWARD_AUTH_BASE_URL")]),
        ("...an unset FORWARD_AUTH_BASE_URL is forward-auth's default, signin.<domain>", fa_unset,
         [("signin.x.localhost", "FORWARD_AUTH_BASE_URL (unset: forward-auth's default)")]),
        ("...a value no host can be read from FAILS, never passes on the console alone", fa_unreadable,
         [(SIGNIN_UNREADABLE % "FORWARD_AUTH_BASE_URL", "FORWARD_AUTH_BASE_URL")]),
        ("...${VAR:-default} is expanded", fa_default, [("signin.y.localhost", "FORWARD_AUTH_BASE_URL")]),
        ("...and an inline comment does not hide forward-auth", fa_comment, []),
    ]
    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("")
    print("declared-host-routing-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
