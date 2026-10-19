"""The transcription engine: one model, loaded on demand, released when nobody is talking.

Why this file is shaped the way it is (all of it measured on the office host, 2 vCPU, no GPU —
see ai/context/local-asr-research.md):

  * A cold load of the model is 58 s and peaks at ~2.5 GB while CTranslate2 quantises fp16 -> int8
    in RAM, even though the resident set afterwards is ~1.0 GB. So the model is NEVER loaded at
    import time: the first job pays for it, and the office boots without it.
  * Reloading from page cache costs 10-16 s, which is cheap enough that dropping the model after
    `SPEECH_IDLE_UNLOAD_SECONDS` (default 300) of silence is strictly better than holding 1 GB on a
    7 GB box shared with n8n, postgres and the console.
  * One worker, and it is pinned to one CPU thread. Measured: 2 threads give ~20% over 1 thread for
    this model, and the whole point is that the office keeps a core.

The model is a PINNED artifact, not "whatever huggingface serves today": repo + revision live in
the environment, the downloaded tree carries a `.ready` marker naming the revision it was fetched
at, and a marker that does not match triggers a re-fetch. That is the same discipline as the Docker
pin, and it is what makes "the model changed" a decision rather than a drift.
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

LOG = logging.getLogger("asr.engine")

DEFAULT_REPO = "ivrit-ai/whisper-large-v3-turbo-ct2"
# Pinned 2026-10-07 (huggingface.co/api/models/ivrit-ai/whisper-large-v3-turbo-ct2 -> sha).
DEFAULT_REVISION = "72ad623a37947395efcc3933132353790e5a12f5"


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class EngineState:
    state: str = "absent"            # absent | cached | downloading | loading | ready | error
    repo: str = ""
    revision: str = ""
    bytes: int = 0
    load_seconds: float | None = None
    loads: int = 0
    last_used: float | None = None
    last_error: str | None = None
    busy: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, idle_seconds: int) -> dict[str, Any]:
        age = None if self.last_used is None else round(time.time() - self.last_used, 1)
        return {
            "state": self.state,
            "repo": self.repo,
            "revision": self.revision,
            "bytes": self.bytes,
            "load_seconds": self.load_seconds,
            "loads": self.loads,
            "idle_seconds": age,
            "unload_after_seconds": idle_seconds,
            "busy": self.busy,
            "last_error": self.last_error,
            **self.detail,
        }


class Engine:
    def __init__(self) -> None:
        self.repo = _env("SPEECH_MODEL_REPO", DEFAULT_REPO)
        self.revision = _env("SPEECH_MODEL_REVISION", DEFAULT_REVISION)
        self.model_root = _env("SPEECH_MODEL_DIR", "/data/models")
        self.compute_type = _env("SPEECH_COMPUTE_TYPE", "int8")
        self.cpu_threads = int(_env("SPEECH_CPU_THREADS", "1"))
        self.idle_unload_seconds = int(_env("SPEECH_IDLE_UNLOAD_SECONDS", "300"))
        self._state = EngineState(repo=self.repo, revision=self.revision)
        # set once we have looked at the volume, so a health probe never walks 1.6 GB of files
        self._disk_checked = False
        self._model: Any = None
        # True when the LAST session() call had to load the model — the caller reports the load
        # time as its own number instead of hiding it inside "how long the transcription took".
        self.loaded_just_now = False
        self._lock = threading.RLock()
        self._in_use = 0
        self._last_used = 0.0
        self._stop = threading.Event()
        threading.Thread(target=self._idle_loop, name="asr-idle", daemon=True).start()

    # ── the model on disk ────────────────────────────────────────────────────────────────
    @property
    def model_dir(self) -> str:
        return os.path.join(self.model_root, self.repo.split("/")[-1])

    def _marker(self) -> str:
        return os.path.join(self.model_dir, ".ready")

    def refresh_disk(self) -> None:
        """One look at the volume, then remember it — a restart must not report 'absent' for a
        model that is sitting right there, and health must not cost a directory walk per probe."""
        if self._disk_checked or self._model is not None:
            return
        self._disk_checked = True
        if self.model_present():
            self._state.bytes = self._dir_bytes()
            self._state.state = "cached"

    def model_present(self) -> bool:
        try:
            with open(self._marker(), "r", encoding="utf-8") as f:
                return f.read().strip() == self.revision
        except OSError:
            return False

    def _dir_bytes(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.model_dir):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total

    def ensure_model(self) -> str:
        """Fetch the pinned revision once, into the volume. Safe to call repeatedly."""
        with self._lock:
            if self.model_present():
                self._state.bytes = self._dir_bytes()
                return self.model_dir
            if self._state.state == "downloading":
                while self._state.state == "downloading":
                    time.sleep(0.5)
                return self.model_dir
            self._state.state = "downloading"
            self._state.last_error = None
        try:
            from huggingface_hub import snapshot_download

            os.makedirs(self.model_root, exist_ok=True)
            LOG.info("fetching model %s@%s", self.repo, self.revision)
            t0 = time.time()
            snapshot_download(repo_id=self.repo, revision=self.revision, local_dir=self.model_dir)
            with open(self._marker(), "w", encoding="utf-8") as f:
                f.write(self.revision)
            with self._lock:
                self._state.detail["download_seconds"] = round(time.time() - t0, 1)
                self._state.bytes = self._dir_bytes()
                self._state.state = "cached"
                self._disk_checked = True
            LOG.info("model ready (%d bytes)", self._state.bytes)
        except Exception as exc:  # noqa: BLE001 - the caller decides what a failure means
            with self._lock:
                self._state.state = "error"
                self._state.last_error = f"{type(exc).__name__}: {exc}"
            LOG.exception("model fetch failed")
            raise
        return self.model_dir

    def discard_model(self) -> None:
        """Throw away a partial/broken download so the next call fetches cleanly."""
        with self._lock:
            self._model = None
            shutil.rmtree(self.model_dir, ignore_errors=True)
            self._state.state = "absent"
            self._state.bytes = 0
            self._disk_checked = True

    # ── the model in RAM ─────────────────────────────────────────────────────────────────
    def _load(self) -> None:
        from faster_whisper import WhisperModel

        path = self.ensure_model()
        t0 = time.time()
        self._model = WhisperModel(
            path,
            device="cpu",
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
            num_workers=1,
        )
        self._state.load_seconds = round(time.time() - t0, 1)
        self._state.loads += 1
        LOG.info("model loaded in %.1fs (compute=%s threads=%d)", self._state.load_seconds, self.compute_type, self.cpu_threads)

    def unload(self, *, reason: str) -> None:
        with self._lock:
            if self._model is None:
                return
            self._model = None
            gc.collect()
            self._state.state = "cached" if self.model_present() else "absent"
            LOG.info("model released (%s), now %s", reason, self._state.state)

    def _idle_loop(self) -> None:
        while not self._stop.wait(30):
            if self.idle_unload_seconds <= 0 or self._in_use:
                continue
            if self._model is not None and (time.time() - self._last_used) > self.idle_unload_seconds:
                self.unload(reason=f"idle {self.idle_unload_seconds}s")

    @contextmanager
    def session(self) -> Iterator["Engine"]:
        """Hold the model for the duration of one job; it cannot be unloaded meanwhile."""
        with self._lock:
            self.loaded_just_now = self._model is None
            if self._model is None:
                self._state.state = "loading"
                self._state.last_error = None
                try:
                    self._load()
                except Exception as exc:  # noqa: BLE001
                    self._state.state = "error"
                    self._state.last_error = f"{type(exc).__name__}: {exc}"
                    raise
            self._state.state = "ready"
            self._state.busy = True
            self._in_use += 1
        try:
            yield self
        finally:
            with self._lock:
                self._in_use = max(0, self._in_use - 1)
                self._last_used = time.time()
                self._state.last_used = self._last_used
                self._state.busy = self._in_use > 0

    def transcribe(self, path: str, **kwargs: Any):
        """(generator of Segment, TranscriptionInfo) — the generator is lazy: work happens on
        iteration, which is what lets the worker report progress and honour a cancel."""
        if self._model is None:
            raise RuntimeError("model not loaded — use engine.session()")
        return self._model.transcribe(path, **kwargs)

    def state(self) -> dict[str, Any]:
        self.refresh_disk()
        return self._state.as_dict(idle_seconds=self.idle_unload_seconds)


ENGINE = Engine()
