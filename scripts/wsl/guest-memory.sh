#!/usr/bin/env bash
# guest-memory.sh — the WSL guest keeps the memory a NEW wsl.exe session needs, from inside the guest (DGO-2188).
#
#     guest-memory.sh tick                     one pass: what the guest's own timer runs every minute
#     guest-memory.sh status                   the last pass, and the timer
#     guest-memory.sh install [--mirror DIR]   as root: this script onto the distro's own disk, the sysctl file, the
#                                              unit and its timer (idempotent; the Windows keepalive runs it). DIR is
#                                              a folder of the HOST each pass copies its state into — the keepalive
#                                              gives its own, as Windows names it (C:\…\AppData\Local\platform-os)
#     guest-memory.sh uninstall                as root: the unit, the timer, the copy and the sysctl file gone
#
# WHY. Every new wsl.exe session — a command from Windows, the keepalive's tick, the disk trim, Windows interop — opens
# an hv_sock channel, and the guest kernel allocates that channel's two ring buffers as ONE contiguous block:
# hv_sock sizes them from the socket's default buffers (net.core.wmem_default + rmem_default = 2 × 212,992 B = 104
# pages), and vmbus_alloc_ring() rounds that up to an order-7 allocation — 512 KB in one piece, GFP_KERNEL. When no
# such block is free the kernel logs «page allocation failure: order:7 … vmbus_alloc_ring ← hvs_probe», the session
# leader's accept4() times out (110), and wsl.exe ends in Wsl/Service/0x8007274c after ~40 s. The office keeps
# running; nothing new can reach it — no command, no trim, no update — until Windows restarts.
#
# MEASURED ON THE HP, kernel log of 2026-11-22 04:46 → 11-24 10:00 (the owner restarted Windows at 10:00):
#   2,252 order-7 allocation failures, 2,227 «accept4 failed 110» — every session of 53 hours — and 15 «Out of memory:
#   Killed process». The remedy of 2026-10-15 was in place the whole time (vm.min_free_kbytes=262144,
#   vm.compaction_proactiveness=50, written by hand into /etc/sysctl.d): a larger free reserve is not a CONTIGUOUS one.
# And 21 minutes after that restart, with everything fresh:
#   - transparent huge pages were `always`: 21,209 huge pages handed out (each one an order-9 block, four of the
#     blocks a session needs) and 10,471 more wanted and not found — anonymous memory of 72 containers takes every
#     large block the kernel puts together, as soon as it exists;
#   - the allocator's own compaction had been tried 16 times and had failed 16 times (compact_stall/compact_fail):
#     for an allocation this large it tries once, lightly, and gives up;
#   - an explicit compaction (/proc/sys/vm/compact_memory) took 0.18 s and raised the free 512 KB blocks 129 → 142.
#
# WHAT A PASS DOES (root, ~10 ms when nothing is wrong):
#   1. transparent huge pages → `madvise`: a program that asks for them still gets them; nothing else drains the
#      large blocks. (DGO_GUEST_THP=keep leaves the setting alone; `always`/`never` set that instead.)
#   2. counts the free blocks of 512 KB and larger in the zones a kernel allocation takes from (/proc/buddyinfo, in
#      512 KB units), and the kernel's allocation failures of the last two minutes.
#   3. under LOW blocks (64 = 32 MB), or after a failed allocation of that size: an explicit compaction.
#   4. still under MIN (16), or failures and still under LOW: the caches are dropped (clean page cache, dentries and
#      inodes: nothing is lost, files are read again) and it compacts once more — at most once in ten minutes, and
#      each drop that did not hold doubles the wait before the next, up to six hours.
#   A count that could not be read is «unknown», never «0»: nothing is done on it, and the state says so.
#   5. writes what it measured and did: /run/dgo/guest-memory.json, a line in the journal when it acted, and — where
#      install was given a mirror — a copy in that folder of the host, which the Windows side reads WITHOUT wsl.exe.
#      That last point is the reason this runs in the guest: the keepalive's own check of this fault asked through a
#      new wsl.exe session, the one thing that cannot be had while the fault is there. The mirror is the keepalive's
#      own folder on C:, never the office's: an office moved onto the guest's disk (`bbox home move`) is read from
#      Windows through the guest, which is the door that is shut.
#
# Not the cause, and not touched: the VM's size, what the office runs, Windows' own memory. A guest that is simply
# full is told (the state's `ok` is false) and still needs less to run in it.
set -uo pipefail

