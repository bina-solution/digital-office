#!/bin/bash
# Mark executions orphaned by an n8n main restart as 'crashed', so the wait tracker stops trying
# to resume them.
#
# WHY THIS IS NEEDED
# n8n marks orphaned RUNNING executions on startup, but a 'waiting' execution whose in-memory
# state died with the old process is left as-is. The wait tracker then polls it forever:
#   Error: No active execution found
#     at ActiveExecutions.getExecutionOrFail -> attachWorkflowExecution -> enqueueExecution
#     at WorkflowRunner.run -> WaitTracker.startExecution
# Measured 2026-08-23: 14 such rows producing 20 errors in 35 minutes AFTER the restart that was
# supposed to have cleared the wedge -- which reads exactly like the wedge recurring, and cost a
# second round of diagnosis to rule out. New waits resumed correctly throughout (4 BaseDrain runs
# succeeded post-restart); only the dead rows failed.
#
# SCOPE IS THE RESTART, NOT THE SYMPTOM. Only executions started BEFORE the given restart instant
# are touched, so a legitimately parked execution is never killed. 'crashed' is n8n's own status
# for this and is already present in the table.
#
# usage: clear_orphaned_waiting_execs.sh <restart-instant-UTC>     e.g. '2026-08-23 05:44:38+00'
#        clear_orphaned_waiting_execs.sh --auto     (reads the container's StartedAt)
set -u
DK="docker -H unix:///run/bbox-docker.sock"
CTR=n8n-shlomo-laptop
OUT=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/data/_registry_backup

if [ "${1:-}" = "--auto" ]; then
  CUT=$($DK inspect -f '{{.State.StartedAt}}' "$CTR" | cut -c1-19 | tr 'T' ' ')
  CUT="${CUT}+00"
else
  CUT="${1:?need a restart instant, or --auto}"
fi
echo "  cutoff (container start): $CUT"

mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
BK="$OUT/orphaned-execs-$STAMP.txt"

$DK exec -i n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -tAc \
 "SELECT id||','||\"workflowId\"||','||status||','||\"startedAt\"
  FROM execution_entity
  WHERE status IN ('waiting','running') AND \"startedAt\" < '$CUT'" | tr -d '\r' > "$BK"
N=$(grep -c . "$BK" || true)
echo "  orphans found: $N   (backed up to ${BK##*/})"
[ "${N:-0}" -eq 0 ] && { echo "  nothing to do"; exit 0; }

$DK exec -i n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -v ON_ERROR_STOP=1 -tAf - <<SQL
BEGIN;
UPDATE execution_entity
   SET status = 'crashed', "stoppedAt" = coalesce("stoppedAt", now())
 WHERE status IN ('waiting','running') AND "startedAt" < '$CUT';
COMMIT;
SELECT '  remaining pre-restart waiting/running (must be 0) = '||count(*)
FROM execution_entity WHERE status IN ('waiting','running') AND "startedAt" < '$CUT';
SELECT '  live now: waiting='||count(*) FILTER (WHERE status='waiting')
     ||'  running='||count(*) FILTER (WHERE status='running')
FROM execution_entity WHERE status IN ('waiting','running');
SQL
