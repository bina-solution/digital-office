#!/usr/bin/env bash
# fetch-runtime.sh — build the RUNTIME segment: a container engine the installer can land offline.
#
#   packaging/linux/fetch-runtime.sh --arch amd64 --out dist/runtime-repo
#
# This fills the 202-byte placeholder in BinaOS.run. Until it does, the installer REQUIRES Docker
# already present on the target — which is the one thing the single-file design exists to remove.
#
# WHAT IT SHIPS, AND WHY THIS AND NOT DOCKER DESKTOP
# Docker Desktop and OrbStack are proprietary; their licences forbid redistribution. The ENGINE is
# not: Docker publishes static builds of the whole runtime under Apache-2.0, and they are
# redistributable. Verified sizes: 77.7 MB (x86_64) / 71.1 MB (aarch64), containing
#   dockerd · containerd · containerd-shim-runc-v2 · runc · docker · docker-proxy · docker-init · ctr
# i.e. everything needed to run containers, with no daemon install and no package manager.
#
# PINNED TO 28.5.2 DELIBERATELY. Docker 29 raised the daemon's hard API floor to 1.40 and CAPS
# DOCKER_MIN_API_VERSION there, so traefik v3.3 (which hardcodes client API 1.24) discovers ZERO
# routers and every route 404s — silently, with traefik reporting healthy. See packaging/linux.md.
# Shipping our own engine is what makes that version guarantee possible rather than a hope.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${REPO_ROOT}"

DOCKER_VERSION=28.5.2
ARCH=amd64
OUT="dist/runtime-repo"

while [ $# -gt 0 ]; do
  case "$1" in
    --arch)    ARCH="${2:?--arch needs amd64|arm64}"; shift ;;
    --version) DOCKER_VERSION="${2:?}"; shift ;;
    --out)     OUT="${2:?}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "fetch-runtime: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

case "${ARCH}" in
  amd64) DL_ARCH=x86_64 ;;
  arm64) DL_ARCH=aarch64 ;;
  *) echo "fetch-runtime: --arch must be amd64 or arm64" >&2; exit 2 ;;
esac

die() { echo "fetch-runtime: $*" >&2; exit 1; }
command -v curl >/dev/null || die "curl not found"

mkdir -p "${OUT}"
TGZ="${OUT}/docker-${DOCKER_VERSION}-${DL_ARCH}.tgz"
URL="https://download.docker.com/linux/static/stable/${DL_ARCH}/docker-${DOCKER_VERSION}.tgz"

if [ -s "${TGZ}" ]; then
  echo "already have $(basename "${TGZ}")"
else
  echo "fetching ${URL}"
  curl -fsSL --retry 3 -o "${TGZ}.part" "${URL}" || die "download failed"
  mv "${TGZ}.part" "${TGZ}"
fi

# Verify it is what we think BEFORE it goes into a signed artifact: a truncated or wrong-arch
# tarball would only surface on the customer's machine, as a runtime that will not start.
# List ONCE into a variable, then match against it. `tar ... | grep -q` looks right and is a trap
# under `set -o pipefail`: grep exits at the first match, closing the pipe, so tar dies of SIGPIPE
# (141) and pipefail reports the whole pipeline as failed. That made this reject a perfectly good
# 77.7 MB tarball with "dockerd missing from the tarball" — a false negative that would have sent
# someone hunting a download problem that did not exist.
listing="$(tar -tzf "${TGZ}" 2>/dev/null)" || die "$(basename "${TGZ}") is not a readable gzip tar"
for bin in dockerd containerd containerd-shim-runc-v2 runc docker docker-proxy docker-init; do
  printf '%s
' "${listing}" | grep -qx "docker/${bin}"     || die "${bin} missing from the tarball (got: $(printf '%s' "${listing}" | tr '
' ' '))"
done
echo "  verified: $(printf '%s
' "${listing}" | grep -c '^docker/.') binaries present"
sha="$(sha256sum "${TGZ}" | cut -d' ' -f1)"
size="$(wc -c < "${TGZ}")"

