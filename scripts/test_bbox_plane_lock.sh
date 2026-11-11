#!/usr/bin/env bash
# test_bbox_plane_lock.sh — on a Mac, Plane's work-item verbs go into the guest one at a time (DGO-1148, bbox's macOS
# hand-off).
#
#     bash scripts/test_bbox_plane_lock.sh
#
# The hand-off is faked: a copy of bbox in a scratch tree whose packaging/macos/engine.sh records when each call
# starts and ends (scripts/ is the real one, linked). Checks:
#   * two `bbox project-pln tasks …` at once run one after the other, never together;
#   * another verb — and another project-pln verb — is never held behind a work-item call;
#   * a call that cannot get its turn in time exits 75, says so, and sends nothing;
#   * a caller that gives up while it waits takes its place in the queue with it: nothing runs later for nobody;
#   * the call's own exit status comes back through the lock.
# macOS only: the lock is the Mac hand-off's, and `lockf` is the BSD tool. Elsewhere it says SKIP and exits 0.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "${HERE}/.." && pwd)"
[ "$(uname -s)" = Darwin ] && command -v lockf >/dev/null 2>&1 || { echo "SKIP  not a Mac (no BSD lockf): the lock is the Mac hand-off's"; exit 0; }
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT
T="${TMP}/tree"; mkdir -p "${T}/packaging/macos"
cp "${ROOT}/bbox" "${T}/bbox"; ln -s "${ROOT}/scripts" "${T}/scripts"
LOG="${TMP}/calls.log"; : > "${LOG}"
# the fake hand-off: `engine.sh exec -- ./bbox <verb> [<project-pln verb>] <tag> [rc]` — holds a second, exits [rc]
cat > "${T}/packaging/macos/engine.sh" <<'SH'
#!/usr/bin/env bash
shift 3                                   # exec -- ./bbox
[ "$1" = project-pln ] && shift           # the app…
shift                                     # …and its verb (or the bbox verb)
tag="${1:-}"; rc="${2:-0}"
echo "start ${tag} $(perl -MTime::HiRes=time -e 'printf "%.3f", time')" >> "${CALLS_LOG}"
sleep 1
echo "end ${tag} $(perl -MTime::HiRes=time -e 'printf "%.3f", time')" >> "${CALLS_LOG}"
exit "${rc}"
SH
export CALLS_LOG="${LOG}" BBOX_PLANE_LOCK="${TMP}/plane.lock"
at() { awk -v w="$1" -v t="$2" '$1 == w && $2 == t {print $3}' "${LOG}"; }
before() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a != "" && b != "" && a < b)}'; }

# 1. two work-item calls at once: the second starts after the first ends
bash "${T}/bbox" project-pln tasks A & a=$!
sleep 0.2
bash "${T}/bbox" project-pln tasks B & b=$!
wait "${a}" "${b}"
if before "$(at end A)" "$(at start B)" || [ "$(at end A)" = "$(at start B)" ]; then
  ok "two work-item calls at once run one after the other (A ended $(at end A), B started $(at start B))"
else
  no "two work-item calls overlapped: $(tr '\n' ' ' < "${LOG}")"
fi

# 2. another verb, and another project-pln verb, are not held behind a work-item call
: > "${LOG}"
bash "${T}/bbox" project-pln tasks P & p=$!
sleep 0.3
bash "${T}/bbox" status S & s=$!
bash "${T}/bbox" project-pln plan Q & q=$!
wait "${p}" "${s}" "${q}"
if before "$(at start S)" "$(at end P)" && before "$(at start Q)" "$(at end P)"; then
  ok "\`bbox status\` and \`bbox project-pln plan\` are not held behind a work-item call"
else
  no "a verb that is not \`tasks\` waited for the work-item call: $(tr '\n' ' ' < "${LOG}")"
fi

# 3. no turn in time: exit 75, said, nothing sent
: > "${LOG}"
bash "${T}/bbox" project-pln tasks H & h=$!
sleep 0.3
out="$(BBOX_PLANE_LOCK_WAIT=0 bash "${T}/bbox" project-pln tasks L 2>&1)"; rc=$?
wait "${h}"
if [ "${rc}" -eq 75 ] && printf '%s' "${out}" | grep -q "already locked" && [ -z "$(at start L)" ]; then
  ok "a call that cannot get its turn exits 75, says so, and sends nothing"
else
  no "no turn in time: rc=${rc}, said «${out}», log $(tr '\n' ' ' < "${LOG}")"
fi

# 4. a caller that gives up while it waits: nothing runs later for it
: > "${LOG}"
bash "${T}/bbox" project-pln tasks H & h=$!
sleep 0.3
bash "${T}/bbox" project-pln tasks K & k=$!
sleep 0.3
kill "${k}" 2>/dev/null; wait "${k}" 2>/dev/null
wait "${h}"; sleep 1.5
[ -z "$(at start K)" ] && ok "a caller that gives up while it waits leaves nothing in the queue" \
  || no "the call of a caller that gave up ran later anyway: $(tr '\n' ' ' < "${LOG}")"

# 5. the call's own status comes back
bash "${T}/bbox" project-pln tasks R 3 >/dev/null 2>&1; rc=$?
[ "${rc}" -eq 3 ] && ok "the call's own exit status comes back through the lock (3)" || no "the call exited 3, bbox said ${rc}"

[ "${fails}" -eq 0 ] && echo "test_bbox_plane_lock: all passed" || echo "test_bbox_plane_lock: ${fails} failed"
exit "$([ "${fails}" -eq 0 ] && echo 0 || echo 1)"
