#!/usr/bin/env python3
"""
timeline-gaps.py — idle-slot / backlog gap analysis for the n8n execution pool.

Reconstructs the worker-slot timeline from n8n's own `execution_entity` table
(startedAt/stoppedAt/status/workflowId) and reports every way the pool leaves
throughput on the table while a backlog exists:

  1. Slot utilisation over time (pool = workers x concurrency, default 2x8=16)
  2. Gap census: idle-slot intervals, ranked by total slot-time lost, with what
     finished right before each gap
  3. Per-workflow concurrency (max simultaneous executions) - flags serial workflows
  4. Schedule alignment: for schedule-triggered workflows, cycle time vs the
     schedule's own configured interval -> dead time per pipe per hour
  5. Queue depth vs activity: sync_ledger delivery timeline vs running executions
     (best-effort - table/columns are environment specific, degrades gracefully)
  6. Zombie executions: rows stuck in status='running' well past any real
     execution's duration - do they occupy slots that never free up?

This talks to Postgres via `docker exec <container> psql` so it needs nothing
installed beyond docker + python3, and works the same on the VPS or shlomo-laptop.
It must be run where the docker socket for this deployment is reachable - on
this workstation that means inside WSL with:

    export DOCKER_HOST=unix:///run/bbox-docker.sock
    python3 scripts/ops/timeline-gaps.py --hours 8

Windows callers: write a one-line wrapper .sh that exports DOCKER_HOST and
calls this script, then run it with
    MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash <wrapper>.sh

READING A CLUSTER OF `canceled` / `crashed` EXECUTIONS — one rule, and it settles it
------------------------------------------------------------------------------------
A tight band of DURATIONS is not evidence of a timeout. Check the STARTS and the STOPS
before believing it is:

    a TIMEOUT     -> stops are spread out, durations are identical.
                     Each execution dies N seconds after its own start, whenever that was.
    an EXTERNAL KILL -> starts are spread out, stops are within seconds of each other,
                     and the durations are just `stop_instant - start_stagger`.

Sorting by duration hides the difference, because it puts the earliest-started rows at the
top and manufactures a tight band out of a single kill. Measured example, 2026-08-06: the 14
slowest `canceled` SyncProcGDoc0001 executions clustered at 1557-1589s and read exactly like a
~26-minute ceiling. They started across 01:06:36-01:07:11 (a 35s stagger) and stopped across
01:32:57.9-01:32:59.7 (a 1.9s window). That minute cancelled 77 executions across 4 different
workflows, and SyncProcGDoc0001's own `executionTimeout` is 2700s -- nowhere near 1589s. It
was an n8n restart, not a ceiling. Several hours were spent on the wrong hypothesis first.

Two cheap confirmations, both one query:

    -- spread inside each big cancel minute: a mass stop is seconds wide, across MANY workflows
    select date_trunc('minute',"stoppedAt") m, count(*) n, count(distinct "workflowId") wfs,
           extract(epoch from (max("stoppedAt")-min("stoppedAt")))::int spread_s
      from execution_entity where status='canceled' group by 1 having count(*)>=20 order by 2 desc;

    -- and the workflow's OWN limit, before blaming one:
    select id, name, settings->>'executionTimeout' from workflow_entity where id='<id>';

`crashed` clusters the same way and even harder (502 rows in one minute across 5 workflows on
this host), which is the same signature confirming itself: containers recreated at 09:36 produced
155 `crashed` rows at 09:38. On a workstation whose WSL VM restarts under memory pressure, most
large `canceled`/`crashed` clusters are the VM, not the pipeline.

Examples:
    python3 timeline-gaps.py --hours 8
    python3 timeline-gaps.py --start "2026-08-05 14:45" --end "2026-08-05 21:00"
    python3 timeline-gaps.py --hours 8 --workers 2 --concurrency 8 --bucket 30
    python3 timeline-gaps.py --hours 8 --min-idle-slots 1   # any idle slot counts
    python3 timeline-gaps.py --hours 8 --lookahead 20       # backlog-signal window (min)
"""
import argparse
import csv
import io
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DEFAULT_WORKERS = 2
DEFAULT_CONCURRENCY = 8

