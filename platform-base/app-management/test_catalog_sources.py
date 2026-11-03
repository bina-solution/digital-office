"""DGO-604 (cyc-204): the catalog routes take an app only from a catalog source.

`GET /api/catalog?ref=` handed its parameter to `catalog.fetch`, which pulls any http(s) address from
inside the office network and reads any local path, and `POST /api/catalog/preview` did the same with a
`ref` from its body — for a linked office through the door too. What these hold:

- the index route never reads `?ref=` and never echoes it;
- preview refuses a linked caller (403), a local path, `file://` and `http://` (400), and never stages them;
- an https address is fetched only in the `warn` stage, only from a public address, never through a
  redirect, and is refused outright in the `refuse` stage;
- an app id goes through the signed index, always this office's own (a caller-named index is ignored).

The catalog and the installer are replaced by fakes that record what they were asked, so nothing here
touches the network or the disk. Run: python -m pytest platform-base/app-management/test_catalog_sources.py -q
"""
import importlib.util
import pathlib
import re
import socket
import sys
import types
import urllib.error
import urllib.request

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_catalog_sources", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_catalog_sources"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")      # appinstall.ID_RE


@pytest.fixture
def seen(monkeypatch):
    """Fakes for the catalog and the installer; `seen` lists every fetch, index load and stage."""
    calls = {"index": [], "stage": [], "fetch": []}

    def load_index(ref, require_signature=True):
        calls["index"].append(ref)
        return {"repo": "local", "entries": []}, {"signature": "ok"}

    cat = types.SimpleNamespace(DEFAULT_OUT=pathlib.Path("/office/catalog"), INDEX_NAME="index.json",
                                load_index=load_index)

    def stage(ref, index_ref=None, **kw):
        calls["stage"].append((ref, index_ref))
        return pathlib.Path("/tmp/staged"), {"ref": ref, "verified": False}

    inst = types.SimpleNamespace(_looks_like_id=lambda r: bool(ID_RE.match(r)), stage=stage,
                                 inspect=lambda d, p: ({"id": "demo", "version": "1"}, {}, {}, {}, []))
    monkeypatch.setattr(app, "catalog_mod", cat)
    monkeypatch.setattr(app, "appinstall", inst)
    monkeypatch.setattr(app, "_fetch_public", lambda url, dest: (calls["fetch"].append(url),
                                                                   pathlib.Path(dest).write_bytes(b"zip")))
    monkeypatch.setattr(app, "CATALOG_URL_REFS", "warn")
    return calls


def _public(monkeypatch, ip="93.184.216.34"):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", (ip, 443))])


client = app.app.test_client()


@pytest.mark.parametrize("ref", ["http://connections:8990/api/instances", "/etc/hostname", "file:///etc/passwd"])
def test_the_index_route_does_not_read_ref(seen, ref):
    r = client.get("/api/catalog", query_string={"ref": ref})
    assert r.status_code == 200
    assert seen["index"] == ["/office/catalog/index.json"], seen["index"]
    assert ref not in r.get_data(as_text=True)


@pytest.mark.parametrize("ref", ["/etc/hostname", "../../.env", "file:///etc/passwd",
                                 "http://connections:8990/api/instances", "http://169.254.169.254/latest"])
def test_preview_refuses_what_is_not_a_catalog_source(seen, ref):
    r = client.post("/api/catalog/preview", json={"ref": ref})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert seen["stage"] == [] and seen["fetch"] == []


def test_preview_refuses_a_linked_office(seen):
    r = client.post("/api/catalog/preview", json={"ref": "drive"}, headers={"X-DGO-Office": "hp-laptop"})
    assert r.status_code == 403
    assert seen["stage"] == []


def test_an_id_goes_through_the_office_own_index_only(seen):
    r = client.post("/api/catalog/preview", json={"ref": "drive", "index": "http://evil.example/index.json"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert seen["stage"] == [("drive", None)]


def test_https_to_a_private_address_is_not_fetched(seen, monkeypatch):
    _public(monkeypatch, "10.0.0.5")
    r = client.post("/api/catalog/preview", json={"ref": "https://internal.example/app.zip"})
    assert r.status_code == 400 and seen["fetch"] == [] and seen["stage"] == []


def test_https_to_a_public_address_is_fetched_in_the_warn_stage(seen, monkeypatch):
    _public(monkeypatch)
    r = client.post("/api/catalog/preview", json={"ref": "https://apps.example/demo.zip", "allow_unverified": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert seen["fetch"] == ["https://apps.example/demo.zip"]
    staged, index = seen["stage"][0]
    assert staged.endswith("demo.zip") and not staged.startswith("https://") and index is None
    assert r.get_json()["provenance"]["ref"] == "https://apps.example/demo.zip"


def test_https_on_another_port_is_not_fetched(seen, monkeypatch):
    _public(monkeypatch)
    r = client.post("/api/catalog/preview", json={"ref": "https://apps.example:8443/demo.zip"})
    assert r.status_code == 400 and seen["fetch"] == []


def test_https_is_refused_in_the_refuse_stage(seen, monkeypatch):
    _public(monkeypatch)
    monkeypatch.setattr(app, "CATALOG_URL_REFS", "refuse")
    r = client.post("/api/catalog/preview", json={"ref": "https://apps.example/demo.zip"})
    assert r.status_code == 400 and seen["fetch"] == []


def test_a_redirect_is_refused_not_followed():
    req = urllib.request.Request("https://apps.example/demo.zip")
    with pytest.raises(urllib.error.HTTPError, match="not followed"):
        app._NoRedirect().redirect_request(req, None, 302, "Found", {}, "http://connections:8990/")


def test_an_upload_is_still_accepted(seen):
    import io
    r = client.post("/api/catalog/preview", data={"file": (io.BytesIO(b"zip"), "demo.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert seen["stage"] and seen["stage"][0][0].endswith("demo.zip")
