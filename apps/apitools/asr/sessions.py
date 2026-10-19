"""Live sessions: dictation that grows while the owner is still talking.

The shape, and why it is this shape rather than a WebSocket:

  * The browser is the only thing that knows where one utterance ends, so it cuts the audio into
    segments (~12 s) and posts each one. Every segment is an ordinary job — the same bounded queue,
    the same worker, the same records — so a live session inherits the caps, the fairness and the
    restart-safety that were already built and measured.
  * Nothing is held open: a dropped connection, a reloaded tab or a restarted container lose no more
    than the segment in flight. There is no session state on the socket, because there is no socket.
  * The interim text IS the segment's transcript, and the final text is a SECOND pass over the whole
    recording (VAD off, beam 5, context across the whole utterance). That two-pass split is the
    standard pattern, and here it is also what keeps the CPU bill honest: the segments are cheap and
    the final pass runs once, after the owner stopped.

The one thing that needed real code: joining the segments back into one recording for the final
pass. WebM/Opus segments are each a complete container, so they cannot be concatenated by bytes —
they are decoded and re-encoded into one 16 kHz mono WAV, which is exactly the input Whisper's mel
front end is defined on.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .engine import ENGINE
from .jobs import JOBS, Job, QueueFull

LOG = logging.getLogger("asr.sessions")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def concat_audio(paths: list[str], out_path: str, rate: int = 16000) -> float:
    """Decode every segment and write one 16 kHz mono PCM WAV. Returns its duration in seconds."""
    import av
    import wave

    pcm = bytearray()
    for path in paths:
        with av.open(path) as container:
            if not container.streams.audio:
                continue
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
            for frame in container.decode(stream):
                for rf in resampler.resample(frame):
                    pcm += bytes(rf.planes[0])[: rf.samples * 2]
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))
    return len(pcm) / 2 / rate


class Sessions:
    def __init__(self) -> None:
        self.dir = os.path.join(JOBS.data_dir, "sessions")
        os.makedirs(self.dir, exist_ok=True)
        self.ttl = int(os.environ.get("SPEECH_SESSION_TTL_SECONDS") or 7 * 24 * 3600)
        self.max_segments = int(os.environ.get("SPEECH_MAX_SEGMENTS") or 240)
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, Any]] = {}

    # ── storage ──────────────────────────────────────────────────────────────────────────
    def _path(self, sid: str) -> str:
        return os.path.join(self.dir, f"{sid}.json")

    def _write(self, rec: dict[str, Any]) -> None:
        tmp = self._path(rec["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, self._path(rec["id"]))

    def _read(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            if sid in self._cache:
                return self._cache[sid]
        try:
            with open(self._path(sid), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            return None
        with self._lock:
            self._cache[sid] = rec
        return rec

    # ── api ──────────────────────────────────────────────────────────────────────────────
    def create(self, *, language: str, source: str = "mic") -> dict[str, Any]:
        rec = {
            "id": "lv_" + uuid.uuid4().hex[:12],
            "created": _now(),
            "language": language,
            "source": source,
            "segments": [],
            "final_job_id": None,
            "finished": None,
        }
        with self._lock:
            self._cache[rec["id"]] = rec
            self._write(rec)
        LOG.info("live session %s opened (language=%s)", rec["id"], language)
        return rec

    def add_segment(self, sid: str, index: int, upload: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        rec = self._read(sid)
        if rec is None:
            raise KeyError(sid)
        if rec.get("finished"):
            raise ValueError("session already finished")
        if len(rec["segments"]) >= self.max_segments:
            raise ValueError(f"session reached SPEECH_MAX_SEGMENTS ({self.max_segments})")
        job = JOBS.submit(
            {**upload, "kind": "voice-segment", "session_id": sid, "index": index},
            options,
        )
        entry = {"index": index, "job_id": job.id, "path": upload["path"], "duration": upload.get("duration"),
                 "created": _now()}
        with self._lock:
            rec["segments"] = [s for s in rec["segments"] if s["index"] != index] + [entry]
            rec["segments"].sort(key=lambda s: s["index"])
            self._write(rec)
        LOG.info("session %s segment %d -> job %s", sid, index, job.id)
        return entry

    def status(self, sid: str) -> dict[str, Any] | None:
        rec = self._read(sid)
        if rec is None:
            return None

        def job_view(job_id: str | None) -> dict[str, Any] | None:
            if not job_id:
                return None
            job: Job | None = JOBS.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "unknown", "text": None}
            return {
                "job_id": job.id,
                "status": job.status,
                "text": job.text() if job.status == "completed" else None,
                "progress": job.progress,
                "error": job.error,
                "usage": job.usage,
            }

        segments = []
        for s in rec["segments"]:
            view = job_view(s["job_id"]) or {}
            segments.append({"index": s["index"], "duration": s.get("duration"), **view})
        text = " ".join(s["text"] for s in segments if s.get("text")).strip()
        final = job_view(rec.get("final_job_id"))
        return {
            "id": rec["id"],
            "created": rec["created"],
            "finished": rec.get("finished"),
            "language": rec.get("language"),
            "segments": segments,
            "text": text,
            "duration": round(sum(s.get("duration") or 0.0 for s in segments), 2),
            "final": final,
            "final_text": (final or {}).get("text"),
            "queue": JOBS.stats(),
        }

    def finish(self, sid: str, options: dict[str, Any]) -> dict[str, Any]:
        rec = self._read(sid)
        if rec is None:
            raise KeyError(sid)
        if rec.get("final_job_id"):
            return {"final_job_id": rec["final_job_id"], "reused": True}
        if not rec["segments"]:
            raise ValueError("no segments to finish")
        # a segment still being decoded must finish first, or the joined file would be short
        deadline = time.time() + 120
        while time.time() < deadline:
            pending = [s for s in rec["segments"]
                       if (JOBS.get(s["job_id"]) or Job(id="x")).status in ("queued", "processing")]
            if not pending:
                break
            time.sleep(1)
        paths = [os.path.join(s["path"]) for s in rec["segments"] if os.path.exists(s["path"])]
        joined = os.path.join(JOBS.uploads_dir, f"session-{sid}.wav")
        duration = concat_audio(paths, joined)
        upload = {"path": joined, "name": f"{sid}-full.wav", "bytes": os.path.getsize(joined),
                  "duration": duration, "kind": "voice-session"}
        job = JOBS.submit({**upload, "session_id": sid, "final": True}, options)
        with self._lock:
            rec["final_job_id"] = job.id
            rec["finished"] = _now()
            rec["duration"] = round(duration, 2)
            self._write(rec)
        LOG.info("session %s finished: %d segments, %.1fs joined -> final job %s",
                 sid, len(rec["segments"]), duration, job.id)
        return {"final_job_id": job.id, "duration": round(duration, 2), "reused": False}

    def export(self, sid: str) -> str | None:
        """One playable file for the whole recording — for sending the voice note itself.

        The segments are separate WebM/Opus containers, so they are joined the same way the accurate
        pass joins them (decode + one 16 kHz mono WAV). Cached: a second call does not re-decode.
        """
        rec = self._read(sid)
        if rec is None or not rec["segments"]:
            return None
        out = os.path.join(JOBS.uploads_dir, f"session-{sid}.wav")
        if os.path.exists(out) and os.path.getmtime(out) >= max(
            os.path.getmtime(p) for p in (s["path"] for s in rec["segments"]) if os.path.exists(p)
        ):
            return out
        paths = [s["path"] for s in rec["segments"] if os.path.exists(s["path"])]
        if not paths:
            return None
        concat_audio(paths, out)
        return out

    def cancel(self, sid: str) -> dict[str, Any] | None:
        rec = self._read(sid)
        if rec is None:
            return None
        cancelled = []
        for s in rec["segments"]:
            if JOBS.cancel(s["job_id"]):
                cancelled.append(s["job_id"])
        if rec.get("final_job_id"):
            JOBS.cancel(rec["final_job_id"])
        return {"id": sid, "cancelled": cancelled}

    def prune(self) -> int:
        now = time.time()
        removed = 0
        for name in os.listdir(self.dir):
            path = os.path.join(self.dir, name)
            try:
                if name.endswith(".json") and now - os.path.getmtime(path) > self.ttl:
                    os.unlink(path)
                    with self._lock:
                        self._cache.pop(name[:-5], None)
                    removed += 1
                elif name.endswith(".tmp") and now - os.path.getmtime(path) > 3600:
                    os.unlink(path)
            except OSError:
                pass
        return removed


SESSIONS = Sessions()
