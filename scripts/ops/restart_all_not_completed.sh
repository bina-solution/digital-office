#!/bin/bash
# The full restart cycle: put every document that has not reached a terminal state back through
# the pipeline, and drain until the table stops moving.
#
# WHAT COUNTS AS TERMINAL (and therefore is NOT restarted)
#   COMPLETED  reached the end. Restarting it re-runs every action on work already delivered.
#   MERGED     the absorbed side of a duplicate. No independent life left.
#   OLD        superseded by a newer document for the same company. The state machine sets this
#              deliberately, and 'Adjudicate Merge' says so in as many words: "a winner that is
#              COMPLETED or OLD has finished its lifecycle and must not be dragged back into the
#              pipeline". There are 18,654 of them -- restarting them would churn eighteen thousand
#              documents through the whole pipeline to re-derive the same OLD.
#   GARBAGE    a deliberate terminal verdict, not a failure to retry.
#   ACTION_RESTART already in flight.
#
# Everything else IS restarted: MISSING_LINK, MISSING_COMPANY_ID, DOUBLE, MISSING_TYPE,
# UNKNOWN_COMPANY, EXTRACTION_FAILED, IN_PROGRESS -- roughly 4,400 documents that stopped somewhere
# short of an answer. ACTION_RESTART is the state machine's only re-run, so this is the sanctioned
# way to ask for one.
#
# "all not completed" read literally would include OLD and GARBAGE. It is read here as "everything
# that has not reached AN END", which is the same sentence with the pipeline's own definition of an
# end. Set INCLUDE_OLD=1 to take the literal reading instead.
#
# HOW IT WRITES
# Through the BFF's PATCH endpoint, the same one the console's retry button uses, NOT a SQL
# UPDATE. The write goes through the batch-upsert path and publishes the row-changed event, so the
# row's history stays honest about who changed it and the state machine stays the only writer.
#
# ORDER MATTERS: run this AFTER the duplicate backlog is clean. Restarting a duplicate group's
# members before the group is adjudicated just re-raises the same merges.
#
# usage:
#   restart_all_not_completed.sh count            -- what would be restarted, by status
#   restart_all_not_completed.sh run [n]          -- restart up to n (default 2000), then drain once
#   restart_all_not_completed.sh drain            -- fire the drainer once (mode=all)
#
# The drainer picks its own documents and runs its own pool. Repeat a cycle by invoking this
# again; nothing here loops, and nothing here fires more than one drainer.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
PSQL="$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc"
PSQL_N8N="$DK exec -i n8n-postgres-shlomo-laptop psql -U hacohen -d n8n -tAc"
ENVF=/mnt/c/Users/user/Desktop/personalWorkspace/AutomateOs/deployment-hacohen/.env
REPO=incoming-documents-main
BFF=http://incoming-documents:8080/incomingDocuments
TERMINAL="'COMPLETED','MERGED','ACTION_RESTART','GARBAGE'"
[ "${INCLUDE_OLD:-0}" = "1" ] || TERMINAL="$TERMINAL,'OLD'"

