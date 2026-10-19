#!/usr/bin/env bash
# lib.sh — shared helpers for the deployment scripts and the bbox CLI.
# Source it AFTER `set -euo pipefail`:   . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# Provides: REPO_ROOT, read_env, DN, N8N_CONTAINER/PG_CONTAINER, colors, ok/warn/bad/log, running, pgq.
# Honors N8N_CONTAINER / PG_CONTAINER / REPO_ROOT overrides from the environment.

export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'   # don't let Git-Bash mangle container paths
# This estate is Hebrew-first, and python defaults stdout to the ANSI codepage on Windows
# (cp1255 here). Printing any Hebrew or bidi character then dies with
#   UnicodeEncodeError: 'charmap' codec can't encode character '⁦'
# — which killed the ui-map seed step. On Linux/macOS stdout is already UTF-8, so this is a
# no-op there. Set it once for every script rather than prefixing call sites by hand.
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${_LIB_DIR}/.." && pwd)}"
# The PHYSICAL path, never the spelling the caller arrived by. Compose runs with
# `--project-directory .` from here, so every relative bind source (`../../.generated/registry`)
# resolves against this string — and the string is sent to the Docker HOST, which may not have it.
# Measured 2026-10-02: inside bina-ds the checkout is reached through the symlink /workspace/office;
# a `./scripts/dc up` from the agent's shell mounted `/workspace/office/.generated/registry`, a path
# the engine does not have, so Docker created it EMPTY and console, app-management and connections
# came up healthy with no registry (the console rail showed 2 rows instead of 13). The physical path
# is the host's own (bina-ds mounts the checkout at its real path), so both shells now agree.
REPO_ROOT="$(cd "${REPO_ROOT}" 2>/dev/null && pwd -P || printf '%s' "${REPO_ROOT}")"

# read a value from the repo-root .env (gitignored). `|| true` keeps set -e happy on miss.
_env_raw() { { grep -E "^$1=" "${REPO_ROOT}/.env" 2>/dev/null || true; } | head -1 | cut -d= -f2- | tr -d '\r'; }

# read_env — a .env value with `${VAR}` / `${VAR:-default}` references RESOLVED, the way compose
# resolves them.
#
# .env is a declarative file: one identity is stated (BUSINESS_NAME -> COMPANY_SLUG) and the rest
# derives — `DEPLOYMENT_DOMAIN=${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}`,
# `MAIL_DKIM_SELECTOR=${COMPANY_SLUG}`, `LOCALMAIL_USER=admin.${COMPANY_SLUG}`. Docker compose has
# always interpolated those. This function did not: it was grep+cut, so it handed callers the
# literal text `${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}` and every derived value became unusable in
# the shell — which is precisely the pressure that kept hosts hardcoded here in the first place.
#
# Iterative, leftmost-first, capped at 20 substitutions so a self-referential .env cannot hang a
# script. An unset name falls back to the `:-` default, or to empty — same as compose.
read_env() {
  local v L='${' pre rest sub name def val i=0
  v="$(_env_raw "$1")"
  while [ "$i" -lt 20 ]; do
    case "$v" in *"$L"*) ;; *) break ;; esac
    pre="${v%%"$L"*}"          # before the first ${
    rest="${v#*"$L"}"          # after  the first ${
    sub="${rest%%\}*}"         # the reference body: NAME or NAME:-default
    rest="${rest#*\}}"         # after the closing }
    case "$sub" in
      *:-*) name="${sub%%:-*}"; def="${sub#*:-}" ;;
      *)    name="$sub";        def="" ;;
    esac
    val="$(_env_raw "$name")"; [ -n "$val" ] || val="$def"
    v="${pre}${val}${rest}"
    i=$((i + 1))
  done
  printf '%s' "$v"
}

DN="$(read_env DEPLOYMENT_NAME)"; DN="${DN:-bina-deployment}"

# ── a credential helper the docker client is told to use and this machine cannot run ──────────
# `~/.docker/config.json` may name one — `"credsStore": "desktop.exe"` is what Docker Desktop's WSL
# integration leaves behind for a user who no longer runs it. Where that program does not exist,
# EVERY build that has to resolve a base image dies at its first FROM with "error getting
# credentials" — for public images, which need none — and only for images not already in the
# local store, so it reads as a flaky build rather than as configuration
# (issues/docker-credsstore-blocks-rebuilds.yaml, 2026-08-10). The file is the user's and is not
# touched: this process is pointed at an empty client config of the project's own, and says so
# once. A helper that exists is left alone, and so is a DOCKER_CONFIG somebody set.
docker_creds_guard() {
  [ -z "${DOCKER_CONFIG:-}" ] || return 0
  local cfg="${HOME:-/root}/.docker/config.json" helper own
  [ -f "${cfg}" ] || return 0
  helper="$(grep -o '"credsStore"[[:space:]]*:[[:space:]]*"[^"]*"' "${cfg}" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
  [ -n "${helper}" ] || return 0
  command -v "docker-credential-${helper}" >/dev/null 2>&1 && return 0
  own="${REPO_ROOT}/data/.docker-client"
  mkdir -p "${own}" 2>/dev/null || return 0
  [ -f "${own}/config.json" ] || printf '{}\n' > "${own}/config.json" 2>/dev/null || return 0
  export DOCKER_CONFIG="${own}"
  [ -n "${BBOX_CREDS_SAID:-}" ] || echo "[bbox] ${cfg} names the credential helper '${helper}', which this machine does not have — using an empty docker client config (data/.docker-client) so pulls and builds do not die on it" >&2
  export BBOX_CREDS_SAID=1
}
docker_creds_guard
N8N_CONTAINER="${N8N_CONTAINER:-n8n-${DN}}"
PG_CONTAINER="${PG_CONTAINER:-n8n-postgres-${DN}}"

# colors (disabled when stdout is not a TTY, e.g. CI logs)
if [ -t 1 ]; then c0=$'\033[0m'; c1=$'\033[1m'; cr=$'\033[31m'; cg=$'\033[32m'; cy=$'\033[33m'
else c0=""; c1=""; cr=""; cg=""; cy=""; fi

ok()   { echo "  ${cg}✓${c0} $*"; }
warn() { echo "  ${cy}!${c0} $*"; }
bad()  { echo "  ${cr}✗${c0} $*"; }
log()  { echo "[${LOG_TAG:-bbox}] $*"; }
# say — the same trap `die` had below, hit again. `say` was defined in bbox and, separately, in
# scripts/onboarding, but never here — so the moment a shared helper in THIS file used it
# (ensure_network, run_app_hooks) it worked from those two callers and died with
# "say: command not found" from anything else that sources the library, such as an app's hook.
# Callers that want their own prefix still override it after sourcing; onboarding does.
say()  { echo "${c1}[${LOG_TAG:-bbox}]${c0} $*"; }
# die — abort loudly. ui-map.sh called `|| die "UI inventory has drift"` but nothing ever
# defined it, so bash printed "die: command not found" and CARRIED ON: a hard gate that
# could not fail. Defined here so every script that sources lib.sh gets it.
die()  { echo "${cr}[${LOG_TAG:-bbox}] error:${c0} $*" >&2; exit 1; }

# ── BBOX_TMP — scratch paths that cannot collide between users ───────────────────────────────
# A FIXED path under /tmp is a trap on any host where bbox is run by more than one user, and it
# fails in the most confusing way available.
#
# Measured 2026-07-30. Someone ran bbox as `shlomo`, which left /tmp/bbox-glitchtip-push.log owned
# by shlomo, mode 644. Every later run as root then died on the REDIRECT:
#
#   ./bbox: line 268: /tmp/bbox-glitchtip-push.log: Permission denied
#
# Root, denied write on a 644 file it does not own — because `fs.protected_regular=2` (default on
# this kernel) forbids writing to another user's file in a sticky world-writable directory, and
# /tmp is drwxrwxrwt. Root does not bypass it.
#
# The consequence was not a missing log. The redirect is part of the `if` that decides whether
# glitchtip provisioning SUCCEEDED, so a failed redirect reads as a failed provision — and the log
# a human then opens is the STALE one from the other user's run, showing success. Real failure,
# fake evidence. On the reset-and-rebuild that found this, glitchtip was never provisioned at all,
# .env kept the API token of a database that had just been destroyed, and `notifications` sat
# unhealthy on a 401 with nothing in the bring-up saying so.
#
# So: one directory per uid, created up front, private. Stable enough for a human to `cat`, and
# impossible for another user's leftovers to occupy.
BBOX_TMP="${BBOX_TMP:-${TMPDIR:-/tmp}/bbox-$(id -u)}"
if ! mkdir -p "${BBOX_TMP}" 2>/dev/null; then BBOX_TMP="${TMPDIR:-/tmp}"; fi
chmod 700 "${BBOX_TMP}" 2>/dev/null || true
export BBOX_TMP

# ── Git-Bash is not a way to run this stack ─────────────────────────────────────────────────
# On Windows the entry point is bbox.cmd, which forwards into the WSL distro. Running bbox directly
# from Git-Bash reaches neither engine that matters: the project engine's socket lives inside the
# distro and is not visible from Win32, so the only daemon Git-Bash can actually see is Docker
# Desktop's — which is precisely the engine this stack must never deploy into.
#
# This used to be a silent fallback ("Git-Bash has no other engine, so use Docker Desktop"). That
# made Git-Bash a second, unsupported way to run the stack that LOOKED like it worked and quietly
# built everything in the wrong engine. Nothing legitimately needs it — there is no Windows CI, and
# packaging/windows/build-rootfs.sh already says "not on Git-Bash" — so it is an error with a
# pointer, not a fallback.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    die "running under Git-Bash. On Windows, run bbox.cmd from CMD/PowerShell in the repo directory instead (e.g. 'bbox.cmd run'). Git-Bash can only reach Docker Desktop, which this stack never uses. See ai/context/running-on-wsl.md." ;;
esac

# ── which docker ENGINE this stack talks to ─────────────────────────────────────────────────
# Never trust a bare `docker`. Where Docker Desktop is installed with WSL integration on, Desktop
# BINDS /var/run/docker.sock *inside the Linux distro* and forwards it to Desktop's own engine. The
# distro's dockerd keeps running and keeps every image and volume this stack owns — but its socket
# file has been replaced underneath it, so `docker` answers from the other daemon and nothing says so.
#
# Measured on this laptop 2026-07-30, two engines up at once:
#   distro's dockerd   60 images  39 running  32 volumes   ← every deployment-hacohen_* volume
#                                                            (n8n_storage, supabase_db_data,
#                                                             postgres_storage, connections_vault)
#   Docker Desktop's    7 images   8 running   8 volumes   ← a half-built duplicate of
#                                                            authentik+glitchtip+redis, created by
#                                                            an earlier run that landed in the wrong
#                                                            engine and reported success
# The next `bbox run` would have deployed into Desktop's again and left the real stack dark.
#
# It is not merely confusing. Desktop's daemon is not started with DOCKER_MIN_API_VERSION=1.24, so
# traefik v3.3's docker provider discovers ZERO routers there and every *.localhost 404s while
# traefik reports healthy — precisely the silent failure CLAUDE.md's Docker-29 note describes.
#
# So the project owns its own endpoint, one Docker Desktop has no reason to touch, and pins
# DOCKER_HOST to it. Desktop may be installed, running, or absent; it is simply irrelevant. bbox's
# need_docker PROVISIONS that socket; this only SELECTS it, and it lives here rather than in bbox so
# scripts/dc and every other entry point that sources lib.sh get the same engine for free.
# EXPORTED, because it is not only the CLI that needs the right engine: traefik, machine,
# connections, app-management, any-concurrency and portainer all bind-mount the docker socket, and
# compose interpolates ${BBOX_DOCKER_SOCK} into those mounts. A container handed Docker Desktop's
# socket does not fail — it succeeds against the WRONG engine. Traefik is the one that shows:
# it reads Desktop's container list, finds none of this stack's labels, and serves 404 for every
# *.localhost while reporting healthy. Measured 2026-07-30: opening Docker Desktop re-bound
# /var/run/docker.sock inside the distro, and stopping Desktop's stray containers took the whole
# site down while all 39 real containers stayed up and healthy.
export BBOX_DOCKER_SOCK="${BBOX_DOCKER_SOCK:-/run/bbox-docker.sock}"

# Desktop names itself: `docker info` reports OperatingSystem "Docker Desktop". One call per
# candidate — prints "desktop", "native", or nothing at all when the endpoint is dead.
bbox_endpoint_kind() {
  local os
  os="$( docker -H "$1" info --format '{{.OperatingSystem}}' 2>/dev/null )" || return 0
  [ -n "${os}" ] || return 0
  case "${os}" in *"Docker Desktop"*) printf 'desktop' ;; *) printf 'native' ;; esac
}

