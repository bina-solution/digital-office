#!/usr/bin/env bash
# test_door.sh — hooks/door gives a machine with no sshd a key-only door that only the engine's network
# can use, and never touches an sshd or a key the owner set up himself.
#
#     bash apps/computers/tests/test_door.sh [image]
#
# Runs the hook as root inside throwaway containers of a Debian image (default: the computers image, which
# is Debian with ssh-keygen and no sshd — the shape of a fresh WSL distro), with apt reaching Debian's mirrors.
# Each container is its own "machine": the office key is a fresh keypair, the engine's gateway is 127.0.0.1
# (a local address, as the bridge's is on a real host) and its network a subnet the container is NOT on, so a
# connection from the container's own address must be refused. Needs docker; changes nothing outside the
# containers, which are removed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
IMAGE="${1:-$(docker ps --filter 'name=^computers-' --format '{{.Image}}' | head -1)}"
[ -n "${IMAGE}" ] || { echo "no image: pass one (a Debian with ssh-keygen)"; exit 2; }
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fails=0
# here-strings, never `printf | grep -q`: under pipefail a grep -q that leaves early fails its printf (SIGPIPE)
check() {   # name expected-line output
  if grep -qxF -- "$2" <<<"$3"; then echo "PASS  $1"; else echo "FAIL  $1"; sed 's/^/      | /' <<<"$3" | tail -15; fails=$((fails + 1)); fi
}

# the hooks run as `bash <hook>` by run_app_hooks, which refuses one that is not executable
for h in door onboard; do
  [ -x "${REPO}/apps/computers/hooks/${h}" ] && echo "PASS  hooks/${h} is executable" || { echo "FAIL  hooks/${h} is not executable"; fails=$((fails + 1)); }
done

# repo <name> [.env lines…] — a minimal checkout the hook runs from
repo() {
  mkdir -p "${T}/$1/scripts" "${T}/$1/apps/computers/hooks"
  cp "${REPO}/scripts/lib.sh" "${T}/$1/scripts/"; cp "${REPO}/apps/computers/hooks/door" "${T}/$1/apps/computers/hooks/"
  { printf 'DEPLOYMENT_NAME=t\n'; shift; for l in "$@"; do printf '%s\n' "${l}"; done; } > "${T}/$1/.env"
}
repo r; repo office 'COMPUTERS_LOCAL_USER=office'
# in_box <repo> <script> [docker -e …] — run as root on a fresh machine; prints the script's output
in_box() {
  local r="$1" s="$2"; shift 2
  docker run --rm -i --entrypoint bash -v "${T}/${r}:/repo:ro" -e REPO_ROOT=/repo -e LANG=C.UTF-8 \
    -e DOOR_PUBKEY_FILE=/root/office_key.pub -e DOOR_SUBNETS=10.254.254.0/24 -e DOOR_GATEWAY=127.0.0.1 "$@" \
    "${IMAGE}" -s <<EOF
set -u
ssh-keygen -q -t ed25519 -N '' -f /root/office_key -C office >/dev/null
door() { bash /repo/apps/computers/hooks/door "\$@"; }
key() { ssh -n -q -i /root/office_key -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 "\$@"; }
eff() { mkdir -p /run/sshd; /usr/sbin/sshd -T -C user=root,host=203.0.113.9,addr=203.0.113.9 2>/dev/null | grep -E "^(passwordauthentication|kbdinteractiveauthentication) "; }
installed() { apt-get update -q >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -q openssh-server >/dev/null 2>&1; mkdir -p /run/sshd; }
listening() { awk '\$4 == "0A" && \$2 ~ /:0016\$/ {f = 1} END {exit !f}' /proc/net/tcp /proc/net/tcp6 && echo "on 22: yes" || echo "on 22: no"; }
$s
EOF
}

