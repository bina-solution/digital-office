#!/usr/bin/env bash
# fetch-runtime.sh — land the macOS RUNTIME: Lima, pinned and checksum-verified, under ~/.bbox.
#
#   packaging/macos/fetch-runtime.sh            # fetch (no-op when already present and verified)
#   packaging/macos/fetch-runtime.sh --print    # print the limactl path and exit
#
# The macOS twin of packaging/linux/fetch-runtime.sh. The engine itself (dockerd) is Linux-only,
# so on macOS the redistributable piece is the VM layer that boots one: Lima (Apache-2.0), which
# drives Apple's Virtualization.framework. Docker Desktop and OrbStack are proprietary and their
# licences forbid redistribution — the same reason the Linux package ships static Docker and not
# Desktop. See packaging/macos.md.
#
# PINNED with sha256 from the release's SHA256SUMS. A version bump is a deliberate edit here, and
# a bad or truncated download fails at the digest, on this machine, not as "the VM will not boot".
#
# Lands OUTSIDE the repo (~/.bbox/macos) on purpose: the tarball is ~45 MB of binaries that must
# never be committed, the checkout may be deleted and re-cloned without re-downloading, and the
# VM's own state (disk image, sockets) lives next to it under LIMA_HOME — one place to `rm -rf`.
set -euo pipefail

LIMA_VERSION="${LIMA_VERSION:-2.2.0}"
LIMA_SHA256_ARM64="bbdef91774885a0d05f7b048c4eb89ae2bcf3a0c252ae7ca7934e63df76d93c3"
LIMA_SHA256_X86_64="__unpinned__"   # Intel Macs are not a target; set from SHA256SUMS if one appears

BBOX_MACOS_HOME="${BBOX_MACOS_HOME:-${HOME}/.bbox/macos}"
DEST="${BBOX_MACOS_HOME}/lima-${LIMA_VERSION}"
LIMACTL="${DEST}/bin/limactl"

die() { echo "fetch-runtime: $*" >&2; exit 1; }

case "${1:-}" in
  --print) printf '%s\n' "${LIMACTL}"; exit 0 ;;
  -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1" ;;
esac

[ "$(uname -s)" = Darwin ] || die "this is the macOS runtime; on Linux/WSL use bbox install debian|windows"
command -v curl >/dev/null || die "curl not found"

case "$(uname -m)" in
  arm64|aarch64) DL_ARCH=arm64;  WANT_SHA="${LIMA_SHA256_ARM64}" ;;
  x86_64)        DL_ARCH=x86_64; WANT_SHA="${LIMA_SHA256_X86_64}" ;;
  *) die "unsupported architecture: $(uname -m)" ;;
esac
[ "${WANT_SHA}" != "__unpinned__" ] || die "no pinned checksum for $(uname -m) — add it from https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/SHA256SUMS"

# Already landed and still what we pinned? Then this is a no-op — `bbox` calls this on every
# Darwin invocation, so it has to be cheap. `limactl --version` proves the binary runs (Gatekeeper
# quarantine, a wrong arch, or a half-extracted tree would all fail here rather than later).
if [ -x "${LIMACTL}" ] && "${LIMACTL}" --version 2>/dev/null | grep -q "${LIMA_VERSION}"; then
  exit 0
fi

TGZ="${BBOX_MACOS_HOME}/lima-${LIMA_VERSION}-Darwin-${DL_ARCH}.tar.gz"
URL="https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/lima-${LIMA_VERSION}-Darwin-${DL_ARCH}.tar.gz"
mkdir -p "${BBOX_MACOS_HOME}"

if [ -s "${TGZ}" ] && [ "$(shasum -a 256 "${TGZ}" | cut -d' ' -f1)" = "${WANT_SHA}" ]; then
  echo "already have $(basename "${TGZ}") (verified)"
else
  echo "fetching ${URL}"
  curl -fL --retry 3 --progress-bar -o "${TGZ}.part" "${URL}" || die "download failed"
  mv "${TGZ}.part" "${TGZ}"
  got="$(shasum -a 256 "${TGZ}" | cut -d' ' -f1)"
  [ "${got}" = "${WANT_SHA}" ] || { rm -f "${TGZ}"; die "sha256 mismatch for $(basename "${TGZ}"): got ${got}, pinned ${WANT_SHA}"; }
  echo "  verified sha256 ${got}"
fi

rm -rf "${DEST}.part"; mkdir -p "${DEST}.part"
tar -xzf "${TGZ}" -C "${DEST}.part"
[ -x "${DEST}.part/bin/limactl" ] || die "limactl missing from the tarball"
# Downloaded via curl, not a browser, so there is normally no quarantine attribute — but clear it
# if one exists, or macOS will refuse to run the binaries and the first `bbox run` dies opaquely.
xattr -dr com.apple.quarantine "${DEST}.part" 2>/dev/null || true
rm -rf "${DEST}"; mv "${DEST}.part" "${DEST}"

"${LIMACTL}" --version >/dev/null || die "limactl does not run after extraction"
echo "runtime landed: ${DEST} ($("${LIMACTL}" --version))"
