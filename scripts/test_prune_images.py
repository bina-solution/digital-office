#!/usr/bin/env python3
"""prune-images (scripts/ci/prune-images.py): the store keeps what the line's last lists name (DGO-2123).

    python3 scripts/test_prune_images.py

A registry stands in on the loopback (a thread: the catalog, tags, a manifest's digest, a delete), and a throwaway git
repository holds refs/remotes/origin/images/dgo-stable: four lists, newest first L4 … L1. Read from what the store was
asked to DELETE, never only from what was printed. Standard library only.
"""
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci" / "prune-images.py"
D = {n: "sha256:" + n * 64 for n in "abcdefgh"}


class Registry(http.server.BaseHTTPRequestHandler):
    store: dict = {}     # repo → {tag: digest}
    deleted: list = []
    broken: set = set()  # "repo:tag" whose manifest answers 500

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/v2/_catalog":
            return self._send(200, json.dumps({"repositories": sorted(self.store)}).encode())
        if p.endswith("/tags/list"):
            repo = p[len("/v2/"):-len("/tags/list")]
            return self._send(200, json.dumps({"name": repo, "tags": sorted(self.store.get(repo, {})) or None}).encode())
        return self._send(404)

    def do_HEAD(self):
        repo, _, tag = self.path[len("/v2/"):].partition("/manifests/")
        if f"{repo}:{tag}" in self.broken:
            return self._send(500)
        d = self.store.get(repo, {}).get(tag)
        return self._send(200, headers={"Docker-Content-Digest": d}) if d else self._send(404)

    def do_DELETE(self):
        repo, _, digest = self.path[len("/v2/"):].partition("/manifests/")
        tags = self.store.get(repo, {})
        gone = [t for t, d in tags.items() if d == digest]
        if not gone:
            return self._send(404)
        for t in gone:
            del tags[t]
        self.deleted.append(f"{repo}@{digest}")
        return self._send(202)


def git(cwd, *args, stdin=None):
    return subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True, text=True, check=True).stdout.strip()


class Prune(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="prune-images-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        Registry.store, Registry.deleted, Registry.broken = {}, [], set()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lists(self, *named):
        """refs/remotes/origin/images/dgo-stable: one commit per list, oldest first; each list {id: digest}"""
        parent = None
        for i, images in enumerate(named):
            doc = {"green": "%040d" % i, "built": [], "images": {k: {"digest": v, "name": "p/" + k}
                                                                for k, v in images.items()}}
            blob = git(self.repo, "hash-object", "-w", "--stdin", stdin=json.dumps(doc))
            tree = git(self.repo, "mktree", stdin=f"100644 blob {blob}\timages.json\n")
            parent = git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree,
                         *(["-p", parent] if parent else []), "-m", f"list {i + 1}")
        git(self.repo, "update-ref", "refs/remotes/origin/images/dgo-stable", parent)

    def run_it(self, *args, url=None):
        env = dict(os.environ, STORE_URL=url or self.url)
        p = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_the_last_three_lists_are_kept_and_the_rest_deleted(self):
        # x went a → b → c → d over four lists; y stayed e; f was pushed and never named (its digest was not read)
        self.lists({"x": D["a"], "y": D["e"]}, {"x": D["b"], "y": D["e"]}, {"x": D["c"], "y": D["e"]},
                   {"x": D["d"], "y": D["e"]})
        Registry.store = {"x": {"t1": D["a"], "t2": D["b"], "t3": D["c"], "t4": D["d"], "t5": D["f"]},
                          "y": {"t1": D["e"]}}
        out = self.run_it("--keep", "3")
        self.assertEqual(sorted(Registry.deleted), sorted([f"x@{D['a']}", f"x@{D['f']}"]), out)
        self.assertEqual(sorted(Registry.store["x"]), ["t2", "t3", "t4"])
        self.assertEqual(Registry.store["y"], {"t1": D["e"]}, "an image every list names stays")
        self.assertIn("kept 4 digest(s) the last 3 list(s) name; deleted 2 of 2 others", out)

    def test_a_dry_run_deletes_nothing(self):
        self.lists({"x": D["b"]})
        Registry.store = {"x": {"t1": D["a"], "t2": D["b"]}}
        out = self.run_it("--dry-run")
        self.assertEqual(Registry.deleted, [])
        self.assertIn(f"would delete x@{D['a'][:19]}", out)

    def test_no_list_deletes_nothing(self):
        Registry.store = {"x": {"t1": D["a"]}}
        out = self.run_it()
        self.assertEqual(Registry.deleted, [])
        self.assertIn("no list of images could be read", out)

    def test_a_newest_list_it_cannot_read_deletes_nothing(self):
        # the older lists alone would delete what the newest names: the images the green that just moved points at
        self.lists({"x": D["a"]}, {"x": D["b"]})
        tip = git(self.repo, "rev-parse", "refs/remotes/origin/images/dgo-stable")
        blob = git(self.repo, "hash-object", "-w", "--stdin", stdin="not json")
        tree = git(self.repo, "mktree", stdin=f"100644 blob {blob}\timages.json\n")
        bad = git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree, "-p", tip, "-m", "bad")
        git(self.repo, "update-ref", "refs/remotes/origin/images/dgo-stable", bad)
        Registry.store = {"x": {"t1": D["a"], "t2": D["b"], "t3": D["c"]}}
        out = self.run_it()
        self.assertEqual(Registry.deleted, [], out)
        self.assertIn("no list of images could be read", out)

    def test_a_list_that_names_nothing_here_deletes_nothing(self):
        # another line's store, or a misread list: never «all of it is old»
        self.lists({"x": D["g"]})
        Registry.store = {"x": {"t1": D["a"], "t2": D["b"]}}
        out = self.run_it()
        self.assertEqual(Registry.deleted, [])
        self.assertIn("nothing is deleted", out)

    def test_a_tag_whose_digest_cannot_be_read_is_kept(self):
        self.lists({"x": D["b"]})
        Registry.store = {"x": {"t1": D["a"], "t2": D["b"], "t3": D["c"]}}
        Registry.broken = {"x:t1"}
        self.run_it()
        self.assertEqual(Registry.deleted, [f"x@{D['c']}"])
        self.assertIn("t1", Registry.store["x"])

    def test_a_store_that_does_not_answer_deletes_nothing_and_ends_zero(self):
        self.lists({"x": D["b"]})
        out = self.run_it(url="http://127.0.0.1:9")
        self.assertIn("could not be read", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
