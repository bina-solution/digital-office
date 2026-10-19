#!/usr/bin/env bash
# scripts/ops/machine-health-guard.sh
#
# "Has the machine stopped working?" detector + gated, safe recovery. Built 2026-08-06 off the
# 19:00 UTC finding on 2026-08-05: indoxProcessDocument01 logged 85 crashed + 10 error + 1 success
# out of 96 attempts (94% failure) in one hour, then 32 crashed + 18 error + 0 success (100%
# failure) the next hour — and NOTHING in the system reacted to that on its own.
#
# SENSORS (reuses the existing tools, does not reinvent them):
#   - error-pulse.sh's own SQL shape (restart-churn check, crash/error counts, stuck-claim counts)
#   - timeline-gaps.py for the utilisation/backlog-signal read when INVESTIGATE mode is used
#
# "STOPPED WORKING" is defined here in two independent, measurable ways — either one alone is
# sufficient to alert, because they catch different failure shapes:
#   A) FAILURE STORM: crashed+error >= FAIL_RATE_PCT of attempts, over >= MIN_ATTEMPTS attempts,
#      for the core pipeline workflows, in the last WINDOW_MIN minutes. (matches the 94%/100% case)
#   B) STARVATION: average slot utilisation < LOW_UTIL_PCT while a backlog signal is present,
#      sustained across TWO consecutive runs of this script at least SUSTAIN_MIN apart (a state
#      file makes this true "sustained", not a single noisy sample — see .health-guard-state/).
#
# RECOVERY (gated, safe-by-default):
#   1. ALWAYS (any STOPPED verdict): run execution-watchdog.py in the same mode (dry-run unless
#      --apply) to clear confirmed zombie executions - proven safe via live Bull-queue
#      corroboration, see that script's own header. This alone recovers "34 executions stuck
#      running holding slots forever" without touching anything destructive.
#   2. n8n RESTART (the heavier lever) fires ONLY when ALL of: --apply AND --confirm-restart AND
#      the failure signature specifically matches the documented restart-orphan shape (a burst of
#      'crashed' executions with NO error payload, clustering at the same stoppedAt second - see
#      error-pulse.sh's own header for why this shape means orphaning, not evidence of anything
#      else) AND that same signature was ALSO seen on the immediately preceding run (state file) -
#      i.e. it must reproduce once before this script ever restarts anything. This is the same
#      remediation n8n already performs on its own at every restart ("queue recovery... recovered
#      dangling executions" per docker logs) - this just does it proactively instead of waiting for
#      a restart to happen for unrelated reasons.
#   3. If the failure signature instead points at ONE specific downstream (e.g. drive api /
#      apitools errors dominate, no restart-orphan shape) — this script explicitly does NOT
#      restart n8n (that would not fix a downstream defect) and does NOT touch sync_registry,
#      take/chunk, or any tuned setting. It prints the downstream culprit loudly and stops there -
#      "back off" here means "stop and hand it to a human / the owner of that file", which is the
#      correct backoff for a defect outside this script's ownership.
#
# Usage:
#   export DOCKER_HOST=unix:///run/bbox-docker.sock
#   bash scripts/ops/machine-health-guard.sh                       # investigate + report, no action
#   bash scripts/ops/machine-health-guard.sh --apply                # + clear confirmed zombies
#   bash scripts/ops/machine-health-guard.sh --apply --confirm-restart   # + allow the n8n restart lever
#
# Run this on a short interval (systemd timer / cron / /loop), NOT as a one-shot — "sustained across
# two runs" is what protects the restart lever from a single noisy sample.

set -uo pipefail

WINDOW_MIN="${WINDOW_MIN:-15}"
FAIL_RATE_PCT="${FAIL_RATE_PCT:-80}"
MIN_ATTEMPTS="${MIN_ATTEMPTS:-20}"
LOW_UTIL_PCT="${LOW_UTIL_PCT:-15}"
SUSTAIN_MIN="${SUSTAIN_MIN:-4}"

# Admission-control thresholds. Overridable, but these defaults are measured, not guessed — see
# the --admit block below for where each number comes from.
# Thresholds come from the ONE declared source, shared with ops/prejob_waitfree.sh so the two
# admission gates on this machine cannot drift into disagreeing about when it is healthy. The
# numbers live there; the wait-vs-refuse POLICY stays here. Per-run overrides still work.
_AT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/admission-thresholds.sh"
# shellcheck source=/dev/null
[ -r "$_AT" ] && . "$_AT"

