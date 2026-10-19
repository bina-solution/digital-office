#!/bin/bash
# Manual log collection - collects last 24h from all containers
# Usage: ./scripts/collect-logs.sh

set -e
cd "$(dirname "$0")/.."

LOGS_DIR="./development/system-logs"
DATE=$(date +%Y-%m-%d)
RETENTION=10
SERVICES="traefik portainer n8n n8n-postgres redis redisinsight apitools chat ollama open-webui"

for s in $SERVICES; do
    mkdir -p "$LOGS_DIR/$s"
    CID=$(docker ps -qf "name=$s" 2>/dev/null | head -1)
    [ -n "$CID" ] && docker logs --since 24h "$CID" >> "$LOGS_DIR/$s/${DATE}.log" 2>&1 && echo "✓ $s" || echo "✗ $s"
done

find "$LOGS_DIR" -name "*.log" -mtime +$RETENTION -delete 2>/dev/null || true
echo "Done"
