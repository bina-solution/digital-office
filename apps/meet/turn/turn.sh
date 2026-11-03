#!/bin/bash
# meet-turn — the media path for a browser whose network lets no UDP out (a company's wifi, a hotel,
# a cloud sandbox): TURN over TLS on 443, the one port every network leaves open. The edge (traefik)
# ends TLS for meet-turn.<domain> and hands the plain TCP stream here; this relays it as UDP to the
# office's video bridge, and to nothing else.
#
# Two addresses are derived at start, because neither is fixed:
#   the bridge's   — the only peer a relay may reach (every other address is denied: a TURN server
#                    that relays anywhere is a door into the office's private network);
#   our own one on the bridge's network — where relayed packets leave from, so the bridge's answers
#                    come back on the same network (Docker drops traffic between two networks).
# When the bridge's address changes (it was recreated), this exits and Docker starts it again.
set -euo pipefail
: "${MEET_TURN_SECRET:?meet-turn: MEET_TURN_SECRET is empty — apps/meet/hooks/prepare mints it into .env}"

ip2int() { local IFS=.; read -r a b c d <<<"$1"; echo $(( (a << 24) | (b << 16) | (c << 8) | d )); }
hex2int() { local h=$1; echo $(( 0x${h:6:2}${h:4:2}${h:2:2}${h:0:2} )); }   # /proc/net/route is little-endian

bridge() { getent ahostsv4 meet-jvb | awk 'NR == 1 { print $1 }'; }
JVB=""
for _ in $(seq 1 60); do JVB="$(bridge)"; [ -n "$JVB" ] && break; sleep 2; done
[ -n "$JVB" ] || { echo "meet-turn: the bridge (meet-jvb) does not resolve"; exit 1; }

LOCALS="$(grep -B1 '/32 host LOCAL' /proc/net/fib_trie | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort -u | grep -v '^127\.')"
RELAY=""
while read -r iface dest _gw _flags _ref _use _metric mask _rest; do
  if [ "$iface" = Iface ] || [ "$mask" = 00000000 ]; then continue; fi
  d=$(hex2int "$dest"); m=$(hex2int "$mask")
  if (( ($(ip2int "$JVB") & m) != d )); then continue; fi
  for ip in $LOCALS; do
    if (( ($(ip2int "$ip") & m) == d )); then RELAY="$ip"; fi
  done
done < /proc/net/route
[ -n "$RELAY" ] || { echo "meet-turn: no address of ours shares a network with the bridge ($JVB)"; exit 1; }
echo "meet-turn: relaying from $RELAY to the bridge at $JVB only"

turnserver \
  --listening-port=3478 --no-tls --no-dtls --no-udp \
  --relay-ip="$RELAY" --min-port=49160 --max-port=49359 \
  --use-auth-secret --static-auth-secret="$MEET_TURN_SECRET" --realm=meet.jitsi \
  --denied-peer-ip=0.0.0.0-255.255.255.255 --allowed-peer-ip="$JVB" \
  --no-tcp-relay --no-multicast-peers --no-cli --fingerprint --no-software-attribute \
  --user-quota=12 --total-quota=1200 \
  --userdb=/tmp/turndb --pidfile=/tmp/turnserver.pid --log-file=stdout --simple-log &
TURN=$!

while sleep 30; do
  kill -0 "$TURN" 2>/dev/null || exit 1
  now="$(bridge)"
  if [ -n "$now" ] && [ "$now" != "$JVB" ]; then
    echo "meet-turn: the bridge moved ($JVB → $now); restarting to follow it"
    kill "$TURN"; exit 1
  fi
done
