#!/usr/bin/env python3
"""Cut the diarization fixtures out of one recording (DGO-1627).

The fixtures are committed WAVs; this script is how they were made, kept so they can be remade from
another recording instead of a hand-edit. It runs where PyAV exists (the ASR image).

    build_diarize_fixtures.py SOURCE --a 60:66 --b 90:96 --a2 66:70 [--out DIR]

  A   the first voice, six seconds            -> the first half of both fixtures
  B   a DIFFERENT voice, six seconds          -> the second half of two-voices.wav
  A2  the SAME person as A, another stretch   -> the second half of one-voice.wav

Both fixtures are A + 0.4 s of silence + the second half, so the two files differ in exactly one
thing — whether the second voice is the first person — and a diarizer that cannot tell them apart
fails one of the two tests either way.

Cutting a stretch that holds one voice is a person's job (the recording's own speaker highlight, or
listening to it); the script only refuses stretches it cannot read.
"""
from __future__ import annotations

import argparse
import os
import sys
import wave

import numpy as np

RATE = 16000
GAP = 0.4


def read(path: str, start: float, seconds: float) -> np.ndarray:
    import av

    want = int(round(seconds * RATE))
    out = np.zeros(1, dtype=np.float32)
    with av.open(path) as container:
        stream = container.streams.audio[0]
        stream.thread_type = "AUTO"
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        t = 0.0
        collected: list[np.ndarray] = []
        have = 0
        for frame in container.decode(stream):
            for block in resampler.resample(frame):
                data = np.asarray(block.to_ndarray(), dtype=np.float32).reshape(-1)
                t0, t1 = t, t + data.size / RATE
                t = t1
                if t1 <= start or t0 >= start + seconds:
                    continue
                a = max(0, int(round((start - t0) * RATE)))
                b = min(data.size, int(round((start + seconds - t0) * RATE)))
                piece = data[a:b]
                if piece.size:
                    collected.append(piece)
                    have += piece.size
                    if have >= want:
                        break
            if have >= want:
                break
    if not collected:
        raise SystemExit(f"{path}: nothing between {start:.1f}s and {start + seconds:.1f}s")
    return np.concatenate(collected)[:want]


def write(path: str, parts: list[np.ndarray]) -> None:
    gap = np.zeros(int(GAP * RATE), dtype=np.float32)
    joined = parts[0]
    for part in parts[1:]:
        joined = np.concatenate([joined, gap, part])
    clipped = np.clip(joined, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm.tobytes())
    print(f"{path}: {pcm.size / RATE:.1f}s, {os.path.getsize(path) / 1024:.0f} KB")


def span(text: str) -> tuple[float, float]:
    try:
        a, b = text.split(":")
        start, end = float(a), float(b)
    except ValueError:
        raise SystemExit(f"{text!r}: give a span as START:END in seconds") from None
    if end <= start:
        raise SystemExit(f"{text!r}: END must be after START")
    return start, end - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--a", required=True, help="first voice, START:END")
    ap.add_argument("--b", required=True, help="a different voice, START:END")
    ap.add_argument("--a2", required=True, help="the same person as --a, another START:END")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    a_start, a_len = span(args.a)
    b_start, b_len = span(args.b)
    a2_start, a2_len = span(args.a2)
    first = read(args.source, a_start, a_len)
    second = read(args.source, b_start, b_len)
    again = read(args.source, a2_start, a2_len)
    write(os.path.join(args.out, "diarize-two-voices.wav"), [first, second])
    write(os.path.join(args.out, "diarize-one-voice.wav"), [first, again])
    return 0


if __name__ == "__main__":
    sys.exit(main())
