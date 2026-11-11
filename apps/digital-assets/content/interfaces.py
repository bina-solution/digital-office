#!/usr/bin/env python3
"""interfaces.py — the monthly check of the interfaces the library and the office lean on (DGO-812, seo-1004).

    python3 apps/digital-assets/content/interfaces.py [--month 2026-11] [--file interfaces.yaml] [--out interfaces/]

For each interface of interfaces.yaml, one GET (never a HEAD: gov.il and the Bank of Israel answer HEAD otherwise):
  state      ok | blocked (401/403/429, or a challenge page: Cloudflare, Radware, Incapsula, «הגישה נחסמה») |
             gone (4xx/5xx, no answer, a redirect onto an error page, or an `api` that answers a web page)
  where      the address it ends at
  page       (kind site/process) the title, the h1–h3 headings, and a hash of the visible text — digits out
  api        (kind api) the answer's shape: JSON keys two levels down (every element of a list, keys that are
             dates or numbers as {*}), or the XML root and its children — never the values
Then it compares with the last month kept (interfaces/<YYYY-MM>.json). Between two months where it answered: a new
address, title, shape, or headings gained or lost (as a set; their order alone is said as such). When the state
itself changed, only that is said. A text hash that moved with nothing else is «the content moved».
It writes interfaces/<month>.json (the measurement) and interfaces/<month>.md (what changed, in Hebrew); in the .md,
everything from the MANUAL marker on (notes by hand) is kept when the month is measured again.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:                                      # the Mac host has none; the engine guest does
    sys.exit("interfaces.py needs PyYAML: pip install pyyaml")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recheck  # noqa: E402 — one opener, one agent and one error-page rule for both checks

HERE = Path(__file__).resolve().parent
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
MANUAL = recheck.MANUAL
#: a challenge page's own title (anchored: «Radware Ltd. Investor Relations» is a real page), or its body's marks
CHALLENGE_TITLE = re.compile(r"^(?:just a moment|attention required|radware page|access denied|request rejected"
                             r"|security check)\b|הגישה נחסמה", re.I)
#: the marks of a challenge itself, never of a bot-manager script a real page loads: login.gov.il loads Radware's
#: perfdrive.com on its real page and has no h1–h3 (measured 2026-11-10), so perfdrive is not a mark at all
CHALLENGE_BODY = re.compile(rb"cf-chl|cf_chl_opt|Incapsula incident|captcha-delivery", re.I)
#: a key that is a value — a number, a date, a timestamp with its zone — is shown as {*}
DATA_KEY = re.compile(r"^(?:\d[\d\-:./T]*(?:Z|[+-]\d\d:?\d\d)?)$")
MAX_BYTES = 2 * 1024 * 1024


def fetch(url: str, timeout: float = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": recheck.AGENT, "Accept": "*/*", "Accept-Language": "he"})
    try:
        with recheck._OPENER.open(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES)
            return {"status": r.status, "where": r.geturl(), "type": r.headers.get("Content-Type", ""), "body": raw,
                    "truncated": len(raw) >= MAX_BYTES}
    except urllib.error.HTTPError as e:
        try:                                              # an error page that stalls is still an answer
            raw = e.read(MAX_BYTES)
        except Exception:                                 # noqa: BLE001
            raw = b""
        return {"status": e.code, "where": e.geturl() or url,
                "type": e.headers.get("Content-Type", "") if e.headers else "", "body": raw, "truncated": False}
    except Exception as e:                                # noqa: BLE001 — no answer is a measurement too
        return {"status": None, "where": url, "type": "", "body": b"", "truncated": False,
                "error": str(getattr(e, "reason", e))[:120]}


def decode(raw: bytes, ctype: str) -> str:
    """The page's own charset (header, then <meta>), else UTF-8, else windows-1255 — an Israeli site may be one."""
    m = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    for cs in ([m.group(1) if isinstance(m.group(1), str) else m.group(1).decode()] if m else []) + ["utf-8", "cp1255"]:
        try:
            return raw.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def page_of(raw: bytes, ctype: str = "") -> dict:
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", decode(raw, ctype))
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
    heads = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())
             for h in re.findall(r"(?is)<h[1-3][^>]*>(.*?)</h[1-3]>", t)]
    heads = [re.sub(r"\d", "", h).strip() for h in heads if h]          # «SALE 1+1», «עודכן 2026» never churn
    heads = [h for h in heads if h]
    visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())
    return {"title": " ".join(html.unescape(title.group(1)).split())[:200] if title else "",
            "headings": heads,                                          # all of them: compared as a whole
            "headings_sha": hashlib.sha256("\n".join(sorted(heads)).encode()).hexdigest()[:16],   # all of them
            "text_sha": hashlib.sha256(re.sub(r"\d", "", visible).encode()).hexdigest()[:16]}


