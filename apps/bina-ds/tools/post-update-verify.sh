#!/usr/bin/env bash
# post-update-verify — prove from OUTSIDE that a bina-ds self-update actually landed.
#
# WHY THIS EXISTS. On 2026-10-07 two self-updates reported success while the office kept running the
# previous image: the helper's own recreate was handed back to itself by the compose guard ("an update
# is already in progress"), compose exited 0, and the health gate passed on the OLD container. A
# health check cannot tell "the new thing is running" from "the old thing is still healthy", so
# something has to compare what is actually running against what was built — and say so where a person
# will see it, not in a log nobody reads.
#
# Run it on the HOST (through the computers app or a shell), detached, right after handing an update
# off; it waits for the container to come back and then answers three questions with evidence:
#
#   1. does the running container still use the image we applied? (or did it roll back?)
#   2. does the harness inside serve the bundle we expect — grepping for a marker in the client half
#      of the voice plugin, which is what the browser actually receives?
#   3. is the service healthy, and what does the self-update log say?
#
# Usage: post-update-verify.sh [expected-image-id-prefix] [marker]
#   defaults: expected = the image behind ghcr.io/solomonboltin/digital-office/bina-ds:latest
#             marker   = bina-voice-strip (the composer-draft UI, not the rejected overlay panel)
set -uo pipefail

REPO="${BBOX_REPO_HOST:-/root/deployment-hacohen}"
CONTAINER="bina-ds-${DEPLOYMENT_NAME:-staging}"
WANT="${1:-$(docker inspect -f '{{.Id}}' ghcr.io/solomonboltin/digital-office/bina-ds:latest 2>/dev/null)}"
MARKER="${2:-bina-voice-strip}"
OUT="${REPO}/data/bina-ds/post-update-verify.log"
mkdir -p "$(dirname "${OUT}")"

say() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "${OUT}"; }
# Same shape self-update.sh uses (same source_id → one row, updated). Needs traefik-network to
# resolve `notifications`; the wrapper below starts this script that way.
notify() {
  command -v curl >/dev/null 2>&1 || return 0
  printf '{"source":"bina-ds","source_id":"post-update-verify","level":"%s","title":"%s","body":"%s","link":"/#/m/bina"}\n' \
    "$1" "$2" "$3" \
    | curl -fsS -m 10 -H 'Content-Type: application/json' --data-binary @- \
        http://notifications:8977/api/notifications >/dev/null 2>&1 || true
}

say "waiting for ${CONTAINER} to run ${WANT:0:12} and be healthy"
deadline=$(( $(date +%s) + ${VERIFY_WAIT_S:-1500} ))
while :; do
  running="$(docker inspect -f '{{.Image}}' "${CONTAINER}" 2>/dev/null || echo none)"
  state="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo missing)"
  # Wait for the IMAGE to change, not merely for health. An update that has not been applied yet also
  # has a healthy container, and calling that "NOT UPDATED" — which the first version of this script
  # did at 19:51 while the update was still queued — is a false alarm sent to the owner.
  [ -n "${WANT}" ] && [ "${running}" = "${WANT}" ] && [ "${state}" = "healthy" ] && break
  [ "$(date +%s)" -ge "${deadline}" ] && break
  sleep 10
done

health="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo missing)"
started="$(docker inspect -f '{{.State.StartedAt}}' "${CONTAINER}" 2>/dev/null || echo none)"
say "running image ${running:7:12} · health ${health} · started ${started}"

if [ -n "${WANT}" ] && [ "${running}" != "${WANT}" ]; then
  say "VERDICT: NOT UPDATED — the container runs ${running:7:12}, the built image is ${WANT:0:12}"
  say "tail: $(tail -n 3 "${REPO}/data/bina-ds/self-update.log" | tr '\n' ' | ')"
  notify error "העדכון של בינה לא הוחל" "בינה חזרה אבל רצה על אימג' אחר מהנדרש (${running:7:12} במקום ${WANT:0:12})."
  exit 1
fi

# The browser receives the client bundle from the harness; grep what it serves, not what is on disk.
slug="$(docker exec "${CONTAINER}" sh -c 'ls /opt/bina/harness/profile/node_modules/.pnpm | grep -m1 "^@bina+dsh-plugin-voice@"' 2>/dev/null | tr -d '\r')"
served="$(docker exec "${CONTAINER}" sh -c "cat /opt/bina/harness/profile/node_modules/.pnpm/${slug}/node_modules/@bina/dsh-plugin-voice/lib/client.js" 2>/dev/null | grep -c "${MARKER}")"
say "client half served to the browser contains '${MARKER}': ${served} occurrence(s)"

