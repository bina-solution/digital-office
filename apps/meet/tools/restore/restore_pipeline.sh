#!/bin/bash
# Restore a Jibri recording whose sound was chopped into bursts with exact-zero gaps (recorder CPU-throttled).
#
# usage: restore_pipeline.sh IN.mp4 OUT_DIR [--listen METHOD] [--asr METHOD] [--model turbo|large]
#                            [--beam 5] [--temps 0] [--tag restored2] [--no-video] [--threads 6]
#
# Writes into OUT_DIR, for <room>_<stamp>.mp4:
#   <room>-<tag>_<stamp>.mp4   original video (stream copy) + the LISTENING audio (timeline preserved) — or,
#                              if the listening method changes the timeline (cut*), the video is re-cut to it
#   <room>-<tag>_<stamp>.ogg   the same audio as 16 kHz mono Opus 32k (what the office's transcriber takes)
#   <room>-<tag>_<stamp>.asr16.wav   the ASR version of the audio (16 kHz; its timeline may be compressed)
#   <room>-<tag>_<stamp>.map.json    output-time -> original-time map of the ASR version (cut methods)
#   <room>-<tag>_<stamp>.transcript.json  the local transcription (asr_run.py shape, word timestamps)
#   <room>-<tag>_<stamp>.stats.json  burst/gap statistics of the original
#
# METHODS (see README): plc | noise12f | plc_f | inpaint | floor   (timeline preserved)
#                       cut | plc_cut | cut_st60 | cut_st75         (gaps removed; timeline compressed)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
IN=$1; OUT=$2; shift 2
LISTEN=plc_f; ASR=cut; MODEL=turbo; BEAM=5; TEMPS=0; TAG=restored2; VIDEO=1; THREADS=6
while [ $# -gt 0 ]; do
  case $1 in
    --listen) LISTEN=$2; shift 2 ;;
    --asr) ASR=$2; shift 2 ;;
    --model) MODEL=$2; shift 2 ;;
    --beam) BEAM=$2; shift 2 ;;
    --temps) TEMPS=$2; shift 2 ;;
    --tag) TAG=$2; shift 2 ;;
    --threads) THREADS=$2; shift 2 ;;
    --no-video) VIDEO=0; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
[ -n "${VENV:-}" ] && source "$VENV/bin/activate"
POST="highpass=f=80,acompressor=threshold=-28dB:ratio=3:attack=5:release=150:makeup=6,loudnorm=I=-18:TP=-2:LRA=11"
LN="loudnorm=I=-18:TP=-2:LRA=11"
base=$(basename "$IN" .mp4)                 # fpg103_2026-10-26-13-10-48
room=${base%_*}; stamp=${base##*_}
name="${room}-${TAG}_${stamp}"
mkdir -p "$OUT/tmp"
W="$OUT/tmp/$base"
echo "== $base -> $name  (listen: $LISTEN, asr: $ASR, model: $MODEL)"
[ -f "$W.44k.wav" ] || ffmpeg -nostdin -v error -y -i "$IN" -vn -ac 1 -ar 44100 -c:a pcm_s16le "$W.44k.wav"

# ---- one method -> 44.1 kHz float wav (+ optional cut map) --------------------------------------------
# produce METHOD SRC DST [MAP]
produce() {
  local M=$1 SRC=$2 DST=$3 MAP=${4:-}
  local mapopt=""; [ -n "$MAP" ] && mapopt="--map $MAP"
  case $M in
    plc)      python "$HERE/plc_opus.py" "$SRC" "$DST" --max-gap 0.12 --trim 0.005 >/dev/null ;;
    plc_f)    python "$HERE/plc_opus.py" "$SRC" "$DST.p.wav" --max-gap 0.12 --trim 0.005 >/dev/null
              python "$HERE/noisefill.py" "$DST.p.wav" "$DST" --max-gap 0 --floor -55 >/dev/null; rm -f "$DST.p.wav" ;;
    noise12f) python "$HERE/noisefill.py" "$SRC" "$DST" --level -12 --floor -55 >/dev/null ;;
    floor)    python "$HERE/noisefill.py" "$SRC" "$DST" --max-gap 0 --floor -55 >/dev/null ;;
    inpaint)  python "$HERE/restore.py" "$SRC" "$DST" --mode inpaint >/dev/null ;;
    cut)      python "$HERE/restore.py" "$SRC" "$DST" --mode cut $mapopt --stats "$W.stats.json" >/dev/null ;;
    plc_cut)  python "$HERE/plc_opus.py" "$SRC" "$DST.p.wav" --max-gap 0.06 --trim 0.005 >/dev/null
              python "$HERE/restore.py" "$DST.p.wav" "$DST" --mode cut --no-edgefix $mapopt --stats "$W.stats.json" >/dev/null; rm -f "$DST.p.wav" ;;
    cut_st60|cut_st75) python "$HERE/restore.py" "$SRC" "$DST" --mode cut $mapopt --stats "$W.stats.json" >/dev/null ;;
    *) echo "unknown method $M"; exit 1 ;;
  esac
}
postfilter() {   # METHOD -> ffmpeg -af chain
  case $1 in
    cut_st60) echo "atempo=0.6,$POST" ;;
    cut_st75) echo "atempo=0.75,$POST" ;;
    plc_f|floor|noise12f) echo "$LN" ;;
    *) echo "$POST" ;;
  esac
}
tempo() { case $1 in cut_st60) echo 0.6 ;; cut_st75) echo 0.75 ;; *) echo 1 ;; esac; }
iscut() { case $1 in cut|plc_cut|cut_st60|cut_st75) return 0 ;; *) return 1 ;; esac; }

