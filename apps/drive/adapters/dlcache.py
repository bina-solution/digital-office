"""adapters.dlcache — a CONTENT-ADDRESSED cache for canonical `download` bytes.

WHY THIS EXISTS. Measured on the live stack 2026-08-10, one hour of the drive access log:
1 214 `POST /download` calls served exactly 100 distinct files — 91.8 % of every download was a
re-fetch of bytes the service had already handed out, 637 MB on the wire for 42 MB of unique
content, and the worst single file was fetched 112 times. That is not a caller bug to be fixed in
one workflow: `indoxV2UploadApiTools01` is invoked from eleven different places (BaseDocEx01, the
Figure*/Query* lanes, the Actions lanes), each one re-reads the SAME source document, and the
short-circuit that was supposed to prevent it (`Check HASH` -> apitools `/docExists`) is keyed on
`API_TOOLS_ID`, which is `md5(file_content)` — a value nothing can know until AFTER the bytes have
been downloaded. It is NULL for 5 956 of the 6 785 rows in the TO_EXTRACT queue, and n8n's Switch
then routes those to a branch with no existence check at all. The check can only ever suppress the
SECOND pass over a document, never the ten concurrent calls inside the first one.

So the de-duplication belongs HERE, at the layer that actually owns the bytes, keyed on something
knowable BEFORE the transfer.

WHY THIS CANNOT SERVE THE WRONG FILE — the property that mattered most in review, because a cache
that silently misfiles a client's document is far worse than the waste it removes:

  * The key is Google's OWN `md5Checksum` for the file, read fresh from the Drive metadata on
    EVERY request. `op_download` already made that metadata call to decide export-vs-media, so
    this costs no extra round trip — only two more fields in the projection.
  * Because the key IS the content digest, "stale" is not a reachable state. If the document in
    Drive is edited, Drive reports a different md5, that is a different key, and the entry for it
    does not exist — a miss, and a real download. There is no TTL to tune and no invalidation to
    get wrong, because nothing is ever keyed on identity (a file id) that can outlive its content.
  * Bytes are verified against the key TWICE — after writing (a partial or corrupted transfer is
    discarded, never published) and again before serving (an entry whose digest no longer matches
    its name is deleted and treated as a miss). A hit therefore proves, not assumes, that the
    caller receives byte-for-byte what Drive would have sent.
  * Google-NATIVE documents (Docs/Sheets/Slides) have no md5Checksum at any projection — Drive
    does not compute one — and they are EXPORTED rather than downloaded, so the bytes are a
    rendering, not the stored file. Those are never cached. No key, no entry, no guess.

Concurrency: two gunicorn workers x six threads share this directory. Writes land on a unique
temp file and are published with `os.replace`, which is atomic, so a reader never observes a
partial entry. Two racing misses for one key both download and both publish; the content is
identical by construction, so the race is benign.
"""
import errno
import hashlib
import json
import os
import re
import tempfile
import threading

_CHUNK = 65536
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _env_int(name, default):
    try:
        return int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


ROOT = os.getenv("DRIVE_DLCACHE_DIR") or "/data/.dlcache"
# Total on-disk budget. The volume also holds active.json and the extension registry, so this
# stays a hard ceiling with room to spare rather than "whatever is free".
MAX_BYTES = _env_int("DRIVE_DLCACHE_MAX_BYTES", 2 * 1024 ** 3)
# Per-entry ceiling. The container runs under a 384M memory limit; nothing here buffers a whole
# file (both paths stream in 64K chunks), but a single outsized document would still evict the
# entire working set for one entry that is unlikely to repeat.
MAX_FILE_BYTES = _env_int("DRIVE_DLCACHE_MAX_FILE_BYTES", 64 * 1024 ** 2)
ENABLED = str(os.getenv("DRIVE_DLCACHE", "1")).strip().lower() not in ("0", "false", "no", "off")

_evict_lock = threading.Lock()

# Observability: a counter pair the /healthz-adjacent surface can print. Per-worker and
# non-authoritative — the access log remains the measurement of record.
STATS = {"hit": 0, "miss": 0, "store": 0, "reject": 0, "evict": 0}


def _blob(key):
    return os.path.join(ROOT, key[:2], key)


def _side(key):
    return _blob(key) + ".json"


