#!/bin/bash
# Restore a chopped Jibri recording (the measured chain, see README.md).
#
# usage: restore_recording.sh REC.mp4 OUT_DIR [--systems "raw post n12f"] [--trim 0.4 --pause 0.3] [--tag restored2] [--no-video]
#
# OUT_DIR gets, for <room>_<stamp>.mp4:
#   <room>-<tag>_<stamp>.ogg / .mp4   listening version on the ORIGINAL timeline: LPC-shaped noise (−12 dB) in every hole
#                                     ≤ 0.3 s + a −55 dBFS floor, loudnorm; the mp4 keeps the original video (stream copy)
#   trim.wav + trim.map.json          ASR timeline: holes ≥ --trim s shortened to --pause s, everything else untouched;
#                                     the map converts ASR times back to the original clock (python mk_comment2.py --map)
#   asr/raw.wav asr/post.wav asr/n12f.wav   the ASR inputs (16 kHz): plain / +highpass-compressor-loudnorm / +noise fill
#   transcript.json                   faster-whisper (ivrit-ai/whisper-large-v3-turbo-ct2, int8, beam 5, temperature
#                                     fallback, word timestamps) for every ASR input
#   stats.json                        burst/hole statistics of the original (the damage fingerprint)
# Then: restore_transcript.sh OUT_DIR <room>-<tag>_<stamp> "method text" "benchmark text"   (LLM layer + Plane comment)
#
# Needs: ffmpeg, python with numpy soundfile soxr scipy faster-whisper (set VENV to a venv to activate).
# CPU: whisper turbo int8 runs at ~0.3x real time per worker on 6 ARM cores; a 48-min recording trimmed to 25 min takes
# ~80 min for two inputs. Never run on the office VPS.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
IN=$1; OUT=$2; shift 2
SYSTEMS="raw post n12f"; TRIM_MIN=0.4; TRIM_PAUSE=0.3; TAG=restored2; VIDEO=1; THREADS=${THREADS:-6}
while [ $# -gt 0 ]; do
  case $1 in
    --systems) SYSTEMS=$2; shift 2 ;;
    --trim) TRIM_MIN=$2; shift 2 ;;
    --pause) TRIM_PAUSE=$2; shift 2 ;;
    --tag) TAG=$2; shift 2 ;;
    --no-video) VIDEO=0; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
[ -n "${VENV:-}" ] && source "$VENV/bin/activate"
POST="highpass=f=80,acompressor=threshold=-28dB:ratio=3:attack=5:release=150:makeup=6,loudnorm=I=-18:TP=-2:LRA=11"
LN="loudnorm=I=-18:TP=-2:LRA=11"
F16="-ac 1 -ar 16000 -c:a pcm_s16le"
base=$(basename "$IN" .mp4); room=${base%_*}; stamp=${base##*_}
NAME="${room}-${TAG}_${stamp}"
mkdir -p "$OUT/asr"; cd "$OUT"
echo "== $base -> $NAME (systems: $SYSTEMS, trim >= ${TRIM_MIN}s -> ${TRIM_PAUSE}s)"
[ -f src44.wav ] || ffmpeg -nostdin -v error -y -i "$IN" -vn -ac 1 -ar 44100 -c:a pcm_s16le src44.wav
[ -f trim.wav ] || python "$HERE/restore.py" src44.wav trim.wav --mode cut --no-edgefix --keep-short --cut-min $TRIM_MIN --pause $TRIM_PAUSE --map trim.map.json --stats stats.json
[ -f asr/raw.wav ]  || ffmpeg -nostdin -v error -y -i trim.wav $F16 asr/raw.wav
[ -f asr/post.wav ] || ffmpeg -nostdin -v error -y -i trim.wav -af "$POST" $F16 asr/post.wav
if echo "$SYSTEMS" | grep -q n12f; then
  [ -f trim_n12f.wav ] || python "$HERE/noisefill.py" trim.wav trim_n12f.wav --level -12 --floor -55
  [ -f asr/n12f.wav ] || ffmpeg -nostdin -v error -y -i trim_n12f.wav -af "$POST" $F16 asr/n12f.wav
fi
[ -f listen_raw.wav ] || python "$HERE/noisefill.py" src44.wav listen_raw.wav --level -12 --floor -55
[ -f listen.wav ] || ffmpeg -nostdin -v error -y -i listen_raw.wav -af "$LN" -ac 1 -ar 44100 -c:a pcm_s16le listen.wav
[ -f "$NAME.ogg" ] || ffmpeg -nostdin -v error -y -i listen.wav -vn -ac 1 -ar 16000 -c:a libopus -b:a 32k -f ogg "$NAME.ogg"
if [ $VIDEO = 1 ] && [ ! -f "$NAME.mp4" ]; then
  ffmpeg -nostdin -v error -y -i listen.wav -c:a aac -b:a 96k listen.m4a
  # no -shortest: Jibri's video track ends a few seconds before its audio, and -shortest cut the restored audio's tail (fpg103 lost 4.5 s, 2026-10-27)
  ffmpeg -nostdin -v error -y -i "$IN" -i listen.m4a -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy -movflags +faststart "$NAME.mp4"
fi
for f in trim.wav "$NAME.ogg"; do echo "$f $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f") s"; done
cat stats.json | tr -d "\n "; echo
FILES=""; for S in $SYSTEMS; do FILES="$FILES asr/$S.wav"; done
python "$HERE/asr_run.py" "$OUT/transcript.json" --temp 0,0.2,0.4,0.6,0.8,1.0 --threads $THREADS $FILES
rm -f listen_raw.wav listen.m4a
echo "done: $OUT/$NAME.ogg $OUT/$NAME.mp4 $OUT/transcript.json"
