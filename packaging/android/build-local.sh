#!/usr/bin/env bash
# build-local.sh — THE PHONE APP, BUILT WHERE THE OFFICE RUNS (DGO-1328)
#
# The app has had exactly one builder: a GitHub self-hosted runner on the Dell, a laptop that is off the
# network most of the time. Every round of the owner's ping-pong ended the same way — «the build is waiting
# for a machine that is not here». This script removes that single point: with Docker alone, on any Linux
# machine (this office's own HP included), it produces what android-app.yml produces — `libdgo.so` and
# `libforward-auth.so` for the phone, the office root the core reads where there is no checkout, and a
# debug-signed APK — from the code in THIS checkout, with no GitHub, no token and no runner.
#
# What it does NOT do, by design: the office's machine (QEMU + the guest image) is built by
# android-engine.yml from Termux's recipe under our package name, and is not here. An APK from this script
# carries the core alone (the same shape as `[android-core]`): its console, its sign-in, its screens and its
# status answer, and a container app says the machine is not on this phone. A phone that already has a
# machine (or an APK built with DGO_MACHINE_URL) takes it as usual.
#
#   ./packaging/android/build-local.sh                       # arm64 (a phone), core only
#   ./packaging/android/build-local.sh --abi x86_64          # an emulator on an x86_64 host
#   ./packaging/android/build-local.sh --door https://…      # the business's door, compiled in (DGO-1332)
#   ./packaging/android/build-local.sh --check               # …and prove the office root answers, first
#   ./packaging/android/build-local.sh --clean               # drop the cached SDK/gradle and start over
#
# Everything cacheable lands in ci-artifacts/android (git-ignored): the SDK, Gradle, the Gradle home and the
# one debug key — a second run is minutes, not a download. Nothing in the checkout is written except the
# build's own ignored paths (app/build, jniLibs, assets/office-root.zip), and what it leaves is the caller's
# own: the containers run as this user, never as root (root-owned sources cost three sessions already).
#
# The debug key: DGO_ANDROID_DEBUG_KEYSTORE_FILE (the same variable android-app.yml's build reads) or the
# cache's own. An APK signed by another key does NOT install over the last (INSTALL_FAILED_UPDATE_INCOMPATIBLE),
# so the script prints the signer's SHA-256: the same line as `apksigner verify` on the APK already on the
# phone means this one installs over it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(git -C "${here}" rev-parse --show-toplevel)"
cache="${DGO_ANDROID_CACHE:-${repo}/ci-artifacts/android}"
out="${repo}/ci-artifacts/dgo-1328/apk"
abi=arm64-v8a
door="${DGO_PHONE_DOOR:-}"
version=""
code=""
check=0
clean=0
image=dgo-android-build:local
gradle_version=8.10.2
bt_version=35.0.0
platform=android-35
say() { printf '\033[36m[build-local]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[build-local] %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out) [ $# -ge 2 ] || die "--out needs a directory"; out="$2"; shift ;;
    --out=*) out="${1#*=}" ;;
    --abi) [ $# -ge 2 ] || die "--abi needs arm64-v8a or x86_64"; abi="$2"; shift ;;
    --abi=*) abi="${1#*=}" ;;
    --door) [ $# -ge 2 ] || die "--door needs a URL"; door="$2"; shift ;;
    --door=*) door="${1#*=}" ;;
    --version) [ $# -ge 2 ] || die "--version needs a value"; version="$2"; shift ;;
    --version-code) [ $# -ge 2 ] || die "--version-code needs a value"; code="$2"; shift ;;
    --check) check=1 ;;
    --clean) clean=1 ;;
    -h|--help) sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done
