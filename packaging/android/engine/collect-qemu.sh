#!/usr/bin/env bash
# collect-qemu.sh <debs-dir> <out-dir> — qemu-system-aarch64 for the Android app, from the .debs Termux's
# recipe built under the app's package name (DGO-1071): the binary and the shared libraries it needs, each
# under a plain lib*.so name, ready for app/src/main/jniLibs/arm64-v8a/. Beside it, the zstd program QEMU's
# own dependency brings (libzstd-cli.so): the app unpacks the office's machine with it, an .xz that Java's
# framework has no reader for (DGO-1084).
#
# Why the renaming: Android extracts from an APK only files named lib*.so, so a versioned soname
# (libglib-2.0.so.0) never reaches the phone. EVERY library copied is renamed libdgoq-<name>.so — never a
# name the phone's own libraries have (its libz, its BoringSSL's libssl/libcrypto) — and every reference
# to it (DT_NEEDED, its own DT_SONAME) is patched with patchelf; two libraries that would share a name stop
# the run. The executable goes in as libqemu-system-aarch64.so: an app that targets Android 10+ may
# execute only what it carries in its native-library directory, where each finds its libraries through
# DT_RUNPATH $ORIGIN (below).
# The phone's own libraries (libc, libm, libdl, liblog, libandroid…) are never copied. Beside them,
# share/: QEMU's data (firmware, keymaps) and the prefix's etc/resolv.conf (slirp's DNS) — plain files for
# the APK's assets — which the app
# places under its files/usr — the prefix the build baked in.
set -euo pipefail
debs="${1:?usage: collect-qemu.sh <debs-dir> <out-dir>}"; out="${2:?usage}"
command -v patchelf >/dev/null || { echo "collect-qemu: patchelf is needed" >&2; exit 1; }
command -v readelf >/dev/null || { echo "collect-qemu: readelf (binutils) is needed" >&2; exit 1; }
work="$(mktemp -d)"; trap 'rm -rf "${work}"' EXIT
for d in "${debs}"/*.deb; do dpkg-deb -x "${d}" "${work}/root"; done
prefix="$(find "${work}/root" -type d -path '*/files/usr' | head -1)"
[ -n "${prefix}" ] || { echo "collect-qemu: no …/files/usr in the debs" >&2; exit 1; }
# each program and the name it goes in as
declare -A programs=([qemu-system-aarch64]=libqemu-system-aarch64.so [zstd]=libzstd-cli.so)
for p in "${!programs[@]}"; do
  [ -x "${prefix}/bin/${p}" ] || { echo "collect-qemu: ${prefix#"${work}"/}/bin/${p} is not in the debs" >&2; exit 1; }
done

android_own='^(libc|libm|libdl|liblog|libandroid|libEGL|libGLESv[123]|libvulkan|libmediandk|libOpenSLES)\.so$'
plain() { printf 'libdgoq-%s.so' "$(printf '%s' "$1" | sed 's/^lib//; s/\.so.*$//; s/[^A-Za-z0-9_+-]/_/g')"; }
needed() { readelf -d "$1" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p'; }

mkdir -p "${out}"
declare -A from=()
queue=()
for p in "${!programs[@]}"; do
  cp -L "${prefix}/bin/${p}" "${out}/${programs[${p}]}"
  queue+=("${out}/${programs[${p}]}")
done
while [ "${#queue[@]}" -gt 0 ]; do
  f="${queue[0]}"; queue=("${queue[@]:1}")
  for n in $(needed "${f}"); do
    [[ "${n}" =~ ${android_own} ]] && continue
    p="$(plain "${n}")"
    patchelf --replace-needed "${n}" "${p}" "${f}"
    if [ -n "${from[${p}]:-}" ]; then
      [ "${from[${p}]}" = "${n}" ] || { echo "collect-qemu: ${from[${p}]} and ${n} would both be ${p}" >&2; exit 1; }
      continue
    fi
    src="$(find "${prefix}/lib" -maxdepth 1 -name "${n}" | head -1)"
    [ -n "${src}" ] || { echo "collect-qemu: ${n} (needed by ${f##*/}) is in no deb" >&2; exit 1; }
    cp -L "${src}" "${out}/${p}"
    patchelf --set-soname "${p}" "${out}/${p}"
    patchelf --set-rpath '$ORIGIN' "${out}/${p}"   # its own needs beside it (below)
    from[${p}]="${n}"
    queue+=("${out}/${p}")
  done
done
# DT_RUNPATH $ORIGIN on the programs and on every library: each finds what it needs beside itself, in the
# app's native-library directory, with nothing in the environment. LD_LIBRARY_PATH alone is not enough:
# under an x86 emulator's ARM translation it is read by the translator's linker, never by the arm64 one
# (the orchestrator's APK 0.1.9 check, 2026-11-01: "library libdgoq-z.so not found", every lib there).
# bionic expands $ORIGIN in DT_RUNPATH. Single quotes: the dollar is the linker's, not the shell's.
for p in "${!programs[@]}"; do patchelf --set-rpath '$ORIGIN' "${out}/${programs[${p}]}"; done
for f in "${out}"/lib*.so; do
  [ "$(readelf -d "${f}" | sed -n 's/.*(RUNPATH).*\[\(.*\)\]/\1/p')" = '$ORIGIN' ] \
    || { echo "collect-qemu: ${f##*/} has no RUNPATH \$ORIGIN" >&2; exit 1; }
done
# the zstd program unpacks the office's machine, an .xz: a zstd built without liblzma could not, and
# that is said here, not on the phone (Termux's recipe builds it with -DZSTD_LZMA_SUPPORT=ON)
needed "${out}/libzstd-cli.so" | grep -qx 'libdgoq-lzma.so' \
  || { echo "collect-qemu: libzstd-cli.so does not need liblzma — this zstd cannot read the machine's .xz" >&2; exit 1; }
# what the binaries read at run time from the prefix they were built for, placed there by the app
mkdir -p "${out}/share"
[ -d "${prefix}/share/qemu" ] && cp -a "${prefix}/share/qemu" "${out}/share/"
[ -f "${prefix}/etc/resolv.conf" ] && cp "${prefix}/etc/resolv.conf" "${out}/share/resolv.conf"
(cd "${out}" && sha256sum lib*.so > SHA256SUMS && du -ch lib*.so | tail -1 | sed 's/^/total: /' && du -sh share && ls -la)
for k in "${!from[@]}"; do echo "  ${from[${k}]} → ${k}"; done | sort
