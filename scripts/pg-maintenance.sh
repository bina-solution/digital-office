#!/usr/bin/env bash
# PostgreSQL maintenance script for n8n database
# Reclaims TOAST bloat from execution_data and other large tables
# Run weekly during low-activity hours (e.g., Saturday 3 AM)
#
# Schedule via crontab:
#   0 3 * * 6 /root/deployment-hacohen/scripts/pg-maintenance.sh >> /var/log/pg-maintenance.log 2>&1

set -euo pipefail

# Derived, not literal: hardcoding one deployment's container makes this script silently
# maintain the WRONG database on any other deployment — or, more often, exit at the first
# docker exec because the container does not exist.
CONTAINER="${PG_CONTAINER:-n8n-postgres-${DEPLOYMENT_NAME:-bina-deployment}}"
DB_USER="hacohen"
DB_NAME="n8n"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TIMESTAMP] $1"; }

# Check container is running
if ! docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    log "ERROR: Container $CONTAINER is not running. Skipping maintenance."
    exit 1
fi

log "=== Starting PostgreSQL maintenance ==="

# 1. Report current sizes
log "Current table sizes:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
    SELECT c.relname AS table_name,
           pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
           pg_size_pretty(pg_relation_size(c.reltoastrelid)) AS toast
    FROM pg_class c
    WHERE c.relkind = 'r'
      AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
      AND pg_total_relation_size(c.oid) > 10485760
    ORDER BY pg_total_relation_size(c.oid) DESC;
"

# 2. VACUUM FULL on execution_data (the main bloat source)
log "Running VACUUM FULL on execution_data..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "VACUUM FULL execution_data;"
log "VACUUM FULL execution_data complete."

# 3. VACUUM FULL on execution_entity
log "Running VACUUM FULL on execution_entity..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "VACUUM FULL execution_entity;"
log "VACUUM FULL execution_entity complete."

# 4. Regular VACUUM ANALYZE on all tables (lightweight, updates query planner stats)
log "Running VACUUM ANALYZE on all tables..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "VACUUM ANALYZE;"
log "VACUUM ANALYZE complete."

# 5. Report final sizes
log "Post-maintenance table sizes:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
    SELECT c.relname AS table_name,
           pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
           pg_size_pretty(pg_relation_size(c.reltoastrelid)) AS toast
    FROM pg_class c
    WHERE c.relkind = 'r'
      AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
      AND pg_total_relation_size(c.oid) > 1048576
    ORDER BY pg_total_relation_size(c.oid) DESC;
"

log "=== PostgreSQL maintenance complete ==="
