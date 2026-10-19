#!/bin/bash
# Drive the duplicate backlog to zero, measuring it the way the DETECTOR defines it.
#
# WHY THIS REPLACES drain_dup_survivors.sh + merge_survivors_loop.sh
# ------------------------------------------------------------------
# Both of those keyed on the BUSINESS key alone (COMPANY_ID|DOC_ID). The detector -- the driver's
# dbl CTE -- groups on biz -> hash -> comp, in that order. So the old pair:
#   * never FED a hash-keyed or comp-keyed group (its main was never selected), and
#   * would have declared CONVERGED with those groups still on the table, because its measure
#     could not see them either.
# A measure that cannot see the work is worse than no measure: it reports success.
#
# The key is defined ONCE, in KEY_SQL, and both the feeder and the counter select from it. They
# cannot drift apart.
#
# usage:
#   dup_backlog_drive.sh count                 -- groups still duplicated, by tier
#   dup_backlog_drive.sh feed  <n> [tier]      -- drain n mains, optionally only biz|hash|comp
#   dup_backlog_drive.sh loop  <rounds> <n>    -- feed/measure until converged, stalled or unsafe
#
# THROUGHPUT IS BOUNDED BY THE LOCK, NOT BY THE BATCH SIZE. A doc_action lock lives ~47 minutes
# and is NOT released when the action completes (984 were held live, every one
# action_merge_doubles), so each main is attemptable roughly once per lock cycle. Batch size is
# the wrong dial: pass a batch LARGER than the backlog so every round feeds everything currently
# feedable, and let the rounds where nothing is feedable simply wait the lock out.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
PSQL="$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env

