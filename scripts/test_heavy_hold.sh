#!/usr/bin/env bash
# test_heavy_hold.sh — the heavy-work slot held across a job its caller cannot wrap (scripts/ops/heavy-hold.sh,
# DGO-1797 package 6): taken, named, refused to a second caller, seen by heavy_admit itself, given back by its own
# caller only, and never kept by a holder whose job is gone.
#
#     bash scripts/test_heavy_hold.sh
#
# Every case runs against a lock in a temp dir (the repo's own data/.locks is never touched), and every holder it
# starts is ended at the exit. Linux only: flock, setsid and /proc (a Mac says SKIP, not PASS).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "${HERE}/.." && pwd)"
HH="${ROOT}/scripts/ops/heavy-hold.sh"
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
for t in flock setsid timeout; do
  command -v "${t}" >/dev/null 2>&1 || { echo "SKIP  no ${t} here — the holder is Linux's (flock, setsid, /proc)"; exit 0; }
done
[ -d /proc/self ] || { echo "SKIP  no /proc here"; exit 0; }
TMP="$(mktemp -d)"
RUN="t$$"
# the holders of THIS run, by their name in /proc (no pgrep: a slim image has none)
holders() {
  local p c n=0
  for p in /proc/[0-9]*; do
    c="$( { tr '\0' ' ' < "${p}/cmdline"; } 2>/dev/null)" || continue   # a process may end between glob and read
    case "${c}" in "heavy-hold: ${RUN}-$1"*) n=$((n + 1)) ;; esac
  done
  echo "${n}"
}
cleanup() {
  local p c
  for p in /proc/[0-9]*; do
    c="$( { tr '\0' ' ' < "${p}/cmdline"; } 2>/dev/null)" || continue
    case "${c}" in "heavy-hold: ${RUN}-"*) kill -KILL -- "-${p#/proc/}" "${p#/proc/}" 2>/dev/null ;; esac
  done
  rm -rf "${TMP}"
}
trap cleanup EXIT
unset BBOX_HEAVY_HELD BBOX_HEAVY_FD BBOX_HEAVY_PID BBOX_HEAVY HEAVY_HOLD_WHILE HEAVY_HOLD_MAX_S HEAVY_HOLD_POLL_S
export HEAVY_LOCKS="${TMP}/data/.locks" HEAVY_HOLD_SAY_S=1
mkdir -p "${TMP}/proc"
printf 'MemAvailable:   %d kB\n' $(( 12000 * 1024 )) > "${TMP}/proc/meminfo"
printf '5000.00 1.00\n' > "${TMP}/proc/uptime"; printf '1.00 1.00 1.00 1/1 1\n' > "${TMP}/proc/loadavg"
export HEAVY_PROC="${TMP}/proc" HEAVY_SYS="${TMP}/nosys" HEAVY_DESK="${TMP}/nodesk.json"
A() { HEAVY_HOLD_PIDFILE="${TMP}/a.pid" bash "${HH}" "$@"; }
B() { HEAVY_HOLD_PIDFILE="${TMP}/b.pid" bash "${HH}" "$@"; }
# heavy_admit itself, from another process tree, answering at once: «admitted», or the reason it died
admit() {
  env -u BBOX_HEAVY_HELD -u BBOX_HEAVY_FD BBOX_HEAVY_WAIT=0 bash -c "
    . '${ROOT}/scripts/lib.sh' >/dev/null 2>&1; REPO_ROOT='${TMP}'
    ( heavy_admit 'a bbox job' 0 ) >/dev/null 2>&1 && echo admitted || ( heavy_admit 'a bbox job' 0 ) 2>&1 | tail -1" 2>/dev/null
}

# 1. a free slot is taken at once, and the lock and the holder line are made world-writable
t0=$SECONDS
A start "${RUN}-A ci gates-hosted" 30 2>"${TMP}/a.err"; rc=$?
[ "${rc}" = 0 ] && [ $(( SECONDS - t0 )) -le 4 ] && [ "$(holders A)" = 1 ] \
  && ok "a free slot is taken at once by one holder" || no "start on a free slot: rc ${rc}, $(( SECONDS - t0 )) s, $(holders A) holder(s): $(cat "${TMP}/a.err")"