def usable(key):
    """A key is usable only if it is a real md5 hex digest. Anything else (None for a Google-native
    export, an empty string, a provider that reports some other digest form) means NO CACHING —
    never a fallback key derived from the file id, which is exactly the identity-keyed mistake this
    module exists to avoid."""
    return bool(ENABLED and key and _HEX32.match(str(key).strip().lower()))


def _digest_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for part in iter(lambda: fh.read(_CHUNK), b""):
            h.update(part)
    return h.hexdigest()


def _drop(key):
    for p in (_blob(key), _side(key)):
        try:
            os.unlink(p)
        except OSError:
            pass


def get(key):
    """(size, content_type) for a VERIFIED hit, or None.

    The digest is recomputed from disk before a single byte is served. That is one extra sequential
    read of a file the page cache is almost certainly already holding (these are ~450 KB scans),
    and it is what turns "the filename says it is this content" into "this IS the content".
    """
    if not usable(key):
        return None
    key = str(key).strip().lower()
    path = _blob(key)
    try:
        size = os.path.getsize(path)
    except OSError:
        STATS["miss"] += 1
        return None
    try:
        if _digest_file(path) != key:
            # Corrupted or truncated on disk. Treat as a miss AND remove it, so a bad entry can
            # never be served and never lingers to be re-checked on every subsequent request.
            _drop(key)
            STATS["reject"] += 1
            return None
    except OSError:
        STATS["miss"] += 1
        return None
    ctype = None
    try:
        with open(_side(key), "r", encoding="utf-8") as fh:
            ctype = (json.load(fh) or {}).get("content_type")
    except (OSError, ValueError):
        ctype = None
    # Mark the entry as freshly used; eviction is least-recently-used by mtime.
    try:
        os.utime(path, None)
    except OSError:
        pass
    STATS["hit"] += 1
    return size, ctype


def stream(key):
    """Yield a verified entry's bytes. Only call after get() returned a hit."""
    with open(_blob(key), "rb") as fh:
        for part in iter(lambda: fh.read(_CHUNK), b""):
            yield part


def tee(key, chunks, content_type=None, expect_size=None):
    """Pass `chunks` through to the caller while capturing them for the cache.

    The entry is published only if the stream completed AND its digest equals the key, so an
    aborted or truncated transfer leaves nothing behind to be served later. If anything about the
    capture fails, the bytes still reach the caller — caching is an optimisation and must never be
    able to break a download.
    """
    if not usable(key):
        yield from chunks
        return
    key = str(key).strip().lower()
    if expect_size is not None and expect_size > MAX_FILE_BYTES:
        yield from chunks
        return

    try:
        os.makedirs(os.path.dirname(_blob(key)), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_blob(key)), suffix=".part")
    except OSError:
        yield from chunks
        return

    h = hashlib.md5()
    total = 0
    ok = False
    try:
        with os.fdopen(fd, "wb") as out:
            for part in chunks:
                yield part
                if total <= MAX_FILE_BYTES:
                    out.write(part)
                    h.update(part)
                    total += len(part)
        ok = total <= MAX_FILE_BYTES and h.hexdigest() == key
    except Exception:
        # Includes GeneratorExit when the client disconnects mid-stream. Never publish.
        ok = False
        raise
    finally:
        if ok:
            try:
                os.replace(tmp, _blob(key))
                with open(_side(key), "w", encoding="utf-8") as fh:
                    json.dump({"content_type": content_type, "size": total}, fh)
                STATS["store"] += 1
                _evict()
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        else:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _walk():
    for base, _dirs, files in os.walk(ROOT):
        for name in files:
            if name.endswith(".part") or name.endswith(".json"):
                continue
            p = os.path.join(base, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            yield p, st.st_size, st.st_mtime


def _evict():
    """Keep the directory under budget, least-recently-used first. Only one thread prunes at a
    time; a concurrent caller simply skips (the next store will prune if it is still needed)."""
    if not _evict_lock.acquire(blocking=False):
        return
    try:
        entries = list(_walk())
        total = sum(sz for _p, sz, _m in entries)
        if total <= MAX_BYTES:
            return
        target = int(MAX_BYTES * 0.9)
        for path, size, _mtime in sorted(entries, key=lambda e: e[2]):
            if total <= target:
                break
            try:
                os.unlink(path)
                try:
                    os.unlink(path + ".json")
                except OSError:
                    pass
                total -= size
                STATS["evict"] += 1
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    continue
    finally:
        _evict_lock.release()
