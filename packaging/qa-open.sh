#!/usr/bin/env bash
# qa-open.sh — probe every gallery app's Open target. Runs INSIDE the distro as a file, because
# `wsl -- bash -lc '...'` lets the outer Git Bash expand $vars and mangles loops.
set -uo pipefail
fail=0
for h in browser42 hello-bina ollama openhands portainer redisinsight supabase-studio drive mail my-docs chat incoming-documents apitools; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  loc=$(curl -sI --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}' | head -1)
  case "${code}" in
    200)      v="OK   serves" ;;
    302|307)  case "${loc}" in *auth.localhost*) v="OK   SSO login" ;; *) v="OK   -> ${loc}" ;; esac ;;
    401|403)  v="OK   auth required" ;;
    *)        v="FAIL"; fail=$((fail+1)) ;;
  esac
  printf '  %-20s %-4s %s\n' "${h}" "${code}" "${v}"
done
echo
echo "failures: ${fail}"
