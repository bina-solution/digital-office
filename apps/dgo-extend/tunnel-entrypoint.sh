#!/bin/sh
# dgo-net — apply the tunnel this office's declarations describe, and stay up.
#
# The CONFIG is not here: the app renders it (net.py) into /tunnel from the records it owns, and this
# script only applies what it finds. That split is the whole design — the applier has no opinion, so a
# change of plan is a re-render, not a new container.
#
# ONE INTERFACE PER PAIR (2026-10-04): the plan is `/tunnel/pairs/wg<slot>.conf`, one file per linked
# pair, and this container holds all of them. That is deliberate — a pair's door, its catalog listener
# and the console's aliases all live in ONE namespace (`linkproxy.py`'s doors bind the pair's tunnel
# address), so several interfaces inside this container is what makes a second link a plan change
# rather than a second container. A pair that is ADDED does not touch the interface of a pair that is
# already up.
#
# It never exits on a bad config: an office whose tunnel cannot come up is still an office, and the
# screens must be able to say "no tunnel" rather than showing a crash loop. Every failure is printed
# once and then waited on.
set -eu

log() { echo "[dgo-net] $*"; }
stamp() { stat -c %Y "$1" 2>/dev/null || echo 0; }
PAIRS_DIR=/tunnel/pairs
KEY=/tunnel/wg-private.key
WG_DIR=/etc/wireguard

# REPLACED, not merged. `nft -f` ADDS the rules of a chain that already exists, so applying the same
# document twice made every rule appear twice — measured 2026-10-01 on the MacBook, where `from_tunnel`
# held two copies of its `drop` and a `serve` accept that a later render REMOVED would have survived.
# firewall.py's contract is that the whole table is replaced on every apply, so the old table goes
# first. The window between the two commands is the price of not using `destroy table`, which the
# nftables this image installs does not know.
apply_firewall() {
  [ -s /tunnel/nftables.rules ] || return 0
  nft delete table inet dgo 2>/dev/null || true
  nft -f /tunnel/nftables.rules && log "firewall applied" \
    || log "nftables refused the rules — no allow-list is in force"
}