# Workflows considered part of the sync/indox document pipeline family, used as
# the "is there backlog work moving nearby" signal for the gap census and as
# the default set for per-workflow concurrency / schedule-alignment sections.
FAMILY_PREFIXES = (
    "syncV3", "SyncProc", "SyncScan", "SyncSource", "syncLedgerApi",
    "sv3Inject", "indoxProcessDocument", "indoxV2", "indoxDocBatchUpsert",
    "indoxGmail", "indoxDataGateway", "indoxDocUploader", "indoxDocGet",
    "mailDiscovery",
)


def sh(cmd: str) -> str:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {cmd}\nSTDERR:\n{p.stderr}")
    return p.stdout


def find_container(prefix: str) -> str:
    out = sh("docker ps --format '{{.Names}}'")
    names = [n for n in out.splitlines() if n.strip().startswith(prefix)]
    if not names:
        raise RuntimeError(f"no running container found with name prefix '{prefix}'")
    return names[0]


def psql_csv(container: str, db: str, user: str, query: str) -> list[dict]:
    query_escaped = query.replace('"', '\\"')
    cmd = f'docker exec {container} psql -U {user} -d {db} --csv -c "{query_escaped}"'
    out = sh(cmd)
    reader = csv.DictReader(io.StringIO(out))
    return list(reader)


_TS_RE = __import__("re").compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<time>\d{2}:\d{2})(?::(?P<sec>\d{2}))?"
    r"(?:\.(?P<frac>\d+))?(?P<tz>[+-]\d{2}(?::?\d{2})?)?$"
)


def parse_ts(s: str):
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # psql CSV timestamps: 2026-08-05 14:45:51.394+00 / .52+00 / no fraction at all
    m = _TS_RE.match(s)
    if not m:
        raise ValueError(f"unrecognised timestamp: {s!r}")
    frac = (m.group("frac") or "0").ljust(6, "0")[:6]
    sec = m.group("sec") or "00"
    tz = m.group("tz") or "+00"
    if ":" not in tz:
        tz = tz + ":00" if len(tz) == 3 else tz[:3] + ":" + tz[3:]
    iso = f"{m.group('date')}T{m.group('time')}:{sec}.{frac}{tz}"
    return datetime.fromisoformat(iso)


