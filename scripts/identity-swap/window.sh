#!/usr/bin/env bash
# window.sh — an office's identity swap, authentik → forward-auth (core-006 §4 steps 6–7, §6.3, §6.6;
# release-030, r030-004/006). Done on the MacBook, vps1 and the Dell, 2026-11-03. One phase per call:
#   bash scripts/identity-swap/window.sh measure|snapshot|pair|flip|off|rollback
# From the office's checkout (in the engine on a MacBook: packaging/macos/engine.sh exec -- bash …).
# Prints counts, codes and the services' own boot lines — never a hash, a key, a cookie or a session id.
# Every phase that cannot do its whole job says STOP and exits 1, so `a && b && c` never builds on a half.
#
# THE ORDER. The office's code has dgo-stable (traefik's DGO_IDENTITY switch, forward-auth's volume and
# -import-users, r030-002/003). Then:
#   1. back up .env and platform.state.yaml; state: forward-auth enabled + `bindings: identity: authentik`;
#      .env: FORWARD_AUTH_SECRET (random), and on a TLS office FORWARD_AUTH_EXTERNAL_URL=https://signin.<domain>
#      and FORWARD_AUTH_ALLOWED_HOSTS=.<domain>,.localhost;
#   2. render, and the image where it does not pull (`./scripts/dc build forward-auth`; never on a MacBook);
#   3. beside.sh, then `sweep.sh fa` — every gated host 302 to the sign-in; `sweep.sh edge` (or `list` and
#      a sweep from outside) — the before;
#   4. state: `bindings: identity: forward-auth`; `snapshot && pair && flip` in one go (FA_PROTO=https on a
#      TLS office, FA_PROTO=http where the office set FORWARD_AUTH_EXTERNAL_URL over plain http) — or, when
#      snapshot says there is no live session, `flip` alone; the sweep again — the after;
#   5. off (authentik stopped; containers and volumes kept). rollback at any point after 4.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=ci-artifacts/identity-swap; mkdir -p "${OUT}"
D="$(sed -n 's/^DEPLOYMENT_NAME=//p' .env | tail -1)"; D="${D:-bina-deployment}"
FA="forward-auth-${D}"; PG="authentik-postgres-${D}"
AK="^authentik-.*-${D}\$"                  # this office's authentik containers, and no other stack's
say() { printf '%s %s\n' "$(date -u +%T)" "$*"; }
die() { say "STOP: $*"; exit 1; }
envv() { sed -n "s/^$1=//p" .env | tail -1; }
# envset KEY < value: replace or append one .env line. The value comes on stdin (the program is -c, so
# stdin is the value's alone), never on argv or the screen.
ENVSET='
import sys, pathlib
key, val = sys.argv[1], sys.stdin.read().rstrip("\n")
p = pathlib.Path(".env"); lines = p.read_text(encoding="utf-8").splitlines()
out, done = [], False
for l in lines:
    if l.startswith(key + "="):
        if not done: out.append(f"{key}={val}"); done = True
        continue
    out.append(l)
