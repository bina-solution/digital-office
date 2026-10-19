#!/usr/bin/env bash
# provision-test-vm.sh — a Windows 10 KVM guest on a Linux box, to test BinaOS-Setup.exe.
#
#   packaging/windows/provision-test-vm.sh --step deps|iso|disk|install
#
# WHY A VM AND NOT THE DEV LAPTOP
# The Windows installer's whole job is to work on a machine that has never seen this platform:
# no WSL distro, no Docker, no .env, no build state. A developer box proves none of that. The
# portable Linux machine has VT-x, /dev/kvm and — the part that actually decides it —
# **nested virtualisation enabled** (`/sys/module/kvm_intel/parameters/nested` = Y), which WSL2
# inside the guest requires. Without nested virt the guest can boot Windows but `wsl --install`
# fails, and the installer would never get past its first step.
#
# Run the steps in order; each is separately re-runnable.
set -uo pipefail

STEP=""
VM=binaos-win10
RAM=8192
CPUS=4
DISK_GB=80
WORK="${HOME}/win-vm"

while [ $# -gt 0 ]; do
  case "$1" in
    --step) STEP="${2:?deps|iso|disk|install}"; shift ;;
    --ram)  RAM="${2:?}"; shift ;;
    --cpus) CPUS="${2:?}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 2 ;;
  esac
  shift
done
mkdir -p "${WORK}"; cd "${WORK}"

case "${STEP}" in

deps)
  echo "== virtualisation host check =="
  grep -qoE 'vmx|svm' /proc/cpuinfo && echo "  ok   CPU virtualisation" || { echo "  FAIL no VT-x/AMD-V"; exit 1; }
  [ -e /dev/kvm ] && echo "  ok   /dev/kvm" || { echo "  FAIL no /dev/kvm"; exit 1; }
  n=$(cat /sys/module/kvm_intel/parameters/nested 2>/dev/null || cat /sys/module/kvm_amd/parameters/nested 2>/dev/null || echo N)
  case "${n}" in
    Y|1) echo "  ok   nested virtualisation (WSL2 inside the guest needs this)" ;;
    *)   echo "  FAIL nested virt is '${n}' — WSL2 will not run inside the guest."
         echo "       Enable with: echo 'options kvm_intel nested=1' | sudo tee /etc/modprobe.d/kvm.conf"
         echo "       then reload:  sudo modprobe -r kvm_intel && sudo modprobe kvm_intel"
         exit 1 ;;
  esac
  echo "== packages =="
  need=""
  for p in qemu-system-x86 qemu-utils ovmf swtpm swtpm-tools; do
    dpkg -s "$p" >/dev/null 2>&1 || need="${need} $p"
  done
  # Windows 11 needs TPM 2.0 + secure boot; Windows 10 does not, but swtpm costs nothing and
  # keeps the door open. OVMF is required either way — a BIOS guest cannot do secure boot.
  if [ -n "${need}" ]; then
    echo "  installing:${need}"
    sudo apt-get update -qq && sudo apt-get install -y -qq ${need}
  else
    echo "  ok   all present"
  fi
  ;;

iso)
  # Microsoft serves the ISO only after a session-scoped product/sku handshake, and the direct
  # links expire in ~24h. Fido (a maintained PowerShell/bash-callable script) does that handshake
  # rather than us hardcoding a URL that rots. Falling back to a manual instruction is deliberate:
  # silently downloading "some" Windows image is worse than telling the operator to fetch one.
  if [ -f win10.iso ]; then
    echo "  ok   win10.iso already present ($(du -h win10.iso | cut -f1))"
  else
    echo "  Windows ISOs need Microsoft's session handshake; direct URLs expire."
    echo "  Fetch one of:"
    echo "    https://www.microsoft.com/en-us/software-download/windows10ISO"
    echo "  and place it at ${WORK}/win10.iso"
    echo
    echo "  (Fido can automate it: https://github.com/pbatard/Fido)"
  fi
  if [ -f virtio-win.iso ]; then
    echo "  ok   virtio-win.iso present"
  else
    echo "  fetching virtio drivers (KVM disk/net need them during setup)"
    curl -fsSL -o virtio-win.iso.part \
      "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso" \
      && mv virtio-win.iso.part virtio-win.iso && echo "  ok   virtio-win.iso"
  fi
  ;;

disk)
  if [ -f "${VM}.qcow2" ]; then
    echo "  ok   ${VM}.qcow2 exists ($(du -h "${VM}.qcow2" | cut -f1))"
  else
    qemu-img create -f qcow2 "${VM}.qcow2" "${DISK_GB}G"
    echo "  created ${VM}.qcow2 (${DISK_GB}G sparse)"
  fi
  # UEFI vars must be per-VM and writable; sharing the template makes boot order unstable.
  [ -f OVMF_VARS.fd ] || cp /usr/share/OVMF/OVMF_VARS_4M.fd OVMF_VARS.fd 2>/dev/null \
                       || cp /usr/share/OVMF/OVMF_VARS.fd OVMF_VARS.fd 2>/dev/null \
                       || echo "  warn: no OVMF vars template found"
  ;;

install)
  [ -f win10.iso ] || { echo "no win10.iso — run --step iso first"; exit 1; }
  cat > run-vm.sh <<'RUNVM'
#!/usr/bin/env bash
# Boots the guest headless with VNC on :1 and RDP forwarded to host 13389.
# -cpu host,+vmx is what exposes nested virtualisation to the guest so WSL2 can run inside it.
cd "$(dirname "$0")"
exec qemu-system-x86_64 \
  -name binaos-win10 -machine q35,accel=kvm -cpu host,+vmx -smp 4 -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive if=pflash,format=raw,file=OVMF_VARS.fd \
  -drive file=binaos-win10.qcow2,if=virtio,cache=writeback,discard=unmap \
  -drive file=win10.iso,media=cdrom \
  -drive file=virtio-win.iso,media=cdrom \
  -netdev user,id=n0,hostfwd=tcp::13389-:3389,hostfwd=tcp::18080-:80 \
  -device virtio-net-pci,netdev=n0 \
  -vga std -display none -vnc :1 \
  -usb -device usb-tablet
RUNVM
  chmod +x run-vm.sh
  echo "  wrote run-vm.sh"
  echo "  start:  ~/win-vm/run-vm.sh &"
  echo "  view:   VNC to <this-host>:5901   (ssh -L 5901:localhost:5901 portable)"
  echo "  after Windows is installed and RDP enabled: rdp to <this-host>:13389"
  echo
  echo "  During setup, load the virtio disk driver from the second CD (E:\\amd64\\w10)"
  echo "  or Windows will not see the disk."
  ;;

*) echo "usage: $0 --step deps|iso|disk|install" >&2; exit 2 ;;
esac
