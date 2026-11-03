#!/usr/bin/env bash
# guest.sh <out.img> — the Android engine's guest disk (DGO-1071): the MacBook engine's own guest, made in
# CI so a phone never provisions under emulation (apt under QEMU's TCG crawls: measured on the MacBook
# engine, a cloud guest took 435 s just to reach cloud-init's last stage). The image and its digest are
# packaging/macos/engine.yaml's (arm64); its provisioning is engine.yaml's, run in an arm64 chroot through
# qemu-user — Docker CE 28.5.2 and Compose 2.40.3 pinned and held, the bbox endpoint drop-in — and, for
# a phone, the office itself: this checkout at /opt/office, brought up at boot by dgo-office.service on the
# Mac's edge (http://console.localhost:8080, CI_DEPLOYMENT_NAME=local), the core on (DGO-1090), every image
# it runs already in the guest's image store (DGO_GUEST_IMAGES, below).
# Needs root, qemu-user-static with binfmt, cloud-guest-utils, python3-yaml, qemu-utils, and dockerd (the
# runner's). A raw disk: a phone reads qcow2 far slower than raw inside QEMU.
set -euo pipefail
out="${1:?usage: guest.sh <out.img>}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
read -r url digest < <(python3 - "${repo}/packaging/macos/engine.yaml" <<'PY'
import sys, yaml
img = next(i for i in yaml.safe_load(open(sys.argv[1]))["images"] if i.get("arch") == "aarch64" and i.get("digest"))
print(img["location"], img["digest"].split(":", 1)[1])
PY
)
work="$(mktemp -d)"; mnt="${work}/root"
cleanup() {
  if [ -n "${dpid:-}" ]; then kill "${dpid}" 2>/dev/null || true; wait "${dpid}" 2>/dev/null || true; fi
  # whatever the image dockerd below left mounted in the image, deepest first
  awk -v m="${mnt}/var/" 'index($2, m) == 1 {print $2}' /proc/mounts | sort -r | while read -r p; do umount "${p}" 2>/dev/null || true; done
  for m in dev/pts dev proc sys run; do umount "${mnt}/${m}" 2>/dev/null || true; done
  umount "${mnt}" 2>/dev/null || true
  [ -n "${loop:-}" ] && losetup -d "${loop}" 2>/dev/null || true
  # never into a filesystem still mounted there: an image that would not unmount was deleted whole once
  # (the second reader of 05d3a9a3: the Mac's swap script had turned the image's swap on, on the runner)
  if mountpoint -q "${mnt}" 2>/dev/null; then echo "guest.sh: ${mnt} is still mounted — ${work} left as it is" >&2; exit 1; fi
  rm -rf --one-file-system "${work}"
}
trap cleanup EXIT
curl -fsSL -o "${work}/cloud.img" "${url}"
echo "${digest}  ${work}/cloud.img" | sha256sum -c -
qemu-img convert -O raw "${work}/cloud.img" "${out}"
qemu-img resize -f raw "${out}" 24G
loop="$(losetup -fP --show "${out}")"
growpart "${loop}" 1
# the partition's node where /dev is a container's copy, not the kernel's (guest-box.sh): the kernel names
# a loop device's partitions as it attaches it, and nothing adds their nodes there — made from sysfs
if [ ! -b "${loop}p1" ]; then
  n="${loop##*/}"
  IFS=: read -r maj min < "/sys/block/${n}/${n}p1/dev"
  mknod "${loop}p1" b "${maj}" "${min}"
fi
e2fsck -fp "${loop}p1" || true
resize2fs "${loop}p1"
mkdir -p "${mnt}"; mount "${loop}p1" "${mnt}"
# the runner's /run in the chroot: the image's /etc/resolv.conf is a link into /run/systemd/resolve, so
# apt in the chroot resolves through the runner's own resolver, and nothing of the image is rewritten
for m in dev dev/pts proc sys run; do mount --bind "/${m}" "${mnt}/${m}"; done
# a command in the guest's root, without the caller's TMPDIR: a path of the caller's (guest-box.sh puts
# the box's TMPDIR on its work disk) that is not there in the guest — ca-certificates' postinst failed its mktemp
# on it, and dpkg with it (run 41423453855). This script's own temporary files stay where TMPDIR says.
inguest() { env -u TMPDIR chroot "${mnt}" "$@"; }

