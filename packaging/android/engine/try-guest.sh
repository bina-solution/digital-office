#!/usr/bin/env bash
# try-guest.sh <dir with dgo-guest-arm64.img.xz.part*> — the Android engine's guest booted on a Linux machine as
# the phone would boot it (DGO-1071): QEMU's aarch64 system emulator under TCG (no KVM for an arm64 guest on
# an x86 host, and none for an app on a phone), the same edge forward (127.0.0.1:8080 → the guest's 80), in a
# throwaway container (Docker is the one thing it needs on the host: no sudo, nothing installed there).
# Says how long each stage took — the disk unpacked, the guest's boot, the office's bring-up, the edge's
# first answer — and the console's last line every 10 minutes. Done when bbox run in
# the guest said "up." AND the edge answers (the edge alone cannot tell: sign-in answers 302 for every host
# before the console behind it is ready); failed when bbox came up with problems, the office's service
# fails, QEMU exits, or GUEST_WAIT seconds pass (default 4 h). A first boot every time: the disk is unpacked afresh (checked
# against dgo-guest-arm64.img.xz.sha256 when it is there) unless GUEST_REUSE=1.
# The guest's console is in <dir>/console.log; the disk is <dir>/guest.img (sparse, 24 GB apparent).
# GUEST_DOCKER_ARGS: limits for the container on a host that runs other work (an office: its CPUs, memory).
set -euo pipefail
dir="$(cd "${1:?usage: try-guest.sh <dir with the guest parts>}" && pwd)"
ls "${dir}"/dgo-guest-arm64.img.xz.part* >/dev/null || { echo "try-guest: no dgo-guest-arm64.img.xz.part* in ${dir}" >&2; exit 1; }
# shellcheck disable=SC2086 # GUEST_DOCKER_ARGS is a list of docker run options, split on purpose
docker run --rm --name dgo-try-guest ${GUEST_DOCKER_ARGS:-} -v "${dir}:/g" -e WAIT="${GUEST_WAIT:-14400}" -e CPUS="${GUEST_CPUS:-4}" \
  -e MEM="${GUEST_MEM:-4096}" -e REUSE="${GUEST_REUSE:-}" -e OWNER="$(id -u):$(id -g)" ubuntu:24.04 bash -c '
set -euo pipefail
# PID 1 of the container: no default action for these, so without a trap Ctrl-C would leave QEMU running
trap "exit 130" INT TERM HUP
trap "chown \"${OWNER}\" /g/guest.img /g/console.log 2>/dev/null || true" EXIT
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq qemu-system-arm qemu-efi-aarch64 curl xz-utils >/dev/null
t0=$(date +%s); say() { echo "[$(( $(date +%s) - t0 ))s] $*"; }
# the office service s own lines (bbox, compose: the unit writes to the console as bash[PID]), its last 400 —
# printed on a failure, so the reason is in the job s log and not only in a console.log the runner drops
office_said() {
  echo "-- the machine s network, as its console said it:"
  grep -a -i -E "ci-info|networkd|resolved|networkctl\[|resolvectl\[|netplan|dhcp|enp0s|eth0|network-online|wait-online" /g/console.log | grep -a -v -E "bash\[[0-9]+\]:" \
    | tail -n 80 | tr -d "\r" | sed "s/\x1b\[[0-9;]*m//g" | cut -c1-300
  echo "-- the office service:"
  grep -a -E "bash\[[0-9]+\]:" /g/console.log | tail -n 400 | tr -d "\r" | sed "s/\x1b\[[0-9;]*m//g" | cut -c1-300
}
# after the office service s verdict, the guest reports its containers (dgo-office-report, guest.sh, which
# always ends on "done" or "clean"): up to 5 minutes for that line, so the reason is in office_said and not
# cut off by the kill. Not after a failed dependency: the service never ran, and nor does its report.
reported() {
  local w=0
  grep -aqs "Dependency failed for dgo-office.service" /g/console.log && return 0
  while [ "${w}" -lt 300 ] && kill -0 "${q}" 2>/dev/null && ! grep -aqs -E "dgo-office-report: (done|clean)" /g/console.log; do
    sleep 10; w=$(( w + 10 ))
  done
}
if [ "${REUSE}" = 1 ] && [ -f /g/guest.img ]; then
  say "disk: the one already here (GUEST_REUSE=1 — not a first boot)"
else
  if [ -f /g/dgo-guest-arm64.img.xz.sha256 ]; then
    want="$(cut -d" " -f1 /g/dgo-guest-arm64.img.xz.sha256)"
    got="$(cat /g/dgo-guest-arm64.img.xz.part* | sha256sum | cut -d" " -f1)"
    [ "${want}" = "${got}" ] || { echo "try-guest: the parts do not match dgo-guest-arm64.img.xz.sha256" >&2; exit 1; }
    say "parts: digest OK"
  fi
  rm -f /g/guest.img /g/guest.img.tmp
  cat /g/dgo-guest-arm64.img.xz.part* | xz -dc | dd of=/g/guest.img.tmp bs=1M conv=sparse status=none
  mv /g/guest.img.tmp /g/guest.img
