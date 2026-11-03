#!/bin/bash
# Upload the restored2 files next to the originals on FPG (owner 1000:1000) and verify checksums.
# usage (Git Bash on this PC): upload_restored.sh LOCAL_DIR SESSION_UUID NAME   (NAME = fpg103-restored2_2026-10-26-13-10-48)
set -e
LOCAL=$1; SESS=$2; NAME=$3
DEST=/var/lib/docker/volumes/fireplace_meet_recordings/_data/recordings/$SESS
for ext in ogg mp4; do
  f="$LOCAL/$NAME.$ext"
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
  local_sum=$(sha256sum "$f" | cut -d' ' -f1)
  scp -q -o BatchMode=yes "$f" "fpg-vps:$DEST/$NAME.$ext.part"
  remote_sum=$(ssh -o BatchMode=yes fpg-vps "sha256sum '$DEST/$NAME.$ext.part' | cut -d' ' -f1")
  if [ "$local_sum" != "$remote_sum" ]; then echo "CHECKSUM MISMATCH $NAME.$ext"; ssh fpg-vps "rm -f '$DEST/$NAME.$ext.part'"; exit 1; fi
  ssh -o BatchMode=yes fpg-vps "chown 1000:1000 '$DEST/$NAME.$ext.part' && mv '$DEST/$NAME.$ext.part' '$DEST/$NAME.$ext'"
  echo "uploaded $NAME.$ext sha256 $local_sum"
done
ssh -o BatchMode=yes fpg-vps "ls -ln $DEST | grep restored2"