# Resolve once, then inherit: exported, so compose and every child script reuse the decision.
# BBOX_DOCKER_HOST is the escape hatch — taken verbatim, no probing.
# bbox_engine_chosen <endpoint> — record ONE engine decision for both the CLI and the containers.
#
# DOCKER_HOST is what the CLI talks to. BBOX_DOCKER_SOCK is what compose interpolates into the
# socket bind-mount of traefik, machine, connections, app-management and any-concurrency. They
# describe the same choice and must never disagree — this used to set only the first.
#
# When they disagreed the failure was silent and misattributed. On a host where the project
# endpoint could not be provisioned, the CLI correctly fell back to /var/run/docker.sock while
# BBOX_DOCKER_SOCK kept pointing at /run/bbox-docker.sock, which did not exist. Docker creates a
# missing bind-mount source as a DIRECTORY, so traefik mounted a directory over
# /var/run/docker.sock, its docker provider could not connect, and it served 404 for every host
# while reporting healthy — the exact symptom CLAUDE.md attributes to Docker 29. Measured
# 2026-08-21 on portable-ubuntu; see issues/bbox-engine-split-cli-vs-containers.yaml.
# ── node, found rather than assumed ──────────────────────────────────────────────────────────
# Blueprints are TypeScript, so every push/pull shells out to the HOST's node to run wrap.mjs
# (the in-container `docker exec ... node` calls are a different thing and always fine). A bare
# `node` resolves from an interactive login shell and NOT from a script, a hook, a cron job, or
# CI — those inherit a PATH without the userland install dirs a version manager adds via
# .bashrc. That asymmetry is a trap: `bbox n8n push indox --wf X` succeeded by hand and, minutes
# later, the identical command from a background script died with
#     apps/n8n/hooks/push-app: line 124: node: command not found
# which reads as a broken push rather than a missing PATH entry. The same bug, in the Python
# half, once blocked the entire INDOX E2E battery: G64 is a hard pre-flight, so ten findings
# were reported that were all one absent binary.
#
# $NODE_BIN wins, then PATH, then the usual install locations. Deliberately the same search
# order as _node() in scripts/refactor/n8n_blueprint.py — two languages, one rule.
bbox_node() {
  if [ -n "${BBOX_NODE_RESOLVED:-}" ]; then printf '%s' "${BBOX_NODE_RESOLVED}"; return 0; fi
  local _c
  for _c in "${NODE_BIN:-}" "$(command -v node 2>/dev/null || true)"             "${HOME}/.local/bin/node" "${HOME}/.local/opt/node/bin/node"             /usr/local/bin/node /usr/bin/node; do
    [ -n "${_c}" ] && [ -x "${_c}" ] || continue
    export BBOX_NODE_RESOLVED="${_c}"
    printf '%s' "${_c}"
    return 0
  done
  # Fatal for every caller: without node a blueprint cannot be compiled at all. die() so the
  # failure names its own cause instead of surfacing as `"" compile: command not found`.
  die "no \`node\` on this host, and blueprints are TypeScript. Looked at \$NODE_BIN, PATH, ~/.local/bin/node, ~/.local/opt/node/bin/node, /usr/local/bin/node, /usr/bin/node. Install node, or set NODE_BIN=/path/to/node."
}

bbox_engine_chosen() {
  export DOCKER_HOST="$1" BBOX_ENGINE_RESOLVED=1
  # Only a unix socket can be bind-mounted; a tcp:// engine leaves BBOX_DOCKER_SOCK alone, and
  # bbox_assert_engine_socket below is what refuses to start a socket-mounting stack against it.
  case "$1" in unix://*) export BBOX_DOCKER_SOCK="${1#unix://}" ;; esac
}

bbox_select_engine() {
  [ -n "${BBOX_ENGINE_RESOLVED:-}" ] && return 0
  if [ -n "${BBOX_DOCKER_HOST:-}" ]; then
    bbox_engine_chosen "${BBOX_DOCKER_HOST}"; return 0
  fi
  local ep
  for ep in "unix://${BBOX_DOCKER_SOCK}" "${DOCKER_HOST:-}" "unix:///var/run/docker.sock" "unix:///run/docker.sock"; do
    [ -n "${ep}" ] || continue
    [ "$(bbox_endpoint_kind "${ep}")" = native ] || continue
    bbox_engine_chosen "${ep}"; return 0
  done
  return 1   # nothing non-Desktop reachable — need_docker provisions the project's own daemon
}

# bbox_assert_engine_socket — refuse to hand containers something that is not a socket.
#
# The whole class of bug above is invisible precisely because Docker is helpful: it creates the
# missing source rather than failing. One stat turns "the edge proxy is healthy and nothing
# routes" into a sentence naming the actual path.
bbox_assert_engine_socket() {
  [ -S "${BBOX_DOCKER_SOCK}" ] && return 0
  if [ -d "${BBOX_DOCKER_SOCK}" ]; then
    die "BBOX_DOCKER_SOCK=${BBOX_DOCKER_SOCK} is a DIRECTORY, not a socket — Docker created it
     for a bind-mount whose source was missing. Every container that mounts the docker socket
     will mount that directory instead and silently fail to reach any engine. Remove it
     (sudo rmdir '${BBOX_DOCKER_SOCK}') and re-run; the engine in use is
     \$DOCKER_HOST=${DOCKER_HOST:-<unset>}."
  fi
  die "BBOX_DOCKER_SOCK=${BBOX_DOCKER_SOCK} does not exist. The engine in use is
   \$DOCKER_HOST=${DOCKER_HOST:-<unset>}; containers cannot be handed a socket that is not there."
}
bbox_select_engine || true

# dcx — the ONLY correct way to invoke docker compose for this stack.
#
# Under the app model the services are COMPILED into .generated/ from apps/*/app.json +
# platform.state.yaml; the root compose.yml declares nothing but the shared network. A bare
# `docker compose <cmd>` at the repo root therefore sees ZERO services and exits 0 with
# "no such service: n8n" — a silent no-op that broke n8n-push's restart step without any
# error (webhooks never re-registered, and every `|| true` swallowed it).
#
# Two arguments are both required and neither can be supplied by an env var:
#   -f <compiled files>   from `reconcile.py compose-files` (the single source of that list)
#   --project-directory   include: paths resolve against it (without it they resolve against
#                         .generated/, so `- compose.yml` self-includes -> "include cycle"),
#                         and its basename is the project name that owns the volumes/network.
# ── the compose PROJECT NAME must survive a checkout directory compose cannot name ─────────────
# compose derives the project name from the project directory's basename, normalised to
# [a-z0-9_-]. A checkout named in Hebrew (or any non-Latin script), or with only spaces and
# punctuation left after normalising, yields an EMPTY name and every compose call dies with
# "project name must not be empty" — measured 2026-09-17 on a Mac whose clone was
# "הלשכה הדיגיטלית שלי ". The failure cascades: every wait loop that shells compose times out
# instantly and `bbox run` reports SSO/glitchtip/health failures that are nothing of the sort.
#
# The fix sets a name ONLY when compose's own derivation would be empty. A Latin basename keeps
# compose's derivation byte-for-byte — this must never re-point an existing deployment (the VPS's
# `deployment-hacohen_*` volumes are owned by the name compose derived from its directory), so on
# every host that worked before, nothing changes. An explicit COMPOSE_PROJECT_NAME still wins.
#
# The PHYSICAL path decides, not the spelling the caller used to get here: inside bina-ds the
# checkout is reached through the symlink /workspace/office, whose basename "office" is a perfectly
# good compose name — for a project that does not exist. Measured 2026-09-30 21:13: every
# `./scripts/dc exec` from the agent's shell answered `service "project-pln" is not running`
# (compose: "project has been loaded without an explicit name from a symlink. Using name office"),
# so the agent's own hooks (`bbox project-pln tasks`) printed nothing while the same command worked
# from the host. `pwd -P` resolves the symlink to the bind-mounted host path, and the derivation
# below then agrees with the host's byte for byte.
#
# A name PINNED in .env wins over every derivation, here as it does in compose: compose reads
# COMPOSE_PROJECT_NAME from .env by itself, and this block — which only looked at the shell's
# environment — would then export its fallback over it for a checkout compose cannot name.
if [ -z "${COMPOSE_PROJECT_NAME:-}" ]; then
  _bbox_pin="$(read_env COMPOSE_PROJECT_NAME 2>/dev/null || true)"
  [ -z "${_bbox_pin}" ] || export COMPOSE_PROJECT_NAME="${_bbox_pin}"
  unset _bbox_pin
