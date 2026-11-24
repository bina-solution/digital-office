#!/usr/bin/env python3
"""step-aside (scripts/ci/step-aside): on the one runner, a version's proof goes first (DGO-1819).

    python3 scripts/test_ci_step_aside.py

The Dell's one self-hosted runner serves every workflow, and GitHub has no queue priorities: a version's proof
(gates-hosted on dgo-stable) stood 45 minutes behind office-branch jobs, one of them the gates of a push made 2.5
hours before (issues/the-versions-proof-stands-behind-office-branch-jobs-on-the-one-runner-which-has-no-queue-
priorities.yaml). Every office-branch job on that runner now asks step-aside first. These are its decisions.

GitHub is a stand-in: `curl` on PATH is a small script that answers each API path from the case's table and logs
every call (its method, its URL, its command line), so a decision is read from what was ASKED and what was
CANCELLED, not only from what the guard printed. It runs on the bash it finds (3.2 on a Mac, 5 on the runner); no
network, no token. The last cases read the five workflows: every job of theirs on the runner calls the guard before
anything else, and only those jobs hold `actions: write`. Two shapes: a job keeps dgo-stable and every non-branch ref
out (GUARD_IF) and never says --line-too — the proof's jobs (on dgo-stable they ARE the proof), android-app's `phone`
(a minute's decision) and android-engine's `guest` (an `[android-engine]` push's APK waits for it); or it is one of
LINE_JOBS — go-test's test, android-app's apk, public-copy's copy — which keep only the non-branch refs out (LINE_IF) and say --line-too, so
on dgo-stable too they yield to its proof (DGO-2111). A copy with an `if:` turned the wrong way, swapped for the other
shape, or with --line-too on the wrong job (read from the guard's own arguments, not from its line), is refused — and
so is a runner job of the line's workflows in neither LINE_JOBS nor LINE_EXEMPT (each exemption says why), or one that
runs on dgo-stable alone without --line-too: only the proof's own jobs may run there unguarded. re-ask's LINE is held to
the same jobs.

WHILE A JOB WORKS (--watch, DGO-2123): asked only at its first step, mac-dgo's gates held the runner from 08:44 while
batch 89's proof, pushed 08:50, waited for a person to cancel them. The long steps WATCHERS names start a watcher beside
their work — in the background, before the work, with a token of its own that never reaches the work's environment,
killed when the step ends; it asks one question a turn and steps aside as the first step would. A watcher anywhere
else is refused: there a mid-step yield would need a person (a hand-run of the Android builds is dispatched again).
"""
import copy
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "ci" / "step-aside"
# public-copy too (DGO-2123): its copy job took the runner for 15–29 minutes, and no structural check read its file;
# office-images too (the king, DGO-2123): an `[office-images]` push's QEMU builds take it for up to 60 and asked nothing
WORKFLOWS = ("gates-hosted.yml", "go-test.yml", "android-app.yml", "android-engine.yml", "public-copy.yml",
             "office-images.yml", "sim-build.yml")   # sim-build: on the Dell's runner since 2026-11-20 (the king)
PROOF = "gates-hosted.yml"
GUARD_IF = "startsWith(github.ref, 'refs/heads/') && github.ref != 'refs/heads/dgo-stable'"   # office branches
LINE_IF = "startsWith(github.ref, 'refs/heads/')"                                             # …and the line
# the jobs that say --line-too (DGO-2111): on dgo-stable they yield to its proof — public-copy's copy since DGO-2123
LINE_JOBS = {("go-test.yml", "test"), ("android-app.yml", "apk"), ("public-copy.yml", "copy")}
# …and the line's other runner jobs that do not, each with why: a job of these workflows in neither list is refused —
# on dgo-stable it would go ahead of the proof, and nothing would have decided that it may
LINE_EXEMPT = {
    ("android-app.yml", "phone"): "a minute's decision: a run that yields has decided to build (re-ask's line_build)",
    ("android-engine.yml", "guest"): "an [android-engine] push's APK waits for it and reads a cancelled engine as failed",
    ("office-images.yml", "build"): "its `on:` is mac-dgo alone: it never runs on the line, so there is no run there to "
                                    "yield",
    ("sim-build.yml", "build"): "its `on:` leaves dgo-stable out (branches-ignore): it never runs on the line",
}
# The long steps that keep asking while they work (step-aside --watch, DGO-2123): (workflow, job) → the work of each
# watched step, as its run text names it — the gates' two lanes (twenty minutes), go-test's legs (packaging/dgo's, eight)
WATCHERS = {("gates-hosted.yml", "gates"): ("scripts/ci/gates.sh --fast", "scripts/ci/gates.sh --slow"),
            ("gates-hosted.yml", "slow"): ("scripts/ci/gates.sh --slow",),   # an office branch's slow lane (DGO-2123)
            ("go-test.yml", "test"): ("go test ",)}
# The proof's jobs that clear the way for its next job at their end (step-aside --clear, DGO-2123): its last step, on a
# push of dgo-stable alone, never failing the proof
CLEARS = {("gates-hosted.yml", "decide"), ("gates-hosted.yml", "gates"), ("gates-hosted.yml", "carrier"),
          ("gates-hosted.yml", "go")}   # forward-auth's tests before green, when it changed (the second reader, DGO-2123)
TOKEN = "ghs_not-a-real-token-0123456789"
RUN = "4242"
RUNNER = "portable-ssd"

# A stand-in for curl: the route whose `match` is in the URL (and whose method is the call's) answers; anything
# else is a failure, as curl -f would say it. Each call is one JSON line in the log.
CURL = r'''#!{python}
import json, os, signal, sys
args = sys.argv[1:]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
url = [a for a in args if a.startswith("http")][-1]
headers = sys.stdin.read() if "@-" in args else ""
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps({"method": method, "url": url, "argv": args, "headers": headers}) + "\n")
for r in json.load(open(os.environ["STUB_ROUTES"])):
    if r["match"] in url and r.get("method", "GET") == method:
        if r.get("term_parent"):   # the step's end killing the watcher while this call is on its way
            os.kill(os.getppid(), signal.SIGTERM)
        if "seq" in r:   # its answers in turn, the last one again and again: the world changing while a watcher asks
            with open(os.environ["STUB_LOG"]) as log:
                n = sum(1 for line in log if r["match"] in json.loads(line)["url"])
            r = r["seq"][min(n, len(r["seq"])) - 1]
        if r["status"] >= 400:
            sys.stderr.write("curl: (22) The requested URL returned error: %d\n" % r["status"])
            sys.exit(22)
        sys.stdout.write(json.dumps(r.get("body", {})))
        sys.exit(0)
sys.stderr.write("curl: (22) The requested URL returned error: 404 (no route in the stand-in)\n")
sys.exit(22)
'''


def runs(status, run_id=None):
    """The proof's runs for one status: one run, or none."""
    body = {"total_count": 1, "workflow_runs": [{"id": run_id}]} if run_id else {"total_count": 0, "workflow_runs": []}
    return {"match": "workflows/gates-hosted.yml/runs?branch=dgo-stable&status=%s&" % status, "status": 200, "body": body}


def no_proof():
    return [runs(s) for s in ("queued", "pending", "waiting", "requested", "in_progress")]


def jobs(*rows, status=200):
    """This run's own jobs: (name, status, runner_name) rows."""
    body = {"total_count": len(rows), "jobs": [{"id": i + 1, "name": n, "status": s, "runner_name": r}
                                               for i, (n, s, r) in enumerate(rows)]}
    return {"match": "/actions/runs/%s/jobs?" % RUN, "status": status, "body": body}


# gates-hosted's gates job taking the runner: decide has COMPLETED (it always has, by then), carrier waits
ALONE = jobs(("decide", "completed", RUNNER), ("gates", "in_progress", RUNNER), ("carrier", "queued", None))
CANCEL = {"match": "/actions/runs/%s/cancel" % RUN, "method": "POST", "status": 202, "body": {}}
HEAD_MOVED = {"match": "/git/ref/heads/", "status": 200, "body": {"object": {"sha": "b" * 40}}}
# A quiet repository, after every case's own routes: nothing else waits for the runner (the way to clear, DGO-2123) and
# no newer run of the workflow (a superseded run's question) — a case that is about them says otherwise first
QUIET = [{"match": "/actions/runs?status=", "status": 200, "body": {"total_count": 0, "workflow_runs": []}},
         {"match": "&event=push&per_page=20", "status": 200, "body": {"total_count": 0, "workflow_runs": []}}]


def waiting(rid, wf, branch, status="queued", event="push", sha="c"):
    """A run of the repository's list (actions/runs?status=…), as the way's clearing reads it."""
    return {"id": rid, "path": ".github/workflows/" + wf, "head_branch": branch, "event": event, "status": status,
            "head_sha": sha * 40}


def listed(status, *rows):
    return {"match": "/actions/runs?status=%s&" % status, "status": 200,
            "body": {"total_count": len(rows), "workflow_runs": list(rows)}}


def their_jobs(rid, *rows):
    """Another run's jobs: (name, status, labels) rows — the labels its runs-on asked for."""
    return {"match": "/actions/runs/%s/jobs?" % rid, "status": 200,
            "body": {"jobs": [{"id": i + 1, "name": n, "status": s, "labels": list(lb), "conclusion": None}
                              for i, (n, s, lb) in enumerate(rows)]}}


def cancel_of(rid):
    return {"match": "/actions/runs/%s/cancel" % rid, "method": "POST", "status": 202, "body": {}}


PORTABLE = ("self-hosted", "portable")


