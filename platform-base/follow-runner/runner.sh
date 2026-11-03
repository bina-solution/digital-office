#!/usr/bin/env bash
# runner.sh — the follow cycle for an office whose `bbox` runs inside containers (r030-205, DGO-1233).
#
# WHY. scripts/follow.sh keeps an office on DGO_FOLLOW from a HOST systemd timer, and `bbox run` installs that timer —
# when it runs on the host. The HP is updated by its agent running `./bbox run` inside bina-ds, where there is no host
# systemd, so it never got the timer (measured 2026-11-03). Everything a cycle needs is reachable from a container —
# git on the checkout, `./bbox run` through the engine socket, `scripts/dc ps` — only the schedule was missing. This
# service is that schedule. On an office that has the host timer it is not enabled (platform.state.default.yaml).
#
# WHY A CYCLE OF ITS OWN. A cycle's `bbox run` may recreate this very service. A cycle running in here would die with
# it, and the next one would roll its take back as unverified — on every take that changes this app, for ever. So each
# cycle runs in a container of its own, `follow-cycle-<deployment>`, started from this service's own image with the
# checkout and the engine socket, outside compose (nothing `up --remove-orphans` touches). This loop only starts one
# when none runs; the engine refuses a second container of that name, and follow.sh holds its own flock besides.
#
# AS WHOM. Root, as bina-ds — the checkout's writer on such an office — is (FOLLOW_USER declares another). The cycle is
# kept after it ends, until the next start reads how it ended (a failure before follow.sh logs anything is not lost).
# THE GIT CREDENTIAL. Whatever the checkout's own git config carries; or, where the office declares it,
# DGO_FOLLOW_GIT_CREDENTIALS — a file ON THE HOST in git's `store` format, mounted read-only into the cycle alone.
# Measured: a container on vps1 has no git credential of its own (`git ls-remote` fails in its bina-ds).
set -uo pipefail
REPO="${BBOX_REPO_HOST:?BBOX_REPO_HOST is the path of the checkout on the host}"
DN="${DEPLOYMENT_NAME:-bina-deployment}"
SOCK_HOST="${BBOX_HOST_DOCKER_SOCK:-/var/run/docker.sock}"    # the socket's path ON THE HOST, for the cycle's -v
SOCK="${FOLLOW_SOCK:-/var/run/docker.sock}"                    # …and in here
NAME="follow-cycle-${DN}"
EVERY="${FOLLOW_EVERY:-1800}"
DOCKER="${FOLLOW_DOCKER:-docker}"
BEAT="${FOLLOW_HEARTBEAT:-/tmp/follow.heartbeat}"
say() { printf '%s [follow] %s\n' "$(date -u '+%F %T')" "$*"; }

# the office declares DGO_FOLLOW (its .env, read through the read-only mount); otherwise there is nothing to start
declared() { grep -Eq '^DGO_FOLLOW=[^[:space:]]' "${REPO}/.env" 2>/dev/null; }

