"""the monthly interfaces check (DGO-812): content/interfaces.py measures each interface with one GET — ok, blocked
(any 403, a challenge page that answers 200, by its title or its body, in UTF-8 or windows-1255), gone (a 404, a
redirect onto an error page, an `api` that answers a web page) — keeps a page's title, headings and text hash and an
API's shape (never its values), and says what changed since the last month. Runs against a local HTTP server whose
answers change between two months.

    python3 apps/digital-assets/tests/test_interfaces.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"   # a sandbox's proxy never sees the test
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "content"))
import interfaces  # noqa: E402

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


class Site(BaseHTTPRequestHandler):
    month = "2026-10"

    def do_GET(self):
        m, oct_ = Site.month, Site.month == "2026-10"
        if self.path == "/soft":
            self.send_response(302)
            self.send_header("Location", "/404")
            self.end_headers()
            return
        if self.path == "/stall":                     # a 403 whose body never arrives (past the 3 s timeout)
            self.send_response(403)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"<title>x")
            self.wfile.flush()
            time.sleep(4)
            return
        if self.path == "/blocked-1255-bare":         # windows-1255 bytes with no charset said anywhere
            data = "<title>הגישה נחסמה</title>".encode("cp1255")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        html = "text/html; charset=utf-8"
        pages = {
            "/api": (200, "application/json", json.dumps({"success": True, "result": [{"rate": 3.71, "key": "USD"}]}
                                                         if oct_ else
                                                         {"success": True, "result": [{"rate": 3.69, "key": "USD",
                                                                                       "unit": 1}]})),
            "/stable-api": (200, "application/json", json.dumps({"success": True, "count": 1 if oct_ else 2})),
            "/rich-api": (200, "application/json", json.dumps({"rates": {f"{m}-09": 3.7}, "empty": [],
                                                               "items": [{"k": 1}, {"k": 2, "unit": 1}]})),
            "/maintenance-api": (200, html, "<title>Maintenance</title><h1>Back soon</h1>"),
            "/page": (200, html, "<html><title>שירותים</title><h1>שירותים מקוונים</h1>"
                      + ("<h2>תשלום</h2>" if oct_ else "<h2>תשלום מקוון</h2><h3>חדש</h3>") + "</html>"),
            "/news": (200, html, f"<title>חדשות</title><h1>חדשות</h1><p>עודכן {m}</p>"
                      + ("<p>ידיעה</p>" if oct_ else "<p>ידיעה אחרת</p>")),
            "/dated": (200, html, f"<title>מחירון</title><h1>מחירון {m}</h1><p>עודכן ב-{m}-01, 1,234 ₪</p>"),
            "/reorder": (200, html, "<title>r</title>" + ("<h2>א</h2><h2>ב</h2>" if oct_ else "<h2>ב</h2><h2>א</h2>")),
            "/pipe": (200, html, f"<title>{'Old' if oct_ else 'Pricing'} | Meta</title><h1>p</h1>"),
            "/flip": ((403, html, "<title>אסור</title>") if oct_ else (200, html, "<title>פתוח</title><h1>א</h1>")),
            "/cf": (403, html, "<title>Just a moment...</title>"),
            "/forbidden": (403, html, "<title>אסור</title>"),
            "/radware": (200, html, "<title>Radware Page</title>"),
            "/radware-ir": (200, html, "<title>Radware Ltd. Investor Relations</title><h1>IR</h1>"),
            "/cf-body": (200, "text/plain", "<html><body><div id='cf-chl-widget'></div></body></html>"),
            "/chl-script": (200, html, "<title>שירות</title><script>var cf_chl_opt={}</script>"   # a real page that
                            "<h1>שירות מקוון</h1><h2>כניסה</h2>"),                         # carries a mark: ok
            "/bot-script": (200, html, "<title>The Goverment Identification System</title>"     # login.gov.il: no h1–h3
                            "<script src='https://validate.perfdrive.com/x.js'></script><div>כניסה</div>"),
            "/blocked-1255": (200, "text/html; charset=windows-1255", "<title>הגישה נחסמה | דואר</title>"),
            "/gone": (404, html, "<title>לא נמצא</title>"),
        }
        code, ctype, body = pages.get(self.path, (200, html, "<title>שגיאה</title>"))
        data = body.encode("cp1255" if "1255" in ctype else "utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


API = {"api", "stable-api", "rich-api", "maintenance-api"}
NAMES = ("api", "stable-api", "rich-api", "maintenance-api", "page", "news", "dated", "reorder", "pipe", "flip", "cf",
         "forbidden", "radware", "radware-ir", "cf-body", "bot-script", "chl-script", "blocked-1255", "blocked-1255-bare",
         "stall",
         "gone", "soft")


def checks() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"https://127.0.0.1:{srv.server_address[1]}"         # https in the file, served as http below
    tmp = Path(tempfile.mkdtemp(prefix="ifx-"))
    (tmp / "interfaces.yaml").write_text("interfaces:\n" + "".join(
        f"  - {{ id: {n}, name: \"{n} | x\", owner: test, url: \"{base}/{n}\", kind: {'api' if n in API else 'site'},"
        f" why: t, watch: t }}\n" for n in NAMES), encoding="utf-8")
    real_fetch = interfaces.fetch
    interfaces.fetch = lambda url, timeout=25: real_fetch(url.replace("https://", "http://"), 3)
    out = tmp / "out"
    args = ["--file", str(tmp / "interfaces.yaml"), "--out", str(out)]

    check(interfaces.main(["--month", "2026-10", *args]) == 0, "the first month runs — a stalled 403 included")
    first = json.loads((out / "2026-10.json").read_text(encoding="utf-8"))["interfaces"]
    states = {k: v["state"] for k, v in first.items()}
    want = {**{n: "ok" for n in ("api", "stable-api", "rich-api", "page", "news", "dated", "reorder", "pipe",
                                  "radware-ir", "bot-script", "chl-script")},
            **{n: "blocked" for n in ("flip", "cf", "forbidden", "radware", "cf-body", "blocked-1255",
                                       "blocked-1255-bare", "stall")},
            "maintenance-api": "gone", "gone": "gone", "soft": "gone"}
    check(states == want, f"each state, by the answer and never by the content type: "
          f"{ {k: (states[k], want[k]) for k in states if states[k] != want[k]} }")
    check(first["api"]["shape"] == ["result", "result.[]", "result.[]key", "result.[]rate", "success"],
          f"an API keeps its shape: {first['api'].get('shape')}")
    check(set(first["rich-api"]["shape"]) >= {"rates.{*}", "empty.[]", "items.[]unit"}
          and not any("2026" in s for s in first["rich-api"]["shape"]),
          f"every element of a list, an empty list, a date as a key: {first['rich-api'].get('shape')}")
    check("3.71" not in (out / "2026-10.json").read_text(encoding="utf-8"), "…never its values")
    check(first["page"]["title"] == "שירותים" and first["page"]["headings"] == ["שירותים מקוונים", "תשלום"],
          f"a page keeps its title and headings: {first['page']}")
    check("נמדד לראשונה" in (out / "2026-10.md").read_text(encoding="utf-8"), "the first month is the baseline")
    (out / "2026-10.v2.json").write_text("{}", encoding="utf-8")       # not a month: never compared with

    Site.month = "2026-11"
    check(interfaces.main(["--month", "2026-11", *args]) == 0, "the second month runs")
    now = json.loads((out / "2026-11.json").read_text(encoding="utf-8"))["interfaces"]
    cmp = {n: interfaces.compare(now[n], first[n]) for n in NAMES}
    check(len(cmp["api"]) == 1 and "result.[]unit" in cmp["api"][0], f"a new field in the answer is a change: {cmp['api']}")
    check(cmp["stable-api"] == [] and cmp["rich-api"] == [], f"new values, or a new date as a key, are not: {cmp}")
    check(len(cmp["page"]) == 1 and "תשלום מקוון" in cmp["page"][0] and "'תשלום'" in cmp["page"][0],
          f"new and gone headings are said: {cmp['page']}")
    check(cmp["news"] == ["התוכן זז (המבנה, הכתובת והכותרות לא השתנו)"], f"text that moved alone: {cmp['news']}")
    check(cmp["dated"] == [], f"a date in a heading or in the text is not a change: {cmp['dated']}")
    check(cmp["reorder"] == ["התוכן זז (המבנה, הכתובת והכותרות לא השתנו)"],
          f"the same headings in another order are not new headings — only the content moved: {cmp['reorder']}")
    check(cmp["flip"] == ["מצב: blocked → ok"], f"blocked → ok is said once, not as every heading new: {cmp['flip']}")
    md = (out / "2026-11.md").read_text(encoding="utf-8")
    check("מושווה ל: 2026-10" in md and "Old \\| Meta" in md and "pipe \\| x" in md,
          f"compared with the last month (not the .v2 file); a `|` in a cell is escaped: {md[:400]}")
    rows = [ln for ln in md.splitlines() if ln.startswith("| [")]
    check(len(rows) == len(NAMES) and all(len(re.split(r"(?<!\\)\|", ln)) == 7 for ln in rows),
          "every row of the table has its five cells (an escaped `|` is not a cell)")

    (out / "2026-11.md").write_text(md + "\n" + interfaces.MANUAL + "\n## ביד\n\nנבדק בדפדפן.\n", encoding="utf-8")
    interfaces.main(["--month", "2026-11", *args])
    again = (out / "2026-11.md").read_text(encoding="utf-8")
    check(again.count(interfaces.MANUAL) == 1 and again.endswith("## ביד\n\nנבדק בדפדפן.\n"),
          "measuring the month again keeps the notes by hand")
    check(interfaces.main(["--month", "2026-13", *args]) == 2, "a month that is not one is refused")
    srv.shutdown()

    # the page's own charset, said only in a <meta>: latin-1 «é», never read as windows-1255 «י»
    page = interfaces.page_of("<meta charset='iso-8859-1'><title>Café</title>".encode("latin-1"), "text/html")
    check(page["title"] == "Café", f"the <meta> charset is read: {page['title']}")
    # headings as a multiset, all of them — a duplicate gone is said, one beyond the 40th too
    a = {"state": "ok", "where": "x", "headings": ["א", "א", "ב"], "headings_sha": "1"}
    b = {"state": "ok", "where": "x", "headings": ["א", "ב"], "headings_sha": "2"}
    check(interfaces.compare(b, a) == ["כותרות: נוספו —, ירדו ['א']"], f"a duplicate heading gone: {interfaces.compare(b, a)}")
    many = "".join(f"<h2>כותרת {chr(0x5d0 + i % 22)}{i // 22}x</h2>" for i in range(46))
    p1 = interfaces.page_of(f"<title>t</title>{many}".encode(), "text/html")
    p2 = interfaces.page_of(f"<title>t</title>{many}<h2>האחרונה</h2>".encode(), "text/html")
    c = interfaces.compare({**p2, "state": "ok", "where": "x"}, {**p1, "state": "ok", "where": "x"})
    check(len(p2["headings"]) == 47 and c == ["כותרות: נוספו ['האחרונה'], ירדו —"], f"the 47th heading: {c}")
    # a timestamp as a key is a value; an XML answer that is an HTML error page is not data
    shape = interfaces.shape_of(json.dumps({"at": {"2026-11-10T00:00:00Z": 1, "2026-11-10T02:00:00+02:00": 2}}).encode(),
                                "application/json")
    check(shape == ["at", "at.{*}"], f"timestamps with a zone, as keys: {shape}")
    check(interfaces.shape_of(b"<html><body>Service Unavailable</body></html>", "text/xml") is None,
          "a text/xml answer that is an HTML page is not the API's shape")
    check(interfaces.shape_of(b"<?xml version='1.0'?><root><a/><b/></root>", "text/xml") == ["root", "a", "b"],
          "real XML keeps its shape")


def main() -> int:
    try:
        checks()
    except Exception:                                     # noqa: BLE001 — a crash is a failure, said as one
        FAIL.append("the check itself raised: " + traceback.format_exc(limit=4))
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_interfaces: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
