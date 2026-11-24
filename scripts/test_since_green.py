#!/usr/bin/env python3
"""since_green (scripts/ci/since_green.py): on the CI, a suite that tests one part of the tree runs only when that part
changed since the last green this job fetched (DGO-2123).

    python3 scripts/test_since_green.py

A throwaway git repository holds a last green and a commit on top. The job's green is named as gates-hosted.yml names
it, in DGO_LAST_GREEN. Each case reads the one answer a suite acts on: the green's sha (nothing it tests changed, so
it says NOT RUN) or "" (it runs). Standard library only. It never skips itself: it is the check of the rule.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "ci" / "since_green.py"


def load():
    spec = importlib.util.spec_from_file_location("since_green", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class SinceGreen(unittest.TestCase):
    SUBJECTS = ("scripts/ci/push-images.sh", ":(glob)apps/*/docker-compose.yml")

    def setUp(self):
        self.sg = load()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="since-green-"))
        r = self.repo = self.tmp / "repo"
        for f in ("scripts/ci/since_green.py", "scripts/ci/push-images.sh", "apps/a/docker-compose.yml", "docs/x.md"):
            (r / f).parent.mkdir(parents=True, exist_ok=True)
            (r / f).write_text(f + "\n")
        git(r, "init", "-q", "-b", "dgo-stable")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "the last green")
        self.green = git(r, "rev-parse", "HEAD")
        self.saved = {k: os.environ.get(k) for k in ("GITHUB_ACTIONS", self.sg.ENV, "PATH")}
        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ.pop(self.sg.ENV, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mark_green(self, sha=None):
        """what gates-hosted.yml's «The last green» step does: this job's green, named"""
        os.environ[self.sg.ENV] = sha or self.green

    def change(self, path, remove=False):
        f = self.repo / path
        if remove:
            git(self.repo, "rm", "-q", path)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text((f.read_text() if f.exists() else "") + "changed\n")
            git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "this proof")

    def answer(self, subjects=None):
        return self.sg.unchanged(self.repo, subjects or self.SUBJECTS)

    def test_nothing_it_tests_changed_is_the_greens_sha(self):
        self.mark_green()
        self.change("docs/x.md")
        self.assertEqual(self.answer(), self.green)

    def test_the_green_itself_is_unchanged(self):
        self.mark_green()
        self.assertEqual(self.answer(), self.green)

    def test_a_subject_that_changed_runs(self):
        self.mark_green()
        self.change("scripts/ci/push-images.sh")
        self.assertEqual(self.answer(), "")

    def test_a_glob_subject_that_changed_runs(self):
        self.mark_green()
        self.change("apps/a/docker-compose.yml")
        self.assertEqual(self.answer(), "")

    def test_a_change_to_the_rule_itself_runs_every_suite(self):
        self.mark_green()
        self.change("scripts/ci/since_green.py")
        self.assertEqual(self.answer(), "")

    def test_measured_from_the_green_never_from_the_commit_before(self):
        # a batch that changed the subject (red: green never moved), then one that leaves it alone: it still runs
        self.mark_green()
        self.change("scripts/ci/push-images.sh")
        self.change("docs/x.md")
        self.assertEqual(self.answer(), "")

    def test_no_green_named_by_this_job_runs_even_beside_an_older_ref(self):
        # an earlier job's green stays in the shared workspace; ci-verify's G72 names none (the second reader)
        git(self.repo, "update-ref", "refs/remotes/origin/green/dgo-stable", self.green)
        self.change("docs/x.md")
        self.assertEqual(self.answer(), "")

    def test_a_green_git_cannot_read_runs(self):
        self.mark_green("f" * 40)   # a commit this clone does not have: git answers 128
        self.change("docs/x.md")
        self.assertEqual(self.answer(), "")

    def test_a_subject_that_names_nothing_runs(self):
        # renamed away: it would read as unchanged forever
        self.mark_green()
        self.change("docs/x.md")
        self.assertEqual(self.answer(("scripts/ci/no-such-file.sh",)), "")

    def test_a_subject_removed_since_the_green_runs(self):
        self.mark_green()
        self.change("scripts/ci/push-images.sh", remove=True)
        self.assertEqual(self.answer(), "")

    def test_no_git_runs(self):
        self.mark_green()
        self.change("docs/x.md")
        empty = self.tmp / "no-git"
        empty.mkdir()
        os.environ["PATH"] = str(empty)
        self.assertEqual(self.answer(), "")

    def test_by_hand_it_always_runs(self):
        self.mark_green()
        self.change("docs/x.md")
        os.environ.pop("GITHUB_ACTIONS", None)
        self.assertEqual(self.answer(), "")

    def test_the_line_is_g72s_not_run(self):
        line = self.sg.say_not_run(self.green, self.SUBJECTS)
        self.assertTrue(line.startswith("NOT RUN "), line)
        self.assertIn(self.green[:9], line)

    def test_the_command_line_a_shell_suite_calls(self):
        # test_door.sh: `python3 scripts/ci/since_green.py <repo> <subject>…`, the NOT RUN line on stdout and exit 1
        self.mark_green()
        self.change("docs/x.md")
        cmd = ["python3", str(HELPER), str(self.repo), *self.SUBJECTS]
        got = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(got.returncode, 1, got.stderr)
        self.assertTrue(got.stdout.startswith("NOT RUN "), got.stdout)
        self.change("scripts/ci/push-images.sh")
        got = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual((got.returncode, got.stdout), (0, ""))
        self.assertEqual(subprocess.run(["python3", str(HELPER)], capture_output=True).returncode, 2)

    def test_or_not_run_exits_1_only_when_nothing_changed(self):
        self.mark_green()
        self.change("docs/x.md")
        said = io.StringIO()
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(said):
            self.sg.or_not_run(self.repo, self.SUBJECTS)
        self.assertEqual(stop.exception.code, 1)
        self.assertTrue(said.getvalue().startswith("NOT RUN "), said.getvalue())
        self.change("scripts/ci/push-images.sh")
        self.assertIsNone(self.sg.or_not_run(self.repo, self.SUBJECTS))


if __name__ == "__main__":
    unittest.main(verbosity=1)
