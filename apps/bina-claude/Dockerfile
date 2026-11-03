# bina-claude — the official Claude Code CLI as an office app, served as one container. See docker-compose.yml.
FROM node:24-bookworm-slim

# ── the office's hands ─────────────────────────────────────────────────────────────────────────
# The same hands bina-ds has (its Dockerfile says why, line by line): Claude here operates the office
# through `./bbox` against the checkout docker-compose.yml mounts at its HOST path, over the engine's
# socket — the Docker CLI + compose plugin PINNED to the engine's versions (28.5.2 / 2.40.3; Docker 29
# breaks traefik v3.3), python3 + PyYAML for the compiler and `bbox agent`, git, ssh, jq/curl.
# ttyd + tmux are the UI: a web terminal on ONE tmux session, so the console's tile and
# `./bbox bina-claude attach` are the same screen.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git openssh-client python3 python3-yaml jq bash procps less \
      rsync unzip ripgrep tmux locales \
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

# ttyd is not in Debian 12; its own release is one static binary per architecture, pinned by checksum
# (the release's SHA256SUMS, 1.7.7).
ARG TTYD_VERSION=1.7.7
RUN case "$(dpkg --print-architecture)" in \
      arm64) a=aarch64; s=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;; \
      amd64) a=x86_64;  s=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;; \
      *) echo "no ttyd build for $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${a}" \
 && echo "${s}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd && ttyd --version

# Claude Code, pinned to the release channel's `stable` tag (npm dist-tag, 2026-10-31). A new version
# is a deliberate bump of this line, never an auto-update inside a running office:
# DISABLE_AUTOUPDATER=1 in docker-compose.yml.
ARG CLAUDE_CODE_VERSION=2.1.309
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && npm cache clean --force \
 && claude --version

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
EXPOSE 7681 3091
ENTRYPOINT ["/entrypoint.sh"]
