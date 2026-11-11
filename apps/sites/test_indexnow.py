"""sites.indexnow — a site the office serves tells the search engines which of its pages changed (DGO-1765).

Measured on 2026-11-10: Bing (the index DuckDuckGo reads) did not hold digital-office.co.il at all, and nothing in
the office ever told an engine that a page was new or had changed. This test runs the module against a synced site
on disk and a recording stand-in for the engine — no request leaves the machine:

  1. the key file: before any announcement there is none; after the first one, `serve()` answers `/<key>.txt`
     with the key (200, text/plain) on the site's domain — and under an entry's path prefix — and no other `.txt`;
  2. the first pass sends every https address of the site's sitemap that the site serves, once, with the key and
     a keyLocation under the entry's path; an address on another host or over http is never sent;
  3. a second pass with nothing changed sends nothing, and does no work: the cache was not synced again, so the
     sitemap is not even read;
  4. a page that changed, a page that left the sitemap, and a new page are sent — and only they;
  5. an engine that refuses (403) or does not answer keeps the addresses for the next try, which waits;
  6. nothing is sent where it is not true: a laptop office (the edge does not answer https), a record that says
     `public.indexnow: false`, a site the office does not serve, an office with `SITES_INDEXNOW=0`, a site whose
     robots.txt closes it to every crawler;
  7. a sitemap index is followed into the sitemaps in the cache;
  8. with the announcement switched off (the code as it was: no key file, nothing sent), cases 1 and 2 FAIL;
  9. the world does not reach this office for the host (a copy, a clone, DNS not moved yet): the key file is
     asked for at its public address first, and nothing is POSTed;
 10. one host refused, another accepted: only the refused host's addresses are sent again;
 11. an address equal to an entry's prefix (`/blog`) is never sent — the key file under `/blog/` does not vouch
     for it;
 12. a percent-encoded (Hebrew) address is found in the cache, and is not re-sent after it was accepted;
 13. a sitemap without its namespace is read; one in an unknown encoding does not throw out of the pass, and
     does not count as «every page went»;
 14. a key file that answers a redirect (another server's 301/308) is not the key: nothing is sent;
 15. a page whose file went missing is sent once, not again on every look;
 16. a site without sitemap.xml is announced from where it keeps its sitemap: Astro's sitemap-index.xml, or the
     sitemaps its robots.txt names on its own domain (ahead of a stale sitemap.xml; another host's is not read).
 Cases 3, 6 (robots), 9, 11, 13, 14, 15 and 16 were each checked against a mutant of indexnow.py (the
 unchanged-skip removed, robots ignored, the key check skipped, the bare prefix let through, an unreadable sitemap
 read as «all gone», a redirect taken for the key, a missing file re-sent, only sitemap.xml looked for): each fails.

    python3 apps/sites/test_indexnow.py
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["SITES_STATE_DIR"] = tempfile.mkdtemp()      # never the app's own state, even inside its image
os.environ["SITES_PUBLIC_DIR"] = tempfile.mkdtemp()
os.environ["SITES_INDEXNOW_URL"] = "https://indexnow.test/indexnow"
# the timings and the switch are the test's own, whatever the image or the shell says
os.environ.update({"SITES_INDEXNOW": "1", "SITES_INDEXNOW_MIN_SECONDS": "600", "SITES_INDEXNOW_RETRY_SECONDS": "3600"})
if "requests" not in sys.modules:
    try:
        import requests  # noqa: F401
    except ImportError:                 # a host without `requests` can run this: nothing here makes a request
        sys.modules["requests"] = types.ModuleType("requests")

import indexnow  # noqa: E402
import public  # noqa: E402

DOMAIN = "digital-office.co.il"
SITE = {"id": "do", "public": {"mode": "office", "entries": [{"domain": DOMAIN, "path": "/"},
                                                             {"domain": f"www.{DOMAIN}", "path": "/",
                                                              "redirect": True}]}}
BLOG = {"id": "blog", "public": {"mode": "office", "entries": [{"domain": "ex.co.il", "path": "/blog"}]}}
TWO = {"id": "two", "public": {"mode": "office", "entries": [{"domain": "a.co.il", "path": "/"},
                                                              {"domain": "b.co.il", "path": "/"}]}}
SM = "http://www.sitemaps.org/schemas/sitemap/0.9"


class Engine:
    """The stand-in for the world: api.indexnow.org records each POST and answers `code` (or `codes[host]`, or
    raises), and a GET of a key file is answered by the office's own `public.serve` — unless the host is one the
    world does not reach here (`away`)."""

    def __init__(self, sites):
        self.posts, self.gets, self.code, self.codes, self.fail, self.away = [], [], 200, {}, False, set()
        self.moved, self.agents, self.sites = set(), set(), sites

    def post(self, url, json=None, timeout=None, headers=None):      # noqa: A002 — requests' own name
        if self.fail:
            raise OSError("no route")
        self.agents.add((headers or {}).get("User-Agent", ""))
        self.posts.append({"url": url, **json})
        return types.SimpleNamespace(status_code=self.codes.get(json["host"], self.code))

    def get(self, url, timeout=None, allow_redirects=True, headers=None):
        self.gets.append(url)
        self.agents.add((headers or {}).get("User-Agent", ""))
        u = urlsplit(url)
        if u.hostname in self.away:
            raise OSError("this host is served elsewhere")
        if u.hostname in self.moved:                       # another server, answering a redirect
            return types.SimpleNamespace(status_code=308, text="")
        for site in self.sites:
            for e in public.entries_of(site):
                prefix = e["path"].rstrip("/")
                if e["domain"] == u.hostname and u.path.startswith(prefix + "/"):
                    out = public.serve(site, u.path[len(prefix):], host=u.hostname, count=False, scheme="https")
                    return types.SimpleNamespace(status_code=out["status"], text=out["body"].decode("utf-8", "replace"))
        return types.SimpleNamespace(status_code=404, text="")

    def urls(self):
        return sorted(u for p in self.posts for u in p["urlList"])


def sitemap(locs):
    rows = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{SM}">{rows}</urlset>'.encode()


def lay_out(site, files, synced_at):
    """A synced copy of `site` in the cache, as `public.sync` leaves it."""
    root = public.cache_dir(site["id"])
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    public._write_meta(site["id"], {"ok": True, "at": synced_at})


def check(module=indexnow, serve=public.serve):
    """Cases 1–7 against `module`. Returns one line per claim that does not hold."""
    bad = []
    engine = Engine([SITE, BLOG, TWO])
    module.requests = engine
    public._state["https"] = True
    pages = [f"https://{DOMAIN}/", f"https://{DOMAIN}/about.html", f"https://{DOMAIN}/apps/n8n.html"]
    lay_out(SITE, {"index.html": b"home", "about.html": b"about", "apps/n8n.html": b"n8n", "robots.txt": b"x",
                   "sitemap.xml": sitemap(pages + [f"https://other.co.il/x", f"http://{DOMAIN}/plain.html"])}, 100)

    if module.key_of(SITE["id"]):                                                       # case 1, before
        bad.append("1: a site that never announced itself must have no key")
    res = module.submit(SITE, now=1000.0)                                               # case 2
    key = module.key_of(SITE["id"])
    if engine.urls() != sorted(pages):
        bad.append(f"2: the first pass must send exactly the site's https sitemap addresses, sent {engine.urls()}")
    elif len(engine.posts) != 1 or engine.posts[0].get("host") != DOMAIN or engine.posts[0].get("key") != key \
            or engine.posts[0].get("keyLocation") != f"https://{DOMAIN}/{key}.txt" \
            or engine.posts[0].get("url") != os.environ["SITES_INDEXNOW_URL"]:
        bad.append(f"2: one POST to the endpoint with host, key and keyLocation, got {engine.posts}")
    if not res.get("ok") or res.get("sent") != 3:
        bad.append(f"2: the answer must say 3 sent, got {res}")
    out = serve(SITE, f"{key}.txt", host=DOMAIN, count=False, scheme="https") if key else {"status": 0}
    if out.get("status") != 200 or out.get("body") != key.encode() \
            or not out.get("headers", {}).get("Content-Type", "").startswith("text/plain"):
        bad.append(f"1: the key file must answer the key as text/plain, got {out.get('status')}")
    other = serve(SITE, "0123456789abcdef0123456789abcdef.txt", host=DOMAIN, count=False, scheme="https")
    if other.get("status") == 200:
        bad.append("1: a .txt shaped like a key but not the key must not answer 200")
    if serve(SITE, "robots.txt", host=DOMAIN, count=False, scheme="https").get("body") != b"x":
        bad.append("1: the site's own files are served as before")

    engine.posts.clear()                                                                # case 3
    real, reads = module.fingerprints, []
    module.fingerprints = lambda site: reads.append(site["id"]) or real(site)
    res = module.submit(SITE, now=1000.0 + module.MIN_SECONDS + 1)
    module.fingerprints = real
    if engine.posts or res.get("sent"):
        bad.append(f"3: nothing changed, nothing sent — sent {engine.urls()}")
    elif reads:
        bad.append("3: a cache not synced again since the last look is not read at all")

    root = public.cache_dir(SITE["id"])                                                 # case 4
    (root / "about.html").write_bytes(b"about, rewritten")
    (root / "apps" / "new.html").write_bytes(b"new")
    (root / "sitemap.xml").write_bytes(sitemap([pages[0], pages[1], f"https://{DOMAIN}/apps/new.html"]))
    public._write_meta(SITE["id"], {"ok": True, "at": 200})
    module.submit(SITE, now=1000.0 + module.MIN_SECONDS - 5)
    if engine.posts:
        bad.append("4: a second submission within MIN_SECONDS must wait")
    module.submit(SITE, now=1000.0 + module.MIN_SECONDS + 5)
    want = sorted([pages[1], pages[2], f"https://{DOMAIN}/apps/new.html"])
    if engine.urls() != want:
        bad.append(f"4: the changed, the gone and the new page — and only they; sent {engine.urls()}")

    engine.posts.clear()                                                                # case 5
    (root / "index.html").write_bytes(b"home, rewritten")
    public._write_meta(SITE["id"], {"ok": True, "at": 300})
    engine.code = 403
    t = 5000.0
    res = module.submit(SITE, now=t)
    if res.get("ok") or engine.urls() != [pages[0]]:
        bad.append(f"5: a refusal is not ok, got {res} sending {engine.urls()}")
    engine.posts.clear()
    engine.code = 200
    module.submit(SITE, now=t + 60)
    if engine.posts:
        bad.append("5: the try after a refusal waits RETRY_SECONDS")
    module.submit(SITE, now=t + module.RETRY_SECONDS + 1)
    if engine.urls() != [pages[0]]:
        bad.append(f"5: the refused address is sent again on the next try, sent {engine.urls()}")
    engine.posts.clear()
    engine.fail = True
    (root / "index.html").write_bytes(b"home, third")
    public._write_meta(SITE["id"], {"ok": True, "at": 400})
    res = module.submit(SITE, now=t + 2 * module.RETRY_SECONDS)
    engine.fail = False
    if res.get("ok") or module.state(SITE["id"]).get("sent", {}).get(pages[0]) == module.fingerprints(SITE)[pages[0]]:
        bad.append("5: an engine that does not answer leaves the address unsent")

    engine.posts.clear()                                                                # case 6
    public._state["https"] = False
    (root / "index.html").write_bytes(b"home, fourth")
    public._write_meta(SITE["id"], {"ok": True, "at": 500})
    module.submit(SITE, force=True, now=t + 10 * module.RETRY_SECONDS)
    if engine.posts:
        bad.append("6: a laptop office (no https on its edge) never announces")
    public._state["https"] = True
    module.submit({**SITE, "public": {**SITE["public"], "indexnow": False}}, force=True, now=t + 11 * 3600)
    if engine.posts:
        bad.append("6: `public.indexnow: false` turns it off for the site")
    module.submit({**SITE, "public": {**SITE["public"], "mode": "container"}}, force=True, now=t + 12 * 3600)
    if engine.posts:
        bad.append("6: a site the office does not serve is never announced")
    saved, module.ENABLED = module.ENABLED, False
    module.submit(SITE, force=True, now=t + 13 * 3600)
    module.ENABLED = saved
    if engine.posts:
        bad.append("6: SITES_INDEXNOW=0 turns it off for the office")

    engine.posts.clear()                                                                # case 7 + prefix
    lay_out(BLOG, {"index.html": b"blog", "a/index.html": b"a",
                   "sitemap.xml": (f'<?xml version="1.0"?><sitemapindex xmlns="{SM}"><sitemap>'
                                   f'<loc>https://ex.co.il/blog/pages.xml</loc></sitemap></sitemapindex>').encode(),
                   "pages.xml": sitemap(["https://ex.co.il/blog/", "https://ex.co.il/blog/a/",
                                         "https://ex.co.il/shop/"])}, 100)
    module.submit(BLOG, now=t + 20 * 3600)
    bkey = module.key_of(BLOG["id"])
    if engine.urls() != ["https://ex.co.il/blog/", "https://ex.co.il/blog/a/"]:
        bad.append(f"7: a sitemap index is followed, and only the entry's own path is sent, sent {engine.urls()}")
    elif engine.posts[0].get("keyLocation") != f"https://ex.co.il/blog/{bkey}.txt":
        bad.append(f"2: the keyLocation sits under the entry's path, got {engine.posts[0].get('keyLocation')}")
    if serve(BLOG, f"{bkey}.txt", host="ex.co.il", count=False, scheme="https").get("body") != bkey.encode():
        bad.append("1: the key file answers under the entry's path too")
    st = module.status(BLOG)
    if not st.get("enabled") or st.get("key_files") != [f"https://ex.co.il/blog/{bkey}.txt"] or st.get("waiting"):
        bad.append(f"status: on, its key file, nothing waiting — got {st}")

    # 9: the world does not reach this office for the host (a copy, a clone, DNS not moved): nothing is POSTed
    engine.posts.clear()
    engine.away = {"a.co.il", "b.co.il"}
    lay_out(TWO, {"index.html": b"two", "x.html": b"x",
                  "sitemap.xml": sitemap(["https://a.co.il/", "https://b.co.il/x.html"])}, 100)
    res = module.submit(TWO, now=t + 30 * 3600)
    if engine.posts or res.get("sent"):
        bad.append(f"9: a key file the world does not reach here means nothing is sent, sent {engine.urls()}")
    elif not any(g.startswith("https://a.co.il/") and g.endswith(".txt") for g in engine.gets):
        bad.append("9: the key file is asked for at its public address before anything is sent")
    engine.away = set()

    # 10: one host refused, the other accepted — the accepted one is not sent again
    engine.posts.clear()
    engine.codes = {"b.co.il": 422}
    module.submit(TWO, now=t + 32 * 3600)
    engine.codes = {}
    engine.posts.clear()
    module.submit(TWO, now=t + 34 * 3600)
    if engine.urls() != ["https://b.co.il/x.html"]:
        bad.append(f"10: after a refusal of one host only its addresses go again, sent {engine.urls()}")

    # 11: an address equal to an entry's prefix (`/blog`, no slash) is not vouched for by `/blog/<key>.txt`
    engine.posts.clear()
    (public.cache_dir(BLOG["id"]) / "pages.xml").write_bytes(sitemap(["https://ex.co.il/blog", "https://ex.co.il/blog/a/"]))
    module.submit(BLOG, force=True, now=t + 40 * 3600)
    if "https://ex.co.il/blog" in engine.urls():
        bad.append("11: `https://ex.co.il/blog` is outside `/blog/`, where the key file sits — never sent")

    # 12: a page whose address is percent-encoded (Hebrew) is found in the cache, and not sent again for nothing
    engine.posts.clear()
    root = public.cache_dir(SITE["id"])
    (root / "דף").mkdir(exist_ok=True)
    (root / "דף" / "index.html").write_bytes(b"page")
    heb = f"https://{DOMAIN}/%D7%93%D7%A3/"
    (root / "sitemap.xml").write_bytes(sitemap([pages[0], heb]))
    public._write_meta(SITE["id"], {"ok": True, "at": 600})
    if not module.fingerprints(SITE).get(heb):
        bad.append("12: a percent-encoded address resolves to its file, as `serve` resolves it")
    module.submit(SITE, force=True, now=t + 50 * 3600)
    if module.status(SITE).get("waiting"):
        bad.append("12: after it was accepted, nothing waits — a missing-file fingerprint would re-send it forever")

    # 13: a sitemap without its namespace is still read; one in an encoding Python does not know does not throw
    (root / "sitemap.xml").write_bytes(b'<?xml version="1.0"?><urlset><url><loc>' + pages[1].encode() + b"</loc></url></urlset>")
    if pages[1] not in module.fingerprints(SITE):
        bad.append("13: a sitemap that forgot its namespace is read")
    (root / "sitemap.xml").write_bytes(b'<?xml version="1.0" encoding="x-no-such"?><urlset/>')
    try:
        module.fingerprints(SITE)
    except Exception as e:                                                  # noqa: BLE001
        bad.append(f"13: an unreadable sitemap must not throw out of the pass ({type(e).__name__})")
    engine.posts.clear()
    public._write_meta(SITE["id"], {"ok": True, "at": 700})
    module.submit(SITE, now=t + 60 * 3600)
    if engine.posts:
        bad.append(f"13: an unreadable sitemap is not «every page went» — sent {engine.urls()}")

    # 6, robots: a site whose own robots.txt closes it to every crawler (a staging alias, a clone) is not announced
    shut = {"id": "shut", "public": {"mode": "office", "entries": [{"domain": "shut.example.co.il", "path": "/"}]}}
    lay_out(shut, {"index.html": b"x", "robots.txt": b"User-agent: *\nDisallow: /\n",
                   "sitemap.xml": sitemap(["https://shut.example.co.il/"])}, 100)
    engine.sites.append(shut)
    engine.posts.clear()
    module.submit(shut, force=True, now=t + 61 * 3600)
    if engine.posts:
        bad.append("6: a robots.txt with Disallow: / for * means the site is not announced")

    # 14: a key file answered by a redirect (another server's 301/308) is not the key
    moved = {"id": "moved", "public": {"mode": "office", "entries": [{"domain": "moved.co.il", "path": "/"}]}}
    lay_out(moved, {"index.html": b"m", "sitemap.xml": sitemap(["https://moved.co.il/"])}, 100)
    engine.sites.append(moved)
    engine.moved = {"moved.co.il"}
    engine.posts.clear()
    module.submit(moved, now=t + 62 * 3600)
    engine.moved = set()
    if engine.posts:
        bad.append("14: a key file that answers a redirect is not the key — nothing is sent")

    # 15: a page whose file went missing is sent once, not on every look
    gone = {"id": "gone", "public": {"mode": "office", "entries": [{"domain": "gone.co.il", "path": "/"}]}}
    lay_out(gone, {"index.html": b"g", "sitemap.xml": sitemap(["https://gone.co.il/", "https://gone.co.il/lost.html"])}, 100)
    engine.sites.append(gone)
    engine.posts.clear()
    module.submit(gone, now=t + 63 * 3600)
    first = engine.urls()
    engine.posts.clear()
    public._write_meta(gone["id"], {"ok": True, "at": 200})                  # an unrelated sync
    module.submit(gone, now=t + 64 * 3600)
    if "https://gone.co.il/lost.html" not in first:
        bad.append(f"15: a page in the sitemap whose file is missing is sent (once), sent {first}")
    elif engine.posts:
        bad.append(f"15: …and not again on the next look, sent {engine.urls()}")

    # 16: a site with no sitemap.xml is still announced — Astro's sitemap-index.xml (the docs, DGO-1788), and the
    # sitemaps its robots.txt names on its own domain (a WordPress copy's wp-sitemap.xml) ahead of a stale sitemap.xml
    docs = {"id": "docs", "public": {"mode": "office", "entries": [{"domain": "docs.ex.co.il", "path": "/"}]}}
    lay_out(docs, {"he/index.html": b"he", "en/index.html": b"en",
                   "sitemap-index.xml": (f'<?xml version="1.0"?><sitemapindex xmlns="{SM}"><sitemap>'
                                         f'<loc>https://docs.ex.co.il/sitemap-0.xml</loc></sitemap></sitemapindex>').encode(),
                   "sitemap-0.xml": sitemap(["https://docs.ex.co.il/he/", "https://docs.ex.co.il/en/"])}, 100)
    wp = {"id": "wp", "public": {"mode": "office", "entries": [{"domain": "wp.ex.co.il", "path": "/"}]}}
    lay_out(wp, {"index.html": b"w", "about/index.html": b"a", "stale.html": b"s",
                 "robots.txt": b"User-agent: *\nDisallow: /wp-admin/\nSitemap: https://wp.ex.co.il/wp-sitemap.xml\n"
                               b"Sitemap: https://elsewhere.co.il/sitemap.xml\n",
                 "wp-sitemap.xml": sitemap(["https://wp.ex.co.il/", "https://wp.ex.co.il/about/"]),
                 "sitemap.xml": sitemap(["https://wp.ex.co.il/stale.html"])}, 100)
    engine.sites += [docs, wp]
    for one, want in ((docs, ["https://docs.ex.co.il/en/", "https://docs.ex.co.il/he/"]),
                      (wp, ["https://wp.ex.co.il/", "https://wp.ex.co.il/about/"])):
        engine.posts.clear()
        module.submit(one, now=t + 65 * 3600)
        if engine.urls() != want:
            bad.append(f"16: {one['id']}: the sitemap is found where the site keeps it, sent {engine.urls()}, want {want}")

    if any(not a.startswith("BinaOfficeSites/") for a in engine.agents):
        bad.append(f"the office's own requests say so (User-Agent), got {sorted(engine.agents)}")
    return bad


def as_it_was():
    """The office before this change: no key file, and nothing ever sent."""
    was = types.ModuleType("indexnow_as_it_was")
    for name in ("MIN_SECONDS", "RETRY_SECONDS", "INDEXNOW_URL", "ENABLED", "state", "fingerprints"):
        setattr(was, name, getattr(indexnow, name))
    was.key_of = lambda sid: ""
    was.submit = lambda site, force=False, now=None: {"ok": True, "sent": 0}
    was.status = lambda site: {}

    def serve(site, path, **kw):
        saved = public.indexnow.key_file
        public.indexnow.key_file = lambda site, path: None
        try:
            return public.serve(site, path, **kw)
        finally:
            public.indexnow.key_file = saved
    return was, serve


def main():
    bad = check()
    if bad:
        print("FAIL\n  " + "\n  ".join(bad))
        return 1
    for sid in ("do", "blog", "two", "shut", "moved", "gone", "docs", "wp"):    # a clean slate for the code as it was
        indexnow._state_path(sid).unlink(missing_ok=True)
    was, serve = as_it_was()
    seen = check(was, serve)
    if not any(line.startswith("1:") for line in seen) or not any(line.startswith("2:") for line in seen):
        print("FAIL\n  8: with the announcement switched off, cases 1 and 2 must fail — the test would not see the "
              f"defect (got {json.dumps(seen, ensure_ascii=False)})")
        return 1
    print(f"ok — cases 1–7 and 9–16 hold; with the announcement switched off {len(seen)} claims fail, as they must")
    return 0


if __name__ == "__main__":
    sys.exit(main())
