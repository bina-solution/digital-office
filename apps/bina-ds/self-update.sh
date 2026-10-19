#!/usr/bin/env bash
# self-update.sh — apply a change to bina-ds from OUTSIDE bina-ds, health-gated, with rollback.
#
# WHY. bina-ds runs the office agent AND the agent's shell. A compose command issued in that shell
# that recreates bina-ds stops the very container the command runs in: compose stops the old
# container first, the compose client dies with it, and the replacement is left in `Created`, never
# started. Measured 2026-09-29 05:03: an agent applied its own sidebar change with
# `./scripts/dc up -d --build bina-ds`; the harness then stayed down for 8 hours and every other
# agent's turn died with it. Developing the office from inside the office is a feature, so the
# restart has to be done by something that survives it.
#
# HOW. scripts/lib.sh (compose_self_guard) notices, inside the harness container, a compose command that would
# recreate or restart bina-ds. It builds as usual (so a build error still reaches the caller), then
# calls `launch` here instead of recreating bina-ds itself:
#
#   launch <up|create|restart> [flags…]   inside bina-ds: start a one-shot helper and return at once
#   apply  <prev-image> <verb> [flags…]   inside the helper: wait, recreate, health gate, roll back
#
# The helper is a separate container on the same engine, so it outlives the container it replaces.
# It runs the image bina-ds is running NOW — the one known to work — never the new build, so a
# broken build cannot break its own rollback.
#
# RESUMING CONVERSATIONS. Two changes after 2026-10-09, when an update applied on the MAX_WAIT
# deadline cut a live turn and hours of work stopped there: (1) the wait is for a real free moment and
# not for a clock — past MAX_WAIT the helper says it is waiting and keeps waiting, with ONE bound
# (BINA_DS_SELF_UPDATE_FORCE_AFTER, 10800 by the office's decision) so a goal that never idles cannot
# hold an update for ever; (2) whoever WAS mid-turn is snapshotted before the recreate and told to
# carry on (`bbox agent send`) once the new image is healthy — which is what makes that bound cost a
# turn's tail and not its work. The owner no longer has to reopen anything.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../.." && pwd)"
SERVICE=bina-ds
HELPER=bina-ds-self-update
LOG_DIR="${REPO}/data/bina-ds"
LOG="${LOG_DIR}/self-update.log"
DELAY="${BINA_DS_SELF_UPDATE_DELAY:-20}"
# The image's own healthcheck: start_period 40s + 5 retries x 30s. Past that, Docker has decided.
HEALTH_TIMEOUT="${BINA_DS_SELF_UPDATE_HEALTH_TIMEOUT:-300}"
# A restart ends every conversation that is working at that moment, not only the one that asked for
# it. Measured 2026-09-29 15:24: one agent's self-update was about to land while three others were
# mid-task, one of them halfway through rotating a database password. So the update waits until the
# office is QUIET — which means, exactly, what busy_reason asks below: no agent command running in
# the harness AND no conversation running a turn. Ask it twice and you have the whole rule.
QUIET_S="${BINA_DS_SELF_UPDATE_QUIET:-120}"   # only the FALLBACK's window now — see busy_reason
MAX_WAIT="${BINA_DS_SELF_UPDATE_MAX_WAIT:-3600}"
# THE BOUND, AND IT IS THREE HOURS BY DECISION (2026-10-09, the coordinator's §1 — DGO-514). The
# predicate above is honest but it is not a promise that a free moment arrives: measured over 115
# turns of a live goal session, the gap between one round and the next is 0.0–1.2 s (median 0.1 s), so
# an office whose goals keep producing rounds can hold an update for a day. Past this bound the update
# LANDS, and `resume_sessions` is what brings the conversations back — the half that exists precisely
# so the bound costs a turn's tail instead of its work. Between rounds nothing is cut; at the bound
# the clock decides, loudly, and the log says so. 0 = never (a deployment that wants to wait).
FORCE_AFTER="${BINA_DS_SELF_UPDATE_FORCE_AFTER:-10800}"

log() { mkdir -p "${LOG_DIR}" 2>/dev/null || true; printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "${LOG}" >&2; }
die() { log "error: $*"; exit 1; }
# `env -u TZ`: compose interpolates `${TZ:-…}` from the CALLER's environment before .env, and both
# callers here run inside a container whose TZ is whatever the PREVIOUS generation was started with.
# Measured 2026-09-30: bina-ds had been recreated from inside itself once with TZ=UTC in the shell,
# and every recreate since inherited it — the agent's clock, its commits and this log sat three
# hours off the office although the compose default is Asia/Jerusalem. Only .env may set it.
dc()  { env -u TZ "${REPO}/scripts/dc" "$@"; }

