"""A peer's CONSOLE, once that peer publishes it as mountable, becomes a door on this console (DGO-553).

The chain has four links, and each is proven somewhere different:

  1. the serving office declares `path_mount` and publishes the console as `embedded` — asserted by
     `test_path_mount.py`;
  2. this office compiles that catalog row into a tile WITH a door — asserted here;
  3. the console's proxy reaches that door at `/a/console-home.<office>/` — measured live on
     2026-11-01 with a stand-in door (page, mount.js, /api/version, /api/modules, an app tile and a
     stylesheet all answered through the mount);
  4. the mounted shell keeps every URL inside the mount — `platform-base/console/test_mount.mjs`.

What is left unproven is the pair of OFFICES, and that is a deployment fact, not a code fact: until
the other office runs this version its catalog still says `external`, and the asserts at the bottom
of this file say exactly what that looks like, so a future reader can tell "not upgraded yet" from
"broken".

Run: python3 platform/manager/test_serve_console_door.py   (or pytest)
"""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


serve = _load("serve")


def _state(module_kind: str, office: str = "macbook", address: str = "10.79.5.2") -> dict:
    """A `remote:` block as this office stores it: what the PEER's catalog said about its own apps."""
    return {"remote": [{
        "office": office,
        "label": {"he": "MacBook", "en": "MacBook"},
        "link": office,
        "address": address,
        "commit": "abc123",
        # the door HERE for that pair (per OFFICE, not per app): every UI route of that office
        # targets `http://<alias>.<office>:<link_port>`
        "link_port": 9005,
        "apps": [{
            "app": "console", "alias": "console-home", "port": 8000, "name": "המרכז",
            "icon": "home", "group": "ראשי", "desc": "מסך הבית של הלשכה",
            "module": {"kind": module_kind, "path": "/a/console-home/", "id": "console"},
            "host": "console.localhost", "health": "/healthz",
            "identity": {"to": "akadmin"},
        }],
    }]}


def _tile(module_kind: str):
    entries, errs = serve.plan(_state(module_kind), {})
    assert not errs, errs
    tiles = serve.module_entries(entries, {})
    return next(t for t in tiles if str(t.get("id", "")).startswith("console-home.")), entries


def test_a_mountable_console_gets_a_proxy_and_a_door():
    tile, _ = _tile("embedded")
    assert tile["id"] == "console-home.macbook", "the tile is namespaced by its office"
    assert tile.get("proxy") == "/a/console-home.macbook/", (
        "the shell frames it through THIS console's origin, not a host of its own")
    door = tile.get("door") or {}
    assert door.get("base") == "http://console-home.macbook:9005", (
        "the door's base is the link proxy at the peer's published link port")
    assert door.get("host") == "console.localhost", (
        "the authority the peer's console answers under — a request without it routes to nothing")
    assert door.get("user") == "akadmin", (
        "the identity the far side becomes; the peer declared it, this office only carries it")


def test_a_console_that_owns_its_origin_gets_no_door():
    # What a peer that predates `path_mount` publishes, and what any app that owns its origin still
    # gets: no proxy, no door — the shell falls back to the nested host, which on a `*.localhost`
    # office cannot sign a browser in inside a frame. Distinguishing these two is the point.
    tile, _ = _tile("external")
    assert "door" not in tile and "proxy" not in tile
    assert tile["host"] == "console-home.macbook", "framed on a host of its own instead"


def test_the_door_is_only_for_an_app_the_peer_declared_mountable():
    # Nothing here overrides the peer: this office renders what it was given.
    for kind, want_door in (("embedded", True), ("external", False)):
        tile, _ = _tile(kind)
        assert bool(tile.get("door")) is want_door, kind


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                     # noqa: BLE001 — a runner reports, never hides
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"test_serve_console_door — {fails} failing")
    sys.exit(1 if fails else 0)
