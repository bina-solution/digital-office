#!/usr/bin/env bash
# test_host_power.sh — scripts/host-power.sh (DGO-1750) against a folder shaped like a laptop's /sys and /etc.
# No root, no systemd, nothing on the real host is read or written: HOST_POWER_ROOT points every path at the folder.
#   bash scripts/test_host_power.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HP="${HERE}/host-power.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fails=0; n=0
check() { n=$((n + 1)); if eval "$2"; then echo "PASS  $1"; else echo "FAIL  $1"; fails=$((fails + 1)); fi; }

# a laptop: two sensors, intel_pstate, a clock, a battery
mkdir -p "$T/sys/class/hwmon/hwmon0" "$T/sys/class/hwmon/hwmon3" "$T/sys/class/hwmon/hwmon7" \
         "$T/sys/devices/system/cpu/intel_pstate" "$T/sys/class/rtc/rtc0" "$T/sys/class/power_supply/BAT0" "$T/proc/sys/kernel"
echo coretemp > "$T/sys/class/hwmon/hwmon0/name"; echo 65000 > "$T/sys/class/hwmon/hwmon0/temp1_input"
echo coretemp > "$T/sys/class/hwmon/hwmon3/name"; echo 84000 > "$T/sys/class/hwmon/hwmon3/temp2_input"
echo nvme > "$T/sys/class/hwmon/hwmon7/name"; echo 95000 > "$T/sys/class/hwmon/hwmon7/temp1_input"   # a hot disk, not the CPU
echo 0 > "$T/sys/devices/system/cpu/intel_pstate/no_turbo"
echo 100 > "$T/sys/devices/system/cpu/intel_pstate/max_perf_pct"
: > "$T/sys/class/rtc/rtc0/wakealarm"
export HOST_POWER_ROOT="$T"

# 1. the ceiling falls with the heat, in the stopgap's measured steps
got="$(for c in 60 75 76 82 83 87 88 101; do bash "$HP" ceiling "$c"; done | paste -sd' ' -)"
check "ceiling 60..101°C = 75 75 55 55 40 40 25 25 (got: $got)" '[ "$got" = "75 75 55 55 40 40 25 25" ]'

# 2. one look of the guard: the hottest CPU sensor (84°C, not the 95°C disk) sets the ceiling, turbo goes off,
#    the wake alarm is armed ten minutes ahead of the clock's own time
line="$(bash "$HP" guard --once)"
check "guard prints its look: $line" '[[ "$line" == *"temp=84C max_perf=40% turbo=off"* ]]'
check "turbo off" '[ "$(cat "$T/sys/devices/system/cpu/intel_pstate/no_turbo")" = 1 ]'
check "max_perf_pct 40 at 84°C (the disk at 95°C is not the CPU)" '[ "$(cat "$T/sys/devices/system/cpu/intel_pstate/max_perf_pct")" = 40 ]'
check "wake alarm armed relative to the clock (+600)" '[ "$(cat "$T/sys/class/rtc/rtc0/wakealarm")" = "+600" ]'
bash "$HP" clear-alarm
check "clear-alarm disarms it" '[ "$(cat "$T/sys/class/rtc/rtc0/wakealarm")" = 0 ]'
# a laptop without intel_pstate: the guard says so once and floods nothing
N="$(mktemp -d)"; mkdir -p "$N/sys/class/hwmon/hwmon0"; echo 70000 > "$N/sys/class/hwmon/hwmon0/temp1_input"
errs="$(HOST_POWER_ROOT="$N" bash "$HP" guard --once 2>&1 >/dev/null)"; rm -rf "$N"
check "no intel_pstate: no error lines" '[ -z "$errs" ]'
echo 61000 > "$T/sys/class/hwmon/hwmon3/temp2_input"
bash "$HP" guard --once >/dev/null
check "cooled to 65°C: back to 75%" '[ "$(cat "$T/sys/devices/system/cpu/intel_pstate/max_perf_pct")" = 75 ]'