fi
if [ -z "${COMPOSE_PROJECT_NAME:-}" ]; then
  _bbox_real="$(cd "${REPO_ROOT}" 2>/dev/null && pwd -P)" || _bbox_real="${REPO_ROOT}"
  _bbox_pn="$(basename "${_bbox_real}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]//g; s/^[^a-z0-9]*//')"
  [ -n "${_bbox_pn}" ] || export COMPOSE_PROJECT_NAME="digital-office"
  unset _bbox_pn _bbox_real
fi

compose_args() {
  [ -f "${REPO_ROOT}/.generated/compose.yml" ] \
    || ( cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py render ) >/dev/null 2>&1 || true
  local a="" f
  while IFS= read -r f; do
    [ -n "${f}" ] && a="${a} -f ${f}"
    # tr -d '\r': Windows python prints CRLF, and a trailing CR inside the path makes docker
    # fail with "The filename, directory name, or volume label syntax is incorrect."
  done < <( cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py compose-files 2>/dev/null | tr -d '\r' )
  # OVERLAYS — extra -f files appended AFTER the compiled ones, so compose merges them on top.
  # scripts/dc has always read this; dcx (i.e. every bbox verb) did not, so an overlay applied
  # under ./scripts/dc and silently did nothing under ./bbox run. That split also meant
  # platform/profiles/ci-images.yml — the prebuilt-image overlay the indox-e2e lane depends on —
  # could never be combined with a bbox verb. One list, both entry points.
  for f in ${OVERLAYS:-}; do
    [ -n "${f}" ] && a="${a} -f ${f}"
  done
  # cd'd to REPO_ROOT by the caller, so "." names the repo and keeps the project name stable.
  printf '%s --project-directory .' "${a}"
}
# ── THE compose binary ───────────────────────────────────────────────────────────────────────
# One path, chosen by this project. NOT `docker compose`, which is a SEARCH: the docker CLI walks a
# list of plugin directories and takes the first hit, and on any host where Docker Desktop is
# installed the first hit is Desktop's.
#
# Measured on this laptop 2026-07-30. /usr/local/lib/docker/cli-plugins/ is entirely symlinks into
# /mnt/wsl/docker-desktop/cli-tools/ — docker-compose among them — and that directory outranks the
# distro's. So `docker compose version` reported v2.34.0-desktop.1 while the package this project
# installs (docker-compose-plugin, via debian-install.sh) sat unused at the path below at v5.3.1.
# Every bbox run had been driving the project engine with Docker Desktop's compose binary, and
# uninstalling Desktop would have dangled the symlink and broken the CLI while the engine, images
# and volumes stayed perfectly healthy.
#
# Same shape as the socket fix, same remedy: name our own thing explicitly instead of competing for
# a shared lookup. No fallback chain and no machine tweak — if the plugin this project installs is
# absent, that is an install problem and says so.
BBOX_COMPOSE="${BBOX_COMPOSE:-/usr/libexec/docker/cli-plugins/docker-compose}"
# …and its VERSION is the one every image that brings containers up is built with (their compose
# files' `build.args`): a container is the hash of what compose made of its service, and two versions
# make two things of one file. The binary THIS machine runs is the fact — a host whose package has
# moved off the installers' number is followed, not fought (it may be shared with another stack).
export BBOX_COMPOSE_VERSION="${BBOX_COMPOSE_VERSION:-$("${BBOX_COMPOSE}" version --short 2>/dev/null || true)}"

# ── the repo's path AS THE DAEMON SEES IT ────────────────────────────────────────────────────
# Exported so compose can mount the repo into app-management at the SAME absolute path it has on
# the host. That equality is the whole point, and without it the control plane cannot run compose:
# compose resolves a relative bind source (`./portainer_password.txt`) against the compose file's
# directory, but the DAEMON resolves the result. A control plane holding the repo at /repo therefore
# emits /repo/apps/<id>/... to a daemon that has no /repo — and docker helpfully CREATES it, as a
# directory, so portainer got a directory where its admin-password file should be and crash-looped
# on "could not get the contents of the file". Measured 2026-07-30; docker had invented a whole
# phantom /repo tree on the host.
# Same path in and out means there is nothing to translate.
export BBOX_REPO_HOST="${REPO_ROOT}"

# ── TIME: every container runs on the HOST machine's clock ───────────────────────────────────
# The stack's timestamps — n8n schedule triggers, execution start/stop, the INDOX audit trail —
# must read the same as the machine the operator is looking at. The zone is therefore READ FROM
# THE HOST at invocation time and never pinned in the repo (a committed `Asia/Jerusalem` is wrong
# the moment the repo is cloned anywhere else, and it silently shifts every cron by the delta).
#
# `.env` is the ONLY override. The export is SKIPPED when .env states the value, because compose
# interpolation ranks the shell environment ABOVE .env — exporting unconditionally would make an
# .env setting unreachable, i.e. exactly the "hardcoded somewhere else" failure this replaces.
#
# A CONTAINER THAT RUNS COMPOSE IS NOT THE HOST, and its own /etc/timezone says UTC: an n8n brought
# up from the apps screen or by an agent ran its schedule three hours off the one `bbox run` made
# (measured 2026-10-06 — 11 services compiled differently by who asked). Such a container is handed
# the host's zone when it is created (BBOX_HOST_TZ, in its own compose file) and answers with it.
host_tz() {
  if [ -n "${BBOX_HOST_TZ:-}" ]; then printf '%s' "${BBOX_HOST_TZ}"; return; fi
  if [ -f /etc/timezone ]; then tr -d '\r\n' < /etc/timezone; return; fi
  if command -v timedatectl >/dev/null 2>&1; then
    local z; z="$(timedatectl show -p Timezone --value 2>/dev/null)"
    [ -n "${z}" ] && { printf '%s' "${z}"; return; }
  fi
  if [ -L /etc/localtime ]; then readlink /etc/localtime | sed 's#.*/zoneinfo/##'; return; fi
  printf 'UTC'
}
export_host_tz() {
  local z; z="$(host_tz)"; [ -n "${z}" ] || z=UTC
  grep -qE '^TZ=.+' "${REPO_ROOT}/.env" 2>/dev/null || export TZ="${z}"
  grep -qE '^GENERIC_TIMEZONE=.+' "${REPO_ROOT}/.env" 2>/dev/null || export GENERIC_TIMEZONE="${z}"
}

dcx() {
  [ -x "${BBOX_COMPOSE}" ] \
    || die "compose plugin missing at ${BBOX_COMPOSE} — run: bbox install debian (installs docker-compose-plugin)"
  export_host_tz
  # What must be refused is handing a CONTAINER something that is not a socket — so it is asked of
  # the commands that create one. `config` needs no engine at all, and a lane without one runs it
  # (`scripts/dc config`, which comes through here now).
  if compose_is_recreate "$@"; then bbox_assert_engine_socket; fi
  compose_admit "$@"
  local rc=0
  if compose_self_guard _dcx_run "$@"; then rc="${COMPOSE_GUARD_RC}"; else _dcx_run "$@" || rc=$?; fi
  # What `up` created holds its declared cap; the machine's budget is told to the kernel here
  # (never by a dry run, which is a question) — after whatever lives in a replaced container's
  # network has been put back in the one that replaced it.
  [ "${rc}" -ne 0 ] || case " $* " in *" --dry-run "*) ;; *" up "*) netns_rejoin || rc=$?; cpu_caps_apply ;; esac
  return "${rc}"
}

# stale_containers — the running containers that are NOT what the files say now, one name per line.
#
# A container is created from the compose definition of its service as it stood at that moment, and
# keeps running on it whatever is edited afterwards: an `.env` value, a port, a label, an alias. The
# file on disk is right, the configuration is right, and the running system disagrees with both —
# with no error anywhere, because the old value exists only inside the container. Three unrelated
# outages were this one thing (issues/state-captured-at-creation-never-reconciles.yaml), and on
# 2026-10-06 it was a security fix: `n8n-postgres` was bound to loopback in the files and went on
# publishing its port on every interface, for the day nobody ran a bring-up.
#
# The answer is COMPOSE's own, asked the way a bring-up would decide it and changing nothing: a dry
# run names every container it would re-create. (Comparing `config --hash` with the hash a
# container is stamped with was tried first and cried wolf for six services: the two are not the
# same number for a service that reads an env_file or lives in another service's namespace.)
# `bbox status` prints it and scripts/config-by-caller.sh asks the same question; what brings them
# in line is a bring-up, which re-creates exactly these. No admission slot is taken: it is a question.
#
# The question has to be asked AS a bring-up asks it. The host's time zone is part of what dcx hands
# compose (`export_host_tz`), so the raw runner without it compiles eleven services differently and
# names all eleven — the same trap as a service brought up from a shell that never exported it.
stale_containers() {
  ( export_host_tz
    _dcx_run --dry-run up -d --no-build 2>&1 ) | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' \
    | awk '$1 == "Container" && $NF == "Recreate" {print $2}' | sort -u || true
}

