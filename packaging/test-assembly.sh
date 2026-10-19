#!/usr/bin/env bash
# test-assembly.sh — prove the .run byte addressing is correct, without Docker.
#
#   packaging/test-assembly.sh
#
# The self-extracting installer reads its own payload by absolute byte offset. If an offset is off
# by even one byte the failure is silent and misleading: `zstd -dc` reports corruption, or worse,
# `docker load` receives a truncated stream and reports an unrelated error. This is the one part of
# the design that cannot be reasoned about — it has to be executed.
#
# So: build a .run with SYNTHETIC segments whose contents are known, then read each one back out
# through the same dd invocation the header uses and compare hashes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
cd "${REPO_ROOT}"

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else
            echo "  FAIL $1"; echo "        want $2"; echo "        got  $3"; fail=$((fail+1)); fi; }

echo "== building a synthetic .run =="

# Three segments with distinct, incompressible content so a wrong offset cannot accidentally match.
head -c 3000   /dev/urandom > "${WORK}/control.bin"
head -c 17000  /dev/urandom > "${WORK}/runtime.bin"
head -c 240000 /dev/urandom > "${WORK}/images.bin"

HEADER_LEN=65536
CTRL_LEN=$(wc -c < "${WORK}/control.bin")
RT_LEN=$(wc -c < "${WORK}/runtime.bin")
IMG_LEN=$(wc -c < "${WORK}/images.bin")
CTRL_OFF=${HEADER_LEN}
RT_OFF=$(( CTRL_OFF + CTRL_LEN ))
IMG_OFF=$(( RT_OFF + RT_LEN ))

sed -e "s|@@HEADER_LEN@@|${HEADER_LEN}|" \
    -e "s|@@SEG_CONTROL_OFF@@|${CTRL_OFF}|" -e "s|@@SEG_CONTROL_LEN@@|${CTRL_LEN}|" \
    -e "s|@@SEG_RUNTIME_OFF@@|${RT_OFF}|"   -e "s|@@SEG_RUNTIME_LEN@@|${RT_LEN}|" \
    -e "s|@@SEG_IMAGES_OFF@@|${IMG_OFF}|"   -e "s|@@SEG_IMAGES_LEN@@|${IMG_LEN}|" \
    -e "s|@@VERSION@@|0.0.0-test|" \
    packaging/linux/header.sh > "${WORK}/header.sh"

hdr_now=$(wc -c < "${WORK}/header.sh")
if [ "${hdr_now}" -gt "${HEADER_LEN}" ]; then
  echo "  FAIL header is ${hdr_now} bytes, exceeds the ${HEADER_LEN}-byte slot"; exit 1
fi
pad=$(( HEADER_LEN - hdr_now ))
{ cat "${WORK}/header.sh"; head -c "${pad}" < /dev/zero | tr '\0' '#'; } > "${WORK}/hdr.padded"
check "header padded to exactly HEADER_LEN" "${HEADER_LEN}" "$(wc -c < "${WORK}/hdr.padded")"

RUN="${WORK}/test.run"
cat "${WORK}/hdr.padded" "${WORK}/control.bin" "${WORK}/runtime.bin" "${WORK}/images.bin" > "${RUN}"
chmod +x "${RUN}"

want_total=$(( HEADER_LEN + CTRL_LEN + RT_LEN + IMG_LEN ))
check "assembled size" "${want_total}" "$(wc -c < "${RUN}")"

echo "== reading each segment back through the header's own dd invocation =="

# Byte-for-byte the seg() function from packaging/linux/header.sh.
seg() { dd if="${RUN}" bs=1M iflag=skip_bytes,count_bytes skip="$1" count="$2" status=none; }

h() { sha256sum "$1" | cut -d' ' -f1; }
check "control segment round-trips" "$(h "${WORK}/control.bin")" "$(seg "${CTRL_OFF}" "${CTRL_LEN}" | sha256sum | cut -d' ' -f1)"
check "runtime segment round-trips" "$(h "${WORK}/runtime.bin")" "$(seg "${RT_OFF}"   "${RT_LEN}"   | sha256sum | cut -d' ' -f1)"
check "images segment round-trips"  "$(h "${WORK}/images.bin")"  "$(seg "${IMG_OFF}"  "${IMG_LEN}"  | sha256sum | cut -d' ' -f1)"

# An off-by-one MUST break. If it doesn't, the test itself proves nothing.
off_by_one="$(seg $(( CTRL_OFF + 1 )) "${CTRL_LEN}" | sha256sum | cut -d' ' -f1)"
if [ "${off_by_one}" = "$(h "${WORK}/control.bin")" ]; then
  echo "  FAIL off-by-one offset produced identical bytes — the test is not sensitive"; fail=$((fail+1))
else
  echo "  ok   off-by-one offset is detected"; pass=$((pass+1))
fi

echo "== the header parses and its --version path works =="
bash -n "${WORK}/hdr.padded" && { echo "  ok   header parses"; pass=$((pass+1)); } || { echo "  FAIL header syntax"; fail=$((fail+1)); }
check "--version reports the stamped version" "0.0.0-test" "$(bash "${RUN}" --version)"

echo "== manifest covers the artifact and its segments =="
python3 packaging/make-manifest.py --version 0.0.0-test --artifact "${RUN}" \
  --segment "control:${CTRL_OFF}:${CTRL_LEN}" \
  --segment "runtime:${RT_OFF}:${RT_LEN}" \
  --segment "images:${IMG_OFF}:${IMG_LEN}" \
  --out "${WORK}/manifest.json" >/dev/null

python3 - "${WORK}/manifest.json" "${RUN}" "${WORK}/control.bin" "${WORK}/images.bin" <<'PY'
import hashlib, json, sys
m = json.load(open(sys.argv[1]))
run, ctrl, imgs = sys.argv[2], sys.argv[3], sys.argv[4]
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
ok = True
if m['artifact']['sha256'] != sha(run):
    print("  FAIL manifest artifact sha256 does not match the file"); ok = False
else: print("  ok   manifest artifact sha256 matches")
seg = {s['id']: s for s in m['segments']}
if seg['control']['sha256'] != sha(ctrl):
    print("  FAIL manifest control-segment hash wrong"); ok = False
else: print("  ok   manifest control-segment hash matches the source bytes")
if seg['images']['sha256'] != sha(imgs):
    print("  FAIL manifest images-segment hash wrong"); ok = False
else: print("  ok   manifest images-segment hash matches the source bytes")
# parts must tile the whole artifact exactly
total = sum(p['len'] for p in m['parts'])
if total != m['artifact']['size']:
    print(f"  FAIL parts sum to {total}, artifact is {m['artifact']['size']}"); ok = False
else: print(f"  ok   {len(m['parts'])} part(s) tile the artifact exactly")
sys.exit(0 if ok else 1)
PY
rc=$?
[ "${rc}" = 0 ] && pass=$((pass+4)) || fail=$((fail+1))

echo
echo "== overlapping segments are rejected =="
if python3 packaging/make-manifest.py --version x --artifact "${RUN}" \
     --segment "a:${CTRL_OFF}:5000" --segment "b:$(( CTRL_OFF + 100 )):5000" \
     --out "${WORK}/bad.json" >/dev/null 2>&1; then
  echo "  FAIL overlapping segments were accepted"; fail=$((fail+1))
else
  echo "  ok   overlapping segments rejected"; pass=$((pass+1))
fi

echo
echo "passed ${pass}, failed ${fail}"
[ "${fail}" = 0 ]
