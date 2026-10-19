#!/usr/bin/env python3
"""
execution-watchdog.py — safe reaper for zombie n8n `execution_entity` rows.

THE GAP THIS CLOSES (2026-08-06): syncLedgerApi01's Reaper (every 5min) already clears stuck
`sync_ledger` claims. Nothing plays the same role for n8n's OWN `execution_entity` table: a row can
sit `status='running'` forever if the worker that owned it dies without n8n's crash-recovery running
(that recovery only fires on n8n container START, not continuously) - 34 executions were observed
stuck `running` on 2026-08-05 and only cleared because the stack happened to restart. A zombie
execution holds a conceptual "slot" (it reads as in-flight work to any human or dashboard looking at
`execution_entity`) even though nothing is actually processing it.

SAFETY MODEL — do not just trust a timestamp. n8n runs in queue mode (BullMQ over Redis): every
in-flight execution has a corresponding job in `bull:jobs:active` (or `:wait`/`:delayed` if not yet
picked up), and that job's `data` field carries the exact same execution id
(`{"workflowId":...,"executionId":"104955",...}`) - confirmed live against this deployment's own
Redis. So "old timestamp" alone is only a CANDIDATE; a row is only ever treated as a confirmed
zombie when its execution id is ALSO absent from every live Bull job list. An execution that is
still genuinely processing always has a live Bull job, at any age - a 45+ minute real run is
completely indistinguishable from a "stuck" one by age alone, which is exactly why age is never
sufficient by itself here.

This script is READ-ONLY / report-only by default. Pass --apply to actually clear confirmed
zombies (UPDATE execution_entity SET status='crashed' ... WHERE status='running' — the same
terminal status n8n's own crash-recovery already uses for orphaned executions, so this does not
invent new vocabulary). Every run also prints which candidates were found NOT to be zombies (still
present in a live Bull list) and left untouched — that list is the running, mechanical proof this
script cannot kill live work, not a one-off manual claim.

Usage:
    export DOCKER_HOST=unix:///run/bbox-docker.sock
    python3 scripts/ops/execution-watchdog.py --minutes 45              # dry run (default)
    python3 scripts/ops/execution-watchdog.py --minutes 45 --apply      # actually clear confirmed zombies
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


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


def redis_password(repo_root: str) -> str:
    try:
        with open(f"{repo_root}/.env", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REDIS_PASSWORD="):
                    return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    raise RuntimeError("REDIS_PASSWORD not found in .env — cannot safely authenticate to Redis")


def redis_cli(container: str, password: str, *args: str) -> str:
    quoted = " ".join(f"'{a}'" if " " not in a else f'"{a}"' for a in args)
    cmd = f"docker exec {container} redis-cli --no-auth-warning -a '{password}' {quoted}"
    return sh(cmd)


def psql_rows(container: str, db: str, user: str, query: str) -> list[dict]:
    import csv
    import io
    query_escaped = query.replace('"', '\\"')
    cmd = f'docker exec {container} psql -U {user} -d {db} --csv -c "{query_escaped}"'
    out = sh(cmd)
    reader = csv.DictReader(io.StringIO(out))
    return list(reader)


def psql_exec(container: str, db: str, user: str, query: str) -> str:
    query_escaped = query.replace('"', '\\"')
    cmd = f'docker exec {container} psql -U {user} -d {db} -tAc "{query_escaped}"'
    return sh(cmd)


def live_bull_execution_ids(redis_container: str, password: str) -> set[str]:
    """Every execution id currently referenced by a live Bull job, across active/wait/delayed."""
    ids: set[str] = set()
    for list_key in ("bull:jobs:active", "bull:jobs:wait", "bull:jobs:waiting", "bull:jobs:delayed"):
        try:
            out = redis_cli(redis_container, password, "LRANGE", list_key, "0", "-1")
        except RuntimeError:
            continue
        job_ids = [j.strip() for j in out.splitlines() if j.strip()]
        for jid in job_ids:
            try:
                data = redis_cli(redis_container, password, "HGET", f"bull:jobs:{jid}", "data")
            except RuntimeError:
                continue
            data = data.strip()
            if not data:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            eid = parsed.get("executionId")
            if eid is not None:
                ids.add(str(eid))
    return ids


def docker_daemon_line() -> str:
    """Docker daemon start time + age, for the report header.

    Added 2026-08-06. This watchdog clears executions stuck in 'running'. The single largest
    producer of those on this deployment is not a wedged workflow — it is the docker daemon
    restarting and orphaning everything in flight. Measured on 2026-08-05/06: 24 daemon starts
    and 7 WSL2 VM kernel boots between 22:00 and 03:35, with zero graceful docker stops logged.
    n8n stamps the orphans "Workflow did not finish, possible out-of-memory issue", which is not
    an OOM and has repeatedly been read as one.

    Printing the daemon's start timestamp next to this run's findings means anyone reading the
    output can tell in one line whether the zombies it just cleared were a workflow defect or
    simply the stack having been restarted underneath them.
    """
    try:
        ts = subprocess.run(
            ["systemctl", "show", "docker", "-p", "ExecMainStartTimestamp", "--value"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "docker daemon: NOT VERIFIED (systemctl unavailable)"
    if not ts:
        return "docker daemon: NOT VERIFIED (no ExecMainStartTimestamp)"
    age = ""
    try:
        epoch = subprocess.run(["date", "-d", ts, "+%s"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
        if epoch:
            mins = (int(datetime.now(timezone.utc).timestamp()) - int(epoch)) // 60
            age = f"  (up {mins}m)"
            if mins < 10:
                age += "  <-- RESTARTED IN THE LAST 10 MINUTES: expect orphaned executions below;" \
                       " they are not workflow defects"
    except Exception:
        pass
    return f"docker daemon started: {ts}{age}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=int, default=45,
                     help="candidate threshold: status='running' older than this many minutes "
                          "(default 45 — comfortably beyond every real runtime measured on this "
                          "deployment so far, including the 1223s/20m worst-case healthy Sync v3 "
                          "Reconcile pass and the 1849s/31m worst-case restart-orphaned one)")
    ap.add_argument("--apply", action="store_true",
                     help="actually clear confirmed zombies (default: dry run / report only)")
    ap.add_argument("--n8n-container", type=str, default="n8n-postgres")
    ap.add_argument("--n8n-db", type=str, default="n8n")
    ap.add_argument("--n8n-user", type=str, default="hacohen")
    ap.add_argument("--redis-container", type=str, default="redis")
    ap.add_argument("--repo-root", type=str, default=".")
    args = ap.parse_args()

    n8n_pg = find_container(args.n8n_container)
    redis_c = find_container(args.redis_container)
    password = redis_password(args.repo_root)

    now = datetime.now(timezone.utc)
    print("================================================================")
    print(f"execution-watchdog  {now.strftime('%Y-%m-%dT%H:%M:%SZ')}  "
          f"threshold={args.minutes}m  mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"n8n_pg={n8n_pg}  redis={redis_c}")
    print(docker_daemon_line())
    print("================================================================")

    # mode='integrated' rows are Execute-Workflow sub-calls that run INSIDE their caller's own Bull
    # job (n8n does not queue them separately - same fact scripts/ops/timeline-gaps.py's slot-occupancy
    # sweep already relies on). They therefore NEVER appear in bull:jobs:active/wait/delayed on their
    # own, by construction - checking for their absence proves nothing about whether they're really
    # stuck. CAUGHT LIVE (2026-08-06) during the safety proof run below: with this filter absent, a
    # perfectly healthy in-flight 'Incoming Documents v2' integrated sub-call was misclassified as a
    # "confirmed zombie" on 6 consecutive checks while it was still genuinely running. Restricting
    # candidates to the same slot-occupying modes timeline-gaps.py already uses (trigger/webhook/
    # manual/error/retry/cli) is the fix: a truly-stuck integrated call is a symptom of its top-level
    # ancestor execution being stuck, and that ancestor - not the integrated child - is what this
    # watchdog targets and can safely corroborate.
    SLOT_MODES = ("trigger", "webhook", "manual", "error", "retry", "cli")
    mode_list = ",".join(f"'{m}'" for m in SLOT_MODES)
    candidates = psql_rows(
        n8n_pg, args.n8n_db, args.n8n_user,
        "select e.id, e.\"workflowId\", w.name as workflow_name, e.\"startedAt\", e.mode, "
        "extract(epoch from (now()-e.\"startedAt\"))/60 as age_min "
        "from execution_entity e left join workflow_entity w on w.id=e.\"workflowId\" "
        f"where e.status='running' and e.mode in ({mode_list}) "
        f"and e.\"startedAt\" < now() - interval '{args.minutes} minutes' "
        "order by e.\"startedAt\""
    )
    print(f"\nCandidates (status='running', older than {args.minutes}m): {len(candidates)}")
    if not candidates:
        print("Nothing to check — no execution has been 'running' longer than the threshold. Exiting clean.")
        return

    live_ids = live_bull_execution_ids(redis_c, password)
    print(f"Execution ids currently referenced by a live Bull job (active/wait/delayed): {len(live_ids)}")

    zombies = []
    proven_live = []
    for c in candidates:
        eid = str(c["id"])
        if eid in live_ids:
            proven_live.append(c)
        else:
            zombies.append(c)

    print(f"\n--- PROVEN LIVE (age alone said 'old', a live Bull job says otherwise — left untouched): {len(proven_live)} ---")
    for c in proven_live:
        print(f"  KEPT   exec {c['id']:>7s}  {c.get('workflow_name') or c['workflowId']:35s}  "
              f"age={float(c['age_min']):.1f}min  mode={c['mode']}  -> still has a live Bull job, not a zombie")

    print(f"\n--- CONFIRMED ZOMBIES (old AND no live Bull job in active/wait/delayed): {len(zombies)} ---")
    for c in zombies:
        print(f"  {'CLEARED' if args.apply else 'WOULD-CLEAR'}  exec {c['id']:>7s}  "
              f"{c.get('workflow_name') or c['workflowId']:35s}  age={float(c['age_min']):.1f}min  mode={c['mode']}  "
              f"started={c['startedAt']}")

    if not zombies:
        print("\nNo confirmed zombies this run. (Candidates existed but every one still has a live Bull job —")
        print("this is exactly the 'do not kill live work' guard doing its job, not a bug.)")
        return

    if not args.apply:
        print(f"\nDRY RUN — {len(zombies)} confirmed zombie(s) would be cleared. Re-run with --apply to clear them.")
        return

    cleared = 0
    for c in zombies:
        # Re-check status in the WHERE clause: if it transitioned away from 'running' between
        # detection and this UPDATE (e.g. it just now finished, or another process already reaped
        # it), the UPDATE simply matches zero rows — safe, idempotent, no race.
        res = psql_exec(
            n8n_pg, args.n8n_db, args.n8n_user,
            f"update execution_entity set status='crashed', \"stoppedAt\"=coalesce(\"stoppedAt\", now()) "
            f"where id={int(c['id'])} and status='running' returning id"
        )
        if res.strip():
            cleared += 1
            print(f"  cleared exec {c['id']}")
        else:
            print(f"  exec {c['id']} no longer matched status='running' at update time — skipped (safe no-op)")

    print(f"\nCleared {cleared}/{len(zombies)} confirmed zombies. "
          f"{len(proven_live)} candidate(s) proven live and left running.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
