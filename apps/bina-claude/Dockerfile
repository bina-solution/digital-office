# bina-claude — the agent.v1 adapter over the official Claude Desktop app (Dockerfile.desktop). Bina Claude is
# ONLY that app, with ONE sign-in; there is no terminal and no Claude Code CLI here (DGO-1684). See
# docker-compose.yml.
FROM node:24-bookworm-slim

# ── the office's hands ─────────────────────────────────────────────────────────────────────────
# The same hands bina-ds has (its Dockerfile says why, line by line): Claude here operates the office
# through `./bbox` against the checkout docker-compose.yml mounts at its HOST path, over the engine's
# socket — the Docker CLI + compose plugin PINNED to the engine's versions (28.5.2 / 2.40.3; Docker 29
# breaks traefik v3.3), python3 + PyYAML for the compiler and `bbox agent`, git, ssh, jq/curl.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git openssh-client python3 python3-yaml jq bash procps less \
      rsync unzip ripgrep locales \
 && sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen && locale-gen \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update && apt-get install -y --no-install-recommends \
      docker-ce-cli=5:28.5.2-1~debian.12~bookworm \
      docker-compose-plugin=2.40.3-1~debian.12~bookworm \
      docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

COPY adapter /opt/bina-claude/adapter
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# THE COMPOSE IN THIS IMAGE IS THE HOST'S — bina-ds's Dockerfile says why (gate G74).
ARG COMPOSE_VERSION=2.40.3
RUN [ "$(docker compose version --short)" = "${COMPOSE_VERSION}" ] || { \
      apt-get update \
   && apt-get install -y --no-install-recommends --allow-downgrades "docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm" \
   && rm -rf /var/lib/apt/lists/* \
   && test "$(docker compose version --short)" = "${COMPOSE_VERSION}"; }

ENV HOME=/data/home BINA_CLAUDE_STATE=/data/bina-claude LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 NODE_ENV=production
VOLUME ["/data"]
EXPOSE 3091
ENTRYPOINT ["/entrypoint.sh"]
