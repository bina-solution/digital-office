"""sites.public — a public site has ONE address: a plain-http request is sent on to https with a 308 (DGO-1765).

Measured on 2026-11-10: `http://digital-office.co.il/` and `http://bina-solutions.co.il/about/` answered 200 with
the page beside the https address, so every page of both sites existed twice and a search engine was left to
choose. The app that serves the site now answers a plain-http request on a public domain with a 308 to the same
address over https — where the office's edge answers https. This test runs the SERVING path, not a rendered
file (a first version that asked the edge to redirect passed its rendered-file test and would have answered 400):

  1. plain http on the site's public domain, on an office whose edge answers https → 308, the Location is the
     same host, path and query over https, and the body is empty — for a page and for an asset alike;
  2. the same request over https → the page, as before;
  3. an office whose edge does not answer https (a laptop, or this process before its first publish) → the page;
  4. plain http on a host that is NOT one of the site's public domains (the console's mount, this app's own
     host, a host a stranger put in the header) → never a redirect, so the Location can name only a declared
     domain;
  5. the address asked for: traefik's `X-Replaced-Path` when it is there, else the entry's own path prefix put
     back in front — with the query;
  6. `edge_answers_https`: a resolver AND the office's own port-80 rule among the live edge's middlewares;
  7. the route handler hands `serve` the request's scheme and the address asked for;
  8. with the redirect switched off (the code as it was), case 1 FAILS — the test sees the defect.

    python3 apps/sites/test_public_edge.py
"""
import ast
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["SITES_STATE_DIR"] = tempfile.mkdtemp()      # never the app's own state, even inside its image
os.environ["SITES_PUBLIC_DIR"] = tempfile.mkdtemp()
try:                                    # nothing here makes a request; a host without `requests` can run this
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")

import public  # noqa: E402

DOMAIN = "digital-office.co.il"
SITE = {"id": "do", "public": {"mode": "office", "entries": [{"domain": DOMAIN, "path": "/"}]}}
BLOG = {"id": "blog", "public": {"mode": "office", "entries": [{"domain": DOMAIN, "path": "/blog"}]}}
SERVER = {"entrypoints": ["web", "websecure"], "tls": True, "certresolver": "le",
          "middlewares_available": ["hsts", "port80-https"]}
THE_SWITCH = "    onward = https_address(site, host, scheme, asked or asked_address(site, host, path))"
PAGE = b"<html><head><title>about</title></head><body>about us</body></html>"


def prepare(module):
    """A synced site on disk and no asset service, for `module` (the real one or the one as it was)."""
    module.bundle = lambda force=False: None
    # an asset that is NOT sent on would be fetched from the asset service: here it is a plain 200
    module._serve_asset = lambda site, path: {"status": 200, "headers": {}, "body": b"asset"}
    root = module.cache_dir(SITE["id"])
    (root / "about").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_bytes(b"<html><body>home</body></html>")
    (root / "about" / "index.html").write_bytes(PAGE)


