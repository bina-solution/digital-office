#!/bin/bash
# A REAL TEST, not a spot check: build synthetic duplicate groups whose correct outcome is known
# in advance, run them through the LIVE pipeline (driver -> decide -> router -> adjudicator ->
# indoxApi01), assert what the table says, then delete the fixtures.
#
# Every case that used to have its own branch is here, and under the owner's rule they must ALL
# end the same way: exactly one survivor, everyone else MERGED with provenance.
#
#   T1 same-hash pair              -> merge (tier: same-hash)
#   T2 two rows agreeing           -> merge (tier: two-rows-agree)
#   T3 CONFLICTED (amounts differ) -> merge anyway, conflict recorded, NOT vetoed
#   T4 junk doc-id (BAD_DOC_ID)    -> merge anyway, no special branch
#   T5 three members               -> one survivor, two MERGED
#   T6 lone row, no twin           -> untouched, never flagged double
DK="docker -H unix:///run/bbox-docker.sock"
S=/mnt/c/Users/user/AppData/Local/Temp/claude/C--Users-user/90c9fa3b-f7b6-4d07-8cb7-84e965839620/scratchpad
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
WU=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
WP=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
PFX='zzdup'

cleanup () {
  $DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
    "DELETE FROM public.incoming_documents WHERE \"ID\" LIKE '${PFX}%'" >/dev/null 2>&1
  $DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
    "DELETE FROM public.indox_action_execution_log WHERE \"ID\" LIKE '${PFX}%'" >/dev/null 2>&1
}
trap cleanup EXIT
cleanup

echo "=== seeding fixtures ==="
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents
 ("ID","COMPANY_ID","DOC_ID","HASH","TYPE","STATUS","DOC_DATE","DOC_TOTAL_AMOUNT","SOURCE_TYPE",
  "BASE_EXTRACTION_COMPLETED","PER_TYPE_EXTRACTION_COMPLETED","SELECTION_COMPLETED",created_at)
VALUES
 -- T1 same hash
 ('${PFX}_t1_a','990000001','TSTA001','hhhhAAAA','INVOICE','ACTION_RESTART','01/08/2026','100','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${PFX}_t1_b','990000001','TSTA001','hhhhAAAA','INVOICE','ACTION_RESTART','01/08/2026','100','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- T2 agree on type+date+amount, different hash
 ('${PFX}_t2_a','990000002','TSTB002','hhhhBBB1','INVOICE','ACTION_RESTART','02/08/2026','250','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${PFX}_t2_b','990000002','TSTB002','hhhhBBB2','INVOICE','ACTION_RESTART','02/08/2026','250','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- T3 CONFLICTED: amounts differ (old rule vetoed this)
 ('${PFX}_t3_a','990000003','TSTC003','hhhhCCC1','INVOICE','ACTION_RESTART','03/08/2026','300','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${PFX}_t3_b','990000003','TSTC003','hhhhCCC2','INVOICE','ACTION_RESTART','03/08/2026','999','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- T4 junk doc-id
 ('${PFX}_t4_a','990000004','000','hhhhDDDD','INVOICE','ACTION_RESTART','04/08/2026','400','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${PFX}_t4_b','990000004','000','hhhhDDDD','INVOICE','ACTION_RESTART','04/08/2026','400','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- T5 three members
 ('${PFX}_t5_a','990000005','TSTE005','hhhhEEE1','INVOICE','ACTION_RESTART','05/08/2026','500','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '3 hours'),
 ('${PFX}_t5_b','990000005','TSTE005','hhhhEEE2','INVOICE','ACTION_RESTART','05/08/2026','500','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '2 hours'),
 ('${PFX}_t5_c','990000005','TSTE005','hhhhEEE3','INVOICE','ACTION_RESTART','05/08/2026','500','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour'),
 -- T6 lone row
 ('${PFX}_t6_a','990000006','TSTF006','hhhhFFF1','INVOICE','ACTION_RESTART','06/08/2026','600','GOOGLE_DRIVE_FILE','true','true','true', now() - interval '1 hour');
SET session_replication_role = origin;
SELECT '  seeded ' || count(*) || ' fixture rows' FROM public.incoming_documents WHERE "ID" LIKE '${PFX}%';
SQL

echo "=== driving them through the real pipeline (3 sweeps) ==="
IDS=$($DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
  "SELECT string_agg(\"ID\", ',') FROM public.incoming_documents WHERE \"ID\" LIKE '${PFX}%'" | tr -d '\r')
for pass in 1 2 3; do
  $DK exec -e I="$IDS" -e U="$WU" -e P="$WP" n8n-shlomo-laptop node -e '
  const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
  fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
   headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
   body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
   .then(r=>r.text().then(t=>console.log("  sweep '"$pass"': "+r.status+" "+t.slice(0,70))))
   .catch(e=>console.log("  ERR "+e.message));'
  sleep 45
done

echo "=== RESULT ==="
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<SQL
SELECT '  ' || rpad("ID",14) || rpad(coalesce("STATUS",'-'),16)
    || 'merged_into=' || rpad(coalesce("MERGED_INTO",'-'),14)
    || 'batch=' || (CASE WHEN "MERGE_BATCH_ID" IS NULL THEN 'no ' ELSE 'yes' END)
    || ' cause=' || coalesce("DUP_CAUSE",'-')
FROM public.incoming_documents WHERE "ID" LIKE '${PFX}%' ORDER BY "ID";

SELECT E'\n  --- assertions ---';
WITH f AS (SELECT * FROM public.incoming_documents WHERE "ID" LIKE '${PFX}%'),
g AS (SELECT "COMPANY_ID" c, count(*) n,
             count(*) FILTER (WHERE "STATUS"='MERGED') m,
             count(*) FILTER (WHERE "STATUS" <> 'MERGED') s
      FROM f GROUP BY "COMPANY_ID")
SELECT '  ' || rpad(c,12)
    || 'members=' || n || '  merged=' || m || '  survivors=' || s
    || CASE WHEN n > 1 AND s = 1 AND m = n-1 THEN '   PASS'
            WHEN n = 1 AND m = 0 THEN '   PASS (lone row untouched)'
            ELSE '   FAIL' END
FROM g ORDER BY c;

SELECT E'\n  repeat check (a loop would show >1):';
SELECT '  max dispatches for one fixture doc+action = ' || COALESCE(max(c),0)
FROM (SELECT count(*) c FROM public.indox_action_execution_log
      WHERE "ID" LIKE '${PFX}%' GROUP BY "ID","ACTION") x;
SQL
