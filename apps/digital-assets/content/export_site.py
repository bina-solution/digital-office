#!/usr/bin/env python3
"""export_site.py — the office's data pages, gated and written into the Bina site's source (DGO-1351, 1383–1387).

    python3 export_site.py <site-repo>                 # gate every row, write the site's _data and downloads
    python3 export_site.py <site-repo> --linkcheck     # first ask every URL once more (cached in index/_links.json)
    python3 export_site.py --gate                      # only the gate's report, nothing written

What goes in (this directory):
  index/_indexes.json        each index's page copy, how its figure is shown, its categories
  index/<slug>.json          the rows, one object each (the schema: index/README.md)
  leaderboard/results.json   the scored runs (apps/ollama/leaderboard/harness.py score, on the Dell)
  leaderboard/models.json    each measured model's name, maker, licence and page
  leaderboard/published.json what others published, by section, each claim with its source
  newsdesk/approved.json     the news items that passed the review step

What comes out (in the site repo): src/_data/{indexes/<slug>.json, leaderboard.json, newsdesk.json, pagedates.json} and
src/public/{index/<slug>/data.{json,csv}, ai-leaderboard/data.{json,csv}, ai-leaderboard/harness.py}.

THE GATE — a row that fails is not published, and the report says why (index/_gate.json):
  G1 an id, a name, and a source with an https URL           G2 every source and the row carry a grade A–E
  G3 a user figure is a range with a unit, a grade and a source; «users» is a unit only when the source says users
  G4 a Hebrew summary of at most 45 words                    G5 checked within the last 90 days
  G6 not dead: the row's page or one of its sources answers (a 403/429 is a bot wall, not a dead page)
  G7 nothing about Bina Solutions or DGO except Bina's own disclosed row
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index"
LB = HERE / "leaderboard"
NEWS = HERE / "newsdesk"
HARNESS = HERE.parent.parent / "ollama" / "leaderboard" / "harness.py"
TODAY = dt.date.today()
MAX_AGE_DAYS = 90
GRADES = set("ABCDE")
UNITS_HE = {   # what the source counts, in Hebrew — never turned into «users» unless the source says users
    "businesses": "עסקים", "businesses in israel": "עסקים בישראל", "business owners": "בעלי עסקים", "business organizations": "ארגונים עסקיים",
    "businesses and companies": "עסקים וחברות", "businesses and freelancers": "עסקים ועצמאים", "self-employed business owners": "בעלי עסקים עצמאיים",
    "self-employed people": "עצמאים", "paying customers": "לקוחות משלמים", "customers": "לקוחות", "active customers": "לקוחות פעילים",
    "satisfied customers": "לקוחות", "customers (businesses)": "לקוחות עסקיים", "customers (companies)": "חברות לקוחות",
    "customers (organizations)": "ארגונים לקוחות", "customers (libraries and institutions)": "ספריות ומוסדות",
    "enterprise customers": "לקוחות ארגוניים", "enterprises": "ארגונים", "organizations": "ארגונים", "companies": "חברות",
    "arr customer accounts": "חשבונות לקוח משלמים", "gtm / revenue teams": "צוותי מכירות", "brands": "מותגים",
    "registered users": "משתמשים רשומים", "users": "משתמשים", "stores": "חנויות", "live stores": "חנויות פעילות",
    "devices": "מכשירים", "venues": "בתי עסק", "merchants": "בתי עסק", "employees using it": "עובדים", "downloads": "הורדות",
    "active installs": "התקנות פעילות", "wordpress sites": "אתרי WordPress", "wordpress/woocommerce sites": "אתרי WordPress/WooCommerce",
    "premium subscriptions": "מנויים בתשלום", "terminals": "מסופים", "credit cards in daily use": "כרטיסי אשראי בשימוש יומי",
    "schools and educational institutions": "בתי ספר ומוסדות חינוך",
}


def unit_he(unit: str) -> str:
    """The source's own unit in Hebrew: the whole phrase, else its head before a bracket, else the Hebrew the
    researcher put in the bracket. A unit with no Hebrew is shown as it is — and said by the export."""
    u = (unit or "").strip()
    low = u.lower()
    if low in UNITS_HE:
        return UNITS_HE[low]
    head = low.split(" (")[0].strip()
    if head in UNITS_HE:
        return UNITS_HE[head]
    m = re.search(r"\(([^)]*[\u0590-\u05FF][^)]*)\)", u)
    if m:
        return m.group(1).strip()
    print(f"unit without Hebrew: {u!r}", file=sys.stderr)
    return u
DEAD = {404, 410}
#: The link check's answers, read once by main(); render() drops a source that is dead.
LINKS: dict = {}


def _load(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _https(u) -> bool:
    return isinstance(u, str) and u.startswith("https://")


# ── links ────────────────────────────────────────────────────────────────────────────────────────
#: Sites answer a script's own User-Agent with 404 or 403 where a browser gets the page (measured 2026-11-05:
#: similarweb.com, bug.co.il, thenextweb.com, dealroom.co), so the check asks the way a reader's browser asks.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _status(url: str) -> int:
    """The HTTP status of one URL: HEAD, then GET when HEAD is refused. 0 = no answer (unknown, never «dead»)."""
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")      # a Hebrew file name is legal in a page, not in urllib
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept-Language": "he,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 400, 501, 404, 410):
                continue                                # a server that does not do HEAD is asked with GET
            return e.code
        except Exception:  # noqa: BLE001 — DNS, TLS, timeout: no answer
            if method == "HEAD":
                continue
            return 0
    return 0


def linkcheck(urls: set) -> dict:
    cache = _load(INDEX / "_links.json", {})
    todo = sorted(u for u in urls if _https(u))
    with ThreadPoolExecutor(12) as ex:
        for u, st in zip(todo, ex.map(_status, todo)):
            cache[u] = {"status": st, "at": TODAY.isoformat()}
    (INDEX / "_links.json").write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return cache


def _dead(url, links: dict) -> bool:
    return (links.get(url) or {}).get("status") in DEAD


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────
def gate(row: dict, links: dict) -> list:
    why = []
    srcs = [s for s in (row.get("sources") or []) if isinstance(s, dict)]
    if not row.get("id") or not (row.get("name_he") or row.get("name_en")):
        why.append("G1 no id or name")
    if not any(_https(s.get("url")) and not _dead(s["url"], links) for s in srcs):
        why.append("G1 no https source that answers (the row's own page does not count as its source)")
    if row.get("grade") not in GRADES or any(s.get("grade") not in GRADES for s in srcs):
        why.append("G2 a grade is missing")
    u = row.get("users")
    if u:
        if not u.get("unit") or u.get("grade") not in GRADES or not _https(u.get("source_url")):
            why.append("G3 the user figure lacks a unit, grade or source")
        if u.get("low") is not None and u.get("high") is not None and u["low"] > u["high"]:
            why.append("G3 low > high")
        if u.get("unit") == "users" and "user" not in (u.get("note") or "").lower():
            why.append("G3 «users» without the source saying users")
    summary = row.get("summary_he") or ""
    if not summary or len(summary.split()) > 45:
        why.append("G4 the summary is missing or longer than 45 words")
    try:
        if (TODAY - dt.date.fromisoformat(str(row.get("verified_at"))[:10])).days > MAX_AGE_DAYS:
            why.append("G5 checked more than 90 days ago")
    except ValueError:
        why.append("G5 no check date")
    if _https(row.get("url")) and _dead(row["url"], links) and all(_dead(s.get("url"), links) for s in srcs):
        why.append("G6 the row's page and every source are dead")
    # G7 reads the WHOLE row, case-blind: names in both languages, the product's English name, and both domains
    text = json.dumps(row, ensure_ascii=False).lower()
    if row.get("id") != "bina-solutions" and re.search(
            r"בינה סו?לושנס|bina solutions|הלשכה הדיגיטלית|digital office|\bdgo\b|bina-solutions\.co\.il|digital-office\.co\.il", text):
        why.append("G7 speaks about Bina or DGO")
    return why


# ── how each index shows its figure ──────────────────────────────────────────────────────────────
def _n(x) -> str:
    return f"{int(x):,}" if isinstance(x, (int, float)) and float(x).is_integer() else (f"{x:,}" if isinstance(x, (int, float)) else str(x))


def fig_users(r, meta):
    u = r.get("users")
    if not u or u.get("low") is None or _dead(u.get("source_url"), LINKS):
        return None, None, None
    lo, hi = u.get("low"), u.get("high")
    unit = unit_he(u.get("unit"))
    # «250,000+» flips around in a right-to-left line; the words say it the way Hebrew does
    val = f"יותר מ-{_n(lo)}" if hi is None else (_n(lo) if lo == hi else f"{_n(lo)}–{_n(hi)}")
    note = "בעולם" if u.get("scope") == "worldwide" else ("בישראל" if u.get("scope") == "israel" else None)
    return f"{val} {unit}", u.get("grade"), note


def fig_provider(r, meta):
    t = meta.get("types", {}).get(r.get("type"), r.get("type") or "")
    tools = [x for x in (r.get("tools") or []) if x and x.lower() not in ("custom",)]
    return " · ".join([t] + ([", ".join(tools[:4])] if tools else [])), r.get("grade"), r.get("city")


def fig_payments(r, meta):
    t = meta["categories"].get(r.get("type"), r.get("type") or "")
    lic = r.get("licence") or {}
    reg = lic.get("regulator") or ""
    reg_he = {"Bank of Israel": "בנק ישראל", "Israel Securities Authority": "רשות ניירות ערך"}.get(reg, reg)
    return t + (f" · רישיון: {reg_he}" if reg_he else ""), lic.get("grade") or r.get("grade"), None


def fig_invoice(r, meta):
    a = r.get("allocation_numbers") or {}
    if isinstance(a, bool):
        a = {"supported": a}
    how = {"automatic": "אוטומטי", "manual": "ידני", "plugin": "בתוסף"}.get(a.get("how"), None)
    sup = a.get("supported")
    txt = "נתמך" + (f" ({how})" if how else "") if sup else ("לא נתמך" if sup is False else "לא ידוע")
    p = r.get("price_from_ils") or {}
    price = f"מ-₪{_n(p['amount'])} ל{ {'month': 'חודש', 'year': 'שנה'}.get(p.get('period'), p.get('period') or '') }" if p.get("amount") else None
    return txt, a.get("grade") or r.get("grade"), price


def fig_hardware(r, meta):
    p = r.get("price_ils") or {}
    mem = f"{r.get('memory_gb')}GB {({'VRAM': 'VRAM', 'unified': 'זיכרון מאוחד', 'system RAM': 'RAM'}).get(r.get('memory_kind'), r.get('memory_kind') or '')}".strip()
    price = f"₪{_n(p['amount'])}" + (f" ({p.get('store')})" if p.get("store") else "") if p.get("amount") else "מחיר לא נמצא בישראל"
    return f"{mem} · {price}", r.get("grade"), (p.get("note") or None)


def fig_rounds(r, meta):
    lr = r.get("last_round") or {}
    if not lr:
        return None, None, None
    amt = lr.get("amount_usd")
    amount = (f"${amt / 1e9:.1f}B" if amt and amt >= 1e9 else f"${amt / 1e6:.0f}M") if amt else ""
    kind = {"acquired": "נרכשה", "IPO": "הנפקה", "growth": "צמיחה"}.get(lr.get("type"), lr.get("type") or "")
    return " · ".join(x for x in (amount, kind, str(lr.get("date") or "")) if x), lr.get("grade") or r.get("grade"), r.get("status") if r.get("status") and r.get("status") != "private" else None


def fig_grants(r, meta):
    a = r.get("amount") or {}
    st = {"open": "פתוח", "recurring": "חוזר", "unknown": "לא ידוע"}.get(r.get("status"), r.get("status"))
    dl = r.get("deadline")
    note = st + (f" · עד {dl}" if dl and dl not in ("rolling", None) else (" · הגשה שוטפת" if dl == "rolling" else ""))
    return (a.get("text") or None), r.get("grade"), note


def fig_gov(r, meta):
    api = (r.get("api") or {}).get("available")
    cost = r.get("cost")
    cost_he = "חינם" if cost == "free" else (str(cost).replace("fee:", "תשלום:") if cost else None)
    return ("יש API" if api else ("אין API" if api is False else "API: לא ידוע")) + (f" · {cost_he}" if cost_he else ""), r.get("grade"), None


def fig_oss(r, meta):
    g = r.get("github") or {}
    lic = r.get("licence") or g.get("licence") or "?"
    stars = g.get("stars")
    return lic + (f" · ★{_n(stars)}" if stars else ""), r.get("grade"), (f"פעילות אחרונה {g['pushed_at'][:10]}" if g.get("pushed_at") else None)


FIGURES = {"users": fig_users, "provider": fig_provider, "payments": fig_payments, "invoice": fig_invoice,
           "hardware": fig_hardware, "rounds": fig_rounds, "grants": fig_grants, "gov": fig_gov, "oss": fig_oss}


def _label(url: str) -> str:
    """A source's short name: its registrable domain (three labels for .co.il-style names), so a long host such as
    hebrew-llm-leaderboard-leaderboard.hf.space does not widen the column — the full URL is the link."""
    host = re.sub(r"^www\.", "", url.split("/")[2]) if url.count("/") >= 2 else url
    parts = host.split(".")
    keep = 3 if len(parts) >= 3 and parts[-2] in ("co", "org", "gov", "ac", "net", "muni") else 2
    return ".".join(parts[-keep:])


def render(slug: str, meta: dict, rows: list) -> dict:
    cat_field = meta.get("category_field", "category")
    out_rows, cats = [], {}
    for r in rows:
        cat = r.get(cat_field) or ""
        cat_he = meta.get("categories", {}).get(cat, cat)
        figure, fgrade, fnote = FIGURES[meta["figure"]](r, meta)
        name = r.get("name_he") or r.get("name_en")
        # the alternate name without the researcher's bracketed notes («Kryon Systems (acquired by Nintex)»)
        alt = re.sub(r"\s*\([^)]*\)", "", r.get("name_en") or "").strip() or None
        alt = alt if alt and alt not in (name or "") else None
        tags = []
        if meta["figure"] == "hardware":
            for s in (r.get("published_speed") or [])[:2]:
                if s.get("tokens_per_s_gen"):
                    tags.append(f"{s.get('model')}: {s['tokens_per_s_gen']} tok/s")
        if meta["figure"] in ("users", "invoice") and r.get("public_company"):
            tags.append(r["public_company"])
        # a page in Hebrew shows Hebrew tags and stock tickers; English research notes stay in the data download
        tags = [t for t in tags if re.search(r"[\u0590-\u05FF]", t) or re.fullmatch(r"[A-Z]+:[A-Z.]+(; [A-Z]+:[A-Z.]+)*", t) or "tok/s" in t]
        srcs = [{"url": s["url"], "label": _label(s["url"]), "date": s.get("date"), "grade": s.get("grade"),
                 "what": (s.get("what") or "")[:160]} for s in (r.get("sources") or [])
                if _https(s.get("url")) and not _dead(s["url"], LINKS)]
        meta_line = " · ".join(x for x in [r.get("issuer"), r.get("authority"), r.get("who_for") if meta["figure"] in ("grants", "gov") else None] if x)
        out_rows.append({
            "id": r["id"], "name": name, "name_alt": alt, "url": r.get("url") or r.get("official_url") or r.get("how_to_apply_url"),
            "category": cat, "category_he": cat_he, "summary": r.get("summary_he"), "meta": meta_line or None,
            "tags": tags, "figure": figure, "figure_grade": fgrade, "figure_note": fnote, "sources": srcs[:4],
            "search": " ".join(str(x).lower() for x in [name, alt, r.get("summary_he"), cat_he, " ".join(tags), figure or ""] if x),
        })
        cats[cat] = cats.get(cat, 0) + 1
    order = list(meta.get("categories", {}))
    categories = sorted(({"id": c, "he": meta.get("categories", {}).get(c, c), "count": n} for c, n in cats.items() if c),
                        key=lambda c: (order.index(c["id"]) if c["id"] in order else 99, -c["count"]))
    return {"slug": slug, "title": meta["title"], "card": meta["card"], "intro": meta["intro"],
            "seo_title": meta["seo_title"], "seo_description": meta["seo_description"], "method": meta["method"],
            "col_figure": meta["col_figure"], "count_label": meta.get("count_label"), "notes": meta.get("notes", []),
            "updated": max((str(r.get("verified_at"))[:10] for r in rows), default=TODAY.isoformat()),
            "categories": categories, "rows": out_rows,
            "itemlist": {"@context": "https://schema.org", "@type": "ItemList", "name": meta["title"],
                         "numberOfItems": len(out_rows),
                         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": r["name"], "url": r["url"]}
                                             for i, r in enumerate(out_rows[:100]) if r.get("url")]}}


def downloads(site: Path, rel: str, rows: list, columns: list) -> None:
    d = site / "src" / "public" / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow([json.dumps(r.get(c), ensure_ascii=False) if isinstance(r.get(c), (dict, list)) else r.get(c) for c in columns])
    (d / "data.csv").write_text("\ufeff" + buf.getvalue(), encoding="utf-8")  # the BOM lets Excel read Hebrew


# ── the leaderboard ──────────────────────────────────────────────────────────────────────────────
def leaderboard(site: Path) -> dict | None:
    # without results the page still carries what was published, the tiers and the machine; the measured table
    # says that runs are in progress (`status.running`) rather than the page disappearing
    res = _load(LB / "results.json") or {"generated_at": TODAY.isoformat(), "models": [], "sets": {}}
    res.setdefault("sets", {})
    models = _load(LB / "models.json", {})
    pub = _load(LB / "published.json", {})
    measured = []
    for m in res["models"]:
        info = models.get(m["model"], {})
        if info.get("hide"):
            continue
        sp = m.get("speed") or {}
        measured.append({
            "model": m["model"], "name": info.get("name", m["model"]), "publisher": info.get("publisher", ""),
            "licence": info.get("licence", "?"), "url": info.get("url", "https://ollama.com/library"),
            "params": (m.get("env", {}).get("model") or {}).get("parameter_size"),
            "quant": (m.get("env", {}).get("model") or {}).get("quantization"),
            "digest": (m.get("env", {}).get("model") or {}).get("digest"),
            "he": m.get("hebrew"), "en": m.get("english"), "parts": m.get("scores"),
            "gen_tps": sp.get("gen_tps"), "prompt_tps": sp.get("prompt_tps"), "mem_gb": sp.get("mem_gb"),
            "speed_runs": sp.get("runs"), "speed_load_max": sp.get("load1_max"),
            "complete": bool(m.get("hebrew") and m["hebrew"].get("complete") and m["answered"] >= m["expected"]
                             and not m.get("errors")),
            "answered": m.get("answered"), "expected": m.get("expected"), "aborted": m.get("aborted"),
        })
    shown = [x for x in measured if x["complete"]]
    # ranks again, among the models the page SHOWS: a half-measured model must not push a shown one down
    for key in ("he", "en"):
        for x in shown:
            if x.get(key):
                x[key] = dict(x[key], rank=1 + sum(1 for o in shown if o is not x and o.get(key) and o[key]["lo"] > x[key]["hi"]))
    shown.sort(key=lambda x: (x["he"] or {}).get("rank") or 99)
    fresh = res.get("models") and (TODAY - dt.date.fromisoformat(res["generated_at"][:10])).days <= 2
    partial = [x["name"] for x in measured if not x["complete"] and not x["aborted"]] if fresh else []
    stopped = [{"name": x["name"], "reason": str(x["aborted"])[:120]} for x in measured if x["aborted"] and not x["complete"]]
    # the published sources go through the same link check as the indexes: a dead one leaves the page
    for sec in pub.values():
        for r in (sec if isinstance(sec, list) else []):
            r["sources"] = [s_ for s_ in r.get("sources", []) if not _dead(s_.get("url"), LINKS)]
    env = next((m.get("env") for m in res["models"] if m.get("env")), {}) or {}
    mach = models.get("_machine", {})
    sources = {s["url"] for sec in pub.values() if isinstance(sec, list) for r in sec for s in r.get("sources", [])}
    out = {
        # the page's date is the newest thing on it: the last scoring, else the day the published results were checked
        "updated": res["generated_at"][:10] if res.get("models") else (pub.get("checked") or TODAY.isoformat()),
        "measured": shown,
        "status": {"pending": not res.get("models"), "partial": partial, "stopped": stopped, "done": len(shown)},
        "machine": {"name": mach.get("name"), "cpu": mach.get("cpu") or (env.get("machine") or {}).get("cpu"),
                    "ram_gb": (env.get("machine") or {}).get("ram_gb") or mach.get("ram_gb"), "gpu": mach.get("gpu", ""),
                    "runtime": f"Ollama {env.get('ollama_version') or mach.get('ollama_version', '')}".strip(), "settings": mach.get("settings", "")},
        "method": {"n_mcq": res["sets"].get("sets", {}).get("belebele", {}).get("n") or 100, "n_mt": res["sets"].get("sets", {}).get("flores", {}).get("n") or 50,
                   "n_office": models.get("_office_n", 40), "seed": res["sets"].get("seed") or 20261105,
                   "weights_he_text": "Belebele בעברית 25%, Global-MMLU בעברית 25%, תרגום מאנגלית לעברית 20%, משימות משרד בעברית 30%",
                   "weights_en_text": "Belebele באנגלית 50%, Global-MMLU באנגלית 50%"},
        "published": {k: pub.get(k, []) for k in ("frontier", "stt", "tts", "ocr", "embeddings", "oss")},
        "tiers": models.get("_tiers", []), "guides": models.get("_guides", []), "changelog": models.get("_changelog", []),
        "sources_count": len(sources),
    }
    hw = [r for r in _load(INDEX / "local-ai-hardware.json", {"rows": []})["rows"] if (r.get("price_ils") or {}).get("amount")]
    for t in out["tiers"]:
        # the models we measured whose loaded size falls in this tier, then up to two machines from the hardware index
        t["models"] = [{"name": x["name"], "note": f"{x['mem_gb']} GB · {x['gen_tps']} tok/s" if x.get("gen_tps") else f"{x['mem_gb']} GB"}
                       for x in shown if t.get("show_measured") and x.get("mem_gb") and t["min_gb"] < x["mem_gb"] <= t["max_gb"]]
        t["models"] += [{"name": r.get("name_en") or r.get("name_he"), "note": f"₪{_n(r['price_ils']['amount'])} · {r['price_ils'].get('store') or ''}".rstrip(" ·")}
                        for r in sorted((r for r in hw if r.get("tier") in t.get("hw_tiers", [])), key=lambda r: r["price_ils"]["amount"])[:2]]
    downloads(site, "ai-leaderboard", [{k: v for k, v in x.items()} for x in shown],
              ["model", "name", "publisher", "licence", "params", "quant", "digest", "he", "en", "parts", "gen_tps", "prompt_tps", "mem_gb"])
    if HARNESS.exists():
        shutil.copy(HARNESS, site / "src" / "public" / "ai-leaderboard" / "harness.py")
    # the sampled public questions, so anyone can ask exactly them even after the upstream sets change; shared under
    # the sets' own licences (Belebele and FLORES-200 CC BY-SA 4.0, Global-MMLU Apache-2.0), with attribution
    if (LB / "sets").is_dir() and any((LB / "sets").glob("*.jsonl")):
        out = site / "src" / "public" / "ai-leaderboard" / "sets"
        out.mkdir(parents=True, exist_ok=True)
        for f in list((LB / "sets").glob("*.jsonl")) + list((LB / "sets").glob("meta.json")):
            shutil.copy(f, out / f.name)
        (out / "README.txt").write_text(
            "Questions sampled once (seed 20261105) for bina-solutions.co.il/ai-leaderboard/ by harness.py.\n"
            "belebele.jsonl  - from Belebele (Meta AI), CC BY-SA 4.0: https://huggingface.co/datasets/facebook/belebele\n"
            "gmmlu.jsonl     - from Global-MMLU (Cohere Labs), Apache-2.0: https://huggingface.co/datasets/CohereLabs/Global-MMLU\n"
            "flores.jsonl    - from FLORES-200 devtest (Meta AI), CC BY-SA 4.0: https://github.com/facebookresearch/flores\n"
            "These subsets are shared under the same licences. The private office set is not published.\n", encoding="utf-8")
    return out


# ── the news desk ────────────────────────────────────────────────────────────────────────────────
SECTIONS = [  # the owner's eight, in his order (2026-11-04)
    ("ai", "חדשות AI", "מה קורה בבינה מלאכותית: מוצרים, מחקר ושימושים בעסקים."),
    ("llm", "חדשות מודלי שפה", "מודלים חדשים, גרסאות, מחירים ותוצאות במבחנים."),
    ("hardware", "חדשות חומרה", "שבבים, כרטיסים ומחשבים להרצת AI, בעולם ובישראל."),
    ("business", "חדשות עסקים", "מה שקורה בשוק התוכנה והטכנולוגיה לעסקים."),
    ("funding", "גיוסים והשקעות", "סבבי גיוס, רכישות והנפקות בטכנולוגיה וב-AI."),
    ("regulation", "רגולציה", "חוקים, תקנות והנחיות שנוגעים לעסקים, לפרטיות ול-AI."),
    ("global", "חדשות מהעולם", "הסיפורים הגדולים בטכנולוגיה מחוץ לישראל."),
    ("israel", "חדשות ישראל", "טכנולוגיה, AI ועסקים בישראל."),
]


def _news_item(it: dict) -> dict:
    """One approved story in the page's shape, from either source: the review step's file (summary_he/why_he, date)
    or newsflow's `GET /api/site` (the same fields, its date from published_at or when it was found)."""
    return {"title": it.get("title"), "url": it.get("url"), "source": it.get("source"), "section": it.get("section"),
            "lang": it.get("lang") or "he", "status": it.get("status") or "approved",
            "summary": it.get("summary") or it.get("summary_he"), "why": it.get("why") or it.get("why_he"),
            "date": (it.get("date") or it.get("published_at") or it.get("found_at") or "")[:10] or None,
            "reviewed_at": it.get("reviewed_at") or "", "reviewer": it.get("reviewer")}


