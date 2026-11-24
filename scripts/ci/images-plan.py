#!/usr/bin/env python3
"""images-plan — which of the line's images a proof builds, keeps, or leaves to the offices (DGO-2123).

    python3 scripts/ci/images-plan.py plan   # «BUILD <id> <dir>» / «KEEP <id> <dir>», one per line; why not, on stderr
    python3 scripts/ci/images-plan.py json   # images.json, from the KEEPs (env KEEP) and stdin's «<id> <digest> <dir>»

scripts/ci/push-images.sh asks it; the design is research_notes/CICD 2026-11/images.md. Standard library only: the
runner's image has no PyYAML.

WHICH. images.yml's set — an app directory with an app.json and a Dockerfile, minus SKIP — and of those only an image an
office would build exactly as `docker build <dir>` builds it on the runner: the service whose compose image is
<PREFIX>/<id> builds from its own directory with its own Dockerfile, and declares nothing else. No args, no target, no
second context, no other Dockerfile. Anything more and every office builds it as today. An image built without an
office's build args is another image: project-pln's Hebrew build, app-management's compose version. The take asks the
same of the office's own compiled config (follow.sh images_pull), and that is the word that counts. This reading of the
compose file keeps the Dell from building what no office can use, so where it errs, an image is built for nothing or
built by each office as today. Never a wrong image.

KEEP OR BUILD. An image the last list named is kept while its directory is still what it was built from (built_from).
Otherwise, or when its directory changed since the commit that list was made for, it is built again. One that fails to
build is named by no list: never an older digest under a newer version's name (the reader, DGO-2123).
"""
import json
import os
import re
import subprocess
import sys

KEY = re.compile(r"""^("[^"]*"|'[^']*'|[^\s:'"#-][^:]*?)\s*:(?:\s+(.*))?$""")

# Images never built for the store, each with its measure. A build of one would be most of the store: three lists of it,
# against the Dell's 19.6 GB free (92% full, read through its office on 2026-11-20). push-images.sh refuses any other
# image over its MAX_IMAGE_BYTES after building it; these are named so they are not even built.
HEAVY = {
    "android-emulator": "7.9 GiB uncompressed on the Dell (its office's machine app, 2026-11-20), one office runs it",
}


def _lines(text):
    """(indent, text) of every line that holds YAML: blank lines and comments left out"""
    out = []
    for raw in text.splitlines():
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        body = re.sub(r"\s+#.*$", "", body)
        out.append((len(raw) - len(raw.lstrip(" ")), body))
    return out


def _mapping(lines, i, indent):
    """The block mapping whose keys sit at `indent`, read from lines[i] on: ({key: text | mapping}, the next index).
    A key's value is its text on the line, or the mapping nested under it. A sequence, a block scalar or anything else
    nested under a key is read as its text on the line, or «…»: nothing here reads one."""
    out = {}
    while i < len(lines) and lines[i][0] == indent:
        text = lines[i][1]
        m = KEY.match(text)
        i += 1
        if not m:   # a sequence item at its key's own indent, or what no key holds: it and what nests under it
            while i < len(lines) and lines[i][0] > indent:
                i += 1
            continue
        key, val = m.group(1).strip("'\""), (m.group(2) or "").strip()
        if i < len(lines) and lines[i][0] > indent and not val and KEY.match(lines[i][1]):
            out[key], i = _mapping(lines, i, lines[i][0])
        else:
            out[key] = val or ("…" if i < len(lines) and lines[i][0] > indent else "")
        while i < len(lines) and lines[i][0] > indent:
            i += 1
    return out, i


def builds_of(compose, image):
    """[(service, build)] for every service of `compose` (a docker-compose.yml's text) whose image is `image`, whatever
    its tag. The build is as read: text, a mapping, or None where the service declares none."""
    doc, _ = _mapping(_lines(compose), 0, 0)
    services = doc.get("services")
    if not isinstance(services, dict):
        return []
    out = []
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        img = str(svc.get("image", "")).strip("'\"")
        if img == image or img.startswith(image + ":") or img.startswith(image + "@"):
            out.append((name, svc.get("build")))
    return out


