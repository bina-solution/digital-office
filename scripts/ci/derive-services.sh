#!/usr/bin/env bash
# derive-services.sh — ask the capability graph which services a lane needs, and export it.
#
#   LANE_ROOTS=indox,traefik LANE_EXCLUDE=studio,meta scripts/ci/derive-services.sh
#
# Reads LANE_ROOTS (optional; empty = every app enabled in platform.state.yaml) and LANE_EXCLUDE
# (optional deliberate trim). Writes SERVICES to $GITHUB_ENV when running under Actions, and always
# prints it.
#
# ONE implementation. Three workflows had their own copy of this five-line block. Before that they
# each had a HAND-WRITTEN service list, which is the bug this replaced: indox's manifest has always
# `use`d the drive capability, but indox-e2e's hand-written list never gained `drive`, so the lane
# started without it and every suite died on its first drive call — silently, because a missing
# service is not an error, just an absence. The lesson only has to be learned once if there is only
# one copy.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(cd "${SCRIPT_DIR}/../.." && pwd)"

args=()
[ -n "${LANE_ROOTS:-}" ]   && args+=(--for "${LANE_ROOTS}")
[ -n "${LANE_EXCLUDE:-}" ] && args+=(--exclude "${LANE_EXCLUDE}")

SERVICES="$(python3 platform/manager/reconcile.py services "${args[@]}")"
[ -n "${SERVICES}" ] || { echo "::error::derived SERVICES is empty (roots=${LANE_ROOTS:-<all enabled>})"; exit 1; }

[ -n "${GITHUB_ENV:-}" ] && echo "SERVICES=${SERVICES}" >> "${GITHUB_ENV}"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "derived SERVICES: ${SERVICES}" >> "${GITHUB_STEP_SUMMARY}"
echo "derived SERVICES: ${SERVICES}"
