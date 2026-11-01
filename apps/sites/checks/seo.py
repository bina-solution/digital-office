"""sites.checks.seo — what a search engine and a link preview actually see.

The check crawls the site the way a crawler does — from `/`, following internal links, bounded —
and then applies the rules that decide whether the page can be FOUND and whether it looks right
when it is shared. It reads HTML only: no API keys, no third-party service, nothing the owner
cannot reproduce by opening the page source.

Deliberately not a score out of 100. A score hides which rule failed, and the owner's next action is
never "raise the score" — it is "this page has no title" or "the sitemap is missing". Every finding
therefore names the URL, the rule, and the fix.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from . import http as H

MAX_PAGES = 20
TITLE_MIN, TITLE_MAX = 15, 65
DESC_MIN, DESC_MAX = 50, 160


class Page(HTMLParser):
    """One page's head and structure, extracted with the standard library.

    A parser and not a regex: `<title>` inside a comment, an `<img>` without a closing slash, an
    attribute in single quotes and a `<h1>` split across lines are all things a regex gets wrong,
    and every one of them turns into a false finding the owner has to disprove by hand.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.metas: dict[str, str] = {}
        self.robots = ""
        self.canonical = ""
        self.hreflang: list[str] = []
        self.html_lang = ""
        self.headings: list[tuple[str, str]] = []
        self.imgs = 0
        self.imgs_no_alt = 0
        self.links: list[str] = []
        self.jsonld = 0
        self._cur: str | None = None
        self._buf: list[str] = []
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang", "")
        elif tag == "title":
            self._cur = "title"
        elif tag in ("h1", "h2", "h3"):
            self._cur = tag
            self._buf = []
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "robots":
                self.robots = a.get("content", "")
            elif name:
                self.metas[name] = a.get("content", "")
            if a.get("charset"):
                self.metas["charset"] = a["charset"]
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if rel == "canonical":
                self.canonical = a.get("href", "")
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflang.append(a["hreflang"])
        elif tag == "img":
            self.imgs += 1
            if not a.get("alt"):
                self.imgs_no_alt += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "script":
            if (a.get("type") or "").lower() == "application/ld+json":
                self.jsonld += 1
        elif tag == "body":
            self._in_body = True

    def handle_data(self, data):
        if self._cur:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == self._cur:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                self.title = text
            elif tag in ("h1", "h2", "h3"):
                self.headings.append((tag, text))
            self._cur = None
            self._buf = []