# Compose stamps its own lines in UTC (`level=warning time="…Z"`) while log() writes office-local
# time, so a single self-update left a file a reader could not order: 15:21 next to 20:19, three
# hours apart, in the same run. Every compose line now goes through log() — one clock, one format.
# The exit code survives the round trip, because the caller's rollback decision depends on it.
dc_logged() {
  local out rc=0 line
  out="$(mktemp)"
  dc "$@" >"${out}" 2>&1 || rc=$?
  while IFS= read -r line; do log "${line}"; done <"${out}"
  rm -f "${out}"
  return "${rc}"
}

# The live bina-ds container (compose knows the project; the name carries DEPLOYMENT_NAME).
current_container() { dc ps -a -q "${SERVICE}" 2>/dev/null | head -n1; }

# One upsert-style notification (same source_id → the same row is updated, never piled up).
notify() {
  local level="$1" title="$2" body="$3"
  command -v curl >/dev/null 2>&1 || return 0
  python3 - "$level" "$title" "$body" <<'PY' | curl -fsS -m 10 -H 'Content-Type: application/json' \
      --data-binary @- http://notifications:8977/api/notifications >/dev/null 2>&1 || true
import json, sys
level, title, body = sys.argv[1:4]
print(json.dumps({"source": "bina-ds", "source_id": "self-update", "level": level,
                  "title": title, "body": body, "link": "/#/m/bina"}, ensure_ascii=False))
PY
}

wait_healthy() {   # → 0 healthy, 1 not healthy within HEALTH_TIMEOUT
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT )) cid st waited=0
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    cid="$(current_container)"
    if [ -n "${cid}" ]; then
      st="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "${cid}" 2>/dev/null || true)"
      case "${st}" in
        "running healthy") return 0 ;;
        # `restarting` right after an update means the new process is crash-looping.
        *unhealthy*|exited*|dead*|restarting*) log "bina-ds is '${st}'"; return 1 ;;
      esac
    fi
    sleep 5; waited=$(( waited + 5 ))
    # A silent five minutes reads as a hang; say what Docker sees once a minute.
    if [ $(( waited % 60 )) -eq 0 ]; then log "still waiting for bina-ds: ${st:-no container yet} (${waited}s)"; fi
  done
  log "bina-ds not healthy after ${HEALTH_TIMEOUT}s (last: ${st:-no container})"
  return 1
}

# The last lines the harness wrote — what a failed health gate actually saw. Measured 2026-09-30
# 13:52: the new image died on a loader error, the rollback then failed on a port, and for five
# minutes this log said only "not healthy"; the reason was in `docker logs` the whole time.
harness_tail() {
  local cid; cid="$(current_container)"
  [ -n "${cid}" ] || { echo "(no bina-ds container)"; return 0; }
  docker logs --tail 20 "${cid}" 2>&1 | cut -c1-240
}
log_harness_tail() { log "last lines from the harness:"; harness_tail | sed 's/^/    /' | tee -a "${LOG}" >&2; }
tail_for_notice() { harness_tail | tail -n 8 | cut -c1-140; }

# Host ports the new definition publishes that the running bina-ds does not already hold — each with
# what holds it now — or nothing when they are all free. Compose stops the old container BEFORE it
# starts the new one: a port that is taken then fails the start, fails the rollback the same way
# (same definition), and leaves the office down until a person frees it. Measured 2026-09-30 13:43:
# 127.0.0.1:3081 was held by a host-side forwarder (`python3 /tmp/fwd3081.py`); bina-ds was down 41
# minutes. So the check runs while the old container is still up. The probe binds the port in the
# ENGINE's network namespace (`--network host`) and names the holder from the engine's /proc
# (`--pid host`): a holder that is a container shows up in `docker ps` and is named as such.
#   $1 engine socket path (see nothing_to_apply)   $2 the running bina-ds   $3 the image to probe with
busy_ports() {
  local sock="$1" cid="$2" image="$3" want have p holder owner found=""
  want="$(BBOX_DOCKER_SOCK="${sock}" COMPOSE_GUARD_OFF=1 dc config --format json "${SERVICE}" 2>/dev/null \
    | python3 -c '
import json, sys
for p in json.load(sys.stdin)["services"][sys.argv[1]].get("ports") or []:
    pub = str(p.get("published") or "")
    if pub.isdigit(): print("%s:%s" % (p.get("host_ip") or "0.0.0.0", pub))
' "${SERVICE}" 2>/dev/null)" || want=""
  [ -n "${want}" ] || return 0
  have="$(docker inspect -f '{{range $k, $v := .HostConfig.PortBindings}}{{range $v}}{{or .HostIp "0.0.0.0"}}:{{.HostPort}} {{end}}{{end}}' "${cid}" 2>/dev/null || true)"
  for p in ${want}; do
    case " ${have} " in *" ${p} "*) continue ;; esac   # freed the moment the old container stops
    # SYS_PTRACE + apparmor=unconfined: naming the holder means reading a HOST process's /proc fd
    # links, and the docker-default AppArmor profile confines ptrace-read to peers under the same
    # profile (tested 2026-09-30: with the capability alone the pid stays unreadable). No new trust
    # is granted — whoever runs this already holds the engine socket, i.e. root on the engine.
    holder="$(docker run --rm -i --network host --pid host --cap-add SYS_PTRACE --security-opt apparmor=unconfined \
                --entrypoint python3 "${image}" - "${p}" <<'PY' 2>/dev/null || true
