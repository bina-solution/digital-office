"""domains: finding the provider apps (DGO-1473).

    python3 apps/domains/test_provider_client.py

The generic app finds a provider by NAME in the compiled registry: an app of this office, else the one
app a linked office gives. Held: ours first; two offices giving the same provider are not guessed
between (a client's office may run its own, with its own account) unless an office is named; an
override address wins; a provider that is nowhere is a state, not an exception.
"""
import json
import os
import sys
import tempfile
import unittest

REG = tempfile.mkdtemp(prefix="domains-registry-")
os.environ["DOMAINS_REGISTRY_DIR"] = REG
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_client as pc  # noqa: E402


def write(name, doc):
    with open(os.path.join(REG, name), "w", encoding="utf-8") as f:
        json.dump(doc, f)


def remote(office, app="domain-internic"):
    return {"app": app, "alias": app, "module": {"host": f"{app}.{office}"}, "port": 8981, "link_port": 9011,
            "remote": {"office": office}}


class Discovery(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(REG):
            os.remove(os.path.join(REG, f))
        for k in [k for k in os.environ if k.startswith("DOMAIN_PROVIDER_")]:
            del os.environ[k]

    def found(self):
        return pc.providers(force=True)

    def test_a_linked_offices_provider_is_reached_at_its_door(self):
        write("office.apps.json", {"apps": [{"app": "domains", "port": 8980, "service": "domains"}]})
        write("remote.hp-laptop.domain-internic.json", remote("hp-laptop"))
        got = self.found()["internic"]
        self.assertEqual(got["url"], "http://domain-internic.hp-laptop:9011")
        self.assertEqual(got["office"], "hp-laptop")

    def test_ours_comes_first(self):
        write("office.apps.json", {"apps": [{"app": "domain-internic", "port": 8981, "service": "domain-internic"}]})
        write("remote.hp-laptop.domain-internic.json", remote("hp-laptop"))
        self.assertEqual(self.found()["internic"]["url"], "http://domain-internic:8981")

    def test_two_offices_are_not_guessed_between(self):
        write("remote.hp-laptop.domain-internic.json", remote("hp-laptop"))
        write("remote.examplef.domain-internic.json", remote("examplef"))
        got = self.found()["internic"]
        self.assertIsNone(got["url"])
        self.assertIn("DOMAIN_PROVIDER_INTERNIC_OFFICE", got["ambiguous"])
        res = pc.read_domains("internic")
        self.assertEqual(res["state"], "provider_unavailable")
        os.environ["DOMAIN_PROVIDER_INTERNIC_OFFICE"] = "hp-laptop"
        self.assertEqual(self.found()["internic"]["url"], "http://domain-internic.hp-laptop:9011")

    def test_an_override_address_wins_and_other_apps_are_not_providers(self):
        write("remote.hp-laptop.domain-internic.json", remote("hp-laptop"))
        write("remote.hp-laptop.domains.json", remote("hp-laptop", app="domains"))
        os.environ["DOMAIN_PROVIDER_INTERNIC_URL"] = "http://127.0.0.1:1/"
        got = self.found()
        self.assertEqual(sorted(got), ["internic"])
        self.assertEqual(got["internic"]["url"], "http://127.0.0.1:1")

    def test_a_provider_that_is_nowhere_is_a_state(self):
        self.found()
        res = pc.read_zone("internic", "digital-office.co.il")
        self.assertEqual(res["state"], "provider_unavailable")
        self.assertFalse(pc.verified("internic", "create"))
        self.assertEqual(pc.write_state("internic")["state"], "provider_unavailable")


if __name__ == "__main__":
    unittest.main()
