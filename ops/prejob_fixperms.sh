#!/usr/bin/env bash
# prejob_fixperms.sh — runner pre-job hook: make the workspace deletable again.
#
# Installed at /opt/actions-runner/prejob_fixperms.sh and referenced by
#   ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/actions-runner/prejob_fixperms.sh
# in /opt/actions-runner/.env. The runner already pointed at this path; the script itself was
# missing, so the hook ran nothing and the problem below went unfixed.
#
# WHY
#
# Jobs in this repo run Docker containers that write into the checkout as root - benchmark output
# under legacy/feature-validation, __pycache__, ci-artifacts. The runner user cannot delete those,
# so the NEXT job's actions/checkout fails while cleaning the workspace, and once it has removed
# what it could the directory is left with files but no .git:
#
#     fatal: not a git repository (or any of the parent directories): .git
#
# From then on EVERY job fails inside checkout after about 0.16 seconds, across every workflow, and
# nothing in the PR view explains it - the commits are fine, the runner simply cannot get the code.
# Observed 2026-07-28: 30 consecutive jobs, with 40 root-owned files left behind.
#
# The real fix is for the jobs to stop writing as root (docker run --user "$(id -u):$(id -g)", or
# chowning what they produce). This hook is the safety net that keeps one such job from wedging the
# runner for everyone afterwards.
set -uo pipefail

# The WHOLE work folder, not $RUNNER_WORKSPACE. sudoers does not allow wildcards in command
# arguments, so the rule that permits this has to name one exact path - and the work folder is the
# only path that is the same for every job:
#   shlomy ALL=(root) NOPASSWD: /usr/bin/chown -R shlomy\:shlomy /opt/actions-runner/_work
WORK=/opt/actions-runner/_work
ME="$(id -un)"

# Nothing to do on the common path, and this hook runs before EVERY job - so it stays quiet unless
# it actually finds something, and never fails the job.
count=$(find "${WORK}" ! -user "${ME}" 2>/dev/null | wc -l)
if [ "${count:-0}" -eq 0 ]; then
  exit 0
fi

echo "prejob: ${count} path(s) under ${WORK} are not owned by ${ME}; taking ownership so checkout can clean them"
if sudo -n chown -R "${ME}:${ME}" "${WORK}" 2>/dev/null; then
  echo "prejob: ownership fixed"
else
  # Without passwordless sudo for this one command there is nothing more we can do, and failing the
  # hook would fail the job for a reason the job cannot fix. Say so loudly and let checkout try.
  echo "prejob: WARNING could not chown - checkout will likely fail." >&2
  echo "prejob: grant it with a narrow sudoers rule, e.g." >&2
  echo "prejob:   ${ME} ALL=(root) NOPASSWD: /usr/bin/chown -R ${ME}\\:${ME} ${WORK}" >&2
fi
exit 0
