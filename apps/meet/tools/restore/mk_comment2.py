#!/usr/bin/env python3
"""Build the Plane comment «תמלול משוחזר v2» (HTML + plain text) from a transcription JSON.

usage: mk_comment2.py HYP.json KEY OUT.html OUT.txt --name RESTORED_FILE --method "…" --bench "…"
                      [--map MAP.json] [--tempo 1.0] [--min-lp -1.0]
Timestamps are given on the ORIGINAL recording's clock: for a time-compressed (cut-mode) transcription the
cut map (restore.py --map) maps them back; --tempo divides the times first when the audio was slowed down
(atempo).  Segments failing the confidence guard (stock phrases, loops, repeats, avg_logprob <= --min-lp)
are dropped; segments with avg_logprob <= -0.6 are marked (?)."""
import argparse
import json
import re
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("hyp")
ap.add_argument("key")
ap.add_argument("out_html")
ap.add_argument("out_txt")
ap.add_argument("--name", required=True)
ap.add_argument("--method", required=True)
ap.add_argument("--bench", required=True)
ap.add_argument("--map", default=None)
ap.add_argument("--tempo", type=float, default=1.0)
ap.add_argument("--min-lp", type=float, default=-1.0)
ap.add_argument("--title", default="תמלול משוחזר v2")
a = ap.parse_args()

r = json.load(open(a.hyp, encoding="utf-8"))[a.key]
if a.map:
    m = json.load(open(a.map))
    segs = m["segments"]
    off = float(m.get("offset_s") or 0)

    def src_time(t):
        t = t / a.tempo
        best = segs[0]
        for s in segs:
            if s[0] <= t:
                best = s
            else:
                break
        return off + best[1] + min(max(0.0, t - best[0]), best[2])
else:
    def src_time(t):
        return t / a.tempo


def mmss(s):
    s = int(s)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


STOCK = {"תודה רבה", "תודה", "תודה רבה לכם", "thank you", "thanks", "you", "bye", "שלום", "תודה שצפיתם", "כתוביות", "תרגום"}
# phrases the ivrit-ai model produces on near-empty audio (Knesset training data); never said in these meetings
HALLU = [r"אדוני היושב[- ]ראש", r"חבריי? חברי הכנסת", r"חברי הכנסת", r"תודה רבה לך,? אדוני", r"היושב[- ]ראש", r"תודה רבה לך"]


def stock(t):
    k = re.sub(r"[.,!?…]+", " ", t.lower())
    return re.sub(r" +", " ", k).strip() in STOCK


def strip_hallu(t):
    """Remove the known hallucination phrases; returns (text, removed_count)."""
    n = 0
    for p in HALLU:
        t, k = re.subn(p, " ", t)
        n += k
    t = re.sub(r"\s+", " ", t).strip(" ,.;:-")
    return t, n


def looped(t):
    w = t.split()
    return len(w) >= 6 and Counter(w).most_common(1)[0][1] >= max(5, len(w) // 2)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


lines = r["segments"]
cnt = Counter(l["text"] for l in lines)
kept, dropped, hallu_removed = [], 0, 0
for l in lines:
    t, k = strip_hallu(l["text"].strip())
    hallu_removed += k
    filler = bool(re.fullmatch(r"(.)\1{3,}[.!?…]*", t)) or (len(t.split()) == 1 and len(set(t)) <= 2 and len(t) >= 5)
    if not t or stock(t) or looped(t) or filler or cnt[l["text"]] >= 3 or l["lp"] <= a.min_lp:
        dropped += 1
        continue
    kept.append(dict(l, text=t))
html = [f"<h3>{esc(a.title)}</h3>",
        f"<p dir=\"rtl\"><b>שיטה:</b> {esc(a.method)}</p>",
        f"<p dir=\"rtl\"><b>מדידה (benchmark עם מסכת הנזק האמיתית של ההקלטה הזאת):</b> {esc(a.bench)}</p>",
        f"<p dir=\"rtl\">הקובץ המשוחזר: <code>{esc(a.name)}</code>. חותמות הזמן לפי שעון ההקלטה המקורית. "
        f"שורות בביטחון נמוך מסומנות (?). {len(kept)} שורות; {dropped} שורות הושמטו (הזיות/חזרות/ביטחון נמוך מאוד); "
        f"{hallu_removed} ביטויי הזיה ידועים של המודל (\"אדוני היושב-ראש\", \"חברי הכנסת\", \"תודה רבה לך\") הוסרו.</p>"]
plain = [a.title, f"method: {a.method}", f"benchmark: {a.bench}", ""]
for l in kept:
    q = " (?)" if l["lp"] <= -0.6 else ""
    st = f"[{mmss(src_time(l['start']))}]"
    html.append(f"<p dir=\"rtl\">{esc(st)} {esc(l['text'])}{q}</p>")
    plain.append(f"{st} {l['text']}{q}")
open(a.out_html, "w", encoding="utf-8").write("".join(html))
open(a.out_txt, "w", encoding="utf-8").write("\n".join(plain) + "\n")
print(f"{len(kept)} lines kept, {dropped} dropped -> {a.out_html}")
