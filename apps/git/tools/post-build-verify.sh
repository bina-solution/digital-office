#!/usr/bin/env bash
#: post-build-verify — ONE command that puts the screen in the container and proves it renders.
#
# Written while the engine was frozen for rebuilds (2026-09-29): the backend was already live and
# verified, the screen was on disk, and the only thing left was a single deliberate build followed by
# a browser capture. Splitting that into the exact steps a person would type by hand makes it one
# command, and makes what it proves unambiguous.
#
# WHAT IT DOES, in order:
#   1. `./scripts/dc up -d --build git`   — the ONLY build this app needs (static files are COPYed)
#   2. waits for the container to report healthy (it has a real /healthz)
#   3. asserts the RUNNING page is the TWO-SCREEN app (accounts + mirrors) and that the served script
#      carries no repository display at all — the direction DGO-57 landed, checked where it is real
#   4. answers the read paths: /api/repos, /api/repo, listDir — the abstraction this app still is, even
#      though its own UI no longer calls them
#   5. captures the app through the console's own path in a real Chromium (the ui-capture image) and
#      prints the verdict: title, node count, the rendered account/mirror text, and every JS error.
#      The capture tool is VERSIONED: apps/git/tools/panel-shot.py (tools/ mounted read-only at /tools),
#      because an acceptance step that reads its script out of gitignored data/ cannot be reproduced.
#
# Exits non-zero on the first failure, and prints what failed. Dev tooling: `tools/` is not copied
# into the image and is never served.
#
#   bash apps/git/tools/post-build-verify.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"
. "${REPO_ROOT}/scripts/lib.sh"   # say, colors, running, dcx, read_env, npath

GIT_URL="${GIT_URL:-http://git:8978}"
fail() { say "${cr}[verify] FAILED: $*${c0}"; exit 1; }

# ── 1. the one build ─────────────────────────────────────────────────────────────────────────────
say "[verify] building and starting the version-control service…"
./scripts/dc up -d --build git || fail "the build/start failed"

# ── 2. healthy, not merely started ───────────────────────────────────────────────────────────────
for _ in $(seq 1 30); do
  if curl -fsS -m 5 "${GIT_URL}/healthz" >/dev/null 2>&1; then break; fi
  sleep 4
done
curl -fsS -m 5 "${GIT_URL}/healthz" >/dev/null 2>&1 || fail "the service is not answering /healthz"
say "[verify] service healthy"

# ── 3. the RUNNING page is the new screen ────────────────────────────────────────────────────────
page="$(curl -fsS -m 10 "${GIT_URL}/" || true)"
case "${page}" in
  *'id="nav-accounts"'*'id="nav-mirrors"'*) say "[verify] the served page is the two-screen app" ;;
  *) fail "the served page is not the accounts/mirrors app — the image was not rebuilt" ;;
esac
case "${page}" in
  *'id="side"'*) fail "the served page still has a side MENU of its own — the shell owns navigation" ;;
esac
script="$(curl -fsS -m 10 "${GIT_URL}/static/app.js" || true)"
case "${script}" in
  *viewRepo*|*repoRow*|*mdToHtml*) fail "the served script still contains repository display (DGO-57)" ;;
esac
say "[verify] the served script has no repository display (the forge is the display)"
node "${SCRIPT_DIR}/ui-selfcheck.mjs" >/dev/null || fail "the offline UI self-check failed"

# ── 4. the read paths the screen depends on ──────────────────────────────────────────────────────
fa="$(curl -s -m 20 "${GIT_URL}/connections" | python3 -c 'import json,sys
d=json.load(sys.stdin)
i=next((x for x in d.get("connections",[]) if x.get("provider")=="forgejo"), None)
print(i["id"] if i else "")')"
[ -n "${fa}" ] || fail "no local forge account is connected (run: ./bbox app git prepare)"
say "[verify] local forge account: ${fa}"

repos="$(curl -s -m 60 "${GIT_URL}/api/repos?limit=100")"
echo "${repos}" | python3 -c '
import json,sys
d=json.load(sys.stdin)
n=len(d.get("repos") or []); acc=len(d.get("accounts") or []); err=d.get("errors") or []
print(f"[verify] /api/repos — {n} repositories across {acc} account(s), {len(err)} account error(s)")
for e in err: print("        !", e.get("label") or e.get("account"), e.get("error"))
sys.exit(0 if n else 1)' || fail "/api/repos returned no repositories"

