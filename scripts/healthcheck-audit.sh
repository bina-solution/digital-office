#!/usr/bin/env bash
# Does every healthcheck's binary actually exist in the image it probes?
#
# chat's probe was `curl -f http://localhost:3000` on a node:22-slim image with no
# curl. Every check failed with "exec: curl: executable file not found", so the container reported
# unhealthy forever while the app served fine — a probe reporting on itself. That is silent, and it
# is the kind of thing that is only ever noticed on a machine with no warm image cache.
set -u
fail=0
for c in $(docker ps --format '{{.Names}}'); do
  t=$(docker inspect "$c" --format '{{json .Config.Healthcheck.Test}}' 2>/dev/null)
  [ "$t" = "null" ] && continue
  for b in curl wget nc python python3 node psql pg_isready redis-cli; do
    case "$t" in
      *"\"$b\""*|*"$b "*)
        if docker exec "$c" sh -c "command -v $b" >/dev/null 2>&1; then
          printf 'OK       %-40s %s\n' "$c" "$b"
        else
          printf 'MISSING  %-40s %s   <-- probe can never pass\n' "$c" "$b"
          fail=1
        fi
        break ;;
    esac
  done
done
exit $fail
