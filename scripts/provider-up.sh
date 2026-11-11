#!/usr/bin/env bash
# provider-up.sh — bring ONE provider app up the way a bring-up brings an app up: its `prepare` hook, its images, its
# containers alone, a wait as long as its own first start may take, its `onboard` hook.
#
#     bash scripts/provider-up.sh <root> <app id> <seconds> <service>…
#
# The one implementation of that step for the two doors that bring a provider up without a whole `bbox run`:
#   * `bbox update <app>` (scripts/app-update.sh) SOURCES this file, for a provider the checkout newly requires
#     (DGO-1583); it builds the images from the checkout it applies;
#   * the apps screen's enable (platform-base/app-management/app.py, `_provider_up`) RUNS it, for a provider the app it
#     switches on needs and that has no container (DGO-1496), with PROVIDER_UP_BUILD=missing: it starts what is there.
# WHICH provider each door brings up is that door's own rule, and so is what it does first (the update also runs
# env-secrets); HOW one comes up is this file's, so the two can never drift apart.
#
# <seconds> is the time its first start may take (its manifest's `progress_deadline_seconds`, else 600: the `provider`
# row of scripts/app-update-plan.py); the wait is the larger of that and APP_UPDATE_TIMEOUT (240). Only the services
# named are built and started (`--no-deps`): what they depend on is up already or comes first in the plan's order, and
# a sibling that runs is never recreated by this. The wait counts a run-once service that finished (exit 0) as done,
# and an exit, or a container restarting again and again, as failed. A hook that fails is said and fails nothing.
# Exit 0: up. 1: not up (the last lines say why). 3: up, and one of its hooks failed (said). 2: usage.
#
# Sourced, it only defines provider_hook, wait_up and bring_up: the caller supplies REPO, dc, say, TIMEOUT, POLL and
# bad, as app-update.sh does.

provider_hook() {   # root aid verb → 0 when the app has no such hook or it succeeded
  local hook="${REPO}/$1/$2/hooks/$3" rc
  [ -e "${hook}" ] || return 0
  [ -x "${hook}" ] || { say "  $2: its $3 hook is not executable — NOT run (chmod +x $1/$2/hooks/$3)"; return 1; }
  # run as run_app_hooks runs it: its own output, not through a pipe (a hook that asks at the terminal is seen)
  rc=0; bash "${hook}" </dev/null || rc=$?
  [ "${rc}" -eq 0 ] || say "  $2: its $3 hook FAILED (exit ${rc})"
  return "${rc}"
}

wait_up() {   # seconds service… → 0 when each runs healthy, runs with no healthcheck, or is a run-once that exited 0
  local limit="$1" waited=0 s cid st restarts stuck; shift
  local left=("$@") next
  while :; do
    next=(); stuck=""
    for s in "${left[@]}"; do
      cid="$(dc ps -a -q "${s}" 2>/dev/null </dev/null | head -n1)"
      st="$( [ -n "${cid}" ] && docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} {{.State.ExitCode}}' "${cid}" 2>/dev/null)"
      restarts="$( [ -n "${cid}" ] && docker inspect -f '{{.RestartCount}}' "${cid}" 2>/dev/null)"
      case "${st}" in
        "running healthy "*|"running  "*|"exited "*" 0") ;;
        "exited "*|dead*) say "  ${s}: ${st}"; return 1 ;;
        # a first start may restart once or twice, or read unhealthy before its migrations end (app-management
        # waits through that too); a crash loop is not a start
        *) if [ "${restarts:-0}" -ge 3 ] 2>/dev/null; then say "  ${s}: restarted ${restarts} times (${st})"; return 1; fi
           next+=("${s}"); stuck="${stuck} ${s} (${st:-no container})" ;;
      esac
    done
    [ "${#next[@]}" -gt 0 ] || return 0
    [ "${waited}" -lt "${limit}" ] || { say "  not up after ${limit}s:${stuck}"; return 1; }
    # a round counts 5 s; APP_UPDATE_POLL only shortens the real sleep (the test plays the clock with 0)
    sleep "${POLL}"; waited=$(( waited + 5 )); left=("${next[@]}")
  done
}

bring_up() {   # root aid seconds service… → 0 when its containers are up; the build log and compose's words on failure
  local root="$1" aid="$2" limit="$3" out log; shift 3
  [ "${TIMEOUT}" -gt "${limit}" ] && limit="${TIMEOUT}"
  provider_hook "${root}" "${aid}" prepare || bad=1
  # PROVIDER_UP_BUILD=missing (the enable): no build of its own — `up` builds an image only when it is missing, as
  # the enable's `_install` does; the update builds from the checkout it applies (the default)
  if [ "${PROVIDER_UP_BUILD:-always}" != missing ]; then
    log="$(mktemp)"
    # </dev/null: this runs inside the loop that reads the plan, and a command that reads stdin would eat it
    if ! dc build "$@" >"${log}" 2>&1 </dev/null; then
      say "  build FAILED — last lines:"; tail -5 "${log}" | sed 's/^/    /'; rm -f "${log}"; return 1
    fi
    rm -f "${log}"
  fi
  out="$(dc up -d --no-deps "$@" 2>&1 </dev/null)" || { printf '%s\n' "${out}" | tail -5 | sed 's/^/  /'; return 1; }
  # what the engine's own steps did beside it (a container recreated for a mount or a namespace) is said
  printf '%s\n' "${out}" | grep -F '[bbox]' | sed 's/^/  /' || true
  wait_up "${limit}" "$@" || return 1
  provider_hook "${root}" "${aid}" onboard || bad=1
}

# ── run, not sourced: one provider, from the checkout this file sits in ───────────────────────────────────────────
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -uo pipefail
  usage="usage: provider-up.sh <root> <app id> <seconds> <service>…"
  [ "$#" -ge 4 ] || { echo "${usage}" >&2; exit 2; }
  case "$3" in ''|*[!0-9]*) echo "${usage} (<seconds> is whole seconds, got '$3')" >&2; exit 2 ;; esac
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  cd "${REPO}" || exit 1
  # what a hook or the compiler prints may be Hebrew: UTF-8 io, or Windows dies (G10)
  export PYTHONIOENCODING=utf-8
  TIMEOUT="${APP_UPDATE_TIMEOUT:-240}"
  case "${TIMEOUT}" in ''|*[!0-9]*) TIMEOUT=240 ;; esac
  # the door's choice stays this script's: a hook it runs (one that ran `bbox update`, say) does not inherit it
  PROVIDER_UP_BUILD="${PROVIDER_UP_BUILD:-always}"; export -n PROVIDER_UP_BUILD
  POLL="${APP_UPDATE_POLL:-5}"
  bad=0
  # through bash: a checkout mounted without its exec bits (a Windows drive) still runs it, as app-management's
  # own calls of scripts/dc do
  dc() { bash "${REPO}/scripts/dc" "$@"; }
  say() { printf '%s\n' "$*"; }
  bring_up "$@" || exit 1
  say "  ok — $2 is up: ${*:4}"
  [ "${bad}" -eq 0 ] || exit 3
  exit 0
fi
