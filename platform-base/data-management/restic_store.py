"""restic's REST backend (v2), served by data-management and written through the generic drive (DGO-1513).

WHAT IT IS

    restic talks to  rest:http://<run>:<token>@data-management:8080/repo/<target>/  and every object
    it writes lands as a file in a files app the owner picked: an office, an engine, an account, a
    folder (ai/context/office-backup.md §3.3). The folder holds restic's own local layout

        config  keys/<id>  locks/<id>  snapshots/<id>  index/<id>  data/<first 2 hex>/<id>

    so a copy of it downloaded by hand opens with `restic -r <folder>` and nothing of DGO.

    Every call goes to the generic drive's HTTP API (apps/drive/ENGINES.md «For backup»), never to an
    engine, so a target on drive-local and a target on drive-google are one code path.

WHAT IT REFUSES

    - A request without the token of a run opened here for THIS target: 401. data-management's API
      has no caller check of its own (SSO is at Traefik only), and any container on traefik-network,
      n8n included, could otherwise read or write a repository. A token exists only in this process,
      for the run that opened it; nothing here mints one over HTTP.
    - An object whose name is not the sha256 of its bytes: 400. Every restic file except `config` is
      named by its own hash, so the write is checked whole before the drive makes it visible.
    - A second write of a name: 403, as restic's rest-server answers, unless the same object is
      already there (a retry of a write whose answer was lost). A name or kind restic never uses:
      404, before the drive is asked anything.
    - A run whose target changed since it opened (folder, account, append_only): 401. Two targets
      whose folders overlap on one account: the targets file is refused whole.
    - On an append-only target (the herd store): every delete except locks/, 403. No office can erase
      its own copies; `forget` and `prune` run only where the target is not append-only.

THE HERD STORE: ANOTHER OFFICE'S RUNS, OVER THE LINK (DGO-1523, slice 3)

    A target may be GIVEN to one linked office (`link: <office>`, append-only always): that office
    opens a run on it at POST /api/repo-runs, through this office's link door (`backup-store`, a door
    with no tile whose paths are /repo/ and /api/repo-runs, DGO-945), with a proof made with the pair's
    own secret (link_proof.py). The answer is the run's token and whether the repository exists. Every
    /repo call of that run must come through the same link (`x-dgo-office`); the run is closed with its
    own token at DELETE /api/repo-runs. Nothing else is opened over the link, and a refusal is one
    401 whatever its reason (the reason goes to this office's log).

    The office that backs up declares the other end as a REMOTE target: `{remote: <the door's
    address>, target: <the store's target id>, link: <the store's office>}`. It is not served here
    (/repo answers 401 for it); backup_run.py asks the store over the link.

    The door delivers to the name in the capability's endpoint, `data-management`. On an engine two
    offices share, that bare name answers for both, so the herd store's office runs alone on its engine
    (the HP does); a door that delivers to a container name is the link's own item, for every door.

    Until a run opens a token, /repo answers 401 to everyone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse

import link_proof as LINK

# ── what restic sends ───────────────────────────────────────────────────────────────────────────
KINDS = ("data", "keys", "locks", "snapshots", "index")
_NAME = re.compile(r"[0-9a-f]{64}")      # always .fullmatch: `^…$` lets a name with a trailing \n through
V2 = "application/vnd.x.restic.rest.v2"
# restic's largest pack is 128 MiB (--pack-size); anything much larger is not restic.
MAX_OBJECT = int(os.environ.get("DATA_REPO_MAX_OBJECT") or 160 * 1024 * 1024)
# A run's token lives while the run is busy: each admitted call extends it by RUN_IDLE, never past
# RUN_MAX from the opening. A first backup over a slow uplink may take a day; a forgotten token is a
# door left open, so an idle one closes in hours.
RUN_IDLE = float(os.environ.get("DATA_REPO_RUN_IDLE") or 2 * 3600)
RUN_MAX = float(os.environ.get("DATA_REPO_RUN_MAX") or 72 * 3600)
# the folder mark (drive-local's `system`): the holding office leaves a marked folder out of its own
# backup, and a person cannot rename, move or delete it from the drive's screen
SYSTEM_MARK = "data-management"

# ── targets ─────────────────────────────────────────────────────────────────────────────────────
#
# A target is where one repository lives. They are written by the screen that picks them (ob-9);
# until then by hand, into the service's own store — data/data-management/state (its old volume
# data_management_state only where the office still waits on the move). The file is read on every request, so a change
# needs no restart, and a malformed file is a 503 naming itself, never a guess.
#
# `url` is the files app's generic API, written by whoever picks the target, from the compiled
# registry. There is no default: the platform does not name the app it writes through (G33).
_TARGET_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_CONN_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _targets_file() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DATA_REPO_TARGETS")
                        or pathlib.Path(os.environ.get("DATA_STATE_DIR", "/state")) / "backup-targets.json")


def _clean_folder(folder) -> str:
    """'/גיבויים/exampleu' as the drive itself will resolve it — each segment NFC and trimmed (drive-local's
    split_path) — absolute, no empty, '.', '..' or backslash segment, and never the drive's root."""
    if not isinstance(folder, str) or not folder.startswith("/") or "\\" in folder or "\x00" in folder:
        raise ValueError(f"folder {folder!r} must be an absolute path with no backslash")
    segs = [unicodedata.normalize("NFC", s).strip() for s in folder.strip("/").split("/")]
    if not segs or any(s in ("", ".", "..") for s in segs):
        raise ValueError(f"folder {folder!r} is not a clean path below the drive's root")
    return "/" + "/".join(segs)


