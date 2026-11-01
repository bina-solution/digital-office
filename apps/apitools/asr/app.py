"""apitools-asr — the office's Hebrew speech-to-text service.

Two surfaces, one pipeline:

  * **The office capability** (`POST /transcribe`, `/transcriptionStatus`, `/transcriptionResult`,
    `/transcriptionCancel`, `/speechHealth`, `/speechModels`) — the names other apps and the office
    agent use. Declared in apps/apitools/app.json as the `speech` capability.
  * **The standard surface** (`POST /v1/audio/transcriptions`, `GET /v1/models`) — the OpenAI audio
    shape, so an existing client or a later swap to a hosted model costs no code. `json` returns
    exactly `{"text": ...}`, as that API does; `verbose_json` returns the canonical object.

Long audio is a JOB: `POST` answers `202 {id, status, position, eta_seconds}` and the caller polls.
Short audio can be answered inline, which is what the shapes above are for. The decision is the
audio's own duration (probed from the header, `SPEECH_SYNC_MAX_SECONDS`, default 120) unless the
caller asks for `?async=1` / `Prefer: respond-async`.

The canonical object (segments + words + timings + revisions) is the store; VTT/SRT/TXT/DOCX are
rendered from it on demand (`formats.py`). Nothing here reaches outside the office network: there is
no public router for this container, and no input is a URL the caller supplies.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .engine import ENGINE
from .formats import to_docx_bytes, to_srt, to_txt, to_vtt
from .jobs import JOBS, QueueFull, TooLong
from .sessions import SESSIONS

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOG = logging.getLogger("asr")

SERVICE = "apitools-asr"
VERSION = "0.1.0"
OPS = [
    "transcribe",
    "transcriptionStatus",
    "transcriptionResult",
    "transcriptionCancel",
    "speechHealth",
    "speechModels",
]
# the live/dictation surface — same queue, same worker, the client just cuts the audio
LIVE_OPS = [
    "voiceExport",
    "voiceStart",
    "voiceSegment",
    "voiceStatus",
    "voiceFinish",
    "voiceCancel",
]
SERVICE_OPS = OPS + LIVE_OPS
FORMATS = ("json", "text", "txt", "srt", "vtt", "verbose_json", "docx")

app = FastAPI(title=SERVICE, version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


SYNC_MAX_SECONDS = _env_float("SPEECH_SYNC_MAX_SECONDS", 120.0)
SYNC_TIMEOUT_SECONDS = _env_float("SPEECH_SYNC_TIMEOUT_SECONDS", 1800.0)
DEFAULT_LANGUAGE = os.environ.get("SPEECH_DEFAULT_LANGUAGE") or "he"

# ── result rendering ────────────────────────────────────────────────────────────────────


def _render(job: Any, fmt: str) -> Response:
    segments = job.segments()
    name = (job.source.get("name") or job.id).rsplit(".", 1)[0]
    if fmt in ("json",):
        return JSONResponse({"text": job.text()})
    if fmt == "text":
        return PlainTextResponse(to_txt(segments))
    if fmt == "txt":
        return PlainTextResponse(to_txt(segments))
    if fmt == "vtt":
        return Response(to_vtt(segments), media_type="text/vtt; charset=utf-8",
                        headers={"content-disposition": f'inline; filename="{name}.vtt"'})
    if fmt == "srt":
        return Response(to_srt(segments), media_type="application/x-subrip; charset=utf-8",
                        headers={"content-disposition": f'inline; filename="{name}.srt"'})
    if fmt == "docx":
        return Response(
            to_docx_bytes(segments, title=job.source.get("name") or ""),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"content-disposition": f'attachment; filename="{name}.docx"'},
        )
    if fmt == "verbose_json":
        return JSONResponse(job.result or {})
    raise HTTPException(400, f"unsupported format '{fmt}' (use one of {', '.join(FORMATS)})")


def _job_or_404(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job '{job_id}'")
    return job


def _async_requested(request: Request, async_flag: bool) -> bool:
    prefer = (request.headers.get("prefer") or "").lower()
    return async_flag or "respond-async" in prefer


def _enqueue(source: dict[str, Any], options: dict[str, Any]) -> Any:
    try:
        return JOBS.submit(source, options)
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"retry-after": "30"}) from None


def _options(language: str | None, beam_size: int | None, vad: bool | None, words: bool | None) -> dict[str, Any]:
    return {
        "language": (language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE,
        "beam_size": beam_size or JOBS.beam_size,
        # DEFAULT OFF, and this is a measured decision, not a preference: on the office's own
        # voice note (WhatsApp, 31.8 s) vad=true removed 7.2 s of audio and with it the trailing
        # word ("בואו!"), while vad=false transcribed the whole utterance. Silero's silence
        # trimming is a throughput feature for long recordings — opt in with ?vad=true there.
        "vad": False if vad is None else bool(vad),
        "word_timestamps": True if words is None else bool(words),
    }


# ── health / manifest ───────────────────────────────────────────────────────────────────


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": SERVICE, "version": VERSION, "ops": SERVICE_OPS, "formats": list(FORMATS)}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Always 200 while the process is alive — a released model is a healthy state, not a fault.

    (Same rule as sites-render: a probe that fails because an idle worker is idle puts the
    container into an unhealthy/autoheal restart loop for no reason.)
    """
    return {"status": "ok", "service": SERVICE, "model": ENGINE.state(), "jobs": JOBS.stats()}


