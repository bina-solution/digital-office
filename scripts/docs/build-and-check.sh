#!/usr/bin/env bash
# build-and-check.sh <n> — one docs preview build, start to proof, from the Mac (DGO-1788):
#   pack (pack.sh) → upload to vps1 → build there (build-on-vps1.sh, under vps1's heavy lock) → the sites app syncs
#   its public cache → the built tree comes back to a scratch folder → every link and picture of every page is
#   checked against that tree, and the TODO-shot boxes are counted.
# The log is ci-artifacts/dgo-docs-build-<n>.out (not tracked); the check's verdict is the last line printed.
# Run it in the background: a build takes 3–6 minutes. VPS names vps1's entry in the office's computers app.
set -uo pipefail
N="${1:?build number}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$REPO"
VPS="${DGO_DOCS_VPS:-computer_ssh-b154fa0c}"
# DGO_DOCS_SSH: a plain ssh command to vps1 (`ssh -o BatchMode=yes <user>@<host>`), used instead of the office's
# computers app while this machine's engine cannot serve it (2026-11-11: the Mac's engine jammed by its own take).
remote() { if [ -n "${DGO_DOCS_SSH:-}" ]; then $DGO_DOCS_SSH "$1"; else ./bbox computers ssh "$VPS" "$1"; fi; }
mkdir -p ci-artifacts; LOG="ci-artifacts/dgo-docs-build-$N.out"
SRC="${TMPDIR:-/tmp}/dgo-docs-src.tgz"; DIST="${TMPDIR:-/tmp}/dgo-docs-dist"
BASE=/a/sites/public/dgo-docs

bash scripts/docs/pack.sh "$SRC" >/dev/null || { echo "pack failed"; exit 1; }
remote 'cat > /var/tmp/dgo-docs-src.tgz' < "$SRC"
remote "bash -s -- /var/tmp/dgo-docs-src.tgz $BASE /opt/bina-sites/dgo-docs" \
  < scripts/docs/build-on-vps1.sh > "$LOG" 2>&1
rc=$?; echo "exit $rc" >> "$LOG"
# A failed build leaves the previous site in place; checking that tree would report the OLD pages as «0 bad»
# (it did once, build 20: a YAML error in a page's front matter). Stop here and show why.
if [ "$rc" -ne 0 ]; then
  grep -v LIBARCHIVE "$LOG" | grep -i -E 'error|failed|refused' | head -5
  echo "BUILD FAILED (exit $rc) — the previous site is still served; log: $LOG"
  exit 1
fi
remote 'docker exec sites-staging python -c "
import urllib.request as u, json
r=u.urlopen(u.Request(\"http://localhost:8979/api/sites/dgo-docs/sync\", data=b\"{\\\"force\\\": true}\", headers={\"Content-Type\":\"application/json\"}, method=\"POST\"), timeout=110); d=json.loads(r.read()); print(\"sync\", d.get(\"ok\"), (d.get(\"result\") or {}).get(\"files\"))
"; tar -C /opt/bina-sites/dgo-docs/site -czf /var/tmp/dgo-docs-dist.tgz .' >> "$LOG" 2>&1
rm -rf "$DIST" && mkdir -p "$DIST"
remote 'cat /var/tmp/dgo-docs-dist.tgz; rm -f /var/tmp/dgo-docs-dist.tgz' 2>/dev/null | tar -xzf - -C "$DIST" 2>/dev/null
grep -E "BUILT|rror|exit|sync" "$LOG" | tail -3
python3 - "$DIST" "$BASE/" <<'EOF'
import os, re, sys
D, P = sys.argv[1], sys.argv[2]
bad = set(); n = pages = boxes = 0
for b, _, fs in os.walk(D):
    for f in fs:
        if not f.endswith(".html"):
            continue
        pages += 1
        t = open(os.path.join(b, f), encoding="utf-8").read()
        boxes += t.count('class="shot-todo"')
        for u in re.findall(r'(?:href|src)="(/[^"#?]*)', t):
            n += 1
            if not u.startswith(P):
                bad.add(("outside", u)); continue
            p = os.path.join(D, u[len(P):])
            if not (os.path.isfile(p) or os.path.isfile(os.path.join(p, "index.html"))):
                bad.add(("missing", u))
print(pages, "pages;", n, "links/images;", len(bad), "bad", sorted(bad)[:5], "; placeholder boxes:", boxes)
EOF
