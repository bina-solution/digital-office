#!/bin/bash
# Post the v2 comments on MEET-22 and MEET-23 from inside project-pln-examplef (key via plan.api_key(), never printed).
# usage: pl_post.sh HTML_22 HTML_23      (run from Git Bash on this PC)
set -e
H22=$1; H23=$2
scp -q -o BatchMode=yes "$H22" exf-vps:/tmp/c22.html
scp -q -o BatchMode=yes "$H23" exf-vps:/tmp/c23.html
ssh -o BatchMode=yes exf-vps '
  set -e
  docker cp /opt/digital-office/examplef/apps/project-pln/plan.py project-pln-examplef:/tmp/plan.py
  docker cp /opt/digital-office/examplef/apps/meet/tools/restore/pl_comment.py project-pln-examplef:/tmp/pl_comment.py
  docker cp /tmp/c22.html project-pln-examplef:/tmp/c22.html
  docker cp /tmp/c23.html project-pln-examplef:/tmp/c23.html
  docker exec project-pln-examplef python3 /tmp/pl_comment.py 222bafc1-049b-469f-9b2c-06e723ae7bec /tmp/c22.html
  docker exec project-pln-examplef python3 /tmp/pl_comment.py 2f16e565-9865-43e5-bf19-585955ba53d5 /tmp/c23.html
  rm -f /tmp/c22.html /tmp/c23.html
'
