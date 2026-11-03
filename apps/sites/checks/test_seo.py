"""Offline tests for sites.checks.seo: a fake site and a fake outside world, no network at all.

    cd apps/sites && python3 -m checks.test_seo        # or: python3 -m pytest checks/test_seo.py

Each test pins down a way the check was wrong, or could become unkind to somebody else's server:

  * the WHOLE sitemap is read — an index of two files, 41 pages, `max_pages=5` — not the first 20;
  * an external link answering 404 is ONE finding however many pages carry it, with page and fix;
  * a site that refuses robots (403) is an `info` under its own code, never "broken";
  * requests are bounded per host and per run, spaced per host, and a URL asked once is not asked
    again by the next run (and the URLs the limit left out go first in that run);
  * a host that does not answer, or says "slow down" (429), is not asked about its other URLs;
  * a link into the office's own network is never requested — not even through a redirect.
"""
from __future__ import annotations

import socket
from contextlib import ExitStack
from unittest import mock
from urllib.parse import urlparse

import requests

from . import http as H
from . import seo

HOST = "example.test"
BASE = f"https://{HOST}"

GONE = "https://gone.example.org/page"
FINE = "https://fine.example.org/"
MOVED = "https://moved.example.org/old"
MOVED_TO = "https://fine.example.org/new"
NOHEAD = "https://nohead.example.org/"
HICCUP = "https://hiccup.example.org/"
GUARDED = "https://guarded.example.org/"
DOWN = "https://down.example.org/"
DEAD = "https://dead.example.org/x"
FLAKY = [f"https://flaky.example.org/{c}" for c in "abc"]
RATE = [f"https://rate.example.org/{c}" for c in "ab"]
BUSY = [f"https://busy.example.org/{i}" for i in range(9)]
PRIVATE = ["http://169.254.169.254/latest", "http://sites:8979/api/sites", "http://localhost:8080/"]
REBIND = "https://rebind.example.org/"


def _html(n: int, links: list[str]) -> str:
    anchors = "".join(f'<a href="{h}">קישור</a>' for h in links)
    description = "תיאור מספיק ארוך לעמוד הבדיקה " * 3
    return ('<!doctype html><html lang="he"><head><meta charset="utf-8">'
            f'<title>עמוד מספר {n} באתר הבדיקה של הלשכה</title>'
            f'<meta name="description" content="{description}">'
            '<meta name="viewport" content="width=device-width">'
            f'<link rel="canonical" href="{BASE}/p{n}.html"></head>'
            f'<body><h1>עמוד {n}</h1><p>{"מילה " * 120}</p>{anchors}</body></html>')


def _locs(paths) -> str:
    return "".join(f"<url><loc>{BASE}{p}</loc></url>" for p in paths)


def _site() -> dict[str, str]:
    """Paths → bodies: a sitemap INDEX over two files (and one that points into the office), 40
    pages and the home page, with the external links the tests care about spread over them."""
    links = {1: [GONE, FINE, MOVED, NOHEAD, "mailto:person91@example.com", "#top", "javascript:void(0)", "/p2.html"],
             2: [GONE], 3: [GONE, HICCUP], 4: [GUARDED, DOWN], 5: [DEAD, *FLAKY, *RATE],
             6: [*BUSY, *PRIVATE, REBIND]}
    site = {f"/p{n}.html": _html(n, links.get(n, [])) for n in range(1, 41)}
    site["/"] = _html(0, [FINE])
    site["/sitemap.xml"] = (f"<sitemapindex><sitemap><loc>{BASE}/sm-1.xml</loc></sitemap>"
                            f"<sitemap><loc>{BASE}/sm-2.xml</loc></sitemap>"
                            "<sitemap><loc>http://sites:8979/evil.xml</loc></sitemap></sitemapindex>")
    site["/sm-1.xml"] = f"<urlset>{_locs(['/'] + [f'/p{n}.html' for n in range(1, 26)])}</urlset>"
    site["/sm-2.xml"] = f"<urlset>{_locs(f'/p{n}.html' for n in range(26, 41))}</urlset>"
    site["/robots.txt"] = f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n"
    return site


class _Resp:
    def __init__(self, status: int, headers: dict | None = None):
        self.status_code, self.headers = status, headers or {}

    def close(self) -> None:
        pass