[ "$(stat -c %a "${HEAVY_LOCKS}/heavy" 2>/dev/null)" = 666 ] && [ "$(stat -c %a "${HEAVY_LOCKS}/heavy.holder" 2>/dev/null)" = 666 ] \
  && ok "a missing lock file and holder line are created world-writable (a root caller never locks the office's user out)" \
  || no "modes: heavy $(stat -c %a "${HEAVY_LOCKS}/heavy" 2>/dev/null), heavy.holder $(stat -c %a "${HEAVY_LOCKS}/heavy.holder" 2>/dev/null)"
case "$(A status)" in "${RUN}-A ci gates-hosted | pid "*) ok "status names the holder" ;; *) no "status: $(A status)" ;; esac

# 2. heavy_admit (every bbox heavy job) sees the slot busy, and says who holds it
case "$(admit)" in *"held by: ${RUN}-A ci gates-hosted"*) ok "heavy_admit finds the slot busy and names the holder" ;;
  *) no "heavy_admit while held: $(admit)" ;; esac

# 3. a second caller waits, says every HEAVY_HOLD_SAY_S who holds it, and is refused when its wait runs out
t0=$SECONDS
B start "${RUN}-B second" 2 2>"${TMP}/b.err"; rc=$?
[ "${rc}" = 1 ] && [ $(( SECONDS - t0 )) -le 6 ] && grep -q "waiting for the heavy-job slot .*held by: ${RUN}-A" "${TMP}/b.err" \
  && grep -q "stayed busy for 2 s — held by: ${RUN}-A" "${TMP}/b.err" && [ "$(holders B)" = 0 ] \
  && ok "a second caller waits, names the holder, and is refused after its wait" \
  || no "second caller: rc ${rc}, $(( SECONDS - t0 )) s, $(holders B) holder(s): $(cat "${TMP}/b.err")"

# 4. only a caller's own holder is ended by its stop
[ "$(B stop)" = none ] && [ "$(holders A)" = 1 ] && ok "another caller's stop leaves the holder alone" \
  || no "B's stop touched A's holder ($(holders A) left)"
sleep 30 & stranger=$!
printf '%s\n' "${stranger}" > "${TMP}/b.pid"
[ "$(B stop)" = none ] && kill -0 "${stranger}" 2>/dev/null && ok "a pid file naming a process that is not a holder ends nothing" \
  || no "stop killed a process that was not a holder"
kill "${stranger}" 2>/dev/null

# 5. its own stop gives the slot back, at once, and a stop with nothing held is harmless
case "$(A stop 2>/dev/null)" in released*) ok "stop gives the slot back and says so" ;; *) no "A's stop did not release" ;; esac
[ "$(A status)" = free ] && [ "$(admit)" = admitted ] && [ "$(holders A)" = 0 ] && ok "after stop the slot is free for heavy_admit" \
  || no "after stop: status $(A status), heavy_admit $(admit), $(holders A) holder(s)"
[ "$(A stop)" = none ] && ok "a second stop is harmless" || no "a second stop said something else"

# 6. a job whose end hook never ran: the next start of the same caller ends the old holder first
A start "${RUN}-A1 first job" 10 2>/dev/null
A start "${RUN}-A2 next job" 10 2>"${TMP}/a2.err"
grep -q "was still alive" "${TMP}/a2.err" && [ "$(holders A1)" = 0 ] && [ "$(holders A2)" = 1 ] \
  && ok "a caller's next start ends the holder its last job left" \
  || no "next start: A1 $(holders A1), A2 $(holders A2): $(cat "${TMP}/a2.err")"
A stop >/dev/null 2>&1

# 7. HEAVY_HOLD_WHILE: the holder ends with its job's process — no end hook needed
sleep 2 & job=$!
HEAVY_HOLD_WHILE="${job}" HEAVY_HOLD_POLL_S=1 A start "${RUN}-W while" 10 2>/dev/null
[ "$(A status)" != free ] && ok "held while its job runs" || no "not held while the job ran"
wait "${job}" 2>/dev/null; sleep 2.5
[ "$(A status)" = free ] && [ "$(holders W)" = 0 ] && ok "the holder ends with its job's process (HEAVY_HOLD_WHILE)" \
  || no "the job ended and the slot is: $(A status), $(holders W) holder(s)"

# 8. HEAVY_HOLD_MAX_S: a holder never outlives its bound
HEAVY_HOLD_MAX_S=2 HEAVY_HOLD_POLL_S=1 A start "${RUN}-M max" 10 2>/dev/null
sleep 3.5
[ "$(A status)" = free ] && [ "$(holders M)" = 0 ] && ok "a holder ends by itself after HEAVY_HOLD_MAX_S" \
  || no "after the bound the slot is: $(A status)"