_SLOT = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_REMOTE_KEYS = {"remote", "target", "link", "nightly_utc"}
_MIRROR_KEYS = {"remote", "target", "link"}


def _plain_address(tid: str, field: str, value) -> str:
    url = str(value or "").rstrip("/")
    u = urllib.parse.urlsplit(url)
    # `@` anywhere in the authority: credentials have no place here (an empty user name passes a
    # `username` check), and an error that names the address would print them
    if u.scheme not in ("http", "https") or not u.hostname or u.query or u.fragment or "@" in u.netloc:
        raise ValueError(f"target {tid}: {field} is not a plain http(s) address")
    return url


def _link_office(tid: str, value) -> str:
    if not isinstance(value, str) or not LINK.OFFICE_RE.fullmatch(value):
        raise ValueError(f"target {tid}: link must be an office id as the link names it")
    return value


def check_target(tid: str, t) -> dict:
    """One target, validated. Raises ValueError.

    A store here: {url, connection_id, folder, append_only} (+ link: the office it is given to over the
    link, append-only always; + nightly_utc). A store on another office: {remote, target, link}
    (+ nightly_utc): the door's address, the store's own target id, the office that keeps it.

    A MIRROR (a client's office, DGO-1523): a store here may say `mirror_to: <office>` — that one linked office
    may READ it over the link, never write (the client's own backups land in it); and a store here may say
    `mirror: {remote, target, link}` — it is filled only by pulling that office's `mirror_to` target
    (mirror.py), append-only always, and no backup of this office runs into it."""
    if not _TARGET_ID.fullmatch(tid or ""):
        raise ValueError(f"target id {tid!r} must be lowercase letters, digits and dashes")
    if not isinstance(t, dict):
        raise ValueError(f"target {tid}: not an object")
    slot = t.get("nightly_utc")
    if slot is not None and not (isinstance(slot, str) and _SLOT.fullmatch(slot)):
        raise ValueError(f"target {tid}: nightly_utc must be HH:MM (UTC)")
    if "remote" in t:
        if set(t) - _REMOTE_KEYS:
            raise ValueError(f"target {tid}: a remote target has remote, target, link and nightly_utc only")
        url = _plain_address(tid, "remote", t.get("remote"))
        if urllib.parse.urlsplit(url).path not in ("", "/"):
            raise ValueError(f"target {tid}: remote is the store's door, with no path")
        store = t.get("target")
        if not isinstance(store, str) or not _TARGET_ID.fullmatch(store):
            raise ValueError(f"target {tid}: target must be the store's own target id")
        out = {"remote": url, "target": store, "link": _link_office(tid, t.get("link"))}
    else:
        url = _plain_address(tid, "url", t.get("url"))
        cid = t.get("connection_id") or ""
        if cid and not _CONN_ID.fullmatch(str(cid)):
            raise ValueError(f"target {tid}: connection_id has characters an id never has")
        ao = t.get("append_only", True)
        if not isinstance(ao, bool):
            raise ValueError(f"target {tid}: append_only must be true or false")
        out = {"url": url, "connection_id": str(cid), "folder": _clean_folder(t.get("folder")),
               "append_only": ao}
        if t.get("link") is not None:
            # given to another office: its copies are its only proof of the past, so it never deletes them;
            # and it is that office's, so this one never runs a backup into it (backup_run refuses it too)
            if ao is not True:
                raise ValueError(f"target {tid}: a target given to a linked office is append-only")
            if slot is not None:
                raise ValueError(f"target {tid}: a target given to a linked office is not this office's to schedule")
            out["link"] = _link_office(tid, t.get("link"))
        if t.get("mirror_to") is not None:
            if "link" in out:
                raise ValueError(f"target {tid}: a target given to a linked office is not also read by one")
            out["mirror_to"] = _link_office(tid, t.get("mirror_to"))
        if t.get("mirror") is not None:
            m = t.get("mirror")
            if not isinstance(m, dict) or set(m) != _MIRROR_KEYS:
                raise ValueError(f"target {tid}: mirror is {{remote, target, link}} — the office it is pulled from")
            if "link" in out or "mirror_to" in out:
                raise ValueError(f"target {tid}: a mirror is filled by its pull alone, so it is given to no office")
            if ao is not True:
                raise ValueError(f"target {tid}: a mirror is append-only: it never loses what it pulled")
            url = _plain_address(tid, "mirror.remote", m.get("remote"))
            if urllib.parse.urlsplit(url).path not in ("", "/"):
                raise ValueError(f"target {tid}: mirror.remote is the office's door, with no path")
            if not isinstance(m.get("target"), str) or not _TARGET_ID.fullmatch(m["target"]):
                raise ValueError(f"target {tid}: mirror.target must be the other office's own target id")
            out["mirror"] = {"remote": url, "target": m["target"], "link": _link_office(tid, m.get("link"))}
    if slot is not None:
        out["nightly_utc"] = slot
    return out


