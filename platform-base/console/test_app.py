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
def owner_client():
    """The console's test client as the office's owner: a linked office's door is the office's admins' (DGO-1755),
    so a test of what that door does goes through it as one."""
    c = app.app.test_client()
    c.environ_base.update({"HTTP_X_AUTHENTIK_USERNAME": "owner", "HTTP_X_AUTHENTIK_GROUPS": "admins"})
    return c


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


def test_forward_auths_session_and_state_do_not_cross_the_link_either():
    # DGO-1090: on a forward-auth office the sign-in is dgo_session (and, mid sign-in, dgo_state)
    out = app._as_remote({"Cookie": "dgo_session=SECRET; theme=dark; dgo_state=ALSO; dgo_sessionx=1"},
                         {"user": "", "host": "", "from": []})

    assert out["Cookie"] == "theme=dark; dgo_sessionx=1"    # only the exact names, nothing that merely starts so


def test_the_browser_gets_the_tile_but_not_the_door():
    tile = {k: v for k, v in REMOTE_TILE.items() if k != "door"}

    assert "door" not in tile and tile["proxy"] == "/a/drive.macbook/"
    with app.app.test_request_context():
        app._modules = lambda: [REMOTE_TILE]
        body = app.modules().get_json()
    assert body["modules"] == [tile]


# ── a person needed in another app's screen (DGO-1336) ──────────────────────────────────────────
BROWSER_TILE = {"id": "browser42.hp-laptop", "external": True, "host": "browser42.hp-laptop",
                "handoffs": "http://browser42.hp-laptop:8766/v1/handoffs",
                "remote": {"office": "hp-laptop", "alias": "browser42", "module_id": "browser42"}}
CLAUDE_TILE = {"id": "bina-claude.hp-laptop", "external": True, "host": "bina-claude.hp-laptop",
               "remote": {"office": "hp-laptop", "alias": "bina-claude", "module_id": "bina-claude"}}
LOCAL_CLAUDE = {"id": "bina-claude", "alias": "bina-claude", "embed": "/a/bina-claude/"}


def test_a_hand_off_is_placed_on_the_tile_of_the_app_that_asked_in_the_same_office():
    asked = []

    def ask(address):
        asked.append(address)
        return [{"slug": "claude-signin", "for": "bina-claude", "state": "needed", "sentence": "בחרו חשבון",
                 "id": "e1", "updated_at": 5, "url": "https://claude.com/x?hop_nonce=leak"}]

    out = app.handoffs_for([LOCAL_CLAUDE, BROWSER_TILE, CLAUDE_TILE], ask=ask, now=9)
    assert asked == ["http://browser42.hp-laptop:8766/v1/handoffs"]
    # the HP's browser asked for the HP's Claude — never this office's own app of the same name
    assert out == [{"at": "browser42.hp-laptop", "for": "bina-claude.hp-laptop", "app": "bina-claude",
                    "slug": "claude-signin", "state": "needed", "sentence": "בחרו חשבון", "id": "e1", "age": 4}]
    assert "leak" not in str(out), "a record's other fields never reach the shell"


def test_a_hand_off_for_an_app_this_office_does_not_show_names_no_tile_and_a_tile_without_a_list_is_not_asked():
    asked = []
    out = app.handoffs_for([BROWSER_TILE, LOCAL_CLAUDE, {"id": "x", "handoffs": "file:///etc/passwd"}],
                           ask=lambda a: asked.append(a) or [{"slug": "s", "for": "bina-claude", "state": "needed", "id": "e"}])
    assert [h["for"] for h in out] == [""]
    assert asked == ["http://browser42.hp-laptop:8766/v1/handoffs"]


