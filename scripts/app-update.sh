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
# BEFORE ANY OF THAT, the compile follows the checkout and a provider the checkout newly requires is brought
# up (DGO-1583, below the helpers): an update of an app that now needs an app this office never ran used to
# leave it without that provider until a whole `bbox run`.
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
# a while loop, not `for arg in "$@"`: a `shift` inside a for loop never reached the S of `--timeout S`, which
# was then updated as if it named a service (the form `--timeout=S` was the only one that worked)
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)   FORCE=1 ;;
    --timeout) [ "$#" -gt 1 ] || { echo "usage: bbox update <app|service> […] [--force] [--timeout S]" >&2; exit 2; }
               TIMEOUT="$2"; shift ;;
    --timeout=*) TIMEOUT="${1#*=}" ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done
set -- ${ARGS[@]+"${ARGS[@]}"}
[ "$#" -gt 0 ] || { echo "usage: bbox update <app|service> […] [--force] [--timeout S]" >&2; exit 2; }
case "${TIMEOUT}" in ''|*[!0-9]*) echo "usage: --timeout takes whole seconds (got '${TIMEOUT}')" >&2; exit 2 ;; esac
# what the compiler, the plan and the frame check print is Hebrew too: UTF-8 io everywhere, or Windows dies (G10)
export PYTHONIOENCODING=utf-8

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

# ── THE COMPILE FOLLOWS THE CHECKOUT, AND A PROVIDER IT NEWLY REQUIRES COMES UP FIRST (DGO-1583) ──────────
# `.generated/` is compiled from the checkout and gitignored, so moving the checkout does not move it: an
# update built the new image and recreated the container from the compile of the LAST bring-up. When the
# checkout made an app require a provider this office has never run (DGO-1500 split «קבצים» into drive-local
# and drive-google), that provider was not in the compile at all: `bbox update drive` recreated drive without
# its engines, `bbox update drive-local` answered «no such service», and only a whole `bbox run` brought them.
#
# So the update does first what a bring-up does before it touches anything, in `bbox run`'s order: the deploy
# ledger's check (G90: never a checkout that drops what this office runs — asked before the compile, which
# writes the edge's and the sign-in's files too), the keys a new app needs in .env (scripts/env-secrets.py
# --if-fresh, `bbox run`'s ensure_secrets), and the compile, which compose must then accept (`dc config -q`).
# An update compiles as `bbox run` does, so it also ends a `bbox rollback` (and says so), and each one archives a
# generation. A compile that fails as `bbox run`'s would is answered as `bbox run` answers it: no app is updated
# — when it had begun to write (it archives the compile it replaces first, so a new generation says it had), and
# when compose refuses what it wrote; then .generated/ and the edge's files may hold the new compile, and the
# update names the generation that puts back the one it replaced. One that failed before it wrote anything
# leaves the office's last compile whole: the update goes on with it as it did before, brings up no provider,
# and exits 1.
#
# Then the named apps' hard closure (scripts/app-update-plan.py, the compiler's own resolution), in dependency
# order. What the CHECKOUT newly requires is remembered until it is up: every app a compile adds — compiled now,
# absent from the compile this update found (.generated/resolved.json's `order`) — goes into
# data/.deploy/update-pending, and leaves it only once it is UP (a first start that crashed leaves a container
# behind, and that is not up) or once it was updated by name. So a retry after a provider failed, or an update of
# another app first (whose compile already holds the new provider), still knows it is new. Another path that
# compiles the moved checkout first (the apps screen, `bbox apps enable`) records nothing here: a provider absent
# for that reason is named, and the update exits 1 rather than report success without it. A pending provider
# that runs HERE and is not up is brought up as a bring-up brings up an app: its `prepare` hook,
# its images, its containers alone (`--no-deps`: what it depends on is up already, or named below, and never
# recreated by this), a wait as long as its own first start may take (its `progress_deadline_seconds`, as
# app-management waits) that counts a run-once service that finished as done and an exit, or a container
# restarting again and again, as failed, its `onboard` hook. Its sign-in refresh and its automations are not an
# update's, and are said. A hook that fails is said and fails the update, as a bring-up says it, and stops
# nothing. Every other provider is never touched: one that has no container and is not pending was taken down
# (`bbox stop` removes containers) or left out by somebody's choice (named, and the update exits 1), and one that
# is stopped is somebody's decision or an on-demand app asleep (named). Two updates at once are not serialised:
# the pending file's last writer wins (an entry lost there is the «exits 1» case above). No provider is brought
# up when the containers could not be listed, nothing of the office runs, the compile it found cannot be read,
# or a named app is not compiled here at all. A provider that does not come up leaves every named app on the
# image it runs. A named app that has no container at all is created by its own update below, as before; its
# `prepare` and `onboard` hooks are the enable path's (`bbox apps enable`), not an update's.
POLL="${APP_UPDATE_POLL:-5}"

