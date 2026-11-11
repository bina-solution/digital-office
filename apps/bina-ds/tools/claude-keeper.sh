#!/usr/bin/env bash
# claude-keeper — one pass that answers ONE question: is the owner's Claude Code session ("the King
# session", in the office's own browser42) standing still and waiting for a human?
#
# Why this exists: Claude Code stops for reasons that are all questions — "sign in again to verify
# your device", a permission prompt, "shall I continue?" — and every one of them is a human-shaped
# pause in a session that has full authority to continue. The owner's standing order (2026-10-22) is
# that this must never block again. The KEEPER is the detector; the AGENT (עזריה המלך, its own agent
# session, preset `azaria-king`) is the hand that clicks. They are deliberately separate: this script
# holds no model and makes no decisions, and the agent never has to be awake to notice.
#
# It is called by pulse.sh on its own tick (apps/bina-ds/pulse.sh). It only LOOKS: `inspect` and
# `status` through browser42's own task client. Clicking and typing belong to the agent, which is
# woken by the notice this script posts into the office's notice centre (source_id `wake …`, the
# queue pulse.sh already drains — no token crosses a container boundary).
#
# State file: $DSH_HOME/claude-king.json
#   { "agent_session": "session-…",   # the azaria-king session to wake when blocked
#     "tab_slug": "king-session",      # browser42 task slug holding the King tab
#     "url": "https://claude.ai/code/…" }
# Absent, or no agent_session in it → this script does nothing at all (the office is not opted in).
#
# Output: one line per pass on stdout (pulse logs it). Exit 0 always — a keeper that fails the timer
# would take the pulse down with it, and the pulse has other work.
set -uo pipefail

STATE="${DSH_HOME:-/data/dsh}/claude-king.json"
NOTIFY="${BINA_DS_NOTIFY_URL:-http://notifications:8977/api/notifications}"
DEDUPE="${DSH_HOME:-/data/dsh}/claude-king.last"
COOLDOWN="${BINA_DS_KEEPER_COOLDOWN:-180}"   # seconds between wake requests (a blocked session stays blocked)
say() { printf '[claude-keeper] %s\n' "$*"; }

[ -f "${STATE}" ] || { say "no ${STATE} — the King session is not configured; nothing to do"; exit 0; }
read -r AGENT TABS_ULG URL < <(python3 - "${STATE}" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(d.get("agent_session") or "-", d.get("tab_slug") or "king-session", d.get("url") or "-")
PY
) || true
AGENT="${AGENT:--}"; TABS_ULG="${TABS_ULG:-king-session}"; URL="${URL:--}"
# THE TAB IS FOUND, NOT REMEMBERED. A browser42 task is killed by its own clocks (30 min total, and
# `stalled` after 5 min without activity) and a terminal task KEEPS ITS SLUG, so a keeper bound to one
# remembered slug watches a corpse: measured 2026-10-22 — it kept probing `king-session` long after the
# runner had ended it, and the live tab the agent had just opened under a new slug was never looked at.
# So: the newest `king-*` task on disk is the one to look at, and no `king-*` at all is a real answer.
newest_king() {
  local dir newest="" newest_t=0
  for dir in "${OFFICE_TASKS}"/*king-*/; do
    [ -d "${dir}" ] || continue
    local t; t="$(stat -c %Y "${dir}" 2>/dev/null || echo 0)"
    if [ "${t}" -gt "${newest_t}" ]; then newest_t="${t}"; newest="${dir%/}"; fi
  done
  [ -n "${newest}" ] && basename "${newest}"
}
OFFICE_TASKS="${BINA_DS_B42_TASKS:-${DSH_OFFICE_ROOT:-/workspace/office}/data/browser42/tasks}"
: <<'NOTE'
The state file's tab_slug is only a fallback: the agent names every pass's task `king-<HHMM>`, so the
slug is never reused and `duplicate_slug` never fires.
NOTE
RESOLVED_TAB="$(newest_king)"
[ -n "${RESOLVED_TAB}" ] && TABS_ULG="${RESOLVED_TAB}"
[ "${AGENT}" != "-" ] || { say "no agent_session in ${STATE} — nothing to wake"; exit 0; }