PROC="${GM_PROC:-/proc}"
SYS="${GM_SYS:-/sys}"
RUN_DIR="${GM_RUN:-/run/dgo}"
ETC_DIR="${GM_ETC:-/etc}"
LIB_DIR="${GM_LIB:-/usr/local/lib/dgo}"
UNIT=dgo-guest-memory
ORDER=7                                   # vmbus_alloc_ring's order for an hv_sock channel: 128 pages, 512 KB

# The office's own settings, when a person wrote any (DGO_GUEST_THP, DGO_GUEST_BLOCKS_LOW, …): install never writes
# this file, so a setting outlives every reinstall.
[ -r "${ETC_DIR}/dgo/guest-memory.env" ] && . "${ETC_DIR}/dgo/guest-memory.env"

num() {   # num VALUE DEFAULT — a whole number of 1–12 digits, or the default (a typo never stops the guard)
  case "$1" in ''|*[!0-9]*|?????????????*) printf '%s' "$2" ;; *) printf '%s' "$((10#$1))" ;; esac
}
LOW="$(num "${DGO_GUEST_BLOCKS_LOW:-}" 64)"
MIN="$(num "${DGO_GUEST_BLOCKS_MIN:-}" 16)"
DROP_EVERY="$(num "${DGO_GUEST_DROP_EVERY_S:-}" 600)"
DROP_MAX=21600                            # the longest wait between two cache drops that did not hold: six hours
THP_WANT="${DGO_GUEST_THP:-madvise}"
case "${THP_WANT}" in always|madvise|never|keep) ;; *) THP_WANT=madvise ;; esac
# <the host's folder>/guest-memory.json: install wrote the name into its own one-line file, and where that file is,
# it alone decides (an empty one: no mirror). GM_MIRROR names one only where nothing was installed (a test, a hand
# run) — a settings file can never send an installed guard's copy somewhere the Windows side does not read.
if [ -f "${ETC_DIR}/dgo/guest-memory.mirror" ]; then MIRROR="$(head -1 "${ETC_DIR}/dgo/guest-memory.mirror" 2>/dev/null || true)"
else MIRROR="${GM_MIRROR:-}"; fi

say() { printf '[guest-memory] %s\n' "$*"; }
die() { printf '[guest-memory] %s\n' "$*" >&2; exit 1; }

#: free blocks of ORDER and larger, in ORDER-sized units, in the zones a kernel allocation is given from: not the
#: 16 MB DMA zone (the lowmem reserve keeps it out) and not a Movable zone (GFP_KERNEL is never served there). A
#: buddyinfo row is «Node N, zone NAME c0 c1 … c10»: order k is field 5+k. Prints NOTHING when no such row was read
#: — «could not tell» is never «0 blocks», which is the reading that drops the caches.
blocks() {
  awk -v o="${ORDER}" '
    $3 == "zone" && $4 != "DMA" && $4 != "Movable" && NF >= 5 + o { seen = 1; for (i = 5 + o; i <= NF; i++) n += $i * 2 ^ (i - 5 - o) }
    END { if (seen) printf "%d\n", n + 0 }' "${PROC}/buddyinfo" 2>/dev/null || true
}

#: the kernel's failed allocations of ORDER and larger in the last two minutes — the size a session needs, not any
#: failure (a small atomic one says nothing about contiguous memory). GM_FAILS answers for it under test.
recent_fails() {
  if [ -n "${GM_FAILS:-}" ]; then num "${GM_FAILS}" 0; return; fi
  command -v journalctl >/dev/null 2>&1 || { echo 0; return; }
  local n
  n="$(timeout 10 journalctl -k -q --since '-2 min' --no-pager 2>/dev/null \
       | grep -c -E 'page allocation failure: order:([7-9]|1[0-9])\b')" || true
  num "${n}" 0
}

thp_file() { printf '%s' "${SYS}/kernel/mm/transparent_hugepage/enabled"; }
thp_now() { sed -n 's/.*\[\([a-z]*\)\].*/\1/p' "$(thp_file)" 2>/dev/null; }