def newsdesk() -> dict:
    # newsdesk/approved.json — the stories this repo's review step approved; newsdesk/newsflow.json — newsflow's own
    # `GET /api/site` feed once the office runs its review step (DGO-1383). One story, one URL: the first wins.
    seen, items = set(), []
    for f in ("approved.json", "newsflow.json"):
        for it in _load(NEWS / f, {"items": []}).get("items", []):
            n = _news_item(it)
            if n["url"] and n["url"] not in seen and n["summary"] and n["title"]:
                seen.add(n["url"])
                items.append(n)
    secs = []
    for sid, title, intro in SECTIONS:
        its = sorted((i for i in items if i.get("section") == sid and i.get("status") == "approved"),
                     key=lambda i: i.get("date") or "", reverse=True)
        secs.append({"id": sid, "title": title, "intro": intro,
                     "description": f"{title} מבינה סלושנס: {intro}", "items": its,
                     "itemlist": {"@context": "https://schema.org", "@type": "ItemList", "name": title,
                                  "itemListElement": [{"@type": "ListItem", "position": n + 1, "name": i["title"], "url": i["url"]}
                                                      for n, i in enumerate(its[:50])]}})
    return {"updated": max((i["reviewed_at"][:10] for i in items if i.get("reviewed_at")), default=TODAY.isoformat()),
            "min_items": 10, "sections": secs}


