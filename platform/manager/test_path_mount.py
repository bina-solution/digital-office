"""`path_mount` — an app that is not framed at home but CAN be mounted under a peer's path (DGO-553).

The console is the case this exists for. `embed: false` says "this office has one console and it is
the one you are looking at", so the compiler publishes the app as `external` and a linked office's
«המרכז» tile can only be opened on a host of its own — which, on a `*.localhost` office, cannot sign
a browser in inside a frame (measured 2026-10-05: the tile opened onto a browser error page). The
declaration says the other half: "not framed here, but servable under a path there".

Three things must hold, and each one is a way the change could be wrong:
  1. nothing about an app that does NOT declare it changes — the refusal stays as it was;
  2. the declaring app is published as `embedded`, which is what gives a peer the proxy and the door;
  3. it is still NOT framed in its own office's rail (the console must not appear inside itself).

Run: python -m pytest platform/manager/test_path_mount.py -q
"""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_path_mount", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_path_mount"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


def test_an_embedded_app_is_not_own_host():
    assert rc._own_host_only({"embed": True, "alias": "drive"}) is False


def test_an_external_app_stays_own_host():
    assert rc._own_host_only({"external": True}) is True
    assert rc._own_host_only({"embed": False}) is True
    assert rc._own_host_only({"embed": True, "passthrough": [{"path": "/api"}]}) is True


def test_path_mount_is_the_declared_exception():
    assert rc._own_host_only({"embed": False, "path_mount": True}) is False, (
        "an app that says it can live under a path is published as embedded")


def test_path_mount_does_not_rescue_a_passthrough_app():
    # A passthrough app answers the console's OWN origin paths, and an `external` one owns its
    # origin; neither is a matter of configuration, so `path_mount` overrides only the `embed: false`
    # half. Without this an app could be talked into a mount that was measured failing twice.
    assert rc._own_host_only({"external": True, "path_mount": True}) is True
    assert rc._own_host_only({"passthrough": [{"path": "/api"}], "path_mount": True}) is True


def test_the_console_declares_it_and_the_catalog_says_embedded():
    import json
    man = json.loads((HERE.parent.parent / "platform-base/console/app.json").read_text(encoding="utf-8"))
    modules = [r.get("module") or {} for r in (man.get("routing") or [])]
    console_tile = next((m for m in modules if m.get("alias") == "console-home"), None)
    assert console_tile is not None, "the console's own tile declaration exists"
    assert console_tile.get("embed") is False, "one office has one console: not framed at home"
    assert console_tile.get("path_mount") is True, "…and it CAN be mounted under a peer's path"
    assert rc._own_host_only(console_tile) is False, "so a peer is given a proxy and a door"


def test_an_own_host_app_and_a_mounted_one_are_both_representable():
    # The distinction has to survive into the published row, because that is what a peer reads.
    own = {"kind": "external" if rc._own_host_only({"embed": False}) else "embedded"}
    mounted = {"kind": "external" if rc._own_host_only({"embed": False, "path_mount": True})
               else "embedded"}
    assert own["kind"] == "external" and mounted["kind"] == "embedded"


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
    print(f"test_path_mount — {fails} failing")
    sys.exit(1 if fails else 0)
