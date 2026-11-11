#!/usr/bin/env python3
"""test_hand_back.py — a compile run as root leaves the office's checkout the owner's (reconcile.hand_back, DGO-121).

    python3 platform/manager/test_hand_back.py

Measured 2026-11-10 on the Dell: 843 of 1,077 entries of .generated/ were root's, from renders the control plane runs
as root. What is asked of hand_back: nothing at all unless the process is root and the checkout is not root's; then
every root-owned entry under .generated/ (files and directories, at any depth) and the compiled files in committed
directories (the sign-in blueprint, traefik's zz-https.yaml and zz-serve.yaml) go to the checkout's uid:gid, and
nothing the owner already owns, nor a committed file, is touched; a link is handed back itself and never followed —
what it points at is never changed and a linked directory is never descended (a walk that followed it FAILS here);
a .generated that is itself a link is not walked; an entry that cannot be changed is skipped, and a stat that fails
is never raised (hand_back runs in a `finally`). A test is not root, so ownership is faked: os.lstat/os.lchown/os.stat
answer from a table, keyed by the path as asked.
"""
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_hand_back_mod", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_hand_back_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
OWNER = (1000, 1000)


class _Owned:
    """A stat result with its owner replaced; every other field is the real one."""

    def __init__(self, real, uid):
        self._real, self.st_uid, self.st_gid = real, uid, uid

    def __getattr__(self, name):
        return getattr(self._real, name)


class Fake:
    """Ownership by path: the paths in `root_owned` are root's, everything else the owner's; lchown is recorded."""

    def __init__(self, repo, root_owned, repo_uid=1000, refuse=(), unreadable=()):
        self.repo, self.root_owned, self.repo_uid = str(repo), {str(p) for p in root_owned}, repo_uid
        self.refuse, self.unreadable = {str(p) for p in refuse}, {str(p) for p in unreadable}
        self.calls = []
        self.real_lstat, self.real_stat, self.real_lchown = os.lstat, os.stat, getattr(os, "lchown", None)

    def lstat(self, p, *a, **k):
        if str(p) in self.unreadable:
            raise PermissionError(13, "Permission denied", str(p))      # EACCES/EIO: not an ENOENT is_dir() swallows
        real = self.real_lstat(p, *a, **k)                              # a missing path raises, as it does for root
        return _Owned(real, 0 if str(p) in self.root_owned else OWNER[0])

    def stat(self, p, *a, **k):
        if str(p) == self.repo:
            return types.SimpleNamespace(st_uid=self.repo_uid, st_gid=self.repo_uid)
        return self.real_stat(p, *a, **k)

    def lchown(self, p, uid, gid):
        if str(p) in self.refuse:
            raise PermissionError(p)
        self.calls.append((str(p), uid, gid))

    def __enter__(self):
        os.lstat, os.stat, os.lchown = self.lstat, self.stat, self.lchown
        return self

    def __exit__(self, *exc):
        os.lstat, os.stat = self.real_lstat, self.real_stat
        if self.real_lchown is None:
            del os.lchown
        else:
            os.lchown = self.real_lchown


def tempdir(test, prefix):
    d = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, d, True)
    return d


def tree(test):
    repo = tempdir(test, "dgo121-")
    gen = repo / ".generated"
    (gen / "registry").mkdir(parents=True)
    (gen / "n8n" / "indox").mkdir(parents=True)
    for p in ("compose.yml", "registry/remote.hp-laptop.drive.json", "registry/console.modules.yaml",
              "n8n/indox/a.json"):
        (gen / p).write_text("x", encoding="utf-8")
    for f in rc.HAND_BACK_FILES + ("platform-base/authentik/blueprints/deployment-apps.yaml",
                                   "platform-base/traefik/config/authentik-forwardauth.yaml"):
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text("x", encoding="utf-8")
    outside = tempdir(test, "dgo121-out-")
    (outside / "secret").write_text("x", encoding="utf-8")
    os.symlink(outside / "secret", gen / "registry" / "link-out")
    os.symlink(outside, gen / "linked-dir")
    return repo, gen, outside


class HandBack(unittest.TestCase):
    def test_not_root_does_nothing(self):
        repo, gen, _ = tree(self)
        with Fake(repo, [gen / "compose.yml"]) as f:
            self.assertEqual(rc.hand_back(repo, euid=1000), 0)
        self.assertEqual(f.calls, [])

    def test_a_checkout_root_owns_keeps_root_files(self):
        repo, gen, _ = tree(self)
        with Fake(repo, [gen / "compose.yml"], repo_uid=0) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), 0)
        self.assertEqual(f.calls, [])

    def test_root_owned_entries_go_to_the_owner_at_any_depth(self):
        repo, gen, _ = tree(self)
        roots = [gen / "registry", gen / "registry" / "remote.hp-laptop.drive.json", gen / "n8n",
                 gen / "n8n" / "indox", gen / "n8n" / "indox" / "a.json"] + [repo / f for f in rc.HAND_BACK_FILES]
        with Fake(repo, roots) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), len(roots))
        self.assertEqual(sorted(p for p, _u, _g in f.calls), sorted(str(p) for p in roots))
        self.assertTrue(all((u, g) == OWNER for _p, u, g in f.calls))

    def test_what_the_owner_owns_and_committed_files_are_not_touched(self):
        repo, gen, _ = tree(self)
        committed = [repo / "platform-base/authentik/blueprints/deployment-apps.yaml",
                     repo / "platform-base/traefik/config/authentik-forwardauth.yaml"]
        with Fake(repo, committed) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), 0)
        self.assertEqual(f.calls, [])

    def test_a_link_is_handed_back_itself_and_never_followed(self):
        repo, gen, outside = tree(self)
        # root's: the two links, what they point at, AND the path through the linked directory — a walk that followed
        # `linked-dir` would list gen/linked-dir/secret, and root would chown the file outside through it
        roots = [gen / "registry" / "link-out", gen / "linked-dir", outside / "secret", outside,
                 gen / "linked-dir" / "secret"]
        with Fake(repo, roots) as f:
            rc.hand_back(repo, euid=0)
        called = sorted(p for p, _u, _g in f.calls)
        self.assertEqual(called, sorted([str(gen / "linked-dir"), str(gen / "registry" / "link-out")]))

    def test_a_linked_generated_is_not_walked(self):
        repo, real = tempdir(self, "dgo121-"), tempdir(self, "dgo121-real-")
        (real / "f").write_text("x", encoding="utf-8")
        os.symlink(real, repo / ".generated")
        with Fake(repo, [real / "f", repo / ".generated" / "f"]) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), 0)
        self.assertEqual(f.calls, [])

    def test_an_entry_that_cannot_change_is_skipped_never_raised(self):
        repo, gen, _ = tree(self)
        a, b = gen / "compose.yml", gen / "registry" / "console.modules.yaml"
        with Fake(repo, [a, b], refuse={a}) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), 1)
        self.assertEqual([p for p, _u, _g in f.calls], [str(b)])

    def test_a_stat_that_fails_is_never_raised(self):
        repo, gen, _ = tree(self)
        with Fake(repo, [gen / "compose.yml"], unreadable={gen}) as f:
            self.assertEqual(rc.hand_back(repo, euid=0), 0)          # .generated unreadable: not walked, no raise
        self.assertEqual(f.calls, [])

    def test_no_checkout_at_all(self):
        self.assertEqual(rc.hand_back(pathlib.Path(tempfile.gettempdir()) / "dgo121-none-here", euid=0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
