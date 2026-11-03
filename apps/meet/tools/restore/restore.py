#!/usr/bin/env python3
"""Restore a Jibri recording whose audio is chopped into short sound bursts separated by exact-zero gaps.

usage: restore.py IN.wav OUT.wav --mode {none,edge,inpaint,cut} [--start S --end E]
       [--inpaint-max 0.12] [--cut-min 0.30] [--pause 0.25] [--no-edgefix] [--map OUT.map.json]

Steps
 1. find zero runs (>= 2 ms) and the sound bursts between them (bursts < 2 ms are dropped as zero);
 2. edge fix: each burst was faded in/out over ~4 ms by the source; the first/last 3 ms (below -40 dB)
    are trimmed and the remaining 2.5 ms ramp is gain-compensated (capped at +18 dB);
 3. mode inpaint: every gap <= inpaint-max is filled with packet-loss-concealment style material:
    pitch-period repetition (voiced) or chunk time-reversal repetition (unvoiced) extrapolated forward
    from the left burst and backward from the right burst, cross-faded across the gap, level-matched
    to the neighbours and attenuated towards the middle for longer gaps. Timeline unchanged.
    mode cut: gaps < cut-min are removed (bursts joined with a 2 ms raised-cosine crossfade); longer
    gaps are shortened to `pause` seconds. Timeline compressed; OUT.map.json maps output->source time.
    mode edge: edge fix only. mode none: passthrough (excerpt/mono only).
"""
import argparse
import json

import numpy as np
import soundfile as sf

ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--mode", default="inpaint", choices=["none", "edge", "inpaint", "cut"])
ap.add_argument("--start", type=float, default=None)
ap.add_argument("--end", type=float, default=None)
ap.add_argument("--inpaint-max", type=float, default=0.12)
ap.add_argument("--cut-min", type=float, default=0.30)
ap.add_argument("--pause", type=float, default=0.25)
ap.add_argument("--no-edgefix", action="store_true")
ap.add_argument("--keep-short", action="store_true",
                help="cut mode: keep gaps shorter than cut-min as they are (zeros kept); only longer gaps are shortened")
ap.add_argument("--map", default=None)
ap.add_argument("--stats", default=None)
a = ap.parse_args()

info = sf.info(a.inp)
sr = info.samplerate
s0 = int((a.start or 0) * sr)
s1 = int(a.end * sr) if a.end else None
x, _ = sf.read(a.inp, dtype="float32", always_2d=True, start=s0, stop=s1)
m = x[:, 0] if x.shape[1] == 1 else x.mean(axis=1).astype(np.float32)
del x
m = np.ascontiguousarray(m)
n = len(m)
ms = sr // 1000

# ---- 1. zero runs / bursts ---------------------------------------------------------------------
z = np.abs(m) < 1e-7
dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
keep = (ze - zs) >= 2 * ms
zs, ze = zs[keep], ze[keep]
bs, be = np.concatenate([[0], ze]), np.concatenate([zs, [n]])
ok = (be - bs) >= 2 * ms
# bursts shorter than 2 ms become zero (merged into the surrounding gap)
for s, e in zip(bs[~ok], be[~ok]):
    m[s:e] = 0.0
bs, be = bs[ok], be[ok]
if len(bs) == 0:
    sf.write(a.out, m, sr, subtype="FLOAT")
    raise SystemExit("no sound bursts")
gaps_s, gaps_e = be[:-1], bs[1:]          # zero gaps between consecutive bursts
glen = gaps_e - gaps_s
stats = {"sr": sr, "duration_s": n / sr, "bursts": int(len(bs)), "gaps": int(len(glen)),
         "sound_s": float((be - bs).sum() / sr),
         "gaps_le_inpaint_max": int((glen <= a.inpaint_max * sr).sum()),
         "gaps_lt_cut_min": int((glen < a.cut_min * sr).sum())}