# foreign_containers — containers that hold one of THIS stack's names under ANOTHER compose project,
# one `name project` per line.
#
# A container name is global to the engine; a compose project is not. A container created for this
# deployment from somewhere compose named differently — another clone, a path it derived another
# project from, a hand-run compose — is invisible to this project's `down` and immovable for its
# `up`: `bbox stop` leaves it serving, and the next bring-up dies on "container name already in
# use" PARTWAY, with whatever came after it in the order never created. Measured 2026-08-22: one
# such container, and the bring-up it broke left the gateway and the object store uncreated — seen
# by a person as a DNS error in a dashboard, three layers from the cause
# (issues/compose-project-name-follows-cwd.yaml). The names are the compiled configuration's own
# and the labels are the engine's, so nothing here is a list. `bbox status` prints what this finds
# and `bbox run` refuses to start over it — saying which project holds what — instead of colliding.
foreign_containers() {
  ( export_host_tz; _dcx_run config --format json 2>/dev/null ) | python3 -c '
import json, subprocess, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
mine = d.get("name") or ""
names = {s.get("container_name") for s in (d.get("services") or {}).values()} - {None}
ps = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"],
                    capture_output=True, text=True).stdout
for line in ps.splitlines():
    name, _, project = line.partition("\t")
    if name in names and project != mine:
        print(name, project or "(no-compose-project)")' 2>/dev/null || true
}

# netns_rejoin — a container that lives in ANOTHER's network namespace follows it when it is replaced.
#
# `network_mode: service:<x>` is resolved to x's container when the consumer is CREATED. Replace x
# alone — a rebuild, a changed setting — and the consumer goes on running in the namespace of a
# container that no longer exists: its listeners are there, `docker ps` says Up, nothing reaches
# them, and a restart cannot help because the container it would rejoin is gone. Measured
# 2026-10-04: `dgo-net` rebuilt, `dgo-link` left behind, the link between two offices dark until
# somebody remembered `--force-recreate dgo-link` (issues/the-link-goes-dark-after-every-tunnel-
# rebuild.yaml) — and again on 2026-10-06. So it is not remembered: after every `up`, whoever ran
# it and whatever it named, a consumer whose owner is gone — or was started after it — is recreated.
# It is STATE that is read, not the command: this also puts right what an earlier `up` left behind,
# and it holds for the next service that shares a namespace without anybody declaring the pair.
# Says only what it recreated.
netns_rejoin() {
  local stale
  stale="$(_dcx_run ps -a --format '{{.ID}} {{.Service}}' 2>/dev/null | while read -r id svc; do
      owner="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "${id}" 2>/dev/null || true)"
      case "${owner}" in container:*) owner="${owner#container:}" ;; *) continue ;; esac
      # an owner that is gone answers nothing, and that IS the answer
      since="$(docker inspect -f '{{if .State.Running}}{{.State.StartedAt}}{{end}}' "${owner}" 2>/dev/null || true)"
      mine="$(docker inspect -f '{{.State.StartedAt}}' "${id}" 2>/dev/null || true)"
      # to the second: the engine prints as many fraction digits as the instant happens to have
      if [ -z "${since}" ] || [[ "${since:0:19}" > "${mine:0:19}" ]]; then printf '%s ' "${svc}"; fi
    done || true)"
  [ -n "${stale}" ] || return 0
  say "recreating ${stale}— the container whose network it lives in was replaced"
  # shellcheck disable=SC2086 — a list of service names
  _dcx_run up -d --no-deps --force-recreate ${stale}
}

# cpu_caps_apply — every running container gets the CPU quota the budget gives its service NOW.
#
# The budget (gate G65) is a scale over every ENABLED app, so it moves whenever one is switched on
# or off. It used to be merged into the compose configuration, which made that scale part of every
# container's identity: one app more, and the next bring-up re-created the edge, two databases and
# the sign-in. It is runtime state of the running SET, so it is set at runtime — `docker update`
# changes a quota in place — after every `up`, by whoever ran it. Says only what it changed.
cpu_caps_apply() {
  [ -f "${REPO_ROOT}/.generated/cpu-budget.yml" ] || return 0
  ( cd "${REPO_ROOT}" && _dcx_run ps --format '{{.ID}} {{.Service}}' 2>/dev/null \
      | python3 scripts/refactor/cpu-budget-lint.py --apply .generated/cpu-budget.yml ) || true
}

# ── HEAVY-JOB ADMISSION: one heavy job at a time on this engine, and only when memory allows ─────
# The office runs several agents at once, and each can start a heavy job: an image build, a full
# `bbox run`, a ui-map (2+ Chromium shards), a baseline. Measured 2026-09-30 on the 5 GiB macOS
# engine: a ui-map, a Plane recreate, nine `dgo-extend` rebuilds and a git rebuild overlapped — load 223,
# swap 4096/4096 MiB, 77 MiB free. bina-ds then failed its healthcheck, the office agent's page
# answered 404, and every agent's LLM stream timed out, so no agent could even stop its own job.
#
# heavy_admit <label> takes ONE engine-wide slot — an flock on data/.locks/heavy, which the host,
# the engine and every container that mounts the checkout (bina-ds does) see as the same lock —
# then waits until MemAvailable >= BBOX_HEAVY_MIN_MB before returning. The slot is held by the
# calling process and released when it exits, crashes included; nested calls (bbox run → dc build,
# ui-map → dc) inherit BBOX_HEAVY_HELD and pass straight through. Waiting is not failing: a caller
# that finds the slot busy says who holds it and waits (BBOX_HEAVY_WAIT, default 3 h) — it does
# not error. BBOX_HEAVY=off disables it for one command (CI runners own their machine).
heavy_admit() {
  [ "${BBOX_HEAVY_HELD:-}" = 1 ] && return 0
  [ "${BBOX_HEAVY:-on}" = off ] && return 0
  command -v flock >/dev/null 2>&1 || return 0
  local dir="${REPO_ROOT}/data/.locks" label="${1:-heavy job}" waited=0 said=-60
  # The memory floor is per job kind: a build wants BBOX_HEAVY_MIN_MB (1200); a recreate is admitted
  # with the floor its caller passes (compose_admit: 400) — otherwise a full box could never bring
  # itself up.
  local limit="${BBOX_HEAVY_WAIT:-10800}" need="${2:-${BBOX_HEAVY_MIN_MB:-1200}}" avail fd
  mkdir -p "${dir}" 2>/dev/null || return 0
  exec {fd}>>"${dir}/heavy" || return 0
  while ! flock -n "${fd}"; do
    if [ $(( waited - said )) -ge 60 ]; then
      say "waiting for the heavy-job slot (one at a time on this engine) — held by: $(cat "${dir}/heavy.holder" 2>/dev/null || echo '?')" >&2
      said="${waited}"
    fi
    [ "${waited}" -ge "${limit}" ] && die "the heavy-job slot is still busy after ${limit}s — held by: $(cat "${dir}/heavy.holder" 2>/dev/null || echo '?')"
    sleep 10; waited=$(( waited + 10 ))
  done
  while avail="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null)"; [ -n "${avail}" ] && [ "${avail}" -lt "${need}" ]; do
    if [ $(( waited - said )) -ge 60 ]; then
      say "waiting for memory before '${label}': ${avail} MB available, ${need} MB wanted" >&2
      said="${waited}"
    fi
    if [ "${waited}" -ge "${limit}" ]; then say "starting '${label}' with ${avail} MB available (waited ${limit}s)" >&2; break; fi
    sleep 10; waited=$(( waited + 10 ))
  done
  printf '%s | pid %s on %s | since %s\n' "${label}" "${BASHPID:-$$}" "$(hostname 2>/dev/null)" "$(date -u '+%F %T UTC')" > "${dir}/heavy.holder" 2>/dev/null || true
  export BBOX_HEAVY_HELD=1 BBOX_HEAVY_FD="${fd}"
}

# heavy_detach — call this at the TOP of any child that will outlive its heavy job (a watchdog, a
# reaper, a `( sleep … ) &`): it closes this job's inherited slot fd, so the child cannot hold the
# slot after the job is gone.
#
# WHY IT EXISTS. flock(2) locks belong to the OPEN FILE DESCRIPTION, not to a process: bash does not
# set close-on-exec on `exec {fd}>>` (measured 2026-10-09: a lock taken in a shell, whose only child
# is `sleep 25`, is STILL held one second after that shell exits), so every child inherits the slot
# and the last one to die releases it. run_capture.sh's shard watchdogs are `( sleep 900; … ) &` —
# they outlive the capture on purpose, so a finished `bbox ui-map` kept the slot for up to 15 more
# minutes and the NEXT heavy job (a second profile, a build) sat in "waiting for the heavy-job slot —
# held by: ui-map --profile desktop | pid …" naming a process that no longer existed. Measured on
# both offices the same afternoon: on srv908573 `flock -n data/.locks/heavy` answered busy with only
# `sleep 900` (ppid 1) holding the fd, and `kill` of that stray sleep freed the slot and let the
# queued capture start. The rule this encodes: a child that outlives the job must not inherit its
# slot — and the job that spawns it says so, here, rather than the waiter guessing.
heavy_detach() {
  [ -n "${BBOX_HEAVY_FD:-}" ] || return 0
  exec {BBOX_HEAVY_FD}>&- 2>/dev/null || true
}

# heavy_slot_status — "free", or the holder line of the job that holds the slot RIGHT NOW.
# Never read data/.locks/heavy.holder on its own: it is written on admission and not cleared when
# the job exits (the lock is released by the kernel when the process dies, crashes included —
# nothing runs afterwards to erase a note). 2026-10-01 02:00–02:26 two watchers read the file,
# reported "the dgo-extend build still holds the lock" for half an hour, and held every lane back
# for a job that had finished at 02:00. Only the flock is truth; this is the one reader to use.
heavy_slot_status() {
  local f="${REPO_ROOT}/data/.locks/heavy"
  [ -e "${f}" ] || { echo free; return 0; }
  if flock -n "${f}" true 2>/dev/null; then echo free
  else cat "${REPO_ROOT}/data/.locks/heavy.holder" 2>/dev/null || echo "held (holder unknown)"; fi
}

# compose_is_build ARGS… — true when a compose invocation builds images: the `build` subcommand, or
# `up`/`create`/`run` with --build. Global flags before the subcommand (-f, -p …) are skipped.
compose_is_build() {
  local a sub=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -f|--file|-p|--project-name|--profile|--env-file|--project-directory|--ansi|--progress|--parallel) shift; [ $# -gt 0 ] && shift ;;
      -*) shift ;;
      *) sub="$1"; shift; break ;;
    esac
  done
  [ "${sub}" = build ] && return 0
  case "${sub}" in up|create|run) for a in "$@"; do [ "${a}" = --build ] && return 0; done ;; esac
  return 1
}

