"""record.py — one line of a job's record on the app's volume (DGO-1797).

    python3 record.py <waiting|started|refused|ended> <waited_s> <the machine's state, one line>

Run by prejob.sh and postjob.sh inside ci-runner-agent, with the job's own GITHUB_* environment. It appends one JSON
object to <state>/jobs.jsonl and nothing else: the screen's server (server.py) reads the file, and it is the server
that puts each new line on the office's stream (`dgo:flow:ci-runner`) — so the office's redis password never has to
be in the runner's environment, which every job step inherits. Every field here comes from the runner's GITHUB_*
facts; none of GitHub's tokens is among them. Standard library only. It never fails the job: a record that cannot be
written is said on stderr, and the job goes on.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

STATE = os.environ.get("CI_RUNNER_STATE", "/state")
JOBS = os.path.join(STATE, "jobs.jsonl")
KEEP = 2000                       # lines kept when the record is trimmed: about a month of a busy runner
TRIM_AT = 2 * KEEP
KINDS = {"waiting": "job.waiting", "started": "job.started", "refused": "job.failed", "ended": "job.ended"}
TITLES = {"waiting": "ממתין בדלת", "started": "התחיל", "refused": "נדחה בדלת", "ended": "הסתיים"}
FACTS = ("GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REF_NAME",
         "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "GITHUB_REPOSITORY", "RUNNER_NAME")


def facts(env=os.environ) -> dict:
    """The job as the runner names it: workflow, job, run, commit, branch, who asked, and the runner."""
    return {k[len("GITHUB_"):].lower() if k.startswith("GITHUB_") else k.lower(): env.get(k, "") for k in FACTS}


def line(kind: str, waited_s: str, state: str, env=os.environ, now=None) -> dict:
    f = facts(env)
    return {"at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind,
            "waited_s": int(waited_s) if str(waited_s).isdigit() else 0, "machine": state[:300], **f}


def span_id(rec: dict) -> str:
    """One job, one bar: the run, its attempt and the job — the same on its start and on its end."""
    return ".".join(str(rec.get(k) or "") for k in ("run_id", "run_attempt", "job"))


def title(rec: dict) -> str:
    """«gates-hosted · 57ef890 · push של bina-solution — התחיל»: what a person reads on the timeline."""
    sha = (rec.get("sha") or "")[:7]
    who = f"{rec.get('event_name') or 'run'} של {rec.get('actor') or '?'}"
    return " · ".join(x for x in (rec.get("workflow") or "job", sha, who) if x) + f" — {TITLES[rec['kind']]}"


def append(rec: dict, path: str = JOBS) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) > TRIM_AT:                             # a window, not an archive: the last KEEP lines stay
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-KEEP:])
        os.replace(tmp, path)


def main(argv) -> int:
    if len(argv) != 4 or argv[1] not in KINDS:
        print("usage: record.py <waiting|started|refused|ended> <waited_s> <state>", file=sys.stderr)
        return 2
    try:
        append(line(argv[1], argv[2], argv[3]))
    except OSError as e:
        print(f"record: the job's record was not written: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
