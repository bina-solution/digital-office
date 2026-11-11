"""A public site's missing page is the SITE's 404, and the sites app says so (DGO-1591).

The console proxies an app under `/a/<alias>/`, and its history fallback answers a page's 404 with the app's own
entry page, so that an app's deep link opens its screen. Under `/a/sites/public/<id>/` that put the Sites app
itself into a public site's frame, with 200, for any page the site does not have (measured on Exampleu,
2026-11-09). The console now leaves an answer marked `X-Bina-Final: 1` as it is
(platform-base/console/test_app.py holds that half). This holds the other one: every error of the public path —
a missing page, a site this office does not serve, «not synced yet», an unreadable file — carries the mark, and
a page that exists does not.

`_public_response` is read out of app.py and run against stand-ins, so no web framework is needed here.
    python3 apps/sites/test_public_404_final.py
"""
import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")


class Response:
    def __init__(self, content=b"", status_code=200, headers=None, media_type=None):
        self.body, self.status_code, self.headers = content, status_code, dict(headers or {})


class Headers(dict):
    """Starlette's request headers as `_public_response` reads them: `.get`, and `.getlist` (DGO-1765)."""

    def getlist(self, name):
        return [self[name]] if name in self else []


class Request:
    def __init__(self):
        self.headers, self.client, self.method = Headers(), None, "GET"
        self.url = type("URL", (), {"query": ""})()


class Store:
    @staticmethod
    def get_site(sid):
        return {"id": sid, "office": sid != "elsewhere"} if sid != "nobody" else None


class Public:
    @staticmethod
    def mode_of(site):
        return "office" if site.get("office") else "external"

    @staticmethod
    def asked_address(site, host, path, replaced="", query=""):
        return replaced or "/" + path

    @staticmethod
    def serve(site, path, **kw):
        if path in ("", "about/"):
            return {"status": 200, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": b"<html>"}
        status = {"not-synced": 503, "unreadable": 500}.get(path, 404)
        return {"status": status, "headers": {"Content-Type": "text/plain; charset=utf-8"}, "body": b"Not Found"}


def public_response():
    fn = [n for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef) and n.name == "_public_response"]
    assert len(fn) == 1, "_public_response moved — this test must follow it"
    ns = {"Response": Response, "Request": Request, "store": Store, "public": Public}
    exec(compile(ast.Module(body=fn, type_ignores=[]), "sites/app.py", "exec"), ns)
    return ns["_public_response"]


if __name__ == "__main__":
    answer = public_response()
    cases = [("exampleu", "no-such-page", 404, True), ("exampleu", "a/b/c", 404, True),
             ("nobody", "", 404, True), ("elsewhere", "about/", 404, True),
             ("exampleu", "not-synced", 503, True), ("exampleu", "unreadable", 500, True),
             ("exampleu", "", 200, False), ("exampleu", "about/", 200, False)]
    for sid, path, status, final in cases:
        r = answer(sid, path, Request())
        assert r.status_code == status, (sid, path, r.status_code)
        assert (r.headers.get("X-Bina-Final") == "1") is final, (sid, path, r.headers)
    print(f"ok: {len(cases)} public answers — every error is marked final, no page that exists is")
