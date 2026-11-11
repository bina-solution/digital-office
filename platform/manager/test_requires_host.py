#!/usr/bin/env python3
"""test_requires_host — an app that drives the host's hardware is not enabled where that hardware is missing (DGO-1797).

    python3 platform/manager/test_requires_host.py      # needs PyYAML (reconcile.py imports it)

The Android emulator maps /dev/kvm (package 11 of the Dell's design). app.json says so (`requires_host.devices`),
and set_disposition() — the ONE writer of the desired state, behind set-state, app-management and the installer —
refuses to enable it on a machine without it, with the reason, before the state file is touched. The Go twin is
held to the same answers by TestSetStateMatchesPython (packaging/dgo/internal/compiler/writers_test.go).
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_requires_host", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_requires_host"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
MISSING = "/dev/dgo-no-such-device"
STATE_TEXT = "schema_version: 1\n\napps:\n  # a comment that stays\n  zz-kvm: { state: disabled, by: user }\n"


class RequiresHost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.saved = rc.REPO, rc.ENVFILE, rc.STATE, rc.GEN, rc.in_container
        rc.REPO = self.repo                            # a temp repo first: the guard lets ENVFILE follow it
        state = self.repo / "platform.state.yaml"     # the temp repo's own, written as test_office.py writes it
        state.write_text(STATE_TEXT, encoding="utf-8")
        rc.STATE = state
        rc.GEN = self.repo / ".generated"
        rc.GEN.mkdir()
        rc.in_container = lambda: False                # on the host, unless a case says otherwise

    def tearDown(self):
        rc.REPO, rc.ENVFILE, rc.STATE, rc.GEN, rc.in_container = self.saved
        self.tmp.cleanup()

    def facts(self, doc):
        (rc.GEN / rc.HOST_DEVICES).write_text(json.dumps(doc), encoding="utf-8")

    def test_inside_a_container_the_hosts_record_answers(self):
        self.app("zz-kvm", {"devices": [MISSING]})
        rc.in_container = lambda: True
        self.assertEqual(rc.missing_host_devices("zz-kvm"), [])                 # no record: it cannot know, no refusal
        self.facts({MISSING: True})
        self.assertEqual(rc.missing_host_devices("zz-kvm"), [])                 # the host has it
        self.assertTrue(rc.set_disposition("zz-kvm", "enabled"))
        self.facts({MISSING: False})
        self.assertEqual(rc.missing_host_devices("zz-kvm"), [MISSING])          # the host said it is not there

    def test_on_the_host_its_own_dev_is_the_truth(self):
        self.app("zz-kvm", {"devices": [MISSING, "/dev/null"]})
        self.facts({MISSING: True})                                              # a stale record
        self.assertEqual(rc.missing_host_devices("zz-kvm"), [MISSING])

    def test_the_record_is_written_on_the_host_only(self):
        cat = {"zz-kvm": {"requires_host": {"devices": [MISSING, "/dev/null", 5, ""]}}, "x": {}, "y": {"requires_host": []}}
        rc.render_host_devices(cat)
        self.assertEqual(json.loads((rc.GEN / rc.HOST_DEVICES).read_text(encoding="utf-8")),
                         {"/dev/null": True, MISSING: False})
        (rc.GEN / rc.HOST_DEVICES).unlink()
        rc.in_container = lambda: True
        rc.render_host_devices(cat)
        self.assertFalse((rc.GEN / rc.HOST_DEVICES).exists())

    def app(self, aid, requires, root="apps"):
        d = self.repo / root / aid
        d.mkdir(parents=True, exist_ok=True)
        (d / "app.json").write_text(json.dumps({"id": aid, "layer": 3, "requires_host": requires}), encoding="utf-8")

    def test_a_missing_device_refuses_the_enable_and_writes_nothing(self):
        self.app("zz-kvm", {"devices": ["/dev/null", MISSING]})
        with self.assertRaises(ValueError) as e:
            rc.set_disposition("zz-kvm", "enabled")
        self.assertEqual(str(e.exception), f"zz-kvm needs {MISSING} (app.json requires_host.devices), which this "
                                           "machine does not have — not enabled, nothing written")
        self.assertEqual(rc.STATE.read_text(encoding="utf-8"), STATE_TEXT)

    def test_disabling_or_archiving_asks_nothing_of_the_host(self):
        self.app("zz-kvm", {"devices": [MISSING]})
        self.assertFalse(rc.set_disposition("zz-kvm", "disabled"))       # already so
        self.assertTrue(rc.set_disposition("zz-kvm", "archived"))

    def test_devices_that_are_all_here_enable(self):
        self.app("zz-kvm", {"devices": ["/dev/null"]}, root="platform-base")
        self.assertTrue(rc.set_disposition("zz-kvm", "enabled"))
        self.assertIn("zz-kvm: { state: enabled, by: user }", rc.STATE.read_text(encoding="utf-8"))

    def test_what_declares_nothing(self):
        for requires in ("/dev/kvm", {"devices": MISSING}, {"devices": [5, "", None]}, {}, None):
            self.app("zz-kvm", requires)
            self.assertEqual(rc.missing_host_devices("zz-kvm"), [], repr(requires))
        (self.repo / "apps" / "zz-kvm" / "app.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(rc.missing_host_devices("zz-kvm"), [])
        self.assertEqual(rc.missing_host_devices("../zz-kvm"), [])          # never a path outside the app folders
        self.assertEqual(rc.missing_host_devices("nosuch"), [])


if __name__ == "__main__":
    unittest.main()