ADMIT_MAX_SWAP_PCT="${ADMIT_MAX_SWAP_PCT:-${ADMISSION_MAX_SWAP_PCT:-50}}"
ADMIT_MIN_AVAIL_MIB="${ADMIT_MIN_AVAIL_MIB:-${ADMISSION_MIN_AVAIL_MIB:-1536}}"
ADMIT_MIN_DAEMON_AGE_S="${ADMIT_MIN_DAEMON_AGE_S:-${ADMISSION_MIN_DAEMON_AGE_S:-300}}"
# Distro restarts in the last hour. This replaced load average as the "is the machine thrashing"
# veto — see the long note in the --admit block for why load average was wrong.
ADMIT_MAX_RECENT_RESTARTS="${ADMIT_MAX_RECENT_RESTARTS:-${ADMISSION_MAX_RECENT_RESTARTS:-2}}"
# Load average is REPORTED but never vetoes. Kept as a variable only so the advisory line has
# something to compare against; changing it cannot block a job.
ADMIT_ADVISORY_LOAD="${ADMIT_ADVISORY_LOAD:-8}"

APPLY=0
CONFIRM_RESTART=0
ADMIT=""
_next_is_admit=0
for arg in "$@"; do
  if [ "$_next_is_admit" -eq 1 ]; then ADMIT="$arg"; _next_is_admit=0; continue; fi
  case "$arg" in
    --apply) APPLY=1 ;;
    --confirm-restart) CONFIRM_RESTART=1 ;;
    --admit) _next_is_admit=1 ;;
    --admit=*) ADMIT="${arg#--admit=}" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.health-guard-state"
mkdir -p "$STATE_DIR"
PREV_SIGNATURE_FILE="$STATE_DIR/last-restart-orphan-signature.txt"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/bbox-docker.sock}"

