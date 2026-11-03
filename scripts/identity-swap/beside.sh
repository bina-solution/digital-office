#!/usr/bin/env bash
# beside.sh — the identity swap's first step (README in window.sh): forward-auth BESIDE authentik
# (core-006 §4 steps 4–5). Additive: no route, no middleware and no running container other than
# forward-auth's own changes. Prints counts, codes and the service's own boot line — never a hash, a key or
# a cookie. Before it: platform.state.yaml enables forward-auth with `bindings: identity: authentik`, and
# .env has FORWARD_AUTH_SECRET. Usage, from the office: bash scripts/identity-swap/beside.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=ci-artifacts/identity-swap; mkdir -p "${OUT}"
D="$(sed -n 's/^DEPLOYMENT_NAME=//p' .env | tail -1)"; D="${D:-bina-deployment}"
IMG=ghcr.io/solomonboltin/digital-office/forward-auth:latest
say() { printf '%s %s\n' "$(date -u +%T)" "$*"; }
die() { say "STOP: $*"; exit 1; }
say "load $(cut -d' ' -f1-3 /proc/loadavg); deployment ${D}"

# 0. the image this office already has must carry -import-users (no build on the Mac)
docker image inspect "${IMG}" >/dev/null 2>&1 || docker pull -q "${IMG}" >/dev/null 2>&1 || die "no ${IMG}, and it does not pull"
docker run --rm "${IMG}" -h 2>&1 | grep -q -- '-import-users' || die "the image predates -import-users"
say "image ok: $(docker image inspect -f '{{.Created}}' "${IMG}")"

# 1. render with forward-auth enabled and identity bound to authentik
out="$(python3 platform/manager/reconcile.py render 2>&1)"; rc=$?
printf '%s\n' "${out}" | grep -iE 'identity|forward-auth|error' | head -12
[ "${rc}" = 0 ] || die "render exit ${rc}"
grep -q 'forward-auth' .generated/*.yml || die "forward-auth is not in the render"
say "render ok"

# 2. the users (§6.3a): authentik's own rows, six fields, straight into -import-users
PG="authentik-postgres-${D}"
SQL="select u.username,
  coalesce(nullif(u.email,''),'(none)'),
  coalesce(nullif(regexp_replace(btrim(u.name),'\s+','-','g'),''),u.username),
  encode(sha256((u.id::text||'-'||(select id from authentik_install_id limit 1))::bytea),'hex'),
  coalesce((select string_agg(g.name, ',' order by g.name) from authentik_core_user_ak_groups ug
            join authentik_core_group g on g.group_uuid = ug.group_id
            where ug.user_id = u.id and g.name !~ '\s'), '-'),
  u.password
from authentik_core_user u where u.is_active and u.type = 'internal' order by u.id"
ERR="$(mktemp)"
rows="$(docker exec "${PG}" psql -U authentik -d authentik -v ON_ERROR_STOP=1 -t -A -F' ' -c "${SQL}" 2>"${ERR}")" \
  || { head -c 400 "${ERR}"; rm -f "${ERR}"; die "the read-only query failed"; }
rm -f "${ERR}"
n="$(printf '%s\n' "${rows}" | grep -c .)"
bad="$(printf '%s\n' "${rows}" | awk 'NF && NF != 6' | wc -l)"
none="$(printf '%s\n' "${rows}" | awk 'NF && $2 == "(none)"' | wc -l)"
dropped="$(docker exec "${PG}" psql -U authentik -d authentik -t -A -c "select count(*) from authentik_core_user_ak_groups ug join authentik_core_group g on g.group_uuid = ug.group_id join authentik_core_user u on u.id = ug.user_id where u.is_active and u.type = 'internal' and g.name ~ '\s'" 2>/dev/null)"
say "authentik users: ${n} active internal; lines not of 6 fields: ${bad}; without e-mail: ${none}; group memberships dropped (a space in the name): ${dropped}"
[ "${n}" -ge 1 ] && [ "${bad}" = 0 ] || die "the users do not convert cleanly"
said="$(printf '%s\n' "${rows}" | ./scripts/dc run --rm --no-deps -T forward-auth -import-users 2>&1 | tr -d '\r' | tail -2)"
unset rows
say "import: ${said}"
printf '%s\n' "${said}" | grep -qxE 'imported|owner-exists' || die "the import did not take"

# 3. up: this one service, nothing it would pull in
./scripts/dc up -d --no-deps forward-auth 2>&1 | tail -3
for i in $(seq 1 24); do
  st="$(docker inspect -f '{{.State.Health.Status}}' "forward-auth-${D}" 2>/dev/null || echo missing)"
  [ "${st}" = healthy ] && break
  sleep 5
done
say "forward-auth: ${st}"
# only its two boot lines' shapes: a users file that fails to load is quoted whole by its fatal error
docker logs "forward-auth-${D}" 2>&1 | grep -E 'forward-auth: (listening on|[0-9]+ of [0-9]+ user)' | tail -2
[ "${st}" = healthy ] || die "forward-auth is not healthy"

# 4. the sweep, asked the way traefik asks it, for every host the edge gates (sweep.sh: the live labels)
bash scripts/identity-swap/sweep.sh fa || die "the sweep did not pass"
say "done"
