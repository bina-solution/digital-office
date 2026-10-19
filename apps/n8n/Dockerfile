# n8n version is centralized in .env as N8N_VERSION. Compose REQUIRES it (${N8N_VERSION:?...}) and
# passes it here as a build arg, so real deployments can't silently drift. The task-runners image
# (production/n8n/docker-compose.yml) uses the SAME N8N_VERSION — they MUST match.
# The default below is only a fallback for a bare `docker build` (not the sanctioned path); compose
# always overrides it with the required .env value.
ARG N8N_VERSION=2.0.3
FROM n8nio/n8n:${N8N_VERSION}

# Build the bina-solutions custom nodes. Only needs node/npm, which are present in the base image
# (incl. n8n's hardened 2.x images, which have NO apk and run as the `node` user).
#
# NOTE: earlier versions of this Dockerfile also `apk add`-ed sudo/python3/curl/bash and the gcloud
# SDK. Those were dropped: (a) no workflow references gcloud/gsutil/python (verified), and (b) n8n's
# 2.x hardened image removed apk so they can't be installed there anyway. If a future workflow truly
# needs a CLI tool, add it via a multi-stage builder (regular alpine) that COPYs the binary in —
# do NOT reintroduce `apk` against the hardened base.
COPY --chown=node:node ./extensions/bina-solutions-nodes /home/node/custom-extensions/bina-solutions-nodes
WORKDIR /home/node/custom-extensions/bina-solutions-nodes
RUN npm install --include=dev && npm run build

# n8n loads bina-solutions from here (also set via compose env N8N_CUSTOM_EXTENSIONS).
ENV N8N_CUSTOM_EXTENSIONS=/home/node/custom-extensions

# Bake the pinned community node packages the document pipeline depends on into a STAGING dir, and seed
# them into ~/.n8n/nodes on boot (see seed-community-nodes.sh). They MUST live in ~/.n8n/nodes (not
# N8N_CUSTOM_EXTENSIONS): nodes there resolve their peer deps (reflect-metadata/typedi — used by
# n8n-nodes-kv-storage) against n8n's runtime; from a separate custom-extensions tree they can't, and
# kv-storage fails to load. ~/.n8n is a runtime volume, hence the boot-time seed. Versions are pinned
# from the blueprint manifest (scripts/n8n-pull writes `community_nodes:` in blueprint.yml — keep in sync).
# PUPPETEER_SKIP_DOWNLOAD: the node loads without a bundled Chromium (it drives a remote browser).
# /opt is root-owned, so this layer runs as root, then hands ownership back to node.
#
# --legacy-peer-deps: every one of these packages declares `n8n-workflow: *` as a PEER, and npm 7+
# auto-installs peers — so this layer used to drag a second, mismatched n8n-workflow (2.16.0 next
# to n8n 2.17.4) into /opt/community-nodes, and with it @n8n/expression-runtime -> isolated-vm, a
# NATIVE module. On amd64 that went unnoticed (a prebuilt binary is picked up); on arm64 (Apple
# Silicon, the macOS engine) node-gyp tried to COMPILE it inside this hardened image, which has no
# Python, and the whole first bring-up died in `npm error gyp ERR! find Python` (2026-09-17).
# The peer is wrong to install anyway: nodes seeded into ~/.n8n/nodes resolve n8n-workflow from
# n8n's own runtime (that is the whole reason they live there, see the note above). Without the
# auto-peers the set has ZERO native modules and is ~60 MB smaller; the five nodes are unchanged.
USER root
RUN mkdir -p /opt/community-nodes && cd /opt/community-nodes \
 && npm init -y >/dev/null 2>&1 \
 && PUPPETEER_SKIP_DOWNLOAD=true npm install --omit=dev --legacy-peer-deps \
      n8n-nodes-puppeteer@1.5.0 \
      n8n-nodes-kv-storage@0.2.0 \
      n8n-nodes-globals@1.1.0 \
      n8n-nodes-tesseractjs@1.5.1 \
      n8n-nodes-pdfvector@0.8.3 \
      reflect-metadata@0.2.2 \
 && chown -R node:node /opt/community-nodes

# Seed wrapper: copies the baked community nodes into the (volume-backed) ~/.n8n/nodes if missing, then
# hands off to the stock entrypoint. Workers override entrypoint in compose but share the n8n_storage
# volume and start after main is healthy, so they inherit the seeded nodes.
COPY --chmod=0755 ./seed-community-nodes.sh /seed-community-nodes.sh
ENTRYPOINT ["tini", "--", "/seed-community-nodes.sh"]

USER node
WORKDIR /home/node
