#!/usr/bin/env bash
# pack.sh <out.tgz> — the archive build-on-vps1.sh builds from docs/: exactly what the build needs (an allow-list, not
# a list of exclusions — macOS tar matches an exclude against any part of a path, so `shots` also dropped
# public/shots/), plus the office's palette as it is in the checkout today (platform-base/bina-ui/theme-tokens.css →
# src/styles/, read by olive.css), so the docs never keep a second copy of a colour. Run from anywhere; writes only
# <out.tgz>. The scripts live here, not in docs/, because they name the office's servers (the release line, DGO-1788).
set -euo pipefail
OUT="${1:?out.tgz}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"; DOCS="$REPO/docs"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
(cd "$DOCS" && COPYFILE_DISABLE=1 tar -cf - package.json package-lock.json astro.config.mjs src public) | tar -xf - -C "$STAGE"
cp "$REPO/platform-base/bina-ui/theme-tokens.css" "$STAGE/src/styles/theme-tokens.css"
(cd "$STAGE" && COPYFILE_DISABLE=1 tar -czf "$OUT" .)
echo "packed $(tar tzf "$OUT" | grep -vc '/$') files into $OUT"
