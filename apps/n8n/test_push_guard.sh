#!/usr/bin/env bash
# test_push_guard.sh — an app this office has switched OFF is not pushed into the live n8n.
#
#     bash apps/n8n/test_push_guard.sh
#
# DGO-531's neighbour, and it is a near-miss rather than a theory: on 2026-10-11 `bbox n8n push indox`
# on the HP office — where platform.state.yaml says `indox: disabled` — created SIXTY-NINE workflows in
# the live instance and activated sixty-one of them (the INDOX scheduler, every extractor, the sync
# engines). The office was handed automations its own declaration says are not part of it, and the
# undo was a delete of every workflow whose createdAt was that minute. `bbox n8n push all` never had
# the hole (the compiler filters by enablement); the SCOPED verb asks "where are this app's
# blueprints", which is not the same question as "should they run here".
#
# The rule now stands at both scoped doors (hooks/push-app, and hooks/push --app), and this asks the
# office's own state file WHICH app to test with — so the test says the same thing on an office that
# has indox on and on one that has it off. A run with nothing disabled says so and passes: there is no
# refusal to prove where nothing is declared off.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
STATE="${ROOT}/platform.state.yaml"
fails=0
say() { printf '%s  %s\n' "$1" "$2"; }

[ -f "${STATE}" ] || { say "SKIP" "no platform.state.yaml — nothing declares an app off here"; exit 0; }

# The app to test with is one BOTH doors must refuse: switched off by its state line, declaring automations,
# and not in the compiler's list of the apps whose workflows this office holds. The pulled-in workflow engine
# (n8n `state: disabled` on the HP and the Mac, while bina-ds pulls it in) is in that list and is pushed: a
# test that picked it would push into the live n8n and restart it (the second reader of DGO-998). With no
# list, nothing is excluded, and the doors refuse anyway — a compiler that cannot answer refuses.
LISTED="$( cd "${ROOT}" && python3 platform/manager/reconcile.py blueprints 2>/dev/null | tr -d '\r' | cut -f1 | tr '\n' ' ' )"
OFF="$(python3 -c 'import json, os, sys, yaml
state, root, listed = sys.argv[1], sys.argv[2], set(sys.argv[3].split())
apps = (yaml.safe_load(open(state, encoding="utf-8")) or {}).get("apps") or {}
def off(v):
    return isinstance(v, dict) and not str(v.get("workflows") or "").strip() and (
        str(v.get("state") or "").strip().lower() in ("disabled", "archived") or str(v.get("enabled")).strip().lower() == "false")
def automations(a):
    for top in ("apps", "platform-base"):
        p = os.path.join(root, top, a, "app.json")
        if os.path.exists(p):
            return bool(((json.load(open(p, encoding="utf-8")).get("blueprints") or {}).get("n8n") or "").strip())
    return False
cand = sorted(a for a, v in apps.items() if off(v) and a not in listed and automations(a))
print(cand[0] if cand else "")' "${STATE}" "${ROOT}" "${LISTED}" 2>/dev/null || true)"

if [ -z "${OFF}" ]; then
  say "SKIP" "no app here is switched off, declares automations, and is left out of the compiler's list — there is no refusal to prove"
  exit 0
fi

# The scoped door refuses BEFORE it compiles or talks to n8n, so this needs no engine and no key.
out="$(bash "${HERE}/hooks/push-app" "${OFF}" --dry-run 2>&1)"; rc=$?
if [ "${rc}" -eq 0 ]; then
  say "FAIL" "hooks/push-app pushed '${OFF}' although the office has it disabled: ${out##*$'\n'}"
  fails=$((fails + 1))
elif ! grep -q "disabled in platform.state.yaml" <<<"${out}"; then
  say "FAIL" "hooks/push-app refused '${OFF}' for the wrong reason: ${out##*$'\n'}"
  fails=$((fails + 1))
else
  say "PASS" "hooks/push-app refuses '${OFF}' (disabled), naming platform.state.yaml"
fi

out2="$(bash "${HERE}/hooks/push" --app "${OFF}" 2>&1)"; rc2=$?
if [ "${rc2}" -eq 0 ] || ! grep -q "disabled in platform.state.yaml" <<<"${out2}"; then
  say "FAIL" "hooks/push --app '${OFF}' did not refuse from the second door (rc=${rc2})"
  fails=$((fails + 1))
else
  say "PASS" "hooks/push --app refuses '${OFF}' too"
fi

if [ "${fails}" -eq 0 ]; then
  echo; echo "0 failing"; exit 0
fi
echo; echo "${fails} failing"; exit 1
