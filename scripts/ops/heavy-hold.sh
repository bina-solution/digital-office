#!/usr/bin/env bash
# heavy-hold.sh — hold the office's ONE heavy-work slot for a job whose caller cannot wrap it (DGO-1797, package 6).
#
#   scripts/ops/heavy-hold.sh start <label> [wait_s]   # wait for the slot, then hold it in a detached holder; 0 = held
#                                                      #   (or covered: BBOX_HEAVY_HELD), 1 = still busy after wait_s,
#                                                      #   2 = the slot cannot be opened, 3 = no flock/setsid here
#   scripts/ops/heavy-hold.sh stop                     # give back the slot THIS caller's holder holds («released N»)
#   scripts/ops/heavy-hold.sh status                   # «free», or the holder line of what holds it now
#
# WHY. The slot is heavy_admit's flock on data/.locks/heavy (scripts/lib.sh): one heavy job at a time on the machine,
# held by the process that admitted and released by the kernel when it exits. A CI runner's job cannot be wrapped
# that way: its JOB_STARTED hook is a process of its own that exits before the job begins, and the job's end is a
# second hook. So the slot is held by a HOLDER: `start` waits for the lock (saying every HEAVY_HOLD_SAY_S who holds
# it), then leaves a process of its own session that holds it — named in `ps` as «heavy-hold: <label>», which is
# also how `stop` knows the pid it was handed is its holder and not a stranger's process; `stop` ends it, and the
# kernel releases the lock. Nothing a holder outlives keeps the slot:
#   - HEAVY_HOLD_WHILE=<pid>: the holder ends within HEAVY_HOLD_POLL_S of that process (a runner's job worker), so a
#     job whose end hook never ran, or whose listener crashed, does not hold it;
#   - `start` first ends a holder this caller left before (a runner takes one job at a time: a new job means the last
#     one is over);
#   - a holder ends by itself after HEAVY_HOLD_MAX_S (6 h by default; a caller whose jobs are shorter sets less —
#     ci-runner 2 h, under bbox's own 3-h wait);
#   - a `start` killed while it waits leaves nothing: the holder, once it has the lock, gives it back at once when
#     the `start` that asked for it is gone;
#   - it lives where its caller lives: a container's stop ends it.
# Its stdin, stdout and stderr are /dev/null: a runner reads its hook's output to the end, and a holder that kept the
# pipe would hold the job at its first step for ever.
# The lock file and the holder line are created world-writable when missing: a root container that made them 0644
# would leave the office's own user a slot it cannot open — and heavy_admit then admits WITHOUT the lock, silently.
# Generic: it names no app (G31). Linux only (flock, setsid, /proc).
#
# Paths: HEAVY_LOCKS (default <checkout>/data/.locks) — the office's directory, mounted where the caller runs;
# HEAVY_HOLD_PIDFILE (default $HEAVY_LOCKS/heavy.hold.<hostname>.pid) — where this caller keeps its holder's pid. Two
# callers on one host must each name their own (ci-runner keeps it on its own volume): `stop` ends the holder that
# file names.
set -uo pipefail

HERE="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCKS="${HEAVY_LOCKS:-${HERE}/../../data/.locks}"
LOCK="${LOCKS}/heavy"
NOTE="${LOCKS}/heavy.holder"
PIDFILE="${HEAVY_HOLD_PIDFILE:-${LOCKS}/heavy.hold.$(hostname 2>/dev/null || echo host).pid}"
MAX_S="${HEAVY_HOLD_MAX_S:-21600}"
POLL_S="${HEAVY_HOLD_POLL_S:-5}"
SAY_S="${HEAVY_HOLD_SAY_S:-60}"
TAG="heavy-hold:"

