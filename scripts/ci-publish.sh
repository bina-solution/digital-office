#!/usr/bin/env bash
# ci-publish.sh — publish the latest CI verification results into the committed
# `.ci-cd/` folder so the observability is BROWSABLE on the GitHub repo page
# (not only inside an ephemeral Actions run). Builds .ci-cd/README.md (badge +
# scorecard + screenshot gallery) from the run's artifacts.
#
#   ./scripts/ci-publish.sh [SRC_DIR]
#     SRC_DIR  where ci-verify.sh/ci-screenshots.sh wrote their output
#              (default: ci-artifacts). Must contain ci-summary.md and,
#              optionally, ci-results.junit.xml + screenshots/app-*.png
#
# Run metadata is read from GitHub Actions env when present, else from git.
set -uo pipefail
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC="${1:-${REPO_ROOT}/ci-artifacts}"
DEST="${REPO_ROOT}/.ci-cd/latest"
README="${REPO_ROOT}/.ci-cd/README.md"
REPO_SLUG="${GITHUB_REPOSITORY:-solomonBoltin/deployment-hacohen}"

BRANCH="${GITHUB_REF_NAME:-$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SHA="${GITHUB_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)}"; SHA_SHORT="${SHA:0:7}"
RUN_NUMBER="${GITHUB_RUN_NUMBER:-local}"
RUN_ID="${GITHUB_RUN_ID:-}"
WHEN="${CI_PUBLISH_DATE:-$(date -u '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo unknown)}"

[ -f "${SRC}/ci-summary.md" ] || { echo "ci-publish: no ${SRC}/ci-summary.md — nothing to publish"; exit 0; }

# 1) Refresh .ci-cd/latest/ with this run's raw artifacts (overwrite, no history churn).
#    Skip the copy when SRC already IS the dest (re-publish/seed in place) — otherwise
#    the rm would wipe the very files we then try to copy from.
mkdir -p "${DEST}/screenshots"
SRC_ABS="$(cd "$SRC" 2>/dev/null && pwd || echo "$SRC")"
if [ "$SRC_ABS" != "$DEST" ]; then
  rm -f "${DEST}/screenshots/"*.png 2>/dev/null || true
  cp -f "${SRC}/ci-summary.md"        "${DEST}/ci-summary.md"        2>/dev/null || true
  cp -f "${SRC}/ci-results.junit.xml" "${DEST}/ci-results.junit.xml" 2>/dev/null || true
  cp -f "${SRC}/screenshots/"app-*.png "${DEST}/screenshots/"        2>/dev/null || true
fi

# Pass/total straight out of the JUnit attributes (fallback to the summary text).
TESTS=$(grep -oE 'tests="[0-9]+"'    "${DEST}/ci-results.junit.xml" 2>/dev/null | grep -oE '[0-9]+' | head -1)
FAILS=$(grep -oE 'failures="[0-9]+"' "${DEST}/ci-results.junit.xml" 2>/dev/null | grep -oE '[0-9]+' | head -1)
TESTS="${TESTS:-?}"; FAILS="${FAILS:-?}"
if [ "${FAILS}" = 0 ]; then VERDICT="✅ all ${TESTS} checks passed"; else VERDICT="❌ ${FAILS}/${TESTS} checks failed"; fi

BADGE="https://github.com/${REPO_SLUG}/actions/workflows/ci-verify.yml/badge.svg?branch=${BRANCH}"
ACTIONS="https://github.com/${REPO_SLUG}/actions/workflows/ci-verify.yml?query=branch%3A${BRANCH}"
[ -n "$RUN_ID" ] && RUNLINK="https://github.com/${REPO_SLUG}/actions/runs/${RUN_ID}" || RUNLINK="$ACTIONS"

# Static shields.io badges, regenerated each run with live numbers parsed from the
# scorecard. (Endpoint/dynamic shields badges can't be used: this repo is PRIVATE,
# so shields can't fetch raw content anonymously. Static badges render anywhere.)
sb() { printf 'https://img.shields.io/badge/%s-%s-%s' \
       "$(printf '%s' "$1" | sed 's/-/--/g; s/ /%20/g')" \
       "$(printf '%s' "$2" | sed 's/-/--/g; s/ /%20/g; s#/#%2F#g')" "$3"; }
