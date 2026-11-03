#!/usr/bin/env bash
# flow-qa.sh — run the office's flow suite (`digital-office/sim/flow-qa.py`) where a BROWSER exists.
#
# WHY THIS FILE EXISTS (rel-2). The flow suite drives every flow a person can start and asserts its
# effect, and it takes `--url <base>` to aim the same assertions at a RUNNING office. Its runner was
# never declared: the suite imports `playwright.sync_api`, and on a fresh clone no host has that —
# the suite died at import with `ModuleNotFoundError: playwright`, which reads as a broken test
# rather than as a missing dependency. `scripts/ui-coverage/route-runtime-qa.py` had the same shape
# and answered it by hand, in its own docstring, with a `docker run` line.
#
# WHAT KIND OF DECLARATION THIS IS. `digital-office/` is the dev-only design/spec workbench: no
# app.json, no compose service, no bbox verbs, never shipped, never run by CI (CLAUDE.md § "What
# digital-office/ is (and is not)"). So the suite itself declares nothing. What it NEEDS is a
# browser, and the office already declares exactly one place for that: `ui-capture`, built from
# `scripts/ui-coverage/Dockerfile` (`pip install playwright`, apt chromium, UI_CHROME_BIN). This
# script is the missing half — the invocation — and it is declared where the office's other verbs
# are: `bbox flow-qa`. Fresh clone → `bbox flow-qa console --live`, no hand step.
#
# USAGE
#   bbox flow-qa                          # every suite, against the offline simulation
#   bbox flow-qa console                  # one suite
#   bbox flow-qa console --live           # …against the office running here (http://console:8000)
#   bbox flow-qa console --live=http://console:8000
#   bbox flow-qa windows --mobile         # any flag the suite itself takes, passed through untouched
#
# It does NOT bring the office up — `bbox run` does that — and it writes the suite's screenshots to
# `digital-office/sim/ui-map/` through the bind mount, exactly as a host run would.
#
# Exit code is the suite's own: non-zero on a failed flow or any JS error (a docker-level failure is
# 125/126/127 from the engine, and is never reported as a passing suite).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd -P)"
. "${REPO_ROOT}/scripts/lib.sh"        # say/warn/die, npath, read_env, colors
. "${HERE}/capture-image.sh"           # ensure_capture_image — the ONE declaration of the browser
LOG_TAG=flow-qa                        # …so every line this script prints names itself

# `--live` is sugar for the address the console answers on INSIDE the office network (the same name
# `scripts/remote-ui-capture.py` and `bbox ui-map` use; Traefik is not involved from in here).
CONSOLE_URL="${FLOW_QA_URL:-http://console:8000}"
LIVE=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --live)     ARGS+=(--url "${CONSOLE_URL}"); LIVE=1 ;;
    --live=*)   ARGS+=(--url "${a#*=}"); LIVE=1 ;;
    --url|--url=*) ARGS+=("$a"); LIVE=1 ;;
    *)          ARGS+=("$a") ;;
  esac
done

TARGET="the offline simulation"
if [ "${#ARGS[@]}" -gt 0 ]; then
  for i in "${!ARGS[@]}"; do
    case "${ARGS[$i]}" in
      --url)  TARGET="${ARGS[$((i + 1))]:-?}" ;;
      --url=*) TARGET="${ARGS[$i]#*=}" ;;
    esac
  done
fi

# The offline lane reads the BUILT simulation (sim/platform-sim.html) — a build artifact, not a
# tracked file — so say what to build rather than letting Playwright report a missing page.
if [ "${LIVE}" = 0 ] && [ ! -f "${REPO_ROOT}/digital-office/sim/platform-sim.html" ]; then
  die "no --live and no built simulation at digital-office/sim/platform-sim.html — build it with
  'node digital-office/sim/build.mjs', or aim this at the office running here: 'bbox flow-qa <suite…> --live'"
fi

ensure_capture_image "flow-qa" || die "the browser image could not be built (see above)"

# The office's network is where the console answers by name (`http://console:8000`). The offline lane
# needs NO network — the simulation is one file on disk, read over file:// — so the office is joined
# only when it is there, and a fresh clone with no stack still runs the sim. A live run without that
# network is not a failure to guess at: it is an office that is not up.
NET_ARGS=()
if docker network inspect traefik-network >/dev/null 2>&1; then
  NET_ARGS=(--network traefik-network)
elif [ "${LIVE}" = 1 ]; then
  die "no traefik-network on this engine — the office is not running here. Bring it up first: ./bbox run"
fi

say "${TARGET}  (image=${IMAGE}; suite args: ${ARGS[*]:-all})"

# The suite reads the checkout (it imports scripts/ui-coverage/drawn.py, the office's one "is this
# screen drawn" rule) and writes its shots into it, so the repo is bind-mounted at the same layout.
# --shm-size: Chromium's own requirement — the default 64 MB crashes tabs during a long suite.
docker run --rm \
  ${NET_ARGS[@]+"${NET_ARGS[@]}"} \
  --shm-size=512m \
  -v "$(npath "${REPO_ROOT}"):/repo" -w /repo \
  -e UI_OWN_BROWSER=1 -e UI_CHROME_BIN=/usr/bin/chromium \
  --entrypoint python3 "${IMAGE}" -u digital-office/sim/flow-qa.py ${ARGS[@]+"${ARGS[@]}"}
rc=$?
[ "${rc}" = 0 ] && ok "every flow passed" || warn "exit ${rc} (a failed flow, a JS error, or an engine failure)"
exit "${rc}"
