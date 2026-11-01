"""OCR result cache — Postgres-backed (Supabase) shared cache, with a guarded local fallback.

The OCR cache used to live only as JSON files under ``.storage/ocr_cache`` keyed by
``file_hash`` (md5 of the uploaded bytes).  This module keeps the exact same
key/value contract (``file_hash`` -> the OCR result dict) but stores it in a
Postgres table ``ocr_cache`` so the results are inspectable directly in the DB and,
critically, so that **every apitools instance sees the same cache**.

──────────────────────────────────────────────────────────────────────────────────
WHY STRICT MODE EXISTS — read this before relaxing it
──────────────────────────────────────────────────────────────────────────────────
This module used to fall back to the per-instance JSON files whenever Postgres was
unreachable, logging a warning and continuing to serve. That is a *silent split
brain*: the instance keeps answering 200, writes OCR results only it can see, and
``/docExists`` answers "false" from everywhere else — so the pipeline re-OCRs
documents it has already paid Google Vision for.

MEASURED 2026-08-11: the portable instance's ssh ``-R 19118`` DB leg was dropped by a
watchdog while haproxy, seeing a healthy *traffic* leg, kept sending it 81.6% of all
requests. Result: **5,296 fallback warnings over 6 hours and 1,171 orphaned OCR
results** in ``~/apitools-storage/ocr_cache/*.json`` that the rest of the estate could
not see. Nothing alerted, because nothing failed.

Note what did NOT prevent it: ``OCR_CACHE_BACKEND=postgres``. That is already the
default and was exactly the configuration running during the split — the only value
with special meaning is ``file``. Making a shared-cache outage *visible* required this
code change, not a config change.

Strict mode turns that silent divergence into a **503**, which:
  * haproxy's ``be_split``/``be_localfile`` already list in ``retry-on``, so the
    request is transparently redispatched to the peer instance that CAN reach the
    shared cache — the caller usually never sees an error at all;
  * ``/readyz`` reflects, so haproxy's health check marks the split instance DOWN and
    stops sending it traffic within ``fall × inter`` (6s for the remote);
  * shows up as a 5xx in the counters, so the outage is detectable at all.

Configuration:
  ``OCR_CACHE_BACKEND``   ``postgres`` (default) | ``file`` (force the legacy local cache)
  ``OCR_CACHE_STRICT``    ``1`` (default) — a shared-cache error raises OcrCacheUnavailable.
                          ``0`` restores the pre-2026-08-11 silent local fallback.
                          Strict only engages when a Postgres DSN is actually configured,
                          so unit tests and standalone dev (no DB) keep the file backend.
  ``OCR_CACHE_READINESS`` ``1`` (default) — ``/readyz`` reports shared-cache reachability.
  ``OCR_CACHE_HEALTH_FILE``  cross-worker health marker (default ``/dev/shm/…``); see below.
  ``OCR_CACHE_PROBE_TTL``    seconds an active probe result is reused (default 15).

Public interface (kept identical to the old OcrProcessor helpers so callers are a
true drop-in):
    load(file_hash, cache_folder) -> dict | None
    save(file_hash, ocr_dict, cache_folder) -> None
"""
import json
import os
import tempfile
import threading
import time
from json import JSONDecodeError

from src.utils.logging_config import get_logger

logger = get_logger('apitools.ocr_cache')


class OcrCacheUnavailable(RuntimeError):
    """The SHARED OCR cache is unreachable and strict mode forbids diverging locally.

    Raised instead of writing a per-instance JSON file that no other instance can see.
    The API layer maps this to 503 so haproxy retries the peer (see src/api/__init__.py)."""


def _flag(name, default):
    return os.getenv(name, default).strip().lower() not in ('0', 'false', 'no', 'off', '')


_BACKEND = os.getenv("OCR_CACHE_BACKEND", "postgres").strip().lower()
_STRICT_REQUESTED = _flag("OCR_CACHE_STRICT", "1")
_READINESS = _flag("OCR_CACHE_READINESS", "1")
_PROBE_TTL = float(os.getenv("OCR_CACHE_PROBE_TTL", "15"))