def plain(build):
    """None when `build` is exactly `docker build <its directory>`; otherwise why not, in words"""
    if build is None or build == "":
        return "it is named with no build"
    if isinstance(build, str):
        b = build.strip("'\"")
        if not (b.startswith("{") and b.endswith("}")):
            return None if b in (".", "./") else "it builds from %s, not its own directory" % b
        flow = {}
        for part in b[1:-1].split(","):
            k, sep, v = part.partition(":")
            if not sep:
                return "a build it cannot read (%s)" % b
            flow[k.strip().strip("'\"")] = v.strip().strip("'\"")
        build = flow
    if not isinstance(build, dict):
        return "a build it cannot read"
    extra = sorted(set(build) - {"context", "dockerfile"})
    if extra:
        return "its build declares %s" % ", ".join(extra)
    ctx = str(build.get("context") or ".").strip("'\"")
    if ctx not in (".", "./"):
        return "it builds from %s, not its own directory" % ctx
    dockerfile = str(build.get("dockerfile") or "Dockerfile").strip("'\"")
    if dockerfile not in ("Dockerfile", "./Dockerfile"):
        return "it builds %s, not its Dockerfile" % dockerfile
    return None


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _commit(sha):
    return bool(sha) and _git("cat-file", "-e", sha + "^{commit}").returncode == 0


def _same(a, b, path):
    """True when `path` is the same in commits a and b; False when it differs, or either is not here"""
    return _git("diff", "--quiet", a, b, "--", path).returncode == 0


def _prev_images():
    try:
        prev = json.loads(os.environ.get("PREV") or "{}")
    except ValueError:
        return {}, ""
    if not isinstance(prev, dict):
        return {}, ""
    images = prev.get("images") if isinstance(prev.get("images"), dict) else {}
    return images, str(prev.get("green") or "")


def _say(text):
    print("push-images: " + text, file=sys.stderr)


def plan():
    head, prefix = os.environ["HEAD_SHA"], os.environ["PREFIX"]
    skip = set(os.environ.get("SKIP", "").split())
    prev, listed_for = _prev_images()
    # what changed is measured from the commit the last list was made for, not from the last green: a proof that named
    # no images (its store was down) moved refs/green alone, and what its batch changed was never built
    base = listed_for if _commit(listed_for) else os.environ.get("PREV_GREEN", "")
    if not _commit(base):
        _say("no last green version, and no list of images, to say what changed — nothing is built")
        return 0
    seen = set()
    for top in ("apps", "platform-base"):
        for name in sorted(os.listdir(top)) if os.path.isdir(top) else []:
            d = "%s/%s" % (top, name)
            if name in seen or name in skip or not (os.path.isfile(d + "/app.json") and os.path.isfile(d + "/Dockerfile")):
                continue
            seen.add(name)
            if name in HEAVY:
                _say("%s: too heavy for the store (%s) — each office builds it as today" % (name, HEAVY[name]))
                continue
            try:
                with open(d + "/docker-compose.yml", encoding="utf-8") as f:
                    users = builds_of(f.read(), "%s/%s" % (prefix, name))
            except OSError:
                users = []
            why = "its compose names no image %s/%s" % (prefix, name) if not users else \
                next((w for w in (plain(b) for _, b in users) if w), None)
            if why:
                _say("%s: %s — each office builds it as today" % (name, why))
                continue
            entry = prev.get(name)
            named = isinstance(entry, dict) and str(entry.get("digest") or "").startswith("sha256:")
            if named and _commit(str(entry.get("built_from") or "")) and _same(entry["built_from"], head, d):
                print("KEEP", name, d)
            elif named or not _same(base, head, d):
                print("BUILD", name, d)
            # else: never named, and unchanged — the offices' own build, as today: the store's first proof builds what
            # its batch changed, never every image at once on the Dell
    return 0


def to_json():
    head, prefix = os.environ["HEAD_SHA"], os.environ["PREFIX"]
    prev, _ = _prev_images()
    images, built = {}, []
    for pair in os.environ.get("KEEP", "").split():
        name, _, d = pair.partition("=")
        if isinstance(prev.get(name), dict):
            images[name] = dict(prev[name], dir=d)
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 3 or not parts[1].startswith("sha256:"):
            continue
        name, digest, d = parts
        images[name] = {"digest": digest, "name": "%s/%s" % (prefix, name), "built_from": head, "dir": d}
        built.append(name)
    print(json.dumps({"green": head, "built": sorted(built), "images": dict(sorted(images.items()))},
                     separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit({"plan": plan, "json": to_json}[sys.argv[1]]() if len(sys.argv) == 2 and sys.argv[1] in ("plan", "json")
             else (print(__doc__.split("\n\n")[1], file=sys.stderr) or 2))
