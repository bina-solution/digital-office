#!/bin/sh
# n8n worker liveness probe -- PROGRESS-based, not process-based.
#
# WHY THIS EXISTS
# ---------------
# The healthcheck this replaced was `pgrep -f 'n8n worker' || exit 1`. That proves a process
# with a matching argv exists. It does not prove the worker is consuming Bull jobs. On
# 2026-08-10 `n8n-worker-1` stopped consuming jobs entirely at 08:19:42 UTC and processed ZERO
# executions for over two hours while burning ~77% CPU, and Docker reported it `healthy` the
# whole time. Effective queue capacity was silently halved (`bull:jobs:active` pinned at 8
# against 16 nameplate slots) while the Bull backlog grew past 2,400 jobs.
#
# WHY NOT n8n's OWN /healthz (QUEUE_HEALTH_CHECK_ACTIVE=true)
# ----------------------------------------------------------
# It has the same blind spot. Read out of the running image (n8n 2.17.0,
# dist/scaling/worker-server.js), the handler is a static literal:
#     this.app.get(healthPath, async (_, res) => { res.send({ status: 'ok' }); });
# It returns 200 whenever the express event loop can serve a request. The wedged worker was
# logging and renewing Bull locks throughout, so its event loop was turning and /healthz would
# have answered 200 for all two hours. `/healthz/readiness` is no better: it checks
# `connectionState.connected && connectionState.migrated && redisClientService.isConnected() &&
# fullyReady` -- every one of which was true for the wedged worker. Worker /metrics is also
# useless here: `isQueueMetricsEnabled` requires `instanceType === 'main'`
# (dist/scaling/scaling.service.js), so a worker emits no queue metrics at all, and the counts
# it would emit are whole-queue totals that worker-2 kept advancing anyway.
#
# WHAT THIS CHECKS INSTEAD
# ------------------------
# The real invariant: a healthy worker with free concurrency slots NEVER leaves jobs waiting.
# Measured on this deployment under a live 2,400-job backlog, each healthy worker holds exactly
# N8N_WORKER_CONCURRENCY (8) Bull job locks; 8 + 8 = the 16 seen in `bull:jobs:active`.
#
#   MINE = jobs this worker started and has not finished, INTERSECTED with `bull:jobs:active`
#   WAIT = LLEN bull:jobs:wait
#
# Ownership is exact and per-worker: the started/finished pairs come from this container's OWN
# n8n log file, so no cross-worker attribution is involved. Intersecting with `bull:jobs:active`
# makes MINE self-cleaning -- an execution that died without logging "finished" leaves the
# active list and stops counting, so stale log lines cannot inflate MINE and mask a wedge.
#
# VERDICT, in order. The primary signal is PROGRESS -- the most recent job id this worker
# started or finished. MINE is only a modifier, because a healthy worker's in-flight count
# fluctuates (measured live: 6 and 7 against a concurrency of 8, because jobs complete and leave
# `bull:jobs:active` between the two reads). Treating "MINE < CONCURRENCY" as the fault
# condition would therefore fire on perfectly healthy workers; progress does not have that flaw.
#
#   WAIT == 0             -> healthy. Nothing to do; idleness is legitimate. This is the check's
#                            main false-positive guard: an idle worker on an empty queue is never
#                            marked unhealthy, no matter how long it has been idle.
#   progress < GRACE ago  -> healthy. The worker is demonstrably still turning jobs over.
#   MINE >= CONCURRENCY   -> healthy while the stall is under SATURATED_STALL. Every slot is
#                            occupied, so having no free capacity to fill is correct behaviour,
#                            not a wedge. This is why long executions are safe: measured over 48h
#                            on this deployment, p99 execution time is 31 min and the max is
#                            68.6 min, with 878 executions longer than 15 min. A worker
#                            legitimately busy with slow work holds all 8 slots -- those jobs stay
#                            in `bull:jobs:active`, so MINE reads a steady 8 -- and stays healthy.
#                            Past SATURATED_STALL (default 90 min, above the 68.6 min longest
#                            execution actually observed) it is wedged holding its slots.
#   otherwise             -> WEDGED: free slots, jobs waiting, and no progress for GRACE seconds.
#                            This is the shape the 2026-08-10 incident took.
#
# COST: one `nc` round trip plus a `tail`/`awk` pass. Measured in-container at 0.01s wall and
# ~1 MB RSS. The host is memory-constrained (9.7 GiB, OOM kills observed), so the obvious
# alternative -- `node` + the bundled ioredis -- was rejected after measuring it at 3.10s wall
# and 66.7 MB RSS per invocation.
#
# FAIL-OPEN: any probe-side failure (Redis unreachable, malformed reply, missing log) exits 0.
# A Redis blip must not mark every worker unhealthy at once.
#
# ── THE ROTATION BUG THIS FILE SHIPPED WITH, fixed 2026-08-10 (READ BEFORE TOUCHING $LOG) ────────
# The first version read the FIXED path /tmp/n8n-worker.log. n8n's file logger is winston's File
# transport, and `N8N_LOG_FILE_SIZE_MAX=8` + `N8N_LOG_FILE_COUNT_MAX=2` make it ROTATE BY RENAMING:
# it fills `n8n-worker.log`, then writes `n8n-worker1.log`, then `n8n-worker2.log`, deleting the
# oldest. So the fixed path stops being the file being written after the first rotation -- measured
# at 431 KiB/h, that is roughly every 19 hours.
#
# What that did, measured live on 2026-08-10 22:06 IDT with BOTH workers demonstrably processing
# jobs (401 and 107 `Worker started/finished execution` lines in the preceding 10 minutes):
#   worker-1  /tmp/n8n-worker.log existed but was STALE, last written 17:02. Its newest job id
#             (104745) could never change, so fp_since froze and STALLED_FOR grew without bound:
#             "WEDGED ... no progress for 7412s". The live file was n8n-worker1.log.
#   worker-2  /tmp/n8n-worker.log did not exist AT ALL (rotated to n8n-worker1/2.log and the
#             original deleted). MINE=0 and FP="" permanently: "WEDGED ... no progress for 850s".
# i.e. the probe was a 100% false positive on BOTH workers, and would have stayed one forever.
# Anything that ACTS on this verdict -- and platform-base/autoheal now does -- would have restarted
# two healthy workers every couple of minutes, in a loop, for ever. Two fixes, both required:
#   1. Follow the rotation: read the NEWEST n8n-worker*.log, not a fixed name. The two newest are
#      read together so a rotation that just happened cannot momentarily hide all the job lines.
#   2. Actually fail open when there is no progress signal. "No job id anywhere" is a probe-side
#      failure -- exactly what the FAIL-OPEN paragraph above already promised and did not deliver:
#      the missing-log path fell through to MINE=0/FP="" and returned a WEDGED verdict built on no
#      evidence. A verdict of "wedged" must be a MEASUREMENT of a stalled job id, never the absence
#      of one.