# compose_is_recreate ARGS… — true when a compose invocation can create, recreate or restart
# containers: `up`, `create`, `run`, `restart`, with or without --build (a plain `up -d` recreates
# whatever changed). Global flags before the subcommand are skipped like compose_is_build.
#
# WHY (2026-10-01 01:58): three simultaneous recreates — forge, dgo-extend+dgo-net, n8n — from
# three agent lanes pushed the 4-vCPU engine to load 105 and containerd into ttrpc timeouts. A
# recreate is a stop, a create, a start and every healthcheck of the new container at once; the
# previous day's storms were the same thing with builds. So a recreate takes the SAME one
# engine-wide slot as a build (heavy_admit): one at a time, in arrival order, with a visible
# "held by" line while waiting. `stop`, `start`, `ps`, `logs`, `exec`, `config` stay free.
compose_is_recreate() {
  local sub=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -f|--file|-p|--project-name|--profile|--env-file|--project-directory|--ansi|--progress|--parallel) shift; [ $# -gt 0 ] && shift ;;
      -*) shift ;;
      *) sub="$1"; shift; break ;;
    esac
  done
  case "${sub}" in up|create|run|restart) return 0 ;; esac
  return 1
}

# compose_admit ARGS… — the one admission line every compose entry point uses (dcx, scripts/dc):
# a build takes the slot with the build memory floor, a recreate with the recreate floor
# (BBOX_RECREATE_MIN_MB, default 400 MiB), anything else passes. Nested calls pass through on
# BBOX_HEAVY_HELD, so `bbox run` (build, then up) holds the slot once for its whole life.
compose_admit() {
  if compose_is_build "$@"; then heavy_admit "compose $*"
  elif compose_is_recreate "$@"; then heavy_admit "compose $*" "${BBOX_RECREATE_MIN_MB:-400}"
  fi
  return 0
}
# BBOX_DOCKER_SOCK means two things that are one path on the host and two in a container: where the
# CLI reaches the engine, and the bind-mount SOURCE compose interpolates into every service that
# holds the socket — a path on the HOST, whoever asks. A container that runs compose was mounting
# the socket at /var/run/docker.sock and compiling THAT as the source: 8 services came out different
# from `bbox run`'s and were re-created at every alternation, and on a machine where that path is
# another engine they would have been handed it (measured 2026-10-06). Such a container is handed
# the host's path when it is created (BBOX_HOST_DOCKER_SOCK, in its own compose file), and compose
# — which talks to the engine through DOCKER_HOST — interpolates that.
_dcx_run() { ( cd "${REPO_ROOT}" && BBOX_DOCKER_SOCK="${BBOX_HOST_DOCKER_SOCK:-${BBOX_DOCKER_SOCK}}" "${BBOX_COMPOSE}" $(compose_args) "$@" ); }

# ── SELF-GUARD: a compose command that would replace the container it is running in ─────────────
# The office agent's harness runs inside a container, and its shell runs ./bbox and ./scripts/dc
# against the engine. Any command there that recreates, restarts or stops THAT container kills the
# process running compose before compose is done: the old container goes first, the client dies with
# it, and the replacement is left in `Created`. Measured 2026-09-29 05:03: one
# `./scripts/dc up -d --build bina-ds` took the harness down for 8 hours, and every agent in it.
#
# Both compose entry points (dcx here, scripts/dc) pass through this guard, and it names NO app:
# "whose container am I in" is asked of the ENGINE (`bbox_self_service`), so the same protection
# covers any app that runs compose from inside itself. What the guard then does, for the service it
# turns out to be in:
#   * up/create/restart  — runs the command for every OTHER service as usual, builds the self
#     service in the foreground if --build was asked (a build error still reaches the caller), and
#     hands the recreate to that app's OWN helper, `<root>/<id>/hooks/self-update`: a one-shot
#     process OUTSIDE the container recreates it, waits for health, and puts the previous image back
#     if the new one is not healthy. An app that ships no such hook gets the refusal below, never a
#     half-finished recreate;
#   * stop/kill/rm/down/pause — refuses for the self service (nothing would be left to bring it
#     back); every other named service is handled as usual.
# Anywhere else — the host, the engine, CI, the helper itself — it returns 1 and changes nothing.
#
# Contract: `compose_self_guard RUNNER ARGS…`. Returns 0 when it handled the command (the caller
# returns/exits with $COMPOSE_GUARD_RC), 1 when the caller should run ARGS unchanged.
COMPOSE_GUARD_RC=0
COMPOSE_SELF=""

#: The compose service of the container THIS command runs in, or empty — the one fact this guard
#: used to carry as an app's name. Asked of the engine: the running container whose `Config.Hostname`
#: is ours, and the compose service label on it. That also covers containers started before any
#: marker env var existed, and it cannot go stale when an app is renamed or its container recreated.
bbox_self_service() {
  [ -f /.dockerenv ] || return 1
  command -v docker >/dev/null 2>&1 || return 1
  local me ids
  me="$(hostname 2>/dev/null)" || return 1
  [ -n "${me}" ] || return 1
  ids="$(docker ps -q 2>/dev/null)" || return 1
  [ -n "${ids}" ] || return 1
  # shellcheck disable=SC2086  # the id list is word-split on purpose: one inspect call for all of them
  docker inspect --format \
    '{{.Config.Hostname}} {{index .Config.Labels "com.docker.compose.service"}}' ${ids} 2>/dev/null \
    | awk -v me="${me}" '$1 == me && $2 != "" { print $2; exit }'
}

#: The app's own door for "recreate ME, from outside myself", or empty when it ships none.
compose_self_helper() {
  local root
  for root in apps platform-base; do
    [ -x "${REPO_ROOT}/${root}/${COMPOSE_SELF}/hooks/self-update" ] \
      && { printf '%s' "${REPO_ROOT}/${root}/${COMPOSE_SELF}/hooks/self-update"; return 0; }
  done
  return 1
}

compose_self_guard() {
  local runner="$1"; shift
  # self-update.sh's own dry run ("would anything change?") must not be handed off again.
  [ "${COMPOSE_GUARD_OFF:-}" = 1 ] && return 1
  # Cheap first, in this order: the subcommand decides whether ANY of this matters, and asking the
  # engine who we are costs a `docker ps`+`inspect` (~250 ms). `dc ps`, `dc logs`, `dc exec` — the
  # commands an agent runs all day — must not pay for a guard that cannot apply to them.
  local -a pre=() opts=() svcs=() others=() flags=()
  local sub="" s implicit=0 self_hit=0 build=0 rc=0
  while [ $# -gt 0 ]; do case "$1" in -*) pre+=("$1"); shift ;; *) sub="$1"; shift; break ;; esac; done
  case "${sub}" in up|create|restart|stop|kill|rm|down|pause) ;; *) return 1 ;; esac
  COMPOSE_SELF="$(bbox_self_service)" || return 1
  [ -n "${COMPOSE_SELF}" ] || return 1
  while [ $# -gt 0 ]; do
    case "$1" in
      -t|--timeout|--wait-timeout|--scale|--pull|--exit-code-from|--attach|--no-attach|-s|--signal|--rmi)
        opts+=("$1"); [ $# -gt 1 ] && { opts+=("$2"); shift; }; shift ;;
      -*) opts+=("$1"); shift ;;
      *)  svcs+=("$1"); shift ;;
    esac
  done
  if [ "${#svcs[@]}" -eq 0 ]; then
    implicit=1
    while IFS= read -r s; do [ -n "${s}" ] && [ "${s}" != "${COMPOSE_SELF}" ] && others+=("${s}"); done \
      < <("${runner}" "${pre[@]}" config --services 2>/dev/null)
    self_hit=1
  else
    for s in "${svcs[@]}"; do
      if [ "${s}" = "${COMPOSE_SELF}" ]; then self_hit=1; else others+=("${s}"); fi
    done
  fi
  [ "${self_hit}" = 1 ] || return 1
  case "${sub}" in
    stop|kill|rm|down|pause)
      if [ "${implicit}" = 1 ] || [ "${sub}" = down ]; then
        echo "dc: '${sub}' of the whole stack from inside ${COMPOSE_SELF} would stop the container" \
             "this command runs in, with nothing left to bring it back. Name the services instead," \
             "or run it from the host." >&2
        COMPOSE_GUARD_RC=3; return 0
      fi
      [ "${#others[@]}" -gt 0 ] && { "${runner}" "${pre[@]}" "${sub}" "${opts[@]}" "${others[@]}" || rc=$?; }
      echo "dc: skipped '${sub}' of ${COMPOSE_SELF} — it is the container this command runs in." \
           "Stopping it belongs to the owner (the apps screen in the office UI, or ./scripts/dc on the host)." >&2
      COMPOSE_GUARD_RC=$(( rc != 0 ? rc : 3 )); return 0 ;;
  esac
  # up / create / restart
  for s in "${opts[@]}"; do
    case "${s}" in --build) build=1 ;; -d|--detach) ;; *) flags+=("${s}") ;; esac
  done
  if [ "${#others[@]}" -gt 0 ]; then
    "${runner}" "${pre[@]}" "${sub}" "${opts[@]}" "${others[@]}" || rc=$?
  fi
  if [ "${build}" = 1 ]; then
    if ! "${runner}" "${pre[@]}" build "${COMPOSE_SELF}"; then
      echo "dc: the ${COMPOSE_SELF} build failed — nothing was restarted; it keeps running as it was." >&2
      COMPOSE_GUARD_RC=1; return 0
    fi
  fi
  local helper=""
  helper="$(compose_self_helper)" || {
    echo "dc: ${COMPOSE_SELF} would have to be recreated from OUTSIDE itself, and it ships no" \
         "<id>/hooks/self-update helper to do that. Run it from the host." >&2
    COMPOSE_GUARD_RC=3; return 0
  }
  bash "${helper}" launch "${sub}" "${flags[@]}" || rc=$?
  COMPOSE_GUARD_RC="${rc}"; return 0
}

