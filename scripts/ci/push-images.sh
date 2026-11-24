#!/usr/bin/env bash
# push-images — the line's ready-made images (DGO-2123; the design: research_notes/CICD 2026-11/images.md).
#
#   bash scripts/ci/push-images.sh            # in the proof's `images` job, on the Dell's runner
#
# WHAT. Every first-party image that an office would build exactly as `docker build <its directory>` (images-plan.py
# says which) and whose directory changed is built ONCE, on the runner, and pushed by digest to the office's image store
# (apps/image-store, its origin role). An image the last list named keeps its digest while its directory is still what
# that digest was built from. The answer is images.json, on stdout as ONE line:
#   {"green": <this commit>, "built": [<ids>], "images": {<id>: {"digest": "sha256:…", "name": <compose's image name>,
#    "built_from": <sha>, "dir": <its directory>}}}
# The proof's green job writes it beside refs/green, as refs/images/dgo-stable, and an office's take PULLS those digests
# through its own mirror instead of building (vps1 built batch 98 for ~8 minutes at load 26).
#
# WHICH IMAGES. images.yml's own set (DGO-41): an app directory with an app.json and a Dockerfile, minus the same skip
# list, each with images.yml's reason (scripts/test_push_images.py holds the two lists equal). Of those, only an image
# whose compose service builds from its own directory with its own Dockerfile and declares nothing else: no build args,
# no target, no second context. Anything more and each office builds it as today (scripts/ci/images-plan.py).
#
# HOW. The engine builds in a capped BuildKit builder of the job's own (BUILDER: the Dell froze under load on 11-01),
# never without one, and loads the image. The ENGINE then pushes it to 127.0.0.1:<port>, the store's port on the
# machine's loopback, which needs no TLS and no daemon setting. The digest is the engine's own RepoDigest of that push.
# Then the tag leaves the engine: the store holds the image, and the Dell's disk would otherwise keep one per proof.
# The store keeps what the last lists name (scripts/ci/prune-images.py, in the green job).
#
# NEVER THE PROOF'S VERDICT. Where no image store answers (STORE_URL), or no capped builder was named, it says so and
# prints nothing: an office then builds as it does today. A build or a push that fails is a ::warning:: naming the
# image, and no list names that image: each office builds it. The script always ends 0.
set -uo pipefail

STORE_URL="${STORE_URL:-http://image-store:5000}"                     # from the runner's network
PUSH_TO="${PUSH_TO:-127.0.0.1:${REGISTRY_HOST_PORT:-5055}}"            # where the ENGINE pushes: the host's loopback
PREV_GREEN_REF="${PREV_GREEN_REF:-refs/remotes/origin/green/dgo-stable}"
PREV_IMAGES_REF="${PREV_IMAGES_REF:-refs/remotes/origin/images/dgo-stable}"
NAME_PREFIX="ghcr.io/bina-solution/digital-office"
# images.yml's skip list, with its reasons there: images published content-addressed elsewhere (apitools, n8n), images
# that name nothing a registry has (indox, chat, autoheal), and one client group's own apps (assets, examplem-io, loans)
SKIP="apitools n8n indox chat autoheal follow-runner assets examplem-io loans"
# An image over this many bytes (as the engine counts them, uncompressed) never goes to the store: three lists of it would
# be the store. The first-party images on the Dell were 11.1 GiB on 2026-11-20, read through its office, and 7.9 of it
# was one image (android-emulator, which images-plan.py names so that it is never built here).
MAX_IMAGE_BYTES="${MAX_IMAGE_BYTES:-1073741824}"
BUILDER="${BUILDER:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}" || exit 0

say() { printf '%s\n' "$*" >&2; }

if ! curl -fsS --max-time 5 -o /dev/null "${STORE_URL}/v2/" 2>/dev/null; then
  say "push-images: no image store answers at ${STORE_URL} — nothing is pushed; an office builds as it does today"
  exit 0
fi
if [ -z "${BUILDER}" ]; then
  say "push-images: no capped builder was named (BUILDER) — nothing is built: never an uncapped build on the Dell"
  exit 0
fi

