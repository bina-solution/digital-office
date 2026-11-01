#!/bin/bash
# Bring up (or tear down) the apitools scale-out: a second instance on the portable laptop plus
# the load balancer that puts it behind the `apitools` name the pipeline hardcodes.
#
#   ./up.sh remote      build + start the second instance on the portable box
#   ./up.sh lb          start the load balancer and give it the `apitools` alias
#   ./up.sh signer      copy the dev signing cert to the portable (see the drift note)
#   ./up.sh lb-portable ON-BOX routing: haproxy on the PORTABLE takes over the `apitools`
#                       name for the workers that live there (measured 38.4ms -> 2.3ms)
#   ./up.sh lb-portable-down   roll on-box routing back to the socat tunnel forward
#   ./up.sh drift       report config divergence between the two instances
#   ./up.sh status      show the split (haproxy counters + both instances)
#   ./up.sh down        remove the LB  -> 100% of traffic returns to the local instance
#
# ORDER MATTERS: `tunnel.sh` must already be running before `lb`, or haproxy marks the remote
# DOWN and every request falls through to the local backup (correct, but pointless).
#
# WHY THE IMAGE IS BUILT ON THE PORTABLE BOX RATHER THAN COPIED:
#   .dockerignore excludes storage/ (9.9G) and feature-validation/ (709M), so the build CONTEXT
#   is only ~21MB. Shipping that and building remotely costs the main box a 17MB upload, versus
#   ~1.9GB for `docker save | ssh docker load` -- which on this host previously saturated the
#   disk and caused a 12-minute DNS incident. The build itself then runs on the idle machine.
#   Do NOT reuse the apitools image already cached on the portable box: it is from 2026-07-24 and
#   predates the findOptionMatching fix, so it would reintroduce 178-206s pathological calls.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
export DOCKER_HOST=${DOCKER_HOST:-unix:///run/bbox-docker.sock}
KEY=${PORTABLE_KEY:-/home/shlomo/.ssh/portable_key}
HOST=${PORTABLE_HOST:-shlomy@192.168.16.103}
SSHO="-i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
APP=$(cd "$HERE/.." && pwd)

case "${1:-status}" in

remote)
  echo "== shipping build context (~21MB) =="
  cd "$APP"
  nice -n 19 ionice -c3 tar --exclude=./storage --exclude=./feature-validation \
    --exclude=./logs --exclude=./logs2 --exclude=./tests --exclude=./docs \
    --exclude=./__pycache__ --exclude='*.pyc' --exclude=./.git \
    -czf /tmp/apitools-ctx.tgz . 2>/dev/null
  ssh $SSHO $HOST 'rm -rf /tmp/apitools-ctx && mkdir -p /tmp/apitools-ctx'
  nice -n 19 ionice -c3 scp $SSHO /tmp/apitools-ctx.tgz $HOST:/tmp/apitools-ctx.tgz
  ssh $SSHO $HOST 'cd /tmp/apitools-ctx && tar xzf /tmp/apitools-ctx.tgz'

  echo "== building on the portable box =="
  ssh $SSHO $HOST 'cd /tmp/apitools-ctx && docker build -t apitools-remote:current . 2>&1 | tail -5'

  # EVERY REBUILD ORPHANS THE PREVIOUS IMAGE. Re-tagging `apitools-remote:current` leaves
  # the old one dangling (<none>:<none>) holding its full layer set, and the build cache
  # grows alongside it. MEASURED 2026-08-11 on the portable: 43.9 GB of images of which
  # 39.4 GB reclaimable, plus 2.8 GB of build cache, on a 234 GB disk with 20 GB free
  # (92%). That is the actual reason the portable is nearly full -- its apitools storage
  # is only 4.3 GB. Reap it here, where it is created, instead of discovering it later as
  # a disk alert.
  # DANGLING ONLY (`prune -f`, never `-a`): `-a` removes every image no *running*
  # container references, which on this box would delete the n8n/runner images that other
  # workers are one restart away from needing.
  echo "== reclaiming build leftovers on the portable =="
  ssh $SSHO $HOST 'docker image prune -f 2>/dev/null | tail -1; docker builder prune -f 2>/dev/null | tail -1; df -h / | tail -1'

  echo "== env, taken FROM THE RUNNING LOCAL CONTAINER so nothing is missed =="
  SKIP='^(PATH|GPG_KEY|LANG|PYTHON_VERSION|PYTHON_SHA256|PIP_NO_CACHE_DIR|PIP_DISABLE_PIP_VERSION_CHECK|PYTHONUNBUFFERED|PYTHONDONTWRITEBYTECODE|HOSTNAME|HOME)='
  umask 077
  docker inspect apitools --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -vE "$SKIP" | grep -v '^$' > /tmp/apitools-remote.env
  # Postgres is reached back through the ssh -R listener on the portable box's loopback.
  sed -i 's|^SUPABASE_DB_HOST=.*|SUPABASE_DB_HOST=127.0.0.1|' /tmp/apitools-remote.env
  sed -i 's|^DOC_DB_PORT=.*|DOC_DB_PORT=19118|'               /tmp/apitools-remote.env
  # Size to the portable box (4 cores / 15GB), not this one (6 cores / 9.95GB).
  sed -i 's|^GUNICORN_WORKERS=.*|GUNICORN_WORKERS=6|'                       /tmp/apitools-remote.env
  sed -i 's|^APITOOLS_MAX_CONCURRENT_OCR=.*|APITOOLS_MAX_CONCURRENT_OCR=6|' /tmp/apitools-remote.env
  sed -i 's|^APITOOLS_MAX_CONCURRENT_PDF=.*|APITOOLS_MAX_CONCURRENT_PDF=6|' /tmp/apitools-remote.env
  sed -i 's|^APITOOLS_MAX_CONCURRENT_JSON_QUERY=.*|APITOOLS_MAX_CONCURRENT_JSON_QUERY=8|' /tmp/apitools-remote.env
  # So a GlitchTip event from the laptop is identifiable as such.
  sed -i 's|^SENTRY_ENVIRONMENT=.*|SENTRY_ENVIRONMENT=production-portable|' /tmp/apitools-remote.env
  # N8N_ENCRYPTION_KEY is deliberately absent: apitools does not use it, so it is not shipped.

  # Piped over stdin so the secrets never appear in a remote process list.
  ssh $SSHO $HOST 'umask 077; mkdir -p ~/apitools-storage ~/apitools-logs; cat > ~/apitools-remote.env' \
    < /tmp/apitools-remote.env
  rm -f /tmp/apitools-remote.env

  # THE SIGNING CERT IS PER-INSTANCE STATE AND MUST NOT BE MINTED TWICE.
  # signing.py generates a self-signed dev signer and caches it in .storage when
  # SIGN_CERT_P12 is unset (it is unset on both instances). The cert existed on the host
  # and NOT on the portable, so the first signed /docGen served by the portable would
  # have minted a SECOND, different certificate — and documents would then carry one of
  # two signers depending purely on which instance haproxy happened to pick. Ship it as
  # part of provisioning so the two instances are the same signer by construction.
  "$HERE/up.sh" signer || echo "WARNING: signer distribution failed; check ./up.sh drift"

  echo "== starting remote instance =="
  # GRACEFUL REPLACE, NOT `rm -f`. `docker rm -f` sends SIGKILL and drops every in-flight
  # request instantly; on this backend that means killing /documentOcr calls that
  # legitimately run for seconds to minutes, and each one becomes an API_TOOLS_FAILED
  # document. The container is created with --stop-signal SIGQUIT --stop-timeout 30, so
  # `docker stop` drains gunicorn properly. Same lesson as the LB reload below.
  ssh $SSHO $HOST 'docker stop apitools-remote 2>/dev/null; docker rm -f apitools-remote 2>/dev/null || true; docker run -d \
    --name apitools-remote --network host --restart unless-stopped \
    --env-file ~/apitools-remote.env \
    -v ~/apitools-storage:/app/.storage -v ~/apitools-logs:/app/logs \
    --memory 6g --stop-signal SIGQUIT --stop-timeout 30 \
    --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
    apitools-remote:current \
    gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8080 run:application'
  ;;

