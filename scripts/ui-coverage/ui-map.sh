#!/usr/bin/env bash
# ui-map.sh — capture the whole platform UI into ONE map image + coverage (bbox ui-map).
#
# The single, consolidated platform-capture pipeline, run byte-for-byte the same locally and in
# CI (no per-environment branches):
#   inventory.py   source  → ui-inventory.json        the denominator (drift-guarded)
#   seed.sh        stack   → demo data                so every view renders real content
#   resolve_params source  → ui-params.json           real ids for /:repo, /:type/:name, {folder}…
#   run_capture.sh browser → screenshots + coverage   N Chromium containers, sharded, direct-to-console
#   report.py      host    → coverage summary + JUnit + markdown
#   compose_map.py host    → ui-map.png + index.html   the one big image
#
# Reads a RUNNING stack (bring it up with `bbox run` first). Env overrides:
#   UI_DATA          data dir (default data/ui-map)          UI_ARTIFACTS   output dir (default ci-artifacts)
#   UI_MAP_SHARDS    parallel shards (default 4; 32-core CI takes 8+)
#   UI_MAP_APPS      app list (default: the first-party eight currently enabled — see
#                    run_capture.sh's APPS= for why my-docs is excluded while disabled)
#   UI_MAP_SKIP_SEED 1 to skip seeding (already seeded)      UI_MAP_GATE    1 to exit non-zero on misses
#   UI_MAP_PROFILE   view profile: mobile|tablet|desktop (default from view-profiles.yaml).
#                    Also settable as `bbox ui-map --profile mobile`. Artifacts for a non-default
#                    profile land in <artifacts>/ui-map/<profile>/ so profiles never overwrite
#                    each other and CI can publish all three from one matrix.
set -uo pipefail
# --profile <name> is sugar for UI_MAP_PROFILE=<name>; everything else passes through untouched.
_um_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) UI_MAP_PROFILE="${2:-}"; shift 2 ;;
    --profile=*) UI_MAP_PROFILE="${1#*=}"; shift ;;
    *) _um_args+=("$1"); shift ;;
  esac
done
[ ${#_um_args[@]} -gt 0 ] && set -- "${_um_args[@]}" || set --
export UI_MAP_PROFILE="${UI_MAP_PROFILE:-}"

UM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "${UM_DIR}/.." && pwd)/lib.sh"
cd "${REPO_ROOT}"

# host-step deps: report/compose parse manifest.yaml (PyYAML) and render the mockup (Pillow).
for mp in "yaml:pyyaml" "PIL:Pillow"; do
  m="${mp%%:*}"; p="${mp##*:}"
  python3 -c "import ${m}" 2>/dev/null || pip3 install --quiet ${UI_PIP_ARGS:-} "$p" 2>/dev/null \
    || pip3 install --quiet --break-system-packages ${UI_PIP_ARGS:-} "$p" 2>/dev/null || warn "could not install $p"
done

DATA="${UI_DATA:-${REPO_ROOT}/data/ui-map}"
ART="${UI_ARTIFACTS:-${REPO_ROOT}/ci-artifacts}"
# Resolve the profile name (empty => the file's default) and scope BOTH the data and artifact dirs to
# it for anything but the default, so `--profile mobile` can never clobber the desktop baseline.
UI_MAP_PROFILE_RESOLVED="$(python3 - <<'PYP' 2>/dev/null || echo desktop
import os,yaml,pathlib
f=pathlib.Path("scripts/ui-coverage/view-profiles.yaml")
d=yaml.safe_load(f.read_text(encoding="utf-8"))
n=os.getenv("UI_MAP_PROFILE") or d.get("default","desktop")
print(n if n in d["profiles"] else d.get("default","desktop"))
PYP
)"
export UI_MAP_PROFILE="${UI_MAP_PROFILE_RESOLVED}"
if [ "${UI_MAP_PROFILE}" != "desktop" ]; then
  DATA="${DATA}/${UI_MAP_PROFILE}"
  ART="${ART}/ui-map/${UI_MAP_PROFILE}"
fi
say "view profile: ${UI_MAP_PROFILE}"
SHOTS="${ART}/screenshots-ui"
mkdir -p "${DATA}/output/ui" "${ART}" "${SHOTS}"

CONSOLE="$(cn console)"; [ -n "$CONSOLE" ] || die "console container not running — 'bbox run' first"

