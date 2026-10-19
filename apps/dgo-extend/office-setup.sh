#!/usr/bin/env bash
# office-setup.sh — make a machine reachable by the office's fleet, so it can become an office (DGO-35).
#
# Run ON the target machine, as root, ONCE before its first converge. The key is passed as ONE quoted
# argument for the REMOTE shell (the local shell strips the quotes before ssh sends them, so without
# the inner '…' the key would arrive in three pieces):
#
#   ssh root@<host> -p <port> "bash -s -- --key '$KEY' --port <port>" < apps/dgo-extend/office-setup.sh
#
#   # facts only, changes nothing (the "before" half of the before/after proof):
#   ssh root@<host> -p <port> 'bash -s -- --check' < apps/dgo-extend/office-setup.sh
#
# On **WSL** (the current target: hp-laptop, 192.168.16.104, port 2222) root is reached through the
# distro itself, so there is no ssh hop at all for the first run:
#
#   wsl -d Ubuntu -u root -- bash /mnt/c/…/apps/dgo-extend/office-setup.sh --key "$KEY" --port 2222
#   wsl -d Ubuntu -u root -- bash …/office-setup.sh --check        # facts + the three WSL traps
#
# What it owns, and what it deliberately does NOT
# -----------------------------------------------
# It owns exactly one thing: making the machine answerable by `apps/computers` over SSH — sshd up on
# the declared port, and the OFFICE's public key authorized for the SSH user. That is the precondition
# for everything else, because `computers` is the only door this office has to a machine (no SSH
# client, no key and no engine socket live in any container).
#
# It does NOT install or pin Docker. The converge's `engine` step runs `debian-install.sh`, which
# pins Docker **28.5.2** and holds it; a second installer here would be a second owner of the same
# fact, and the two would drift. It only REPORTS what is installed, because a machine that runs
# Docker 29 is one where traefik v3.3 discovers ZERO routers, silently, and every host 404s
# (CLAUDE.md). That report is what decides `engine.replace_docker: true`.
#
# It does NOT clone the checkout either: the converge's `code` step does that, with the git app's
# token passed as a one-shot header and never written into .git/config.
#
# It does NOT disable password authentication unless asked (`--harden`). Key-only login is the
# office's own rule, but turning off a password door is the one change here that can lock a person
# out of their own machine, and it must be the owner's deliberate act on a machine he can also reach
# from its console.
#
# It DOES report the three facts that decide whether a WSL machine can host an office at all
# (`WSL=`, `SYSTEMD=`, `PATH_FS[…]`) — see ai/context/running-on-wsl.md and §0 of SECOND-OFFICE.md:
# systemd runs Docker there, `/mnt/c` cannot hold a checkout (9p: every file 777, `chmod` a no-op,
# `acme.json`'s 600 impossible → traefik silently falls back to a self-signed certificate).
#
# The office's public key is an ARGUMENT, not a constant in this file: a key baked into the repo is a
# key that stops matching the office the day the identity is re-minted, and the symptom would be
# "ssh stopped working" with nothing to point at.
set -euo pipefail

KEY=""
CHECK=0
HARDEN=0
PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY="${2:-}"; shift 2 ;;
    --check) CHECK=1; shift ;;
    --harden) HARDEN=1; shift ;;
    --port) PORT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'SETUP_FAILED: %s\n' "$*" >&2; exit 1; }

# ── facts, always ────────────────────────────────────────────────────────────────
facts() {
  say "HOSTNAME=$(hostname 2>/dev/null || echo unknown)"
  # shellcheck disable=SC1091
  . /etc/os-release 2>/dev/null || true
  say "OS=${PRETTY_NAME:-unknown}"
  say "KERNEL=$(uname -r)"
  say "ARCH=$(uname -m)"
  say "NCPU=$(nproc 2>/dev/null || echo 0)"
  awk '/^MemTotal:/{printf "MEM_TOTAL_MB=%d\n", $2/1024}' /proc/meminfo 2>/dev/null || true
  awk '/^MemAvailable:/{printf "MEM_AVAILABLE_MB=%d\n", $2/1024}' /proc/meminfo 2>/dev/null || true
  df -Pm / 2>/dev/null | awk 'NR==2{printf "DISK_FREE_MB=%d\n", $4}'
  if command -v docker >/dev/null 2>&1; then
    say "DOCKER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'installed-not-running')"
  else
    say "DOCKER=none"
  fi
  say "SSHD=$(systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || echo unknown)"
  say "SSHD_CMD=$(command -v sshd || echo none)"
  say "KEY_AUTHORIZED=$([ -s /root/.ssh/authorized_keys ] && grep -cq . /root/.ssh/authorized_keys && echo yes || echo no)"
  # ── the WSL traps, measured rather than assumed ───────────────────────────────────────────────
  # (ai/context/running-on-wsl.md) A checkout on /mnt/c is 9p with no real permissions, `chmod` a
  # silent no-op, and acme.json's 600 impossible — the office must live on the distro's own ext4.
  # systemd is what runs Docker here, and it is off unless /etc/wsl.conf enables it.
  say "WSL=$([ -n "${WSL_DISTRO_NAME:-}" ] && echo "${WSL_DISTRO_NAME}" || echo no)"
  say "SYSTEMD=$( [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ] && echo yes || echo "no (PID 1 is $(cat /proc/1/comm 2>/dev/null || echo unknown))")"
  for p in /opt/digital-office /root/deployment-hacohen "$HOME/deployment-hacohen"; do
    [ -e "$p" ] || continue
    say "PATH_FS[$p]=$(stat -f -c %T "$p" 2>/dev/null || echo unknown)"
  done
  say "CHECKOUT=$([ -d /opt/digital-office ] && echo present || echo absent)"
  say "MNT_C=$([ -d /mnt/c ] && echo present || echo absent)"
}