# engine.yaml's provisioning, the scripts that are not Lima's own (the hosts line) and with no running
# systemd in a chroot: what `systemctl restart` would do happens at the guest's first boot
# Not the swap script either: in a chroot its swapon runs on the RUNNER's kernel (the image then cannot
# unmount) and it sizes from the runner's /proc/swaps. The guest's swap is made here instead, as a file
# with its fstab line, turned on by the guest itself at boot.
# Nor a `sysctl` call, for the same reason: vm.*, and most of kernel.* and fs.*, are not per-namespace and
# the box is privileged, so in the chroot it would set the RUNNER's kernel (engine.yaml's memory floor,
# 44b1f9d0, on the Dell); only net.* would stay in the box's own network. What the script writes to
# /etc/sysctl.d/ stays in the image, and the guest's systemd-sysctl applies it at boot. A call the rewrite
# below does not reach (inside a line, by its path) or a write to /proc/sys stops the build instead.
python3 - "${repo}/packaging/macos/engine.yaml" "${work}" <<'PY'
import sys, re, yaml, pathlib
steps = [p["script"] for p in yaml.safe_load(open(sys.argv[1]))["provision"] if p.get("mode") == "system"]
keep = [s for s in steps if "host.lima.internal" not in s and "swapon" not in s]
for i, s in enumerate(keep):
    s = s.replace("systemctl daemon-reload", ": daemon-reload at boot").replace("systemctl restart docker.service", ": started at boot")
    s = s.replace('usermod -aG docker "{{.User}}" || true', ": no Lima user here")
    s = re.sub(r"(?m)^([ \t]*)sysctl\b", r"\1: at the guest boot, by systemd-sysctl: sysctl", s)
    # fail closed: what is left that would still reach the kernel (not a path like /etc/sysctl.d/, not a comment)
    left = [l.strip() for l in s.splitlines() if not l.lstrip().startswith((":", "#"))
            and (re.search(r"(?<![\w.-])sysctl(?![\w.])", l) or "/proc/sys" in l)]
    if left:
        sys.exit(f"guest.sh: engine.yaml's provisioning would set the runner's kernel from the chroot: {left[0]}")
    pathlib.Path(sys.argv[2], f"provision-{i}.sh").write_text(s)
print(f"{len(keep)} of engine.yaml's {len(steps)} provisioning scripts")
PY
# no package starts its service in the chroot (Debian's policy-rc.d, which invoke-rc.d and
# deb-systemd-invoke obey): where the runner's /run says no systemd runs — a box's (guest-box.sh) —
# docker-ce's postinst would fall to its init.d script and start an arm64 dockerd on the guest's own store
printf '#!/bin/sh\nexit 101\n' > "${mnt}/usr/sbin/policy-rc.d"
chmod 755 "${mnt}/usr/sbin/policy-rc.d"
for s in "${work}"/provision-*.sh; do
  cp "${s}" "${mnt}/tmp/p.sh"
  inguest /bin/bash /tmp/p.sh
done
rm -f "${mnt}/usr/sbin/policy-rc.d"   # the guest's own boots start what it enables
# the guest's swap: a phone's memory is small and an office's first start is not (the Mac guest's reason)
fallocate -l 2G "${mnt}/swapfile"   # one command a line: set -e stops on each, an && chain would not
chmod 600 "${mnt}/swapfile"
mkswap -q "${mnt}/swapfile"
grep -q '^/swapfile ' "${mnt}/etc/fstab" || echo '/swapfile none swap sw 0 0' >> "${mnt}/etc/fstab"
# the packages apt fetched for that are installed now: not carried to every phone. After the swap file,
# which would otherwise be allocated over their freed blocks — the trim below zeroes only free ones
inguest apt-get clean

