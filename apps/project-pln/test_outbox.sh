#!/usr/bin/env bash
# test_outbox.sh — the outbox of DGO-1100 / any-201, against stand-ins for docker and for Plane.
#
# What is proved here, with the REAL hooks/tasks, hooks/plan, where.sh and outbox.py in a scratch copy of
# the repo's layout (no Docker, no Plane, no Mac, no HP):
#   1. a write with NO path is kept, and the reply says «בתור, N ממתין» (never a failure);
#   2. a write that dies on the NETWORK is kept the same way;
#   3. when a path is back, the queue goes out once, in the order it was written;
#   4. a read with no path answers «לא מחובר מאז …» and no data at all;
#   5. a send that fails keeps its entry, in its place (order is the contract).
#
#   bash apps/project-pln/test_outbox.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/scripts" "${T}/apps/project-pln/hooks" "${T}/apps/project-pln/plans" \
         "${T}/apps/computers" "${T}/.generated/registry"
for f in hooks/tasks hooks/plan where.sh outbox.py; do
  tr -d '\r' < "${HERE}/${f}" > "${T}/apps/project-pln/${f}"
done
printf 'workspace:\n  slug: bina\n' > "${T}/apps/project-pln/bootstrap.yaml"
: > "${T}/apps/project-pln/tasks.py"          # the applier's body is never reached: dcx is a stand-in
printf 'apps:\n  project-pln: hp-laptop\n' > "${T}/apps/computers/herd.yaml"
printf 'plan: {}\n' > "${T}/apps/project-pln/plans/x.yaml"
: > "${T}/apps/project-pln/plan.py"      # idem: the plan applier is never reached
LOG="${T}/calls.log"; : > "${LOG}"
# ── the stand-ins ────────────────────────────────────────────────────────────────────────────────
cat > "${T}/scripts/lib.sh" <<'EOF'
say()  { echo "[bbox] $*"; }
c0=""; c1=""; cr=""; cg=""; cy=""; DN=vps1
npath() { printf '%s' "$1"; }
read_env() { grep -E "^$1=" "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2-; }
running() { [ "${STUB_RUNNING:-0}" = 1 ]; }            # a local project-pln container?
dcx() {                                                # every call is answered, from STUB_*_RC
  echo "dcx $*" >> "${STUB_LOG}"
  case " $* " in *"python3 -c"*) return "${STUB_PROBE_RC:-0}" ;; esac   # where.sh's reachability probe
  return "${STUB_DCX_RC:-0}"                                            # the applier in the container
}
EOF
cat > "${T}/bbox" <<'EOF'
#!/usr/bin/env bash
echo "bbox $*" >> "${STUB_LOG}"
[ "${STUB_BBOX_RC:-0}" = 0 ] || { echo "  [project-pln] Plane refused (HTTP 500)" >&2; exit "${STUB_BBOX_RC}"; }
echo "  [project-pln] did $*"
EOF
chmod +x "${T}/bbox"
FAILS=0
UNSET_SESSION=()
while IFS= read -r v; do
  case "${v}" in DSH_*) UNSET_SESSION+=(-u "${v}") ;; esac
done < <(env | cut -d= -f1)
clean() { "${T}/apps/project-pln/hooks/tasks" flush >/dev/null 2>&1; rm -rf "${T}/.state"; : > "${LOG}"; }
run() {   # run <name> <want exit> <want in output> <must not be in output|-> -- <hook args…>
  local name="$1" want="$2" must="$3" mustnot="$4"; shift 5
  out="$(cd "${T}" && env ${UNSET_SESSION[@]+"${UNSET_SESSION[@]}"} -u PLANE_API_URL -u PLN_OUTBOX_DIR \
         -u PLN_OUTBOX_REPLAY STUB_LOG="${LOG}" STUB_RUNNING="${RUNNING:-0}" \
         STUB_PROBE_RC="${PROBE_RC:-0}" STUB_DCX_RC="${DCX_RC:-0}" STUB_BBOX_RC="${BBOX_RC:-0}" \
         bash "${T}/apps/project-pln/hooks/tasks" "$@" 2>&1)"; rc=$?
  if [ "${rc}" = "${want}" ] && { [ -z "${must}" ] || printf '%s' "${out}" | grep -qF -- "${must}"; } \
     && { [ "${mustnot}" = "-" ] || ! printf '%s' "${out}" | grep -qF -- "${mustnot}"; }; then
    echo "PASS  ${name}"
  else
    echo "FAIL  ${name}: exit ${rc} (want ${want}), wanted «${must}»${mustnot:+ and not «${mustnot}»} in:"
    printf '%s\n' "${out}" | sed 's/^/        /'
    FAILS=$((FAILS + 1))
  fi
}
entries() { ls "${T}/.state/outbox/project-pln/pending" 2>/dev/null | wc -l | tr -d ' '; }

# ── 1. no path at all: the writes are kept, in order, and the reply says how many wait ─────────────
clean
run "no path: comment kept, «בתור, 1 ממתין», exit 0" 0 "בתור, 1 ממתין" - -- comment DGO-1 "first"
run "no path: a second write, «בתור, 2 ממתין»"       0 "בתור, 2 ממתין" - -- comment DGO-1 "second"
run "no path: start kept too"                        0 "בתור, 3 ממתין" - -- start DGO-1
[ "$(entries)" = 3 ] && echo "PASS  no path: three entries in the outbox" \
  || { echo "FAIL  no path: $(entries) entries, wanted 3"; FAILS=$((FAILS + 1)); }