def test_what_a_linked_office_answers_is_data_never_an_address_of_the_shell():
    """A slug steers the shell's hash (`#/m/<tile>/handoff/<slug>`): one that is not a slug is dropped."""
    bad = [{"slug": "../../m/x", "for": "bina-claude", "state": "needed", "id": "e1"},
           {"slug": "ok", "for": "bina-claude", "state": "pwned", "id": "e2"},
           {"slug": "ok", "for": "bina-claude", "state": "needed", "id": "x/../y"},
           {"slug": "ok", "for": "bina-claude", "state": "failed", "id": "e3", "sentence": "x" * 900}]
    out = app.handoffs_for([BROWSER_TILE, CLAUDE_TILE], ask=lambda a: bad)
    assert [(h["id"], len(h["sentence"])) for h in out] == [("e3", 300)]


def test_the_browser_never_gets_where_the_server_asks():
    with app.app.test_request_context():
        app._modules = lambda: [BROWSER_TILE, CLAUDE_TILE]
        app._HANDOFF_TILES["key"] = None
        body = app.modules().get_json()
        real = app._handoffs_of
        app._handoffs_of = lambda address: [{"slug": "claude-signin", "for": "bina-claude", "state": "done", "id": "e1"}]
        try:
            listed = app.handoffs().get_json()
        finally:
            app._handoffs_of = real
            app._HANDOFF_TILES["key"] = None
    assert "handoffs" not in body["modules"][0]
    assert listed["handoffs"][0]["for"] == "bina-claude.hp-laptop" and listed["handoffs"][0]["state"] == "done"


def test_an_app_that_does_not_answer_is_not_asked_again_at_once_and_keeps_its_last_good_answer():
    calls, up = [], {"ok": True}

    class Answer:
        ok = True

        @staticmethod
        def json():
            return {"handoffs": [{"slug": "claude-signin", "state": "needed", "id": "e1"}]}

    def get(*args, **kwargs):
        calls.append(args)
        if not up["ok"]:
            raise app.requests.ConnectionError("the link is down")
        return Answer()

    real, clock = (app.requests.get, app.time.time), [1000.0]
    app.requests.get, app.time.time = get, (lambda: clock[0])
    try:
        app._HANDOFFS_SEEN.clear()
        address = "http://x.office:8766/v1/handoffs"
        assert [h["id"] for h in app._handoffs_of(address)] == ["e1"]
        up["ok"] = False
        clock[0] += app.HANDOFFS_FRESH_S + 0.1
        assert [h["id"] for h in app._handoffs_of(address)] == ["e1"], "a moment's silence is not «it is gone»"
        clock[0] += 1
        app._handoffs_of(address)
        assert len(calls) == 2, "a fallen link is not asked again at once"
    finally:
        app.requests.get, app.time.time = real
        app._HANDOFFS_SEEN.clear()


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


def test_an_error_the_app_means_is_passed_on_as_it_is_and_any_other_404_still_falls_back():
    """DGO-1591, measured on Exampleu: under `/a/sites/public/<id>/`, a page the site does not have was
    answered by the history fallback with the Sites app's own entry page, 200, inside the site's frame.
    An app that MEANS its 404 says so (`X-Bina-Final: 1`): the console passes that answer on as it is —
    no fallback, no card. A 404 the app does not mark still falls back, as every SPA's deep link needs."""
    calls = []

    class Upstream:
        is_redirect = False

        def __init__(self, url):
            root = url.endswith(":8080/")                     # the app's entry page; anything else is missing
            self.status_code = 200 if root else 404
            self.headers = ({"Content-Type": "text/html; charset=utf-8"} if root else
                            {"Content-Type": "text/plain; charset=utf-8", **MARK})
            self.content = b"<title>\xd7\x90\xd7\xaa\xd7\xa8\xd7\x99\xd7\x9d</title>app" if root else b"Not Found"

        def iter_content(self, chunk_size=None):
            return iter((self.content,))

        def close(self):
            pass

    def fake(method, url, **k):
        calls.append(url)
        return Upstream(url)

    page = {"Accept": "text/html,application/xhtml+xml"}
    real = (app._app_bases, app._modules, app.requests.request)
    app._app_bases = lambda: {"tool": "http://tool:8080"}     # any app that serves pages it does not own
    app._modules = lambda: [{"id": "tool", "name": "כלי"}]
    app.requests.request = fake
    try:
        client = app.app.test_client()
        MARK = {"X-Bina-Final": "1"}
        meant = client.get("/a/tool/public/exampleu/no-such-page", headers=page)
        meant_calls, calls[:] = list(calls), []
        MARK = {}
        unmarked = client.get("/a/tool/public/exampleu/no-such-page", headers=page)
    finally:
        app._app_bases, app._modules, app.requests.request = real

    assert meant.status_code == 404 and meant.get_data() == b"Not Found", (meant.status_code, meant.get_data()[:80])
    assert "X-Bina-History-Fallback" not in meant.headers and len(meant_calls) == 1     # the root was never asked
    assert unmarked.status_code == 200 and unmarked.headers.get("X-Bina-History-Fallback") == "1"
    assert len(calls) == 2 and calls[1].endswith("/")                                     # …and the root was


