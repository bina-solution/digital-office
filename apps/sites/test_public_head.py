"""sites — a public page answers HEAD as it answers GET, without the body, and a HEAD is not a visit (DGO-1772).

Measured on 2026-11-10: `curl -I https://digital-office.co.il/` and `curl -I https://bina-solutions.co.il/` answered
405 Method Not Allowed: the public routes were GET-only, and FastAPI (unlike Starlette) does not answer HEAD on a GET
route. Link checkers, uptime monitors, card fetchers and some crawlers ask HEAD first, and a page that refuses it
reads as broken to them. This test drives the real app through ASGI — its own routing, no network, no framework
stand-in — and checks:

  1. HEAD on a public page of a site the office serves answers what GET answers: the same status and Content-Type
     (200 for a page, the site's 404 for a missing one, the 301 of the root without its slash);
  2. HEAD on a site the office does not serve answers GET's 404, not 405;
  3. a HEAD on the site's own domain is not counted as a visit; a GET there is — for a page, and for a site asset
     (`.assets/…`, which used to count every fetch from any host);
  4. on the code as it was (GET-only routes) cases 1 and 2 FAIL with 405 — checked by hand on 2026-11-10 by running
     this file against that tree, and again by the second reader against the old app.py in memory.

    python3 apps/sites/test_public_head.py
"""
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["SITES_STATE_DIR"] = tempfile.mkdtemp()      # never the app's own state, even inside its image
os.environ["SITES_PUBLIC_DIR"] = tempfile.mkdtemp()
os.environ["SITES_SCHEDULER"] = "0"

import app as sites_app  # noqa: E402
import public  # noqa: E402
import store  # noqa: E402

DOMAIN = "head.example.co.il"
SITE = {"id": "headsite", "label": "head", "kind": "static", "machine": "computer_local-local",
        "public": {"mode": "office", "entries": [{"domain": DOMAIN, "path": "/"}]}}


def ask(method: str, path: str, host: str = "sites:8979") -> tuple[int, dict, bytes]:
    """One request through the app's own ASGI routing: (status, headers, body)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"host", host.encode()), (b"x-forwarded-host", host.encode()),
                         (b"user-agent", b"test-visitor/1.0"), (b"x-forwarded-for", b"203.0.113.7")],
             "client": ("127.0.0.1", 1),
             "server": ("sites", 8979)}
    got: dict = {"status": 0, "headers": {}, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            got["status"] = message["status"]
            got["headers"] = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            got["body"] += message.get("body", b"")

    asyncio.run(sites_app.app(scope, receive, send))
    return got["status"], got["headers"], got["body"]


def main() -> int:
    store.init()
    store.upsert_site(SITE)
    root = public.cache_dir(SITE["id"])
    (root / "about").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_bytes(b"<html><body>home</body></html>")
    (root / "about" / "index.html").write_bytes(b"<html><body>about</body></html>")
    (root / "404.html").write_bytes(b"<html><body>not here</body></html>")
    public.bundle = lambda force=False: None                        # no asset service in a test
    visits: list = []
    public._count_visit = lambda sid, path, status, nbytes, ua="", ip="": visits.append((sid, path, status, ua, ip))

    bad = []
    for path in ("/public/headsite/about/", "/public/headsite/no-such-page", "/public/headsite"):    # case 1
        g, h = ask("GET", path), ask("HEAD", path)
        same = ("content-type", "content-length", "location")
        if (h[0], *(h[1].get(k) for k in same)) != (g[0], *(g[1].get(k) for k in same)):
            bad.append(f"1: HEAD {path} must answer what GET answers ({g[0]} {[g[1].get(k) for k in same]}), got {h[0]} "
                       f"{[h[1].get(k) for k in same]}")
    g, h = ask("GET", "/public/nobody/x"), ask("HEAD", "/public/nobody/x")                           # case 2
    if h[0] != g[0] or h[0] == 405:
        bad.append(f"2: HEAD on a site the office does not serve answers GET's {g[0]}, got {h[0]}")
    visits.clear()                                                                                 # case 3
    ask("HEAD", "/public/headsite/about/", host=DOMAIN)
    if visits:
        bad.append(f"3: a HEAD is not a visit, counted {visits}")
    ask("GET", "/public/headsite/about/", host=DOMAIN)
    if len(visits) != 1:
        bad.append(f"3: a GET on the site's own domain is one visit, counted {visits}")
    # an asset, proxied from digital-assets (stood in for here): counted like a page, never for a HEAD
    public.requests = types.SimpleNamespace(
        RequestException=Exception,
        get=lambda url, timeout=None, headers=None: types.SimpleNamespace(status_code=200, content=b"png",
                                                                           headers={"content-type": "image/png"}))
    visits.clear()
    ask("HEAD", "/public/headsite/.assets/ab12.png", host=DOMAIN)
    ask("GET", "/public/headsite/.assets/ab12.png")                     # the office looking at it, not a visitor
    if visits:
        bad.append(f"3: an asset is not a visit for a HEAD, nor from the office's own host, counted {visits}")
    ask("GET", "/public/headsite/.assets/ab12.png", host=DOMAIN)
    # one visit, at the asset's own path, with the visitor's agent and address (so bots and the office's probe are
    # told apart, and a visitor is counted once an hour)
    if visits != [("headsite", "/.assets/ab12.png", 200, "test-visitor/1.0", "203.0.113.7")]:
        bad.append(f"3: an asset fetched by a visitor is one visit, with its path, agent and address — counted {visits}")
    if bad:
        print("FAIL\n  " + "\n  ".join(bad))
        return 1
    print("public HEAD: ok — HEAD answers what GET answers on the serving path (200, 404, 301), and is not a visit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
