#!/usr/bin/env bash
# host-power.sh — a laptop that runs an office stays on, stays cool, and comes back by itself (DGO-1750).
#
#   bash scripts/host-power.sh status [--machine]   # what this host does now: sleep, lid, heat, panic, watchdog, wake
#   sudo ./bbox host-power install                  # declare it on the host (the OWNER's act: it is host policy)
#   sudo ./bbox host-power uninstall                # take it off again
#   host-power.sh guard [--once]                    # the heat guard itself — run by its unit, as root
#
# WHY. The Dell (portable-ubuntu, i7-5500U, Ubuntu 26.04) powered off again and again with nothing in its journal:
# its own memory log read 98°C, 100°C and 101°C in the last samples before its three last stops (11-05 12:42Z,
# 11-09 21:50Z, 11-10 09:32Z), at a load of 2–4 with turbo on. The laptop's controller cuts the power before the
# kernel's 105°C trip, so nothing is logged. thermald runs there and binds no zone, so it never acts. A stopgap
# container (privileged, by hand) held it at 57–69°C from 09:45Z; this is the same guard, declared, on the host.
#
# WHAT install DECLARES (every file names this script; uninstall removes exactly these):
# 1. The heat guard: a host unit (dgo-heat-guard.service, Restart=always), started before the engine (the kernel
#    turns turbo back on at every boot, and the containers' start is the hottest minute) and running `guard`:
#    turbo off, and a CPU ceiling (intel_pstate max_perf_pct) that falls as the CPU warms — 75% under 76°C, 55%
#    from 76, 40% from 83, 25% from 88 — read from the CPU's own sensors (coretemp) where there are any.
# 2. Back by itself after a power loss: the guard keeps the clock's wake alarm armed ten minutes ahead, so a
#    machine whose power was cut (the firmware's heat cut-off, a pulled plug) is switched on again where the
#    firmware honours the alarm. A CLEAN stop clears it — a laptop the owner shuts down stays down.
# 3. A frozen or panicked kernel restarts the machine: kernel.panic=10, softlockup_panic=1, hardlockup_panic=1
#    (/etc/sysctl.d), and the chipset's hardware watchdog (iTCO_wdt — Ubuntu blacklists it, so the unit loads it by
#    name at every start) fed by systemd (RuntimeWatchdogSec=30s, RebootWatchdogSec=2min): a hung host is reset.
# 4. It never sleeps by itself: sleep, suspend, hibernate and hybrid-sleep masked; the lid and idleness ignored
#    (a logind drop-in) — on AC, on battery and docked.
# A host with no battery is not a laptop: install refuses there unless HOST_POWER_FORCE=1 (a server has its own
# posture, scripts/ops/host-baseline.sh). Nothing here touches the BIOS; what only the firmware can do (power on
# when AC returns) is the owner's, on DGO-1409.
set -uo pipefail
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
# Every host path is under ROOT: "" on a host; a test points it at a folder shaped like one.
ROOT="${HOST_POWER_ROOT:-}"
UNIT="dgo-heat-guard"
LIB="/usr/local/lib/dgo/host-power.sh"
LOGIND="/etc/systemd/logind.conf.d/90-dgo-laptop.conf"
FILES=(
  "/etc/systemd/system/${UNIT}.service"
  "/etc/sysctl.d/90-dgo-recover.conf"
  "/etc/modules-load.d/dgo-watchdog.conf"
  "/etc/systemd/system.conf.d/90-dgo-watchdog.conf"
  "${LOGIND}"
  "${LIB}"
)
SLEEP_TARGETS="sleep.target suspend.target hibernate.target hybrid-sleep.target"
PSTATE="/sys/devices/system/cpu/intel_pstate"
RTC="/sys/class/rtc/rtc0/wakealarm"
say() { echo "[host-power] $*"; }
die() { echo "[host-power] error: $*" >&2; exit 1; }

# ── the guard ──────────────────────────────────────────────────────────────────────────────────────────────────
# The ceiling for a temperature (°C). The steps are the stopgap's, measured on the Dell: 75°C → 62°C in 20 s.
ceiling() {
  local t="$1"
  if [ "$t" -ge 88 ]; then echo 25
  elif [ "$t" -ge 83 ]; then echo 40
  elif [ "$t" -ge 76 ]; then echo 55
  else echo 75
  fi
}

