#!/bin/sh
# «פגישות» — the page asks for TWO files (the office's edge speaks HTTP/1.1: six connections per host, and every
# extra file waits for one). mf.css and mf.js are these sources, concatenated in order; edit the sources, then run this.
# `build.sh --check` writes nothing and fails when a bundle is not its sources (apps/meet/start/test_flow_client.mjs).
cd "$(dirname "$0")" || exit 1
CSS="bina-ui.css bina-page.css meet.css"
JS="bina-icons.js bina-ask.js core.js status.js sheet.js stage.js transcript.js work.js upload.js screens.js meeting.js home.js"
css() { for f in $CSS; do cat "$f"; done; }
js() { for f in $JS; do cat "$f"; printf '\n;\n'; done; }
if [ "$1" = "--check" ]; then
  bad=0
  css | cmp -s - mf.css || { echo "mf.css is not its sources ($CSS): run flow/build.sh"; bad=1; }
  js | cmp -s - mf.js || { echo "mf.js is not its sources ($JS): run flow/build.sh"; bad=1; }
  [ "$bad" = 0 ] && echo "mf.css and mf.js are their sources"
  exit "$bad"
fi
css > mf.css
js > mf.js
echo "mf.css $(wc -c < mf.css) bytes, mf.js $(wc -c < mf.js) bytes"
