#!/usr/bin/env bash
# app-update.sh — apply ONE app's rebuilt image to the running office, and prove it landed.
#
#     ./bbox update <app|service> […]        [--force] [--timeout S]
#
# WHY THIS EXISTS. `./scripts/dc up -d --build <app>` is the documented way to deploy an app, and on
# 2026-10-12 it failed twice in the same hour, silently, while updating drive:
#
#   * THE BUILD SUCCEEDED AND NOTHING WAS REPLACED. Compose printed `Container drive-staging
#     Running`, and the container kept the image it had been started from — even though a new image
#     had just been built and tagged under the very name the service uses (`pull_policy: missing` +
#     `image:` means compose resolves the tag once and compares the CONFIGURATION, where the image
#     name is unchanged). A deploy that did nothing read exactly like a deploy that worked; the only
#     way to tell was to grep the served asset for the change (which is how it was caught). `--force
#     -recreate` is what the first case needs, unconditionally.
#   * NOBODY ASKED ABOUT HEALTH. An image that comes up unhealthy, or crash-loops, was reported by no
#     one: compose exits 0 as soon as the container is started.
#
# So: build, compare the image the CONTAINER runs against the one just built, replace only when they
# differ (or when --force), wait for the container's own healthcheck, and put the previous image back
# if it never gets healthy. One line per app, and it either says what changed or says why not.
#
# bina-ds IS LEFT TO ITS OWN DOOR and this verb says so: recreating it kills the agent that is
# running the command, so the recreate is handed to apps/bina-ds/self-update.sh through the guard in
# scripts/lib.sh (which waits for the asking conversation's turn to end and then continues it). This
# verb detects the hand-off and does not wait for a container it just asked to die.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
# `--force` may arrive twice over: as this script's own flag, or as bbox's global one, which bbox
# consumes before dispatch and hands over in APP_UPDATE_FORCE (its own --force never reaches a verb).
FORCE="${APP_UPDATE_FORCE:-0}"
TIMEOUT="${APP_UPDATE_TIMEOUT:-240}"
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --force)   FORCE=1 ;;
    --timeout) shift ;;
    --timeout=*) TIMEOUT="${arg#*=}" ;;
    *) ARGS+=("${arg}") ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
[ "$#" -gt 0 ] || { echo "usage: bbox update <app|service> […] [--force] [--timeout S]" >&2; exit 2; }

dc() { "${REPO}/scripts/dc" "$@"; }
say() { printf '%s\n' "$*"; }
bad=0

# The image a container was STARTED from (by id) — the only thing that answers "did this deploy
# change anything", because the tag it was started from may since point at a different build.
running_image() { docker inspect -f '{{.Image}}' "$1" 2>/dev/null; }
container_image_name() { docker inspect -f '{{.Config.Image}}' "$1" 2>/dev/null; }

health_of() {
  local cid="$1"
  docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "${cid}" 2>/dev/null
}

wait_healthy() {   # → 0 healthy (or running with no healthcheck), 1 unhealthy/gone
  local svc="$1" waited=0 st cid
  while [ "${waited}" -lt "${TIMEOUT}" ]; do
    cid="$(dc ps -a -q "${svc}" 2>/dev/null | head -n1)"
    if [ -n "${cid}" ]; then
      st="$(health_of "${cid}")"
      case "${st}" in
        "running healthy"|"running ") return 0 ;;
        *unhealthy*|exited*|dead*|restarting*) say "  ${svc}: ${st}"; return 1 ;;
      esac
    fi
    sleep 5; waited=$(( waited + 5 ))
  done
  say "  ${svc}: not healthy after ${TIMEOUT}s (last: ${st:-no container})"
  return 1
}

# #63 — may the console still show the app inside itself? Returns 1 only when FRAME_GATE=refuse (.env) and the
# app forbids the console's frame (platform/manager/framecheck.py exits 3); a checker that cannot run keeps the
# update. Asked from inside app-management when it runs — it mounts this checkout at the same path and sits on
# the office network, so an embedded app's internal address answers too — else from here.
frame_gate() {
  local svc="$1" am rc=0
  am="$(dc ps -q app-management 2>/dev/null | head -n1)"
  if [ -n "${am}" ] && docker exec "${am}" test -f "${REPO}/platform/manager/framecheck.py" 2>/dev/null; then
    docker exec "${am}" python3 "${REPO}/platform/manager/framecheck.py" check "${svc}" --phase update 2>&1 \
      | sed 's/^/  /'; rc="${PIPESTATUS[0]}"
  else
    python3 "${REPO}/platform/manager/framecheck.py" check "${svc}" --phase update 2>&1 | sed 's/^/  /'
    rc="${PIPESTATUS[0]}"
  fi
  [ "${rc}" -ne 3 ]
}