# provider_hook, wait_up and bring_up: the ONE bring-up of a provider, which the apps screen's enable runs too
# (DGO-1496) — so the two doors bring a provider up the same way
. "${HERE}/provider-up.sh" || { echo "scripts/provider-up.sh could not be read — this checkout is incomplete; nothing updated" >&2; exit 1; }

newest_generation() { ls -1 "${REPO}/.generated/generations" 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -n1; }
compiled_order() {   # the apps a compile ran, from its resolved.json; nothing when it cannot be read
  python3 -c 'import json, sys; print(" ".join(json.load(open(sys.argv[1])).get("order") or []))' \
    "${REPO}/.generated/resolved.json" 2>/dev/null
}
said_by() {   # log — the lines that say what went wrong (the compiler prints its info lines too), else the last ones
  grep -E 'ERROR|FAILED|REFUSED|FATAL|[Ee]rror' "$1" | tail -5 | sed 's/^/    /' | grep . || tail -5 "$1" | sed 's/^/    /'
}
undo_hint() {   # the generation the compiler archived before it wrote: the compile it replaced
  local g; g="$(newest_generation)"
  [ -n "${g}" ] && [ "${g}" != "${gen0}" ] \
    && say "  .generated/ may now hold the new compile; generation ${g} is the .generated/ it replaced (python3 platform/manager/reconcile.py rollback --for ${g}). The edge's zz-serve.yaml and the sign-in blueprint are outside it: the next compile that succeeds writes them again"
}
PENDING="${REPO}/data/.deploy/update-pending"
pending=""
add_pending() { case " ${pending} " in *" $1 "*) ;; *) pending="${pending} $1" ;; esac; }
drop_pending() {
  case " ${pending} " in *" $1 "*) ;; *) return 0 ;; esac
  pending="$(printf '%s\n' ${pending} | grep -vxF "$1" | tr '\n' ' ')"; save_pending
}
save_pending() {
  # the host user and the agent's container (root) both update from one checkout, so the folder is anyone's to
  # write, as the deploy ledger's is (deploy_ledger_record): a rename needs the folder, not the file
  local dir; dir="$(dirname "${PENDING}")"
  { mkdir -p "${dir}" && chmod a+rwx "${dir}"; } 2>/dev/null
  if ! { printf '%s\n' ${pending} | grep . > "${PENDING}.tmp.$$"; [ -f "${PENDING}.tmp.$$" ] && mv -f "${PENDING}.tmp.$$" "${PENDING}"; } 2>/dev/null; then
    rm -f "${PENDING}.tmp.$$" 2>/dev/null
    say "  (what the checkout added could not be written to ${PENDING#"${REPO}"/} — a later update may not know it is new)"
  fi
}

# G90 first: a checkout that drops what this office runs is refused before anything is compiled or built
if [ -f "${REPO}/scripts/lib.sh" ] && ! ( cd "${REPO}" && . scripts/lib.sh && deploy_ledger_gate build ); then
  say "nothing updated — the deploy ledger refuses this checkout (above)"
  exit 1
fi
[ ! -f "${REPO}/.env" ] || ( cd "${REPO}" && python3 scripts/env-secrets.py --env .env --if-fresh ) \
  || say "the keys of .env could not be checked (scripts/env-secrets.py, above) — the update goes on"
compiled=1
gen0="$(newest_generation)"
# the apps the compile this update found ran: an app compiled now and absent there is what the checkout added
had="$(compiled_order)" || had=""
log="$(mktemp)"
if ! ( cd "${REPO}" && python3 platform/manager/reconcile.py render ) >"${log}" 2>&1; then
  say "the compile FAILED:"; said_by "${log}"
  if [ "$(newest_generation)" != "${gen0}" ]; then
    # it archives the compile it replaces before it writes: it had begun to write, as a failed `bbox run` would have
    say "no app updated — the compile stopped after it began to write; \`bbox run\` refuses this checkout too: fix what it says above, and update again"
    undo_hint; rm -f "${log}"; exit 1
  fi
  compiled=0; bad=1
  say "  it wrote nothing: this update runs on the office's last compile, brings up no provider, and exits 1"