say() { printf 'heavy-hold: %s\n' "$*" >&2; }
int() { case "${1:-}" in ''|*[!0-9]*) echo "${2}" ;; *) echo $((10#$1)) ;; esac; }

# NO PIPELINE'S STATUS IS READ HERE (`set -o pipefail`, above): a reader that stops early — `grep -q` at its first
# match, `head -1` at its first line — can leave the writer before it to die of SIGPIPE, and pipefail then fails a
# pipeline whose answer was yes. That was `mine()`: `tr … | grep -q` said «not a holder» about a living holder, so
# `stop` answered «none» and left the slot held — 3 of 3 runs of test_heavy_hold.sh on Ubuntu 26.04 (the Dell's
# runner, batch 39's red, DGO-1819), never on the older userland. Text is read into a variable, then matched.

# what holds the slot now — the flock is the truth, the holder line only names it (heavy_slot_status's rule)
status() {
  local line
  [ -e "${LOCK}" ] || { echo free; return 0; }
  if flock -n "${LOCK}" true 2>/dev/null; then echo free; return 0; fi
  line="$(head -c 400 "${NOTE}" 2>/dev/null)"
  line="${line%%$'\n'*}"
  if [ -n "${line}" ]; then printf '%s\n' "${line}"; else echo "held (holder unknown)"; fi
}

# the pid in this caller's pid file, when that process is alive AND is a holder (its argv says so); else nothing
mine() {
  local pid argv
  pid="$(head -c 32 "${PIDFILE}" 2>/dev/null | tr -cd '0-9')"
  [ -n "${pid}" ] && [ -r "/proc/${pid}/cmdline" ] || return 1
  argv="$( { tr '\0' ' ' < "/proc/${pid}/cmdline"; } 2>/dev/null)" || return 1
  case "${argv}" in "${TAG} "*) echo "${pid}" ;; *) return 1 ;; esac
}

end_pid() {   # its own session and group (setsid): the group, then the pid, TERM then KILL
  local p="$1" i
  kill -TERM -- "-${p}" 2>/dev/null || kill -TERM "${p}" 2>/dev/null
  for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "${p}" 2>/dev/null || return 0; sleep 0.2; done
  kill -KILL -- "-${p}" 2>/dev/null || kill -KILL "${p}" 2>/dev/null || true
}

# __hold <wait_s> <ready file> <label> <starter pid>: runs in its own session. Waits for the lock and says how it ended
# in the ready file — its pid once it holds it, «fail» when the wait ran out — then becomes the holder: a loop under
# the holder's name that ends with HEAVY_HOLD_WHILE's process or after HEAVY_HOLD_MAX_S. A starter that is gone by
# the time the lock comes (it was killed while it waited) gets nothing held for it. The descriptor that holds the
# lock is inherited through exec (bash sets no close-on-exec).
hold() {
  local fd
  { exec {fd}>>"${LOCK}"; } 2>/dev/null || { exec {fd}<"${LOCK}"; } 2>/dev/null || { echo fail > "$2"; exit 3; }
  flock -w "$1" "${fd}" || { echo fail > "$2"; exit 4; }
  kill -0 "${4:-0}" 2>/dev/null || exit 0
  printf '%s\n' "$$" > "$2"
  exec -a "${TAG} $3" bash -c '
    w="$1"; poll="$2"; left="$3"
    while [ "${left}" -gt 0 ]; do
      if [ -n "${w}" ] && ! kill -0 "${w}" 2>/dev/null; then exit 0; fi
      sleep "${poll}"; left=$(( left - poll ))
    done' _ "$(int "${HEAVY_HOLD_WHILE:-}" "")" "$(int "${POLL_S}" 5)" "$(int "${MAX_S}" 21600)"
}

