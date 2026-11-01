#!/usr/bin/env bash
# baseline.sh — prove a HEALTHY BASELINE for the whole platform in ONE fresh command.
#
#   ./bbox baseline                    # full fresh proof (reset -> build --pull -> up -> verify)
#
# A "healthy baseline" (the operator's definition) is five things, all green:
#   1. one command, always a FRESH hard-reset build run (down -v -> build --pull -> up)
#   2. all tests green — scripts/ci-verify.sh (infra battery) AND `bbox indox test all` (functional)
#   3. any-concurrency (כל מקביל) full log review — all green
#   4. notification service (התראות) working — no special errors
#      (3 and 4 are now asserted by those apps' OWN hooks/verify — see P6. This script names no app.)
#   5. full ui-map verified — the one big montage image captured + coverage reported
#
# It runs byte-for-byte the same locally and (optionally) in CI, reusing the exact machinery the
# individual lanes already use — this script only ORCHESTRATES + SCORES, it invents no new mechanism:
#   your own .env · bbox reset/run · scripts/ci-verify.sh · bbox indox test ·
#   bbox ui-map · the services' own /healthz endpoints.
#
# Result scorecard -> ci-artifacts/baseline-summary.md ; exit 0 only if ALL applicable criteria pass.
#
# Env knobs (all optional):
#   (baseline NEVER touches .env — it uses yours as-is, so creds are stable across runs)
#   BASELINE_SKIP_BUILD=1   skip the fresh `docker compose build --pull` (use present images)
#   BASELINE_SKIP_RESET=1   skip the destructive `bbox reset` (bring up on top of current state)
#   BASELINE_NO_INDOX=1     skip the functional INDOX suites (criterion 2b)
#   BASELINE_NO_UIMAP=1     skip the ui-map capture (criterion 5)
#   BASELINE_WITH_BROWSER42=1   keep browser42 in the stack (needs a big-disk host; default drops it)
#   BASELINE_SERVICES="…"   override the bring-up service set (default: whole graph minus browser42)
set -uo pipefail
LOG_TAG=baseline
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SELF_DIR}/lib.sh"                        # REPO_ROOT, read_env, DN, cn, colors, ok/warn/bad/log, running
cd "${REPO_ROOT}"

ART="${REPO_ROOT}/ci-artifacts"; mkdir -p "${ART}"
SUMMARY="${ART}/baseline-summary.md"
RESULTS="$(mktemp)"                            # lines: criterion|status|detail
FAILS=0
crit() { # crit "name" pass|fail|warn "detail"
  # Flatten the detail to ONE line for the scorecard. A multi-line detail (P6 folds in a 4-line
  # log tail, and some details carry a literal \n) otherwise splits into extra markdown table rows
  # that render with an empty result cell — which read as spurious ❌ next to an already-GREEN run.
  # The console output ($3) keeps its newlines; only the RESULTS row is flattened.
  local d; d="$(printf '%s' "$3" | tr '\n\t' '  ' | sed 's/\\n/ ¶ /g; s/  */ /g')"
  printf '%s|%s|%s\n' "$1" "$2" "$d" >> "${RESULTS}"
  case "$2" in pass) ok "$1 — $3";; warn) warn "$1 — $3";; *) bad "$1 — $3"; FAILS=$((FAILS+1));; esac
}
hr() { echo; echo "${c1}==== $* ====${c0}"; }

need_docker() { docker info >/dev/null 2>&1 || die "docker daemon not reachable"; }
die() { echo "${cr}[baseline] error:${c0} $*" >&2; exit 2; }