elif ! dc config -q >"${log}" 2>&1; then
  say "no app updated — compose refuses the new compile, as \`bbox run\` would:"; said_by "${log}"
  undo_hint; rm -f "${log}"; exit 1
else
  say "compiled the checkout, as \`bbox run\` does (a \`bbox rollback\` in force ends here)"
  # what this compile added stays pending until it is up — across a failed bring-up, and across updates
  pending="$( { tr '\n' ' ' < "${PENDING}"; } 2>/dev/null)"
  if [ -n "${had}" ]; then
    before="${pending}"
    for a in $(compiled_order); do case " ${had} " in *" ${a} "*) ;; *) add_pending "${a}" ;; esac; done
    [ "${pending}" = "${before}" ] || save_pending
  fi
fi
rm -f "${log}"

# the named arguments in the closure's dependency order (a named provider before the app that needs it)
order=("$@")
held=""             # a provider that did not come up: the apps named here are not touched
if [ "${compiled}" -eq 1 ]; then
  if ! plan="$(cd "${REPO}" && python3 scripts/app-update-plan.py "$@")"; then
    say "the providers of $* could not be resolved (above) — none is brought up"
    plan=""
  fi
  named_apps="$(printf '%s\n' "${plan}" | awk '$1 == "named" && $3 != "-" {print $3}' | awk '!seen[$0]++' | tr '\n' ' ')"
  named_apps="${named_apps% }"
  if [ -n "${plan}" ]; then
    order=()
    while read -r kind arg _; do [ "${kind}" = named ] && order+=("${arg}"); done <<<"${plan}"
  fi
  declared=" $(dc config --services 2>/dev/null | tr '\n' ' ') "
  if ! present="$(dc ps -a --format '{{.Service}} {{.State}}' 2>/dev/null)"; then
    [ -z "${plan}" ] || say "the office's containers could not be listed — no provider is brought up"
    plan=""
  elif [ -n "${plan}" ] && ! printf '%s\n' "${present}" | awk '$2 == "running" {found = 1} END {exit !found}'; then
    say "nothing of this office is running — no provider is brought up (\`bbox run\` brings the office up)"
    plan=""
  elif [ -n "${plan}" ] && [ -z "${had}" ]; then
    say "the compile this update found could not be read (.generated/resolved.json) — no provider is brought up"
    plan=""
  fi
  # a named app none of whose services is compiled here runs elsewhere, or not at all: its providers are not this
  # office's to bring up (its own update below says «no such service», as it always did)
  while read -r kind f1 f2 f3 svcs; do
    [ "${kind}" = named ] && [ "${f2}" != "-" ] || continue
    here=()
    for s in ${svcs}; do [[ "${declared}" == *" ${s} "* ]] && here+=("${s}"); done
    if [ "${#here[@]}" -eq 0 ]; then
      say "${f2} is not compiled on this office — no provider is brought up"
      plan="$(printf '%s\n' "${plan}" | awk '$1 != "provider"')"
      break
    fi
  done <<<"${plan}"
  while read -r kind f1 f2 f3 svcs; do
    [ "${kind}" = provider ] || continue
    # `provider <root> <app> <seconds of its first start> <service>…`
    root="${f1}"; aid="${f2}"; limit="${f3}"
    here=()
    for s in ${svcs}; do [[ "${declared}" == *" ${s} "* ]] && here+=("${s}"); done
    # none of its services is compiled here: it runs on another office, or not at all
    [ "${#here[@]}" -gt 0 ] || continue
    states="$(printf '%s\n' "${present}" | awk -v want=" ${here[*]} " 'index(want, " " $1 " ") {print $2}')"
    case " ${pending} " in
      *" ${aid} "*)
        # new in the checkout: it stays pending until it is UP — a first start that crashed leaves a container behind,
        # and that container is no reason to update the app without it
        if [ -n "${states}" ] && POLL=0 wait_up 0 "${here[@]}" >/dev/null; then drop_pending "${aid}"; continue; fi ;;
      *)
        if [ -n "${states}" ]; then
          case $'\n'"${states}"$'\n' in
            *$'\n'running$'\n'*) ;;
            *) say "== ${aid} — required by ${named_apps} and not running (${here[*]}); an update starts no provider: \`bbox run\` or the apps screen does" ;;
          esac
        else
          # compiled here, required, and absent — but not what this update's compiles added (another path compiled
          # the checkout first, or it was taken down: `bbox stop` removes containers). Not touched, and not a success.
          say "== ${aid} — required by ${named_apps}, has no container here, and is not pending from an update (another compile came first, or it was taken down): ${named_apps} is updated without it, and the update exits 1 — \`bbox run\` or the apps screen brings it up"
          bad=1
        fi
        continue ;;
    esac
    say "== ${aid} — the checkout makes ${named_apps} require it, and it is not up here: bringing it up first"
    if ! bring_up "${root}" "${aid}" "${limit}" "${here[@]}"; then held="${held} ${aid}"; bad=1; break; fi
    drop_pending "${aid}"
    for later in $(printf '%s\n' "${plan}" | awk -v a="${aid}" '$1 == "later" && $2 == a {print $3}'); do
      case "${later}" in
        sign-in)     say "  the sign-in refresh of the host it gates comes with the next \`bbox run\`" ;;
        automations) say "  its automations (n8n blueprints) are not pushed by an update: \`bbox n8n push ${aid}\` does" ;;
      esac
    done
    say "  ok — ${aid} is up: ${here[*]}"
  done <<<"${plan}"