def targets() -> dict:
    """Every declared target, validated. A missing file is no targets; a broken one raises."""
    f = _targets_file()
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(f"{f.name} cannot be read: {e}") from e
    items = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(items, dict):
        raise ValueError(f"{f.name} has no 'targets' object")
    try:
        out = {tid: check_target(tid, t) for tid, t in items.items()}
    except ValueError as e:
        raise ValueError(f"{f.name}: {e}") from e
    # Two ids over one place would give the open one's run the append-only one's objects to delete:
    # on one account, no target's folder may equal or sit inside another's.
    seen = sorted(((t["url"], t["connection_id"], t["folder"] + "/"), tid) for tid, t in out.items()
                  if "remote" not in t)
    for (a, ta), (b, tb) in zip(seen, seen[1:]):
        if a[:2] == b[:2] and b[2].startswith(a[2]):
            raise ValueError(f"{f.name}: targets {ta} and {tb} overlap on one account ({b[2].rstrip('/')})")
    return out


# ── runs: who may call ──────────────────────────────────────────────────────────────────────────
class Busy(Exception):
    """A pull asked for a store this office's own night is forgetting/pruning now: answered 503, asked again."""


class Runs:
    """The tokens of the runs this process opened. Only a digest is kept; the token itself goes to
    the run's restic helper as a file on tmpfs (never an argv or a log), and dies with this process.
    A run is bound to the target AS IT WAS when the run opened: a target changed under a run (its
    folder, its account, append_only turned off) ends that run instead of widening it."""

    def __init__(self, clock=time.monotonic):
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}
        self._clock = clock
        self._deleting: dict[str, int] = {}     # target → this office's own nights forgetting/pruning it now

    def _read_open(self, target: str, now: float) -> bool:
        """Callers hold the lock."""
        return any(r["target"] == target and r.get("read") and r["expires"] > now and r["until"] > now
                   for r in self._runs.values())

    def begin_delete(self, target: str) -> bool:
        """Mark `target` as being forgotten/pruned by this office's own night (DGO-1517) — unless a run that only
        reads it is open (another office's pull, DGO-1523): then False and nothing marked. Atomic with
        `open(read=True)`, which refuses while the mark stands: a pull never lists what the night is deleting, and the
        night never deletes under a pull — for the whole of the helper's run, not only at its start (the reader)."""
        with self._lock:
            if self._read_open(target, self._clock()):
                return False
            self._deleting[target] = self._deleting.get(target, 0) + 1
            return True

    def end_delete(self, target: str) -> None:
        with self._lock:
            n = self._deleting.get(target, 0) - 1
            if n > 0:
                self._deleting[target] = n
            else:
                self._deleting.pop(target, None)

    def open(self, target: str, idle: float = RUN_IDLE, cap: float = RUN_MAX, link: str = "",
             read: bool = False) -> tuple[str, str]:
        """(user, token) for one run on one target, a store HERE, declared now. `link`: the office that
        opened it over the link; then every call of the run must come over that link. `read`: the run reads
        and lists, and every write or delete of it is refused (a mirror's pull, DGO-1523)."""
        spec = targets().get(target)
        if spec is None or "remote" in spec:
            raise KeyError(f"no target {target!r} is a store here")
        user, token = "run-" + secrets.token_hex(8), secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            if read and self._deleting.get(target):
                raise Busy(f"{target} is being forgotten/pruned by this office's night; a pull waits for it to end")
            self._runs[user] = {"target": target, "spec": spec, "idle": idle, "until": now + cap,
                                "digest": hashlib.sha256(token.encode()).digest(), "link": link,
                                "read": bool(read), "expires": min(now + idle, now + cap)}
        return user, token

    def close(self, user: str) -> None:
        with self._lock:
            self._runs.pop(user, None)

    def reading(self, target: str) -> bool:
        """Is a run that only reads `target` open now (another office's pull, DGO-1523)? A question for a screen or a
        test: the night itself asks `begin_delete`, which answers and marks under one lock."""
        with self._lock:
            return self._read_open(target, self._clock())

    def _run_of(self, authorization: str | None, office: str | None) -> tuple[str, dict] | None:
        """(user, run) for Basic <user:token> of an open, unexpired run, called over the link it was
        opened on (if any); None otherwise. Callers hold the lock."""
        if not authorization or not authorization[:6].lower() == "basic ":
            return None
        try:
            user, _, token = base64.b64decode(authorization[6:].strip(), validate=True).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        now = self._clock()
        for u in [u for u, r in self._runs.items() if r["expires"] <= now]:
            del self._runs[u]
        run = self._runs.get(user)
        if not run or not hmac.compare_digest(run["digest"], hashlib.sha256(token.encode()).digest()):
            return None
        # a run another office opened over the link answers only through that link's door: its token
        # used past the door (from a container here) or through another office's door is not that run
        if run.get("link") and (office or "") != run["link"]:
            return None
        return user, run

    def admits(self, authorization: str | None, target: str, office: str | None = None) -> dict | None:
        """The target as the run opened it, for Basic <user:token> of an open, unexpired run of exactly
        this target (over its own link, when it was opened over one); None otherwise. An admitted call
        keeps the run alive (up to its cap)."""
        with self._lock:
            got = self._run_of(authorization, office)
            if not got or got[1]["target"] != target:
                return None
            run = got[1]
            run["expires"] = min(self._clock() + run["idle"], run["until"])
            return {**run["spec"], "read": run["read"]}

    def close_own(self, authorization: str | None, office: str | None) -> bool:
        """Close the run whose own token this is (over its own link); False when there is none."""
        with self._lock:
            got = self._run_of(authorization, office)
            if not got:
                return False
            del self._runs[got[0]]
            return True


