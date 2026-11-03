#!/usr/bin/env python3
"""How much of each spoken word survives the mask?  (the physical ceiling of any restoration)

usage: ceiling.py HYP.json DATA_DIR STREAM MASK...   e.g. ceiling.py asr_turbo_b5.json data s0 mask103 mask104
Uses the word timestamps of the CLEAN transcription of stream/<STREAM>.wav as word spans, and the exact-zero
samples of dmg/<STREAM>_<MASK>.wav.  Reports the distribution of the surviving fraction per word."""
import json
import sys

import numpy as np
import soundfile as sf

hyp, d, stream, masks = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
h = json.load(open(hyp, encoding="utf-8"))[f"stream/{stream}.wav"]
words = [(w[1], w[2]) for s in h["segments"] for w in s["words"] if w[2] > w[1]]
print(f"{stream}: {len(words)} recognised words in the clean stream, median length {np.median([e - s for s, e in words])*1000:.0f} ms")
for mk in masks:
    x, sr = sf.read(f"{d}/dmg/{stream}_{mk}.wav", dtype="float32")
    z = np.abs(x) < 1e-7
    surv = []
    for s, e in words:
        a, b = int(s * sr), int(e * sr)
        if b <= a:
            continue
        surv.append(1.0 - z[a:b].mean())
    surv = np.array(surv)
    print(f"  {mk}: zero fraction of file {z.mean():.3f}; per-word surviving fraction: "
          f"mean {surv.mean():.2f}, p10/p50/p90 {np.percentile(surv,10):.2f}/{np.percentile(surv,50):.2f}/{np.percentile(surv,90):.2f}; "
          f"words with <30% left: {(surv < 0.3).mean():.1%}, <50%: {(surv < 0.5).mean():.1%}, 0%: {(surv <= 0.0).mean():.1%}")
    for suf, label in (("_t", "holes>0.3 s treated as pauses"), ("_s", "speech-holes: long holes only next to speech-level sound")):
        try:
            x2, _ = sf.read(f"{d}/dmg/{stream}_{mk}{suf}.wav", dtype="float32")
        except Exception:
            continue
        z2 = np.abs(x2) < 1e-7
        s2 = np.array([1.0 - z2[int(s*sr):int(e*sr)].mean() for s, e in words if int(e*sr) > int(s*sr)])
        print(f"  {mk}{suf} ({label}): zero fraction {z2.mean():.3f}; per-word surviving mean {s2.mean():.2f}, "
              f"words with <30% left: {(s2 < 0.3).mean():.1%}, 0%: {(s2 <= 0.0).mean():.1%}")