# ── P0 preflight ─────────────────────────────────────────────────────────────
hr "P0  preflight (env + network + volumes)"
need_docker
# Traefik v3.3 compiles its docker client against API 1.24. If the daemon's floor is above that,
# the provider never loads: traefik starts, reports healthy, and every single *.localhost host
# 404s. This is a FAILURE, not a warning — a baseline run on such a daemon produces a hundred
# unrelated-looking test failures and wastes an hour before anyone reads the traefik log.
#
# ASK THE DAEMON, don't infer from its version number.
#
# This check used to read Server.MinAPIVersion and fail anything above 1.3x, on the reasoning
# that Docker 29 raises the hard floor to 1.40 and therefore refuses traefik's 1.24 client. That
# inference does not hold: measured 2026-08-21 on Docker 29.1.3, traefik v3.3 discovered its
# routers normally and routing worked end-to-end (auth.localhost 302, glitchtip.localhost 200,
# an unknown host 404). A version gate cannot see that, and it refused to run baseline at all on
# a daemon that works — while masking the two faults that WERE breaking routing on that host (a
# socket bind-mount that had become a directory, and ufw dropping container egress).
# See issues/docker29-traefik-warning-does-not-reproduce.yaml.
#
# So probe the actual capability: can a v1.24 client list containers on this endpoint? That is
# precisely what traefik's docker provider does, it is one request, and it stays true whatever
# Docker renumbers next.
api124_ok() {
  case "${DOCKER_HOST:-}" in
    unix://*) curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
                --unix-socket "${DOCKER_HOST#unix://}" 'http://localhost/v1.24/containers/json' ;;
    tcp://*)  curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
                "http://${DOCKER_HOST#tcp://}/v1.24/containers/json" ;;
    *)        echo 000 ;;
  esac
}
API124="$(api124_ok 2>/dev/null || echo 000)"
case "${API124}" in
  200) : ;;
  000) crit "P0 docker-api-floor" fail "could not probe the docker API at \$DOCKER_HOST=${DOCKER_HOST:-<unset>} — traefik's provider talks to this same endpoint, so if the probe cannot reach it, traefik will not either." ;;
  *)   crit "P0 docker-api-floor" fail "the daemon refused an API v1.24 request (HTTP ${API124}). traefik v3.3 compiles its docker client against 1.24, so it will discover ZERO routers and every *.localhost will 404 while traefik reports healthy. Run an engine that still serves 1.24." ;;
esac

# Container egress. A container that cannot resolve a name is a host-readiness fact checkable in
# one second, and not checking it is expensive: on portable-ubuntu (ufw enabled,
# DEFAULT_FORWARD_POLICY=DROP) every image build died on "Temporary failure in name resolution"
# — 55 times in one run — which reads as a flaky network rather than a firewall. ICMP passed
# throughout, because ufw's before-rules accept echo in FORWARD, so even a ping test would have
# said everything was fine. See issues/ufw-forward-drop-blocks-container-egress.yaml.
# [2026-08-23] This FAILED the run; it now reports what is true and lets the run continue.
# The default bridge having no egress does not stop a build -- bbox builds first-party images
# over the HOST network when it detects this (see ccr_build_serial / ccr_proxy_build_flags), and
# nothing the platform RUNS is on docker0 anyway: every service sits on traefik-network, which
# reaches TCP/443 and DNS normally. Measured on portable-ubuntu: docker0 pings 1.1.1.1 but cannot
# open TCP/443 or UDP/53, while the same probe on traefik-network succeeds on both -- and a full
# `bbox run` then completed 40 of 42 services with 0 DNS failures.
# Failing here was wrong twice: it red-flagged a host that builds correctly, and it hid the P0
# checks after it behind a stop that had nothing to do with them.
if ! docker run --rm --quiet alpine:latest nslookup deb.debian.org >/dev/null 2>&1; then
  crit "P0 container-egress" warn "the default bridge cannot resolve DNS — first-party images will be built over the host network (bbox handles this); services run on traefik-network and are unaffected"
else
  crit "P0 container-egress" pass "containers resolve DNS on the default bridge"
