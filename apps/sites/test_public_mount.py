"""sites.public.serve — a site the office serves opens 1:1 from the console, under `/a/<alias>/`.

The console proxies an app at `/a/<alias>/…` and writes `<base href="/a/<alias>/">` into every HTML page
it passes on, unless the page names a base of its own. A site's pages reference everything RELATIVE to
the page (`wp-content/x.css`, `../.assets/<sha>.png`, `about/`), so under the app's base the whole site
lost its styles, pictures and links (Exampleu's clone, 2026-11-09, DGO-1591). This test runs the console's
OWN two rewrites — `_rewrite_abs` and `_inject_base`, read out of platform-base/console/app.py — over
what `public.serve` answers, and proves for every reference in every page:

  * through the console, it resolves to the same file as on the app's own host (`/public/<id>/…`),
    only under the mount — and a link inside the page (`#top`, `?p=2`, `""`) to the same document,
    with the address spelled as the browser spells it (a lowercase `%d7`, a `(`), so it stays on it;
  * the page a visitor gets on the site's own domain is byte for byte what it was (no base), even when
    the request carries an `X-Forwarded-Prefix`;
  * without the fix (no prefix passed), the console's base breaks the page — the test sees the bug.

    python3 apps/sites/test_public_mount.py
"""
import ast
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SITES_STATE_DIR", tempfile.mkdtemp())
os.environ["SITES_PUBLIC_DIR"] = tempfile.mkdtemp()
import public  # noqa: E402

public.bundle = lambda force=False: None        # no asset service here: pages are served as written


def console_rewrites():
    """`_rewrite_abs` and `_inject_base` exactly as the console has them — not a copy that can drift."""
    src = (REPO / "platform-base/console/app.py").read_text(encoding="utf-8")
    keep = [n for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name in ("_rewrite_abs", "_inject_base")]
    assert len(keep) == 2, "the console's rewrites moved — this test must follow them"
    ns: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "console/app.py", "exec"), ns)
    return ns["_rewrite_abs"], ns["_inject_base"]


REWRITE_ABS, INJECT_BASE = console_rewrites()
SID = "exampleu"
PAGES = {
    "index.html": '<!DOCTYPE html><html lang="he"><head><meta charset="utf-8">'
                  '<link rel="stylesheet" href="wp-content/a.css"><script src="wp-includes/j.js"></script>'
                  '</head><body><a href="עלינו/">עלינו</a><img src=".assets/ab.png" '
                  'srcset="wp-content/s1.jpg 1x, wp-content/s2.jpg 2x"><a href="#top">↑</a>'
                  '<a href="https://example.org/x">out</a></body></html>',
    "עלינו/index.html": '<html><head><link rel="stylesheet" href="../wp-content/a.css"></head><body>'
                        '<a href="../">בית</a><a href="../projects/village/">כפר</a>'
                        '<img src="../.assets/ab.png"></body></html>',
    "projects/village/index.html": '<html><head itemscope><link href="../../wp-content/a.css" rel="stylesheet">'
                                  '</head><body><video src="../../wp-content/v.mp4"></video>'
                                  '<a href="../../">בית</a></body></html>',
    # asked for WITHOUT its slash (`features` → features.html): its links inside the page must stay on it
    "features.html": '<!doctype html><meta charset=utf-8><title>f</title><img src="wp-content/f.png">'
                     '<a href="#top">↑</a><a href="?p=2">2</a><a href="">here</a>',
    # a name with characters a browser keeps as typed, whatever a server would re-encode them as
    "projects/a(b),c/index.html": '﻿<!DOCTYPE html><p><a href="#top">↑</a><img src="../../wp-content/p.png">',
}
# the address as the BROWSER spells it (WordPress writes Hebrew slugs in lowercase hex) → the path the app
# receives, decoded — what `public.resolve` turns into the file
ASKED = {"index.html": ("", ""),
         "עלינו/index.html": ("%d7%a2%d7%9c%d7%99%d7%a0%d7%95/", "עלינו/"),
         "projects/village/index.html": ("projects/village/", "projects/village/"),
         "features.html": ("features", "features"),
         "projects/a(b),c/index.html": ("projects/a(b),c/", "projects/a(b),c/")}
URL_ATTR = re.compile(r'\b(href|src|srcset)="([^"]*)"')


def refs(html):
    """Every URL the page references, as the browser reads them (srcset split into its candidates)."""
    out = []
    for attr, val in URL_ATTR.findall(re.sub(r"<base [^>]*>", "", html)):
        if attr == "srcset":
            out += [c.strip().split()[0] for c in val.split(",") if c.strip()]
        else:
            out.append(val)
    return [u for u in out if not u.startswith(("http:", "https:", "//", "data:"))]


def base_of(doc_url, html):
    m = re.search(r'<base href="([^"]*)"', html)
    return urljoin(doc_url, m.group(1)) if m else doc_url


def through_console(served_html):
    return INJECT_BASE(REWRITE_ABS(served_html, "sites"), "/a/sites/")


def main():
    site = {"id": SID, "public": {"mode": "office", "entries": [{"domain": "example.co.il", "path": "/"}]}}
    root = public.cache_dir(SID)
    for rel, text in PAGES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    checked = 0
    broken_before = 0
    for rel, text in PAGES.items():
        for query in ("", "q=1"):
            spelled, page = ASKED[rel]
            on_host = "/public/" + SID + "/" + spelled + (f"?{query}" if query else "")
            in_console = "/a/sites" + on_host
            # the app's own host: no mount, nothing added
            plain = public.serve(site, page, host="sites.office.example", count=False)
            assert plain["status"] == 200 and plain["body"].decode() == text, rel
            # a visitor on the site's own domain, even one that sends the header: unchanged
            visitor = public.serve(site, page, host="example.co.il", count=False, prefix="/a/sites")
            assert visitor["body"].decode() == text and "Vary" not in visitor["headers"], rel
            # through the console, after the console's own rewrites
            served = public.serve(site, page, host="console.office.example", count=False, prefix="/a/sites")
            assert served["headers"].get("Vary") == "X-Forwarded-Prefix", served["headers"]
            html = through_console(served["body"].decode())
            assert html.lower().count("<base ") == 1 and public.NO_BASE in html, html[:300]
            assert html.lower().find("<base ") > html.lower().find("<!doctype") or "<!doctype" not in html.lower()
            # each reference resolves as on the app's own host, only under the mount — a link inside
            # the page (`#top`, `?p=2`, `""`) to the same document, so the browser stays on it
            want = [urljoin(on_host, u) for u in refs(text)]
            got = [urljoin(base_of(in_console, html), u) for u in refs(html)]
            assert got == ["/a/sites" + w for w in want], (rel, query, got, want)
            checked += len(got)
            # what the console made of the page before this fix: the app's base, every reference off its page
            old = through_console(plain["body"].decode())
            old_got = [urljoin(base_of(in_console, old), u) for u in refs(old)]
            broken_before += sum(1 for g, w in zip(old_got, want) if g != "/a/sites" + w)
    assert checked == 2 * 20, checked            # every reference above, with and without a query
    assert broken_before == checked, broken_before   # the bug is visible to this test: all of them
    print(f"test_public_mount: ok — {checked} references in {len(PAGES)} pages resolve under the console "
          f"as on the app's own host ({broken_before} were off their page before)")


if __name__ == "__main__":
    main()