# ---- 2. edge fix -------------------------------------------------------------------------------
TRIM = 3 * ms
RAMP = int(2.5 * ms)
if a.mode != "none" and not a.no_edgefix:
    w = 0.5 * (1 - np.cos(np.pi * (np.arange(RAMP) + 0.5) / RAMP))      # the residual raised-cosine fade
    g = (1.0 / np.maximum(w, 1 / 4.0)).astype(np.float32)               # cap +12 dB
    nbs, nbe = [], []
    for s, e in zip(bs, be):
        if e - s < 2 * TRIM + 2 * RAMP + 4 * ms:
            m[s:e] = 0.0                       # too short to carry anything once its fades are gone
            continue
        m[s:s + TRIM] = 0.0
        m[e - TRIM:e] = 0.0
        s2, e2 = s + TRIM, e - TRIM
        m[s2:s2 + RAMP] *= g
        m[e2 - RAMP:e2] *= g[::-1]
        # a ramp whose fade was not the modelled one would spike: keep it under the burst's own level
        ref = 1.2 * float(np.max(np.abs(m[s2 + RAMP:s2 + RAMP + 5 * ms])) + 1e-6)
        np.clip(m[s2:s2 + RAMP], -ref, ref, out=m[s2:s2 + RAMP])
        ref = 1.2 * float(np.max(np.abs(m[e2 - RAMP - 5 * ms:e2 - RAMP])) + 1e-6)
        np.clip(m[e2 - RAMP:e2], -ref, ref, out=m[e2 - RAMP:e2])
        nbs.append(s2); nbe.append(e2)
    bs, be = np.array(nbs), np.array(nbe)
    gaps_s, gaps_e = be[:-1], bs[1:]
    glen = gaps_e - gaps_s
    stats["bursts_after_edgefix"] = int(len(bs))

# ---- helpers for PLC-style fill ----------------------------------------------------------------
def pitch_period(ctx):
    """Lag (samples) of the strongest normalised autocorrelation peak in 2-15 ms, or 0 if unvoiced."""
    lo, hi = 2 * ms, 15 * ms
    if len(ctx) < hi + 5 * ms:
        return 0
    c = ctx - ctx.mean()
    N = len(c)
    best, bl = 0.0, 0
    for lag in range(lo, hi):
        a_, b_ = c[lag:], c[: N - lag]
        den = np.sqrt((a_ ** 2).sum() * (b_ ** 2).sum()) + 1e-12
        r = (a_ * b_).sum() / den
        if r > best:
            best, bl = r, lag
    return bl if best > 0.5 else 0


def extrapolate_forward(left, length):
    """Material continuing `left` (its end) for `length` samples."""
    ctx = left[-30 * ms:] if len(left) >= 30 * ms else left
    P = pitch_period(ctx)
    if P:
        unit = left[-P:]
        reps = length // P + 2
        return np.tile(unit, reps)[:length]
    chunk = left[-10 * ms:] if len(left) >= 10 * ms else left
    pieces, flip = [], True
    while sum(len(p) for p in pieces) < length:
        pieces.append(chunk[::-1] if flip else chunk)
        flip = not flip
    return np.concatenate(pieces)[:length]


def extrapolate_backward(right, length):
    """Material leading into `right` (its start) for `length` samples, phase-aligned at the boundary."""
    ctx = right[: 30 * ms] if len(right) >= 30 * ms else right
    P = pitch_period(ctx)
    if P:
        unit = right[:P]
        reps = length // P + 2
        t = np.tile(unit, reps)
        return t[len(t) - length:]
    chunk = right[: 10 * ms] if len(right) >= 10 * ms else right
    pieces, flip = [], True
    while sum(len(p) for p in pieces) < length:
        pieces.append(chunk[::-1] if flip else chunk)
        flip = not flip
    t = np.concatenate(pieces)
    return t[len(t) - length:]


def rms(v):
    return float(np.sqrt(np.mean(v ** 2)) + 1e-9)


