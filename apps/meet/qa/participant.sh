#!/bin/sh
# Runs INSIDE the test container: one synthetic participant, its own Chrome process.
#   participant.sh <id> <display name> <room> <wav|none> <x> <y> <host|guest|share> <video height> <devtools port>
# The host reads its token from /t/host.jwt (minted in meet-start, never printed).
set -u
id="$1"; name="$2"; room="$3"; wav="$4"; x="$5"; y="$6"; kind="$7"; res="${8:-180}"; port="${9:-9222}"
base="https://meet.fpg.digital-office.co.il/$room"
q=""
[ "$kind" = host ] && q="?jwt=$(cat /t/host.jwt)"
enc=$(printf '%s' "$name" | sed 's/ /%20/g')
# single-layer video at the given height and at most one received stream: the participants must
# not load the 2-vCPU box more than remote people would.
hash="config.prejoinConfig.enabled=false&userInfo.displayName=%22${enc}%22&config.resolution=${res}&config.constraints.video.height.ideal=${res}&config.constraints.video.height.max=${res}&config.disableSimulcast=true&config.channelLastN=1"
case "$kind" in
  share) hash="$hash&config.startWithAudioMuted=true&config.startWithVideoMuted=true" ;;
esac
url="$base$q#$hash"
audio=""
[ "$wav" != none ] && audio="--use-file-for-fake-audio-capture=/t/$wav"
export DISPLAY=:11
rm -rf "/tmp/prof-$id"
exec google-chrome --no-sandbox --disable-gpu --disable-dev-shm-usage --no-first-run --no-default-browser-check \
  --disable-extensions --disable-background-networking --disable-sync --mute-audio \
  --use-fake-ui-for-media-stream --use-fake-device-for-media-stream $audio \
  --auto-select-desktop-capture-source="Entire screen" \
  --remote-debugging-port="$port" --remote-allow-origins='*' \
  --autoplay-policy=no-user-gesture-required --window-size=900,560 --window-position=$x,$y \
  --user-data-dir="/tmp/prof-$id" --enable-logging=stderr --v=0 "$url" > "/t/out/chrome-$id.log" 2>&1
