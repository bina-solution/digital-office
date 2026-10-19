#!/usr/bin/env bash
# `bbox dgo test fresh` — FRESH OFFICES, as real processes, through the real pairing API.
#
# WHY THIS EXISTS
#   The owner's test is "any two fresh offices on one network pair out of the box" (2026-10-05). The
#   engine's selftests walk the whole flow, but with offices in memory; the live gate (phase 3) walks
#   it on offices that have existed for days. Neither is an office on its FIRST minute: the app's own
#   image, empty volumes, an identity minted seconds ago, nobody having named it or declared anything.
#   The first run of this found what neither could: an office with no identity answered every pairing
#   route with a bare 500, and the screen said "HTTP 500".
#
# WHAT IT DOES
#   Starts throwaway containers of THIS office's own app image (no network at all, state on tmpfs)
#   and carries the codes between them by hand, exactly as two people would:
#     · before it has an identity, a fresh office refuses in words that name the command;
#     · two fresh offices get different ids, say they are unnamed, and say why they only dial;
#     · fresh-b offers and the LIVE office here claims — the same six digits on both sides
#       (or, where the live office cannot be dialed either, the plain-words refusal);
#     · fresh-c offers and fresh-b claims — two offices that only dial: refused with 409, in words;
#     · fresh-d is an office AT HOME (it declares the address its own LAN knows it by) and offers —
#       the live office must not dial that private address: it listens and lets her dial (lnk-032).
#   NOTHING IS CONFIRMED, so nothing is written anywhere: a claim lives in the live office's memory
#   for ten minutes and is gone. The live office's pairings are compared before and after.
set -uo pipefail

LIVE="$(docker ps --filter 'name=^dgo-extend-' --format '{{.Names}}' 2>/dev/null | head -1)"
[ -n "${LIVE}" ] || { echo "dgo test fresh: this office's dgo-extend is not running — \`bbox run\` first"; exit 2; }
IMG="$(docker inspect "${LIVE}" --format '{{.Config.Image}}')"
B="dgo-fresh-b-$$"; C="dgo-fresh-c-$$"; D="dgo-fresh-d-$$"
trap 'docker rm -f "${B}" "${C}" "${D}" >/dev/null 2>&1 || true' EXIT

fails=0
check() { if [ "$2" = "1" ]; then echo "  PASS  $1"; else echo "  FAIL  $1"; echo "        $3" | cut -c1-260; fails=$((fails + 1)); fi; }
call() {   # <container> <METHOD> <path> [json body]  →  "<status> <body>"
  docker exec -i "$1" python3 - "$2" "$3" "${4:-}" <<'PY'
import sys, urllib.request, urllib.error
method, path, body = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request("http://127.0.0.1:8983" + path, method=method,
                             data=body.encode() if body else None, headers={"content-type": "application/json"})
try:
    r = urllib.request.urlopen(req, timeout=60)
    print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
PY
}
# one field of an answer, as python would print it ("" when the answer is not JSON)
field() { python3 -c "import json,sys; d=json.loads(sys.argv[1].split(' ',1)[1]); print(eval(sys.argv[2], {'d': d}))" "$1" "$2" 2>/dev/null; }
status() { echo "${1%% *}"; }
as_json() { python3 -c "import json,sys; print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2]))))" "$@"; }

before="$(call "${LIVE}" GET /api/pair)"
live_id="$(field "${before}" "d['home']['id']")"
live_listen="$(field "${before}" "(d.get('listen') or {}).get('endpoint', '')")"
echo "live office: ${live_id} (${LIVE}) · can be dialed: ${live_listen:-no} · image: ${IMG}"

for name in "${B}" "${C}"; do
  docker run -d --rm --name "${name}" --network none --tmpfs /data --tmpfs /identity --tmpfs /registry \
    -e DGO_STATE_DIR=/data -e DGO_IDENTITY_DIR=/identity -e DGO_REGISTRY_DIR=/registry -e "DEPLOYMENT_NAME=${name}" \
    "${IMG}" >/dev/null || { echo "dgo test fresh: could not start ${name}"; exit 2; }