fi
# Values that must AGREE with a committed artifact, not merely be set. Checked here because the
# failures they cause are invisible at startup and surface an hour later as a dozen unrelated red
# checks — which is exactly how the rotated n8n encryption key was found.
if ecout="$(python3 "$(npath "${SELF_DIR}")/env-consistency-check.py" 2>&1)"; then
  crit "P0 env-consistency" pass "n8n key matches the blueprint; supabase JWTs match their secret"
else
  crit "P0 env-consistency" fail "$(printf '%s' "${ecout}" | sed -n '3,12p')"
fi
docker network inspect traefik-network >/dev/null 2>&1 || { log "creating traefik-network"; docker network create traefik-network >/dev/null; }
docker volume  inspect wa_media        >/dev/null 2>&1 || { log "creating volume wa_media";  docker volume create wa_media >/dev/null; }
# baseline uses YOUR .env exactly as a manual `bbox run` does — it never generates, rewrites or
# edits one. Credentials therefore stay identical across every run unless you deliberately change
# them. (Random per-run secrets are minted ONLY by scripts/ci-env.sh, which the CI lanes call
# themselves; baseline does not.)
[ -f .env ] || die "no .env — copy .env.ex to .env and set your credentials, then re-run"
log "using existing .env ($(grep -c = .env) keys) — baseline does not modify it"
# n8n-postgres asks for nofile hard=262144; a sandbox with a lower hard limit refuses it ("error
# setting rlimit type 7: operation not permitted") and the container never starts. Cap PG_NOFILE_*
# to the host's hard limit so it boots anywhere. No-op on a normal host (its limit is already higher).
HARDLIM="$(ulimit -Hn 2>/dev/null || echo 262144)"
if [ "${HARDLIM}" != unlimited ] && [ "${HARDLIM}" -lt 262144 ] 2>/dev/null; then
  for kv in "PG_NOFILE_SOFT=${HARDLIM}" "PG_NOFILE_HARD=${HARDLIM}"; do
    k="${kv%%=*}"; grep -q "^${k}=" .env && sed -i "s#^${k}=.*#${kv}#" .env || echo "${kv}" >> .env
  done
  log "capped PG_NOFILE_* to host hard nofile limit (${HARDLIM})"
fi
# Drop browser42 unless explicitly asked to keep it (its patched-Chromium image is huge and pulls
# from a non-docker.io base — excluded to fit a ~30GB host). This zeroes the compose profile.
if [ "${BASELINE_WITH_BROWSER42:-0}" != 1 ]; then
  grep -q '^COMPOSE_PROFILES=' .env && sed -i 's#^COMPOSE_PROFILES=.*#COMPOSE_PROFILES=#' .env || echo 'COMPOSE_PROFILES=' >> .env
  log "browser42 dropped (COMPOSE_PROFILES=)"
fi
dcx config -q 2>/tmp/baseline-cfg.err || { cat /tmp/baseline-cfg.err; die "compose config invalid"; }
crit "P0 preflight" pass "network+volume ready; .env=$(grep -c = .env) keys; compose config valid"

# ── P0b architecture + hardening gates ───────────────────────────────────────
# The baseline calls itself the full-system proof, and it ran NONE of the invariant gates — so
# "baseline green" and "the architecture holds" were unrelated claims, and the only lane that
# checked the invariants was CI. They belong here, FIRST: every one is static and cheap, and a
# layering or engine-bypass violation explains a later runtime failure rather than the reverse.
# The list itself lives in scripts/ci/gates.sh so this lane, fresh-machine-check and CI cannot
# disagree about what the gates are.
hr "P0b architecture + hardening gates"
if gout="$(bash "${SELF_DIR}/ci/gates.sh" 2>&1)"; then
  printf '%s\n' "${gout}" | sed 's/^/  /'
  crit "P0b gates" pass "$(printf '%s' "${gout}" | tail -1)"
else
  printf '%s\n' "${gout}" | sed 's/^/  /'
  crit "P0b gates" fail "$(printf '%s' "${gout}" | tail -1) — invariants broken; fix before trusting anything below"
