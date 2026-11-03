#!/usr/bin/env bash
# guest-box.sh <work> — the Android engine's guest disk, made inside one privileged box of its own
# (box/Dockerfile; android-engine.yml's guest job, DGO-1090): on a runner that is an office's own machine
# (the Dell), the job builds into no Docker but the box's, prunes nothing, needs no sudo, and leaves nothing
# behind but what it publishes and the box's Docker store (/store, kept for the next build). The checkout is /src (read-only), <work> the job's own directory; out of it
# come <work>/out's parts of the .xz and its digest. What GitHub's runner did, in the same order: the
# office's images for arm64, guest.sh, xz.
#   guest-box.sh --sweep <work>   what a box that was killed left: its loop device, the arm64 handler, <work>
# The arm64 handler (binfmt_misc) is the kernel's, the one thing here that is not the box's own: added only
# where the machine has none, and removed again at the end. Run under `dind` (android-engine.yml), which
# nests the box's cgroups before this script forks anything, so the box's dockerd starts directly here.
set -euo pipefail
sweep=""
if [ "${1:-}" = --sweep ]; then sweep=1; shift; fi
work="${1:?usage: guest-box.sh [--sweep] <work>}"
src=/src
bm=/proc/sys/fs/binfmt_misc
mountpoint -q "${bm}" || mount -t binfmt_misc binfmt_misc "${bm}"
# a box's /dev is a copy made as it starts: a loop device the kernel adds later has no node here
for i in $(seq 0 127); do [ -e "/dev/loop${i}" ] || mknod -m 0660 "/dev/loop${i}" b 7 "${i}"; done

unbind() {
  # the handler, if this job added it (a mark in <work>, which a sweep reads too)
  if [ -f "${work}/binfmt-added" ]; then
    { [ -e "${bm}/qemu-aarch64" ] && echo -1 > "${bm}/qemu-aarch64"; } || true
    rm -f "${work}/binfmt-added"
  fi
}

if [ -n "${sweep}" ]; then
  # the disk's loop device, by the file's inode (its path as the dead box named it is no longer anyone's),
  # before the file goes: a device left holding it would hold its blocks until the machine restarts
  if [ -f "${work}/dgo-guest-arm64.img" ]; then
    losetup -l -n -O NAME -j "${work}/dgo-guest-arm64.img" | while read -r d; do
      echo "sweep: ${d}"; losetup -d "${d}" || true
    done
  fi
  unbind
  find "${work}" -mindepth 1 -maxdepth 1 -exec rm -rf --one-file-system {} +
  exit 0
fi

dpid=""
leave() {
  set +e
  if [ -n "${dpid}" ]; then kill "${dpid}"; wait "${dpid}" && dstop=clean; dpid=""; fi
  # only a Docker that stopped as it should (0 on SIGTERM) leaves the kept store whole — not one the kernel
  # killed for memory mid-build, nor one that never started on it
  if [ "${droot:-}" = /store/docker ] && [ "${dstop:-}" = clean ]; then rm -f /store/dirty; fi
  unbind
}
trap leave EXIT

# the package's own line (Ubuntu 24.04's qemu-user-static ships it for systemd-binfmt alone, nothing in
# /usr/share/binfmts for update-binfmts to import), written to the kernel as systemd-binfmt writes it
if [ ! -e "${bm}/qemu-aarch64" ]; then
  touch "${work}/binfmt-added"
  # a write the kernel refused added nothing — not even one another registered meanwhile is this job's
  grep '^:qemu-aarch64:' /usr/lib/binfmt.d/qemu-aarch64.conf > "${bm}/register" || {
    rm -f "${work}/binfmt-added"
    echo "guest-box.sh: could not register the arm64 handler from /usr/lib/binfmt.d/qemu-aarch64.conf" >&2; exit 1
  }
fi
# F: the kernel opens the interpreter now, so a build's container and guest.sh's chroot run arm64 too
grep -q '^flags: .*F' "${bm}/qemu-aarch64" || { echo "guest-box.sh: the machine's arm64 handler has no F flag" >&2; exit 1; }