import os, socket, sys
ip, port = sys.argv[1].rsplit(":", 1); port = int(port)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # TIME_WAIT is not a holder
try:
    s.bind((ip, port)); sys.exit(0)                                            # free: print nothing
except OSError:
    pass
inodes = set()
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try: rows = open(f).read().splitlines()[1:]
    except OSError: continue
    for r in rows:
        c = r.split()
        if c[3] == "0A" and int(c[1].rsplit(":", 1)[1], 16) == port: inodes.add("socket:[%s]" % c[9])
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        for fd in os.listdir("/proc/%s/fd" % pid):
            try:
                if os.readlink("/proc/%s/fd/%s" % (pid, fd)) in inodes:
                    cmd = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                    print("pid %s (%s)" % (pid, cmd[:100])); sys.exit(0)
            except OSError: pass
    except OSError: pass
print("a process on the engine (pid not readable from here)")
PY
)"
    [ -n "${holder}" ] || continue
    owner="$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -F ":${p##*:}->" | cut -d' ' -f1 | head -n1 || true)"
    found="${found}${found:+; }${p} held by ${holder}${owner:+ = container ${owner}}"
  done
  [ -n "${found}" ] && echo "${found}"
  return 0
}

# IS AN AGENT COMMAND RUNNING? A process running UNDER THE HARNESS — the harness's own subtree — and
# not "any process in the container". The container also runs daemons, and they are not work: the
# office pulse (`bash apps/bina-ds/pulse.sh`, `setsid`-detached from the entrypoint so it belongs to
# the init, plus the `sleep 300` it sits in) is there every second of the day. Measured 2026-10-09:
# those two loops alone are a permanent floor of FOUR processes, so the older "every process that is
# not node" count could never reach zero, `wait_quiet` could never return early, and every
# self-update sat for ever while the log blamed "13 agent command(s) running" for commands nobody was
# running. What a turn spawns is under the harness and still counts (node reports its comm here as
# `MainThread`, which is why both names are the roots); a daemon detached from the entrypoint does
# not — and neither does a `nohup … &` an agent left behind, which is right: it is not a turn.
agent_commands() {   # $1 container id → how many processes are running under the harness
  docker top "$1" -eo pid,ppid,comm 2>/dev/null | awk '
    NR > 1 { pid = $1; pp[pid] = $2; cm[pid] = $3 }
    END {
      for (p in cm) if (cm[p] == "node" || cm[p] == "MainThread") under[p] = 1
      for (pass = 0; pass < 8; pass++) {          # children of children … a few passes is the tree
        moved = 0
        for (p in cm) if (!under[p] && under[pp[p]]) { under[p] = 1; moved = 1 }
        if (!moved) break
      }
      for (p in cm) if (under[p] && cm[p] != "node" && cm[p] != "MainThread") c++
      print c + 0
    }'
}

# THE ADDRESS OF THE CONTAINER'S OWN AGENT API, as seen from OUTSIDE it. This helper is a different
# container on the same network, so the container's `127.0.0.1` is ITS OWN loopback and nothing
# listens there: measured 2026-10-09, the restart landed and every resumed conversation answered
# `agent: provider unreachable at http://127.0.0.1:3081 ([Errno 111] Connection refused)` — the four
# conversations that were mid-turn were found and not one of them came back. The service name on the
# shared network, plus the adapter port the container declares.
agent_api_url() {   # $1 container id
  local port
  port="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null \
    | sed -n 's/^BINA_DS_ADAPTER_PORT=//p' | head -n1)"
  printf 'http://%s:%s' "${SERVICE}" "${port:-3081}"
}

