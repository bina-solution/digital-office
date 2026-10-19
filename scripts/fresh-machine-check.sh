#!/usr/bin/env bash
# fresh-machine-check — can a STRANGER stand this platform up?
#
# Everything else in this repo is verified on a machine that already has an .env, built images,
# populated volumes and years of accumulated state. That proves the platform works *here*. It does
# not prove it works.
#
# This clones the repo into a scratch directory with NO .env, NO .generated/, NO volumes and NO
# local state, and drives it as far as a machine can go without pulling images:
#
#   1. a fresh clone contains everything it needs        (nothing reaches outside the tree)
#   2. .env can be generated from nothing                (scripts/ci-env.sh, no secrets required)
#   3. the catalog compiles                              (validate)
#   4. the config renders                                (render)
#   5. the rendered config is a valid compose project    (docker compose config)
#   6. every invariant gate passes on the clone          (G0/G5-G13)
#
# Deliberately NOT done here: pulling images and starting containers. That is ci-verify's job and
# it needs a Docker daemon with network. This lane is the cheap, deterministic half — it catches
# the "works because my machine has X" class of bug in under a minute, which is the class that
# silently accumulates.
#
#   ./scripts/fresh-machine-check.sh              # clone from the local repo (fast, offline)
#   ./scripts/fresh-machine-check.sh --keep       # leave the scratch dir for inspection
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
KEEP=0
for a in "$@"; do [ "$a" = "--keep" ] && KEEP=1; done

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t freshmachine)"
CLONE="${WORK}/clone"
cleanup() { [ "${KEEP}" = 1 ] || rm -rf "${WORK}"; }
trap cleanup EXIT

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
FAILED=0

step "0. clone into a scratch dir (no .env, no .generated, no volumes)"
# A clone, not a copy: `git clone` carries only what is COMMITTED, so anything this repo depends on
# that was never committed shows up here as a failure instead of silently working.
git clone --quiet --no-hardlinks "${REPO_ROOT}" "${CLONE}" 2>/dev/null \
  || { bad "git clone failed"; exit 1; }
cd "${CLONE}"
# Only LOCAL/BUILD state is wrong here. `data/` legitimately ships .gitkeep files for compose bind
# sources (browser42) — the same reason apps/apitools/{storage,logs} ship theirs.
for junk in .env .generated ci-artifacts; do
  [ -e "${junk}" ] && { bad "a fresh clone should not contain ${junk} — it is committed by mistake"; rm -rf "${junk}"; }
done
ok "clone is clean ($(git ls-files | wc -l | tr -d ' ') tracked files)"

step "1. a fresh clone is self-contained (G11)"
if python3 scripts/refactor/fresh-clone-lint.py >/dev/null 2>&1; then
  ok "every path a runnable tracked file reaches for is itself tracked"
else
  python3 scripts/refactor/fresh-clone-lint.py 2>&1 | tail -6; bad "G11"
fi

step "2. .env can be generated from nothing"
# No secrets, no operator input, no pre-existing file. If this needs something the machine happens
# to have, a stranger cannot install the platform.
if ./scripts/ci-env.sh >/dev/null 2>&1 && [ -s .env ]; then
  ok ".env generated from an empty tree ($(grep -c = .env | tr -d ' ') keys)"
else
  ./scripts/ci-env.sh 2>&1 | tail -5; bad "ci-env.sh could not produce an .env"
fi
# ...and it does that ONCE. The generator mints every secret, so a second run over an .env that
# exists must change nothing: on 2026-09-29 one run on a live checkout replaced n8n's encryption
# key and every database password (issues/ci-env-sh-overwrites-a-live-env.yaml).
was="$(cksum < .env)"
if ./scripts/ci-env.sh >/dev/null 2>&1; then
  bad "ci-env.sh ran a second time over an existing .env instead of refusing"
elif [ "$(cksum < .env)" = "${was}" ]; then
  ok "a second run refuses, and the .env it would have replaced is untouched"
else
  bad "ci-env.sh refused the second run and changed .env anyway"
fi

