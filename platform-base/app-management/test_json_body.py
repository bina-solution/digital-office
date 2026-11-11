"""A JSON body that is not an object is refused by name — 400, never a 500 (DGO-607).

enable, move, uninstall, catalog preview and catalog install read their body with `get_json(silent=True) or {}`
and then `.get(...)` — so a truthy body that is not an object (a list, a number, a string) raised AttributeError
and the route answered 500 with a traceback. A falsy one (`[]`, `0`, `""`, no body) still means `{}`, as before
and as the native twin's guard reads a plain switch-on (packaging/dgo internal/serve `plainSwitchOn`).

Run: python -m pytest platform-base/app-management/test_json_body.py -q      (in the app's image: it needs Flask)
On the code before DGO-607 the refused cases fail: four routes answer 500, and the preview's catch-all answers 400
with Python's own words ("'list' object has no attribute 'get'"), which names no JSON object.
"""
import glob
import importlib.util
import os
import pathlib
import sys
import tempfile

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_json_body", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_json_body"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
NOT_OBJECTS = [[1], "x", 5, True]
ROUTES = [("/api/apps/drive/enable", "enable"), ("/api/apps/drive/move", "move"), ("/api/apps/drive/uninstall", "uninstall"),
          ("/api/catalog/preview", "preview"), ("/api/catalog/install", "install")]


@pytest.fixture
def plane(monkeypatch):
    """Everything a route checks BEFORE it reads the body says yes: a known layer-3 app, a docker socket, a catalog."""
    monkeypatch.setattr(app, "_manifest", lambda aid: {"id": aid, "_root": "apps"})
    monkeypatch.setattr(app, "docker_sdk", object())
    monkeypatch.setattr(app, "appinstall", object())
    monkeypatch.setattr(app, "_stage_gc", lambda: None)
    monkeypatch.setattr(app, "_being_brought_up", lambda aid: None)
    monkeypatch.setattr(app, "_still_needed", lambda aid: None)
    return app.app.test_client()


@pytest.mark.parametrize("path,name", ROUTES)
@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_a_body_that_is_not_an_object_is_refused_by_name(plane, path, name, body):
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "bbox-install-*")))
    r = plane.post(path, json=body)
    assert r.status_code == 400, (name, body, r.status_code, r.get_data(as_text=True)[:300])
    assert "JSON object" in (r.get_json() or {}).get("error", ""), r.get_data(as_text=True)
    # the preview made its work directory before it read the body: a refusal leaves nothing behind
    assert set(glob.glob(os.path.join(tempfile.gettempdir(), "bbox-install-*"))) == before


@pytest.mark.parametrize("body", [[], 0, "", False])
def test_a_falsy_body_is_still_an_empty_object(plane, monkeypatch, body):
    """…as `or {}` always made it: enable goes on to its next question (here: the move to make, none), and is not
    refused for its body — the native twin's guard decides a plain switch-on the same way."""
    asked = []
    monkeypatch.setattr(app, "_lifecycle", lambda aid, enable, restore=None: (asked.append(restore), ("", 202))[1])
    r = plane.post("/api/apps/drive/enable", json=body)
    assert "JSON object" not in r.get_data(as_text=True)
    assert asked == [None], (r.status_code, r.get_data(as_text=True)[:300])
