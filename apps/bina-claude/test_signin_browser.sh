#!/usr/bin/env bash
# test_signin_browser.sh — the desktop's sign-in round trip (DGO-1506), offline: desktop/signin-browser opens
# the app's sign-in (and nothing else) in a throwaway browser profile, desktop/claude-desktop hands claude.ai's
# answer to the running app, and hooks/signin-log.awk reads what became of it. A fake browser and a fake app
# record what they were given; nothing here starts Chromium or the app.
#   bash apps/bina-claude/test_signin_browser.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN="${HERE}/desktop/signin-browser"
APPCMD="${HERE}/desktop/claude-desktop"
AWK_PROG="${HERE}/signin-log.awk"
W="$(mktemp -d)"
LOOP_PIDS=""
stop_loops() { for p in ${LOOP_PIDS}; do kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; done; LOOP_PIDS=""; }
cleanup() { stop_loops; pkill -f -- "--user-data-dir=${W}/tmp/bina-claude-signin\." 2>/dev/null; rm -rf "${W}"; }
trap cleanup EXIT
mkdir -p "${W}/home" "${W}/tmp"
export HOME="${W}/home" TMPDIR="${W}/tmp"
LOG="${HOME}/.claude-open-url.log"
pass=0; fail=0
ok() { pass=$((pass + 1)); echo "  ok   $1"; }
no() { fail=$((fail + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
check() { if eval "$2"; then ok "$1"; else no "$1" "${3:-}"; fi; }
wait_for() { local i; for i in $(seq 1 50); do eval "$1" && return 0; sleep 0.1; done; return 1; }
windows() { ls "${W}/tmp" 2>/dev/null | grep -c '^bina-claude-signin\.'; }

# The fake browser: records its arguments, notes that its profile folder exists, and stays open FAKE_STAY s.
cat > "${W}/browser" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "${FAKE_ARGS:-/dev/null}"
for a in "$@"; do case "$a" in --user-data-dir=*) [ -d "${a#--user-data-dir=}" ] && echo yes > "${FAKE_MARK:-/dev/null}";; esac; done
sleep "${FAKE_STAY:-0}"
SH
chmod 755 "${W}/browser"
export BINA_CLAUDE_BROWSER_BIN="${W}/browser"
# The fake app: records its arguments (the second instance that passes a link on) and exits FAKE_APP_RC.
cat > "${W}/app" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "${FAKE_APP_ARGS:-/dev/null}"
exit "${FAKE_APP_RC:-0}"
SH
chmod 755 "${W}/app"
export BINA_CLAUDE_APP_BIN="${W}/app"

NONCE="n0nce-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
SIGNIN="https://claude.com/cai/login/app-google-auth?open_in_browser=1&hop_nonce=${NONCE}"
CODE="c0de-$(head -c 9 /dev/urandom | od -An -tx1 | tr -d ' \n')"
ANSWER="claude://login/google-auth?code=${CODE}&hop_nonce=${NONCE}"

echo "signin-browser"
t0=$(date +%s)
FAKE_ARGS="${W}/args1" FAKE_MARK="${W}/mark1" FAKE_STAY=3 sh "${OPEN}" "${SIGNIN}"; rc=$?
t1=$(date +%s)
check "returns at once while the window stays open" "[ $rc = 0 ] && [ $((t1 - t0)) -lt 2 ]" "rc=$rc took $((t1 - t0)) s"
wait_for "grep -q 'closed sign-in window=' '${LOG}'"
check "the log says a sign-in opened, by host and path, and names its window" \
  "grep -q -E ' opened sign-in https://claude.com/cai/login/app-google-auth window=[A-Za-z0-9]+\$' '${LOG}'" "$(cat "${LOG}")"
check "the log never holds the nonce or a query" "! grep -q -e '${NONCE}' -e '?' '${LOG}'"
check "the browser was given the whole address, last" "[ \"\$(tail -n 1 '${W}/args1')\" = '${SIGNIN}' ]"
check "no sandbox (the container is), no keyring, no crash dumps, its own profile" \
  "grep -qx -- '--no-sandbox' '${W}/args1' && grep -qx -- '--password-store=basic' '${W}/args1' && grep -qx -- '--disable-breakpad' '${W}/args1' && grep -q -- '^--user-data-dir=${W}/tmp/bina-claude-signin\.' '${W}/args1'"
check "the window opens maximized (the whole phone screen)" "grep -qx -- '--start-maximized' '${W}/args1'"
check "its throwaway profile existed while the window was open" "[ \"\$(cat '${W}/mark1' 2>/dev/null)\" = yes ]"
check "the profile is gone once the window closed" "[ \"\$(windows)\" = 0 ]" "$(ls -A "${W}/tmp")"
id1=$(sed -n 's/.* opened sign-in .* window=\([A-Za-z0-9]*\)$/\1/p' "${LOG}" | tail -n 1)
check "the close names the same window, with the browser's exit" "grep -q \" closed sign-in window=${id1} (browser exit 0)\$\" '${LOG}'" "$(cat "${LOG}")"

: > "${LOG}"; rm -f "${W}/args2"
for u in "https://support.claude.com/en/articles/13189465?utm=x#top" "https://github.com/acme/repo?token=s3cr3t" \
         "https://claude.ai@evil.example/login/x" "https://claude.ai.evil.example/login/x" "http://localhost:8080/login/" \
         "https://claude.ai/?next=/login/" "https://claude.ai?a=/s3cr3t/login/" "https://claude.ai/x#hop_nonce=1"; do
  FAKE_ARGS="${W}/args2" sh "${OPEN}" "$u"
done
check "nothing but the app's sign-in on claude.ai/claude.com is opened (/login/ in the path, or its nonce)" "[ ! -e '${W}/args2' ] && [ \"\$(windows)\" = 0 ]"
check "…each refusal logged by host only" \
  "[ \"\$(grep -c ' not opened link ' '${LOG}')\" = 8 ] && grep -q 'not opened link support.claude.com:' '${LOG}' && grep -q 'not opened link evil.example:' '${LOG}' && grep -q 'not opened link claude.ai.evil.example:' '${LOG}' && ! grep -q -e s3cr3t -e repo -e articles -e '?' '${LOG}'" "$(cat "${LOG}")"
: > "${LOG}"
for u in 'https://evil.example\@claude.ai/login/x' 'https://claude.ai/login/ x' "$(printf 'https://claude.ai/login/\nforged')" 'https://claude.ai/login/é'; do
  FAKE_ARGS="${W}/args2" sh "${OPEN}" "$u"
done
check "a backslash, a space, a newline or a non-ASCII byte is refused before it is read" \
  "[ ! -e '${W}/args2' ] && [ \"\$(grep -c 'refused: not a plain web address' '${LOG}')\" = 4 ] && [ \"\$(wc -l < '${LOG}' | tr -d ' ')\" = 4 ] && ! grep -q -e evil -e forged '${LOG}'" "$(cat "${LOG}")"
sh "${OPEN}" "file:///etc/passwd"; rc=$?
check "anything but http(s) is refused" "[ $rc = 2 ] && grep -q 'refused: not a web address' '${LOG}'"
sh "${OPEN}"; rc=$?
check "no address is refused" "[ $rc = 2 ]"

: > "${LOG}"
FAKE_STAY=30 sh "${OPEN}" "${SIGNIN}"
wait_for "[ \"\$(windows)\" = 1 ]"
first="$(ls "${W}/tmp")"
FAKE_STAY=30 sh "${OPEN}" "${SIGNIN}2"
wait_for "grep -q 'closed sign-in window=.*(browser exit' '${LOG}'"
check "a second press closes the first press's window" "grep -q \"closed an earlier sign-in's window\" '${LOG}'" "$(cat "${LOG}")"
wait_for "[ ! -d '${W}/tmp/${first}' ]"
check "…and deletes its profile" "[ ! -d '${W}/tmp/${first}' ]"
check "one sign-in window is left open" "[ \"\$(windows)\" = 1 ]"
check "the log reads as the second window still open" "[ \"\$(awk -f '${AWK_PROG}' '${LOG}' | cut -d' ' -f2)\" = opened ]" "$(cat "${LOG}")"

echo "claude-desktop"
FAKE_APP_ARGS="${W}/app1" sh "${APPCMD}" --no-sandbox --disable-gpu --password-store=gnome-libsecret; rc=$?
check "with no link it is the app with this container's flags" \
  "[ $rc = 0 ] && [ \"\$(head -n 3 '${W}/app1' | tr '\n' ' ')\" = '--no-sandbox --disable-gpu --password-store=gnome-libsecret ' ]" "$(cat "${W}/app1")"

: > "${LOG}"; rm -f "${W}/app2"
FAKE_APP_ARGS="${W}/app2" sh "${APPCMD}" "${ANSWER}"; rc=$?
check "a link while the app is not running is dropped, not started" "[ $rc = 1 ] && [ ! -e '${W}/app2' ]"
check "…and the log says so, without the code" \
  "grep -q ' dropped sign-in answer claude://login/google-auth: the app is not running' '${LOG}' && ! grep -q -e '${CODE}' -e '${NONCE}' '${LOG}'" "$(cat "${LOG}")"

( exec -a "${W}/app --type=zygote" sleep 60 ) & LOOP_PIDS="${LOOP_PIDS} $!"
wait_for "ps -u \"\$(id -u)\" -o args= | grep -q '^${W}/app --type=zygote'"
: > "${LOG}"; rm -f "${W}/app2"
FAKE_APP_ARGS="${W}/app2" sh "${APPCMD}" "${ANSWER}"; rc=$?
check "a helper left behind (--type=) is not a running app" "[ $rc = 1 ] && [ ! -e '${W}/app2' ] && grep -q ' dropped sign-in answer ' '${LOG}'"

# A running app: a process whose command line starts with the app's path, not one of its --type= helpers.
( exec -a "${W}/app --no-sandbox --disable-gpu" sleep 60 ) & LOOP_PIDS="${LOOP_PIDS} $!"
wait_for "ps -u \"\$(id -u)\" -o args= | grep -q '^${W}/app --no-sandbox'"
FAKE_STAY=30 sh "${OPEN}" "${SIGNIN}"
wait_for "[ \"\$(windows)\" = 1 ]"
: > "${LOG}"
FAKE_APP_RC=3 FAKE_APP_ARGS="${W}/app3" sh "${APPCMD}" "${ANSWER}"; rc=$?
check "an answer the app did not take is said so, and its window stays open" \
  "[ $rc = 3 ] && grep -q ' failed to deliver sign-in answer claude://login/google-auth (exit 3)\$' '${LOG}' && ! grep -q -e ' delivered ' -e 'closed the sign-in window' '${LOG}' && [ \"\$(windows)\" = 1 ]" "$(cat "${LOG}")"
: > "${LOG}"
FAKE_APP_ARGS="${W}/app4" sh "${APPCMD}" "${ANSWER}"; rc=$?
check "the answer goes to the running app, with this container's flags" \
  "[ $rc = 0 ] && grep -qx -- '--no-sandbox' '${W}/app4' && [ \"\$(tail -n 1 '${W}/app4')\" = '${ANSWER}' ]" "$(cat "${W}/app4" 2>/dev/null)"
check "the log says it was delivered, by scheme, host and path only" \
  "grep -q ' delivered sign-in answer claude://login/google-auth to the app\$' '${LOG}' && ! grep -q -e '${CODE}' -e '${NONCE}' -e '?' '${LOG}'" "$(cat "${LOG}")"
check "the sign-in window is closed once the app took its answer" "grep -q ' closed the sign-in window\$' '${LOG}'"
wait_for "[ \"\$(windows)\" = 0 ]"
check "…and its profile is deleted" "[ \"\$(windows)\" = 0 ]"
: > "${LOG}"
FAKE_APP_ARGS="${W}/app5" sh "${APPCMD}" "claude://claude.ai/new?surface=chat&source=desktop_action"; rc=$?
check "the app's own links (its desktop actions) reach it too, as links" \
  "[ $rc = 0 ] && grep -q ' delivered link claude://claude.ai/new to the app' '${LOG}' && ! grep -q 'closed the sign-in window' '${LOG}'" "$(cat "${LOG}")"
stop_loops

echo "signin-log.awk"
state() { printf '%s\n' "$@" | awk -f "${AWK_PROG}"; }
T=2026-11-09T07:50:17Z
check "opened, then delivered" "[ \"\$(state '$T opened sign-in https://claude.com/x window=A1' '$T delivered sign-in answer claude://login/google-auth to the app' '$T closed the sign-in window' '$T closed sign-in window=A1 (browser exit 143)')\" = '$T delivered' ]"
check "opened, then the app was not running" "[ \"\$(state '$T opened sign-in https://claude.com/x window=A1' '$T dropped sign-in answer claude://login/google-auth: the app is not running')\" = '$T dropped' ]"
check "opened, then the app did not take it" "[ \"\$(state '$T opened sign-in https://claude.com/x window=A1' '$T failed to deliver sign-in answer claude://login/google-auth (exit 3)')\" = '$T failed' ]"
check "opened, then the window closed" "[ \"\$(state '$T opened sign-in https://claude.com/x window=A1' '$T closed sign-in window=A1 (browser exit 124)')\" = '$T closed' ]"
check "a double press: the first window's close is not the open one's" \
  "[ \"\$(state '$T opened sign-in https://claude.com/x window=A1' \"$T closed an earlier sign-in's window\" '$T opened sign-in https://claude.com/x window=B2' '$T closed sign-in window=A1 (browser exit 143)')\" = '$T opened' ]"
check "links and refusals alone say nothing" "[ -z \"\$(state '$T not opened link github.com: x' '$T delivered link claude://claude.ai/new to the app' '$T refused: not a web address')\" ]"
check "the older office browser's words say nothing here" "[ -z \"\$(state '$T busy: the office browser is busy')\" ]"

echo "${pass} passed, ${fail} failed"
[ "${fail}" = 0 ]