# The machine's network, declared: QEMU's user network (slirp) on the phone and in try-guest.sh alike —
# DHCP gives 10.0.2.15, the way out, and its DNS proxy 10.0.2.3. Left to cloud-init's fallback, the first
# boot came up with a resolver that had no working server ("lookup registry-1.docker.io on 127.0.0.53:53:
# server misbehaving", android-guest run 41247843400): the office's own images loaded, every public pull
# failed. So DHCP on whatever virtio NIC the machine has, cloud-init's network config off, and the
# resolver told the proxy and two public servers besides.
mkdir -p "${mnt}/etc/netplan" "${mnt}/etc/systemd/resolved.conf.d"
cat > "${mnt}/etc/netplan/90-dgo.yaml" <<'NETPLAN'
network:
  version: 2
  ethernets:
    nic:
      match:
        name: "en*"
      dhcp4: true
      nameservers:
        addresses: [10.0.2.3]
NETPLAN
chmod 600 "${mnt}/etc/netplan/90-dgo.yaml"
echo "guest: netplan holds $(ls "${mnt}/etc/netplan" | tr '\n' ' ')"   # another file for the NIC would compete
echo 'network: {config: disabled}' > "${mnt}/etc/cloud/cloud.cfg.d/99-dgo-network.cfg"
# all three as servers: resolved asks a FallbackDNS only when it knows no server at all, never beside one
printf '[Resolve]\nDNS=10.0.2.3 1.1.1.1 8.8.8.8\n' > "${mnt}/etc/systemd/resolved.conf.d/90-dgo.conf"

# the office, and its start at every boot (Type=oneshot: bbox run returns once the stack is up)
mkdir -p "${mnt}/opt"
# anchored excludes (apps/chat/src/data is tracked code); root's own tree, and git told it is (the runner's
# uid would make it "dubious ownership" to root's git in the guest)
# Not this checkout's platform.state.yaml (tracked) nor its .env: the guest's first boot makes both, the
# core (platform.state.core.yaml) — the very set its images were built for in CI (android-engine.yml).
rsync -a --exclude '/apps/n8n/tooling/node_modules' --exclude '/.generated' --exclude '/data' \
  --exclude '/platform.state.yaml' --exclude '/.env' --exclude '/.git' "${repo}/" "${mnt}/opt/office/"
# Its git, one commit deep, as a fresh clone has it: never the runner's .git, which on a runner that keeps
# its workspace (the Dell's) holds every fetch since — 5 GB of it in the guest, and a 3.1 GB .xz no APK
# can carry (run 41441079036). The same commit, branch and origin; the index from that commit, the tree
# already there (so the guest's git status is the rsync's, as before).
# (each read into a variable first: a git that fails stops the build, never compares as an empty string)
want="$(git -c safe.directory='*' -C "${repo}" rev-parse HEAD)"
origin="$(git -c safe.directory='*' -C "${repo}" remote get-url origin)"
git -c safe.directory='*' clone -q --depth 1 --no-checkout "file://${repo}" "${work}/office-git"
mv "${work}/office-git/.git" "${mnt}/opt/office/.git"
git -c safe.directory='*' -C "${mnt}/opt/office" remote set-url origin "${origin}"
git -c safe.directory='*' -C "${mnt}/opt/office" read-tree HEAD
have="$(git -c safe.directory='*' -C "${mnt}/opt/office" rev-parse HEAD)"
[ -n "${want}" ] && [ "${have}" = "${want}" ] \
  || { echo "guest.sh: the guest's git is not at this checkout's commit" >&2; exit 1; }
