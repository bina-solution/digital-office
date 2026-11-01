#!/usr/bin/env bash
# apitools-tag.sh — the content-addressed GHCR tag for the apitools image.
#
#   AP="$(bash scripts/ci/apitools-tag.sh)"
#
# ONE implementation. `indox-e2e.yml` and `local-hebrew-doc-ex.yml` both prebake apitools by this
# exact tag (tree-hash the app dir, use it as the tag, skip the build if GHCR already has it) and
# had grown byte-for-byte copies of the six lines that compute it — the same duplication shape
# `scripts/ci/cap-cpus.py` and `scripts/ci/derive-services.sh` already existed to close for other
# steps, just not reached here yet.
#
# apitools is a layer-3 app: apps/apitools (it was production/apitools pre-refactor). A stale path
# here once made `git ls-tree` return nothing, so the tag was EMPTY and buildx died on
# `apitools:` — "invalid reference format". Fail loudly instead: a caller with an empty tag is
# exactly the failure this script exists to prevent silently.
set -euo pipefail
AP="$(git ls-tree HEAD apps/apitools | awk '{print substr($3,1,12)}')"
[ -n "${AP}" ] || { echo "::error::apitools tree hash empty — apps/apitools missing?" >&2; exit 1; }
printf '%s\n' "${AP}"
