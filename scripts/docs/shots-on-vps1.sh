#!/usr/bin/env bash
# shots-on-vps1.sh <page>… — run ON vps1 (piped through `bbox computers ssh … 'bash -s -- <pages>'`): screenshots of
# the BUILT docs (/opt/bina-sites/dgo-docs/site), the way a reader sees them, at 1440×1000 and a phone's 390×844 @2x.
# Not on the Mac (8 GB; the coordinator, 2026-11-11): here, one page at a time, under the host's heavy lock. Each shot
# is its own throwaway container from the meet recorder's image (it carries Chrome and python3): `--init`, no
# network at all (the tree is served on the container's own loopback, read-only, under the preview's prefix so every
# link and asset resolves), and a hard `timeout -k`. Writes PNGs to /tmp/dgo-shots/, prints their names and sizes.
# <page> is a path under he/, e.g. `apps/console`.
set -uo pipefail
SITE=/opt/bina-sites/dgo-docs/site
OUT=/tmp/dgo-shots
IMG="${DGO_SHOTS_IMAGE:-$(docker inspect -f '{{.Config.Image}}' meet-jibri-staging 2>/dev/null)}"
[ -n "$IMG" ] || { echo "no Chrome image (meet-jibri-staging not found; set DGO_SHOTS_IMAGE)"; exit 1; }
mkdir -p "$OUT"
uptime
# DGO_SHOTS_NO_LOCK=1: a page or two is light (one Chrome at a time, 1 CPU, 90 s cap each) and may run beside a heavy
# job when the coordinator says so (2026-11-11 10:50Z: «light, outside the heavy lock»); a batch of pages takes it.
if [ -z "${DGO_SHOTS_NO_LOCK:-}" ]; then
  exec 9>/tmp/dgo-heavy.lock
  flock -w 1200 9 || { echo "the heavy lock stayed taken for 20 minutes — nothing shot"; exit 1; }
fi
for page in "$@"; do
  name="$(echo "$page" | tr '/' '-')"
  for size in desktop phone; do
    if [ "$size" = desktop ]; then win=1440,1000; dpr=1; else win=390,844; dpr=2; fi
    timeout -k 10 90 docker run --rm --init --network none --user 0 --shm-size 256m \
      -v "$SITE":/srv/a/sites/public/dgo-docs:ro -v "$OUT":/out --entrypoint sh "$IMG" -c "
        cd /srv && (python3 -m http.server 8799 --bind 127.0.0.1 >/dev/null 2>&1 &) && sleep 1
        google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=$win \
          --force-device-scale-factor=$dpr --virtual-time-budget=4000 \
          --screenshot=/out/$name.$size.png http://127.0.0.1:8799/a/sites/public/dgo-docs/he/$page/ >/dev/null 2>&1" \
      || echo "shot failed: $page $size"
  done
done
ls -la "$OUT" | awk 'NR>1 {print $5, $9}'
