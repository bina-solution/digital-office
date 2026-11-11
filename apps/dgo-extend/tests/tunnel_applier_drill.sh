#!/bin/sh
# tunnel_applier_drill.sh — the tunnel applier (tunnel-entrypoint.sh) brings a real pair up on THIS docker host.
#
# Two throwaway containers from the office's own dgo-extend image, each running the entrypoint under test
# as dgo-net runs it (NET_ADMIN, NET_RAW, /dev/net/tun, ip_forward, no init — the script is PID 1 — and
# its 0.2 CPU / 96 MB), on an internal network of
# their own. Each holds one pair file shaped like net.py's render, naming the other. The drill passes when:
#   1. both interfaces come up and complete a WireGuard handshake;
#   2. an HTTP request crosses the tunnel (10.79.9.1 → 10.79.9.2);
#   3. the MTU is wg-quick's: the endpoint's device MTU less 80 (the drill's network is 1380, so 1300 —
#      a default-route or 1500 guess would give 1420);
#   4. measure() writes wg-state.json with the handshake (`wg show … dump` through a pipe);
#   5. a re-rendered pair is re-applied by the loop and handshakes again;
#   6. a pair removed from the plan loses its interface;
#   7. with the kernel's WireGuard refused (a shim `ip`), the userspace one carries the pair (wireguard-go).
# Why on the host itself: a host's AppArmor may attach profiles of its own to the image's binaries
# (Ubuntu 26.04: /usr/bin/wg, /usr/bin/wg-quick) — measured on the Dell, 2026-11-10. Run it where the
# office runs: `sh tunnel_applier_drill.sh <image> <path of tunnel-entrypoint.sh>`. Nothing outside the
# probe-wgdrill-* containers, its network and its folder is touched, and all three are removed at the end.
set -u
IMG="${1:?usage: tunnel_applier_drill.sh <dgo-extend image> <tunnel-entrypoint.sh>}"
ENTRY="${2:?the entrypoint under test}"
P=probe-wgdrill
DIR="${WGDRILL_DIR:-/tmp/$P}"
case "$DIR" in */"$P"|*/"$P"-*) ;; *) echo "[drill] WGDRILL_DIR must end in /$P or /$P-<name>: it is removed whole" >&2; exit 2 ;; esac
NET_MTU=1380
NET="$P-net"
SUB=10.252.77
fails=0
say() { echo "[drill] $*"; }
ok() { say "PASS $*"; }
bad() { say "FAIL $*"; fails=$((fails + 1)); }

cleanup() {
  docker rm -f "$P-a" "$P-b" "$P-c" "$P-d" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  rm -rf "$DIR"
}
cleanup
# a drill stopped from outside (its `timeout`, ^C) still leaves nothing behind — measured on a loaded vps1, where
# the bound killed the drill mid-run and its last two containers stayed up
trap 'cleanup; say "stopped"; exit 3' INT TERM HUP
trap cleanup EXIT
mkdir -p "$DIR" && cp "$ENTRY" "$DIR/entry.sh" && chmod 755 "$DIR/entry.sh" || { say "cannot prepare $DIR"; exit 2; }
docker network create --internal --subnet "$SUB.0/24" -o com.docker.network.driver.mtu="$NET_MTU" "$NET" >/dev/null || { say "cannot create $NET"; exit 2; }

# keys, made the way an office makes them: by `wg`, in /etc/wireguard (the one place a host profile allows)
keypair() {
  docker run --rm --network none --entrypoint sh "$IMG" -c \
    'umask 077; wg genkey > /etc/wireguard/k && wg pubkey < /etc/wireguard/k > /etc/wireguard/p && cat /etc/wireguard/k /etc/wireguard/p'
}

# one side: its key, and its pair file naming the other (the shape net.py renders)
side() {  # name mine other peer_pub peer_ip
  mkdir -p "$DIR/$1/pairs"
  printf '%s\n' "$2" > "$DIR/$1/wg-private.key"
  chmod 600 "$DIR/$1/wg-private.key"
  cat > "$DIR/$1/pairs/wg9.conf" <<EOF
# GENERATED for the drill — the shape of net.py's render.
[Interface]
Address = 10.79.9.$3/24
ListenPort = 51820
PrivateKey = @PRIVATE@

[Peer]
# drill
PublicKey = $4
AllowedIPs = 10.79.9.$5/32
Endpoint = $6:51820
PersistentKeepalive = 5
EOF
}

start() {  # name ip [extra docker args…]
  n="$1"; ip="$2"; shift 2
  docker run -d --name "$P-$n" --network "$NET" --ip "$ip" --hostname "$P-$n" \
    --cap-add NET_ADMIN --cap-add NET_RAW --device /dev/net/tun --sysctl net.ipv4.ip_forward=1 \
    --cpus 0.2 --memory 96m -v "$DIR/$n:/tunnel" -v "$DIR/entry.sh:/tunnel-entrypoint.sh:ro" \
    "$@" --entrypoint /tunnel-entrypoint.sh "$IMG" >/dev/null
}

handshake() {  # container → seconds since epoch of the pair's last handshake (0 = none); bounded, so a wedged
  # interface fails the drill instead of hanging it (measured on vps1: a `wg show` that waited 6 minutes)
  timeout -k 2 10 docker exec "$1" wg show wg9 latest-handshakes 2>/dev/null | awk '{print $2}' | head -1
}

