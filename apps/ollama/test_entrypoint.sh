#!/usr/bin/env bash
# test_entrypoint.sh — the Ollama app's own start, against a stand-in `ollama`: what the office declares
# is there after a start, and a stop is answered at once.
#
#     bash apps/ollama/test_entrypoint.sh
#
# entrypoint.sh is the app's only logic: OLLAMA_PULL is the declaration and nobody pulls by hand
# (DGO-825). So a model that is there must be left alone (a restart never swaps it for a newer upload
# under the same tag), a missing one pulled, one that cannot be pulled said — its error's last line,
# without the spinner's escape codes — and the server kept serving; an office whose server never
# answers pulls nothing and says why; and a stop in the middle of a download of gigabytes ends the
# start at once. The stand-in is a script on PATH (serve / list / show / pull), in a directory of its
# own: no container, no network, no model. Written for the app standard (DGO-1039: ollama had no test).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRY="${HERE}/entrypoint.sh"
REAL_SLEEP="$(command -v sleep)"
T="$(mktemp -d)"; trap 'reap; rm -rf "${T}"' EXIT
fails=0
say() { printf '%s  %s\n' "$1" "$2"; }
check() { if eval "$1"; then say PASS "$2"; else say FAIL "$2"; fails=$((fails + 1)); fi; }

mkdir -p "${T}/bin" "${T}/fastbin"
cat > "${T}/bin/ollama" <<'STUB'
#!/bin/sh
S="${STUB_STATE}"
case "$1" in
  serve) echo $$ > "${S}/serve.pid"; [ -n "${STUB_NO_ANSWER:-}" ] || : > "${S}/up"; exec "${REAL_SLEEP}" 300 ;;
  list)  echo x >> "${S}/listed"; [ -f "${S}/up" ] ;;
  show)  [ -f "${S}/models/$2" ] ;;
  pull)  echo "$2" >> "${S}/pulled"
         case " ${STUB_FAIL:-} " in
           # as ollama's own progress ends: the spinner's line, then the cursor shown again before the error
           *" $2 "*) printf 'pulling manifest \033[?25l\033[1G\033[K\rpulling manifest \033[K\n\033[?25h\033[?2026lError: pull model manifest: file does not exist\n'; exit 1 ;;
         esac
         [ "$2" != "${STUB_HANG:-}" ] || { echo $$ > "${S}/pull.pid"; exec "${REAL_SLEEP}" 60; }
         : > "${S}/models/$2" ;;
esac
STUB
printf '#!/bin/sh\nexit 0\n' > "${T}/fastbin/sleep"   # the 120 one-second waits, without the 120 seconds
chmod +x "${T}/bin/ollama" "${T}/fastbin/sleep"

# start <case> [VAR=value…]: the entrypoint in the background, in a state directory of its own — its
# pull log there too (TMPDIR), and no OLLAMA_PULL but the case's own
start() {
  S="${T}/$1"; shift
  mkdir -p "${S}/models"; : > "${S}/pulled"
  env -u OLLAMA_PULL STUB_STATE="${S}" REAL_SLEEP="${REAL_SLEEP}" TMPDIR="${S}" PATH="${T}/bin:${PATH}" "$@" \
    sh "${ENTRY}" > "${S}/out" 2> "${S}/err" &
  pid=$!
}
# until <seconds> <condition>: true once the condition holds, false when the time is out
until_() { local n=$(( $1 * 10 )); shift; while [ "${n}" -gt 0 ]; do eval "$1" && return 0; "${REAL_SLEEP}" 0.1; n=$((n - 1)); done; return 1; }
# leftovers: put down what a case's stand-ins still run, and forget their pids — a pull outlives the
# entrypoint's stop by design (its trap kills the pulls' subshell, not the pull it runs; in the
# container that dies with the container)
leftovers() {
  local f p
  for f in "${S}/serve.pid" "${S}/pull.pid"; do
    p="$(cat "${f}" 2>/dev/null)"; [ -n "${p}" ] && kill -KILL "${p}" 2>/dev/null; rm -f "${f}"
  done
  return 0
}
reap() { [ -z "${pid:-}" ] || kill -KILL "${pid}" 2>/dev/null; [ -z "${S:-}" ] || leftovers; }
# stop: TERM, as `docker stop` sends it; its exit code (124 when it is still running 5 s later, then
# killed), and whether the server outlived it — before the case's leftovers are put down
stop() {
  local p
  kill -TERM "${pid}" 2>/dev/null
  if until_ 5 '! kill -0 "${pid}" 2>/dev/null'; then wait "${pid}"; rc=$?; else rc=124; kill -KILL "${pid}" 2>/dev/null; fi
  pid=""
  p="$(cat "${S}/serve.pid" 2>/dev/null)"
  if [ -n "${p}" ] && kill -0 "${p}" 2>/dev/null; then server_left=yes; else server_left=no; fi
  leftovers
}
# pulls_done: the pulls' subshell asked the server, and has ended — the entrypoint's one child left is
# the server (without pgrep, past the subshell's one-second wait instead)
pulls_done() {
  [ -s "${S}/listed" ] || return 1
  command -v pgrep >/dev/null || { "${REAL_SLEEP}" 2.5; return 0; }
  [ "$(pgrep -P "${pid}" | wc -l)" -le 1 ]
}

