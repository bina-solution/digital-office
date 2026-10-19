#!/usr/bin/env bash
# build-rootfs.sh — produce the WSL2-importable rootfs, with the platform's images PRE-BAKED.
#
#   packaging/windows/build-rootfs.sh --out dist/binaos-rootfs.tar.gz
#
# Run on Linux with Docker (a runner, the VPS, or WSL). Not on Git-Bash.
#
# WHY PRE-BAKE
# The alternative is shipping a `docker save` tarball and importing it on the customer's machine:
# 8-25 minutes dominated by the import, ~34 GB peak disk, and a partially-imported state to recover
# from if it dies half way. Baking the images into /var/lib/docker at build time — what `kind` does
# for node images — makes first run a boot instead. See packaging/README.md.
#
# WHY .tar.gz AND NOT .tar.zst
# WSL's importer is libarchive, and .tar.zst was empirically confirmed to import fine — but
# `wsl --export --format` only advertises tar/tar.gz/tar.xz, so zstd on the import side is
# undocumented and could regress silently. gzip is small enough here and is what Microsoft documents.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${REPO_ROOT}"

OUT="dist/binaos-rootfs.tar.gz"
BASE="debian:trixie-slim"

while [ $# -gt 0 ]; do
  case "$1" in
    --out)  OUT="${2:?}"; shift ;;
    --base) BASE="${2:?}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "build-rootfs: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "build-rootfs: $*" >&2; exit 1; }
[ "$(uname -s)" = "Linux" ] || die "must run on Linux (WSL counts); got $(uname -s)"
command -v docker >/dev/null || die "docker not found"
docker version >/dev/null 2>&1 || die "docker daemon not reachable"

mkdir -p "$(dirname "${OUT}")"
WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT

# ── the image that becomes the distro ─────────────────────────────────────────────────────────
# QUOTED heredoc, and the base image substituted after. This block is mostly English prose, and an
# UNQUOTED heredoc executes every backtick and $(...) inside it. A comment reading "every command
# the platform runs is <backtick>docker compose<backtick>" therefore RAN docker compose and pasted
# its help text into the middle of the Dockerfile:
#     dockerfile parse error on line 24: unknown instruction: Define
# Nothing in that message points at a comment. Prose and command substitution must not share a
# heredoc, so the only variable is injected afterwards via the @@PLACEHOLDER@@ convention header.sh
# already uses.
cat > "${WORK}/Dockerfile" <<'DOCKERFILE'
FROM @@BASE@@

