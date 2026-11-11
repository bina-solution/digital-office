"""INDOX's web UI scopes every call to its BFF with the instance on screen (DGO-1815).

    python3 apps/indox/tests/test_web_ui_scopes_every_call.py

`call()` applies `withInstance()`; two hand-built `fetch()`s did not — the documents CSV export, which INDOX then
answered on the default instance (handing over the first client's documents whatever instance the operator was
looking at), and the extraction upload (which reads no schema itself, so for it the scope is consistency and one
call fewer in INDOX's no-instance log). What holds: in apps/indox/app/webapp/src/api.ts every use of the BFF's
prefix (`${API_PREFIX}`) — a fetch, or a URL builder whose string an `<img src>` or `<a href>` renders — is followed
directly by `${withInstance(`, and the prefix is never concatenated (`API_PREFIX +`) or exported.

WEB_SCOPE_ROOT=<a checkout> runs the same check on another tree (the proof that it catches the old file).
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("WEB_SCOPE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
API = ROOT / "apps/indox/app/webapp/src/api.ts"
USE = re.compile(r"\$\{API_PREFIX\}(.{0,60})")


class WebUiScopesEveryCall(unittest.TestCase):
    def test_every_use_of_the_bff_prefix_goes_through_with_instance(self):
        text = API.read_text(encoding="utf-8")
        uses = USE.findall(text)
        self.assertGreaterEqual(len(uses), 5, "uses of ${API_PREFIX} found: %d" % len(uses))
        unscoped = [u for u in uses if not u.startswith("${withInstance(")]
        self.assertEqual(unscoped, [], "a use of the BFF's prefix with no instance")

    def test_the_prefix_is_never_concatenated_or_handed_out(self):
        text = API.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"API_PREFIX\s*\+|\+\s*API_PREFIX")
        self.assertNotRegex(text, r"export\s+(const|let|var)\s+API_PREFIX|export\s*\{[^}]*\bAPI_PREFIX\b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