# npath — a path the NATIVE binaries understand. No-op on Linux.
#
# lib.sh sets MSYS_NO_PATHCONV=1 so Git-Bash stops rewriting container-side paths (/data,
# /blueprints/...). The cost is that host-side paths stay in MSYS form (/c/Users/...), and
# python.exe / docker.exe are Windows programs that do not understand them — python resolves
# `/c/Users/x` to `C:\c\Users\x` and docker reports `path "/c/..." not found`.
#
# So convert explicitly at the boundary where a HOST path is handed to a native binary:
# `python3 "$(npath "$DIR")/x.py"`, `docker build "$(npath "$CTX")"`, `-v "$(npath "$D"):/data"`.
# cygpath -m yields C:/Users/... — forward slashes, which both python and docker accept.
npath() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) cygpath -m "$1" 2>/dev/null || printf '%s' "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

# ensure_generated_writable — self-heal root-owned .generated before anything tries to write it.
#
# THE BUG IT REMOVES. Containers that bind-mount the repo (app-management, data-management) have
# no `user:` and their images declare no USER, so they run as uid 0 — a container's uid comes from
# its IMAGE, never from whoever ran the CLI. When one of them shells `reconcile.py render`, every
# file it writes under .generated/ lands root:root at mode 0644. The next `bbox n8n push`, running
# as you, then dies with a raw Node EACCES naming a workflow you did not ask to touch (compileDir
# writes the whole app). Measured twice: 2026-08-17 (the "fix" was rm -rf .generated, which broke
# the live console) and 2026-08-26 (a hand chown, which is what this function replaces).
#
# WHY THIS IS SAFE TO DO AUTOMATICALLY. .generated/ is compiled output, gitignored, owned entirely
# by this toolchain and regenerable by `reconcile.py render`. Repairing its ownership changes no
# content and loses nothing.
#
# WHY NO sudo AND NO HARDCODED UID. bbox already talks to a root-owned docker daemon, so it can
# borrow it for one throwaway container instead of prompting for a password — which matters
# because agents and CI run with no tty and would hang forever on a sudo prompt. The uid/gid come
# from `id` at runtime, so nothing in the repo names a user and this stays correct on any host.
#
# On Docker Desktop (macOS/Windows) the file-sharing layer fakes ownership, so this is a no-op
# there — the condition only exists on native Linux and WSL, where bind-mount ownership is real.
ensure_generated_writable() {
  local dir="${1:-${REPO_ROOT}/.generated}"
  [ -d "$dir" ] || return 0
  # The check must look at the whole TREE, not just $dir. A write-probe on the top directory
  # passes while .generated/n8n/<app>/*.json underneath is root-owned — which is precisely the
  # failing case, since compileDir writes the per-app files, not the parent. `find -print -quit`
  # stops at the first foreign-owned entry, so the normal (clean) case costs one cheap walk and
  # the poisoned case exits immediately.
  local foreign
  foreign="$(find "$dir" ! -user "$(id -u)" -print -quit 2>/dev/null || true)"
  [ -n "$foreign" ] || return 0
  command -v docker >/dev/null 2>&1 || {
    echo "[bbox] ${foreign} is not owned by $(id -un) and docker is unavailable to repair it." >&2
    return 1; }
  echo "[bbox] ${dir} contains files owned by another user (a container render ran as root) — repairing"
  docker run --rm -v "${dir}:/g" alpine:3 chown -R "$(id -u):$(id -g)" /g >/dev/null 2>&1 || {
    echo "[bbox] could not repair ${dir}; see issues/n8n-push-cannot-recover-root-owned-generated.yaml" >&2
    return 1; }
  foreign="$(find "$dir" ! -user "$(id -u)" -print -quit 2>/dev/null || true)"
  [ -z "$foreign" ] && { echo "[bbox] ownership repaired"; return 0; }
  echo "[bbox] ${foreign} still not owned by $(id -un) after repair" >&2; return 1
}

# ncores / gtimeout — GNU coreutils are NOT in macOS base userland. `nproc` does not exist
# there and `timeout` ships as `gtimeout` (brew coreutils). Both are present on Linux and in
# Git-Bash. Without these, a 12-core Mac fell through `nproc || echo 2` and got sized to the
# 2-core ci-small performance profile, and every `timeout ...` call simply failed.
ncores() {
  if command -v nproc >/dev/null 2>&1; then nproc
  elif command -v sysctl >/dev/null 2>&1; then sysctl -n hw.ncpu 2>/dev/null || echo 2
  else echo 2; fi
}
# Echoes the timeout binary, or nothing when there is none — callers use:
#   TO="$(timeout_bin)"; ${TO:+$TO --kill-after=30 --signal=KILL 600} some-command
timeout_bin() {
  if command -v timeout  >/dev/null 2>&1; then printf 'timeout'
  elif command -v gtimeout >/dev/null 2>&1; then printf 'gtimeout'
  fi
}

running() { docker ps --format '{{.Names}}' | grep -Fxq "$1"; }            # running <container>
# cn <service> — the real container name for a compose service, whichever docker actually shows:
# bare `<svc>`, `<svc>-<DN>`, or a compose-prefixed `<svc>-<n>`. Robust to deployment-name drift
# between a laptop (…-local-dev) and CI (…-<DN>). Empty output = not running.
cn() {
  local svc="$1" names; names="$(docker ps --format '{{.Names}}' 2>/dev/null)"
  local n; for n in "${svc}-${DN}" "${svc}"; do printf '%s\n' "$names" | grep -Fxq "$n" && { echo "$n"; return; }; done
  printf '%s\n' "$names" | grep -E "^${svc}(-[a-z0-9-]+)?$" | head -1
}
pgq()     { docker exec -e PGPASSWORD="$(read_env POSTGRES_PASSWORD)" "${PG_CONTAINER}" \
              psql -U "$(read_env POSTGRES_USER)" -d "$(read_env POSTGRES_DB)" -tAc "$1" 2>/dev/null | tr -d '\r'; }

# ── Bring-up primitives (shared by `bbox run` and `scripts/onboarding`) ───────────────────────
# Both live here rather than in bbox because BOTH entry points need them and neither names an app.
# ensure_network was written twice — bbox had this, and onboarding open-coded the same
# inspect-or-create inline. Two implementations of "make sure the shared network exists" is one
# more than the number of ways it can be right.
ensure_network() {
  docker network inspect traefik-network >/dev/null 2>&1 \
    || { say "creating external network traefik-network"; docker network create traefik-network >/dev/null; }
}

# run_app_hooks <verb> — run <root>/<id>/hooks/<verb> for every ENABLED app that has one.
#
# This is what lets the CLI stop knowing app names. bbox used to carry a bespoke function per app
# that needed something done before it could start: ensure_portainer_password (one gallery app's
# admin secret, minted on every run even though the app ships DISABLED), ensure_acme_perms
# (traefik's acme.json mode and its ACME contact address), ccr_warn_browser42 in this very library
# (one app's digest-pinned base). Five app names in the bring-up path of a tool that is supposed to
# be app-agnostic — and all of them in the WRONG PLACE besides, because installing an app from the
# apps screen never runs bbox, so none of them fired on that path.
#
# The convention already existed for on-demand tooling (`bbox app <id> <verb>`, "an app is a folder;
# its tooling belongs inside it"). This is the lifecycle-side counterpart, and it is the whole
# mechanism: an app declares what it needs by having the file, and gets it in both paths.
#
# Verbs in use:
#   prepare   before containers start                                          (`bbox run`)
#   onboard   first-run seeding, after the stack is up and n8n is restored     (`bbox run`)
#
# `onboard` runs unconditionally on every `bbox run` (not just the interactive `bbox onboarding`
# flow) — each app's onboard hook is therefore responsible for being a safe no-op once its own
# first-run work is already done, the same contract `push` already has for re-runs.
#
# Enablement comes from the compiler (`reconcile.py enabled-apps`), not from a glob, so a disabled
# app's hook does not run — which is the bug ensure_portainer_password had, and the same bug
# onboarding had when it restored browser42's state dump for an app that ships disabled.
#
# RETURNS the number of hooks that failed, and never stops early. Those are two separate promises
# and both matter:
#
#   never stops early — one app's broken bootstrap must not deny every later app its own.
#   returns a status  — because `verify` exists. A verification that cannot fail is not a
#                       verification, and this function previously swallowed every exit code
#                       (`bash "${hook}" || say "… (continuing)"`), so the only way a caller could
#                       learn of a failure was to capture stdout and grep for that sentence. That
#                       is a string contract between two files, and it silently becomes a lie the
#                       first time someone rewords the message or a hook writes to stderr.
#
# Callers therefore choose. Bring-up verbs (`prepare`, `onboard`) append `|| true`: a failed
# bootstrap is loud but not fatal, which is the behaviour they always had. `bbox baseline` does NOT,
# because reporting a green baseline over a failing app is the exact disease this repo is curing.
run_app_hooks() {
  local verb="${1:?usage: run_app_hooks <verb>}" root aid hook rc=0
  while read -r root aid; do
    [ -n "${root}" ] && [ -n "${aid}" ] || continue
    hook="${REPO_ROOT}/${root}/${aid}/hooks/${verb}"
    [ -e "${hook}" ] || continue
    # A hook that is THERE and cannot run is said, and counted: skipped in silence, seven
    # bootstraps once never executed (traefik's acme.json mode among them) and nothing said a word.
    # G31 keeps the committed mode right; this is the checkout that lost its modes on the way.
    [ -x "${hook}" ] || { say "${cy}${aid}: ${verb} hook is not executable — NOT run (chmod +x ${root}/${aid}/hooks/${verb})${c0}"; rc=$((rc + 1)); continue; }
    if ! bash "${hook}"; then
      say "${cy}${aid}: ${verb} hook FAILED${c0}"
      rc=$((rc + 1))
    fi
  done < <( cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py enabled-apps 2>/dev/null )
  return "${rc}"
}

# ── Cloud-sandbox accommodations (GUARDED NO-OPS on a normal Windows/VPS host) ────────────────
# A Claude-Code-on-the-web / cloud sandbox differs from a laptop or VPS in two ways that break a
# plain `docker compose up --build`: a TLS-terminating egress proxy MITMs HTTPS (so pip/npm inside
# a build can't verify certs), and the host caps ulimits low. Each helper below detects that
# environment and adapts; when the tell-tale is absent (no proxy CA file, ample ulimits) it returns
# immediately and changes NOTHING — so behaviour on the laptop and the VPS is byte-for-byte the same
# as before. `bbox baseline` has always done the CA shadow; these lift it so `bbox run`/`bbox ui-map`
# are self-sufficient too. Override the CA path with PROXY_CA=… (or the legacy BASELINE_PROXY_CA).
PROXY_CA="${PROXY_CA:-${BASELINE_PROXY_CA:-/root/.ccr/ca-bundle.crt}}"

