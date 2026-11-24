"""An app's data where it lives now (DGO-2019): its volumes AND its stores in the DGO folder's data/<app>/.

Two readers of «the app's data» knew only `data.volumes`, which every app moved into data/ has emptied: the guard
that refuses bringing an app from another office over data this office holds (409), and `uninstall --purge`. Moved
apps then had no guard, and a purge deleted nothing (the second reader of the batch that moved eleven apps). The
purge deletes, so it is held to the app's own home, store by store, and never past a reader.

Run: python -m pytest platform-base/app-management/test_data_home_stores.py -q
"""
import importlib.util
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_stores", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_stores"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
MOVED = {"id": "loans", "data": {"volumes": [], "paths": ["data/loans/state", "apps/loans/static"],
                                 "moved_from": {"data/loans/state": "loans_data", "data/loans/relay": "external:by_hand"}}}


class _Docker:
    """docker's volumes and running containers, faked: `have` volumes, `mounts` {container: [source…]}."""

    def __init__(self, have=(), mounts=None, busy=()):
        self.have, self.mounts, self.busy, self.removed = set(have), dict(mounts or {}), set(busy), []
        outer = self

        class Vol:
            def __init__(self, n):
                self.n = n

            def remove(self, force=False):
                if self.n in outer.busy:
                    raise RuntimeError("volume is in use")
                outer.have.discard(self.n)
                outer.removed.append(self.n)

        class Volumes:
            def get(self, n):
                if n not in outer.have:
                    raise app.docker_sdk.errors.NotFound(n)
                return Vol(n)

        class C:
            def __init__(self, name, srcs):
                self.name = name
                self.attrs = {"Mounts": [{"Type": "volume", "Name": s} if not s.startswith("/") else
                                         {"Type": "bind", "Source": s} for s in srcs]}

        class Containers:
            def list(self):
                return [C(n, s) for n, s in outer.mounts.items()]

        class Client:
            volumes, containers = Volumes(), Containers()
        self.client = Client()


def _office(monkeypatch, tmp_path, **docker):
    d = _Docker(**docker)
    monkeypatch.setattr(app.docker_sdk, "from_env", lambda: d.client)
    monkeypatch.setattr(app, "REPO", str(tmp_path))
    monkeypatch.setattr(app, "PROJECT", "office")
    return d


def test_the_stores_and_their_exact_volumes(monkeypatch):
    monkeypatch.setattr(app, "PROJECT", "office")
    assert app._stores("loans", MOVED) == [("data/loans/relay", "by_hand"), ("data/loans/state", "office_loans_data")]
    # a store with no old volume: the one datahome makes it wait in; a path outside the home is no store of it
    m = {"data": {"paths": ["data/new/db", "data/other/x", "data/new/../other", "data/new/."]}}
    assert app._stores("new", m) == [("data/new/db", "office_dh_new_db")]
    assert app._stores("bina-claude", {"data": {"paths": ["data/bina-claude-2/home"]}}) == []   # a neighbour is not home
    assert app._store_volumes({"id": "x", "data": {"volumes": ["a", {"name": "b"}]}}) == ["office_a", "office_b"]
    # a store that was a folder of the source tree has no volume: it waits in that folder, never named as a volume
    src = {"id": "chat", "data": {"paths": ["data/chat/files"], "moved_from": {"data/chat/files": "path:apps/chat/data"}}}
    assert app._stores("chat", src) == [("data/chat/files", "path:apps/chat/data")]
    assert app._store_volumes(src) == []


def test_a_store_from_a_source_folder_is_held_there_and_never_purged(monkeypatch, tmp_path):
    d = _office(monkeypatch, tmp_path)
    src = {"id": "chat", "data": {"paths": ["data/chat/files"], "moved_from": {"data/chat/files": "path:apps/chat/data"}}}
    assert app._held_volumes(src) == []
    (tmp_path / "apps/chat/data").mkdir(parents=True)
    (tmp_path / "apps/chat/data/chat.db").write_text("x")          # waiting there (or the copy its move left)
    assert app._held_volumes(src) == ["apps/chat/data"]
    (tmp_path / "data/chat/files").mkdir(parents=True)
    (tmp_path / "data/chat/files/chat.db").write_text("x")
    led = tmp_path / "data/.moves/chat/files.json"
    led.parent.mkdir(parents=True)
    led.write_text("{}")
    removed, failed = app._remove_store_folders("chat", src)
    assert removed == [] and d.removed == []
    assert any("apps/chat/data/" in f and "not purged" in f for f in failed)
    # nothing of it went: the store, the folder it came from, and its record — no record over a full old folder
    assert (tmp_path / "data/chat/files/chat.db").exists() and (tmp_path / "apps/chat/data/chat.db").exists()
    assert led.exists()
    # …and once the old folder holds nothing, the store is purged as any other, its record with it
    (tmp_path / "apps/chat/data/chat.db").unlink()
    removed, failed = app._remove_store_folders("chat", src)
    assert failed == [], failed
    assert "data/chat/files" in removed and not (tmp_path / "data/chat/files").exists() and not led.exists()
    assert (tmp_path / "apps/chat/data").is_dir(), "the source tree's folder itself is never removed"


