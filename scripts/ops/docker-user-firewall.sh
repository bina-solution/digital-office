#!/bin/bash
# Restrict externally-reachable Docker published ports to 80/443 + 25 (SMTP) + the DGO link's UDP port.
# Docker bypasses ufw, so this chain is the actual enforcement point.
#
# Installed on vps1 as /usr/local/sbin/docker-user-firewall.sh, run at boot by
# docker-user-firewall.service (After/Requires=docker.service, oneshot). This file is its tracked copy.
#
# 25 is open because this host runs a real MTA and mail delivery REQUIRES the world to connect
# inbound — an MX record that nothing can reach is a mailbox that silently loses mail. Senders
# retry for days before bouncing, so the failure is slow and invisible.
#
# 587/993 are deliberately NOT opened: the MTA has no TLS certificate yet (SSL_TYPE empty), and
# publishing submission/IMAPS without one puts plaintext credentials on the public internet.
#
# The DGO link's UDP port is admitted when the office publishes one on every interface
# (DGO_WG_PUBLISH_BIND=0.0.0.0 + DGO_WG_PUBLISH_PORT in its .env — apps/dgo-extend/hooks/prepare
# derives both from the pair this office listens in). Read from that .env, so the port the office
# publishes and the port this gate admits are one fact. Without it a paired office's handshakes reach
# the server and die here (hp-laptop → vps1, 2026-10-15 → 10-19; issues/dgos-vps-stopped-publishing-
# the-hp-pairs-port-after-its-env-was-rebuilt.yaml). WireGuard answers only keys it was given.
#
# The video meetings' bridge UDP port (apps/meet, DGO-824) is admitted the same way and for the same
# reason: it is the one media path, it cannot go through the edge, and apps/meet/hooks/prepare
# publishes it on every interface (MEET_JVB_BIND=0.0.0.0, MEET_JVB_PORT, default 10000) only on an
# office with a public domain. The bridge answers only ICE checks for a session it signalled.
#
# On every other server office scripts/ops/host-baseline.sh installs this file as a boot unit
# (docker-user-firewall.service) with OFFICE_ENV and DGO_PUBLIC_IFACE — the public interface — set for that
# server. Not `IFACE`: ifupdown and networkd-dispatcher export that name to their hooks, so a caller run from
# one would fence the interface that changed (even lo) and leave the public one open.
#
# The link's carry door (TCP, DGO_CARRY_PUBLISH_BIND=0.0.0.0 + DGO_CARRY_PUBLISH_PORT) is admitted the same way,
# and the link's WireGuard on compose's default port (51839) when the office publishes it with no port named.
set -e
PUBLIC_IFACE="${DGO_PUBLIC_IFACE:-eth0}"
# Fail CLOSED: the chain is flushed first, so a rule that fails part-way would otherwise leave it with
# no DROP at all and every published port (postgres and redis among them) open to the internet.
trap 'iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -j DROP 2>/dev/null; iptables -A DOCKER-USER -j RETURN 2>/dev/null' ERR
OFFICE_ENV="${OFFICE_ENV:-/root/digital-office/.env}"
env_value() { sed -n "s/^$1=//p" "${OFFICE_ENV}" 2>/dev/null | tail -1 | sed -E 's/[[:space:]]+#.*$//' | tr -d '"'"'"'\r '; }
DGO_PORT="$(env_value DGO_WG_PUBLISH_PORT)"
DGO_BIND="$(env_value DGO_WG_PUBLISH_BIND)"
[ "${DGO_BIND}" = "0.0.0.0" ] && DGO_PORT="${DGO_PORT:-51839}"
CARRY_PORT="$(env_value DGO_CARRY_PUBLISH_PORT)"
CARRY_BIND="$(env_value DGO_CARRY_PUBLISH_BIND)"
MEET_PORT="$(env_value MEET_JVB_PORT)"
MEET_PORT="${MEET_PORT:-10000}"
MEET_BIND="$(env_value MEET_JVB_BIND)"

iptables -F DOCKER-USER
iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
if [[ "${DGO_PORT}" =~ ^[0-9]{2,5}$ ]] && [ "${DGO_BIND}" = "0.0.0.0" ]; then
  iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p udp -m conntrack --ctorigdstport "${DGO_PORT}" -j RETURN
fi
if [[ "${CARRY_PORT}" =~ ^[0-9]{2,5}$ ]] && [ "${CARRY_BIND}" = "0.0.0.0" ]; then
  iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p tcp -m conntrack --ctorigdstport "${CARRY_PORT}" -j RETURN
fi
if [[ "${MEET_PORT}" =~ ^[0-9]{2,5}$ ]] && (( MEET_PORT >= 1024 && MEET_PORT <= 65535 )) && [ "${MEET_BIND}" = "0.0.0.0" ]; then
  iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p udp -m conntrack --ctorigdstport "${MEET_PORT}" -j RETURN
fi
iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p tcp -m conntrack --ctorigdstport 80  -j RETURN
iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p tcp -m conntrack --ctorigdstport 443 -j RETURN
iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -p tcp -m conntrack --ctorigdstport 25  -j RETURN
iptables -A DOCKER-USER -i "${PUBLIC_IFACE}" -j DROP
iptables -A DOCKER-USER -j RETURN
