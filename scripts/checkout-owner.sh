#!/usr/bin/env bash
# checkout-owner.sh — what root writes in the office checkout stays usable by the checkout's owner (DGO-1324).
#
#     scripts/checkout-owner.sh setup        what `bbox run` declares: git's shared mode, the hooks, .git's group bits
#     scripts/checkout-owner.sh restore      (the git hooks, follow.sh) give the owner the paths on stdin, NUL-separated
#
# WHY. The checkout belongs to a user (the uid:gid of .git — 1000 on the HP), and the sessions that edit it run as that
# user. Three writers run as root: bina-ds's `bbox` and git (no `user:`), the follow cycle (root by design) and the
# bina-claude terminal. Every file git (re)created as root — a merge, a checkout, a commit — became root's, and blocked
# the next session that had to write it: 1183 paths under .git/objects and ~1400 tracked sources on the HP, measured
# 2026-11-03 (2572 of them from one day of merges). A one-off chown fixes a day; this fixes the writers.
#
# HOW, cheaply (a walk of .git costs 21 s on the HP's mount, so nothing walks per operation):
#   .git      git's own `core.sharedRepository=group` + setgid directories in the owner's group: what git creates there
#             is group-writable in that group, whoever runs it. The one walk that gives the existing directories the
#             bit happens only while .git's top directory lacks it — and sets that bit LAST, so a walk that failed
#             halfway is done again.
#   worktree  the hooks (scripts/git-hooks) and follow.sh's resets hand this script exactly the paths an operation
#             wrote; it gives the ones root owns (and the directories root made for them) back. A list, never a walk.
#             Each path is walked from the checkout's top WITHOUT following a symlink anywhere in it: a tracked
#             symlink (`x` → /etc) must never make root chown /etc/shadow (the second reader, DGO-1324).
# A checkout that root owns (.git's uid is 0), or a run that is not root, has nothing to do here.
set -uo pipefail
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
# CDPATH cleared: with one exported, bash's `cd` prints where it went, and GITDIR became two lines — a hooksPath git
# reads as no hooks at all, which nothing repaired (the reader of v4)
GITDIR="$(CDPATH='' cd -- "${TOP}" && CDPATH='' cd -P -- "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)" \
  || exit 0
case "${GITDIR}" in
  *$'\n'*|"") echo "[checkout-owner] the checkout's .git could not be named: the office's git hooks are not wired" >&2
              exit 0 ;;
esac
# uid:gid of .git, by GNU stat; empty where there is none (a macOS host: the owner's chown work is the guest's)
OWNER="$(stat -c %u:%g "${GITDIR}" 2>/dev/null || true)"
OUID="${OWNER%%:*}"; OGID="${OWNER##*:}"

case "${1:-}" in
  setup)
    # the office's own hooks FIRST, on every checkout — whoever owns it and whatever `stat` this host has: the branch
    # rule is not the owner's chown business (the reader of v3: a macOS or root-owned checkout was never wired).
    # Unless the checkout already names other hooks (never overridden). The MAIN checkout's, by an absolute path: a
    # relative one is read from each worktree's top, where an older commit has no hook (DGO-1764).
    hp="$(git -C "${TOP}" config --type=path --get core.hooksPath || true)"     # `~/…` read as git reads it
    want="$(dirname "${GITDIR}")/scripts/git-hooks"
    # unset, the old relative one, or OUR OWN broken write (two lines, or a …/scripts/git-hooks that holds no hook) —
    # never another office's own value (setup ships in the same commit as the hooks it points at)
    ours_broken=""
    case "${hp}" in
      *$'\n'*) ours_broken=1 ;;
      */scripts/git-hooks) [ -f "${hp}/reference-transaction" ] || [ "${hp}" = "${want}" ] || ours_broken=1 ;;
    esac
    if [ -z "${hp}" ] || [ "${hp}" = scripts/git-hooks ] || [ -n "${ours_broken}" ]; then
      git -C "${TOP}" config --replace-all core.hooksPath "${want}"
    elif [ "${hp}" != "${want}" ]; then
      # said, never overridden: another hooks path (this checkout's, or a global one) keeps the branch rule off
      echo "[checkout-owner] core.hooksPath is ${hp}: the office's git hooks (${want}) are not wired here" >&2
    fi
    [ -n "${OWNER}" ] && [ "${OUID}" != 0 ] || exit 0
    [ "$(git -C "${TOP}" config --get core.sharedRepository)" = group ] || git -C "${TOP}" config core.sharedRepository group
    if [ "$(id -u)" = 0 ] && [ ! -g "${GITDIR}" ]; then
      # once: .git's entries take the owner's group and become group-writable, its directories setgid — the top one
      # last, because its bit is what says the walk is done
      chgrp -R "${OGID}" "${GITDIR}" && chmod -R g+w "${GITDIR}" \
        && find "${GITDIR}" -xdev -mindepth 1 -type d -exec chmod g+s {} + \
        && chmod g+s "${GITDIR}" \
        && echo "[checkout-owner] .git is shared with ${OWNER}: group ${OGID}, setgid, group-writable" >&2
    fi
    ;;
  restore)
    [ "$(id -u)" = 0 ] && [ -n "${OWNER}" ] && [ "${OUID}" != 0 ] || { cat >/dev/null; exit 0; }
    command -v python3 >/dev/null || { echo "[checkout-owner] no python3 here: nothing given back" >&2; cat >/dev/null; exit 0; }
    python3 -c '
import os, sys
top, uid, gid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
done, given, failed = set(), 0, 0

def own(name, dirfd):
    """Give one entry of an already-opened directory back, never following it."""
    global given
    st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    if os.path.stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
        raise OSError("a hard link")                      # git never makes one in a worktree: not ours to give
    if st.st_uid == 0:
        os.chown(name, uid, gid, dir_fd=dirfd, follow_symlinks=False)
        given += 1

for raw in sys.stdin.buffer.read().split(b"\0"):
    rel = raw.decode("utf-8", "surrogateescape")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        continue                                          # git never names such a path; nothing to give back
    fds = []
    try:
        fd = os.open(top, FLAGS)
        fds.append(fd)
        for i, comp in enumerate(parts):
            key = "/".join(parts[: i + 1])
            if key not in done:
                done.add(key)
                own(comp, fd)                             # the entry itself, through its own directory
            if i < len(parts) - 1:
                fd = os.open(comp, FLAGS, dir_fd=fd)      # a symlinked directory refuses here (ELOOP/ENOTDIR)
                fds.append(fd)
    except FileNotFoundError:
        pass                                              # deleted by the operation: nothing to give back
    except OSError:
        failed += 1                                       # a symlink in the way, a mount without chown: this one only
    finally:
        for f in fds:
            os.close(f)
if given or failed:
    print(f"[checkout-owner] {given} path(s) git wrote as root given back to {uid}:{gid}"
          + (f", {failed} not (a symlink in the path, or no chown here)" if failed else ""), file=sys.stderr)
' "${TOP}" "${OUID}" "${OGID}"
    ;;
  *)
    sed -n 's/^#     //p' "${BASH_SOURCE[0]}" | head -2; exit 2 ;;
esac
