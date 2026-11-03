#!/usr/bin/env bash
# scripts/ops/error-pulse.sh
#
# Cheap, repeatable n8n error/crash monitor. Read-only (no restarts, no rebuilds,
# no writes) — safe to run on a memory-constrained host every few minutes.
#
# Written 2026-08-05 during the RCA in ai/context/archive/indox-pre-2026-09/ERROR-RCA-2026-08-05.md. Context
# that motivated every check below:
#   - n8n restart-orphaning marks in-flight executions `crashed` with the generic
#     string "Workflow did not finish, possible out-of-memory issue" — that text is
#     NOT evidence of OOM (n8n runs at ~300MiB of a 2GiB limit). This script counts
#     restarts explicitly so that count stops being confused with real errors.
#   - workflow_history "import" rows are a proxy for `n8n-push`/CLI redeploys —
#     each one briefly deactivates the workflow (any concurrent sub-workflow call
#     into it fails with "Workflow is not active and cannot be executed") and is
#     usually followed by a full n8n container restart (orphaning whatever was
#     in flight). A churny import cadence explains a lot of otherwise-mysterious
#     crash/error noise — surface it every run.
#   - sync_ledger.claimed_at rows with no delivered_at past a timeout are a real
#     stuck-pipe signal (distinct from n8n orphaning).
#   - /incomingDocuments/sync/{registry,inventory,items} have a documented 40s
#     console-proxy read-timeout budget (see apps/indox/app/incoming_documents/api/__init__.py
#     around "console proxy's 40s read timeout"). Track how close they run to it.
#
# Usage:
#   bash scripts/ops/error-pulse.sh [minutes] [claim_timeout_minutes]
#   minutes                 - lookback window for error/crash counts (default 15)
#   claim_timeout_minutes   - sync_ledger stuck-claim threshold (default 10)
#
# State (new error-class tracking) persists in scripts/ops/.error-pulse-state/
# next to this script (gitignored — created on first run).

set -uo pipefail

MINUTES="${1:-15}"
CLAIM_TIMEOUT="${2:-10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.error-pulse-state"
SEEN_FILE="$STATE_DIR/seen-fingerprints.txt"
mkdir -p "$STATE_DIR"
touch "$SEEN_FILE"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/bbox-docker.sock}"

# ---- auto-detect container names (portable across shlomo-laptop / bina-deployment / vps) ----
N8N_MAIN=$(docker ps --format '{{.Names}}' | grep -E '^n8n-[a-z0-9-]+$' | grep -v worker | grep -v runners | grep -v postgres | head -1)
N8N_PG=$(docker ps --format '{{.Names}}' | grep -E '^n8n-postgres-' | head -1)
SUPA_PG=$(docker ps --format '{{.Names}}' | grep -E '^supabase-db-' | head -1)
INCOMING=$(docker ps --format '{{.Names}}' | grep -E '^incoming-documents-' | head -1)

echo "================================================================"
echo "error-pulse  $(date -u +%Y-%m-%dT%H:%M:%SZ)   window=${MINUTES}m  claim_timeout=${CLAIM_TIMEOUT}m"
echo "containers: n8n=$N8N_MAIN  n8n_pg=$N8N_PG  supabase_pg=$SUPA_PG  incoming=$INCOMING"
echo "================================================================"

if [ -z "$N8N_PG" ]; then
  echo "FATAL: no n8n-postgres-* container found (docker ps). Aborting."
  exit 1
fi

