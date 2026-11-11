"""door — the job door: a linked office asks this office for a NAMED job, never a shell (DGO-1797, package 9).

    python3 door.py work      the worker, in ci-runner-agent (agent.sh starts it and keeps it running)

The server (server.py) serves the routes and only VERIFIES and QUEUES; the worker, beside the runner with the
engine's socket and the office's checkout, RUNS — one job at a time. They share the app's volume:

  <state>/door/queue/<id>.json     a request the server accepted, waiting for the worker
  <state>/door/jobs/<id>/job.json  the request, once the worker claimed it (an atomic rename: one worker, one job)
  <state>/door/jobs/<id>/state.json  queued | running | done | failed | timeout | cancelled, its exit and times
  <state>/door/jobs/<id>/log       stdout and stderr together, at most LOG_MAX bytes

WHO MAY ASK: a linked office whose request the link's door SIGNED (x-dgo-office + x-dgo-identity, verified by the
platform's one verifier, /opt/dgo/link_identity.py) and that this office lists in CI_RUNNER_ACCEPT_FROM — or the app's
own CLI (loopback). A claim on an address is not enough here: a door that RUNS something asks for the signature.
WHAT: jobs.json — each job an argv template whose every argument is a fixed word or a {placeholder} matching its
pattern. v1: read-only bbox verbs in this office's checkout, class light (no heavy-job slot), each with its timeout.
Each job is one bar on «כל מקביל» through the app's record (record.py → jobs.jsonl → the server's flow), named
«door · <job>» and «<user>@<office>». Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS_FILE = Path(os.environ.get("CI_RUNNER_JOBS", str(HERE / "jobs.json")))
LOG_MAX = 1 << 20                 # 1 MiB: a read verb's answer, never a disk filled by a runaway
LOG_PAGE = 64 << 10               # what one GET of the log returns at most
QUEUE_MAX = 20                    # waiting requests in all…
QUEUE_PER_OFFICE = 5              # …and from one office: a peer that loops cannot fill the queue for the others
KEEP_JOBS = 100                   # finished jobs kept on the volume, the newest
ID_RE = re.compile(r"^[0-9]{10}-[0-9a-f]{8}\Z")
DONE = ("done", "failed", "timeout", "cancelled")
#: who the app's own CLI is: a name no office id can be (an office id is [a-z][a-z0-9-]+), so an office called
#: «local» is an office like any other (the second reader: it read and cancelled the CLI's jobs)
LOCAL = "@local"
_ENQUEUE = threading.Lock()       # the queue's caps are counted and written as one step (30 asks at once broke them)


def catalog(path: Path | None = None) -> dict:
    """The named jobs, as jobs.json declares them ({} when it cannot be read: then nothing is runnable)."""
    try:
        data = json.loads((path or JOBS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def names(path: Path | None = None) -> dict:
    """What a caller may ask for — the job names, each with its class, timeout and verb templates."""
    return {n: {"class": j.get("class", "light"), "timeout_s": j.get("timeout_s"), "what": j.get("what", ""),
                "verbs": j.get("verbs", []), "args": j.get("args", {})}
            for n, j in catalog(path).items()}


def validate(body, path: Path | None = None) -> tuple[list | None, str]:
    """`{"name": "bbox", "args": {"verb": [...]}}` → (the argv to run, "") or (None, why). Every word of the verb must
    equal its template's word, or match the pattern of the template's {placeholder}; the length must be the
    template's. Nothing else reaches a command line."""
    jobs = catalog(path)
    if not isinstance(body, dict):
        return None, "the request is a JSON object: {\"name\": …, \"args\": {…}}"
    name = body.get("name")
    if not isinstance(name, str) or name not in jobs:
        return None, f"no such job {str(name)[:40]!r} — the jobs this office runs: {', '.join(sorted(jobs)) or 'none'}"
    job = jobs[name]
    verb = (body.get("args") or {}).get("verb") if isinstance(body.get("args"), dict) else None
    if not isinstance(verb, list) or not all(isinstance(w, str) for w in verb) or not verb:
        return None, f"{name}: args.verb is a list of words, e.g. {json.dumps((job.get('verbs') or [[]])[0])}"
    pats = job.get("args") or {}
    for tpl in job.get("verbs") or []:
        if len(tpl) != len(verb):
            continue
        ok = True
        for want, got in zip(tpl, verb):
            m = re.fullmatch(r"\{([a-z_]+)\}", want)
            if m:
                pat = pats.get(m.group(1))
                ok = bool(pat) and re.fullmatch(pat, got) is not None
            else:
                ok = want == got
            if not ok:
                break
        if ok:
            return list(verb), ""
    return None, (f"{name}: «{' '.join(verb)[:120]}» is not one of the verbs this office runs: "
                  + "; ".join(" ".join(t) for t in job.get("verbs") or []))


