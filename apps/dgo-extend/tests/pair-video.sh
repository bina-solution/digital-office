#!/usr/bin/env bash
# `bbox dgo test pair` — TWO OFFICES PAIRED BY THEIR OWN SCREENS, IN A REAL BROWSER, ON VIDEO.
#
# WHY THIS EXISTS
#   The owner, 2026-10-11: «חייב למצוא דרך להריץ בעצמך שתי לשכות לצמד בינהם אני רוצה סרטון מלא של
#   התהליך». Two offices, two screens, the codes carried by hand — and a screen that cannot finish is
#   a defect no API test can see (the 409 with no way on, measured that morning, was invisible to
#   every green test here).
#
# WHAT IT DOES
#   1. starts two throwaway offices of THIS office's own image (tmpfs state, no data anywhere) on
#      `traefik-network`; one of them declares a dialable address, because a pairing needs exactly one;
#   2. drives their `/connect` pages in Chromium through the Playwright image — the same buttons a
#      person presses: הצגת קוד → הדבקת קוד → פענוח הקוד → אישור — twice: a fresh pairing, and the
#      RETRY that the owner met after a link died (`tests/pair-screens.mjs` owns the flow and fails
#      by name if a screen cannot answer the refusal);
#   3. records both screens and muxes them side by side into ONE film, with a screenshot of every step.
#
#   bash apps/dgo-extend/tests/pair-video.sh          # → ci-artifacts/dgo-pair-video/<stamp>/pair.mp4
#
# Evidence, not a claim: the exit code is the run's, the film is the run itself, and the throwaway
# offices are removed when it ends (their link tokens are taken out of the shared vault with them).
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LIVE="$(docker ps --filter 'name=^dgo-extend-' --format '{{.Names}}' | head -1)"
if [ -z "${LIVE}" ]; then
  echo "pair-video: this office's dgo-extend is not running — \`./bbox run\` first" >&2
  exit 2
fi
IMG="$(docker inspect "${LIVE}" --format '{{.Config.Image}}')"
PW_IMG="mcr.microsoft.com/playwright:v1.49.1-noble"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${REPO_ROOT}/ci-artifacts/dgo-pair-video/${STAMP}"
A="dgo-video-a-$$"; B="dgo-video-b-$$"
WORKVOL="dgo_video_work"; TOOLSVOL="dgo_video_tools"

connections_container() { docker ps --filter 'name=^connections-' --format '{{.Names}}' | head -1; }
vault_delete() {
  local c; c="$(connections_container)"; [ -n "${c}" ] || return 0
  docker exec "${c}" python3 -c "
import sys, urllib.request
r = urllib.request.Request('http://127.0.0.1:8990/api/instances/' + sys.argv[1], method='DELETE')
try:
    print(urllib.request.urlopen(r, timeout=10).status)
except Exception as e:
    print('left behind:', e)
" "$1" 2>/dev/null
}
cleanup() {
  # The throwaway offices wrote their link tokens into the SHARED vault. Each writes ONE, under the
  # PEER's office id (`dgo_link-<peer>`), so the two ids are read off the offices THEMSELVES before
  # they go — the ids are minted from each office's own label, never the container name, and a cleanup
  # that guessed the name left `dgo_link-office-a`/`-office-b` behind on every run (measured).
  local ids=""
  for c in "${A}" "${B}"; do
    ids="${ids} $(docker exec "${c}" python3 -c "
import json, urllib.request
try:
    print(json.load(urllib.request.urlopen('http://127.0.0.1:8983/api/pair', timeout=5))['home']['id'])
except Exception:
    pass" 2>/dev/null)"
  done
  docker rm -f "${A}" "${B}" >/dev/null 2>&1 || true
  local n
  for n in ${ids}; do vault_delete "dgo_link-${n}"; done
}
trap cleanup EXIT

