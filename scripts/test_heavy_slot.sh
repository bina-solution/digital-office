#!/usr/bin/env bash
# test_heavy_slot.sh — the engine-wide heavy-job slot (scripts/lib.sh heavy_admit) is given back when a
# job says so, and only then.
#
#     bash scripts/test_heavy_slot.sh
#
# `bbox run` gives the slot back before it waits for the convergence, whose pushes take it from another
# process tree (DGO-1024). Closing the run's own descriptor was not enough: a flock belongs to the OPEN
# FILE DESCRIPTION, every child started under the slot holds a duplicate of it, and the cloud proof of
# 2be2e327 measured the slot still held ~2 minutes after the run's POST opened. What is held here, each
# against a lock in a temp dir (the repo's own data/.locks is never touched):
#   * a release frees the slot at once, though a child started under it still runs;
#   * a child's own detach does NOT free the slot of the job that is still running;
#   * a release keeps the job's stderr (2be2e327: it once went to /dev/null with the descriptor).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "${HERE}/.." && pwd)"
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
command -v flock >/dev/null 2>&1 || { echo "SKIP  no flock(1) on this machine — heavy_admit is a no-op here"; exit 0; }
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT
# heavy_admit also asks the readiness rule (scripts/ops/heavy-ready.sh) and may SAY something on stderr: every case
# runs on a fixture machine — plenty of memory, up for hours, no heat sensor, no desk reading until a case writes
# one — and nothing in this shell's environment may move a verdict
unset BBOX_HEAVY_CPUS HEAVY_DESK HEAVY_NOW HEAVY_RESERVE_MB HEAVY_MIN_UPTIME_S CI_MIN_UPTIME_S HEAVY_MAX_START_C \
      CI_MAX_START_C DESK_STALE_S DESK_SMALL_MB ADMISSION_MIN_AVAIL_MIB BBOX_HEAVY_HELD BBOX_HEAVY_FD BBOX_HEAVY_PID BBOX_HEAVY
mkdir -p "${TMP}/data/power" "${TMP}/proc"
printf 'MemAvailable:   %d kB\n' $(( 12000 * 1024 )) > "${TMP}/proc/meminfo"
printf '5000.00 1.00\n' > "${TMP}/proc/uptime"; printf '1.00 1.00 1.00 1/1 1\n' > "${TMP}/proc/loadavg"
export HEAVY_PROC="${TMP}/proc" HEAVY_SYS="${TMP}/nosys"

# Another process tree asks for the slot and answers at once: "admitted" or "busy" (BBOX_HEAVY_WAIT=0 —
# a busy slot is `die`, so the ask runs in a subshell of its own).
other_job() {
  env -u BBOX_HEAVY_HELD -u BBOX_HEAVY_FD BBOX_HEAVY_WAIT=0 bash -c "
    . '${ROOT}/scripts/lib.sh' >/dev/null 2>&1; REPO_ROOT='${TMP}'
    ( heavy_admit 'the other job' 0 ) >/dev/null 2>&1 && echo admitted || echo busy" 2>/dev/null
}

answer="$(
  . "${ROOT}/scripts/lib.sh" >/dev/null 2>&1; REPO_ROOT="${TMP}"
  heavy_admit "a run" 0
  sleep 30 >/dev/null 2>&1 & child=$!       # started under the slot: it holds a duplicate of the lock
  heavy_release
  other_job
  kill "${child}" 2>/dev/null
)"
[ "${answer}" = admitted ] && ok "a release frees the slot though a child started under it still runs" \
  || no "the slot stayed held by a child after the job released it (answered: ${answer:-nothing})"

answer="$(
  . "${ROOT}/scripts/lib.sh" >/dev/null 2>&1; REPO_ROOT="${TMP}"
  heavy_admit "a run" 0
  ( heavy_detach ) >/dev/null 2>&1          # a watchdog child drops its copy, and the job goes on
  other_job
)"
[ "${answer}" = busy ] && ok "a child's detach leaves the running job its slot" \
  || no "a child's detach freed the slot of a job that still runs (answered: ${answer:-nothing})"

