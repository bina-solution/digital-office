#!/usr/bin/env bash
# run_capture.sh — build the ui-capture image and drive a sharded, containerized capture.
#
# THE capture mechanism, shared byte-for-byte between local dev and CI so nothing differs
# between "here" and "there". N single-purpose headless-Chromium containers run on the stack
# network in parallel; each captures a shard (capture.py --shard i/N) and reaches the console
# DIRECTLY by its container IP — NO Traefik hop (that path rendered console near-empty in CI)
# and NO browser42 (2-CPU-capped, shared long-running browser with a tab reaper). Each shard is
# its own container → its own Chromium, cgroup and /dev/shm-less profile, so parallelism scales
# with cores instead of thrashing one browser.
#
# Inputs (env):
#   UI_DATA               the /data dir (inventory, ui-env.json, ui-params.json, output/ui) [required]
#   UI_CONSOLE_CONTAINER  the console container name [required]
#   UI_MAP_APPS           space-separated app list (default: the first-party eight currently
#                         enabled — my-docs is excluded while disabled, see APPS= below)
#   UI_MAP_SHARDS         parallel shards (default 4; the 32-core runner takes 8+)
#   UI_CAPTURE_IMAGE      image tag to build/run (default ui-capture:latest)
#   UI_CAPTURE_BUILD_ARGS extra `docker build` args (e.g. pip trusted-host behind a proxy)
#   UI_SHARD_TIMEOUT      per-shard hard ceiling in seconds (default 900) — a hung shard can
#                         never stall the run; the map composes from whatever captured
#   AK_USER/AK_PASS/WA_USER/WA_PASS  passed through for the in-capture logins
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "${SCRIPT_DIR}/.." && pwd)/lib.sh"   # read_env, cn, colors — REPO_ROOT resolved here too
TIMEOUT_BIN="$(timeout_bin)"   # empty on a macOS without coreutils -> run uncapped rather than fail

# in-capture logins fall back to the repo .env so the caller (CI step) needs no secret passthrough
AK_USER="${AK_USER:-akadmin}"
AK_PASS="${AK_PASS:-$(read_env AUTHENTIK_BOOTSTRAP_PASSWORD)}"
WA_USER="${WA_USER:-$(read_env CHAT_AUTH_USER)}"
WA_PASS="${WA_PASS:-$(read_env CHAT_AUTH_PASS)}"

DATA="${UI_DATA:?set UI_DATA to the ui-map data dir}"
CONSOLE="${UI_CONSOLE_CONTAINER:?set UI_CONSOLE_CONTAINER to the console container name}"
# my-docs is deliberately NOT in this default list. It is disabled in platform.state.yaml
# (`my-docs: {state: disabled, by: user}`), so its container never starts and it has no
# console_embed entry (see scripts/ui-coverage/manifest.yaml's 2026-08-06 note) — it is captured
# on its own standalone host (my-docs.localhost) same as any third-party app would be. That
# standalone host hits a REAL problem specific to this capture mechanism: every shard resolves
# `*.localhost` to the CONSOLE container's IP (one line down — `MAP *.localhost ${CIP}`), because
# every OTHER first-party app in this default list is embedded and only ever reached through
# console's own hash router, so a wildcard rule was safe. A disabled app is the one case that
# breaks the assumption: my-docs.localhost:8000 silently serves the CONSOLE app instead of
# failing to connect, and the console happily renders real, hydrated, non-blank content for
# whatever path it's asked for — which passes capture.py's blank/auth-wall/error validator even
# though it never reached my-docs at all. Measured 2026-08-06: all 14 my-docs__*.png came back as
# byte-identical files (27531 bytes each) reported "captured" — a false positive, not a real
# capture. Exactly the hello-bina precedent below (removed from console_embed, and — the harder
# lesson this data point adds — ALSO belongs out of the default capture list while disabled, not
# just out of console_embed). Add it back here if my-docs is re-enabled.
# [2026-09-27] This list is now EVERY embedded module the console actually shows, not "the
# first-party eight". Measured that date: the rail carried 16 tiles and the map photographed 9 —
# bina, telegram-tv, git, sites, domains, computers, data-management and app-management were
# enabled, live and in the rail while the report read "all first-party views captured", because
# the denominator had never heard of them. The tiles themselves are no longer a list anybody
# keeps: inventory.py reads them from the manifests (console_embed) and leaves out the apps this
# office does not run, so a name here that the office lacks simply has no views to capture.
# [2026-10-07] archify added: in the rail since it shipped, in no map.
APPS="${UI_MAP_APPS-console connections incoming-documents mailview drive machine notifications any-concurrency sites domains telegram-tv git computers app-management data-management bina digital-assets social-list dgo-extend project-pln archify}"
SHARDS="${UI_MAP_SHARDS:-4}"
IMAGE="${UI_CAPTURE_IMAGE:-ui-capture:latest}"
SHARD_TIMEOUT="${UI_SHARD_TIMEOUT:-900}"

