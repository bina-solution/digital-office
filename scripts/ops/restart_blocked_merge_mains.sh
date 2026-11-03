#!/bin/bash
# Re-run the merge on group mains the double-action guard refuses, through the SANCTIONED path.
#
# WHAT IS BLOCKED AND WHY
# -----------------------
# 'Dup Guard: Double Action' raises DOUBLE ACTION BLOCKED when the same action was dispatched
# again with no restart after it. That guard is correct and must never be silenced: a repeated
# action that does not move the document is exactly the loop it exists to catch.
#
# But a population of mains dispatched action_merge_doubles under code that COULD NOT succeed --
# the truncated 'Adjudicate Merge' (which returned nothing at all) and 'Build Group Fetch' asking
# only by COMPANY_ID (which starved hash-keyed groups of candidates). Those merges completed
# without merging, so the guard now refuses every retry, and the groups can never close.
#
# The state machine's own answer to "this action failed, run it again" is ACTION_RESTART -- the
# guard treats that status as a sanctioned re-run, and it is what the console's retry button sets.
# So this writes ACTION_RESTART through the SAME endpoint that button uses
# (PATCH /incomingDocuments/repos/<repo>/documents/<id>), not with a SQL UPDATE: the BFF routes it
# through the batch-upsert path and publishes the row-changed event, so the row's history stays
# honest about who changed it.
#
# Scope is the incident, not the symptom: only mains of groups that are STILL duplicated whose
# last logged action is action_merge_doubles. A document whose merge legitimately resolved its
# group is not in this set.
#
# usage:
#   restart_blocked_merge_mains.sh list          -- how many, and a sample
#   restart_blocked_merge_mains.sh one           -- restart ONE, drain it, report the outcome
#   restart_blocked_merge_mains.sh all [n]       -- restart up to n (default 50)
#   restart_blocked_merge_mains.sh escalate      -- mains that burned the retry cap; do NOT retry
#
# MAX_ATTEMPTS (default 6) caps how many action_merge_doubles a main may have before this tool
# refuses to restart it. Counted from the dispatch log, so there is no side state to drift.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
PSQL="$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
REPO=incoming-documents-main
BFF=http://incoming-documents:8080/incomingDocuments

read -r -d '' BLOCKED_MAINS <<'SQL'
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
),
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
-- THE RETRY CAP, so this tool can run on a cycle without defeating the guard it works around.
-- 'Dup Guard: Double Action' exists to catch an action that keeps running and never moves the
-- document. Restarting a main once is a repair; restarting it forever IS that loop, wearing a
-- different hat. The counter is the dispatch log itself -- no side state to drift -- and anything
-- at or over the cap is reported for investigation instead of being restarted again.
attempts AS (
  SELECT "ID", count(*) AS n
  FROM public.indox_action_execution_log
  WHERE "ACTION" = 'action_merge_doubles'
  GROUP BY "ID"
)
SQL
MAX_ATTEMPTS=${MAX_ATTEMPTS:-6}

ids_of () {   # $1 = limit
  $PSQL "SET statement_timeout='240s';
  $BLOCKED_MAINS
  SELECT string_agg(\"ID\", ',') FROM (
    SELECT \"ID\" FROM g WHERE n>1 AND rn=1 AND \"ID\" IN (SELECT \"ID\" FROM blocked)
      AND coalesce((SELECT a.n FROM attempts a WHERE a.\"ID\" = g.\"ID\"), 0) < $MAX_ATTEMPTS
    ORDER BY created_at ASC LIMIT $1) t" | grep -v '^SET$' | tr -d '\r'
}

patch_ids () {   # $1 = comma list
  $DK exec -e I="$1" -e B="$BFF" -e R="$REPO" n8n-shlomo-laptop node -e '
const ids = process.env.I.split(",").filter(Boolean);
(async () => {
  let ok = 0, fail = 0;
  for (const id of ids) {
    try {
      const r = await fetch(process.env.B + "/repos/" + process.env.R + "/documents/" + encodeURIComponent(id),
        { method: "PATCH", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ STATUS: "ACTION_RESTART" }) });
      if (r.ok) ok++; else { fail++; if (fail < 4) console.log("    " + id + " -> " + r.status + " " + (await r.text()).slice(0,140)); }
    } catch (e) { fail++; if (fail < 4) console.log("    " + id + " ERR " + e.message); }
  }
  console.log("    patched ok=" + ok + "  failed=" + fail);
})();'
}

