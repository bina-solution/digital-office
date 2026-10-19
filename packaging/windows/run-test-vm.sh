#!/usr/bin/env bash
# run-test-vm.sh — build and boot an unattended Windows 10 guest for testing BinaOS-Setup.exe.
#
#   bash run-test-vm.sh unattend   # build the autounattend ISO
#   bash run-test-vm.sh disk       # create the guest disk
#   bash run-test-vm.sh boot       # start the VM (installs Windows with no interaction)
#   bash run-test-vm.sh status     # is it up, is SSH answering
#   bash run-test-vm.sh stop
#
# The guest reaches the host over user-mode networking, and the host reaches the guest through three
# forwarded ports: 2222 -> 22 (ssh), 8090 -> 80 (the platform's traefik) and 13389 -> 3389 (rdp, for
# looking at it when something is wrong). No bridge, no root networking, nothing to clean up.
#
# IDE + e1000 rather than virtio, deliberately: Windows 10 has in-box drivers for both, so setup
# never stops to ask for a driver disk. virtio would be faster and would also make this need a human.
#
# SeaBIOS rather than OVMF - see the comment in `boot`. UEFI could not read the install DVD at all.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VMDIR="${VMDIR:-/home/shlomy/vm}"
DISK="${VMDIR}/binaos-win10.qcow2"
ISO="${VMDIR}/win10.iso"
UNATTEND="${VMDIR}/unattend.iso"
DISK_GB="${DISK_GB:-64}"
RAM_MB="${RAM_MB:-6144}"
CPUS="${CPUS:-4}"
SSH_PORT=2222
RDP_PORT=13389
# The guest's traefik, so routes can be probed from the Linux host without going through the guest.
# User-mode networking gives the guest no address of its own on the LAN, so anything we want to
# reach has to be forwarded explicitly.
#
# 8090 rather than 8080, and the reason is worth keeping: a BinaOS install on the SAME host that has
# been moved off :80 by BINAOS_PORT_OFFSET=8000 lands on :8080 - so the obvious choice for "http,
# but not 80" collides with it, and qemu refuses to start with
#   Could not set up host forwarding rule 'tcp::8080-:80'
# Overridable, because the next person's host will have its own occupied ports.
HTTP_PORT="${HTTP_PORT:-8090}"

die() { echo "run-test-vm: $*" >&2; exit 1; }
cd "${VMDIR}" 2>/dev/null || die "no ${VMDIR}"

