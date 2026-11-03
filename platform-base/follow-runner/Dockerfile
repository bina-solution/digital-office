# follow-runner — the image a follow cycle runs in (runner.sh): what `./bbox run` needs from inside a container, and no more.
# The docker CLI and the compose plugin pinned as app-management pins them (compose's version is part of what the
# compiled files mean), git for the take itself, and PyYAML for the compiler (platform/manager/reconcile.py).
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
 && rm -rf /var/lib/apt/lists/* \
 && docker --version \
 && test "$(docker compose version --short)" = "${COMPOSE_VERSION}"
RUN pip install --no-cache-dir pyyaml==6.0.2 \
 && mkdir -m 1777 /tmp/follow-home
COPY runner.sh /usr/local/bin/follow-runner
CMD ["bash", "/usr/local/bin/follow-runner"]
