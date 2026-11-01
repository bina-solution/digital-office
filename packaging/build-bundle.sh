#!/usr/bin/env bash
# build-bundle.sh — produce (or just measure) the offline image bundle.
#
#   packaging/build-bundle.sh --measure-only     # print sizes, keep nothing
#   packaging/build-bundle.sh -o dist/images.tar.zst
#   packaging/build-bundle.sh --measure-only --images "redis:7-alpine caddy:2-alpine"
#
# WHAT THIS IS
# The customer-facing artifact has two halves: a per-OS installer that lands a container runtime,
# and this — every image the platform needs, in one file, so the customer's machine never contacts
# a registry. See packaging/README.md.
#
# WHY IT STREAMS
# The obvious implementation (`docker save -o big.tar` then compress) needs the RAW size on disk —
# ~9.5-10 GB — before compression removes two thirds of it. Doing exactly that on a Docker Desktop
# host is what filled this repo's own dev machine to 0 bytes free, wedged its WSL VM, and left a
# 66 GB VHDX that does not shrink on its own. So `docker save` is piped straight into zstd and the
# raw tar never touches disk. Peak requirement is the COMPRESSED output plus slack, not the raw.
#
# WHERE TO RUN IT
# The VPS, or any Linux host with real disk. Not Docker Desktop — see above.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
cd "${REPO_ROOT}"

OUT=""
MEASURE_ONLY=0
IMAGES_OVERRIDE=""
LEVEL=19
# zstd's decompressor defaults to a 128 MiB window. Compressing with windowLog > 27 makes
# decompression FAIL unless the extractor also passes --long=. Pinning 27 keeps `zstd -d` and
# `docker load` working with no special flags on the customer's side.
LONG=27

while [ $# -gt 0 ]; do
  case "$1" in
    --measure-only) MEASURE_ONLY=1 ;;
    --images)       IMAGES_OVERRIDE="${2:?--images needs a space-separated list}"; shift ;;
    -o|--output)    OUT="${2:?-o needs a path}"; shift ;;
    --level)        LEVEL="${2:?--level needs a number}"; shift ;;
    -h|--help)      sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "build-bundle: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

[ "${MEASURE_ONLY}" = 1 ] || [ -n "${OUT}" ] || OUT="dist/images.tar.zst"

