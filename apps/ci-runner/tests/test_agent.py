"""test_agent.py — ci-runner's supervisor (agent.sh) against a stand-in for GitHub's run.sh, on Linux (DGO-1797).

    python3 apps/ci-runner/tests/test_agent.py

The stand-in is what matters about the real one: run.sh starts a child named Runner.Listener and waits for it, so a
signal to run.sh alone would leave the listener running. A job is a process named Runner.Worker. The agent runs with a
one-second tick. It needs setsid, pgrep and jq — the agent's own image has them; a machine without them says NOT RUN.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
need = [t for t in ("setsid", "pgrep", "jq") if not shutil.which(t)]
if need or not Path("/proc").is_dir():
    print(f"NOT RUN needs {', '.join(need) or '/proc'} (Linux, as in the agent's image)")
    sys.exit(1)

fails = 0
MARK = uuid.uuid4().hex[:8]                                   # this run's processes, and nobody else's


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


def procs(name):
    out = subprocess.run(["pgrep", "-f", f"{name}-{MARK}"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out]


def beat(state):
    try:
        return json.loads((state / "agent.json").read_text())
    except (OSError, ValueError):
        return {}


def until(pred, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return pred()


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    state, work, runner = d / "state", d / "work", d / "runner"
    for p in (state, work, runner):
        p.mkdir()
    # like the real one: run.sh dies at once on a signal, its Runner.Listener takes seconds to cancel and close
    (runner / "listener.sh").write_text(
        "#!/usr/bin/env bash\n"
        "trap 'sleep 3; exit 0' TERM\n"
        "while :; do sleep 0.2 & wait $!; done\n")
    (runner / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        f"bash -c 'exec -a Runner.Listener-{MARK} bash {runner}/listener.sh' &\n"
        "wait\n")
    (runner / "run.sh").chmod(0o755)
    # the agent's job test is `pgrep -f Runner.Worker`; here it matches THIS run's stand-in only — on a host that is
    # itself a runner (the Dell's gates) the real Runner.Worker running this test read as a job, and no pause came
    env = dict(os.environ, CI_RUNNER_STATE=str(state), CI_RUNNER_WORK=str(work), CI_RUNNER_HOME=str(runner),
               CI_RUNNER_TICK="1", PATH=os.environ["PATH"], CI_RUNNER_JOB_MATCH=f"Runner.Worker-{MARK}")
    # …so production's own match, which the run above never takes, is held here as text: a typo in it would let a
    # pause stop a running job (the second reader)
    check("production's job match is Runner.Worker",
          '"${CI_RUNNER_JOB_MATCH:-Runner.Worker}"' in (APP / "agent.sh").read_text())
    agent = subprocess.Popen(["bash", str(APP / "agent.sh")], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
    try:
        check("no registration: it says so, and runs nothing",
              until(lambda: beat(state).get("state") == "unregistered") and not procs("Runner.Listener"), beat(state))

        reg = state / "registration"
        (reg / ".runner").write_text(json.dumps({"agentName": "test-runner", "workFolder": "_work"}))
        (reg / ".credentials").write_text("{}")
        check("a registration placed later is taken without a restart",
              until(lambda: beat(state).get("state") == "running" and procs("Runner.Listener")), beat(state))
        check("…its work folder pointed at the host path",
              json.loads((runner / ".runner").read_text())["workFolder"] == str(work))

        (state / "paused").write_text("x")
        check("paused with no job: the listener's whole group is stopped — Runner.Listener too, not only run.sh",
              until(lambda: beat(state).get("state") == "paused" and not procs("Runner.Listener")), beat(state))
        os.unlink(state / "paused")
        check("resumed: the listener starts again",
              until(lambda: beat(state).get("state") == "running" and procs("Runner.Listener")), beat(state))

        job = subprocess.Popen(["bash", "-c", f"exec -a Runner.Worker-{MARK} sleep 1000"])
        time.sleep(0.5)
        (state / "paused").write_text("x")
        check("paused during a job: «pausing», and the listener keeps running for it",
              until(lambda: beat(state).get("state") == "pausing", 5) and procs("Runner.Listener"), beat(state))
        job.terminate(); job.wait()
        check("…the job ends: stopped between jobs",
              until(lambda: beat(state).get("state") == "paused" and not procs("Runner.Listener")), beat(state))
        os.unlink(state / "paused")
        until(lambda: beat(state).get("state") == "running" and procs("Runner.Listener"))

        # TERM with a listener working and a job running: the agent waits for the listener's GROUP to finish (the
        # stand-in lingers 3 s, as the real one cancels its job and closes its session), then ends — nothing left
        job = subprocess.Popen(["bash", "-c", f"exec -a Runner.Worker-{MARK} sleep 1000"])
        t0 = time.time()
        agent.send_signal(signal.SIGTERM)
        agent.wait(timeout=60)
        took = time.time() - t0
        job.terminate(); job.wait()
        check("TERM mid-job: it waits for the listener to finish (≈3 s), then leaves no listener behind",
              agent.returncode == 0 and took >= 2.5 and not procs("Runner.Listener"), (agent.returncode, round(took, 1)))

        # a listener that dies at once, three times: «failing», and the heartbeat goes on through the back-off
        (runner / "run.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
        agent = subprocess.Popen(["bash", str(APP / "agent.sh")], env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
        check("three quick ends in a row: «failing»", until(lambda: beat(state).get("state") == "failing", 20),
              beat(state))
        first = beat(state).get("at")
        check("…and the heartbeat goes on during the back-off", until(lambda: beat(state).get("at") != first, 15),
              beat(state))
        agent.send_signal(signal.SIGTERM)
        agent.wait(timeout=30)
        check("TERM in the back-off ends it at once", agent.returncode == 0, agent.returncode)

        # the job door's worker (door.py): started by the supervisor, started again when it ends, and said to be —
        # registered or not, paused or not (a stand-in worker that writes a line and ends)
        marks = d / "door-starts"
        stub = d / "door-stub.py"
        stub.write_text(f"import os, time\nopen({str(marks)!r}, 'a').write(os.environ.get('CI_RUNNER_DOOR_REPO', '-')"
                        f" + '\\n')\ntime.sleep(0.5)\n")
        listener_env = d / "listener-env"
        (runner / "run.sh").write_text(f"#!/usr/bin/env bash\nenv > {listener_env}\nexit 1\n")
        agent = subprocess.Popen(["bash", str(APP / "agent.sh")], env=dict(env, CI_RUNNER_DOOR=str(stub),
                                                                          CI_RUNNER_DOOR_REPO="/office-here"),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        starts = lambda: len(marks.read_text().splitlines()) if marks.exists() else 0   # noqa: E731
        check("the job door's worker is started, and started again when it ends", until(lambda: starts() >= 2, 15),
              starts())
        agent.send_signal(signal.SIGTERM)
        out, _ = agent.communicate(timeout=30)
        check("…said each time it ended", "the job door's worker ended" in out, out[-400:])
        check("the worker is handed the checkout's path", marks.read_text().splitlines()[0] == "/office-here",
              marks.read_text()[:80])
        check("…and the listener — every job step — never inherits it",
              listener_env.exists() and "CI_RUNNER_DOOR_REPO" not in listener_env.read_text(),
              listener_env.exists())
    finally:
        if agent.poll() is None:
            agent.kill()
        for name in ("Runner.Listener", "Runner.Worker"):
            for p in procs(name):
                os.kill(p, signal.SIGKILL)

print("ci-runner agent: " + ("PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
