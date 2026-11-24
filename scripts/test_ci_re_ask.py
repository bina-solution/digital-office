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
    def __init__(self, runs, annotations=None, broken=(), jobs=None, held=(), unwatched=(), down=()):
        self._runs, self._ann, self._broken, self._jobs = runs, annotations or {}, set(broken), jobs or {}
        # heads the proof's tree holds; (path, sha) of workflow files that start no watcher; questions that fail
        self._held, self._unwatched, self._down = set(held), set(unwatched), set(down)
        self.reran, self.compared = [], []

    def compare(self, base, head):
        if "compare" in self._down:
            raise urllib.error.URLError("down")
        self.compared.append((base, head))
        return "ahead" if base in self._held else "diverged"

    def watches(self, path, sha):
        if "watches" in self._down:
            raise urllib.error.URLError("down")
        return (path, sha) not in self._unwatched

    def runs(self, workflow, branch="", status="", pages=1):
        if workflow in self._broken:
            raise urllib.error.URLError("down")
        return [r for r in self._runs if r["wf"] == workflow and (not branch or r["head_branch"] == branch)
                and (not status or r["status"] == status)]

    def jobs(self, run_id):
        """One job per run (check run <id>0), or the ones given for it — a name, (name, conclusion), or (name,
        conclusion, runner) where None is a job never on a runner (the runner is the Dell's otherwise): check runs
        <id>0, <id>1, …"""
        given = self._jobs.get(run_id, ["gates"])
        out = []
        for i, g in enumerate(given):
            # a name; or (name, conclusion[, runner[, labels]]) — the Dell's runner and labels unless a row says otherwise
            row = g if isinstance(g, tuple) else (g, None, None)
            name, conclusion = row[0], row[1]
            runner = row[2] if len(row) > 2 else "portable-ssd"
            labels = row[3] if len(row) > 3 else ("self-hosted", "portable")
            out.append({"name": name, "conclusion": conclusion, "runner_name": runner, "labels": list(labels),
                        "check_run_url": f"https://api.github.com/repos/o/r/check-runs/{run_id}{i}"})
        return out

    def annotations(self, check_run_id):
        return self._ann.get(check_run_id, [])

    def rerun(self, run_id):
        self.reran.append(run_id)


def run(wf, rid, branch, conclusion, status="completed", event="push", attempt=1, sha=""):
    r = {"wf": wf, "id": rid, "head_branch": branch, "conclusion": conclusion, "status": status, "event": event,
         "run_attempt": attempt}
    if sha:   # a run as GitHub lists it: its head, and its workflow's file
        r.update(head_sha=sha, path=".github/workflows/" + wf)
    return r


def proof(rid, status="in_progress"):
    return run("gates-hosted.yml", rid, "dgo-stable", None, status)


