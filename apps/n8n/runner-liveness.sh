#!/bin/sh
# n8n TASK-RUNNER liveness probe -- PROGRESS-based, not process-based.
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-18 `n8n-worker-2`'s runner sidecar went deaf. The Go launcher was fine, the Node
# runner process was alive at 0.05% CPU, the container reported `healthy` for 35 minutes, and
# worker-2 logged 4,125 `took too long to acknowledge acceptance of task` lines while completing
# almost nothing. The cycle was fired 11 minutes AFTER the runner went deaf, so it ran at roughly
# half runner capacity from the start and nothing said so. Restarting that one sidecar by hand
# took it from 0.09% to 99.29% CPU.
#
# WHAT WAS MISSED THE FIRST TIME
# ------------------------------
# `worker-liveness.sh` was written for this exact failure shape one layer up (worker-1,
# 2026-08-10), and its whole argument is that `/healthz` cannot see a wedge because it only proves
# an event loop is turning. That reasoning was applied ONLY to the worker. The runner sidecar
# shipped with `wget -q --spider http://127.0.0.1:5680/healthz` -- the very probe we had just
# proven worthless, one layer down. The launcher's health server has a single route returning a
# static `{"status":"ok"}` (verified against the running binary), so it answers 200 whenever the
# LAUNCHER is alive. The launcher was never the broken part.
#
# THE SECOND MISS, AND WHY THIS FILE DOES NOT USE THE EVENT LOG AS ITS DEMAND SIGNAL
# ---------------------------------------------------------------------------------
# The first version of THIS file counted n8n's own event-bus pairs -- `n8n.runner.task.requested`
# vs `n8n.runner.response.received` -- and called a growing gap a wedge. That is wrong, and the
# running source says why (`dist/task-runners/task-managers/task-requester.js`):
#
#     const taskId = await taskIdPromise;              // line 82: BLOCKS until a runner ACCEPTS
#     ...
#     this.eventService.emit('runner-task-requested',  // line 94: only emitted AFTER that
#
# A deaf runner never accepts, so `taskIdPromise` never resolves and NO EVENT IS EVER WRITTEN.
# During a wedge the counters do not diverge -- they FREEZE. Replaying the real 2026-08-18 worker
# event log through that arithmetic confirmed it: 906 requested, 906 received, zero imbalance
# across the entire incident window. The probe would have reported "idle/clear" throughout.
# The lesson is the same one as above: a signal that looks like demand is not demand until it has
# been checked against the failure it is supposed to catch.
#
# WHAT THIS CHECKS INSTEAD -- and why it is only sound because AUTO_SHUTDOWN is at its default
# --------------------------------------------------------------------------------------------
# The launcher kills an idle runner after `N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT` seconds (upstream
# default 15, read out of the launcher binary: `AutoShutdownTimeout env:"...", default=15`; this
# deployment carried an unexplained 300 until 2026-08-18). Observed live on this box: two
# `Runner process exited on idle timeout` lines in 45 minutes. That gives a hard invariant:
#
#     A HEALTHY RUNNER EITHER BURNS CPU OR CEASES TO EXIST.
#
# Idleness is not a state a runner sustains -- it is killed out of it within seconds. So a runner
# process that is ALIVE while consuming NO CPU for minutes is, by construction, neither working
# nor idle. That is the wedge, and it is visible entirely inside this container via /proc.
#
#   PID   = the JS runner process (absent = launcher idle-killed it = the healthy resting state)
#   TICKS = utime+stime from /proc/<pid>/stat -- monotonic CPU actually consumed
#   OUT   = task.requested - response.received, from n8n's event log
#
# VERDICT, in order:
#   no runner process   -> healthy. Idle-killed. This is the normal resting state at a 15s
#                          timeout and must never be a fault, or every quiet minute is an alarm.
#   TICKS advanced      -> healthy, stall clock RESETS. The runner is demonstrably computing.
#   PID changed         -> healthy, clock resets. A relaunch is not a wedge.
#   OUT > 0             -> healthy. A task WAS accepted and has not answered yet. This is the
#                          false-positive guard that makes a modest GRACE safe: a code node
#                          awaiting an RPC back to n8n (an HTTP helper call, say) legitimately
#                          burns no CPU for a long time -- but its task was accepted, so the
#                          event log shows it outstanding. A DEAF runner accepts nothing, so its
#                          OUT is exactly 0. This is the one thing the event log can tell us
#                          reliably, and it is used only for that.
#   otherwise, for      -> WEDGED: alive, not computing, holding no accepted work, for far longer
#   GRACE seconds          than the launcher would have let it idle.
#
# GRACE is held above AUTO_SHUTDOWN + 120s automatically, so raising the idle timeout can never
# turn a legitimately-resting runner into a false positive.
#
# FAIL-OPEN: every probe-side failure (no /proc entry, unreadable stat, unparseable counts, a
# counter that went BACKWARDS because the log rotated) exits 0 and rewrites state fresh. This is
# not politeness -- worker-liveness.sh shipped a rotation bug that made it a 100% false positive
# on BOTH workers, and anything acting on that verdict would have restarted two healthy workers in
# a loop forever. A verdict of "wedged" must be a MEASUREMENT, never the absence of evidence.
#
# COST: one `ps`, one `/proc` read, two `grep -c` passes. `sh` + busybox deliberately, not node:
# the host is memory-constrained (6 cores / ~10 GiB with the estate resident) and worker-liveness.sh
# measured the node form at 3.10s wall and 66.7 MB RSS per invocation versus ~0.01s and ~1 MB here.

set -u

