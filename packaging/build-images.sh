#!/usr/bin/env bash
# build-images.sh — build the first-party images for RELEASE, multi-arch.
#
#   packaging/build-images.sh                              # amd64 + arm64, into the local store
#   packaging/build-images.sh --platform linux/arm64        # one arch
#   packaging/build-images.sh --push registry.example/bina  # to a registry instead
#   packaging/build-images.sh --list                        # what would be built, build nothing
#
# WHY THIS IS SEPARATE FROM `bbox run`
# `bbox run` builds NATIVE-ONLY on purpose: a developer waiting twice as long for an arm64 image
# they will never execute is a tax on every single iteration. Multi-arch is a property of a
# RELEASE, so it lives on the release path. This script does not touch the compose build flow and
# nothing in bbox calls it.
#
# WHY MULTI-ARCH AT ALL
# All 16 third-party images the stack pulls already publish linux/arm64 (verified —
# packaging/check-arch.py). Our own images are therefore the ONLY thing standing between this
# platform and an Apple Silicon bundle. On Apple Silicon the alternatives are Rosetta-for-Linux,
# whose installer downloads from Apple and so breaks the offline promise, or qemu-user-static at
# roughly 10x slower, which across forty services is non-functional rather than merely slow.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
cd "${REPO_ROOT}"

PLATFORMS="linux/amd64,linux/arm64"
PUSH_TO=""
LIST_ONLY=0
BUILDER="bina-release"

while [ $# -gt 0 ]; do
  case "$1" in
    --platform) PLATFORMS="${2:?--platform needs a value}"; shift ;;
    --push)     PUSH_TO="${2:?--push needs a registry prefix}"; shift ;;
    --list)     LIST_ONLY=1 ;;
    -h|--help)  sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "build-images: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "build-images: $*" >&2; exit 1; }

# ── resolve what to build, from the compiled stack ────────────────────────────────────────────
# Same source of truth as the bundle: platform.state.yaml + every app.json, resolved by the
# compiler. A hand-written list here would be a second place to forget an app.
SPEC_PY="$(mktemp)"; trap 'rm -f "${SPEC_PY}"' EXIT
cat > "${SPEC_PY}" <<'PY'
import json, os, shlex, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
root = os.path.abspath(sys.argv[1])
specs = []
for name, svc in sorted((data.get("services") or {}).items()):
    b = svc.get("build")
    if not b:
        continue
    if isinstance(b, str):
        ctx, df, args = b, "Dockerfile", {}
    else:
        ctx = b.get("context", "."); df = b.get("dockerfile", "Dockerfile"); args = b.get("args") or {}
    if isinstance(args, list):
        args = {k: v for a in args for k, _, v in [a.partition("=")]}
    img = svc.get("image") or ("deployment-hacohen-" + name)
    # compose resolves context to an absolute host path; make it repo-relative so the command is
    # portable and readable, and so it works the same on a Linux runner as on a Windows dev box.
    try:
        ctx = os.path.relpath(os.path.abspath(ctx), root).replace(os.sep, "/")
    except ValueError:
        pass
    argflags = " ".join("--build-arg " + shlex.quote(f"{k}={v}") for k, v in sorted(args.items()))
    specs.append((name, img, ctx, df, argflags))

# Collapse specs that are byte-for-byte the same build. n8n, n8n-worker-1 and n8n-worker-2 share
# one context, one Dockerfile and one set of build args, differing ONLY by `command` — so they are
# three tags on one image, and building them separately is three invocations to produce it. Layer
# sharing means the disk cost was never 3x, but the release path should not pay the build cost
# three times either. Key on what actually determines image content.
by_build = {}
for name, img, ctx, df, argflags in specs:
    by_build.setdefault((ctx, df, argflags), []).append((name, img))

for (ctx, df, argflags), members in sorted(by_build.items()):
    names = ",".join(n for n, _ in members)
    tags  = ",".join(i for _, i in members)
    print("\t".join([names, tags, ctx, df, argflags]))
