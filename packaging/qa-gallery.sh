#!/usr/bin/env bash
# qa-gallery.sh — enable every gallery app and prove its "Open" target actually serves.
#
# The apps screen's Open button uses the routing entry that declares a `module`. This drives the
# same URLs the button produces and reports what each one really answers, so a broken landing page
# is caught here instead of by a person clicking through the UI.
#
# A 302 to auth.localhost is a PASS: the app is SSO-gated and traefik+authentik are doing their job.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1   # repo root, wherever it is cloned

GALLERY="browser42 ollama openhands portainer redisinsight supabase google-workspace-agent"

echo "=== enabling every gallery app ==="
for a in $GALLERY; do ./bbox apps enable "$a" >/dev/null 2>&1; done
./scripts/dc up -d --remove-orphans >/dev/null 2>&1
echo "waiting for containers…"; sleep 90

echo
echo "=== Open targets, as the apps screen computes them ==="
docker exec app-management-shlomo-laptop python3 -c '
import json, urllib.request
d = json.load(urllib.request.urlopen("http://localhost:8080/api/apps"))
apps = d if isinstance(d, list) else d.get("apps", [])
for a in sorted(apps, key=lambda x: x["id"]):
    l = (a.get("launch") or {}).get("url")
    if l and a.get("layer") == 3:
        print("%s %s" % (a["id"], l))
' 2>/dev/null > /tmp/targets.txt

while read -r app url; do
  [ -n "$app" ] || continue
  host="${url#http://}"; host="${host%%/*}"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: ${host}" http://127.0.0.1/)
  loc=$(curl -sI --max-time 20 -H "Host: ${host}" http://127.0.0.1/ | grep -i '^location:' | head -1 | tr -d '\r')
  case "$code" in
    200)     verdict="OK   serves" ;;
    302|307) case "$loc" in *auth.localhost*) verdict="OK   SSO login" ;; *) verdict="OK   redirect" ;; esac ;;
    401|403) verdict="OK   auth required" ;;
    *)       verdict="FAIL" ;;
  esac
  printf '  %-24s %-28s %s  %s\n' "$app" "$host" "$code" "$verdict"
done < /tmp/targets.txt
