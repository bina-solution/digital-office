#!/usr/bin/env python3
"""push-images (scripts/ci/push-images.sh, scripts/ci/images-plan.py): the line's ready-made images, built once on the
runner (DGO-2123).

    python3 scripts/test_push_images.py

A throwaway git repository stands in for the checkout: a last green commit (refs/remotes/origin/green/dgo-stable), the
images.json it named (refs/remotes/origin/images/dgo-stable), and this proof's commit on top. `curl` (does the image
store answer?) and `docker` (build, push, the digest it read back) are stand-ins on PATH that log every call, so a
decision is read from what was BUILT and PUSHED, not only from what was printed. Standard library only.
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci" / "push-images.sh"
PLAN = REPO / "scripts" / "ci" / "images-plan.py"
PREFIX = "ghcr.io/bina-solution/digital-office"

DOCKER = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
fail = set(os.environ.get("STUB_FAIL", "").split())
tag = next((a for a in args if ":" in a and "/" in a and not a.startswith("-")), "")
image = tag.split("/", 1)[-1].split(":")[0] if tag else ""
if args[:1] == ["build"] or args[:2] == ["buildx", "build"]:
    sys.exit(1 if "build:" + image in fail else 0)
if args[:1] == ["push"]:
    sys.exit(1 if "push:" + image in fail else 0)
if args[:2] == ["image", "inspect"]:
    if "{{.Size}}" in args:   # the engine's own size of the image, in bytes (STUB_SIZES: "<id>=<bytes> …")
        sizes = dict(x.split("=", 1) for x in os.environ.get("STUB_SIZES", "").split() if "=" in x)
        print(sizes.get(image, "150000000"))
        sys.exit(0)
    if "digest:" + image in fail:
        sys.exit(0)
    print(tag.rsplit(":", 1)[0] + "@sha256:" + ("%064x" % (abs(hash(image)) % (1 << 64))))
    sys.exit(0)
sys.exit(0)
'''

# the store answers while STUB_STORE is set; a manifest of an image in STUB_MISSING is not there (curl -f: 22)
CURL = ('#!/bin/sh\n[ -n "$STUB_STORE" ] || { echo "curl: (7) Failed to connect" >&2; exit 7; }\n'
        'for m in $STUB_MISSING; do case "$*" in *"/v2/$m/manifests/"*) exit 22 ;; esac; done\nexit 0\n')


def compose(app, build="    build:\n      context: .\n      dockerfile: Dockerfile\n", image=None):
    """a docker-compose.yml as the apps write theirs: one service, its image named as images.yml names it"""
    return ("services:\n  %s:\n%s    image: %s\n    volumes:\n      - type: bind\n        source: ./data\n"
            "        target: /data\n" % (app, build, image or "%s/%s:${IMAGE_TAG:-latest}" % (PREFIX, app)))


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def load_plan():
    spec = importlib.util.spec_from_file_location("images_plan", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PushImages(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="push-images-"))
        r = self.repo = self.tmp / "repo"
        (r / "scripts" / "ci").mkdir(parents=True)
        shutil.copy(SCRIPT, r / "scripts" / "ci" / "push-images.sh")
        shutil.copy(PLAN, r / "scripts" / "ci" / "images-plan.py")
        for app, files in (("a", ("app.json", "Dockerfile")), ("b", ("app.json", "Dockerfile")),
                           ("apitools", ("app.json", "Dockerfile")), ("c", ("app.json",)),
                           ("nomanifest", ("Dockerfile",))):
            (r / "apps" / app).mkdir(parents=True)
            for f in files:
                (r / "apps" / app / f).write_text(f"{app} {f}\n")
            (r / "apps" / app / "docker-compose.yml").write_text(compose(app))
        (r / "platform-base" / "console").mkdir(parents=True)
        for f in ("app.json", "Dockerfile"):
            (r / "platform-base" / "console" / f).write_text("console\n")
        (r / "platform-base" / "console" / "docker-compose.yml").write_text(
            "services:\n  console:\n    build: {context: ., dockerfile: Dockerfile}\n"
            "    image: %s/console:${IMAGE_TAG:-latest}\n" % PREFIX)
        git(r, "init", "-q", "-b", "dgo-stable")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "the last green")
        self.green = git(r, "rev-parse", "HEAD")
        git(r, "update-ref", "refs/remotes/origin/green/dgo-stable", self.green)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "docker").write_text(DOCKER.replace("{python}", sys.executable))
        (bin_ / "curl").write_text(CURL)
        for f in ("docker", "curl"):
            os.chmod(bin_ / f, 0o755)
        self.bin, self.log = bin_, self.tmp / "docker.log"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def named(self, images, green=None):
        """refs/remotes/origin/images/dgo-stable: an images.json the last list named, made for `green`"""
        doc = {"green": green or self.green, "built": [], "images": images}
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.repo, input=json.dumps(doc),
                              capture_output=True, text=True, check=True).stdout.strip()
        tree = subprocess.run(["git", "mktree"], cwd=self.repo, input=f"100644 blob {blob}\timages.json\n",
                              capture_output=True, text=True, check=True).stdout.strip()
        commit = git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree, "-m", "images")
        git(self.repo, "update-ref", "refs/remotes/origin/images/dgo-stable", commit)

    def change(self, *paths):
        for p in paths:
            f = self.repo / p
            f.write_text(f.read_text() + "changed\n")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "this proof")
        return git(self.repo, "rev-parse", "HEAD")

    def app(self, name, compose_text):
        """one more app in the set (an app.json and a Dockerfile) with this compose file, committed"""
        d = self.repo / "apps" / name
        d.mkdir(parents=True)
        (d / "app.json").write_text("{}\n")
        (d / "Dockerfile").write_text("FROM scratch\n")
        (d / "docker-compose.yml").write_text(compose_text)
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "app " + name)

    def run_it(self, store=True, fail="", builder="capped", sizes="", missing=""):
        if self.log.exists():
            self.log.unlink()
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", STUB_LOG=str(self.log),
                   STUB_STORE="1" if store else "", STUB_FAIL=fail, BUILDER=builder, STUB_SIZES=sizes,
                   STUB_MISSING=missing)
        p = subprocess.run(["bash", str(self.repo / "scripts" / "ci" / "push-images.sh")], capture_output=True,
                           text=True, env=env, timeout=120)
        calls = [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.exists() else []
        out = json.loads(p.stdout) if p.stdout.strip() else None
        return p, out, calls

    def built(self, calls):
        """The images the engine was asked to build: the name in each build's tag (<host:port>/<id>:<sha>)."""
        tags = [next(a for a in c if "/" in a and ":" in a and not a.startswith("-"))
                for c in calls if c[:1] == ["build"] or c[:2] == ["buildx", "build"]]
        return sorted(t.split("/")[-1].split(":")[0] for t in tags)

    def test_no_store_pushes_nothing(self):
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it(store=False)
        self.assertEqual((p.returncode, out, calls), (0, None, []))
        self.assertIn("no image store answers", p.stderr)

    def test_a_changed_image_is_built_pushed_and_named_and_the_rest_keep_their_digest(self):
        self.named({"b": {"digest": "sha256:" + "b" * 64, "name": PREFIX + "/b", "built_from": self.green}})
        head = self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.built(calls), ["a"], "only what changed is built")
        pushes = [c for c in calls if c[:1] == ["push"]]
        self.assertEqual(pushes, [["push", "127.0.0.1:5055/a:" + head[:12]]], "the ENGINE pushes, through the loopback")
        self.assertEqual(out["green"], head)
        self.assertEqual(out["built"], ["a"])
        self.assertEqual(sorted(out["images"]), ["a", "b"])
        self.assertTrue(out["images"]["a"]["digest"].startswith("sha256:"))
        self.assertEqual(out["images"]["a"]["name"], PREFIX + "/a")
        self.assertEqual(out["images"]["a"]["built_from"], head)
        self.assertEqual(out["images"]["a"]["dir"], "apps/a", "the take checks the office's own tree there")
        self.assertEqual(out["images"]["b"]["digest"], "sha256:" + "b" * 64, "an unchanged image keeps its digest")
        self.assertEqual((out["images"]["b"]["built_from"], out["images"]["b"]["dir"]), (self.green, "apps/b"))

    def test_never_an_image_outside_the_set(self):
        # a changed app on images.yml's skip list, one with no Dockerfile, a Dockerfile with no manifest
        self.change("apps/apitools/Dockerfile", "apps/c/app.json", "apps/nomanifest/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual((self.built(calls), out), ([], None))
        self.change("platform-base/console/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(self.built(calls), ["console"], "platform-base apps are in the set too, a flow-style build too")

    def test_an_unchanged_image_never_named_stays_the_offices_own_build(self):
        # the store's first proof builds what its batch changed — never every image at once on the Dell
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(sorted(out["images"]), ["a"])

    def test_an_image_that_fails_is_named_by_no_list(self):
        # the reader (DGO-2123): a changed image whose build failed kept the last green's digest, so a take pulled the
        # code from before the change, built nothing (BBOX_PREBUILT), and ran it
        self.named({"a": {"digest": "sha256:" + "a" * 64, "name": PREFIX + "/a", "built_from": self.green}})
        self.change("apps/a/Dockerfile", "apps/b/Dockerfile")
        for fail, what in (("build:a", "did not build"), ("push:a", "was built and not pushed"),
                           ("digest:a", "was pushed and its digest not read")):
            p, out, calls = self.run_it(fail=fail)
            self.assertEqual(p.returncode, 0, fail)
            self.assertIn("::warning::push-images: a " + what, p.stderr)
            self.assertIn("no list names it", p.stderr)
            self.assertEqual(out["built"], ["b"], fail)
            self.assertNotIn("a", out["images"], "never the older digest under this version's name: " + fail)

    def test_the_engine_keeps_no_tag_once_the_store_holds_it(self):
        # the Dell's engine kept every proof's tag of every image it built (its disk, 92% on 2026-11-20)
        head = self.change("apps/a/Dockerfile", "apps/b/Dockerfile")
        p, out, calls = self.run_it(fail="push:b")
        removed = [c[2] for c in calls if c[:2] == ["image", "rm"]]
        self.assertEqual(sorted(removed), ["127.0.0.1:5055/a:" + head[:12], "127.0.0.1:5055/b:" + head[:12]],
                         "after its push, and after a push that failed")
        reads = [i for i, c in enumerate(calls) if c[:2] == ["image", "inspect"] and "{{.Size}}" not in c]
        rm_a = calls.index(["image", "rm", "127.0.0.1:5055/a:" + head[:12]])
        self.assertTrue(reads and reads[0] < rm_a, "the digest is read before the tag goes")
        self.assertEqual(out["built"], ["a"])

    def test_an_image_over_the_stores_size_is_never_pushed(self):
        # three lists of a 7.9 GiB image would be most of the store, against the Dell's 19.6 GB free (2026-11-20)
        head = self.change("apps/a/Dockerfile", "apps/b/Dockerfile")
        p, out, calls = self.run_it(sizes="a=2000000000")
        self.assertEqual([c for c in calls if c[:1] == ["push"]], [["push", "127.0.0.1:5055/b:" + head[:12]]])
        self.assertIn("::warning::push-images: a is 1907 MiB, over the store's 1024 MiB an image — not pushed", p.stderr)
        self.assertIn(["image", "rm", "127.0.0.1:5055/a:" + head[:12]], calls, "and it leaves the engine")
        self.assertEqual((out["built"], sorted(out["images"])), (["b"], ["b"]))

    def test_a_kept_digest_gone_from_the_store_is_built_again(self):
        # the second reader: a prune that read a stale list deleted a digest the newest list named, and every later list
        # carried it — every office built everything on every take. A list names only what the store holds.
        self.named({"b": {"digest": "sha256:" + "b" * 64, "name": PREFIX + "/b", "built_from": self.green}})
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it(missing="b")
        self.assertEqual(self.built(calls), ["a", "b"])
        self.assertIn("push-images: b: the digest the last list named is not in the store — built again", p.stderr)
        self.assertNotEqual(out["images"]["b"]["digest"], "sha256:" + "b" * 64)
        p, out, calls = self.run_it()   # …and one the store holds is kept, as before
        self.assertEqual((self.built(calls), out["images"]["b"]["digest"]), (["a"], "sha256:" + "b" * 64))

    def test_a_heavy_image_is_never_built(self):
        self.app("android-emulator", compose("android-emulator"))
        self.change("apps/android-emulator/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(self.built(calls), [], "named in images-plan.py's HEAVY: not even built")
        self.assertIn("push-images: android-emulator: too heavy for the store (7.9 GiB", p.stderr)

    def test_a_list_behind_the_green_is_measured_from_its_own_commit(self):
        # the reader (DGO-2123): a proof whose store was down moved refs/green alone; what ITS batch changed was then
        # «unchanged since the last green», and the older digest was carried under the newer version's name
        self.named({"b": {"digest": "sha256:" + "b" * 64, "name": PREFIX + "/b", "built_from": self.green}})
        moved = self.change("apps/b/Dockerfile")
        git(self.repo, "update-ref", "refs/remotes/origin/green/dgo-stable", moved)   # green moved, the list did not
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(self.built(calls), ["a", "b"], "b changed since the list's own commit: built again")
        self.assertNotEqual(out["images"]["b"]["digest"], "sha256:" + "b" * 64)

    def test_a_named_image_whose_directory_moved_on_is_built_again(self):
        # an entry is kept only while its directory is what it was built from, whatever the list's commit says
        old = self.change("apps/b/Dockerfile")
        self.named({"b": {"digest": "sha256:" + "b" * 64, "name": PREFIX + "/b", "built_from": self.green}}, green=old)
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual(self.built(calls), ["a", "b"])

    def test_only_a_build_an_office_makes_the_same_way_is_built(self):
        # the reader (DGO-2123): the runner built `docker build <dir>` whatever compose declared — project-pln without
        # its Hebrew build's args, app-management without its compose version
        cases = {
            "withargs": compose("withargs", "    build:\n      context: .\n      args:\n        - V=${V:-1}\n"),
            "withtarget": compose("withtarget", "    build:\n      context: .\n      target: runtime\n"),
            "twocontexts": compose("twocontexts", "    build:\n      context: .\n      additional_contexts:\n"
                                                  "        door: ../door\n"),
            "otherfile": compose("otherfile", "    build:\n      context: .\n      dockerfile: Dockerfile.desktop\n"),
            "elsewhere": compose("elsewhere", "    build:\n      context: ../..\n"),
            "localname": compose("localname", image="localname:${IMAGE_TAG:-latest}"),
            "nobuild": compose("nobuild", ""),
            "short": compose("short", "    build: .\n"),
            "nofile": compose("nofile", "    build:\n      context: ./\n"),
        }
        for name, text in cases.items():
            self.app(name, text)
        self.change(*["apps/%s/Dockerfile" % n for n in cases])
        p, out, calls = self.run_it()
        self.assertEqual(self.built(calls), ["nofile", "short"], p.stderr)
        for name, why in (("withargs", "its build declares args"), ("withtarget", "its build declares target"),
                          ("twocontexts", "its build declares additional_contexts"),
                          ("otherfile", "it builds Dockerfile.desktop, not its Dockerfile"),
                          ("elsewhere", "it builds from ../.., not its own directory"),
                          ("localname", "its compose names no image %s/localname" % PREFIX),
                          ("nobuild", "it is named with no build")):
            self.assertIn("push-images: %s: %s — each office builds it as today" % (name, why), p.stderr)

    def test_no_last_green_builds_nothing(self):
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/green/dgo-stable")
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        self.assertEqual((p.returncode, out, calls), (0, None, []))

    def test_only_in_a_capped_builder_of_the_jobs_own(self):
        self.change("apps/a/Dockerfile")
        p, out, calls = self.run_it()
        b = [c for c in calls if c[:2] == ["buildx", "build"]]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0][b[0].index("--builder") + 1], "capped")
        self.assertIn("--load", b[0], "loaded into the engine, which pushes it")
        # the reader (DGO-2123): a builder that failed to start left BUILDER empty, and the build ran uncapped
        p, out, calls = self.run_it(builder="")
        self.assertEqual((p.returncode, out, calls), (0, None, []))
        self.assertIn("no capped builder was named", p.stderr)

    def test_the_skip_list_is_images_yml_s(self):
        text = SCRIPT.read_text(encoding="utf-8")
        mine = re.search(r'^SKIP="([^"]*)"', text, re.M).group(1).split()
        theirs = re.search(r'skip="([^"]*)"', (REPO / ".github" / "workflows" / "images.yml").read_text()).group(1).split()
        self.assertEqual(sorted(mine), sorted(theirs))


class ReadingACompose(unittest.TestCase):
    """images-plan.py reads a compose file with the standard library alone: what a service builds, and from what"""

    def setUp(self):
        self.p = load_plan()

    def test_a_service_s_build_and_image(self):
        text = ("x-shared: &shared\n  restart: unless-stopped\nservices:\n  web:\n    <<: *shared\n    build:\n"
                "      context: .   # its own directory\n      dockerfile: Dockerfile\n    image: \"%s/web:${T:-x}\"\n"
                "    ports:\n    - \"8080:80\"\n    command: |\n      image: not-this\n  side:\n    image: other\n"
                "    build: {context: ., dockerfile: Dockerfile.side}\n" % PREFIX)
        self.assertEqual(self.p.builds_of(text, PREFIX + "/web"),
                         [("web", {"context": ".", "dockerfile": "Dockerfile"})])
        self.assertIsNone(self.p.plain({"context": ".", "dockerfile": "Dockerfile"}))
        self.assertEqual(self.p.builds_of(text, "other"), [("side", "{context: ., dockerfile: Dockerfile.side}")])
        self.assertEqual(self.p.plain("{context: ., dockerfile: Dockerfile.side}"),
                         "it builds Dockerfile.side, not its Dockerfile")
        self.assertEqual(self.p.builds_of(text, "not-this"), [], "a block scalar's text is no service")
        self.assertEqual(self.p.builds_of(text, PREFIX + "/we"), [], "a name is matched whole, never as a prefix")

    def test_every_compose_file_here_is_read(self):
        # the reading of this repository's own files: none raises, and what it reads is a mapping of services
        n = 0
        for f in sorted(REPO.glob("apps/*/docker-compose.yml")) + sorted(REPO.glob("platform-base/*/docker-compose.yml")):
            doc, _ = self.p._mapping(self.p._lines(f.read_text(encoding="utf-8")), 0, 0)
            self.assertIsInstance(doc.get("services", {}), dict, str(f))
            n += 1
        self.assertGreater(n, 20, "the files were found")


#: What this suite tests, for the CI's «changed since the last green» (scripts/ci/since_green.py): 69 s of G72's one
#: `scripts/` worker on batch 114, the second slowest suite of the line. It reads the real compose files and images.yml.
SUBJECTS = ("scripts/ci/push-images.sh", "scripts/ci/images-plan.py", "scripts/test_push_images.py",
            ".github/workflows/images.yml", ":(glob)apps/*/docker-compose.yml",
            ":(glob)platform-base/*/docker-compose.yml")

if __name__ == "__main__":
    _spec = importlib.util.spec_from_file_location("since_green", REPO / "scripts" / "ci" / "since_green.py")
    since_green = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(since_green)
    since_green.or_not_run(REPO, SUBJECTS)
    unittest.main(verbosity=1)
