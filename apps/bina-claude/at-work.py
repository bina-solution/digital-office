#!/usr/bin/env python3
"""at-work.py count|ids — the Claude sessions at work in this desktop (run inside it, where its home is /config).

The office asks it before it recreates the desktop (hooks/busy, DGO-2129), and before-recreate notes with it whom to
resume. Claude Code keeps one file per running session, .claude/sessions/<pid>.json, and a file counts only while its
process runs: the pid's start tick in /proc is the file's own `procStart`. So a session whose process died, or a pid
the kernel has since given to another process, is not taken for one at work. Measured on the HP, 2026-11-20: 31 files,
12 of them alive. One dead file still said `busy`, and the adapter's count, which reads the status alone, counted it as
at work for good: the office would never have found the desktop idle. A file without `procStart` counts while its pid
started no later than its `startedAt` + 60 s (measured: 5–22 s before it).
The rest is the adapter's rule (adapter/server.mjs `live`):
  * a file from before the running app's SingletonLock (minus 5 s) is from a life that is over;
  * of two files for one session, the newer counts;
  * a session is at work while its status is busy (a turn runs) or waiting (a question is open, still inside the turn).
One more, which the status cannot show: a session whose turn ended while work it started still runs is at work too.
That is its background Bash or Monitor jobs, each a shell under its process (`bash -c source …/.claude/shell-snapshots/…`).
Its status says idle, and a recreate kills the job and leaves it waiting for a notice that never comes; gates and builds
run that way (DGO-2129's second reader, measured on the HP: an idle session with a `sleep 60` watcher under it).
A file that cannot be read twice in a row, while its process runs, is counted as at work: a recreate is never taken on
a guess.
    count → the number at work · ids → their session ids (local_…), one per line
"""
import glob
import json
import os
import sys
import time

HOME = os.environ.get("CLAUDE_DESKTOP_HOME", "/config")


def start_tick(pid):
    """The kernel's start tick of process <pid> (/proc/<pid>/stat, field 22), or None when it does not run."""
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="ascii", errors="replace") as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def runs(pid, j):
    tick = start_tick(pid)
    if tick is None:
        return False
    if j.get("procStart") is not None:
        return str(j["procStart"]) == str(tick)
    try:
        with open("/proc/stat", encoding="ascii") as fh:
            boot = next(int(line.split()[1]) for line in fh if line.startswith("btime "))
        return boot + tick / os.sysconf("SC_CLK_TCK") <= (j.get("startedAt") or 0) / 1000 + 60
    except (OSError, ValueError, StopIteration):
        return True                                    # it runs, and when it started cannot be read


def with_jobs():
    """The pids that have a shell of the Claude app's tools under them (a Bash or Monitor job still running)."""
    parent, jobs = {}, []
    for d in glob.glob("/proc/[0-9]*"):
        pid = d[len("/proc/"):]
        try:
            with open(f"{d}/stat", encoding="ascii", errors="replace") as fh:
                parent[pid] = fh.read().rsplit(")", 1)[1].split()[1]
            with open(f"{d}/cmdline", "rb") as fh:
                if b"/.claude/shell-snapshots/" in fh.read():
                    jobs.append(pid)
        except (OSError, IndexError):
            continue                                   # it ended meanwhile
    found = set()
    for pid in jobs:
        seen = 0
        while pid in parent and pid not in ("0", "1") and seen < 64:
            pid, seen = parent[pid], seen + 1
            found.add(pid)
    return found


def read(f):
    for _ in range(2):
        try:
            with open(f, encoding="utf-8") as fh:
                j = json.load(fh)
            return j if isinstance(j, dict) else {}
        except ValueError:
            time.sleep(0.2)                            # mid-write
        except OSError:
            return None                                # gone: the session ended
    return {}


def at_work():
    """(the ids of the sessions at work, how many more are at work without an id)."""
    try:
        since = os.lstat(os.path.join(HOME, ".config/Claude/SingletonLock")).st_mtime * 1000 - 5000
    except OSError:
        since = 0
    live, unknown, jobs = {}, 0, with_jobs()
    for f in glob.glob(os.path.join(HOME, ".claude/sessions/*.json")):
        pid = os.path.basename(f)[:-len(".json")]
        j = read(f)
        if j is None:
            continue
        if not j:
            unknown += start_tick(pid) is not None     # unreadable: at work while its process runs
            continue
        sid, started = j.get("hostSessionId"), j.get("startedAt") or 0
        if since and started < since:
            continue
        if not runs(j.get("pid") or pid, j):
            continue
        key = sid or f"pid:{pid}"                      # a session the app did not start counts, and cannot be resumed
        if key not in live or started > (live[key].get("startedAt") or 0):
            live[key] = dict(j, _jobs=str(j.get("pid") or pid) in jobs)
    busy = sorted(k for k, j in live.items() if j.get("status") in ("busy", "waiting") or j["_jobs"])
    return [k for k in busy if not k.startswith("pid:")], unknown + sum(k.startswith("pid:") for k in busy)


if __name__ == "__main__":
    ids, more = at_work()
    if sys.argv[1:] == ["ids"]:
        print("\n".join(ids))
    else:
        print(len(ids) + more)
