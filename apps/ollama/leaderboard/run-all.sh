#!/bin/sh
# run-all.sh <dir> <model>… — the leaderboard's whole pass on THIS machine (DGO-1351): every model's answers, one
# model at a time, each model asked twice (the second pass asks only what failed — a server recreated mid-run leaves
# failures, never zeros); then, once the machine is quiet, every model's speed; then the scores. It runs the harness
# that sits beside it. Ollama is found by its container (OLLAMA_CONTAINER, default ollama-engine-portable — its address
# changes when it is recreated), and the model the office keeps loaded is loaded again at the end, pinned as before.
# Exit status: the number of steps that failed (0 = every step ran).
set -u
DIR=$1; shift
H="$(cd "$(dirname "$0")" && pwd)/harness.py"
C=${OLLAMA_CONTAINER:-ollama-engine-portable}
FAILED=0
cd "$DIR" || exit 1
[ -f "$H" ] || { echo "no harness at $H"; exit 1; }
url() {
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$C" 2>/dev/null | awk '{print $1}')
  [ -n "$ip" ] || { echo "no address for container $C" >&2; return 1; }
  echo "http://$ip:11434"
}
step() {  # step <what> <command…> — one step, its failure counted and said, never silent
  what=$1; shift
  "$@" || { FAILED=$((FAILED + 1)); echo "[$(date -u +%FT%TZ)] FAILED: $what"; }
}
KEEP=$(docker exec "$C" ollama ps 2>/dev/null | awk 'NR==2{print $1}')
echo "[$(date -u +%FT%TZ)] start; the office keeps «${KEEP:-nothing}» loaded; harness $H"
for m in "$@"; do
  for pass in 1 2; do
    U=$(url) || { FAILED=$((FAILED + 1)); continue; }
    echo "[$(date -u +%FT%TZ)] answers: $m (pass $pass)"
    step "answers $m pass $pass" python3 -I "$H" run . "$m" --url "$U"
  done
  python3 -I "$H" score . > score.txt 2>&1
done
# the speed wants a quiet machine: wait (up to 6 h) for the 1-minute load to fall under 1.5
for i in $(seq 1 360); do
  L=$(cut -d' ' -f1 /proc/loadavg)
  awk -v l="$L" 'BEGIN{exit !(l < 1.5)}' && break
  [ "$i" = 1 ] && echo "[$(date -u +%FT%TZ)] waiting for a quiet machine (load $L)"
  sleep 60
done
for m in "$@"; do
  U=$(url) || { FAILED=$((FAILED + 1)); continue; }
  echo "[$(date -u +%FT%TZ)] speed: $m (load $(cut -d' ' -f1 /proc/loadavg))"
  step "speed $m" python3 -I "$H" speed . "$m" --url "$U"
done
step "score" sh -c "python3 -I '$H' score . > score.txt 2>&1"
if [ -n "${KEEP:-}" ] && U=$(url); then
  step "reload $KEEP" curl -sf "$U/api/generate" -d "{\"model\":\"$KEEP\",\"keep_alive\":-1}" -o /dev/null
fi
echo "[$(date -u +%FT%TZ)] done — $FAILED step(s) failed"
exit "$FAILED"
