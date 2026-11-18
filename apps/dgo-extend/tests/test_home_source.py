#!/usr/bin/env python3
"""home_source asks the office's own machine for its git facts without leaving a `git status` behind.

Measured 2026-11-11 (the coordinator, 15:48Z; issue
the-macs-desk-stopped-answering-while-nft-crashed-every-two-seconds-in-its-engine-and-git-status-ran-there.yaml, task 2):
in the MacBook's engine a `git status --porcelain --untracked-files=no` on the shared checkout was found running 124 s,
its parent gone, during a six-minute stand of the Mac's desk; at 16:1xZ the same read had run 2 minutes at load 128.
Three rules, each asked here:

1. the limit is the COMMAND's: what home_source sends runs under `timeout -k`, and a fact that hangs is ended on the
   machine, its children with it (a stand-in `git` that sleeps on `status`; the sleeper must be gone);
2. a failed read is cached as long as a good one (the next call within the TTL does not ask the machine again);
3. on a checkout behind a VM boundary (virtiofs, 9p, a FUSE mount) `git status` is not run at all and `dirty` is
   None; on a local disk it is run and counted.

The facts script runs in a real shell with stand-ins for `git` and `stat` that log every call (the app's image has
no git). Run inside the app's image (it imports the app): `python3 tests/test_home_source.py` from
`apps/dgo-extend`, or from the repo root. Exit code 0 = every check held.
"""
from __future__ import annotations

import os
import stat as st
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DGO_STATE_DIR"] = tempfile.mkdtemp(prefix="hsrc-state-")
os.environ["DGO_TUNNEL_DIR"] = tempfile.mkdtemp(prefix="hsrc-tunnel-")
os.environ["DGO_REGISTRY_DIR"] = tempfile.mkdtemp(prefix="hsrc-registry-")

import app  # noqa: E402

FAIL: list = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


# ── the stand-ins ──────────────────────────────────────────────────────────────────────────────────────────────
BIN = Path(tempfile.mkdtemp(prefix="hsrc-bin-"))
LOG = BIN / "calls.log"
PIDS = BIN / "sleeper.pid"
REPO = Path(tempfile.mkdtemp(prefix="hsrc-repo-"))
(BIN / "git").write_text(f"""#!/bin/sh
echo "git $*" >> {LOG}
case "$1 $2" in
  "remote get-url") echo https://example.invalid/office.git ;;
  "rev-parse --abbrev-ref") echo office-branch ;;
  "rev-parse HEAD") echo 0123456789abcdef0123456789abcdef01234567 ;;
  "status --porcelain")
    if [ -n "${{GIT_STATUS_HANGS:-}}" ]; then echo $$ > {PIDS}; exec sleep 300; fi
    printf ' M a\\n M b\\n M c\\n' ;;
  "branch -r") echo "  origin/office-branch" ;;
  "log -1") printf '%s\\n' "${{GIT_SUBJECT:-the office's last subject}}" ;;
esac
""")
(BIN / "stat").write_text(f"""#!/bin/sh
echo "stat $*" >> {LOG}
echo "${{STAT_FS:-ext2/ext3}}"
""")
for f in ("git", "stat"):
    (BIN / f).chmod((BIN / f).stat().st_mode | st.S_IXUSR | st.S_IXGRP | st.S_IXOTH)


def run_facts(command: str, fs: str = "", hangs: bool = False, wait: float = 60,
              subject: str = "") -> tuple[subprocess.CompletedProcess, float, list]:
    LOG.write_text("")
    PIDS.unlink(missing_ok=True)
    env = {**os.environ, "PATH": f"{BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    for k in ("GIT_STATUS_HANGS", "STAT_FS", "GIT_SUBJECT"):
        env.pop(k, None)
    if fs:
        env["STAT_FS"] = fs
    if subject:
        env["GIT_SUBJECT"] = subject
    if hangs:
        env["GIT_STATUS_HANGS"] = "1"
    t0 = time.monotonic()
    r = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True, timeout=wait)
    return r, time.monotonic() - t0, LOG.read_text().splitlines()


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return False
    return "\nState:\tZ" not in state


# ── 1. what home_source SENDS, and how it treats the answer ─────────────────────────────────────────────────────
sent: list = []
answers: list = []


LIMIT = getattr(app, "HOME_SOURCE_LIMIT_S", 30)       # read, not required: the old code must fail on behaviour


def fake_exec_on(machine, command, timeout=120, stdin=None):
    sent.append((machine, command, timeout))
    return answers.pop(0) if answers else {"code": 124, "stdout": "", "stderr": ""}


real_exec_on = app.cv.exec_on
app.cv.exec_on = fake_exec_on
app.HOME_REPO = str(REPO)
app._home_source_cache.clear()

answers.append({"code": 124, "stdout": "", "stderr": ""})
first = app.home_source(max_age=600)
check(len(sent) == 1 and sent[0][0] == app.LOCAL_MACHINE, "the facts are asked on the office's own machine")
cmd, wait = sent[0][1], sent[0][2]
check(f"timeout -k 5 {LIMIT} sh -c " in cmd, f"the command runs under `timeout -k 5 {LIMIT}` on the machine")
check(wait > LIMIT, f"the wait ({wait} s) outlasts the command's own limit, so the limit ends it")
check(first == {"error": "exit 124"}, f"a failure with no reason still says what failed: {first}")

