"""test_ci_runner.py — «מריץ CI»'s server, its job record and its door's arithmetic, on a temporary volume (DGO-1797).

    python3 apps/ci-runner/tests/test_ci_runner.py

Standard library only, no network: the GitHub calls are not made (no token in a vault that does not answer).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
os.environ.setdefault("CONNECTIONS_URL", "http://127.0.0.1:9")      # a vault that does not answer
import record   # noqa: E402
import server   # noqa: E402

fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ENV = {"GITHUB_WORKFLOW": "gates-hosted", "GITHUB_JOB": "gates", "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1",
       "GITHUB_SHA": "57ef8904b9901632", "GITHUB_ACTOR": "bina-solution", "GITHUB_EVENT_NAME": "push",
       "GITHUB_REF_NAME": "dgo-stable", "GITHUB_TOKEN": "never-read", "RUNNER_NAME": "portable-ssd"}

with tempfile.TemporaryDirectory() as d:
    state = Path(d)
    now = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
    rec = record.line("started", "30", "8000 MB available", env=ENV, now=now)
    check("a record names the job from the runner's own facts", rec["workflow"] == "gates-hosted" and rec["run_id"] == "42"
          and rec["waited_s"] == 30 and rec["at"] == "2026-11-10T20:00:00Z", rec)
    check("no token reaches a record, whatever the environment holds", "never-read" not in json.dumps(rec), rec)
    check("the timeline's title is one line a person reads",
          record.title(rec) == "gates-hosted · 57ef890 · push של bina-solution — התחיל", record.title(rec))
    check("one job, one span: the run, its attempt and the job", record.span_id(rec) == "42.1.gates", record.span_id(rec))

    jobs = state / "jobs.jsonl"
    follower = server.Follower(state)                         # starts at the end: history is not replayed
    record.append(record.line("waiting", "0", "x", env=ENV, now=now), path=str(jobs))
    record.append(record.line("started", "45", "x", env=ENV, now=now), path=str(jobs))
    ev = follower.events()
    check("the follower turns each new line into one event", [e[0] for e in ev] == ["job.waiting", "job.started"], ev)
    check("a start carries its span", ev[1][2].get("span") == "42.1.gates", ev[1][2])
    with jobs.open("a", encoding="utf-8") as fh:
        fh.write('{"kind": "ended", "run_id": "42", "run_attempt": "1", "job": "gat')   # a line still being written
    check("a line still being written waits for its end", follower.events() == [])
    with jobs.open("a", encoding="utf-8") as fh:
        fh.write('es", "at": "2026-11-10T20:05:00Z", "workflow": "gates-hosted"}\n')
    ev = follower.events()
    check("its end shares the span and carries t0 — one bar on «כל מקביל»",
          len(ev) == 1 and ev[0][0] == "job.ended" and ev[0][2]["span"] == "42.1.gates"
          and ev[0][2]["t0"] == int(now.timestamp() * 1000), ev)

    events = server.jobs(20, state)
    check("jobs are newest first", [e["kind"] for e in events] == ["ended", "started", "waiting"], events)
    beat_job = {"job": True}
    check("…and once it ended, nothing runs", server.running_now(events, beat_job) is None)
    check("a started job with no end runs only while the agent says a job runs",
          server.running_now(events[1:], beat_job) is not None and server.running_now(events[1:], {"job": False}) is None)
    with jobs.open("a", encoding="utf-8") as fh:
        fh.write("{cut by a crash\n")
    check("a line a crash cut is passed over", server.jobs(20, state)[0].get("kind") == "ended")

    record.KEEP, record.TRIM_AT = 3, 6
    for _ in range(5):
        record.append(record.line("waiting", "0", "x", env=ENV, now=now), path=str(jobs))
    # 4 lines + 5 appends = 9 without a trim; past TRIM_AT (6) it falls to KEEP (3) and grows again: 3 + 2 = 5
    check("the record is a window: past TRIM_AT it falls to the last KEEP lines", len(jobs.read_text().splitlines()) == 5,
          len(jobs.read_text().splitlines()))
    check("…and the follower, finding it replaced, does not replay it", follower.events() == [] and
          follower.offset == jobs.stat().st_size)
    # a trim that leaves the file LONGER than the old offset: the follower goes on after its last line, by content
    record.KEEP, record.TRIM_AT = 4, 8
    big = server.Follower(state)
    for _ in range(3):
        record.append(record.line("waiting", "0", "padding-" + "x" * 200, env=ENV, now=now), path=str(jobs))
    big.events()
    record.append(record.line("started", "1", "the one new line", env=dict(ENV, GITHUB_RUN_ID="77"), now=now),
                  path=str(jobs))                         # this append trims: the file is replaced, 4 lines kept
    ev = big.events()
    check("a trim that leaves the file longer than the old offset: exactly the new line, once",
          len(ev) == 1 and ev[0][2]["run_id"] == "77", ev)

    t = time.time()
    check("no heartbeat is «unknown»", server.heartbeat(state, now=t)["state"] == "unknown")
    (state / "agent.json").write_text(json.dumps({"state": "running", "listener": True, "job": False, "at": iso(t - 20)}))
    check("a fresh heartbeat is the agent's own word", server.heartbeat(state, now=t)["state"] == "running")
    (state / "agent.json").write_text(json.dumps({"state": "running", "listener": True, "job": True, "at": iso(t - 600)}))
    hb = server.heartbeat(state, now=t)
    check("a heartbeat older than a minute is «not-running», whatever it last said", hb["state"] == "not-running"
          and hb["job"] is False, hb)

    # the HTTP face, on a free port, with this state
    server.STATE = state
    (state / "agent.json").write_text(json.dumps({"state": "paused", "listener": False, "job": False, "at": iso(time.time())}))
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(method, path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    code, body = call("GET", "/healthz")
    check("/healthz answers", code == 200 and body == {"ok": True}, (code, body))
    code, body = call("GET", "/api/status")
    check("status is a canonical op with the heartbeat's state", code == 200 and body["ok"] and body["op"] == "status"
          and body["data"]["agent"] == "paused" and body["data"]["labels"] is None, body)
    code, body = call("GET", "/api/jobs?n=2")
    check("jobs?n=2 answers two", code == 200 and len(body["data"]) == 2, body)
    code, body = call("GET", "/api/queue")
    check("no token in the vault: the queue says so, it does not fail", code == 200 and body["data"]["available"] is False
          and "github-runner-token" in body["data"]["why"] and "runner" not in body["data"], body)
    code, body = call("POST", "/api/pause")
    check("pause from loopback (the CLI) writes the flag", code == 200 and body["data"]["paused"] is True and
          (state / "paused").exists(), body)
    code, body = call("POST", "/api/pause")
    check("pausing twice changes nothing", body["data"]["changed"] is False, body)
    code, body = call("POST", "/api/resume")
    check("resume takes the flag away", code == 200 and not (state / "paused").exists(), body)
    code, body = call("GET", "/nope")
    check("an unknown route is a 404 that says so", code == 404 and body["ok"] is False, (code, body))
    httpd.shutdown()

    sent = {}

    class Fake:
        client_address = ("172.18.0.9", 5555)
        path = "/api/pause"

        def _json(self, code, obj):
            sent.update(code=code, obj=obj)
    server.Handler.do_POST(Fake())
    check("a write from anywhere but loopback is refused, and says how", sent.get("code") == 403 and
          "bbox ci-runner pause" in sent["obj"]["error"] and not (state / "paused").exists(), sent)

# the follower's corners, on a volume of their own
record.KEEP, record.TRIM_AT = 2000, 4000
with tempfile.TemporaryDirectory() as d:
    state = Path(d)
    jobs = state / "jobs.jsonl"
    now = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
    record.append(record.line("started", "0", "x", env=ENV, now=now), path=str(jobs))     # run 42 began earlier
    follower = server.Follower(state)
    ref = dict(ENV, GITHUB_RUN_ID="43")
    record.append(record.line("refused", "2700", "x", env=ref, now=now), path=str(jobs))
    record.append(record.line("ended", "0", "x", env=ref, now=now), path=str(jobs))
    ev = follower.events()
    check("a refused job is one red bar, and the completed hook's end after it carries no span",
          [e[0] for e in ev] == ["job.failed", "job.ended"] and ev[0][2].get("span") == "43.1.gates"
          and "span" not in ev[1][2], ev)
    record.append(record.line("ended", "0", "x", env=ENV, now=now), path=str(jobs))
    ev = follower.events()
    check("an end whose start came before the server: one bar, t0 read off the file",
          len(ev) == 1 and ev[0][2].get("span") == "42.1.gates" and ev[0][2].get("t0") == int(now.timestamp() * 1000), ev)
    # a server that has read nothing since it started, and a trim: it goes on after the line it started at
    fresh = server.Follower(state)
    record.KEEP, record.TRIM_AT = 3, 5
    record.append(record.line("waiting", "0", "x", env=dict(ENV, GITHUB_RUN_ID="88"), now=now), path=str(jobs))
    record.append(record.line("waiting", "0", "x", env=dict(ENV, GITHUB_RUN_ID="89"), now=now), path=str(jobs))
    ev = fresh.events()
    check("a trim before the server read anything: exactly the lines written since it started",
          [e[2]["run_id"] for e in ev] == ["88", "89"], ev)

# the door's arithmetic: the class from classes.yaml, the figure from the office's thresholds file — on a machine
# with /proc, as the agent is (a Mac has none: said, not faked)
if not Path("/proc/meminfo").exists():
    print("skip the door's cases: no /proc/meminfo here (they run on Linux, where the agent runs)")
else:
    with tempfile.TemporaryDirectory() as d:
        th = Path(d) / "admission-thresholds.sh"
        th.write_text(': "${ADMISSION_MIN_AVAIL_MIB:=1536}"\n: "${ADMISSION_STACK_MIN_AVAIL_GB:=6}"\n')
        # NEVER the office's real slot: this test runs as a step of a gates job ON this runner (G72), whose agent has
        # /opt/dgo/heavy-hold.sh — a holder path that does not exist keeps the door's own cases off the slot, and the
        # hooks run as the runner runs them, `bash -e` (the second reader measured both)
        base = dict(os.environ, CI_RUNNER_THRESHOLDS=str(th), CI_RUNNER_STATE=d, CI_WAITFREE_TIMEOUT="0",
                    CI_MIN_UPTIME_S="0", CI_MAX_START_C="1000", CI_RUNNER_HOLD=str(Path(d) / "no-holder-here.sh"),
                    CI_RUNNER_LOCKS=str(Path(d) / "no-locks"), CI_RUNNER_HOLD_PIDFILE=str(Path(d) / "no.pid"),
                    # under a REAL runner this test is a descendant of the job's worker: name one no process has
                    CI_RUNNER_WORKER_COMM="no-such-worker")
        for k in ("CI_WAITFREE_GB", "HEAVY_LOCKS", "HEAVY_HOLD_PIDFILE", "HEAVY_HOLD_WHILE", "HEAVY_DESK",
                  "HEAVY_HOLD_MAX_S", "CI_RUNNER_SLOT"):
            base.pop(k, None)
        hook = ["bash", "-e"]
        for wf, want in (("go-test", "need 2 GB, class light"), ("gates-hosted", "need 2 GB, class light"),
                         ("android-app", "need 6 GB, class stack")):
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=dict(base, GITHUB_WORKFLOW=wf),
                                 capture_output=True, text=True)
            check(f"{wf}: its class and the office's figure, in the door's own words", want in got.stdout + got.stderr,
                  got.stdout + got.stderr)
        got = subprocess.run([*hook, str(APP / "prejob.sh")], env=dict(base, GITHUB_WORKFLOW="go-test",
                                                                         CI_WAITFREE_GB="100000"),
                             capture_output=True, text=True)
        check("a job the machine cannot take is refused at the door, and says why", got.returncode == 1 and
              "never freed up" in got.stderr, got.stderr)
        # the completed hook runs with the JOB's PATH: after actions/setup-python its first `python3` is the tool
        # cache's, which exits 127 without the steps' LD_LIBRARY_PATH — on the Dell no job's end was recorded
        job_path = Path(d) / "job-path"
        job_path.mkdir()
        (job_path / "python3").write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        (job_path / "python3").chmod(0o755)
        jobs = Path(d) / "jobs.jsonl"
        before = len(jobs.read_text(encoding="utf-8").splitlines()) if jobs.exists() else 0
        # the interpreter the hook must use is named (the image's own in the agent; this test's here, so a Mac's
        # /usr/bin/python3 shim or a CI_RUNNER_PYTHON from outside never decides it)
        got = subprocess.run([*hook, str(APP / "postjob.sh")], capture_output=True, text=True, timeout=30,
                             env=dict(base, PATH=f"{job_path}:{base['PATH']}", CI_RUNNER_PYTHON=sys.executable))
        lines = jobs.read_text(encoding="utf-8").splitlines() if jobs.exists() else []
        last = json.loads(lines[-1]) if lines else {}
        check("a job's end is recorded although the job left a broken python3 first on PATH (setup-python's)",
              got.returncode == 0 and len(lines) == before + 1 and last.get("kind") == "ended",
              (got.stderr, before, len(lines), last))

        # the office's heavy-job slot (scripts/ops/heavy-hold.sh, DGO-1797 package 6): a job takes it at its start
        # and gives it back at its end; one another job holds refuses it at the door, and says by whom
        import shutil
        if not (shutil.which("flock") and shutil.which("setsid")):
            print("skip the slot's cases: no flock or setsid here (the agent's image has both)")
        else:
            hh = APP.parents[1] / "scripts" / "ops" / "heavy-hold.sh"
            locks = Path(d) / "locks"
            slot = dict(base, CI_RUNNER_HOLD=str(hh), CI_RUNNER_LOCKS=str(locks), CI_RUNNER_HOLD_MAX_S="60",
                        CI_RUNNER_HOLD_PIDFILE=str(Path(d) / "agent.pid"), GITHUB_WORKFLOW="go-test",
                        GITHUB_SHA="57ef8904b9901632", GITHUB_RUN_ID="7", CI_RUNNER_SLOT="on",
                        CI_RUNNER_READY=str(APP.parents[1] / "scripts" / "ops" / "heavy-ready.sh"))
            mine = dict(slot, HEAVY_LOCKS=str(locks))            # what a person's own `status` asks with

            def status():
                return subprocess.run(["bash", str(hh), "status"], env=mine, capture_output=True,
                                      text=True, timeout=30).stdout.strip()
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=slot, capture_output=True, text=True,
                                 timeout=60)
            check("a job takes the office's heavy-job slot at its start, and it stays held after the hook exits",
                  got.returncode == 0 and "holding the heavy-job slot" in got.stdout
                  and status().startswith("ci go-test · 57ef8904b · run 7 | pid "), (got.stdout + got.stderr, status()))
            check("…and says when it could not find the job's worker (the holder's bound is its only end then)",
                  "the job's worker was not found: held at most 60 s" in got.stdout, got.stdout)
            rec = locks / "heavy.would"
            line = rec.read_text(encoding="utf-8").splitlines()[-1].split("\t") if rec.exists() else []
            import stat as _stat
            check("…and leaves one line of the office's readiness record, in heavy_admit's own format, the file "
                  "world-writable (a root container must never lock the office's user out of it)",
                  len(line) == 3 and line[1] == "ci go-test · run 7" and line[2] != ""
                  and _stat.S_IMODE(rec.stat().st_mode) == 0o666, (line, oct(rec.stat().st_mode) if rec.exists() else 0))
            subprocess.run([*hook, str(APP / "postjob.sh")], env=slot, capture_output=True, text=True, timeout=30)
            last = json.loads((Path(d) / "jobs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            check("its end gives the slot back, and the record says so",
                  status() == "free" and last["kind"] == "ended" and "given back" in last["machine"], (status(), last))
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=dict(slot, GITHUB_WORKFLOW="go\ttest\nnext",
                                                                             CI_WAITFREE_GB="1"),
                                 capture_output=True, text=True, timeout=60)
            lines = rec.read_text(encoding="utf-8").splitlines()
            check("…one line with three fields whatever the workflow's name holds (a tab, a newline)",
                  len(lines[-1].split("\t")) == 3 and "next" in lines[-1], (lines[-2:], got.stdout[-200:]))
            subprocess.run([*hook, str(APP / "postjob.sh")], env=slot, capture_output=True, text=True, timeout=30)
            other = dict(mine, HEAVY_HOLD_PIDFILE=str(Path(d) / "other.pid"))
            subprocess.run(["bash", str(hh), "start", "bbox run apitools", "5"], env=other, capture_output=True,
                           timeout=30)
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=dict(slot, CI_WAITFREE_TIMEOUT="2"),
                                 capture_output=True, text=True, timeout=60)
            refused = json.loads((Path(d) / "jobs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            check("a slot another job holds refuses the job at the door — under `bash -e` too — and names the holder",
                  got.returncode == 1 and "heavy-job slot never freed" in got.stderr
                  and "bbox run apitools" in got.stderr and refused["kind"] == "refused", (got.stdout + got.stderr,
                                                                                          refused))
            subprocess.run(["bash", str(hh), "stop"], env=other, capture_output=True, timeout=30)
            check("…and the door that refused holds nothing", status() == "free", status())
            nosha = {k: v for k, v in slot.items() if k != "GITHUB_SHA"}
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=nosha, capture_output=True, text=True,
                                 timeout=60)
            subprocess.run([*hook, str(APP / "postjob.sh")], env=slot, capture_output=True, text=True, timeout=30)
            check("a job with no GITHUB_SHA still passes the door (set -u)", got.returncode == 0, got.stderr)

            # the hook gate: only the runner's own hook (its parent is the job's worker) touches the slot
            import shutil as _sh
            import time as _t
            worker = Path(d) / "ci-test-worker"                 # a stand-in worker: bash under that name
            _sh.copy(_sh.which("bash"), worker)
            hooked = {k: v for k, v in slot.items() if k != "CI_RUNNER_SLOT"}
            hooked["CI_RUNNER_WORKER_COMM"] = "ci-test-worker"
            got = subprocess.run([str(worker), "-c", f"bash -e {APP / 'prejob.sh'}; sleep 2"], env=hooked,
                                 capture_output=True, text=True, timeout=60)
            check("started by the job's worker: the slot is taken, and the holder ends with that worker",
                  "holding the heavy-job slot" in got.stdout and "was not found" not in got.stdout, got.stdout)
            end = _t.time() + 15
            while status() != "free" and _t.time() < end:
                _t.sleep(0.5)
            check("…free within seconds of the worker's end, no end hook needed", status() == "free", status())
            mine_job = dict(mine, HEAVY_HOLD_PIDFILE=str(Path(d) / "agent.pid"))
            subprocess.run(["bash", str(hh), "start", "the running job", "5"], env=mine_job, capture_output=True,
                           timeout=30)
            got = subprocess.run([*hook, str(APP / "postjob.sh")], env=hooked, capture_output=True, text=True,
                                 timeout=30)
            check("a step that runs postjob.sh by hand never frees the running job's slot",
                  status().startswith("the running job | pid "), status())
            got = subprocess.run([*hook, str(APP / "prejob.sh")], env=hooked, capture_output=True, text=True,
                                 timeout=60)
            check("…nor does one that runs prejob.sh by hand take or end it — and it says so",
                  "not started by the runner" in got.stdout and status().startswith("the running job | pid "),
                  (got.stdout, status()))
            subprocess.run(["bash", str(hh), "stop"], env=mine_job, capture_output=True, timeout=30)

print("ci-runner: " + ("PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
