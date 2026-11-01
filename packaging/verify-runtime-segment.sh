#!/usr/bin/env bash
# verify-runtime-segment.sh — the engine inside the .run is a WORKING engine, not just 78 MB.
#
#   packaging/verify-runtime-segment.sh dist/BinaOS-<ver>-linux-amd64.run
#
# `verify-artifact.sh` proves the runtime segment is present and hashes correctly. That is not the
# same as proving it runs: a wrong-arch or truncated-but-valid-gzip payload would pass every hash
# check and then fail on the customer's machine as "cannot execute binary file".
#
# So: read the segment out of the artifact exactly as the installer does, unpack it, and execute
# the binaries. `dockerd --version` runs the real ELF — it is the cheapest proof that the thing we
# shipped is executable on this architecture.
set -uo pipefail

RUN="${1:?usage: verify-runtime-segment.sh <artifact.run>}"
DIR="$(cd "$(dirname "${RUN}")" && pwd)"
MAN="${DIR}/manifest.json"
[ -f "${MAN}" ] || { echo "no manifest beside the artifact"; exit 1; }

pass=0; fail=0
ok()  { printf '  \033[32mok\033[0m   %s\n' "$*"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }

read -r off len < <(python3 -c '
import json,sys
for s in json.load(open(sys.argv[1]))["segments"]:
    if s["id"] == "runtime": print(s["offset"], s["len"])' "${MAN}")

echo "== runtime segment: ${len} bytes @ ${off} =="
[ "${len}" -gt 50000000 ] && ok "segment is a real payload, not a placeholder" \
                          || bad "segment is only ${len} bytes — still a placeholder?"

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
# Byte-for-byte the header's own read.
dd if="${RUN}" bs=1M iflag=skip_bytes,count_bytes skip="${off}" count="${len}" status=none \
  | zstd -dc 2>/dev/null | tar -x -C "${WORK}" 2>/dev/null \
  && ok "segment extracts" || bad "segment did not extract"

[ -f "${WORK}/install-runtime.sh" ] && ok "install-runtime.sh present" || bad "install-runtime.sh missing"
[ -f "${WORK}/RUNTIME.json" ] && ok "RUNTIME.json present" || bad "RUNTIME.json missing"

tgz="$(ls "${WORK}"/docker-*.tgz 2>/dev/null | head -1)"
if [ -n "${tgz}" ]; then
  ok "engine tarball present ($(basename "${tgz}"))"
  # The sha256 the build recorded must match what actually shipped.
  want="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "${WORK}/RUNTIME.json")"
  got="$(sha256sum "${tgz}" | cut -d' ' -f1)"
  [ "${want}" = "${got}" ] && ok "engine sha256 matches RUNTIME.json" || bad "engine sha256 MISMATCH"

  tar -xzf "${tgz}" -C "${WORK}"
  echo "== the binaries actually execute =="
  for b in dockerd containerd runc docker; do
    if v=$("${WORK}/docker/${b}" --version 2>&1 | head -1); then
      ok "${b}: ${v}"
    else
      bad "${b} did not execute (wrong arch or truncated)"
    fi
  done
  # The version we ship must be the one we promised: Docker 29 breaks traefik v3.3 silently.
  dv=$("${WORK}/docker/dockerd" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  case "${dv}" in
    28.*) ok "engine is Docker 28.x (29 would break traefik routing silently)" ;;
    *)    bad "engine is ${dv} — must be 28.x" ;;
  esac
else
  bad "no engine tarball in the runtime segment"
fi

echo
echo "passed ${pass}, failed ${fail}"
[ "${fail}" = 0 ]
