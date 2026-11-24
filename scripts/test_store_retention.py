#!/usr/bin/env python3
"""store-retention (scripts/ci/store-retention.sh): the image store keeps the last lists' images, under its cap (DGO-2123).

    python3 scripts/test_store_retention.py

The engine and the prune stand in (the DOCKER and PRUNE_CMD seams): the store's container is there or not, each
`du` answers the next size of a list, and every prune and garbage collection is logged. A decision is read from what was
PRUNED, with how many lists kept, not only from what was printed. Standard library and bash only.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci" / "store-retention.sh"

DOCKER = r'''#!/bin/sh
# the engine, stood in: `ps` finds the store while STUB/up exists; each `du` answers the next line of STUB/sizes
echo "docker $*" >> "${STUB}/log"
case "$1" in
  ps) [ -f "${STUB}/up" ] && echo c0ffee ;;
  exec)
    case "$*" in
      *garbage-collect*) [ ! -f "${STUB}/gc.fail" ] ;;
      *"du -sk"*) n="$(grep -c '^docker exec .*du -sk' "${STUB}/log")"; s="$(sed -n "${n}p" "${STUB}/sizes" 2>/dev/null)"
                  [ -n "${s}" ] && printf '%s\t/var/lib/registry\n' "${s}" ;;
    esac ;;
esac
'''
PRUNE = '#!/bin/sh\necho "prune $*" >> "${STUB}/log"\n'


class Retention(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="store-retention-"))
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "docker").write_text(DOCKER)
        (self.tmp / "bin" / "prune").write_text(PRUNE)
        for f in ("docker", "prune"):
            os.chmod(self.tmp / "bin" / f, 0o755)
        self.stub = self.tmp / "stub"
        self.stub.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, sizes=(), up=True, cap="1000"):
        if up:
            (self.stub / "up").write_text("")
        (self.stub / "sizes").write_text("".join(f"{s}\n" for s in sizes))
        env = dict(os.environ, STUB=str(self.stub), DOCKER=str(self.tmp / "bin" / "docker"),
                   PRUNE_CMD=str(self.tmp / "bin" / "prune"), STORE_CAP_KIB=cap)
        p = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        log = (self.stub / "log").read_text().splitlines() if (self.stub / "log").exists() else []
        return p.stdout, [ln for ln in log if ln.startswith("prune ")], log

    def test_under_its_cap_it_keeps_three_lists_and_stops(self):
        out, prunes, log = self.run_it(sizes=["800"])
        self.assertEqual(prunes, ["prune --keep 3"])
        self.assertTrue(any("exec c0ffee timeout 600 registry garbage-collect /etc/docker/registry/config.yml" in ln
                            for ln in log), "bounded inside the container: %s" % log)
        self.assertFalse(any("--delete-untagged" in ln for ln in log), "never: it can delete an index's children")
        self.assertIn("the store holds 800 KiB, keeping what the last 3 list(s) name; its cap is 1000 KiB", out)

    def test_the_store_is_restarted_once_after_its_collections(self):
        # the second reader: the serving registry's in-memory blob cache outlives what a collection swept
        out, prunes, log = self.run_it(sizes=["1500", "900"])
        restarts = [i for i, ln in enumerate(log) if ln == "docker restart c0ffee"]
        collects = [i for i, ln in enumerate(log) if "garbage-collect" in ln]
        self.assertEqual(len(restarts), 1, log)
        self.assertTrue(restarts[0] > max(collects), "after the last collection: %s" % log)

    def test_over_its_cap_it_keeps_fewer_lists_until_it_is_under(self):
        out, prunes, _ = self.run_it(sizes=["1500", "900"])
        self.assertEqual(prunes, ["prune --keep 3", "prune --keep 2"])

    def test_never_below_the_newest_list(self):
        out, prunes, _ = self.run_it(sizes=["3000", "2500", "2000"])
        self.assertEqual(prunes, ["prune --keep 3", "prune --keep 2", "prune --keep 1"])
        self.assertIn("::warning::the store holds 2000 KiB with the newest list alone, over its cap of 1000 KiB", out)

    def test_no_store_here_prunes_nothing(self):
        out, prunes, _ = self.run_it(up=False)
        self.assertEqual(prunes, [])
        self.assertIn("no image-store container runs on this engine", out)

    def test_a_size_it_cannot_read_deletes_nothing_more(self):
        out, prunes, _ = self.run_it(sizes=[])
        self.assertEqual(prunes, ["prune --keep 3"], "the first prune keeps three lists; with no size, no fewer")
        self.assertIn("the store's size could not be read — nothing more is deleted", out)

    def test_a_failed_collection_is_said_and_ends_zero(self):
        (self.stub / "gc.fail").write_text("")
        out, prunes, _ = self.run_it(sizes=["500"])
        self.assertIn("the garbage collection failed", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