# The pairs this container is asked to hold: one name per rendered file, `wg<slot>`. A plan written
# before pairs existed (`/tunnel/wg0.conf`, and no `pairs/`) is applied as the single pair it was:
# a rollback to an older render, or the window between replacing this script and re-rendering, must
# not take a live link down.
planned_pairs() {
  found=0
  for conf in "$PAIRS_DIR"/*.conf; do
    [ -s "$conf" ] || continue
    basename "$conf" .conf
    found=1
  done
  if [ "$found" = "0" ] && [ -s /tunnel/wg0.conf ]; then
    echo "wg0"
  fi
}

# The rendered file for one interface, whichever layout wrote it.
pair_conf() {
  if [ -s "$PAIRS_DIR/$1.conf" ]; then echo "$PAIRS_DIR/$1.conf"; return 0; fi
  if [ "$1" = "wg0" ] && [ -s /tunnel/wg0.conf ]; then echo /tunnel/wg0.conf; return 0; fi
  return 1
}

# Bring ONE interface to what is rendered for it, and only when that changed. The applied copy carries
# the RENDERED file's mtime (`touch -r`), so "has this pair changed" is one comparison rather than a
# state file that can drift from the files it describes.
apply_pair() {
  name="$1"
  conf="$(pair_conf "$name")" || return 0
  applied="$WG_DIR/$name.conf"
  if [ -s "$applied" ] && [ "$(stamp "$applied")" = "$(stamp "$conf")" ] \
     && wg show "$name" >/dev/null 2>&1; then
    return 0
  fi
  if [ ! -s "$KEY" ]; then
    log "$name: no private key rendered yet — waiting"
    return 0
  fi
  wg-quick down "$name" 2>/dev/null || true
  if sed "s|@PRIVATE@|$(cat "$KEY")|" "$conf" > "$applied"; then
    chmod 600 "$applied"
    touch -r "$conf" "$applied"
    if wg-quick up "$name"; then
      log "$name up: $(wg show "$name" | head -1)"
    else
      log "$name: wg-quick failed — this pair runs without a tunnel. Check NET_ADMIN, /dev/net/tun and the peer's endpoint."
    fi
  else
    log "$name: the rendered config could not be written — waiting for the next render"
  fi
}

# An interface that is no longer in the plan is taken down HERE rather than left holding an address
# and a route: a removed link that keeps its interface is a door nobody declared.
retire_absent() {
  planned="$1"
  for applied in "$WG_DIR"/*.conf; do
    [ -e "$applied" ] || continue
    name="$(basename "$applied" .conf)"
    case " $planned " in
      *" $name "*) continue ;;
    esac
    log "$name is no longer in the plan — down"
    wg-quick down "$name" 2>/dev/null || true
    rm -f "$applied"
  done
}

apply_plan() {
  mkdir -p "$WG_DIR"
  chmod 700 "$WG_DIR"
  planned="$(planned_pairs | tr '\n' ' ')"
  # RETIRE FIRST, THEN APPLY. A pair keeps its address when its interface is RENAMED (`wg0` → `wg<slot>`,
  # the one-interface-per-pair change), and two interfaces cannot hold one address: bringing the new one
  # up before the old one is down fails with `RTNETLINK answers: Address already in use`, the new
  # interface is deleted, and the plan then retires the old one — leaving the office with NO tunnel at
  # all. Measured 2026-10-04 on this Mac, on the first live pairing: vps1's link dropped for ~2 minutes
  # exactly this way. The order below is the fix.
  retire_absent "$planned"
  for name in $planned; do
    apply_pair "$name"
  done
  apply_firewall
}

# What the tunnel MEASURES, written where the app can read it. The interface lives in this container
# and nowhere else, so until this existed no screen could tell a live tunnel from one that had not
# completed a handshake in fifteen hours (issues/the-office-tunnel-wedges-silently-and-nothing-
# measures-it.yaml) — the app saw files, not packets. Per pair: where the peer was last heard from,
# when the last handshake completed (0 = never since this container started), the byte counters.
# NO KEY LEAVES HERE: the interface's own line of `wg show dump` (it holds the private key) is
# skipped, and of the peer's line only fields 3, 5, 6 and 7 are written.
measure() {
  {
    printf '{"at":%s,"pairs":{' "$(date +%s)"
    sep=""
    for n in $(wg show interfaces 2>/dev/null); do
      line="$(wg show "$n" dump 2>/dev/null | sed -n 2p)"
      [ -n "$line" ] || continue
      printf '%s\n' "$line" | awk -v n="$n" -v sep="$sep" \
        '{ printf "%s\"%s\":{\"endpoint\":\"%s\",\"handshake\":%d,\"rx\":%d,\"tx\":%d}", sep, n, $3, $5, $6, $7 }'
      sep=","
    done
    printf '}}\n'
  } > /tunnel/wg-state.json.tmp 2>/dev/null && mv -f /tunnel/wg-state.json.tmp /tunnel/wg-state.json || true
}

if [ -z "$(planned_pairs)" ]; then
  log "no tunnel rendered yet (/tunnel has no pairs) — waiting. The app writes it with POST /api/tunnel/render"
  # WAITED FOR, not given up on. This used to be `exec sleep infinity`, which is a container that can
  # never notice the plan arriving: measured 2026-10-01 on the MacBook, the link step rendered both
  # ends, the peer came up on vps1, and this side sat in that branch for the life of the container —
  # a tunnel that was correct everywhere except the machine that started it.
  while [ -z "$(planned_pairs)" ] || [ ! -s "$KEY" ]; do
    sleep 10
  done
  log "a tunnel appeared — applying it"
fi

# FIND A PEER WHOSE ADDRESS MOVED. A pair's endpoint is a fact of the PAIRING — written on both ends
# when they paired — and a home router hands out a new address whenever the machine reconnects (DHCP).
# Measured 2026-10-07: hp-laptop's Wi-Fi came back as 192.168.16.100 while the pair still said
# 192.168.16.102, and every packet went to an address nobody holds, for hours, with the handshake
# counted as sent. Nothing local can tell that; the peer can. A WireGuard handshake IS the
# identification — only the holder of that key completes one — so the app writes the addresses to try
# (`/tunnel/scan.cmd`) and reads the answer here (`/tunnel/scan.result`). Same contract as the rest of
# this container: the app decides WHAT, this script only does it, and the answer is a file.
scan_peer() {
  req=/tunnel/scan.cmd
  res=/tunnel/scan.result
  [ -s "$req" ] || return 0
  want="$(sed -n 's/^want //p' "$req" | head -1)"
  [ -n "$want" ] || return 0
  # One answer per request: a result that names this `want` has already been written.
  [ "$(sed -n 's/^want //p' "$res" 2>/dev/null | head -1)" = "$want" ] && return 0
  iface="$(sed -n 's/^iface //p' "$req" | head -1)"
  peer="$(sed -n 's/^peer //p' "$req" | head -1)"
  port="$(sed -n 's/^port //p' "$req" | head -1)"
  if ! wg show "$iface" >/dev/null 2>&1; then
    log "scan $want: no interface $iface — nothing to probe"
    return 0
  fi
  found=""
  tried=0
  lost="$(sed -n 's/^Endpoint *= *//p' "$(pair_conf "$iface" 2>/dev/null)" 2>/dev/null | head -1)"
  # A handshake is NOT sent the moment an endpoint changes: the pair keeps its session alive every
  # 25 s, and waiting for that tick would make one /24 take an hour. Lowering the keepalive makes the
  # next one an immediate probe. The window is FIVE SECONDS because the answer is not instant —
  # measured 2026-10-07: two to four seconds, and a 2 s window missed every one of them while
  # crediting the address that came after it (a stamp has one-second resolution).
  wg set "$iface" peer "$peer" persistent-keepalive 1 2>/dev/null || true
  for ip in $(sed -n 's/^cand //p' "$req"); do
    tried=$((tried + 1))
    t_set="$(date +%s)"
    wg set "$iface" peer "$peer" endpoint "$ip:$port" 2>/dev/null || break
    for _try in 1 2 3 4 5 6 7 8 9 10; do
      sleep 0.5
      hs="$(wg show "$iface" latest-handshakes 2>/dev/null | awk -v p="$peer" '$1 == p {print $2}' || true)"
      if [ "${hs:-0}" -ge "$t_set" ]; then
        # A HIT IS CONFIRMED, NEVER BELIEVED. A handshake stamp has one-second resolution and the
        # answer to an initiation sent to the PREVIOUS address arrives after this one is set, so the
        # stamp alone can credit the wrong address — measured 2026-10-07, when a scan adopted
        # `192.168.16.82` (which never answered) over `192.168.16.100` (which did). The address that
        # is left out, then tried again and handshakes a SECOND time inside its own window, is the
        # peer; a stamp left over from an earlier candidate cannot do that.
        if [ -n "$lost" ]; then
          wg set "$iface" peer "$peer" endpoint "$lost" 2>/dev/null || true
          sleep 1.2
        fi
        t_set="$(date +%s)"
        wg set "$iface" peer "$peer" endpoint "$ip:$port" 2>/dev/null || true
        for _confirm in 1 2 3 4 5 6 7 8 9 10 11 12; do
          sleep 0.5
          hs="$(wg show "$iface" latest-handshakes 2>/dev/null | awk -v p="$peer" '$1 == p {print $2}' || true)"
          if [ "${hs:-0}" -ge "$t_set" ]; then
            found="$ip"
            break
          fi
        done
        break
      fi
    done
    if [ -n "$found" ]; then
      break
    fi
  done
  # The last candidate is not a decision: the interface goes back to the endpoint the plan declares
  # (the app writes the found address into the record and re-renders, and that is what makes it
  # stick), and the keepalive back to the pair's own.
  plan_ep="$(sed -n 's/^Endpoint *= *//p' "$(pair_conf "$iface" 2>/dev/null)" 2>/dev/null | head -1)"
  if [ -n "$plan_ep" ]; then
    wg set "$iface" peer "$peer" endpoint "$plan_ep" 2>/dev/null || true
  fi
  wg set "$iface" peer "$peer" persistent-keepalive "${WG_KEEPALIVE:-25}" 2>/dev/null || true
  {
    echo "want $want"
    echo "found $found"
    echo "tried $tried"
    echo "at $(date +%s)"
  } > "$res.tmp" 2>/dev/null && mv -f "$res.tmp" "$res" || true
  log "scan $want: ${found:-no peer found} after $tried address(es)"
}