if [ "${UI_CAPTURE_SKIP_BUILD:-0}" = 1 ] && docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  echo "### ui-map — using prebuilt capture image (${IMAGE})"
else
  echo "### ui-map — build capture image (${IMAGE})"
  # Build context = the Dockerfile's own dir, NOT the repo root: the Dockerfile has no COPY, so it
  # needs nothing from the tree, and sending the whole repo (data/, .git/, node_modules) as context
  # every run wasted minutes. capture.py is bind-mounted at runtime, not baked in. Layers (apt+pip)
  # are content-addressed, so on the persistent runner the second run onward is a near-instant cache
  # hit. Bounded by `timeout`: a wedged apt/pip download must fail fast, never wedge the whole run
  # for the job's 60-min ceiling the way an un-timed build did.
  bargs=(${UI_CAPTURE_BUILD_ARGS:-})
  # MITM-proxy sandbox: `bbox run` CA-shadows python:3.12-slim so pip trusts the proxy CA; if this
  # capture is run standalone (base not shadowed), trust pypi directly so `pip install playwright`
  # still succeeds. Also share the host network + pass the proxy build-args so the image's apt-get
  # (chromium + fonts) reaches a strict egress proxy. Empty/absent on a normal host → same as before.
  if command -v ccr_have_proxy_ca >/dev/null 2>&1 && ccr_have_proxy_ca; then
    bargs+=(--build-arg "PIP_TRUSTED=--trusted-host=pypi.org --trusted-host=files.pythonhosted.org")
  fi
  # [2026-08-23] MOVED OUT of the proxy-CA branch. ccr_proxy_build_flags answers TWO questions,
  # and only one of them is about a proxy: it also emits `--network host` for a host whose DEFAULT
  # BRIDGE has no egress, where a build cannot reach deb.debian.org at all. Nesting the call inside
  # `if ccr_have_proxy_ca` meant that on a no-proxy/dead-bridge host the flag was never asked for,
  # and this build died after 481s of:
  #     Err:3 http://deb.debian.org/debian-security trixie-security InRelease
  #       Temporary failure resolving 'deb.debian.org'
  #     ::error::ui-capture image build failed or timed out (600s)
  # which is why `bbox ui-map` produced no capture results. The function is a no-op on a healthy
  # host (empty output, same command as before), so calling it unconditionally costs nothing.
  # Third site with this shape — ccr_build_serial and baseline.sh P2 had the same gate.
  if command -v ccr_proxy_build_flags >/dev/null 2>&1; then
    # shellcheck disable=SC2206 — flags (--network host + --build-arg …) are meant to word-split.
    bargs+=( $(ccr_proxy_build_flags) )
  fi
  ${TIMEOUT_BIN:+${TIMEOUT_BIN} --kill-after=30 --signal=KILL ${UI_BUILD_TIMEOUT:-600}} \
    docker build -f "$(npath "${SCRIPT_DIR}")/Dockerfile" -t "${IMAGE}" "${bargs[@]}" "$(npath "${SCRIPT_DIR}")" \
    || { echo "::error::ui-capture image build failed or timed out (${UI_BUILD_TIMEOUT:-600}s)"; exit 1; }
fi

# The console's serving network + its IP ON THAT network, read together so they can't disagree.
# We attach each shard to this network and point Chromium's host-resolver at this IP, so
# console.localhost:${CPORT} resolves straight to the console container — the direct path that
# renders, exactly like a local run. PREFER the traefik/app network: console may be attached to
# more than one, and picking the wrong one leaves the shards unable to reach it (every view then
# fails and retries — a silent multi-minute stall). Fall back to the first network otherwise.
NETS="$(docker inspect "${CONSOLE}" \
  --format '{{range $n,$v := .NetworkSettings.Networks}}{{$n}} {{$v.IPAddress}}{{"\n"}}{{end}}')"
read -r NET CIP < <(printf '%s\n' "$NETS" | awk 'NF==2 && $1 ~ /traefik/ {print; found=1; exit} END{}')
[ -n "${NET:-}" ] || read -r NET CIP < <(printf '%s\n' "$NETS" | awk 'NF==2{print; exit}')
if [ -z "${NET:-}" ] || [ -z "${CIP:-}" ]; then
  echo "::error::could not resolve console network/IP from ${CONSOLE}"; exit 1
