#!/usr/bin/env python3
"""Build the ground-truth benchmark: FLEURS he_il test utterances -> clean streams -> damaged streams.

usage: make_bench.py FLEURS_DIR OUT_DIR --masks mask103.json mask104.json [--n-utt 72] [--stream-max 170]

Writes
  OUT/utt/<k>.wav                 clean utterances, 16 kHz mono (k = 0..n-1)
  OUT/stream/s<j>.wav             clean streams, 16 kHz mono (utterances joined with 0.4 s silence)
  OUT/stream44/s<j>.wav           the same at 44.1 kHz (the recorder's rate)
  OUT/dmg/s<j>_<mask>[_t].wav     damaged streams, 44.1 kHz float: the real zero mask applied hard, then the
                                  recorder's AAC chain (ffmpeg aac, 44.1 kHz, 2 ch, 128 kbps, like Jibri),
                                  decoded back.  "_t" = throttle-only variant (zero runs > 0.3 s not applied)
  OUT/dmg16/...                   16 kHz mono copies of the damaged streams (the un-processed ASR baseline)
  OUT/uttdmg/<k>_<mask>.wav       damaged utterances (16 kHz) for the first mask
  OUT/refs.json                   reference transcripts: {"utt/<k>.wav": text, "stream/s<j>.wav": text, ...}
  OUT/bench.json                  what went where (utterance ids per stream, mask offsets, stats)
"""
import argparse
import csv
import json
import os
import re
import subprocess

import numpy as np
import soundfile as sf
import soxr

ap = argparse.ArgumentParser()
ap.add_argument("fleurs")
ap.add_argument("out")
ap.add_argument("--masks", nargs="+", required=True)
ap.add_argument("--n-utt", type=int, default=72)
ap.add_argument("--stream-max", type=float, default=170.0)
ap.add_argument("--gap", type=float, default=0.4, help="silence between utterances in a stream (s)")
ap.add_argument("--min-dur", type=float, default=5.0)
ap.add_argument("--max-dur", type=float, default=16.0)
ap.add_argument("--aac-bitrate", default="128k")
ap.add_argument("--utt-mask", default=None, help="mask name to apply to the utterance set (default: first)")
ap.add_argument("--variants", default="full,t", help="damage variants: full | t (throttle-only) | s (speech-holes)")
ap.add_argument("--skip-existing", action="store_true")
ap.add_argument("--no-utt", action="store_true")
a = ap.parse_args()
VARIANTS = {"full": (False, ""), "t": (True, "_t"), "s": ("speech", "_s")}
variants = [VARIANTS[v] for v in a.variants.split(",")]

SR16, SR44 = 16000, 44100
os.makedirs(a.out, exist_ok=True)
for d in ["utt", "stream", "stream44", "dmg", "dmg16", "uttdmg"]:
    os.makedirs(os.path.join(a.out, d), exist_ok=True)

# ---- 1. read the FLEURS test split ----------------------------------------------------------------
rows = []
with open(os.path.join(a.fleurs, "test.tsv"), encoding="utf-8", newline="") as f:
    for r in csv.reader(f, delimiter="\t", quotechar='"'):
        if len(r) < 4:
            continue
        rows.append({"id": int(r[0]), "file": r[1], "raw": r[2], "norm": r[3],
                     "gender": r[6] if len(r) > 6 else "?"})
rows.sort(key=lambda r: r["id"])
print("fleurs test rows:", len(rows))

cands = []
for r in rows:
    p = os.path.join(a.fleurs, "audio", "test", r["file"])
    if not os.path.exists(p):
        continue
    if re.search(r"[0-9A-Za-z]", r["raw"]):
        continue                                      # digits / Latin: normalisation ambiguity, skip
    info = sf.info(p)
    dur = info.frames / info.samplerate
    if not (a.min_dur <= dur <= a.max_dur):
        continue
    cands.append((r, p, dur))
print("candidates:", len(cands))
step = len(cands) / a.n_utt
sel = [cands[int(i * step)] for i in range(a.n_utt)]
print("selected:", len(sel), "total s:", round(sum(d for _, _, d in sel), 1),
      "genders:", {g: sum(1 for r, _, _ in sel if r["gender"] == g) for g in set(r["gender"] for r, _, _ in sel)})