@app.get("/speechHealth")
def speech_health() -> dict[str, Any]:
    return healthz()


@app.get("/readyz")
def readyz() -> Response:
    state = ENGINE.state()
    if state["state"] == "error":
        return JSONResponse({"ready": False, "reason": state.get("last_error") or "model error"}, status_code=503)
    if state["state"] == "absent" and not ENGINE.model_present() and not os.environ.get("SPEECH_ALLOW_FETCH", "1") == "1":
        return JSONResponse({"ready": False, "reason": "model not present and fetching is disabled"}, status_code=503)
    return JSONResponse({"ready": True, "model": state})


@app.get("/manifest")
def manifest() -> dict[str, Any]:
    return {
        "service": SERVICE,
        "version": VERSION,
        "ops": SERVICE_OPS,
        "live_ops": LIVE_OPS,
        "formats": list(FORMATS),
        "capabilities": {"speech": {"ops": OPS, "optional_ops": LIVE_OPS}},
        "model": ENGINE.state(),
        "limits": JOBS.stats()["limits"],
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": ENGINE.repo,
                "object": "model",
                "owned_by": "ivrit-ai",
                "revision": ENGINE.revision,
                "compute_type": ENGINE.compute_type,
                "language": DEFAULT_LANGUAGE,
            }
        ],
    }


@app.get("/speechModels")
def speech_models() -> dict[str, Any]:
    return models()


@app.get("/speechJobs")
def speech_jobs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return {"jobs": JOBS.recent(limit), "queue": JOBS.stats()}


# ── the transcription surface ───────────────────────────────────────────────────────────


async def _handle_transcribe(
    request: Request,
    file: UploadFile | None,
    path: str | None,
    language: str | None,
    response_format: str,
    beam_size: int | None,
    vad: bool | None,
    words: bool | None,
    async_flag: bool,
) -> Response:
    options = _options(language, beam_size, vad, words)
    if file is not None and file.filename:
        try:
            source = JOBS.save_upload(file.file, file.filename)
        except TooLong as exc:
            raise HTTPException(413, f"audio is too long for this office: {exc}") from None
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from None
    elif path:
        allowed_root = os.path.realpath(JOBS.data_dir)
        real = os.path.realpath(path)
        if not real.startswith(allowed_root + os.sep):
            raise HTTPException(400, f"path must be inside {allowed_root}")
        if not os.path.isfile(real):
            raise HTTPException(404, f"no such file: {path}")
        source = {"path": real, "name": os.path.basename(real), "bytes": os.path.getsize(real),
                  "duration": None, "kind": "path"}
    else:
        raise HTTPException(400, "send the audio as multipart 'file', or a 'path' inside the data dir")

    job = _enqueue(source, options)
    LOG.info("job %s accepted (%s, %.1fs)", job.id, source.get("name"), source.get("duration") or 0.0)

    duration = source.get("duration") or 0.0
    if _async_requested(request, async_flag) or duration > SYNC_MAX_SECONDS:
        return JSONResponse(
            {
                "id": job.id,
                "status": job.status,
                "position": JOBS.stats()["queue_depth"],
                "eta_seconds": round(duration * 3.0 + 15, 0) if duration else None,
                "status_url": f"/v1/audio/transcriptions/{job.id}",
                "result_url": f"/v1/audio/transcriptions/{job.id}/{response_format}",
            },
            status_code=202,
        )

    if not job.wait(SYNC_TIMEOUT_SECONDS):
        raise HTTPException(504, f"still running after {SYNC_TIMEOUT_SECONDS:.0f}s — poll /v1/audio/transcriptions/{job.id}")
    if job.status == "error":
        raise HTTPException(500, f"{job.error['code']}: {job.error['message']}" if job.error else "job failed")
    if job.status == "cancelled":
        raise HTTPException(409, "job was cancelled")
    LOG.info("job %s answered inline (rtf %s)", job.id, (job.usage or {}).get("rtf"))
    return _render(job, response_format)