fi

# The bring-up set: the whole default graph minus browser42 (compose pulls in depends_on automatically).
BASELINE_SERVICES="${BASELINE_SERVICES:-$(dcx config --services 2>/dev/null | grep -viE 'browser42' | tr '\n' ' ')}"

# ── P1 fresh reset (hard) ────────────────────────────────────────────────────
hr "P1  fresh reset (down -v)"
if [ "${BASELINE_SKIP_RESET:-0}" = 1 ]; then crit "P1 reset" warn "skipped (BASELINE_SKIP_RESET=1)"
else "${REPO_ROOT}/bbox" reset --force --remove-orphans || true; crit "P1 reset" pass "docker compose down -v (fresh-machine state)"; fi

# A TLS-terminating egress proxy (Claude Code web / cloud sandbox) MITMs HTTPS, so pip/npm inside a
# docker build fail cert-verify. The fixes — CA-shadowing every base image so `FROM` inherits trust,
# capping the postgres nofile ulimit, and building serially to dodge the concurrent-npm OOM — now
# live in scripts/lib.sh (ccr_*), shared with `bbox run` and `bbox ui-map`. Every one is a no-op on a
# normal host, so the non-proxy path below is byte-for-byte unchanged. BASELINE_PROXY_CA stays as an
# override alias for the shared PROXY_CA.
BASELINE_PROXY_CA="${BASELINE_PROXY_CA:-${PROXY_CA}}"; PROXY_CA="${BASELINE_PROXY_CA}"
ccr_clamp_nofile

# ── P2 fresh build + disk hygiene ────────────────────────────────────────────
if ccr_have_proxy_ca; then hr "P2  fresh build (CA-shadowed bases, MITM proxy detected)"; else hr "P2  fresh build --pull"; fi
if [ "${BASELINE_SKIP_BUILD:-0}" = 1 ]; then crit "P2 build" warn "skipped (BASELINE_SKIP_BUILD=1)"
# [2026-08-23] Two reasons to build serially over the HOST network, not one. The original was a
# proxied sandbox. The second is a host whose DEFAULT BRIDGE has no egress: `dcx build` in the
# else-branch below uses docker0 and dies on `Ign http://deb.debian.org` and a failed npm
# install, which is exactly how P2 failed here. bbox run already takes this path; baseline had
# its own build and did not, so the two disagreed about whether this machine can build.
# ccr_shadow_bases stays proxy-only — there is no CA to inject when there is no proxy.
elif ccr_have_proxy_ca || bbox_container_dns_broken; then
  ccr_have_proxy_ca && ccr_shadow_bases                  # inject the proxy CA into base images…
  if ccr_build_serial; then                              # …then build first-party images serially
    docker builder prune -f >/dev/null 2>&1 || true
    crit "P2 build" pass "all first-party images rebuilt from source (CA-shadowed, serial)"
  else
    crit "P2 build" fail "a serial first-party build failed (see above; check disk with 'docker system df')"
  fi
else
  # n8n + its 2 workers share ONE Dockerfile; building all three in parallel runs three heavy
  # `npm install --include=dev` at once and OOM-crashes npm ("Exit handler never called") on a small
  # host. Build the n8n image ONCE first (serially) so the workers are pure cache hits.
  dcx build n8n >/dev/null 2>&1 || warn "serial n8n pre-build reported an issue (main build will surface it)"
  if dcx build --pull; then
    docker builder prune -f >/dev/null 2>&1 || true      # reclaim intermediate layers before bring-up
    crit "P2 build" pass "all first-party images rebuilt from source"
  else
    crit "P2 build" fail "docker compose build failed (see log; check disk with 'docker system df')"
  fi
fi
# P3's `bbox run` re-checks CA-shadow + serial build; the images are fresh now, so tell it to skip.
export CCR_BASES_READY=1
log "disk after build:"; df -h / | tail -1; docker system df 2>/dev/null | sed 's/^/  /'

