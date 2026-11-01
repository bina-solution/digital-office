#!/usr/bin/env bash
# accept.sh — one command that answers "does the microphone actually work for the owner?".
#
#   apps/bina-ds/plugins/voice/tools/accept.sh            # against a throwaway harness built from this tree
#   BASE_URL=… TOKEN=… accept.sh                          # against a running office (the post-update case)
#
# WHY THIS EXISTS. Every failure in this feature so far was shipped because the test environment was
# easier than the owner's: a desktop viewport instead of his phone, a 35-second recording instead of
# the 8-second one he actually makes, and a lab container instead of the office. This script removes
# the excuse: it builds the image, starts a throwaway harness from it, drives a real chromium at a
# phone viewport in the dark theme with a 16 kHz WAV as the microphone — records EIGHT SECONDS,
# stops by hand, and asserts that Hebrew text landed in the composer, that the harness's send button
# delivered it, and that no console error appeared. Non-zero exit on any failure.
#
# It prints PASS/FAIL and the raw JSON. Nothing is "verified" without having run it.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
TOOLS="${REPO}/apps/bina-ds/plugins/voice/tools"
HARNESS="${ACCEPT_HARNESS:-bina-accept}"
RUNNER="${ACCEPT_RUNNER:-accept-runner}"
IMAGE="${ACCEPT_IMAGE:-ghcr.io/solomonboltin/digital-office/bina-ds:latest}"
PLAYWRIGHT_IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.49.1-noble}"
WAV="${ACCEPT_WAV:-${REPO}/data/bina-ds/note16k.wav}"
SHORT_MS="${SHORT_MS:-8000}"
MODE="${MODE:-short}"

cleanup() {
  [ "${KEEP:-0}" = 1 ] || { docker rm -f "${HARNESS}" "${RUNNER}" >/dev/null 2>&1 || true; }
}
trap cleanup EXIT

if [ ! -f "${WAV}" ]; then
  echo "accept: no microphone file at ${WAV}" >&2
  echo "        record any Hebrew voice note and convert it:  ffmpeg -i note.ogg -ac 1 -ar 16000 note16k.wav" >&2
  echo "        (or point ACCEPT_WAV at one; the file is a stand-in for the owner's microphone)" >&2
  exit 2
fi

own_office=0
if [ -n "${BASE_URL:-}" ] && [ -n "${TOKEN:-}" ]; then
  own_office=1
else
  echo "accept: building ${IMAGE} from this tree…"
  ( cd "${REPO}" && BBOX_HEAVY_MIN_MB="${BBOX_HEAVY_MIN_MB:-700}" ./scripts/dc build bina-ds ) >/tmp/accept-build.log 2>&1 \
    || { echo "accept: build failed — see /tmp/accept-build.log" >&2; tail -5 /tmp/accept-build.log >&2; exit 2; }
  docker rm -f "${HARNESS}" >/dev/null 2>&1 || true
  docker run -d --name "${HARNESS}" --network traefik-network \
    -e DSH_HOME=/tmp/dsh-accept -e DSH_PROFILE=bina -e DSH_PORT=3080 \
    -e DSH_OFFICE_ROOT="${REPO}" -e DSH_TRUSTED_HOSTS="bina.localhost console.localhost" \
    -e DSH_PERMISSION_MODE=danger-full-access -e AGENT_TOKEN_FILE=/tmp/dsh-accept/api-token \
    -e TZ=Asia/Jerusalem -v "${REPO}:${REPO}" "${IMAGE}" >/dev/null || exit 2
  sleep 22
  BASE_URL="http://bina.localhost:3080"
  TOKEN="$(docker logs "${HARNESS}" 2>&1 | grep -o 'token=[A-Za-z0-9_-]*' | tail -1 | sed 's/token=//')"
  host_ip="$(docker inspect "${HARNESS}" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
fi

host_ip="${host_ip:-$(getent hosts "$(printf '%s' "${BASE_URL}" | sed -E 's#https?://([^:/]+).*#\1#')" | awk '{print $1}' | head -1)}"
docker rm -f "${RUNNER}" >/dev/null 2>&1 || true
docker run -d --name "${RUNNER}" --network traefik-network "${PLAYWRIGHT_IMAGE}" sleep 1800 >/dev/null
docker exec "${RUNNER}" sh -c 'cd /tmp && npm i --silent playwright-core@1.49.1 >/dev/null 2>&1'
docker cp "${TOOLS}/verify-voice.cjs" "${RUNNER}:/verify.cjs" >/dev/null
docker cp "${WAV}" "${RUNNER}:/tmp/note16k.wav" >/dev/null

echo "accept: recording ${SHORT_MS}ms on a phone viewport (dark), then asserting…"
docker exec \
  -e BASE_URL="${BASE_URL}" -e TOKEN="${TOKEN}" \
  -e HOST_MAP="bina.localhost ${host_ip}" \
  -e MOBILE=1 -e MODE="${MODE}" -e SHORT_MS="${SHORT_MS}" \
  -e WAIT_AFTER_STOP_MS="${WAIT_AFTER_STOP_MS:-120000}" \
  "${RUNNER}" node /verify.cjs 2>&1 | grep -vE '"Failed to load resource' | tail -40
rc="${PIPESTATUS[0]}"
[ "${own_office}" = 1 ] && KEEP=1
echo "accept: exit ${rc}"
exit "${rc}"
