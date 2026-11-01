"""data-management.pull — one archive from a LINKED office into this office's archive root.

Moving an app between two linked offices is: export it there, bring the archive HERE, import it
here. The first and the last already exist; this is the middle, and it is a PULL on purpose. The
office that will be written to fetches artifacts the other one already serves (its download
route), one GET per artifact, each checked against the manifest before it is kept — so there is no
upload door to harden, an interrupted transfer costs the artifact in flight, and nothing the other
office sends is believed before it is hashed.

The way to the other office is the console's own door (`/a/<alias>.<office>/`): the ONE place that
knows how this office reaches a linked one and as whom. Nothing about the link is restated here — an
office that does not give its data-management to this one simply has no such door.

A module of its own, not a section of `app.py`: it is the only part of this service that speaks
HTTP to anybody, and it has nothing to do with jobs or routes — `archive()` takes a `say` and
raises with the sentence to show.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request

CONSOLE = os.environ.get("CONSOLE_INTERNAL_URL", "http://console:8000").rstrip("/")
PEER_ALIAS = "data-management"                   # this service, as a linked office names it
OFFICE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ARCHIVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")
ARTIFACT = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
MANIFEST_LIMIT = 8 << 20                         # a manifest is a few KB; this is a ceiling, not a size


def _peer_get(office: str, name: str, artifact: str):
    url = (f"{CONSOLE}/a/{PEER_ALIAS}.{office}/api/archives/"
           f"{urllib.parse.quote(name)}/download/{urllib.parse.quote(artifact)}")
    return urllib.request.urlopen(urllib.request.Request(url), timeout=120)


def fetch(office: str, name: str, artifact: str, dest: pathlib.Path, limit: int) -> tuple[str, int]:
    """One artifact into `dest`, never more than `limit` bytes. Returns (sha256, bytes)."""
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with _peer_get(office, name, artifact) as r, part.open("wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                part.unlink(missing_ok=True)
                raise ValueError(f"{artifact} is longer than the {limit} bytes it claims")
            digest.update(chunk)
            out.write(chunk)
    part.replace(dest)
    return digest.hexdigest(), size


def _said(e: urllib.error.HTTPError) -> str:
    """The other office's own sentence, when it sent one: its services answer an error as JSON with
    a `detail` or an `error`. Anything else (a proxy's HTML page) is not a sentence and is left out."""
    try:
        doc = json.loads(e.read(4000) or b"{}")
    except ValueError:
        return ""
    return str(doc.get("detail") or doc.get("error") or "")[:300] if isinstance(doc, dict) else ""


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive(office: str, name: str, target: pathlib.Path, root: pathlib.Path, say) -> None:
    """Bring `name` from `office` into `target`, or raise with the reason.

    The manifest is written LAST: the archive list calls a directory without one "incomplete", which
    is exactly what a half-pulled archive is. `root` is where free space is measured.
    """
    pulled = target / "manifest.json.pulled"
    try:
        target.mkdir(parents=True, exist_ok=True)
        fetch(office, name, "manifest.json", pulled, MANIFEST_LIMIT)
        man = json.loads(pulled.read_text(encoding="utf-8"))
        arts = man.get("artifacts") if isinstance(man, dict) else None
        if not isinstance(arts, dict):
            raise ValueError("the manifest names no artifacts")
        wanted = []
        for rel, e in sorted(arts.items()):
            if not isinstance(e, dict) or e.get("kind") == "skipped":
                continue
            size, digest = e.get("bytes"), str(e.get("sha256") or "")
            # The NAME is the other office's word and becomes a path here: plain segments only.
            if (not ARTIFACT.match(rel) or ".." in rel.split("/") or rel.startswith("manifest.json")
                    or not isinstance(size, int) or size < 0 or len(digest) != 64):
                raise ValueError(f"the manifest's entry {rel!r} is not one this office will fetch")
            wanted.append((rel, size, digest))
        total = sum(size for _rel, size, _d in wanted)
        free = shutil.disk_usage(root).free
        if total * 1.1 > free:
            raise RuntimeError(f"the archive is {total / 1e6:.0f} MB and {root} has "
                               f"{free / 1e6:.0f} MB free")
        say(f"[pull] {name} from {office}: {len(wanted)} artifact(s), {total / 1e6:.1f} MB")
        for rel, size, digest in wanted:
            dest = target / rel
            if dest.is_file() and dest.stat().st_size == size and sha(dest) == digest:
                say(f"[pull]   = {rel} (already here)")
                continue
            got, n = fetch(office, name, rel, dest, size)
            if n != size or got != digest:
                dest.unlink(missing_ok=True)
                raise ValueError(f"{rel} arrived as {n} bytes / {got[:12]}…, the manifest says "
                                 f"{size} / {digest[:12]}…")
            say(f"[pull]   + {rel}  {n / 1e6:.1f} MB")
        pulled.replace(target / "manifest.json")
        say(f"[pull] DONE  {target}")
    except urllib.error.HTTPError as e:
        # The other office's own sentence is in the body, and it is the only account of WHY there
        # is: read it before it is gone.
        pulled.unlink(missing_ok=True)
        said = _said(e)
        raise RuntimeError(
            f"{office} did not hand over '{name}' (HTTP {e.code}{': ' + said if said else ''}) — the "
            f"archive is not there, or that office does not give its data-management to this one") from e
    except Exception:
        pulled.unlink(missing_ok=True)
        raise