# 1. one declared model there, one missing, one that cannot be pulled — separated by a comma and spaces
mkdir -p "${T}/declared/models"; : > "${T}/declared/models/a:1"
start declared OLLAMA_PULL="a:1, b:2 c:3" STUB_FAIL="c:3"
until_ 10 'grep -q "c:3 could not be pulled" "${S}/err"'
check 'grep -qx "\[ollama\] declared model a:1: present" "${S}/out"' "a declared model that is there is said present"
check '[ "$(tr "\n" " " < "${S}/pulled")" = "b:2 c:3 " ]' "only the missing ones are pulled, in the declared order (pulled: $(tr '\n' ' ' < "${S}/pulled"))"
check 'grep -qx "\[ollama\] declared model b:2: pulled" "${S}/out"' "a missing model is pulled and said pulled"
check 'grep -q "c:3 could not be pulled now (offline, or no such tag) — tried again on the next start: Error: pull model manifest: file does not exist$" "${S}/err"' "a pull that fails is said with its error's last line"
check '! grep -q "$(printf "\033")" "${S}/err"' "the failure line carries none of the spinner's escape codes"
until_ 5 pulls_done
check 'kill -0 "${pid}" 2>/dev/null && kill -0 "$(cat "${S}/serve.pid")" 2>/dev/null' "the server goes on serving after a failed pull"
stop
check '[ "${rc}" = 0 ]' "a stop ends the start with 0 (exit ${rc})"
check '[ "${server_left}" = no ]' "and the server with it"

# 2. nothing declared: nothing pulled, nothing said about models — read once the pulls' part has ended
start nothing
until_ 10 pulls_done
check '[ -s "${S}/listed" ] && [ ! -s "${S}/pulled" ] && ! grep -q "declared model" "${S}/out" "${S}/err"' "no declaration, no pull"
stop
check '[ "${rc}" = 0 ]' "a stop with nothing declared ends with 0 (exit ${rc})"

# 3. a server that never answers: the pulls give up after their 120 waits and say so; the start goes on
start silent OLLAMA_PULL="a:1" STUB_NO_ANSWER=1 PATH="${T}/bin:${T}/fastbin:${PATH}"
until_ 10 'grep -q "did not answer" "${S}/err"'
check 'grep -qx "\[ollama\] the server did not answer in 120 s — not pulling" "${S}/err"' "a server that never answers is said, and nothing is pulled"
check '[ ! -s "${S}/pulled" ]' "…nothing pulled"
stop
check '[ "${rc}" = 0 ]' "a stop then ends with 0 (exit ${rc})"

# 4. a stop in the middle of a download
start hang OLLAMA_PULL="big:70b" STUB_HANG="big:70b"
until_ 10 'grep -q "big:70b: pulling" "${S}/out"'
"${REAL_SLEEP}" 0.3
t0="$(date +%s)"; stop; took=$(( $(date +%s) - t0 ))
check '[ "${rc}" = 0 ] && [ "${took}" -le 2 ]' "a stop during a pull is answered at once (exit ${rc} after ${took}s)"

[ "${fails}" -eq 0 ] && echo "ollama entrypoint: all checks pass" || echo "ollama entrypoint: ${fails} check(s) failed"
exit "$(( fails > 0 ))"