lb)
  LBDIR=${LB_CFG_DIR:-/home/shlomo/apitools-lb}
  mkdir -p "$LBDIR" 2>/dev/null
  # THE CONFIG FILE CAN BE ROOT-OWNED and this script does not run as root, so the write
  # silently fails and the `docker kill -s USR2` below then reloads the OLD config —
  # a "successful" no-op deploy. Observed 2026-08-11 18:26Z. Fail loudly, and fix the
  # mode through a container (the only root this script reliably has) rather than sudo,
  # which is not available non-interactively here.
  if [ -e "$LBDIR/haproxy.cfg" ] && [ ! -w "$LBDIR/haproxy.cfg" ]; then
    echo "config not writable ($(ls -ld "$LBDIR/haproxy.cfg" | awk '{print $3":"$4" "$1}')) — fixing mode via a container"
    docker run --rm -v "$LBDIR":/t alpine:latest sh -c 'chmod 666 /t/haproxy.cfg' \
      || { echo "could not make $LBDIR/haproxy.cfg writable; aborting rather than reloading the OLD config"; exit 1; }
  fi
  # CRLF from the Windows tree makes haproxy fail with cryptic parse errors.
  tr -d '\r' < "$HERE/haproxy.cfg" > "$LBDIR/haproxy.cfg" \
    || { echo "write failed; aborting rather than reloading the OLD config"; exit 1; }
  # Prove the file on disk is the file we meant to deploy before anything is reloaded.
  if ! cmp -s <(tr -d '\r' < "$HERE/haproxy.cfg") "$LBDIR/haproxy.cfg"; then
    echo "deployed config does not match the repo copy; aborting"; exit 1
  fi
  docker run --rm --network traefik-network \
    -v "$LBDIR"/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
    haproxy:alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg || {
      echo "config invalid, not deploying"; exit 1; }
  # IF THE LB IS ALREADY RUNNING AND ONLY haproxy.cfg CHANGED, RELOAD IT -- DO NOT RECREATE.
  # `docker rm -f` sends SIGKILL, which drops every in-flight request instantly. On this backend
  # that means killing /documentOcr calls that legitimately run for seconds to minutes, and each
  # one becomes an API_TOOLS_FAILED document. Four config iterations during this build did
  # exactly that. The official haproxy image runs in master-worker mode, so SIGUSR2 re-execs the
  # master and finishes in-flight requests on the old worker.
  if docker ps --filter name=apitools-lb --filter status=running -q | grep -q .; then
    echo "LB already running - reloading config gracefully (SIGUSR2), keeping in-flight requests"
    docker kill -s USR2 apitools-lb
    sleep 3
    docker ps --filter name=apitools-lb --format '{{.Names}}|{{.Status}}'
    exit 0
  fi
  # Two aliases: `apitools` puts it in the production DNS rotation ALONGSIDE the real container;
  # `apitools-lb` stays available for testing it in isolation.
  docker run -d --name apitools-lb --network traefik-network \
    --network-alias apitools --network-alias apitools-lb \
    --restart unless-stopped \
    -v "$LBDIR"/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
    --memory 96m --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
    haproxy:alpine
  ;;

