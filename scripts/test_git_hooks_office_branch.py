#!/usr/bin/env python3
"""test_git_hooks_office_branch — the office's branch rule, held by git itself (DGO-1764, after DGO-1461).

    python3 scripts/test_git_hooks_office_branch.py

Real git, in temporary repositories: a bare «origin» with `mac-dgo` and `dgo-stable`, and an office's clone on
`mac-dgo` whose `core.hooksPath` is THIS checkout's scripts/git-hooks (pre-push, reference-transaction), its branch
declared in its .env as an office declares it. Each case runs the real git command and reads what git did — the refs
before and after, on both sides — never the hook's words alone.

Refused, every shape the guard's fourth reader proved against the text hook (DGO-1461): a branch made by `branch`,
`checkout -b`, `switch -c`, `worktree add` (with and without -b), `stash branch`, `fetch . HEAD:<branch>`; HEAD
pointed at another branch (`checkout`, `checkout -`, a worktree on it); a commit on another branch through a worktree;
a reset, amend or rebase of pushed history; a push to another branch, by refspec, alias, `remote.*.push` or `:`
(matching); a delete (`:mac-dgo`, `-d`); a force; `--mirror`; `--tags`; a new branch on the remote. Allowed, the
office's ordinary work: a commit, its push, `push origin HEAD`, a merge of dgo-stable, an amend or reset of commits not
pushed, a detached probe worktree and a commit in it, fetch, stash, a local tag, and the owner's DGO_GIT_OVERRIDE=1.
An office that declares no branch is not held.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent / "git-hooks"
FAIL: list[str] = []
BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("DGO_BRANCH", "DGO_GIT_OVERRIDE", "CLAUDECODE", "DGO_BRANCH_ENFORCE", "CDPATH")
            and not k.startswith("GIT_")}          # no inherited git config, directory or CDPATH (the reader of v4)
# the refusals are judged as an office that enforces (rule 8's second stage); the staged warning has its own cases
BASE_ENV.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": tempfile.mkdtemp(),
                 "DGO_BRANCH_ENFORCE": "1"})


def git(cwd, *args, env=None, ok=True):
    p = subprocess.run(["git", *args], cwd=cwd, env={**BASE_ENV, **(env or {})}, capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()[:300]}")
    return p


def refs(cwd):
    return git(cwd, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags").stdout


def remote_refs(origin):
    return git(origin, "for-each-ref", "--format=%(refname) %(objectname)").stdout


def head(cwd):
    return git(cwd, "symbolic-ref", "-q", "HEAD", ok=False).stdout.strip() or "detached"


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(f"{name}: {detail}")


def office(declare=True):
    """(tmp, origin, clone): origin has mac-dgo and dgo-stable; the clone is on mac-dgo with the office's hooks."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="office-hooks-"))
    seed = tmp / "seed"
    git(tmp, "init", "-q", "-b", "mac-dgo", str(seed))
    git(seed, "commit", "-q", "--allow-empty", "-m", "base")
    git(seed, "branch", "dgo-stable")
    git(seed, "checkout", "-q", "dgo-stable")
    git(seed, "commit", "-q", "--allow-empty", "-m", "stable's own")
    git(seed, "checkout", "-q", "mac-dgo")
    origin = tmp / "origin.git"
    git(tmp, "clone", "-q", "--bare", str(seed), str(origin))
    clone = tmp / "office"
    git(tmp, "clone", "-q", "-b", "mac-dgo", str(origin), str(clone))
    git(clone, "config", "core.hooksPath", str(HOOKS))
    if declare:
        (clone / ".env").write_text("FOO=1\nexport DGO_BRANCH=\"mac-dgo\"  # this office\n")
    git(clone, "commit", "-q", "--allow-empty", "-m", "office work")
    git(clone, "push", "-q", "origin", "mac-dgo")
    return tmp, origin, clone


def refused(name, clone, origin, *args, env=None, setup=None):
    """The command fails, and neither side's refs nor HEAD moved."""
    if setup:
        setup()
    before = (refs(clone), remote_refs(origin), head(clone))
    p = git(clone, *args, env=env, ok=False)
    after = (refs(clone), remote_refs(origin), head(clone))
    check(f"refused: {name}", p.returncode != 0 and before == after,
          f"rc={p.returncode}, moved={before != after}, stderr={p.stderr.strip()[-200:]}")
    check(f"…{name} says why", "office-branch (git)" in p.stderr, p.stderr.strip()[-200:])


