#!/usr/bin/env bash
# READ-ONLY census of the six drive folders (two source families x 3 states), measured through
# the SAME path the sync engine uses: drive /list with the live 6-month createdAfter bound.
# No writes. Safe to re-run.
set -u
D="docker -H unix:///run/bbox-docker.sock"
CONN="drive_google_service_account-ea660043"
CUT=$(date -u -d '6 months ago' +%Y-%m-%dT%H:%M:%SZ)
echo "createdAfter (OldDocumentMonthsBack=6): $CUT"
echo

probe () {
  local label="$1" fid="$2" lim="$3" ca="$4"
  local body
  if [ -n "$ca" ]; then
    body="{\"folderId\":\"$fid\",\"limit\":$lim,\"whatToSearch\":\"files\",\"connection_id\":\"$CONN\",\"createdAfter\":\"$ca\"}"
  else
    body="{\"folderId\":\"$fid\",\"limit\":$lim,\"whatToSearch\":\"files\",\"connection_id\":\"$CONN\"}"
  fi
  local t0 t1 out n
  t0=$(date +%s%3N)
  out=$($D exec -i drive-shlomo-laptop python3 -c '
import json,sys,urllib.request
b=sys.stdin.read().encode()
r=urllib.request.Request("http://127.0.0.1:8975/list",data=b,headers={"Content-Type":"application/json"})
try:
    d=json.load(urllib.request.urlopen(r,timeout=300))
    print(len(d.get("files") or []))
except Exception as e:
    print("ERR "+type(e).__name__+" "+str(e)[:160])
' <<<"$body" 2>&1 | tail -1)
  t1=$(date +%s%3N)
  printf '%-46s limit=%-6s window=%-4s -> %-10s (%sms)\n' "$label" "$lim" "${ca:+6m}${ca:+ }${ca:-none}" "$out" "$((t1-t0))"
}

echo "=== SCANNED family ==="
probe "to_sync  1stuMS.. srukot-lifney-shemot" 1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P 20000 "$CUT"
probe "synced   1YpapJ.. srukot-hitzliach"     1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu 20000 "$CUT"
probe "failed   1m25Rd.. srukot-nichshal(B)"   1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2 20000 "$CUT"
probe "REGISTRY-failed 11rj5z.. acharei-shemot" 11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb 20000 "$CUT"
echo
echo "=== CHAT-EXPORT family ==="
probe "to_sync  1DYzDE.. yetzu-chat-lifney"    1DYzDE5T3c2PGFOfNwnmCP3jjSqr2DiBx 20000 "$CUT"
probe "synced   1xthre.. yetzu-chat-acharei"   1xthreeBl1VD-5uN9PFu9Zi-0IABQDwst 20000 "$CUT"
probe "failed   1PYaVJ.. yetzu-chat-nichshal"  1PYaVJ4dKdOl1iGJlVKFT0pzJ_Rs2mYNL 20000 "$CUT"
echo
echo "=== unbounded (no window) totals, for headroom sizing ==="
probe "synced   1YpapJ.. FULL"                 1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu 20000 ""
probe "synced   1xthre.. FULL"                 1xthreeBl1VD-5uN9PFu9Zi-0IABQDwst 20000 ""
