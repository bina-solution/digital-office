#!/usr/bin/env bash
# scripts/ops/quiet-mode.sh
#
# A SWITCHABLE POSTURE: run the document pipeline OR the QA suite, never both.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS (measured, 2026-08-05 22:00 -> 2026-08-06 03:35 IDT)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 24 docker daemon starts and 7 WSL2 VM kernel boots in five and a half hours, with ZERO graceful
# docker stops recorded in the journal — the daemon was never asked to stop, the VM was torn down
# underneath it. Every teardown recreates every container, orphans every in-flight n8n execution,
# and forces a ~65 s / 390 MB WAL crash-recovery on n8n-postgres. n8n labels the orphans
# "Workflow did not finish, possible out-of-memory issue", which is NOT an OOM and sent the team
# chasing a phantom for hours.
#
# The binding constraint is FREE RAM ON THE WINDOWS HOST, not swap and not any single container:
#   Windows physical 15.65 GiB / committed 14.38 GiB / free 1.27 GiB, with vmmemWSL at 7.04 GiB
#   and the VM ceiling set to 10 GB. When the VM grows toward its ceiling the host runs out, and
#   `wsl.exe` itself starts returning Wsl/Service/0x8007274c (reproduced three times while
#   preparing this script). There is no single runaway process to kill — it is a 44-container
#   stack whose observed peaks already sum to 10.6 GiB against a 9.7 GiB VM.
#
# So the lever is DEMAND, and the cheapest demand to remove is everything that is not on the path
# a document takes from source to COMPLETED.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# THIS IS NOT A NEW MECHANISM
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# The platform already has exactly one owner of "should this app be running": the `enabled`
# disposition in platform.state.yaml, written by `reconcile.py set-state` and converged by
# `bbox reconcile up`. This script does not start or stop containers itself and does not edit
# platform.state.yaml by hand — it drives that reconciler and records what it changed so it can
# put the disposition back. If you find yourself adding `docker stop` here, stop: that would make
# this a second, competing owner of container lifecycle, which is the defect this repo has been
# bitten by before.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# WHAT IS DISCRETIONARY — AND WHAT ONLY LOOKS DISCRETIONARY (verify before you extend this list)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# QUIETABLE (verified NOT on the source -> COMPLETED path):
#   browser42  6 containers. QA/automation browser. platform.state.yaml already declares it
#              `enabled: false` and its own comment says "nothing declares a dependency on its
#              `browser` capability" — yet all six were running. That is drift, and converging it
#              is free. This is also the Chromium tree in the top-RSS list.
#   glitchtip  4 containers. Error-reporting sink. Nothing in the document path blocks on it.
#   chat       1 container. Chat domain adapter (baileys). Not on the document path.
#
# NOT QUIETABLE — these look optional and are not. Checked, not assumed:
#   supabase   kong + rest + storage ARE on the document path. incoming-documents reaches its data
#              through the gateway, not through direct SQL:
#                .env:421                       INCOMING_DOCS_SUPABASE_URL=http://supabase-kong:8000
#                apps/indox/docker-compose.yml  SUPABASE_BASE_URL=${INCOMING_DOCS_SUPABASE_URL:-http://kong:8000}
#                apps/supabase/app.json         "endpoint": "http://supabase-kong:8000/storage/v1"
#              Disabling the `supabase` app breaks INDOX outright. Only supabase-studio and
#              supabase-meta are genuinely UI-only, and the app is a single on/off unit, so they
#              cannot be dropped through this mechanism. (Note the same drift as browser42:
#              platform.state.yaml declares `supabase: { enabled: false }` while five of its
#              containers run. Do NOT "fix" that drift by converging it — it would take INDOX
#              down. The state file is what is wrong there, not the running stack.)
#   authentik  Layer 1, "system: cannot be disabled". The document path does not traverse
#              forward-auth (n8n and incoming-documents talk over service DNS, bypassing traefik),
#              but the platform does not offer disabling it and this script will not force it.
#   mail       One app owns mailapi + mailserver + mailview + mailboxd. mailapi/mailserver are a
#              document SOURCE, so the app must stay enabled even though mailview is UI-only.
#   indox      Owns incoming-documents (on the path) and indox-demo-docs (not). Single unit.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# MEASURED EFFECT of `quiet-mode.sh on` (cgroup memory.peak, sampled 2026-08-06 03:38)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#   containers stopped        11  (browser42 x6, glitchtip x4, chat x1)
#   declared ceiling freed    6272 MiB   (at the right-sized limits in this same change)
#   REAL working set freed    2116 MiB   (browser42 1339 + glitchtip 561 + chat 216)
# The 2116 MiB is the number that matters — that is memory the WSL VM stops holding against a
# Windows host that had 1.27 GiB free.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# USAGE
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#   bash scripts/ops/quiet-mode.sh status         # what posture are we in, and what is drifting
#   bash scripts/ops/quiet-mode.sh on             # DRY RUN — print exactly what would change
#   bash scripts/ops/quiet-mode.sh on --apply     # disable the discretionary set + converge
#   bash scripts/ops/quiet-mode.sh off --apply    # restore the recorded dispositions + converge
#
# --apply RECREATES CONTAINERS. That is the same disruption this work exists to prevent, so never
# run it during a proof run. `status` and the dry run are always safe.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_DIR="$SCRIPT_DIR/.quiet-mode-state"
SAVED="$STATE_DIR/pre-quiet-dispositions.txt"
mkdir -p "$STATE_DIR"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/bbox-docker.sock}"