done
# …and one that is an office AT HOME: it declares the address its own LAN knows it by. Two offices in
# one house pair with it in either direction; an office on a public address can never DIAL it, and a
# pair written the other way round is a link that can never handshake while both screens say "paired"
# (measured 2026-10-12 on vps1 against the owner's own HP — lnk-032). It is this office's own live
# decision, so the check below runs against the live office, not an office in memory.
docker run -d --rm --name "${D}" --network none --tmpfs /data --tmpfs /identity --tmpfs /registry \
  -e DGO_STATE_DIR=/data -e DGO_IDENTITY_DIR=/identity -e DGO_REGISTRY_DIR=/registry -e "DEPLOYMENT_NAME=${D}" \
  -e DGO_WG_ENDPOINT=192.168.16.100 -e DGO_WG_PUBLISH_PORT=51830 \
  "${IMG}" >/dev/null || { echo "dgo test fresh: could not start ${D}"; exit 2; }
for name in "${B}" "${C}" "${D}"; do
  for _ in $(seq 1 60); do [ "$(status "$(call "${name}" GET /healthz 2>/dev/null)")" = "200" ] && break; sleep 0.5; done
done

echo "— a brand-new office, before it has an identity —"
r="$(call "${B}" POST /api/pair/offer '{"direction":"both"}')"
check "an offer is refused in a sentence that names the command (409, not a crash)" \
  "$([ "$(status "${r}")" = "409" ] && echo "${r}" | grep -q 'bbox dgo identity mint' && echo 1)" "${r}"
for route in /api/pair /api/pair/giving /api/link; do
  x="$(call "${B}" GET "${route}")"
  check "GET ${route} answers the same refusal (the screens read it first)" \
    "$([ "$(status "${x}")" = "409" ] && echo "${x}" | grep -q 'bbox dgo identity mint' && echo 1)" "${x}"
done
check "the office itself is healthy all the while" "$([ "$(status "$(call "${B}" GET /healthz)")" = "200" ] && echo 1)" "healthz"

echo "— the two of them, each with a freshly minted identity —"
docker exec "${B}" python3 /app/identity.py --dir /identity --label "FRESH-B-PC" mint >/dev/null 2>&1
docker exec "${C}" python3 /app/identity.py --dir /identity --label "lima-bbox" mint >/dev/null 2>&1
pb="$(call "${B}" GET /api/pair)"; pc="$(call "${C}" GET /api/pair)"
idb="$(field "${pb}" "d['home']['id']")"; idc="$(field "${pc}" "d['home']['id']")"
check "a machine with a name of its own gets that name as its office id" "$([ "${idb}" = "fresh-b-pc" ] && echo 1)" "${idb}"
check "a machine whose name every such machine has gets an id from its key instead" \
  "$(echo "${idc}" | grep -qE '^office-[0-9a-f]{8}$' && echo 1)" "${idc}"
check "neither is named yet, and both say they only dial — with a reason and what would change it" \
  "$([ "$(field "${pb}" "(d['home']['named'], d.get('listen'), bool((d.get('dial_only') or {}).get('fix')))")" = "(False, None, True)" ] \
     && [ "$(field "${pc}" "(d['home']['named'], d.get('listen'), bool((d.get('dial_only') or {}).get('fix')))")" = "(False, None, True)" ] && echo 1)" "${pb}"
g="$(call "${B}" GET /api/pair/giving)"
check "a fresh office answers what it gives (nothing chosen yet)" \
  "$([ "$(status "${g}")" = "200" ] && [ "$(field "${g}" "(d['mode'], d['chosen'])")" = "('none', False)" ] && echo 1)" "${g}"

echo "— fresh-b (only dials) offers; the live office claims —"
off="$(call "${B}" POST /api/pair/offer '{"direction":"both"}')"
check "the fresh office mints an offer that names no address" \
  "$([ "$(status "${off}")" = "200" ] && [ "$(field "${off}" "(d['listens'], 'listen' in d['offer'])")" = "(False, False)" ] && echo 1)" "${off}"
