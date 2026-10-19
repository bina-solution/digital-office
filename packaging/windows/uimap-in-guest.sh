#!/usr/bin/env bash
# uimap-in-guest.sh — capture a UI map of the stack that BinaOS-Setup.exe installed in the guest.
#
#   bash uimap-in-guest.sh keepalive # register the scheduled task that stops WSL reaping the distro
#   bash uimap-in-guest.sh push      # get the repo into the guest's WSL distro
#   bash uimap-in-guest.sh image     # ship the prebuilt capture image (do NOT let the guest build it)
#   bash uimap-in-guest.sh run       # capture
#   bash uimap-in-guest.sh fetch     # bring the map back to the Linux host
#
# Runs on the Linux HOST and drives the Windows guest over the forwarded ssh port.
#
# WHY THE REPO HAS TO GO INSIDE THE DISTRO
# The capture starts Chromium containers ON the stack's own docker network and points their
# host-resolver at the console container's IP. That only works from the same docker daemon, which
# here is the one inside the BinaOS distro. Probing from the Linux host through the forwarded port
# would reach traefik, but the capture needs container-to-container addressing, not a route.
#
# And the artifact deliberately does not carry bbox or the app sources - stage-control ships the
# runtime tree only, because a customer never screenshots their own platform. So the STACK comes
# from the executable and the MAPPER comes from a repo copy, exactly as on Linux.
set -uo pipefail

# guest-capture.sh sits next to this file and gets shipped into the guest by the `run` subcommand.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GUEST_PORT=2222
GUEST_USER=binaos
GUEST_PASS='BinaOS!test1'
DISTRO=BinaOS
REPO_SRC="${REPO_SRC:-/home/shlomy/binaos-repo}"

gssh() { sshpass -p "${GUEST_PASS}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -o ConnectTimeout=20 -p "${GUEST_PORT}" "${GUEST_USER}@127.0.0.1" "$@"; }
gscp() { sshpass -p "${GUEST_PASS}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -P "${GUEST_PORT}" "$@"; }

case "${1:-}" in

  push)
    [ -d "${REPO_SRC}" ] || { echo "no repo at ${REPO_SRC}"; exit 1; }
    echo "packing the mapper (source only - no images, no git, no node_modules)"
    tar -C "$(dirname "${REPO_SRC}")" -czf /tmp/binaos-repo.tgz \
      --exclude=node_modules --exclude=.git --exclude=dist --exclude=ci-artifacts \
      --exclude='data/*' --exclude='*.run' --exclude='*.iso' --exclude='*.tar.zst' \
      "$(basename "${REPO_SRC}")" || exit 1
    du -h /tmp/binaos-repo.tgz | cut -f1 | sed 's/^/  tarball: /'

    echo "copying into the guest (forwarded ssh - the slow part)"
    gscp /tmp/binaos-repo.tgz "${GUEST_USER}@127.0.0.1:C:/Users/${GUEST_USER}/repo.tgz" || exit 1

    echo "unpacking inside the distro"
    # wslpath turns the Windows path into something the distro can read through /mnt/c.
    gssh "wsl.exe -d ${DISTRO} -e sh -c 'mkdir -p /opt/mapper && tar -xzf \"\$(wslpath -a C:/Users/${GUEST_USER}/repo.tgz)\" -C /opt/mapper --strip-components=1 && ls /opt/mapper | head -5'" 2>&1 | tr -d '\000' | tail -6
    ;;

  image)
    # Ship the ALREADY-BUILT capture image instead of building it in the guest. This is the whole
    # difference between the capture working and not: run_capture.sh rebuilds ui-capture unless
    # UI_CAPTURE_SKIP_BUILD=1, and building Chromium + fonts inside a nested VM alongside 33 running
    # containers blows straight through the 600s build timeout - which surfaces only as
    # "capture produced NO results", with the real cause buried behind a `tail`.
    #
    # The image is identical on every platform, so the host that already ran a capture has it.
    HOST_SOCK="${HOST_SOCK:-unix:///run/binaos-docker.sock}"
    echo "saving ui-capture from the host engine"
    DOCKER_HOST="${HOST_SOCK}" docker save ui-capture:latest | zstd -T0 -3 -o /tmp/ui-capture.tar.zst -f || exit 1
    du -h /tmp/ui-capture.tar.zst | cut -f1 | sed 's/^/  /'
    gscp /tmp/ui-capture.tar.zst "${GUEST_USER}@127.0.0.1:C:/Users/${GUEST_USER}/ui-capture.tar.zst" || exit 1
    gssh "cmd /c wsl.exe -d ${DISTRO} -u root -e sh -c 'zstd -dc /mnt/c/Users/${GUEST_USER}/ui-capture.tar.zst | docker load'" 2>&1 | tr -d '\000' | tail -3
    ;;

  keepalive)
    # install.ps1 registers BinaOS-keepalive itself - this only starts it, and FAILS if it is absent
    # rather than registering one here. A second definition of the keepalive is a second thing to
    # keep in sync, and its absence means install.ps1 did not finish, which is the actual bug to see.
    gssh "powershell -NoProfile -Command \"\$t = Get-ScheduledTask -TaskName BinaOS-keepalive -ErrorAction SilentlyContinue; if (-not \$t) { Write-Host 'ABSENT - install.ps1 did not reach the keepalive step'; exit 1 }; Start-ScheduledTask -TaskName BinaOS-keepalive; Start-Sleep 8; (Get-ScheduledTask -TaskName BinaOS-keepalive).State\"" 2>&1 | tr -d '\r\000' | tail -2
    ;;

  run)
    # Everything runs from a script shipped into the guest, not from arguments. The path here is
    # ssh -> cmd.exe -> wsl.exe -> sh, which is FOUR sets of quoting rules, and Windows OpenSSH
    # runs the remote command through cmd.exe - which does not honour single quotes at all. So
    # `docker ps --format '{{.Names}}'` came back as "' was unexpected at this time." and the
    # capture came back as "Unterminated quoted string", from two different hops. Escaping deeper
    # has no answer that stays correct when the command changes; a file needs no quoting.
    gscp "${HERE}/guest-capture.sh" "${GUEST_USER}@127.0.0.1:C:/Users/${GUEST_USER}/guest-capture.sh" || exit 1
    echo "=== capture (this is the long part, ~15 min) ==="
    gssh "cmd /c wsl.exe -d ${DISTRO} -u root -e sh /mnt/c/Users/${GUEST_USER}/guest-capture.sh ${GUEST_USER}" 2>&1 | tr -d '\000' | tail -12
    ;;

  fetch)
    # `run` already staged the map on the Windows side from inside the distro, where quoting
    # behaves. All that is left here is a copy - no shell on the far end, nothing to escape.
    gscp "${GUEST_USER}@127.0.0.1:C:/Users/${GUEST_USER}/ui-map-windows.png" /home/shlomy/vm/ui-map-windows.png || { echo "no map staged - run: uimap-in-guest.sh run"; exit 1; }
    ls -lh /home/shlomy/vm/ui-map-windows.png
    ;;

  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
