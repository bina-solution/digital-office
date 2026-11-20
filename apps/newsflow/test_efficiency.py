#!/usr/bin/env python3
"""test_efficiency — what DGO-2030 changed in newsflow, pinned (standard library only; G72 runs it).

    python3 apps/newsflow/test_efficiency.py

1. The feed's answers are the same as before: a row's headline verdict is now decided once per (title, url), and the
   screen's two reads are kept until the store changes — the items served must not change by a single field.
2. A kept answer is never older than the store: a write through another connection makes the next ask recompute.
3. A pass stops when DRY_STOP sources that gave an article lately read nothing in a row (the office browser is not
   reading pages) and the sources it never reached are «skipped» with their place in the rotation kept. A source
   that gave nothing lately does not count; a healthy pass and a mixed one never stop; DRY_STOP=0 never stops; and a
   run of sites that died together cuts ONE pass short — the next pass moves past them (the second reader's case:
   restoring their stamps held the rotation on them for good).
4. A client that hung up is not answered with a 500 (that raised into the dead socket and logged a double
   traceback); any other failure still is.
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="newsflow-efficiency-")
os.environ["NEWSFLOW_DB"] = os.path.join(TMP, "newsflow.db")
os.environ["NEWSFLOW_TASKS"] = os.path.join(TMP, "tasks.json")
os.environ["NEWSFLOW_SEEN"] = os.path.join(TMP, "source-seen.json")
spec = importlib.util.spec_from_file_location("newsflow_main_efficiency", os.path.join(HERE, "main.py"))
nf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nf)
nf.init()

#: rows as the store holds them: real headlines, furniture, a card's clock glued to the sentence
ROWS = [
    ("https://www.calcalist.co.il/local_news/b", "חסימות ענק בנתיבי איילון בסוף השבוע: הכביש ייסגר בשני הכיוונים", "calcalist", "israel"),
    ("https://www.mako.co.il/news-y", "לפני 54 דקות גנב קונסולת פלייסטיישן ואוזניות: תושב קרית עקרון בן 46 נאשם", "mako", "israel"),
    ("https://www.techinasia.com/jobs/5a3f2364-d05a", "Product Owner Daya Wira Performa IDR 6M – 11M", "techinasia", "israel"),
    ("https://www.timesofisrael.com/", "Support Tol and remove all ads", "timesofisrael", "israel"),
    ("https://techcrunch.com/2026/11/19/x", "FEATURED PREMIUM Is it a neocloud? A hyperscaler? Sea's AI move puzzles investors", "techcrunch", "tech"),
    ("https://example.com/grant", "The Innovation Authority opens a new grant track for AI startups", "innovation-israel", "initiatives"),
    ("https://example.com/ai/1", "A new open model beats the last one on every public benchmark", "huggingface", "models"),
    ("https://example.com/ai/2", "Contact us", "huggingface", "models"),
]


def old_news(category="", limit=60, source=""):
    """The served list as the code before DGO-2030 computed it (is_headline + clean_title on every row)."""
    q = "select url,title,source,category,image,found_at from articles"
    args, where = [], []
    if source:
        where.append("source=?")
        args.append(source)
    if category == "opportunities":
        where.append("(" + " or ".join("title like ?" for _ in nf.OPPORTUNITY_CUES) + ")")
        args.extend(["%" + c + "%" for c in nf.OPPORTUNITY_CUES])
    elif category:
        where.append("category=?")
        args.append(category)
    if where:
        q += " where " + " and ".join(where)
    q += " order by found_at desc, id desc limit ?"
    args.append(max(1, min(1000, max(limit, 1) * 8)))
    with nf.db() as c:
        rows = []
        for r in c.execute(q, args):
            if not nf.is_headline(r["title"], r["url"]):
                continue
            r = dict(r)
            r["title"] = nf.clean_title(r["title"])
            rows.append(r)
        if not category and not source:
            rows = nf.order_front(rows)
        rows = rows[:max(1, min(500, limit))]
    for r in rows:
        r["category_he"] = nf.CAT_NAME.get(r["category"], r["category"])
    return {"items": rows, "count": len(rows), "category": category, "source": source}


def add(url, title, source, category, at="2026-11-19T10:00:00Z"):
    c = sqlite3.connect(nf.DB)                             # another connection, as a pass's own is
    c.execute("insert or ignore into articles(url_key,url,title,source,category,found_at,first_seen_at) values (?,?,?,?,?,?,?)",
              (nf.url_key(url), url, title, source, category, at, at))
    c.commit()
    c.close()


class Answers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for i, (url, title, source, cat) in enumerate(ROWS):
            add(url, title, source, cat, at="2026-11-19T10:%02d:00Z" % i)

    def test_the_feed_is_the_same(self):
        for cat in ("", "israel", "tech", "models", "opportunities"):
            self.assertEqual(nf.news(cat, 60), old_news(cat, 60), cat)
            self.assertEqual(json.loads(nf.answer_news(cat, 60, "")), old_news(cat, 60), cat)
        self.assertEqual(nf.news("", 60, "huggingface"), old_news("", 60, "huggingface"))

    def test_a_kept_answer_is_never_older_than_the_store(self):
        calls = []
        real = nf.news
        nf.news = lambda *a: calls.append(a) or real(*a)
        try:
            first = json.loads(nf.answer_news("models", 60, ""))
            again = json.loads(nf.answer_news("models", 60, ""))
            self.assertEqual(first, again)
            self.assertEqual(len(calls), 1, "the second ask of an unchanged store is answered from memory")
            add("https://example.com/ai/3", "Local models now run a full office on one small machine", "ollama-blog", "models",
                at="2026-11-19T11:00:00Z")
            after = json.loads(nf.answer_news("models", 60, ""))
            self.assertEqual(len(calls), 2, "a write through another connection makes the next ask recompute")
            self.assertEqual(after["items"][0]["url"], "https://example.com/ai/3")
        finally:
            nf.news = real

    def test_categories_total_is_every_article(self):
        d = json.loads(nf.answer_categories())
        with nf.db() as c:
            self.assertEqual(d["total"], c.execute("select count(*) from articles").fetchone()[0])
        self.assertEqual([x["id"] for x in d["categories"]], [i for i, _ in nf.CATEGORIES])


class Pass(unittest.TestCase):
    """collect() against a fake office browser: `reads(slug)` decides whether that source's page gives links."""

    def run_pass(self, sources, reads, gave=(), seen=None, days_ago=1, fresh=True):
        """One pass. `gave`: sources with an article `days_ago` days old; `fresh=False` keeps the rotation clock of the
        pass before (a second pass)."""
        if fresh:
            with open(nf.SEEN, "w") as fh:
                json.dump(seen or {}, fh)
        with open(nf.TASKS, "w") as fh:
            json.dump([], fh)
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days_ago * 86400))
        for slug in gave:
            add(f"https://gave.example/{slug}", f"An earlier headline that this source gave once ({slug})", slug, "tech",
                at=at)
        current = {}

        def b42(verb, task="", *rest, timeout=0):
            if verb == "start":
                current[task] = task.split("-", 1)[1].removesuffix("-r")
                return {"ok": True}
            if verb == "inspect":
                slug = current.get(task, "")
                if not reads(slug):
                    return {"controls": []}
                return {"controls": [{"role": "link", "handle": "h1", "href": f"https://news.example/{slug}/story",
                                      "name": f"Markets move as the central bank holds its rate for {slug}"}]}
            if verb == "js":
                return {"result": "{}"}
            return {"ok": True}

        real = (nf.b42, nf.SOURCES, nf.publish)
        nf.b42, nf.SOURCES = b42, [(s, f"https://{s}.example/", "tech") for s in sources]
        nf.publish = lambda events: ""                     # never the office's real stream
        try:
            out = nf.collect(None)
        finally:
            nf.b42, nf.SOURCES, nf.publish = real
        with open(nf.SEEN) as fh:
            return out, json.load(fh)

    @staticmethod
    def kinds(out):
        tried = [s for s, v in out["report"].items() if v.startswith("no links read")]
        skipped = [s for s, v in out["report"].items() if v.startswith("skipped: the pass stopped")]
        return tried, skipped

    def test_a_browser_that_reads_nothing_stops_the_pass(self):
        srcs = [f"dead{i}" for i in range(12)]
        before = {s: 1000.0 + i for i, s in enumerate(srcs)}
        out, seen = self.run_pass(srcs, reads=lambda s: False, gave=srcs, seen=before)
        tried, skipped = self.kinds(out)
        self.assertEqual(tried, srcs[:nf.DRY_STOP])
        self.assertEqual(skipped, srcs[nf.DRY_STOP:])
        self.assertIn("read nothing from %d sources in a row" % nf.DRY_STOP, out["stopped"])
        for s in skipped:
            self.assertEqual(seen.get(s), before[s], f"{s} was not reached and keeps its place in the rotation")
        for s in tried:
            self.assertGreater(seen.get(s), before[s], f"{s} had its turn")

    def test_a_source_that_gave_nothing_lately_is_no_evidence(self):
        srcs = [f"mix{i}" for i in range(2 * nf.DRY_STOP)]
        out, _ = self.run_pass(srcs, reads=lambda s: False, gave=srcs[::2])          # every other gave lately
        tried, _ = self.kinds(out)
        self.assertEqual(tried, srcs[:2 * nf.DRY_STOP - 1])
        srcs = [f"old{i}" for i in range(nf.DRY_STOP + 2)]
        add("https://anchor.example/today", "A headline from today that sets the store's newest article", "anchor",
            "tech", at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        out, _ = self.run_pass(srcs, reads=lambda s: False, gave=srcs, days_ago=nf.DRY_DAYS + 3)   # gave, long ago
        self.assertEqual(out["stopped"], "")
        self.assertEqual(self.kinds(out)[0], srcs)

    def test_a_long_outage_keeps_the_stop(self):
        # no article at all for longer than DRY_DAYS: «lately» counts back from the store's newest article, so the
        # window freezes instead of emptying (the second reader's case: counted back from now, the stop turned off)
        real = nf.DB
        nf.DB = os.path.join(TMP, "outage.db")
        try:
            nf.init()
            srcs = [f"out{i}" for i in range(nf.DRY_STOP + 3)]
            out, _ = self.run_pass(srcs, reads=lambda s: False, gave=srcs, days_ago=nf.DRY_DAYS + 5)
        finally:
            nf.DB = real
        self.assertTrue(out["stopped"])
        self.assertEqual(self.kinds(out)[0], srcs[:nf.DRY_STOP])

    def test_a_half_dead_browser_keeps_the_stop(self):
        # the last healthy pass was 10 days ago; one source still trickles an article through (an hour ago). Counted
        # back from the newest article, «lately» would hold that one source and the stop could never fire.
        real = nf.DB
        nf.DB = os.path.join(TMP, "partial.db")
        try:
            nf.init()
            ago = lambda days: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
            c = sqlite3.connect(nf.DB)
            c.execute("insert into runs(started_at, ended_at, added, sources_ok, report) values (?,?,?,?,?)",
                      (ago(10), ago(10), 40, 20, "{}"))
            c.commit()
            c.close()
            add("https://trickle.example/1", "One source still reads through a half-dead browser today", "trickle",
                "tech", at=ago(1 / 24))
            srcs = [f"half{i}" for i in range(nf.DRY_STOP + 3)]
            out, _ = self.run_pass(srcs, reads=lambda s: False, gave=srcs, days_ago=12)
        finally:
            nf.DB = real
        self.assertTrue(out["stopped"])
        self.assertEqual(self.kinds(out)[0], srcs[:nf.DRY_STOP])

    def test_sites_that_died_together_cut_one_pass_short_never_the_rotation(self):
        # the browser is fine; eight sites that gave lately died together (a redesign, a bot wall)
        srcs = [f"live{i}" for i in range(4)] + [f"gone{i}" for i in range(8)] + [f"later{i}" for i in range(8)]
        reads = lambda s: not s.startswith("gone")
        out1, _ = self.run_pass(srcs, reads=reads, gave=srcs)
        self.assertTrue(out1["stopped"])
        self.assertEqual(self.kinds(out1)[1], srcs[12:])
        out2, _ = self.run_pass(srcs, reads=reads, fresh=False)
        self.assertEqual(out2["sources_ok"], 12, "the next pass reads the ones the first never reached")
        self.assertFalse([s for s in srcs[12:] if s in out2["report"]], "every one the first pass skipped was read")

    def test_dry_stop_zero_never_stops(self):
        srcs = [f"zero{i}" for i in range(nf.DRY_STOP + 3)]
        real, nf.DRY_STOP = nf.DRY_STOP, 0
        try:
            out, _ = self.run_pass(srcs, reads=lambda s: False, gave=srcs)
        finally:
            nf.DRY_STOP = real
        self.assertEqual(out["stopped"], "")
        self.assertEqual(self.kinds(out)[0], srcs)

    def test_a_healthy_pass_and_a_mixed_one_never_stop(self):
        srcs = [f"ok{i}" for i in range(12)]
        out, _ = self.run_pass(srcs, reads=lambda s: True, gave=srcs)
        self.assertEqual(out["stopped"], "")
        self.assertEqual(out["sources_ok"], 12)
        srcs = [f"alt{i}" for i in range(20)]
        out, _ = self.run_pass(srcs, reads=lambda s: int(s[3:]) % 4 == 0, gave=srcs)   # 3 in a row read nothing
        self.assertEqual(out["stopped"], "")
        self.assertFalse(any(v.startswith("skipped") for v in out["report"].values()))


class HangUp(unittest.TestCase):
    def ask(self, raise_):
        sent, errors = [], []
        h = nf.Handler.__new__(nf.Handler)
        h.path = "/api/news?limit=60"
        h._send = lambda code, payload, *a: sent.append(code)
        real = nf.answer_news

        def boom(*a):
            raise raise_
        nf.answer_news = boom
        try:
            h.do_GET()
        except Exception as e:                             # what would reach socketserver's handle_error
            errors.append(e)
        finally:
            nf.answer_news = real
        return sent, errors

    def test_a_client_that_hung_up_gets_no_500(self):
        for e in (BrokenPipeError(32, "Broken pipe"), ConnectionResetError(104, "reset")):
            self.assertEqual(self.ask(e), ([], []))

    def test_any_other_failure_is_still_a_500(self):
        self.assertEqual(self.ask(ValueError("x")), ([500], []))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
