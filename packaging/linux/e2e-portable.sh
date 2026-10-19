#!/usr/bin/env bash
# e2e-portable.sh — install the single executable on this machine, bring the stack up, prove it.
#
#   sudo bash e2e-portable.sh /path/to/BinaOS-<ver>-linux-amd64.run
#
# Runs ON the target. Every step reports what it actually observed rather than assuming the
# previous one worked — this whole exercise exists because ten separate things reported success
# while doing nothing.
set -uo pipefail

RUN="${1:?usage: e2e-portable.sh <artifact.run>}"
LOG=/tmp/binaos-e2e.log
exec > >(tee -a "${LOG}") 2>&1
echo "=== $(date -u +%FT%TZ) e2e on $(hostname) ==="

step() { printf '\n=== %s ===\n' "$*"; }

step "1. integrity"
"${RUN}" --check || { echo "FAILED: --check"; exit 1; }

step "2. install"
"${RUN}" || { echo "FAILED: install"; exit 1; }

# The installer writes this when it lands its own engine; without it we would talk to the host's.
[ -f /etc/binaos/engine.env ] && . /etc/binaos/engine.env
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/binaos-docker.sock}"
echo "using DOCKER_HOST=${DOCKER_HOST}"

step "3. start the stack"
systemctl start binaos || echo "unit start returned non-zero — checking what actually came up"

step "4. wait for containers"
for i in $(seq 1 40); do
  n=$(docker ps -q 2>/dev/null | wc -l)
  echo "  t+$((i*15))s: ${n} running"
  [ "${n}" -ge 25 ] && break
  sleep 15
done

step "5. what is up"
docker ps --format '{{.Names}}\t{{.Status}}' | sort | head -40
echo "--- total: $(docker ps -q | wc -l) running, $(docker ps -q -f health=healthy | wc -l) healthy ---"

step "6. routes answer"
fail=0
for h in console apps n8n drive mail my-docs incoming-documents; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: ${h}.localhost" http://127.0.0.1/ 2>/dev/null)
  case "${code}" in
    200|302|307|401|403) printf '  ok   %-22s %s\n' "${h}.localhost" "${code}" ;;
    *) printf '  FAIL %-22s %s\n' "${h}.localhost" "${code}"; fail=$((fail+1)) ;;
  esac
done

step "7. ui-map"
# Deliberately NOT in the installed tree. bbox derives its denominator from application source, and
# stage-control ships the runtime tree only — a customer never screenshots their own platform. The
# stack under test comes from the executable; the mapper comes from a repo copy:
#
#     sudo bash uimap-portable.sh /home/shlomy/binaos-repo
echo "  run uimap-portable.sh against a repo copy — see that script for why it is separate."

echo
echo "=== done: $(docker ps -q | wc -l) containers, ${fail} route failure(s) ==="