# ---- listening version -------------------------------------------------------------------------------
LMAP=""; iscut $LISTEN && LMAP="$OUT/$name.listen.map.json"
produce $LISTEN "$W.44k.wav" "$W.listen.raw.wav" "$LMAP"
ffmpeg -nostdin -v error -y -i "$W.listen.raw.wav" -af "$(postfilter $LISTEN)" -ac 1 -ar 44100 -c:a pcm_s16le "$W.listen.wav"
ffmpeg -nostdin -v error -y -i "$W.listen.wav" -vn -ac 1 -ar 16000 -c:a libopus -b:a 32k -f ogg "$OUT/$name.ogg"
if [ $VIDEO = 1 ]; then
  ffmpeg -nostdin -v error -y -i "$W.listen.wav" -c:a aac -b:a 96k "$W.listen.m4a"
  if iscut $LISTEN; then
    python "$HERE/cutvideo.py" "$IN" "$LMAP" "$W.listen.m4a" "$OUT/$name.mp4"
  else
    # no -shortest: Jibri's video track ends a few seconds before its audio, and -shortest cut the restored audio's tail (fpg103 lost 4.5 s, 2026-10-27)
    ffmpeg -nostdin -v error -y -i "$IN" -i "$W.listen.m4a" -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy -movflags +faststart "$OUT/$name.mp4"
  fi
fi

# ---- ASR version + transcription --------------------------------------------------------------------
AMAP=""; iscut $ASR && AMAP="$OUT/$name.map.json"
if [ "$ASR" = "$LISTEN" ]; then
  cp "$W.listen.wav" "$W.asr.wav"; [ -n "$LMAP" ] && cp "$LMAP" "$AMAP"
else
  produce $ASR "$W.44k.wav" "$W.asr.raw.wav" "$AMAP"
  ffmpeg -nostdin -v error -y -i "$W.asr.raw.wav" -af "$(postfilter $ASR)" -ac 1 -ar 44100 -c:a pcm_s16le "$W.asr.wav"
fi
ffmpeg -nostdin -v error -y -i "$W.asr.wav" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/$name.asr16.wav"
python "$HERE/asr_run.py" "$OUT/$name.transcript.json" "$OUT/$name.asr16.wav" --model $MODEL --beam $BEAM --temp "$TEMPS" --threads $THREADS 2>&1 | grep -E "^###|loaded|ALLDONE"
echo "tempo=$(tempo $ASR) map=${AMAP:-none}" > "$OUT/$name.asr.info"
[ -f "$W.stats.json" ] && cp "$W.stats.json" "$OUT/$name.stats.json"
ls -la "$OUT/$name".*
