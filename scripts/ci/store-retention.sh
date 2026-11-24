#!/usr/bin/env bash
# store-retention — the image store keeps what the line's last lists name, and stays under its cap (DGO-2123).
#
#   bash scripts/ci/store-retention.sh        # in the proof's green job, after refs/green moved
#
# Each proof pushes the images its batch changed (scripts/ci/push-images.sh). This keeps what the last three lists of
# refs/images/dgo-stable name (scripts/ci/prune-images.py deletes every other manifest through the store's own API,
# never through the read-only door), and the registry's garbage collection in the store's own container gives the
# space back. Then it reads the store's size there. Over its cap, it keeps two lists, then one. It never deletes what
# the newest list names: a store still over its cap with one list is said, and nothing more is deleted.
#
# THE CAP (STORE_CAP_KIB, 4 GiB by default). The Dell's disk was 92% full on 2026-11-20, with 19.6 GB free of 250, read
# through its office (the machine app's /api/storage, `scripts/remote.py portable-ubuntu machine /api/storage`). That
# leaves 15 GB to the office. The store holds plain builds alone, each under push-images.sh's MAX_IMAGE_BYTES (1 GiB);
# at about 35 of them, one version each, compressed, that is 3–4 GiB. The cap is what bounds it whatever that sum.
#
# Never the proof's verdict: every failure is said, and it always ends 0. There is no --delete-untagged in the
# collection: in registry 2.8 it can delete the untagged children of an index. Blobs no manifest names are what it frees.
# Nothing pushes while it runs: the one runner is in this job, and the collection is bounded inside the container.
# After it, the store is restarted once: its in-memory blob cache would otherwise outlive what was swept.
#
# THE LISTS are read from GIT_DIR when the job sets it: the green job's `retention` job fetches them fresh into an
# empty repository, so a fetch that fails leaves no list and prune-images.py deletes nothing.
#
#   env STORE_CAP_KIB    the cap, in KiB (default 4194304)
#       DOCKER           the engine's CLI (a seam for the test)
#       PRUNE_CMD        the prune (a seam for the test; default: python3 scripts/ci/prune-images.py)
set -uo pipefail
CAP="${STORE_CAP_KIB:-4194304}"
DOCKER="${DOCKER:-docker}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}" || exit 0
say() { printf 'store-retention: %s\n' "$*"; }
prune() { if [ -n "${PRUNE_CMD:-}" ]; then ${PRUNE_CMD} --keep "$1"; else python3 scripts/ci/prune-images.py --keep "$1"; fi; }

c="$(${DOCKER} ps -q --filter label=com.docker.compose.service=image-store --filter status=running 2>/dev/null | head -1)"
if [ -z "${c}" ]; then say "no image-store container runs on this engine — nothing pruned"; exit 0; fi
kib="" under=""
for keep in 3 2 1; do
  prune "${keep}" || say "the prune keeping ${keep} list(s) failed (above)"
  # bounded INSIDE the container: a limit on this step would stop only the client, and the collection would go on
  # into the next proof's push (the second reader)
  ${DOCKER} exec "${c}" timeout 600 registry garbage-collect /etc/docker/registry/config.yml >/dev/null 2>&1 \
    || say "the garbage collection failed or ran past 10 minutes — the store keeps what it held"
  kib="$(${DOCKER} exec "${c}" du -sk /var/lib/registry 2>/dev/null | cut -f1)"
  case "${kib}" in ''|*[!0-9]*) say "the store's size could not be read — nothing more is deleted"; kib=""; break ;; esac
  say "the store holds ${kib} KiB, keeping what the last ${keep} list(s) name; its cap is ${CAP} KiB"
  if [ "${kib}" -le "${CAP}" ]; then under=1; break; fi
done
[ -n "${under}" ] || [ -z "${kib}" ] \
  || say "::warning::the store holds ${kib} KiB with the newest list alone, over its cap of ${CAP} KiB — what that list names is kept"
# The serving registry keeps an in-memory cache of the blobs it has seen. After a collection it can still believe in a
# swept one, and accept a push of an image whose layer is gone (the second reader). A restart forgets it, once.
${DOCKER} restart "${c}" >/dev/null 2>&1 || say "the store could not be restarted after its collection"
exit 0
