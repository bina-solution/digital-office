"""The job plane: one bounded queue, one worker, and a record per job on disk.

Three properties this file exists to guarantee, in the order they matter on a 2-core box:

  1. **Nothing unbounded.** A bounded queue and a single worker. A full queue is a 429 with a
     Retry-After, not an ever-growing backlog that eats the RAM the database needs.
  2. **A job is a record, not a promise.** Every transition is written to /data/jobs/<id>.json, so
     "what happened to my recording" survives a container restart, and a completed transcript can
     be re-read (and re-rendered into another format) without re-running the model.
  3. **Cancellation and progress are real.** The transcriber yields segments lazily, so the loop
     below can report how far it got (a percent that means audio seconds, not a guess) and stop
     between segments when the client asks it to.

Duration is probed BEFORE the work is queued (PyAV reads the header), because "this file is 9 hours
long" must be a refusal with a number in it, not an OOM at 03:00.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, BinaryIO

from .engine import ENGINE

LOG = logging.getLogger("asr.jobs")

STATUSES = ("queued", "processing", "completed", "error", "cancelled")


class QueueFull(Exception):
    pass


class TooLong(Exception):
    def __init__(self, duration: float, limit: float) -> None:
        super().__init__(f"audio is {duration:.0f}s, the limit is {limit:.0f}s")
        self.duration = duration
        self.limit = limit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def probe_duration(path: str) -> float | None:
    """Duration in seconds, from the container header. None when the format will not say."""
    try:
        import av

        with av.open(path) as container:
            if container.duration:
                return float(container.duration) / 1_000_000
            stream = container.streams.audio[0] if container.streams.audio else None
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception as exc:  # noqa: BLE001 - an unreadable header is a job-level failure, later
        LOG.warning("duration probe failed for %s: %s", path, exc)
    return None


@dataclass
class Job:
    id: str
    status: str = "queued"
    created: str = field(default_factory=_now)
    started: str | None = None
    ended: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "ended": self.ended,
            "source": self.source,
            "options": self.options,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "usage": self.usage,
            "cancel_requested": self.cancel_requested,
        }

    def text(self) -> str:
        if self.result:
            return self.result.get("text") or ""
        return ""

    def segments(self) -> list[dict[str, Any]]:
        if self.result:
            return self.result.get("segments") or []
        return []

    def wait(self, timeout: float | None) -> bool:
        return self._done.wait(timeout)


class Jobs:
    def __init__(self) -> None:
        self.data_dir = _env("SPEECH_DATA_DIR", "/data")
        self.jobs_dir = os.path.join(self.data_dir, "jobs")
        self.uploads_dir = os.path.join(self.data_dir, "uploads")
        self.max_queue = int(_env("SPEECH_MAX_QUEUE", "8"))
        self.max_duration = float(_env("SPEECH_MAX_DURATION_SECONDS", str(4 * 3600)))
        self.max_upload_bytes = int(_env("SPEECH_MAX_UPLOAD_BYTES", str(3 * 1024**3)))
        self.upload_ttl = int(_env("SPEECH_UPLOAD_TTL_SECONDS", str(7 * 24 * 3600)))
        self.job_ttl = int(_env("SPEECH_JOB_TTL_SECONDS", str(30 * 24 * 3600)))
        self.uploads_max_bytes = int(_env("SPEECH_UPLOADS_MAX_BYTES", str(5 * 1024**3)))
        self.job_timeout = float(_env("SPEECH_JOB_TIMEOUT_SECONDS", str(2 * 3600)))
        self.beam_size = int(_env("SPEECH_BEAM_SIZE", "5"))
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.uploads_dir, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=self.max_queue)
        self._current: str | None = None
        self._stop = threading.Event()
        self._load_existing()
        self._worker = threading.Thread(target=self._loop, name="asr-worker", daemon=True)
        self._worker.start()
        threading.Thread(target=self._cleanup_loop, name="asr-cleanup", daemon=True).start()

    # ── persistence ──────────────────────────────────────────────────────────────────────
    def _path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _persist(self, job: Job) -> None:
        tmp = self._path(job.id) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(job.as_dict(), f, ensure_ascii=False)
            os.replace(tmp, self._path(job.id))
        except OSError as exc:
            LOG.warning("could not persist job %s: %s", job.id, exc)

    def _load_existing(self) -> None:
        for name in os.listdir(self.jobs_dir):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.jobs_dir, name), encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                continue
            job = Job(id=raw.get("id") or name[:-5], **{k: raw.get(k) for k in
                                                         ("status", "created", "started", "ended", "source",
                                                          "options", "progress", "result", "error", "usage")})
            if job.status in ("queued", "processing"):
                # The process that was running it is gone; the record must not lie about that.
                job.status = "error"
                job.error = {"code": "interrupted", "message": "the office restarted while this job was running"}
                job.ended = _now()
                self._persist(job)
            job._done.set()
            self._jobs[job.id] = job

    # ── uploads ──────────────────────────────────────────────────────────────────────────
    def save_upload(self, stream: BinaryIO, filename: str) -> dict[str, Any]:
        """Content-addressed so the same voice note twice costs one file."""
        digest = hashlib.sha256()
        tmp = os.path.join(self.uploads_dir, f".incoming-{uuid.uuid4().hex}")
        size = 0
        with open(tmp, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_upload_bytes:
                    out.close()
                    os.unlink(tmp)
                    raise ValueError(f"upload exceeds SPEECH_MAX_UPLOAD_BYTES ({self.max_upload_bytes} bytes)")
                digest.update(chunk)
                out.write(chunk)
        ext = os.path.splitext(filename or "")[1].lower()[:10]
        final = os.path.join(self.uploads_dir, f"{digest.hexdigest()[:32]}{ext}")
        os.replace(tmp, final)
        duration = probe_duration(final)
        if duration and duration > self.max_duration:
            os.unlink(final)
            raise TooLong(duration, self.max_duration)
        return {"path": final, "name": filename or os.path.basename(final), "bytes": size,
                "duration": duration, "kind": "upload"}

    # ── queue ────────────────────────────────────────────────────────────────────────────
    def submit(self, source: dict[str, Any], options: dict[str, Any]) -> Job:
        job = Job(id="tr_" + uuid.uuid4().hex[:12], source=source, options=options)
        if source.get("duration"):
            job.progress = {"audio_seconds": round(float(source["duration"]), 2), "processed_seconds": 0.0, "percent": 0.0}
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
            try:
                self._queue.put_nowait(job.id)
            except queue.Full:
                job.status = "error"
                job.error = {"code": "queue_full", "message": f"queue is full ({self.max_queue})"}
                job.ended = _now()
                job._done.set()
                self._persist(job)
                raise QueueFull(job.error["message"]) from None
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
            job.ended = _now()
            job._done.set()
            self._persist(job)
        return job

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {s: 0 for s in STATUSES}
            for job in self._jobs.values():
                counts[job.status] = counts.get(job.status, 0) + 1
            return {
                "queue_depth": self._queue.qsize(),
                "queue_limit": self.max_queue,
                "current": self._current,
                "counts": counts,
                "limits": {
                    "max_duration_seconds": self.max_duration,
                    "max_upload_bytes": self.max_upload_bytes,
                    "job_timeout_seconds": self.job_timeout,
                    "beam_size": self.beam_size,
                },
            }

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)[:limit]
            return [
                {k: v for k, v in j.as_dict().items() if k not in ("result",)}
                for j in jobs
            ]

    # ── the worker ───────────────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            job = self.get(job_id)
            if job is None or job.status != "queued" or job.cancel_requested:
                self._queue.task_done()
                continue
            self._current = job_id
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001 - a job failure is data, not a crash
                LOG.exception("job %s failed", job.id)
                self._fail(job, "internal_error", f"{type(exc).__name__}: {exc}")
            finally:
                self._current = None
                self._queue.task_done()

    def _fail(self, job: Job, code: str, message: str) -> None:
        if job.status in ("completed", "error", "cancelled"):
            return
        job.status = "error"
        job.error = {"code": code, "message": message}
        job.ended = _now()
        job._done.set()
        self._persist(job)

    def _run(self, job: Job) -> None:
        opts = job.options
        job.status = "processing"
        job.started = _now()
        self._persist(job)
        started = time.time()
        language = opts.get("language") or "he"
        beam = int(opts.get("beam_size") or self.beam_size)
        vad = bool(opts.get("vad", True))
        word_timestamps = bool(opts.get("word_timestamps", True))

        with ENGINE.session() as engine:
            loaded_now = engine.loaded_just_now
            inference_started = time.time()
            segments_iter, info = engine.transcribe(
                job.source["path"],
                language=language,
                beam_size=beam,
                word_timestamps=word_timestamps,
                # WhisperX's default, and the fix for the repetition/hallucination loop that
                # Whisper's own sliding window is prone to at chunk boundaries.
                condition_on_previous_text=False,
                vad_filter=vad,
                vad_parameters={"min_silence_duration_ms": 500} if vad else None,
            )
            duration = float(getattr(info, "duration", None) or job.source.get("duration") or 0.0)
            job.progress = {"audio_seconds": round(duration, 2), "processed_seconds": 0.0, "percent": 0.0}
            out: list[dict[str, Any]] = []
            for seg in segments_iter:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.ended = _now()
                    job._done.set()
                    self._persist(job)
                    return
                if time.time() - started > self.job_timeout:
                    self._fail(job, "timeout", f"job exceeded SPEECH_JOB_TIMEOUT_SECONDS ({self.job_timeout:.0f}s)")
                    return
                item: dict[str, Any] = {
                    "id": seg.id,
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "text": (seg.text or "").strip(),
                    "revision": 1,
                    "confidence": round(float(getattr(seg, "avg_logprob", 0.0) or 0.0), 4),
                }
                words = getattr(seg, "words", None)
                if words:
                    item["words"] = [
                        {"w": w.word, "start": round(float(w.start), 3), "end": round(float(w.end), 3),
                         "confidence": round(float(getattr(w, "probability", 0.0) or 0.0), 4)}
                        for w in words
                    ]
                out.append(item)
                processed = min(duration, float(seg.end)) if duration else None
                job.progress = {
                    "audio_seconds": round(duration, 2),
                    "processed_seconds": round(processed, 2) if processed is not None else None,
                    "percent": round(100.0 * processed / duration, 1) if duration and processed else 0.0,
                    "segments": len(out),
                }
                if len(out) % 5 == 0:
                    self._persist(job)

        inference = time.time() - inference_started
        wall = time.time() - started
        job.status = "completed"
        job.ended = _now()
        job.result = {
            "id": job.id,
            "created": job.created,
            "source": job.source,
            "language": getattr(info, "language", language),
            "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
            "model": {"name": ENGINE.repo, "revision": ENGINE.revision, "compute": ENGINE.compute_type},
            "duration": round(duration, 2),
            "text": " ".join(s["text"] for s in out if s["text"]).strip(),
            "segments": out,
            "usage": {
                "audio_seconds": round(duration, 2),
                # inference only — the fetch and the load are costs of the FIRST job and are
                # reported beside it (wall_seconds), because mixing them makes the RTF a lie.
                "inference_seconds": round(inference, 1),
                "wall_seconds": round(wall, 1),
                "rtf": round(duration / inference, 2) if inference else None,
                "model_load_seconds": round(ENGINE.state().get("load_seconds") or 0.0, 1) if loaded_now else 0.0,
            },
        }
        job.usage = job.result["usage"]
        job.progress = {"audio_seconds": round(duration, 2), "processed_seconds": round(duration, 2), "percent": 100.0,
                        "segments": len(out)}
        job._done.set()
        self._persist(job)
        LOG.info(
            "job %s done: %.1fs audio in %.1fs inference (rtf %.2f; wall %.1fs%s), %d segments",
            job.id, duration, inference, job.result["usage"]["rtf"] or 0.0, wall,
            f", incl. model load {job.result['usage']['model_load_seconds']}s" if loaded_now else "",
            len(out),
        )

    # ── housekeeping ─────────────────────────────────────────────────────────────────────
    def _cleanup_loop(self) -> None:
        while not self._stop.wait(900):
            try:
                self._prune()
            except Exception:  # noqa: BLE001
                LOG.exception("prune failed")

    def _prune(self) -> None:
        now = time.time()
        for name in os.listdir(self.jobs_dir):
            path = os.path.join(self.jobs_dir, name)
            try:
                if name.endswith(".json") and now - os.path.getmtime(path) > self.job_ttl:
                    os.unlink(path)
                    with self._lock:
                        self._jobs.pop(name[:-5], None)
                elif name.endswith(".tmp") and now - os.path.getmtime(path) > 3600:
                    os.unlink(path)
            except OSError:
                pass
        keep = {j.source.get("path") for j in self._jobs.values() if j.source.get("path")}
        uploads = []
        for name in os.listdir(self.uploads_dir):
            path = os.path.join(self.uploads_dir, name)
            try:
                uploads.append((os.path.getmtime(path), os.path.getsize(path), path))
            except OSError:
                pass
        total = sum(u[1] for u in uploads)
        for mtime, size, path in sorted(uploads):
            if path in keep:
                continue
            if now - mtime > self.upload_ttl or total > self.uploads_max_bytes:
                try:
                    os.unlink(path)
                    total -= size
                except OSError:
                    pass
        # the model volume is not pruned here: it is a pinned artifact, re-fetched deliberately


JOBS = Jobs()
