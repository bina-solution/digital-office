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

THE LINE'S OWN (DGO-2111). On dgo-stable, go-test, android-app's build and public-copy's copy (DGO-2123) step aside
for the line's proof too (step-aside --line-too). go-test's and the copy's newest run there is owed as any branch's is:
a newer test of the whole tree covers an older, and a newer copy of the line an older one. A build is not covered by a newer run that built nothing — android-app decides from the push's own range — so its
newest run that stepped aside is owed unless a newer one built (line_build). The line's runs are asked first.

NOT WHILE ANOTHER PROOF WAITS. A run asked again while a version's proof is still queued or running steps aside again at
once; then nothing is asked — that proof's own last job asks.

WHAT A CANCELLED RUN OWES (DGO-2123). Besides a run that stepped aside (its notice), a run CLEARED away — cancelled
while it waited for our runner, none of its cancelled jobs ever on one: step-aside clears the way for a proof so (and a
person's cancel of a waiting run is the same act) — owes its verdict too. A job that waited for another label (GitHub's
own runner) makes it a person's cancel. A run that EXPIRED (step-aside's `superseded` notice: a newer run of its branch
tests its head) owes nothing. Two more answers, on an office branch only (2026-11-20):
  - COVERED: a gates-hosted or go-test run whose head this proof's tree holds is answered by this proof, and by the
    line's own go-test of that tree, which this job asks first — not asked again (the king's ask). Only when the proof's
    gates PASSED (PROOF_GATES, its `needs.gates.result`): a red proof may have stopped before its slow gates; never a
    hand-run, an explicit ask; never public-copy, whose copy nothing else makes.
  - A gates-hosted or go-test run that CANNOT STEP ASIDE WHILE IT WORKS — its workflow file at its head starts no
    watcher (step-aside --watch), a branch that has not taken the line since — is not asked again: asked here, it would
    hold the runner ahead of the next proof for all its minutes. Batch 98 waited 16.5 of them so, behind hp-dgo's
    go-test this job had just asked again. Said; its branch's next push asks it. The Android builds and public-copy's
    copy never had a watcher: asked again as before (their hold is said in the issue).

FAIL OPEN, LOUD. A question GitHub does not answer is a ::warning:: and the rest goes on; this job never fails the proof.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.request

# public-copy too (DGO-2123): its copy job steps aside on an office branch like the others, and with no re-ask its
# runs that did were never run again (measured 2026-11-13…20: one; issues/public-copy-steps-aside-…)
WORKFLOWS = ("gates-hosted.yml", "go-test.yml", "android-app.yml", "android-engine.yml", "public-copy.yml",
             "office-images.yml", "sim-build.yml")
PROOF_WORKFLOW, PROOF_BRANCH = "gates-hosted.yml", "dgo-stable"
#: The line's other workflows — a job of theirs says step-aside --line-too (DGO-2111), so their dgo-stable runs may be
#: owed. The value is None for a test of the whole tree, which any newer run covers, or the name of a BUILD's job: a
#: newer run of a build covers an older one only when that job succeeded (line_build).
LINE = {"go-test.yml": None, "android-app.yml": "apk",
        # the copy of a version follows its proof (DGO-2123): a newer copy of the line covers an older one
        "public-copy.yml": None}
WALK = 40   # a build's dgo-stable runs read back, at most, to find the newest that built
NOTICE_TITLE = "step-aside"
SUPERSEDED = "superseded"   # step-aside's notice on a run that expired: a newer run of its branch tests its head
CLEARED = "cleared"         # cancelled while it waited for OUR runner: no cancelled job of it was ever on a runner
#: The workflows whose line files start a watcher beside their long steps (step-aside --watch): a run of theirs whose
#: own file starts none — a branch that has not taken the line since — cannot yield while it works. The others never
#: had one (the Android builds, public-copy's copy): they are asked again as before, and said in the issue.
WATCHED = ("gates-hosted.yml", "go-test.yml")
#: The workflows a proof's tree answers for an office branch: its gates, and the line's own go-test of that tree,
#: which re-ask asks first. Never public-copy (its copy is of refs/green, made by nothing else) nor a build.
COVERED_BY_PROOF = ("gates-hosted.yml", "go-test.yml")
#: What the proof's gates job ended in (`needs.gates.result`): only a GREEN proof ran every gate on its tree. A red one
#: may have stopped in its fast lane, or before it, so its slow gates never ran (the reader of ac436e0b8): after it, a
#: branch's run is asked again, and gives the culprit's branch a verdict of its own
TESTED = ("success",)
#: a watcher in a workflow file — a step's line that runs step-aside --watch (not a comment that names it)
WATCH = re.compile(r"""^[^#\n]*scripts/ci/step-aside["']?[^\n#]*\s--watch\b""", re.M)
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

    def compare(self, base: str, head: str) -> str:
        """GitHub's word for head against base: «ahead» or «identical» when head's tree holds base."""
        return str(self._call("GET", f"repos/{self.repo}/compare/{base}...{head}?per_page=1").get("status") or "")

    def watches(self, path: str, sha: str) -> bool:
        """Does this workflow file, at this commit, start a watcher (step-aside --watch) beside its work?"""
        got = self._call("GET", f"repos/{self.repo}/contents/{path}?ref={sha}")
        return bool(WATCH.search(base64.b64decode(got.get("content") or "").decode("utf-8", "replace")))


