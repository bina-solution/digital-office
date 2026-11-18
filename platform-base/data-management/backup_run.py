"""One backup of this office into a restic repository on a target (DGO-1523, the run).

ONE RUN

    1. Admission. One run at a time in this process; none sooner than DATA_RUN_MIN_INTERVAL after the
       last one started (POST /api/backup has no caller check of its own, and every run on an
       append-only target is a copy nobody can remove); free space on the archive root of the last
       export's size and a fifth, plus DATA_RUN_MIN_FREE. A run that does not start says why
       (Refused), never a silent success. What a run cut short left in staging goes first.
    2. The key: backup_key-<office> in this office's vault. It is made there once, and only while the
       repository does not exist yet. A missing key in front of an existing repository stops the run:
       a new key cannot open it, and nobody would know until the day of a restore.
    3. The export: the archiver (scripts/deployment-archive.py export --mode full), the one program
       export and import have always used, into a staging directory under the archive root.
    4. restic, in a throwaway helper container (pinned by digest; 1 CPU, 1 GiB; the staging directory
       read-only at /backup/office), talking to THIS service's /repo/<target>/ with a token for this
       run only (restic_store.py). The repository address, which carries the token, and the key go to
       the helper on its STDIN, into a tmpfs: never an argv, never an environment the engine keeps in
       the container's config, never a log (the helper's log driver is none).
    5. init when the repository does not exist (and only then: a key it does not open stops the run);
       the stale locks of a run cut short are removed (never a live one); backup with --host <office>
       and tags; on a target that may delete, forget by KEEP (7/4/6), pruned on PRUNE_DAY (`retention`);
       then check --read-data-subset=<weekday>/7, so every byte is read once a week.
    6. The token is closed and the staging directory removed on every path out of the run; what a
       process that died mid-run left there is removed when the next run starts.
    7. For a new repository the key is read back from the vault once more and must be the one that
       made it. The result (snapshot, sizes, the check) is kept in the service's volume.

THE HERD STORE, ON ANOTHER OFFICE (slice 3)

    A REMOTE target ({remote, target, link}, restic_store.py) is a store another office keeps, reached
    through that office's link door. The run asks it over the link FIRST, before anything is made or
    exported: POST <remote>/api/repo-runs with a proof made with the pair's secret (link_proof.py). The
    answer says whether the repository exists, so the key rule above holds across offices, and a store
    that does not admit this office stops the run with nothing sent. That first run is closed at once;
    after the export a second one is opened for the helper, whose repository address is the store's
    door with that run's token. It is closed on every path out of the run.

THE NIGHTLY RUN

    A target with `nightly_utc: "HH:MM"` is due once that time of day plus its `spread` (the same every night for
    one office and target, ≤ DATA_NIGHTLY_SPREAD) has passed since its last start (`due`), and app.py's schedule
    starts it. A night the service was down is caught up when it is back.

    A target that may delete then forgets by KEEP and prunes on PRUNE_DAY, or on any night once its last prune is
    PRUNE_OVERDUE old (`retention`) — and never while another office is pulling it: the store marks the target for
    the helper's whole run (restic_store.Runs.begin_delete), a pull asked for meanwhile is answered 503, and a
    night that finds a pull open deletes nothing (DGO-1517).

WHAT IT IS NOT YET

    One snapshot of the whole office, not one per app: the archiver's per-app export carries no office
    part (secrets, declarations). Its artifacts are compressed (tar czf, pg_dump -Fc), so restic stores
    every night whole instead of only what changed. Both are ob-4's.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import threading
import base64
import http.client
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import link_proof as LINK
import restic_store as STORE

# restic 0.18.0, by digest: a moving tag is a different program on the day somebody pulls (G74)
RESTIC_IMAGE = os.environ.get("DATA_RESTIC_IMAGE") or (
    "restic/restic:0.18.0@sha256:4cf4a61ef9786f4de53e9de8c8f5c040f33830eb0a10bf3d614410ee2fcb6120")
# How the helper reaches this service: its container name, which is unique per office (compose's
# container_name), not the bare service name, which two offices on one engine would both answer to.
SELF = os.environ.get("DATA_REPO_SELF") or \
    f"data-management-{os.environ.get('DEPLOYMENT_NAME') or 'bina-deployment'}:8080"
NETWORK = os.environ.get("DATA_RUN_NETWORK") or "traefik-network"
# The name THIS office has on its links (`DGO_OFFICE_ID`), which the store's door writes as the asker
# (x-dgo-office) and the proof must name. It is not DEPLOYMENT_NAME: the MacBook is `local` to compose
# and `macbook` to every link. Without a declared id the run's own office name is used.
LINK_OFFICE = os.environ.get("DGO_OFFICE_ID") or ""
VAULT = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
MIN_FREE = int(os.environ.get("DATA_RUN_MIN_FREE") or 2 * 1024 ** 3)
MIN_INTERVAL = float(os.environ.get("DATA_RUN_MIN_INTERVAL") or 3600)
# a first backup of a large office over a slow uplink takes long; past this a hung step is stopped
RUN_TIMEOUT = float(os.environ.get("DATA_RUN_TIMEOUT") or 24 * 3600)
EXPORT_TIMEOUT = float(os.environ.get("DATA_EXPORT_TIMEOUT") or 12 * 3600)
_OFFICE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")
_ONE = threading.Lock()
# What a target that may delete keeps (DGO-1517, «7/4/6»): the last snapshot of each of the last 7 days, of each of
# the last 4 weeks and of each of the last 6 months. Forgotten every night; their unreferenced data pruned on PRUNE_DAY
# (ISO weekday, 7 = Sunday), so the week's prune is one night's long step and the other six stay short. An append-only
# target (the herd store, a store given to another office) and a remote one keep every snapshot: nothing is forgotten.
KEEP = (("daily", 7), ("weekly", 4), ("monthly", 6))
PRUNE_DAY = 7
# A prune missed on its day (the night failed, or another office was pulling the store) is not a week's wait: any
# night after PRUNE_OVERDUE since the last one prunes; past PRUNE_LATE the result says so (DGO-1517, the reader).
PRUNE_OVERDUE = 8 * 86400
PRUNE_LATE = 14 * 86400
# Offices whose nights all say 03:00 do not all reach one store at 03:00: each target starts at its slot plus a
# spread of up to NIGHTLY_SPREAD seconds, the same every night for one office and target (DGO-1517, «+ פיזור»)
NIGHTLY_SPREAD = int(os.environ.get("DATA_NIGHTLY_SPREAD") or 3600)


def retention(spec: dict, weekday: int, pruned: float | None = None, now: float | None = None) -> str:
    """What the night's helper does after the backup: `none` (keeps every snapshot), `forget` or `prune` — prune on
    PRUNE_DAY, or on any night once the last prune (`pruned`, a unix time; None when none is recorded) is
    PRUNE_OVERDUE old. Whether another office is pulling the store is `run`'s to decide, for the helper's whole
    run (restic_store.Runs.begin_delete): then nothing is deleted at all."""
    if "remote" in spec or spec.get("mirror") or spec.get("append_only", True) is not False:
        return "none"
    if weekday == PRUNE_DAY:
        return "prune"
    if pruned is not None and (time.time() if now is None else now) - pruned >= PRUNE_OVERDUE:
        return "prune"
    return "forget"


def _when(value) -> float | None:
    """An ISO time a result kept (`pruned`) as a unix time, or None when there is none or it does not read."""
    try:
        return datetime.datetime.fromisoformat(str(value)).timestamp() if value else None
    except (TypeError, ValueError):
        return None


def spread(office: str, target: str) -> int:
    """Seconds after its slot a target's night starts: from the office and the target, so the same every night."""
    if NIGHTLY_SPREAD <= 0:
        return 0
    digest = hashlib.sha256(f"{office}\0{target}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % min(NIGHTLY_SPREAD, 23 * 3600)


class Refused(Exception):
    """Nothing was started, and the sentence says why."""


class Failed(Exception):
    """The run started and did not finish; the sentence says where."""


# ── the vault ───────────────────────────────────────────────────────────────────────────────────
def _vault(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """(status, json) from this office's vault; (0, {...}) when it did not answer at all."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(VAULT + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {}


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def read_key(office: str) -> str:
    """backup_key-<office> as the vault holds it now; '' when it holds none."""
    iid = f"backup_key-{office}"
    st, js = _vault("GET", f"/api/instances/{iid}/secret")
    if st not in (200, 404):
        # the vault did not answer: that is not «the key is gone», and nothing may be made on it
        raise Failed(f"the vault did not answer ({st or 'no answer'}): {iid} was not read, and none is made")
    return ((js.get("secret") or {}).get("key") or "") if st == 200 else ""


def office_key(office: str, repo_exists: bool) -> tuple[str, str]:
    """(key, fingerprint) of backup_key-<office>, made in the vault once and only for a new repository."""
    iid = f"backup_key-{office}"
    key = read_key(office)
    if key:
        return key, fingerprint(key)
    if repo_exists:
        raise Failed(f"{iid} is not in this office's vault, but the repository exists and only that key opens "
                     "it: put it back from the vault's own backup. No new key is made.")
    st, js = _vault("POST", "/api/instances", {
        "id": iid, "protocol": "backup_key", "label": f"Backup key · {office}",
        "account_hint": "opens this office's restic backups; a restore needs it",
        "secret": {"key": secrets.token_urlsafe(32)}})
    if st not in (200, 409):                       # 409: made a moment ago by another run; read it back
        raise Failed(f"the vault did not keep {iid} ({st or 'no answer'})")
    key = read_key(office)                         # what is stored is what encrypts
    if not key:
        raise Failed(f"{iid} was not read back from the vault")
    return key, fingerprint(key)


# ── the helper ──────────────────────────────────────────────────────────────────────────────────
# $1 office, $2 run id, $3 the check's subset, $4 the retention (none | forget | prune, `retention`), $5 the keep
# policy's flags (split on purpose: `--keep-daily 7 …`). Line 1 of stdin is the repository address (with the run's
# token), line 2 the key. Each step prints one JSON line of its own; restic's own lines pass. The forget runs before
# the check, so the night's check reads the repository a prune left; a forget that failed fails the run (exit 21) even
# when the check passed, or a store that stopped forgetting would fill up unseen.
HELPER = r"""set -eu
IFS= read -r RESTIC_REPOSITORY
IFS= read -r k
umask 077
printf %s "$k" > /run/k/key
k=
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE=/run/k/key
rc=0
restic --no-cache cat config >/dev/null 2>/run/k/err || rc=$?
if [ "$rc" -eq 10 ]; then
  restic --no-cache -q init >/dev/null
  echo '{"step":"init","ok":true}'
elif [ "$rc" -ne 0 ]; then
  echo "{\"step\":\"open\",\"ok\":false,\"rc\":$rc}"
  head -c 400 /run/k/err >&2
  exit 20
fi
# the locks a run cut short left (a timeout, a restart that dropped its token): stale ones only, so
# a live run elsewhere keeps its own; without this every later check fails on them
restic --no-cache -q unlock
echo '{"step":"unlock","ok":true}'
restic --no-cache -q backup /backup/office --host "$1" --tag "office=$1" --tag "run=$2" --json
frc=0
case "$4" in
  forget|prune)
    p=
    [ "$4" = prune ] && p=--prune
    # this office's snapshots only, grouped by host and path: never by tags, which carry each run's own id
    restic --no-cache -q forget --host "$1" --group-by host,paths $5 $p >/run/k/err 2>&1 || frc=$?
    if [ "$frc" -ne 0 ]; then head -c 400 /run/k/err >&2; fi
    echo "{\"step\":\"forget\",\"ok\":$([ "$frc" -eq 0 ] && echo true || echo false),\"prune\":$([ -n "$p" ] && echo true || echo false)}"
    ;;
esac
rc=0
restic --no-cache -q check --read-data-subset "$3" >/run/k/err 2>&1 || rc=$?
if [ "$rc" -ne 0 ]; then head -c 400 /run/k/err >&2; fi
echo "{\"step\":\"check\",\"ok\":$([ "$rc" -eq 0 ] && echo true || echo false),\"subset\":\"$3\"}"
if [ "$rc" -eq 0 ] && [ "$frc" -ne 0 ]; then exit 21; fi
exit "$rc"
"""


def keep_flags() -> str:
    """restic forget's policy flags for KEEP: `--keep-daily 7 --keep-weekly 4 --keep-monthly 6`."""
    return " ".join(f"--keep-{unit} {int(n)}" for unit, n in KEEP)


def helper_argv(name: str, staging: pathlib.Path, office: str, run_id: str, subset: str,
                keep: str = "none") -> list[str]:
    """The helper's command line. It carries no secret: those go on stdin (see HELPER)."""
    if keep not in ("none", "forget", "prune"):
        raise ValueError(f"retention {keep!r}")
    return ["docker", "run", "--rm", "-i", "--init", "--name", name, "--network", NETWORK,
            "--cpus", "1", "--memory", "1g", "--pids-limit", "256", "--log-driver", "none",
            "--tmpfs", "/run/k:size=1m,mode=0700",
            "-v", f"{staging}:/backup/office:ro",
            "--entrypoint", "/bin/sh", RESTIC_IMAGE, "-c", HELPER, "restic-run", office, run_id, subset,
            keep, keep_flags()]


def _parse(stdout: str) -> dict:
    out = {"steps": []}
    for line in stdout.splitlines():
        try:
            js = json.loads(line)
        except ValueError:
            continue
        if not isinstance(js, dict):
            continue
        if js.get("message_type") == "summary":
            out["snapshot"] = js.get("snapshot_id")
            out["files"] = js.get("total_files_processed")
            out["bytes"] = js.get("total_bytes_processed")
            out["added"] = js.get("data_added")
        elif js.get("step"):
            out["steps"].append(js)
    return out


# ── the herd store on another office ────────────────────────────────────────────────────────────
class Bounded:
    """One HTTP exchange with another office that ends by `deadline` (time.monotonic()), whatever the other side
    does: a timer shuts the socket at the deadline, so neither a trickled answer nor trickled HEADERS hold this
    office's one run (the mirror's second reader). Never follows a redirect (http.client does not), so a 3xx never
    carries a proof or a run's token to an address the other office names. Use as a context manager; `.resp` is the
    answer, `.read(limit)` its whole body — refused when longer than `limit`, or shorter than its Content-Length, or
    of no known length (a body cut short is never taken for a short one)."""

    def __init__(self, url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None,
                 deadline: float | None = None, read_timeout: float = 60.0):
        self.deadline = deadline if deadline is not None else time.monotonic() + 120
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise OSError(f"not an http(s) address: {url[:120]}")
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the deadline passed before the request")
        conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        self.conn = conn_cls(u.hostname, u.port, timeout=min(read_timeout, left))
        self.sock = None
        self.timer = threading.Timer(left, self._shut)
        self.timer.daemon = True
        self.timer.start()
        try:
            self.conn.connect()
            # held HERE: an answer that says `Connection: close` (or is HTTP/1.0) makes getresponse() drop the
            # connection's own reference, and a timer that looked there found nothing to shut while a chunk-size
            # line trickled in for days (the mirror's third reader)
            self.sock = self.conn.sock
            self.conn.request(method, (u.path or "/") + (f"?{u.query}" if u.query else ""), body=body,
                              headers=dict(headers or {}))
            self.resp = self.conn.getresponse()
        except BaseException:
            self.close()
            raise

    def _shut(self):
        for sock in (self.sock, getattr(self.conn, "sock", None)):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def late(self) -> bool:
        return time.monotonic() >= self.deadline

    def read(self, limit: int) -> bytes:
        declared = self.resp.getheader("Content-Length")
        chunked = (self.resp.getheader("Transfer-Encoding") or "").lower() == "chunked"
        if declared is None and not chunked:
            raise ValueError("an answer of no known length is not believed (no Content-Length, not chunked)")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            raise ValueError(f"an answer of {declared} bytes is longer than {limit}")
        buf, n = [], 0
        while True:
            if self.late():
                raise TimeoutError("the answer ran past its deadline")
            chunk = self.resp.read1(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise ValueError(f"the answer is longer than {limit} bytes")
            buf.append(chunk)
        if self.late():
            raise TimeoutError("the answer ran past its deadline")
        if declared is not None and n != int(declared):
            raise ValueError(f"the answer was cut short: {n} of the {declared} bytes it declared")
        return b"".join(buf)

    def close(self):
        self.timer.cancel()
        try:
            self.conn.close()
        except Exception:                                 # noqa: BLE001 — closing never raises
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


#: what a dropped, refused, cut or stalled exchange raises (TimeoutError and ValueError included)
EXCHANGE_BROKEN = (OSError, http.client.HTTPException, ValueError, RecursionError)


class Remote:
    """A store another office keeps, asked through its link door (restic_store.py, /api/repo-runs)."""

    def __init__(self, spec: dict, office: str):
        self.base, self.target, self.link, self.office = spec["remote"], spec["target"], spec["link"], office

    DEADLINE = 120.0                                      # one call, headers and body, whatever the other side does

    def _call(self, method: str, headers: dict) -> tuple[int, dict]:
        url = f"{self.base}/api/repo-runs" + (f"?target={self.target}" if method == "POST" else "")
        try:
            # never a redirect, and a deadline on the whole exchange: the office at the other end may be a client's
            # (a mirror's pull, DGO-1523) — a 3xx would carry the proof or the run's token to any address it names,
            # inside this office's network, and a stalled answer would hold this office's one run
            with Bounded(url, method, headers, b"" if method == "POST" else None,
                         deadline=time.monotonic() + self.DEADLINE) as x:
                status, raw = x.resp.status, x.read(1 << 16)
        except EXCHANGE_BROKEN as e:
            # a refused, dropped, cut or stalled exchange (IncompleteRead, BadStatusLine, the deadline)
            raise Refused(f"the herd store on {self.link} did not answer at {self.base}: "
                          f"{type(e).__name__}: {e}") from e
        try:
            js = json.loads(raw or b"{}")
        except (ValueError, RecursionError):
            return status, {}
        return status, js if isinstance(js, dict) else {}

    def open(self) -> dict:
        """{user, token, exists} of a run the store opened for this office. Refused when it did not."""
        try:
            secret = LINK.link_secret(self.link)
        except LINK.Unavailable as e:
            raise Refused(f"this office's vault did not answer, so the link with {self.link} was not read: {e}") from e
        if not secret:
            raise Refused(f"no link with {self.link} in this office's vault: its herd store is reached only over it")
        st, js = self._call("POST", {LINK.HEADER: LINK.make(self.office, self.target, secret)})
        if st == 401:
            raise Refused(f"the herd store on {self.link} did not admit {self.office} to {self.target} "
                          f"(its own log says why)")
        if st != 200 or not (isinstance(js.get("user"), str) and re.fullmatch(r"run-[0-9a-f]{16}", js["user"])
                             and isinstance(js.get("token"), str) and re.fullmatch(r"[A-Za-z0-9_-]{20,100}", js["token"])
                             and isinstance(js.get("exists"), bool)):
            # its own sentence goes on (a 503 «forgetting/pruning that store now», DGO-1517): every hop keeps it
            said = js.get("detail") if isinstance(js, dict) else None
            raise Refused(f"the herd store on {self.link} answered {st} for {self.target}, not a run"
                          + (f": {str(said)[:200]}" if said else ""))
        return js

    def close(self, run: dict) -> None:
        """Best effort, never raising: a run left open closes itself when idle (restic_store.RUN_IDLE),
        and nothing that goes wrong here may keep this office's one run from being released."""
        auth = base64.b64encode(f"{run['user']}:{run['token']}".encode()).decode()
        try:
            self._call("DELETE", {"Authorization": f"Basic {auth}"})
        except Exception:                                   # noqa: BLE001 — see the docstring
            pass

    def repository(self, run: dict) -> str:
        u = urllib.parse.urlsplit(self.base)
        return f"rest:{u.scheme}://{run['user']}:{run['token']}@{u.netloc}/repo/{self.target}/"


def due(slot: str, last_start: float | None, now: datetime.datetime, offset: int = 0) -> bool:
    """Is a nightly run at `slot` (HH:MM, UTC) plus `offset` seconds (`spread`) due at `now`, its last start at
    `last_start`? Once that night's start time has passed and nothing started since its bare slot (a start at or after
    the slot — a run by hand, or last night's under the rule before the spread — is that night's: the first night
    after this deploy is not an extra daytime run, the reader); never run is due at once (a nightly backup that waits
    a day for its first copy is a day without one)."""
    hh, mm = (int(x) for x in slot.split(":"))
    now = now.astimezone(datetime.timezone.utc)
    today = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + datetime.timedelta(seconds=offset)
    if today - datetime.timedelta(days=1) > now:          # an offset that carried tonight's slot past midnight
        today -= datetime.timedelta(days=1)
    latest = today if now >= today else today - datetime.timedelta(days=1)
    return last_start is None or last_start < latest.timestamp() - offset


# ── the run ─────────────────────────────────────────────────────────────────────────────────────
def archiver_export(repo: pathlib.Path):
    """The default export: the archiver, the same program /api/export runs, into `staging`."""
    def export(staging: pathlib.Path, log) -> None:
        argv = ["python3", str(repo / "scripts" / "deployment-archive.py"), "export", "--mode", "full",
                "--out", str(staging)]
        p = subprocess.Popen(argv, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert p.stdout is not None
        # a hung tar or pg_dump would hold the one run forever: past its deadline it is killed
        late = threading.Event()
        watchdog = threading.Timer(EXPORT_TIMEOUT, lambda: (late.set(), p.kill()))
        watchdog.start()
        try:
            for line in p.stdout:
                log(line.rstrip())
            rc = p.wait()
        finally:
            watchdog.cancel()
        if late.is_set():
            raise Failed(f"the export ran past {EXPORT_TIMEOUT / 3600:.0f} h and was stopped; nothing was sent")
        if rc != 0:
            raise Failed(f"the export stopped (exit {rc}); nothing was sent")
    return export


def left_out(staging: pathlib.Path) -> dict:
    """What the export named and did not carry, from its manifest (DGO-1510): every volume on the engine that no
    installed app declares — this project's and the others' — with its size, and the anonymous ones counted. The
    run's result carries it, so the run's report names them as its manifest does. A listing that failed, or a manifest
    that says nothing of it, is UNKNOWN, never «nothing left out»; and a report never stops the backup."""
    def unknown(why: str) -> dict:
        return {"volumes": None, "anonymous": None, "error": why}
    try:
        man = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        if man.get("undeclared_volumes_error"):
            return unknown(str(man["undeclared_volumes_error"])[:300])
        if not isinstance(man.get("undeclared_volumes"), list):
            return unknown("the export's manifest does not say which volumes no app declares")
        return {"volumes": [{k: v.get(k) for k in ("name", "project", "size")} for v in man["undeclared_volumes"]],
                "anonymous": int(man.get("anonymous_volumes") or 0)}
    except Exception as e:                                          # noqa: BLE001 — a report, never the run's end
        return unknown(f"the export's manifest did not read: {type(e).__name__}")


def run(target: str, office: str, archive_root: pathlib.Path, state_dir: pathlib.Path, export, log,
        weekday: int | None = None) -> dict:
    """One backup of `office` to `target`. Returns the result (also kept in state_dir); raises Refused
    when nothing was started and Failed when the run stopped. Never two at once in one process."""
    if not _OFFICE.fullmatch(office or ""):
        raise Refused(f"office id {office!r} is not a name a key or a restic host can carry")
    if not _ONE.acquire(blocking=False):
        raise Refused("a backup run is already going in this service")
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    staging = archive_root / ".restic-staging" / run_id
    close = None                                      # how the helper's run is closed, once one is open
    held = False                                      # the target marked against a pull (Runs.begin_delete)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        try:
            spec = STORE.targets().get(target)
        except ValueError as e:
            raise Refused(str(e)) from e
        if spec is None:
            raise Refused(f"no backup target {target!r} is declared")
        if spec.get("link") and "remote" not in spec:
            # the store this office keeps FOR another one: its first repository must be that office's,
            # made with that office's key — a run from here would make it with this office's key
            raise Refused(f"{target} is kept here for {spec['link']}: only {spec['link']} backs up into it")
        began = _started(state_dir, target)
        if began is not None and datetime.datetime.now(datetime.timezone.utc).timestamp() - began < MIN_INTERVAL:
            raise Refused(f"a run to {target} started less than {MIN_INTERVAL / 60:.0f} min ago")
        if spec.get("mirror"):
            # a client office's repository, kept here (DGO-1523): filled by its pull alone, never by an export of
            # this office; the night counts as started once the client admitted the pull (a refusal retries)
            import mirror as MIRROR
            try:
                result = MIRROR.pull(target, spec, LINK_OFFICE or office, log,
                                     began=lambda: _mark_started(state_dir, target))
            except MIRROR.Refused as e:
                raise Refused(str(e)) from e
            except MIRROR.Failed as e:
                raise Failed(str(e)) from e
            _keep(state_dir, target, result)
            return result
        # what a run cut short left here (a process that died mid-run never reached its finally):
        # only this process runs backups, and it holds the one run now, so nothing here is alive
        for old in (archive_root / ".restic-staging").glob("*"):
            shutil.rmtree(old, ignore_errors=True)
        archive_root.mkdir(parents=True, exist_ok=True)
        prev = last(state_dir, target) or {}
        need = MIN_FREE + int(1.2 * int(prev.get("bytes") or 0))
        free = shutil.disk_usage(archive_root).free
        if free < need:
            raise Refused(f"{free / 1e9:.1f} GB free on the archive root, {need / 1e9:.1f} GB needed "
                          f"(the last export and a fifth, and {MIN_FREE / 1e9:.1f} GB to spare)")
        remote = Remote(spec, LINK_OFFICE or office) if "remote" in spec else None
        if remote:
            # asked over the link before anything is made: whether it admits this office, and whether
            # the repository is there (the key rule below depends on it)
            first = remote.open()
            remote.close(first)
            exists = first["exists"]
        else:
            try:
                exists = STORE.Drive(spec["url"], spec["connection_id"]).stat(spec["folder"] + "/config") is not None
            except Exception as e:                                  # noqa: BLE001 — named in the sentence
                raise Refused(f"the target's files app did not answer, so whether the repository exists is "
                              f"unknown: {str(e)[:200]}") from e
        key, fp = office_key(office, exists)
        where = f"{target} (the herd store on {remote.link})" if remote else target
        log(f"run {run_id}: office {office} → {where} ({'existing' if exists else 'new'} repository, key {fp})")

        _mark_started(state_dir, target)
        staging.mkdir(parents=True)
        export(staging, log)
        not_carried = left_out(staging)

        if remote:
            try:
                lease = remote.open()
            except Refused as e:
                raise Failed(f"after the export: {e}") from e
            close = lambda: remote.close(lease)          # noqa: E731
            repo = remote.repository(lease)
        else:
            user, token = STORE.RUNS.open(target)
            close = lambda: STORE.RUNS.close(user)       # noqa: E731
            repo = f"rest:http://{user}:{token}@{SELF}/repo/{target}/"
        n = weekday or datetime.date.today().isoweekday()
        pruned = _when(prev.get("pruned"))
        keep = retention(spec, n, pruned)
        # A night that deletes holds the target against a pull for the helper's WHOLE run, taken atomically with
        # "no pull is open" (restic_store.Runs.begin_delete), and lets go only after the run's token is closed (the
        # finally below); a pull already open means nothing is deleted tonight.
        waited = False
        if keep != "none":
            held = STORE.RUNS.begin_delete(target)
            if not held:
                keep, waited = "none", True
                log(f"run {run_id}: another office is pulling {target}: nothing is forgotten or pruned tonight")
        name = f"restic-run-{run_id.lower()}"
        argv = helper_argv(name, staging, office, run_id, f"{n}/7", keep)
        try:
            p = subprocess.run(argv, input=f"{repo}\n{key}\n", capture_output=True, text=True,
                               timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
            raise Failed(f"restic ran past {RUN_TIMEOUT / 3600:.0f} h and was stopped") from e
        res = _parse(p.stdout)
        for s in res["steps"]:
            log(f"  {s.get('step')}: {'ok' if s.get('ok') else 'FAILED'}")
        if p.returncode != 0 or not res.get("snapshot"):
            raise Failed(f"restic exited {p.returncode}"
                         f"{'' if res.get('snapshot') else ' without a snapshot'}: {p.stderr.strip()[-400:]}")
        if not exists and fingerprint(read_key(office)) != fp:
            # the vault rewrote itself around the new key (a concurrent write it does not lock against):
            # the repository just made opens with a key nobody holds any more
            raise Failed(f"backup_key-{office} in the vault is no longer the key this new repository was made "
                         f"with ({fp}): the repository cannot be trusted to open; it must be made again")
        finished = datetime.datetime.now(datetime.timezone.utc)
        policy = "/".join(str(k) for _, k in KEEP)
        if waited:
            said = f"nothing forgotten tonight: another office was pulling this store ({policy} next night)"
        elif keep == "none":
            said = "every snapshot kept (append-only)"
        else:
            said = f"{policy} forgotten" + (", pruned" if keep == "prune" else "")
        if keep != "prune" and retention(spec, PRUNE_DAY) == "prune" and pruned is not None \
                and finished.timestamp() - pruned >= PRUNE_LATE:
            said += f"; NOT PRUNED since {datetime.datetime.fromtimestamp(pruned, datetime.timezone.utc):%Y-%m-%d}"
        result = {"run": run_id, "target": target, "office": office, "started": started,
                  "finished": finished.isoformat(),
                  "snapshot": res["snapshot"], "files": res.get("files"), "bytes": res.get("bytes"),
                  "added": res.get("added"), "check": f"{n}/7 ok", "key": f"backup_key-{office}",
                  "key_fingerprint": fp, "image": RESTIC_IMAGE, "retention": said,
                  # the clock of the overdue prune, carried from run to run: the last prune — or, before the first,
                  # the first night this target was kept by the rule, so a target whose prunes are always blocked
                  # is overdue too (the third reader)
                  # (None for a store that keeps everything; a carried value that does not read is a new baseline)
                  "pruned": (None if retention(spec, PRUNE_DAY) != "prune"
                             else finished.isoformat() if keep == "prune" or pruned is None
                             else prev.get("pruned")),
                  "not_carried": not_carried}
        if remote:
            result["store"] = {"office": remote.link, "target": remote.target}
        _keep(state_dir, target, result)
        log(f"run {run_id}: snapshot {res['snapshot'][:8]} · {res.get('files')} files · "
            f"{(res.get('added') or 0) / 1e6:.1f} MB added · check {n}/7 ok")
        if not_carried.get("error"):
            log(f"run {run_id}: which volumes no app declares is UNKNOWN: {not_carried['error']}")
        elif not_carried["volumes"] or not_carried["anonymous"]:
            log(f"run {run_id}: NOT carried — {len(not_carried['volumes'])} volume(s) no app declares, "
                f"{not_carried['anonymous']} anonymous: "
                + ", ".join(f"{v['name']} ({v['size'] or 'size unknown'})" for v in not_carried["volumes"]))
        return result
    finally:
        try:
            if close:
                close()
        finally:
            try:
                if held:          # after the token: no pull opens while a helper with a live token could delete
                    STORE.RUNS.end_delete(target)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
                _ONE.release()


def _started(state_dir: pathlib.Path, target: str) -> float | None:
    try:
        return float((state_dir / f"last-start-{target}").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _mark_started(state_dir: pathlib.Path, target: str) -> None:
    """When the last run to `target` began, kept past a restart: the interval holds across one."""
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / f"last-start-{target}"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(str(datetime.datetime.now(datetime.timezone.utc).timestamp()))
    os.replace(tmp, f)


def _keep(state_dir: pathlib.Path, target: str, result: dict) -> None:
    """The last good run per target, whole or not at all."""
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / f"last-backup-{target}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def last(state_dir: pathlib.Path, target: str) -> dict | None:
    f = state_dir / f"last-backup-{target}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