def test_an_error_a_linked_offices_app_means_is_passed_on_as_it_is_too():
    """The same mark through a linked office's door: a site served by another office answers its missing page
    marked final, and the frame shows that answer, not «the app is not available there»."""
    class Answer:
        status_code, is_redirect, content = 404, False, b"Not Found"
        headers = {"Content-Type": "text/plain; charset=utf-8", "X-Bina-Final": "1"}

        def iter_content(self, chunk_size=None):
            return iter((self.content,))

        def close(self):
            pass

    real = (app._remote_doors, app.requests.request)
    app._remote_doors = lambda: app._doors_of([REMOTE_TILE])
    app.requests.request = lambda *a, **k: Answer()
    try:
        page = owner_client().get("/a/drive.macbook/public/x/no-such-page",
                                  headers={"Accept": "text/html,application/xhtml+xml"})
    finally:
        app._remote_doors, app.requests.request = real
    assert page.status_code == 404 and page.get_data() == b"Not Found", (page.status_code, page.get_data()[:80])


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
        client = owner_client()
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
        client = owner_client()
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
        client = owner_client()
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


# ── #63: an app that refuses to be framed is said so, never a dead window ─────────────────────────
def _verdict(headers, console="https://console.office.example", app_origin="https://svc.office.example"):
    return app.frame_verdict(headers, console, app_origin)


def test_x_frame_options_deny_is_refused_and_says_which_header():
    v, why = _verdict({"X-Frame-Options": "DENY"})
    assert v == "refused" and "X-Frame-Options: DENY" in why


def test_sameorigin_is_refused_for_another_host_and_allowed_for_the_same_origin():
    assert _verdict({"X-Frame-Options": "SAMEORIGIN"})[0] == "refused"
    assert _verdict({"X-Frame-Options": "SAMEORIGIN"}, app_origin="https://console.office.example")[0] == "ok"


def test_frame_ancestors_naming_the_console_wins_over_x_frame_options():
    h = {"X-Frame-Options": "DENY",
         "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self' https://console.office.example"}
    assert _verdict(h)[0] == "ok"


def test_frame_ancestors_none_or_self_only_is_refused():
    assert _verdict({"Content-Security-Policy": "frame-ancestors 'none'"})[0] == "refused"
    assert _verdict({"Content-Security-Policy": "frame-ancestors 'self'"})[0] == "refused"


def test_frame_ancestors_wildcards_and_schemes_match_like_a_browser():
    assert _verdict({"Content-Security-Policy": "frame-ancestors https://*.office.example"})[0] == "ok"
    assert _verdict({"Content-Security-Policy": "frame-ancestors https:"})[0] == "ok"
    assert _verdict({"Content-Security-Policy": "frame-ancestors https://*.elsewhere.example"})[0] == "refused"
    assert _verdict({"Content-Security-Policy": "frame-ancestors http://console.office.example"})[0] == "refused"


