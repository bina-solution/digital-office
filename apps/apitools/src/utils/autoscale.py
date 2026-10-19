# -*- coding: utf-8 -*-
"""FALLBACK sizing for apitools, used only when the platform profile has not spoken.

═══════════════════════════════════════════════════════════════════════════════════════════════════
OWNERSHIP — read this before changing anything here
═══════════════════════════════════════════════════════════════════════════════════════════════════
The PLATFORM PROFILE owns concurrency. This module is a FALLBACK, not an authority.

    Precedence, at every call site, without exception:
        explicit env var  >  this module's default

The env vars are written by scripts/perf-profile-apply from the profile selected in
platform/profiles/perf-profiles.yml. When apitools runs inside the platform, every slot count is
pinned there and NOTHING in this file is consulted. This file answers only when apitools runs
somewhere the profile system does not reach — CI, a bare `docker run`, someone's laptop — where a
container that cannot size itself at all would be worse.

WHY THE PROFILE OWNS IT AND NOT THIS FILE
-----------------------------------------
A container sizing itself from its own cgroup is locally correct and globally wrong. This module
can see only its own limit; it cannot see the other 43 containers. That is precisely the mechanism
that produced 4.46x oversubscription — every service sized itself sensibly and the sum was absurd.
Only the profile layer sees the whole machine budget, so only it can own the numbers.

THE BUG THAT ESTABLISHED THIS RULE (2026-08-06)
-----------------------------------------------
APITOOLS_MAX_CONCURRENT_OCR and APITOOLS_MAX_CONCURRENT_JSON_QUERY were pinned in the profile.
APITOOLS_MAX_CONCURRENT_PDF was not — so it fell through to ocr_slots_default() here, which is
MEMORY-DERIVED. A proposed APITOOLS_MEM cut of 8G -> 4G would therefore have silently moved PDF
rasterisation concurrency from 5 to 3, with nothing in the diff saying so: a memory edit changing
throughput through a hidden coupling. The fix was not to delete this logic, it was to PIN THE
REMAINING VALUE in the profile. The pattern was already right for two of three knobs.

CONSEQUENCE FOR ANYONE ADDING A KNOB HERE
-----------------------------------------
If you add a new `*_default()` below, you MUST also pin it in every profile in perf-profiles.yml.
An unpinned default is not a convenience — it is a value that changes when someone edits an
unrelated memory limit. scripts/refactor/memory-budget-lint.py (gate G30) checks for this.

═══════════════════════════════════════════════════════════════════════════════════════════════════

Derive concurrency defaults from the machine we ACTUALLY landed on.

WHY: the same image runs on a 4-core laptop and on much bigger servers. Hard-coded
slot counts are wrong on both ends — they idle cores on big boxes and oversubscribe
small ones. Every knob here is a DEFAULT: an explicit env var always wins.

The two inputs, read once at import:
- allotted CPUs: the cgroup CPU quota if one is set (docker `cpus:`), else the
  visible core count. Under the resident tesseract engine (0.6.1+) one OCR doc is
  ~single-threaded, so "cores" translates ~1:1 to useful OCR slots.
- memory limit: each concurrent OCR of a 300-DPI raster can spike toward ~1.2 GiB
  (75 MP pages); CPU-only sizing OOMs small containers, so slots are clamped by
  memory too.

Sizing rules:
- OCR slots   = clamp(cores - 1, by memory) — leave one core for the JSON-query
  traffic that runs interleaved with OCR; never below 1.
- JSON slots  = cores + 2 — queries are shorter and partly I/O-shaped (DB reads),
  so slight oversubscription keeps the pipe full without swamping the box.

Yielding to OTHER processes is deliberately NOT done here: that is the kernel's
job. The compose file gives apitools a low cpu_shares weight, so when anything
else needs CPU the scheduler shifts capacity within milliseconds — and when the
box is idle, OCR gets all of it. Priority, not caps.
"""
import os

from src.utils.logging_config import get_logger

logger = get_logger('apitools.autoscale')


def _cgroup_cpu_quota() -> float | None:
    """Allotted CPUs from the cgroup, or None when unlimited/unreadable."""
    try:  # cgroup v2
        with open('/sys/fs/cgroup/cpu.max') as f:
            quota, period = f.read().split()
            if quota != 'max':
                return float(quota) / float(period)
    except OSError:
        pass
    try:  # cgroup v1
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
            quota = int(f.read())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
            period = int(f.read())
        if quota > 0:
            return quota / period
    except OSError:
        pass
    return None