# ── 4. a read with no path: «offline since …», and no data at all ───────────────────────────────────
run "no path: a read says «לא מחובר מאז», not a failure of its own" 1 "לא מחובר מאז" "the title" -- show DGO-1
run "no path: a read never answers from a stale copy" 1 "אין תשובה חיה" - -- list --project DGO

# ── 3. the path is back: the queue goes out once, in order — and nothing is sent twice ──────────────
RUNNING=1 run "path back: the write itself succeeds" 0 "" - -- comment DGO-1 "live"
grep -c '^bbox project-pln tasks' "${LOG}" | grep -qx 3 && echo "PASS  path back: three queued writes replayed" \
  || { echo "FAIL  path back: $(grep -c '^bbox project-pln tasks' "${LOG}") replayed, wanted 3"; FAILS=$((FAILS + 1)); }
order="$(grep '^bbox project-pln tasks' "${LOG}" | sed 's/.*tasks //' | tr '\n' '|')"
[ "${order}" = "comment DGO-1 first|comment DGO-1 second|start DGO-1|" ] \
  && echo "PASS  path back: in the order it was written, before this run's own write" \
  || { echo "FAIL  path back: order was «${order}»"; FAILS=$((FAILS + 1)); }
[ "$(entries)" = 0 ] && echo "PASS  path back: the outbox is empty" \
  || { echo "FAIL  path back: $(entries) still waiting"; FAILS=$((FAILS + 1)); }
: > "${LOG}"
RUNNING=1 run "path back: a second run sends nothing again" 0 "" "did project-pln tasks comment" -- show DGO-1
[ "$(grep -c '^bbox' "${LOG}")" = 0 ] && echo "PASS  exactly once: an empty queue sends nothing" \
  || { echo "FAIL  exactly once: $(grep -c '^bbox' "${LOG}") calls on an empty queue"; FAILS=$((FAILS + 1)); }
[ -s "${T}/.state/outbox/project-pln/last-seen" ] && echo "PASS  «offline since» is measured: last-seen is written" \
  || { echo "FAIL  last-seen was not written"; FAILS=$((FAILS + 1)); }

# ── 5. a send that fails keeps its entry, first in line (order is the contract) ─────────────────────
clean
run "queue while offline (1)" 0 "בתור, 1 ממתין" - -- comment DGO-1 "a"
run "and one more"            0 "בתור, 2 ממתין" - -- comment DGO-1 "b"
BBOX_RC=1 RUNNING=1 run "a failing send is reported, not lost" 0 "נשאר בתור, 2 ממתין" - -- show DGO-1
[ "$(entries)" = 2 ] && echo "PASS  a failed replay keeps both entries" \
  || { echo "FAIL  a failed replay left $(entries)"; FAILS=$((FAILS + 1)); }

# ── 2. a write that dies on the NETWORK (the door answered, then dropped) is kept as well ───────────
clean
DCX_RC=0 run "dead door mid-write: the applier's network error is caught" 0 "" - -- comment DGO-1 "x"
rm -rf "${T}/.state"
printf '' > "${T}/apps/project-pln/stub.env"
# the applier's own words when the network died (tasks.py: `{"error": "URLError: …"}`, code -1)
cat > "${T}/apps/project-pln/tasks.py" <<'EOF'
import sys
sys.stderr.write("[project-pln] URLError: <urlopen error [Errno 111] Connection refused>\n")
EOF
DCX_RC=1 run "network death mid-write: kept, not failed" 0 "בתור, 1 ממתין" - -- comment DGO-1 "y"

# ── a queued PLAN carries a copy of the plan file, and replays as `plan` ────────────────────────────
clean
out="$(cd "${T}" && env -u PLANE_API_URL -u PLN_OUTBOX_DIR -u PLN_OUTBOX_REPLAY STUB_LOG="${LOG}" \
      bash "${T}/apps/project-pln/hooks/plan" 'apps/project-pln/plans/x.yaml' --dry-run 2>&1)"; rc=$?
if [ "${rc}" = 0 ] && printf '%s' "${out}" | grep -qF "בתור, 1 ממתין"; then
  entry="$(ls -d "${T}/.state/outbox/project-pln/pending/"*/ | head -1)"
  if [ -n "${entry}" ] && [ -f "${entry}files/0-x.yaml" ]; then
    echo "PASS  plan: kept with a copy of the plan file"
  else
    echo "FAIL  plan: no copy of the plan file in ${entry:-the entry}"; FAILS=$((FAILS + 1))
  fi
else
  echo "FAIL  plan: exit ${rc}, output:"; printf '%s\n' "${out}" | sed 's/^/        /'; FAILS=$((FAILS + 1))
fi
: > "${LOG}"
RUNNING=1 PROBE_RC=0 run "plan: replayed as a plan, once" 0 "" - -- flush
grep -q '^bbox project-pln plan .*0-x.yaml --dry-run' "${LOG}" \
  && echo "PASS  plan: replay is «plan <the copy> --dry-run»" \
  || { echo "FAIL  plan: replay line «$(grep '^bbox' "${LOG}" | head -1)»"; FAILS=$((FAILS + 1)); }

echo
[ "${FAILS}" = 0 ] && { echo "outbox: all cases passed"; exit 0; }
echo "outbox: ${FAILS} case(s) failed"; exit 1
