#!/usr/bin/env bash
# prejob.sh — the runner's ACTIONS_RUNNER_HOOK_JOB_STARTED inside ci-runner-agent: a job passes the office's door
# before it runs, and the screen «מריץ CI» sees it wait and start (DGO-1797).
#
# THE SLOT FIRST: one heavy job at a time on this machine, whichever door it came through — a bbox build, a recreate,
# the emulator, this runner. It is the office's own (scripts/lib.sh heavy_admit's flock, its directory mounted at
# /data/locks), and a holder process holds it from here to postjob.sh (scripts/ops/heavy-hold.sh): the hook itself
# exits before the job begins. The holder ends with the job's Runner.Worker, so a job whose end hook never ran, or
# whose listener died, keeps nothing; and the next job's start ends a holder the last one left.
# THEN THE MACHINE, under the slot (as heavy_admit waits for memory once it holds it): memory (what decides whether
# the job can succeed), the CPU package's heat and a fresh boot (the Dell froze three times with memory to spare,
# DGO-1122). The memory a job needs is its workflow's CLASS (classes.yaml) at the office's own figure for that class
# (scripts/ops/admission-thresholds.sh, mounted read-only — one source for every gate on the machine).
# THE DESK is said, not waited for (the readiness rule's stage 2, scripts/ops/heavy-ready.sh): «would wait».
# A PAUSE is not a condition here: the agent stops the listener between jobs (agent.sh), so a paused runner takes no
# job at all and the jobs stay queued for another; a job that reached this hook was assigned before the pause and
# runs. Both waits share one bound, CI_WAITFREE_TIMEOUT (45 min); a job refused at the door gives the slot back.
# The runner runs this hook as `bash -e {0}` (actions/runner's ScriptHandler): every exit status is caught here.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLASSES="${CI_RUNNER_CLASSES:-${HERE}/classes.yaml}"
THRESHOLDS="${CI_RUNNER_THRESHOLDS:-/opt/dgo/admission-thresholds.sh}"
HOLD="${CI_RUNNER_HOLD:-/opt/dgo/heavy-hold.sh}"
READY="${CI_RUNNER_READY:-/opt/dgo/heavy-ready.sh}"
# The slot's paths are set HERE, never in the agent's environment: every job step inherits that one, and a test a
# job runs (G72 runs this app's own) found the office's real slot through it and gave the running job's slot away
# (the second reader, measured). The holder lasts at most 2 h — under bbox's own 3-h wait — whatever else happens.
export HEAVY_LOCKS="${CI_RUNNER_LOCKS:-/data/locks}" \
       HEAVY_HOLD_PIDFILE="${CI_RUNNER_HOLD_PIDFILE:-${CI_RUNNER_STATE:-/state}/heavy.hold.pid}" \
       HEAVY_DESK="${CI_RUNNER_DESK:-/data/power/desk.json}" HEAVY_HOLD_MAX_S="${CI_RUNNER_HOLD_MAX_S:-7200}"
# shellcheck source=/dev/null
[ -r "${THRESHOLDS}" ] && . "${THRESHOLDS}"
TIMEOUT_S="${CI_WAITFREE_TIMEOUT:-2700}"
POLL_S=15
MAX_START_C="${CI_MAX_START_C:-80}"
MIN_UPTIME_S="${CI_MIN_UPTIME_S:-600}"
WF="${GITHUB_WORKFLOW:-}"

class() {
  awk -v wf="${WF}" -F': *' '
    /^[[:space:]]*#/ || NF < 2 { next }
    $1 == wf { found = $2 } $1 == "default" { dflt = $2 }
    END { v = (found != "" ? found : dflt); print (v == "" ? "stack" : v) }' "${CLASSES}" 2>/dev/null || echo stack
}
CLASS="$(class)"
case "${CLASS}" in
  light) NEED_GB="$(( (${ADMISSION_MIN_AVAIL_MIB:-1536} + 1023) / 1024 ))" ;;
  *)     NEED_GB="${ADMISSION_STACK_MIN_AVAIL_GB:-6}" ;;
esac
NEED_GB="${CI_WAITFREE_GB:-${NEED_GB}}"

pkg_c() {
  for z in /sys/class/thermal/thermal_zone*; do
    if [ "$(cat "$z/type" 2>/dev/null)" = x86_pkg_temp ]; then
      t=$(cat "$z/temp" 2>/dev/null) && [ -n "$t" ] && { echo $((t / 1000)); return; }
    fi
  done
  echo 0
}
up_s()     { awk '{printf "%d", $1}' /proc/uptime; }
avail_mb() { awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo; }
fits()     { [ "$(avail_mb)" -ge $(( NEED_GB * 1024 )) ]; }
ready()    { fits && [ "$(pkg_c)" -lt "${MAX_START_C}" ] && [ "$(up_s)" -ge "${MIN_UPTIME_S}" ]; }
state()    { echo "$(avail_mb) MB available (need ${NEED_GB} GB, class ${CLASS}), CPU $(pkg_c)°C (under ${MAX_START_C}), up $(up_s)s (at least ${MIN_UPTIME_S})"; }

# one line of the job's record (the screen reads jobs.jsonl) and one event on the office's stream (flow.v1)
record() { python3 "${HERE}/record.py" "$@" || true; }

# the job's worker process (its name a setting only so a test names its own stand-in, never the real one)
WORKER_COMM="${CI_RUNNER_WORKER_COMM:-Runner.Worker}"
WORKER_COMM="${WORKER_COMM:0:15}"                          # /proc/<pid>/comm holds 15 characters

