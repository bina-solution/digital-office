#!/usr/bin/env bash
# follow.sh — an office FOLLOWS dgo-stable by itself (r030-201).
#
#     ./bbox follow [--dry-run]    one cycle: what the host timer runs (--dry-run says what it would do)
#     ./bbox follow heal           only the heal a cycle starts with: what the boot timer runs, 3 and 8 minutes in
#     ./bbox follow status        what is declared, where this office stands, the last cycle
#     ./bbox follow install        install or remove the host timer from the declaration (`bbox run` does this)
#     ./bbox follow clear          after a session repaired a stopped take by hand: forget it, follow again
#     ./bbox follow clear services after a session put the services right by hand: the next cycle closes their row
#
# WHY. Nothing kept an office current: it took dgo-stable only when a person or a session merged it by hand. The
# HP drifted 761 commits in ten days, and every door that would have let another office update it was itself new
# code the HP did not have — so the only way left was the owner, at the machine (rep-local-261102-201500).
#
# THE DECLARATION is .env: DGO_FOLLOW=dgo-stable (empty: this office does not follow). DGO_BRANCH is the office's
# own branch, the only one ever written (the branch rule, AGENTS.md). DGO_FOLLOW_GATES names the workflow whose
# success makes a commit takeable (default gates-hosted.yml). The MacBook leaves DGO_FOLLOW empty: live sessions
# commit in its checkout, and a merge under them is the one thing this must never do. An office with no GitHub
# credential of its own (the HP) declares DGO_FOLLOW_VIA=<a linked office> and DGO_FOLLOW_VIA_PATH (its git proxy's
# path for the repository, /git/gh/<account>/<owner>/<repo>.git): each cycle then fetches and pushes through that
# office's git app, at the address `bbox remote` gives NOW — a port written into a remote goes stale (the HP's
# macbook-git pointed at 9004 after the Mac's door moved to 9005). DGO_FOLLOW_VIA may name several offices, in order
# (`macbook vps1`): the cycle fetches from, and pushes to, the first whose git app ANSWERS this cycle. Published is not
# enough. On 2026-11-13 from 02:12Z the MacBook was out of memory, its door answered 502 and timeouts, and the HP's
# and the Dell's follows, both through it, took nothing (DGO-1863). Each office's git app names its account itself, so
# an entry may carry its own path (`vps1:/git/gh/<account>/<owner>/<repo>.git`); DGO_FOLLOW_VIA_PATH is the path of
# the entries that carry none.
#
# ONE CYCLE (the timer's, every 30 minutes) makes at most ONE change, and every change is a TAKE:
#   1. One at a time (flock, held by flock(1) itself so nothing the cycle starts inherits it); never beside another
#      heavy job (the bbox heavy slot), on a loaded host, or while an app says it is in use (its own hooks/busy: Meet,
#      a call in progress); only on DGO_BRANCH, with no git command in flight.
#   2. A take an earlier cycle did not finish is settled first (TAKING in the state): rolled back if it was never
#      verified, and the cycle stops — sticky — when the checkout moved on top of it. Nothing is ever called current
#      while one is open.
#   3. The office's own branch, if origin is ahead of the checkout (pushed from elsewhere), is a take of its own. An
#      office whose DGO_FOLLOW IS its DGO_BRANCH — a client office on the public release (both `main`), which may not
#      push — takes only this: each public commit is a version already cut after its gates, and nothing is pushed back.
#   4. Otherwise the target is the newest first-parent commit of origin/DGO_FOLLOW whose gates run SUCCEEDED: GitHub's
#      API, with the checkout's own git credential (in memory, handed to curl on stdin, never in argv) — a run that
#      succeeded, or one still in progress whose `green` job already did (only re-ask is left, DGO-2123); where that
#      cannot be read, the ref refs/green/DGO_FOLLOW that gates-hosted moves forward on every green run (git data, so
#      any path that brings the code brings it).
#   A TAKE: refused before anything moves when the index holds staged changes, a modified file is one the target
#   changes (renames counted as both paths), or a file the target adds is already on disk untracked. platform.state.yaml
#   is the office's own state (the console and the link write it): committed on the office branch first, when the
#   target touches it — but a dgo-stable take that would change which apps it DECLARES enabled (another office's
#   decision, merged into dgo-stable) is undone before anything runs. Then `bbox run`, and every service that was
#   running and healthy before must be running and healthy after (one that vanished counts, unless the take retired it
#   from the compiled model; services that cannot be read count). An app switched in the checkout (the owner on his
#   console, a session's proof) is «switched», never «lost»: a service of an app the checkout declares off in so many
#   words, which the compiled model no longer declares, is spared and named, and the take's line names a switch made
#   while it ran (the king's decision, 2026-11-20). Healthy, and
#   HEAD still the merge → push (never forced). Not → `git reset --keep` to the commit before (never pushed, so no
#   published history changes), `bbox run` again, and the target is not taken again until a newer one is green.
# The owner hears what failed: ONE row in the notice centre (source `follow`), written once per distinct text,
# updated in place, and closed with «back to normal» by the next good take or current cycle. And a good take of
# dgo-stable, once, in a row of its own (told_took) — with a row open, its «back to normal» says the take instead.
# And the line itself, where the checkout reads GitHub's API: a gates job of DGO_FOLLOW queued longer than
# DGO_FOLLOW_LINE_WAIT_MIN (60) for a runner is told, in a row of its own (line_waits), and closed when none waits.
set -uo pipefail

# The merge below may replace this very file, and bash reads a script as it runs: run from a private copy.
HERE="${DGO_FOLLOW_HERE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)}"
REPO_ROOT="${REPO_ROOT:-$(cd "${HERE}/.." && pwd -P)}"
if [ -z "${DGO_FOLLOW_COPY:-}" ]; then
  _copy="$(mktemp "${TMPDIR:-/tmp}/dgo-follow.XXXXXX")" || exit 1
  cp "${BASH_SOURCE[0]}" "${_copy}" || exit 1
  DGO_FOLLOW_COPY="${_copy}" DGO_FOLLOW_HERE="${HERE}" REPO_ROOT="${REPO_ROOT}" exec bash "${_copy}" "$@"
fi
_COPY="${DGO_FOLLOW_COPY}"; unset DGO_FOLLOW_COPY      # a nested follow.sh (`bbox run` → install) makes its own
trap 'rm -f "${_COPY}"' EXIT
export REPO_ROOT
LOG_TAG=follow
. "${HERE}/lib.sh"

FOLLOW="$(read_env DGO_FOLLOW)"
BRANCH="$(read_env DGO_BRANCH)"
GATES="$(read_env DGO_FOLLOW_GATES)"; GATES="${GATES:-gates-hosted.yml}"
# read_env_value: a quoted list (`"macbook vps1"`) or a trailing ` # comment` is not part of the value
VIA="$(read_env_value DGO_FOLLOW_VIA)"
read -r -a _VIA_LIST <<<"${VIA//,/ }"; VIA="${_VIA_LIST[*]-}"   # the ordered list, one space between entries
VIA_PATH="$(read_env_value DGO_FOLLOW_VIA_PATH)"
# how long one office's git app may take to answer, in seconds; the environment wins, as for MAX_LOAD below.
# 1–99999, or 20, said: a typo must never abort the cycle unsaid — a leading 0 is octal to bash's arithmetic (`08`
# aborts the script), and git refuses a lowSpeedTime above 2^31 (the second reader of DGO-1863)
VIA_PROBE="${DGO_FOLLOW_VIA_PROBE_S:-$(read_env_value DGO_FOLLOW_VIA_PROBE_S)}"
VIA_PROBE="${VIA_PROBE#"${VIA_PROBE%%[![:space:]]*}"}"; VIA_PROBE="${VIA_PROBE%"${VIA_PROBE##*[![:space:]]}"}"   # the ends only: «1 5» is no number
case "${VIA_PROBE}" in ''|*[!0-9]*|0*|??????*) [ -z "${VIA_PROBE}" ] || warn "DGO_FOLLOW_VIA_PROBE_S=${VIA_PROBE} is not 1–99999 seconds — 20 applies"; VIA_PROBE=20 ;; esac
# "A loaded host" is the 1-minute load above this, default the CPU count. An office that runs its agents' sessions
# all day (the HP: 8 of them, DGO-1299) sits above its CPU count while it works, and never took a green dgo-stable
# (skipped at 8–20 on 6 CPUs, 2026-11-03). So the office declares its own ceiling in .env; the environment still wins.
MAX_LOAD="${DGO_FOLLOW_MAX_LOAD:-$(read_env_value DGO_FOLLOW_MAX_LOAD)}"
# A number or nothing: awk compares anything else as text, and "16" quoted skipped every cycle while abc never did.
case "${MAX_LOAD}" in ''|*[!0-9.]*|*.*.*) [ -z "${MAX_LOAD}" ] || warn "DGO_FOLLOW_MAX_LOAD=${MAX_LOAD} is not a number — the CPU count applies"; MAX_LOAD= ;; esac
# minutes a gates run of DGO_FOLLOW may wait for a runner before the owner is told (line_waits): 1–99999, or 60, said
LINE_WAIT_MIN="${DGO_FOLLOW_LINE_WAIT_MIN:-$(read_env_value DGO_FOLLOW_LINE_WAIT_MIN)}"
LINE_WAIT_MIN="${LINE_WAIT_MIN#"${LINE_WAIT_MIN%%[![:space:]]*}"}"; LINE_WAIT_MIN="${LINE_WAIT_MIN%"${LINE_WAIT_MIN##*[![:space:]]}"}"   # as VIA_PROBE: the ends only
case "${LINE_WAIT_MIN}" in ''|*[!0-9]*|0*|??????*) [ -z "${LINE_WAIT_MIN}" ] || warn "DGO_FOLLOW_LINE_WAIT_MIN=${LINE_WAIT_MIN} is not 1–99999 minutes — 60 applies"; LINE_WAIT_MIN=60 ;; esac
SRC=origin                              # where a cycle fetches and pushes: origin, or the URL resolve_src() makes
VIA_USED=""                             # …and the office of DGO_FOLLOW_VIA whose git app answered this cycle
VIA_WHY=""                              # …or, when none did, what each one said
OFFICE="$(read_env DGO_OFFICE_ID)"; OFFICE="${OFFICE:-${DN}}"
STATE_DIR="${REPO_ROOT}/data/follow"
STATE="${STATE_DIR}/state"
SETTLE="${DGO_FOLLOW_SETTLE:-600}"      # seconds a service may still be "starting" after `bbox run`
# seconds a file changed here must be untouched before it is LEFT WORK (take: kept in a commit, or unstaged)
KEEP_AFTER="${DGO_FOLLOW_KEEP_AFTER:-21600}"
UNIT=dgo-follow
DRY=0
HEAL=0                                  # `bbox follow heal`: office_heal, and nothing after it
APPS_START="?" MODEL_START="" SWITCHED=""   # a take's start, and its switches (note_switched): none, never inherited
export GIT_TERMINAL_PROMPT=0            # a timer has no terminal: a missing credential fails, never waits
# Every compose command a cycle runs (`bbox run`, a folder's or a held service's `up`) waits for a quiet moment of an app
# at work, even one it names: nobody pressed anything (lib.sh compose_when_idle_split, DGO-2129)
export BBOX_RECREATE_WHEN_IDLE=1
# Every HTTP transfer a cycle makes is bounded like its probe (DGO-1876). A door that answered the probe and then goes
# silent mid-pack fails the fetch or the push in a minute, and the cycle says so. The MacBook's door did exactly that
# from 10:09Z on 2026-11-13, its engine's share hung; without the bound the cycle, and every later one, waited for its
# 6 h. The bound is three probes long, since a pack takes longer than a list of refs, and the server's own work before
# its first byte counts too. Never under 15 s: a server working silently sends a keepalive every 5 s, and a shorter
# bound would cut a real pack (the second reader). http.* is read only by an HTTP transfer: no local command changes,
# and an ssh remote is not bounded by it.
NET_SLOW=$((VIA_PROBE * 3 > 15 ? VIA_PROBE * 3 : 15))
git() { command git -c core.quotePath=false -c http.lowSpeedLimit=1 -c "http.lowSpeedTime=${NET_SLOW}" -C "${REPO_ROOT}" "$@"; }   # paths as they are on disk
short() { git rev-parse --short "$1" 2>/dev/null || printf '%.8s' "$1"; }

# ── state: key=value lines, rewritten whole (only the locked cycle and `clear` write it) ───────────
st_get() { { grep -E "^$1=" "${STATE}" 2>/dev/null || true; } | tail -1 | cut -d= -f2-; }
st_set() {   # st_set KEY VALUE [KEY VALUE…] — a dry run writes nothing
  [ "${DRY}" = 1 ] && return 0
  mkdir -p "${STATE_DIR}" || return 1
  local keys="" a i=0 tmp="${STATE}.new.$$"
  for a in "$@"; do [ $((i % 2)) = 0 ] && keys="${keys}${keys:+|}${a}"; i=$((i + 1)); done
  { grep -vE "^(${keys})=" "${STATE}" 2>/dev/null || true
    while [ $# -ge 2 ]; do printf '%s=%s\n' "$1" "$(printf '%s' "$2" | tr '\n' ' ')"; shift 2; done
  } > "${tmp}" && mv -f "${tmp}" "${STATE}"
}
logline() {
  [ "${DRY}" = 1 ] && return 0
  mkdir -p "${STATE_DIR}" && printf '%s %s\n' "$(date -u '+%F %T UTC')" "$*" >> "${STATE_DIR}/log"
}

# ── the owner's one row in the notice centre ─────────────────────────────────────────────────────
post_notice() {   # level title body [id] — the office's one row (follow:<office>), or a row of its own (follow:<id>)
  if [ -n "${DGO_FOLLOW_NOTIFY_CMD:-}" ]; then "${DGO_FOLLOW_NOTIFY_CMD}" "$@"; return; fi
  local cid
  cid="$("${REPO_ROOT}/scripts/dc" ps -q notifications 2>/dev/null | head -1)"
  [ -n "${cid}" ] || { say "the notice centre is not running here — not told: $2"; return 1; }
  python3 -c 'import json, sys
sid = "follow:" + (sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else sys.argv[1])
print(json.dumps({"source": "follow", "source_id": sid, "level": sys.argv[2],
                  "title": sys.argv[3][:200], "body": sys.argv[4][:2000], "meta": {"office": sys.argv[1]}},
                 ensure_ascii=False))' "${OFFICE}" "$@" \
    | docker exec -i "${cid}" python3 -c 'import sys, urllib.request
r = urllib.request.Request("http://127.0.0.1:8977/api/notifications", data=sys.stdin.buffer.read(),
                           method="POST", headers={"Content-Type": "application/json"})
sys.exit(0 if urllib.request.urlopen(r, timeout=15).status in (200, 201) else 1)' >/dev/null 2>&1
}
tell() {   # title body — told once per distinct text; the row is updated, never duplicated
  local key; key="$(printf '%s\n%s' "$1" "$2" | cksum | cut -d' ' -f1)"
  say "$1 — $2"
  [ "${DRY}" = 1 ] && return 0
  [ "$(st_get NOTICE)" = "${key}" ] && return 0
  post_notice error "$1" "$2" && st_set NOTICE "${key}"
}
all_clear() {   # close the open row, if there is one
  [ "${DRY}" = 1 ] && return 0
  [ -n "$(st_get NOTICE)" ] || return 0
  post_notice info "המשרד מעודכן שוב — ${OFFICE}" "back to normal: $1" && st_set NOTICE "" TOLD_PENDING ""
}   # (a take line still waiting is old news once the office is back to normal: never said after it)

# THE SERVICES' OWN ROW (DGO-2123; the king's second reader, 2026-11-20). An alarm about services after a take — on the
# code from before it, or fallen — is no reason a take is blocked: the green commit IS in the branch, so the «current»
# path's all_clear closed the office's row while they still ran the old code (a failed rebuild, the next cycle), or in
# the very cycle that said it (folders_retry failing again). Such an alarm has a row of its own (follow:svc:<office>),
# which all_clear never touches: only a cycle that finds its cause gone closes it (svc_clear).
#
# The row holds CAUSES (SVC_CAUSES, «kind:name» each), and each closes by its own proof alone (its second reader):
#   images:<svc>     a rebuild of it that worked (svc_drop, in a take) — never stale_images' file times, which call a
#                    cache-hit image old for ever (issues/stale-images-reads-file-times-…)
#   folders:<svc>    no recreate waits for it any more (FOLDERS_PENDING)
#   fell:<svc>       good in two cycles in a row, after the one that said it (fell → settling → gone): one reading of a
#                    service that restarts and restarts can say «running» between two crashes (the third reader)
#   unchecked:<sha>  nothing the follow runs: a later take's check reads only ITS diff, never the one that could not be
#                    read (the third reader) — a session that looked says so: `bbox follow clear services`
# A service the office no longer declares holds nothing. The row closes when no cause is left; `follow clear services`
# drops them all, and the next cycle closes it (and posts again until it could).
svc_name() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; }   # a service's name — never a word of a sentence
tell_svc() {   # title body kind [name…] — told once per distinct text on the services' row; its causes kept once told
  local key t="$1" b="$2" kind="$3" n causes
  shift 3
  key="$(printf '%s\n%s' "${t}" "${b}" | cksum | cut -d' ' -f1)"
  say "${t} — ${b}"
  [ "${DRY}" = 1 ] && return 0
  causes="$(st_get SVC_CAUSES)"
  for n in "$@"; do
    svc_name "${n}" || continue
    [[ " ${causes} " == *" ${kind}:${n} "* ]] || causes="${causes:+${causes} }${kind}:${n}"
  done
  if [ "$(st_get SVC_NOTICE)" != "${key}" ]; then
    post_notice error "${t}" "${b}" "svc:${OFFICE}" || return 1   # not told: nothing kept for it, as tell() keeps nothing
    st_set SVC_NOTICE "${key}" SVC_TOLD "${causes}"                # SVC_TOLD: what the row's text speaks for
  fi
  st_set SVC_CAUSES "${causes}"
}
svc_drop() {   # kind name… — causes the calling path proved gone; with no name, none (never «all of the kind»)
  [ "${DRY}" = 1 ] && return 0
  local kind="$1" c n gone out=""
  shift
  [ $# -gt 0 ] || return 0
  for c in $(st_get SVC_CAUSES); do
    gone=""
    if [ "${c%%:*}" = "${kind}" ]; then for n in "$@"; do [ "${c#*:}" != "${n}" ] || gone=1; done; fi
    [ -n "${gone}" ] || out="${out:+${out} }${c}"
  done
  st_set SVC_CAUSES "${out}"
}
svc_clear() {   # a cycle, before anything it tells: drop the causes found gone; close the row when none is left
  [ "${DRY}" = 1 ] && return 0
  [ -n "$(st_get SVC_NOTICE)" ] || return 0
  local causes c kind name out="" declared="" good="" pending
  causes="$(st_get SVC_CAUSES)"
  if [ -n "${causes}" ]; then
    # cannot tell — unreadable, or EMPTY (a model with no service is a compose that read no file: G7) — the row stays
    declared="$(model_services 2>/dev/null)" && [ -n "${declared}" ] || return 0
    good="$(services 2>/dev/null | good_names)" || return 0
    pending=" $(st_get FOLDERS_PENDING | cut -s -d' ' -f2-) "
    for c in ${causes}; do
      kind="${c%%:*}" name="${c#*:}"
      if [ "${kind}" != unchecked ]; then
        grep -qxF -- "${name}" <<<"${declared}" || continue      # retired, renamed: nothing left to wait for
        case "${kind}" in
          folders)  [[ "${pending}" == *" ${name}:"* ]] || continue ;;
          fell)     grep -qxF -- "${name}" <<<"${good}" && c="settling:${name}" ;;   # good once: once more to go
          settling) if grep -qxF -- "${name}" <<<"${good}"; then continue; else c="fell:${name}"; fi ;;
        esac
      fi
      out="${out:+${out} }${c}"
    done
    st_set SVC_CAUSES "${out}"
    if [ -n "${out}" ]; then
      # some went — here, or in a take (svc_drop) — and some stay: the row says what holds it now, not the last alarm
      # (the third reader); a cause between its two good readings is still the same cause
      [ "$(sed 's/settling:/fell:/g' <<<"${out}")" = "$(st_get SVC_TOLD | sed 's/settling:/fell:/g')" ] \
        || { post_notice error "עדיין פתוח: שירותים אחרי עדכון — ${OFFICE}" "Still open: ${out} (bbox follow status; once put right by hand: bbox follow clear services)." "svc:${OFFICE}" \
             && st_set SVC_TOLD "${out}"; } || true
      return 0
    fi
  fi
  post_notice info "השירותים רצים שוב על הקוד העדכני — ${OFFICE}" "back to normal: every service ${BRANCH} $(short HEAD) runs is on its code" "svc:${OFFICE}" \
    && st_set SVC_NOTICE "" SVC_CAUSES "" SVC_TOLD ""
}
told_took() {   # what tgt — a good take of dgo-stable is news too (DGO-1329: «every important event», a take first
  # among them): said in a row of its own (follow:took:<office>:<sha>, the kind first so a rule can match every
  # office's), so the office's open row is never overwritten by good news; its body is the taken commit's subject
  # (the notice centre cuts it, never a byte cut inside a letter). With a row open, its «back to normal» says the take
  # instead. A take of the office's own branch is a push from elsewhere, told by whoever pushed it: not said. A line
  # that could not be posted waits in TOLD_PENDING and is said by a later cycle.
  local sha; sha="$(short "$2")"
  [ "${DRY}" = 1 ] && return 0
  if [ -n "$(st_get NOTICE)" ]; then all_clear "$1 ${sha} taken"; return 0; fi
  # …except where the own branch IS what the office follows (a client office on the public release): there a take of
  # it is the new version, and nobody else tells it (DGO-1819)
  [ "$1" = "${FOLLOW}" ] || { [ "${FOLLOW}" = "${BRANCH}" ] && [ "$1" = "origin/${FOLLOW}" ]; } || return 0
  if post_notice info "המשרד התעדכן ל־${1#origin/} ${sha}" "$(git log -1 --format=%s "$2" 2>/dev/null)" "took:${OFFICE}:${sha}"
  then say "told: took $1 ${sha}"; st_set TOLD_PENDING ""
  else say "the take of $1 ${sha} could not be told — the next cycle tells it"; st_set TOLD_PENDING "$1 $2"
  fi
}

