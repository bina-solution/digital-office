"""artwork — a poster for a film that has none.

The Friends bot publishes its episodes as plain documents: no thumbnail, no poster message, nothing.
In the library they arrive as 51 correct, properly-named cards with no artwork at all — which is the
difference between "a TV app" and "a list of links", and it is not the owner's fault: Telegram simply
has no picture for that message.

The film itself is the picture. One frame, taken a little way in (the first seconds of an episode are
usually a logo or black), scaled twice: a 2:3 poster for the card and a 16:9 backdrop for the hero.
Both are cached on disk next to the poster cache, so this costs one small range read and one decode
per file, once, ever.

Nothing here invents content: the frame is the film's own, and a film whose frame cannot be read
simply keeps its placeholder card.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

log = logging.getLogger("telegram-tv.artwork")

FFMPEG = os.environ.get("TV_FFMPEG", "ffmpeg")
#: Where in the film the frame is taken, as a fraction of its length, clamped to a sane window: 12% in
#: is past the titles for a sitcom and past the cold open for a film, and never past 15 minutes.
AT = float(os.environ.get("TV_ARTWORK_AT", "0.06"))
MIN_AT, MAX_AT = 15.0, 420.0
TIMEOUT = float(os.environ.get("TV_ARTWORK_TIMEOUT", "150"))
#: How many frames may be decoded at once. Two is deliberate: this runs on four ARM cores that are
#: already serving a film, and a poster that arrives a minute late is worth more than a stutter.
CONCURRENCY = int(os.environ.get("TV_ARTWORK_CONCURRENCY", "1"))
#: How many frames may be waiting. A series is a hundred episodes; the queue is not a job system.
# Deliberately small. Each frame costs seconds to tens of seconds of ffmpeg, and the
# office runs on four cores: a queue of 240 turned "nice artwork" into 1.4 cores of
# continuous decode (measured), which starved the API that serves the very pages it was
# decorating. What is NOT queued is generated on demand when a card asks for it.
MAX_PENDING = int(os.environ.get("TV_ARTWORK_MAX_PENDING", "40"))


def _frame_time(duration: float) -> str:
    t = duration * AT if duration and duration > 0 else 90.0
    return f"{min(max(t, MIN_AT), MAX_AT):.1f}"


def safe(movie_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", movie_id)


class Artwork:
    def __init__(self, directory: str):
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)

    def poster_path(self, movie_id: str) -> str:
        return os.path.join(self.dir, safe(movie_id) + ".poster.jpg")

    def backdrop_path(self, movie_id: str) -> str:
        return os.path.join(self.dir, safe(movie_id) + ".backdrop.jpg")

    def has_poster(self, movie_id: str) -> bool:
        return os.path.exists(self.poster_path(movie_id))

    def failed(self, movie_id: str) -> bool:
        """True when a frame was ATTEMPTED and produced nothing (no video stream, unreadable file).
        Kept separate from "not generated yet": conflating the two is how a shelf ends up permanently
        grey after one unlucky attempt."""
        return os.path.exists(self.poster_path(movie_id) + ".failed")

    def mark_failed(self, movie_id: str) -> None:
        try:
            open(self.poster_path(movie_id) + ".failed", "wb").close()
        except OSError:
            pass

    async def generate(self, movie: dict, url: str, duration: float = 0.0) -> bool:
        """One decode, two images. Returns True when a poster now exists."""
        poster, backdrop = self.poster_path(movie["id"]), self.backdrop_path(movie["id"])
        if os.path.exists(poster):
            return True
        tmp_p, tmp_b = poster + ".part.jpg", backdrop + ".part.jpg"
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            # Input seek with `-noaccurate_seek`: keyframe precision is irrelevant for a still, and it
            # is the difference between reading a few hundred KB and re-reading the file's index. The
            # number that forced it: a poster request took 39 SECONDS with an accurate seek, which is
            # also long enough to hit the console's 40s proxy timeout — so artwork can never be
            # generated inside a request (see ArtworkQueue).
            "-noaccurate_seek", "-ss", _frame_time(duration), "-i", url,
            "-filter_complex",
            "[0:v]split=2[a][b];[a]scale=640:-2:flags=lanczos[p];[b]scale=1600:-2:flags=lanczos[d]",
            "-map", "[p]", "-frames:v", "1", "-q:v", "4", tmp_p,
            "-map", "[d]", "-frames:v", "1", "-q:v", "5", tmp_b,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            log.warning("artwork: timeout for %s", movie["id"])
            return False
        ok = proc.returncode == 0 and os.path.exists(tmp_p) and os.path.getsize(tmp_p) > 0
        if ok:
            os.replace(tmp_p, poster)
            if os.path.exists(tmp_b) and os.path.getsize(tmp_b) > 0:
                os.replace(tmp_b, backdrop)
            log.info("artwork: generated for %s", movie["id"])
        else:
            log.warning("artwork: failed for %s: %s", movie["id"],
                        (err or b"").decode("utf-8", "replace")[:200])
            self.mark_failed(movie["id"])
            for p in (tmp_p, tmp_b):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return ok


class ArtworkQueue:
    """Background artwork: the ONLY place frames are generated.

    Measured: generating one frame takes ~40 seconds of decode+seek on this hardware. A request that
    waited for it would both block a console worker thread and trip the console's 40-second proxy
    timeout — the poster would arrive as a 502. So `/api/poster` answers IMMEDIATELY: it serves the
    artwork if it exists, otherwise it queues the work and says "not yet". The shelf shows a
    placeholder for a moment and then the real still, and nothing in the app ever blocks on ffmpeg.
    """

    def __init__(self, artwork: "Artwork", store, url_for, busy=None):
        self.artwork = artwork
        self.store = store
        self.url_for = url_for                       # callable(movie) -> a file path or a URL
        self.busy = busy                             # callable() -> True while a sync is running
        self._pending: list[dict] = []
        self._queued: set[str] = set()
        self._workers: list[asyncio.Task] = []
        self.done = 0
        self.failed = 0

    def ensure(self, movie: dict) -> bool:
        """Queue one film. True when the artwork already exists."""
        mid = movie["id"]
        if self.artwork.has_poster(mid):
            return True
        if mid in self._queued or len(self._pending) >= MAX_PENDING:
            return False
        self._queued.add(mid)
        self._pending.append(movie)
        self._spawn()
        return False

    def ensure_front(self, movie: dict) -> bool:
        """Queue one film ahead of everything else (the hero banner uses this)."""
        mid = movie["id"]
        if self.artwork.has_poster(mid):
            return True
        if mid in self._queued:
            self._pending = [m for m in self._pending if m["id"] != mid] + [movie]
        else:
            self._queued.add(mid)
            self._pending.insert(0, movie)
        self._spawn()
        return False

    def _spawn(self) -> None:
        self._workers = [w for w in self._workers if not w.done()]
        while self._pending and len(self._workers) < CONCURRENCY:
            self._workers.append(asyncio.ensure_future(self._work()))

    async def _work(self) -> None:
        while self._pending:
            if self.busy is not None and self.busy():
                # A sync reads hundreds of Telegram messages and the office's cores are few; artwork
                # is cosmetic and can wait for it. Without this, browsing a shelf while a scan runs
                # makes both slower and the app looks broken.
                await asyncio.sleep(10)
                continue
            movie = self._pending.pop(0)
            try:
                info = self.store.get_probe(movie["id"]) or {}
                ok = await self.artwork.generate(movie, self.url_for(movie),
                                                 duration=float(info.get("duration") or 0))
                self.done += bool(ok)
                self.failed += (not ok)
            except Exception as e:                        # noqa: BLE001 - never kill the worker
                self.failed += 1
                log.warning("artwork queue: %s failed: %s", movie.get("id"), e)
            finally:
                self._queued.discard(movie["id"])

    def status(self) -> dict:
        return {"pending": len(self._pending), "done": self.done, "failed": self.failed,
                "concurrency": CONCURRENCY}