def call(gh, *extra, sha="", gates="success"):
    """re-ask as the proof's last job: this run, this proof's head and what its gates ended in — set here, never the
    environment's own (on the runner, G72 runs this test inside a job that has a GITHUB_SHA of its own)."""
    out = io.StringIO()
    os.environ["GITHUB_RUN_ID"] = str(OWN)
    os.environ["GITHUB_SHA"] = sha
    os.environ["PROOF_GATES"] = gates
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

    def test_the_lines_other_workflows_that_stepped_aside_for_its_proof_are_asked_again(self):
        # DGO-2111: go-test and the Android builds of a dgo-stable push yield to its proof (step-aside --line-too); the
        # proof's last job asks them again — the line's own runs, never the proof's
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 19, "dgo-stable", "cancelled"),
                         run("android-app.yml", 20, "dgo-stable", "cancelled"),
                         run("gates-hosted.yml", 21, "dgo-stable", "cancelled")], {190: ASIDE, 200: ASIDE, 210: ASIDE})
        rc, out = call(gh)
        self.assertEqual((rc, sorted(gh.reran)), (0, [19, 20]))
        self.assertIn("asked again go-test.yml on dgo-stable", out)

    def test_a_line_run_cancelled_by_hand_is_not_asked_again(self):
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 22, "dgo-stable", "cancelled")], {})
        call(gh)
        self.assertEqual(gh.reran, [])

    # ── a build of the line: a newer run hides an older one only when it BUILT (the second reader, DGO-2123) ──
    def test_a_newer_line_run_that_built_nothing_does_not_hide_a_build_that_stepped_aside(self):
        # P1's phone said «build», its apk stepped aside; P2 touched no phone path: its run succeeded with apk skipped
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 40, "dgo-stable", "cancelled"),
                         run("android-app.yml", 41, "dgo-stable", "success")], {401: ASIDE},
                        jobs={40: [("phone", "success"), ("apk", "cancelled")],
                              41: [("phone", "success"), ("apk", "skipped")]})
        rc, out = call(gh)
        self.assertEqual((rc, gh.reran), (0, [40]))
        self.assertIn("asked again android-app.yml on dgo-stable (run 40)", out)

    def test_a_newer_line_run_that_built_covers_the_older_one(self):
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 42, "dgo-stable", "cancelled"),
                         run("android-app.yml", 43, "dgo-stable", "success")], {421: ASIDE},
                        jobs={42: [("phone", "success"), ("apk", "cancelled")],
                              43: [("phone", "success"), ("apk", "success")]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_only_the_newest_line_build_that_stepped_aside_is_asked(self):
        # its build holds the older one's changes; a failed run between them hides nothing
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 44, "dgo-stable", "cancelled"),
                         run("android-app.yml", 45, "dgo-stable", "failure"),
                         run("android-app.yml", 46, "dgo-stable", "cancelled"),
                         run("android-app.yml", 47, "dgo-stable", "success")], {441: ASIDE, 461: ASIDE},
                        jobs={44: [("phone", "success"), ("apk", "cancelled")],
                              45: [("phone", "success"), ("apk", "failure")],
                              46: [("phone", "success"), ("apk", "cancelled")],
                              47: [("phone", "success"), ("apk", "skipped")]})
        call(gh)
        self.assertEqual(gh.reran, [46])

    def test_a_newer_line_build_that_failed_is_that_trees_answer(self):
        # an older tree is never built behind a newer build that failed (the second reader of the fix)
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 60, "dgo-stable", "cancelled"),
                         run("android-app.yml", 61, "dgo-stable", "failure")], {601: ASIDE},
                        jobs={60: [("phone", "success"), ("apk", "cancelled")],
                              61: [("phone", "success"), ("apk", "failure")]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_newer_line_run_cancelled_by_hand_is_not_undone(self):
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 62, "dgo-stable", "cancelled"),
                         run("android-app.yml", 63, "dgo-stable", "cancelled")], {621: ASIDE},
                        jobs={62: [("phone", "success"), ("apk", "cancelled")],
                              63: [("phone", "success"), ("apk", "cancelled")]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_line_build_asked_too_often_is_said_with_how_to_run_it_by_hand(self):
        # a push to the line builds no APK unless it touches the phone's paths: «push again» would not ask it
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 64, "dgo-stable", "cancelled",
                                          attempt=re_ask.MAX_ATTEMPTS)], {641: ASIDE},
                        jobs={64: [("phone", "success"), ("apk", "cancelled")]})
        _, out = call(gh)
        self.assertEqual(gh.reran, [])
        self.assertIn("re-run it by hand: gh run rerun 64 --failed", out)

    def test_a_newer_line_build_still_going_decides_for_itself(self):
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 48, "dgo-stable", "cancelled"),
                         run("android-app.yml", 49, "dgo-stable", None, "in_progress")], {481: ASIDE},
                        jobs={48: [("phone", "success"), ("apk", "cancelled")]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_public_copy_run_that_stepped_aside_is_asked_again(self):
        # its copy job steps aside on an office branch; it was in no list re-ask read, so nothing ran it again
        gh = FakeGitHub([proof(OWN), run("public-copy.yml", 70, "mac-dgo", "cancelled"),
                         run("public-copy.yml", 71, "mac-dgo", "skipped")], {700: ASIDE})
        rc, out = call(gh)
        self.assertEqual((rc, gh.reran), (0, [70]))
        self.assertIn("asked again public-copy.yml on mac-dgo", out)
        # …and its run on the line too, since its guard says --line-too there (DGO-2123: a batch asking for a copy
        # started the copy beside its proof, and it could take the runner first — the copy now follows its proof): the
        # copy of THIS proof's head, once it is green
        head = "f" * 40
        gh = FakeGitHub([proof(OWN), run("public-copy.yml", 72, "dgo-stable", "cancelled", sha=head)], {720: ASIDE})
        call(gh, sha=head)
        self.assertEqual(gh.reran, [72])
        # …never after a red proof (it would copy a red commit, and hold the runner ahead of the fix's proof)
        gh = FakeGitHub([proof(OWN), run("public-copy.yml", 75, "dgo-stable", "cancelled", sha=head)], {750: ASIDE})
        rc, out = call(gh, sha=head, gates="failure")
        self.assertEqual(gh.reran, [])
        self.assertIn("not this green proof's head", out)
        # …nor an older batch's copy, when this batch asked for none (its own run skipped, walked past)
        gh = FakeGitHub([proof(OWN), run("public-copy.yml", 73, "dgo-stable", "cancelled", sha="e" * 40),
                         run("public-copy.yml", 74, "dgo-stable", "skipped", sha=head)], {730: ASIDE})
        call(gh, sha=head)
        self.assertEqual(gh.reran, [])

    def test_android_engine_on_the_line_is_never_asked_here(self):
        # its guest does not step aside on dgo-stable (no --line-too: an [android-engine] push's APK waits for it)
        gh = FakeGitHub([proof(OWN), run("android-engine.yml", 50, "dgo-stable", "cancelled")], {500: ASIDE})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_the_lines_runs_come_first_under_the_cut(self):
        runs = [run("go-test.yml", 200 + i, f"b{i}", "cancelled") for i in range(re_ask.MAX + 1)]
        runs.append(run("android-app.yml", 300, "dgo-stable", "cancelled"))
        ann = {(200 + i) * 10: ASIDE for i in range(re_ask.MAX + 1)}
        ann[3001] = ASIDE
        gh = FakeGitHub([proof(OWN)] + runs, ann, jobs={300: [("phone", "success"), ("apk", "cancelled")]})
        call(gh)
        self.assertEqual(len(gh.reran), re_ask.MAX)
        self.assertEqual(gh.reran[0], 300, "the line's build is asked first, never cut")

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
        # after a hand-run proof of dgo-stable too (DGO-2123): step-aside yields to one as to any proof
        for needle in ("needs: [decide, gates, carrier, green]",
                       "if: always() && github.ref == 'refs/heads/dgo-stable'",
                       "continue-on-error: true", "actions: write", "checks: read", "self-hosted",
                       "scripts/ci/re-ask.py", "persist-credentials: false"):
            self.assertIn(needle, job, needle)
        self.assertFalse((REPO / ".github" / "workflows" / "re-ask.yml").exists(),
                         "no workflow_run file: that trigger fires only from the default branch")

    def test_step_aside_still_leaves_the_notices_this_reads(self):
        # a yield's title by default, an expiry's when a newer run supersedes (scripts/test_ci_step_aside.py runs both)
        guard = (REPO / "scripts" / "ci" / "step-aside").read_text(encoding="utf-8")
        self.assertIn("::notice title=${title}::", guard)
        self.assertIn('title="${3:-%s}"' % re_ask.NOTICE_TITLE, guard)
        self.assertRegex(guard, r"\b%s \|\| return 0" % re_ask.SUPERSEDED)

    # ── what a cancelled run owes, and two answers on an office branch (DGO-2123) ──────────────────────────
    def test_a_run_cleared_while_it_waited_is_asked_again(self):
        # step-aside cleared the way for a proof: none of the run's cancelled jobs was ever on a runner
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 31, "mac-dgo", "cancelled")],
                        jobs={31: [("decide", "success"), ("gates", "cancelled", None), ("carrier", "cancelled", None)]})
        rc, out = call(gh)
        self.assertEqual(gh.reran, [31])

    def test_a_run_whose_stopped_job_waited_for_another_runner_is_a_persons_cancel(self):
        # android-engine's qemu waits for GitHub's own runner, which takes no job while billing is stopped: a run
        # cancelled then was not cleared for a proof, and is not asked again (the second reader of 59774eeb7)
        gh = FakeGitHub([proof(OWN), run("android-engine.yml", 30, "mac-dgo", "cancelled", event="workflow_dispatch")],
                        jobs={30: [("qemu", "cancelled", None, ("ubuntu-24.04",)), ("guest", "cancelled", None)]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_run_a_person_stopped_at_work_is_not(self):
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 32, "mac-dgo", "cancelled")],
                        jobs={32: [("decide", "success"), ("gates", "cancelled"), ("carrier", "cancelled", None)]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_superseded_run_owes_nothing(self):
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 33, "vps1-dgo", "cancelled")],
                        {330: [{"title": "superseded", "message": "run 34 tests this run's head"}], 331: ASIDE},
                        jobs={33: [("test (packaging/dgo)", "cancelled"), ("test (packaging/trust)", "cancelled", None)]})
        call(gh)
        self.assertEqual(gh.reran, [])

    def test_a_run_this_proof_holds_is_covered(self):
        # the king, 2026-11-20: mac-dgo's gates runs of ce4252547 and ed80b1d34 waited behind batch 100, which held both
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 35, "mac-dgo", "cancelled", sha="e" * 40)], {350: ASIDE},
                        held={"e" * 40})
        rc, out = call(gh, sha="f" * 40)
        self.assertEqual(gh.reran, [])
        self.assertEqual(gh.compared, [("e" * 40, "f" * 40)])
        self.assertIn("run 35 on mac-dgo — its head eeeeeeeee is in this proof's tree: covered, not asked again", out)

    def test_a_run_this_proof_does_not_hold_is_asked(self):
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 36, "mac-dgo", "cancelled", sha="e" * 40)], {360: ASIDE})
        call(gh, sha="f" * 40)
        self.assertEqual(gh.reran, [36])

    def test_only_a_green_proof_covers(self):
        # re-ask runs `always()`: after a proof whose gates were cancelled or never asked, nothing was answered; a red
        # one may have stopped in its fast lane, before the slow gates ran (the reader of ac436e0b8)
        for gates, reran in (("cancelled", [43]), ("skipped", [43]), ("", [43]), ("failure", [43]), ("success", [])):
            gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 43, "mac-dgo", "cancelled", sha="e" * 40)],
                            {430: ASIDE}, held={"e" * 40})
            rc, out = call(gh, sha="f" * 40, gates=gates)
            self.assertEqual(gh.reran, reran, gates)
            if reran:
                self.assertIn("no run is taken as covered by it", out)

    def test_public_copy_and_the_android_builds_are_held_to_neither_answer(self):
        # public-copy's copy is of refs/green, which no proof makes; the builds never had a watcher (the second reader):
        # asked again as before — their hold of the runner is said in the issue, not paid with a lost build
        gh = FakeGitHub([proof(OWN), run("public-copy.yml", 44, "mac-dgo", "cancelled", sha="e" * 40),
                         run("android-app.yml", 45, "mac-dgo", "cancelled", event="workflow_dispatch", sha="d" * 40)],
                        {440: ASIDE, 450: ASIDE}, held={"e" * 40, "d" * 40},
                        unwatched={(".github/workflows/public-copy.yml", "e" * 40),
                                   (".github/workflows/android-app.yml", "d" * 40)})
        call(gh, sha="f" * 40)
        self.assertEqual(sorted(gh.reran), [44, 45])
        self.assertEqual(gh.compared, [], "neither is ever taken as covered")

    def test_coverage_is_never_a_hand_runs_nor_an_unanswered_question(self):
        gh = FakeGitHub([proof(OWN), run("android-app.yml", 37, "mac-dgo", "cancelled", event="workflow_dispatch",
                                         sha="e" * 40)], {370: ASIDE}, held={"e" * 40})
        call(gh, sha="f" * 40)
        self.assertEqual((gh.reran, gh.compared), ([37], []), "an explicit ask is answered for its own tree")
        gh = FakeGitHub([proof(OWN), run("gates-hosted.yml", 38, "mac-dgo", "cancelled", sha="e" * 40)],
                        {380: ASIDE}, held={"e" * 40}, down={"compare"})
        rc, out = call(gh, sha="f" * 40)
        self.assertEqual(gh.reran, [38])
        self.assertIn("could not be read (URLError); it is asked as before", out)

    def test_the_lines_own_runs_are_never_covered_by_the_proof(self):
        # the line's go-test of this very batch has this proof's head: it is still owed (the proof runs no go test)
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 39, "dgo-stable", "cancelled", sha="f" * 40)], {390: ASIDE},
                        held={"f" * 40})
        call(gh, sha="f" * 40)
        self.assertEqual((gh.reran, gh.compared), ([39], []))

    def test_a_run_that_cannot_step_aside_while_it_works_is_not_asked(self):
        # batch 98, 2026-11-20: hp-dgo's go-test, asked again at 14:00:29 by batch 97's re-ask, held the runner from
        # 14:01:14 to 14:17:43 — its go-test.yml predates the watcher — while batch 98's proof waited
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 40, "hp-dgo", "cancelled", sha="1" * 40)], {400: ASIDE},
                        unwatched={(".github/workflows/go-test.yml", "1" * 40)})
        rc, out = call(gh)
        self.assertEqual(gh.reran, [])
        self.assertIn("run 40 (go-test.yml on hp-dgo) cannot step aside while it works — .github/workflows/go-test.yml "
                      "at 111111111 starts no watcher", out)
        # …a file that cannot be read is asked as before; the line's builds never are held to it (re-ask's line_build)
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 41, "hp-dgo", "cancelled", sha="1" * 40)], {410: ASIDE},
                        unwatched={(".github/workflows/go-test.yml", "1" * 40)}, down={"watches"})
        call(gh)
        self.assertEqual(gh.reran, [41])
        gh = FakeGitHub([proof(OWN), run("go-test.yml", 42, "dgo-stable", "cancelled", sha="1" * 40)], {420: ASIDE},
                        unwatched={(".github/workflows/go-test.yml", "1" * 40)})
        call(gh)
        self.assertEqual(gh.reran, [42])

    def test_the_watcher_is_read_from_a_step_not_from_a_comment(self):
        for text, watches in (('  run: GH_TOKEN="${T}" bash scripts/ci/step-aside --watch & w=$!\n', True),
                              ('  run: bash "${GITHUB_WORKSPACE}/scripts/ci/step-aside" --watch --line-too &\n', True),
                              ("# each lane starts `scripts/ci/step-aside --watch` beside gates.sh\n", False),
                              ("  run: bash .step-aside/scripts/ci/step-aside --line-too && rm -rf .step-aside\n", False),
                              ("  run: bash scripts/ci/step-aside  # then --watch, some day\n", False)):
            self.assertEqual(bool(re_ask.WATCH.search(text)), watches, text)
        # and the files of today's line watch where WATCHERS says they do
        for wf in ("gates-hosted.yml", "go-test.yml"):
            self.assertTrue(re_ask.WATCH.search((REPO / ".github" / "workflows" / wf).read_text(encoding="utf-8")), wf)


if __name__ == "__main__":
    unittest.main(verbosity=1)
