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
# SIGNED IN, DECLAREDLY (rel-2). A real address sends the browser to the office's sign-in, so a live run
# there measures the login page and not the office (measured 2026-11-04 signed out: `console` 1/3, and
# every flow that needs the rail failed with it). `--auth <file>` (`--storage-state` is the same flag)
# hands the suite a Playwright storage_state, written in one command by
# `python3 scripts/ui-coverage/flow-qa-session.py` — or `./scripts/ui-coverage/flow-qa-session.py`,
# which is executable — from an approval the office ALREADY holds (`.env`'s owner account, POSTed to
# the office's own /login form: this office signs in through `platform-base/forward-auth`, and
# authentik's `/api/v3/flows/executor/…` is a 404 here — measured, not assumed). The file lands in
# `ci-artifacts/`, which git ignores. The flag supplies COOKIES ONLY: no check is skipped, no threshold
# moves, and with no flag the run is the run it always was. An absolute path is rewritten to its place
# under the `/repo` mount below, so the flag means one file on both sides of the container.
#
#   bbox flow-qa console --live=https://console.staging.digital-office.co.il \
#       --auth ci-artifacts/flow-qa/storage-state.json
#
# WHAT A LIVE RUN IS ALLOWED TO BLAME ON THE ADDRESS (rel-2). `--live` aims the suite at the name the
# console answers on INSIDE the office network — `http://console:8000`, a service name with no domain
# under it. Two errors follow from that name and from nothing else: the console derives an app's own
# host from its own (`externalUrl()` nests it, so `*.console:8000` is a name nobody resolves), and an
# app that refuses to be framed names the console's REAL origin in its `frame-ancestors`, which the
# run address is not. `flow-qa.py` decides this itself, from the `--url` it was given (`lan_run()`
# asks the shell's own question, `noNestedHost()`), and it does not hide what it decides: the summary
# carries a line `artifacts: N (lan host …)` naming each one with the browser's reason. So this
# script takes no flag for it and invents no verdict — the suite's exit code IS the verdict, and it has
# three states, because rel-2's criterion is "a green baseline in both offices" and a gate reading one
# number cannot tell a clean run from a run that skipped the errors its own address caused:
#   `exit 0`   a clean baseline: no flow failed and no JS error was raised;
#   `exit 2`   no real failure, but artifacts were skipped and printed — NOT a baseline. A run aimed at
#              a domain-less address can never be a rel-2 baseline, and this is the code that says so;
#   `exit 1`   a failed flow, or a JS error that is not one of those two kinds (and every error at all,
#              on a real address such as https://console.staging.digital-office.co.il).
# There is no --force-green and nothing here that switches a check off.
#
# It does NOT bring the office up — `bbox run` does that — and it writes the suite's screenshots to
# `digital-office/sim/ui-map/` through the bind mount, exactly as a host run would.
#
# Exit code is the suite's own, passed through untouched: 0 a clean baseline, 2 no real failure but
# artifacts were skipped (NOT a baseline — the states above), 1 a failed flow or a real JS error (a
# docker-level failure is 125/126/127 from the engine, and is never reported as a passing suite).
# Beside those three the suite declares 3 (no session was obtained), 4 (a session was handed over and
# the target refused it) and 5 (a flag was given no value). They are NOT verdicts on the office, and
# they are the reason a string `sys.exit(...)` was removed: a string exit is 1, the same number as a
# red run, so "nobody signed the browser in" was unreadable to every gate (measured 2026-11-10).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd -P)"
. "${REPO_ROOT}/scripts/lib.sh"        # say/warn/die, npath, read_env, colors
. "${HERE}/capture-image.sh"           # ensure_capture_image — the ONE declaration of the browser
LOG_TAG=flow-qa                        # …so every line this script prints names itself

# `--live` is sugar for the address the console answers on INSIDE the office network (the same name
# `scripts/remote-ui-capture.py` and `bbox ui-map` use; Traefik is not involved from in here). That
# name has NO domain under it, and the paragraph above says what the suite does about that.
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