# the box's own Docker, its store on a real filesystem (overlay2 does not stack on the box's own): /store,
# kept between builds in the runner's tool cache (android-engine.yml), so a build reuses every layer whose
# inputs did not change — from zero, the office's images took 5677 s through emulation (run 41423453855).
# One box at a time holds it; another (a second runner) builds in <work>, from zero, and leaves nothing.
mkdir -p "${work}/tmp" "${work}/out"
export TMPDIR="${work}/tmp"
droot="${work}/docker"
drop() { echo "guest-box.sh: $1 — the kept store dropped, built from zero"; rm -rf --one-file-system /store/docker; rm -f /store/builder-prune.stamp /store/kept-mb /store/dirty; }
if [ -d /store ]; then
  exec 9> /store/lock
  if flock -n 9; then
    droot=/store/docker
    # a Docker that did not stop clean on the store (a cancelled job ends in SIGKILL, the kernel's OOM
    # killer, a store that never opened) can leave BuildKit's cache half written, and every later build
    # failing on it: its mark is still there
    if [ -e /store/dirty ]; then drop "the last box's Docker did not stop clean"; fi
    # the disk and its packing need their room beside the store, which used to go before them
    free="$(df -Pk "${work}" | awk 'NR == 2 {print int($4 / 1048576)}')"
    if [ -d /store/docker ] && [ "${free}" -lt 30 ]; then drop "${free} GB free beside it, under 30"; fi
    touch /store/dirty
  else
    echo "guest-box.sh: another box holds /store — this one builds from zero"
  fi
fi
mkdir -p "${droot}"
dockerd --data-root "${droot}" -H unix:///run/docker.sock --pidfile /run/docker.pid > "${work}/dockerd.log" 2>&1 &
dpid=$!
for _ in $(seq 60); do docker info >/dev/null 2>&1 && break; kill -0 "${dpid}" 2>/dev/null || break; sleep 1; done
docker info >/dev/null 2>&1 || { echo "guest-box.sh: the box's Docker did not start:" >&2; tail -n 30 "${work}/dockerd.log" >&2; exit 1; }
git config --global --add safe.directory '*'   # the checkout is the runner's user's; the box is root

# Every image the office runs, for arm64, with the .env and collection the guest's first boot makes: its
# own (the ones bbox builds: console, connections, machine…) built here through the handler, and the
# public ones (traefik, the databases…) pulled for arm64 — guest.sh unpacks them all into the guest's
# image store, so the phone neither builds, pulls nor unpacks one under emulation.
s=$(date +%s)
cp -a "${src}" "${work}/office" && cd "${work}/office"
# the guest's compose (2.40.3, pinned there): app-management bakes the compose version it was built with,
# and two versions re-create each other's containers
export COMPOSE_PROJECT_NAME=office DOCKER_DEFAULT_PLATFORM=linux/arm64 BBOX_COMPOSE_VERSION=2.40.3
docker version --format 'box docker {{.Server.Version}}'
# the phone's office as its first boot makes it (guest.sh): forward-auth's identity, the core
CI_IDENTITY=forward-auth CI_ENV_FORCE=1 CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh
cp platform.state.core.yaml platform.state.yaml
python3 platform/manager/reconcile.py render
# dc's weekly prune of the build cache keeps its schedule (a stamp under data/) with the store it prunes:
# in this fresh copy no stamp read as "never pruned", and the cache went after every build
if [ "${droot}" = /store/docker ]; then
  mkdir -p data/.locks
  # a store with no stamp is one built from zero by this job: its week starts now, not with a prune of it
  if [ -f /store/builder-prune.stamp ]; then cp /store/builder-prune.stamp data/.locks/; else date +%s > data/.locks/builder-prune.stamp; fi
fi
# --pull: each base checked against its registry, as a build from an empty store did — a kept store would
# otherwise build on the base it first pulled until the store goes
./scripts/dc build --pull
if [ "${droot}" = /store/docker ] && [ -f data/.locks/builder-prune.stamp ]; then
  cp data/.locks/builder-prune.stamp /store/
fi
# the public ones: an image no service builds (n8n's workers run the image its main service builds, which
# is in no registry) and none says never to pull. Pulled for arm64 even when one by that name is here
./scripts/dc config --format json > "${work}/compose.json"
pulled="$(python3 -c 'import json, sys; s = list(json.load(open(sys.argv[1]))["services"].values()); built = {v.get("image") for v in s if "build" in v}; print(" ".join(sorted({v["image"] for v in s if v.get("image") and v["image"] not in built and v.get("pull_policy") != "never"})))' "${work}/compose.json")"
for i in ${pulled}; do docker pull -q --platform linux/arm64 "${i}"; done
echo "pulled for arm64: ${pulled}"
# all of them, each checked to be here and for arm64 — a missing build stops it
all="$(./scripts/dc config --images | sort -u)"
for i in ${all}; do
  a="$(docker image inspect -f '{{.Architecture}}' "${i}" 2>/dev/null || true)"
  [ "${a}" = arm64 ] || { echo "guest-box.sh: ${i} is ${a:-not here}, not arm64" >&2; exit 1; }
