#!/bin/bash
# Turn on action_priority_sync AGAINST THE LOCAL MOCK, and prove on a small cohort before volume.
#
# THE ONE THING THAT MATTERS: `indox.actions.priority_sync.local` must be 'true' before
# activePrioritySync is flipped. That setting is the only thing standing between this action and
# the client's real ERP at https://msh.macomp.vip/... -- the router resolves per item:
#
#   __priority_local === false ? <client ERP> : <priorityLocalApi01>
#
# The default is inverted on purpose (COALESCE(..., true) in the driver) so a MISSING settings row
# means "keep it local", never "post to the client". This script refuses to flip if that check
# does not read exactly 'true' -- a missing or malformed row aborts rather than proceeding.
#
# usage: enable_priority_sync_local.sh check      -- preconditions only, changes nothing
#        enable_priority_sync_local.sh on <n>     -- flip, then feed n COMPLETED docs and verify
#        enable_priority_sync_local.sh off        -- flip back
set -u
DK="docker -H unix:///run/bbox-docker.sock"
PSQL="$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env

local_mode () {
  $PSQL "SELECT lower(btrim(value)) FROM public.settings
         WHERE key='indox.actions.priority_sync.local' LIMIT 1" | tr -d '\r '
}
active_mode () {
  $PSQL "SELECT lower(btrim(value)) FROM public.settings
         WHERE key='activePrioritySync' LIMIT 1" | tr -d '\r '
}
mirror_rows () {
  $PSQL "SELECT count(*) FROM public.indox_priority_local" | tr -d '\r '
}

require_local () {
  local m; m=$(local_mode)
  echo "  indox.actions.priority_sync.local = '${m:-<missing>}'"
  if [ "$m" != "true" ]; then
    echo "  ABORT: local mode is not 'true'. Flipping activePrioritySync now would post to the"
    echo "         CLIENT'S ERP. Set the setting first, or leave this off."
    exit 1
  fi
  local w; w=$($DK exec -i n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -tAc \
    "SELECT active::text FROM workflow_entity WHERE id='priorityLocalApi01'" | tr -d '\r ')
  echo "  priorityLocalApi01 active = '${w:-<missing>}'"
  [ "$w" = "true" ] || { echo "  ABORT: the local mock is not active; there is nowhere safe to send."; exit 1; }
}

case "${1:-check}" in
  check)
    require_local
    echo "  activePrioritySync = $(active_mode)"
    echo "  local mirror rows  = $(mirror_rows)"
    echo "  preconditions OK"
    ;;
  on)
    N="${2:-20}"
    require_local
    BEFORE=$(mirror_rows)
    echo "  mirror rows before = $BEFORE"
    $PSQL "UPDATE public.settings SET value='true' WHERE key='activePrioritySync'"
    echo "  activePrioritySync = $(active_mode)"

    IDS=$($PSQL "SELECT string_agg(\"ID\", ',') FROM (
            SELECT \"ID\" FROM public.incoming_documents
            WHERE \"STATUS\"='COMPLETED'
              AND lower(coalesce(\"PRIORITY_SYNC_COMPLETED\",'')) <> 'true'
            ORDER BY updated_at DESC LIMIT $N) t" | tr -d '\r')
    CNT=$(echo "$IDS" | tr ',' '\n' | grep -c .)
    echo "  feeding $CNT COMPLETED document(s) as the proof cohort"
    [ "$CNT" -eq 0 ] && { echo "  nothing to feed"; exit 0; }

    wu=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
    wp=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
    $DK exec -e I="$IDS" -e U="$wu" -e P="$wp" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t.slice(0,56))))
 .catch(e=>console.log("  ERR "+e.message));'
    sleep 150

    AFTER=$(mirror_rows)
    echo "  mirror rows after  = $AFTER   (delta $((AFTER - BEFORE)))"
    $PSQL "SELECT '  dispatched action_priority_sync in last 5m = '||count(*)
           FROM public.indox_action_execution_log
           WHERE \"ACTION\"='action_priority_sync' AND \"STARTED_AT\" > now() - interval '5 minutes'"
    echo "  LIVENESS: $( [ "$((AFTER - BEFORE))" -gt 0 ] && echo "PASS -- $((AFTER - BEFORE)) row(s) landed in the LOCAL mirror" || echo 'VOID -- nothing reached the mirror; do not read anything into the absence of client traffic' )"
    ;;
  off)
    $PSQL "UPDATE public.settings SET value='false' WHERE key='activePrioritySync'"
    echo "  activePrioritySync = $(active_mode)"
    ;;
  *) echo "usage: $0 check|on [n]|off"; exit 2;;
esac