# ── the compose plugin ────────────────────────────────────────────────────────────────────────
# The static tarball above ships dockerd, containerd, runc and the `docker` CLI — but NOT
# `docker compose`, which is a separate CLI plugin. Everything the platform runs is invoked as
# `docker compose`, so without this the artifact silently depends on the customer having ALREADY
# installed Docker from their distro. On the portable test machine this went unnoticed for a full
# day because the host had /usr/libexec/docker/cli-plugins/docker-compose from its own apt install,
# and the `docker` CLI happily found it. A machine with no Docker at all would have failed with:
#
#     docker: 'compose' is not a docker command
#
# which is the exact "no external dependencies" promise the whole single-file exercise exists to
# keep. Apache-2.0, redistributable, same terms as the engine.
COMPOSE_VERSION="${COMPOSE_VERSION:-2.40.3}"
case "${ARCH}" in amd64) CMP_ARCH=x86_64 ;; arm64) CMP_ARCH=aarch64 ;; esac
CMP="${OUT}/docker-compose-${COMPOSE_VERSION}-${CMP_ARCH}"
CMP_URL="https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${CMP_ARCH}"

if [ -s "${CMP}" ]; then
  echo "already have $(basename "${CMP}")"
else
  echo "fetching ${CMP_URL}"
  curl -fsSL --retry 3 -o "${CMP}.part" "${CMP_URL}" || die "compose plugin download failed"
  mv "${CMP}.part" "${CMP}"
fi
# A plugin that cannot report its own version is not one we ship. This also catches an HTML error
# page saved under a binary's name, which is what a wrong version tag produces.
chmod +x "${CMP}"
cmp_reported="$("${CMP}" version --short 2>/dev/null || true)"
[ -n "${cmp_reported}" ] || die "$(basename "${CMP}") does not run — wrong arch or a bad download"
echo "  verified: compose plugin reports ${cmp_reported}"
cmp_sha="$(sha256sum "${CMP}" | cut -d' ' -f1)"

# The installer runs this to land the engine. Kept as a script beside the payload so the .run's
# header stays generic: it extracts the runtime segment and executes install-runtime.sh, whatever
# that turns out to do for this arch.
cat > "${OUT}/install-runtime.sh" <<INSTALL
#!/usr/bin/env bash
# Installed by BinaOS.run when the target has no usable Docker. Static binaries into /usr/local/bin
# plus a systemd unit — no package manager, no repository, no network.
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"

