#!/usr/bin/env python3
"""STOI of timeline-preserving processed files against the clean stream (cheap pre-screen, not the metric).
usage: stoi_screen.py DATA_DIR NAME method1 method2 ...   (NAME = s0_mask103; clean = stream/s0.wav)"""
import os
import sys

import numpy as np
import soundfile as sf
from pystoi import stoi

d, name, methods = sys.argv[1], sys.argv[2], sys.argv[3:]
stream = name.split("_")[0]
c, sr = sf.read(os.path.join(d, "stream", stream + ".wav"), dtype="float32")
assert sr == 16000
dm, _ = sf.read(os.path.join(d, "dmg16", name + ".wav"), dtype="float32")
n = min(len(c), len(dm))
print(f"{name}: damaged STOI {stoi(c[:n], dm[:n], 16000):.3f}")
for m in methods:
    p = os.path.join(d, "proc", m, name + ".wav")
    if not os.path.exists(p):
        continue
    y, _ = sf.read(p, dtype="float32")
    n = min(len(c), len(y))
    if abs(len(y) - len(c)) > 0.05 * len(c):
        print(f"  {m:12s} (timeline changed: {len(y)/16000:.1f}s vs {len(c)/16000:.1f}s; STOI n/a)")
        continue
    print(f"  {m:12s} STOI {stoi(c[:n], y[:n], 16000):.3f}")
