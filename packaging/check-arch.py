#!/usr/bin/env python3
"""check-arch — which third-party images publish linux/arm64?

    python3 packaging/check-arch.py
    python3 packaging/check-arch.py --strict     # exit 1 if any image lacks arm64

WHY THIS MATTERS NOW AND NOT LATER

Every image in this stack is linux/amd64 today. On Apple Silicon that leaves two options, and
both are bad if discovered late:

  * Rosetta-for-Linux (VZLinuxRosettaDirectoryShare) is NOT preinstalled, and its installer
    downloads from Apple. That breaks the offline promise outright — the one thing the whole
    single-file design exists to deliver.
  * qemu-user-static binfmt in the guest works offline but runs roughly 10x slower. Across forty
    services that is not "slow", it is non-functional.

So arm64 is not a macOS nicety, it is the precondition for macOS existing as a target at all.
For our own 16 images it is a `docker buildx build --platform linux/amd64,linux/arm64` change —
cheap today, a rewrite once anything depends on the amd64 assumption. For the third-party set we
do not get a choice: an image with no arm64 manifest is a hard blocker that has to be replaced,
rebuilt from source, or emulated. Knowing WHICH ones, now, is what makes that plannable.

This reads the registries directly (anonymous pull scope) and needs no Docker daemon.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# The third-party images this stack pulls. First-party images are ours to rebuild, so they are
# not listed — `docker buildx` handles them and there is nothing to discover.
IMAGES = [
    "caddy:2-alpine",
    "ghcr.io/goauthentik/server:2024.12",
    "glitchtip/glitchtip:6.2.2",
    "greenmail/standalone:2.1.3",
    "kong/kong:3.9.1",
    "n8nio/runners:2.17.4",
    "postgres:16-alpine",
    "postgres:17",
    "postgrest/postgrest:v14.8",
    "redis:7-alpine",
    "redis/redisinsight:3.8.0",
    "supabase/postgres:15.8.1.085",
    "supabase/storage-api:v1.48.26",
    "supabase/studio:2026.04.08-sha-205cbe7",
    "traefik:v3.3",
    "ollama/ollama:0.32.5",
]

ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
TIMEOUT = 30


def parse(image):
    """-> (registry_host, repository, reference). Docker Hub shorthand expands to library/*."""
    ref = "latest"
    name = image
    if ":" in image.rsplit("/", 1)[-1]:
        name, ref = image.rsplit(":", 1)
    if "/" not in name:
        return "registry-1.docker.io", f"library/{name}", ref
    head = name.split("/", 1)[0]
    if "." in head or ":" in head:            # a real registry host, not a Hub namespace
        return head, name.split("/", 1)[1], ref
    return "registry-1.docker.io", name, ref


def token(registry, repo):
    """Anonymous pull token. Hub and GHCR both hand one out with no credentials."""
    if registry == "registry-1.docker.io":
        url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
    elif registry == "ghcr.io":
        url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    else:
        return None
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.load(r).get("token")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def platforms(image):
    """-> (sorted list of 'os/arch', error string or None)."""
    registry, repo, ref = parse(image)
    tok = token(registry, repo)
    req = urllib.request.Request(
        f"https://{registry}/v2/{repo}/manifests/{ref}",
        headers={"Accept": ACCEPT, **({"Authorization": f"Bearer {tok}"} if tok else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            doc = json.load(r)
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return [], str(e)[:40]

    if "manifest.list" in ctype or "image.index" in ctype:
        out = set()
        for m in doc.get("manifests", []):
            p = m.get("platform") or {}
            if p.get("os") in (None, "unknown") or p.get("architecture") == "unknown":
                continue          # attestation manifests, not runnable images
            out.add(f"{p.get('os')}/{p.get('architecture')}")
        return sorted(out), None
    # A single manifest carries no platform block; it is whatever the repo was built for. The
    # registry cannot tell us more, so report it honestly rather than guessing amd64.
    return ["single-manifest (arch not advertised)"], None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit 1 if any image lacks linux/arm64")
    args = ap.parse_args()

    missing, unknown = [], []
    width = max(len(i) for i in IMAGES)
    print(f"{'image'.ljust(width)}  arm64  platforms")
    print("-" * (width + 40))
    for image in IMAGES:
        plats, err = platforms(image)
        if err:
            unknown.append((image, err))
            print(f"{image.ljust(width)}  {'?':^5}  query failed: {err}")
            continue
        has = any(p == "linux/arm64" or p.startswith("linux/arm64") for p in plats)
        if not has:
            missing.append(image)
        shown = " ".join(p for p in plats if p.startswith("linux/") or "single" in p) or " ".join(plats)
        print(f"{image.ljust(width)}  {'yes' if has else 'NO':^5}  {shown}")

    print()
    ok = len(IMAGES) - len(missing) - len(unknown)
    print(f"{ok}/{len(IMAGES)} publish linux/arm64")
    if missing:
        print("\nBLOCKERS for an Apple Silicon target — each needs replacing, rebuilding from")
        print("source, or accepting ~10x qemu-user-static emulation:")
        for m in missing:
            print(f"  {m}")
    if unknown:
        print("\nCould not determine (network or auth):")
        for m, e in unknown:
            print(f"  {m}  ({e})")
    return 1 if (args.strict and (missing or unknown)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