# The discretionary set. Keep this list short and keep the justification above it honest — an app
# added here without checking the document path is a throughput outage waiting to happen.
QUIETABLE="browser42 glitchtip chat"

ACTION="${1:-status}"
APPLY=0
for a in "$@"; do [ "$a" = "--apply" ] && APPLY=1; done

say() { printf '%s\n' "$*"; }
rule() { printf '================================================================\n'; }

# Read an app's current disposition straight out of platform.state.yaml. reconcile.py is the
# writer; this is only a reader, so a regex is legitimate here.
dispo_of() {
  local app="$1"
  python3 - "$REPO_ROOT/platform.state.yaml" "$app" <<'PYEOF'
import re, sys
path, app = sys.argv[1], sys.argv[2]
txt = open(path, encoding='utf-8').read()
m = re.search(r'^\s*%s:\s*\{([^}]*)\}' % re.escape(app), txt, re.M)
if not m:
    print('absent'); sys.exit(0)
body = m.group(1)
if re.search(r'enabled:\s*true', body):  print('enabled')
elif re.search(r'enabled:\s*false', body): print('disabled')
elif re.search(r'state:\s*disabled', body): print('disabled')
else: print('unknown')
PYEOF
}

running_count() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -cE "^$1" || true
}

rule
say "quiet-mode  $(date -u +%Y-%m-%dT%H:%M:%SZ)  action=${ACTION}  mode=$([ $APPLY -eq 1 ] && echo APPLY || echo DRY-RUN)"
rule

# ---- host pressure, always printed: this is the number the posture exists to move ----
say
say "--- host pressure right now ---"
free -m | sed 's/^/  /'
say "  load average:$(cut -d' ' -f1-3 /proc/loadavg | sed 's/^/ /')"
say "  docker daemon started: $(systemctl show docker -p ExecMainStartTimestamp --value 2>/dev/null || echo unknown)"

