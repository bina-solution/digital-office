#!/bin/bash
# Does the TEXT-boolean fix actually unblock a real stuck row? Pick an IN_PROGRESS document whose
# BASE_EXTRACTION_COMPLETED is the string 'false' and which holds NO lock, feed it, and see whether
# extract_base_doc is dispatched. Before the fix `!doc.BASE_EXTRACTION_COMPLETED` was false for
# exactly these rows and the action was never chosen.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
RP=$(grep -E '^REDIS_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
L=/tmp/pu_locks_$$.txt

$DK exec -e RP="$RP" redis-shlomo-laptop sh -lc \
  'redis-cli -a "$RP" --no-auth-warning --scan --pattern "n8n.process_lock.doc_action.*" 2>/dev/null' \
  | sed -e 's/^n8n[.]process_lock[.]doc_action[.]//' -e 's/::.*$//' | tr -d '\r' | sort -u > "$L"

CAND=$($DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
  "SELECT \"ID\" FROM public.incoming_documents
   WHERE \"STATUS\"='IN_PROGRESS' AND \"BASE_EXTRACTION_COMPLETED\"='false'
   ORDER BY updated_at ASC LIMIT 400" | tr -d '\r' | grep -v '^$')
ID=$(printf '%s\n' "$CAND" | grep -Fxv -f "$L" | head -1)
rm -f "$L"
if [ -z "$ID" ]; then echo "  no unlocked candidate right now"; exit 0; fi
echo "  candidate: $ID"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '  before: status='||\"STATUS\"||'  base_extraction='||coalesce(\"BASE_EXTRACTION_COMPLETED\",'<null>')
  FROM public.incoming_documents WHERE \"ID\"='$ID'"
BEFORE=$($DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT count(*) FROM public.indox_action_execution_log WHERE \"ID\"='$ID'" | tr -d '\r ')

$DK exec -e I="$ID" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:[process.env.I],dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t.slice(0,56))))
 .catch(e=>console.log("  ERR "+e.message));'
sleep 150

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '  dispatch: '||\"ACTION\"||'  end='||coalesce(\"ENDED_AT\"::text,'OPEN')
  FROM public.indox_action_execution_log WHERE \"ID\"='$ID' ORDER BY \"STARTED_AT\" DESC LIMIT 3"
AFTER=$($DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT count(*) FROM public.indox_action_execution_log WHERE \"ID\"='$ID'" | tr -d '\r ')
echo "  dispatch rows: $BEFORE -> $AFTER"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '  after : status='||\"STATUS\"||'  base_extraction='||coalesce(\"BASE_EXTRACTION_COMPLETED\",'<null>')
  FROM public.incoming_documents WHERE \"ID\"='$ID'"
if [ "${AFTER:-0}" -gt "${BEFORE:-0}" ]; then
  echo "  UNBLOCKED: PASS -- the row was dispatched an action it could not receive before"
else
  echo "  UNBLOCKED: VOID/FAIL -- no new dispatch; do not conclude the fix works from this run"
fi
