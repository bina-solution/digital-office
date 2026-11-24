#!/usr/bin/env python3
"""test_asr_flow — every transcription is ONE bar in «כל מקביל», whichever model heard it (DGO-1886).

The owner, Telegram msg 892: «make sure also transcribes happen within the dgo and that they show up in any-concurency
of both stt models … via flow». The worker publishes on `dgo:flow:apitools` through the office's one publisher:
`transcription.started` when it takes a job, then `transcription.ended` (completed), `.cancelled` or `.failed`, sharing
`data.span`. A job is the one door every caller goes through — the inline answer, the async job, a dictation's piece —
so the bar is opened and closed in the job's own lifecycle (jobs.py `_loop`), and what is tested here is a real job
through the real worker, with the model and the publisher stood in for. A bar a kill left open is closed by the next
start (`_load_existing`), and a publisher that raises costs the job nothing.
What a person said, and the file it came in, never go out: not the words, not a file's name, not a path.

On the tree before DGO-1886 every case fails: the worker published nothing.

Run in the ASR image (it has numpy), from apps/apitools:  python3 tests/test_asr_flow.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
DATA = tempfile.mkdtemp(prefix="asr-flow-test-")
os.environ.update(SPEECH_DATA_DIR=DATA, SPEECH_MODEL_DIR=os.path.join(DATA, "models"), SPEECH_DIARIZE="0",
                  SPEECH_IDLE_UNLOAD_SECONDS="0")

from asr import jobs  # noqa: E402
from asr.engine import ENGINES  # noqa: E402

FAIL: list[str] = []
SAID = "שלום זה טקסט פרטי"           # what the audio "says": it must never reach the stream
FILE = "הקלטה-של-יוסי.ogg"           # a person's file name: nor this
#: the platform's publisher: the checkout's, or the one an office mounts; neither = stood in for
REAL = [p for p in (HERE.parent.parent / "platform-base" / "redis" / "flowpub.py", Path("/opt/dgo/flowpub.py"))
        if p.is_file()]


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


# ── the publisher: the platform's own flowpub where it can be read (its span_start/span_end write the bar), its
# `emit` recording instead of sending; where it cannot, the same three calls stood in for
def publisher():
    events: list[dict] = []
    if REAL:
        spec = importlib.util.spec_from_file_location("flowpub_under_test", REAL[0])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        def emit(app, type_, title, data=None, link=""):
            events.append({"app": app, "type": type_, "title": title, "data": dict(data or {}),
                           "contract": mod.fields_of(app, type_, title, data, link) is not None})
            return True
        mod.emit = emit
        return mod, events

    class Pub:
        def emit(self, app, type_, title, data=None, link=""):
            events.append({"app": app, "type": type_, "title": title, "data": dict(data or {})})
            return True

        def span_start(self, app, kind, title, data=None, link=""):
            sid = f"s{len(events)}"
            t0 = int(time.time() * 1000)
            self.emit(app, f"{kind}.started", title, {**(data or {}), "span": sid})
            return sid, t0, True

        def span_end(self, app, kind, title, sid, t0, failed=False, data=None, link=""):
            return self.emit(app, f"{kind}.{'failed' if failed else 'ended'}", title,
                             {**(data or {}), "span": sid, "t0": t0, "ms": max(0, int(time.time() * 1000) - t0)})
    return Pub(), events


class Raising:                       # a publisher that breaks at every call: the job must not notice
    def __getattr__(self, name):
        def boom(*a, **kw):
            raise RuntimeError("redis is on fire")
        return boom


# ── the model: two segments of SAID, the length it was told
class Seg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text, self.avg_logprob, self.words = start, end, text, -0.2, None


class Info:
    def __init__(self, duration):
        self.duration, self.language, self.language_probability = duration, "he", 0.98


class Model:
    def __init__(self, duration, fail=False, cancel=False):
        self.duration, self.fail, self.cancel = duration, fail, cancel

    def transcribe(self, audio, **kw):
        if self.fail:
            raise RuntimeError(f"cannot decode {DATA}/uploads/{FILE}")
        half = (self.duration or 4.0) / 2

        def segments():
            if self.cancel:                      # the client cancels while the model is at work
                jobs.JOBS.cancel(jobs.JOBS._current)
            yield Seg(0.0, half, SAID)
            yield Seg(half, half * 2, SAID)
        return segments(), Info(self.duration)


def ended(events):
    return any(e["type"].rsplit(".", 1)[-1] in ("ended", "failed", "cancelled") for e in events)


def run(model, duration, kind="upload", fail=False, told=True, cancel=False, language="he", pub=None):
    """One job through the real queue and worker; the events it gave, once the worker let go of it."""
    events: list[dict] = []
    if pub is None:
        pub, events = publisher()
    jobs.flowpub = pub
    for engine in ENGINES.values():
        engine._model = Model(duration, fail, cancel)
    path = os.path.join(DATA, "uploads", FILE)
    open(path, "wb").close()
    source = {"path": path, "name": FILE, "bytes": 0, "duration": duration if told else None, "kind": kind}
    if kind == "voice-segment":
        source.update(session_id="vs_test", index=0)
    job = jobs.JOBS.submit(source, {"model": model, "language": language})
    job.wait(10)
    end = time.time() + 10
    while time.time() < end and (jobs.JOBS._current or not jobs.JOBS._queue.empty() or (events and not ended(events))):
        time.sleep(0.02)
    return job, events


def bar_of(job, events, label, end_type="transcription.ended"):
    started = [e for e in events if e["type"] == "transcription.started"]
    ends = [e for e in events if e["type"] != "transcription.started"]
    check(len(started) == 1 and len(ends) == 1, f"{label}: one started and one end ({[e['type'] for e in events]})")
    if not (started and ends):
        return None, None
    s, e = started[0], ends[0]
    check(e["type"] == end_type, f"{label}: the bar ends as {end_type} (got {e['type']})")
    check(s["app"] == e["app"] == "apitools", f"{label}: on dgo:flow:apitools (got {s['app']!r})")
    check(s["data"].get("span") and s["data"]["span"] == e["data"].get("span"), f"{label}: the two share data.span")
    check(s["data"].get("job") == e["data"].get("job") == job.id, f"{label}: data.job is the job's id")
    check(isinstance(e["data"].get("ms"), int) and isinstance(e["data"].get("t0"), int),
          f"{label}: the end carries the elapsed time (data.ms, data.t0)")
    check(s["data"].get("model") == e["data"].get("model") == job.options["model"], f"{label}: data.model")
    blob = repr(events)
    check(SAID not in blob and "שלום" not in blob, f"{label}: no word of the transcript on the stream")
    check(FILE not in blob and DATA not in blob and "/uploads" not in blob, f"{label}: no file name, no path")
    check(all(ev.get("contract", True) for ev in events), f"{label}: every event passes flowpub's contract")
    return s, e


def main() -> int:
    print(f"      (publisher: {'the platform flowpub, ' + str(REAL[0]) + ', emit recorded' if REAL else 'stood in for'})")

    # each model, a 3:06 voice note
    for model in ("ivrit", "whisper"):
        job, events = run(model, 186.0)
        s, e = bar_of(job, events, model)
        if s:
            check(s["title"] == f"תמלול 3:06 דק׳ · {model}", f"{model}: the title a person reads (got «{s['title']}»)")
            check(s["data"].get("audio_seconds") == 186.0 and s["data"].get("language") == "he",
                  f"{model}: data.audio_seconds and data.language at the start")
            check(e["data"].get("status") == "completed" and e["data"].get("segments") == 2,
                  f"{model}: the end says completed, and how many segments")

    # a job that fails ends its bar as failed, with the error's code and never its message (it names the file)
    job, events = run("ivrit", 40.0, fail=True)
    s, e = bar_of(job, events, "a failed job", "transcription.failed")
    if e:
        check(e["data"].get("error") == "internal_error", f"a failed job: data.error is its code (got {e['data'].get('error')})")

    # a cancel while the model works is drawn as a cancel, not as a finished job
    job, events = run("whisper", 30.0, cancel=True)
    s, e = bar_of(job, events, "a cancelled job", "transcription.cancelled")
    check(job.status == "cancelled", f"a cancelled job: the job itself was cancelled (got {job.status})")

    # a dictation's piece says so; a job without a length (a `path` the header does not give) still has its bar
    job, events = run("whisper", 4.0, kind="voice-segment")
    s, e = bar_of(job, events, "a dictation piece")
    if s:
        check(s["title"] == "תמלול 0:04 דק׳ · whisper · קטע הכתבה", f"a dictation piece: its title (got «{s['title']}»)")
    job, events = run("ivrit", 0.0, kind="path", told=False)
    s, e = bar_of(job, events, "an unmeasured path")
    if s:
        check(s["title"] == "תמלול · ivrit", f"an unmeasured path: a title without a length (got «{s['title']}»)")

    # the caller's `language` is its own free text: only a language code goes out
    words = "דברים שאמרתי בפגישה"
    job, events = run("ivrit", 10.0, language=words)
    s, e = bar_of(job, events, "free text as language")
    check(words not in repr(events), "free text as language: it does not reach the stream")

    # the publisher breaking at every call costs the job nothing
    job, _ = run("ivrit", 10.0, pub=Raising())
    check(job.status == "completed" and SAID in job.text(), f"a raising publisher: the job still completes (got {job.status})")

    # a kill mid-job (past the memory cap, EXF-272) left a bar open: the next start closes it, as failed/interrupted
    job, _ = run("ivrit", 60.0)
    rec_path = os.path.join(DATA, "jobs", f"{job.id}.json")
    rec = json.load(open(rec_path, encoding="utf-8"))
    check(bool(rec.get("flow", {}).get("span")), "a job's record keeps its bar (job.flow) for the restart")
    rec.update(status="processing", ended=None, result=None, error=None)
    json.dump(rec, open(rec_path, "w", encoding="utf-8"))
    pub, events = publisher()
    jobs.flowpub = pub
    jobs.Jobs()                                    # the process after the kill, over the same records
    deadline = time.time() + 5
    while time.time() < deadline and not events:
        time.sleep(0.02)
    mine = [e for e in events if e["data"].get("job") == job.id]
    check(len(mine) == 1 and mine[0]["type"] == "transcription.failed" and mine[0]["data"].get("error") == "interrupted"
          and mine[0]["data"].get("span") == rec["flow"]["span"],
          f"a killed job: the restart closes its bar as failed/interrupted ({[(e['type'], e['data'].get('error')) for e in mine]})")
    check(len(events) == len(mine), f"a killed job: no other job's bar is touched ({len(events)} events)")

    # the publisher reaches the container: the platform file mounted read-only, the redis password passed
    compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
    block = re.search(r"^  apitools-asr:\n(.*?)(?=^\S|^  \S)", compose, re.M | re.S)
    body = block.group(1) if block else ""
    check("../../platform-base/redis/flowpub.py:/opt/dgo/flowpub.py:ro" in body,
          "apitools-asr mounts the platform's flowpub.py read-only at /opt/dgo")
    check(re.search(r"^\s*- REDIS_PASSWORD=\$\{REDIS_PASSWORD", body, re.M) is not None,
          "apitools-asr is given the redis password")

    print(f"\n{'all passed' if not FAIL else f'{len(FAIL)} failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