# --- the one definition of a duplicate group -----------------------------------------------
# Mirrors groupKeyOf() in indoxV2ActionsGlobal01 'Adjudicate Merge' and the driver's dbl CTE:
# same tiers, same precedence, same predicates. MERGED rows are out of the universe -- they are
# the resolved side of a duplicate, not a member of one.
read -r -d '' KEY_SQL <<'SQL'
WITH u AS (
  SELECT d.*,
    CASE
      WHEN coalesce(btrim(d."COMPANY_ID"),'') <> ''
       AND coalesce(btrim(d."DOC_ID"),'') <> ''
       AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
       AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
       AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
       AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
       -- [2026-08-23] The bad-doc-id quarantine, mirrored from indoxV2Driver01's detector: a
       -- doc-id used by 3+ companies is a mis-extraction, not a document id, so it forms no biz
       -- key. Without this line the tool counts groups the pipeline no longer raises and the
       -- backlog reads as stuck at 10 forever.
       AND btrim(d."DOC_ID") NOT IN (
         SELECT btrim(b."DOC_ID") FROM public.incoming_documents b
         WHERE coalesce(btrim(b."DOC_ID"), '') <> ''
           AND length(regexp_replace(btrim(b."DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
         GROUP BY btrim(b."DOC_ID")
         HAVING count(DISTINCT btrim(b."COMPANY_ID")) >= 3)
        THEN 'biz'||chr(1)||btrim(d."COMPANY_ID")||chr(1)||btrim(d."DOC_ID")
      WHEN coalesce(btrim(d."HASH"),'') <> ''
       AND lower(btrim(d."HASH")) <> 'unknown'
       AND coalesce(btrim(d."LINKED_BS"),'') = ''
        THEN 'hash'||chr(1)||btrim(d."HASH")
      WHEN coalesce(btrim(d."COMPANY_ID"),'') <> ''
       AND coalesce(btrim(d."SHORT_DOC_ID"),'') <> ''
       AND btrim(d."SHORT_DOC_ID") !~ '^0+$'
        THEN 'comp'||chr(1)||btrim(d."COMPANY_ID")||chr(1)||btrim(d."SHORT_DOC_ID")
    END AS k
  FROM public.incoming_documents d
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED'
),
g AS (
  SELECT *, count(*) OVER (PARTITION BY k) AS n,
         row_number() OVER (PARTITION BY k ORDER BY created_at DESC, "ID" DESC) AS rn
  FROM u WHERE k IS NOT NULL
)
SQL

count_groups () {
  $PSQL "SET statement_timeout='240s';
  $KEY_SQL
  SELECT count(*) FROM (SELECT k FROM g WHERE n>1 GROUP BY k) z" | grep -v '^SET$' | tr -d '\r '
}

count_by_tier () {
  $PSQL "SET statement_timeout='240s';
  $KEY_SQL
  SELECT '    '||rpad(split_part(k, chr(1), 1),6)||count(*)
  FROM (SELECT k FROM g WHERE n>1 GROUP BY k) z GROUP BY split_part(k, chr(1), 1) ORDER BY 1" \
  | grep -v '^SET$'
}

# A COMPLETED row absorbed into a survivor that is not COMPLETED.
#
# [2026-08-23] THIS MUST BE MEASURED AT MERGE TIME, NOT NOW.
# The naive current-state version fired a hard stop on 5 pairs that were all legitimate: in every
# one, both rows were COMPLETED when the merge ran, and the winner was demoted to OLD 13-39
# SECONDS LATER by update_status_old_doc (a newer document superseded it). pickWinner ranks
# COMPLETED above everything, so it cannot produce this pair in the first place -- which is
# exactly why a current-state reading of it is a false alarm rather than a defect.
#
# So: a demotion logged AFTER the merge is a CASCADE and is not counted. A winner with no
# demotion logged at all, or one demoted BEFORE the merge, is a real violation -- pickWinner
# would have had to choose a worse row while a better one was available.
UNSAFE_SQL="
WITH bad AS (
  SELECT m.\"ID\" AS loser, m.\"MERGED_AT\" AS merged_at, s.\"ID\" AS winner
  FROM public.incoming_documents m
  JOIN public.incoming_documents s ON s.\"ID\" = m.\"MERGED_INTO\"
  WHERE m.\"STATUS\"='MERGED' AND m.\"STATUS_BEFORE_MERGE\"='COMPLETED'
    AND s.\"STATUS\" <> 'COMPLETED'
), dem AS (
  SELECT b.loser, b.merged_at,
         max(l.\"STARTED_AT\") FILTER (WHERE l.\"ACTION\"='update_status_old_doc') AS demoted_at
  FROM bad b LEFT JOIN public.indox_action_execution_log l ON l.\"ID\" = b.winner
  GROUP BY 1,2)
"

count_unsafe () {   # real violations only -- this is what the hard stop reads
  $PSQL "SET statement_timeout='120s'; $UNSAFE_SQL
  SELECT count(*) FROM dem WHERE demoted_at IS NULL OR demoted_at <= merged_at" \
  | grep -v '^SET$' | tr -d '\r '
}

count_cascade () { # winner demoted after the merge -- reported, never a stop
  $PSQL "SET statement_timeout='120s'; $UNSAFE_SQL
  SELECT count(*) FROM dem WHERE demoted_at > merged_at" | grep -v '^SET$' | tr -d '\r '
}

count_merged () {
  $PSQL "SELECT count(*) FROM public.incoming_documents WHERE \"STATUS\"='MERGED'" | tr -d '\r '
}

# A main the double-action guard will refuse. The guard (indoxV2Driver01 'Dup Guard: Double
# Action') raises DOUBLE ACTION BLOCKED when the same action was dispatched again with no restart
# after it -- unless the row is in ACTION_RESTART, which it treats as a sanctioned re-run.
# Feeding one of these produces an error and no work, and because LIMIT returns the same rows
# every round, a handful of them can absorb the whole batch and the backlog stops moving.
#
# RECENTLY ATTEMPTED is a separate exclusion and matters just as much. A doc_action redis lock is
# held for ~47 minutes, and lock-skip is by design. Feeding the same oldest 250 mains every round
# therefore re-feeds rows that are still locked and cannot act: conversion decayed 166 -> 40 -> 24
# -> 14 -> 10 groups per 250 fed over five rounds, which looks like a converging backlog and is
# actually a loop talking to itself. Excluding a recent attempt rotates the selection through the
# rest of the backlog instead.
read -r -d '' BLOCKED_SQL <<'SQL'
blocked AS (
  -- MIRRORS 'Dup Guard: Double Action' SIGNAL A EXACTLY, and it has to.
  --
  -- The first version tested only the doc's LAST logged action. The guard does not: it scans the
  -- newest 10 ACTION_HISTORY rows and blocks when action_merge_doubles appears with no restart
  -- AFTER it -- whatever ran since. doc_msq6hmoidspohq slipped through on exactly that
  -- difference: merge at 00:23, update_status_old_doc at 00:27, so its last action was not a
  -- merge and it was fed anyway.
  --
  -- One such document is not one lost document. 'Raise Double Blocked' is a stop-and-error, so it
  -- aborts the WHOLE driver execution: a 702-id drain produced 4 driver errors and ZERO
  -- dispatches. Two stale documents were holding the entire backlog still.
  --
  -- The 10-row window is copied too. Reading the whole history instead would over-exclude
  -- documents the guard would actually let through -- and while over-excluding is the safe
  -- direction, it is not the same rule, and a mirror that is not exact drifts.
  SELECT h."ID"
  FROM (
    SELECT r."ID",
           max(r."STARTED_AT") FILTER (WHERE r."ACTION" = 'action_merge_doubles') AS last_merge,
           max(r."STARTED_AT") FILTER (WHERE r."ACTION" LIKE 'restart%')          AS last_restart
    FROM (
      SELECT "ID", "ACTION", "STARTED_AT",
             row_number() OVER (PARTITION BY "ID" ORDER BY "STARTED_AT" DESC) AS rn
      FROM public.indox_action_execution_log
    ) r
    WHERE r.rn <= 10
    GROUP BY r."ID"
  ) h
  JOIN public.incoming_documents d ON d."ID" = h."ID"
  WHERE h.last_merge IS NOT NULL
    AND (h.last_restart IS NULL OR h.last_merge > h.last_restart)
    AND d."STATUS" IS DISTINCT FROM 'ACTION_RESTART'
),
recent AS (
  -- A cheap pre-filter only. The AUTHORITATIVE exclusion is the redis lock set, read below --
  -- this window just keeps the candidate list small. It is deliberately SHORTER than the lock,
  -- because guessing the TTL is exactly what went wrong: the window was set to 50 minutes from a
  -- remembered "~47 min", and live TTLs measured up to 4,358s (~73 min). Mains attempted 55
  -- minutes earlier passed the filter, were still locked, and lock-skipped: 702 fed, 20
  -- dispatched. Do not tune this number -- the lock set is the truth.
  SELECT DISTINCT "ID" FROM public.indox_action_execution_log
  WHERE "ACTION" = 'action_merge_doubles'
    AND "STARTED_AT" > now() - interval '10 minutes'
)
SQL

# The locks actually held, straight from redis. Without -a, NOAUTH is swallowed and this silently
# reads zero -- which would put every locked main straight back into the feed.
locked_ids () {
  local rp
  rp=$(grep -E '^REDIS_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
  $DK exec -e RP="$rp" redis-shlomo-laptop sh -lc \
    'redis-cli -a "$RP" --no-auth-warning --scan --pattern "n8n.process_lock.doc_action.*::action_merge_doubles" 2>/dev/null' \
    | sed -e 's/^n8n[.]process_lock[.]doc_action[.]//' -e 's/::action_merge_doubles$//' | tr -d '\r'
}

count_blocked () {
  $PSQL "SET statement_timeout='240s';
  $KEY_SQL , $BLOCKED_SQL
  SELECT count(*) FROM g WHERE n>1 AND rn=1 AND \"ID\" IN (SELECT \"ID\" FROM blocked)" \
  | grep -v '^SET$' | tr -d '\r '
}

feed () {
  local n="$1"
  local tier="${2:-}"
  local wu wp ids cnt tierfilter
  # Optional tier filter. Without it the selection is ordered by created_at and a small tier can
  # sit past every LIMIT forever: the 18 hash-keyed groups survived four rounds of 250 untouched
  # because 1,100+ biz groups are older. A tier that never gets fed never converges.
  tierfilter=""
  [ -n "$tier" ] && tierfilter="AND k LIKE '${tier}'||chr(1)||'%'"
  wu=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
  wp=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
  # Feed the MAIN of each group: the main is the only line decide dispatches a merge on, and the
  # merge writes MERGED on the rest. Feeding members too would only produce lock-skips.
  # ORDER BY is deliberate: without it LIMIT returns the same rows every round, so any main that
  # cannot progress is re-fed forever and the batch never reaches the rest of the backlog.
  local cand lockf ncand nlock
  cand=$($PSQL "SET statement_timeout='240s';
  $KEY_SQL , $BLOCKED_SQL
  SELECT \"ID\" FROM g
  WHERE n>1 AND rn=1 AND \"ID\" NOT IN (SELECT \"ID\" FROM blocked)
    AND \"ID\" NOT IN (SELECT \"ID\" FROM recent) $tierfilter
  ORDER BY created_at ASC" | grep -v '^SET$' | tr -d '\r' | grep -v '^$')
  lockf=$(mktemp); locked_ids > "$lockf"
  ncand=$(printf '%s\n' "$cand" | grep -c . || true)
  nlock=$(grep -c . "$lockf" || true)
  ids=$(printf '%s\n' "$cand" | grep -Fxv -f "$lockf" | head -n "$n" | paste -sd, -)
  rm -f "$lockf"
  cnt=$(echo "$ids" | tr ',' '\n' | grep -c .)
  echo "    mains fed: $cnt   (candidates $ncand, merge locks held $nlock)"
  [ "$cnt" -eq 0 ] && return 0
  $DK exec -e I="$ids" -e U="$wu" -e P="$wp" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("    drain: "+r.status+" "+t.slice(0,60))))
 .catch(e=>console.log("    ERR "+e.message));'
}

case "${1:-count}" in
  count)
    echo "  duplicate groups still open: $(count_groups)"
    count_by_tier
    echo "  mains the double-action guard will refuse: $(count_blocked)"
    echo "  unsafe merges (real, at merge time): $(count_unsafe)"
    echo "  cascades (winner demoted after its merge, informational): $(count_cascade)"
    ;;
  feed)
    feed "${2:-100}" "${3:-}"
    ;;
  loop)
    ROUNDS="${2:-20}"; BATCH="${3:-150}"
    BASE_UNSAFE=$(count_unsafe)
    # NO SILENT CAPS: say up front how many groups this loop can never move, so a floor above
    # zero reads as "these are blocked" and not as "converged".
    echo "  baseline: groups=$(count_groups) merged=$(count_merged) unsafe=$BASE_UNSAFE"
    echo "  guard-blocked mains (excluded from every round): $(count_blocked)"
    prev=-1; same=0
    for r in $(seq 1 "$ROUNDS"); do
      # NEVER suppress the feed line. A round that fed 0 mains and a round that fed 300 and
      # converted none look identical in the group count, and they need opposite responses.
      feed "$BATCH"
      sleep 75
      m=$(count_merged); sv=$(count_groups); bad=$(count_unsafe); csc=$(count_cascade)
      echo "  [round $r] MERGED=$m  groups_open=$sv  unsafe=$bad (baseline $BASE_UNSAFE)  cascades=$csc"
      if [ "${bad:-0}" -gt "${BASE_UNSAFE:-0}" ]; then
        echo "  HARD STOP: unsafe merges rose above baseline"; break
      fi
      [ "${sv:-0}" = "0" ] && { echo "  CONVERGED: no duplicate groups left"; break; }
      if [ "$sv" = "$prev" ]; then
        same=$((same+1))
        [ "$same" -ge 4 ] && { echo "  STALLED at $sv for 4 rounds"; break; }
      else same=0; fi
      prev="$sv"
    done
    ;;
  *) echo "usage: $0 count|feed <n>|loop <rounds> <n>"; exit 2;;
esac