wait_handshake() {  # container seconds [after]
  i=0
  while [ "$i" -lt "$2" ]; do
    h="$(handshake "$1")"
    [ "${h:-0}" -gt "${3:-0}" ] && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

pair_test() {  # a b ipA ipB label
  a="$1"; b="$2"; ia="$3"; ib="$4"; label="$5"
  if wait_handshake "$P-$a" 45 && wait_handshake "$P-$b" 10; then ok "$label: handshake both ways"
  else bad "$label: no handshake"; docker logs "$P-$a" 2>&1 | tail -8; docker logs "$P-$b" 2>&1 | tail -8; return; fi
  docker exec -d "$P-$b" python3 -m http.server --bind 10.79.9.2 8099 >/dev/null 2>&1
  sleep 2
  got="$(docker exec "$P-$a" python3 -c 'import urllib.request;print(urllib.request.urlopen("http://10.79.9.2:8099/",timeout=8).status)' 2>&1 | tail -1)"
  [ "$got" = "200" ] && ok "$label: HTTP across the tunnel ($got)" || bad "$label: HTTP across the tunnel: $got"
  mtu="$(docker exec "$P-$a" ip link show dev wg9 | sed -n 's/.* mtu \([0-9]*\).*/\1/p')"
  want=$((NET_MTU - 80))
  [ "$mtu" = "$want" ] && ok "$label: mtu $mtu (the endpoint's device, $NET_MTU, less 80)" || bad "$label: mtu $mtu, wg-quick's would be $want"
}

say "image $IMG on $(hostname) ($(uname -r))"
ka="$(keypair)"; kb="$(keypair)"
pa="$(printf '%s\n' "$ka" | sed -n 2p)"; pb="$(printf '%s\n' "$kb" | sed -n 2p)"
if [ "${#pa}" -ne 44 ] || [ "${#pb}" -ne 44 ]; then bad "wg genkey/pubkey in /etc/wireguard gave no key"; cleanup; exit 1; fi
side a "$(printf '%s\n' "$ka" | sed -n 1p)" 1 "$pb" 2 "$SUB.11"
side b "$(printf '%s\n' "$kb" | sed -n 1p)" 2 "$pa" 1 "$SUB.10"
start a "$SUB.10"; start b "$SUB.11"
pair_test a b "$SUB.10" "$SUB.11" "kernel"

sleep 16    # one turn of the loop: measure() runs every 15 s
st="$(docker exec "$P-a" cat /tunnel/wg-state.json 2>/dev/null)"
case "$st" in *'"wg9":{'*'"handshake":0,'*|'') bad "wg-state.json has no handshake: ${st:-missing}" ;;
              *'"wg9":{'*) ok "wg-state.json measures the pair" ;;
              *) bad "wg-state.json: $st" ;; esac
case "$st" in *PRIVATE*|*"$(sed -n 1p "$DIR/a/wg-private.key")"*) bad "wg-state.json carries a private key" ;; esac

before="$(handshake "$P-a")"
sleep 1; touch "$DIR/a/pairs/wg9.conf"   # a re-render: a new mtime, the same pair
if wait_handshake "$P-a" 50 "$before" && docker logs "$P-a" 2>&1 | grep -q "the plan changed"; then ok "re-applied after a re-render, and handshaked again"
else bad "the re-render was not re-applied"; docker logs "$P-a" 2>&1 | tail -6; fi

rm -f "$DIR/a/pairs/wg9.conf"
i=0; while [ "$i" -lt 40 ] && docker exec "$P-a" ip link show dev wg9 >/dev/null 2>&1; do sleep 1; i=$((i + 1)); done
docker exec "$P-a" ip link show dev wg9 >/dev/null 2>&1 && bad "a pair removed from the plan kept its interface" || ok "a pair removed from the plan lost its interface"
docker rm -f "$P-a" "$P-b" >/dev/null 2>&1

# the userspace fallback: `ip link add … type wireguard` refused, as on a kernel without WireGuard.
# Not on a host whose AppArmor profile for /usr/bin/wg is loaded: that profile allows wg no unix socket,
# and the userspace interface is driven through one (/var/run/wireguard/<iface>.sock) — measured on the
# Dell, «Unable to modify interface: Permission denied». Such a host has WireGuard in its kernel (Ubuntu
# 26.04 does), so the fallback is never taken there; it is drilled on a host without the profile.
if [ -e /etc/apparmor.d/wg ] && [ -d /sys/module/wireguard ]; then
  say "SKIP userspace: this host's AppArmor profile for wg forbids wg's control socket, and its kernel has WireGuard"
  say "$fails failure(s)"
  [ "$fails" -eq 0 ] && exit 0 || exit 1
fi
cat > "$DIR/ip-shim" <<'EOF'
#!/bin/sh
case " $* " in *" link add "*" type wireguard "*) echo "drill: no WireGuard in this kernel" >&2; exit 2 ;; esac
exec /usr/bin/ip "$@"
EOF
chmod 755 "$DIR/ip-shim"
side c "$(printf '%s\n' "$ka" | sed -n 1p)" 1 "$pb" 2 "$SUB.13"
side d "$(printf '%s\n' "$kb" | sed -n 1p)" 2 "$pa" 1 "$SUB.12"
start c "$SUB.12" -v "$DIR/ip-shim:/usr/local/bin/ip:ro" -e DGO_WG_MODULE=/nonexistent; start d "$SUB.13"
pair_test c d "$SUB.12" "$SUB.13" "userspace"
docker logs "$P-c" 2>&1 | grep -q "the userspace one (wireguard-go)" && ok "userspace: the applier says it fell back to wireguard-go" || bad "userspace: no fallback line in the log"

say "$fails failure(s)"      # the EXIT trap cleans up
[ "$fails" -eq 0 ] && exit 0 || exit 1