# ── P3 bring-up ──────────────────────────────────────────────────────────────
# `bbox run` runs every enabled app's own hooks/prepare AND hooks/onboard on the way in (schema,
# n8n blueprints, first-run seeding) — so whatever an app has to provision for itself happens
# without this lane naming it, and by construction before P5/P6 ever run. Logged to a file (not
# just the terminal) so the onboard-hook check below can grep it the same way P4 greps ci-verify's.
hr "P3  bring up the stack (--wait)"
BBOX_WAIT_TIMEOUT="${BBOX_WAIT_TIMEOUT:-600}" "${REPO_ROOT}/bbox" run --wait ${BASELINE_SERVICES} 2>&1 | tee /tmp/baseline-run.log || true
onboard_fail="$(sed 's/\x1b\[[0-9;]*m//g' /tmp/baseline-run.log \
              | grep -oE '[A-Za-z0-9_.-]+: onboard hook FAILED' | sed 's/: onboard hook FAILED$//' \
              | sort -u | tr '\n' ' ')"
if [ -z "${onboard_fail}" ]; then crit "P3 app-onboarding" pass "every enabled app's onboard hook succeeded (schema + first-run seeding)"
else crit "P3 app-onboarding" fail "onboard hook(s) failed: ${onboard_fail}— see bring-up log above"
fi
# health census
total=$(docker ps -a --format '{{.Names}}' | grep -c -- "-${DN}$" || true)
upc=$(docker ps --format '{{.Status}}' | grep -c 'Up' || true)
downlist="$(docker ps -a --format '{{.Names}}\t{{.Status}}' | grep -- "-${DN}" | grep -viE 'Up |Exited \(0\)' || true)"
if [ -z "${downlist}" ]; then crit "P3 bring-up" pass "${upc}/${total} containers Up; no unhealthy/crashed"
else crit "P3 bring-up" fail "${upc}/${total} Up — problems:\n$(echo "${downlist}" | sed 's/^/      /')"; fi
# Does every probe in the LIVE stack use a binary its container actually has? G18 answers this
# statically for images we build; only a running stack can answer it for vendor images. The bug it
# catches is silent by construction — a container stuck unhealthy while the app serves fine — so
# the census above would report the symptom without ever naming the cause.
if hcout="$(bash "${SELF_DIR}/healthcheck-audit.sh" 2>&1)"; then
  crit "P3 healthcheck-probes" pass "$(printf '%s' "${hcout}" | grep -c '^OK') probe(s) use a binary their image has"
else
  crit "P3 healthcheck-probes" fail "probe binary missing:
$(printf '%s' "${hcout}" | grep '^MISSING' | sed 's/^/      /')"
fi
# Is a container the same container whoever asks compose for it — and is every CPU quota the
# budget's? A stack brought up by ONE caller always looks whole; it is the next install from the
# apps screen, or the agent's own `./bbox run`, that re-creates half of it (the edge, the databases,
# the sign-in — measured 2026-10-06). The check is read-only and asks the engine itself.
if idout="$(bash "${SELF_DIR}/config-by-caller.sh" 2>&1)"; then
  crit "P3 one-identity" pass "every caller of compose compiles the same containers; a second bring-up re-creates none; every CPU quota is the budget's"
else
  crit "P3 one-identity" fail "a container's configuration depends on who asks for it:
$(printf '%s\n' "${idout}" | grep -E '^[0-9]\. ' | sed 's/^/      /')"
fi
# The gates only a RUNNING stack can answer (run-gates.py's LIVE_SET): every host .env declares for
# sign-in has a router, an active workflow runs the body you can read, every object an enabled
# app's schema declares exists, the rendered dock fits its pill, no container runs on an older .env.
# The census above cannot say any of it — the first is every container healthy and a bare 404 at
# the first login. They had no caller: `--live` was typed by hand or not at all, and where it was
# typed two of the five were looking at nothing. One line here, so a gate added to that list is
# scored the day it is added.
if lgout="$(python3 "$(npath "${REPO_ROOT}")/scripts/refactor/run-gates.py" --live 2>&1)"; then
  crit "P3 live-gates" pass "$(printf '%s\n' "${lgout}" | grep -m1 'gate(s) run')"