step "3. the catalog compiles"
if out=$(python3 platform/manager/reconcile.py validate 2>&1); then
  ok "$(printf '%s' "${out}" | head -1 | cut -c1-72)"
else
  printf '%s\n' "${out}" | tail -8; bad "validate"
fi

step "4. the config renders"
if out=$(python3 platform/manager/reconcile.py render 2>&1); then
  ok "$(printf '%s' "${out}" | head -1 | cut -c1-72)"
else
  printf '%s\n' "${out}" | tail -8; bad "render"
fi

step "5. the rendered config is a valid compose project"
if command -v docker >/dev/null 2>&1; then
  # portainer binds a gitignored password file; the platform creates it, so create it the way the
  # platform does rather than skipping the check.
  mkdir -p apps/portainer && : > apps/portainer/portainer_password.txt
  if err=$(./scripts/dc config 2>&1 >/dev/null); then
    ok "docker compose resolves the rendered project"
  else
    printf '%s\n' "${err}" | grep -viE '^time=.*level=warning' | tail -6; bad "compose config"
  fi
else
  printf '  \033[33mSKIP\033[0m  docker not on PATH\n'
fi

step "5b. a docker client config naming a helper this machine lacks does not reach a build"
# Hermetic: three homes of its own, nothing of the real user's is read. The helper named is one no
# machine has; "present" is the same name as an executable on PATH.
_h="$(mktemp -d)"; mkdir -p "${_h}/broken/.docker" "${_h}/fine/.docker" "${_h}/bin"
printf '{"auths": {}, "credsStore": "nohelper-xyz"}\n' > "${_h}/broken/.docker/config.json"
printf '{"auths": {}}\n' > "${_h}/fine/.docker/config.json"
printf '#!/bin/sh\nexit 0\n' > "${_h}/bin/docker-credential-nohelper-xyz"; chmod +x "${_h}/bin/docker-credential-nohelper-xyz"
_ask() { env -u DOCKER_CONFIG -u BBOX_CREDS_SAID "$@" bash -c '. scripts/lib.sh >/dev/null 2>&1; printf "%s" "${DOCKER_CONFIG:-}"'; }
_a="$(_ask HOME="${_h}/broken")"; _b="$(_ask HOME="${_h}/fine")"
_c="$(_ask HOME="${_h}/broken" PATH="${_h}/bin:${PATH}")"; _d="$(DOCKER_CONFIG=/somewhere/else bash -c '. scripts/lib.sh >/dev/null 2>&1; printf "%s" "${DOCKER_CONFIG:-}"')"
if [ -n "${_a}" ] && [ -f "${_a}/config.json" ] && [ -z "${_b}" ] && [ -z "${_c}" ] && [ "${_d}" = /somewhere/else ]; then
  ok "a missing helper -> the project's own empty config; no helper named, a helper that exists, or an explicit DOCKER_CONFIG -> untouched"
else
  bad "docker_creds_guard: missing=[${_a}] none=[${_b}] present=[${_c}] explicit=[${_d}]"
fi
rm -rf "${_h}"

step "6. invariant gates on the clone"
# The list lives in scripts/ci/gates.sh — one enumeration shared with `bbox baseline` and checked
# against CI by `gates.sh --verify-ci`. This lane used to keep its own copy, which had already
# fallen 6 gates behind.
for g in $(bash scripts/ci/gates.sh --list); do
  if out=$(python3 "scripts/refactor/${g}.py" 2>&1); then
    ok "$(printf '%s' "${out}" | tail -1 | cut -c1-68)"
  else
    printf '%s\n' "${out}" | tail -4; bad "${g}"
  fi
done

printf '\n'
if [ "${FAILED}" = 0 ]; then
  printf '\033[32mFRESH MACHINE: OK\033[0m — a bare clone with no state compiles, renders and passes every gate.\n'
else
  printf '\033[31mFRESH MACHINE: FAILED\033[0m — this platform depends on something not in the repo.\n'
fi
[ "${KEEP}" = 1 ] && printf 'scratch kept at %s\n' "${CLONE}"
exit "${FAILED}"
