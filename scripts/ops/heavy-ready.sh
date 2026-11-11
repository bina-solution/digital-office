# shellcheck shell=bash
# heavy-ready.sh — may a heavy job start on this machine NOW? The one readiness rule (DGO-1797, package 6).
#
#   . scripts/ops/heavy-ready.sh
#   heavy_ready_why   <mem_mb> <cpus>  # prints what holds the job («» when nothing does); always returns 0
#   heavy_ready       <mem_mb> <cpus>  # 0 = start, 1 = wait
#   heavy_ready_state <mem_mb> <cpus>  # one line of every fact, for a waiting line or a status screen
#
# The owner, DGO-1797: on a machine somebody sits at, heavy work — a CI job, the emulator, a big model, a
# build — runs one at a time, and waits for the desk unless it is small. Three gates already measured parts
# of this, each its own way: heavy_admit (scripts/lib.sh: the slot and a memory floor), ops/prejob_waitfree.sh
# (memory, heat, a fresh boot) and the emulator's own heat watch. This file is the rule once, generic (it
# names no app — G31), sourced by each of them. The slot itself (one at a time) stays heavy_admit's flock.
#
# A job of `mem_mb` MB and `cpus` CPUs starts when ALL of these hold (each read from a file every caller sees):
#   1. MemAvailable >= mem_mb + HEAVY_RESERVE_MB              — the job's own ceiling plus the desk's reserve
#      (HEAVY_RESERVE_MB defaults to ADMISSION_MIN_AVAIL_MIB; a caller whose number is already a floor — a
#      recreate that must be able to bring a full box back up — passes HEAVY_RESERVE_MB=0)
#   2. the CPU package is under HEAVY_MAX_START_C              — no reading = no hold (a VM, a Mac)
#   3. up at least HEAVY_MIN_UPTIME_S                          — the office settles after a boot first (a caller
#      that IS the office's bring-up passes HEAVY_MIN_UPTIME_S=0)
#   4. nobody is at the desk — OR the job is small: mem_mb <= DESK_SMALL_MB and cpus <= 1.
#      «At the desk» is data/power/desk.json, written by machine (desk.py); a missing, unreadable, older than
#      DESK_STALE_S or future-stamped file, or `in_use: null`, is UNKNOWN, and unknown is NOT in use: a dead
#      sampler never holds every job. heavy_ready_state says «desk unknown» and why, so it is never silent.
# LOAD IS NOT A HOLD. admission-thresholds.sh measured why (load 15–35 is the normal state of a busy office,
# and Linux counts I/O waits in it): «Report it; never gate». It is in the state line, never in the rule.
# The numbers live in scripts/ops/admission-thresholds.sh; every read can be pointed elsewhere (HEAVY_PROC,
# HEAVY_SYS, HEAVY_DESK, HEAVY_NOW) — the test does.

_HR_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# the numbers, written once (ADMISSION_MIN_AVAIL_MIB, HEAVY_MAX_START_C, HEAVY_MIN_UPTIME_S, DESK_SMALL_MB,
# DESK_STALE_S); each can be set before this file is sourced
# shellcheck source=/dev/null
. "${_HR_DIR}/admission-thresholds.sh"