fi
say "disk ready: $(du -h --apparent-size /g/guest.img | cut -f1) apparent, $(du -h /g/guest.img | cut -f1) on disk"
cp /usr/share/AAVMF/AAVMF_VARS.fd /tmp/vars.fd
: > /g/console.log
# werror/rerror=report: a full host disk is an error the guest sees, not a VM paused while this waits
qemu-system-aarch64 -machine virt -accel tcg,thread=multi -cpu max,pauth=off -smp "${CPUS}" -m "${MEM}" -nographic \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd -drive if=pflash,format=raw,file=/tmp/vars.fd \
  -drive if=virtio,format=raw,cache=writeback,discard=unmap,werror=report,rerror=report,file=/g/guest.img \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:8080-:80 -device virtio-net-pci,netdev=n0 > /g/console.log 2>&1 &
q=$!
seen=""; code=""; up=""; edge=""; beat=0
while kill -0 "${q}" 2>/dev/null && [ $(( $(date +%s) - t0 )) -lt "${WAIT}" ]; do
  for mark in "Kernel command line" "login:" "Starting dgo-office.service" "Finished dgo-office.service" \
              "up. check health" "up, with problems"; do
    case "${seen}" in *"|${mark}|"*) continue ;; esac
    if line="$(grep -a -m1 "${mark}" /g/console.log 2>/dev/null)"; then
      say "console: $(printf "%s" "${line}" | tr -d "\r" | sed "s/\x1b\[[0-9;]*m//g" | cut -c1-200)"; seen="${seen}|${mark}|"
      # only a clean "up." is up: bbox exits 0 with problems too (DGO-995), so systemd says Finished then
      case "${mark}" in "up. check health") up=1 ;; esac
    fi
  done
  if grep -aqs "up, with problems" /g/console.log; then
    say "THE OFFICE CAME UP WITH PROBLEMS — what the office service said in the guest:"
    reported; office_said; kill "${q}" 2>/dev/null || true; exit 1
  fi
  if grep -aqs -e "Failed to start dgo-office.service" -e "Dependency failed for dgo-office.service" /g/console.log; then
    say "THE OFFICE FAILED TO START: dgo-office.service failed in the guest — what it said:"
    reported; office_said; tail -n 20 /g/console.log | tr -d "\r"; kill "${q}" 2>/dev/null || true; exit 1
  fi
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: console.localhost:8080" --max-time 10 http://127.0.0.1:8080/ || true)
  case "${code}" in
    200|301|302|303)
      [ -n "${edge}" ] || { say "the edge answers: HTTP ${code} on console.localhost:8080"; edge=1; }
      if [ -n "${up}" ]; then
        say "THE OFFICE IS UP: bbox run said so in the guest, and the edge answers HTTP ${code}"
        # A fresh forward-auth office printed its first-run link (DGO-1090): it must open the form that
        # makes the owner — the phone opens it as its first screen. The code itself stays out of this log.
        link=$(grep -ao "\[forward-auth\] first run: open http://signin.localhost:8080/setup?[^ ]*" /g/console.log | tail -n 1 | sed "s/.* open //" | tr -d "\r")
        if [ -n "${link}" ]; then
          page=$(curl -s -H "Host: signin.localhost:8080" --max-time 30 "http://127.0.0.1:8080/${link#http://signin.localhost:8080/}" || true)
          case "${page}" in
            *name=\"password\"*) say "the first-run link opens the owner form (${link%%code=*}code=…)" ;;
            *) say "THE FIRST-RUN LINK DOES NOT OPEN THE OWNER FORM (${link%%code=*}code=…): $(printf %s "${page}" | head -c 300)"
               kill "${q}" 2>/dev/null || true; exit 1 ;;
          esac
        fi
        kill "${q}" 2>/dev/null || true; exit 0
      fi ;;
  esac
  if [ $(( $(date +%s) - t0 )) -ge $(( beat + 600 )) ]; then
    beat=$(( $(date +%s) - t0 ))
    say "still booting — the console last said: $(tail -n 1 /g/console.log | tr -d "\r" | sed "s/\x1b\[[0-9;]*m//g" | cut -c1-200)"
  fi
  sleep 30 & wait $!
done
if ! kill -0 "${q}" 2>/dev/null; then
  st=0; wait "${q}" || st=$?
  say "QEMU exited (status ${st}) before the office was up; the console log tail:"
else
  say "the office was not up within ${WAIT} s (the edge last answered HTTP ${code:-none}); the console log tail:"
  kill "${q}" 2>/dev/null || true
fi
tail -n 40 /g/console.log | tr -d "\r"
say "what the office service said:"
office_said
exit 1
'
