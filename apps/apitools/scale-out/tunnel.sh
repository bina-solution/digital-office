#!/bin/bash
# Bidirectional ssh tunnel between the main box and the portable laptop's second apitools.
# Run supervised (it reconnects on drop) and leave it running; the load balancer depends on it.
#
#   -L 172.18.0.1:18080 -> portable 127.0.0.1:8080  traffic IN to the remote instance
#   -L 172.18.0.1:18082 -> portable 127.0.0.1:8082  gunicorn's master-process health sidecar
#   -R portable 127.0.0.1:19118 -> supabase-db:5432 the remote instance's shared OCR cache
#
# WHY -L AND NOT -R FOR THE TRAFFIC LEG: WSL2 sits behind NAT, so the portable box cannot open a
# connection to WSL. Both legs therefore ride ONE ssh connection that WSL initiates.
#
# THAT SHARED CONNECTION IS ALSO A SAFETY PROPERTY, not just convenience. ocr_cache.py silently
# falls back to a LOCAL json file cache when Postgres is unreachable (logging only a warning),
# which would split-brain the shared cache: the remote would write results the rest of the estate
# cannot see, and /docExists would answer "false" for documents that were in fact processed.
# Because the DB leg and the traffic leg are the same TCP connection, a tunnel drop takes BOTH
# down together -- haproxy's health check fails and the remote stops receiving traffic before it
# can write anything to a local cache. Do not split these into two ssh processes.
#
# The bind address 172.18.0.1 is the traefik-network BRIDGE GATEWAY, so the haproxy container
# (which lives on that network) can reach the forward. Binding 127.0.0.1 would be invisible to it.
#
# NEVER LET THIS CONNECTION BE MULTIPLEXED (the -o ControlMaster=no -o ControlPath=none below).
# If the operator's ~/.ssh/config has a `ControlMaster auto` stanza matching this host -- and a
# wildcard `Host <alias> <ip>` stanza does match, because we connect by literal IP -- then this
# process becomes a mux SLAVE. Its forwards leak into the master and are NOT released when it
# exits, so the next iteration of the loop hits an already-bound port, ExitOnForwardFailure fires,
# and this supervisor exits instantly. Forever. Observed 2026-08-11: four tunnel supervisors in a
# permanent fast-fail loop, 1,334 ssh spawn/exit cycles in 10 minutes, every one of them a no-op,
# with the entire tunnel estate hanging off a single unsupervised mux process.
#
# The damage is not just churn. Leaked forwards stay bound while their owner is gone, so a partial
# rebuild can bring up SOME legs and not others -- which defeats the shared-connection safety
# property described above. That is exactly what happened: a watchdog rebuilt this tunnel with only
# the -L 18080 traffic leg, dropping -R 19118. haproxy saw a healthy traffic leg and kept sending
# the remote 81.6% of requests, while ocr_cache.py silently fell back to a local JSON file cache
# (5,296 warnings in 6 hours) -- the exact split-brain the single-connection design exists to
# prevent. If you write a watchdog for this tunnel, it must restart THIS SCRIPT, never a
# hand-rolled ssh with a subset of the legs.
set -u

KEY=${PORTABLE_KEY:-/home/shlomo/.ssh/portable_key}
HOST=${PORTABLE_HOST:-shlomy@192.168.16.103}
GW=${BRIDGE_GW:-172.18.0.1}
RPORT=${DB_RPORT:-19118}
DOCKER_SOCK=${DOCKER_SOCK:-unix:///run/bbox-docker.sock}
DB_CONTAINER=${DB_CONTAINER:-supabase-db-shlomo-laptop}

log() { echo "$(date -Is) $*"; }

while true; do
  # supabase-db is attached to BOTH traefik-network and the supabase internal network, so a
  # `range` over .Networks concatenates two IPs into one unusable string. Index the exact network.
  DBIP=$(DOCKER_HOST=$DOCKER_SOCK docker inspect "$DB_CONTAINER" \
          --format '{{index .NetworkSettings.Networks "traefik-network" "IPAddress"}}' 2>/dev/null | head -1)
  if [ -z "$DBIP" ]; then
    log "ERROR: could not resolve $DB_CONTAINER on traefik-network; retrying in 15s"
    sleep 15
    continue
  fi
  log "connecting: -L $GW:18080/18082 -> portable 8080/8082 ; -R $RPORT -> $DBIP:5432"
  ssh -N -T \
    -o ControlMaster=no \
    -o ControlPath=none \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=20 \
    -o ServerAliveCountMax=3 \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o TCPKeepAlive=yes \
    -i "$KEY" \
    -L "$GW:18080:127.0.0.1:8080" \
    -L "$GW:18082:127.0.0.1:8082" \
    -R "127.0.0.1:$RPORT:$DBIP:5432" \
    "$HOST"
  log "tunnel exited (rc=$?), reconnecting in 5s"
  sleep 5
done
