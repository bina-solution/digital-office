#!/usr/bin/env bash
# BinaOS installer — self-extracting, byte-addressed segments appended after this header.
#
# The @@PLACEHOLDER@@ values are substituted by packaging/linux/build-run.sh once the segment sizes
# are known. Do not run this file directly; it is only meaningful with a payload attached.
#
# SHAPE
#   [ this header      ]  offset 0 .. HEADER_LEN
#   [ SEG control      ]  manifest.json, manifest.sigstore.json, cosign.pub, compose, units
#   [ SEG runtime      ]  a local deb/rpm repo for this host's distro
#   [ SEG images       ]  the image bundle — NEVER extracted, piped straight into `docker load`
#
# WHY BYTE OFFSETS RATHER THAN makeself/AppImage
# makeself's default path extracts into $TMPROOT, which is fatal when /tmp is a tmpfs — and a 3 GB
# payload on a RAM-backed /tmp is exactly the shape of failure this design exists to avoid.
# AppImage is disqualified twice: it needs FUSE 2 (renamed/removed on modern distros), and its
# --appimage-extract-and-run fallback materialises the whole payload in the CWD. This is conda
# constructor's approach instead: dd per segment, each piped straight to its consumer.
set -euo pipefail

HEADER_LEN=@@HEADER_LEN@@
SEG_CONTROL_OFF=@@SEG_CONTROL_OFF@@;  SEG_CONTROL_LEN=@@SEG_CONTROL_LEN@@
SEG_RUNTIME_OFF=@@SEG_RUNTIME_OFF@@;  SEG_RUNTIME_LEN=@@SEG_RUNTIME_LEN@@
SEG_IMAGES_OFF=@@SEG_IMAGES_OFF@@;    SEG_IMAGES_LEN=@@SEG_IMAGES_LEN@@
VERSION=@@VERSION@@

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
PREFIX="${BINAOS_PREFIX:-/opt/binaos}"
CONFIG="${BINAOS_CONFIG:-/etc/binaos}"
KEEP_STAGING=0
ACTION=install
SKIP_VERIFY=0

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)       PREFIX="${2:?}"; shift ;;
    --config)       CONFIG="${2:?}"; shift ;;
    --check)        ACTION=check ;;
    --skip-verify)  SKIP_VERIFY=1 ;;
    --extract-only) ACTION=extract; KEEP_STAGING=1 ;;
    --version)      echo "${VERSION}"; exit 0 ;;
    -h|--help)      sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

# ── read a byte range out of ourselves ────────────────────────────────────────────────────────
# iflag=skip_bytes,count_bytes is what makes this exact rather than block-quantised; without it a
# non-block-aligned offset silently reads the wrong bytes.
seg() {
  dd if="${SELF}" bs=1M iflag=skip_bytes,count_bytes skip="$1" count="$2" status=none
}

# ── preflight ─────────────────────────────────────────────────────────────────────────────────
[ "$(id -u)" = 0 ] || die "must run as root (one sudo, at install — see packaging/README.md)"

command -v dd   >/dev/null || die "dd not found"
command -v zstd >/dev/null || die "zstd not found — install it, or use the --extract-only path"

say "BinaOS ${VERSION}"

# Verify BEFORE doing anything. `tee`ing into `docker load` and checking afterwards is not
# verification — by then the images are already in the store.
STAGING="${PREFIX}/.staging"
mkdir -p "${STAGING}"
seg "${SEG_CONTROL_OFF}" "${SEG_CONTROL_LEN}" | zstd -dc | tar -x -C "${STAGING}"
ok "control segment extracted"

