#!/usr/bin/env bash
# postjob.sh — the runner's ACTIONS_RUNNER_HOOK_JOB_COMPLETED inside ci-runner-agent: the job's end, on the screen
# «מריץ CI» and on the office's stream (DGO-1797), and the office's heavy-job slot given back (prejob.sh took it;
# scripts/ops/heavy-hold.sh). The runner does not hand the hook the job's result; the screen reads it from GitHub
# (its runs), so this line says only that the job left the machine, and when — and whether its holder was still
# there to give back («not held at the end» = it ended with the job's worker first, which is also fine).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOLD="${CI_RUNNER_HOLD:-/opt/dgo/heavy-hold.sh}"
# the same paths as prejob.sh's, set here and never in the agent's environment (prejob.sh says why)
export HEAVY_LOCKS="${CI_RUNNER_LOCKS:-/data/locks}" \
       HEAVY_HOLD_PIDFILE="${CI_RUNNER_HOLD_PIDFILE:-${CI_RUNNER_STATE:-/state}/heavy.hold.pid}"
# only as the runner's own hook (its parent is the job's worker) — prejob.sh says why a step never touches the slot
WORKER_COMM="${CI_RUNNER_WORKER_COMM:-Runner.Worker}"
is_hook() { [ "${CI_RUNNER_SLOT:-}" = on ] || [ "$(cat "/proc/${PPID}/comm" 2>/dev/null)" = "${WORKER_COMM:0:15}" ]; }
slot=""
if [ -r "${HOLD}" ] && is_hook; then
  case "$(bash "${HOLD}" stop 2>/dev/null)" in
    released*) slot=" · the heavy-job slot given back" ;;
    *)         slot=" · the heavy-job slot was not held at the end" ;;
  esac
fi
python3 "${HERE}/record.py" ended 0 "$(awk '/MemAvailable/ {printf "%d MB available", $2/1024}' /proc/meminfo)${slot}" || true
exit 0