def test_no_header_at_all_frames_as_before():
    assert _verdict({}) == ("ok", "")


def test_the_check_asks_only_hosts_of_this_offices_domain():
    client = app.app.test_client()
    r = client.get("/api/frame-check?url=http://169.254.169.254/latest", base_url="https://console.office.example")
    assert r.status_code == 400 and r.get_json()["verdict"] == "unknown"
    r = client.get("/api/frame-check?url=file:///etc/passwd", base_url="https://console.office.example")
    assert r.status_code == 400


def test_the_check_reports_a_refusing_app_and_an_unreachable_one_as_unknown():
    class Resp:
        def __init__(self, headers):
            self.headers, self.status_code, self.url = headers, 200, "https://svc.office.example/"
        def close(self):
            pass
    calls = []
    def fake_get(url, **kw):
        calls.append(url)
        if "down" in url:
            raise app.requests.ConnectionError("no route")
        return Resp({"X-Frame-Options": "DENY"})
    real = app.requests.get
    app.requests.get = fake_get
    app._frame_seen.clear()
    try:
        client = app.app.test_client()
        r = client.get("/api/frame-check?url=https://svc.office.example/", base_url="https://console.office.example")
        assert r.get_json()["verdict"] == "refused"
        client.get("/api/frame-check?url=https://svc.office.example/", base_url="https://console.office.example")
        assert len(calls) == 1                                  # asked once, then remembered
        r = client.get("/api/frame-check?url=https://down.office.example/", base_url="https://console.office.example")
        assert r.get_json()["verdict"] == "unknown"
    finally:
        app.requests.get = real


def _frame_check_against(answers, url):
    """GET /api/frame-check?url=… with every hop answered from `answers` ({url: (status, headers)});
    returns (the JSON verdict, the URLs that were asked)."""
    class Resp:
        def __init__(self, status, headers):
            self.status_code, self.headers = status, headers
        def close(self):
            pass
    asked = []
    def fake_get(u, **kw):
        assert kw.get("allow_redirects") is False          # every hop is judged here, never by requests
        asked.append(u)
        return Resp(*answers[u])
    real = app.requests.get
    app.requests.get = fake_get
    app._frame_seen.clear()
    try:
        r = app.app.test_client().get("/api/frame-check?url=" + url, base_url="https://console.office.example")
        return r.get_json(), asked
    finally:
        app.requests.get = real


def test_an_app_behind_the_sign_in_is_not_judged_by_the_sign_in_page():
    """DGO-1502 (Exampleu, 2026-11-09): this request carries nobody's sign-in, so Meet's own host answered
    302 → signin.<domain>/login, whose page refuses every frame (X-Frame-Options: DENY). Followed to
    the end that was "refused" for Meet, Plane and Obsidian alike, and the desktop's next open of Meet
    went to a new tab. The browser passes that door with its own session: the verdict is unknown."""
    login = "https://signin.office.example/login?rd=https%3A%2F%2Fmeet-start.office.example%2F"
    out, asked = _frame_check_against({
        "https://meet-start.office.example/": (302, {"Location": login}),
        login: (200, {"X-Frame-Options": "DENY"}),
    }, "https://meet-start.office.example/")
    assert out["verdict"] == "unknown" and "signin.office.example" in out["why"]
    assert asked == ["https://meet-start.office.example/"]      # the sign-in page is never fetched


def test_a_redirect_on_the_apps_own_origin_is_followed_and_judged():
    out, asked = _frame_check_against({
        "https://svc.office.example/": (302, {"location": "/signin"}),
        "https://svc.office.example/signin": (200, {"X-Frame-Options": "SAMEORIGIN"}),
    }, "https://svc.office.example/")
    assert out["verdict"] == "refused" and "SAMEORIGIN" in out["why"]
    assert asked == ["https://svc.office.example/", "https://svc.office.example/signin"]