# ---- 0. DOCKER DAEMON / VM LIFECYCLE (check this BEFORE anything below) ----
#
# Added 2026-08-06. Everything in section 1 below assumes the n8n *container* restarting is the
# confound to rule out. It is not the only one, and it was not the big one. On the night of
# 2026-08-05/06 the DOCKER DAEMON restarted 24 times between 22:00 and 03:35, and the WSL2 VM
# under it booted 7 times, with ZERO graceful docker stops in the journal — the VM was being torn
# down, taking every container with it. Each teardown orphans every in-flight execution and
# n8n stamps them "Workflow did not finish, possible out-of-memory issue". That string cost the
# team hours chasing a phantom OOM: n8n was at ~442 MiB of a 2 GiB limit, restarts=0, oom=false.
#
# So the daemon's own start timestamp is now recorded on EVERY pulse. If it moved since the last
# pulse, every 'crashed' count below is explained by that and nothing else needs a theory.
echo
echo "--- docker daemon / VM lifecycle (the FIRST confound, ahead of container churn) ---"
DAEMON_TS=$(systemctl show docker -p ExecMainStartTimestamp --value 2>/dev/null)
if [ -n "$DAEMON_TS" ]; then
  echo "  docker ExecMainStartTimestamp: $DAEMON_TS"
  DAEMON_EPOCH=$(date -d "$DAEMON_TS" +%s 2>/dev/null || echo "")
  if [ -n "$DAEMON_EPOCH" ]; then
    echo "  daemon uptime: $(( ($(date +%s) - DAEMON_EPOCH) / 60 )) minutes"
  fi
  LAST_TS_FILE="$STATE_DIR/last-docker-start.txt"
  PREV_TS=""
  [ -f "$LAST_TS_FILE" ] && PREV_TS=$(cat "$LAST_TS_FILE")
  if [ -n "$PREV_TS" ] && [ "$PREV_TS" != "$DAEMON_TS" ]; then
    echo "  *** DAEMON RESTARTED SINCE THE LAST PULSE ***"
    echo "      was: $PREV_TS"
    echo "      now: $DAEMON_TS"
    echo "      => Every 'crashed' execution below with no error payload is an ORPHAN of this"
    echo "         restart. It is NOT an OOM and NOT a workflow defect. Do not open a task for it."
  elif [ -n "$PREV_TS" ]; then
    echo "  (unchanged since last pulse — container-level churn below is NOT daemon-caused)"
  else
    echo "  (first pulse to record this — no prior value to compare)"
  fi
  printf '%s' "$DAEMON_TS" > "$LAST_TS_FILE"
else
  echo "  systemctl unavailable — daemon start time NOT VERIFIED this pulse."
fi
echo "  docker daemon starts in the last 24h: $(journalctl -u docker --since '-24 hours' --no-pager 2>/dev/null | grep -c 'Starting Docker Application Container Engine' || echo 'unknown')"
echo "  WSL VM kernel boots in the last 24h:  $(journalctl --since '-24 hours' --no-pager 2>/dev/null | grep -c 'kernel: Linux version' || echo 'unknown')"
echo "  host: $(free -m | awk '/^Mem:/{printf "mem %sMiB used / %sMiB total, %sMiB avail", $3, $2, $7}'), swap $(free -m | awk '/^Swap:/{printf "%s/%sMiB", $3, $2}'), load$(cut -d' ' -f1-3 /proc/loadavg | sed 's/^/ /')"

# ---- 1. n8n restart / redeploy churn (THE confound to check before trusting any crash count) ----
echo
echo "--- n8n restart / redeploy churn ---"
if [ -n "$N8N_MAIN" ]; then
  docker inspect "$N8N_MAIN" --format 'main container StartedAt: {{.State.StartedAt}}  (Created: {{.Created}})'
fi
echo -n "workflow_history 'import' rows in last ${MINUTES}m (redeploy proxy): "
docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select count(*) from workflow_history
  where \"createdAt\" > now() - interval '${MINUTES} minutes'"
echo "  by workflow:"
docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select w.name, count(*) from workflow_history h
  join workflow_entity w on w.id = h.\"workflowId\"
  where h.\"createdAt\" > now() - interval '${MINUTES} minutes'
  group by w.name order by 2 desc" | sed 's/^/    /'

# ---- 2. error/crash counts by workflow, last N minutes ----
echo
echo "--- status counts, last ${MINUTES}m (by workflow) ---"
docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select w.name, e.status, count(*)
  from execution_entity e join workflow_entity w on w.id = e.\"workflowId\"
  where e.\"startedAt\" > now() - interval '${MINUTES} minutes'
    and e.status in ('error','crashed')
  group by w.name, e.status
  order by 3 desc" | sed 's/^/  /'

