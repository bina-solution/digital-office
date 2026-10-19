#!/usr/bin/env bash
# verify-artifact.sh — prove a built .run is what the signed manifest says it is.
#
#   packaging/verify-artifact.sh dist/BinaOS-<ver>-linux-amd64.run [cosign.pub]
#
# This is the check a customer can run before installing, and the check CI must run before
# publishing. It exists because this session produced, in order: an exit-0 build with a zero-byte
# artifact, a "launched" build that never detached, and a 1.53 GB measurement of an incomplete
# image set. Every one of them looked like success from the outside. The only defence is to
# interrogate the artifact rather than the log.
set -uo pipefail

RUN="${1:?usage: verify-artifact.sh <artifact.run> [cosign.pub]}"
PUB="${2:-/root/binaos-keys/cosign.pub}"
DIR="$(cd "$(dirname "${RUN}")" && pwd)"
MAN="${DIR}/manifest.json"
SIG="${DIR}/manifest.sigstore.json"

pass=0; fail=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }

[ -f "${RUN}" ] || { echo "no such artifact: ${RUN}"; exit 1; }
[ -f "${MAN}" ] || { echo "no manifest beside it: ${MAN}"; exit 1; }

echo "== 1. signature over the manifest =="
if [ -f "${SIG}" ] && command -v cosign >/dev/null 2>&1; then
  # All three conditions matter: --key alone does NOT suppress Rekor, so an offline verify without
  # --insecure-ignore-tlog will try to reach the transparency log and fail on an airgapped host.
  if cosign verify-blob --key "${PUB}" --bundle "${SIG}" \
       --insecure-ignore-tlog=true "${MAN}" >/dev/null 2>&1; then
    ok "cosign verified the manifest offline"
  else
    bad "cosign REJECTED the manifest — do not install this artifact"
  fi
else
  printf '  \033[33mskip\033[0m no signature or no cosign\n'
fi

echo "== 2. the artifact is the one the manifest describes =="
want_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["sha256"])' "${MAN}")"
want_size="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["size"])' "${MAN}")"
got_size="$(wc -c < "${RUN}")"
[ "${want_size}" = "${got_size}" ] && ok "size ${got_size}" || bad "size: manifest ${want_size}, actual ${got_size}"
got_sha="$(sha256sum "${RUN}" | cut -d' ' -f1)"
[ "${want_sha}" = "${got_sha}" ] && ok "sha256 ${got_sha:0:16}…" || bad "sha256 mismatch"

echo "== 3. every segment reads back at its recorded offset =="
# The same dd invocation the installer's header uses. A wrong offset here is the failure that
# presents as zstd corruption or an unrelated docker error at install time.
while IFS=$'\t' read -r sid soff slen ssha; do
  [ -n "${sid}" ] || continue
  actual="$(dd if="${RUN}" bs=1M iflag=skip_bytes,count_bytes skip="${soff}" count="${slen}" status=none | sha256sum | cut -d' ' -f1)"
  if [ "${actual}" = "${ssha}" ]; then ok "segment ${sid} (${slen} bytes @ ${soff})"
  else bad "segment ${sid} hash mismatch"; fi
done < <(python3 -c '
import json,sys
for s in json.load(open(sys.argv[1]))["segments"]:
    print("\t".join([s["id"], str(s["offset"]), str(s["len"]), s["sha256"]]))' "${MAN}")

echo "== 4. the images segment is a loadable docker archive =="
iseg="$(python3 -c '
import json,sys
for s in json.load(open(sys.argv[1]))["segments"]:
    if s["id"] == "images": print(s["offset"], s["len"])' "${MAN}")"
set -- ${iseg}
if [ -n "${1:-}" ]; then
  # Decompress and read only the archive index, not the whole 10 GB: manifest.json is at the root
  # of a docker save archive, so tar can stop as soon as it has it.
  if dd if="${RUN}" bs=1M iflag=skip_bytes,count_bytes skip="$1" count="$2" status=none \
       | zstd -dc --long=27 2>/dev/null | tar -tf - manifest.json >/dev/null 2>&1; then
    ok "images segment decompresses and contains a docker manifest"
  else
    bad "images segment is not a loadable docker archive"
  fi
fi

echo "== 5. image coverage =="
n_img="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["images"]))' "${MAN}")"
n_dig="$(python3 -c '
import json,sys
print(sum(1 for i in json.load(open(sys.argv[1]))["images"] if i["digest"].startswith("sha256:")))' "${MAN}")"
[ "${n_img}" -gt 0 ] && ok "${n_img} image(s) recorded, ${n_dig} with a digest" || bad "no images in manifest"

echo "== 6. the control segment carries everything the header calls =="
# The installer is a shell script that invokes files it expects to have shipped. When one is absent
# the install still reports success and the failure surfaces later as something unrelated:
# binaos.service went missing once and `systemctl start binaos` answered "Unit could not be found",
# and adapt-host.py is what points the docker-socket mounts at our own engine — without it traefik
# silently watches the host's daemon and every route 404s. Both were shipped by `cp ... || true`.
cseg="$(python3 -c '
import json,sys
for s in json.load(open(sys.argv[1]))["segments"]:
    if s["id"] == "control": print(s["offset"], s["len"])' "${MAN}")"
set -- ${cseg}
if [ -n "${1:-}" ]; then
  listing="$(dd if="${RUN}" bs=1M iflag=skip_bytes,count_bytes skip="$1" count="$2" status=none \
             | zstd -dc 2>/dev/null | tar -tf - 2>/dev/null)"
  for want in binaos.service adapt-host.py platform/.generated/compose.runtime.yml; do
    if printf '%s\n' "${listing}" | grep -qx "./${want}" || printf '%s\n' "${listing}" | grep -qx "${want}"; then
      ok "control carries ${want}"
    else
      bad "control segment is missing ${want} — the installer calls it"
    fi
  done
else
  bad "no control segment in the manifest"
fi

echo
echo "passed ${pass}, failed ${fail}"
[ "${fail}" = 0 ]