def test_held_counts_a_store_folder_that_holds_anything_and_exact_volumes(monkeypatch, tmp_path):
    _office(monkeypatch, tmp_path)
    assert app._held_volumes(MOVED) == []
    (tmp_path / "data/loans/state").mkdir(parents=True)
    assert app._held_volumes(MOVED) == []                       # an empty folder is not data
    (tmp_path / "data/loans/state/loans.db").write_text("x")
    assert app._held_volumes(MOVED) == ["data/loans/state"]
    _office(monkeypatch, tmp_path, have=["loans_data"])          # a bare-named stranger is NOT this app's
    assert app._held_volumes(MOVED) == ["data/loans/state"]
    _office(monkeypatch, tmp_path, have=["office_loans_data", "by_hand"])
    assert app._held_volumes(MOVED) == ["by_hand", "office_loans_data", "data/loans/state"]


def test_purge_goes_store_by_store_and_takes_the_record(monkeypatch, tmp_path):
    d = _office(monkeypatch, tmp_path, have=["office_loans_data"])
    (tmp_path / "data/loans/state").mkdir(parents=True)
    (tmp_path / "data/loans/state/loans.db").write_text("x")
    for p in ("data/.moves/loans", "data/.moves/aside/loans", "data/.moves/wait"):
        (tmp_path / p).mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/.moves/wait/loans.yml").write_text("services: {}\n")
    (tmp_path / "data/.moves/wait/other.yml").write_text("services: {}\n")
    removed, failed = app._remove_store_folders("loans", MOVED)
    assert failed == [], failed
    assert d.removed == ["office_loans_data"] and "data/loans/state" in removed and "data/.moves/loans" in removed
    assert not (tmp_path / "data/loans/state").exists() and not (tmp_path / "data/.moves/aside/loans").exists()
    assert (tmp_path / "data/.moves/wait/other.yml").exists()   # another app's record is never touched


def test_purge_never_passes_a_reader_or_leaves_a_volume_beside_an_empty_folder(monkeypatch, tmp_path):
    (tmp_path / "data/loans/state").mkdir(parents=True)
    (tmp_path / "data/loans/state/loans.db").write_text("x")
    # a running container still reads the folder: that store is refused and named, and nothing of it goes
    _office(monkeypatch, tmp_path, have=["office_loans_data"], mounts={"peek-1": [str(tmp_path / "data/loans/state")]})
    removed, failed = app._remove_store_folders("loans", MOVED)
    assert any("still read by peek-1" in f for f in failed) and (tmp_path / "data/loans/state/loans.db").exists()
    assert not any(r.startswith("data/.moves") for r in removed)                 # the record stays with the data
    # …and so is one that reads only a part of it (a subfolder), or binds a folder above it inside data/
    for src in (tmp_path / "data/loans/state/users", tmp_path / "data/loans"):
        _office(monkeypatch, tmp_path, have=["office_loans_data"], mounts={"peek-2": [str(src)]})
        removed, failed = app._remove_store_folders("loans", MOVED)
        assert any("still read by peek-2" in f for f in failed) and (tmp_path / "data/loans/state/loans.db").exists()
    # the office's own hands mount the whole checkout, or the machine's root: they read no store, never block a purge
    d = _office(monkeypatch, tmp_path, have=["office_loans_data"],
                mounts={"app-management-hp": [str(tmp_path)], "machine-hp": ["/"]})
    removed, failed = app._remove_store_folders("loans", MOVED)
    assert failed == [] and not (tmp_path / "data/loans/state").exists(), failed
    (tmp_path / "data/loans/state").mkdir(parents=True)
    (tmp_path / "data/loans/state/loans.db").write_text("x")
    # the volume cannot be removed (in use): the folder stays too — never a full volume beside an empty folder
    _office(monkeypatch, tmp_path, have=["office_loans_data"], busy=["office_loans_data"])
    removed, failed = app._remove_store_folders("loans", MOVED)
    assert any("in use" in f for f in failed) and (tmp_path / "data/loans/state/loans.db").exists()