ccr_have_proxy_ca() { [ -f "${PROXY_CA}" ]; }   # true only inside a MITM-proxy sandbox

# ── Container DNS, which is a different failure from "no egress" ─────────────────────────────
# [2026-08-22] `bbox run` on a Debian host died ~22 services in, at
#     RUN pip install --no-cache-dir -r requirements.txt   ->   exit code 1
# and left 20 of 42 services up, so the console showed 2 apps instead of the full set. Measured on
# that host:
#     container ping 1.1.1.1   0% packet loss          <- the internet is reachable
#     container nslookup       connection timed out    <- names are not
#     container resolv.conf    8.8.8.8, 1.1.1.1        <- the same resolvers the HOST uses fine
# So egress works and only UDP/53 out of the bridge does not. That distinction matters: it was
# first misdiagnosed as ufw's DEFAULT_FORWARD_POLICY="DROP", which is Ubuntu's shipped default,
# had been set for a month, and cannot be the cause because ICMP crosses the same FORWARD chain.
#
# This is a PRE-FLIGHT, not a fallback. bbox does not paper over a host whose container DNS is
# broken -- it says so before spending five minutes discovering it inside a pip install. One
# behaviour on every machine; the operator fixes their host.
#
# Probed once per process and cached. Any failure to probe (no docker yet, image cannot be pulled,
# timeout) answers "not broken", so this can only ever ADD a fallback, never block a healthy host.
# ── no service may be given more CPUs than the host has ──────────────────────────────────────
# [2026-08-23] `docker compose up` ABORTS the whole bring-up on this, it does not warn:
#     range of CPUs is from 0.01 to 4.00, as there are only 4 CPUs available
# and the profiles themselves are the source. Measured against their OWN declared envelopes:
#     ci-small  requires 1 core  ->  APITOOLS_CPUS 2.0    over-subscribed
#     laptop    requires 4 cores ->  APITOOLS_CPUS 5.0    over-subscribed
#     vps 3/3.0   prod 6/6.0   wsl-10g 5/4.0              ok
# So a 4-core machine selects `laptop` correctly, and then cannot start apitools. Clamping here
# rather than editing two numbers means a profile added later cannot reintroduce it, and an .env
# carried over from a bigger machine is corrected on this one too.
# Only ever lowers a value. A host with MORE cores than the profile asks for keeps the profile's
# number, because that is a deliberate choice about how much of the box a service may take.
bbox_clamp_cpus_to_host() {
  local env_file="${REPO_ROOT}/.env" n
  [ -f "${env_file}" ] || return 0
  n="$(ncores 2>/dev/null || nproc 2>/dev/null || echo 0)"
  [ "${n:-0}" -gt 0 ] || return 0
  python3 - "${env_file}" "${n}" <<'PYCLAMP'
import io, re, sys
path, cores = sys.argv[1], float(sys.argv[2])
src = io.open(path, encoding="utf-8", errors="replace").readlines()
pat = re.compile(r"^([A-Z0-9_]*CPUS)=([0-9]+(?:\.[0-9]+)?)\s*$")
changed = []
for k, ln in enumerate(src):
    m = pat.match(ln.rstrip())
    if not m:
        continue
    key, val = m.group(1), float(m.group(2))
    if val > cores:
        src[k] = "%s=%g" % (key, cores) + ln[len(ln.rstrip()):]
        changed.append("%s %g -> %g" % (key, val, cores))
if changed:
    io.open(path, "w", encoding="utf-8").writelines(src)
    print("clamped to %g core(s): %s" % (cores, ", ".join(changed)))
PYCLAMP
}


bbox_container_dns_broken() {
  [ -n "${BBOX_DNS_PROBED:-}" ] && return "${BBOX_DNS_BROKEN:-1}"
  export BBOX_DNS_PROBED=1 BBOX_DNS_BROKEN=1
  [ -n "${BBOX_ASSUME_DNS_OK:-}" ] && return 1
  command -v docker >/dev/null 2>&1 || return 1
  local img="${BBOX_DNS_PROBE_IMAGE:-busybox:latest}"
  timeout 60 docker run --rm "${img}" nslookup deb.debian.org >/dev/null 2>&1 && return 1
  # A second look before believing it: the probe image may simply be unpullable.
  timeout 30 docker run --rm "${img}" true >/dev/null 2>&1 || return 1
  export BBOX_DNS_BROKEN=0
  return 0
}


# Extra `docker build` flags for a proxied sandbox: share the HOST network (so the build can reach an
# egress proxy bound to host loopback — `docker compose build` can't do this, which is why the serial
# build shells out to `docker build`), and pass the proxy as the predefined proxy build-args that
# apt/pip/npm honour. Echoes a flag string (word-split by the caller); empty off-cloud → no change.
ccr_proxy_build_flags() {
  # [2026-08-23] --network host is needed for TWO reasons, and only one of them is a proxy.
  # The other is a host whose DEFAULT BRIDGE has no egress (docker0 pings but cannot open
  # TCP/443 or UDP/53), where the build must borrow the host's network to reach PyPI/npm at
  # all. Widening ccr_build_serial's gate alone was not enough: the flag is emitted HERE, so
  # without this the serial build ran with no --network at all and still died on
  #     ERROR: Could not find a version that satisfies the requirement fastapi==0.115.6
  # There is no proxy to pass build-args for in that case, so the flag is emitted alone.
  if ! ccr_have_proxy_ca; then
    bbox_container_dns_broken && printf -- '--network host'
    return 0
  fi
  local p="${HTTPS_PROXY:-${https_proxy:-}}"
  printf -- '--network host'
  [ -n "$p" ] && printf -- ' --build-arg https_proxy=%s --build-arg http_proxy=%s --build-arg HTTPS_PROXY=%s --build-arg HTTP_PROXY=%s' "$p" "$p" "$p" "$p"
}
# A Dockerfile RUN that flips Debian apt sources http→https. A strict egress proxy only tunnels
# HTTPS/CONNECT, so plain-HTTP apt gets 403; baked into shadowed debian/node bases so every apt in a
# build FROM them uses https (works transparently, or via the proxy build-args + host network above).
CCR_APT_HTTPS_RUN='RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do [ -f "$f" ] && sed -i "s#http://deb.debian.org#https://deb.debian.org#g; s#http://security.debian.org#https://security.debian.org#g" "$f" || true; done; true'

# Docs page describing Claude-Code-on-the-web environments + network policies.
CCR_WEB_DOCS="https://code.claude.com/docs/en/claude-code-on-the-web"
# Printed when a base image can't be pulled in the cloud sandbox — almost always the environment's
# network policy blocking container image registries / layer CDNs (Docker Hub, GHCR), which bbox
# cannot work around. `bbox run` turns this into a fast, clear failure instead of a cryptic deep-in-
# the-build CDN error. Sets CCR_REGISTRY_BLOCKED so the caller can stop before the doomed build.
ccr_egress_hint() {
  [ "${CCR_REGISTRY_BLOCKED:-0}" = 1 ] && return 0   # print once
  CCR_REGISTRY_BLOCKED=1
  bad "cannot pull base images — this environment's network policy is blocking container image"
  bad "registries / layer CDNs (Docker Hub, GHCR). bbox can't build without them."
  bad "Fix: recreate this Claude Code web environment with a network policy that ALLOWS container"
  bad "registries, then re-run. Docs: ${CCR_WEB_DOCS}   (Windows/VPS are unaffected.)"
}

