#!/usr/bin/env bash
# scripts/ops/host-baseline.sh — a Linux server office's host posture, declared once and applied the same way on
# every server (DGO-1495: Exampleu's server, 2026-11-09; the plan it carries out: ai/context/dgo-security.md §3.5).
#
#   scripts/ops/host-baseline.sh check             # the host against this file, one line per fact
#                                                  #   exit 0 all ok · 1 drift · 2 refused (no public interface)
#                                                  #   · 3 ok but a revert is still ARMED
#   scripts/ops/host-baseline.sh apply             # back up, write, validate, reload — with a revert ARMED
#   scripts/ops/host-baseline.sh confirm           # disarm the revert once a NEW ssh login has worked
#   scripts/ops/host-baseline.sh revert <backup>   # put back exactly what apply replaced (the armed timer runs this)
#   scripts/ops/host-baseline.sh render            # print what apply would write
#
# What it declares — every value that differs per office is read from the office's .env (OFFICE_ENV):
# 1. SSH: keys only (PubkeyAuthentication yes, AuthenticationMethods any, no keyboard-interactive); root by key
#    only; no X11; 30 s to log in. A password is accepted only from HOST_SSH_PASSWORD_FROM (addresses, CIDRs or
#    sshd patterns, space- or comma-separated; empty = from nowhere). The drop-in is named 00-…, the first file
#    sshd reads, so it wins over a provider's 50-cloud-init.conf (sshd keeps a keyword's FIRST value).
# 2. No LLMNR and no mDNS: systemd-resolved answers name queries on 0.0.0.0:5355 by default (S14).
# 3. Only the office's doors answer on any interface but lo, docker0, docker's br-* bridges and a tunnel that ends on
#    the host (a WireGuard interface, tailscale0 — their listen ports stay open) (HOST_TRUSTED_IFACES adds more):
#    every port sshd answers on (`port` and `listenaddress` in `sshd -T`, its live listeners, ssh.socket), tcp 80
#    and 443, and what the office publishes on every
#    interface — tcp 25 (MAIL_BIND=0.0.0.0), the link's carry door (DGO_CARRY_PUBLISH_*), the link's WireGuard
#    (DGO_WG_PUBLISH_*, default 51839) and meet's bridge (MEET_JVB_*, default 10000) — plus HOST_DOORS_TCP_EXTRA /
#    HOST_DOORS_UDP_EXTRA. Those are the IPv4 doors; over IPv6 only sshd and a host tunnel answer, plus
#    HOST_DOORS_TCP6_EXTRA / HOST_DOORS_UDP6_EXTRA, or every IPv4 door with HOST_IPV6_WEB=1 (DGO-1633: docker-proxy
#    hands the edge an IPv6 visitor as the bridge's own address). A renamed or added interface is CLOSED, not open. It is a table of its own
#    (inet dgo_host), loaded by a unit ordered like Debian's own nftables.service (before the network comes up). It
#    never touches docker's tables or the security app's (inet dgo_security), and `nftables.service` stays OFF:
#    Debian's /etc/nftables.conf starts with `flush ruleset`, which would erase docker's NAT at the next boot.
# 4. Docker's published ports are fenced in DOCKER-USER by scripts/ops/docker-user-firewall.sh, as a unit, on the
#    public interface (DGO_PUBLIC_IFACE, else the default route's device).
# 5. Hosting agents that call out on their own are stopped, masked, and their re-install cron moved aside
#    (HOST_AGENTS_OFF, default Hostinger's `monarx-agent` with /etc/cron.d/monarx-update), and the package source
#    that the daily apt update would still fetch from its vendor (/etc/apt/sources.list.d/monarx.list).
#
# Lockout: `apply` refuses when no root key can open a shell, refuses while an earlier revert is still armed,
# validates sshd's config before reloading and asserts what a stranger and each declared address get (`sshd -T -C`),
# puts the previous sshd config back if any of that fails, and arms a transient timer that runs `revert` after
# HOST_BASELINE_REVERT_S seconds (default 600) unless `confirm` disarms it. A reload never drops an open session.
# The timer is transient: a reboot inside the window cancels it.
set -euo pipefail
set -f   # no pathname expansion: `br-*` is an interface pattern for nft, never a file in the working directory
export LC_ALL=C   # one sort order on every machine: a locale's order would read as drift

SELF="$(readlink -f "$0")"
INSTALLED=/usr/local/sbin/dgo-host-baseline
CONF_DIR=/etc/dgo
CONF_ENV="${CONF_DIR}/host-baseline.env"
SSHD_DROPIN=/etc/ssh/sshd_config.d/00-dgo-baseline.conf
RESOLVED_DROPIN=/etc/systemd/resolved.conf.d/00-dgo-baseline.conf
NFT_FILE="${CONF_DIR}/host-firewall.nft"
FW_UNIT=/etc/systemd/system/dgo-host-firewall.service
DU_SCRIPT=/usr/local/sbin/docker-user-firewall.sh
DU_UNIT=/etc/systemd/system/docker-user-firewall.service
REVERT_UNIT=dgo-host-baseline-revert
BACKUP_ROOT=/root/dgo-backup
KEPT_FILES=("${NFT_FILE}" "${FW_UNIT}" "${DU_SCRIPT}" "${DU_UNIT}" "${CONF_ENV}")

die() { echo "host-baseline: $*" >&2; exit 2; }
say() { echo "host-baseline: $*"; }
[ "$(id -u)" = 0 ] || die "run as root"
MODE="${1:-check}"

