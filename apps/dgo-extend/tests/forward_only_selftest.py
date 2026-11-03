#!/usr/bin/env python3
"""A converge never steps an office back (DGO-1016): the code step's own script, run for real.

On 2026-10-16 a converge checked vps1 out at the commit its declaration had been saved with eight days
earlier and rebuilt everything from it. 418 commits that vps1 was running went, among them the price
meter in Azaria's sessions. This test builds a real repository (A → B → C, plus a side commit S),
renders `converge.code_script` exactly as the step renders it, and runs it with bash against a
checkout:
  1. the machine runs C, the declaration says B         → refused: exit 3, ROLLBACK + DROP lines, HEAD stays C
  2. the machine runs C, the declaration says C         → done, HEAD = C
  3. the machine runs B, the declaration says C         → done (forward), HEAD = C
  4. the machine runs S (not in C), the declaration C   → refused, S named
  5. the machine runs C, B with allow_rollback          → done, HEAD = B (a rollback on purpose)
  6. no checkout yet, the declaration says B            → a fresh clone, done, HEAD = B
  7. a clone that was never checked out, retried at B  → done (it runs nothing, so it loses nothing)
Proven both ways: on the code before DGO-1016, cases 1 and 4 check out the older commit and exit 0.

Run: python3 apps/dgo-extend/tests/forward_only_selftest.py   (needs bash and git on PATH)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import converge  # noqa: E402

FAILS: list[str] = []
CHECKS = [0]


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(work: Path, name: str) -> str:
    (work / f"{name}.txt").write_text(name + "\n")
    git(work, "add", f"{name}.txt")
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"feature {name}")
    return git(work, "rev-parse", "HEAD")


def run(path: Path, repo: Path, commit_: str, allow: bool, shims: Path) -> subprocess.CompletedProcess:
    # `set -e` first, as start_detached runs every step's script.
    script = "set -e\n" + converge.code_script(str(path), str(repo), "", commit_, "", allow)
    env = dict(os.environ, PATH=f"{shims}{os.pathsep}{os.environ.get('PATH', '')}")
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        shims = t / "shims"                 # the script may call apt-get; a test never installs anything
        shims.mkdir()
        (shims / "apt-get").write_text("#!/bin/sh\nexit 0\n")
        (shims / "apt-get").chmod(0o755)
        work = t / "work"
        work.mkdir()
        git(work, "init", "-q", "-b", "main")
        a, b, c = commit(work, "A"), commit(work, "B"), commit(work, "C")
        git(work, "checkout", "-q", "-b", "side", b)
        s = commit(work, "S")
        git(work, "checkout", "-q", "main")
        origin = t / "origin.git"
        git(t, "clone", "-q", "--bare", str(work), str(origin))
        git(origin, "update-ref", "refs/heads/side", s)

        def machine_at(rev: str) -> Path:
            m = t / f"machine-{rev[:7]}-{len(list(t.iterdir()))}"
            git(t, "clone", "-q", str(origin), str(m))
            git(m, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", rev)
            return m

        m = machine_at(c)
        r = run(m, origin, b, False, shims)
        check("1. C → B is refused with exit 3", r.returncode == 3, f"rc={r.returncode} {r.stdout[-300:]}")
        check("1. the refusal counts what would go", "ROLLBACK: 1 commits" in r.stdout, r.stdout[-300:])
        check("1. the refusal names it", "DROP:" in r.stdout and "feature C" in r.stdout, r.stdout[-300:])
        check("1. HEAD is untouched", git(m, "rev-parse", "HEAD") == c)

        r = run(m, origin, c, False, shims)
        check("2. C → C is done", r.returncode == 0 and git(m, "rev-parse", "HEAD") == c, r.stdout[-300:])

        m = machine_at(b)
        r = run(m, origin, c, False, shims)
        check("3. B → C (forward) is done", r.returncode == 0 and git(m, "rev-parse", "HEAD") == c,
              r.stdout[-300:] + r.stderr[-300:])

        m = machine_at(s)
        r = run(m, origin, c, False, shims)
        check("4. S → C (S is not in C) is refused", r.returncode == 3 and "feature S" in r.stdout,
              f"rc={r.returncode} {r.stdout[-300:]}")
        check("4. HEAD is untouched", git(m, "rev-parse", "HEAD") == s)

        m = machine_at(c)
        r = run(m, origin, b, True, shims)
        check("5. C → B with allow_rollback is done", r.returncode == 0 and git(m, "rev-parse", "HEAD") == b,
              r.stdout[-300:] + r.stderr[-300:])

        fresh = t / "fresh" / "office"
        r = run(fresh, origin, b, False, shims)
        check("6. a fresh clone at B is done", r.returncode == 0 and git(fresh, "rev-parse", "HEAD") == b,
              r.stdout[-300:] + r.stderr[-300:])

        # A first converge that stopped right after `clone --no-checkout`: HEAD is the remote's default
        # branch (C), nothing was ever checked out, and the retry at B must not be refused for it.
        stopped = t / "stopped" / "office"
        stopped.parent.mkdir()
        git(stopped.parent, "clone", "-q", "--no-checkout", str(origin), "office")
        r = run(stopped, origin, b, False, shims)
        check("7. a clone never checked out, retried at B, is done",
              r.returncode == 0 and git(stopped, "rev-parse", "HEAD") == b, r.stdout[-300:] + r.stderr[-300:])
        check("the history is A → B → C", git(work, "rev-list", "--count", "main") == "3" and bool(a))
    print(f"FAILED: {len(FAILS)} of {CHECKS[0]}" if FAILS else f"OK: {CHECKS[0]} checks")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
