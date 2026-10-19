#!/usr/bin/env bash
# scripts/ops/admission-thresholds.sh
#
# THE ONE DECLARED SOURCE of "is this machine well enough to start heavy work".
# Source it; do not copy the numbers.
#
#     . "$(dirname "$0")/admission-thresholds.sh"      # or a path to here
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# WHY THIS FILE EXISTS
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Two admission gates were built independently, months apart, against the same laptop:
#
#   ops/prejob_waitfree.sh              WAITS for memory before a CI job starts (poll, then fail)
#   scripts/ops/machine-health-guard.sh REFUSES a heavy job outright (--admit <class>, exit 3)
#
# They are not redundant — one blocks-and-waits for a job that will eventually run, the other
# vetoes a job that should not start at all, and they have different callers. But they each carried
# their own hard-coded memory threshold (6 GiB and 1.5 GiB respectively, chosen at different times
# for different reasons), with nothing keeping them coherent. Two gates guarding one machine while
# disagreeing about when it is healthy is worse than either alone: whichever is looser silently
# becomes the real policy, and nobody notices which one that is.
#
# So the NUMBERS live here and the POLICY stays in each script. That split is deliberate: "how much
# memory is enough" is a property of the machine and belongs in one place; "wait vs refuse" is a
# property of the caller and belongs with the caller.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# WHERE THESE NUMBERS COME FROM (measured 2026-08-05/06 on the 9.7 GiB WSL2 VM)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# The failure being guarded against: the WSL distro is torn down under the running stack — 42
# systemd inits and 16 kernel boots in 24h, ZERO graceful docker stops — orphaning every in-flight
# n8n execution, which n8n then mislabels "possible out-of-memory issue". Memory correlates with
# it; CPU does not (load 15.0 at one teardown, 35.5 during a period with none).

# Minimum MemAvailable to START heavy work, MiB. At the 03:49 slide the VM had 192 MiB free while
# swap still had 4.3 GiB spare — a swap-only gate would have admitted the job. This is the number
# that catches it.
: "${ADMISSION_MIN_AVAIL_MIB:=1536}"

# Minimum MemAvailable to run a full 33-container stack bring-up, MiB. Higher than the figure
# above because bringing the stack UP is the heaviest thing this machine does; prejob_waitfree.sh
# is gating exactly that. Kept as GiB-granularity because its historical env var is GiB.
: "${ADMISSION_STACK_MIN_AVAIL_GB:=6}"

# Swap utilisation above which nothing heavy should start, percent. The documented precondition at
# the 03:31 teardown was 5.6 GiB of 6.0 GiB consumed.
: "${ADMISSION_MAX_SWAP_PCT:=50}"

# Seconds a freshly (re)started docker daemon must have been up. A stack that restarted a minute
# ago is still settling — n8n-postgres was measured replaying 390 MB of WAL over 65 s. Jobs started
# into that window fail for reasons that have nothing to do with the job.
: "${ADMISSION_MIN_DAEMON_AGE_S:=300}"

# Distro re-initialisations in the last hour above which the host is considered to be actively
# tearing itself down. Counting systemd[1] inits is the truest available measure: docker daemon
# starts matched systemd inits 42:42 over 24h, exactly 1:1 — dockerd never died on its own once.
: "${ADMISSION_MAX_RECENT_RESTARTS:=2}"

# Load average is DELIBERATELY ABSENT and must stay absent. This stack is CPU-oversubscribed by
# owner decision (two n8n workers at --concurrency=8 = 16 slots on 6 processors, plus a 12-worker
# gunicorn pool), so load above 8 is the NORMAL state of a machine doing its job. A load veto fires
# only during the conditions worth measuring, i.e. it demands an idle machine in order to measure a
# busy one. It also has no demonstrated predictive value for the teardown. Report it; never gate.
