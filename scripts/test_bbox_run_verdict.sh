#!/usr/bin/env bash
# test_bbox_run_verdict.sh — how `bbox run` ends (DGO-995): «up.», «up, with problems» (soft, exit 0), «NOT up» (a
# fatal problem, exit 3); the old contract for a caller that asks for it (BBOX_RUN_FATAL_EXIT=0: follow's take,
# dgo-extend's converge) and for the Android office unit (the only one setting BBOX_ASSUME_DNS_OK); a targeted run;
# and the item's four call sites pinned. The functions are read out of bbox itself: the test holds the code that runs.
#     bash scripts/test_bbox_run_verdict.sh        (bash only; no docker, no office; scripts/test_bbox_run_contract.py runs it)
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BBOX="${HERE}/bbox"
fns="$(awk '/^run_problem\(\) \{/,/^\}/ {print} /^run_verdict\(\) \{/,/^\}/ {print} /^run_whole_kind\(\)/ {print}' "${BBOX}")"
[ "$(grep -c '^run_problem() {\|^run_verdict() {\|^run_whole_kind()' <<<"${fns}")" = 3 ] \
  || { echo "FAIL  bbox no longer defines run_problem, run_verdict and run_whole_kind"; exit 1; }
bad=0
# case_ <name> <want rc> <want text> <setup…>   (env: FATAL_EXIT, ASSUME, TARGETED)
case_() {
  local name="$1" want_rc="$2" want="$3"; shift 3
  local out rc
  out="$(FE="${FATAL_EXIT:-}" AS="${ASSUME:-}" TG="${TARGETED:-}" bash -c '
    say() { printf "[bbox] %s\n" "$*"; }; cr=""; cy=""; c0=""
    BBOX_RUN_PROBLEMS=""; BBOX_RUN_FATAL=""; BBOX_NL=$'"'"'\n'"'"'; BBOX_RUN_TARGETED="${TG}"
    [ -n "${FE}" ] && export BBOX_RUN_FATAL_EXIT="${FE}"
    [ -n "${AS}" ] && export BBOX_ASSUME_DNS_OK="${AS}"
    eval "$1"; shift; for s in "$@"; do eval "$s"; done; run_verdict; echo "[rc] 0"' _ "${fns}" "$@" 2>&1)"; rc=$?
  if [ "${rc}" = "${want_rc}" ] && grep -qF -- "${want}" <<<"${out}"; then echo "PASS  ${name}"
  else echo "FAIL  ${name}: rc=${rc} (want ${want_rc})"; printf '%s\n' "${out}" | sed 's/^/        /'; bad=1; fi
}
case_ "no problem: «up.», exit 0" 0 "up. check health with"
case_ "a soft problem: «up, with problems», exit 0" 0 "up, with problems:" 'run_problem soft "the follow timer could not be installed"'
case_ "…and its line is said" 0 "  - the follow timer could not be installed" 'run_problem soft "the follow timer could not be installed"'
case_ "a fatal problem: «NOT up», exit 3" 3 "NOT up:" 'run_problem fatal "not all services healthy after 300s"'
case_ "…and says it exits 3" 3 "this run exits 3" 'run_problem fatal "some first-party builds failed (above)"'
case_ "soft and fatal: fatal wins, both lines said" 3 "  - the follow timer could not be installed" \
  'run_problem soft "the follow timer could not be installed"' 'run_problem fatal "convergence finished with errors (above)"'
case_ "a kind that is neither is read as fatal" 3 "NOT up:" 'run_problem fatl "a typo"'
case_ "…and its words are kept" 3 "  - fatl a typo" 'run_problem fatl "a typo"'
case_ "an old call with no kind is fatal, its text whole" 3 "  - convergence finished with errors" 'run_problem "convergence finished with errors"'
FATAL_EXIT=0 case_ "BBOX_RUN_FATAL_EXIT=0: the old contract — «up, with problems», exit 0" 0 "up, with problems:" \
  'run_problem fatal "2 onboard hook(s) failed or did not run (named above)"'