class StepAside(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="step-aside-")
        bin_ = os.path.join(self.tmp, "bin")
        os.mkdir(bin_)
        with open(os.path.join(bin_, "curl"), "w") as f:
            f.write(CURL.replace("{python}", sys.executable))
        os.chmod(os.path.join(bin_, "curl"), 0o755)
        os.symlink(sys.executable, os.path.join(bin_, "python3"))   # the guard's JSON reader is this interpreter
        self.bin = bin_
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guard(self, routes, ref="refs/heads/mac-dgo", event="push", args=(), extra=None):
        p, said, calls, output = self.ask(routes, ref, event, args, extra)
        self.assertEqual(len(said), 1, "one decision line, got:\n" + p.stdout + p.stderr)
        return p, said[0], calls, output

    def watch(self, routes, ref="refs/heads/mac-dgo", event="push", args=(), extra=None):
        """step-aside --watch with no pause between asks: every case ends in a proof ahead, or in nothing to watch."""
        return self.ask(routes, ref, event, ["--watch", *args], dict({"STEP_ASIDE_EVERY": "0"}, **(extra or {})))

    def ask(self, routes, ref, event, args, extra):
        routes_file = os.path.join(self.tmp, "routes.json")
        with open(routes_file, "w") as f:
            json.dump(list(routes) + QUIET, f)
        out_file = os.path.join(self.tmp, "github_output")
        if os.path.exists(self.log):
            os.remove(self.log)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "GH_", "RUNNER_"))}
        env.update({"PATH": self.bin + os.pathsep + env.get("PATH", "/usr/bin:/bin"), "STUB_LOG": self.log,
                    "STUB_ROUTES": routes_file, "STEP_ASIDE_WAIT": "0", "GH_TOKEN": TOKEN,
                    "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": "https://api.example.invalid",
                    "GITHUB_SERVER_URL": "https://github.example.invalid", "GITHUB_REF": ref,
                    "GITHUB_REF_NAME": ref.rsplit("/", 1)[-1], "GITHUB_EVENT_NAME": event, "GITHUB_SHA": "a" * 40,
                    "GITHUB_RUN_ID": RUN, "GITHUB_JOB": "gates", "RUNNER_NAME": RUNNER, "GITHUB_OUTPUT": out_file})
        env.update(extra or {})
        p = subprocess.run(["bash", str(GUARD), *args], capture_output=True, text=True, env=env, timeout=60)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = [json.loads(line) for line in f if line.strip()]
        said = [ln for ln in p.stdout.splitlines() if ln.startswith("step-aside=")]
        output = ""
        if os.path.exists(out_file):
            with open(out_file) as f:
                output = f.read()
        return p, said, calls, output

    def cancelled(self, calls):
        return [c for c in calls if c["method"] == "POST" and c["url"].endswith("/actions/runs/%s/cancel" % RUN)]

    def assert_aside(self, p, said, calls, output, why):
        self.assertTrue(said.startswith("step-aside=yes"), said)
        self.assertIn(why, p.stdout)
        self.assertEqual(len(self.cancelled(calls)), 1, "its own run is cancelled once")
        self.assertIn("aside=yes", output)
        # the cancel was ACCEPTED and nothing stopped the step (STEP_ASIDE_WAIT=0): red, never a green
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("::error::", p.stdout)

    def assert_runs(self, p, said, calls):
        self.assertTrue(said.startswith("step-aside=no"), said)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.cancelled(calls), [], "nothing is cancelled")

    # ── the decisions ──────────────────────────────────────────────────────────────────────────────
    def test_proof_queued_steps_aside(self):
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL])
        self.assert_aside(p, said, calls, output, "::notice title=step-aside::a version's proof is ahead (run 111, queued")
        self.assertIn("this office-branch job steps aside; the proof's last job (re-ask) asks again once it has ended", p.stdout)
        # decide had COMPLETED and carrier was waiting: neither holds the cancel back
        self.assertTrue(any(c["url"].endswith("/actions/runs/%s/jobs?filter=latest&per_page=100" % RUN) for c in calls))

    def test_proof_in_progress_steps_aside(self):
        p, said, calls, output = self.guard(
            [runs("queued"), runs("pending"), runs("waiting"), runs("requested"), runs("in_progress", 222), ALONE,
             CANCEL])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 222, in_progress")

    def proof_jobs(self, run_id, *rows, status=200):
        body = {"jobs": [{"id": i + 1, "name": n, "status": s} for i, (n, s) in enumerate(rows)]}
        return {"match": "/actions/runs/%s/jobs?" % run_id, "status": status, "body": body}

    def in_progress(self, *ids):
        body = {"total_count": len(ids), "workflow_runs": [{"id": i} for i in ids]}
        return [runs("queued"), runs("pending"), runs("waiting"), runs("requested"),
                {"match": "workflows/gates-hosted.yml/runs?branch=dgo-stable&status=in_progress&", "status": 200,
                 "body": body}]

    def test_a_proof_whose_last_job_alone_is_left_is_not_ahead(self):
        # the runs its re-ask job asks again must not step aside for it once more
        done = [("decide", "completed"), ("gates", "completed"), ("carrier", "completed"), ("green", "completed")]
        p, said, calls, _ = self.guard(self.in_progress(222) + [
            self.proof_jobs(222, *done, ("re-ask", "in_progress")), ALONE, CANCEL])
        self.assert_runs(p, said, calls)
        self.assertIn("run 222 is a version's proof whose last job (re-ask) alone is left", p.stdout)

    def test_a_proof_still_at_work_is_ahead(self):
        p, said, calls, output = self.guard(self.in_progress(222) + [
            self.proof_jobs(222, ("decide", "completed"), ("gates", "in_progress"), ("re-ask", "queued")), ALONE, CANCEL])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 222, in_progress")

    def test_a_proof_whose_jobs_cannot_be_read_is_ahead(self):
        p, said, calls, output = self.guard(self.in_progress(222) + [self.proof_jobs(222, status=500), ALONE, CANCEL])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 222, in_progress")

    def test_an_ending_proof_does_not_hide_another_in_progress(self):
        done = [("decide", "completed"), ("gates", "completed"), ("re-ask", "in_progress")]
        p, said, calls, output = self.guard(self.in_progress(222, 333) + [
            self.proof_jobs(222, *done), self.proof_jobs(333, ("decide", "completed"), ("gates", "in_progress")),
            ALONE, CANCEL])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 333, in_progress")

    def test_a_queued_proof_is_ahead_without_asking_its_jobs(self):
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL])
        self.assert_aside(p, said, calls, output, "(run 111, queued")
        self.assertFalse(any("/actions/runs/111/jobs" in c["url"] for c in calls))

    def test_no_proof_runs_and_asks_every_status(self):
        p, said, calls, _ = self.guard(no_proof() + [ALONE, CANCEL])
        self.assert_runs(p, said, calls)
        asked = [c["url"] for c in calls]
        self.assertEqual(sum("status=" in u for u in asked), 5, "every waiting status is asked, of any age")
        self.assertEqual(len(asked), 5, "nothing else is asked: %s" % asked)

    def test_a_moved_head_is_not_a_reason(self):
        # DGO-1797: the three mac-dgo gates verdicts since 11-10 22:31Z had 6, 2 and 26 later pushes before their
        # proof job started — a head check would have cancelled every one
        p, said, calls, _ = self.guard(no_proof() + [HEAD_MOVED, ALONE, CANCEL])
        self.assert_runs(p, said, calls)
        self.assertFalse(any("/git/ref" in c["url"] for c in calls), "the branch's head is never asked")

    def test_dgo_stable_runs_and_asks_nothing(self):
        # without --line-too (gates-hosted, the proof itself): a proof queued is not a reason, nothing is asked
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/heads/dgo-stable")
        self.assert_runs(p, said, calls)
        self.assertEqual(calls, [], "dgo-stable asks GitHub nothing")
        self.assertIn("a version's proof never steps aside", said)

    # ── the line's other workflows: --line-too (DGO-2111) ──────────────────────────────────────────
    def test_dgo_stable_with_line_too_steps_aside_for_a_queued_proof(self):
        # 2026-11-19: batch 87's gates waited behind its own android-app build and its go-test
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/heads/dgo-stable",
                                            args=["--line-too"], extra={"GITHUB_WORKFLOW": "go-test"})
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111, queued")
        self.assertIn("this job of the line's go-test workflow steps aside; the proof's last job (re-ask) asks again",
                      p.stdout)

    def test_dgo_stable_with_line_too_and_no_proof_runs(self):
        p, said, calls, _ = self.guard(no_proof() + [ALONE, CANCEL], ref="refs/heads/dgo-stable", args=["--line-too"],
                                       extra={"GITHUB_WORKFLOW": "go-test"})
        self.assert_runs(p, said, calls)
        self.assertIn("on dgo-stable: no version's proof queued or running", said)
        self.assertEqual(sum("status=" in c["url"] for c in calls), 5, "every waiting status is asked")

    def test_dgo_stable_with_line_too_runs_once_the_proof_has_ended_but_its_re_ask(self):
        # the proof's last job asks this run again while that job is still going: it must not step aside once more
        done = [("decide", "completed"), ("gates", "completed"), ("carrier", "completed"), ("green", "completed")]
        p, said, calls, _ = self.guard(self.in_progress(222) + [
            self.proof_jobs(222, *done, ("re-ask", "in_progress")), ALONE, CANCEL],
            ref="refs/heads/dgo-stable", args=["--line-too"])
        self.assert_runs(p, said, calls)

    def test_a_dgo_stable_hand_run_with_line_too_yields_where_it_says_dispatch_too(self):
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/heads/dgo-stable",
                                            event="workflow_dispatch", args=["--dispatch-too", "--line-too"])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111")
        # …and without --dispatch-too a hand-run on the line says so and runs
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/heads/dgo-stable",
                                       event="workflow_dispatch", args=["--line-too"])
        self.assert_runs(p, said, calls)

    def test_a_run_is_never_ahead_of_itself(self):
        # were the proof's own job ever to say --line-too, its run would be the proof it finds (in progress, not ended:
        # ALONE has no re-ask job) — and without this rule it would cancel itself, the line left with no verdict
        p, said, calls, _ = self.guard(self.in_progress(int(RUN)) + [ALONE, CANCEL], ref="refs/heads/dgo-stable",
                                       args=["--line-too"])
        self.assert_runs(p, said, calls)
        self.assertIn("run %s is this job's own run" % RUN, p.stdout)

    def test_a_tag_runs_asks_nothing_and_says_nothing(self):
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/tags/v0.2.1")
        self.assert_runs(p, said, calls)
        self.assertEqual(calls, [])
        self.assertNotIn("::", p.stdout, "no notice, no warning")

    def test_a_pull_requests_merge_ref_runs_and_asks_nothing(self):
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/pull/7/merge",
                                       event="pull_request")
        self.assert_runs(p, said, calls)
        self.assertEqual(calls, [])

    def test_api_failure_runs_with_a_warning(self):
        p, said, calls, _ = self.guard([])   # every call fails
        self.assert_runs(p, said, calls)
        self.assertIn("::warning::step-aside could not ask GitHub whether a version's proof is queued", p.stdout)

    def test_a_refused_cancel_runs_with_a_warning(self):
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, dict(CANCEL, status=403)])
        self.assertTrue(said.startswith("step-aside=no the cancel was refused"), said)
        self.assertEqual(p.returncode, 0)
        self.assertIn("actions: write", p.stdout)
        self.assertNotIn("::notice", p.stdout, "a step-aside that did not happen is not announced")

    # ── watching while the job works: --watch (DGO-2123) ──────────────────────────────────────────
    def line(self, *turns):
        """The line's ten newest proof runs, one answer a turn: [(id, status)…], or an HTTP status that fails."""
        seq = [{"status": t} if isinstance(t, int) else
               {"status": 200, "body": {"total_count": len(t), "workflow_runs": [{"id": i, "status": s} for i, s in t]}}
               for t in turns]
        return {"match": "workflows/gates-hosted.yml/runs?branch=dgo-stable&per_page=10", "status": 200, "seq": seq}

    def test_watching_steps_aside_once_a_proof_is_pushed(self):
        # batch 89, 2026-11-20: pushed 08:50Z while mac-dgo's gates (from 08:44) held the runner — asked at the start alone
        over = [(100, "completed")]
        p, said, calls, output = self.watch([self.line(over, over, over + [(111, "queued")]), ALONE, CANCEL])
        # STEP_ASIDE_WAIT=0: nothing stopped the step — beside the work an exit decides nothing, so it says so and ends
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("had not stopped this step 0 s later; watching ends", p.stdout)
        self.assertNotIn("::error::", p.stdout)
        self.assertEqual(len(self.cancelled(calls)), 1)
        self.assertIn("::notice title=step-aside::a version's proof is ahead (run 111, queued", p.stdout)
        lines = p.stdout.splitlines()
        notice = next(i for i, ln in enumerate(lines) if ln.startswith("::notice"))
        self.assertEqual(lines[notice - 1], "", "the notice starts on a line of its own: the work shares the pipe")
        self.assertEqual(said[0], "step-aside=no office-branch job on mac-dgo: no version's proof queued or running")
        self.assertEqual(len(said), 2, "three asks, one «no» said once, then the yes: %s" % said)
        self.assertTrue(said[1].startswith("step-aside=yes a version's proof is ahead (run 111, queued"), said)
        asked = [c["url"] for c in calls if "/runs?branch=dgo-stable" in c["url"]]
        self.assertEqual(len(asked), 3, "one question a turn: %s" % asked)
        self.assertFalse(any("status=" in u for u in asked), "watching asks one list, not five statuses")
        self.assertEqual(output, "aside=yes\n", "a «no» while watching is no output of the step")

    def test_watching_says_a_no_only_when_it_changes(self):
        # the outage's two answers differ in their digits only, as curl's timeouts do (their milliseconds): one outage
        p, said, calls, _ = self.watch([self.line([], [], 500, 502, [], [(111, "queued")]), ALONE, CANCEL])
        self.assertEqual(said[:3], [
            "step-aside=no office-branch job on mac-dgo: no version's proof queued or running",
            "step-aside=no GitHub did not answer whether a version's proof is queued or running",
            "step-aside=no office-branch job on mac-dgo: no version's proof queued or running"])
        self.assertEqual(len(said), 4, said)
        self.assertEqual(p.stdout.count("::warning::step-aside could not ask"), 1, "an outage of two asks is one warning")
        self.assertEqual(p.stdout.count("returned error: 50"), 1, "curl's own words come with it, once")
        self.assertEqual(len(self.cancelled(calls)), 1)

    def test_watching_an_unreadable_proof_is_not_ahead_this_turn(self):
        # a proof in progress whose last job waits for the runner is read every turn: one 5xx there must not throw
        # away the work so far (at the start it is ahead: test_a_proof_whose_jobs_cannot_be_read_is_ahead)
        going = self.proof_jobs(222, ("decide", "completed"), ("gates", "queued"))
        turns = dict(going, seq=[{"status": 502}, {"status": 200, "body": going["body"]}])
        p, said, calls, _ = self.watch([self.line([(222, "in_progress")]), turns, ALONE, CANCEL])
        self.assertIn("::warning::step-aside could not read the jobs of run 222", p.stdout)
        self.assertEqual(len(self.cancelled(calls)), 1, "the next turn reads it, ahead, and steps aside")
        self.assertEqual(sum("runs?branch=dgo-stable" in c["url"] for c in calls), 2, "two turns, not one")

    def test_watching_the_steps_end_during_the_cancel_still_announces_it(self):
        # the work ends while the cancel is on its way: the step's trap TERMs the watcher, the cancel goes through — and
        # without its notice re-ask would never ask the run again (the second reader of 5a220ad98)
        p, said, calls, _ = self.watch([self.line([(111, "queued")]), ALONE, dict(CANCEL, term_parent=True)])
        self.assertEqual(len(self.cancelled(calls)), 1)
        self.assertIn("::notice title=step-aside::a version's proof is ahead (run 111", p.stdout)
        self.assertEqual(p.returncode, 0, "the TERM ends it right after the notice: %s" % p.stdout)
        self.assertNotIn("watching ends", p.stdout, "it did not wait for the runner")

    def test_watching_passes_its_own_run_and_a_proof_whose_re_ask_alone_is_left(self):
        done = [("decide", "completed"), ("gates", "completed"), ("re-ask", "in_progress")]
        p, said, calls, _ = self.watch(
            [self.line([(222, "in_progress"), (int(RUN), "in_progress")], [(222, "in_progress"), (333, "queued")]),
             self.proof_jobs(222, *done), ALONE, CANCEL], ref="refs/heads/dgo-stable", args=["--line-too"])
        self.assertIn("run 222 is a version's proof whose last job (re-ask) alone is left", p.stdout)
        self.assertIn("run %s is this job's own run" % RUN, p.stdout)
        self.assertTrue(said[-1].startswith("step-aside=yes a version's proof is ahead (run 333, queued"), said)
        self.assertEqual(len(self.cancelled(calls)), 1)
        # a queued proof is read before one in progress: its jobs are never asked on the second turn
        self.assertEqual(sum("/actions/runs/222/jobs" in c["url"] for c in calls), 1)

    def test_watching_asks_again_after_a_held_back_cancel(self):
        held = jobs(("gates", "in_progress", RUNNER), ("qemu", "in_progress", "GitHub Actions 7"))
        turns = dict(held, seq=[{"status": 200, "body": held["body"]}, {"status": 200, "body": ALONE["body"]}])
        p, said, calls, _ = self.watch([self.line([(111, "queued")]), turns, CANCEL])
        self.assertIn("another job at work (qemu)", p.stdout)
        self.assertEqual(len(self.cancelled(calls)), 1, "the second turn, qemu gone, steps aside")
        self.assertEqual(p.returncode, 0)

    def test_watching_a_hand_run_that_never_yields_watches_nothing(self):
        p, said, calls, _ = self.watch([self.line([(111, "queued")]), ALONE, CANCEL], event="workflow_dispatch")
        self.assertEqual((p.returncode, said, calls),
                         (0, ["step-aside=no a hand-run on mac-dgo: it never steps aside, so nothing is watched"], []))

    def test_watching_on_the_line_without_line_too_asks_nothing(self):
        # gates-hosted's lanes start the watcher on dgo-stable too: there the job IS the proof
        p, said, calls, _ = self.watch([self.line([(111, "queued")]), ALONE, CANCEL], ref="refs/heads/dgo-stable")
        self.assertEqual((p.returncode, calls), (0, []))
        self.assertEqual(len(said), 1)
        self.assertIn("a version's proof never steps aside", said[0])

    def test_watching_a_tag_asks_nothing(self):
        p, said, calls, _ = self.watch([self.line([(111, "queued")]), ALONE, CANCEL], ref="refs/tags/v0.3.3")
        self.assertEqual((p.returncode, calls, len(said)), (0, [], 1))

    # ── never a run with another job at work ───────────────────────────────────────────────────────
    def test_another_job_in_progress_holds_the_cancel_back(self):
        # android-engine: the guest takes the Dell while the qemu job builds on GitHub's runner, no `needs:` between
        beside = jobs(("guest", "in_progress", RUNNER), ("qemu", "in_progress", "GitHub Actions 7"))
        p, said, calls, _ = self.guard([runs("queued", 111), beside, CANCEL], event="workflow_dispatch",
                                       args=["--dispatch-too"], extra={"GITHUB_JOB": "guest"})
        self.assert_runs(p, said, calls)
        self.assertIn("another job at work (qemu)", p.stdout)
        self.assertIn("::warning::", p.stdout)

    def test_unreadable_jobs_hold_the_cancel_back(self):
        p, said, calls, _ = self.guard([runs("queued", 111), jobs(status=500), CANCEL])
        self.assert_runs(p, said, calls)
        self.assertIn("could not read run %s's own jobs" % RUN, p.stdout)

    def test_without_a_runner_name_this_job_is_the_one_github_job_names(self):
        legs = jobs(("test (packaging/trust)", "completed", RUNNER), ("test (packaging/dgo)", "in_progress", RUNNER),
                    ("test (packaging/relsign)", "queued", None))
        p, said, calls, output = self.guard([runs("queued", 111), legs, CANCEL],
                                            extra={"RUNNER_NAME": "", "GITHUB_JOB": "test"})
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111")
        # …and a job it cannot tell is its own counts as another: no cancel
        p, said, calls, _ = self.guard([runs("queued", 111), legs, CANCEL],
                                       extra={"RUNNER_NAME": "", "GITHUB_JOB": "other"})
        self.assert_runs(p, said, calls)

    # ── hand-runs ──────────────────────────────────────────────────────────────────────────────────
    def test_a_hand_run_never_steps_aside_but_says_the_proof_is_ahead(self):
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], event="workflow_dispatch")
        self.assert_runs(p, said, calls)
        self.assertIn("::warning::a version's proof is ahead (run 111", p.stdout)
        self.assertFalse(any("/jobs" in c["url"] for c in calls))

    def test_a_hand_run_yields_where_the_workflow_says_dispatch_too(self):
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL], event="workflow_dispatch",
                                            args=["--dispatch-too"])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111")
        self.assertIn("this hand-run steps aside; dispatch it again once run 111 has ended", p.stdout)

    def test_the_token_is_never_on_curls_command_line(self):
        _, _, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL])
        self.assertTrue(calls)
        for c in calls:
            self.assertNotIn(TOKEN, " ".join(c["argv"]))
            self.assertIn("Authorization: Bearer " + TOKEN, c["headers"])

    # ── the way cleared for a proof, and a superseded run (DGO-2123) ──────────────────────────────────────────
    def clear_world(self):
        """What waits for the runner while this job yields to proof 111 — the afternoon of batch 98, and each kind of run
        the clearing must leave alone."""
        q = listed("queued",
                   waiting(501, "go-test.yml", "hp-dgo"),                              # an office branch's: cleared
                   waiting(503, "go-test.yml", "mac-dgo", event="workflow_dispatch"),  # a hand-run: never
                   waiting(111, "gates-hosted.yml", "dgo-stable"),                     # the proof itself
                   waiting(504, "gates-hosted.yml", "dgo-stable"),                     # another proof: never
                   waiting(505, "go-test.yml", "dgo-stable"),                          # the line's go-test yields: cleared
                   waiting(506, "android-app.yml", "dgo-stable"),                      # the line's phone decides first
                   waiting(507, "go-test.yml", "vps1-dgo"),                            # a job of it at work elsewhere
                   waiting(508, "images.yml", "mac-dgo"),                              # not a workflow of the protocol
                   waiting(509, "go-test.yml", "v0.3.2"),                              # a tag
                   waiting(510, "gates-hosted.yml", "mac-dgo"),                        # nothing of it waits HERE
                   waiting(int(RUN), "gates-hosted.yml", "mac-dgo"))                   # this job's own run
        return [q, listed("pending", waiting(512, "public-copy.yml", "mac-dgo", status="pending")),
                listed("in_progress", waiting(502, "gates-hosted.yml", "mac-dgo", status="in_progress")),
                their_jobs(501, ("test (packaging/dgo)", "queued", PORTABLE), ("test (packaging/trust)", "queued", PORTABLE)),
                their_jobs(502, ("decide", "completed", PORTABLE), ("gates", "queued", PORTABLE),
                           ("carrier", "queued", PORTABLE)),
                their_jobs(505, ("test (packaging/relsign)", "queued", PORTABLE)),
                their_jobs(506, ("phone", "queued", PORTABLE + ("ssd",))),
                their_jobs(507, ("test (packaging/dgo)", "in_progress", ("self-hosted", "elsewhere")),
                           ("test (packaging/trust)", "queued", PORTABLE)),
                their_jobs(510, ("gates", "queued", ("self-hosted", "elsewhere"))),
                their_jobs(512, ("copy", "pending", PORTABLE + ("ssd",))),
                cancel_of(501), cancel_of(502), cancel_of(505), cancel_of(512)]

    def others_cancelled(self, calls):
        return sorted(int(c["url"].rsplit("/", 2)[-2]) for c in calls
                      if c["method"] == "POST" and c["url"].endswith("/cancel") and not self.cancelled([c]))

    def test_a_yield_clears_the_way_for_the_proof(self):
        # batch 95, 2026-11-20: nine jobs took the runner one by one and yielded one by one — 7.2 minutes
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL] + self.clear_world())
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111, queued")
        self.assertEqual(self.others_cancelled(calls), [501, 502, 505, 512])
        # each cancel said as it is sent, then what it comes to
        self.assertIn("step-aside: run 501 (go-test.yml hp-dgo ccccccccc) waited for the runner — cancelled, to clear the "
                      "way for run 111", p.stdout)
        self.assertEqual(sum("waited for the runner — cancelled" in ln for ln in p.stdout.splitlines()), 4)
        self.assertIn("the way is cleared for run 111 — 4 run(s) cancelled; re-ask asks each again", p.stdout)
        posts = [c["url"] for c in calls if c["method"] == "POST"]
        self.assertTrue(posts[-1].endswith("/actions/runs/%s/cancel" % RUN), "its own run goes last: %s" % posts)

    def test_a_way_that_cannot_be_listed_still_yields(self):
        p, said, calls, output = self.guard([runs("queued", 111), ALONE, CANCEL,
                                             {"match": "/actions/runs?status=queued&", "status": 502}])
        self.assert_aside(p, said, calls, output, "a version's proof is ahead (run 111, queued")
        self.assertIn("::warning::step-aside could not list the queued runs (above): the way for run 111 is not cleared",
                      p.stdout)
        self.assertEqual(self.others_cancelled(calls), [])

    def test_a_watcher_that_yields_clears_the_way_too(self):
        over = [(100, "completed")]
        p, said, calls, _ = self.watch([self.line(over, over + [(111, "queued")]), ALONE, CANCEL] + self.clear_world())
        self.assertEqual(self.others_cancelled(calls), [501, 502, 505, 512])
        lines = p.stdout.splitlines()
        notice = next(i for i, ln in enumerate(lines) if ln.startswith("::notice"))
        # said at once, on a line of its own — never kept for a notice the step's end may kill the watcher before
        cleared = next(i for i, ln in enumerate(lines) if "the way is cleared for run 111" in ln)
        self.assertLess(cleared, notice)
        self.assertEqual(lines[cleared - 1], "", "the clearing starts on a line of its own: the work shares the pipe")
        self.assertTrue(lines[cleared].startswith("step-aside: the way is cleared"), lines[cleared])

    def test_a_job_that_runs_clears_nothing(self):
        p, said, calls, _ = self.guard(no_proof() + [ALONE, CANCEL] + self.clear_world())
        self.assert_runs(p, said, calls)
        self.assertEqual(self.others_cancelled(calls), [])
        self.assertFalse(any("/actions/runs?status=" in c["url"] for c in calls), "nothing is listed without a yield")

    def clear(self, routes, ref="refs/heads/dgo-stable", event="push", extra=None, own=ALONE):
        """step-aside --clear from a job of a proof whose own jobs are `own` (by default: none red)."""
        env = {"GITHUB_WORKFLOW_REF": "o/r/.github/workflows/gates-hosted.yml@" + ref}
        p, said, calls, _ = self.ask([own] + list(routes), ref, event, ["--clear"], dict(env, **(extra or {})))
        self.assertEqual(p.returncode, 0, "a clearing never fails the proof:\n" + p.stdout + p.stderr)
        self.assertEqual(said, [], "a clearing decides nothing about its own job")
        return p, calls

    def test_a_proof_clears_the_way_for_its_next_job(self):
        # batch 100, 2026-11-20: five branch jobs took the runner between its decide and its gates, each to yield
        p, calls = self.clear(self.clear_world())
        self.assertEqual(self.others_cancelled(calls), [501, 502, 505, 512])
        self.assertEqual(self.cancelled(calls), [], "never its own run")
        self.assertIn("the way is cleared for run %s — 4 run(s)" % RUN, p.stdout)

    def test_a_proof_with_nothing_waiting_says_so(self):
        p, calls = self.clear([])
        self.assertIn("nothing waits for the runner ahead of this proof's next job", p.stdout)

    def test_a_red_proof_clears_nothing(self):
        # its next job is its re-ask alone, which the waiting runs may go ahead of (step-aside's «last job alone») —
        # cleared, they would hang on that re-ask (the second reader of 59774eeb7)
        red = {"match": "/actions/runs/%s/jobs?" % RUN, "status": 200, "body": {"jobs": [
            {"name": "decide", "status": "completed", "conclusion": "success"},
            {"name": "carrier", "status": "completed", "conclusion": "failure"},
            {"name": "gates", "status": "in_progress", "conclusion": None}]}}
        p, calls = self.clear(self.clear_world(), own=red)
        self.assertIn("this proof is red already (carrier) — its re-ask alone is left; nothing is cleared", p.stdout)
        self.assertEqual(self.others_cancelled(calls), [])
        # …and own jobs that cannot be read: said, and the way cleared all the same (the common case is a green one)
        p, calls = self.clear(self.clear_world(), own={"match": "/actions/runs/%s/jobs?" % RUN, "status": 500})
        self.assertIn("::warning::step-aside could not read this proof's own jobs", p.stdout)
        self.assertEqual(self.others_cancelled(calls), [501, 502, 505, 512])

    def test_a_clearing_github_does_not_answer_still_ends_well(self):
        p, calls = self.clear([{"match": "/actions/runs?status=", "status": 500}])
        self.assertIn("::warning::step-aside could not list the queued runs", p.stdout)
        self.assertNotIn("nothing waits", p.stdout, "an unanswered question is not «nothing waits»")
        p, calls = self.clear(self.clear_world(), extra={"GH_TOKEN": ""})
        self.assertEqual(calls, [])
        self.assertIn("::warning::step-aside has no repository or token to clear the way with", p.stdout)

    def test_clear_is_a_proofs_own(self):
        for ref, event, wf in (("refs/heads/mac-dgo", "push", "gates-hosted.yml"),
                               ("refs/heads/dgo-stable", "workflow_dispatch", "gates-hosted.yml"),
                               ("refs/heads/dgo-stable", "push", "go-test.yml")):
            p, calls = self.clear(self.clear_world(), ref=ref, event=event,
                                  extra={"GITHUB_WORKFLOW_REF": "o/r/.github/workflows/%s@%s" % (wf, ref)})
            self.assertEqual(calls, [], (ref, event, wf))
            self.assertIn("--clear is a version's proof's own step", p.stdout)

    OWN_LEG = jobs(("test (packaging/relsign)", "in_progress", RUNNER), ("test (packaging/dgo)", "queued", None))

    def newer_world(self, status="queued", conclusion=None, compare="ahead", job_rows=None, wf="go-test.yml",
                    branch="vps1-dgo"):
        """A newer run (5000, head c…) of this job's workflow on its branch — and older ones, which never count."""
        legs = [{"name": "test (packaging/dgo)", "status": "queued", "conclusion": None},
                {"name": "test (packaging/trust)", "status": "queued", "conclusion": None}]
        return [{"match": "workflows/%s/runs?branch=%s&event=push&per_page=20" % (wf, branch), "status": 200,
                 "body": {"workflow_runs": [
                     {"id": 5000, "head_sha": "c" * 40, "status": status, "conclusion": conclusion},
                     {"id": int(RUN), "head_sha": "a" * 40, "status": "in_progress", "conclusion": None},
                     {"id": 4000, "head_sha": "9" * 40, "status": "queued", "conclusion": None}]}},
                {"match": "/actions/runs/5000/jobs?", "status": 200,
                 "body": {"jobs": legs if job_rows is None else job_rows}},
                {"match": "/compare/%s...%s" % ("a" * 40, "c" * 40), "status": 200, "body": {"status": compare}}]

    @staticmethod
    def expiry_env(wf="go-test.yml", branch="vps1-dgo", job="test"):
        return {"GITHUB_WORKFLOW_REF": "o/r/.github/workflows/%s@refs/heads/%s" % (wf, branch), "GITHUB_JOB": job}

    def asked_expiry(self, calls):
        return any("&event=push&per_page=20" in c["url"] for c in calls)

    def test_a_superseded_run_expires(self):
        # 2026-11-20: vps1-dgo's go-test of 32ab6901e, re-asked again and again from 12:35, while 39ff82d88's waited
        p, said, calls, output = self.guard(self.newer_world() + [self.OWN_LEG, CANCEL], ref="refs/heads/vps1-dgo",
                                            extra=self.expiry_env())
        self.assertTrue(said.startswith("step-aside=yes run 5000 "), said)
        self.assertIn("::notice title=superseded::run 5000 ", p.stdout)
        self.assertIn("this run is superseded — this office-branch job expires; it owes nothing", p.stdout)
        self.assertEqual(len(self.cancelled(calls)), 1)
        self.assertIn("aside=yes", output)
        self.assertFalse(any("gates-hosted.yml/runs?branch=dgo-stable" in c["url"] for c in calls), "no proof asked")
        self.assertFalse(any("/actions/runs?status=" in c["url"] for c in calls), "an expiry clears no way")

    def test_a_newer_run_still_waiting_for_its_group_supersedes(self):
        # the main case: the old run holds go-test's group and the newer one waits in it — «pending», and GitHub lists
        # no job of it until it starts (measured: mac-dgo's go-test of 59774eeb7, 2026-11-20)
        p, said, calls, _ = self.guard(self.newer_world("pending", job_rows=[]) + [self.OWN_LEG, CANCEL],
                                       ref="refs/heads/vps1-dgo", extra=self.expiry_env())
        self.assertIn("::notice title=superseded::run 5000 ", p.stdout)
        # …but not gates-hosted's: before its decide has answered, nothing says that run tests at all
        p, said, calls, _ = self.guard(self.newer_world("pending", job_rows=[], wf="gates-hosted.yml", branch="mac-dgo")
                                       + no_proof() + [ALONE, CANCEL],
                                       extra=self.expiry_env("gates-hosted.yml", "mac-dgo", "gates"))
        self.assert_runs(p, said, calls)
        # …nor a run that lists no job and is not waiting in its group, nor public-copy's (its one job asks the push's
        # message: a run with none listed yet may skip it — the reader of ac436e0b8)
        for status, wf, job in (("in_progress", "go-test.yml", "test"), ("queued", "go-test.yml", "test"),
                                ("pending", "public-copy.yml", "copy")):
            p, said, calls, _ = self.guard(self.newer_world(status, job_rows=[], wf=wf) + no_proof()
                                           + [self.OWN_LEG, CANCEL], ref="refs/heads/vps1-dgo",
                                           extra=self.expiry_env(wf, job=job))
            self.assert_runs(p, said, calls)
            self.assertNotIn("superseded", p.stdout, (status, wf))

    def test_a_newer_run_with_a_verdict_supersedes_too(self):
        done = [{"name": "test (packaging/dgo)", "status": "completed", "conclusion": "failure"}]
        p, _, _, _ = self.guard(self.newer_world("completed", "failure", job_rows=done) + [self.OWN_LEG, CANCEL],
                                ref="refs/heads/vps1-dgo", extra=self.expiry_env())
        self.assertIn("::notice title=superseded::run 5000 ", p.stdout)

    def test_a_run_expires_only_for_a_newer_run_that_tests_it(self):
        cases = {
            "a newer run cancelled": dict(status="completed", conclusion="cancelled"),
            "a newer run that tested nothing": dict(status="completed", conclusion="skipped"),
            "a newer head that does not hold this one": dict(compare="diverged"),
            "its job skipped there": dict(job_rows=[{"name": "test (packaging/dgo)", "status": "completed",
                                                      "conclusion": "skipped"}]),
            "its job not there": dict(job_rows=[{"name": "other", "status": "queued", "conclusion": None}]),
            "its jobs unreadable": dict(job_rows=None),
        }
        for why, kw in cases.items():
            routes = self.newer_world(**kw)
            if why == "its jobs unreadable":
                routes[1] = {"match": "/actions/runs/5000/jobs?", "status": 500}
            p, said, calls, _ = self.guard(routes + no_proof() + [self.OWN_LEG, CANCEL], ref="refs/heads/vps1-dgo",
                                           extra=self.expiry_env())
            self.assert_runs(p, said, calls)
            self.assertNotIn("superseded", p.stdout, why)
            self.assertTrue(self.asked_expiry(calls), why)

    def test_a_gates_job_expires_only_once_the_newer_decide_asked_for_it(self):
        def rows(decided):
            return [{"name": "decide", "status": "completed" if decided else "queued",
                     "conclusion": "success" if decided else None},
                    {"name": "gates", "status": "queued", "conclusion": None}]
        env = self.expiry_env("gates-hosted.yml", "mac-dgo", "gates")
        p, said, calls, _ = self.guard(self.newer_world(job_rows=rows(False), wf="gates-hosted.yml", branch="mac-dgo")
                                       + no_proof() + [ALONE, CANCEL], extra=env)
        self.assert_runs(p, said, calls)
        p, said, calls, _ = self.guard(self.newer_world(job_rows=rows(True), wf="gates-hosted.yml", branch="mac-dgo")
                                       + [ALONE, CANCEL], extra=env)
        self.assertIn("::notice title=superseded::run 5000 ", p.stdout)
        # decide itself never expires: a newer decide's success says nothing of whether that run tests (it answers no
        # to a push that did not ask)
        p, said, calls, _ = self.guard(self.newer_world(job_rows=rows(True), wf="gates-hosted.yml", branch="mac-dgo")
                                       + no_proof() + [ALONE, CANCEL],
                                       extra=self.expiry_env("gates-hosted.yml", "mac-dgo", "decide"))
        self.assert_runs(p, said, calls)
        self.assertFalse(self.asked_expiry(calls))

    def test_a_slow_job_never_expires_for_a_run_whose_fast_lane_failed(self):
        # that run's slow job reads «queued», and waits for a fast lane that will never let it run
        newer = [{"name": "decide", "status": "completed", "conclusion": "success"},
                 {"name": "gates", "status": "completed", "conclusion": "failure"},
                 {"name": "slow", "status": "queued", "conclusion": None}]
        env = self.expiry_env("gates-hosted.yml", "mac-dgo", "slow")
        own = jobs(("decide", "completed", RUNNER), ("gates", "completed", RUNNER), ("slow", "in_progress", RUNNER))
        p, said, calls, _ = self.guard(self.newer_world(job_rows=newer, wf="gates-hosted.yml", branch="mac-dgo")
                                       + no_proof() + [own, CANCEL], extra=env)
        self.assert_runs(p, said, calls)
        self.assertNotIn("superseded", p.stdout)
        newer[1]["conclusion"] = "success"
        p, said, calls, _ = self.guard(self.newer_world(job_rows=newer, wf="gates-hosted.yml", branch="mac-dgo")
                                       + [own, CANCEL], extra=env)
        self.assertIn("::notice title=superseded::run 5000 ", p.stdout)

    def test_never_superseded_a_hand_run_an_apk_or_a_watcher(self):
        p, said, calls, _ = self.guard(self.newer_world() + no_proof() + [self.OWN_LEG, CANCEL],
                                       ref="refs/heads/vps1-dgo", event="workflow_dispatch", extra=self.expiry_env())
        self.assert_runs(p, said, calls)
        self.assertFalse(self.asked_expiry(calls), "a hand-run is an explicit ask")
        p, said, calls, _ = self.guard(self.newer_world(wf="android-app.yml") + no_proof() + [self.OWN_LEG, CANCEL],
                                       ref="refs/heads/vps1-dgo", extra=self.expiry_env("android-app.yml", job="apk"))
        self.assert_runs(p, said, calls)
        self.assertFalse(self.asked_expiry(calls), "an APK is not covered by a newer run that built nothing")
        over = [(100, "completed")]
        p, said, calls, _ = self.watch(self.newer_world() + [self.line(over, over + [(111, "queued")]), self.OWN_LEG,
                                                             CANCEL], ref="refs/heads/vps1-dgo", extra=self.expiry_env())
        self.assertFalse(self.asked_expiry(calls), "a run at work finishes: watching never asks it")
        self.assertIn("::notice title=step-aside::", p.stdout)

    def test_the_guards_lists_are_re_asks(self):
        # the workflows the way is cleared of are the ones re-ask asks again; the line's jobs that yield are LINE_JOBS
        text = GUARD.read_text(encoding="utf-8")

        def const(name):
            return re.search(r'^%s="([^"]*)"' % name, text, re.M).group(1).split()
        spec_ = importlib.util.spec_from_file_location("re_ask", REPO / "scripts" / "ci" / "re-ask.py")
        re_ask = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(re_ask)
        self.assertEqual(set(const("YIELDING")), set(re_ask.WORKFLOWS))
        self.assertEqual({tuple(x.split(":")) for x in const("LINE_YIELDS")}, LINE_JOBS)
        self.assertTrue(set(const("EXPIRES")) <= set(const("YIELDING")))
        self.assertEqual([w for w in const("EXPIRES") if w.startswith("android-")], [], "an APK never expires")

    # ── the workflows call it ──────────────────────────────────────────────────────────────────────
    def workflows(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not here")
        return {n: yaml.safe_load((REPO / ".github" / "workflows" / n).read_text(encoding="utf-8")) for n in WORKFLOWS}

    def test_every_office_branch_job_on_the_runner_asks_first(self):
        for name, doc in self.workflows().items():
            self.assertEqual(findings(name, doc), [])

    def test_an_inverted_if_is_refused(self):
        # each guarded job's own `if:` turned the wrong way (onto dgo-stable alone; off every branch), and swapped for
        # the other shape — a line job back to keeping dgo-stable out is DGO-2111 undone; an office-branch job's onto
        # dgo-stable puts it ahead of the proof again
        for name, doc in self.workflows().items():
            for job_name, job in doc["jobs"].items():
                if guard_index(job) is None:
                    continue
                want = guard_if(name, job_name)
                wrongs = ("github.ref == 'refs/heads/dgo-stable'", "!startsWith(github.ref, 'refs/heads/')",
                          LINE_IF if want == GUARD_IF else GUARD_IF)
                for where in ("checkout", "guard"):
                    for wrong in wrongs:
                        bad = copy.deepcopy(doc)
                        flipped = 0
                        for step in bad["jobs"][job_name].get("steps") or []:
                            is_guard = "scripts/ci/step-aside" in str(step.get("run") or "")
                            if step.get("if") == want and (is_guard == (where == "guard")):
                                step["if"] = wrong
                                flipped += 1
                        if not flipped:   # decide's checkout has no `if:` (it holds gates-asked too)
                            self.assertEqual((name, job_name, where), (PROOF, "decide", "checkout"))
                            continue
                        self.assertNotEqual(findings(name, bad), [],
                                            "%s/%s: the %s `if:` %r passed" % (name, job_name, where, wrong))

    def test_line_too_is_line_jobs_alone(self):
        # on the proof it would read the proof ahead as one to yield to; off a line job, that job's dgo-stable run goes
        # ahead of the proof again (batch 87's)
        turned = set()
        for name, doc in self.workflows().items():
            for job_name, job in doc["jobs"].items():
                i = guard_index(job)
                if i is None or i < 0:
                    continue
                bad = copy.deepcopy(doc)
                step = bad["jobs"][job_name]["steps"][i]
                if "--line-too" in step["run"]:
                    step["run"] = step["run"].replace(" --line-too", "")
                else:
                    step["run"] = step["run"].replace("scripts/ci/step-aside", "scripts/ci/step-aside --line-too", 1)
                turned.add((name, job_name))
                self.assertTrue(any("--line-too" in f and job_name in f for f in findings(name, bad)),
                                "%s/%s: --line-too turned and passed: %s" % (name, job_name, findings(name, bad)))
        self.assertTrue(LINE_JOBS <= turned, "every line job was turned: %s" % (LINE_JOBS - turned))

    def test_a_line_job_that_is_gone_is_refused(self):
        # a LINE_JOBS row that stopped matching would let its job keep dgo-stable out unseen
        for name, job_name in LINE_JOBS:
            bad = copy.deepcopy(self.workflows()[name])
            bad["jobs"]["renamed-" + job_name] = bad["jobs"].pop(job_name)
            self.assertTrue(any("LINE_JOBS" in f for f in findings(name, bad)), name)

    def test_a_dgo_stable_only_job_of_the_line_is_not_exempt(self):
        # only the proof's own jobs (green, re-ask) run on dgo-stable unguarded: a dgo-stable-only job of go-test or the
        # Android builds on the runner is exactly a job that would go ahead of the proof (the second reader) — in either
        # spelling of the branch
        for name in WORKFLOWS:
            if name == PROOF:
                continue
            for cond in ("github.ref == 'refs/heads/dgo-stable'", "github.ref_name == 'dgo-stable'"):
                bad = copy.deepcopy(self.workflows()[name])
                bad["jobs"]["only-the-line"] = {"runs-on": ["self-hosted", "portable"], "if": cond,
                                                "steps": [{"run": "true"}]}
                self.assertTrue(any("neither LINE_JOBS" in f for f in findings(name, bad)), name + ": " + cond)
            # …and an exempt job made dgo-stable-only: its guard keeps dgo-stable out, so it would never ask
            for (wf, job_name) in LINE_EXEMPT:
                if wf != name:
                    continue
                bad = copy.deepcopy(self.workflows()[name])
                bad["jobs"][job_name]["if"] = "github.ref_name == 'dgo-stable'"
                self.assertTrue(any("runs on dgo-stable alone" in f for f in findings(name, bad)), job_name)

    def test_a_new_runner_job_of_the_line_must_say_which_it_is(self):
        # a job shaped like android-app's phone (office branches only), added to go-test: on dgo-stable it would go
        # ahead of the proof, and no list said it may
        doc = self.workflows()["go-test.yml"]
        bad = copy.deepcopy(doc)
        twin = copy.deepcopy(self.workflows()["android-app.yml"]["jobs"]["phone"])
        bad["jobs"]["another"] = twin
        got = findings("go-test.yml", bad)
        self.assertTrue(any("job another" in f and "neither LINE_JOBS" in f for f in got), got)

    def test_a_flag_in_a_comment_is_not_a_flag(self):
        doc = self.workflows()["go-test.yml"]
        bad = copy.deepcopy(doc)
        step = bad["jobs"]["test"]["steps"][guard_index(bad["jobs"]["test"])]
        step["run"] = "bash .step-aside/scripts/ci/step-aside && rm -rf .step-aside  # --line-too"
        self.assertTrue(any("--line-too" in f for f in findings("go-test.yml", bad)))
        self.assertEqual(guard_flags("bash x/scripts/ci/step-aside --dispatch-too --line-too && rm -rf x"),
                         {"--dispatch-too", "--line-too"})

    def test_a_watcher_out_of_shape_is_refused(self):
        # each way a watcher fails silently: gone, after the work, in the foreground (the work waits for it forever),
        # its token in the work's environment, never stopped, the wrong flags
        broke = {
            "gone": lambda r: "\n".join(ln for ln in r.splitlines() if "scripts/ci/step-aside" not in ln),
            "after the work": lambda r: "\n".join(sorted(r.splitlines(), key=lambda ln: "scripts/ci/step-aside" in ln)),
            "in the foreground": lambda r: r.replace(" & watcher=$!", "; watcher=0"),
            "no unset": lambda r: r.replace("unset STEP_ASIDE_TOKEN", "true"),
            "no trap": lambda r: "\n".join(ln for ln in r.splitlines() if not ln.strip().startswith("trap ")),
            "--line-too turned": lambda r: (r.replace(" --line-too", "") if "--line-too" in r
                                            else r.replace("--watch", "--watch --line-too")),
            "--dispatch-too": lambda r: r.replace("--watch", "--watch --dispatch-too"),
            # the second reader of 5a220ad98: each of these passed the first checker
            "a trap that kills another": lambda r: r.replace('kill "${watcher}"', "kill 0"),
            "a later EXIT trap": lambda r: "\n".join(ln + ("\ntrap - EXIT" if ln.strip().startswith("trap ") else "")
                                                     for ln in r.splitlines()),
        }
        docs = self.workflows()
        for (name, job_name), work in WATCHERS.items():
            for what in work:
                for how, f in broke.items():
                    bad = copy.deepcopy(docs[name])
                    step = next(s for s in bad["jobs"][job_name]["steps"] if what in str(s.get("run") or ""))
                    step["run"] = f(step["run"])
                    self.assertNotEqual(findings(name, bad), [], "%s/%s %r: %s passed" % (name, job_name, what, how))
                bad = copy.deepcopy(docs[name])
                step = next(s for s in bad["jobs"][job_name]["steps"] if what in str(s.get("run") or ""))
                step["env"]["GH_TOKEN"] = "${{ github.token }}"
                self.assertTrue(any("reaches the environment" in f for f in findings(name, bad)), (name, what))
            # …and the token anywhere else the work can read it: the job's env, the workflow's, a checkout's git config
            for where in ("job", "workflow"):
                bad = copy.deepcopy(docs[name])
                (bad["jobs"][job_name] if where == "job" else bad).setdefault("env", {})["GH_TOKEN"] = "${{ github.token }}"
                self.assertTrue(any("reaches every step's work" in f for f in findings(name, bad)), (name, where))
            for i, s in enumerate(docs[name]["jobs"][job_name]["steps"]):
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    bad = copy.deepcopy(docs[name])
                    bad["jobs"][job_name]["steps"][i].setdefault("with", {}).pop("persist-credentials", None)
                    self.assertTrue(any("persist-credentials" in f for f in findings(name, bad)), (name, i))

    def test_a_watcher_elsewhere_is_refused(self):
        # android-app's apk: a hand-run that yielded mid-build would wait for a person to dispatch it again
        bad = copy.deepcopy(self.workflows()["android-app.yml"])
        step = next(s for s in reversed(bad["jobs"]["apk"]["steps"]) if "run" in s)
        step["run"] = 'GH_TOKEN="${STEP_ASIDE_TOKEN}" bash scripts/ci/step-aside --watch & watcher=$!\n' + step["run"]
        self.assertTrue(any("outside WATCHERS" in f for f in findings("android-app.yml", bad)))
        # …and a WATCHERS row whose job is gone
        bad = copy.deepcopy(self.workflows()["gates-hosted.yml"])
        bad["jobs"]["renamed-gates"] = bad["jobs"].pop("gates")
        self.assertTrue(any("WATCHERS names job gates" in f for f in findings("gates-hosted.yml", bad)))

    def test_a_clear_out_of_shape_is_refused(self):
        doc = self.workflows()["gates-hosted.yml"]
        self.assertEqual(findings("gates-hosted.yml", doc), [])

        def clear_step(d, job):
            return next(s for s in d["jobs"][job]["steps"] if "--clear" in guard_flags(s.get("run")))
        # on an office branch's job: a branch never clears the way for itself
        bad = copy.deepcopy(doc)
        bad["jobs"]["slow"]["steps"].append(copy.deepcopy(clear_step(doc, "gates")))
        self.assertTrue(any("outside CLEARS" in f for f in findings("gates-hosted.yml", bad)))
        # an `if:` that lets it run on a branch, or on a hand-run
        for cond in ("!cancelled()", "github.ref == 'refs/heads/dgo-stable'"):
            bad = copy.deepcopy(doc)
            clear_step(bad, "gates")["if"] = cond
            self.assertTrue(any("does not keep it to a push of dgo-stable" in f
                                for f in findings("gates-hosted.yml", bad)), cond)
        # one that can fail the proof, or that is not the job's last
        bad = copy.deepcopy(doc)
        del clear_step(bad, "carrier")["continue-on-error"]
        self.assertTrue(any("could fail the proof" in f for f in findings("gates-hosted.yml", bad)))
        bad = copy.deepcopy(doc)
        bad["jobs"]["decide"]["steps"].append({"name": "after", "run": "true"})
        self.assertTrue(any("is not the job's last" in f for f in findings("gates-hosted.yml", bad)))
        # …and a CLEARS row whose job lost its step
        bad = copy.deepcopy(doc)
        bad["jobs"]["carrier"]["steps"].remove(clear_step(bad, "carrier"))
        self.assertTrue(any("0 of its steps say --clear" in f for f in findings("gates-hosted.yml", bad)))

    def test_re_asks_line_is_these_jobs(self):
        # re-ask's LINE and LINE_JOBS name the same workflows, and a BUILD's job is a line job of its workflow: rename
        # `apk` in one and not the other, and re-ask would rebuild older runs after a newer one built (the second reader)
        spec_ = importlib.util.spec_from_file_location("re_ask", REPO / "scripts" / "ci" / "re-ask.py")
        re_ask = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(re_ask)
        self.assertEqual(set(re_ask.LINE), {wf for wf, _ in LINE_JOBS})
        for wf, build in re_ask.LINE.items():
            if build is not None:
                self.assertIn((wf, build), LINE_JOBS)
        docs = self.workflows()
        for wf, job_name in set(LINE_JOBS) | set(LINE_EXEMPT):
            self.assertIn(job_name, docs[wf]["jobs"], "%s has no job %s" % (wf, job_name))

    def test_actions_write_is_the_guarded_jobs_alone(self):
        for name, doc in self.workflows().items():
            bad = copy.deepcopy(doc)
            bad.setdefault("permissions", {})["actions"] = "write"
            self.assertNotEqual(findings(name, bad), [], name + ": a workflow-level actions: write passed")
            bad = copy.deepcopy(doc)
            for job in bad["jobs"].values():
                if guard_index(job) is not None:
                    job["permissions"].pop("actions")
                    break
            self.assertNotEqual(findings(name, bad), [], name + ": a guarded job without actions: write passed")

    def test_the_proofs_re_ask_job_is_the_one_exception_and_a_narrow_one(self):
        doc = self.workflows()["gates-hosted.yml"]
        self.assertIn("re-ask", doc["jobs"])
        self.assertEqual(findings("gates-hosted.yml", doc), [])
        # …one more step run beside re-ask.py: no longer the exception
        bad = copy.deepcopy(doc)
        bad["jobs"]["re-ask"]["steps"].append({"run": "echo anything"})
        self.assertIn("gates-hosted.yml: job re-ask holds `actions: write` and calls no guard", findings("gates-hosted.yml", bad))
        # …the same job on an office branch too: no longer stable-only, so it must call the guard
        bad = copy.deepcopy(doc)
        bad["jobs"]["re-ask"]["if"] = "always()"
        self.assertNotEqual(findings("gates-hosted.yml", bad), [])
        # …another script under the same permissions: refused
        bad = copy.deepcopy(doc)
        for s in bad["jobs"]["re-ask"]["steps"]:
            if "run" in s:
                s["run"] = "python3 .re-ask/scripts/ci/other.py"
        self.assertIn("gates-hosted.yml: job re-ask holds `actions: write` and calls no guard", findings("gates-hosted.yml", bad))


def guard_index(job):
    """The job's guard: the one step that calls step-aside — its watchers (--watch, beside a step's work) and a proof's
    clearing of the way (--clear, its last step) aside."""
    hits = [i for i, s in enumerate(job.get("steps") or []) if "scripts/ci/step-aside" in str(s.get("run") or "")
            and not {"--watch", "--clear"} & guard_flags(s.get("run"))]
    return hits[0] if len(hits) == 1 else (None if not hits else -1)


def clear_findings(where, name, job_name, job):
    """What is wrong with a job's `--clear` step: [] when nothing is. Only CLEARS' jobs say it — a version's proof
    clearing the way for its own next job — as the job's last step, on a push of dgo-stable alone, never failing it."""
    out = []
    steps = job.get("steps") or []
    at = [i for i, s in enumerate(steps) if "--clear" in guard_flags(s.get("run"))]
    if (name, job_name) not in CLEARS:
        if at:
            out.append(where + ": a --clear step outside CLEARS — only a version's proof clears the way for itself")
        return out
    if len(at) != 1:
        return ["%s: CLEARS names it, and %d of its steps say --clear" % (where, len(at))]
    step = steps[at[0]]
    cond = str(step.get("if") or "")
    if "github.ref == 'refs/heads/dgo-stable'" not in cond or "github.event_name == 'push'" not in cond:
        out.append(where + ": the --clear step's `if:` does not keep it to a push of dgo-stable")
    if step.get("continue-on-error") is not True:
        out.append(where + ": the --clear step could fail the proof (continue-on-error: true)")
    if at[0] != len(steps) - 1:
        out.append(where + ": the --clear step is not the job's last — what comes after would run behind the next job")
    if (step.get("env") or {}).get("GH_TOKEN") != "${{ github.token }}":
        out.append(where + ": the --clear step has no GH_TOKEN of its own")
    if guard_flags(step.get("run")) != {"--clear"}:
        out.append(where + ": the --clear step says more than --clear")
    return out


def watch_findings(where, name, job_name, job, top_env=None):
    """What is wrong with a job's watchers (step-aside --watch): [] when nothing is."""
    out = []
    steps = job.get("steps") or []
    work = WATCHERS.get((name, job_name))
    if work is None:
        if any("--watch" in guard_flags(s.get("run")) for s in steps):
            out.append(where + ": a step-aside watcher outside WATCHERS — a mid-step yield only where that list says")
        return out
    want = {"--watch"} | ({"--line-too"} if (name, job_name) in LINE_JOBS else set())
    # the token is the watcher's alone: not in the job's or the workflow's env, nor in a checkout's git config
    leaked = {"GH_TOKEN", "GITHUB_TOKEN"} & (set(job.get("env") or {}) | set(top_env or {}))
    if leaked:
        out.append("%s: %s in the job's or the workflow's env — the token reaches every step's work" % (
            where, "/".join(sorted(leaked))))
    for s in steps:
        if (str(s.get("uses", "")).startswith("actions/checkout@")
                and (s.get("with") or {}).get("persist-credentials") is not False):
            out.append(where + ": a checkout keeps the job's token in the work's git config (persist-credentials: false)")
    for what in work:
        hits = [s for s in steps if what in str(s.get("run") or "")]
        if len(hits) != 1:
            out.append("%s: WATCHERS names the work %r, which %d steps run" % (where, what, len(hits)))
            continue
        step = hits[0]
        lines = str(step["run"]).splitlines()
        at = [i for i, ln in enumerate(lines) if "scripts/ci/step-aside" in ln]
        w = min(i for i, ln in enumerate(lines) if what in ln)
        if len(at) != 1 or at[0] > w:
            out.append("%s: the step running %r starts no watcher before it" % (where, what))
            continue
        a, line = at[0], lines[at[0]]
        if guard_flags(line) != want:
            out.append("%s: the watcher of %r says %s, not %s" % (where, what, sorted(guard_flags(line)), sorted(want)))
        if not re.search(r"(?<!&)&(?!&)\s*(\w+=\$!\s*)?$", line):
            out.append("%s: the watcher of %r is not in the background — the work would wait for it" % (where, what))
        env = step.get("env") or {}
        if env.get("STEP_ASIDE_TOKEN") != "${{ github.token }}" or 'GH_TOKEN="${STEP_ASIDE_TOKEN}"' not in line:
            out.append("%s: the watcher of %r has no token of its own (STEP_ASIDE_TOKEN → its GH_TOKEN)" % (where, what))
        if {"GH_TOKEN", "GITHUB_TOKEN"} & set(env) or not any(
                ln.strip() == "unset STEP_ASIDE_TOKEN" for ln in lines[a + 1:w]):
            out.append("%s: the token reaches the environment of %r — only the watcher holds it" % (where, what))
        # stopped when its step ends: an EXIT trap between it and the work that kills ITS pid, and no EXIT trap after
        pid = re.search(r"&\s*(\w+)=\$!", line)
        exits = [i for i, ln in enumerate(lines) if re.match(r"\s*trap\s", ln) and re.search(r"\bEXIT\b|\s0\s*$", ln)]
        kills = [i for i in exits if a < i < w and pid
                 and re.search(r"\bkill\b[^#]*\$\{?%s\}?" % re.escape(pid.group(1)), lines[i])]
        if not kills or any(i > kills[0] for i in exits):
            out.append("%s: nothing stops the watcher of %r when its step ends" % (where, what))
    return out


def guard_flags(run):
    """The guard's own arguments: what follows `scripts/ci/step-aside` on its line, up to the next shell operator or
    comment — a flag in a comment after it, or in another command, is not one (the second reader of DGO-2123). A
    quoted path's closing quote is not a flag, and a single `&` (a watcher sent to the background) ends it too."""
    for line in str(run or "").splitlines():
        if "scripts/ci/step-aside" in line:
            rest = line.split("scripts/ci/step-aside", 1)[1].lstrip("\"'")
            return set(re.split(r"[&|;#]", rest, maxsplit=1)[0].split())
    return set()


def guard_if(name, job_name):
    """The `if:` of a job's guard and of the guard's checkout: a line job asks on dgo-stable too, with --line-too
    (DGO-2111); every other keeps dgo-stable out — the proof's (there they ARE the proof), and the ones whose run on
    the line must not yield (android-app's phone, android-engine's guest: LINE_JOBS' comment)."""
    return LINE_IF if (name, job_name) in LINE_JOBS else GUARD_IF


def asks_again(job):
    """The one other job that may hold `actions: write`: the proof's last job, which asks again the runs that stepped
    aside (scripts/ci/re-ask.py, DGO-1848) — its only steps a checkout and that script, nothing else run with it."""
    steps = job.get("steps") or []
    runs = [s.get("run") or "" for s in steps if "run" in s]
    uses = [s.get("uses") or "" for s in steps if "uses" in s]
    return (len(runs) == 1 and runs[0].strip().startswith("python3 ") and runs[0].strip().endswith("scripts/ci/re-ask.py")
            and all(u.startswith("actions/checkout@") for u in uses))


def clears_the_way(name, job_name, job):
    """The other dgo-stable-only job of the proof that may hold `actions: write`, for one thing alone: its last step,
    clearing the way for the proof's next job (CLEARS, step-aside --clear) — `go`, forward-auth's tests before green.
    clear_findings holds that step's shape."""
    steps = job.get("steps") or []
    return (name, job_name) in CLEARS and bool(steps) and guard_flags(steps[-1].get("run")) == {"--clear"}


def findings(name, doc):
    """What is wrong with one workflow's use of the guard: [] when nothing is."""
    out = []
    top = doc.get("permissions") or {}
    if top.get("actions") == "write":
        out.append("%s: `actions: write` at the workflow level — only the jobs that call the guard hold it" % name)
    jobs_ = 0
    for n, job_name in sorted(LINE_JOBS):
        if n == name and job_name not in doc["jobs"]:
            out.append("%s: LINE_JOBS names job %s, which is not there" % (name, job_name))
    for n, job_name in sorted(WATCHERS):
        if n == name and job_name not in doc["jobs"]:
            out.append("%s: WATCHERS names job %s, which is not there" % (name, job_name))
    for n, job_name in sorted(CLEARS):
        if n == name and job_name not in doc["jobs"]:
            out.append("%s: CLEARS names job %s, which is not there" % (name, job_name))
    for job_name, job in doc["jobs"].items():
        where = "%s: job %s" % (name, job_name)
        out.extend(watch_findings(where, name, job_name, job, doc.get("env")))
        out.extend(clear_findings(where, name, job_name, job))
        runs_on = job.get("runs-on")
        on_runner = isinstance(runs_on, list) and "self-hosted" in runs_on
        # the proof's own dgo-stable-only jobs (green, re-ask) are not office-branch jobs: they need no guard. In the
        # line's other workflows a dgo-stable-only job on the runner is the one that would go ahead of the proof.
        stable_only = name == PROOF and "github.ref == 'refs/heads/dgo-stable'" in str(job.get("if") or "")
        perms = job.get("permissions")
        if not on_runner or stable_only:
            if (perms or {}).get("actions") == "write" and not (
                    stable_only and (asks_again(job) or clears_the_way(name, job_name, job))):
                out.append(where + " holds `actions: write` and calls no guard")
            continue
        jobs_ += 1
        line = (name, job_name) in LINE_JOBS
        if name != PROOF and not line and (name, job_name) not in LINE_EXEMPT:
            out.append(where + ": a runner job of the line's workflows in neither LINE_JOBS (it yields on dgo-stable) "
                               "nor LINE_EXEMPT (why it does not) — on dgo-stable it would go ahead of the proof")
        i = guard_index(job)
        if i is None or i < 0:
            out.append(where + " does not call scripts/ci/step-aside exactly once")
            continue
        steps = job["steps"]
        guard = steps[i]
        flags = guard_flags(guard["run"])
        want_if = guard_if(name, job_name)
        if guard.get("if") != want_if:
            out.append("%s: the guard's `if:` is %r, not %r" % (where, guard.get("if"), want_if))
        if "GH_TOKEN" not in (guard.get("env") or {}):
            out.append(where + ": the guard has no GH_TOKEN")
        if ("--dispatch-too" in flags) != name.startswith("android-"):
            out.append(where + ": --dispatch-too is the Android builds' alone")
        if ("--line-too" in flags) != line:
            out.append(where + ": --line-too is LINE_JOBS' alone — never the proof's, nor a job whose line run must "
                               "not yield")
        if not line and name != PROOF and re.search(r"github\.ref(_name)?\s*==\s*'(refs/heads/)?dgo-stable'",
                                                    str(job.get("if") or "")):
            out.append(where + ": runs on dgo-stable alone, so a guard that keeps dgo-stable out never asks — a line "
                               "job says --line-too (LINE_JOBS)")
        for before in steps[:i]:   # only the checkout of the guard itself comes before it
            sparse = str((before.get("with") or {}).get("sparse-checkout"))
            if not str(before.get("uses", "")).startswith("actions/checkout@") or "scripts/ci/step-aside" not in sparse:
                out.append(where + ": a step other than the guard's own checkout runs before it")
            elif before.get("if") != want_if and not ("if" not in before and "scripts/ci/gates-asked" in sparse):
                out.append("%s: the guard's checkout has `if:` %r, not %r" % (where, before.get("if"), want_if))
        if not isinstance(perms, dict) or perms.get("actions") != "write":
            out.append(where + ": calls the guard without its own `actions: write`")
        elif perms.get("contents") != top.get("contents"):
            out.append(where + ": its contents permission is not the workflow's (%r)" % top.get("contents"))
    if not jobs_:
        out.append(name + ": no job on the runner found — the check measured nothing")
    return out


#: What this suite tests, for the CI's «changed since the last green» (scripts/ci/since_green.py): 46 s of G72's one
#: `scripts/` worker on batch 114. It reads every workflow and the guard, re-ask and gates scripts beside it.
SUBJECTS = (".github/workflows", "scripts/ci", "scripts/test_ci_step_aside.py")

if __name__ == "__main__":
    _spec = importlib.util.spec_from_file_location("since_green", REPO / "scripts" / "ci" / "since_green.py")
    since_green = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(since_green)
    since_green.or_not_run(REPO, SUBJECTS)
    unittest.main(verbosity=2)