fi
echo "### ui-map — capture: image=${IMAGE} net=${NET} console=${CIP}:${CPORT:-8000} shards=${SHARDS} apps=[${APPS}]"

# ── the edge's routing, for a capture that never visits the edge ────────────────────────────────
# A capture reaches the console by its container address, so it skips Traefik — and Traefik is where
# the office's ROOT paths live: `apps/bina-ds` declares `/api`, `/plugins` and `/assets` mounted at
# the CONSOLE host's root (its app.json `passthrough`, mount: root), because the agent's page is
# framed at the console's origin and addresses those paths there. Without them every client bundle
# import fails and the agent renders "Failed to load plugins": measured 2026-10-09, the `bina` view
# captured as `failed · embedded app near-empty (20 nodes)` in both profiles, which left the beauty
# score with no bina row at all. So the shards talk to a byte-for-byte proxy carrying the same two
# decisions Traefik's compiled rules carry — the authority picks the app, and for an app with root
# paths the prefix picks it back, longest first (the console's own `reserved_paths` beat the agent's
# `/api`). When that agent is not running there is no proxy and no rule: the old path is untouched.
EDGE_NAME="uicap-edge-$$"
EDGE_ROOTS=()
EDGE_IP=""
resolve_ip="${CIP}"
AGENT_ADDR="$(python3 -c "
import json,pathlib,sys
try:
    bases = json.loads(pathlib.Path('.generated/registry/console.app_bases.json').read_text(encoding='utf-8'))
    app = json.load(open('platform-base/console/app.json', encoding='utf-8'))
except OSError:
    sys.exit(0)
for alias in ('bina',):
    host = (((bases.get(alias) or {}).get('default') or '')).split('//', 1)[-1].split('/', 1)[0]
    if host:
        print(host)
        print(' '.join(p for p in (app.get('reserved_paths') or []) if p.startswith('/api')))
        break
