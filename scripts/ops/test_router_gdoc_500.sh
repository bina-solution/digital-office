#!/bin/bash
# Fire the GDoc action router DIRECTLY with N full-row lines and measure how it behaves.
# [2026-08-24, owner orders] v2: "run full 500 directly into the action router, 25 at a time;
# the http node uses built-in batching 2 with 1s interval". So: N lines total, POSTed to
# /webhook/indox-action-router in SEQUENTIAL groups of CHUNK (default 25); within each lane
# pass the Post node itself paces 2-concurrent/1s. No DB back-check exists in the lane any
# more -- the HTTP call's own outcome is the verdict (owner: "we must make sure our call works").
#
# Pools (TEST_POOL): armed   (default) sentinel/PSC-owing COMPLETED docs
#                    synced  already-synced docs (PSC=true, no signature) -- drain-invisible,
#                            safe to fire while drains run; rows added are deleted afterwards
#
# usage: test_router_gdoc_500.sh [N] [CHUNK]
set -u
DK="docker -H unix:///run/bbox-docker.sock"
ENVF="$(cd "$(dirname "$0")/../.." && pwd)/.env"
N="${1:-500}"
CHUNK="${2:-25}"
POOL="${TEST_POOL:-armed}"
TAG="router_test_$(date -u +%H%M%S)"
wu=$(grep -E '^BS_WEBHOOK_USER=' "$ENVF" | head -1 | cut -d= -f2-)
wp=$(grep -E '^BS_WEBHOOK_PASS=' "$ENVF" | head -1 | cut -d= -f2-)

if [ "$POOL" = "synced" ]; then
  ELIG="d.\"STATUS\"='COMPLETED'
    AND NOT coalesce(d.\"PRIORITY_SKIP\", false)
    AND coalesce(d.\"TYPE\",'') NOT IN ('SHIPMENT','BALANCE_SHEET','UNKNOWN')
    AND lower(coalesce(d.\"PRIORITY_SYNC_COMPLETED\",'')) = 'true'
    AND d.\"PRIORITY_SYNC_SIGNATURE\" IS NOT NULL
    AND d.\"PRIORITY_SYNC_SIGNATURE\" <> 'rethink-2026-08-23'"
else
  ELIG="d.\"STATUS\"='${TEST_STATUS:-COMPLETED}'
    AND NOT coalesce(d.\"PRIORITY_SKIP\", false)
    AND coalesce(d.\"TYPE\",'') NOT IN ('SHIPMENT','BALANCE_SHEET')
    AND (d.\"PRIORITY_SYNC_SIGNATURE\"='rethink-2026-08-23'
         OR lower(coalesce(d.\"PRIORITY_SYNC_COMPLETED\",'')) <> 'true')"
fi

echo "  tag=$TAG  n=$N  chunk=$CHUNK  pool=$POOL"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc "
SET statement_timeout='240s';
SELECT json_agg(j)::text FROM (
  SELECT row_to_json(d)::jsonb
         || jsonb_build_object('ACTION','action_priority_sync','DOC_TYPE','gdoc') AS j
  FROM public.incoming_documents d
  WHERE $ELIG
  ORDER BY d.updated_at ASC
  LIMIT $N) q" | grep -v '^SET$' | tr -d '\r' > /tmp/router_test_lines.json

LINES=$(python3 - <<'PY'
import json
d=json.load(open('/tmp/router_test_lines.json'))
print(len(d or []))
PY
)
echo "  exported full rows: $LINES"
[ "${LINES:-0}" -eq 0 ] && { echo "  nothing to test"; exit 1; }

$DK exec -i n8n-shlomo-laptop sh -lc 'cat > /tmp/router_test_lines.json' < /tmp/router_test_lines.json
T0=$(date +%s)
$DK exec -e U="$wu" -e P="$wp" -e TAG="$TAG" -e CHUNK="$CHUNK" n8n-shlomo-laptop node -e '
// Sequential chunks of CHUNK lines; each POST is completion-gated so its wall time IS the
// lane behaviour. http.request, NOT fetch (undici has a 300s headers timeout).
const fs = require("fs"), http = require("http");
const lines = JSON.parse(fs.readFileSync("/tmp/router_test_lines.json", "utf8"));
const auth = Buffer.from(process.env.U + ":" + process.env.P).toString("base64");
const size = Number(process.env.CHUNK) || 25;
const chunks = [];
for (let i = 0; i < lines.length; i += size) chunks.push(lines.slice(i, i + size));
const t0 = Date.now();
let ok = 0, bad = 0;
function fire(i) {
  if (i >= chunks.length) {
    console.log("  ALL CHUNKS DONE: " + ok + " ok, " + bad + " failed, total " + Math.round((Date.now()-t0)/1000) + "s");
    return;
  }
  const body = JSON.stringify({ ACTION_LINES: chunks[i], TRIGGER_TYPE: process.env.TAG });
  const tc = Date.now();
  // production webhooks live on the dedicated webhook processor since 2026-08-24
  const req = http.request({ host: "n8n-webhook", port: 5678, path: "/webhook/indox-action-router",
    method: "POST", headers: { "Content-Type": "application/json", Authorization: "Basic " + auth,
    "Content-Length": Buffer.byteLength(body) } }, (res) => {
    let b = "";
    res.on("data", (c) => b += c);
    res.on("end", () => {
      const s = Math.round((Date.now()-tc)/1000);
      if (res.statusCode === 200) ok++; else bad++;
      console.log("  chunk " + (i+1) + "/" + chunks.length + ": HTTP " + res.statusCode + " in " + s + "s  lines=" + chunks[i].length + "  body=" + b.slice(0, 80));
      fire(i + 1);
    });
  });
  req.setTimeout(0);
  req.on("error", (e) => { bad++; console.log("  chunk " + (i+1) + "/" + chunks.length + " FAILED after " + Math.round((Date.now()-tc)/1000) + "s: " + e.message); fire(i + 1); });
  req.end(body);
}
fire(0);'
T1=$(date +%s)
echo "  wall: $((T1-T0))s"

echo "  == verification from the system's own records =="
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc "
SET statement_timeout='120s';
SELECT '    brackets for $TAG: opened='||count(*)||' closed='||count(*) FILTER (WHERE \"ENDED_AT\" IS NOT NULL)
FROM public.indox_action_execution_log WHERE \"TRIGGER\" LIKE '%$TAG%'" | grep -v '^SET$'
python3 - <<'PY'
import json
ids=[r['ID'] for r in json.load(open('/tmp/router_test_lines.json'))]
open('/tmp/router_test_ids.txt','w').write(','.join(ids))
print('    batch ids saved: %d' % len(ids))
PY
IDS=$(cat /tmp/router_test_ids.txt)
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc "
SET statement_timeout='120s';
SELECT '    rows landed in window='||count(*)||' distinct='||count(DISTINCT \"INCOMING_DOC_ID\")
FROM public.indox_priority_local
WHERE \"INCOMING_DOC_ID\" = ANY(string_to_array('$IDS', ','))
  AND received_at > now() - (interval '1 second' * ($(date +%s) - $T0 + 120))" | grep -v '^SET$'
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAc "
SET statement_timeout='120s';
SELECT '    ps_failed_now='||count(*) FILTER (WHERE d.\"STATUS\"='PRIORITY_SYNC_FAILED')
     ||'  error_set='||count(*) FILTER (WHERE coalesce(btrim(d.\"ERROR\"),'') <> '')
FROM public.incoming_documents d WHERE d.\"ID\" = ANY(string_to_array('$IDS', ','))" | grep -v '^SET$'
