#!/usr/bin/env bash
# What `hooks/refresh` DECIDES, against an engine this test plays itself.
#
#   bash platform-base/authentik/test_refresh.sh
#
# The hook has three remedies and they cost very different things: waiting (nothing), having the
# sentinel apply every blueprint again (minutes, no outage), restarting the sign-in server (a minute
# in which every gated host of the office answers 404 or 5xx). Which one it reaches for, in what
# order, after how long — and, more to the point, when it must touch nothing — cannot be tried on a
# running office without taking it down each time, so the decisions are tried here: the hook's own
# text runs unmodified except for the one line that sources scripts/lib.sh, which is pointed at a
# stand-in whose `docker` answers from files this test writes and whose clock moves only when the
# hook sleeps — so "fifteen minutes later" costs nothing to reach.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT

cat > "${T}/lib.sh" <<'STUB'
DN=t; c0=; c1=; cy=; cr=; cg=
say() { echo "say: $*"; }
ok()  { echo "ok: $*"; }
# the clock: real time plus every second the hook has slept
skew()  { cat "${T}/skew" 2>/dev/null || echo 0; }
sleep() { echo $(( $(skew) + ${1%.*} )) > "${T}/skew"; }
date()  { if [ "$*" = "+%s" ]; then echo $(( $(command date +%s) + $(skew) )); else command date "$@"; fi; }
dcx() { echo "UP $*" >> "${T}/calls"; }
running() { grep -Fxq "$1" "${T}/running"; }
iso() { command date -u -d "@$1" +%Y-%m-%dT%H:%M:%S.000000000Z; }
count() { local n; n="$(cat "${T}/$1" 2>/dev/null || echo 0)"; n=$((n + 1)); echo "${n}" > "${T}/$1"; echo "${n}"; }
docker() {
  case "$1" in
    inspect) cat "${T}/started.${!#}" 2>/dev/null ;;
    logs)    echo '{"event": "a json line of authentik"}'; echo "authentik not ready yet (attempt 7/60) — retrying in 5s" ;;
    restart)
      echo "RESTART $2 after $(skew)s" >> "${T}/calls"; iso "$(date +%s)" > "${T}/started.$2"
      case "$2" in
        authentik-bootstrap-t) : > "${T}/applying"; rm -f "${T}/checks" ;;   # it starts applying again
        authentik-server-t)      # a restarted server loads everything that was applied — unless the case says not
          rm -f "${T}/n"; [ -f "${T}/server-cures-nothing" ] || echo 0 > "${T}/probe" ;;
      esac ;;
    exec)
      case "$3" in
        rm) rm -f "${T}/applied" ;;
        test)                    # has the sentinel said it applied? an applying one says so after APPLIES_IN asks
          local c; c="$(count checks)"
          if [ -f "${T}/applying" ] && [ "${c}" -ge "$(cat "${T}/applies-in" 2>/dev/null || echo 2)" ]; then
            # applied: it says so, and from here the outpost answers what this case says it then does
            rm -f "${T}/applying" "${T}/n"; : > "${T}/applied"
            [ -f "${T}/probe.after-apply" ] && cp "${T}/probe.after-apply" "${T}/probe"
          fi
          [ -f "${T}/applied" ] ;;
        *)                       # the probe
          local n rc; n="$(count n)"
          rc="$(sed -n "${n}p" "${T}/probe")"; [ -n "${rc}" ] || rc="$(tail -1 "${T}/probe")"
          [ "${rc}" = 1 ] && echo "outpost not serving: new.localhost" >&2
          [ "${rc}" = 2 ] && echo "the compiled blueprint states no gated_hosts" >&2
          return "${rc}" ;;
      esac ;;
  esac
}
STUB

