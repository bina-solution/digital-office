#!/bin/bash
# REGRESSION TEST for the pickWinner ordering bug.
# The exact shape that broke at volume: a COMPLETED row with ONE completion flag against an OLD
# row with THREE. Old order sorted completeness first, so OLD won and a deliverable document was
# demoted. COMPLETED must now win regardless of flag count.
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
P=zzpw$(date +%H%M%S)

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents
 ("ID","COMPANY_ID","DOC_ID","HASH","TYPE","STATUS","DOC_DATE","DOC_TOTAL_AMOUNT","SOURCE_TYPE",
  "BASE_EXTRACTION_COMPLETED","PER_TYPE_EXTRACTION_COMPLETED","SELECTION_COMPLETED",created_at)
VALUES
 -- OLD, fully extracted (3 flags), NEWER  -> under the old order this won
 ('${P}_old','990000088','PWR0088','hhhhPWR8','INVOICE','OLD','08/08/2026','800','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- COMPLETED, only 1 flag, OLDER          -> must win now
 ('${P}_cmp','990000088','PWR0088','hhhhPWR8','INVOICE','COMPLETED','08/08/2026','800','GOOGLE_DRIVE_FILE','true','false','false', now() - interval '2 hours');
SET session_replication_role = origin;
SELECT '  seeded: OLD(3 flags, newer) vs COMPLETED(1 flag, older)';
SQL

$DK exec -e I="${P}_old,${P}_cmp" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t.slice(0,70))))
 .catch(e=>console.log("  ERR "+e.message));'
sleep 60

echo "  --- result ---"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    '||rpad(\"ID\",18)||rpad(coalesce(\"STATUS\",'-'),12)||'into='||coalesce(\"MERGED_INTO\",'-')
  FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%' ORDER BY \"ID\""
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT CASE
    WHEN (SELECT \"STATUS\" FROM public.incoming_documents WHERE \"ID\"='${P}_cmp')='MERGED'
      THEN '    FAIL: the COMPLETED row was absorbed'
    WHEN (SELECT \"STATUS\" FROM public.incoming_documents WHERE \"ID\"='${P}_old')='MERGED'
      THEN '    PASS: COMPLETED survived, OLD absorbed'
    ELSE '    INCONCLUSIVE: neither merged yet' END"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "DELETE FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${P}%';
  DELETE FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%'" >/dev/null 2>&1
echo "  (fixtures removed)"
