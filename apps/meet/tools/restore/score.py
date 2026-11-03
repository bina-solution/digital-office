#!/usr/bin/env python3
"""Score ASR hypotheses against references by word alignment (jiwer / Levenshtein).

usage: score.py REFS.json HYP.json [--select REGEX] [--min-lp -1.0] [--guard] [--label NAME] [--per-file] [--json OUT]

Per file and pooled:  N (reference words), recall = hits/N, WER = (S+D+I)/N, ins = insertions (hallucinated words),
precision = hits / hypothesis words.
--guard applies the deliverable's confidence guard before scoring: drop segments with avg_logprob <= --min-lp,
stock phrases ("תודה רבה" …), looped segments (one token >= half the words) and texts repeated 3+ times.
"""
import argparse
import json
import re
import sys
from collections import Counter

import jiwer

sys.path.insert(0, __import__("os").path.dirname(__file__))
from hebnorm import norm_str  # noqa: E402

STOCK = {"תודה רבה", "תודה", "תודה רבה לכם", "thank you", "thanks", "you", "bye", "שלום", "תודה שצפיתם", "כתוביות", "תרגום"}


def is_stock(t):
    k = re.sub(r"[.,!?…]+", " ", t.lower())
    return re.sub(r" +", " ", k).strip() in STOCK or not k.strip()


def looped(t):
    w = t.split()
    if len(w) < 6:
        return False
    return Counter(w).most_common(1)[0][1] >= max(5, len(w) // 2)


def hyp_text(entry, guard=False, min_lp=-1.0):
    segs = entry["segments"]
    if not guard:
        return " ".join(s["text"] for s in segs)
    cnt = Counter(s["text"] for s in segs)
    keep = []
    for s in segs:
        t = s["text"].strip()
        if not t or is_stock(t) or looped(t) or cnt[t] >= 3 or s["lp"] <= min_lp:
            continue
        keep.append(t)
    return " ".join(keep)


def score_pair(ref, hyp):
    r, h = norm_str(ref), norm_str(hyp)
    if not r:
        return None
    if not h:
        n = len(r.split())
        return {"N": n, "hits": 0, "S": 0, "D": n, "I": 0, "H": 0}
    o = jiwer.process_words(r, h)
    return {"N": len(r.split()), "hits": o.hits, "S": o.substitutions, "D": o.deletions, "I": o.insertions, "H": len(h.split())}


def summarize(rows):
    N = sum(r["N"] for r in rows); hits = sum(r["hits"] for r in rows)
    S = sum(r["S"] for r in rows); D = sum(r["D"] for r in rows); I = sum(r["I"] for r in rows); H = sum(r["H"] for r in rows)
    return {"files": len(rows), "N": N, "hits": hits, "recall": hits / max(1, N), "WER": (S + D + I) / max(1, N),
            "ins": I, "ins_rate": I / max(1, N), "precision": hits / max(1, H), "S": S, "D": D, "hyp_words": H}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("refs")
    ap.add_argument("hyp")
    ap.add_argument("--select", default=None, help="regex on the hypothesis key")
    ap.add_argument("--strip-prefix", default=None, help="regex removed from the key before looking up the reference")
    ap.add_argument("--min-lp", type=float, default=-1.0)
    ap.add_argument("--guard", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--per-file", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    refs = json.load(open(a.refs, encoding="utf-8"))
    hyps = json.load(open(a.hyp, encoding="utf-8"))
    rows, per = [], {}
    for key, entry in hyps.items():
        if a.select and not re.search(a.select, key):
            continue
        fkey = entry.get("file", key)
        # reference lookup: by the file's path relative to the bench dir
        rk = None
        for cand in [fkey, re.sub(r"^.*?/(utt|stream|dmg|dmg16|uttdmg|proc)/", r"\1/", fkey)]:
            if cand in refs:
                rk = cand; break
        if rk is None:
            # processed files: proc/<method>/<stream>_<mask>.wav -> reference of the stream
            m = re.search(r"(?:^|/)(s\d+)_", fkey) or re.search(r"(?:^|/)(s\d+)\.wav$", fkey)
            if m and f"stream/{m.group(1)}.wav" in refs:
                rk = f"stream/{m.group(1)}.wav"
            else:
                m = re.search(r"(?:^|/)(\d+)_mask\d+", fkey) or re.search(r"(?:^|/)(\d+)\.wav$", fkey)
                if m and f"utt/{m.group(1)}.wav" in refs:
                    rk = f"utt/{m.group(1)}.wav"
        if rk is None:
            print("no reference for", key, file=sys.stderr); continue
        sc = score_pair(refs[rk], hyp_text(entry, a.guard, a.min_lp))
        if sc:
            rows.append(sc); per[key] = sc
    if not rows:
        print("no rows"); sys.exit(1)
    s = summarize(rows)
    print(f"{a.label:34s} files={s['files']:3d} N={s['N']:5d} recall={s['recall']:.3f} WER={s['WER']:.3f} "
          f"ins={s['ins']:4d} ({s['ins_rate']:.3f}) prec={s['precision']:.3f}  S={s['S']} D={s['D']} hyp={s['hyp_words']}")
    if a.per_file:
        for k, r in per.items():
            print(f"   {k[-40:]:40s} N={r['N']:4d} recall={r['hits']/r['N']:.3f} ins={r['I']:3d}")
    if a.json:
        json.dump({"summary": s, "per_file": per, "label": a.label}, open(a.json, "w"), indent=1)
