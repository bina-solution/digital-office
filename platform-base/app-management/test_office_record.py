"""Unit tests for the office's own record on the control plane — `GET/PUT /api/office`.

The install wizard's one write. What these hold: a fresh office is not installed and says so; the
wizard's record makes it installed; a caller that arrived over a link cannot say who THIS office is
(§9 of the pairing contract — the route is in G85's class and must carry its refusal); a record the
compiler refuses is refused with the compiler's own sentence and nothing is written.

The compiler itself (`reconcile.set_office`) is tested beside it in platform/manager/test_office.py;
here its two shell-outs are replaced by a dict.

Run: python -m pytest platform-base/app-management/test_office_record.py -q
"""
import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    """Import app.py without its Flask app touching a real repo or docker socket."""
    spec = importlib.util.spec_from_file_location("appmgmt_office", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_office"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()

RECORD = {"name": "הלשכה בחיפה", "animal": "deer", "hue": "lime", "terms_version": "2026-10-09.1",
          "terms_accepted_at": "2026-10-09T18:00:00Z", "installed_at": "2026-10-09T18:01:00Z"}


@pytest.fixture
def plane(monkeypatch):
    """The plane with the compiler's two shell-outs replaced by one dict (`store` is the file)."""
    store = {}
    monkeypatch.setattr(app, "_office_get", lambda: dict(store))

    def _set(fields, by="wizard"):
        bad = [k for k in fields if k not in ("name", "animal", "hue", "terms_version",
                                              "terms_accepted_at", "installed_at")]
        if bad:
            return False, [f"office: unknown field {bad[0]!r} (the fields are name, animal, …)"]
        store.update({k: v for k, v in fields.items() if v})
        return True, []
    monkeypatch.setattr(app, "_office_set", _set)
    # a fresh office: no layer-3 app switched on (a test says otherwise where it matters)
    monkeypatch.setattr(app, "_load_state", lambda: {"traefik": {"enabled": True}, "console": {"enabled": True}})
    monkeypatch.setattr(app, "_load_manifests", lambda: [{"id": "traefik", "_root": "platform-base"},
                                                         {"id": "console", "_root": "platform-base"},
                                                         {"id": "drive", "_root": "apps"}])
    monkeypatch.setattr(app, "_disposition", lambda entry: "enabled" if (entry or {}).get("enabled") or (entry or {}).get("state") == "enabled" else "disabled")
    return store


def test_an_office_that_runs_a_layer3_app_is_installed_even_without_a_record(plane, monkeypatch):
    # the offices that predate the wizard: twenty apps on, no office: block — never the wizard again
    monkeypatch.setattr(app, "_load_state", lambda: {"traefik": {"enabled": True}, "drive": {"state": "enabled", "by": "user"}})
    r = app.app.test_client().get("/api/office")
    assert r.get_json() == {"office": {}, "installed": True}


def test_a_core_app_alone_does_not_make_an_office_installed(plane):
    assert app.app.test_client().get("/api/office").get_json()["installed"] is False


def test_a_fresh_office_is_not_installed_and_has_an_empty_record(plane):
    r = app.app.test_client().get("/api/office")
    assert r.status_code == 200
    assert r.get_json() == {"office": {}, "installed": False}


def test_the_wizards_record_makes_the_office_installed(plane):
    c = app.app.test_client()
    r = c.put("/api/office", json=RECORD)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["installed"] is True and r.get_json()["office"]["animal"] == "deer"
    assert plane == RECORD
    assert c.get("/api/office").get_json()["installed"] is True


def test_a_record_without_an_installed_at_is_a_wizard_still_running(plane):
    r = app.app.test_client().put("/api/office", json={"name": "הלשכה", "animal": "elephant", "hue": "muted"})
    assert r.status_code == 200 and r.get_json()["installed"] is False


def test_a_linked_office_does_not_write_this_offices_identity(plane):
    r = app.app.test_client().put("/api/office", json=RECORD, headers={app.OFFICE_HEADER: "macbook"})
    assert r.status_code == 403
    assert "linked office" in r.get_json()["error"]
    assert plane == {}                                   # nothing was written


def test_a_record_the_compiler_refuses_is_refused_with_its_sentence_and_nothing_is_written(plane):
    r = app.app.test_client().put("/api/office", json={"colour": "#ff0000"})
    assert r.status_code == 400
    assert "unknown field 'colour'" in r.get_json()["error"]
    assert r.get_json()["errors"] == ["office: unknown field 'colour' (the fields are name, animal, …)"]
    assert plane == {}


def test_a_body_that_is_not_an_object_is_refused(plane):
    c = app.app.test_client()
    assert c.put("/api/office", json=["name"]).status_code == 400
    assert c.put("/api/office", data="not json", content_type="application/json").status_code == 400
    assert plane == {}


def test_a_compiler_that_cannot_be_asked_is_a_500_not_a_fresh_office(plane, monkeypatch):
    def boom():
        raise RuntimeError("office-get failed: no such file")
    monkeypatch.setattr(app, "_office_get", boom)
    r = app.app.test_client().get("/api/office")
    assert r.status_code == 500 and "office-get failed" in r.get_json()["error"]
