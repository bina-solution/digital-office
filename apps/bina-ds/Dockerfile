# bina-ds — a customized DeepSeek Harness (MIT), served as one container. See docker-compose.yml.
FROM node:24-bookworm-slim

# pnpm is what the harness uses to manage a profile's plugins (`dsh plugin` shells out to it).
RUN corepack enable && corepack prepare pnpm@10 --activate

# ── the office's hands ─────────────────────────────────────────────────────────────────────────
# The agent that lives here (עזריה, see harness/profile/agents/) operates the office itself: it runs
# `./bbox`, `./scripts/dc`, reconcile.py and git against the checkout that docker-compose.yml
# mounts at its HOST path, over the engine's socket. So the container carries exactly what bbox
# needs on a Linux host — the Docker CLI + compose plugin PINNED to the engine's own versions
# (28.5.2 / 2.40.3, the same majors the VPS and the WSL/Lima engines run; Docker 29 breaks traefik
# v3.3, CLAUDE.md), python3 + PyYAML for the compiler, git, ssh for the machines it manages, jq/curl.
# Owner decision 2026-09-17: the agent has full access to the deployment — this is that access.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git openssh-client python3 python3-yaml jq bash procps less \
      rsync unzip \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update && apt-get install -y --no-install-recommends \
      docker-ce-cli=5:28.5.2-1~debian.12~bookworm \
      docker-compose-plugin=2.40.3-1~debian.12~bookworm \
      docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# The profile project: stock dsh pinned from npm + the Bina plugins from this tree.
# Same layout as the repo (harness/profile next to plugins/), so the profile's `file:../../plugins/*`
# dependencies resolve identically in the image and in a checkout.
WORKDIR /opt/bina
COPY plugins ./plugins
# The install layer depends on the manifest alone (and on the plugins it links by `file:`). The rest
# of the profile — cordis.patch.yml, agent-presets — lands AFTER the install, so editing a row or a
# preset never re-runs `pnpm install`, the heaviest step of this image (a full harness install; on
# the 5 GB engine it is what wedged the daemon on 2026-09-30).
COPY harness/profile/package.json ./harness/profile/package.json
# The Hebrew bundle is generated from its JSON dictionaries; the build refuses key-set drift.
RUN cd plugins/locale-he && node build-client.mjs
RUN cd harness/profile && pnpm install --prod --no-frozen-lockfile && test -x node_modules/.bin/dsh
COPY harness/profile ./harness/profile
# The one node-side customization (see harness/customize.sh): trust the edge's identity header.
COPY harness/customize.sh ./harness/customize.sh
RUN sh harness/customize.sh harness/profile

# The agent.v1 adapter (ai/context/agent-contract.md): a sibling process started by the entrypoint.
COPY adapter /opt/bina/adapter
COPY harness/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# THE COMPOSE IN THIS IMAGE IS THE HOST'S. The agent's `./bbox run` brings containers up, and a
# container is the hash of what compose made of its service — another version than the host's makes
# another container of the same file, so the agent and `bbox run` on the host each re-created what
# the other had made. Whoever builds hands in the version its own compose has (docker-compose.yml
# `build.args`); the default is the one installed above, which is what the installers install
# (gate G74). LAST, and a no-op when they already agree: a host that runs another compose costs one
# small layer here, not a rebuild of everything above.
ARG COMPOSE_VERSION=2.40.3
RUN [ "$(docker compose version --short)" = "${COMPOSE_VERSION}" ] || { \
      apt-get update \
   && apt-get install -y --no-install-recommends --allow-downgrades "docker-compose-plugin=${COMPOSE_VERSION}-1~debian.12~bookworm" \
   && rm -rf /var/lib/apt/lists/* \
   && test "$(docker compose version --short)" = "${COMPOSE_VERSION}"; }

ENV DSH_HOME=/data/dsh DSH_PROFILE=bina DSH_PORT=3080 NODE_ENV=production
VOLUME ["/data/dsh"]
EXPOSE 3080
ENTRYPOINT ["/entrypoint.sh"]