start_cycle() {
  local img st code sg who=() cred=() git=(-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*')
  # an engine that does not answer is not "no cycle": nothing is started, and nothing removed, on a guess
  if ! st="$("${DOCKER}" ps -a --filter "name=^${NAME}\$" --format '{{.State}}' 2>/dev/null)"; then
    say "the engine did not answer \`docker ps\` — no cycle started"; return 1
  fi
  case "${st}" in
    "") ;;
    running|restarting|created|paused) say "a cycle is still running (${NAME})"; return 0 ;;
    *)  # the previous cycle, kept until now for exactly this: how it ended, and its last words when it failed
        code="$("${DOCKER}" inspect -f '{{.State.ExitCode}}' "${NAME}" 2>/dev/null)"
        say "the previous cycle ended with exit ${code:-?}"
        [ "${code:-0}" = 0 ] || "${DOCKER}" logs --tail 20 "${NAME}" 2>&1 | sed 's/^/    | /'
        "${DOCKER}" rm "${NAME}" >/dev/null 2>&1 || { say "could not remove the previous cycle (${NAME}) — no new one started"; return 1; } ;;
  esac
  img="$("${DOCKER}" inspect -f '{{.Image}}' "follow-runner-${DN}" 2>/dev/null)"
  [ -n "${img}" ] || { say "cannot read this service's own image — no cycle started"; return 1; }
  # AS WHOM: root by default — on an office operated from containers the checkout is written by bina-ds, as root, and a
  # uid that did not write git's objects or data/.locks cannot write them; the socket is root on the engine either way.
  # FOLLOW_USER=uid:gid declares another writer (it then gets the socket's group).
  if [ -n "${FOLLOW_USER:-}" ]; then
    sg="$(stat -c %g "${SOCK}")" || { say "cannot read the engine socket's group — no cycle started"; return 1; }
    who=(--user "${FOLLOW_USER}" --group-add "${sg}")
  fi
  if [ -n "${DGO_FOLLOW_GIT_CREDENTIALS:-}" ]; then
    # --mount, not -v: a -v whose source is missing makes the engine CREATE it, as a directory, on the host — at the
    # very path the host's git reads its credentials from. --mount refuses instead, and the cycle is not started.
    cred=(--mount "type=bind,source=${DGO_FOLLOW_GIT_CREDENTIALS},target=/tmp/follow-home/.git-credentials,readonly")
    git=(-e GIT_CONFIG_COUNT=2 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*'
         -e GIT_CONFIG_KEY_1=credential.helper -e GIT_CONFIG_VALUE_1=store)
  fi
  # `com.docker.compose.service=` (empty): the image compose built carries this service's labels, and a container
  # inherits them — so bbox would take the cycle for the `follow-runner` service itself and refuse the `up` it runs
  # (scripts/lib.sh, bbox_self_service). The project label stays: autoheal reads it, and binaos.max-age, for a cycle
  # that outlives `timeout`. 6 h is the host timer's TimeoutStartSec.
  if "${DOCKER}" run -d --name "${NAME}" --label binaos.follow-cycle=1 --label com.docker.compose.service= \
       --label binaos.max-age=21600 ${who[@]+"${who[@]}"} --network "${FOLLOW_NETWORK:-traefik-network}" \
       -v "${REPO}:${REPO}" -v "${SOCK_HOST}:/var/run/docker.sock" ${cred[@]+"${cred[@]}"} "${git[@]}" \
       -w "${REPO}" -e HOME=/tmp/follow-home -e REPO_ROOT="${REPO}" \
       -e BBOX_REPO_HOST="${REPO}" -e BBOX_DOCKER_SOCK=/var/run/docker.sock -e BBOX_HOST_DOCKER_SOCK="${SOCK_HOST}" \
       -e BBOX_HOST_TZ="${BBOX_HOST_TZ:-UTC}" -e DEPLOYMENT_NAME="${DN}" \
       "${img}" timeout -k 60 6h bash "${REPO}/scripts/follow.sh" >/dev/null; then
    say "cycle started (${NAME})"
  else
    say "the engine refused to start a cycle (${NAME})"; return 1
  fi
}

if [ "${FOLLOW_ONCE:-0}" = 1 ]; then          # one decision, then exit (tests/test_runner.sh)
  declared || { say "DGO_FOLLOW is not declared in ${REPO}/.env — nothing to follow"; exit 0; }
  start_cycle; exit $?
fi
touch "${BEAT}"
waited=0
while [ "${waited}" -lt "${FOLLOW_FIRST:-900}" ]; do sleep 30; waited=$((waited + 30)); touch "${BEAT}"; done
while :; do
  touch "${BEAT}"
  declared && start_cycle
  # every EVERY seconds, plus up to five minutes, so offices on one dgo-stable do not all pull at once
  waited=0; pause=$((EVERY + RANDOM % 300))
  while [ "${waited}" -lt "${pause}" ]; do sleep 30; waited=$((waited + 30)); touch "${BEAT}"; done
done
