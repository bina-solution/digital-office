#!/usr/bin/env bash
# office-root.sh <out> — the office root the APK carries for its native core (DGO-1090): the core office's
# state, the manifests of the apps it runs and the one registry file the console reads
# (console.modules.yaml), marked `.dgo-office-root` with the commit it was made from. No checkout, no
# compiler, no bbox and no secret: `dgo be-child` reads it where there is no checkout (DGO_OFFICE_ROOT,
# packaging/dgo main.go officeRoot), and the phone makes its own .env and forward-auth secret at first run.
#
# Made from HEAD in a throwaway copy, so this checkout's platform.state.yaml, .env and .generated are never
# touched; rendered with the phone's own settings (ci-env.sh as the guest's first boot runs it, the edge on
# :8080), whose .env stays in the copy. The root is put together in the copy and checked there — every
# value that run minted is absent from it, every app it runs has its manifest — and marked last, so a
# refused root is never one `dgo` would take; only then is it copied to <out>.
#   DGO   a dgo built for this machine: its compiler renders, so no Python is needed
set -euo pipefail
out="${1:?usage: office-root.sh <out>}"
dgo="$(cd "$(dirname "${DGO:?DGO: a dgo built for this machine}")" && pwd)/$(basename "${DGO}")"
repo="$(git rev-parse --show-toplevel)"
commit="$(git -C "${repo}" rev-parse HEAD)"
mkdir -p "${out}"
chmod 700 "${out}"   # a root is its owner's alone (officeRoot refuses one others may write, as umask 002 makes it)
out="$(cd "${out}" && pwd)"
[ -z "$(ls -A "${out}")" ] || { echo "office-root.sh: ${out} is not empty" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

mkdir "${tmp}/copy" "${tmp}/root"
git -C "${repo}" archive HEAD | tar -x -C "${tmp}/copy"
cd "${tmp}/copy"
cp platform.state.core.yaml platform.state.yaml
# no secret and no domain of the host's in reach: a phone's root is rendered for the phone alone
N8N_ENCRYPTION_KEY_SECRET= CHANGE_ME \
  CI_IDENTITY=forward-auth CI_ENV_FORCE=1 CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh
"${dgo}" render > render.log 2>&1 || { cat render.log >&2; echo "office-root.sh: the core office does not render" >&2; exit 1; }

root="${tmp}/root"
cp platform.state.yaml "${root}/"
# every app's manifest — the core's and every one the install wizard may offer (141 KB): a container app is
# listed by the core and runs in the machine, whose compose files stay there (android-path.md)
"${dgo}" enabled-apps > enabled.txt 2> enabled.err || { cat enabled.err >&2; exit 1; }   # the core resolves
for m in platform-base/*/app.json apps/*/app.json; do
  mkdir -p "${root}/$(dirname "${m}")"
  cp "${m}" "${root}/${m}"
done
mkdir -p "${root}/.generated/registry"
cp .generated/registry/console.modules.yaml "${root}/.generated/registry/"
# the office record's vocabulary: the install wizard's hue and animal are checked against the palette and
# the icon set (office-set), 28 KB
mkdir -p "${root}/platform-base/bina-ui"
cp platform-base/bina-ui/theme-tokens.css platform-base/bina-ui/bina-icons.js "${root}/platform-base/bina-ui/"

manifests="$(find "${root}" -name app.json | wc -l | tr -d ' ')"
catalog="$(ls platform-base/*/app.json apps/*/app.json | wc -l | tr -d ' ')"
[ "${manifests}" = "${catalog}" ] && [ "${manifests}" -gt 0 ] \
  || { echo "office-root.sh: ${manifests} manifests of the catalog's ${catalog}" >&2; exit 1; }
while read -r dir id; do   # and every app the core runs among them
  [ -f "${root}/${dir}/${id}/app.json" ] || { echo "office-root.sh: the core's ${id} has no manifest in the root" >&2; exit 1; }
done < enabled.txt
[ -s "${root}/.generated/registry/console.modules.yaml" ] || { echo "office-root.sh: the console's registry is empty" >&2; exit 1; }
# no value this run minted is in it — whatever its name; said by name only, never the value. Not minted: one of
# .env.ex's own, one ci-env.sh writes from its own text (a service's URL, as supabase's manifest names it too —
# the script's, public), the phone's localhost addresses. A random value, or one handed in from the host, is in
# neither file, and is checked
while IFS='=' read -r k v; do
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  [ "${#v}" -ge 16 ] || continue
  case "${v}" in *localhost*) continue ;; esac
  ! grep -qF -- "${v}" .env.ex || continue
  ! grep -qF -- "${v}" scripts/ci-env.sh || continue
  if grep -rqF -- "${v}" "${root}"; then echo "office-root.sh: ${k}'s value is in the root — refused" >&2; exit 1; fi
done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env)

printf 'dgo office root\ncommit %s\n' "${commit}" > "${root}/.dgo-office-root"
cp -R "${root}/." "${out}/"
echo "office root ${commit::8}: ${manifests} apps, $(find "${out}" -type f | wc -l | tr -d ' ') files, $(du -sk "${out}" | cut -f1) KB"
