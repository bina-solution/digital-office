#!/usr/bin/env python3
"""layer_gate.py — the gate between the SEO layers (DGO-664, seo-005): what counts as perfect in each layer, and
the check that proves it. One file: the definition is the data below, the check is the code under it.

    python3 apps/digital-assets/content/layer_gate.py --layer 1 [--today 2026-11-10] [--json]

The owner, 2026-10-19 (DGO-659): «every layer should be perfect for itself. So after the second layer, we should have
all the text already». So a layer is passed only when every one of its items is perfect, and the next layer does not
start before it (AGENTS.md rule 4: one perfect example, review, then the rest).

LAYER 1 — the map (SEO · 1, seo-101…115). Every list is finished, dated and sourced, and has its place on the site:
  · a list kept as an index (content/index/<slug>.json): the file exists, has rows, every row has an https source and
    was verified within 91 days, and the index has its page (an entry in index/_indexes.json);
  · a list kept as a file (ai/context/seo/…, research/…): the file exists, carries a date within 91 days and at
    least one https source;
  · the project lists (assignments.yaml): every project has its facts row — licence, repository, sources, verified
    within 91 days — in content/index/open-source-business-apps.json.
LAYER 2 — the text (SEO · 3–7). Every piece the plan names is written within its range (status.py «ok») and passes
  the quarterly check clean (recheck.py, offline): FACTS.md not newer, no undated price, no «משרד» left to read, not
  due. Publication itself is measured on the site (its sitemap), not here.
LAYER 3 — media (SEO · 9). It starts only when layer 2 has passed: this gate says «closed» until then.
Exit 0 when the layer is perfect, 1 when it is not (each item says what is missing), 2 on a wrong call.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:                                      # the Mac host has none; the engine guest does
    sys.exit("layer_gate.py needs PyYAML: pip install pyyaml")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FRESH = dt.timedelta(days=91)
DATE = re.compile(r"(?<!\d)(20\d\d-\d\d-\d\d)(?!\d)")

#: layer 1, item by item: (key, work item, what, how it is kept, where)
LAYER1 = [
    ("seo-101", "DGO-667", "מפת הנושאים", "file", "ai/context/seo/topic-map.yaml"),
    ("seo-102", "DGO-668", "מחקר הביטויים בעברית", "file", "ai/context/seo/keywords.yaml"),
    ("seo-103", "DGO-669", "35 פרויקטי הדגל ודף עובדות לכל אחד", "projects", "flagship"),
    ("seo-104", "DGO-670", "200 הפרויקטים ושורת עובדות לכל אחד", "projects", "projects"),
    ("seo-105", "DGO-671", "חברות כמונו שהצליחו", "file", "apps/digital-assets/research/startup-patterns.md"),
    ("seo-106", "DGO-672", "200 האתרים הישראליים", "index", "israeli-popular-sites"),
    ("seo-107", "DGO-673", "הבנקים ושירותיהם הדיגיטליים", "index", "israeli-banks"),
    ("seo-108", "DGO-674", "התוכנה העסקית הישראלית", "index", "israeli-business-software"),
    ("seo-109", "DGO-675", "קמעונאים עם קנייה אונליין", "index", "israeli-online-retailers"),
    ("seo-110", "DGO-676", "משרדי הממשלה ושירותיהם הדיגיטליים", "index", "gov-digital-services-for-business"),
    ("seo-111", "DGO-677", "משרדים פיזיים ושגרירויות", "index", "israel-physical-offices"),
    ("seo-112", "DGO-678", "טבלת השמות ו-sameAs", "file", "ai/context/seo/names.yaml"),
    ("seo-113", "DGO-679", "מבנה האתר והכתובות", "file", "ai/context/seo/site-structure.yaml"),
    ("seo-114", "DGO-680", "ענן ותשתית", "index", "cloud-and-vps"),
    ("seo-115", "DGO-681", "מפת עולם ה-AI", "index", "ai-world-map"),
]


def _date(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _rows(path: Path) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("rows", []) if isinstance(doc, dict) else doc


def _row_gaps(rows: list, today: dt.date) -> list[str]:
    unsourced = [r.get("id", "?") for r in rows
                 if not any(str(s.get("url", "")).startswith("https://") for s in r.get("sources") or [] if isinstance(s, dict))]
    stale = [r.get("id", "?") for r in rows if not _date(r.get("verified_at")) or _date(r.get("verified_at")) + FRESH < today]
    out = []
    if unsourced:
        out.append(f"{len(unsourced)} שורות בלי מקור https (למשל {', '.join(unsourced[:3])})")
    if stale:
        out.append(f"{len(stale)} שורות שלא נבדקו ב-91 הימים האחרונים (למשל {', '.join(stale[:3])})")
    return out


def check_index(slug: str, content: Path, today: dt.date) -> list[str]:
    f = content / "index" / f"{slug}.json"
    if not f.exists():
        return [f"אין רשימה: index/{slug}.json"]
    rows = _rows(f)
    gaps = ["הרשימה ריקה"] if not rows else _row_gaps(rows, today)
    pages = json.loads((content / "index" / "_indexes.json").read_text(encoding="utf-8")) \
        if (content / "index" / "_indexes.json").exists() else {}
    if slug not in pages:
        gaps.append("אין לה עמוד באתר (אין רשומה ב-index/_indexes.json)")
    return gaps


def check_file(rel: str, repo: Path, today: dt.date) -> list[str]:
    f = repo / rel
    if not f.exists() or not f.read_text(encoding="utf-8").strip():
        return [f"אין קובץ: {rel}"]
    text = f.read_text(encoding="utf-8")
    dates = [d for d in (_date(m) for m in DATE.findall(text)) if d and d <= today]
    gaps = []
    if not dates or max(dates) + FRESH < today:
        gaps.append(f"אין תאריך מ-91 הימים האחרונים (האחרון: {max(dates) if dates else '—'})")
    if "https://" not in text:
        gaps.append("אין מקור https")
    return gaps


def check_projects(which: str, content: Path, today: dt.date) -> list[str]:
    plan = yaml.safe_load((content / "assignments.yaml").read_text(encoding="utf-8")) or {}
    slugs = [f["slug"] for f in plan.get("flagship") or []] if which == "flagship" else \
        [s for c in (plan.get("projects") or {}).values() for s in c.get("slugs") or []]
    if not slugs:
        return [f"אין רשימה ב-assignments.yaml ({which})"]
    f = content / "index" / "open-source-business-apps.json"
    rows = {r.get("id"): r for r in (_rows(f) if f.exists() else [])}
    missing = [s for s in slugs if s not in rows]
    have = [rows[s] for s in slugs if s in rows]
    thin = [r.get("id") for r in have if not r.get("licence") or not (r.get("github") or r.get("url"))]
    gaps = []
    if missing:
        gaps.append(f"{len(missing)} מתוך {len(slugs)} בלי שורת עובדות (למשל {', '.join(missing[:3])})")
    if thin:
        gaps.append(f"{len(thin)} שורות בלי רישיון או מאגר (למשל {', '.join(thin[:3])})")
    return gaps + _row_gaps(have, today)


def layer1(repo: Path, content: Path, today: dt.date) -> list[dict]:
    out = []
    for key, ref, what, kind, where in LAYER1:
        gaps = {"index": lambda: check_index(where, content, today), "file": lambda: check_file(where, repo, today),
                "projects": lambda: check_projects(where, content, today)}[kind]()
        out.append({"key": key, "ref": ref, "what": what, "kept": kind, "where": where, "ok": not gaps, "gaps": gaps})
    return out


def layer2(content: Path, today: dt.date) -> list[dict]:
    sys.path.insert(0, str(content))
    import recheck
    import status
    out = []
    checked = {r["path"]: r for r in recheck.recheck(content, today, recheck.facts_changed(content), net=False)}
    for p in status.planned():
        state, words = status.state(p)
        path = f"{p['type']}/{p['slug']}.he.md"
        r = checked.get(path, {})
        gaps = [] if state == "ok" else [f"{state} ({words} מילים)"]
        gaps += (["FACTS.md חדש ממנה"] if r.get("facts_newer") else []) + \
                ([f"{len(r['undated_prices'])} מחירים בלי שנה"] if r.get("undated_prices") else []) + \
                ([f"{len(r['office_word'])} «משרד» לקריאה"] if r.get("office_word") else []) + \
                (["הגיע זמן הבדיקה שלה"] if r.get("due") else [])
        out.append({"key": path, "ref": p.get("plane", ""), "what": p.get("title", p["slug"]), "kept": p["type"],
                    "where": path, "ok": not gaps, "gaps": gaps})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--layer", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo, today = Path(a.repo), dt.date.fromisoformat(a.today)
    content = repo / "apps" / "digital-assets" / "content"
    if a.layer == 3:
        below = layer2(content, today)
        items = [{"key": "seo-9", "ref": "", "what": "מדיה", "kept": "—", "where": "—", "ok": False,
                  "gaps": [f"סגורה: שכבה 2 לא עברה ({sum(not i['ok'] for i in below)} מתוך {len(below)} פיסות)"]}] \
            if not all(i["ok"] for i in below) else []
    else:
        items = layer1(repo, content, today) if a.layer == 1 else layer2(content, today)
    passed = sum(i["ok"] for i in items)
    perfect = bool(items) and passed == len(items) if a.layer != 3 else not items
    if a.json:
        print(json.dumps({"layer": a.layer, "today": today.isoformat(), "perfect": perfect, "passed": passed,
                          "items": items}, ensure_ascii=False, indent=1))
    else:
        print(f"שכבה {a.layer} — {today.isoformat()}: {'מושלמת' if perfect else 'עוד לא'} ({passed} מתוך {len(items)})")
        for i in items:
            print(f"  {'✓' if i['ok'] else '·'} {i['key']} {i['ref']} {i['what']}"
                  + ("" if i["ok"] else ": " + "; ".join(i["gaps"])))
    return 0 if perfect else 1


if __name__ == "__main__":
    sys.exit(main())
