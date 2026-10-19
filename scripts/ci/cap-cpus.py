#!/usr/bin/env python3
"""Cap every `cpus:` limit in the compose files to what this runner actually has.

    python3 scripts/ci/cap-cpus.py [--max 2]

`docker compose up` ENFORCES `deploy.resources.limits.cpus` and refuses to start a service that
asks for more CPU than the host has — "range of CPUs is from 0.01 to 2.00". The committed values
are sized for the production VPS, so on a 2-vCPU CI runner several services abort. This rewrites
them in place for the duration of the job; the committed values stay correct for prod.

ONE implementation. This existed as three inline copies — in ci-verify.yml, indox-e2e.yml and
ui-map.yml — and they had already drifted: different comments, different output messages, and
ui-map's copy carried a note that the OTHER two never got, recording that the pre-refactor
`production/` + `development/` globs had silently matched nothing after the layout changed, so the
cap was a no-op and prod-sized cpus reached the runner anyway. Three copies of a fix means the
lesson is learned in one of them and lost in the others.

Overlaps with `platform/profiles/perf-profiles.yml` (the `ci-small` profile sizes the same knobs
through PERFORMANCE_PROFILE). Sizing the runner ought to be that mechanism alone — recorded in the
release plan rather than fixed here, because it changes what CI builds and needs its own proof.
"""
import argparse
import glob
import re
import sys

#: Post-refactor layout: every service lives in apps/ (layer 3) or platform-base/ (layers 1-2).
GLOBS = ("apps/**/docker-compose.yml", "platform-base/**/docker-compose.yml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=float, default=2.0,
                    help="ceiling in vCPUs (default 2, the CI runner)")
    a = ap.parse_args()

    def cap(m):
        try:
            v = float(m.group(1))
        except ValueError:
            return m.group(0)
        return "cpus: '%s'" % ("%g" % min(v, a.max))

    files = [f for g in GLOBS for f in glob.glob(g, recursive=True)]
    if not files:
        # The exact failure the ui-map copy recorded: globs matching nothing looked like success.
        print("cap-cpus: FAIL — no compose files matched; the layout moved and this would be a "
              "silent no-op, letting prod-sized cpus reach the runner.", file=sys.stderr)
        return 1

    changed = 0
    for f in files:
        try:
            s = open(f, encoding="utf-8").read()
        except OSError:
            continue
        s2 = re.sub(r"cpus: '([0-9.]+)'", cap, s)
        if s2 != s:
            open(f, "w", encoding="utf-8", newline="\n").write(s2)
            changed += 1
    print(f"cap-cpus: capped to {a.max:g} vCPU in {changed} of {len(files)} compose file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