# IS A TURN RUNNING RIGHT NOW? That, and not "did anything write lately", is the question: a recreate
# between two turns interrupts nothing in flight, a recreate inside a turn throws the turn away. The
# answer is `running` on the container's own `/v1/sessions` — the field apps/bina-ds/pulse.sh already
# reads — and this helper asks it from outside the container it is about to replace: the same token
# the container mints into its own volume (mounted read-only here), over the network they share.
# Deliberately NOT the harness's own `session/list` (`?fresh=1`, its most expensive call): the adapter
# caches that and refreshes every 20 s, which is plenty for "is a turn running".
#
# The size of the free moment, measured 2026-10-09 over 115 turns of a live goal session: the gap
# between one round's turn and the next is 0.0–1.2 s, median 0.1 s. So a goal that keeps producing
# rounds reads `running` on nearly every sample — that is the truth, not a bug in this predicate —
# and the deliberate override (BINA_DS_SELF_UPDATE_FORCE_AFTER) remains the only way to land an
# update through one; `resume_sessions` is what brings those turns back.
turns_running() {   # $1 container id → the number of conversations running a turn, or a failed status
  local cid="$1" t json url="${BINA_DS_SELF_UPDATE_API_URL:-}"
  t="$(cat "${API_TOKEN_FILE:-/data/dsh/api-token}" 2>/dev/null || true)"
  [ -n "${t}" ] || return 1
  [ -n "${url}" ] || url="$(agent_api_url "${cid}")"
  json="$(curl -fsS -m 15 -H "Authorization: Bearer ${t}" "${url}/v1/sessions" 2>/dev/null)" || return 1
  [ -n "${json}" ] || return 1
  printf '%s' "${json}" | python3 -c '
import json, sys
d = json.load(sys.stdin)
items = d.get("sessions") if isinstance(d, dict) else d
print(sum(1 for s in (items or []) if s.get("running")))
'
}

# Prints why the office is busy, or nothing when it is quiet. Both signals are "right now", and each
# misses nothing the other catches: a command in flight, a turn in flight.
busy_reason() {
  local cid="$1" n turns
  n="$(agent_commands "${cid}")"
  if [ "${n:-0}" -gt 0 ]; then echo "${n} agent command(s) running"; return 0; fi
  if turns="$(turns_running "${cid}")"; then
    if [ "${turns:-0}" -gt 0 ]; then echo "${turns} conversation(s) running"; fi
    return 0
  fi
  # The agent API did not answer (no token, adapter down, network): rather than call an office we
  # cannot see "quiet", use the signal this file used before — silence in the conversation logs —
  # and SAY that this is what the answer is based on. It is a worse answer, and it is labelled.
  if [ -d /data/dsh/sessions ] && [ -n "$(find /data/dsh/sessions -name 'session.v3.jsonl.zstd' \
        -newermt "${QUIET_S} seconds ago" -print -quit 2>/dev/null)" ]; then
    echo "the agent API did not answer; a conversation wrote in the last ${QUIET_S}s"
  fi
}

# WHO WAS WORKING, snapshotted BEFORE the container goes: a session log written in the last few
# seconds belongs to a conversation that is mid-turn. After the new image is healthy these are told to
# carry on by themselves — the half this file used to leave to a person, and the reason an update can
# no longer cost hours of work (measured 2026-10-09: one applied mid-turn and the work stopped there).
#
# A RESTART ALSO DISARMS EVERY GOAL, and nothing puts that back by itself: the goal service keeps the
# continuation authority ("activation") in the PROCESS — `agent/created` sets it to `disarmed` and
# only an explicit `resume` arms it again (apps/bina-ds/harness's own goal service, read 2026-10-09).
# A conversation whose goal was armed therefore comes back able to do ONE turn and then sits still,
# which is the office going quiet by another route — so the resume sentence names the command.
#
# IT IS SENT OVER THE NETWORK, not over loopback: `bbox agent` in here addresses the container's API
# by `BBOX_AGENT_URL`, which cmd_launch passes (agent_api_url) — the helper's own 127.0.0.1 is its
# own, and without that the send answered "provider unreachable" for every conversation (2026-10-09).
LIVE_WINDOW="${BINA_DS_SELF_UPDATE_LIVE_WINDOW:-180}"

live_sessions() {
  # The DIRECTORY name IS the session id (`session-<uuid>`) and it is passed through untouched.
  # Stripping the prefix — which this did — produced ids the adapter answers `session "…" not found`
  # for: measured 2026-10-09 18:48, after the address was fixed, three sends that REACHED the API and
  # named nobody. A resume that fails on the id is the same silent loss as one that fails on the
  # address, and the full id works for `bbox agent send` and `bbox agent goal … resume` alike.
  find /data/dsh/sessions -name 'session.v3.jsonl.zstd' -newermt "${LIVE_WINDOW} seconds ago" -print 2>/dev/null \
    | awk -F/ '{print $(NF-1)}' | sort -u
}

