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
network, no token. The last cases read the four workflows: every job of theirs on the runner that can run on a
branch other than dgo-stable calls the guard before anything else, under the one `if:` that keeps dgo-stable and
every non-branch ref out, and only those jobs hold `actions: write` — and a copy with that `if:` inverted is refused.
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "ci" / "step-aside"
WORKFLOWS = ("gates-hosted.yml", "go-test.yml", "android-app.yml", "android-engine.yml")
GUARD_IF = "startsWith(github.ref, 'refs/heads/') && github.ref != 'refs/heads/dgo-stable'"
TOKEN = "ghs_not-a-real-token-0123456789"
RUN = "4242"
RUNNER = "portable-ssd"

# A stand-in for curl: the route whose `match` is in the URL (and whose method is the call's) answers; anything
# else is a failure, as curl -f would say it. Each call is one JSON line in the log.
CURL = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
url = [a for a in args if a.startswith("http")][-1]
headers = sys.stdin.read() if "@-" in args else ""
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps({"method": method, "url": url, "argv": args, "headers": headers}) + "\n")
for r in json.load(open(os.environ["STUB_ROUTES"])):
    if r["match"] in url and r.get("method", "GET") == method:
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
        routes_file = os.path.join(self.tmp, "routes.json")
        with open(routes_file, "w") as f:
            json.dump(routes, f)
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
        self.assertEqual(len(said), 1, "one decision line, got:\n" + p.stdout + p.stderr)
        output = ""
        if os.path.exists(out_file):
            with open(out_file) as f:
                output = f.read()
        return p, said[0], calls, output

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
        p, said, calls, _ = self.guard([runs("queued", 111), ALONE, CANCEL], ref="refs/heads/dgo-stable")
        self.assert_runs(p, said, calls)
        self.assertEqual(calls, [], "dgo-stable asks GitHub nothing")

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
        for name, doc in self.workflows().items():
            for where in ("checkout", "guard"):
                bad = copy.deepcopy(doc)
                flipped = 0
                for job in bad["jobs"].values():
                    for step in job.get("steps") or []:
                        is_guard = "scripts/ci/step-aside" in str(step.get("run") or "")
                        if step.get("if") == GUARD_IF and (is_guard == (where == "guard")):
                            step["if"] = "github.ref == 'refs/heads/dgo-stable'"
                            flipped += 1
                if where == "checkout" and name == "gates-hosted.yml":
                    self.assertGreater(flipped, 0)   # decide's checkout has no `if:`; gates' and carrier's do
                if flipped:
                    self.assertNotEqual(findings(name, bad), [], "%s: an inverted %s `if:` passed" % (name, where))

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
    hits = [i for i, s in enumerate(job.get("steps") or []) if "scripts/ci/step-aside" in str(s.get("run") or "")]
    return hits[0] if len(hits) == 1 else (None if not hits else -1)


def asks_again(job):
    """The one other job that may hold `actions: write`: the proof's last job, which asks again the runs that stepped
    aside (scripts/ci/re-ask.py, DGO-1848) — its only steps a checkout and that script, nothing else run with it."""
    steps = job.get("steps") or []
    runs = [s.get("run") or "" for s in steps if "run" in s]
    uses = [s.get("uses") or "" for s in steps if "uses" in s]
    return (len(runs) == 1 and runs[0].strip().startswith("python3 ") and runs[0].strip().endswith("scripts/ci/re-ask.py")
            and all(u.startswith("actions/checkout@") for u in uses))


def findings(name, doc):
    """What is wrong with one workflow's use of the guard: [] when nothing is."""
    out = []
    top = doc.get("permissions") or {}
    if top.get("actions") == "write":
        out.append("%s: `actions: write` at the workflow level — only the jobs that call the guard hold it" % name)
    jobs_ = 0
    for job_name, job in doc["jobs"].items():
        where = "%s: job %s" % (name, job_name)
        runs_on = job.get("runs-on")
        on_runner = isinstance(runs_on, list) and "self-hosted" in runs_on
        stable_only = "github.ref == 'refs/heads/dgo-stable'" in str(job.get("if") or "")
        perms = job.get("permissions")
        if not on_runner or stable_only:
            if (perms or {}).get("actions") == "write" and not (stable_only and asks_again(job)):
                out.append(where + " holds `actions: write` and calls no guard")
            continue
        jobs_ += 1
        i = guard_index(job)
        if i is None or i < 0:
            out.append(where + " does not call scripts/ci/step-aside exactly once")
            continue
        steps = job["steps"]
        guard = steps[i]
        if guard.get("if") != GUARD_IF:
            out.append("%s: the guard's `if:` is %r, not %r" % (where, guard.get("if"), GUARD_IF))
        if "GH_TOKEN" not in (guard.get("env") or {}):
            out.append(where + ": the guard has no GH_TOKEN")
        if ("--dispatch-too" in guard["run"]) != name.startswith("android-"):
            out.append(where + ": --dispatch-too is the Android builds' alone")
        for before in steps[:i]:   # only the checkout of the guard itself comes before it
            sparse = str((before.get("with") or {}).get("sparse-checkout"))
            if not str(before.get("uses", "")).startswith("actions/checkout@") or "scripts/ci/step-aside" not in sparse:
                out.append(where + ": a step other than the guard's own checkout runs before it")
            elif before.get("if") != GUARD_IF and not ("if" not in before and "scripts/ci/gates-asked" in sparse):
                out.append("%s: the guard's checkout has `if:` %r, not %r" % (where, before.get("if"), GUARD_IF))
        if not isinstance(perms, dict) or perms.get("actions") != "write":
            out.append(where + ": calls the guard without its own `actions: write`")
        elif perms.get("contents") != top.get("contents"):
            out.append(where + ": its contents permission is not the workflow's (%r)" % top.get("contents"))
    if not jobs_:
        out.append(name + ": no job on the runner found — the check measured nothing")
    return out


if __name__ == "__main__":
    unittest.main(verbosity=2)