signer)
  # Mint-once-then-distribute. The alternative — setting SIGN_CERT_P12 to a real CA cert
  # on both instances — is strictly better and makes this a no-op; until then, one shared
  # dev cert beats two different ones.
  SRC="$APP/storage/dev_signer.p12"
  if [ ! -f "$SRC" ]; then
    echo "no $SRC on this box; nothing to distribute (it is minted on first signed /docGen)"
    exit 0
  fi
  echo "== distributing dev_signer.p12 ($(stat -c%s "$SRC") bytes) =="
  # Piped over stdin: the key never lands in a remote process list or a temp file path.
  ssh $SSHO $HOST 'umask 077; mkdir -p ~/apitools-storage; cat > ~/apitools-storage/dev_signer.p12' < "$SRC"
  L=$(sha256sum "$SRC" | cut -c1-16)
  R=$(ssh $SSHO $HOST 'sha256sum ~/apitools-storage/dev_signer.p12 | cut -c1-16')
  [ "$L" = "$R" ] && echo "  ok  identical on both ($L)" || { echo "  MISMATCH local=$L remote=$R"; exit 1; }
  ;;

lb-portable)
  # ON-BOX ROUTING. Replaces the socat that forwarded the portable's `apitools` name
  # (127.0.0.10:8080) back across the tunnel to the HOST's load balancer — which then
  # sent 20/21 of it straight back over the same WiFi link to the instance already
  # running on the portable. See haproxy-portable.cfg for the measurements.
  echo "== validating config =="
  tr -d '\r' < "$HERE/haproxy-portable.cfg" > /tmp/haproxy-portable.cfg
  ssh $SSHO $HOST 'mkdir -p ~/apitools-lb-portable; cat > ~/apitools-lb-portable/haproxy.cfg' < /tmp/haproxy-portable.cfg
  ssh $SSHO $HOST 'docker run --rm --network host \
      -v ~/apitools-lb-portable/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
      haproxy:alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg' || {
    echo "config invalid, not deploying"; exit 1; }

  # Already running? Reload in place (SIGUSR2 re-execs the master and lets in-flight
  # requests finish on the old worker). Never `rm -f` a live proxy — see the note above.
  if ssh $SSHO $HOST 'docker ps --filter name=apitools-lb-portable --filter status=running -q | grep -q .'; then
    echo "== reloading in place (SIGUSR2) =="
    ssh $SSHO $HOST 'docker kill -s USR2 apitools-lb-portable'
    exit 0
  fi

  # THE HANDOVER. socat owns 127.0.0.10:8080, so there is an unavoidable moment where the
  # address is unbound. Keep it as short as possible: pre-pull the image, then stop socat
  # and start haproxy in ONE remote command with nothing in between.
  echo "== pre-pulling haproxy:alpine on the portable =="
  ssh $SSHO $HOST 'docker image inspect haproxy:alpine >/dev/null 2>&1 || docker pull -q haproxy:alpine'
  echo "== handover: socat -> haproxy on 127.0.0.10:8080 =="
  # NEVER `pkill -f socat.*bind=127.0.0.10` HERE. The pattern appears in this very
  # command's own argv, so pkill -f matches the shell running it and the handover kills
  # ITSELF -- socat dies, haproxy is never started, and the `apitools` name is simply
  # gone for every worker on this box. That happened on the first attempt (2026-08-11
  # 18:11Z). Resolve the owner by PORT via ss and kill that exact pid instead.
  ssh $SSHO $HOST 'set -u
    PID=$(ss -ltnp 2>/dev/null | grep "127\.0\.0\.10:8080" | sed -n "s/.*pid=\([0-9]*\).*/\1/p" | head -1)
    if [ -n "$PID" ]; then
      tr "\0" " " < /proc/$PID/cmdline > ~/apitools-lb-portable/socat.rollback 2>/dev/null
      echo "  stopping listener pid=$PID ($(cat ~/apitools-lb-portable/socat.rollback))"
      kill "$PID" 2>/dev/null
      for i in 1 2 3 4 5; do ss -ltn | grep -q "127\.0\.0\.10:8080" || break; sleep 1; done
    fi
    docker rm -f apitools-lb-portable >/dev/null 2>&1 || true
    docker run -d --name apitools-lb-portable --network host --restart unless-stopped \
      -v ~/apitools-lb-portable/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
      --memory 96m --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
      haproxy:alpine >/dev/null || echo "  docker run FAILED"
    sleep 3
    docker ps --filter name=apitools-lb-portable --format "  {{.Names}}|{{.Status}}"

    # AUTO-ROLLBACK. This address is how every n8n worker on this box reaches apitools;
    # leaving it unbound is worse than not having tried. If haproxy is not serving within
    # a few seconds, put the tunnel forward back and fail loudly.
    ok=0
    for i in 1 2 3 4 5 6; do
      c=$(curl -s -o /dev/null -m 5 -w "%{http_code}" http://127.0.0.10:8080/ 2>/dev/null)
      [ "$c" = "200" ] && { ok=1; break; }
      sleep 2
    done
    if [ "$ok" != 1 ]; then
      echo "  HANDOVER FAILED (last code=$c) -- rolling back to the tunnel forward"
      docker logs apitools-lb-portable 2>&1 | tail -15
      docker rm -f apitools-lb-portable >/dev/null 2>&1 || true
      CMD=$(cat ~/apitools-lb-portable/socat.rollback 2>/dev/null)
      [ -z "$CMD" ] && CMD="socat TCP-LISTEN:8080,bind=127.0.0.10,fork,reuseaddr,keepalive TCP:127.0.0.1:19021"
      nohup $CMD >/dev/null 2>&1 &
      sleep 2
      curl -s -o /dev/null -m 10 -w "  rolled back: apitools:8080 -> %{http_code}\n" http://127.0.0.10:8080/
      exit 1
    fi
    echo "  handover OK"'
  echo "== verify =="
  ssh $SSHO $HOST 'curl -s -o /dev/null -m 10 -w "  apitools:8080 (127.0.0.10) -> %{http_code} in %{time_total}s\n" http://127.0.0.10:8080/
    curl -s -m 5 "http://127.0.0.1:8405/;csv" | awk -F, "\$1~/^(be_|apitools_fe)/{print \"  \"\$1\",\"\$2\",\"\$18\",\"\$5}"'
  ;;

lb-portable-down)
  # Rollback: haproxy out, socat back exactly as it was.
  echo "== rolling back to the tunnel forward =="
  ssh $SSHO $HOST 'docker rm -f apitools-lb-portable >/dev/null 2>&1 || true
    CMD=$(cat ~/apitools-lb-portable/socat.rollback 2>/dev/null)
    [ -z "$CMD" ] && CMD="socat TCP-LISTEN:8080,bind=127.0.0.10,fork,reuseaddr,keepalive TCP:127.0.0.1:19021"
    nohup $CMD >/dev/null 2>&1 &
    sleep 2
    curl -s -o /dev/null -m 10 -w "  apitools:8080 -> %{http_code}\n" http://127.0.0.10:8080/'
  ;;

