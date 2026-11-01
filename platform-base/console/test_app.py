import pathlib
import types


MODULE_PATH = pathlib.Path(__file__).with_name("app.py")
app = types.ModuleType("console_app_under_test")
app.__file__ = str(MODULE_PATH)
exec(compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec"), app.__dict__)


def test_redirect_under_pathful_base_maps_to_mount_root():
    location = "/ui/dashboard?mode=compact"

    actual = app._rewrite_location(
        location,
        "http://tool:8080/ui/",
        "http://tool:8080/ui/",
        "tool",
    )

    assert actual == "/a/tool/dashboard?mode=compact"


def test_redirect_under_root_base_keeps_upstream_path():
    actual = app._rewrite_location(
        "/login?next=%2F",
        "http://machine:8080/",
        "http://machine:8080",
        "machine",
    )

    assert actual == "/a/machine/login?next=%2F"


def test_relative_redirect_resolves_from_current_upstream_url():
    actual = app._rewrite_location(
        "next",
        "http://service:8000/base/current",
        "http://service:8000/base/",
        "service",
    )

    assert actual == "/a/service/next"


def test_external_redirect_is_not_rewritten():
    location = "https://accounts.google.com/o/oauth2/auth?client_id=example"

    assert app._rewrite_location(
        location,
        "http://service:8000/",
        "http://service:8000",
        "service",
    ) == location


# ── a remote app through the console's own origin ───────────────────────────────────────────────
REMOTE_TILE = {
    "id": "drive.macbook", "name": "דרייב", "external": True, "host": "drive.macbook",
    "proxy": "/a/drive.macbook/",
    "door": {"base": "http://drive.macbook:9004", "host": "drive.localhost", "user": "owner", "from": ["guest"]},
    "remote": {"office": "macbook", "label": {"he": "המקבוק", "en": "MacBook"}, "alias": "drive"},
}


def test_a_remote_tile_declares_the_door_the_console_proxies_to():
    doors = app._doors_of([REMOTE_TILE, {"id": "drive", "embed": "/a/drive/"},
                           {"id": "x.y", "door": {"base": "http://x.y:1"}}])     # no `remote`: not a remote tile

    assert list(doors) == ["drive.macbook"]
    assert doors["drive.macbook"]["base"] == "http://drive.macbook:9004"
    assert doors["drive.macbook"]["office"] == "המקבוק"


def test_a_remote_app_that_keeps_its_own_host_has_no_door_here():
    own_host = {k: v for k, v in REMOTE_TILE.items() if k not in ("proxy", "door")}

    assert app._doors_of([own_host]) == {}


def test_a_request_to_a_remote_app_carries_the_mapped_identity_and_not_this_offices_session():
    door = app._doors_of([REMOTE_TILE])["drive.macbook"]
    fwd = {"X-authentik-username": "akadmin", "X-Authentik-Email": "a@here", "X-DGO-From": "forged",
           "Cookie": "authentik_proxy_abc=SECRET; theme=dark; authentik_session=ALSO; sid=42",
           "Accept": "text/html"}

    out = app._as_remote(fwd, door)

    assert out["X-authentik-username"] == "owner"          # the serving office's user, not ours
    assert out["X-DGO-From"] == "guest"                    # the link's own value, never the client's
    assert out["Host"] == "drive.localhost"                 # the name the app answers under
    assert out["Cookie"] == "theme=dark; sid=42"           # this office's sign-in does not cross the link
    assert out["X-Authentik-Email"] == "a@here" and out["Accept"] == "text/html"


def test_a_request_with_only_this_offices_session_sends_no_cookie_at_all():
    out = app._as_remote({"cookie": "authentik_proxy_abc=SECRET"}, {"user": "", "host": "", "from": []})

    assert not any(k.lower() == "cookie" for k in out)


def test_the_browser_gets_the_tile_but_not_the_door():
    tile = {k: v for k, v in REMOTE_TILE.items() if k != "door"}

    assert "door" not in tile and tile["proxy"] == "/a/drive.macbook/"
    with app.app.test_request_context():
        app._modules = lambda: [REMOTE_TILE]
        body = app.modules().get_json()
    assert body["modules"] == [tile]


def test_a_page_that_stays_open_can_tell_that_its_tiles_changed_and_only_then():
    own_host = {k: v for k, v in REMOTE_TILE.items() if k not in ("proxy", "door")}
    with app.app.test_request_context():
        app._modules = lambda: [REMOTE_TILE]
        drawn = app.version().get_json()
        app._modules = lambda: [dict(REMOTE_TILE, door={"base": "http://elsewhere:1"})]
        same_for_a_browser = app.version().get_json()     # the door is the server's, never a tile's
        app._modules = lambda: [own_host]
        moved = app.version().get_json()

    assert len(drawn["shell"]) == 12 and drawn["version"]
    assert same_for_a_browser == drawn
    assert moved["registry"] != drawn["registry"] and moved["shell"] == drawn["shell"]


def test_a_linked_office_that_does_not_answer_is_said_in_hebrew_inside_the_frame():
    page = app._remote_asleep({"name": "<b>x</b>", "office": "המקבוק"})

    assert "המקבוק" in page and "הלשכה לא ענתה" in page and 'dir="rtl"' in page
    assert "<b>x</b>" not in page and "<h2>&lt;b&gt;x&lt;/b&gt;</h2>" in page


def test_the_card_in_the_frame_is_the_card_the_shell_draws():
    """A tile with no screen to show was two cards: the shell's (an icon, a centred title, a line that
    says which case this is) for an app it cannot frame, and this module's own for one it can — a
    plain box with rules written here. Side by side in one menu they were two designs (the live map,
    2026-10-07). The frame's card is now written with the shell's own rules, palette and icon, read
    from the files the shell serves; a status code is one click away, not in the sentence."""
    shell = (pathlib.Path(app.STATIC) / "app.js").read_text(encoding="utf-8")
    css = (pathlib.Path(app.STATIC) / "style.css").read_text(encoding="utf-8")
    real = app._modules
    app._modules = lambda: [{"id": "notes", "name": "פתקים"}]
    try:
        asleep = app._remote_asleep({"name": "דרייב", "office": "המקבוק"})
        answered = app._remote_asleep({"name": "דרייב", "office": "המקבוק"}, "הלשכה ענתה בלי האפליקציה.", raw="404")
        no_screen = app._app_no_screen("notes", 401, "who are you")
        silent = app._app_no_screen("notes")
    finally:
        app._modules = real

    rules = css.split("/* @card:start */", 1)[1].split("/* @card:end */", 1)[0]
    alert = shell.split("alert:", 1)[1].split("'", 2)[1]
    for page in (asleep, answered, no_screen, silent):
        # the shell's markup, rules, palette and glyph — the same text, not a likeness of it
        assert '<div class="xn"><div class="xn-card"><span class="xn-ic">' in page and rules in page
        assert "--surface:#fff" in page and "prefers-color-scheme:dark" in page and alert in page
    assert '<div class="xn"><div class="xn-card">' in shell and ".xn-card{" in rules
    # which case this is, on the line under the title — and no status code in what a person reads
    assert '<div class="xn-sub">המקבוק לא זמינה כרגע</div>' in asleep
    assert '<div class="xn-sub">המקבוק · האפליקציה לא זמינה</div>' in answered
    assert '<div class="xn-sub">אין לה מסך להציג</div>' in no_screen and '<div class="xn-sub">האפליקציה לא ענתה</div>' in silent
    said = lambda page: page.split("<p>", 1)[1].split("<details>", 1)[0]          # noqa: E731
    assert "401" not in said(no_screen) and "<pre>401 who are you</pre>" in no_screen
    assert "404" not in said(answered) and "<pre>404</pre>" in answered
    assert "<details>" not in asleep and "<details>" not in silent
    assert 'http-equiv="refresh"' in asleep and 'http-equiv="refresh"' not in no_screen



def test_an_app_of_this_office_with_no_screen_to_show_gets_a_card_and_keeps_its_status():
    """The office agent's harness answers a visitor it does not know with `401 text/plain` and one
    line of English, and that line was the whole tile. A page request gets the card, with the line
    one click away; an API call gets the app's answer as it is; an app that does not answer at all
    gets the card too, where it used to get a JSON error in the frame."""
    class Refusal:
        status_code, is_redirect = 401, False
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        content = b"dsh web authentication required; reopen the URL printed by <dsh> web."

        def iter_content(self, chunk_size=None):
            return iter((self.content,))

        def close(self):
            pass

    def down(*a, **k):
        raise app.requests.ConnectionError("refused")

    real = (app._app_bases, app._modules, app.requests.request)
    app._app_bases = lambda: {"notes": "http://notes:3081"}     # any app: the shell names none
    app._modules = lambda: [{"id": "notes", "name": "פתקים"}]
    try:
        client = app.app.test_client()
        app.requests.request = lambda *a, **k: Refusal()
        page = client.get("/a/notes/", headers={"Accept": "text/html,application/xhtml+xml"})
        call = client.get("/a/notes/api/sessions", headers={"Accept": "application/json"})
        app.requests.request = down
        gone = client.get("/a/notes/", headers={"Accept": "text/html"})
        gone_call = client.get("/a/notes/api/sessions", headers={"Accept": "application/json"})
    finally:
        app._app_bases, app._modules, app.requests.request = real

    text = page.get_data(as_text=True)
    assert page.status_code == 401 and "text/html" in page.content_type and 'dir="rtl"' in text
    assert "פתקים" in text and "לא זיהתה את הכניסה" in text
    assert "&lt;dsh&gt;" in text and "<dsh>" not in text            # its own words, escaped, one click away
    assert call.status_code == 401 and call.get_data(as_text=True).startswith("dsh web")
    assert gone.status_code == 502 and "לא ענתה כרגע" in gone.get_data(as_text=True)
    assert gone_call.status_code == 502 and gone_call.get_json()["error"] == "app_unreachable"


def test_a_linked_office_that_answers_without_the_app_gets_the_card_and_keeps_its_status():
    """The office answered, and for the tile's own page it answered an error with no page of its own
    (the MacBook's browser tile: 404, empty body). The frame was blank. A page request gets the card;
    anything else — an API call, an asset — gets the office's answer as it is."""
    class Answer:
        status_code, is_redirect, headers, content = 404, False, {"Content-Type": "text/plain; charset=utf-8"}, b""

        def iter_content(self, chunk_size=None):
            return iter(())

        def close(self):
            pass

    real = (app._remote_doors, app.requests.request)
    app._remote_doors = lambda: app._doors_of([REMOTE_TILE])
    app.requests.request = lambda *a, **k: Answer()
    try:
        client = app.app.test_client()
        page = client.get("/a/drive.macbook/", headers={"Accept": "text/html,application/xhtml+xml"})
        call = client.get("/a/drive.macbook/api/files", headers={"Accept": "application/json"})
    finally:
        app._remote_doors, app.requests.request = real

    text = page.get_data(as_text=True)
    assert page.status_code == 404 and "text/html" in page.content_type
    assert "המקבוק" in text and "לא זמינה בה כרגע" in text and "404" in text
    assert call.status_code == 404 and "הלשכה" not in call.get_data(as_text=True)


def test_what_the_links_own_door_said_becomes_this_consoles_card():
    """The door of a link answers for itself with `X-Dgo-Door` (and, to a bare browser, a card of its
    own). Behind this console the card is the console's: it names the office, and says which of the
    three things it is. A CALL gets the same sentence as JSON, with the door's status and its word: a
    screen that is already open has something to say other than "the answer is not JSON"."""
    def answer(reason, status):
        class Answer:
            status_code, is_redirect, content = status, False, "<html>the door's own card</html>".encode()
            headers = {"Content-Type": "text/html; charset=utf-8", "X-Dgo-Door": reason}

            def iter_content(self, chunk_size=None):
                return iter((self.content,))

            def close(self):
                pass
        return Answer()

    real = (app._remote_doors, app.requests.request)
    app._remote_doors = lambda: app._doors_of([REMOTE_TILE])
    try:
        client = app.app.test_client()
        seen = {}
        for reason, status in (("app-down", 502), ("no-app", 404), ("unreachable", 502)):
            app.requests.request = lambda *a, _r=reason, _s=status, **k: answer(_r, _s)
            page = client.get("/a/drive.macbook/", headers={"Accept": "text/html"})
            seen[reason] = (page.status_code, page.get_data(as_text=True))
        call = client.get("/a/drive.macbook/api/files", headers={"Accept": "application/json"})
    finally:
        app._remote_doors, app.requests.request = real

    assert seen["app-down"][0] == 502 and "לא עונה בה כרגע" in seen["app-down"][1]
    assert seen["no-app"][0] == 404 and "לא נותנת את האפליקציה" in seen["no-app"][1]
    assert seen["unreachable"][0] == 502 and "הלשכה לא ענתה" in seen["unreachable"][1]
    assert all("המקבוק" in page and "the door's own card" not in page for _s, page in seen.values())
    said = call.get_json()
    assert call.status_code == 502 and said["code"] == "unreachable" and said["office"] == "macbook"
    assert "המקבוק" in said["error"] and "הלשכה לא ענתה" in said["error"] and said["message"] == said["error"]
    assert "the door's own card" not in call.get_data(as_text=True)


def test_a_call_to_an_office_nobody_answered_for_is_told_so_in_json():
    """The request never got through the link at all (the tunnel is down): a page gets the card, and
    a call the same sentence as JSON — it used to get the card too, which no API client can read."""
    def refused(*a, **k):
        raise app.requests.ConnectionError("nobody there")

    real = (app._remote_doors, app.requests.request)
    app._remote_doors, app.requests.request = (lambda: app._doors_of([REMOTE_TILE])), refused
    try:
        client = app.app.test_client()
        page = client.get("/a/drive.macbook/", headers={"Accept": "text/html"})
        call = client.get("/a/drive.macbook/api/files", headers={"Accept": "application/json"})
    finally:
        app._remote_doors, app.requests.request = real
    assert page.status_code == 502 and "text/html" in page.content_type and "המקבוק" in page.get_data(as_text=True)
    assert call.status_code == 502 and call.is_json and "המקבוק" in call.get_json()["error"]


def test_a_linked_office_tile_carries_what_was_measured_about_its_office():
    """`remote.ok` was read by the shell and written by nothing: every tile of an office whose tunnel
    had been dead for fifteen hours looked alive. The link's owner now writes one file, and a tile
    says what it holds — before anything is opened, in the words of the hop that fell — and says
    NOTHING once the file is older than a measurement can be."""
    import json
    import tempfile
    import time

    real = app.PEERS_DIR
    app.PEERS_DIR = tempfile.mkdtemp()
    link = pathlib.Path(app.PEERS_DIR) / "link.json"

    def tiles(at, offices):
        link.write_text(json.dumps({"at": at, "offices": offices}), encoding="utf-8")
        local = {"id": "drive", "embed": "/a/drive/"}
        out = app._judged([dict(REMOTE_TILE), local])
        return out[0]["remote"], out[1]

    try:
        now = time.time()
        down, local = tiles(now, {"macbook": {"ok": False, "hop": "tunnel", "why": "המנהרה נפלה."}})
        up, _ = tiles(now, {"macbook": {"ok": True, "hop": "", "why": ""}})
        unmeasured, _ = tiles(now, {"macbook": {"ok": None, "hop": "", "why": ""}})
        stale, _ = tiles(now - 3600, {"macbook": {"ok": False, "hop": "tunnel", "why": "המנהרה נפלה."}})
        other, _ = tiles(now, {"vps1": {"ok": False, "hop": "office", "why": "הלשכה שותקת."}})
        link.write_text(json.dumps({"at": now, "offices": {"macbook": {"ok": False, "hop": "office", "why": "הלשכה שותקת."}}}),
                        encoding="utf-8")
        card = app._remote_asleep({"name": "דרייב", "office": "המקבוק", "oid": "macbook"})
        answered = app._remote_asleep({"name": "דרייב", "office": "המקבוק", "oid": "macbook"}, "הלשכה ענתה (404).")
    finally:
        app.PEERS_DIR = real

    assert down["ok"] is False and down["why"] == "המנהרה נפלה." and down["label"] == REMOTE_TILE["remote"]["label"]
    assert up["ok"] is True and "why" not in up
    assert "ok" not in unmeasured and "ok" not in stale and "ok" not in other
    assert local == {"id": "drive", "embed": "/a/drive/"}                # a local tile is never judged
    assert "ok" not in REMOTE_TILE["remote"]                             # …and the registry's own entry is not written on
    assert "הלשכה שותקת." in card and 'http-equiv="refresh"' in card             # the link's words, as given
    assert "הלשכה ענתה (404)." in answered and "הלשכה שותקת." not in answered