# One browser42 task client, reached the way every other caller reaches it (never CDP directly).
RUNNER="$(docker ps --filter name=browser42-task-runner --format '{{.Names}}' 2>/dev/null | head -1)"
[ -n "${RUNNER}" ] || { say "browser42-task-runner is not running — cannot look (not an error)"; exit 0; }
task_client() { docker exec -i "${RUNNER}" python3 /task-client.py "$@" 2>/dev/null; }

STATUS="$(task_client status "${TABS_ULG}")"
case "${STATUS}" in
  *'"task_not_found"'*)
    # The King tab is not open yet. Opening it is the AGENT's first step, not this script's.
    say "no browser42 task '${TABS_ULG}' yet — the agent opens the tab on its next pass"
    exit 0 ;;
  "") say "browser42 did not answer — not looking this tick"; exit 0 ;;
esac
case "${STATUS}" in
  # A task the watchdog marked stalled (no activity for five minutes) or a rejected one holds the
  # slug, so it must be CLOSED before a fresh start: `task start` refuses a slug that already exists.
  # That is housekeeping, not control of the page — the agent still does the opening.
  *'"state": "stalled"'*|*'"state": "rejected"'*)
    say "task '${TABS_ULG}' is stalled or rejected — the agent closes it and opens a fresh one" ;;
esac

# WHAT A BLOCKED CLAUDE LOOKS LIKE, measured on claude.ai/code (2026-10-22):
#   * an alertdialog whose text is "Sign in again to verify your device"      → a device re-check
#   * a visible button named Allow / Approve / Yes / Continue / Not now       → a prompt waiting
#   * the "Blocked … Asked a question" rows on claude.ai/code                 → a session asking
# `inspect` returns only what is on screen and only for the fragment it is given, so each pattern is
# asked for by name; a pattern that finds nothing costs one round trip. THREE probes, not five: a pass
# that takes minutes is a pass that misses the moment (measured 2026-10-22: five probes ran 2.5 min
# behind a session that was itself using the browser).
BLOCKED=""
for probe in "Sign in again" "Allow" "Continue" "Approve" "DNS"; do
  OUT="$(task_client inspect "${TABS_ULG}" "${probe}")"
  case "${OUT}" in
    *'"alertdialog"'*|*'"role": "button"'*) BLOCKED="${probe}"; break ;;
  esac
done

if [ -z "${BLOCKED}" ]; then
  say "King is not showing a prompt — leaving it alone"
  exit 0
fi

# A blocked session STAYS blocked; do not post the same wake request every tick.
NOW="$(date +%s)"
if [ -f "${DEDUPE}" ]; then
  LAST="$(cat "${DEDUPE}" 2>/dev/null || echo 0)"
  case "${LAST}" in ''|*[!0-9]*) LAST=0 ;; esac
  if [ $((NOW - LAST)) -lt "${COOLDOWN}" ]; then
    say "blocked on '${BLOCKED}' but the last wake request was $((NOW - LAST))s ago — waiting"
    exit 0
  fi
fi

BODY="הסשן ${AGENT} מתבקש לאשר/להמשיך את סשן ה-King. סימן: ${BLOCKED}. כתובת: ${URL}"
curl -s -o /dev/null --max-time 10 -X POST "${NOTIFY}" -H 'content-type: application/json' \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"source":"claude-keeper","source_id":"wake king","level":"warn","title":"King ממתין לאישור: "+sys.argv[1],"body":sys.argv[2]}))' "${BLOCKED}" "${BODY}")" \
  && printf '%s\n' "${NOW}" > "${DEDUPE}" \
  && say "posted a wake request for ${AGENT} (blocked on '${BLOCKED}')" \
  || say "could not post the wake request to ${NOTIFY}"
exit 0
