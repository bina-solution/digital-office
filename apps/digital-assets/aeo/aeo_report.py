#!/usr/bin/env python3
"""aeo_report.py — one panel run → the scorecard (JSON) and the dated page (HTML, Hebrew, right to left).

    python3 apps/digital-assets/aeo/aeo_report.py --date 2026-11-05 --out <dir> run1.jsonl [more.jsonl …]

Input rows are what the collector writes (aeo-watch, DGO-1399): {"id","kind","engine","run","at","result"}.
What is measured is whether an answer NAMES us, not where (SparkToro, 2026-01-28: < 1 in 100 runs give the
same list twice), plus every alternative named and every source cited. A row whose answer is about another
entity that shares our Hebrew name is counted as NOT naming us and listed as a collision — that is the finding,
not noise. Overrides for rows a person checked live in --checks (a JSON file: {"engine:id": {"named": false,
"why": "…", "date": "YYYY-MM-DD", "run": 1}}): a check applies ONLY to the answer it read — the run of that date —
never to another run or another week's answer to the same prompt, which is a new answer. The page's colours are
the office's palette (platform-base/bina-ui/theme-tokens.css, read at render time; G82).
"""
import argparse
import collections
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: the office's one palette — the page takes its colours from here and names none (G82)
TOKENS = HERE.parents[2] / "platform-base/bina-ui/theme-tokens.css"
#: …and its one mark, read where it is drawn — beside «הלשכה הדיגיטלית» on the page (the owner, DGO-1846)
MARK = HERE.parents[2] / "platform-base/bina-ui/brand/mark.html"
UI_LABELS = re.compile(r"^(Related links|Related results|Show all related results|Show all related links|"
                       r"תוצאות קשורות|הצגת כל התוצאות הקשורות|קישורים קשורים)$", re.I)
ENGINE_HE = {"google-aio": "Google · תקציר מ-AI", "google-aimode": "Google · מצב AI", "chatgpt": "ChatGPT (ללא התחברות)",
             "gemini": "Gemini", "perplexity": "Perplexity", "claude": "Claude"}
KIND_HE = {"category": "קטגוריה", "problem": "בעיה", "comparison": "השוואה", "brand": "המותג", "local": "ישראל"}
#: A label as the engine shows it → the site it stands for, when the label is a known name, not a domain.
SITE = {"reddit": "reddit.com", "youtube": "youtube.com", "github": "github.com", "dev community": "dev.to",
        "gov.il": "gov.il", "linkedin": "linkedin.com", "medium": "medium.com", "facebook": "facebook.com",
        "xda": "xda-developers.com", "wikipedia": "wikipedia.org", "גיקטיים": "geektime.co.il",
        "spdx": "spdx.org", "gnu.org": "gnu.org", "coolify": "coolify.io", "cloudron": "cloudron.io"}


def site_of(label: str) -> str:
    s = re.sub(r"\s*\(\+\d+\)\s*$", "", label.strip())
    s = s.split(" · ")[0].strip()
    low = s.lower()
    if re.match(r"^(www\.)?[a-z0-9.-]+\.[a-z]{2,}$", low):
        return re.sub(r"^www\.", "", low)
    return SITE.get(low, s)


