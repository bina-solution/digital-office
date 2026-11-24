#!/usr/bin/env bash
# test_as_host_root.sh — scripts/as-host-root.sh: root on THIS host with the access the office has (DGO-1848).
#
#     bash scripts/test_as_host_root.sh
#
# `id`, `sudo`, `uname`, `stat`, `logger` and `docker` are stand-ins on a CLOSED PATH (never the machine's own sudo)
# that log every call. The engine's stand-in really RUNS what follows `nsenter … --` — the helper's own inner check
# and the command — so each case is read from what was run and with which arguments, exactly. The working directory's
# name ends in a space, as this checkout's does. No root, no engine, no network.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AHR="${HERE}/as-host-root.sh"
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
BASE="$(mktemp -d)"; trap 'rm -rf "${BASE}"' EXIT
TMP="${BASE}/work dir "; mkdir -p "${TMP}"
BIN="${BASE}/bin"; TOOLS="${BASE}/tools"; mkdir -p "${BIN}" "${TOOLS}"
for t in sh bash env touch true grep cat ls; do ln -s "$(command -v "${t}")" "${TOOLS}/${t}"; done
LOG="${BASE}/calls"; BOOT="${BASE}/boot_id"

stub() {   # $1 name, $2 body (sh)
  printf '#!/bin/sh\necho "%s $*" >> "%s"\n%s\n' "$1" "${LOG}" "$2" > "${BIN}/$1"; chmod +x "${BIN}/$1"
}
setup() {
  rm -f "${LOG}" "${BIN}"/*; : > "${LOG}"; echo "boot-1" > "${BOOT}"
  find "${TMP}" -mindepth 1 -delete 2>/dev/null
  stub id 'case "$1" in -u) echo "${UID_:-1000}";; -un) echo owner;; esac'
  [ "${SUDO}" = none ] || stub sudo '[ "$1" = -n ] && [ "$2" = true ] && { [ "${SUDO}" = ok ]; exit $?; }; shift; exec "$@"'
  stub uname 'case "$1" in -s) echo "${OS}";; -n) echo "${HOST}";; esac'
  stub stat '[ -n "${INSIDE:-}" ] && echo "${DEVINO_IN}" || echo "1:2"'
  stub logger 'true'
  stub timeout 'shift; exec "$@"'
  # the engine: `info`, `context inspect`, `image inspect`, `pull`; `run` drops what is before `--`, gives the inner
  # env this PATH (the real one names /usr/bin), writes the case's boot as the kernel the inside sees, runs the rest
  cat > "${BIN}/docker" <<EOF
#!${TOOLS}/bash
printf 'docker %s\n' "\$*" >> "${LOG}"
case "\$1" in
  info) case "\$3" in
          "{{.Name}}") [ -n "\${ENGINE_NAME}" ] || exit 1; echo "\${ENGINE_NAME}" ;;
          *) [ -n "\${SECOPTS}" ] && echo "\${SECOPTS}" ;;
        esac ;;
  context) echo "\${CONTEXT_HOST}" ;;
  image) [ -n "\${HAVE_IMAGE}" ] ;;
  pull) [ -n "\${CAN_PULL}" ] ;;
  run) while [ \$# -gt 0 ] && [ "\$1" != -- ]; do shift; done; shift
       out=()
       for a in "\$@"; do case "\$a" in PATH=*) out+=("PATH=\${PATH}") ;; *) out+=("\$a") ;; esac; done
       echo "\${BOOT_IN:-boot-1}" > "${BOOT}"
       INSIDE=1 exec "\${out[@]}" ;;
esac
EOF
  chmod +x "${BIN}/docker"
}
run() {   # the helper on the closed PATH, in TMP; echoes its rc
  ( cd "${TMP}" && env -i PATH="${BIN}:${TOOLS}" HOME="${BASE}" SUDO="${SUDO}" UID_="${UID_:-1000}" OS="${OS}" \
      HOST="${HOST}" ENGINE_NAME="${ENGINE_NAME}" SECOPTS="${SECOPTS}" CONTEXT_HOST="${CONTEXT_HOST}" \
      HAVE_IMAGE="${HAVE_IMAGE}" CAN_PULL="${CAN_PULL}" DEVINO_IN="${DEVINO_IN}" BOOT_IN="${BOOT_IN}" \
      AS_ROOT_BOOT_ID="${BOOT}" AS_ROOT_ENV="${AS_ROOT_ENV:-}" AA_PULL=1 \
      ${DOCKER_HOST_:+DOCKER_HOST="${DOCKER_HOST_}"} ${OPT_IN:+DGO_HOST_ROOT_VIA_DOCKER="${OPT_IN}"} \
      bash "${AHR}" "$@" ) > "${BASE}/out" 2>&1
  echo $?
}
ran() { grep -q -- "$1" "${LOG}"; }
# the Dell's shape: no sudo password, this host's engine, the office opted in
dell() {
  SUDO=ask OS=Linux HOST=dell ENGINE_NAME=dell SECOPTS='["name=apparmor","name=seccomp"]' CONTEXT_HOST=unix:///var/run/docker.sock
  HAVE_IMAGE=1 CAN_PULL="" DEVINO_IN=1:2 BOOT_IN=boot-1 OPT_IN=1 DOCKER_HOST_="" UID_=1000 AS_ROOT_ENV=""
}

# 1. already root: the command itself
dell; UID_=0; setup; rc="$(run touch marker-root)"
[ "${rc}" = 0 ] && [ -e "${TMP}/marker-root" ] && ! ran "^docker run" && ok "root: the command runs itself" \
  || no "root (rc ${rc}; $(cat "${BASE}/out"))"

# 2. passwordless sudo: through it, with the named variables
dell; SUDO=ok; AS_ROOT_ENV=AA_PULL; setup; rc="$(run touch marker-sudo)"
[ "${rc}" = 0 ] && ran "^sudo -n env AA_PULL=1 touch marker-sudo" && [ -e "${TMP}/marker-sudo" ] && ! ran "^docker run" \
  && ok "passwordless sudo: through sudo, AS_ROOT_ENV carried" || no "passwordless sudo (rc ${rc}; $(cat "${LOG}"))"

# 3. the Dell: through the engine, nsenter into PID 1, in THIS directory, every argument exactly. `touch --`: GNU's
# touch reads an option anywhere on its line, so on Linux «-n» was its option (and refused) before it was a file —
# found when the CI runner first ran this suite (batch 112, DGO-2123); BSD's touch stops at the first file name. And the
# names in C order: GNU's ls sorts by the locale, which sets «-n» after «c'd»
dell; AS_ROOT_ENV=AA_PULL; setup; rc="$(run touch -- "a b" "c'd" '$(x)' "-n")"
names="$(cd "${TMP}" && LC_ALL=C ls -A | tr '\n' '|')"
[ "${rc}" = 0 ] && [ "${names}" = '$(x)|-n|a b|c'"'"'d|' ] && ok "the engine's way: in this directory (its name ends in a space), each argument exactly" \
  || no "the engine's way (rc ${rc}; files «${names}»; $(cat "${BASE}/out"))"
line="$(grep '^docker run' "${LOG}")"
case "${line}" in
  *"--privileged --userns=host --pid=host --network host --pull never alpine:3.20@sha256:"*"nsenter -t 1 -m -u -i -n -p --"*"AA_PULL=1"*)
    ok "…a pinned image, never pulled at run, the host's user namespace, AA_PULL handed on" ;;
  *) no "…the run was «${line}»" ;;
esac
grep -q "through its own docker engine" "${BASE}/out" && ran "^logger -t dgo-as-host-root" \
  && ok "…said, and logged to the host's journal" || no "…said and logged: $(cat "${BASE}/out")"

# the refusals: rc 3, nothing run (no docker run, no file), the reason said
refused() {   # $1 name, $2 the words; the case is already set
  local rc; setup; rc="$(run touch marker-x)"
  if [ "${rc}" = 3 ] && ! ran "^docker run" && [ ! -e "${TMP}/marker-x" ] && grep -q -- "$2" "${BASE}/out" \
     && grep -q "nothing was run. Run it as root: sudo touch marker-x" "${BASE}/out"; then
    ok "$1: refused (3), nothing run, says «$2»"
  else
    no "$1: rc ${rc}; $(cat "${BASE}/out")"
  fi
}
dell; OPT_IN="";                          refused "an office that did not opt in (a client's server)" "does not declare root through its docker engine"
dell; SUDO=none; OPT_IN="";               refused "…with no sudo at all" "does not declare"
dell; ENGINE_NAME=docker-desktop;         refused "another machine's engine (Docker Desktop)" "another machine's"
dell; DOCKER_HOST_="ssh://root@dell";     refused "a remote engine of the same name, by DOCKER_HOST" "DOCKER_HOST is not a local socket"
dell; CONTEXT_HOST="tcp://10.0.0.5:2376"; refused "a remote engine of the same name, by the docker context" "the docker context is not a local socket"
dell; OS=Darwin;                          refused "a Mac (its engine is a VM)" "not a Linux host"
dell; SECOPTS='["name=rootless"]';        refused "a rootless engine" "rootless"
dell; SECOPTS="";                         refused "an engine that does not say how it runs" "does not say how it runs"
dell; ENGINE_NAME="";                     refused "no engine answers" "no docker engine answers"
dell; HAVE_IMAGE="";                      refused "no helper image and none to pull (offline)" "helper image could not be had"

# pulled once when absent
dell; HAVE_IMAGE=""; CAN_PULL=1; setup; rc="$(run touch marker-pull)"
[ "${rc}" = 0 ] && ran "^docker pull -q alpine:3.20@sha256:" && [ -e "${TMP}/marker-pull" ] \
  && ok "an absent helper image is pulled first (by digest)" || no "absent image pulled (rc ${rc}; $(cat "${BASE}/out"))"

# inside, not the same directory or not the same boot: nothing run
dell; DEVINO_IN=9:9; setup; rc="$(run touch marker-in)"
[ "${rc}" = 3 ] && [ ! -e "${TMP}/marker-in" ] && grep -q "not the same directory on the same host" "${BASE}/out" \
  && ok "inside, another directory of the same name: refused (3), nothing run" || no "inside, another directory (rc ${rc}; $(cat "${BASE}/out"))"
dell; BOOT_IN=boot-2; setup; rc="$(run touch marker-in)"
[ "${rc}" = 3 ] && [ ! -e "${TMP}/marker-in" ] && grep -q "not the same directory on the same host" "${BASE}/out" \
  && ok "inside, another kernel: refused (3), nothing run" || no "inside, another kernel (rc ${rc}; $(cat "${BASE}/out"))"

# a variable name that is not a name is never handed on (nor $1 by an all-digit «name»)
dell; SUDO=ok; AS_ROOT_ENV='AA_PULL $(touch pwned) X-Y 1'; setup; rc="$(run true)"
! ran "pwned" && [ ! -e "${TMP}/pwned" ] && ran "^sudo -n env AA_PULL=1 true$" \
  && ok "AS_ROOT_ENV: only names are handed on" || no "AS_ROOT_ENV names ($(cat "${LOG}"))"

# no command: usage, nothing run
dell; SUDO=ok; setup; rc="$(run)"
[ "${rc}" = 2 ] && ! ran "^sudo -n env" && ok "no command: usage (2)" || no "no command (rc ${rc})"

echo "${fails} failed"
exit $(( fails > 0 ))
