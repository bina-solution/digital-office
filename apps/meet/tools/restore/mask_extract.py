#!/usr/bin/env python3
"""Extract the exact burst/zero damage mask from a damaged recording.

usage: mask_extract.py IN_44k.wav OUT.json [--min-len 150] [--window 1.0]

Finds exact-zero runs (>= 2 ms), computes the per-second fraction of non-zero samples and picks the
longest stretch of consecutive seconds in which that fraction is between `lo` and `hi` (someone is
talking through the throttled recorder: bursts present, but not continuous audio) with at most `maxgap`
seconds of all-zero windows inside it.  Writes the zero runs inside that stretch as a mask
(seconds, relative to the stretch start) plus statistics.
"""
import argparse
import json

import numpy as np
import soundfile as sf

ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--min-len", type=float, default=150.0, help="minimum stretch length (s)")
ap.add_argument("--lo", type=float, default=0.15)
ap.add_argument("--hi", type=float, default=0.95)
ap.add_argument("--maxgap", type=float, default=4.0, help="max run of all-zero seconds inside a stretch")
ap.add_argument("--region", type=str, default=None, help="force region START:END seconds")
ap.add_argument("--densest", type=float, default=None,
                help="instead of the longest stretch, take the N-second window with the highest sound fraction")
a = ap.parse_args()

info = sf.info(a.inp)
sr = info.samplerate
x, _ = sf.read(a.inp, dtype="float32", always_2d=True)
m = x[:, 0] if x.shape[1] == 1 else x.mean(axis=1).astype(np.float32)
del x
n = len(m)
ms = sr // 1000
z = np.abs(m) < 1e-7
# zero runs >= 2 ms; anything shorter counts as sound
dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
keep = (ze - zs) >= 2 * ms
zs, ze = zs[keep], ze[keep]
zmask = np.zeros(n, dtype=bool)
for s, e in zip(zs, ze):
    zmask[s:e] = True

# per-second fraction of sound
nsec = n // sr
frac = 1.0 - zmask[: nsec * sr].reshape(nsec, sr).mean(axis=1)
print("seconds:", nsec, " sound fraction p50 over seconds with any sound:",
      float(np.median(frac[frac > 0])) if (frac > 0).any() else None)

if a.region:
    r0, r1 = [float(v) for v in a.region.split(":")]
elif a.densest:
    W = int(a.densest)
    cs = np.concatenate([[0.0], np.cumsum(frac)])
    dens = (cs[W:] - cs[:-W]) / W
    i0 = int(np.argmax(dens))
    r0, r1 = float(i0), float(i0 + W)
    print(f"densest {W}-s window: {r0:.0f}-{r1:.0f} s, mean sound fraction {dens[i0]:.3f}")
else:
    # stretches: seconds with lo<=frac<=hi, allowing runs of up to maxgap all-zero seconds inside
    good = (frac >= a.lo) & (frac <= a.hi)
    best = None
    i = 0
    while i < nsec:
        if not good[i]:
            i += 1
            continue
        j = i
        zero_run = 0
        last_good = i
        while j < nsec:
            if good[j]:
                zero_run = 0
                last_good = j
            elif frac[j] == 0:
                zero_run += 1
                if zero_run > a.maxgap:
                    break
            else:  # frac > hi (continuous audio) or 0<frac<lo: tolerate as part of the stretch
                zero_run = 0
                last_good = j
            j += 1
        length = last_good + 1 - i
        if best is None or length > best[1]:
            best = (i, length)
        i = last_good + 1
    r0, r1 = float(best[0]), float(best[0] + best[1])
    print(f"longest stretch: {r0:.0f}-{r1:.0f} s ({r1 - r0:.0f} s)")

s0, s1 = int(r0 * sr), int(r1 * sr)
sel = (ze > s0) & (zs < s1)
runs = [[max(int(s), s0) - s0, min(int(e), s1) - s0] for s, e in zip(zs[sel], ze[sel])]


def burst_db(a, b):
    """RMS (dBFS) of the sound between samples a and b of the region (the burst next to a hole)."""
    seg = m[s0 + max(0, a): s0 + min(s1 - s0, b)]
    return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)) if len(seg) >= 2 * ms else -120.0


# each run: [start_s, end_s, dB of the burst before it, dB of the burst after it]
runs_s = []
for i, r in enumerate(runs):
    pb = runs[i - 1][1] if i > 0 else 0
    na = runs[i + 1][0] if i + 1 < len(runs) else s1 - s0
    runs_s.append([r[0] / sr, r[1] / sr, round(burst_db(pb, r[0]), 1), round(burst_db(r[1], na), 1)])
levels = np.array([max(r[2], r[3]) for r in runs_s])
speech_ref = float(np.percentile([max(r[2], r[3]) for r in runs_s if (r[1] - r[0]) < 0.08], 75)) if runs_s else -30.0
glen = np.array([r[1] - r[0] for r in runs]) / sr
bl = np.diff(np.array([[r[0], r[1]] for r in runs]).ravel()[1:-1].reshape(-1, 2), axis=1).ravel() / sr if len(runs) > 1 else np.array([])
zero_total = float(glen.sum())
stats = {
    "source": a.inp, "sr": sr, "region_s": [r0, r1], "region_len_s": r1 - r0,
    "zero_runs": len(runs), "zero_total_s": zero_total, "zero_fraction": zero_total / (r1 - r0),
    "zero_fraction_excl_gt1s": float(glen[glen <= 1.0].sum() / ((r1 - r0) - glen[glen > 1.0].sum())),
    "gap_hist_ms": {
        "<=60": int((glen <= 0.06).sum()), "60-120": int(((glen > 0.06) & (glen <= 0.12)).sum()),
        "120-300": int(((glen > 0.12) & (glen <= 0.3)).sum()), "300-1000": int(((glen > 0.3) & (glen <= 1.0)).sum()),
        ">1000": int((glen > 1.0).sum())},
    "gap_time_s": {
        "<=60": float(glen[glen <= 0.06].sum()), "60-120": float(glen[(glen > 0.06) & (glen <= 0.12)].sum()),
        "120-300": float(glen[(glen > 0.12) & (glen <= 0.3)].sum()), "300-1000": float(glen[(glen > 0.3) & (glen <= 1.0)].sum()),
        ">1000": float(glen[glen > 1.0].sum())},
    "gap_ms_p10_p50_p90": [float(v) for v in np.percentile(glen * 1000, [10, 50, 90])] if len(glen) else None,
    "burst_ms_p10_p50_p90": [float(v) for v in np.percentile(bl * 1000, [10, 50, 90])] if len(bl) else None,
    "bursts": int(len(bl)),
    # "speech-holes" criterion: a hole counts as lost speech if the louder of its two neighbouring bursts is
    # within 12 dB of the speech level (p75 of the levels next to short holes); quieter holes are pauses
    "speech_ref_db": speech_ref,
    "long_holes": int((glen > 0.3).sum()),
    "long_holes_in_speech": int(((glen > 0.3) & (levels >= speech_ref - 12)).sum()),
    "long_hole_time_in_speech_s": float(glen[(glen > 0.3) & (levels >= speech_ref - 12)].sum()),
}
json.dump({"stats": stats, "zero_runs_s": runs_s}, open(a.out, "w"), indent=0)
print(json.dumps(stats, indent=1))