# The office's .env: OFFICE_ENV, else the checkout this script sits in, else what `apply` recorded.
office_env() {
  if [ -n "${OFFICE_ENV:-}" ]; then echo "${OFFICE_ENV}"; return; fi
  local here; here="$(cd "$(dirname "${SELF}")/../.." 2>/dev/null && pwd || true)"
  if [ -n "${here}" ] && [ -f "${here}/.env" ] && [ -f "${here}/platform.state.yaml" ]; then echo "${here}/.env"; return; fi
  if [ -f "${CONF_ENV}" ]; then sed -n 's/^OFFICE_ENV=//p' "${CONF_ENV}" | tail -1; return; fi
  echo ""
}
ENV_FILE="$(office_env)"
env_value() {
  [ -n "${ENV_FILE}" ] || return 0
  sed -n "s/^$1=//p" "${ENV_FILE}" 2>/dev/null | tail -1 | sed -E 's/[[:space:]]+#.*$//' | tr -d '"'"'"'\r' || true
}

# The public interface: DGO_PUBLIC_IFACE, else the token after `dev` on the default route (v4, then v6).
default_dev() { ip -o "$@" route show default 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit }}'; }
PUBLIC_IFACE="${DGO_PUBLIC_IFACE:-$(env_value DGO_PUBLIC_IFACE)}"
[ -n "${PUBLIC_IFACE}" ] || PUBLIC_IFACE="$(default_dev)"
[ -n "${PUBLIC_IFACE}" ] || PUBLIC_IFACE="$(default_dev -6)"
need_iface() {
  [ -n "${PUBLIC_IFACE}" ] && ip link show dev "${PUBLIC_IFACE}" >/dev/null 2>&1 \
    || die "no public interface ('${PUBLIC_IFACE:-none}' from the default route does not exist) — set DGO_PUBLIC_IFACE"
}

