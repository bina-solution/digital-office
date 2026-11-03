#!/usr/bin/env python3
"""ROVER-style word voting across several ASR hypotheses of the same audio (time-aligned, timeline-mapped).

usage: rover.py OUT.json --refs REFS.json --sys LABEL=HYP.json:KEYREGEX ... [--maps MAPDIR] [--min-votes 2]

Each system contributes word tokens with absolute times on the ORIGINAL timeline.  For a system whose audio
was time-compressed (cut mode: proc/cut*, plc_cut*), the word times are mapped back through the cut map
(data/tmp/<name>_cut.map.json written by restore.py --map); for timeline-preserving systems they are used as is;
for atempo-stretched systems the times are divided by the stretch factor before mapping.

Voting: the words of all systems are pooled and clustered greedily by time overlap (a word joins a cluster if
its midpoint falls within an existing cluster's span +-0.25 s and the cluster has no word from the same system);
each cluster's output is the most frequent normalised form (ties: highest mean word probability); clusters with
fewer than --min-votes supporting systems are dropped unless the best word's probability >= 0.8 and its system
is the primary one (--primary LABEL).  Output: {"<key>": {"file":..., "segments":[{"text":...,"words":[...]}]}}
in the asr_run.py shape so that score.py can score it.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from hebnorm import norm_str  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--sys", nargs="+", required=True, help="LABEL=HYP.json:KEYREGEX[:MAPSUFFIX[:TEMPO]]")
ap.add_argument("--maps", default="/root/fpgaudio/bench/data/tmp")
ap.add_argument("--min-votes", type=int, default=2)
ap.add_argument("--primary", default=None)
ap.add_argument("--win", type=float, default=0.25)
ap.add_argument("--group", default=None, help="treat every selected key as this one group (real recordings)")
a = ap.parse_args()


def load_map(path):
    m = json.load(open(path))
    segs = m["segments"]
    off = float(m.get("offset_s") or 0)

    def f(t):
        best = segs[0]
        for s in segs:
            if s[0] <= t:
                best = s
            else:
                break
        return off + best[1] + min(max(0.0, t - best[0]), best[2])
    return f


systems = []
for spec in a.sys:
    label, rest = spec.split("=", 1)
    parts = rest.split(":")
    path, rx = parts[0], parts[1]
    mapsuf = parts[2] if len(parts) > 2 and parts[2] else None
    tempo = float(parts[3]) if len(parts) > 3 else 1.0
    hyps = json.load(open(path, encoding="utf-8"))
    sel = {k: v for k, v in hyps.items() if re.search(rx, k)}
    systems.append((label, sel, mapsuf, tempo))
    print(f"system {label}: {len(sel)} files", file=sys.stderr)

# group by stream/mask name (s0_mask103 etc.)
by_name = defaultdict(dict)
for label, sel, mapsuf, tempo in systems:
    for k, v in sel.items():
        m = re.search(r"(s\d+_mask\d+(?:_[ts])?)", k)
        if a.group:
            by_name[a.group][label] = (v, mapsuf, tempo)
        elif m:
            by_name[m.group(1)][label] = (v, mapsuf, tempo)

out = {}
for name, syss in sorted(by_name.items()):
    words = []  # (t_mid, t0, t1, norm, prob, label)
    for label, (v, mapsuf, tempo) in syss.items():
        f = None
        if mapsuf:
            mp = os.path.join(a.maps, f"{name}_{mapsuf}.map.json")
            if os.path.exists(mp):
                f = load_map(mp)
            else:
                print("no map", mp, file=sys.stderr)
        for seg in v["segments"]:
            for w in seg.get("words", []):
                txt, s, e, p = w
                nz = norm_str(txt)
                if not nz:
                    continue
                s2, e2 = s / tempo, e / tempo
                if f:
                    s2, e2 = f(s2), f(e2)
                words.append([(s2 + e2) / 2, s2, e2, nz, p, label])
    words.sort(key=lambda w: w[0])
    clusters = []  # each: {"t0","t1","items":[...], "labels":set}
    for w in words:
        placed = False
        for c in reversed(clusters[-12:]):
            if w[5] in c["labels"]:
                continue
            if c["t0"] - a.win <= w[0] <= c["t1"] + a.win:
                c["items"].append(w); c["labels"].add(w[5])
                c["t0"] = min(c["t0"], w[1]); c["t1"] = max(c["t1"], w[2])
                placed = True
                break
        if not placed:
            clusters.append({"t0": w[1], "t1": w[2], "items": [w], "labels": {w[5]}})
    clusters.sort(key=lambda c: (c["t0"] + c["t1"]) / 2)
    chosen = []
    for c in clusters:
        cnt = Counter(it[3] for it in c["items"])
        best, votes = cnt.most_common(1)[0]
        probs = [it[4] for it in c["items"] if it[3] == best]
        labels = {it[5] for it in c["items"] if it[3] == best}
        if votes >= a.min_votes or (a.primary in labels and max(probs) >= 0.8):
            chosen.append([best, round(c["t0"], 2), round(c["t1"], 2), round(sum(probs) / len(probs), 3)])
    text = " ".join(w[0] for w in chosen)
    out[f"rover/{name}.wav"] = {"file": f"rover/{name}.wav", "segments": [{"start": 0, "end": 0, "text": text, "lp": 0, "nsp": 0, "cr": 0, "words": chosen}]}
    print(f"{name}: {len(words)} words in, {len(clusters)} clusters, {len(chosen)} out", file=sys.stderr)
json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
