"""The sync-registry hook writes to the tenant it reads (DGO-1815).

    python3 apps/indox/tests/test_sync_converge_names_instance.py

apps/indox/hooks/sync-registry-converge.py resolves one tenant (--instance / INDOX_INSTANCE, else the sole enabled
production tenant — purpose not 'test' — and it refuses two) and reads that tenant's schema; but its writes through
the BFF (POST/PATCH /sync/registry) named no `?instance=`, so they landed on the BFF's default instance. What holds,
with no stack and no database: every BFF address the hook builds names the resolved tenant's id, and the tenant is
resolved by the registry rule before the first one.

SYNC_CONVERGE_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import importlib.util
import os
import pathlib
import unittest

ROOT = pathlib.Path(os.environ.get("SYNC_CONVERGE_ROOT") or pathlib.Path(__file__).resolve().parents[3])
HOOK = ROOT / "apps/indox/hooks/sync-registry-converge.py"


def load(psql_rows):
    spec = importlib.util.spec_from_file_location("sync_registry_converge", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    asked = []
    mod.psql = lambda dn, sql: (asked.append(sql), "\n".join(psql_rows))[1]
    return mod, asked


REGISTRY = ["example|indox_example|", "test|indox_test|test"]


class SyncConvergeNamesInstance(unittest.TestCase):
    def test_every_bff_address_names_the_resolved_tenant(self):
        mod, asked = load(REGISTRY)
        self.assertTrue(hasattr(mod, "bff_url"), "the hook builds its BFF addresses in one place")
        self.assertEqual(mod.bff_url("staging", "/sync/registry"),
                         mod.BFF_BASE + "/sync/registry?instance=example")
        self.assertEqual(mod.bff_url("staging", "/sync/registry/drive-in?x=1"),
                         mod.BFF_BASE + "/sync/registry/drive-in?x=1&instance=example")
        self.assertEqual(len(asked), 1, "the registry is read once per run")

    def test_the_read_and_the_write_name_the_same_tenant(self):
        mod, _ = load(REGISTRY)
        self.assertEqual(mod.resolve_tenant("staging"), "indox_example")
        self.assertTrue(mod.bff_url("staging", "/sync/registry").endswith("?instance=example"))

    def test_a_declared_instance_wins_and_two_production_tenants_refuse(self):
        mod, _ = load(REGISTRY)
        self.assertEqual(mod.resolve_tenant("staging", "test"), "indox_test")
        self.assertTrue(mod.bff_url("staging", "/sync/registry").endswith("?instance=test"))
        two, _ = load(REGISTRY + ["exampleu|indox_exampleu|"])
        with self.assertRaises(SystemExit):
            two.bff_url("staging", "/sync/registry")

    def test_what_bff_sends_names_the_tenant_and_quotes_a_pipe_name(self):
        mod, _ = load(REGISTRY)
        sent = []

        class Done:
            stdout, stderr = '{"http": 200, "body": {}}', ""

        mod.sh = lambda cmd, timeout=120: (sent.append(cmd), Done)[1]
        mod.bff("staging", "POST", "/sync/registry", {"name": "x"})
        code = sent[-1][-1]          # the python the hook runs inside INDOX's container
        self.assertIn(repr(mod.BFF_BASE + "/sync/registry?instance=example"), code)
        src = HOOK.read_text(encoding="utf-8")
        self.assertIn("f\"/sync/registry/{urllib.parse.quote(name, safe='')}\"", src)

    def test_a_schema_without_an_id_is_refused_not_sent_to_the_default(self):
        mod, _ = load([])
        mod._TENANT_SCHEMA, mod._TENANT_ID = "indox_example", None
        with self.assertRaises(SystemExit):
            mod.bff_url("staging", "/sync/registry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
