#!/usr/bin/env bash
# test_heavy_ready.sh — the one readiness rule for heavy work (scripts/ops/heavy-ready.sh, DGO-1797 package 6),
# against a fixture machine: its /proc (meminfo, uptime, loadavg, cpuinfo), its /sys thermal zones and the
# desk reading `machine` writes. Needs only bash and awk.
#
#     bash scripts/test_heavy_ready.sh
set -uo pipefail
HERE="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fails=0
NOW=1794350000

machine() {   # machine <avail_mb> <uptime_s> <load1> <threads> <pkg_c|none|broken> <desk: yes|no|null|old|future|zero|none>
  rm -rf "${T}/proc" "${T}/sys" "${T}/desk.json"; mkdir -p "${T}/proc" "${T}/sys/class/thermal/thermal_zone0" "${T}/sys/class/thermal/thermal_zone1"
  printf 'MemTotal:       16000000 kB\nMemAvailable:   %d kB\n' $(( $1 * 1024 )) > "${T}/proc/meminfo"
  printf '%s.00 1000.00\n' "$2" > "${T}/proc/uptime"
  printf '%s 1.00 1.00 1/300 999\n' "$3" > "${T}/proc/loadavg"
  : > "${T}/proc/cpuinfo"; for i in $(seq 1 "$4"); do printf 'processor\t: %d\n\n' $((i - 1)) >> "${T}/proc/cpuinfo"; done
  echo acpitz > "${T}/sys/class/thermal/thermal_zone0/type"; echo 99000 > "${T}/sys/class/thermal/thermal_zone0/temp"   # not the package: never read
  case "$5" in
    none) echo iwlwifi > "${T}/sys/class/thermal/thermal_zone1/type" ;;
    broken) echo x86_pkg_temp > "${T}/sys/class/thermal/thermal_zone1/type"; : > "${T}/sys/class/thermal/thermal_zone1/temp" ;;
    *) echo x86_pkg_temp > "${T}/sys/class/thermal/thermal_zone1/type"; echo $(( $5 * 1000 )) > "${T}/sys/class/thermal/thermal_zone1/temp" ;;
  esac
  case "$6" in
    yes)    printf '{"at": %d, "in_use": true, "idle_s": 4, "how": "gnome"}\n' "${NOW}" > "${T}/desk.json" ;;
    no)     printf '{"at": %d, "in_use": false, "idle_s": 900, "how": "gnome"}\n' "${NOW}" > "${T}/desk.json" ;;
    null)   printf '{"at": %d, "in_use": null, "idle_s": null, "how": "unknown", "why": "AccessDenied"}\n' "${NOW}" > "${T}/desk.json" ;;
    old)    printf '{"at": %d, "in_use": true, "idle_s": 4, "how": "gnome"}\n' $(( NOW - 61 )) > "${T}/desk.json" ;;
    edge)   printf '{"at": %d, "in_use": true, "idle_s": 4, "how": "gnome"}\n' $(( NOW - 60 )) > "${T}/desk.json" ;;
    future) printf '{"at": %d, "in_use": true, "idle_s": 4, "how": "gnome"}\n' $(( NOW + 3600 )) > "${T}/desk.json" ;;
    zero)   printf '{"at": 0%d, "in_use": true, "idle_s": 4, "how": "gnome"}\n' "${NOW}" > "${T}/desk.json" ;;
    none) ;;
  esac
}

env_() { HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}" "$@"; }
why() { ( export HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}"
          # shellcheck source=/dev/null
          . "${HERE}/ops/heavy-ready.sh"; heavy_ready_why "$@" ) 2> "${T}/err"; }
expect() {   # expect <name> <words the reason starts with, or «» for start> <mem> <cpus>
  local got; got="$(why "$3" "$4")"
  if { { [ -z "$2" ] && [ -z "${got}" ]; } || { [ -n "$2" ] && [ "${got#"$2"}" != "${got}" ]; }; } && [ ! -s "${T}/err" ]; then echo "PASS $1"
  else echo "FAIL $1 — wanted «$2», got «${got}»$( [ -s "${T}/err" ] && printf ' stderr: %s' "$(head -c 200 "${T}/err")")"; fails=$((fails + 1)); fi
}

machine 12000 5000 1.5 4 60 no;    expect "a free machine, nobody at the desk: start"           ""          6000 3
machine 5000 5000 1.5 4 60 no;     expect "memory under the job + the desk's reserve: wait"   "memory:"   6000 3
machine 7536 5000 1.5 4 60 no;     expect "…exactly the job + the reserve: start"               ""          6000 3
machine 7535 5000 1.5 4 60 no;     expect "…one MB short: wait"                                 "memory:"   6000 3
machine 600 5000 1.5 4 60 no
got="$( export HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}" HEAVY_RESERVE_MB=0
        . "${HERE}/ops/heavy-ready.sh"; heavy_ready_why 400 1 )"