compact() { echo 1 > "${PROC}/sys/vm/compact_memory" 2>/dev/null; }

#: the last cache drop, «<when> <the wait before the next one>», or «0 <the first wait>» when there was none
dropped() {
  local when wait
  read -r when wait < "${RUN_DIR}/guest-memory.dropped" 2>/dev/null || true
  printf '%s %s\n' "$(num "${when:-}" 0)" "$(num "${wait:-}" "${DROP_EVERY}")"
}

cmd_tick() {
  local now before after fails thp acted="" ok=true why="" bad=0 when wait
  now="$(date +%s)"
  [ -r "${PROC}/buddyinfo" ] || die "no ${PROC}/buddyinfo here"
  mkdir -p "${RUN_DIR}" 2>/dev/null || true

  thp="$(thp_now)"
  if [ "${THP_WANT}" != keep ] && [ -n "${thp}" ] && [ "${thp}" != "${THP_WANT}" ]; then
    if echo "${THP_WANT}" > "$(thp_file)" 2>/dev/null; then acted="thp ${thp}→${THP_WANT}"; thp="$(thp_now)"; fi
  fi

  before="$(blocks)"; fails="$(recent_fails)"
  case "${before}" in
    ''|*[!0-9]*)
      # the count could not be read: nothing is done on a reading that is no reading, and it is said
      before=-1; after=-1; ok=false; why="${PROC}/buddyinfo gave no zone row to count: nothing was done on it" ;;
    *)
      after="${before}"
      if [ "${before}" -lt "${LOW}" ] || [ "${fails}" -gt 0 ]; then
        if compact; then acted="${acted}${acted:+, }compacted"; fi
        after="$(num "$(blocks)" "${before}")"
        if [ "${after}" -lt "${MIN}" ] || { [ "${fails}" -gt 0 ] && [ "${after}" -lt "${LOW}" ]; }; then
          # THE LAST RESORT, AND IT IS RATIONED. The caches are dropped only when the time of this drop could be
          # written down FIRST — a guard that cannot remember its last drop would drop every minute for ever — and
          # every drop that did not hold doubles the wait before the next (ten minutes, twenty … six hours): a guest
          # that is simply full gets told, not flushed 144 times a day. A pass that finds the blocks back resets it.
          read -r when wait <<<"$(dropped)"
          if [ $((now - when)) -ge "${wait}" ]; then
            local next=$((wait * 2)); [ "${next}" -le "${DROP_MAX}" ] || next="${DROP_MAX}"
            [ "${when}" != 0 ] || next="${DROP_EVERY}"            # the first drop: the next may come after the first wait
            if printf '%s %s\n' "${now}" "${next}" > "${RUN_DIR}/guest-memory.dropped" 2>/dev/null \
               && echo 3 > "${PROC}/sys/vm/drop_caches" 2>/dev/null; then
              compact || true
              after="$(num "$(blocks)" "${after}")"; acted="${acted}${acted:+, }dropped caches and compacted again"
            fi
          fi
        fi
      elif [ -e "${RUN_DIR}/guest-memory.dropped" ]; then
        read -r when wait <<<"$(dropped)"                         # the blocks are back: the next drop waits the first wait
        [ "${wait}" = "${DROP_EVERY}" ] || printf '%s %s\n' "${when}" "${DROP_EVERY}" > "${RUN_DIR}/guest-memory.dropped" 2>/dev/null || true
      fi
      if [ "${after}" -lt "${MIN}" ]; then ok=false; why="only ${after} free 512 KB block(s) (under ${MIN}): a new wsl.exe session may not get in"
      elif [ "${fails}" -gt 0 ]; then ok=false; why="the kernel failed ${fails} allocation(s) of 512 KB or more in the last 2 min"; fi ;;
  esac

  # how many passes in a row were not ok: one bad minute the guard repaired is not an alarm, three are (the reader of
  # the state decides; here it is only counted)
  if [ "${ok}" = true ]; then rm -f "${RUN_DIR}/guest-memory.bad" 2>/dev/null
  else bad=$(( $(num "$(cat "${RUN_DIR}/guest-memory.bad" 2>/dev/null)" 0) + 1 )); printf '%s\n' "${bad}" > "${RUN_DIR}/guest-memory.bad" 2>/dev/null || true; fi

  local doc tmp="${RUN_DIR}/guest-memory.json.$$"
  doc="$(printf '{"at":%s,"ok":%s,"bad_passes":%s,"blocks":%s,"blocks_before":%s,"low":%s,"min":%s,"fails_2m":%s,"thp":"%s","acted":"%s","why":"%s"}' \
    "${now}" "${ok}" "${bad}" "${after}" "${before}" "${LOW}" "${MIN}" "${fails}" "${thp:-?}" "${acted}" "${why}")"
  { printf '%s\n' "${doc}" > "${tmp}" && mv -f "${tmp}" "${RUN_DIR}/guest-memory.json"; } 2>/dev/null || rm -f "${tmp}" 2>/dev/null
  # the copy for the side that cannot ask the guest. EVERY touch of the host's folder is inside the bound — the
  # look at it too: a mount that hangs (C: on 2026-11-20) must never hold a pass, and with it every pass after.
  if [ -n "${MIRROR}" ]; then
    timeout 5 sh -c '[ -d "$(dirname "$2")" ] && printf "%s\n" "$1" > "$2.tmp" && mv -f "$2.tmp" "$2"' _ "${doc}" "${MIRROR}" 2>/dev/null || true
  fi
  if [ -n "${acted}" ] || [ "${ok}" != true ]; then
    local line="blocks ${before}→${after} (low ${LOW}, min ${MIN}), ${fails} failure(s) in 2 min${acted:+; ${acted}}${why:+; ${why}}"
    command -v logger >/dev/null 2>&1 && [ -z "${GM_PROC:-}" ] && logger -t "${UNIT}" -- "${line}" 2>/dev/null
    say "${line}"
  fi
  return 0
}