resume_sessions() {
  local ids="$1" id sent=0 total=0
  if [ -z "${ids}" ]; then log "no conversation was mid-turn; nothing to resume"; return 0; fi
  # WAIT FOR THE API, NOT FOR DOCKER. The container being healthy is Docker's opinion of the
  # healthcheck, and it lands BEFORE the harness starts listening on 3081 — measured 2026-10-09 on the
  # first real recreate: two sends died with `[Errno 111] Connection refused`, and the sessions were
  # only brought back later by the office pulse's wake queue. A resume that fails silently is worse
  # than no resume, because it looks like the conversation was returned. Bounded: if the API never
  # answers, say so and let the wake queue be the backstop.
  local waited=0
  until curl -s -o /dev/null --max-time 5 http://127.0.0.1:3081/v1/health 2>/dev/null; do
    if [ "${waited}" -ge 90 ]; then
      log "the agent API did not answer within 90s — resuming anyway (the pulse's wake queue is the backstop)"
      break
    fi
    sleep 5; waited=$(( waited + 5 ))
  done
  for id in ${ids}; do
    total=$(( total + 1 ))
    if ( cd "${REPO}" && ./bbox agent send "${id}" \
         "העדכון של בינה הוחל והקונטיינר הוחלף בזמן שעבדת — המשך מהנקודה שבה היית, ואל תמתין לאישור. אם הייתה לך מטרה פעילה (goal): ההפעלה מחדש שחררה את ההמשך האוטומטי שלה, וצריך לחמש אותה מחדש — bbox agent goal ${id} resume — ואז להמשיך בלולאה." ) >>"${LOG}" 2>&1; then
      sent=$(( sent + 1 )); log "resumed conversation ${id} after the restart"
    else
      log "could not resume conversation ${id} (bbox agent send failed)"
    fi
  done
  # THE NOTICE SAYS WHAT ACTUALLY HAPPENED. It used to fire on `sent > 0` alone: one resumed
  # conversation out of four reported "the conversations continue on their own", and zero reported
  # nothing at all — a resume that fails quietly is worse than no resume, because it reads as if the
  # work came back (measured 2026-10-09, four sends refused and the owner told otherwise).
  if [ "${sent}" -eq 0 ]; then
    notify error "בינה חזרה, אבל השיחות לא קיבלו הוראה להמשיך" \
      "${total} שיחות היו בעבודה כשהקונטיינר הוחלף ואף אחת מהן לא קיבלה הודעה (bbox agent send נכשל). הן ימשיכו רק כשמישהו יכתוב להן. פרטים: ${LOG#"${REPO}/"}"
  elif [ "${sent}" -lt "${total}" ]; then
    notify warn "בינה חזרה — ${sent} מתוך ${total} שיחות ממשיכות לבד" \
      "השאר לא קיבלו הודעה (bbox agent send נכשל). פרטים: ${LOG#"${REPO}/"}"
  else
    notify info "בינה חזרה — והשיחות ממשיכות לבד" "${sent} שיחות שהיו בעבודה קיבלו הוראה להמשיך מאליהן."
  fi
  return 0
}

# THE RESUMES WAIT FOR THE AGENT API TO LISTEN, and they wait on ITS OWN ADDRESS. Two different waits,
# and each was a real failure: (1) the address — inside a helper container `127.0.0.1` is the
# HELPER's loopback, so every send answered "provider unreachable" (measured 2026-10-09), which is
# why cmd_launch passes BBOX_AGENT_URL; (2) the moment — the container's health check probes the
# HARNESS (a static asset on :3080), while the agent API is a separate process on the adapter port
# and can be seconds behind it, so a send can arrive before anything is listening. Bounded on
# purpose: past API_WAIT the sends are attempted anyway, and whatever fails is reported as failed.
API_WAIT="${BINA_DS_SELF_UPDATE_API_WAIT:-60}"
wait_api_ready() {   # $1 container id → 0 when /v1/health answers on the API's own address
  local url waited=0
  url="${BINA_DS_SELF_UPDATE_API_URL:-$(agent_api_url "$1")}"
  while [ "${waited}" -lt "${API_WAIT}" ]; do
    if curl -fsS -m 5 -o /dev/null "${url}/v1/health" 2>/dev/null; then
      [ "${waited}" -eq 0 ] || log "the agent API answered on ${url} after ${waited}s"
      return 0
    fi
    sleep 2; waited=$(( waited + 2 ))
  done
  log "the agent API did not answer on ${url} within ${API_WAIT}s — sending the resumes anyway"
  return 1
}