def shape_of(raw: bytes, ctype: str) -> list[str] | None:
    """The answer's shape, never its values: JSON keys two levels down, or the XML root and its children."""
    try:
        doc = json.loads(raw)
    except ValueError:
        doc = None
    if doc is not None:
        def keys(v, prefix="", depth=0) -> set:
            if isinstance(v, list):                       # every element, and a list is always «x.[]»
                found = {prefix + "[]"}
                for el in v:
                    found |= keys(el, prefix + "[]", depth)
                return found
            if isinstance(v, dict) and depth < 2:
                found = set()
                for k, sub in v.items():
                    name = "{*}" if DATA_KEY.match(str(k)) else str(k)
                    found |= {prefix + name} | keys(sub, prefix + name + ".", depth + 1)
                return found
            return set()
        return sorted(keys(doc))
    xml = ("xml" in ctype and "html" not in ctype) or raw.lstrip().startswith(b"<?xml")
    if xml and b"<html" not in raw[:4096].lower():        # a text/xml error page that is HTML is not the API's data
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return None
        strip = lambda tag: tag.split("}")[-1]           # noqa: E731
        return [strip(root.tag)] + sorted({strip(c.tag) for c in root})
    return None


def measure(entry: dict) -> dict:
    got = fetch(entry["url"])
    status, where, raw, ctype = got["status"], got["where"], got["body"], (got["type"] or "").lower()
    out = {"status": status, "where": where}
    looks_html = "html" in ctype or raw.lstrip()[:1] == b"<"
    page = page_of(raw, ctype) if raw and looks_html else None
    bare = len((page or {}).get("headings") or []) < 2              # a challenge page has next to nothing on it
    if status in recheck.BLOCKED or (bare and CHALLENGE_BODY.search(raw[:200_000])) \
            or (page and CHALLENGE_TITLE.search(page["title"])):
        out.update(state="blocked", note=(page or {}).get("title", ""))
        return out
    redirected = urllib.parse.unquote(where).rstrip("/") != urllib.parse.unquote(entry["url"]).rstrip("/")
    if status is None or status >= 300 or (redirected and recheck.ERROR_PAGE.search(urllib.parse.urlsplit(where).path)):
        out.update(state="gone", note=got.get("error", ""))
        return out
    if entry.get("kind") == "api":
        shape = None if got["truncated"] else shape_of(raw, ctype)
        if shape is None:                                 # an API that answers a web page, or an answer cut short
            out.update(state="gone", note="truncated at 2 MiB" if got["truncated"] else
                       f"answered {ctype or 'something'} that is not its data: «{(page or {}).get('title', '')}»")
            return out
        out.update(state="ok", shape=shape)
        return out
    out["state"] = "ok"
    out.update(page or {"title": "", "headings": [], "headings_sha": "", "text_sha": ""})
    return out


def compare(now: dict, before: dict | None) -> list[str]:
    """What changed for one interface since the last month, in Hebrew."""
    if before is None:
        return ["נמדד לראשונה"]
    out = []
    if now.get("where") != before.get("where"):
        out.append(f"כתובת: {before.get('where')} → {now.get('where')}")
    if now.get("state") != before.get("state"):
        return [f"מצב: {before.get('state')} → {now.get('state')}"] + out      # the content is not comparable
    if now.get("state") != "ok":
        return out
    if now.get("title") != before.get("title"):
        out.append(f"כותרת: «{before.get('title')}» → «{now.get('title')}»")
    if now.get("shape") != before.get("shape"):
        gone = sorted(set(before.get("shape") or []) - set(now.get("shape") or []))
        new = sorted(set(now.get("shape") or []) - set(before.get("shape") or []))
        out.append(f"מבנה התשובה: נוספו {new or '—'}, ירדו {gone or '—'}")
    if now.get("headings_sha") != before.get("headings_sha"):
        a, b = collections.Counter(before.get("headings") or []), collections.Counter(now.get("headings") or [])
        new, gone = sorted((b - a).elements()), sorted((a - b).elements())
        out.append(f"כותרות: נוספו {new[:5] or '—'}, ירדו {gone[:5] or '—'}" if new or gone
                   else "כותרות: אותן כותרות, בסדר אחר או בכמות אחרת")
    if not out and now.get("text_sha") != before.get("text_sha"):
        out.append("התוכן זז (המבנה, הכתובת והכותרות לא השתנו)")
    return out


