#!/usr/bin/env bash
# pulse.sh — the office's own 5-minute reminder, inside the agent's container.
#
# WHY IT EXISTS. On 2026-10-09 the owner said: "make sure you two don't stop working until everything
# is perfect (set a reminder or something) … set yourself a reminder every 5 minutes to verify that
# development is progressing as well as possible, fast and efficiently". The reminder cannot live in a
# turn: the turn that was doing exactly this was cut mid-work when bina-ds was recreated at 04:53, and
# the reminder died with it. So the timer lives here — in the container that runs the agent — and it
# keeps ticking whether or not a conversation is open.
#
# WHAT IT DOES, every BINA_DS_PULSE_EVERY seconds (default 300):
#   1. asks the agent API (127.0.0.1, this container's own token) which sessions exist and which are
#      actually RUNNING;
#   2. RE-ARMS every active goal whose session has no turn running and whose `activation` is not
#      `armed` (`POST /v1/sessions/{id}/goal/resume`). Measured 2026-10-09 17:25 UTC on all three active
#      goals, and again 2026-10-10 after a recreate: a goal is `disarmed` after every round, after a
#      restart and after `goal set`; the harness does not continue a disarmed goal, and a message buys
#      ONE turn — only resume re-arms. At the nudge's pace the agent ran 23 rounds in 21 hours; re-armed
#      every minute it ran ~12 an hour. The tick is the pacer (≤ 12 rounds/hour/session), the same
#      loopback door and token, nothing else written;
#   3. if something is running — says so and does nothing else (the office is working);
#   4. if nothing is running for BINA_DS_PULSE_IDLE_TICKS ticks in a row WHILE a session still holds a
#      goal, it nudges that session to carry on (`POST /v1/sessions/{id}/messages`) and says so in the
#      notification centre — the watchdog for a session that re-arming did not move.
#
# IT NEEDS NO NEW DOOR. The token is this container's own (`${DSH_HOME}/api-token`, root-only), the
# API is on loopback, and nothing leaves the container. That is deliberate: the automation that
# observes from outside (n8n `raphaelPulse00001`) can only read `/v1/health` without a token, and
# giving an outside container the agent token is a security decision, not a convenience.
#
# ONE TICK: BINA_DS_PULSE_ONCE=1 bash pulse.sh   — prints the verdict and exits (tests, cron, debugging)
set -uo pipefail

DSH_HOME="${DSH_HOME:-/data/dsh}"
API="${BINA_DS_AGENT_URL:-http://127.0.0.1:3081}"
EVERY="${BINA_DS_PULSE_EVERY:-300}"
# A watchdog, not a pacer: the harness already continues a session that holds an active goal, so
# nudging after two ticks would double-drive it. 20 minutes of NOTHING running while a goal is active
# is a stall, and that is what this waits for.
IDLE_TICKS="${BINA_DS_PULSE_IDLE_TICKS:-4}"
LOG="${BINA_DS_PULSE_LOG:-${DSH_HOME}/pulse.log}"
STATE="${BINA_DS_PULSE_STATE:-${DSH_HOME}/pulse.state}"
NOTIFY="${BINA_DS_NOTIFY_URL:-http://notifications:8977/api/notifications}"
NUDGE="${BINA_DS_PULSE_TEXT:-הדופק של הלשכה: קיבלת מטרה פעילה ואף תור לא רץ — המשך מהמקום שבו עצרת, בלי לשאול.}"
# The hub's list verb prints aligned rows (ref, state, priority, assignee, name); `--json` answers
# nothing usable here (measured 2026-10-09), so the row is read as it is printed.
HUB="${BINA_DS_HUB_CMD:-${DSH_OFFICE_ROOT:-/workspace/office}/bbox project-pln tasks list --as azaria --state unstarted}"
DRY="${BINA_DS_PULSE_DRY:-0}"

# The log is the record; a terminal that is watching gets the line too. Writing both unconditionally
# duplicated every line when the launcher also sent stderr into the same file (measured 2026-10-09).
say() {
  mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true
  printf '%s %s\n' "$(date '+%F %T')" "$*" >> "${LOG}"
  [ -t 2 ] && printf '%s %s\n' "$(date '+%F %T')" "$*" >&2
  return 0
}

token() { cat "${DSH_HOME}/api-token" 2>/dev/null; }

notify() { # level, title, body
  local level="$1" title="$2" body="$3"
  curl -s -o /dev/null --max-time 10 -X POST "${NOTIFY}" -H 'content-type: application/json' \
    -d "$(printf '{"source":"azaria","source_id":"pulse-nudge","level":"%s","title":"%s","body":"%s"}' \
          "${level}" "${title}" "${body}")" 2>/dev/null || true
}

