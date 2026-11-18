#!/usr/bin/env bash
# as-host-root.sh <command…> — run a command as root ON THIS HOST, with the access the office already has.
#
#   bash scripts/as-host-root.sh bash scripts/apparmor-host.sh install     # what `./bbox apparmor install` runs
#
# WHY (DGO-1822, DGO-1848; issues/the-agents-handed-the-owner-a-root-command-they-could-run-themselves-and-his-
# message-waited-half-an-hour.yaml). A host-policy step — the AppArmor profile, the laptop's power posture — needs
# root. On the Dell `sudo` asks for a password, so for two days the step was printed as «the owner's act» and waited
# for him at the machine, while the user running the office was in the docker group, which IS root on its own host.
# The owner: «יש לך הרשאות מלאות ויכולת להריץ הכל ואישור מלא ממני». Run once, it took six seconds.
#
# HOW, in order, never a password prompt:
#   1. already root → the command itself;
#   2. passwordless sudo (`sudo -n`) → through it;
#   3. ONLY where the office declares it (DGO_HOST_ROOT_VIA_DOCKER=1 in its .env — the company's own machines, by the
#      owner's standing word; a client's server keeps its human gate) and only through THIS host's own engine: a
#      privileged container that enters PID 1's namespaces (nsenter), so the command runs as the host's root.
# «This host's own engine», each checked, else refused (rc 3, why said, nothing run):
#   - a local unix socket (DOCKER_HOST and the docker context name no ssh:// or tcp:// — a remote engine's root is
#     another machine's, whatever its name);
#   - Linux, and the engine's name is this host's (a VM's engine — the Mac's Lima, Docker Desktop — or bbox inside a
#     container answer to another name); not rootless (its root is the user);
#   - and inside, before the command: the working directory is the SAME directory (device:inode) and the kernel the
#     same boot (boot_id) — a namespace that only looks like this host runs nothing.
# The helper image is pinned by digest (it runs as host root): pulled only when absent, and said when it cannot be.
# Every use of step 3 is logged to the host's journal (logger -t dgo-as-host-root).
#
# WHAT IT IS NOT. Nothing calls it on its own: only the verbs that SAY they change the host (`bbox apparmor
# install|uninstall`, `bbox host-power install|uninstall`). The command runs in the current directory, with PATH and
# the variables named in AS_ROOT_ENV (and DOCKER_HOST) — on the command line, so never a secret. What it starts
# outside systemd ends with the helper container (the host verbs use systemctl).
set -uo pipefail
export PYTHONIOENCODING=utf-8   # its words carry «» (G10: a Windows console on an ANSI codepage)

IMAGE="${BBOX_AS_ROOT_IMAGE:-alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc}"
T="${AS_ROOT_TIMEOUT:-20}"
BOOT_ID="${AS_ROOT_BOOT_ID:-/proc/sys/kernel/random/boot_id}"   # the kernel's boot (a test gives its own file)
[ $# -gt 0 ] || { echo "usage: $0 <command…>" >&2; exit 2; }
CMD="$*"

envs=()
for v in DOCKER_HOST ${AS_ROOT_ENV:-}; do
  case "${v}" in [A-Za-z_]*) ;; *) continue ;; esac
  case "${v}" in *[!A-Za-z0-9_]*) continue ;; esac
  [ -n "${!v+x}" ] && envs+=("${v}=${!v}")
done

if [ "$(id -u)" = 0 ]; then
  exec "$@"
fi
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  exec sudo -n env "${envs[@]+"${envs[@]}"}" "$@"
fi

refuse() {
  echo "as-host-root: cannot get root on this host: no passwordless sudo, and $1." >&2
  echo "as-host-root: nothing was run. Run it as root: sudo ${CMD}" >&2
  exit 3
}
[ "${DGO_HOST_ROOT_VIA_DOCKER:-}" = 1 ] \
  || refuse "this office does not declare root through its docker engine (DGO_HOST_ROOT_VIA_DOCKER=1 in .env: the company's own machines only)"
[ "$(uname -s)" = Linux ] || refuse "this is not a Linux host: its docker engine runs in a VM"
command -v docker >/dev/null 2>&1 || refuse "there is no docker here"
case "${DOCKER_HOST:-unix://}" in unix://*) ;; *) refuse "DOCKER_HOST is not a local socket (${DOCKER_HOST})" ;; esac
endpoint="$(timeout "${T}" docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)"
case "${endpoint:-unix://}" in unix://*) ;; *) refuse "the docker context is not a local socket (${endpoint})" ;; esac
name="$(timeout "${T}" docker info --format '{{.Name}}' 2>/dev/null)" || refuse "no docker engine answers"
[ -n "${name}" ] || refuse "the docker engine does not say its name"
[ "${name}" = "$(uname -n)" ] || refuse "the docker engine is another machine's («${name}»; this is «$(uname -n)»)"
sec="$(timeout "${T}" docker info --format '{{json .SecurityOptions}}' 2>/dev/null)"
[ -n "${sec}" ] || refuse "the docker engine does not say how it runs"
case "${sec}" in *rootless*) refuse "the docker engine is rootless" ;; esac
here="$(stat -c %d:%i . 2>/dev/null)" || refuse "this directory cannot be read"
boot="$(cat "${BOOT_ID}" 2>/dev/null)" && [ -n "${boot}" ] || refuse "this kernel does not say its boot"
if ! timeout "${T}" docker image inspect "${IMAGE}" >/dev/null 2>&1 \
   && ! timeout 120 docker pull -q "${IMAGE}" >/dev/null 2>&1; then
  refuse "its helper image could not be had (${IMAGE}; offline?)"
fi

echo "as-host-root: no passwordless sudo — running it as this host's root through its own docker engine (nsenter into PID 1)" >&2
command -v logger >/dev/null 2>&1 && logger -t dgo-as-host-root -- "$(id -un) via=docker cwd=${PWD}: ${CMD}" 2>/dev/null
exec docker run --rm -i --privileged --userns=host --pid=host --network host --pull never "${IMAGE}" \
  nsenter -t 1 -m -u -i -n -p -- \
  env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "${envs[@]+"${envs[@]}"}" \
  sh -c 'cd "$1" && [ "$(stat -c %d:%i .)" = "$2" ] && [ "$(cat "$4")" = "$3" ] \
           || { echo "as-host-root: inside, this is not the same directory on the same host — nothing run" >&2; exit 3; }
         shift 4; exec "$@"' sh "${PWD}" "${here}" "${boot}" "${BOOT_ID}" "$@"