RUNS = Runs()


# ── the drive, through its generic HTTP API ─────────────────────────────────────────────────────
class DriveUnavailable(Exception):
    """The drive did not answer, or answered 5xx: restic retries a 503."""


class Drive:
    """The calls restic's six needs map to (apps/drive/ENGINES.md «For backup»), on one connection."""

    def __init__(self, base: str, connection_id: str = "", timeout: float = 120.0):
        self.base, self.cid, self.timeout = base.rstrip("/"), connection_id, timeout

    def _url(self, endpoint: str, query: dict) -> str:
        q = dict(query)
        if self.cid:
            q["connection_id"] = self.cid
        return f"{self.base}{endpoint}" + ("?" + urllib.parse.urlencode(q) if q else "")

    def _call(self, method: str, endpoint: str, query: dict | None = None, *, json_body=None,
              data=None, headers: dict | None = None):
        """(status, response) — the response is open; the caller reads or closes it."""
        hdrs = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url(endpoint, query or {}), data=data, method=method, headers=hdrs)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            resp = e                                      # a 4xx/5xx is an answer, read like any other
        except (urllib.error.URLError, OSError) as e:
            raise DriveUnavailable(f"drive {self.base} did not answer: {e}") from e
        status = getattr(resp, "status", None) or resp.code
        if status >= 500:
            try:
                body = resp.read(300)
            finally:
                resp.close()
            if status in (502, 503, 504):                 # the engine restarting, or a gateway: retry
                raise DriveUnavailable(f"drive answered {status}: {body[:200]!r}")
            # 500/501 (an account that cannot do paths, say) will answer the same in fifteen minutes:
            # 403 is one restic does not retry, and the sentence says why
            raise HTTPException(403, f"the files app cannot serve this target (HTTP {status}): {body[:200]!r}")
        return status, resp

    def _json(self, method, endpoint, query=None, **kw):
        status, resp = self._call(method, endpoint, query, **kw)
        try:
            body = resp.read()
        finally:
            resp.close()
        try:
            return status, json.loads(body or b"{}")
        except ValueError:
            return status, {}

    def stat(self, path: str) -> dict | None:
        """The file at `path` ({id, size, …}), or None when nothing is there: exactly 404."""
        status, js = self._json("GET", "/api/fs", {"path": path})
        if status == 404:
            return None
        if status != 200:
            raise HTTPException(502, f"drive stat answered {status}")
        return js.get("file") if js.get("kind") == "file" else None

    def folder(self, path: str) -> dict | None:
        """{id, folders: [...], files: [...]} of the folder at `path`, or None. `files` is the drive's
        first page (drive-local: up to 1000; Google: the whole folder)."""
        status, js = self._json("GET", "/api/fs", {"path": path})
        if status == 404:
            return None
        if status != 200:
            raise HTTPException(502, f"drive folder answered {status}")
        if js.get("kind") != "folder":
            return None
        return {"id": (js.get("folder") or {}).get("id") or "", "folders": js.get("folders") or [],
                "files": js.get("files") or []}

    def files(self, folder_id: str, page: int = 1000) -> list[dict]:
        """Every live file of one folder, paged. An engine that ignores the page (Google lists the
        whole folder) ends the loop the first time a page adds nothing new."""
        seen: dict[str, dict] = {}
        offset = 0
        while True:
            status, js = self._json("GET", "/api/files", {"folder": folder_id, "limit": page, "offset": offset})
            if status != 200:
                raise HTTPException(502, f"drive list answered {status}")
            batch = js.get("files") or []
            new = 0
            for f in batch:
                if f.get("id") and f["id"] not in seen:
                    seen[f["id"]] = f
                    new += 1
            if len(batch) < page or not new:
                return list(seen.values())
            offset += page

    def mkdir(self, path: str, system: str | None = None) -> None:
        status, _ = self._json("POST", "/api/fs/mkdir", json_body={"path": path, "system": system})
        if status != 200:
            raise HTTPException(502, f"drive mkdir answered {status}")

    def put_new(self, path: str, fileobj, size: int) -> int:
        """Write `fileobj` as a NEW file at `path`: 201, or 409 when the name is taken."""
        status, resp = self._call("PUT", "/api/fs/content", {"path": path, "mode": "exclusive"}, data=fileobj,
                                  headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"})
        resp.close()
        return status

    def get(self, path: str, rng: str | None):
        """(status, headers, response) of the bytes at `path`, Range passed through."""
        status, resp = self._call("GET", "/api/fs/content", {"path": path}, headers={"Range": rng} if rng else None)
        return status, resp.headers, resp

    def delete(self, file_id: str) -> bool:
        """A hard delete: to the trash, then out of it (the drive's delete acts on the trash only, and
        Google's trash counts against the account's quota)."""
        for path in ("/api/trash", "/api/delete"):
            status, js = self._json("POST", path, json_body={"ids": [file_id]})
            if status != 200:
                raise HTTPException(502, f"drive {path} answered {status}")
        if not js.get("deleted"):
            raise HTTPException(502, "the drive kept the bytes (its storage refused the delete)")
        return True


# ── the routes ──────────────────────────────────────────────────────────────────────────────────
router = APIRouter()


def _object_path(t: dict, kind: str, name: str) -> str:
    if kind == "data":
        return f"{t['folder']}/data/{name[:2]}/{name}"
    return f"{t['folder']}/{kind}/{name}"


def _where(spec: dict | None):
    """What a run is bound to: where the repository is and who may do what there. Not its time of night:
    a slot changed during a long first backup must not end it."""
    if spec is None:
        return None
    return tuple(spec.get(k) for k in ("url", "connection_id", "folder", "append_only", "link", "remote",
                                       "mirror_to", "mirror"))


def _open(request: Request, target: str) -> tuple[dict, Drive]:
    """The target and its drive, once the caller is admitted. Every route starts here.

    The token is checked FIRST, from memory: nothing about the targets file (not even that it is
    broken, nor what it says) reaches a caller who holds no run. One answer for «no such target» and
    «not your token», so probing names teaches nothing."""
    refused = HTTPException(401, "a run's token for this target is required",
                            headers={"WWW-Authenticate": 'Basic realm="restic"'})
    spec = RUNS.admits(request.headers.get("authorization"), target, request.headers.get(LINK.OFFICE_HEADER))
    if spec is None:
        raise refused
    try:
        now = targets().get(target)
    except ValueError as e:
        raise HTTPException(503, str(e)) from e
    if _where(now) != _where(spec):
        # moved, re-pointed, or append_only turned off under a running backup: that run is over
        raise HTTPException(401, "this target changed since the run opened; a new run is needed",
                            headers={"WWW-Authenticate": 'Basic realm="restic"'})
    return spec, Drive(spec["url"], spec["connection_id"])


def _writes(t: dict) -> None:
    """A run that only reads (a mirror's pull) writes and deletes nothing, not even a lock: restic's own locks are
    the source office's, and its pull never runs restic (DGO-1523)."""
    if t.get("read"):
        raise HTTPException(403, "this run reads only")


def _kind_name(kind: str, name: str | None = None) -> None:
    if kind not in KINDS or (name is not None and not _NAME.fullmatch(name)):
        raise HTTPException(404, "not an object restic writes")


async def _spool(request: Request, limit: int):
    """The request body in a temp file (memory up to 8 MiB), with its size and sha256 hex."""
    tmp = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    h, size = hashlib.sha256(), 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, "larger than any object restic writes")
            h.update(chunk)
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        raise
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) != size:
        tmp.close()
        raise HTTPException(400, f"body is {size} bytes, Content-Length said {declared}")
    tmp.seek(0)
    return tmp, size, h.hexdigest()