# 1. a machine with no sshd: installed, keys only in the EFFECTIVE config, the key in once, only from the network
out="$(in_box r '
door status | sed "s/^.*\] //"
door install >/dev/null 2>&1; echo "install rc=$?"
pid1="$(cat /run/sshd.pid)"; second="$(door install 2>&1)"; echo "second rc=$? out=[${second}]"
[ "$(cat /run/sshd.pid)" = "${pid1}" ] && echo "not restarted"
eff
echo "key lines: $(grep -c "computers-office:t$" /root/.ssh/authorized_keys)"
key root@127.0.0.1 "echo id=\$(id -u)" 2>&1
me="$(getent hosts "$(cat /etc/hostname)" | cut -d" " -f1)"; key "root@${me}" true 2>/dev/null; echo "from own address rc=$?"
door status | sed "s/^.*\] //"
')"
check "no sshd: status says so before" "sshd: none installed" "${out}"
check "no sshd: install succeeds" "install rc=0" "${out}"
check "second run: silent, rc 0" "second rc=0 out=[]" "${out}"
check "second run: sshd not restarted" "not restarted" "${out}"
check "effective config: no passwords" "passwordauthentication no" "${out}"
check "effective config: no keyboard-interactive" "kbdinteractiveauthentication no" "${out}"
check "the office key is in once" "key lines: 1" "${out}"
check "the office key opens it from this machine" "id=0" "${out}"
check "a connection from outside the engine's network is refused" "from own address rc=255" "${out}"
check "status: the door's sshd" "sshd: installed by this hook (/etc/ssh/sshd_config.d/10-dgo-computers.conf), listening on :22" "${out}"

# 2. the machine's own sshd, running, with the key approved by hand: byte for byte untouched
out="$(in_box r '
installed; /usr/sbin/sshd
mkdir -p /root/.ssh && { echo "ssh-ed25519 AAAAOWNERSOWNKEY owner"; cat /root/office_key.pub; } > /root/.ssh/authorized_keys
before="$(sha256sum /root/.ssh/authorized_keys /etc/ssh/sshd_config; ls /etc/ssh/sshd_config.d/)"; pid1="$(cat /run/sshd.pid)"
door install; echo "rc=$?"
[ "$(sha256sum /root/.ssh/authorized_keys /etc/ssh/sshd_config; ls /etc/ssh/sshd_config.d/)" = "${before}" ] && [ "$(cat /run/sshd.pid)" = "${pid1}" ] && echo "untouched=yes"
door status | sed "s/^.*\] //"
')"
check "own sshd: install succeeds" "rc=0" "${out}"
check "own sshd and hand-approved key: untouched, not reloaded" "untouched=yes" "${out}"
check "status: the machine's own sshd" "sshd: the machine's own, untouched (listening on :22)" "${out}"
check "status: approved by hand" "office key: authorized for root by hand" "${out}"

# 3. the machine's own sshd, installed but STOPPED: not configured, not started (it is the owner's to start)
out="$(in_box r '
installed; pkill -x sshd 2>/dev/null; sleep 1
door install >/dev/null 2>&1; echo "rc=$?"
[ -e /etc/ssh/sshd_config.d/10-dgo-computers.conf ] && echo "dropin=written" || echo "dropin=none"
listening
')"
check "own sshd stopped: no drop-in" "dropin=none" "${out}"
check "own sshd stopped: not started" "on 22: no" "${out}"

# 4. the machine's own sshd on ANOTHER port: not configured, not reloaded, still on its port
out="$(in_box r '
installed; pkill -x sshd 2>/dev/null; sleep 1; rm -f /run/sshd.pid; /usr/sbin/sshd -p 2222
while [ ! -s /run/sshd.pid ]; do sleep 0.2; done; pid1="$(cat /run/sshd.pid)"
door install >/dev/null 2>&1; echo "rc=$?"
[ -e /etc/ssh/sshd_config.d/10-dgo-computers.conf ] && echo "dropin=written" || echo "dropin=none"
[ "$(cat /run/sshd.pid)" = "${pid1}" ] && echo "same sshd"
')"
check "own sshd on 2222: no drop-in" "dropin=none" "${out}"
check "own sshd on 2222: not reloaded" "same sshd" "${out}"