def _dirs(state: Path) -> tuple[Path, Path]:
    q, j = state / "door" / "queue", state / "door" / "jobs"
    q.mkdir(parents=True, exist_ok=True)
    j.mkdir(parents=True, exist_ok=True)
    return q, j


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def enqueue(state: Path, name: str, argv: list, office: str, user: str) -> tuple[dict | None, str]:
    """Queue one validated job for the worker → ({id, state}, "") or (None, why) when the queue is full."""
    q, _ = _dirs(state)
    with _ENQUEUE:
        waiting = [_read(p) for p in q.glob("*.json")]
        if len(waiting) >= QUEUE_MAX:
            return None, f"the job door's queue is full ({QUEUE_MAX} waiting) — ask again in a minute"
        if sum(1 for w in waiting if w.get("office") == office) >= QUEUE_PER_OFFICE:
            return None, f"{office} already has {QUEUE_PER_OFFICE} jobs waiting here — ask again when one ends"
        jid = f"{int(time.time())}-{secrets.token_hex(4)}"
        job = {"id": jid, "name": name, "argv": argv, "office": office, "user": user,
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _write(q / f"{jid}.json", job)
    return {"id": jid, "state": "queued"}, ""


def find(state: Path, jid: str, office: str) -> tuple[dict | None, str]:
    """A job's request and state, for the office that asked for it (or the local CLI) → (row, "") or (None, why)."""
    if not ID_RE.match(str(jid or "")):
        return None, "no such job"
    q, j = _dirs(state)
    job = _read(q / f"{jid}.json") or _read(j / jid / "job.json")
    if not job:
        return None, "no such job"
    if office != LOCAL and job.get("office") != office:
        return None, "no such job"                       # another office's job is not even said to exist
    st = _read(j / jid / "state.json") or {"state": "queued"}
    return {**job, **st}, ""


def log_page(state: Path, jid: str, offset: int) -> bytes:
    """Up to LOG_PAGE bytes of a job's log from `offset`, ending on a whole UTF-8 character: a caller across the link
    gets TEXT, counts its bytes for the next offset, and a page cut inside «ש» would make that count drift."""
    p = state / "door" / "jobs" / jid / "log"
    try:
        with open(p, "rb") as fh:
            fh.seek(max(0, int(offset)))
            page = fh.read(LOG_PAGE)
    except (OSError, ValueError, OverflowError):             # an offset past any file is an empty page, not a 500
        return b""
    try:
        page.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start >= len(page) - 3 and e.reason == "unexpected end of data":
            page = page[:e.start]                         # the rest of that character comes with the next page
    return page


def cancel(state: Path, jid: str, office: str) -> tuple[dict | None, str]:
    """A job that still WAITS is taken off the queue; one that runs is not stopped (v1 says so)."""
    row, why = find(state, jid, office)
    if row is None:
        return None, why
    q, j = _dirs(state)
    try:
        os.remove(q / f"{jid}.json")
    except FileNotFoundError:
        return None, f"the job is {row.get('state', 'running')} — only a job that still waits can be cancelled"
    (j / jid).mkdir(parents=True, exist_ok=True)
    _write(j / jid / "job.json", {k: row[k] for k in ("id", "name", "argv", "office", "user", "at") if k in row})
    _write(j / jid / "state.json", {"state": "cancelled", "ended": int(time.time())})
    prune(state)                                          # asking and cancelling in a loop never fills the volume
    return {"id": jid, "state": "cancelled"}, ""


# ── the worker ────────────────────────────────────────────────────────────────────────────────────────────────────

def _record(kind: str, job: dict, said: str) -> None:
    """The job as one bar on «כל מקביל»: the app's own record (record.py), named as a job of the door."""
    try:
        import record
        env = {"GITHUB_WORKFLOW": f"door · {job.get('name')}", "GITHUB_JOB": "door", "GITHUB_RUN_ID": job.get("id", ""),
               "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "", "GITHUB_ACTOR": f"{job.get('user')}@{job.get('office')}",
               "GITHUB_EVENT_NAME": "door", "GITHUB_REF_NAME": " ".join(job.get("argv") or [])[:80],
               "GITHUB_REPOSITORY": "", "RUNNER_NAME": "door"}
        record.append(record.line(kind, "0", said, env=env))
    except Exception as e:                                # noqa: BLE001 — a record never stops a job
        print(f"door: the record was not written: {e}", file=sys.stderr, flush=True)


def _env(repo: str) -> dict:
    """What a job's process gets: a path, a home, a language and the office's checkout — nothing of the agent's
    own environment (no token, no registration, nothing a job step of GitHub's would see either). BBOX_VIA=1: the job
    came from another office, so a verb never goes on to a second hop (the mark `bbox via` sets the same way)."""
    # BBOX_DOCKER_SOCK names the engine's socket as mounted here: without it bbox looks for its own project engine at
    # /run/bbox-docker.sock and, root with dockerd in the image, STARTS one — in a session of its own the job's timeout
    # never reaches (the second reader measured it outliving the job)
    sock = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/root"),
            "LANG": "C.UTF-8", "TERM": "dumb", "BBOX_HEAVY": "off", "BBOX_VIA": "1", "BBOX_REPO_HOST": repo,
            "DOCKER_HOST": sock, "BBOX_DOCKER_SOCK": sock.split("unix://", 1)[-1],
            # …and BBOX_DOCKER_HOST, which bbox takes as it is and never probes: with the socket alone, an engine too
            # busy to answer `docker info` sent bbox to start its own (the same reader, second round)
            "BBOX_DOCKER_HOST": sock}