echo
echo "--- crashed executions with NO error payload recorded (pure orphan signature), last ${MINUTES}m ---"
docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select count(*) from execution_entity e
  where e.status = 'crashed' and e.\"startedAt\" > now() - interval '${MINUTES} minutes'
    and not exists (select 1 from execution_data d where d.\"executionId\" = e.id and d.data like '%\"error\":%')"

# ---- 3. new error classes (workflow + lastNodeExecuted + first error-ish string), diffed against state ----
echo
echo "--- error/crash fingerprints seen in last ${MINUTES}m ---"
CUR_FILE=$(mktemp)
docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
  select e.id, w.name
  from execution_entity e join workflow_entity w on w.id = e.\"workflowId\"
  where e.\"startedAt\" > now() - interval '${MINUTES} minutes' and e.status in ('error','crashed')
  order by e.id" > "$CUR_FILE.ids"

NEW_COUNT=0
while IFS='|' read -r EID WFNAME; do
  [ -z "$EID" ] && continue
  # cheap fingerprint: workflow name + the start of the node's error message. execution_data's
  # dedup format means the "message"/"stack" KEYS just hold index refs (e.g. "stack":"28"), not
  # inline text -- but the actual stack string is present verbatim elsewhere in the same blob,
  # always shaped "<ErrorClassName>: <message>\n    at ...". Grep that shape directly instead of
  # trying to resolve the index. Empty for pure orphan-crashes (no error recorded at all) -- those
  # correctly collapse to one "<workflow>|" fingerprint instead of drowning out real classes.
  MSG=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc \
    "select data from execution_data where \"executionId\"=$EID" 2>/dev/null \
    | grep -oE '"(NodeApiError|WorkflowCrashedError|ExpressionError|NodeOperationError|Error): [^\\"]{5,120}' \
    | head -1 | sed 's/^"//')
  FP=$(printf '%s' "${WFNAME}|${MSG}" | tr -d '\n' | md5sum | cut -d' ' -f1)
  echo "${FP}|${WFNAME}|${MSG}" >> "$CUR_FILE.fp"
  if ! grep -q "^${FP}|" "$SEEN_FILE" 2>/dev/null; then
    NEW_COUNT=$((NEW_COUNT+1))
    echo "  NEW CLASS: [$WFNAME] $MSG  (exec $EID)"
  fi
done < "$CUR_FILE.ids"
echo "  ($NEW_COUNT new fingerprint(s) not seen in a prior run; state has $(wc -l < "$SEEN_FILE" 2>/dev/null || echo 0) known)"
sort -u "$CUR_FILE.fp" 2>/dev/null >> "$SEEN_FILE" 2>/dev/null
sort -u -o "$SEEN_FILE" "$SEEN_FILE" 2>/dev/null
rm -f "$CUR_FILE.ids" "$CUR_FILE.fp" "$CUR_FILE"

# ---- 4. stuck sync-ledger claims past timeout ----
if [ -n "$SUPA_PG" ]; then
  echo
  echo "--- sync_ledger claims older than ${CLAIM_TIMEOUT}m with no delivered_at ---"
  docker exec "$SUPA_PG" psql -U postgres -d postgres -tAc "
    select source, instance, count(*), min(claimed_at), now()-min(claimed_at) as oldest_age
    from sync_ledger
    where claimed_at < now() - interval '${CLAIM_TIMEOUT} minutes' and delivered_at is null
    group by source, instance
    order by 3 desc" | sed 's/^/  /'
  echo "  sync_ledger status totals (all time):"
  docker exec "$SUPA_PG" psql -U postgres -d postgres -tAc "select status, count(*) from sync_ledger group by 1 order by 2 desc" | sed 's/^/    /'
else
  echo
  echo "--- sync_ledger: no supabase-db-* container found, skipped ---"
fi

# ---- 5. endpoint timings vs 40s console-proxy budget ----
if [ -n "$N8N_MAIN" ] && [ -n "$INCOMING" ]; then
  echo
  echo "--- /incomingDocuments/sync/* timings vs 40s budget ---"
  for p in registry inventory items; do
    S=$(date +%s)
    if docker exec "$N8N_MAIN" wget -qO /dev/null -T 40 \
        "http://${INCOMING}:8080/incomingDocuments/sync/${p}" 2>/dev/null; then
      OK=ok
    else
      OK=FAIL
    fi
    E=$(date +%s)
    ELAPSED=$((E-S))
    PCT=$((ELAPSED*100/40))
    echo "  /sync/${p}: ${ELAPSED}s (${PCT}% of 40s budget), ${OK}"
  done
else
  echo
  echo "--- endpoint timings: n8n or incoming-documents container not found, skipped ---"
fi