def test_a_half_purge_takes_the_record_of_each_store_that_went(monkeypatch, tmp_path):
    """Two stores, one still read: the other goes, and its own record with it — never a «moved» record over its now
    empty folder; the read one keeps its folder, its volume and its record. A path outside the home blocks nothing."""
    two = {"id": "loans", "data": {"paths": ["data/loans/state", "data/loans/media", "data/shared/x"],
                                   "moved_from": {"data/loans/state": "loans_data", "data/loans/media": "loans_media"}}}
    for p in ("data/loans/state", "data/loans/media", "data/.moves/loans", "data/.moves/wait"):
        (tmp_path / p).mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/.moves/wait/loans.yml").write_text("services: {}\n")
    (tmp_path / "data/loans/state/loans.db").write_text("x")
    (tmp_path / "data/loans/media/a.jpg").write_text("x")
    (tmp_path / "data/.moves/loans/state.json").write_text('{"moved_at": "t"}')
    (tmp_path / "data/.moves/loans/media.json").write_text('{"moved_at": "t"}')
    _office(monkeypatch, tmp_path, have=["office_loans_data", "office_loans_media"],
            mounts={"peek-1": [str(tmp_path / "data/loans/media")]})
    removed, failed = app._remove_store_folders("loans", two)
    assert not (tmp_path / "data/loans/state").exists() and not (tmp_path / "data/.moves/loans/state.json").exists()
    assert (tmp_path / "data/loans/media/a.jpg").exists() and (tmp_path / "data/.moves/loans/media.json").exists()
    assert any("data/shared/x" in f for f in failed) and any("still read by peek-1" in f for f in failed)
    assert not (tmp_path / "data/.moves/wait/loans.yml").exists()   # the wait file goes even in a half purge
    # the reader gone: the rest goes, and with every store gone the app's whole record too — the outside path
    # (refused and said again) does not hold that back
    _office(monkeypatch, tmp_path, have=["office_loans_media"])
    removed, failed = app._remove_store_folders("loans", two)
    assert not (tmp_path / "data/loans/media").exists() and not (tmp_path / "data/.moves/loans").exists(), failed
    assert failed == ["data/shared/x: not in data/loans/ — never purged from here"], failed


def test_a_store_that_is_one_file_goes_too(monkeypatch, tmp_path):
    _office(monkeypatch, tmp_path)
    (tmp_path / "data/loans").mkdir(parents=True)
    (tmp_path / "data/loans/config.json").write_text("{}")
    removed, failed = app._remove_store_folders("loans", {"data": {"paths": ["data/loans/config.json"]}})
    assert failed == [] and not (tmp_path / "data/loans/config.json").exists() and "data/loans/config.json" in removed


def test_purge_stays_in_the_apps_own_home(monkeypatch, tmp_path):
    _office(monkeypatch, tmp_path)
    (tmp_path / "data/forward-auth/state").mkdir(parents=True)
    (tmp_path / "data/forward-auth/state/users").write_text("x")
    removed, failed = app._remove_store_folders("loans", {"data": {"paths": ["data/forward-auth/state", "data"]}})
    assert removed == [] and failed == ["data/forward-auth/state: not in data/loans/ — never purged from here"], failed
    assert (tmp_path / "data/forward-auth/state/users").exists()
    # a link INSIDE the home that points out of it (to data/ itself): the store under it is never deleted
    (tmp_path / "data/loans").mkdir(parents=True, exist_ok=True)
    os.symlink(tmp_path / "data", tmp_path / "data/loans/sub")
    removed, failed = app._remove_store_folders("loans", {"data": {"paths": ["data/loans/sub/forward-auth"]}})
    assert any("resolves outside" in f for f in failed) and (tmp_path / "data/forward-auth/state/users").exists()
    os.remove(tmp_path / "data/loans/sub")
    # a home that is a link (to anywhere) is never purged through
    outside = tmp_path / "elsewhere"
    (outside / "state").mkdir(parents=True)
    (outside / "state/keep").write_text("x")
    os.symlink(outside, tmp_path / "data/linked")
    removed, failed = app._remove_store_folders("linked", {"data": {"paths": ["data/linked/state"]}})
    assert removed == [] and any("a link" in f for f in failed) and (outside / "state/keep").exists()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