echo "guest: its git $(du -sh "${mnt}/opt/office/.git" | cut -f1), at $(git -c safe.directory='*' -C "${mnt}/opt/office" rev-parse --short HEAD) on $(git -c safe.directory='*' -C "${mnt}/opt/office" rev-parse --abbrev-ref HEAD)"
chown -R 0:0 "${mnt}/opt/office"
inguest git config --system --add safe.directory /opt/office
# Every image the office runs (DGO_GUEST_IMAGES, a `docker save` tar of arm64 images: its own, built in CI,
# and the public ones, pulled there), unpacked HERE into the guest's own image store: the phone neither
# builds, pulls nor unpacks one. Under the phone's emulation unpacking is what crawls — the first boot that
# pulled the public images spent 1.8 h on them, one 340 MB layer an hour, and the office was not up at
# 3.5 h (android-guest run 41249591722). The runner's dockerd does it natively, a second daemon with the
# guest's /var/lib/docker as its data root: overlay2 and no containerd snapshotter, the store the guest's
# Docker CE 28 reads by default; its own socket, state and containerd namespace, no network. Only the
# image store is kept — its networks, engine-id and the rest every guest makes for itself.
if [ -n "${DGO_GUEST_IMAGES:-}" ] && [ -f "${DGO_GUEST_IMAGES}" ]; then
  d="${work}/dockerd"; mkdir -p "${d}"
  printf '{"storage-driver": "overlay2", "features": {"containerd-snapshotter": false}}\n' > "${d}/daemon.json"
  dockerd --config-file "${d}/daemon.json" --data-root "${mnt}/var/lib/docker" --exec-root "${d}/exec" \
    --pidfile "${d}/pid" -H "unix://${d}/sock" --containerd-namespace dgo-guest \
    --containerd-plugins-namespace dgo-guest-plugins --iptables=false --ip6tables=false --bridge=none \
    > "${d}/log" 2>&1 &
  dpid=$!
  g() { docker -H "unix://${d}/sock" "$@"; }
  for _ in $(seq 120); do g info >/dev/null 2>&1 && break; kill -0 "${dpid}" 2>/dev/null || break; sleep 1; done
  g info >/dev/null 2>&1 || { echo "guest.sh: the image dockerd did not start:" >&2; tail -n 20 "${d}/log" >&2; exit 1; }
  g load -q -i "${DGO_GUEST_IMAGES}"
  archs="$(g image inspect -f '{{.Architecture}}' $(g image ls -q | sort -u) | sort -u | tr '\n' ' ')"
  [ "${archs}" = "arm64 " ] || { echo "guest.sh: the images are for ${archs}— not arm64 alone" >&2; exit 1; }
  echo "guest: $(g image ls --format '{{.Repository}}:{{.Tag}}' | wc -l) images in its store, $(du -sh "${mnt}/var/lib/docker" | cut -f1)"
  kill "${dpid}"; wait "${dpid}" || true; dpid=""
  if awk -v m="${mnt}/var/" 'index($2, m) == 1' /proc/mounts | grep -q .; then
    echo "guest.sh: the image dockerd left mounts in the image" >&2; exit 1
  fi
  find "${mnt}/var/lib/docker" -mindepth 1 -maxdepth 1 ! -name image ! -name overlay2 -exec rm -rf --one-file-system {} +
  # what they were built from (root's git on the runner's checkout: told it is safe, whatever git's age)
  mkdir -p "${mnt}/var/lib/dgo"
  git -c safe.directory='*' -C "${repo}" rev-parse HEAD > "${mnt}/var/lib/dgo/images-commit"
fi
# when the office does not come up clean: every container's state and each unhealthy one's last probes, on
# the console — the phone's screen shows that tail, and try-guest.sh prints it (run 41249591722's console
# said only "container docker-socket-proxy-local is unhealthy")
cat > "${mnt}/usr/local/bin/dgo-office-report" <<'REPORT'
#!/bin/bash
# dgo-office-report [--if-not-clean] — the office's containers, as Docker sees them (dgo-office.service).
# Always ends with one "dgo-office-report:" line, "clean" or "done", which try-guest.sh waits for.
if ! docker info >/dev/null 2>&1; then
  echo "dgo-office-report: Docker does not answer"; systemctl status docker --no-pager -n 20 || true
  echo "dgo-office-report: done"; exit 0
