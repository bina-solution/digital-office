"""test_language — the console reads the office's language and tells every framed app (DGO-971).

    python -m pytest platform-base/console/test_language.py -q      (in the console's image: it needs Flask)

.generated/registry/locale.json is compiled from `language:` in platform.state.yaml (reconcile.py and its Go
twin). What is held here:
  * GET /api/language answers the compiled document, and the fallback (Hebrew, rtl) when there is none;
  * a changed file is read again with no restart, and a half-written or malformed one keeps the last good one;
  * every HTML page the console frames carries <meta name="bina-lang"> with the code and its direction, before
    </head>, and a JSON answer is untouched;
  * a document whose code or direction is not one is never written into a page.
"""
import json
import os
import pathlib
import tempfile
import types

MODULE_PATH = pathlib.Path(__file__).with_name("app.py")
app = types.ModuleType("console_app_language_under_test")
app.__file__ = str(MODULE_PATH)
exec(compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec"), app.__dict__)


def owner_client():
    """The console's test client as the office's owner: switching the office's language is the admins' (DGO-1755)."""
    c = app.app.test_client()
    c.environ_base.update({"HTTP_X_AUTHENTIK_USERNAME": "owner", "HTTP_X_AUTHENTIK_GROUPS": "admins"})
    return c


EN = {"active": "en", "default": "en", "dir": "ltr",
      "available": [{"code": "he", "label": "עברית", "label_en": "Hebrew", "dir": "rtl"},
                    {"code": "en", "label": "English", "label_en": "English", "dir": "ltr"}]}


def _at(path):
    app._LOCALE_FILE = str(path)
    app._LOCALE_SEEN.update(mtime=None, doc=app._LOCALE_FALLBACK)


def _write(path, text, tick):
    path.write_text(text, encoding="utf-8")
    os.utime(path, (tick, tick))                 # a new mtime each time, as a render makes one


def test_no_file_is_hebrew_and_the_api_says_so():
    _at(pathlib.Path(tempfile.mkdtemp()) / "locale.json")
    r = app.app.test_client().get("/api/language")
    assert r.status_code == 200 and r.get_json() == app._LOCALE_FALLBACK
    assert app._lang_meta() == '<meta name="bina-lang" content="he" data-dir="rtl">'


def test_a_switch_is_read_with_no_restart_and_a_broken_file_keeps_the_last_good_one():
    f = pathlib.Path(tempfile.mkdtemp()) / "locale.json"
    _at(f)
    _write(f, json.dumps(EN, ensure_ascii=False), 1_000)
    assert app.app.test_client().get("/api/language").get_json() == EN
    _write(f, '{"active": "en", "dir": ', 2_000)                       # half-written
    assert app._locale() == EN
    _write(f, json.dumps({"active": '"><script>', "dir": "ltr"}), 3_000)  # not a code: never in a page
    assert app._locale() == EN
    _write(f, json.dumps({"active": "he", "dir": "sideways"}), 4_000)
    assert app._locale() == EN
    _write(f, json.dumps({**EN, "active": "he", "default": "he", "dir": "rtl"}), 5_000)
    assert app._locale()["active"] == "he"


class _Page:
    is_redirect = False

    def __init__(self, body, ctype):
        self.status_code, self.content = 200, body
        self.headers = {"Content-Type": ctype}

    def iter_content(self, chunk_size=None):
        return iter((self.content,))

    def close(self):
        pass


def test_every_framed_page_learns_the_language_and_json_is_untouched():
    f = pathlib.Path(tempfile.mkdtemp()) / "locale.json"
    _at(f)
    _write(f, json.dumps(EN, ensure_ascii=False), 6_000)
    real = (app._app_bases, app._modules, app.requests.request)
    app._app_bases = lambda: {"tool": "http://tool:8080"}
    app._modules = lambda: [{"id": "tool", "name": "כלי"}]
    answers = {"/": _Page(b"<!doctype html><html><head><title>t</title></head><body>x</body></html>",
                          "text/html; charset=utf-8"),
               "/api/x": _Page(b'{"ok": true}', "application/json")}
    app.requests.request = lambda method, url, **k: answers["/" + url.split(":8080/", 1)[1]]
    try:
        c = app.app.test_client()
        page = c.get("/a/tool/", headers={"Accept": "text/html"}).get_data(as_text=True)
        data = c.get("/a/tool/api/x", headers={"Accept": "application/json"}).get_data(as_text=True)
    finally:
        app._app_bases, app._modules, app.requests.request = real
    meta = '<meta name="bina-lang" content="en" data-dir="ltr">'
    assert page.count(meta) == 1 and page.index(meta) < page.lower().index("</head>"), page
    assert page.lower().startswith("<!doctype html>"), page          # never before the doctype: quirks mode
    assert data == '{"ok": true}'


def test_the_meta_is_first_in_head_and_never_before_the_doctype():
    """The second reader of DGO-971: connections' ui.html has no <head>, and a meta put in front of its doctype
    turns the page to quirks mode; a script in <head> reads the meta once, so the meta comes first."""
    doc = EN
    meta = '<meta name="bina-lang" content="en" data-dir="ltr">'
    shapes = {
        # connections' own shape: a doctype, <html>, no <head> or </head>
        "no head": '<!doctype html>\n<html lang="he" dir="rtl">\n<meta charset="utf-8"/>\n<title>t</title><body>x',
        "a script in head": '<!DOCTYPE html><html><head><script src="bina-lang.js"></script></head><body></body></html>',
        "a doctype only": "<!doctype html><title>t</title><p>x",
        "a fragment": "<p>x</p>",
        "an İ before it": '<!doctype html><html><head><title>İİİİ</title></head><body>x</body></html>',
    }
    for name, html in shapes.items():
        out = app._inject_lang(html, doc)
        assert out.count(meta) == 1, (name, out)
        if html.lower().startswith("<!doctype"):
            assert out.lower().startswith("<!doctype html>"), (name, out)
        if "<script" in html:
            assert out.index(meta) < out.index("<script"), (name, out)
        if "<head>" in html:
            assert out.index(meta) == html.index("<head>") + len("<head>"), (name, out)
    connections = pathlib.Path(__file__).resolve().parents[1] / "connections" / "ui.html"
    if connections.is_file():
        out = app._inject_lang(app._inject_base(connections.read_text(encoding="utf-8"), "/a/connections/"), doc)
        assert out.lower().startswith("<!doctype html>") and out.count(meta) == 1


def test_a_switch_goes_to_the_control_plane_with_the_link_header_and_its_answer_comes_back():
    """POST /api/language is the control plane's write; the console only carries it. The link's header goes
    with it (a linked office is refused there), the body says the console asked, and the plane's answer —
    a refusal included — comes back as it is."""
    sent = []

    class Answer:
        def __init__(self, status, body):
            self.status_code, self.content = status, json.dumps(body).encode()
            self.headers = {"Content-Type": "application/json"}

    def post(url, data=None, headers=None, timeout=None):
        sent.append((url, json.loads(data), dict(headers)))
        lang = json.loads(data)["lang"]
        return Answer(200, {"ok": True, **EN}) if lang == "en" else \
            Answer(400, {"ok": False, "error": "unknown_language", "lang": lang})

    real = app.requests.post
    app.requests.post = post
    try:
        c = owner_client()
        ok = c.post("/api/language", json={"lang": "en", "by": "someone-else"})
        bad = c.post("/api/language", json={"lang": "eng"})
        linked = c.post("/api/language", json={"lang": "en"}, headers={"X-DGO-Office": "macbook"})
    finally:
        app.requests.post = real
    assert ok.status_code == 200 and ok.get_json()["active"] == "en"
    assert bad.status_code == 400 and bad.get_json()["error"] == "unknown_language"
    assert [s[0] for s in sent] == [app.APP_MANAGEMENT_URL + "/api/language"] * 3
    assert sent[0][1] == {"lang": "en", "by": "console"}                        # the console, not the body's word
    assert sent[2][2].get("X-Dgo-Office", sent[2][2].get("X-DGO-Office")) == "macbook"
    assert linked.status_code == 200      # the fake plane does not refuse; the real one does (G85, api_language_set)


def test_a_body_that_is_no_switch_is_answered_here_and_never_handed_on():
    """The second reader of slice 4: a JSON body that is not an object answered 500 here (`.get` on a list), and
    a code of any length was handed to the plane. Both are a 400 from the console, and the plane is not asked."""
    sent = []

    def post(*a, **k):
        sent.append(a)
        raise AssertionError("the plane was asked")
    real = app.requests.post
    app.requests.post = post
    try:
        c = owner_client()
        answers = [c.post("/api/language", data=json.dumps(b), content_type="application/json") for b in (["en"], "en", 3)]
        long = c.post("/api/language", json={"lang": "e" * 41})
    finally:
        app.requests.post = real
    assert [a.status_code for a in answers] == [400, 400, 400], [(a.status_code, a.get_json()) for a in answers]
    assert long.status_code == 400 and long.get_json()["error"] == "unknown_language", long.get_json()
    assert sent == []


def test_a_plane_that_is_down_is_said():
    def down(*a, **k):
        raise app.requests.ConnectionError("refused")
    real = app.requests.post
    app.requests.post = down
    try:
        r = owner_client().post("/api/language", json={"lang": "en"})
    finally:
        app.requests.post = real
    assert r.status_code == 502 and r.get_json()["error"] == "control_plane_unreachable"