@app.post("/v1/audio/transcriptions")
async def openai_transcriptions(
    request: Request,
    file: UploadFile | None = File(None),
    model: str = Form("ivrit-ai/whisper-large-v3-turbo-ct2"),
    language: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float | None = Form(None),
    path: str | None = Form(None),
    beam_size: int | None = Query(None),
    vad: bool | None = Query(None),
    words: bool | None = Query(None),
    async_: bool = Query(False, alias="async"),
) -> Response:
    fmt = (response_format or "json").lower()
    if fmt not in FORMATS:
        raise HTTPException(400, f"unsupported response_format '{response_format}' (use one of {', '.join(FORMATS)})")
    del model, temperature  # one model is served; a client's temperature is not used by this engine
    return await _handle_transcribe(request, file, path, language, fmt, beam_size, vad, words, async_)


@app.post("/transcribe")
async def op_transcribe(
    request: Request,
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    language: str | None = Form(None),
    response_format: str = Form("json"),
    beam_size: int | None = Query(None),
    vad: bool | None = Query(None),
    words: bool | None = Query(None),
    async_: bool = Query(False, alias="async"),
) -> Response:
    fmt = (response_format or "json").lower()
    if fmt not in FORMATS:
        raise HTTPException(400, f"unsupported response_format '{response_format}' (use one of {', '.join(FORMATS)})")
    return await _handle_transcribe(request, file, path, language, fmt, beam_size, vad, words, async_)


@app.get("/v1/audio/transcriptions/{job_id}")
def openai_status(job_id: str) -> Response:
    job = _job_or_404(job_id)
    if job.status in ("completed", "error", "cancelled"):
        return JSONResponse(job.as_dict())
    return JSONResponse(job.as_dict(), status_code=200 if job.status == "processing" else 202)


@app.get("/transcriptionStatus")
def op_status(id: str = Query(...)) -> Response:
    return openai_status(id)


@app.get("/v1/audio/transcriptions/{job_id}/{fmt}")
def openai_result(job_id: str, fmt: str) -> Response:
    job = _job_or_404(job_id)
    if job.status == "completed":
        return _render(job, fmt.lower())
    if job.status == "error":
        return JSONResponse(job.as_dict(), status_code=500)
    return JSONResponse(job.as_dict(), status_code=202)


@app.get("/transcriptionResult")
def op_result(id: str = Query(...), format: str = Query("json")) -> Response:
    return openai_result(id, format)


@app.post("/v1/audio/transcriptions/{job_id}/cancel")
def openai_cancel(job_id: str) -> dict[str, Any]:
    job = _job_or_404(job_id)
    JOBS.cancel(job.id)
    return {"id": job.id, "status": job.status, "cancel_requested": job.cancel_requested}


@app.post("/transcriptionCancel")
def op_cancel(id: str = Query(...)) -> dict[str, Any]:
    return openai_cancel(id)


# ── live sessions (dictation) ───────────────────────────────────────────────────────────


@app.post("/v1/voice/sessions")
async def voice_start(
    request: Request,
    language: str | None = Query(None),
    source: str = Query("mic"),
) -> dict[str, Any]:
    """Open a live session. The client then posts segments and polls the status."""
    rec = SESSIONS.create(language=(language or DEFAULT_LANGUAGE), source=source)
    return {"id": rec["id"], "created": rec["created"], "language": rec["language"], "status_url": f"/v1/voice/sessions/{rec['id']}"}


@app.post("/voiceStart")
async def op_voice_start(request: Request, language: str | None = Query(None), source: str = Query("mic")) -> dict[str, Any]:
    return await voice_start(request, language, source)


async def _voice_segment(sid: str, index: int, file: UploadFile | None, language: str | None,
                         beam_size: int | None, vad: bool | None, words: bool | None) -> Response:
    if file is None or not file.filename:
        raise HTTPException(400, "send the segment as multipart 'file'")
    try:
        upload = JOBS.save_upload(file.file, file.filename)
    except TooLong as exc:
        raise HTTPException(413, f"segment is too long: {exc}") from None
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from None
    try:
        entry = SESSIONS.add_segment(sid, index, upload, _options(language, beam_size, vad, words))
    except KeyError:
        raise HTTPException(404, f"unknown live session '{sid}'") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"retry-after": "15"}) from None
    return JSONResponse({"session": sid, "index": entry["index"], "job_id": entry["job_id"],
                         "duration": entry.get("duration"), "status": "queued"}, status_code=202)


