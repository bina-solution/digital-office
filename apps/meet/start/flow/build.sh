#!/bin/sh
# «פגישות» — the page asks for TWO files (the office's edge speaks HTTP/1.1: six connections per host, and every
# extra file waits for one). mf.css and mf.js are these sources, concatenated in order; edit the sources, then run this.
cd "$(dirname "$0")"
cat bina-ui.css bina-page.css meet.css > mf.css
for f in bina-icons.js bina-ask.js core.js stage.js transcript.js work.js upload.js screens.js meeting.js home.js; do cat "$f"; printf '\n;\n'; done > mf.js
echo "mf.css $(wc -c < mf.css) bytes, mf.js $(wc -c < mf.js) bytes"
