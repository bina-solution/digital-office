#!/usr/bin/env sh
# browser42-state.sh — preserve / share the FULL browser state (cookies, logins,
# localStorage, IndexedDB, the whole stealth profile) between deployments via an
# encrypted dump you can move to another host and load.
#
#   ./browser42-state.sh dump  [outfile.enc]     # encrypted snapshot of /profile
#   ./browser42-state.sh load  <infile.enc>      # restore a snapshot (REPLACES state)
#   ./browser42-state.sh info                     # volume name + size
#
# Encryption: AES-256-CBC + PBKDF2 (200k iters, salted) with a passphrase.
# Passphrase resolution: $BROWSER42_STATE_PASSPHRASE in the env wins; else it is
# read from the repo-root .env (gitignored); else you're prompted. The .env value
# is a per-host secret — it stays local and never travels with the .enc dump.
# Share the passphrase out-of-band (never commit it / never ship it with the .enc).
#
# State lives in the Docker volume mounted at /profile (cloakserve --data-dir).
# The browser is stopped during dump (consistency) and load (required), then
# restarted. Uses an already-present image (node:22-slim) so it needs no pull.
set -eu

# `dr` runs docker with MSYS_NO_PATHCONV so Git Bash doesn't mangle CONTAINER-side
# paths (-v vol:/profile, -C /profile). Host openssl below runs WITHOUT it, so its
# own file paths convert normally. On Linux/VPS the env var is simply ignored.
dr() { MSYS_NO_PATHCONV=1 docker "$@"; }

# Repo-root .env (gitignored) — used to auto-supply BROWSER42_STATE_PASSPHRASE.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/../../.env"

ITER=200000
IMG=node:22-slim            # already pulled; has tar + gzip
ENC="openssl enc -aes-256-cbc -pbkdf2 -iter ${ITER} -salt -pass env:BROWSER42_STATE_PASSPHRASE"

cmd="${1:-}"; arg="${2:-}"

# --- resolve the browser container + its /profile volume (deployment-agnostic) ---
BROWSER="$(docker ps -a --filter name=browser42-browser --format '{{.Names}}' | head -1)"
[ -n "$BROWSER" ] || { echo "browser42-browser container not found" >&2; exit 1; }
VOL="$(docker inspect "$BROWSER" --format '{{range .Mounts}}{{if eq .Destination "/profile"}}{{.Name}}{{end}}{{end}}')"
[ -n "$VOL" ] || { echo "could not resolve /profile volume" >&2; exit 1; }

need_pass() {
  # 1) already in env wins. 2) else pull it from the repo-root .env (gitignored),
  #    tolerating surrounding quotes and a stray CR (CRLF .env on Windows).
  if [ -z "${BROWSER42_STATE_PASSPHRASE:-}" ] && [ -f "$ENV_FILE" ]; then
    val=$(grep -E '^[[:space:]]*BROWSER42_STATE_PASSPHRASE=' "$ENV_FILE" | tail -1 \
          | sed -E 's/^[[:space:]]*BROWSER42_STATE_PASSPHRASE=//' | tr -d '\r')
    case "$val" in
      \"*\") val=$(printf '%s' "$val" | sed -E 's/^"//; s/"$//') ;;
      \'*\') val=$(printf '%s' "$val" | sed -E "s/^'//; s/'$//") ;;
    esac
    [ -n "$val" ] && { BROWSER42_STATE_PASSPHRASE="$val"; export BROWSER42_STATE_PASSPHRASE; }
  fi
  # 3) else prompt interactively.
  if [ -z "${BROWSER42_STATE_PASSPHRASE:-}" ]; then
    printf 'Passphrase: ' >&2
    stty -echo 2>/dev/null || true; read -r BROWSER42_STATE_PASSPHRASE; stty echo 2>/dev/null || true
    printf '\n' >&2
    export BROWSER42_STATE_PASSPHRASE
  fi
  [ -n "${BROWSER42_STATE_PASSPHRASE:-}" ] || { echo "empty passphrase" >&2; exit 1; }
}

was_running() { [ "$(docker inspect -f '{{.State.Running}}' "$BROWSER" 2>/dev/null)" = "true" ]; }