async def _save(request: Request, t: dict, d: Drive, path: str, must_hash: str | None) -> Response:
    tmp, size, digest = await _spool(request, MAX_OBJECT)
    with tmp:
        if must_hash is not None and digest != must_hash:
            raise HTTPException(400, "the bytes are not the object their name says (sha256 differs)")
        status = await run_in_threadpool(d.put_new, path, tmp, size)
    if status == 409:
        # A retry of a write that landed after its answer was lost (a timeout while the engine was
        # still storing) meets its own object. The name is the object's sha256 and every write through
        # here was checked against it, so the same name and size is the same object: done, not a
        # refusal restic would never retry. Anything else under that name was not written by restic.
        there = await run_in_threadpool(d.stat, path) if must_hash is not None else None
        if there is not None and int(there.get("size") or -1) == size:
            return Response(status_code=200)
        raise HTTPException(403, "an object of this name exists; restic never writes one twice")
    if status != 201:
        raise HTTPException(502, f"drive write answered {status}")
    return Response(status_code=200)


async def _head(d: Drive, path: str) -> Response:
    f = await run_in_threadpool(d.stat, path)
    if f is None:
        return Response(status_code=404)
    return Response(status_code=200, headers={"Content-Length": str(int(f.get("size") or 0))})


async def _load(request: Request, d: Drive, path: str) -> Response:
    status, hdrs, resp = await run_in_threadpool(d.get, path, request.headers.get("range"))
    if status == 404:
        resp.close()
        return Response(status_code=404)
    if status not in (200, 206):
        resp.close()
        raise HTTPException(502 if status != 416 else 416, f"drive read answered {status}")
    out = {"Content-Type": "application/octet-stream"}
    for h in ("Content-Length", "Content-Range"):
        if hdrs.get(h):
            out[h] = hdrs[h]

    def chunks():
        with resp:
            while True:
                buf = resp.read(256 * 1024)
                if not buf:
                    return
                yield buf

    return StreamingResponse(chunks(), status_code=status, headers=out)


