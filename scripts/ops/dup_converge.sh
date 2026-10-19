#!/bin/bash
# Run duplicate-backlog convergence unattended: drive rounds, then repair what the guard blocked,
# and repeat until the backlog is zero or genuinely stuck.
#
# WHY IT ALTERNATES
# -----------------
# Two mechanisms fight each other and neither alone converges:
#   * dup_backlog_drive.sh feeds group mains. Every fed main that does not close its group gets an
#     action_merge_doubles row, and the double-action guard then refuses to dispatch it again.
#     Left alone, the drive loop's feedable pool drains to nothing while the backlog stands.
#   * restart_blocked_merge_mains.sh clears exactly those, through the console's own retry path,
#     with a retry cap so a genuine loop escalates instead of being restarted forever.
# So: drive, repair, drive, repair.
#
# WHAT SETS THE PACE (do not "fix" these by raising them)
#   * Admission control in the driver decides how many of the fed mains actually dispatch. Feeding
#     911 mains closes ~100 groups, not 911. That is the concurrency ceiling doing its job.
#   * A doc_action lock lives ~47 minutes and is NOT released when the action completes, so a main
#     is re-attemptable about once per lock cycle. The drive loop already excludes anything
#     attempted inside that window.
#
# usage: dup_converge.sh [cycles] [rounds_per_cycle] [batch]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CYCLES="${1:-8}"
ROUNDS="${2:-6}"
BATCH="${3:-5000}"

prev=""
for c in $(seq 1 "$CYCLES"); do
  echo "===== cycle $c/$CYCLES : drive ====="
  bash "$HERE/dup_backlog_drive.sh" loop "$ROUNDS" "$BATCH"

  echo "===== cycle $c/$CYCLES : repair guard-blocked mains ====="
  bash "$HERE/restart_blocked_merge_mains.sh" all 500

  echo "===== cycle $c/$CYCLES : state ====="
  bash "$HERE/dup_backlog_drive.sh" count
  now=$(bash "$HERE/dup_backlog_drive.sh" count | head -1 | tr -dc '0-9')

  if [ "${now:-1}" = "0" ]; then
    echo "  CONVERGED: no duplicate groups left"
    break
  fi
  # Two cycles with no movement at all means the remaining groups need a person, not another
  # dispatch -- print what to look at rather than spinning.
  if [ "$now" = "$prev" ]; then
    echo "  NO MOVEMENT across a full cycle. Remaining mains that burned the retry cap:"
    bash "$HERE/restart_blocked_merge_mains.sh" escalate
    break
  fi
  prev="$now"
done
echo "===== converge run finished ====="