# THE WAKE QUEUE — how an automation outside this container gets work moving again.
#
# An outside app cannot hold this container's agent token (it is root-only here, by the contract), and
# handing it out would make "any container in the office may drive the agent" a design decision nobody
# asked for. So the door is a QUEUE nobody needs a secret to write: the office's notice centre. n8n —
# which already posts notices and already watches the office every five minutes — posts a notice whose
# `source_id` starts with `wake`; THIS timer, which does hold the token, reads it, wakes the session the
# notice names (or the one holding an active goal), and marks the notice read. Every wake is an
# auditable row, and no credential ever crosses a container boundary.
wake_requests() {
  curl -s --max-time 10 "${NOTIFY}?limit=20" 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit
for n in (d.get("notifications") or []):
    sid = str(n.get("source_id") or "")
    if n.get("is_read") or not sid.startswith("wake"):
        continue
    title = (n.get("title") or "").replace("\t", " ")
    body = (n.get("body") or "").replace("\t", " ")
    print("%s\t%s\t%s" % (n.get("id"), title, body))
' 2>/dev/null
}

handle_wake() { # token, fallback-session-ids
  local t="$1" fallback="$2" rows wid wtitle wbody target text
  rows="$(wake_requests)"
  [ -n "${rows}" ] || return 0
  while IFS="$(printf '\t')" read -r wid wtitle wbody; do
    [ -n "${wid}" ] || continue
    target="$(printf '%s %s' "${wtitle}" "${wbody}" | grep -oE 'session-[a-z0-9]{6,}' | head -1)"
    [ -n "${target}" ] || target="$(printf '%s' "${fallback}" | awk '{print $1}')"
    if [ -z "${target}" ]; then
      say "wake request ${wid} has no session to wake (none holds an active goal) — leaving it unread"
      continue
    fi
    text="בקשת השכמה מהלשכה: ${wtitle} ${wbody}"
    if [ "${DRY}" = "1" ]; then say "dry run — would wake ${target} for notice ${wid}: ${wtitle}"; continue; fi
    if curl -s -o /dev/null --max-time 15 -X POST "${API}/v1/sessions/${target}/messages" \
         -H "Authorization: Bearer ${t}" -H 'content-type: application/json' \
         -d "$(python3 -c 'import json,sys;print(json.dumps({"text": sys.argv[1]}))' "${text}")"; then
      curl -s -o /dev/null --max-time 10 -X POST "${NOTIFY}/${wid}/read" 2>/dev/null
      say "woke ${target} for wake request ${wid} (${wtitle})"
    else
      say "could not wake ${target} for wake request ${wid}"
    fi
  done <<EOF
${rows}
EOF
  return 0
}

# A NUDGE IS A MESSAGE; ONLY A RESUME RESTARTS A GOAL — and that is the whole difference between this
# timer working and appearing to work. Measured 2026-10-10: the harness here does NOT continue an
# active goal by itself. One `goal/resume` buys exactly ONE round, after which the goal is
# `active` but `disarmed` again — so three sessions sat with a live goal while this pulse nudged them
# every 20 minutes to no effect, and the office went quiet with everything looking armed.
#
# Order, therefore: RE-ARM first, then nudge. The message is what carries the work (and the next item);
# the resume is what lets a turn happen at all. A cap that ran out is the one block a resume cannot
# lift, so that case clears the goal and sets it again with the same objective and a fresh cap; the
# objective is read back rather than remembered, so a session's own words survive.
ROUNDS="${BINA_DS_PULSE_ROUNDS:-400}"
rearm_goal() { # token, session id
  local t="$1" sid="$2" doc phase obj code
  doc="$(curl -s --max-time 10 -H "Authorization: Bearer ${t}" "${API}/v1/sessions/${sid}/goal" 2>/dev/null)"
  [ -n "${doc}" ] || return 0
  read -r phase activation <<EOF
$(printf '%s' "${doc}" | python3 -c 'import json,sys
try: g=(json.load(sys.stdin).get("goal") or {})
except Exception: g={}
print(g.get("phase") or "-", g.get("activation") or "-")' 2>/dev/null)
EOF
  [ -n "${phase}" ] && [ "${phase}" != "-" ] || return 0
  # ALREADY ARMED IS NOTHING TO DO — and asking anyway is not harmless: `goal/resume` on a goal that
  # is already armed answers 502 ("already active and armed"), and a resume that fails is exactly the
  # signal this function treats as "the cap ran out, clear and re-create". Without this line an armed
  # goal would be destroyed and re-created by its own watchdog.
  if [ "${phase}" = "active" ] && [ "${activation}" = "armed" ]; then
    say "left ${sid} alone — its goal is active and armed"
    return 0
  fi
  if [ "${DRY}" = "1" ]; then say "dry run — would re-arm ${sid} (goal ${phase}/${activation})"; return 0; fi
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST \
          "${API}/v1/sessions/${sid}/goal/resume" -H "Authorization: Bearer ${t}" 2>/dev/null)"
  if [ "${code}" = "200" ]; then
    say "re-armed ${sid} (goal was ${phase})"
    return 0
  fi
  obj="$(printf '%s' "${doc}" | python3 -c 'import json,sys
try: g=(json.load(sys.stdin).get("goal") or {})
except Exception: g={}
print((g.get("objective") or "").replace("\n", " "))' 2>/dev/null)"
  [ -n "${obj}" ] || { say "could not re-arm ${sid} (goal ${phase}) and no objective to restore"; return 0; }
  curl -s -o /dev/null --max-time 15 -X POST "${API}/v1/sessions/${sid}/goal/clear" \
       -H "Authorization: Bearer ${t}" 2>/dev/null
  if curl -s -o /dev/null --max-time 15 -X POST "${API}/v1/sessions/${sid}/goal" \
       -H "Authorization: Bearer ${t}" -H 'content-type: application/json' \
       -d "$(python3 -c 'import json,sys;print(json.dumps({"objective": sys.argv[1], "max_rounds": int(sys.argv[2])}))' "${obj}" "${ROUNDS}")"; then
    say "re-set ${sid} — goal was ${phase}; cleared and re-created with ${ROUNDS} rounds"
    notify warning "הדופק של הלשכה: מטרה שחוסלה" "מטרה במצב ${phase} לא ניתנה לחידוש, ולכן נוקתה והוגדרה מחדש עם ${ROUNDS} סבבים — אותה מטרה, מכסה חדשה."
  else
    say "could not re-set ${sid} (goal was ${phase})"
  fi
}