refs = {}
bench = {"utterances": [], "streams": [], "masks": {}}
utts16 = []
for k, (r, p, dur) in enumerate(sel):
    x, sr = sf.read(p, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR16:
        x = soxr.resample(x, sr, SR16).astype(np.float32)
    # trim leading/trailing digital silence (keep up to 0.15 s)
    nz = np.where(np.abs(x) > 1e-4)[0]
    if len(nz):
        s0 = max(0, nz[0] - int(0.15 * SR16))
        s1 = min(len(x), nz[-1] + int(0.15 * SR16))
        x = x[s0:s1]
    # level: peak-normalise to -3 dBFS so that all utterances have a comparable level
    pk = float(np.max(np.abs(x))) + 1e-9
    x = (x * (0.7 / pk)).astype(np.float32)
    utts16.append(x)
    name = f"utt/{k}.wav"
    sf.write(os.path.join(a.out, name), x, SR16, subtype="PCM_16")
    refs[name] = r["raw"]
    bench["utterances"].append({"k": k, "fleurs_id": r["id"], "file": r["file"], "dur": round(len(x) / SR16, 2),
                                "gender": r["gender"], "raw": r["raw"]})

# ---- 2. streams --------------------------------------------------------------------------------------
gap = np.zeros(int(a.gap * SR16), dtype=np.float32)
streams, cur, cur_ids, cur_len = [], [], [], 0.0
for k, x in enumerate(utts16):
    d = len(x) / SR16 + a.gap
    if cur and cur_len + d > a.stream_max:
        streams.append((cur, cur_ids))
        cur, cur_ids, cur_len = [], [], 0.0
    cur.append(x); cur_ids.append(k); cur_len += d
if cur:
    streams.append((cur, cur_ids))
stream44 = {}
for j, (parts, ids) in enumerate(streams):
    pieces = [gap.copy()]
    for x in parts:
        pieces += [x, gap.copy()]
    s16 = np.concatenate(pieces).astype(np.float32)
    name = f"stream/s{j}.wav"
    sf.write(os.path.join(a.out, name), s16, SR16, subtype="PCM_16")
    refs[name] = " ".join(refs[f"utt/{k}.wav"] for k in ids)
    s44 = soxr.resample(s16, SR16, SR44).astype(np.float32)
    sf.write(os.path.join(a.out, f"stream44/s{j}.wav"), s44, SR44, subtype="PCM_16")
    stream44[j] = s44
    bench["streams"].append({"j": j, "utts": ids, "dur": round(len(s16) / SR16, 2), "words": len(refs[name].split())})
    print(f"stream s{j}: {len(ids)} utts, {len(s16)/SR16:.1f} s, {len(refs[name].split())} words")


# ---- 3. damage -----------------------------------------------------------------------------------------
def aac_roundtrip(x44, path_tmp):
    """Jibri's recorder chain: pulse -> ffmpeg aac 44.1 kHz 2 ch 128k -> mp4; decode back to mono float."""
    st = np.stack([x44, x44], axis=1)
    sf.write(path_tmp + ".wav", st, SR44, subtype="PCM_16")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path_tmp + ".wav", "-c:a", "aac", "-b:a", a.aac_bitrate,
                    "-ar", "44100", "-ac", "2", path_tmp + ".m4a"], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path_tmp + ".m4a", "-f", "f32le", "-ac", "1", "-ar", "44100", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32).copy()
    os.remove(path_tmp + ".wav"); os.remove(path_tmp + ".m4a")
    # the decoder adds priming/padding; align by cross-correlation of the first second
    n = min(len(x44), len(y))
    L = SR44
    c = np.correlate(y[: L + 4096], x44[:L], mode="valid")
    lag = int(np.argmax(c))
    y = y[lag: lag + len(x44)]
    if len(y) < len(x44):
        y = np.concatenate([y, np.zeros(len(x44) - len(y), dtype=np.float32)])
    return y, lag


def apply_mask(x44, runs, offset, region_len, throttle_only=False, speech_ref=None):
    """Zero the sample ranges of `runs` (seconds, cyclic over region_len) starting at `offset` seconds.
    throttle_only=True: holes > 0.3 s are not applied (treated as pauses);
    throttle_only="speech": holes > 0.3 s are applied only if the real recording had speech-level sound
    next to them (louder neighbour >= speech_ref - 12 dB)."""
    y = x44.copy()
    n = len(y)
    T = n / SR44
    pos = 0.0
    applied = 0.0
    while pos < T:
        for run in runs:
            s, e = run[0], run[1]
            if throttle_only is True and (e - s) > 0.3:
                continue
            if throttle_only == "speech" and (e - s) > 0.3 and len(run) >= 4 and max(run[2], run[3]) < speech_ref - 12:
                continue
            s2, e2 = s - offset, e - offset
            if e2 <= 0:
                s2 += region_len; e2 += region_len
            s2 += pos; e2 += pos
            if s2 >= T:
                continue
            i0, i1 = int(max(0, s2) * SR44), int(min(T, e2) * SR44)
            if i1 > i0:
                y[i0:i1] = 0.0
                applied += (i1 - i0) / SR44
        pos += region_len
    return y, applied


