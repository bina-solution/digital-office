#!/usr/bin/env bash
# test_wrap_where.sh — `bbox n8n push|pull` work on a host with no node (DGO-1746).
#
#     bash apps/n8n/test_wrap_where.sh
#
# Measured on Exampleu's office, 2026-11-10: `bbox n8n push` minted the API key and then died — «no `node` on
# this host, and blueprints are TypeScript» — although the office's own n8n container runs node. Only
# hooks/push had a second path (DGO-994's compile_in_engine); push-app, pull and pull-app called the host's
# node. Two checks:
#   1. no n8n hook runs wrap.mjs with the host's node itself: every run goes through tooling/wrap.sh's
#      wrap_run (five call sites did not, on the code of that day);
#   2. wrap_run on a host with no node runs the verb INSIDE the container and brings its output back —
#      driven here with a stand-in `docker` whose container is a directory, and a stand-in wrap.mjs.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fails=0
say() { printf '%s  %s\n' "$1" "$2"; }

# ── 1. every wrap.mjs run goes through wrap_run ─────────────────────────────────────────────────────────
direct="$(grep -nE '"\$\(bbox_node\)"|\$\{_node\}" "\$\{WRAP\}"' "${HERE}"/hooks/* 2>/dev/null || true)"
if [ -z "${direct}" ]; then
  say PASS "no hook runs wrap.mjs with the host's node directly ($(ls "${HERE}"/hooks | wc -l | tr -d ' ') hooks read)"
else
  say FAIL "hooks that run wrap.mjs with the host's node only:"; printf '        %s\n' "${direct}"; fails=$((fails + 1))
fi
for h in push push-app pull pull-app; do
  if grep -q 'tooling/wrap.sh' "${HERE}/hooks/${h}" && grep -q 'wrap_run ' "${HERE}/hooks/${h}"; then
    say PASS "hooks/${h} runs wrap.mjs through wrap_run"
  else
    say FAIL "hooks/${h} does not source tooling/wrap.sh and call wrap_run"; fails=$((fails + 1))
  fi
done

# ── 2. no node here: the verb runs in the container, and its output comes back ────────────────────────
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
CROOT="${T}/container"; mkdir -p "${CROOT}/tmp" "${T}/tooling" "${T}/src" "${T}/out"
CALLS="${T}/calls"; : > "${CALLS}"
printf 'stand-in\n' > "${T}/tooling/wrap.mjs"
printf 'const x = 1;\n' > "${T}/src/abc.workflow.ts"
inside() { printf '%s' "${1//\/tmp\//${CROOT}/tmp/}"; }   # a path in the container, as a path here
docker() {   # docker exec [-i] [-e K=V] [-w dir]… <container> <command…>
  [ "$1" = exec ] || return 99; shift
  local opts=""
  while [ $# -gt 0 ] && [ "${1#-}" != "$1" ]; do case "$1" in -e|-w) opts="${opts} $1 $2"; shift 2 ;; *) shift ;; esac; done
  local who="$1"; shift
  echo "container=${who}${opts:+ [${opts# }]} $*" >> "${CALLS}"
  case "$1" in
    sh) bash -c "$(inside "$3")" ;;
    tar) shift; local a=() d; while [ $# -gt 0 ]; do if [ "$1" = -C ]; then d="$(inside "$2")"; a+=(-C "${d}"); shift 2; else a+=("$1"); shift; fi; done
         tar "${a[@]}" ;;
    node) # node <box>/tooling/wrap.mjs <verb> <box>/src <box>/out — compile: each .ts to a .json; render: each .json to a .ts
          local verb="$3" src out f; src="$(inside "$4")"; out="$(inside "$5")"
          [ -f "$(inside "$2")" ] || { echo "no wrap.mjs carried in" >&2; return 1; }
          if [ "${verb}" = render ]; then
            for f in "${src}"/*.json; do echo "// rendered" > "${out}/$(basename "${f}" .json).workflow.ts"; done
          else
            for f in "${src}"/*.workflow.ts; do echo "{\"verb\":\"${verb}\"}" > "${out}/$(basename "${f}" .workflow.ts).json"; done
          fi ;;
    rm) rm -rf "$(inside "$3")" ;;
  esac
}
bbox_node() { return 1; }   # this host has no node (lib.sh's would die)
N8N_DIR="${T}"; WRAP="${T}/tooling/wrap.mjs"; N8N_CONTAINER="n8n-test"
# shellcheck disable=SC1091
. "${HERE}/tooling/wrap.sh" 2>/dev/null || { say FAIL "tooling/wrap.sh is missing"; exit 1; }
if wrap_run compile "${T}/src" "${T}/out" >/dev/null 2>"${T}/err" && [ "$(cat "${T}/out/abc.json" 2>/dev/null)" = '{"verb":"compile"}' ]; then
  say PASS "no node here: compile ran inside n8n-test and abc.json came back"
else
  say FAIL "no node here: compile did not come back from the container ($(cat "${T}/err"))"; fails=$((fails + 1))
fi
grep -q 'container=n8n-test \[-e BBOX_WRAP_CACHE=1 -w [^]]*\] node .*/tooling/wrap.mjs compile' "${CALLS}" \
  && say PASS "the container ran node with the carried-in wrap.mjs, its toolchain kept in the container's cache" \
  || { say FAIL "the container never ran wrap.mjs with BBOX_WRAP_CACHE=1:"; cat "${CALLS}"; fails=$((fails + 1)); }
# pull's shape: render a directory of exported JSON into itself — the .ts arrive and the JSON stay
mkdir -p "${T}/pulled" && echo '{}' > "${T}/pulled/wf1.json"
if wrap_run render "${T}/pulled" "${T}/pulled" >/dev/null 2>"${T}/err" && [ -f "${T}/pulled/wf1.workflow.ts" ] && [ -f "${T}/pulled/wf1.json" ]; then
  say PASS "no node here: render ran inside n8n-test into the same directory, its JSON kept"
else
  say FAIL "no node here: render did not come back ($(cat "${T}/err"); $(ls "${T}/pulled"))"; fails=$((fails + 1))
fi
[ -z "$(ls -A "${CROOT}/tmp")" ] && say PASS "the container's scratch box is removed" \
  || { say FAIL "left in the container: $(ls "${CROOT}/tmp")"; fails=$((fails + 1)); }

echo
[ "${fails}" = 0 ] && echo "all pass" || echo "${fails} FAILED"
exit $(( fails > 0 ))
