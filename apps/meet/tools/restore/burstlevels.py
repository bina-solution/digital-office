#!/usr/bin/env python3
"""Are the long zero holes in a speech region pauses or lost audio?  Look at what the bursts contain.
usage: burstlevels.py FILE44.wav START END
If the microphone streamed continuously, the bursts between words carry room noise (quiet but not zero), and a
pause in speech shows up as quiet BURSTS, not as exact zeros.  Prints the RMS distribution of bursts and, for
bursts adjacent to long holes (> 0.3 s), their level on both sides of the hole."""
import sys

import numpy as np
import soundfile as sf

p, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
info = sf.info(p)
sr = info.samplerate
x, _ = sf.read(p, dtype="float32", always_2d=True, start=int(t0 * sr), stop=int(t1 * sr))
m = x.mean(axis=1)
n = len(m)
ms = sr // 1000
z = np.abs(m) < 1e-7
dz = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
keep = (ze - zs) >= 2 * ms
zs, ze = zs[keep], ze[keep]
bs, be = np.concatenate([[0], ze]), np.concatenate([zs, [n]])
ok = (be - bs) >= 10 * ms
bs, be = bs[ok], be[ok]
rms = np.array([np.sqrt(np.mean(m[s:e] ** 2)) for s, e in zip(bs, be)])
db = 20 * np.log10(rms + 1e-9)
print(f"{p} {t0}-{t1}: {len(bs)} bursts >= 10 ms; burst RMS dBFS p5/p25/p50/p75/p95: {np.percentile(db,[5,25,50,75,95]).round(1)}")
print(f"   bursts quieter than -50 dBFS: {(db < -50).mean():.1%}, -45: {(db < -45).mean():.1%}, -40: {(db < -40).mean():.1%}")
# the quietest 1-ms slice inside each burst (noise floor the mic sends between words)
floors = []
for s, e in zip(bs, be):
    seg = m[s + 3 * ms: e - 3 * ms]
    k = len(seg) // ms
    if k < 3:
        continue
    r = np.sqrt(np.mean(seg[: k * ms].reshape(k, ms) ** 2, axis=1))
    floors.append(20 * np.log10(r.min() + 1e-9))
floors = np.array(floors)
print(f"   quietest 1-ms slice per burst, dBFS p5/p50/p95: {np.percentile(floors,[5,50,95]).round(1)}; "
      f"exact-zero slices inside bursts: {(floors < -120).mean():.1%}")
# around long holes
gl = (bs[1:] - be[:-1]) / sr
long_ = np.where(gl > 0.3)[0]
pre = db[long_]; post = db[long_ + 1]
print(f"   holes > 0.3 s: {len(long_)}; burst level before/after the hole, median dBFS: {np.median(pre):.1f} / {np.median(post):.1f}; "
      f"before < -45 dBFS: {(pre < -45).mean():.1%}, after < -45: {(post < -45).mean():.1%}")
short = np.where((gl > 0.02) & (gl < 0.08))[0]
print(f"   holes 20-80 ms: {len(short)}; burst level before/after, median dBFS: {np.median(db[short]):.1f} / {np.median(db[short + 1]):.1f}")
