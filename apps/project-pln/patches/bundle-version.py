#!/usr/bin/env python3
"""
bundle-version.py — the patched frontend gets an address made of its own bytes.  RUN at build time.

    RUN python3 /app/patches/bundle-version.py        (Dockerfile, after patches/hebrew-strings.py)

WHY. This deployment PATCHES a prebuilt bundle in place (patches/hebrew-strings.py rewrites 642
strings inside `/app/web/assets/*.js`), and Vite names those files by a hash of the SOURCE they were
built from — not of the bytes this image serves. So a patched chunk keeps the name of the chunk it
replaced, and any browser that already holds that name has no reason to ask for it again. Measured
2026-10-08: the owner refreshed Plane after the Hebrew patch and read the same English screen — his
browser was serving its own copy of `layout-CjRcgqEa.js`, whose bytes had changed under an unchanged
URL and whose response carried no `Cache-Control` at all (Caddy's file_server sends ETag and
Last-Modified only, so a browser may treat the copy as fresh without asking).

WHAT IT DOES, in two steps that cannot be half-done:

  1. RENAMES `/app/web/assets` to `/app/web/assets-<12 hex of the bundle's own contents>` — the
     directory's name IS the content's hash, so the same name always means the same bytes.
  2. REWRITES every absolute reference to it (`/assets/…` → `/assets-<hash>/…`) in the files that
     carry one (index.html, the JS chunks, CSS, the web manifest).

…and REFUSES to finish unless the result is consistent: nothing in the bundle still points at the old
directory, every `/<new>/<file>` a file references exists on disk, and the entry the HTML names is
one of them. A rename whose references were not all rewritten is a frontend that 404s, so it fails the
build here instead.

With the address tied to the bytes, the app's Caddyfile can serve that directory `immutable` — it is
the one thing in this container that can never go stale — and everything else `no-cache`.

Re-running is a no-op: an already-versioned bundle says so and exits 0.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import sys

WEB = pathlib.Path(os.environ.get("PLANE_WEB_DIR") or "/app/web")
PLAIN = "assets"
# A reference to the bundle's OWN directory — and not the API path `/api/assets/v2/…`, which carries
# the same five characters in the middle of a URL. The lookbehind is the whole difference: without it
# this script's own invariant check caught the first version rewriting that API path into
# `/api/assets-<hash>/v2/…` — i.e. every attachment upload 404ing. Refuse, never guess.
BOUNDARY = r"(?<![A-Za-z0-9_/.\-])"
REF = re.compile(BOUNDARY + r"/assets/([A-Za-z0-9._-]+)")
# …and the RELATIVE form, which is the one that got away: Vite's `__vite__mapDeps` array holds bare
# module names — `["assets/AppProgressBar-….js", …]` — that its preload helper resolves against the
# document base (`/`), while every other reference is absolute. Only the absolute ones were rewritten
# on the first pass, so the app booted, asked for `/assets/<chunk>.js`, met the retired path's 404 and
# died in React error #418 — measured 2026-10-08 with a headless run against the live container. The
# quote in front is what keeps this apart from `/api/assets/v2/…` and from the new `assets-<hash>/`.
REL = re.compile(r'(["\'])assets/([A-Za-z0-9._-]+)')
TEXT = (".html", ".js", ".css", ".json", ".webmanifest", ".xml", ".txt")


def bundle_hash(d: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def main() -> int:
    plain = WEB / PLAIN
    versioned = sorted(p for p in WEB.glob("assets-*") if p.is_dir())
    if not plain.is_dir():
        if versioned:
            print(f"bundle-version: already versioned as {versioned[0].name} — nothing to do")
            return 0
        print(f"bundle-version: neither {PLAIN}/ nor an assets-<hash>/ is under {WEB} — the bundle "
              f"is not where the Dockerfile put it")
        return 1

    name = f"assets-{bundle_hash(plain)}"
    (WEB / name)
    refs = 0
    files = 0
    for p in sorted(WEB.rglob("*")):
        # …including the files INSIDE the assets directory: their imports of each other are relative
        # (`./x.js`, which cannot match `/assets/`), but a font or an image URL is absolute there too.
        if not p.is_file() or p.suffix.lower() not in TEXT:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new, n = REF.subn(f"/{name}/\\1", text)
        new, n2 = REL.subn(lambda m: f"{m.group(1)}{name}/{m.group(2)}", new)
        if n or n2:
            p.write_text(new, encoding="utf-8")
            refs += n + n2
            files += 1

    if not refs:
        print("bundle-version: NOTHING references /assets/ — the layout is not what this expects")
        return 1

    # …the invariants that make the rename safe. First on the TEXT (before anything moves): a single
    # reference left behind is a file the browser asks for and does not get.
    left, bad = 0, {}
    refs_to = {}
    for p in sorted(WEB.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        left += len(re.findall(BOUNDARY + r"/assets/", text))
        left += len(REL.findall(text))
        for ref in re.findall(BOUNDARY + rf"/{re.escape(name)}/([A-Za-z0-9._-]+)", text):
            refs_to.setdefault(ref, p.relative_to(WEB))
    if left:
        print(f"bundle-version: {left} references still point at /assets/ — refusing")
        return 1

    # COPY, then remove — not `rename`. Measured in this image's build: `os.rename` of the directory
    # inside its own parent fails with `OSError: [Errno 18] Cross-device link` (the builder's view of
    # /app/web is not the plain directory it looks like), and a copy is right in every layout anyway.
    shutil.copytree(plain, WEB / name)
    shutil.rmtree(plain)

    # …and then on the DISK: everything any file now asks for must exist under the new name.
    bad = [f"{src} → {ref}" for ref, src in sorted(refs_to.items()) if not (WEB / name / ref).exists()]
    # The HTML boots the SPA from an INLINE module script at the END of the document (`import
    # "/assets-<hash>/entry.client-….js"` — react-router's SSR export), so there is no `src=` to read:
    # the check is that the HTML names files of the NEW directory and they are on disk.
    index = WEB / "index.html"
    html = index.read_text(encoding="utf-8") if index.exists() else ""
    named = re.findall(BOUNDARY + rf"/{re.escape(name)}/([A-Za-z0-9._-]+)", html)
    entry = next((n for n in named if (WEB / name / n).exists()), None)

    if left:
        print(f"bundle-version: {left} references still point at /assets/ — refusing")
        return 1
    if bad:
        print("bundle-version: references to files that do not exist after the rename — refusing:")
        for b in bad[:10]:
            print(f"    · {b}")
        return 1
    if not named or not entry:
        print("bundle-version: index.html names nothing under the new directory — refusing")
        return 1

    print(f"bundle-version: {PLAIN}/ → {name}/ — {refs} references in {files} files; "
          f"index.html names {len(named)} of them, first {entry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
