#!/bin/sh
# Seed baked community node packages into the (volume-backed) ~/.n8n/nodes on boot, if missing, then
# hand off to the stock n8n entrypoint. Idempotent: skips when already seeded. The packages must live
# in ~/.n8n/nodes (not N8N_CUSTOM_EXTENSIONS) so their peer deps (reflect-metadata/typedi) resolve
# against n8n's runtime — see production/n8n/Dockerfile.
NODES_DIR="/home/node/.n8n/nodes"
if [ -d /opt/community-nodes/node_modules ] && [ ! -d "$NODES_DIR/node_modules/n8n-nodes-kv-storage" ]; then
  echo "[seed-community-nodes] seeding baked community nodes -> $NODES_DIR"
  mkdir -p "$NODES_DIR/node_modules"
  cp -R /opt/community-nodes/node_modules/. "$NODES_DIR/node_modules/" 2>/dev/null || true
  cp /opt/community-nodes/package.json "$NODES_DIR/package.json" 2>/dev/null || true
fi
exec /docker-entrypoint.sh "$@"
