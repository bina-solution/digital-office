#!/usr/bin/env bash
# pg-extensions.sh — which extensions are INSTALLED (not merely available) in each cluster?
#
# This decides the consolidation target. supabase/postgres is 1.96 GB versus 454 MB for vanilla
# postgres:17 — but only if nothing depends on the extensions supabase's fork bundles. "Available"
# is irrelevant; only `pg_extension` (actually created) can break a restore.
set -uo pipefail
D=shlomo-laptop

for pair in "supabase-db:postgres" "authentik-postgres:authentik" "glitchtip-postgres:glitchtip" "n8n-postgres:n8n"; do
  c="${pair%%:*}"; u="${pair##*:}"
  n="${c}-${D}"
  docker ps --format '{{.Names}}' | grep -qx "${n}" || { echo "== ${c}: not running"; continue; }
  echo "== ${c} (as ${u})"
  docker exec "${n}" psql -U "${u}" -At -c \
    "select string_agg(extname, ', ' order by extname) from pg_extension" 2>/dev/null | sed 's/^/     /'
  # per-database, since extensions are per-db not per-cluster
  for db in $(docker exec "${n}" psql -U "${u}" -At -c \
      "select datname from pg_database where datistemplate=false" 2>/dev/null); do
    ext=$(docker exec "${n}" psql -U "${u}" -d "${db}" -At -c \
      "select string_agg(extname, ', ' order by extname) from pg_extension where extname not in ('plpgsql')" 2>/dev/null)
    [ -n "${ext}" ] && printf '     %-14s %s\n' "${db}:" "${ext}"
  done
done

echo
echo "== non-default ROLES (these must be recreated in a consolidated cluster) =="
docker exec "supabase-db-${D}" psql -U postgres -At -c \
  "select string_agg(rolname, ', ' order by rolname) from pg_roles where rolname not like 'pg\_%'" 2>/dev/null | sed 's/^/     /'
