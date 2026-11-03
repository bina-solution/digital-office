# The box android-engine.yml's guest job runs in (guest-box.sh, DGO-1090): Ubuntu 24.04 as GitHub's runner
# is, with the tools guest.sh names (qemu-user-static, qemu-utils, cloud-guest-utils, python3-yaml) and a
# Docker of its own — the release the installers and the guest install (debian-install.sh: 28.5.2), its
# daemon out of Docker's dind image, its CLI with buildx and compose out of the CLI image (G74). The box's
# Docker is the job's alone: what it builds, pulls and prunes is never the machine's own Docker's — whose
# store holds only this box's image and its three bases (docker:28.5.2-cli, -dind, ubuntu:24.04).
FROM docker:28.5.2-cli AS cli
FROM docker:28.5.2-dind AS engine
FROM ubuntu:24.04
# no handler is registered here (no binfmt_misc in a build): guest-box.sh registers the one it needs, from
# qemu-user-static's own binfmt.d line, only while it runs
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
       ca-certificates curl git python3 python3-yaml openssl jq rsync xz-utils iptables procps \
       qemu-user-static qemu-utils cloud-guest-utils fdisk e2fsprogs util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY --from=engine /usr/local/bin/ /usr/local/bin/
# where the compose package puts them, which is where scripts/lib.sh looks (BBOX_COMPOSE)
COPY --from=cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/libexec/docker/cli-plugins/docker-buildx
COPY --from=cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose
