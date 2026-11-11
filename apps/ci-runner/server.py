"""ci-runner — «מריץ CI»: the office's GitHub Actions runner as an app the owner sees and switches (DGO-1797).

The owner, 2026-11-10: the Dell runs only the office, what runs in it and a browser; the runner and the emulator
are OFFICE apps «עם כל הסטנדארטים», and he sees what is on and what is not. This server is the app's screen, API
and CLI; the runner itself is the sibling container ci-runner-agent (agent.sh), and the two share one volume:

  <state>/agent.json      the agent's heartbeat, every 10 s: running | paused | pausing | unregistered | failing,
                          whether GitHub's listener is alive and a job runs; older than a minute = not running
  <state>/jobs.jsonl      one line per job event (waiting at the door, started, refused, ended — record.py)
  <state>/paused          present = the agent stops the listener BETWEEN jobs: the job running finishes, the next
                          ones stay queued on GitHub for another runner with the labels

Ops (`{"ok": true, "op": …, "data": …}`; capabilities[].required_ops):
  GET  /api/status        the agent's state, paused or not, the job running now, the last event, the labels
  GET  /api/jobs?n=20     the last n job events, newest first
  GET  /api/queue         every queued run of the repository, from GitHub with the office's token (cached 30 s)
  POST /api/pause         stop taking jobs (the running one finishes)  — from the app's own CLI only, for now
  POST /api/resume        take jobs again                               — the same
Who may write: the CLI inside this container (loopback). A person's write from the screen needs the office's
sign-in asked about the session (forward-auth's /whoami), which six apps each carry a copy of today; the seventh
copy is not written here — the screen shows the CLI line instead, and the one shared check is its own item.

The flow channel (`dgo:flow:ci-runner`, through the office's one publisher platform-base/redis/flowpub.py): this
server follows jobs.jsonl and puts each new line on the stream — job.waiting (an instant), job.started and
job.ended / job.failed as ONE bar (data.span, and t0 on the end) — and runner.paused / runner.resumed. The agent
holds no redis password: every job step inherits the runner's environment. Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import record

import door

sys.path.insert(0, "/opt/dgo")
try:
    import flowpub                                         # the office's ONE flow.v1 publisher
except ImportError:                                        # a test, or an office without it mounted
    flowpub = None
try:
    import link_identity as linkid                         # the platform's ONE verifier of the link's signature
except ImportError:                                        # not mounted: the job door then answers only the CLI
    linkid = None

STATE = Path(os.environ.get("CI_RUNNER_STATE", "/state"))
STATIC = Path(__file__).resolve().parent / "static"
PORT = int(os.environ.get("CI_RUNNER_PORT", "8988"))
REPO = os.environ.get("CI_RUNNER_REPO", "bina-solution/digital-office")
VAULT = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
TOKEN_INSTANCE = os.environ.get("CI_RUNNER_GITHUB_INSTANCE", "github-runner-token-local")
GITHUB_TTL = 30.0
STALE_S = 60
OPS = ["status", "jobs", "queue", "pause", "resume", "door_names", "door_ask", "door_job", "door_log", "door_cancel"]
#: the linked offices this office takes door jobs from (comma list in .env; empty = nobody — a decision per office)
ACCEPT_FROM = {o.strip().lower() for o in (os.environ.get("CI_RUNNER_ACCEPT_FROM") or "").split(",") if o.strip()}
LOOPBACK = ("127.0.0.1", "::1")
_gh = {"at": 0.0, "data": None}
_gh_lock = threading.Lock()


def _ms(iso: str) -> int:
    try:
        return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError):
        return int(time.time() * 1000)


def jobs(n: int = 20, state: Path | None = None) -> list[dict]:
    """The last n job events, newest first; a line that is not JSON is passed over (a write cut by a crash)."""
    state = STATE if state is None else state
    try:
        lines = (state / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
        if len(out) >= n:
            break
    return out


def heartbeat(state: Path | None = None, now: float | None = None) -> dict:
    """The agent's last word, and whether it is fresh: a heartbeat older than a minute is a container that does not
    run (stopped, disabled, crashed), whatever it last said."""
    state = STATE if state is None else state
    now = time.time() if now is None else now
    try:
        beat = json.loads((state / "agent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "unknown", "listener": False, "job": False, "fresh": False}
    fresh = now - _ms(beat.get("at", "")) / 1000 <= STALE_S
    return {**beat, "fresh": fresh} if fresh else {**beat, "state": "not-running", "listener": False, "job": False,
                                                   "fresh": False}


def running_now(events: list[dict], beat: dict) -> dict | None:
    """The job on the machine now: the newest `started` with no `ended` after it — and only while the agent says a
    job runs (a job cut by a crash or a cancel has no `ended`)."""
    if not beat.get("job"):
        return None
    ended = set()
    for rec in events:                                     # newest first
        if rec.get("kind") in ("ended", "refused"):
            ended.add(record.span_id(rec))
        elif rec.get("kind") == "started":
            return None if record.span_id(rec) in ended else rec
    return None


def status(state: Path | None = None) -> dict:
    state = STATE if state is None else state
    recent = jobs(200, state)
    beat = heartbeat(state)
    runner = (_gh["data"] or {}).get("runner") or {"labels": None, "why": "GitHub not asked yet"}
    if (_gh["data"] is None or time.time() - _gh["at"] >= GITHUB_TTL) and not _gh_lock.locked():
        threading.Thread(target=github, name="github-refresh", daemon=True).start()   # never waits on GitHub
    return {"agent": beat.get("state"), "listener": beat.get("listener"), "heartbeat": beat.get("at"),
            "paused": (state / "paused").exists(), "labels": runner.get("labels"),
            "labels_why": runner.get("why"), "warning": runner.get("warning"),
            "repository": REPO, "now": running_now(recent, beat), "last": recent[0] if recent else None,
            "flow": flowpub.stats() if flowpub else None}


def _token() -> str:
    """The office's GitHub token, from the vault, in memory only — never logged, never on a command line."""
    try:
        with urllib.request.urlopen(f"{VAULT}/api/instances/{TOKEN_INSTANCE}/secret", timeout=6) as r:
            sec = json.load(r)
    except (OSError, ValueError):
        return ""
    secret = sec.get("secret") if isinstance(sec, dict) else None
    return str((secret or {}).get("token") or "").strip() if isinstance(secret, dict) else ""


def _vault_json(path: str, params) -> tuple[int, dict]:
    """The vault's HTTP for link_identity.link_secret — injected, so the verifier names no service."""
    url = f"{VAULT}{path}" + (("?" + urlencode(params)) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}


_secrets = linkid.Secrets(lambda office: linkid.link_secret(_vault_json, office)) if linkid else None


def door_caller(client: str, headers) -> tuple[tuple[str, str] | None, int, str]:
    """Who asks the job door → ((office, user), 0, "") or (None, http code, why). The app's own CLI (loopback, no
    office named) is «local»; anyone else must be a linked office this office lists in CI_RUNNER_ACCEPT_FROM, whose
    request the link's door SIGNED. An address alone is never enough: this door runs things."""
    office = str(headers.get("x-dgo-office") or "").strip().lower()
    claim = str(headers.get("x-dgo-identity") or "")
    if not office and not claim.strip():
        if client in LOOPBACK:
            return (door.LOCAL, "cli"), 0, ""
        return None, 403, ("the job door answers a linked office's signed request, or this app's own CLI "
                           "(./bbox ci-runner …) — not a request with no office")
    if linkid is None:
        return None, 503, "the link's verifier is not mounted here (/opt/dgo/link_identity.py) — no office is asked"
    if office not in ACCEPT_FROM:
        return None, 403, (f"this office takes no jobs from {office[:40]!r} — CI_RUNNER_ACCEPT_FROM in its .env "
                           "names the offices it does")
    fields = linkid.parse(claim)
    if fields is None or fields[0] != office:             # unsigned, malformed or another office's: no vault call
        ok, kind, why = linkid.verify(claim, office=office, secret="")
        return None, 403, f"{why} ({kind})"
    ok, kind, why = linkid.verify(claim, office=office, secret=_secrets.get(office))
    if not ok:
        return None, 403, f"{why} ({kind})"
    return (office, linkid.parse(claim)[1]), 0, ""


def _agent_name(state: Path | None = None) -> str:
    try:
        return json.loads(((STATE if state is None else state) / "registration" / ".runner")
                          .read_text(encoding="utf-8-sig")).get("agentName") or ""
    except (OSError, ValueError):
        return ""


