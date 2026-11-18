#!/usr/bin/env python3
"""re-ask (scripts/ci/re-ask.py): once a version's proof ends, the runs that stepped aside for it are asked again.

    python3 scripts/test_ci_re_ask.py

GitHub is a stand-in that holds each workflow's runs (filtered by branch and status as GitHub filters them), each
run's jobs and each check run's annotations, and records every re-run asked — so a decision is read from what was
ASKED, not only from what was printed.
"""
import importlib.util
import io
import os
import pathlib
import unittest
import urllib.error
from contextlib import redirect_stdout

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("re_ask", REPO / "scripts" / "ci" / "re-ask.py")
re_ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(re_ask)

ASIDE = [{"title": "step-aside", "message": "a version's proof is ahead"}]
OWN = 9000                      # this proof run (GITHUB_RUN_ID)


class FakeGitHub:
    def __init__(self, runs, annotations=None, broken=(), jobs=None):
        self._runs, self._ann, self._broken, self._jobs = runs, annotations or {}, set(broken), jobs or {}
        self.reran = []

    def runs(self, workflow, branch="", status="", pages=1):
        if workflow in self._broken:
            raise urllib.error.URLError("down")
        return [r for r in self._runs if r["wf"] == workflow and (not branch or r["head_branch"] == branch)
                and (not status or r["status"] == status)]

    def jobs(self, run_id):
        """One job per run (check run <id>0), or the names given for it: check runs <id>0, <id>1, …"""
        names = self._jobs.get(run_id, ["gates"])
        return [{"name": n, "check_run_url": f"https://api.github.com/repos/o/r/check-runs/{run_id}{i}"}
                for i, n in enumerate(names)]

    def annotations(self, check_run_id):
        return self._ann.get(check_run_id, [])

    def rerun(self, run_id):
        self.reran.append(run_id)


def run(wf, rid, branch, conclusion, status="completed", event="push", attempt=1):
    return {"wf": wf, "id": rid, "head_branch": branch, "conclusion": conclusion, "status": status, "event": event,
            "run_attempt": attempt}


def proof(rid, status="in_progress"):
    return run("gates-hosted.yml", rid, "dgo-stable", None, status)


def call(gh, *extra):
    out = io.StringIO()
    os.environ["GITHUB_RUN_ID"] = str(OWN)
    with redirect_stdout(out):
        rc = re_ask.main(list(extra), gh=gh)
    return rc, out.getvalue()


