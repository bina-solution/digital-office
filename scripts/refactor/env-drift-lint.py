#!/usr/bin/env python3
"""env-drift-lint — gate G68: anything created BEFORE the current .env runs on stale config.

    python3 scripts/refactor/env-drift-lint.py [--self-test] [--env PATH]

WHY THIS EXISTS. Three separate failures on the portable box on 2026-08-24 were one defect:
state captured when an object is CREATED never reconciles with a .env edited afterwards.

    authentik-worker container created   2026-08-23 09:23
    authentik-postgres created           2026-08-23 09:23
    authentik-server/bootstrap created   2026-08-23 22:23
    .env last modified                   2026-08-24 00:22

  1. THE SSO REDIRECT. Container env is baked at creation. The worker was 13 hours older than the
     rest of the stack and still carried AUTH_EXTERNAL_URL=auth.localhost, AUTH_PROTOCOL=https,
     CONSOLE_BASE_URL=console2.localhost. The worker is the process that APPLIES BLUEPRINTS, and
     the outpost's authentik_host and the console provider's external_host are both derived from
     that env - so bootstrap wrote the right values at boot and the worker's periodic
     reconciliation overwrote them. The deployment worked in the evening and was broken by morning
     with nothing changed.
  2. THE ADMIN PASSWORD. AUTHENTIK_BOOTSTRAP_PASSWORD is consumed ONLY when the initial user is
     created. The postgres volume dates from 09:23, so every later .env edit was silently inert and
     the live password stayed at its 09:23 value while .env moved on.
  3. THE BAKED IMAGE. /app is copied at build time, so repo edits are invisible to the running
     service until a rebuild - the reason a fix can look committed and correct while the running
     system does not have it.

WHY GREP CANNOT FIND ANY OF THEM: every one LOOKS fine. The file on disk is right, the compose file
is right, and the running system disagrees silently, because the wrong value exists only inside a
container or a database. There is no error to search for. The only observable is a TIMESTAMP, which
is exactly what this checks.

WHAT A FINDING MEANS. It is a RISK, not a proven fault: an object older than .env is only actually
broken if the keys that changed are ones it reads. The gate cannot know that without diffing the
env of a container against what it WOULD get today - which it does when it can, to keep the noise
down (see `live_drift`). A container older than .env whose relevant values still match is reported
as a soft finding; one whose values genuinely differ is a hard one.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# EXACT keys, not prefixes, and deliberately few.
#
# The first version watched every *_BASE_URL and reported 40 containers with 14 "drifted" keys
# each. Every one was false: .env stores `any-concurrency.${DEPLOYMENT_DOMAIN}` while the container
# holds the EXPANDED `any-concurrency.localhost` - the same value either side of substitution. A
# gate that reports forty findings where one matters is one people learn to ignore, which is the
# lesson already written into open-destructive-webhook-lint.py.
#
# The second class of false positive is subtler and cannot be fixed by expanding: compose is free
# to set a container's variable from something OTHER than the .env key of the same name.
# incoming-documents carries SUPABASE_BASE_URL=http://kong:8000 (the internal service address)
# while .env's SUPABASE_BASE_URL is the external host. Same name, different meaning, no drift.
#
# So this watches only keys that are (a) passed through from .env unchanged and (b) have actually
# caused a measured incident. Add one only with a reason - and expect noise to be the cost of a
# loose entry.
WATCHED = (
    "AUTH_EXTERNAL_URL",            # 2026-08-24: stale value sent SSO to the wrong authentik
    "AUTH_PROTOCOL",                # 2026-08-24: stale https produced an untrusted-cert wall
    "CONSOLE_BASE_URL",             # 2026-08-24: stale console2 left the console3 router with no provider
    "AUTHENTIK_BOOTSTRAP_PASSWORD", # 2026-08-24: consumed only at user creation; later edits inert
    "AUTHENTIK_BOOTSTRAP_EMAIL",
)


def watched(key):
    return key in WATCHED


def expand(value, env_values, depth=4):
    """Resolve ${VAR} / ${VAR:-default} against .env, the way compose would before baking it in.

    Without this the gate compares a TEMPLATE against a RESOLVED value and calls every container
    drifted. Bounded depth so a self-referential .env cannot spin.
    """
    import re
    if not isinstance(value, str):
        return value
    pat = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
    for _ in range(depth):
        if "$" not in value:
            break
        def sub(m):
            got = env_values.get(m.group(1))
            if got in (None, ""):
                got = m.group(2) if m.group(2) is not None else m.group(0)
            return got
        nxt = pat.sub(sub, value)
        if nxt == value:
            break
        value = nxt
    return value


def analyse(env_mtime, env_values, objects):
    """Pure. objects = [{name, created, kind, env:{...} or None}] -> (hard, soft).

    HARD  = created before .env AND a watched key it carries differs from .env today.
    SOFT  = created before .env, but nothing watched actually differs (or its env is unreadable).
    """
    hard, soft = [], []
    for o in objects:
        if (o.get("created") or 0) >= env_mtime:
            continue
        env = o.get("env")
        if env is None:
            soft.append({**o, "diffs": [], "why": "created before .env; its env could not be read"})
            continue
        diffs = []
        for k, live in sorted(env.items()):
            if not watched(k):
                continue
            want = env_values.get(k)
            if want is not None:
                want = expand(want, env_values)
            if want is not None and want != live:
                diffs.append({"key": k, "running": live, "dotenv": want})
        if diffs:
            hard.append({**o, "diffs": diffs})
        else:
            soft.append({**o, "diffs": [],
                         "why": "created before .env but no watched value differs"})
    return hard, soft


def read_env(path):
    vals, mtime = {}, 0.0
    p = pathlib.Path(path)
    if p.is_file():
        mtime = p.stat().st_mtime
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    return vals, mtime


def docker_objects():
    """Every running container, with its creation time and baked env."""
    import datetime
    out = []
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=60).stdout.split()
    except Exception:                                        # noqa: BLE001
        return out
    for n in names:
        try:
            raw = subprocess.run(
                ["docker", "inspect", n, "--format", "{{.Created}}\t{{json .Config.Env}}"],
                capture_output=True, text=True, timeout=60).stdout.strip()
            created_s, _, env_s = raw.partition("\t")
            ts = datetime.datetime.fromisoformat(created_s.replace("Z", "+00:00")).timestamp()
            env = {}
            for item in json.loads(env_s):
                k, _, v = item.partition("=")
                env[k] = v
            out.append({"name": n, "kind": "container", "created": ts, "env": env})
        except Exception:                                    # noqa: BLE001
            out.append({"name": n, "kind": "container", "created": 0.0, "env": None})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--env", default=str(REPO / ".env"))
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()

    env_values, env_mtime = read_env(a.env)
    if not env_mtime:
        print("[env-drift-lint] FAIL - no .env at %s. An unreadable baseline is not a pass." % a.env)
        return 1
    objs = docker_objects()
    if not objs:
        print("[env-drift-lint] FAIL - inspected ZERO containers. An empty scan is never a pass.")
        return 1

    hard, soft = analyse(env_mtime, env_values, objs)
    import datetime
    stamp = datetime.datetime.fromtimestamp(env_mtime).isoformat(timespec="seconds")
    print("[env-drift-lint] %d container(s); .env last modified %s" % (len(objs), stamp))

    for h in hard:
        print("")
        print("  DRIFT  %s (created %s)" % (
            h["name"], datetime.datetime.fromtimestamp(h["created"]).isoformat(timespec="seconds")))
        for d in h["diffs"]:
            print("     %-24s running=%-28s .env=%s" % (d["key"], d["running"], d["dotenv"]))
    if soft:
        print("")
        print("  older than .env, but nothing watched differs:")
        for s_ in soft:
            print("     %s" % s_["name"])

    if hard:
        print("")
        print("[env-drift-lint] FAIL - %d container(s) are RUNNING ON STALE CONFIG." % len(hard))
        print("  Recreate them so they pick up the current .env; a restart is NOT enough, because")
        print("  env is baked when the container is CREATED.")
        print("  Mind the one that applies blueprints (the authentik WORKER, not the server and not")
        print("  the bootstrap): it re-applies on a schedule and will silently revert a")
        print("  hand-correction made in the database.")
        return 1
    print("")
    print("[env-drift-lint] PASS - nothing is running on config older than .env")
    return 0


def self_test():
    ENV = {"AUTH_EXTERNAL_URL": "auth3.localhost", "AUTH_PROTOCOL": "http",
           "CONSOLE_BASE_URL": "console3.localhost", "UNWATCHED": "new"}

    def obj(name, created, env):
        return {"name": name, "kind": "container", "created": created, "env": env}

    # The real 2026-08-24 case: worker 13h older than .env, still on the defaults.
    worker = obj("authentik-worker", 100, {"AUTH_EXTERNAL_URL": "auth.localhost",
                                           "AUTH_PROTOCOL": "https",
                                           "CONSOLE_BASE_URL": "console2.localhost"})
    fresh = obj("authentik-server", 300, {"AUTH_EXTERNAL_URL": "auth3.localhost",
                                          "AUTH_PROTOCOL": "http"})
    old_ok = obj("redis", 100, {"AUTH_EXTERNAL_URL": "auth3.localhost"})
    old_unwatched = obj("misc", 100, {"UNWATCHED": "old"})
    unreadable = obj("opaque", 100, None)

    ENV_MTIME = 200
    cases = []

    hard, soft = analyse(ENV_MTIME, ENV, [worker])
    cases.append(("the real worker case is caught", (len(hard), len(soft)), (1, 0)))
    cases.append(("and it names every drifted key", len(hard[0]["diffs"]), 3))

    hard, soft = analyse(ENV_MTIME, ENV, [fresh])
    cases.append(("a container NEWER than .env is never a finding", (len(hard), len(soft)), (0, 0)))

    hard, soft = analyse(ENV_MTIME, ENV, [old_ok])
    cases.append(("old but matching is SOFT, not a failure", (len(hard), len(soft)), (0, 1)))

    hard, soft = analyse(ENV_MTIME, ENV, [old_unwatched])
    cases.append(("an unwatched key drifting is not worth failing over",
                  (len(hard), len(soft)), (0, 1)))

    hard, soft = analyse(ENV_MTIME, ENV, [unreadable])
    cases.append(("an unreadable env is a soft finding, not a silent pass",
                  (len(hard), len(soft)), (0, 1)))

    # THE DEFECT THE LIVE RUN EXPOSED: .env keeps templates, containers keep resolved values.
    tmpl_env = {"CONSOLE_BASE_URL": "console.${DEPLOYMENT_DOMAIN}", "DEPLOYMENT_DOMAIN": "localhost"}
    hard, _ = analyse(ENV_MTIME, tmpl_env, [obj("t", 100, {"CONSOLE_BASE_URL": "console.localhost"})])
    cases.append(("an UNEXPANDED .env template is not drift", len(hard), 0))
    hard, _ = analyse(ENV_MTIME, tmpl_env, [obj("t", 100, {"CONSOLE_BASE_URL": "console2.localhost"})])
    cases.append(("but a genuinely different resolved value still is", len(hard), 1))
    dflt = {"CONSOLE_BASE_URL": "${MISSING:-fallback.localhost}"}
    hard, _ = analyse(ENV_MTIME, dflt, [obj("t", 100, {"CONSOLE_BASE_URL": "fallback.localhost"})])
    cases.append(("a :- default resolves rather than mismatching", len(hard), 0))

    # A key absent from .env must not be reported as drift - absence is not disagreement.
    hard, _ = analyse(ENV_MTIME, ENV, [obj("x", 100, {"AUTH_MISSING_KEY": "whatever"})])
    cases.append(("a key absent from .env is not drift", len(hard), 0))

    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("")
    print("env-drift-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
