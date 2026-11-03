"""sites.checks.seo — what a search engine and a link preview actually see.

The check reads the site the way a crawler does — EVERY page its sitemap lists, then `/` and the
internal links it finds, bounded — and then applies the rules that decide whether the page can be
FOUND and whether it looks right when it is shared. It reads HTML only: no API keys, no third-party
service, nothing the owner cannot reproduce by opening the page source.

The one thing it does that reaches past the site is asking where the pages SEND the reader: each
external link is probed once, politely (see "external links" below). A link to a page that is gone
is the same defect as a broken internal one — the reader lands on an error — and nobody else will
ever report it.

Deliberately not a score out of 100. A score hides which rule failed, and the owner's next action is
never "raise the score" — it is "this page has no title" or "the sitemap is missing". Every finding
therefore names the URL, the rule, and the fix.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from . import http as H

log = logging.getLogger("sites.checks.seo")

#: Pages the crawl may add by FOLLOWING LINKS. The sitemap is not bounded by this number: every URL
#: it lists is read (up to SITEMAP_MAX_URLS), because a check that looks at 20 of a site's 37 pages
#: reports on a site it has not seen. `max_pages` is the floor of the crawl, not its ceiling.
MAX_PAGES = 20
SITEMAP_MAX_URLS = 500        # a ceiling for a generated sitemap, reported when it is reached
SITEMAP_MAX_FILES = 10        # child files read from a sitemap INDEX
CRAWL_SECONDS = 240           # wall-clock budget of the page crawl; a crawl that stops says so
TITLE_MIN, TITLE_MAX = 15, 65
DESC_MIN, DESC_MAX = 50, 160

# ── external links ───────────────────────────────────────────────────────────────────────────────
# This is the one place in the app that sends requests to strangers on a schedule, so it is built to
# be a polite guest: sequential, a fixed number of URLs per run and per host, a gap between two
# requests to the same host, and every answer REMEMBERED per host — for hours, across runs and across
# sites — so a weekly scan of three sites that all link to github.com asks github.com once.
EXTERNAL_MAX_URLS = 60        # requests sent per run, in total
EXTERNAL_PER_HOST = 5         # ... and to any one host
EXTERNAL_TIMEOUT = 8          # seconds, per request
EXTERNAL_SECONDS = 90         # wall-clock budget of all the probes of one run
EXTERNAL_HOST_GAP = 1.0       # seconds between two requests to the same host
EXTERNAL_MAX_HOPS = 5         # redirects followed, each one checked before it is requested
EXTERNAL_TTL = 6 * 3600       # an answer is reused this long
EXTERNAL_ERROR_TTL = 1800     # a host that did not answer is left alone this long
EXTERNAL_HOSTS_KEPT = 300     # the memory is bounded too: hosts remembered ...
EXTERNAL_URLS_KEPT = 100      # ... and URLs remembered per host
#: 4xx that say "I will not serve a robot" rather than "this page is gone": reported, not as broken.
BLOCKS = (401, 403, 429, 999)

_lock = threading.Lock()
#: host → {"last": when it was last asked, "down": until when it is left alone, "why": the reason,
#:         "seen": {url: (when, status, why)}} — the per-host memory described above.
_hosts: dict[str, dict] = {}
_clock = time.monotonic       # the two seams the tests replace
_sleep = time.sleep


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


# ── the sitemap: every page the site says it has ─────────────────────────────────────────────────
def _locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def _read_sitemap(text: str, own: tuple[str, ...]) -> tuple[list[str], int, bool]:
    """Every page URL a sitemap names → (urls, files read, True when SITEMAP_MAX_URLS cut the list).

    A sitemap INDEX (`<sitemapindex>`) lists other sitemaps, and a big site has nothing else:
    reading only the index would call a 40,000-page site a five-page one. Child files are read one
    level deep, at most SITEMAP_MAX_FILES of them, and only on the site's own hosts — the file is the
    site's own input, and a `<loc>` that points at `http://sites:8979/` must not make the office
    fetch it.
    """
    files = 1
    if re.search(r"<sitemapindex\b", text):
        pages: list[str] = []
        for child in _locs(text)[:SITEMAP_MAX_FILES]:
            if urlparse(child).netloc not in own:
                continue
            r = H.fetch(child, timeout=15)
            if r.get("status") == 200:
                pages += _locs(r.get("text", ""))
                files += 1
    else:
        pages = _locs(text)
    urls = list(dict.fromkeys(pages))                       # duplicates dropped, order kept
    return urls[:SITEMAP_MAX_URLS], files, len(urls) > SITEMAP_MAX_URLS


# ── external links: where the pages send the reader ──────────────────────────────────────────────
def _blocked(host: str) -> str | None:
    """Why NO request may go to `host`: "private" or "dns"; None when one may.

    A link comes out of a web page, and a web page is somebody's input: an href of
    `http://169.254.169.254/` or `http://sites:8979/` must not make the office knock on its own
    network. So a name is asked only if every address it resolves to is a public one — and the check
    is made again for every redirect hop. A name that does not resolve at all is "dns": a dead link.
    """
    host = (host or "").strip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
        return "private"
    try:
        return None if ipaddress.ip_address(host).is_global else "private"
    except ValueError:
        pass                                                # a name, not an address
    if "." not in host:
        return "private"                                    # a bare name is a container or a LAN machine
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return "dns"
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                return "private"
        except ValueError:
            return "private"
    return None


def _probe(url: str, session: requests.Session | None = None) -> tuple[int | None, str]:
    """One external URL → (status, why). `why` is "" when a status came back, else what stopped us:
    "private", "dns", "hops", "timeout", "tls" or "connection".

    HEAD first — it costs the other side no body. A HEAD answered with 4xx/5xx is asked again as a GET
    whose body is never read: plenty of servers mishandle HEAD and serve the GET fine, and reporting
    those would be a false finding the owner has to disprove by hand. Redirects are walked by hand,
    like `H.fetch` does, so the address behind every hop is checked before anything is sent to it.
    """
    s = session or H.session()
    cur = url
    status: int | None = None
    for _ in range(EXTERNAL_MAX_HOPS + 1):
        why = _blocked(urlparse(cur).hostname or "")
        if why:
            # The link itself is the problem on the first hop. Later on, the link answered — with a
            # redirect we decline to follow into a private address — and that answer stands.
            return (None, why) if status is None else (status, "")
        try:
            r = s.head(cur, timeout=EXTERNAL_TIMEOUT, allow_redirects=False)
            if r.status_code >= 400:
                r = s.get(cur, timeout=EXTERNAL_TIMEOUT, allow_redirects=False, stream=True)
                r.close()
        except requests.Timeout:
            return None, "timeout"
        except requests.exceptions.SSLError:
            return None, "tls"
        except requests.RequestException:
            return None, "connection"
        status = r.status_code
        loc = r.headers.get("location")
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        return status, ""
    return None, "hops"


def _seen_at(host: str, url: str) -> float:
    with _lock:
        return _hosts.get(host, {}).get("seen", {}).get(url, (0.0,))[0]


def _check_external(targets: dict[str, list[str]]) -> tuple[dict[str, tuple[int | None, str]], dict]:
    """The external URLs a crawl found (url → the pages linking to it) → ({url: (status, why)}, stats).

    Bounded three ways (requests per run, requests per host, seconds), polite two ways (one request at
    a time, EXTERNAL_HOST_GAP between two to the same host) and remembered per host: an answer is
    reused for EXTERNAL_TTL by any later run of any site in this process, and a host that did not
    answer — or answered 429, "slow down" — is left alone for EXTERNAL_ERROR_TTL instead of being
    asked about each of its URLs. URLs go round-robin over the hosts, so the gap is almost never
    waited for, and the ones with the OLDEST answer (or none) go first — a limit that bites then
    bites a different URL each run. What was not asked is counted: a check that stops early says so.
    """
    stats = {"links": len(targets), "hosts": 0, "checked": 0, "cached": 0, "skipped": 0,
             "unreachable": 0, "private": 0}
    by_host: dict[str, list[str]] = {}
    for url in targets:
        by_host.setdefault((urlparse(url).hostname or "").lower(), []).append(url)
    stats["hosts"] = len(by_host)
    for host, queue in by_host.items():
        queue.sort(key=lambda u: _seen_at(host, u))
    rounds = max((len(q) for q in by_host.values()), default=0)
    order = [q[i] for i in range(rounds) for q in by_host.values() if i < len(q)]
    verdicts: dict[str, tuple[int | None, str]] = {}
    sent: dict[str, int] = {}
    session = H.session()
    deadline = _clock() + EXTERNAL_SECONDS
    for url in order:
        host = (urlparse(url).hostname or "").lower()
        with _lock:
            st = _hosts.setdefault(host, {"last": None, "down": 0.0, "why": "", "seen": {}})
            hit, down, why_down, last = st["seen"].get(url), st["down"], st["why"], st["last"]
        now = _clock()
        if hit and now - hit[0] < (EXTERNAL_TTL if hit[1] is not None else EXTERNAL_ERROR_TTL):
            verdicts[url] = (hit[1], hit[2])
            stats["cached"] += 1
            continue
        if down > now:                                      # this host did not answer a moment ago
            if why_down == "dns":
                verdicts[url] = (None, "dns")               # a name that does not exist, for all its URLs
            stats["unreachable"] += 1
            continue
        wait = 0.0 if last is None else max(0.0, last + EXTERNAL_HOST_GAP - now)
        if (sum(sent.values()) >= EXTERNAL_MAX_URLS or sent.get(host, 0) >= EXTERNAL_PER_HOST
                or now + wait >= deadline):
            stats["skipped"] += 1
            continue
        if wait:
            _sleep(wait)
        status, why = _probe(url, session)
        if status is not None and status >= 500:            # a 5xx is as often a hiccup as a fault: once more
            _sleep(EXTERNAL_HOST_GAP)
            status, why = _probe(url, session)
        if why == "private":
            stats["private"] += 1                           # nothing was sent; nothing to remember
            continue
        sent[host] = sent.get(host, 0) + 1
        stats["checked"] += 1
        done = _clock()
        with _lock:
            st["last"] = done
            st["seen"][url] = (done, status, why)
            while len(st["seen"]) > EXTERNAL_URLS_KEPT:
                st["seen"].pop(next(iter(st["seen"])))
            if status is None or status == 429:             # no answer, or "slow down": leave the host be
                st["down"], st["why"] = done + EXTERNAL_ERROR_TTL, why or "rate"
            while len(_hosts) > EXTERNAL_HOSTS_KEPT:
                _hosts.pop(next(iter(_hosts)))
        verdicts[url] = (status, why)
        if status is None:
            stats["unreachable"] += 1
    return verdicts, stats


def _external_findings(verdicts: dict[str, tuple[int | None, str]],
                       targets: dict[str, list[str]]) -> list[dict]:
    """One finding per external URL that answered 4xx/5xx (or whose domain does not exist), however
    many pages link to it — a link in the header and footer of 36 pages is ONE thing to fix.

    A page that merely refuses a robot (401/403/429/999) is an `info`, apart, under its own code: a
    site that will not talk to a crawler is not a site that is gone, and calling its links broken
    would send the owner to "repair" links that work. A connection that failed (timeout, TLS) is not
    a finding at all — from here that is as likely our network as their server; it is in the summary.
    """
    broken: list[dict] = []
    blocked: list[dict] = []
    for url, (status, why) in verdicts.items():
        if status is None and why != "dns":
            continue
        if status is not None and status < 400:
            continue
        pages = targets.get(url) or [""]
        path = urlparse(pages[0]).path or "/"
        more = f" · וגם ב-{len(pages) - 1} עמודים נוספים" if len(pages) > 1 else ""
        key = f"{(urlparse(url).hostname or '')[:60]}:{hashlib.sha1(url.encode()).hexdigest()[:8]}"
        if status in BLOCKS:
            blocked.append(H.finding(
                f"external_blocked:{key}", "info",
                f"אתר היעד של קישור חיצוני לא ענה לבדיקה ({status}) ב-{path}", f"{url}{more}",
                "פתח את הקישור בדפדפן. אם הוא עובד, אין מה לתקן: האתר חוסם בדיקות אוטומטיות.",
                pages[0]))
            continue
        what = "הדומיין אינו קיים" if status is None else str(status)
        broken.append(H.finding(
            f"broken_external:{key}", "warn", f"קישור חיצוני שבור ({what}) ב-{path}", f"{url}{more}",
            "תקן את הכתובת או הסר את הקישור — מי שלוחץ עליו מגיע לעמוד שגיאה.", pages[0]))
    return broken[:20] + blocked[:10]


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
    bare = host[4:] if host.startswith("www.") else host
    own = (bare, f"www.{bare}")                  # both spellings are THIS site, never an external link
    sitemap = H.fetch(f"{base}/sitemap.xml", timeout=15)
    sm_text = sitemap.get("text", "") if sitemap.get("status") == 200 else ""
    urls, sm_files, sm_capped = _read_sitemap(sm_text, own) if sm_text else ([], 0, False)
    summary["sitemap"] = {"present": bool(sm_text), "urls": len(urls), "files": sm_files,
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
        if sm_capped:
            findings.append(H.finding("sitemap_capped", "info",
                                      f"ה-sitemap ארוך מ-{SITEMAP_MAX_URLS} כתובות",
                                      f"נבדקו {SITEMAP_MAX_URLS} הראשונות.",
                                      "פצל ל-sitemap index קטן יותר, או הגדל את SITEMAP_MAX_URLS "
                                      "ב-checks/seo.py."))

    # ── crawl ────────────────────────────────────────────────────────────────────────────────────
    seen: dict[str, dict] = {}
    home = base + "/"
    wanted = list(dict.fromkeys([home] + [u for u in urls if urlparse(u).netloc in own]))
    queue = list(wanted)
    limit = max(max_pages, len(wanted))          # the sitemap is read in full; max_pages is the floor
    pages: list[dict] = []
    titles: dict[str, list[str]] = {}
    external: dict[str, list[str]] = {}          # external URL → the pages that link to it
    deadline = time.monotonic() + CRAWL_SECONDS
    while queue and len(pages) < limit and time.monotonic() < deadline:
        url = queue.pop(0)
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
                parts = urlparse(nxt)
                clean = nxt.split("#")[0]
                if parts.netloc not in own:
                    if parts.scheme in ("http", "https") and parts.hostname:
                        pages_of = external.setdefault(clean, [])
                        if url not in pages_of:
                            pages_of.append(url)
                    continue
                if clean not in seen and len(seen) < limit * 3:
                    queue.append(clean)

    uncrawled = [u for u in wanted if u not in seen]
    if uncrawled:
        findings.append(H.finding("crawl_truncated", "info",
                                  f"הסריקה נעצרה לפני סוף ה-sitemap: {len(uncrawled)} כתובות לא נבדקו",
                                  ", ".join(urlparse(u).path or "/" for u in uncrawled[:5]),
                                  "הרץ את הסריקה שוב. אם זה חוזר, האתר איטי מדי לסריקה בתקציב הזמן."))
    summary["sitemap"]["crawled"] = len(wanted) - len(uncrawled)
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
    for u, st in broken[:20]:
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

    home_page = next((p for p in pages if p["path"] == "/"), pages[0] if pages else None)
    if home_page:
        summary["home"] = {"title": home_page["title"], "h1": home_page["h1"][:1],
                           "words": home_page["words"]}

    # ── external links: the pages' own links to other sites ──────────────────────────────────────
    if deep and external:
        try:
            verdicts, ext = _check_external(external)
            summary["external"] = ext
            findings += _external_findings(verdicts, external)
            if ext["skipped"]:
                findings.append(H.finding(
                    "external_partial", "info", f"{ext['skipped']} קישורים חיצוניים לא נבדקו הפעם",
                    f"הבדיקה מוגבלת במכוון: עד {EXTERNAL_MAX_URLS} בקשות, {EXTERNAL_PER_HOST} לכל אתר "
                    f"ו-{EXTERNAL_SECONDS} שניות, כדי לא להציף אף אחד.",
                    "הם ייבדקו בסריקה הבאה, ראשונים בתור."))
        except Exception as e:                               # noqa: BLE001 — the rest of the report stands
            log.exception("external link check failed for %s", host)
            summary["external"] = {"error": type(e).__name__}
            findings.append(H.finding("external_failed", "info",
                                      "בדיקת הקישורים החיצוניים לא הושלמה",
                                      "שגיאה פנימית בבדיקה. הפרטים בלוג של אפליקציית האתרים.",
                                      "הרץ את הסריקה שוב; אם זה חוזר, בדוק את הלוג."))

    return _done(summary, findings)


def _done(summary: dict, findings: list[dict]) -> dict:
    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    summary.update({"errors": errors, "warnings": warns, "findings": len(findings)})
    return {"check": "seo", "summary": summary, "findings": findings,
            "state": "error" if errors else ("warn" if warns else "ok")}