def fmt_dur(seconds: float) -> str:
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=None, help="analyse the last N hours of execution history")
    ap.add_argument("--start", type=str, default=None, help="window start, e.g. '2026-08-05 14:45'")
    ap.add_argument("--end", type=str, default=None, help="window end, e.g. '2026-08-05 21:00' (default: now)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--bucket", type=int, default=30, help="bucket size in seconds for the utilisation sweep (default 30)")
    ap.add_argument("--min-idle-slots", type=int, default=1, help="minimum idle slots for a bucket to count toward the gap census")
    ap.add_argument("--lookahead", type=int, default=20, help="minutes to look ahead for a 'family' execution start to treat a gap as backlog-present (default 20)")
    ap.add_argument("--zombie-minutes", type=int, default=20, help="a 'running' execution older than this (minutes) with no stoppedAt is flagged a zombie")
    ap.add_argument("--n8n-container", type=str, default="n8n-postgres", help="container name prefix for the n8n postgres db")
    ap.add_argument("--n8n-db", type=str, default="n8n")
    ap.add_argument("--n8n-user", type=str, default="hacohen")
    ap.add_argument("--ledger-container", type=str, default="supabase-db", help="container name prefix for the ledger/supabase postgres db")
    ap.add_argument("--ledger-db", type=str, default="postgres")
    ap.add_argument("--ledger-user", type=str, default="postgres")
    ap.add_argument("--doc-seconds", type=float, default=200.0, help="assumed seconds per document, for converting lost slot-time into documents/hour (default 200s, midpoint of the 150-250s known range)")
    ap.add_argument("--top", type=int, default=15, help="how many rows to print in ranked tables")
    ap.add_argument("--slot-modes", type=str, default="trigger,webhook,manual,error,retry,cli",
                     help="execution 'mode' values that actually occupy a worker/queue slot. "
                          "n8n's mode='integrated' rows are sub-workflow (Execute Workflow) calls that run "
                          "INSIDE the calling execution's own slot, not a new queued job - including them "
                          "in the slot sweep overcounts occupancy (can show >100%% utilisation). Excluded by default.")
    args = ap.parse_args()
    slot_modes = {m.strip() for m in args.slot_modes.split(",") if m.strip()}

    pool_size = args.workers * args.concurrency

    n8n_container = find_container(args.n8n_container)
    try:
        ledger_container = find_container(args.ledger_container)
    except RuntimeError:
        ledger_container = None

    now = datetime.now(timezone.utc)
    end = parse_ts(args.end) if args.end else now
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if args.start:
        start = parse_ts(args.start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    elif args.hours:
        start = end - timedelta(hours=args.hours)
    else:
        # default: full available history
        rows = psql_csv(n8n_container, args.n8n_db, args.n8n_user,
                         'SELECT min("startedAt") AS m FROM execution_entity WHERE "startedAt" IS NOT NULL;')
        start = parse_ts(rows[0]["m"]) if rows and rows[0]["m"] else end - timedelta(hours=8)

    print(f"# timeline-gaps.py")
    print(f"# window: {start} .. {end}  ({(end-start).total_seconds()/3600:.2f}h)")
    print(f"# pool: {args.workers} workers x {args.concurrency} concurrency = {pool_size} slots")
    print(f"# n8n db container: {n8n_container}   ledger db container: {ledger_container or '(not found - queue-depth section skipped)'}")
    print()

    # ---- 1. fetch workflow name map -----------------------------------------
    wf_rows = psql_csv(n8n_container, args.n8n_db, args.n8n_user, "SELECT id, name FROM workflow_entity;")
    wf_name = {r["id"]: r["name"] for r in wf_rows}

    # ---- 2. fetch executions in window --------------------------------------
    q = (
        'SELECT id, "workflowId", mode, status, "startedAt", "stoppedAt" '
        'FROM execution_entity '
        f"WHERE \"startedAt\" >= '{start.strftime('%Y-%m-%d %H:%M:%S')}' "
        f"AND \"startedAt\" <= '{end.strftime('%Y-%m-%d %H:%M:%S')}' "
        'ORDER BY "startedAt";'
    )
    exec_rows = psql_csv(n8n_container, args.n8n_db, args.n8n_user, q)

    intervals = []  # (start, stop_effective, workflowId, status, id, mode) -- ALL executions (incl. sub-workflow calls)
    slot_intervals = []  # subset that actually occupies a worker/queue slot (mode in slot_modes)
    trigger_intervals = []  # subset that is mode=='trigger' - actual cron/schedule firings only
    no_start = 0
    still_running = 0
    mode_counts = defaultdict(int)
    for r in exec_rows:
        st = parse_ts(r["startedAt"])
        if st is None:
            no_start += 1
            continue
        sp = parse_ts(r["stoppedAt"])
        if sp is None:
            still_running += 1
            sp = end if r["status"] == "running" else st  # crashed/error w/o stoppedAt: treat as instantaneous
        mode_counts[r["mode"]] += 1
        row = (st, sp, r["workflowId"], r["status"], r["id"])
        intervals.append(row)
        if r["mode"] in slot_modes:
            slot_intervals.append(row)
        if r["mode"] == "trigger":
            trigger_intervals.append(row)

    print(f"# executions in window: {len(exec_rows)}  (no startedAt/phantom: {no_start}, still running at window end: {still_running})")
    print(f"# mode breakdown: " + ", ".join(f"{m}={n}" for m, n in sorted(mode_counts.items(), key=lambda x: -x[1])))
    print(f"# slot-occupying executions (mode in {sorted(slot_modes)}): {len(slot_intervals)} of {len(intervals)}")
    print(f"# NOTE: mode='integrated' rows are Execute-Workflow sub-calls that run INSIDE the caller's own")
    print(f"# slot (n8n does not queue them separately) - they are excluded from slot occupancy below but")
    print(f"# still included in the per-workflow concurrency section, since a workflow fanning out many")
    print(f"# parallel integrated calls is itself a meaningful (non-slot) concurrency signal.")
    print()

    if not intervals:
        print("No executions with a usable startedAt in this window - nothing to analyse.")
        return

    # ---- 3. bucketed occupancy sweep (slot-occupying executions only) -------
    bucket_s = args.bucket
    total_s = (end - start).total_seconds()
    n_buckets = int(total_s // bucket_s) + 2
    delta = [0] * (n_buckets + 1)
    family_delta = [0] * (n_buckets + 1)  # starts of family-workflow executions (any mode), for backlog signal

    def bucket_idx(t):
        off = (t - start).total_seconds()
        off = max(0, min(off, total_s))
        return int(off // bucket_s)

    for st, sp, wfid, status, _id in slot_intervals:
        bi = bucket_idx(st)
        bj = bucket_idx(sp) + 1
        if bj <= bi:
            bj = bi + 1
        delta[bi] += 1
        delta[bj] -= 1

    for st, sp, wfid, status, _id in intervals:
        if any(wfid.startswith(p) for p in FAMILY_PREFIXES) or wf_name.get(wfid, "").lower().startswith(("sync", "process document", "indox")):
            bi = bucket_idx(st)
            family_delta[bi] += 1

    occ = [0] * n_buckets
    running_total = 0
    for i in range(n_buckets):
        running_total += delta[i]
        occ[i] = running_total

    # forward-looking family activity signal (has-family-start-within-lookahead)
    lookahead_buckets = int((args.lookahead * 60) // bucket_s) + 1
    family_starts = [0] * n_buckets
    running_total = 0
    for i in range(n_buckets):
        running_total += family_delta[i]
        family_starts[i] = running_total
    # backlog_signal[i] = any family execution START in [i, i+lookahead_buckets)
    backlog_signal = [False] * n_buckets
    # suffix technique: is there a bucket j in [i, i+la) with family_delta[j] > 0 (a start)?
    next_family_start_bucket = [None] * (n_buckets + 1)
    nxt = None
    for i in range(n_buckets - 1, -1, -1):
        if family_delta[i] > 0:
            nxt = i
        next_family_start_bucket[i] = nxt
    for i in range(n_buckets):
        j = next_family_start_bucket[i]
        backlog_signal[i] = j is not None and j <= i + lookahead_buckets

    # ---- utilisation summary -------------------------------------------------
    util_sum = sum(occ)
    util_avg = util_sum / n_buckets if n_buckets else 0
    idle_slot_seconds_all = sum(max(0, pool_size - o) for o in occ) * bucket_s
    idle_slot_seconds_backlog = sum(
        max(0, pool_size - o) for i, o in enumerate(occ) if backlog_signal[i]
    ) * bucket_s

    print("## 1. Slot utilisation")
    print(f"Average busy slots: {util_avg:.2f} / {pool_size}  ({100*util_avg/pool_size:.1f}% utilisation)")
    print(f"Idle slot-time, whole window:        {fmt_dur(idle_slot_seconds_all)}  ({idle_slot_seconds_all/3600:.1f} slot-hours)")
    print(f"Idle slot-time, WHILE BACKLOG SIGNAL: {fmt_dur(idle_slot_seconds_backlog)}  ({idle_slot_seconds_backlog/3600:.1f} slot-hours)")
    lost_docs = idle_slot_seconds_backlog / args.doc_seconds
    lost_docs_per_hour = lost_docs / (total_s / 3600) if total_s else 0
    print(f"  -> at {args.doc_seconds:.0f}s/doc that idle time could have processed ~{lost_docs:.0f} more documents")
    print(f"  -> averaged over the window: ~{lost_docs_per_hour:.1f} documents/hour left on the table")
    print()

    # 10-minute utilisation table
    print("Utilisation by 10-minute bin (busy/pool, backlog-signal marked with *):")
    bin_buckets = max(1, int(600 // bucket_s))
    i = 0
    while i < n_buckets:
        j = min(i + bin_buckets, n_buckets)
        avg_busy = sum(occ[i:j]) / (j - i)
        any_backlog = any(backlog_signal[i:j])
        t0 = start + timedelta(seconds=i * bucket_s)
        filled = min(pool_size, int(round(avg_busy)))
        overflow = "+" if avg_busy > pool_size else " "
        bar = "#" * filled + "." * (pool_size - filled)
        print(f"  {t0.strftime('%H:%M')}  [{bar}]{overflow} {avg_busy:6.1f}/{pool_size}  {'*backlog' if any_backlog else ''}")
        i = j
    print()

    # ---- 4. gap census --------------------------------------------------------
    print("## 2. Gap census (idle-slot intervals while backlog signal was present)")
    gaps = []  # (start_bucket, end_bucket, idle_slot_seconds, min_busy)
    i = 0
    while i < n_buckets:
        if backlog_signal[i] and (pool_size - occ[i]) >= args.min_idle_slots:
            j = i
            slot_secs = 0
            while j < n_buckets and backlog_signal[j] and (pool_size - occ[j]) >= args.min_idle_slots:
                slot_secs += (pool_size - occ[j]) * bucket_s
                j += 1
            gaps.append((i, j, slot_secs))
            i = j
        else:
            i += 1

    # what finished right before each gap
    stops_sorted = sorted(intervals, key=lambda r: r[1])

    def last_finisher_before(t):
        # binary-search-ish linear scan is fine at this scale; keep simple
        best = None
        for st, sp, wfid, status, _id in stops_sorted:
            if sp <= t:
                best = (sp, wfid, status)
            else:
                break
        return best

    gaps.sort(key=lambda g: -g[2])
    print(f"Total distinct gap intervals: {len(gaps)}   Total slot-time lost to gaps: {fmt_dur(sum(g[2] for g in gaps))}")
    print(f"Top {min(args.top, len(gaps))} by slot-time lost:")
    for i, j, slot_secs in gaps[: args.top]:
        gs = start + timedelta(seconds=i * bucket_s)
        ge = start + timedelta(seconds=j * bucket_s)
        wall = (ge - gs).total_seconds()
        finisher = last_finisher_before(gs)
        fin_str = f"{wf_name.get(finisher[1], finisher[1])} ({finisher[2]}) @ {finisher[0].strftime('%H:%M:%S')}" if finisher else "(nothing recorded before window start)"
        print(f"  {gs.strftime('%H:%M:%S')} -> {ge.strftime('%H:%M:%S')}  wall={fmt_dur(wall)}  slot-time-lost={fmt_dur(slot_secs)}   preceded by: {fin_str}")
    print()

    # ---- 5. per-workflow concurrency ------------------------------------------
    print("## 3. Per-workflow concurrency (max simultaneous executions, ALL modes incl. sub-workflow calls)")
    by_wf = defaultdict(list)
    for st, sp, wfid, status, _id in intervals:
        by_wf[wfid].append((st, sp))

    wf_stats = []
    for wfid, ivs in by_wf.items():
        events = []
        for st, sp in ivs:
            events.append((st, 1))
            events.append((sp, -1))
        events.sort(key=lambda e: (e[0], -e[1]))  # starts before stops at same instant
        cur = 0
        peak = 0
        for _, d in events:
            cur += d
            peak = max(peak, cur)
        wf_stats.append((wfid, len(ivs), peak))

    wf_stats.sort(key=lambda r: -r[1])
    print(f"{'workflow':45s} {'runs':>6s} {'max concurrent':>15s}")
    for wfid, n, peak in wf_stats[: args.top]:
        name = wf_name.get(wfid, wfid)
        flag = "  <- SERIALISED (never overlaps itself)" if peak == 1 and n > 3 else ""
        print(f"{name[:45]:45s} {n:6d} {peak:15d}{flag}")

    watch_ids = [
        "syncV3Main0001", "syncV3Unit0001", "SyncScanner00001", "SyncScanUnit0001",
        "SyncProcBS000001", "SyncProcGDoc0001", "syncV3Deliver0001", "syncLedgerApi01",
        "indoxProcessDocument01", "indoxV2GenerateThumbnail01", "indoxV2Driver01",
        "processLock01", "indoxDataGateway01",
    ]
    watch_stats = {w[0]: w for w in wf_stats}
    print("\nNamed pipeline workflows (called out in scope, may not be in the top-N above):")
    for wfid in watch_ids:
        name = wf_name.get(wfid, wfid)
        if wfid in watch_stats:
            _, n, peak = watch_stats[wfid]
            flag = "  <- SERIALISED (never overlaps itself)" if peak == 1 and n > 3 else ""
            print(f"  {name[:45]:45s} {n:6d} {peak:15d}{flag}")
        else:
            print(f"  {name[:45]:45s}      0 runs in window")
    print()

    # ---- 6. schedule alignment --------------------------------------------------
    print("## 4. Schedule alignment (mode='trigger' executions ONLY - real cron/schedule firings, "
          "excludes on-demand sub-workflow calls that happen to run at a steady cadence)")
    trigger_by_wf = defaultdict(list)
    for st, sp, wfid, status, _id in trigger_intervals:
        trigger_by_wf[wfid].append((st, sp))
    print(f"{'workflow':40s} {'runs':>5s} {'median cycle':>13s} {'median runtime':>15s} {'dead/cycle':>11s} {'dead-time/hr':>13s}")
    schedule_rows = []
    for wfid, ivs in trigger_by_wf.items():
        # only consider workflows that look schedule-shaped: >=3 runs, roughly-regular gaps
        ivs.sort(key=lambda r: r[0])
        if len(ivs) < 3:
            continue
        starts = [st for st, sp in ivs]
        deltas = [(starts[k + 1] - starts[k]).total_seconds() for k in range(len(starts) - 1)]
        deltas.sort()
        median_cycle = deltas[len(deltas) // 2]
        runtimes = sorted([(sp - st).total_seconds() for st, sp in ivs])
        median_runtime = runtimes[len(runtimes) // 2]
        # only report workflows with a plausible fixed-interval shape (low spread) and cycle >> a few seconds
        if median_cycle < 30:
            continue
        dead_per_cycle = max(0, median_cycle - median_runtime)
        cycles_per_hour = 3600 / median_cycle if median_cycle else 0
        dead_per_hour = dead_per_cycle * cycles_per_hour
        schedule_rows.append((wfid, len(ivs), median_cycle, median_runtime, dead_per_cycle, dead_per_hour))

    schedule_rows.sort(key=lambda r: -r[5])
    for wfid, n, cyc, rt, dead, dead_hr in schedule_rows[: args.top]:
        name = wf_name.get(wfid, wfid)
        print(f"{name[:40]:40s} {n:5d} {fmt_dur(cyc):>13s} {fmt_dur(rt):>15s} {fmt_dur(dead):>11s} {fmt_dur(dead_hr)+'/hr':>13s}")
    total_dead_hr = sum(r[5] for r in schedule_rows)
    print(f"\nTotal schedule dead-time across these pipes: ~{fmt_dur(total_dead_hr)} per hour of wall clock"
          f" (~{total_dead_hr/args.doc_seconds:.1f} docs/hour of pool time, if that time were reallocated)")
    print()

    # ---- 7. zombie executions ----------------------------------------------------
    print("## 5. Zombie executions (status='running', started long ago, never stopped)")
    zq = (
        'SELECT id, "workflowId", "startedAt" FROM execution_entity '
        'WHERE status=\'running\' ORDER BY "startedAt";'
    )
    running_rows = psql_csv(n8n_container, args.n8n_db, args.n8n_user, zq)
    zombies = []
    for r in running_rows:
        st = parse_ts(r["startedAt"])
        if st is None:
            continue
        age = (now - st).total_seconds() / 60
        if age >= args.zombie_minutes:
            zombies.append((r["id"], r["workflowId"], st, age))
    print(f"Currently running executions: {len(running_rows)}   Zombies (running >= {args.zombie_minutes}min): {len(zombies)}")
    if zombies:
        held_slots_pct = 100 * len(zombies) / pool_size
        print(f"  -> if still occupying worker slots, that's {len(zombies)}/{pool_size} slots ({held_slots_pct:.0f}%) permanently unavailable until reaped")
        for eid, wfid, st, age in zombies[: args.top]:
            print(f"    exec {eid}  {wf_name.get(wfid, wfid)}  started {st}  age={age:.0f}min")
    print()

    # ---- 8. queue depth vs activity (best-effort) ---------------------------------
    print("## 6. Queue depth vs activity (sync_ledger)")
    if ledger_container is None:
        print("  ledger db container not found on this host - skipped.")
    else:
        try:
            cols = psql_csv(ledger_container, args.ledger_db, args.ledger_user,
                             "SELECT column_name FROM information_schema.columns WHERE table_name='sync_ledger';")
            colnames = {c["column_name"] for c in cols}
            if not colnames:
                print("  sync_ledger table not found - skipped.")
            else:
                status_rows = psql_csv(ledger_container, args.ledger_db, args.ledger_user,
                                        "SELECT status, count(*) AS n FROM sync_ledger GROUP BY status ORDER BY n DESC;")
                print("  current sync_ledger status breakdown:")
                for r in status_rows:
                    print(f"    {r['status']:20s} {r['n']}")
                if "delivered_at" in colnames:
                    dq = ("SELECT date_trunc('hour', delivered_at) AS h, count(*) AS n FROM sync_ledger "
                          "WHERE delivered_at IS NOT NULL GROUP BY 1 ORDER BY 1;")
                    dr = psql_csv(ledger_container, args.ledger_db, args.ledger_user, dq)
                    print("  deliveries per hour:")
                    for r in dr:
                        print(f"    {r['h']}  {r['n']}")
                if "claimed_at" in colnames:
                    cq = "SELECT count(*) AS n FROM sync_ledger WHERE claimed_at IS NOT NULL AND delivered_at IS NULL;"
                    cr = psql_csv(ledger_container, args.ledger_db, args.ledger_user, cq)
                    print(f"  items claimed but not yet delivered (in-flight per ledger): {cr[0]['n'] if cr else 'n/a'}")
                if "created_at" in colnames:
                    # scripts/ops/migrations/2026-08-06_sync_ledger_created_at.sql - degrades
                    # gracefully (this whole block is skipped) on any environment where that
                    # migration has not been applied yet, same pattern as delivered_at/claimed_at above.
                    aq = ("SELECT date_trunc('hour', created_at) AS h, count(*) AS n FROM sync_ledger "
                          "GROUP BY 1 ORDER BY 1;")
                    ar = psql_csv(ledger_container, args.ledger_db, args.ledger_user, aq)
                    print("  arrivals per hour (created_at):")
                    for r in ar:
                        print(f"    {r['h']}  {r['n']}")
                    if "delivered_at" in colnames:
                        bq = ("SELECT date_trunc('hour', h) AS bucket, "
                              "count(*) FILTER (WHERE created_at <= h) - "
                              "count(*) FILTER (WHERE delivered_at IS NOT NULL AND delivered_at <= h) AS backlog_depth "
                              "FROM sync_ledger, generate_series(now() - interval '8 hours', now(), interval '1 hour') h "
                              "GROUP BY 1 ORDER BY 1;")
                        br = psql_csv(ledger_container, args.ledger_db, args.ledger_user, bq)
                        print("  backlog depth over last 8h (created but not yet delivered, as of each hour mark):")
                        for r in br:
                            print(f"    {r['bucket']}  {r['backlog_depth']}")
                    sq = ("SELECT date_trunc('hour', created_at) AS h, "
                          "percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM delivered_at-created_at)) AS median_s "
                          "FROM sync_ledger WHERE delivered_at IS NOT NULL GROUP BY 1 ORDER BY 1;")
                    sr = psql_csv(ledger_container, args.ledger_db, args.ledger_user, sq)
                    if sr:
                        print("  median time-to-delivery per hour (created_at -> delivered_at, seconds):")
                        for r in sr:
                            v = r.get("median_s")
                            print(f"    {r['h']}  {float(v):.0f}s" if v not in (None, "") else f"    {r['h']}  n/a")
                else:
                    print("  NOTE: sync_ledger has no created_at / status-change history yet, so true")
                    print("  queue-depth-over-time cannot be reconstructed from it alone - this is a")
                    print("  point-in-time + cumulative-delivery view, not a backlog time series.")
                    print("  See scripts/ops/migrations/2026-08-06_sync_ledger_created_at.sql - additive,")
                    print("  safe, and once applied this section reports real backlog-depth-over-time.")
        except RuntimeError as e:
            print(f"  ledger query failed ({e}) - skipped.")
    print()

    print("## Summary")
    print(f"Utilisation: {100*util_avg/pool_size:.1f}% average ({util_avg:.1f}/{pool_size} slots busy)")
    print(f"Idle-while-backlog: {fmt_dur(idle_slot_seconds_backlog)} slot-time (~{lost_docs_per_hour:.1f} docs/hour opportunity)")
    print(f"Schedule dead-time: ~{fmt_dur(total_dead_hr)}/hour across fixed-interval pipes")
    print(f"Zombies right now: {len(zombies)} (~{100*len(zombies)/pool_size:.0f}% of pool if held)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