# ── where a cycle fetches and pushes ──────────────────────────────────────────────────────────────
via_bare() {   # 0 when an office of DGO_FOLLOW_VIA carries no path of its own (it then needs DGO_FOLLOW_VIA_PATH)
  local e
  for e in ${_VIA_LIST[@]+"${_VIA_LIST[@]}"}; do case "${e}" in *:/*) ;; *) return 0 ;; esac; done
  return 1
}
via_names() {   # the offices DGO_FOLLOW_VIA names, in order, without their paths: «macbook, vps1»
  local e out=""
  for e in ${_VIA_LIST[@]+"${_VIA_LIST[@]}"}; do out="${out:+${out}, }${e%%:*}"; done
  printf '%s' "${out}"
}
git_said() {   # what git printed → its verdict in one line: its first fatal:/error: (not a warning printed before it),
  # else its last line (-a: a line git's proxy wrote in another encoding is still text), without the URL git repeats
  local line
  line="$(grep -a -m1 -E '^(fatal|error):' <<<"$1" || tail -n 1 <<<"$1")"
  sed -E "s/^fatal: unable to access '[^']*': /fatal: /" <<<"${line}"
}
resolve_src() {   # SRC = origin, or the first git app of DGO_FOLLOW_VIA that ANSWERS now, in order; fails, said
  SRC=origin; VIA_USED=""; VIA_WHY=""
  [ -n "${VIA}" ] || return 0
  local entry office path port url err rc probe="${VIA_PROBE}" cap="" why line   # VIA_PROBE: checked where it is read
  # git's low-speed bound stops a door that accepts and goes silent; timeout(1) also bounds a connect to an address that
  # never replies and a name that never resolves, which no git setting does (where there is no timeout, git's bound alone)
  command -v timeout >/dev/null 2>&1 && cap="timeout -k 5 $((probe + 10))"
  for entry in ${_VIA_LIST[@]+"${_VIA_LIST[@]}"}; do
    office="${entry%%:*}"
    case "${entry}" in *:/*) path="/${entry#*:/}" ;; *) path="${VIA_PATH}" ;; esac   # office:/path, or the shared one
    [ -n "${path}" ] || continue      # never here: the cycle blocks on a missing path before it asks (via_bare)
    # the DOOR the link publishes for it (registry.link_port), which is what `bbox remote` itself calls — not the app's
    # own port, which only the serving office's network answers on (that one is only the last resort, for a record the
    # compiler has not rendered yet: then the probe below fails, and the next office is asked)
    port="$("${DGO_FOLLOW_BBOX:-${REPO_ROOT}/bbox}" remote "${office}" git-accounts --json 2>/dev/null \
            | python3 -c 'import json, sys
d = json.load(sys.stdin)
print(int((d.get("registry") or {}).get("link_port") or d["app"]["port"]))' 2>/dev/null)" || port=""
    if [ -z "${port}" ]; then
      say "${office}'s git app (DGO_FOLLOW_VIA) is not published to this office"
      VIA_WHY="${VIA_WHY:+${VIA_WHY}; }${office}: not published"; continue
    fi
    # it must ANSWER, with the branch this office follows (exit 2, the branch absent, is no answer either: the fetch would
    # fail the same). What git said is kept — on this line and in the cycle's own (LAST_DETAIL, data/follow/log) — so
    # the root is named: a 502, a timeout (124), a wrong path.
    url="http://git-accounts.${office}:${port}${path}"
    # -C explicitly: timeout(1) runs the git BINARY, not the git() function above, and from this cycle's own directory
    # the checkout's config (its insteadOf, its remotes) would not be read
    err="$( { ${cap} git -C "${REPO_ROOT}" -c http.lowSpeedLimit=1 -c "http.lowSpeedTime=${probe}" \
                ls-remote -q --exit-code "${url}" "refs/heads/${FOLLOW}" >/dev/null; } 2>&1 )"; rc=$?
    if [ "${rc}" != 0 ]; then
      # git's own verdict (git_said). Without the URL git repeats — it is on the line above — so the cause fits
      # («… returned error: 502»), and cut by characters, not bytes: the git proxy's errors are Hebrew
      line="$(git_said "${err}")"
      why="exit ${rc}${line:+: ${line:0:120}}"
      say "${office}'s git app, at its door :${port}, does not answer (${why})"
      VIA_WHY="${VIA_WHY:+${VIA_WHY}; }${office}: ${why}"; continue
    fi
    say "through the git app of ${office}, at its door :${port}"
    SRC="${url}"; VIA_USED="${office}"
    return 0
  done
  return 1
}
push_branch() {   # sha → DGO_BRANCH where this cycle fetched from (never forced); origin/DGO_BRANCH then says so, as a
  # push to a NAMED remote would have set it — recover() reads it to tell "pushed" from "never verified". Nothing to
  # push when origin's branch, as this cycle fetched it, already IS that commit (a take of the office's own branch is a
  # fast-forward to it): an office with no right to push — a client office on the public release — would otherwise be
  # refused every cycle and told so every cycle (DGO-1819).
  [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "$1" ] && return 0
  git push -q "${SRC}" "$1:refs/heads/${BRANCH}" 2>/dev/null || return 1
  git update-ref "refs/remotes/origin/${BRANCH}" "$1"
}

# ── the gates ─────────────────────────────────────────────────────────────────────────────────────
gh_api() {   # <path under repos/<owner>/<repo>/> → GitHub's JSON for it, with the checkout's own git credential; fails
  # when origin is not on GitHub or the call does not answer (5 s to connect: a host whose packets to GitHub are dropped
  # loses seconds, not a minute, per call). Never print the URL: it may carry a credential.
  if [ -n "${DGO_FOLLOW_GH_CMD:-}" ]; then "${DGO_FOLLOW_GH_CMD}" "$1"; return; fi
  local url slug tok
  url="$(git remote get-url origin 2>/dev/null)" || return 1
  case "${url}" in *github.com[:/]*) ;; *) return 1 ;; esac
  slug="$(printf '%s' "${url}" | sed -E 's#\.git$##; s#^.*github\.com[:/]##')"
  tok="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')"
  { [ -z "${tok}" ] || printf 'header = "Authorization: Bearer %s"\n' "${tok}"; } \
    | curl -sf --connect-timeout 5 --max-time 30 -K - -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/${slug}/$1"
}
green_shas() {   # the commits of DGO_FOLLOW whose ${GATES} run succeeded, one per line; fails when none can be read
  if [ -n "${DGO_FOLLOW_GREEN_CMD:-}" ]; then "${DGO_FOLLOW_GREEN_CMD}"; return; fi
  local ref="" api="" going="" id sha
  # Every green run, where the checkout can read GitHub's API.
  api="$(gh_api "actions/workflows/${GATES}/runs?branch=${FOLLOW}&status=success&per_page=100" \
    | python3 -c 'import json, sys
for r in json.load(sys.stdin).get("workflow_runs", []):
    print(r["head_sha"])' 2>/dev/null)" || api=""
  # …and a run still IN PROGRESS whose verdict is in: its `green` job succeeded (the gates and the carrier passed and
  # refs/green moved), and what is left — re-ask, continue-on-error — cannot change it. re-ask waits for the one runner
  # behind the very runs it asks again, and until it ends the run is not «success»: batch 88 was green, refs/green had
  # moved, and every office that reads the API kept the version before (DGO-2123, measured 2026-11-20 on vps1).
  going="$(gh_api "actions/workflows/${GATES}/runs?branch=${FOLLOW}&per_page=20" | python3 -c 'import json, sys
for r in json.load(sys.stdin).get("workflow_runs", []):
    if r.get("status") != "completed":
        print(r["id"], r["head_sha"])' 2>/dev/null)" || going=""
  while read -r id sha; do
    [ -n "${id}" ] || continue
    gh_api "actions/runs/${id}/jobs?filter=latest&per_page=100" | python3 -c 'import json, sys
sys.exit(0 if any(j.get("name") == "green" and j.get("conclusion") == "success"
                  for j in json.load(sys.stdin).get("jobs", [])) else 1)' 2>/dev/null \
      && api="${api:+${api}$'\n'}${sha}"
  done <<EOF
${going}
EOF
  [ -z "${api}" ] || { printf '%s\n' "${api}"; return 0; }
  # Where the API cannot be read: gates-hosted's own record as git data (its green job moves refs/green/<branch> to
  # each green commit), from wherever this cycle fetches. Only then — a ref is a weaker word than the API: refs/green
  # cannot be protected the way a branch is, and anyone who may push to the repository may move it.
  if git fetch -q "${SRC}" "+refs/green/${FOLLOW}:refs/follow/green/${FOLLOW}" 2>/dev/null; then
    ref="$(git rev-parse -q --verify "refs/follow/green/${FOLLOW}^{commit}")" || ref=""
  fi
  [ -n "${ref}" ] || { say "neither GitHub's API nor refs/green/${FOLLOW} could be read — no gates" >&2; return 1; }
  printf '%s\n' "${ref}"
}
line_wait() {   # [runners|runners-required] — the ${GATES} runs of DGO_FOLLOW with a job no runner has taken yet, one line
  # of fields split by | (an empty one stays empty): "<minutes the oldest job waited>|<how many runs>|<the oldest's
  # commit>|<since, UTC>|<the runners, when NONE is online, comma-separated; «none registered» when the list is empty>".
  # No line when none waits — unless `runners` is asked, then "0|0|||<runners>": a row that is open closes only once no
  # runner is listed offline. Fails when GitHub's API cannot be read, and with `runners-required` (the open row named
  # runners) also when the runners cannot be listed this time: one failed lookup must not read as «a runner is back». A
  # run is read by its JOBS: one in progress may wait too (decide done, gates queued behind the one runner), and a re-run
  # keeps its run's first created_at but its jobs are new. Runners are listed only where the credential may (an admin's),
  # and only when none is online: an old registration left offline beside a working runner is no outage.
  if [ -n "${DGO_FOLLOW_LINE_CMD:-}" ]; then "${DGO_FOLLOW_LINE_CMD}" "$@"; return; fi
  local runs id sha j waits="" q="0|0||" off
  runs="$(gh_api "actions/workflows/${GATES}/runs?branch=${FOLLOW}&per_page=100" | python3 -c 'import json, sys
for r in json.load(sys.stdin)["workflow_runs"]:
    if r["status"] != "completed":
        print(r["id"], r["head_sha"])' 2>/dev/null)" || return 1
  while read -r id sha; do
    [ -n "${id}" ] || continue
    j="$(gh_api "actions/runs/${id}/jobs?filter=latest&per_page=100" | python3 -c 'import json, sys
q = [j["created_at"] for j in json.load(sys.stdin)["jobs"] if j["status"] == "queued"]
if q:
    print(min(q))' 2>/dev/null)" || return 1
    [ -z "${j}" ] || waits="${waits}${j} ${sha}"$'\n'
  done <<<"${runs}"
  [ -n "${waits}" ] || [ -n "${1:-}" ] || return 0
  if [ -n "${waits}" ]; then
    q="$(printf '%s' "${waits}" | python3 -c 'import datetime, sys, time
w = sorted(l.split() for l in sys.stdin if l.strip())
t = datetime.datetime.strptime(w[0][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
print("%d|%d|%s|%s" % ((time.time() - t.timestamp()) // 60, len(w), w[0][1], t.strftime("%Y-%m-%d %H:%M")))')" || return 1
  fi
  off="$(gh_api "actions/runners" 2>/dev/null | python3 -c 'import json, sys
r = json.load(sys.stdin)["runners"]
if not r:
    print("none registered")
elif not any(x.get("status") == "online" for x in r):
    print(",".join(x["name"].replace("|", "/") for x in r))' 2>/dev/null)" \
    || { [ "${1:-}" != runners-required ] || return 1; off=""; }
  printf '%s|%s\n' "${q}" "${off}"
}
line_waits() {   # the line itself: a gates job of DGO_FOLLOW queued over LINE_WAIT_MIN for a runner is told, in a row of its
  # own (follow:line:<office>), and closed («back to normal», same row) once none waits that long. On 2026-11-13–15
  # batches 66–68 waited 37 h and more behind the Dell's one runner, offline, and only a coordinator's notes said so
  # (DGO-1895). It rings (error) when a runner is listed offline, or after 3 × LINE_WAIT_MIN — longer than a busy
  # runner's drain (gates-hosted.yml: up to ~2 h behind a mac-dgo proof); before that, a wait behind a runner that may
  # only be busy is shown, not rung (warning), and told again once if it turns into a ring. It closes only once no job
  # waits that long AND no runner is listed offline: GitHub ends a job after 24 h in the queue, and a re-ask job then
  # queues fresh, so «none waits» alone would close it while the runner is still off. Where the API cannot be read (an
  # office fetching through another's git app), nothing is said or closed: a row told stays until a cycle reads it.
  local w mins n sha since off told level title mode=""
  told="$(st_get LINE_TOLD)"   # "<level>[-off] <commit>": -off when the row named runners offline
  case "${told}" in *-off\ *) mode=runners-required ;; ?*) mode=runners ;; esac
  w="$(line_wait "${mode}")" || return 0
  IFS='|' read -r mins n sha since off <<<"${w}"
  case "${mins}" in ''|*[!0-9]*) mins=0 ;; esac   # none waits — or a field that is no number, never read as a wait
  if [ "${mins}" -lt "${LINE_WAIT_MIN}" ]; then
    [ -n "${told}" ] && [ -z "${off}" ] || return 0
    post_notice info "קו השחרור זז שוב — ${OFFICE}" "No ${GATES} job of ${FOLLOW} has waited for a runner longer than ${LINE_WAIT_MIN} min any more." "line:${OFFICE}" \
      && st_set LINE_TOLD ""
    return 0
  fi
  level=warning; title="קו השחרור ממתין לשרת בדיקות — ${OFFICE}"
  [ -z "${off}" ] || title="קו השחרור עומד: שרת הבדיקות כבוי (${off}) — ${OFFICE}"
  if [ -n "${off}" ] || [ "${mins}" -ge $((LINE_WAIT_MIN * 3)) ]; then level=error; fi
  case "${told}" in error*) return 0 ;; warning*) [ "${level}" = error ] || return 0 ;; esac
  post_notice "${level}" "${title}" "${n} ${GATES} run(s) of ${FOLLOW} have a job waiting for a runner, the oldest ($(short "${sha}")) since ${since} UTC${off:+; offline: ${off}}. Until a runner takes them, no office can take anything newer than ${FOLLOW}'s last green commit." "line:${OFFICE}" \
    && st_set LINE_TOLD "${level}${off:+-off} ${sha}"
}

# ── health: "<service> <state> <health>" for every service; fails when they cannot be read ─────────
services() {
  local out
  if [ -n "${DGO_FOLLOW_HEALTH_CMD:-}" ]; then out="$("${DGO_FOLLOW_HEALTH_CMD}")" || return 1
  else
    out="$("${REPO_ROOT}/scripts/dc" ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}' 2>/dev/null)" || return 1
    out="$(printf '%s\n' "${out}" | awk -F'|' 'NF >= 2 {s = $2; if (s == "exited" && $4 == "0") s = "done"   # a one-shot that finished
                                                         print $1, s, ($3 == "" ? "-" : $3)}' | sort -u)"
  fi
  out="$(printf '%s\n' "${out}" | sed '/^$/d')"
  [ -n "${out}" ] || return 1          # zero services is a compile that resolved nothing (gate G7's shape), not health
  printf '%s\n' "${out}"
}
good_names() { awk '($2 == "running" && $3 != "unhealthy" && $3 != "starting") || $2 == "done" {print $1}'; }
settle() {   # the services, once none is still starting (or SETTLE ran out); fails when they cannot be read
  local waited=0 out
  while :; do
    out="$(services)" || return 1
    printf '%s\n' "${out}" | awk '$3 == "starting" {f = 1} END {exit !f}' && [ "${waited}" -lt "${SETTLE}" ] || break
    sleep 15; waited=$((waited + 15))
  done
  printf '%s\n' "${out}"
}
model_services() {   # the services the compiled model now declares (after `bbox run` compiled it); fails when unreadable
  if [ -n "${DGO_FOLLOW_MODEL_CMD:-}" ]; then "${DGO_FOLLOW_MODEL_CMD}"; return; fi
  "${REPO_ROOT}/scripts/dc" config --services 2>/dev/null
}
retired() {   # service — did THIS take retire it on purpose? (TAKE_PREV/TAKE_MERGED/TAKE_APPS_MOVED, set by take)
  # Only when the take's own diff removes its key from a compose file, or the office's own branch changed which apps it
  # declares. A service that merely dropped out of the compiled model (an app.json that stopped resolving) is not.
  [ -n "${TAKE_PREV:-}" ] && [ -n "${TAKE_MERGED:-}" ] || return 1
  [ "${TAKE_APPS_MOVED:-0}" = 1 ] && return 0
  # a here-string, never `git diff | grep -q`: under pipefail the grep that leaves early fails the diff (SIGPIPE)
  grep -qE "^-  ${1//./\\.}:[[:space:]]*\$" <<<"$(git diff -U0 "${TAKE_PREV}" "${TAKE_MERGED}" -- \
    ':(glob)**/docker-compose*.yml' ':(glob)**/compose*.yml')"
}
model_deps() {   # "<service> <dependency>" for every depends_on edge of the compiled model; empty when unreadable
  if [ -n "${DGO_FOLLOW_DEPS_CMD:-}" ]; then "${DGO_FOLLOW_DEPS_CMD}"; return; fi
  "${REPO_ROOT}/scripts/dc" config --format json 2>/dev/null | python3 -c 'import json, sys
for n, s in (json.load(sys.stdin).get("services") or {}).items():
    for d in (s.get("depends_on") or {}):
        print(n, d)' 2>/dev/null
}
leaning() {   # before after → "<service> <dependency>" for each service good before that leans (depends_on, transitively,
  # through services present before) on one that was NOT good before AND is not good after either.
  # Their «good» was not the office working: the Dell's n8n-task-runners and worker runners ran healthy beside an n8n
  # that had exited and an n8n-postgres in a 12-hour livelock (2026-11-11), exited within seconds of the take's
  # recreate, and the take was rolled back for three services nothing it changed had broken. A dependency the take
  # put right (good after) spares nothing — then a dependent's fall is the take's; so does one absent or a finished
  # one-shot before. When the model's edges cannot be read, none is spared. The edges are the model AFTER the take:
  # a take that adds a depends_on onto an already-bad service spares its dependent — named, never silent (lost()).
  local deps; deps="$(model_deps)" || deps=""
  [ -n "${deps}" ] || return 0
  python3 -c 'import sys
def health(text):
    good, seen = set(), set()
    for ln in text.splitlines():
        p = ln.split()
        if len(p) < 3:
            continue
        seen.add(p[0])
        if (p[1] == "running" and p[2] not in ("unhealthy", "starting")) or p[1] == "done":
            good.add(p[0])
    return good, seen
good, seen = health(sys.argv[1])
good_after, _ = health(sys.argv[2])
bad = (seen - good) - good_after             # not good before, and not put right by the take
edges = {}
for ln in sys.argv[3].splitlines():
    p = ln.split()
    if len(p) == 2:
        edges.setdefault(p[0], set()).add(p[1])
def leans(n, path):                          # the bad dependency it leans on, or None
    for d in sorted(edges.get(n, ())):
        if d in bad:
            return d
        if d in seen and d not in good_after and d not in path:   # through what ran here before and is not good now
            hit = leans(d, path | {d})
            if hit:
                return hit
    return None
for n in sorted(good):
    hit = leans(n, {n})
    if hit:
        print(n, hit)' "$1" "$2" "${deps}"
}
lost() {   # before after → every service that was good before and is not good now ("<name> gone" when it vanished)
  # A service gone from the running office AND from the compiled model, that the take itself retired, is a release.
  # When the model cannot be read, every vanished service counts. A service PRESENT after but not good, that was good
  # before only by leaning on one that is bad before and after (leaning), is not the take's to answer for — and is
  # said, on stderr, so the cycle's log names it. A service that VANISHED is judged as ever: a dead dependency leaves
  # its dependent created or exited, never gone.
  local n line model spared="" by off_pairs="" sw_off="" app
  model="$(model_services)" || model=""
  [ "${LOST_SPARE:-1}" = 0 ] || spared="$(leaning "$1" "$2")" || spared=""
  # OFF BY THE OWNER'S WORD (above the take): asked only when something good before is not good now, and only of a model
  # that can be read. It is spared in a rollback's report too, whatever LOST_SPARE says: «still not healthy» over an app
  # its owner switched off would be false.
  # (outside a take, recover's or a retry's, neither SWITCHED nor MODEL_START is set, so nothing can be spared: not asked)
  if [ -n "${model}" ] && [ -n "${SWITCHED:-}${MODEL_START:-}" ] \
     && [ -n "$(comm -23 <(good_names <<<"$1" | sort) <(good_names <<<"$2" | sort))" ]; then
    off_pairs="$(declared_off_services || true)"
    sw_off="$(awk '$2 == "off" {print $1}' <<<"${SWITCHED:-}")"
  fi
  printf '%s\n' "$1" | good_names | while read -r n; do
    line="$(printf '%s\n' "$2" | awk -v n="${n}" '$1 == n')"
    grep -qxF -- "${n}" <<<"$(good_names <<<"${line}")" && continue   # good now: nothing lost
    # …and switched by the OWNER, never by the take: switched off while the take ran, or already out of the compiled model
    # when it began (its render done, its containers still stopping). An app the state named off all along, which the
    # take's own change dropped from the model (a required provider: resolve()), is the take's (the third reading).
    app="$(awk -v n="${n}" '$2 == n {print $1; exit}' <<<"${off_pairs}")"
    if [ -n "${app}" ] && ! grep -qxF -- "${n}" <<<"${model}" \
       && { grep -qxF -- "${app}" <<<"${sw_off}" \
            || { [ -n "${MODEL_START:-}" ] && ! grep -qxF -- "${n}" <<<"${MODEL_START}"; }; }; then
      say "${n} — its app ${app} is declared off and the compiled model no longer declares it: not the take's to answer for" >&2
      logline "spared: ${n} — its app ${app} is declared off, and the compiled model no longer declares it"
      continue
    fi
    if [ -z "${line}" ]; then
      [ -n "${model}" ] && ! grep -qxF -- "${n}" <<<"${model}" && retired "${n}" && continue
      echo "${n} gone"
    elif ! grep -qxF -- "${n}" <<<"$(good_names <<<"${line}")"; then
      by="$(awk -v n="${n}" '$1 == n {print $2; exit}' <<<"${spared}")"
      if [ -n "${by}" ]; then
        say "${line} — not the take's: it leaned on ${by}, which was not good before and is not now" >&2
        logline "spared: ${line} — leaned on ${by}, not good before and not now"   # the file every notice points at
        continue
      fi
      echo "${line}"
    fi
  done
}
# The apps platform.state.yaml at <rev> DECLARES enabled, by reconcile.py's own rule (disposition(): `state:` when it is
# one of its words, else `enabled: true|false`, else disabled) — the office's own decisions, not the resolved set (a
# release that adds a base app changes that for every office, and is exactly what following is for). Fails when the
# file cannot be read or parsed. An office of the public line keeps platform.state.yaml as its own file, out of git (the
# public copy tracks only platform.state.default.yaml): no merge can change it — a target that adds it is refused before
# the merge (the `present` check) — so it is read from the checkout at either revision (DGO-2126 on the line; the same
# root on Examplex's office, DGO-2015, on hp-dgo — the two fixes met in «dgo-stable takes hp-dgo», and this is hp-dgo's,
# which also fails closed when git cannot read the index). A failed `git show` still fails the read (pipefail).
# own_state — 0 when platform.state.yaml is the office's own (not in the index: untracked), 1 when it is tracked, 2 when
# git cannot say (an index it cannot read): a caller fails closed on 2, as a read from the commit would.
own_state() {
  local t
  t="$(git -C "${REPO_ROOT}" ls-files -- platform.state.yaml)" || return 2
  [ -z "${t}" ]
}
declared_apps() {
  # The apps declared on as of commit $1. An office whose platform.state.yaml is untracked keeps it as its own (a
  # client's office on the public copy: the copy ignores the file and ships none), so no commit holds it and no merge
  # can change it: the office's own file is the answer for every revision, and none at all is no apps. Read from the
  # commit alone, it failed for both sides, and every take of main on Examplex's office ended «skipped» (38 cycles,
  # 2026-11-17 → 11-18; DGO-2015).
  local own; own_state; own=$?
  [ "${own}" = 2 ] && return 1
  { if [ "${own}" = 1 ]; then
      git show "$1:platform.state.yaml" 2>/dev/null
    elif [ -e "${REPO_ROOT}/platform.state.yaml" ]; then
      cat "${REPO_ROOT}/platform.state.yaml" 2>/dev/null
    else
      false   # no state file at all is no answer, never «no apps»: the line's own rule and test (DGO-2126)
    fi; } | enabled_apps
}
enabled_apps() { state_apps enabled; }   # a platform.state.yaml on stdin → the apps it declares on, one per line
off_apps() { state_apps off; }           # …→ the apps it declares OFF in so many words, never one it does not name
state_apps() {   # enabled|off — reconcile.py's disposition() on a platform.state.yaml on stdin; fails when it cannot be parsed
  # `state:` when it is one of its words, else `enabled: true|false`, else disabled by default. OFF is only what the
  # file SAYS (disabled, archived, enabled: false): an app it does not name may be a base app that runs by default.
  python3 -c 'import sys, yaml
mode = sys.argv[1]
apps =(yaml.safe_load(sys.stdin.read()) or {}).get("apps") or {}
for aid, e in sorted(apps.items()):
    e = e if isinstance(e, dict) else {}
    st = str(e.get("state") or "").strip().lower()
    said = st in ("enabled", "disabled", "archived")
    if not said:
        said = "enabled" in e
        st = ("enabled" if e.get("enabled") else "disabled") if said else "disabled"
    if (mode == "enabled" and st == "enabled") or (mode == "off" and said and st != "enabled"):
        print(aid)' "$1" 2>/dev/null
}
# SWITCHED DURING THE TAKE (the king's decision, 2026-11-20: issues/an-app-switched-during-a-take-is-counted-as-lost-…).
# A take snapshots its services when it starts and judges them after its run, and `bbox run` compiles the CHECKOUT's
# platform.state.yaml, while declared_apps reads git's. An app switched in the checkout in between was invisible: on
# vps1 a proof switched image-store off while the take of 113 ran, its two services counted as lost, and a good version
# was rolled back with a failure row for the owner. The owner's own switch on his console would do the same.
# - OFF BY THE OWNER'S WORD (lost(): declared_off_services). A lost service that the compiled model no longer declares,
#   of an app the checkout declares off in so many words NOW, is spared and named when the OWNER made it so:
#   - switched off while the take ran, or
#   - already out of the model when the take began (MODEL_START). `bbox apps disable` writes the state and renders,
#     then stops the containers one by one, so a baseline read in between sees them good (the second reader).
#   It is judged by what runs: a provider another enabled app requires stays compiled in and running (resolve()), and
#   one the state named off all along that the take's own change drops from the model is the take's (its third
#   reading). An app the file does not name is never «off»: a base app runs by default.
# - SWITCHED (the take's line): the checkout's apps when the take began (APPS_START) against each later read. An app
#   switched ON needs no spare: its services were in no baseline, and one that ran before for another reason is judged.
checkout_apps() {   # the apps the checkout's platform.state.yaml declares on now; fails when it is missing or unparsable
  [ -e "${REPO_ROOT}/platform.state.yaml" ] || return 1
  enabled_apps < "${REPO_ROOT}/platform.state.yaml"
}
switched_apps() {   # the apps declared on when the take began → "<app> on|off" for each switched since; fails unread
  local now; now="$(checkout_apps)" || return 1
  comm -13 <(sed '/^$/d' <<<"$1" | sort) <(sed '/^$/d' <<<"${now}" | sort) | sed 's/$/ on/'
  comm -23 <(sed '/^$/d' <<<"$1" | sort) <(sed '/^$/d' <<<"${now}" | sort) | sed 's/$/ off/'
}
app_services() {   # app… → "<app> <service>" for each service each declares, as the compiler reads them
  # The compiler's own `compose-services`: the compose file its app.json names, in any catalog root (apps/,
  # platform-base/, instances/), never a glob. A standalone quick-start file beside it (any-concurrency's) declares
  # n8n's own services, and a glob would have spared a broken n8n (the second reader). An app the catalog does not know
  # (a retired one its state still names) answers nothing, and never silences the others (its third reading).
  if [ -n "${DGO_FOLLOW_APP_SERVICES_CMD:-}" ]; then "${DGO_FOLLOW_APP_SERVICES_CMD}" "$@" || true; return 0; fi
  local a
  for a in "$@"; do
    ( cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py compose-services --app "${a}" 2>/dev/null ) \
      | sed "s/^/${a} /" || true
  done
  return 0
}
declared_off_services() {   # → "<app> <service>" for each app the checkout declares OFF now; fails when it cannot be read
  # (not lib.sh's off_services, which reads the resolved set for stop_off_apps: this one is the take's)
  local off
  [ -e "${REPO_ROOT}/platform.state.yaml" ] || return 1
  off="$(off_apps < "${REPO_ROOT}/platform.state.yaml")" || return 1
  [ -n "${off}" ] || return 0
  # shellcheck disable=SC2086 — one app id per word
  app_services ${off}
}
note_switched() {   # SWITCHED: "<app> on|off" for each app the checkout switched since APPS_START — the take's line
  # Added up: a later read that cannot be made, or that finds the switch undone, takes nothing back from an earlier one.
  local s
  [ "${APPS_START-?}" != "?" ] || return 0          # not in a take, or the checkout could not be read when it began
  s="$(switched_apps "${APPS_START}")" || return 0   # unreadable now: what an earlier read found stands
  SWITCHED="$(printf '%s\n%s\n' "${SWITCHED}" "${s}" | sed '/^$/d' | awk '!seen[$0]++')"
  [ -z "${SWITCHED}" ] || say "switched during the take: ${SWITCHED//$'\n'/, }"
}
busy_apps() {   # "<app>: <what it said>" for every enabled app whose own hooks/busy says it is in use right now
  # An app knows when recreating it would hurt someone (Meet: a call in progress) — bbox names none of them. A hook
  # that cannot answer is not busy.
  if [ -n "${DGO_FOLLOW_BUSY_CMD:-}" ]; then "${DGO_FOLLOW_BUSY_CMD}"; return; fi
  local root aid hook said cap=""
  command -v timeout >/dev/null 2>&1 && cap="timeout -k 5 30"   # a hook that hangs (an engine that does) answers "not busy"
  ( cd "${REPO_ROOT}" && python3 platform/manager/reconcile.py enabled-apps 2>/dev/null ) | while read -r root aid; do
    hook="${REPO_ROOT}/${root}/${aid}/hooks/busy"
    [ -n "${aid}" ] && [ -x "${hook}" ] || continue
    said="$(${cap} bash "${hook}" </dev/null 2>/dev/null)" && printf '%s: %s\n' "${aid}" "$(printf '%s' "${said}" | head -1)"
  done
}
when_idle_ids() {   # the enabled apps recreated only while idle (app.json "recreate": "when-idle"), one id per line
  if [ -n "${DGO_FOLLOW_WHEN_IDLE_CMD:-}" ]; then "${DGO_FOLLOW_WHEN_IDLE_CMD}"; return; fi
  ( cd "${REPO_ROOT}" && python3 platform/manager/when_idle.py apps 2>/dev/null ) | cut -f1
}
take_busy() {   # the busy apps that hold a WHOLE take back (Meet: a call). A «when-idle» app holds only its own running
  # containers, which the bring-up leaves alone while it is at work (lib.sh compose_when_idle_split, DGO-2129). Holding
  # the whole take for it would never take anything: the HP's agents work all day.
  local busy idle
  busy="$(busy_apps)"; [ -n "${busy}" ] || return 0
  idle="$(when_idle_ids)"
  if [ -z "${idle}" ]; then printf '%s\n' "${busy}"; return 0; fi
  awk -F': ' 'NR == FNR { w[$1] = 1; next } !($1 in w)' <(printf '%s\n' "${idle}") <(printf '%s\n' "${busy}")
}
held_retry() {   # what an `up` held because its app was at work (data/.held/<service>, lib.sh when_idle_held): brought up
  # again each cycle. dcx asks the app again and holds it once more while it is busy. When it is idle: the build the held
  # command had asked (the note says so), the app's backup, the recreate, then the sessions it cut are resumed (its
  # before/after-recreate hooks). A note is removed only by an `up` of it that succeeded.
  local d="${REPO_ROOT}/data/.held" f s declared list=""
  [ -d "${d}" ] || [ -n "$(st_get HELD_TOLD)" ] || return 0
  if [ -d "${d}" ]; then
    declared="$(model_services 2>/dev/null)" || { logline "held: the declared services cannot be read — the retry waits"; return 0; }
    for f in "${d}"/*; do
      [ -f "${f}" ] || continue
      s="$(basename "${f}")"
      if grep -qFx -- "${s}" <<<"${declared}"; then list="${list}${list:+ }${s}"; else rm -f "${f}"; fi   # retired since
    done
  fi
  # (nothing held now: only the rows of holds that ended are closed, below)
  if [ -n "${list}" ]; then
    say "held while their app was at work: ${list} — asked again"
    if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then
      "${DGO_FOLLOW_RUN_CMD}" held ${list}
    else
      # --wait: a recreate here is health-checked as a take's is; one that never gets healthy keeps its note, and says so
      # shellcheck disable=SC2086 — a list of service names
      "${REPO_ROOT}/scripts/dc" up -d --no-deps --wait --wait-timeout 300 ${list} \
        > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-held.log" 2>&1 \
        || logline "held: bringing up ${list} failed or did not get healthy (data/follow/run-*-held.log)"
    fi
  fi
  # Still held after hours means its app was never idle at a cycle: a session's job that never ends, a watcher left
  # running. That could hold it for good with nobody the wiser, so the office is told, once per hold, with what its
  # app says; whoever knows decides (BBOX_RECREATE_BUSY=1 brings it up now). DGO-2129's third reader. In a row of its own
  # (held:<office>:<service>): the office's one row is the take's, and the cycle's own «back to normal» would close it.
  local now since said key told keep="" age
  now="$(date -u +%s)"; told="$(st_get HELD_TOLD)"
  for s in ${list}; do
    f="${d}/${s}"
    [ -f "${f}" ] || continue
    since="$(cut -f1 "${f}")"; said="$(cut -f3 "${f}")"; key="${s}@${since// /_}"
    case " ${told} " in *" ${key} "*) keep="${keep} ${key}"; continue ;; esac
    # the note's own time, read the same way on GNU and BSD userlands (`date -d` is GNU's only)
    age="$(python3 -c 'import datetime, sys
t = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=datetime.timezone.utc)
print(int(float(sys.argv[2]) - t.timestamp()))' "${since}" "${now}" 2>/dev/null)" || age=0
    [ "${age:-0}" -ge "${DGO_FOLLOW_HELD_TELL_S:-21600}" ] || continue
    post_notice warning "שירות ממתין שעות לרגע שקט — ${OFFICE}" \
      "${s} has been held since ${since}: its app is at work (${said}). follow brings it up at the first quiet cycle; BBOX_RECREATE_BUSY=1 brings it up now, and cuts what runs there." \
      "held:${OFFICE}:${s}" || continue
    keep="${keep} ${key}"
  done
  # a told hold that ended closes its own row; one whose closing could not be posted is tried again next cycle
  local k
  for k in ${told}; do
    case " ${keep} " in *" ${k} "*) continue ;; esac
    s="${k%%@*}"
    if [ -f "${d}/${s}" ]; then keep="${keep} ${k}"; continue; fi   # held again since: its row closes when that hold ends
    post_notice info "שירות חזר לפעול — ${OFFICE}" "${s} is held no more: its app was idle at a cycle, and it was brought up." \
      "held:${OFFICE}:${s}" || keep="${keep} ${k}"
  done
  [ "${keep# }" = "${told}" ] || st_set HELD_TOLD "${keep# }"
}

office_disk() {   # admit | reclaim | free — the disk floor of a take (lib.sh disk_admit, disk_reclaim, disk_free_gb)
  if [ -n "${DGO_FOLLOW_DISK_CMD:-}" ]; then "${DGO_FOLLOW_DISK_CMD}" "$1"; return; fi
  case "$1" in
    admit)   BBOX_DISK_ENFORCE=1 disk_admit "follow ${FOLLOW}" 2>/dev/null ;;   # a take never starts on a short disk
    reclaim) disk_reclaim ;;
    free)    disk_free_gb ;;
  esac
}

office_heal() {   # a container left behind in a network namespace is recreated (lib.sh netns_rejoin) — never a stop
  # After a reboot the engine restores containers in parallel, and a `network_mode: container:<x>` start that comes
  # before x is up fails and is never retried: the HP's door (dgo-link) and dgo-carry stayed shut for 43 minutes after
  # the WSL restart of 2026-11-05, and nothing on any office ran netns_rejoin outside a `dcx up`. It reads state and
  # does nothing when nothing is stale, so it runs at the start of every cycle — following or not (DGO-1393).
  if [ -n "${DGO_FOLLOW_HEAL_CMD:-}" ]; then "${DGO_FOLLOW_HEAL_CMD}" || true; return 0; fi
  netns_rejoin || say "${cy}recreating a container left out of its network namespace failed — the next cycle tries again${c0}"
  return 0
}

room() {   # 0 when a take may build here; otherwise the cycle is put off, and the owner told once (DGO-1393: the HP's C:
  # at 100% on 2026-11-05) — asked inside take(), once nothing else holds the take back, so the `bbox run` of a take is
  # never the one refused half-way; and never told over a notice already open about something else (a conflict keeps
  # its row until it is cleared)
  office_disk admit && return 0
  [ -n "$(st_get NOTICE)" ] || tell "לא ניתן לעדכן: הדיסק כמעט מלא — ${OFFICE}" "Free space is under the floor of $(disk_floor_gb) GiB (BBOX_DISK_MIN_GB) even after the dangling images and the build cache were given back: no take builds here until space is freed. What holds it: ./bbox machine storage."
  finish skipped "disk: $(office_disk free) GiB free, under the floor of $(disk_floor_gb) GiB"
  return 1
}

# READY-MADE IMAGES (DGO-2123; the design: research_notes/CICD 2026-11/images.md). A take BUILDS what changed: vps1
# built batch 98 for ~8 minutes at load 26 on its two cores. Where this office runs the image store's mirror
# (apps/image-store) AND opted in — DGO_FOLLOW_IMAGES=1 in its .env: one office first, measured, then the rest — the
# take PULLS the images the line's proof named for its very target (refs/images/<line>), tags each under the name its
# compose file gives it, builds the other first-party images itself (an unchanged one is a cache hit), and runs `bbox
# run` without --build (BBOX_PREBUILT): `--build` would build again what was just pulled. Any step that fails, and the
# take builds as it always did — never half pulled: a build overwrites whatever tag a pull had set.
# AN IMAGE STANDS IN FOR THIS OFFICE'S OWN BUILD ONLY WHERE IT IS THAT BUILD (images_choose; the reader, DGO-2123):
# a service of this office runs it; that service builds from the image's own directory with its own Dockerfile and
# declares nothing else (build args, a target or a second context make another image: project-pln's Hebrew build,
# app-management's compose version); and this office's tree there is the target's — its own commits or edits in that
# directory are what it runs, not the line's. Every other image is built here, with the rest.
IMAGES_ENGINE="${DGO_FOLLOW_ENGINE_CMD:-docker}"
images_config() {   # the office's compiled compose config as JSON: what each service runs and builds, and from what
  if [ -n "${DGO_FOLLOW_CONFIG_CMD:-}" ]; then "${DGO_FOLLOW_CONFIG_CMD}"; return; fi
  ( cd "${REPO_ROOT}" && dcx config --format json 2>/dev/null )
}
images_choose() {   # stdin: «id digest name dir» per named image; $1 the target, $2 the config's file, $3 the tag →
  # «PULL id digest name», «WHY id <why it is built here>», then «OTHERS <every service that builds here>»; exit 3 when
  # the config cannot be read
  TGT="$1" CFG="$2" TAG="$3" ROOT="${REPO_ROOT}" python3 -c '
import json, os, subprocess, sys
try:
    with open(os.environ["CFG"], encoding="utf-8") as f:
        services = json.load(f).get("services") or {}
except (OSError, ValueError, AttributeError):
    sys.exit(3)
root, tgt, tag = os.environ["ROOT"], os.environ["TGT"], os.environ["TAG"]
builds = {s: v for s, v in services.items() if isinstance(v, dict) and v.get("build")}

def plain(build, d):
    if isinstance(build, str):
        build = {"context": build}
    if not isinstance(build, dict):
        return "its build here cannot be read"
    extra = sorted(k for k in build if k not in ("context", "dockerfile"))
    if extra:
        return "its build here declares " + ", ".join(extra)
    if os.path.realpath(os.path.join(root, str(build.get("context") or "."))) != os.path.realpath(os.path.join(root, d)):
        return "it builds here from %s, not %s" % (build.get("context"), d)
    if str(build.get("dockerfile") or "Dockerfile") not in ("Dockerfile", "./Dockerfile"):
        return "it builds here %s, not its Dockerfile" % build.get("dockerfile")
    return None

def git(*args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)

pulled = set()
for line in sys.stdin.read().splitlines():
    parts = line.split()
    if len(parts) != 4:
        continue
    i, digest, name, d = parts
    users = sorted(s for s, v in builds.items() if v.get("image") == "%s:%s" % (name, tag))
    why = "no service of this office runs %s:%s" % (name, tag) if not users else \
        next((w for w in (plain(builds[s]["build"], d) for s in users) if w), None)
    if not why and (git("diff", "--quiet", tgt, "--", d).returncode != 0
                    or git("ls-files", "--others", "--exclude-standard", "--", d).stdout.strip()):
        why = "this office holds %s other than the target does (its own commits or edits there)" % d
    if why:
        print("WHY", i, why)
        continue
    print("PULL", i, digest, name)
    pulled.update(users)
print("OTHERS", " ".join(sorted(s for s in builds if s not in pulled)))'
}
images_build() {   # the services that were not pulled, built as compose builds them
  if [ -n "${DGO_FOLLOW_BUILD_CMD:-}" ]; then "${DGO_FOLLOW_BUILD_CMD}" "$@"; return; fi
  ( cd "${REPO_ROOT}" && dcx build "$@" )
}
images_pull() {   # $1 the target → 0: its images pulled and the rest built, so the take runs with BBOX_PREBUILT; 1: as today
  local tgt="$1" lines port tag id digest name pulled="" others t0 cfg choice pulls whys w
  [ "$(read_env DGO_FOLLOW_IMAGES)" = 1 ] || return 1
  t0="$(date +%s)"
  if ! "${IMAGES_ENGINE}" ps -q --filter "name=^image-store-${DN}\$" --filter status=running 2>/dev/null | grep -q .; then
    say "images: this office runs no image store — the take builds"; return 1
  fi
  if ! git -C "${REPO_ROOT}" fetch -q "${SRC}" "+refs/images/${FOLLOW}:refs/follow/images/${FOLLOW}" 2>/dev/null; then
    say "images: refs/images/${FOLLOW} could not be read — the take builds"; return 1
  fi
  # only the images the proof named for THIS target: a list of another version's is no answer for this one
  if ! lines="$(git -C "${REPO_ROOT}" show "refs/follow/images/${FOLLOW}:images.json" 2>/dev/null | TGT="${tgt}" python3 -c '
import json, os, sys
d = json.load(sys.stdin)
if d.get("green") != os.environ["TGT"]:
    sys.exit(3)
for i, e in sorted((d.get("images") or {}).items()):
    if isinstance(e, dict) and str(e.get("digest") or "").startswith("sha256:") and e.get("name") and e.get("dir"):
        print(i, e["digest"], e["name"], e["dir"])')" || [ -z "${lines}" ]; then
    say "images: the line named no images for $(short "${tgt}") — the take builds"; return 1
  fi
  port="$(read_env REGISTRY_HOST_PORT)"; port="${port:-5055}"
  tag="$(read_env IMAGE_TAG)"; tag="${tag:-latest}"
  cfg="$(mktemp)" || { say "images: no temporary file for this office's compose config — the take builds"; return 1; }
  if ! images_config > "${cfg}" 2>/dev/null || ! choice="$(printf '%s\n' "${lines}" | images_choose "${tgt}" "${cfg}" "${tag}")"; then
    rm -f "${cfg}"; say "images: this office's compose config could not be read — the take builds"; return 1
  fi
  rm -f "${cfg}"
  whys="$(sed -n 's/^WHY \([^ ]*\) /\1: /p' <<< "${choice}")"
  [ -z "${whys}" ] || while IFS= read -r w; do say "images: built here, not pulled — ${w}"; done <<< "${whys}"
  pulls="$(sed -n 's/^PULL //p' <<< "${choice}")"
  others="$(sed -n 's/^OTHERS *//p' <<< "${choice}")"
  if [ -z "${pulls}" ]; then
    say "images: none of the line's images stands in for this office's own build — the take builds"; return 1
  fi
  while read -r id digest name; do
    [ -n "${id}" ] || continue
    # through the mirror on this machine's loopback: the engine fetches only the layers it lacks, the mirror only the
    # blobs IT lacks, over the link
    if ! "${IMAGES_ENGINE}" pull -q "127.0.0.1:${port}/${id}@${digest}" >/dev/null 2>&1 \
       || ! "${IMAGES_ENGINE}" tag "127.0.0.1:${port}/${id}@${digest}" "${name}:${tag}" >/dev/null 2>&1; then
      say "images: ${id} (${digest:0:19}…) could not be pulled through the mirror — the take builds"; return 1
    fi
    pulled="${pulled}${pulled:+ }${id}"
  done <<< "${pulls}"
  # shellcheck disable=SC2086 — service names
  if [ -n "${others}" ] && ! images_build ${others}; then
    say "images: what was not pulled did not build — the take builds"; return 1
  fi
  say "images: pulled ${pulled}; built ${others:-nothing else}; $(( $(date +%s) - t0 ))s — the take runs without --build"
  return 0
}