if [ "${served:-0}" -le 0 ] || [ "${health}" != "healthy" ]; then
  say "VERDICT: SUSPECT — health ${health}, marker occurrences ${served:-0}"
  notify warning "בינה עלתה אבל משהו לא תואם" "בריאות: ${health}; סימן הממשק: ${served:-0}. פרטים: data/bina-ds/post-update-verify.log"
  exit 1
fi

# ── the owner's own gesture, in the owner's own conditions, against the LIVE office ──────────────
# The image being right is not the claim. The claim is "press the microphone, speak, stop, get the
# words" — so that is what runs here: 390x844, dark theme, a SHORT recording stopped by hand.
say "running the browser acceptance against the live office (short recording + the audio send)"
playwright_image="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.49.1-noble}"
ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${CONTAINER}" 2>/dev/null | awk '{print $1}')"
launch_token="$(docker logs "${CONTAINER}" 2>&1 | grep -o 'dsh web: http://127.0.0.1:3080/?token=[A-Za-z0-9_-]*' | tail -1 | sed 's/.*token=//')"
if ! docker image inspect "${playwright_image}" >/dev/null 2>&1; then
  say "SKIPPED: ${playwright_image} is not on this engine — the acceptance test did not run"
  notify warning "העדכון הוחל אבל לא נבדק בדפדפן" "התמונה ${playwright_image} אינה במנוע. הרץ ידנית: apps/bina-ds/plugins/voice/tools/verify-voice.cjs"
  exit 0
fi
if [ -z "${ip}" ] || [ -z "${launch_token}" ]; then
  say "SKIPPED: no container IP or launch token — cannot drive the browser"
  notify warning "העדכון הוחל אבל לא נבדק בדפדפן" "לא הצלחתי להשיג IP או טוקן הרצה של בינה."
  exit 0
fi
docker rm -f bina-voice-verify >/dev/null 2>&1 || true
docker run -d --name bina-voice-verify --network traefik-network \
  -e BASE_URL="http://bina.localhost:3080" -e TOKEN="${launch_token}" \
  -e HOST_MAP="bina.localhost ${ip}" -e MOBILE=1 -e MODE=short -e SHORT_MS=8000 \
  -e WAIT_AFTER_STOP_MS=120000 -e NODE_PATH=/tmp/node_modules \
  --entrypoint bash "${playwright_image}" -lc \
    "cd /tmp && npm i --silent playwright-core@1.49.1 >/dev/null 2>&1; cd ${REPO} && cp /tmp/note16k.wav /tmp/note16k.wav 2>/dev/null; node apps/bina-ds/plugins/voice/tools/verify-voice.cjs" \
  >/dev/null 2>&1
# the "microphone" file the acceptance records from
docker cp "${REPO}/data/bina-ds/note16k.wav" bina-voice-verify:/tmp/note16k.wav >/dev/null 2>&1 || true
sleep 200
verdict="$(docker logs bina-voice-verify 2>&1 | tail -80 || true)"
docker rm -f bina-voice-verify >/dev/null 2>&1 || true
printf '%s\n' "${verdict}" >> "${OUT}"
if printf '%s' "${verdict}" | grep -q '"step": "short-recording"' && \
   printf '%s' "${verdict}" | grep -q '"hebrew": true'; then
  say "VERDICT: OK — a short recording produced Hebrew text in the composer (phone viewport, dark)"
  notify success "בינה עודכנה ונבדקה" "הקלטה קצרה תומללה לתיבת ההודעה בדפדפן בטלפון במצב כהה. סגור ופתח את הלשונית."
  exit 0
fi
say "VERDICT: the browser acceptance did not pass — see the log"
notify error "בינה עודכנה אבל בדיקת הדפדפן נכשלה" "הקונטיינר החדש רץ, אבל סימולציית ההקלטה לא החזירה טקסט. פרטים: data/bina-ds/post-update-verify.log"
exit 1
say "VERDICT: SUSPECT — health ${health}, marker occurrences ${served:-0}"
notify warning "בינה עלתה אבל משהו לא תואם" "בריאות: ${health}; סימן הממשק החדש: ${served:-0}. פרטים: data/bina-ds/post-update-verify.log"
exit 1
