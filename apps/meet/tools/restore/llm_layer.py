#!/usr/bin/env python3
"""LLM-assisted reconstruction layer (separate, clearly labelled): chooses among ASR hypotheses, never invents.

usage: llm_layer.py OUT.json --sys LABEL=HYP.json:KEYREGEX[:MAPSUFFIX[:TEMPO]] ... [--window 40] [--provider deepseek]
                    [--model deepseek-chat] [--dry-run] [--maps DIR] [--names s0_mask103,...]

For every stream/mask name, the hypotheses of all systems are mapped to the original timeline (like rover.py),
cut into --window-second windows and sent to the LLM with the instruction to output the most plausible transcript
of that window using ONLY words present in the hypotheses (split/merged words may be fixed), no additions.
The output is written in the asr_run.py shape so score.py can measure its recall AND its precision.
The API key is read from a file and never printed.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from hebnorm import norm_str  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--sys", nargs="+", required=True)
ap.add_argument("--maps", default="/root/fpgaudio/bench/data/tmp")
ap.add_argument("--window", type=float, default=40.0)
ap.add_argument("--provider", default="deepseek")
ap.add_argument("--model", default="deepseek-chat")
ap.add_argument("--keyfile", default="/mnt/c/Users/wbolo/.claude/.deepseek_key")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--names", default=None)
ap.add_argument("--sleep", type=float, default=2.0)
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
    systems.append((label, {k: v for k, v in hyps.items() if re.search(rx, k)}, mapsuf, tempo))

by_name = defaultdict(dict)
for label, sel, mapsuf, tempo in systems:
    for k, v in sel.items():
        m = re.search(r"(s\d+_mask\d+(?:_[ts])?)", k)
        if a.group:
            by_name[a.group][label] = (v, mapsuf, tempo)
        elif m:
            by_name[m.group(1)][label] = (v, mapsuf, tempo)
if a.names:
    by_name = {k: v for k, v in by_name.items() if k in a.names.split(",")}

SYSTEM = ("You are a careful Hebrew transcription editor. You receive several automatic transcripts (from "
          "different audio-repair variants) of the SAME window of a damaged recording. Produce the single most "
          "plausible transcript of that window.\nRules:\n"
          "1. Use ONLY words that appear in at least one of the hypotheses. Never add words, names or content that "
          "no hypothesis contains.\n"
          "2. You may fix a word that was split or merged by the recognizer (e.g. 'ה טכנולוגיה' -> 'הטכנולוגיה') "
          "and choose between competing readings of the same stretch; prefer readings that make grammatical Hebrew.\n"
          "3. When hypotheses disagree about whether something was said at all, include it only if at least two "
          "hypotheses contain it, or it is clearly the continuation of the sentence.\n"
          "4. Drop obvious recognizer artefacts (repeated loops, 'תודה רבה' at silence, stray single letters).\n"
          "5. Output ONLY the transcript text, without quotes, numbering or comments.")


def call_llm(prompt):
    key = open(a.keyfile).read().strip()
    if a.provider == "deepseek":
        url = "https://api.deepseek.com/chat/completions"
        body = {"model": a.model, "temperature": 0.0, "max_tokens": 1200,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode())
        return out["choices"][0]["message"]["content"].strip(), out.get("usage", {})
    raise SystemExit("unknown provider")


out = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
for name, syss in sorted(by_name.items()):
    key = f"llm/{name}.wav"
    if key in out:
        continue
    # words on the original timeline per system
    per = {}
    tmax = 0.0
    for label, (v, mapsuf, tempo) in syss.items():
        f = None
        if mapsuf:
            mp = os.path.join(a.maps, f"{name}_{mapsuf}.map.json")
            f = load_map(mp) if os.path.exists(mp) else None
        ws = []
        for seg in v["segments"]:
            for w in seg.get("words", []):
                txt, s, e, p = w
                s2, e2 = s / tempo, e / tempo
                if f:
                    s2, e2 = f(s2), f(e2)
                ws.append((s2, e2, txt.strip()))
                tmax = max(tmax, e2)
        per[label] = ws
    segs_out = []
    t = 0.0
    while t < tmax:
        t1 = t + a.window
        lines = []
        empty = True
        for label, ws in per.items():
            seg = " ".join(w for s, e, w in ws if t <= (s + e) / 2 < t1)
            if seg:
                empty = False
            lines.append(f"[{label}] {seg if seg else '(nothing recognised)'}")
        prompt = (f"Window {int(t)}-{int(t1)} s. Hypotheses:\n" + "\n".join(lines) + "\n\nTranscript of this window:")
        txt = ""
        if empty:
            pass                                   # nothing recognised by anyone: nothing to reconstruct
        elif a.dry_run:
            print(prompt, "\n---", file=sys.stderr)
        else:
            try:
                txt, usage = call_llm(prompt)
            except Exception as e:  # noqa
                print("LLM error:", e, file=sys.stderr)
            time.sleep(a.sleep)
        if txt and txt.strip() not in ("(nothing recognised)", ""):
            segs_out.append({"start": round(t, 2), "end": round(min(t1, tmax), 2), "text": txt.strip(), "lp": 0, "nsp": 0, "cr": 0, "words": []})
        t = t1
    full = " ".join(s["text"] for s in segs_out)
    out[key] = {"file": key, "segments": segs_out, "systems": list(syss)}
    print(f"{name}: {len(segs_out)} windows with text, {len(full.split())} words", file=sys.stderr)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
