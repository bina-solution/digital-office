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

[ "${fails}" -eq 0 ] && { echo; echo "0 failing"; exit 0; }
echo; echo "${fails} failing"; exit 1