def load(paths):
    rows = {}
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[(r["engine"], r["id"], r.get("run", 1))] = r     # a later file's row replaces an earlier one
    return list(rows.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checks", default=str(HERE / "checks.json"))
    a = ap.parse_args()
    panel = json.loads((HERE / "prompts.json").read_text(encoding="utf-8"))
    prompts = {p["id"]: p for p in panel["prompts"]}
    checks = json.loads(Path(a.checks).read_text(encoding="utf-8")) if Path(a.checks).exists() else {}

    def check_for(e, r):
        """The person's check of THIS answer, or None. A check names the date and the run it read: an answer of
        another week, or another run of the same week, is a new answer, and the engine's own text counts."""
        c = checks.get(f"{e}:{r['id']}")
        if c and c.get("date") == a.date and int(c.get("run", 1)) == int(r.get("run", 1)):
            return c
        return None
    rows = load(a.files)
    engines = sorted({r["engine"] for r in rows}, key=lambda e: list(ENGINE_HE).index(e) if e in ENGINE_HE else 99)
    card = {"date": a.date, "panel": panel["panel"], "engines": {}, "runs": {}, "collisions": [], "named_rows": []}
    for e in engines:
        er = [r for r in rows if r["engine"] == e]
        card["runs"][e] = len({r.get("run", 1) for r in er})
        answered = [r for r in er if (r["result"].get("aio") is not False and r["result"].get("answered", True) is not False
                                      and not r["result"].get("blocked") and not r["result"].get("wall"))]
        named, by_kind = 0, collections.defaultdict(lambda: [0, 0])
        alts, srcs = collections.Counter(), collections.Counter()
        for r in answered:
            res, chk = r["result"], check_for(e, r)
            is_named = bool(res.get("named"))
            if chk is not None:
                is_named = bool(chk.get("named"))
                if chk.get("collision"):
                    card["collisions"].append({"engine": e, "id": r["id"], "run": r.get("run", 1),
                                               "prompt": prompts[r["id"]]["text"], "why": chk["why"]})
            kind = prompts[r["id"]]["kind"]
            by_kind[kind][1] += 1
            if is_named:
                named += 1
                by_kind[kind][0] += 1
                card["named_rows"].append({"engine": e, "id": r["id"]})
            for x in res.get("alts") or []:
                alts[x] += 1
            for s in res.get("sources") or []:
                if not UI_LABELS.match(s.strip()):
                    srcs[site_of(s)] += 1
            for y in res.get("youtube") or []:
                srcs["youtube.com"] += 1
            for d in res.get("domains") or []:
                srcs[d] += 1
        nb = [r for r in answered if prompts[r["id"]]["kind"] != "brand"]
        nb_named = sum(1 for r in nb if ((check_for(e, r) or {}).get("named", r["result"].get("named"))))
        card["engines"][e] = {"rows": len(er), "answered": len(answered), "named": named,
                              "unbranded": len(nb), "unbranded_named": nb_named,
                              "by_kind": {k: {"named": v[0], "answered": v[1]} for k, v in by_kind.items()},
                              "alternatives": alts.most_common(15), "sources": srcs.most_common(20)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"aeo-{a.date}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"aeo-{a.date}.html").write_text(page(card, prompts, panel), encoding="utf-8")
    for e, v in card["engines"].items():
        print(f"{e:<14} answered {v['answered']}/{v['rows']} · named {v['named']} · unbranded named {v['unbranded_named']}/{v['unbranded']}")
    print(f"collisions: {len(card['collisions'])} → {out}")
    return 0


def page(card, prompts, panel) -> str:
    esc = html.escape
    eng_rows = "".join(
        f"<tr><td>{esc(ENGINE_HE.get(e, e))}</td><td>{v['answered']}</td><td><b>{v['unbranded_named']}</b> מתוך {v['unbranded']}</td>"
        f"<td>{v['by_kind'].get('brand', {}).get('named', 0)} מתוך {v['by_kind'].get('brand', {}).get('answered', 0)}</td></tr>"
        for e, v in card["engines"].items())
    def top_rows(lst, n=12):       # not `top`: symtable calls the module's table «top», and G80 read this as it
        return "".join(f"<li><span>{esc(str(k))}</span><b>{c}</b></li>" for k, c in lst[:n])
    alts = collections.Counter()
    srcs = collections.Counter()
    for v in card["engines"].values():
        alts.update(dict(v["alternatives"]))
        srcs.update(dict(v["sources"]))
    coll = "".join(f"<li><b>{esc(ENGINE_HE.get(c['engine'], c['engine']))}</b> · «{esc(c['prompt'])}» — {esc(c['why'])}</li>"
                   for c in card["collisions"])
    plist = "".join(f"<li><code>{p['id']}</code> <span class='k'>{KIND_HE[p['kind']]}</span> {esc(p['text'])}</li>"
                    for p in panel["prompts"])
    # what THIS run held — never a fixed sentence (a page that says «one run» over three runs is wrong)
    runs = card.get("runs") or {}
    measured = ", ".join(f"{ENGINE_HE.get(e, e)} ({runs.get(e, 1)} {'ריצה' if runs.get(e, 1) == 1 else 'ריצות'})"
                         for e in card["engines"])
    missing = [ENGINE_HE[e] for e in ENGINE_HE if e not in card["engines"]]
    not_measured = (f" לא נמדדו בריצה הזו: {', '.join(missing)}." if missing else "")
    # the office's ONE palette, read where it is written (G82: only theme-tokens.css names a colour)
    tokens = TOKENS.read_text(encoding="utf-8")
    drawn = MARK.read_text(encoding="utf-8")
    start, end = "<!-- @bina-brand:start -->", "<!-- @bina-brand:end -->"     # the region G27 keeps, not a guess at <svg
    mark = drawn[drawn.index(start) + len(start):drawn.index(end)]
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>על מי ה-AI ממליץ — {card['date']}</title>
<style>
{tokens}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 "Heebo","Noto Sans Hebrew",system-ui,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 64px}} h1{{font-size:30px;line-height:1.25;margin:8px 0 4px}}
h2{{font-size:21px;margin:34px 0 10px}} .sub{{color:var(--muted)}} section{{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin:14px 0}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:right;padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top}} th{{color:var(--muted);font-weight:600}}
ul.top{{list-style:none;padding:0;margin:0;columns:2;column-gap:28px}} ul.top li{{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px dashed var(--line);break-inside:avoid}}
.big{{font-size:44px;font-weight:800;color:var(--olive);line-height:1}} .k{{color:var(--muted);font-size:14px;margin-inline:6px}} code{{font-size:14px;color:var(--muted)}}
ol.p{{padding-inline-start:0;list-style:none}} ol.p li{{padding:6px 0;border-bottom:1px solid var(--line)}} .warn{{border-color:var(--lime-d)}}
@media (max-width:560px){{ul.top{{columns:1}} h1{{font-size:25px}}}}
.dgo-mark{{display:inline-block;width:1.35em;height:1.35em;vertical-align:-.34em;margin-inline-end:.3em}} .dgo-mark svg{{display:block;width:100%;height:100%}}
.dgo-mark .t{{fill:var(--olive)}} .dgo-mark .m{{fill:var(--olive-ink)}} .dgo-mark .a{{fill:var(--lime)}}
</style></head><body><main>
<p class="sub"><span class="dgo-mark">{mark}</span>הלשכה הדיגיטלית · מחקר AEO · {card['date']} · פאנל {esc(card['panel'])}</p>
<h1>על מי ה-AI ממליץ לעסק ישראלי — הבסיס</h1>
<p class="sub">40 שאלות קבועות בעברית ובאנגלית, כפי שאדם שואל אותן, נקראו ב-{card['date']} מישראל, בלי התחברות: {esc(measured)}. תמונת מצב מתוארכת, לא דירוג: אותה רשימה חוזרת פעמיים בפחות מאחת ממאה ריצות (SparkToro, ינואר 2026), ולכן מודדים כמה פעמים קוראים לנו בשם לאורך הרבה ריצות, כל שבוע על אותן שאלות.</p>
<section><h2>כמה פעמים קראו לנו בשם</h2><table><tr><th>מנוע</th><th>תשובות</th><th>בשאלות בלי השם שלנו</th><th>בשאלות על המותג</th></tr>{eng_rows}</table></section>
<section class="warn"><h2>השם שלנו בעברית תפוס</h2><ul>{coll or '<li>אין</li>'}</ul></section>
<section><h2>על מי כן ממליצים</h2><ul class="top">{top_rows(alts.most_common(), 16)}</ul></section>
<section><h2>את מי מצטטים</h2><ul class="top">{top_rows(srcs.most_common(), 20)}</ul></section>
<section><h2>40 השאלות</h2><ol class="p">{plist}</ol></section>
<section><h2>איך נמדד</h2><p>דפדפן בישראל, לא מחובר לשום חשבון; Google עם hl=iw/en ו-gl=il; ChatGPT במצב לא מחובר עם חיפוש. לכל תשובה נרשם: האם נאמר «הלשכה הדיגיטלית», «בינה סולושנס» או אחד הדומיינים שלנו, אילו חלופות נזכרו, ואילו מקורות צוטטו. תשובה על גוף אחר שנושא את השם שלנו נספרת כ«לא נקראנו בשם» ומופיעה למעלה.{esc(not_measured)}</p></section>
</main></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
