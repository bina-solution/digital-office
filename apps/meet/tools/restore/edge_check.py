#!/usr/bin/env python3
"""Compare the burst-edge fade profile of a simulated damaged file with the real recording.
usage: edge_check.py FILE.wav [start end] ...   (several files; each followed optionally by a start:end region)
Prints the median 1-ms RMS profile (dB relative to the burst's p90 slice) of the first/last 8 ms of bursts 30-100 ms long,
plus the zero-run statistics, exactly like edges.py did for the original."""
import sys

import numpy as np
import soundfile as sf


def profile(path, region=None):
    info = sf.info(path)
    sr = info.samplerate
    if region:
        t0, t1 = region
        x, _ = sf.read(path, dtype="float32", always_2d=True, start=int(t0 * sr), stop=int(t1 * sr))
    else:
        x, _ = sf.read(path, dtype="float32", always_2d=True)
    m = x.mean(axis=1).astype(np.float32)
    n = len(m)
    ms = sr // 1000
    z = np.abs(m) < 1e-7
    dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
    zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
    keep = (ze - zs) >= 2 * ms
    zs, ze = zs[keep], ze[keep]
    bs, be = np.concatenate([[0], ze]), np.concatenate([zs, [n]])
    bl = (be - bs) / sr * 1000.0
    sel = (bl >= 30) & (bl <= 100)
    K = 8
    head, tail = [], []
    for s, e in zip(bs[sel], be[sel]):
        seg = m[s:e]
        nsl = len(seg) // ms
        r = np.sqrt(np.mean(seg[: nsl * ms].reshape(nsl, ms) ** 2, axis=1)) + 1e-9
        top = np.percentile(r, 90)
        head.append(20 * np.log10(r[:K] / top))
        tail.append(20 * np.log10(r[-K:] / top))
    head, tail = np.array(head), np.array(tail)
    gl = (ze - zs) / sr * 1000
    print(f"{path} {region or ''}: zero runs>=2ms {len(zs)}, gap ms p50 {np.median(gl):.1f}, bursts 30-100ms {sel.sum()}")
    print("   fade-in  dB (ms 1..8):", np.median(head, axis=0).round(1))
    print("   fade-out dB (ms -8..-1):", np.median(tail, axis=0).round(1))
    # how sharp is the edge: fraction of bursts whose 1st ms is within 6 dB of p90
    print(f"   first-ms within 6 dB of p90: {(head[:, 0] > -6).mean():.2f}; 3rd ms: {(head[:, 2] > -6).mean():.2f}")


args = sys.argv[1:]
i = 0
while i < len(args):
    p = args[i]
    reg = None
    if i + 1 < len(args) and ":" in args[i + 1] and not args[i + 1].endswith(".wav"):
        reg = tuple(float(v) for v in args[i + 1].split(":")); i += 1
    profile(p, reg)
    i += 1
