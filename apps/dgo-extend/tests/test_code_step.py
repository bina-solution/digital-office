#!/usr/bin/env python3
"""test_code_step — a fresh clone of a release copy ends with a platform.state.yaml (FPG-8).

The public release carries no platform.state.yaml: a new office starts from platform.state.default.yaml.
step_code's fallback copied the default BEFORE the commit was checked out, so on a fresh
`clone --no-checkout` it ran on an empty tree, and the state step then had no file to write — measured
on fireplace, 2026-10-22. This runs the script step_code sends to the machine, against a scratch repo
shaped like the release.

Run: python3 apps/dgo-extend/tests/test_code_step.py  (inside the app's image, or with its deps + git)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d, "src")
        src.mkdir()
        git(src, "init", "-q", "-b", "dgo-stable")
        Path(src, "platform.state.default.yaml").write_text("apps: {}\n")
        Path(src, "README.md").write_text("release\n")
        git(src, "add", "-A")
        git(src, "commit", "-q", "-m", "release")
        commit = git(src, "rev-parse", "HEAD")
        office = {"id": "t", "path": str(Path(d, "office")), "machine": "m",
                  "source": {"repo": str(src), "branch": "dgo-stable", "commit": commit}}
        sent = {}
        real = converge.start_detached, converge.wait_detached
        try:
            converge.start_detached = lambda o, step, script, secret=False: sent.update(script=script)
            converge.wait_detached = lambda o, step, emit, limit=0, every=0: "HEAD=" + commit
            converge.step_code(office, {}, lambda *_: None)
        finally:
            converge.start_detached, converge.wait_detached = real
        out = subprocess.run(["bash", "-c", sent["script"]], capture_output=True, text=True, timeout=60)
        check(out.returncode == 0, f"the code step's script runs: {out.stderr[-400:]}")
        state = Path(office["path"], "platform.state.yaml")
        check(state.exists() and state.read_text() == "apps: {}\n",
              "a fresh clone of a release copy ends with platform.state.yaml, made from the default")
        check(("HEAD=" + commit) in out.stdout, "…at the declared commit")
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_code_step" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
