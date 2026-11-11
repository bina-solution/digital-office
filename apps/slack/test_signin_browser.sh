#!/usr/bin/env bash
# test_signin_browser.sh — Slack's sign-in round trip (DGO-1264), offline: desktop/signin-browser opens Slack's own
# addresses (and nothing else) in a throwaway browser profile, and desktop/open-link hands the slack:// answer only
# to a RUNNING Slack. A fake browser and a fake app record what they were given; nothing starts Chromium or Slack.
#   bash apps/slack/test_signin_browser.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN="${HERE}/desktop/signin-browser"
LINK="${HERE}/desktop/open-link"
W="$(mktemp -d)"
cleanup() { pkill -f -- "--user-data-dir=${W}/tmp/slack-signin\." 2>/dev/null; [ -n "${APP_PID:-}" ] && kill "${APP_PID}" 2>/dev/null; rm -rf "${W}"; }
trap cleanup EXIT
mkdir -p "${W}/home" "${W}/tmp"
export HOME="${W}/home" TMPDIR="${W}/tmp"
LOG="${HOME}/.slack-open-url.log"
pass=0; fail=0
ok() { pass=$((pass + 1)); echo "  ok   $1"; }
no() { fail=$((fail + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
check() { if eval "$2"; then ok "$1"; else no "$1" "${3:-}"; fi; }
wait_for() { local i; for i in $(seq 1 50); do eval "$1" && return 0; sleep 0.1; done; return 1; }

cat > "${W}/browser" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "${FAKE_ARGS:-/dev/null}"
sleep "${FAKE_STAY:-0}"
SH
chmod 755 "${W}/browser"
export SLACK_BROWSER_BIN="${W}/browser"

STATE="st4te$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
SIGNIN="https://slack.com/signin?redir=%2Fapp-redir%3Fstate%3D${STATE}"
WORKSPACE="https://office.slack.com/sso/saml/start?redir=${STATE}"

echo "signin-browser"
FAKE_ARGS="${W}/args1" sh "${OPEN}" "${SIGNIN}"; rc=$?
wait_for "grep -q 'closed sign-in window=' '${LOG}'"
check "Slack's sign-in opens, and the browser is given the whole address" \
  "[ $rc = 0 ] && [ \"\$(tail -n 1 '${W}/args1')\" = '${SIGNIN}' ]" "rc=$rc $(cat "${W}/args1" 2>/dev/null)"
check "no sandbox (the container is), no keyring, its own profile" \
  "grep -qx -- '--no-sandbox' '${W}/args1' && grep -qx -- '--password-store=basic' '${W}/args1' && grep -q -- '--user-data-dir=${W}/tmp/slack-signin\.' '${W}/args1'"
check "the log names host and path, never the query" \
  "grep -q ' opened sign-in https://slack.com/signin window=' '${LOG}' && ! grep -q -e '${STATE}' -e '?' '${LOG}'" "$(cat "${LOG}")"
check "the throwaway profile is gone when the window closes" "[ -z \"\$(ls '${W}/tmp' | grep '^slack-signin\.')\" ]"
: > "${W}/args2"; FAKE_ARGS="${W}/args2" sh "${OPEN}" "${WORKSPACE}"
wait_for "[ -s '${W}/args2' ]"
check "a workspace's own address (<name>.slack.com) opens" "[ \"\$(tail -n 1 '${W}/args2')\" = '${WORKSPACE}' ]"
for u in "https://evil.example/phish" "https://slack.com.evil.example/signin" "https://evilslack.com/signin"; do
  : > "${W}/args3"; FAKE_ARGS="${W}/args3" sh "${OPEN}" "$u"; rc=$?
  sleep 0.3
  check "not opened (logged by host only): ${u}" "[ $rc = 0 ] && [ ! -s '${W}/args3' ]"
done
for u in "http://slack.com/signin" "https://evil.example\\@slack.com/signin" "javascript:alert(1)"; do
  : > "${W}/args4"; FAKE_ARGS="${W}/args4" sh "${OPEN}" "$u"; rc=$?
  check "refused (2): ${u}" "[ $rc = 2 ] && [ ! -s '${W}/args4' ]" "rc=$rc"
done

echo "open-link"
cat > "${W}/app" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "${FAKE_APP_ARGS:-/dev/null}"
[ -n "${FAKE_APP_STAY:-}" ] && sleep "${FAKE_APP_STAY}"
exit 0
SH
chmod 755 "${W}/app"
export SLACK_APP_BIN="${W}/app"
ANSWER="slack://T0000001/magic-login/c0de${STATE}"
FAKE_APP_ARGS="${W}/appargs" sh "${LINK}" "${ANSWER}"; rc=$?
check "an answer with Slack not running is dropped, and said" \
  "[ $rc = 1 ] && [ ! -s '${W}/appargs' ] && grep -q 'dropped sign-in answer slack://T0000001/magic-login: ' '${LOG}'" "rc=$rc"
# a helper left behind (--type=) is not a running Slack
( exec -a "${W}/app --type=zygote" sleep 20 ) & HELPER_PID=$!
sleep 0.3
: > "${W}/appargs"; FAKE_APP_ARGS="${W}/appargs" sh "${LINK}" "${ANSWER}"; rc=$?
check "a helper (--type=) is not a running Slack: still dropped" "[ $rc = 1 ] && [ ! -s '${W}/appargs' ]" "rc=$rc"
kill "${HELPER_PID}" 2>/dev/null
# a running Slack: a process whose command line starts with the app's path
( exec -a "${W}/app --no-sandbox --disable-gpu" sleep 20 ) & APP_PID=$!
sleep 0.3
FAKE_APP_ARGS="${W}/appargs" sh "${LINK}" "${ANSWER}"; rc=$?
check "to a running Slack it is handed on, with the container's flags" \
  "[ $rc = 0 ] && grep -qx -- '--no-sandbox' '${W}/appargs' && grep -qx -- '${ANSWER}' '${W}/appargs'" "rc=$rc $(cat "${W}/appargs" 2>/dev/null)"
check "the log never holds the sign-in's code" "! grep -q 'c0de' '${LOG}'"
# links of other shapes: no team, an encoded slash, a team in lowercase, a code made of letters only — the
# code never reaches the log
for odd in "slack://magic-login/c0de${STATE}" "slack://T0000001/magic-login%2Fc0de${STATE}" "slack://t0de${STATE}/x" \
           "slack://magic-login/codeofletters"; do
  sh "${LINK}" "${odd}" >/dev/null 2>&1
done
check "a link of another shape logs «…», never its code" \
  "! grep -q -e 'c0de' -e 't0de' -e 'codeofletters' '${LOG}' && [ \"\$(grep -c 'slack://…/…' '${LOG}')\" -ge 3 ] && grep -q 'slack://T0000001/…' '${LOG}'" "$(tail -n 4 "${LOG}")"

echo "${pass} passed, ${fail} failed"
[ "${fail}" = 0 ]