if not done: out.append(f"{key}={val}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
'
envset() { python3 -c "${ENVSET}" "$1"; }
vol() { docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/forward-auth"}}{{.Name}}{{end}}{{end}}' "${FA}" 2>/dev/null; }
mem() {
  say "engine: $(free -m | awk '/^Mem:/{print "used " $3 " MiB, available " $7 " MiB of " $2}'); load $(cut -d' ' -f1-3 /proc/loadavg)"
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' $(docker ps -q --filter name="${AK}" --filter name="^${FA}\$") 2>/dev/null
}
# forward-auth's own boot lines that carry no secret: a users file that fails to load is quoted whole by
# its fatal error, so nothing broader than these two shapes is ever printed (the second reader)
bootlines() { docker logs --since "$1" "${FA}" 2>&1 | grep -E 'forward-auth: (listening on|[0-9]+ of [0-9]+ user)' | tail -2; }
# the services that read the switch, of those this office runs (compose service names; traefik's is
# `traefik-deployment` — missing it left the MacBook's edge asking a stopped authentik for 35 s)
services() {
  local known s out=""
  known="$(./scripts/dc config --services 2>/dev/null)" || return 1
  for s in forward-auth traefik-deployment lan-signin security browser42-caddy; do
    printf '%s\n' "${known}" | grep -qx "${s}" && out="${out} ${s}"; done
  printf '%s' "${out}"
}
binding() { sed -n 's/^  identity:[[:space:]]*\([a-z-]*\).*/\1/p' platform.state.yaml | head -1; }
has() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }     # has <service> "<list>"
# the offices swapped before these scripts moved here kept the rollback's values under ci-artifacts/r030
[ -s "${OUT}/pre-flip.env" ] || cp ci-artifacts/r030/pre-flip.env "${OUT}/" 2>/dev/null

case "${1:-}" in
  measure)
    mem
    docker ps -a --format '{{.Names}} {{.Status}}' | grep -E "^authentik-.*-${D}\$|^${FA}\$|^lan-(signin|outpost)-${D}\$|^traefik-${D}\$" ;;

  snapshot)   # §6.3(b): authentik's live sessions → forward-auth's volume, 600, owned by the service's uid
    V="$(vol)"; [ -n "${V}" ] || die "no forward-auth volume (is ${FA} running?)"
    # read first: a psql that fails replaces nothing (the rows stay in this shell, never printed)
    rows="$(docker exec "${PG}" psql -U authentik -d authentik -v ON_ERROR_STOP=1 -t -A -F' ' -c "
      select s.session_key, u.username, extract(epoch from s.expires)::bigint
      from authentik_core_authenticatedsession s join authentik_core_user u on u.id = s.user_id
      where s.expires > now()" 2>/dev/null)" || die "the sessions could not be read from ${PG}"
    # forward-auth refuses an empty sessions file (legacy.go: "no sessions"), so with none there is no pair
    # to make: the flip runs alone, and every browser signs in again with the same password
    [ -n "$(printf '%s\n' "${rows}" | grep . | head -1)" ] \
      || die "no live authentik session: skip snapshot and pair, run flip alone"
    printf '%s\n' "${rows}" | grep . | docker run --rm -i -v "${V}:/v" --entrypoint sh postgres:16-alpine -c \
      'cat > /v/legacy-sessions.new && chmod 600 /v/legacy-sessions.new && chown 65534:65534 /v/legacy-sessions.new && mv /v/legacy-sessions.new /v/legacy-sessions' \
      || die "the snapshot did not write"
    n="$(printf '%s\n' "${rows}" | grep -c .)"; unset rows
    say "legacy sessions snapshot: ${n} live authentik session(s) in ${V}:/legacy-sessions" ;;

  pair)       # the migration pair (both-or-neither) into .env; the flip's recreate reads it
    [ -n "$(envv AUTHENTIK_SECRET_KEY)" ] || die "no AUTHENTIK_SECRET_KEY in .env: the pair would be half, and forward-auth would not start"
    envv AUTHENTIK_SECRET_KEY | envset FORWARD_AUTH_LEGACY_SECRET
    printf '/etc/forward-auth/legacy-sessions' | envset FORWARD_AUTH_LEGACY_SESSIONS
    set_="$(grep -cE '^FORWARD_AUTH_LEGACY_(SECRET|SESSIONS)=.' .env)"
    [ "${set_}" = 2 ] || die "the pair is ${set_} of 2 in .env"
    say "pair written to .env (2 of 2 set)" ;;

  flip)       # §4 step 6: the edge asks forward-auth, and forward-auth takes the auth host.
    # Before it, by hand with the file tool: platform.state.yaml `bindings.identity: forward-auth`.
    # The auth host is the one authentik answers on now (AUTH_EXTERNAL_URL): a browser's authentik_session
    # cookie lives there, so only a sign-in on that host can carry it (the legacy pair, §6.4 #2).
    # vps1 names it AUTHENTIK_BASE_URL; an office with neither has authentik's default, auth.<domain>.
    [ "$(binding)" = forward-auth ] || die "platform.state.yaml binds identity to '$(binding)': set it to forward-auth first"
    auth="$(envv AUTH_EXTERNAL_URL)"; [ -n "${auth}" ] || auth="$(envv AUTHENTIK_BASE_URL)"
    [ -n "${auth}" ] || auth="auth.$(envv DEPLOYMENT_DOMAIN)"
    case "${auth}" in auth.*) ;; *) die "the auth host '${auth}' does not look like one" ;; esac
    # an office that set the sign-in's URL itself (a TLS office's signin) must say which scheme the new one
    # takes, or the old URL would keep the sign-in on signin.* and no authentik cookie would be carried
    if [ -z "${FA_PROTO:-}" ] && [ -n "$(envv FORWARD_AUTH_EXTERNAL_URL)" ] && [ "$(envv DGO_IDENTITY)" != forward-auth ]; then
      die "FORWARD_AUTH_EXTERNAL_URL is set: run with FA_PROTO=https (or http)"; fi
    # what the rollback restores (no secret among them) — written only while the office is still on
    # authentik, so a second flip never records the post-flip values over the real ones
    if [ "$(envv DGO_IDENTITY)" != forward-auth ]; then
      for k in DGO_IDENTITY FORWARD_AUTH_BASE_URL FORWARD_AUTH_EXTERNAL_URL; do
        printf '%s=%s\n' "${k}" "$(envv "${k}")"; done > "${OUT}/pre-flip.env"
    elif [ ! -s "${OUT}/pre-flip.env" ]; then
      die "this office is already on forward-auth and has no pre-flip.env: nothing to flip"; fi
    svcs="$(services)" || die "the compose config does not render (./scripts/dc config): nothing was changed"
    has forward-auth "${svcs}" && has traefik-deployment "${svcs}" \
      || die "forward-auth or traefik-deployment is not in the render (${svcs}): nothing was changed"
    printf '%s' "${auth}" | envset FORWARD_AUTH_BASE_URL
    [ -n "${FA_PROTO:-}" ] && printf '%s://%s' "${FA_PROTO}" "${auth}" | envset FORWARD_AUTH_EXTERNAL_URL
    printf 'forward-auth' | envset DGO_IDENTITY
    say "DGO_IDENTITY=$(envv DGO_IDENTITY); FORWARD_AUTH_BASE_URL=$(envv FORWARD_AUTH_BASE_URL); FORWARD_AUTH_EXTERNAL_URL=$(envv FORWARD_AUTH_EXTERNAL_URL)"
    python3 platform/manager/reconcile.py render > "${OUT}/render.log" 2>&1 \
      || die "the render failed (${OUT}/render.log); authentik still serves — run rollback to restore .env"
    grep -iE 'identity' "${OUT}/render.log" | head -2
    # authentik-server's routers hold the same host: they go in the same step (worker and database stay
    # up until `off`, so a rollback is a `docker start`)
    docker stop "authentik-server-${D}" >/dev/null && say "authentik-server stopped (kept)"
    case " ${svcs} " in *" lan-signin "*) ./bbox lan-console prepare 2>&1 | tail -3 ;; esac
    say "recreating:${svcs}"
    ./scripts/dc up -d --no-deps ${svcs} 2>&1 | grep -vi orphan | tail -6
    ok=""; for i in $(seq 1 24); do
      [ "$(docker inspect -f '{{.State.Health.Status}}' "${FA}" 2>/dev/null)" = healthy ] && { ok=1; break; }; sleep 5; done
    bootlines 3m
    [ -n "${ok}" ] || die "forward-auth is not healthy after the flip: run rollback NOW (the edge asks it)" ;;

  off)        # §4 step 7: authentik stopped — containers and volumes KEPT (rollback = docker start)
    mem
    ./bbox apps disable authentik 2>&1 | tail -2
    say "stopped $(docker stop $(docker ps -q --filter name="${AK}") 2>&1 | grep -c . || true) authentik container(s)"
    sleep 10; mem
    say "authentik containers running: $(docker ps --format '{{.Names}}' | grep -cE "${AK}" || true)" ;;

  rollback)   # §6.5: the edge back to authentik, authentik started again; nothing was deleted.
    # Before it, by hand: platform.state.yaml `bindings.identity: authentik`; and, on the MacBook, a revert
    # of the LAN door's change (c9cbfdce) if the LAN must go back too (lan-outpost: `bbox lan-console prepare`).
    [ "$(binding)" = authentik ] || die "platform.state.yaml binds identity to '$(binding)': set it back to authentik first"
    [ -s "${OUT}/pre-flip.env" ] || die "no pre-flip.env: restore DGO_IDENTITY, FORWARD_AUTH_BASE_URL by hand"
    grep -qx 'DGO_IDENTITY=forward-auth' "${OUT}/pre-flip.env" \
      && die "pre-flip.env records forward-auth, not what came before it: restore DGO_IDENTITY by hand"
    while IFS='=' read -r k v; do printf '%s' "${v}" | envset "${k}"; done < "${OUT}/pre-flip.env"
    say "restored: $(tr '\n' ' ' < "${OUT}/pre-flip.env")"
    ./bbox apps enable authentik 2>&1 | tail -1
    docker start $(docker ps -aq --filter name="${AK}") >/dev/null 2>&1
    svcs="$(services)" || die "the compose config does not render: recreate forward-auth and traefik-deployment by hand"
    has forward-auth "${svcs}" && has traefik-deployment "${svcs}" \
      || die "forward-auth or traefik-deployment is not in the render (${svcs}): recreate them by hand"
    ./scripts/dc up -d --no-deps ${svcs} 2>&1 | grep -vi orphan | tail -3
    say "rolled back: DGO_IDENTITY=$(envv DGO_IDENTITY), authentik started, recreated:${svcs}" ;;

  *) die "usage: window.sh measure|snapshot|pair|flip|off|rollback   (the sweeps: sweep.sh fa|edge|list)" ;;
esac