fi
if [ -n "${held}" ]; then
  say "nothing updated — ${named_apps:-$*} keeps the image it runs: the provider${held} did not come up (above)"
  exit 1
fi
set -- "${order[@]}"
named_up() {   # svc — a named app is no longer pending once EVERY service of it compiled here is up (the provider
  # loop's rule): «nothing to apply» over a crashed first start, or one service of three, is not up
  local row aid s here=()
  row="$(printf '%s\n' "${plan:-}" | awk -v s="$1" '$1 == "named" && $2 == s {print; exit}')"
  [ -n "${row}" ] || return 0
  set -- ${row}
  aid="${3:--}"; [ "${aid}" != "-" ] || return 0
  shift 4
  for s in "$@"; do [[ "${declared:-}" == *" ${s} "* ]] && here+=("${s}"); done
  [ "${#here[@]}" -gt 0 ] && POLL=0 wait_up 0 "${here[@]}" >/dev/null && drop_pending "${aid}"
  return 0
}

for svc in "$@"; do
  cid="$(dc ps -a -q "${svc}" 2>/dev/null | head -n1)"
  before=""; ref=""
  if [ -n "${cid}" ]; then
    before="$(running_image "${cid}")"
    ref="$(container_image_name "${cid}")"
  fi
  say "== ${svc}"
  log="$(mktemp)"
  if ! dc build "${svc}" >"${log}" 2>&1; then
    say "  build FAILED — last lines:"; tail -5 "${log}" | sed 's/^/    /'; bad=1; rm -f "${log}"; continue
  fi
  rm -f "${log}"
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
    named_up "${svc}"
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
      say "  previous image back if the new one is not healthy, and names whoever it cut mid-turn;"
      say "  the log is data/${svc}/self-update.log"
      continue
    fi
    say "  ${svc} ships a self-update door but it did not take the recreate; falling back to compose"
  fi
  # NOT --no-deps: compose starts the service's own dependencies with it — its database, its one-shot init and
  # migrate containers (glitchtip-migrate, mailserver-init), which an update must run — and recreates one whose
  # definition changed. A dependency's own compose file always reached this from the checkout; the compile
  # above adds only what the compiler lays over it (routing labels, the broker).
  urc=0; out="$(dc up -d --force-recreate "${svc}" 2>&1)" || urc=$?
  printf '%s\n' "${out}" | tail -3 | sed 's/^/  /'
  # 75: its app is at work, and the bring-up held the recreate (lib.sh compose_when_idle_up, DGO-2129). The old
  # container runs on healthy, so the health check below would read as a success: said, left pending, not ok.
  if [ "${urc}" -eq 75 ]; then
    say "  held — ${svc}'s app is at work, so it was not recreated: follow brings it up at a quiet cycle (BBOX_RECREATE_BUSY=1 goes now)"
    bad=1; continue
  fi
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
    named_up "${svc}"
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