cmd_status() {
  if [ -r "${RUN_DIR}/guest-memory.json" ]; then cat "${RUN_DIR}/guest-memory.json"; else say "no pass recorded yet (${RUN_DIR}/guest-memory.json)"; fi
  say "now: $(blocks) free 512 KB block(s); huge pages: $(thp_now)"
  command -v systemctl >/dev/null 2>&1 && systemctl is-active "${UNIT}.timer" 2>/dev/null | sed 's/^/[guest-memory] timer: /'
  return 0
}

is_wsl() { grep -qi microsoft "${PROC}/sys/kernel/osrelease" 2>/dev/null; }

cmd_install() {
  local mirror="" force=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --mirror) [ $# -ge 2 ] || die "install: --mirror names a folder"; mirror="$2"; shift 2 ;;
      --force) force=1; shift ;;
      *) die "install: unknown argument $1" ;;
    esac
  done
  [ "$(id -u)" = 0 ] || die "install runs as root (from Windows: wsl.exe -u root -e bash $0 install)"
  [ "${force}" = 1 ] || is_wsl || die "this is not a WSL guest: nothing here opens hv_sock channels (--force installs anyway)"
  command -v systemctl >/dev/null 2>&1 && [ -d "${GM_SYSTEMD_RUN:-/run/systemd/system}" ] \
    || die "the guest runs no systemd (/etc/wsl.conf [boot] systemd=true): there is no timer to install"
  # the host's folder as Windows names it (the keepalive knows no other name) is turned into this guest's path
  local given="${mirror}"
  case "${mirror}" in
    [A-Za-z]:[\\/]*|\\\\*) mirror="$(wslpath -a "${mirror}" 2>/dev/null)" && [ -n "${mirror}" ] \
                             || die "install: «${given}» cannot be turned into a path of this guest (wslpath)" ;;
  esac
  local self; self="$(readlink -f "${BASH_SOURCE[0]}")"
  mkdir -p "${LIB_DIR}" "${ETC_DIR}/dgo" "${ETC_DIR}/sysctl.d" "${ETC_DIR}/systemd/system" || die "cannot create ${LIB_DIR}"
  # onto the distro's own disk: a guard read from the office's folder would stop with that folder's mount
  install -m 0755 "${self}" "${LIB_DIR}/guest-memory.sh" || die "cannot copy the guard to ${LIB_DIR}"
  # the mirror's name, in a file of its own (guest-memory.env is the office's settings: never written here). An
  # install with no mirror says so: the passes to come copy nowhere, an earlier install's folder is not kept.
  if [ -n "${mirror}" ]; then
    printf '%s\n' "${mirror%/}/guest-memory.json" > "${ETC_DIR}/dgo/guest-memory.mirror"
  else
    : > "${ETC_DIR}/dgo/guest-memory.mirror"
  fi
  # the free reserve: a fortieth of the guest's memory, never more than the 256 MB the HP's 10 GB guest was given
  # (DGO-625) and never under 64 MB — the same number on a 4 GB guest would be a sixteenth of it
  local reserve
  reserve="$(awk '/^MemTotal:/ { kb = int($2 / 40); if (kb > 262144) kb = 262144; if (kb < 65536) kb = 65536; print kb }' "${PROC}/meminfo" 2>/dev/null)"
  reserve="$(num "${reserve}" 262144)"
  cat > "${ETC_DIR}/sysctl.d/90-dgo-wsl-hvsock.conf" <<EOF
