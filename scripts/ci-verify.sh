#!/usr/bin/env bash
# ci-verify.sh — assert the declaratively-configured stack came up correctly from a
# clean bring-up, with LAYERED, NAMED observability:
#   health-<app>            — the app is up / serving (basic liveness)
#   integration-<app>[-facet] — its declarative config actually took (configured as declared)
#
# Run AFTER `docker compose up -d` (CI) or against a running local stack:
#   ./scripts/ci-verify.sh
#
# Outputs (for CI surfacing; harmless locally):
#   $CI_JUNIT   (default ci-artifacts/ci-results.junit.xml) — per-check JUnit testcases
#   $CI_SUMMARY (default ci-artifacts/ci-summary.md)        — markdown scorecard
# Exit 0 = all checks passed; non-zero = number of failed checks (CI gate).
set -uo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Sourced for npath() — the ONE host-path conversion, not a second copy of it. The local
# definitions below deliberately follow and win, so this script's behaviour is unchanged.
. "${SCRIPT_DIR}/lib.sh"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
read_env() { grep -E "^$1=" "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }
DN="$(read_env DEPLOYMENT_NAME)"; DN="${DN:-bina-deployment}"
cn() { docker ps -a --format '{{.Names}}' | grep -E "^$1(-${DN})?$" | head -1; }

CI_JUNIT="${CI_JUNIT:-${REPO_ROOT}/ci-artifacts/ci-results.junit.xml}"
CI_SUMMARY="${CI_SUMMARY:-${REPO_ROOT}/ci-artifacts/ci-summary.md}"
mkdir -p "$(dirname "$CI_JUNIT")" "$(dirname "$CI_SUMMARY")" 2>/dev/null || true
RESULTS="$(mktemp)"   # lines: app|check-name|pass|message

FAILS=0
gh()    { [ -n "${GITHUB_ACTIONS:-}" ] && echo "::group::$1" || echo "==== $1 ===="; }
ghend() { [ -n "${GITHUB_ACTIONS:-}" ] && echo "::endgroup::" || true; }
# record APP CHECK-NAME STATUS MESSAGE
record() {
  printf '%s|%s|%s|%s\n' "$1" "$2" "$3" "$4" >> "$RESULTS"
  if [ "$3" = pass ]; then echo "  PASS  $2 — $4"
  else echo "  FAIL  $2 — $4"; FAILS=$((FAILS+1)); [ -n "${GITHUB_ACTIONS:-}" ] && echo "::error title=$2::$4"; fi
}
ok() { record "$1" "$2" pass "$3"; }   # app check msg
ko() { record "$1" "$2" fail "$3"; }   # app check msg
# assert: app check timeout msg  <command...>  — pass if command succeeds within timeout
assert() { local app="$1" name="$2" to="$3" msg="$4"; shift 4
  local start now; start=$(date +%s)
  while :; do "$@" && { ok "$app" "$name" "$msg"; return 0; }; now=$(date +%s); [ $((now-start)) -ge "$to" ] && { ko "$app" "$name" "$msg (timed out ${to}s)"; return 1; }; sleep 5; done
}
healthy_state() { docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || echo missing; }
is_up()   { case "$(healthy_state "$1")" in healthy|running) return 0;; *) return 1;; esac; }
pg()      { docker exec -e PGPASSWORD="$2" -i "$1" psql -U "$3" -d "$4" -tAc "$5" 2>/dev/null | tr -d '[:space:]'; }

echo "### ci-verify — DEPLOYMENT_NAME=${DN}"

# ── authentik ───────────────────────────────────────────────────────────────
gh "authentik"
AK_SRV="$(cn authentik-server)"; AK_PG="$(cn authentik-postgres)"; AK_PGPW="$(read_env AUTHENTIK_POSTGRES_PASSWORD)"
if [ -n "$AK_SRV" ] && assert authentik health-authentik 600 "authentik-server healthy" is_up "$AK_SRV"; then
  ak_ok()  { [ "$(pg "$AK_PG" "$AK_PGPW" authentik authentik "SELECT count(*) FROM authentik_core_user WHERE username='akadmin' AND password NOT LIKE '!%';")" = "1" ]; }
  prov_ok(){ [ "$(pg "$AK_PG" "$AK_PGPW" authentik authentik "SELECT count(*) FROM authentik_providers_proxy_proxyprovider;")" -ge 7 ] 2>/dev/null; }
  assert authentik integration-authentik-akadmin   300 "akadmin created with a usable password (worker bootstrap)" ak_ok
  assert authentik integration-authentik-providers 300 "SSO proxy providers applied from deployment-apps.yaml" prov_ok
