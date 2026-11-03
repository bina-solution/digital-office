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
PLN_SELF="$(read_env_value DGO_OFFICE_ID)"
PLN_OURS=""                      # 1 on one of THIS herd's own offices (a client's office runs the same checkout)
#: Did the door that discovery named FAIL to answer? That is not the same fact as a PLN_API left empty
#: (there is nowhere to go at all): here the office knows where its Plane is and cannot reach it. A write
#: is kept in the outbox in both cases; the difference is what the person is told (DGO-1100, any-201).
PLN_DEAD=0
# An address given in the ENVIRONMENT wins over discovery (`PLANE_API_URL` is also the name the applier
# reads): a drill that points this office at a dead door, or a proxy between the office and Plane, is not
# overruled by where the registry says the app lives. Nothing in .env is read for this.
if [ -n "${PLANE_API_URL:-}" ]; then
  PLN_API="${PLANE_API_URL}"
elif ! running "project-pln-${DN}"; then
  # More than one linked office can publish a Plane — ours, and a client's office we installed and
  # linked. The herd names the one that runs OURS (apps/computers/herd.yaml, `apps: project-pln`), and on
  # the herd's own offices it is the only answer, even while it is mid-update; scripts/herd_home.py
  # decides, for this hook and for Meet's (MEET_PLANE_API_URL), and holds what was measured.
  PLN_WHERE="$(python3 "${REPO_ROOT}/scripts/herd_home.py" project-pln "${PLN_SELF}")"
  [ "${PLN_WHERE%% *}" = 1 ] && PLN_OURS=1
  PLN_API="${PLN_WHERE#* }"
  [ "${PLN_API}" != "${PLN_WHERE}" ] || PLN_API=""
  # `return`, never `exit`: the hooks SOURCE this file, and a write with no path is now KEPT (outbox.py),
  # not fatal — so the caller must be able to tell "no path" from the end of its own script (DGO-1100).
  [ -n "${PLN_API}" ] || { say "${cy}[project-pln] the app does not run on this office, and no linked office's Plane may be used from here${c0}"; return 1; }
  PLN_IN=connections
  say "[project-pln] the app runs on a linked office — reaching it at ${PLN_API}"
fi

# AWAY FROM HOME (DGO-1092). Pairs are two by two: a laptop out of the house has no live pair to the office
# that runs Plane, but the herd's hub (apps/computers/herd.yaml `hub:`) keeps one. So the link's door is
# asked first, and when nothing answers — no answer at all, or the link proxy's 502/503/504 for a dead
# tunnel — PLN_HUB names the hub, and the hook re-runs the same verb THERE (`bbox via`, scripts/via.py).
# A command that came in through `via` never goes on to a second hop (BBOX_VIA), so the hub, whose own
# pair may be the dead one too, answers for itself instead of bouncing the request back.
PLN_HUB=""
if [ -n "${PLN_API}" ] && [ -z "${BBOX_VIA:-}" ]; then
  if ! dcx exec -T "${PLN_IN}" python3 -c '
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen(sys.argv[1] + "/", timeout=8)
except urllib.error.HTTPError as e:
    sys.exit(1 if e.code in (502, 503, 504) else 0)
except Exception:
    sys.exit(1)
' "${PLN_API}" >/dev/null 2>&1; then
    PLN_HUB="$(sed -n 's/^hub:[[:space:]]*\([A-Za-z0-9_-]*\).*/\1/p' "${REPO_ROOT}/apps/computers/herd.yaml" 2>/dev/null | head -1)"
    PLN_TARGET="$(printf '%s' "${PLN_API}" | sed -E 's#^https?://[^.]+\.([^:/]+).*#\1#')"
    # Not when the hub is the office that cannot reach Plane (the hub itself), and not on an office that is
    # not one of this herd's (a client's office runs the same checkout and must never fall back to OUR hub).
    [ "${PLN_HUB}" = "${PLN_TARGET}" ] || [ "${PLN_HUB}" = "${PLN_SELF:-local}" ] && PLN_HUB=""
    if [ -n "${PLN_SELF}" ] && [ -z "${PLN_OURS}" ]; then
      PLN_HUB=""
    fi
    if [ -n "${PLN_HUB}" ]; then
      say "${cy}[project-pln] ${PLN_TARGET} does not answer through its own pair — going through the herd's hub, ${PLN_HUB}${c0}"
    fi
    # No hub to ask either: the office is offline, and the caller keeps the write (outbox.py). An address
    # given explicitly in the environment is the WHOLE path decision — no hub behind it (above).
    [ -n "${PLANE_API_URL:-}" ] && PLN_HUB=""
    [ -n "${PLN_HUB}" ] || PLN_DEAD=1
  fi
fi