start_office() {   # <name> [extra docker-run args…]
  local name="$1"; shift
  docker run -d --rm --name "${name}" --network traefik-network \
    --tmpfs /data --tmpfs /identity --tmpfs /registry \
    -e DGO_STATE_DIR=/data -e DGO_IDENTITY_DIR=/identity -e DGO_REGISTRY_DIR=/registry \
    -e "DEPLOYMENT_NAME=${name}" -e CONNECTIONS_URL=http://connections:8990 \
    "$@" "${IMG}" >/dev/null
}

mkdir -p "${OUT}/steps"
echo "pair-video: two offices of ${IMG}"
start_office "${A}" || { echo "pair-video: could not start ${A}" >&2; exit 2; }
# B is the office another office can dial: a pairing needs one side that publishes an address
start_office "${B}" -e DGO_WG_ENDPOINT=10.9.9.9 -e DGO_WG_PUBLISH_PORT=51830 \
  || { echo "pair-video: could not start ${B}" >&2; exit 2; }
sleep 4
# every office is ready to be paired from its FIRST minute: an identity minted on its own machine
docker exec "${A}" python3 /app/identity.py --dir /identity --label "OFFICE-A" mint >/dev/null 2>&1
docker exec "${B}" python3 /app/identity.py --dir /identity --label "OFFICE-B" mint >/dev/null 2>&1

echo "pair-video: driving both screens in Chromium (recorded)"
docker run --rm --network traefik-network \
  -v "${REPO_ROOT}/apps/dgo-extend/tests:/t:ro" -v "${OUT}:/out" -v "${WORKVOL}:/work" \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright -e npm_config_cache=/work/.npm \
  "${PW_IMG}" sh -c "cd /work && npm i --silent --no-audit --no-fund playwright-core@1.49.1 >/dev/null 2>&1 \
    && cp /t/pair-screens.mjs /work/ \
    && node /work/pair-screens.mjs --a http://${A}:8983 --b http://${B}:8983 --out /out"
rc=$?

# ── the film: each screen's two rounds, one after the other, side by side ────────────────────────
# A static ffmpeg in its own volume, fetched once: the Playwright image's own build speaks WebM only
# (libvpx), and a WebM is a film the owner cannot open in the Mac's player. The binary runs in the
# python image, so this works from the host, from an agent's container, or anywhere else.
echo "pair-video: ffmpeg (static, once) in volume ${TOOLSVOL}"
docker run --rm -v "${TOOLSVOL}:/t" python:3.12-slim sh -c \
  'test -x /t/ffmpeg || { pip install -q imageio-ffmpeg >/dev/null 2>&1 && cp "$(python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")" /t/ffmpeg && chmod +x /t/ffmpeg; }' \
  || echo "pair-video: ffmpeg unavailable — the .webm recordings below play as they are" >&2
have_all=1
for f in a-r1 a-r2 b-r1 b-r2; do [ -f "${OUT}/${f}.webm" ] || have_all=0; done
if [ "${have_all}" = "1" ]; then
  docker run --rm -v "${TOOLSVOL}:/t" -v "${OUT}:/out" python:3.12-slim /t/ffmpeg -y -loglevel error \
    -i /out/a-r1.webm -i /out/a-r2.webm -i /out/b-r1.webm -i /out/b-r2.webm \
    -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0,scale=1360:940,setsar=1[a]; \
                     [2:v][3:v]concat=n=2:v=1:a=0,scale=1360:940,setsar=1[b]; [a][b]hstack=inputs=2" \
    -c:v libx264 -preset veryfast -crf 27 -pix_fmt yuv420p -movflags +faststart \
    /out/pair.mp4 && echo "pair-video: film → ${OUT}/pair.mp4"
  # the newest film under one name that does not move, so "the video of the process" is one path
  cp -f "${OUT}/pair.mp4" "${REPO_ROOT}/ci-artifacts/dgo-pair-video/pair-latest.mp4" 2>/dev/null \
    && echo "pair-video: newest film → ci-artifacts/dgo-pair-video/pair-latest.mp4"
elif [ "${rc}" != "0" ]; then
  echo "pair-video: the run failed before both rounds were recorded — no film, by design" >&2
fi

echo "pair-video: evidence in ${OUT}"
ls -1 "${OUT}" | sed 's/^/  /'
exit "${rc}"
