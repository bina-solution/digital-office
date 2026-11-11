"""data-management.mirror — a client office's backup, PULLED into this office's herd store (DGO-1523).

WHY A PULL. An office we set up for a company is linked to our herd ONE WAY (DGO-1636, the owner's MEET-13
rule): we use it, it sees nothing of ours. Slice 3's herd store was a push — the client's restic writing into
our store through a door of ours — which would give the client a door into our herd. So the client backs up
into a repository on its OWN files app, a target it declares `mirror_to: <our office>`, and our office pulls
that repository over the link it already has, through the client's door, in a run that can only read
(restic_store.py, /api/repo-runs, with the pair's proof as slice 3 made it). Nothing of ours is opened to the
client, and a client that is broken into cannot reach, let alone delete, the copies we keep.

WHAT IS COPIED, AND HOW IT IS BELIEVED. The repository's own files: `config`, then keys/, data/, index/ and
snapshots/. All four are LISTED first, newest-written kind first (snapshots, index, data, keys), and copied from
those lists in the other order: restic writes packs, then the index, then the snapshot, so whatever a listed
snapshot names was already written when data/ was listed — a client backing up during the pull never leaves a
snapshot here whose packs are not. (A `prune` at the source during a pull deletes packs the pull listed: fetching
one is a 404, that night's pull fails and is said, and the next night copies what the prune left — the source's
retention, DGO-1517, prunes only while no reading run of the target is open.) Never locks/. Every restic file
but `config` is named by the sha256 of its bytes: each is fetched to a spool, hashed, and written only when its
bytes are its name and its length is the one listed (pull.py's rule: nothing the other office sends is believed
before it is hashed). `config` is fetched once and must come whole; a different `config` at the source is a
different repository, and nothing more is copied until a person looks.

THE CLIENT IS NOT TRUSTED. Its door is answered as a stranger's (backup_run.Bounded): a redirect is never followed
(it would carry the run's token to any address the client names, inside our network too); every exchange — its
headers included — ends by the pull's deadline, a timer shutting the socket; an answer shorter than its
Content-Length, or of no known length, is cut, never short; a listing is read up to a size, parsed row by row in
restic_store's own shape without building a document in memory, a name listed twice with two sizes refused; a pull
has a byte budget for the night (every byte fetched counts) and the mirror a total cap, past which it stops and the
next night goes on from where it stopped; every way an answer can be cut short or malformed is a Failed with its
reason, never a stray exception.

WHAT IS NEVER DONE. Nothing in the mirror is deleted or overwritten: what the source pruned stays here, and
`forget`/`prune` on the mirror are this office's own decision (office-backup.md §3.3). Nothing at the source is
written: the run reads only, not even a lock.

THE TARGET, at the office that keeps the copy:
    {"url": <its drive>, "folder": "/גיבויים/exampleu", "append_only": true,
     "mirror": {"remote": <the client's door>, "target": <the client's own target id>, "link": "exampleu"},
     "nightly_utc": "02:30"}
and at the client:
    {"url": <its drive>, "folder": "/גיבויים/dgo", "append_only": false, "mirror_to": "hp-laptop",
     "nightly_utc": "00:30"}
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import http.client
import os
import re
import tempfile
import time

import restic_store as STORE

LIST_ORDER = ("snapshots", "index", "data", "keys")   # listed newest-written first…
ORDER = tuple(reversed(LIST_ORDER))                   # …copied so a snapshot comes after all it names
READ_TIMEOUT = 60                                     # one socket read; the deadline bounds the whole exchange
DEADLINE = float(os.environ.get("DATA_MIRROR_DEADLINE") or 2 * 3600)       # one pull, all of it (a client's
#                                       first copy of ~1.4 GB takes minutes; a slow client holds the office's one run
#                                       no longer than this, and the next night goes on from where it stopped)
BUDGET = int(os.environ.get("DATA_MIRROR_BUDGET") or 50 * 10**9)           # bytes one pull may fetch
MAX_TOTAL = int(os.environ.get("DATA_MIRROR_MAX_TOTAL") or 200 * 10**9)    # bytes one mirror may hold
LIST_MAX_BYTES = 16 << 20                             # ~180,000 rows: a repository of ~3 TB in 16 MiB packs
LIST_MAX_ROWS = 200_000
CONFIG_MAX = 64 << 10                                 # restic's config is a few hundred bytes
CHUNK = 1 << 20
#: one row as restic_store's listing writes it (JSONResponse: compact, name then size)
_ROW = re.compile(rb'\s*\{\s*"name"\s*:\s*"([0-9a-f]{64})"\s*,\s*"size"\s*:\s*(0|[1-9][0-9]{0,15})\s*\}\s*')


class Refused(Exception):
    """Nothing was copied: the pull did not start (no run, no repository at the source)."""


class Failed(Exception):
    """The pull stopped part way; what was copied is whole, and the next pull goes on from there."""


def parse_listing(body: bytes) -> list[tuple[str, int]]:
    """[(name, size)] from a v2 listing, read row by row in restic_store's shape — never a document built in memory
    (16 MiB of `{},` was 400 MiB of Python objects: the second reader). A name listed twice is one object when its
    sizes agree and a refusal when they do not. Raises Failed for anything else."""
    body = body.strip()
    if not (body.startswith(b"[") and body.endswith(b"]")):
        raise Failed("the listing is not a list")
    pos, end, rows = 1, len(body) - 1, {}
    if body[1:end].strip() == b"":
        return []
    while True:
        m = _ROW.match(body, pos, end)
        if not m:
            raise Failed(f"the listing holds a row restic never writes, at byte {pos}: {body[pos:pos + 80]!r}")
        name, size = m.group(1).decode(), int(m.group(2))
        if size > STORE.MAX_OBJECT:
            raise Failed(f"the listing names {name[:12]}… at {size} bytes, more than any object restic writes")
        if rows.get(name, size) != size:
            raise Failed(f"the listing names {name[:12]}… twice, at two sizes")
        rows[name] = size
        if len(rows) > LIST_MAX_ROWS:
            raise Failed(f"the listing holds more than {LIST_MAX_ROWS} objects")
        pos = m.end()
        if pos == end:
            return sorted(rows.items())
        if body[pos:pos + 1] != b",":
            raise Failed(f"the listing's rows are not separated as a list's are, at byte {pos}")
        pos += 1


class _Source:
    """The client's repository, read through its door with the run's token, against the pull's deadline."""

    def __init__(self, base: str, target: str, run: dict, deadline: float):
        self.base, self.target, self.deadline = base.rstrip("/"), target, deadline
        self.auth = "Basic " + base64.b64encode(f"{run['user']}:{run['token']}".encode()).decode()

    def _late(self) -> None:
        if time.monotonic() >= self.deadline:
            raise Failed(f"the pull ran past its {DEADLINE / 3600:.1f} h; what was copied is kept, and the next "
                         f"pull goes on from there")

    def _exchange(self, path: str, accept: str | None = None):
        import backup_run as BACKUP
        self._late()
        hdrs = {"Authorization": self.auth}
        if accept:
            hdrs["Accept"] = accept
        return BACKUP.Bounded(f"{self.base}/repo/{self.target}/{path}", "GET", hdrs, deadline=self.deadline,
                              read_timeout=READ_TIMEOUT)

    def _whole(self, path: str, limit: int, what: str, accept: str | None = None) -> tuple[int, bytes]:
        import backup_run as BACKUP
        try:
            with self._exchange(path, accept) as x:
                status = x.resp.status
                if status != 200:
                    return status, b""
                return status, x.read(limit)
        except BACKUP.EXCHANGE_BROKEN as e:
            self._late()
            raise Failed(f"{what} could not be read whole: {type(e).__name__}: {str(e)[:200]}") from e

    def listing(self, kind: str) -> list[tuple[str, int]]:
        status, body = self._whole(f"{kind}/", LIST_MAX_BYTES, f"the source's {kind}/ listing", accept=STORE.V2)
        if status != 200:
            raise Failed(f"the source's {kind}/ listing answered HTTP {status}")
        return parse_listing(body)

    def config(self) -> bytes | None:
        status, body = self._whole("config", CONFIG_MAX, "the source's config")
        if status == 404:
            return None
        if status != 200:
            raise Failed(f"the source's config could not be read: HTTP {status}")
        if not body:
            raise Failed("the source's config is empty: not a restic repository")
        return body

    def fetch(self, kind: str, name: str, size: int):
        """The object in a spool, checked: its bytes hash to its name and its length is the listed one."""
        import backup_run as BACKUP
        spool = tempfile.SpooledTemporaryFile(max_size=8 << 20)
        h, n = hashlib.sha256(), 0
        try:
            with self._exchange(f"{kind}/{name}") as x:
                if x.resp.status != 200:
                    raise Failed(f"{kind}/{name[:12]}… answered HTTP {x.resp.status}")
                while True:
                    self._late()
                    buf = x.resp.read1(CHUNK)
                    if not buf:
                        break
                    n += len(buf)
                    if n > size:
                        raise Failed(f"{kind}/{name[:12]}… is longer than the {size} bytes listed")
                    h.update(buf)
                    spool.write(buf)
                self._late()
        except Failed:
            spool.close()
            raise
        except BACKUP.EXCHANGE_BROKEN as e:
            spool.close()
            self._late()
            raise Failed(f"{kind}/{name[:12]}… could not be read: {type(e).__name__}: {str(e)[:200]}") from e
        except BaseException:
            spool.close()
            raise
        if h.hexdigest() != name or n != size:
            spool.close()
            raise Failed(f"{kind}/{name[:12]}… is not the object its name says ({n} bytes, sha256 "
                         f"{h.hexdigest()[:12]}…): nothing of it was written")
        spool.seek(0)
        return spool


