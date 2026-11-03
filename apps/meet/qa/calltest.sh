#!/bin/bash
# Runs on the HOST: orchestrates a synthetic multi-participant call against the live FPG Meet and
# samples the recorder's cgroup while it runs.   calltest.sh <tag> <room> [guest video height]
# Timeline (s): 0 host joins (auto-record) · 25 guest joins · 60 sharer joins (screen share on)
# · 150 sharer leaves · 180 guest leaves · 210 guest rejoins · 240 sharer rejoins · 330 sharer leaves
# · 345 guest leaves · 360 host leaves (the room ends, the recording stops).
# Each participant is unmuted / set sharing through Chrome's DevTools once the page has joined (the
# page creates no local tracks on its own with the prejoin page off: measured 2026-10-26), by a
# babysitter that looks every 10 s (a Chrome on this box takes 12-25 s to come up).
set -u
tag="$1"; room="$2"; res="${3:-180}"; T=/root/meet-test; out=$T/out/$tag; mkdir -p "$out"
cg() { find /sys/fs/cgroup/system.slice -maxdepth 1 -name "docker-$(docker inspect -f '{{.Id}}' "$1").scope"; }
JIB=$(cg meet-jibri-fireplace); JVB=$(cg meet-jvb-fireplace); ASR=$(cg apitools-asr-fireplace)
stat() { awk -v k="$2" '$1==k{print $2}' "$1/cpu.stat"; }
log() { echo "$(date -u +%T)Z +$(( $(date +%s) - T0 ))s $*" | tee -a "$out/timeline.log"; }
sampler() {
  echo "t,jibri_usage_us,jibri_throttled_us,jibri_nr_throttled,jvb_usage_us,jvb_throttled_us,asr_usage_us,load1,mem_avail_mb,jibri_cpu_max,asr_weight" > "$out/samples.csv"
  while true; do
    echo "$(( $(date +%s) - T0 )),$(stat $JIB usage_usec),$(stat $JIB throttled_usec),$(stat $JIB nr_throttled),$(stat $JVB usage_usec),$(stat $JVB throttled_usec),$(stat $ASR usage_usec),$(cut -d' ' -f1 /proc/loadavg),$(( $(awk '/MemAvailable/{print $2}' /proc/meminfo) / 1024 )),$(cat $JIB/cpu.max | tr ' ' '/'),$(cat $ASR/cpu.weight)" >> "$out/samples.csv"
    sleep 5
  done
}
P() { docker exec -d meet-test sh /t/participant.sh "$@"; }
K() { docker exec meet-test pkill -f "prof-$1" >/dev/null 2>&1; }
J() { docker exec meet-test python3 /t/cdp.py "$1" "$2" 2>/dev/null | cut -c1-200; }
STATE='({joined: APP.conference.isJoined(), audioMuted: APP.conference.isLocalAudioMuted(), videoMuted: APP.conference.isLocalVideoMuted(), sharing: APP.conference.isSharingScreen, n: APP.conference.membersCount})'
babysit() {   # unmute host/guest, and start the share, whenever a page is joined and not yet so
  local ok='{"type": "string", "value": "ok"}' r lastkey=0
  while true; do
    for p in 9301 9302; do
      r=$(J $p 'APP.conference.isJoined() && (APP.conference.isLocalAudioMuted() || APP.conference.isLocalVideoMuted()) ? (APP.conference.muteAudio(false), APP.conference.muteVideo(false), "unmuted") : "ok"')
      [ -n "$r" ] && [ "$r" != "$ok" ] && log "babysit $p $r"
    done
    # the share: Jitsi's "d" shortcut as a real key press (APP.conference.toggleScreenSharing is gone
    # in this build); at most once per 30 s, since the share takes a few seconds to show as on
    r=$(J 9303 'APP.conference.isJoined() && !APP.conference.isSharingScreen ? "wants share" : "ok"')
    if [ "$r" = '{"type": "string", "value": "wants share"}' ] && [ $(( $(date +%s) - lastkey )) -ge 30 ]; then
      lastkey=$(date +%s); log "babysit 9303 $(J 9303 key:d)"
    fi
    sleep 10
  done
}
at() { local want=$1; shift; local now=$(( $(date +%s) - T0 )); [ $now -lt $want ] && sleep $(( want - now )); log "$*"; }

