#!/usr/bin/env bash
# route-runtime-qa.sh — the ONE command for the runtime half of G83 (`bbox route-runtime-qa`).
#
# WHY THIS FILE EXISTS (rel-2). `route-runtime-qa.py` opens every view the inventory declares in a
# real browser and requires it to be DRAWN at its own address. A view whose route carries a
# parameter (`{folder}`, `{id}`, `{site}`, `:repo`, `:type/:name`) cannot be opened blind: the values
# come from `resolve_params.py`, which reads them out of each app's own live API on the HOST (it
# talks to the containers through `docker exec`, which is why it cannot run inside the browser
# container). The driver's default params file, `data/browser42/ui-params.json`, is GITIGNORED, and
# nothing in the QA path ever wrote it — `ui-map.sh` does resolve, but into `data/ui-map/`, and only
# as a step of the pixel-capture pipeline. So on a fresh clone (and in CI) every parameterised view
# was reported SKIPPED and rel-2's acceptance — "zero routes skipped on a missing parameter" — was met
# only on the office where that file had been produced by hand.
#
# WHAT THIS IS: the missing first half, declared where the office's other verbs are.
#   1. RESOLVE — `resolve_params.py` on the host, when the params file is absent or empty (or with
#      `--resolve`, or always with UI_QA_RESOLVE=always). A resolve that fails WARNS and continues:
#      the QA then runs against whatever is there and reports the skips itself, so a failed resolve
#      can never read as a full run.
#   2. DRIVE — the same `docker run` the driver's docstring names: the one image on this engine that
#      carries Playwright + Chromium, attached to the office network, with the checkout mounted.
#
# It does NOT bring the office up (`bbox run` does that) and it does NOT resolve when the file is
# already there — a QA run is a measurement, not a seeder. The one side effect of a resolve is
# `resolve_params.py`'s own, documented there: on an INDOX `test` instance whose repo is empty it seeds the demo
# documents, exactly as `bbox ui-map` already does. `UI_QA_RESOLVE=never` turns the resolve off.
#
# USAGE
#   bash scripts/ui-coverage/route-runtime-qa.sh            # the whole office, EXIT 0 = every view drawn
#   bash scripts/ui-coverage/route-runtime-qa.sh --resolve   # re-resolve the ids first (a changed app)
#   bash scripts/ui-coverage/route-runtime-qa.sh --only sites --url http://console:8000
# Any other flag goes to `route-runtime-qa.py` untouched (`--only`, `--json`, `--params`, `--shot-dir`).
#
# READS:
#   UI_QA_IMAGE    the browser image (default: the office's own `sites-render` image, which carries
#                  Playwright + Chromium; else the declared `ui-capture`, see capture-image.sh)
#   UI_QA_PARAMS   the params file (default data/browser42/ui-params.json — the driver's own default)
#   UI_QA_RESOLVE  missing (default) | always | never
#
# THE DENOMINATOR IS THE WHOLE OFFICE (rel-2, phase 2). The driver used to skip every view with no
# proxy — 16 of this office's own screens (console ×9, machine ×4, cad, meet, project-pln) — and
# printed «72 declared view(s) … 72 open and drawn» while the inventory declared 95: a perfect guide
# to a denominator that was not the office. Those views are now opened at their OWN address (the
# app's own console module url from its app.json, or `--hosts NAME=URL,…`), and the run prints
# DECLARED / MEASURED / EXCLUDED / FAILED, exiting non-zero for any first_party view that was neither
# drawn nor excluded by name. `third_party` stays outside the denominator and is printed by name,
# with its reason.
#
# EXIT is the driver's own: non-zero when any declared view fails — it did not open at its address,
# the shell's address does not carry it back, it was NOT DRAWN (still «טוען…»/a skeleton/still
# growing at the cap: rel-2, the finding that `drawn` was measured but left out of the verdict), or
# ITS OWN ADDRESS THREW a JS runtime error (rel-2ג, the same finding about `js_errors`: 39 React
# errors used to print `FAILED 0` and exit 0; a screen named in runtime-error-exclusions.yaml with a
# `why` and a `root` is the one way such an error stops failing the run) — 2
# when the inventory itself has drifted. A drawn-but-SLOW screen (over drawn.BUDGET_MS) is printed
# with its address and time and listed in the JSON's `slow`, and does NOT fail the run: the
# acceptance is «נצבע», not «נצבע מהר». An engine-level failure (125/126/127) is never a passing run.
# `--self-test` (passed straight to the driver) proves the verdict bites: a page that never stops
# loading must FAIL the run, and so must a screen that is drawn and throws.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd -P)"
. "${REPO_ROOT}/scripts/lib.sh"        # say/warn/die/ok, read_env, npath, cn, DN
LOG_TAG=route-runtime-qa
cd "${REPO_ROOT}"