valid_port() { [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }
add_port() {   # add_port <var> <value> <why> — a bad value is said, never silently dropped
  local var="$1" v="$2"
  if valid_port "${v}"; then printf -v "${var}" '%s %s' "${!var}" "$((10#${v}))"; else say "ignored door '${v}' ($3): not a port"; fi
}
words() { tr ',' ' ' <<<"$1"; }

# ── the declaration ────────────────────────────────────────────────────────────────────────────────────────────
PW_FROM="$(words "$(env_value HOST_SSH_PASSWORD_FROM)")"
# Every port sshd answers on: its `port` lines, the port of each `listenaddress` (sshd -T prints `port 22` even
# when ListenAddress 0.0.0.0:2222 is what listens), what it really listens on now, and ssh.socket's when the
# socket starts it — a door missed here is a lockout (the second reader, pass 2).
ssh_ports() {
  {
    sshd -T 2>/dev/null | awk '$1 == "port" { print $2 } $1 == "listenaddress" { n = split($2, a, ":"); print a[n] }'
    ss -Hltnp 2>/dev/null | awk '/"sshd"/ { n = split($4, a, ":"); print a[n] }'
    systemctl show -p Listen --value ssh.socket 2>/dev/null | tr ' ' '\n' | awk -F: '/Stream/ || /^\[?[0-9a-f.:]*\]?:[0-9]+$/ { print $NF }'
  } | grep -oE '^[0-9]+' | sort -un | tr '\n' ' ' || true
}
SSH_PORTS="$(ssh_ports)"
SSH_PORTS="${SSH_PORTS:-22}"
DOORS_TCP=""; DOORS_UDP=""
for p in ${SSH_PORTS}; do add_port DOORS_TCP "${p}" "sshd"; done
add_port DOORS_TCP 80 "edge"; add_port DOORS_TCP 443 "edge"
[ "$(env_value MAIL_BIND)" = "0.0.0.0" ] && add_port DOORS_TCP 25 "MAIL_BIND"
if [ "$(env_value DGO_CARRY_PUBLISH_BIND)" = "0.0.0.0" ]; then add_port DOORS_TCP "$(env_value DGO_CARRY_PUBLISH_PORT)" "DGO_CARRY_PUBLISH_PORT"; fi
for p in $(words "$(env_value HOST_DOORS_TCP_EXTRA)"); do add_port DOORS_TCP "${p}" "HOST_DOORS_TCP_EXTRA"; done
if [ "$(env_value MEET_JVB_BIND)" = "0.0.0.0" ]; then v="$(env_value MEET_JVB_PORT)"; add_port DOORS_UDP "${v:-10000}" "MEET_JVB_PORT"; fi
if [ "$(env_value DGO_WG_PUBLISH_BIND)" = "0.0.0.0" ]; then v="$(env_value DGO_WG_PUBLISH_PORT)"; add_port DOORS_UDP "${v:-51839}" "DGO_WG_PUBLISH_PORT"; fi
for p in $(words "$(env_value HOST_DOORS_UDP_EXTRA)"); do add_port DOORS_UDP "${p}" "HOST_DOORS_UDP_EXTRA"; done
TRUSTED_IFACES="lo docker0 br-* $(words "$(env_value HOST_TRUSTED_IFACES)")"
# A tunnel that ends ON the host (dgo-extend's far-end mode runs wg-quick@wg0; tailscale) carries only peers that
# authenticated: trust its interface and keep its port open, or the baseline would cut the link it serves.
HOST_TUNNELS="$(ip -o link show type wireguard 2>/dev/null | awk -F': ' '{ split($2, a, "@"); print a[1] }' | tr '\n' ' ' || true)"
[ -d /sys/class/net/tailscale0 ] && HOST_TUNNELS="${HOST_TUNNELS} tailscale0"
TRUSTED_IFACES="${TRUSTED_IFACES} ${HOST_TUNNELS}"
TUNNEL_UDP=""
for p in $( { wg show all listen-port 2>/dev/null | awk '{ print $2 }'; ss -Hlunp 2>/dev/null | awk '/"tailscaled"/ { n = split($4, a, ":"); print a[n] }'; } || true); do
  add_port DOORS_UDP "${p}" "a tunnel that ends on this host"
  add_port TUNNEL_UDP "${p}" "a tunnel that ends on this host"
done
# IPv6 ADMITS ONLY WHAT THE HOST ITSELF SERVES (DGO-1633). Docker publishes a container's port on [::] through
# docker-proxy. For IPv4, docker's NAT keeps the visitor's address; for IPv6, docker-proxy opens its own
# connection from the bridge's gateway, so the edge sees every IPv6 visitor as 172.18.0.1 (measured on Exampleu
# and vps1, 2026-11-09: Host supabase.localhost /storage/v1/version over IPv6 answered 200, logged as
# 172.18.0.1). Every rule that trusts the office's own addresses then lets the whole IPv6 internet through: a
# `.localhost` guard, an n8n webhook's IP allow-list, the security app's «the office itself». No office name has
# an AAAA record (Exampleu: 58 names, vps1: 59, none), so no visitor needs IPv6. Over IPv6 the host admits sshd (it
# sees the true address), the tunnels that end on it, and what HOST_DOORS_TCP6_EXTRA / HOST_DOORS_UDP6_EXTRA
# declare; an IPv4-only TCP door answers IPv6 with a reset, never a silent drop, so a client that finds an AAAA
# name some day falls back to IPv4 at once. HOST_IPV6_WEB=1 gives IPv6 every IPv4 door, for an office that
# serves IPv6 through docker-proxy knowing the edge then sees the bridge. Docker keeping the IPv6 source
# (ip6tables NAT on an IPv6 bridge) is a different road: that traffic is forwarded and never reaches this chain,
# and docker-user-firewall.sh fences IPv4 only — an ip6tables DOCKER-USER fence must come first.
DOORS_TCP6=""; DOORS_UDP6=""
IPV6_WEB="$(env_value HOST_IPV6_WEB)"
if [ "${IPV6_WEB}" = 1 ]; then
  DOORS_TCP6="${DOORS_TCP}"; DOORS_UDP6="${DOORS_UDP}"
else
  for p in ${SSH_PORTS}; do add_port DOORS_TCP6 "${p}" "sshd"; done
  for p in ${TUNNEL_UDP}; do add_port DOORS_UDP6 "${p}" "a tunnel that ends on this host"; done
fi
for p in $(words "$(env_value HOST_DOORS_TCP6_EXTRA)"); do add_port DOORS_TCP6 "${p}" "HOST_DOORS_TCP6_EXTRA"; done
for p in $(words "$(env_value HOST_DOORS_UDP6_EXTRA)"); do add_port DOORS_UDP6 "${p}" "HOST_DOORS_UDP6_EXTRA"; done
AGENTS_OFF="$(words "$(env_value HOST_AGENTS_OFF)")"; AGENTS_OFF="${AGENTS_OFF:-monarx-agent}"
AGENTS_OFF="$(for a in ${AGENTS_OFF}; do echo "${a%.service}"; done | tr '\n' ' ')"   # `monarx-agent.service` is monarx-agent
# What brings an agent back besides its unit: Monarx's weekly re-install cron, and its apt source — with the agent
# masked, apt's daily update still reached repository.monarx.com (the security app's egress view, 2026-11-09).
agent_files() {   # both apt formats: a one-line .list and a deb822 .sources (set -f: named, never globbed)
  case "$1" in
    monarx-agent) echo /etc/cron.d/monarx-update /etc/apt/sources.list.d/monarx.list /etc/apt/sources.list.d/monarx.sources ;;
    *) echo "" ;;
  esac
}
sorted() { tr ' ' '\n' <<<"$1" | sed '/^$/d' | sort -un | paste -sd' ' -; }       # ports, numerically
sorted_words() { tr ' ' '\n' <<<"$1" | sed '/^$/d' | sort -u | paste -sd' ' -; }  # addresses: never -n (10.0.0.1 = 10.0.0.2)
DOORS_TCP="$(sorted "${DOORS_TCP}")"; DOORS_UDP="$(sorted "${DOORS_UDP}")"
DOORS_TCP6="$(sorted "${DOORS_TCP6}")"; DOORS_UDP6="$(sorted "${DOORS_UDP6}")"
TCP6_RESET=""   # the IPv4 TCP doors IPv6 does not get: a reset, so a client tries IPv4 at once (see DOORS_TCP6)
for p in ${DOORS_TCP}; do [[ " ${DOORS_TCP6} " == *" ${p} "* ]] || TCP6_RESET="${TCP6_RESET:+${TCP6_RESET} }${p}"; done

# An address sshd will be asked about for each HOST_SSH_PASSWORD_FROM entry (a CIDR's first host, a pattern's
# wildcards as 1) — and the entry refused when it is neither an address, a network nor an sshd pattern.
probe_addr() {
  python3 - "$1" <<'PY'
import ipaddress, re, sys
e = sys.argv[1]
if "%" in e:                   # a scope id (fe80::1%eth0): sshd refuses it
    sys.exit(1)
try:
    n = ipaddress.ip_network(e, strict=True)   # 10.0.0.1/8 has host bits set: sshd refuses it, so do we
    print(n.network_address if n.num_addresses == 1 else next(n.hosts()))
except ValueError:
    if re.fullmatch(r"[0-9a-fA-F.:*?]+", e) and ("*" in e or "?" in e):
        print(re.sub(r"[*?]", "1", e))
    else:
        sys.exit(1)
PY
}