def run(state: Path, job: dict, repo: str, path: Path | None = None) -> dict:
    """Run one claimed job to its end: its argv in the checkout, its own process group, its timeout, its log."""
    _, j = _dirs(state)
    d = j / job["id"]
    # THE WORKER CHECKS AGAIN, against its own catalog: the queue is a directory the server writes, and the worker
    # holds the engine's socket — a request that did not come through validate() runs nothing (the second reader ran
    # a hand-written `engine shell id` through it)
    argv, why = validate({"name": job.get("name"), "args": {"verb": job.get("argv")}}, path)
    if argv is None:
        with open(d / "log", "ab") as log:
            log.write(f"door: refused by the worker — {why}\n".encode())
        out = {"state": "failed", "exit": None, "started": int(time.time()), "ended": int(time.time()),
               "why": "not a job of this office's list"}
        _write(d / "state.json", out)
        return out
    spec = catalog(path).get(job.get("name")) or {}
    timeout = max(1, min(int(spec.get("timeout_s") or 300), 600))
    t0 = time.time()
    _write(d / "state.json", {"state": "running", "started": int(t0)})
    _record("started", job, f"{job.get('office')} asked: bbox {' '.join(job.get('argv') or [])}"[:300])
    argv = ["./bbox", *argv]
    state_now, code = "failed", None
    with open(d / "log", "wb") as log:
        try:
            p = subprocess.Popen(argv, cwd=repo, env=_env(repo), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            log.write(f"door: the job could not start: {e}\n".encode())
            p = None
        if p is not None:
            written = [0]

            def pump():
                for chunk in iter(lambda: p.stdout.read(8192), b""):
                    room = LOG_MAX - written[0]
                    if room > 0:
                        log.write(chunk[:room])
                        log.flush()
                        written[0] += min(len(chunk), room)
            t = threading.Thread(target=pump, daemon=True)
            t.start()
            try:
                code = p.wait(timeout=timeout)
                state_now = "done" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
                p.wait()
                code, state_now = 124, "timeout"
            t.join(timeout=5)
            if written[0] >= LOG_MAX:
                log.write(f"\ndoor: the log was cut at {LOG_MAX} bytes\n".encode())
            if state_now == "timeout":
                log.write(f"\ndoor: stopped after {timeout} s (the job's timeout)\n".encode())
    end = time.time()
    out = {"state": state_now, "exit": code, "started": int(t0), "ended": int(end)}
    _write(d / "state.json", out)
    _record("ended", job, f"{state_now} · exit {code} · {int(end - t0)} s")
    return out


def claim(state: Path) -> dict | None:
    """The oldest waiting job, claimed by an atomic rename (None when nothing waits)."""
    q, j = _dirs(state)
    for p in sorted(q.glob("*.json"), key=lambda x: x.name):
        job = _read(p)
        jid = job.get("id", "")
        if not ID_RE.match(jid) or p.name != f"{jid}.json":
            p.unlink(missing_ok=True)                     # not a request the server wrote
            continue
        (j / jid).mkdir(parents=True, exist_ok=True)
        try:
            os.rename(p, j / jid / "job.json")
        except OSError:
            continue                                      # taken (or cancelled) in between
        return job
    return None


def prune(state: Path) -> None:
    _, j = _dirs(state)
    done = sorted((d for d in j.iterdir() if d.is_dir() and _read(d / "state.json").get("state") in DONE),
                  key=lambda d: d.name)
    for d in done[:-KEEP_JOBS] if len(done) > KEEP_JOBS else []:
        for f in d.iterdir():
            f.unlink(missing_ok=True)
        d.rmdir()


def recover(state: Path) -> int:
    """At the worker's start: a job it had claimed and not finished (it was stopped, the container restarted) is
    settled as failed, said in its log — never left «queued» or «running» for ever. Returns how many."""
    _, j = _dirs(state)
    n = 0
    for d in j.iterdir():
        if d.is_dir() and (d / "job.json").exists() and _read(d / "state.json").get("state") not in DONE:
            with open(d / "log", "ab") as log:
                log.write(b"\ndoor: the worker stopped before this job ended - it did not finish\n")
            _write(d / "state.json", {"state": "failed", "exit": None, "ended": int(time.time()),
                                      "why": "the worker stopped before the job ended"})
            n += 1
    return n


def work(state: Path, repo: str, once: bool = False, tick: float = 2.0) -> None:
    left = recover(state)
    if left:
        print(f"door: {left} job(s) the worker had not finished are settled as failed", file=sys.stderr, flush=True)
    if not repo or not (Path(repo) / "bbox").exists():
        print(f"door: no office checkout at {repo!r} — the job door takes no jobs here", file=sys.stderr, flush=True)
        if once:
            return
    idle = 0.0
    while True:
        job = claim(state) if repo else None
        if job:
            run(state, job, repo)
            prune(state)
            if once:
                return
            continue
        if once:
            return
        time.sleep(tick)
        idle += tick
        if idle >= 60:                                    # cancelled jobs are pruned even when nothing runs
            prune(state)
            idle = 0.0


if __name__ == "__main__":
    if sys.argv[1:2] == ["work"]:
        work(Path(os.environ.get("CI_RUNNER_STATE", "/state")), os.environ.get("CI_RUNNER_DOOR_REPO") or "")
    else:
        print("usage: door.py work", file=sys.stderr)
        sys.exit(2)
