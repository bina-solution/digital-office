#!/usr/bin/env python3
"""checkout-owner-lint — gate G94: the checkout's owner can write every path a session writes (DGO-1324).

    python3 scripts/refactor/checkout-owner-lint.py            count, and fail on any
    python3 scripts/refactor/checkout-owner-lint.py --paths0   the same paths, NUL-separated and relative to the
                                                               checkout, for `xargs -0 chown -h` (DGO-1322's one-off)
    python3 scripts/refactor/checkout-owner-lint.py --self-test

The office checkout belongs to a user (the uid:gid of .git), and the sessions that edit it run as that user. Root
writers (bina-ds, the follow cycle, the bina-claude terminal) used to leave what git (re)created as root's: on the HP,
2026-11-03, 1183 paths under .git/objects and ~1400 tracked sources, and every one of them was a session that could
not save, commit or merge. scripts/checkout-owner.sh is the fix; this is its measure.

What is counted — exactly the paths a session must write, and nothing a session should not:
  * every TRACKED file and its directories, that the owner cannot write;
  * .git's own files and directories (index, HEAD, refs, logs, the object DIRECTORIES) that it cannot write.
    A loose object or a pack is read-only to everyone by design — it is only ever replaced, which its directory allows.
"Cannot write" = owned by another uid AND not group-writable in the owner's group. What `bbox run` writes UNTRACKED
(.generated/, data/, ci-artifacts/) is not counted: sessions do not edit it, and data/ may hold files that must stay
root's. A tracked file under those directories is counted like any other.

A checkout that root owns, or one where every path has one owner (CI, a fresh clone), passes by construction.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
#: --paths0 writes ONLY paths to stdout (they go to `xargs -0 chown`): every sentence goes to stderr then
SAY = sys.stderr if "--paths0" in sys.argv else sys.stdout


def blocked(st: os.stat_result, uid: int, gid: int) -> bool:
    """Can the owner (uid, gid) NOT write this path?"""
    if st.st_uid == uid:
        return False
    return not (st.st_gid == gid and st.st_mode & stat.S_IWGRP)


def git_paths(gitdir: str):
    """.git's own entries a session writes: everything but the objects themselves (their directories, yes)."""
    for dirpath, dirnames, filenames in os.walk(gitdir):
        yield dirpath
        rel = os.path.relpath(dirpath, gitdir)
        if rel == "objects" or rel.startswith("objects" + os.sep):
            continue                                        # loose objects and packs are read-only by design
        for f in filenames:
            yield os.path.join(dirpath, f)


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    # the COMMON git dir: in a linked worktree (a gates probe) ROOT/.git is a file, and the office's is elsewhere
    got = subprocess.run(["git", "-c", "safe.directory=*", "-C", ROOT, "rev-parse", "--path-format=absolute",
                          "--git-common-dir"], capture_output=True, text=True)
    gitdir = got.stdout.strip()
    try:
        g = os.stat(gitdir) if got.returncode == 0 and gitdir else None
    except OSError:
        g = None
    if g is None:
        print("G94 SKIP — no git checkout here (an exported tree has no checkout owner)", file=SAY)
        return 0
    uid, gid = g.st_uid, g.st_gid
    if uid == 0:
        print("G94 PASS — the checkout belongs to root; there is no other owner to block", file=SAY)
        return 0
    # safe.directory: run as root on a checkout another uid owns, git would refuse to list it
    try:
        files = subprocess.run(["git", "-c", "safe.directory=*", "-C", ROOT, "ls-files", "-z"], capture_output=True,
                               check=True).stdout.split(b"\0")
    except subprocess.CalledProcessError as e:
        print(f"G94 FAIL — git refused to list the tracked files: {(e.stderr or b'').decode(errors='replace')[:200]}",
              file=SAY)
        return 1
    paths, seen = [], set()
    for rel in filter(None, files):
        p = os.path.join(ROOT, rel.decode("utf-8", "surrogateescape"))
        while p not in seen and p.startswith(ROOT + os.sep):
            seen.add(p)
            paths.append(p)
            p = os.path.dirname(p)
    n_tracked = len(paths)
    paths += list(git_paths(gitdir))
    bad = []
    for p in paths:
        try:
            if blocked(os.lstat(p), uid, gid):
                bad.append(os.path.relpath(p, ROOT))
        except OSError:
            continue
    if "--paths0" in sys.argv:
        # exactly what is counted, for the one-off: nothing hand-picked, nothing beyond the gate's own reach
        sys.stdout.buffer.write(b"".join(os.fsencode(b) + b"\0" for b in bad))
        return 0
    print(f"checkout-owner-lint — G94: owner {uid}:{gid}; {n_tracked} tracked path(s) and {len(paths) - n_tracked} "
          f"of .git's own read")
    if not bad:
        print("G94 PASS — the checkout's owner can write every path a session writes")
        return 0
    groups = Counter(b.split(os.sep)[0] + ("/" + b.split(os.sep)[1] if b.split(os.sep)[0] in (".git", "apps", "platform-base") and os.sep in b else "") for b in bad)
    print(f"G94 FAIL — {len(bad)} path(s) the checkout's owner cannot write (another uid, not group-writable in {gid}):")
    for k, v in groups.most_common(15):
        print(f"  {v:>6}  {k}")
    for b in bad[:10]:
        print(f"         e.g. {b}")
    print("  The writers keep it from coming back (scripts/checkout-owner.sh, set up by `bbox run`); what is already\n"
          "  there is a one-off as root: chown the listed paths to the owner (DGO-1322).")
    return 1


def self_test() -> int:
    mk = lambda uid, gid, mode: os.stat_result((mode, 0, 0, 1, uid, gid, 0, 0, 0, 0))   # noqa: E731
    cases = [
        ("the owner's file", mk(1000, 1000, 0o100644), False),
        ("root's file, root's group", mk(0, 0, 0o100644), True),
        ("root's file, owner's group, not group-writable", mk(0, 1000, 0o100644), True),
        ("root's file, owner's group, group-writable (git's shared mode)", mk(0, 1000, 0o100664), False),
        ("root's dir, owner's group, setgid + group-writable", mk(0, 1000, 0o42775), False),
        ("root's file, another group, group-writable", mk(0, 0, 0o100664), True),
    ]
    fails = 0
    for name, st, want in cases:
        got = blocked(st, 1000, 1000)
        fails += got != want
        print(("ok   " if got == want else "FAIL ") + name)
    print(f"G94 self-test {'PASS' if not fails else 'FAIL'} — {len(cases) - fails}/{len(cases)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