# Written by scripts/wsl/guest-memory.sh (DGO-625, DGO-2188). A new wsl.exe session needs 512 KB of contiguous
# memory in the guest (vmbus_alloc_ring, order 7). A reserve of free memory and a kernel that compacts on its own
# keep the guard's work small; the guard itself (dgo-guest-memory.timer) is what holds the blocks.
vm.min_free_kbytes = ${reserve}
vm.compaction_proactiveness = 50
EOF
  sysctl -q -p "${ETC_DIR}/sysctl.d/90-dgo-wsl-hvsock.conf" >/dev/null 2>&1 || true
  # TimeoutStartSec: a oneshot has no limit of its own, and a pass that never ends is a timer that never fires again
  cat > "${ETC_DIR}/systemd/system/${UNIT}.service" <<EOF
[Unit]
Description=DGO: keep the contiguous memory a new wsl.exe session needs (scripts/wsl/guest-memory.sh)

[Service]
Type=oneshot
ExecStart=${LIB_DIR}/guest-memory.sh tick
TimeoutStartSec=45s
Nice=-5
EOF
  cat > "${ETC_DIR}/systemd/system/${UNIT}.timer" <<EOF
[Unit]
Description=DGO: one pass of the guest memory guard every minute

[Timer]
OnBootSec=20s
OnUnitActiveSec=60s
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload || die "systemctl daemon-reload failed"
  systemctl enable --now "${UNIT}.timer" >/dev/null 2>&1 || die "the timer did not start"
  systemctl start "${UNIT}.service" >/dev/null 2>&1 || true      # one pass now: the state file exists from here on
  # what is installed, in one line the Windows side compares with what it would install: the guard's own sha256,
  # and the sha256 of the mirror's folder exactly as it was given (hex on both sides: a folder named in Hebrew
  # crosses wsl.exe's console in whatever encoding it has that day). Written last: a stamp means every step above
  # was done.
  printf '%s %s\n' "$(sha256sum "${LIB_DIR}/guest-memory.sh" | cut -c1-64)" "$(printf '%s' "${given}" | sha256sum | cut -c1-64)" \
    > "${ETC_DIR}/dgo/guest-memory.stamp"
  local where=""; [ -z "${mirror}" ] || where=", each pass copied to ${mirror%/}/guest-memory.json"
  say "installed: ${LIB_DIR}/guest-memory.sh, ${UNIT}.timer (every minute)${where}"
}

cmd_uninstall() {
  [ "$(id -u)" = 0 ] || die "uninstall runs as root"
  systemctl disable --now "${UNIT}.timer" >/dev/null 2>&1 || true
  rm -f "${ETC_DIR}/systemd/system/${UNIT}.service" "${ETC_DIR}/systemd/system/${UNIT}.timer" \
        "${ETC_DIR}/sysctl.d/90-dgo-wsl-hvsock.conf" "${ETC_DIR}/dgo/guest-memory.mirror" \
        "${ETC_DIR}/dgo/guest-memory.stamp" "${LIB_DIR}/guest-memory.sh"
  systemctl daemon-reload >/dev/null 2>&1 || true
  say "removed (the running kernel keeps its settings until the guest restarts)"
}

case "${1:-}" in
  tick) cmd_tick ;;
  status) cmd_status ;;
  install) shift; cmd_install "$@" ;;
  uninstall) cmd_uninstall ;;
  *) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