set -u

CONC=${N8N_WORKER_CONCURRENCY:-8}
# A GLOB, not a path -- see the rotation note above. Must not match the state file below, which is
# why the pattern is anchored on the `.log` suffix.
LOG_GLOB=${WORKER_LIVENESS_LOG_GLOB:-/tmp/n8n-worker*.log}
STATE=${WORKER_LIVENESS_STATE:-/tmp/n8n-worker-liveness.state}
GRACE=${WORKER_LIVENESS_GRACE_SECONDS:-240}
SAT_STALL=${WORKER_LIVENESS_SATURATED_STALL_SECONDS:-5400}
SCAN_LINES=${WORKER_LIVENESS_SCAN_LINES:-40000}
RHOST=${QUEUE_BULL_REDIS_HOST:-redis}
RPORT=${QUEUE_BULL_REDIS_PORT:-6379}
RPASS=${QUEUE_BULL_REDIS_PASSWORD:-}
PREFIX=${QUEUE_BULL_PREFIX:-bull}

NOW=$(date +%s)

# ---------------------------------------------------------------- Redis: WAIT depth + active set
# Inline command protocol: one connection, one round trip, no client library.
REPLY=$(printf 'AUTH %s\r\nLLEN %s:jobs:wait\r\nLRANGE %s:jobs:active 0 -1\r\nQUIT\r\n' \
          "$RPASS" "$PREFIX" "$PREFIX" \
        | nc -w 5 "$RHOST" "$RPORT" 2>/dev/null | tr -d '\r')

[ -z "$REPLY" ] && { echo "liveness: SKIP redis unreachable ($RHOST:$RPORT) - failing open"; exit 0; }

WAIT=$(echo "$REPLY" | awk '/^:/ { sub(/^:/,""); print; exit }')
case "${WAIT:-x}" in ''|*[!0-9]*)
  echo "liveness: SKIP unparseable redis reply - failing open"; exit 0 ;;
esac

# Job ids of the active list: bare-digit lines after the '*' array header ('$len' lines start
# with '$', the LLEN integer with ':', statuses with '+'/'-').
ACTIVE=$(echo "$REPLY" | awk '/^\*/ { inarr=1; next } inarr && /^[0-9]+$/ { print }')

# ------------------------------------------------------------- Own log: my started-but-unfinished
# Per-worker by construction: these files are written by THIS container only.
#
# Rotation-aware: `ls -1t` is newest-first, so NEWEST is whatever n8n is writing right now whatever
# its index happens to be. PREV (the one before it) is read too, and read FIRST, so that a rotation
# which happened seconds ago -- leaving a nearly-empty newest file -- cannot momentarily erase every
# job line and make a busy worker look like it has never started a job.
NEWEST=$(ls -1t $LOG_GLOB 2>/dev/null | head -1)
PREV=$(ls -1t $LOG_GLOB 2>/dev/null | head -2 | tail -1)
[ "$PREV" = "$NEWEST" ] && PREV=""

