#!/usr/bin/env bash
# shots.sh <dist dir> <out dir> — screenshots of the BUILT docs (the same bytes vps1's `sites` serves), at the
# blueprint's sizes (§6: desktop 1440x900, phone 390x844), Hebrew, light. It serves <dist dir> on 127.0.0.1 under the
# preview's own prefix (/a/sites/public/dgo-docs/), so every link and asset resolves exactly as through the console.
# Reads only; nothing leaves the Mac.
set -euo pipefail
DIST="$(cd "${1:?dist dir}" && pwd)"; OUT="${2:?out dir}"; mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
ROOT="$(mktemp -d)"; mkdir -p "$ROOT/a/sites/public"; ln -s "$DIST" "$ROOT/a/sites/public/dgo-docs"
PORT=8791
( cd "$ROOT" && exec python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 ) & SRV=$!
trap 'kill $SRV 2>/dev/null; rm -rf "$ROOT"' EXIT
sleep 1
CH="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell"
for page in he/ he/start/ he/start/install/linux/ he/idea/ en/; do
  name="$(echo "${page%/}" | tr '/' '-')"
  for size in 1440,900 390,844; do
    kind=$([ "$size" = 1440,900 ] && echo desktop || echo phone)
    "$CH" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size="$size" \
      --virtual-time-budget=4000 --screenshot="$OUT/${name}.${kind}.png" "http://127.0.0.1:$PORT/a/sites/public/dgo-docs/$page" \
      >/dev/null 2>&1 || echo "shot failed: $page $kind"
  done
done
ls -1 "$OUT"