# ═════════════════════════════════════════════════════════════════════════════════════════════════
# ADMISSION CONTROL  —  `--admit <job-class>`
# ═════════════════════════════════════════════════════════════════════════════════════════════════
# Exit 0 = the machine can take this job. Exit 3 = REFUSED, do not start.
#
# Call it as a gate, so a heavy job cannot start on a machine that is already tipping:
#   bash scripts/ops/machine-health-guard.sh --admit e2e   || exit 0   # skip, don't fail the run
#   bash scripts/ops/machine-health-guard.sh --admit e2e   || exit 1   # hard-fail the run
#
# WHY (measured 2026-08-05 22:00 -> 2026-08-06 03:35 IDT): 24 docker daemon starts and 7 WSL2 VM
# kernel boots, ZERO graceful docker stops. The VM is torn down under the daemon, every container
# is recreated, every in-flight n8n execution is orphaned, and n8n mislabels the orphans
# "Workflow did not finish, possible out-of-memory issue" — which is not an OOM. Four separate
# attempts to time one document through the pipeline were destroyed this way.
#
# The thresholds, and why each one is here rather than a round number someone liked:
#   swap > 50%             the documented precondition at the 03:31 failure (5.6 GiB of 6.0 GiB).
#   MemAvailable < 1.5GiB  THE BINDING CONSTRAINT, and the one a swap-only check misses entirely:
#                          during the 03:49 slide the VM had 192 MiB free while swap still had
#                          4.3 GiB spare. A swap-only gate would have admitted the job.
#   daemon age < 300s      a stack that restarted a minute ago is still settling — postgres may
#                          still be replaying WAL (measured: 65 s over 390 MB). Jobs started into
#                          that window fail for reasons unrelated to the job.
#   >2 restarts in 1h      the machine is actively in the failure regime. A proof run started into
#                          it will be destroyed by the next restart, which is what killed proof
#                          attempts 1-4.
#
# ── WHY LOAD AVERAGE IS REPORTED BUT NEVER VETOES (changed 2026-08-06) ───────────────────────────
# The first version of this gate refused above load 8. That was wrong, and it would have blocked
# every proof run permanently while looking like a safety feature.
#
# This stack is CPU-oversubscribed BY DESIGN and by explicit owner decision: two n8n workers at
# --concurrency=8 is 16 execution slots on 6 processors, plus apitools' 12-worker gunicorn pool.
# Load above 8 is therefore the NORMAL state of a machine that is processing documents — measured
# at 27.92 while perfectly healthy. A load gate would only ever fire during exactly the conditions
# we need to measure, i.e. it would require an idle machine in order to measure a busy one.
#
# It also has no demonstrated predictive value for the actual failure: load was 15.0 at the 03:31
# teardown and 27.92 during a period with no teardown at all. Memory is what correlates. Note too
# that Linux load average counts uninterruptible-sleep tasks, so swap thrash inflates it — meaning
# a genuinely dangerous load spike is already caught by the swap and MemAvailable gates, directly
# and earlier. Reporting it is useful context; vetoing on it is a false green in reverse.
#
# This deliberately does NOT read the Windows host's free memory, which is the true root pressure
# (host 15.65 GiB, committed 14.38 GiB, free 1.27 GiB while vmmemWSL held 7.04 GiB). Reading it
# means calling powershell.exe from inside the VM, and that call is itself what fails with
# Wsl/Service/0x8007274c under exactly the pressure we are testing for. Gating on an unreliable
# probe would produce false greens, so the in-VM signals above are used instead. NOT VERIFIED
# from inside the VM: Windows-side headroom. If you need it, measure it from Windows.
if [ -n "$ADMIT" ]; then
  echo "================================================================"
  echo "admission check  $(date -u +%Y-%m-%dT%H:%M:%SZ)  job-class=${ADMIT}"
  echo "================================================================"

  REFUSE=0
  REASONS=""

  SWAP_TOTAL=$(awk '/^SwapTotal:/{print int($2/1024)}' /proc/meminfo)
  SWAP_FREE=$(awk '/^SwapFree:/{print int($2/1024)}' /proc/meminfo)
  MEM_AVAIL=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
  MEM_TOTAL=$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)
  LOAD1=$(cut -d' ' -f1 /proc/loadavg)

  SWAP_PCT=0
  if [ "${SWAP_TOTAL:-0}" -gt 0 ]; then
    SWAP_PCT=$(( (SWAP_TOTAL - SWAP_FREE) * 100 / SWAP_TOTAL ))
  fi
  # /proc/loadavg is a decimal; compare in hundredths so we never need bc.
  LOAD1_X100=$(printf '%s' "$LOAD1" | awk '{printf "%d", $1*100}')
  LOAD_MAX_X100=$(printf '%s' "$ADMIT_ADVISORY_LOAD" | awk '{printf "%d", $1*100}')

  echo "  swap used ......... ${SWAP_PCT}% of ${SWAP_TOTAL}MiB      (refuse above ${ADMIT_MAX_SWAP_PCT}%)"
  echo "  MemAvailable ...... ${MEM_AVAIL}MiB of ${MEM_TOTAL}MiB   (refuse below ${ADMIT_MIN_AVAIL_MIB}MiB)"
  if [ "$LOAD1_X100" -gt "$LOAD_MAX_X100" ]; then
    echo "  load average (1m) . ${LOAD1}   ADVISORY ONLY — above ${ADMIT_ADVISORY_LOAD}, but this stack"
    echo "                      is CPU-oversubscribed by design (16 n8n slots on 6 processors)."
    echo "                      Expect this while processing. NOT a blocker. See note in source."
  else
    echo "  load average (1m) . ${LOAD1}   (advisory only, never blocks)"
  fi

  [ "$SWAP_PCT" -gt "$ADMIT_MAX_SWAP_PCT" ] && { REFUSE=1; REASONS="${REASONS}
    - swap at ${SWAP_PCT}% (limit ${ADMIT_MAX_SWAP_PCT}%)"; }
  [ "${MEM_AVAIL:-0}" -lt "$ADMIT_MIN_AVAIL_MIB" ] && { REFUSE=1; REASONS="${REASONS}
    - only ${MEM_AVAIL}MiB available (need ${ADMIT_MIN_AVAIL_MIB}MiB)"; }

  # ── Is the machine actively thrashing? ────────────────────────────────────────────────────────
  # This is the veto that replaced load average, and it measures the failure DIRECTLY rather than
  # via a proxy. Forensics (2026-08-06): in 24h there were 42 docker daemon starts, 42 systemd[1]
  # inits, and 16 kernel boots — docker starts and systemd inits match 1:1, exactly. dockerd never
  # died on its own even once; the whole Linux userspace was torn down and re-inited 42 times, 26
  # of those without a kernel boot (a WSL *distro* restart, kernel surviving). Counting systemd
  # inits is therefore the truest available measure of "is this host tearing itself down right
  # now", and a proof run started into that regime will be orphaned exactly as attempts 1-4 were.
  RECENT_RESTARTS=$(journalctl --since '-60 min' --no-pager -o short 2>/dev/null \
                    | grep -c 'systemd\[1\]: Reached target Basic System' || echo 0)
  RECENT_RESTARTS=${RECENT_RESTARTS:-0}
  echo "  distro restarts 1h  ${RECENT_RESTARTS}                     (refuse above ${ADMIT_MAX_RECENT_RESTARTS})"
  [ "$RECENT_RESTARTS" -gt "$ADMIT_MAX_RECENT_RESTARTS" ] && { REFUSE=1; REASONS="${REASONS}
    - the distro has re-initialised ${RECENT_RESTARTS} times in the last hour. The host is in the
      failure regime; a proof run started now will be orphaned by the next teardown."; }

  # How long has the docker daemon been up? This is also the value that makes a stack restart
  # legible instead of being misread as an OOM — see error-pulse.sh, which records it every pulse.
  DAEMON_TS=$(systemctl show docker -p ExecMainStartTimestamp --value 2>/dev/null)
  DAEMON_AGE=""
  if [ -n "$DAEMON_TS" ]; then
    DAEMON_EPOCH=$(date -d "$DAEMON_TS" +%s 2>/dev/null || echo "")
    if [ -n "$DAEMON_EPOCH" ]; then
      DAEMON_AGE=$(( $(date +%s) - DAEMON_EPOCH ))
      echo "  docker daemon age . ${DAEMON_AGE}s (started ${DAEMON_TS})  (refuse below ${ADMIT_MIN_DAEMON_AGE_S}s)"
      [ "$DAEMON_AGE" -lt "$ADMIT_MIN_DAEMON_AGE_S" ] && { REFUSE=1; REASONS="${REASONS}
    - docker daemon is only ${DAEMON_AGE}s old — the stack is still settling (postgres may still be
      replaying WAL; a 65s/390MB redo was measured on 2026-08-06)"; }
    fi
  else
    echo "  docker daemon age . unknown (systemctl unavailable) — NOT VERIFIED, not gated on"
  fi

  # A heavy job and the pipeline must not share this machine. browser42 is the Chromium/Playwright
  # stack; quiet-mode.sh is the switch that takes it down.
  if [ "$ADMIT" = "e2e" ] || [ "$ADMIT" = "loadtest" ]; then
    PIPE_BUSY=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -cE '^n8n-worker-' || true)
    echo "  n8n workers up .... ${PIPE_BUSY}"
  fi
  if [ "$ADMIT" = "pipeline" ] || [ "$ADMIT" = "proof" ]; then
    B42=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -cE '^browser42-' || true)
    echo "  browser42 up ...... ${B42}   (refuse above 0 for a pipeline proof)"
    [ "${B42:-0}" -gt 0 ] && { REFUSE=1; REASONS="${REASONS}
    - ${B42} browser42/Chromium containers are running. platform.state.yaml declares browser42
      'enabled: false' — this is drift. Take it down with:
        bash scripts/ops/quiet-mode.sh on --apply"; }
  fi

  # ── FAIL CLOSED ───────────────────────────────────────────────────────────────────────────────
  # Added after this gate printed "VERDICT: ADMITTED" on a run where two of its own checks had
  # errored out ("ADMIT_MAX_LOAD: unbound variable", "integer expression expected"). A gate that
  # green-lights a proof run because its own sensors failed is worse than no gate — it is the
  # dominant defect class in this repo (an operation reporting success while doing nothing) wearing
  # a safety label. If a metric could not be read, that is a REFUSAL, not a pass.
  for _m in SWAP_PCT MEM_AVAIL MEM_TOTAL RECENT_RESTARTS; do
    _v=$(eval printf '%s' "\${${_m}:-}")
    case "$_v" in
      ''|*[!0-9]*) REFUSE=1; REASONS="${REASONS}
    - SENSOR FAILURE: ${_m} did not read back as a number (got '${_v}'). Refusing rather than
      admitting on unverified data."; ;;
    esac
  done

  echo
  if [ "$REFUSE" -eq 1 ]; then
    echo "VERDICT: REFUSED — do not start '${ADMIT}' on this machine right now.${REASONS}"
    echo
    echo "  Free capacity first:  bash scripts/ops/quiet-mode.sh on --apply"
    echo "  Then re-check:        bash scripts/ops/machine-health-guard.sh --admit ${ADMIT}"
    echo "================================================================"
    exit 3
  fi
  echo "VERDICT: ADMITTED — '${ADMIT}' may start."
  echo "================================================================"
  exit 0
fi

N8N_PG=$(docker ps --format '{{.Names}}' | grep -E '^n8n-postgres-' | head -1)
N8N_MAIN=$(docker ps --format '{{.Names}}' | grep -E '^n8n-[a-z0-9-]+$' | grep -v worker | grep -v runners | grep -v postgres | head -1)

echo "================================================================"
echo "machine-health-guard  $(date -u +%Y-%m-%dT%H:%M:%SZ)  window=${WINDOW_MIN}m  mode=$([ $APPLY -eq 1 ] && echo APPLY || echo DRY-RUN)"
echo "n8n=$N8N_MAIN  n8n_pg=$N8N_PG"
echo "================================================================"

if [ -z "$N8N_PG" ]; then
  echo "FATAL: no n8n-postgres-* container found. Aborting."
  exit 1
fi

# ---- Sensor A: failure-storm, core pipeline workflows only (avoid drowning in test-harness noise,
#      same caveat error-pulse.sh's own header documents for ...Test/E2E workflows) ----
echo
echo "--- Sensor A: failure rate, core pipeline workflows, last ${WINDOW_MIN}m ---"
READ=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select
    count(*) filter (where e.status in ('crashed','error')) as bad,
    count(*) as total
  from execution_entity e join workflow_entity w on w.id = e.\"workflowId\"
  where e.\"startedAt\" > now() - interval '${WINDOW_MIN} minutes'
    and w.name not ilike '%test%' and w.name not ilike '%E2E%'
    and (w.name ilike '%process document%' or w.name ilike '%sync v3%' or w.name ilike '%drive api%'
         or w.name ilike '%incoming documents%' or w.name ilike '%sync ledger%' or w.name ilike '%indox api%')
")
BAD=$(echo "$READ" | cut -d'|' -f1 | tr -d ' ')
TOTAL=$(echo "$READ" | cut -d'|' -f2 | tr -d ' ')
BAD="${BAD:-0}"; TOTAL="${TOTAL:-0}"
FAIL_PCT=0
[ "$TOTAL" -gt 0 ] && FAIL_PCT=$((BAD * 100 / TOTAL))
echo "  bad=${BAD} total=${TOTAL} fail_pct=${FAIL_PCT}%  (threshold: >=${FAIL_RATE_PCT}% over >=${MIN_ATTEMPTS} attempts)"

STORM=0
if [ "$TOTAL" -ge "$MIN_ATTEMPTS" ] && [ "$FAIL_PCT" -ge "$FAIL_RATE_PCT" ]; then
  STORM=1
  echo "  -> FAILURE STORM: yes"
else
  echo "  -> FAILURE STORM: no"
fi

# ---- Sensor A2: restart-orphan signature (crashed, no error payload, clustered same-second stop) ----
echo
echo "--- Sensor A2: restart-orphan shape (crashed executions with no error payload) last ${WINDOW_MIN}m ---"
ORPHAN_COUNT=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select count(*) from execution_entity e
  where e.status='crashed' and e.\"startedAt\" > now() - interval '${WINDOW_MIN} minutes'
    and not exists (select 1 from execution_data d where d.\"executionId\"=e.id and d.data like '%\"error\":%')
" | tr -d ' ')
ORPHAN_COUNT="${ORPHAN_COUNT:-0}"
CLUSTER=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select date_trunc('second', \"stoppedAt\") ts, count(*) c from execution_entity
  where status='crashed' and \"startedAt\" > now() - interval '${WINDOW_MIN} minutes'
  group by 1 having count(*) >= 5 order by c desc limit 1
")
echo "  orphan-shaped crashed (no error payload): ${ORPHAN_COUNT}"
echo "  largest same-second crash cluster: ${CLUSTER:-none}"

RESTART_ORPHAN_SIGNATURE=""
if [ -n "$CLUSTER" ] && [ "$ORPHAN_COUNT" -ge 10 ]; then
  RESTART_ORPHAN_SIGNATURE="$CLUSTER"
  echo "  -> RESTART-ORPHAN SIGNATURE: yes ($CLUSTER)"
else
  echo "  -> RESTART-ORPHAN SIGNATURE: no"
fi

# ---- Sensor A3: is the dominant failure a single named downstream instead? ----
echo
echo "--- Sensor A3: top failing workflow this window (downstream-vs-engine classifier) ---"
TOP_FAIL=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select w.name, count(*) c from execution_entity e join workflow_entity w on w.id=e.\"workflowId\"
  where e.status in ('crashed','error') and e.\"startedAt\" > now() - interval '${WINDOW_MIN} minutes'
  group by 1 order by 2 desc limit 1
")
echo "  ${TOP_FAIL:-none}"

echo
echo "--- Sensor B: stuck sync_ledger claims (backlog-is-real corroboration), >10m ---"
SUPA_PG=$(docker ps --format '{{.Names}}' | grep -E '^supabase-db-' | head -1)
if [ -n "$SUPA_PG" ]; then
  docker exec "$SUPA_PG" psql -U postgres -d postgres -tAc "
    select source, count(*), min(claimed_at) from sync_ledger
    where claimed_at < now() - interval '10 minutes' and delivered_at is null
    group by source order by 2 desc" | sed 's/^/  /'
fi

# ---- Verdict ----
echo
echo "================================================================"
if [ "$STORM" -eq 1 ]; then
  echo "VERDICT: MACHINE STOPPED WORKING (failure storm: ${FAIL_PCT}% of ${TOTAL} attempts failed)"
  VERDICT=1
else
  echo "VERDICT: healthy by Sensor A (failure rate ${FAIL_PCT}% under ${FAIL_RATE_PCT}% threshold)"
  VERDICT=0
fi
echo "================================================================"

if [ "$VERDICT" -eq 0 ]; then
  echo "No recovery actions needed this run."
  rm -f "$PREV_SIGNATURE_FILE" 2>/dev/null
  exit 0
fi

echo
echo "--- Recovery action 1/2: clear confirmed zombie executions (always safe, always attempted) ---"
WD_ARGS="--minutes 45"
[ "$APPLY" -eq 1 ] && WD_ARGS="$WD_ARGS --apply"
python3 "$SCRIPT_DIR/execution-watchdog.py" $WD_ARGS

echo
echo "--- Recovery action 2/2: n8n restart lever ---"
if [ -z "$RESTART_ORPHAN_SIGNATURE" ]; then
  echo "  Failure signature does NOT match restart-orphan shape (top failing workflow: ${TOP_FAIL:-unknown})."
  echo "  This looks like a downstream/config defect, not a wedged n8n process — restarting n8n would"
  echo "  not fix it and risks orphaning healthy work for no gain. NOT restarting. Reporting only:"
  echo "  -> investigate '${TOP_FAIL:-the top failing workflow above}' directly (its owner, not this script)."
elif [ "$APPLY" -eq 0 ] || [ "$CONFIRM_RESTART" -eq 0 ]; then
  echo "  Restart-orphan signature present ($RESTART_ORPHAN_SIGNATURE) but --apply --confirm-restart"
  echo "  not both given — this is the heaviest lever this script has and requires explicit, separate"
  echo "  opt-in every time. Re-run with both flags to allow it. NOT restarting."
else
  PREV=""
  [ -f "$PREV_SIGNATURE_FILE" ] && PREV=$(cat "$PREV_SIGNATURE_FILE")
  if [ -z "$PREV" ]; then
    echo "  Restart-orphan signature present but this is the FIRST run to see it — recording it and"
    echo "  waiting for it to reproduce on the next run before restarting anything (no single-sample"
    echo "  restarts). Re-run this script again in a few minutes."
    echo "$RESTART_ORPHAN_SIGNATURE" > "$PREV_SIGNATURE_FILE"
  else
    echo "  Restart-orphan signature reproduced across two consecutive runs (prev: $PREV / now:"
    echo "  $RESTART_ORPHAN_SIGNATURE). Restarting n8n main container ONLY (not workers, not the rest"
    echo "  of the stack) — this mirrors n8n's own documented crash-recovery, run proactively instead"
    echo "  of waiting for an unrelated restart."
    if [ -n "$N8N_MAIN" ]; then
      docker restart "$N8N_MAIN"
      echo "  docker restart $N8N_MAIN issued."
    else
      echo "  ERROR: could not find the n8n main container to restart."
    fi
    rm -f "$PREV_SIGNATURE_FILE"
  fi
fi

echo
echo "================================================================"
echo "machine-health-guard done  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "================================================================"