def _cgroup_mem_limit_gb() -> float | None:
    """Memory limit in GiB, or None when unlimited/unreadable."""
    for path in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        try:
            with open(path) as f:
                raw = f.read().strip()
            if raw == 'max':
                return None
            val = int(raw)
            # v1 reports a huge sentinel (~9.2e18) when no limit is set
            if val > 1 << 48:
                return None
            return val / (1 << 30)
        except OSError:
            continue
    return None


ALLOTTED_CPUS = _cgroup_cpu_quota() or float(os.cpu_count() or 2)
MEM_LIMIT_GB = _cgroup_mem_limit_gb()

# Calibrated against MEASURED reality on 0.6.2 (resident engine): a full cold
# corpus run with 3 concurrent OCR slots peaked the whole cgroup at 1.29 GiB —
# the resident engine passes raw buffers (no subprocess PNG copies), so per-OCR
# increments are far smaller than the pre-S1 guess of 1.2. 0.9/slot + 0.7 base
# keeps real headroom: on a 4 GiB limit this yields 3 slots (the proven config).
_MEM_PER_OCR_GB = 0.9
_MEM_BASE_GB = 0.7


def ocr_slots_default() -> int:
    by_cpu = max(1, int(ALLOTTED_CPUS) - 1)
    if MEM_LIMIT_GB is not None:
        by_mem = max(1, int((MEM_LIMIT_GB - _MEM_BASE_GB) / _MEM_PER_OCR_GB))
        return min(by_cpu, by_mem)
    return by_cpu


def json_slots_default() -> int:
    return int(ALLOTTED_CPUS) + 2


# MEASURED TWICE 2026-08-06, and the two measurements disagree — keep both, because the
# gap between them IS the finding:
#   (a) a FRESH worker (preload_app=False, cold-imports Flask/cv2/numpy/pytesseract/fitz
#       on its own) sits at 95-150 MiB before serving anything.
#   (b) under REAL traffic (12 workers, this host, during the saturated backfill window),
#       8 workers' actual /proc VmRSS summed to ~2.58 GiB — an OPERATING average of
#       ~322 MiB/worker, not 95-150. max_requests=50 recycling is confirmed firing (4
#       "Booting worker" events in 20 minutes) but a freshly-recycled worker can pick up
#       the very next large document and re-balloon within seconds when the queue is
#       this saturated — recycling bounds how long a worker STAYS bloated, not whether
#       it bloats at all. Sizing worker count from (a) undercounts real risk; (b) is
#       what the host actually has to carry, so it is what the formula uses.
_MEM_PER_WORKER_GB = 0.32

# This apitools-only reservation is a SECONDARY control. The primary constraint is
# host-wide, not this container's own cgroup: measured the same day, apitools's own 6G
# limit was NEVER the binding one — the WSL VM had as little as 135-734 MiB free
# system-wide (86%+ of a 6G swap file in use) while apitools itself sat at 2.5-2.95 GiB,
# comfortably under its 6G ceiling. A per-container memory limit cannot see the other 35+
# containers on the same host (see the ledger note in the module docstring) — no amount
# of retuning this formula fixes a host-wide 3.37x declared-memory overcommit (measured:
# ~33.5 GiB declared against a 9.95 GiB physical host, one container — `chat`, outside
# this app — declared with NO limit at all). What this formula CAN do is stop apitools
# from being the container that grows fastest into that shared shortfall. A fixed 2 GiB
# worker-memory budget (rather than a fraction of apitools's OWN 6G, which the host
# cannot actually spare regardless of what's nominally allotted) keeps that contribution
# bounded independent of whatever APITOOLS_MEM happens to be set to.
_WORKER_MEM_BUDGET_GB = 2.0


def gunicorn_workers_default() -> int:
    by_cpu = max(2, min(int(ALLOTTED_CPUS * 1.5), 8))
    by_mem = max(2, int(_WORKER_MEM_BUDGET_GB / _MEM_PER_WORKER_GB))
    return min(by_cpu, by_mem)


logger.info('autoscale: cpus=%.1f mem_limit=%s -> ocr_slots=%d json_slots=%d '
            '(env overrides win)',
            ALLOTTED_CPUS,
            ('%.1fGiB' % MEM_LIMIT_GB) if MEM_LIMIT_GB is not None else 'unlimited',
            ocr_slots_default(), json_slots_default())
