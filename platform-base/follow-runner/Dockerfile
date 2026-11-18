# follow-runner — the image a follow cycle runs in (runner.sh): what `./bbox run` needs from inside a container, and no more.
# The docker CLI and the compose plugin pinned as app-management pins them (compose's version is part of what the
# compiled files mean), git for the take itself, and PyYAML for the compiler (platform/manager/reconcile.py).
# BuildKit (the buildx plugin, as apps/bina-ds and apps/bina-claude install it): without it compose hands a build to the
# engine's classic builder, which refuses `COPY --chmod` (https-redirect, n8n) and never sets the BUILDPLATFORM /
# TARGETOS / TARGETARCH that forward-auth's build reads. One such refusal stops the whole build of a take, and the take's
# second `up` then recreates every service built from the checkout on its OLD image — measured on the HP, 2026-11-12
# 18:35Z: «the --chmod option requires BuildKit», then dgo-extend crash-looping on its 11-06 image under the new
# compose and drive unhealthy on its 11-03 one (DGO-1863).
FROM python:3.12-slim
ARG COMPOSE_VERSION=2.40.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker-cli ca-certificates curl gnupg git \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends "docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm" \
      docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/* \
 && docker --version \
 && docker buildx version \
 && test "$(docker compose version --short)" = "${COMPOSE_VERSION}"
RUN pip install --no-cache-dir pyyaml==6.0.2 \
 && mkdir -m 1777 /tmp/follow-home
COPY runner.sh /usr/local/bin/follow-runner
CMD ["bash", "/usr/local/bin/follow-runner"]