MINE=0
FP=""
if [ -n "$NEWEST" ] && [ -r "$NEWEST" ]; then
  SUMMARY=$({ [ -n "$PREV" ] && [ -r "$PREV" ] && tail -n "$SCAN_LINES" "$PREV" 2>/dev/null
              tail -n "$SCAN_LINES" "$NEWEST" 2>/dev/null; } | awk -v active="$ACTIVE" '
    BEGIN { na = split(active, a, "\n"); for (i = 1; i <= na; i++) if (a[i] != "") isactive[a[i]] = 1 }
    function jobid(s,   r) { if (match(s, /job [0-9]+/)) { r = substr(s, RSTART + 4, RLENGTH - 4); return r } return "" }
    /Worker started execution/  { j = jobid($0); if (j != "") { started[j] = 1; delete finished[j]; last = j } }
    /Worker finished execution/ { j = jobid($0); if (j != "") { finished[j] = 1; last = j } }
    END {
      n = 0
      for (j in started) if (!(j in finished) && (j in isactive)) n++
      print n "|" last
    }')
  MINE=${SUMMARY%%|*}
  FP=${SUMMARY#*|}
fi
case "${MINE:-x}" in ''|*[!0-9]*) MINE=0 ;; esac

# THE FAIL-OPEN THE HEADER PROMISES. No job id anywhere in this worker's own logs means the probe
# has NO progress signal to reason about -- the log is missing, unreadable, or has not yet recorded
# a single job. That is a statement about the PROBE, not about the worker, and the two must never be
# confused: the pre-fix version fell through here with FP="" and reported a healthy worker WEDGED
# because a fingerprint that is always empty never changes, so its stall timer only ever grows.
# Exiting 0 here costs nothing -- a genuinely wedged worker still has thousands of historical job
# lines in its log (measured: 6109 starts in a live file), so it reaches the verdict below with a
# real, frozen fingerprint. Only a probe-side fault lands here.
if [ -z "$FP" ]; then
  echo "liveness: SKIP no job id in ${NEWEST:-<no n8n-worker*.log found>} - no progress signal, failing open"
  exit 0
fi

# ------------------------------------------------------------------------------- previous state
FP_PREV=""; FP_SINCE=$NOW
if [ -r "$STATE" ]; then
  FP_PREV=$(awk -F= '$1=="fp"{print $2}' "$STATE" 2>/dev/null)
  FP_SINCE=$(awk -F= '$1=="fp_since"{print $2}' "$STATE" 2>/dev/null)
fi
case "${FP_SINCE:-x}" in ''|*[!0-9]*) FP_SINCE=$NOW ;; esac

# Progress fingerprint: the most recent job id this worker started or finished. Job ids increase
# monotonically, so any change is real progress. Deliberately NOT the log file's mtime -- the
# wedged worker kept appending "Custom data value over 512 characters long." forever, so mtime
# would have looked alive for the entire two hours.
if [ "$FP" != "$FP_PREV" ]; then FP_SINCE=$NOW; fi

# ------------------------------------------------------------------------------------- verdict
VERDICT=ok
REASON=""
STALLED_FOR=$((NOW - FP_SINCE))
if [ "$WAIT" -eq 0 ]; then
  REASON="queue empty - idle is legitimate"
elif [ "$STALLED_FOR" -le "$GRACE" ]; then
  REASON="progress ${STALLED_FOR}s ago (grace ${GRACE}s)"
elif [ "$MINE" -ge "$CONC" ]; then
  if [ "$STALLED_FOR" -gt "$SAT_STALL" ]; then
    VERDICT=wedged
    REASON="all ${MINE}/${CONC} slots held but no job start/finish for ${STALLED_FOR}s (> ${SAT_STALL}s)"
  else
    REASON="saturated ${MINE}/${CONC}, last progress ${STALLED_FOR}s ago (long executions allowed up to ${SAT_STALL}s)"
  fi
else
  VERDICT=wedged
  REASON="free slots (${MINE}/${CONC}) and no progress for ${STALLED_FOR}s (> ${GRACE}s) while ${WAIT} jobs wait"
fi

# Write state before exiting so a failing probe still advances its own timers.
{ echo "fp=$FP"; echo "fp_since=$FP_SINCE"; } > "$STATE" 2>/dev/null || true

if [ "$VERDICT" = wedged ]; then
  echo "liveness: WEDGED wait=$WAIT mine=$MINE/$CONC :: $REASON"
  exit 1
fi
echo "liveness: OK wait=$WAIT mine=$MINE/$CONC :: $REASON"
exit 0
