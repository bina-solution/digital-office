#!/bin/bash
# Post the v2 comments on MEET-22 and MEET-23 from inside project-pln-fireplace (key via plan.api_key(), never printed).
# usage: pl_post.sh HTML_22 HTML_23      (run from Git Bash on this PC)
set -e
H22=$1; H23=$2
scp -q -o BatchMode=yes "$H22" fpg-vps:/tmp/c22.html
scp -q -o BatchMode=yes "$H23" fpg-vps:/tmp/c23.html
ssh -o BatchMode=yes fpg-vps '
  set -e
  docker cp /opt/digital-office/fireplace/apps/project-pln/plan.py project-pln-fireplace:/tmp/plan.py
  docker cp /opt/digital-office/fireplace/apps/meet/tools/restore/pl_comment.py project-pln-fireplace:/tmp/pl_comment.py
  docker cp /tmp/c22.html project-pln-fireplace:/tmp/c22.html
  docker cp /tmp/c23.html project-pln-fireplace:/tmp/c23.html
  docker exec project-pln-fireplace python3 /tmp/pl_comment.py 222bafc1-049b-469f-9b2c-06e723ae7bec /tmp/c22.html
  docker exec project-pln-fireplace python3 /tmp/pl_comment.py 2f16e565-9865-43e5-bf19-585955ba53d5 /tmp/c23.html
  rm -f /tmp/c22.html /tmp/c23.html
'