# The base images this office builds from, one per line: every FROM of every Dockerfile the RENDERED
# compose project builds (it names each build's context and file, so no list of directories can go
# stale — the old one globbed production/ and development/, which the platform-OS refactor removed,
# and from then on only n8n was shadowed), multi-stage builder bases included, stage names and
# `scratch` not; plus the n8n image, whose FROM is an ARG and is pinned by N8N_VERSION.
# Ends with `|| true`: callers run under `set -euo pipefail` and an empty list is a legitimate answer.
ccr_bases() {
  { dcx config --format json 2>/dev/null | python3 -c '
import json, os, re, sys
for s in json.load(sys.stdin).get("services", {}).values():
    b = s.get("build") or {}
    text = b.get("dockerfile_inline") or ""
    if not text and b.get("context"):
        try: text = open(os.path.join(b["context"], b.get("dockerfile") or "Dockerfile"), encoding="utf-8").read()
        except OSError: pass
    stages = {"scratch"}
    for m in re.finditer(r"^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", text, re.M | re.I):
        if m.group(1) not in stages and "$" not in m.group(1): print(m.group(1))
        if m.group(2): stages.add(m.group(2))
' 2>/dev/null; echo "n8nio/n8n:$(read_env N8N_VERSION)"; } | sort -u || true
}

# Re-tag each base image with the proxy CA injected, so every `FROM` in a build inherits trust
# (no product Dockerfile is edited). Handles debian/slim, alpine, and the hardened n8nio/n8n image.
# NO-OP when no proxy CA is present. Shared by bbox run / ui-map / baseline.
ccr_shadow_bases() {
  ccr_have_proxy_ca || return 0
  local ca="${PROXY_CA}" sdir; sdir="$(mktemp -d)"; cp "$ca" "${sdir}/ccr-ca.crt"
  local CAP=/etc/ssl/certs/ca-certificates.crt RAW=/usr/local/share/ca-certificates/ccr-proxy.crt
  local ENVS="ENV PIP_CERT=${CAP} REQUESTS_CA_BUNDLE=${CAP} SSL_CERT_FILE=${CAP} NODE_EXTRA_CA_CERTS=${CAP} GIT_SSL_CAINFO=${CAP} CURL_CA_BUNDLE=${CAP} npm_config_cafile=${CAP}"
  local bases n=0 b; bases="$(ccr_bases)"
  # n8n's base ALONE means the compose half did not answer (a render that failed, an engine not up
  # yet): every office builds first-party images. Said, because "shadowed only n8n" and "shadowed
  # everything" print the same nothing, and that is how every other build once lost the proxy CA
  # (issues/ccr-shadow-bases-lost-its-base-list-in-the-layout-refactor.yaml).
  [ "$(printf '%s\n' "${bases}" | grep -c .)" -gt 1 ] \
    || warn "could not derive the base images from the compose project — only n8n's base will trust the proxy CA, and every other build will fail on TLS"
  for b in $bases; do
    docker image inspect "$b" >/dev/null 2>&1 || docker pull "$b" >/dev/null 2>&1 || { warn "cannot fetch base $b — skipping shadow"; ccr_egress_hint; continue; }
    if printf '%s' "$b" | grep -qiE 'alpine'; then
      printf 'FROM %s\nCOPY ccr-ca.crt %s\nRUN cat %s >> %s 2>/dev/null || true\nENV NODE_EXTRA_CA_CERTS=%s npm_config_cafile=%s SSL_CERT_FILE=%s GIT_SSL_CAINFO=%s\n' "$b" "$RAW" "$RAW" "$CAP" "$RAW" "$RAW" "$RAW" "$RAW" > "${sdir}/Dockerfile"
    elif printf '%s' "$b" | grep -qiE 'n8nio/n8n'; then
      # hardened image: no shell/apk to merge the CA into the system bundle → point node/npm/git
      # straight at the copied CA file (NODE_EXTRA_CA_CERTS is additive over the built-in roots).
      printf 'FROM %s\nCOPY ccr-ca.crt %s\nENV NODE_EXTRA_CA_CERTS=%s SSL_CERT_FILE=%s npm_config_cafile=%s GIT_SSL_CAINFO=%s CURL_CA_BUNDLE=%s\nUSER node\n' "$b" "$RAW" "$RAW" "$RAW" "$RAW" "$RAW" "$RAW" > "${sdir}/Dockerfile"
    else
      printf 'FROM %s\nCOPY ccr-ca.crt %s\n%s\nRUN command -v update-ca-certificates >/dev/null 2>&1 || (apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*); cat %s >> %s 2>/dev/null || true; update-ca-certificates 2>/dev/null || true\n%s\n' "$b" "$RAW" "$CCR_APT_HTTPS_RUN" "$RAW" "$CAP" "$ENVS" > "${sdir}/Dockerfile"
    fi
    # shellcheck disable=SC2046,SC2086 — proxy flags are intentionally word-split; empty off-cloud.
    docker build $(ccr_proxy_build_flags) -q -t "$b" -f "${sdir}/Dockerfile" "${sdir}" >/dev/null 2>&1 && { n=$((n+1)); } || warn "shadow build failed for ${b}"
  done
  rm -rf "${sdir}"
  [ "$n" -gt 0 ] && log "proxy CA → CA-shadowed ${n} base image(s) so in-container pip/npm/git trust it"
  return 0
}

# n8n-postgres requests a high nofile ulimit (compose default hard 262144). A sandbox host may cap
# the hard limit far lower; docker then REFUSES TO START the container ("operation not permitted
# setting rlimit"), which aborts the whole `up`. When the host hard limit is below the request,
# export a capped PG_NOFILE_* for this process so compose asks for something the kernel allows.
# NO-OP when the host limit already meets the request or reports "unlimited" (normal laptop/VPS).
ccr_clamp_nofile() {
  local hard; hard="$(ulimit -Hn 2>/dev/null)"
  case "${hard}" in ''|unlimited|*[!0-9]*) return 0 ;; esac
  local want="${PG_NOFILE_HARD:-262144}"; case "${want}" in *[!0-9]*) want=262144 ;; esac
  if [ "${hard}" -lt "${want}" ]; then
    export PG_NOFILE_HARD="${hard}"
    local soft="${PG_NOFILE_SOFT:-1024}"; [ "${soft}" -gt "${hard}" ] && soft="${hard}"
    export PG_NOFILE_SOFT="${soft}"
    warn "host nofile hard limit ${hard} < requested ${want} → PG_NOFILE_HARD=${hard} for this run (else n8n-postgres won't start)"
  fi
  return 0
}

# browser42's base is DIGEST-PINNED (cloakhq/cloakbrowser@sha256:…), so the CA-shadow cannot retag
# it to trust a MITM proxy: its build fails on a proxied sandbox and, because compose builds during
# `up`, aborts the WHOLE bring-up.
#
# This used to drop the `browser42` compose profile. That profile is GONE — it was a second switch
# for whether the app runs, underneath platform.state.yaml, and it silently produced an app that
# was enabled, compiled in, routed, and had no containers (gate G22). browser42 now ships
# `enabled: false` like every other gallery app, so a plain `bbox run` never builds it and the
# sandbox needs no accommodation.
#
# Kept as a WARNING rather than deleted: if an operator enables browser42 on a proxied host they
# should be told why the build is about to fail, instead of silently having their choice reverted.

# Free GiB available on the writable filesystem (0 if it can't be read).
ccr_disk_avail_gb() { df -P "${REPO_ROOT}" 2>/dev/null | awk 'NR==2{print int($4/1048576)}' || echo 0; }

# Build the first-party images ONE AT A TIME (proxied envs only), via `docker build --network host`
# so their `apt-get`/`pip`/`npm` reach a host-loopback egress proxy (`docker compose build` can't set
# the network, and a strict proxy rejects plain-HTTP apt with 403 — the shadowed bases already switch
# apt to https). Serial also avoids the concurrent-npm OOM ("Exit handler never called") on a small
# host, and between builds it reclaims build cache whenever free disk dips below CCR_DISK_MIN_GB
# (default 6) so the small cloud allowance doesn't fill to 100%. Returns non-zero if any build failed.
# NO-OP off-cloud (the caller's normal parallel `docker compose build --pull` path stays as-is).
#
# WHICH services get built is not a list anyone maintains: it is every service the compiled compose
# gives a `build:`. It used to be CCR_FIRSTPARTY_BUILD, thirteen names typed by hand in this file —
# which meant layer 0 named thirteen layer-3 apps (gate G31), and meant adding an app silently
# excluded it from the serial build until someone remembered to come back here. `homepage` needed a
# comment explaining its absence; now it is absent because it has no `build:`, which is the actual
# reason. Pass explicit service names to override.
ccr_build_serial() {
  # [2026-08-23] Runs for TWO reasons now, not one. The original was a proxied cloud
  # sandbox. The second is a host whose DEFAULT BRIDGE has no egress: measured on
  # portable-ubuntu, a docker0 container pings 1.1.1.1 but cannot open TCP/443 or UDP/53,
  # while the stack's own user-defined network reaches both. Nothing the platform RUNS
  # notices, because every service is on traefik-network -- only `docker build`, which
  # uses docker0, fails, ~22 services deep inside a pip install.
  # Building over the host network is not a workaround for a broken host: it is the
  # same choice this function already makes for the proxy case, for the same reason
  # (`docker compose build` cannot set a build network, which is why this shells out).
  ccr_have_proxy_ca || bbox_container_dns_broken || return 0
  local svcs="$*" rc=0
  log "proxied env → building first-party images serially (host network, proxy-aware apt)${svcs:+: ${svcs}}"
  # Resolve each service's build context/dockerfile/image/args from the merged compose config once.
  # The parser goes in a tempfile: `cmd | python3 - <<PY` would give python the HEREDOC as stdin, not
  # the piped JSON — so load the script from a file and let the pipe be stdin.
  local pyf; pyf="$(mktemp)"
  cat > "${pyf}" <<'PY'
import sys, json, shlex
try: data = json.load(sys.stdin)
except Exception: sys.exit(0)
services = data.get("services", {}) or {}
# No explicit selection = every service the COMPILED compose says is built from source. The
# `if not b: continue` below is what excludes prebuilt images, so the set needs no hand-kept list.
sel = sys.argv[1].split() if len(sys.argv) > 1 and sys.argv[1].strip() else list(services)
for s in sel:
    svc = services.get(s, {})
    b = svc.get("build")
    if not b: continue
    if isinstance(b, str): ctx, df, args = b, "Dockerfile", {}
    else:
        ctx = b.get("context", "."); df = b.get("dockerfile", "Dockerfile"); args = b.get("args", {}) or {}
    if isinstance(args, list):
        args = {k: v for a in args for k, _, v in [a.partition("=")]}
    img = svc.get("image") or ("deployment-hacohen-" + s)
    argflags = " ".join("--build-arg " + shlex.quote("%s=%s" % (k, v)) for k, v in args.items())
    print("\t".join([s, img, ctx, df, argflags]))
PY
  local specs; specs="$( dcx config --format json 2>/dev/null | python3 "${pyf}" "$svcs" 2>/dev/null || true)"
  rm -f "${pyf}"
  # [2026-08-23] THIS FALLBACK CANNOT CARRY THE HOST-NETWORK ACCOMMODATION, and that is not
  # fixable by adding a flag: `docker compose build` has no per-service --network, which is the
  # whole reason the loop below shells out to `docker build` instead. So on a host whose default
  # bridge has no egress, this path builds with no working network and dies on package
  # downloads. It says so now rather than reporting a plain "build failed" ten minutes later.
  if [ -z "${specs}" ]; then
    warn "could not resolve build specs (python/compose) — falling back to compose build"
    if bbox_container_dns_broken; then
      warn "  ...and this host has NO container egress on the default bridge. compose build"
      warn "  cannot be given --network host, so package downloads will fail. Fix the spec"
      warn "  resolution (python3 + dcx config --format json) rather than trusting this build."
    fi
    dcx build ${svcs} || rc=1
    return "$rc"
  fi
  local pflags; pflags="$(ccr_proxy_build_flags)"
  local s img ctx df argflags
  while IFS=$'\t' read -r s img ctx df argflags; do
    [ -n "$s" ] || continue
    if [ "$(ccr_disk_avail_gb)" -lt "${CCR_DISK_MIN_GB:-6}" ]; then
      warn "low disk ($(ccr_disk_avail_gb) GiB free) → pruning build cache before ${s}"
      docker builder prune -f >/dev/null 2>&1 || true
    fi
    # shellcheck disable=SC2086 — pflags/argflags are intentionally word-split.
    if docker build ${pflags} ${argflags} -t "${img}" -f "${ctx}/${df}" "${ctx}"; then ok "built ${s}"; else bad "build failed: ${s}"; rc=1; fi
  done <<EOF
${specs}
EOF
  docker builder prune -f >/dev/null 2>&1 || true   # reclaim intermediate layers before bring-up
  return "$rc"
}
