#!/usr/bin/env bash
# test-in-guest.sh — install BinaOS-Setup.exe inside the Windows guest and prove the stack came up.
#
#   bash test-in-guest.sh wait      # block until the guest's SSH answers
#   bash test-in-guest.sh push      # copy the installer into the guest
#   bash test-in-guest.sh install   # run it silently and wait
#   bash test-in-guest.sh verify    # stack up? routes answering?
#
# Runs on the Linux HOST and drives the guest over the forwarded SSH port. The guest is reached at
# 127.0.0.1:2222 because run-test-vm.sh publishes it with user-mode networking - there is no bridge,
# so the guest has no address of its own on the LAN.
set -uo pipefail

GUEST_PORT=2222
GUEST_USER=binaos
GUEST_PASS='BinaOS!test1'
SETUP="${SETUP:-/home/shlomy/vm/BinaOS-Setup.exe}"

# sshpass keeps this scriptable without provisioning keys into the guest during OOBE, which would
# mean generating and injecting them through the unattend file for a throwaway VM.
gssh() { sshpass -p "${GUEST_PASS}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -o ConnectTimeout=15 -p "${GUEST_PORT}" "${GUEST_USER}@127.0.0.1" "$@"; }
gscp() { sshpass -p "${GUEST_PASS}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -P "${GUEST_PORT}" "$@"; }

case "${1:-}" in

  wait)
    # Windows setup + OOBE + the first-logon commands take a while on this CPU; report progress
    # rather than sitting silent, so a hang is distinguishable from slowness.
    for i in $(seq 1 120); do
      if timeout 5 bash -c "</dev/tcp/127.0.0.1/${GUEST_PORT}" 2>/dev/null; then
        echo "  t+$((i*30))s: ssh port open"
        if gssh 'echo ok' 2>/dev/null | grep -q ok; then
          echo "GUEST READY after ~$((i*30))s"
          gssh 'ver' 2>/dev/null | tail -2
          exit 0
        fi
      else
        echo "  t+$((i*30))s: still installing"
      fi
      sleep 30
    done
    echo "guest did not become reachable"; exit 1
    ;;

  find)
    # The installer arrives as a mounted disc (run-test-vm.sh attaches payload.iso), so there is
    # nothing to copy. Its drive letter depends on how many volumes Windows enumerated, so it is
    # searched for rather than assumed.
    gssh 'powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | ForEach-Object { $p = Join-Path $_.Root \"BinaOS-Setup.exe\" ; if (Test-Path $p) { \"{0}  {1:N0} bytes\" -f $p, (Get-Item $p).Length } }"'
    ;;

  push)
    # Fallback only, for a guest booted without payload.iso attached. Half an hour through a
    # user-mode network hop, versus instant for a mounted disc.
    [ -f "${SETUP}" ] || { echo "no ${SETUP}"; exit 1; }
    echo "copying $(du -h "${SETUP}" | cut -f1) into the guest (slow - prefer the payload disc)"
    gscp "${SETUP}" "${GUEST_USER}@127.0.0.1:C:/Users/${GUEST_USER}/BinaOS-Setup.exe" || exit 1
    gssh 'powershell -NoProfile -Command "(Get-Item C:\Users\binaos\BinaOS-Setup.exe).Length"'
    ;;

  install)
    # Inno Setup silent switches. /VERYSILENT shows no wizard at all; /SUPPRESSMSGBOXES answers the
    # prompts that would otherwise block forever with nobody at the keyboard; /LOG gives us
    # something to read when it fails.
    echo "running the installer (no wizard, no prompts)"
    # Locate it wherever it is - the mounted payload disc, or C:\Users\binaos if it was pushed.
    gssh 'powershell -NoProfile -Command "$e = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root \"BinaOS-Setup.exe\" } | Where-Object { Test-Path $_ } | Select-Object -First 1; if (-not $e) { $e = \"C:\Users\binaos\BinaOS-Setup.exe\" }; \"running: $e\"; Start-Process -FilePath $e -ArgumentList \"/VERYSILENT\",\"/SUPPRESSMSGBOXES\",\"/NORESTART\",\"/LOG=C:\Users\binaos\binaos-install.log\" -Wait -PassThru | Select-Object -ExpandProperty ExitCode"' 2>&1 | tail -6
    echo "=== installer log tail ==="
    gssh 'powershell -NoProfile -Command "Get-Content C:\Users\binaos\binaos-install.log -Tail 25"' 2>&1 | tail -25
    ;;

  verify)
    echo "=== WSL distros ==="
    gssh 'wsl.exe -l -v' 2>&1 | tr -d '\000' | tail -6
    echo "=== containers inside the distro ==="
    gssh 'wsl.exe -d BinaOS -e docker ps --format "{{.Names}} {{.Status}}"' 2>&1 | tail -20
    echo "=== counts ==="
    gssh 'wsl.exe -d BinaOS -e sh -c "echo running=$(docker ps -q | wc -l) healthy=$(docker ps -q -f health=healthy | wc -l)"' 2>&1 | tail -2
    echo "=== routes, from inside the distro ==="
    # *.localhost does NOT resolve on Windows itself - the OS resolver does not implement RFC 6761 -
    # so the probe runs inside the distro, where it does.
    for h in console apps n8n drive; do
      code=$(gssh "wsl.exe -d BinaOS -e curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'Host: ${h}.localhost' http://127.0.0.1/" 2>/dev/null | tr -d '\r\000')
      printf '  %-20s %s\n' "${h}.localhost" "${code:-no-answer}"
    done
    ;;

  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
