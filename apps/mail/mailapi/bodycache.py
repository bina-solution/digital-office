"""bodycache — parsed messages on the /data volume, so an INDOX-touched message opens without IMAP.

RELEASE-DECISIONS N11 ("a body cache filled by the sync deliveries, mailapi-side on its /data
volume, keyed by gmail id"). Measured before it existed (§2.7): opening one message cost
NOOP + SELECT + SEARCH + 2 FETCH on a lock shared with 300 s sync gets, and there was no cache at
any level. Every sync delivery already downloads the whole RFC822 blob of the message it files
(``GmailBackend.message`` with ``attachments=true``) and then parses it — that parsed result is what
this module keeps, so the reader's ``meta=true`` open of the same message is a file read.

WHAT IS STORED — the immutable parts of a message only:
  headers (from/to/subject/date/ids), body_text, body_html, attachments as
  ``[{filename, mimeType, size, content_id}]``. NEVER the attachment bytes (``data_base64`` is
  stripped at the door), and never a message larger than ``max_entry_bytes`` once serialised.
Labels are the one field of a message that changes, so the entry keeps the labels seen at cache
time only as a fallback; the read path refreshes them live when that is cheap (app.py).

KEY — ``<namespace>/<gmail hex id>.json``. The gmail hex id is the message identity every caller
speaks (X-GM-MSGID; the same value the Gmail API returns as ``id``), stable for the life of the
message and independent of folder and UID. The namespace is the ACCOUNT (a digest of the mailbox
address): two registry connections into the same mailbox share one cache, two mailboxes can never
collide, and the local backend's ids (a hex INBOX uid, identical in every mailbox) could never be
mistaken for a Gmail id even if it were ever cached here.

BOUND — count AND bytes (``MAIL_BODY_CACHE_MAX_COUNT``, ``MAIL_BODY_CACHE_MAX_MB``). When either is
exceeded after a write, the oldest entries by mtime are removed until the cache is under 90% of both
(hysteresis, so a full cache does not evict on every single write). Totals are kept in memory and
re-derived from a directory walk on first use and after every ``RESCAN_EVERY`` writes, so a volume
that was pruned by hand, or shared with an earlier process, converges rather than drifting.

INVALIDATION — none is needed for the content (a Gmail message's bytes never change; a message that
was deleted upstream still opens from here, marked ``cached: true`` with its ``cached_at``, which is
the honest answer for "what did the sync file"), and the labels are refreshed live by the caller.
``put`` always overwrites, so a full fetch supersedes a metadata-only entry of the same message.

Writes are atomic (temp file + ``os.replace``), the same pattern options.py uses, and every failure
is swallowed: a cache that cannot write must degrade to "no cache", never to a failed delivery.
"""
import json
import os
import re
import threading
import time
import hashlib

CACHE_DIR = os.environ.get("MAIL_BODY_CACHE_DIR", "/data/bodycache")
MAX_COUNT = int(os.environ.get("MAIL_BODY_CACHE_MAX_COUNT", "20000"))
MAX_BYTES = int(float(os.environ.get("MAIL_BODY_CACHE_MAX_MB", "256")) * 1024 * 1024)
MAX_ENTRY_BYTES = int(float(os.environ.get("MAIL_BODY_CACHE_MAX_ENTRY_KB", "1024")) * 1024)
RESCAN_EVERY = 500

_GID = re.compile(r"^[0-9a-f]{1,32}$")
_VERSION = 1

# The fields of a rendered message that are immutable and therefore cacheable. `labels` is kept
# too, but as the labels AT CACHE TIME — the reader marks them stale unless it refreshed them.
_MESSAGE_FIELDS = ("uid", "id", "gm_msgid", "gm_thrid", "threadId", "from", "to", "subject",
                   "date", "labels", "body_text", "body_html")
_ATTACHMENT_FIELDS = ("filename", "mimeType", "size", "content_id")