else
  crit "P3 live-gates" fail "$(printf '%s\n' "${lgout}" | grep -m1 'gate(s) run')
$(printf '%s\n' "${lgout}" | grep -E '^FAIL|^          \| |UNWIRED|DUPLICATE' | cut -c1-190 | head -24 | sed 's/^/      /')"
fi
# (the GlitchTip poller-token assertion that used to live here is now
#  platform-base/glitchtip/hooks/verify — scored in P6 with every other app's own verify hook.)

# ── P4 infra tests (ci-verify) ───────────────────────────────────────────────
hr "P4  infra battery — scripts/ci-verify.sh"
CI_SUMMARY="${ART}/ci-summary.md" CI_JUNIT="${ART}/ci-results.junit.xml" bash "${SELF_DIR}/ci-verify.sh" >/tmp/baseline-civerify.log 2>&1
cv=$?
civ_pass=$(grep -c '  PASS ' /tmp/baseline-civerify.log || true); civ_fail=$(grep -c '  FAIL ' /tmp/baseline-civerify.log || true)
if [ "$cv" = 0 ]; then crit "P4 ci-verify" pass "all ${civ_pass} applicable checks green (browser42 N/A)"
else
  # browser42 is intentionally absent → its 3 checks fail; treat ONLY those as expected.
  nonb42=$(grep '  FAIL ' /tmp/baseline-civerify.log | grep -vi browser42 | wc -l | tr -d ' ')
  if [ "${nonb42}" = 0 ] && [ "${BASELINE_WITH_BROWSER42:-0}" != 1 ]; then
    crit "P4 ci-verify" pass "${civ_pass} green; only browser42's ${civ_fail} checks N/A (excluded by design)"
  else
    crit "P4 ci-verify" fail "${civ_fail} failed (${nonb42} non-browser42) — see /tmp/baseline-civerify.log"
    grep '  FAIL ' /tmp/baseline-civerify.log | grep -vi browser42 | sed 's/^/      /'
  fi
fi

# ── P5 functional tests (INDOX E2E) ──────────────────────────────────────────
hr "P5  functional suites — bbox indox test all"
if [ "${BASELINE_NO_INDOX:-0}" = 1 ]; then crit "P5 indox" warn "skipped (BASELINE_NO_INDOX=1)"
else
  if "${REPO_ROOT}/bbox" indox test all --junit "${ART}/baseline-indox.junit.xml" >/tmp/baseline-indox.log 2>&1; then
    crit "P5 indox" pass "all suites green ($(grep -c 'ALL TESTS PASS' /tmp/baseline-indox.log) suite(s))"
  else
    red="$(grep -E 'NO SUMMARY|❌' /tmp/baseline-indox.log | grep -oE '^\[indox-test\] [a-z_]+' | awk '{print $2}' | sort -u | tr '\n' ' ')"
    crit "P5 indox" fail "red suite(s): ${red:-see log} — /tmp/baseline-indox.log"
  fi
fi