repo_full="$(echo "${repos}" | python3 -c 'import json,sys
d=json.load(sys.stdin); print((d.get("repos") or [{}])[0].get("full_name") or "")')"
curl -s -m 60 "${GIT_URL}/api/repo?account=${fa}&repo=office/deployment-hacohen" | python3 -c '
import json,sys
d=json.load(sys.stdin); s=d.get("sections") or {}
assert d.get("ok"), d.get("error")
print("[verify] /api/repo — branches %d, commits %d, tree %d, readme %s" % (
  len((s.get("branches") or {}).get("branches") or []),
  len((s.get("commits") or {}).get("commits") or []),
  len((s.get("tree") or {}).get("entries") or []),
  (s.get("readme") or {}).get("path")))' || fail "/api/repo did not answer"

curl -s -m 30 -X POST "${GIT_URL}/listDir" -H 'content-type: application/json' \
  -d "{\"account\":\"${fa}\",\"repo\":\"office/deployment-hacohen\",\"path\":\"scripts\"}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok"), d.get("error");
print("[verify] listDir — %d entries" % len((d.get("data") or {}).get("entries") or []))' \
  || fail "listDir did not answer"

# ── 4b. the app's OWN proof, live, against the providers (read-only: it creates nothing) ─────────
say "[verify] running the app's read-only self-test inside the container…"
docker exec "git-local" python3 /app/selftest.py --read-only 2>&1 | tail -12 \
  || fail "the in-container self-test failed (see its output above)"
bash "${SCRIPT_DIR}/repoindex-selfcheck.py" >/dev/null || fail "the fan-out self-check failed"

# ── 5. a real browser, twice: the screen and the forge ───────────────────────────────────────────
cip="$(docker inspect traefik-local --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)"
[ -n "${cip}" ] || fail "could not resolve the edge's address"
ak="$(read_env AUTHENTIK_BOOTSTRAP_PASSWORD)"
say "[verify] capturing the screen and the forge in Chromium…"
docker run --rm --network traefik-network \
  -v "$(npath "${REPO_ROOT}/data/ui-map"):/data" -v "$(npath "${SCRIPT_DIR}"):/tools:ro" \
  -e PANEL_OUT=/data \
  -e UI_HOST_RESOLVER="MAP console.localhost ${cip}, MAP forge.console.localhost ${cip}, MAP *.localhost ${cip}" \
  -e UI_OWN_BROWSER=1 -e UI_CHROME_BIN=/usr/bin/chromium \
  -e AK_USER=akadmin -e AK_PASS="${ak}" \
  -e PANEL_URL="http://console:8000/a/git-accounts/" \
  -e PANEL_FORGE="http://forge.console.localhost/" \
  ${PANEL_SHOTS:+-e PANEL_SHOTS="${PANEL_SHOTS}"} \
  ui-capture:latest python3 -u /tools/panel-shot.py > /tmp/git-verify-capture.json 2>&1 \
  || fail "the capture did not run (see /tmp/git-verify-capture.json)"
python3 - <<'PY' || fail "what the console rendered is not this app: no rows, or a JS error"
import json
raw = open('/tmp/git-verify-capture.json', encoding='utf-8').read()
d = json.loads(raw[raw.index('{'):])
p = d.get('panel') or {}
a = p.get('app') if isinstance(p.get('app'), dict) else {}
a = a or {}
print("[verify] panel   :", p.get('title'), "| nodes", p.get('nodes'))
print("[verify] who     :", a.get('who'))
print("[verify] accounts:", a.get('rows'), "row(s) | menu row marked current:", a.get('nav_active'),
      "| menu rows:", a.get('nav_rows'))
print("[verify] acting as :", a.get('who'))
print("[verify] screen  :", (a.get('main') or '')[:70].replace('\n', ' '))
print("[verify] forge   :", (d.get('forge') or {}).get('title'))
print("[verify] JS errors:", d.get('page_errors') or 'none')
# The app must be the thing the console shows, with its rows and its own tab marked: a title alone
# would also be true of an error page that happens to render.
ok = ((p.get('nodes') or 0) > 60 and (a.get('rows') or 0) >= 1
      and a.get('nav_active') == 'accounts' and not d.get('page_errors'))
print("[verify] screenshots: data/ui-map/panel-shot.png, data/ui-map/forge-shot.png" + (
      ", data/ui-map/shots/*.png" if d.get('screens') else ""))
raise SystemExit(0 if ok else 1)
PY

say "${cg}[verify] OK — the screen is live, the read paths answer, and the browser rendered it cleanly.${c0}"