office_run() {   # bbox run, logged; the exit code is the run's
  # A rollback goes back ON PURPOSE: the deploy ledger (scripts/lib.sh, deploy_ledger_gate) refuses a bring-up that
  # drops what runs here unless the command says so — without it the checkout was back at the commit before while the
  # containers stayed on the failed take, and the owner was told the office was back (the second reader, r030-205).
  local back=0; [ "$1" = rollback ] && back=1
  # …and is never refused for the disk (disk_admit): going back is how the office stays what it was
  local admitted="${BBOX_DISK_ADMITTED:-}"; [ "${back}" = 1 ] && admitted=1
  if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then BBOX_ALLOW_ROLLBACK="${back}" BBOX_DISK_ADMITTED="${admitted}" "${DGO_FOLLOW_RUN_CMD}" "$1"; return; fi
  # A take is judged by what follows it (settle, lost: the services this office runs), never by the run's fatal
  # exit (DGO-995): a take whose image did not build stays and is rebuilt below (DGO-1356) — so the old exit
  BBOX_RUN_FATAL_EXIT=0 BBOX_ALLOW_ROLLBACK="${back}" BBOX_DISK_ADMITTED="${admitted}" "${REPO_ROOT}/bbox" run > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-$1.log" 2>&1
}

old_images() {   # the services running an image older than their own build files (lib.sh stale_images), names only
  if [ -n "${DGO_FOLLOW_OLD_IMAGES_CMD:-}" ]; then "${DGO_FOLLOW_OLD_IMAGES_CMD}"; return; fi
  # Asked of the checkout's lib.sh in a shell of its own: after a take that is the MERGED code, while the lib.sh this
  # cycle sourced at its start is the one from before the merge. vps1's take of 55 (2026-11-13, DGO-1838) ran 45's
  # stale_images, which still listed a service the office no longer declares (chat), and «no such service» failed the
  # whole rebuild — the fix was already in 55 (DGO-1848). The rebuild itself is a fresh `bbox run`, so it already ran
  # the new code. A follow.sh therefore reads a NEWER lib.sh's stale_image_services: its output (service names, space
  # separated) is a contract across versions. A merged lib.sh that cannot answer (it fails to source, or lost the
  # function) is logged, and the cycle's own one answers — never a silent «nothing is stale» (the second reader).
  if [ -f "${REPO_ROOT}/scripts/lib.sh" ]; then
    local out rc=0
    out="$(cd "${REPO_ROOT}" && bash -c '. scripts/lib.sh >/dev/null 2>&1
      declare -F stale_image_services >/dev/null || exit 3
      stale_image_services')" || rc=$?
    if [ "${rc}" = 0 ]; then
      [ -z "${out}" ] || printf '%s\n' "${out}"
      return 0
    fi
    logline "old_images: the merged scripts/lib.sh could not list stale images (exit ${rc}); the cycle's own lib.sh answered"
  fi
  stale_image_services
}

