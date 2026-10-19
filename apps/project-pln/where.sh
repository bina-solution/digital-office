# where.sh — WHERE the office's Plane is, for the hooks that talk to it. Sourced; sets PLN_IN (the
# service whose container runs the applier) and PLN_API (the address the applier is told; empty =
# its own default, the container's loopback).
#
# Here, in its own container. Or — on an office the app moved away from — behind the link: the
# compiled registry names the office that runs it (`.generated/registry/remote.<office>.<alias>.json`
# with `app: project-pln`), and the same applier then runs in the credential plane's container, which
# every office has and which sits on the office network where the link's names resolve. Measured
# 2026-10-06 from the MacBook, the day after the app moved to hp-laptop: its agent's own key listed
# hp-laptop's work items through `http://plane.hp-laptop:9004` — but only by hand, because these
# hooks exec'd into a local container that no longer existed there.
PLN_IN=project-pln
PLN_API=""
if ! running "project-pln-${DN}"; then
  PLN_API="$(python3 - "${REPO_ROOT}/.generated/registry" <<'PY'
import glob, json, sys
for f in sorted(glob.glob(sys.argv[1] + "/remote.*.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if d.get("app") == "project-pln":
        office = f.replace("\\", "/").rsplit("/remote.", 1)[1].split(".", 1)[0]
        print("http://%s.%s:%s" % (d.get("alias"), office, d.get("link_port") or d.get("port")))
        break
PY
)"
  [ -n "${PLN_API}" ] || { say "${cr}[project-pln] the app does not run on this office, and no linked office publishes it${c0}"; exit 1; }
  PLN_IN=connections
  say "[project-pln] the app runs on a linked office — reaching it at ${PLN_API}"
fi
