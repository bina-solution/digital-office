#!/usr/bin/env bash
# One-shot acceptance harness for the 150-doc fresh-start goal.
#   seed:    inject N docs into each of the 5 sync registries (default N=30) = the "existing files"
#   reset:   full indox reset -> all to initial sync state (table cleared, sources re-queued to_sync)
#   trigger: kick the Sync Scanner
#   measure: print the acceptance scorecard
#   full:    seed -> reset -> trigger   (then run `measure` repeatedly to watch the 20-min window)
# Usage: ./scripts/acceptance-run.sh <seed|reset|trigger|measure|full> [N]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
CMD="${1:-measure}"; N="${2:-30}"; DN=shlomo-laptop
FULL_RESET_WF=IndoxResetFull01; SCANNER_WF=SyncScanner00001
EM=$(grep -E '^N8N_OWNER_EMAIL=' .env | cut -d= -f2-); PW=$(grep -E '^N8N_OWNER_PASSWORD=' .env | cut -d= -f2-)

cp_helpers(){ docker cp scripts/acceptance-gmail-post.js n8n-$DN:/tmp/acceptance-gmail-post.js >/dev/null
              docker cp scripts/acceptance-wf-trigger.js n8n-$DN:/tmp/acceptance-wf-trigger.js >/dev/null; }
trig(){ MSYS_NO_PATHCONV=1 docker exec -e N8N_OWNER_EMAIL="$EM" -e N8N_OWNER_PASSWORD="$PW" n8n-$DN node /tmp/acceptance-wf-trigger.js "$1"; }

seed_gmail(){ echo "[seed] gmail doc/bs/link x$N (pdfsrv must be up for link)"
  python scripts/_inject_gmail_direct.py --doc "$N" --bs "$N" --link "$N" --link-url http://pdfsrv:8088
  docker cp data/_runs/inject_payload.json n8n-$DN:/tmp/inject_payload.json >/dev/null
  MSYS_NO_PATHCONV=1 docker exec n8n-$DN node /tmp/acceptance-gmail-post.js; }
seed_drive(){ echo "[seed] drive gdoc(inv/ship/unk) + bs x$N"
  python scripts/highload-inject.py --drive-inv "$N" --drive-ship 0 --drive-unk 0 --drive-bs "$N"; }
ensure_pdfsrv(){ if ! docker ps --format '{{.Names}}'|grep -q '^pdfsrv$'; then
  MSYS_NO_PATHCONV=1 docker run -d --name pdfsrv --network traefik-network \
    -v "$(pwd -W 2>/dev/null||pwd)/data/data-set-2/invoice/files:/srv:ro" -w /srv python:3.12-slim python -m http.server 8088 >/dev/null
  echo "[pdfsrv] started"; sleep 3; fi; }

clear_state(){ echo "[clear] table + locks (fresh state; seeded sources untouched, accumulated NOT re-queued)"
  MSYS_NO_PATHCONV=1 docker exec supabase-db-$DN psql -U postgres -d postgres -c "delete from incoming_documents where \"ID\"<>'__bootstrap__';" 2>&1 | tail -1
  RP=$(grep -E '^REDIS_PASSWORD=' .env | cut -d= -f2-)
  for pat in 'doc_step*' 'indox*' '*lock*'; do
    MSYS_NO_PATHCONV=1 docker exec redis-$DN sh -lc "redis-cli -a '$RP' --no-auth-warning keys '$pat' 2>/dev/null | while read k; do redis-cli -a '$RP' --no-auth-warning del \"\$k\" >/dev/null; done" 2>/dev/null || true
  done
  echo "[clear] done"; }

case "$CMD" in
  seed)    cp_helpers; ensure_pdfsrv; seed_drive; seed_gmail ;;
  clear)   clear_state ;;
  reset)   cp_helpers; echo "[reset] full indox reset ($FULL_RESET_WF)"; trig "$FULL_RESET_WF" ;;
  trigger) cp_helpers; echo "[trigger] scanner ($SCANNER_WF)"; trig "$SCANNER_WF" ;;
  pscan)   docker cp scripts/acceptance-parallel-scan.js n8n-$DN:/tmp/acceptance-parallel-scan.js >/dev/null
           REG=$(MSYS_NO_PATHCONV=1 docker exec supabase-db-$DN psql -U postgres -d postgres -tAc "select value from settings where key='sync_registry'")
           echo "[pscan] firing all sync units CONCURRENTLY (Gap-A parallel registration)"
           MSYS_NO_PATHCONV=1 docker exec -e EM="$EM" -e PW="$PW" -e REG="$REG" n8n-$DN node /tmp/acceptance-parallel-scan.js ;;
  pdrain)  docker cp scripts/acceptance-parallel-scan.js n8n-$DN:/tmp/acceptance-parallel-scan.js >/dev/null
           REG=$(MSYS_NO_PATHCONV=1 docker exec supabase-db-$DN psql -U postgres -d postgres -tAc "select value from settings where key='sync_registry'")
           qdone(){ MSYS_NO_PATHCONV=1 docker exec supabase-db-$DN psql -U postgres -d postgres -tAc "select count(*) filter(where \"STATUS\"='COMPLETED') from incoming_documents where \"ID\"<>'__bootstrap__'"; }
           qrun(){ MSYS_NO_PATHCONV=1 docker exec n8n-postgres-$DN sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from execution_entity e join workflow_entity w on w.id=e.\"workflowId\" where w.name='"'"'Sync Scan Unit'"'"' and e.status='"'"'running'"'"'"'; }
           prev=-1; stall=0
           for r in $(seq 1 30); do
             echo "[pdrain] round $r: pscan"
             MSYS_NO_PATHCONV=1 docker exec -e EM="$EM" -e PW="$PW" -e REG="$REG" n8n-$DN node /tmp/acceptance-parallel-scan.js >/dev/null
             for w in $(seq 1 20); do sleep 6; [ "$(qrun)" = "0" ] && break; done   # wait this round's units to finish (avoid overlap)
             d=$(qdone); echo "[pdrain]   completed=$d"
             if [ "$d" = "$prev" ]; then stall=$((stall+1)); else stall=0; fi
             prev=$d
             [ $stall -ge 2 ] && echo "[pdrain] no progress 2 rounds -> drained/stalled, stop" && break
           done ;;
  full)    cp_helpers; ensure_pdfsrv; seed_drive; seed_gmail; echo "--- reset+trigger ---"; trig "$FULL_RESET_WF"; sleep 5; trig "$SCANNER_WF" ;;
  measure) MSYS_NO_PATHCONV=1 python scripts/acceptance-measure.py ;;
  *) echo "usage: $0 <seed|reset|trigger|measure|full> [N]"; exit 1 ;;
esac
