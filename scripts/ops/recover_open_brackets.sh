#!/bin/bash
# Recover the 60 documents left IN_PROGRESS by a timed-out extract_base_doc batch.
#
# Execution 3489295 dispatched extract_base_doc for 60 documents (extract_base_doc.max = 60) and
# was cancelled: "The execution was cancelled because it timed out". Its 60 brackets never closed,
# so 'Dup Guard: Double Action' sees extract_base_doc dispatched with no restart after it and
# refuses to re-dispatch. The documents are stuck IN_PROGRESS and no drain will move them.
#
# ACTION_RESTART is the state machine's sanctioned re-run and the guard exempts that status, so
# this writes it through the console's own PATCH endpoint -- not a SQL UPDATE.
set -u
DK="docker -H unix:///run/bbox-docker.sock"
REPO=incoming-documents-main
BFF=http://incoming-documents:8080/incomingDocuments

IDS=$($DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
  "SELECT string_agg(DISTINCT \"ID\", ',') FROM public.indox_action_execution_log
   WHERE \"ENDED_AT\" IS NULL" | tr -d '\r')
CNT=$(echo "$IDS" | tr ',' '\n' | grep -c .)
echo "  documents with an open bracket: $CNT"
[ "${CNT:-0}" -eq 0 ] && { echo "  nothing to recover"; exit 0; }

$DK exec -e I="$IDS" -e B="$BFF" -e R="$REPO" n8n-shlomo-laptop node -e '
const ids = process.env.I.split(",").filter(Boolean);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  let ok = 0, fail = 0;
  for (const id of ids) {
    for (let a = 0; a < 4; a++) {
      if (a) await sleep(400 * a);
      try {
        const r = await fetch(process.env.B + "/repos/" + process.env.R + "/documents/" + encodeURIComponent(id),
          { method: "PATCH", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ STATUS: "ACTION_RESTART" }) });
        if (r.ok) { ok++; break; }
        if (r.status < 500) { fail++; break; }
      } catch (e) { if (a === 3) fail++; }
    }
  }
  console.log("    patched ok=" + ok + "  failed=" + fail);
})();'

$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc \
 "SELECT '  now ACTION_RESTART: '||count(*) FROM public.incoming_documents WHERE \"STATUS\"='ACTION_RESTART'"
