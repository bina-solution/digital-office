#!/bin/bash
# A REASON FOR EVERY ROW IN MISSING_LINK -- the largest non-terminal population left.
#
# Same discipline as reconcile_dup_keys.sh and explain_stuck_action_restart.sh: a cause per row and
# an explicit "*** NOT EXPLAINED ***" arm, so a row the pipeline dropped cannot hide in a count.
#
# MISSING_LINK means the document has no Drive link. The action that would find one is `find_link`,
# gated on SEARCH_IN_DRIVE_COMPLETED. The interesting question is therefore not "why no link" but
# "has the search already run and come back empty" -- in which case the row is at a legitimate
# terminus pending data, not stuck -- versus "was the search never attempted", which would be the
# pipeline dropping it.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<'SQL'
SET statement_timeout='240s';
WITH ml AS (SELECT * FROM public.incoming_documents WHERE "STATUS"='MISSING_LINK'),
last AS (
  SELECT DISTINCT ON (l."ID") l."ID", l."ACTION", l."STARTED_AT", l."ENDED_AT"
  FROM public.indox_action_execution_log l JOIN ml ON ml."ID" = l."ID"
  ORDER BY l."ID", l."STARTED_AT" DESC),
searched AS (
  SELECT DISTINCT "ID" FROM public.indox_action_execution_log WHERE "ACTION"='find_link'),
reasoned AS (
  SELECT m."ID",
    CASE
      WHEN coalesce(btrim(m."LINK"),'') <> ''
        THEN '*** NOT EXPLAINED -- has a LINK but sits in MISSING_LINK ***'
      WHEN lower(coalesce(btrim(m."SEARCH_IN_DRIVE_COMPLETED"),'')) = 'true'
        THEN 'SEARCHED, NOTHING FOUND (find_link ran and completed; terminus pending the file)'
      WHEN s."ID" IS NOT NULL
        THEN 'SEARCH ATTEMPTED but flag not true (flag='
             || coalesce(btrim(m."SEARCH_IN_DRIVE_COMPLETED"),'<null>') || ')'
      WHEN coalesce(btrim(m."COMPANY_NAME"),'') = '' OR coalesce(btrim(m."SHORT_DOC_ID"),'') = ''
        THEN 'CANNOT SEARCH -- find_link needs COMPANY_NAME and SHORT_DOC_ID; one is blank'
      ELSE '*** NOT EXPLAINED -- searchable, never searched, last='
           || coalesce(l."ACTION",'<never dispatched>') || ' ***'
    END AS reason
  FROM ml m
  LEFT JOIN last l ON l."ID" = m."ID"
  LEFT JOIN searched s ON s."ID" = m."ID")
SELECT '  ' || lpad(count(*)::text, 5) || '  ' || reason
FROM reasoned GROUP BY reason ORDER BY count(*) DESC;

SELECT '  ---- sample of any unexplained rows ----';
WITH ml AS (SELECT * FROM public.incoming_documents WHERE "STATUS"='MISSING_LINK'),
searched AS (SELECT DISTINCT "ID" FROM public.indox_action_execution_log WHERE "ACTION"='find_link')
SELECT '    ' || rpad(m."ID",22)
     || ' link=' || rpad(coalesce(left(btrim(m."LINK"),16),'<none>'),18)
     || ' searchflag=' || rpad(coalesce(btrim(m."SEARCH_IN_DRIVE_COMPLETED"),'<null>'),8)
     || ' company=' || rpad(coalesce(left(btrim(m."COMPANY_NAME"),14),'<blank>'),16)
     || ' short=' || coalesce(btrim(m."SHORT_DOC_ID"),'<blank>')
FROM ml m LEFT JOIN searched s ON s."ID" = m."ID"
WHERE coalesce(btrim(m."LINK"),'') <> ''
   OR (s."ID" IS NULL
       AND lower(coalesce(btrim(m."SEARCH_IN_DRIVE_COMPLETED"),'')) <> 'true'
       AND coalesce(btrim(m."COMPANY_NAME"),'') <> ''
       AND coalesce(btrim(m."SHORT_DOC_ID"),'') <> '')
LIMIT 15;
SQL
