"""test_herd_enable — the apps screen does not switch on, by one press, an app the herd runs on another office (DGO-579).

On 2026-10-14 a second office browser was started on vps1 while the herd's one — every sign-in, in one profile — was
the HP's. `bbox apps enable` asks the herd file first since 9521487b; this holds the screen's door, app-management's
`POST /api/apps/<id>/enable`, on a temp checkout (the guard and herd_home beside it, herd.yaml, .env):
  * an app the herd runs elsewhere, not running here, is refused (409) naming where it runs — nothing is started;
  * `{"anyway": true}` (what the screen sends after asking the person) starts it;
  * a move (`restore`, the app arriving with its data) is never asked;
  * its home office, an app the herd does not place, an app already running here, an office that says another herd,
    and a checkout with no guard are not asked;
  * the catalog's reader gives each app placed elsewhere with its office's label.
Run: python3 -m pytest platform-base/app-management/test_herd_enable.py (in the app-management image: Flask, PyYAML).
"""
import importlib.util
import pathlib
import shutil
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HERD = """herd: Bina Solutions
offices:
  vps1:
    label: VPS
  hp-laptop:
    label: HP
    aliases: [hp]
apps:
  demo-view: hp-laptop
  sites: vps1
"""


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_herd", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_herd"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()


@pytest.fixture
def office(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    for f in ("herd_home.py", "herd_enable_guard.py"):
        shutil.copy(ROOT / "scripts" / f, tmp_path / "scripts" / f)
    (tmp_path / "apps" / "computers").mkdir(parents=True)
    (tmp_path / "apps" / "computers" / "herd.yaml").write_text(HERD, encoding="utf-8")
    (tmp_path / ".env").write_text("DGO_OFFICE_ID=vps1\n", encoding="utf-8")
    monkeypatch.setattr(app, "REPO", str(tmp_path))
    monkeypatch.delenv("DGO_OFFICE_ID", raising=False)
    monkeypatch.delenv("DGO_HERD", raising=False)
    state = {}
    monkeypatch.setattr(app, "_load_state", lambda: state)
    ran = []
    monkeypatch.setattr(app, "_lifecycle", lambda aid, enable, restore=None: (ran.append((aid, restore)), app.jsonify(ok=True))[1])
    return tmp_path, state, ran


def enable(aid, body=None):
    return app.app.test_client().post(f"/api/apps/{aid}/enable", json=body if body is not None else {})


def test_an_app_the_herd_runs_elsewhere_is_refused_by_name_and_nothing_starts(office):
    _, _, ran = office
    r = enable("demo-view")
    assert r.status_code == 409 and not ran
    d = r.get_json()
    assert d["herd"] == {"home": "hp-laptop", "label": "HP"} and "hp-laptop" in d["error"] and "anyway" in d["error"]


def test_anyway_starts_it_and_a_move_is_never_asked(office):
    _, _, ran = office
    assert enable("demo-view", {"anyway": True}).status_code == 200
    assert enable("demo-view", {"anyway": "yes"}).status_code == 409, "only true means it"
    assert enable("demo-view", {"restore": {"archive": "hp-20261110-demo-view", "office": "hp-laptop"}}).status_code == 200
    assert [a for a, _ in ran] == ["demo-view", "demo-view"] and ran[1][1] == {"office": "hp-laptop", "archive": "hp-20261110-demo-view"}


def test_what_is_not_held_is_not_asked(office):
    root, state, ran = office
    assert enable("sites").status_code == 200, "its home office"
    assert enable("computers").status_code == 200, "an app the herd does not place"
    state["demo-view"] = {"state": "enabled", "by": "user"}
    assert enable("demo-view").status_code == 200, "already running here: switching it on changes nothing"
    state.clear()
    (root / ".env").write_text("DGO_OFFICE_ID=vps1\nDGO_HERD=Acme\n", encoding="utf-8")
    assert enable("demo-view").status_code == 200, "an office that says another herd is not ours"
    (root / ".env").write_text("DGO_OFFICE_ID=vps1\n", encoding="utf-8")
    (root / "scripts" / "herd_enable_guard.py").unlink()
    assert enable("demo-view").status_code == 200, "a checkout with no guard asks nothing"
    assert len(ran) == 5


def test_the_catalog_reader_gives_each_app_placed_elsewhere_with_its_offices_label(office):
    assert app._herd_away() == {"demo-view": ("hp-laptop", "HP")}


def test_the_guard_is_loaded_once_per_version_and_the_import_path_does_not_grow(office):
    """The catalog is asked every few seconds by every open screen: the guard's file is read again only when it
    changes, and its folder is put on the import path once (second reader: one entry per poll, for ever)."""
    app._herd_away()
    before, mod = len(sys.path), app._GUARD.get("mod")
    for _ in range(5):
        app._herd_away()
    assert len(sys.path) == before and app._GUARD.get("mod") is mod


def test_a_quoted_herd_with_a_comment_is_read_as_the_shell_reads_it(office):
    root, _, ran = office
    (root / ".env").write_text('DGO_OFFICE_ID="vps1"  # this office\nDGO_HERD="Acme" # another herd\n', encoding="utf-8")
    assert enable("demo-view").status_code == 200, "Acme is not this herd: nothing is asked"
    (root / ".env").write_text('DGO_OFFICE_ID="vps1"  # this office\nDGO_HERD="Bina Solutions" # ours\n', encoding="utf-8")
    assert enable("demo-view").status_code == 409, "the herd's own name, quoted and commented, is ours"


# ── DGO-1743 (579's second reader): the two other routes that start an app ────────────────────────────────────────

def unarchive(aid, body=None):
    return app.app.test_client().post(f"/api/apps/{aid}/unarchive", json=body if body is not None else {})


def test_unarchive_asks_what_enable_asks_archived_here_or_not(office):
    """`unarchive` started any app, archived or not: a caller that skipped enable's question reached the same start.
    And an app the herd moved to the HP, archived here and brought back with «שחזר», is a second running copy too
    (the second reader): data kept here does not make two copies one."""
    _, state, ran = office
    r = unarchive("demo-view")
    assert r.status_code == 409 and not ran and r.get_json()["herd"] == {"home": "hp-laptop", "label": "HP"}
    assert unarchive("demo-view", {"anyway": True}).status_code == 200
    assert unarchive("demo-view", [1]).status_code == 400, "a body that is not an object is refused by name"
    state["demo-view"] = {"state": "archived", "by": "user"}
    assert unarchive("demo-view").status_code == 409, "archived here, run by the herd elsewhere: asked"
    assert unarchive("demo-view", {"anyway": True}).status_code == 200
    assert unarchive("sites").status_code == 200, "its home office brings its own archive back unasked"
    assert [a for a, _ in ran] == ["demo-view", "demo-view", "sites"]


def test_the_catalog_says_where_the_herd_runs_an_app_archived_here(office, monkeypatch):
    """So the screen asks before «שחזר», as the office does (DGO-1743)."""
    _, state, _ = office
    state["demo-view"] = {"state": "archived", "by": "user"}
    monkeypatch.setattr(app, "_load_manifests", lambda: [{"id": "demo-view", "layer": 3, "title": {"he": "x"}}])
    monkeypatch.setattr(app, "_container_index", lambda: {})
    rows = {a["id"]: a for a in app._catalog()}
    assert rows["demo-view"]["archived"] and rows["demo-view"]["herd_home"] == "hp-laptop"


class _Placer:
    def __init__(self):
        self.placed = []

    def place(self, src, aid, enable=False):
        self.placed.append((aid, enable))


def test_a_catalog_install_of_an_app_the_herd_runs_elsewhere_is_asked_and_its_bytes_kept(office, tmp_path, monkeypatch):
    _, _, ran = office
    # install unpacks what the lifecycle answers (response, status), as the real one does
    monkeypatch.setattr(app, "_lifecycle", lambda aid, enable, restore=None: (ran.append((aid, restore)),
                                                                              (app.jsonify(ok=True), 200))[1])
    placer = _Placer()
    monkeypatch.setattr(app, "appinstall", placer)
    work = tmp_path / "staged"
    work.mkdir()
    monkeypatch.setitem(app._STAGED, "tok-1", {"id": "demo-view", "refusals": [], "dir": str(work / "demo-view"),
                                                "work": str(work), "prov": {"how": "test", "verified": True}})
    client = app.app.test_client()
    r = client.post("/api/catalog/install", json={"token": "tok-1"})
    assert r.status_code == 409 and r.get_json()["herd"]["home"] == "hp-laptop"
    assert not placer.placed and not ran and "tok-1" in app._STAGED, "nothing placed; the token stays to ask again"
    r = client.post("/api/catalog/install", json={"token": "tok-1", "anyway": True})
    assert r.status_code == 200 and placer.placed == [("demo-view", False)] and [a for a, _ in ran] == ["demo-view"]
    assert "tok-1" not in app._STAGED