# A NESTED job (`bbox baseline` → `bbox run`): its release must not free the parent's slot, and the
# nested job stays covered by it — its next heavy step passes through instead of waiting on its parent.
answer="$(
  . "${ROOT}/scripts/lib.sh" >/dev/null 2>&1; REPO_ROOT="${TMP}"
  heavy_admit "a baseline" 0
  nested="$(bash -c ". '${ROOT}/scripts/lib.sh' >/dev/null 2>&1; REPO_ROOT='${TMP}'; heavy_release
            ( BBOX_HEAVY_WAIT=0 heavy_admit 'its next build' 0 ) >/dev/null 2>&1 && echo covered || echo waited")"
  echo "${nested} $(other_job)"
)"
[ "${answer}" = "covered busy" ] && ok "a nested job's release leaves the parent's slot held, and the nested job covered" \
  || no "a nested release freed the parent's slot or lost the child its pass-through (answered: ${answer:-nothing})"

said="$( (
  . "${ROOT}/scripts/lib.sh" >/dev/null 2>&1; REPO_ROOT="${TMP}"
  heavy_admit "a run" 0
  heavy_release
  echo "still said" >&2
) 2>&1 >/dev/null )"
[ "${said}" = "still said" ] && ok "a release keeps the job's stderr" || no "stderr was lost after the release (got: ${said:-nothing})"

# The readiness rule (scripts/ops/heavy-ready.sh, DGO-1797) is ASKED and SAID — and in this stage the job is still
# admitted at once (warn only). The fixture machine above, now with somebody at the desk.
desk() { printf '{"at": %d, "in_use": %s, "idle_s": 3, "how": "gnome"}\n' "$(date +%s)" "$1" > "${TMP}/data/power/desk.json"; }
asked() { ( . "${ROOT}/scripts/lib.sh" >/dev/null 2>&1; REPO_ROOT="${TMP}"
            BBOX_HEAVY_WAIT=0 heavy_admit "$1" 0 && echo "admitted" >&2; heavy_release ) 2>&1 >/dev/null; }
desk true;  said="$(asked "a build")"
case "${said}" in *"'a build' would wait under the readiness rule"*"the desk:"*admitted*) ok "somebody at the desk: the rule says why a build would wait, and the build is admitted (warn only)" ;;
  *) no "the readiness rule was not asked, not said, or held the job (got: ${said:-nothing})" ;; esac
desk false; said="$(asked "a build")"
case "${said}" in admitted) ok "nobody at the desk: nothing said, admitted" ;; *) no "a free desk drew a word or held the job (got: ${said:-nothing})" ;; esac

# …and each admission is ONE line of data/.locks/heavy.would — the week of evidence stage 3 is decided from
would="${TMP}/data/.locks/heavy.would"
last2="$(tail -n 2 "${would}" 2>/dev/null)"
case "${last2}" in *"	a build	"*"the desk:"*"	a build	-") ok "every admission leaves one line: the job, and what the rule would hold it for («-» when nothing)" ;;
  *) no "heavy.would's last two lines: ${last2:-none}" ;; esac
for _ in $(seq 1 4001); do echo "2026-11-11T00:00:00Z	filler	-"; done >> "${would}"
asked "one more" >/dev/null
n="$(wc -l < "${would}")"
[ "${n}" -le 2001 ] && [ "$(tail -n 1 "${would}" | cut -f2)" = "one more" ] \
  && ok "the record is bounded (past 4000 lines the newest 2000 stay), the newest line kept" \
  || no "heavy.would has ${n} lines; last: $(tail -n 1 "${would}")"
ino="$(ls -i "${would}" | awk '{print $1}')"
for _ in $(seq 1 4001); do echo "2026-11-11T00:00:00Z	filler	-"; done >> "${would}"
said="$( (asked "trimmed") 2>&1 )"
[ "$(ls -i "${would}" | awk '{print $1}')" = "${ino}" ] && ! ls "${would}".tmp.* >/dev/null 2>&1 \
  && ok "a trim rewrites the record in place: the same file (its owner and mode kept), no temporary left" \
  || no "the trim replaced the file or left a temporary"
rm -f "${would}"; mkfifo "${would}"
said="$(timeout 20 bash -c "$(declare -f asked); ROOT='${ROOT}' TMP='${TMP}' HEAVY_PROC='${HEAVY_PROC}' HEAVY_SYS='${HEAVY_SYS}' asked 'by a fifo'" 2>&1)"; rc=$?
rm -f "${would}"
[ "${rc}" -ne 124 ] && ok "a FIFO where the record should be never hangs an admission" || no "an admission hung on a FIFO record"

[ "${fails}" -eq 0 ] && { echo; echo "0 failing"; exit 0; }
echo; echo "${fails} failing"; exit 1
