#!/usr/bin/env bash
# test_runner_liveness.sh — runner-liveness.sh tells a runner type whose launcher loop quit from one
# that is resting.
#
#     bash apps/n8n/test_runner_liveness.sh
#
# The 2026-10-26 outage on vps1: both workers' launchers quit their JavaScript loop after a 403 from
# the broker, and for six days the probe answered "OK no runner process" — the healthy resting state
# and the dead one look the same from `ps`. They do not look the same from the broker's sockets, and
# that is what this drives: a fake /proc (cmdline, stat, fd links, net/tcp) shaped like the sidecars
# measured on vps1 on 2026-11-01, a `ps` that lists only the fake runner, a `wget` that plays the
# broker's /healthz, and the probe's own state files in a scratch directory. Each case states the
# shape it reproduces.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="${HERE}/runner-liveness.sh"
# The probe reads these; a caller's own values must not change what is tested.
unset RUNNER_LIVENESS_BROKER_GRACE_SECONDS RUNNER_LIVENESS_GRACE_SECONDS RUNNER_LIVENESS_PROCESS \
      N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT
T="$(mktemp -d)"
trap 'chmod -R u+rwx "${T}" 2>/dev/null; rm -rf "${T}"' EXIT
fails=0
say() { printf '%s  %s\n' "$1" "$2"; }

BROKER_HEX=162F                       # 5679, the broker port in N8N_RUNNERS_TASK_BROKER_URI below
LAUNCHER_ARGV='tini\0--\0/usr/local/bin/task-runner-launcher\0javascript\0python\0'
SHIM_ARGV='ld-linux-x86-64.so.2\0--argv0\0/usr/local/bin/task-runner-launcher\0--preload\0/lib/libgcompat.so.0\0--\0/usr/local/bin/task-runner-launcher\0javascript\0python\0'
RUNNER_ARGV='/usr/local/bin/node\0--disallow-code-generation-from-strings\0/opt/runners/task-runner-javascript/dist/start.js\0'
BOOT=12345                            # PID 1's start time (field 22 of its stat) in this container's life

# build <pid-1 argv> — a proc tree with PID 1, the launcher (pid 7), net/tcp's headers and no `ps` runner
build() {
  chmod -R u+rwx "${T}/proc" 2>/dev/null
  rm -rf "${T}/proc" "${T}/state" "${T}/ps.out"; mkdir -p "${T}/proc/1/fd" "${T}/proc/7/fd" "${T}/proc/net" "${T}/state"
  printf "$1" > "${T}/proc/1/cmdline"
  echo "1 (tini) S 0 1 1 0 -1 4194560 100 0 0 0 0 0 0 0 20 0 1 0 ${BOOT} 1000 10" > "${T}/proc/1/stat"
  printf "${SHIM_ARGV}" > "${T}/proc/7/cmdline"
  echo '  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode' > "${T}/proc/net/tcp"
  echo '  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode' > "${T}/proc/net/tcp6"
  : > "${T}/ps.out"
  BROKER_UP=1
}
# sock <pid> <inode> <state> [port-hex] [tcp|tcp6] — a socket of <pid> to the broker (or to another port)
sock() {
  local fd; fd=$(( $(ls "${T}/proc/$1/fd" | wc -l) + 3 ))
  ln -s "socket:[$2]" "${T}/proc/$1/fd/${fd}"
  if [ "${5:-tcp}" = tcp6 ]; then
    echo "   0: 0000000000000000FFFF0000240012AC:95C6 0000000000000000FFFF0000040012AC:${4:-${BROKER_HEX}} $3 00000000:00000000 02:00000B51 00000000  1000        0 $2 2 0000000000000000 20 4 30 10 -1" >> "${T}/proc/net/tcp6"
  else
    echo "   0: 240012AC:95C6 040012AC:${4:-${BROKER_HEX}} $3 00000000:00000000 02:00000B51 00000000  1000        0 $2 2 0000000000000000 20 4 30 10 -1" >> "${T}/proc/net/tcp"
  fi
}
# runner <pid> — a JS runner process, listed by `ps`, that has burnt CPU
runner() {
  mkdir -p "${T}/proc/$1/fd"
  printf "${RUNNER_ARGV}" > "${T}/proc/$1/cmdline"
  echo "$1 (node) S 7 1 1 0 -1 4194560 100 0 0 0 250 30 0 0 20 0 11 0 100 0 0" > "${T}/proc/$1/stat"
  echo "  $1 {MainThread} /usr/local/bin/node /opt/runners/task-runner-javascript/dist/start.js" >> "${T}/ps.out"
}
# since <seconds> [boot] — the deficit clock started that long ago, in this container's life or another's
since() { echo "$(( $(date +%s) - $1 )) ${2:-${BOOT}}" > "${T}/state/broker"; }
mkdir -p "${T}/bin"
cat > "${T}/bin/ps" <<'SH'
#!/bin/sh
echo "PID   COMMAND"
cat "$RL_TEST_PS"
SH
# The broker's /healthz answers only at the address the probe must ask: a probe that built a wrong URL
# would read every shortfall as "broker down" and never accuse anything.
cat > "${T}/bin/wget" <<'SH'
#!/bin/sh
[ "$*" = "-q -T 2 -O /dev/null http://n8n-worker-1:5679/healthz" ] && [ "$RL_TEST_BROKER_UP" = 1 ]
SH
chmod +x "${T}/bin/ps" "${T}/bin/wget"
printf 'n8n.runner.task.requested\nn8n.runner.response.received\n' > "${T}/n8nEventLog-w1-worker.log"

