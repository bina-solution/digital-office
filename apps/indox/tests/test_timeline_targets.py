"""Which INDOX instances one /timeline/spans call is served for (DGO-1815).

    python3 apps/indox/tests/test_timeline_targets.py

any-concurrency's INDOX lane cannot name an instance, and an instance-less call was answered from INDOX's default
schema — the first client's books. apps/indox/app/incoming_documents/core/timeline_targets.py decides, and holds:
a named instance is served alone (as before); none named → every enabled instance in the registry, in its order;
an unreadable or empty registry keeps the old answer (the default schema); a row with an unsafe id or schema is
never served. (The endpoint's own loop is tested in incoming_documents/tests/unit/test_timeline_every_instance.py.)

TIMELINE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import importlib.util
import os
import pathlib
import unittest

ROOT = pathlib.Path(os.environ.get("TIMELINE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
MOD = ROOT / "apps/indox/app/incoming_documents/core/timeline_targets.py"


def rule():
    spec = importlib.util.spec_from_file_location("timeline_targets", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.timeline_targets


REG = [{"id": "example", "schema_name": "indox_example", "enabled": True},
       {"id": "test", "schema_name": "indox_test", "enabled": True},
       {"id": "old", "schema_name": "indox_old", "enabled": False}]


class TimelineTargets(unittest.TestCase):
    def test_a_named_instance_is_served_alone(self):
        self.assertEqual(rule()("exampleu", "indox_exampleu", REG), [("exampleu", "indox_exampleu")])

    def test_none_named_serves_every_enabled_instance(self):
        self.assertEqual(rule()(None, None, REG), [("example", "indox_example"), ("test", "indox_test")])

    def test_the_standing_test_tenant_is_not_the_offices_work(self):
        reg = [dict(REG[0], purpose=""), dict(REG[1], purpose="test"),
               {"id": "exampleu", "schema_name": "indox_exampleu", "enabled": True, "purpose": ""}]
        self.assertEqual(rule()(None, None, reg), [("example", "indox_example"), ("exampleu", "indox_exampleu")])
        self.assertEqual(rule()(None, None, [dict(REG[1], purpose="test")]), [("", None)],
                         "only the test tenant: the old answer, not the suite's runs")

    def test_an_unread_or_empty_registry_keeps_the_old_answer(self):
        self.assertEqual(rule()(None, None, None), [("", None)])
        self.assertEqual(rule()(None, None, []), [("", None)])

    def test_an_unsafe_row_is_never_served(self):
        bad = [{"id": "x; drop", "schema_name": "indox_x", "enabled": True},
               {"id": "y", "schema_name": "public\"; --", "enabled": True}]
        self.assertEqual(rule()(None, None, bad), [("", None)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
