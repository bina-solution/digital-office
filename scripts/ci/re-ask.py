#!/usr/bin/env python3
"""re-ask — once a version's proof has ended, the runs that stepped aside for it are asked again.

    python3 scripts/ci/re-ask.py             # the last job of gates-hosted.yml on dgo-stable (`re-ask`)
    python3 scripts/ci/re-ask.py --dry-run   # say what would be asked, ask nothing

WHY (DGO-1848, issues/the-versions-proof-stands-behind-office-branch-jobs-on-the-one-runner-which-has-no-queue-
priorities.yaml). scripts/ci/step-aside cancels an office-branch run while a version's proof waits for the one runner,
and says «the next push asks again» — but a branch with no next push never got its verdict, and the android runs that
stepped aside were never built. This is the «again». It runs as the proof's own last job (not a `workflow_run`
workflow: that trigger fires only from the default branch's file, and this repository's default branch carries none).

WHICH RUNS. Per workflow and branch, the branch's runs are walked newest first, past the ones that tested nothing
(`skipped`: a push whose gates were not asked) and past a pull request's runs (step-aside never steps aside there, and
they carry the branch's name); the first run left decides. It is asked again only when it was
CANCELLED BY STEP-ASIDE — its job carries step-aside's own `::notice title=step-aside::`, read back as a check-run
annotation — so a run somebody cancelled by hand, a run that ran, or one still going owes nothing. No time window: the
newest real run per branch bounds the work, and a run that stepped aside before this proof began is the case step-aside
was built for. Only its cancelled jobs are run again (`rerun-failed-jobs`). At most MAX a proof, and a run already
attempted MAX_ATTEMPTS times is said, not asked again. Runs are read PAGES pages deep per workflow (about four days of
this repository's pushes). A known gap: a gates-hosted run whose `decide` said «no gates» concludes success and hides
an older run that stepped aside — reading every candidate's jobs to tell them apart costs a call per run, for a case
the next push answers.

NOT WHILE ANOTHER PROOF WAITS. A run asked again while a version's proof is still queued or running steps aside again at
once; then nothing is asked — that proof's own last job asks.

FAIL OPEN, LOUD. A question GitHub does not answer is a ::warning:: and the rest goes on; this job never fails the proof.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

WORKFLOWS = ("gates-hosted.yml", "go-test.yml", "android-app.yml", "android-engine.yml")
PROOF_WORKFLOW, PROOF_BRANCH = "gates-hosted.yml", "dgo-stable"
NOTICE_TITLE = "step-aside"
WAITING = ("queued", "pending", "waiting", "requested", "in_progress")
MAX = 8
MAX_ATTEMPTS = 5
PAGES = 3
SKIP_EVENTS = ("pull_request", "pull_request_target")


def warn(msg: str) -> None:
    print(f"::warning::{msg}")


class GitHub:
    """The calls this needs, with the job's token in a header (never on a command line)."""

    def __init__(self, repo: str, token: str, api: str = "https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api.rstrip("/")

    def _call(self, method: str, path: str):
        req = urllib.request.Request(f"{self.api}/{path}", method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
        return json.loads(body) if body else {}

    def runs(self, workflow: str, branch: str = "", status: str = "", pages: int = 1) -> list:
        out = []
        for page in range(1, pages + 1):
            q = (f"per_page=100&page={page}" + (f"&branch={branch}" if branch else "")
                 + (f"&status={status}" if status else ""))
            got = self._call("GET", f"repos/{self.repo}/actions/workflows/{workflow}/runs?{q}").get("workflow_runs") or []
            out += got
            if len(got) < 100:
                break
        return out

    def jobs(self, run_id: int) -> list:
        return self._call("GET", f"repos/{self.repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100").get("jobs") or []

    def annotations(self, check_run_id: int) -> list:
        return self._call("GET", f"repos/{self.repo}/check-runs/{check_run_id}/annotations?per_page=100")

    def rerun(self, run_id: int) -> None:
        self._call("POST", f"repos/{self.repo}/actions/runs/{run_id}/rerun-failed-jobs")


def another_proof_waits(gh, own_run: int) -> bool:
    """Is a version's proof other than this run still queued or running?"""
    for status in WAITING:
        if any(r.get("id") != own_run for r in gh.runs(PROOF_WORKFLOW, PROOF_BRANCH, status)):
            return True
    return False


def stepped_aside(gh, run: dict) -> bool:
    """Did step-aside cancel this run? Only its own notice says so — on whichever of the run's jobs carries it."""
    for job in gh.jobs(run["id"]) or []:
        if not isinstance(job, dict):
            continue
        cid = str(job.get("check_run_url") or "").rstrip("/").rsplit("/", 1)[-1]
        notes = gh.annotations(int(cid)) if cid.isdigit() else []
        if isinstance(notes, list) and any(isinstance(a, dict) and a.get("title") == NOTICE_TITLE for a in notes):
            return True
    return False


def owed(gh, runs: list) -> list:
    """[(branch, run)] — per branch, the newest run that tested something, when step-aside cancelled it."""
    newest: dict = {}
    for r in runs:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        branch = r.get("head_branch") or ""
        if (not branch or branch == PROOF_BRANCH or r.get("conclusion") == "skipped"
                or r.get("event") in SKIP_EVENTS):
            continue                                   # tested nothing, or never steps aside: neither owes nor hides
        if branch not in newest or r["id"] > newest[branch]["id"]:
            newest[branch] = r
    out = []
    for b, r in sorted(newest.items()):
        if r.get("status") != "completed" or r.get("conclusion") != "cancelled":
            continue
        try:
            aside = stepped_aside(gh, r)
        except Exception as e:                         # one run that cannot be read does not stop the others
            warn(f"re-ask: run {r['id']} on {b} could not be read ({type(e).__name__}); not asked again this time")
            continue
        if not aside:
            continue
        if int(r.get("run_attempt") or 1) >= MAX_ATTEMPTS:
            warn(f"re-ask: run {r['id']} on {b} stepped aside {r.get('run_attempt')} times; not asked again — push again")
            continue
        out.append((b, r))
    return out


def main(argv=None, gh=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if gh is None:
        repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
        if not repo or not token:
            warn("re-ask: no repository or token (GITHUB_REPOSITORY, GH_TOKEN); nothing asked")
            return 0
        gh = GitHub(repo, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    own = int(os.environ.get("GITHUB_RUN_ID") or 0)
    try:
        if another_proof_waits(gh, own):
            print("re-ask: another version's proof is still queued or running — its own last job asks; nothing now")
            return 0
    except Exception as e:
        warn(f"re-ask: whether another proof waits could not be read ({type(e).__name__}); nothing asked")
        return 0
    chosen = []
    for wf in WORKFLOWS:
        try:
            chosen += [(wf, b, r) for b, r in owed(gh, gh.runs(wf, pages=PAGES))]
        except Exception as e:
            warn(f"re-ask: {wf}'s runs could not be read ({type(e).__name__}); its runs are not asked again this time")
    if not chosen:
        print("re-ask: no run that stepped aside is still owed its verdict")
        return 0
    for wf, branch, run in chosen[:MAX]:
        if a.dry_run:
            print(f"re-ask: would ask again {wf} on {branch} (run {run['id']})")
            continue
        try:
            gh.rerun(run["id"])
            print(f"re-ask: asked again {wf} on {branch} (run {run['id']})")
        except Exception as e:
            warn(f"re-ask: run {run['id']} ({wf} on {branch}) could not be asked again ({type(e).__name__})")
    if len(chosen) > MAX:
        warn(f"re-ask: {len(chosen) - MAX} more run(s) stepped aside and are not asked this time (at most {MAX})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