PY

SPECS="$(./scripts/dc config --format json 2>/dev/null | python3 "${SPEC_PY}" "${REPO_ROOT}" || true)"
[ -n "${SPECS}" ] || die "could not resolve build specs — is the stack compiled? (bbox reconcile)"

count="$(printf '%s\n' "${SPECS}" | grep -c . || true)"

if [ "${LIST_ONLY}" = 1 ]; then
  printf '%-24s %-34s %s\n' SERVICE IMAGE CONTEXT
  while IFS=$'\t' read -r s img ctx _df _args; do
    [ -n "${s}" ] || continue
    printf '%-24s %-34s %s\n' "${s}" "${img}" "${ctx}"
  done <<EOF
${SPECS}
EOF
  echo
  echo "${count} first-party image(s); would build for: ${PLATFORMS}"
  exit 0
fi

command -v docker >/dev/null 2>&1 || die "docker not found"
docker version >/dev/null 2>&1     || die "docker daemon not reachable"
docker buildx version >/dev/null 2>&1 || die "docker buildx not available — required for multi-arch"

# A multi-platform build needs a builder backed by the docker-container driver; the default
# "docker" driver can only ever produce the host's own architecture and fails with a confusing
# "multiple platforms feature is currently not supported" rather than saying so.
if ! docker buildx inspect "${BUILDER}" >/dev/null 2>&1; then
  echo "creating buildx builder '${BUILDER}' (docker-container driver)…"
  docker buildx create --name "${BUILDER}" --driver docker-container --bootstrap >/dev/null
fi

# Cross-building arm64 on an amd64 runner needs binfmt handlers registered. GitHub's ubuntu
# runners have them; a bare VPS usually does not, and the failure is an exec-format error deep
# inside a RUN step rather than anything that names the real cause.
if ! docker buildx inspect "${BUILDER}" | grep -qi 'linux/arm64'; then
  die "builder '${BUILDER}' cannot target linux/arm64 — register binfmt first:
    docker run --privileged --rm tonistiigi/binfmt --install all"
fi

echo "building ${count} first-party image(s) for ${PLATFORMS}…"
rc=0
while IFS=$'\t' read -r s img ctx df argflags; do
  [ -n "${s}" ] || continue
  # `img` may be a comma-separated list when one build produces several tags (the n8n triple).
  # Each needs its own -t; passing the joined string would create one absurdly-named image.
  tagflags=""
  for t in $(printf '%s' "${img}" | tr ',' ' '); do
    [ -z "${PUSH_TO}" ] || t="${PUSH_TO%/}/${t##*/}"
    tagflags="${tagflags} -t ${t}"
  done
  out="--load"
  if [ -n "${PUSH_TO}" ]; then
    out="--push"
  elif [ "${PLATFORMS}" != "${PLATFORMS#*,}" ]; then
    # `--load` cannot import a multi-platform result into the local docker image store: the store
    # holds one manifest per tag, not an index. Real releases push to a registry (or write an OCI
    # layout); building multi-arch locally is only ever a syntax check.
    out="--output=type=cacheonly"
    echo "  note: multi-platform without --push cannot be loaded locally → cacheonly (build check only)"
  fi
  # shellcheck disable=SC2086  # argflags and tagflags are intentionally word-split
  if docker buildx build --builder "${BUILDER}" --platform "${PLATFORMS}" \
        ${argflags} ${tagflags} -f "${ctx}/${df}" "${out}" "${ctx}"; then
    echo "  ok   ${s} ->${tagflags// -t /  }"
  else
    echo "  FAIL ${s}" >&2; rc=1
  fi
done <<EOF
${SPECS}
EOF

[ "${rc}" = 0 ] && echo "all ${count} image(s) built for ${PLATFORMS}" || echo "some builds failed" >&2
exit "${rc}"