case "$ACTION" in

  status)
    say
    say "--- discretionary apps: declared disposition vs what is actually running ---"
    for app in $QUIETABLE; do
      d=$(dispo_of "$app")
      n=$(running_count "$app")
      flag=""
      [ "$d" = "disabled" ] && [ "$n" -gt 0 ] && flag="   <-- DRIFT: declared disabled, $n running"
      printf '  %-12s declared=%-9s running_containers=%-3s%s\n' "$app" "$d" "$n" "$flag"
    done
    say
    if [ -f "$SAVED" ]; then
      say "--- quiet mode is ON (saved dispositions present) ---"
      sed 's/^/  /' "$SAVED"
      say "  restore with: bash scripts/ops/quiet-mode.sh off --apply"
    else
      say "--- quiet mode is OFF (no saved dispositions) ---"
    fi
    ;;

  on)
    if [ -f "$SAVED" ]; then
      say
      say "REFUSING: $SAVED already exists — quiet mode is already ON."
      say "Turning it on twice would overwrite the record of what to restore, and you would lose"
      say "the original dispositions. Run 'off --apply' first if you want to re-arm it."
      exit 1
    fi
    say
    say "--- would disable (and record for restore) ---"
    TMP="$STATE_DIR/.pending"
    : > "$TMP"
    for app in $QUIETABLE; do
      d=$(dispo_of "$app")
      n=$(running_count "$app")
      printf '  %-12s declared=%-9s running=%-3s -> disabled\n' "$app" "$d" "$n"
      printf '%s %s\n' "$app" "$d" >> "$TMP"
    done
    if [ "$APPLY" -eq 0 ]; then
      rm -f "$TMP"
      say
      say "DRY RUN — nothing changed. Re-run with --apply, in a window with no proof run in flight."
      exit 0
    fi
    mv "$TMP" "$SAVED"
    for app in $QUIETABLE; do
      say "  set-state $app -> disabled"
      ( cd "$REPO_ROOT" && python3 platform/manager/reconcile.py set-state --app "$app" --state disabled --by quiet-mode ) \
        || { say "  ERROR: could not set $app disabled — aborting before converge."; exit 1; }
    done

    # ── WHY THIS STOPS CONTAINERS DIRECTLY INSTEAD OF CALLING `reconcile.py up` ──────────────────
    # `reconcile.py up` has NO app scoping. Read it: reconcile.py:1324-1329 shells
    #   docker compose -f <every compose file> up -d --remove-orphans
    # over the WHOLE stack. It would remove the disabled apps' containers (what we want) AND
    # recreate every other container whose compose definition has changed since the last converge
    # (what we do not want). With the memory-limit right-sizing sitting on disk unapplied, a full
    # converge here would silently apply all of it too — turning "one controlled restart" into a
    # stack-wide recreate, which is the exact disruption this posture exists to avoid.
    #
    # So the split is deliberate and narrow:
    #   - the RECONCILER still owns "what should exist"  (set-state above, and render below)
    #   - this only enacts the DELTA of that decision — stopping containers the state file no
    #     longer declares. It touches nothing it did not just disable.
    # This is not a second lifecycle owner; it is the removal half of one decision, scoped.
    #
    # `stop`, not `rm`: it frees the memory (which is the entire point) while leaving the container
    # objects and every named volume intact, so `off --apply` is a cheap restart rather than a
    # rebuild. And a manually-stopped container is NOT resurrected when the docker daemon restarts
    # — measured on this very machine in the journal:
    #   "ShouldRestart failed, container will not be restarted ... hasBeenManuallyStopped=true"
    # which matters here precisely because the daemon restarts ~24 times a night.
    say
    say "--- re-rendering .generated/ so the disabled apps stop being declared ---"
    ( cd "$REPO_ROOT" && python3 platform/manager/reconcile.py render ) \
      || say "  WARNING: render failed — state is written but .generated/ is stale."

    say
    say "--- stopping containers for the disabled apps (scoped: nothing else is touched) ---"
    STOPPED=0
    for app in $QUIETABLE; do
      # chat's container is `chat-<deployment>`; browser42's are `browser42-*`; glitchtip's
      # `glitchtip-*`. Anchor the match so `chat` can never match e.g. `chatapi-something`.
      for c in $(docker ps --format '{{.Names}}' | grep -E "^${app}(-|$)" || true); do
        say "  docker stop $c"
        if docker stop "$c" >/dev/null 2>&1; then
          STOPPED=$((STOPPED+1))
        else
          say "    WARNING: could not stop $c"
        fi
      done
    done
    say "  stopped ${STOPPED} container(s)."
    say
    say "  NOTE: these are stopped, not removed. The state file now says disabled, so the next"
    say "        full 'reconcile up' will drop them as orphans. That is expected."
    say "  quiet mode ON."
    ;;

  off)
    if [ ! -f "$SAVED" ]; then
      say
      say "REFUSING: no $SAVED — quiet mode was not turned on by this script."
      say "Restoring blind would guess at dispositions this script never recorded. Set them with"
      say "'bbox apps enable <app>' yourself if that is really what you want."
      exit 1
    fi
    say
    say "--- would restore ---"
    while read -r app d; do
      [ -z "$app" ] && continue
      printf '  %-12s -> %s\n' "$app" "$d"
    done < "$SAVED"
    if [ "$APPLY" -eq 0 ]; then
      say
      say "DRY RUN — nothing changed. Re-run with --apply."
      exit 0
    fi
    while read -r app d; do
      [ -z "$app" ] && continue
      # 'absent'/'unknown' are not dispositions we can write back; leave those alone and say so.
      case "$d" in
        enabled|disabled) ;;
        *) say "  SKIP $app — recorded disposition was '$d', nothing safe to restore."; continue ;;
      esac
      say "  restoring $app -> $d"
      ( cd "$REPO_ROOT" && python3 platform/manager/reconcile.py set-state --app "$app" --state "$d" --by quiet-mode ) \
        || say "  WARNING: could not restore $app to $d"
    done < "$SAVED"
    say
    say "--- re-rendering .generated/ ---"
    ( cd "$REPO_ROOT" && python3 platform/manager/reconcile.py render ) \
      || say "  WARNING: render failed."
    # Symmetric with `on`: start back exactly what we stopped, and nothing else. A full
    # `reconcile up` here would recreate unrelated containers whose compose files have changed
    # since the last converge — see the long note in the `on` branch.
    say
    say "--- starting the containers this script stopped (scoped) ---"
    STARTED=0
    while read -r app d; do
      [ -z "$app" ] && continue
      [ "$d" = "enabled" ] || continue
      for c in $(docker ps -a --format '{{.Names}}' | grep -E "^${app}(-|$)" || true); do
        say "  docker start $c"
        if docker start "$c" >/dev/null 2>&1; then STARTED=$((STARTED+1)); else say "    WARNING: could not start $c"; fi
      done
    done < "$SAVED"
    say "  started ${STARTED} container(s)."
    say
    say "  NOTE: apps recorded as already-disabled (e.g. browser42, which platform.state.yaml"
    say "        declared disabled before this ran) are deliberately NOT started — restoring them"
    say "        would recreate the drift, not undo this script."
    rm -f "$SAVED"
    say "  quiet mode OFF."
    ;;

  *)
    say "unknown action '$ACTION' (status|on|off)"
    exit 1
    ;;
esac

say
rule
say "quiet-mode done  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
rule
