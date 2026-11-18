#!/usr/bin/env python3
"""test_ceilings — render says when a memory limit is set above what the app declares or the machine has (DGO-1797).

    python3 platform/manager/test_ceilings.py      # needs PyYAML (reconcile.py imports it)

The Dell's .env gave Ollama 9G of its 15.4 GB while the app declares 6g, and nothing said a word. ceiling_warnings()
says it, for every app alike; the Go twin is held to the same lines by the render oracle
(packaging/dgo/internal/compiler/render_test.go).
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_ceilings", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_ceilings"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
G = 2 ** 30


class Sizes(unittest.TestCase):
    def test_docker_s_own_reading(self):
        for text, want in (("6G", 6 * G), ("6g", 6 * G), ("512M", 512 * 2 ** 20), ("64m", 64 * 2 ** 20), ("1024", 1024),
                           ("1.5g", 3 * G // 2), ("1gb", G), ("1GiB", G), ("6 G", 6 * G), ("2k", 2048)):
            self.assertEqual(rc._mem_bytes(text), want, text)
        self.assertEqual(rc._mem_bytes(1073741824), G)
        for bad in ("", "abc", "-1", "1.2.3", "6X", " 6G", "6G\n", "٦G", "${OLLAMA_MEMORY:-6G}", True, None, 1.5, -5,
                    "9" * 40, 2 ** 62):
            self.assertIsNone(rc._mem_bytes(bad), repr(bad))


class Warnings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.saved = rc.REPO, rc.ENVFILE, rc.MEMINFO
        rc.REPO = self.dir                     # a temp repo first: the guard then lets ENVFILE follow it here
        rc.MEMINFO = self.dir / "meminfo"
        self.mem(16 * G)

    def tearDown(self):
        rc.REPO, rc.ENVFILE, rc.MEMINFO = self.saved
        self.tmp.cleanup()

    def mem(self, n):
        (self.dir / "meminfo").write_text(f"MemTotal:       {n // 1024} kB\nMemFree:        1 kB\n", encoding="utf-8")

    def app(self, aid, compose, memory="6g"):
        d = self.dir / aid
        d.mkdir(exist_ok=True)
        (d / "docker-compose.yml").write_text(compose, encoding="utf-8")
        a = {"_dir": d, "compose": "docker-compose.yml"}
        if memory is not None:
            a["resources"] = {"memory": memory}
        return a

    def engine(self, limit="${OLLAMA_MEMORY:-6G}"):
        return ("services:\n  front:\n    image: caddy\n    deploy: {resources: {limits: {memory: 64M}}}\n"
                f"  engine:\n    image: x\n    deploy:\n      resources:\n        limits:\n          memory: {limit}\n")

    def test_the_dell_s_override_is_said_twice(self):
        (self.dir / ".env").write_text("OLLAMA_MEMORY=9G\n", encoding="utf-8")
        self.mem(int(15.4 * G))
        out = rc.ceiling_warnings({"ollama": self.app("ollama", self.engine())}, ["ollama"])
        self.assertEqual(out, [
            "warning: ollama/engine: .env sets OLLAMA_MEMORY=9G, above the 6g the app declares (app.json "
            "resources.memory) — the budget gates count 6g",
            "warning: ollama/engine: a memory limit of 9G (OLLAMA_MEMORY in .env) is 58% of this machine's 15.3 GiB — "
            "more than 50% for one service"])

    def test_nothing_to_say_on_the_defaults_and_within_the_declaration(self):
        cat = {"ollama": self.app("ollama", self.engine())}
        self.assertEqual(rc.ceiling_warnings(cat, ["ollama"]), [])            # no .env: the default, 6G of 16
        (self.dir / ".env").write_text("OLLAMA_MEMORY=4G\n", encoding="utf-8")
        self.assertEqual(rc.ceiling_warnings(cat, ["ollama"]), [])            # lowered: nothing
        (self.dir / ".env").write_text("OLLAMA_MEMORY=\n", encoding="utf-8")
        self.assertEqual(rc.ceiling_warnings(cat, ["ollama"]), [])            # empty with `:-`: the default

    def test_a_figure_written_in_the_compose_is_g30s_not_this(self):
        self.mem(8 * G)
        cat = {"db": self.app("db", self.engine("5G"), memory="5g")}
        self.assertEqual(rc.ceiling_warnings(cat, ["db"]), [])               # 62% of 8 GiB, but the app's own

    def test_every_form_of_a_reference(self):
        self.mem(8 * G)
        compose = ("services:\n"
                   "  bare:\n    deploy: {resources: {limits: {memory: \"${BARE}\"}}}\n"
                   "  dash:\n    deploy: {resources: {limits: {memory: \"${DASH-1G}\"}}}\n"
                   "  frac:\n    deploy: {resources: {limits: {memory: \"${FRAC:-1G}\"}}}\n"
                   "  5:\n    deploy: {resources: {limits: {memory: \"${BARE}\"}}}\n")
        (self.dir / ".env").write_text("BARE=6g\nDASH=\nFRAC=4.5G\n", encoding="utf-8")
        out = rc.ceiling_warnings({"x": self.app("x", compose, memory="1g")}, ["x"])
        self.assertEqual([line.split(":")[1].strip() for line in out], ["x/bare", "x/bare", "x/frac", "x/frac"])
        self.assertIn("a memory limit of 4.5G (FRAC in .env) is 56%", out[3])   # `-` with "" set: no size; 5: not read

    def test_no_machine_figure_no_share_warning(self):
        rc.MEMINFO = self.dir / "absent"
        (self.dir / ".env").write_text("OLLAMA_MEMORY=9G\n", encoding="utf-8")
        out = rc.ceiling_warnings({"ollama": self.app("ollama", self.engine())}, ["ollama"])
        self.assertEqual(len(out), 1)
        self.assertIn("above the 6g the app declares", out[0])

    def test_what_is_not_read(self):
        (self.dir / ".env").write_text("OLLAMA_MEMORY=7G\nX=lots\n", encoding="utf-8")   # 44% of 16 GiB
        cat = {"none": self.app("none", self.engine(), memory=None),          # no declaration: only the share
               "word": self.app("word", self.engine("${X:-1G}")),            # a value that is no size
               "bad": self.app("bad", "services: [\n"),                       # a compose PyYAML refuses
               "list": self.app("list", "- a\n"),
               "nocompose": {"_dir": self.dir, "resources": {"memory": "1g"}}}
        self.assertEqual(rc.ceiling_warnings(cat, ["none", "word", "bad", "list", "nocompose"]), [])
        self.mem(8 * G)
        self.assertEqual(len(rc.ceiling_warnings(cat, ["none"])), 1)          # 7G of 8: the share alone


class Forever(unittest.TestCase):
    """forever_warnings (DGO-1848): an .env value an app DECLARES holds its resources for ever (resources.forever)."""
    KEEP = {"env": "OLLAMA_KEEP_ALIVE", "starts_with": "-", "why": "held for ever", "unless": "OLLAMA_DEDICATED"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.saved = rc.REPO, rc.ENVFILE
        rc.REPO = self.dir

    def tearDown(self):
        rc.REPO, rc.ENVFILE = self.saved
        self.tmp.cleanup()

    def say(self, env, *forever):
        (self.dir / ".env").write_text(env, encoding="utf-8")
        return rc.forever_warnings({"ollama": {"resources": {"memory": "6g", "forever": list(forever)}}}, ["ollama"])

    def test_the_dell_s_keep_alive_is_said(self):
        self.assertEqual(self.say("OLLAMA_KEEP_ALIVE=-1\n", self.KEEP), [
            "warning: ollama: .env sets OLLAMA_KEEP_ALIVE=-1 — held for ever (a machine that is there for it says so: "
            "OLLAMA_DEDICATED=1)"])
        self.assertEqual(len(self.say('OLLAMA_KEEP_ALIVE="-5m"\n', self.KEEP)), 1)

    def test_nothing_on_the_default_an_empty_value_or_no_env(self):
        self.assertEqual(self.say("OLLAMA_KEEP_ALIVE=10m\n", self.KEEP), [])
        self.assertEqual(self.say("OLLAMA_KEEP_ALIVE=\n", self.KEEP), [])
        self.assertEqual(self.say("", self.KEEP), [])

    def test_a_machine_that_is_there_for_it_says_so(self):
        self.assertEqual(self.say("OLLAMA_KEEP_ALIVE=-1\nOLLAMA_DEDICATED= 1 \n", self.KEEP), [])
        self.assertEqual(len(self.say("OLLAMA_KEEP_ALIVE=-1\nOLLAMA_DEDICATED=yes\n", self.KEEP)), 1)

    def test_a_declaration_of_another_shape_says_nothing(self):
        self.assertEqual(self.say("OLLAMA_KEEP_ALIVE=-1\n", "a word", {"env": 5, "starts_with": "-", "why": "x"},
                                  {"env": "OLLAMA_KEEP_ALIVE", "starts_with": "", "why": "x"},
                                  {"env": "OLLAMA_KEEP_ALIVE", "matches": "-", "why": "the old key"}), [])

    def test_the_app_declares_it(self):
        import json
        app = json.loads((HERE.parents[1] / "apps" / "ollama" / "app.json").read_text(encoding="utf-8"))
        held = [f for f in app["resources"].get("forever") or [] if f.get("env") == "OLLAMA_KEEP_ALIVE"]
        self.assertTrue(held and held[0].get("unless") == "OLLAMA_DEDICATED", "apps/ollama declares its keep-alive")


if __name__ == "__main__":
    unittest.main()