# a whole number from anything («0089» → 89, «6G» / «» / «-1» → empty): no arithmetic error, no octal
_hr_int() { local v="${1:-}"; case "${v}" in ''|*[!0-9]*) echo "" ;; *) echo $((10#${v})) ;; esac; }
_hr_proc() { echo "${HEAVY_PROC:-/proc}"; }
_hr_avail_mb() { awk '/^MemAvailable:/ {printf "%d", $2 / 1024}' "$(_hr_proc)/meminfo" 2>/dev/null; }
_hr_up_s() { awk '{printf "%d", $1}' "$(_hr_proc)/uptime" 2>/dev/null; }
_hr_load() { awk '{print $1}' "$(_hr_proc)/loadavg" 2>/dev/null; }
_hr_threads() {
  local n; n="$(grep -c '^processor' "$(_hr_proc)/cpuinfo" 2>/dev/null)"
  [ -n "${n}" ] && [ "${n}" != 0 ] || n="$(getconf _NPROCESSORS_ONLN 2>/dev/null)"
  echo "${n:-?}"
}
_hr_pkg_c() {
  # a sysfs read can fail (EIO, ENODATA): no answer is «no reading», never a shell error that holds the job
  local z t
  for z in "${HEAVY_SYS:-/sys}"/class/thermal/thermal_zone*; do
    if [ "$(cat "$z/type" 2>/dev/null)" = x86_pkg_temp ]; then
      t="$(_hr_int "$(cat "$z/temp" 2>/dev/null)")" && [ -n "$t" ] && { echo $((t / 1000)); return; }
    fi
  done
}
# «yes», «no» or «unknown (why)» — desk.json is one line written by desk.write_desk (json.dumps); a regular
# file only (never a FIFO a read would hang on)
_hr_desk() {
  local f="${HEAVY_DESK:-${REPO_ROOT:-.}/data/power/desk.json}" line at now
  [ -f "$f" ] || { echo "unknown (no desk reading)"; return; }
  line="$(head -c 4096 "$f" 2>/dev/null)"
  [ -n "${line}" ] || { echo "unknown (no desk reading)"; return; }
  at="$(_hr_int "$(printf '%s' "${line}" | grep -o '"at": *[0-9]*' | head -1 | grep -o '[0-9]*$')")"
  now="${HEAVY_NOW:-$(date +%s)}"
  [ -n "${at}" ] || { echo "unknown (the desk reading has no time)"; return; }
  [ $(( now - at )) -le "${DESK_STALE_S}" ] || { echo "unknown (the desk reading is $(( now - at )) s old)"; return; }
  [ $(( at - now )) -le "${DESK_STALE_S}" ] || { echo "unknown (the desk reading is stamped in the future)"; return; }
  case "$(printf '%s' "${line}" | grep -o '"in_use": *[a-z]*' | head -1 | grep -o '[a-z]*$')" in
    true)  echo "yes" ;;
    false) echo "no" ;;
    *)     echo "unknown (the desk did not say)" ;;
  esac
}
_hr_small() {   # <mem_mb> <cpus>: under the desk's ceiling in memory AND at most one CPU (cpus may be 0.5, 1.0)
  local mem; mem="$(_hr_int "$1")"
  [ -n "${mem}" ] && [ "${mem}" -le "${DESK_SMALL_MB}" ] || return 1
  printf '%s' "${2:-}" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || return 1
  awk -v c="$2" 'BEGIN {exit !(c + 0 <= 1)}'
}

heavy_ready_why() {
  local mem cpus="${2:-1}" reserve avail up c desk
  mem="$(_hr_int "${1:-0}")"; mem="${mem:-0}"
  reserve="$(_hr_int "${HEAVY_RESERVE_MB:-${ADMISSION_MIN_AVAIL_MIB}}")"; reserve="${reserve:-0}"
  avail="$(_hr_avail_mb)"
  if [ -n "${avail}" ] && [ "${avail}" -lt $(( mem + reserve )) ]; then
    echo "memory: ${avail} MB available, ${mem} MB for the job + ${reserve} MB for the desk"; return 0
  fi
  c="$(_hr_pkg_c)"
  if [ -n "${c}" ] && [ "${c}" -ge "${HEAVY_MAX_START_C}" ]; then
    echo "heat: the CPU is at ${c}°C (starts under ${HEAVY_MAX_START_C}°C)"; return 0
  fi
  up="$(_hr_up_s)"
  if [ -n "${up}" ] && [ "${up}" -lt "${HEAVY_MIN_UPTIME_S}" ]; then
    echo "a fresh boot: up ${up} s (the office settles for ${HEAVY_MIN_UPTIME_S} s)"; return 0
  fi
  desk="$(_hr_desk)"
  if [ "${desk}" = yes ] && ! _hr_small "${mem}" "${cpus}"; then
    echo "the desk: somebody is at this computer, and only a small job runs beside them (at most ${DESK_SMALL_MB} MB and 1 CPU; this one was given as ${mem} MB, ${cpus} CPU)"
  fi
  return 0
}

heavy_ready() { [ -z "$(heavy_ready_why "$@")" ]; }

heavy_ready_state() {
  local c; c="$(_hr_pkg_c)"
  echo "$(_hr_avail_mb || true) MB available · CPU ${c:-no reading}${c:+°C} · up $(_hr_up_s || true) s · load $(_hr_load || true) on $(_hr_threads) threads (reported, never a hold) · desk $(_hr_desk)"
}