cl="$(call "${LIVE}" POST /api/pair/claim "$(as_json text "$(field "${off}" "d['text']")" direction both)")"
if [ -n "${live_listen}" ]; then
  check "the live office reads it and proposes that the fresh office dials ITS address" \
    "$([ "$(status "${cl}")" = "200" ] && [ "$(field "${cl}" "(d['tunnel']['dial'], d['tunnel']['endpoint'])")" = "('joiner', '${live_listen}')" ] && echo 1)" "${cl}"
  check "its answer carries no token" "$(echo "${cl}" | grep -q '"token"' || echo 1)" "a token in the claim's answer"
  rp="$(call "${B}" POST /api/pair/reply "$(as_json text "$(field "${cl}" "d['reply_text']")")")"
  check "the fresh office opens the reply: the SAME six digits, and it sees who answered" \
    "$([ "$(status "${rp}")" = "200" ] && [ -n "$(field "${rp}" "d['code']")" ] && [ "$(field "${rp}" "d['code']")" = "$(field "${cl}" "d['code']")" ] \
       && [ "$(field "${rp}" "d['peer']['office_id']")" = "${live_id}" ] && echo 1)" "${rp}"
else
  check "the live office cannot be dialed either: the pair is refused with 409, in plain words" \
    "$([ "$(status "${cl}")" = "409" ] && ! echo "${cl}" | grep -q 'DGO_' && echo 1)" "${cl}"
fi

echo "— fresh-c (only dials) offers; fresh-b (only dials) claims —"
offc="$(call "${C}" POST /api/pair/offer '{"direction":"both"}')"
clb="$(call "${B}" POST /api/pair/claim "$(as_json text "$(field "${offc}" "d['text']")")")"
check "two offices that only dial are refused with 409, in plain words (no variable name in them)" \
  "$([ "$(status "${clb}")" = "409" ] && ! echo "${clb}" | grep -q 'DGO_' && echo 1)" "${clb}"

echo "— fresh-d (an office at home) offers; the live office claims —"
docker exec "${D}" python3 /app/identity.py --dir /identity --label "FRESH-D-HOME" mint >/dev/null 2>&1
pd="$(call "${D}" GET /api/pair)"
check "the office at home publishes the address its own LAN knows it by" \
  "$([ "$(field "${pd}" "(d.get('listen') or {}).get('endpoint')")" = "192.168.16.100" ] && echo 1)" "${pd}"
offd="$(call "${D}" POST /api/pair/offer '{"direction":"both"}')"
cld="$(call "${LIVE}" POST /api/pair/claim "$(as_json text "$(field "${offd}" "d['text']")" direction both)")"
if [ -n "${live_listen}" ]; then
  # THE DECISION THIS FILE EXISTS FOR (2026-10-12). "She published an address" is not "we can dial
  # it": a public office that dials a peer's private address writes a pair that can never handshake,
  # and every screen then says "paired". It listens on its own published address instead.
  check "the live office does NOT dial a private address it is not on — it listens and lets her dial" \
    "$([ "$(status "${cld}")" = "200" ] \
       && [ "$(field "${cld}" "d['tunnel']['endpoint']")" != "192.168.16.100" ] \
       && [ "$(field "${cld}" "(d['tunnel']['dial'], d['tunnel']['endpoint'])")" = "('joiner', '${live_listen}')" ] \
       && echo 1)" "${cld}"
else
  check "the live office cannot be dialed either: the pair is refused with 409, in plain words" \
    "$([ "$(status "${cld}")" = "409" ] && ! echo "${cld}" | grep -q 'DGO_' && echo 1)" "${cld}"
fi

echo "— nothing was written anywhere —"
after="$(call "${LIVE}" GET /api/pair)"
check "the live office's pairings are exactly what they were" \
  "$([ "$(field "${before}" "sorted(i['office'] for i in d['items'])")" = "$(field "${after}" "sorted(i['office'] for i in d['items'])")" ] && echo 1)" "${after}"
check "the fresh offices hold no pairing either" \
  "$([ "$(field "$(call "${B}" GET /api/pair)" "d['items']")" = "[]" ] && [ "$(field "$(call "${C}" GET /api/pair)" "d['items']")" = "[]" ] \
     && [ "$(field "$(call "${D}" GET /api/pair)" "d['items']")" = "[]" ] && echo 1)" "a fresh office holds a pairing"

echo
if [ "${fails}" = "0" ]; then echo "PASS — fresh offices, 0 failing check(s)"; else echo "FAIL — ${fails} failing check(s)"; fi
exit "${fails}"
