#!/usr/bin/env python3
"""Benchmark table: recall / WER / insertions per (method, mask), pooled over the streams present.

usage: table.py REFS.json HYP.json [HYP2.json ...] [--guard] [--min-lp -1.0] [--streams s0,s1] [--md]
Keys are grouped by method = the path component before the file (proc/<method>/, dmg16/ -> "damaged",
stream/ -> "clean", rover/, llm/) and by mask (mask103 / mask104 / mask103_t / ... or "clean"), plus the
hypothesis file's tag (model/options) when several HYP files are given.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from score import hyp_text, score_pair, summarize  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("refs")
ap.add_argument("hyps", nargs="+")
ap.add_argument("--guard", action="store_true")
ap.add_argument("--min-lp", type=float, default=-1.0)
ap.add_argument("--streams", default=None)
ap.add_argument("--md", action="store_true")
ap.add_argument("--per-stream", action="store_true")
a = ap.parse_args()
refs = json.load(open(a.refs, encoding="utf-8"))
streams = set(a.streams.split(",")) if a.streams else None

groups = defaultdict(list)
for hp in a.hyps:
    tag = os.path.basename(hp).replace("asr_", "").replace(".json", "")
    hyps = json.load(open(hp, encoding="utf-8"))
    for key, entry in hyps.items():
        f = entry.get("file", key)
        m = re.search(r"(?:^|/)(s\d+)(?:_(mask\d+(?:_[ts])?))?\.wav$", f)
        if not m:
            continue
        stream, mask = m.group(1), m.group(2) or "clean"
        if streams and stream not in streams:
            continue
        if f.startswith("proc/"):
            method = f.split("/")[1]
        elif f.startswith("dmg16/"):
            method = "damaged"
        elif f.startswith("stream/"):
            method = "clean"
        else:
            method = f.split("/")[0]
        rk = f"stream/{stream}.wav"
        sc = score_pair(refs[rk], hyp_text(entry, a.guard, a.min_lp))
        if sc:
            groups[(tag, method, mask)].append((stream, sc))

rows = []
for (tag, method, mask), lst in groups.items():
    s = summarize([x for _, x in lst])
    rows.append((tag, method, mask, s, sorted(st for st, _ in lst)))
rows.sort(key=lambda r: (r[2], -r[3]["recall"]))
hdr = f"{'tag':14s} {'method':13s} {'mask':10s} {'streams':14s} {'N':>5s} {'recall':>7s} {'WER':>6s} {'ins':>5s} {'prec':>6s}"
if a.md:
    print("| tag | method | mask | streams | N | recall | WER | ins | precision |")
    print("|---|---|---|---|---:|---:|---:|---:|---:|")
else:
    print(hdr)
for tag, method, mask, s, sts in rows:
    st = ",".join(sts)
    if a.md:
        print(f"| {tag} | {method} | {mask} | {st} | {s['N']} | {s['recall']:.3f} | {s['WER']:.3f} | {s['ins']} | {s['precision']:.3f} |")
    else:
        print(f"{tag:14s} {method:13s} {mask:10s} {st:14s} {s['N']:5d} {s['recall']:7.3f} {s['WER']:6.3f} {s['ins']:5d} {s['precision']:6.3f}")
if a.per_stream:
    for (tag, method, mask), lst in sorted(groups.items()):
        print(f"  {tag} {method} {mask}: " + "  ".join(f"{st}:{sc['hits']/sc['N']:.3f}" for st, sc in sorted(lst)))
