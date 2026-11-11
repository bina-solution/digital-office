#!/usr/bin/env python3
"""office_branch_admit (scripts/lib.sh): `bbox run` from a branch that is not the office's own (DGO-850).

    python3 scripts/test_office_branch_admit.py

AGENTS.md rule 6: each office commits and runs on the branch its .env declares (DGO_BRANCH). Claude sessions are held
by .claude/hooks/office-branch.py, but Azaria, Copilot and a person at the shell reach `bbox run` without it. The DGOs
review found three offices on three code lines (S8, S20), so a fix landed on whichever branch the checkout was on.
The check warns first, then refuses: an office that declares DGO_BRANCH_ENFORCE=1 refuses.

Each case is a throwaway git checkout with branches o-dgo and other, plus a .env. lib.sh is sourced with REPO_ROOT
set to that checkout, and office_branch_admit is called as `bbox run` calls it. It runs on the bash it finds (3.2 on
a Mac, 5 on Linux). It needs git, and no engine or network.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib.sh")
CLEAN = ("DGO_BRANCH", "DGO_BRANCH_ENFORCE", "DGO_GIT_OVERRIDE", "BBOX_BRANCH_ADMITTED", "REPO_ROOT")


class OfficeBranchAdmit(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="office-branch-admit-")
        self.genv = {k: v for k, v in os.environ.items() if k not in CLEAN and not k.startswith("GIT_")}
        self.genv.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid", "GIT_COMMITTER_NAME": "t",
                          "GIT_COMMITTER_EMAIL": "t@t.invalid", "GIT_CONFIG_NOSYSTEM": "1",
                          "GIT_CONFIG_GLOBAL": os.path.join(self.repo, ".gitconfig-test")})
        self.git("init", "-q", "-b", "o-dgo")
        with open(os.path.join(self.repo, "README"), "w") as f:
            f.write("x\n")
        self.git("add", "README")
        self.git("commit", "-q", "-m", "one")
        self.git("branch", "other")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def git(self, *a):
        subprocess.run(["git", "-C", self.repo, *a], check=True, env=self.genv, capture_output=True, timeout=60)

    def env_file(self, text):
        with open(os.path.join(self.repo, ".env"), "w") as f:
            f.write(text)

    def admit(self, extra=None, root=None):
        env = dict(self.genv)
        env.update(extra or {})
        env["REPO_ROOT"] = root or self.repo
        env["DOCKER_CONFIG"] = self.repo                 # sourcing lib.sh says nothing about this machine's docker
        # as bbox runs it: set -euo pipefail, and the check's own answer read with `|| rc=$?`
        script = ('set -euo pipefail; . "$1"; rc=0; office_branch_admit "bbox run" || rc=$?; '
                  'echo "rc=${rc} said=${BBOX_BRANCH_ADMITTED:-}"')
        p = subprocess.run(["bash", "-c", script, "test", LIB], capture_output=True, text=True, env=env,
                           cwd=self.repo, timeout=60)
        rc = [l for l in p.stdout.splitlines() if l.startswith("rc=")]
        self.assertTrue(rc, f"the check did not run: {p.stdout!r} {p.stderr!r}")
        return rc[-1], p.stderr

    def test_the_office_branch_is_silent(self):
        self.env_file("DGO_BRANCH=o-dgo\n")
        rc, err = self.admit()
        self.assertEqual(rc, "rc=0 said=")
        self.assertEqual(err.strip(), "")

    def test_an_aligned_comment_is_not_part_of_the_branch(self):
        self.env_file("DGO_BRANCH=o-dgo      # the office's own line (AGENTS.md rule 6)\n")
        rc, err = self.admit()
        self.assertEqual((rc, err.strip()), ("rc=0 said=", ""))

    def test_another_branch_warns_and_runs(self):
        self.env_file("DGO_BRANCH=o-dgo\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit()
        self.assertEqual(rc, "rc=0 said=1")
        self.assertIn("runs from other, and this office's branch is o-dgo", err)
        self.assertIn("DGO_BRANCH_ENFORCE=1 refuses it", err)

    def test_a_detached_checkout_is_said_and_never_refused(self):
        # a converge checks out the declared commit detached, then runs `bbox run` (apps/dgo-extend/converge.py)
        self.env_file("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1\n")
        self.git("checkout", "-q", "other")
        with open(os.path.join(self.repo, "README"), "a") as f:
            f.write("y\n")
        self.git("commit", "-q", "-am", "two")          # a commit that is not o-dgo's tip
        self.git("checkout", "-q", "--detach")
        rc, err = self.admit()
        self.assertEqual(rc, "rc=0 said=1")
        self.assertIn("runs from a detached HEAD (", err)
        self.assertNotIn("is not started", err)

    def test_detached_at_the_office_branch_tip_is_silent(self):
        self.env_file("DGO_BRANCH=o-dgo\n")
        self.git("checkout", "-q", "--detach", "o-dgo")
        rc, err = self.admit()
        self.assertEqual((rc, err.strip()), ("rc=0 said=", ""))

    def test_the_branch_is_read_as_the_guard_reads_it(self):
        self.git("checkout", "-q", "other")
        for text, extra, why in (
                ("DEPLOYMENT_NAME=x\n", {"DGO_BRANCH": "o-dgo"}, "from the environment"),
                ("export DGO_BRANCH=o-dgo\n", None, "an export line"),
                ("DGO_BRANCH=\nDGO_BRANCH=o-dgo\n", None, "the template's empty line before the real one"),
                ("DGO_BRANCH='o-dgo'\t# quoted, a tab before the note\r\n", None, "quotes, a tab and a CR")):
            self.env_file(text)
            rc, err = self.admit(extra)
            self.assertEqual(rc, "rc=0 said=1", why)
            self.assertIn("runs from other, and this office's branch is o-dgo", err, why)

    def test_a_folder_inside_another_repository_is_not_this_checkout(self):
        sub = os.path.join(self.repo, "nested")
        os.makedirs(sub)
        with open(os.path.join(sub, ".env"), "w") as f:
            f.write("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit(root=sub)
        self.assertEqual((rc, err.strip()), ("rc=0 said=", ""))

    def test_an_enforcing_office_refuses(self):
        self.env_file("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1   # stage 2, DGO-850\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit()
        self.assertEqual(rc, "rc=1 said=")
        self.assertIn("is not started", err)
        self.assertIn("git switch o-dgo", err)

    def test_the_override_passes_said(self):
        self.env_file("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit({"DGO_GIT_OVERRIDE": "1"})
        self.assertEqual(rc, "rc=0 said=1")
        self.assertIn("DGO_GIT_OVERRIDE=1 passes it", err)

    def test_once_per_job(self):
        self.env_file("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit({"BBOX_BRANCH_ADMITTED": "1"})
        self.assertEqual(rc, "rc=0 said=1")
        self.assertEqual(err.strip(), "")

    def test_no_declared_branch_and_no_checkout_admit_silently(self):
        self.env_file("DEPLOYMENT_NAME=x\n")
        self.git("checkout", "-q", "other")
        rc, err = self.admit()
        self.assertEqual((rc, err.strip()), ("rc=0 said=", ""))
        shutil.rmtree(os.path.join(self.repo, ".git"))
        self.env_file("DGO_BRANCH=o-dgo\nDGO_BRANCH_ENFORCE=1\n")
        rc, err = self.admit()
        self.assertEqual((rc, err.strip()), ("rc=0 said=", ""))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
