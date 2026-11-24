#!/usr/bin/env python3
"""test_stale_image_rows.py — an image that names its commit is current while its sources are that commit's (DGO-2123).

    python3 scripts/test_stale_image_rows.py

scripts/lib.sh _stale_image_rows lists the running services whose image is older than the files it was built from, and
a take rebuilds exactly those (follow.sh, DGO-1356). It compared file TIMES. A take's merge rewrites the files it
brings, so the times of a directory move while what it holds is what the image was built from. Every image a take
pulled from the line (scripts/ci/push-images.sh labels each with org.opencontainers.image.revision) read as older than
its sources, and was built again: the pull bought nothing (the reader of DGO-2123). Now such an image is current while
its context holds that commit's files, untracked ones included. Anything else is measured by time, as before.

The measurement is lib.sh's own text (its python heredoc), run in a throwaway repository with `docker` stood in on
PATH: one running service, xs, built from apps/x by an image created in 2020 (older than any file here).
"""
from __future__ import annotations

import io
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


try:
    import yaml  # noqa: F401 — the measurement reads the app composes with it, a stream as PyYAML takes one
    yaml.safe_load(io.StringIO("a: 1"))
except Exception:
    print("NOT RUN needs PyYAML (lib.sh's measurement reads the app composes with it)")
    sys.exit(1)

text = (ROOT / "scripts" / "lib.sh").read_text(encoding="utf-8")
m = re.search(r"^_stale_image_rows\(\) \{\n.*?python3 - <<'PY'\n(.*?)\nPY\n", text, re.S | re.M)
if not m:
    print("FAIL _stale_image_rows' measurement was not found in scripts/lib.sh")
    sys.exit(1)
MEASURE = m.group(1)

DOCKER = r'''#!/bin/sh
# docker, stood in: one running service xs (container xs-1, image sha256:img, created in 2020, labelled STUB_REV)
case "$*" in
  "ps --format {{.Label \"com.docker.compose.service\"}}") echo xs ;;
  "ps -q --filter label=com.docker.compose.service=xs --format {{.Names}}") echo xs-1 ;;
  "inspect -f {{.Image}} xs-1") echo sha256:img ;;
  "image inspect -f {{.Created}} sha256:img") echo 2020-01-01T00:00:00Z ;;
  "image inspect -f {{index .Config.Labels \"org.opencontainers.image.revision\"}} sha256:img") printf '%s\n' "${STUB_REV}" ;;
esac
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    repo, bin_ = t / "repo", t / "bin"
    (repo / "apps" / "x").mkdir(parents=True)
    bin_.mkdir()
    (repo / "apps" / "x" / "docker-compose.yml").write_text("services:\n  xs:\n    build:\n      context: .\n")
    (repo / "apps" / "x" / "app.py").write_text("print('x')\n")
    (repo / "apps" / "x" / "Dockerfile").write_text("FROM scratch\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    built_from = git(repo, "rev-parse", "HEAD")
    (bin_ / "docker").write_text(DOCKER)
    os.chmod(bin_ / "docker", 0o755)
    script = t / "measure.py"
    script.write_text(MEASURE)

    def rows(rev):
        env = dict(os.environ, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", STUB_REV=rev)
        p = subprocess.run([sys.executable, str(script)], cwd=repo, capture_output=True, text=True, env=env, timeout=60)
        return p.stdout.strip() + (" ERR " + p.stderr.strip() if p.returncode else "")

    check("an image with no revision is measured by time: older than its files, it is stale",
          rows("").startswith("xs ("), rows(""))
    check("an image built from this very commit is current, whatever the files' times",
          rows(built_from) == "", rows(built_from))
    check("a revision this repository does not hold is measured by time", rows("f" * 40).startswith("xs ("),
          rows("f" * 40))
    check("a label that is not a commit is measured by time", rows("<no value>").startswith("xs ("), rows("<no value>"))
    (repo / "apps" / "x" / "app.py").write_text("print('edited here')\n")
    check("an edit in its context since that commit: stale", rows(built_from).startswith("xs ("), rows(built_from))
    git(repo, "checkout", "-q", "--", "apps/x/app.py")
    (repo / "apps" / "x" / "new.py").write_text("print('new')\n")
    check("a new file in its context, not yet committed: stale", rows(built_from).startswith("xs ("), rows(built_from))
    (repo / "apps" / "x" / "new.py").unlink()
    (repo / "README.md").write_text("elsewhere\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "elsewhere")
    check("a later commit that leaves its context alone: still current", rows(built_from) == "", rows(built_from))

print(f"\n{'FAIL' if fails else 'PASS'} — {fails} failure(s)")
sys.exit(1 if fails else 0)
