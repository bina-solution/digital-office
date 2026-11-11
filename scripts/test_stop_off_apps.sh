#!/usr/bin/env bash
# test_stop_off_apps.sh — `bbox apps disable <app>` stops what it switched off (DGO-995): lib.sh stop_off_apps, read
# out of lib.sh itself, with docker and the compiler's answer (off_services) stubbed. No docker, no office.
#     bash scripts/test_stop_off_apps.sh
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
fn="$(awk '/^stop_off_apps\(\) \{/,/^\}/' "${HERE}/scripts/lib.sh")"
[ -n "${fn}" ] || { echo "FAIL  lib.sh no longer defines stop_off_apps"; exit 1; }
bad=0
# run <off_services answer|FAIL> <running "svc=id …"> <stop rc> <apps…> — prints the function's lines, then the
# docker calls it made (one per line, "docker …"), then "[rc] N"
run() {
  local off="$1" running="$2" stoprc="$3"; shift 3
  OFF="${off}" RUNNING="${running}" STOPRC="${stoprc}" PN="${PROJECT-proj}" CFG="${CONFIG_NAME-}" bash -c '
    say() { printf "%s\n" "$*"; }; cy=""; cr=""; c0=""; COMPOSE_PROJECT_NAME="${PN}"
    # compose'"'"'s own name for the project, as `dcx config --format json` answers it
    dcx() { [ -n "${CFG}" ] && printf "{\"name\": \"%s\"}\n" "${CFG}"; return 0; }
    off_services() { [ "${OFF}" = FAIL ] && return 1; printf "%b\n" "${OFF}"; }
    docker() { echo "docker $*" >> /tmp/stopoff.calls.$$
      case "$1" in
        ps) local svc=""; for a in "$@"; do case "$a" in label=com.docker.compose.service=*) svc="${a#*service=}";; esac; done
            for p in ${RUNNING}; do [ "${p%%=*}" = "${svc}" ] && echo "${p#*=}"; done; return 0 ;;
        stop) return "${STOPRC}" ;;
      esac; }
    eval "$1"; shift; stop_off_apps "$@"; rc=$?
    cat /tmp/stopoff.calls.$$ 2>/dev/null; rm -f /tmp/stopoff.calls.$$; echo "[rc] ${rc}"' _ "${fn}" "$@" 2>&1
}
check() { if grep -qF -- "$2" <<<"$3"; then echo "PASS  $1"; else echo "FAIL  $1 — wanted «$2» in:"; sed 's/^/        /' <<<"$3"; bad=1; fi; }
nope()  { if grep -qF -- "$2" <<<"$3"; then echo "FAIL  $1 — «$2» in:"; sed 's/^/        /' <<<"$3"; bad=1; else echo "PASS  $1"; fi; }

o="$(run 'forge\tgit\tdisabled\ngit\tgit\tdisabled\nother\tx\tdisabled' 'forge=c1 other=c9' 0 git)"
check "the app's running service is stopped, volumes kept" "git: switched off — stopped: forge (volumes kept)" "$o"
check "…by its compose project's label" "docker stop -t 20 c1" "$o"
check "…looked up in THIS project" "label=com.docker.compose.project=proj" "$o"
nope  "another switched-off app's container is left alone" "docker stop -t 20 c9" "$o"
check "…and it answers 0" "[rc] 0" "$o"

o="$(run 'other\tx\tdisabled' 'supabase=c3' 0 supabase)"
check "a switched-off app an enabled app requires keeps its containers" "supabase: switched off — its containers stay up while an enabled app requires it" "$o"
nope  "…and nothing is stopped" "docker stop" "$o"

o="$(run 'forge\tgit\tdisabled' '' 0 git)"
check "nothing running: said, nothing stopped" "git: switched off — nothing of it was running" "$o"

o="$(run 'forge\tgit\tdisabled' 'forge=c1' 1 git)"
check "a stop that fails is said" "git: could not stop forge" "$o"
check "…and answers non-zero" "[rc] 1" "$o"

o="$(run FAIL 'forge=c1' 0 git)"
check "the compiler does not answer: nothing stopped, said" "nothing stopped" "$o"
nope  "…no docker call at all" "docker " "$o"
check "…non-zero" "[rc] 1" "$o"

o="$(run 'a1\tdgo-extend\tdisabled\na2\tdgo-extend\tdisabled\nb1\tcomputers\tdisabled' 'a1=i1 a2=i2 b1=i3' 0 dgo-extend computers)"
check "every app named is stopped (the item's case: several at once)" "dgo-extend: switched off — stopped: a1 a2 (volumes kept)" "$o"
check "…the second one too" "computers: switched off — stopped: b1 (volumes kept)" "$o"

# a Latin-named checkout (vps1's digital-office): lib.sh leaves COMPOSE_PROJECT_NAME empty — compose's own name
o="$(PROJECT= CONFIG_NAME=digital-office run 'forge\tgit\tdisabled' 'forge=c1' 0 git)"
check "no COMPOSE_PROJECT_NAME: the project compose names is used" "label=com.docker.compose.project=digital-office" "$o"
check "…and the app is stopped" "git: switched off — stopped: forge (volumes kept)" "$o"
o="$(PROJECT= CONFIG_NAME= run 'forge\tgit\tdisabled' 'forge=c1' 0 git)"
check "no name at all: refused, said" "could not tell this office's compose project — nothing stopped" "$o"
nope  "…no docker call" "docker " "$o"
check "…non-zero" "[rc] 1" "$o"
exit ${bad}