def github(now: float | None = None) -> dict:
    """What GitHub says, cached 30 s: every queued run of the repository, and THIS runner's labels as GitHub holds
    them for its registration (the labels decide which jobs it takes — not anything written in the office)."""
    now = time.time() if now is None else now
    with _gh_lock:
        if _gh["data"] is not None and now - _gh["at"] < GITHUB_TTL:
            return _gh["data"]
        tok = _token()
        if not tok:
            no = f"no GitHub token in the office's vault ({TOKEN_INSTANCE})"
            data = {"available": False, "why": no, "runner": {"name": _agent_name(), "labels": None, "why": no}}
        else:
            def get(path):
                req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}",
                                             headers={"Authorization": f"Bearer {tok}",
                                                      "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.load(r)
            def why(e):
                return f"GitHub answered {e.code}" if isinstance(e, urllib.error.HTTPError) else \
                    f"GitHub did not answer: {type(e).__name__}"
            # two questions, answered apart: the runners list needs the repository's Administration permission,
            # which the queue does not, and a refusal there must not hide the queue
            try:
                runs = get("/actions/runs?status=queued&per_page=30").get("workflow_runs") or []
                data = {"available": True,
                        "runs": [{"id": x.get("id"), "workflow": x.get("name"), "sha": (x.get("head_sha") or "")[:7],
                                  "branch": x.get("head_branch"), "actor": (x.get("actor") or {}).get("login"),
                                  "queued_at": x.get("created_at")} for x in runs]}
            except (urllib.error.HTTPError, OSError, ValueError) as e:
                data = {"available": False, "why": why(e)}
            name = _agent_name()
            try:
                runners = get("/actions/runners?per_page=100").get("runners") or [] if name else []
                mine = next((x for x in runners if x.get("name") == name), None)
                if mine:
                    labels = [lb.get("name") for lb in mine.get("labels") or []]
                    data["runner"] = {"name": name, "status": mine.get("status"), "busy": mine.get("busy"),
                                      "labels": labels,
                                      # the ssd jobs (the Android workflows, export-verify) need the emulator's
                                      # device and the host's runner: this app should not carry that label yet
                                      "warning": "התווית ssd על המריץ הזה: הוא ייקח עבודות שהוא לא יכול להריץ"
                                      if "ssd" in labels else None}
                else:
                    data["runner"] = {"name": name, "labels": None,
                                      "why": "no registration on the volume" if not name
                                      else f"GitHub lists no runner named {name}"}
            except (urllib.error.HTTPError, OSError, ValueError) as e:
                data["runner"] = {"name": name, "labels": None, "why": why(e)}
        _gh.update(at=now, data=data)
        return data


def queue() -> dict:
    data = github()
    return {k: v for k, v in data.items() if k != "runner"}


def set_paused(on: bool, state: Path | None = None) -> dict:
    flag = (STATE if state is None else state) / "paused"
    was = flag.exists()
    if on and not was:
        flag.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n", encoding="utf-8")
    elif not on and was:
        flag.unlink()
    if was != on and flowpub:
        flowpub.emit("ci-runner", "runner.paused" if on else "runner.resumed",
                     "המריץ נעצר בין עבודות — עבודות חדשות ממתינות בתור" if on else "המריץ חזר לקבל עבודות",
                     link="/#/m/ci-runner")
    return {"paused": on, "changed": was != on}


class Follower:
    """jobs.jsonl → the office's stream: each line written after the server started becomes one event; a start and
    its end share data.span (the run, its attempt and the job) and the end carries t0, so «כל מקביל» draws one bar."""

    def __init__(self, state: Path | None = None):
        self.path = (STATE if state is None else state) / "jobs.jsonl"
        self.last = b""                                       # the last whole line read: where to go on after a trim
        try:
            data = self.path.read_bytes()
            st = self.path.stat()
            whole = data.rfind(b"\n") + 1                     # a line still being written is read when it ends
            self.offset, self.inode = whole, st.st_ino        # history is not replayed…
            lines = data[:whole].splitlines()
            self.last = lines[-1] if lines else b""           # …but its last line is where a trim is followed from
        except OSError:
            self.offset, self.inode = 0, None
        self.started: dict = {}                               # span → its start, in ms

    def _started_at(self, sid: str) -> int | None:
        """A start this server did not see (it began while the server was down): read off the file, or None."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for ln in reversed(lines):
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("kind") == "started" and record.span_id(rec) == sid:
                return _ms(rec.get("at"))
        return None

    def _resync(self) -> None:
        """record.py trims by REPLACING the file with its last lines: go on after the last line read, as it stands in
        the new file — and from the new end when it is not there (nothing written since is lost but what fell out)."""
        try:
            data = self.path.read_bytes()
        except OSError:
            self.offset = 0
            return
        at = data.rfind(self.last + b"\n") if self.last else -1
        self.offset = at + len(self.last) + 1 if at >= 0 else len(data)

    def events(self) -> list[tuple]:
        """The (type, title, data) of every line written since the last call."""
        try:
            st = self.path.stat()
        except OSError:
            return []
        if self.inode is not None and st.st_ino != self.inode or st.st_size < self.offset:
            self._resync()
        self.inode = st.st_ino
        size = st.st_size
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read(max(0, size - self.offset))
        cut = chunk.rfind(b"\n") + 1                          # a line still being written waits for its end
        self.offset += cut
        lines = chunk[:cut].splitlines()
        if lines:
            self.last = lines[-1]
        out = []
        for raw in lines:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("kind") not in record.KINDS:
                continue
            data = {k: rec.get(k) for k in ("workflow", "job", "run_id", "sha", "ref_name", "actor", "waited_s",
                                            "runner_name")}
            sid = record.span_id(rec)
            if rec["kind"] == "started":
                self.started[sid] = _ms(rec.get("at"))
                data["span"] = sid
            elif rec["kind"] == "ended":
                # a bar only for a job that STARTED: a refused job's ended (the completed hook runs after a failed
                # started hook too) would otherwise turn its red bar into a success on «כל מקביל»
                t0 = self.started.pop(sid, None)
                t0 = self._started_at(sid) if t0 is None else t0
                if t0 is not None:
                    data["span"], data["t0"] = sid, t0
            elif rec["kind"] == "refused":
                data["span"] = sid                            # its own bar: from its last word at the door to the refusal
                data["t0"] = self.started.pop(sid, _ms(rec.get("at")) - int(rec.get("waited_s") or 0) * 1000)
            out.append((record.KINDS[rec["kind"]], record.title(rec), data))
        return out

    def run(self) -> None:
        while True:
            for typ, title, data in self.events():
                if flowpub:
                    flowpub.emit("ci-runner", typ, title, data=data, link="/#/m/ci-runner")
            time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    server_version = "ci-runner"

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _ok(self, op: str, data) -> None:
        self._json(200, {"ok": True, "op": op, "data": data})

    def do_GET(self) -> None:  # noqa: N802 — http.server's name
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        if path == "/healthz":
            return self._json(200, {"ok": True})
        if path == "/manifest":
            return self._json(200, {"app": "ci-runner", "ops": OPS, "state": status()})
        if path == "/api/status":
            return self._ok("status", status())
        if path == "/api/jobs":
            n = parse_qs(url.query).get("n", ["20"])[0]
            return self._ok("jobs", jobs(min(int(n), 500) if n.isdigit() else 20))
        if path == "/api/queue":
            return self._ok("queue", queue())
        if path == "/api/door/names":
            return self._ok("door_names", door.names())
        if path.startswith("/api/door/jobs/"):
            return self._door_read(path, url.query)
        if path in ("/", "/index.html"):
            try:
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            except OSError:
                return self._json(500, {"ok": False, "error": "the screen is missing from the image"})
        return self._json(404, {"ok": False, "error": f"no such route: {path}"})

    # ── the job door (door.py): every route asks who is asking first ─────────────────────────────────────────────
    def _who(self):
        who, code, why = door_caller(self.client_address[0], self.headers)
        if who is None:
            self._json(code, {"ok": False, "error": why})
        return who

    def _door_read(self, path: str, query: str) -> None:
        who = self._who()
        if who is None:
            return
        parts = path.split("/")                           # ['', 'api', 'door', 'jobs', '<id>'(, 'log')]
        if len(parts) not in (5, 6) or (len(parts) == 6 and parts[5] != "log"):
            return self._json(404, {"ok": False, "error": f"no such route: {path}"})
        row, why = door.find(STATE, parts[4], who[0])
        if row is None:
            return self._json(404, {"ok": False, "error": why})
        if len(parts) == 5:
            return self._ok("door_job", row)
        off = parse_qs(query).get("offset", ["0"])[0]
        page = door.log_page(STATE, parts[4], int(off) if off.isdigit() else 0)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("X-Door-State", str(row.get("state", "")))
        self.send_header("X-Door-Exit", "" if row.get("exit") is None else str(row.get("exit")))
        self.send_header("X-Door-Next", str((int(off) if off.isdigit() else 0) + len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def _door_ask(self) -> None:
        who = self._who()
        if who is None:
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 16 << 10)) or b"{}") if 0 < n <= (16 << 10) else None
        except (ValueError, OSError):
            body = None
        argv, why = door.validate(body)
        if argv is None:
            return self._json(400, {"ok": False, "error": why, "names": sorted(door.names())})
        got, why = door.enqueue(STATE, body["name"], argv, who[0], who[1])
        if got is None:
            return self._json(429, {"ok": False, "error": why})
        return self._json(202, {"ok": True, "op": "door_ask", "data": got})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        if len(parts) != 5 or not path.startswith("/api/door/jobs/"):
            return self._json(404, {"ok": False, "error": f"no such route: {path}"})
        who = self._who()
        if who is None:
            return
        got, why = door.cancel(STATE, parts[4], who[0])
        if got is None:
            return self._json(409 if why != "no such job" else 404, {"ok": False, "error": why})
        return self._ok("door_cancel", got)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/door/jobs":
            return self._door_ask()
        if path not in ("/api/pause", "/api/resume"):
            return self._json(404, {"ok": False, "error": f"no such route: {path}"})
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._json(403, {"ok": False, "error": "pause and resume are the app's own CLI's for now: "
                                                         "./bbox ci-runner pause | resume"})
        op = path.rsplit("/", 1)[-1]
        return self._ok(op, set_paused(op == "pause"))

    def log_message(self, *a) -> None:
        pass


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=Follower().run, name="follow-records", daemon=True).start()
    print(f"ci-runner on :{PORT} (state {STATE})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