def allowed(name, clone, *args, env=None):
    p = git(clone, *args, env=env, ok=False)
    check(f"allowed: {name}", p.returncode == 0, p.stderr.strip()[-300:])
    return p


def main() -> int:
    if not shutil.which("git"):
        print("test_git_hooks_office_branch: no git here"); return 1
    version = tuple(int(x) for x in git(".", "version").stdout.split()[2].split(".")[:2])
    tmp, origin, clone = office()
    try:
        # ── refused: branches, made or moved, however asked ────────────────────────────────────────────────────
        refused("git branch", clone, origin, "branch", "other")
        refused("checkout -b", clone, origin, "checkout", "-b", "other")
        refused("checkout -b glued", clone, origin, "checkout", "-bother")
        refused("switch -c", clone, origin, "switch", "-c", "other")
        refused("worktree add with -b", clone, origin, "worktree", "add", "-q", "-b", "other", str(tmp / "w1"))
        refused("worktree add (makes a branch from its folder's name)", clone, origin, "worktree", "add", "-q",
                str(tmp / "probe"))
        refused("fetch . HEAD:dgo-stable", clone, origin, "fetch", ".", "HEAD:dgo-stable")
        refused("fetch origin dgo-stable:other", clone, origin, "fetch", "origin", "dgo-stable:other")
        refused("checkout a remote branch (makes a local one)", clone, origin, "checkout", "dgo-stable")
        (clone / "stashed.txt").write_text("x")
        git(clone, "add", "stashed.txt")
        git(clone, "stash", "-q")
        refused("stash branch", clone, origin, "stash", "branch", "other")
        git(clone, "stash", "drop", "-q")
        # an existing other branch, made on the owner's ask: HEAD may not point at it, nor a worktree commit on it
        allowed("the owner's ask makes a branch", clone, "branch", "other", env={"DGO_GIT_OVERRIDE": "1"})
        if version >= (2, 46):                    # an older git does not hand HEAD's switches to the hook
            refused("checkout other", clone, origin, "checkout", "-q", "other")
            refused("a worktree on another branch", clone, origin, "worktree", "add", "-q", str(tmp / "w2"), "other")
        git(clone, "worktree", "add", "-q", str(tmp / "w3"), "other", env={"DGO_GIT_OVERRIDE": "1"})
        refused("a commit on another branch, in its worktree", tmp / "w3", origin, "commit", "-q", "--allow-empty",
                "-m", "x")
        git(clone, "worktree", "remove", "--force", str(tmp / "w3"))           # git itself keeps a branch in use
        refused("delete another branch", clone, origin, "branch", "-D", "other")
        # ── refused: pushed history rewritten ─────────────────────────────────────────────────────────────────
        refused("reset --hard of a pushed commit", clone, origin, "reset", "-q", "--hard", "HEAD~1")
        refused("amend of a pushed commit", clone, origin, "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")
        # a rebase detaches HEAD first (allowed) and fails where it would move the branch: the branch is what is judged
        before = (refs(clone), remote_refs(origin))
        p = git(clone, "rebase", "-q", "origin/dgo-stable", ok=False)
        check("refused: rebase onto dgo-stable (rewrites the pushed commit)",
              p.returncode != 0 and (refs(clone), remote_refs(origin)) == before and "office-branch (git)" in p.stderr,
              p.stderr[-200:])
        git(clone, "rebase", "--abort", ok=False)
        check("…and after its abort the office is on its branch", head(clone) == "refs/heads/mac-dgo", head(clone))
        # no old value named: git hands the hook zeroes, and the branch's tip is read (the reader). After each case the
        # office is put back by the owner's override, so a hook that let one through fails it alone
        tip = git(clone, "rev-parse", "refs/heads/mac-dgo").stdout.strip()

        def back(at=tip):
            o = {"DGO_GIT_OVERRIDE": "1"}
            git(clone, "update-ref", "--no-deref", "refs/heads/mac-dgo", at, env=o)
            git(clone, "symbolic-ref", "HEAD", "refs/heads/mac-dgo", env=o)
            git(clone, "reset", "-q", "--hard", env=o)

        refused("update-ref of the office's branch to a pushed commit's parent", clone, origin,
                "update-ref", "refs/heads/mac-dgo", "HEAD~1")
        back()
        git(clone, "checkout", "-q", "--detach")
        refused("branch -f of the office's branch, from a detached HEAD", clone, origin, "branch", "-f", "mac-dgo", "HEAD~1")
        back()
        if version >= (2, 46):
            refused("the office's branch made a symbolic ref of another", clone, origin,
                    "symbolic-ref", "refs/heads/mac-dgo", "refs/heads/dgo-stable")
            back()
            refused("symbolic-ref HEAD at another branch", clone, origin, "symbolic-ref", "HEAD", "refs/heads/dgo-stable")
            back()
        # local commits on top of the pushed ones: dropping the pushed one under them is a rewrite all the same
        git(clone, "commit", "-q", "--allow-empty", "-m", "local, not pushed")
        ahead = git(clone, "rev-parse", "HEAD").stdout.strip()
        refused("reset below the pushed commit while ahead of it", clone, origin, "reset", "-q", "--hard", "HEAD~2")
        back(ahead)
        allowed("reset to the pushed commit (drops only what is not pushed)", clone, "reset", "-q", "--hard", "origin/mac-dgo")
        # the main checkout's .env is the declaration: not a variable on one command, nor a worktree's own .env
        refused("DGO_BRANCH=other on the command", clone, origin, "branch", "env-named",
                env={"DGO_BRANCH": "env-named"})
        git(clone, "worktree", "add", "-q", "--detach", str(tmp / "wenv"), "HEAD")
        (tmp / "wenv" / ".env").write_text("DGO_BRANCH=wt-named\n")
        refused("a worktree's own .env naming another branch", tmp / "wenv", origin, "branch", "wt-named")
        # (`symbolic-ref main-worktree/HEAD …` from a linked worktree: git itself refuses the name, measured on 2.50)
        git(clone, "worktree", "remove", "--force", str(tmp / "wenv"))
        try:
            refused("update-ref --no-deref -d HEAD (the checkout would stop being one)", clone, origin,
                    "update-ref", "--no-deref", "-d", "HEAD")
        except RuntimeError as e:                         # HEAD went: git no longer sees a repository here
            check("refused: update-ref --no-deref -d HEAD", False, f"the checkout stopped being one: {e}"[:200])
            (clone / ".git" / "HEAD").write_text("ref: refs/heads/mac-dgo\n")
        # an exported CDPATH aimed at a folder with a .git must not turn the .env's declaration off (the reader)
        decoy = tmp / "cd-decoy"
        (decoy / ".git").mkdir(parents=True)
        refused("CDPATH and DGO_BRANCH=x on the command", clone, origin, "branch", "cdpath-named",
                env={"CDPATH": str(decoy), "DGO_BRANCH": "cdpath-named"})
        p = git(clone, "branch", "says-why", ok=False)
        check("a refusal says the files may already have moved", "git status" in p.stderr, p.stderr[-300:])
        # gc and maintenance pack the refs: a create and a delete of each branch that change nothing (the reader)
        for i in range(20):
            git(clone, "update-ref", f"refs/tags/t{i}", "HEAD")
        before = refs(clone)
        allowed("git gc (packs every loose ref)", clone, "gc", "-q")
        allowed("pack-refs --all --prune", clone, "pack-refs", "--all", "--prune")
        check("…and no branch changed", refs(clone) == before, "")
        packed = (clone / ".git" / "packed-refs").read_text()
        check("…the office's branch is packed", " refs/heads/mac-dgo" in packed, packed[-200:])
        # a real delete of a packed branch is still refused (`other`, made on the owner's ask above, is packed now)
        refused("delete of a packed branch", clone, origin, "branch", "-D", "other")
        p = git(clone, "branch", "-D", "other", ok=False)
        check("…and it is named a delete, not a create (zero → zero)", "would delete the branch other" in p.stderr,
              p.stderr.strip()[-200:])
        refused("update-ref -d of a packed branch", clone, origin, "update-ref", "-d", "refs/heads/other")
        # ── refused: pushes ───────────────────────────────────────────────────────────────────────────────────
        git(clone, "commit", "-q", "--allow-empty", "-m", "more office work")
        # forced, so that git's own fast-forward check lets them reach the hook: the hook is what is tested
        refused("push HEAD:dgo-stable", clone, origin, "push", "-q", "-f", "origin", "HEAD:dgo-stable")
        refused("push through an alias", clone, origin, "-c", "alias.p=push", "p", "-q", "-f", "origin", "HEAD:dgo-stable")
        refused("push through remote.origin.push", clone, origin, "-c", "remote.origin.push=+HEAD:refs/heads/dgo-stable",
                "push", "-q", "origin")
        refused("push :mac-dgo (delete)", clone, origin, "push", "-q", "origin", ":mac-dgo")
        refused("push -d", clone, origin, "push", "-q", "-d", "origin", "mac-dgo")
        refused("push to a new branch", clone, origin, "push", "-q", "origin", "HEAD:refs/heads/evil/mac-dgo")
        refused("push --mirror", clone, origin, "push", "-q", "--mirror", "origin")
        allowed("a local tag", clone, "tag", "v9")
        refused("push --tags", clone, origin, "push", "-q", "--tags", "origin")
        refused("push a tag named like the branch", clone, origin, "push", "-q", "origin", "HEAD:refs/tags/mac-dgo")
        refused("force push of an older commit", clone, origin, "push", "-q", "-f", "origin", "HEAD~2:mac-dgo")
        # ── allowed: the office's ordinary work ───────────────────────────────────────────────────────────────
        allowed("push origin mac-dgo", clone, "push", "-q", "origin", "mac-dgo")
        git(clone, "commit", "-q", "--allow-empty", "-m", "unpushed")
        allowed("amend of a commit not pushed", clone, "commit", "-q", "--amend", "--allow-empty", "-m", "unpushed, fixed")
        allowed("reset of a commit not pushed", clone, "reset", "-q", "--hard", "HEAD~1")
        git(clone, "commit", "-q", "--allow-empty", "-m", "office work 3")
        allowed("push origin HEAD", clone, "push", "-q", "origin", "HEAD")
        allowed("fetch", clone, "fetch", "-q", "origin")
        allowed("merge of dgo-stable", clone, "merge", "-q", "--no-edit", "origin/dgo-stable")
        allowed("its push", clone, "push", "-q", "origin", "mac-dgo")
        allowed("a detached probe worktree", clone, "worktree", "add", "-q", "--detach", str(tmp / "probe2"), "HEAD")
        allowed("a commit inside the probe", tmp / "probe2", "commit", "-q", "--allow-empty", "-m", "probe")
        allowed("a merge inside the probe", tmp / "probe2", "merge", "-q", "--no-edit", "origin/dgo-stable")
        (clone / "s.txt").write_text("s")
        git(clone, "add", "s.txt")
        allowed("stash", clone, "stash", "-q")
        allowed("stash pop", clone, "stash", "pop", "-q")
        allowed("checkout --detach and back", clone, "checkout", "-q", "--detach")
        allowed("…back to the office's branch", clone, "checkout", "-q", "mac-dgo")
        p = allowed("the owner's explicit ask pushes elsewhere", clone, "push", "-q", "origin", "HEAD:dgo-stable",
                    env={"DGO_GIT_OVERRIDE": "1"})
        check("…and it is said", "DGO_GIT_OVERRIDE=1" in p.stderr, p.stderr[-200:])
        check("the office is still on its branch", head(clone) == "refs/heads/mac-dgo", head(clone))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # rule 8's stages: an office that declares its branch but not DGO_BRANCH_ENFORCE=1 is WARNED; a Claude session is
    # refused at once; the office's main .env saying DGO_BRANCH_ENFORCE=1 makes it a refusal for everyone
    tmp, origin, clone = office()
    try:
        staged = {"DGO_BRANCH_ENFORCE": ""}
        p = allowed("not enforced yet: another branch passes", clone, "branch", "staged-one", env=staged)
        check("…with the warning", "WOULD refuse" in p.stderr and "DGO_BRANCH_ENFORCE=1" in p.stderr, p.stderr[-200:])
        git(clone, "branch", "-D", "staged-one", env={"DGO_GIT_OVERRIDE": "1"}, ok=False)
        p = git(clone, "branch", "staged-two", env={**staged, "CLAUDECODE": "1"}, ok=False)
        check("a Claude session is refused at once", p.returncode != 0 and "refused" in p.stderr, p.stderr[-200:])
        with open(clone / ".env", "a") as f:
            f.write("DGO_BRANCH_ENFORCE=1\n")
        p = git(clone, "branch", "staged-three", env=staged, ok=False)
        check("the main .env's DGO_BRANCH_ENFORCE=1 refuses everyone", p.returncode != 0, p.stderr[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # an office that declares no branch is not held; the declaration may also be the environment's
    tmp, origin, clone = office(declare=False)
    try:
        allowed("no declaration: a branch", clone, "branch", "other")
        p = git(clone, "branch", "other2", env={"DGO_BRANCH": "mac-dgo"}, ok=False)
        check("the environment's DGO_BRANCH holds it", p.returncode != 0, p.stderr[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # setup wires the MAIN checkout's hooks by an absolute path, even when run from a worktree (the reader); a relative
    # path set by an older setup is made absolute; another office's own hooksPath is never overridden
    tmp, origin, clone = office(declare=False)
    try:
        fake = tmp / "bin"
        fake.mkdir()
        (fake / "stat").write_text("#!/bin/sh\necho 1000:1000\n")        # the owner's uid, wherever GNU stat is not
        (fake / "stat").chmod(0o755)
        env = {"PATH": f"{fake}:{os.environ.get('PATH', '')}"}
        setup = ["bash", str(HOOKS.parent / "checkout-owner.sh"), "setup"]
        git(clone, "worktree", "add", "-q", "--detach", str(tmp / "wsetup"), "HEAD")
        want = str(clone.resolve() / "scripts" / "git-hooks")
        for start, name in (("", "unset"), ("scripts/git-hooks", "relative")):
            if start:
                git(clone, "config", "core.hooksPath", start)
            else:
                git(clone, "config", "--unset", "core.hooksPath", ok=False)
            p = subprocess.run(setup, cwd=tmp / "wsetup", env={**BASE_ENV, **env}, capture_output=True, text=True)
            got = git(clone, "config", "--get", "core.hooksPath", ok=False).stdout.strip()
            check(f"setup from a worktree ({name}): the main checkout's hooks, absolute", got == want,
                  f"rc={p.returncode} got={got!r} want={want!r} {p.stderr[-200:]}")
        git(clone, "config", "core.hooksPath", "/elsewhere/hooks")
        subprocess.run(setup, cwd=clone, env={**BASE_ENV, **env}, capture_output=True, text=True)
        check("setup never overrides another hooksPath",
              git(clone, "config", "--get", "core.hooksPath").stdout.strip() == "/elsewhere/hooks")
        # the hooks are wired whoever owns the checkout and whatever `stat` the host has (the reader of v3): a stat
        # that answers nothing (macOS has no `stat -c`) and a root-owned checkout
        for body, name in (("#!/bin/sh\nexit 1\n", "a stat that answers nothing"),
                           ("#!/bin/sh\necho 0:0\n", "a root-owned checkout")):
            (fake / "stat").write_text(body)
            git(clone, "config", "--unset", "core.hooksPath", ok=False)
            p = subprocess.run(setup, cwd=clone, env={**BASE_ENV, **env}, capture_output=True, text=True)
            got = git(clone, "config", "--get", "core.hooksPath", ok=False).stdout.strip()
            check(f"setup wires the hooks on {name}", got == want and p.returncode == 0,
                  f"rc={p.returncode} got={got!r} {p.stderr[-200:]}")
        # an exported CDPATH made `cd` print, and a two-line hooksPath ran no hook (the reader of v4); and that broken
        # value of ours is repaired by the next setup
        (fake / "stat").write_text("#!/bin/sh\necho 1000:1000\n")
        git(clone, "config", "--unset", "core.hooksPath", ok=False)
        p = subprocess.run(setup, cwd=clone, env={**BASE_ENV, **env, "CDPATH": ".:/nonexistent"},
                           capture_output=True, text=True)
        got = git(clone, "config", "--get", "core.hooksPath", ok=False).stdout.strip()
        check("setup under an exported CDPATH writes one absolute line", got == want, f"got={got!r}")
        git(clone, "config", "core.hooksPath", f"{clone}/.git\n{want}")
        subprocess.run(setup, cwd=clone, env={**BASE_ENV, **env}, capture_output=True, text=True)
        got = git(clone, "config", "--get", "core.hooksPath", ok=False).stdout.strip()
        check("…and a two-line value of ours is repaired", got == want, f"got={got!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for f in FAIL:
        print("FAIL:", f)
    print(f"test_git_hooks_office_branch: {'all passed' if not FAIL else f'{len(FAIL)} failed'} (git {'.'.join(map(str, version))})")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
