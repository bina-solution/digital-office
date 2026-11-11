#!/usr/bin/env bash
# test_ccr_pull.sh — a base image that cannot be pulled is said for what it is (DGO-1017, scripts/lib.sh ccr_pull_base).
#
#     bash scripts/test_ccr_pull.sh
#
# The pull's stderr used to go to /dev/null and every failure printed the network-policy hint, so a FULL DISK sent the
# reader to recreate a cloud environment. Each case here fakes `docker` with the words a real daemon prints, and checks:
#   * no space left on device → «the disk is full», with the free space and the path; never the network hint;
#   * a network / registry error → the network hint, as before (and CCR_REGISTRY_BLOCKED for `bbox run`);
#   * anything else → docker's own last line, and neither;
#   * a pull that works → silent, status 0.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "${HERE}/.." && pwd)"
fails=0
ok() { printf 'PASS  %s\n' "$1"; }
no() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT

# One case: <the stderr the fake daemon prints for `docker pull`> <its exit> → "rc|disk|net|blocked|diskflag|output"
run_case() {
  FAKE_ERR="$1" FAKE_RC="$2" FAKE_ROOT="${TMP}" bash -c '
    . "'"${ROOT}"'/scripts/lib.sh" >/dev/null 2>&1
    docker() {
      case "$1" in
        pull) [ -n "${FAKE_ERR}" ] && printf "%s\n" "${FAKE_ERR}" >&2; return "${FAKE_RC}" ;;
        info) printf "%s\n" "${FAKE_ROOT}" ;;
      esac
    }
    unset CCR_REGISTRY_BLOCKED CCR_DISK_FULL
    out="$(ccr_pull_base node:24-bookworm-slim 2>&1)"; rc=$?
    # the flags are set in the function, which ran in the command substitution: ask again here, quietly
    ccr_pull_base node:24-bookworm-slim >/dev/null 2>&1
    printf "%s|%s|%s|%s\n" "${rc}" "${CCR_REGISTRY_BLOCKED:-0}" "${CCR_DISK_FULL:-0}" "$(printf "%s" "${out}" | tr "\n" " ")"'
}

r="$(run_case 'failed to register layer: write /var/lib/docker/overlay2/abc/diff/usr/lib/x.so: no space left on device' 1)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${rc}" != 0 ] && [[ "${out}" == *"the disk is full"* ]] && [[ "${out}" == *"free at ${TMP}"* ]] \
  && [[ "${out}" != *"— ? free"* ]] \
  && [[ "${out}" != *"network policy"* ]] && [ "${blocked}" = 0 ] && [ "${disk}" = 1 ] \
  && ok "no space left on device: «the disk is full», the free space at the path, CCR_DISK_FULL — never the network hint" \
  || no "ENOSPC was not said as the disk (rc=${rc} blocked=${blocked} disk=${disk}): ${out}"

r="$(run_case 'Error response from daemon: Get "https://registry-1.docker.io/v2/": dial tcp: lookup registry-1.docker.io: no such host' 1)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${rc}" != 0 ] && [[ "${out}" == *"network policy"* ]] && [[ "${out}" == *"no such host"* ]] && [ "${blocked}" = 1 ] \
  && [ "${disk}" = 0 ] \
  && ok "a network error: docker's words and the network hint, CCR_REGISTRY_BLOCKED for bbox run" \
  || no "a network error lost its hint (rc=${rc} blocked=${blocked} disk=${disk}): ${out}"

r="$(run_case 'Error response from daemon: Get "https://registry-1.docker.io/v2/": proxyconnect tcp: 404 Not Found' 1)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${blocked}" = 1 ] && [[ "${out}" == *"network policy"* ]] \
  && ok "a proxy's «404 Not Found» is the network, not a missing tag" \
  || no "a proxy's 404 skipped the network hint (blocked=${blocked}): ${out}"