async def _remove(t: dict, d: Drive, path: str, kind: str) -> Response:
    if t["append_only"] and kind != "locks":
        raise HTTPException(403, "this target is append-only: only a lock may be removed")
    f = await run_in_threadpool(d.stat, path)
    if f is None:
        return Response(status_code=404)
    await run_in_threadpool(d.delete, f["id"])
    return Response(status_code=200)


@router.api_route("/repo/{target}/", methods=["POST", "DELETE"])
async def repo_root(target: str, request: Request):
    """`POST ?create=true` makes the layout. Deleting a whole repository is never served."""
    t, d = _open(request, target)
    if request.method != "POST" or request.query_params.get("create") != "true":
        raise HTTPException(405, "only ?create=true is served here")
    _writes(t)
    try:
        await run_in_threadpool(make_layout, d, t["folder"])
    except DriveUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return Response(status_code=200)


def make_layout(d: "Drive", folder: str) -> None:
    """Every folder, data/00…ff included, made now and one at a time, as restic's local backend does: an engine
    that creates folders without a lock (drive-google) would otherwise get two data/ab from two packs uploaded at
    once, and a pack in the older one could be listed but never read. Each is marked, so a person cannot trash
    one from the drive's screen. A mirror's pull makes its own the same way (mirror.py)."""
    for f in [folder] + [f"{folder}/{k}" for k in KINDS] + [f"{folder}/data/{i:02x}" for i in range(256)]:
        d.mkdir(f, SYSTEM_MARK)


