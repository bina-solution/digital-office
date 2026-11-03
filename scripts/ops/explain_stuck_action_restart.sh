#!/bin/bash
# A REASON FOR EVERY ROW LEFT IN ACTION_RESTART. Not a count, not a plan -- a cause per row.
#
# Modelled on scripts/ops/reconcile_dup_keys.sh, which ended a recurring argument by printing why
# each group was not a duplicate. Same discipline here: an explicit
# "*** NOT EXPLAINED -- investigate ***" arm, so a row the pipeline simply forgot cannot hide
# inside an aggregate. "200 rows remain" invites a shrug; "200 rows remain and 3 have no reason"
# does not.
#
# The causes, in the order they are checked:
#   LOCKED            holds a doc_action lock, so every feed lock-skips it by design
#   FED RECENTLY      dispatched inside the last 15 minutes; in flight, not stuck
#   NEVER DISPATCHED  no dispatch row at all -- the feeder has never selected it
#   RESTART LOOPING   restart_base ran and the row is STILL ACTION_RESTART
#   AT ITERATION CAP  ITERATION_COUNT >= max_iterations_per_doc
set -u
DK="docker -H unix:///run/bbox-docker.sock"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
RP=$(grep -E '^REDIS_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
LOCKS=/tmp/ear_locks_$$.txt

$DK exec -e RP="$RP" redis-shlomo-laptop sh -lc \
  'redis-cli -a "$RP" --no-auth-warning --scan --pattern "n8n.process_lock.doc_action.*" 2>/dev/null' \
  | sed -e 's/^n8n[.]process_lock[.]doc_action[.]//' -e 's/::.*$//' | tr -d '\r' | sort -u > "$LOCKS"
echo "  live doc_action locks: $(grep -c . "$LOCKS")"

# Ship the lock list into a temp table so the reason query can join on it.
{
  echo "DROP TABLE IF EXISTS _ear_locked; CREATE TEMP TABLE _ear_locked(id text);"
  if [ -s "$LOCKS" ]; then
    echo "INSERT INTO _ear_locked(id) VALUES"
    awk '{printf "%s(%s)", (NR>1?",":""), "'"'"'" $1 "'"'"'"}' "$LOCKS"
    echo ";"
  fi
  cat <<'EOS'
SET statement_timeout='240s';
WITH cap AS (
  SELECT coalesce((SELECT value::int FROM public.settings
                   WHERE key='max_iterations_per_doc' LIMIT 1), 15) AS n
),
stuck AS (SELECT * FROM public.incoming_documents WHERE "STATUS"='ACTION_RESTART'),
last AS (
  SELECT DISTINCT ON (l."ID") l."ID", l."ACTION", l."STARTED_AT", l."ENDED_AT"
  FROM public.indox_action_execution_log l
  JOIN stuck s ON s."ID" = l."ID"
  ORDER BY l."ID", l."STARTED_AT" DESC
),
reasoned AS (
  SELECT s."ID",
    CASE
      WHEN EXISTS (SELECT 1 FROM _ear_locked k WHERE k.id = s."ID")
        THEN 'LOCKED (doc_action lock held -- every feed lock-skips it, by design)'
      WHEN l."STARTED_AT" > now() - interval '15 minutes'
        THEN 'FED RECENTLY (' || l."ACTION" || ', in flight)'
      WHEN coalesce(s."ITERATION_COUNT",0) >= (SELECT n FROM cap)
        THEN 'AT ITERATION CAP (' || s."ITERATION_COUNT" || ')'
      WHEN l."ID" IS NULL
        THEN '*** NOT EXPLAINED -- never dispatched, the feeder has never selected it ***'
      WHEN l."ACTION" LIKE 'restart%' AND l."ENDED_AT" IS NOT NULL
        THEN 'RESTART COMPLETED but row still ACTION_RESTART (last=' || l."ACTION" || ')'
      ELSE '*** NOT EXPLAINED -- last=' || coalesce(l."ACTION",'<none>')
           || ' ended=' || coalesce(l."ENDED_AT"::text,'OPEN') || ' ***'
    END AS reason
  FROM stuck s LEFT JOIN last l ON l."ID" = s."ID"
)
SELECT '  ' || lpad(count(*)::text, 5) || '  ' || reason
FROM reasoned GROUP BY reason ORDER BY count(*) DESC;

SELECT '  ---- unexplained rows (if any) ----';
WITH cap AS (SELECT coalesce((SELECT value::int FROM public.settings
                   WHERE key='max_iterations_per_doc' LIMIT 1), 15) AS n),
stuck AS (SELECT * FROM public.incoming_documents WHERE "STATUS"='ACTION_RESTART'),
last AS (
  SELECT DISTINCT ON (l."ID") l."ID", l."ACTION", l."STARTED_AT", l."ENDED_AT"
  FROM public.indox_action_execution_log l JOIN stuck s ON s."ID" = l."ID"
  ORDER BY l."ID", l."STARTED_AT" DESC)
SELECT '    ' || rpad(s."ID",22) || ' last=' || coalesce(l."ACTION",'<never dispatched>')
     || ' iter=' || coalesce(s."ITERATION_COUNT"::text,'-')
     || ' updated=' || to_char(s.updated_at,'MM-DD HH24:MI')
FROM stuck s LEFT JOIN last l ON l."ID" = s."ID"
WHERE NOT EXISTS (SELECT 1 FROM _ear_locked k WHERE k.id = s."ID")
  AND (l."STARTED_AT" IS NULL OR l."STARTED_AT" <= now() - interval '15 minutes')
  AND coalesce(s."ITERATION_COUNT",0) < (SELECT n FROM cap)
  AND (l."ID" IS NULL OR NOT (l."ACTION" LIKE 'restart%' AND l."ENDED_AT" IS NOT NULL))
LIMIT 20;
EOS
} > /tmp/ear_$$.sql

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - < /tmp/ear_$$.sql
rm -f "$LOCKS" /tmp/ear_$$.sql
