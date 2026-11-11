#!/usr/bin/env python3
"""linkmap.py — the link map between the two sites, the repository and back (DGO-793, seo-802).

    python3 apps/digital-assets/content/linkmap.py [--today 2026-11-10] [--out linkmap/]

Who links to whom, and since when. Every page of each site's sitemap (digital-office.co.il, bina-solutions.co.il;
a sitemap index is followed, a .gz is opened) is read once with a GET, and the public repository's README too.
A link is kept when an <a>/<area> on one of our ends goes to another of them (<base> honoured, comments and <link>
tags not links). Each link keeps the day it was FIRST seen; a link is «gone» only when its page WAS read and no
longer has it — a page that did not answer this run keeps its links as they were (a 503 is not a deletion). Links
are keyed by a normalised address (host lowercase, no www., no default port, no trailing slash), so a sitemap that
moves from www. to the bare host changes nothing.
Run it after every publication: linkmap/links.json is its own history, and linkmap/LINKS.md says it in Hebrew —
how many links each way, the pages that do not link to the other site, the pages that did not answer, the links to
the repository's old private address (404 to everyone but its owner, seo-202), and a sitemap that is not valid XML.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import html
import html.parser
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recheck  # noqa: E402 — one opener and one agent for every check of the library

HERE = Path(__file__).resolve().parent
SITES = {"do": "https://digital-office.co.il", "bina": "https://bina-solutions.co.il"}
REPO = "https://github.com/bina-solution/digital-office"
OLD_REPO = "https://github.com/bina-solution/digital-office"
README = "https://raw.githubusercontent.com/bina-solution/digital-office/main/README.md"
URL = re.compile(r"https?://[^\s)<>\"'\]]+")
MAX_PAGES = 400


def get(url: str, timeout: float = 20) -> tuple[int | None, bytes]:
    req = recheck.urllib.request.Request(recheck._as_sent(url), headers={"User-Agent": recheck.AGENT, "Accept": "*/*"})
    try:
        with recheck._OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read(5 * 1024 * 1024)
    except recheck.urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:                                     # noqa: BLE001 — a page that does not answer is «unread»
        return None, b""


def norm(url: str) -> str:
    """The address a link is known by: lowercase host, no www., no default port, no trailing slash, no #."""
    p = urllib.parse.urlsplit(url.strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    path = p.path.rstrip("/") or ""
    return urllib.parse.urlunsplit((p.scheme.lower(), host + port, path, p.query, ""))


def _repo_path(url: str) -> str | None:
    p = urllib.parse.urlsplit(url)
    if (p.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    parts = [s for s in p.path.split("/") if s]
    return "/".join(s.lower().removesuffix(".git") for s in parts[:2]) if len(parts) >= 2 else None


def side_of(url: str, sites: dict, repo: str, old_repo: str = OLD_REPO) -> str | None:
    """Which end a URL is: a site's key, «repo», «old-repo», or None (not ours)."""
    rp = _repo_path(url)
    if rp is not None:
        return "repo" if rp == _repo_path(repo) else "old-repo" if rp == _repo_path(old_repo) else None
    if url.lower().startswith(repo.lower() + "/") or norm(url) == norm(repo):    # a test's repo, not on github
        return "repo"
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    for key, base in sites.items():
        if host == (urllib.parse.urlsplit(base).hostname or "").lower().removeprefix("www."):
            return key
    return None


class _Anchors(html.parser.HTMLParser):
    """The href of every <a> and <area> (comments and <link> are not links), resolved against <base>."""

    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.base, self.found = page, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href"):
            self.base = urllib.parse.urljoin(self.base, a["href"])
        elif tag in ("a", "area") and a.get("href"):
            self.found.append(urllib.parse.urljoin(self.base, a["href"].strip()))


def sitemap_pages(url: str, depth: int = 0) -> tuple[list[str], bool]:
    """(the pages, whether the sitemap is valid XML). An index is followed one level; a .gz is opened."""
    status, raw = get(url)
    if status != 200:
        return [], False
    if url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return [], False
    try:
        ET.fromstring(raw)
        valid = True
    except ET.ParseError:
        valid = False                                     # read it anyway, and say so
    text = raw.decode("utf-8", "replace")
    locs = [html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", u.strip()))
            for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)]
    if re.search(r"<sitemapindex", text) and depth == 0:
        pages: list[str] = []
        for sub in locs:
            got, ok = sitemap_pages(sub, 1)
            pages += got
            valid = valid and ok
        return sorted(set(pages))[:MAX_PAGES], valid
    return sorted(set(locs))[:MAX_PAGES], valid


def links_on(page: str, sites: dict, repo: str) -> tuple[bool, list[tuple[str, str]]]:
    """(the page answered, [(to, kind)] for every link on it that goes to another of our ends)."""
    status, raw = get(page)
    if status != 200:
        return False, []
    src = side_of(page, sites, repo)
    parser = _Anchors(page)
    parser.feed(raw.decode("utf-8", "replace"))
    out = set()
    for to in parser.found:
        dst = side_of(to, sites, repo)
        if src and dst and dst != src:
            out.add((to, f"{src}→{dst}"))
    return True, sorted(out)


def measure(sites: dict, repo: str, readme: str) -> dict:
    found = {k: sitemap_pages(v.rstrip("/") + "/sitemap.xml") for k, v in sites.items()}
    pages = {k: [p for p in found[k][0] if side_of(p, sites, repo) == k] for k in sites}   # our own pages only
    jobs = [p for k in sites for p in pages[k]]
    edges, read = [], set()
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for page, (ok, links) in zip(jobs, pool.map(lambda p: links_on(p, sites, repo), jobs)):
            if ok:
                read.add(page)
            edges += [{"from": page, "to": to, "kind": kind} for to, kind in links]
    status, raw = get(readme)
    page = repo + "#readme"                               # the README, as a page of the repository it belongs to
    if status == 200:
        read.add(page)
        for to in sorted({u.rstrip(".,;") for u in URL.findall(raw.decode("utf-8", "replace"))}):
            dst = side_of(to, sites, repo)
            if dst in sites:
                edges.append({"from": page, "to": to, "kind": f"repo→{dst}"})
    return {"pages": pages, "read": sorted(read), "sitemap_valid": {k: found[k][1] for k in sites},
            "readme_read": status == 200, "edges": edges}


def merge(old: dict | None, edges: list[dict], read: set, today: str) -> list[dict]:
    """Every link keeps the day it was first seen. A link is gone only when its page WAS read and no longer has it;
    the links of a page that did not answer are carried as they were."""
    key = lambda e: (norm(e["from"]), norm(e["to"]))      # noqa: E731
    readn = {norm(p) for p in read}
    before = {key(e): e for e in (old or {}).get("edges", [])}
    now = {key(e): e for e in edges}
    out = []
    for k, e in now.items():
        prev = before.get(k)                              # a link that was gone and is back is seen anew today
        first = prev["first_seen"] if prev and prev.get("first_seen") and not prev.get("gone") else today
        out.append({**e, "first_seen": first, "last_seen": today})
    for k, e in before.items():
        if k in now:
            continue
        if e.get("gone") or k[0] not in readn:            # already gone, or its page was not read: as it was
            out.append(e)
        else:
            out.append({**e, "gone": today})
    return sorted(out, key=lambda e: (e["kind"], e["from"], e["to"]))


def report(doc: dict, sites: dict) -> str:
    live = [e for e in doc["edges"] if not e.get("gone")]
    read = set(doc.get("read", []))
    kinds = sorted({e["kind"] for e in live})
    lines = [f"# מפת הקישורים בין האתרים והמאגר — {doc['updated']}", "",
             "- עמודים שנקראו: " + ", ".join(f"{k} {sum(p in read for p in doc['page_list'].get(k, []))} מתוך "
                                             f"{len(doc['page_list'].get(k, []))}" for k in sites)
             + f", README {'נקרא' if doc.get('readme_read') else 'לא נקרא'}",
             f"- קישורים חיים: {len(live)} · נעלמו מאז שנמדדו: {sum(bool(e.get('gone')) for e in doc['edges'])}", "",
             "| כיוון | קישורים | עמודים שמקשרים |", "|---|---|---|"]
    for k in kinds:
        lines.append(f"| {k} | {sum(e['kind'] == k for e in live)} | {len({e['from'] for e in live if e['kind'] == k})} |")
    for k, ok in doc.get("sitemap_valid", {}).items():
        if not ok:
            lines += ["", f"- **ה-sitemap של {sites[k]} אינו XML תקין** (מנועי חיפוש עלולים לדחות אותו). הדפים נקראו ממנו בכל זאת."]
    if doc.get("readme_read") and not any(e["kind"].startswith("repo→") for e in live):
        lines += ["", f"- ה-README של המאגר ({REPO}) לא מקשר לאף אחד משני האתרים."]
    old = sorted({e["from"] for e in live if e["kind"].endswith("old-repo")})
    lines += ["", f"## קישורים לכתובת הישנה של המאגר ({len(old)} עמודים)", "",
              f"{OLD_REPO} עונה 404 לכל מי שאינו הבעלים; הכתובת הנכונה: {REPO}", ""]
    lines += [f"- {p}" for p in old] or ["- אין"]
    for k, base in sites.items():
        other = [o for o in sites if o != k][0]
        mine = doc["page_list"].get(k, [])
        unread = sorted(p for p in mine if p not in read)
        without = sorted(p for p in mine if p in read and not any(
            norm(e["from"]) == norm(p) and e["kind"] == f"{k}→{other}" for e in live))
        lines += ["", f"## עמודים ב-{base} בלי קישור ל-{sites[other]} ({len(without)})", ""]
        lines += [f"- {p}" for p in without[:60]] + ([f"- …ועוד {len(without) - 60}"] if len(without) > 60 else [])
        if unread:
            lines += ["", f"## עמודים ב-{base} שלא ענו בריצה הזו ({len(unread)}) — הקישורים שלהם נשמרו כפי שהיו", ""]
            lines += [f"- {p}" for p in unread[:60]]
    gone =[e for e in doc["edges"] if e.get("gone")]
    if gone:
        lines += ["", "## קישורים שנעלמו", ""] + [f"- {e['from']} → {e['to']} (נראה לראשונה {e.get('first_seen')}, "
                                                    f"נעלם {e['gone']})" for e in gone]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=str(HERE / "linkmap"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    old = json.loads((out / "links.json").read_text(encoding="utf-8")) if (out / "links.json").exists() else None
    m = measure(SITES, REPO, README)
    if not any(m["pages"][k] for k in SITES):
        print("linkmap: no sitemap answered — nothing measured, the map is kept as it was", file=sys.stderr)
        return 1
    doc = {"updated": a.today, "page_list": m["pages"], "read": m["read"], "sitemap_valid": m["sitemap_valid"],
           "readme_read": m["readme_read"], "edges": merge(old, m["edges"], set(m["read"]), a.today)}
    (out / "links.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "LINKS.md").write_text(report(doc, SITES), encoding="utf-8")
    live = [e for e in doc["edges"] if not e.get("gone")]
    print(f"linkmap: {len(live)} links, {len(m['read'])} pages read → {out.name}/LINKS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