# systemd is what gives WSL a proper cgroup2 unified hierarchy; without it /sys/fs/cgroup is a
# tmpfs with no controllers and dockerd runs on cgroup v1 hybrid.
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus ca-certificates curl gnupg iptables nftables \
      iproute2 procps xz-utils zstd python3 python3-yaml \
 && rm -rf /var/lib/apt/lists/*

# Docker from the STATIC tarball, not the apt repo.
#
# The apt route installs whatever the repo currently serves - today that is Docker 29, and Docker 29
# makes traefik v3.3 discover ZERO routers while reporting healthy (it caps DOCKER_MIN_API_VERSION
# at 1.40). A rootfs built on Tuesday would work and one built on Thursday would 404 everything,
# with nothing in the build log to say why. The static tarball is byte-pinned to the version this
# platform is verified against, and it is the SAME artifact the Linux .run embeds - one engine, one
# version, all platforms.
COPY docker-static.tgz /tmp/docker-static.tgz
COPY containerd.service /etc/systemd/system/containerd.service
COPY docker.service /etc/systemd/system/docker.service
# The compose plugin is NOT in the static tarball - it is a separate CLI plugin, and every command
# the platform runs is "docker compose". Without it the unit fails with
# "docker: compose is not a docker command".
COPY docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
RUN tar -xzf /tmp/docker-static.tgz -C /tmp \
 && install -m 0755 /tmp/docker/* /usr/local/bin/ \
 && rm -rf /tmp/docker /tmp/docker-static.tgz \
 && chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose \
 && dockerd --version && runc --version && docker compose version

# iptables-legacy, not the nf_tables backend Debian trixie defaults to. dockerd cannot create its
# bridge network on a WSL2 kernel using nf_tables:
#   failed to register "bridge" driver: iptables --wait -t nat -A PREROUTING ...
#   Warning: Extension addrtype revision 0 not supported, missing kernel module?
#   iptables v1.8.11 (nf_tables): CHAIN_ADD failed (No such file or directory): chain PREROUTING
# containerd starts fine, so it presents as "docker load failed" with no obvious cause. The WSL2
# kernel supports the legacy xtables path; this switches to it.
RUN update-alternatives --set iptables /usr/sbin/iptables-legacy \
 && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy

# Units Microsoft documents as breaking a WSL distro. Leaving them enabled produces a distro that
# boots but has no working DNS, which presents as every pull failing for no visible reason.
RUN systemctl mask systemd-resolved systemd-networkd NetworkManager \
      systemd-tmpfiles-setup systemd-tmpfiles-clean systemd-tmpfiles-clean.timer \
      systemd-tmpfiles-setup-dev tmp.mount 2>/dev/null || true

COPY wsl.conf /etc/wsl.conf
COPY binaos.service /etc/systemd/system/binaos.service
# The platform tree the unit runs, and the script the installer uses to fit it to the customer's
# machine. Without these /opt/binaos is empty and the unit starts nothing.
COPY platform /opt/binaos
COPY adapt-host.py /opt/binaos/adapt-host.py

# ORDER: this must come AFTER the COPY above. It used to run before it, so the enable was pointed at
# a unit file that did not exist yet - it failed, "|| true" swallowed it, and the distro shipped
# with the stack not enabled. install.ps1 starts the unit explicitly, so the only visible symptom
# was that the platform never came back after a reboot.
RUN systemctl enable docker.service containerd.service binaos.service
DOCKERFILE
sed -i "s|@@BASE@@|${BASE}|" "${WORK}/Dockerfile"

cat > "${WORK}/wsl.conf" <<'WSLCONF'
[boot]
systemd=true

# Imported distros cannot use `<distro>.exe config --default-user`, so the default user has to be
# baked in here. This appliance runs as root deliberately — there is no interactive login.
[user]
default=root

[interop]
enabled=true
appendWindowsPath=false

[network]
generateResolvConf=true
WSLCONF

# The engine: the same static tarball the Linux .run embeds, fetched and VERIFIED by the same
# script, so Windows and Linux can never drift onto different engine versions.
echo "==> staging the container engine"
bash "${HERE}/../linux/fetch-runtime.sh" --arch amd64 --out "${WORK}/runtime" >/dev/null   || die "could not stage the container engine"
cp "${WORK}"/runtime/docker-*.tgz "${WORK}/docker-static.tgz"
cp "${WORK}"/runtime/docker-compose-* "${WORK}/docker-compose"

# The platform itself. The Dockerfile COPYs this to /opt/binaos, which is what the unit runs from —
# nothing was staging it before, so the unit had an empty working directory and started nothing.
# Same two scripts the Linux .run uses, so both platforms ship an identical tree.
echo "==> staging the platform tree"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
[ -f "${REPO_ROOT}/.generated/compose.yml" ] || die "no .generated/compose.yml - run 'bbox reconcile' first"
python3 "${REPO_ROOT}/packaging/make-runtime-compose.py" \
  --out "${REPO_ROOT}/.generated/compose.runtime.yml" >/dev/null \
  || die "could not generate the build-free runtime compose"
python3 "${REPO_ROOT}/packaging/stage-control.py" --dest "${WORK}/platform" \
  || die "platform staging failed"
[ -f "${HERE}/../linux/adapt-host.py" ] || die "packaging/linux/adapt-host.py is missing - install.ps1 calls it"
cp "${HERE}/../linux/adapt-host.py" "${WORK}/adapt-host.py"
cp "${WORK}"/runtime/../runtime/RUNTIME.json "${WORK}/RUNTIME.json" 2>/dev/null || true

# systemd units the apt packages used to provide.
cat > "${WORK}/containerd.service" <<'CTR'
[Unit]
Description=containerd container runtime
After=network.target
[Service]
ExecStart=/usr/local/bin/containerd
Restart=always
Delegate=yes
KillMode=process
LimitNOFILE=1048576
OOMScoreAdjust=-999
[Install]
WantedBy=multi-user.target
CTR

cat > "${WORK}/docker.service" <<'DOC'
[Unit]
Description=Docker Application Container Engine
After=containerd.service
Requires=containerd.service
[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd --containerd=/run/containerd/containerd.sock
Restart=always
LimitNOFILE=1048576
TasksMax=infinity
Delegate=yes
KillMode=process
OOMScoreAdjust=-500
[Install]
WantedBy=multi-user.target
DOC

# ONE unit definition, shared with the Linux installer. There used to be a fallback here that wrote
# its own copy if the cp failed, and that copy ran `docker compose -f /opt/binaos/compose.yml`. The
# root compose.yml holds only the shared network, so a bare invocation resolves ZERO services and
# exits 0 - a silent no-op that reports success and starts nothing. That is precisely what gate G7
# exists to catch, reintroduced in a fallback path nobody would look at. Better to fail the build.
[ -f "${HERE}/../linux/binaos.service" ] || die "packaging/linux/binaos.service is missing - Windows shares it"
cp "${HERE}/../linux/binaos.service" "${WORK}/binaos.service"

echo "==> building the distro image"
docker build -t binaos-rootfs "${WORK}"

# ── export ────────────────────────────────────────────────────────────────────────────────────
# `docker create` + `docker export`, not `docker run` — nothing in the image should execute here.
echo "==> exporting"
cid="$(docker create binaos-rootfs)"
trap 'docker rm -f "${cid}" >/dev/null 2>&1 || true; rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/rootfs"
docker export "${cid}" | tar -C "${WORK}/rootfs" -x

# WSL supplies these itself; shipping them breaks DNS and hostname resolution in the imported distro.
rm -f "${WORK}/rootfs/.dockerenv" "${WORK}/rootfs/etc/resolv.conf" "${WORK}/rootfs/etc/hostname"
# Must be present and EMPTY, not absent — systemd regenerates a per-install id from an empty file.
: > "${WORK}/rootfs/etc/machine-id"

# --sort=name --mtime=@0 + gzip -n make the output byte-reproducible, which matters because the
# installer that carries it gets signed.
echo "==> packing ${OUT}"
tar --numeric-owner --sort=name --mtime='@0' --owner=0 --group=0 --xattrs \
    -C "${WORK}/rootfs" -c . | gzip -n --best > "${OUT}"

printf 'done: %s (%.2f GB)\n' "${OUT}" "$(wc -c < "${OUT}" | awk '{print $1/1e9}')"
echo
echo "NOTE: images are NOT yet baked into this rootfs. Baking requires running dockerd inside the"
echo "      build container (dind, --privileged) and pulling the pinned set into /var/lib/docker."
echo "      Until that lands, the Windows installer must \`docker load\` on first run."
