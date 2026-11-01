"""Background polling engine for active repos.

One daemon thread per Gunicorn worker is started via ``start_polling()``.
A per-repo *file lock* ensures that across multiple workers only one thread
actually runs a sync cycle at a time – the others skip and sleep.

Sync logic is intentionally shared with the HTTP ``POST /repos/<r>/sync``
endpoint so behaviour is identical whether triggered manually or
automatically.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .core.models import EventEnvelope, OrderClause, Query, RepoConfig
from .core.registry import RepoRegistry

_log = logging.getLogger(__name__)

# How long (s) to wait between full registry scans when no active repo has
# a shorter interval.
_REGISTRY_SCAN_INTERVAL = 10

# PostgREST page size for the paged full-table read below. Not a business
# choice — it only bounds how many rows move per HTTP round trip.
_FETCH_PAGE = 1000


def _fetch_all_rows(cfg: RepoConfig, repo_obj) -> list[dict]:
    """Every row of the repo, paged by offset.

    ``repo_obj.fetch_all()`` issues ONE unbounded select, which PostgREST
    silently caps at its configured ``db-max-rows`` (1000 on this stack) —
    a table past that size then has its remainder reported as ABSENT on
    every poll cycle, forever, because the snapshot below is rebuilt from
    exactly what this function returns. Paging by offset with a stable
    primary-key order is what ``_paged_select`` in the sync API already does
    for the same reason; this is that pattern applied here.
    """
    out: list[dict] = []
    offset = 0
    order = [OrderClause(col=cfg.primary_key, dir="asc")]
    while True:
        chunk = repo_obj.query(
            Query(mode="all", limit=_FETCH_PAGE, offset=offset, order=order)
        )
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < _FETCH_PAGE:
            break
        offset += _FETCH_PAGE
    return out


def sync_repo_once(
    cfg: RepoConfig,
    repo_obj,
    snapshot_dir: Path,
    producer,
) -> dict:
    """Fetch all rows, diff vs snapshot, publish events, save snapshot.

    Returns a summary dict ``{scanned, events_published, created, changed}``.
    This function is re-used by both the background poller and the manual
    HTTP sync endpoint.
    """
    current_rows = _fetch_all_rows(cfg, repo_obj)

    snapshot_path = snapshot_dir / f"{cfg.name}.json"

    prev: dict[str, dict] = {}
    if snapshot_path.exists():
        try:
            prev = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    pk = cfg.primary_key
    envelopes: list[EventEnvelope] = []
    for row in current_rows:
        pk_val = str(row.get(pk, ""))
        if not pk_val:
            continue
        old = prev.get(pk_val)
        if old is None:
            envelopes.append(
                EventEnvelope(repo=cfg.name, event_type="ROW_CREATED", row=row)
            )
        else:
            # Emit full row (matches n8n Google Sheets Trigger semantics:
            # downstream consumers reference any column directly).
            if any(old.get(k) != v for k, v in row.items()) or set(old) - set(row):
                envelopes.append(
                    EventEnvelope(
                        repo=cfg.name,
                        event_type="ROW_CHANGED",
                        row=row,
                    )
                )

    if envelopes:
        producer.publish_many(envelopes)
        producer.flush()

    # Atomic snapshot write
    new_snapshot = {
        str(row.get(pk, "")): row
        for row in current_rows
        if row.get(pk)
    }
    fd, tmp = tempfile.mkstemp(
        prefix=".snap.", suffix=".json.tmp", dir=str(snapshot_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(new_snapshot, f, ensure_ascii=False)
        os.replace(tmp, snapshot_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return {
        "scanned": len(current_rows),
        "events_published": len(envelopes),
        "created": sum(1 for e in envelopes if e.event_type == "ROW_CREATED"),
        "changed": sum(1 for e in envelopes if e.event_type == "ROW_CHANGED"),
    }


def _try_lock(lock_path: Path) -> int | None:
    """Open and try to acquire an exclusive non-blocking flock.

    Returns the file descriptor (caller must close) or None if already locked.
    """
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def _poller_loop(
    reg: RepoRegistry,
    factory: Callable,
    producer,
    stop_event: threading.Event,
) -> None:
    """Main loop – runs in a daemon thread."""
    _log.info("Incoming-documents poller started (pid=%s)", os.getpid())

    # next_poll[repo_name] = monotonic time when we should next poll it
    next_poll: dict[str, float] = {}

    while not stop_event.is_set():
        now = time.monotonic()

        try:
            all_cfgs = reg.list()
        except Exception as exc:
            _log.warning("Poller: registry read error: %s", exc)
            time.sleep(_REGISTRY_SCAN_INTERVAL)
            continue

        active_cfgs = [c for c in all_cfgs if c.active and c.kafka.enabled]
        snapshot_dir = Path(reg.path).parent / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        lock_dir = snapshot_dir / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)

        for cfg in active_cfgs:
            due = next_poll.get(cfg.name, 0.0)
            if now < due:
                continue

            lock_path = lock_dir / f"{cfg.name}.lock"
            lock_fd = _try_lock(lock_path)
            if lock_fd is None:
                # Another worker is syncing this repo right now – skip
                continue

            try:
                repo_obj = factory(cfg)
                result = sync_repo_once(cfg, repo_obj, snapshot_dir, producer)
                if result["events_published"]:
                    _log.info(
                        "Poller synced '%s': %s created, %s changed",
                        cfg.name,
                        result["created"],
                        result["changed"],
                    )
            except Exception as exc:
                _log.warning("Poller: sync failed for '%s': %s", cfg.name, exc)
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except OSError:
                    pass

            next_poll[cfg.name] = time.monotonic() + cfg.poll_interval_seconds

        stop_event.wait(timeout=_REGISTRY_SCAN_INTERVAL)

    _log.info("Incoming-documents poller stopped (pid=%s)", os.getpid())


_poller_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def start_polling(reg: RepoRegistry, factory: Callable, producer) -> None:
    """Start the background poller daemon thread (idempotent)."""
    global _poller_thread, _stop_event
    if _poller_thread is not None and _poller_thread.is_alive():
        return  # already running in this process

    _stop_event = threading.Event()
    _poller_thread = threading.Thread(
        target=_poller_loop,
        args=(reg, factory, producer, _stop_event),
        name="incoming-docs-poller",
        daemon=True,
    )
    _poller_thread.start()


def stop_polling() -> None:
    """Signal the poller to stop (used in tests / graceful shutdown)."""
    global _stop_event
    if _stop_event:
        _stop_event.set()