render_sshd() {
  echo "# Written by scripts/ops/host-baseline.sh (DGO host baseline, DGO-1495). The FIRST file sshd reads: its"
  echo "# values win. Change the office's .env (HOST_SSH_PASSWORD_FROM) and re-apply; never edit this by hand."
  echo "PasswordAuthentication no"
  echo "KbdInteractiveAuthentication no"
  echo "PubkeyAuthentication yes"
  echo "AuthenticationMethods any"
  echo "PermitRootLogin prohibit-password"
  echo "PermitEmptyPasswords no"
  echo "X11Forwarding no"
  echo "LoginGraceTime 30"
  if [ -n "${PW_FROM// /}" ]; then
    echo "Match Address $(sorted_words "${PW_FROM}" | tr ' ' ',')"
    echo "    PasswordAuthentication yes"
    echo "    PermitRootLogin yes"
    echo "Match all"
  fi
}

render_nft() {
  local i
  echo "# Written by scripts/ops/host-baseline.sh (DGO-1495). Loaded before the network by dgo-host-firewall.service."
  echo "# lo, docker0 and docker's bridges pass as before; every other interface admits only the office's doors."
  echo "add table inet dgo_host"
  echo "delete table inet dgo_host"
  echo "table inet dgo_host {"
  echo "  chain input {"
  echo "    type filter hook input priority filter; policy accept;"
  for i in ${TRUSTED_IFACES}; do echo "    iifname \"${i}\" accept"; done
  echo "    ct state established,related accept"
  echo "    ct state invalid drop"
  echo "    meta l4proto { icmp, ipv6-icmp } accept"
  echo "    udp sport 67 udp dport 68 accept"
  echo "    ip6 saddr fe80::/10 udp dport 546 accept"
  echo "    meta nfproto ipv4 tcp dport { $(sed 's/ /, /g' <<<"${DOORS_TCP}") } accept"
  [ -n "${DOORS_UDP}" ] && echo "    meta nfproto ipv4 udp dport { $(sed 's/ /, /g' <<<"${DOORS_UDP}") } accept"
  # IPv6: only what the host itself serves, unless HOST_IPV6_WEB=1 (DGO-1633, see DOORS_TCP6 above)
  [ -n "${DOORS_TCP6}" ] && echo "    meta nfproto ipv6 tcp dport { $(sed 's/ /, /g' <<<"${DOORS_TCP6}") } accept"
  [ -n "${DOORS_UDP6}" ] && echo "    meta nfproto ipv6 udp dport { $(sed 's/ /, /g' <<<"${DOORS_UDP6}") } accept"
  # nft LISTS this rule without its `meta nfproto ipv6` (it reads as the reset's own dependency; the kernel still
  # matches IPv6 only), so the rule names its family itself — a reader of `nft list` must not see IPv4 80/443 reset
  [ -n "${TCP6_RESET}" ] && echo "    meta nfproto ipv6 tcp dport { $(sed 's/ /, /g' <<<"${TCP6_RESET}") } reject with tcp reset comment \"IPv6 only: these doors are IPv4 (DGO-1633)\""
  echo "    counter drop"
  echo "  }"
  echo "}"
}

render_fw_unit() {
  cat <<UNIT
[Unit]
Description=DGO host baseline: only the office's doors answer (scripts/ops/host-baseline.sh)
DefaultDependencies=no
Wants=network-pre.target
Before=network-pre.target shutdown.target
Conflicts=shutdown.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f ${NFT_FILE}
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
UNIT
}

unit_quote() { local v="${1//%/%%}"; echo "\"${v//\"/\\\"}\""; }
render_du_unit() {
  # computed BEFORE the here-document: a here-document runs no command (gate heredoc-substitution-lint)
  local env_office env_iface
  env_office="$(unit_quote "OFFICE_ENV=${ENV_FILE}")"
  env_iface="$(unit_quote "DGO_PUBLIC_IFACE=${PUBLIC_IFACE}")"
  cat <<UNIT
[Unit]
Description=DGO: docker's published ports admit only the office's doors (scripts/ops/docker-user-firewall.sh)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
Environment=${env_office}
Environment=${env_iface}
ExecStart=${DU_SCRIPT}
RemainAfterExit=yes

[Install]
WantedBy=docker.service multi-user.target
UNIT
}

