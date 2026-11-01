#!/usr/bin/env bash
# engine-orphans.sh — list (and with --clean, remove) what a wedged engine leaves behind.
#
#   ./scripts/engine-orphans.sh            report only, exit 1 if anything is found
#   ./scripts/engine-orphans.sh --clean    kill orphan shims, remove leftover containers, exit 0
#
# Runs ON THE ENGINE (the Lima guest / WSL distro / the VPS), as root: it reads /proc and
# /var/lib/docker/containers directly, because when this matters the docker API is the thing that
# is not answering. On macOS: `./bbox engine shell -- scripts/engine-orphans.sh`.
#
# WHAT IT FINDS, and why each is worth a script (measured 2026-09-30 on the 5 GiB macOS engine):
#
#   * ORPHAN SHIMS — a containerd-shim-runc-v2 whose container record is gone or not running, with
#     no child process. Each one is a live runc in the scheduler's runnable set and a task record
#     containerd still holds. Sixteen had accumulated over three days of crashes and stalled
#     recreates; killing them took `docker version` from 27 s to 1.2 s, and cleared the
#     "AlreadyExists: task …" that made `docker start` fail for a container whose old shim was
#     still around.
#
#   * LEFTOVER CONTAINERS — `<12-hex>_<name>`: compose renames the old container while it creates
#     the new one; if the daemon then loses containerd's start event (ttrpc "context deadline
#     exceeded", "broken pipe"), the old one stays renamed (Exited) and the new one sits in Created,
#     and the app is DOWN with nobody noticing. Three batches of recreates did that in one morning.
#     Reported only when the plain name is running again (i.e. the app was recovered and the
#     renamed copy is dead weight); otherwise it is the ONLY copy and this script says so instead.
#
# It never touches a container that is the sole copy of an app, and never restarts anything.
set -euo pipefail
CLEAN=0; [ "${1:-}" = "--clean" ] && CLEAN=1
[ "$(id -u)" = 0 ] || { echo "engine-orphans: run as root on the engine" >&2; exit 2; }
CDIR=/var/lib/docker/containers
found=0

name_of() {   # container id (any prefix) -> /name, running flag
  local d; d="$(ls "${CDIR}" 2>/dev/null | grep "^$1" | head -1)"
  [ -n "${d}" ] || { echo ""; return; }
  python3 - "${CDIR}/${d}/config.v2.json" <<'PY' 2>/dev/null || true
import json, sys
c = json.load(open(sys.argv[1]))
print(c["Name"].strip("/"), "running" if c.get("State", {}).get("Running") else "stopped")
PY
}

echo "== orphan shims (no running container behind them)"
for s in $(pgrep -f containerd-shim-runc-v2 || true); do
  id="$(tr '\0' ' ' < "/proc/${s}/cmdline" 2>/dev/null | grep -oE -- '-id [0-9a-f]{64}' | cut -d' ' -f2)"
  [ -n "${id}" ] || continue
  read -r nm st <<<"$(name_of "${id}")"
  [ "${st:-}" = running ] && continue
  # `|| true`: pgrep exits 1 when there are NO children — which is precisely an orphan — and under
  # `set -e` that ended the script on its first real finding (measured 2026-09-30).
  kids="$( (pgrep -P "${s}" || true) | wc -l)"
  echo "  shim ${s} age=$(ps -o etime= -p "${s}" | tr -d ' ') children=${kids} -> ${nm:-NO-RECORD} ${st:-} ${id:0:12}"
  found=$((found + 1))
  if [ "${CLEAN}" = 1 ] && [ "${kids}" = 0 ]; then
    kill -9 "${s}" 2>/dev/null || true
    rm -rf "/run/containerd/io.containerd.runtime.v2.task/moby/${id}" 2>/dev/null || true
    echo "    killed"
  fi
done

echo "== leftover renamed containers (<hash>_<name>) whose plain name runs again"
for d in "${CDIR}"/*/; do
  read -r nm st <<<"$(name_of "$(basename "${d}")")"
  [[ "${nm:-}" =~ ^[0-9a-f]{12}_(.+)$ ]] || continue
  base="${BASH_REMATCH[1]}"
  plain="$(for e in "${CDIR}"/*/; do read -r n s <<<"$(name_of "$(basename "${e}")")"; [ "${n:-}" = "${base}" ] && echo "${s}" && break; done)"
  if [ "${plain:-}" = running ]; then
    echo "  ${nm} (${st}) — ${base} is running; this copy is dead weight"
    found=$((found + 1))
    if [ "${CLEAN}" = 1 ]; then
      timeout 60 docker rm -f "${nm}" >/dev/null 2>&1 && echo "    removed" || echo "    docker rm failed (daemon busy?) — retry later"
    fi
  else
    echo "  ${nm} (${st}) — ${base} is NOT running: this may be the only copy. Recover it:"
    echo "      docker rename ${nm} ${base} && docker start ${base}"
    found=$((found + 1))
  fi
done

echo "== containers whose last start FAILED (Docker keeps the error; nothing restarts them)"
# Measured 2026-09-30 13:43: bina-ds sat in Created with "port is already allocated" while every
# dashboard showed it merely stopped. A port conflict is the one start error a person must resolve
# outside compose, so it gets its own hint. Report only — starting is a decision, not a cleanup.
for d in "${CDIR}"/*/; do
  line="$(python3 - "${d}config.v2.json" <<'PY' 2>/dev/null || true
import json, sys
c = json.load(open(sys.argv[1])); st = c.get("State", {})
err = (st.get("Error") or "").strip().replace("\n", " ")
if err and not st.get("Running"):
    when = "never started" if str(st.get("StartedAt", "")).startswith("0001") else "ran before, last start failed"
    print(c["Name"].strip("/"), "(%s) --" % when, err[:160])
PY
)"
  [ -n "${line}" ] || continue
  echo "  ${line}"
  found=$((found + 1))
  case "${line}" in
    *"port is already allocated"*|*"address already in use"*)
      echo "      a host port is held by something outside compose: find it with \`ss -ltnp\` on the engine," \
           "free it, then: docker start ${line%% *}" ;;
  esac
done

echo "== engine health"
echo "  shims=$(pgrep -fc containerd-shim-runc-v2 || echo 0) running=$(ls -d /sys/fs/cgroup/system.slice/docker-*.scope 2>/dev/null | wc -l)"
echo "  containerd ttrpc errors, last 5 min: $(journalctl -u containerd --since '5 min ago' --no-pager 2>/dev/null | grep -cE 'context deadline exceeded|inactive stream|broken pipe' || echo '?')"
echo "  load: $(cut -d' ' -f1-3 /proc/loadavg)   cpu pressure: $(awk '/^some/{print $2}' /proc/pressure/cpu 2>/dev/null)"

[ "${found}" = 0 ] && { echo "clean"; exit 0; }
[ "${CLEAN}" = 1 ] && exit 0
echo "engine-orphans: ${found} finding(s) — re-run with --clean to remove what is safe to remove"
exit 1
