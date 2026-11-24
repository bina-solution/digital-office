#!/usr/bin/env python3
"""test_page_base — the documents screen's page carries a <base> at the prefix it is served under (DGO-2167).

The owner's phone, 2026-11-22 12:12Z: a document opened at its own address (`/doc/<id>`, the app at its own host)
sent «שליחה לחתימה» to `/doc/api/sign/<id>` — 405, «הקישור לא נוצר — הבקשה נדחתה» — because the screen calls its
API by relative urls and the page had no <base>. These claims hold the fix:
- `/`, a screen route (`/doc/<id>`, `/doc/<id>/edit`, `/docs`) and `index.html` all serve the page with
  `<base href="/">`: a relative `api/sign/<id>` then resolves to `/api/sign/<id>`, wherever the address bar is;
- under the console (`X-Forwarded-Prefix: /a/my-docs`) the base is `/a/my-docs/`, the console's own; and through
  another office's door (`/a/my-docs.hp-laptop`) that prefix;
- a prefix that is not a plain path (a quote, a script, `//evil`) is not trusted: the base is `/`;
- a real file (`app.js`) is that file, never the page (the cold deep link used to load `doc/app.js` as the page).

Run: python3 apps/my-docs/test_page_base.py   (in the my-docs image: it imports the app — flask, requests)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as A  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


c = A.app.test_client()


def base(path, prefix=None):
    # follow_redirects: `/index.html` is Flask's 308 to `/` (the route's default), as it always was
    r = c.get(path, headers={"X-Forwarded-Prefix": prefix} if prefix is not None else {}, follow_redirects=True)
    m = re.search(r'<base href="([^"]*)">', r.get_data(as_text=True))
    return r.status_code, (m.group(1) if m else None), r.headers.get("Content-Type", "")


for p in ("/", "/index.html", "/doc/doc_74aff3f899bb4c5b", "/doc/doc_x/edit", "/docs"):
    st, b, ct = base(p)
    check(st == 200 and b == "/" and ct.startswith("text/html"), f"{p}: the page, with <base href=\"/\"> ({st} {b})")
st, b, _ = base("/doc/doc_x", "/a/my-docs")
check(b == "/a/my-docs/", f"under the console: <base href=\"/a/my-docs/\"> ({b})")
st, b, _ = base("/", "/a/my-docs.hp-laptop/")
check(b == "/a/my-docs.hp-laptop/", f"through another office's door: its prefix ({b})")
check(A._PREFIX.fullmatch("/a\n") is None and A._PREFIX.fullmatch("/a/my-docs") is not None,
      "a prefix with a trailing newline is no plain path (fullmatch, not `$`)")
for bad in ('/a/x"><script>alert(1)</script>', "//evil.example", "/a/my docs", "javascript:alert(1)"):
    st, b, _ = base("/", bad)
    check(b == "/", f"an untrusted prefix {bad[:24]!r} is not used: <base href=\"/\"> ({b})")
r = c.get("/app.js")
body = r.get_data(as_text=True)
check(r.status_code == 200 and "<base" not in body and "<html" not in body.lower(), "/app.js is the script, never the page")
check(len(re.findall(r"<base ", c.get("/").get_data(as_text=True))) == 1, "exactly one <base> in the page")
r = c.get("/doc/doc_x")
check(r.headers.get("Cache-Control") == "no-cache", "the page is revalidated (no-cache), as before")

print(f"test_page_base: {'all passed' if not FAIL else str(len(FAIL)) + ' failed'}")
sys.exit(1 if FAIL else 0)