masks = {}
for mp in a.masks:
    m = json.load(open(mp))
    nm = os.path.splitext(os.path.basename(mp))[0]
    masks[nm] = m
    bench["masks"][nm] = m["stats"]

tmpd = os.path.join(a.out, "tmp")
os.makedirs(tmpd, exist_ok=True)
for j, s44 in stream44.items():
    for nm, m in masks.items():
        runs = m["zero_runs_s"]
        region_len = m["stats"]["region_len_s"]
        offset = (j * 41.0) % region_len
        for throttle_only, suffix in variants:
            out = f"dmg/s{j}_{nm}{suffix}.wav"
            if a.skip_existing and os.path.exists(os.path.join(a.out, out)):
                refs[out] = refs[f"stream/s{j}.wav"]; refs[f"dmg16/s{j}_{nm}{suffix}.wav"] = refs[f"stream/s{j}.wav"]
                continue
            y, applied = apply_mask(s44, runs, offset, region_len, throttle_only, m["stats"].get("speech_ref_db"))
            z, lag = aac_roundtrip(y, os.path.join(tmpd, f"s{j}_{nm}{suffix}"))
            # the AAC decoder output: zero runs are kept exact?  measure
            zz = np.abs(z) < 1e-7
            dz = np.diff(np.concatenate([[0], zz.astype(np.int8), [0]]))
            zs, ze = np.where(dz == 1)[0], np.where(dz == -1)[0]
            zl = (ze - zs)
            keep = zl >= 2 * (SR44 // 1000)
            out = f"dmg/s{j}_{nm}{suffix}.wav"
            sf.write(os.path.join(a.out, out), z, SR44, subtype="FLOAT")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(a.out, out), "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", os.path.join(a.out, f"dmg16/s{j}_{nm}{suffix}.wav")], check=True)
            refs[out] = refs[f"stream/s{j}.wav"]
            refs[f"dmg16/s{j}_{nm}{suffix}.wav"] = refs[f"stream/s{j}.wav"]
            bench["streams"][j].setdefault("damage", {})[nm + suffix] = {
                "offset_s": offset, "zeroed_s": round(applied, 2), "zero_frac": round(applied / (len(s44) / SR44), 3),
                "decoded_zero_runs": int(keep.sum()), "decoded_zero_s": round(float(zl[keep].sum()) / SR44, 2), "aac_lag": lag}
            print(f"  s{j} {nm}{suffix}: offset {offset:.1f}s zeroed {applied:.1f}s ({applied/(len(s44)/SR44):.1%}); "
                  f"decoded exact-zero runs {int(keep.sum())}, {float(zl[keep].sum())/SR44:.1f}s, lag {lag}")

# damaged utterance set (first mask, full), each utterance gets a different mask offset
um = a.utt_mask or list(masks)[0]
m = masks[um]
for k, x in enumerate(utts16 if not a.no_utt else []):
    x44 = soxr.resample(x, SR16, SR44).astype(np.float32)
    offset = (k * 7.3) % m["stats"]["region_len_s"]
    y, applied = apply_mask(x44, m["zero_runs_s"], offset, m["stats"]["region_len_s"])
    z, lag = aac_roundtrip(y, os.path.join(tmpd, f"u{k}"))
    sf.write(os.path.join(a.out, f"uttdmg/{k}_{um}.wav"), z, SR44, subtype="FLOAT")
    refs[f"uttdmg/{k}_{um}.wav"] = refs[f"utt/{k}.wav"]
    bench["utterances"][k]["damage"] = {um: {"offset_s": round(offset, 2), "zero_frac": round(applied / (len(x44) / SR44), 3)}}

json.dump(refs, open(os.path.join(a.out, "refs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
json.dump(bench, open(os.path.join(a.out, "bench.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done:", len(refs), "reference entries")