FATAL_EXIT=0 case_ "…a line that would have ended it «NOT up» is tagged" 0 "  - [fatal] 2 onboard hook(s) failed" \
  'run_problem fatal "2 onboard hook(s) failed or did not run (named above)"'
FATAL_EXIT=0 case_ "…and what chose the old ending is named" 0 "BBOX_RUN_FATAL_EXIT=0 chose the old ending" \
  'run_problem fatal "2 onboard hook(s) failed or did not run (named above)"'
FATAL_EXIT=0 case_ "…a soft line is not tagged" 0 "  - the follow timer could not be installed" \
  'run_problem soft "the follow timer could not be installed"' 'run_problem fatal "x"'
ASSUME=1 case_ "the Android office unit (BBOX_ASSUME_DNS_OK): the old contract" 0 "up, with problems:" \
  'run_problem fatal "not all services healthy after 300s"'
ASSUME=1 case_ "…and it says so" 0 "BBOX_ASSUME_DNS_OK (Android's office unit) chose the old ending" \
  'run_problem fatal "not all services healthy after 300s"'
case_ "«NOT up» lines carry no kind prefix" 3 "  - not all services healthy after 300s" 'run_problem fatal "not all services healthy after 300s"'
ASSUME=1 FATAL_EXIT=3 case_ "…unless it asks for the new one" 3 "NOT up:" 'run_problem fatal "not all services healthy after 300s"'
TARGETED=1 case_ "a targeted run: an office-wide step is said, not fatal" 0 "up, with problems:" \
  'run_problem "$(run_whole_kind)" "1 onboard hook(s) failed or did not run (named above)"'
case_ "a whole-stack run: the same step is fatal" 3 "NOT up:" \
  'run_problem "$(run_whole_kind)" "1 onboard hook(s) failed or did not run (named above)"'
TARGETED=1 case_ "…and a targeted run's own build failing is fatal" 3 "NOT up:" 'run_problem fatal "some first-party builds failed (above)"'

# every call site names its kind, and the item's four are fatal (on a whole-stack run)
pin() { if grep -qE -- "$2" "${BBOX}"; then echo "PASS  $1"; else echo "FAIL  $1 — no line in bbox matches: $2"; bad=1; fi; }
untyped="$(grep -nE 'run_problem +"[^$]' "${BBOX}" || true)"
[ -z "${untyped}" ] && echo "PASS  every run_problem names its kind" || { echo "FAIL  run_problem without a kind:"; echo "${untyped}"; bad=1; }
[ "$(grep -cE 'run_problem fatal "some first-party builds failed' "${BBOX}")" = 2 ] && echo "PASS  a failed build is fatal (both build paths)" \
  || { echo "FAIL  a failed build is not fatal on both build paths"; bad=1; }
pin "unhealthy services are fatal" 'run_problem fatal "not all services healthy'
pin "a convergence that finished with errors is fatal on a whole-stack run" 'run_problem "\$\(run_whole_kind\)" "convergence finished with errors'
pin "a convergence check that failed is fatal on a whole-stack run" 'run_problem "\$\(run_whole_kind\)" "the convergence check failed'
pin "a refused onboard is fatal on a whole-stack run" 'run_problem "\$\(run_whole_kind\)" "\$\{_n\} onboard hook'
pin "a convergence that skipped an app while the workflow engine runs is fatal" 'run_problem "\$\(run_whole_kind\)" "automations not checked for: \$\{uc\} — the workflow engine'
pin "…and soft when no workflow engine runs here" 'run_problem soft "automations not checked for: \$\{uc\} — no workflow engine runs here'
pin "a targeted run is told by its arguments" '\[ \$# -gt 0 \] && BBOX_RUN_TARGETED=1'
exit ${bad}
