#!/usr/bin/env bash
# qa-consolidation.sh — is every app declared the same way, and does install-on-demand round-trip?
#
# A file, never an inline `wsl -- bash -lc` loop: the outer Git Bash expands $vars and mangles
# for-loops, which silently turned earlier probes into "command not found" instead of results.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1   # repo root, wherever it is cloned

echo "=== 1. install-on-demand round-trip (portainer) ==="
./bbox apps enable portainer >/dev/null 2>&1
./scripts/dc up -d --remove-orphans >/dev/null 2>&1
sleep 40
up=$(docker ps --format '{{.Names}}' | grep -c portainer)
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H 'Host: portainer.localhost' http://127.0.0.1/)
echo "  after enable : containers=${up} http=${code}"

./bbox apps disable portainer >/dev/null 2>&1
./scripts/dc up -d --remove-orphans >/dev/null 2>&1
sleep 25
down=$(docker ps --format '{{.Names}}' | grep -c portainer)
echo "  after disable: containers=${down}"

echo
echo "=== 2. declaration consistency across every app ==="
python3 - <<'PY'
import json, pathlib, yaml
REPO = pathlib.Path('.')
rows, issues = [], []
for m in sorted(REPO.glob('platform-base/*/app.json')) + sorted(REPO.glob('apps/*/app.json')):
    a = json.loads(m.read_text(encoding='utf-8'))
    aid, layer = a['id'], a.get('layer')
    routing = a.get('routing') or []
    ui = [r for r in routing if r.get('module')]
    gated = [r for r in routing if r.get('auth') == 'sso']
    # every SSO-gated route needs an sso block, or authentik has nothing to gate with
    for r in gated:
        if 'sso' not in r:
            issues.append(f"{aid}: host '{r['host']}' auth=sso but no sso: block")
    # a UI route should be reachable: it needs a host
    for r in ui:
        if not r.get('host'):
            issues.append(f"{aid}: module route has no host")
    # title/summary must be {he,en} objects — a plain string crashes the apps screen
    for k in ('title', 'summary'):
        v = a.get(k)
        if v is not None and not isinstance(v, dict):
            issues.append(f"{aid}: {k} must be an object with he/en, got {type(v).__name__}")
        elif isinstance(v, dict) and not ('he' in v and 'en' in v):
            issues.append(f"{aid}: {k} is missing he or en")
    rows.append((aid, layer, a.get('kind'), len(routing), len(ui), len(gated)))

print(f"  {'app':<24} {'L':<3} {'kind':<10} {'routes':<7} {'ui':<4} {'sso'}")
for aid, layer, kind, nr, nu, ng in rows:
    print(f"  {aid:<24} {layer:<3} {str(kind):<10} {nr:<7} {nu:<4} {ng}")
print()
if issues:
    print(f"  {len(issues)} inconsistency(ies):")
    for i in issues:
        print(f"    - {i}")
else:
    print("  no inconsistencies")
PY
