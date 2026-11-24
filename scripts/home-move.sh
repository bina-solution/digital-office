#!/usr/bin/env bash
# home-move — the DGO folder off Windows' C: and onto WSL's own disk (DGO-2019, the product root of DGO-1999).
#
#   ./bbox home status                      where the folder is, and whether it can hold the office's databases
#   ./bbox home move [--to DIR] [--dry-run]
#
# On Windows the office's folder sits on C: and WSL reaches it through drvfs (9p). A database there breaks, and on
# 2026-11-18 C: answered «Input/output error» to git, to bind mounts and to the branch guard for hours (DGO-1999).
# The office moves ONCE to the distro's own ext4 — `\\wsl.localhost\<distro>\home\<user>\<folder>` from Windows,
# where Explorer, a backup and the Desktop shortcut bbox.cmd makes all reach it:
#   1. refused unless the folder is on drvfs/9p, DIR is on a disk that holds databases and is empty, this runs on
#      the host (never inside a container of the office, which the move restarts), and there is room for a copy —
#      on DIR's disk AND on C:, which that disk is a file on;
#   2. the office stopped (`dc stop`: its containers and volumes are kept);
#   3. the folder copied with tar as root — .git, .env, data/, everything — owners, modes, times and links kept;
#   4. compared: every file's path and sha256, on both sides;
#   5. the new folder made the same office: its .env pins the compose project the old folder ran under (another
#      folder name is another project), its worktrees point at it, and Claude Desktop's memory of the folder follows;
#   6. the office brought up from the new folder (`./bbox run`): every bind follows it (BBOX_REPO_HOST is the
#      folder), every volume is kept, and every store stays HELD on its volume (DGO_DATA_HOLD) — the stores move to
#      data/ at the next `bbox run`, with its own room check against C:;
#   7. only when that run is healthy: the old folder marked (MOVED-TO.txt — its bbox.cmd reads it and hands every
#      command to the new one, and bbox and compose refuse to run there), and the new folder put on the Desktop.
# Cut or failed before 7, the office goes back where it was: exactly the containers that ran, or a run from the old
# folder; a partial copy is removed (before 6) or set aside as <dir>.failed-<time> (from 6). The move's own log is on
# the distro's disk (/var/log/dgo-home-move.log), never on the C: it moves off. Nothing of the old folder is deleted:
# it is the owner's to remove.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
. "${REPO_ROOT}/scripts/lib.sh"

fs_of() { python3 - "$1" <<'PY'
import os, sys
p = os.path.realpath(sys.argv[1] if os.path.exists(sys.argv[1]) else os.path.dirname(sys.argv[1]))
best, kind = "", "?"
for line in open("/proc/self/mountinfo"):
    left, _, right = line.partition(" - ")
    mp = left.split()[4]
    if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
        best, kind = mp, right.split()[0]
print(kind)
PY
}
slow_fs() { case "$1" in 9p|v9fs|drvfs|fuse*|cifs|smb3|nfs|nfs4|virtiofs) return 0 ;; esac; return 1; }
# the Windows path of a folder on this distro's own disk
win_path() { printf '\\\\wsl.localhost\\%s%s' "${WSL_DISTRO_NAME:-Ubuntu}" "$(printf '%s' "$1" | tr '/' '\\')"; }

