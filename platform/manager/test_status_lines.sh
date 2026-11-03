#!/usr/bin/env bash
# test_status_lines.sh — the two drift lines `bbox status` owes the person reading it.
#
#     bash platform/manager/test_status_lines.sh
#
# eng-013's instances 1 and 3 are two DIFFERENT questions about the same office, and each has a line:
#   * a running container that is not what the files say now (compose's own answer, `stale_containers`)
#     — a bring-up re-creates it;
#   * a running IMAGE older than the files it was built from (`stale_images`) — a bring-up re-creates
#     the container and runs the OLD code, so nothing else shows it. Measured 2026-10-11: nine services
#     behind their own sources, one by four days.
# The lines are what makes either answer reachable without an agent re-deriving it; this holds them
# wired (the helper, the call, and the sentence that says what to DO about it).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "${HERE}/../.." && pwd)"
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
LIB="$(cat "${ROOT}/scripts/lib.sh" 2>/dev/null || true)"
BBOX="$(cat "${ROOT}/bbox" 2>/dev/null || true)"
grep -q '^stale_containers()' <<<"${LIB}" && ok "lib.sh: stale_containers" || no "lib.sh no longer defines stale_containers"
grep -q '^stale_images()' <<<"${LIB}" && ok "lib.sh: stale_images" || no "lib.sh no longer defines stale_images (the image-vs-sources question)"
grep -q 'not what the files say now' <<<"${BBOX}" && ok "bbox: the container drift line" || no "bbox stopped printing the container drift line"
grep -q 'images older than their sources' <<<"${BBOX}" && ok "bbox: the image drift line" || no "bbox stopped printing the image drift line"
grep -q 'stale_img="$(stale_images)"' <<<"${BBOX}" && ok "bbox: it is the helper that feeds the line" || no "the image line no longer comes from stale_images"
grep -q 'a re-create runs the old code' <<<"${BBOX}" && ok "bbox: the line says what to do (rebuild, not re-create)" || no "the image line lost the sentence that says a re-create is not enough"
[ "${fails}" -eq 0 ] && { echo; echo "0 failing"; exit 0; }
echo; echo "${fails} failing"; exit 1