# ---- 6. ERROR-CLASS CENSUS with restart-orphan correlation (opt-in: it scans hours, not minutes) --
#
#   CENSUS_HOURS=24 bash scripts/ops/error-pulse.sh
#
# WHY THIS EXISTS, AND WHY IT DOES NOT USE THE JOURNAL. Section 0 above records the docker DAEMON's
# start time, which is the right confound to name on a per-pulse basis. It is the WRONG reference to
# correlate a historical census against, and correlating against it UNDERCOUNTS badly:
#   * an n8n CONTAINER restart (`dcx restart n8n`, the tail of every `bbox n8n push`, health-guard,
#     quiet-mode) orphans every in-flight execution and never appears as a "Starting Docker
#     Application Container Engine" line at all;
#   * measured 2026-08-06: 29 daemon starts in the journal, but 34 distinct mass-teardown events
#     visible in execution_entity. Correlating drive-api/Settings/etc. against the journal alone
#     scored several classes at 0-6% that the teardown reference scores at 96-100%.
#
# So the reference here is derived from the DATA and is self-evidencing: a "mass-stop instant" is
# many executions across SEVERAL DIFFERENT workflows all stopping inside the same second. Nothing
# but a process/container/VM teardown does that — a real defect does not fail six unrelated
# workflows on the same second. No journal, no systemd, works identically on the VPS.
#
# READ THE OUTPUT AS: orphan_pct vs the printed CHANCE baseline.
#   ~chance      -> REAL. The restart story does not explain it. Root-cause it.
#   90-100%      -> orphan. Do not open a task; it is teardown debris.
#   in between   -> mixed; the class has both, split it before drawing conclusions.
# Median duration is the corroborating signal: sub-15s medians cannot be "interrupted mid-run",
# and multi-hundred-second medians with no error payload usually can.
if [ -n "${CENSUS_HOURS:-}" ]; then
  echo
  echo "--- error-class census + teardown-orphan correlation (last ${CENSUS_HOURS}h) ---"
  # Chance that a uniformly-random timestamp lands within +/-2s of one of N mass-stop instants.
  MS=$(docker exec "$N8N_PG" psql -U hacohen -d n8n -tAc "
    select count(*) from (
      select date_trunc('second', \"stoppedAt\")
      from execution_entity
      where \"stoppedAt\" > now() - interval '${CENSUS_HOURS} hours'
        and status in ('crashed','error')
      group by 1 having count(*) >= 8 and count(distinct \"workflowId\") >= 2) t" 2>/dev/null | tr -d ' \r')
  if [ -n "${MS}" ] && [ "${MS}" -gt 0 ] 2>/dev/null; then
    CH=$(awk -v n="$MS" -v h="$CENSUS_HOURS" 'BEGIN{p=n*4/(h*3600); if(p>1)p=1; printf "%.2f", p*100}')
    echo "  mass-stop (teardown) instants: ${MS}   window +/-2s   CHANCE BASELINE: ${CH}%"
    echo "  (a class scoring near ${CH}% is REAL; near 100% is teardown debris)"
  else
    echo "  no mass-stop instants found in the window — every class below is unexplained by teardown."
  fi
  # The reporter/handler pair is excluded BY DEFAULT: when glitchtipReporter01 cannot reach its sink
  # it fails once per real error, and until 2026-08-06 it also span a self-sustaining cycle with
  # errorHandler01 (~2,900 exec/hour, 93% of the error board). Leaving them in makes every other
  # class unreadable. Set CENSUS_ALL=1 to include them.
  EXCL="and e.\"workflowId\" not in ('glitchtipReporter01','errorHandler01')"
  [ -n "${CENSUS_ALL:-}" ] && EXCL=""
  docker exec "$N8N_PG" psql -U hacohen -d n8n -c "
    with stops as (
      select date_trunc('second', \"stoppedAt\") as s
      from execution_entity
      where \"stoppedAt\" > now() - interval '${CENSUS_HOURS} hours' and status in ('crashed','error')
      group by 1 having count(*) >= 8 and count(distinct \"workflowId\") >= 2),
    cls as (
      select w.name as wf, e.status, e.\"stoppedAt\" as sp,
             extract(epoch from (e.\"stoppedAt\"-e.\"startedAt\")) as dur
      from execution_entity e join workflow_entity w on w.id = e.\"workflowId\"
      where e.status in ('error','crashed')
        and e.\"startedAt\" > now() - interval '${CENSUS_HOURS} hours' ${EXCL})
    select wf as workflow, status, count(*) as n,
           round(100.0*count(*) filter (where exists (
             select 1 from stops r where abs(extract(epoch from (cls.sp - r.s))) <= 2))/count(*),1)
             as orphan_pct,
           round(percentile_cont(0.5) within group (order by dur)::numeric,1) as median_s
    from cls group by 1,2 having count(*) >= 10
    order by 3 desc limit 30;" 2>/dev/null | sed 's/^/  /'
fi

echo
echo "================================================================"
echo "error-pulse done  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "================================================================"
