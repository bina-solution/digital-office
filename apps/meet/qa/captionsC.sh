#!/bin/bash
# Test (c), on the HOST: live captions forced on for one test call (the runtime override file inside
# meet-jibri), a host and a guest speaking English TTS. Samples the recorder's and the transcriber's
# cgroups every 5 s, reads the chat for «כתוביות» lines and the overlay, and collects the watchdog's
# own latency lines. Also checks what a muted track looks like in presence (SourceInfo), so a person
# who mutes on purpose is never told they have no microphone.
#   captionsC.sh <tag> <room> [seconds of call, default 240]
set -u
tag="$1"; room="$2"; dur="${3:-240}"; T=/root/meet-test; out=$T/out/$tag; mkdir -p "$out"
JIB=meet-jibri-fireplace
cg() { echo /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "$1").scope; }
CJ=$(cg $JIB); CA=$(cg apitools-asr-fireplace); CV=$(cg meet-jvb-fireplace)
stat() { awk -v k="$2" '$1==k{print $2}' "$1/cpu.stat"; }
log() { echo "$(date -u +%T)Z +$(( $(date +%s) - T0 ))s $*" | tee -a "$out/timeline.log"; }
P() { docker exec -d meet-test sh /t/participant.sh "$@"; }
K() { docker exec meet-test pkill -f "prof-$1" >/dev/null 2>&1; }
J() { docker exec meet-test python3 /t/cdp.py "$1" "$2" 2>/dev/null; }
CHAT='(function(){var s=APP.store.getState();var m=(s["features/chat"]||{}).messages||[];var c=document.getElementById("meet-captions");var n=(s["features/notifications"]||{}).notifications||[];return JSON.stringify({n:m.length,joined:APP.conference.isJoined(),muted:APP.conference.isLocalAudioMuted(),overlay:c&&c.style.display!=="none"?c.textContent.slice(0,80):null,notifications:n.map(function(x){return String((x.props||{}).title||(x.props||{}).titleKey||"").slice(0,40)}),msgs:m.map(function(x){return (x.displayName||"?")+": "+String(x.message).slice(0,110)})})})()'
PRES='(function(){var lp=APP.conference._room.room.lastPresences||{};return JSON.stringify(Object.keys(lp).map(function(j){var si=(lp[j]||[]).filter(function(x){return x.tagName==="SourceInfo"})[0];return j.split("/")[1]+" "+(si?si.value:"-")}))})()'
unmute() { J "$1" 'APP.conference.isJoined() && APP.conference.isLocalAudioMuted() ? (APP.conference.muteAudio(false), "unmuted") : "ok"'; }
conferences() { docker exec meet-jvb-fireplace curl -s localhost:8080/colibri/stats | python3 -c 'import json,sys;print(json.load(sys.stdin)["conferences"])'; }
busy() { docker exec $JIB python3 -c 'import urllib.request,json;print(json.load(urllib.request.urlopen("http://localhost:2222/jibri/api/v1.0/health"))["status"]["busyStatus"])' 2>/dev/null; }
sampler() {
  echo "t,jibri_usage_us,jibri_nr_periods,jibri_nr_throttled,jibri_throttled_us,asr_usage_us,asr_nr_throttled,jvb_usage_us,load1,mem_avail_mb" > "$out/samples.csv"
  while true; do
    echo "$(( $(date +%s) - T0 )),$(stat $CJ usage_usec),$(stat $CJ nr_periods),$(stat $CJ nr_throttled),$(stat $CJ throttled_usec),$(stat $CA usage_usec),$(stat $CA nr_throttled),$(stat $CV usage_usec),$(cut -d' ' -f1 /proc/loadavg),$(( $(awk '/MemAvailable/{print $2}' /proc/meminfo) / 1024 ))" >> "$out/samples.csv"
    sleep 5
  done
}
seen=""
poll() { for p in 9301 9302; do r=$(J $p "$CHAT" | cut -c1-2000); key="$p:$r"; case "$seen" in *"$key"*) ;; *) seen="$seen|$key"; log "page $p $r" ;; esac; done; }