case "$cmd" in
  info)
    echo "container : $BROWSER"
    echo "volume    : $VOL"
    dr run --rm -v "$VOL":/profile:ro "$IMG" sh -c 'echo "size      : $(du -sh /profile | cut -f1)"; echo "modified  : $(date -r /profile/__default__ 2>/dev/null || date)"'
    ;;

  dump)
    need_pass
    out="${arg:-browser42-state-$(date +%Y%m%d-%H%M%S).tar.gz.enc}"
    restart=0; was_running && restart=1
    [ "$restart" = 1 ] && { echo "stopping $BROWSER for a consistent snapshot..." >&2; docker stop "$BROWSER" >/dev/null; }
    dr run --rm -v "$VOL":/profile:ro "$IMG" tar czf - -C /profile . | $ENC > "$out"
    [ "$restart" = 1 ] && docker start "$BROWSER" >/dev/null
    echo "dumped $VOL -> $out ($(wc -c < "$out") bytes, encrypted)"
    ;;

  verify)   # decrypt + list without restoring (sanity-check an .enc + passphrase)
    need_pass
    [ -n "$arg" ] || { echo "usage: $0 verify <file.enc>" >&2; exit 1; }
    openssl enc -d -aes-256-cbc -pbkdf2 -iter "$ITER" -pass env:BROWSER42_STATE_PASSPHRASE < "$arg" \
      | dr run --rm -i "$IMG" tar tzf - | head -20
    echo "... (archive decrypts OK)"
    ;;

  load)
    need_pass
    [ -n "$arg" ] || { echo "usage: $0 load <file.enc>" >&2; exit 1; }
    [ -f "$arg" ] || { echo "no such file: $arg" >&2; exit 1; }
    echo "WARNING: this REPLACES the entire browser profile in $VOL." >&2
    restart=0; was_running && restart=1
    docker stop "$BROWSER" >/dev/null 2>&1 || true
    # Read via shell redirect (< "$arg"), NOT openssl -in: on Git-Bash the host openssl can't open
    # an absolute MSYS path (/c/Users/…) that callers (onboarding/bbox) pass, but the shell can.
    openssl enc -d -aes-256-cbc -pbkdf2 -iter "$ITER" -pass env:BROWSER42_STATE_PASSPHRASE < "$arg" \
      | dr run --rm -i -v "$VOL":/profile "$IMG" sh -c 'find /profile -mindepth 1 -delete 2>/dev/null; tar xzf - -C /profile'
    # always (re)start the browser so the loaded profile is live — the point of a load is a usable
    # browser afterward; conditioning on prior state lost logins when called on a just-started container.
    docker start "$BROWSER" >/dev/null 2>&1 || true
    # Don't return while the live view is still black: a container restart drops the reaper's CDP
    # connection (which keeps the headed Chrome alive); the reaper reconnects and re-wakes Chrome.
    # Wait for CDP to actually serve so the caller knows the view is live. Bounded — warn, never hang.
    printf 'waiting for browser to come live' >&2; i=0
    while [ "$i" -lt 30 ]; do
      if docker exec "$BROWSER" python3 -c 'import urllib.request,sys;sys.exit(0 if b"webSocketDebuggerUrl" in urllib.request.urlopen("http://localhost:9222/json/version",timeout=2).read() else 1)' >/dev/null 2>&1; then
        printf ' live\n' >&2; break; fi
      printf '.' >&2; sleep 2; i=$((i+1))
    done
    [ "$i" -ge 30 ] && printf ' (still warming — open the view again in a moment)\n' >&2
    echo "loaded $arg -> $VOL (browser restarted)"
    ;;

  reset)
    # Wipe the profile -> fresh stealth browser (no cookies/logins). Destructive.
    [ "${arg:-}" = "--yes" ] || { echo "WIPES all logins/cookies in $VOL. Re-run: $0 reset --yes" >&2; exit 1; }
    restart=0; was_running && restart=1
    docker stop "$BROWSER" >/dev/null 2>&1 || true
    dr run --rm -v "$VOL":/profile "$IMG" sh -c 'find /profile -mindepth 1 -delete 2>/dev/null'
    [ "$restart" = 1 ] && docker start "$BROWSER" >/dev/null
    echo "reset $VOL — fresh profile on next start"
    ;;

  *)
    echo "usage: $0 {dump [outfile.enc] | load <infile.enc> | reset --yes | verify <file.enc> | info}" >&2
    exit 1;;
esac