if [ "$CHECK" = "1" ]; then
  say "# --check: nothing was changed"
  facts
  exit 0
fi

[ "$(id -u)" = "0" ] || die "must run as root (the fleet logs in as root; there is no sudo in this script)"
[ -n "$KEY" ] || die "--key is required (the office's public key, from computers' /api/computers → office_key.public_key)"

# ── the platform this office can install onto ────────────────────────────────────
# `debian-install.sh` (the converge's engine step) is written for the Debian family, and the
# checkpoint/resume it uses is systemd's. Discovering that on a different distribution here is one
# sentence instead of an hour of a converge failing at container start.
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu|raspbian|linuxmint) : ;;
    *) die "unsupported distribution '${ID:-unknown}' — the office's installer is Debian-family only (Debian/Ubuntu)" ;;
  esac
else
  die "no /etc/os-release — cannot tell whether this machine is Debian-family"
fi

# ── prerequisites: a door, and the tools the converge needs to use it ────────────
export DEBIAN_FRONTEND=noninteractive
say "# installing prerequisites (openssh-server, git, curl, ca-certificates, jq) — idempotent"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  openssh-server git curl ca-certificates jq tar gzip >/dev/null

# ── sshd: up, and staying up ────────────────────────────────────────────────────
# The machine this was written for answered `Connection refused` on :22 — reachable, but nothing
# listening — so the fleet could not even prove the key. Enable AND start, and make it survive a
# reboot: a laptop that is asleep is a state the console reports; a laptop whose sshd never came back
# after a reboot is a fleet entry that is permanently "unreachable".
systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || die "ssh.service could not be started"

install -d -m 700 /root/.ssh
if [ "$HARDEN" = "1" ] || [ -n "$PORT" ]; then
  dropin=/etc/ssh/sshd_config.d/10-digital-office.conf
  : > "$dropin"
  say "# written by apps/dgo-extend/office-setup.sh — the office's own sshd settings" >> "$dropin"
  if [ -n "$PORT" ]; then
    # The port is declared, not discovered: 2222 is what this office's fleet entry dials (a WSL
    # machine sharing the Windows host's network has 22 spoken for, and the owner's own setup opens
    # 2222). Writing it here keeps the door and the declaration from drifting apart.
    case "$PORT" in
      ''|*[!0-9]*) die "--port must be a number" ;;
    esac
    printf 'Port %s\n' "$PORT" >> "$dropin"
    say "# sshd will listen on port $PORT"
  fi
  if [ "$HARDEN" = "1" ]; then
    # Keys only for root, and only when the owner asked for it. This is the machine's own setting and
    # the office's own rule (nothing types a password anywhere), but it is also the one change here
    # that can lock a person out of his own machine — so it is opt-in and it is his act.
    printf '%s\n' \
      'PermitRootLogin prohibit-password' \
      'PubkeyAuthentication yes' \
      'PasswordAuthentication no' \
      >> "$dropin"
  fi
  # Debian's stock sshd_config has no `Include` directive on very old releases, where a drop-in would
  # be silently ignored — the door would still work on a key, but the hardening would not, which is
  # the worse of the two surprises. Say so instead of assuming.
  grep -qE '^\s*Include\s+/etc/ssh/sshd_config\.d/\*' /etc/ssh/sshd_config \
    || say "WARN: /etc/ssh/sshd_config has no Include for sshd_config.d — $dropin may be ignored on this release"
fi

touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
if grep -qF "$(printf '%s' "$KEY" | awk '{print $2}')" /root/.ssh/authorized_keys 2>/dev/null; then
  say "# the office key is already authorized"
else
  printf '%s\n' "$KEY" >> /root/.ssh/authorized_keys
  say "# the office key was added to /root/.ssh/authorized_keys"
fi
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true

# ── the report the converge reads ───────────────────────────────────────────────
say "# --- facts ---"
facts
say "SETUP_OK"
say "# next: apps/dgo-extend converge (machine → engine → code → env → state → run → health → link)."
say "#   Docker 29 present → engine.replace_docker: true, or traefik will route nothing on this machine."
