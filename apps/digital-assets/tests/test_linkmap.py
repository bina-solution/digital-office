"""the link map (DGO-793): content/linkmap.py reads every page of each site's sitemap (an index followed) and the
repository's README, keeps each <a> link from one of our ends to another, and keeps its history — the day it was
first seen, the day it was gone — where a page that did not answer keeps its links as they were. Runs against two
local "sites" (localhost and 127.0.0.1) whose pages change between runs.

    python3 apps/digital-assets/tests/test_linkmap.py
"""
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"   # a sandbox's proxy never sees the test
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "content"))
import linkmap  # noqa: E402

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


class Site(BaseHTTPRequestHandler):
    pages: dict = {}
    down: set = set()

    def do_GET(self):
        port = self.server.server_address[1]
        body = None if (port, self.path) in Site.down else Site.pages.get((port, self.path))
        self.send_response(200 if body is not None else (503 if (port, self.path) in Site.down else 404))
        self.end_headers()
        self.wfile.write((body or "").encode())

    def log_message(self, *a):
        pass


def checks() -> None:
    a = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    b = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    for s in (a, b):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    pa, pb = a.server_address[1], b.server_address[1]
    A, B = f"http://localhost:{pa}", f"http://127.0.0.1:{pb}"
    repo = f"{B}/repo"
    sites = {"do": A, "bina": B}
    Site.pages = {
        (pa, "/sitemap.xml"): f"<sitemapindex><sitemap><loc>{A}/sm-pages.xml</loc></sitemap></sitemapindex>",
        (pa, "/sm-pages.xml"): f"<urlset><url><loc>{A}/one</loc></url><url><loc><![CDATA[{A}/two]]></loc></url>"
                               f"<url><loc>{A}/three</loc></url><url><loc>https://elsewhere.test/x</loc></url></urlset>",
        (pa, "/three"): "<p>no links</p>",
        (pa, "/one"): f"<link rel=stylesheet href='{B}/x.css'><!-- <a href='{B}/hidden'>x</a> -->"
                      f"<a href={B}/news>bina</a> <a href=\"{repo}/blob/main/README.md\">repo</a> <a href='/two'>self</a>",
        (pa, "/two"): "<base href='https://example.test/'><a href='https://github.com/bina-solution/digital-office'>"
                      "old</a><a href='https://github.com/bina-solution/digital-office-other'>sibling</a>",
        (pb, "/sitemap.xml"): f"<!DOCTYPE html><html><body><urlset><url><loc>{B}/news</loc></url></urlset></body>",
        (pb, "/news"): f"<a href='{A}/one#top'>do</a>",
        (pb, "/readme"): f"# DGO\n\nThe site: {A}/one, and <a href=\"{B}/news\">bina</a>.\n",
    }
    m = linkmap.measure(sites, repo, f"{B}/readme")
    kinds = sorted((e["kind"], e["from"].rsplit("/", 1)[-1], e["to"].rsplit("/", 1)[-1]) for e in m["edges"])
    check({k: len(v) for k, v in m["pages"].items()} == {"do": 3, "bina": 1},
          f"a sitemap index is followed, CDATA read, another host's page left out: {m['pages']}")
    check(m["sitemap_valid"] == {"do": True, "bina": False}, f"a sitemap that is not valid XML is said: {m['sitemap_valid']}")
    check(kinds == sorted([("do→bina", "one", "news"), ("do→repo", "one", "README.md"), ("do→old-repo", "two",
                                                                                         "digital-office"),
                           ("bina→do", "news", "one#top"), ("repo→do", "repo#readme", "one"),
                           ("repo→bina", "repo#readme", "news")]),
          f"<a> links only (not <link>, not a comment), an unquoted href, a bare URL in the README, a sibling repo is not "
          f"ours: {kinds}")
    check(linkmap.side_of("https://www.bina-solutions.co.il/he/x", linkmap.SITES, linkmap.REPO) == "bina"
          and linkmap.side_of("https://github.com/bina-solution/digital-office-other", linkmap.SITES, linkmap.REPO) is None
          and linkmap.side_of("http://www.github.com/bina-solution/digital-office.git", linkmap.SITES, linkmap.REPO) == "repo"
          and linkmap.side_of("https://x.test/?u=github.com/bina-solution/digital-office", linkmap.SITES,
                              linkmap.REPO) is None,
          "www. is the same site; the repo is its owner and name exactly; an address in a query is not a link to it")

    read = set(m["read"])
    first = linkmap.merge(None, m["edges"], read, "2026-11-10")
    check(len(first) == 6 and all(e["first_seen"] == "2026-11-10" for e in first), f"the first run: {len(first)} links")
    # day 2: /one does not answer; /two drops its old-repo link; bina's page moves to www. and a trailing slash
    Site.down = {(pa, "/one"), (pa, "/three")}
    Site.pages[(pa, "/two")] = "<a href='/one'>self</a>"
    m2 = linkmap.measure(sites, repo, f"{B}/readme")
    m2["edges"] = [{**e, "to": e["to"].replace("#top", "/")} for e in m2["edges"]]
    second = linkmap.merge({"edges": first}, m2["edges"], set(m2["read"]), "2026-11-11")
    by = {(e["kind"], e["from"].rsplit("/", 1)[-1]): e for e in second}
    check(not by[("do→bina", "one")].get("gone") and by[("do→bina", "one")]["first_seen"] == "2026-11-10",
          f"a page that did not answer keeps its links as they were (a 503 is not a deletion): {by.get(('do→bina', 'one'))}")
    check(by[("do→old-repo", "two")].get("gone") == "2026-11-11", "a page that was read and lost a link: gone today")
    check(by[("bina→do", "news")]["first_seen"] == "2026-11-10" and not by[("bina→do", "news")].get("gone"),
          f"a trailing slash or #fragment is the same link: {by[('bina→do', 'news')]}")
    Site.down = set()
    third = linkmap.merge({"edges": second}, linkmap.measure(sites, repo, f"{B}/readme")["edges"],
                          set(linkmap.measure(sites, repo, f"{B}/readme")["read"]), "2026-11-12")
    one = [e for e in third if e["kind"] == "do→bina"]
    check(len(one) == 1 and one[0]["first_seen"] == "2026-11-10", f"…and its history is whole when it answers: {one}")

    doc = {"updated": "2026-11-11", "page_list": m2["pages"], "read": m2["read"], "sitemap_valid": m2["sitemap_valid"],
           "readme_read": m2["readme_read"], "edges": second}
    text = linkmap.report(doc, sites)
    unread_part = text.split("שלא ענו")[1].split("##")[0]
    check("do 1 מתוך 3" in text and "שלא ענו בריצה הזו (2)" in text and f"{A}/one" in unread_part
          and f"{A}/three" in unread_part,
          f"pages read are counted as read; the pages that did not answer are their own list: {text[:400]}")
    without_part = text.split(f"## עמודים ב-{A} בלי קישור")[1].split("##")[0]
    check(f"{A}/three" not in without_part, "a page that did not answer is never listed as «without a link»")
    check("אינו XML תקין" in text and "קישורים שנעלמו" in text, "the broken sitemap and the gone link are said")
    check(f"## עמודים ב-{A} בלי קישור ל-{B} (1)" in text and f"- {A}/two" in text,
          "a page that answered and has no link to the other site is listed (not the one that did not answer)")
    check("לא מקשר לאף אחד" not in text, "a README that links to the sites is not flagged")
    bare = linkmap.report({**doc, "edges": [e for e in first if not e["kind"].startswith("repo→")]}, sites)
    check("לא מקשר לאף אחד משני האתרים" in bare, "a README that links to neither site is said")
    a.shutdown()
    b.shutdown()


def main() -> int:
    try:
        checks()
    except Exception:                                     # noqa: BLE001 — a crash is a failure, said as one
        FAIL.append("the check itself raised: " + traceback.format_exc(limit=4))
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_linkmap: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