tar -xzf "\${HERE}/$(basename "${TGZ}")" -C /tmp
install -m 0755 /tmp/docker/* /usr/local/bin/
rm -rf /tmp/docker

# The compose plugin goes to the CLI's plugin directory, not onto PATH. \`docker compose\` looks in
# /usr/local/lib/docker/cli-plugins before the distro's /usr/libexec one, so ours wins and the
# customer's own Docker install (if any) keeps whatever version it had.
install -d /usr/local/lib/docker/cli-plugins
install -m 0755 "\${HERE}/$(basename "${CMP}")" /usr/local/lib/docker/cli-plugins/docker-compose

# containerd: REUSE the host's if it already runs one.
#
# The first install on a box with Docker 29 overwrote /etc/systemd/system/containerd.service and
# restarted it — disrupting the host's own engine to install ours. That is exactly the collision
# the private socket/data-root/bridge design exists to avoid, and it undid it in one line.
#
# Sharing containerd is safe: dockerd isolates its state with --containerd-namespace, which is why
# our daemon and the host's can drive the same containerd without seeing each other's containers.
# So only write the unit when there is nothing to reuse.
if systemctl is-active --quiet containerd 2>/dev/null; then
  echo "reusing the host containerd (our state is namespaced under 'binaos')"
else
cat > /etc/systemd/system/containerd.service <<'UNIT'
[Unit]
Description=containerd container runtime
After=network.target

[Service]
ExecStart=/usr/local/bin/containerd
Restart=always
Delegate=yes
KillMode=process
LimitNOFILE=1048576
# Docker's own unit sets these: an OOM-killed daemon takes every container with it.
OOMScoreAdjust=-999

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now containerd.service
fi

# A PRIVATE engine: own socket, own data-root, own bridge, own address pool.
#
# The host may already run Docker — possibly a version this platform cannot use (29 caps
# DOCKER_MIN_API_VERSION at 1.40 and makes traefik v3.3 find zero routers, silently). Refusing in
# that case defeats the purpose of shipping an engine at all. Instead BinaOS runs its own beside
# whatever is there, sharing nothing:
#
#   socket     /run/binaos-docker.sock      not /var/run/docker.sock
#   data-root  /var/lib/binaos-docker       its images never mix with the host's
#   bridge     binaos0                      distinct from docker0
#   pool       10.201.0.0/16                cannot collide with the host's default 172.17/16
#
# Multiple daemons on one host are officially unsupported ONLY because they collide on exactly
# those four things. Separate them and they coexist. containerd is namespaced per data-root, so
# the shim processes stay distinct too.
#
# THE BRIDGE IS PART OF STARTING THE SERVICE. dockerd creates its default bridge by itself ONLY
# when it is called docker0; with any other name it refuses outright:
#   "bridge device with non default name binaos0 must be created manually"
# This script used to create it once, at install time — and an \`ip link\` bridge does not survive
# a reboot. After the first one the unit burned its five starts in three seconds and gave up for
# good, and the host fell back, silently, to the system engine this one exists to stand beside
# (portable-ubuntu, dead from its first reboot: issues/binaos-docker-bridge-not-persistent.yaml).
# So the unit makes the bridge on every start, with an address inside the pool the daemon is
# configured for, and a slow boot can no longer use up a start limit: it retries every 3 s.
cat > /etc/systemd/system/binaos-docker.service <<'UNIT'
[Unit]
Description=BinaOS container engine (private instance)
After=containerd.service network-online.target
Wants=network-online.target
Requires=containerd.service
StartLimitIntervalSec=0

[Service]
Type=notify
ExecStartPre=/bin/sh -c 'ip link show binaos0 >/dev/null 2>&1 || { ip link add name binaos0 type bridge && ip addr add 10.201.0.1/24 dev binaos0; }; ip link set binaos0 up'
ExecStart=/usr/local/bin/dockerd \
  --host=unix:///run/binaos-docker.sock \
  --data-root=/var/lib/binaos-docker \
  --exec-root=/var/run/binaos-docker \
  --pidfile=/run/binaos-docker.pid \
  --bridge=binaos0 \
  --default-address-pool base=10.201.0.0/16,size=24 \
  --containerd=/run/containerd/containerd.sock \
  --containerd-namespace=binaos \
  --containerd-plugins-namespace=binaos-plugins
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=3
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
Delegate=yes
KillMode=process
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
UNIT

getent group docker >/dev/null || groupadd docker

systemctl daemon-reload
systemctl enable --now binaos-docker.service

# Do not trust "enabled" — prove the daemon answers before the installer moves on to loading
# 2 GB of images into it.
export DOCKER_HOST=unix:///run/binaos-docker.sock
for i in \$(seq 1 45); do
  docker version --format '{{.Server.Version}}' >/dev/null 2>&1 && break
  sleep 2
done
docker version --format 'BinaOS engine {{.Server.Version}} ready on /run/binaos-docker.sock' || {
  echo "the bundled engine did not start; see: journalctl -u binaos-docker" >&2
  exit 1
}
INSTALL
chmod +x "${OUT}/install-runtime.sh"

cat > "${OUT}/RUNTIME.json" <<META
{
  "engine": "docker",
  "version": "${DOCKER_VERSION}",
  "arch": "${ARCH}",
  "file": "$(basename "${TGZ}")",
  "size": ${size},
  "sha256": "${sha}",
  "license": "Apache-2.0",
  "source": "${URL}"
}
META

printf 'runtime staged: %s (%.1f MB, docker %s/%s)\n' \
  "${OUT}" "$(echo "${size}" | awk '{print $1/1048576}')" "${DOCKER_VERSION}" "${ARCH}"
echo "  sha256 ${sha}"
