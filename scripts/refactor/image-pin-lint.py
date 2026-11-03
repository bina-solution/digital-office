#!/usr/bin/env python3
"""image-pin-lint — gate G15: every third-party image is pinned to an immutable reference.

    python3 scripts/refactor/image-pin-lint.py
    python3 scripts/refactor/image-pin-lint.py --digests   # also require @sha256:...

WHY THIS GATE EXISTS

The offline bundle (see packaging/README.md) is built by resolving every image the compiled
stack references and writing its layers into an OCI image layout. That artifact is then signed
and shipped to a customer who has NO registry access. Two properties have to hold, and neither
is free:

  1. The bundle must be REPRODUCIBLE. `glitchtip/glitchtip` with no tag means "whatever :latest
     resolved to on the machine that happened to build the bundle". Two builds a week apart
     produce different artifacts from identical source, and the signature attests to nothing you
     can name.

  2. The bundle must be COMPLETE. Anything not pinned at build time is something the customer's
     machine would have to fetch at run time — which is exactly the external dependency the whole
     single-file design exists to remove. A floating tag turns a working airgap install into a
     silent network call that fails on the customer's site, not on ours.

This gate does NOT apply to first-party images. Those are built from this repo by `bbox run`, so
their content is pinned by the commit, not by a tag. First-party is what SOME service builds: a
sidecar that runs its app's image names that image and carries no `build:` of its own (compose
stamps the building service's name on an image, so two services building one Dockerfile are two
image ids under one tag) — the name is still this repo's output, whichever service is asked.

TWO STRICTNESS LEVELS

Default (tag): reject images with no tag, and reject `:latest` / `:stable` / `:main` and friends.
This is enforceable today and is what CI runs.

--digests: additionally require `@sha256:`. A tag is mutable — upstream can and does re-push
`postgres:17` — so only a digest is truly immutable.

⚠️ DO NOT SWITCH THIS ON FOR THE SHIPPED COMPOSE FILES. Digest pinning and offline `docker load`
are in direct tension: `docker save`/`load` transfers only RepoTags, NOT RepoDigests (moby#43570 —
"the digested references are lost during transit"). A compose file that says
`image: postgres@sha256:…` on an airgapped machine will therefore find no local match and try to
contact a registry, which is the exact failure the bundle exists to prevent.

The correct split, and the reason this flag stays opt-in:

    pin digests in the BUILD          -> reproducible artifact
    emit TAGS into customer compose   -> resolvable offline after `docker load`
    record digests in the SIGNED MANIFEST -> the thing that actually attests what shipped

So `--digests` is a build-side audit, not a shipping requirement. It also still needs a renovation
workflow before it is usable at all: a human re-pinning 13 digests by hand on every security
update is worse than a tag.
"""
import argparse
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    print("image-pin-lint: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[2]

# Tags that are, by construction, a moving target.
FLOATING = {"latest", "stable", "main", "master", "edge", "dev", "nightly", "release"}

# Images built by THIS repo and referenced by a local tag rather than a build: context.
# They are the commit's output, so a tag is the right reference — there is no upstream to drift.
FIRST_PARTY_PREFIXES = ("deployment-hacohen-",)
FIRST_PARTY_SUFFIXES = ("-local:latest",)


def is_first_party(image: str) -> bool:
    return image.startswith(FIRST_PARTY_PREFIXES) or image.endswith(FIRST_PARTY_SUFFIXES)


def split_ref(image: str):
    """-> (name, tag or None, digest or None). Handles a registry host with a port."""
    digest = None
    if "@" in image:
        image, digest = image.split("@", 1)
    # a colon is only a tag separator if it is after the last slash (else it is a host:port)
    tag = None
    last_slash = image.rfind("/")
    colon = image.rfind(":")
    if colon > last_slash:
        image, tag = image[:colon], image[colon + 1:]
    return image, tag, digest


def third_party(docs):
    """`{image: [where…]}` for every image that NO service builds, from `{where: compose document}`.

    A service that BUILDS its image from this repo is first-party by definition: the name beside
    `build:` is where the result is stored (a local tag, or the GHCR name CI pushes the same build
    to — `ghcr.io/…/<app>:${IMAGE_TAG:-latest}` since images are built in CI), not an upstream
    that can drift. The name lists below were the whole rule, and they predate that naming: 18
    first-party images were reported as "floating", which kept this gate red for a reason it says
    it does not have. And the name stays first-party for a service that only NAMES it.
    """
    seen, built = [], set()
    for where, doc in docs.items():
        for svc in ((doc or {}).get("services") or {}).values():
            img = svc.get("image")
            if not img:
                continue
            # `image:` may carry ${VAR:-default}; lint the default, which is what ships.
            img = re.sub(r"\$\{[^}:]+:-([^}]*)\}", r"\1", img)
            if svc.get("build"):
                built.add(img)
            elif "${" not in img:    # fully dynamic — a human chose this, not a drifting upstream
                seen.append((img, where))
    found = {}
    for img, where in seen:
        if img not in built:
            found.setdefault(img, []).append(where)
    return found


def declared_images():
    """Every `image:` in every app compose file, compiled or not.

    The static path is the one CI depends on: it needs no Docker daemon, and it covers gallery
    apps that are disabled right now but will be enabled on a customer's machine — those ship in
    the bundle too, so an unpinned gallery image is exactly as fatal.
    """
    docs = {}
    for compose in sorted(REPO.glob("apps/*/docker-compose.yml")) + sorted(
        REPO.glob("platform-base/*/docker-compose.yml")
    ):
        try:
            docs[compose.relative_to(REPO).as_posix()] = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            print(f"image-pin-lint: {compose.relative_to(REPO)}: unparseable: {exc}", file=sys.stderr)
            return None
    return third_party(docs)


def problems_of(images, digests=False):
    """`[(image, where, why)]` — the references an offline bundle cannot be built from."""
    problems = []
    for image, where in sorted(images.items()):
        if is_first_party(image):
            continue
        name, tag, digest = split_ref(image)
        if tag is None and digest is None:
            problems.append((image, where, "no tag at all — resolves to :latest at build time"))
        elif tag in FLOATING and digest is None:
            problems.append((image, where, f"floating tag ':{tag}'"))
        elif digests and digest is None:
            problems.append((image, where, "no @sha256: digest"))
    return problems


def self_test() -> int:
    """The rule on documents written here: what it must catch, and what it must leave alone."""
    app = "ghcr.io/acme/office/app:${IMAGE_TAG:-latest}"
    svc = lambda image, build=False: {"image": image, **({"build": {"context": "."}} if build else {})}  # noqa: E731
    doc = lambda **services: {"services": services}                                                      # noqa: E731
    why = lambda docs: [w for _i, _where, w in problems_of(third_party(docs))]                           # noqa: E731
    cases = [
        ("an upstream image on a floating tag is caught",
         why({"a.yml": doc(db=svc("postgres:latest"))}) == ["floating tag ':latest'"]),
        ("an upstream image with no tag is caught",
         why({"a.yml": doc(db=svc("postgres"))}) == ["no tag at all — resolves to :latest at build time"]),
        ("a pinned upstream image passes",
         why({"a.yml": doc(db=svc("postgres:17.2"))}) == []),
        ("a service that builds its image is first-party, whatever the tag",
         why({"a.yml": doc(app=svc(app, build=True))}) == []),
        ("a sidecar that NAMES an image its app builds is first-party too",
         why({"a.yml": doc(app=svc(app, build=True), net=svc(app), door=svc(app))}) == []),
        ("…also when the builder is declared in another compose file",
         why({"a.yml": doc(app=svc(app, build=True)), "b.yml": doc(side=svc(app))}) == []),
        ("the same name with NO service building it is an upstream on a floating tag",
         why({"a.yml": doc(net=svc(app), door=svc(app))}) == ["floating tag ':latest'"]),
        ("a registry host with a port is not read as a tag",
         why({"a.yml": doc(x=svc("registry.local:5000/tool"))}) == ["no tag at all — resolves to :latest at build time"]),
    ]
    bad = [name for name, ok in cases if not ok]
    for name, ok in cases:
        print(("  ok    " if ok else "  FAIL  ") + name)
    print(f"image-pin-lint self-test: {len(cases) - len(bad)}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digests", action="store_true",
                    help="also require @sha256: (the level the bundle build needs)")
    ap.add_argument("--self-test", action="store_true", help="prove the rule on documents written here")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    images = declared_images()
    if images is None:
        return 2
    if not images:
        print("image-pin-lint: FAIL — read ZERO third-party image references, so nothing was checked")
        return 1

    problems = problems_of(images, args.digests)
    if problems:
        print("image-pin-lint: FAIL — an offline bundle cannot be built from these\n")
        for image, where, why in problems:
            print(f"  {image}")
            print(f"      {why}")
            for w in where:
                print(f"      declared in {w}")
        print("\nPin each to an immutable reference. See packaging/README.md for why the bundle")
        print("cannot tolerate a moving tag.")
        return 1

    level = "tag+digest" if args.digests else "tag"
    print(f"OK — {len(images)} image reference(s), every third-party one pinned ({level} level)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
