#!/bin/bash
# DGO cloud — a node's first boot (DGO-1893). Hostinger stores this text as a post-install script and runs it once as
# /post_install (its output: /post_install.log). It carries ONE secret, a boot token spent on first use, and fetches
# the real installer from the front, so the installer is fixed in one place for every server bought after the fix.
set -u
FRONT="@@FRONT@@"
NAME="@@NAME@@"
BOOT="@@BOOT@@"
fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsS -m 60 "$1" -o "$2"
  else python3 -c 'import sys,urllib.request; open(sys.argv[2],"wb").write(urllib.request.urlopen(sys.argv[1],timeout=60).read())' "$1" "$2"
  fi
}
for i in $(seq 1 60); do
  fetch "${FRONT}/node/install.sh" /root/dgo-cloud-install.sh && break
  echo "the front did not answer (try ${i}/60) - again in 10 s"; sleep 10
done
exec bash /root/dgo-cloud-install.sh "${FRONT}" "${NAME}" "${BOOT}"