def _object_path(folder: str, kind: str, name: str) -> str:
    return f"{folder}/data/{name[:2]}/{name}" if kind == "data" else f"{folder}/{kind}/{name}"


def pull(target: str, spec: dict, office: str, log, began=lambda: None) -> dict:
    """One pull of `spec["mirror"]` into the store here. Returns the result; raises Refused when nothing was
    started and Failed when it stopped part way (what it copied is whole). `began` is called once the source
    admitted the run and holds a repository: from then on the night's pull counts as started."""
    import backup_run as BACKUP                        # its Remote: the run asked over the link, with the proof

    m = spec["mirror"]
    remote = BACKUP.Remote({"remote": m["remote"], "target": m["target"], "link": m["link"]}, office)
    started = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.monotonic()
    try:
        run = remote.open()
    except BACKUP.Refused as e:
        raise Refused(str(e)) from e
    try:
        if not run["exists"]:
            raise Refused(f"{m['link']} has no repository in {m['target']} yet: its first backup makes it")
        began()
        return _copy(target, spec, m, _Source(m["remote"], m["target"], run, t0 + DEADLINE), started, t0, log)
    except (STORE.DriveUnavailable, STORE.HTTPException, http.client.HTTPException, OSError, ValueError) as e:
        # this office's own files app (or state dir) failed under the pull: a Failed with its reason, never a stray
        raise Failed(f"this office's files app did not take the mirror: "
                     f"{type(e).__name__}: {str(getattr(e, 'detail', e))[:200]}") from e
    finally:
        remote.close(run)