# The manifest CANNOT live inside the control segment: it records the sha256 of the FINISHED file,
# so it is written after assembly. It ships BESIDE the artifact.
#
# The first fresh-machine test caught what that cost: --check read the manifest from the staged
# control segment, found nothing, and skipped the whole-artifact hash SILENTLY — printing "check
# only - nothing installed" as though it had verified something. An integrity check that quietly
# does nothing is worse than none, because the customer believes they checked.
# The manifest records the sha256 of the FINISHED file, so it cannot live inside that file — it is
# written after assembly. A sibling manifest.json is therefore the only source, and that makes it
# possible to check an artifact against a manifest describing a DIFFERENT one.
#
# That is not hypothetical: a directory holding two releases did exactly this. r5 was checked
# against r3's leftover manifest.json and refused to install with "artifact sha256 MISMATCH -
# corrupt or tampered". Nothing was corrupt or tampered; the expected hash simply described another
# file. Keeping the previous release's manifest next to the new one is an ordinary thing to do, and
# it turned a good artifact into an alarming security warning — the kind that teaches people to
# ignore security warnings.
#
# So match on version before trusting a manifest, and say plainly when one is for something else.
MANIFEST=""
for cand in "${STAGING}/manifest.json" "$(dirname "${SELF}")/manifest.json"; do
  [ -f "${cand}" ] || continue
  # A manifest that names a different version is describing another artifact. Say so plainly rather
  # than letting it fail later as a hash mismatch, which reads as tampering.
  mver="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('version',''))" "${cand}" 2>/dev/null || echo '')"
  if [ -n "${mver}" ] && [ -n "${VERSION}" ] && [ "${mver}" != "${VERSION}" ]; then
    printf '  \033[33mwarn\033[0m ignoring %s — it describes %s, not %s\n' "${cand}" "${mver}" "${VERSION}"
    continue
  fi
  MANIFEST="${cand}"; break
done
SIGFILE=""
for cand in "${STAGING}/manifest.sigstore.json" "$(dirname "${SELF}")/manifest.sigstore.json"; do
  [ -f "${cand}" ] && { SIGFILE="${cand}"; break; }
done

if command -v cosign >/dev/null 2>&1 && [ -f "${STAGING}/cosign.pub" ] && [ -n "${SIGFILE}" ]; then
  cosign verify-blob --key "${STAGING}/cosign.pub" --bundle "${SIGFILE}" \
      --insecure-ignore-tlog=true "${MANIFEST}" >/dev/null \
    || die "manifest signature INVALID — refusing to install"
  ok "manifest signature verified"
else
  printf '  \033[33mwarn\033[0m cosign not present — signature NOT verified\n'
fi

if [ "${SKIP_VERIFY}" = 1 ]; then
  printf '  \033[33mwarn\033[0m integrity NOT verified (--skip-verify)\n'
elif [ -z "${MANIFEST}" ]; then
  die "no manifest.json beside the artifact — integrity cannot be checked.
       Download manifest.json from the same place as the .run, or re-run with --skip-verify
       if you knowingly accept an unverified install."
else
  want="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['artifact']['sha256'])" \
          "${MANIFEST}" 2>/dev/null || echo '')"
  [ -n "${want}" ] || die "manifest.json is unreadable or carries no artifact.sha256"
  got="$(sha256sum "${SELF}" | cut -d' ' -f1)"
  [ "${want}" = "${got}" ] || die "artifact sha256 MISMATCH — corrupt or tampered
       expected ${want}
       actual   ${got}"
  ok "artifact sha256 verified (${got:0:16}…)"
fi

if [ "${ACTION}" = check ]; then
  say "check only — nothing installed"
  rm -rf "${STAGING}"
  exit 0
fi

# ── docker: use theirs, or install ours ───────────────────────────────────────────────────────
# Deliberately conservative: never upgrade, never flip a storage driver, never touch a daemon we
# did not install. Rationale for each rule is in packaging/linux.md.
# ── which engine runs the stack ───────────────────────────────────────────────────────────────
# Preference order, and the reasoning:
#   1. a host engine on 28.x        — reuse it; no second daemon, no extra disk
#   2. anything else (incl. none)   — run OUR pinned engine on a private socket
#
# The old logic refused when the host had Docker 29 and stopped there. That is self-defeating: we
# ship 78 MB of pinned engine precisely so the host's version stops mattering. The test box runs
# 29.1.3, where traefik v3.3 finds zero routers and every route 404s while reporting healthy —
# exactly the case the bundled engine exists for.
BINAOS_SOCK=/run/binaos-docker.sock
USE_HOST=0

if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
  hostver="$(docker version --format '{{.Server.Version}}')"
  hostmaj="${hostver%%.*}"
  case "$(docker info --format '{{.SecurityOptions}}' 2>/dev/null)" in
    *rootless*) hostmaj=0 ;;   # rootless cannot bind :80/:443 — treat as unusable
  esac
  if [ "${hostmaj}" = "28" ]; then
    USE_HOST=1
    ok "reusing the host engine (Docker ${hostver})"
  else
    say "host has Docker ${hostver}; this platform needs 28.x — using the bundled engine instead"
  fi