def list_objects(d: "Drive", folder: str, kind: str) -> list[tuple[str, int]]:
    """[(name, size)] of one kind in the repository at `folder`, sorted: only names restic could have written, each
    in the place restic's layout puts it. What /repo/<t>/<kind>/ answers, and what a mirror's pull compares."""
    top = d.folder(f"{folder}/{kind}")
    if top is None:
        return []
    # (folder id, the prefix every name in it must have): data/ is split by the first two hex of
    # the name, as restic's local layout, and a file under the wrong prefix could not be read back
    if kind == "data":
        places = [(s["id"], s["name"], None) for s in top["folders"]
                  if s.get("id") and re.fullmatch(r"[0-9a-f]{2}", s.get("name") or "")]
    else:
        # the folder's own answer already carries its files: page only when it may be cut short
        first = top["files"] if len(top["files"]) < 1000 else None
        places = [(top["id"], "", first)]
    out = {}
    for fid, prefix, known in places:
        for f in (known if known is not None else d.files(fid)):
            name = f.get("name") or ""
            if _NAME.fullmatch(name) and name.startswith(prefix):
                out[name] = int(f.get("size") or 0)
    return sorted(out.items())


@router.api_route("/repo/{target}/config", methods=["HEAD", "GET", "POST", "DELETE"])
async def repo_config(target: str, request: Request):
    t, d = _open(request, target)
    path = f"{t['folder']}/config"
    try:
        if request.method == "HEAD":
            return await _head(d, path)
        if request.method == "GET":
            return await _load(request, d, path)
        _writes(t)
        if request.method == "POST":
            return await _save(request, t, d, path, None)
        raise HTTPException(403, "a repository's config is never deleted here")
    except DriveUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.get("/repo/{target}/{kind}/")