else [ -z "$AK_SRV" ] && ko authentik health-authentik "authentik-server container not found"; fi
ghend

# ── n8n (blueprint push + verify) ────────────────────────────────────────────
gh "n8n"
N8N="$(cn n8n)"; N8N_PG="$(cn n8n-postgres)"
N8N_U="$(read_env POSTGRES_USER)"; N8N_DB="$(read_env POSTGRES_DB)"; N8N_PW="$(read_env POSTGRES_PASSWORD)"
if [ -n "$N8N" ] && assert n8n health-n8n 600 "n8n healthy" is_up "$N8N"; then
  push_ok=0
  for attempt in 1 2; do
    if "${REPO_ROOT}/bbox" n8n push all >/tmp/ci-n8n-push.log 2>&1; then push_ok=1; break; fi
    echo "  n8n-push attempt $attempt failed; n8n log:"; docker logs --tail 40 "$N8N" 2>&1 | tail -40; sleep 15
  done
  # The expected set is what the COMPILER says will be pushed, not every blueprint file on disk.
  # Globbing apps/*/blueprint/n8n counted workflows belonging to DISABLED apps —
  # google-workspace-agent is a gallery app the operator has not installed, and its 4 workflows are
  # deliberately absent from n8n. That made this check fail with "workflows 80 < 84" for a system
  # behaving exactly as designed. `reconcile.py blueprints` is the same source of truth the push
  # hook stages from, so the check and the push can no longer disagree.
  BP_DIRS=$(cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py blueprints 2>/dev/null | tr -d '' | cut -f2)
  # blueprints are CODE (*.workflow.ts) with legacy *.json still honoured mid-migration
  WF_WANT=$(cd "${REPO_ROOT}" && { for d in ${BP_DIRS}; do ls "${d}"/*.workflow.ts "${d}"/*.json 2>/dev/null; done; } | sed 's/\.workflow\.ts$//; s/\.json$//' | sort -u | wc -l | tr -d ' ')
  CRED_WANT=$(ls "${REPO_ROOT}/apps/n8n/credentials"/*.json 2>/dev/null | wc -l | tr -d ' ')
  WF=$(pg "$N8N_PG" "$N8N_PW" "$N8N_U" "$N8N_DB" "SELECT count(*) FROM workflow_entity;")
  CRED=$(pg "$N8N_PG" "$N8N_PW" "$N8N_U" "$N8N_DB" "SELECT count(*) FROM credentials_entity;")
  COL_ACT=$(pg "$N8N_PG" "$N8N_PW" "$N8N_U" "$N8N_DB" "SELECT count(*) FROM workflow_entity WHERE active;")
  # PUBLISH state — the real activation gate. n8n 2.x only registers triggers for
  # PUBLISHED workflows (activeVersionId non-null). A bare active=true leaves a DRAFT
  # that the DB+UI show as "active" but n8n never runs. So gate on published==declared
  # (no silent drafts), see issues/n8n-active-state-publish.yaml.
  PUB_ACT=$(pg "$N8N_PG" "$N8N_PW" "$N8N_U" "$N8N_DB" "SELECT count(*) FROM workflow_entity WHERE active AND \"activeVersionId\" IS NOT NULL;")
  # Same source as WF_WANT: the installed apps' blueprint dirs, so an uninstalled app's active
  # workflows are not expected to be running.
  ACT_WANT=$(cd "${REPO_ROOT}" && { for d in ${BP_DIRS}; do
      grep -l '"active": true' "${d}"/*.json 2>/dev/null
      grep -l 'active: true' "${d}"/*.workflow.ts 2>/dev/null
    done; } | wc -l | tr -d ' ')
  # Also confirm n8n's RUNTIME actually registered trigger-listeners (independent of
  # the DB): /rest/active-workflows. It lists STANDALONE listeners only, so it is <=
  # published (executeWorkflowTrigger sub-workflows, errorTrigger, mcpTrigger are
  # published+active but invoked indirectly). Route via traefik Host header (the
  # runner doesn't resolve *.localhost). Empty/auth-fail => -1 (UNVERIFIED, not 0).
  N8N_OE="$(read_env N8N_OWNER_EMAIL)"; N8N_OP="$(read_env N8N_OWNER_PASSWORD)"
  # Self-verifying: log the login result + raw endpoint response so a runtime=0 can
  # be told apart from "couldn't query" (login/endpoint failure must NOT masquerade
  # as 0 active). Try both login field shapes across n8n versions.
  # n8n-push RESTARTED n8n at its end; wait until its REST API is serving again
  # before querying, else /rest/login 404s on the still-booting SPA (false UNVERIFIED).
  for i in $(seq 1 30); do
    rc=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: n8n.localhost" "http://127.0.0.1/rest/settings" 2>/dev/null)
    [ "$rc" = 200 ] && { echo "    n8n REST ready (/rest/settings 200)"; break; }
    echo "    waiting for n8n REST post-restart (got ${rc})..."; sleep 5
  done
  # npath, because curl is a NATIVE binary and this script sets MSYS_NO_PATHCONV=1: on Git-Bash
  # curl.exe took "/tmp/n8n-ci.cookies" literally and wrote it under the Windows drive root, while
  # the shell's grep read the MSYS /tmp — a different file. The auth cookie was always issued and
  # never found, so login=0 and this check could not pass on Windows, ever.
  CK="$(npath /tmp)/n8n-ci.cookies"; LOGIN_OUT="$(npath /tmp)/n8n-login.out"; rm -f "$CK"; LOGIN_OK=0
  # Use the correct login field shape FIRST and stop as soon as a cookie is captured — n8n's
  # /rest/login is rate-limited (express-rate-limit), so extra attempts only push toward HTTP 429.
  # The X-Forwarded-For/trust-proxy prerequisite is handled by N8N_PROXY_HOPS in the compose (without
  # it express-rate-limit throws and silently withholds the auth cookie on an otherwise-200 response).
  # [2026-08-23] READ THE COOKIE FROM THE HEADER, NOT FROM A JAR. n8n issues
  #     Set-Cookie: n8n-auth=<JWT>; Max-Age=604800; Path=/; HttpOnly; Secure; SameSite=Lax
  # and this probe talks PLAIN HTTP (http://127.0.0.1 with a Host: override, because that is the
  # only address traefik answers on here). curl correctly refuses to persist a `Secure` cookie
  # received over an insecure connection, so `-c "$CK"` produced an EMPTY jar on every run and
  # the check read that as a failed login. Measured: http=200 with Set-Cookie present, jar empty.
  # --resolve does not help — the scheme is what disqualifies the cookie, not the host.
  # So the JWT is taken straight off the response header and replayed as a request header. Same
  # credential, same session, no dependence on curl's cookie store or on the URL scheme.
  for B in "{\"emailOrLdapLoginId\":\"${N8N_OE}\",\"password\":\"${N8N_OP}\"}" "{\"email\":\"${N8N_OE}\",\"password\":\"${N8N_OP}\"}"; do
    hdr="$(npath /tmp)/n8n-login.hdr"; rm -f "$hdr"
    code=$(curl -s -o "$LOGIN_OUT" -D "$hdr" -w '%{http_code}' -X POST "http://127.0.0.1/rest/login" -H "Host: n8n.localhost" -H 'Content-Type: application/json' --data "$B" 2>/dev/null || echo 000)
    N8N_COOKIE="$(grep -ai '^set-cookie:' "$hdr" 2>/dev/null | sed -n 's/.*\(n8n-auth=[^;]*\).*/\1/p' | head -1)"
    echo "    n8n /rest/login http=${code} cookie=$([ -n "${N8N_COOKIE}" ] && echo yes || echo no)"
    [ -n "${N8N_COOKIE}" ] && { LOGIN_OK=1; break; }
  done
  AW_RAW=$(curl -s -H "Cookie: ${N8N_COOKIE}" -H "Host: n8n.localhost" "http://127.0.0.1/rest/active-workflows" 2>/dev/null)
  echo "    /rest/active-workflows -> ${AW_RAW:0:200}"
  FUNC_ACT=$(printf '%s' "$AW_RAW" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin); d=d.get('data',d) if isinstance(d,dict) else d
  print(len(d) if isinstance(d,list) else -1)
except Exception: print(-1)" 2>/dev/null || echo -1)
  echo "  n8n active: login=${LOGIN_OK} runtime-listeners=${FUNC_ACT} published=${PUB_ACT} active-col=${COL_ACT} blueprint-declared=${ACT_WANT}"
  echo "  --- n8n activation log (tail) ---"; docker logs "$N8N" 2>&1 | grep -iE "dependency index|draft|published|could not activate|fail" | tail -8 || true
  echo "  ---------------------------------"
  [ "$push_ok" = 1 ] && ok n8n integration-n8n-push "blueprint restored via bbox n8n push all" || ko n8n integration-n8n-push "n8n-push failed (after retries)"
  { [ "${WF:-0}" -ge "$WF_WANT" ] 2>/dev/null && ok n8n integration-n8n-workflows "workflows imported ${WF}/${WF_WANT}"; }     || ko n8n integration-n8n-workflows "workflows ${WF:-0} < ${WF_WANT}"
  # PASS iff every blueprint-active workflow is PUBLISHED (no silent drafts) AND n8n's
  # runtime registered standalone listeners (>0). Fails on a regression to the
  # active=true-only "false-active" bug. UNVERIFIED if the runtime couldn't be queried.
  if [ "$LOGIN_OK" != 1 ] || [ "${FUNC_ACT:-(-1)}" -lt 0 ] 2>/dev/null; then
    ko n8n integration-n8n-active-state "could NOT query n8n runtime (login=${LOGIN_OK}, resp unparseable) — active state UNVERIFIED"
  elif [ "${PUB_ACT:-0}" -ge "$ACT_WANT" ] && [ "${FUNC_ACT:-0}" -gt 0 ] && [ "$ACT_WANT" -gt 0 ] 2>/dev/null; then
    ok n8n integration-n8n-active-state "all ${PUB_ACT}/${ACT_WANT} blueprint-active workflows PUBLISHED; runtime registered ${FUNC_ACT} trigger-listeners"
  else
    ko n8n integration-n8n-active-state "publish gap: published ${PUB_ACT}/${ACT_WANT}, runtime-listeners ${FUNC_ACT} (drafts not published? active-col ${COL_ACT}; see issues/n8n-active-state-publish.yaml)"
  fi
  { [ "${CRED:-0}" -ge "$CRED_WANT" ] 2>/dev/null && ok n8n integration-n8n-creds "credentials imported ${CRED}/${CRED_WANT}"; } || ko n8n integration-n8n-creds "creds ${CRED:-0} < ${CRED_WANT}"
  # integration-n8n-active-workflow-webhook: the END-TO-END functional proof — poke a
  # REAL active, SECURED webhook ([CI] Active-state webhook probe, ciHelloWebhook01).
  # Proves (a) >=1 workflow is genuinely active (trigger registered + serving) and
  # (b) the webhook works. Auth = the env-managed CICD basic-auth cred (re-seeded from
  # $N8N_WEBHOOK_USER/PASS via blueprint credential_overrides, so it decrypts under any
  # key). Retry briefly (the webhook registers on n8n's post-push restart).
  WH_USER="$(read_env N8N_WEBHOOK_USER)"; WH_PASS="$(read_env N8N_WEBHOOK_PASS)"
  WH_OK=0; WH_BODY=""
  for i in $(seq 1 12); do
    WH_BODY=$(curl -s -m 10 -u "${WH_USER}:${WH_PASS}" -H "Host: n8n.localhost" "http://127.0.0.1/webhook/ci-hello" 2>/dev/null)
    printf '%s' "$WH_BODY" | grep -q "hello-from-n8n-ci" && { WH_OK=1; break; }
    sleep 5
  done
  # confirm it is actually SECURED: an unauthenticated poke must be rejected (not 'hello').
  WH_NOAUTH=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Host: n8n.localhost" "http://127.0.0.1/webhook/ci-hello" 2>/dev/null)
  if [ "$WH_OK" = 1 ] && [ "$WH_NOAUTH" != 200 ]; then
    ok n8n integration-n8n-active-workflow-webhook "GET /webhook/ci-hello (CICD basic-auth) -> hello-from-n8n-ci; no-auth rejected (HTTP ${WH_NOAUTH}) — a real active, secured workflow responded"
  else
    ko n8n integration-n8n-active-workflow-webhook "webhook probe failed (authed body='${WH_BODY:0:40}', no-auth HTTP ${WH_NOAUTH}) — no active/secured webhook responding"
  fi
else [ -z "$N8N" ] && ko n8n health-n8n "n8n container not found"; fi
ghend

# ── glitchtip (declarative: org + projects + out-of-the-box error ingest) ─────
gh "glitchtip"
GT="$(cn glitchtip)"
if [ -n "$GT" ] && assert glitchtip health-glitchtip 600 "/_health green (DB + migrations + redis)" \
     sh -c "docker exec '$GT' python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/_health/')\" >/dev/null 2>&1"; then
  # Declarative config from platform-base/glitchtip/blueprint.yml (org + project per app +
  # deterministic DSNs written to .env). Idempotent.
  "${REPO_ROOT}/platform-base/glitchtip/hooks/push" >/tmp/ci-gt-push.log 2>&1 || { echo "  glitchtip-push log:"; tail -8 /tmp/ci-gt-push.log; }
  # Expected project count comes from the COMPILED list (each app declares its own
  # observability{}), not from glitchtip's blueprint — a base app must not name its consumers.
  PROJ_WANT=$(grep -cE '^[[:space:]]*-[[:space:]]*\{[[:space:]]*name:' "${REPO_ROOT}/.generated/glitchtip.projects.yml" 2>/dev/null); PROJ_WANT="${PROJ_WANT:-13}"
  GT_ORG=$(docker exec "$GT" python manage.py shell -c "from apps.teams.models import Organization;print('OCOUNT',Organization.objects.count())" 2>/dev/null | grep -oE 'OCOUNT [0-9]+' | grep -oE '[0-9]+$')
  GT_PROJ=$(docker exec "$GT" python manage.py shell -c "from apps.projects.models import Project;print('PCOUNT',Project.objects.count())" 2>/dev/null | grep -oE 'PCOUNT [0-9]+' | grep -oE '[0-9]+$')
  { [ "${GT_ORG:-0}" -ge 1 ] && [ "${GT_PROJ:-0}" -ge "$PROJ_WANT" ] 2>/dev/null \
      && ok glitchtip integration-glitchtip-projects "org + ${GT_PROJ}/${PROJ_WANT} app projects configured (declarative blueprint)"; } \
      || ko glitchtip integration-glitchtip-projects "not configured: orgs=${GT_ORG:-0} projects=${GT_PROJ:-0}/${PROJ_WANT}"
  # Ingest roundtrip: a project's DSN accepts an event => apps can route errors out of the box.
  KEYINFO=$(docker exec "$GT" python manage.py shell -c "from apps.projects.models import ProjectKey;k=ProjectKey.objects.order_by('project_id').first();print('KEY',str(k.public_key).replace('-',''),k.project_id) if k else print('KEY none 0')" 2>/dev/null | grep -oE 'KEY [0-9a-f]+ [0-9]+')
  GT_PUB=$(echo "$KEYINFO" | awk '{print $2}'); GT_PID=$(echo "$KEYINFO" | awk '{print $3}')
  GT_EID=$(python3 -c "import uuid;print(uuid.uuid4().hex)" 2>/dev/null)
  if [ -n "$GT_PUB" ] && [ -n "$GT_PID" ]; then
    GT_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 12 -X POST "http://127.0.0.1/api/${GT_PID}/store/" \
      -H "Host: glitchtip.localhost" -H "X-Sentry-Auth: Sentry sentry_key=${GT_PUB}, sentry_version=7" \
      -H "Content-Type: application/json" -d "{\"event_id\":\"${GT_EID}\",\"message\":\"ci-verify ingest probe\",\"level\":\"error\",\"platform\":\"other\"}" 2>/dev/null)
    { [ "$GT_CODE" = 200 ] && ok glitchtip integration-glitchtip-ingest "DSN ingest accepted (HTTP 200, project ${GT_PID}) — apps route errors out of the box"; } \
      || ko glitchtip integration-glitchtip-ingest "ingest HTTP ${GT_CODE} (project ${GT_PID})"
  else
    ko glitchtip integration-glitchtip-ingest "no project DSN key found"
  fi
elif [ -z "$GT" ]; then ko glitchtip health-glitchtip "glitchtip container not found"; fi
ghend

# ── browser42 (live-view VNC core) ───────────────────────────────────────────
gh "browser42"
B42="$(cn browser42-browser)"
if [ -n "$B42" ] && assert browser42 health-browser42 300 "browser42-browser up" is_up "$B42"; then
  assert browser42 integration-browser42-cdp 300 "CDP (:9222) responding" \
    sh -c "docker exec '$B42' python3 -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=4)\" >/dev/null 2>&1"
  assert browser42 integration-browser42-vnc 180 "noVNC/websockify (:6080) serving" \
    sh -c "docker exec '$B42' python3 -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:6080/',timeout=4)\" >/dev/null 2>&1"
elif [ -z "$B42" ]; then echo "  (browser42 not deployed — skipping)"; fi
ghend

# ── redis ────────────────────────────────────────────────────────────────────
gh "redis"
RC="$(cn redis)"; RPW="$(read_env REDIS_PASSWORD)"
if [ -n "$RC" ]; then assert redis health-redis 120 "PONG" sh -c "docker exec '$RC' redis-cli -a '$RPW' ping 2>/dev/null | grep -q PONG"
else ko redis health-redis "redis container not found"; fi
ghend

# ── every other service: basic liveness ──────────────────────────────────────
gh "other services"
for svc in traefik redisinsight portainer machine any-concurrency n8n-task-runners authentik-worker n8n-worker-1; do
  c="$(cn "$svc")"
  if [ -z "$c" ]; then echo "  (skip: $svc not deployed)"; continue; fi
  assert "$svc" "health-$svc" 420 "$svc up" is_up "$c"
done
ghend

# ── emit JUnit + markdown summary ────────────────────────────────────────────
xesc() { sed -e 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'; }
TOTAL=$(wc -l < "$RESULTS" | tr -d ' ')
{
  echo "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
  echo "<testsuites><testsuite name=\"ci-verify\" tests=\"${TOTAL}\" failures=\"${FAILS}\">"
  while IFS='|' read -r app name status msg; do
    em=$(printf '%s' "$msg" | xesc)
    if [ "$status" = pass ]; then echo "  <testcase classname=\"${app}\" name=\"${name}\"/>"
    else echo "  <testcase classname=\"${app}\" name=\"${name}\"><failure message=\"${em}\"/></testcase>"; fi
  done < "$RESULTS"
  echo "</testsuite></testsuites>"
} > "$CI_JUNIT"
{
  echo "## Deployment verification — $([ "$FAILS" -eq 0 ] && echo '✅ all passed' || echo "❌ ${FAILS} failed") (${TOTAL} checks)"
  echo
  echo "| Check | Result | Detail |"
  echo "|---|---|---|"
  while IFS='|' read -r app name status msg; do
    echo "| \`${name}\` | $([ "$status" = pass ] && echo ✅ || echo ❌) | ${msg} |"
  done < "$RESULTS"
} > "$CI_SUMMARY"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && cat "$CI_SUMMARY" >> "$GITHUB_STEP_SUMMARY" || true

echo
if [ "$FAILS" -eq 0 ]; then echo "### ci-verify: ALL CHECKS PASSED (${TOTAL})"; else echo "### ci-verify: ${FAILS}/${TOTAL} CHECK(S) FAILED"; fi
echo "  JUnit:   $CI_JUNIT"; echo "  Summary: $CI_SUMMARY"
exit "$FAILS"
