#!/usr/bin/env bash
#: does a container's configuration depend on WHO asks compose for it? (read-only)
#
#   bash scripts/config-by-caller.sh [service …]
#
# Three questions, all answered by the engine itself and none changing anything:
#   1. the configuration THIS shell compiles (dcx — what `bbox run` and every hook use) against the
#      one EVERY OTHER CALLER compiles: each running container that brings containers up (the
#      control plane for an install from the apps screen, the agent's shell). They are found by what
#      they were handed for it — BBOX_HOST_DOCKER_SOCK — so no app is named here. A key that differs
#      is a container re-created at every alternation between the two callers (a caller built with
#      another compose than the host's shows as a differing `build.args`);
#   2. `up -d --dry-run` from here: the running containers a bring-up would re-create although
#      nobody edited them;
#   3. the CPU quota of every running container against the machine's budget (gate G65's plan).
# Exit 1 when an answer is not "none". Values of secret-looking keys are never printed.
# Why it exists: issues/a-containers-configuration-depends-on-who-asks-and-on-who-else-runs.yaml
set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
dcx config --format json > "${tmp}/here" 2>/dev/null || die "this shell cannot compile the configuration"
mine="$(_dcx_run ps -q 2>/dev/null)"
[ -n "${mine}" ] || die "no container of this office is running — there is nobody to compare with"
# shellcheck disable=SC2086  # the id list is word-split on purpose: one inspect call for all of them
callers="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}{{range .Config.Env}} {{.}}{{end}}' ${mine} 2>/dev/null \
            | awk '/ BBOX_HOST_DOCKER_SOCK=/ {print $1}' | sort -u)"
[ -n "${callers}" ] || die "no running container was handed the host's facts (BBOX_HOST_DOCKER_SOCK) — the services that run compose were created before they carried them; bring them up once"
for svc in ${callers}; do
  dcx exec -T -w "${REPO_ROOT}" "${svc}" bash -c '. scripts/lib.sh >/dev/null 2>&1; dcx config --format json' \
    > "${tmp}/${svc}" 2>/dev/null || die "${svc} cannot compile the configuration"
done

python3 - "${tmp}" "${callers}" "$@" <<'PY'
import json, pathlib, re, sys
tmp, callers, only = pathlib.Path(sys.argv[1]), sys.argv[2].split(), set(sys.argv[3:])
load = lambda name: json.loads((tmp / name).read_text(encoding="utf-8"))["services"]   # noqa: E731
SECRET = re.compile(r"PASSWORD|SECRET|TOKEN|KEY|DSN|CREDENTIAL", re.I)


def flat(node, path=""):
    if isinstance(node, dict):
        return {k2: v for k, sub in node.items() for k2, v in flat(sub, f"{path}.{k}" if path else k).items()}
    if isinstance(node, list):
        return {k2: v for i, sub in enumerate(node) for k2, v in flat(sub, f"{path}[{i}]").items()}
    return {path: node}


a, bad = load("here"), 0
for caller in callers:
    b, differing = load(caller), 0
    for svc in sorted(set(a) | set(b)):
        if only and svc not in only:
            continue
        fa, fb = flat(a.get(svc, {})), flat(b.get(svc, {}))
        keys = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
        if not keys:
            continue
        differing += 1
        print(f"  {svc}: {len(keys)} key(s)")
        for k in keys[:6]:
            shown = "(differs — not shown)" if SECRET.search(k) else f"{str(fa.get(k))[:44]!r} here, {str(fb.get(k))[:44]!r} there"
            print(f"      {k}: {shown}")
    print(f"1. this shell vs {caller}: {differing or 'none'} of {len(only or set(a) | set(b))} service(s) differ")
    bad += differing
sys.exit(1 if bad else 0)
PY
rc=$?

again="$(stale_containers | tr '\n' ' ')"
echo "2. a bring-up from here would re-create: ${again:-none}"

off="$( cd "${REPO_ROOT}" && _dcx_run ps --format '{{.ID}} {{.Service}}' 2>/dev/null \
          | python3 scripts/refactor/cpu-budget-lint.py --apply .generated/cpu-budget.yml --dry-run 2>/dev/null | tr '\n' ';' )"
echo "3. containers whose CPU quota is not the budget's: ${off:-none}"
[ "${rc}" = 0 ] && [ -z "${again}" ] && [ -z "${off}" ]