# The n8n event log written by the process this sidecar serves. A GLOB, not a path -- the event
# bus rotates by renaming, and reading a fixed name is precisely the bug worker-liveness.sh
# shipped with. NOTE: n8n APPENDS `-worker` to N8N_EVENTBUS_LOGWRITER_LOGBASENAME on worker
# processes, so basename `n8nEventLog-w1` produces the file `n8nEventLog-w1-worker.log`.
LOG_GLOB=${RUNNER_LIVENESS_LOG_GLOB:-/n8n-data/n8nEventLog-worker*.log}
STATE=${RUNNER_LIVENESS_STATE:-/tmp/runner-liveness.state}
# Pattern identifying the runner process this sidecar owns.
RUNNER_PAT=${RUNNER_LIVENESS_PROCESS:-task-runner-javascript}

IDLE=${N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT:-15}
case "$IDLE" in ''|*[!0-9]*) IDLE=15 ;; esac
GRACE=${RUNNER_LIVENESS_GRACE_SECONDS:-240}
case "$GRACE" in ''|*[!0-9]*) GRACE=240 ;; esac
# Never let GRACE fall to or below the window in which a runner may legitimately sit idle.
MIN_GRACE=$((IDLE + 120))
[ "$GRACE" -lt "$MIN_GRACE" ] && GRACE=$MIN_GRACE

NOW=$(date +%s)

# --------------------------------------------------------------------------- is a runner alive?
PID=$(ps -o pid,args 2>/dev/null | grep "$RUNNER_PAT" | grep -v grep | head -1 | awk '{print $1}')
case "${PID:-}" in ''|*[!0-9]*) PID='' ;; esac

if [ -z "$PID" ]; then
  echo "runner-liveness: OK no runner process (idle-killed at ${IDLE}s - the healthy resting state)"
  rm -f "$STATE" 2>/dev/null
  exit 0
fi

STAT=/proc/$PID/stat
if [ ! -r "$STAT" ]; then
  echo "runner-liveness: SKIP cannot read $STAT - failing open"
  rm -f "$STATE" 2>/dev/null
  exit 0
fi
# fields 14,15 = utime,stime in clock ticks. Monotonic for the life of the process.
TICKS=$(awk '{print $14+$15}' "$STAT" 2>/dev/null)
case "${TICKS:-}" in ''|*[!0-9]*) TICKS='' ;; esac
if [ -z "$TICKS" ]; then
  echo "runner-liveness: SKIP unparseable $STAT - failing open"
  rm -f "$STATE" 2>/dev/null
  exit 0
fi

# ------------------------------------------------- accepted-but-unanswered work, from n8n itself
REQ=0; RES=0; FOUND=0
for f in $LOG_GLOB; do
  [ -f "$f" ] && [ -r "$f" ] || continue
  FOUND=$((FOUND + 1))
  r=$(grep -c 'n8n\.runner\.task\.requested' "$f" 2>/dev/null) || r=0
  s=$(grep -c 'n8n\.runner\.response\.received' "$f" 2>/dev/null) || s=0
  case "$r" in ''|*[!0-9]*) r=0 ;; esac
  case "$s" in ''|*[!0-9]*) s=0 ;; esac
  REQ=$((REQ + r)); RES=$((RES + s))
done
OUT=$((REQ - RES))
# No event log is a PROBE failure, not a runner failure: without it the RPC-wait guard below is
# blind, and a probe that cannot exclude its own false positive must not accuse.
if [ "$FOUND" -eq 0 ]; then
  echo "runner-liveness: SKIP no event log matching $LOG_GLOB - failing open"
  rm -f "$STATE" 2>/dev/null
  exit 0
fi

# ------------------------------------------------------------------------------- previous probe
P_PID=''; P_TICKS=-1; P_SINCE=$NOW
if [ -f "$STATE" ]; then
  # state format: "<pid> <ticks> <epoch-when-ticks-last-advanced>"
  read -r P_PID P_TICKS P_SINCE _ < "$STATE" 2>/dev/null || { P_PID=''; P_TICKS=-1; P_SINCE=$NOW; }
  case "${P_PID:-}"   in ''|*[!0-9]*)  P_PID=''     ;; esac
  case "${P_TICKS:-}" in ''|*[!0-9-]*) P_TICKS=-1   ;; esac
  case "${P_SINCE:-}" in ''|*[!0-9]*)  P_SINCE=$NOW ;; esac
fi

# A different pid means the launcher relaunched the runner. Not a wedge; start measuring afresh.
# Ticks going backwards means the same (pid reuse or an unreadable previous sample).
if [ "$P_PID" != "$PID" ] || [ "$P_TICKS" -lt 0 ] || [ "$TICKS" -lt "$P_TICKS" ]; then
  P_SINCE=$NOW
elif [ "$TICKS" -gt "$P_TICKS" ]; then
  P_SINCE=$NOW
fi
echo "$PID $TICKS $P_SINCE" > "$STATE" 2>/dev/null

STALLED=$((NOW - P_SINCE))
[ "$STALLED" -lt 0 ] && STALLED=0

# ------------------------------------------------------------------------------------- verdict
if [ "$OUT" -gt 0 ]; then
  echo "runner-liveness: OK $OUT task(s) accepted and in flight (pid=$PID ticks=$TICKS stalled=${STALLED}s)"
  exit 0
fi

if [ "$STALLED" -lt "$GRACE" ]; then
  echo "runner-liveness: OK running (pid=$PID ticks=$TICKS stalled=${STALLED}s < ${GRACE}s, req=$REQ res=$RES)"
  exit 0
fi

echo "runner-liveness: WEDGED pid=$PID alive with no CPU for ${STALLED}s and no accepted work (ticks=$TICKS req=$REQ res=$RES idle_timeout=${IDLE}s grace=${GRACE}s)"
exit 1