head="$(git rev-parse HEAD)" || { say "::warning::push-images: no commit to build from"; exit 0; }
prev_green="$(git rev-parse -q --verify "${PREV_GREEN_REF}" 2>/dev/null || true)"
prev_json="$(git show "${PREV_IMAGES_REF}:images.json" 2>/dev/null || true)"

plan="$(HEAD_SHA="${head}" PREV_GREEN="${prev_green}" PREV="${prev_json}" PREFIX="${NAME_PREFIX}" SKIP="${SKIP}" \
        python3 scripts/ci/images-plan.py plan)" \
  || { say "::warning::push-images: which images to build could not be read (above) — nothing is built"; exit 0; }
[ -n "${plan}" ] || { say "push-images: nothing to build and nothing to keep — this proof names no image"; exit 0; }

ACCEPT="application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json"
ACCEPT="${ACCEPT}, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json"
# kept_in_store <id> — the digest the last list named for it is still in the store. A list names only what the store
# holds: a digest gone from it (a prune that read a stale list, a store rebuilt) is built again, never carried into
# every later list (the second reader)
kept_in_store() {
  local d
  d="$(PREV="${prev_json}" ID="$1" python3 -c 'import json, os
e = ((json.loads(os.environ["PREV"] or "{}").get("images") or {}).get(os.environ["ID"]) or {})
print(e.get("digest") or "")' 2>/dev/null)"
  [ -n "${d}" ] && curl -fsS --max-time 10 -o /dev/null -I -H "Accept: ${ACCEPT}" "${STORE_URL}/v2/$1/manifests/${d}" 2>/dev/null
}

keep="" built_lines=""
while read -r verb id dir; do
  case "${verb}" in
    KEEP)
      if kept_in_store "${id}"; then keep="${keep} ${id}=${dir}"; continue; fi
      say "push-images: ${id}: the digest the last list named is not in the store — built again" ;;
    BUILD) ;;
    *) continue ;;
  esac
  tag="${PUSH_TO}/${id}:${head:0:12}"
  docker buildx build --builder "${BUILDER}" --load -t "${tag}" \
    --label "org.opencontainers.image.revision=${head}" "${dir}" </dev/null >&2 \
    || { say "::warning::push-images: ${id} did not build (above) — no list names it, and each office builds it"; continue; }
  size="$(docker image inspect --format '{{.Size}}' "${tag}" </dev/null 2>/dev/null || true)"
  if [ -n "${size}" ] && [ "${size}" -gt "${MAX_IMAGE_BYTES}" ] 2>/dev/null; then
    say "::warning::push-images: ${id} is $(( size / 1048576 )) MiB, over the store's $(( MAX_IMAGE_BYTES / 1048576 )) MiB an image — not pushed: each office builds it as today"
    docker image rm "${tag}" </dev/null >/dev/null 2>&1 || true
    continue
  fi
  if ! docker push "${tag}" </dev/null >&2; then
    say "::warning::push-images: ${id} was built and not pushed (above) — no list names it, and each office builds it"
    docker image rm "${tag}" </dev/null >/dev/null 2>&1 || true
    continue
  fi
  digest="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${tag}" </dev/null 2>/dev/null \
            | grep "^${PUSH_TO}/${id}@sha256:" | head -1 | cut -d@ -f2)"
  # the store holds it now: the engine keeps no tag of each proof (the Dell's disk, 92% on 2026-11-20)
  docker image rm "${tag}" </dev/null >/dev/null 2>&1 || true
  if [ -z "${digest}" ]; then
    say "::warning::push-images: ${id} was pushed and its digest not read — no list names it, and each office builds it"
    continue
  fi
  built_lines="${built_lines}${id} ${digest} ${dir}"$'\n'
  say "push-images: ${id} → ${digest}"
done <<< "${plan}"

# images.json: what this proof built, and what the last list named whose directory is still the one it was built from
printf '%s' "${built_lines}" | HEAD_SHA="${head}" PREV="${prev_json}" PREFIX="${NAME_PREFIX}" KEEP="${keep}" \
  python3 scripts/ci/images-plan.py json || say "::warning::push-images: images.json could not be written — this proof names no image"
exit 0