wait_quiet() {
  local cid="$1" waited=0 reason said=-600 long_said=-1800
  while reason="$(busy_reason "${cid}")"; [ -n "${reason}" ]; do
    # MAX_WAIT is when the update stops waiting for a QUIET office — it is NOT a licence to kill work
    # that is still running. Measured 2026-10-09 04:53: an update applied on the deadline while a
    # conversation was mid-turn; ten seconds later the container was recreated and the turn died as
    # `{"kind":"interrupted"}` — hours of work stopped there for no reason but the clock. Past
    # MAX_WAIT the update SAYS it is waiting and keeps waiting; the bound that may land it anyway is
    # FORCE_AFTER (10800 = three hours by the office's decision; 0 = never), and what it costs is
    # paid back by resume_sessions.
    if [ "${FORCE_AFTER}" -gt 0 ] && [ "${waited}" -ge "${FORCE_AFTER}" ]; then
      log "office still busy after ${waited}s (${reason}) — FORCE_AFTER=${FORCE_AFTER}s says apply now; the conversations that are mid-turn come back through resume_sessions"
      return 0
    fi
    if [ "${waited}" -ge "${MAX_WAIT}" ] && [ $(( waited - long_said )) -ge 1800 ]; then
      log "office still busy after ${waited}s (${reason}) — waiting for a free moment; if none comes, FORCE_AFTER=${FORCE_AFTER}s lands it (0 would wait for ever)"
      notify warn "עדכון של בינה ממתין לעבודה" "העדכון נבנה ואינו מוחל כל עוד סוכן עובד (${reason}). הוא יוחל בחלון השקט הבא, ואם לא יגיע — עד ${FORCE_AFTER} שניות מההתחלה, והשיחות שעבדו חוזרות מעצמן."
      long_said="${waited}"
    fi
    if [ $(( waited - said )) -ge 600 ] && [ "${waited}" -lt "${MAX_WAIT}" ]; then
      log "waiting for a quiet moment before restarting bina-ds: ${reason}"
      notify info "עדכון של בינה ממתין" "העדכון נבנה ויוחל כשאף סוכן לא עובד (כדי לא לקטוע אף שיחה). כרגע: ${reason}."
      said="${waited}"
    fi
    sleep 30; waited=$(( waited + 30 ))
  done
}

# True when compose would leave the running bina-ds exactly as it is (dry run says only "Running").
#   $1  the ENGINE-side docker socket path bina-ds was started with. Inside bina-ds the socket is
#       mounted at /var/run/docker.sock and BBOX_DOCKER_SOCK says so, but compose interpolates it
#       into the socket mount's SOURCE — an engine path. Where the engine serves more than one path
#       (the macOS engine: /run/bbox-docker.sock and /var/run/docker.sock), the wrong one reads as a
#       config change and every no-op rebuild would plan a recreate.
# COMPOSE_GUARD_OFF: this dry run must not be handed off again by the guard in lib.sh.
nothing_to_apply() {
  local sock="$1" plan; shift
  plan="$(BBOX_DOCKER_SOCK="${sock}" COMPOSE_GUARD_OFF=1 dc up -d --dry-run "$@" "${SERVICE}" 2>&1)" || return 1
  printf '%s\n' "${plan}" | grep -q "bina-ds.* Running" \
    && ! printf '%s\n' "${plan}" | grep -qE "bina-ds.* (Recreate|Create|Start|Restart)"
}

cmd_launch() {
  local verb="${1:-up}"; shift || true
  local cid prev sock home busy
  cid="$(current_container)"
  [ -n "${cid}" ] || die "no ${SERVICE} container found — nothing to hand off"
  prev="$(docker inspect -f '{{.Image}}' "${cid}")"
  # The conversations' volume, read-only, so the helper can tell when the office is quiet.
  home="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data/dsh"}}{{.Name}}{{end}}{{end}}' "${cid}")"
  # The engine-side path of the socket this container was given; the helper mounts the same one
  # at the same path, so compose's own interpolation of BBOX_DOCKER_SOCK stays true for it.
  sock="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}{{.Source}}{{end}}{{end}}' "${cid}")"
  [ -n "${sock}" ] || sock=/var/run/docker.sock
  # A rebuild that produced the same image, with the same compose config, changes nothing — and a
  # restart for nothing still ends every working conversation. Measured 2026-09-29 15:24: an agent
  # rebuilt bina-ds, got a byte-identical image, and the restart would have cut off three agents.
  if [ "${verb}" != restart ] && nothing_to_apply "${sock}" "$@"; then
    log "nothing to apply: bina-ds already runs this build and configuration"
    echo "bina-ds: already runs this exact build and configuration — nothing to restart."
    return 0
  fi
  # Refuse NOW, with the holder's name, rather than after the old container is gone.
  if [ "${verb}" != restart ] && busy="$(busy_ports "${sock}" "${cid}" "${prev}")" && [ -n "${busy}" ]; then
    log "refused: the new definition publishes a host port that is taken — ${busy}"
    cat <<EOF