# ---- 3. modes ----------------------------------------------------------------------------------
if a.mode == "inpaint":
    filled = 0
    filled_s = 0.0
    XF = 1 * ms                                   # overlap into the bursts at both ends
    for i in range(len(glen)):
        L = int(glen[i])
        if L > a.inpaint_max * sr:
            continue
        gs, ge = int(gaps_s[i]), int(gaps_e[i])
        left = m[bs[i]:be[i]]
        right = m[bs[i + 1]:be[i + 1]]
        if len(left) < 6 * ms or len(right) < 6 * ms:
            continue
        T = L + 2 * XF                            # fill spans XF into each neighbour
        fwd = extrapolate_forward(left[:-XF] if len(left) > XF else left, T)
        bwd = extrapolate_backward(right[XF:] if len(right) > XF else right, T)
        # level: match each side's last/first 10 ms, never louder than the quieter neighbour
        lv_l, lv_r = rms(left[-10 * ms:]), rms(right[: 10 * ms])
        fwd *= min(1.0, lv_l / rms(fwd)) if rms(fwd) > lv_l else 1.0
        bwd *= min(1.0, lv_r / rms(bwd)) if rms(bwd) > lv_r else 1.0
        wv = 0.5 * (1 - np.cos(np.pi * (np.arange(T) + 0.5) / T))       # 0 -> 1 across the fill
        fill = (1 - wv) * fwd + wv * bwd
        if L > 40 * ms:                           # longer fills: duck the middle (less buzz)
            duck = 1 - 0.5 * np.sin(np.pi * np.arange(T) / T)
            fill *= duck
        # overlap-add into the neighbours' edges
        o0, o1 = gs - XF, ge + XF
        seg = m[o0:o1].copy()
        wi = np.ones(T, dtype=np.float32)
        wi[:XF] = np.linspace(0, 1, XF, endpoint=False)
        wi[-XF:] = np.linspace(1, 0, XF, endpoint=False)
        m[o0:o1] = seg * (1 - wi) + fill.astype(np.float32) * wi
        filled += 1
        filled_s += L / sr
    stats.update(filled=filled, filled_s=filled_s)
    out = m
    tmap = None

elif a.mode == "cut":
    XF = 2 * ms
    wxf = 0.5 * (1 - np.cos(np.pi * (np.arange(XF) + 0.5) / XF)).astype(np.float32)
    pause = np.zeros(int(a.pause * sr), dtype=np.float32)
    pieces, tmap = [], []          # tmap: [out_start_s, src_start_s, length_s]
    pos = 0
    first = next(i for i in range(len(bs)) if be[i] - bs[i] >= 2 * XF)
    cur = m[bs[first]:be[first]].copy()
    cur_src = int(bs[first])
    cur_end = int(be[first])
    removed, shortened = 0, 0
    for i in range(first + 1, len(bs)):
        if be[i] - bs[i] < 2 * XF:
            continue                       # too short to crossfade: counts as part of the gap
        nxt = m[bs[i]:be[i]].copy()
        gap = int(bs[i] - cur_end)
        cur_end = int(be[i])
        if a.keep_short and gap < a.cut_min * sr:
            # keep the gap as it is: extend cur with the zeros and the next burst (no map break needed)
            cur = np.concatenate([cur, np.zeros(gap, dtype=np.float32), nxt])
            continue
        if gap < a.cut_min * sr:
            # join with crossfade: last XF of cur fades out over first XF of nxt
            cur[-XF:] = cur[-XF:] * wxf[::-1] + nxt[:XF] * wxf
            tmap.append([pos / sr, cur_src / sr, (len(cur) - XF) / sr])
            pieces.append(cur[:-XF] if False else cur)   # keep full cur; nxt loses its first XF
            pos += len(cur)
            cur = nxt[XF:]
            cur_src = int(bs[i]) + XF
            removed += 1
        else:
            tmap.append([pos / sr, cur_src / sr, len(cur) / sr])
            pieces.append(cur); pos += len(cur)
            pieces.append(pause); pos += len(pause)
            cur = nxt
            cur_src = int(bs[i])
            shortened += 1
    tmap.append([pos / sr, cur_src / sr, len(cur) / sr])
    pieces.append(cur)
    out = np.concatenate(pieces).astype(np.float32)
    stats.update(gaps_removed=removed, gaps_shortened=shortened, out_duration_s=len(out) / sr)
else:
    out = m
    tmap = None

np.clip(out, -0.999, 0.999, out=out)      # the source itself touches full scale; no global rescale
sf.write(a.out, out, sr, subtype="FLOAT")
if a.map and tmap is not None:
    json.dump({"offset_s": a.start or 0, "segments": tmap}, open(a.map, "w"))
if a.stats:
    json.dump(stats, open(a.stats, "w"), indent=1)
print(json.dumps(stats))