fi
# clean: none unhealthy, starting or restarting, and none that stopped with an error (a job that exited
# 0 is done) — and something there at all
if [ "${1:-}" = --if-not-clean ] && [ -n "$(docker ps -aq)" ] \
   && [ -z "$(docker ps -aq --filter health=unhealthy)$(docker ps -aq --filter health=starting)$(docker ps -aq --filter status=restarting)" ] \
   && ! docker ps -a --filter status=exited --filter status=dead --format '{{.Status}}' | grep -qv '^Exited (0)'; then
  echo "dgo-office-report: clean"; exit 0
fi
echo "dgo-office-report: the containers"
docker ps -a --format '{{.Names}}: {{.Status}}' | sort
# each unhealthy one's probes, one a line: the newest are the last lines
for c in $(docker ps -aq --filter health=unhealthy); do
  docker inspect -f '{{.Name}} probes:{{range .State.Health.Log}}{{"\n"}}  [exit {{.ExitCode}} at {{.Start.Format "15:04:05"}}] {{printf "%.200s" .Output}}{{end}}' "${c}"
done
# each running container's CPU since it started: its cap, what it used, how often the cap held it back.
# Caps are sized for a native CPU and this one is emulated (~20x slower), so here none is capped
# (cpu-budget-lint.py); this shows whether anything is still held back (DGO-1084)
echo "dgo-office-report: CPU — cap, used, throttled"
for id in $(docker ps -q --no-trunc); do
  f="/sys/fs/cgroup/system.slice/docker-${id}.scope/cpu.stat"
  [ -f "${f}" ] || continue
  awk -v who="$(docker inspect -f '{{.Name}} cap={{.HostConfig.NanoCpus}}' "${id}")" \
    '{a[$1] = $2} END {printf "%s used=%.0fs throttled=%d/%d periods (%.0fs)\n", who, a["usage_usec"] / 1e6, a["nr_throttled"], a["nr_periods"], a["throttled_usec"] / 1e6}' "${f}"
