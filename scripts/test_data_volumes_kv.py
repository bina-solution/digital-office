#!/usr/bin/env python3
"""G26's data.kv rule (DGO-1512): one app per redis database, and no `durable` claim on the office redis while its
backup hook carries no key.

Why it exists: any-concurrency declared n8n's db0 `durable: true` while platform-base/redis/hooks/backup skipped the
redis volume and failed the export on any key without a TTL — one of the two had to be wrong, and nobody was told.
Measured 2026-11-10 on vps1 and the Mac: db0 holds only n8n's queue and caches and the TTL'd flow streams; the
declaration moved to n8n as `durable: false`. These cases hold the rule on made-up manifests and on the real tree.

    python3 scripts/test_data_volumes_kv.py
"""
import importlib.util
import json
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("g26", REPO / "scripts/refactor/data-volumes-lint.py")
g26 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g26)

HOOK_NOW = (REPO / "platform-base/redis/hooks/backup").read_text(encoding="utf-8")


def man(*kv):
    return {"data": {"kv": list(kv)}}


class KvRule(unittest.TestCase):
    def test_a_durable_claim_on_the_office_redis_is_refused_while_the_hook_carries_nothing(self):
        got = g26.bad_kv({"demo": man({"instance": "redis", "db": 0, "durable": True})}, HOOK_NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("durable", got[0][1])

    def test_durable_is_the_schemas_default(self):
        self.assertEqual(len(g26.bad_kv({"demo": man({"instance": "redis", "db": 3})}, HOOK_NOW)), 1)

    def test_a_cache_or_queue_said_as_such_passes(self):
        self.assertEqual(g26.bad_kv({"demo": man({"instance": "redis", "db": 0, "durable": False})}, HOOK_NOW), [])

    def test_another_instance_is_its_own_apps_business(self):
        self.assertEqual(g26.bad_kv({"demo": man({"instance": "glitchtip-valkey", "db": 0, "durable": True})},
                                    HOOK_NOW), [])

    def test_a_hook_that_carries_keys_lifts_the_refusal(self):
        self.assertEqual(g26.bad_kv({"demo": man({"instance": "redis", "db": 0, "durable": True})},
                                    HOOK_NOW + "\nredis-cli DUMP \"$k\"\n"), [])

    def test_a_comment_that_names_dump_carries_nothing(self):
        self.assertEqual(len(g26.bad_kv({"demo": man({"instance": "redis", "db": 0, "durable": True})},
                                        HOOK_NOW + "\n# we never DUMP a key\n")), 1)

    def test_two_apps_on_one_database_is_one_too_many(self):
        got = g26.bad_kv({"a": man({"instance": "redis", "db": 0, "durable": False}),
                          "b": man({"instance": "redis", "db": 0, "durable": False})}, HOOK_NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("one app declares a database", got[0][1])

    def test_the_entry_before_dgo_1512_is_caught(self):
        # any-concurrency's data block as it stood until this fix (4384ea1c), inline so a shallow clone runs it
        before = {"data": {"shares": ["n8n_storage"], "on_uninstall": "keep",
                           "kv": [{"instance": "redis", "db": 0, "durable": True, "note": "REDIS_URL pins /0"}]}}
        got = g26.bad_kv({"any-concurrency": before}, HOOK_NOW)
        self.assertEqual([a for a, _ in got], ["any-concurrency"])

    def test_the_tree_passes_and_n8n_owns_db0(self):
        manifests = {}
        for root in ("apps", "platform-base"):
            for m in sorted((REPO / root).glob("*/app.json")):
                app = json.loads(m.read_text(encoding="utf-8"))
                manifests[app.get("id") or m.parent.name] = app
        self.assertGreater(len(manifests), 40, "the tree read is not empty")
        self.assertEqual(g26.bad_kv(manifests, HOOK_NOW), [])
        owners = [a for a, app in manifests.items()
                  for kv in (app.get("data") or {}).get("kv") or [] if (kv.get("instance"), kv.get("db")) == ("redis", 0)]
        self.assertEqual(owners, ["n8n"])


class Hook(unittest.TestCase):
    def test_the_hook_knows_authentiks_celery_queue(self):
        # measured on vps1 2026-11-10: a list named `authentik`, no TTL, in db1 with no authentik running
        self.assertIn('k == "authentik"', HOOK_NOW)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=1).result.wasSuccessful() else 1)