# Create the table lazily, once per process.
_table_ready = False

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS ocr_cache (
  file_hash  TEXT PRIMARY KEY,
  ocr_json   JSONB NOT NULL,
  ocr_engine TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
)
"""


# ── cross-worker health marker ───────────────────────────────────────────────
# gunicorn runs `sync` workers with preload_app=False, so every worker has its OWN
# copy of this module's globals. A health check lands on ONE arbitrary worker, so
# per-process state would report "fine" from a worker that has not touched the DB
# since the outage began. The shared-cache verdict therefore lives in a tiny file on
# /dev/shm, which is already the gunicorn worker_tmp_dir: tmpfs, shared by every
# worker in the container, and physically incapable of the blocking-on-a-hung-mount
# failure that keeps `/health` out of the haproxy check.

def _default_health_file():
    for base in ('/dev/shm', tempfile.gettempdir()):
        if os.path.isdir(base) and os.access(base, os.W_OK):
            return os.path.join(base, 'apitools_shared_cache.state')
    return os.path.join(tempfile.gettempdir(), 'apitools_shared_cache.state')


_HEALTH_FILE = os.getenv("OCR_CACHE_HEALTH_FILE") or _default_health_file()
_HEALTH_MIN_WRITE_S = 5.0          # rate-limit unchanged-state rewrites
_LOCAL_HEALTH = {'ok': None, 'ts': 0.0, 'written': 0.0}
_HEALTH_LOCK = threading.Lock()

# Per-request marker so the API layer can turn a shared-cache outage into a 503
# without every route having to learn about this module. One request per thread
# under sync workers, so a thread-local is exactly the right scope.
_TL = threading.local()


def _note(ok, err=None):
    """Record the shared cache's reachability. Cheap: writes only on state change
    or every _HEALTH_MIN_WRITE_S, so the hot path is a couple of comparisons."""
    now = time.time()
    with _HEALTH_LOCK:
        changed = _LOCAL_HEALTH['ok'] is not ok
        _LOCAL_HEALTH['ok'] = ok
        _LOCAL_HEALTH['ts'] = now
        if not changed and (now - _LOCAL_HEALTH['written']) < _HEALTH_MIN_WRITE_S:
            return
        _LOCAL_HEALTH['written'] = now
    payload = {'ok': bool(ok), 'ts': now, 'pid': os.getpid(),
               'err': (str(err)[:300] if err else None)}
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_HEALTH_FILE), prefix='.schs.')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        os.replace(tmp, _HEALTH_FILE)
    except Exception:  # noqa: BLE001 — health bookkeeping must never break a request
        pass
    if changed:
        (logger.error if not ok else logger.info)(
            "shared OCR cache %s%s", 'UNREACHABLE' if not ok else 'reachable again',
            f": {err}" if err else "")


def _read_health():
    try:
        with open(_HEALTH_FILE, 'r', encoding='utf-8') as f:
            rec = json.load(f)
        if isinstance(rec, dict) and 'ok' in rec:
            return rec
    except Exception:  # noqa: BLE001
        pass
    return None


def failed_this_request():
    """True if this request already hit a shared-cache outage (and cleared for reuse)."""
    v = getattr(_TL, 'failed', None)
    _TL.failed = None
    return v is not None


def begin_request():
    _TL.failed = None


# ── backend selection ────────────────────────────────────────────────────────

def _pg_configured():
    """True when a Postgres DSN is actually configured for this process.

    Distinguishes 'the shared DB is DOWN' (an incident) from 'there is no shared DB'
    (unit tests / standalone dev), so strict mode cannot break the latter."""
    try:
        from src.doc_data import db
        return db.dsn_configured()
    except Exception:  # noqa: BLE001
        return False


def _strict():
    return _STRICT_REQUESTED and _BACKEND != "file" and _pg_configured()


def _fail(op, file_hash, err):
    """Strict-mode failure: mark the instance unhealthy and refuse to diverge."""
    _note(False, err)
    _TL.failed = err
    raise OcrCacheUnavailable(
        f"shared OCR cache unreachable on {op} for {file_hash}: {err}")


def _pg_enabled():
    """True when the Postgres backend is requested *and* reachable.

    In strict mode an unreachable-but-configured Postgres raises rather than
    silently selecting the per-instance file cache."""
    if _BACKEND == "file":
        return False
    try:
        from src.doc_data import db
        ok = db.is_postgres()
        if ok:
            return True
        # A configured DSN that resolves to the SQLite dev fallback should never
        # happen in the deployment; treat it as a shared-cache failure.
        if _strict():
            _fail("backend-select", "-", "postgres configured but not active")
        return False
    except OcrCacheUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — any resolve/connect failure
        if _strict():
            _fail("connect", "-", e)
        logger.warning(f"OCR cache: Postgres unavailable, using file fallback: {e}")
        return False


def _ensure_table(cur):
    global _table_ready
    if _table_ready:
        return
    cur.run(CREATE_SQL)
    _table_ready = True


# ── Postgres backend ─────────────────────────────────────────────────────────

def _pg_load(file_hash):
    from src.doc_data.db import Cursor
    with Cursor() as cur:
        _ensure_table(cur)
        row = cur.run(
            "SELECT ocr_json FROM ocr_cache WHERE file_hash = %s", (file_hash,)
        ).one()
    if not row:
        return None
    val = row.get('ocr_json')
    # psycopg2 auto-decodes JSONB to dict; SQLite fallback returns a JSON string.
    if isinstance(val, (str, bytes, bytearray)):
        val = json.loads(val)
    return val


def _jsonb_safe(ocr_dict):
    """Serialise an OCR result to JSON text Postgres will actually accept.

    POSTGRES CANNOT STORE \\u0000 IN jsonb (or in text at all) — `unsupported Unicode
    escape sequence / \\u0000 cannot be converted to text`. Some OCR output genuinely
    contains NUL: it comes out of PDF text-layer extraction on documents with embedded
    NULs in their font/ToUnicode tables, and Google Vision occasionally emits it too.

    Discovered 2026-08-11 while backfilling the orphaned cache files: the INSERT failed
    on real production documents. This matters far more under the strict guard than it
    did before. Previously such a document quietly took the local-file fallback and
    became an invisible orphan — one of the SOURCES of the orphan set, independent of the
    tunnel outage. Under strict mode the same document would instead 503 forever, on
    BOTH instances, because it is a property of the document and not of the machine.
    Stripping NUL is lossless for every downstream consumer: it is not a character any
    OCR text, query or geometry has meaning for.

    Done on the serialised text rather than by walking the dict because json.dumps always
    escapes NUL as the literal 6 characters \\u0000 regardless of ensure_ascii, so this is
    one linear pass instead of a recursive rebuild of a structure with thousands of nodes."""
    return json.dumps(ocr_dict, ensure_ascii=False).replace('\\u0000', '')


def _pg_save(file_hash, ocr_dict):
    from src.doc_data.db import Cursor
    engine = ocr_dict.get('ocr_engine') if isinstance(ocr_dict, dict) else None
    with Cursor() as cur:
        _ensure_table(cur)
        # %s::jsonb, not a dict param: the value is pre-serialised text (see _jsonb_safe),
        # so it needs an explicit cast to reach a jsonb column. _pg_save only ever runs on
        # Postgres — _pg_enabled() gates it — so the SQLite dialect rewrite never sees this.
        cur.run(
            "INSERT INTO ocr_cache (file_hash, ocr_json, ocr_engine, updated_at) "
            "VALUES (%s, %s::jsonb, %s, now()) "
            "ON CONFLICT (file_hash) DO UPDATE SET "
            "ocr_json = EXCLUDED.ocr_json, "
            "ocr_engine = EXCLUDED.ocr_engine, "
            "updated_at = now()",
            (file_hash, _jsonb_safe(ocr_dict), engine),
        )


# ── legacy local-file backend (unchanged behavior) ───────────────────────────

def _file_save(file_hash, file_ocr, cache_folder):
    """Save OCR results to a cache file atomically (temp file -> os.replace)."""
    cache_file_path = os.path.join(cache_folder, f"{file_hash}.json")
    fd, tmp_path = tempfile.mkstemp(
        dir=cache_folder, prefix=f"{file_hash}.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(file_ocr, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, cache_file_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _file_load(file_hash, cache_folder):
    """Load OCR results from a cache file, recovering from trailing junk."""
    cache_file_path = os.path.join(cache_folder, f"{file_hash}.json")
    if not os.path.exists(cache_file_path):
        return None
    try:
        with open(cache_file_path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except JSONDecodeError as e:
        try:
            with open(cache_file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            decoder = json.JSONDecoder()
            obj, end = decoder.raw_decode(raw)
            if end < len(raw):
                logger.warning(
                    f"Trailing content detected in cache {file_hash}.json; "
                    f"auto-fixing (end at {end}, size {len(raw)})."
                )
            _file_save(file_hash, obj, cache_folder)
            return obj
        except Exception as e2:  # noqa: BLE001
            logger.warning(
                f"Failed to decode JSON for file {file_hash}: {e} and recovery failed: {e2}"
            )
            return None


# ── readiness ────────────────────────────────────────────────────────────────

def probe(timeout=3.0):
    """Bounded, independent reachability check of the SHARED cache.

    Deliberately opens its OWN short-lived connection instead of borrowing the
    module-global one: doc_data.db serialises every statement behind a process lock,
    so a health check that took that lock would block behind an in-flight
    documentJsonQuery — i.e. it would report the app unhealthy exactly when it is
    merely busy, which is the failure mode the gunicorn health sidecar exists to avoid."""
    from src.doc_data import db
    return db.ping(timeout=timeout)


def readiness():
    """(ok: bool, detail: dict) — is the shared OCR cache usable from this instance?

    Fast path is a read of the tmpfs marker written by real traffic. An active probe
    only runs when no traffic has exercised the cache recently, and its result is
    shared through the same marker so all workers rate-limit together."""
    if not _READINESS or _BACKEND == "file" or not _pg_configured():
        return True, {'shared_cache': 'not_required', 'backend': _BACKEND}
    rec = _read_health()
    now = time.time()
    if rec and (now - float(rec.get('ts') or 0)) <= _PROBE_TTL:
        return bool(rec.get('ok')), {
            'shared_cache': 'ok' if rec.get('ok') else 'unreachable',
            'source': 'observed', 'age_s': round(now - float(rec.get('ts') or 0), 2),
            'error': rec.get('err'),
        }
    try:
        probe()
        _note(True)
        return True, {'shared_cache': 'ok', 'source': 'probe'}
    except Exception as e:  # noqa: BLE001
        _note(False, e)
        return False, {'shared_cache': 'unreachable', 'source': 'probe',
                       'error': str(e)[:300]}


def status():
    """Diagnostics for /readyz and the drift checker."""
    ok, detail = readiness()
    detail.update({'backend': _BACKEND, 'strict': _strict(),
                   'strict_requested': _STRICT_REQUESTED,
                   'dsn_configured': _pg_configured()})
    return ok, detail


# ── public API ───────────────────────────────────────────────────────────────

def load(file_hash, cache_folder):
    """Return the cached OCR dict for *file_hash*, or None on a miss.

    Strict mode raises OcrCacheUnavailable rather than reading the per-instance file
    cache: a miss caused by an unreachable shared cache would trigger a redundant
    Google Vision call whose result then could not be persisted anywhere shared."""
    if _pg_enabled():
        try:
            result = _pg_load(file_hash)
            _note(True)
            logger.debug(
                f"OCR cache (postgres) {'HIT' if result is not None else 'MISS'} for {file_hash}"
            )
            return result
        except Exception as e:  # noqa: BLE001
            if _strict():
                _fail("load", file_hash, e)
            _note(False, e)
            logger.warning(f"OCR cache PG load failed for {file_hash}; file fallback: {e}")
    return _file_load(file_hash, cache_folder)


def save(file_hash, ocr_dict, cache_folder):
    """Store *ocr_dict* under *file_hash*.

    Strict mode raises OcrCacheUnavailable rather than writing a JSON file only this
    instance can see — see the module docstring for the 6-hour incident that is."""
    if _pg_enabled():
        try:
            _pg_save(file_hash, ocr_dict)
            _note(True)
            logger.debug(f"OCR cache (postgres) stored {file_hash}")
            return
        except Exception as e:  # noqa: BLE001
            if _strict():
                _fail("save", file_hash, e)
            _note(False, e)
            logger.warning(f"OCR cache PG save failed for {file_hash}; file fallback: {e}")
    _file_save(file_hash, ocr_dict, cache_folder)