fails=0
# case_ <label> <server: young|old|absent> <probe answers, last repeats> <want: sentinel/server restarts> <want: exit> [setup]
# The sentinel of every case applied long ago and said so, unless the setup says otherwise.
case_() {
  local label="$1" server="$2" probes="$3" want="$4" want_exit="$5" setup="${6:-}"
  rm -f "${T}/calls" "${T}/n" "${T}/checks" "${T}/skew" "${T}/applying" "${T}/applies-in" \
        "${T}/probe.after-apply" "${T}/server-cures-nothing" "${T}"/started.*
  : > "${T}/calls"; : > "${T}/applied"
  printf '%s\n' authentik-server-t authentik-bootstrap-t > "${T}/running"
  date -u -d "@$(( $(date +%s) - 5000 ))" +%Y-%m-%dT%H:%M:%S.000000000Z > "${T}/started.authentik-bootstrap-t"
  case "${server}" in
    young)  date -u -d "@$(( $(date +%s) - 10 ))" +%Y-%m-%dT%H:%M:%S.000000000Z > "${T}/started.authentik-server-t" ;;
    old)    date -u -d "@$(( $(date +%s) - 5000 ))" +%Y-%m-%dT%H:%M:%S.000000000Z > "${T}/started.authentik-server-t" ;;
    absent) : > "${T}/running" ;;
  esac
  printf '%s\n' ${probes} > "${T}/probe"
  [ -n "${setup}" ] && eval "${setup}"
  sed 's|^\. "\${REPO_ROOT}/scripts/lib.sh".*|. "${T}/lib.sh"|' "${HERE}/hooks/refresh" > "${T}/hook"
  local rc got
  out="$(T="${T}" bash "${T}/hook" 2>&1)"; rc=$?
  got="$(grep -c '^RESTART authentik-bootstrap-t' "${T}/calls")/$(grep -c '^RESTART authentik-server-t' "${T}/calls")"
  order="$(sed -n 's/^RESTART authentik-\([a-z]*\)-t after \([0-9]*\)s$/\1 at \2s/p' "${T}/calls" | paste -sd, | sed 's/,/, then /; s/bootstrap/sentinel/')"
  if [ "${got}" = "${want}" ] && [ "${rc}" = "${want_exit}" ]; then
    echo "PASS  ${label} — ${order:-nothing restarted}, exit ${rc} after $(cat "${T}/skew" 2>/dev/null || echo 0)s"
  else
    echo "FAIL  ${label} — sentinel/server restarts ${got} (want ${want}), exit ${rc} (want ${want_exit})"; echo "${out}" | sed 's/^/        /'
    fails=$((fails + 1))
  fi
}
# at_ <which: bootstrap|server> <at least> <less than> — that restart of the case just run came in that span of waiting
at_() {
  local t; t="$(sed -n "s/^RESTART authentik-$1-t after \([0-9]*\)s\$/\1/p" "${T}/calls" | head -1)"
  if [ -n "${t}" ] && [ "${t}" -ge "$2" ] && [ "${t}" -lt "$3" ]; then
    echo "PASS  …the ${1/bootstrap/sentinel} only after ${t}s of waiting (wanted $2–$3)"
  else
    echo "FAIL  the ${1/bootstrap/sentinel} was restarted after ${t:-no}s of waiting (wanted $2–$3)"; fails=$((fails + 1))
  fi
}
said_() {   # said_ <words the hook must have said in the case just run>
  if echo "${out}" | grep -q "$1"; then echo "PASS  …and it says so: «$1»"; else
    echo "FAIL  the hook did not say «$1»"; echo "${out}" | sed 's/^/        /'; fails=$((fails + 1)); fi
}

grep -q '^\. "\${REPO_ROOT}/scripts/lib.sh"' "${HERE}/hooks/refresh" \
  || { echo "FAIL  the hook no longer sources scripts/lib.sh on a line this test can replace"; exit 1; }

echo "── nothing is touched"
case_ "every gated host is served"                                              old    "0"       0/0 0
case_ "a new host the outpost learns by itself is waited for"                   old    "1 1 1 0" 0/0 0
case_ "a server that has only just started is waited for"                       young  "1 1 1 0" 0/0 0
case_ "there is no list of hosts to ask about: said, and nothing is acted on"   old    "2"       0/0 0
said_ "could not verify"
case_ "the sign-in server is not running here: nothing to do"                   absent "1"       0/0 0
case_ "a sentinel that is still applying when the hook arrives is waited for, not started over" old "1" 0/0 0 \
      'rm -f "${T}/applied"; : > "${T}/applying"; echo 40 > "${T}/applies-in"; echo 0 > "${T}/probe.after-apply"'
said_ "still applying"
echo "── the sentinel applies again, and that is enough: the server is never restarted"
case_ "a render nobody applied"                                                 old    "1"       1/0 0 'printf "1\n0\n" > "${T}/probe.after-apply"'
at_ bootstrap 90 120
case_ "…also when applying takes ten minutes (what it said LAST time is not this time's word)" old "1" 1/0 0 \
      'echo 0 > "${T}/probe.after-apply"; echo 120 > "${T}/applies-in"'
case_ "a young server that never comes to serve the host: the same, once it has had its time" young "1" 1/0 0 'echo 0 > "${T}/probe.after-apply"'
at_ bootstrap 170 200
echo "── blueprints that are never applied are not the outpost's fault: the server is left alone"
case_ "the sentinel does not arrive in fifteen minutes (a refused blueprint, a crash loop)" old "1" 1/0 1 'echo 100000 > "${T}/applies-in"'
said_ "still not applied after 15 minutes"
said_ "last word: authentik not ready yet (attempt 7/60)"
echo "── applied again and still not served: only then the server"
case_ "an outpost that does not learn what was applied"                         old    "1"       1/1 0
at_ bootstrap 90 120
at_ server 180 260            # a second LEARN after the sentinel said it had applied
case_ "the restart cures nothing either: loud, and exit 1"                      old    "1"       1/1 1 ': > "${T}/server-cures-nothing"'
said_ "still not served after restarting authentik-server — outpost not serving: new.localhost"
echo "── what the hook starts"
case_ "the sentinel and the worker are brought up together, without their dependencies" old "0" 0/0 0
if [ "$(cat "${T}/calls")" = "UP up -d --no-deps authentik-worker authentik-bootstrap" ]; then
  echo "PASS  …and that is the only thing the hook starts"
else
  echo "FAIL  the hook started: $(cat "${T}/calls")"; fails=$((fails + 1))
fi

echo; echo "${fails} failing"
[ "${fails}" = 0 ]
