#!/usr/bin/env bash
# agent.sh — the runner's life inside ci-runner-agent: a small supervisor around GitHub's listener (DGO-1797).
#
# What it keeps true:
#   * a registration on the volume (/state/registration: .runner, .credentials, .credentials_rsaparams — the
#     runner's identity on GitHub, never printed) is what the listener runs with, copied in once per listener start;
#     none → it says so and waits, and a registration placed later is taken without a restart;
#   * PAUSED (/state/paused, written by the screen's server) means the listener is stopped BETWEEN jobs — the job
#     running finishes, and the next ones stay QUEUED on GitHub, where another runner with the labels can take them.
#     While pausing it looks every second, so a job ending is not followed by the next one; in the second between a
#     job's end and the stop ONE more job can still be assigned — it either runs (its worker started first) or is
#     cancelled by the stop (said on the screen);
#   * a heartbeat (/state/agent.json: state, listener alive or not, a job running or not, the time) every round,
#     back-offs included — the screen reads a heartbeat older than a minute as «not running».
#
# THE LISTENER RUNS IN A PROCESS GROUP OF ITS OWN (setsid), and is stopped with SIGTERM to that group: a command a
# script starts with `&` ignores SIGINT (POSIX), and a signal to run.sh alone never reaches Runner.Listener under
# it. Every wait on it is bounded. A `docker stop` gives the job running the compose's stop_grace_period; a job
# still running when it ends is lost — say so before stopping the agent mid-job.
#
# THE WORK FOLDER IS ON THE HOST, AT THE SAME PATH. Jobs drive the office's engine through its socket, so a bind
# mount a job asks for (`docker run -v "$RUNNER_TEMP/x:/y"`, a compose's relative volume) is resolved by the engine
# on the HOST. The runner's work folder (and $RUNNER_TEMP under it) is therefore a host directory mounted here at
# the identical path (compose: CI_RUNNER_WORK), and the registration's work folder is pointed at it.
set -uo pipefail
STATE="${CI_RUNNER_STATE:-/state}"
REG="${STATE}/registration"
WORK="${CI_RUNNER_WORK:?the compose names the work folder, the same path on the host and here}"
RUNNER="${CI_RUNNER_HOME:-/runner}"
TICK="${CI_RUNNER_TICK:-10}"
mkdir -p "${REG}" "${WORK}" "${STATE}/toolcache"
say() { printf '%s ci-runner-agent: %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
LISTENER="" STARTED=0 FAILS=0

alive()   { [ -n "${LISTENER}" ] && kill -0 "${LISTENER}" 2>/dev/null; }
# the listener's GROUP: run.sh dies at once on a signal, Runner.Listener under it takes seconds to cancel its job
# and close its session with GitHub — a stop waits for the group, not for run.sh
group_alive() { [ -n "${LISTENER}" ] && kill -0 -- "-${LISTENER}" 2>/dev/null; }
# A job is a process named Runner.Worker — in the agent's container, its own (the PID namespace scopes it). The match
# is a setting only so a test on a host that is ITSELF a runner can name its own stand-in: there the host's real
# Runner.Worker (the job running the test) read as «a job», and a pause never came (the Dell's gates, 2026-11-11).
job_now() { pgrep -f -- "${CI_RUNNER_JOB_MATCH:-Runner.Worker}" >/dev/null 2>&1; }
# A TAKE THAT WANTS THE SLOT (scripts/follow.sh, DGO-2164): the office's follow holds the lock heavy.want, in the
# office's locks folder that prejob.sh's slot shares, for as long as its take needs the machine. Meanwhile the runner
# stands aside between jobs, as it does when paused: the running job finishes, the next ones wait on GitHub. It never
# writes /state/paused, which stays the screen's and the owner's. The kernel lets go of the lock with its holder,
# whatever ends it, so a killed take cannot keep the runner aside. «paused» on the heartbeat, which is what the screen
# then shows.
WANT="${CI_RUNNER_WANT:-${CI_RUNNER_LOCKS:-/data/locks}/heavy.want}"
# HELD is flock's conflict exit alone (-E 75): a lock it cannot even try (no flock, no access) never parks the runner
wanted() { [ -e "${WANT}" ] || return 1; flock -n -E 75 "${WANT}" true 2>/dev/null; [ "$?" = 75 ]; }

beat() {   # the screen's one source for «is it up»: written every round, read as stale after a minute
  printf '{"state":"%s","listener":%s,"job":%s,"at":"%s"}\n' "$1" "$(group_alive && echo true || echo false)" \
    "$(job_now && echo true || echo false)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE}/agent.json.tmp" && mv "${STATE}/agent.json.tmp" "${STATE}/agent.json"
}

registered() { [ -s "${REG}/.runner" ] && [ -s "${REG}/.credentials" ]; }

start_listener() {
  for f in .runner .credentials .credentials_rsaparams; do
    [ -s "${REG}/${f}" ] && cp -p "${REG}/${f}" "${RUNNER}/${f}"
  done
  # the work folder at the host path (a carried registration names `_work`, relative to the runner)
  if ! jq --arg w "${WORK}" '.workFolder = $w' "${RUNNER}/.runner" > "${RUNNER}/.runner.tmp" \
     || ! mv "${RUNNER}/.runner.tmp" "${RUNNER}/.runner"; then
    say "the registration's work folder could not be pointed at ${WORK} — not starting: a job's mounts would break"
    return 1
  fi
  # the hooks around every job; no office secret is in this environment — every job step inherits it
  ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/ci-runner/prejob.sh ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/ci-runner/postjob.sh \
  RUNNER_TOOL_CACHE="${STATE}/toolcache" AGENT_TOOLSDIRECTORY="${STATE}/toolcache" RUNNER_ALLOW_RUNASROOT=1 \
    setsid "${RUNNER}/run.sh" &
  LISTENER=$!
  STARTED=$(date +%s)
  say "listener started (process group ${LISTENER})"
}

# stop the listener's whole group: SIGTERM, up to `$1` seconds, then SIGKILL — never an unbounded wait
stop_listener() {
  group_alive || { LISTENER=""; return 0; }
  kill -TERM -- "-${LISTENER}" 2>/dev/null || kill -TERM "${LISTENER}" 2>/dev/null
  local i=0
  while group_alive && [ "${i}" -lt "${1:-30}" ]; do sleep 1; i=$((i + 1)); done
  group_alive && kill -KILL -- "-${LISTENER}" 2>/dev/null
  wait "${LISTENER}" 2>/dev/null
  LISTENER=""
}

# paused: stop it only between jobs, looking again right before the signal
pause_step() {
  group_alive || { LISTENER=""; return 0; }
  job_now && return 1
  sleep 1
  job_now && return 1                                       # a job was taken in that second: it runs, and finishes
  stop_listener 30
  if [ -e "${STATE}/paused" ]; then say "listener stopped between jobs (paused on the screen)"
  else say "listener stopped between jobs (the office's take wants the slot: ${WANT})"; fi
}

# the job door's worker (door.py, DGO-1797 package 9): it runs the named jobs a linked office asked for, one at a time,
# whether or not GitHub's listener runs or is registered (a pause is GitHub's; the door's v1 jobs are light read
# verbs). Looked at every round and started again when it ended — said, not silent.
DOOR="" DOOR_PY="${CI_RUNNER_DOOR:-/opt/ci-runner/door.py}"
# the checkout's path is the worker's alone: taken here and dropped from this environment BEFORE the listener starts,
# so no job step inherits it (the slot's paths are kept out the same way — prejob.sh says why)
DOOR_REPO="${CI_RUNNER_DOOR_REPO:-}"
unset CI_RUNNER_DOOR_REPO
door_up() {
  [ -r "${DOOR_PY}" ] || return 0
  [ -n "${DOOR}" ] && kill -0 "${DOOR}" 2>/dev/null && return 0
  if [ -n "${DOOR}" ]; then wait "${DOOR}" 2>/dev/null; say "the job door's worker ended (exit $?) — starting it again"; fi
  CI_RUNNER_DOOR_REPO="${DOOR_REPO}" python3 "${DOOR_PY}" work &
  DOOR=$!
}

on_term() {
  [ -z "${DOOR}" ] || kill -TERM "${DOOR}" 2>/dev/null
  say "stopping: the listener's group gets SIGTERM$(job_now && echo ' — a job is running and will be cancelled')"
  stop_listener 50                                          # inside the compose's 60 s stop_grace_period
  exit 0
}
trap on_term TERM INT

while :; do
  tick="${TICK}"
  door_up
  if ! registered; then
    beat unregistered
  elif [ -e "${STATE}/paused" ] || wanted; then
    if pause_step; then beat paused; else beat pausing; tick=1; fi
  elif group_alive; then                                    # run.sh may be gone while its listener still works
    beat running
  else
    if [ -n "${LISTENER}" ]; then
      # a listener that dies within a minute, three times running, is failing (a revoked registration, no network):
      # said on the screen, and tried again every five minutes instead of every round
      if [ $(( $(date +%s) - STARTED )) -lt 60 ]; then FAILS=$((FAILS + 1)); else FAILS=0; fi
      wait "${LISTENER}" 2>/dev/null; LISTENER=""
      say "the listener ended (${FAILS} quick end(s) in a row)"
    fi
    if [ "${FAILS}" -ge 3 ]; then
      for _ in $(seq 1 $((300 / TICK))); do beat failing; door_up; sleep "${TICK}" & wait $!; done
      FAILS=2                                               # one more quick end after the wait: back to the wait
      continue
    fi
    if start_listener; then beat running; else FAILS=3; beat failing; fi
  fi
  sleep "${tick}" & wait $!                                 # a trap fires at once, not after the sleep
done
