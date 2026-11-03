#!/bin/sh
# Inside the test container: Chrome plays the fake-capture file ONCE (measured 2026-10-26), so the
# speech files are made 8 minutes long (the short ones looped 20 times).
set -eu
cd /t
for w in host guest; do
  ffmpeg -nostdin -y -v error -stream_loop 20 -i $w.wav -c:a pcm_s16le $w.long.wav
  ffprobe -v error -show_entries format=duration -of csv=p=0 $w.long.wav
done
echo LONGWAV-OK
