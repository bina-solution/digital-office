#!/usr/bin/env bash
# prejob_waitfree.sh — hold a job at the gate until this machine can actually run it.
#
# WHY THIS EXISTS
#
# The portable machine has 15 GB of RAM and two jobs that both want most of it:
#
#   * a CI job, which brings up the 33-container stack (~8 GB)
#   * the Windows test VM from packaging/windows/run-test-vm.sh (qemu, 10 GB resident)
#
# They do not fit together, and nothing was stopping them from being started together. Measured
# 2026-07-29 10:56 with the VM up: 12 GB used, 2 GB available, load 6.5, and ZERO containers running
# on either engine. Every job that needs the stack failed - gate, e2e, verify and all three ui-map
# profiles - while the two that do not need it (images, profiles) passed. Nothing in those failures
# says "out of memory": the stack simply never converges and the job times out on a health wait, so
# it reads as a product regression. It is not one. It is two workloads sharing one laptop.
#
# WHY WAIT RATHER THAN FAIL
#
# Failing fast would keep CI honest but throw the job away, and the VM is often up for 20 minutes at
# a time during packaging work. Waiting serialises them instead, which is what the machine needs and
# costs only latency. The wait is bounded: on timeout the job fails with a message that NAMES the
# VM, so the cause is in the failure rather than three layers underneath it.
#
# WHY THE TEST IS MEMORY, NOT "IS QEMU RUNNING"
#
# The first version required BOTH no qemu AND enough memory. Testing it immediately showed why that
# is wrong: after the VM was shut down, 11 GB was available and the qemu process was still winding
# down - so the gate blocked a job that the machine could comfortably run. Worse, it would block
# indefinitely for any small VM that is not the problem.
#
# Memory is the constraint that actually decides whether the job can succeed, so memory is what is
# tested. qemu is only the usual CAUSE, and it belongs in the message rather than in the condition.
#
# WHY NOT A LOCK
#
# The runner's only hook slot (ACTIONS_RUNNER_HOOK_JOB_STARTED) runs in its own process and exits
# before the job begins, so it cannot hold a flock for the job's duration. Observing the actual
# resource is also more honest than a lock: it is correct even when the VM is started by hand, from
# a different shell, or by someone who never read this file.
set -uo pipefail

# Threshold comes from the ONE declared source, shared with scripts/ops/machine-health-guard.sh
# --admit. Added 2026-08-06: these two gates guard the same machine and each carried its own
# hard-coded memory figure (6 GiB here, 1.5 GiB there) chosen at different times for different
# reasons, with nothing keeping them coherent. Whichever was looser silently became the real
# policy. The NUMBERS are shared; the wait-vs-refuse POLICY stays in each script, because "how
# much memory is enough" is a property of the machine and "wait or refuse" is a property of the
# caller. CI_WAITFREE_GB still overrides, so no CI invocation changes behaviour.
_AT="$(cd "$(dirname "$0")/../scripts/ops" 2>/dev/null && pwd)/admission-thresholds.sh"
# shellcheck source=/dev/null
[ -r "$_AT" ] && . "$_AT"

NEED_GB="${CI_WAITFREE_GB:-${ADMISSION_STACK_MIN_AVAIL_GB:-6}}"  # stack needs ~8; 6 free + cache is enough
TIMEOUT_S="${CI_WAITFREE_TIMEOUT:-2700}" # 45 min - longer than a full VM test run
POLL_S=15                                # short poll: this must not add idle time of its own

avail_gb() { awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo; }
vm_up()    { pgrep -f 'qemu-system-x86_64' >/dev/null 2>&1; }

if [ "$(avail_gb)" -ge "${NEED_GB}" ]; then exit 0; fi

echo "prejob: not enough memory to start this job yet - waiting"
echo "prejob:   memory available: $(avail_gb) GB (need ${NEED_GB} GB)"
vm_up && echo "prejob:   qemu (the Windows test VM) is running - that is usually the reason"

waited=0
while [ "${waited}" -lt "${TIMEOUT_S}" ]; do
  sleep "${POLL_S}"; waited=$((waited + POLL_S))
  if [ "$(avail_gb)" -ge "${NEED_GB}" ]; then
    echo "prejob: machine free after ${waited}s ($(avail_gb) GB available) - starting the job"
    exit 0
  fi
  [ $((waited % 300)) -eq 0 ] && echo "prejob:   still waiting (${waited}s), $(avail_gb) GB available, qemu $(vm_up && echo up || echo down)"
done

echo "prejob: FAILING after ${TIMEOUT_S}s - the machine never freed up." >&2
echo "prejob: qemu (the Windows test VM) is $(vm_up && echo STILL RUNNING || echo down), $(avail_gb) GB available." >&2
echo "prejob: this job needs ~${NEED_GB} GB. Stop the VM, or run CI on a machine that is not also" >&2
echo "prejob: hosting a 10 GB guest. Failing here rather than letting the stack fail to converge," >&2
echo "prejob: which looks like a product bug and is not one." >&2
exit 1