# The hottest CPU sensor, in whole °C: the coretemp chip's when the host has one (a disk's or a stuck sensor
# would hold the CPU down for nothing), every sensor otherwise. 0 when none can be read — the guard then keeps
# turbo off at 75%, never full speed.
hottest() {
  local t=0 f v d dirs=()
  for d in "${ROOT}"/sys/class/hwmon/hwmon*; do
    [ "$(cat "$d/name" 2>/dev/null)" = coretemp ] && dirs+=("$d")
  done
  [ "${#dirs[@]}" -gt 0 ] || dirs=("${ROOT}"/sys/class/hwmon/hwmon*)
  for d in "${dirs[@]}"; do
    for f in "$d"/temp*_input; do
      [ -r "$f" ] || continue
      v="$(cat "$f" 2>/dev/null)" || continue
      case "$v" in ''|*[!0-9]*) continue ;; esac
      [ "$v" -gt "$t" ] && t="$v"
    done
  done
  echo $((t / 1000))
}

arm_alarm() {   # ten minutes ahead, relative to the clock's own time (right whether it keeps UTC or local time)
  [ -w "${ROOT}${RTC}" ] || return 0
  { echo 0 > "${ROOT}${RTC}"; echo +600 > "${ROOT}${RTC}"; } 2>/dev/null
}

clear_alarm() { [ -w "${ROOT}${RTC}" ] && { echo 0 > "${ROOT}${RTC}"; } 2>/dev/null; return 0; }

guard_step() {   # guard_step <n>: one look; every 20th re-arms the wake alarm and prints a line
  local n="$1" t pct turbo
  t="$(hottest)"
  pct="$(ceiling "$t")"
  { echo 1 > "${ROOT}${PSTATE}/no_turbo"; echo "${pct}" > "${ROOT}${PSTATE}/max_perf_pct"; } 2>/dev/null
  if [ $((n % 20)) -eq 1 ]; then
    arm_alarm
    turbo="$(cat "${ROOT}${PSTATE}/no_turbo" 2>/dev/null)"
    case "${turbo}" in 1) turbo=off ;; 0) turbo=ON ;; *) turbo="not settable here" ;; esac
    echo "$(date -u +%FT%TZ) temp=${t}C max_perf=$(cat "${ROOT}${PSTATE}/max_perf_pct" 2>/dev/null || echo -)% turbo=${turbo}"
  fi
}

guard() {
  [ -d "${ROOT}${PSTATE}" ] || say "no intel_pstate here — the ceiling cannot be set; the wake alarm is still kept"
  # the recovery settings are also files (install); set again here so a host that lost them keeps them
  if [ -z "${ROOT}" ]; then
    sysctl -q -w kernel.panic=10 kernel.softlockup_panic=1 kernel.hardlockup_panic=1 2>/dev/null || true
  fi
  local n=0
  while :; do
    n=$((n + 1))
    guard_step "$n"
    [ "${1:-}" = --once ] && return 0
    sleep "${HOST_POWER_EVERY:-3}"
  done
}

# ── what install writes ────────────────────────────────────────────────────────────────────────────────────────
render() {   # render <path>: the content declared for that file
  case "$1" in
    "/etc/systemd/system/${UNIT}.service") cat <<EOF
# DGO-1750 — written by \`bbox host-power install\` (scripts/host-power.sh); removed by \`bbox host-power uninstall\`.
[Unit]
Description=DGO heat guard: no turbo, a CPU ceiling that falls as the laptop warms, the wake alarm kept
# before the engine: the kernel turns turbo back on at every boot, and the office's start is the hottest minute
Before=docker.service

[Service]
# the hardware watchdog, by name: Ubuntu blacklists iTCO_wdt, so modules-load.d alone does not load it
ExecStartPre=-/sbin/modprobe iTCO_wdt
ExecStart=/bin/bash ${LIB} guard
# a CLEAN stop (shutdown, reboot, uninstall) clears the wake alarm: a laptop the owner shuts down stays down
ExecStopPost=/bin/bash ${LIB} clear-alarm
Restart=always
RestartSec=5
Nice=-5