else
  say "no usable host engine — using the bundled one"
fi

if [ "${USE_HOST}" = 0 ]; then
  seg "${SEG_RUNTIME_OFF}" "${SEG_RUNTIME_LEN}" | zstd -dc | tar -x -C "${STAGING}"
  [ -f "${STAGING}/install-runtime.sh" ] \
    || die "this build carries no engine and the host has none usable"
  bash "${STAGING}/install-runtime.sh" || die "the bundled engine failed to install"
  export DOCKER_HOST="unix://${BINAOS_SOCK}"
  ok "engine ready on ${BINAOS_SOCK}"
fi

# ── disk, on the docker data root and not on / ────────────────────────────────────────────────
# The classic overlay2 loader untars the ENTIRE archive into <data-root>/tmp before importing, so
# peak is roughly scratch + final. Refuse with the real number rather than dying half way through.
ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/binaos-docker)"
STORE="$(docker info --format '{{.Driver}}' 2>/dev/null || echo overlay2)"
case "${STORE}" in containerd*) need_gb=15 ;; *) need_gb=25 ;; esac
avail_gb=$(( $(df -Pk "${ROOT}" | awk 'NR==2{print $4}') / 1024 / 1024 ))
[ "${avail_gb}" -ge "${need_gb}" ] \
  || die "need ${need_gb} GiB free on ${ROOT} (driver: ${STORE}); have ${avail_gb} GiB"
ok "${avail_gb} GiB free on ${ROOT}"

# ── the images: streamed, never a file ────────────────────────────────────────────────────────
# --long=27 must match what packaging/build-bundle.sh compressed with. zstd's decompressor
# defaults to a 128 MiB window; a larger windowLog at compression time makes this FAIL unless the
# same flag is passed here.
say "loading images (this is the long part)"
seg "${SEG_IMAGES_OFF}" "${SEG_IMAGES_LEN}" | zstd -dc --long=27 | docker load
ok "images loaded"

# ── install the program ───────────────────────────────────────────────────────────────────────
mkdir -p "${PREFIX}" "${CONFIG}"
cp -r "${STAGING}/platform/." "${PREFIX}/" 2>/dev/null || true
[ -f "${CONFIG}/binaos.env" ] || cp "${STAGING}/binaos.env.example" "${CONFIG}/binaos.env" 2>/dev/null || true
# compose reads `.env` from the PROJECT directory for ${VAR} interpolation; --env-file alone is not
# enough, and without it every interpolated value silently becomes empty. A fresh install failed
# with `env file /opt/binaos/.env not found`.
ln -sf "${CONFIG}/binaos.env" "${PREFIX}/.env"

# ── adapt the compose to THIS host ────────────────────────────────────────────────────────────
# ORDER MATTERS, and getting it wrong is why this shipped broken twice. This block rewrites the
# INSTALLED compose, so it has to run AFTER the copy above. It used to run before, which meant on
# a fresh machine the file did not exist yet and the whole block was skipped in silence, and on a
# machine with a previous install it edited the OLD file and the copy then overwrote it. Both
# paths printed "capped 0 cpu limit(s)" and looked fine.
#
# Two things the shipped compose cannot know at build time.
#
# CPU LIMITS. deploy.resources.limits.cpus carries values sized for the production host. Docker
# REFUSES outright when a limit exceeds the host:
#   "range of CPUs is from 0.01 to 4.00, as there are only 4 CPUs available"
# — not a warning, the container never starts. A customer laptop with 2 cores could not run this
# at all. Capping belongs here and not in the generator, because the builder's core count has
# nothing to do with the customer's. `*_CPUS` environment values carry the same production sizing
# into the app's own worker pools, so they get capped by the same rule.
#
# EXTERNAL VOLUMES. compose creates managed volumes itself but refuses to create `external: true`
# ones — that keyword means "something else provides this". The installer already creates the
# external traefik-network; not doing the same for volumes was an arbitrary asymmetry that killed
# a fresh install with `external volume "wa_media" not found`.
RUNTIME_COMPOSE="${PREFIX}/.generated/compose.runtime.yml"
# Not `if [ -f ]`. A missing compose after a successful copy means the artifact is malformed, and
# continuing would produce an install that reports success and cannot start.
[ -f "${RUNTIME_COMPOSE}" ] || die "installed tree has no .generated/compose.runtime.yml"