async def repo_list(target: str, kind: str, request: Request):
    """v2 (asked by Accept): [{name, size}]; v1: [name]. Only names restic could have written."""
    t, d = _open(request, target)
    _kind_name(kind)
    try:
        items = await run_in_threadpool(list_objects, d, t["folder"], kind)
    except DriveUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if V2 in (request.headers.get("accept") or ""):
        return JSONResponse([{"name": n, "size": s} for n, s in items], media_type=V2)
    return JSONResponse([n for n, _ in items])


@router.api_route("/repo/{target}/{kind}/{name}", methods=["HEAD", "GET", "POST", "DELETE"])
async def repo_object(target: str, kind: str, name: str, request: Request):
    t, d = _open(request, target)
    _kind_name(kind, name)
    path = _object_path(t, kind, name)
    try:
        if request.method == "HEAD":
            return await _head(d, path)
        if request.method == "GET":
            return await _load(request, d, path)
        _writes(t)
        if request.method == "POST":
            return await _save(request, t, d, path, name)
        return await _remove(t, d, path, kind)
    except DriveUnavailable as e:
        raise HTTPException(503, str(e)) from e


# ── the herd store: a run opened by a linked office (DGO-1523, slice 3) ─────────────────────────
def _say(line: str) -> None:
    """One line on this service's log: why a linked office was refused. Never a token or a proof."""
    print(f"[data-management] herd store: {line}", flush=True)


@router.post("/api/repo-runs")
async def repo_runs_open(request: Request, target: str = Query(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")):
    """A run on `target` for the linked office it is given to: {user, token, exists}. Refused alike
    (401) for every reason, and the reason is logged here; a vault that does not answer is 503.

    A target this office READS to one linked office (`mirror_to`, DGO-1523) opens a run that only reads, for
    that office alone: the office that keeps our client's copy pulls it; the client gets nothing of ours."""
    refused = HTTPException(401, "this office does not open that run for the asker")
    office = request.headers.get(LINK.OFFICE_HEADER)
    try:
        spec = targets().get(target)
    except ValueError as e:
        _say(f"the targets file is broken ({e}); nothing is opened")
        raise HTTPException(503, "this office's backup targets cannot be read") from e
    if spec is None or "remote" in spec or not (spec.get("link") or spec.get("mirror_to")):
        _say(f"{office or 'a request with no door'} asked for {target}, which is given to no linked office")
        raise refused
    given, read = (spec["link"], False) if spec.get("link") else (spec["mirror_to"], True)
    try:
        who = await run_in_threadpool(LINK.verify, request.headers.get(LINK.HEADER), office, target)
    except LINK.Unavailable as e:
        _say(f"the vault did not answer, so {office}'s proof for {target} could not be checked: {e}")
        raise HTTPException(503, "this office's vault did not answer; try again") from e
    except LINK.NotProved as e:
        _say(f"{office or 'a request with no door'} for {target}: {e}")
        raise refused from e
    if who != given:
        _say(f"{who} asked for {target}, which is {'read by' if read else 'given to'} {given}")
        raise refused
    try:
        exists = await run_in_threadpool(
            lambda: Drive(spec["url"], spec["connection_id"]).stat(spec["folder"] + "/config") is not None)
    except DriveUnavailable as e:
        raise HTTPException(503, str(e)) from e
    try:
        user, token = RUNS.open(target, link=who, read=read)
    except Busy as e:
        _say(f"{who}'s pull of {target} waits: {e}")
        raise HTTPException(503, "this office is forgetting/pruning that store now; try again later") from e
    _say(f"a {'reading ' if read else ''}run on {target} opened for {who} ({user})")
    return {"user": user, "token": token, "exists": exists}


@router.delete("/api/repo-runs")
async def repo_runs_close(request: Request):
    """The run whose own token this is, closed (over the link it was opened on)."""
    if not RUNS.close_own(request.headers.get("authorization"), request.headers.get(LINK.OFFICE_HEADER)):
        raise HTTPException(401, "no open run has this token")
    return {"closed": True}
