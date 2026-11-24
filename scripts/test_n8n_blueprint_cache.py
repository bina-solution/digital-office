#!/usr/bin/env python3
"""The blueprint reader's shared cache (scripts/refactor/n8n_blueprint.py, N8N_BP_CACHE — DGO-2123).

    python3 scripts/test_n8n_blueprint_cache.py

Each of the ~17 gates that read blueprints is a process of its own, and each compiled every blueprint directory again
(about 18 s a gate on the Dell). scripts/ci/gates.sh now names one directory for its run, and a directory compiled by
one gate is read back by the next. A wrong answer there would be every blueprint gate reading the wrong workflows, so
this holds what the cache may and may not answer. No node is needed: the compiler is a stand-in that writes what
wrap.mjs would, or that fails the test if it is called at all.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("n8n_blueprint", REPO / "scripts" / "refactor" / "n8n_blueprint.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


class Compiled:
    """subprocess.run as wrap.mjs answers it: `node wrap.mjs compile <src> <out>` writes <stem>.json per workflow."""

    def __init__(self):
        self.calls = 0

    def __call__(self, cmd, **_kw):
        self.calls += 1
        src, out = pathlib.Path(cmd[3]), pathlib.Path(cmd[4])
        for f in src.glob("*.workflow.ts"):
            stem = f.name[:-len(".workflow.ts")]
            (out / f"{stem}.json").write_text(json.dumps({"id": stem, "body": f.read_text(encoding="utf-8")}),
                                              encoding="utf-8")
        return mock.Mock(returncode=0, stdout="", stderr="")


def never(*_a, **_kw):
    raise AssertionError("compiled, where the shared cache had the answer")


class SharedCache(unittest.TestCase):
    def setUp(self):
        self.box = pathlib.Path(tempfile.mkdtemp(prefix="n8nbp-test-"))
        self.cache = self.box / "cache"
        self.cache.mkdir()
        self.src = (self.box / "blueprint").resolve()
        self.src.mkdir()
        (self.src / "a01.workflow.ts").write_text("// one\n", encoding="utf-8")
        self.wrap = self.box / "wrap.mjs"
        self.wrap.write_text("// the transformer\n", encoding="utf-8")
        patches = [mock.patch.dict(os.environ, {"N8N_BP_CACHE": str(self.cache)}),
                   mock.patch.object(bp, "WRAP", self.wrap), mock.patch.object(bp, "_node", lambda: "node")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        bp._CACHE.clear()
        self.addCleanup(bp._CACHE.clear)
        self.addCleanup(shutil.rmtree, self.box, True)

    def compile_once(self):
        compiled = Compiled()
        with mock.patch.object(bp.subprocess, "run", compiled):
            got = bp._compile_dir(self.src)
        return got, compiled.calls

    def test_a_later_process_reads_the_compile_back(self):
        got, calls = self.compile_once()
        self.assertEqual((calls, got["a01"]["body"]), (1, "// one\n"))
        bp._CACHE.clear()                                   # another gate: another process, an empty memory
        with mock.patch.object(bp.subprocess, "run", never):
            self.assertEqual(bp._compile_dir(self.src), got)

    def test_a_changed_file_is_compiled_again_never_the_old_answer(self):
        self.compile_once()
        (self.src / "a01.workflow.ts").write_text("// two\n", encoding="utf-8")
        bp._CACHE.clear()
        got, calls = self.compile_once()
        self.assertEqual((calls, got["a01"]["body"]), (1, "// two\n"))

    def test_a_new_file_and_a_new_transformer_are_new_keys(self):
        k1 = bp._shared_key(self.src)
        (self.src / "b02.workflow.ts").write_text("// b\n", encoding="utf-8")
        k2 = bp._shared_key(self.src)
        self.wrap.write_text("// another transformer\n", encoding="utf-8")
        k3 = bp._shared_key(self.src)
        (self.src / "sub").mkdir()
        (self.src / "sub" / "helper.ts").write_text("export const x = 1\n", encoding="utf-8")   # what a workflow imports
        self.assertEqual(len({k1, k2, k3, bp._shared_key(self.src)}), 4)

    def test_an_entry_that_cannot_be_read_is_a_miss(self):
        self.compile_once()
        entry = self.cache / bp._shared_key(self.src)
        (entry / "a01.json").write_text("{not json", encoding="utf-8")
        bp._CACHE.clear()
        self.assertEqual(bp._shared_get(self.src), (None, None))
        got, calls = self.compile_once()
        self.assertEqual((calls, got["a01"]["body"]), (1, "// one\n"))

    def test_without_the_variable_nothing_is_kept(self):
        with mock.patch.dict(os.environ, {"N8N_BP_CACHE": ""}):
            self.assertEqual(bp._shared_get(self.src), (None, None))
            self.compile_once()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_an_entry_already_there_stays_and_nothing_is_left_beside_it(self):
        self.compile_once()
        key = bp._shared_key(self.src)
        out = self.box / "out"
        out.mkdir()
        (out / "a01.json").write_text('{"id": "late"}', encoding="utf-8")
        bp._shared_put(key, str(out))                      # a second writer of the same key
        self.assertEqual(json.loads((self.cache / key / "a01.json").read_text(encoding="utf-8"))["body"], "// one\n")
        self.assertEqual([p.name for p in self.cache.iterdir()], [key])

    def test_the_transformers_own_files_are_in_the_key(self):
        # literal-check.mjs (beside wrap.mjs) decides what a compile refuses; the lockfile pins the toolchain
        k0 = bp._shared_key(self.src)
        (self.box / "literal-check.mjs").write_text("// v1\n", encoding="utf-8")
        k1 = bp._shared_key(self.src)
        (self.box / "literal-check.mjs").write_text("// v2\n", encoding="utf-8")
        k2 = bp._shared_key(self.src)
        (self.box / "package-lock.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(len({k0, k1, k2, bp._shared_key(self.src)}), 4)

    def test_g100_still_reads_the_extraction_prefix(self):
        # G100 (blueprint-tmp-test) plants dirs of the module's first `mkdtemp(prefix=…)`: the shared cache's own
        # temp dir must not become it (33fb4e34f's did, and G100 went red — the second reader)
        spec_ = importlib.util.spec_from_file_location("g100", REPO / "scripts" / "refactor" / "blueprint-tmp-test.py")
        g100 = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(g100)
        self.assertEqual(g100.module_prefix(REPO / "scripts" / "refactor" / "n8n_blueprint.py"), "n8n-bp-")

    def test_gates_sh_makes_one_for_its_run_and_removes_it(self):
        gates = (REPO / "scripts" / "ci" / "gates.sh").read_text(encoding="utf-8")
        self.assertIn("N8N_BP_CACHE", gates)
        self.assertIn("rm -rf", gates[gates.index("N8N_BP_CACHE"):])
        # …named so that a run killed before its trap leaves it to prune_stale's 12-hour sweep of `n8n-bp-*`
        self.assertIn('mktemp -d "${TMPDIR:-/tmp}/n8n-bp-cache.XXXXXX"', gates)


if __name__ == "__main__":
    unittest.main(verbosity=1)
