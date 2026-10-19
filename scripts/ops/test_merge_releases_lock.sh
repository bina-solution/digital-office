#!/bin/bash
# REGRESSION TEST: a completed MERGE must release the doc_action lock it took.
#
# 'API Unlock Doc' is fed only by 'API Emit IDs' on the upsert path, and its note calls the upsert
# "the one step every action necessarily ends with". That is true of every action except a merge:
# the MERGE branch ends at PG Merge Write -> Merge Result, and nothing on it unlocked. Audited
# 2026-08-23: 977 of 1,203 live doc_action locks were ::action_merge_doubles, and 364 of a
# 400-document sample held a live lock against a CLOSED dispatch bracket -- 81% of the lock
# population owned by actions that had already finished, clearing only by TTL (measured to 4,358s).
#
# The consequence is not a slow merge, it is a document that cannot be re-attempted for over an
# hour, which reads from outside as a converging backlog and is really a feeder talking to itself.
#
# Asserts three things, in order, because only the third is the fix:
#   LIVENESS  a merge actually happened (a no-op run must never read as a pass)
#   MERGED    one row absorbed the other
#   UNLOCKED  neither row still holds a doc_action lock
set -u
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
RP=$(grep -E '^REDIS_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
P=zzml$(date +%H%M%S)

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents
 ("ID","COMPANY_ID","DOC_ID","SHORT_DOC_ID","HASH","TYPE","STATUS","DOC_DATE","DOC_TOTAL_AMOUNT",
  "SOURCE_TYPE","BASE_EXTRACTION_COMPLETED","PER_TYPE_EXTRACTION_COMPLETED","SELECTION_COMPLETED",created_at)
VALUES
 ('${P}_1','970000311','ZZMLOCK311','3111','zzmlHASH1','INVOICE','ACTION_RESTART','09/08/2026','610','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${P}_2','970000311','ZZMLOCK311','3112','zzmlHASH2','INVOICE','ACTION_RESTART','09/08/2026','610','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour');
SET session_replication_role = origin;
SELECT '  seeded merge pair ${P}_1 / ${P}_2';
SQL

for s in 1 2; do
  $DK exec -e I="${P}_1,${P}_2" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t.slice(0,56))))
 .catch(e=>console.log("  ERR "+e.message));'
  sleep 150
done

echo "  --- result ---"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    '||rpad(\"ID\",14)||rpad(coalesce(\"STATUS\",'-'),16)||'into='||coalesce(\"MERGED_INTO\",'-')
  FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%' ORDER BY \"ID\""

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    LIVENESS : '||CASE WHEN (SELECT count(*) FROM public.indox_action_execution_log
      WHERE \"ID\" LIKE '${P}%' AND \"ACTION\"='action_merge_doubles')>0
    THEN 'ok -- a merge was dispatched' ELSE 'VOID -- no merge dispatched, verdicts below mean nothing' END;
  SELECT '    MERGED   : '||CASE WHEN (SELECT count(*) FROM public.incoming_documents
      WHERE \"ID\" LIKE '${P}%' AND \"STATUS\"='MERGED')=1
    THEN 'PASS (one absorbed)' ELSE 'FAIL' END"

LOCKS=$($DK exec -e RP="$RP" redis-shlomo-laptop sh -lc \
  "redis-cli -a \"\$RP\" --no-auth-warning --scan --pattern 'n8n.process_lock.doc_action.${P}*' 2>/dev/null" \
  | tr -d '\r' | grep -c . || true)
echo "    UNLOCKED : $( [ "${LOCKS:-0}" -eq 0 ] && echo 'PASS (no doc_action lock left on either row)' || echo "FAIL ($LOCKS lock(s) still held)" )"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "DELETE FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${P}%';
  DELETE FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%'" >/dev/null 2>&1
$DK exec -e RP="$RP" redis-shlomo-laptop sh -lc \
  "for k in \$(redis-cli -a \"\$RP\" --no-auth-warning --scan --pattern 'n8n.process_lock.doc_action.${P}*' 2>/dev/null); do redis-cli -a \"\$RP\" --no-auth-warning DEL \"\$k\" >/dev/null; done" 2>/dev/null
echo "  (fixtures removed)"