[ -z "${got}" ] && echo "PASS a recreate's own floor (400 MB, reserve 0) with 600 MB: start" || { echo "FAIL reserve 0: «${got}»"; fails=$((fails + 1)); }
machine 12000 5000 1.5 4 80 no;    expect "the package at 80°C: wait"                           "heat:"     6000 3
machine 12000 5000 1.5 4 79 no;    expect "…at 79°C: start"                                     ""          6000 3
machine 12000 5000 1.5 4 none no;  expect "no package sensor (a VM, a Mac): no hold"            ""          6000 3
machine 12000 5000 1.5 4 broken no; expect "a sensor that reads empty: no hold, no shell error" ""          6000 3
machine 12000 599 1.5 4 60 no;     expect "599 s after a boot: wait"                            "a fresh boot:" 6000 3
machine 12000 600 1.5 4 60 no;     expect "…600 s: start"                                       ""          6000 3
machine 12000 5000 30.5 4 60 no;   expect "load 30.5 on 4 threads: NOT a hold (reported only)"  ""          6000 3
machine 12000 5000 1.5 4 60 yes;   expect "somebody at the desk, a big job: wait"               "the desk:" 6000 3
machine 12000 5000 1.5 4 60 yes;   expect "…a small job (1536 MB, 1 CPU): start"                ""          1536 1
machine 12000 5000 1.5 4 60 yes;   expect "…1537 MB is not small: wait"                         "the desk:" 1537 1
machine 12000 5000 1.5 4 60 yes;   expect "…0.5 CPU is small: start"                            ""          1024 0.5
machine 12000 5000 1.5 4 60 yes;   expect "…1.5 CPU is not small: wait"                         "the desk:" 1024 1.5
machine 12000 5000 1.5 4 60 yes;   expect "…a CPU figure that is not a number is not small"     "the desk:" 1024 two
machine 12000 5000 1.5 4 60 yes;   expect "…a negative CPU figure is not small"                 "the desk:" 1024 -1
machine 12000 5000 1.5 4 60 edge;  expect "a desk reading exactly 60 s old still counts"        "the desk:" 6000 3
machine 12000 5000 1.5 4 60 old;   expect "a desk reading 61 s old is unknown = not in use"     ""          6000 3
machine 12000 5000 1.5 4 60 future; expect "a desk reading stamped an hour ahead is unknown"    ""          6000 3
machine 12000 5000 1.5 4 60 zero;  expect "a leading-zero time is read, not an octal error"     "the desk:" 6000 3
machine 12000 5000 1.5 4 60 null;  expect "the desk could not be read (AppArmor): not in use"   ""          6000 3
machine 12000 5000 1.5 4 60 none;  expect "no desk file at all (no machine app): not in use"    ""          6000 3
machine 12000 5000 1.5 4 60 no;    expect "a memory figure that is not a number is 0"           ""          "6G" 3
machine 12000 5000 1.5 4 60 no;    expect "a leading-zero memory figure is decimal (08000)"      ""          08000 3
machine 2000 5000 9.0 4 90 yes;    expect "several hold: the first one is said (memory)"        "memory:"   6000 3

# no /proc and no /sys at all (a Mac host): nothing holds, nothing is printed on stderr
got="$( export HEAVY_PROC="${T}/nowhere" HEAVY_SYS="${T}/nowhere" HEAVY_DESK="${T}/nowhere/desk.json" HEAVY_NOW="${NOW}"
        . "${HERE}/ops/heavy-ready.sh"; heavy_ready_why 6000 3 )" 2> "${T}/err"
[ -z "${got}" ] && [ ! -s "${T}/err" ] && echo "PASS no /proc, no /sys (a Mac): no hold, no error" || { echo "FAIL no /proc: «${got}» $(cat "${T}/err")"; fails=$((fails + 1)); }

# a FIFO where the desk file should be is not read (a read would hang)
machine 12000 5000 1.5 4 60 none; mkfifo "${T}/desk.json"
got="$( export HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}"
        . "${HERE}/ops/heavy-ready.sh"; heavy_ready_why 6000 3 )"
[ -z "${got}" ] && echo "PASS a FIFO at the desk path: unknown, not a hang" || { echo "FAIL fifo: «${got}»"; fails=$((fails + 1)); }

# under `set -e`, a bare call never ends the caller
machine 12000 5000 1.5 4 60 yes
out="$( set -e; export HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}"
        . "${HERE}/ops/heavy-ready.sh"; heavy_ready_why 6000 3 >/dev/null; echo "still here" )"
[ "${out}" = "still here" ] && echo "PASS set -e: a bare heavy_ready_why returns 0" || { echo "FAIL set -e: «${out}»"; fails=$((fails + 1)); }

# the state line says every fact — the load, and a desk that is unknown with why
machine 12000 5000 30.5 4 60 null
got="$( export HEAVY_PROC="${T}/proc" HEAVY_SYS="${T}/sys" HEAVY_DESK="${T}/desk.json" HEAVY_NOW="${NOW}"
        . "${HERE}/ops/heavy-ready.sh"; heavy_ready_state 6000 3 )"
case "${got}" in *"load 30.5 on 4 threads (reported, never a hold)"*"desk unknown (the desk did not say)"*) echo "PASS the state line: load reported, desk unknown said" ;;
  *) echo "FAIL state line: «${got}»"; fails=$((fails + 1)) ;; esac

# the predicate as a command: heavy_ready answers by its exit code; sourcing it from another directory works
machine 12000 5000 1.5 4 60 no
( cd / && env_ bash -c ". '${HERE}/ops/heavy-ready.sh'; heavy_ready 6000 3" ) \
  && echo "PASS heavy_ready: 0 when it may start (sourced from /)" || { echo "FAIL heavy_ready on a free machine"; fails=$((fails + 1)); }
machine 12000 5000 1.5 4 60 yes
( CDPATH=/tmp env_ bash -c ". '${HERE}/ops/heavy-ready.sh'; heavy_ready 6000 3" ) \
  && { echo "FAIL heavy_ready let a big job past the desk"; fails=$((fails + 1)); } || echo "PASS heavy_ready: 1 when it must wait (with CDPATH set)"

echo
[ "${fails}" = 0 ] && echo "PASS test_heavy_ready" || echo "FAIL test_heavy_ready (${fails} failed)"
exit $((fails > 0))