def test_a_redirect_out_of_the_office_is_not_followed():
    out, asked = _frame_check_against({
        "https://svc.office.example/": (307, {"Location": "http://169.254.169.254/latest/meta-data"}),
    }, "https://svc.office.example/")
    assert out["verdict"] == "unknown" and asked == ["https://svc.office.example/"]


def test_the_same_origin_written_two_ways_is_one_origin_and_a_broken_location_is_unknown():
    out, asked = _frame_check_against({
        "https://Svc.office.example/": (302, {"Location": "https://svc.office.example:443/in"}),
        "https://svc.office.example:443/in": (200, {"X-Frame-Options": "DENY"}),
    }, "https://Svc.office.example/")
    assert out["verdict"] == "refused" and len(asked) == 2
    out, _ = _frame_check_against({"https://svc.office.example/": (302, {"Location": "http://[::1/x"})},
                                  "https://svc.office.example/")
    assert out["verdict"] == "unknown"                         # not a 500 with a traceback


def test_a_redirect_that_never_ends_is_unknown():
    loop = {"https://svc.office.example/a": (302, {"Location": "/b"}),
            "https://svc.office.example/b": (302, {"Location": "/a"})}
    out, asked = _frame_check_against(loop, "https://svc.office.example/a")
    assert out["verdict"] == "unknown" and len(asked) == app.FRAME_CHECK_HOPS + 1