def run(site: dict, max_pages: int = MAX_PAGES, deep: bool = True) -> dict:
    hosts = [h for h in (site.get("hosts") or []) if h]
    if not hosts:
        return {"check": "seo", "state": "error", "summary": {"reason": "לא הוגדר שם אתר"},
                "findings": [H.finding("no_host", "error", "לא הוגדר דומיין לאתר", "", "")]}
    host = hosts[0]
    base = f"https://{host}"
    max_pages = max(1, min(50, int(max_pages or MAX_PAGES)))
    findings: list[dict] = []
    summary: dict = {"host": host, "base": base}

    # ── robots.txt and sitemap.xml: how the site ASKS to be crawled ──────────────────────────────
    robots = H.fetch(f"{base}/robots.txt", timeout=15)
    robots_text = robots.get("text", "") if robots.get("status") == 200 else ""
    summary["robots"] = {"present": bool(robots_text), "status": robots.get("status")}
    if not robots_text:
        findings.append(H.finding("no_robots", "warn", "אין robots.txt",
                                  f"{base}/robots.txt אינו קיים ({robots.get('status')}).",
                                  "הוסף robots.txt עם Sitemap: והרשאות סריקה."))
    elif re.search(r"(?im)^\s*user-agent:\s*\*\s*$(?:.*\n)*?\s*disallow:\s*/\s*$", robots_text):
        findings.append(H.finding("robots_blocks_all", "error", "robots.txt חוסם את כל האתר",
                                  "Disallow: / תחת User-agent: * מוציא את האתר ממנועי החיפוש.",
                                  "הסר את החסימה הגורפת."))
    sitemap = H.fetch(f"{base}/sitemap.xml", timeout=15)
    sm_text = sitemap.get("text", "") if sitemap.get("status") == 200 else ""
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm_text)
    summary["sitemap"] = {"present": bool(sm_text), "urls": len(urls),
                          "status": sitemap.get("status")}
    if not sm_text:
        findings.append(H.finding("no_sitemap", "warn", "אין sitemap.xml",
                                  f"{base}/sitemap.xml אינו קיים או אינו XML.",
                                  "ייצר sitemap.xml (Eleventy/Vite יודעים לעשות זאת) והפנה אליו "
                                  "מ-robots.txt."))
    elif not urls:
        findings.append(H.finding("empty_sitemap", "warn", "ה-sitemap אינו מכיל כתובות", "", ""))
    else:
        http_urls = [u for u in urls if u.startswith("http://")]
        if http_urls:
            findings.append(H.finding("sitemap_http", "warn", "כתובות http ב-sitemap",
                                      ", ".join(http_urls[:3]), "החלף ל-https ב-sitemap."))
        if robots_text and "sitemap" not in robots_text.lower():
            findings.append(H.finding("sitemap_unreferenced", "info",
                                      "ה-sitemap אינו מוצהר ב-robots.txt", "",
                                      "הוסף שורת Sitemap: ל-robots.txt."))

    # ── crawl ────────────────────────────────────────────────────────────────────────────────────
    seen: dict[str, dict] = {}
    queue = ["/"] + [u for u in urls if urlparse(u).netloc in (host, f"www.{host}")][:max_pages]
    pages: list[dict] = []
    titles: dict[str, list[str]] = {}
    while queue and len(pages) < max_pages:
        path = queue.pop(0)
        url = path if path.startswith("http") else urljoin(base + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen[url] = {"status": None}
        r = H.fetch(url, timeout=20)
        seen[url] = {"status": r.get("status"), "ok": r.get("ok"), "error": r.get("error")}
        if not r.get("ok") or r.get("status") != 200:
            continue
        p = Page()
        try:
            p.feed(r.get("text", ""))
        except Exception:                                    # noqa: BLE001 — a broken page is data
            pass
        path_only = urlparse(url).path or "/"
        page = {"url": url, "path": path_only, "title": p.title,
                "title_len": len(p.title), "desc": p.metas.get("description", ""),
                "h1": [t for tag, t in p.headings if tag == "h1"],
                "imgs": p.imgs, "imgs_no_alt": p.imgs_no_alt,
                "words": len(re.sub(r"<[^>]+>", " ", r.get("text", "")).split()),
                "canonical": p.canonical, "lang": p.html_lang, "robots": p.robots,
                "viewport": bool(p.metas.get("viewport")), "jsonld": p.jsonld,
                "hreflang": p.hreflang,
                "og": {k: v for k, v in p.metas.items() if k.startswith("og:")},
                "ms": r.get("ms"), "bytes": r.get("bytes")}
        pages.append(page)
        titles.setdefault(p.title, []).append(path_only)
        if deep:
            for href in p.links:
                if href.startswith(("mailto:", "tel:", "#", "javascript:")):
                    continue
                nxt = urljoin(url, href)
                if urlparse(nxt).netloc not in (host, f"www.{host}"):
                    continue
                clean = nxt.split("#")[0]
                if clean not in seen and len(seen) < max_pages * 3:
                    queue.append(clean)

    summary["pages_crawled"] = len(pages)
    summary["pages"] = [{"path": p["path"], "title": p["title"], "words": p["words"],
                         "status": seen.get(p["url"], {}).get("status")} for p in pages[:40]]

    # ── site-level rules ─────────────────────────────────────────────────────────────────────────
    dupes = {t: ps for t, ps in titles.items() if t and len(ps) > 1}
    for t, ps in list(dupes.items())[:5]:
        findings.append(H.finding("duplicate_title", "warn", f"כותרת כפולה בכמה עמודים: „{t}“",
                                  ", ".join(ps[:5]),
                                  "תן לכל עמוד כותרת ייחודית — זה מה שמופיע בתוצאות החיפוש."))
    soft = H.fetch(f"{base}/this-page-should-not-exist-{abs(hash(host)) % 9999}", timeout=15,
                   follow=False)
    summary["soft404"] = {"status": soft.get("status")}
    if soft.get("status") == 200:
        findings.append(H.finding("soft_404", "warn", "עמוד שלא קיים מחזיר 200",
                                  "כל כתובת מחזירה דף — מנועי חיפוש יאנדקסו אינסוף דפים ריקים.",
                                  "הגדר error_page 404 שמחזיר קוד 404 אמיתי."))
    broken = [(u, v.get("status")) for u, v in seen.items() if v.get("status") and v["status"] >= 400]
    for u, st in broken[:5]:
        findings.append(H.finding(f"broken_link:{urlparse(u).path}", "warn",
                                  f"קישור פנימי שבור ({st})", u,
                                  "תקן או הסר את הקישור."))

    # ── per-page rules ───────────────────────────────────────────────────────────────────────────
    for p in pages:
        u = p["url"]
        if not p["title"]:
            findings.append(H.finding("no_title", "error", f"אין כותרת (title) ב-{p['path']}",
                                      "הכותרת היא מה שמופיע בתוצאות החיפוש ובלשונית.",
                                      "הוסף <title> ייחודי.", u))
        elif not (TITLE_MIN <= p["title_len"] <= TITLE_MAX):
            findings.append(H.finding("title_length", "info",
                                      f"אורך הכותרת {p['title_len']} תווים ב-{p['path']}",
                                      f"מומלץ {TITLE_MIN}–{TITLE_MAX}: „{p['title'][:80]}“",
                                      "קצר או הרחב את הכותרת.", u))
        if not p["desc"]:
            findings.append(H.finding("no_description", "warn",
                                      f"אין meta description ב-{p['path']}", "",
                                      "הוסף תיאור של 50–160 תווים.", u))
        elif not (DESC_MIN <= len(p["desc"]) <= DESC_MAX):
            findings.append(H.finding("description_length", "info",
                                      f"אורך התיאור {len(p['desc'])} תווים ב-{p['path']}",
                                      p["desc"][:120], f"מומלץ {DESC_MIN}–{DESC_MAX} תווים.", u))
        if not p["h1"]:
            findings.append(H.finding("no_h1", "warn", f"אין כותרת ראשית (h1) ב-{p['path']}", "",
                                      "הוסף h1 אחד שמתאר את העמוד.", u))
        elif len(p["h1"]) > 1:
            findings.append(H.finding("multi_h1", "info",
                                      f"{len(p['h1'])} כותרות h1 ב-{p['path']}",
                                      " · ".join(p["h1"][:3]),
                                      "השאר h1 אחד ותרגם את השאר ל-h2.", u))
        if not p["lang"]:
            findings.append(H.finding("no_lang", "warn", f"תג <html> בלי lang ב-{p['path']}", "",
                                      "הוסף lang=\"he\" — בלעדיו מנוע החיפוש מנחש את השפה.", u))
        if not p["canonical"]:
            findings.append(H.finding("no_canonical", "info", f"אין canonical ב-{p['path']}", "",
                                      "הוסף <link rel=canonical> לכתובת הקנונית.", u))
        if p["imgs_no_alt"]:
            findings.append(H.finding("img_alt", "warn",
                                      f"{p['imgs_no_alt']} תמונות בלי alt ב-{p['path']}",
                                      f"מתוך {p['imgs']} תמונות.",
                                      "הוסף alt תיאורי — נדרש לנגישות ולחיפוש תמונות.", u))
        if not p["og"].get("og:title") or not p["og"].get("og:image"):
            findings.append(H.finding("og_tags", "info",
                                      f"תגי שיתוף (Open Graph) חסרים ב-{p['path']}",
                                      f"og:title={'כן' if p['og'].get('og:title') else 'לא'}, "
                                      f"og:image={'כן' if p['og'].get('og:image') else 'לא'}",
                                      "הוסף og:title/og:description/og:image — זה מה שנראה "
                                      "בשיתוף בוואטסאפ/פייסבוק.", u))
        if "noindex" in (p["robots"] or "").lower():
            findings.append(H.finding("noindex", "error", f"העמוד מסומן noindex: {p['path']}",
                                      p["robots"], "הסר את noindex אם העמוד אמור להופיע בחיפוש.", u))
        if p["words"] < 80:
            findings.append(H.finding("thin_content", "info",
                                      f"תוכן דק ({p['words']} מילים) ב-{p['path']}", "",
                                      "הוסף תוכן של ממש — עמוד דק לא מדורג.", u))
        if not p["viewport"]:
            findings.append(H.finding("no_viewport", "warn", f"אין תג viewport ב-{p['path']}",
                                      "בטלפון הדף יוצג מוקטן וללא התאמה לרוחב המסך.",
                                      "הוסף <meta name=\"viewport\" "
                                      "content=\"width=device-width, initial-scale=1\">", u))

    home = next((p for p in pages if p["path"] == "/"), pages[0] if pages else None)
    if home:
        summary["home"] = {"title": home["title"], "h1": home["h1"][:1], "words": home["words"]}

    return _done(summary, findings)


def _done(summary: dict, findings: list[dict]) -> dict:
    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    summary.update({"errors": errors, "warnings": warns, "findings": len(findings)})
    return {"check": "seo", "summary": summary, "findings": findings,
            "state": "error" if errors else ("warn" if warns else "ok")}
