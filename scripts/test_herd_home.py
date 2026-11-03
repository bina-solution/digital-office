"""test_herd_home.py — scripts/herd_home.py: which linked office's copy of an app this office may use.

    python3 scripts/test_herd_home.py

What is asked: on one of the herd's own offices the office the herd names is the only answer, even while
it does not publish the app (never the client's); an office that is not the herd's keeps the first one; a
registry that names an office by an alias still counts as that office; being "ours" is decided by the
`offices:` block only (a key of another block, or a prefix, is not an office); and no office guesses
between two when the herd names neither. Each case runs twice: with PyYAML and with the by-hand reader.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("herd_home", os.path.join(HERE, "herd_home.py"))
hh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hh)

HERD = """# a herd, the shape of apps/computers/herd.yaml
offices:
  macbook:
    label: MacBook
  hp-laptop:
    label: HP
  dell:
    label: Dell
    aliases: [portable-ubuntu, portable]     # the id the Dell declares
  vps1:
    label: vps1
  spare:

hub: vps1

shared:
  chat: [hp-laptop, vps1]

apps:
  project-pln: hp-laptop        # the one Plane
  ollama: dell
"""


def registry(*entries):
    d = tempfile.mkdtemp()
    for office, alias, app, port in entries:
        with open(os.path.join(d, "remote.%s.%s.json" % (office, alias)), "w", encoding="utf-8") as f:
            json.dump({"app": app, "alias": alias, "link_port": port}, f)
    with open(os.path.join(d, "remote.vps1.broken.json"), "w", encoding="utf-8") as f:
        f.write("[1, 2]")                                  # not an entry: skipped, never a crash
    return d


HERD_FILE = os.path.join(tempfile.mkdtemp(), "herd.yaml")
with open(HERD_FILE, "w", encoding="utf-8") as f:
    f.write(HERD)
FPG = ("fireplace", "plane", "project-pln", 9006)
HP = ("hp-laptop", "plane", "project-pln", 9005)


def home(app, me, *entries):
    return hh.home(app, me, registry(*entries), HERD_FILE)


class Cases:
    def test_a_herd_office_never_takes_the_clients_plane(self):
        ours, url, why = home("project-pln", "macbook", FPG)
        self.assertEqual((ours, url), (True, ""))
        self.assertIn("never another office's (fireplace)", why)

    def test_the_named_office_wins_over_the_first_one(self):
        self.assertEqual(home("project-pln", "macbook", FPG, HP)[1], "http://plane.hp-laptop:9005")
        self.assertEqual(home("project-pln", "fireplace", FPG, HP)[1], "http://plane.hp-laptop:9005")

    def test_a_client_office_keeps_its_only_plane(self):
        self.assertEqual(home("project-pln", "fireplace", FPG), (False, "http://plane.fireplace:9006", ""))
        self.assertEqual(home("project-pln", None, FPG), (False, "http://plane.fireplace:9006", ""))

    def test_an_alias_is_the_office(self):
        self.assertEqual(home("ollama", "macbook", ("portable-ubuntu", "ollama", "ollama", 9003))[1],
                         "http://ollama.portable-ubuntu:9003")
        self.assertTrue(home("ollama", "portable", ("portable-ubuntu", "ollama", "ollama", 9003))[0])

    def test_ours_is_read_from_the_offices_block_only(self):
        for me in ("chat", "vps", "mac.*", "hub", "shared", "label", "aliases"):
            self.assertFalse(home("project-pln", me, FPG)[0], me)
        for me in ("macbook", "hp-laptop", "dell", "portable-ubuntu", "vps1"):
            self.assertTrue(home("project-pln", me, HP)[0], me)

    def test_no_guess_between_two_the_herd_does_not_name(self):
        ours, url, why = home("drive", "fireplace", ("fireplace", "drive", "drive", 1), ("acme", "drive", "drive", 2))
        self.assertEqual(url, "")
        self.assertIn("2 linked offices publish drive", why)

    def test_nothing_published(self):
        self.assertEqual(home("drive", "fireplace"), (False, "", ""))
        ours, url, why = home("project-pln", "macbook")
        self.assertEqual((ours, url), (True, ""))
        self.assertNotIn("never another", why)

    def test_on_the_office_that_runs_it(self):
        ours, url, why = home("project-pln", "hp-laptop", FPG)
        self.assertEqual((ours, url), (True, ""))
        self.assertIn("on this office (hp-laptop), and it is not running here", why)

    def test_an_office_with_no_body_is_still_an_office(self):
        self.assertTrue(home("project-pln", "spare", HP)[0])


class BrokenYaml(unittest.TestCase):
    """PyYAML present but failing (or answering a non-mapping): the by-hand reader answers instead."""

    def run_with(self, safe_load):
        saved = sys.modules.get("yaml", "absent")
        fake = type(sys)("yaml")
        fake.safe_load = safe_load
        sys.modules["yaml"] = fake
        try:
            return home("project-pln", "macbook", FPG, HP)
        finally:
            if saved == "absent":
                sys.modules.pop("yaml", None)
            else:
                sys.modules["yaml"] = saved

    def test_a_reader_that_raises(self):
        def boom(text):
            raise ValueError("bad")
        self.assertEqual(self.run_with(boom), (True, "http://plane.hp-laptop:9005", ""))

    def test_a_reader_that_answers_a_list(self):
        self.assertEqual(self.run_with(lambda text: ["not", "a", "herd"]), (True, "http://plane.hp-laptop:9005", ""))


class WithYaml(Cases, unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("no PyYAML on this host — the by-hand reader is tested below")


class ByHand(Cases, unittest.TestCase):
    def setUp(self):
        self.saved = sys.modules.get("yaml", "absent")
        sys.modules["yaml"] = None                        # `import yaml` raises ImportError

    def tearDown(self):
        if self.saved == "absent":
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = self.saved


if __name__ == "__main__":
    unittest.main()