bina-ds: NOT restarting — the new definition publishes a host port that something else holds:
  ${busy}
  Compose would stop bina-ds first and then fail to start it, and the rollback would fail the same
  way (measured 2026-09-30 13:43: 41 minutes down). Free the port on the engine, or change
  BINA_DS_AGENT_PORT / BINA_DS_AGENT_BIND in .env, and run the command again. bina-ds keeps running.
EOF
    return 1
  fi
  if [ -n "$(docker ps -q --filter "name=^${HELPER}$")" ]; then
    echo "bina-ds: an update of bina-ds is already in progress (container ${HELPER}); see ${LOG}"
    return 0
  fi
  docker rm -f "${HELPER}" >/dev/null 2>&1 || true
  docker run -d --rm --name "${HELPER}" \
    --label binaos.role=bina-ds-self-update \
    --network traefik-network \
    -v "${sock}:${sock}" -e BBOX_DOCKER_SOCK="${sock}" -e DOCKER_HOST="unix://${sock}" \
    -v "${REPO}:${REPO}" -w "${REPO}" -e BBOX_REPO_HOST="${REPO}" \
    -e BBOX_AGENT_URL="$(agent_api_url "${cid}")" \
    ${home:+-v "${home}:/data/dsh:ro"} \
    -e TZ="${TZ:-Asia/Jerusalem}" -e BINA_DS_SELF_UPDATE_DELAY="${DELAY}" \
    -e BINA_DS_SELF_UPDATE_HEALTH_TIMEOUT="${HEALTH_TIMEOUT}" \
    -e BINA_DS_SELF_UPDATE_QUIET="${QUIET_S}" -e BINA_DS_SELF_UPDATE_MAX_WAIT="${MAX_WAIT}" \
    -e BINA_DS_SELF_UPDATE_FORCE_AFTER="${FORCE_AFTER}" \
    --entrypoint bash "${prev}" "${REPO}/apps/bina-ds/self-update.sh" apply "${prev}" "${verb}" "$@" \
    >/dev/null
  log "handed off: '${verb} ${*}' of bina-ds to ${HELPER} (previous image ${prev:7:12})"
  cat <<EOF
bina-ds: the restart of bina-ds itself is handed to a helper outside this container (${HELPER}).
  It waits until no conversation is working (so no agent is cut off mid-task; at most
  $(( MAX_WAIT / 60 )) min), then recreates bina-ds, waits for the health check, and puts the previous
  image back if the new one is not healthy. Progress: ${LOG#"${REPO}/"}
  Finish this turn now with a short summary — the restart waits for it. After the restart the
  owner gets a notification and continues the conversation.
EOF
}

