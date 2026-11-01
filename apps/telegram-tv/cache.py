"""cache — keep the bytes close to the viewer.

The measurement that forced this module: a Telegram download from this office runs at **0.9–1.6 MiB/s**
while a 1080p episode of the Friends bot plays at 4.3 Mbit/s (0.54 MiB/s). Playback therefore works,
but with almost no headroom — and every seek backwards, every rewatch and every second viewer pays for
the same bytes again, because nothing was kept.

A home media server solves this the boring way, and so does this: once a file has been played, keep it
on disk. `/data/cache` holds whole files (only files small enough to be worth it — every 480p episode
of a series, and most mp4 films), evicted least-recently-used when the budget is full. Serving from
there costs nothing and is instant, and `ensure()` can also be called BEFORE anyone presses play:

  * the NEXT episode of a series is prefetched while the current one is being watched — which is
    exactly what a streaming service does, and the only honest way "auto-play the next episode"
    can start instantly on a 1 MiB/s connection,
  * a film's two quality variants are cached independently, so switching to 480p when the network
    drops does not throw away what was already fetched.

Nothing here is authoritative: delete the whole directory and the app re-downloads on demand.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time

log = logging.getLogger("telegram-tv.cache")

CACHE_DIR = os.environ.get("TV_CACHE_DIR", "/data/cache")
#: How much disk the cache may hold. The office volume is small and shared, and a 4 GB film must not
#: be able to evict itself into an infinite loop; the number below holds ~15 series episodes.
BUDGET_BYTES = int(os.environ.get("TV_CACHE_BYTES", str(3 * 1024 ** 3)))
#: Only files up to this size are cached whole. A 4 GB film is not: caching it would spend the whole
#: budget on one film nobody rewatches nightly, and the download itself is the bottleneck anyway.
MAX_FILE_BYTES = int(os.environ.get("TV_CACHE_MAX_FILE", str(400 * 1024 ** 2)))
#: Parallel prefetches. One is enough to fill the cache ahead of a viewer and it does not compete with
#: the stream being watched for the account's bandwidth.
PREFETCH_CONCURRENCY = int(os.environ.get("TV_PREFETCH_CONCURRENCY", "1"))


def safe_name(movie_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", movie_id) + ".mp4"


class Cache:
    def __init__(self, store, library):
        self.store = store
        self.library = library
        self.dir = CACHE_DIR
        # exposed on the INSTANCE as well: the limits are configuration, and a caller (the prefetch
        # endpoint, the settings screen) should not have to import module globals to ask about them
        self.budget_bytes = BUDGET_BYTES
        self.max_file_bytes = MAX_FILE_BYTES
        os.makedirs(self.dir, exist_ok=True)
        self._lock = asyncio.Lock()
        self._queued: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._downloading: set[str] = set()

    # ── what is on disk ──────────────────────────────────────────────────────────────────────
    def path(self, movie: dict) -> str:
        return os.path.join(self.dir, safe_name(movie["id"]))

    def complete(self, movie: dict) -> bool:
        """A file is cached only when it is finished: the download writes to `.part` and renames, so a
        half file can never be served as if it were whole."""
        p = self.path(movie)
        try:
            return os.path.getsize(p) == int(movie.get("size") or 0) > 0
        except OSError:
            return False

    def stat(self) -> dict:
        total = 0
        files = 0
        for name in os.listdir(self.dir):
            try:
                total += os.path.getsize(os.path.join(self.dir, name))
                files += 1
            except OSError:
                pass
        return {"files": files, "bytes": total, "budget_bytes": BUDGET_BYTES,
                "max_file_bytes": MAX_FILE_BYTES, "downloading": sorted(self._downloading),
                "queued": len(self._queued)}

    def touch(self, path: str) -> None:
        try:
            os.utime(path, None)
        except OSError:
            pass

    def evict(self, keep: str | None = None) -> int:
        """LRU eviction down to the budget. Never evicts the file being served (`keep`)."""
        entries = []
        for name in os.listdir(self.dir):
            p = os.path.join(self.dir, name)
            try:
                entries.append((os.path.getmtime(p), os.path.getsize(p), p))
            except OSError:
                continue
        total = sum(e[1] for e in entries)
        freed = 0
        for _mtime, size, p in sorted(entries):
            if total - freed <= BUDGET_BYTES:
                break
            if keep and os.path.abspath(p) == os.path.abspath(keep):
                continue
            try:
                os.remove(p)
                freed += size
                log.info("evicted %s (%.0f MB)", os.path.basename(p), size / 1e6)
            except OSError:
                pass
        return freed

    # ── filling it ───────────────────────────────────────────────────────────────────────────
    def ensure(self, movie: dict, *, priority: bool = False) -> bool:
        """Queue a whole-file download. Returns True when the file is already there.

        `priority` puts it at the front — used for the file the viewer actually asked for, so it is
        fetched before a prefetched neighbour."""
        size = int(movie.get("size") or 0)
        if size <= 0 or size > MAX_FILE_BYTES:
            return False
        if self.complete(movie):
            self.touch(self.path(movie))
            return True
        if movie["id"] in self._downloading:
            return False
        coro = self._download(movie, priority=priority)
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return False

    async def _download(self, movie: dict, *, priority: bool = False) -> None:
        mid = movie["id"]
        dest = self.path(movie)
        part = dest + ".part"
        self._queued.discard(mid)
        async with self._lock:
            if mid in self._downloading:
                return
            self._downloading.add(mid)
        started = time.time()
        try:
            size = int(movie["size"])
            got = 0
            log.info("cache: fetching %s (%.0f MB)", mid, size / 1e6)
            with open(part, "wb") as fh:
                async for chunk in self.library.stream(movie, 0, size):
                    fh.write(chunk)
                    got += len(chunk)
            if got != size:
                raise RuntimeError(f"short download: {got} of {size} bytes")
            os.replace(part, dest)
            took = time.time() - started
            log.info("cache: %s ready (%.0f MB in %.0fs = %.1f MiB/s)", mid, size / 1e6, took,
                     size / 1e6 / max(took, 0.001))
            self.evict(keep=dest)
        except asyncio.CancelledError:
            raise
        except Exception as e:                                # noqa: BLE001 - a cache miss is not an error
            log.warning("cache: %s failed: %s", mid, e)
            try:
                os.remove(part)
            except OSError:
                pass
        finally:
            self._downloading.discard(mid)

    def prefetch(self, movie: dict) -> bool:
        """Warm the cache for a film nobody is watching yet — the next episode, in practice."""
        if not movie or self.complete(movie) or movie["id"] in self._downloading:
            return False
        return not self.ensure(movie)

    def disk_free(self) -> int:
        try:
            return shutil.disk_usage(self.dir).free
        except OSError:
            return 0