def another_proof_waits(gh, own_run: int) -> bool:
    """Is a version's proof other than this run still queued or running?"""
    for status in WAITING:
        if any(r.get("id") != own_run for r in gh.runs(PROOF_WORKFLOW, PROOF_BRANCH, status)):
            return True
    return False


def why_cancelled(gh, run: dict):
    """What this cancelled run owes, by how it was cancelled: NOTICE_TITLE (it stepped aside — its notice, on whichever
    of its jobs carries it), SUPERSEDED (it expired — its notice: it owes nothing), CLEARED (it was cancelled while it
    waited: no cancelled job of it was ever on a runner) or None (a person stopped it at work)."""
    jobs = [j for j in gh.jobs(run["id"]) or [] if isinstance(j, dict)]
    titles = set()
    for job in jobs:
        cid = str(job.get("check_run_url") or "").rstrip("/").rsplit("/", 1)[-1]
        notes = gh.annotations(int(cid)) if cid.isdigit() else []
        titles |= {a.get("title") for a in notes if isinstance(a, dict)} if isinstance(notes, list) else set()
    if SUPERSEDED in titles:
        return SUPERSEDED
    if NOTICE_TITLE in titles:
        return NOTICE_TITLE
    # cleared: every job of it that was stopped was waiting for OUR runner and never on one — a job waiting for another
    # label (android-engine's qemu, GitHub's own runner, which takes no job while billing is stopped) is a person's cancel
    stopped = [j for j in jobs if j.get("conclusion") == "cancelled"]
    return CLEARED if stopped and not any(j.get("runner_name") for j in stopped) and all(
        "portable" in (j.get("labels") or []) for j in stopped) else None


def askable(gh, branch: str, r: dict):
    """True when this run stepped aside, or was cleared away, and may be asked again; False when it owes nothing; None
    when it cannot be told or may not be asked (said, as a warning)."""
    try:
        if why_cancelled(gh, r) not in (NOTICE_TITLE, CLEARED):
            return False
    except Exception as e:                             # one run that cannot be read does not stop the others
        warn(f"re-ask: run {r['id']} on {branch} could not be read ({type(e).__name__}); not asked again this time")
        return None
    if int(r.get("run_attempt") or 1) >= MAX_ATTEMPTS:
        # on the line a push asks for no APK unless it touches the phone's paths: there a person re-runs it by hand
        again = (f"re-run it by hand: gh run rerun {r['id']} --failed" if branch == PROOF_BRANCH else "push again")
        warn(f"re-ask: run {r['id']} on {branch} stepped aside {r.get('run_attempt')} times; not asked again — {again}")
        return None
    return True


def built(gh, r: dict, job: str) -> bool:
    """Did this run's build job succeed?"""
    return any(isinstance(j, dict) and j.get("name") == job and j.get("conclusion") == "success"
               for j in gh.jobs(r["id"]) or [])


def line_build(gh, runs: list, job: str):
    """A build of the line to ask again, or None — its dgo-stable runs, NEWEST FIRST. Only a newer run that decided it
    had NOTHING to build is walked past: android-app's `phone` decides from the push's own range, so batch P2 with no
    phone change would otherwise hide batch P1's APK, which stepped aside (the second reader of DGO-2123). The first
    other run answers: one that stepped aside is owed — the newest such, and enough: `phone` ran before `apk` yielded,
    so it builds, and its tree holds the older ones'; one that BUILT covers every older one; one still going decides
    for itself (a later proof's re-ask asks what is left); one that failed, or that a person cancelled, is that tree's
    own answer — an older tree is never built behind it (the second reader of the fix)."""
    for r in runs[:WALK]:
        if r.get("status") != "completed":
            return None
        conclusion = r.get("conclusion")
        if conclusion == "cancelled":
            return r if askable(gh, PROOF_BRANCH, r) else None
        if conclusion != "success":
            return None
        try:
            if built(gh, r, job):
                return None
        except Exception as e:
            warn(f"re-ask: run {r['id']} on {PROOF_BRANCH} could not be read ({type(e).__name__}); its build is "
                 "not asked again this time")
            return None
    if len(runs) > WALK:
        print(f"re-ask: the newest {WALK} runs on {PROOF_BRANCH} built nothing and none stepped aside; older ones "
              "are not read")
    return None