# 9. a runner reads its hook's output to the end: start returns though its caller reads stdout and stderr to EOF
out="$(timeout -k 2 15 bash -c "HEAVY_HOLD_PIDFILE='${TMP}/p.pid' bash '${HH}' start '${RUN}-P pipe' 5 2>&1; echo returned")"
case "${out}" in *returned) ok "start returns to a caller that reads its output to the end (the holder keeps no pipe)" ;;
  *) no "start held its caller's pipe: ${out}" ;; esac
HEAVY_HOLD_PIDFILE="${TMP}/p.pid" bash "${HH}" stop >/dev/null 2>&1

# 10. a zero wait on a free slot is not lost to a status probe (`flock -n … true` takes a free lock for an instant):
#     measured once as «stayed busy for 0 s — held by: free»
probers=()
for _ in 1 2 3; do ( while :; do flock -n "${HEAVY_LOCKS}/heavy" true; done ) 2>/dev/null & probers+=($!); done
lost=0
for i in 1 2 3 4 5; do
  A start "${RUN}-Z zero ${i}" 0 2>>"${TMP}/z.err" || lost=$((lost + 1))
  A stop >/dev/null 2>&1
done
kill "${probers[@]}" 2>/dev/null; wait "${probers[@]}" 2>/dev/null
[ "${lost}" = 0 ] && ok "a zero wait on a free slot is not lost to other callers' status probes (5 tries, 3 probers)" \
  || no "zero wait under probes: lost ${lost} of 5: $(tail -2 "${TMP}/z.err")"

# 11. the label is one line and keeps a person's words: «·» and Hebrew stay, a newline does not split it
A start "${RUN}-L ci gates · 57ef890 · ריצה"$'\n'"second line" 5 2>/dev/null
case "$(A status)" in "${RUN}-L ci gates · 57ef890 · ריצהsecond line | pid "*) ok "the holder line is one line and keeps «·» and Hebrew" ;;
  *) no "holder line: $(A status)" ;; esac
A stop >/dev/null 2>&1

# 12. a `start` killed while it waits leaves nothing behind: when the lock comes, its holder gives it back at once
A start "${RUN}-K1 held" 30 2>/dev/null
HEAVY_HOLD_PIDFILE="${TMP}/b.pid" bash "${HH}" start "${RUN}-K2 killed while waiting" 30 2>/dev/null & killed=$!
sleep 1.5; kill -KILL "${killed}" 2>/dev/null; wait "${killed}" 2>/dev/null
A stop >/dev/null 2>&1
sleep 2
[ "$(A status)" = free ] && [ "$(holders K2)" = 0 ] && ok "a start killed while it waited holds nothing once the slot frees" \
  || no "after the killed start: status $(A status), $(holders K2) holder(s)"

# 13. a caller already inside a heavy job (BBOX_HEAVY_HELD=1) passes through and starts no holder
BBOX_HEAVY_HELD=1 A start "${RUN}-N nested" 5 2>/dev/null; rc=$?
[ "${rc}" = 0 ] && [ "$(holders N)" = 0 ] && [ "$(A status)" = free ] && ok "a nested caller passes through" \
  || no "nested: rc ${rc}, $(holders N) holder(s)"

# 14. no pipeline's status is read under the holder's `set -o pipefail` (batch 39's red on the Dell): a reader that
#     stops early (`grep -q`, `head -1 | grep`) can leave the writer to die of SIGPIPE, and pipefail fails a «yes».
#     The race is the scheduler's, so the case reads the source: no `| grep` that stops early (-q, --quiet, -m1), and
#     no `| head -1 | …` before `||`. A heuristic over single lines, said as one: a read through `if`, `&&` or `$?`,
#     or a pipe split across lines, is the reader's to see.
pipes="$(grep -nE '\|[[:space:]]*grep[^|]*([[:space:]]-[a-zA-Z]*q|--quiet|[[:space:]]-m[[:space:]]*1)|\|[[:space:]]*head[[:space:]]+-(1|n[[:space:]]*1)[^|]*\|[^|]*\|\|' "${HH}" | grep -v '^[0-9]*:[[:space:]]*#')"
[ -z "${pipes}" ] && ok "heavy-hold.sh reads no early-exit pipeline's status (grep -q, head -1 … ||)" \
  || no "an early-exit pipeline's status is read under pipefail: ${pipes}"

echo "heavy-hold: $([ "${fails}" = 0 ] && echo PASS || echo "${fails} FAILED")"
exit $(( fails > 0 ))
