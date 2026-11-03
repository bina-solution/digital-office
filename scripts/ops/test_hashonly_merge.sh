#!/bin/bash
# REGRESSION TEST: hash-only duplicates must merge.
# The exact shape of the 18 stuck rows -- NO COMPANY_ID, NO DOC_ID, NO SHORT_DOC_ID, only a shared
# HASH. The detector matches them on the hash key; before this fix the adjudicator regrouped on
# the business key alone, skipped them, emitted nothing, and they were re-raised every sweep.
# Also asserts the biz path still works, so the key-precedence change did not break the normal case.
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
P=zzho$(date +%H%M%S)

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents
 ("ID","COMPANY_ID","DOC_ID","SHORT_DOC_ID","HASH","TYPE","STATUS","DOC_DATE","DOC_TOTAL_AMOUNT",
  "SOURCE_TYPE","BASE_EXTRACTION_COMPLETED","PER_TYPE_EXTRACTION_COMPLETED","SELECTION_COMPLETED",created_at)
VALUES
 -- A: hash-only pair, nothing else to key on  (the stuck-18 shape)
 ('${P}_h1',NULL,NULL,NULL,'hhhhHASHONLY1','INVOICE','ACTION_RESTART','09/08/2026','900','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${P}_h2',NULL,NULL,NULL,'hhhhHASHONLY1','INVOICE','ACTION_RESTART','09/08/2026','900','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- B: ordinary business-key pair, must still merge (no regression)
 ('${P}_b1','990000099','HOB0099','99','hhhhHOB991','INVOICE','ACTION_RESTART','09/08/2026','910','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${P}_b2','990000099','HOB0099','99','hhhhHOB992','INVOICE','ACTION_RESTART','09/08/2026','910','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour');
SET session_replication_role = origin;
SELECT '  seeded: hash-only pair + business-key pair';
SQL

$DK exec -e I="${P}_h1,${P}_h2,${P}_b1,${P}_b2" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain 1: "+r.status+" "+t.slice(0,70))))
 .catch(e=>console.log("  ERR "+e.message));'
sleep 70
# SECOND SWEEP. Sweep 1 flags the non-main DOUBLE and dispatches the main's merge; the merge
# itself lands on the following pass. One sweep is not the contract -- convergence is.
$DK exec -e I="${P}_h1,${P}_h2,${P}_b1,${P}_b2" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain 2: "+r.status+" "+t.slice(0,70))))
 .catch(e=>console.log("  ERR "+e.message));'
sleep 80

echo "  --- result ---"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    '||rpad(\"ID\",16)||rpad(coalesce(\"STATUS\",'-'),16)||'into='||coalesce(\"MERGED_INTO\",'-')
  FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%' ORDER BY \"ID\""

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    HASH-ONLY : '||CASE WHEN (SELECT count(*) FROM public.incoming_documents
      WHERE \"ID\" IN ('${P}_h1','${P}_h2') AND \"STATUS\"='MERGED')=1
    THEN 'PASS (one absorbed)' ELSE 'FAIL (still unmerged)' END;
  SELECT '    BUSINESS  : '||CASE WHEN (SELECT count(*) FROM public.incoming_documents
      WHERE \"ID\" IN ('${P}_b1','${P}_b2') AND \"STATUS\"='MERGED')=1
    THEN 'PASS (no regression)' ELSE 'FAIL' END"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "DELETE FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${P}%';
  DELETE FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%'" >/dev/null 2>&1
echo "  (fixtures removed)"
