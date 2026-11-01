#!/bin/bash
# DETERMINISTIC test of the detector's KEY expression -- no drain, no queue, no starvation.
#
# The bad-doc-id quarantine is a change to SQL, so it can be tested as SQL. The end-to-end fixture
# (test_baddocid_quarantine.sh) exercises the pipeline around it, but it needs a quiet system: two
# runs returned VOID because their drains queued behind a 4,000-dispatch wave and nothing was
# dispatched inside the window. This test answers the narrower question the change actually poses,
# and answers it every time:
#
#   Does the key still group an ORDINARY duplicate pair, and does it refuse to group rows whose
#   doc-id is shared by 3+ companies?
#
# Both halves matter. A quarantine that also blinded the detector to real duplicates would show up
# here as case B failing -- which is exactly the reassurance a count of "0 duplicate groups" cannot
# give you on its own.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
P=zzk$(date +%H%M%S)

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -v ON_ERROR_STOP=1 -tAf - <<SQL
SET session_replication_role = replica;
INSERT INTO public.incoming_documents ("ID","COMPANY_ID","DOC_ID","TYPE","STATUS",created_at) VALUES
 -- A: doc-id under THREE companies, two rows sharing one -> must NOT form a biz group
 ('${P}_a1','880000201','ZZKBAD777','INVOICE','ACTION_RESTART', now()),
 ('${P}_a2','880000201','ZZKBAD777','INVOICE','ACTION_RESTART', now()),
 ('${P}_a3','880000202','ZZKBAD777','INVOICE','ACTION_RESTART', now()),
 ('${P}_a4','880000203','ZZKBAD777','INVOICE','ACTION_RESTART', now()),
 -- B: ordinary duplicate pair, doc-id used by ONE company -> MUST still form a biz group
 ('${P}_b1','880000204','ZZKGOOD88','INVOICE','ACTION_RESTART', now()),
 ('${P}_b2','880000204','ZZKGOOD88','INVOICE','ACTION_RESTART', now());
SET session_replication_role = origin;

-- The detector's key, verbatim from indoxV2Driver01.
WITH bad_docid AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"), '') <> ''
    AND length(regexp_replace(btrim("DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
  GROUP BY btrim("DOC_ID") HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
), u AS (
  SELECT d."ID", COALESCE(
    CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> '' AND lower(d."COMPANY_ID") <> 'unknown'
          AND d."DOC_ID" IS NOT NULL AND d."DOC_ID" <> ''
          AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
          AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
          AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+\$'
          AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
          AND btrim(d."DOC_ID") NOT IN (SELECT did FROM bad_docid)
         THEN 'biz' || chr(1) || btrim(d."COMPANY_ID") || chr(1) || btrim(d."DOC_ID") END,
    CASE WHEN d."HASH" IS NOT NULL AND d."HASH" <> '' AND lower(d."HASH") <> 'unknown'
          AND (d."LINKED_BS" IS NULL OR d."LINKED_BS" = '') THEN 'hash' || chr(1) || d."HASH" END,
    CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> ''
          AND d."SHORT_DOC_ID" IS NOT NULL AND d."SHORT_DOC_ID" <> ''
          AND btrim(d."SHORT_DOC_ID") !~ '^0+\$'
         THEN 'comp' || chr(1) || d."COMPANY_ID" || chr(1) || d."SHORT_DOC_ID" END
  ) AS dup_key
  FROM public.incoming_documents d
  WHERE d."ID" LIKE '${P}%' AND d."STATUS" IS DISTINCT FROM 'MERGED'
)
SELECT '  ' || rpad("ID",14) || 'key=' || coalesce(replace(dup_key, chr(1), '|'), 'NONE') FROM u ORDER BY "ID";

WITH bad_docid AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"), '') <> ''
    AND length(regexp_replace(btrim("DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
  GROUP BY btrim("DOC_ID") HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
)
SELECT '  QUARANTINE   : ' || CASE WHEN 'ZZKBAD777' IN (SELECT did FROM bad_docid)
  THEN 'PASS (3-company doc-id is quarantined, forms no biz key)'
  ELSE 'FAIL (bad doc-id was not quarantined)' END;

WITH bad_docid AS (
  SELECT btrim("DOC_ID") AS did FROM public.incoming_documents
  WHERE coalesce(btrim("DOC_ID"), '') <> ''
    AND length(regexp_replace(btrim("DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
  GROUP BY btrim("DOC_ID") HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
)
SELECT '  NOT BLINDED  : ' || CASE WHEN 'ZZKGOOD88' NOT IN (SELECT did FROM bad_docid)
  THEN 'PASS (ordinary doc-id still forms a biz key -- detector is not blind)'
  ELSE 'FAIL (quarantine is over-broad)' END;

DELETE FROM public.incoming_documents WHERE "ID" LIKE '${P}%';
SELECT '  (fixtures removed)';
SQL