cmd_apply() {
  local prev="$1" verb="$2"; shift 2
  local ref cid rc=0 busy live
  # `create` from inside meant "apply the new container"; bina-ds was running, so it runs again.
  [ "${verb}" = create ] && verb=up
  sleep "${DELAY}"
  cid="$(current_container)"
  wait_quiet "${cid}"
  live="$(live_sessions)"
  # The wait can be long; whatever was pending may have been applied (or undone) meanwhile.
  if [ "${verb}" != restart ] && nothing_to_apply "${BBOX_DOCKER_SOCK}" "$@"; then
    log "nothing to apply any more: bina-ds already runs this build and configuration"
    return 0
  fi
  # Checked again here, after the wait: a port free at launch may be taken an hour later. The old
  # container is still up at this point, and stays up.
  if [ "${verb}" != restart ] && busy="$(busy_ports "${BBOX_DOCKER_SOCK}" "${cid}" "${prev}")" && [ -n "${busy}" ]; then
    log "refused: the new definition publishes a host port that is taken — ${busy}; bina-ds keeps running as it was"
    notify error "העדכון של בינה לא הוחל — פורט תפוס" "ההגדרה החדשה מפרסמת פורט במארח שמשהו אחר מחזיק: ${busy}. בינה ממשיכה לרוץ כמו שהיא. שחרר את הפורט (או שנה BINA_DS_AGENT_PORT ב-.env) והרץ שוב: ./scripts/dc up -d bina-ds"
    return 1
  fi
  ref="$(docker inspect -f '{{.Config.Image}}' "${cid}" 2>/dev/null || true)"
  ref="${ref%%:*}"; [ -n "${ref}" ] || ref="digital-office-bina-ds"
  # Keep a name on the known-good image: once the old container is removed it would otherwise be
  # a dangling image, one `docker image prune` away from gone.
  docker tag "${prev}" "${ref}:previous" 2>/dev/null || true
  log "applying: ${verb} ${*} ${SERVICE} (previous image ${prev:7:12})"
  # COMPOSE_GUARD_OFF: THIS helper IS the outside process the self-guard hands a self-recreate to, so
  # its own compose calls must not be handed back to `launch` a second time. They were, silently:
  # compose bakes `com.docker.compose.service=bina-ds` into the IMAGE, `bbox_self_service` matches on
  # that label, so inside this helper (started from that very image) the guard answered "bina-ds" and
  # sent `dc up -d bina-ds` back to `launch` — which then found THIS helper running and refused with
  # "an update of bina-ds is already in progress". Measured 2026-10-05 twice (this morning and
  # 18:31): the log reads `applying: up bina-ds` → `already in progress` → `ok: bina-ds healthy on
  # image 05fcfd222ecc` — healthy on the OLD container, never recreated, so a `.env` change that the
  # owner was waiting for never landed while every log line said success. The guard's own dry run
  # already uses this switch for the same reason (scripts/lib.sh: "must not be handed off again");
  # these three calls are the ones that actually apply and roll back.
  if [ "${verb}" = restart ]; then COMPOSE_GUARD_OFF=1 dc_logged restart "$@" "${SERVICE}" || rc=$?
  else COMPOSE_GUARD_OFF=1 dc_logged "${verb}" -d "$@" "${SERVICE}" || rc=$?; fi
  [ "${rc}" -eq 0 ] || log "compose exited ${rc}"
  if wait_healthy; then
    log "ok: bina-ds healthy on image $(docker inspect -f '{{.Image}}' "$(current_container)" | cut -c8-19)"
    wait_api_ready "$(current_container)" || true    # the agent API is a sibling that can be seconds
    resume_sessions "${live}"                        # behind the harness the health check probes
    notify info "בינה עודכנה והופעלה מחדש" "העדכון הוחל ובינה תקינה."   # resume_sessions reports how
    return 0                                                          # many conversations came back
  fi
  log_harness_tail
  [ "${verb}" = restart ] && { notify error "בינה לא חזרה אחרי הפעלה מחדש" "השורות האחרונות מיומן בינה:
$(tail_for_notice)
פרטים: ${LOG#"${REPO}/"}"; return 1; }
  log "rolling back to the previous image ${prev:7:12}"
  docker tag "${prev}" "${ref}:latest"
  COMPOSE_GUARD_OFF=1 dc_logged up -d "${SERVICE}" || log "compose exited $? during rollback"
  if wait_healthy; then
    log "rolled back: bina-ds healthy on the previous image"
    notify warning "העדכון של בינה נכשל — הוחזרה הגרסה הקודמת" "הגרסה החדשה לא עברה את בדיקת התקינות, ובינה רצה שוב על הגרסה הקודמת. פרטים: ${LOG#"${REPO}/"}"
    return 0
  fi
  # The rollback failing too means the fault is not in the image: a port, the volume, the engine.
  log_harness_tail
  notify error "בינה לא עולה — גם לא בגרסה הקודמת" "גם הגרסה הקודמת לא עברה את בדיקת התקינות, כלומר הבעיה אינה בתמונה אלא בסביבה (פורט תפוס, קובץ בנפח הנתונים, המנוע). נדרשת בדיקה ידנית: ./scripts/dc up -d bina-ds. השורות האחרונות מיומן בינה:
$(tail_for_notice)
פרטים: ${LOG#"${REPO}/"}"
  return 1
}

# One line, read whole before it runs: a helper that is still waiting keeps working even if this file
# is edited meanwhile (bash reads a script as it executes it; it never reads past this line).
main() { case "${1:-}" in launch) shift; cmd_launch "$@" ;; apply) shift; cmd_apply "$@" ;; *) echo "usage: $0 launch <up|create|restart> [flags…] | apply <prev-image> <verb> [flags…]" >&2; return 2 ;; esac; }; main "$@"; exit $?
