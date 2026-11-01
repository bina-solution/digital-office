"""player — turning "a file in Telegram" into "a video that plays smoothly in a browser".

WHY THIS IS NOT JUST A <video src>. Three facts about this library, all measured:

  1. Most of it is **Matroska**, which no browser can open, and a good part of the rest has **AC3/E-AC3
     audio**, which Chrome cannot decode. Handing the raw bytes to <video> gives a black rectangle and
     no error — the exact opposite of "smooth".
  2. Telegram is not a CDN. Every byte is pulled by this container over MTProto at whatever rate the
     account gets, so a 680 MB 1080p episode is a *stream*, not a download, and it must start within a
     second or two or the illusion of a TV dies.
  3. Seeking must feel instant. With a live remux there is no index to seek into, so a seek is
     implemented the way a real player does it: **start a new ffmpeg at the target timestamp** and swap
     the stream. ffmpeg seeks on the INPUT (which is this app's own range-capable endpoint), so the
     jump costs a keyframe, not a re-download.

So a session is born from a decision (`probe.policy`) and lives as one ffmpeg process:

    direct  → no process at all; the browser streams /api/stream/<id> and seeking is HTTP Range
    remux   → ffmpeg copies the video stream, converts only the audio when it must, and emits
              fragmented MP4 into a pipe this app forwards to the browser
    unsupported → refused with the codec named, because a slideshow is worse than an explanation

Sessions are capped and reaped: a leaked ffmpeg would hold a core and a Telegram connection forever,
and the office runs on four cores.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

import probe as prober

log = logging.getLogger("telegram-tv.player")

FFMPEG = os.environ.get("TV_FFMPEG", "ffmpeg")
#: How many players may exist at once. Each is one ffmpeg and one Telegram download stream; the box
#: has 4 cores and a memory ceiling, and nobody watches more than one film at a time in this office —
#: the extra slots exist for a second person and for the moment a seek overlaps with a closing stream.
MAX_SESSIONS = int(os.environ.get("TV_MAX_SESSIONS", "3"))
#: A session that nobody has read from for this long is killed. Without it, closing a laptop lid
#: leaves ffmpeg pulling a 4 GB film from Telegram until the container restarts.
IDLE_SECONDS = float(os.environ.get("TV_SESSION_IDLE_SECONDS", "45"))
#: Audio bitrate when the source audio has to be re-encoded. 192k stereo is transparent for a film
#: track and costs ~2% of a core.
AUDIO_BITRATE = os.environ.get("TV_AUDIO_BITRATE", "192k")


class Session:
    def __init__(self, sid: str, movie: dict, mode: str, start: int):
        self.id = sid
        self.movie_id = movie["id"]
        self.title = movie.get("title") or ""
        self.mode = mode
        self.start = int(start)
        self.proc: asyncio.subprocess.Process | None = None
        self.created = time.time()
        self.last_read = time.time()
        self.bytes = 0
        self.first_byte_at: float | None = None
        self.stderr_tail: list[str] = []

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def public(self) -> dict:
        return {"session": self.id, "mode": self.mode, "start": self.start, "bytes": self.bytes,
                "url": f"api/live/{self.id}" if self.mode == "remux" else None,
                "title": self.title, "alive": self.alive,
                "startup_ms": int((self.first_byte_at - self.created) * 1000) if self.first_byte_at else None,
                "stderr": "".join(self.stderr_tail[-4:])}


class Players:
    def __init__(self, store):
        self.store = store
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    # ── opening ──────────────────────────────────────────────────────────────────────────────
    async def open(self, movie: dict, raw_url: str, *, start: int = 0,
                   force: str | None = None) -> dict:
        """Decide HOW to play this file and, if it needs one, start the ffmpeg for it.

        `force=remux` exists for the client: a browser may believe it can play HEVC and then fail, and
        the honest recovery is to ask for the remuxed path rather than to show a black screen."""
        await self.reap()
        info = await prober.probe(movie, raw_url, self.store)
        pol = info.get("policy") or {}
        mode = force or pol.get("mode") or "direct"
        if mode == "unsupported":
            return {"ok": False, "mode": "unsupported", "reason": pol.get("reason"),
                    "probe": info}
        if mode == "direct":
            return {"ok": True, "mode": "direct", "url": f"api/stream/{movie['id']}",
                    "probe": info, "note": "הקובץ מתאים לדפדפן כמו שהוא"}
        async with self._lock:
            if len([s for s in self.sessions.values() if s.alive]) >= MAX_SESSIONS:
                self._kill_oldest(n=1)
            sid = uuid.uuid4().hex[:12]
            sess = Session(sid, movie, "remux", start)
            await self._spawn(sess, movie, raw_url, info, start)
            self.sessions[sid] = sess
        return {"ok": True, "mode": "remux", "url": f"api/live/{sid}", "probe": info,
                **sess.public()}

    async def _spawn(self, sess: Session, movie: dict, raw_url: str, info: dict, start: int) -> None:
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-nostdin"]
        if start > 0:
            # Input seeking: ffmpeg asks our own endpoint for a byte range near the timestamp, so the
            # jump is one keyframe away instead of a download from zero.
            cmd += ["-ss", str(int(start))]
        cmd += ["-i", raw_url, "-map", "0:v:0"]
        audio = info.get("audio") or ""
        if info.get("has_audio"):
            cmd += ["-map", "0:a:0?"]
        cmd += ["-c:v", "copy"]
        if info.get("audio") and audio not in prober.PLAYABLE_AUDIO:
            # The common case in a film release, and the cheap fix: copy the picture, re-encode only
            # the soundtrack. Cost is a few percent of a core, versus a full video transcode which
            # this hardware cannot do in realtime.
            cmd += ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", "2"]
        elif info.get("has_audio"):
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-an"]
        if (info.get("video") or "") in prober.CONDITIONAL_VIDEO:
            cmd += ["-tag:v", "hvc1"]           # the tag Apple's decoder insists on
        cmd += ["-avoid_negative_ts", "make_zero",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", "pipe:1"]
        log.info("session %s: %s", sess.id, " ".join(cmd[:6] + ["…"]))
        sess.cmd = cmd
        sess.proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024)
        asyncio.create_task(self._drain_stderr(sess))

    async def _drain_stderr(self, sess: Session) -> None:
        """Keep the last few lines of ffmpeg's complaints. A remux that dies mid-film must be
        diagnosable from /api/play/status without a shell on the container."""
        if sess.proc is None or sess.proc.stderr is None:
            return
        try:
            while True:
                line = await sess.proc.stderr.readline()
                if not line:
                    break
                sess.stderr_tail.append(line.decode("utf-8", "replace"))
                del sess.stderr_tail[:-8]
        except Exception:                                     # noqa: BLE001 - diagnostics only
            pass

    # ── streaming ────────────────────────────────────────────────────────────────────────────
    async def stream(self, sid: str):
        sess = self.sessions.get(sid)
        if sess is None or not sess.alive:
            raise KeyError("session")
        assert sess.proc is not None and sess.proc.stdout is not None
        try:
            while True:
                chunk = await sess.proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                sess.last_read = time.time()
                sess.bytes += len(chunk)
                if sess.first_byte_at is None:
                    sess.first_byte_at = time.time()
                    log.info("session %s: first bytes after %dms", sid,
                             int((sess.first_byte_at - sess.created) * 1000))
                yield chunk
        finally:
            # The browser closing the player is the normal end of a session: stop ffmpeg and stop
            # pulling from Telegram immediately, or the film keeps downloading into nothing.
            await self.close(sid)

    async def close(self, sid: str) -> None:
        sess = self.sessions.pop(sid, None)
        if sess is None:
            return
        if sess.proc is not None and sess.proc.returncode is None:
            try:
                sess.proc.kill()
            except ProcessLookupError:
                pass
        log.info("session %s closed after %dB", sid, sess.bytes)

    def _kill_oldest(self, n: int = 1) -> None:
        alive = sorted((s for s in self.sessions.values() if s.alive), key=lambda s: s.last_read)
        for sess in alive[:n]:
            log.info("killing session %s (cap %d reached)", sess.id, MAX_SESSIONS)
            if sess.proc is not None and sess.proc.returncode is None:
                sess.proc.kill()
            self.sessions.pop(sess.id, None)

    async def reap(self) -> int:
        """Kill sessions nobody is reading. Called on every new play request, which is the only moment
        a leak can matter."""
        now = time.time()
        dead = [s for s in self.sessions.values() if s.alive and now - s.last_read > IDLE_SECONDS]
        for sess in dead:
            log.info("reaping idle session %s (%ds idle)", sess.id, int(now - sess.last_read))
            if sess.proc is not None and sess.proc.returncode is None:
                sess.proc.kill()
            self.sessions.pop(sess.id, None)
        for sid, sess in list(self.sessions.items()):
            if not sess.alive and now - sess.last_read > 5:
                self.sessions.pop(sid, None)
        return len(dead)

    def status(self) -> dict:
        return {"max_sessions": MAX_SESSIONS, "idle_seconds": IDLE_SECONDS,
                "sessions": [s.public() for s in self.sessions.values()]}
