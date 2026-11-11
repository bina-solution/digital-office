# where.sh — WHERE domain-internic runs, for its hooks. Sourced; sets DI_IN (the service whose container
# runs cli.py) and DI_API (the address cli.py is told; empty = the container's own loopback).
#
# Here, in its own container. Or — on an office that does not run it (the app runs where its credential is
# typed and its browser signs in: apps/computers/herd.yaml) — behind the link: the herd names the office
# (scripts/herd_home.py, the same answer project-pln's hooks use), and cli.py then runs in the credential
# plane's container, which every office has and which sits where the link's names resolve. What these lines
# say goes to stderr: stdout is the CLI's answer, which a caller may pipe to jq.
DI_IN=domain-internic
DI_API="${DOMAIN_INTERNIC_API:-}"
if [ -z "${DI_API}" ] && [ -z "$(cn domain-internic)" ]; then
  if grep -Eq '^  domain-internic:[[:space:]]*\{[^}]*(state:[[:space:]]*enabled|enabled:[[:space:]]*true)' "${REPO_ROOT}/platform.state.yaml" 2>/dev/null; then
    die "[domain-internic] the app is enabled on this office but its container is not running — ./bbox run domain-internic"
  fi
  DI_WHERE="$(python3 "${REPO_ROOT}/scripts/herd_home.py" domain-internic "$(read_env_value DGO_OFFICE_ID)")"
  DI_API="${DI_WHERE#* }"
  [ "${DI_API}" != "${DI_WHERE}" ] || DI_API=""
  [ -n "${DI_API}" ] || die "[domain-internic] the app does not run on this office, and no linked office gives it to this one (apps/computers/herd.yaml give:)"
  DI_IN=connections
  say "[domain-internic] the app runs on a linked office — reaching it at ${DI_API}" >&2
fi

di_cli() {
  dcx exec -T -e "DOMAIN_INTERNIC_API=${DI_API}" "${DI_IN}" python3 - "$@" < "$(npath "${REPO_ROOT}")/apps/domain-internic/cli.py"
}
