#!/bin/bash
# LLM reconstruction layer over the ASR inputs of restore_recording.sh, then the Plane comment (HTML + text) with
# timestamps on the ORIGINAL recording clock.
#
# usage: restore_transcript.sh OUT_DIR NAME "method text" "benchmark text" [--window 20] [--keyfile ~/.deepseek_key]
#   NAME = <room>-restored2_<stamp> (the file name without extension, as written by restore_recording.sh)
# The LLM (DeepSeek chat via its API; the key is read from --keyfile and never printed) may only choose among the
# hypotheses and fix split/merged words — measured on the benchmark: 0.5–1.4 % of its words occur in no hypothesis.
# Without an API key, pass --rover to use plain word voting instead (lower recall, no LLM).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1; NAME=$2; METHOD=$3; BENCH=$4; shift 4
WINDOW=20; KEYFILE=${DEEPSEEK_KEYFILE:-$HOME/.deepseek_key}; ROVER=0
while [ $# -gt 0 ]; do
  case $1 in
    --window) WINDOW=$2; shift 2 ;;
    --keyfile) KEYFILE=$2; shift 2 ;;
    --rover) ROVER=1; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
[ -n "${VENV:-}" ] && source "$VENV/bin/activate"
cd "$OUT"
SYS=""
for S in raw post n12f; do [ -f "asr/$S.wav" ] && SYS="$SYS $S=transcript.json:asr/$S.wav"; done
if [ $ROVER = 1 ]; then
  python "$HERE/rover.py" final.json --group rec --primary raw --sys $SYS 2>/dev/null
  KEY=rover/rec.wav
else
  python "$HERE/llm_layer.py" final.json --group rec --window $WINDOW --keyfile "$KEYFILE" --sys $SYS 2>&1 | grep -v "^system" || true
  KEY=llm/rec.wav
fi
python "$HERE/mk_comment2.py" final.json $KEY comment.html comment.txt --name "$NAME.ogg" --method "$METHOD" --bench "$BENCH" --map trim.map.json --min-lp -9
echo "comment: $OUT/comment.html  (post with pl_comment.py from inside project-pln-fireplace)"
