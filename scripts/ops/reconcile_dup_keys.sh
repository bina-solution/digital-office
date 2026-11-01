#!/bin/bash
# Reconcile two duplicate counts: the RAW (COMPANY_ID, DOC_ID) pair vs the DETECTOR's key.
# Both are computed here, on the same snapshot, so the difference is attributable rather than
# argued about. Every group the raw key sees but the detector does not is listed with the reason.
DK="docker -H unix:///run/bbox-docker.sock"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<'SQL'
SET statement_timeout='180s';
WITH bad_docid AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"),'') <> ''
    AND length(regexp_replace(btrim("DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
  GROUP BY btrim("DOC_ID") HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
),
live AS (SELECT * FROM public.incoming_documents WHERE "STATUS" IS DISTINCT FROM 'MERGED'),
raw AS (
  SELECT btrim("COMPANY_ID")||'|'||btrim("DOC_ID") AS k, count(*) n,
         min(btrim("DOC_ID")) did, min(btrim("COMPANY_ID")) co
  FROM live
  WHERE coalesce(btrim("COMPANY_ID"),'') <> '' AND coalesce(btrim("DOC_ID"),'') <> ''
  GROUP BY 1 HAVING count(*) > 1
),
det AS (
  SELECT btrim("COMPANY_ID")||'|'||btrim("DOC_ID") AS k
  FROM live d
  WHERE coalesce(btrim(d."COMPANY_ID"),'') <> '' AND coalesce(btrim(d."DOC_ID"),'') <> ''
    AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
    AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
    AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
    AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
    AND btrim(d."DOC_ID") NOT IN (SELECT did FROM bad_docid)
  GROUP BY 1 HAVING count(*) > 1
)
SELECT '  raw (COMPANY_ID|DOC_ID) groups     = '||(SELECT count(*) FROM raw)
   ||E'\n  detector-keyed groups              = '||(SELECT count(*) FROM det)
   ||E'\n  seen by raw, NOT by the detector    = '||(SELECT count(*) FROM raw WHERE k NOT IN (SELECT k FROM det));

WITH bad_docid AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"),'') <> ''
    AND length(regexp_replace(btrim("DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
  GROUP BY btrim("DOC_ID") HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
),
live AS (SELECT * FROM public.incoming_documents WHERE "STATUS" IS DISTINCT FROM 'MERGED'),
raw AS (
  SELECT btrim("COMPANY_ID")||'|'||btrim("DOC_ID") AS k, count(*) n,
         min(btrim("DOC_ID")) did, min(btrim("COMPANY_ID")) co
  FROM live
  WHERE coalesce(btrim("COMPANY_ID"),'') <> '' AND coalesce(btrim("DOC_ID"),'') <> ''
  GROUP BY 1 HAVING count(*) > 1
)
SELECT '    size='||n||'  '||rpad(k,34)||' excluded because: '||
  CASE
    WHEN did IN (SELECT did FROM bad_docid) THEN 'DOC_ID used by 3+ companies (mis-extraction)'
    WHEN lower(did) IN ('unknown','action_required','null','none') THEN 'DOC_ID is a placeholder'
    WHEN length(regexp_replace(did,'[^a-zA-Z0-9]','','g')) < 3 THEN 'DOC_ID under 3 alphanumerics'
    WHEN regexp_replace(did,'[^a-zA-Z0-9]','','g') ~ '^0+$' THEN 'DOC_ID is all zeros'
    WHEN co = did THEN 'DOC_ID equals COMPANY_ID'
    ELSE '*** NOT EXPLAINED -- investigate ***'
  END
FROM raw
WHERE k NOT IN (
  SELECT btrim("COMPANY_ID")||'|'||btrim("DOC_ID") FROM live d
  WHERE coalesce(btrim(d."COMPANY_ID"),'') <> '' AND coalesce(btrim(d."DOC_ID"),'') <> ''
    AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
    AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
    AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
    AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
    AND btrim(d."DOC_ID") NOT IN (SELECT did FROM bad_docid)
  GROUP BY 1 HAVING count(*) > 1)
ORDER BY n DESC LIMIT 30;
SQL