# One tick: prints a verdict line and leaves the idle counter in ${STATE}.
tick() {
  local t sessions running active_goal_ids idle
  t="$(token)"
  if [ -z "${t}" ]; then say "no agent token at ${DSH_HOME}/api-token — cannot pulse"; return 1; fi
  sessions="$(curl -s --max-time 15 -H "Authorization: Bearer ${t}" "${API}/v1/sessions" 2>/dev/null)"
  if [ -z "${sessions}" ]; then say "the agent API did not answer on ${API}"; return 1; fi
  read -r running active_goal_ids stalled_goal_spec <<<"$(printf '%s' "${sessions}" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print("0  -"); raise SystemExit
items = d.get("sessions") if isinstance(d, dict) else d
items = items or []
running = sum(1 for s in items if s.get("running"))
def phase(s):
    return (s.get("goal") or {}).get("phase") or ""
active = " ".join(s.get("id","") for s in items if phase(s) == "active")
# A goal that EXISTS but is not active — `blocked` (the harness stopped continuing it: its round limit,
# a blocker it reported) or `paused` — used to be invisible here, and that is how the office went SILENT:
# the session stopped being continued, no scan had anything to report, and the next turn only ever
# started because the owner wrote (measured 2026-10-09, after 12/12 rounds were spent). So it is its own
# state, named, and it wakes the session the same way an active goal does.
stalled = ",".join(s.get("id","") + "=" + phase(s) for s in items if phase(s) not in ("", "active"))
print(f"{running} {active or chr(45)} {stalled or chr(45)}")
')"
  # `-` is the shell-level "none" (an empty field cannot be read back from a three-field line)
  [ "${active_goal_ids}" = "-" ] && active_goal_ids=""
  [ "${stalled_goal_spec}" = "-" ] && stalled_goal_spec=""
  local stalled_goal_ids="${stalled_goal_spec//=/ }"
  stalled_goal_ids="${stalled_goal_ids//,/ }"
  handle_wake "${t}" "${active_goal_ids} ${stalled_goal_ids}"
  # RE-ARM EVERY TICK, NOT ONLY WHEN THE OFFICE LOOKS IDLE. Measured 2026-10-10: the harness here does
  # not continue a goal by itself — one `goal/resume` buys exactly one round, then the goal is
  # `active` but `disarmed` again — so a session that finishes a round sits parked until something
  # resumes it. Waiting for four idle ticks means up to twenty minutes of a session doing nothing
  # between rounds; this asks every five minutes, and rearm_goal leaves an already-armed goal alone.
  local disarmed_id
  for disarmed_id in $(printf '%s' "${sessions}" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: raise SystemExit
items = (d.get("sessions") if isinstance(d, dict) else d) or []
for s in items:
    g = s.get("goal") or {}
    if g.get("phase") == "active" and (g.get("activation") or "") != "armed":
        print(s.get("id",""))
' 2>/dev/null); do
    rearm_goal "${t}" "${disarmed_id}"
  done
  idle="$(cat "${STATE}" 2>/dev/null || echo 0)"
  if [ "${running:-0}" -gt 0 ]; then
    echo 0 > "${STATE}"
    say "working: ${running} conversation(s) running — nothing to do"
    return 0
  fi
  idle=$(( idle + 1 )); echo "${idle}" > "${STATE}"
  if [ -z "${active_goal_ids}${stalled_goal_ids}" ]; then
    say "idle ${idle} tick(s), no goal — waiting"
    return 0
  fi
  if [ "${idle}" -lt "${IDLE_TICKS}" ]; then
    say "idle ${idle}/${IDLE_TICKS} tick(s) but a goal is active — giving it one more tick before nudging"
    return 0
  fi
  # A nudge that carries WORK, not just "carry on": the office's own hub is asked what is next, so the
  # continuation starts on an item rather than on a shrug. Best-effort — a hub that is down (measured:
  # project-pln restarts under other writers) still gets a nudge, just a generic one.
  local next_item=""
  next_item="$(cd "${DSH_OFFICE_ROOT:-/workspace/office}" 2>/dev/null && ${HUB} 2>/dev/null \
    | awk 'NF>4 && $1 ~ /^[A-Z][A-Z0-9]*-[0-9]+$/ { ref=$1; $1=""; $2=""; $3=""; $4=""; sub(/^[ \t]+/, ""); printf "%s — %s", ref, $0; exit }')"
  local id
  for id in ${active_goal_ids} ${stalled_goal_ids}; do
    # A stalled goal gets its own sentence, because the session cannot see this from the inside: the
    # harness stopped continuing it, so nothing in its own turn ever happens again. It is told the
    # phase, and told what to do about it (`bbox agent goal <id> resume|edit`).
    local stalled_phase="" p
    for p in ${stalled_goal_spec//,/ }; do [ "${p%%=*}" = "${id}" ] && stalled_phase="${p#*=}"; done
    if [ -n "${stalled_phase}" ]; then
      text="הדופק של הלשכה: המטרה שלך במצב ${stalled_phase} — ההרנס הפסיק להמשיך אותך, ולכן השיחה עמדה. חדש/י אותה (bbox agent goal ${id} resume, ואם נגמרה המכסה גם edit עם max_goal_rounds) וחזור/י לעבודה מפס ההתקדמות שבלוח."
      [ -n "${next_item}" ] && text="${text} הפריט הבא בתור בלוח: ${next_item}"
    else
      text="${NUDGE}"
      [ -n "${next_item}" ] && text="${NUDGE} הפריט הבא בתור בלוח: ${next_item}"
    fi
    if [ "${DRY}" = "1" ]; then
      say "dry run — would nudge ${id} with: ${text}"
      continue
    fi
    # RE-ARM, THEN NUDGE (see rearm_goal above): a message into a disarmed goal starts nothing.
    rearm_goal "${t}" "${id}"
    if curl -s -o /dev/null --max-time 15 -X POST "${API}/v1/sessions/${id}/messages" \
         -H "Authorization: Bearer ${t}" -H 'content-type: application/json' \
         -d "$(python3 -c 'import json,sys;print(json.dumps({"text": sys.argv[1]}))' "${text}")"; then
      if [ -n "${stalled_phase}" ]; then
        say "nudged ${id} — its goal was ${stalled_phase} and nothing had run for ${idle} tick(s)"
        notify warning "הדופק של הלשכה: מטרה שקערה" "הדופק מצא שיחה שהמטרה שלה במצב ${stalled_phase} (ההרנס הפסיק להמשיך אותה) ולא רץ בה דבר ${idle} דקות — השיחה הוערה.${next_item:+ הפריט הבא: ${next_item}}"
      else
        say "nudged ${id} to continue (nothing had run for ${idle} tick(s) while its goal is active)${next_item:+ — next item: ${next_item}}"
        notify info "הדופק של הלשכה: חידשתי עבודה" "הדופק לא ראה תור רץ בעוד שיחה עם מטרה פעילה, ושלח לה הוראה להמשיך."
      fi
    else
      say "could not nudge ${id}"
    fi
  done
  echo 0 > "${STATE}"
  return 0
}

if [ "${BINA_DS_PULSE_ONCE:-0}" = "1" ]; then tick; exit $?; fi

say "pulse starting: every ${EVERY}s, nudge after ${IDLE_TICKS} idle tick(s)"
while :; do
  tick || true
  sleep "${EVERY}"
done
