#!/usr/bin/env bash
# qa-gallery-full.sh — enable every gallery app, bring it up, and probe its Open target.
#
# ENTIRELY a file, and it NEVER runs `git reset`. Both rules exist because of real failures:
#   * `wsl -- bash -lc '... for a in $LIST ...'` lets the OUTER Git Bash expand the variables, so
#     the loop enabled nothing and every app then "failed" its probe.
#   * platform.state.yaml is TRACKED, so a `git reset --hard` between enabling and probing reverts
#     every app to disabled — and the next `--remove-orphans` deletes the containers. Three QA
#     rounds were invalidated this way before anyone noticed the platform was never at fault.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1   # repo root, wherever it is cloned

GALLERY="browser42 redisinsight portainer supabase"

echo "=== enable ==="
for a in ${GALLERY}; do
  ./bbox apps enable "${a}" 2>&1 | head -1
done

echo "=== state ==="
grep -E "browser42|redisinsight|portainer|supabase:" platform.state.yaml | sed 's/^/  /'

echo "=== up ==="
./scripts/dc up -d --remove-orphans 2>&1 | tail -2
echo "waiting…"; sleep 75

echo "=== SSO re-register (enabling an app adds a provider the outpost must sync) ==="
docker restart authentik-bootstrap-shlomo-laptop >/dev/null 2>&1; sleep 75
docker restart authentik-server-shlomo-laptop   >/dev/null 2>&1; sleep 85

echo "=== containers ==="
docker ps --format '{{.Names}}' | grep -E 'browser42|redisinsight|portainer|studio|kong' | sed 's/^/  /'

echo "=== Open targets ==="
fail=0
for h in browser42 redisinsight portainer supabase-studio hello-bina drive mail my-docs chat apitools; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  loc=$(curl -sI --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null | tr -d '\r' \
        | awk 'tolower($1)=="location:"{print $2}' | head -1)
  case "${code}" in
    200)     v="OK   serves" ;;
    302|307) case "${loc}" in *auth.localhost*) v="OK   SSO login" ;; *) v="OK   -> ${loc}" ;; esac ;;
    401|403) v="OK   auth required" ;;
    *)       v="FAIL"; fail=$((fail+1)) ;;
  esac
  printf '  %-18s %-4s %s\n' "${h}" "${code}" "${v}"
done
echo
echo "failures: ${fail}"
