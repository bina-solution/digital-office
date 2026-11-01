#!/usr/bin/env bash
# build-run.sh — assemble BinaOS-<ver>-linux-<arch>.run from a header + three appended segments.
#
#   packaging/linux/build-run.sh --version 2026.08.0 --images dist/images.tar.zst
#
# Produces, in dist/:
#   BinaOS-<ver>-linux-<arch>.run          the single self-extracting file
#   manifest.json                          what a signature covers
#   manifest.sigstore.json                 if a cosign key is available
#
# THE ORDERING RULE, and it is not negotiable:
#     build fully  ->  compute offsets  ->  concatenate  ->  sign  ->  never touch the bytes again
# Appending anything to a signed file voids the signature (verified empirically on Windows: copying
# a signed notepad.exe and appending 1 MB flips Get-AuthenticodeSignature from Valid to NotSigned).
# The same is true in spirit here: the manifest records offsets and hashes of the FINAL file, so
# the file cannot change afterwards.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${REPO_ROOT}"

VERSION=""
IMAGES_BUNDLE="dist/images.tar.zst"
ARCH="$(uname -m)"; case "${ARCH}" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; esac
OUTDIR="dist"
COSIGN_KEY="${COSIGN_KEY:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:?}"; shift ;;
    --images)  IMAGES_BUNDLE="${2:?}"; shift ;;
    --arch)    ARCH="${2:?}"; shift ;;
    --out)     OUTDIR="${2:?}"; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "build-run: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "build-run: $*" >&2; exit 1; }
[ -n "${VERSION}" ] || die "--version is required"
[ -f "${IMAGES_BUNDLE}" ] || die "image bundle not found: ${IMAGES_BUNDLE} (run packaging/build-bundle.sh)"
command -v zstd >/dev/null || die "zstd not found"

mkdir -p "${OUTDIR}"
WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT

# ── SEG control ───────────────────────────────────────────────────────────────────────────────
# Everything the installer needs to verify itself and to lay down the platform. Small; extracted.
say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
say "staging control segment"
# Do NOT re-render here. A release build must ship the configuration that was reviewed and tested,
# not whatever a fresh compile produces at package time — and rendering has side effects (it
# archives a generation). Fail loudly if the caller has not compiled.
[ -f .generated/compose.yml ] || die "no .generated/compose.yml — run 'bbox reconcile' first"
# stage-control.py copies the minimum runtime tree: compiled compose, every app.json +
# docker-compose.yml + hooks, the compiler, and every relative bind-mount source DISCOVERED from
# the compose files. Not source. The naive `tar -c apps platform-base` this replaced was 125 MB,
# 1033 entries of which were apitools' source — already inside the images the bundle carries.
# The shipped compose must RUN images, never build them. Generated here so it always matches the
# configuration being packaged rather than whatever was last rendered by hand.
say "generating the build-free runtime compose"
python3 packaging/make-runtime-compose.py --out .generated/compose.runtime.yml \
  || die "could not generate compose.runtime.yml"

python3 packaging/stage-control.py --dest "${WORK}/control/platform" || die "control staging failed"
# NOT `|| true`. This was copied best-effort and the file did not exist, so the installer shipped
# with no systemd unit: the install reported success and `systemctl start binaos` then answered
# "Unit binaos.service could not be found". A missing unit is a broken product, not a warning.
[ -f "${HERE}/binaos.service" ] || die "packaging/linux/binaos.service is missing — the installer would ship with no unit"
cp "${HERE}/binaos.service" "${WORK}/control/"
# The header runs this at install time to fit the compose to the customer's machine (CPU sizing, and
# pointing docker-socket mounts at our private engine). Shipping it is not optional — `die` here,
# because the same `cp ... || true` habit is exactly how binaos.service came to be missing.
[ -f "${HERE}/adapt-host.py" ] || die "packaging/linux/adapt-host.py is missing — the installer calls it"
cp "${HERE}/adapt-host.py" "${WORK}/control/"
[ -f "${WORK}/control/platform/.generated/compose.runtime.yml" ] \
  || die "compose.runtime.yml did not reach the control segment — the install would try to BUILD"
[ -f .env.ex ] && cp .env.ex "${WORK}/control/binaos.env.example"
[ -n "${COSIGN_KEY}" ] && [ -f "${COSIGN_KEY%.key}.pub" ] && cp "${COSIGN_KEY%.key}.pub" "${WORK}/control/cosign.pub"

# ── SEG runtime ───────────────────────────────────────────────────────────────────────────────
# The offline docker repo. Built by packaging/linux/fetch-runtime.sh on a machine with network;
# an empty placeholder is tolerated so the installer can still be assembled and tested against a
# host that already has Docker.
say "staging runtime segment"
mkdir -p "${WORK}/runtime"
if [ -d "${OUTDIR}/runtime-repo" ]; then
  cp -r "${OUTDIR}/runtime-repo/." "${WORK}/runtime/"
else
  printf '#!/usr/bin/env bash\necho "no bundled runtime in this build — install docker first" >&2\nexit 1\n' \
    > "${WORK}/runtime/install-runtime.sh"
  echo "  note: no dist/runtime-repo — this build REQUIRES Docker already present on the target"
fi