before=$(docker exec meet-jibri-fireplace sh -c 'ls /storage/recordings' | sort)
T0=$(date +%s); log "start tag=$tag room=$room guest_res=$res jibri cpu.max=$(cat $JIB/cpu.max) jibri weight=$(cat $JIB/cpu.weight) asr weight=$(cat $ASR/cpu.weight)"
sampler & SP=$!
babysit & BS=$!
P host "Verify Host" "$room" host.long.wav 0 0 host 360 9301;   log "host started (recording should start automatically)"
at 25  "guest starts";       P guest "Verify Guest" "$room" guest.long.wav 300 100 guest "$res" 9302
at 60  "sharer starts";      P share "Verify Share" "$room" none 500 200 share 180 9303
at 100 "state host $(J 9301 "$STATE") guest $(J 9302 "$STATE") share $(J 9303 "$STATE")"
at 150 "sharer leaves";      K share
at 180 "guest leaves";       K guest
at 210 "guest rejoins";      P guest "Verify Guest" "$room" guest.long.wav 300 100 guest "$res" 9302
at 240 "sharer rejoins";     P share "Verify Share" "$room" none 500 200 share 180 9303
at 290 "state host $(J 9301 "$STATE") guest $(J 9302 "$STATE") share $(J 9303 "$STATE")"
at 330 "sharer leaves";      K share
at 345 "guest leaves";       K guest
at 360 "host leaves";        K host
kill $BS 2>/dev/null
sleep 5; docker exec meet-test pkill -f google-chrome >/dev/null 2>&1
log "waiting for the recording to be finalized"
for i in $(seq 1 60); do
  now=$(docker exec meet-jibri-fireplace sh -c 'ls /storage/recordings' | sort)
  new=$(comm -13 <(echo "$before") <(echo "$now") | tail -1)
  [ -n "$new" ] && docker exec meet-jibri-fireplace sh -c "ls /storage/recordings/$new/*.ogg" >/dev/null 2>&1 && break
  sleep 5
done
kill $SP 2>/dev/null
log "recording session: $new"
echo "$new" > "$out/session.txt"
docker exec meet-jibri-fireplace sh -c "ls -la /storage/recordings/$new; cat /storage/recordings/$new/metadata.json; echo; cat /storage/recordings/$new/*.silence.json" | tee -a "$out/timeline.log"
docker exec meet-jibri-fireplace sh -c "grep -E 'session_id=$new' /var/log/jitsi/jibri/log.0.txt | grep -E 'Starting ffmpeg|Stopping ffmpeg' | sed -E 's/^Jibri //' | cut -c1-120; grep -E 'Lsize=' /var/log/jitsi/jibri/ffmpeg.0.txt | tail -1 | sed -E 's/^.*#61: //'" | tee -a "$out/timeline.log"
docker logs meet-jicofo-fireplace --since 20m 2>&1 | grep "room=$room" | grep -E "Member joined|Member left|status on|status off|Room destroyed|Accepted initial sources" | sed -E 's/ INFO: \[[0-9]+\] \[room=[^]]*\]//; s/features=.*//; s/stats-id=([A-Za-z0-9-]+).*isJibri=(true|false).*/\1 jibri=\2/; s/(Accepted initial sources from [0-9a-f]+).*/\1/' | cut -c1-150 | tee -a "$out/timeline.log"
python3 - "$out/samples.csv" <<'EOF' | tee -a "$out/timeline.log"
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
a, b = rows[0], rows[-1]
dt = int(b['t']) - int(a['t'])
d = lambda k: (int(b[k]) - int(a[k])) / 1e6
print(f"run {dt}s: jibri cpu {d('jibri_usage_us'):.0f}s ({d('jibri_usage_us')/dt:.2f} cores avg), throttled {d('jibri_throttled_us'):.0f}s in {int(b['jibri_nr_throttled'])-int(a['jibri_nr_throttled'])} periods; "
      f"jvb cpu {d('jvb_usage_us'):.0f}s ({d('jvb_usage_us')/dt:.2f} cores), throttled {d('jvb_throttled_us'):.0f}s; asr cpu {d('asr_usage_us'):.0f}s ({d('asr_usage_us')/dt:.2f} cores); "
      f"load1 max {max(float(r['load1']) for r in rows)}; mem_avail min {min(int(r['mem_avail_mb']) for r in rows)} MB; jibri cpu.max {b['jibri_cpu_max']}; asr weight {b['asr_weight']}")
EOF
log "done"
