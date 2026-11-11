"""the quarterly check (DGO-817): content/recheck.py runs the same fixed list on every written piece — over its body
and the public lines of its front matter: its links still answer, FACTS.md is not newer than it, it is due 91 days
after its own date (flagged in the run before that day), its sources were opened within a quarter, every price
carries its year, and every «משרד» is read by a person. --write keeps the reading by hand. Runs on a scratch library
and a local HTTP server that answers each case.

    python3 apps/digital-assets/tests/test_recheck.py
"""
import datetime as dt
import os
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"   # a sandbox's proxy never sees the test
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "content"))
import recheck  # noqa: E402

FAIL: list = []
D = dt.date.fromisoformat


def check(cond, what):
    if not cond:
        FAIL.append(what)


class Site(BaseHTTPRequestHandler):
    ROUTES = {"/ok": (200, None), "/gone": (404, None), "/blocked": (403, None), "/Foo_(bar)": (200, None),
              "/move": (301, "/ok2"), "/ok2": (200, None), "/soft": (302, "/404"), "/404": (200, None),
              "/loop": (302, "/loop"), "/dead-end": (302, "/gone"), "/עברית": (200, None)}

    def _answer(self, body: bool):
        path = urllib.parse.unquote(self.path)
        code, to = self.ROUTES.get(path, (404, None))
        if path == "/no-head":                         # gov.il: HEAD → 404, GET → 200
            code = 200 if body else 404
        if path == "/head-to-404":                     # the Bank of Israel: HEAD → 302 /404, GET → 200
            code, to = (200, None) if body else (302, "/404")
        self.send_response(code)
        if to:
            self.send_header("Location", to)
        self.send_header("Content-Length", "2")
        self.end_headers()
        if body:
            self.wfile.write(b"ok")

    def do_HEAD(self):
        self._answer(False)

    def do_GET(self):
        self._answer(True)

    def log_message(self, *a):
        pass


def library(base: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="recheck-"))
    for t in ("article", "project", "news", "tutorial"):
        (root / t).mkdir()
    (root / "FACTS.md").write_text("# facts\n", encoding="utf-8")
    (root / "article" / "old.he.md").write_text(f"""﻿---
type: article
slug: old
title: "ישן"
meta_description: "המנוי עולה 49 ₪ לחודש, וכך זה במשרד"
published: 2026-06-01
updated: 2026-07-01 10:00:00
faq:
  - q: "כמה זה עולה?"
    a: "8.79$ לחודש, בלי שנה"
sources:
  - {{ title: "a", url: "{base}/ok", accessed: 2026-06-01 }}
  - {{ title: "b", url: "{base}/gone", accessed: 2026-10-30 }}
  - {{ title: "c", url: "{base}/ok2" }}
  - {{ title: "typo", url: "http//example.invalid/x" }}
---
# ישן

ראו [כאן]({base}/ok), [וכאן]({base}/move), [חסום]({base}/blocked), [מסמך ממשלתי]({base}/no-head), \
[שער הדולר]({base}/head-to-404 "כותרת"), [ויקי]({base}/Foo_(bar)), <{base}/עברית>, [לולאה]({base}/loop), \
[מוביל לשום מקום]({base}/dead-end), [דף ששמו 404]({base}/404) ו[דף שנעלם]({base}/soft).

המנוי עולה 49 ₪ לחודש, בלי שנה בפסקה.

המחירים נכון לאוקטובר 2026:

| תוכנית | מחיר |
|---|---|
| קטנה | 20 אירו |

```
echo $1
```

אחרי ההתקנה יש לכם משרד שלם.
""", encoding="utf-8")
    (root / "project" / "new.he.md").write_text(f"""---
type: project
slug: new
title: "חדש"
published: 2026-11-01
updated: 2026-11-01
project: {{ name: new, website: "{base}/ok", repo: "{base}/gone" }}
sources:
  - {{ title: "c", url: "{base}/ok", accessed: 2026-11-01 }}
---
# חדש

המנוי עולה 49 ₪ לחודש, נכון לנובמבר 2026, ורץ בלשכה. 2000 מילים עולות 100 ₪.
""", encoding="utf-8")
    (root / "news" / "unclosed.he.md").write_text("---\ntype: news\ntitle: x\n\nno closing line, 5 ₪\n",
                                                  encoding="utf-8")
    (root / "tutorial" / "bare.he.md").write_text(f"# בלי front matter\n\n[קישור]({base}/gone)\n", encoding="utf-8")
    return root


