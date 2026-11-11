"""test_door.py — the job door (door.py + server.py's routes): who may ask, what may be asked, and how a job runs
(DGO-1797, package 9). On a temporary volume and a stand-in checkout whose `bbox` is a script; no network.

    python3 apps/ci-runner/tests/test_door.py

The worker's cases need a POSIX process group (Linux or a Mac); the routes are asked over real HTTP on loopback,
with real signatures made by the platform's one verifier (platform-base/connections/link_identity.py).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
TMP = tempfile.mkdtemp(prefix="door-")
os.environ.update(CI_RUNNER_STATE=TMP, CI_RUNNER_ACCEPT_FROM="macbook,vps1", CONNECTIONS_URL="http://127.0.0.1:9")
os.environ["CI_SECRET_PLANTED"] = "never-in-a-job"         # what a job's process must never see
sys.path.insert(0, str(ROOT / "platform-base" / "connections"))
sys.path.insert(0, str(APP))
import door              # noqa: E402
import link_identity as L  # noqa: E402
import server            # noqa: E402

STATE = Path(TMP)
SECRETS = {"macbook": "s-mac-0123456789abcdef", "vps1": "s-vps-0123456789abcdef"}
server._secrets = L.Secrets(lambda office: SECRETS.get(office, ""))
fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


def signed(office, user="owner", secret=None, ts=None):
    ts = int(time.time()) if ts is None else ts
    sec = SECRETS.get(office, "x") if secret is None else secret
    return {"x-dgo-office": office, "x-dgo-identity": f"v1 {office} {user} {ts} {L.signature(sec, office, user, ts)}"}


# ── what may be asked: the allow-list, word by word ───────────────────────────────────────────────────────────────
v = door.validate
check("an exact verb of the list is a job", v({"name": "bbox", "args": {"verb": ["dgo", "link", "status"]}})[0]
      == ["dgo", "link", "status"])
check("a {ref} placeholder takes a work item's id", v({"name": "bbox", "args": {"verb": ["project-pln", "tasks", "show",
                                                                                       "DGO-1797"]}})[0] is not None)
for name, body in [
    ("a job that is not named", {"name": "shell", "args": {"verb": ["status"]}}),
    ("a verb off the list", {"name": "bbox", "args": {"verb": ["run"]}}),
    ("a word added to a listed verb", {"name": "bbox", "args": {"verb": ["status", "--fix"]}}),
    ("a placeholder's value with a shell in it", {"name": "bbox", "args": {"verb": ["project-pln", "tasks", "show",
                                                                                  "DGO-1; rm -rf /"]}}),
    ("a placeholder's value of another shape", {"name": "bbox", "args": {"verb": ["project-pln", "tasks", "show",
                                                                                "--help"]}}),
    ("a verb that is a string, not words", {"name": "bbox", "args": {"verb": "status"}}),
    ("an empty verb", {"name": "bbox", "args": {"verb": []}}),
    ("a body that is not an object", ["bbox"]),
]:
    argv, why = v(body)
    check(f"refused: {name}, and says why", argv is None and bool(why), why)
check("an unknown job's refusal names the jobs there are", "bbox" in v({"name": "x"})[1], v({"name": "x"})[1])

# ── the queue: per office, bounded, and another office's job does not exist for it ─────────────────────────────────
got, _ = door.enqueue(STATE, "bbox", ["status"], "macbook", "owner")
jid = got["id"]
check("a job is queued with an id", door.ID_RE.match(jid) is not None, got)
check("the office that asked sees it", door.find(STATE, jid, "macbook")[0]["state"] == "queued")
check("the local CLI sees it", door.find(STATE, jid, door.LOCAL)[0] is not None)
check("another office is told it does not exist", door.find(STATE, jid, "vps1") == (None, "no such job"))
check("an id that is a path is no job", door.find(STATE, "../../etc/passwd", "local")[0] is None)
for _ in range(door.QUEUE_PER_OFFICE - 1):
    door.enqueue(STATE, "bbox", ["status"], "macbook", "owner")
check("one office cannot queue more than its share", door.enqueue(STATE, "bbox", ["status"], "macbook", "o")[0] is None)
check("…while another office still can", door.enqueue(STATE, "bbox", ["status"], "vps1", "o")[0] is not None)
check("another office cannot cancel it", door.cancel(STATE, jid, "vps1")[0] is None)
check("the office that asked can, while it waits", door.cancel(STATE, jid, "macbook")[0] == {"id": jid,
                                                                                              "state": "cancelled"})
check("…and it is cancelled, not queued", door.find(STATE, jid, "macbook")[0]["state"] == "cancelled")
check("a job no longer waiting cannot be cancelled, and says so", "only a job that still waits" in
      door.cancel(STATE, jid, "macbook")[1])
for p in (STATE / "door" / "queue").glob("*.json"):                       # a clean queue for the worker's cases
    p.unlink()

# ── the worker: the checkout's bbox, its own process group, its timeout, a clean environment, a bounded log ───────
repo = Path(tempfile.mkdtemp(prefix="door-repo-"))
(repo / "bbox").write_text("#!/usr/bin/env bash\n"
                           "echo \"args: $*\"\n"
                           "env | grep -c CI_SECRET_PLANTED | sed 's/^/planted: /'\n"
                           "echo \"heavy: ${BBOX_HEAVY:-}\"\n"
                           "echo \"via: ${BBOX_VIA:-}\"\n"
                           "case \"$1\" in\n"
                           "  status) exit 0 ;;\n"
                           "  computers) exit 3 ;;\n"
                           "  ci-runner) (sleep 30 & echo $! > \"$PWD/child.pid\"; wait) ; exit 0 ;;\n"
                           "  dgo) head -c 5000 /dev/zero | tr '\\0' 'z'; exit 0 ;;\n"
                           "esac\n")
os.chmod(repo / "bbox", 0o755)


def ask_and_run(argv, office="macbook", jobs=None):
    got, why = door.enqueue(STATE, "bbox", argv, office, "owner")
    job = door.claim(STATE)
    return got["id"], door.run(STATE, job, str(repo), path=jobs)


jid, out = ask_and_run(["status"])
log = (STATE / "door" / "jobs" / jid / "log").read_text()
check("a job runs the checkout's bbox with its words, and ends done/0", out["state"] == "done" and out["exit"] == 0
      and "args: status" in log, (out, log))
check("…in an environment with nothing of the worker's own (a planted secret is not there)", "planted: 0" in log, log)
check("…and as light work: no heavy-job slot asked (BBOX_HEAVY=off)", "heavy: off" in log, log)
check("…and as a hop from another office: it never goes on to a second (BBOX_VIA=1)", "via: 1" in log, log)
door.LOG_PAGE = 5
hebrew = "שלום עולם — ok\n".encode("utf-8")
(STATE / "door" / "jobs" / jid / "log").write_bytes(hebrew)
got_back, off = b"", 0
for _ in range(50):
    page = door.log_page(STATE, jid, off)
    if not page:
        break
    page.decode("utf-8")                                  # every page is whole characters, or this raises
    got_back, off = got_back + page, off + len(page)
door.LOG_PAGE = 64 << 10
check("a log read in pages comes back whole, each page ending on a whole character (Hebrew across a cut)",
      got_back == hebrew, got_back)
rec = [json.loads(x) for x in (STATE / "jobs.jsonl").read_text().splitlines()]
check("the job is one bar on «כל מקביל»: a started and an ended record, named as the door's",
      [r["kind"] for r in rec[-2:]] == ["started", "ended"] and rec[-1]["workflow"] == "door · bbox"
      and rec[-1]["actor"] == "owner@macbook", rec[-2:])
jid, out = ask_and_run(["computers", "herd"])
check("a job that fails ends failed, with its own exit", out == {**out, "state": "failed", "exit": 3}, out)
short = Path(TMP) / "jobs-short.json"
short.write_text(json.dumps({"jobs": {"bbox": {"class": "light", "timeout_s": 1,
                                               "verbs": [["ci-runner", "status"]], "args": {}}}}))
t0 = time.time()
jid, out = ask_and_run(["ci-runner", "status"], jobs=short)
pid = int((repo / "child.pid").read_text().strip())
time.sleep(0.3)
alive = True
try:
    os.kill(pid, 0)
except OSError:
    alive = False
check("a job past its timeout ends «timeout», exit 124, within seconds", out["state"] == "timeout"
      and out["exit"] == 124 and time.time() - t0 < 10, out)
check("…and its whole process group is gone (a child it started too)", not alive, pid)
check("…and its log says why it stopped", "the job's timeout" in (STATE / "door" / "jobs" / jid / "log").read_text())
door.LOG_MAX = 1000
jid, out = ask_and_run(["dgo", "link", "status"])
size = (STATE / "door" / "jobs" / jid / "log").stat().st_size
check("a job's log is bounded, and says it was cut", size < 1200 and "the log was cut" in
      (STATE / "door" / "jobs" / jid / "log").read_text(), size)
door.LOG_MAX = 1 << 20
check("one job, one claim: nothing is left to claim twice", door.claim(STATE) is None)
door.KEEP_JOBS = 2
door.prune(STATE)
check("finished jobs are pruned to the newest KEEP_JOBS",
      sum(1 for d in (STATE / "door" / "jobs").iterdir() if d.is_dir()) <= 3)
door.KEEP_JOBS = 100

# ── who may ask, over real HTTP: the CLI, or a signed office this office lists ─────────────────────────────────────
srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


ASK = {"name": "bbox", "args": {"verb": ["status"]}}
code, body, _ = call("GET", "/api/door/names")
check("the names are open to read (a caller decides from them)", code == 200 and "bbox" in body["data"], body)
code, body, _ = call("POST", "/api/door/jobs", ASK)
check("the app's own CLI (loopback, no office) may ask", code == 202 and body["data"]["state"] == "queued", body)
code, body, _ = call("POST", "/api/door/jobs", ASK, {"x-dgo-office": "macbook"})
check("an office named with no signature is refused (an address is not enough here)", code == 403
      and "unsigned" in body["error"], body)
code, body, _ = call("POST", "/api/door/jobs", ASK, signed("macbook", secret="not-the-pair-secret"))
check("a signature made with another secret is refused", code == 403 and "bad-mac" in body["error"], body)
code, body, _ = call("POST", "/api/door/jobs", ASK, signed("macbook", ts=int(time.time()) - 3600))
check("an old signature is refused", code == 403 and "stale" in body["error"], body)
SECRETS["hp-laptop"] = "s-hp-0123456789abcdef"
code, body, _ = call("POST", "/api/door/jobs", ASK, signed("hp-laptop"))
check("a signed office this office does not list is refused, and told where the list is", code == 403
      and "CI_RUNNER_ACCEPT_FROM" in body["error"], body)
code, body, _ = call("POST", "/api/door/jobs", {"name": "bbox", "args": {"verb": ["run"]}}, signed("macbook"))
check("a listed, signed office asking off the list: 400 with the names", code == 400 and body.get("names") == ["bbox"],
      body)
code, body, _ = call("POST", "/api/door/jobs", ASK, signed("macbook", user="owner"))
check("a listed, signed office asking a listed job: 202, queued", code == 202, body)
mine = body["data"]["id"]
code, body, _ = call("GET", f"/api/door/jobs/{mine}", headers=signed("vps1"))
check("another listed office is told the job does not exist", code == 404, body)
code, body, _ = call("GET", f"/api/door/jobs/{mine}", headers=signed("macbook"))
check("the office that asked reads its job, with who asked", code == 200 and body["data"]["user"] == "owner", body)
while door.claim(STATE) is not None:          # the CLI's job first, then this one: the worker takes the oldest
    pass
for p in (STATE / "door" / "jobs").iterdir():
    j = door._read(p / "job.json")
    if j.get("id") == mine:
        door.run(STATE, j, str(repo))
code, page, hdrs = call("GET", f"/api/door/jobs/{mine}/log?offset=0", headers=signed("macbook"))
check("its log, with the job's state, exit and the next offset in the headers", code == 200
      and b"args: status" in page and hdrs["X-Door-State"] == "done" and hdrs["X-Door-Exit"] == "0"
      and int(hdrs["X-Door-Next"]) == len(page), (code, page[:80], dict(hdrs)))
code, page, hdrs = call("GET", f"/api/door/jobs/{mine}/log?offset={len(page)}", headers=signed("macbook"))
check("…and from the next offset, nothing more once it ended", code == 200 and page == b"", page)
code, body, _ = call("DELETE", f"/api/door/jobs/{mine}", headers=signed("macbook"))
check("a job that ran cannot be cancelled: 409, said", code == 409, body)
claimed_not_run = [p.name for p in (STATE / "door" / "jobs").iterdir()
                   if p.is_dir() and not (p / "state.json").exists()]
settled = door.recover(STATE)
check("a worker that starts again settles the jobs it had claimed and not finished: failed, said in the log",
      settled == len(claimed_not_run) >= 1 and all(door._read(STATE / "door" / "jobs" / n / "state.json")["state"]
                                                   == "failed" for n in claimed_not_run), (settled, claimed_not_run))
# the app's own CLI (`./bbox ci-runner door …`) against this server, with the worker running beside it
import contextlib  # noqa: E402
import io  # noqa: E402

import cli  # noqa: E402
cli.BASE = BASE
worker = threading.Thread(target=door.work, args=(STATE, str(repo)), kwargs={"tick": 0.2}, daemon=True)
worker.start()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = cli.main(["door"])
check("`ci-runner door` lists the named verbs", rc == 0 and "project-pln tasks show {ref}" in buf.getvalue(),
      buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = cli.main(["door", "status"])
check("`ci-runner door status` runs it through the door: its log, and exit 0", rc == 0
      and "args: status" in buf.getvalue(), (rc, buf.getvalue()))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rc = cli.main(["door", "computers", "herd"])
check("…a job that fails exits 1 and says how it ended", rc == 1 and "failed" in err.getvalue(), (rc, err.getvalue()))
with contextlib.redirect_stderr(io.StringIO()):
    rc = cli.main(["door", "run"])
check("…a verb off the list exits 1", rc == 1, rc)

who, code, why = server.door_caller("172.18.0.9", {})
check("a request with no office from anywhere but loopback is refused", who is None and code == 403, why)
saved, server.linkid = server.linkid, None
who, code, why = server.door_caller("127.0.0.1", signed("macbook"))
server.linkid = saved
check("no verifier mounted: an office is never asked to be trusted (503, said)", who is None and code == 503, why)
srv.shutdown()

# ── the second reader's points, each a case ───────────────────────────────────────────────────────────────────────
for p in (STATE / "door" / "queue").glob("*.json"):
    p.unlink()
q = STATE / "door" / "queue"
door._write(q / "1762800000-deadbeef.json", {"id": "1762800000-deadbeef", "name": "bbox", "argv": ["engine", "shell",
            "id"], "office": "macbook", "user": "x", "at": "x"})
forged = door.claim(STATE)
out = door.run(STATE, forged, str(repo))
flog = (STATE / "door" / "jobs" / "1762800000-deadbeef" / "log").read_text()
check("a queue file that never passed the server's check runs nothing — the worker refuses it by its own list",
      out["state"] == "failed" and "refused by the worker" in flog and "args:" not in flog, (out, flog))
cli_job, _ = door.enqueue(STATE, "bbox", ["status"], door.LOCAL, "cli")
check("the CLI is «@local», a name no office id can be: an office called «local» sees none of its jobs",
      door.find(STATE, cli_job["id"], "local")[0] is None and door.find(STATE, cli_job["id"], door.LOCAL)[0] is not None)
check("a job name that is not a string is refused, never an exception", v({"name": ["bbox"]})[0] is None)
check("an offset past any file is an empty page, never an error", door.log_page(STATE, cli_job["id"], 10 ** 30) == b"")
for p in (STATE / "door" / "queue").glob("*.json"):
    p.unlink()
burst = [threading.Thread(target=door.enqueue, args=(STATE, "bbox", ["status"], "burst", "x")) for _ in range(30)]
[t.start() for t in burst]
[t.join() for t in burst]
n = sum(1 for p in (STATE / "door" / "queue").glob("*.json") if door._read(p).get("office") == "burst")
check("30 asks at once still keep one office to its share of the queue", n == door.QUEUE_PER_OFFICE, n)
asked_vault = []
saved = server._secrets
server._secrets = L.Secrets(lambda office: asked_vault.append(office) or SECRETS.get(office, ""))
who, code, why = server.door_caller("127.0.0.1", {"x-dgo-office": "macbook", "x-dgo-identity": "not a signature"})
check("a malformed claim is refused before the vault is asked", who is None and code == 403 and asked_vault == [],
      (code, asked_vault))
server._secrets = saved
check("a job's environment names the engine's socket, so bbox never starts an engine of its own",
      door._env("/x")["BBOX_DOCKER_SOCK"] == "/var/run/docker.sock")
check("…and names the engine itself (BBOX_DOCKER_HOST), so bbox never probes it and falls back — even when busy",
      door._env("/x").get("BBOX_DOCKER_HOST") == "unix:///var/run/docker.sock")
# the reader's test gaps, each a case
check("a job id is anchored at both ends: a longer string around a real id is no job",
      door.find(STATE, "x" + cli_job["id"] + "x", door.LOCAL)[0] is None)
(q / "not-a-request.json").write_text(json.dumps({"id": cli_job["id"], "name": "bbox", "argv": ["status"]}))
for p in list(q.glob("*.json")):
    if p.name != "not-a-request.json":
        p.unlink()
check("a queue file whose name is not its id's is removed, never claimed",
      door.claim(STATE) is None and not (q / "not-a-request.json").exists())
logged, _ = door.enqueue(STATE, "bbox", ["status"], "macbook", "x")
(STATE / "door" / "jobs" / logged["id"]).mkdir(parents=True, exist_ok=True)
(STATE / "door" / "jobs" / logged["id"] / "log").write_bytes(b"some log\n")
check("a huge offset on a log that EXISTS is an empty page, never an error",
      door.log_page(STATE, logged["id"], 10 ** 30) == b"")
door.KEEP_JOBS = 2
for _ in range(6):
    got, _ = door.enqueue(STATE, "bbox", ["status"], "pruner", "x")
    door.cancel(STATE, got["id"], "pruner")
done_dirs = [d for d in (STATE / "door" / "jobs").iterdir()
             if d.is_dir() and door._read(d / "state.json").get("state") in door.DONE]
door.KEEP_JOBS = 100
check("cancelling prunes: finished jobs stay at the newest KEEP_JOBS", len(done_dirs) <= 2, len(done_dirs))

print("job door: " + ("PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
