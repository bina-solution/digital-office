#!/usr/bin/env python3
"""make-manifest — build the signed manifest that describes a release artifact.

    python3 packaging/make-manifest.py --version 2026.08.0 \
        --artifact dist/BinaOS-2026.08.0-linux-amd64.run \
        --segment control:40960:2097152 \
        --segment runtime:2138112:94371840 \
        --segment images:96509952:3091144369 \
        --images dist/images.tar.zst.images.txt \
        --out dist/manifest.json

WHY A MANIFEST AND NOT A SIGNATURE OVER THE ARTIFACT

Signing the 3 GB artifact directly means the customer must read all 3 GB before learning anything
is wrong, cannot verify incrementally while downloading, and cannot verify a single part. Signing a
~20 KB manifest that transitively covers the artifact costs one indirection and buys all three.
This is Zarf's model: every file -> checksums -> aggregate hash in the metadata -> one signature
over the metadata.

WHY THE IMAGE DIGESTS LIVE HERE

`docker save`/`load` transfers RepoTags but NOT RepoDigests (moby#43570), so a digest cannot be
carried in the compose file the customer runs — an `image: foo@sha256:...` reference finds no local
match after `docker load` and reaches for a registry, which is the exact failure an offline bundle
exists to prevent. Pin digests in the build, ship tags, and attest the digests HERE. This file is
the only place a digest survives the trip.

Sign with:
    cosign sign-blob --key cosign.key --bundle manifest.sigstore.json \
        --tlog-upload=false --use-signing-config=false --yes manifest.json
Verify offline with:
    cosign verify-blob --key cosign.pub --bundle manifest.sigstore.json \
        --insecure-ignore-tlog=true manifest.json

All three of those flags are load-bearing — see packaging/linux.md.
"""
import argparse
import hashlib
import json
import pathlib
import sys

FORMAT = "bina.installer/v1"
PART_SIZE = 256 * 1024 * 1024   # 256 MiB — see packaging/linux.md on Cloudflare's 512 MB cache cap
CHUNK = 8 * 1024 * 1024


def sha256_file(path, offset=0, length=None):
    """Hash a byte range without reading the whole file into memory."""
    h = hashlib.sha256()
    remaining = length
    with open(path, "rb") as fh:
        fh.seek(offset)
        while remaining is None or remaining > 0:
            want = CHUNK if remaining is None else min(CHUNK, remaining)
            block = fh.read(want)
            if not block:
                break
            h.update(block)
            if remaining is not None:
                remaining -= len(block)
    return h.hexdigest()


def parse_segment(spec):
    """`name:offset:length` -> dict. Offsets are absolute within the artifact."""
    try:
        name, offset, length = spec.split(":")
        return {"id": name, "offset": int(offset), "len": int(length)}
    except ValueError:
        raise argparse.ArgumentTypeError(f"segment must be name:offset:length, got {spec!r}")


def read_images(path):
    """Read build-bundle.sh's `<tag>\\t<digest>` output. Comment lines start with #."""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ref, _, digest = line.partition("\t")
        out.append({"ref": ref.strip(), "digest": digest.strip() or "unknown"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--artifact", required=True, type=pathlib.Path)
    ap.add_argument("--segment", action="append", default=[], type=parse_segment)
    ap.add_argument("--images", type=pathlib.Path,
                    help="the .images.txt written by build-bundle.sh (tag<TAB>digest)")
    ap.add_argument("--built-at", default="", help="ISO-8601; the caller stamps it (scripts cannot)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()

    if not args.artifact.is_file():
        print(f"make-manifest: no such artifact: {args.artifact}", file=sys.stderr)
        return 1

    size = args.artifact.stat().st_size

    # Segments must tile the artifact without gaps or overlap past the header. A wrong offset here
    # produces an installer that reads the wrong bytes into `docker load` and fails with something
    # unrelated-looking, so it is worth catching at build time.
    segs = sorted(args.segment, key=lambda s: s["offset"])
    for a, b in zip(segs, segs[1:]):
        if a["offset"] + a["len"] > b["offset"]:
            print(f"make-manifest: segments overlap: {a['id']} and {b['id']}", file=sys.stderr)
            return 1
    if segs and segs[-1]["offset"] + segs[-1]["len"] > size:
        print(f"make-manifest: segment {segs[-1]['id']} runs past end of artifact", file=sys.stderr)
        return 1

    for s in segs:
        s["sha256"] = sha256_file(args.artifact, s["offset"], s["len"])

    parts = []
    for n, off in enumerate(range(0, size, PART_SIZE)):
        length = min(PART_SIZE, size - off)
        parts.append({"n": n, "offset": off, "len": length,
                      "sha256": sha256_file(args.artifact, off, length)})

    manifest = {
        "format": FORMAT,
        "version": args.version,
        "built_at": args.built_at,
        "artifact": {
            "name": args.artifact.name,
            "size": size,
            "sha256": sha256_file(args.artifact),
        },
        "segments": segs,
        "parts": parts,
        "images": read_images(args.images) if args.images else [],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False: the field order above is the reading order for a human auditing a release.
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"{args.out}: {size/1e9:.2f} GB artifact, {len(segs)} segment(s), "
          f"{len(parts)} part(s), {len(manifest['images'])} image(s)")
    print(f"  sha256 {manifest['artifact']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