# 5. authorized_keys holding other keys (one line not UTF-8): appended; then the network moves: replaced by rename
out="$(in_box r '
mkdir -p /root/.ssh && printf "ssh-ed25519 AAAAOWNERA a\nssh-ed25519 AAAAOWNERB \377\376 not utf-8\n" > /root/.ssh/authorized_keys
others="$(head -2 /root/.ssh/authorized_keys | sha256sum)"
door install >/dev/null 2>&1; echo "rc=$?"
[ "$(head -2 /root/.ssh/authorized_keys | sha256sum)" = "${others}" ] && echo "others kept"
echo "ours: $(grep -c "computers-office:t$" /root/.ssh/authorized_keys)"
DOOR_SUBNETS=10.253.0.0/16 door install >/dev/null 2>&1; echo "moved rc=$?"
[ "$(LC_ALL=C grep -av "computers-office:t$" /root/.ssh/authorized_keys | sha256sum)" = "${others}" ] && echo "others kept after the move"
echo "ours after the move: $(grep -c "computers-office:t$" /root/.ssh/authorized_keys)"
grep -q "10.253.0.0/16" /root/.ssh/authorized_keys && ! grep -q "10.254.254.0/24" /root/.ssh/authorized_keys && echo "from= moved"
stat -c "mode=%a" /root/.ssh/authorized_keys
')"
check "other keys: install succeeds" "rc=0" "${out}"
check "other keys, one not UTF-8: kept byte for byte" "others kept" "${out}"
check "other keys: ours added once" "ours: 1" "${out}"
check "network moved: succeeds" "moved rc=0" "${out}"
check "network moved: the others still byte for byte" "others kept after the move" "${out}"
check "network moved: ours replaced, once" "ours after the move: 1" "${out}"
check "network moved: from= follows" "from= moved" "${out}"
check "authorized_keys stays 600" "mode=600" "${out}"

# 6. apt cannot install (no package sources): no drop-in left behind, and the next run installs
out="$(in_box r '
mkdir /tmp/src && mv /etc/apt/sources.list.d/* /tmp/src/ 2>/dev/null; rm -rf /var/lib/apt/lists/*
door install >/dev/null 2>&1; echo "rc=$?"
[ -e /etc/ssh/sshd_config.d/10-dgo-computers.conf ] && echo "dropin=left" || echo "dropin=none"
mv /tmp/src/* /etc/apt/sources.list.d/
door install >/dev/null 2>&1; echo "retry rc=$?"
listening
')"
check "apt fails: reported" "rc=1" "${out}"
check "apt fails: no drop-in left behind" "dropin=none" "${out}"
check "apt fails: the next run installs" "retry rc=0" "${out}"
check "apt fails: then up on 22" "on 22: yes" "${out}"

# 7. the engine network cannot be read: nothing written at all
out="$(in_box r '
DOOR_SUBNETS="" door install >/dev/null 2>&1; echo "rc=$?"
[ -e /etc/ssh/sshd_config.d/10-dgo-computers.conf ] || [ -e /root/.ssh/authorized_keys ] && echo "wrote something" || echo "wrote nothing"
')"
check "no subnets: reported" "rc=1" "${out}"
check "no subnets: nothing written" "wrote nothing" "${out}"

# 8. the gateway is not on this machine (bbox run from inside a container): nothing written, not an error
out="$(in_box r '
DOOR_GATEWAY=10.254.254.1 door install 2>&1 | sed "s/^.*\] //"; echo "rc=${PIPESTATUS[0]}"
[ -e /root/.ssh/authorized_keys ] && echo "wrote something" || echo "wrote nothing"
')"
check "gateway elsewhere: rc 0" "rc=0" "${out}"
check "gateway elsewhere: nothing written" "wrote nothing" "${out}"

# 9. COMPUTERS_LOCAL_USER is not root: the key is that user's, owned by it, and opens only that user
out="$(in_box office '
useradd -m office
door install > /tmp/door.out 2>&1; echo "rc=$?"; sed "s/^/door: /" /tmp/door.out
stat -c "owner=%U mode=%a" /home/office/.ssh/authorized_keys
key office@127.0.0.1 "echo who=\$(id -un)" 2>&1
key root@127.0.0.1 true 2>/dev/null; echo "as root rc=$?"
')"
check "another user: install succeeds" "rc=0" "${out}"
check "another user: its file, 600" "owner=office mode=600" "${out}"
check "another user: the key opens that user" "who=office" "${out}"
check "another user: the key does not open root" "as root rc=255" "${out}"

echo
[ "${fails}" = 0 ] && echo "test_door: all passed" || echo "test_door: ${fails} FAILED"
exit $((fails > 0))
