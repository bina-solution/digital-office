"""Probe: where do the voices change in one recording? (DGO-1627, a developer's tool, not a test)

Embeds fixed windows across a whole file, prints the label of each window and the distance
statistics between them, so a person can pick two stretches that are clearly different voices (and
two that are clearly the same) for the committed fixtures, and can see whether the threshold is
where it should be on THIS office's audio.

    python -m asr.probe_voices /tmp/slice.mp3 --window 4 --threshold 0.62
"""
from __future__ import annotations

import argparse
import itertools
import sys

import numpy as np

from . import diarize


def pitch_hz(window: "np.ndarray", rate: int = 16000, lo: float = 70.0, hi: float = 350.0) -> float:
    """Median fundamental frequency of a window, by autocorrelation — an INDEPENDENT voice cue.

    Not used by the diarizer: it is what a person can check without listening, so a fixture can
    claim "two different voices" on evidence that does not come from the model under test."""
    import numpy as np

    x = np.asarray(window, dtype=np.float64)
    if x.size < rate // 4:
        return 0.0
    x = x - x.mean()
    spec = np.fft.rfft(x, n=2 * x.size)
    ac = np.fft.irfft(spec * np.conj(spec))[: x.size]
    ac /= (ac[0] or 1.0)
    a, b = int(rate / hi), int(rate / lo)
    if b <= a or b >= ac.size:
        return 0.0
    lag = a + int(np.argmax(ac[a:b]))
    return round(rate / lag, 1) if lag else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--window", type=float, default=4.0)
    ap.add_argument("--duration", type=float, default=180.0)
    ap.add_argument("--threshold", type=float, default=diarize.THRESHOLD)
    args = ap.parse_args()

    spans = [(i * args.window, min((i + 1) * args.window, args.duration))
             for i in range(int(args.duration // args.window))]
    segs = [{"id": i + 1, "start": a, "end": b, "text": ""} for i, (a, b) in enumerate(spans)]
    got = diarize.attach(segs, args.source, threshold=args.threshold)

    print("voices:", [(s["label"], s["segments"], s["seconds"]) for s in got["speakers"]])
    print("method:", got["method"])

    # the distances the threshold has to sit between: same voice vs different voice
    encoder = diarize._load_encoder()
    audio = diarize._Audio(args.source)
    embs = []
    for seg in got["segments"]:
        chunk = audio.slice(seg["start"], seg["end"])
        if chunk is not None:
            print(f"  {seg['start']:6.1f}-{seg['end']:6.1f}  {seg.get('speaker', '-'):8s} f0={pitch_hz(chunk):6.1f} Hz")
            embs.append(diarize.embed(encoder, chunk))
    if len(embs) > 1:
        m = diarize._distances(np.vstack(embs))
        labels = [s.get("speaker") for s in got["segments"]]
        same, diff = [], []
        for i, j in itertools.combinations(range(len(labels)), 2):
            (same if labels[i] == labels[j] else diff).append(m[i, j])
        if same:
            print(f"same-voice distances : min {min(same):.3f} median {np.median(same):.3f} max {max(same):.3f}")
        if diff:
            print(f"diff-voice distances : min {min(diff):.3f} median {np.median(diff):.3f} max {max(diff):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