done
# shellcheck disable=SC2086 — a list of image names
docker save -o "${work}/images.tar" ${all}
ls -la "${work}/images.tar"; echo "$(echo ${all} | wc -w) images in $(( $(date +%s) - s )) s"
# the box's Docker is done. A store in <work> goes (room for the disk and its packing); the kept one stays,
# and its size is what the next job counts as room it already has — dropped past 15 GB, so it never grows
# without bound (an app gone, a public image's old tag: nothing else removes those)
cd /
kill "${dpid}"; if wait "${dpid}"; then dstop=clean; fi; dpid=""
rm -rf --one-file-system "${work}/docker" "${work}/office"
if [ "${droot}" = /store/docker ]; then
  if [ "${dstop:-}" = clean ]; then rm -f /store/dirty; else echo "guest-box.sh: the box's Docker did not stop clean — its store goes at the next build"; fi
  kept="$(du -sm /store/docker | cut -f1)"
  if [ "${kept}" -gt 15360 ]; then drop "it is ${kept} MB, past 15 GB (for the next build)"; kept=0; fi
  echo "${kept}" > /store/kept-mb
  echo "the store kept for the next build: ${kept} MB"
fi
df -h "${work}" | tail -1

# guest.sh binds the box's /run into its chroot, as it did the runner's: the image's /etc/resolv.conf is a
# link into /run/systemd/resolve — the runner's resolver there; in a box there is none, so the box's own is
# put there (no service starts in the chroot either way: guest.sh's policy-rc.d)
mkdir -p /run/systemd/resolve
cp /etc/resolv.conf /run/systemd/resolve/stub-resolv.conf
cp /etc/resolv.conf /run/systemd/resolve/resolv.conf

s=$(date +%s)
DGO_GUEST_IMAGES="${work}/images.tar" bash "${src}/packaging/android/engine/guest.sh" "${work}/dgo-guest-arm64.img"
echo "made in $(( $(date +%s) - s )) s"
rm -f "${work}/images.tar"
# xz, the smallest the phone reads (the zstd program beside QEMU reads .xz; Java's framework has no reader
# for either): the whole office, every image in it, inside one APK under GitHub's 2 GB a file (gzip -6 left
# 1.13 GB of public images no room: measured from their registries, 2026-11-01). As many threads as the
# box has CPUs (its --cpus); in parts under that limit too, joined in name order.
s=$(date +%s)
xz -T"${GUEST_BOX_CPUS:-2}" -9 -c "${work}/dgo-guest-arm64.img" > "${work}/dgo-guest-arm64.img.xz"
rm -f "${work}/dgo-guest-arm64.img"
echo "packed in $(( $(date +%s) - s )) s: $(du -h "${work}/dgo-guest-arm64.img.xz" | cut -f1)"
(cd "${work}" && sha256sum dgo-guest-arm64.img.xz > out/dgo-guest-arm64.img.xz.sha256)
split -b 1900M -d -a 2 "${work}/dgo-guest-arm64.img.xz" "${work}/out/dgo-guest-arm64.img.xz.part"
# …and the pieces a phone fetches instead (DGO-1089, Guest.fetch): 32 MiB of the .xz each, named by its
# SHA-256, and their list — whose own SHA-256 is what an APK that fetches the machine is built with
# (read straight from the .xz, one 32 MiB block at a time — the memory one piece takes). The list is also
# published under its own SHA-256, the name a phone asks for it by.
mkdir -p "${work}/out/pieces"
python3 - "${work}/dgo-guest-arm64.img.xz" "${work}/out/pieces" "${work}/out/dgo-guest-arm64.manifest.json" <<'PY'
import hashlib, json, os, sys
xz, pieces, manifest = sys.argv[1:4]
listed, total = [], 0
with open(xz, "rb") as f:
    while True:
        block = f.read(32 << 20)
        if not block:
            break
        sha = hashlib.sha256(block).hexdigest()
        tmp = os.path.join(pieces, sha + ".tmp")
        with open(tmp, "wb") as o:
            o.write(block)
        os.replace(tmp, os.path.join(pieces, sha))   # the same bytes twice are one piece, listed twice
        listed.append({"sha256": sha, "size": len(block)})
        total += len(block)
raw = json.dumps({"version": 1, "total": total, "pieces": listed}, separators=(",", ":")).encode()
with open(manifest, "wb") as o:
    o.write(raw)
with open(os.path.join(pieces, hashlib.sha256(raw).hexdigest()), "wb") as o:
    o.write(raw)
print(f"{len(listed)} pieces, {total} bytes; the list {hashlib.sha256(raw).hexdigest()}")
PY
rm -f "${work}/dgo-guest-arm64.img.xz"
# the runner's user publishes them (the box is root)
chown -R "$(stat -c %u:%g "${src}")" "${work}/out"
ls -la "${work}/out"
