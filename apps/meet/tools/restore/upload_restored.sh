#!/bin/bash
# Upload the restored2 files next to the originals on EXF (owner 1000:1000) and verify checksums.
# usage (Git Bash on this PC): upload_restored.sh LOCAL_DIR SESSION_UUID NAME   (NAME = exf103-restored2_2026-10-26-13-10-48)
set -e
LOCAL=$1; SESS=$2; NAME=$3
# where the office's recordings ARE: the folder meet-start mounts at /recordings — data/meet/recordings since
# DGO-2019, the volume meet_recordings before — asked of the machine, as tools/move/host.py locate does. Never the old
# volume by name: a recording put there after the move is one nothing lists, files or keeps.
ROOT="$(ssh -o BatchMode=yes exf-vps 'c=$(docker ps -q --filter label=com.docker.compose.service=meet-start);
  [ "$(printf "%s\n" $c | grep -c .)" = 1 ] &&
  docker inspect -f "{{range .Mounts}}{{if eq .Destination \"/recordings\"}}{{.Source}}{{end}}{{end}}" "$c"')" || ROOT=""
[ -n "$ROOT" ] || { echo "not exactly one meet-start runs on exf-vps: where its recordings are is not known — nothing uploaded"; exit 1; }
DEST=$ROOT/recordings/$SESS
for ext in ogg mp4; do
  f="$LOCAL/$NAME.$ext"
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
  local_sum=$(sha256sum "$f" | cut -d' ' -f1)
  scp -q -o BatchMode=yes "$f" "exf-vps:$DEST/$NAME.$ext.part"
  remote_sum=$(ssh -o BatchMode=yes exf-vps "sha256sum '$DEST/$NAME.$ext.part' | cut -d' ' -f1")
  if [ "$local_sum" != "$remote_sum" ]; then echo "CHECKSUM MISMATCH $NAME.$ext"; ssh exf-vps "rm -f '$DEST/$NAME.$ext.part'"; exit 1; fi
  ssh -o BatchMode=yes exf-vps "chown 1000:1000 '$DEST/$NAME.$ext.part' && mv '$DEST/$NAME.$ext.part' '$DEST/$NAME.$ext'"
  echo "uploaded $NAME.$ext sha256 $local_sum"
done
ssh -o BatchMode=yes exf-vps "ls -ln $DEST | grep restored2"
