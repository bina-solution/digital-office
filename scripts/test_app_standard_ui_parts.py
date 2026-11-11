#!/usr/bin/env python3
"""test_app_standard_ui_parts — the ui column's parts in the app standard are the gates' own verdicts (DGO-1053).

    python3 scripts/test_app_standard_ui_parts.py      # needs PyYAML (measure.py imports the compiler)

What is asked, on this tree: every app has the four parts (palette, menu, address, phone) and the section lists
exactly the apps with a tile; each part is what its gate says — palette a colour count from G82's own scan, None
exactly where G82 reads no file of the app; «own» menus exactly G107's KNOWN owners (the console among them); an
address only for an app with a tile the shell frames (`embed`), its ✗ set exactly G83's own `unrouted()` over
them, hello-bina «allowed» by G83's ALLOWED, n8n (a link-out tile) None; phone not read from files (None); and the
parts decide no cell (`compare` finds nothing lost or closed when every part changes).
"""
import importlib.util
import json
import pathlib
import unittest

import yaml  # noqa: F401 — measure.py imports the compiler, which needs it: said here, so G72 names it NOT RUN where absent

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("measure_under_test", ROOT / "scripts/app-standard/measure.py")
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


class Parts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat, rows, console, published, doors = measure.catalog()
        cls.apps = {aid: (man["_dir"].parent.name, man) for aid, man in sorted(cat.items())}
        cls.console = console
        cls.parts = measure.ui_parts(cls.apps, console)

    def test_every_app_has_the_four_parts(self):
        for aid in self.apps:
            self.assertEqual(set(self.parts[aid]), {"palette", "menu", "address", "phone"}, aid)
            self.assertIsNone(self.parts[aid]["phone"], aid)

    def test_palette_is_g82s_own_reading(self):
        pal = measure._gate("palette-lint")
        owners = {measure._owner(rel) for rel in pal.tracked()} - {None}
        found = sum(len(h) for rel, h in pal.scan().items() if measure._owner(rel))
        self.assertEqual(sum(p["palette"] or 0 for p in self.parts.values()), found)
        for aid in self.apps:                                             # a count where G82 reads, None where not
            self.assertEqual(self.parts[aid]["palette"] is not None, aid in owners, aid)

    def test_menu_follows_g107(self):
        menu = measure._gate("menu-host-lint")
        known = {measure._owner(rel) for rel in menu.KNOWN}
        own = {aid for aid, p in self.parts.items() if p["menu"] == "own"}
        self.assertEqual(own, known)                  # G107 passes on this tree: «own» is exactly its KNOWN debt
        self.assertEqual(self.parts["console"]["menu"], "own")

    def test_address_is_g83s_verdict_on_g83s_selection(self):
        route = measure._gate("embed-route-lint")
        rows, external = [], set()
        for aid, (root, _man) in self.apps.items():
            framed = {t["kind"] for t in self.console.get(aid, []) if t.get("embed")}
            self.assertEqual(self.parts[aid]["address"] is not None, bool(framed), aid)   # only what G83 asks
            if framed:
                rows.append((aid, f"{root}/{aid}"))
                if "external" in framed:
                    external.add(f"{root}/{aid}")
        failing = {alias for alias, _d in route.unrouted(rows, external)}
        self.assertEqual(failing, {aid for aid, p in self.parts.items() if p["address"] is False})
        self.assertEqual(self.parts["hello-bina"]["address"], "allowed")  # G83's ALLOWED, with its reason
        self.assertIsNone(self.parts["n8n"]["address"])                   # a link-out tile: G83 never asks it

    def test_the_section_lists_the_apps_with_a_tile(self):
        inv = {"apps": [{"app": aid, "ui": {"ok": bool(self.console.get(aid)), "parts": self.parts[aid]}}
                        for aid in self.apps]}
        rows = [ln for ln in measure.ui_parts_table(inv) if ln.startswith("| `")]
        self.assertEqual(sorted(ln.split("`")[1] for ln in rows), sorted(a for a in self.apps if self.console.get(a)))

    def test_the_parts_decide_no_cell(self):
        old = json.loads(measure.OUT_JSON.read_text(encoding="utf-8"))
        changed = json.loads(json.dumps(old))
        for r in changed["apps"]:
            r["ui"]["parts"] = {"palette": 99, "menu": "own", "address": False, "phone": None}
        self.assertEqual(measure.compare(old, changed), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=1)