def last_before(out: Path, month: str) -> dict | None:
    kept = sorted(p for p in out.glob("*.json") if MONTH.fullmatch(p.stem) and p.stem < month)
    return json.loads(kept[-1].read_text(encoding="utf-8")) if kept else None


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def report(entries: list, snap: dict, before: dict | None) -> str:
    states = [v["state"] for v in snap["interfaces"].values()]
    lines = [f"# הממשקים שהספרייה והלשכה נשענות עליהם — {snap['month']}", "",
             f"- נמדד: {snap['taken_at']} · {len(entries)} ממשקים · עובדים: {states.count('ok')} · "
             f"נחסמו לרובוט (נפתחים בדפדפן של הלשכה): {states.count('blocked')} · לא עונים: {states.count('gone')}",
             f"- מושווה ל: {before['month'] if before else '— (המדידה הראשונה)'}", "",
             "| ממשק | של | סוג | מצב | מה השתנה |", "|---|---|---|---|---|"]
    for e in entries:
        now = snap["interfaces"][e["id"]]
        prev = (before or {}).get("interfaces", {}).get(e["id"])
        what = "; ".join(compare(now, prev)) or "לא השתנה"
        state = {"ok": "עובד", "blocked": "נחסם לרובוט", "gone": "לא עונה"}[now["state"]]
        lines.append(f"| [{_cell(e['name'])}]({e['url']}) | {_cell(e['owner'])} | {e['kind']} | {state} | {_cell(what)} |")
    lines += ["", "השיטה: בקשת GET אחת לכל ממשק ממחשב של הלשכה, בלי הזדהות. נשמרים הכתובת הסופית, הכותרת, כותרות h1–h3,"
              " hash של הטקסט בלי ספרות, ובממשק API מבנה התשובה בלבד — לעולם לא הערכים. ממשק שחוסם רובוט נפתח בדפדפן של"
              " הלשכה, והחסימה עצמה נרשמת. מצב החסימה תלוי לפעמים בלקוח (דואר ישראל חוסם את curl ועונה ל-urllib), ולכן"
              " ממשק כזה עשוי לעבור בין «עובד» ל«נחסם» בין חודשים.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--month", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--file", default=str(HERE / "interfaces.yaml"))
    ap.add_argument("--out", default=str(HERE / "interfaces"))
    a = ap.parse_args(argv)
    if not MONTH.fullmatch(a.month):
        print(f"interfaces: {a.month!r} is not a month (YYYY-MM)", file=sys.stderr)
        return 2
    entries = (yaml.safe_load(Path(a.file).read_text(encoding="utf-8")) or {}).get("interfaces") or []
    ids = [e.get("id") for e in entries]
    if len(set(ids)) != len(ids) or not all(str(e.get("url", "")).startswith("https://") for e in entries):
        print("interfaces: every interface has a unique id and an https address", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    snap = {"month": a.month, "taken_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "interfaces": {e["id"]: measure(e) for e in entries}}
    before = last_before(out, a.month)
    (out / f"{a.month}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = out / f"{a.month}.md"
    old = md.read_text(encoding="utf-8") if md.exists() else ""
    kept = old[old.index(MANUAL):] if MANUAL in old else ""          # notes by hand are never overwritten
    md.write_text(report(entries, snap, before) + ("\n" + kept if kept else ""), encoding="utf-8")
    states = [v["state"] for v in snap["interfaces"].values()]
    print(f"interfaces: {a.month} — {states.count('ok')} ok, {states.count('blocked')} blocked, "
          f"{states.count('gone')} gone → {out.name}/{a.month}.md" + (" (notes by hand kept)" if kept else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
