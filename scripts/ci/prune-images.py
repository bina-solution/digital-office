#!/usr/bin/env python3
"""prune-images — the image store keeps what the line's last lists name, and gives back the rest (DGO-2123).

    python3 scripts/ci/prune-images.py [--keep 3] [--dry-run]    # in the proof's green job, after refs/green moved

Every proof pushes the images its batch changed to the store on the Dell (scripts/ci/push-images.sh), and nothing
removed them. The Dell's disk was 92% full on 2026-11-20. This keeps every digest the last N lists name: the commits of
refs/images/dgo-stable, newest first, each with one images.json. Every other manifest in the store is deleted through
the store's own API (image-store:5000, which takes deletes; the door is read-only). Then the registry's garbage
collection gives the space back (the green job's next step).

NEVER A GUESS. A keep set it cannot read deletes nothing, and so does a newest list it cannot read: the older lists
alone would delete what the newest names. A keep set that shares no digest with a store that holds images deletes
nothing either: that is another line's store, or a misread list, never «all of it is old». A tag whose digest it cannot
read is kept. It always ends 0: the store's space is never the proof's verdict. The lists are fresh: the `retention` job
fetches them into an empty repository (GIT_DIR), so one left by an earlier job is never read as the newest.

    env STORE_URL     the store, from the runner's network   (default http://image-store:5000)
        IMAGES_REF    the lists' ref, fetched beside the checkout   (default refs/remotes/origin/images/dgo-stable)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))


def say(text: str) -> None:
    print("prune-images: " + text, flush=True)


def keep_set(ref: str, lists: int) -> tuple[set, int]:
    """(the digests the newest `lists` lists name, how many lists were read). Nothing at all when the NEWEST list cannot
    be read: the older ones alone would delete what it names, the images the green that just moved points at (the
    second reader)."""
    out = subprocess.run(["git", "log", "--format=%H", "-n", str(lists), ref], capture_output=True, text=True)
    keep, read = set(), 0
    for i, commit in enumerate(out.stdout.split() if out.returncode == 0 else []):
        shown = subprocess.run(["git", "show", f"{commit}:images.json"], capture_output=True, text=True)
        try:
            doc = json.loads(shown.stdout) if shown.returncode == 0 else None
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or not isinstance(doc.get("images"), dict):
            if i == 0:
                return set(), 0
            continue
        read += 1
        keep |= {str(e.get("digest")) for e in doc["images"].values()
                 if isinstance(e, dict) and str(e.get("digest") or "").startswith("sha256:")}
    return keep, read


class Store:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _ask(self, method: str, path: str, accept: str = "application/json"):
        req = urllib.request.Request(self.url + path, method=method, headers={"Accept": accept})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers, (r.read() if method == "GET" else b"")

    def repositories(self) -> list:
        _, _, body = self._ask("GET", "/v2/_catalog?n=1000")
        return list(json.loads(body or b"{}").get("repositories") or [])

    def tags(self, repo: str) -> list:
        _, _, body = self._ask("GET", f"/v2/{repo}/tags/list")
        return list(json.loads(body or b"{}").get("tags") or [])

    def digest(self, repo: str, tag: str) -> str:
        _, headers, _ = self._ask("HEAD", f"/v2/{repo}/manifests/{tag}", ACCEPT)
        return headers.get("Docker-Content-Digest") or ""

    def delete(self, repo: str, digest: str) -> int:
        status, _, _ = self._ask("DELETE", f"/v2/{repo}/manifests/{digest}")
        return status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=3, help="how many of the newest lists to keep the images of")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    store = Store(os.environ.get("STORE_URL") or "http://image-store:5000")
    keep, read = keep_set(os.environ.get("IMAGES_REF") or "refs/remotes/origin/images/dgo-stable", max(1, a.keep))
    if not keep:
        say(f"no list of images could be read ({read} read) — nothing is deleted")
        return 0
    try:
        held = {}   # digest → [repo, …]
        for repo in store.repositories():
            for tag in store.tags(repo):
                try:
                    d = store.digest(repo, tag)
                except (urllib.error.URLError, OSError) as e:
                    say(f"{repo}:{tag} — its digest could not be read ({type(e).__name__}); kept")
                    continue
                if d.startswith("sha256:"):
                    held.setdefault(d, set()).add(repo)
    except (urllib.error.URLError, OSError, ValueError) as e:
        say(f"the store could not be read at {store.url} ({type(e).__name__}) — nothing is deleted")
        return 0
    if held and not keep & set(held):
        say(f"none of the {len(keep)} digest(s) the last {read} list(s) name is in this store of {len(held)} — "
            "another line's store, or a misread list: nothing is deleted")
        return 0
    gone = sorted((repo, d) for d, repos in held.items() if d not in keep for repo in repos)
    deleted = 0
    for repo, d in gone:
        if a.dry_run:
            say(f"would delete {repo}@{d[:19]}…")
            continue
        try:
            status = store.delete(repo, d)
            deleted += 1 if status in (200, 202) else 0
            say(f"deleted {repo}@{d[:19]}… ({status})")
        except (urllib.error.URLError, OSError) as e:
            say(f"{repo}@{d[:19]}… could not be deleted ({type(e).__name__}); kept")
    say(f"kept {len(set(held) & keep)} digest(s) the last {read} list(s) name; "
        f"{'would delete' if a.dry_run else 'deleted'} {len(gone) if a.dry_run else deleted} of {len(gone)} others")
    return 0


if __name__ == "__main__":
    sys.exit(main())