case "${abi}" in arm64-v8a|x86_64) ;; *) die "--abi is arm64-v8a or x86_64, not ${abi}" ;; esac
command -v docker >/dev/null || die "docker is needed (and the engine it talks to)"
docker info >/dev/null 2>&1 || die "the docker engine does not answer"
[ -z "${door}" ] || [[ "${door}" =~ ^https://[A-Za-z0-9._~:/%-]+$ ]] || die "--door is not a plain https URL"

# ── room, before anything big is pulled (this disk is shared with every container of the office) ──────
avail_gb="$(df -Pk "${repo}" | awk 'NR==2 {print int($4/1024/1024)}')"
[ "${avail_gb}" -ge 6 ] || die "${avail_gb} GB free where the checkout lives: the toolchain and the build need 6"

if [ "${clean}" = 1 ]; then
  say "clean: dropping ${cache}"
  rm -rf "${cache}"
fi
mkdir -p "${cache}/sdk" "${cache}/gradle" "${cache}/gradle-home" "${cache}/home" "${cache}/bin"
chmod 700 "${cache}"   # the debug key lives here

# ── the toolchain image: JDK 17 (what AGP 8.7 wants) and the few tools the build reads ───────────────
if ! docker image inspect "${image}" >/dev/null 2>&1; then
  say "the toolchain image (once: JDK 17, curl, unzip, git)"
  docker build -q -t "${image}" -f - "${here}" <<'DOCKERFILE' >/dev/null
FROM eclipse-temurin:17-jdk-jammy
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip zip curl ca-certificates git python3 \
 && rm -rf /var/lib/apt/lists/*
DOCKERFILE
fi

# ONE way into the toolchain: this user (never root), this checkout, this cache.
run_tc() {
  docker run --rm -u "$(id -u):$(id -g)" \
    -e HOME="${cache}/home" \
    -e ANDROID_HOME="${cache}/sdk" -e ANDROID_SDK_ROOT="${cache}/sdk" \
    -e GRADLE_USER_HOME="${cache}/gradle-home" \
    -e DGO_ANDROID_ABI="${abi}" \
    -e DGO_APP_VERSION="${version:-0.2.local-$(date -u +%m%d-%H%M)}" \
    -e DGO_APP_VERSION_CODE="${code:-$(date -u +%y%m%d%H)}" \
    -e DGO_PHONE_DOOR="${door}" \
    -e DGO_ANDROID_DEBUG_KEYSTORE_FILE="${DGO_ANDROID_DEBUG_KEYSTORE_FILE:-${cache}/debug.keystore}" \
    -e DGO_MACHINE_URL="${DGO_MACHINE_URL:-}" -e DGO_MACHINE_MANIFEST="${DGO_MACHINE_MANIFEST:-}" \
    -v "${repo}:${repo}" -v "${cache}:${cache}" -w "${repo}/packaging/android" \
    "${image}" "$@"
}
gradle="${cache}/gradle/gradle-${gradle_version}/bin/gradle"

# ── the SDK and Gradle, in the cache: a second run reads them, never downloads ───────────────────────
if [ ! -x "${cache}/sdk/cmdline-tools/latest/bin/sdkmanager" ]; then
  say "the Android SDK command-line tools"
  run_tc bash -c '
    set -euo pipefail
    t="$(mktemp -d)"; trap "rm -rf \"${t}\"" EXIT
    curl -fsSL -o "${t}/tools.zip" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
    mkdir -p "${ANDROID_HOME}/cmdline-tools"
    unzip -q "${t}/tools.zip" -d "${t}/x"
    rm -rf "${ANDROID_HOME}/cmdline-tools/latest"
    mv "${t}/x/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest"
    # `< <(yes)`, not `yes |`: under pipefail a happy `yes` killed by SIGPIPE fails the step
    "${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null < <(yes)
  ' || die "the SDK command-line tools did not install"
fi
if [ ! -d "${cache}/sdk/platforms/${platform}" ] || [ ! -d "${cache}/sdk/build-tools/${bt_version}" ]; then
  say "platform ${platform} and build-tools ${bt_version}"
  run_tc bash -c "
    set -euo pipefail
    \"\${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager\" --licenses >/dev/null < <(yes)
    \"\${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager\" 'platforms;${platform}' 'build-tools;${bt_version}' >/dev/null
  " || die "the SDK packages did not install"
fi
if [ ! -x "${gradle}" ]; then
  say "gradle ${gradle_version}"
  run_tc bash -c "
    set -euo pipefail
    t=\"\$(mktemp -d)\"; trap 'rm -rf \"\${t}\"' EXIT
    curl -fsSL -o \"\${t}/g.zip\" https://services.gradle.org/distributions/gradle-${gradle_version}-bin.zip
    unzip -q \"\${t}/g.zip\" -d '${cache}/gradle'
  " || die "gradle did not install"
fi

# ── the debug key: one across runs, or the caller's (DGO_ANDROID_DEBUG_KEYSTORE_FILE) ────────────────
ks="${DGO_ANDROID_DEBUG_KEYSTORE_FILE:-${cache}/debug.keystore}"
if [ ! -f "${ks}" ]; then
  say "a debug key (kept in the cache: the next APK installs over this one)"
  run_tc bash -c "keytool -genkeypair -keystore '${ks}' -storepass android -keypass android \
    -alias androiddebugkey -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 10000" \
    || die "the debug key was not made"
fi
fingerprint() {   # keytool prints upper case with colons, apksigner lower case without: one spelling
  run_tc bash -c "keytool -list -v -keystore '${ks}' -storepass android -alias androiddebugkey" \
    | awk '/SHA256:/ && !p {print $NF; p=1}' | tr -d ':' | tr 'A-F' 'a-f'
}
key_fp="$(fingerprint)"
[ -n "${key_fp}" ] || die "the debug key has no SHA256 fingerprint line"
say "debug key ${key_fp}"

# ── dgo and forward-auth for the phone, as the app's native libraries ────────────────────────────────
# (an app that targets Android 10+ runs only what it carries in its native-library directory — W^X — so
# both programs go in named lib*.so, and dgo carries the console's files, built in with consoleembed)
lib="${here}/app/src/main/jniLibs/${abi}"
# android/arm64 is Go's own target. android/amd64 is NOT: Go refuses it without cgo ("android/amd64
# requires external (cgo) linking"), and the emulator does not need it — it runs a linux/amd64 static Go
# binary as it is, which is how android-install-check ran the core (DGO-1333's x86_64 libs, X86=1).
goarch=arm64; goos=android
[ "${abi}" = x86_64 ] && { goarch=amd64; goos=linux; }
say "dgo and forward-auth for ${abi} (console embedded)"
snapshot="${repo}/packaging/dgo/internal/console/snapshot"
rm -rf "${snapshot}" && mkdir -p "${snapshot}" "${lib}"
cp -R "${repo}/platform-base/console/static" "${repo}/platform-base/console/modules.yaml" "${snapshot}/"
git -C "${repo}" show -s --format=%ct HEAD > "${snapshot}/commit-time"
run_go() {   # run_go <workdir> <shell command>
  docker run --rm -u "$(id -u):$(id -g)" -e HOME="${cache}/home" -e GOCACHE="${cache}/home/go-cache" \
    -e GOFLAGS=-mod=mod -v "${repo}:${repo}" -v "${cache}:${cache}" -w "$1" golang:1.22 bash -c "$2"
}
run_go "${repo}/packaging/dgo" "CGO_ENABLED=0 GOOS=${goos} GOARCH=${goarch} go build -trimpath -buildvcs=false -tags consoleembed \
  -ldflags '-s -w -X main.version=${version:-0.2.local}' -o '${lib}/libdgo.so' ." \
  || die "dgo did not build for android/${goarch}"
run_go "${repo}/platform-base/forward-auth" "CGO_ENABLED=0 GOOS=${goos} GOARCH=${goarch} go build -trimpath -buildvcs=false \
  -ldflags '-s -w' -o '${lib}/libforward-auth.so' ." || die "forward-auth did not build for android/${goarch}"
ls -la "${lib}"

# ── the office root: what the core reads where there is no checkout ──────────────────────────────────
say "the office root (state, manifests, the console's registry, the screens the core answers itself)"
run_go "${repo}/packaging/dgo" "CGO_ENABLED=0 go build -trimpath -buildvcs=false -o '${cache}/bin/dgo' ." \
  || die "a host dgo did not build (office-root.sh renders with it)"
root="$(mktemp -d)"; trap 'rm -rf "${root}"' EXIT
# The host dgo runs OUTSIDE the checkout: a dgo built into it walks UP from its own directory and reads
# THIS office — the check below then answered installed=true for a phone's root (measured 2026-11-06;
# android-app.yml builds it in $RUNNER_TEMP for the same reason, without the note).
cp "${cache}/bin/dgo" "${root}/dgo"
DGO="${root}/dgo" bash "${here}/native/office-root.sh" "${root}/office-root" \
  || die "the office root was refused (above)"
mkdir -p "${here}/app/src/main/assets"   # gradle's asset root: absent in a fresh checkout (it is built)
python3 - "${root}/office-root" "${here}/app/src/main/assets/office-root.zip" <<'PY' \
  || die "assets/office-root.zip was not made"
import pathlib, sys, zipfile
root, apk_zip = pathlib.Path(sys.argv[1]), sys.argv[2]
files = sorted(p for p in root.rglob("*") if p.is_file())
with zipfile.ZipFile(apk_zip, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f, f.relative_to(root).as_posix())
print(f"assets/office-root.zip: {pathlib.Path(apk_zip).stat().st_size} bytes, {len(files)} files")
PY

# ── the check android-app.yml makes, here: the native control plane answers from that root ───────────
if [ "${check}" = 1 ]; then
  say "the office root proves itself: be-child control answers /api/office from it"
  # run from a scratch directory, as android-app.yml does: started in the checkout, the core reads THIS
  # office's .env and answers installed=true — a phone's root is a fresh office, and that is what is asked
  env -C "${root}" DGO_OFFICE_ROOT="${root}/office-root" BBOX_CONTROL_PLANE= \
    "${root}/dgo" be-child control --listen 127.0.0.1:0 --container http://127.0.0.1:9 \
    2> "${root}/control.log" &
  plane=$!
  at=""
  for _ in $(seq 1 50); do
    at="$(grep -o 'answering on http://127\.0\.0\.1:[0-9]*' "${root}/control.log" 2>/dev/null | head -1 | sed 's/^answering on //')" || true
    [ -n "${at}" ] && curl -fsS "${at}/healthz" >/dev/null 2>&1 && break
    sleep 0.2
  done
  [ -n "${at}" ] || { cat "${root}/control.log"; kill "${plane}" 2>/dev/null || true; die "the control plane did not answer"; }
  office="$(curl -fsS "${at}/api/office" || true)"
  kill "${plane}" 2>/dev/null || true
  say "/api/office ${office}"
  printf '%s' "${office}" | python3 -c 'import json,sys
o = json.load(sys.stdin)
sys.exit(0 if o.get("installed") is False else "not a fresh core office: %r" % (o,))' \
    || die "the office root does not answer as a fresh core office"
fi

# ── the APK ──────────────────────────────────────────────────────────────────────────────────────────
say "gradle assembleDebug (${abi}, heap 1400m: this machine shares its memory with the whole office)"
mkdir -p "${out}"
run_tc bash -c "'${gradle}' --no-daemon --max-workers=2 -Dorg.gradle.jvmargs=-Xmx1400m assembleDebug" \
  || die "gradle failed (above)"
apk_in="${here}/app/build/outputs/apk/debug/app-debug.apk"
[ -f "${apk_in}" ] || die "gradle reported no failure, and there is no ${apk_in}"
apk="${out}/dgo-android-local-${abi}.apk"
cp "${apk_in}" "${apk}"

# ── said, not assumed: the signer IS this key, the libraries and the root are inside ─────────────────
run_tc bash -c "bt=\$(ls -d \"\${ANDROID_HOME}\"/build-tools/* | sort -V | tail -1)
  \"\${bt}/apksigner\" verify --print-certs '${apk}' \
    | sed -n 's/^Signer #1 certificate SHA-256 digest: /apksigner says /p'" \
  || die "apksigner could not verify ${apk}"
python3 - "${apk}" "${abi}" <<'PY' || die "the APK is missing its own parts"
import sys, zipfile
apk, abi = sys.argv[1], sys.argv[2]
names = set(zipfile.ZipFile(apk).namelist())
want = [f"lib/{abi}/libdgo.so", f"lib/{abi}/libforward-auth.so", "assets/office-root.zip"]
missing = [w for w in want if w not in names]
print("APK parts:", ", ".join(w for w in want if w in names))
sys.exit(1 if missing else 0)
PY
size="$(stat -c %s "${apk}")"
sha="$(sha256sum "${apk}" | cut -d' ' -f1)"
say "APK ${apk}"
say "$(python3 -c "print(f'{${size}/1048576:.1f} MiB')"), sha256 ${sha}"
say "signed by ${key_fp} — the phone's last APK installs over only if this is the same key"
printf '%s\n' "${sha}" > "${apk}.sha256"
