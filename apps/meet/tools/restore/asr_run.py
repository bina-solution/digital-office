#!/usr/bin/env python3
"""Transcribe files with an ivrit-ai faster-whisper model (CPU int8) and store hypotheses with word timestamps.

usage: asr_run.py OUT.json [--model turbo|large] [--beam 5] [--temp 0 | --temp 0,0.2,0.4,0.6,0.8,1.0]
                  [--vad] [--cond] [--best-of 5] [--patience 1.0] [--threads 6] [--prefix NAME] file.wav ...

OUT.json: {"<key>": {"file":..., "secs":..., "opts":..., "segments":[{start,end,text,lp,nsp,cr,words:[[w,s,e,p],..]}]}}
key = prefix + file path.  Files already in OUT.json are skipped (resume-friendly).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("files", nargs="+")
ap.add_argument("--model", default="turbo")
ap.add_argument("--beam", type=int, default=5)
ap.add_argument("--temp", default="0")
ap.add_argument("--vad", action="store_true")
ap.add_argument("--cond", action="store_true", help="condition_on_previous_text")
ap.add_argument("--best-of", type=int, default=5)
ap.add_argument("--patience", type=float, default=1.0)
ap.add_argument("--threads", type=int, default=6)
ap.add_argument("--prefix", default="")
ap.add_argument("--no-words", action="store_true")
ap.add_argument("--lp-thresh", type=float, default=-1.0)
ap.add_argument("--cr-thresh", type=float, default=2.4)
ap.add_argument("--nsp-thresh", type=float, default=0.6)
ap.add_argument("--hotwords", default=None)
ap.add_argument("--workers", type=int, default=2, help="parallel transcriptions sharing one model (CT2 num_workers)")
a = ap.parse_args()

MODELS = {"turbo": "ivrit-ai/whisper-large-v3-turbo-ct2", "large": "ivrit-ai/whisper-large-v3-ct2"}
model_name = MODELS.get(a.model, a.model)
temps = [float(t) for t in a.temp.split(",")]
opts = {"model": model_name, "beam": a.beam, "temp": temps, "vad": a.vad, "cond": a.cond, "best_of": a.best_of,
        "patience": a.patience, "lp_thresh": a.lp_thresh, "cr_thresh": a.cr_thresh, "nsp_thresh": a.nsp_thresh}

results = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
todo = [f for f in a.files if a.prefix + f not in results]
if not todo:
    print("nothing to do"); sys.exit(0)

import threading  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

from faster_whisper import WhisperModel  # noqa: E402
t0 = time.time()
W = max(1, min(a.workers, len(todo)))
model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(1, a.threads // W), num_workers=W)
print(f"model {model_name} loaded in {time.time()-t0:.0f}s; {len(todo)} files; {W} workers x {max(1, a.threads // W)} threads", flush=True)
lock = threading.Lock()


def load16k(path):
    if path.endswith(".wav"):
        x, sr = sf.read(path, dtype="float32", always_2d=True)
        x = x.mean(axis=1).astype(np.float32)
        if sr == 16000:
            return x
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def work(f):
    t0 = time.time()
    audio = load16k(f)
    kw = dict(language="he", beam_size=a.beam, best_of=a.best_of, patience=a.patience,
              temperature=temps if len(temps) > 1 else temps[0],
              compression_ratio_threshold=a.cr_thresh, log_prob_threshold=a.lp_thresh, no_speech_threshold=a.nsp_thresh,
              vad_filter=a.vad, condition_on_previous_text=a.cond, word_timestamps=not a.no_words)
    if a.hotwords:
        kw["hotwords"] = a.hotwords
    segs, info = model.transcribe(audio, **kw)
    out = []
    for s in segs:
        words = [[w.word.strip(), round(w.start, 2), round(w.end, 2), round(w.probability, 3)] for w in (s.words or [])]
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": re.sub(r"[‎‏‪-‮]", "", s.text).strip(),
                    "lp": round(s.avg_logprob, 3), "nsp": round(s.no_speech_prob, 3), "cr": round(s.compression_ratio, 2),
                    "temp": getattr(s, "temperature", None), "words": words})
    secs = time.time() - t0
    txt = " ".join(s["text"] for s in out)
    with lock:
        results[a.prefix + f] = {"file": f, "secs": round(secs, 1), "duration": round(len(audio) / 16000, 1), "opts": opts, "segments": out}
        json.dump(results, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"### {f}: {secs:.0f}s for {len(audio)/16000:.0f}s, {len(out)} segs, {len(txt.split())} words", flush=True)


with ThreadPoolExecutor(max_workers=W) as ex:
    list(ex.map(work, todo))
print("ALLDONE", flush=True)