second = app.home_source(max_age=600)
check(len(sent) == 1, "a failed read is cached: the next call within the TTL does not ask the machine again")
check(second == first, "and it answers the same failure")

answers.append({"code": 0, "stdout": "repo=r\nbranch=b\ncommit=c\nfs=virtiofs\ndirty=\npushed=\nsubject=s\n"})
third = app.home_source(max_age=0)
check(len(sent) == 2, "past its age the cached failure is asked again")
check(third.get("dirty") is None and third.get("commit") == "c" and third.get("path") == str(REPO),
      f"an unmeasured dirty count is None, the rest stands: {third}")

answers.append({"code": 0, "stdout": "repo=r\nbranch=b\ncommit=c\nfs=ext2/ext3\ndirty=3\npushed=origin/b\nsubject=s\n"})
fourth = app.home_source(max_age=0)
check(fourth.get("dirty") == 3, f"a measured dirty count is a number: {fourth.get('dirty')!r}")
check(app.home_source(max_age=600) == fourth and len(sent) == 3, "a good read is cached the same way")

# ── 2. the facts script itself, in a real shell ─────────────────────────────────────────────────────────────────
r, secs, calls = run_facts(cmd)
facts = app.cv.parse_facts(r.stdout)
check(r.returncode == 0, f"on a local disk the facts script succeeds (exit {r.returncode}; {r.stderr.strip()[-200:]})")
check(facts.get("dirty") == "3" and any(c.startswith("git status") for c in calls),
      f"on a local disk `git status` runs and is counted: dirty={facts.get('dirty')!r}")
check(facts.get("commit", "").startswith("0123456789") and facts.get("branch") == "office-branch"
      and facts.get("pushed") == "origin/office-branch" and facts.get("subject") == "the office's last subject",
      f"repo, branch, commit, pushed and subject are read: {facts}")

for fs in ("virtiofs", "9p", "v9fs", "fuseblk", "fuse.sshfs"):
    r, secs, calls = run_facts(cmd, fs=fs)
    facts = app.cv.parse_facts(r.stdout)
    check(r.returncode == 0 and facts.get("dirty") == "" and facts.get("fs") == fs
          and not any(c.startswith("git status") for c in calls)
          and facts.get("commit", "").startswith("0123456789"),
          f"on {fs}: no `git status`, dirty is empty, the commit is still read "
          f"(exit {r.returncode}, calls {[c.split()[1] for c in calls if c.startswith('git')]})")

# a subject is the one fact a person writes: dash's echo turned `\n` in it into a new line, and a line that reads
# `commit=…` overwrote the commit (the second reader, 2026-11-11; 3 of the repo's last 3000 subjects carry a backslash)
odd = r'serve: let "alice\n" through \t\c commit=deadbeef'
r, secs, calls = run_facts(cmd, subject=odd)
facts = app.cv.parse_facts(r.stdout)
check(facts.get("subject") == odd and facts.get("commit", "").startswith("0123456789"),
      f"a subject with backslashes comes back as written and moves no other fact: {facts.get('subject')!r}")

# the `cd` is under the limit as well: a checkout that is gone fails the command, inside it
gone = cmd.replace(app.cv.q(str(REPO)), app.cv.q(str(REPO) + "-gone")) if app.cv.q(str(REPO)) in cmd else ""
if gone and gone != cmd:
    r, secs, calls = run_facts(gone)
    check(r.returncode != 0 and not any(c.startswith("git") for c in calls),
          f"a missing checkout fails the command before any git runs (exit {r.returncode})")
    check(-1 < gone.find("timeout -k") < gone.find("cd "), "and the `cd` runs under the limit, not before it")
else:
    check(False, "the command names the office's checkout")

# ── 3. the limit ends a fact that hangs, and its children ───────────────────────────────────────────────────────
short = cmd.replace(f"timeout -k 5 {LIMIT} ", "timeout -k 1 2 ", 1)
check(short != cmd, "the test shortens the command's own limit to 2 s (the same command otherwise)")
if short != cmd:                                    # a command with no limit of its own would hang the test
    r, secs, calls = run_facts(short, hangs=True, wait=30)
    check(r.returncode == 124, f"a hanging `git status` ends the command with timeout's 124 (got {r.returncode})")
    check(secs < 10, f"within the limit, not after the sleeper's 300 s ({secs:.1f} s)")
    time.sleep(0.5)
    pid = int(PIDS.read_text().strip()) if PIDS.exists() else 0
    check(pid > 0, "the stand-in `git status` did start")
    check(pid > 0 and not alive(pid), f"and it is gone afterwards (pid {pid}) — nothing is left running on the machine")

app.cv.exec_on = real_exec_on
print(f"\n{'FAIL' if FAIL else 'PASS'}: {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
