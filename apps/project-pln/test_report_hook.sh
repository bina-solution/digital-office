#!/usr/bin/env bash
# test_report_hook.sh — hooks/report against stand-ins for `plan` and `tasks` (DGO-948): what it prints
# and how it exits when the item is created, refused, created and then failed, already there, or asked
# for help. The real hook and the real report.py run in a scratch copy of the repo's layout; `plan`
# answers as plan.py's lines do, chosen by STUB_PLAN.
#
# The hook's environment is scrubbed of EVERY DSH_* variable before each case: a test that inherits a
# live agent session measures its runner (DSH_SESSION_ID makes `--said` read the session's own page and
# write a sixth report), not the code. So the run is the same inside an agent container and in CI.
#
#   bash apps/project-pln/test_report_hook.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/scripts" "${T}/apps/project-pln/hooks" "${T}/apps/project-pln/plans"
tr -d '\r' < "${HERE}/hooks/report" > "${T}/apps/project-pln/hooks/report"
cp "${HERE}/report.py" "${T}/apps/project-pln/report.py"
cat > "${T}/scripts/lib.sh" <<'EOF'
say() { echo "[bbox] $*"; }
c0=""; c1=""; cr=""; cg=""; cy=""; DN="hp"
npath() { printf '%s' "$1"; }
EOF
cat > "${T}/apps/project-pln/hooks/plan" <<'EOF'
#!/usr/bin/env bash
# stand-in: $1 the plan, $2 --only, $3 the key
touch "$(dirname "$0")/../plan-called"
case "${STUB_PLAN:-created}" in
  created) echo "  created label דיווח"; echo "  created DGO-99 [$3] the title"; echo "  created=2" ;;
  refused) echo "[bbox] [project-pln] applying $1 to workspace 'bina' (only: $3)"; echo "  Plane refused the token (HTTP 401)"; exit 1 ;;
  late)    echo "  created DGO-99 [$3] the title"; echo "  module-issues POST → HTTP 500"; exit 1 ;;
  updated) echo "  updated DGO-98 [$3]"; echo "  updated=1" ;;
esac
EOF
cat > "${T}/apps/project-pln/hooks/tasks" <<'EOF'
#!/usr/bin/env bash
echo "$2  the title"; echo "  http://console.localhost/#/m/project-pln/x/issues/y"
EOF
chmod +x "${T}/apps/project-pln/hooks/"*
FAILS=0
# every DSH_* variable of this shell, collected as `-u NAME` pairs (bash 3.2: no mapfile/readarray)
UNSET_SESSION=()
while IFS= read -r v; do
  case "${v}" in DSH_*) UNSET_SESSION+=(-u "${v}") ;; esac
done < <(env | cut -d= -f1)
run() {   # run <name> <want exit> <must print> -- <args…>
  local name="$1" want="$2" must="$3"; shift 4
  rm -f "${T}/apps/project-pln/plan-called"
  out="$(env ${UNSET_SESSION[@]+"${UNSET_SESSION[@]}"} \
         bash "${T}/apps/project-pln/hooks/report" "$@" 2>&1)"; rc=$?
  if [ "${rc}" = "${want}" ] && printf '%s' "${out}" | grep -qF -- "${must}"; then
    echo "PASS  ${name}"
  else
    echo "FAIL  ${name}: exit ${rc} (want ${want}), wanted «${must}» in:"; printf '%s\n' "${out}" | sed 's/^/        /'
    FAILS=$((FAILS + 1))
  fi
}
STUB_PLAN=created run "created: the item and its link, exit 0" 0 "http://console.localhost" -- 'הקונסול לא נטען'
STUB_PLAN=refused run "refused: the reason and the one command, exit 1" 1 "Plane refused the token" -- 't'
STUB_PLAN=refused run "refused: never «run the report again»" 1 "./bbox project-pln plan reports-hp --only rep-hp-" -- 't'
STUB_PLAN=late    run "created, then a failure: still exit 0, the failure shown" 0 "DGO-99 was created" -- 't'
STUB_PLAN=updated run "a key already in Plane: said loudly" 0 "ALREADY an item" -- 't'
run "--help: the usage, exit 0" 0 "report --said" -- --help
run "no arguments: the usage, exit 2" 2 "report --said" --
run "--said outside an agent session: refused, exit 2" 2 "inside an agent's session" -- --said
run "an empty title: refused, exit 2" 2 "needs a title" -- '   '
[ -e "${T}/apps/project-pln/plan-called" ] && { echo "FAIL  an empty title still called plan"; FAILS=$((FAILS + 1)); }
n="$(grep -c '^  - key: rep-hp-' "${T}/apps/project-pln/plans/reports-hp.yaml")"
[ "${n}" = 5 ] && echo "PASS  five reports, five keys in the file" || { echo "FAIL  ${n} keys in the file, want 5"; FAILS=$((FAILS + 1)); }
[ "$(grep -o '^  - key: rep-hp-[0-9-]*' "${T}/apps/project-pln/plans/reports-hp.yaml" | sort | uniq -d)" = "" ] \
  && echo "PASS  no key twice" || { echo "FAIL  a key twice"; FAILS=$((FAILS + 1)); }
echo "${FAILS} failing"
[ "${FAILS}" = 0 ]
