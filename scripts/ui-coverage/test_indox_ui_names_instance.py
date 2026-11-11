"""`bbox indox ui-qa` compares the screen with the same tenant the screen shows (DGO-1815).

    python3 scripts/ui-coverage/test_indox_ui_names_instance.py

scripts/ui-coverage/e2e/test_indox_ui.py measures every number on INDOX's screens against a live API query (its
«yardsticks»). The UI scopes its calls with the instance its front door opens (webapp/src/App.tsx: the first enabled
entry of /instances); the yardsticks named none, so INDOX answered them on its default instance, and on an office
with two tenants the screen was compared with another tenant. What holds, with no browser and no office: the driver
picks the UI's own default, and every API call it makes names it (unless the call names one already).

UIQA_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import importlib.util
import os
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(os.environ.get("UIQA_ROOT") or pathlib.Path(__file__).resolve().parents[2])
DRIVER = ROOT / "scripts/ui-coverage/e2e/test_indox_ui.py"


def load(sent):
    # the driver imports its sibling `common` (browser plumbing); a stand-in records the API calls
    common = types.ModuleType("common")
    common.ARTIFACTS = pathlib.Path("/tmp")
    common.Suite = object
    common.container_request = lambda svc, path, method="GET", body=None, port=0: (sent.append((method, path)), (200, {}))[1]
    for name in ("incoming_documents_base_url", "new_browser", "new_context", "settle"):
        setattr(common, name, lambda *a, **k: None)
    with mock.patch.dict(sys.modules, {"common": common}):    # the stand-in never outlives the load
        spec = importlib.util.spec_from_file_location("test_indox_ui_driver", DRIVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class IndoxUiNamesInstance(unittest.TestCase):
    def test_the_driver_picks_the_uis_own_default(self):
        mod = load([])
        rows = [{"id": "example", "enabled": True}, {"id": "test", "enabled": True}]
        self.assertEqual(mod.first_enabled(rows), "example")
        self.assertEqual(mod.first_enabled([{"id": "old", "enabled": False}, {"id": "main", "enabled": True}]), "main")
        self.assertEqual(mod.first_enabled([{"id": "old", "enabled": False}]), "", "none enabled: App.tsx names none")
        self.assertEqual(mod.first_enabled([]), "")

    def test_the_standing_test_tenant_is_never_the_default_when_a_production_one_is_enabled(self):
        mod = load([])
        # /instances is ordered by id: Exampleu's own tenant sorts AFTER «test»
        rows = [{"id": "test", "enabled": True, "purpose": "test"}, {"id": "exampleu", "enabled": True, "purpose": ""}]
        self.assertEqual(mod.first_enabled(rows), "exampleu")
        self.assertEqual(mod.first_enabled([{"id": "test", "enabled": True, "purpose": "test"}]), "test",
                         "only the test tenant: it is the one the UI opens")
        self.assertEqual(mod.first_enabled([{"id": "test", "enabled": True, "purpose": "test"},
                                            {"id": "exampleu", "enabled": False, "purpose": ""}]), "test",
                         "a disabled production tenant is not the default")
        self.assertEqual(mod.first_enabled([{"id": "example", "enabled": True}, {"id": "test", "enabled": True}]),
                         "example", "an older INDOX with no purpose: the first enabled, as before")

    def test_every_yardstick_names_the_instance(self):
        sent = []
        mod = load(sent)
        mod.INSTANCE = "example"
        mod.dash("http://x", period="all")
        mod.query("http://x", "main", None)
        mod.api("http://x", "/repos")
        mod.api("http://x", "/documents?instance=test")
        self.assertEqual([p for _, p in sent], [
            "/incomingDocuments/dashboard/stats?period=all&instance=example",
            "/incomingDocuments/repos/main/documents/query?instance=example",
            "/incomingDocuments/repos?instance=example",
            "/incomingDocuments/documents?instance=test",
        ])

    def test_no_instance_known_names_none(self):
        sent = []
        mod = load(sent)
        mod.INSTANCE = ""
        mod.api("http://x", "/repos")
        self.assertEqual(sent[-1][1], "/incomingDocuments/repos")


if __name__ == "__main__":
    unittest.main(verbosity=2)
