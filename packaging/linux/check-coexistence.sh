#!/usr/bin/env bash
# check-coexistence.sh — prove the installed executable and the machine's own CI cannot disturb each
# other, and say plainly where they still CAN.
#
#   sudo bash check-coexistence.sh
#
# The portable machine runs a self-hosted GitHub Actions runner that builds and runs this same
# platform on the HOST Docker. The executable installs its own engine. Everything below is about
# whether those two can collide.
#
# Isolation is designed in at five points - socket, data-root, bridge, address pool and containerd
# namespace - so containers, images, volumes and networks cannot be shared or clobbered. The one
# thing that CANNOT be isolated by any of those is a published host PORT: two stacks both binding
# 0.0.0.0:80 is a real conflict, and whichever starts second simply fails.
set -uo pipefail

HOST_SOCK=/var/run/docker.sock
OURS=/run/binaos-docker.sock

hr() { printf '\n=== %s ===\n' "$*"; }

hr "the two engines"
for s in "${HOST_SOCK}" "${OURS}"; do
  if [ -S "$s" ]; then
    v=$(DOCKER_HOST="unix://$s" docker version --format '{{.Server.Version}}' 2>/dev/null)
    c=$(DOCKER_HOST="unix://$s" docker ps -q 2>/dev/null | wc -l)
    i=$(DOCKER_HOST="unix://$s" docker images -q 2>/dev/null | wc -l)
    vol=$(DOCKER_HOST="unix://$s" docker volume ls -q 2>/dev/null | wc -l)
    printf '  %-28s engine %-8s %3s container(s)  %3s image(s)  %3s volume(s)\n' "$s" "${v:-unreachable}" "$c" "$i" "$vol"
  else
    printf '  %-28s (absent)\n' "$s"
  fi
done

hr "storage is separate"
for d in /var/lib/docker /var/lib/binaos-docker; do
  printf '  %-26s %s\n' "$d" "$([ -d "$d" ] && du -sh "$d" 2>/dev/null | cut -f1 || echo absent)"
done

hr "networks are separate"
echo "  host bridges:   $(ip -o link show 2>/dev/null | grep -oE 'docker0|binaos0' | sort -u | tr '\n' ' ')"
echo "  our subnet:     $(ip -o -4 addr show binaos0 2>/dev/null | awk '{print $4}')"
echo "  docker0 subnet: $(ip -o -4 addr show docker0 2>/dev/null | awk '{print $4}')"

hr "the CI runner"
echo "  Runner.Listener: $(pgrep -c -f Runner.Listener) process(es)"
echo "  active jobs:     $(pgrep -c -f Runner.Worker) "
echo "  leaked log tails:$(pgrep -cf 'tail -n .1 -f /opt/actions-runner') (these pile up per job and pin the load average)"

hr "THE REAL COLLISION RISK: published ports"
# This is the one thing separate engines do NOT protect you from.
for p in 80 443 5432 6379; do
  who=$(ss -lntp 2>/dev/null | awk -v p=":$p" '$4 ~ p"$" {print $NF; exit}')
  printf '  :%-6s %s\n' "$p" "${who:-free}"
done
echo
echo "  Both stacks publish 80/443/5432/6379. Separate engines do not separate host ports, so"
echo "  whichever starts second fails to bind. If CI needs to run the platform on this machine"
echo "  while the executable is installed, one of them has to move - the executable's ports are"
echo "  the ones under our control, via the compose it installs."