# ── P5c full extraction proof — 527/527 corpus gate ──────────────────────────
hr "P5c  extraction gate — whole Hebrew corpus → 527/527 exact values"
if [ "${BASELINE_NO_EXTRACT:-0}" = 1 ]; then crit "P5c extract-gate" warn "skipped (BASELINE_NO_EXTRACT=1)"
else
  # OMP_THREAD_LIMIT=1 for the baseline's gate run. The baseline is a CONTENDED run by definition —
  # the full 49-container stack shares the host CPU with the gate's cold apitools — and concurrent
  # in-process libtesseract calls deadlock their OpenMP threads under that contention (5 OCR slots
  # sat "busy" with no OCR ever completing; docs froze mid-corpus). Serialising each OCR's internal
  # threading removes the deadlock; doc-level concurrency still uses the cores. The standalone CI
  # gate on a dedicated, uncontended runner leaves this unset and keeps full OpenMP speed.
  if OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}" "${REPO_ROOT}/bbox" indox extract-gate >/tmp/baseline-extract.log 2>&1; then
    crit "P5c extract-gate" pass "$(grep -oE 'values=[0-9]+/[0-9]+' /tmp/baseline-extract.log | tail -1) exact field values (100% accuracy)"
  else
    crit "P5c extract-gate" fail "$(grep -oE 'values=[0-9]+/[0-9]+' /tmp/baseline-extract.log | tail -1 || echo 'gate did not report'); see /tmp/baseline-extract.log"
  fi
fi

# ── P5d node coverage — how much of the estate the suites actually executed ───────
# Placed HERE, not in P0b, on purpose: every gate in P0b is static and answers from the tree
# alone. This one counts EXECUTIONS, so before P5 it would read zero — and a coverage number
# over zero inputs is not a low score, it is no score. That distinction is the whole reason this
# phase exists: scripts/n8n-node-coverage.py globbed *.json for weeks after blueprints became
# .workflow.ts, matched nothing, and the figure it once produced (279/624) was still being
# quoted as live long after nothing could reproduce it.
hr "P5d  node coverage — nodes the suites executed"
if [ "${BASELINE_NO_INDOX:-0}" = 1 ]; then crit "P5d node-coverage" warn "skipped (BASELINE_NO_INDOX=1)"
else
  covout="$(python3 "$(npath "${REPO_ROOT}")/scripts/refactor/node-coverage-gate.py" 2>&1)"; covrc=$?
  printf '%s\n' "${covout}" | sed 's/^/  /'
  if [ "${covrc}" = 0 ]; then
    crit "P5d node-coverage" pass "$(printf '%s' "${covout}" | head -1 | sed 's/^G65 PASS — //')"
  else
    crit "P5d node-coverage" fail "$(printf '%s' "${covout}" | head -1 | sed 's/^G65 FAIL — //')"
  fi
fi

# ── P6 per-app self-verification (run_app_hooks verify) ──────────────────────
# An app owns its own facts. This phase used to be TWO hard-coded phases — P6 knew any-concurrency's
# port, its /healthz shape and its log filter; P7 knew the same three things about notifications;
# P3 knew that glitchtip mints a token into .env. Three apps named inside layer 0, each with an
# assertion only the app itself can state honestly.
#
# Now each of those lives in <root>/<id>/hooks/verify and the platform runs them the same generic
# way it already runs `prepare` and `onboard`. baseline ORCHESTRATES and SCORES; it does not know
# which apps exist. Adding an app with a fact worth asserting needs no edit here.
#
# Placement is deliberate: after the infra battery, the functional suites and the extraction gate,
# because the two log reviews that moved here read the LAST 400 lines — the value of that review
# comes from the tests having already exercised the stack. Same position P6/P7 held.
hr "P6  app self-verification — every enabled app's own hooks/verify"
# run_app_hooks RETURNS the number of failed hooks and never stops early, so this reads an EXIT
# CODE rather than grepping stdout for a sentence. It used to do the latter — a string contract
# between two files that becomes a lie the moment someone rewords the message or a hook writes to
# stderr. `set -uo pipefail` (no -e) means a non-zero here does not abort the lane; baseline scores
# it, which is this script's entire job.
vout="$(run_app_hooks verify 2>&1)"; vrc=$?
printf '%s\n' "${vout}"
# Name them too: the count says how many, the ids say which, the hooks' own output above says why.
# Strip ANSI first — `say` colours the line and an escape sequence ends in `m`, which the id
# pattern would otherwise swallow.
vfail="$(printf '%s\n' "${vout}" | sed 's/\x1b\[[0-9;]*m//g' \
        | grep -oE '[A-Za-z0-9_.-]+: verify hook FAILED' | sed 's/: verify hook FAILED$//' \
        | sort -u | tr '\n' ' ')"