[Install]
WantedBy=multi-user.target
EOF
    ;;
    /etc/sysctl.d/90-dgo-recover.conf) cat <<'EOF'
# DGO-1750 — a frozen or panicked kernel restarts the machine instead of sitting dead (bbox host-power).
kernel.panic = 10
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
EOF
    ;;
    /etc/modules-load.d/dgo-watchdog.conf) cat <<'EOF'
# DGO-1750 — the chipset's hardware watchdog (bbox host-power). Ubuntu blacklists it, so the heat guard's unit
# also loads it by name at every start; this line is for a distribution that does not.
iTCO_wdt
EOF
    ;;
    /etc/systemd/system.conf.d/90-dgo-watchdog.conf) cat <<'EOF'
# DGO-1750 — systemd feeds the hardware watchdog; a host that stops feeding it is reset (bbox host-power).
[Manager]
RuntimeWatchdogSec=30s
RebootWatchdogSec=2min
EOF
    ;;
    "${LOGIND}") cat <<'EOF'
# DGO-1750 — an office never sleeps by itself: the lid and idleness are ignored (bbox host-power).
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
EOF
    ;;
    "${LIB}") cat "${SELF}" ;;
    *) return 1 ;;
  esac
}

laptop() { ls "${ROOT}"/sys/class/power_supply/BAT* >/dev/null 2>&1; }

CHANGED=()
install_files() {   # writes every declared file under ROOT; records and prints each one that changed
  local f tmp rc=0
  for f in "${FILES[@]}"; do
    mkdir -p "$(dirname "${ROOT}${f}")" || { rc=1; continue; }
    tmp="${ROOT}${f}.dgo-new"
    if ! render "$f" > "$tmp"; then rm -f "$tmp"; rc=1; continue; fi
    if cmp -s "$tmp" "${ROOT}${f}" 2>/dev/null; then rm -f "$tmp"; continue; fi
    if chmod 0644 "$tmp" && mv -f "$tmp" "${ROOT}${f}"; then CHANGED+=("$f"); echo "  wrote ${f}"; else rm -f "$tmp"; rc=1; fi
  done
  return "$rc"
}

changed() { local c; for c in "${CHANGED[@]+"${CHANGED[@]}"}"; do [ "$c" = "$1" ] && return 0; done; return 1; }

install() {
  [ -n "${ROOT}" ] || [ "$(id -u)" = 0 ] || die "this writes host policy — run it with sudo: sudo ./bbox host-power install"
  laptop || [ "${HOST_POWER_FORCE:-}" = 1 ] || die "no battery here: not a laptop (HOST_POWER_FORCE=1 to declare it anyway)"
  [ -d "${ROOT}${PSTATE}" ] || say "no intel_pstate on this host: the heat ceiling cannot be set here (the rest is declared)"
  install_files || die "a file could not be written"
  [ -n "${ROOT}" ] && return 0                     # a test stops at the files
  local t
  for t in ${SLEEP_TARGETS}; do systemctl mask -q "$t" 2>/dev/null; done
  sysctl -q --system >/dev/null 2>&1 || true
  modprobe iTCO_wdt 2>/dev/null || say "iTCO_wdt did not load (no TCO watchdog on this chipset?) — a kernel that panics still restarts"
  systemctl daemon-reload
  if changed /etc/systemd/system.conf.d/90-dgo-watchdog.conf; then
    systemctl daemon-reexec 2>/dev/null || true    # systemd re-reads RuntimeWatchdogSec only on a re-exec
  fi
  if changed "${LOGIND}"; then
    systemctl reload systemd-logind 2>/dev/null || systemctl kill -s HUP systemd-logind 2>/dev/null || true
  fi
  systemctl enable -q "${UNIT}.service" 2>/dev/null
  if changed "${LIB}" || changed "/etc/systemd/system/${UNIT}.service"; then
    systemctl restart "${UNIT}.service" || die "${UNIT}.service did not start: journalctl -u ${UNIT}"
  else
    systemctl start "${UNIT}.service" || die "${UNIT}.service did not start: journalctl -u ${UNIT}"
  fi
  say "installed. Undo: sudo ./bbox host-power uninstall"
  status
}

