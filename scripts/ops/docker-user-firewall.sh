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
set -e
# Fail CLOSED: the chain is flushed first, so a rule that fails part-way would otherwise leave it with
# no DROP at all and every published port (postgres and redis among them) open to the internet.
trap 'iptables -A DOCKER-USER -i eth0 -j DROP 2>/dev/null; iptables -A DOCKER-USER -j RETURN 2>/dev/null' ERR
OFFICE_ENV="${OFFICE_ENV:-/root/deployment-hacohen/.env}"
env_value() { sed -n "s/^$1=//p" "${OFFICE_ENV}" 2>/dev/null | tail -1 | tr -d '"'"'"'\r '; }
DGO_PORT="$(env_value DGO_WG_PUBLISH_PORT)"
DGO_BIND="$(env_value DGO_WG_PUBLISH_BIND)"
MEET_PORT="$(env_value MEET_JVB_PORT)"
MEET_PORT="${MEET_PORT:-10000}"
MEET_BIND="$(env_value MEET_JVB_BIND)"

iptables -F DOCKER-USER
iptables -A DOCKER-USER -i eth0 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
if [[ "${DGO_PORT}" =~ ^[0-9]{2,5}$ ]] && [ "${DGO_BIND}" = "0.0.0.0" ]; then
  iptables -A DOCKER-USER -i eth0 -p udp -m conntrack --ctorigdstport "${DGO_PORT}" -j RETURN
fi
if [[ "${MEET_PORT}" =~ ^[0-9]{2,5}$ ]] && (( MEET_PORT >= 1024 && MEET_PORT <= 65535 )) && [ "${MEET_BIND}" = "0.0.0.0" ]; then
  iptables -A DOCKER-USER -i eth0 -p udp -m conntrack --ctorigdstport "${MEET_PORT}" -j RETURN
fi
iptables -A DOCKER-USER -i eth0 -p tcp -m conntrack --ctorigdstport 80  -j RETURN
iptables -A DOCKER-USER -i eth0 -p tcp -m conntrack --ctorigdstport 443 -j RETURN
iptables -A DOCKER-USER -i eth0 -p tcp -m conntrack --ctorigdstport 25  -j RETURN
iptables -A DOCKER-USER -i eth0 -j DROP
iptables -A DOCKER-USER -j RETURN