for svc in "$@"; do
  cid="$(dc ps -a -q "${svc}" 2>/dev/null | head -n1)"
  before=""; ref=""
  if [ -n "${cid}" ]; then
    before="$(running_image "${cid}")"
    ref="$(container_image_name "${cid}")"
  fi
  say "== ${svc}"
  if ! dc build "${svc}" >/tmp/app-update-build.$$ 2>&1; then
    say "  build FAILED — last lines:"; tail -5 /tmp/app-update-build.$$ | sed 's/^/    /'; bad=1; rm -f /tmp/app-update-build.$$; continue
  fi
  rm -f /tmp/app-update-build.$$
  # COMPOSE'S OWN NAME FOR THE IMAGE, not the one the running container was started with. They can
  # differ (`my-docs-local:latest` on a container built before the image was renamed, while compose
  # now builds `ghcr.io/…/my-docs:latest`), and comparing "before" against a name the build never
  # touched reported `nothing to apply` for a change that had just been built — measured
  # 2026-10-12 on my-docs, where the running container said 1ae98ad98ce9 and the fresh build was
  # 79d0667b0b0a under compose's name.
  built="$(dc config --images "${svc}" 2>/dev/null | head -n1)"
  [ -n "${built}" ] && ref="${built}"
  after="$(docker image inspect -f '{{.Id}}' "${ref}" 2>/dev/null || true)"
  if [ -n "${before}" ] && [ -n "${after}" ] && [ "${before}" = "${after}" ] && [ "${FORCE}" -eq 0 ]; then
    say "  nothing to apply — ${svc} already runs the build just made (${after:7:12})"
    continue
  fi
  [ -n "${before}" ] && docker tag "${before}" "${ref%%:*}:previous" 2>/dev/null || true
  # A SERVICE THAT SHIPS ITS OWN RECREATE DOOR IS REPLACED THROUGH IT — from the host too.
  # `<root>/<id>/hooks/self-update` is that door ("recreate ME, from outside myself") and it is the
  # only path that snapshots the conversations working at that moment and sends each of them its
  # "carry on" message. The compose guard in scripts/lib.sh hands off by itself only when the CALLER
  # is inside the container being replaced (`bbox_self_service`, lib.sh:697 — `[ -f /.dockerenv ]`),
  # so a host-side `bbox update bina-ds` recreated it directly: measured 2026-10-13, twice
  # (12:37Z→12:39Z and 12:21Z→12:24Z), and the session that was mid-turn at 12:23:49Z was simply gone.
  # BBOX_UPDATE_NOW says what this is — an EXPLICIT update, not a background one — so the door applies
  # at its first check instead of holding the update for a free moment it may never see, and still
  # resumes whoever it cut.
  door=""
  for root in apps platform-base; do
    [ -x "${REPO}/${root}/${svc}/hooks/self-update" ] && { door="${REPO}/${root}/${svc}/hooks/self-update"; break; }
  done
  if [ -n "${door}" ]; then
    out="$(BBOX_UPDATE_NOW=1 bash "${door}" launch up --force-recreate 2>&1)" || true
    printf '%s\n' "${out}" | tail -3 | sed 's/^/  /'
    if printf '%s\n' "${out}" | grep -q "handed off"; then
      say "  handed to ${svc}'s own self-update door — it applies now, health-checks itself, rolls the"
      say "  previous image back if the new one is not healthy, and continues whoever was mid-turn;"
      say "  the log is data/${svc}/self-update.log"
      continue
    fi
    say "  ${svc} ships a self-update door but it did not take the recreate; falling back to compose"
  fi
  out="$(dc up -d --force-recreate "${svc}" 2>&1)"
  printf '%s\n' "${out}" | tail -3 | sed 's/^/  /'
  if printf '%s\n' "${out}" | grep -q "handed off\|handed to a helper"; then
    say "  handed to bina-ds's own self-update helper (its recreate is done from outside this"
    say "  container, and the conversation that asked is continued when it is back) — see"
    say "  data/bina-ds/self-update.log"
    continue
  fi
  if wait_healthy "${svc}"; then
    cid="$(dc ps -a -q "${svc}" | head -n1)"
    # #63: FRAME_GATE=refuse and the app forbids the console's frame -> the previous image goes back, as for
    # an update that never gets healthy; warn (the default) only says so
    if ! frame_gate "${svc}"; then
      if [ -n "${before}" ] && [ "${before}" != "${after}" ]; then
        say "  rolling back to ${before:7:12} (FRAME_GATE=refuse)"
        docker tag "${before}" "${ref}" 2>/dev/null && dc up -d --force-recreate "${svc}" >/dev/null 2>&1
        if wait_healthy "${svc}"; then say "  rolled back — ${svc} runs the previous image"
        else say "  ${svc} did not come back on the previous image"; fi
      else
        say "  ${svc}: there is no previous image to go back to — it keeps the new one"
      fi
      bad=1; continue
    fi
    say "  ok — ${svc} healthy on ${after:7:12} (was ${before:7:12})"
    continue
  fi
  if [ -z "${before}" ] || [ "${before}" = "${after}" ]; then
    say "  ${svc} did not become healthy and there is no previous image to go back to"; bad=1; continue
  fi
  say "  rolling back to ${before:7:12}"
  docker tag "${before}" "${ref}" 2>/dev/null && dc up -d --force-recreate "${svc}" >/dev/null 2>&1
  if wait_healthy "${svc}"; then
    say "  rolled back — ${svc} healthy on the previous image"
  else
    say "  ${svc} did not come back on the previous image either — this is the environment, not the build"; bad=1
  fi
done
exit "${bad}"