before=$(docker exec $JIB sh -c 'ls /storage/recordings' | sort)
docker exec $JIB sh -c 'mkdir -p /run/meet-watch && echo on > /run/meet-watch/captions && cat /run/meet-watch/captions'
T0=$(date +%s); log "start tag=$tag room=$room dur=$dur conferences_before=$(conferences) jibri=$(busy) captions override=on"
sampler & SP=$!
P host "QA Host" "$room" host.long.wav 0 0 host 360 9301; log "host started (auto-record)"
sleep 4; P guest "QA Guest" "$room" guest.long.wav 300 100 guest 180 9302; log "guest started"
muted_check=""
for i in $(seq 1 200); do
  sleep 5
  for p in 9301 9302; do r=$(unmute $p); [ -n "$r" ] && [ "$r" != '{"type": "string", "value": "ok"}' ] && log "unmute $p $r"; done
  poll
  now=$(( $(date +%s) - T0 ))
  # at ~90 s: the guest mutes on purpose for 40 s — the presence must show a MUTED track, and nobody
  # must be told they have no microphone; then unmutes
  if [ $now -ge 90 ] && [ -z "$muted_check" ]; then muted_check=1; log "guest mutes on purpose: $(J 9302 'APP.conference.muteAudio(true), "muted"')"; sleep 6; log "presences seen by the host: $(J 9301 "$PRES" | cut -c1-600)"; fi
  if [ $now -ge 130 ] && [ "$muted_check" = 1 ]; then muted_check=2; log "guest unmutes: $(J 9302 'APP.conference.muteAudio(false), "unmuted"')"; fi
  [ $now -ge $dur ] && break
  c=$(conferences); [ "$c" != "1" ] && [ "$c" != "0" ] && { log "ANOTHER CONFERENCE APPEARED ($c) — stopping the test"; break; }
done
log "final host chat: $(J 9301 "$CHAT" | cut -c1-4000)"
K host; K guest; sleep 3; docker exec meet-test pkill -f google-chrome >/dev/null 2>&1
log "waiting for the recording to end"
for i in $(seq 1 40); do [ "$(busy)" = IDLE ] && break; sleep 5; done
sleep 10; kill $SP 2>/dev/null
docker exec $JIB sh -c 'echo auto > /run/meet-watch/captions'; log "captions override back to auto"
new=$(comm -13 <(echo "$before") <(docker exec $JIB sh -c 'ls /storage/recordings' | sort) | tail -1); log "session $new"
docker exec $JIB sh -c "ls -la /storage/recordings/$new; echo '--- live.txt'; cat /storage/recordings/$new/*.live.txt; echo '--- capture.json'; cat /storage/recordings/$new/*.capture.json" 2>&1 | tee -a "$out/timeline.log"
docker logs $JIB --since 15m 2>&1 | grep meet-watch | cut -c1-300 | tee "$out/watch.log" | grep -E "caption|DEGRADED|OK again|ended|lag" | tail -40
docker logs meet-prosody-fireplace --since 15m 2>&1 | grep -E "meet_silent_mic.*(told|first time)" | cut -c1-220 | tee -a "$out/timeline.log"
python3 - "$out/samples.csv" <<'EOF' | tee -a "$out/timeline.log"
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
a, b = rows[0], rows[-1]
dt = int(b['t']) - int(a['t'])
d = lambda k: (int(b[k]) - int(a[k]))
print(f"run {dt}s: jibri cpu {d('jibri_usage_us')/1e6:.0f}s ({d('jibri_usage_us')/1e6/dt:.2f} cores avg), throttled {d('jibri_nr_throttled')} of {d('jibri_nr_periods')} periods ({d('jibri_throttled_us')/1e6:.1f} s); "
      f"asr cpu {d('asr_usage_us')/1e6:.0f}s ({d('asr_usage_us')/1e6/dt:.2f} cores avg), asr throttled periods {d('asr_nr_throttled')}; jvb cpu {d('jvb_usage_us')/1e6:.0f}s; "
      f"load1 max {max(float(r['load1']) for r in rows)}; mem_avail min {min(int(r['mem_avail_mb']) for r in rows)} MB")
# per-minute: cores used by jibri / asr, throttled periods
for m in range(0, dt, 60):
    seg = [r for r in rows if m <= int(r['t']) < m + 60]
    if len(seg) < 2: continue
    x, y = seg[0], seg[-1]; w = int(y['t']) - int(x['t']) or 1
    print(f"  min {m//60}: jibri {(int(y['jibri_usage_us'])-int(x['jibri_usage_us']))/1e6/w:.2f} cores, throttled {int(y['jibri_nr_throttled'])-int(x['jibri_nr_throttled'])} periods; asr {(int(y['asr_usage_us'])-int(x['asr_usage_us']))/1e6/w:.2f} cores; load1 {y['load1']}")
EOF
log "done"
