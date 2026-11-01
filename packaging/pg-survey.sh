#!/usr/bin/env bash
# pg-survey.sh — what the four Postgres instances actually hold, before consolidating them.
#
# A file, not an inline `wsl -- bash -lc` command: the outer Git Bash mangles $( ) and loops.
set -uo pipefail
D=shlomo-laptop

probe() {
  local c="$1" u="$2"
  local n="${c}-${D}"
  docker ps --format '{{.Names}}' | grep -qx "${n}" || { printf '  %-20s NOT RUNNING\n' "${c}"; return; }
  local ver dbs sz
  ver=$(docker exec "${n}" psql -U "${u}" -At -c 'show server_version' 2>/dev/null | head -1)
  dbs=$(docker exec "${n}" psql -U "${u}" -At -c \
        "select datname from pg_database where datistemplate=false order by 1" 2>/dev/null | tr '\n' ' ')
  sz=$(docker exec "${n}" psql -U "${u}" -At -c \
        "select pg_size_pretty(sum(pg_database_size(datname))) from pg_database where datistemplate=false" 2>/dev/null | head -1)
  printf '  %-20s pg=%-8s size=%-8s dbs: %s\n' "${c}" "${ver:-?}" "${sz:-?}" "${dbs:-?}"
}

echo "=== the four clusters ==="
probe supabase-db      postgres
probe authentik-postgres authentik
probe glitchtip-postgres glitchtip
probe n8n-postgres     n8n

echo
echo "=== image cost of the duplication ==="
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' \
  | grep -E '^(postgres|supabase/postgres):' | sort -u | sed 's/^/  /'