apply_plan
measure

# Re-apply when the app renders a new plan: mtimes, cheap, no inotify dependency. BOTH artifacts are
# watched, and each on its own: the firewall changes on a `serve:` declaration alone (a port added or
# removed with no change to the tunnel), and a rule that is rendered but never applied is a door a
# person believes is open.
last_fw="$(stamp /tunnel/nftables.rules)"
last_plan="$(planned_pairs | while read -r n; do printf '%s:%s ' "$n" "$(stamp "$(pair_conf "$n" || echo /dev/null)")"; done)"
while true; do
  sleep 15
  scan_peer
  measure
  now_fw="$(stamp /tunnel/nftables.rules)"
  now_plan="$(planned_pairs | while read -r n; do printf '%s:%s ' "$n" "$(stamp "$(pair_conf "$n" || echo /dev/null)")"; done)"
  if [ "$now_plan" = "$last_plan" ]; then
    if [ "$now_fw" != "$last_fw" ]; then
      last_fw="$now_fw"
      log "firewall rules changed — re-applying"
      apply_firewall
    fi
    continue
  fi
  last_plan="$now_plan"
  last_fw="$now_fw"
  if [ -z "$(planned_pairs)" ]; then
    # A REVOKE removes the files, and that is a state this script must SURVIVE rather than die from:
    # `sed` on a missing file under `set -e` killed it, the container restarted, and the tunnel was
    # then gone for the length of a restart instead of for the length of a decision (measured
    # 2026-10-01).
    log "the plan is empty (the tunnel was taken down) — retiring every interface"
  else
    log "the plan changed — re-applying"
  fi
  apply_plan
done