# 3. install writes exactly the declared files, once
out1="$(bash "$HP" install 2>&1)"; rc1=$?
check "install on a laptop folder succeeds (rc $rc1)" '[ "$rc1" = 0 ]'
for f in /etc/systemd/system/dgo-heat-guard.service /etc/sysctl.d/90-dgo-recover.conf \
         /etc/modules-load.d/dgo-watchdog.conf /etc/systemd/system.conf.d/90-dgo-watchdog.conf \
         /etc/systemd/logind.conf.d/90-dgo-laptop.conf /usr/local/lib/dgo/host-power.sh; do
  check "wrote $f" '[ -s "$T$f" ]'
done
check "the unit runs the guard from its own copy" 'grep -q "^ExecStart=/bin/bash /usr/local/lib/dgo/host-power.sh guard$" "$T/etc/systemd/system/dgo-heat-guard.service"'
check "the unit restarts always" 'grep -q "^Restart=always$" "$T/etc/systemd/system/dgo-heat-guard.service"'
check "the unit starts before the engine, not after the office" 'grep -q "^Before=docker.service$" "$T/etc/systemd/system/dgo-heat-guard.service" && ! grep -q "^After=multi-user" "$T/etc/systemd/system/dgo-heat-guard.service"'
check "the unit loads the blacklisted watchdog by name" 'grep -q "^ExecStartPre=-/sbin/modprobe iTCO_wdt$" "$T/etc/systemd/system/dgo-heat-guard.service"'
check "a clean stop clears the wake alarm" 'grep -q "^ExecStopPost=/bin/bash /usr/local/lib/dgo/host-power.sh clear-alarm$" "$T/etc/systemd/system/dgo-heat-guard.service"'
check "a panic restarts in 10 s, a soft or hard lockup panics" 'grep -q "^kernel.panic = 10$" "$T/etc/sysctl.d/90-dgo-recover.conf" && grep -q "^kernel.softlockup_panic = 1$" "$T/etc/sysctl.d/90-dgo-recover.conf" && grep -q "^kernel.hardlockup_panic = 1$" "$T/etc/sysctl.d/90-dgo-recover.conf"'
check "the watchdog module loads at boot, systemd feeds it" 'grep -qx "iTCO_wdt" "$T/etc/modules-load.d/dgo-watchdog.conf" && grep -q "^RuntimeWatchdogSec=30s$" "$T/etc/systemd/system.conf.d/90-dgo-watchdog.conf"'
check "the lid and idleness are ignored" 'grep -q "^HandleLidSwitch=ignore$" "$T/etc/systemd/logind.conf.d/90-dgo-laptop.conf" && grep -q "^IdleAction=ignore$" "$T/etc/systemd/logind.conf.d/90-dgo-laptop.conf"'
check "the installed copy is this script" 'cmp -s "$HP" "$T/usr/local/lib/dgo/host-power.sh"'
out2="$(bash "$HP" install 2>&1)"
check "a second install changes nothing" '! grep -q "wrote" <<<"$out2"'

# 4. status reads the folder
st="$(bash "$HP" status --machine)"
check "status: laptop, the hottest sensor (65°C), the recovery file there" 'grep -qx "laptop=yes" <<<"$st" && grep -qx "temp_c=65" <<<"$st" && grep -qx "panic_persisted=yes" <<<"$st"'

# 5. uninstall removes exactly them
bash "$HP" guard --once >/dev/null           # re-arms the alarm
bash "$HP" uninstall >/dev/null 2>&1
check "uninstall removed every declared file" '[ -z "$(find "$T/etc" "$T/usr" -type f 2>/dev/null)" ]'
check "uninstall cleared the wake alarm" '[ "$(cat "$T/sys/class/rtc/rtc0/wakealarm")" = 0 ]'

# 6. no battery: not a laptop — install refuses, unless declared
rm -rf "$T/sys/class/power_supply/BAT0"
bash "$HP" install >/dev/null 2>&1; rc=$?
check "no battery: install refuses (rc $rc)" '[ "$rc" != 0 ] && [ ! -e "$T/etc/sysctl.d/90-dgo-recover.conf" ]'
HOST_POWER_FORCE=1 bash "$HP" install >/dev/null 2>&1; rc=$?
check "HOST_POWER_FORCE=1 declares it anyway (rc $rc)" '[ "$rc" = 0 ] && [ -s "$T/etc/sysctl.d/90-dgo-recover.conf" ]'

echo "host_power: ${n} check(s), $((n - fails)) pass, ${fails} fail"
[ "$fails" = 0 ]