# ── arguments: `--resolve`/`--no-resolve` are this script's, everything else is the driver's ─────
RESOLVE="${UI_QA_RESOLVE:-missing}"
PARAMS="${UI_QA_PARAMS:-data/browser42/ui-params.json}"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --resolve)    RESOLVE=always; shift ;;
    --no-resolve) RESOLVE=never;  shift ;;
    --params)     PARAMS="${2:-}"; ARGS+=("$1" "${2:-}"); shift 2 ;;
    --params=*)   PARAMS="${1#*=}"; ARGS+=("$1"); shift ;;
    *)            ARGS+=("$1"); shift ;;
  esac
done

# ── 1. the parameters, when they are not here ────────────────────────────────────────────────────
# "There" means a file with at least one resolved value: `resolve_params.py` writes the file even
# when it resolved nothing (`{}` — a stack that is not up), and an empty map is the same measurement
# as no file at all, so it is re-resolved rather than trusted.
have_params() { [ -s "${PARAMS}" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d else 1)' "${PARAMS}" 2>/dev/null; }
if [ "${RESOLVE}" = never ]; then
  say "params: ${PARAMS} — resolve skipped (UI_QA_RESOLVE=never)"
elif [ "${RESOLVE}" = always ] || ! have_params; then
  if [ -f "${PARAMS}" ]; then why="re-resolving (asked)"; else why="not here — a fresh clone has no data/browser42"; fi
  say "params: ${PARAMS} ${why}"
  # Host-side on purpose: it reads each app's own API through `docker exec` (resolve_params.py's
  # header). A failure is stated and NOT fatal — the driver reports the skips it causes.
  python3 "$(npath "${HERE}/resolve_params.py")" --data "$(npath "$(dirname "${PARAMS}")")" \
    || warn "param resolve reported issues — continuing with what is in ${PARAMS}"
  if [ -s "${PARAMS}" ]; then
    say "params: $(python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
print(sum(len(v) if isinstance(v, dict) else 1 for v in d.values()), "value(s) in", len(d), "entry(ies)")' "${PARAMS}" 2>/dev/null || echo 'written')"
  else
    warn "${PARAMS} was not written — parameterised views will be reported SKIPPED"
  fi
else
  say "params: ${PARAMS} (already resolved)"
fi

# ── 2. the browser image: the office's own, never a host install ─────────────────────────────────
IMAGE="${UI_QA_IMAGE:-}"
if [ -z "${IMAGE}" ]; then
  # The office already runs an image that carries Playwright + Chromium (its renderer), so it is
  # preferred: it is on the engine of every office that is actually up, with no build at all.
  qa_container="$(cn sites-render)"
  [ -n "${qa_container}" ] && IMAGE="$(docker inspect --format '{{.Config.Image}}' "${qa_container}" 2>/dev/null)"
  [ -n "${IMAGE}" ] || IMAGE="${DN}-sites-render:latest"
  if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    # …else the declared browser image (scripts/ui-coverage/capture-image.sh: the ONE declaration of
    # a browser in this repo) — the same one `bbox flow-qa` runs in.
    . "${HERE}/capture-image.sh"
    ensure_capture_image "route-runtime-qa" \
      || die "no browser image: ${IMAGE} is not on this engine and the declared ui-capture could not be built"
    IMAGE="${UI_CAPTURE_IMAGE:-ui-capture:latest}"
  fi
fi
docker image inspect "${IMAGE}" >/dev/null 2>&1 || die "browser image ${IMAGE} is not on this engine"

docker network inspect traefik-network >/dev/null 2>&1 \
  || die "no traefik-network on this engine — the office is not running here. Bring it up first: ./bbox run"

say "image=${IMAGE}  (args: ${ARGS[*]:-all views})"
# --shm-size: Chromium's own requirement (the default 64 MB crashes tabs during a long run).
# The checkout is mounted at the same layout the driver imports from (drawn.py, inventory.py).
docker run --rm --network traefik-network --shm-size=512m \
  -v "$(npath "${REPO_ROOT}"):/w" -w /w \
  --entrypoint python3 "${IMAGE}" \
  -u scripts/ui-coverage/route-runtime-qa.py ${ARGS[@]+"${ARGS[@]}"}
rc=$?
if printf '%s\n' ${ARGS[@]+"${ARGS[@]}"} | grep -qx -- '--self-test'; then
  [ "${rc}" = 0 ] && ok "the verdict holds: a screen that is never drawn fails the run" \
    || warn "exit ${rc}: the verdict does NOT catch a screen that was never drawn"
else
  [ "${rc}" = 0 ] && ok "every declared view opens and is drawn at its own address" \
    || warn "exit ${rc}: a view that failed, an inventory that drifted, or an engine failure"
fi
exit "${rc}"
