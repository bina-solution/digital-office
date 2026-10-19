#!/usr/bin/env bash
# uimap-portable.sh — capture a full UI map of the stack that the single executable installed.
#
#   sudo bash uimap-portable.sh [/path/to/repo-copy]
#
# WHY THE REPO IS NEEDED AND THE ARTIFACT IS NOT WRONG TO OMIT IT
#
# `bbox ui-map` is BUILD-side QA, not part of the product: it derives the denominator (every view the
# platform is supposed to have) from application SOURCE, then screenshots a running stack and reports
# what it could not reach. stage-control deliberately ships only the runtime tree, so the artifact
# has no source and no bbox — correctly, since a customer never screenshots their own platform.
#
# So the split is: the STACK under test comes from the executable, the MAPPER comes from the repo.
# That is the honest arrangement, and it is what makes the resulting map a statement about the
# artifact rather than about a developer checkout.
#
# The capture fans out Chromium containers onto the stack's own network and points their
# host-resolver at the console's container IP, so it has to run on the machine hosting the stack and
# against the engine that stack runs on — ours, not the host's.
set -uo pipefail

REPO="${1:-/home/shlomy/binaos-repo}"
LOG=/tmp/binaos-uimap.log
exec > >(tee "${LOG}") 2>&1
echo "=== $(date -u +%FT%TZ) ui-map on $(hostname) ==="

[ -d "${REPO}" ] || { echo "no repo copy at ${REPO}"; exit 1; }

# Everything below must talk to the engine the executable installed, not the host's Docker.
[ -f /etc/binaos/engine.env ] && . /etc/binaos/engine.env
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/binaos-docker.sock}"
echo "engine: ${DOCKER_HOST} -> $(docker version --format '{{.Server.Version}}' 2>/dev/null), $(docker ps -q | wc -l) container(s)"

# Credentials for the app logins the capture performs; without them those views come back as a login
# screen and count as misses rather than coverage.
[ -f /etc/binaos/binaos.env ] && set -a && . /etc/binaos/binaos.env && set +a

cd "${REPO}"

echo "=== stack must be up before capturing ==="
for h in console apps; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  echo "  ${h}.localhost -> ${code}"
done

echo "=== capture ==="
# Skip seeding by default: the stack came from the artifact and we are mapping what a fresh install
# looks like. UI_MAP_SKIP_SEED=0 seeds first - though measured on this machine that changed coverage
# by under a percent, because the views it does not capture are parameterised routes it declines
# without a resolved id, not empty screens waiting for data.
export UI_MAP_SKIP_SEED="${UI_MAP_SKIP_SEED:-1}"
export UI_MAP_SHARDS="${UI_MAP_SHARDS:-2}"      # 4-core machine; 8 shards would thrash

# tee, NOT `| tail -40`. A pipe to tail buffers the whole run and emits nothing until it finishes,
# so a 20-minute capture looks identical to a hang, and everything before the last 40 lines is lost
# for good - including the seed step, which is how a question about whether seeding had even run
# became unanswerable after the fact.
CAPTURE_LOG="${CAPTURE_LOG:-/tmp/binaos-uimap-capture.log}"
bash scripts/ui-coverage/ui-map.sh 2>&1 | tee "${CAPTURE_LOG}" | tail -40
echo "  (full capture log: ${CAPTURE_LOG})"

echo
echo "=== output ==="
find ci-artifacts/ui-map -maxdepth 2 -name '*.png' -o -maxdepth 2 -name 'index.html' 2>/dev/null | head -10
ls -lh ci-artifacts/ui-map/ui-map.png 2>/dev/null