# run <expect-exit> <expect-substring> <case> — the probe, against the fake tree, with the state in ${T}/state
run() {
  local out code
  out="$(PATH="${T}/bin:${PATH}" RL_TEST_PS="${T}/ps.out" RL_TEST_BROKER_UP="${BROKER_UP}" \
         RUNNER_LIVENESS_PROC="${T}/proc" RUNNER_LIVENESS_STATE="${T}/state/cpu" \
         RUNNER_LIVENESS_BROKER_STATE="${T}/state/broker" RUNNER_LIVENESS_LOG_GLOB="${T}/n8nEventLog-w1-worker*.log" \
         N8N_RUNNERS_TASK_BROKER_URI=http://n8n-worker-1:5679 sh "${PROBE}" 2>&1)"; code=$?
  if [ "${code}" = "$1" ] && case "${out}" in *"$2"*) true ;; *) false ;; esac; then
    say "PASS" "$3"
  else
    say "FAIL" "$3 — exit ${code} (want $1), said: ${out}"; fails=$((fails + 1))
  fi
}
# clock <present|absent> <case> — whether the deficit clock is on disk after the last run
clock() {
  if { [ "$1" = present ] && [ -f "${T}/state/broker" ]; } || { [ "$1" = absent ] && [ ! -f "${T}/state/broker" ]; }; then
    say "PASS" "  ... $2"
  else
    say "FAIL" "  ... $2 (the clock is not $1)"; fails=$((fails + 1))
  fi
}

build "${LAUNCHER_ARGV}"; sock 7 111 01; sock 7 222 01
run 0 "OK no runner process" "idle: both types' launcher sockets held -> resting, not a fault"
clock absent "and no deficit is counted"

build "${LAUNCHER_ARGV}"; sock 7 222 01
run 0 "OK no runner process" "JS loop quit, first probe -> the clock starts, no verdict yet"
clock present "the deficit clock is written"

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 100
run 0 "OK no runner process" "JS loop quit 100s ago -> inside the 300s grace (a handover or a worker restart)"

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 400
run 1 "DISCONNECTED 1 of 2" "JS loop quit 400s ago, no runner process -> the 2026-10-26 shape, caught"

build "${LAUNCHER_ARGV}"; since 400
run 1 "DISCONNECTED 0 of 2" "both loops quit, the broker answering -> caught"

build "${LAUNCHER_ARGV}"; since 400; BROKER_UP=0
run 0 "OK no runner process" "nothing held because the broker is DOWN -> the worker's fault, not this sidecar's"
clock absent "and the clock starts again once it answers"

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 3600 99999
run 0 "OK no runner process" "a clock from before a restart (another PID-1 life) -> the restarted sidecar gets its grace"
clock present "a fresh clock is written"

build "${LAUNCHER_ARGV}"; sock 7 111 01; sock 7 222 01; since 400
run 0 "OK no runner process" "both sockets back -> healthy"
clock absent "the deficit clock is reset"

build "${LAUNCHER_ARGV}"; sock 7 222 01; runner 50; sock 50 333 01; since 400
run 0 "OK running" "a JS runner holds its own socket beside python's launcher -> working"

build "${LAUNCHER_ARGV}"; sock 7 222 01; sock 7 111 06; since 400
run 1 "DISCONNECTED 1 of 2" "a TIME_WAIT socket to the broker is not a held connection"

build "${LAUNCHER_ARGV}"; sock 7 222 01; sock 7 111 01 1631; since 400
run 1 "DISCONNECTED 1 of 2" "a socket to another port (the runner's own health port) is not the broker"

build "${LAUNCHER_ARGV}"; sock 7 222 01; sock 7 111 01 "${BROKER_HEX}" tcp6; since 400
run 0 "OK no runner process" "a broker socket in tcp6 counts"

# One socket and an old clock: a probe that can still read the directory says DISCONNECTED, so this case
# fails loudly instead of passing for the wrong reason. Root reads a mode-000 directory anyway.
if [ "$(id -u)" = 0 ]; then
  say "SKIP" "the launcher's fd directory unreadable — run as root, which reads it anyway"
else
  build "${LAUNCHER_ARGV}"; sock 7 222 01; since 400; chmod 000 "${T}/proc/7/fd"
  run 0 "broker check skipped (blind)" "the launcher's fd directory unreadable -> blind, skipped (fail open), never a verdict"
  clock present "a blind count leaves the clock as it was"
fi

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 400; BROKER_UP=0
run 0 "broker check skipped (broker-down)" "a deficit while the broker does not answer -> skipped, and says why"

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 400; rm -f "${T}/proc/net/tcp" "${T}/proc/net/tcp6"
run 0 "OK no runner process" "no /proc/net/tcp -> the check is skipped (fail open), never a verdict"

build 'sleep\0infinity\0'; sock 7 222 01; since 400
run 0 "OK no runner process" "PID 1 is not the launcher -> types unknown -> skipped (fail open)"

build "${LAUNCHER_ARGV}"; sock 7 222 01; since 400; runner 50
printf 'n8n.runner.task.requested\n' > "${T}/n8nEventLog-w1-worker.log"
run 1 "DISCONNECTED" "a runner process holding no broker socket does not count, and accepted work does not hide a quit loop"

if [ "${fails}" -gt 0 ]; then echo "${fails} case(s) failed"; exit 1; fi
echo "all cases passed"