def check(module=public):
    """Cases 1–6 against `module`. Returns one line per claim that does not hold."""
    bad = []
    prepare(module)
    assert module.mode_of(SITE) == "office" and module.entries_of(SITE), "the test's site record is not an office site"

    def ask(scheme, host=DOMAIN, path="about/", asked="/about/?a=1", https=True):
        module._state["https"] = https
        return module.serve(SITE, path, host=host, count=False, scheme=scheme, asked=asked)

    out = ask("http")                                                           # case 1
    if out["status"] != 308 or out["headers"].get("Location") != f"https://{DOMAIN}/about/?a=1" or out["body"] != b"":
        bad.append(f"1: plain http on a public domain must answer 308 to the same address over https, got "
                   f"{out['status']} {out['headers'].get('Location')}")
    elif out["headers"].get("Cache-Control") != "max-age=3600":
        bad.append("1: the 308 must carry a lifetime — a browser keeps one without it for ever")
    out = ask("http", path=".assets/ab.png", asked="/.assets/ab.png")
    if out["status"] != 308 or out["headers"].get("Location") != f"https://{DOMAIN}/.assets/ab.png":
        bad.append(f"1: an asset asked over plain http is sent on too, got {out['status']}")
    out = ask("HTTP", host=DOMAIN.upper() + ":80")
    if out["status"] != 308 or out["headers"].get("Location") != f"https://{DOMAIN}/about/?a=1":
        bad.append("1: the scheme and the host are read without their case and port")

    out = ask("https")                                                          # case 2
    if out["status"] != 200 or PAGE not in out["body"]:
        bad.append(f"2: over https the page is served as before, got {out['status']}")

    out = ask("http", https=False)                                              # case 3
    if out["status"] != 200 or PAGE not in out["body"]:
        bad.append(f"3: where the edge does not answer https the page is served, got {out['status']}")

    for host in ("console.localhost", "sites:8979", "evil.example", ""):          # case 4
        out = ask("http", host=host)
        if out["status"] in (301, 302, 307, 308) or "Location" in out["headers"]:
            bad.append(f"4: a request on {host or 'no host'!r} must never be redirected, got {out['status']} "
                       f"{out['headers'].get('Location')}")

    if hasattr(module, "asked_address"):                                         # case 5
        got = [module.asked_address(SITE, DOMAIN, "docs/x", "", "q=1"),
               module.asked_address(BLOG, DOMAIN, "x", "", "q=1"),
               module.asked_address(BLOG, DOMAIN, "x", "/blog/y", ""),
               module.asked_address(SITE, DOMAIN, "", "", "")]
        if got != ["/docs/x?q=1", "/blog/x?q=1", "/blog/y", "/"]:
            bad.append(f"5: the address asked for is rebuilt wrongly: {got}")
        module._state["https"] = True
        out = module.serve(BLOG, "x", host=DOMAIN, count=False, scheme="http")   # no header: the prefix comes back
        if out["headers"].get("Location") != f"https://{DOMAIN}/blog/x":
            bad.append(f"5: an entry under a path prefix must go back to that prefix, got {out['headers'].get('Location')}")
    else:
        bad.append("5: no `asked_address`")

    if hasattr(module, "edge_answers_https"):                                    # case 6
        got = [module.edge_answers_https(SERVER),
               module.edge_answers_https({**SERVER, "middlewares_available": ["hsts"]}),
               module.edge_answers_https({**SERVER, "certresolver": ""}),
               module.edge_answers_https({**SERVER, "tls": False}),
               module.edge_answers_https({})]
        if got != [True, False, False, False, False]:
            bad.append(f"6: the edge answers https only with a resolver and the office's port-80 rule: {got}")
    else:
        bad.append("6: no `edge_answers_https`")
    module._state["https"] = False
    return bad


def handler_hands_them_over():
    """Case 7: `_public_response` in app.py calls `public.serve(…, scheme=<X-Forwarded-Proto>, asked=…)`."""
    src = (HERE / "app.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_public_response")
    text = ast.get_source_segment(src, fn) or ""
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "serve"]
    kw = {k.arg for c in calls for k in c.keywords}
    # the LAST X-Replaced-Path is read: traefik adds its own after a copy the client sent
    return ({"scheme", "asked"} <= kw and "x-forwarded-proto" in text and "public.asked_address(" in text
            and 'getlist("x-replaced-path")' in text and "[-1]" in text)


def as_it_was():
    """The same module with the redirect switched off — `serve` as it was before DGO-1765."""
    src = (HERE / "public.py").read_text(encoding="utf-8")
    assert src.count(THE_SWITCH) == 1, "serve's https line moved — this test must follow it"
    old = types.ModuleType("public_as_it_was")
    old.__file__ = str(HERE / "public.py")
    exec(compile(src.replace(THE_SWITCH, '    onward = ""'), "public_as_it_was.py", "exec"), old.__dict__)
    return old


if __name__ == "__main__":
    failed = check()
    if not handler_hands_them_over():
        failed.append("7: app.py's _public_response does not hand serve() the scheme and the address asked for")
    for line in failed:
        print("FAIL:", line)
    old_failed = check(as_it_was())
    if not any(line.startswith("1: plain http on a public domain") for line in old_failed):   # case 8
        failed.append("8")
        print("FAIL: 8: on the code as it was plain http served the page, and the test did not say so")
    print(f"public https: {'FAILED' if failed else 'ok'} — eight cases; on the code as it was, "
          f"{len(old_failed)} claim(s) fail, as they must")
    sys.exit(1 if failed else 0)
