"""Unit tests for what the catalog READS on every answer (app.py `_services_of`).

`/api/apps` is asked every 5 seconds by every open apps screen. One answer used to parse each app's
compose file twice with the pure-Python YAML loader — 2.9 s of every answer on an office whose
checkout is a Windows folder (2026-10-09) — and the screen stood as placeholders for 5 to 13
seconds. What these hold: a compose file is parsed when it CHANGES, not when it is asked about; the
answer is still the file's, the moment it changes; and nobody can spoil what is remembered.

Run: python -m pytest platform-base/app-management/test_catalog_reads.py -q
"""
import importlib.util
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    """Import app.py without its Flask app touching a real repo or docker socket."""
    spec = importlib.util.spec_from_file_location("appmgmt_reads", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_reads"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()


def _counting(monkeypatch):
    """The YAML parses app.py asks for, each by the name of the file it was given."""
    real, calls = app.yaml.safe_load, []

    def counted(stream):
        calls.append(os.path.basename(getattr(stream, "name", "") or ""))
        return real(stream)
    monkeypatch.setattr(app.yaml, "safe_load", counted)
    return calls


def _compose(tmp_path, *names):
    f = tmp_path / "docker-compose.yml"
    f.write_text("services:\n" + "".join(f"  {n}:\n    image: x\n" for n in names), encoding="utf-8")
    return {"compose": f.name, "_dir": str(tmp_path)}, f


def test_a_compose_file_is_parsed_once_however_often_it_is_asked_about(tmp_path, monkeypatch):
    m, _ = _compose(tmp_path, "web", "worker")
    calls = _counting(monkeypatch)
    assert [app._services_of(m) for _ in range(5)] == [["web", "worker"]] * 5
    assert len(calls) == 1


def test_a_changed_file_is_read_again_and_the_answer_is_the_new_one(tmp_path, monkeypatch):
    m, f = _compose(tmp_path, "web")
    calls = _counting(monkeypatch)
    assert app._services_of(m) == ["web"]
    _compose(tmp_path, "web", "worker", "db")
    assert app._services_of(m) == ["web", "worker", "db"]
    assert len(calls) == 2


def test_a_change_that_keeps_the_size_is_still_seen_by_its_time(tmp_path, monkeypatch):
    m, f = _compose(tmp_path, "aaa")
    assert app._services_of(m) == ["aaa"]
    st = f.stat()
    _compose(tmp_path, "bbb")                                   # the same number of bytes
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert f.stat().st_size == st.st_size
    assert app._services_of(m) == ["bbb"]


def test_the_list_handed_out_is_the_callers_own(tmp_path):
    m, _ = _compose(tmp_path, "web", "worker")
    got = app._services_of(m)
    got.append("something-a-caller-added")
    assert app._services_of(m) == ["web", "worker"]


def test_no_compose_and_a_missing_or_broken_file_are_no_services_and_are_not_remembered(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    assert app._services_of({}) == [] and app._services_of({"compose": None, "_dir": str(tmp_path)}) == []
    assert len(calls) == 0
    m = {"compose": "docker-compose.yml", "_dir": str(tmp_path)}
    assert app._services_of(m) == []                            # not there yet
    (tmp_path / "docker-compose.yml").write_text("services: [unclosed", encoding="utf-8")
    assert app._services_of(m) == []                            # there, and not YAML
    _compose(tmp_path, "web")                                   # put right: the next question sees it
    assert app._services_of(m) == ["web"]


def test_one_catalog_answer_parses_no_compose_file_it_has_already_read(tmp_path, monkeypatch):
    """The whole answer, over a small office: `_catalog()` asks for every app's services twice."""
    apps = tmp_path / "apps"
    for n in ("one", "two", "three"):
        d = apps / n
        d.mkdir(parents=True)
        (d / "app.json").write_text('{"id": "%s", "compose": "docker-compose.yml", "layer": 3}' % n, encoding="utf-8")
        (d / "docker-compose.yml").write_text(f"services:\n  {n}:\n    image: x\n", encoding="utf-8")
    (tmp_path / "platform-base").mkdir()
    (tmp_path / "platform.state.yaml").write_text("apps: {}\n", encoding="utf-8")
    monkeypatch.setattr(app, "REPO", str(tmp_path))
    monkeypatch.setattr(app, "STATE", str(tmp_path / "platform.state.yaml"))
    monkeypatch.setattr(app, "_container_index", lambda: {})
    monkeypatch.setattr(app, "_auth_blockers", lambda: {})
    # the compiler's own parser is not importable from a bare copy of this file; its rule is tested there
    monkeypatch.setattr(app, "_disposition", lambda entry: (entry or {}).get("state", "disabled"))
    first = app._catalog()
    assert sorted(a["id"] for a in first) == ["one", "three", "two"]
    assert {a["id"]: a["services"] for a in first} == {"one": ["one"], "two": ["two"], "three": ["three"]}
    calls = _counting(monkeypatch)
    again = app._catalog()
    assert [a["services"] for a in again] == [a["services"] for a in first]
    assert "docker-compose.yml" not in calls, f"a second answer parsed a compose file again: {calls}"