# The browser reaches the console DIRECTLY on its own port via a host-resolver rule (run_capture.sh),
# so the base URL is always console.localhost:<port> regardless of the real public domain — the same
# in every environment. Discover the console's published container port (8000 for this image).
CPORT="${UI_CONSOLE_PORT:-$(docker inspect "$CONSOLE" --format '{{range $p,$_ := .Config.ExposedPorts}}{{$p}} {{end}}' 2>/dev/null | tr '/' ' ' | awk '{print $1; exit}')}"
CPORT="${CPORT:-8000}"
printf '{"CONSOLE_BASE_URL":"console.localhost:%s"}\n' "$CPORT" > "${DATA}/ui-env.json"

log "ui-map — inventory"
python3 "$(npath "${UM_DIR}")/inventory.py" --out "$(npath "${DATA}")/ui-inventory.json" || die "UI inventory has drift — denominator not trustworthy"
cp "${DATA}/ui-inventory.json" "${ART}/ui-inventory.json" 2>/dev/null || true

[ "${UI_MAP_SKIP_SEED:-0}" = 1 ] || UI_DATA="${DATA}" bash "${UM_DIR}/seed.sh"

log "ui-map — resolve parameterised-route ids"
python3 "$(npath "${UM_DIR}")/resolve_params.py" --data "$(npath "${DATA}")" || warn "param resolve reported issues — continuing"

# THE capture: N Chromium containers, sharded, direct-to-console (no browser42). Shared mechanism.
UI_DATA="${DATA}" UI_CONSOLE_CONTAINER="${CONSOLE}" bash "${UM_DIR}/run_capture.sh"

cp "${DATA}/ui-capture-results.json" "${ART}/" 2>/dev/null || true
cp "${DATA}/ui-raw-coverage.json"    "${ART}/" 2>/dev/null || true
cp "${DATA}"/output/ui/*.png         "${SHOTS}/" 2>/dev/null || true

log "ui-map — coverage report"
python3 "$(npath "${UM_DIR}")/report.py" --raw "$(npath "${DATA}")/ui-raw-coverage.json" --results "$(npath "${DATA}")/ui-capture-results.json" --outdir "$(npath "${ART}")"

log "ui-map — compose the one big image"
python3 "$(npath "${UM_DIR}")/compose_map.py" --results "$(npath "${DATA}")/ui-capture-results.json" \
  --inventory "$(npath "${DATA}")/ui-inventory.json" --coverage "$(npath "${ART}")/ui-code-coverage.json" --out "$(npath "${ART}")/ui-map"

# Report THIS run's results, not whatever png files happen to be lying on disk.
#
# This line used to be `ls "${SHOTS}"/*.png | wc -l`, so a run in which every shard failed still
# counted the PREVIOUS run's screenshots and printed a tick with exit 0. That is exactly how a
# broken capture passed for green — the success line was measuring the filesystem, not the work.
n_cap="$(python3 -c "$(printf '%s\n' \
  "import json,sys" \
  "try: r = json.load(open(sys.argv[1], encoding='utf-8'))['results']" \
  "except Exception: r = []" \
  "print(sum(1 for x in r if x.get('status') != 'failed'))")" \
  "$(npath "${DATA}")/ui-capture-results.json" 2>/dev/null || echo 0)"
[ "${n_cap:-0}" -gt 0 ] 2>/dev/null || die "capture produced NO results — ${DATA}/ui-capture-results.json is missing or empty. Screenshots on disk are from an earlier run and are NOT being reported as success."
n_png="$(ls -1 "${SHOTS}"/*.png 2>/dev/null | wc -l | tr -d ' ')"
ok "ui-map — done: ${n_cap} views captured THIS run; ${n_png} screenshots on disk + ${ART}/ui-map/ui-map.png"

# Optional gate (default off): fail if any first-party view went uncaptured.
if [ "${UI_MAP_GATE:-0}" = 1 ]; then
  python3 - "$(npath "${DATA}")/ui-capture-results.json" <<'PY' || exit 1
import json, sys
r = json.load(open(sys.argv[1]))["results"]
bad = [x for x in r if x["status"] == "failed" and x.get("tier") != "third_party"]
print(f"gate: {len(bad)} first-party views failed" if bad else "gate: all first-party views captured")
sys.exit(1 if bad else 0)
PY
fi