" 2>/dev/null)"
AGENT_SVC="$(printf '%s\n' "${AGENT_ADDR}" | head -1)"
AGENT_HOST="${AGENT_SVC%%:*}"
AGENT_PORT="${AGENT_SVC##*:}"
RESERVED="$(printf '%s\n' "${AGENT_ADDR}" | tail -1)"
if [ -n "${AGENT_HOST}" ]; then
  AGENT_CID="$(docker ps -q --filter "label=com.docker.compose.service=${AGENT_HOST}" | head -1)"
  AGENT_IP=""
  [ -n "${AGENT_CID}" ] && AGENT_IP="$(docker inspect "${AGENT_CID}" \
      --format "{{(index .NetworkSettings.Networks \"${NET}\").IPAddress}}" 2>/dev/null || true)"
  if [ -n "${AGENT_IP}" ]; then
    for p in /api /plugins /assets; do
      EDGE_ROOTS+=(--root "console.localhost:${p}=${AGENT_IP}:${AGENT_PORT}")
    done
    for p in ${RESERVED}; do
      EDGE_ROOTS+=(--root "console.localhost:${p}=${CIP}:${CPORT:-8000}")
    done
    docker rm -f "${EDGE_NAME}" >/dev/null 2>&1 || true
    if docker run -d --rm --network "${NET}" --name "${EDGE_NAME}" \
         -v "$(npath "${SCRIPT_DIR}"):/edge" \
         --entrypoint python3 "${IMAGE}" /edge/capture-edge.py "${CPORT:-8000}" \
         --route "console.localhost=${CIP}:${CPORT:-8000}" "${EDGE_ROOTS[@]}" >/dev/null 2>&1; then
      for _ in 1 2 3 4 5 6 7 8; do                # the address is not there the instant it starts
        EDGE_IP="$(docker inspect "${EDGE_NAME}" \
          --format "{{(index .NetworkSettings.Networks \"${NET}\").IPAddress}}" 2>/dev/null || true)"
        [ -n "${EDGE_IP}" ] && break
        sleep 1
      done
    fi
    if [ -n "${EDGE_IP}" ]; then
      resolve_ip="${EDGE_IP}"
      trap 'docker rm -f "${EDGE_NAME}" >/dev/null 2>&1 || true' EXIT
      echo "### ui-map — capture edge ${EDGE_IP}:${CPORT:-8000}: console → ${CIP}, ${AGENT_HOST} → ${AGENT_IP} on ${EDGE_ROOTS[*]}"
    else
      echo "### ui-map — capture edge did not come up; the console is captured directly (bina will fail)"
    fi
  fi
fi


cp "${SCRIPT_DIR}/capture.py" "${DATA}/ui-capture.py"
# [2026-09-28] AND THE PROFILE NAME HAS TO REACH THE CONTAINER TOO. The copy below fixed half
# of this bug and hid the other half: capture.py's _load_profile() reads UI_MAP_PROFILE from the
# environment FIRST and only then falls back to the file's `default` — and the docker run above
# never passed it. Measured: `UI_MAP_PROFILE=mobile bbox ui-map` printed "view profile: mobile"
# on the host and "[ui-map] view profile: desktop (1440x900 @1x)" inside the shard, wrote every
# screenshot at 1440x900, and filed them under ci-artifacts/ui-map/mobile/. Every non-desktop
# artifact this pipeline has ever produced was a desktop shot in a mobile-named directory, and
# the CI matrix builds all three profiles that way — so "we test mobile" was never true.
# The dimension assertion after the shards is what makes this impossible to repeat silently.
#
# capture.py's _load_profile() reads /data/view-profiles.yaml — without this copy that open()
# always raised (nothing ever put the file there) and the container-side fallback is hardcoded to
# "desktop" regardless of what UI_MAP_PROFILE actually asked for. Silent, not a crash: a
# `--profile mobile` run captured every view at the desktop 1440x900 viewport instead of mobile's,
# with no error — the ui-map.sh host-side resolver still name a mobile ARTIFACTS dir, but every
# screenshot INSIDE it would be the desktop layout. Found 2026-08-06 alongside the my-docs fix.
cp "${SCRIPT_DIR}/view-profiles.yaml" "${DATA}/view-profiles.yaml"
rm -f "${DATA}"/ui-capture-results.*.json "${DATA}"/ui-raw-coverage.*.json 2>/dev/null

# PREFLIGHT: one throwaway container proves the two things a shard needs before we fan out 8 of
# them — that the /data bind mount actually carried the inventory into the container (a silent DinD
# mount miss would give every shard an empty /data), and that the console answers on its IP. Either
# failure aborts fast with a clear message instead of 8 shards each stalling to their 15-min timeout.
echo "### ui-map — preflight (mount + console reachability)"
if ! docker run --rm --network "${NET}" -v "$(npath "${DATA}"):/data" "${IMAGE}" python3 -c "
import os, sys, socket
if not os.path.exists('/data/ui-inventory.json'):
    sys.exit('FATAL: /data/ui-inventory.json missing in container — the ${DATA}:/data bind mount did not carry through (DinD host-path not visible to the daemon)')
try:
    s = socket.create_connection(('${CIP}', ${CPORT:-8000}), timeout=10); s.close()
except Exception as e:
    sys.exit('FATAL: console ${CIP}:${CPORT:-8000} unreachable from a container on ${NET}: %s' % e)
print('preflight OK: /data mounted + console reachable')
"; then
  echo "::error::ui-map capture preflight failed — see FATAL above (not launching shards)"; exit 1
fi

# ── the shards, and a promise that they die ─────────────────────────────────────────────────
# `timeout --signal=KILL docker run` kills the CLIENT and leaves the CONTAINER running as an orphan.
# Measured 2026-09-30: the desktop run's shards timed out, its script moved on to tablet, and the two
# desktop Chromium containers kept running for another hour — four uicaps at once, load 223, swap
# full, and bina-ds (this very harness) failing its healthcheck. A timeout has to stop the WORK, not
# just the process that started it.
#
# So: each shard gets a name we own, a background `docker run` whose PID we wait on, and a watchdog
# that removes the CONTAINER when its deadline passes. The EXIT trap covers the case where this
# script itself is killed (whose containers are then also ours to clean up).
cap_t0="$(date +%s)"
pids=(); names=(); watch=()
cleanup_shards() {
  for n in "${names[@]:-}"; do
    docker rm -f "$n" >/dev/null 2>&1 || true
  done
}
trap cleanup_shards EXIT INT TERM

for i in $(seq 0 $((SHARDS - 1))); do
  cname="uicap-${i}-$$"
  names+=("$cname")
  docker rm -f "$cname" >/dev/null 2>&1 || true     # a name we own is a name we can reuse
  # THE PROXY RUNS INSIDE THE SHARD, on its own loopback: Chromium pins every `*.localhost` name to
  # 127.0.0.1 whatever the resolver says, so the only place that can serve those names is the shard
  # itself — and this is exactly what browser42's own localhost-forward does. A proxy container on
  # the office network was tried first and the shards never spoke to it (measured 2026-10-09: the
  # edge logged its routes and not one request).
  docker run --rm --network "${NET}" -v "$(npath "${DATA}"):/data" -v "$(npath "${SCRIPT_DIR}"):/edge" \
    -e UI_HOST_RESOLVER="MAP *.localhost 127.0.0.1" \
    -e CONSOLE_BASE_URL="console.localhost:${CPORT:-8000}" \
    -e BINA_DS_BASE_URL="bina.localhost:${AGENT_PORT:-3080}" \
    -e UI_MAP_PROFILE="${UI_MAP_PROFILE}" \
    -e UI_OWN_BROWSER=1 -e UI_CHROME_BIN=/usr/bin/chromium \
    -e AK_USER="${AK_USER:-akadmin}" -e AK_PASS="${AK_PASS:-}" \
    -e WA_USER="${WA_USER:-}" -e WA_PASS="${WA_PASS:-}" \
    --name "$cname" --entrypoint sh \
    "${IMAGE}" -c "python3 -u /edge/capture-edge.py ${CPORT:-8000} --route console.localhost=${CIP}:${CPORT:-8000} ${EDGE_ROOTS[*]} >/data/capture-edge.log 2>&1 & sleep 1; exec python3 -u /data/ui-capture.py ${APPS} --shard \"${i}/${SHARDS}\"" &
  pids+=("$!")
  # The watchdog: sleep the deadline, and if the container is still there, remove it. `docker rm -f`
  # also kills the client's connection, so the `wait` below returns.
  # It outlives the capture on purpose, so it must NOT keep this job's heavy slot (heavy_detach: an
  # inherited flock fd is why a finished capture used to hold the slot for its whole 900s and the
  # next profile waited on a job that was already gone).
  ( heavy_detach; sleep "${SHARD_TIMEOUT}"; \
    if docker inspect "$cname" >/dev/null 2>&1; then \
      echo "  ! shard ${i} hit its ${SHARD_TIMEOUT}s deadline — removing ${cname} (partial results are already checkpointed)"; \
      docker rm -f "$cname" >/dev/null 2>&1 || true; \
    fi ) &
  watch+=("$!")
done
rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done
for w in "${watch[@]}"; do kill "$w" >/dev/null 2>&1 || true; done
cleanup_shards
cap_dur=$(( $(date +%s) - cap_t0 ))
[ "$rc" = 0 ] || echo "  (a shard reported errors or timed out — continuing with whatever captured)"

# PROVE the profile actually applied, from the pixels. A wrong profile is invisible in the report:
# the files are named right, the run is green, and only the size gives it away. PNG width is the
# IHDR field at byte offset 16, so this needs no image library.
read -r VIEWPORT_W VIEWPORT_DSF < <(python3 - "$(npath "${SCRIPT_DIR}")/view-profiles.yaml" "${UI_MAP_PROFILE:-desktop}" <<'PYP' 2>/dev/null || echo "0 1"
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
p = doc["profiles"].get(sys.argv[2]) or doc["profiles"][doc.get("default", "desktop")]
print(p["width"], p.get("dsf", 1))
PYP
)
python3 - "$(npath "${DATA}")/output/ui" "${VIEWPORT_W:-}" "${VIEWPORT_DSF:-}" <<'PY'
import struct, sys, pathlib
out, want_w, want_dsf = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
pngs = sorted(out.glob("*.png")) if out.exists() else []
if not pngs or not want_w:
    raise SystemExit(0)
want = int(want_w) * int(want_dsf or 1)
bad = []
for f in pngs:
    with f.open("rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        continue
    w = struct.unpack(">I", head[16:20])[0]
    if w != want:
        bad.append((f.name, w))
if bad:
    print(f"::error::view profile did NOT apply: {len(bad)}/{len(pngs)} shot(s) are not {want}px wide "
          f"(expected {want_w}px x dsf {want_dsf}) — e.g. {bad[:3]}")
    raise SystemExit(1)
print(f"profile check: all {len(pngs)} shot(s) are {want}px wide  ({want_w}px x dsf {want_dsf})")
PY
echo "### ui-map — capture wall-time: ${cap_dur}s (${SHARDS} shards; excludes image build)"

# fold the per-shard result/coverage files back into the single pair the report/compose read
python3 "$(npath "${SCRIPT_DIR}")/merge_shards.py" --data "$(npath "${DATA}")" || echo "  (shard merge reported issues)"
