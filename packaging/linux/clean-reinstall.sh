#!/usr/bin/env bash
# clean-reinstall.sh — wipe every trace of a previous BinaOS install, then install and prove.
#
#   sudo bash clean-reinstall.sh /path/to/BinaOS-<ver>-linux-amd64.run
#
# WHY A WIPE AND NOT A REPAIR
#
# Testing an upgrade on top of a half-broken install proves nothing about the artifact. The portable
# machine had three start attempts killed mid-run, which left authentik's database with 22 of its
# several hundred migrations applied — enough state that authentik believed it was an existing
# install and tried `tenant_to_brand`, which then died on a table that a fresh database never has:
#
#     psycopg.errors.UndefinedTable: relation "authentik_tenants_tenant" does not exist
#
# That is interrupted-migration damage, not a defect in the executable. The only way to learn
# whether the artifact works is to give it the same blank machine a customer would.
#
# The BinaOS engine is a PRIVATE instance — its own socket, data-root and containerd namespace — so
# wiping it cannot touch the host's own Docker containers, images or volumes.
set -uo pipefail

RUN="${1:?usage: clean-reinstall.sh <artifact.run>}"
LOG=/tmp/binaos-clean.log

# REFUSE to run alongside another install. Two of these overlapping produced a genuinely confusing
# hour: the first was killed by its wrapper but its children kept going, finished installing, wrote
# an install receipt, and then deleted the staging directory out from under the second - which died
# with `tar: /opt/binaos/.staging: No such file or directory`. Both wrote to this same log, so the
# file interleaved two runs and read as one that decided two contradictory things at once.
#
# A LOCK, not a pgrep pattern. The first version of this guard scanned the process list for
# "BinaOS-.*\.run" and matched the ssh command line that was launching it - the artifact name
# appears as an argument there - so it refused to start because of itself. Matching process
# command lines to answer "am I already running" is guesswork; a lock answers it exactly.
LOCK=/var/lock/binaos-install.lock
exec 9>"${LOCK}" || { echo "cannot open ${LOCK}" >&2; exit 1; }
if ! flock -n 9; then
  echo "refusing to start: another install holds ${LOCK}" >&2
  echo "wait for it to finish, or: sudo pkill -f 'BinaOS-.*[.]run'" >&2
  exit 1
fi
# The lock is released when this script exits and fd 9 closes, including on kill.

exec > >(tee "${LOG}") 2>&1
echo "=== $(date -u +%FT%TZ) clean reinstall on $(hostname) ==="

step() { printf '\n=== %s ===\n' "$*"; }
SOCK=unix:///run/binaos-docker.sock

step "1. stop the stack"
systemctl stop binaos 2>/dev/null
echo "binaos unit: $(systemctl is-active binaos 2>/dev/null)"

step "2. remove every container and volume on the PRIVATE engine"
# Scoped to this block ONLY, never exported. The installer probes for a usable engine by asking
# `docker version` what the host has, and it inherits this process's environment - so exporting
# DOCKER_HOST here made that probe answer with OUR private engine (28.5.2) instead of the host's
# real one (29.1.3). The installer concluded the machine already had a good Docker, skipped landing
# its own, wrote no engine.env, and left the socket mounts pointing at the host daemon - which has
# none of our images. A wipe script silently changing what the thing under test detects is exactly
# the kind of test-harness bug that gets mistaken for a product bug.
if DOCKER_HOST="${SOCK}" docker info >/dev/null 2>&1; then
  export DOCKER_HOST="${SOCK}"
  ids=$(docker ps -aq)
  [ -n "${ids}" ] && docker rm -f ${ids} >/dev/null 2>&1
  echo "  containers removed: $(echo "${ids}" | grep -c . 2>/dev/null || echo 0)"
  vols=$(docker volume ls -q)
  [ -n "${vols}" ] && docker volume rm -f ${vols} >/dev/null 2>&1
  echo "  volumes removed:    $(echo "${vols}" | grep -c . 2>/dev/null || echo 0)"
  echo "  left behind:        $(docker ps -aq | wc -l) container(s), $(docker volume ls -q | wc -l) volume(s)"
else
  echo "  private engine not reachable — nothing to clear"
fi

step "3. remove the installed tree"
rm -rf /opt/binaos /etc/binaos
echo "  /opt/binaos exists: $([ -e /opt/binaos ] && echo yes || echo no)"
echo "  /etc/binaos exists: $([ -e /etc/binaos ] && echo yes || echo no)"

# The installer must see the machine exactly as a customer's would. Anything step 2 set would
# otherwise decide, invisibly, which engine it detects.
unset DOCKER_HOST
echo "  DOCKER_HOST cleared; host engine reads as: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo none)"

step "4. verify the artifact before trusting it"
chmod +x "${RUN}"
"${RUN}" --check || { echo "FAILED: --check"; exit 1; }

step "5. install"
"${RUN}" || { echo "FAILED: install"; exit 1; }

# systemd's EnvironmentFile format — no `export` keyword — so this is a plain KEY=VALUE file.
[ -f /etc/binaos/engine.env ] && . /etc/binaos/engine.env
export DOCKER_HOST="${DOCKER_HOST:-${SOCK}}"
echo "using DOCKER_HOST=${DOCKER_HOST}"

step "6. start"
systemctl start binaos || echo "unit start returned non-zero — reporting what actually came up"

step "7. wait for the stack to settle"
# authentik migrates a fresh database on first boot and everything with SSO waits on it, so the
# ceiling here is minutes, not seconds. Report every poll rather than only the outcome.
for i in $(seq 1 60); do
  r=$(docker ps -q 2>/dev/null | wc -l)
  h=$(docker ps -q -f health=healthy 2>/dev/null | wc -l)
  u=$(docker ps -q -f health=unhealthy 2>/dev/null | wc -l)
  echo "  t+$((i*15))s: running=${r} healthy=${h} unhealthy=${u}"
  [ "${u}" = "0" ] && [ "${h}" -ge 15 ] && break
  sleep 15
done

step "8. what is up"
docker ps --format '{{.Names}}\t{{.Status}}' | sort
echo "--- $(docker ps -q | wc -l) running, $(docker ps -q -f health=healthy | wc -l) healthy, $(docker ps -q -f health=unhealthy | wc -l) unhealthy ---"

step "9. routes"
fail=0
for h in console apps n8n drive mail my-docs incoming-documents; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  case "${code}" in
    200|302|307|401|403) printf '  ok   %-22s %s\n' "${h}.localhost" "${code}" ;;
    *) printf '  FAIL %-22s %s\n' "${h}.localhost" "${code}"; fail=$((fail+1)) ;;
  esac
done

echo
echo "=== done: $(docker ps -q | wc -l) running, $(docker ps -q -f health=unhealthy | wc -l) unhealthy, ${fail} route failure(s) ==="
