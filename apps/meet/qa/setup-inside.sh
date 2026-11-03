#!/bin/sh
# Runs INSIDE the throwaway test container (jibri image, root): TTS wavs + a dummy X display.
set -eu
cd /t
cat > host.txt <<'EOF'
This is the fireplace office recording check. The host is counting now: one, two, three, four, five, six, seven, eight, nine, ten. Fireplace host is done speaking.
EOF
cat > guest.txt <<'EOF'
Guest speaking now. Alpha, bravo, charlie, delta, echo, foxtrot, golf, hotel, india, juliet. Fireplace guest is done speaking.
EOF
# host: speech then 12 s of silence; guest: 12 s of silence then speech (so they mostly alternate)
ffmpeg -nostdin -y -v error -f lavfi -i "flite=textfile=/t/host.txt:voice=slt" -af "apad=pad_dur=12" -ac 1 -ar 48000 -c:a pcm_s16le host.wav
ffmpeg -nostdin -y -v error -f lavfi -i "flite=textfile=/t/guest.txt:voice=rms" -af "adelay=12000,apad=pad_dur=1" -ac 1 -ar 48000 -c:a pcm_s16le guest.wav
for w in host.wav guest.wav; do ffprobe -v error -show_entries format=duration -of csv=p=0 $w; done
mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
# the dummy X server the participants' Chrome windows draw on: the same driver and config Jibri uses,
# taken RENDERED from the live recorder first (the image's /defaults copy is a template):
#   docker exec meet-jibri-<name> cat /run/jibri/config/xorg-video-dummy.conf > /root/meet-test/xorg-dummy.conf
nohup Xorg -noreset -nolisten tcp +extension RANDR +extension RENDER -logfile /tmp/xorg11.log -config /t/xorg-dummy.conf :11 >/tmp/xorg11.out 2>&1 &
sleep 3
ls -la /tmp/.X11-unix/
curl -sS -o /dev/null -w "meet web: %{http_code}\n" --max-time 10 https://meet.fpg.digital-office.co.il/
echo SETUP-OK