def test_a_large_download_passes_through_in_bounded_pieces():
    """DGO-1231: a meeting's mp4 (297 MB) served through /a/meet/recordings OOM-killed this worker at
    its 256M limit, because `iter_content(chunk_size=None)` makes urllib3 read a body that has a
    Content-Length in ONE `read(None)`. Measured with the real `requests` against a real server: the
    first piece the proxy hands on is at most PASS_CHUNK, and the whole body still arrives intact."""
    import http.server
    import threading

    body = bytes(range(256)) * (16 * 1024)                     # 4 MiB, sent with a Content-Length

    class Upstream(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    real = app._app_bases
    app._app_bases = lambda: {"rec": f"http://127.0.0.1:{server.server_address[1]}"}
    try:
        client = app.app.test_client()
        first = client.get("/a/rec/meeting.mp4", headers={"Accept": "*/*"}, buffered=False)
        pieces = iter(first.response)
        head = next(pieces)
        first.close()
        whole = client.get("/a/rec/meeting.mp4", headers={"Accept": "*/*"})
    finally:
        app._app_bases = real
        server.shutdown()
        server.server_close()

    assert first.status_code == 200 and 0 < len(head) <= 256 * 1024, f"first piece {len(head)} bytes"
    assert len(head) <= app.PASS_CHUNK
    assert whole.status_code == 200 and whole.get_data() == body


def test_a_peer_file_that_is_not_an_object_is_skipped_and_the_rail_stands():
    """DGO-611: `.get` on a peer file holding a JSON list raised in _peer_entries, and /api/modules answered 500 —
    no tiles at all, for one malformed file. A list or a scalar is no placement: skipped, the rest stands."""
    import json
    import tempfile
    real = app.PEERS_DIR
    app.PEERS_DIR = tempfile.mkdtemp()
    try:
        peers = pathlib.Path(app.PEERS_DIR)
        (peers / "a-list.json").write_text("[1, 2]", encoding="utf-8")
        (peers / "b-scalar.json").write_text('"a placement"', encoding="utf-8")
        (peers / "c-good.json").write_text(json.dumps(
            {"alias": "files", "office": "vps1", "module": {"id": "files.vps1", "name": "קבצים"}}), encoding="utf-8")
        assert [e["alias"] for e in app._peer_entries()] == ["files"]
        assert app.app.test_client().get("/api/modules").status_code == 200
    finally:
        app.PEERS_DIR = real


def test_a_compressed_shell_file_revalidates_with_the_etag_it_was_given():
    """DGO-611: flask-compress answers a STREAMED response conditionally on the ETag it writes only for the endpoints
    COMPRESS_STREAMING_ENDPOINT_CONDITIONAL names, and the shell is served by `spa`, not "static" — so a reload sent
    the whole compressed file again for the very ETag the browser held (measured: 200, 61,619 bytes)."""
    c = app.app.test_client()
    first = c.get("/app.js", headers={"Accept-Encoding": "deflate"})
    etag = first.headers.get("ETag", "")
    assert first.status_code == 200 and first.headers.get("Content-Encoding") == "deflate" and etag.endswith(':deflate"')
    again = c.get("/app.js", headers={"Accept-Encoding": "deflate", "If-None-Match": etag,
                                      "If-Modified-Since": first.headers["Last-Modified"]})
    assert again.status_code == 304 and not again.get_data()
    assert again.headers.get("ETag") == etag and "Content-Encoding" not in again.headers
    other = c.get("/app.js", headers={"Accept-Encoding": "deflate", "If-None-Match": '"other:deflate"'})
    assert other.status_code == 200 and other.headers.get("Content-Encoding") == "deflate" and other.get_data()
    plain = c.get("/app.js", headers={"Accept-Encoding": "identity", "If-None-Match": etag.replace(":deflate", "")})
    assert plain.status_code == 304, "the uncompressed file revalidated before, and still does"


def test_only_the_shells_own_files_are_made_conditional_after_compression():
    """…and nothing else `spa` hands back: what an app answers through it (app_proxy) is passed on as it streams —
    a compressed stream made conditional is buffered whole first (second reader, DGO-611)."""
    from flask import Response, g
    for shell, want in ((False, 200), (True, 304)):
        with app.app.test_request_context("/x.json", headers={"If-None-Match": '"e:deflate"'}):
            if shell:
                g.shell_file = True
            resp = Response(iter([b"{}"]), mimetype="application/json", headers={"Content-Encoding": "deflate"})
            resp.set_etag("e:deflate")
            assert app._shell_file_revalidates(resp).status_code == want


def test_a_signin_header_is_forwarded_only_when_traefik_or_the_door_wrote_it():
    # DGO-1304: the console forwarded any caller's X-authentik-* headers, so a container calling it directly
    # became a PERSON to the app behind it (computers: root on the fleet). From traefik it stays; from
    # anywhere else it is dropped — and nothing else is touched.
    real = app._signin_hops
    app._signin_hops = lambda: {"172.18.0.27"}
    try:
        for addr, kept in (("172.18.0.27", True), ("172.18.0.99", False)):
            fwd = {"X-authentik-username": "owner", "X-Authentik-Groups": "admins", "Accept": "*/*"}
            with app.app.test_request_context("/a/computers/api/computers/x/exec", method="POST",
                                              environ_base={"REMOTE_ADDR": addr}):
                app._drop_unproved_signin(fwd)
            assert ("X-authentik-username" in fwd) is kept and ("X-Authentik-Groups" in fwd) is kept, (addr, fwd)
            assert fwd["Accept"] == "*/*"
    finally:
        app._signin_hops = real


def test_an_admins_door_opened_on_an_unproved_groups_header_is_named_and_still_opened():
    # DGO-1813, stage one (AGENTS rule 8): `_is_admin()` believed `X-authentik-groups` from any container. It still
    # does — three QA tools open admins' doors that way — but each such belief is NAMED, once per door and caller
    # per ten minutes, so every office lists who still relies on it before stage two refuses it. A proved one
    # (traefik, the door, the link builder) and a non-admin header are never named.
    import logging
    said = []

    class Catch(logging.Handler):
        def emit(self, record):
            said.append(record.getMessage())
    catch = Catch(level=logging.WARNING)
    app.app.logger.addHandler(catch)
    real = app._signin_hops
    app._signin_hops = lambda: {"172.18.0.27"}
    app._UNPROVED_ADMIN_SAID.clear()
    try:
        def ask(path, addr, groups="authentik Admins", environ=None):
            with app.app.test_request_context(path, headers={"X-authentik-groups": groups},
                                              environ_base={"REMOTE_ADDR": addr, **(environ or {})}):
                return app._is_admin()
        assert ask("/a/computers/api/x", "172.18.0.27") is True and said == [], "traefik wrote it: proved, unnamed"
        assert ask("/a/computers/api/x", "172.18.0.99") is True, "stage one: still believed"
        assert len(said) == 1 and said[0].startswith(
            "console-unproved-admin: 'GET' '/a/computers/' caller='172.18.0.99'") and "hops=1" in said[0], said
        assert ask("/a/computers/api/y", "172.18.0.99") is True and len(said) == 1, "the same door and caller: once"
        assert ask("/api/connections", "172.18.0.99") is True and len(said) == 2 and "'/api/connections'" in said[1]
        assert ask("/a/connections/", "172.18.0.98") is True and len(said) == 3, "another caller is named too"
        assert ask("/a/chat/", "127.0.0.1", environ={app._LINK_BUILDER_MARK: True}) is True and len(said) == 3
        assert ask("/a/computers/", "172.18.0.97", groups="people") is False and len(said) == 3
        # the DOOR is named, never the caller's path: a token in it, a newline, a thousand ids are one key, one line
        for tail in ("broker/redeem/SECRETTOKEN123", "x%0Aconsole-unproved-admin: forged", *[f"id{i}" for i in range(50)]):
            ask(f"/api/conn/{tail}", "172.18.0.96")
        assert len(said) == 4 and "'/api/conn/'" in said[3] and "SECRETTOKEN123" not in said[3] and "forged" not in said[3]
        assert "authentik Admins" not in "".join(said), "no header value is named"
        # bounded: a forger varying its address does not grow the console without end
        for i in range(400):
            ask("/api/language", f"10.0.{i // 250}.{i % 250}")
        assert len(app._UNPROVED_ADMIN_SAID) <= 256
        # through the real gate (before_request), not only the function: an admins' path from an unproved caller
        said.clear()
        app._UNPROVED_ADMIN_SAID.clear()
        app.app.test_client().get("/api/conn/anything", headers={"X-authentik-groups": "admins"},
                                  environ_base={"REMOTE_ADDR": "172.18.0.95"})
        assert len(said) == 1 and "'/api/conn/'" in said[0] and "caller='172.18.0.95'" in said[0], said
        # and with no sign-in hop resolving at all, the line says so — stage two never reads such an office as clean
        said.clear()
        app._UNPROVED_ADMIN_SAID.clear()
        app._signin_hops = lambda: set()
        ask("/a/computers/", "172.18.0.27")
        assert len(said) == 1 and "hops=0" in said[0] and "NO sign-in hop resolves here" in said[0], said
    finally:
        app._signin_hops = real
        app.app.logger.removeHandler(catch)
        app._UNPROVED_ADMIN_SAID.clear()
    # and the forwarding takes the same proof: one function, not two copies of the rule
    src = (pathlib.Path(app.__file__)).read_text(encoding="utf-8")
    for fn in ("def _drop_unproved_signin(", "def _is_admin("):
        body = src[src.index(fn):src.index("\ndef ", src.index(fn) + 5)]
        assert "_signin_proved()" in body, fn


def test_the_link_builders_own_request_keeps_the_identity_it_is_asked_as():
    # DGO-1792: `_frame_answer` asks the frame in-process (test_client, REMOTE_ADDR 127.0.0.1) as a named admin,
    # and the DGO-1304 rule dropped those headers — every identity-gated app behind /a/ saw an anonymous check.
    # Only the WSGI mark keeps them; a header of any spelling, or loopback alone, does not.
    real = app._signin_hops
    app._signin_hops = lambda: {"172.18.0.27"}
    try:
        cases = (({"REMOTE_ADDR": "127.0.0.1", app._LINK_BUILDER_MARK: True}, {}, True),
                 ({"REMOTE_ADDR": "127.0.0.1"}, {}, False),
                 ({"REMOTE_ADDR": "172.18.0.99"}, {"Dgo.Console.Link-Builder": "1"}, False),
                 ({"REMOTE_ADDR": "172.18.0.99", "HTTP_DGO_CONSOLE_LINK_BUILDER": "1"}, {}, False),
                 ({"REMOTE_ADDR": "172.18.0.99", app._LINK_BUILDER_MARK: "1"}, {}, False))
        for environ, headers, kept in cases:
            fwd = {"X-authentik-username": "owner", "X-Authentik-Groups": "admins", "Accept": "text/html"}
            with app.app.test_request_context("/a/chat/", headers=headers, environ_base=environ):
                app._drop_unproved_signin(fwd)
            assert ("X-authentik-username" in fwd) is kept and ("X-Authentik-Groups" in fwd) is kept, (environ, fwd)
            assert fwd["Accept"] == "text/html"
    finally:
        app._signin_hops = real
    # and `_frame_answer` is the one that sets it, on its in-process request — and nothing else names the key:
    # the literal once (its definition), the name only where it is defined, set by the builder, and read here
    src = (pathlib.Path(app.__file__)).read_text(encoding="utf-8")
    body = src[src.index("def _frame_answer("):src.index("def ", src.index("def _frame_answer(") + 10)]
    assert "environ_base={_LINK_BUILDER_MARK: True}" in body
    assert src.count('"dgo.console.link_builder"') == 1 and src.count("dgo.console.link_builder") == 1
    uses = [ln.strip() for ln in src.splitlines() if "_LINK_BUILDER_MARK" in ln and not ln.lstrip().startswith("#")]
    assert len(uses) == 3, uses   # the definition, the builder's environ_base, `_drop_unproved_signin`'s read


def test_signout_names_the_way_out_for_a_signed_in_person_only(monkeypatch):
    """DGO-1621: the owner had no way to sign out («אין לי אפשרות להתנתקות») and cleared the browser's site data to
    leave. /api/signout says where a signed-in person signs out — the office's own sign-in app's page — and gives
    nothing to a visitor, or under authentik (its outpost sign-out reaches no app host); /api/me is unchanged."""
    c = app.app.test_client()
    who = {"X-authentik-username": "owner", "Host": "console.example.test"}
    monkeypatch.setenv("DGO_IDENTITY", "forward-auth")
    monkeypatch.setenv("CONSOLE_SIGNOUT_URL", "https://signin.example.test/logout")
    monkeypatch.setenv("CONSOLE_HOST", "console.example.test")
    assert c.get("/api/signout", headers=who).get_json() == {"url": "https://signin.example.test/logout"}
    assert c.get("/api/signout", headers={**who, "Host": "console.example.test:8080"}).get_json()["url"]
    # the console at a LAN address (apps/lan-console) signs in through another app: no way out offered from there
    assert c.get("/api/signout", headers={**who, "Host": "console.192-168-1-5.sslip.io"}).get_json() == {"url": ""}
    # …nor through another office's link: its door writes the console's own Host and X-DGO-Office, and that person
    # signed in at the office they browse from
    assert c.get("/api/signout", headers={**who, "X-DGO-Office": "hp-laptop"}).get_json() == {"url": ""}
    assert c.get("/api/signout", headers={"Host": "console.example.test"}).get_json() == {"url": ""}
    monkeypatch.setenv("DGO_IDENTITY", "authentik")
    assert c.get("/api/signout", headers=who).get_json() == {"url": ""}
    assert "signout" not in c.get("/api/me", headers=who).get_json()
