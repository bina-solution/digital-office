#!/usr/bin/env bash
# prejob.sh — the runner's ONE pre-job hook, which now has two jobs to do.
#
#   ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/actions-runner/prejob.sh
#
# The runner offers exactly one hook path, so a dispatcher is the only way to keep the two concerns
# in separate files instead of accreting them into whichever script got there first.
#
# Order matters: wait for the machine to be free BEFORE touching the workspace, so a job that is
# going to sit at the gate for 20 minutes is not holding a half-fixed checkout while it waits.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${HERE}/prejob_waitfree.sh" || exit 1
bash "${HERE}/prejob_fixperms.sh" || exit 1
