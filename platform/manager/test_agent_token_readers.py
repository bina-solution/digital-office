#!/usr/bin/env python3
"""test_agent_token_readers — who may read an agent's action token, compiled from the manifests (DGO-1152).

    python3 platform/manager/test_agent_token_readers.py      # needs PyYAML (reconcile.py imports it)

The vault hands an agent's token to dgo-extend and, from this registry, to the services of the apps that the
agent's app NAMES for a capability (`token_readers`), that `use` it, where that app is its one provider. The Go twin writes the same file, held by
the render oracle (packaging/dgo/internal/compiler/render_test.go).
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_agent_readers", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_agent_readers"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


class Readers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def app(self, aid, compose=None, caps=(), use=(), readers=None):
        """`readers`: the apps this provider names (token_readers) on each of its capabilities."""
        d = self.dir / aid
        d.mkdir()
        a = {"id": aid, "_dir": d, "use": list(use),
             "capabilities": [{"name": c, **({"token_readers": readers} if readers is not None else {})} for c in caps]}
        if compose is not None:
            (d / "docker-compose.yml").write_text(compose, encoding="utf-8")
            a["compose"] = "docker-compose.yml"
        return a

    def test_the_browser_s_runner_and_who_uses_the_browser(self):
        cat = {
            "browser42": self.app("browser42", "services:\n  browser42-mcp: {image: x}\n"
                                               "  browser42-task-runner:\n    environment:\n"
                                               "      AGENT_TOKEN_FILE: /data/t\n      X: 1\n", caps=["browser"],
                                  readers=["newsflow", "absent"]),
            "newsflow": self.app("newsflow", "services:\n  newsflow: {image: x}\n",
                                 use=[{"capability": "browser", "strength": "requires"}]),
            # uses the browser, but the provider does not name it: a consumer never grants itself
            "lister": self.app("lister", "services:\n  lister: {image: x}\n  lister-worker: {image: x}\n", use=["browser"]),
            "other": self.app("other", "services:\n  other: {image: x}\n", use=[{"capability": "sql"}]),
        }
        self.assertEqual(rc.agent_token_readers(cat, list(cat)), {"browser42-task-runner": ["newsflow"]})

    def test_a_named_app_that_does_not_use_the_capability_reads_nothing(self):
        cat = {"p": self.app("p", "services:\n  p-door: {environment: {AGENT_TOKEN_FILE: /t}}\n", caps=["door"],
                             readers=["x"]),
               "x": self.app("x", "services:\n  x: {}\n", use=[{"capability": "sql"}])}
        self.assertEqual(rc.agent_token_readers(cat, list(cat)), {})
        cat["p"]["capabilities"][0]["token_readers"] = "x"                       # not a list: names nobody
        cat["x"]["use"] = [{"capability": "door"}]
        self.assertEqual(rc.agent_token_readers(cat, list(cat)), {})

    def test_environment_as_a_list_and_no_reader_no_entry(self):
        cat = {"agent": self.app("agent", "services:\n  agent-door:\n    environment:\n      - AGENT_TOKEN_FILE=/t\n",
                                 caps=["door"], readers=["user"])}
        self.assertEqual(rc.agent_token_readers(cat, ["agent"]), {})              # nobody uses `door`
        cat["user"] = self.app("user", "services:\n  user: {}\n", use=[{"capability": "door"}])
        self.assertEqual(rc.agent_token_readers(cat, ["agent", "user"]), {"agent-door": ["user"]})

    def test_an_ambiguous_capability_or_an_app_using_itself_hands_out_nothing(self):
        door = "services:\n  {0}:\n    environment: {{AGENT_TOKEN_FILE: /t}}\n"
        cat = {"a": self.app("a", door.format("a-door"), caps=["door"], readers=["b", "c"]),
               "b": self.app("b", door.format("b-door"), caps=["door"], use=[{"capability": "door"}], readers=["b", "c"]),
               "c": self.app("c", "services:\n  c: {}\n", use=[{"capability": "door"}])}
        self.assertEqual(rc.agent_token_readers(cat, list(cat)), {})             # two providers: ambiguous
        self.assertEqual(rc.agent_token_readers(cat, ["b"]), {})                 # b uses its own door
        self.assertEqual(rc.agent_token_readers(cat, ["b", "c"]), {"b-door": ["c"]})

    def test_what_is_not_read(self):
        cat = {"p": self.app("p", "services: [\n", caps=["door"], readers=["u"]),  # PyYAML refuses it
               "q": self.app("q", None, caps=["door2"], readers=["u"]),           # no compose
               "u": self.app("u", "services:\n  u: {}\n", use=[{"capability": "door"}, {"capability": "door2"}])}
        self.assertEqual(rc.agent_token_readers(cat, list(cat)), {})


if __name__ == "__main__":
    unittest.main()
