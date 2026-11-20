#!/bin/sh
# entrypoint.sh — boot the Bina harness profile against the persistent home.
#
# The profile's code (node_modules, package.json, cordis.patch.yml, agent-presets) lives in the image
# under /opt/bina/harness/profile; everything a user accumulates — .credentials.yaml, sessions,
# workspaces, and the profile's OWN settings layer — lives in $DSH_HOME on the bina_ds_home volume.
#
# Since DeepSeek Harness 0.2.x the user's settings (the default model, the Models page, the local model
# routes) are not `$DSH_HOME/settings.yaml` any more but the profile directory's own `cordis.yml` (and
# its `cordis.snapshot.yml`), written by the harness — and the first 0.2.x start MOVES an old
# settings.yaml into it (renaming the file `settings.yaml.imported`). With the profile directory a
# symlink into the image, that import landed in the container's own filesystem and was lost at the next
# recreate (EXU-64, measured 2026-11-14: the office's local default model was gone after a redeploy).
# So $DSH_HOME/profiles/bina is a REAL directory on the volume: every file of the image's profile is
# linked into it, refreshed at every start so an image upgrade replaces the code, and the settings layer
# beside them is the volume's own. That layer is the profile's `cordis.patch.yml` — the one file 0.2.x
# writes the user's settings into, as rows — so the OFFICE'S declared composition (the image's
# cordis.patch.yml) is not that file: it is passed to dsh as the first `--patch` overlay (below), and
# the volume's own cordis.patch.yml starts empty and belongs to the harness and the routes writer.
set -eu
: "${DSH_HOME:=/data/dsh}"
: "${DSH_PROFILE:=bina}"
: "${DSH_PORT:=3080}"
PROFILE_SRC=/opt/bina/harness/profile
PROFILE_DIR="${DSH_HOME}/profiles/${DSH_PROFILE}"
mkdir -p "${DSH_HOME}/profiles"
[ -L "${PROFILE_DIR}" ] && rm -f "${PROFILE_DIR}"            # the 0.1.6 layout: one symlink into the image
mkdir -p "${PROFILE_DIR}"
for f in "${PROFILE_DIR}"/* "${PROFILE_DIR}"/.[!.]*; do         # links whose target the new image no longer has
  [ -L "$f" ] && [ ! -e "$f" ] && rm -f "$f"
done
for f in "${PROFILE_SRC}"/* "${PROFILE_SRC}"/.[!.]*; do
  [ -e "$f" ] || continue
  case "$(basename "$f")" in cordis.yml|cordis.snapshot.yml|cordis.patch.yml) continue ;; esac   # the volume's own
  ln -sfn "$f" "${PROFILE_DIR}/$(basename "$f")"
done
[ -L "${PROFILE_DIR}/cordis.patch.yml" ] && rm -f "${PROFILE_DIR}/cordis.patch.yml"
if [ ! -e "${PROFILE_DIR}/cordis.patch.yml" ]; then
  printf '%s\n' "# The user's settings layer of this office's agent harness (written by the harness and by" \
    "# bina-ds-llm-routes). The office's own composition is apps/bina-ds/harness/profile/cordis.patch.yml," \
    "# applied as an overlay after this file. EXU-64." "[]" > "${PROFILE_DIR}/cordis.patch.yml"
fi
# The settings an earlier 0.2.x start imported into a profile directory that was not on the volume: the
# volume's settings layer does not exist yet, so the old document is put back once and imported again —
# this time where it stays.
# ONCE: a marker on the volume says it was done, so a later restart never re-imports stale settings over
# what the owner changed since.
if [ ! -e "${DSH_HOME}/.settings-reimported" ] && [ -e "${DSH_HOME}/settings.yaml.imported" ] && [ ! -e "${DSH_HOME}/settings.yaml" ]; then
  mv "${DSH_HOME}/settings.yaml.imported" "${DSH_HOME}/settings.yaml"
  date -u '+%FT%TZ' > "${DSH_HOME}/.settings-reimported"
  echo "entrypoint: settings.yaml put back once, to be imported into the profile on the volume" >&2
fi
export DSH_HOME

# A cordis.patch.yml in the HOME is a second plugin layer — dsh stacks it over the profile's — that
# every image version shares and none can roll back from. Measured 2026-09-30 13:13-14:24: an agent
# wrote a "temporary" plugin insert there to try a plugin without a rebuild; the old image then named
# a package it does not ship and never bound its port, the new image hit "duplicate loader entry" and
# exited, the health gate rolled back into the same state, and every conversation was down for 41
# minutes. The profile in the image (apps/bina-ds/harness/profile/cordis.patch.yml, in git) is the
# one layer this deployment boots from: a stray file is moved aside — kept, never deleted — said out
# loud here, and reported to the owner once the network is up. Boot goes on: recover, do not block.
for stray in "${DSH_HOME}/cordis.patch.yml" "${DSH_HOME}/cordis.patch.yaml"; do
  [ -e "${stray}" ] || continue
  aside="${stray}.disabled-$(date +%Y%m%d-%H%M%S)"
  mv "${stray}" "${aside}"
  echo "entrypoint: ${stray} is not a layer this deployment boots from — moved to ${aside}." >&2
  echo "entrypoint: plugins are declared in the image's profile (apps/bina-ds/harness/profile/cordis.patch.yml): change it there and rebuild (./scripts/dc up -d --build bina-ds)." >&2
  BINA_DS_BOOT_NOTICE="הקובץ ${stray} הוזז ל-${aside}. תוספים מוגדרים רק בפרופיל שבתמונה (apps/bina-ds/harness/profile/cordis.patch.yml): שנה שם ובנה מחדש — לעולם לא בנפח הנתונים."
done
unset stray aside

# Provider keys reach this container three ways, and the harness treats them in one order:
#   1. the platform's connections (the deepseek-key / openai-key / anthropic-key cards) and .env —
#      arrive as environment variables; the harness resolves `apiKeyEnv` per request and the Models
#      page shows the field as "provided by the launch environment (read-only)";
#   2. keys the operator types into the Models page — stored by the harness in
#      $DSH_HOME/.credentials.yaml (on the volume), used when no environment key exists;
#   3. nothing — the provider is listed, the field is editable, requests fail MISSING_CREDENTIAL.
# A template PLACEHOLDER (.env.ex ships `sk-your-…`/`your-…` stubs so every key has a line) must
# count as case 3, not case 1: left in place it LOCKS the field with a value that can never work.
# `CHANGE_ME` is one too: .env.ex ships DEEPSEEK_API_KEY='CHANGE_ME', and taken as a key it made
# DeepSeek look configured — עזריה offered its models and every turn on them failed 401 (EXU-64).
# Compared without quotes, carriage returns or case, so `"CHANGE_ME"`, 'changeme' and a CRLF .env match too.
for var in DEEPSEEK_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY; do
  eval "val=\${${var}:-}"
  bare=$(printf '%s' "${val}" | tr -d "\"'\r" | tr '[:upper:]' '[:lower:]')
  case "${bare}" in
    ""|sk-your-*|your-*|*your-*-key*|change_me*|changeme*) unset "${var}" ;;
  esac
done
unset var val bare

# The checkout is mounted at its host path (docker-compose.yml); /workspace/office is the short,
# ASCII alias of the same directory. Never loop the link onto itself when the two coincide.
if [ -n "${BBOX_REPO_HOST:-}" ] && [ -d "${BBOX_REPO_HOST}" ] && [ "${BBOX_REPO_HOST}" != /workspace/office ]; then
  mkdir -p /workspace && ln -sfn "${BBOX_REPO_HOST}" /workspace/office
fi
# git refuses a checkout owned by another uid (virtiofs/WSL mounts) unless told it is ours.
git config --global --add safe.directory '*' 2>/dev/null || true
git config --global user.name  "${GIT_AUTHOR_NAME:-עזריה}" 2>/dev/null || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-azaria@bina.local}" 2>/dev/null || true

# ── pushes leave through the office's own proxy (DGO-62) ────────────────────────────────────────
# `origin` is https://github.com/... and STAYS that way; this rewrite sends it to the git app, which
# injects the credential server-side. No token is ever on a command line, in .git/config, or in this
# container's environment — and `git fetch origin dgo` / `git push origin dgo` simply work.
#
# The account id comes FROM THE VAULT, read at container start through the app's own /api/overview;
# nothing about it is written down here. Best effort by design: at start the git app may not be up
# yet, and a missing rewrite costs a slower push, never a broken container. Re-run it by hand with
# the same two lines (the skill documents them).
office_git_proxy() {
  command -v git >/dev/null 2>&1 || return 0
  command -v curl >/dev/null 2>&1 || return 0
  local base="${OFFICE_GIT_URL:-http://git:8978}" ov acc code
  ov="$(curl -fsS --max-time 8 "${base}/api/overview" 2>/dev/null)" || return 0
  [ -n "${ov}" ] || return 0
  for code in gh gl; do
    case "${code}" in
      gh) acc="$(printf '%s' "${ov}" | grep -o '"id":"git_github[^"]*"' | head -1 | cut -d'"' -f4)" ;;
      gl) acc="$(printf '%s' "${ov}" | grep -o '"id":"git_gitlab[^"]*"' | head -1 | cut -d'"' -f4)" ;;
    esac
    [ -n "${acc}" ] || continue
    case "${code}" in
      gh) git config --global "url.${base}/git/gh/${acc}/.insteadOf" "https://github.com/" ;;
      gl) git config --global "url.${base}/git/gl/${acc}/.insteadOf" "https://gitlab.com/" ;;
    esac
  done
  return 0
}
office_git_proxy

# dsh parses `<cwd>/.env` at boot, so the process keeps starting from the profile directory
# (which has none). DSH_OFFICE_ROOT tells the office-workspace plugin where the checkout is.
if [ -d "${BBOX_REPO_HOST:-/workspace/office}" ]; then export DSH_OFFICE_ROOT="${BBOX_REPO_HOST:-/workspace/office}"; fi
# The action token of the agent.v1 adapter (ai/context/agent-contract.md): minted ONCE into the
# volume, root-only, exported to both processes of this container. `bbox agent` reads it through the
# engine; it is never an .env value and never leaves the volume otherwise.
TOKEN_FILE="${DSH_HOME}/api-token"
if [ ! -s "${TOKEN_FILE}" ]; then
  ( umask 077; node -e 'process.stdout.write(require("crypto").randomBytes(32).toString("base64url"))' > "${TOKEN_FILE}" )
fi
chmod 600 "${TOKEN_FILE}"
BINA_DS_API_TOKEN="$(cat "${TOKEN_FILE}")"
export BINA_DS_API_TOKEN
# The ONE address the harness listens on. Since 0.2.x its web server refuses a wildcard (`0.0.0.0`:
# "binding every interface would expose remote code execution to the network") and takes one concrete
# address. The edge reaches this container on the network it shares with it, so that is the address:
# the local interface whose subnet holds the edge (`traefik-<office>`, its alias on traefik-network) —
# not merely the first interface, which on a container joined to a second network may be the wrong leg.
# When the edge cannot be resolved yet, the first non-internal IPv4 is used and the log says so.
# Everything inside the container that calls the harness (the adapter, the healthcheck) calls it on
# the same address; the healthcheck reads it from /tmp/dsh-bind-host.
DSH_BIND_HOST="$(node -e '
const os = require("os"), dns = require("dns");
const ifs = Object.values(os.networkInterfaces()).flat().filter((i) => i && i.family === "IPv4" && !i.internal);
const v = (s) => s.split(".").reduce((a, x) => ((a << 8) + Number(x)) >>> 0, 0);
const same = (ip, cidr) => { if (!cidr) return false; const [a, b] = cidr.split("/"); const m = Number(b) === 0 ? 0 : (~0 << (32 - Number(b))) >>> 0; return ((v(ip) & m) >>> 0) === ((v(a) & m) >>> 0); };
const edges = [process.env.DSH_EDGE_HOST, "traefik-" + (process.env.DEPLOYMENT_NAME || ""), "traefik-deployment"].filter((h) => h && !h.endsWith("-"));
(async () => {
  for (const h of edges) {
    try { const { address } = await dns.promises.lookup(h, { family: 4 }); const i = ifs.find((x) => same(address, x.cidr)); if (i) return process.stdout.write(i.address); } catch {}
  }
  process.stderr.write("entrypoint: the edge is not resolvable from here — listening on the first network address\n");
  process.stdout.write(ifs[0] ? ifs[0].address : "127.0.0.1");
})().catch(() => process.stdout.write(ifs[0] ? ifs[0].address : "127.0.0.1"));')" || DSH_BIND_HOST=""
[ -n "${DSH_BIND_HOST}" ] || DSH_BIND_HOST=127.0.0.1
export DSH_BIND_HOST
printf '%s' "${DSH_BIND_HOST}" > /tmp/dsh-bind-host
# The adapter is a sibling process; if it dies the harness keeps serving the UI, and /v1/health
# going dark is what reports it. It is restarted with the container, like the harness.
node /opt/bina/adapter/server.mjs &

# The stray-patch notice (above), delivered once the harness is coming up; same upsert row every
# time (source_id), so repeated boots do not pile up notifications.
if [ -n "${BINA_DS_BOOT_NOTICE:-}" ]; then
  ( sleep 5; python3 -c 'import json, sys; print(json.dumps({"source": "bina-ds", "source_id": "boot-stray-patch", "level": "warning", "title": "בינה: קובץ תוספים בנפח הנתונים הוזז הצידה", "body": sys.argv[1], "link": "/#/m/bina"}, ensure_ascii=False))' "${BINA_DS_BOOT_NOTICE}" \
      | curl -fsS -m 10 -H 'Content-Type: application/json' --data-binary @- http://notifications:8977/api/notifications >/dev/null 2>&1 || true ) &
fi

# NO CONTAINER-SIDE TIMER LIVES HERE. The office's 5-minute pulse was a shell loop in this container
# (apps/bina-ds/pulse.sh — deleted 2026-10-14, DGO-562). The owner's ruling that day: «use n8n
# automation blueprinted inside bina-ds app. And remove pulse and all of this mod bullshit, keep clean
# and official». So the schedule is DECLARED as a workflow under apps/bina-ds/blueprint/n8n/ and runs
# in the office's n8n; what this container owns is one narrow, declared door for it to call
# (`POST /v1/seder/<cycle>` on the adapter below), which needs no secret and fires a cycle at most once
# a day. Nothing in this container polls, sleeps or wakes on a timer.

# ── THE HARNESS RUNS AS A CHILD, SO ITS EXIT LEAVES A RECORD ─────────────────────────────────────
# This used to end with `exec`, which made the harness PID 1: when that process exited — for any
# reason, including a clean exit 0 — Docker's `unless-stopped` policy restarted the SAME container,
# every conversation mid-tool-call died with an outcome the harness could not record, and NOTHING was
# written down anywhere. Measured twice on 2026-10-14: 01:44:55Z the container came back with
# `RestartCount=1`, `ExitCode=0`, no shutdown line at all (two sessions and the two executors the
# day's שחרית had just spawned were killed); and the owner reported the same shape again at 04:44
# local. The evidence for that day had to be reconstructed from the sessions' own logs after the fact,
# because neither the container log nor the app's log carried a word about it.
#
# What changes: the harness is started as a CHILD and waited on. Its exit — a code, or the signal that
# ended it — is appended to a file **on the volume**, the one place that survives the same container
# being restarted, and the NEXT boot reads that file and says what happened: a log line always, and a
# notification when the exit was not clean. The restart itself is deliberately NOT suppressed: the
# office must come back. What was missing was the record, not the recovery.
#
# The trap forwards SIGTERM/SIGINT to the child, so `docker stop` still reads as a deliberate stop and
# not as a crash — a stop must never be reported to the owner as "בינה קרסה".
EXIT_LOG="${DSH_HOME}/harness-exit.log"
if [ -s "${EXIT_LOG}" ]; then
  last="$(tail -n 1 "${EXIT_LOG}")"
  echo "entrypoint: the previous harness process ended — ${last}" >&2
  case "${last}" in
    *"exit=0"*) : ;;   # a clean exit is still worth the line above, and is not worth a notification
    *)
      ( sleep 8; python3 -c 'import json, sys; print(json.dumps({"source": "bina-ds", "source_id": "harness-exit", "level": "warning", "title": "בינה יצאה מעצמה והלשכה הופעלה מחדש", "body": sys.argv[1], "link": "/#/m/bina"}, ensure_ascii=False))' "התהליך של בינה הסתיים מעצמו והמכולה הופעלה מחדש. הרשומה: ${last}" \
          | curl -fsS -m 10 -H 'Content-Type: application/json' --data-binary @- http://notifications:8977/api/notifications >/dev/null 2>&1 || true ) &
      ;;
  esac
fi
: >"${EXIT_LOG}"          # this boot's own record; whatever was there has just been read

cd /opt/bina/harness/profile
set -- node_modules/.bin/dsh --profile "${DSH_PROFILE}" --patch /opt/bina/harness/profile/cordis.patch.yml
# The office's agent presets (עזריה, רפאל, עזריה · מקומי), one patch file each beside the profile:
# since 0.2.x a preset is a row of the preset registry (`@deepseek-ai/dsh-agent-preset`), not a
# directory the harness discovers, so each is composed in as its own overlay, in name order.
# `--patch` is the launcher's option, so it goes before the app's own flags.
for p in agent-presets/*/preset.patch.yml; do [ -f "$p" ] && set -- "$@" --patch "/opt/bina/harness/profile/$p"; done
set -- "$@" --no-open --port "${DSH_PORT}"
for h in ${DSH_TRUSTED_HOSTS:-}; do set -- "$@" --trusted-host "$h"; done
"$@" &
harness_pid=$!
# The office's own time on every line (the door learnt this the hard way: a UTC line beside local
# ones reads as a different day).
record_exit() {   # $1 = exit code, $2 = signal name or empty
  printf '%s office=%s pid=%s %s\n' \
    "$(date -u '+%FT%TZ')" "$(TZ="${TZ:-Asia/Jerusalem}" date '+%F %T')" "${harness_pid}" \
    "${2:+signal=${2} }exit=$1" >>"${EXIT_LOG}" 2>/dev/null || true
}
trap 'kill -TERM "${harness_pid}" 2>/dev/null || true; wait "${harness_pid}" 2>/dev/null || true; record_exit 0 TERM; exit 0' TERM INT
# `|| rc=$?` and not a bare `wait`: this script runs under `set -e`, so a child that exited non-zero
# would end the shell at the `wait` — BEFORE the record line, which is the one thing this whole block
# exists to write. Measured on the first run of this supervisor (2026-10-14): the crashing-harness case
# produced an empty `harness-exit.log` and looked exactly like the silent death it is meant to fix.
rc=0
wait "${harness_pid}" || rc=$?
trap - TERM INT
record_exit "${rc}"
exit "${rc}"