drift)
  exec "$HERE/drift-check.sh" "${2:-}"
  ;;

status)
  echo "== haproxy counters =="
  docker exec apitools-lb sh -c 'wget -qO- "http://127.0.0.1:8404/;csv"' 2>/dev/null \
    | awk -F, 'NR==1||$1 ~ /be_/ {print $1","$2","$5","$8","$18","$41}' | column -t -s,
  echo "== on-box (portable) haproxy counters =="
  ssh $SSHO $HOST 'curl -s -m 5 "http://127.0.0.1:8405/;csv" 2>/dev/null' \
    | awk -F, 'NR==1||$1 ~ /be_/ {print $1","$2","$5","$8","$18","$41}' | column -t -s,
  echo "== shared-cache readiness (the thing `GET /` cannot tell you) =="
  docker exec apitools sh -c 'wget -qO- http://127.0.0.1:8080/readyz' 2>/dev/null | sed 's/^/  local:  /'; echo
  ssh $SSHO $HOST 'docker exec apitools-remote sh -c "wget -qO- http://127.0.0.1:8080/readyz"' 2>/dev/null | sed 's/^/  remote: /'; echo
  echo "== local ==";  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' apitools apitools-lb
  echo "== remote =="; ssh $SSHO $HOST 'docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}}" apitools-remote apitools-lb-portable'
  ;;

down)
  # Removing the LB drops its `apitools` DNS record, so 100% of traffic returns to the local
  # instance immediately. This is the rollback; it needs no change to any caller.
  docker rm -f apitools-lb
  echo "LB removed - all apitools traffic is local again."
  echo "The remote instance and tunnel are left running; stop them separately if intended:"
  echo "  ssh <portable> docker stop apitools-remote   # drains in-flight work (SIGQUIT, 30s)"
  echo "  pkill -f apitools/scale-out/tunnel.sh"
  ;;

*) echo "usage: $0 {remote|lb|signer|lb-portable|lb-portable-down|drift|status|down}"; exit 2 ;;
esac