# ── facts ──────────────────────────────────────────────────────────────────────────────────────────────────────
LADDR="$(ip -o -4 addr show dev "${PUBLIC_IFACE}" 2>/dev/null | awk '{ split($4, a, "/"); print a[1]; exit }' || true)"
LPORT="${SSH_PORTS%% *}"
eff() {   # eff <address> <keyword> [user] — what sshd gives <user> (root) connecting from <address>
  local spec="user=${3:-root},host=probe.invalid,addr=$1,lport=${LPORT}"
  [ -n "${LADDR}" ] && spec="${spec},laddr=${LADDR}"
  { sshd -T -C "${spec}" 2>/dev/null || true; } | awk -v k="$2" '$1 == k { print $2; exit }'
}
# Every account that can log in, not root alone: a provider's `Match User deploy` with passwords would make
# «keys only» false for that user while root's answer stayed right (the second reader, pass 2).
login_users() { getent passwd 2>/dev/null | awk -F: '$7 !~ /(nologin|false|sync|halt|shutdown)$/ { print $1 }' | sort -u | tr '\n' ' ' || true; }
# What a stranger must get: the keyword and the values that are acceptable.
STRANGER_RULES=(
  "passwordauthentication:no"
  "kbdinteractiveauthentication:no"
  "pubkeyauthentication:yes"
  "authenticationmethods:any"
  "permitrootlogin:without-password prohibit-password"
  "x11forwarding:no"
)
sshd_problems() {   # prints one line per way a stranger or a declared address is not what is declared
  local rule k ok a e u
  for rule in "${STRANGER_RULES[@]}"; do
    k="${rule%%:*}"; ok="${rule#*:}"; a="$(eff 203.0.113.9 "${k}")"
    [[ " ${ok} " == *" ${a:-?} "* ]] || echo "a stranger gets ${k}=${a:-?} (want ${ok})"
  done
  for u in $(login_users); do
    [ "${u}" = root ] && continue
    for k in passwordauthentication kbdinteractiveauthentication; do
      a="$(eff 203.0.113.9 "${k}" "${u}")"; [ "${a}" = no ] || echo "a stranger logging in as ${u} gets ${k}=${a:-?} (want no)"
    done
  done
  for e in ${PW_FROM}; do
    a="$(probe_addr "${e}")" || { echo "HOST_SSH_PASSWORD_FROM entry '${e}' is not an address, a network or an sshd pattern"; continue; }
    [ "$(eff "${a}" passwordauthentication)" = yes ] || echo "the declared ${e} gets no password"
  done
}
shell_keys() {   # authorized keys of root that can open a shell (a forced command cannot)
  [ -f /root/.ssh/authorized_keys ] || { echo 0; return; }
  awk '!/^[[:space:]]*(#|$)/ { if ($1 ~ /^(ssh-|ecdsa-|sk-)/) n++; else if ($1 !~ /command=/) n++ } END { print n + 0 }' /root/.ssh/authorized_keys
}
loaded_ports() {   # loaded_ports tcp|udp [ipv4|ipv6] — the doors the LOADED host table admits for that family
  # A rule names its family (`meta nfproto ipv4 tcp dport {…}`); a table loaded before DGO-1633 has rules that
  # name none, and those admit both families — so the old table reads as drift until it is re-applied.
  nft list table inet dgo_host 2>/dev/null | awk -v p="$1" -v f="${2:-ipv4}" '
      $1 == "meta" && $2 == "nfproto" && $3 == f && $4 == p && $5 == "dport" && /accept$/ { print; next }
      $1 == p && $2 == "dport" && /accept$/ { print }' \
    | sed 's/.*dport//' | grep -oE '[0-9]+' | sort -un | paste -sd' ' - || true
}
# ARMED = the timer still WAITS. A transient timer reads «active (running)» while its revert executes, so
# `is-active` alone let `confirm` say «the baseline stays» during a revert that then finished (pass 2).
armed() { [ "$(systemctl show -p SubState --value "${REVERT_UNIT}.timer" 2>/dev/null)" = waiting ]; }
reverting() { systemctl is-active --quiet "${REVERT_UNIT}.service" 2>/dev/null; }
# The public interface must never be one the table trusts (a bridge named br-…, HOST_TRUSTED_IFACES=*): that
# would open the whole host while every check agreed with itself.
iface_trusted() { local t; for t in ${TRUSTED_IFACES}; do [[ "${PUBLIC_IFACE}" == ${t} ]] && return 0; done; return 1; }
recorded_iface() { [ -f "${CONF_ENV}" ] && sed -n 's/^DGO_PUBLIC_IFACE=//p' "${CONF_ENV}" | tail -1 || true; }

DRIFT=0
fact() { if [ "$1" = ok ]; then echo "ok     $2"; else echo "DRIFT  $2"; DRIFT=1; fi; }

