#!/usr/bin/env python3
"""test_herd_offices — which linked offices are the owner's own herd, compiled into computers' registry (DGO-1800).

    python3 platform/manager/test_herd_offices.py      # needs PyYAML (reconcile.py imports it)

computers keeps the whole view for a door read from a herd office and narrows every other linked office to what
it was given. An office is the herd's by its WireGuard KEY, never by its name (herd.yaml: «a client's machine may
be called `portable`») — so the registry carries each office's key and the set of keys; ids and aliases are only
said. Read as YAML, failing closed. The Go twin writes the same file, held by the render oracle
(packaging/dgo/internal/compiler/render_test.go) and herdoffices_test.go — the same cases, the same JSON.
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent
K1, K2 = "A" * 43 + "=", "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8="


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_herd_offices", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_herd_offices"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()

# (name, herd.yaml text, the JSON both compilers write) — herdoffices_test.go holds the same three
CASES = [
    ("each office by its key; aliases said, quoted or not, bad and repeated ones dropped; one without a key is none",
     "offices:\n"
     f"  a:\n    label: A\n    wg_public_key: '{K1}'\n    aliases: ['a-1', \"a2\", BAD, a-1, 7, x/y]   # a comment\n"
     f"  b:\n    wg_public_key: {K2}\n"
     "  nokey:\n    aliases: [portable]\n"
     "  badkey:\n    wg_public_key: 'not-a-key'\n"
     "hub: a\n",
     {"offices": {"a": {"wg_public_key": K1, "aliases": ["a-1", "a2"]}, "b": {"wg_public_key": K2, "aliases": []}},
      "keys": sorted([K1, K2])}),
    ("a duplicate key is its last, as safe_load reads it",
     f"offices:\n  a:\n    wg_public_key: '{K1}'\n    aliases: [one]\n    aliases: [two]\n",
     {"offices": {"a": {"wg_public_key": K1, "aliases": ["two"]}}, "keys": [K1]}),
    ("no offices block", "hub: vps1\n", {"offices": {}, "keys": []}),
    ("an id YAML does not type as a string is no office", f"offices:\n  7:\n    wg_public_key: '{K1}'\n",
     {"offices": {}, "keys": []}),
    ("not YAML", "offices: [unclosed\n", {"offices": {}, "keys": []}),
    ("an empty file (safe_load gives None)", "", {"offices": {}, "keys": []}),
]


class HerdOffices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / "apps" / "computers").mkdir(parents=True)
        self.keep, rc.REPO = rc.REPO, self.repo

    def tearDown(self):
        rc.REPO = self.keep
        self.tmp.cleanup()

    def herd(self, text):
        (self.repo / "apps" / "computers" / "herd.yaml").write_text(text, encoding="utf-8")
        return rc.herd_offices()

    def test_the_real_herd_is_its_four_offices_by_their_keys(self):
        rc.REPO = HERE.parent.parent
        got = rc.herd_offices()
        self.assertEqual(sorted(got["offices"]), ["dell", "hp-laptop", "macbook", "vps1"])
        self.assertEqual(got["offices"]["dell"]["aliases"], ["portable-ubuntu", "portable"])
        self.assertEqual(len(got["keys"]), 4)
        self.assertNotIn("portable", json.dumps(got["keys"]))   # a name is never an identity

    def test_the_cases_both_compilers_hold(self):
        for name, text, want in CASES:
            self.assertEqual(self.herd(text), want, name)

    def test_a_herd_file_that_cannot_be_read_gives_no_office(self):
        self.assertEqual(rc.herd_offices(), {"offices": {}, "keys": []})            # absent
        (self.repo / "apps" / "computers" / "herd.yaml").write_bytes(b"offices:\n  a: \xff\n")
        self.assertEqual(rc.herd_offices(), {"offices": {}, "keys": []})            # not UTF-8


if __name__ == "__main__":
    unittest.main()