r="$(run_case 'Error response from daemon: received unexpected HTTP status: 403' 1)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${blocked}" = 1 ] && [[ "${out}" == *"network policy"* ]] \
  && ok "a registry refusal (a bare 403) is the egress hint too" \
  || no "a 403 from the registry was not read as the egress (blocked=${blocked}): ${out}"

for words in 'Error response from daemon: pull access denied for nodee, repository does not exist or may require docker login' \
             'permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock' \
             'failed to register layer: open /var/lib/docker/overlay2/x: permission denied'; do
  r="$(run_case "${words}" 1)"
  IFS='|' read -r rc blocked disk out <<<"${r}"
  [ "${rc}" != 0 ] && [ "${blocked}" = 0 ] && [ "${disk}" = 0 ] && [[ "${out}" != *"network policy"* ]] \
    && ok "not the network, though it says «denied»: ${words:0:60}…" \
    || no "«${words:0:60}…» was read as the network policy (blocked=${blocked}): ${out}"
done

r="$(run_case 'Error response from daemon: manifest for node:99-nope not found: manifest unknown: manifest unknown' 1)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${rc}" != 0 ] && [[ "${out}" == *"manifest unknown"* ]] && [[ "${out}" != *"network policy"* ]] \
  && [[ "${out}" != *"disk is full"* ]] && [ "${blocked}" = 0 ] && [ "${disk}" = 0 ] \
  && ok "anything else: docker's own last line, neither the disk nor the network" \
  || no "an unknown tag was read as something it is not (blocked=${blocked} disk=${disk}): ${out}"

r="$(run_case '' 0)"
IFS='|' read -r rc blocked disk out <<<"${r}"
[ "${rc}" = 0 ] && [ -z "${out// /}" ] && [ "${blocked}" = 0 ] && [ "${disk}" = 0 ] \
  && ok "a pull that works is silent, status 0" || no "a working pull said something (rc=${rc}): ${out}"

# the one caller, and bbox run's stop on the flag
grep -q 'ccr_pull_base "\$b" ||' "${ROOT}/scripts/lib.sh" \
  && ok "ccr_shadow_bases pulls through ccr_pull_base" || no "ccr_shadow_bases still pulls on its own"
! grep -qE 'docker pull "\$b" >/dev/null 2>&1' "${ROOT}/scripts/lib.sh" \
  && ok "no pull of a base sends its stderr to /dev/null any more" || no "a base pull still discards its stderr"
shadow="$(grep -n 'ccr_shadow_bases || true' "${ROOT}/bbox" | head -1 | cut -d: -f1)"
stop="$(grep -n 'CCR_DISK_FULL:-0}" = 1 ] && die' "${ROOT}/bbox" | head -1 | cut -d: -f1)"
[ -n "${shadow}" ] && [ -n "${stop}" ] && [ "${stop}" -gt "${shadow}" ] \
  && ok "bbox run stops on a full disk with the disk's words, after the shadowing that sets it" \
  || no "bbox run does not stop on CCR_DISK_FULL after ccr_shadow_bases (shadow line ${shadow:-none}, stop ${stop:-none})"

# a bare call under `set -e` (a caller with no `||`) returns its status instead of exiting the caller's shell
r="$(FAKE_ERR='x: no such host' bash -c '
  . "'"${ROOT}"'/scripts/lib.sh" >/dev/null 2>&1
  docker() { [ "$1" = pull ] && { printf "%s\n" "${FAKE_ERR}" >&2; return 1; }; }
  set -e; ccr_pull_base b >/dev/null 2>&1 && echo pulled || echo "returned $?"' 2>/dev/null)"
[ "${r}" = "returned 1" ] && ok "under set -e a failed pull returns 1 to its caller, it does not end the caller's shell" \
  || no "under set -e the helper ended its caller (said: ${r:-nothing})"

echo "test_ccr_pull: $([ "${fails}" = 0 ] && echo 'all passed' || echo "${fails} FAILED")"
exit $([ "${fails}" = 0 ] && echo 0 || echo 1)
