"""since_green.py — has any of what a suite tests changed since the last green? (DGO-2123)

    green = since_green.unchanged(repo, subjects)   # the last green's sha when nothing in `subjects` changed, else ""

On the CI (GITHUB_ACTIONS), a suite that tests one part of the tree runs only when that part changed since the LAST
GREEN. That is the green THIS job fetched: gates-hosted.yml's «The last green» step fetches refs/green/dgo-stable
beside the checkout and names it in DGO_LAST_GREEN. A ref alone is never trusted, because the runner's workspace is
shared and an earlier job's green stays in it (ci-verify's G72 runs there with no such step; the second reader). It is
never measured from the commit before: a red batch that broke the part, then a batch that leaves it alone, would turn
green with the part untested.

The suite RUNS whenever there is doubt:
- there is no green to measure from, or it is run by hand;
- git is missing or cannot answer;
- a subject no longer names anything at HEAD (renamed: it would read as unchanged forever).

`subjects` are git pathspecs. This file is always one of them, so a change here runs every suite that asks.

A suite that is told a sha prints `NOT RUN <why>` and exits 1: G72 (plane-tests-lint) reads that as «did not run»,
neither a pass nor a failure. Used by scripts/test_follow_suite.py, test_push_images.py and test_ci_step_aside.py,
and tested by scripts/test_since_green.py. `scripts/ci` is no package (its other files are commands), so a suite
loads this file by its path:

    spec = importlib.util.spec_from_file_location("since_green", REPO / "scripts" / "ci" / "since_green.py")
    since_green = importlib.util.module_from_spec(spec); spec.loader.exec_module(since_green)
    since_green.or_not_run(REPO, SUBJECTS)
"""
from __future__ import annotations

import os
import subprocess

SELF = "scripts/ci/since_green.py"
ENV = "DGO_LAST_GREEN"


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def unchanged(repo, subjects) -> str:
    """The last green's sha when nothing in `subjects` changed between it and HEAD, on the CI only; else ""."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return ""
    green = os.environ.get(ENV, "").strip()
    if not green:
        return ""
    every = (*subjects, SELF)
    try:
        for s in every:
            if not s.startswith(":") and not _git(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", s).stdout.strip():
                return ""
        # 0 is «no difference»; 1 is a difference, and anything else (128: git could not answer) runs the suite too
        same = _git(repo, "diff", "--quiet", green, "HEAD", "--", *every).returncode == 0
    except OSError:
        return ""
    return green if same else ""


def say_not_run(green: str, subjects) -> str:
    """The one line a suite prints when it does not run: G72's `NOT RUN <why>`, naming the green it measured from."""
    return f"NOT RUN nothing it tests changed since the last green, {green[:9]} ({' '.join(subjects)})"


def or_not_run(repo, subjects) -> None:
    """A suite's first call: returns when it should run, else prints G72's NOT RUN line and exits 1."""
    green = unchanged(repo, subjects)
    if green:
        print(say_not_run(green, subjects))
        raise SystemExit(1)


if __name__ == "__main__":
    # A SHELL suite's first line (apps/computers/tests/test_door.sh):
    #     python3 "${REPO}/scripts/ci/since_green.py" "${REPO}" <subject>… || exit 1
    # Exit 0 is «run». Exit 1 comes with G72's NOT RUN line. Exit 2 is a call with no subjects, which also runs.
    import sys
    if len(sys.argv) < 3:
        print("since_green.py <repo> <subject>…", file=sys.stderr)
        raise SystemExit(2)
    or_not_run(sys.argv[1], sys.argv[2:])