# Both small segments are zstd'd; the image bundle already is.
( cd "${WORK}/control" && tar -c . ) | zstd -19 -T0 -q -o "${WORK}/control.tar.zst"
( cd "${WORK}/runtime" && tar -c . ) | zstd -19 -T0 -q -o "${WORK}/runtime.tar.zst"

# ── offsets ───────────────────────────────────────────────────────────────────────────────────
# Substituting the offsets changes the header's own length, which changes the offsets. Resolve it
# by padding the header to a fixed size rather than iterating: write the placeholders at a known
# width, then pad with a comment block to a round number.
say "computing offsets"
HEADER_TMPL="${HERE}/header.sh"
CTRL_LEN=$(wc -c < "${WORK}/control.tar.zst")
RT_LEN=$(wc -c < "${WORK}/runtime.tar.zst")
IMG_LEN=$(wc -c < "${IMAGES_BUNDLE}")

HEADER_LEN=65536   # fixed; the header is padded to exactly this
CTRL_OFF=${HEADER_LEN}
RT_OFF=$(( CTRL_OFF + CTRL_LEN ))
IMG_OFF=$(( RT_OFF + RT_LEN ))

sed -e "s|@@HEADER_LEN@@|${HEADER_LEN}|" \
    -e "s|@@SEG_CONTROL_OFF@@|${CTRL_OFF}|" -e "s|@@SEG_CONTROL_LEN@@|${CTRL_LEN}|" \
    -e "s|@@SEG_RUNTIME_OFF@@|${RT_OFF}|"   -e "s|@@SEG_RUNTIME_LEN@@|${RT_LEN}|" \
    -e "s|@@SEG_IMAGES_OFF@@|${IMG_OFF}|"   -e "s|@@SEG_IMAGES_LEN@@|${IMG_LEN}|" \
    -e "s|@@VERSION@@|${VERSION}|" \
    "${HEADER_TMPL}" > "${WORK}/header.sh"

# `exit 0` in the header means everything past it is never executed, so padding is inert.
hdr_now=$(wc -c < "${WORK}/header.sh")
[ "${hdr_now}" -le "${HEADER_LEN}" ] \
  || die "header is ${hdr_now} bytes, exceeds the fixed ${HEADER_LEN}-byte slot — raise HEADER_LEN"
pad=$(( HEADER_LEN - hdr_now ))
{ cat "${WORK}/header.sh"; head -c "${pad}" < /dev/zero | tr '\0' '#'; } > "${WORK}/header.padded"
[ "$(wc -c < "${WORK}/header.padded")" = "${HEADER_LEN}" ] || die "padding miscomputed"

# ── assemble ──────────────────────────────────────────────────────────────────────────────────
OUT="${OUTDIR}/BinaOS-${VERSION}-linux-${ARCH}.run"
say "assembling ${OUT}"
cat "${WORK}/header.padded" "${WORK}/control.tar.zst" "${WORK}/runtime.tar.zst" "${IMAGES_BUNDLE}" > "${OUT}"
chmod +x "${OUT}"

# ── manifest, then signature. In that order, and nothing touches the file after. ──────────────
say "writing manifest"
python3 packaging/make-manifest.py \
  --version "${VERSION}" \
  --artifact "${OUT}" \
  --segment "control:${CTRL_OFF}:${CTRL_LEN}" \
  --segment "runtime:${RT_OFF}:${RT_LEN}" \
  --segment "images:${IMG_OFF}:${IMG_LEN}" \
  ${IMAGES_BUNDLE:+--images "${IMAGES_BUNDLE}.images.txt"} \
  --out "${OUTDIR}/manifest.json"

if [ -n "${COSIGN_KEY}" ] && command -v cosign >/dev/null 2>&1; then
  say "signing manifest"
  # All three flags are load-bearing: --use-signing-config=false is the one people miss, and
  # without it cosign fetches service URLs from the TUF CDN even with a local key.
  cosign sign-blob --key "${COSIGN_KEY}" --bundle "${OUTDIR}/manifest.sigstore.json" \
    --tlog-upload=false --use-signing-config=false --yes "${OUTDIR}/manifest.json" >/dev/null
  echo "  signed -> ${OUTDIR}/manifest.sigstore.json"
else
  # Delete any signature left over from a previous build. dist/ is reused across versions, so an
  # unsigned build would otherwise sit next to the PREVIOUS version's manifest.sigstore.json, and
  # verify-artifact.sh reports that as "cosign REJECTED the manifest — do not install this
  # artifact". The artifact is fine; the signature just describes a different one. A stale
  # signature is worse than no signature: it turns "unsigned" into what looks like tampering, and
  # the day the versions happen to line up it would turn tampering into "verified".
  if [ -f "${OUTDIR}/manifest.sigstore.json" ]; then
    rm -f "${OUTDIR}/manifest.sigstore.json"
    echo "  removed a stale signature from a previous build"
  fi
  echo "  note: UNSIGNED (set COSIGN_KEY and install cosign to sign)"
fi

printf '\ndone: %s (%.2f GB)\n' "${OUT}" "$(wc -c < "${OUT}" | awk '{print $1/1e9}')"
echo "verify on the target with:  ./$(basename "${OUT}") --check"