die() { echo "build-bundle: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found"
command -v zstd   >/dev/null 2>&1 || die "zstd not found (apt-get install zstd)"
docker version >/dev/null 2>&1     || die "docker daemon not reachable"

# ── the image list ────────────────────────────────────────────────────────────────────────────
# Source of truth is the COMPILED stack, not a hand-written list: platform.state.yaml plus every
# app.json, resolved by the compiler. A hand-written list is a second place to forget an app.
if [ -n "${IMAGES_OVERRIDE}" ]; then
  # Escape hatch for smoke-testing the pipeline (and for building a bundle for a subset). The
  # DEFAULT must stay the compiled stack — a hand-passed list is exactly how an app goes missing
  # from a customer's bundle and is not noticed until their airgapped machine tries to fetch it.
  echo "using --images override (NOT the compiled stack)"
  # shellcheck disable=SC2086  # splitting the space-separated list into one line per image
  IMAGES="$(printf '%s\n' ${IMAGES_OVERRIDE})"
else
  echo "resolving images from the compiled stack…"
  # `compose config --images`, NOT a scan of `image:` fields in the YAML.
  #
  # This distinction is not cosmetic — getting it wrong produced a bundle that measured a
  # convincing 1.53 GB and would have installed a platform with no automation engine. 12 of this
  # stack's 16 first-party services declare only `build:` and no `image:`, so compose names them
  # `<project>-<service>` at build time and a YAML scan cannot see them. The omitted set was
  # n8n, apitools, chat, drive, inbox, mailview, machine, notifications,
  # any-concurrency, app-management and both n8n workers: 17 images found where 29 exist, and
  # every large first-party image among the missing.
  #
  # `config --images` is compose's own answer to "what images does this project use", so it
  # resolves built services to their effective tag exactly as `compose build` would.
  IMAGES="$(./scripts/dc config --images 2>/dev/null | sort -u)"
fi
[ -n "${IMAGES}" ] || die "no images resolved — is the stack compiled? (bbox reconcile)"

count="$(printf '%s\n' "${IMAGES}" | wc -l | tr -d ' ')"
echo "  ${count} distinct image(s)"

# COVERAGE GUARD. Every service the stack runs must map to an image in the bundle. The previous
# resolution bug was silent precisely because nothing checked this: it produced a plausible number
# and a plausible artifact, and the gap would only have surfaced on a customer's airgapped machine
# as "no such image" for the platform's core services. Compare service count against the images
# compose says those services use, and refuse rather than warn.
if [ -z "${IMAGES_OVERRIDE}" ]; then
  svc_count="$(./scripts/dc config --services 2>/dev/null | grep -c . || echo 0)"
  img_lines="$(./scripts/dc config --images 2>/dev/null | grep -c . || echo 0)"
  if [ "${svc_count}" -ne "${img_lines}" ]; then
    die "compose reports ${svc_count} service(s) but ${img_lines} image line(s) — the image list
       does not cover every service, and a bundle built from it would be incomplete."
  fi
  echo "  coverage: ${svc_count} service(s) all map to an image"
fi

# Every image must be present locally: this bundle IS the customer's registry, so anything missing
# here is something their machine would have to fetch — the exact dependency we are removing.
missing=""
while IFS= read -r img; do
  docker image inspect "${img}" >/dev/null 2>&1 || missing="${missing} ${img}"
done <<EOF
${IMAGES}
EOF
if [ -n "${missing}" ]; then
  echo "build-bundle: these images are not present locally:" >&2
  for m in ${missing}; do echo "    ${m}" >&2; done
  die "build or pull them first (./bbox run), then re-run"
fi

# ── size accounting, before writing anything ──────────────────────────────────────────────────
# `docker images` SIZE double-counts shared layers, so summing it overstates badly (~18.7 GB for a
# set that deduplicates to ~9.3 GB). Ask the daemon for the deduplicated figure instead.
raw_est="$(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || true)"
echo "  image store (deduplicated, all images): ${raw_est:-unknown}"

avail_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
avail_gb=$(( avail_kb / 1024 / 1024 ))
echo "  free space here: ${avail_gb} GiB"
# Streaming means we need room for the compressed artifact only. 6 GiB is ~2x the expected 2.4-3.2
# GB payload — enough headroom to not be the thing that fills the disk.
if [ "${MEASURE_ONLY}" = 0 ] && [ "${avail_gb}" -lt 6 ]; then
  die "need >= 6 GiB free to write a bundle safely; have ${avail_gb} GiB (--measure-only writes nothing)"
fi

# ── build or measure ──────────────────────────────────────────────────────────────────────────
# shellcheck disable=SC2086  # word splitting is the point: one arg per image
if [ "${MEASURE_ONLY}" = 1 ]; then
  echo "measuring (zstd -${LEVEL} --long=${LONG}, nothing kept)…"
  bytes="$(docker save ${IMAGES} | zstd -${LEVEL} -T0 --long=${LONG} -c | wc -c)"
  printf 'compressed payload: %s bytes (%.2f GB)\n' "${bytes}" "$(echo "${bytes}" | awk '{print $1/1000000000}')"
  exit 0
fi

mkdir -p "$(dirname "${OUT}")"
echo "writing ${OUT} (zstd -${LEVEL} --long=${LONG})…"
# -f: overwrite. A build must be repeatable, and without this a leftover artifact from a killed
# run blocks the next one with "already exists; stdin is an input - not proceeding" — which is
# exactly what a zero-byte file from an interrupted build did.
docker save ${IMAGES} | zstd -f -${LEVEL} -T0 --long=${LONG} -o "${OUT}"

# The manifest is what makes the artifact auditable: which images, at which references, and the
# hash of the file that claims to contain them. Milestone 4 signs THIS, not the tarball — signing a
# 3 GB blob means the customer reads 3 GB before learning anything is wrong, and can verify neither
# incrementally nor in parts.
#
# It records the DIGEST of each image, not just the tag, because the manifest is the only place a
# digest can survive: `docker save`/`load` transfers RepoTags but not RepoDigests (moby#43570), so
# a digest cannot be carried in the compose file the customer runs without breaking offline
# resolution. Pin digests in the build, ship tags, attest digests here.
{
  printf '# image\tdigest (Id — the config digest, stable across save/load)\n'
  while IFS= read -r img; do
    [ -n "${img}" ] || continue
    printf '%s\t%s\n' "${img}" "$(docker image inspect --format '{{.Id}}' "${img}" 2>/dev/null || echo 'unknown')"
  done <<EOF
${IMAGES}
EOF
} > "${OUT}.images.txt"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${OUT}" > "${OUT}.sha256"
else
  shasum -a 256 "${OUT}" > "${OUT}.sha256"
fi

size_b="$(wc -c < "${OUT}")"
printf 'done: %s (%.2f GB), %s images\n' "${OUT}" "$(echo "${size_b}" | awk '{print $1/1000000000}')" "${count}"
echo "load it on the target with:  zstd -d -c ${OUT##*/} | docker load"