class Web:
    """The fake outside world: a DNS, sessions that answer from a table, and a clock that only moves
    when something sleeps or asks. `log` is every request that actually "went out"."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.log: list[tuple[str, str, float]] = []
        self.answers: dict[str, list] = {
            GONE: [404], FINE: [200], MOVED: [(301, MOVED_TO)], MOVED_TO: [200], NOHEAD: [200],
            HICCUP: [503, 503, 200], GUARDED: [403], DOWN: [503], REBIND: [(302, "http://10.0.0.1/admin")],
            **{u: [requests.Timeout()] for u in FLAKY}, **{u: [429] for u in RATE},
            **{u: [200] for u in BUSY},
        }
        self.head_only: dict[str, list] = {NOHEAD: [405]}
        self.dns = {urlparse(u).hostname: "93.184.216.34" for u in self.answers}

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def getaddrinfo(self, host, port, *args, **kw):
        if host not in self.dns:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (self.dns[host], 0))]

    def session(self):
        web = self

        class Session:
            def head(self, url, **kw):
                return web._answer("HEAD", url, web.head_only)

            def get(self, url, **kw):
                return web._answer("GET", url, {})

        return Session()

    def _answer(self, method: str, url: str, overrides: dict):
        self.log.append((method, url, self.now))
        self.now += 0.1                                        # a request takes a moment
        seq = overrides.get(url) or self.answers[url]
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        status, location = item if isinstance(item, tuple) else (item, None)
        return _Resp(status, {"location": location} if location else {})

    def asked(self, url: str, method: str | None = None) -> int:
        return sum(1 for m, u, _ in self.log if u == url and (method is None or m == method))


def _fetcher(site: dict[str, str]):
    def fetch(url, timeout=20, follow=True, session_=None):
        text = site.get(urlparse(url).path)
        if text is None:
            return {"ok": True, "status": 404, "text": "", "headers": {}, "url": url, "ms": 1, "bytes": 0}
        return {"ok": True, "status": 200, "text": text, "headers": {}, "url": url, "ms": 1,
                "bytes": len(text)}
    return fetch


def _run(web: Web, crash_ok: bool = False, **kw) -> dict:
    with ExitStack() as stack:
        for target, name, value in ((H, "fetch", _fetcher(_site())), (H, "session", web.session),
                                    (seo, "_clock", web.clock), (seo, "_sleep", web.sleep),
                                    (socket, "getaddrinfo", web.getaddrinfo)):
            stack.enter_context(mock.patch.object(target, name, value))
        result = seo.run({"hosts": [HOST]}, **kw)
    # `run` survives a crash in the external step on purpose, so a test that does not EXPECT one must
    # look for it — otherwise a broken fake or a real bug passes as "no findings".
    assert crash_ok or not any(f["code"] == "external_failed" for f in result["findings"]), \
        result["summary"].get("external")
    return result


def _codes(result: dict, prefix: str) -> list[dict]:
    return [f for f in result["findings"] if f["code"].startswith(prefix)]


def _fresh() -> Web:
    seo._hosts.clear()
    return Web()


def test_the_whole_sitemap_is_read() -> None:
    result = _run(_fresh(), max_pages=5)
    sm = result["summary"]["sitemap"]
    assert result["summary"]["pages_crawled"] == 41, result["summary"]["pages_crawled"]
    assert sm["urls"] == 41 and sm["files"] == 3 and sm["crawled"] == 41, sm   # index + 2, not the evil one
    assert not _codes(result, "crawl_truncated")


def test_a_sitemap_over_the_ceiling_is_cut_and_says_so() -> None:
    urls = "".join(f"<url><loc>{BASE}/q{n}.html</loc></url>" for n in range(seo.SITEMAP_MAX_URLS + 20))
    got, files, capped = seo._read_sitemap(f"<urlset>{urls}</urlset>", (HOST,))
    assert len(got) == seo.SITEMAP_MAX_URLS and capped and files == 1


def test_a_broken_external_link_is_one_finding_with_page_and_fix() -> None:
    web = _fresh()
    result = _run(web)
    gone = [f for f in _codes(result, "broken_external") if f["detail"].startswith(GONE)]
    assert len(gone) == 1, gone
    f = gone[0]
    assert f["severity"] == "warn" and "404" in f["title"] and f["url"].endswith("/p1.html"), f
    assert "וגם ב-2 עמודים נוספים" in f["detail"] and f["fix"], f
    answered = {FINE, MOVED, NOHEAD, HICCUP}                 # fine, redirected, HEAD refused, hiccuped
    assert not [x for x in _codes(result, "broken_external") if x["detail"].split(" ")[0] in answered]
    assert web.asked(HICCUP) == 3                            # HEAD 503, GET 503, then a retry that worked
    assert web.asked(NOHEAD, "GET") == 1                     # HEAD said 405, the GET said 200


def test_a_503_that_stays_503_and_a_dead_domain_are_broken() -> None:
    result = _run(_fresh())
    broken = {f["detail"].split(" ")[0]: f for f in _codes(result, "broken_external")}
    assert DOWN in broken and "503" in broken[DOWN]["title"], list(broken)
    assert DEAD in broken and "הדומיין אינו קיים" in broken[DEAD]["title"], list(broken)


def test_a_robot_that_is_refused_is_not_a_broken_link() -> None:
    result = _run(_fresh())
    blocked = {f["detail"].split(" ")[0]: f for f in _codes(result, "external_blocked")}
    assert set(blocked) == {GUARDED, RATE[0]}, list(blocked)
    assert all(f["severity"] == "info" for f in blocked.values())
    assert "403" in blocked[GUARDED]["title"] and "429" in blocked[RATE[0]]["title"]
    assert not [f for f in _codes(result, "broken_external") if GUARDED in f["detail"] or RATE[0] in f["detail"]]


def test_requests_are_bounded_spaced_and_a_dead_host_is_left_alone() -> None:
    web = _fresh()
    result = _run(web)
    busy = [t for m, u, t in web.log if m == "HEAD" and u in BUSY]
    assert len(busy) == seo.EXTERNAL_PER_HOST, busy                          # 9 links, 5 asked
    assert all(b - a >= seo.EXTERNAL_HOST_GAP for a, b in zip(busy, busy[1:])), busy
    assert sum(web.asked(u) for u in FLAKY) == 1, "the host that timed out is asked once, not 3 times"
    assert web.asked(RATE[1]) == 0, "a host that said 'slow down' is not asked again in the run"
    ext = result["summary"]["external"]
    assert (ext["links"], ext["checked"], ext["skipped"], ext["private"]) == (26, 16, 4, 3), ext
    assert ext["unreachable"] == 5, ext                          # flaky x3, the second rate URL, the dead domain
    partial = _codes(result, "external_partial")
    assert partial and partial[0]["severity"] == "info" and "4" in partial[0]["title"], partial


def test_nothing_private_is_ever_requested() -> None:
    web = _fresh()
    _run(web)
    hosts = {urlparse(u).hostname for _, u, _ in web.log}
    assert not hosts & {"169.254.169.254", "sites", "localhost", "10.0.0.1"}, hosts
    assert web.asked(REBIND) == 1                            # it answered with a redirect; not followed
    for bad in ("127.0.0.1", "169.254.169.254", "10.1.2.3", "192.168.0.9", "::1", "localhost",
                "sites", "db.internal", "printer.local", ""):
        assert seo._blocked(bad) == "private", bad
    assert seo._blocked("8.8.8.8") is None and seo._blocked("2606:4700:4700::1111") is None


def test_the_second_run_asks_nobody_twice_and_the_left_out_go_first() -> None:
    web = _fresh()
    _run(web)
    before = len(web.log)
    left_out = {u for u in BUSY if web.asked(u) == 0}
    assert len(left_out) == 4
    web.now += 60                                            # a minute later, far inside the memory
    result = _run(web)
    again = [(m, u) for m, u, _ in web.log[before:]]
    assert sorted(u for m, u in again if m == "HEAD") == sorted(left_out), again
    assert all(web.asked(u, "HEAD") == 1 for u in BUSY), "all nine asked exactly once across two runs"
    assert web.asked(GONE, "HEAD") == 1, "a cached verdict is not asked again"
    ext = result["summary"]["external"]
    assert (ext["checked"], ext["cached"], ext["skipped"], ext["private"]) == (4, 16, 0, 3), ext
    assert [f for f in _codes(result, "broken_external") if GONE in f["detail"]], "a cached verdict still reports"
    web.now += seo.EXTERNAL_TTL + 1                          # the memory expires: asked again
    _run(web)
    assert web.asked(GONE, "HEAD") == 2


def test_a_shallow_scan_sends_no_external_requests() -> None:
    web = _fresh()
    result = _run(web, deep=False)
    assert not web.log and "external" not in result["summary"]


def test_a_crash_in_the_external_step_does_not_lose_the_report() -> None:
    with mock.patch.object(seo, "_check_external", side_effect=RuntimeError("boom")), \
            mock.patch.object(seo, "log") as log:
        result = _run(_fresh(), crash_ok=True)
    assert result["summary"]["pages_crawled"] == 41 and result["summary"]["external"] == {"error": "RuntimeError"}
    failed = _codes(result, "external_failed")
    assert len(failed) == 1 and failed[0]["severity"] == "info" and "RuntimeError" not in failed[0]["detail"]
    assert log.exception.called


def test_a_redirect_loop_ends_instead_of_hanging() -> None:
    web = _fresh()
    web.answers["https://loop.example.org/"] = [(302, "https://loop.example.org/")]
    web.dns["loop.example.org"] = "93.184.216.34"
    with mock.patch.object(socket, "getaddrinfo", web.getaddrinfo):
        assert seo._probe("https://loop.example.org/", web.session()) == (None, "hops")
    assert web.asked("https://loop.example.org/") == seo.EXTERNAL_MAX_HOPS + 1


def test_findings_are_capped_and_broken_come_before_blocked() -> None:
    urls = {f"https://h{n}.example.org/": [f"{BASE}/p{n}.html"] for n in range(30)}
    verdicts = {u: (404 if n < 25 else 403, "") for n, u in enumerate(urls)}
    kinds = [f["code"].split(":")[0] for f in seo._external_findings(verdicts, urls)]
    assert kinds.count("broken_external") == 20 and kinds.count("external_blocked") == 5, kinds
    assert kinds[0] == "broken_external" and kinds[-1] == "external_blocked", kinds


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"seo: {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
