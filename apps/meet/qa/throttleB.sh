#!/bin/bash
# Test (b), on the HOST, during a TEST call only: starve the recorder for ~60 s and watch the room be
# told, then told it is fine again. Records the recorder's cgroup values before, throttles with
# `docker update --cpus 0.4`, restores `--cpus 2.0`, and checks cpu.max / weight / memory.low after.
#   throttleB.sh <tag> <room>
set -u
tag="$1"; room="$2"; T=/root/meet-test; out=$T/out/$tag; mkdir -p "$out"
JIB=meet-jibri-fireplace
cg() { echo /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$1").scope; }
CG=$(cg $JIB)
log() { echo "$(date -u +%T)Z +$(( $(date +%s) - T0 ))s $*" | tee -a "$out/timeline.log"; }
P() { docker exec -d meet-test sh /t/participant.sh "$@"; }
K() { docker exec meet-test pkill -f "prof-$1" >/dev/null 2>&1; }
J() { docker exec meet-test python3 /t/cdp.py "$1" "$2" 2>/dev/null; }
CHAT='(function(){var s=APP.store.getState();var m=(s["features/chat"]||{}).messages||[];return JSON.stringify({n:m.length,joined:APP.conference.isJoined(),muted:APP.conference.isLocalAudioMuted(),msgs:m.map(function(x){return (x.displayName||"?")+": "+String(x.message).slice(0,90)})})})()'
unmute() { J "$1" 'APP.conference.isJoined() && APP.conference.isLocalAudioMuted() ? (APP.conference.muteAudio(false), "unmuted") : "ok"'; }
conferences() { docker exec meet-jvb-fireplace curl -s localhost:8080/colibri/stats | python3 -c 'import json,sys;print(json.load(sys.stdin)["conferences"])'; }
busy() { docker exec $JIB python3 -c 'import urllib.request,json;print(json.load(urllib.request.urlopen("http://localhost:2222/jibri/api/v1.0/health"))["status"]["busyStatus"])' 2>/dev/null; }
cgvals() { echo "cpu.max=$(cat $CG/cpu.max | tr ' ' '/') weight=$(cat $CG/cpu.weight) memory.low=$(cat $CG/memory.low) nr_throttled=$(awk '$1=="nr_throttled"{print $2}' $CG/cpu.stat) nanocpus=$(docker inspect -f '{{.HostConfig.NanoCpus}}' $JIB) shares=$(docker inspect -f '{{.HostConfig.CpuShares}}' $JIB)"; }
seen=""
poll() { r=$(J 9301 "$CHAT" | cut -c1-1500); case "$seen" in *"$r"*) ;; *) seen="$seen|$r"; log "host chat $r" ;; esac; }
restore() { docker update --cpus 2.0 $JIB >/dev/null; log "RESTORED --cpus 2.0: $(cgvals)"; }
trap 'restore' EXIT

before=$(docker exec $JIB sh -c 'ls /storage/recordings' | sort)
T0=$(date +%s); log "start tag=$tag room=$room conferences_before=$(conferences) jibri=$(busy)"; log "BEFORE: $(cgvals)"
P host "QA Host" "$room" host.long.wav 0 0 host 360 9301; log "host started (auto-record)"
phase=wait
for i in $(seq 1 80); do
  sleep 5
  r=$(unmute 9301); [ -n "$r" ] && [ "$r" != '{"type": "string", "value": "ok"}' ] && log "unmute 9301 $r"
  poll
  now=$(( $(date +%s) - T0 ))
  b=$(busy)
  if [ "$phase" = wait ] && [ "$b" = BUSY ]; then phase=recording; TR=$(date +%s); log "recorder BUSY"; fi
  if [ "$phase" = recording ] && [ $(( $(date +%s) - TR )) -ge 50 ]; then
    phase=throttled; docker update --cpus 0.4 $JIB >/dev/null; TT=$(date +%s); log "THROTTLED --cpus 0.4: $(cgvals)"
  fi
  if [ "$phase" = throttled ] && [ $(( $(date +%s) - TT ))  -ge 60 ]; then
    phase=restored; restore; trap - EXIT
  fi
  if [ "$phase" = restored ] && [ $(( $(date +%s) - TT )) -ge 150 ]; then break; fi
  c=$(conferences); [ "$c" != "1" ] && [ "$c" != "0" ] && { log "ANOTHER CONFERENCE APPEARED ($c) — stopping the test"; break; }
done
log "final: $(J 9301 "$CHAT" | cut -c1-2500)"
K host; sleep 3; docker exec meet-test pkill -f google-chrome >/dev/null 2>&1
log "waiting for the recording to end"
for i in $(seq 1 30); do [ "$(busy)" = IDLE ] && break; sleep 5; done
sleep 8
now=$(docker exec $JIB sh -c 'ls /storage/recordings' | sort); new=$(comm -13 <(echo "$before") <(echo "$now") | tail -1); log "session $new"
docker exec $JIB sh -c "ls -la /storage/recordings/$new; cat /storage/recordings/$new/*.capture.json" 2>&1 | tee -a "$out/timeline.log"
docker logs $JIB --since 12m 2>&1 | grep meet-watch | cut -c1-300 | tee -a "$out/timeline.log"
# the notice centre's row for this recording (one per recording: warning, then info when it recovered)
docker exec notifications-fireplace python3 -c '
import urllib.request, json
d = json.load(urllib.request.urlopen("http://localhost:8977/api/notifications?source=meet-recorder&limit=5"))
for n in d.get("notifications", []):
    print("notification", n.get("id"), n.get("level"), n.get("source_id"), "|", n.get("title"), "|", (n.get("body") or "")[:160], "| created", n.get("created_at"), "updated", n.get("updated_at"))
' 2>&1 | tee -a "$out/timeline.log"
log "AFTER: $(cgvals)"
log "done"
