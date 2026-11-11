"""test_links — `/go/<ref>`: the one link a person is given resolves to the shell's own route, or says why not
(DGO-1433, links.py).

The registries below have the shapes the console really holds: a compiled linked tile carries `office` AND a
`remote` block (serve.module_entries), a peers.d tile carries `remote` alone (app.py `_peer_module`). VPS1 is vps1's
own for the cases that broke on the owner's phone (the HP's Plane and Bina Claude are external tiles of a linked
office — no door, so `/a/<alias>.<office>/` is `unknown_app` there; meet is vps1's own); MAC is the MacBook's, where
a client office (examplef) runs Plane and meet too. `ref` reaches `resolve` DECODED, as werkzeug hands it to the
route. Run: python3 -m pytest platform-base/console/test_links.py
"""
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import links  # noqa: E402


def far(tid, office, alias=None, module_id=None, **extra):
    a = alias or tid.split(".", 1)[0]
    return {"id": tid, "host": tid, "office": office, **extra,
            "remote": {"office": office, "alias": a, "module_id": module_id or a, "label": {"he": office}}}


VPS1 = [
    {"id": "bina", "alias": "bina", "name": "בינה"},
    {"id": "meet", "alias": "meet", "url": "https://meet-start.staging.digital-office.co.il", "host": "meet-start"},
    far("plane.hp-laptop", "hp-laptop", module_id="project-pln", signed_in="/.dgo/signed-in", enter="/.dgo/enter"),
    far("bina-claude.hp-laptop", "hp-laptop", signed_in="/.dgo/signed-in", enter="/.dgo/enter"),
    far("telegram.hp-laptop", "hp-laptop", proxy="/a/telegram.hp-laptop/"),
    far("dashboard.macbook", "macbook"),
]
MAC = [
    {"id": "dashboard", "alias": "dashboard"},
    far("plane.hp-laptop", "hp-laptop", module_id="project-pln"),
    far("plane.examplef", "examplef", module_id="project-pln"),
    far("meet.vps1", "vps1"),
    far("meet.examplef", "examplef"),
    far("drive.examplef", "examplef"),
]


def go(ref, query="", tiles=VPS1, own="vps1"):
    return links.resolve(ref, query, tiles, own, "bina")