done
uptime
free -m
echo "dgo-office-report: done"
REPORT
chmod 755 "${mnt}/usr/local/bin/dgo-office-report"
cat > "${mnt}/etc/systemd/system/dgo-office.service" <<'UNIT'
[Unit]
Description=The Digital Office — this phone's office (DGO-1071)
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=infinity
WorkingDirectory=/opt/office
Environment=BBOX_WAIT_TIMEOUT=7200
# the project name the images were built and tagged with in CI (office-<service>), pinned as there
Environment=COMPOSE_PROJECT_NAME=office
# the network is the guest's own slirp: bbox's DNS probe (busybox, 60 s) can time out under emulation and
# then rebuild every image serially
Environment=BBOX_ASSUME_DNS_OK=1
# bbox's progress and its verdict on the guest's serial console too: the app shows that console's tail
# while the office comes up, and try-guest.sh reads "up." there (the edge alone cannot tell: sign-in
# answers 302 for every host before the console behind it is ready)
StandardOutput=journal+console
StandardError=journal+console
# the machine's network as it stands, on the console before anything needs it (its lease, its DNS servers)
ExecStartPre=-/usr/bin/networkctl status --no-pager
ExecStartPre=-/usr/bin/resolvectl status --no-pager
# Behind a phone's native core (DGO-1090, android-path.md "the machine on demand") the machine is given
# the core's token for this boot in QEMU's fw_cfg, outside its network: it replaces the last boot's in .env,
# where forward-auth's compose takes it (FORWARD_AUTH_EDGE_TOKEN). A machine started without one — the
# machine's own office — keeps .env as it is.
# The first boot starts from the core (platform.state.core.yaml: the console, app management,
# notifications, forward-auth, the extensions — DGO-1090) and makes .env with forward-auth as the edge's
# identity (CI_IDENTITY); forward-auth's prepare hook prints the one-time link that makes the owner. The
# state FIRST: ci-env.sh's CPU plan reads the state through the compiler, whose ensure_state() writes the
# product's full default where there is none — and then the core was never copied (the 0.1.15 boot,
# run 41302698368, pulled authentik and built every app for its whole 3.6 h). Said on the console.
# BBOX_PREBUILT only while the checkout is the commit its images were built from: once it moves on, bbox
# builds as everywhere (a prebuilt flag kept for good would hide a stale image). $$ is systemd's literal $.
# Then the containers on the console: always when bbox failed, and when it exited 0 (as it does with
# problems too) unless every container is clean.
ExecStart=/bin/bash -c 'if [ ! -f platform.state.yaml ]; then cp platform.state.core.yaml platform.state.yaml || { echo "dgo-office: no platform.state.core.yaml to start from"; exit 1; }; fi; echo "dgo-office: $$(grep -cE "^ +[a-z0-9-]+: .*(enabled: *true|state: *enabled)" platform.state.yaml) apps on in platform.state.yaml"; [ -f .env ] || CI_IDENTITY=forward-auth CI_ENV_FORCE=1 CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh; modprobe qemu_fw_cfg 2>/dev/null || true; t=/sys/firmware/qemu_fw_cfg/by_name/opt/dgo/edge-token/raw; v=""; if [ -r "$$t" ]; then v="$$(tr -dc A-Za-z0-9 < "$$t")"; fi; if [ -s .env ] && { [ $${#v} -ge 32 ] || grep -q "^FORWARD_AUTH_EDGE_TOKEN=" .env; }; then if { grep -v "^FORWARD_AUTH_EDGE_TOKEN=" .env; if [ $${#v} -ge 32 ]; then echo "FORWARD_AUTH_EDGE_TOKEN=$$v"; fi; } > .env.edge && [ -s .env.edge ]; then mv .env.edge .env; else rm -f .env.edge; fi; if [ $${#v} -ge 32 ]; then echo "dgo-office: behind the native core of the phone, its token for this boot taken"; else echo "dgo-office: no core token this boot, the last one dropped"; fi; elif [ -d /sys/firmware ] && [ ! -d /sys/firmware/qemu_fw_cfg ]; then echo "dgo-office: no fw_cfg in this guest (qemu_fw_cfg)"; fi; if [ -s /var/lib/dgo/images-commit ] && [ "$$(git rev-parse HEAD 2>/dev/null)" = "$$(cat /var/lib/dgo/images-commit)" ]; then export BBOX_PREBUILT=1; fi; ./bbox run; s=$$?; if [ $$s = 0 ]; then /usr/local/bin/dgo-office-report --if-not-clean; else /usr/local/bin/dgo-office-report; fi; exit $$s'

[Install]
WantedBy=multi-user.target
UNIT
inguest systemctl enable dgo-office.service
# the first boot: no cloud-init datasource on a phone, so it is told there is none. 99-: the image's own
# 90_dpkg.cfg names every datasource and sorts after a 90- (`-` before `_`), so a 90- file would lose to it
# and cloud-init would go probing (OpenStack's 169.254.169.254) before the network is online
echo 'datasource_list: [ NoCloud, None ]' > "${mnt}/etc/cloud/cloud.cfg.d/99-dgo-datasource.cfg"
rm -f "${mnt}/tmp/p.sh"
# what the machine holds, by the largest parts — the APK carries all of it, under GitHub's 2 GB a file
echo "guest: $(du -xsh "${mnt}" | cut -f1) in its filesystem; the largest:"
du -xm --max-depth=3 "${mnt}" 2>/dev/null | sort -rn | sed -n '2,13p' | sed "s|${mnt}||; s/^/  MB /"
# every free block zeroes (the loop device punches it out of the raw file): what was deleted here — apt's
# packages above — compresses to nothing instead of travelling to every phone
fstrim -v "${mnt}" || echo "guest: no trim on this runner — the deleted blocks travel as they are"
# unmounted HERE, where set -e stops the run on a failure — an image whose filesystem was never cleanly
# unmounted is not published (the EXIT trap only cleans up after a failure)
sync
for m in dev/pts dev proc sys run; do umount "${mnt}/${m}"; done
umount "${mnt}"
losetup -d "${loop}"; loop=""
echo "guest: $(du -h --apparent-size "${out}" | cut -f1) raw, $(du -h "${out}" | cut -f1) on disk"
