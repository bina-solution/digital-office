"""The console as an installable app (DGO-1972): its web-app manifest, its icons, and the link that finds them.

What makes Chrome and Edge offer «Install» and put the office in the computer's list of apps: a manifest with a
name, a start URL inside its scope, a standalone display and a 192 and a 512 icon. The console is behind the
sign-in, so the page's link must ask for the manifest WITH cookies — without `crossorigin="use-credentials"`
the edge answers it with the sign-in's redirect and the browser finds no manifest at all.

Run: python -m pytest platform-base/console/test_app_manifest.py -q
"""
import json
import pathlib
import re
import struct

import pytest

STATIC = pathlib.Path(__file__).with_name("static")
MANIFEST = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def png_size(path):
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", head[16:24])


def test_the_page_links_the_manifest_with_its_cookies():
    links = re.findall(r"<link\b[^>]*\brel=\"manifest\"[^>]*>", INDEX)
    assert len(links) == 1, links
    assert 'href="/manifest.webmanifest"' in links[0]
    assert 'crossorigin="use-credentials"' in links[0]


def test_the_manifest_is_installable_and_opens_the_office_in_its_own_window():
    assert MANIFEST["name"] == "הלשכה הדיגיטלית" and MANIFEST["short_name"]
    assert MANIFEST["lang"] == "he" and MANIFEST["dir"] == "rtl"
    assert MANIFEST["display"] == "standalone"
    assert MANIFEST["id"] == "/" and MANIFEST["start_url"] == "/" and MANIFEST["scope"] == "/"


def test_it_names_no_colour_of_its_own():
    # one fixed colour cannot follow the office's two themes; the palette lives in the screens' tokens (G82)
    assert "theme_color" not in MANIFEST and "background_color" not in MANIFEST


@pytest.mark.parametrize("icon", MANIFEST["icons"], ids=lambda i: i["src"])
def test_every_icon_exists_at_the_size_it_declares(icon):
    path = STATIC / icon["src"].lstrip("/")
    assert path.is_file(), f"{icon['src']} is not in static/ (render it: python3 platform-base/console/app_icons.py)"
    w, h = (int(n) for n in icon["sizes"].split("x"))
    assert png_size(path) == (w, h)
    assert icon["type"] == "image/png"


def test_an_installable_set_of_icons():
    any_sizes = {i["sizes"] for i in MANIFEST["icons"] if i.get("purpose", "any") == "any"}
    assert {"192x192", "512x512"} <= any_sizes
    assert any(i.get("purpose") == "maskable" for i in MANIFEST["icons"])   # a phone's own shape


def test_the_console_serves_them_as_files_not_as_the_shell():
    flask = pytest.importorskip("flask")                                   # noqa: F841 — the console's own image has it
    import types
    module = types.ModuleType("console_manifest_under_test")
    module.__file__ = str(pathlib.Path(__file__).with_name("app.py"))
    exec(compile(pathlib.Path(module.__file__).read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)
    client = module.app.test_client()
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.mimetype == "application/manifest+json"
    assert json.loads(r.data)["name"] == MANIFEST["name"]
    for icon in MANIFEST["icons"]:
        r = client.get(icon["src"])
        assert r.status_code == 200 and r.mimetype == "image/png", icon["src"]
