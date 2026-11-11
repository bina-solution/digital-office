#!/usr/bin/env bash
# test_link_status.sh — `bbox dgo link status` answers within ten seconds and says what it means (DGO-1784, DGO-1782).
#
#     bash apps/dgo-extend/tests/test_link_status.sh
#
# On 2026-11-10, at load 21 on the MacBook, the status printed nothing for 180 s, three runs in a row; and a tunnel that
# answered while the office's catalog check did not read «down», which to the owner means the office is off. The hook
# runs here against a fake `docker` (the app's answer, a hang, or an error page) and a `curl` that reaches nothing.
# The hang is a GRANDCHILD of the bounded command (bash → docker → sleep), as a stuck `docker exec` is: a bound that
# kills only the command it started (uutils' `timeout`, Ubuntu 25.10+) leaves it holding the pipe — 121 s on the
# Dell's runner, 2026-11-10. Needs only bash: the hook bounds by itself.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HOOK="${HERE}/../hooks/link"
mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }   # GNU/uutils, or BSD (a Mac)
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/bin" "${T}/tmp"
fails=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; sed 's/^/      | /' "${T}/out" | tail -8; fails=$((fails + 1)); fi; }

# the app's answer: the HP connected with its check unanswered, vps1 not measured yet, the Dell really down
cat > "${T}/link.json" <<'EOF'
{"home": {"id": "macbook", "slot": 2, "domain": "localhost", "fingerprint": "AAAA"}, "tunnel": {"tunnel": {}},
 "items": [
  {"office": "hp-laptop", "declared": true, "state": "down", "verdict": {"ok": false, "hop": "office", "why": "x"},
   "tunnel": {"handshake_age_s": 30, "alive": true}, "transport": "tcp",
   "carry": {"state": "up", "via": "172.18.0.1:41304", "dialed": false, "rtt_ms": 7.8, "heard_s": 0}, "kind": "paired"},
  {"office": "vps1", "declared": true, "state": "unknown", "verdict": {"ok": null, "hop": "", "why": ""},
   "tunnel": {"handshake_age_s": 20, "alive": true}, "transport": "udp", "kind": "paired"},
  {"office": "portable-ubuntu", "declared": true, "state": "down", "verdict": {"ok": false, "hop": "tunnel", "why": "x"},
   "tunnel": {"handshake_age_s": 900, "alive": false}, "transport": "udp", "kind": "paired"}]}
EOF
printf '{"items": []}' > "${T}/history.json"
cat > "${T}/bin/docker" <<EOF
#!/bin/sh
# ps → the app's container; exec → as ${T}/mode says: ok (the answer for the path asked), hang, error
case "\$1" in
  ps) echo dgo-extend-test ;;
  exec)
    cat > /dev/null                                  # the program on stdin
    case "\$(cat "${T}/mode")" in
      hang)  exec sleep 120 ;;
      error) echo '<html>502 Bad Gateway</html>' ;;
      *)     case "\$7" in /api/link/history*) cat "${T}/history.json" ;; *) cat "${T}/link.json" ;; esac ;;
    esac ;;
esac
EOF
printf '#!/bin/sh\nexit 7\n' > "${T}/bin/curl"               # nothing answers by name: the docker path is taken
chmod +x "${T}/bin/"*
run() { local s; s="$(date +%s)"; TMPDIR="${T}/tmp" PATH="${T}/bin:${PATH}" bash "${HOOK}" status > "${T}/out" 2>&1; rc=$?
        took=$(( $(date +%s) - s )); }

# 1. live: the words the owner reads
echo ok > "${T}/mode"; run
check "live: answers, exit 0" '[ "${rc}" = 0 ] && grep -q "^home: macbook" "${T}/out"'
check "live: answered before the bound — nothing of the bound held the pipe (took ${took} s)" '[ "${took}" -lt 7 ]'
check "a live tunnel whose check did not answer: «connected», never down" 'grep -q "answers: connected - the check did not answer (מחובר, הבדיקה לא ענתה)" "${T}/out"'
check "an office not measured yet: «not measured» by name" 'grep -q "answers: not measured (לא נמדד)" "${T}/out"'
check "a dead tunnel is still down" '[ "$(grep -c "answers: down" "${T}/out")" = 1 ]'
check "the reading is kept, privately" '[ -n "$(ls "${T}/tmp"/bbox-link-status-*.link 2>/dev/null)" ] && [ "$(mode_of "${T}"/tmp/bbox-link-status-*.link)" = 600 ]'
# 2. the app hangs: the last reading, its age, within ten seconds, exit 3
echo hang > "${T}/mode"; run
check "the app hangs: answered within 10 s (took ${took} s)" '[ "${took}" -le 10 ]'
check "…from the last reading, with its age, exit 3" '[ "${rc}" = 3 ] && grep -q "^measured: [0-9]*s ago" "${T}/out" && grep -q "answers: connected" "${T}/out"'
# 3. the app answers with an error page: it never replaces the kept reading
echo error > "${T}/mode"; run
check "an error page: the kept reading shown, not the page" '[ "${rc}" = 3 ] && grep -q "^home: macbook" "${T}/out" && grep -q "\"home\"" "${T}"/tmp/bbox-link-status-*.link'
# 4. nothing kept and nothing answers: «לא נמדד», exit 1, within ten seconds
rm -f "${T}"/tmp/bbox-link-status-*; echo hang > "${T}/mode"; run
check "nothing kept, the app hangs: «לא נמדד», exit 1, within 10 s (took ${took} s)" '[ "${rc}" = 1 ] && grep -q "לא נמדד" "${T}/out" && [ "${took}" -le 10 ]'

echo
[ "${fails}" = 0 ] && echo "PASS test_link_status" || echo "FAIL test_link_status (${fails} failed)"
exit $((fails > 0))