check() {
  local p c n r
  need_iface
  [ -n "${ENV_FILE}" ] && [ -f "${ENV_FILE}" ] && fact ok "office .env: ${ENV_FILE}" || fact drift "office .env not found (OFFICE_ENV)"
  if iface_trusted; then fact drift "the public interface ${PUBLIC_IFACE} matches a trusted pattern (${TRUSTED_IFACES}): the host would be open"
  else fact ok "public interface: ${PUBLIC_IFACE}; trusted: ${TRUSTED_IFACES}"; fi
  r="$(recorded_iface)"
  [ -z "${r}" ] || [ "${r}" = "${PUBLIC_IFACE}" ] || fact drift "the public interface was ${r} at apply and is ${PUBLIC_IFACE} now — re-apply (docker's fence still names ${r})"
  cmp -s <(render_sshd) "${SSHD_DROPIN}" 2>/dev/null && fact ok "sshd drop-in matches the declaration" || fact drift "sshd drop-in differs from the declaration (${SSHD_DROPIN})"
  p="$(sshd_problems)"
  if [ -z "${p}" ]; then fact ok "sshd: a stranger gets keys only (every login user: $(login_users)), root by key, no X11$( [ -n "${PW_FROM// /}" ] && echo "; a password from ${PW_FROM}")"
  else while read -r line; do fact drift "sshd: ${line}"; done <<<"${p}"; fi
  if ss -Hlnu 'sport = :5355' 2>/dev/null | grep -q . || ss -Hlnt 'sport = :5355' 2>/dev/null | grep -q .; then fact drift "LLMNR listens on 5355"; else fact ok "nothing listens on 5355 (LLMNR off)"; fi
  if nft list table inet dgo_host >/dev/null 2>&1; then
    [ "$(loaded_ports tcp ipv4)" = "${DOORS_TCP}" ] && [ "$(loaded_ports udp ipv4)" = "${DOORS_UDP}" ] \
      && fact ok "the loaded host table admits tcp ${DOORS_TCP}; udp ${DOORS_UDP:-none}" \
      || fact drift "the loaded host table admits tcp $(loaded_ports tcp ipv4); udp $(loaded_ports udp ipv4) — declared tcp ${DOORS_TCP}; udp ${DOORS_UDP:-none}"
    local why6="the edge's doors are IPv4 only: an IPv6 visitor would reach the edge as the docker bridge (DGO-1633)"
    [ "${IPV6_WEB}" = 1 ] && why6="HOST_IPV6_WEB=1: every IPv4 door, and the edge sees IPv6 visitors as the docker bridge"
    [ "$(loaded_ports tcp ipv6)" = "${DOORS_TCP6}" ] && [ "$(loaded_ports udp ipv6)" = "${DOORS_UDP6}" ] \
      && fact ok "over IPv6 it admits tcp ${DOORS_TCP6:-none}; udp ${DOORS_UDP6:-none} — ${why6}" \
      || fact drift "over IPv6 the loaded host table admits tcp $(loaded_ports tcp ipv6); udp $(loaded_ports udp ipv6) — declared tcp ${DOORS_TCP6:-none}; udp ${DOORS_UDP6:-none} (${why6})"
    cmp -s <(render_nft) "${NFT_FILE}" 2>/dev/null && fact ok "its boot file matches the declaration" || fact drift "${NFT_FILE} differs from the declaration — re-apply"
  else fact drift "host table inet dgo_host not loaded"; fi
  [ "$(systemctl is-enabled dgo-host-firewall.service 2>/dev/null || true)" = enabled ] && cmp -s <(render_fw_unit) "${FW_UNIT}" 2>/dev/null \
    && fact ok "dgo-host-firewall.service enabled, ordered before the network" || fact drift "dgo-host-firewall.service missing, old or not enabled"
  [ "$(systemctl is-enabled nftables.service 2>/dev/null || true)" = enabled ] && fact drift "nftables.service is ENABLED: its flush ruleset erases docker's NAT at boot" || fact ok "nftables.service off"
  if has_docker; then
    iptables -S DOCKER-USER 2>/dev/null | grep -q -- "-i ${PUBLIC_IFACE} -j DROP" && fact ok "DOCKER-USER fences ${PUBLIC_IFACE}" || fact drift "DOCKER-USER has no fence on ${PUBLIC_IFACE}"
    [ "$(systemctl is-enabled docker-user-firewall.service 2>/dev/null || true)" = enabled ] && cmp -s <(render_du_unit) "${DU_UNIT}" 2>/dev/null \
      && fact ok "docker-user-firewall.service enabled" || fact drift "docker-user-firewall.service missing, old or not enabled"
  else fact ok "no docker on this host: no DOCKER-USER fence to hold"; fi
  for svc in ${AGENTS_OFF}; do
    if systemctl list-unit-files "${svc}.service" --no-legend 2>/dev/null | grep -q .; then
      [ "$(systemctl is-active "${svc}" 2>/dev/null || true)" != active ] && [ "$(systemctl is-enabled "${svc}" 2>/dev/null || true)" = masked ] \
        && fact ok "${svc} stopped and masked" || fact drift "${svc} runs or can start"
    else fact ok "${svc} not installed"; fi
    # checked whether or not the unit is still there: an apt source outlives the package it came with
    for c in $(agent_files "${svc}"); do
      [ -e "${c}" ] && fact drift "${c} would bring ${svc} back" || fact ok "${svc}: ${c} is not there"
    done
  done
  n="$(shell_keys)"; [ "${n}" -gt 0 ] && fact ok "root has ${n} authorized key(s) that open a shell" || fact drift "no root key opens a shell"
  if reverting; then echo "REVERT a revert is running right now — check again when it has finished"
  elif armed; then echo "ARMED  a revert is armed — run: ${INSTALLED} confirm (after a NEW ssh login worked)"; fi
}
has_docker() { command -v docker >/dev/null 2>&1 && systemctl list-unit-files docker.service --no-legend 2>/dev/null | grep -q .; }

# ── apply / revert / confirm ───────────────────────────────────────────────────────────────────────────────────
agent_state() { local e a; e="$(systemctl is-enabled "$1" 2>/dev/null || true)"; a="$(systemctl is-active "$1" 2>/dev/null || true)"; echo "$1 ${e:-none} ${a:-none}"; }

backup() {
  local bk="$1" f
  mkdir -p "${bk}/sshd_config.d" "${bk}/resolved.conf.d" "${bk}/files" && chmod 700 "${bk}"
  : > "${bk}/moved.list"
  cp -a /etc/ssh/sshd_config.d/. "${bk}/sshd_config.d/" 2>/dev/null || true
  cp -a /etc/systemd/resolved.conf.d/. "${bk}/resolved.conf.d/" 2>/dev/null || true
  : > "${bk}/existed.before"
  for f in "${KEPT_FILES[@]}"; do
    if [ -e "${f}" ]; then echo "${f}" >> "${bk}/existed.before"; mkdir -p "${bk}/files$(dirname "${f}")"; cp -a "${f}" "${bk}/files${f}"; fi
  done
  nft list ruleset > "${bk}/nft-ruleset.before" 2>/dev/null || true
  iptables -S DOCKER-USER > "${bk}/docker-user.before" 2>/dev/null || rm -f "${bk}/docker-user.before"
  : > "${bk}/agents.before"
  for f in ${AGENTS_OFF}; do agent_state "${f}" >> "${bk}/agents.before"; done
}

restore_files() {   # restore_files <backup dir> <live dir> — each backed-up file back, never the directory's own mode
  local f
  for f in $(ls -A "$1" 2>/dev/null); do cp -p "$1/${f}" "$2/${f}"; done
}
restore_sshd() {   # put the backed-up sshd_config.d back, exactly
  local bk="$1"
  rm -f "${SSHD_DROPIN}"
  restore_files "${bk}/sshd_config.d" /etc/ssh/sshd_config.d
}

apply() {
  local ts bk p
  need_iface
  [ -n "${ENV_FILE}" ] && [ -f "${ENV_FILE}" ] || die "the office's .env was not found — set OFFICE_ENV"
  [ "$(shell_keys)" -gt 0 ] || die "no root key can open a shell: keys-only SSH would lock everyone out"
  command -v nft >/dev/null && command -v systemd-run >/dev/null && command -v python3 >/dev/null || die "needs nft, systemd-run and python3"
  iface_trusted && die "the public interface ${PUBLIC_IFACE} matches a trusted pattern (${TRUSTED_IFACES}): nothing written"
  reverting && die "a revert is running right now: let it finish, then check, then apply"
  armed && die "a revert from an earlier apply is still armed: confirm it (after a new login worked) or let it run, then apply"
  for p in ${PW_FROM}; do probe_addr "${p}" >/dev/null || die "HOST_SSH_PASSWORD_FROM: '${p}' is not an address, a network or an sshd pattern — nothing written"; done
  ts="$(date -u +%Y%m%dT%H%M%SZ)"; bk="${BACKUP_ROOT}/host-baseline-${ts}"
  backup "${bk}"; say "backup: ${bk}"

  [ "${SELF}" = "${INSTALLED}" ] || install -m 0755 "${SELF}" "${INSTALLED}"
  mkdir -p "${CONF_DIR}"; printf 'OFFICE_ENV=%s\nDGO_PUBLIC_IFACE=%s\n' "${ENV_FILE}" "${PUBLIC_IFACE}" > "${CONF_ENV}"

  systemctl reset-failed "${REVERT_UNIT}.service" "${REVERT_UNIT}.timer" >/dev/null 2>&1 || true
  systemd-run --quiet --unit "${REVERT_UNIT}" --on-active="${HOST_BASELINE_REVERT_S:-600}" "${INSTALLED}" revert "${bk}"
  say "revert ARMED: in ${HOST_BASELINE_REVERT_S:-600}s unless '${INSTALLED} confirm' runs"

  # 1. SSH — anything wrong puts the previous config back before sshd is ever reloaded
  render_sshd > "${SSHD_DROPIN}.new"; chmod 0644 "${SSHD_DROPIN}.new"; mv -f "${SSHD_DROPIN}.new" "${SSHD_DROPIN}"
  if ! sshd -t; then restore_sshd "${bk}"; die "sshd -t refused the drop-in: the previous config is back, nothing reloaded (the revert is still armed)"; fi
  p="$(sshd_problems)"
  if [ -n "${p}" ]; then restore_sshd "${bk}"; die "sshd would not be what is declared — ${p//$'\n'/; } — the previous config is back, nothing reloaded (the revert is still armed)"; fi
  systemctl reload ssh 2>/dev/null || systemctl reload sshd
  say "sshd reloaded (keys only$( [ -n "${PW_FROM// /}" ] && echo "; a password only from ${PW_FROM}"))"

  # 2. LLMNR / mDNS
  mkdir -p "$(dirname "${RESOLVED_DROPIN}")"
  printf '# Written by scripts/ops/host-baseline.sh (DGO-1495): a server answers nobody'"'"'s local name lookups.\n[Resolve]\nLLMNR=no\nMulticastDNS=no\n' > "${RESOLVED_DROPIN}"
  systemctl restart systemd-resolved 2>/dev/null || true
  say "LLMNR and mDNS off"

  # 3. the doors
  render_nft > "${NFT_FILE}.new"
  nft -c -f "${NFT_FILE}.new" || { rm -f "${NFT_FILE}.new"; die "nft refused the host table: nothing loaded (the revert is still armed)"; }
  mv -f "${NFT_FILE}.new" "${NFT_FILE}"
  render_fw_unit > "${FW_UNIT}"
  systemctl daemon-reload
  systemctl reenable dgo-host-firewall.service >/dev/null 2>&1
  systemctl restart dgo-host-firewall.service
  say "every interface but ${TRUSTED_IFACES} admits tcp ${DOORS_TCP}; udp ${DOORS_UDP:-none} — over IPv6 tcp ${DOORS_TCP6:-none}; udp ${DOORS_UDP6:-none}"

  # 4. docker's published ports
  local du_src; du_src="$(dirname "${SELF}")/docker-user-firewall.sh"
  [ "${SELF}" = "${INSTALLED}" ] && du_src="${DU_SCRIPT}"
  if ! has_docker; then
    say "no docker on this host: no DOCKER-USER fence to install"
  elif [ -f "${du_src}" ]; then
    [ "${du_src}" = "${DU_SCRIPT}" ] || install -m 0755 "${du_src}" "${DU_SCRIPT}"
    render_du_unit > "${DU_UNIT}"; systemctl daemon-reload
    systemctl reenable docker-user-firewall.service >/dev/null 2>&1
    systemctl restart docker-user-firewall.service
    say "DOCKER-USER fence on ${PUBLIC_IFACE}"
  else
    say "docker-user-firewall.sh not beside this script — the DOCKER-USER fence was left as it was"
  fi

  # 5. hosting agents
  for p in ${AGENTS_OFF}; do
    if systemctl list-unit-files "${p}.service" --no-legend 2>/dev/null | grep -q .; then
      systemctl disable --now "${p}" >/dev/null 2>&1 || true
      systemctl mask "${p}" >/dev/null 2>&1 || true
      say "${p} stopped and masked"
    fi
    for c in $(agent_files "${p}"); do   # kept under its full path, so revert puts each back where it was
      if [ -e "${c}" ]; then
        mkdir -p "${bk}/moved$(dirname "${c}")"; mv -f "${c}" "${bk}/moved${c}"; echo "${c}" >> "${bk}/moved.list"
        say "${c} moved aside"
      fi
    done
  done

  echo; check
  echo; say "now open a NEW ssh session to this server; when it works, run: ${INSTALLED} confirm"
  [ "${DRIFT}" = 0 ] || { say "DRIFT after apply — the revert stays armed"; exit 1; }
}

confirm() {
  if reverting; then
    die "the revert is RUNNING right now: it cannot be stopped half way — let it finish, then '$0 check', then apply again"
  elif armed; then
    systemctl stop "${REVERT_UNIT}.timer"
    say "revert disarmed — the baseline stays"
  elif systemctl is-failed --quiet "${REVERT_UNIT}.service" 2>/dev/null; then
    die "the revert already RAN and FAILED: see 'journalctl -u ${REVERT_UNIT}', then '$0 check'"
  else
    die "no revert is armed — it already ran (the host is back to the backup) or was never armed: run '$0 check'"
  fi
}

revert() {
  local bk="${1:-}" f svc enabled active line
  [ -n "${bk}" ] && [ -d "${bk}" ] || die "revert <backup-dir>"
  existed() { grep -qxF "$1" "${bk}/existed.before"; }
  put_back() { mkdir -p "$(dirname "$1")"; cp -a "${bk}/files$1" "$1"; }
  # 1. sshd and resolved, exactly as they were (a reload that fails must not stop the rest of the revert)
  restore_sshd "${bk}"
  if sshd -t; then systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || say "sshd did not reload: the files are back, a restart picks them up"; fi
  rm -f "${RESOLVED_DROPIN}"; restore_files "${bk}/resolved.conf.d" /etc/systemd/resolved.conf.d
  systemctl restart systemd-resolved 2>/dev/null || true
  # 2. the host table: the old file loaded again (atomic swap), or no table when there was none
  if existed "${NFT_FILE}"; then put_back "${NFT_FILE}"; nft -f "${NFT_FILE}" || true
  else nft delete table inet dgo_host 2>/dev/null || true; rm -f "${NFT_FILE}"; fi
  if existed "${FW_UNIT}"; then put_back "${FW_UNIT}"; systemctl daemon-reload; systemctl reenable dgo-host-firewall.service >/dev/null 2>&1 || true
  else systemctl disable dgo-host-firewall.service >/dev/null 2>&1 || true; rm -f "${FW_UNIT}"; fi
  # 3. the DOCKER-USER fence: its script and unit as they were, and the chain's own rules replayed
  if existed "${DU_SCRIPT}"; then put_back "${DU_SCRIPT}"; else rm -f "${DU_SCRIPT}"; fi
  if existed "${DU_UNIT}"; then put_back "${DU_UNIT}"; systemctl daemon-reload; systemctl reenable docker-user-firewall.service >/dev/null 2>&1 || true
  else systemctl disable docker-user-firewall.service >/dev/null 2>&1 || true; rm -f "${DU_UNIT}"; fi
  # One transaction that also parses quoted arguments (--comment "…"): declaring the chain in the input replaces
  # its rules atomically even under --noflush (measured on Exampleu). Replayed rule by rule, a quoted argument failed
  # right after the flush and left published ports open (pass 2) — so a failed restore fails CLOSED.
  if iptables -S DOCKER-USER >/dev/null 2>&1; then
    if ! { echo '*filter'; echo ':DOCKER-USER - [0:0]'; grep '^-A DOCKER-USER ' "${bk}/docker-user.before" 2>/dev/null || true; echo 'COMMIT'; } \
         | iptables-restore --noflush; then
      iptables -A DOCKER-USER -i "${PUBLIC_IFACE:-eth0}" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN 2>/dev/null || true
      iptables -A DOCKER-USER -i "${PUBLIC_IFACE:-eth0}" -j DROP 2>/dev/null || true
      say "DOCKER-USER could not be restored: it now DROPS new connections on ${PUBLIC_IFACE:-eth0} (fail closed) — re-apply"
    fi
  fi
  if existed "${CONF_ENV}"; then put_back "${CONF_ENV}"; else rm -f "${CONF_ENV}"; fi
  systemctl daemon-reload
  # 4. hosting agents, to the exact state recorded
  while read -r svc enabled active; do
    [ -n "${svc}" ] || continue
    case "${enabled}" in
      masked)   systemctl mask "${svc}" >/dev/null 2>&1 || true ;;
      enabled)  systemctl unmask "${svc}" >/dev/null 2>&1 || true; systemctl enable "${svc}" >/dev/null 2>&1 || true ;;
      disabled) systemctl unmask "${svc}" >/dev/null 2>&1 || true; systemctl disable "${svc}" >/dev/null 2>&1 || true ;;
      none)     ;;
      *)        systemctl unmask "${svc}" >/dev/null 2>&1 || true ;;   # static, indirect, alias…: apply masked it
    esac
    if [ "${active}" = active ]; then systemctl start "${svc}" >/dev/null 2>&1 || true; fi
  done < "${bk}/agents.before"
  # Each moved file back to its own path, FILE BY FILE: copying a backup directory over / or /etc/cron.d with
  # `cp -a dir/.` also wrote that directory's mode onto them (0700 under a strict umask — the second reader).
  while read -r f; do
    [ -n "${f}" ] && [ -e "${bk}/moved${f}" ] && { mkdir -p "$(dirname "${f}")"; cp -p "${bk}/moved${f}" "${f}"; }
  done < "${bk}/moved.list" 2>/dev/null || true
  restore_files "${bk}/cron.d" /etc/cron.d   # a backup made before moved.list (2026-11-09 00:30 UTC) kept its cron here
  say "reverted to ${bk}"
}

case "${MODE}" in
  check)   check; if [ "${DRIFT}" != 0 ]; then exit 1; elif armed || reverting; then exit 3; else exit 0; fi ;;
  apply)   apply ;;
  confirm) confirm ;;
  revert)  shift; revert "${1:-}" ;;
  render)  need_iface; echo "--- ${SSHD_DROPIN}"; render_sshd; echo "--- ${NFT_FILE}"; render_nft; echo "--- ${FW_UNIT}"; render_fw_unit; echo "--- ${DU_UNIT}"; render_du_unit ;;
  *) die "usage: $0 check|apply|confirm|revert <backup>|render" ;;
esac