# the job's worker — the nearest ancestor of this hook by that name — for the holder to end with
worker_pid() {
  local p="$$" i comm
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    p="$(awk '/^PPid:/ {print $2}' "/proc/${p}/status" 2>/dev/null)" || p=""
    [ -n "${p}" ] && [ "${p}" -gt 1 ] 2>/dev/null || return 0
    comm="$(cat "/proc/${p}/comm" 2>/dev/null)" || comm=""
    [ "${comm}" = "${WORKER_COMM}" ] && { echo "${p}"; return 0; }
  done
}
# THE HOOK, OR NOT: the runner starts its hooks itself, so their PARENT is the job's worker. A step that runs this
# file by hand — a test G72 runs as a step of a job on this very runner — is a grandchild of it at best, and must
# never touch the office's slot, whose holder the running job holds (the second reader measured a step's postjob.sh
# freeing it). CI_RUNNER_SLOT=on says otherwise for a test that brings a slot of its own.
is_hook() { [ "${CI_RUNNER_SLOT:-}" = on ] || [ "$(cat "/proc/${PPID}/comm" 2>/dev/null)" = "${WORKER_COMM}" ]; }
slot() { bash "${HOLD}" status 2>/dev/null || echo "?"; }

t0=${SECONDS}
waited=0
held=""
if [ -r "${HOLD}" ] && ! is_hook; then
  echo "prejob: not started by the runner as a job's hook — the office's heavy-job slot is not touched"
elif [ -r "${HOLD}" ]; then
  bash "${HOLD}" stop >/dev/null 2>&1 || true            # a holder the last job left: that job is over
  busy="$(slot)"
  if [ "${busy}" != free ]; then
    echo "prejob: the office's heavy-job slot is held — waiting: ${busy}"
    record waiting 0 "the heavy-job slot is held by: ${busy}"
  fi
  sha="${GITHUB_SHA:-}"
  wpid="$(worker_pid)" || wpid=""
  rc=0
  HEAVY_HOLD_WHILE="${wpid}" bash "${HOLD}" start "ci ${WF:-job} · ${sha:0:9} · run ${GITHUB_RUN_ID:-?}" "${TIMEOUT_S}" \
    || rc=$?
  case ${rc} in
    0) held=" · holding the heavy-job slot"
       [ -n "${wpid}" ] || held="${held} (the job's worker was not found: held at most ${HEAVY_HOLD_MAX_S} s)" ;;
    1) waited=$(( SECONDS - t0 ))
       echo "prejob: FAILING after ${waited}s — the office's heavy-job slot never freed: $(slot)" >&2
       record refused "${waited}" "the heavy-job slot stayed held by: $(slot)"
       exit 1 ;;
    3) echo "prejob: no flock or setsid here — this job runs without the office's heavy-job slot" >&2 ;;
    *) echo "prejob: the office's heavy-job slot cannot be opened here — this job runs without it" >&2 ;;
  esac
  waited=$(( SECONDS - t0 ))
else
  echo "prejob: no heavy-job holder mounted (${HOLD}) — this job runs without the office's slot" >&2
fi

if ! ready; then
  echo "prejob: this machine cannot take the job yet — waiting: $(state)"
  record waiting "${waited}" "$(state)"
  said=$(( waited / 300 ))
  while [ "${waited}" -lt "${TIMEOUT_S}" ]; do
    sleep "${POLL_S}"; waited=$(( SECONDS - t0 ))
    ready && break
    if [ $(( waited / 300 )) -gt "${said}" ]; then                 # every 5 minutes, whatever a poll took
      said=$(( waited / 300 ))
      echo "prejob:   still waiting (${waited}s): $(state)"; record waiting "${waited}" "$(state)"
    fi
  done
fi
if ! ready; then
  echo "prejob: FAILING after ${TIMEOUT_S}s — the machine never freed up: $(state)" >&2
  record refused "${waited}" "$(state)"
  [ -z "${held}" ] || bash "${HOLD}" stop >/dev/null 2>&1
  exit 1
fi
# the desk: said, not waited for — what the readiness rule WOULD hold this job for (its stage 2, AGENTS rule 8)
if [ -r "${READY}" ]; then
  would="$( . "${READY}" 2>/dev/null && HEAVY_RESERVE_MB=0 HEAVY_MIN_UPTIME_S=0 HEAVY_MAX_START_C=1000 \
            heavy_ready_why "$(( NEED_GB * 1024 ))" 2 2>/dev/null )" || would=""
  [ -z "${would}" ] || echo "prejob: under the readiness rule this job would wait (warn only — it starts now): ${would}"
  # …and one line of the office's readiness record, in heavy_admit's own format (scripts/lib.sh heavy_would_note:
  # «utc \t label \t what it would wait for, or -»), so the week stage 3 is decided from counts the runner's jobs too.
  # Only when this job holds the office's slot (the record lives beside it); appended, never trimmed here (heavy_admit
  # trims in place); made world-writable if this root container is the first to write it.
  if [ -n "${held}" ] && [ -d "${HEAVY_LOCKS}" ]; then
    rec="${HEAVY_LOCKS}/heavy.would"
    if [ ! -L "${rec}" ] && { [ ! -e "${rec}" ] || [ -f "${rec}" ]; }; then   # a regular file, never a link
      [ -e "${rec}" ] || ( umask 000; : >> "${rec}" ) 2>/dev/null || true
      { printf '%s\t%s\t%s\n' "$(date -u '+%FT%TZ')" \
          "$(printf '%s' "ci ${WF:-job} · run ${GITHUB_RUN_ID:-?}" | tr '\t\n' '  ' | head -c 120)" \
          "$(printf '%s' "${would:--}" | tr '\t\n' '  ' | head -c 300)" >> "${rec}"; } 2>/dev/null || true
    fi
  fi
fi
echo "prejob: starting after ${waited}s ($(state))${held}"
record started "${waited}" "$(state)${held}"
exit 0
