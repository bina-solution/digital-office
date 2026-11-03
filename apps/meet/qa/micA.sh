#!/bin/bash
# Test (a), on the HOST: a synthetic call with a host that speaks, a guest whose microphone is on but
# gives digital silence (silence.wav), and a guest with no microphone track at all (never unmuted).
# Expect, within ~15 s: the two private warnings, the host's two room notes, the red banner on the
# no-mic page. Then the no-mic guest is unmuted (Chrome's fake device, a tone) → the «✅» lines.
#   micA.sh <tag> <room>
set -u
tag="$1"; room="$2"; T=/root/meet-test; out=$T/out/$tag; mkdir -p "$out"
log() { echo "$(date -u +%T)Z +$(( $(date +%s) - T0 ))s $*" | tee -a "$out/timeline.log"; }
P() { docker exec -d meet-test sh /t/participant.sh "$@"; }
K() { docker exec meet-test pkill -f "prof-$1" >/dev/null 2>&1; }
J() { docker exec meet-test python3 /t/cdp.py "$1" "$2" 2>/dev/null; }
CHAT='(function(){var s=APP.store.getState();var m=(s["features/chat"]||{}).messages||[];var b=document.getElementById("meet-mic-banner");return JSON.stringify({n:m.length,banner:b?b.getAttribute("data-state"):null,joined:APP.conference.isJoined(),muted:APP.conference.isLocalAudioMuted(),msgs:m.map(function(x){return (x.displayName||"?")+": "+String(x.message).slice(0,70)})})})()'
unmute() { J "$1" 'APP.conference.isJoined() && APP.conference.isLocalAudioMuted() ? (APP.conference.muteAudio(false), "unmuted") : "ok"'; }
conferences() { docker exec meet-jvb-fireplace curl -s localhost:8080/colibri/stats | python3 -c 'import json,sys;print(json.load(sys.stdin)["conferences"])'; }
at() { local want=$1; shift; local now=$(( $(date +%s) - T0 )); [ $now -lt $want ] && sleep $(( want - now )); log "$*"; }
seen=""
poll() {   # chat + banner of every page, said only when something changes
  for p in 9301 9302 9303; do
    r=$(J $p "$CHAT" | cut -c1-900)
    key="$p:$r"
    case "$seen" in *"$key"*) ;; *) seen="$seen|$key"; log "page $p $r" ;; esac
  done
}

T0=$(date +%s); log "start tag=$tag room=$room conferences_before=$(conferences)"
P host "QA Host" "$room" host.long.wav 0 0 host 360 9301;   log "host started"
at 4  "silent-mic guest starts";   P silent "Silent Mic" "$room" silence.wav 300 100 guest 180 9302
at 6  "no-mic guest starts";       P nomic "No Mic" "$room" none 500 200 guest 180 9303
# unmute the host and the silent guest as soon as they are joined (never the no-mic one)
for i in $(seq 1 90); do
  sleep 5
  for p in 9301 9302; do r=$(unmute $p); [ -n "$r" ] && [ "$r" != '{"type": "string", "value": "ok"}' ] && log "unmute $p $r"; done
  poll
  now=$(( $(date +%s) - T0 ))
  if [ $now -ge 95 ] && [ -z "${unmuted3:-}" ]; then unmuted3=1; log "now unmuting the no-mic guest: $(unmute 9303)"; fi
  [ $now -ge 140 ] && break
  c=$(conferences); [ "$c" != "1" ] && [ "$c" != "0" ] && { log "ANOTHER CONFERENCE APPEARED ($c) — stopping the test"; break; }
done
# the bridge's view of the endpoints (shape of the debug document), and prosody's word
docker exec meet-jvb-fireplace curl -s localhost:8080/debug > "$out/jvb-debug.json" 2>/dev/null
cid=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(list(d.get("conferences",{}).keys())[0] if d.get("conferences") else "")' "$out/jvb-debug.json")
[ -n "$cid" ] && docker exec meet-jvb-fireplace curl -s "localhost:8080/debug/$cid" > "$out/jvb-conference.json" 2>/dev/null
log "final chats:"; poll
K host; K silent; K nomic; sleep 3; docker exec meet-test pkill -f google-chrome >/dev/null 2>&1
docker logs meet-prosody-fireplace --since 6m 2>&1 | grep -E "meet_silent_mic|meet_recorder_watch" | grep -v "asks http" | cut -c1-260 | tee -a "$out/timeline.log"
log "done"