def test_a_work_item_by_its_key_opens_plane_on_the_office_that_runs_it():
    hit = go("DGO-1433")
    assert hit["to"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"
    assert hit["kind"] == "item" and hit["ref"] == "DGO-1433"


def test_a_key_typed_in_small_letters_is_the_same_item_and_the_query_goes_on():
    assert go("dgo-1433")["to"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"
    assert go("DGO-1433", "tab=activity")["to"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/?tab=activity"


def test_this_offices_own_plane_wins_over_a_linked_offices():
    tiles = VPS1 + [{"id": "project-pln", "alias": "plane", "app": "project-pln"}]
    assert go("MEET-24", tiles=tiles)["to"] == "/#/m/project-pln/bina/browse/MEET-24/"


def test_several_linked_planes_are_a_choice_never_a_guess():
    hit = go("DGO-1433", tiles=MAC, own="macbook")
    assert "to" not in hit
    assert [c["go"] for c in hit["choices"]] == ["/go/plane.examplef/bina/browse/DGO-1433/",
                                                  "/go/plane.hp-laptop/bina/browse/DGO-1433/"]
    # …and each choice is a link that resolves by itself, on the same console
    assert go("plane.hp-laptop/bina/browse/DGO-1433/", tiles=MAC, own="macbook")["to"] == \
        "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"


def test_no_plane_anywhere_is_said():
    hit = go("DGO-1433", tiles=[t for t in VPS1 if not t["id"].startswith("plane")])
    assert "to" not in hit and hit["why"] and "choices" not in hit


def test_a_meeting_by_its_room_with_meets_own_rule():
    assert go("meet/exu101")["to"] == "/#/m/meet/flow/exu101/"
    assert go("meet/exu101/t90")["to"] == "/#/m/meet/flow/exu101/t90"
    assert go("Meet/Exu101")["to"] == "/#/m/meet/flow/exu101/"
    assert go("meet/team.weekly")["to"] == "/#/m/meet/flow/team.weekly/"
    assert "to" not in go("meet/..")
    hit = go("meet/exu101", tiles=MAC, own="macbook")
    assert [c["tile"] for c in hit["choices"]] == ["meet.examplef", "meet.vps1"]


def test_an_app_on_an_office_is_its_tile_and_keeps_its_inner_route_and_query():
    assert go("bina-claude.hp-laptop")["to"] == "/#/m/bina-claude.hp-laptop"
    assert go("bina-claude.hp-laptop/sessions/42", "tab=log")["to"] == "/#/m/bina-claude.hp-laptop/sessions/42?tab=log"
    assert go("bina-claude.hp-laptop/sessions/")["to"] == "/#/m/bina-claude.hp-laptop/sessions/"


def test_a_decoded_segment_is_encoded_once_for_the_route():
    # werkzeug has decoded the path already: a literal `%` and a space are characters, not escapes
    assert go("bina-claude.hp-laptop/a%41")["to"] == "/#/m/bina-claude.hp-laptop/a%2541"
    assert go("bina-claude.hp-laptop/My Docs")["to"] == "/#/m/bina-claude.hp-laptop/My%20Docs"
    assert go("bina-claude.hp-laptop/דוחות")["to"].startswith("/#/m/bina-claude.hp-laptop/%D7%93")


def test_an_app_named_by_the_office_that_owns_it_is_that_offices_own_tile_there():
    on_hp = [{"id": "bina-claude", "alias": "bina-claude"}, {"id": "plane", "alias": "plane", "app": "project-pln"}]
    assert go("bina-claude.hp-laptop", tiles=on_hp, own="hp-laptop")["to"] == "/#/m/bina-claude"
    assert "to" not in go("bina-claude.hp-laptop", tiles=on_hp, own="macbook")


def test_the_own_office_rule_never_lands_on_another_offices_tile():
    # a peers.d tile is marked by `remote` alone — it is not this office's, whatever its alias
    peer = {"id": "bina-claude.hp-laptop", "remote": {"office": "hp-laptop", "alias": "bina-claude"}}
    assert "to" not in go("bina-claude.macbook", tiles=[peer], own="macbook")


def test_a_bare_alias_several_offices_give_is_a_choice():
    hit = go("drive", tiles=MAC + [far("drive.hp-laptop", "hp-laptop")], own="macbook")
    assert "to" not in hit and sorted(c["tile"] for c in hit["choices"]) == ["drive.examplef", "drive.hp-laptop"]
    assert go("drive", tiles=MAC, own="macbook")["to"] == "/#/m/drive.examplef"     # exactly one: that one


def test_a_tile_this_console_does_not_have_is_said_with_its_name():
    hit = go("browser42.hp-laptop")
    assert "to" not in hit and "browser42.hp-laptop" in hit["why"]


def test_nothing_and_garbage_are_said():
    for ref in ("", "/", "..", "a b", "<script>", "x/../../etc", "DGO-1433\n", "bina\r\nSet-Cookie: x"):
        hit = go(ref)
        assert "to" not in hit and hit["why"], ref


def test_every_route_is_a_fragment_of_this_page():
    refs = ["DGO-1433", "meet/exu101", "bina-claude.hp-laptop", "bina-claude.hp-laptop/https:",
            "bina-claude.hp-laptop/x/y", "telegram.hp-laptop/chat/1"]
    for ref in refs:
        hit = go(ref)
        assert "to" in hit, ref
        to = hit["to"]
        assert to.startswith("/#/m/") and "\n" not in to and "\r" not in to and " " not in to, to


def test_the_shells_own_module_ref_cases_resolve_the_same_here():
    """platform-base/console/test_module_ref.mjs, case for case: links.find is the shell's rule on the server."""
    local = [{"id": "bina", "alias": "bina", "embed": "/a/bina/"},
             {"id": "project-pln", "alias": "plane", "embed": "/a/plane/", "external": True, "host": "plane"}]
    remote = [{"id": "bina", "alias": "bina"},
              {"id": "plane.hp-laptop", "remote": {"alias": "plane", "module_id": "project-pln", "office": "hp-laptop"}}]
    tid = lambda m: m["id"] if m else "<none>"   # noqa: E731
    assert tid(links.find(local, "project-pln")) == "project-pln"
    assert tid(links.find(local, "plane")) == "project-pln"
    assert tid(links.find(remote, "project-pln")) == "plane.hp-laptop"
    assert tid(links.find(remote, "plane")) == "plane.hp-laptop"
    assert tid(links.find(remote, "plane.hp-laptop")) == "plane.hp-laptop"
    assert tid(links.find(local + [{"id": "plane.macbook", "remote": {"alias": "plane", "module_id": "plane"}}],
                          "plane")) == "project-pln"
    assert tid(links.find(remote, "bina")) == "bina"
    assert tid(links.find(local, "nope")) == "<none>"
    assert tid(links.find(local, "")) == "<none>"
    assert tid(links.find([], "bina")) == "<none>"


# ── the route itself, through Flask ──────────────────────────────────────────────────────────────
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _office_env(monkeypatch):
    monkeypatch.setenv("DGO_OFFICE_ID", "vps1")


def _console(tiles=VPS1, office="vps1"):
    import os
    os.environ["DGO_OFFICE_ID"] = office            # restored after each test by _office_env (monkeypatch)
    path = HERE / "app.py"
    mod = types.ModuleType("console_app_links")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    mod._tiles = lambda: tiles
    # the control plane's REAL record shape: reconcile.OFFICE_FIELDS, no id
    mod._office_record = lambda fresh=False: {"office": {"name": "x", "animal": "y"}, "installed": True}
    return mod


def test_go_answers_a_redirect_to_the_shell_route():
    app = _console()
    r = app.app.test_client().get("/go/DGO-1433")
    assert r.status_code == 302
    assert r.headers["Location"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"
    assert r.headers.get("Cache-Control") == "no-store"


def test_the_consoles_own_office_comes_from_its_environment():
    on_hp = [{"id": "bina-claude", "alias": "bina-claude"}]
    app = _console(on_hp, "hp-laptop")
    r = app.app.test_client().get("/go/bina-claude.hp-laptop")
    assert r.status_code == 302 and r.headers["Location"] == "/#/m/bina-claude"


def test_go_says_what_it_cannot_open_as_the_consoles_card_never_json():
    app = _console()
    for path in ("/go/browser42.hp-laptop", "/go", "/go/"):
        r = app.app.test_client().get(path, headers={"Accept": "text/html"})
        assert r.status_code == 404 and r.content_type.startswith("text/html"), path
        body = r.get_data(as_text=True)
        assert 'dir="rtl"' in body and "data-card" in body and not body.lstrip().startswith("{")
    assert "browser42.hp-laptop" in app.app.test_client().get("/go/browser42.hp-laptop").get_data(as_text=True)


def _ledger_console(tmp_path, verdicts, took=True):
    """A console whose ledger is in tmp_path and whose check answers `verdicts` in order; returns (app, posted).
    The notifications app takes each notice (`took`); the age window is off (these links are given at t=1)."""
    app = _console()
    app.LINKS_DIR = str(tmp_path)
    app.LINKS_RECHECK_DAYS = 0
    answers = list(verdicts)
    app.links_check = lambda ref, user, query="": answers.pop(0)
    posted = []

    def post(url, json=None, timeout=None):
        posted.append(json)
        return types.SimpleNamespace(ok=took, status_code=201 if took else 503)
    app.requests = types.SimpleNamespace(post=post, RequestException=Exception)
    return app, posted


def test_a_link_given_is_a_record_and_is_opened_again(tmp_path):
    app, posted = _ledger_console(tmp_path, [{"ok": True, "at": 2, "checks": [{"said": "200"}]}])
    app.links_record({"path": "/go/DGO-1433", "link": "https://c.example/go/DGO-1433", "for": "owner", "as": "akadmin",
                      "given_at": 1, "checked_at": 1, "ok": True})
    seen = app.links_recheck()
    assert seen == [{"path": "/go/DGO-1433", "link": "https://c.example/go/DGO-1433", "ok": True, "said": "200"}]
    assert not posted, "a link that still opens says nothing"
    rows = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2, "the check is a line of its own; the given line is never edited"


def test_a_link_that_stopped_opening_is_a_notice_and_one_that_came_back_closes_it(tmp_path):
    app, posted = _ledger_console(tmp_path, [{"ok": False, "why": "דלת הקישור ענתה במקום האפליקציה (404, no-app)"},
                                             {"ok": False, "why": "same"}, {"ok": True, "checks": []}])
    app.links_record({"path": "/go/bina-claude.hp-laptop", "link": "https://c.example/go/bina-claude.hp-laptop",
                      "for": "owner", "as": "akadmin", "given_at": 1, "ok": True})
    app.links_recheck()
    assert len(posted) == 1 and posted[0]["level"] == "error" and posted[0]["source"] == "links"
    assert posted[0]["source_id"] == "/go/bina-claude.hp-laptop" and "no-app" in posted[0]["body"]
    app.links_recheck()
    assert len(posted) == 1, "still broken: no second notice"
    app.links_recheck()
    assert len(posted) == 2 and posted[1]["level"] == "info", "it came back: the notice is closed"


def test_only_links_given_are_opened_again(tmp_path):
    app, posted = _ledger_console(tmp_path, [])
    app.links_record({"path": "/go/DGO-1", "checked_at": 5, "ok": True})          # a check line with no given line
    app.links_record({"path": "/a/x/", "given_at": 1, "ok": True})               # not a /go/ link
    assert app.links_given() == {} and app.links_recheck() == []


def _rows(tmp_path):
    import json as _json
    return [_json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_notice_the_notifications_app_did_not_take_is_said_again(tmp_path):
    app, posted = _ledger_console(tmp_path, [{"ok": False, "why": "x"}, {"ok": False, "why": "x"}], took=False)
    app.links_record({"path": "/go/DGO-9", "link": "https://c.example/go/DGO-9", "as": "akadmin", "given_at": 1, "ok": True})
    app.links_recheck()
    app.links_recheck()
    assert len(posted) == 2, "refused the first time: said again, never counted as said"
    assert all("noticed" not in r for r in _rows(tmp_path))


def test_a_notice_left_up_for_a_link_given_again_is_closed(tmp_path):
    app, posted = _ledger_console(tmp_path, [{"ok": False, "why": "x"}, {"ok": True, "checks": []}])
    app.links_record({"path": "/go/DGO-9", "link": "l", "as": "akadmin", "given_at": 1, "ok": True})
    app.links_recheck()                                                       # broken: the error notice goes up
    app.links_record({"path": "/go/DGO-9", "link": "l", "as": "akadmin", "given_at": 5, "checked_at": 5, "ok": True})
    app.links_recheck()                                                       # given again, and it opens
    assert [p["level"] for p in posted] == ["error", "info"]


def test_an_unchanged_verdict_writes_one_line_a_day_not_one_a_pass(tmp_path):
    app, posted = _ledger_console(tmp_path, [{"ok": True, "at": 100}, {"ok": True, "at": 200}, {"ok": True, "at": 100 + 86400}])
    app.links_record({"path": "/go/DGO-9", "link": "l", "as": "akadmin", "given_at": 50, "checked_at": 50, "ok": True})
    for _ in range(3):
        app.links_recheck()
    assert [r.get("checked_at") for r in _rows(tmp_path)] == [50, 100, 100 + 86400] and not posted


def test_a_link_given_long_ago_is_not_opened_again(tmp_path):
    import time as _time
    app, posted = _ledger_console(tmp_path, [{"ok": True}, {"ok": True}])
    app.LINKS_RECHECK_DAYS = 14
    now = int(_time.time())
    app.links_record({"path": "/go/OLD-1", "link": "old", "as": "a", "given_at": now - 30 * 86400, "ok": True})
    app.links_record({"path": "/go/NEW-1", "link": "new", "as": "a", "given_at": now - 3600, "ok": True})
    # …unless the owner was last told it is broken: it stays checked until it is said to open again
    app.links_record({"path": "/go/OLD-2", "link": "told", "as": "a", "given_at": now - 30 * 86400, "ok": False,
                      "noticed": False})
    assert [s["path"] for s in app.links_recheck()] == ["/go/NEW-1", "/go/OLD-2"]
    assert [p["level"] for p in posted] == ["info"]


def test_one_link_whose_check_raises_does_not_end_the_pass(tmp_path):
    app, posted = _ledger_console(tmp_path, [])
    seen = []

    def check(ref, user, query=""):
        seen.append(ref)
        if ref == "A-1":
            raise IndexError("a tile's route changed shape")
        return {"ok": True}
    app.links_check = check
    for p in ("/go/A-1", "/go/B-1"):
        app.links_record({"path": p, "link": p, "as": "a", "given_at": 1, "ok": True})
    out = app.links_recheck()
    assert seen == ["A-1", "B-1"] and [o["ok"] for o in out] == [False, True]
    assert "IndexError" not in out[0]["said"] and posted and posted[0]["level"] == "error"


def test_the_recheck_loop_starts_once_and_not_on_import():
    app = _console()
    assert not getattr(app.start_links_recheck, "started", False), "importing app.py starts nothing"
    started = []
    import threading as _t
    real = _t.Thread
    _t.Thread = lambda target=None, daemon=None, name=None: types.SimpleNamespace(start=lambda: started.append(name))
    try:
        app.start_links_recheck()
        app.start_links_recheck()
    finally:
        _t.Thread = real
    assert started == ["links-recheck"]


def test_go_answers_the_route_as_json_only_to_whoever_asks_for_json():
    # the shell's frame-link catcher (static/app.js goTo) asks for JSON; a browser navigating never does
    app = _console()
    c = app.app.test_client()
    r = c.get("/go/DGO-1433", headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.get_json()["to"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"
    assert r.headers.get("Cache-Control") == "no-store" and "Accept" in r.headers.get("Vary", "")
    r = c.get("/go/DGO-1433", headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    assert r.status_code == 302
    r = c.get("/go/DGO-1433", headers={"Accept": "*/*"})
    assert r.status_code == 302
    r = c.get("/go/browser42.hp-laptop", headers={"Accept": "application/json"})
    assert r.status_code == 404 and "to" not in r.get_json() and r.get_json()["why"]
    r = _console(MAC, "macbook").app.test_client().get("/go/DGO-1433", headers={"Accept": "application/json"})
    assert r.status_code == 300 and len(r.get_json()["choices"]) == 2


def test_go_offers_the_choice_as_links_when_several_offices_run_it():
    app = _console(MAC, "macbook")
    r = app.app.test_client().get("/go/DGO-1433")
    body = r.get_data(as_text=True)
    assert r.status_code == 300 and 'href="/go/plane.hp-laptop/bina/browse/DGO-1433/"' in body
    assert 'href="/go/plane.examplef/bina/browse/DGO-1433/"' in body


class _Answer:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.content = status, body
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}


PAGE = b"<!doctype html><html><head><title>Plane | x</title></head><body></body></html>"


def _checked(answer, ref="DGO-1433", tmp=None, user="qa", query="", tiles=VPS1):
    """links_check on vps1's registry, with the HP's door answering `answer` (one answer, or a list in order);
    returns (result, what was asked)."""
    app = _console(tiles)
    import json as _json
    gen = pathlib.Path(tmp)
    for alias in ("plane", "bina-claude"):
        (gen / f"remote.hp-laptop.{alias}.json").write_text(_json.dumps({"id": f"{alias}.hp-laptop", "link_port": 9003}))
    app.GENERATED = str(gen)
    app._modules = lambda: tiles
    app._app_bases = lambda: {}
    app._remote_doors = lambda: {}
    asked, answers = [], list(answer) if isinstance(answer, list) else [answer]

    def get(url, headers=None, timeout=None, allow_redirects=True):
        asked.append((url, dict(headers or {}), allow_redirects))
        return answers.pop(0) if len(answers) > 1 else answers[0]
    app.requests = types.SimpleNamespace(get=get, RequestException=Exception)
    return app.links_check(ref, user, query), asked


def test_no_identity_no_check(tmp_path):
    out, asked = _checked(_Answer(200, PAGE), user="", tmp=tmp_path)
    assert not out["ok"] and not asked and "זהות" in out["why"]


def test_the_door_is_addressed_by_the_tiles_own_name_never_a_field_a_peer_wrote(tmp_path):
    tiles = [dict(t, host="evil.example") if t["id"] == "plane.hp-laptop" else t for t in VPS1]
    out, asked = _checked(_Answer(200, PAGE), tmp=tmp_path, tiles=tiles)
    assert asked[0][0].startswith("http://plane.hp-laptop:9003/")


def test_a_redirect_inside_the_app_is_followed_and_one_elsewhere_is_not(tmp_path):
    out, asked = _checked([_Answer(308, b"", {"Location": "/bina/browse/DGO-1433"}), _Answer(200, PAGE)], tmp=tmp_path)
    assert out["ok"] and [a[0] for a in asked] == ["http://plane.hp-laptop:9003/bina/browse/DGO-1433/",
                                                   "http://plane.hp-laptop:9003/bina/browse/DGO-1433"]
    out, _ = _checked(_Answer(302, b"", {"Location": "https://auth.example/flow"}), tmp=tmp_path)
    assert not out["ok"] and "הפניה" in out["why"]


def test_the_link_given_is_the_link_checked(tmp_path):
    for ref, query, want in (("DGO-1433", "tab=activity", "/go/DGO-1433?tab=activity"),
                             ("bina-claude.hp-laptop/sessions/42", "x=1", "/go/bina-claude.hp-laptop/sessions/42?x=1")):
        out, asked = _checked(_Answer(200, PAGE), ref=ref, query=query, tmp=tmp_path)
        assert out["ok"] and out["path"] == want, out
        # …and resolving that path again opens the same screen
        again = links.resolve(want[len("/go/"):].split("?")[0], want.partition("?")[2], VPS1, "vps1", "bina")
        assert again["to"] == out["opens"]
    assert go("meet/exu101/t90")["to"] == "/#/m/meet/flow/exu101/t90"


def test_a_page_that_mentions_authentik_is_still_a_page(tmp_path):
    out, _ = _checked(_Answer(200, b"<html><head><title>Security</title></head><body>authentik is the sign-in"
                                   b"</body></html>"), tmp=tmp_path)
    assert out["ok"]


def test_check_opens_the_items_frame_at_the_door_as_the_edge_does(tmp_path):
    page = b"<!doctype html><html><head><title>Plane | x</title></head><body></body></html>"
    out, asked = _checked(_Answer(200, page), tmp=tmp_path)
    assert out["ok"] and out["path"] == "/go/DGO-1433" and out["opens"] == "/#/m/plane.hp-laptop/bina/browse/DGO-1433/"
    url, headers, follow = asked[0]
    assert url == "http://plane.hp-laptop:9003/bina/browse/DGO-1433/"
    assert headers["Host"] == "plane.localhost" and headers["Accept"] == "text/html" and follow is False


def test_a_redirect_is_never_a_page(tmp_path):
    out, _ = _checked(_Answer(302, b"", {"Location": "https://auth.example/flow"}), tmp=tmp_path)
    assert not out["ok"] and "הפניה" in out["why"]


def test_the_doors_refusal_is_said_with_the_doors_own_word(tmp_path):
    out, _ = _checked(_Answer(404, b"", {"X-Dgo-Door": "no-app"}), tmp=tmp_path)
    assert not out["ok"] and "no-app" in out["why"]


def test_a_sign_in_page_or_json_is_not_the_app(tmp_path):
    out, _ = _checked(_Answer(200, b'<html><body><div id="ak-flow">authentik</div></body></html>'), tmp=tmp_path)
    assert not out["ok"]
    out, _ = _checked(_Answer(200, b'{"error":"unknown_app"}', {"Content-Type": "application/json"}), tmp=tmp_path)
    assert not out["ok"]


def test_a_ref_that_does_not_resolve_is_checked_as_nothing(tmp_path):
    out, asked = _checked(_Answer(200, b"<html></html>"), ref="browser42.hp-laptop", tmp=tmp_path)
    assert not out["ok"] and not asked and "browser42.hp-laptop" in out["why"]