case "${1:-}" in

  unattend)
    # Windows Setup reads autounattend.xml from the ROOT of any attached optical media.
    rm -rf "${VMDIR}/unattend-root"; mkdir -p "${VMDIR}/unattend-root"
    cp "${HERE}/autounattend.xml" "${VMDIR}/unattend-root/autounattend.xml" 2>/dev/null \
      || cp "${VMDIR}/autounattend.xml" "${VMDIR}/unattend-root/autounattend.xml" \
      || die "autounattend.xml not found"
    # -J -R: Joliet + Rock Ridge, so the filename survives as `autounattend.xml` rather than being
    # truncated to 8.3 by plain ISO9660 - which Setup would then not find.
    xorriso -as mkisofs -J -R -V UNATTEND -o "${UNATTEND}" "${VMDIR}/unattend-root" 2>&1 | tail -2
    ls -lh "${UNATTEND}"
    ;;

  disk)
    [ -f "${DISK}" ] && { echo "disk already exists: ${DISK}"; exit 0; }
    qemu-img create -f qcow2 "${DISK}" "${DISK_GB}G"
    ;;

  boot)
    [ -f "${ISO}" ]      || die "no ${ISO}"
    [ -f "${UNATTEND}" ] || die "no ${UNATTEND} - run: $0 unattend"
    [ -f "${DISK}" ]     || die "no ${DISK} - run: $0 disk"
    [ -e /dev/kvm ]      || die "no /dev/kvm"

    # SeaBIOS and an MBR disk, NOT OVMF/UEFI. OVMF could not read the install DVD at all:
    #   BdsDxe: failed to start Boot0002 "UEFI QEMU DVD-ROM" ... Sata(0x1,0xFFFF,0x0): Time out
    #   >>Start PXE over IPv4.
    # The media is fine: it loop-mounts, carries efi/boot/bootx64.efi and a 4.9 GB
    # sources/install.wim, and detaching the other CDs changed nothing - so it is OVMF's AHCI
    # CD-ROM path timing out on a 5.7 GB image. Legacy BIOS has none of that, Windows 10 installs
    # identically either way, and WSL2 does not care which firmware booted the machine.

    # EXPLICIT bootindex, not `-boot order=d`. "order=d" means "the first CD-ROM", and the first one
    # the firmware enumerates here is the tiny unattend disc on the primary slave - which is not
    # bootable, so the guest sat at a black screen with a cursor and never touched the disk. Naming
    # the install DVD bootindex=1 removes the guesswork.
    #
    # The installer travels as a THIRD optical disc rather than being pushed over the forwarded ssh
    # port afterwards. Copying 2.1 GB through a user-mode network hop takes about half an hour and
    # is the single most fragile step in the whole test; mounting it is instant and cannot half-
    # transfer. The guest sees it as a normal drive, so nothing about the installer changes.
    PAYLOAD_ARGS=""
    if [ -f "${VMDIR}/payload.iso" ]; then
      PAYLOAD_ARGS="-drive id=cd2,file=${VMDIR}/payload.iso,if=none,media=cdrom,readonly=on -device ide-cd,drive=cd2,bus=ahci.3"
      echo "attaching payload.iso ($(du -h "${VMDIR}/payload.iso" | cut -f1)) as a third disc"
    fi

    # q35 + AHCI + SeaBIOS. This exact combination is the ONLY one of the four that boots this
    # media, and the two failures looked nothing alike:
    #
    #   OVMF  + AHCI  -> "failed to start Boot0002 UEFI QEMU DVD-ROM ... Time out", then PXE
    #   SeaBIOS + IDE -> "Booting from 0000:7c00" and then a bare cursor forever, disk never touched
    #   SeaBIOS + AHCI -> Windows Setup, 1024x768, disk being written        <- this one
    #
    # It is not the host and not the media: a 63 MB Alpine ISO boots fine over legacy IDE on this
    # same machine, and the Windows ISO loop-mounts with a valid BIOS El Torito entry and a 4.9 GB
    # install.wim. Windows' loader simply does not come up over QEMU's legacy IDE CD here, and OVMF
    # cannot read the disc at all. Do not "simplify" this back to -machine pc.
    echo "booting; ssh :${SSH_PORT}, http :${HTTP_PORT}, rdp :${RDP_PORT}, vnc :1"
    setsid --fork qemu-system-x86_64 \
      -name binaos-win10 \
      -machine q35,accel=kvm \
      -cpu host \
      -smp "${CPUS}" \
      -m "${RAM_MB}" \
      -device ahci,id=ahci \
      -drive id=hd,file="${DISK}",if=none,format=qcow2,cache=writeback,discard=unmap \
      -device ide-hd,drive=hd,bus=ahci.0,bootindex=2 \
      -drive id=cd0,file="${ISO}",if=none,media=cdrom,readonly=on \
      -device ide-cd,drive=cd0,bus=ahci.1,bootindex=1 \
      -drive id=cd1,file="${UNATTEND}",if=none,media=cdrom,readonly=on \
      -device ide-cd,drive=cd1,bus=ahci.2 \
      ${PAYLOAD_ARGS} \
      -netdev "user,id=n0,hostfwd=tcp::${SSH_PORT}-:22,hostfwd=tcp::${RDP_PORT}-:3389,hostfwd=tcp::${HTTP_PORT}-:80" \
      -device e1000,netdev=n0 \
      -vga std -display none -vnc :1 \
      -monitor "unix:${VMDIR}/monitor.sock,server,nowait" \
      -debugcon "file:${VMDIR}/bios.log" -global isa-debugcon.iobase=0x402 \
      -boot menu=off \
      > "${VMDIR}/qemu.log" 2>&1 < /dev/null
    sleep 3
    pgrep -af "qemu-system-x86_64 -name binaos-win10" | head -1
    ;;

  status)
    if pgrep -f "qemu-system-x86_64 -name binaos-win10" >/dev/null; then
      echo "vm: running"
    else
      echo "vm: not running"; exit 1
    fi
    # Read the BANNER, do not just open the socket. qemu's user-mode forwarding binds the host port
    # the moment the VM starts, so a bare TCP connect succeeds while Windows is still formatting the
    # disk - which reported "guest has reached first logon" 20 seconds into a 40-minute install.
    banner=$(timeout 6 bash -c "exec 3<>/dev/tcp/127.0.0.1/${SSH_PORT} && head -c 40 <&3" 2>/dev/null)
    case "${banner}" in
      SSH-*) echo "ssh: UP on ${SSH_PORT} — ${banner}" ;;
      *)     echo "ssh: not yet (windows still installing)" ;;
    esac
    echo "disk: $(qemu-img info "${DISK}" 2>/dev/null | awk -F': ' '/disk size/{print $2}')"
    ;;

  key)
    # Windows UEFI install media prints "Press any key to boot from CD or DVD" and waits. With
    # nobody at the keyboard it times out and falls through to the (empty) hard disk, leaving the
    # guest at a UEFI shell while qemu happily burns CPU - which looks exactly like a slow install.
    printf 'sendkey ret\n' | socat - "unix-connect:${VMDIR}/monitor.sock" 2>/dev/null \
      || echo "no monitor socket - boot with this version of the script first"
    ;;

  screenshot)
    # Ask qemu for the guest's framebuffer. The only way to see what an unattended install is
    # actually showing, since there is no display and nobody watching VNC.
    out="${2:-${VMDIR}/screen.ppm}"
    printf 'screendump %s\n' "${out}" | socat - "unix-connect:${VMDIR}/monitor.sock" 2>/dev/null
    sleep 2
    ls -lh "${out}" 2>/dev/null || echo "no screenshot produced"
    ;;

  stop)
    pkill -f "qemu-system-x86_64 -name binaos-win10" && echo stopped || echo "not running"
    ;;

  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
