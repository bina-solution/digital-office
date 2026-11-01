#!/usr/bin/env bash
# build-release.sh — produce the Linux artifact end to end, detached-safe.
#
#   nohup bash packaging/build-release.sh 2026.07.28 > /tmp/binaos-release.log 2>&1 &
#
# WHY THIS EXISTS AS A SCRIPT RATHER THAN A COMMAND LINE
# The bundle step is ~45 minutes of `docker save | zstd -19`. Driving that from the Windows side as
# `wsl.exe -- bash -lc '...'` loses it the moment the wsl.exe connection drops: the first attempt
# reported exit 0 and left a ZERO-BYTE images.tar.zst, because the pipeline died mid-write and the
# exit status came from the dead connection rather than from zstd. Running it detached inside the
# distro, with the log as the source of truth, removes that whole class of false success.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
VERSION="${1:-0.0.0-dev}"
# zstd level. -19 is the release setting and measured 2.20 GB in 44m36s. A long compression window
# is a liability on a host that can restart under you: the first real build was killed 26 minutes
# in when the WSL VM restarted, losing everything. -12 trades a few percent of ratio for roughly an
# order of magnitude less wall time, which is the right trade for producing a first real artifact.
LEVEL="${2:-19}"
OUT=dist

echo "=== $(date -u +%FT%TZ) build-release ${VERSION} (zstd -${LEVEL}) ==="
mkdir -p "${OUT}"

# QUIESCE. The bundle needs the IMAGES, not the running stack — `docker save` reads the image
# store and does not care whether anything is up. Building against a live 37-container stack cost
# three attempts here: the VM held 8.3 GB, the host fell to 0.8 GB of 15.7 GB free, and `wsl.exe`
# itself began returning Wsl/Service/0x8007274c, which is this repo's own documented symptom of
# host memory exhaustion rather than any fault in the build.
#
# Opt-in, because on the VPS this script may run beside a production stack that must stay up.
if [ "${BINAOS_QUIESCE:-0}" = "1" ]; then
  running="$(docker ps -q | wc -l)"
  if [ "${running}" -gt 0 ]; then
    echo "quiescing ${running} container(s) for the build (BINAOS_QUIESCE=1)"
    docker stop $(docker ps -q) >/dev/null 2>&1 || true
  fi
fi

echo "--- 1/2 image bundle ---"
if ! bash packaging/build-bundle.sh --level "${LEVEL}" -o "${OUT}/images.tar.zst"; then
  echo "FAILED: build-bundle"; exit 1
fi

# Do not trust an exit code alone here — that is exactly what lied last time. Verify the artifact.
if ! zstd -t "${OUT}/images.tar.zst" 2>/dev/null; then
  echo "FAILED: images.tar.zst does not decompress cleanly (truncated write?)"; exit 1
fi
echo "bundle verified: $(wc -c < "${OUT}/images.tar.zst") bytes"

echo "--- 2/2 assemble .run ---"
if ! bash packaging/linux/build-run.sh --version "${VERSION}" --images "${OUT}/images.tar.zst" --out "${OUT}"; then
  echo "FAILED: build-run"; exit 1
fi

echo "--- artifacts ---"
ls -lh "${OUT}"
echo "=== $(date -u +%FT%TZ) DONE ==="
