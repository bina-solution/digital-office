#!/usr/bin/env bash
# build-on-vps1.sh <archive of this folder> <DOCS_BASE> <out dir> — run ON vps1 (piped through `bbox computers ssh`):
# builds the docs in a throwaway node container under the host's heavy lock and puts dist/ into <out dir>, keeping the
# previous copy beside it. The Mac never builds (AGENTS.md: the Mac is the command centre).
# The outside call: `npm ci`/`npm install` reads registry.npmjs.org (named on DGO-1788).
set -euo pipefail
ARCHIVE="${1:?archive}"; BASE="${2:?DOCS_BASE}"; OUT="${3:?out dir}"
W=/var/tmp/dgo-docs-build
uptime
exec 9>/tmp/dgo-heavy.lock
flock -w 7200 9
rm -rf "$W" && mkdir -p "$W" && tar -xzf "$ARCHIVE" -C "$W"
docker rm -f probe-dgo1788 >/dev/null 2>&1 || true
timeout -k 30 1500 docker run --rm --init --name probe-dgo1788 --cpus 2 --memory 2g \
  -e DOCS_BASE="$BASE" -e ASTRO_TELEMETRY_DISABLED=1 -v "$W":/w -w /w node:24-bookworm-slim \
  sh -c 'if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi && npm run build' 2>&1 | tail -40
[ -f "$W/dist/he/index.html" ] || { echo "BUILD: no dist/he/index.html"; exit 3; }
mkdir -p "$OUT"
[ -d "$OUT/site" ] && rm -rf "$OUT/site.prev" && mv "$OUT/site" "$OUT/site.prev"
cp -a "$W/dist" "$OUT/site"
echo "BUILT: $(find "$OUT/site" -type f | wc -l) files, $(du -sh "$OUT/site" | cut -f1) in $OUT/site"
cp "$W/package-lock.json" "$OUT/package-lock.json" 2>/dev/null || true