# the office stopped, listed and started again, and run from a folder; scripts/test_home_move.sh hands a command of its
# own instead of the engine (DGO_HOME_MOVE_DC)
office() {
  if [ -n "${DGO_HOME_MOVE_DC:-}" ]; then ${DGO_HOME_MOVE_DC} "$@"; return; fi
  case "$1" in
    running)     docker ps -q --filter "label=com.docker.compose.project=$(office_project)" | tr '\n' ' ' ;;
    stop-these)  shift; docker stop -t 60 "$@" >/dev/null ;;
    timers)
      # the follow timers (scripts/follow.sh: dgo-follow, dgo-follow-heal), where systemd runs them
      { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; } || return 0
      local t; for t in dgo-follow dgo-follow-heal; do systemctl "$2" "${t}.timer" >/dev/null 2>&1 || true; done ;;
    start-these)
      # oldest first — the order they were made in, so what another joins (dgo-net's network namespace) is up before
      # it — and a second pass for what could not start yet; says what is still down
      shift
      local ids left=""
      ids="$(docker inspect -f '{{.Created}} {{.Id}}' "$@" 2>/dev/null | sort | awk '{print $2}')"
      for c in ${ids}; do docker start "${c}" >/dev/null 2>&1 || left="${left} ${c}"; done
      for c in ${left}; do docker start "${c}" >/dev/null 2>&1 || echo "${c:0:12}"; done ;;
    run-in)      ( cd "$2" && ./bbox run ) ;;
    claude-memory)
      # in Claude Desktop's home (where its sessions keep each folder's memory): <new> → <old>, made once. The home is
      # its volume, or data/bina-claude/home once it moved; never a volume made here by naming one that is not there
      local src="" v; v="$(office_project)_bina_claude_home"
      if docker volume inspect "${v}" >/dev/null 2>&1; then src="${v}"
      elif [ -d "$4/data/bina-claude/home" ]; then src="$4/data/bina-claude/home"
      else return 0; fi
      # the link belongs to the home's own user (1000), or the desktop's start would chown the whole home once over it
      docker run --rm --network none -v "${src}:/c" alpine:3 sh -c \
        'for d in /c/desktop/.claude/projects /c/.claude/projects; do
           [ -d "$d/$1" ] && [ ! -e "$d/$2" ] && ln -s "$1" "$d/$2" && chown -h 1000:1000 "$d/$2"; done; true' sh "$2" "$3" ;;
    desktop-shortcut)
      # a Windows object the distro cannot make itself: through WSL's interop — the window that started the move may
      # be gone with its socket (the move runs detached), so any live one of this distro's (the keepalive anchor's)
      command -v powershell.exe >/dev/null 2>&1 || return 1
      local s ps1; ps1="$(wslpath -w "$2/scripts/windows/home-shortcut.ps1")"
      for s in "${WSL_INTEROP:-}" /run/WSL/*_interop; do
        [ -S "${s}" ] || continue
        WSL_INTEROP="${s}" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${ps1}" \
          -Target "$3" -Name "$(basename "${REPO_ROOT}") (WSL)" >/dev/null 2>&1 && return 0
      done
      return 1 ;;
    follow-busy)
      # a follow cycle under way (a take's own `bbox run` from the OLD folder): the move waits for it, never races it
      { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; } || return 1
      systemctl is-active --quiet dgo-follow.service || systemctl is-active --quiet dgo-follow-heal.service ;;
    *)           ( cd "${REPO_ROOT}" && dcx "$@" ) ;;
  esac
}

sub="${1:-status}"; shift || true
TO=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --to) TO="${2:?--to DIR}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) die "bbox home status | move [--to DIR] [--dry-run]" ;;
  esac
done
kind="${DGO_HOME_MOVE_TEST_FS:-$(fs_of "${REPO_ROOT}")}"     # the test says "9p" for a folder that is not on C:

if [ "${sub}" = status ]; then
  if slow_fs "${kind}"; then
    say "${cy}the DGO folder ${REPO_ROOT} is on ${kind}: it cannot hold the office's databases, so its apps keep their state in volumes (DGO-2019). \`bbox.cmd home move\` puts it on WSL's own disk.${c0}"
  else
    say "the DGO folder ${REPO_ROOT} is on ${kind}: the apps' state lives in its data/ (./bbox data plan)"
  fi
  [ ! -f "${REPO_ROOT}/MOVED-TO.txt" ] || say "${cy}this folder was MOVED — the office runs from $(head -1 "${REPO_ROOT}/MOVED-TO.txt")${c0}"
  exit 0
fi
[ "${sub}" = move ] || die "bbox home status | move [--to DIR] [--dry-run]"
# NOT YET on a real office: the Windows side does not fully follow a moved office — the disk-facts and trim helpers
# still write the old folder's data\power, and the keepalive tasks run the old folder's scripts, which the owner is told
# he may remove (the move's third reading, DGO-2019). Until that lands, `move` runs only in its test.
[ -n "${DGO_HOME_MOVE_DC:-}" ] || [ "${DGO_HOME_MOVE_WINDOWS_SIDE:-}" = ready ] \
  || die "the move is not open yet: the Windows side (keepalive tasks, disk facts and trim) does not follow a moved office — DGO-2019 lands that first"

# ── 1. refusals, before anything moves ─────────────────────────────────────────────────────────────
# a folder already moved is the old copy: moving it again would stop the live office and move a stale tree (H3)
[ ! -f "${REPO_ROOT}/MOVED-TO.txt" ] \
  || die "this folder was moved already — the office runs from $(head -1 "${REPO_ROOT}/MOVED-TO.txt")"
slow_fs "${kind}" || die "the DGO folder is on ${kind}, which holds databases already — nothing to move"
# (a test hands its own stop and start, DGO_HOME_MOVE_DC: no container of an office is stopped then)
[ -n "${DGO_HOME_MOVE_DC:-}" ] || [ ! -f /.dockerenv ] \
  || die "home move restarts the whole office, this container with it: run it on the host — from Windows, \`bbox.cmd home move\`"
[ "$(id -u)" = 0 ] || die "home move copies every owner of the folder: run it as root (bbox.cmd does)"
if [ -z "${TO}" ]; then
  owner_home="$( { getent passwd "$(stat -c %u "${REPO_ROOT}")" || true; } | cut -d: -f6)"
  [ -n "${owner_home}" ] && [ "${owner_home}" != / ] || owner_home=/root
  # an ASCII name: bbox.cmd reads MOVED-TO.txt in the console's code page, where a Hebrew name arrives garbled (L1)
  name="$(basename "${REPO_ROOT}" | LC_ALL=C tr -c 'A-Za-z0-9._-' '-')"
  case "${name}" in *[A-Za-z0-9]*) ;; *) name="$(office_project)" ;; esac
  TO="${owner_home}/${name}"
fi
case "${TO}" in /*) ;; *) die "--to takes an absolute folder" ;; esac
# ASCII only: bbox.cmd reads MOVED-TO.txt in the console's code page, and a `!` is cmd's delayed expansion (L1)
printf '%s' "${TO}" | LC_ALL=C grep -q '^[A-Za-z0-9/._-]*$' \
  || die "--to takes letters, digits and / . _ - only: Windows reads this name back through cmd.exe"
# a follow cycle under way would run `bbox run` from the OLD folder in the middle of the move
! office follow-busy || die "a follow cycle is running (dgo-follow): move when it is done"
# a copy an earlier move left (cut short, or failed its check) is set aside, never moved over, never reused (L3)
if [ -f "${TO}/.dgo-home-move-partial" ] && [ "${DRY}" = 0 ]; then
  mv "${TO}" "${TO}.failed-$(date -u +%Y%m%dT%H%M%SZ)" && say "an earlier move's partial copy was set aside beside ${TO}"
fi
if [ -e "${TO}" ] && [ -n "$(ls -A "${TO}" 2>/dev/null)" ]; then die "${TO} is not empty: the office never moves over something"; fi
# an office that is not up here cannot be judged up there: the move's own run would fail on what already failed (M2)
[ -n "${DGO_HOME_MOVE_DC:-}" ] || [ -n "$(office running)" ] \
  || die "the office is not running from ${REPO_ROOT}: bring it up (bbox.cmd run) and move it then"
mkdir -p "${TO}"
tkind="$(fs_of "${TO}")"
! slow_fs "${tkind}" || die "${TO} is on ${tkind}, which does not hold databases either — choose a folder on the distro's own disk"
need_kb="$( { du -sk "${REPO_ROOT}" 2>/dev/null || true; } | cut -f1)"
[ -n "${need_kb}" ] || { rmdir "${TO}" 2>/dev/null || true; die "the folder could not be measured (a read of C: failed? DGO-1999): nothing moved"; }
want_kb=$(( need_kb + need_kb / 10 + 1048576 ))
free_kb="$(df -Pk "${TO}" | awk 'NR==2 {print $4}')"
[ "${free_kb}" -gt "${want_kb}" ] \
  || { rmdir "${TO}" 2>/dev/null || true; die "the folder is $(( need_kb / 1024 )) MB and ${TO} has $(( free_kb / 1024 )) MB free: no room for the copy"; }
# On WSL the distro's disk is a FILE ON C: (ext4.vhdx): it grows on C: as the copy is written, and `df` of TO reports
# the file's virtual size, not what C: has left. A full C: mid-copy gives the distro's ext4 I/O errors — and that disk
# holds every docker volume too. So C: itself must have the room (the second reader of DGO-2019).
# …and keep the office's own floor on C: after the copy (disk_floor_gb, 20 GiB under WSL: DGO-625 had the VM stopped
# from outside at 2.3 GB free), not a bare gigabyte — the next run's builds and the stores' own copies come after it
# (no /mnt/c — not WSL — is no C: to measure; the test says how full it is)
cfree_kb="${DGO_HOME_MOVE_CFREE_KB:-$( { df -Pk /mnt/c 2>/dev/null || true; } | awk 'NR==2 {print $4}')}"
cwant_kb=$(( need_kb + need_kb / 10 + $(disk_floor_gb) * 1048576 ))
[ -z "${cfree_kb}" ] || [ "${cfree_kb}" -gt "${cwant_kb}" ] \
  || { rmdir "${TO}" 2>/dev/null || true; die "the folder is $(( need_kb / 1024 )) MB and C: has $(( cfree_kb / 1024 )) MB free, which WSL's disk grows on — the copy and $(disk_floor_gb) GB besides: free C: first"; }
say "moving the office: ${REPO_ROOT} (${kind}, $(( need_kb / 1024 )) MB) → ${TO} (${tkind}) = $(win_path "${TO}")"
[ "${DRY}" = 0 ] || { rmdir "${TO}" 2>/dev/null || true; say "(--dry-run: nothing was stopped, copied or written)"; exit 0; }

# DETACHED from the window that asked: closing the CMD window (wsl.exe ends, a hangup), Ctrl-C there or a dropped
# session must never cut the move between the stop and the mark. That window follows this run's log instead (H2).
if [ -z "${DGO_HOME_MOVE_DETACHED:-}" ] && [ -z "${DGO_HOME_MOVE_DC:-}" ]; then
  # on the distro's own disk: never on the C: the move leaves (a failing C: would stop the recovery's first line), and
  # never inside the tree it copies and compares
  log="${DGO_HOME_MOVE_LOG:-/var/log/dgo-home-move.log}"; mkdir -p "$(dirname "${log}")"; : > "${log}"
  DGO_HOME_MOVE_DETACHED=1 setsid nohup bash "${BASH_SOURCE[0]}" move --to "${TO}" >> "${log}" 2>&1 < /dev/null &
  pid=$!
  say "the move runs on its own (pid ${pid}); its log: ${log}. Closing this window does not stop it."
  tail -n +1 --pid="${pid}" -f "${log}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null; exit $?
fi

# exactly the containers that run now come back if the move stops — never `start` of the whole project, which would
# also start what is off on purpose and run the one-shot jobs again
ran="$(office running)"
phase=before
# The recovery runs to its end whatever fails in it (set +e, every line said `|| true`): a recovery that stops at its
# first failed write is an office left stopped.
restart_here() {
  set +e
  say "${cr}the move stopped (above): the office starts again from ${REPO_ROOT}${c0}" || true
  if [ -n "${ran}" ]; then
    down="$(office start-these ${ran})"
    [ -z "${down}" ] || say "${cr}these did not start again: ${down} — \`bbox.cmd run\` brings the whole office up${c0}" || true
  fi
  rm -rf "${TO}"                                  # TO was empty: only this move's partial copy is removed
  office timers start
}
# whatever cuts it (a TERM at a reboot, an error `set -e` stops on): the office goes back to where it was — before
# step 6 by starting what ran, in step 6 by running the office from the old folder (a run in the new one may have
# recreated the containers); after the mark there is nothing to undo
on_cut() {
  local why="$1"
  trap - INT TERM HUP ERR
  set +e
  case "${phase}" in
    stopped) say "${cr}the move was cut (${why}) before the new folder ran${c0}" || true; restart_here ;;
    running|marking)
      say "${cr}the move was cut (${why}) while the new folder ran: the office runs from ${REPO_ROOT} again${c0}" || true
      rollback; office timers start ;;
  esac
  exit 1
}
rollback() {
  # The office back in the old folder. A half-written mark goes first — it would refuse this very run (bbox and compose
  # refuse a moved folder) and send every later command nowhere; when C: will not even let it be removed, the office
  # stays where it runs healthy, the new folder, and that is said (return 2). The run is checked: its disk admission
  # is this move's (C: is smaller by the copy now), and when even it fails, the containers come up from the old folder
  # as they are (M1).
  set +e
  if [ -e "${REPO_ROOT}/MOVED-TO.txt" ]; then
    rm -f "${REPO_ROOT}/MOVED-TO.txt"
    if [ -e "${REPO_ROOT}/MOVED-TO.txt" ]; then
      say "${cr}C: will not let the half-written mark ${REPO_ROOT}/MOVED-TO.txt be removed: the office stays in ${TO}${c0}" || true
      return 2
    fi
  fi
  if DGO_DATA_HOLD=1 BBOX_DISK_ADMITTED=1 office run-in "${REPO_ROOT}"; then return 0; fi
  say "${cr}the office's run from ${REPO_ROOT} failed too: its containers start from it as they are${c0}" || true
  ( cd "${REPO_ROOT}" && dcx up -d --no-build ) || say "${cr}they did not: \`bbox.cmd run\` from ${REPO_ROOT}${c0}" || true
  return 1
}
trap 'on_cut "a signal"' INT TERM HUP
trap 'on_cut "an error"' ERR

# ── 2. the office stopped: containers and volumes kept ─────────────────────────────────────────────
# the follow timers first (a take's own `bbox run`, from the OLD folder): stopped, then asked again whether a cycle
# runs — one a timer started since the check above would race the copy. The new folder's run installs them for
# itself, and a move that goes back starts them again (M7)
office timers stop || true
if office follow-busy; then office timers start || true; die "a follow cycle started (dgo-follow): move when it is done"; fi
phase=stopped
office stop || { restart_here; die "the office did not stop"; }
# …all of it: a container of the project outside the compiled services keeps its bind to the old folder (M4)
still="$(office running)"
[ -z "${still}" ] || office stop-these ${still} || { restart_here; die "the office did not stop"; }

# ── 3. the copy ────────────────────────────────────────────────────────────────────────────────────
# marked as a partial copy until the move is done: a move cut by a reboot leaves it, and the next try sets it aside
: > "${TO}/.dgo-home-move-partial"
# extended attributes too, every namespace (root restores them): Drive keeps each object's content-type in one
# (`user.supabase.*`), and a copy without them serves every file as an untyped download (the data move keeps them too)
if ! tar -C "${REPO_ROOT}" --numeric-owner --xattrs --xattrs-include='*' -cf - . \
     | tar -C "${TO}" --numeric-owner --xattrs --xattrs-include='*' -xpf -; then
  restart_here; die "the copy failed (a read of C: failed? DGO-1999) — nothing else changed"
fi

# ── 4. the compare: every file's path and sha256 ───────────────────────────────────────────────────
sums() { ( cd "$1" && find . -type f ! -path ./.dgo-home-move-partial -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum ); }
a="$(mktemp)"; b="$(mktemp)"
sums "${REPO_ROOT}" > "${a}" || true
sums "${TO}" > "${b}" || true
if ! cmp -s "${a}" "${b}"; then
  diff "${a}" "${b}" | head -5 >&2 || true
  restart_here; die "the copy differs from the folder (above) — it was removed, and the office runs where it was"
fi
say "copied and compared: $(wc -l < "${a}") files, identical"
rm -f "${a}" "${b}"
# …and the stores' extended attributes, which no sha256 sees: listed by the data move's own lister
# (platform/manager/datahome.py XATTRS: path|name|sha256 of the value), both sides, the same
if [ -d "${REPO_ROOT}/data" ]; then
  xl="$(mktemp)"
  # -B: no __pycache__ written into the old folder; -I for the lister, which root runs from /tmp: no /tmp module of
  # anyone's is imported in its place (it needs the standard library alone)
  if ! python3 -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import datahome; sys.stdout.write(datahome.XATTRS)' \
         "${REPO_ROOT}/platform/manager" > "${xl}" \
     || ! xa="$(python3 -I "${xl}" list "$(npath "${REPO_ROOT}")/data")" || ! xb="$(python3 -I "${xl}" list "${TO}/data")"; then
    rm -f "${xl}"; restart_here; die "the stores' extended attributes could not be listed — the copy was removed"
  fi
  rm -f "${xl}"
  if [ "${xa}" != "${xb}" ]; then
    diff <(printf '%s\n' "${xa}") <(printf '%s\n' "${xb}") | head -5 >&2 || true
    restart_here; die "the copy's extended attributes differ (above) — it was removed, and the office runs where it was"
  fi
  [ -z "${xa}" ] || say "…and the stores' $(printf '%s\n' "${xa}" | wc -l) extended attributes, identical"
fi

# ── 5. the new folder: the same office ─────────────────────────────────────────────────────────────
# the same compose project: a folder of another name is another project to compose, and the office's containers and
# volumes would be a stranger's (lib.sh office_project). Pinned in the NEW folder's .env only.
proj="$(office_project)"
grep -qE '^[[:space:]]*COMPOSE_PROJECT_NAME=' "${TO}/.env" 2>/dev/null \
  || printf '\n# the office moved off C: (DGO-2019): the compose project it ran under, whatever this folder is named\nCOMPOSE_PROJECT_NAME=%s\n' \
       "${proj}" >> "${TO}/.env"
# the worktrees inside the copy still point at the old folder, both ways: the repository's record of each
# (.git/worktrees/<w>/gitdir) and the worktree's own .git file. Both are rewritten to the copy's own paths here, by
# hand — `git worktree repair <path>` follows the worktree's .git file, which names the OLD repository, and rewires
# the old one instead (measured in scripts/test_home_move.sh). A worktree outside the folder stays the old one's.
for admin in "${TO}"/.git/worktrees/*/; do
  [ -f "${admin}gitdir" ] || continue
  was="$(cat "${admin}gitdir")"
  case "${was}" in "${REPO_ROOT}"/*) ;; *) continue ;; esac
  now="${TO}${was#"${REPO_ROOT}"}"
  [ -f "${now}" ] || continue
  printf '%s\n' "${now}" > "${admin}gitdir"
  printf 'gitdir: %s\n' "${admin%/}" > "${now}"
done
# Claude Desktop keys a folder's memory by its path (~/.claude/projects/<the path, every character but a letter or a
# digit as ->): the new path gets the old one's, so a session in the new folder starts with what the office learned
key() { printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g'; }
office claude-memory "$(key "${REPO_ROOT}")" "$(key "${TO}")" "${TO}" || true
# data/power is where Windows writes the machine's facts (host.json, the power hold, the disk survey) — through
# \\wsl.localhost, as the distro's default user (1000): its folder is that user's, or every new file there is refused
[ ! -d "${TO}/data/power" ] || chown 1000:1000 "${TO}/data/power" || true

# ── 6. the office, from the new folder ─────────────────────────────────────────────────────────────
# every store stays on its volume in this run (DGO_DATA_HOLD): a run that goes back loses nothing, and the copy of the
# stores into data/ is the next `bbox run`'s, with its own room check (H1, M3)
win="$(win_path "${TO}")"
phase=running
if ! DGO_DATA_HOLD=1 office run-in "${TO}"; then
  trap - INT TERM HUP ERR                          # this branch IS the recovery: the ERR trap would run it twice
  set +e
  say "${cr}the office did not come up healthy from ${TO}: it runs again from ${REPO_ROOT}${c0}" || true
  rollback
  office timers start
  mv "${TO}" "${TO}.failed-$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null
  die "the move stopped after the copy; the copy is set aside beside ${TO}, and the old folder runs the office"
fi

# ── 7. only now: the old folder marked, the new one on the Desktop ─────────────────────────────────
# the mark is what hands bbox.cmd (and bbox) to the new folder: written, read back, and when C: will not take it the
# office goes back to the old folder — a live office in the new one with the old one unmarked is two offices (H3)
mark="$(printf '%s\n%s\nmoved %s by bbox home move (DGO-2019). This folder is the old copy: nothing runs from it, and it is\nyours to remove once the office runs well from the new one.\n' \
  "${TO}" "${win}" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')")"
phase=marking
marked=""
for i in 1 2 3; do
  if [ -n "${DGO_HOME_MOVE_TEST_MARK:-}" ]; then
    # the test's C: that will not take the mark: nothing written, or a truncated file left behind
    [ "${DGO_HOME_MOVE_TEST_MARK}" != truncate ] || printf '%s' "${TO}" > "${REPO_ROOT}/MOVED-TO.txt"
  elif printf '%s\n' "${mark}" > "${REPO_ROOT}/MOVED-TO.txt" 2>/dev/null \
       && [ "$(head -2 "${REPO_ROOT}/MOVED-TO.txt" 2>/dev/null)" = "$(printf '%s\n%s' "${TO}" "${win}")" ]; then
    marked=1; break
  fi
  sleep "${DGO_HOME_MOVE_TEST_SLEEP:-5}"
done
if [ -z "${marked}" ]; then
  trap - INT TERM HUP ERR                          # this branch IS the recovery: the ERR trap would run it twice
  set +e
  say "${cr}the old folder could not be marked (C: did not take MOVED-TO.txt): the office goes back to ${REPO_ROOT}${c0}" || true
  rollback; rc=$?
  office timers start
  [ "${rc}" != 2 ] || die "the office runs from ${TO}, healthy — the old folder's mark is half-written and C: would not let it go: when C: answers, write MOVED-TO.txt there (two lines: ${TO} and ${win}) or remove it"
  die "the move stopped at its mark; the copy at ${TO} is kept — run \`bbox.cmd home move\` again when C: answers"
fi
phase=done
trap - INT TERM HUP ERR
rm -f "${TO}/.dgo-home-move-partial"
# The Windows keepalive tasks stay with the script on C: — a monitor on the disk it watches would be silent exactly
# when WSL will not start (the second reader) — and that script follows MOVED-TO.txt to the new folder.
office desktop-shortcut "${TO}" "${win}" \
  || say "${cy}the Desktop shortcut could not be made (no live Windows interop): open ${win}${c0}"
say "${cg}the office now runs from ${win}${c0}"