# ── real dates for the sitemap ───────────────────────────────────────────────────────────────────
def lastmod(site: Path) -> dict:
    out = {}
    try:
        files = subprocess.run(["git", "-C", str(site), "ls-files", "src"], capture_output=True, text=True, check=True).stdout.split()
        for f in files:
            d = subprocess.run(["git", "-C", str(site), "log", "-1", "--format=%cs", "--", f], capture_output=True, text=True).stdout.strip()
            if d:
                out["./" + f] = d
    except Exception as e:  # noqa: BLE001
        print(f"lastmod: git dates not read ({e})", file=sys.stderr)
    return out


def main(argv: list) -> int:
    only_gate = "--gate" in argv
    args = [a for a in argv if not a.startswith("--")]
    site = Path(args[0]) if args else None
    metas = {k: v for k, v in _load(INDEX / "_indexes.json").items() if not k.startswith("_")}
    allrows = {slug: _load(INDEX / f"{slug}.json", {"rows": []}).get("rows", []) for slug in metas}
    if "--linkcheck" in argv:
        urls = {u for rows in allrows.values() for r in rows for u in [r.get("url")] + [s.get("url") for s in r.get("sources") or []] if u}
        urls |= {s_.get("url") for sec in _load(LB / "published.json", {}).values() if isinstance(sec, list)
                 for r in sec for s_ in r.get("sources", []) if s_.get("url")}
        links = linkcheck(urls)
    else:
        links = _load(INDEX / "_links.json", {})
    LINKS.update(links)
    report, rendered = {"at": TODAY.isoformat(), "indexes": {}}, {}
    for slug, meta in sorted(metas.items(), key=lambda kv: kv[1].get("order", 99)):
        ok, bad = [], []
        for r in allrows[slug]:
            why = gate(r, links)
            (bad.append({"id": r.get("id"), "why": why}) if why else ok.append(r))
        report["indexes"][slug] = {"rows": len(allrows[slug]), "published": len(ok), "failed": bad}
        if ok:
            rendered[slug] = render(slug, meta, ok)
    # the gate's report is for whoever runs the export, not data: it goes where the repo keeps run output
    out = HERE.parent.parent.parent / "ci-artifacts" / "bina-site-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for slug, r in report["indexes"].items():
        print(f"{slug:36} {r['published']:4} published / {r['rows']:4} rows  ({len(r['failed'])} failed the gate)")
    if only_gate or not site:
        return 0
    data = site / "src" / "_data"
    (data / "indexes").mkdir(parents=True, exist_ok=True)
    for old in (data / "indexes").glob("*.json"):
        if old.stem not in rendered:
            old.unlink()
    for slug, ix in rendered.items():
        (data / "indexes" / f"{slug}.json").write_text(json.dumps(ix, ensure_ascii=False, indent=1), encoding="utf-8")
        downloads(site, f"index/{slug}", allrows_published(allrows[slug], report["indexes"][slug]["failed"]),
                  ["id", "name_he", "name_en", "url", "category", "summary_he", "users", "sources", "verified_at"])
    lb = leaderboard(site)
    if lb:
        (data / "leaderboard.json").write_text(json.dumps(lb, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / "newsdesk.json").write_text(json.dumps(newsdesk(), ensure_ascii=False, indent=1), encoding="utf-8")
    # `pagedates`, not `lastmod`: a global data file named lastmod would shadow every page's own `lastmod` field
    (data / "pagedates.json").write_text(json.dumps(lastmod(site), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written into {site}")
    return 0


def public_row(r: dict) -> dict:
    """A row as the public may download it — exactly what the page shows: no dead source, and no user figure whose
    own source is dead (the page shows «—» for it; the download must not carry it either)."""
    r = dict(r)
    r["sources"] = [s for s in (r.get("sources") or []) if _https(s.get("url")) and not _dead(s["url"], LINKS)]
    if isinstance(r.get("users"), dict) and _dead(r["users"].get("source_url"), LINKS):
        r["users"] = None
    return r


def allrows_published(rows: list, failed: list) -> list:
    bad = {f["id"] for f in failed}
    return [public_row(r) for r in rows if r.get("id") not in bad]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