num() { grep -oiE "$1"' [0-9]+' "${DEST}/ci-summary.md" 2>/dev/null | grep -oE '[0-9]+' | head -1; }
COLOR=$([ "${FAILS}" = 0 ] && echo brightgreen || echo red)
WF_N=$(num 'workflows imported'); ACT_N=$(num 'active workflows'); CRED_N=$(num 'credentials imported')
BADGES="[![checks]($(sb checks "${TESTS}/$(( ${TESTS:-0} - ${FAILS:-0} )) passing" "$COLOR"))](latest/ci-summary.md)"
[ -n "$WF_N" ]   && BADGES="$BADGES ![n8n workflows]($(sb 'n8n workflows' "$WF_N" blue))"
[ -n "$ACT_N" ]  && BADGES="$BADGES ![active]($(sb 'active workflows' "$ACT_N" blue))"
[ -n "$CRED_N" ] && BADGES="$BADGES ![credentials]($(sb credentials "$CRED_N" blue))"

# 2) (Re)generate the human-facing .ci-cd/README.md.
{
  echo "# Deployment verification — live observability"
  echo
  echo "[![ci-verify](${BADGE})](${ACTIONS})"
  echo
  echo "${BADGES}"
  echo
  echo "Auto-published by [\`ci-verify\`](../.github/workflows/ci-verify.yml) on every push. It brings the"
  echo "**whole stack up from scratch** (fresh \`down -v\` + \`up -d\`, minus the apitools submodule)"
  echo "and asserts every app came up correctly from the declarative config — then drops the scorecard and"
  echo "app screenshots here so the result is browsable without opening an Actions run."
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| **Status** | ${VERDICT} |"
  echo "| **Branch** | \`${BRANCH}\` |"
  echo "| **Commit** | \`${SHA_SHORT}\` |"
  echo "| **Run** | [#${RUN_NUMBER}](${RUNLINK}) |"
  echo "| **Updated** | ${WHEN} |"
  echo
  echo "## Observability model"
  echo
  echo "Two layers, one named check each (published as a JUnit Check Run on the commit):"
  echo
  echo "- **\`health-<app>\`** — liveness: the container is up / serving."
  echo "- **\`integration-<app>[-facet]\`** — declarativity: its config actually took. Complex apps split"
  echo "  into facets, e.g. \`integration-n8n-workflows\` / \`-active-state\` / \`-creds\`,"
  echo "  \`integration-authentik-akadmin\` / \`-providers\`, \`integration-browser42-cdp\` / \`-vnc\`."
  echo
  echo "## Latest scorecard"
  echo
  # ci-summary.md already starts with a \"## Deployment verification …\" heading + table.
  # Drop its leading heading line so it nests under the section above.
  tail -n +2 "${DEST}/ci-summary.md"
  echo
  echo "## App screenshots"
  echo
  echo "Captured by [\`ci-screenshots.sh\`](../scripts/ci-screenshots.sh) driving browser42 over CDP."
  echo
  shopt -s nullglob
  shots=("${DEST}/screenshots/"app-*.png)
  if [ ${#shots[@]} -eq 0 ]; then
    echo "_No screenshots in the latest run._"
  else
    for f in "${shots[@]}"; do
      base="$(basename "$f")"; title="${base#app-}"; title="${title%.png}"
      echo "### ${title}"
      echo
      echo "![${title}](latest/screenshots/${base})"
      echo
    done
  fi
  echo "---"
  echo "_Generated by [\`scripts/ci-publish.sh\`](../scripts/ci-publish.sh). Do not edit by hand — overwritten each run._"
} > "$README"

echo "ci-publish: wrote ${README} (${VERDICT}) + $(ls "${DEST}/screenshots/"app-*.png 2>/dev/null | wc -l | tr -d ' ') screenshots."
