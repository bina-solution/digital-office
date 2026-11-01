#!/bin/bash
# Did my quarantine suppress REAL duplicates? For each quarantined doc-id, are its rows actually
# the same document (shared HASH, or same date+amount)? If yes, the quarantine is hiding a merge.
DK="docker -H unix:///run/bbox-docker.sock"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<'SQL'
SET statement_timeout='240s';
WITH bad AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"),'') <> ''
    AND length(regexp_replace(btrim("DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
  GROUP BY 1 HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3),
rows AS (
  SELECT d.*, btrim(d."DOC_ID") did FROM public.incoming_documents d
  JOIN bad b ON b.did = btrim(d."DOC_ID")
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED'),
-- within one quarantined doc-id, do any two rows share a real HASH? that would be a true duplicate
dup AS (
  SELECT did, btrim("HASH") h, count(*) n
  FROM rows
  WHERE coalesce(btrim("HASH"),'') <> '' AND lower(btrim("HASH")) <> 'unknown'
  GROUP BY 1,2 HAVING count(*) > 1)
SELECT '  quarantined doc-ids whose rows SHARE a real HASH = '||count(DISTINCT did)
     ||'   (these would be caught by the HASH tier anyway)' FROM dup;

-- and do any share company+date+amount (same doc, different hash e.g. rescan)?
WITH bad AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"),'') <> ''
    AND length(regexp_replace(btrim("DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
  GROUP BY 1 HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3),
rows AS (
  SELECT d.*, btrim(d."DOC_ID") did FROM public.incoming_documents d
  JOIN bad b ON b.did = btrim(d."DOC_ID")
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED'),
same AS (
  SELECT did, btrim("COMPANY_ID") co, btrim("DOC_DATE") dt, btrim("DOC_TOTAL_AMOUNT") amt, count(*) n
  FROM rows
  WHERE coalesce(btrim("COMPANY_ID"),'') <> '' AND coalesce(btrim("DOC_DATE"),'') <> ''
  GROUP BY 1,2,3,4 HAVING count(*) > 1)
SELECT '  quarantined doc-ids with 2+ rows under the SAME company AND same date+amount = '
     ||count(DISTINCT did)||'   <- real duplicates the quarantine now hides' FROM same;

WITH bad AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"),'') <> ''
    AND length(regexp_replace(btrim("DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
  GROUP BY 1 HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3),
rows AS (
  SELECT d.*, btrim(d."DOC_ID") did FROM public.incoming_documents d
  JOIN bad b ON b.did = btrim(d."DOC_ID")
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED')
SELECT '    '||rpad(did,16)||rpad(coalesce(btrim("COMPANY_ID"),'-'),12)
     ||rpad(coalesce(btrim("DOC_DATE"),'-'),12)||rpad(coalesce(btrim("DOC_TOTAL_AMOUNT"),'-'),10)
     ||'hash='||coalesce(left(btrim("HASH"),10),'-')
FROM rows WHERE did = 'SH26000114' ORDER BY "COMPANY_ID";
SQL