def checks() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    root = library(base)
    rows = {r["path"]: r for r in recheck.recheck(root, D("2026-11-10"), D("2026-10-20"))}
    old, new = rows["article/old.he.md"], rows["project/new.he.md"]

    check(old["due"] and old["due_on"] == "2026-09-30", f"due 91 days after its own `updated` (a datetime): {old}")
    check(not new["due"] and new["due_on"] == "2027-01-31", f"due after the next run: not yet: {new['due_on']}")
    soon = {r["path"]: r for r in recheck.recheck(root, D("2026-12-15"), None, net=False)}["project/new.he.md"]
    check(not soon["due"], "15 Dec: the next run (1 Jan) comes before 31 Jan")
    late = {r["path"]: r for r in recheck.recheck(root, D("2027-01-01"), None, net=False)}["project/new.he.md"]
    check(late["due"], "1 Jan: due on 31 Jan, before the next run (1 Apr) — flagged now, not a quarter late")
    check(old["facts_newer"] and not new["facts_newer"], "FACTS.md changed after the old piece, not after the new one")

    broken = sorted(b.split(" → ")[0] for b in old["broken"])
    want = sorted([f"{base}/gone", f"{base}/soft", f"{base}/loop", f"{base}/dead-end", "http//example.invalid/x"])
    check(broken == want, f"a 404, a redirect onto the error page, a loop, a chain to a 404, a typo: {broken}")
    check(not {f"{base}/404", f"{base}/no-head", f"{base}/head-to-404"} & set(broken),
          f"a page named 404 that answers, and a 404 or a /404 to HEAD alone, are not broken: {old['broken']}")
    check(old["moved"] == [f"{base}/move → {base}/ok2"], f"a move says where it goes now: {old['moved']}")
    check(old["blocked"] == [f"{base}/blocked → 403"], f"a 403 is «not for a robot», not broken: {old['blocked']}")
    all_links = " ".join(u for p in recheck.pieces(root) for u in recheck.links_of(p))
    check(f"{base}/Foo_(bar)" in all_links and f"{base}/עברית" in all_links and f"{base}/head-to-404" in all_links,
          f"a link with parentheses, an autolink and a link with a title are all found: {all_links[:300]}")
    check(not any("עברית" in b or "Foo_" in b for b in old["broken"]), "…and they answer (a Hebrew path is quoted)")
    check(sorted(new["broken"]) == [f"{base}/gone → 404"], f"`project:` links are checked: {new['broken']}")
    check(sorted(old["stale_sources"]) == sorted([f"{base}/ok", f"{base}/ok2 (בלי תאריך פתיחה)",
                                                  "http//example.invalid/x (בלי תאריך פתיחה)"]),
          f"a source opened more than a quarter ago, or never dated: {old['stale_sources']}")
    und = old["undated_prices"]
    check(len(und) == 3 and any("49" in u and "₪" in u for u in und) and any("8.79$" in u for u in und)
          and not any("20 אירו" in u for u in und) and not any("$1" in u for u in und),
          f"prices without a year — in the body and the FAQ; a table under a dated line and `$1` are not: {und}")
    check(new["undated_prices"] == [] or all("2000" not in u or "100" in u for u in new["undated_prices"]),
          f"«2000 מילים» is not a year: {new['undated_prices']}")
    check(len(new["undated_prices"]) == 0, f"a paragraph with its year has no undated price: {new['undated_prices']}")
    at = next(n for n, ln in enumerate((root / "article" / "old.he.md").read_text(encoding="utf-8").split("\n"), 1)
              if "משרד" in ln and not ln.startswith("meta"))
    check(len(old["office_word"]) == 2 and old["office_word"][0].startswith("מטא:")
          and old["office_word"][1].startswith(f"{at}:"),
          f"«משרד» in the front matter and in the body, at its line in the file ({at}): {old['office_word']}")
    check("news/unclosed.he.md" in rows and "tutorial/bare.he.md" in rows,
          "a front matter that never closes, and a piece with none, are read — not a crash")
    check(rows["tutorial/bare.he.md"]["broken"] == [f"{base}/gone → 404"],
          f"…and a piece with no front matter is checked as all body: {rows['tutorial/bare.he.md']}")

    text = recheck.report(list(rows.values()), D("2026-11-10"), D("2026-10-20"))
    check("2026 Q4" in text and "הריצה הבאה: 2027-01-01" in text, f"the report: the quarter, the next run: {text[:200]}")
    for when, nxt in (("2026-02-10", "2026-04-01"), ("2026-05-10", "2026-07-01"), ("2026-08-10", "2026-10-01"),
                      ("2026-11-10", "2027-01-01")):
        check(recheck.next_run(D(when)) == D(nxt), f"the next run after {when} is {nxt}")
    rc = recheck.main(["--root", str(root), "--today", "2026-11-10", "--write", "--no-net"])
    written = root / "rechecks" / "2026-Q4.md"
    check(rc == 0 and written.exists() and "(הקישורים לא נבדקו בריצה הזו)" in written.read_text(encoding="utf-8"),
          "--write keeps the report as rechecks/2026-Q4.md, and says when links were not checked")
    written.write_text(written.read_text(encoding="utf-8") + recheck.MANUAL + "\n## ביד\n\nקראתי.\n", encoding="utf-8")
    recheck.main(["--root", str(root), "--today", "2026-11-12", "--write", "--no-net"])
    again = written.read_text(encoding="utf-8")
    check("רצה: 2026-11-12" in again and again.count(recheck.MANUAL) == 1 and again.endswith("## ביד\n\nקראתי.\n"),
          f"a second --write renews the measurement and keeps the reading by hand as it was: {again[-120:]}")
    check(recheck.main(["--root", str(root), "--today", "2026-11-10", "--strict", "--no-net"]) == 1,
          "--strict exits 1 on a piece that is due")
    before = (root / "article" / "old.he.md").read_text(encoding="utf-8")
    recheck.main(["--root", str(root), "--today", "2026-11-10", "--write"])
    check((root / "article" / "old.he.md").read_text(encoding="utf-8") == before, "the check never edits a piece")
    srv.shutdown()

    # prices, one form each: every one without a year is flagged; «2000 מילים» is not a year
    forms = ["המנוי עולה $20 לחודש.", "49€ לחודש.", "20 אירו לחודש.", "כ-100 אלף שקל.", "כ-5 אלף ₪ בשנה.",
             "50 אלף ש״ח.", "2000 מילים עולות 100 ₪."]
    check(len(recheck._undated(forms)) == len(forms), f"each price form is found: {recheck._undated(forms)}")
    check(recheck._undated(["עולה 49 ₪, נכון לנובמבר 2026."]) == [], "a price with its year is dated")
    # a front matter that cannot be read is no crash, and the file is all body
    for bad in ("---\nupdated: 2026-02-30\n---\n# x\n", "---\nfaq: 5\nsources: 5\ntitle: x\n---\n# x\n"):
        front, body, _ = recheck.split_piece(bad)
        check(isinstance(front, dict) and recheck.public_lines(front) is not None, f"no crash on {bad!r}")
    front, body, _ = recheck.split_piece("---\nupdated: 2026-02-30\n---\n# x\n")
    check(front == {} and "# x" in body, f"an unreadable front matter leaves all of it as body: {body!r}")
    # a Hebrew host in IDNA, a Hebrew path %-encoded
    sent = recheck._as_sent("https://בינה.co.il/מדריך?ש=1")
    check(sent.startswith("https://xn--") and "%D7" in sent and "בינה" not in sent, f"as a browser sends it: {sent}")
    # a public page may not send the check into the office's own network
    real = recheck._private
    recheck._private = lambda host: host == "inside.test"
    try:
        req = urllib.request.Request("https://public.test/x")
        recheck._NoInward().redirect_request(req, None, 302, "Found", {}, "http://inside.test/admin")
        FAIL.append("a redirect from a public page into a private address is refused")
    except urllib.error.HTTPError as e:
        check(e.code == 310, f"…refused as 310: {e.code}")
    finally:
        recheck._private = real
    check(recheck._private("100.100.100.100") and recheck._private("10.0.0.5") and not recheck._private("1.1.1.1"),
          "a CGNAT/Tailscale address (100.64/10) and a private one are inside; a public one is not")
    # the edges: due on the very day of the next run is the next run's; a source opened 91 days ago is not stale
    edge = Path(tempfile.mkdtemp(prefix="recheck-edge-"))
    (edge / "article").mkdir()
    for slug, upd in (("at-next", "2026-10-02"), ("before-next", "2026-10-01")):
        (edge / "article" / f"{slug}.he.md").write_text(
            f"---\ntitle: x\nupdated: {upd}\nsources:\n  - {{ url: 'https://a.test/', accessed: 2026-08-11 }}\n"
            f"  - {{ url: 'https://b.test/', accessed: 2026-08-10 }}\n---\n# x\n", encoding="utf-8")
    e = {r["path"]: r for r in recheck.recheck(edge, D("2026-11-10"), None, net=False)}
    check(not e["article/at-next.he.md"]["due"] and e["article/before-next.he.md"]["due"],
          "due on 1 Jan is the next run's; due on 31 Dec is this one's")
    check(e["article/at-next.he.md"]["stale_sources"] == ["https://b.test/"],
          f"opened 91 days ago is not stale, 92 is: {e['article/at-next.he.md']['stale_sources']}")


def main() -> int:
    try:
        checks()
    except Exception:                                     # noqa: BLE001 — a crash is a failure, said as one
        FAIL.append("the check itself raised: " + traceback.format_exc(limit=4))
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_recheck: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