# One implementation, in a file that can be run again against an installed tree — not a heredoc that
# only exists inside a 2 GB artifact. When we land our own engine we also pass its socket, so the
# services that watch the daemon watch OURS.
ADAPT_SOCK=""
[ "${USE_HOST}" = 0 ] && ADAPT_SOCK="${BINAOS_SOCK}"
# Separate engines isolate containers, images, volumes and networks - but not host PORTS. On a
# machine that also runs CI for this same platform, both want 80/443/5432/6379 and the second to
# start fails to bind. BINAOS_PORT_OFFSET moves ours out of the way; 0 (the default) keeps the
# ordinary single-install behaviour.
PORT_OFFSET="${BINAOS_PORT_OFFSET:-0}"
[ -f "${CONFIG}/binaos.env" ] && PORT_OFFSET="$(. "${CONFIG}/binaos.env" 2>/dev/null; echo "${BINAOS_PORT_OFFSET:-${PORT_OFFSET}}")"
python3 "${STAGING}/adapt-host.py" "${RUNTIME_COMPOSE}" \
  --cores "$(nproc)" --socket "${ADAPT_SOCK}" --port-offset "${PORT_OFFSET}" \
  || die "could not adapt the compose to this host"

# Create every external volume the project expects. Networks too, for the same reason.
for v in $(python3 -c "
import yaml,sys
d=yaml.safe_load(open(sys.argv[1],encoding='utf-8'))
print(' '.join(k for k,s in (d.get('volumes') or {}).items()
               if isinstance(s,dict) and s.get('external')))" "${RUNTIME_COMPOSE}"); do
  docker volume create "${v}" >/dev/null 2>&1 && ok "created external volume ${v}"
done
for n in $(python3 -c "
import yaml,sys
d=yaml.safe_load(open(sys.argv[1],encoding='utf-8'))
print(' '.join(k for k,s in (d.get('networks') or {}).items()
               if isinstance(s,dict) and s.get('external')))" "${RUNTIME_COMPOSE}"); do
  docker network create "${n}" >/dev/null 2>&1 && ok "created external network ${n}"
done

# The install receipt is what makes `--remove-docker` safe later: if the engine pre-existed,
# uninstall must never remove it.
cat > "${CONFIG}/install-receipt.json" <<EOF
{"version":"${VERSION}","prefix":"${PREFIX}","config":"${CONFIG}",
 "engine":"$([ "${USE_HOST}" = 1 ] && echo host || echo bundled)",
 "docker_host":"$([ "${USE_HOST}" = 1 ] && echo default || echo "unix://${BINAOS_SOCK}")"}
EOF
# The stack must talk to the SAME engine after a reboot, not whichever socket happens to exist.
if [ "${USE_HOST}" = 0 ]; then
  mkdir -p /etc/systemd/system/binaos.service.d
  printf '[Service]\nEnvironment=DOCKER_HOST=unix://%s\n' "${BINAOS_SOCK}" \
    > /etc/systemd/system/binaos.service.d/engine.conf
  # No `export` keyword. This file is read by systemd's EnvironmentFile=, which parses KEY=VALUE and
  # rejects anything else outright:
  #   Ignoring invalid environment assignment 'export DOCKER_HOST=...': /etc/binaos/engine.env
  # It survived only because the drop-in above sets the same variable. Shells that `.` this file
  # must export it themselves, which is the normal contract for an env file.
  printf 'DOCKER_HOST=unix://%s\n' "${BINAOS_SOCK}" > "${CONFIG}/engine.env"
fi

if [ -f "${STAGING}/binaos.service" ]; then
  install -m 0644 "${STAGING}/binaos.service" /etc/systemd/system/binaos.service
  systemctl daemon-reload
  systemctl enable binaos.service >/dev/null 2>&1 || true
  ok "systemd unit installed"
fi

[ "${KEEP_STAGING}" = 1 ] || rm -rf "${STAGING}"

say "installed. start with:  systemctl start binaos"
exit 0
@@PAYLOAD_FOLLOWS@@
