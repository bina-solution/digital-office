#!/bin/bash
# REGRESSION TEST: a DOC_ID shared by 3+ companies must not form a duplicate group at all,
# and an ordinary business duplicate must still merge.
#
# The detector used to key on any doc-id. 'Adjudicate Merge' then refused to merge groups whose
# doc-id spans 3+ companies -- correctly, because those are different documents whose id was
# mis-extracted. The two disagreed, so the group had no terminal state: raised, refused, nothing
# written, raised again. Five mains reached 146 dispatches. The quarantine now lives in the KEY.
#
# Case A: doc-id 'ZZBADID999' under three companies, with TWO rows under one of them. Under the
#         old key those two are a duplicate pair and would be raised forever. They must now not be
#         raised at all -- and must NOT be merged either, since they are not duplicates.
# Case B: an ordinary two-row business duplicate, untouched by the quarantine. Must still merge.
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
P=zzbd$(date +%H%M%S)

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents
 ("ID","COMPANY_ID","DOC_ID","SHORT_DOC_ID","HASH","TYPE","STATUS","DOC_DATE","DOC_TOTAL_AMOUNT",
  "SOURCE_TYPE","BASE_EXTRACTION_COMPLETED","PER_TYPE_EXTRACTION_COMPLETED","SELECTION_COMPLETED",created_at)
VALUES
 -- A: the same bad doc-id under THREE companies; two rows share company 990000101
 ('${P}_a1','990000101','ZZBADID999','9901','zzbadHASHA1','INVOICE','ACTION_RESTART','09/08/2026','100','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '3 hours'),
 ('${P}_a2','990000101','ZZBADID999','9902','zzbadHASHA2','INVOICE','ACTION_RESTART','09/08/2026','200','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${P}_a3','990000102','ZZBADID999','9903','zzbadHASHA3','INVOICE','ACTION_RESTART','09/08/2026','300','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 ('${P}_a4','990000103','ZZBADID999','9904','zzbadHASHA4','INVOICE','ACTION_RESTART','09/08/2026','400','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '30 minutes'),
 -- B: an ordinary business duplicate, one company, a doc-id nobody else uses
 ('${P}_b1','990000104','ZZGOODID77','7701','zzbadHASHB1','INVOICE','ACTION_RESTART','09/08/2026','500','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${P}_b2','990000104','ZZGOODID77','7702','zzbadHASHB2','INVOICE','ACTION_RESTART','09/08/2026','500','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour');
SET session_replication_role = origin;
SELECT '  seeded: ZZBADID999 under 3 companies (2 rows share one) + one ordinary pair';
SQL

for s in 1 2; do
  $DK exec -e I="${P}_a1,${P}_a2,${P}_a3,${P}_a4,${P}_b1,${P}_b2" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t.slice(0,60))))
 .catch(e=>console.log("  ERR "+e.message));'
  # 80s was not enough. The drain is accepted immediately, but its driver run queues behind
  # whatever else is in flight -- with a 4,000-dispatch wave running, six fixture ids waited out
  # the whole window and produced zero dispatches, twice. Long enough to outlast a busy stretch.
  sleep 150
done

echo "  --- result ---"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    '||rpad(\"ID\",16)||rpad(coalesce(\"STATUS\",'-'),16)||'into='||coalesce(\"MERGED_INTO\",'-')
  FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%' ORDER BY \"ID\""

# LIVENESS GATE -- assert the drain actually did something before believing any verdict.
# The first run of this fixture reported "QUARANTINE : PASS" while NOTHING had been dispatched:
# all six rows sat untouched in ACTION_RESTART. "No merge happened" is equally true when the
# quarantine works and when the drain never ran, so the pass was worthless. The control case
# failing is what exposed it. A fixture that cannot tell those apart is not a test.
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    LIVENESS   : '||CASE WHEN (SELECT count(*) FROM public.indox_action_execution_log
      WHERE \"ID\" LIKE '${P}%')>0
    THEN 'ok ('||(SELECT count(*) FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${P}%')||' dispatch(es)) -- verdicts below are meaningful'
    ELSE 'VOID -- nothing was dispatched; the verdicts below mean nothing, re-run when the system is quiet' END"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '    QUARANTINE : '||CASE WHEN (SELECT count(*) FROM public.incoming_documents
      WHERE \"ID\" LIKE '${P}_a%' AND \"STATUS\"='MERGED')=0
    THEN 'PASS (bad doc-id never merged)' ELSE 'FAIL (a bad-doc-id row was absorbed)' END;
  SELECT '    NO REGRESSION: '||CASE WHEN (SELECT count(*) FROM public.incoming_documents
      WHERE \"ID\" LIKE '${P}_b%' AND \"STATUS\"='MERGED')=1
    THEN 'PASS (ordinary pair still merged)' ELSE 'FAIL (ordinary pair did not merge)' END"

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "DELETE FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${P}%';
  DELETE FROM public.incoming_documents WHERE \"ID\" LIKE '${P}%'" >/dev/null 2>&1
echo "  (fixtures removed)"