# THE SIGNED-IN SESSION, ON BOTH SIDES OF THE MOUNT (rel-2). `--auth <file>` names a storage_state the
# suite reads from INSIDE the browser image, and the repo is bind-mounted at /repo (the `docker run`
# below), so an absolute host path has to become the same file under the mount. A path relative to the
# repo root already means the same thing in both places (`-w /repo`), which is what the producer
# (`scripts/ui-coverage/flow-qa-session.py`) hands out; nothing else about the flag is touched here,
# and this script still invents no verdict: the suite's own exit code IS the verdict.
for i in "${!ARGS[@]}"; do
  case "${ARGS[$i]}" in
    --auth|--storage-state)
      j=$((i + 1))
      if [ "${j}" -lt "${#ARGS[@]}" ]; then
        case "${ARGS[$j]}" in
          "${REPO_ROOT}"/*) ARGS[$j]="/repo/${ARGS[$j]#"${REPO_ROOT}"/}" ;;
        esac
      fi ;;
    --auth=*|--storage-state=*)
      v="${ARGS[$i]#*=}"
      case "${v}" in
        "${REPO_ROOT}"/*) ARGS[$i]="${ARGS[$i]%%=*}=/repo/${v#"${REPO_ROOT}"/}" ;;
      esac ;;
  esac
done

# The offline lane reads the BUILT simulation — a build artifact, not a tracked file — so say what to
# build rather than letting Playwright report a missing page. `node digital-office/sim/build.mjs`
# writes it to `digital-office/platform-sim.html` (`sim/build.mjs`: OUT = <sim>/../platform-sim.html)
# and that is where the suite reads it from (`sim/flow-qa.py`: SIM = <sim>/../platform-sim.html). A
# build made with `SIM_OUT` into the old `sim/` path is accepted too, so neither spelling is a
# false "not built". The message names the path the run actually wants.
if [ "${LIVE}" = 0 ] \
   && [ ! -f "${REPO_ROOT}/digital-office/platform-sim.html" ] \
   && [ ! -f "${REPO_ROOT}/digital-office/sim/platform-sim.html" ]; then
  die "no --live and no built simulation at digital-office/platform-sim.html — build it with
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
# The verdict is the suite's own tally (flows failed, JS errors that are not the address's) — these
# lines only say what each code means, so nobody reads "every flow passed" as "and every error was
# filtered away", and nobody reads a 2 as a crash or as a pass. The suite prints its own
# `artifacts: N (lan host …)` line and its `VERDICT:` line just above this one.
case "${rc}" in
  0) ok "clean baseline: every flow passed and no JS error was raised" ;;
  2) warn "no real failure, but artifacts were skipped and printed — NOT a baseline: a run that is green-with-artifacts cannot stand in for rel-2 (the suite's 'artifacts: N' line says how many, and the address that caused them)" ;;
  # 3/4/5 are the SUITE's own declared codes beside its 0/1/2 (`flow-qa.py` § the exit contract), and
  # they are NOT a verdict on the office: no session was ever handed to the browser. Before 2026-11-10
  # they arrived as a string `sys.exit(...)`, which is 1 — "a flow failed" — so a gate could not tell a
  # missing sign-in from a regression. `rc` is still passed through untouched below.
  3) warn "NO SESSION: no storage_state was obtained, so the suite had nothing to sign in with (mint it: 'bbox flow-qa-session') — this is not a verdict on the office" ;;
  4) warn "SIGNED IN, TARGET REFUSED: the target would not take the session it was given — this is not a verdict on the office" ;;
  5) warn "BAD INVOCATION: a flag was given with no value — nothing ran, and this is not a verdict on the office" ;;
  *) warn "exit ${rc} (a failed flow, a JS error that is not the address's, or an engine failure)" ;;
esac
exit "${rc}"