def _same_config(here, folder: str, theirs: bytes) -> bool:
    status, _, resp = here.get(f"{folder}/config", None)
    with resp:
        return status in (200, 206) and resp.read(CONFIG_MAX + 1) == theirs


def _copy(target: str, spec: dict, m: dict, src: _Source, started, t0: float, log) -> dict:
    here = STORE.Drive(spec["url"], spec["connection_id"])
    folder = spec["folder"]
    theirs = src.config()
    if theirs is None:
        raise Failed(f"{m['link']} answered that its repository exists, then had no config")
    if here.stat(f"{folder}/config") is None:
        STORE.make_layout(here, folder)
        with tempfile.SpooledTemporaryFile() as f:
            f.write(theirs)
            f.seek(0)
            status = here.put_new(f"{folder}/config", f, len(theirs))
        if status != 201:
            raise Failed(f"the mirror's config could not be written here (the drive answered {status})")
        log(f"mirror {target}: a new repository, the config of {m['link']}'s {m['target']}")
    elif not _same_config(here, folder, theirs):
        raise Failed(f"{m['link']}'s {m['target']} is not the repository this mirror holds (another config): "
                     f"nothing was copied; a person decides whether it is a new repository")
    listed = {kind: src.listing(kind) for kind in LIST_ORDER}
    have = {kind: dict(STORE.list_objects(here, folder, kind)) for kind in ORDER}
    held = sum(sum(v.values()) for v in have.values())
    copied, fetched = {}, 0
    for kind in ORDER:
        missing = [(n, s) for n, s in listed[kind] if n not in have[kind]]
        done = 0
        for name, size in missing:
            if fetched + size > BUDGET:
                raise Failed(f"the night's budget of {BUDGET / 1e9:.0f} GB is used ({done} {kind} objects copied); "
                             f"the next pull goes on from there")
            if held + size > MAX_TOTAL:
                raise Failed(f"the mirror holds {held / 1e9:.1f} GB, and its cap is {MAX_TOTAL / 1e9:.0f} GB: "
                             f"nothing more is taken until a person looks (prune, or a larger cap)")
            body = src.fetch(kind, name, size)
            fetched += size                                 # every byte fetched counts, written or not
            with body:
                status = here.put_new(_object_path(folder, kind, name), body, size)
            if status == 409:
                # a write whose answer was lost: the same name is the same bytes only at the same length
                there = here.stat(_object_path(folder, kind, name))
                if there is None or int(there.get("size") or -1) != size:
                    raise Failed(f"{kind}/{name[:12]}… exists here with other bytes: nothing overwrites it")
            elif status != 201:
                raise Failed(f"{kind}/{name[:12]}… could not be written here (the drive answered {status})")
            else:
                held += size
            done += 1
        copied[kind] = done
        # whole = every object the source listed for this kind is here now, before the next kind is copied
        lack = {n for n, _ in listed[kind]} - {n for n, _ in STORE.list_objects(here, folder, kind)}
        if lack:
            raise Failed(f"after copying, the mirror still lacks {len(lack)} {kind} objects the source listed "
                         f"(a write was lost); the next pull goes on from here")
        log(f"mirror {target}: {kind} — {done} copied, {len(listed[kind])} at the source")
    counts = {k: len(v) for k, v in listed.items()}
    result = {"target": target, "mirror_of": {"office": m["link"], "target": m["target"]},
              "started": started.isoformat(), "finished": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "seconds": round(time.monotonic() - t0, 1), "copied": copied, "objects": counts, "bytes": fetched,
              "held_bytes": held, "snapshots": counts["snapshots"], "complete": True}
    log(f"mirror {target}: {sum(copied.values())} objects, {fetched / 1e6:.1f} MB copied; "
        f"{counts['snapshots']} snapshots held; complete")
    return result