start() {
  local label="${1:-heavy job}" wait_s fw ready pid waited=0 said=0 old
  wait_s="$(int "${2:-}" 10800)"
  # the holder waits at least 2 s: a status probe (here, heavy_slot_status, `flock -n … true`) takes a free lock for
  # an instant, and a zero wait lost the slot to it — measured: «stayed busy for 0 s — held by: free»
  fw=$(( wait_s < 2 ? 2 : wait_s ))
  # one line, whatever the caller passed: control characters out (a newline would split the holder line), the
  # rest kept — «·» and Hebrew are a person's words on machine's card
  label="$(printf '%s' "${label}" | tr -d '\000-\037\177' | head -c 200)"
  if [ "${BBOX_HEAVY_HELD:-}" = 1 ]; then say "this caller already holds the slot — nothing more to take"; return 0; fi
  command -v flock >/dev/null 2>&1 && command -v setsid >/dev/null 2>&1 \
    || { say "no flock or setsid here — the slot cannot be held, and '${label}' runs unguarded"; return 3; }
  mkdir -p "${LOCKS}" 2>/dev/null || true
  [ -e "${LOCK}" ] || ( umask 000; : >> "${LOCK}" ) 2>/dev/null || true
  [ -r "${LOCK}" ] || { say "cannot open the slot ${LOCK}"; return 2; }
  if old="$(mine)"; then
    say "the holder of this caller's last job was still alive (pid ${old}) — that job is over: released"
    end_pid "${old}"
  fi
  ready="$(mktemp "${TMPDIR:-/tmp}/heavy-hold.XXXXXX")" || { say "no temporary file"; return 2; }
  # $! is not always the holder (setsid forks when its caller leads a process group): the ready file is the answer
  setsid bash "${BASH_SOURCE[0]}" __hold "${fw}" "${ready}" "${label}" "$$" < /dev/null > /dev/null 2>&1 &
  pid=$!
  while :; do
    case "$(head -c 32 "${ready}" 2>/dev/null)" in
      fail*)  rm -f "${ready}"; say "the heavy-job slot stayed busy for ${fw} s — held by: $(status)"; return 1 ;;
      *[0-9]*) break ;;
    esac
    if [ "${waited}" -gt $(( fw + 5 )) ] && ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${ready}"; say "the holder ended without a word — the slot is not held"; return 1
    fi
    if [ $(( waited - said )) -ge "$(int "${SAY_S}" 60)" ]; then
      say "waiting for the heavy-job slot (one at a time on this machine) — held by: $(status)"
      said="${waited}"
    fi
    sleep 1; waited=$(( waited + 1 ))
  done
  pid="$(head -c 32 "${ready}" | tr -cd '0-9')"; rm -f "${ready}"
  printf '%s\n' "${pid}" > "${PIDFILE}" 2>/dev/null || say "could not write ${PIDFILE} — stop cannot find this holder"
  if [ -e "${NOTE}" ]; then
    printf '%s | pid %s on %s | since %s\n' "${label}" "${pid}" "$(hostname 2>/dev/null)" "$(date -u '+%F %T UTC')" > "${NOTE}" 2>/dev/null
  else
    ( umask 000; printf '%s | pid %s on %s | since %s\n' "${label}" "${pid}" "$(hostname 2>/dev/null)" "$(date -u '+%F %T UTC')" > "${NOTE}" ) 2>/dev/null
  fi || true
  say "holding the heavy-job slot for '${label}' (pid ${pid}, after ${waited} s)"
  return 0
}

stop() {
  local pid since
  if pid="$(mine)"; then
    since="$(ps -o etimes= -p "${pid}" 2>/dev/null | tr -d ' ')"
    end_pid "${pid}"
    rm -f "${PIDFILE}" 2>/dev/null
    say "released the heavy-job slot (held ${since:-?} s)"
    echo "released ${since:-?}"
    return 0
  fi
  rm -f "${PIDFILE}" 2>/dev/null
  echo "none"
  return 0
}

case "${1:-}" in
  start)  shift; start "$@" ;;
  stop)   stop ;;
  status) status ;;
  __hold) shift; hold "$@" ;;
  *) echo "usage: heavy-hold.sh start <label> [wait_s] | stop | status" >&2; exit 2 ;;
esac