@app.post("/v1/voice/sessions/{sid}/segments")
async def voice_segment(
    sid: str,
    file: UploadFile | None = File(None),
    index: int = Form(0),
    language: str | None = Form(None),
    beam_size: int | None = Query(None),
    vad: bool | None = Query(None),
    words: bool | None = Query(None),
) -> Response:
    return await _voice_segment(sid, index, file, language, beam_size, vad, words)


@app.post("/voiceSegment")
async def op_voice_segment(
    file: UploadFile | None = File(None),
    session: str = Query(...),
    index: int = Form(0),
    language: str | None = Form(None),
    beam_size: int | None = Query(None),
    vad: bool | None = Query(None),
    words: bool | None = Query(None),
) -> Response:
    return await _voice_segment(session, index, file, language, beam_size, vad, words)


@app.get("/v1/voice/sessions/{sid}")
def voice_status(sid: str) -> Response:
    view = SESSIONS.status(sid)
    if view is None:
        raise HTTPException(404, f"unknown live session '{sid}'")
    return JSONResponse(view)


@app.get("/voiceStatus")
def op_voice_status(session: str = Query(...)) -> Response:
    return voice_status(session)


@app.post("/v1/voice/sessions/{sid}/finish")
def voice_finish(
    sid: str,
    language: str | None = Query(None),
    beam_size: int | None = Query(None),
) -> Response:
    """Join the segments and run the accurate second pass over the whole utterance."""
    try:
        # the final pass is deliberately the faithful configuration: VAD off (it drops short
        # trailing speech — measured), beam 5, word timestamps on.
        result = SESSIONS.finish(sid, _options(language, beam_size or 5, False, True))
    except KeyError:
        raise HTTPException(404, f"unknown live session '{sid}'") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"retry-after": "15"}) from None
    return JSONResponse({**result, "status": "queued"}, status_code=202)


@app.post("/voiceFinish")
def op_voice_finish(session: str = Query(...), language: str | None = Query(None), beam_size: int | None = Query(None)) -> Response:
    return voice_finish(session, language, beam_size)


@app.post("/v1/voice/sessions/{sid}/export")
def voice_export(sid: str) -> Response:
    """The whole recording as one playable WAV — what lets a caller send the voice note itself."""
    path = SESSIONS.export(sid)
    if path is None:
        raise HTTPException(404, f"live session '{sid}' has no audio")
    with open(path, "rb") as handle:
        body = handle.read()
    return Response(body, media_type="audio/wav",
                    headers={"content-disposition": f'attachment; filename="voice-{sid}.wav"'})


@app.post("/voiceExport")
def op_voice_export(session: str = Query(...)) -> Response:
    return voice_export(session)


@app.post("/v1/voice/sessions/{sid}/cancel")
def voice_cancel(sid: str) -> dict[str, Any]:
    result = SESSIONS.cancel(sid)
    if result is None:
        raise HTTPException(404, f"unknown live session '{sid}'")
    return result


@app.post("/voiceCancel")
def op_voice_cancel(session: str = Query(...)) -> dict[str, Any]:
    return voice_cancel(session)


def main() -> None:
    import threading

    import uvicorn

    port = int(os.environ.get("PORT", "8987"))
    LOG.info("starting %s on :%d (model %s@%s, idle unload %ss)", SERVICE, port, ENGINE.repo, ENGINE.revision,
             ENGINE.idle_unload_seconds)
    def _prune_loop() -> None:
        import time as _time

        while True:
            _time.sleep(900)
            try:
                removed = SESSIONS.prune()
                if removed:
                    LOG.info("pruned %d finished live session(s)", removed)
            except Exception:  # noqa: BLE001
                LOG.exception("live-session prune failed")

    threading.Thread(target=_prune_loop, name="asr-session-prune", daemon=True).start()
    if os.environ.get("SPEECH_PREFETCH", "0") == "1":
        import threading

        threading.Thread(target=lambda: ENGINE.ensure_model(), name="asr-prefetch", daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=os.environ.get("LOG_LEVEL", "info").lower(),
                timeout_keep_alive=75)


if __name__ == "__main__":
    main()