# The convergence test. It MUST return a non-empty string, or the loop compares empty to empty and
# declares a resting point on the third round no matter what the table is doing. The first version
# did exactly that: `GROUP BY 1` on an expression that CONTAINS count(*) is a postgres error
# ("aggregate functions are not allowed in GROUP BY"), the query returned nothing, and the loop
# that read it was about to certify a table still moving 1,500 rows every three minutes.
census () {
  local out
  out=$($PSQL "SET statement_timeout='120s';
  SELECT string_agg(s.st||'='||s.n, ' | ' ORDER BY s.st) FROM (
    SELECT coalesce(\"STATUS\",'-') AS st, count(*) AS n
    FROM public.incoming_documents GROUP BY 1) s" | grep -v '^SET$' | tr -d '\r')
  if [ -z "$out" ]; then
    echo "CENSUS-FAILED"      # never an empty string: an empty census must not read as "unchanged"
  else
    echo "$out"
  fi
}

ids_of () {
  $PSQL "SET statement_timeout='240s';
  SELECT string_agg(\"ID\", ',') FROM (
    SELECT \"ID\" FROM public.incoming_documents
    WHERE \"STATUS\" IS NULL OR \"STATUS\" NOT IN ($TERMINAL)
    ORDER BY created_at ASC LIMIT $1) t" | grep -v '^SET$' | tr -d '\r'
}

patch_ids () {
  $DK exec -e I="$1" -e B="$BFF" -e R="$REPO" n8n-shlomo-laptop node -e '
const ids = process.env.I.split(",").filter(Boolean);
// RETRY ON 5xx. Two thousand sequential PATCHes against the BFF while a drain is running is
// enough to make it return 500 for a stretch; the same request succeeds immediately afterwards.
// Without a retry those documents are silently left in their old status. That used to mean the
// drain never saw them at all; with mode=all it does see them, but they arrive carrying whatever
// status the PATCH failed to change, so the double-action guard can still refuse them.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let ok = 0, fail = 0, retried = 0;
  for (const id of ids) {
    let done = false;
    for (let attempt = 0; attempt < 4 && !done; attempt++) {
      if (attempt) { retried++; await sleep(400 * attempt); }
      try {
        const r = await fetch(process.env.B + "/repos/" + process.env.R + "/documents/" + encodeURIComponent(id),
          { method: "PATCH", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ STATUS: "ACTION_RESTART" }) });
        if (r.ok) { ok++; done = true; }
        else if (r.status < 500) { fail++; done = true; if (fail < 4) console.log("    " + id + " -> " + r.status); }
      } catch (e) { if (attempt === 3) { fail++; if (fail < 4) console.log("    " + id + " ERR " + e.message); } }
    }
    if (!done && ok + fail < ids.length) { /* exhausted retries */ }
  }
  console.log("    patched ok=" + ok + "  failed=" + fail + "  (retries " + retried + ")");
})();'
}

# THE DRAINER SELECTS ITS OWN WORK. Do not reimplement any of it here.
#
# indoxV2BaseDrain01 already contains 'Select IDs' -- its own note calls it "THE only id source"
# -- plus 'Reap Stale Dispatches' (closes brackets older than the router's 3600s timeout) and
# its own pool. mode=all is unfiltered on purpose: decide is the filter, and a no_action verdict
# costs nothing.
#
# What used to be here: a candidate query, a redis lock-exclusion, an ORDER BY and a head -n,
# all of it a second and divergent copy of Select IDs, then the list POSTed back in 200-id
# chunks -- one drain execution per chunk. Six drains alive at once on 2026-08-23, four drivers,
# load 12 on a six-core host. None of that logic belonged in this script.
drain_restarts () {
  local wu wp
  wu=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
  wp=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)
  $DK exec -e U="$wu" -e P="$wp" n8n-shlomo-laptop node -e '
const auth=Buffer.from(process.env.U+":"+process.env.P).toString("base64");
fetch("http://localhost:5678/webhook/indox-drain",{method:"POST",
 headers:{"Content-Type":"application/json",Authorization:"Basic "+auth},
 body:JSON.stringify({mode:"all"})})
 .then(r=>r.text().then(t=>console.log("  drain: "+r.status+" "+t)))
 .catch(e=>console.log("  drain ERR "+e.message));'
}

case "${1:-count}" in
  count)
    $PSQL "SET statement_timeout='120s';
    SELECT '  '||rpad(coalesce(\"STATUS\",'-'),20)||count(*)||
           CASE WHEN coalesce(\"STATUS\",'x') IN ($TERMINAL) THEN '   (terminal, left alone)' ELSE '   <- would restart' END
    FROM public.incoming_documents GROUP BY \"STATUS\" ORDER BY count(*) DESC" | grep -v '^SET$'
    ;;
  run)
    IDS=$(ids_of "${2:-2000}")
    CNT=$(echo "$IDS" | tr ',' '\n' | grep -c .)
    echo "  restarting $CNT document(s)"
    [ "$CNT" -eq 0 ] && { echo "  nothing to restart"; exit 0; }
    patch_ids "$IDS"
    drain_restarts
    ;;
  drain)
    drain_restarts
    echo "  census: $(census)"
    ;;
  *) echo "usage: $0 count | run [n] | drain        (drain fires the drainer once, mode=all)"; exit 2;;
esac
