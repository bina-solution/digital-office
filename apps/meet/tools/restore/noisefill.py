#!/usr/bin/env python3
"""Phonemic-restoration style fill: speech-shaped noise in the zero gaps (timeline preserved).

usage: noisefill.py IN.wav OUT.wav [--level -9] [--max-gap 0.3] [--trim 0.003] [--floor -60] [--mode lpc|pink]

For each exact-zero gap (>= 2 ms, <= --max-gap): white noise filtered by an LPC(16) model of the neighbouring
bursts (20 ms each side, crossfaded across the gap), scaled to the neighbours' RMS plus --level dB, with 3-ms
raised-cosine crossfades.  --floor adds a constant low-level pink noise floor (dBFS) to the whole file (so no
sample is digital silence); set to -200 to disable.
"""
import argparse

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--level", type=float, default=-9.0)
ap.add_argument("--max-gap", type=float, default=0.3)
ap.add_argument("--trim", type=float, default=0.003)
ap.add_argument("--floor", type=float, default=-200.0)
ap.add_argument("--mode", default="lpc", choices=["lpc", "pink"])
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--chunk", type=float, default=600.0, help="process long files in pieces of this many seconds")
a = ap.parse_args()

info = sf.info(a.inp)
sr, N = info.samplerate, info.frames
ms = sr // 1000
rng = np.random.default_rng(a.seed)
TRIM = int(a.trim * sr)
XF = 3 * ms
CTX = 20 * ms
ORDER = 16
wxf = 0.5 * (1 - np.cos(np.pi * (np.arange(XF) + 0.5) / XF)).astype(np.float32)


def lpc(seg, order):
    seg = seg - seg.mean()
    if len(seg) < order * 3 or np.max(np.abs(seg)) < 1e-5:
        return None, 0.0
    w = seg * np.hanning(len(seg))
    r = np.correlate(w, w, mode="full")[len(w) - 1: len(w) + order]
    if r[0] <= 0:
        return None, 0.0
    # Levinson-Durbin
    a_ = np.zeros(order + 1); a_[0] = 1.0
    e = r[0]
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a_[1:i], r[i - 1:0:-1])
        k = -acc / e
        a_[1:i] = a_[1:i] + k * a_[i - 1:0:-1]
        a_[i] = k
        e *= (1 - k * k)
        if e <= 0:
            return None, 0.0
    return a_, e


def shaped_noise(ctx, length):
    A, e = lpc(ctx, ORDER)
    if A is None:
        return None
    exc = rng.standard_normal(length + 200).astype(np.float32)
    y = lfilter([1.0], A, exc)[200:]
    return y.astype(np.float32)


def rms(v):
    return float(np.sqrt(np.mean(v ** 2)) + 1e-9)


stats = {"gaps": 0, "filled": 0, "level_db": a.level, "mode": a.mode, "floor": a.floor}


def fill_piece(m):
    n = len(m)
    z = np.abs(m) < 1e-7
    dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
    zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
    keep = (ze - zs) >= 2 * ms
    zs, ze = zs[keep], ze[keep]
    out = m.copy()
    for gs, ge in zip(zs, ze):
        stats["gaps"] += 1
        if (ge - gs) / sr > a.max_gap:
            continue
        gs2, ge2 = gs - TRIM, ge + TRIM
        if gs2 - CTX - XF < 0 or ge2 + CTX + XF > n:
            continue
        left, right = m[gs2 - CTX - XF: gs2 - XF], m[ge2 + XF: ge2 + XF + CTX]
        L_ = ge2 - gs2 + 2 * XF
        if a.mode == "pink":
            wn = rng.standard_normal(L_ + 400).astype(np.float32)
            fl = lfilter([1.0], [1.0, -0.95], wn)[400:]          # pink-ish: one-pole lowpass
            fl = lfilter([1.0, -0.9], [1.0], fl)                  # mild pre-emphasis back -> speech-like tilt
            fill = fl.astype(np.float32)
        else:
            fl = shaped_noise(left, L_)
            fr = shaped_noise(right, L_)
            if fl is None and fr is None:
                continue
            if fl is None:
                fill = fr
            elif fr is None:
                fill = fl
            else:
                fl *= rms(left) / rms(fl); fr *= rms(right) / rms(fr)
                wv = np.linspace(0, 1, L_, dtype=np.float32)
                fill = (1 - wv) * fl + wv * fr
        target = 0.5 * (rms(left) + rms(right)) * (10 ** (a.level / 20))
        fill = fill * (target / rms(fill))
        f0, f1 = gs2 - XF, ge2 + XF
        w = np.ones(f1 - f0, dtype=np.float32)
        w[:XF] = wxf
        w[-XF:] = wxf[::-1]
        out[f0:f1] = out[f0:f1] * (1 - w) + fill[: f1 - f0] * w
        stats["filled"] += 1
    if a.floor > -150:
        wn = rng.standard_normal(n + 400).astype(np.float32)
        pk = lfilter([1.0], [1.0, -0.97], wn)[400:].astype(np.float32)
        pk *= (10 ** (a.floor / 20)) / rms(pk)
        out += pk
    np.clip(out, -0.999, 0.999, out=out)
    return out


# whole file, or pieces split inside sound bursts (bounded memory for hour-long recordings)
CHUNK, OV = int(a.chunk * sr), int(1.0 * sr)
with sf.SoundFile(a.out, "w", samplerate=sr, channels=1, subtype="FLOAT") as fo:
    if N <= CHUNK + CHUNK // 2:
        x, _ = sf.read(a.inp, dtype="float32", always_2d=True)
        fo.write(fill_piece(x.mean(axis=1).astype(np.float32)))
    else:
        pos = 0
        while pos < N:
            nominal = min(N, pos + CHUNK)
            end = nominal
            if nominal < N:
                a0 = max(pos + CHUNK // 2, nominal - 10 * sr)
                probe, _ = sf.read(a.inp, dtype="float32", always_2d=True, start=a0, stop=min(N, nominal + 10 * sr))
                nz = np.abs(probe.mean(axis=1)) > 1e-6
                d = np.diff(np.concatenate([[0], nz.astype(np.int8), [0]]))
                bs, be = np.where(d == 1)[0], np.where(d == -1)[0]
                good = (be - bs) >= 20 * ms
                if good.any():
                    mids = (bs[good] + be[good]) // 2 + a0
                    end = int(mids[np.argmin(np.abs(mids - nominal))])
            r0, r1 = max(0, pos - OV), min(N, end + OV)
            piece, _ = sf.read(a.inp, dtype="float32", always_2d=True, start=r0, stop=r1)
            y = fill_piece(piece.mean(axis=1).astype(np.float32))
            fo.write(y[pos - r0: pos - r0 + (end - pos)])
            pos = end
print(stats)
