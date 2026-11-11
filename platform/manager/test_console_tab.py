#!/usr/bin/env python3
"""test_console_tab — an app's `module.tab: true` reaches the console's tiles (DGO-1800, reading 02).

    python3 platform/manager/test_console_tab.py      # needs PyYAML (reconcile.py imports it)

The console's bar on a phone named four layer-3 apps in its own layer-2 code (app.js buildBottomNav). The faithful
fix is that each app declares it wants the place, as it declares its name and icon, and the console reads the
declaration. The compiler writes an explicit key list for every tile, so the key has to be carried through: here
for reconcile.py, and by the render oracle (packaging/dgo/internal/compiler/render_test.go) for its Go twin.
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_console_tab", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_console_tab"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


def _app(aid, **module):
    m = {"name": aid, "icon": "x", "group": "עסק", "alias": aid}
    m.update(module)
    return {"id": aid, "layer": 3, "routing": [{"host": aid, "port": 80, "module": m}]}


class ConsoleTab(unittest.TestCase):
    def tiles(self, cat):
        with tempfile.TemporaryDirectory() as tmp:
            gen = pathlib.Path(tmp) / ".generated"
            old = rc.GEN
            rc.GEN = gen
            try:
                rc.render_registries(cat, list(cat))
                text = (gen / "registry" / "console.modules.yaml").read_text(encoding="utf-8")
            finally:
                rc.GEN = old
        return {t["id"]: t for t in yaml.safe_load(text)}

    def test_a_declared_tab_reaches_the_tile_embedded_and_framed(self):
        tiles = self.tiles({"drive": _app("drive", tab=True),
                            "plane": _app("plane", tab=True, external=True)})
        self.assertIs(tiles["drive"].get("tab"), True)
        self.assertIs(tiles["plane"].get("tab"), True)
        self.assertTrue(tiles["plane"].get("external"))

    def test_no_tab_unless_it_is_declared_true(self):
        tiles = self.tiles({"a": _app("a"), "b": _app("b", tab=False), "c": _app("c", tab="yes"),
                            "d": _app("d", tab=1, external=True)})
        for aid in "abcd":
            self.assertNotIn("tab", tiles[aid], aid)

    def test_the_schema_declares_it(self):
        schema = json.loads(rc.SCHEMA.read_text(encoding="utf-8"))
        module = schema["properties"]["routing"]["items"]["properties"]["module"]
        self.assertFalse(module.get("additionalProperties", True))       # an undeclared key is refused there
        self.assertEqual(module["properties"]["tab"]["type"], "boolean")


if __name__ == "__main__":
    unittest.main()
