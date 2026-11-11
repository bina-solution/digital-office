"""INDOX's front door opens the office's own tenant, never the standing `test` one when a production one is enabled.

    python3 apps/indox/tests/test_front_door_default.py

With no instance in the link the web UI opened «the first enabled entry» of GET /instances, which is ordered by id;
every office carries the standing `test` tenant, so an office whose own id sorts after «test» (Exampleu's) opened on
the test tenant (issues/indox-front-door-opens-the-test-tenant-…, DGO-1815). What holds, read from the sources:
  a. api.ts has ONE rule, `defaultInstanceId`: the first enabled instance whose purpose is not 'test', else the first
     enabled — the office's own default (apps/indox/hooks/_schema-lib.sh);
  b. every place that picks a default goes through it (no `accounts.find((a) => a.enabled !== false)?.id` left);
  c. the instance list carries `purpose` from /instances into the accounts, and /instances selects it.
The types are checked by the image's own `tsc -b`.

FRONT_DOOR_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("FRONT_DOOR_ROOT") or pathlib.Path(__file__).resolve().parents[3])
SRC = ROOT / "apps/indox/app/webapp/src"


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


class FrontDoorDefault(unittest.TestCase):
    def test_one_rule_that_skips_the_test_tenant(self):
        api = read("api.ts")
        body = api[api.index("export function defaultInstanceId"):]
        body = body[:body.index("\n}\n")]
        # exactly the two lookups, the non-test one FIRST, joined by ?? — nothing before it can win
        self.assertRegex(body, r"return \(\s*accounts\.find\(\(a\) => a\.enabled !== false && a\.purpose !== 'test'\) \?\?"
                               r"\s*accounts\.find\(\(a\) => a\.enabled !== false\)\s*\)\?\.id;\s*$")
        self.assertIn("purpose?: string;", api)

    def test_every_default_goes_through_it(self):
        files = [p for p in SRC.rglob("*.ts*") if p.is_file()]
        self.assertGreater(len(files), 20)
        # any spelling of «the first enabled one's id» outside the helper: .find((x) => x.enabled …)?.id
        bare = re.compile(r"\.find\(\((\w+)\) => \1\.enabled(\s*!==\s*false)?\s*\)\s*\?\.id")
        left = [str(p.relative_to(SRC)) for p in files if bare.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(left, [], "a default picked without the office's rule")
        for rel in ("App.tsx", "pages/NotFoundPage.tsx", "components/InstanceSwitcher.tsx"):
            self.assertIn("defaultInstanceId(accounts)", read(rel), rel)
        self.assertIn("defaultInstanceId(instances)", read("pages/DocumentBrowserPage.tsx"))

    def test_purpose_travels_from_instances_to_the_accounts(self):
        self.assertIn("purpose: x.purpose,", read("App.tsx"))
        py = (ROOT / "apps/indox/app/incoming_documents/api/__init__.py").read_text(encoding="utf-8")
        self.assertIn("coalesce(purpose, '') as purpose", py)


if __name__ == "__main__":
    unittest.main(verbosity=2)
