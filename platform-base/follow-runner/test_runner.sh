#!/usr/bin/env bash
# test_runner.sh — runner.sh starts ONE follow cycle in a container of its own, only when the office declares
# DGO_FOLLOW, never beside one that still runs, never on an engine that does not answer, and keeps how the last one
# ended.
#
#     bash platform-base/follow-runner/test_runner.sh
#
# A fake `docker` (FOLLOW_DOCKER) records every call and plays the engine: `ps` gives the cycle's state (or fails),
# `inspect` gives this service's image or the last cycle's exit code, `logs` its last words, `rm`/`run` succeed or not.
# The checkout is a temp folder with a .env; the socket is a temp file. Needs bash 4 and GNU stat; no engine.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fails=0
ok() { if eval "$2"; then echo "PASS  $1"; else echo "FAIL  $1"; sed 's/^/      | /' "${CALLS}" "${T}/out" 2>/dev/null | tail -8; fails=$((fails + 1)); fi; }

cat > "${T}/docker" <<'EOF'
#!/bin/sh
echo "$*" >> "${CALLS}"
case "$1" in
  ps)      [ -e "${STUB}/ps-fails" ] && exit 1; cat "${STUB}/state" 2>/dev/null; exit 0 ;;
  inspect) case "$*" in
             *ExitCode*) cat "${STUB}/exitcode" 2>/dev/null; exit 0 ;;
             # only this service's own container (compose's container_name) has the image the cycle runs from
             *" follow-runner-t") [ -e "${STUB}/no-image" ] && exit 1; echo sha256:image; exit 0 ;;
             *) exit 1 ;;
           esac ;;
  logs)    echo "the last words of the cycle"; exit 0 ;;
  rm)      [ -e "${STUB}/rm-fails" ] && exit 1; exit 0 ;;
  run)     [ -e "${STUB}/refuse" ] && exit 1; echo cid; exit 0 ;;
esac
EOF
chmod +x "${T}/docker"
export STUB="${T}/stub" CALLS="${T}/calls" FOLLOW_DOCKER="${T}/docker" FOLLOW_ONCE=1 FOLLOW_SOCK="${T}/sock" \
       BBOX_REPO_HOST="${T}/office" DEPLOYMENT_NAME=t BBOX_HOST_DOCKER_SOCK=/run/bbox-docker.sock BBOX_HOST_TZ=Asia/Jerusalem
unset DGO_FOLLOW_GIT_CREDENTIALS FOLLOW_USER
fresh() { rm -rf "${STUB}" "${T}/office"; mkdir -p "${STUB}" "${T}/office"; : > "${T}/sock"; : > "${CALLS}"
          printf 'DEPLOYMENT_NAME=t\nDGO_FOLLOW=%s\n' "$1" > "${T}/office/.env"; }
runner() { bash "${HERE}/runner.sh" > "${T}/out" 2>&1; }
ran() { grep -c '^run ' "${CALLS}"; }
run_line() { grep '^run ' "${CALLS}"; }

fresh ""; runner
ok "DGO_FOLLOW not declared: no cycle, not even asked" '[ "$(ran)" = 0 ] && grep -q "not declared" "${T}/out"'

fresh dgo-stable; runner; line="$(run_line)"
ok "declared: one cycle started" '[ "$(ran)" = 1 ] && grep -q "cycle started" "${T}/out"'
ok "a container of its own, by name, kept after it ends (no --rm)" 'grep -q -- "--name follow-cycle-t " <<<"${line}" && ! grep -q -- "--rm" <<<"${line}"'
ok "not taken for the follow service (its compose service label cleared)" 'grep -q -- "--label com.docker.compose.service= " <<<"${line}"'
ok "root by default, as bina-ds writes the checkout; git trusts it" '! grep -q -- "--user" <<<"${line}" && grep -q "GIT_CONFIG_KEY_0=safe.directory" <<<"${line}"'
ok "the checkout at its host path, the HOST socket path" 'grep -q -- "-v ${T}/office:${T}/office -v /run/bbox-docker.sock:/var/run/docker.sock" <<<"${line}"'
ok "the host zone handed on (what its bbox run compiles)" 'grep -q -- "-e BBOX_HOST_TZ=Asia/Jerusalem" <<<"${line}"'
ok "bounded: timeout 6h around follow.sh, from its own image" 'grep -q "sha256:image timeout -k 60 6h bash ${T}/office/scripts/follow.sh" <<<"${line}" && grep -q "binaos.max-age=21600" <<<"${line}"'
ok "on the stack network (egress where the default bridge has none)" 'grep -q -- "--network traefik-network" <<<"${line}"'
ok "no git credential when none is declared" '! grep -q "git-credentials" <<<"${line}" && grep -q "GIT_CONFIG_COUNT=1 " <<<"${line}"'

fresh dgo-stable; FOLLOW_USER=1000:1000 runner; line="$(run_line)"
ok "FOLLOW_USER declares the writer, with the socket's group" 'grep -q -- "--user 1000:1000 --group-add $(stat -c %g "${T}/sock")" <<<"${line}"'

fresh dgo-stable; DGO_FOLLOW_GIT_CREDENTIALS=/home/owner/.git-credentials runner; line="$(run_line)"
ok "a declared credential: --mount read-only (a missing file is refused, never made a directory), git reads it" \
   'grep -q -- "--mount type=bind,source=/home/owner/.git-credentials,target=/tmp/follow-home/.git-credentials,readonly" <<<"${line}" && grep -q "GIT_CONFIG_COUNT=2 " <<<"${line}" && grep -q "GIT_CONFIG_VALUE_1=store" <<<"${line}"'

fresh dgo-stable; echo running > "${STUB}/state"; runner
ok "a cycle still running: no second one, and it is not removed" '[ "$(ran)" = 0 ] && ! grep -q "^rm " "${CALLS}" && grep -q "still running" "${T}/out"'

fresh dgo-stable; touch "${STUB}/ps-fails"; runner
ok "the engine does not answer ps: nothing removed, nothing started" '[ "$(ran)" = 0 ] && ! grep -q "^rm " "${CALLS}" && grep -q "did not answer" "${T}/out"'

fresh dgo-stable; echo exited > "${STUB}/state"; echo 1 > "${STUB}/exitcode"; runner
ok "the previous cycle failed: its exit and last words logged, removed (never forced), a new one started" \
   'grep -q "ended with exit 1" "${T}/out" && grep -q "the last words" "${T}/out" && grep -q "^rm follow-cycle-t$" "${CALLS}" && [ "$(ran)" = 1 ]'

fresh dgo-stable; echo exited > "${STUB}/state"; echo 1 > "${STUB}/exitcode"; touch "${STUB}/rm-fails"; runner
ok "the previous cycle cannot be removed: no new one" '[ "$(ran)" = 0 ] && grep -q "could not remove" "${T}/out"'

fresh dgo-stable; touch "${STUB}/no-image"; runner
ok "its own image unreadable: no cycle, said" '[ "$(ran)" = 0 ] && grep -q "cannot read this service" "${T}/out"'

fresh dgo-stable; touch "${STUB}/refuse"; runner; rc=$?
ok "the engine refuses: said, and a failing exit" '[ "${rc}" != 0 ] && grep -q "refused" "${T}/out"'

echo
[ "${fails}" = 0 ] && echo "test_runner: all passed" || echo "test_runner: ${fails} FAILED"
exit $((fails > 0))
