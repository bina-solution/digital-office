"""UI-QA's address filler reads the instance the screens show, and seeds fixture documents only into `test` (DGO-1815).

    python3 scripts/ui-coverage/test_resolve_params_instance.py

scripts/ui-coverage/resolve_params.py fills `:repo`/`:id` for INDOX's screens. It read the documents with no instance
(INDOX's default), and when that table was empty it PUT the fixture documents there — on a fresh office the default is
a client's production books. What holds, with no office: the documents probe names the instance `:instance` names; it
seeds only when that instance's purpose is `test` (an INDOX that does not say purpose reads as production); the
instance is resolved before the documents, and the two merge into one entry.

RESOLVE_PARAMS_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import importlib.util
import os
import pathlib
import unittest

ROOT = pathlib.Path(os.environ.get("RESOLVE_PARAMS_ROOT") or pathlib.Path(__file__).resolve().parents[2])
MOD = ROOT / "scripts/ui-coverage/resolve_params.py"


def load():
    spec = importlib.util.spec_from_file_location("resolve_params", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ResolveParamsInstance(unittest.TestCase):
    def test_the_documents_probe_names_the_instance(self):
        code = load().indox_documents_code("http://x/incomingDocuments", "example", False)
        self.assertIn('D + "/query?instance=example"', code)
        self.assertNotIn('method="PUT"', code, "a production instance is never seeded")

    def test_only_a_test_instance_is_seeded_and_then_by_name(self):
        code = load().indox_documents_code("http://x/incomingDocuments", "test", True)
        self.assertIn('D + "?instance=test", data=body, method="PUT"', code)
        self.assertNotIn('method="PUT"', load().indox_documents_code("http://x/incomingDocuments", "", True),
                         "no instance known: nothing is seeded")

    def test_seeding_follows_the_purpose_and_the_order_merges(self):
        mod = load()
        calls = []
        mod.indox_probe = lambda build, timeout=60: (calls.append(build("http://x/incomingDocuments")),
                                                      '{":instance": "example", "purpose": ""}' if len(calls) == 1
                                                      else '{":repo": "main", ":id": "D1"}')[1]
        subs = {}
        instance, purpose = mod.indox_instances(subs)
        self.assertEqual((instance, purpose), ("example", ""))
        mod.indox(subs, instance, purpose)
        self.assertNotIn('method="PUT"', calls[-1], "purpose '' is production: not seeded")
        self.assertEqual(subs["incoming-documents"], {":instance": "example", ":repo": "main", ":id": "D1"})

    def test_a_test_instance_is_seeded_through_indox(self):
        mod = load()
        calls = []
        mod.indox_probe = lambda build, timeout=60: (calls.append(build("http://x/incomingDocuments")),
                                                      '{":repo": "main", ":id": "D1"}')[1]
        mod.indox({}, "test", "test")
        self.assertIn('D + "?instance=test", data=body, method="PUT"', calls[-1])

    def test_main_resolves_the_instance_before_the_documents(self):
        src = MOD.read_text(encoding="utf-8")
        body = src[src.index("def main()"):]
        self.assertLess(body.index("indox_instances(subs)"), body.index("indox(subs, instance, purpose)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