class ReAsk(unittest.TestCase):
    def test_a_run_that_stepped_aside_is_asked_again(self):
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 11, "mac-dgo", "cancelled")], {110: ASIDE})
        rc, out = call(gh)
        self.assertEqual((rc, gh.reran), (0, [11]))
        self.assertIn("asked again gates-hosted.yml on mac-dgo", out)

    def test_a_newer_run_that_tested_nothing_does_not_hide_it(self):
        # most mac-dgo pushes do not ask for gates: their run is «skipped», and it must not count as newer
        gh = FakeGitHub([run("gates-hosted.yml", 11, "mac-dgo", "cancelled"),
                         run("gates-hosted.yml", 12, "mac-dgo", "skipped"),
                         run("gates-hosted.yml", 13, "mac-dgo", "skipped")], {110: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [11])

    def test_a_run_from_before_the_proof_is_asked_too(self):
        # no time window: the run was made hours before this proof (the case step-aside was built for)
        gh = FakeGitHub([run("go-test.yml", 5, "hp-dgo", "cancelled"), proof(OWN)], {50: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [5])

    def test_a_run_cancelled_by_hand_is_not(self):
        gh = FakeGitHub([run("gates-hosted.yml", 12, "mac-dgo", "cancelled")], {})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_newer_run_that_ran_owes_nothing(self):
        gh = FakeGitHub([run("go-test.yml", 13, "hp-dgo", "cancelled"),
                         run("go-test.yml", 14, "hp-dgo", "success")], {130: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_newer_run_still_going_owes_nothing_yet(self):
        gh = FakeGitHub([run("go-test.yml", 13, "hp-dgo", "cancelled"),
                         run("go-test.yml", 14, "hp-dgo", None, "queued")], {130: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_only_the_newest_stepped_aside_run_of_a_branch(self):
        gh = FakeGitHub([run("go-test.yml", 15, "dell-dgo", "cancelled"),
                         run("go-test.yml", 16, "dell-dgo", "cancelled")], {150: ASIDE, 160: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [16])

    def test_the_proof_branch_is_never_asked_again_here(self):
        gh = FakeGitHub([run("gates-hosted.yml", 17, "dgo-stable", "cancelled")], {170: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_nothing_while_another_proof_waits(self):
        gh = FakeGitHub([proof(OWN), proof(9001, "queued"), run("go-test.yml", 18, "mac-dgo", "cancelled")],
                        {180: ASIDE})
        _, out = call(gh)
        self.assertEqual(gh.reran, [])
        self.assertIn("another version's proof is still queued or running", out)

    def test_this_proof_itself_does_not_count_as_waiting(self):
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 18, "mac-dgo", "cancelled")], {180: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [18])

    def test_at_most_max_and_the_rest_said(self):
        runs = [run("android-app.yml", 100 + i, f"b{i}", "cancelled") for i in range(re_ask.MAX + 2)]
        gh = FakeGitHub(runs, {(100 + i) * 10: ASIDE for i in range(re_ask.MAX + 2)})
        _, out = call(gh)
        self.assertEqual(len(gh.reran), re_ask.MAX)
        self.assertIn("2 more run(s) stepped aside", out)

    def test_github_that_does_not_answer_is_a_warning_and_the_others_go_on(self):
        gh = FakeGitHub([run("go-test.yml", 18, "mac-dgo", "cancelled")], {180: ASIDE}, broken={"android-app.yml"})
        rc, out = call(gh)
        self.assertEqual((rc, gh.reran), (0, [18]))
        self.assertIn("::warning::re-ask: android-app.yml's runs could not be read", out)

    def test_the_notice_on_a_later_job_counts(self):
        # decide succeeded, gates carries the notice (check run 211 = the run's second job)
        gh = FakeGitHub([run("gates-hosted.yml", 21, "mac-dgo", "cancelled")], {211: ASIDE},
                        jobs={21: ["decide", "gates", "carrier"]})
        call(gh)
        self.assertEqual(gh.reran, [21])

    def test_a_newer_queued_run_with_no_conclusion_owes_nothing_yet(self):
        gh = FakeGitHub([run("go-test.yml", 22, "hp-dgo", "cancelled"),
                         run("go-test.yml", 23, "hp-dgo", None, "queued")], {220: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_pull_requests_run_does_not_hide_a_push_run(self):
        gh = FakeGitHub([run("go-test.yml", 24, "mac-dgo", "cancelled"),
                         run("go-test.yml", 25, "mac-dgo", "success", event="pull_request")], {240: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [24])

    def test_a_run_attempted_max_times_is_said_not_asked(self):
        gh = FakeGitHub([run("go-test.yml", 26, "mac-dgo", "cancelled", attempt=re_ask.MAX_ATTEMPTS)], {260: ASIDE})
        _, out = call(gh)
        self.assertEqual(gh.reran, [])
        self.assertIn("stepped aside %d times" % re_ask.MAX_ATTEMPTS, out)

    def test_an_answer_that_is_not_a_list_does_not_stop_the_others(self):
        class Odd(FakeGitHub):
            def annotations(self, check_run_id):
                return {"message": "Not Found"} if check_run_id == 270 else super().annotations(check_run_id)
        gh = Odd([run("go-test.yml", 27, "a", "cancelled"), run("go-test.yml", 28, "b", "cancelled")], {280: ASIDE})
        rc, _ = call(gh)
        self.assertEqual((rc, gh.reran), (0, [28]))

    def test_one_run_that_raises_does_not_stop_the_others(self):
        class Raising(FakeGitHub):
            def jobs(self, run_id):
                if run_id == 29:
                    raise RuntimeError("odd body")
                return super().jobs(run_id)
        gh = Raising([run("go-test.yml", 29, "a", "cancelled"), run("go-test.yml", 30, "b", "cancelled")],
                     {290: ASIDE, 300: ASIDE})
        _, out = call(gh)
        self.assertEqual(gh.reran, [30])
        self.assertIn("run 29 on a could not be read", out)

    def test_a_dry_run_asks_nothing(self):
        gh = FakeGitHub([run("gates-hosted.yml", 19, "mac-dgo", "cancelled")], {190: ASIDE})
        _, out = call(gh, "--dry-run")
        self.assertEqual(gh.reran, [])
        self.assertIn("would ask again gates-hosted.yml on mac-dgo (run 19)", out)

    def test_the_proof_runs_it_as_its_last_job(self):
        wf = (REPO / ".github" / "workflows" / "gates-hosted.yml").read_text(encoding="utf-8")
        job = wf[wf.index("\n  re-ask:"):]
        for needle in ("needs: [decide, gates, carrier, green]",
                       "if: always() && github.event_name == 'push' && github.ref == 'refs/heads/dgo-stable'",
                       "continue-on-error: true", "actions: write", "checks: read", "self-hosted",
                       "scripts/ci/re-ask.py", "persist-credentials: false"):
            self.assertIn(needle, job, needle)
        self.assertFalse((REPO / ".github" / "workflows" / "re-ask.yml").exists(),
                         "no workflow_run file: that trigger fires only from the default branch")

    def test_step_aside_still_leaves_the_notice_this_reads(self):
        guard = (REPO / "scripts" / "ci" / "step-aside").read_text(encoding="utf-8")
        self.assertIn(f"::notice title={re_ask.NOTICE_TITLE}::", guard)


if __name__ == "__main__":
    unittest.main(verbosity=1)