drain_ids () {
  local wu wp
  wu=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
  wp=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
  $DK exec -e I="$1" -e U="$wu" -e P="$wp" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"ids",ids:process.env.I.split(","),dry:false})})
 .then(r=>r.text().then(t=>console.log("    drain: "+r.status+" "+t.slice(0,60))))
 .catch(e=>console.log("    ERR "+e.message));'
}

case "${1:-list}" in
  list)
    $PSQL "SET statement_timeout='240s';
    $BLOCKED_MAINS
    SELECT '  blocked mains of still-open groups: '||count(*)
    FROM g WHERE n>1 AND rn=1 AND \"ID\" IN (SELECT \"ID\" FROM blocked)" | grep -v '^SET$'
    $PSQL "SET statement_timeout='240s';
    $BLOCKED_MAINS
    SELECT '    '||rpad(\"ID\",22)||rpad(coalesce(\"STATUS\",'-'),16)||'group_n='||n
    FROM g WHERE n>1 AND rn=1 AND \"ID\" IN (SELECT \"ID\" FROM blocked)
    ORDER BY created_at ASC LIMIT 8" | grep -v '^SET$'
    ;;
  one)
    ID=$(ids_of 1)
    [ -z "$ID" ] && { echo "  nothing blocked"; exit 0; }
    echo "  proving on a single document: $ID"
    $PSQL "SELECT '    before: status='||coalesce(\"STATUS\",'-')||' into='||coalesce(\"MERGED_INTO\",'-')
           FROM public.incoming_documents WHERE \"ID\"='$ID'"
    patch_ids "$ID"
    $PSQL "SELECT '    after patch: status='||coalesce(\"STATUS\",'-')
           FROM public.incoming_documents WHERE \"ID\"='$ID'"
    drain_ids "$ID"; sleep 80
    drain_ids "$ID"; sleep 80
    $PSQL "SELECT '    after drain: status='||coalesce(\"STATUS\",'-')||' into='||coalesce(\"MERGED_INTO\",'-')
           FROM public.incoming_documents WHERE \"ID\"='$ID'"
    ;;
  all)
    N="${2:-50}"
    IDS=$(ids_of "$N")
    CNT=$(echo "$IDS" | tr ',' '\n' | grep -c .)
    echo "  restarting $CNT blocked main(s)"
    [ "$CNT" -eq 0 ] && exit 0
    patch_ids "$IDS"
    drain_ids "$IDS"
    ;;
  escalate)
    # Mains that have burned the retry cap. These are NOT restarted again: a merge that has run
    # this many times without closing its group is the loop the guard is for, and it needs a
    # person to look at the group, not another dispatch.
    $PSQL "SET statement_timeout='240s';
    $BLOCKED_MAINS
    SELECT '  '||rpad(g.\"ID\",22)||rpad(coalesce(g.\"STATUS\",'-'),14)
         ||'group_n='||g.n||'  merge_attempts='||coalesce(a.n,0)
    FROM g LEFT JOIN attempts a ON a.\"ID\" = g.\"ID\"
    WHERE g.n>1 AND g.rn=1 AND coalesce(a.n,0) >= $MAX_ATTEMPTS
    ORDER BY a.n DESC LIMIT 20" | grep -v '^SET$'
    ;;
  *) echo "usage: $0 list|one|all [n]|escalate   (MAX_ATTEMPTS=$MAX_ATTEMPTS)"; exit 2;;
esac