if [ "${vrc}" -eq 0 ]; then
  crit "P6 app-verify" pass "every enabled app's verify hook passed"
else
  crit "P6 app-verify" fail "${vrc} app verify hook(s) failed${vfail:+: ${vfail}}— each printed its reason above"
fi

# ── P8 ui-map ────────────────────────────────────────────────────────────────
hr "P8  ui-map — capture the whole platform + coverage"
if [ "${BASELINE_NO_UIMAP:-0}" = 1 ]; then crit "P8 ui-map" warn "skipped (BASELINE_NO_UIMAP=1)"
else
  if "${REPO_ROOT}/bbox" ui-map >/tmp/baseline-uimap.log 2>&1; then :; else warn "ui-map exited non-zero (partial capture still composed)"; fi
  BIG="${ART}/ui-map/ui-map.png"
  nshot="$(ls -1 "${ART}/screenshots-ui"/*.png 2>/dev/null | wc -l | tr -d ' ')"
  cov="$(grep -oE 'visible-region coverage[^|]*\| \*\*[0-9.]+%' "${ART}/ui-coverage.md" 2>/dev/null | grep -oE '[0-9.]+%' | head -1)"
  # npath: python.exe is native and cannot open an MSYS-form /c/Users/... path, so on Windows this
  # one-liner hit FileNotFoundError, printed '?', and P8 warned "? first-party view(s) failed" even
  # when zero actually failed. Convert the host path at the boundary.
  nfailed="$(python3 -c "import json,sys
try: r=json.load(open(r'$(npath "${REPO_ROOT}")/data/ui-map/ui-capture-results.json'))['results']
except Exception: print('?'); sys.exit()
print(sum(1 for x in r if x.get('status')=='failed' and x.get('tier')!='third_party'))" 2>/dev/null)"
  if [ -f "${BIG}" ] && [ "${nshot:-0}" -gt 0 ]; then
    if [ "${nfailed:-1}" = 0 ]; then crit "P8 ui-map" pass "big image + ${nshot} views; region-cov ${cov:-?}; 0 first-party failures"
    else crit "P8 ui-map" warn "big image + ${nshot} views; region-cov ${cov:-?}; ${nfailed} first-party view(s) failed — review"; fi
  else crit "P8 ui-map" fail "no big image produced — see /tmp/baseline-uimap.log"; fi
fi

# ── P9 scorecard ─────────────────────────────────────────────────────────────
hr "P9  healthy-baseline scorecard"
{
  echo "# Healthy-baseline scorecard — ${DN}"
  echo
  echo "| # | criterion | result | detail |"
  echo "|---|---|---|---|"
  i=0
  while IFS='|' read -r name st det; do
    i=$((i+1)); case "$st" in pass) e="✅";; warn) e="🟡";; *) e="❌";; esac
    echo "| ${i} | ${name} | ${e} | $(echo "${det}" | tr '\n' ' ' | sed 's/|/\\|/g') |"
  done < "${RESULTS}"
  echo
  echo "_Generated by scripts/baseline.sh. Artifacts: ci-artifacts/ci-summary.md, baseline-indox.junit.xml, ui-map/ui-map.png, ui-coverage.md._"
} > "${SUMMARY}"
cat "${SUMMARY}"
rm -f "${RESULTS}"
echo
if [ "${FAILS}" = 0 ]; then echo "${cg}${c1}HEALTHY BASELINE: GREEN${c0} — all criteria passed."; exit 0
else echo "${cr}${c1}HEALTHY BASELINE: ${FAILS} criterion(s) RED${c0} — see ${SUMMARY}."; exit 1; fi