def namespace_for(account):
    """Filesystem-safe, non-reversible directory name for one mailbox address."""
    return hashlib.sha1(str(account or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def strip_message(msg):
    """The cacheable projection of a rendered message: known fields only, attachment META only.
    Never mutates its input, never returns attachment bytes."""
    out = {k: msg.get(k) for k in _MESSAGE_FIELDS if k in msg}
    atts = []
    for a in msg.get("attachments") or []:
        if isinstance(a, dict):
            atts.append({k: a.get(k) for k in _ATTACHMENT_FIELDS if k in a})
    out["attachments"] = atts
    return out


class BodyCache:
    def __init__(self, root=None, max_count=None, max_bytes=None, max_entry_bytes=None):
        self.root = root or CACHE_DIR
        self.max_count = MAX_COUNT if max_count is None else int(max_count)
        self.max_bytes = MAX_BYTES if max_bytes is None else int(max_bytes)
        self.max_entry_bytes = MAX_ENTRY_BYTES if max_entry_bytes is None else int(max_entry_bytes)
        self._lock = threading.Lock()
        self._count = None          # None = not yet derived from disk
        self._bytes = 0
        self._writes_since_scan = 0
        self.hits = 0
        self.misses = 0
        self.evicted = 0

    # ── paths ──────────────────────────────────────────────────────────────────
    def path(self, account, gid):
        gid = str(gid or "").strip().lower()
        if not _GID.match(gid):
            return None
        return os.path.join(self.root, namespace_for(account), gid + ".json")

    # ── reads ──────────────────────────────────────────────────────────────────
    def get(self, account, gid):
        """The cached entry ``{"v", "cached_at", "source", "message": {...}}`` or None."""
        p = self.path(account, gid)
        if not p:
            return None
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            self.misses += 1
            return None
        if not isinstance(d, dict) or not isinstance(d.get("message"), dict):
            self.misses += 1
            return None
        self.hits += 1
        return d

    # ── writes ─────────────────────────────────────────────────────────────────
    def put(self, account, gid, message, source="full"):
        """Store the cacheable projection of `message`. Returns True when written. Never raises."""
        p = self.path(account, gid)
        if not p or not isinstance(message, dict):
            return False
        try:
            entry = {"v": _VERSION, "cached_at": int(time.time()), "source": source,
                     "message": strip_message(message)}
            blob = json.dumps(entry, ensure_ascii=False).encode("utf-8")
            if len(blob) > self.max_entry_bytes:
                return False
            with self._lock:
                self._ensure_totals()
                os.makedirs(os.path.dirname(p), exist_ok=True)
                old = 0
                try:
                    old = os.stat(p).st_size
                except OSError:
                    pass
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(blob)
                os.replace(tmp, p)
                if old:
                    self._bytes += len(blob) - old
                else:
                    self._count += 1
                    self._bytes += len(blob)
                self._writes_since_scan += 1
                if self._writes_since_scan >= RESCAN_EVERY:
                    self._scan()
                self._evict_locked()
            return True
        except Exception:
            return False

    # ── bounds ─────────────────────────────────────────────────────────────────
    def _entries(self):
        """Every (path, mtime, size) under the root. Only *.json — a stranded .tmp is skipped."""
        out = []
        try:
            for ns in os.scandir(self.root):
                if not ns.is_dir():
                    continue
                for e in os.scandir(ns.path):
                    if not e.name.endswith(".json"):
                        continue
                    try:
                        st = e.stat()
                    except OSError:
                        continue
                    out.append((e.path, st.st_mtime, st.st_size))
        except OSError:
            pass
        return out

    def _scan(self):
        rows = self._entries()
        self._count = len(rows)
        self._bytes = sum(r[2] for r in rows)
        self._writes_since_scan = 0

    def _ensure_totals(self):
        if self._count is None:
            self._scan()

    def _evict_locked(self):
        if self._count <= self.max_count and self._bytes <= self.max_bytes:
            return 0
        rows = sorted(self._entries(), key=lambda r: r[1])       # oldest first
        target_count = int(self.max_count * 0.9)
        target_bytes = int(self.max_bytes * 0.9)
        count, size = len(rows), sum(r[2] for r in rows)
        n = 0
        for p, _mtime, sz in rows:
            if count <= target_count and size <= target_bytes:
                break
            try:
                os.unlink(p)
                count -= 1
                size -= sz
                n += 1
            except OSError:
                pass
        self._count, self._bytes = count, size
        self.evicted += n
        return n

    def evict(self):
        """Apply the bounds now (exposed for /stats and tests)."""
        with self._lock:
            self._ensure_totals()
            return self._evict_locked()

    def stats(self):
        with self._lock:
            self._ensure_totals()
            return {"dir": self.root, "count": self._count, "bytes": self._bytes,
                    "max_count": self.max_count, "max_bytes": self.max_bytes,
                    "hits": self.hits, "misses": self.misses, "evicted": self.evicted}


_shared = None
_shared_lock = threading.Lock()


def shared():
    """The process-wide cache (one directory, one set of totals) every backend writes into."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = BodyCache()
        return _shared
