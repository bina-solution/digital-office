#!/usr/bin/env bash
# qa-fix-loop.sh — enable every gallery app, repair what blocks it, prove every Open target serves.
#
# Repairs two failure modes seen for real:
#   * a STRANDED container from an earlier enable/disable cycle blocks recreation with
#     "container name is already in use" — compose will not adopt it, so it is removed by name.
#   * a newly enabled app adds an authentik proxy provider the embedded outpost has not synced,
#     so its host 404s until bootstrap re-runs.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1   # repo root, wherever it is cloned

GALLERY="browser42 redisinsight supabase portainer"

echo "=== 1. enable (archived apps need the disposition cleared, not just enabled) ==="
# Delegated to reconcile's set-state — the one writer of platform.state.yaml. This used to carry a
# fourth private copy of the regex, whose comment claimed `bbox apps enable` could not transition
# out of `archived`. It can: both now replace the whole brace block through the same function.
for a in ${GALLERY}; do
  python3 platform/manager/reconcile.py set-state --app "$a" --state enabled --by qa \
    || echo "  $a: not in platform.state.yaml"
done
python3 platform/manager/reconcile.py render >/dev/null 2>&1

echo "=== 2. up, removing ONLY containers that actually block recreation ==="
# Removing every non-running container was too blunt: it deleted `mail` mid-restart and
# `glitchtip-migrate`, a run-once job that exits 0 BY DESIGN. Only a name conflict reported by
# compose justifies a removal, so parse the conflict and remove exactly that name.
for attempt in 1 2; do
  out="$(./scripts/dc up -d --remove-orphans 2>&1)"
  conflicts="$(printf '%s' "${out}" | grep -oE 'The container name "/[^"]+"' | sed 's|.*"/||; s|"||' | sort -u)"
  [ -n "${conflicts}" ] || break
  for name in ${conflicts}; do
    docker rm -f "${name}" >/dev/null 2>&1 && echo "  removed conflicting ${name}"
  done
done
printf '%s' "${out}" | grep -iE "error" | head -4
sleep 75

echo "=== 3. sync SSO for newly enabled apps ==="
docker restart authentik-bootstrap-shlomo-laptop >/dev/null 2>&1; sleep 80
docker restart authentik-server-shlomo-laptop   >/dev/null 2>&1; sleep 85

echo "=== 4. Open targets ==="
fail=0
for h in browser42 redisinsight portainer supabase-studio hello-bina drive mail my-docs chat apitools incoming-documents; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  loc=$(curl -sI --max-time 25 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null | tr -d '\r' \
        | awk 'tolower($1)=="location:"{print $2}' | head -1)
  case "${code}" in
    200)     v="OK   serves" ;;
    302|307) case "${loc}" in *auth.localhost*) v="OK   SSO login" ;; *) v="OK   -> ${loc}" ;; esac ;;
    401|403) v="OK   auth required" ;;
    *)       v="FAIL"; fail=$((fail+1)) ;;
  esac
  printf '  %-20s %-4s %s\n' "${h}" "${code}" "${v}"
done
echo
echo "failures: ${fail}"
exit "${fail}"