uninstall() {
  [ -n "${ROOT}" ] || [ "$(id -u)" = 0 ] || die "this removes host policy — run it with sudo: sudo ./bbox host-power uninstall"
  [ -n "${ROOT}" ] || systemctl disable --now "${UNIT}.service" >/dev/null 2>&1 || true
  clear_alarm
  local f
  for f in "${FILES[@]}"; do rm -f "${ROOT}${f}"; done
  [ -n "${ROOT}" ] && return 0
  systemctl daemon-reload
  say "removed; the sleep targets stay masked (unmask them by hand if the machine should sleep again)"
}

# ── status ─────────────────────────────────────────────────────────────────────────────────────────────────────
status() {
  local machine="${1:-}" k v bad=0 masked=0 t wd
  local -a rows=()
  row() { rows+=("$1=$2"); }
  laptop && row laptop yes || row laptop no
  for t in ${SLEEP_TARGETS}; do [ "$(systemctl is-enabled "$t" 2>/dev/null)" = masked ] && masked=$((masked + 1)); done
  row sleep_masked "${masked}/4"
  row lid "$(grep -hs '^HandleLidSwitch=' "${ROOT}"/etc/systemd/logind.conf "${ROOT}"/etc/systemd/logind.conf.d/*.conf | tail -1 | cut -d= -f2)"
  row guard "$(systemctl is-active "${UNIT}.service" 2>/dev/null || true)"
  row temp_c "$(hottest)"
  row no_turbo "$(cat "${ROOT}${PSTATE}/no_turbo" 2>/dev/null || echo -)"
  row max_perf_pct "$(cat "${ROOT}${PSTATE}/max_perf_pct" 2>/dev/null || echo -)"
  row panic "$(cat "${ROOT}/proc/sys/kernel/panic" 2>/dev/null || echo -)"
  row panic_persisted "$([ -f "${ROOT}/etc/sysctl.d/90-dgo-recover.conf" ] && echo yes || echo no)"
  # a watchdog is expected only where one can exist: the module loaded and found no device (an AMD laptop, a
  # firmware that locks the reboot bit) is «none on this host», never a fault that nothing could fix
  if ls "${ROOT}"/dev/watchdog0 >/dev/null 2>&1; then wd=present
  elif [ -d "${ROOT}/sys/module/iTCO_wdt" ]; then wd=none-on-this-host
  elif [ -z "${ROOT}" ] && modinfo -n iTCO_wdt >/dev/null 2>&1; then wd=absent
  else wd=none-on-this-host; fi
  row watchdog "${wd}"
  row watchdog_fed "$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null | sed 's/^$/-/')"
  v="$(cat "${ROOT}${RTC}" 2>/dev/null)"; row wake_alarm "${v:-none}"
  if [ "${machine}" = --machine ]; then printf '%s\n' "${rows[@]}"; return 0; fi
  for k in "${rows[@]}"; do printf '  %-16s %s\n' "${k%%=*}" "${k#*=}"; done
  laptop || { say "not a laptop: nothing is declared here"; return 0; }
  [ "${masked}" = 4 ] || bad=1
  systemctl is-active -q "${UNIT}.service" 2>/dev/null || bad=1
  [ -f "${ROOT}/etc/sysctl.d/90-dgo-recover.conf" ] || bad=1
  [ "${wd}" != absent ] || bad=1
  if [ "${bad}" = 0 ]; then say "this laptop stays on, cool, and comes back by itself"
  else say "not all of it is in place — the owner's act: sudo ./bbox host-power install"; fi
  return "${bad}"
}

case "${1:-status}" in
  status)      shift || true; status "${1:-}" ;;
  guard)       shift; guard "${1:-}" ;;
  clear-alarm) clear_alarm ;;
  install)     install ;;
  uninstall)   uninstall ;;
  render)      render "${2:?render <path>}" ;;
  ceiling)     ceiling "${2:?ceiling <°C>}" ;;
  *) die "usage: host-power.sh status [--machine] | install | uninstall | guard [--once]" ;;
esac