def covered(gh, branch: str, r: dict, proof_sha: str) -> bool:
    """Does the tree of the proof that has just ended hold this office-branch run's head? Then that proof answers it,
    with the line's own runs of its tree (asked first, here) — said. Never a hand-run: an explicit ask, answered for
    its own tree. A question GitHub does not answer is no: asked as before."""
    sha = str(r.get("head_sha") or "")
    if not proof_sha or not sha or r.get("event") == "workflow_dispatch":
        return False
    try:
        held = gh.compare(sha, proof_sha) in ("ahead", "identical")
    except Exception as e:
        warn(f"re-ask: whether this proof holds run {r['id']}'s head on {branch} could not be read ({type(e).__name__}); "
             "it is asked as before")
        return False
    if held:
        print(f"re-ask: run {r['id']} on {branch} — its head {sha[:9]} is in this proof's tree: covered, not asked again")
    return held


def yields(gh, branch: str, r: dict, workflow: str) -> bool:
    """Can this office-branch run step aside while it works — does its workflow file, at its head, start a watcher? One
    that cannot would hold the runner ahead of the next proof for all its minutes: it is not asked again (said). A file
    that cannot be read is asked as before."""
    sha, path = str(r.get("head_sha") or ""), str(r.get("path") or "")
    if not sha or not path:
        return True
    try:
        if gh.watches(path, sha):
            return True
    except Exception as e:
        warn(f"re-ask: whether run {r['id']}'s {workflow} watches while it works could not be read "
             f"({type(e).__name__}); it is asked as before")
        return True
    warn(f"re-ask: run {r['id']} ({workflow} on {branch}) cannot step aside while it works — {path} at {sha[:9]} starts "
         f"no watcher (step-aside --watch): not asked again, or it would hold the runner ahead of the next proof "
         f"(batch 98 waited 16.5 minutes so, 2026-11-20); {branch}'s next push asks it, and once {branch} takes the line "
         "its runs yield")
    return False


def owed(gh, runs: list, workflow: str = PROOF_WORKFLOW, proof_sha: str = "") -> list:
    """[(branch, run)] — per branch, the newest run that tested something, when step-aside cancelled it or cleared it
    away. dgo-stable's own runs count only for the line's other workflows (LINE: go-test, android-app's build —
    step-aside --line-too, DGO-2111), never for the proof itself; a build of the line is owed by line_build(). An office
    branch's run is not owed when this proof covers it, nor when it cannot step aside while it works (the header)."""
    newest: dict = {}
    line: list = []
    for r in runs:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        branch = r.get("head_branch") or ""
        if (not branch or (branch == PROOF_BRANCH and workflow not in LINE) or r.get("conclusion") == "skipped"
                or r.get("event") in SKIP_EVENTS):
            continue                                   # tested nothing, or never steps aside: neither owes nor hides
        if branch == PROOF_BRANCH and LINE[workflow]:
            line.append(r)
            continue
        if branch not in newest or r["id"] > newest[branch]["id"]:
            newest[branch] = r
    out = []
    if line:
        r = line_build(gh, sorted(line, key=lambda x: -x["id"]), LINE[workflow])
        if r is not None:
            out.append((PROOF_BRANCH, r))
    for b, r in sorted(newest.items()):
        if r.get("status") != "completed" or r.get("conclusion") != "cancelled":
            continue
        if not askable(gh, b, r):
            continue
        # the line's copy follows ITS proof alone: a copy of this very head, once this proof is green. A red proof's
        # copy would publish a red commit, and an older batch's copy is no one's to make now (the reader of the change)
        if b == PROOF_BRANCH and workflow == "public-copy.yml" and (not proof_sha or r.get("head_sha") != proof_sha):
            print(f"re-ask: the line's copy run {r['id']} is of {str(r.get('head_sha') or '?')[:9]} — not this green "
                  "proof's head: not asked again (a copy follows its own proof)")
            continue
        # the line's own (go-test on dgo-stable): never covered by the proof, which runs no go test, and its files are
        # the line's newest
        if b == PROOF_BRANCH or (
                not (workflow in COVERED_BY_PROOF and covered(gh, b, r, proof_sha))
                and (workflow not in WATCHED or yields(gh, b, r, workflow))):
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
    # this proof's head — what it covers (the header) — when its gates passed; a proof cancelled, red, or whose decide
    # asked nothing answers for no run (the readers of 59774eeb7 and ac436e0b8)
    gates = os.environ.get("PROOF_GATES", "")
    proof_sha = (os.environ.get("GITHUB_SHA") or "") if gates in TESTED else ""
    if not proof_sha:
        print(f"re-ask: this proof's gates ended «{gates or 'unknown'}» — no run is taken as covered by it")
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
            chosen += [(wf, b, r) for b, r in owed(gh, gh.runs(wf, pages=PAGES), wf, proof_sha)]
        except Exception as e:
            warn(f"re-ask: {wf}'s runs could not be read ({type(e).__name__}); its runs are not asked again this time")
    if not chosen:
        print("re-ask: no run that stepped aside is still owed its verdict")
        return 0
    chosen.sort(key=lambda c: c[1] != PROOF_BRANCH)    # the line's own first: the cut at MAX never drops them
    # (stable: within each, the order of WORKFLOWS)
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