office_rebuild() {   # bbox run of exactly these services, logged: it builds what it brings up (--build, or the serial build)
  # its exit is the run's, fatal included (DGO-995): a build that fails here is now told, as the caller always meant
  if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then "${DGO_FOLLOW_RUN_CMD}" rebuild "$@"; return; fi
  "${REPO_ROOT}/bbox" run "$@" > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-rebuild.log" 2>&1
}

# ── code mounted as a FOLDER (issues/a-service-that-mounts-its-code-as-a-folder-keeps-running-the-old-code-…) ──────
# A service that mounts its code as a read-only folder keeps running what it loaded at start: the folder shows the
# take's files, nothing in its build or definition moved, so the bring-up leaves it be (lib.sh filemount_refresh
# follows FILE mounts only). Measured 2026-11-13 (DGO-1865): android-emulator mounts ./server:/app:ro, its 0.2.1
# changed only governor.py, which server.py imports once — and the Dell's phone would have kept the old one. Matched on
# the MERGE's own diff, never on mtimes: a merge rewrites files whose text did not change. Read-only only: a service
# writes a read-write folder itself, and its code is not read from there.
folder_mounts() {   # "<service> <started epoch> <path under the checkout>" per read-only folder bind of a RUNNING container
  # of this office — listed as filemount_refresh lists them (`dc ps -q`: COMPOSE_PROJECT_NAME is empty on a checkout with a
  # Latin folder name, the Dell's, and a label filter on it matched nothing — the first version's reader, F1)
  local json ids
  if [ -n "${DGO_FOLLOW_INSPECT_CMD:-}" ]; then json="$("${DGO_FOLLOW_INSPECT_CMD}")" || return 1
  else
    ids="$(_dcx_run ps -q 2>/dev/null)" || return 1
    [ -n "${ids}" ] || return 0
    # shellcheck disable=SC2086 — a list of container ids
    json="$(docker inspect ${ids} 2>/dev/null)" || return 1
  fi
  printf '%s' "${json}" | python3 -c '
import datetime, json, os, sys
roots = {os.path.realpath(r) for r in sys.argv[1:] if r}
rows = json.load(sys.stdin)
for c in rows:
    st = c.get("State") or {}
    if not st.get("Running"):
        continue
    svc = ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service", "")
    try:
        started = int(datetime.datetime.fromisoformat(st.get("StartedAt", "")[:19]).replace(
            tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        continue
    for m in c.get("Mounts") or []:
        src = m.get("Source") or ""
        if not svc or m.get("Type") != "bind" or m.get("RW") or not os.path.isdir(src):
            continue
        real = os.path.realpath(src)
        for r in roots:
            if real.startswith(r + os.sep):
                print(svc, started, real[len(r) + 1:])
                break' "${REPO_ROOT}" "$(cd "${REPO_ROOT}" 2>/dev/null && pwd -P)"
}
folder_app() {   # <path under the checkout> → the app it belongs to (<layer dir>/<app>/…), or nothing
  case "$1" in apps/?*|platform-base/?*) printf '%s' "$1" | cut -d/ -f2 ;; esac   # the app's own dir too (`.:/app:ro`)
}
folders_changed() {   # <before> <merged> <since epoch> → "<service> <app>" per declared service, not this cycle's own
  # container, running since before <since>, whose read-only folder mount holds a file the merge changed. Fails (logged)
  # when the merge's diff or the containers cannot be read: never a silent «nothing changed» (F6).
  local changed mounts declared self s started rel p out=""
  changed="$(git diff --no-renames --name-only "$1" "$2" 2>/dev/null)" \
    || { logline "folders: git diff $(short "$1")..$(short "$2") failed — no folder-mounted service checked"; return 1; }
  [ -n "${changed}" ] || return 0
  mounts="$(folder_mounts 2>/dev/null)" || { logline "folders: the containers' mounts cannot be read — none checked"; return 1; }
  [ -n "${mounts}" ] || return 0
  declared="$(model_services 2>/dev/null)" || { logline "folders: the declared services cannot be read — none checked"; return 1; }
  self="$(bbox_self_service 2>/dev/null || true)"
  while read -r s started rel; do
    [ -n "${rel}" ] || continue
    grep -qFx -- "${s}" <<<"${declared}" || continue     # a retired service's container: `up <it>` fails them all (F2)
    [ "${s}" != "${self}" ] || continue
    [ "${started:-0}" -lt "$3" ] || continue             # started after the bring-up: it already runs the take's code
    case " ${out} " in *" ${s} "*) continue ;; esac
    while IFS= read -r p; do
      case "${p}" in "${rel}"/*) out="${out:+${out} }${s}"; printf '%s %s\n' "${s}" "$(folder_app "${rel}")"; break ;; esac
    done <<<"${changed}"
  done <<<"${mounts}"
}
office_recreate() {   # recreate exactly these services: no build, no dependency
  if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then "${DGO_FOLLOW_RUN_CMD}" recreate "$@"; return; fi
  "${REPO_ROOT}/scripts/dc" up -d --no-deps --force-recreate "$@" > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-recreate.log" 2>&1
}
busy_holds() {   # <service> <folder's app> <busy apps, one per line> → 0 when one of them is this service's
  local b
  while IFS= read -r b; do
    [ -n "${b}" ] || continue
    [ "${b}" = "$2" ] || [ "${b}" = "$1" ] || [ "${1#"${b}"-}" != "$1" ] && return 0
  done <<<"$3"
  return 1
}
folders_refresh() {   # <since epoch> "<service> <app>"… → recreates them, a busy app's left for later (F4); what is left
  # or failed waits in FOLDERS_PENDING for the next cycle (F5), which finds HEAD at the target and would never ask again.
  # 0: nothing failed (some may wait for a busy app); 1: a recreate failed (said).
  # An entry is "<service>:<app>" in FOLDERS_PENDING, so a retry asks the same app whether it is busy.
  local since="$1" busy go="" names="" held="" s a pending rc=0; shift
  busy="$(busy_apps | cut -d: -f1)"
  for s in "$@"; do
    a="${s#* }"; s="${s%% *}"; [ "${a}" != "${s}" ] || a=""
    # busy when the app the folder belongs to is, or the service's own app: no container carries its app, so it is the
    # service's name or its prefix (vps1, 2026-11-13: dgo-extend mounts apps/computers; meet-jibri, meet-start are meet's)
    if busy_holds "${s}" "${a}" "${busy}"; then held="${held}${held:+ }${s}:${a}"
    else go="${go}${go:+ }${s}:${a}"; names="${names}${names:+ }${s}"; fi
  done
  [ -z "${held}" ] || say "code mounted as a folder changed under ${held} — its app is busy, recreated by a later cycle"
  pending="${held}"
  if [ -n "${names}" ]; then
    say "code mounted as a folder changed under ${names} — recreating exactly these"
    # shellcheck disable=SC2086 — a list of service names
    if ! office_recreate ${names}; then rc=1; logline "folders: recreating ${names} failed"; pending="${pending}${pending:+ }${go}"; fi
  fi
  # …added to what an EARLIER take left, never over it (a newer take's diff rarely touches that folder again): the older
  # `since` kept, an entry this call handled replaced by its outcome
  local old old_since e
  old="$(st_get FOLDERS_PENDING)"
  if [ -n "${old}" ]; then
    old_since="${old%% *}"; [ "${old_since}" -lt "${since}" ] 2>/dev/null && since="${old_since}"
    for e in ${old#* }; do
      # this call saw it (recreated, failed or held): its outcome is already in pending, or it is done
      case " ${names} ${held} " in *" ${e%%:*} "*|*" ${e%%:*}:"*) continue ;; esac
      pending="${pending}${pending:+ }${e}"
    done
  fi
  if [ -n "${pending}" ]; then st_set FOLDERS_PENDING "${since} ${pending}"; else st_set FOLDERS_PENDING ""; fi
  return "${rc}"
}
folders_retry() {   # a cycle after a take: what folders_refresh left (busy, or failed) — the ones still running from before
  local p since s started mounts names=""
  local -a live=()
  p="$(st_get FOLDERS_PENDING)"; [ -n "${p}" ] || return 0
  since="${p%% *}"
  mounts="$(folder_mounts 2>/dev/null)" || { logline "folders: the containers' mounts cannot be read — the retry waits"; return 0; }
  for s in ${p#* }; do
    started="$(awk -v s="${s%%:*}" '$1 == s {print $2; exit}' <<<"${mounts}")"
    [ -n "${started}" ] && [ "${started}" -lt "${since}" ] || continue   # gone, or recreated since: it has the new code
    live+=("${s%%:*} ${s#*:}"); names="${names}${names:+ }${s%%:*}"
  done
  if [ "${#live[@]}" = 0 ]; then st_set FOLDERS_PENDING ""; return 0; fi
  # the first time the merged code runs in them, so judged as the take judged its own (F3): the services before and after
  local before after bad=""
  before="$(settle)" || { logline "folders: the services cannot be read — the retry waits"; return 0; }
  folders_refresh "${since}" "${live[@]}" \
    || tell_svc "שירות רץ על קוד ישן אחרי עדכון — ${OFFICE}" "${names} mount their code as a folder the last take changed, and recreating them failed again (data/follow/run-*-recreate.log): they run the code from before it until recreated." folders ${names}
  if after="$(settle)"; then bad="$(lost "${before}" "${after}")"; else bad="the services cannot be read"; fi
  # the services the loss names — or, when the services could not be read at all, the ones just recreated (never the
  # first word of that sentence: its second reader)
  local fell="${names}"; [ "${bad}" = "the services cannot be read" ] || fell="$(awk '{print $1}' <<<"${bad}")"
  # shellcheck disable=SC2086 — the names, one word each
  [ -z "${bad}" ] || tell_svc "שירות נפל אחרי עדכון — ${OFFICE}" "Recreating ${names}, whose code is mounted as a folder the last take changed, left: ${bad//$'\n'/, }. A session must look." fell ${fell}
  return 0
}

# ── the host timer ────────────────────────────────────────────────────────────────────────────────
install_timer() {
  local sudo="" dir=/etc/systemd/system owner svc tim hsvc htim t
  # Inside a container (an agent's `./bbox run`, a follow cycle) the host's timer is not this run's to install: an
  # office operated only from containers enables the `follow-runner` app instead (platform-base/follow-runner, r030-205).
  if [ -f /.dockerenv ]; then
    # …said, though, when that means nothing follows here at all
    if [ -n "${FOLLOW}" ] && ! grep -q . <<<"$(docker ps -q --filter "name=^follow-runner-${DN}\$" 2>/dev/null)"; then
      say "${cy}DGO_FOLLOW=${FOLLOW} is declared, but this bbox runs in a container and no follow-runner app runs here — nothing follows it: \`bbox apps enable follow-runner\` (platform-base/follow-runner)${c0}"
    fi
    return 0
  fi
  if ! { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }; then
    [ -z "${FOLLOW}" ] || say "${cy}DGO_FOLLOW=${FOLLOW} is declared, but this host has no systemd — this office does not follow it${c0}"
    return 0
  fi
  if [ "$(id -u)" != 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then sudo="sudo -n"
    else
      [ -z "${FOLLOW}" ] || say "${cy}DGO_FOLLOW=${FOLLOW} is declared, but installing its timer needs root or passwordless sudo — this office does not follow it${c0}"
      return 0
    fi
  fi
  # Installed whether or not the office follows: every cycle first recreates what a reboot left out of a shared network
  # namespace (office_heal), and only then, where DGO_FOLLOW is declared, follows (DGO-1393).
  owner="$(stat -c %U "${REPO_ROOT}" 2>/dev/null)" || owner=root
  # TimeoutStartSec above the heavy slot's own 3-hour wait, so a run that queued behind a build is not killed mid-take.
  # WorkingDirectory=-: systemd strips a value's trailing space, and a checkout's path may end in one (the MacBook's
  # does, and its engine's guest runs this): a directory it then cannot find is not fatal — bbox finds its own root.
  svc="$(printf '%s\n' '[Unit]' \
    "Description=DGO follow: heal what a reboot left behind$([ -n "${FOLLOW}" ] && echo ", and take ${FOLLOW} into ${BRANCH} when its gates are green") (scripts/follow.sh)" \
    'After=docker.service network-online.target' 'Wants=network-online.target' '' \
    '[Service]' 'Type=oneshot' "User=${owner}" "WorkingDirectory=-${REPO_ROOT}" \
    "ExecStart=\"${REPO_ROOT}/bbox\" follow" 'Nice=10' 'TimeoutStartSec=6h')"
  tim="$(printf '%s\n' '[Unit]' "Description=DGO follow, every 30 minutes (scripts/follow.sh)" '' \
    '[Timer]' 'OnBootSec=15min' 'OnUnitInactiveSec=30min' 'RandomizedDelaySec=5min' '' \
    '[Install]' 'WantedBy=timers.target')"
  # …and the heal on its own, soon after a boot. The follow timer waits 15 minutes so that a booting host is not
  # loaded with a take, and the door waited with it: the HP's dgo-link waited 45 minutes on 2026-11-05. The heal
  # only reads state when nothing is stale, so it runs 3 and 8 minutes after a boot. At 3 minutes the engine may
  # still be restoring containers; a recreate that could not yet join its namespace's owner is put right at 8. A heal
  # gets 3 minutes: with systemd's 90 s to stop it, a hung one has ended before 8 minutes, a trigger systemd drops while
  # the service still runs, and long before the first cycle, which leaves at once while a heal holds the lock.
  hsvc="$(printf '%s\n' '[Unit]' \
    'Description=DGO heal: recreate what a reboot left out of a shared network namespace (scripts/follow.sh heal)' \
    'After=docker.service' '' \
    '[Service]' 'Type=oneshot' "User=${owner}" "WorkingDirectory=-${REPO_ROOT}" \
    "ExecStart=\"${REPO_ROOT}/bbox\" follow heal" 'Nice=10' 'TimeoutStartSec=3min')"
  htim="$(printf '%s\n' '[Unit]' 'Description=DGO heal, 3 and 8 minutes after a boot (scripts/follow.sh heal)' '' \
    '[Timer]' 'OnBootSec=3min' 'OnBootSec=8min' '' \
    '[Install]' 'WantedBy=timers.target')"
  if [ "$(cat "${dir}/${UNIT}.service" 2>/dev/null)" != "${svc}" ] || [ "$(cat "${dir}/${UNIT}.timer" 2>/dev/null)" != "${tim}" ] \
     || [ "$(cat "${dir}/${UNIT}-heal.service" 2>/dev/null)" != "${hsvc}" ] || [ "$(cat "${dir}/${UNIT}-heal.timer" 2>/dev/null)" != "${htim}" ]; then
    printf '%s\n' "${svc}" | ${sudo} tee "${dir}/${UNIT}.service" >/dev/null \
      && printf '%s\n' "${tim}" | ${sudo} tee "${dir}/${UNIT}.timer" >/dev/null \
      && printf '%s\n' "${hsvc}" | ${sudo} tee "${dir}/${UNIT}-heal.service" >/dev/null \
      && printf '%s\n' "${htim}" | ${sudo} tee "${dir}/${UNIT}-heal.timer" >/dev/null \
      && ${sudo} systemctl daemon-reload || { say "${cy}could not write the follow timer into ${dir}${c0}"; return 1; }
    say "follow timer installed: $([ -n "${FOLLOW}" ] && echo "${FOLLOW} → ${BRANCH}" || echo "heal only (DGO_FOLLOW is empty)"), every 30 minutes, and the heal 3 and 8 minutes after a boot, as ${owner}"
  fi
  for t in "${UNIT}" "${UNIT}-heal"; do
    ${sudo} systemctl is-enabled --quiet "${t}.timer" 2>/dev/null && ${sudo} systemctl is-active --quiet "${t}.timer" \
      || ${sudo} systemctl enable --now "${t}.timer" >/dev/null 2>&1 \
      || { say "${cy}could not enable ${t}.timer${c0}"; return 1; }
  done
}

status() {
  local behind="?" timer="not installed"
  say "declared: DGO_FOLLOW=${FOLLOW:-<empty: not following>}  DGO_BRANCH=${BRANCH:-<empty>}  gates: ${GATES}${VIA:+  via: the git app of $(via_names)}"
  if [ -n "${FOLLOW}" ] && git rev-parse -q --verify "refs/remotes/origin/${FOLLOW}" >/dev/null; then
    behind="$(git rev-list --count "HEAD..origin/${FOLLOW}")"
  fi
  say "HEAD $(short HEAD) on $(git rev-parse --abbrev-ref HEAD) — ${behind} commit(s) of origin/${FOLLOW:-?} not in it (as of the last fetch)"
  command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "${UNIT}.timer" 2>/dev/null \
    && timer="active, next: $(systemctl show -p NextElapseUSecRealtime --value "${UNIT}.timer" 2>/dev/null)"
  # an office operated from containers runs its cycles from the `follow-runner` app instead (r030-205)
  docker ps -q --filter "name=^follow-runner-${DN}\$" 2>/dev/null | grep -q . \
    && timer="${timer}; the follow-runner app runs (follow-runner-${DN})"
  say "timer: ${timer}"
  say "last cycle: $(st_get LAST_AT) $(st_get LAST_RESULT) — $(st_get LAST_DETAIL)"
  [ -z "$(st_get LAST_VIA)" ] || say "last fetched through the git app of $(st_get LAST_VIA)"
  [ -z "$(st_get TAKING)" ] || say "a take is open: $(st_get TAKING) (merged: $(st_get MERGED))"
  [ -z "$(st_get FAILED_TARGET)" ] || say "not taken again until a newer one is green$([ -z "$(st_get FAILED_HEAD)" ] || printf ' or %s moves past %s (a conflict)' "${BRANCH}" "$(short "$(st_get FAILED_HEAD)")"): $(short "$(st_get FAILED_TARGET)") ($(st_get FAILED_AT))"
}

finish() {   # result detail — the cycle's one line, in the state and the log
  local now since; now="$(date +%s)"
  [ "${DRY}" = 1 ] && { say "$1: $2"; return 0; }
  st_set LAST_AT "$(date -u '+%F %T UTC')" LAST_RESULT "$1" LAST_DETAIL "$2"
  logline "$1 $2"
  case "$1" in skipped|current|waiting) ;; *) say "$1: $2" ;; esac
  case "$1" in
    current|took) st_set CURRENT_EPOCH "${now}" ;;
    skipped)
      # A cycle that is only ever put off (the slot, the load, a fetch or a gate run that cannot be read) is how an
      # office falls behind without a word: after a day of it the owner is told — unless a row about a real failure
      # is already open (it stays the one he reads), and in a text that does not change per cycle.
      since="$(st_get CURRENT_EPOCH)"
      [ -n "${since}" ] || { st_set CURRENT_EPOCH "${now}"; since="${now}"; }
      [ $((now - since)) -lt "${DGO_FOLLOW_STALE_S:-86400}" ] || [ -n "$(st_get NOTICE)" ] \
        || tell "המשרד לא התעדכן מ-${FOLLOW} יותר מיממה — ${OFFICE}" "Since $(date -u -d "@${since}" '+%F %T UTC' 2>/dev/null || echo "${since}"), every follow cycle was put off. The last reason is in \`bbox follow status\` and data/follow/log." ;;
  esac
}

# ── a take: one ref into the office branch, verified or undone ─────────────────────────────────────
moved_on_top() {   # target — the take stays open (sticky) until a session clears it; ONE text wherever it is found
  tell "עדכון נעצר: הענף זז בזמן העדכון — ${OFFICE}" "The take of $(short "$1") into ${BRANCH} was not finished: a commit landed on top of it meanwhile, which nothing checked, so nothing was pushed or rolled back. A session must check ${BRANCH}, then run \`bbox follow clear\`."
  finish blocked "HEAD moved on top of the open take of $(short "$1")"
}
reset_keep() {   # <commit> — `git reset --keep`, and what it rewrote stays the checkout owner's (no git hook runs on a
  # reset, and this cycle runs as root: scripts/checkout-owner.sh, DGO-1324)
  local before; before="$(git rev-parse HEAD)" || return 1
  git reset -q --keep "$1" || return 1
  git diff --name-only --no-renames -z "$1" "${before}" 2>/dev/null \
    | bash "${REPO_ROOT}/scripts/checkout-owner.sh" restore 2>/dev/null || true
}
merge_abort() {   # `git merge --abort`, and what the merge and the abort wrote stays the owner's (no hook runs on either:
  # the merge failed, and an abort is a reset). HEAD..MERGE_HEAD is a superset of what they touched.
  local touched; touched="$(git diff --name-only --no-renames -z HEAD MERGE_HEAD 2>/dev/null | base64 -w0)"
  git merge --abort || return 1
  printf '%s' "${touched}" | base64 -d | bash "${REPO_ROOT}/scripts/checkout-owner.sh" restore 2>/dev/null || true
}
rollback() {   # prev merged target why — back to the commit before the take, which was never pushed
  local prev="$1" merged="$2" tgt="$3" why="$4" rc=0 still
  st_set WHY "${why}"              # a refused rollback is retried by the next cycle, and says the same
  if [ "$(git rev-parse HEAD)" != "${merged}" ]; then moved_on_top "${tgt}"; return 1; fi
  if ! reset_keep "${prev}" 2>/dev/null; then
    tell "עדכון נכשל ולא חזר אחורה — ${OFFICE}" "Taking $(short "${tgt}") into ${BRANCH} left the office unhealthy (${why}), and going back to $(short "${prev}") was refused by git (local changes in the files it moves). Each cycle tries again; a session can look at \`git status\`."
    finish failed "$(short "${tgt}") unhealthy, and the rollback was refused"; return 1
  fi
  st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
  office_run rollback || rc=$?
  TAKE_PREV="" TAKE_MERGED=""   # back on prev: nothing the take did is "retired" any more
  # a REPORT of what is still down, not a verdict: nothing is spared here — «healthy again» must never be said over a
  # service that ran before and is down now, whatever it leans on (the second reader, 2026-11-11)
  still="$(settle)" && still="$(LOST_SPARE=0 lost "$(st_get BEFORE | tr ';' '\n')" "${still}")" || still="the services cannot be read"
  st_set TAKING "" MERGED "" BEFORE "" WHY ""
  tell "עדכון ${FOLLOW} נכשל והוחזר — ${OFFICE}" "$(short "${tgt}") left the office unhealthy (${why}), so ${BRANCH} is back at $(short "${prev}")$( [ -z "${still}" ] && [ "${rc}" = 0 ] && echo ', healthy again' || echo "; still not healthy: ${still//$'\n'/, }${still:+ }(bbox run exit ${rc})"). It is not taken again until a newer one is green. Logs: data/follow/."
  finish failed "$(short "${tgt}") unhealthy, rolled back to $(short "${prev}")"
  return 1
}

# A conflicted path the office never changed itself. Its version HERE is a version origin/DGO_FOLLOW itself had at some
# point: it came in by CONTENT (a cherry-pick, the release line carrying an office's branch), not by a merge, so the merge
# base never moved and every later change to that file conflicts again (vps1-dgo, 2026-11-03: carried into dgo-stable by
# content, then add/add on scripts/follow.sh at the next take). Such a path holds no change of the office's own, so
# DGO_FOLLOW's version wins; a path the office DID change — a blob dgo-stable never had — stops the take as before.
carried() {   # path target → 0 when HEAD's version of the path (mode and blob) is one the target's side had SINCE the base
  # Since the merge base, and up to the target only: content carried FROM an office lands on DGO_FOLLOW after the base,
  # while an office that reverted a file to an OLD dgo-stable version on purpose holds a version from before it — its
  # own change, which must stop the take (the second reader). The office's desired state is never "carried": dgo-stable
  # has held other offices' platform.state.yaml, and this office's own must not be swapped for one.
  local ours base c
  [ "$1" = platform.state.yaml ] && return 1
  ours="$(git --literal-pathspecs ls-tree HEAD -- "$1" | cut -f1 | awk '{print $1, $3}')"
  [ -n "${ours}" ] || return 1                           # gone here: the office deleted it — its own change
  base="$(git merge-base HEAD "$2")" || return 1          # no shared history: nothing was carried
  # --full-history: every commit since the base that touched the path, on every side of every merge. git's default
  # simplification follows only the parent a merge equals for the path, so the commit that held the office's version
  # vanishes when dgo-stable takes a batch through another line's merge of it — vps1-dgo against batch 34, whose
  # first parent is the Mac's merge of c89acf4f, stopped on two files dgo-stable had carried (2026-11-10).
  # HEAD..target, not base..target: it leaves out what is behind EVERY merge base, so in a criss-cross history the
  # office's own past behind a second base is still its own (the second reader).
  for c in $(git --literal-pathspecs log --full-history --format=%H -n 500 "HEAD..$2" -- "$1"); do
    [ "$(git --literal-pathspecs ls-tree "${c}" -- "$1" | cut -f1 | awk '{print $1, $3}')" = "${ours}" ] && return 0
  done
  return 1
}
untouched_for() {   # path → seconds since the file here last changed (a file that is gone: as long as can be)
  local m; m="$(stat -c %Y -- "${REPO_ROOT}/$1" 2>/dev/null || stat -f %m -- "${REPO_ROOT}/$1" 2>/dev/null || echo 0)"
  echo $(( $(date +%s) - m ))
}
here_carried() {   # path target → 0 when the file's text HERE (not HEAD's) is the target's own text for it
  # The target's CURRENT text only: an earlier version it held, kept here and merged three ways, could bring back
  # what the target has since removed, with no conflict to stop it (second reader).
  local blob
  [ "$1" = platform.state.yaml ] && return 1
  [ -f "${REPO_ROOT}/$1" ] || return 1
  blob="$(git hash-object -- "$1" 2>/dev/null)" || return 1
  [ "$(git rev-parse -q --verify "$2:$1" 2>/dev/null)" = "${blob}" ]
}
left_work() {   # path target → 0 when the change here is left work: a file that is here (a deletion is a session's call
  # to make) and named plainly (git quotes a name with a quote, a backslash or a control character), untouched
  # for KEEP_AFTER — the cheap look first — or holding the target's own text
  case "$1" in \"*) return 1 ;; esac
  [ -e "${REPO_ROOT}/$1" ] || [ -L "${REPO_ROOT}/$1" ] || return 1
  [ "$(untouched_for "$1")" -ge "${KEEP_AFTER}" ] || here_carried "$1" "$2"
}
settle_carried() {   # target conflicts(newline list) → 0 when every conflict was carried content — or this office's own
  # platform.state.yaml (keep_own_state) — resolved and committed
  local tgt="$1" p state="" rest
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    if [ "${p}" = platform.state.yaml ]; then state=1; continue; fi
    carried "${p}" "${tgt}" || return 1
  done <<<"$2"
  rest="$(grep -vFx platform.state.yaml <<<"$2" | sed '/^$/d' || true)"
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    if git cat-file -e "${tgt}:${p}" 2>/dev/null; then git --literal-pathspecs checkout -q "${tgt}" -- "${p}" || return 1
    else git --literal-pathspecs rm -q -- "${p}" || return 1; fi   # DGO_FOLLOW removed it; the office's copy was carried
  done <<<"${rest}"
  [ -z "${state}" ] || keep_own_state || return 1
  # the message in steps: an apostrophe inside "${x:+…}" opens a quote in bash, and broke the whole file once
  local msg="follow: take ${FOLLOW} $(short "${tgt}") into ${BRANCH} (${GATES} green)"
  [ -z "${rest}" ] || msg="${msg}; content ${FOLLOW} itself carried, its versions taken: $(tr '\n' ' ' <<<"${rest}")"
  [ -z "${state}" ] || msg="${msg}; platform.state.yaml conflicted, this office's own kept"
  git commit -q -m "${msg}" || return 1
  # …and what was resolved stays the checkout owner's: the post-commit hook gives back only what differs from the first
  # parent, and a path resolved to this office's own version does not (the second reader: a root-owned
  # platform.state.yaml refused the next `bbox apps enable` on the HP and the Dell)
  printf '%s\n' "$2" | sed '/^$/d' | tr '\n' '\0' | bash "${REPO_ROOT}/scripts/checkout-owner.sh" restore 2>/dev/null || true
  [ -z "${rest}" ] || say "the take's conflicts were content ${FOLLOW} itself had carried: $(tr '\n' ' ' <<<"${rest}")— its versions taken"
  if [ -n "${state}" ]; then
    say "platform.state.yaml conflicted with ${FOLLOW}: this office's own kept, whole"
    # told, in a row of its own: a version whose code needs a change of its state would run on the state before it
    post_notice warning "platform.state.yaml של ${FOLLOW} לא נלקח — ${OFFICE}" "Taking ${FOLLOW} $(short "${tgt}") into ${BRANCH}, platform.state.yaml conflicted: this office's own was kept, whole, and ${FOLLOW}'s changes to it were not taken (git diff ${BRANCH} $(short "${tgt}") -- platform.state.yaml). A session looks when the version needs them." "state:${OFFICE}:$(short "${tgt}")" || true
  fi
}

# THIS OFFICE'S OWN STATE, ON A CONFLICT (the king, 2026-11-20, DGO-2123). dgo-stable has held other offices'
# platform.state.yaml (carried(), above), and the take by hand that met a conflict there kept the office's own, the
# whole file: vps1's cycle of 10:37Z stopped on batch 91 for it until the king took it by hand (ee8a0239f, whose
# platform.state.yaml is its first parent's). So in a take of DGO_FOLLOW a conflicted platform.state.yaml is this
# office's own, whole — no three-way merge, which let another office's lines that do not overlap (its sign-in binding,
# its peers, its instances) in through the conflict (this rule's second reader). What it does NOT do: a clean merge
# still brings the target's lines in, as before, guarded by the apps check alone; and the target's changes to the file
# that this conflict drops are told (settle_carried), never silent. git writes the file (G33's one writer aside).
keep_own_state() {   # mid-merge: platform.state.yaml, this office's version staged → 0; removed here → 1
  git cat-file -e :2:platform.state.yaml 2>/dev/null || return 1   # removed HERE: not this rule's to settle
  git checkout -q --ours -- platform.state.yaml && git add -- platform.state.yaml
}

take() {   # ref what — merge ref into BRANCH, run, verify, push or roll back
  local tgt what="$2" changed dirty overlap rest added present apps_before apps_after before after bad prev merged out rc conflicts
  tgt="$(git rev-parse "$1")" || return 1
  if [ "$(st_get FAILED_TARGET)" = "${tgt}" ]; then
    # A CONFLICT is the two sides together: once the office's branch has moved (someone resolved it there), the
    # same target is tried again. The HP waited for a newer dgo-stable after its own .env.ex was fixed (DGO-1299).
    if [ -z "$(st_get FAILED_HEAD)" ] || [ "$(st_get FAILED_HEAD)" = "$(git rev-parse HEAD)" ]; then
      finish waiting "${what} $(short "${tgt}") failed at $(st_get FAILED_AT); waiting for a newer one"; return 0
    fi
    say "${BRANCH} moved since ${what} $(short "${tgt}") conflicted with it: trying it again"
    st_set FAILED_TARGET "" FAILED_AT "" FAILED_HEAD ""
  fi
  changed="$(git diff --name-only --no-renames "HEAD...${tgt}")"
  dirty="$(git diff --name-only --no-renames HEAD)"
  overlap="$(printf '%s\n' "${dirty}" | grep -Fx -f <(printf '%s\n' "${changed}" | sed '/^$/d') || true)"
  rest="$(printf '%s\n' "${overlap}" | grep -vFx platform.state.yaml | sed '/^$/d' || true)"
  # LEFT WORK (DGO-1782). A merge refuses on any staged change and on a change here in a file the target changes too,
  # and this used to stop the take until a session cleared it — measured 2026-11-10: the HP had not updated itself
  # since 11-04, behind four files staged on 11-03 and 31 changed by sessions that had since died, told once and
  # silent after. Now each such file is looked at: one whose text here the target's side already holds (carried) or
  # that nobody touched for KEEP_AFTER is left work — a staged one the target does not touch is unstaged (its text
  # stays), the rest are kept in a commit of their own on BRANCH before the merge (a conflict then goes the way every
  # conflict goes, carried content settled). A file touched more recently may be a session at work: refused, as before.
  # Only for a take of FOLLOW: a take of the office's own branch is a fast-forward, and a commit of ours under it
  # would split the branch for good (second reader). An index left mid-conflict is never kept: its markers would be.
  local keep="" unstage="" fresh_staged="" fresh_rest="" p mine=1
  [ "${what}" = "${FOLLOW}" ] && [ -z "$(git ls-files -u | head -1)" ] || mine=0
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    if [ "${mine}" = 1 ] && left_work "${p}" "${tgt}"; then keep+="${p}"$'\n'; else fresh_rest+="${p}"$'\n'; fi
  done <<<"${rest}"
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    grep -qFx -- "${p}" <<<"${rest}" && continue                       # in the commit above
    [ "${p}" = platform.state.yaml ] && grep -qFx platform.state.yaml <<<"${overlap}" && continue   # its own commit below
    if [ "${mine}" = 1 ] && left_work "${p}" "${tgt}"; then unstage+="${p}"$'\n'; else fresh_staged+="${p}"$'\n'; fi
  done <<<"$(git diff --cached --name-only --no-renames)"
  # refused before anything moves: these are the office's side, never the target's fault (no FAILED_TARGET)
  if [ -n "${fresh_staged}" ]; then
    tell "לא ניתן לעדכן: שינויים מוכנים לקומיט — ${OFFICE}" "The index of ${BRANCH} holds staged changes ($(head -5 <<<"${fresh_staged}" | tr '\n' ' ')), touched within $((KEEP_AFTER / 3600)) h; a merge would refuse. Commit or unstage them; nothing was merged."
    finish blocked "staged changes in the checkout"; return 1
  fi
  if [ -n "${fresh_rest}" ]; then
    fresh_rest="$(sed '/^$/d' <<<"${fresh_rest}")"
    tell "לא ניתן לעדכן: שינויים מקומיים בקבצים שהעדכון משנה — ${OFFICE}" "Uncommitted changes here in: ${fresh_rest//$'\n'/ } — ${what} $(short "${tgt}") changes them too, and they were touched within $((KEEP_AFTER / 3600)) h. Commit or drop them on ${BRANCH}; nothing was merged."
    finish blocked "local changes in ${fresh_rest//$'\n'/ }"; return 1
  fi
  keep="$(sed '/^$/d' <<<"${keep}")"; unstage="$(sed '/^$/d' <<<"${unstage}")"
  added="$(git diff --name-only --no-renames --diff-filter=A "HEAD...${tgt}")"
  # on disk and NOT tracked here (a file the office already has through a cherry-pick merges cleanly). One that holds
  # the VERY bytes and mode the take adds is nobody's other work: it is kept as left work in the commit below, and the
  # merge then adds nothing over it — measured 2026-11-12, the Dell refused 45 for 21 such files (an app copied in by
  # hand before the line carried it); a file that differs, a link or an ignored one still refuses (DGO-1838).
  local same="" f mode want filemode
  filemode="$(git config --type=bool core.fileMode 2>/dev/null || echo true)"
  present=""
  while IFS= read -r f; do
    [ -n "${f}" ] || continue
    git cat-file -e "HEAD:${f}" 2>/dev/null && continue
    [ -e "${REPO_ROOT}/${f}" ] || [ -L "${REPO_ROOT}/${f}" ] || continue
    # git's own word that it is a plain untracked file by that exact name: not ignored, not under a symlinked
    # directory, not another case of the name on a case-insensitive disk (second reader)
    if [ "${mine}" = 1 ] && [ ! -L "${REPO_ROOT}/${f}" ] \
       && [ "$(git --literal-pathspecs ls-files -o --exclude-standard -- "${f}")" = "${f}" ] \
       && here_carried "${f}" "${tgt}"; then
      # the mode git will STAGE: 100755 only where it keeps modes and the owner may execute (WSL/9p: always 100644)
      want=100644
      [ "${filemode}" != false ] && [ -n "$(find "${REPO_ROOT}/${f}" -maxdepth 0 -perm -u+x 2>/dev/null)" ] && want=100755
      mode="$(git ls-tree "${tgt}" -- "${f}" | cut -d' ' -f1)"
      if [ "${mode}" = "${want}" ]; then same+="${f}"$'\n'; continue; fi
    fi
    present+="${f} "
  done <<<"${added}"
  keep="$(printf '%s\n%s' "${keep}" "${same}" | sed '/^$/d' | awk '!s[$0]++')"
  if [ -n "${present}" ]; then
    tell "לא ניתן לעדכן: קבצים מקומיים במקום שהעדכון מוסיף — ${OFFICE}" "${what} $(short "${tgt}") adds ${present}which already exist here, untracked or ignored. Move them away; nothing was merged."
    finish blocked "files already where the take adds them: ${present}"; return 1
  fi
  # an app in use right now (a meeting) is not recreated under its people: the next cycle tries again
  local busy; busy="$(take_busy)"
  if [ -n "${busy}" ]; then finish skipped "busy — ${busy//$'\n'/; }"; return 0; fi
  if [ "${DRY}" = 1 ]; then
    say "would take ${what} $(short "${tgt}") into ${BRANCH} at $(short HEAD): $(git rev-list --count "HEAD..${tgt}") commit(s), $(printf '%s\n' "${changed}" | sed '/^$/d' | wc -l | tr -d ' ') file(s)"
    grep -qFx platform.state.yaml <<<"${overlap}" && say "would first commit this office's own platform.state.yaml on ${BRANCH}"
    [ -n "${unstage}" ] && say "would unstage left work the take does not touch (its text stays): ${unstage//$'\n'/ }"
    [ -n "${keep}" ] && say "would keep left work in a commit on ${BRANCH} first: ${keep//$'\n'/ }"
    say "then: bbox run, every healthy service compared ($(services | good_names | wc -l | tr -d ' ') healthy now), push or roll back"
    return 0
  fi
  room || return 0
  # every check above has passed, so this take will run: a CI job on the slot is asked to make room now (want_gap)
  if [ -n "${CI_ON_SLOT}" ]; then
    want_gap || { finish skipped "a heavy job holds the slot: ${CI_ON_SLOT%% |*} — ${GAP_WHY}"; return 0; }
  fi
  before="$(settle)" || { finish skipped "the services cannot be read before the take"; return 0; }
  # with the services: the take's line names what the checkout switched from here (an app switched off just before,
  # its containers still being stopped, is lost()'s: off by the owner's word)
  APPS_START="$(checkout_apps)" || APPS_START="?"
  MODEL_START="$(model_services)" || MODEL_START=""   # what an app switched off just before had already left
  SWITCHED=""
  # asked again: the baseline may have waited minutes, and a meeting may have begun in them — seconds before the merge
  busy="$(take_busy)"
  if [ -n "${busy}" ]; then finish skipped "busy — ${busy//$'\n'/; }"; return 0; fi
  export GIT_AUTHOR_NAME="dgo-follow (${OFFICE})" GIT_COMMITTER_NAME="dgo-follow (${OFFICE})"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo "follow@${OFFICE}.invalid")}"
  export GIT_COMMITTER_EMAIL="${GIT_AUTHOR_EMAIL}"
  if grep -qFx platform.state.yaml <<<"${overlap}"; then
    git commit -q -m "follow: ${OFFICE}'s own platform state, before taking ${what} $(short "${tgt}")" \
      -- platform.state.yaml || { finish blocked "could not commit platform.state.yaml"; return 1; }
  fi
  if [ -n "${unstage}${keep}" ]; then
    # asked again: the services may have taken minutes to settle, and a session may have come back to one of them
    while IFS= read -r p; do
      [ -n "${p}" ] || continue
      left_work "${p}" "${tgt}" || { finish skipped "${p} was touched again while the take waited"; return 0; }
    done <<<"${unstage}"$'\n'"${keep}"
    local -a paths
    if [ -n "${unstage}" ]; then
      mapfile -t paths <<<"${unstage}"
      git --literal-pathspecs reset -q -- "${paths[@]}" 2>/dev/null \
        || { finish blocked "could not unstage the left work: ${unstage//$'\n'/ }"; return 1; }
      say "unstaged left work the take does not touch (its text stays): ${unstage//$'\n'/ }"
    fi
    if [ -n "${keep}" ]; then
      mapfile -t paths <<<"${keep}"
      # the commit names its paths: whatever else a session staged meanwhile stays out of it (second reader)
      git --literal-pathspecs add -A -- "${paths[@]}" \
        && git --literal-pathspecs commit -q -o -m "follow: the work left uncommitted on ${OFFICE} — carried by ${FOLLOW} or untouched for $((KEEP_AFTER / 3600)) h or more — kept before taking ${what} $(short "${tgt}"): ${keep//$'\n'/ }" -- "${paths[@]}" \
        || { finish blocked "could not keep the left work in a commit: ${keep//$'\n'/ }"; return 1; }
      say "kept left work in $(short HEAD) on ${BRANCH}: ${keep//$'\n'/ }"
      post_notice warning "שמרתי עבודה שנשארה לא מקומטת — ${OFFICE}" \
        "$(wc -l <<<"${keep}" | tr -d ' ') file(s) changed here and left (carried by ${FOLLOW}, or untouched for $((KEEP_AFTER / 3600)) h or more) were kept in commit $(short HEAD) on ${BRANCH} before taking ${what} $(short "${tgt}"): ${keep//$'\n'/ }. Nothing was lost; a session can look at them there." \
        "kept:${OFFICE}:$(short HEAD)" || true
    fi
  fi
  prev="$(git rev-parse HEAD)"
  # recorded BEFORE the merge: a cycle killed from here on is settled by the next one (recover)
  st_set TAKING "${prev} ${tgt}" TAKING_WHAT "${what}" MERGED "" VERIFIED "" BEFORE "$(printf '%s' "${before}" | tr '\n' ';')"
  if ! out="$(git merge -q --no-edit -m "follow: take ${what} $(short "${tgt}") into ${BRANCH} (${GATES} green)" "${tgt}" 2>&1)" \
     && ! { conflicts="$(git diff --name-only --diff-filter=U)"; [ -n "${conflicts}" ] && [ "${what}" = "${FOLLOW}" ] \
            && settle_carried "${tgt}" "${conflicts}"; }; then
    local files gd; files="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"; gd="$(git rev-parse --absolute-git-dir)"
    # every path resolved and then the commit failed: still the conflicts, not "refused before it started"
    [ -n "${files}" ] || files="$(tr '\n' ' ' <<<"${conflicts:-}" | sed 's/^ *$//')"
    if [ -e "${gd}/MERGE_HEAD" ] && ! merge_abort 2>/dev/null; then
      tell "עדכון נתקע באמצע מיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} conflicted${files:+ in ${files}}, and \`git merge --abort\` failed: the checkout is mid-merge. A session must finish or abort it, then run \`bbox follow clear\`."
      finish blocked "mid-merge, abort failed"; return 1
    fi
    st_set TAKING "" MERGED "" BEFORE ""
    if [ -n "${files}" ]; then
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD "${prev}"
      # no HEAD in the text: tell() says a text once, and a retry after an unrelated commit is the same conflict
      tell "לא ניתן לעדכן: התנגשות במיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} conflicts in ${files}— aborted; ${BRANCH} is unchanged. A session must merge it by hand."
      finish failed "merge of $(short "${tgt}") conflicts in ${files}"; return 1
    fi
    tell "לא ניתן לעדכן: git סירב למיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} was refused before it started: $(printf '%s' "${out}" | head -3 | tr '\n' ' ') Nothing was merged."
    finish blocked "merge refused: $(printf '%s' "${out}" | head -1)"; return 1
  fi
  merged="$(git rev-parse HEAD)"; st_set MERGED "${merged}"
  # Another office's state, merged into dgo-stable, must not decide which apps run HERE. (The office's own branch, taken
  # from origin, IS this office's decision: not checked.)
  TAKE_PREV="${prev}" TAKE_MERGED="${merged}" TAKE_APPS_MOVED=0
  # An office's own state file (untracked) is one file, not two revisions: it is read once, so a write between two
  # reads is never taken for a move (DGO-2015's second reader).
  local read_ok
  if own_state; then
    apps_before="$(declared_apps "${merged}")"; read_ok=$?; apps_after="${apps_before}"
  else
    apps_before="$(declared_apps "${prev}")" && apps_after="$(declared_apps "${merged}")"; read_ok=$?
  fi
  if [ "${read_ok}" != 0 ]; then
    reset_keep "${prev}" 2>/dev/null || { finish failed "the declared apps cannot be read, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE ""
    if [ -n "$(declared_apps "${prev}")" ]; then   # ours reads, the merged one does not: the target's fault, not retried
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
      tell "לא ניתן לעדכן: platform.state.yaml שבור אחרי המיזוג — ${OFFICE}" "Merged with ${what} $(short "${tgt}"), platform.state.yaml cannot be parsed. Nothing ran; ${BRANCH} is back at $(short "${prev}"). A session must merge it by hand."
      finish failed "platform.state.yaml unreadable after merging $(short "${tgt}")"; return 1
    fi
    finish skipped "the apps platform.state.yaml declares cannot be read (the file, or python3 + yaml) — nothing ran"; return 0
  fi
  [ "${apps_after}" = "${apps_before}" ] || TAKE_APPS_MOVED=1
  if [ "${what}" = "${FOLLOW}" ] && [ "${TAKE_APPS_MOVED}" = 1 ]; then
    local plus minus
    plus="$(comm -13 <(printf '%s\n' "${apps_before}") <(printf '%s\n' "${apps_after}") | tr '\n' ' ')"
    minus="$(comm -23 <(printf '%s\n' "${apps_before}") <(printf '%s\n' "${apps_after}") | tr '\n' ' ')"
    reset_keep "${prev}" 2>/dev/null || { finish failed "the apps would change, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
    tell "לא ניתן לעדכן: העדכון משנה אילו אפליקציות רצות כאן — ${OFFICE}" "${what} $(short "${tgt}") would change which apps this office runs (${plus:+on: ${plus}}${minus:+off: ${minus}}). That is this office's decision, not a merge's: nothing ran, ${BRANCH} is back at $(short "${prev}"). A session must take it by hand."
    finish blocked "the take would change the enabled apps (${plus:+on: ${plus}}${minus:+off: ${minus}})"; return 1
  fi
  say "took ${what} $(short "${tgt}") into ${BRANCH} — bringing the office up on it"
  local took_at; took_at="$(date +%s)"   # a container started from here on runs the take's code (folders_changed)
  # ready-made images (images_pull): pulled, and the rest built — then the run builds nothing again; else as always
  rc=0
  if images_pull "${tgt}"; then BBOX_PREBUILT=1 office_run take || rc=$?; else office_run take || rc=$?; fi
  if after="$(settle)"; then note_switched; bad="$(lost "${before}" "${after}")"; else bad="the services cannot be read"; fi
  [ "${rc}" = 0 ] || bad="${bad:+${bad}$'\n'}bbox run exited ${rc}"
  if [ -n "${bad}" ]; then
    rollback "${prev}" "${merged}" "${tgt}" "${bad//$'\n'/, }${SWITCHED:+; switched during the take: ${SWITCHED//$'\n'/, }}"
    return 1
  fi
  st_set VERIFIED "${merged}"     # healthy: what recover() trusts, origin's ref being no proof for an own-branch take
  # WHAT WAS MERGED IS WHAT RUNS (DGO-1356). A service whose image is older than its own build files runs the code
  # from before the take: measured 2026-11-05 on the Dell, dgo-extend and dgo-carry ran images from before the relay
  # its checkout had held for three days, so the relay line in its .env did nothing. Exactly those are built again;
  # a build that fails is said. The take stands either way: its code is merged and the office is healthy.
  local old rebuilt=1 s; old="$(old_images 2>/dev/null)" || old=""
  # …but not one the bring-up held while its app was at work: its note carries the build, and held_retry makes it at a
  # quiet cycle (DGO-2129). Built here, it would only be held once more, after a build that waits on nobody.
  if [ -n "${old}" ] && [ -d "${REPO_ROOT}/data/.held" ]; then
    old="$(for s in ${old}; do [ -e "${REPO_ROOT}/data/.held/${s}" ] || printf '%s ' "${s}"; done)"; old="${old% }"
  fi
  if [ -n "${old}" ]; then
    say "images older than their sources after the take: ${old} — building exactly these"
    # shellcheck disable=SC2086
    if office_rebuild ${old}; then
      svc_drop images ${old}   # a rebuild that worked: what an earlier one left on the old code is current now
    else
      tell_svc "שירותים רצים על קוד ישן אחרי עדכון — ${OFFICE}" "After taking ${what} $(short "${tgt}"), ${old} run images older than their sources and building them again failed (data/follow/run-*-rebuild.log): the code is merged, and those services run the code from before it. A later take that rebuilds them closes this; once put right by hand: bbox follow clear services." images ${old} && rebuilt=0
    fi
  fi
  # …and a service whose read-only FOLDER mount holds a file the merge changed, still running what it loaded before the
  # take (folders_changed). Its recreate is the first time the merged code runs, so it is judged like the bring-up (F3):
  # settle + lost against the services before the take — a loss or a failed recreate is said, and the take's own line
  # waits, as for a failed rebuild. The take stands: its code is merged, and going back would not undo a recreate.
  local folded fl_svc bad_after
  local -a fl=()
  if ! folded="$(folders_changed "${prev}" "${merged}" "${took_at}")"; then
    # nothing to keep for a retry (the services are unknown), and the next cycle finds HEAD at the target: said, once
    # …on the services' row: the «green is in the branch» path re-checks nothing, so it must not close it (its reader)
    tell_svc "לא נבדקו שירותים שהקוד שלהם מותקן כתיקייה — ${OFFICE}" "After taking ${what} $(short "${tgt}"), the services whose code is mounted as a folder could not be checked (data/follow/log): one may run the code from before the take. A session must look, and then: bbox follow clear services." unchecked "$(short "${tgt}")" && rebuilt=0
    folded=""   # whatever a failed check printed is no list to recreate (as before: this branch recreated nothing)
  fi   # (a later take's check that runs is no answer to this one: it reads its own diff — the third reader)
  if [ -n "${folded}" ]; then
    while IFS= read -r fl_svc; do [ -n "${fl_svc}" ] && fl+=("${fl_svc}"); done <<<"${folded}"
    folders_refresh "${took_at}" "${fl[@]}" \
      || { tell_svc "שירות רץ על קוד ישן אחרי עדכון — ${OFFICE}" "After taking ${what} $(short "${tgt}"), recreating the services whose code is mounted as a folder the take changed failed (data/follow/run-*-recreate.log): they run the code from before it; the next cycle tries again." folders $(printf '%s\n' "${fl[@]}" | awk '{print $1}') && rebuilt=0; }
    if after="$(settle)"; then note_switched; bad_after="$(lost "${before}" "${after}")"; else bad_after="the services cannot be read"; fi
    local fell_after; fell_after="$(printf '%s\n' "${fl[@]}" | awk '{print $1}')"
    [ "${bad_after}" = "the services cannot be read" ] || fell_after="$(awk '{print $1}' <<<"${bad_after}")"
    # shellcheck disable=SC2086 — the names, one word each
    [ -z "${bad_after}" ] \
      || { tell_svc "שירות נפל אחרי עדכון — ${OFFICE}" "After taking ${what} $(short "${tgt}"), recreating the services whose code is mounted as a folder the take changed left: ${bad_after//$'\n'/, }. The take is merged; a session must look." fell ${fell_after} && rebuilt=0; }
  fi
  if [ "$(git rev-parse HEAD)" != "${merged}" ]; then moved_on_top "${tgt}"; return 1; fi
  local held=""; [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "${merged}" ] && held=1
  # the merge itself, not HEAD: a commit landing between the check above and the push is never pushed unchecked
  if push_branch "${merged}"; then
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING ""
    finish took "${what} $(short "${tgt}") into ${BRANCH} at $(short HEAD), healthy, $([ -n "${held}" ] && echo "origin's own commit (nothing to push)" || echo pushed)${VIA_USED:+, through ${VIA_USED}}${SWITCHED:+; switched during the take: ${SWITCHED//$'\n'/, }}"
    [ "${rebuilt}" = 0 ] || told_took "${what}" "${tgt}"   # a failed rebuild's row names the take, and stays open
  else
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING "${merged}"
    finish took "${what} $(short "${tgt}") into ${BRANCH}, healthy — the push${VIA_USED:+ through ${VIA_USED}} was refused, the next cycle pushes again${SWITCHED:+; switched during the take: ${SWITCHED//$'\n'/, }}"
    tell "המשרד עודכן אבל הענף לא נדחף — ${OFFICE}" "${BRANCH} took ${what} $(short "${tgt}") and is healthy, but pushing it${VIA_USED:+ through ${VIA_USED}} was refused; the next cycle pushes again."
  fi
  # What the take's builds replaced is given back now, not the day the disk is full (DGO-1393): the dangling images —
  # never a tagged image, a volume or a container; the build cache keeps its weekly prune (scripts/dc). After the push
  # and the bookkeeping, so a cycle stopped in the middle of it leaves no open take for the next one to roll back.
  office_disk reclaim
  return 0
}

recover() {   # an open take from a cycle that did not finish → 0 to go on, 1 when this cycle must stop here
  local taking prev tgt merged head
  taking="$(st_get TAKING)"; [ -n "${taking}" ] || return 0
  prev="${taking%% *}"; tgt="${taking#* }"; merged="$(st_get MERGED)"; head="$(git rev-parse HEAD)"
  # killed in the instant between the merge landing and MERGED being written: HEAD is the fast-forward to tgt, or a
  # merge whose parents are prev and tgt (never just "a commit on prev": that may be a session's, and is not ours)
  if [ -z "${merged}" ] && [ "${head}" != "${prev}" ] \
     && { [ "${head}" = "${tgt}" ] || { [ "$(git rev-parse -q --verify "${head}^1")" = "${prev}" ] \
                                         && [ "$(git rev-parse -q --verify "${head}^2")" = "${tgt}" ]; }; }; then
    merged="${head}"
  fi
  if [ -n "${merged}" ] && [ "${head}" = "${merged}" ]; then
    # verified by an earlier cycle — unless that take had already failed. Origin's branch at the merge proves it only
    # for a take of FOLLOW (that merge reaches origin only by the push of a verified take); a take of the office's own
    # branch IS origin's commit from the start (a fast-forward), so a cycle killed in its `bbox run` would read as
    # verified — the client office on the public release takes nothing else (DGO-1819): VERIFIED, written once healthy.
    if [ -z "$(st_get WHY)" ] && { [ "$(st_get VERIFIED)" = "${merged}" ] \
         || { [ "$(st_get TAKING_WHAT)" = "${FOLLOW}" ] && [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "${merged}" ]; }; }; then
      # verified; only the bookkeeping was lost — and the push too, when the cycle was killed in it: then it is
      # pending, and the next cycle pushes it (the second reader of DGO-1819)
      local pend=""; [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "${merged}" ] || pend="${merged}"
      st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING "${pend}"
      finish took "$(short "${tgt}") into ${BRANCH} (verified by an earlier cycle$([ -n "${pend}" ] && echo ", its push pending"))"
      # …and so was its line: told now, by what the take was (an own-branch take never is)
      told_took "$(st_get TAKING_WHAT)" "${tgt}"
      return 1
    fi
    local why; why="$(st_get WHY)"
    rollback "${prev}" "${merged}" "${tgt}" "${why:-the cycle that took it was stopped before its health check finished}"
    return 1
  fi
  if [ "${head}" = "${prev}" ]; then
    if [ -n "${merged}" ]; then   # rolled back, then stopped before the run: run it, so the office matches its files
      local why rc=0; why="$(st_get WHY)"
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
      office_run rollback || rc=$?
      st_set TAKING "" MERGED "" BEFORE "" WHY ""
      tell "עדכון ${FOLLOW} נכשל והוחזר — ${OFFICE}" "$(short "${tgt}") left the office unhealthy (${why:-its take was stopped before it was verified}), so ${BRANCH} is back at $(short "${prev}") (bbox run exit ${rc}). It is not taken again until a newer one is green. Logs: data/follow/."
      finish failed "$(short "${tgt}") rolled back by an earlier cycle; the office was brought up on $(short "${prev}") again"
      return 1
    fi
    st_set TAKING "" MERGED "" BEFORE "" WHY ""
    return 0                      # stopped before the merge landed: nothing to settle
  fi
  if [ -n "${merged}" ] && git merge-base --is-ancestor "${merged}" HEAD; then moved_on_top "${tgt}"; return 1; fi
  st_set TAKING "" MERGED "" BEFORE "" WHY ""   # someone reset it away by hand: nothing of it is left to settle
  return 0
}

# ── a take gets its gap (DGO-2164) ───────────────────────────────────────────────────────────────
# One heavy job at a time on a machine (lib.sh heavy_admit). On an office that runs the CI runner, its jobs hold that
# slot one after another while the line moves, and a cycle that only skipped on a held slot took only when its minute
# fell between two jobs. The Dell's one take by itself since 11-13 needed its runner paused by hand (04:01–04:45Z), and
# on 11-22 four of its cycles in a row met a job there. So a cycle that finds a CI job on the slot still reads the line
# (CI_ON_SLOT). take(), once every check of its own has passed, asks the runner to stand aside: it holds the lock
# heavy.want, which the runner's agent honours between jobs (apps/ci-runner/agent.sh). The job running finishes, the
# next ones wait on GitHub, and the owner's own pause is never touched. take() waits, bounded, until the runner says
# its listener stopped, the slot is free and the load has settled. ONE process holds the lock and ends with this cycle
# (`tail --pid`), so the kernel lets go of it however the cycle ends, a kill included, and nothing the take starts
# inherits it. The second reader of a first version found the flaws this one is built against (on DGO-2164).
GAP_WAIT="${DGO_FOLLOW_GAP_WAIT_S:-3600}"     # the longest wait for the running job: a proof takes ~15 min, a leg ~8
GAP_SETTLE="${DGO_FOLLOW_GAP_SETTLE_S:-300}"  # …and for the load the job leaves behind to fall under MAX_LOAD
GAP_POLL="${DGO_FOLLOW_GAP_POLL_S:-15}"
for _g in GAP_WAIT GAP_SETTLE GAP_POLL; do    # 1–99999 s, or the default, said: a 0 poll would spin
  case "${!_g}" in ''|*[!0-9]*|0*|??????*)
    warn "DGO_FOLLOW_${_g}_S=${!_g} is not 1–99999 seconds — the default applies"
    case "${_g}" in GAP_WAIT) GAP_WAIT=3600 ;; GAP_SETTLE) GAP_SETTLE=300 ;; GAP_POLL) GAP_POLL=15 ;; esac ;;
  esac
done
CI_ON_SLOT=""                                 # the CI job's holder line, when this cycle met one on the slot
WANT_LOCK="${REPO_ROOT}/data/.locks/heavy.want"
WANT_HOLDER="" GAP_WHY=""
over_load() {   # 0 when the 1-minute load is over MAX_LOAD (the CPU count when it is not declared)
  local cpus load
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  load="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)"
  awk -v l="${load}" -v c="${cpus}" -v m="${MAX_LOAD}" 'BEGIN {exit !(l > (m == "" ? c : m))}'
}
runner_listening() {   # «false» once the runner's listener is stopped (no job can start); «true»; or «» unread
  "${DGO_FOLLOW_BBOX:-${REPO_ROOT}/bbox}" ci-runner status --json 2>/dev/null | python3 -c 'import json, sys
d = json.load(sys.stdin).get("data") or {}
print("true" if d.get("listener") else "false")' 2>/dev/null
}
want_release() { [ -z "${WANT_HOLDER}" ] || kill "${WANT_HOLDER}" 2>/dev/null; WANT_HOLDER=""; }
want_gap() {   # → 0 once the runner stands aside, the slot is free and the load settled; 1 to skip (GAP_WHY)
  local waited=0 settled=0 heard unread=0
  mkdir -p "${REPO_ROOT}/data/.locks" || { GAP_WHY="no locks folder"; return 1; }
  # created writable by anyone (umask 0): a cycle as root must not leave a lock a cycle as the office's user cannot open
  bash -c 'umask 0; exec 9>>"$1" || exit 1; flock -w 5 9 || exit 1; exec tail --pid="$2" -f /dev/null' _ "${WANT_LOCK}" "$$" &
  WANT_HOLDER=$!
  say "a take is due and a CI job holds the slot (${CI_ON_SLOT%% |*}): the runner is asked to stand aside"
  while :; do
    kill -0 "${WANT_HOLDER}" 2>/dev/null || { WANT_HOLDER=""; GAP_WHY="the want lock could not be held"; return 1; }
    heard="$(runner_listening)"
    # a runner whose status cannot be read four times running (its app restarting, an answer that is not its JSON)
    # is not waited on for the hour: the lock is let go at once, and the next cycle asks again (the second reader)
    if [ -z "${heard}" ]; then unread=$((unread + 1)); else unread=0; fi
    [ "${unread}" -lt 4 ] || { want_release; GAP_WHY="the runner's status could not be read"; return 1; }
    [ "${heard}" = false ] && [ "$(heavy_slot_status)" = free ] && break
    [ "${waited}" -lt "${GAP_WAIT}" ] || { want_release; GAP_WHY="no gap within ${GAP_WAIT}s"; return 1; }
    sleep "${GAP_POLL}"; waited=$((waited + GAP_POLL))
  done
  while over_load; do
    [ "${settled}" -lt "${GAP_SETTLE}" ] || { want_release; GAP_WHY="the load stayed over its ceiling ${settled}s after the job"; return 1; }
    sleep "${GAP_POLL}"; settled=$((settled + GAP_POLL))
  done
  say "the runner stands aside and the slot is free after ${waited}s (the load settled in ${settled}s) — the take goes on"
  return 0
}

# ── one cycle ─────────────────────────────────────────────────────────────────────────────────────
cycle() {
  local cpus load gd green target slot
  if [ "${DRY}" != 1 ]; then
    # under a heavy job the heal waits for the next trigger or cycle — said, since not every heavy job runs an `up`
    if [ "$(heavy_slot_status)" = free ]; then office_heal; else say "the heal is put off: a heavy job holds the slot"; fi
  fi
  [ "${HEAL}" = 0 ] || return 0
  # The services' row (tell_svc) closes only when a cycle finds its causes gone — never by all_clear. Asked FIRST, so it
  # judges what earlier cycles said, never what this one is about to say (a service that fell this minute reads
  # «running» between two restarts); and before «DGO_FOLLOW is empty», so an office that stopped following can close it.
  [ "${DRY}" = 1 ] || svc_clear
  [ -n "${FOLLOW}" ] || { say "DGO_FOLLOW is empty — this office does not follow"; return 0; }
  [ -n "${BRANCH}" ] || { tell "לא ניתן לעקוב: DGO_BRANCH ריק — ${OFFICE}" "DGO_FOLLOW=${FOLLOW} is declared, but the office's own branch (DGO_BRANCH) is not: nothing is merged without it."; return 1; }
  mkdir -p "${REPO_ROOT}/data/.locks" "${STATE_DIR}" || return 1
  # A CI job on the slot: the cycle still reads the line, and a take asks the runner to stand aside (want_gap) —
  # unless a take is open (recover() may need the slot). Anything else on the slot (a build, a recreate, a take) is
  # waited out, as before.
  slot="$(heavy_slot_status)"
  if [ "${slot}" != free ]; then
    case "${slot}" in "ci "*) [ "${DRY}" = 1 ] || [ -n "$(st_get TAKING)" ] || CI_ON_SLOT="${slot}" ;; esac
    [ -n "${CI_ON_SLOT}" ] || { finish skipped "a heavy job holds the slot: ${slot}"; return 0; }
  fi
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  load="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)"
  # …a CI job's load is that job's own: want_gap waits for it to settle before a take
  if [ -z "${CI_ON_SLOT}" ] && awk -v l="${load}" -v c="${cpus}" -v m="${MAX_LOAD}" 'BEGIN {exit !(l > (m == "" ? c : m))}'; then
    finish skipped "load ${load} on ${cpus} CPU(s)"; return 0
  fi
  [ "$(git rev-parse --abbrev-ref HEAD)" = "${BRANCH}" ] \
    || { tell "לא ניתן לעקוב: המשרד לא על הענף שלו — ${OFFICE}" "The checkout is on $(git rev-parse --abbrev-ref HEAD), not ${BRANCH} (DGO_BRANCH). Nothing was merged."; finish blocked "not on ${BRANCH}"; return 1; }
  gd="$(git rev-parse --absolute-git-dir)"
  # a merge OUR open take left mid-way (the cycle killed between its conflicted merge and the carried commit) is ours to
  # abort, so recover() can settle the take; any other merge in flight is someone else's
  if [ "${DRY}" != 1 ] && [ -e "${gd}/MERGE_HEAD" ] && [ -n "$(st_get TAKING)" ] \
     && [ "$(head -1 "${gd}/MERGE_HEAD")" = "$(st_get TAKING | cut -d' ' -f2)" ]; then
    merge_abort 2>/dev/null && say "aborted the merge an earlier cycle left mid-way (its open take)"
  fi
  if [ -e "${gd}/MERGE_HEAD" ] || [ -d "${gd}/rebase-merge" ] || [ -d "${gd}/rebase-apply" ] || [ -e "${gd}/index.lock" ]; then
    finish skipped "a merge, rebase or git command is in flight in the checkout"; return 0
  fi
  # a folder-mounted service an earlier take could not recreate (its app was busy, or the recreate failed): again now —
  # before the fetch, which it does not need (a fetch that fails would otherwise hold it back too)
  # (not under a CI job: their recreates would wait behind it for the slot; a later cycle retries them)
  [ "${DRY}" = 1 ] || [ -n "${CI_ON_SLOT}" ] || folders_retry
  [ "${DRY}" = 1 ] || [ -n "${CI_ON_SLOT}" ] || held_retry
  # a declaration to fix: an office whose own path does not start with / (`vps1:git/gh/…`) — said as that, first, so it
  # is never read as «no path of its own» below
  local e bad=""
  for e in ${_VIA_LIST[@]+"${_VIA_LIST[@]}"}; do case "${e}" in *:/*) ;; *:*) bad="${e}"; break ;; esac; done
  if [ -n "${bad}" ]; then
    tell "לא ניתן לעקוב: נתיב לא תקין ב-DGO_FOLLOW_VIA — ${OFFICE}" "DGO_FOLLOW_VIA names «${bad}»: an office's own path is <office>:/git/gh/<account>/<owner>/<repo>.git, starting with /. Nothing was fetched."
    finish blocked "DGO_FOLLOW_VIA entry ${bad}: its path must start with /"; return 1
  fi
  # …and a declaration missing (an office named without a path of its own, and no DGO_FOLLOW_VIA_PATH): no cycle fixes that
  if [ -z "${VIA_PATH}" ] && via_bare; then
    tell "לא ניתן לעקוב: DGO_FOLLOW_VIA_PATH ריק — ${OFFICE}" "DGO_FOLLOW_VIA=${VIA} is declared, but not the path of the repository on its git app (DGO_FOLLOW_VIA_PATH=/git/gh/<account>/<owner>/<repo>.git, or <office>:/git/gh/… for one office). Nothing was fetched."
    finish blocked "DGO_FOLLOW_VIA=${VIA} without DGO_FOLLOW_VIA_PATH"; return 1
  fi
  resolve_src || { finish skipped "the git app of $(via_names) cannot be reached (DGO_FOLLOW_VIA)${VIA_WHY:+ — ${VIA_WHY:0:300}}"; return 0; }
  # A fetch that fails says git's own verdict and how long it took. Without them the Dell said «fetch of dgo-stable
  # failed (through macbook)» on every cycle for nine days, and nobody could tell a pack that stopped on its way (git's
  # low-speed bound, NET_SLOW) from a refusal in its own checkout (a ref it could not lock): 11-22, its git app's door
  # handed the whole pack over (5.2 MB in 2.6 s) and the cycle still failed a minute later (DGO-2164).
  local fetch_t0 fetch_err
  fetch_t0="$(date +%s)"
  if ! fetch_err="$(git fetch -q "${SRC}" "+refs/heads/${FOLLOW}:refs/remotes/origin/${FOLLOW}" 2>&1 >/dev/null)"; then
    fetch_err="$(git_said "${fetch_err}")"
    finish skipped "fetch of ${FOLLOW} failed${VIA_USED:+ (through ${VIA_USED})} after $(( $(date +%s) - fetch_t0 )) s${fetch_err:+: ${fetch_err:0:200}}"
    return 0
  fi
  st_set LAST_VIA "${VIA_USED}"   # which office's git app served it (empty: origin itself) — `status` says, a take's line too
  git fetch -q "${SRC}" "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" 2>/dev/null || true
  [ "${DRY}" = 1 ] || recover || return 0
  # a take whose line could not be posted is told now — or, while a row is open, once that row is closed
  local waiting; waiting="$(st_get TOLD_PENDING)"
  # shellcheck disable=SC2086
  [ "${DRY}" = 1 ] || [ -z "${waiting}" ] || [ -n "$(st_get NOTICE)" ] || told_took ${waiting}

  # the office's own branch, pushed from elsewhere: a take of its own
  if git rev-parse -q --verify "refs/remotes/origin/${BRANCH}" >/dev/null && ! git merge-base --is-ancestor "origin/${BRANCH}" HEAD; then
    if git merge-base --is-ancestor HEAD "origin/${BRANCH}"; then take "origin/${BRANCH}" "origin/${BRANCH}"; return; fi
    tell "לא ניתן לעקוב: הענף של המשרד התפצל — ${OFFICE}" "${BRANCH} here and origin/${BRANCH} have each moved since they last met. A session must join them; nothing was merged."
    finish blocked "${BRANCH} diverged from origin/${BRANCH}"; return 1
  fi
  # An office that follows its OWN branch (DGO_FOLLOW = DGO_BRANCH: a client office on the public release, whose every
  # commit is a version cut after its gates) has nothing more to take than the block above took: no gates to read
  # here — or it would be «skipped» every cycle and, after a day of that, told it fell behind (DGO-1819).
  if [ "${FOLLOW}" = "${BRANCH}" ]; then
    finish current "${BRANCH} at $(short HEAD) holds origin's $(short "origin/${BRANCH}")"
    # PUSH_PENDING too: one left by a cycle from before this rule is never pushed (the office may not push)
    [ "${DRY}" = 1 ] || { st_set FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING ""; all_clear "${BRANCH} $(short HEAD) holds origin's"; }
    return 0
  fi

  green="$(green_shas)" || green=""
  [ "${DRY}" = 1 ] || line_waits
  [ -n "${green}" ] || { finish skipped "no green ${GATES} run on ${FOLLOW} could be read"; return 0; }
  target="$(git rev-list --first-parent -n 300 "origin/${FOLLOW}" | grep -Fx -f <(printf '%s\n' "${green}") | head -1)"
  [ -n "${target}" ] || { finish skipped "none of the last 300 commits of ${FOLLOW} has a green ${GATES} run"; return 0; }
  if git merge-base --is-ancestor "${target}" HEAD; then
    # a verified take whose push was refused: that merge is pushed, never HEAD (a session may have added to it since)
    local pending; pending="$(st_get PUSH_PENDING)"
    if [ -n "${pending}" ] && [ "${DRY}" != 1 ] && git merge-base --is-ancestor "${pending}" HEAD; then
      push_branch "${pending}" && st_set PUSH_PENDING ""
    fi
    finish current "${FOLLOW} green at $(short "${target}") is in ${BRANCH}"
    [ "${DRY}" = 1 ] || [ -n "$(st_get PUSH_PENDING)" ] \
      || { st_set FAILED_TARGET "" FAILED_AT "" FAILED_HEAD ""; all_clear "${FOLLOW} $(short "${target}") is in ${BRANCH}"; }
    return 0
  fi
  take "${target}" "${FOLLOW}"
}

case "${1:-}" in
  ""|--dry-run|heal)
    [ "${1:-}" = --dry-run ] && DRY=1
    [ "${1:-}" = heal ] && HEAL=1
    # One at a time. flock(1) holds the lock itself (-o: the cycle and everything it starts do not inherit it), so a
    # process a `bbox run` leaves behind cannot put off every later cycle (the reason heavy_detach exists, lib.sh).
    if [ -z "${DGO_FOLLOW_LOCKED:-}" ] && command -v flock >/dev/null 2>&1; then
      mkdir -p "${REPO_ROOT}/data/.locks" || exit 1
      DGO_FOLLOW_LOCKED=1 DGO_FOLLOW_COPY="${_COPY}" DGO_FOLLOW_HERE="${HERE}" \
        flock -n -o -E 75 "${REPO_ROOT}/data/.locks/follow" bash "${_COPY}" "$@"
      rc=$?
      [ "${rc}" = 75 ] && { say "another follow cycle is running"; exit 0; }
      exit "${rc}"
    fi
    cycle ;;
  status)  status ;;
  install) install_timer ;;
  clear)
    if [ "${2:-}" = services ]; then
      # the services' row (tell_svc), after a session put it right by hand: its causes go, and the next cycle's
      # svc_clear closes the row — and posts again until it could (a close posted here and lost would never return)
      say "follow: the services' row's causes are dropped ($(st_get SVC_CAUSES)) — the next cycle closes it"
      st_set SVC_CAUSES ""
    else
      st_set TAKING "" MERGED "" VERIFIED "" BEFORE "" WHY "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD ""
      say "follow: the open take and the failed target are forgotten — the next cycle follows ${FOLLOW:-<nothing>} again"
    fi ;;
  -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) die "usage: bbox follow [--dry-run] | heal | status | install | clear [services]" ;;
esac
