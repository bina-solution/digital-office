#!/usr/bin/env python3
"""Did the LLM layer invent words?  For each LLM output, the fraction of its (normalised) words that occur in none
of the input hypotheses of the same stream, and how many of those invented words are actually in the reference.
usage: llm_check.py LLM.json REFS.json HYP.json:KEYREGEX ..."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hebnorm import normalize  # noqa: E402

llm = json.load(open(sys.argv[1], encoding="utf-8"))
refs = json.load(open(sys.argv[2], encoding="utf-8"))
pool = {}
for spec in sys.argv[3:]:
    path, rx = spec.split(":", 1)
    for k, v in json.load(open(path, encoding="utf-8")).items():
        if re.search(rx, k):
            m = re.search(r"(s\d+_mask\d+(?:_[ts])?)", k)
            if m:
                pool.setdefault(m.group(1), set()).update(w for s in v["segments"] for w in normalize(s["text"]))
for k, v in llm.items():
    name = re.search(r"(s\d+_mask\d+(?:_[ts])?)", k).group(1)
    stream = name.split("_")[0]
    words = normalize(" ".join(sg["text"] for sg in v["segments"]))
    voc = pool.get(name, set())
    refw = set(normalize(refs[f"stream/{stream}.wav"]))
    inv = [w for w in words if w not in voc]
    inv_ok = [w for w in inv if w in refw]
    print(f"{name}: {len(words)} words out; not in any hypothesis: {len(inv)} ({len(inv)/max(1,len(words)):.1%}), "
          f"of which in the reference: {len(inv_ok)}; examples: {inv[:8]}")
